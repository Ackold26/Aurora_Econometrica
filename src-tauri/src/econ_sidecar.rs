//! Econometrica sidecar lifecycle management - start, health check, auto-respawn, stop.
//!
//! # v1.0.9 - RDP hardening
//!
//! Порт НЕ хардкожен. На cold start `sidecar_runtime::allocate_port()` выдаёт
//! deterministic per-user port (SID hash → base+offset). Порт передаётся в
//! Python через `sys.argv[1]`. Состояние (port, pid, session_id, product, version)
//! пишется атомарно в `%LOCALAPPDATA%\com.aurora.econometrica\sidecar.json`.
//!
//! Кадый HTTP-запрос на /health проверяется handshake'ом - если product/version
//! чужой, Rust форс-киллит процесс (значит, мы попали на sidecar другого юзера
//! или старой версии на том же порту).
//!
//! # Features
//! - Cold start в Tauri setup()
//! - Proactive watchdog - respawn на freeze/crash (15s tick)
//! - Reactive recovery через `ensure_alive()` - из post_json при connect errors
//! - Zombie detection: TCP accepts но HTTP fails → force-kill + respawn
//! - Exponential backoff + banned cooldown - предотвращает spin на broken env
//! - Force restart - bypass cooldown, для "Перезапустить модуль" button
//! - Per-user process kill - убивает только процессы того же OS-юзера
//! - Kill-switch env var `AURORA_SIDECAR_LEGACY_PORT=1` - bypass discovery
//!
//! # Critical
//! Always use Stdio::null() - piped() без чтения deadlock'ит sidecar.

use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU16, AtomicU32, AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use log::{debug, error, info, warn};
use tauri::{AppHandle, Manager};
use tokio::sync::Mutex as AsyncMutex;
use wait_timeout::ChildExt;

use crate::sidecar_runtime::{
    self, allocate_port, current_user_name, delete_state_file, handshake_client,
    read_state_file, verify_handshake, write_state_file, HealthInfo, SidecarConfig,
    SidecarState,
};

const CHILD_WAIT_TIMEOUT: Duration = Duration::from_secs(3);
const GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(5);

/// Канонический конфиг для Econometrica. Остальные 9 продуктов имеют свой.
///
/// 🔴 `identifier_dir` — НЕ `product_id`. `product_id` фиксирован намеренно: это одно и то же
/// значение рукопожатия с Python-модулем (`PRODUCT_ID` в `server.py`), который у обеих редакций —
/// один и тот же собранный `econometrica-sidecar.exe`; разведение product_id по редакциям сломало
/// бы рукопожатие и модуль форс-killился бы сразу после каждого старта.
///
/// `identifier_dir` — это каталог state-файла `sidecar.json` (порт/PID/session_id) на стороне
/// Rust, редакции никак не касается. Он был захардкожен на базовый идентификатор для ОБЕИХ
/// редакций, хотя `AURORA_APP_IDENTIFIER` (из `build.rs`) уже разводит `com.aurora.econometrica` и
/// `com.aurora.econometrica.local` для durable_store/метрик. Клиент с обеими редакциями на одной
/// машине делил бы один state-файл: одинаковый детерминированный порт (выводится из SID, не из
/// редакции) + рукопожатие по одинаковому product_id не различает их — одна редакция могла убить
/// активный расчёт другой, приняв её процесс за старую копию себя.
const SIDECAR_CONFIG: SidecarConfig = SidecarConfig {
    product_id: "com.aurora.econometrica",
    version: env!("CARGO_PKG_VERSION"),
    legacy_port: 7430,
    identifier_dir: env!("AURORA_APP_IDENTIFIER"),
    process_exe_hint: "econometrica-sidecar",
    extra_image_hints: SIDECAR_IMAGE_HINTS,
};

