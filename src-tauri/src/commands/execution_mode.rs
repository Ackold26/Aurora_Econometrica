//! Режим исполнения кабинета: свой Claude Code клиента или шлюз Авроры (ADR-049).
//!
//! 🔴 Развилка живёт во ВРЕМЕНИ РАБОТЫ, а не в сборке. Прежде редакции различались
//! признаком компиляции: обычная звала локальный Claude Code, тонкая уходила на наш
//! шлюз, и сменить решение можно было только переустановкой другого приложения.
//! Мотив слияния — не удобство сборки, а конфиденциальность: в локальном режиме
//! Платформа Аврора вообще не участвует в передаче, материалы идут от машины клиента
//! прямо к Anthropic. Такое свойство нельзя продать, если за ним надо переустанавливать
//! программу.
//!
//! Признак сборки `cloud` СОХРАНЯЕТСЯ: без него зависимость на приватный крейт шлюза
//! не входит в граф, и обычная сборка не требует доступа к закрытому репозиторию
//! (находка Н-01 аудита 30 июля). Он отвечает на вопрос «есть ли облачный путь в этом
//! бинаре», а не «каким путём идти сейчас».
//!
//! ## Приоритет выбора
//!
//! ```text
//! явный выбор человека  →  автоопределение
//! ```
//!
//! Слоя лицензии в клиенте нет намеренно (решение владельца 2026-08-03): подпись ответа
//! сервера `AUTHSIG-v1` покрывает фиксированный набор полей, и новое поле «разрешённые
//! режимы» оказалось бы вне подписи — то есть обходилось бы подменой ответа. Право на
//! облачный режим проверяет сам шлюз при обращении, и его отказ приходит с причиной.
//!
//! ## Асимметрия отказа
//!
//! 🔴 Из локального режима в облачный САМИ НЕ ПЕРЕХОДИМ никогда. Человек выбирает
//! локальный ровно затем, чтобы его материалы не проходили через наши серверы; тихий
//! переход при отказе Claude Code нарушает единственное обещание, ради которого режим
//! существует. Отказ локального — это причина и предложение переключиться, не действие.
//! Обратное направление ADR разрешает автоматическим, но и его мы не делаем молча
//! (решение владельца): дефект «работает не в том режиме» невидим по природе.

use std::sync::Mutex;
use std::time::{Duration, Instant};

use log::{debug, info, warn};
use serde::{Deserialize, Serialize};

/// Каким путём исполняется работа кабинета.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ExecutionMode {
    /// Свой Claude Code на машине клиента: Платформа Аврора не участвует в передаче.
    Local,
    /// Шлюз Авроры: подписка не нужна клиенту, но материалы проходят через наш узел.
    Cloud,
}

impl ExecutionMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::Cloud => "cloud",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "local" => Some(Self::Local),
            "cloud" => Some(Self::Cloud),
            _ => None,
        }
    }

    /// Как режим называется человеку. Одна формулировка на журнал, интерфейс и отказы:
    /// разные имена одного и того же режима в разных местах — готовый источник путаницы
    /// там, где человек и так не видит, где исполняется его работа.
    pub fn human(self) -> &'static str {
        match self {
            Self::Local => "ваш Claude Code",
            Self::Cloud => "шлюз Авроры",
        }
    }
}

/// Откуда взялось решение о режиме — нужно и человеку на экране, и журналу.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ModeSource {
    /// Человек выбрал сам. Автоопределением не перебивается никогда.
    Explicit,
    /// Выбрано программой по доступности.
    Auto,
}

impl ModeSource {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Explicit => "явный выбор",
            Self::Auto => "автоопределение",
        }
    }
}

/// Решение о режиме вместе с объяснением — объяснение показывается человеку, а не
/// хранится «на всякий случай»: режим, выбранный без названной причины, невозможно
/// проверить, а именно проверяемость и есть смысл обещания о конфиденциальности.
#[derive(Debug, Clone, Serialize)]
pub struct ModeDecision {
    pub mode: ExecutionMode,
    pub source: ModeSource,
    pub explanation: String,
}

