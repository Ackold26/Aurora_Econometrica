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
use std::sync::atomic::{AtomicBool, AtomicU16, AtomicU32, AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

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

/// Срок холодного старта движка, отсчитываемый от МОМЕНТА ПОРОЖДЕНИЯ процесса (не от вызова
/// ожидания). Пока процесс жив, ещё ни разу не ответил после этого порождения и срок не вышел,
/// движок «запускается»: сторож не считает неудачи, `ensure_alive` не снимает его, а ждёт.
///
/// Обоснование значения – журнал установленной 2.5.9 (`Optimizer MMM.log`, 10.08–29.09.2026):
/// худший записанный старт ≈ 79 с от порождения (29.09, порождение 15:36:06, ответ 15:37:25);
/// 120 с – запас ×1,5. Худший откат правки ограничен этим же сроком: процесс, зависший на
/// старте, снимется не позже чем через 120 с + три проверки сторожа.
const COLD_START_GRACE_SECS: u64 = 120;
/// Срок ожидания, когда момент порождения неизвестен (переиспользован движок прошлого сеанса,
/// своего порождения в этом сеансе не было).
const UNKNOWN_SPAWN_WAIT_SECS: u64 = 45;

static SIDECAR_PROCESS: OnceLock<Mutex<Option<Child>>> = OnceLock::new();
static APP_HANDLE: OnceLock<AppHandle> = OnceLock::new();
static RESPAWN_LOCK: OnceLock<AsyncMutex<()>> = OnceLock::new();
static HEALTH_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
static CONSECUTIVE_FAILS: AtomicU32 = AtomicU32::new(0);
static BANNED_UNTIL: AtomicU64 = AtomicU64::new(0);

/// Эпоха монотонных часов процесса программы. Монотонные, а не `SystemTime`: перевод системных
/// часов назад дал бы на `now_secs()` вечное «запускается».
static SPAWN_EPOCH: OnceLock<Instant> = OnceLock::new();
/// Момент последнего порождения движка, мс от `SPAWN_EPOCH`; 0 = в этом сеансе не порождали.
/// Выставляется ТОЛЬКО в `store_child` – через него проходят все три пути порождения.
/// Это не флаг «запускается», который надо снимать: состояние выводится из момента порождения,
/// поэтому ранний возврат или паника между порождением и ожиданием ничего не оставляют висеть.
static SPAWNED_AT_MS: AtomicU64 = AtomicU64::new(0);
/// Движок ответил на рукопожатие после последнего порождения.
static READY_SINCE_SPAWN: AtomicBool = AtomicBool::new(false);

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

/// Монотонные миллисекунды от `SPAWN_EPOCH`.
fn now_ms() -> u64 {
    SPAWN_EPOCH.get_or_init(Instant::now).elapsed().as_millis() as u64
}

fn store_child(child: Child) {
    // Сначала «ещё не готов», потом момент порождения: читатель, увидевший новый момент,
    // обязан увидеть и сброшенную готовность (иначе на миг – «устоялся» вместо «запускается»).
    READY_SINCE_SPAWN.store(false, Ordering::SeqCst);
    SPAWNED_AT_MS.store(now_ms().max(1), Ordering::SeqCst);
    if let Ok(mut lock) = process_lock().lock() {
        *lock = Some(child);
    }
}

fn take_child() -> Option<Child> {
    process_lock().lock().ok().and_then(|mut l| l.take())
}

// ── Cold start phase ─────────────────────────────────────────────────────────

/// Что известно о собственном дочернем процессе движка.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ChildState {
    /// Процесс жив (`try_wait` → `Ok(None)`).
    Alive,
    /// Процесс завершился, с кодом выхода, если система его сообщила.
    Exited(Option<i32>),
    /// Своего процесса нет (переиспользован движок прошлого сеанса, ячейку опустошил
    /// `take_child`), блокировка отравлена или система не ответила.
    Unknown,
}

/// Состояние дочернего процесса. `process_lock` держится только на сам `try_wait` и
/// отпускается до возврата – вызывать можно откуда угодно, но не под `process_lock`.
fn child_state() -> ChildState {
    let Ok(mut lock) = process_lock().lock() else {
        return ChildState::Unknown;
    };
    match lock.as_mut() {
        None => ChildState::Unknown,
        Some(child) => match child.try_wait() {
            Ok(None) => ChildState::Alive,
            Ok(Some(status)) => ChildState::Exited(status.code()),
            Err(_) => ChildState::Unknown,
        },
    }
}

/// Фаза жизненного цикла движка с точки зрения «можно ли его снимать».
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Phase {
    /// Жив, после порождения ещё не отвечал, срок холодного старта не вышел – не снимать, ждать.
    Starting,
    /// Всё прочее, включая «неизвестно» – прежнее поведение сторожа и восстановления.
    Settled,
    /// Собственный процесс завершился – ждать нечего.
    Died,
}

