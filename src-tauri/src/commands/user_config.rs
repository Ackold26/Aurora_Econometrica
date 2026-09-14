use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use crate::commands::cabinet;

/// User-configurable settings stored as JSON in app_config_dir.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct UserConfig {
    /// Custom output paths per cabinet: cabinet_id → absolute path
    #[serde(default)]
    pub cabinet_paths: HashMap<String, String>,
    /// Claude model: "sonnet" | "opus"
    #[serde(default)]
    pub model: Option<String>,
    /// Thinking effort: "medium" | "high" | "max"
    #[serde(default)]
    pub model_effort: Option<String>,
    /// Кастомная директория для Econometrica-проектов. Если None - дефолт
    /// (%APPDATA%\<identifier>\projects\). При смене существующие проекты
    /// не переносятся автоматически - пользователю показывается информер.
    #[serde(default)]
    pub econometrica_projects_root: Option<String>,
    /// Согласие пользователя на облачную обработку (кабинеты-советники на Anthropic).
    /// None = согласие не давалось. Только облачная редакция (см. `cloud_consent_required`).
    #[serde(default)]
    pub cloud_consent: Option<CloudConsent>,
    /// Runtime-режим «только локально»: пользователь явно отключил облачный ИИ,
    /// данные не уходят на серверы. Одна сборка, два режима — тумблер в Настройках.
    /// Дефолт false. Проверяется в egress-чок-поинте `run_claude` (defense-in-depth).
    #[serde(default)]
    pub local_only: bool,
    /// Явный выбор режима исполнения советника человеком: `"local"` (свой Claude Code)
    /// или `"cloud"` (шлюз Авроры). `None` — выбора не делал, работает автоопределение
    /// (ADR-049 §3).
    ///
    /// 🔴 Это ДРУГАЯ ось, чем `local_only` выше, и путать их нельзя. `local_only`
    /// отвечает на вопрос «обращаться ли к облачному ИИ вообще»; это поле — «если
    /// обращаемся, чей Claude Code исполняет работу». Первый вопрос решается раньше и
    /// может запретить обращение целиком, второй действует только внутри разрешённого.
    ///
    /// Лежит в durable-настройках, а не в памяти процесса: явный выбор ОБЯЗАН пережить
    /// перезапуск, иначе человек, выбравший локальный режим ради того, чтобы материалы
    /// не проходили через наши серверы, молча окажется на шлюзе после перезапуска.
    #[serde(default)]
    pub execution_mode: Option<String>,
    /// Нужно ли один раз сказать человеку, что маршрут ассистента сменился.
    ///
    /// Ставится переносом прежних настроек (`migrate_route_axis`) тем, у кого работа шла
    /// через свой Claude Code, снимается после показа. Дефолт false — новым установкам
    /// говорить не о чем.
    #[serde(default)]
    pub route_notice_pending: bool,
    /// Согласие на «Условия ознакомительного использования» (пробный период, вынесенный
    /// из лицензионного договора в отдельный документ, п.5 ст.1286 ГК РФ, единый для
    /// линейки Aurora AI). None = согласие не давалось.
    #[serde(default)]
    pub trial_consent: Option<TrialConsent>,
}

/// Редакция «Условий ознакомительного использования». Bump (при изменении формулировок
/// правовым блоком) → согласие запрашивается повторно. Формат ГГГГ-ММ-ДД.НН — дата
/// правки + двузначный номер редакции ЭТОГО дня, сортируется лексикографически, поэтому
/// сравнение строк ниже даёт верный хронологический порядок.
///
/// 🔴 s48, 14.09.2026 (второй бамп за сутки): раньше редакция опознавалась ГОЛОЙ датой
/// (`ГГГГ-ММ-ДД`), а номер в документе не стоял вовсе. Правовой блок поднял в документе
/// номер до 2, но текст изменился СУЩЕСТВЕННО (срок ознакомления 30→15 дней и другие
/// пункты) в течение одних тех же суток — голая дата не различает такие версии, и человек,
/// принявший редакцию 1, остался бы с согласием на документ, которого больше нет, а окно
/// не поднялось бы никогда (`"2026-09-14" < "2026-09-14"` — ложь). Отсюда номер редакции
/// ВНУТРИ константы, а не только в тексте для человека. Номер — ИМЕННО двузначный: при
/// однозначной записи `".10" < ".2"` лексикографически (де­сятая правка read как меньшая
/// второй) — та же ловушка на новом уровне.
///
/// 🔴 Текст чекбокса `TrialConsentOverlay.svelte` (юридически согласованный, менять нельзя)
/// обязан называть И номер, И дату редакции — этого требует п.10.1 самого документа.
/// Расхождение с этой константой ловит тест `trial_terms_revision_matches_frontend_checkbox_text`
/// ниже (в родственном продукте линейки разошедшиеся константы фронта и Rust уже были
/// проблемой).
pub const TRIAL_TERMS_REVISION: &str = "2026-09-14.02";

/// Имя PDF-файла условий, поставляемого бандлом рядом со справкой продукта
/// (`src-tauri/help-econometrica/`, см. `tauri.conf.json` → `bundle.resources`,
/// "help-econometrica/*"). Одна константа на команду открытия и сторож поставки —
/// чтобы имя не разъехалось между ними.
pub const TRIAL_TERMS_PDF_FILENAME: &str = "Условия ознакомительного использования.pdf";

/// Имя PDF-файла «Порядок обработки данных - Aurora AI Econometrica», второго обязательного
/// документа правового комплекта (см. Business/Projects/СИГНАЛ_сессиям_правовой_комплект_
/// 2026-09-14.md). На него ссылаются пункты 6.2, 6.5, 6.8 «Условий»: без него эти пункты
/// ведут в пустоту. Поставляется тем же бандлом, что и `TRIAL_TERMS_PDF_FILENAME` —
/// `help-econometrica/*` в `tauri.conf.json` уже включает весь каталог маской, отдельная
/// строка ресурса не нужна.
/// 🔴 s48 (2026-09-14): правовой блок переименовал файл (убрал длинное тире из имени -
/// имя файла - контракт с кодом) - было «... — Econometrica.pdf», стало «... - Aurora AI
/// Econometrica.pdf» (короткое тире). Синхронизировано с sync_trial_terms.py и манифестом.
pub const DATA_PROCESSING_PDF_FILENAME: &str = "Порядок обработки данных - Aurora AI Econometrica.pdf";

