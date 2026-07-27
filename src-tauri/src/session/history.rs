use anyhow::{Context, Result};
use log::{debug, info, warn};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatHistoryMessage {
    pub role: String,
    pub content: String,
    pub ts: f64,
    // Служебные признаки рендера (метка «Авто-продолжение» / компактный quick-reply
    // пузырь на фронте, ChatPanel.svelte). Optional + skip_serializing_if — старые
    // файлы истории (записанные до этого поля) читаются без ошибки: serde(default)
    // подставляет None при отсутствии ключа в JSON; обычные сообщения не разбухают
    // лишним "isAutoContinue":null в файле.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub is_auto_continue: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub is_quick_reply: Option<bool>,
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
            is_auto_continue: None,
            is_quick_reply: None,
        };

        let json = serde_json::to_string(&msg).expect("serialize failed");
        let parsed: serde_json::Value = serde_json::from_str(&json).expect("parse failed");

        assert!(parsed.get("role").is_some(), "field 'role' must be present");
        assert!(parsed.get("content").is_some(), "field 'content' must be present");
        assert!(parsed.get("ts").is_some(), "field 'ts' must be present");
        // Ни isAutoContinue, ни isQuickReply не должны писаться, когда None
        // (skip_serializing_if) — обычные сообщения не разбухают лишними ключами.
        assert!(parsed.get("isAutoContinue").is_none(), "None-поле не должно сериализоваться");
        assert!(parsed.get("isQuickReply").is_none(), "None-поле не должно сериализоваться");

        assert_eq!(parsed["role"].as_str().unwrap(), "user");
        assert_eq!(parsed["content"].as_str().unwrap(), "Hello, world!");
        assert!((parsed["ts"].as_f64().unwrap() - 1711360000.0).abs() < f64::EPSILON);
    }

    #[test]
    fn session_history_flags_roundtrip_camel_case() {
        let msg = ChatHistoryMessage {
            role: "user".to_string(),
            content: "Продолжай.".to_string(),
            ts: 1711360000.0,
            is_auto_continue: Some(true),
            is_quick_reply: None,
        };

        let json = serde_json::to_string(&msg).expect("serialize failed");
        // rename_all = "camelCase" обязан отдать ключ isAutoContinue — ровно то имя,
        // которое читает ChatPanel.svelte (loadHistory) через invoke().
        assert!(json.contains("\"isAutoContinue\":true"), "JSON: {json}");
        assert!(!json.contains("isQuickReply"), "None-поле isQuickReply не должно писаться: {json}");

        let parsed: ChatHistoryMessage = serde_json::from_str(&json).expect("deserialize failed");
        assert_eq!(parsed.is_auto_continue, Some(true));
        assert_eq!(parsed.is_quick_reply, None);
    }

    /// Обратная совместимость (задача 1a): файл истории, записанный ДО того как
    /// появились эти поля, не содержит ключей isAutoContinue/isQuickReply вовсе.
    /// #[serde(default)] обязан подставить None, а не провалить парсинг файла —
    /// иначе вся история кабинета молча пропадала бы при первом же apparте после
    /// обновления (load_history_inner проглатывает serde-ошибку и отдаёт vec![]).
    #[test]
    fn old_format_history_file_without_flags_still_parses() {
        let old_format_json = r#"[
            {"role":"user","content":"Привет","ts":1711360000.0},
            {"role":"assistant","content":"Здравствуйте!","ts":1711360001.0}
        ]"#;

        let parsed: Vec<ChatHistoryMessage> =
            serde_json::from_str(old_format_json).expect("старый формат файла обязан парситься");

        assert_eq!(parsed.len(), 2);
        assert_eq!(parsed[0].role, "user");
        assert_eq!(parsed[0].is_auto_continue, None, "отсутствующий ключ => None, не ошибка парсинга");
        assert_eq!(parsed[0].is_quick_reply, None);
        assert_eq!(parsed[1].content, "Здравствуйте!");
    }

    /// То же самое, но через реальный путь load_history_inner (файл на диске,
    /// не serde_json::from_str напрямую) — гарантия того, что защита от ошибки
    /// парсинга (warn! + vec![]) не срабатывает на старом формате.
    #[test]
    fn old_format_history_file_loads_via_load_history_inner() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("old-cabinet.json");
        std::fs::write(
            &path,
            r#"[{"role":"user","content":"Старое сообщение без флагов","ts":1711360000.0}]"#,
        )
        .unwrap();

        let messages = load_history_inner(&path);
        assert_eq!(messages.len(), 1, "старый файл истории обязан прочитаться, а не превратиться в пустой vec![]");
        assert_eq!(messages[0].content, "Старое сообщение без флагов");
        assert_eq!(messages[0].is_auto_continue, None);
    }
}
