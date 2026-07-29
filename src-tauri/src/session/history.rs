use anyhow::{Context, Result};
use log::{debug, info};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// 🔴 Внешний аудит 2026-07-29 (High): сериализует конкурентные `save_message` — без этого два
/// одновременных сохранения одного кабинета (стриминг ответа + реплика пользователя) читают одно
/// и то же N сообщений и оба пишут N+1 — одно сообщение молча теряется (классическая гонка
/// read-modify-write). Образец — Aurora Creative Hub (`session/history.rs::WRITE_LOCK`).
static WRITE_LOCK: std::sync::LazyLock<std::sync::Mutex<()>> =
    std::sync::LazyLock::new(|| std::sync::Mutex::new(()));

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
    // CPD-30: per-app каталог с одноразовым переносом legacy AIAgency\history — см. durable_store.
    crate::durable_store::app_state_dir("history")
}

fn history_path(cabinet_id: &str) -> Result<PathBuf> {
    // Sanitize cabinet_id to prevent path traversal
    let safe_id = cabinet_id.replace(|c: char| !c.is_alphanumeric() && c != '-' && c != '_', "");
    Ok(history_dir()?.join(format!("{}.json", safe_id)))
}

pub fn save_message(cabinet_id: &str, msg: ChatHistoryMessage) -> Result<()> {
    let path = history_path(cabinet_id)?;
    save_message_at(&path, msg)
}

/// Ядро сохранения — тестируемое явным путём, без обращения к per-app каталогу/BASE_DIR
/// (по образцу `durable_store::migrate_into`: логика отделена от резолва реального пути,
/// чтобы тест не мог случайно задеть живой `%LOCALAPPDATA%`). `save_message` (выше) — единственный
/// вызывающий с реальным путём через `history_path`.
fn save_message_at(path: &Path, msg: ChatHistoryMessage) -> Result<()> {
    // 🔴 Внешний аудит 2026-07-29 (High): держим лок на ВЕСЬ цикл чтение→изменение→запись —
    // иначе два одновременных вызова читают одну и ту же историю и оба пишут поверх друг друга.
    let _guard = WRITE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let mut messages = load_history_inner(path);
    messages.push(msg);

    // Cap history at 500 messages per cabinet
    if messages.len() > 500 {
        messages = messages.split_off(messages.len() - 500);
    }

    let json = serde_json::to_string_pretty(&messages)?;
    // 🔴 Внешний аудит 2026-07-29 (High): атомарная запись (tmp + rename) — см. durable_store
    // (донор): прямая запись при обрыве процесса оставляла усечённый JSON.
    crate::durable_store::write_atomic(path, json.as_bytes()).context("Failed to write history")?;
    debug!("Saved history at {}: {} messages", path.display(), messages.len());
    Ok(())
}

pub fn load_history(cabinet_id: &str) -> Result<Vec<ChatHistoryMessage>> {
    let path = history_path(cabinet_id)?;
    Ok(load_history_inner(&path))
}

fn load_history_inner(path: &Path) -> Vec<ChatHistoryMessage> {
    // 🔴 Внешний аудит 2026-07-29 (High): битый JSON уходит в карантин `.corrupt.bak`, а не
    // подменяется молча пустым списком — см. durable_store::read_json_or_quarantine (донор).
    crate::durable_store::read_json_or_quarantine(path).unwrap_or_default()
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

    /// 🔴 Внешний аудит 2026-07-29 (High), бюллет 1: битый файл истории уходит в карантин
    /// `.corrupt.bak`, а не подменяется молча пустым списком. `load_history_inner` по-прежнему
    /// отдаёт `vec![]` (показывать в интерфейсе битые байты нечем), но исходный файл при этом
    /// НЕ остаётся на месте молча — он уводится в сторону с warn-логом, и следующее сохранение
    /// пишет НОВЫЙ файл, а не затирает нечитаемый оригинал.
    #[test]
    fn corrupt_history_file_is_quarantined_not_silently_emptied() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("broken-cabinet.json");
        let garbage = "{битый json, не список сообщений клиента";
        std::fs::write(&path, garbage).unwrap();

        let messages = load_history_inner(&path);
        assert!(messages.is_empty(), "битый файл не парсится ни во что осмысленное");
        assert!(!path.exists(), "битый файл обязан уйти из исходного места в карантин");
        assert!(path.with_extension("corrupt.bak").exists(), "карантинная копия обязана существовать");
    }

    /// 🔴 Внешний аудит 2026-07-29 (High), бюллет 2: после карантина исходное содержимое битого
    /// файла истории сохранено дословно — данные клиента не уничтожены, их можно восстановить
    /// вручную из `.corrupt.bak`.
    #[test]
    fn quarantined_history_file_preserves_original_content() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("broken-cabinet-2.json");
        let garbage = "{ещё один битый файл истории, тут была переписка клиента";
        std::fs::write(&path, garbage).unwrap();

        let _ = load_history_inner(&path);

        assert_eq!(
            std::fs::read_to_string(path.with_extension("corrupt.bak")).unwrap(),
            garbage,
            "карантинная копия обязана содержать ИСХОДНЫЕ байты без искажения"
        );
    }

    /// 🔴 Внешний аудит 2026-07-29 (High), пункт 3 задачи: `save_message` без WRITE_LOCK — это
    /// read-modify-write без сериализации: два одновременных сохранения читают одно и то же N
    /// сообщений и оба пишут N+1, одно теряется.
    ///
    /// 🔴 Правка после находки team-lead (2026-07-29): первая версия этого теста гоняла потоки
    /// через ПУБЛИЧНЫЙ `save_message`/`load_history` — те резолвят путь через `history_path` →
    /// `history_dir` → `crate::durable_store::app_state_dir("history")`, а это РЕАЛЬНЫЙ
    /// `%LOCALAPPDATA%` (в тестовом процессе `durable_store::init()` не вызывается, значит
    /// действует боевой фолбэк `local_app_data().join(CARGO_PKG_NAME)`). Тест невольно запускал
    /// настоящую one-shot миграцию legacy→per-app и копировал реальные файлы клиента. Здесь —
    /// только `save_message_at`/`load_history_inner` с явным путём во `tempfile::tempdir()`,
    /// как и `migrate_into`-тесты в durable_store.rs: WRITE_LOCK — тот же самый глобальный
    /// мьютекс (он не зависит от пути), так что защита проверяется без риска задеть профиль.
    #[test]
    fn concurrent_save_message_does_not_lose_writes() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("concurrency-test.json");

        const THREADS: usize = 30;
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(THREADS));
        let handles: Vec<_> = (0..THREADS)
            .map(|i| {
                let barrier = barrier.clone();
                let path = path.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    save_message_at(
                        &path,
                        ChatHistoryMessage {
                            role: "user".to_string(),
                            content: format!("msg-{i}"),
                            ts: i as f64,
                            is_auto_continue: None,
                            is_quick_reply: None,
                        },
                    )
                    .unwrap();
                })
            })
            .collect();
        for h in handles {
            h.join().unwrap();
        }

        let saved = load_history_inner(&path);
        assert_eq!(
            saved.len(), THREADS,
            "конкурентные save_message не должны терять сообщения (гонка read-modify-write без WRITE_LOCK)"
        );
    }
}
