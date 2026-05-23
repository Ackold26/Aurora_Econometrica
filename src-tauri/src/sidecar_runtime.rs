//! Sidecar runtime - shared foundation для port discovery, version handshake,
//! per-user process isolation, state file management.
//!
//! **Canonical файл** для всех 10 Aurora-продуктов. Sync через sync_variants.py.
//!
//! # Архитектура
//!
//! На multi-user RDP-серверах TCP-порты - глобальный ресурс ОС. Захардкоженный
//! `:7430` → конфликт между пользователями: первый занимает, остальные переиспользуют
//! чужой sidecar → 404/500, смешивание контекстов.
//!
//! Решение:
//! 1. **Deterministic port** по хешу SID пользователя (stable, race-free).
//! 2. **Fallback на `bind(0)`** если preferred port занят (zombie от той же сессии).
//! 3. **State file** `%LOCALAPPDATA%\<identifier>\sidecar.json` - per-user gauranteed
//!    (НЕ `%APPDATA%` - тот роумит в AD-доменах).
//! 4. **Handshake `/health`** - {product, version, session_id} проверяется перед
//!    использованием. Mismatch → force kill + respawn.
//! 5. **Process owner detection** через WinAPI (OpenProcessToken + LookupAccountSidW),
//!    не `tasklist /V` - encoding hell на локализованной Windows.
//! 6. **Kill-switch** env `AURORA_SIDECAR_LEGACY_PORT=1` → bypass discovery,
//!    fallback на hardcoded port. Safety valve для прод-отката без rebuild.
//!
//! # Usage
//!
//! ```ignore
//! use crate::sidecar_runtime::{SidecarConfig, allocate_port, write_state_file};
//!
//! const CFG: SidecarConfig = SidecarConfig {
//!     product_id: "com.aurora.econometrica",
//!     version: env!("CARGO_PKG_VERSION"),
//!     legacy_port: 7430,
//!     identifier_dir: "com.aurora.econometrica",
//!     process_exe_hint: "econometrica-sidecar",
//! };
//!
//! let port = allocate_port(&CFG)?;
//! // spawn sidecar с аргументом port ...
//! write_state_file(&CFG, port, child.id(), &session_id)?;
//! ```

use std::net::TcpListener;
use std::path::PathBuf;
use std::time::Duration;

use log::{debug, info, warn};
use serde::{Deserialize, Serialize};

// ── Configuration ────────────────────────────────────────────────────────────

/// Per-product конфигурация sidecar. Задаётся как const в каждом продукте.
#[derive(Clone, Copy)]
pub struct SidecarConfig {
    /// Обратный domain ID, должен совпадать с `tauri.conf.json::identifier`.
    /// Пример: `"com.aurora.econometrica"`.
    pub product_id: &'static str,

    /// Версия продукта, читается Rust-side из `env!("CARGO_PKG_VERSION")`
    /// и передаётся в Python-sidecar через env `AURORA_PRODUCT_VERSION`.
    pub version: &'static str,

    /// Hardcoded port для legacy fallback (kill-switch) и для back-compat
    /// с pre-v1.0.9 бинарниками. Также база для user_scoped_port().
    pub legacy_port: u16,

    /// Имя поддиректории в `%LOCALAPPDATA%` для state file + logs.
    /// Пример: `"com.aurora.econometrica"`.
    pub identifier_dir: &'static str,

    /// Подстрока для определения «наш» ли процесс (case-insensitive).
    /// Пример: `"econometrica-sidecar"` или `"rag-server"`.
    pub process_exe_hint: &'static str,
}

// ── Types ────────────────────────────────────────────────────────────────────

/// Содержимое state file `%LOCALAPPDATA%\<identifier>\sidecar.json`.
/// Записывается Rust после успешного handshake на cold start.
/// Читается Rust при reconnect - если handshake подтверждает session_id,
/// переиспользуется; иначе считается stale → respawn.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SidecarState {
    pub port: u16,
    pub pid: u32,
    pub session_id: String,
    pub product: String,
    pub version: String,
    pub user: String,
    pub started_at: String,
}

