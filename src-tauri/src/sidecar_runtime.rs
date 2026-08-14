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

use chrono::{DateTime, Utc};
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

    /// Дополнительные допустимые имена образа — ТОЛЬКО для продуктов, чей движок
    /// действительно запускается сторонним интерпретатором (например, dev-режим
    /// через `python server.py`).
    ///
    /// 🔴 Раньше `python`/`pythonw` принимались безусловно для ЛЮБОГО продукта, вне
    /// зависимости от того, python-овый ли у него движок. Это делало проверку имени
    /// образа почти бессодержательной: под неё подпадал любой Jupyter, Anaconda,
    /// языковой модуль редактора и движок соседнего продукта Aurora. Теперь список
    /// задаёт сам продукт и, как правило, он пуст в релизной сборке.
    pub extra_image_hints: &'static [&'static str],
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

// ── Решение о снятии процесса (чистая логика, без системных вызовов) ─────────

/// Свойства реально существующего процесса, снятые системным слоем
/// (`observe_process`). Все поля необязательные: если системный вызов не удался,
/// значение остаётся `None`, и решение обязано быть консервативным.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ObservedProcess {
    /// Владелец в виде `DOMAIN\user` либо `user`.
    pub owner: Option<String>,
    /// Полный путь к образу процесса (`QueryFullProcessImageNameW`).
    pub image_path: Option<String>,
    /// Момент создания процесса по системным часам, в UTC (`GetProcessTimes`).
    pub created_at: Option<DateTime<Utc>>,
}

/// Допуск на расхождение между временем создания процесса и `started_at`
/// в файле состояния, в секундах.
///
/// Порядок операций при запуске движка (`econ_sidecar::start_sidecar`):
/// `spawn_sidecar_proc` → `child.id()` → `store_child` → `write_initial_state`.
/// То есть процесс создаётся ЗАВЕДОМО РАНЬШЕ записи `started_at`, и зазор между
/// ними — доли секунды: между двумя операциями нет ни ожиданий, ни ввода-вывода
/// кроме самой записи файла. Реальный разброс может дать только скачок системных
/// часов (коррекция NTP, ручной перевод) ровно в этом промежутке, поэтому пяти
/// минут с запасом хватает на честный случай.
///
/// Окно двустороннее и обе границы содержательны:
/// * верхняя (`created_at ≤ started_at + допуск`) — главная защита от
///   переиспользования номера процесса: после перезагрузки Windows раздаёт номера
///   заново, и чужой процесс с тем же номером создан ПОЗЖЕ нашей записи, обычно на
///   часы;
/// * нижняя (`created_at ≥ started_at − допуск`) — защита от долгоживущего чужого
///   процесса, который получил этот номер задолго до нашей записи (запущенный
///   вчера Jupyter и тому подобное).
pub const KILL_TIME_TOLERANCE_SECS: i64 = 300;

/// Почему процесс решено НЕ снимать. Попадает в журнал и в тесты.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkipReason {
    /// Идентификатор нулевой — снимать нечего.
    InvalidPid,
    /// Файл состояния оставлен другим продуктом.
    ProductMismatch,
    /// Файл состояния оставлен другим пользователем ОС.
    StateUserMismatch,
    /// Владельца процесса определить не удалось.
    OwnerUnknown,
    /// Владелец процесса — другой пользователь ОС.
    OwnerMismatch,
    /// Путь к образу процесса определить не удалось.
    ImageUnknown,
    /// Образ процесса не наш.
    ImageMismatch,
    /// Время создания процесса получить не удалось.
    CreationTimeUnknown,
    /// `started_at` в файле состояния не разбирается как дата.
    StartedAtUnparsable,
    /// Процесс создан вне допустимого окна вокруг `started_at` — почти наверняка
    /// номер переиспользован операционной системой.
    CreatedOutsideWindow,
}