/// Дополнительные допустимые имена образа движка.
///
/// В отладочной сборке `spawn_sidecar_proc` идёт сразу в `spawn_python_dev` —
/// движок там действительно запускается интерпретатором (`python -B server.py`),
/// поэтому имя образа процесса — `python.exe`.
///
/// 🔴 В релизной сборке движок — собранный `econometrica-sidecar.exe`, и список
/// пуст намеренно. Прежде `python`/`pythonw` принимались безусловно и в релизе:
/// этого хватало, чтобы под проверку подпал любой Jupyter, Anaconda, языковой
/// модуль редактора или движок соседнего продукта Aurora (у Docs Lab и Smart
/// Analytica движок RAG — буквально `python.exe`), запущенный тем же
/// пользователем. Аварийный откат релиза на `spawn_python_dev` существует, но
/// требует `server.py` рядом с приложением, чего в поставке нет; если такой
/// откат всё же сработал (запуск из рабочей копии), зомби-движок просто не будет
/// снят, а порт возьмётся свободный через `allocate_port`.
#[cfg(debug_assertions)]
const SIDECAR_IMAGE_HINTS: &[&str] = &["python", "pythonw"];
#[cfg(not(debug_assertions))]
const SIDECAR_IMAGE_HINTS: &[&str] = &[];

const MAX_CONSECUTIVE_FAILS: u32 = 5;
const BANNED_COOLDOWN_SECS: u64 = 300;
const WATCHDOG_INTERVAL_SECS: u64 = 15;
const WATCHDOG_FAIL_THRESHOLD: u32 = 3;
const WATCHDOG_STARTUP_DELAY_SECS: u64 = 30;
const HEALTH_TIMEOUT_SECS: u64 = 2;

static SIDECAR_PROCESS: OnceLock<Mutex<Option<Child>>> = OnceLock::new();
static APP_HANDLE: OnceLock<AppHandle> = OnceLock::new();
static RESPAWN_LOCK: OnceLock<AsyncMutex<()>> = OnceLock::new();
static HEALTH_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
static CONSECUTIVE_FAILS: AtomicU32 = AtomicU32::new(0);
static BANNED_UNTIL: AtomicU64 = AtomicU64::new(0);

/// Текущий порт. 0 = не назначен, читать legacy_port.
static CURRENT_PORT: AtomicU16 = AtomicU16::new(0);
/// Session_id **от sidecar'а** (Python генерит свой SESSION_ID при старте,
/// мы читаем его из первого /health и сохраняем здесь как source of truth).
/// Используется как X-Expected-Session header. `None` до первого успешного
/// handshake - клиент не шлёт header (Python middleware пропускает).
static CURRENT_SESSION: OnceLock<Mutex<Option<String>>> = OnceLock::new();

// ── Public API for clients (commands/econometrica.rs) ───────────────────────

/// Текущий порт sidecar'а - читать из клиентского кода перед HTTP-запросом.
/// Если ещё не allocate'ен, возвращает `SIDECAR_CONFIG.legacy_port` (back-compat).
pub fn current_port() -> u16 {
    let p = CURRENT_PORT.load(Ordering::Relaxed);
    if p == 0 {
        SIDECAR_CONFIG.legacy_port
    } else {
        p
    }
}

/// Session_id ожидаемого sidecar'а - для заголовка `X-Expected-Session`.
/// None до первого успешного handshake (sidecar ещё не сообщил свой session).
pub fn current_session_id() -> Option<String> {
    current_session_cell().lock().ok()?.clone()
}

fn current_session_cell() -> &'static Mutex<Option<String>> {
    CURRENT_SESSION.get_or_init(|| Mutex::new(None))
}

fn set_current_session(s: String) {
    if let Ok(mut lock) = current_session_cell().lock() {
        *lock = Some(s);
    }
}

fn clear_current_session() {
    if let Ok(mut lock) = current_session_cell().lock() {
        *lock = None;
    }
}

/// Базовый URL для HTTP-запросов к sidecar'у - http://127.0.0.1:<port>.
pub fn base_url() -> String {
    format!("http://127.0.0.1:{}", current_port())
}

// ── Internal state helpers ───────────────────────────────────────────────────

fn process_lock() -> &'static Mutex<Option<Child>> {
    SIDECAR_PROCESS.get_or_init(|| Mutex::new(None))
}

fn respawn_lock() -> &'static AsyncMutex<()> {
    RESPAWN_LOCK.get_or_init(|| AsyncMutex::new(()))
}

fn health_client() -> &'static reqwest::Client {
    HEALTH_CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(Duration::from_secs(HEALTH_TIMEOUT_SECS))
            .build()
            .unwrap_or_default()
    })
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn store_child(child: Child) {
    if let Ok(mut lock) = process_lock().lock() {
        *lock = Some(child);
    }
}