/// Состояние переключателя для интерфейса.
#[derive(Debug, Clone, Serialize)]
pub struct ModeState {
    /// Что действует сейчас.
    pub mode: ExecutionMode,
    pub source: ModeSource,
    pub explanation: String,
    /// Явный выбор человека, если он сделан (`None` — работает автоопределение).
    pub explicit: Option<ExecutionMode>,
    /// Есть ли облачный путь в этом бинаре (признак сборки `cloud`).
    pub cloud_built_in: bool,
    /// Запускается ли Claude Code на этой машине (последний зонд).
    pub local_available: bool,
    /// Почему облачный режим недоступен, если шлюз отказал по праву. Пустая строка —
    /// отказа не было.
    pub cloud_refusal: String,
}

/// Входит ли облачный путь в этот бинарь.
///
/// Читается `cfg!`, а не `#[cfg]`: функция существует в обеих сборках, и вызывающему
/// коду не нужно ветвиться самому — иначе условная компиляция расползается обратно по
/// продукту, ровно оттуда мы её и убираем.
pub fn cloud_built_in() -> bool {
    cfg!(feature = "thin")
}

// ── Зонд доступности локального Claude Code ─────────────────────────────────────

/// Сколько живёт результат зонда. Клиент ставит Claude Code или входит в него, не
/// перезапуская нашу программу, — вечный кэш заставлял бы его перезапускаться, а зонд
/// на каждый вопрос стоил бы полсекунды на горячем пути.
const PROBE_TTL: Duration = Duration::from_secs(120);

/// Сколько ждём ответа `claude --version`. Живой запуск отвечает за десятые доли
/// секунды; всё, что дольше, для человека уже неотличимо от «не работает».
const PROBE_TIMEOUT: Duration = Duration::from_secs(6);

struct LocalProbe {
    checked_at: Instant,
    available: bool,
    /// Почему недоступен — показывается человеку, если он выбрал локальный режим явно.
    reason: String,
}

static LOCAL_PROBE: Mutex<Option<LocalProbe>> = Mutex::new(None);

/// Отказ шлюза по праву: запоминается, чтобы пункт «шлюз Авроры» назывался
/// недоступным С ПРИЧИНОЙ до следующей успешной работы, а не молча отказывал каждый раз.
static CLOUD_REFUSAL: Mutex<String> = Mutex::new(String::new());

/// Шла ли работа этого запуска программы локальным путём хоть раз.
///
/// 🔴 Находка внешнего аудита (Critical). Без этой памяти автоопределение молча меняло
/// маршрут данных: человек без явного выбора работал локально и видел «ваш Claude Code»
/// с обещанием «материалы не проходят через серверы Платформы Аврора»; ЛЮБОЙ отказ
/// прогона — хоть ошибка записи отчёта — помечал локальный путь недоступным, и
/// следующий же вопрос уходил на шлюз. Согласия никто не спрашивал, а показанный текст
/// утверждал обратное.
///
/// Асимметрия §4 не про то, был ли выбор ЯВНЫМ, а про то, что круг видящих не
/// расширяется без ведома человека. Поэтому один раз пойдя локально, автоопределение
/// в облако само уже не уходит: отказ называется причиной, переход — только выбором.
static LOCAL_ENGAGED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

fn local_engaged() -> bool {
    LOCAL_ENGAGED.load(std::sync::atomic::Ordering::Relaxed)
}

/// Отметить, что работа пошла локальным путём. Зовётся в момент РЕШЕНИЯ, а не успеха:
/// человек уже увидел признак «ваш Claude Code» и вправе считать обещание действующим.
fn mark_local_engaged() {
    LOCAL_ENGAGED.store(true, std::sync::atomic::Ordering::Relaxed);
}

/// Снять память о локальной работе — только явный выбор человека вправе это сделать.
fn forget_local_engagement() {
    LOCAL_ENGAGED.store(false, std::sync::atomic::Ordering::Relaxed);
}

fn cached_probe() -> Option<(bool, String)> {
    let guard = LOCAL_PROBE.lock().ok()?;
    let probe = guard.as_ref()?;
    if probe.checked_at.elapsed() > PROBE_TTL {
        return None;
    }
    Some((probe.available, probe.reason.clone()))
}

fn store_probe(available: bool, reason: String) {
    if let Ok(mut guard) = LOCAL_PROBE.lock() {
        *guard = Some(LocalProbe { checked_at: Instant::now(), available, reason });
    }
}

