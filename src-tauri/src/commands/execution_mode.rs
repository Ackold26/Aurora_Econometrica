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

//! ## 🔴 Два режима вместо трёх (решение владельца 10–11.09.2026)
//!
//! Развилка выше описывает состояние ДО 11.09.2026. Владелец убрал средний маршрут —
//! работу через Claude Code, установленный у клиента, — и вместе с ним автоопределение:
//! 10.09 оно сломало показ покупателю, молча уведя запрос в чужую программу на машине,
//! пока на экране стояла «облачная обработка». Осталось два положения одного
//! переключателя: «полностью локально» (ассистента нет, материалы не покидают машину)
//! и «через шлюз Авроры» (единственный путь ассистента).
//!
//! Всё, что ниже относится к зонду `claude --version`, к `resolve`/`decide_with_history`
//! и к памяти `LOCAL_ENGAGED`, ВЫВЕДЕНО ИЗ УПОТРЕБЛЕНИЯ и оставлено целиком до решения
//! владельца об удалении. Действующая развилка — раздел «Единственный переключатель».

// 🔴 Слой автоопределения больше не вызывается ни из одного рабочего пути (см. шапку).
// Код оставлен по правилу «ничего не удалять без решения владельца», поэтому в модуле
// глушится dead_code: иначе каждая сборка тонула бы в предупреждениях о заведомо
// неработающем слое, и в этом шуме потерялось бы предупреждение настоящее.
#![allow(dead_code)]

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

// ── Единственный переключатель ──────────────────────────────────────────────────
//
// «Полностью локально ●———○ Через шлюз Авроры». Третьего, промежуточного и
// «автоматического» положения нет (решение владельца 10.09.2026).
//
// 🔴 Положение считается от ФАКТИЧЕСКОГО положения дел, а не от одного хранимого поля.
// Находка внешнего аудита 11.09.2026: прежняя подпись смотрела только на `local_only`
// и на свежей установке жирным утверждала «материалы уходят на наш сервер», хотя
// согласия ещё никто не давал и наружу не уходило ничего. Слагаемых четыре, и любое
// из них в одиночку оставляет переключатель слева:
//   1. редакция собрана с ассистентом (`cloud_advisors`);
//   2. путь к шлюзу входит в эту сборку (`thin`);
//   3. согласие на облачную обработку действует (оно же — часть выбора режима);
//   4. человек не выбрал «полностью локально».

/// Что показывать человеку в положении «полностью локально», когда он всё-таки
/// обращается к ассистенту. Показывается ДО отправки, а не после отказа, и не только
/// в переходный период (решение владельца 10.09.2026, требование 5).
pub const LOCAL_MODE_NOTICE: &str = "Сейчас включён полностью локальный режим: \
    ИИ-ассистент отключён, материалы не покидают эту машину. Чтобы задать вопрос Авроре, \
    переключите режим в Настройках.";

/// Что сказать ОДИН РАЗ тому, у кого работа шла через свой Claude Code.
///
/// 🔴 Требование владельца при переносе таких настроек вправо (11.09.2026). Смена маршрута
/// данных, о которой человеку не сказали, — тот же дефект, из-за которого всё и затевалось,
/// только с другого конца. Текст называет, что было, что стало и где это менять; без
/// запугивания и без извинений — ничего дурного не произошло.
pub const ROUTE_CHANGED_NOTICE: &str = "Маршрут ИИ-ассистента изменился. Раньше запросы шли \
    в программу Claude Code, установленную на вашем компьютере, теперь они идут через шлюз \
    Авроры – своя подписка для этого больше не нужна. Расчёт медиасплита по-прежнему \
    выполняется на этой машине. Режим работы можно сменить в Настройках.";