/// Ответ `/health` endpoint'а. Схема расширена в v1.0.9.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthInfo {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub version: String,
    #[serde(default)]
    pub product: String,
    #[serde(default)]
    pub session_id: String,
    #[serde(default)]
    pub pid: u32,
    #[serde(default)]
    pub started_at: String,
}

// ── User identity (Windows-specific via WinAPI) ──────────────────────────────

/// Возвращает SID текущего пользователя как строку S-1-5-21-... или None.
/// На не-Windows - возвращает USER/USERNAME env как fallback (не для продакшна).
pub fn current_user_sid() -> Option<String> {
    #[cfg(windows)]
    {
        win_impl::current_user_sid_impl()
    }
    #[cfg(not(windows))]
    {
        std::env::var("USER").or_else(|_| std::env::var("USERNAME")).ok()
    }
}

/// Возвращает имя текущего пользователя (без домена).
/// На Windows - `GetUserNameW`; на других - $USER/%USERNAME%.
pub fn current_user_name() -> String {
    #[cfg(windows)]
    {
        win_impl::current_user_name_impl().unwrap_or_else(|| "unknown".to_string())
    }
    #[cfg(not(windows))]
    {
        std::env::var("USER")
            .or_else(|_| std::env::var("USERNAME"))
            .unwrap_or_else(|_| "unknown".to_string())
    }
}

// ── Port allocation ──────────────────────────────────────────────────────────

/// Deterministic per-user порт: `base + (xxhash(SID) % 100)`.
/// Возвращает тот же порт для того же юзера при каждом вызове.
/// Если SID недоступен - fallback на hash имени пользователя.
/// Если и это fail - возвращает `base` (legacy-режим).
pub fn user_scoped_port(base: u16) -> u16 {
    use xxhash_rust::xxh3::xxh3_64;

    let sid_or_name = current_user_sid().unwrap_or_else(current_user_name);
    if sid_or_name.is_empty() || sid_or_name == "unknown" {
        warn!("user_scoped_port: cannot determine user identity, using legacy port {base}");
        return base;
    }
    let hash = xxh3_64(sid_or_name.as_bytes());
    let offset = (hash % 100) as u16;
    base + offset
}

/// Проверяет, свободен ли TCP-порт на 127.0.0.1.
pub fn port_is_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

/// Находит порт для этого юзера. Strategy:
/// 1. Если kill-switch `AURORA_SIDECAR_LEGACY_PORT=1` → вернуть `cfg.legacy_port`.
/// 2. Deterministic port по SID → если свободен, вернуть.
/// 3. Иначе - `bind(0)` OS-assigned ephemeral.
pub fn allocate_port(cfg: &SidecarConfig) -> std::io::Result<u16> {
    if is_kill_switch_enabled() {
        info!(
            "allocate_port: kill-switch enabled (AURORA_SIDECAR_LEGACY_PORT=1), \
             using legacy port {}",
            cfg.legacy_port
        );
        return Ok(cfg.legacy_port);
    }

    let preferred = user_scoped_port(cfg.legacy_port);
    if port_is_free(preferred) {
        debug!("allocate_port: using user-scoped port {preferred}");
        return Ok(preferred);
    }

    // Preferred занят - возможно, zombie от нашей сессии. Пробуем OS-assigned.
    warn!(
        "allocate_port: preferred port {preferred} busy (zombie?), \
         falling back to OS-assigned ephemeral"
    );
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

// ── Kill-switch ──────────────────────────────────────────────────────────────

/// Env var `AURORA_SIDECAR_LEGACY_PORT=1` - bypass port discovery,
/// использовать hardcoded port. Safety valve для прод-отката без rebuild.
pub fn is_kill_switch_enabled() -> bool {
    matches!(
        std::env::var("AURORA_SIDECAR_LEGACY_PORT")
            .unwrap_or_default()
            .as_str(),
        "1" | "true" | "yes"
    )
}

/// Env var `AURORA_SKIP_HANDSHAKE=1` - пропускать version/product check в handshake.
/// Оставляет только базовый HTTP health. Safety valve при thrashing'е.
pub fn is_handshake_disabled() -> bool {
    matches!(
        std::env::var("AURORA_SKIP_HANDSHAKE")
            .unwrap_or_default()
            .as_str(),
        "1" | "true" | "yes"
    )
}

// ── State file I/O ───────────────────────────────────────────────────────────

/// Путь к sidecar.json в `%LOCALAPPDATA%\<identifier_dir>\sidecar.json`.
/// Используется `%LOCALAPPDATA%` а не `%APPDATA%` - AppData\Local гарантированно
/// не роумит между RDP-серверами в AD-доменах.
pub fn state_file_path(cfg: &SidecarConfig) -> PathBuf {
    let base = if cfg!(windows) {
        std::env::var("LOCALAPPDATA")
            .ok()
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                // Fallback если LOCALAPPDATA не установлена (necessary на старых Windows)
                let home = std::env::var("USERPROFILE").unwrap_or_else(|_| ".".to_string());
                PathBuf::from(home).join("AppData").join("Local")
            })
    } else {
        // На Unix - ~/.local/share (XDG). Для тестов/CI.
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        PathBuf::from(home).join(".local").join("share")
    };

    base.join(cfg.identifier_dir).join("sidecar.json")
}