/// Ключи документов в `tools/trial_terms_manifest.json` (объект `documents`). Общие для
/// Rust-сторожа и `tools/sync_trial_terms.py` — расхождение ключа сторож ловит тем же
/// приёмом, что и расхождение имени файла (`sync_script_filename_matches_rust_constant`).
pub const TRIAL_TERMS_MANIFEST_KEY: &str = "terms";
pub const DATA_PROCESSING_MANIFEST_KEY: &str = "data_processing";

/// Зафиксированное согласие на условия ознакомительного использования. Юридически
/// значимо → хранится в durable backend-конфиге (см. `CloudConsent` выше — тот же приём).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrialConsent {
    /// Редакция документа, на которую дано согласие (ISO ГГГГ-ММ-ДД).
    pub revision: String,
    /// Unix-время (секунды) принятия — для аудита.
    pub accepted_at: i64,
}

/// Pure: устарело/отсутствует ли согласие на условия ознакомительного использования.
fn trial_consent_outdated(consent: &Option<TrialConsent>) -> bool {
    match consent {
        Some(c) => c.revision.as_str() < TRIAL_TERMS_REVISION,
        None => true,
    }
}

/// Нужно ли показать экран согласия на условия ознакомительного использования:
/// согласие отсутствует или дано на устаревшую (более старую) редакцию документа.
pub fn trial_consent_required(config_dir: &Path) -> bool {
    trial_consent_outdated(&load(config_dir).trial_consent)
}

/// Версия условий облачной обработки. Bump → согласие запрашивается повторно
/// (например, при изменении формулировок EULA об облачной обработке).
pub const CLOUD_CONSENT_TERMS_VERSION: u32 = 1;

/// Зафиксированное согласие на облачную обработку. Юридически значимо → хранится в
/// durable backend-конфиге (НЕ localStorage, который сбрасывается при очистке WebView2-кэша).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CloudConsent {
    /// Версия условий, на которые дано согласие.
    pub terms_version: u32,
    /// Unix-время (секунды) принятия — для аудита.
    pub accepted_at: i64,
}

/// Pure: устарело/отсутствует ли согласие (без проверки редакции и диска).
fn consent_outdated(consent: &Option<CloudConsent>) -> bool {
    match consent {
        Some(c) => c.terms_version < CLOUD_CONSENT_TERMS_VERSION,
        None => true,
    }
}

/// Нужно ли запросить согласие на облачную обработку: только в облачной редакции
/// (`cloud_advisors`) и если согласие отсутствует или дано на устаревшую версию условий.
/// В локальной редакции облачной обработки нет → согласие не требуется никогда.
pub fn cloud_consent_required(config_dir: &Path) -> bool {
    if !crate::commands::claude::CLOUD_ADVISORS_ENABLED {
        return false;
    }
    consent_outdated(&load(config_dir).cloud_consent)
}

/// Левое положение единственного переключателя, выведенное из сохранённых настроек.
///
/// 🔴 Ось ровно одна — `local_only`. Прежнее поле `execution_mode` («чей Claude Code
/// исполняет работу») положение НЕ задаёт: маршрут через свой Claude Code клиента убран,
/// а человек, выбиравший его, согласие на облачную обработку уже давал — оно спрашивалось
/// ДО развилки маршрута, в обеих ветках. Он выбирал не локальность, а путь мимо нашего
/// шлюза, но всё равно наружу. Такого человека переносим ВПРАВО и говорим об этом вслух
/// (решение владельца 11.09.2026, см. `migrate_route_axis`), а не отнимаем ассистента
/// молча: молчаливая пропажа читается как поломка, а не как забота.
pub fn stored_local_only(config: &UserConfig) -> bool {
    config.local_only
}

/// Каталоги настроек, где перенос маршрута случился, а записать признак сообщения не
/// удалось (настройки только для чтения, диск полон).
///
/// 🔴 Смена маршрута от записи НЕ зависит: положение считается по `local_only` и согласию,
/// а прежнее `execution_mode` его не задаёт. Значит, при отказе записи маршрут всё равно
/// сменился — а признак на диске остался снятым, и человек не узнал бы об этом никогда
/// (находка внешнего аудита 11.09.2026: `let _ = save(..)` глотал отказ). Здесь признак
/// держится хотя бы до конца запуска. Ключ — каталог, а не общий флаг: тесты идут
/// параллельно, и один общий флаг перетекал бы из теста в тест.
static ROUTE_NOTICE_UNSAVED: Mutex<Vec<PathBuf>> = Mutex::new(Vec::new());

fn route_notice_unsaved(config_dir: &Path) -> bool {
    ROUTE_NOTICE_UNSAVED
        .lock()
        .map(|dirs| dirs.iter().any(|d| d == config_dir))
        .unwrap_or(false)
}

fn set_route_notice_unsaved(config_dir: &Path, pending: bool) {
    if let Ok(mut dirs) = ROUTE_NOTICE_UNSAVED.lock() {
        dirs.retain(|d| d != config_dir);
        if pending {
            dirs.push(config_dir.to_path_buf());
        }
    }
}

/// Перенести прежние настройки на единственную ось. Возвращает `true`, если человеку нужно
/// один раз сказать, что маршрут ассистента сменился.
///
/// Какой именно текст показать, решает не перенос, а фактическое положение в момент показа
/// (`execution_mode::route_changed_notice`): у кого согласие отозвано или устарело, тот
/// после переноса остаётся СЛЕВА, и сообщение «теперь через шлюз Авроры» было бы ложью.
///
/// 🔴 Идемпотентность держится на успешной ЗАПИСИ: после переноса `execution_mode`
/// становится зеркалом положения («cloud»), и второй раз условие не выполняется. Если
/// запись не удалась, перенос повторится при следующем запуске — и сообщение тоже, это
/// честнее молчания. Признак `route_notice_pending` живёт в durable-настройках: человек,
/// закрывший программу до того, как прочитал сообщение, обязан увидеть его при следующем
/// запуске — иначе смена маршрута данных пройдёт молча.
pub fn migrate_route_axis(config_dir: &Path) -> bool {
    let mut config = load(config_dir);
    if config.execution_mode.as_deref() == Some("local") && !config.local_only {
        config.execution_mode = Some("cloud".to_string());
        config.route_notice_pending = true;
        if let Err(e) = save(config_dir, &config) {
            log::warn!(
                "перенос маршрута ассистента не записан ({e}) – сообщение о смене маршрута \
                 держится до конца запуска, перенос повторится при следующем"
            );
            set_route_notice_unsaved(config_dir, true);
        }
        return true;
    }
    config.route_notice_pending || route_notice_unsaved(config_dir)
}