/// Запускается ли Claude Code на этой машине.
///
/// 🔴 Проверяется ЗАПУСК, а не наличие файла (ADR-049 §4). `claude.exe` может стоять
/// без подписки, с истёкшим входом или сломанной установкой — и тогда «файл найден»
/// означает лишь то, что человек получит отказ вместо работы. Запуск доказывает, что
/// программа хотя бы жива.
///
/// Чего этот зонд НЕ доказывает: действующей подписки и незавершённого входа —
/// `--version` их не касается. Это выясняется на первом реальном прогоне; такой отказ
/// в облако не ведёт (см. `mark_local_failed`), а гасит ЛОКАЛЬНЫЙ выбор автоопределения.
pub async fn local_available() -> (bool, String) {
    if let Some(cached) = cached_probe() {
        return cached;
    }
    let (available, reason) = probe_local().await;
    store_probe(available, reason.clone());
    (available, reason)
}

async fn probe_local() -> (bool, String) {
    let binary = match crate::commands::claude::find_claude_binary() {
        Ok(path) => path,
        Err(e) => {
            debug!("Локальный режим недоступен: {e}");
            return (false, "Claude Code на этой машине не найден".to_string());
        }
    };

    let mut command = tokio::process::Command::new(&binary);
    command.arg("--version");
    command.stdin(std::process::Stdio::null());
    command.stdout(std::process::Stdio::piped());
    command.stderr(std::process::Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: зонд не мигает консолью

    match tokio::time::timeout(PROBE_TIMEOUT, command.output()).await {
        Ok(Ok(output)) if output.status.success() => {
            let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
            debug!("Локальный Claude Code отвечает: {version}");
            (true, String::new())
        }
        Ok(Ok(output)) => {
            let text = String::from_utf8_lossy(&output.stderr).trim().to_string();
            warn!("Claude Code найден, но запуск не удался: {text}");
            (false, "Claude Code найден, но не запускается".to_string())
        }
        Ok(Err(e)) => {
            warn!("Claude Code найден, но запуск не удался: {e}");
            (false, "Claude Code найден, но не запускается".to_string())
        }
        Err(_) => {
            warn!("Claude Code не ответил за {PROBE_TIMEOUT:?}");
            (false, "Claude Code не отвечает".to_string())
        }
    }
}

/// Отметить, что локальный путь на деле не работает (нет входа, исчерпан лимит).
///
/// 🔴 Гасит ЛОКАЛЬНЫЙ выбор автоопределения, но НЕ переводит человека в облако: явный
/// выбор сильнее любой отметки, а тихий переход из локального режима в облачный
/// запрещён (ADR-049 §4).
pub fn mark_local_failed(reason: &str) {
    store_probe(false, reason.to_string());
}

/// Забыть результат зонда: человек мог поставить Claude Code или войти в него, не
/// перезапуская программу, и ждать истечения кэша ради этого он не обязан.
pub fn forget_local_probe() {
    if let Ok(mut guard) = LOCAL_PROBE.lock() {
        *guard = None;
    }
}

/// Отметить отказ шлюза по праву — чтобы пункт назывался недоступным с причиной.
pub fn mark_cloud_refused(reason: &str) {
    if let Ok(mut guard) = CLOUD_REFUSAL.lock() {
        *guard = reason.to_string();
    }
}

/// Снять отметку отказа шлюза: работа прошла — право есть.
pub fn clear_cloud_refusal() {
    if let Ok(mut guard) = CLOUD_REFUSAL.lock() {
        guard.clear();
    }
}

fn cloud_refusal() -> String {
    CLOUD_REFUSAL.lock().map(|g| g.clone()).unwrap_or_default()
}

// ── Явный выбор человека ────────────────────────────────────────────────────────

/// Что выбрал человек. `None` — выбора не делал, работает автоопределение.
pub fn explicit_choice(app_handle: &tauri::AppHandle) -> Option<ExecutionMode> {
    use tauri::Manager;
    let config_dir = app_handle.path().app_config_dir().ok()?;
    crate::commands::user_config::load(&config_dir)
        .execution_mode
        .as_deref()
        .and_then(ExecutionMode::parse)
}

/// Записать явный выбор. `None` возвращает продукт к автоопределению.
pub fn set_explicit_choice(
    app_handle: &tauri::AppHandle,
    mode: Option<ExecutionMode>,
) -> Result<(), String> {
    use tauri::Manager;
    let config_dir = app_handle
        .path()
        .app_config_dir()
        .map_err(|e| format!("каталог настроек недоступен: {e}"))?;
    let mut config = crate::commands::user_config::load(&config_dir);
    config.execution_mode = mode.map(|m| m.as_str().to_string());
    crate::commands::user_config::save(&config_dir, &config)?;
    // Явный выбор облака — согласие человека расширить круг видящих. Только оно снимает
    // память о локальной работе: сама программа этого сделать не вправе.
    if mode == Some(ExecutionMode::Cloud) {
        forget_local_engagement();
    }
    match mode {
        Some(m) => info!("Режим исполнения выбран человеком: {}", m.human()),
        None => info!("Режим исполнения возвращён к автоопределению"),
    }
    Ok(())
}

// ── Решение ─────────────────────────────────────────────────────────────────────

/// Каким путём идти сейчас.
///
/// Порядок разбирается сверху вниз и нигде не «доопределяется» вызывающим кодом:
/// иначе правило приоритета разъезжается по продукту и перестаёт быть проверяемым.
pub async fn resolve(app_handle: &tauri::AppHandle) -> ModeDecision {
    let explicit = explicit_choice(app_handle);
    // Зонд не запускается, когда решение уже принято человеком: явный выбор сильнее
    // любой доступности, а лишний запуск чужой программы на горячем пути не бесплатен.
    let (local_ok, why_not) = if explicit.is_some() {
        (false, String::new())
    } else {
        local_available().await
    };
    let decision = decide_with_history(explicit, cloud_built_in(), local_ok, &why_not, local_engaged());
    if decision.mode == ExecutionMode::Local {
        mark_local_engaged();
    }
    decision
}

/// Само правило приоритета — без обращения к среде.
///
/// 🔴 Вынесено отдельно нарочно: приоритет «явный выбор → автоопределение» и есть то,
/// что обязано проверяться таблицей, а не живым прогоном. Спрятанное за чтением
/// настроек и запуском чужой программы, оно проверялось бы только вручную — то есть
/// на деле никогда.
/// Правило приоритета без памяти о локальной работе — обёртка для проверок.
/// Рабочий код зовёт `decide_with_history`: без памяти автоопределение уводило бы
/// человека на шлюз после первого же отказа локального прогона.
#[cfg(test)]
pub(crate) fn decide(
    explicit: Option<ExecutionMode>,
    cloud_built_in: bool,
    local_ok: bool,
    why_not: &str,
) -> ModeDecision {
    decide_with_history(explicit, cloud_built_in, local_ok, why_not, false)
}

/// То же правило, но с памятью о том, шла ли работа локально в этом запуске программы.
///
/// 🔴 `local_engaged` появился после находки внешнего аудита: без него автоопределение
/// уводило человека на шлюз при первом же отказе локального прогона — включая отказы,
/// не имеющие к доступности Claude Code никакого отношения.
pub(crate) fn decide_with_history(
    explicit: Option<ExecutionMode>,
    cloud_built_in: bool,
    local_ok: bool,
    why_not: &str,
    local_engaged: bool,
) -> ModeDecision {
    if let Some(chosen) = explicit {
        // 🔴 Явный выбор облачного режима в сборке без облачного пути — не отказ
        // человеку, а честное сообщение: такой бинарь физически не умеет ходить на
        // шлюз, и молча делать вид, что умеет, нельзя.
        if chosen == ExecutionMode::Cloud && !cloud_built_in {
            return ModeDecision {
                mode: ExecutionMode::Local,
                source: ModeSource::Explicit,
                explanation: "Облачный режим не входит в эту сборку — работа идёт через ваш \
                              Claude Code."
                    .to_string(),
            };
        }
        return ModeDecision {
            mode: chosen,
            source: ModeSource::Explicit,
            explanation: format!("Режим выбран вами: {}.", chosen.human()),
        };
    }

    if local_ok {
        // 🔴 Локальный вперёд облачного не ради «приватнее», а ради непрерывности:
        // у клиента обычной редакции Claude Code есть, и после слияния редакций его
        // работа обязана идти тем же путём, что вчера. Маршрут данных не меняется
        // молча ни у кого — ни в ту, ни в другую сторону.
        return ModeDecision {
            mode: ExecutionMode::Local,
            source: ModeSource::Auto,
            explanation: "Работа идёт через ваш Claude Code: материалы не проходят через \
                          серверы Платформы Аврора."
                .to_string(),
        };
    }

    // 🔴 Работа уже шла локально в этом запуске — в облако автоопределение НЕ уходит
    // (находка внешнего аудита, Critical). Человек видел признак «ваш Claude Code» и
    // обещание, что материалы не проходят через наши серверы; отказ прогона — любой,
    // хоть ошибка записи отчёта — не даёт права расширить круг видящих без его ведома.
    // Отказ называется причиной, переход остаётся выбором.
    if local_engaged {
        return ModeDecision {
            mode: ExecutionMode::Local,
            source: ModeSource::Auto,
            explanation: format!(
                "{}. Работа продолжает идти через ваш Claude Code: сами на шлюз Авроры мы вас \
                 не переводим — это расширило бы круг тех, кто видит материалы. Переключить \
                 можно в настройках.",
                if why_not.is_empty() { "Локальный запуск сейчас недоступен" } else { why_not }
            ),
        };
    }

    if cloud_built_in {
        return ModeDecision {
            mode: ExecutionMode::Cloud,
            source: ModeSource::Auto,
            explanation: format!(
                "Работа идёт через шлюз Авроры: {}. Своя подписка Claude не нужна.",
                if why_not.is_empty() { "локальный запуск недоступен".to_string() } else { why_not.to_lowercase() }
            ),
        };
    }

    ModeDecision {
        mode: ExecutionMode::Local,
        source: ModeSource::Auto,
        explanation: format!(
            "{}. Облачного режима в этой сборке нет.",
            if why_not.is_empty() { "Локальный запуск недоступен" } else { why_not }
        ),
    }
}

/// Полное состояние переключателя для интерфейса.
pub async fn state(app_handle: &tauri::AppHandle) -> ModeState {
    let decision = resolve(app_handle).await;
    let (local_ok, _) = local_available().await;
    ModeState {
        mode: decision.mode,
        source: decision.source,
        explanation: decision.explanation,
        explicit: explicit_choice(app_handle),
        cloud_built_in: cloud_built_in(),
        local_available: local_ok,
        cloud_refusal: cloud_refusal(),
    }
}

/// Текст отказа локального режима: причина плюс ПРЕДЛОЖЕНИЕ переключиться.
///
/// 🔴 Именно предложение, а не переключение. Человек, выбравший локальный режим,
/// сделал это ради обещания «Платформа Аврора не видит материалы»; перевести его на
/// шлюз без спроса — нарушить ровно то, ради чего режим существует.
pub fn local_failure_text(reason: &str) -> String {
    if cloud_built_in() {
        format!(
            "{reason}\n\nРабота НЕ была отправлена на шлюз Авроры: в локальном режиме ваши \
             материалы не проходят через наши серверы, и менять это без вашего согласия мы не \
             станем — повторный вопрос тоже пойдёт через ваш Claude Code. Если сейчас участие \
             наших серверов допустимо, переключите режим на «шлюз Авроры» в настройках, и тогда \
             повторите вопрос."
        )
    } else {
        reason.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mode_survives_text_round_trip() {
        for mode in [ExecutionMode::Local, ExecutionMode::Cloud] {
            assert_eq!(ExecutionMode::parse(mode.as_str()), Some(mode));
        }
        assert_eq!(ExecutionMode::parse("узел-а"), None, "чужой режим не должен разбираться");
    }

    #[test]
    fn local_failure_text_offers_but_does_not_switch() {
        let text = local_failure_text("Сессия Claude истекла.");
        assert!(text.contains("Сессия Claude истекла."), "причина обязана остаться");
        if cloud_built_in() {
            assert!(
                text.contains("НЕ была отправлена"),
                "человек обязан узнать, что работа НЕ ушла на шлюз",
            );
            assert!(text.contains("переключите режим"), "предложение переключиться обязано быть");
        }
    }

    #[test]
    fn failed_local_run_marks_probe_unavailable() {
        mark_local_failed("Сессия Claude недоступна или истекла");
        let (available, reason) = cached_probe().expect("отметка обязана попасть в кэш зонда");
        assert!(!available, "после отказа локальный путь не считается доступным");
        assert!(reason.contains("Сессия"), "причина обязана дойти до человека");
    }

    /// Гейт приёмки 3 ADR-049: явный выбор человека сильнее автоопределения.
    ///
    /// Таблица покрывает обе стороны развилки в ОБЕИХ сборках: правило приоритета —
    /// не свойство одной поставки, и проверка, ветвящаяся по признаку сборки, молчала
    /// бы ровно там, где правило нарушено.
    #[test]
    fn explicit_choice_always_beats_autodetection() {
        // Человек выбрал локальный — облако не берётся, даже если Claude Code не отвечает.
        let d = decide(Some(ExecutionMode::Local), true, false, "Claude Code не отвечает");
        assert_eq!(d.mode, ExecutionMode::Local, "явный локальный выбор не должен уходить в облако");
        assert_eq!(d.source, ModeSource::Explicit);

        // Человек выбрал облако — локальный не берётся, даже если Claude Code работает.
        let d = decide(Some(ExecutionMode::Cloud), true, true, "");
        assert_eq!(d.mode, ExecutionMode::Cloud, "явный облачный выбор не должен уходить в локальный");
        assert_eq!(d.source, ModeSource::Explicit);
    }

    /// 🔴 Асимметрия отказа: автоопределение при недоступном локальном пути уходит в
    /// облако — это НЕ переход из локального режима, а первичный выбор. Обратного
    /// (из выбранного локального в облако) не происходит ни при каких входах.
    #[test]
    fn autodetection_prefers_working_local_and_never_leaves_chosen_local() {
        let d = decide(None, true, true, "");
        assert_eq!(d.mode, ExecutionMode::Local, "работающий Claude Code выбирается сам");
        assert_eq!(d.source, ModeSource::Auto);

        let d = decide(None, true, false, "Claude Code на этой машине не найден");
        assert_eq!(d.mode, ExecutionMode::Cloud, "без локального пути автоопределение берёт шлюз");

        // Ни один вход с явным локальным выбором не даёт облака — перебираем все.
        for cloud_built_in in [false, true] {
            for local_ok in [false, true] {
                let d = decide(Some(ExecutionMode::Local), cloud_built_in, local_ok, "неважно");
                assert_eq!(
                    d.mode,
                    ExecutionMode::Local,
                    "выбранный локальный режим обязан оставаться локальным при любых условиях",
                );
            }
        }
    }

    /// 🔴 Находка внешнего аудита (Critical): автоопределение уводило человека на шлюз
    /// при первом же отказе локального прогона — включая отказы, не связанные с
    /// доступностью Claude Code (ошибка записи отчёта, отмена, сетевой сбой внутри
    /// локального пути). Человек согласия не давал, а на экране стояло обещание, что
    /// материалы не проходят через наши серверы.
    #[test]
    fn autodetection_never_moves_to_cloud_after_working_locally() {
        // Работа уже шла локально, теперь локальный путь «недоступен» — остаёмся локально.
        let d = decide_with_history(None, true, false, "Сессия Claude истекла", true);
        assert_eq!(
            d.mode,
            ExecutionMode::Local,
            "после локальной работы автоопределение не вправе уйти на шлюз без согласия",
        );
        assert!(
            d.explanation.contains("не переводим"),
            "человеку обязана называться причина, по которой маршрут НЕ изменился: {}",
            d.explanation,
        );

        // А первый выбор при недоступном локальном пути по-прежнему может быть облачным:
        // это не ПЕРЕХОД, а начальное решение — круг видящих не расширяется задним числом.
        let d = decide_with_history(None, true, false, "Claude Code не найден", false);
        assert_eq!(d.mode, ExecutionMode::Cloud, "первичный выбор при отсутствии локального пути");
    }

    /// Сборка без облачного пути не притворяется, что умеет ходить на шлюз.
    #[test]
    fn build_without_cloud_says_so_instead_of_pretending() {
        let d = decide(Some(ExecutionMode::Cloud), false, false, "");
        assert_eq!(d.mode, ExecutionMode::Local, "без облачного пути работа идёт локально");
        assert!(
            d.explanation.contains("не входит в эту сборку"),
            "человеку обязана называться причина: {}",
            d.explanation,
        );
    }

    #[test]
    fn cloud_refusal_is_remembered_and_cleared() {
        mark_cloud_refused("Облачный режим не входит в вашу лицензию");
        assert!(cloud_refusal().contains("лицензи"), "отказ по праву обязан запомниться");
        clear_cloud_refusal();
        assert!(cloud_refusal().is_empty(), "успешная работа снимает отметку отказа");
    }
}