/// Чистое решение о фазе: все входы параметрами, без глобалов.
fn cold_start_phase(
    now_ms: u64,
    spawned_at_ms: u64,
    ready: bool,
    child: ChildState,
    grace_ms: u64,
) -> Phase {
    match child {
        ChildState::Exited(_) => Phase::Died,
        ChildState::Alive
            if !ready && spawned_at_ms > 0 && now_ms.saturating_sub(spawned_at_ms) < grace_ms =>
        {
            Phase::Starting
        }
        _ => Phase::Settled,
    }
}

/// Фаза движка сейчас – добывание входов для [`cold_start_phase`].
fn current_phase() -> Phase {
    cold_start_phase(
        now_ms(),
        SPAWNED_AT_MS.load(Ordering::SeqCst),
        READY_SINCE_SPAWN.load(Ordering::SeqCst),
        child_state(),
        COLD_START_GRACE_SECS * 1000,
    )
}

/// Один шаг сторожа: (неудач подряд, здоров ли, фаза, порог) → (новый счётчик, перезапускать ли).
/// Цикл сторожа только исполняет это решение – так его можно проверить без процессов.
fn watchdog_step(fails: u32, healthy: bool, phase: Phase, threshold: u32) -> (u32, bool) {
    if healthy {
        return (0, false);
    }
    if phase == Phase::Starting {
        return (0, false);
    }
    let fails = fails + 1;
    if fails >= threshold {
        (0, true)
    } else {
        (fails, false)
    }
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

/// Полный путь образа движка, каким он стоит В ЭТОЙ УСТАНОВКЕ, — то, с чем сверяется
/// образ процесса, занявшего наш порт.
///
/// Берётся оттуда же, откуда движок запускается (`resolve_bundled_exe`), то есть это
/// статический факт установки, а не запись, которая может устареть. Он же различает
/// облачную и локальную редакции продукта: `product_id` у них намеренно одинаков
/// (рукопожатие с Python-модулем), пользователь один, имя файла образа одно и то же —
/// отличается только каталог установки.
///
/// В ОТЛАДОЧНОЙ сборке — `None`: `spawn_sidecar_proc` идёт там сразу в
/// `spawn_python_dev`, движок запускается интерпретатором, и ожидаемым путём оказался
/// бы путь до `python.exe`. Сверка в этом случае откатывается на прежнее сравнение по
/// имени образа, где `SIDECAR_IMAGE_HINTS` как раз содержит `python`/`pythonw`.
/// Само РЕШЕНИЕ, отделённое от добывания пути, — чтобы его можно было проверить.
///
/// 🔴 Вынесено после того, как мутация «в релизе неразрешённый путь снова разрешает откат на
/// имя» пережила весь набор тестов: проверки били по чистой функции решения, которой значение
/// передают уже готовым, а вычисляется оно здесь — в коде, привязанном к признаку сборки и к
/// глобальному дескриптору приложения. Проверить такое на месте нельзя, поэтому решение
/// принимает свои входы параметрами, а добывание остаётся в вызывающем.
fn classify_expected_image(is_release: bool, resolved: Option<String>) -> ExpectedImageOwned {
    if !is_release {
        // Отладочная сборка: движок запускают интерпретатором, своего образа у нас нет по
        // построению — откат на сверку по имени здесь законен.
        return ExpectedImageOwned::NameFallbackAllowed;
    }
    match resolved {
        Some(path) => ExpectedImageOwned::Known(path),
        // Релиз, а путь не разрешён: образ изъят антивирусом либо установка повреждена.
        // Снимать нельзя — своего образа мы не знаем.
        None => ExpectedImageOwned::Unknown,
    }
}

#[cfg(windows)]
fn expected_engine_image_path() -> ExpectedImageOwned {
    if cfg!(debug_assertions) {
        return classify_expected_image(false, None);
    }
    // 🔴 Ниже — РЕЛИЗ. Здесь «не смогли разрешить путь» НЕ равнозначно «пути не бывает»:
    // образ мог быть изъят антивирусом или установка повреждена. Прежняя редакция
    // возвращала в обоих случаях пусто, решение откатывалось на сверку по имени, а имя у
    // облачной и локальной редакций одинаково — и продукт снимал чужой идущий расчёт
    // (High-1 прошлого аудита, найден заново внешним аудитом блока 2.4.10).
    let resolved = APP_HANDLE
        .get()
        .and_then(resolve_bundled_exe)
        .map(|path| sidecar_runtime::canonical_path_for_compare(&path.to_string_lossy()));
    if resolved.is_none() {
        warn!(
            "Ожидаемый путь образа движка не разрешён (дескриптор приложения не выставлен, образ \
             изъят антивирусом либо установка повреждена) — снятие держателя порта отменяется: \
             без своего пути мы не отличим собственный движок от движка другой редакции"
        );
    }
    classify_expected_image(true, resolved)
}

/// Владеющий двойник [`sidecar_runtime::ExpectedImage`]: та же тройка случаев, но со своей
/// строкой — заимствовать её из временного значения на месте вызова неудобно.
#[derive(Debug)]
enum ExpectedImageOwned {
    Known(String),
    NameFallbackAllowed,
    Unknown,
}

impl ExpectedImageOwned {
    fn as_ref(&self) -> sidecar_runtime::ExpectedImage<'_> {
        match self {
            Self::Known(p) => sidecar_runtime::ExpectedImage::Known(p),
            Self::NameFallbackAllowed => sidecar_runtime::ExpectedImage::NameFallbackAllowed,
            Self::Unknown => sidecar_runtime::ExpectedImage::Unknown,
        }
    }
}