/// Ждёт ли показа сообщение о смене маршрута: признак на диске или незаписанный признак
/// этого запуска.
pub fn route_notice_pending(config_dir: &Path) -> bool {
    load(config_dir).route_notice_pending || route_notice_unsaved(config_dir)
}

/// Снять признак: сообщение о смене маршрута человеку показано.
pub fn clear_route_notice(config_dir: &Path) -> Result<(), String> {
    set_route_notice_unsaved(config_dir, false);
    let mut config = load(config_dir);
    if !config.route_notice_pending {
        return Ok(());
    }
    config.route_notice_pending = false;
    save(config_dir, &config)
}

/// Включён ли режим «полностью локально» (левое положение переключателя, egress
/// ассистента отключён). Дефолт false (нет конфига / поле отсутствует → правое
/// положение, если редакция облачная, путь к шлюзу в сборке есть и согласие дано).
pub fn local_only_enabled(config_dir: &Path) -> bool {
    stored_local_only(&load(config_dir))
}

/// Дано ли действующее согласие на облачную обработку (без учёта редакции).
///
/// Согласие — часть выбора режима (решение владельца 10.09.2026 №3): отдельного
/// переключателя больше нет, вопрос задаётся один раз при первом переводе вправо, а
/// отказ оставляет переключатель слева. Поэтому фактическое положение обязано читать
/// и его тоже — иначе подпись под переключателем утверждает уход материалов там, где
/// его нет (находка внешнего аудита 11.09.2026).
pub fn cloud_consent_granted(config_dir: &Path) -> bool {
    !consent_outdated(&load(config_dir).cloud_consent)
}

fn config_path(config_dir: &Path) -> PathBuf {
    config_dir.join("user_config.json")
}

/// Замок записи настроек на процесс: `save` вызывается из многих команд, а временный файл
/// у процесса один. Держится на время «записать временный + переименовать».
static SAVE_LOCK: Mutex<()> = Mutex::new(());

/// Временный файл записи. Своё имя у каждого процесса: две копии программы, пишущие в
/// один временный файл, склеили бы половинки друг друга.
fn tmp_path(config_dir: &Path) -> PathBuf {
    config_dir.join(format!("user_config.json.{}.tmp", std::process::id()))
}

pub fn load(config_dir: &Path) -> UserConfig {
    let path = config_path(config_dir);
    if !path.exists() {
        return UserConfig::default();
    }
    match std::fs::read_to_string(&path) {
        Ok(data) => match serde_json::from_str(&data) {
            Ok(config) => config,
            Err(e) => {
                // 🔴 Нечитаемые настройки подменяются значениями по умолчанию — и первая же
                // запись затёрла бы их навсегда. Копия кладётся рядом один раз: без неё
                // потерю всех настроек человека нечем ни объяснить, ни вернуть.
                let kept = config_dir.join("user_config.json.corrupt");
                if !kept.exists() {
                    let _ = std::fs::copy(&path, &kept);
                }
                log::warn!(
                    "настройки не разобрались ({e}) – действуют значения по умолчанию, \
                     прежний файл сохранён как {}",
                    kept.display()
                );
                UserConfig::default()
            }
        },
        Err(_) => UserConfig::default(),
    }
}

/// Записать настройки.
///
/// 🔴 Через временный файл и переименование, а не `fs::write` поверх: обрыв питания или
/// снятие процесса посреди записи оставлял битый JSON, `load` молча возвращал значения по
/// умолчанию, и все настройки человека исчезали без единого слова (находка внешнего аудита
/// 11.09.2026). Переименование в пределах каталога заменяет файл целиком: на диске лежит
/// либо прежняя версия, либо новая. Гонку двух одновременно запущенных копий программы
/// (чтение–правка–запись) это не снимает — только порчу файла.
///
/// 🔴 Внутри процесса запись сериализована замком: имя временного файла различает процессы,
/// но не потоки, а `save` зовут из девятнадцати мест — два потока склеили бы в одном
/// временном файле половинки разных настроек (находка внешнего аудита s42).
pub fn save(config_dir: &Path, config: &UserConfig) -> Result<(), String> {
    let _serialized = SAVE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let path = config_path(config_dir);
    let _ = std::fs::create_dir_all(config_dir);
    let data = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    let tmp = tmp_path(config_dir);
    let written = std::fs::File::create(&tmp).and_then(|mut f| {
        f.write_all(data.as_bytes())?;
        f.sync_all()
    });
    if let Err(e) = written.and_then(|_| std::fs::rename(&tmp, &path)) {
        let _ = std::fs::remove_file(&tmp);
        return Err(e.to_string());
    }
    Ok(())
}

/// Returns the workspace root for a cabinet.
/// If a custom path is configured, uses it; otherwise falls back to Desktop/AIAgency/<folder>.
pub fn get_cabinet_workspace(config_dir: &Path, cabinet_id: &str) -> Result<PathBuf, String> {
    let config = load(config_dir);
    if let Some(custom) = config.cabinet_paths.get(cabinet_id) {
        if !custom.is_empty() {
            return Ok(PathBuf::from(custom));
        }
    }
    default_cabinet_workspace(cabinet_id)
}