/// Подпись «Сейчас: …» для левого положения.
///
/// 🔴 Названы ВСЕ три допустимых обращения (решение владельца Р-1 от 11.09.2026):
/// лицензия, обновления и докачка содержимого. Подпись, называющая два из трёх, врёт
/// умолчанием — а это единственный текст в программе, отвечающий на вопрос «уходят ли
/// мои данные». Состав тройки закреплён сторожем `guard_left_position_egress`.
pub const HEADLINE_LOCAL: &str = "Сейчас: материалы не покидают эту машину – ИИ-ассистент \
    отключён. Наружу уходят только проверка лицензии, обновления программы и докачка \
    содержимого кабинетов и оболочки.";

/// Подпись «Сейчас: …» для правого положения.
pub const HEADLINE_CLOUD: &str =
    "Сейчас: запросы ассистента идут через шлюз Авроры. Расчёт медиасплита остаётся на этой машине.";

/// Фактическое положение переключателя и всё, из чего оно сложилось.
///
/// Слагаемые отдаются наружу целиком нарочно: человеку показывается одно положение, но
/// причина «почему слева» у трёх из четырёх случаев разная, и интерфейс обязан назвать
/// именно свою, а не общую.
#[derive(Debug, Clone, Serialize)]
pub struct RouteState {
    /// Правое положение действует: ассистент работает через шлюз Авроры.
    pub cloud: bool,
    /// Есть ли ассистент в этой редакции (`cloud_advisors`).
    pub advisors_built_in: bool,
    /// Входит ли путь к шлюзу в эту сборку (`thin`).
    pub gateway_built_in: bool,
    /// Действует ли согласие на облачную обработку.
    pub consent_granted: bool,
    /// Выбрано ли человеком «полностью локально» (с учётом переноса прежних настроек).
    pub local_only: bool,
    /// Переключатель заблокирован: в этой сборке пути наружу нет вовсе.
    pub locked: bool,
    /// Почему заблокирован — пустая строка, если не заблокирован.
    pub locked_reason: String,
    /// Готовая подпись «Сейчас: …».
    pub headline: String,
    /// Готовое сообщение для левого положения — показывается ДО отправки.
    ///
    /// 🔴 Текст отдаётся отсюда, а не пишется вторым экземпляром в интерфейсе: две
    /// строки-константы расходятся молча (INV-146), а это ровно тот текст, по которому
    /// человек понимает, уходят ли его материалы.
    pub local_notice: String,
    /// Отказ шлюза по праву, если он был.
    pub gateway_refusal: String,
}

/// Правило положения — без обращения к среде, чтобы проверялось таблицей.
pub fn route_is_cloud(
    local_only: bool,
    consent_granted: bool,
    advisors_built_in: bool,
    gateway_built_in: bool,
) -> bool {
    advisors_built_in && gateway_built_in && consent_granted && !local_only
}

/// Заблокирован ли переключатель: в сборке физически нет пути наружу.
///
/// 🔴 Заблокирован, а НЕ спрятан (решение владельца Р-2 от 11.09.2026): пропавший орган
/// управления человек читает как неисправность, а не как гарантию.
pub fn route_locked_reason(advisors_built_in: bool, gateway_built_in: bool) -> &'static str {
    if !advisors_built_in {
        "Эта редакция собрана без ИИ-ассистента: пути наружу для ваших материалов в ней нет \
         вовсе. Переключатель заблокирован в левом положении."
    } else if !gateway_built_in {
        "В эту сборку не входит путь к шлюзу Авроры – обращаться ассистенту некуда. \
         Переключатель заблокирован в левом положении."
    } else {
        ""
    }
}