fn take_child() -> Option<Child> {
    process_lock().lock().ok().and_then(|mut l| l.take())
}

fn set_current_port(p: u16) {
    CURRENT_PORT.store(p, Ordering::Relaxed);
}

// ── Health probes ────────────────────────────────────────────────────────────

/// TCP probe - быстрая проверка, но uvicorn может accept TCP будучи deadlock'нутым.
fn tcp_responsive(port: u16) -> bool {
    use std::net::TcpStream;
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}")
            .parse()
            .unwrap_or_else(|_| "127.0.0.1:7430".parse().unwrap()),
        Duration::from_millis(500),
    )
    .is_ok()
}

/// Full handshake - HTTP /health + product/version validation.
/// Возвращает `Some(HealthInfo)` если этот sidecar наш (product совпал).
async fn probe_and_verify(port: u16) -> Option<HealthInfo> {
    verify_handshake(port, &SIDECAR_CONFIG, health_client()).await
}

/// Basic /health check без handshake (для watchdog - просто жив ли процесс).
async fn is_healthy_on(port: u16) -> bool {
    matches!(
        health_client()
            .get(format!("http://127.0.0.1:{port}/health"))
            .send()
            .await,
        Ok(r) if r.status().is_success()
    )
}

async fn is_healthy() -> bool {
    is_healthy_on(current_port()).await
}

/// Handshake check: HTTP health + product + (опционально) session_id match.
/// Используется при cold start для решения «reuse или respawn».
///
/// - Если expected_session=Some → требуем совпадения session_id (strict).
/// - Если expected_session=None → достаточно чтобы product совпал.
async fn is_healthy_and_ours(port: u16, expected_session: Option<&str>) -> bool {
    let Some(info) = probe_and_verify(port).await else {
        return false;
    };
    if let Some(expected) = expected_session {
        if info.session_id != expected {
            debug!(
                "handshake: session mismatch on :{port} (want={}, got={})",
                &expected[..8.min(expected.len())],
                &info.session_id[..8.min(info.session_id.len())]
            );
            return false;
        }
    }
    true
}

// ── Port cleanup (zombie kill) ───────────────────────────────────────────────

/// Снятие зависшего движка по ЗАПИСАННОМУ нами файлу состояния - только если процесс
/// действительно наш: тот же пользователь, тот же образ И создан в окне вокруг записанного
/// нами `started_at`.
///
/// 🔴 2026-08-12 (CPD-77): раньше идентификатор искали через
/// `cmd /C "netstat -ano | findstr :порт"`. Поиск был ИЗБЫТОЧЕН: мы сами записываем pid движка
/// в файл состояния при запуске (`write_initial_state`), то есть он известен во всех трёх точках
/// вызова. Ради уже имеющегося числа порождались три скрытых консольных процесса (`cmd` →
/// `netstat` → `findstr`), и получалась связка «разведка процессов по порту → снятие
/// найденного», которую поведенческая защита антивируса разбирает как вредоносную (10.08
/// Kaspersky снял оболочку продукта с диска у пользователя, вердикт PDM:Trojan.Win32.Generic —
/// поведенческий).
///
/// 🔴 2026-08-14 (CPD-79, регресс той правки): вместе с разбором вывода `netstat` пропала
/// нигде не записанная гарантия — найденный процесс был ДЕРЖАТЕЛЕМ НАШЕГО ПОРТА, то есть почти
/// наверняка наш. Именно на неё молча опиралась слабая последующая проверка, а вместе с ней
/// исчезла и она; в комментарии при этом было заявлено, что защита не ослабла — это неверно.
/// Файл состояния переживает завершение процесса (`delete_state_file` вызывается только на трёх
/// штатных путях: протухшая запись, принудительный перезапуск, штатное закрытие), после
/// перезагрузки Windows раздаёт номера процессов заново, а снятие идёт деревом
/// (`taskkill /T /F`). Пользователь с открытым Jupyter, Anaconda или соседним продуктом Aurora
/// мог получить молча убитый расчёт. Решение теперь принимает `sidecar_runtime::should_kill`,
/// где решающая проверка — время создания процесса против `started_at`.
#[cfg(windows)]
fn kill_sidecar_from_state(state: &SidecarState) {
    use crate::sidecar_runtime::KillVerdict;
    let pid = state.pid;
    if pid == 0 {
        return;
    }
    // Защита от самоубийства: если номер вдруг совпал с нашим собственным, снятие
    // унесло бы оболочку.
    if pid == std::process::id() {
        warn!("PID={pid} совпал с идентификатором самой оболочки - не трогаем");
        return;
    }

    // 🔴 2026-08-14 (High-3 аудита блока 2.4.9). Дескриптор процесса удерживается от
    // наблюдения ДО снятия и снятие идёт по нему же. Прежде дескриптор закрывался
    // сразу после снятия свойств, а снимали порождением `taskkill /PID n`: между этими
    // двумя моментами процесс мог завершиться сам, номер — освободиться и достаться
    // другому процессу, и снималось бы уже оно. Пока дескриптор жив, Windows номер не
    // переиспользует — гонка закрывается без единой дополнительной проверки.
    let Some(held) = sidecar_runtime::hold_and_observe(pid) else {
        debug!("PID={pid}: дескриптор не открылся (процесс уже завершился либо нет прав) - снимать нечего");
        return;
    };

    match sidecar_runtime::should_kill(state, held.observed(), &SIDECAR_CONFIG, &current_user_name())
    {
        KillVerdict::Kill => {
            info!("Killing zombie sidecar PID={pid}");
            match held.terminate() {
                Ok(()) => {
                    if held.wait_exit(3000) {
                        debug!("Зомби-движок PID={pid} снят");
                    } else {
                        warn!("Зомби-движок PID={pid} не завершился за 3 с после снятия");
                    }
                }
                Err(e) => {
                    warn!("Снятие PID={pid} по дескриптору не прошло ({e}) - запасной путь");
                    kill_process_tree_fallback(pid);
                }
            }
        }
        KillVerdict::Skip(reason) => {
            warn!("PID={pid} не снимаем: {reason}");
        }
    }
}