/// Default workspace path: %USERPROFILE%\Desktop\AIAgency\<cabinet_folder>
pub fn default_cabinet_workspace(cabinet_id: &str) -> Result<PathBuf, String> {
    let user_profile = std::env::var("USERPROFILE")
        .map_err(|_| "USERPROFILE environment variable is not set".to_string())?;
    let folder = cabinet::cabinet_folder_name(cabinet_id);
    Ok(PathBuf::from(&user_profile)
        .join("Desktop")
        .join("AIAgency")
        .join(folder))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn consent_required_when_absent() {
        assert!(consent_outdated(&None));
    }

    #[test]
    fn consent_satisfied_at_current_version() {
        let c = Some(CloudConsent { terms_version: CLOUD_CONSENT_TERMS_VERSION, accepted_at: 1 });
        assert!(!consent_outdated(&c));
    }

    #[test]
    fn consent_required_again_when_terms_bumped() {
        // Согласие дано на более старую версию условий → требуется повторно.
        let c = Some(CloudConsent { terms_version: CLOUD_CONSENT_TERMS_VERSION.saturating_sub(1), accepted_at: 1 });
        if CLOUD_CONSENT_TERMS_VERSION == 0 {
            // Защита от вырожденного случая, если константу сбросят в 0.
            assert!(!consent_outdated(&c));
        } else {
            assert!(consent_outdated(&c));
        }
    }

    #[test]
    fn cloud_consent_serde_roundtrip() {
        let c = CloudConsent { terms_version: 3, accepted_at: 1_700_000_000 };
        let json = serde_json::to_string(&c).unwrap();
        let back: CloudConsent = serde_json::from_str(&json).unwrap();
        assert_eq!(back.terms_version, 3);
        assert_eq!(back.accepted_at, 1_700_000_000);
    }

    #[test]
    fn local_only_defaults_false_for_legacy_config() {
        // Старый конфиг без поля local_only → serde default false (НЕ миграция,
        // старые user_config.json читаются без ошибок).
        let cfg: UserConfig = serde_json::from_str(r#"{"model":"opus"}"#).unwrap();
        assert!(!cfg.local_only);
    }

    #[test]
    fn local_only_serde_roundtrip() {
        let cfg = UserConfig { local_only: true, ..Default::default() };
        let json = serde_json::to_string(&cfg).unwrap();
        let back: UserConfig = serde_json::from_str(&json).unwrap();
        assert!(back.local_only);
    }
    /// Гейт приёмки 3 ADR-049: явный выбор режима ПЕРЕЖИВАЕТ перезапуск.
    ///
    /// 🔴 Проверяется круг «записали → прочитали с диска», а не присвоение поля:
    /// человек, выбравший свой Claude Code ради того, чтобы материалы не проходили
    /// через наши серверы, после перезапуска не должен молча оказаться на шлюзе.
    #[test]
    fn explicit_mode_survives_restart() {
        let dir = std::env::temp_dir().join(format!("aurora-econ-cfg-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);

        let mut config = UserConfig::default();
        assert_eq!(config.execution_mode, None, "по умолчанию работает автоопределение");

        config.execution_mode = Some("local".to_string());
        save(&dir, &config).expect("настройки обязаны записаться");

        let reloaded = load(&dir);
        assert_eq!(
            reloaded.execution_mode.as_deref(),
            Some("local"),
            "выбор режима обязан пережить перезапуск",
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 🔴 Перенос прежних настроек при сведении трёх осей к одной (владелец, 11.09.2026).
    ///
    /// Левое положение задаёт РОВНО ОДНО хранимое поле. Прежний выбор «свой Claude Code»
    /// влево не тянет: согласие на облачную обработку у такого человека уже есть, и молча
    /// отнимать у него ассистента нельзя. Тест перебирает все сочетания — ошибиться в таком
    /// правиле можно ровно в пропущенном сочетании, а не в разобранном.
    #[test]
    fn only_the_explicit_local_only_moves_the_switch_left() {
        let cases: &[(bool, Option<&str>, bool, &str)] = &[
            (false, None, false, "свежая установка — правое положение по умолчанию"),
            (true, None, true, "включённый «только локально» остаётся слева"),
            (false, Some("local"), false, "прежний свой Claude Code переносится вправо"),
            (true, Some("local"), true, "но запрет обращений сильнее прежнего выбора пути"),
            (false, Some("cloud"), false, "выбравший шлюз остаётся справа"),
            (true, Some("cloud"), true, "запрет обращений сильнее прежнего выбора пути"),
            (false, Some("узел-а"), false, "неизвестное значение не двигает переключатель"),
        ];
        for (local_only, execution_mode, expected_left, why) in cases {
            let config = UserConfig {
                local_only: *local_only,
                execution_mode: execution_mode.map(|s| s.to_string()),
                ..Default::default()
            };
            assert_eq!(stored_local_only(&config), *expected_left, "{why}");
        }
    }

    /// Перенос маршрута: вправо, один раз, с сообщением — и не повторяется.
    #[test]
    fn moving_the_old_local_route_right_says_so_once() {
        let dir = std::env::temp_dir().join(format!("aurora-econ-migrate-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);

        // Человек работал через свой Claude Code.
        let config = UserConfig { execution_mode: Some("local".to_string()), ..Default::default() };
        save(&dir, &config).expect("прежние настройки записаны");

        assert!(migrate_route_axis(&dir), "о смене маршрута обязаны сказать");
        let after = load(&dir);
        assert!(!stored_local_only(&after), "перенос обязан оставить человека справа");
        assert_eq!(after.execution_mode.as_deref(), Some("cloud"), "зеркало положения обновлено");
        assert!(after.route_notice_pending, "признак сообщения обязан пережить перезапуск");

        // Повторный запуск до показа сообщения: признак держится, но перенос не повторяется.
        assert!(migrate_route_axis(&dir), "непоказанное сообщение обязано дожить до показа");

        clear_route_notice(&dir).expect("после показа признак снимается");
        assert!(!migrate_route_axis(&dir), "показанное сообщение не повторяется");

        // А тому, кто выбрал «только локально», ничего не переносим и ничего не говорим.
        let _ = std::fs::remove_dir_all(&dir);
        let config = UserConfig {
            execution_mode: Some("local".to_string()),
            local_only: true,
            ..Default::default()
        };
        save(&dir, &config).expect("настройки записаны");
        assert!(!migrate_route_axis(&dir), "выбравшему локальный режим сообщать не о чем");
        assert!(stored_local_only(&load(&dir)), "и он обязан остаться слева");

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 🔴 Отказ записи при переносе не делает смену маршрута молчаливой.
    ///
    /// Маршрут сменился независимо от записи (положение считает `local_only` и согласие),
    /// поэтому признак сообщения обязан дожить хотя бы до показа в этом запуске, а отказ —
    /// дойти до вызывающего, а не утонуть в `let _`. Отказ носителя изображён каталогом на
    /// месте временного файла: создать файл поверх каталога нельзя ни в одной системе.
    #[test]
    fn route_notice_survives_a_failed_write() {
        let dir = std::env::temp_dir().join(format!("aurora-econ-rofail-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let config = UserConfig { execution_mode: Some("local".to_string()), ..Default::default() };
        save(&dir, &config).expect("прежние настройки записаны");

        std::fs::create_dir_all(tmp_path(&dir)).expect("носитель испорчен нарочно");
        assert!(save(&dir, &config).is_err(), "отказ записи обязан дойти до вызывающего");

        assert!(migrate_route_axis(&dir), "о смене маршрута обязаны сказать и без записи");
        assert_eq!(
            load(&dir).execution_mode.as_deref(),
            Some("local"),
            "на диске перенос не записан – зонд действительно изобразил отказ",
        );
        assert!(route_notice_pending(&dir), "незаписанный признак обязан дожить до показа");

        clear_route_notice(&dir).expect("снятие незаписанного признака не пишет на диск");
        assert!(!route_notice_pending(&dir), "после показа в этом запуске не повторяем");

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Запись заменяет файл целиком и не оставляет временных файлов; битый файл не
    /// затирается молча.
    #[test]
    fn save_replaces_whole_file_and_keeps_a_corrupt_one() {
        let dir = std::env::temp_dir().join(format!("aurora-econ-atomic-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);

        save(&dir, &UserConfig { local_only: true, ..Default::default() }).expect("первая запись");
        save(&dir, &UserConfig { model: Some("opus".into()), ..Default::default() })
            .expect("запись поверх существующего файла");
        let back = load(&dir);
        assert_eq!(back.model.as_deref(), Some("opus"));
        assert!(!back.local_only, "файл заменён целиком, а не дописан");
        assert!(!tmp_path(&dir).exists(), "временный файл не остаётся");

        std::fs::write(config_path(&dir), "{\"local_only\": tru").expect("файл испорчен нарочно");
        let fallback = load(&dir);
        assert!(!fallback.local_only, "битый файл читается как значения по умолчанию");
        let kept = dir.join("user_config.json.corrupt");
        assert_eq!(
            std::fs::read_to_string(&kept).expect("копия битого файла обязана остаться"),
            "{\"local_only\": tru",
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Две оси не путаются в хранении: выбор пути не трогает запрет обращений.
    ///
    /// 🔴 `local_only` («не обращаться к облачному ИИ вовсе») и `execution_mode`
    /// («если обращаемся, чей Claude Code») живут рядом и звучат похоже. Тест
    /// закрепляет, что запись одного не меняет другое — иначе человек, выбравший
    /// шлюз, однажды обнаружил бы снятым свой запрет на обращения.
    #[test]
    fn choosing_a_route_does_not_touch_the_egress_ban() {
        let dir = std::env::temp_dir().join(format!("aurora-econ-axes-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);

        let mut config = UserConfig::default();
        config.local_only = true;
        save(&dir, &config).expect("запрет обращений записан");

        let mut reloaded = load(&dir);
        reloaded.execution_mode = Some("cloud".to_string());
        save(&dir, &reloaded).expect("выбор пути записан");

        let after = load(&dir);
        assert!(after.local_only, "запрет обращений обязан уцелеть при выборе пути");
        assert_eq!(after.execution_mode.as_deref(), Some("cloud"));

        let _ = std::fs::remove_dir_all(&dir);
    }

    // ── Условия ознакомительного использования (s48, 2026-09-14) ──────────────────

    #[test]
    fn trial_consent_required_when_absent() {
        assert!(trial_consent_outdated(&None));
    }

    #[test]
    fn trial_consent_satisfied_at_current_revision() {
        let c = Some(TrialConsent { revision: TRIAL_TERMS_REVISION.to_string(), accepted_at: 1 });
        assert!(!trial_consent_outdated(&c));
    }

    #[test]
    fn trial_consent_required_again_when_revision_is_older() {
        // Согласие дано на более старую (лексикографически меньшую ISO-дату) редакцию →
        // требуется повторно, даже если признак принятия стоит.
        let c = Some(TrialConsent { revision: "2020-01-01".to_string(), accepted_at: 1 });
        assert!(trial_consent_outdated(&c));
    }

    #[test]
    fn trial_consent_serde_roundtrip() {
        let c = TrialConsent { revision: "2026-09-14".to_string(), accepted_at: 1_700_000_000 };
        let json = serde_json::to_string(&c).unwrap();
        let back: TrialConsent = serde_json::from_str(&json).unwrap();
        assert_eq!(back.revision, "2026-09-14");
        assert_eq!(back.accepted_at, 1_700_000_000);
    }

    /// Гейт приёмки: согласие ПЕРЕЖИВАЕТ перезапуск (durable-хранение, не только память
    /// процесса) — тот же круг «записали → прочитали с диска», что и у `explicit_mode_survives_restart`.
    #[test]
    fn trial_consent_survives_restart() {
        let dir = std::env::temp_dir().join(format!("aurora-econ-trial-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);

        assert!(trial_consent_required(&dir), "свежая установка - согласие ещё не дано");

        let mut config = load(&dir);
        config.trial_consent = Some(TrialConsent {
            revision: TRIAL_TERMS_REVISION.to_string(),
            accepted_at: 1_726_000_000,
        });
        save(&dir, &config).expect("согласие обязано записаться");

        assert!(!trial_consent_required(&dir), "согласие на текущую редакцию обязано пережить перезапуск");
        let reloaded = load(&dir).trial_consent.expect("согласие обязано читаться с диска");
        assert_eq!(reloaded.revision, TRIAL_TERMS_REVISION);
        assert_eq!(reloaded.accepted_at, 1_726_000_000);

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// При смене редакции (правовой блок обновил текст условий) сохранённое согласие на
    /// СТАРУЮ редакцию не защищает от повторного показа — человек обязан увидеть новый текст.
    #[test]
    fn trial_consent_shows_again_when_saved_revision_is_outdated() {
        let dir = std::env::temp_dir().join(format!("aurora-econ-trial-stale-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);

        let config = UserConfig {
            trial_consent: Some(TrialConsent { revision: "2025-01-01".to_string(), accepted_at: 1 }),
            ..Default::default()
        };
        save(&dir, &config).expect("прежнее согласие записано");

        assert!(
            trial_consent_required(&dir),
            "согласие на устаревшую редакцию не должно закрывать показ окна"
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Старый конфиг без поля `trial_consent` (люди, обновившиеся с версии до s48) читается
    /// без ошибок serde и трактуется как «согласия не было» — а не как отказ разбора файла.
    #[test]
    fn trial_consent_defaults_to_none_for_legacy_config() {
        let cfg: UserConfig = serde_json::from_str(r#"{"model":"opus"}"#).unwrap();
        assert!(cfg.trial_consent.is_none());
    }

    /// 🔴 Сторож монотонности (s48, 14.09.2026, второй бамп за сутки): суть находки этой
    /// задачи. Прежний формат `TRIAL_TERMS_REVISION` был голой датой - редакция 1 и редакция 2
    /// поднялись в ОДИН день, и голая дата не различила бы их (человек, принявший прежний
    /// текст, остался бы согласившимся на документ, которого больше нет). Наивный переход
    /// на голый номер редакции ("2" вместо даты) воспроизвёл бы ту же дыру зеркально: "2" -
    /// префикс строки "2026-09-14", а более короткая строка при совпадающем начале МЕНЬШЕ,
    /// то есть `"2026-09-14" < "2"` дало бы ЛОЖЬ и окно не поднялось бы уже для старого
    /// боевого значения. Список ниже перебирает несколько прошлых значений - не одно, как
    /// раньше `trial_consent_shows_again_when_saved_revision_is_outdated` - потому что именно
    /// перечень доказывает монотонность, а не единичный частный случай.
    ///
    /// Ось мутации: заменить `TRIAL_TERMS_REVISION` на голый номер ("2") без даты, или на
    /// дату без номера ("2026-09-14") - оба варианта красят этот тест (первый - на прежнем
    /// боевом значении "2026-09-14" в списке, второй - тем, что сравнение снова не различает
    /// редакции одного дня).
    #[test]
    fn trial_consent_revision_monotonicity_across_past_values() {
        let past_revisions = ["2026-09-14", "2025-01-01", ""];
        for past in past_revisions {
            let c = Some(TrialConsent { revision: past.to_string(), accepted_at: 1 });
            assert!(
                trial_consent_outdated(&c),
                "согласие на прошлую редакцию {past:?} обязано считаться устаревшим против \
                 текущей TRIAL_TERMS_REVISION = {TRIAL_TERMS_REVISION} - иначе принявшие её \
                 люди никогда не увидят новое окно"
            );
        }

        // Обратное: согласие на ТЕКУЩУЮ редакцию не должно снова поднимать окно.
        let current = Some(TrialConsent {
            revision: TRIAL_TERMS_REVISION.to_string(),
            accepted_at: 1,
        });
        assert!(
            !trial_consent_outdated(&current),
            "согласие на текущую редакцию TRIAL_TERMS_REVISION = {TRIAL_TERMS_REVISION} не \
             должно снова требовать окна"
        );
    }
}

/// 🔴 Сторож расхождения констант фронта/Rust (s48, 2026-09-14): дата в юридически
/// согласованном тексте чекбокса `TrialConsentOverlay.svelte` обязана совпадать с
/// `TRIAL_TERMS_REVISION`. В родственном продукте линейки такие константы уже расходились
/// молча — здесь любое расхождение краснеет прогон.
///
/// Ось мутации: поднять `TRIAL_TERMS_REVISION` без правки текста во фронтенд-компоненте
/// (или наоборот) — тест обязан покраснеть.
#[cfg(test)]
mod trial_terms_frontend_consistency_guard {
    use super::TRIAL_TERMS_REVISION;

    #[test]
    fn trial_terms_revision_matches_frontend_checkbox_text() {
        const OVERLAY: &str =
            include_str!("../../../src/lib/components/TrialConsentOverlay.svelte");

        // Формат ГГГГ-ММ-ДД.НН: дата + двузначный номер редакции этого дня (см. докстринг
        // TRIAL_TERMS_REVISION). Разбираем ОБЕ части - п.10.1 документа требует, чтобы текст
        // чекбокса называл И номер, И дату, поэтому сторож обязан проверить обе, а не только
        // дату, как раньше (когда номера в константе не было вовсе).
        let (date_part, number_part) = TRIAL_TERMS_REVISION.split_once('.').unwrap_or_else(|| {
            panic!(
                "TRIAL_TERMS_REVISION обязана быть в формате ГГГГ-ММ-ДД.НН (дата + номер \
                 редакции дня), получено {TRIAL_TERMS_REVISION}"
            )
        });
        let date_parts: Vec<&str> = date_part.split('-').collect();
        assert_eq!(
            date_parts.len(),
            3,
            "дата в TRIAL_TERMS_REVISION обязана быть в формате ГГГГ-ММ-ДД, получено {date_part} \
             (TRIAL_TERMS_REVISION = {TRIAL_TERMS_REVISION})"
        );
        let ru_date = format!("{}.{}.{}", date_parts[2], date_parts[1], date_parts[0]);
        let revision_number: u32 = number_part.parse().unwrap_or_else(|_| {
            panic!(
                "номер редакции в TRIAL_TERMS_REVISION не разобрался как число: {number_part} \
                 (TRIAL_TERMS_REVISION = {TRIAL_TERMS_REVISION})"
            )
        });
        // s48: докстринг TRIAL_TERMS_REVISION требует двузначный номер - иначе строковое
        // сравнение в trial_consent_outdated (".10" < ".2" лексикографически) даёт ту же
        // ловушку монотонности, что уже чинили на уровне даты. u32::parse однозначный номер
        // разбирает без возражений, поэтому длину проверяем отдельно.
        assert_eq!(
            number_part.len(),
            2,
            "номер редакции в TRIAL_TERMS_REVISION обязан быть двузначным (docstring требует \
             ГГГГ-ММ-ДД.НН) - иначе строковое сравнение \".10\" < \".2\" в trial_consent_outdated \
             сломает монотонность редакций на новом уровне; получено '{number_part}' \
             (TRIAL_TERMS_REVISION = {TRIAL_TERMS_REVISION})"
        );

        assert!(
            OVERLAY.contains(&ru_date),
            "текст чекбокса в TrialConsentOverlay.svelte не содержит дату редакции {ru_date} \
             (TRIAL_TERMS_REVISION = {TRIAL_TERMS_REVISION}) - константы разошлись"
        );
        let ru_number = revision_number.to_string();
        assert!(
            OVERLAY.contains(&format!("редакция {ru_number} от")),
            "текст чекбокса в TrialConsentOverlay.svelte не содержит номер редакции \
             {ru_number} (TRIAL_TERMS_REVISION = {TRIAL_TERMS_REVISION}) - п.10.1 документа \
             требует называть номер, не только дату"
        );
    }
}

/// Сверяет байты PDF с ожидаемой суммой одного документа из манифеста
/// `tools/trial_terms_manifest.json` (JSON: `{"documents": {"<key>": {"sha256": "...",
/// "revision": "...", "status": "..."}, ...}}`). `doc_key` — ключ документа внутри
/// `documents` (`TRIAL_TERMS_MANIFEST_KEY` / `DATA_PROCESSING_MANIFEST_KEY`), `human_name` —
/// название для человека, попадающее в текст ошибки, чтобы сторож называл КОНКРЕТНЫЙ
/// документ, а не абстрактный "PDF". Чистая функция — без обращения к диску, поэтому её
/// красное/зелёное поведение проверяется юнит-тестами на синтетических данных
/// (`trial_terms_manifest_guard_logic` ниже), а не только на реальном (юридически значимом,
/// живущем вне репозитория) файле.
///
/// 🔴 Требование владельца s48 (2026-09-14): «сторож, который никогда не краснел, ничего не
/// сторожит» — в этой линейке одиннадцать сторожей из тринадцати оказались мёртвыми именно
/// потому, что их не проверяли на срабатывание. Ниже — доказательство обоих исходов.
///
/// `#[cfg(test)]` - вызывается только из тестовых модулей ниже; в production-сборке сверку
/// суммы делает `tools/sync_trial_terms.py` до упаковки, а не рантайм программы.
#[cfg(test)]
fn verify_pdf_matches_manifest(
    pdf_bytes: &[u8],
    manifest_json: &str,
    doc_key: &str,
    human_name: &str,
) -> Result<(), String> {
    use sha2::{Digest, Sha256};

    let manifest: serde_json::Value = serde_json::from_str(manifest_json)
        .map_err(|e| format!("манифест trial_terms_manifest.json не разобрался: {e}"))?;

    let doc = manifest.get("documents").and_then(|d| d.get(doc_key));

    let expected = match doc.and_then(|d| d.get("sha256")).and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s,
        _ => {
            let status = doc
                .and_then(|d| d.get("status"))
                .and_then(|v| v.as_str())
                .unwrap_or("сумма PDF в манифесте не задана");
            return Err(format!(
                "манифест trial_terms_manifest.json ещё не заполнен для документа \
                 «{human_name}» (ключ {doc_key}): {status}"
            ));
        }
    };
    let expected_revision = doc
        .and_then(|d| d.get("revision"))
        .and_then(|v| v.as_str())
        .unwrap_or("?");

    let mut hasher = Sha256::new();
    hasher.update(pdf_bytes);
    let actual = format!("{:x}", hasher.finalize());

    if actual != expected {
        return Err(format!(
            "PDF документа «{human_name}» не совпадает с эталоном манифеста (ожидалась \
             редакция {expected_revision}, сумма {expected}): у файла в поставке сумма \
             {actual} — доставлена НЕ та редакция, файл повреждён при переносе, либо \
             манифест устарел (перезапустите tools/sync_trial_terms.py)"
        ));
    }
    Ok(())
}

/// Юнит-тесты логики сверки — на синтетических байтах, без реального документа: доказывают,
/// что механизм действительно способен покраснеть, не дожидаясь того, придёт ли когда-нибудь
/// правовой PDF. Ось мутации у каждого теста — сделать сверку тождественной, независимо от
/// входа (например, вернуть `Ok(())` безусловно) — красит противоположный тест.
#[cfg(test)]
mod trial_terms_manifest_guard_logic {
    use super::verify_pdf_matches_manifest;

    #[test]
    fn matches_when_hash_equals_manifest() {
        use sha2::{Digest, Sha256};
        let bytes: &[u8] = "условная замена содержимого документа для юнит-теста".as_bytes();
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        let hash = format!("{:x}", hasher.finalize());
        let manifest =
            format!(r#"{{"documents":{{"terms":{{"revision":"2026-09-14","sha256":"{hash}"}}}}}}"#);
        assert!(verify_pdf_matches_manifest(bytes, &manifest, "terms", "Условия").is_ok());
    }

    /// 🔴 Доказательство красного: заведомо неверная сумма ОБЯЗАНА провалить проверку, а
    /// сообщение — назвать документ, ожидаемую редакцию и то, что суммы разошлись (не
    /// абстрактное "тест упал").
    #[test]
    fn fails_loudly_when_hash_does_not_match() {
        let bytes: &[u8] = "то, что реально лежит в поставке".as_bytes();
        let manifest = r#"{"documents":{"terms":{"revision":"2026-09-14","sha256":"0000000000000000000000000000000000000000000000000000000000000000"}}}"#;
        let err = verify_pdf_matches_manifest(bytes, manifest, "terms", "Условия").unwrap_err();
        assert!(err.contains("не совпадает"), "сообщение обязано объяснять причину: {err}");
        assert!(err.contains("2026-09-14"), "сообщение обязано называть ожидаемую редакцию: {err}");
        assert!(err.contains("Условия"), "сообщение обязано называть, какой документ разошёлся: {err}");
    }

    #[test]
    fn fails_loudly_on_malformed_manifest() {
        let err = verify_pdf_matches_manifest(b"whatever", "not json", "terms", "Условия").unwrap_err();
        assert!(err.contains("не разобрался"), "сообщение обязано называть причину: {err}");
    }

    /// Манифест ещё не заполнен реальной суммой для документа (например, поле pending) —
    /// сообщение обязано это объяснять и называть документ, а не молча падать на разборе типа.
    #[test]
    fn fails_loudly_when_manifest_pending() {
        let manifest = r#"{"documents":{"data_processing":{"revision":"2026-09-14","sha256":null,"status":"PENDING - проверка на ПДн"}}}"#;
        let err = verify_pdf_matches_manifest(b"anything", manifest, "data_processing", "Порядок обработки данных").unwrap_err();
        assert!(err.contains("PENDING"), "сообщение обязано процитировать причину ожидания: {err}");
        assert!(err.contains("Порядок обработки данных"), "сообщение обязано называть документ: {err}");
    }

    /// Ключ документа отсутствует в `documents` вовсе (второй документ не добавлен в
    /// манифест) — обязан провалиться с понятным сообщением, а не запаниковать на None.
    #[test]
    fn fails_loudly_when_doc_key_missing() {
        let manifest = r#"{"documents":{"terms":{"revision":"2026-09-14","sha256":"aa"}}}"#;
        let err = verify_pdf_matches_manifest(b"anything", manifest, "data_processing", "Порядок обработки данных").unwrap_err();
        assert!(
            err.contains("Порядок обработки данных") && err.contains("data_processing"),
            "сообщение обязано называть отсутствующий документ и его ключ: {err}"
        );
    }
}

/// 🔴 Сторож поставки (s48, 2026-09-14): ОБА правовых PDF обязаны ФИЗИЧЕСКИ лежать там,
/// откуда их возьмёт установщик (`src-tauri/help-econometrica/`, целиком включена в
/// `bundle.resources` как `"help-econometrica/*"` в `tauri.conf.json`), И их суммы обязаны
/// совпадать с эталоном в `tools/trial_terms_manifest.json` — а не просто числиться строкой
/// в конфигурации и не просто существовать (устаревшая или повреждённая копия тоже физически
/// существует). Второй документ («Порядок обработки данных») добавлен по требованию
/// правового блока (Business/Projects/СИГНАЛ_сессиям_правовой_комплект_2026-09-14.md) — без
/// него пункты 6.2/6.5/6.8 «Условий» ведут в пустоту, поэтому его отсутствие валит поставку
/// точно так же, как отсутствие «Условий».
///
/// Манифест обновляется ТОЛЬКО через `tools/sync_trial_terms.py` — вручную сумму в него не
/// подставлять (см. этот файл: обе суммы считает скрипт, а не рука).
#[cfg(test)]
mod trial_terms_delivery_guard {
    use super::{
        verify_pdf_matches_manifest, DATA_PROCESSING_MANIFEST_KEY, DATA_PROCESSING_PDF_FILENAME,
        TRIAL_TERMS_MANIFEST_KEY, TRIAL_TERMS_PDF_FILENAME, TRIAL_TERMS_REVISION,
    };
    use std::path::Path;

    const MANIFEST_JSON: &str = include_str!("../../../tools/trial_terms_manifest.json");

    /// Общая проверка одного документа поставки: файл физически на диске бандла + сумма
    /// совпадает с манифестом. Вызывается для каждого из двух документов ниже — так падение
    /// одного не маскирует и не подменяет падение другого (два отдельных теста, а не один
    /// цикл с общим `assert`, чтобы `cargo test` печатал имя провалившегося документа).
    fn check_delivered_document(filename: &str, doc_key: &str, human_name: &str) {
        let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        let pdf_path = manifest_dir.join("help-econometrica").join(filename);
        let bytes = match std::fs::read(&pdf_path) {
            Ok(b) => b,
            Err(_) => panic!(
                "PDF документа «{human_name}» отсутствует в {} - поставка НЕ готова \
                 (запустите tools/sync_trial_terms.py; см. Projects/PULSE_s48_docsblock.md)",
                pdf_path.display()
            ),
        };
        if let Err(e) = verify_pdf_matches_manifest(&bytes, MANIFEST_JSON, doc_key, human_name) {
            panic!("{e}");
        }
    }

    #[test]
    fn trial_terms_pdf_matches_manifest_hash() {
        check_delivered_document(
            TRIAL_TERMS_PDF_FILENAME,
            TRIAL_TERMS_MANIFEST_KEY,
            "Условия ознакомительного использования",
        );
    }

    #[test]
    fn data_processing_pdf_matches_manifest_hash() {
        check_delivered_document(
            DATA_PROCESSING_PDF_FILENAME,
            DATA_PROCESSING_MANIFEST_KEY,
            "Порядок обработки данных",
        );
    }

    /// Вспомогательный к тесту выше: конфигурация обязана продолжать включать
    /// `help-econometrica/*` целиком в ресурсы поставки — иначе даже присланный PDF
    /// не попадёт к клиенту. Проверка строки в конфиге ДОПОЛНЯЕТ проверку суммы выше,
    /// а не заменяет её.
    #[test]
    fn tauri_conf_bundles_help_econometrica_directory() {
        const TAURI_CONF: &str = include_str!("../../tauri.conf.json");
        assert!(
            TAURI_CONF.contains("\"help-econometrica/*\""),
            "tauri.conf.json больше не включает help-econometrica/* в ресурсы поставки"
        );
    }

    /// Имена файлов в `tools/sync_trial_terms.py` обязаны дословно совпадать с
    /// `TRIAL_TERMS_PDF_FILENAME`/`DATA_PROCESSING_PDF_FILENAME` — иначе воспроизводимый
    /// перенос кладёт файл под ДРУГИМ именем, и открытие документа из настроек
    /// (`open_trial_terms`/`open_data_processing_terms`) его не найдёт.
    #[test]
    fn sync_script_filename_matches_rust_constant() {
        const SYNC_SCRIPT: &str = include_str!("../../../tools/sync_trial_terms.py");
        assert!(
            SYNC_SCRIPT.contains(TRIAL_TERMS_PDF_FILENAME),
            "имя файла условий в tools/sync_trial_terms.py разошлось с TRIAL_TERMS_PDF_FILENAME"
        );
        assert!(
            SYNC_SCRIPT.contains(DATA_PROCESSING_PDF_FILENAME),
            "имя файла порядка обработки данных в tools/sync_trial_terms.py разошлось с \
             DATA_PROCESSING_PDF_FILENAME"
        );
    }

    /// Редакция дублируется буквально В ТРЁХ местах (Rust-константа ниже — источник истины
    /// для логики согласия; текст чекбокса `TrialConsentOverlay.svelte` — юридически
    /// согласованный текст, дата в нём не может «просто ссылаться» на константу; поле
    /// `revision` в `tools/sync_trial_terms.py`, попадающее в манифест исключительно для
    /// человекочитаемого сообщения об ошибке, а не для самой сверки — её делает сумма).
    /// Каждая копия под своим сторожем: эта - за python-скрипт, `trial_terms_revision_
    /// matches_frontend_checkbox_text` выше - за фронтенд. Обе читают ОДНУ и ту же
    /// `TRIAL_TERMS_REVISION` - бампить редакцию нужно в трёх местах, но забыть одно из них
    /// незамеченным нельзя: тест покраснеет.
    #[test]
    fn sync_script_revision_matches_rust_constant() {
        const SYNC_SCRIPT: &str = include_str!("../../../tools/sync_trial_terms.py");
        assert!(
            SYNC_SCRIPT.contains(&format!("\"{TRIAL_TERMS_REVISION}\"")),
            "редакция в tools/sync_trial_terms.py (TRIAL_TERMS_REVISION) разошлась с \
             user_config.rs::TRIAL_TERMS_REVISION = {TRIAL_TERMS_REVISION} - сообщения об \
             ошибке сторожа поставки будут называть неверную редакцию"
        );
    }
}
