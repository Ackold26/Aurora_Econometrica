use anyhow::{Context, Result};
use log::{debug, info, warn};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatHistoryMessage {
    pub role: String,
    pub content: String,
    pub ts: f64,
}

fn history_dir() -> Result<PathBuf> {
    let local_app_data = std::env::var("LOCALAPPDATA")
        .unwrap_or_else(|_| "C:\\Users\\Default\\AppData\\Local".to_string());
    let dir = PathBuf::from(&local_app_data)
        .join("AIAgency")
        .join("history");
    std::fs::create_dir_all(&dir).context("Failed to create history directory")?;
    Ok(dir)
}

fn history_path(cabinet_id: &str) -> Result<PathBuf> {
    // Sanitize cabinet_id to prevent path traversal
    let safe_id = cabinet_id.replace(|c: char| !c.is_alphanumeric() && c != '-' && c != '_', "");
    Ok(history_dir()?.join(format!("{}.json", safe_id)))
}

pub fn save_message(cabinet_id: &str, msg: ChatHistoryMessage) -> Result<()> {
    let path = history_path(cabinet_id)?;
    let mut messages = load_history_inner(&path);
    messages.push(msg);

    // Cap history at 500 messages per cabinet
    if messages.len() > 500 {
        messages = messages.split_off(messages.len() - 500);
    }

    let json = serde_json::to_string_pretty(&messages)?;
    std::fs::write(&path, json).context("Failed to write history")?;
    debug!("Saved history for {cabinet_id}: {} messages", messages.len());
    Ok(())
}

pub fn load_history(cabinet_id: &str) -> Result<Vec<ChatHistoryMessage>> {
    let path = history_path(cabinet_id)?;
    Ok(load_history_inner(&path))
}

fn load_history_inner(path: &PathBuf) -> Vec<ChatHistoryMessage> {
    if !path.exists() {
        return vec![];
    }
    match std::fs::read_to_string(path) {
        Ok(content) => {
            serde_json::from_str(&content).unwrap_or_else(|e| {
                warn!("Failed to parse history file: {e}");
                vec![]
            })
        }
        Err(e) => {
            warn!("Failed to read history file: {e}");
            vec![]
        }
    }
}

pub fn clear_history(cabinet_id: &str) -> Result<()> {
    let path = history_path(cabinet_id)?;
    if path.exists() {
        std::fs::remove_file(&path).context("Failed to delete history file")?;
        info!("Cleared history for {cabinet_id}");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn session_history_format() {
        let msg = ChatHistoryMessage {
            role: "user".to_string(),
            content: "Hello, world!".to_string(),
            ts: 1711360000.0,
        };

        let json = serde_json::to_string(&msg).expect("serialize failed");
        let parsed: serde_json::Value = serde_json::from_str(&json).expect("parse failed");

        assert!(parsed.get("role").is_some(), "field 'role' must be present");
        assert!(parsed.get("content").is_some(), "field 'content' must be present");
        assert!(parsed.get("ts").is_some(), "field 'ts' must be present");

        assert_eq!(parsed["role"].as_str().unwrap(), "user");
        assert_eq!(parsed["content"].as_str().unwrap(), "Hello, world!");
        assert!((parsed["ts"].as_f64().unwrap() - 1711360000.0).abs() < f64::EPSILON);
    }
}