/// Atomic write: tmp + rename. На Windows используется MoveFileEx с
/// MOVEFILE_REPLACE_EXISTING (через std::fs::rename - корректно работает на NTFS).
pub fn write_state_file(cfg: &SidecarConfig, state: &SidecarState) -> std::io::Result<()> {
    let path = state_file_path(cfg);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("json.tmp");

    let json = serde_json::to_string_pretty(state)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
    std::fs::write(&tmp, json)?;
    std::fs::rename(&tmp, &path)?;
    debug!("write_state_file: {}", path.display());
    Ok(())
}

/// Читает state file, возвращает None если файла нет или он битый.
/// Битый файл логируется но не ломает startup (просто respawn заново).
pub fn read_state_file(cfg: &SidecarConfig) -> Option<SidecarState> {
    let path = state_file_path(cfg);
    let raw = std::fs::read_to_string(&path).ok()?;
    match serde_json::from_str::<SidecarState>(&raw) {
        Ok(s) => Some(s),
        Err(e) => {
            warn!(
                "read_state_file: corrupt sidecar.json at {} ({e}) - ignoring",
                path.display()
            );
            None
        }
    }
}

/// Удаление state file при graceful shutdown. Не ошибка если файла нет.
pub fn delete_state_file(cfg: &SidecarConfig) {
    let path = state_file_path(cfg);
    if path.exists() {
        if let Err(e) = std::fs::remove_file(&path) {
            warn!("delete_state_file: {} ({e})", path.display());
        }
    }
}

// ── Session ID ───────────────────────────────────────────────────────────────

/// Генерирует новый session_id - короткий UUID v4 hex.
pub fn generate_session_id() -> String {
    uuid::Uuid::new_v4().simple().to_string()
}

// ── Handshake ────────────────────────────────────────────────────────────────

/// Проверяет handshake с sidecar на указанном порту.
/// Возвращает HealthInfo если:
/// - HTTP `/health` вернул 200
/// - `product` совпадает с `cfg.product_id`
/// - `version` присутствует (строгость check'а решает caller)
///
/// Если `AURORA_SKIP_HANDSHAKE=1` - возвращает минимальный HealthInfo без проверок.
pub async fn verify_handshake(
    port: u16,
    cfg: &SidecarConfig,
    client: &reqwest::Client,
) -> Option<HealthInfo> {
    let url = format!("http://127.0.0.1:{port}/health");
    let resp = client.get(&url).send().await.ok()?;
    if !resp.status().is_success() {
        debug!("verify_handshake: {url} returned {}", resp.status());
        return None;
    }
    let info = resp.json::<HealthInfo>().await.ok()?;

    if is_handshake_disabled() {
        debug!("verify_handshake: AURORA_SKIP_HANDSHAKE=1, returning without product check");
        return Some(info);
    }

    if !info.product.is_empty() && info.product != cfg.product_id {
        warn!(
            "verify_handshake: product mismatch on port {port} - expected {}, got '{}'. \
             Foreign sidecar, will respawn.",
            cfg.product_id, info.product
        );
        return None;
    }

    Some(info)
}

