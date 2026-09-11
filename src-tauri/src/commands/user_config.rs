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
pub fn save(config_dir: &Path, config: &UserConfig) -> Result<(), String> {
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
}