/// Фактическое положение по сохранённым настройкам и признакам сборки.
pub fn route_state(app_handle: &tauri::AppHandle) -> RouteState {
    use tauri::Manager;
    let advisors_built_in = crate::commands::claude::CLOUD_ADVISORS_ENABLED;
    let gateway_built_in = cloud_built_in();
    let (local_only, consent_granted) = match app_handle.path().app_config_dir() {
        Ok(dir) => (
            crate::commands::user_config::local_only_enabled(&dir),
            crate::commands::user_config::cloud_consent_granted(&dir),
        ),
        // 🔴 Настройки не прочитались — считаем, что человек СЛЕВА. Ошибка в эту сторону
        // отнимает ответ ассистента; ошибка в другую отправила бы материалы наружу от
        // имени человека, который об этом не просил.
        Err(e) => {
            warn!("каталог настроек недоступен ({e}) – считаем режим полностью локальным");
            (true, false)
        }
    };
    let cloud = route_is_cloud(local_only, consent_granted, advisors_built_in, gateway_built_in);
    RouteState {
        cloud,
        advisors_built_in,
        gateway_built_in,
        consent_granted,
        local_only,
        locked: !advisors_built_in || !gateway_built_in,
        locked_reason: route_locked_reason(advisors_built_in, gateway_built_in).to_string(),
        headline: if cloud { HEADLINE_CLOUD } else { HEADLINE_LOCAL }.to_string(),
        local_notice: LOCAL_MODE_NOTICE.to_string(),
        gateway_refusal: cloud_refusal(),
    }
}

/// Записать положение переключателя.
///
/// Пишутся ОБА хранимых поля: `local_only` — действующая ось, `execution_mode` — её
/// зеркало. Зеркало нужно затем, чтобы перенос прежних настроек (`stored_local_only`)
/// не тянул человека обратно влево после того, как он сам выбрал шлюз.
pub fn set_route(app_handle: &tauri::AppHandle, cloud: bool) -> Result<(), String> {
    use tauri::Manager;
    let config_dir = app_handle
        .path()
        .app_config_dir()
        .map_err(|e| format!("каталог настроек недоступен: {e}"))?;
    let mut config = crate::commands::user_config::load(&config_dir);
    config.local_only = !cloud;
    config.execution_mode = Some(if cloud { "cloud" } else { "local" }.to_string());
    crate::commands::user_config::save(&config_dir, &config)?;
    info!(
        "Режим работы выбран человеком: {}",
        if cloud { "через шлюз Авроры" } else { "полностью локально" }
    );
    Ok(())
}

// ── Зонд доступности локального Claude Code (ВЫВЕДЕН ИЗ УПОТРЕБЛЕНИЯ 11.09.2026) ──

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

/// Собрать команду зонда `--version`.
///
/// На Windows — через `cmd /C`, тем же приёмом, что `run_claude_inner` в `claude.rs`:
/// npm кладёт CLI как `.cmd`-скрипт, а такие скрипты (и скрипт без расширения) Windows
/// не запускает напрямую (os error 193). Правка порядка кандидатов в
/// `find_claude_binary` уже уводит резолв от голого `claude`, когда есть выбор, но если
/// на машине стоит ТОЛЬКО он — выбирать не из чего, и без этой обёртки зонд снова упал
/// бы. На остальных системах путь запускается как есть.
///
/// 🔴 Строку команды строит `claude::windows_cmd_command_line` — тот же построитель,
/// что и у боевого запуска. Своя сборка строки здесь означала бы, что зонд и работа
/// разбирают путь по разным правилам: пока путь передавался отдельным аргументом,
/// знак `&` в имени учётной записи ронял зонд, и материалы клиента уходили на шлюз при
/// рабочей локальной установке.
fn probe_command(binary: &str) -> tokio::process::Command {
    #[cfg(windows)]
    {
        let mut c = tokio::process::Command::new("cmd");
        c.arg("/C");
        c.raw_arg(crate::commands::claude::windows_cmd_command_line(binary, &["--version"]));
        c
    }
    #[cfg(not(windows))]
    {
        let mut c = tokio::process::Command::new(binary);
        c.arg("--version");
        c
    }
}