/// Запасной путь снятия — порождением системной утилиты, деревом (`/T`).
///
/// 🔴 Держится ТОЛЬКО на случай отказа `TerminateProcess` (дескриптор без права на
/// снятие: защита процесса сторонним средством, необычная политика). Основной путь
/// процессов не порождает вовсе — это и был смысл блока CPD-77: связка «скрытая
/// разведка процессов → принудительное снятие дерева» разбирается поведенческой
/// защитой антивируса как вредоносная.
///
/// Разница в семантике осознанная: `TerminateProcess` снимает только сам процесс,
/// `/T` — вместе с деревом потомков. Для этого движка потомки не долгоживущие:
/// выборка идёт либо NumPyro/JAX внутри одного процесса, либо PyMC с `cores=1`
/// (`engines/modeler.py`), а сборка движка — PyInstaller onedir, то есть отдельного
/// процесса-загрузчика нет. Порождается только компилятор PyTensor на время сборки
/// модели — короткий синхронный вызов, который завершается сам.
#[cfg(windows)]
fn kill_process_tree_fallback(pid: u32) {
    use std::os::windows::process::CommandExt;
    let _ = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .creation_flags(0x08000000)
        .output();
}

#[cfg(not(windows))]
fn kill_sidecar_from_state(_state: &SidecarState) {
    if let Some(mut child) = take_child() {
        let _ = child.kill();
        let _ = child.wait_timeout(CHILD_WAIT_TIMEOUT);
    }
}

/// То же, но состояние читается из файла - для точек, где оно не держится в руках.
/// Отсутствие файла = снимать нечего (наш дочерний процесс в памяти закрывается
/// вызывающей стороной через `take_child`).
fn kill_known_sidecar() {
    match read_state_file(&SIDECAR_CONFIG) {
        Some(state) => kill_sidecar_from_state(&state),
        None => debug!("Файла состояния нет - идентификатор движка неизвестен, снимать нечего"),
    }
}

// ── Spawn paths ──────────────────────────────────────────────────────────────