/// Снятие зависшего движка, ЗАНЯВШЕГО наш порт: держателя называет операционная
/// система, а не наша собственная запись.
///
/// 🔴 2026-08-12 (CPD-77): раньше держателя порта искали через
/// `cmd /C "… -ano | … :порт"` — три скрытых консольных процесса, и получалась связка
/// «разведка процессов по порту → снятие найденного», которую поведенческая защита
/// антивируса разбирает как вредоносную (10.08 Kaspersky снял оболочку продукта с диска у
/// пользователя, вердикт PDM:Trojan.Win32.Generic — поведенческий). Правка убрала
/// порождение процессов, перейдя на номер из нашего файла состояния.
///
/// 🔴 2026-08-14 (CPD-79, регресс той правки): вместе с разбором вывода утилиты пропала
/// нигде не записанная гарантия — найденный процесс был ДЕРЖАТЕЛЕМ НАШЕГО ПОРТА, то есть
/// почти наверняка наш. Файл состояния переживает завершение процесса, после перезагрузки
/// Windows раздаёт номера процессов заново, и записанный номер мог достаться постороннему —
/// пользователь с открытым Jupyter, Anaconda или соседним продуктом Aurora получал молча
/// убитый расчёт.
///
/// 🔴 2026-08-14 (эта правка): гарантия возвращена, но БЕЗ подпроцессов. Держателя порта
/// называет `GetExtendedTcpTable` — прямой системный вызов, 7–15 мс, обе таблицы адресов.
/// Заплата по времени создания процесса (окно вокруг `started_at`) больше не нужна и
/// упразднена: она лечила устаревание записи, а устаревать больше нечему.
///
/// Порядок ровно такой, как в решении [`sidecar_runtime::should_kill_port_holder`]:
/// спросить систему → отсечь самоубийство ДО наблюдения → удержать дескриптор →
/// переспросить систему → сверить владельца и образ → снять по удерживаемому дескриптору.
#[cfg(windows)]
fn kill_port_holder(port: u16) {
    use crate::sidecar_runtime::{KillVerdict, PortHolderFacts};

    let self_pid = std::process::id();
    let holders = sidecar_runtime::listening_port_owners(port);

    // Отсекаем «слушать некому», «держателей несколько» и самоубийство ДО открытия
    // дескриптора — наблюдение это системный вызов, а трогать себя нельзя вовсе.
    let holder = match sidecar_runtime::holder_worth_observing(&holders, self_pid) {
        Ok(pid) => pid,
        Err(reason) => {
            debug!("Порт {port}: снимать нечего - {reason}");
            return;
        }
    };

    // 🔴 High-3 аудита блока 2.4.9. Дескриптор удерживается от наблюдения ДО снятия и
    // снятие идёт по нему же: пока дескриптор жив, Windows номер процесса не
    // переиспользует.
    let held = sidecar_runtime::hold_and_observe(holder);

    // Переспрос ПОСЛЕ удержания: закрывает зазор между ответом таблицы и открытием
    // дескриптора, который само удержание закрыть не может.
    let holders_after = sidecar_runtime::listening_port_owners(port);

    // Обе стороны сравнения приводим к одному написанию до чистого решения: короткие
    // имена 8.3 и символические ссылки снимаются только здесь, системным вызовом.
    let observed = held.as_ref().map(|h| {
        let mut o = h.observed().clone();
        o.image_path = o
            .image_path
            .as_deref()
            .map(sidecar_runtime::canonical_path_for_compare);
        o
    });
    let expected = expected_engine_image_path();

    let facts = PortHolderFacts {
        holders: &holders,
        self_pid,
        observed: observed.as_ref(),
        holders_after: &holders_after,
        expected_image: expected.as_ref(),
    };

    match sidecar_runtime::should_kill_port_holder(&facts, &SIDECAR_CONFIG, &current_user_name()) {
        KillVerdict::Skip(reason) => {
            warn!("Держателя порта {port} (PID={holder}) не снимаем: {reason}");
        }
        KillVerdict::Kill => {
            // Решение «снимать» достижимо только когда дескриптор удержан - иначе была
            // бы причина отказа ObserveFailed.
            let Some(held) = held else {
                error!("Порт {port}: решение снимать при неудержанном дескрипторе - не снимаем");
                return;
            };
            info!("Снимаем зависший движок на порту {port} (PID={holder})");
            match held.terminate() {
                Ok(()) => {
                    if held.wait_exit(3000) {
                        debug!("Зомби-движок PID={holder} снят");
                    } else {
                        warn!("Зомби-движок PID={holder} не завершился за 3 с после снятия");
                    }
                }
                Err(e) => {
                    warn!("Снятие PID={holder} по дескриптору не прошло ({e}) - запасной путь");
                    kill_process_tree_fallback(holder);
                }
            }
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

/// На не-Windows системного вопроса «кто слушает порт» нет — снимаем только
/// собственный дочерний процесс, как и прежде.
#[cfg(not(windows))]
fn kill_port_holder(_port: u16) {
    if let Some(mut child) = take_child() {
        let _ = child.kill();
        let _ = child.wait_timeout(CHILD_WAIT_TIMEOUT);
    }
}

// ── Spawn paths ──────────────────────────────────────────────────────────────

/// Путь к собранному движку в этой установке — ОДИН источник и для запуска
/// (`spawn_bundled_exe`), и для ожидаемого пути образа при снятии зомби
/// (`expected_engine_image_path`). Разъехаться этим двум местам нельзя: тогда
/// собственный зомби перестал бы сниматься молча.
fn resolve_bundled_exe(app_handle: &AppHandle) -> Option<std::path::PathBuf> {
    [
        "sidecar/econometrica/econometrica-sidecar.exe",
        "_up_/sidecar/econometrica/econometrica-sidecar.exe",
    ]
    .iter()
    .filter_map(|p| {
        app_handle
            .path()
            .resolve(p, tauri::path::BaseDirectory::Resource)
            .ok()
    })
    .find(|p| p.exists())
}

fn spawn_bundled_exe(app_handle: &AppHandle, port: u16) -> Result<Child, String> {
    let exe_path = resolve_bundled_exe(app_handle)
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
        // Спрашиваем систему, кто держит этот порт СЕЙЧАС, и снимаем держателя только
        // если он выдержит все проверки `should_kill_port_holder` (один держатель, не мы,
        // тот же пользователь, образ = движок этой установки, держатель не сменился).
        kill_port_holder(saved_port);
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
                match wait_for_sidecar_ready().await {
                    WaitOutcome::Ready => info!("Cold start handshake complete - state synced"),
                    other => warn!(
                        "Cold start handshake not complete ({other:?}) - next restart may force-respawn"
                    ),
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
    // Полный путь образа снимаем у живого процесса, которого только что породили. Поле
    // СПРАВОЧНОЕ: журнал и разбор случая у клиента. Основанием для снятия зомби оно быть
    // перестало — решение сверяет образ держателя порта с путём движка в этой установке
    // (`expected_engine_image_path`), а не с записью, которая может устареть.
    let image_path = sidecar_runtime::observe_process(pid)
        .image_path
        .unwrap_or_default();
    if image_path.is_empty() {
        debug!("Путь образа движка (PID={pid}) снять не удалось - запись будет без него");
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

/// Итог ожидания готовности движка.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WaitOutcome {
    /// Рукопожатие прошло.
    Ready,
    /// Собственный процесс движка завершился – ждать нечего.
    Died,
    /// Срок вышел, процесс жив (или его нет) – движок, возможно, ещё запускается.
    StillStarting,
}

/// Ожидание готовности до крайнего срока `deadline_ms` (монотонные мс, см. [`now_ms`]).
///
/// На каждом шаге: рукопожатие на ТЕКУЩЕМ порту (`current_port()` перечитывается – порт мог
/// смениться при перезапуске) → гибель собственного процесса (сразу `Died`, срок не ждём) →
/// крайний срок (`StillStarting`, это `warn!`, не ошибка) → пауза 300 мс, затем по 2 с.
/// ERROR пишется только при гибели процесса.
///
/// `respawn_lock` здесь не берётся, `process_lock` – только внутри `child_state()` без `.await`.
/// После успеха обновляет sidecar.json с session_id от движка (он может отличаться от нашего,
/// если произошёл перезапуск внутри того же сеанса).
async fn wait_until(deadline_ms: u64) -> WaitOutcome {
    let client = handshake_client();
    let mut attempt: u32 = 0;
    loop {
        attempt += 1;
        let port = current_port();
        // Готовность отмечаем за ТЕМ порождением, при котором пробу начинали: если за время
        // пробы движок успели перепородить, отметка «ответил» новому порождению не достаётся.
        let spawn_mark = SPAWNED_AT_MS.load(Ordering::SeqCst);
        if let Some(info) = verify_handshake(port, &SIDECAR_CONFIG, &client).await {
            if SPAWNED_AT_MS.load(Ordering::SeqCst) == spawn_mark {
                READY_SINCE_SPAWN.store(true, Ordering::SeqCst);
            }
            info!(
                "Econometrica sidecar healthy after {attempt} attempt(s), session={}…",
                &info.session_id[..8.min(info.session_id.len())]
            );
            // Обновить session_id - используем то что сказал sidecar (source of truth)
            set_current_session(info.session_id.clone());
            if let Some(mut state) = read_state_file(&SIDECAR_CONFIG) {
                state.session_id = info.session_id.clone();
                state.version = info.version.clone();
                let _ = write_state_file(&SIDECAR_CONFIG, &state);
            }
            return WaitOutcome::Ready;
        }
        if attempt == 1 {
            info!("Waiting for econometrica sidecar on :{port} to start...");
        }
        if let ChildState::Exited(code) = child_state() {
            error!(
                "Модуль расчётов завершился при запуске (код выхода {code:?}) - ожидание прекращено"
            );
            return WaitOutcome::Died;
        }
        let now = now_ms();
        if now >= deadline_ms {
            warn!(
                "Модуль расчётов запускается дольше обычного: за отведённый срок не ответил на \
                 :{port} (попыток {attempt}); процесс не снимаем"
            );
            return WaitOutcome::StillStarting;
        }
        let pause_ms: u64 = if attempt == 1 { 300 } else { 2000 };
        tokio::time::sleep(Duration::from_millis(pause_ms.min(deadline_ms - now))).await;
    }
}

/// Ожидание готовности после порождения (`start_sidecar`, `ensure_alive`, `force_restart`):
/// срок – от момента порождения (`SPAWNED_AT_MS + COLD_START_GRACE_SECS`), а не от вызова.
/// Порождения в этом сеансе не было – `now + UNKNOWN_SPAWN_WAIT_SECS`.
pub async fn wait_for_sidecar_ready() -> WaitOutcome {
    let spawned_at = SPAWNED_AT_MS.load(Ordering::SeqCst);
    let deadline = if spawned_at == 0 {
        now_ms() + UNKNOWN_SPAWN_WAIT_SECS * 1000
    } else {
        spawned_at + COLD_START_GRACE_SECS * 1000
    };
    wait_until(deadline).await
}

/// Пассивное ожидание для интерфейса: свой короткий раунд `timeout_ms` от вызова. Повторы
/// раундов – забота вызывающего (`src/lib/engine-status.js`).
pub async fn wait_ready_within(timeout_ms: u64) -> WaitOutcome {
    wait_until(now_ms() + timeout_ms).await
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

    // 🔴 Стартующий движок не снимаем: ждём его до конца срока от порождения. Проверка стоит
    // ПОСЛЕ блокировки и повторной проверки здоровья и ДО счётчика неудач, пробы TCP (ветка
    // снятия держателя порта) и `take_child` – иначе два вызова гонятся, а снять можно было бы
    // ещё стартующий процесс. Счётчик неудач при этом не растёт.
    if current_phase() == Phase::Starting {
        info!("Модуль расчётов ещё запускается – жду его, не перезапуская");
        return wait_for_sidecar_ready().await == WaitOutcome::Ready;
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
        kill_port_holder(port);
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

    let healthy = wait_for_sidecar_ready().await == WaitOutcome::Ready;
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
        kill_port_holder(port);
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

    if wait_for_sidecar_ready().await == WaitOutcome::Ready {
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
        // Порождение, про ожидание которого сторож уже написал в журнал (одна строка на порождение).
        let mut starting_noted_for = 0u64;
        loop {
            tokio::time::sleep(Duration::from_secs(WATCHDOG_INTERVAL_SECS)).await;

            let healthy = is_healthy().await;
            let phase = current_phase();
            let was_failing = consecutive_fails > 0;
            // Решение – только здесь, цикл его лишь исполняет.
            let (next_fails, restart) =
                watchdog_step(consecutive_fails, healthy, phase, WATCHDOG_FAIL_THRESHOLD);
            consecutive_fails = next_fails;

            if healthy {
                if was_failing {
                    info!("Watchdog: sidecar recovered");
                }
                continue;
            }

            if phase == Phase::Starting {
                let spawned_at = SPAWNED_AT_MS.load(Ordering::SeqCst);
                if starting_noted_for != spawned_at {
                    starting_noted_for = spawned_at;
                    info!(
                        "Watchdog: сторож ждёт запуска модуля расчётов (с порождения {} с, срок {COLD_START_GRACE_SECS} с)",
                        now_ms().saturating_sub(spawned_at) / 1000
                    );
                }
                continue;
            }

            if restart {
                warn!("Watchdog: sidecar unhealthy ({WATCHDOG_FAIL_THRESHOLD}/{WATCHDOG_FAIL_THRESHOLD})");
                info!("Watchdog triggering respawn");
                let _ = ensure_alive().await;
            } else {
                warn!("Watchdog: sidecar unhealthy ({consecutive_fails}/{WATCHDOG_FAIL_THRESHOLD})");
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
mod expected_image_tests {
    use super::{classify_expected_image, ExpectedImageOwned};

    /// 🔴 Контроль находки внешнего аудита блока 2.4.10 (High), на стороне ПРОВОДКИ.
    ///
    /// Тест решения в `sidecar_runtime` проверяет, что при `Unknown` снимать нельзя. Но само
    /// значение `Unknown` вычисляется здесь — и первая попытка доказать правку мутацией это
    /// вскрыла: подмена «в релизе неразрешённый путь снова разрешает откат на имя» пережила
    /// весь набор, потому что проверялась чистая функция, а не место, где величина берётся.
    ///
    /// Ось мутации: вернуть в релизной ветке `NameFallbackAllowed` вместо `Unknown` —
    /// этот тест обязан покраснеть.
    #[test]
    fn release_without_resolved_path_forbids_killing() {
        assert!(
            matches!(
                classify_expected_image(true, None),
                ExpectedImageOwned::Unknown
            ),
            "релиз без разрешённого пути установки обязан давать Unknown: откат на сверку по \
             имени снимает движок другой редакции — имя у них одинаково"
        );
    }

    /// Отладочная сборка — единственный случай, где откат на имя законен: движок там
    /// запускает интерпретатор, своего образа у продукта нет по построению.
    #[test]
    fn debug_build_allows_name_fallback() {
        assert!(matches!(
            classify_expected_image(false, None),
            ExpectedImageOwned::NameFallbackAllowed
        ));
        // И даже если путь каким-то образом разрешился — в отладке всё равно откат по имени.
        assert!(matches!(
            classify_expected_image(false, Some("C:\\что-угодно.exe".to_string())),
            ExpectedImageOwned::NameFallbackAllowed
        ));
    }

    /// Положительный случай: путь разрешён — строгая сверка по нему.
    /// Без него тест умел бы только запрещать и зеленел бы на функции, запрещающей всё.
    #[test]
    fn release_with_resolved_path_is_known() {
        let путь = r"C:\Program Files\Aurora\econometrica-sidecar.exe".to_string();
        match classify_expected_image(true, Some(путь.clone())) {
            ExpectedImageOwned::Known(p) => assert_eq!(p, путь),
            иное => panic!("ожидался Known, получено {иное:?}"),
        }
    }
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

/// Ч2 «Не снимать стартующий движок»: решения о фазе и шаге сторожа, проводка этих решений в
/// `ensure_alive` / `spawn_watchdog` / `force_restart` и отметка порождения в `store_child`.
///
/// Тесты чистых функций сами по себе зеленеют, даже если вызов решения из цикла удалить (урок
/// `classify_expected_image` выше), поэтому проводку держит структурный тест по исходнику.
#[cfg(test)]
mod cold_start_tests {
    use super::{
        child_state, cold_start_phase, current_phase, set_current_port, store_child, take_child,
        wait_until, watchdog_step, now_ms, ChildState, Phase, WaitOutcome, READY_SINCE_SPAWN,
        SPAWNED_AT_MS,
    };
    use std::sync::atomic::Ordering;
    use std::time::{Duration, Instant};

    const GRACE: u64 = 120_000;

    #[test]
    fn cold_start_phase_table() {
        use ChildState::{Alive, Exited, Unknown};
        use Phase::{Died, Settled, Starting};
        // (now, spawned_at, ready, child) → фаза
        let cases: &[(u64, u64, bool, ChildState, Phase, &str)] = &[
            (10_000, 1, false, Alive, Starting, "живой и молодой"),
            (10_000, 1, true, Alive, Settled, "живой, молодой, но уже отвечал"),
            (200_000, 1, false, Alive, Settled, "живой и старый"),
            (10_000, 1, false, Exited(Some(3)), Died, "погиб молодым"),
            (500_000, 1, false, Exited(None), Died, "погиб старым"),
            (10_000, 1, true, Exited(Some(0)), Died, "погиб после готовности"),
            (10_000, 1, false, Unknown, Settled, "своего процесса нет"),
            (10_000, 0, false, Alive, Settled, "порождения в сеансе не было"),
            (1_000 + GRACE, 1_000, false, Alive, Settled, "ровно на границе срока"),
            (1_000 + GRACE - 1, 1_000, false, Alive, Starting, "за миг до границы"),
        ];
        for &(now, spawned, ready, child, want, label) in cases {
            assert_eq!(
                cold_start_phase(now, spawned, ready, child, GRACE),
                want,
                "{label}: now={now} spawned={spawned} ready={ready} child={child:?}"
            );
        }
    }

    #[test]
    fn watchdog_never_restarts_while_starting() {
        let mut fails = 0;
        for tick in 0..10 {
            let (next, restart) = watchdog_step(fails, false, Phase::Starting, 3);
            assert!(!restart, "шаг {tick}: стартующий движок перезапускать нельзя");
            fails = next;
        }
        assert_eq!(fails, 0, "пока движок запускается, неудачи не копятся");
    }

    #[test]
    fn watchdog_restarts_on_third_settled_failure() {
        assert_eq!(watchdog_step(0, false, Phase::Settled, 3), (1, false));
        assert_eq!(watchdog_step(1, false, Phase::Settled, 3), (2, false));
        assert_eq!(watchdog_step(2, false, Phase::Settled, 3), (0, true));
        // Погибший движок считается так же, как прежде.
        assert_eq!(watchdog_step(2, false, Phase::Died, 3), (0, true));
    }

    #[test]
    fn watchdog_health_resets_counter() {
        assert_eq!(watchdog_step(2, true, Phase::Settled, 3), (0, false));
        assert_eq!(watchdog_step(2, true, Phase::Starting, 3), (0, false));
    }

    // ── Структура исходника ──────────────────────────────────────────────────

    /// Боевая часть файла без комментариев и с вычищенным содержимым строковых литералов:
    /// имя функции в тексте журнала или в комментарии не должно сойти за её вызов.
    fn production_code() -> String {
        let src = include_str!("econ_sidecar.rs");
        let cut = src
            .find("#[cfg(test)]")
            .expect("в файле должен быть модуль тестов");
        code_only(&src[..cut])
    }

    /// Убирает `//` и `/* */` комментарии, содержимое строк заменяет пробелами (кавычки остаются).
    /// Сырых строк и символьного литерала `'"'` в боевой части файла нет.
    fn code_only(src: &str) -> String {
        let chars: Vec<char> = src.chars().collect();
        let mut out = String::with_capacity(src.len());
        let mut i = 0;
        while i < chars.len() {
            let c = chars[i];
            if c == '"' {
                out.push('"');
                i += 1;
                while i < chars.len() {
                    if chars[i] == '\\' && i + 1 < chars.len() {
                        out.push_str("  ");
                        i += 2;
                        continue;
                    }
                    if chars[i] == '"' {
                        out.push('"');
                        i += 1;
                        break;
                    }
                    out.push(if chars[i] == '\n' { '\n' } else { ' ' });
                    i += 1;
                }
            } else if c == '/' && chars.get(i + 1) == Some(&'/') {
                while i < chars.len() && chars[i] != '\n' {
                    i += 1;
                }
            } else if c == '/' && chars.get(i + 1) == Some(&'*') {
                i += 2;
                while i + 1 < chars.len() && !(chars[i] == '*' && chars[i + 1] == '/') {
                    i += 1;
                }
                i += 2;
            } else {
                out.push(c);
                i += 1;
            }
        }
        out
    }

    /// Тело функции (между парными фигурными скобками) по её объявлению.
    fn fn_body<'a>(code: &'a str, signature: &str) -> &'a str {
        let start = code
            .find(signature)
            .unwrap_or_else(|| panic!("в исходнике нет `{signature}`"));
        let open = start + code[start..].find('{').expect("нет открывающей скобки");
        let mut depth = 0usize;
        for (k, ch) in code[open..].char_indices() {
            match ch {
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        return &code[open..open + k + 1];
                    }
                }
                _ => {}
            }
        }
        panic!("у `{signature}` нет закрывающей скобки");
    }

    fn pos(body: &str, needle: &str, func: &str) -> usize {
        body.find(needle)
            .unwrap_or_else(|| panic!("в теле `{func}` нет `{needle}`"))
    }

    /// 🔴 Проверка фазы в `ensure_alive` стоит после блокировки перезапуска и ДО счётчика неудач,
    /// пробы TCP (ветка снятия держателя порта) и `take_child`.
    #[test]
    fn ensure_alive_checks_phase_before_any_kill_path() {
        let code = production_code();
        let body = fn_body(&code, "pub async fn ensure_alive(");
        let phase = pos(body, "current_phase()", "ensure_alive");
        let lock = pos(body, "respawn_lock()", "ensure_alive");
        assert!(lock < phase, "проверка фазы обязана идти после взятия respawn_lock");
        for later in ["CONSECUTIVE_FAILS.fetch_add", "tcp_responsive(", "take_child()"] {
            assert!(
                phase < pos(body, later, "ensure_alive"),
                "проверка фазы обязана стоять раньше `{later}`"
            );
        }
        let current = fn_body(&code, "fn current_phase(");
        assert!(
            current.contains("cold_start_phase("),
            "current_phase обязана решать через cold_start_phase"
        );
    }

    #[test]
    fn watchdog_decides_only_through_step() {
        let code = production_code();
        let body = fn_body(&code, "pub fn spawn_watchdog(");
        assert!(body.contains("watchdog_step("), "сторож обязан решать через watchdog_step");
        assert!(body.contains("current_phase()"), "сторож обязан знать фазу движка");
        assert!(
            !body.contains("consecutive_fails += 1"),
            "счётчик неудач сторожа считается только в watchdog_step"
        );
    }

    /// Ручной перезапуск снимает всегда, в том числе стартующий движок.
    #[test]
    fn force_restart_does_not_check_phase() {
        let code = production_code();
        let body = fn_body(&code, "pub async fn force_restart(");
        assert!(!body.contains("cold_start_phase("));
        assert!(!body.contains("current_phase()"));
    }

    /// Отметка порождения ставится ровно в одном месте – в `store_child`.
    #[test]
    fn spawn_mark_is_set_only_in_store_child() {
        let code = production_code();
        let body = fn_body(&code, "fn store_child(");
        assert!(body.contains("SPAWNED_AT_MS.store("));
        assert!(body.contains("READY_SINCE_SPAWN.store(false"));
        assert_eq!(
            code.matches("SPAWNED_AT_MS.store(").count(),
            1,
            "момент порождения выставляется только в store_child"
        );
    }

    // ── Поведение на настоящем процессе ──────────────────────────────────────

    /// Настоящий дочерний процесс, который сразу завершается с кодом 3: `store_child` ставит
    /// отметку порождения и сбрасывает готовность, `child_state` видит код выхода, фаза – `Died`,
    /// а ожидание с далёким сроком возвращает `Died` за секунды, не дожидаясь срока.
    /// Глобальное состояние трогает только этот тест, поэтому всё – в одной функции.
    #[test]
    fn exited_child_is_died_fast_and_spawn_is_marked() {
        #[cfg(windows)]
        let child = std::process::Command::new("cmd")
            .args(["/C", "exit 3"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .expect("cmd должен запускаться");
        #[cfg(not(windows))]
        let child = std::process::Command::new("sh")
            .args(["-c", "exit 3"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .expect("sh должен запускаться");

        READY_SINCE_SPAWN.store(true, Ordering::SeqCst);
        store_child(child);
        assert!(
            SPAWNED_AT_MS.load(Ordering::SeqCst) > 0,
            "store_child обязан ставить момент порождения"
        );
        assert!(
            !READY_SINCE_SPAWN.load(Ordering::SeqCst),
            "store_child обязан сбрасывать готовность"
        );

        let started = Instant::now();
        let mut state = child_state();
        while state == ChildState::Alive && started.elapsed() < Duration::from_secs(10) {
            std::thread::sleep(Duration::from_millis(50));
            state = child_state();
        }
        assert_eq!(state, ChildState::Exited(Some(3)));
        assert_eq!(current_phase(), Phase::Died);

        // Порт, на котором заведомо никто не слушает: заняли и сразу отпустили.
        let free_port = std::net::TcpListener::bind("127.0.0.1:0")
            .and_then(|l| l.local_addr())
            .map(|a| a.port())
            .expect("свободный порт");
        set_current_port(free_port);
        let rt = tokio::runtime::Runtime::new().expect("runtime");
        let t0 = Instant::now();
        let outcome = rt.block_on(wait_until(now_ms() + 60_000));
        let took = t0.elapsed();

        let _ = take_child();
        set_current_port(0);

        assert_eq!(outcome, WaitOutcome::Died);
        assert!(
            took < Duration::from_secs(15),
            "гибель процесса обязана обнаруживаться сразу, не по сроку: заняло {took:?}"
        );
    }
}