impl SkipReason {
    /// Пояснение на русском — для журнала приложения.
    pub fn as_str(&self) -> &'static str {
        match self {
            SkipReason::InvalidPid => "нулевой идентификатор процесса",
            SkipReason::ProductMismatch => "файл состояния от другого продукта",
            SkipReason::StateUserMismatch => "файл состояния от другого пользователя",
            SkipReason::OwnerUnknown => "владелец процесса неизвестен",
            SkipReason::OwnerMismatch => "процесс принадлежит другому пользователю",
            SkipReason::ImageUnknown => "путь к образу процесса неизвестен",
            SkipReason::ImageMismatch => "образ процесса не наш",
            SkipReason::CreationTimeUnknown => "время создания процесса неизвестно",
            SkipReason::StartedAtUnparsable => "started_at в файле состояния не разбирается",
            SkipReason::CreatedOutsideWindow => {
                "процесс создан вне окна вокруг started_at (номер переиспользован)"
            }
        }
    }
}

impl std::fmt::Display for SkipReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Итог проверки: снимать процесс или нет (и почему нет).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KillVerdict {
    Kill,
    Skip(SkipReason),
}

impl KillVerdict {
    pub fn is_kill(&self) -> bool {
        matches!(self, KillVerdict::Kill)
    }
}

/// Сравнение владельца процесса с текущим пользователем.
/// `owner` приходит как `DOMAIN\user` либо `user`; в файле состояния и в
/// `current_user_name()` домена нет, поэтому сверяем хвост.
fn owner_matches(owner: &str, current_user: &str) -> bool {
    let owner_lc = owner.trim().to_lowercase();
    let me_lc = current_user.trim().to_lowercase();
    if me_lc.is_empty() || me_lc == "unknown" {
        return false;
    }
    owner_lc == me_lc || owner_lc.ends_with(&format!("\\{me_lc}"))
}

/// Сверка образа процесса с ожидаемыми именами продукта.
///
/// Работаем с ПОЛНЫМ путём (`QueryFullProcessImageNameW`), берём имя файла без
/// расширения и сверяем его с `process_exe_hint` и `extra_image_hints`. Это строже
/// прежнего «вывод `tasklist` содержит подстроку»: подстрока могла совпасть с чем
/// угодно в строке вывода, а имя файла — ровно то, что запущено.
///
/// Допускается совпадение по началу имени (`python` ↔ `python3`): версии
/// интерпретатора различаются суффиксом, а не префиксом.
pub fn image_matches(image_path: Option<&str>, cfg: &SidecarConfig) -> bool {
    let Some(path) = image_path else {
        return false;
    };
    let file_name = path
        .rsplit(['\\', '/'])
        .next()
        .unwrap_or(path)
        .to_lowercase();
    let stem = file_name
        .strip_suffix(".exe")
        .unwrap_or(&file_name)
        .to_string();
    if stem.is_empty() {
        return false;
    }

    std::iter::once(cfg.process_exe_hint)
        .chain(cfg.extra_image_hints.iter().copied())
        .filter(|h| !h.is_empty())
        .any(|hint| {
            let hint_lc = hint.to_lowercase();
            stem == hint_lc || stem.starts_with(&hint_lc)
        })
}