fn spawn_bundled_exe(app_handle: &AppHandle, port: u16) -> Result<Child, String> {
    let resolve = |p: &str| {
        app_handle
            .path()
            .resolve(p, tauri::path::BaseDirectory::Resource)
            .ok()
    };
    let exe_path = [
        "sidecar/econometrica/econometrica-sidecar.exe",
        "_up_/sidecar/econometrica/econometrica-sidecar.exe",
    ]
    .iter()
    .filter_map(|p| resolve(p))
    .find(|p| p.exists())
    .ok_or_else(|| "Bundled sidecar not found in sidecar/ or _up_/sidecar/".to_string())?;

    let mut cmd = Command::new(&exe_path);
    cmd.arg(port.to_string())
        .env("AURORA_PRODUCT_ID", SIDECAR_CONFIG.product_id)
        .env("AURORA_PRODUCT_VERSION", SIDECAR_CONFIG.version)
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }

    cmd.spawn()
        .map_err(|e| format!("Failed to spawn bundled sidecar: {e}"))
}

fn spawn_python_dev(port: u16) -> Result<Child, String> {
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").unwrap_or_else(|_| ".".to_string());
    let sidecar_dir = std::path::Path::new(&manifest_dir)
        .parent()
        .unwrap_or(std::path::Path::new("."))
        .join("sidecar")
        .join("econometrica");

    if !sidecar_dir.join("server.py").exists() {
        return Err(format!(
            "server.py not found at: {}",
            sidecar_dir.display()
        ));
    }

    #[cfg(windows)]
    let python = "python";
    #[cfg(not(windows))]
    let python = "python3";

    let mut cmd = Command::new(python);
    cmd.args(["-B", "server.py", &port.to_string()])
        .current_dir(&sidecar_dir)
        .env("AURORA_PRODUCT_ID", SIDECAR_CONFIG.product_id)
        .env("AURORA_PRODUCT_VERSION", SIDECAR_CONFIG.version)
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }

    cmd.spawn()
        .map_err(|e| format!("Failed to spawn python sidecar: {e}"))
}

fn spawn_sidecar_proc(app_handle: &AppHandle, port: u16) -> Result<Child, String> {
    if !cfg!(debug_assertions) {
        match spawn_bundled_exe(app_handle, port) {
            Ok(c) => return Ok(c),
            Err(e) => warn!("Bundled sidecar failed, falling back to python: {e}"),
        }
    }
    spawn_python_dev(port)
}

// ── Public API ───────────────────────────────────────────────────────────────

/// Cold start - call once from setup(). Stores app handle for later respawns.
///
/// Decision tree:
/// 1. Есть stale sidecar.json с handshake OK (наш port, product, session_id)
///    → просто reuse, НЕ spawn'им заново (idempotent).
/// 2. Есть sidecar.json но handshake fail → foreign/stale. Пробуем убить
///    process, удалить файл, allocate new port, spawn.
/// 3. Нет sidecar.json → allocate new port, spawn.
pub fn start_sidecar(app_handle: &AppHandle) {
    let _ = APP_HANDLE.set(app_handle.clone());

    // Попытка reuse. Читаем state file и делаем handshake.
    if let Some(state) = read_state_file(&SIDECAR_CONFIG) {
        let saved_port = state.port;
        let saved_session = state.session_id.clone();
        // Если saved_session пустой (cold start прервался до handshake'а) -
        // проверяем только product match, не strict session. Product mismatch =
        // форрин sidecar → respawn, а пустой session → benign transient state.
        let session_check = if saved_session.is_empty() {
            None
        } else {
            Some(saved_session.as_str())
        };
        let is_ours = tauri::async_runtime::block_on(async {
            is_healthy_and_ours(saved_port, session_check).await
        });
        if is_ours {
            info!(
                "Sidecar reuse: port={saved_port} session={}… (pid={})",
                &saved_session[..8.min(saved_session.len())],
                state.pid
            );
            set_current_port(saved_port);
            set_current_session(saved_session);
            return;
        }
        info!(
            "Sidecar state file stale (session_id/product mismatch or dead). \
             Cleaning up and respawning."
        );
        // Попытка убить старый процесс по нашей же записи - только если он выдержит все
        // проверки `should_kill` (пользователь, образ, время создания против started_at).
        kill_sidecar_from_state(&state);
        delete_state_file(&SIDECAR_CONFIG);
    }

    // Cold spawn.
    let port = match allocate_port(&SIDECAR_CONFIG) {
        Ok(p) => p,
        Err(e) => {
            warn!(
                "allocate_port failed: {e}. Falling back to legacy port {}.",
                SIDECAR_CONFIG.legacy_port
            );
            SIDECAR_CONFIG.legacy_port
        }
    };
    set_current_port(port);
    clear_current_session(); // Начинаем cold start - session_id будет задан после handshake'а
    info!("Starting Econometrica sidecar on :{port} (session: TBD from sidecar handshake)");

    match spawn_sidecar_proc(app_handle, port) {
        Ok(child) => {
            let pid = child.id();
            info!("Econometrica sidecar started (PID={pid}, port={port})");
            store_child(child);
            // Initial state file с пустым session_id (hint). Python-sidecar
            // генерит свой SESSION_ID при запуске, wait_for_sidecar_ready
            // прочитает его из /health и заполнит state файл.
            let _ = write_initial_state(port, pid, "");
            // Background task: ждём когда sidecar будет health-ready, синхронизируем
            // CURRENT_SESSION + state file с настоящим session_id от Python-sidecar'а.
            tauri::async_runtime::spawn(async move {
                if wait_for_sidecar_ready().await {
                    info!("Cold start handshake complete - state synced");
                } else {
                    warn!("Cold start handshake timeout - next restart may force-respawn");
                }
            });
        }
        Err(e) => {
            warn!("Failed to start econometrica sidecar: {e}. Compute features unavailable.");
        }
    }
}