async fn probe_local() -> (bool, String) {
    // 🔴 Тот же резолв, что и у боевого запуска, и с тем же запомненным ответом: зонд
    // обязан доказывать запускаемость ИМЕННО того файла, который пойдёт в работу.
    let binary = match crate::commands::claude::find_claude_binary_detailed() {
        Ok(path) => path,
        Err(crate::commands::claude::ResolveFailure::Untrusted(path)) => {
            // Отдельная причина: Claude Code стоит и, возможно, работает — мы сами
            // отказались его запускать. Назвать это «не найден» значит скрыть от
            // человека, почему работа ушла на шлюз.
            warn!("Claude Code вне доверенных расположений: {path}");
            return (false, "Claude Code установлен вне доверенных расположений".to_string());
        }
        Err(e) => {
            debug!("Локальный режим недоступен: {e:?}");
            return (false, "Claude Code на этой машине не найден".to_string());
        }
    };

    let mut command = probe_command(&binary);
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
///
/// Вместе с результатом забывается и выбранный путь: если Claude Code переставили в
/// другое место, зонд обязан искать заново, а не подтверждать вчерашний файл.
pub fn forget_local_probe() {
    if let Ok(mut guard) = LOCAL_PROBE.lock() {
        *guard = None;
    }
    crate::commands::claude::forget_claude_binary();
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
///
/// 🔴 Считается от единственной оси и НЕ запускает зонд: запуск чужой программы на
/// машине клиента убран целиком (решение владельца 10.09.2026), а этот вызов был
/// последним местом, где он ещё происходил бы — на каждом открытии кабинета и на
/// каждом возврате фокуса окна. Поле `local_available` осталось в ответе ради
/// совместимости и всегда `false`: локального пути больше нет.
pub async fn state(app_handle: &tauri::AppHandle) -> ModeState {
    let route = route_state(app_handle);
    let mode = if route.cloud { ExecutionMode::Cloud } else { ExecutionMode::Local };
    ModeState {
        mode,
        source: ModeSource::Explicit,
        explanation: route.headline,
        explicit: Some(mode),
        cloud_built_in: route.gateway_built_in,
        local_available: false,
        cloud_refusal: route.gateway_refusal,
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

    /// 🔴 Правило единственного переключателя, перебором ВСЕХ шестнадцати сочетаний.
    ///
    /// Находка внешнего аудита 11.09.2026: подпись считалась от одной оси и на свежей
    /// установке (согласия нет) утверждала уход материалов на наш сервер. Правило
    /// проверяется таблицей именно потому, что ошибка тут не видна на глаз: неверным
    /// оказывается один вход из шестнадцати, и это ровно тот, в котором человек ничего
    /// не выбирал.
    #[test]
    fn right_position_requires_all_four_conditions() {
        for local_only in [false, true] {
            for consent in [false, true] {
                for advisors in [false, true] {
                    for gateway in [false, true] {
                        let cloud = route_is_cloud(local_only, consent, advisors, gateway);
                        let expected = advisors && gateway && consent && !local_only;
                        assert_eq!(
                            cloud, expected,
                            "положение при local_only={local_only}, согласие={consent}, \
                             ассистент в редакции={advisors}, шлюз в сборке={gateway}",
                        );
                        if !cloud {
                            continue;
                        }
                        assert!(
                            consent && !local_only,
                            "правое положение без согласия или при выбранном локальном режиме",
                        );
                    }
                }
            }
        }
        // Свежая установка: согласия ещё нет — переключатель СЛЕВА, что бы ни было в сборке.
        assert!(!route_is_cloud(false, false, true, true), "без согласия наружу не ходим");
    }

    /// Заблокированный переключатель называет СВОЮ причину, а не общую.
    #[test]
    fn locked_switch_names_its_own_reason() {
        assert!(
            route_locked_reason(false, false).contains("без ИИ-ассистента"),
            "локальная редакция обязана объясниться своими словами",
        );
        assert!(
            route_locked_reason(true, false).contains("шлюзу Авроры"),
            "сборка без шлюза обязана назвать именно это",
        );
        assert_eq!(route_locked_reason(true, true), "", "рабочая поставка не блокирует выбор");
    }

    /// Подпись левого положения называет все три допустимых обращения (владелец, Р-1).
    #[test]
    fn left_headline_names_all_three_allowed_calls() {
        for word in ["лицензи", "обновлени", "докачка"] {
            assert!(
                HEADLINE_LOCAL.contains(word),
                "подпись обязана называть «{word}»: {HEADLINE_LOCAL}",
            );
        }
        assert!(
            HEADLINE_LOCAL.contains("не покидают эту машину"),
            "главное обещание обязано стоять в подписи дословно",
        );
        assert!(HEADLINE_CLOUD.contains("шлюз Авроры"), "правое положение называет путь");
        assert!(
            !HEADLINE_LOCAL.contains('—') && !HEADLINE_CLOUD.contains('—'),
            "клиентский текст — короткое тире",
        );
    }

    /// Сообщение о смене маршрута говорит, что было, что стало и где это менять.
    #[test]
    fn route_changed_notice_names_before_after_and_where_to_change() {
        assert!(ROUTE_CHANGED_NOTICE.contains("Claude Code"), "что было");
        assert!(ROUTE_CHANGED_NOTICE.contains("шлюз Авроры"), "что стало");
        assert!(ROUTE_CHANGED_NOTICE.contains("Настройках"), "где менять");
        assert!(
            !ROUTE_CHANGED_NOTICE.contains('—'),
            "клиентский текст — короткое тире",
        );
    }

    /// Сообщение перед отправкой в левом положении называет причину и действие.
    #[test]
    fn local_notice_says_what_to_do() {
        assert!(LOCAL_MODE_NOTICE.contains("ИИ-ассистент отключён"), "причина");
        assert!(LOCAL_MODE_NOTICE.contains("Настройках"), "действие");
        assert!(!LOCAL_MODE_NOTICE.contains('—'), "клиентский текст — короткое тире");
    }

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

    /// Починка ложного зонда: на Windows скрипт `.cmd`/скрипт без расширения не
    /// запускается напрямую (os error 193) — зонд обязан идти через `cmd /C`, как уже
    /// делает настоящий запуск в `claude.rs`. Без этой обёртки прямой `Command::new(binary)`
    /// ложно репортил «Claude Code найден, но не запускается» на рабочей установке.
    ///
    /// 🔴 Плюс главное: строку команды зонд обязан брать у ОБЩЕГО построителя, а не
    /// собирать сам — иначе путь со знаком `&` в имени учётной записи снова разберётся
    /// как оператор, зонд соврёт «недоступно», и материалы уйдут на шлюз. Сам
    /// построитель проверяется в `claude.rs` без привязки к платформе; здесь —
    /// что зонд пользуется именно им.
    #[test]
    #[cfg(windows)]
    fn probe_command_wraps_via_cmd_on_windows() {
        let binary = r"C:\Users\A&B\AppData\Roaming\npm\claude.cmd";
        let cmd = probe_command(binary);
        let std_cmd = cmd.as_std();
        assert_eq!(
            std_cmd.get_program().to_string_lossy(),
            "cmd",
            "зонд обязан запускаться через cmd.exe, а не напрямую"
        );
        let args: Vec<String> = std_cmd
            .get_args()
            .map(|a| a.to_string_lossy().into_owned())
            .collect();
        assert_eq!(
            args,
            vec![
                "/C".to_string(),
                crate::commands::claude::windows_cmd_command_line(binary, &["--version"]),
            ],
            "зонд обязан звать cmd /C со строкой общего построителя"
        );
        assert!(
            args[1].contains(&format!("\"{binary}\"")),
            "путь обязан уехать в кавычках, иначе & разберётся как оператор: {}",
            args[1]
        );
    }
}