/// Convenience: создаёт reqwest client с коротким timeout для /health probes.
pub fn handshake_client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap_or_default()
}

// ── Process owner detection ──────────────────────────────────────────────────

/// Получает owner процесса (formatted как `DOMAIN\user` или `user`) через WinAPI.
/// Fallback: None - caller должен трактовать как "неизвестно, не убиваем".
pub fn get_process_owner(pid: u32) -> Option<String> {
    #[cfg(windows)]
    {
        win_impl::get_process_owner_impl(pid)
    }
    #[cfg(not(windows))]
    {
        let _ = pid;
        None
    }
}

/// Проверяет что процесс PID:
/// 1. Принадлежит текущему OS-пользователю (multi-tenant safety)
/// 2. Image name совпадает с `cfg.process_exe_hint` или содержит `python`/`pythonw`
///
/// Никогда не возвращает true для процесса другого пользователя -
/// security invariant для RDP.
pub fn is_our_process_and_user(pid: u32, cfg: &SidecarConfig) -> bool {
    #[cfg(windows)]
    {
        let Some(owner) = get_process_owner(pid) else {
            debug!("is_our_process_and_user: owner unknown for PID={pid}, NOT killing (safe default)");
            return false;
        };
        let me = current_user_name().to_lowercase();
        let owner_lower = owner.to_lowercase();
        let user_match = owner_lower.ends_with(&format!("\\{me}")) || owner_lower == me;

        if !user_match {
            debug!(
                "is_our_process_and_user: PID={pid} owner={owner} ≠ current user {me}, NOT killing"
            );
            return false;
        }

        // Owner матчит - теперь проверяем image name через tasklist (позитивная проверка, без риска)
        win_impl::process_image_contains(pid, cfg.process_exe_hint)
    }
    #[cfg(not(windows))]
    {
        let _ = (pid, cfg);
        false
    }
}

// ── Windows-specific implementations ─────────────────────────────────────────

#[cfg(windows)]
mod win_impl {
    use log::debug;
    use std::os::windows::process::CommandExt;
    use std::process::Command;
    use windows_sys::Win32::{
        Foundation::{CloseHandle, LocalFree, HANDLE, HLOCAL},
        Security::{
            Authorization::ConvertSidToStringSidW, GetTokenInformation, LookupAccountSidW,
            TokenUser, SID_NAME_USE, TOKEN_QUERY, TOKEN_USER,
        },
        System::Threading::{
            GetCurrentProcess, OpenProcess, OpenProcessToken, PROCESS_QUERY_LIMITED_INFORMATION,
        },
    };

    /// Возвращает SID текущего пользователя как S-1-5-... строку.
    pub fn current_user_sid_impl() -> Option<String> {
        unsafe {
            let proc_handle: HANDLE = GetCurrentProcess();
            let mut token: HANDLE = std::ptr::null_mut();
            if OpenProcessToken(proc_handle, TOKEN_QUERY, &mut token) == 0 {
                return None;
            }
            let result = sid_string_from_token(token);
            CloseHandle(token);
            result
        }
    }

    /// Возвращает имя текущего пользователя (без домена).
    pub fn current_user_name_impl() -> Option<String> {
        // Простой путь через %USERNAME% - задаётся ОС корректно
        std::env::var("USERNAME").ok().filter(|s| !s.is_empty())
    }