/// Пишет state с pid + port до handshake (как hint). После ready получаем
/// реальный session_id от sidecar'а и обновляем.
fn write_initial_state(port: u16, pid: u32, session_id: &str) -> Result<(), String> {
    // Полный путь образа снимаем У ЖИВОГО процесса, которого только что породили, а не
    // берём путь, по которому его запускали: сверять придётся ровно с тем, что вернёт
    // `QueryFullProcessImageNameW` при следующем наблюдении, и одинаковый источник строки
    // избавляет от расхождений в написании пути. Номер процесса в этот момент занят
    // гарантированно — дескриптор порождённого процесса держит `store_child`.
    // Пусто (не удалось снять) → сверка при снятии откатится на сравнение по имени образа.
    let image_path = sidecar_runtime::observe_process(pid)
        .image_path
        .unwrap_or_default();
    if image_path.is_empty() {
        debug!("Путь образа движка (PID={pid}) снять не удалось - сверка редакций ослаблена");
    }
    let state = SidecarState {
        port,
        pid,
        session_id: session_id.to_string(),
        product: SIDECAR_CONFIG.product_id.to_string(),
        version: SIDECAR_CONFIG.version.to_string(),
        user: current_user_name(),
        started_at: chrono::Utc::now().to_rfc3339(),
        image_path,
    };
    write_state_file(&SIDECAR_CONFIG, &state).map_err(|e| e.to_string())
}

/// Wait for sidecar to be healthy. Returns true if ready within timeout.
/// После успеха обновляет sidecar.json с session_id от sidecar'а (он может
/// отличаться от нашего если произошёл respawn внутри того же GUI).
pub async fn wait_for_sidecar_ready() -> bool {
    let delays_ms = [300, 500, 1000, 1000, 2000, 2000, 3000, 3000, 5000, 5000];
    let port = current_port();
    let client = handshake_client();

    for (attempt, &delay_ms) in delays_ms.iter().enumerate() {
        if let Some(info) = verify_handshake(port, &SIDECAR_CONFIG, &client).await {
            info!(
                "Econometrica sidecar healthy after {} attempt(s), session={}…",
                attempt + 1,
                &info.session_id[..8.min(info.session_id.len())]
            );
            // Обновить session_id - используем то что сказал sidecar (source of truth)
            set_current_session(info.session_id.clone());
            if let Some(mut state) = read_state_file(&SIDECAR_CONFIG) {
                state.session_id = info.session_id.clone();
                state.version = info.version.clone();
                let _ = write_state_file(&SIDECAR_CONFIG, &state);
            }
            return true;
        }
        if attempt == 0 {
            info!("Waiting for econometrica sidecar on :{port} to start...");
        }
        tokio::time::sleep(Duration::from_millis(delay_ms)).await;
    }

    error!("Econometrica sidecar did not become healthy within timeout");
    false
}

