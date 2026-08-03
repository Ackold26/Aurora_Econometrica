use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

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

/// Включён ли пользователем runtime-режим «только локально» (egress отключён).
/// Дефолт false (нет конфига / поле отсутствует → облачный ИИ разрешён, если
/// редакция облачная и согласие дано).
pub fn local_only_enabled(config_dir: &Path) -> bool {
    load(config_dir).local_only
}

fn config_path(config_dir: &Path) -> PathBuf {
    config_dir.join("user_config.json")
}

pub fn load(config_dir: &Path) -> UserConfig {
    let path = config_path(config_dir);
    if !path.exists() {
        return UserConfig::default();
    }
    match std::fs::read_to_string(&path) {
        Ok(data) => serde_json::from_str(&data).unwrap_or_default(),
        Err(_) => UserConfig::default(),
    }
}

pub fn save(config_dir: &Path, config: &UserConfig) -> Result<(), String> {
    let path = config_path(config_dir);
    let _ = std::fs::create_dir_all(config_dir);
    let data = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    std::fs::write(&path, data).map_err(|e| e.to_string())
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
}