    /// Owner чужого процесса через OpenProcess + token + LookupAccountSidW.
    pub fn get_process_owner_impl(pid: u32) -> Option<String> {
        unsafe {
            let proc_handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if proc_handle.is_null() {
                debug!("OpenProcess({pid}) failed (process gone or permission denied)");
                return None;
            }

            let mut token: HANDLE = std::ptr::null_mut();
            let ok = OpenProcessToken(proc_handle, TOKEN_QUERY, &mut token);
            CloseHandle(proc_handle);
            if ok == 0 || token.is_null() {
                return None;
            }

            let owner = domain_user_from_token(token);
            CloseHandle(token);
            owner
        }
    }

    /// Позитивная проверка имени процесса через tasklist (не для trusted decisions).
    /// Использование только когда owner уже совпал с current user.
    pub fn process_image_contains(pid: u32, hint: &str) -> bool {
        let out = Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
            .creation_flags(0x08000000)
            .output();
        let Ok(out) = out else { return false };
        let s = String::from_utf8_lossy(&out.stdout).to_lowercase();
        let hint_lc = hint.to_lowercase();
        s.contains(&hint_lc) || s.contains("python") || s.contains("pythonw")
    }

    // ── Internal token helpers ───────────────────────────────────────────

    /// Читает SID из token, возвращает как S-1-5-... строку.
    unsafe fn sid_string_from_token(token: HANDLE) -> Option<String> {
        let mut needed: u32 = 0;
        GetTokenInformation(token, TokenUser, std::ptr::null_mut(), 0, &mut needed);
        if needed == 0 {
            return None;
        }
        let mut buf = vec![0u8; needed as usize];
        if GetTokenInformation(
            token,
            TokenUser,
            buf.as_mut_ptr() as _,
            needed,
            &mut needed,
        ) == 0
        {
            return None;
        }
        let tu = &*(buf.as_ptr() as *const TOKEN_USER);
        let sid = tu.User.Sid;
        if sid.is_null() {
            return None;
        }

        let mut sid_str_ptr: *mut u16 = std::ptr::null_mut();
        if ConvertSidToStringSidW(sid, &mut sid_str_ptr) == 0 || sid_str_ptr.is_null() {
            return None;
        }

        // Read UTF-16 until null
        let mut len = 0usize;
        while *sid_str_ptr.add(len) != 0 {
            len += 1;
        }
        let slice = std::slice::from_raw_parts(sid_str_ptr, len);
        let result = String::from_utf16(slice).ok();

        LocalFree(sid_str_ptr as HLOCAL);
        result
    }

    /// Читает SID из token, резолвит в DOMAIN\user через LookupAccountSidW.
    unsafe fn domain_user_from_token(token: HANDLE) -> Option<String> {
        let mut needed: u32 = 0;
        GetTokenInformation(token, TokenUser, std::ptr::null_mut(), 0, &mut needed);
        if needed == 0 {
            return None;
        }
        let mut buf = vec![0u8; needed as usize];
        if GetTokenInformation(
            token,
            TokenUser,
            buf.as_mut_ptr() as _,
            needed,
            &mut needed,
        ) == 0
        {
            return None;
        }
        let tu = &*(buf.as_ptr() as *const TOKEN_USER);
        let sid = tu.User.Sid;
        if sid.is_null() {
            return None;
        }

        // First pass - get required buffer sizes
        let mut name_len: u32 = 0;
        let mut domain_len: u32 = 0;
        let mut sid_use: SID_NAME_USE = 0;
        LookupAccountSidW(
            std::ptr::null(),
            sid,
            std::ptr::null_mut(),
            &mut name_len,
            std::ptr::null_mut(),
            &mut domain_len,
            &mut sid_use,
        );
        if name_len == 0 || domain_len == 0 {
            return None;
        }

        let mut name_buf = vec![0u16; name_len as usize];
        let mut domain_buf = vec![0u16; domain_len as usize];
        if LookupAccountSidW(
            std::ptr::null(),
            sid,
            name_buf.as_mut_ptr(),
            &mut name_len,
            domain_buf.as_mut_ptr(),
            &mut domain_len,
            &mut sid_use,
        ) == 0
        {
            return None;
        }

        // Trim trailing nulls
        let name = String::from_utf16_lossy(&name_buf[..name_len as usize]);
        let domain = String::from_utf16_lossy(&domain_buf[..domain_len as usize]);

        if domain.is_empty() {
            Some(name)
        } else {
            Some(format!("{domain}\\{name}"))
        }
    }
}

// ── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    const TEST_CFG: SidecarConfig = SidecarConfig {
        product_id: "com.aurora.test",
        version: "0.0.1",
        legacy_port: 7430,
        identifier_dir: "com.aurora.test",
        process_exe_hint: "test-sidecar",
    };

    #[test]
    fn user_scoped_port_stable() {
        let p1 = user_scoped_port(7430);
        let p2 = user_scoped_port(7430);
        assert_eq!(p1, p2, "same user must get same port");
        assert!(
            p1 >= 7430 && p1 < 7530,
            "port {p1} должен быть в диапазоне base..base+100"
        );
    }

    #[test]
    fn user_scoped_port_different_bases() {
        let p1 = user_scoped_port(7430);
        let p2 = user_scoped_port(7420);
        // Offset одинаковый для одного user
        assert_eq!(p1 - 7430, p2 - 7420);
    }

    #[test]
    fn state_file_roundtrip() {
        let state = SidecarState {
            port: 52431,
            pid: 19284,
            session_id: "abc123".to_string(),
            product: "com.aurora.test".to_string(),
            version: "1.0.9".to_string(),
            user: "tester".to_string(),
            started_at: "2026-04-20T14:32:01Z".to_string(),
        };

        let cfg = SidecarConfig {
            identifier_dir: "com.aurora.test-rt",
            ..TEST_CFG
        };

        // Очистка после предыдущих прогонов
        delete_state_file(&cfg);

        write_state_file(&cfg, &state).expect("write");
        let read = read_state_file(&cfg).expect("read");

        assert_eq!(read.port, state.port);
        assert_eq!(read.pid, state.pid);
        assert_eq!(read.session_id, state.session_id);
        assert_eq!(read.product, state.product);

        delete_state_file(&cfg);
    }

    #[test]
    fn read_state_file_missing_returns_none() {
        let cfg = SidecarConfig {
            identifier_dir: "com.aurora.test-missing-nonexistent-dir",
            ..TEST_CFG
        };
        delete_state_file(&cfg); // ensure missing
        assert!(read_state_file(&cfg).is_none());
    }

    #[test]
    fn read_state_file_corrupt_returns_none() {
        let cfg = SidecarConfig {
            identifier_dir: "com.aurora.test-corrupt",
            ..TEST_CFG
        };
        let path = state_file_path(&cfg);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, "not json at all {{").unwrap();

        assert!(read_state_file(&cfg).is_none());
        delete_state_file(&cfg);
    }

    #[test]
    fn session_id_unique() {
        let a = generate_session_id();
        let b = generate_session_id();
        assert_ne!(a, b);
        assert_eq!(a.len(), 32); // simple UUID hex
    }

    #[test]
    fn allocate_port_returns_free_port() {
        let cfg = SidecarConfig {
            legacy_port: 17430, // unusual base чтобы не конфликтовать с реальным sidecar'ом
            ..TEST_CFG
        };
        let port = allocate_port(&cfg).expect("allocate");
        assert!(port >= 1024); // sanity - не privileged range
    }

    #[test]
    fn kill_switch_disabled_by_default() {
        // Тест может ложно упасть если test harness запущен с AURORA_SIDECAR_LEGACY_PORT=1
        if std::env::var("AURORA_SIDECAR_LEGACY_PORT").is_err() {
            assert!(!is_kill_switch_enabled());
        }
    }

    #[test]
    fn current_user_not_empty() {
        let u = current_user_name();
        assert!(!u.is_empty());
        assert_ne!(u, "unknown", "CI must provide USERNAME/USER");
    }

    #[cfg(windows)]
    #[test]
    fn current_user_sid_format() {
        let sid = current_user_sid().expect("SID on Windows");
        assert!(sid.starts_with("S-1-"), "SID format S-1-... got '{sid}'");
    }
}