/// Ensure sidecar is alive; respawn if not. Idempotent, thread-safe, bounded retries.
pub async fn ensure_alive() -> bool {
    if is_healthy().await {
        CONSECUTIVE_FAILS.store(0, Ordering::Relaxed);
        return true;
    }

    let banned_until = BANNED_UNTIL.load(Ordering::Relaxed);
    let now = now_secs();
    if banned_until > now {
        warn!(
            "Sidecar respawn banned for {}s (broken env suspected - use manual restart)",
            banned_until - now
        );
        return false;
    }

    let Some(app_handle) = APP_HANDLE.get() else {
        error!("Cannot respawn sidecar: APP_HANDLE not initialized");
        return false;
    };

    let _guard = respawn_lock().lock().await;

    if is_healthy().await {
        CONSECUTIVE_FAILS.store(0, Ordering::Relaxed);
        return true;
    }

    let fails = CONSECUTIVE_FAILS.fetch_add(1, Ordering::Relaxed) + 1;
    info!("Sidecar unhealthy - respawn attempt #{fails}");

    if fails > 1 {
        let backoff_secs = 2_u64.pow((fails - 1).min(4));
        tokio::time::sleep(Duration::from_secs(backoff_secs)).await;
    }

    let port = current_port();

    if tcp_responsive(port) {
        warn!("Sidecar TCP accepts but HTTP unresponsive - killing deadlocked process");
        kill_known_sidecar();
        tokio::time::sleep(Duration::from_secs(1)).await;
    }

    if let Some(mut child) = take_child() {
        let _ = child.kill();
        let _ = child.wait_timeout(CHILD_WAIT_TIMEOUT);
    }

    // При respawn порт МОЖЕТ измениться (если preferred занят другим зомби).
    let new_port = match allocate_port(&SIDECAR_CONFIG) {
        Ok(p) => p,
        Err(e) => {
            warn!("allocate_port failed on respawn: {e}. Using current.");
            port
        }
    };
    if new_port != port {
        info!("Respawn on different port: {port} → {new_port}");
        set_current_port(new_port);
    }

    clear_current_session(); // новый sidecar → новый session_id, получим через handshake
    match spawn_sidecar_proc(app_handle, new_port) {
        Ok(child) => {
            let pid = child.id();
            info!("Sidecar respawned (PID={pid}, port={new_port}) - waiting for health");
            store_child(child);
            let _ = write_initial_state(new_port, pid, "");
        }
        Err(e) => {
            error!("Respawn spawn failed: {e}");
            maybe_ban(fails);
            return false;
        }
    }

    let healthy = wait_for_sidecar_ready().await;
    if healthy {
        CONSECUTIVE_FAILS.store(0, Ordering::Relaxed);
        info!("Sidecar respawn successful");
    } else {
        error!("Sidecar respawned but did not reach healthy state");
        maybe_ban(fails);
    }
    healthy
}

fn maybe_ban(fails: u32) {
    if fails >= MAX_CONSECUTIVE_FAILS {
        let until = now_secs() + BANNED_COOLDOWN_SECS;
        BANNED_UNTIL.store(until, Ordering::Relaxed);
        error!(
            "Sidecar failed {fails}× - banning auto-respawn for {BANNED_COOLDOWN_SECS}s. \
             Check Python env / MCMC logs. Use manual restart to clear."
        );
    }
}

/// Force restart - bypass banned cooldown, reset counters, kill + spawn fresh.
pub async fn force_restart() -> Result<(), String> {
    CONSECUTIVE_FAILS.store(0, Ordering::Relaxed);
    BANNED_UNTIL.store(0, Ordering::Relaxed);

    let _guard = respawn_lock().lock().await;
    let port = current_port();

    // Graceful shutdown first (correct cleanup при активном pm.sample)
    if tcp_responsive(port) {
        let _ = request_graceful_shutdown(port).await;
        kill_known_sidecar();
        tokio::time::sleep(Duration::from_secs(1)).await;
    }
    if let Some(mut child) = take_child() {
        let _ = child.kill();
        let _ = child.wait_timeout(CHILD_WAIT_TIMEOUT);
    }
    delete_state_file(&SIDECAR_CONFIG);

    let app_handle = APP_HANDLE
        .get()
        .ok_or_else(|| "APP_HANDLE not initialized".to_string())?;

    let new_port = allocate_port(&SIDECAR_CONFIG).unwrap_or(SIDECAR_CONFIG.legacy_port);
    set_current_port(new_port);
    clear_current_session();

    let child = spawn_sidecar_proc(app_handle, new_port)?;
    let pid = child.id();
    info!("Sidecar force-restarted (PID={pid}, port={new_port})");
    store_child(child);
    let _ = write_initial_state(new_port, pid, "");

    if wait_for_sidecar_ready().await {
        Ok(())
    } else {
        Err("Sidecar did not become healthy within timeout".to_string())
    }
}