/// Чистое решение «снимать ли процесс `state.pid`».
///
/// 🔴 CPD-79. До этой правки решение принималось по двум признакам — владелец
/// процесса и «имя образа содержит python» — и этого достаточно НЕ было. Файл
/// состояния переживает падение приложения (`delete_state_file` вызывается только
/// на трёх штатных путях), Windows после перезагрузки раздаёт номера процессов
/// заново, а снятие идёт деревом (`taskkill /T /F`). В итоге приложение могло
/// молча снять чужой python того же пользователя — Jupyter, Anaconda, движок
/// соседнего продукта Aurora — вместе со всеми его потомками.
///
/// Решающая проверка — время создания процесса против `started_at`, см.
/// [`KILL_TIME_TOLERANCE_SECS`].
///
/// Порядок проверок — от дешёвых к дорогим; каждая может только запретить снятие.
/// Любая неопределённость трактуется как запрет: не снять своего зомби дешевле,
/// чем убить чужой расчёт. Зомби максимум удержит порт, а `allocate_port` в этом
/// случае возьмёт свободный — потеря восстановима без участия пользователя.
pub fn should_kill(
    state: &SidecarState,
    observed: &ObservedProcess,
    cfg: &SidecarConfig,
    current_user: &str,
) -> KillVerdict {
    if state.pid == 0 {
        return KillVerdict::Skip(SkipReason::InvalidPid);
    }

    // 1. Сверка продукта — бесплатно, строки уже в руках.
    if !state.product.is_empty() && state.product != cfg.product_id {
        return KillVerdict::Skip(SkipReason::ProductMismatch);
    }

    // 2. Сверка пользователя из файла состояния — тоже бесплатно, до системных
    //    вызовов. Отсекает запись, оставленную другим пользователем на общей
    //    машине (RDP), даже не трогая процесс.
    if !state.user.is_empty() && !owner_matches(&state.user, current_user) {
        return KillVerdict::Skip(SkipReason::StateUserMismatch);
    }

    // 3. Владелец реального процесса.
    let Some(owner) = observed.owner.as_deref() else {
        return KillVerdict::Skip(SkipReason::OwnerUnknown);
    };
    if !owner_matches(owner, current_user) {
        return KillVerdict::Skip(SkipReason::OwnerMismatch);
    }

    // 4. Образ реального процесса.
    if observed.image_path.is_none() {
        return KillVerdict::Skip(SkipReason::ImageUnknown);
    }
    if !image_matches(observed.image_path.as_deref(), cfg) {
        return KillVerdict::Skip(SkipReason::ImageMismatch);
    }

    // 5. Время создания против записанного нами started_at.
    let Some(created_at) = observed.created_at else {
        return KillVerdict::Skip(SkipReason::CreationTimeUnknown);
    };
    let Ok(started_at) = DateTime::parse_from_rfc3339(state.started_at.trim()) else {
        return KillVerdict::Skip(SkipReason::StartedAtUnparsable);
    };
    let started_at = started_at.with_timezone(&Utc);
    let delta = (created_at - started_at).num_seconds();
    if delta.abs() > KILL_TIME_TOLERANCE_SECS {
        return KillVerdict::Skip(SkipReason::CreatedOutsideWindow);
    }

    KillVerdict::Kill
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

/// Снимает свойства процесса одним открытием дескриптора: владелец, полный путь
/// к образу, время создания. Любое поле остаётся `None`, если системный вызов
/// не удался — вызывающая сторона обязана трактовать это как «не трогаем».
///
/// Один `OpenProcess` на все три запроса: и дешевле, и без гонки, при которой
/// между двумя открытиями номер процесса успевает смениться.
pub fn observe_process(pid: u32) -> ObservedProcess {
    #[cfg(windows)]
    {
        win_impl::observe_process_impl(pid)
    }
    #[cfg(not(windows))]
    {
        let _ = pid;
        ObservedProcess::default()
    }
}

/// Проверяет что процесс PID:
/// 1. Принадлежит текущему OS-пользователю (multi-tenant safety)
/// 2. Имя образа входит в список ожидаемых имён продукта
///    (`cfg.process_exe_hint` + `cfg.extra_image_hints`)
///
/// Никогда не возвращает true для процесса другого пользователя -
/// security invariant для RDP.
///
/// 🔴 Этой проверки НЕДОСТАТОЧНО для решения о снятии процесса: она ничего не
/// знает о переиспользовании номера процесса операционной системой. Решение
/// принимает [`should_kill`], которая дополнительно сверяет время создания
/// процесса с `started_at` из файла состояния (CPD-79).
pub fn is_our_process_and_user(pid: u32, cfg: &SidecarConfig) -> bool {
    #[cfg(windows)]
    {
        let observed = observe_process(pid);
        let Some(owner) = observed.owner.as_deref() else {
            debug!("is_our_process_and_user: owner unknown for PID={pid}, NOT killing (safe default)");
            return false;
        };
        let me = current_user_name();
        if !owner_matches(owner, &me) {
            debug!(
                "is_our_process_and_user: PID={pid} owner={owner} ≠ current user {me}, NOT killing"
            );
            return false;
        }

        image_matches(observed.image_path.as_deref(), cfg)
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
    use chrono::{DateTime, Utc};
    use log::debug;
    use windows_sys::Win32::{
        Foundation::{CloseHandle, LocalFree, FILETIME, HANDLE, HLOCAL},
        Security::{
            Authorization::ConvertSidToStringSidW, GetTokenInformation, LookupAccountSidW,
            TokenUser, SID_NAME_USE, TOKEN_QUERY, TOKEN_USER,
        },
        System::Threading::{
            GetCurrentProcess, GetProcessTimes, OpenProcess, OpenProcessToken,
            QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
        },
    };

    use super::ObservedProcess;

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
            let owner = owner_from_process_handle(proc_handle);
            CloseHandle(proc_handle);
            owner
        }
    }

    /// Владелец, полный путь к образу и время создания — за одно открытие
    /// дескриптора. `PROCESS_QUERY_LIMITED_INFORMATION` достаточно для всех трёх
    /// запросов и не требует повышения прав.
    ///
    /// 🔴 Прежде имя образа выяснялось порождением `tasklist` со скрытым окном, а
    /// следом шёл `taskkill` — тоже со скрытым окном. Связка «скрытая разведка
    /// процессов → принудительное снятие дерева» разбирается поведенческой защитой
    /// антивируса как вредоносная (10.08 Kaspersky снял оболочку продукта с диска,
    /// вердикт PDM:Trojan.Win32.Generic). Прямой системный вызов не порождает
    /// процессов вовсе и заодно даёт ПОЛНЫЙ путь вместо строки вывода утилиты.
    pub fn observe_process_impl(pid: u32) -> ObservedProcess {
        if pid == 0 {
            return ObservedProcess::default();
        }
        unsafe {
            let proc_handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if proc_handle.is_null() {
                debug!("OpenProcess({pid}) failed (process gone or permission denied)");
                return ObservedProcess::default();
            }

            let observed = ObservedProcess {
                owner: owner_from_process_handle(proc_handle),
                image_path: image_path_from_process_handle(proc_handle),
                created_at: creation_time_from_process_handle(proc_handle),
            };

            CloseHandle(proc_handle);
            observed
        }
    }

    /// Полный путь к образу процесса. `MAX_PATH` недостаточно — пути с длинными
    /// именами и включённым `LongPathsEnabled` доходят до 32 767 символов.
    unsafe fn image_path_from_process_handle(proc_handle: HANDLE) -> Option<String> {
        let mut buf = vec![0u16; 32768];
        let mut size = buf.len() as u32;
        if QueryFullProcessImageNameW(proc_handle, PROCESS_NAME_WIN32, buf.as_mut_ptr(), &mut size)
            == 0
            || size == 0
        {
            return None;
        }
        String::from_utf16(&buf[..size as usize]).ok()
    }

    /// Время создания процесса. `GetProcessTimes` отдаёт `FILETIME` в UTC —
    /// часовой пояс машины на результат не влияет.
    unsafe fn creation_time_from_process_handle(proc_handle: HANDLE) -> Option<DateTime<Utc>> {
        let mut creation = FILETIME {
            dwLowDateTime: 0,
            dwHighDateTime: 0,
        };
        let mut exit = creation;
        let mut kernel = creation;
        let mut user = creation;
        if GetProcessTimes(
            proc_handle,
            &mut creation,
            &mut exit,
            &mut kernel,
            &mut user,
        ) == 0
        {
            return None;
        }
        filetime_to_utc(creation)
    }

    /// `FILETIME` — число интервалов по 100 нс от 1601-01-01 UTC.
    fn filetime_to_utc(ft: FILETIME) -> Option<DateTime<Utc>> {
        /// Интервалов по 100 нс между 1601-01-01 и 1970-01-01.
        const UNIX_EPOCH_TICKS: u64 = 116_444_736_000_000_000;

        let ticks = ((ft.dwHighDateTime as u64) << 32) | ft.dwLowDateTime as u64;
        if ticks < UNIX_EPOCH_TICKS {
            // Ноль либо дата до 1970 — доверять такому значению нельзя.
            return None;
        }
        let since_epoch = ticks - UNIX_EPOCH_TICKS;
        let secs = (since_epoch / 10_000_000) as i64;
        let nanos = ((since_epoch % 10_000_000) * 100) as u32;
        DateTime::from_timestamp(secs, nanos)
    }

    // ── Internal token helpers ───────────────────────────────────────────

    /// Владелец процесса по уже открытому дескриптору. Дескриптор процесса
    /// закрывает вызывающая сторона, токен закрывается здесь.
    unsafe fn owner_from_process_handle(proc_handle: HANDLE) -> Option<String> {
        let mut token: HANDLE = std::ptr::null_mut();
        if OpenProcessToken(proc_handle, TOKEN_QUERY, &mut token) == 0 || token.is_null() {
            return None;
        }
        let owner = domain_user_from_token(token);
        CloseHandle(token);
        owner
    }

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
        extra_image_hints: &[],
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

    // ── CPD-79: решение о снятии процесса ────────────────────────────────
    //
    // Решение вынесено в чистую функцию именно ради этих тестов: ни Windows,
    // ни живых процессов они не требуют. До правки таких тестов не было вовсе -
    // решение было сварено с системными вызовами, и вызывать было нечего.

    /// Конфиг «как в релизе»: движок — собранный exe, сторонние интерпретаторы
    /// в список допустимых имён образа не входят.
    const KILL_CFG: SidecarConfig = SidecarConfig {
        process_exe_hint: "econometrica-sidecar",
        ..TEST_CFG
    };

    /// Конфиг «как в отладочной сборке»: движок запускается интерпретатором.
    const KILL_CFG_DEV: SidecarConfig = SidecarConfig {
        extra_image_hints: &["python", "pythonw"],
        ..KILL_CFG
    };

    const OUR_USER: &str = "anton";
    const OUR_IMAGE: &str = r"C:\Program Files\Aurora Econometrica\sidecar\econometrica\econometrica-sidecar.exe";

    /// Состояние, записанное нами в момент `started_at`.
    fn state_at(started_at: DateTime<Utc>) -> SidecarState {
        SidecarState {
            port: 7461,
            pid: 9134,
            session_id: "abc123".to_string(),
            product: KILL_CFG.product_id.to_string(),
            version: "2.4.8".to_string(),
            user: OUR_USER.to_string(),
            started_at: started_at.to_rfc3339(),
        }
    }

    fn observed(created_at: Option<DateTime<Utc>>, image: &str) -> ObservedProcess {
        ObservedProcess {
            owner: Some(format!("AURORA-PC\\{OUR_USER}")),
            image_path: Some(image.to_string()),
            created_at,
        }
    }

    fn epoch(secs: i64) -> DateTime<Utc> {
        DateTime::from_timestamp(secs, 0).expect("валидная отметка времени")
    }

    /// Случай 1а. Реальный порядок операций в `start_sidecar`: процесс порождается,
    /// и лишь затем пишется файл состояния. Значит наш процесс создан на доли
    /// секунды РАНЬШЕ `started_at` - это штатное снятие зомби, оно обязано работать.
    #[test]
    fn kill_our_process_created_just_before_state_write() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = observed(Some(started - chrono::Duration::milliseconds(200)), OUR_IMAGE);

        let verdict = should_kill(&state, &obs, &KILL_CFG, OUR_USER);
        assert_eq!(verdict, KillVerdict::Kill);
        assert!(verdict.is_kill());
    }

    /// Случай 1б. Тот же процесс, но часы качнулись и время создания оказалось
    /// чуть ПОЗЖЕ записи - в пределах допуска снимаем по-прежнему.
    #[test]
    fn kill_our_process_created_slightly_after_state_write() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = observed(Some(started + chrono::Duration::seconds(2)), OUR_IMAGE);

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Kill
        );
    }

    /// Случай 2 — прямой контроль дефекта CPD-79. Оболочку сняли (антивирус, падение,
    /// диспетчер задач), файл состояния остался с мёртвым номером. Машина
    /// перезагрузилась, Windows раздала номера заново, и этот же номер достался
    /// другому процессу - тот создан ПОЗЖЕ нашей записи. До правки такой процесс
    /// снимался деревом.
    #[test]
    fn skip_when_pid_reused_after_reboot() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        // Новый владелец номера появился через 9 часов после нашей записи.
        let obs = observed(Some(started + chrono::Duration::hours(9)), OUR_IMAGE);

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::CreatedOutsideWindow)
        );
    }

    /// Случай 2б. Долгоживущий чужой процесс, получивший этот номер задолго до
    /// нашей записи, - нижняя граница окна.
    #[test]
    fn skip_when_process_predates_state_file() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = observed(Some(started - chrono::Duration::hours(20)), OUR_IMAGE);

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::CreatedOutsideWindow)
        );
    }

    /// Случай 3. Чужой python того же пользователя (Jupyter, Anaconda, движок
    /// соседнего продукта Aurora), запущенный вчера. В релизной сборке отсекается
    /// уже по образу: безусловного «имя содержит python» больше нет.
    #[test]
    fn skip_foreign_python_by_image_in_release_config() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = observed(
            Some(started - chrono::Duration::hours(14)),
            r"C:\Users\anton\anaconda3\python.exe",
        );

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::ImageMismatch)
        );
    }

    /// Случай 3б. Тот же чужой python, но конфиг отладочной сборки, где имя образа
    /// `python` законно. Здесь его держит уже время создания - страховка на случай,
    /// если продукту действительно нужен интерпретатор.
    #[test]
    fn skip_foreign_python_by_creation_time_in_dev_config() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = observed(
            Some(started - chrono::Duration::hours(14)),
            r"C:\Users\anton\anaconda3\python.exe",
        );

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG_DEV, OUR_USER),
            KillVerdict::Skip(SkipReason::CreatedOutsideWindow)
        );
    }

    /// Случай 3в. Отладочная сборка, свой же `python.exe`, созданный непосредственно
    /// перед записью состояния, - снимаем.
    #[test]
    fn kill_dev_python_engine_within_window() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = observed(
            Some(started - chrono::Duration::milliseconds(150)),
            r"C:\Python312\python.exe",
        );

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG_DEV, OUR_USER),
            KillVerdict::Kill
        );
    }

    /// Случай 4. Процесс принадлежит другому пользователю ОС - неприкосновенен
    /// (инвариант RDP, ради которого этот код и писался).
    #[test]
    fn skip_when_process_owner_is_another_user() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = ObservedProcess {
            owner: Some("AURORA-PC\\maria".to_string()),
            ..observed(Some(started), OUR_IMAGE)
        };

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::OwnerMismatch)
        );
    }

    /// Случай 4б. Запись оставлена другим пользователем на общей машине -
    /// отсекается сравнением строк, до всяких системных вызовов.
    #[test]
    fn skip_when_state_file_belongs_to_another_user() {
        let started = epoch(1_800_000_000);
        let mut state = state_at(started);
        state.user = "maria".to_string();
        let obs = observed(Some(started), OUR_IMAGE);

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::StateUserMismatch)
        );
    }

    /// Случай 5. Время создания получить не удалось - решение консервативное.
    /// Не снять своего зомби дешевле, чем убить чужой расчёт: зомби максимум
    /// удержит порт, и `allocate_port` возьмёт свободный.
    #[test]
    fn skip_when_creation_time_unavailable() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = observed(None, OUR_IMAGE);

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::CreationTimeUnknown)
        );
    }

    /// Владельца определить не удалось (процесс уже исчез либо нет прав) - тоже
    /// консервативно.
    #[test]
    fn skip_when_owner_unavailable() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = ObservedProcess {
            owner: None,
            ..observed(Some(started), OUR_IMAGE)
        };

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::OwnerUnknown)
        );
    }

    /// Путь к образу недоступен - консервативно.
    #[test]
    fn skip_when_image_path_unavailable() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);
        let obs = ObservedProcess {
            image_path: None,
            ..observed(Some(started), OUR_IMAGE)
        };

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::ImageUnknown)
        );
    }

    /// Нулевой идентификатор - снимать нечего.
    #[test]
    fn skip_when_pid_is_zero() {
        let started = epoch(1_800_000_000);
        let mut state = state_at(started);
        state.pid = 0;
        let obs = observed(Some(started), OUR_IMAGE);

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::InvalidPid)
        );
    }

    /// Файл состояния оставлен другим продуктом Aurora (общий каталог, ручное
    /// копирование) - не наш процесс.
    #[test]
    fn skip_when_state_belongs_to_another_product() {
        let started = epoch(1_800_000_000);
        let mut state = state_at(started);
        state.product = "com.aurora.docs-lab".to_string();
        let obs = observed(Some(started), OUR_IMAGE);

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::ProductMismatch)
        );
    }

    /// Битый `started_at` - сверить время не с чем, значит не снимаем.
    #[test]
    fn skip_when_started_at_unparsable() {
        let started = epoch(1_800_000_000);
        let mut state = state_at(started);
        state.started_at = "вчера вечером".to_string();
        let obs = observed(Some(started), OUR_IMAGE);

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::StartedAtUnparsable)
        );
    }

    /// Границы окна: ровно допуск - снимаем, на секунду дальше - нет.
    #[test]
    fn kill_window_boundaries_are_inclusive() {
        let started = epoch(1_800_000_000);
        let state = state_at(started);

        let on_edge = observed(
            Some(started + chrono::Duration::seconds(KILL_TIME_TOLERANCE_SECS)),
            OUR_IMAGE,
        );
        assert_eq!(
            should_kill(&state, &on_edge, &KILL_CFG, OUR_USER),
            KillVerdict::Kill
        );

        let past_edge = observed(
            Some(started + chrono::Duration::seconds(KILL_TIME_TOLERANCE_SECS + 1)),
            OUR_IMAGE,
        );
        assert_eq!(
            should_kill(&state, &past_edge, &KILL_CFG, OUR_USER),
            KillVerdict::Skip(SkipReason::CreatedOutsideWindow)
        );
    }

    /// `started_at` в файле состояния записан со смещением часового пояса -
    /// сравнение обязано приводить обе стороны к UTC.
    #[test]
    fn started_at_with_timezone_offset_is_normalized() {
        let started = epoch(1_800_000_000);
        let mut state = state_at(started);
        state.started_at = started
            .with_timezone(&chrono::FixedOffset::east_opt(3 * 3600).unwrap())
            .to_rfc3339();
        let obs = observed(Some(started - chrono::Duration::milliseconds(200)), OUR_IMAGE);

        assert_eq!(
            should_kill(&state, &obs, &KILL_CFG, OUR_USER),
            KillVerdict::Kill
        );
    }

    /// Сверка образа идёт по имени файла из полного пути, а не по подстроке в
    /// строке вывода утилиты: чужой каталог с похожим названием не проходит.
    #[test]
    fn image_matches_uses_file_name_not_substring() {
        assert!(image_matches(Some(OUR_IMAGE), &KILL_CFG));
        assert!(image_matches(
            Some(r"D:\build\econometrica-sidecar.exe"),
            &KILL_CFG
        ));
        assert!(!image_matches(
            Some(r"C:\econometrica-sidecar\notepad.exe"),
            &KILL_CFG
        ));
        assert!(!image_matches(Some(r"C:\Windows\py.exe"), &KILL_CFG_DEV));
        assert!(image_matches(Some(r"C:\Python312\python3.exe"), &KILL_CFG_DEV));
        assert!(!image_matches(None, &KILL_CFG));
    }

    /// Владелец приходит как `DOMAIN\user`, в состоянии и в `current_user_name()`
    /// домена нет - сверяем хвост, но не путаем разных пользователей.
    #[test]
    fn owner_matches_handles_domain_prefix() {
        assert!(owner_matches("AURORA-PC\\anton", "anton"));
        assert!(owner_matches("anton", "ANTON"));
        assert!(!owner_matches("AURORA-PC\\anton2", "anton"));
        assert!(!owner_matches("AURORA-PC\\anton", "unknown"));
        assert!(!owner_matches("AURORA-PC\\anton", ""));
    }
}
