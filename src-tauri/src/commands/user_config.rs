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