/// Background watchdog - proactive respawn on freeze/crash.
pub fn spawn_watchdog() {
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(Duration::from_secs(WATCHDOG_STARTUP_DELAY_SECS)).await;

        let mut consecutive_fails = 0u32;
        loop {
            tokio::time::sleep(Duration::from_secs(WATCHDOG_INTERVAL_SECS)).await;

            if is_healthy().await {
                if consecutive_fails > 0 {
                    info!("Watchdog: sidecar recovered");
                }
                consecutive_fails = 0;
                continue;
            }

            consecutive_fails += 1;
            warn!("Watchdog: sidecar unhealthy ({consecutive_fails}/{WATCHDOG_FAIL_THRESHOLD})");

            if consecutive_fails >= WATCHDOG_FAIL_THRESHOLD {
                info!("Watchdog triggering respawn");
                let _ = ensure_alive().await;
                consecutive_fails = 0;
            }
        }
    });
}

/// Graceful shutdown request через HTTP /shutdown. Возвращает Ok если sidecar
/// ответил 200, иначе Err (caller всё равно делает force kill).
async fn request_graceful_shutdown(port: u16) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}/shutdown");
    health_client()
        .post(&url)
        .send()
        .await
        .map(|_| ())
        .map_err(|e| e.to_string())
}

/// Stop sidecar - call from window close handler. Idempotent.
///
/// 1. POST /shutdown → ждём до 5 секунд
/// 2. Если не остановился → force kill
/// 3. Удаляем sidecar.json
pub fn stop_sidecar() {
    let Some(mut child) = take_child() else {
        return;
    };
    let pid = child.id();
    let port = current_port();

    // Graceful сначала
    let graceful = tauri::async_runtime::block_on(async {
        if request_graceful_shutdown(port).await.is_ok() {
            // Wait до 5 секунд на mягкое завершение
            for _ in 0..10 {
                tokio::time::sleep(Duration::from_millis(500)).await;
                if !tcp_responsive(port) {
                    return true;
                }
            }
        }
        false
    });

    if graceful {
        debug!("Sidecar exited gracefully (PID={pid})");
    } else {
        // Force kill process tree
        warn!("Sidecar did not exit on /shutdown within {GRACEFUL_SHUTDOWN_TIMEOUT:?}, force-killing PID={pid}");
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            let _ = Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .creation_flags(0x08000000)
                .output();
        }
        let _ = child.kill();
    }
    let _ = child.wait();
    delete_state_file(&SIDECAR_CONFIG);
    info!("Econometrica sidecar stopped (was PID={pid})");
}

#[cfg(test)]
mod identifier_dir_tests {
    /// Регрессия: `identifier_dir` раньше был жёстко `"com.aurora.econometrica"` для ОБЕИХ
    /// редакций — локальная и облачная делили один state-файл `sidecar.json` (порт/PID),
    /// а рукопожатие по одинаковому `product_id` их не различало. Клиент с обеими
    /// редакциями на одной машине рисковал получить убитый форс-киллом активный расчёт.
    #[test]
    fn identifier_dir_tracks_build_edition_not_hardcoded() {
        assert_eq!(
            super::SIDECAR_CONFIG.identifier_dir,
            env!("AURORA_APP_IDENTIFIER"),
            "identifier_dir обязан идти от идентификатора сборки (build.rs), не быть отдельной константой"
        );
        let src = include_str!("econ_sidecar.rs");
        assert!(
            !src.contains("identifier_dir: \"com.aurora.econometrica\""),
            "identifier_dir снова захардкожен строковым литералом — регресс общего state-файла редакций"
        );
    }
}
