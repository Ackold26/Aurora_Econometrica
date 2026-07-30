use anyhow::{Context, Result};
use log::{debug, info, warn};
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

/// Межпроцессный замок записи истории ждёт ТЕМ ЖЕ циклом, что и всё прочее вокруг файлов
/// состояния: 5 попыток по 100 мс, не дольше полусекунды (`durable_store::STATE_RETRY_*`).
///
/// 🔴 Поправка F-14 внешнего аудита к контракту: изначально контракт назначал 30 × 100 мс =
/// 3 секунды. Зонд показал, что ожидание лежит на пути ИЗ ИНТЕРФЕЙСА — `save_message` вызывается
/// синхронной командой `save_chat_message` (`lib.rs`), возвращающей `Result` фронту. Реальная
/// запись занимает единицы миллисекунд, поэтому три секунды защищали бы от того, чего не бывает,
/// а платил бы за них клиент замершим окном. Константа общая с чтением и заменой файла намеренно:
/// причина ожидания у всех трёх одна — файл ненадолго кем-то занят.
const HISTORY_LOCK_ATTEMPTS: u32 = crate::durable_store::STATE_RETRY_ATTEMPTS;
const HISTORY_LOCK_RETRY: std::time::Duration = crate::durable_store::STATE_RETRY_PAUSE;

/// Путь файла-замка для файла истории: `<каталог истории>/.history-<кабинет>.lock`.
fn history_lock_path(history_path: &Path) -> PathBuf {
    let cabinet = history_stem(history_path);
    history_path.with_file_name(format!(".history-{cabinet}.lock"))
}

/// Взять МЕЖПРОЦЕССНЫЙ замок на цикл «прочитал → добавил → записал».
///
/// 🔴 Батч C (C4, Critical по классу ADR-047): `WRITE_LOCK` — мьютекс внутри процесса, а плагина
/// единственного экземпляра у продукта нет. Два клика по ярлыку = два процесса = два независимых
/// мьютекса: оба читают N сообщений, оба пишут N+1, реплика клиента исчезает без следа. Сценарий
/// не экзотический — продукт восстанавливает последний кабинет при старте, поэтому второе окно
/// само откроет тот же кабинет.
///
/// Приём тот же, что у замка живой сессии (`manager::open_session_lock`, `share_mode(0)`, без
/// внешних зависимостей) — одна реализация монопольного открытия на продукт, чтобы вторая не
/// разошлась с первой. Дескриптор держится до конца записи и освобождается при выходе из области
/// видимости; при падении процесса дескриптор закрывает операционная система.
///
/// 🔴 Не удалось за полсекунды → ОШИБКА, а не запись без замка: потеря одного нового сообщения
/// обратима (клиент видит отказ и повторяет), потеря чужой реплики — нет. Исключение — ответ
/// модели, он платный и дословно не повторяется: см. `park_pending_message`.
fn acquire_history_lock(history_path: &Path) -> Result<std::fs::File> {
    let lock_path = history_lock_path(history_path);
    let mut last_err: Option<std::io::Error> = None;
    for attempt in 0..HISTORY_LOCK_ATTEMPTS {
        match crate::session::manager::open_session_lock(&lock_path) {
            Ok(file) => return Ok(file),
            Err(e) => {
                last_err = Some(e);
                if attempt + 1 < HISTORY_LOCK_ATTEMPTS {
                    std::thread::sleep(HISTORY_LOCK_RETRY);
                }
            }
        }
    }
    let waited = HISTORY_LOCK_RETRY * (HISTORY_LOCK_ATTEMPTS - 1);
    anyhow::bail!(
        "замок {} занят дольше {:.1} с ({})",
        lock_path.display(),
        waited.as_secs_f32(),
        last_err
            .map(|e| e.to_string())
            .unwrap_or_else(|| "причина неизвестна".to_string())
    );
}

/// Роль, потеря которой НЕ обратима.
///
/// 🔴 Поправка F-14 внешнего аудита к контракту: обоснование отказа «клиент видит ошибку и
/// повторит» верно для реплики человека и неверно для ответа модели — он получен платным вызовом
/// и не повторяется ни дёшево, ни дословно. Реплика пользователя и служебные сообщения при занятом
/// замке отклоняются (клиент видит отказ и отправляет заново), ответ модели — откладывается.
fn is_model_answer(msg: &ChatHistoryMessage) -> bool {
    msg.role.eq_ignore_ascii_case("assistant")
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
    // 🔴 Порядок ожидания — поправка F-16 внешнего аудита к контракту. Контракт требовал брать
    // файловый замок ПОД внутрипроцессным мьютексом; тогда ожидание чужого процесса замораживало
    // бы ВСЕ сохранения этого процесса, включая стриминг, на всё время ожидания. Ждём файловый
    // замок СНАРУЖИ, а мьютекс берём на сам цикл чтения-записи. Плата за перестановку известна и
    // принята: два потока одного процесса теперь спорят за файл, а не за мьютекс, — но первая
    // попытка делается без паузы, а сам цикл занимает единицы миллисекунд. Порядок захвата
    // ЕДИНЫЙ во всём продукте (замок → мьютекс), поэтому взаимной блокировки быть не может.
    let file_lock = match acquire_history_lock(path) {
        Ok(lock) => lock,
        Err(e) => return park_or_reject(path, msg, e),
    };
    // 🔴 Внешний аудит 2026-07-29 (High): держим лок на ВЕСЬ цикл чтение→изменение→запись —
    // иначе два одновременных вызова читают одну и ту же историю и оба пишут поверх друг друга.
    let _guard = WRITE_LOCK.lock().unwrap_or_else(|e| e.into_inner());

    // 🔴 Батч C (C1, High): здесь чтение предшествует ЗАПИСИ ТОГО ЖЕ файла, поэтому отказ чтения
    // обязан прервать запись. Прежний `unwrap_or_default()` превращал нечитаемый файл (занят, нет
    // прав) в пустой список, и следующая строка затирала им всю переписку клиента. `Absent` и
    // `Quarantined` — законные пустоты: файла нет либо испорченный уже сохранён в карантине.
    // Повторы (`..._for_update`) — потому что отказ чтения чаще всего мгновенный и проходящий:
    // файл на миг держит индексатор, антивирус или второе окно.
    let mut messages: Vec<ChatHistoryMessage> = crate::durable_store::load_json_for_update(path)?
        .into_value()
        .unwrap_or_default();
    // Отложенные ответы модели (см. `park_pending_message`) возвращаются в историю при первом же
    // удавшемся сохранении — иначе они остались бы лежать отдельными файлами навсегда.
    let picked_up = merge_pending(path, &mut messages);
    messages.push(msg);

    // Cap history at 500 messages per cabinet
    if messages.len() > 500 {
        messages = messages.split_off(messages.len() - 500);
    }

    let json = serde_json::to_string_pretty(&messages)?;
    // 🔴 Внешний аудит 2026-07-29 (High): атомарная запись (tmp + rename) — см. durable_store
    // (донор): прямая запись при обрыве процесса оставляла усечённый JSON.
    crate::durable_store::write_atomic(path, json.as_bytes()).context("Failed to write history")?;

    // Отложенные файлы убираются ТОЛЬКО после успешной записи: упади она — они останутся на
    // диске и будут подобраны следующей попыткой.
    for pending in picked_up {
        if let Err(e) = std::fs::remove_file(&pending) {
            warn!("Отложенный ответ учтён, но файл {} не удалён: {e}", pending.display());
        }
    }
    debug!("Saved history at {}: {} messages", path.display(), messages.len());
    drop(file_lock);
    Ok(())
}

/// Замок не взят: ответ модели откладываем в запасной файл, всё остальное — отклоняем.
fn park_or_reject(path: &Path, msg: ChatHistoryMessage, cause: anyhow::Error) -> Result<()> {
    if !is_model_answer(&msg) {
        return Err(cause.context(
            "сообщение не сохранено — повторите отправку; запись без замка уничтожила бы \
             сообщения другого окна",
        ));
    }
    let parked = park_pending_message(path, &msg).context(
        "ответ модели не удалось ни сохранить в историю, ни отложить — он будет потерян",
    )?;
    warn!(
        "Замок истории занят ({cause:#}); ответ модели отложен в {} и вернётся в историю при \
         следующем удавшемся сохранении",
        parked.display()
    );
    Ok(())
}

/// Отложить ответ модели рядом с историей: `<кабинет>.pending-<отметка>.json`.
///
/// 🔴 Поправка F-14 внешнего аудита к контракту. Ответ модели оплачен вызовом и дословно не
/// воспроизводится, поэтому отказывать по нему нельзя — но и писать его в историю без замка
/// нельзя тем более (это уничтожило бы сообщения другого окна). Отдельный файл разрешает
/// противоречие: он никому не мешает, его подхватывает первое же удавшееся сохранение
/// (`merge_pending`), а до тех пор его показывает чтение истории.
fn park_pending_message(history_path: &Path, msg: &ChatHistoryMessage) -> Result<PathBuf> {
    let stem = history_stem(history_path);
    let stamp = chrono::Local::now().format("%Y%m%d-%H%M%S%3f");
    let mut target = history_path.with_file_name(format!("{stem}.pending-{stamp}.json"));
    let mut n = 1u32;
    while target.exists() {
        target = history_path.with_file_name(format!("{stem}.pending-{stamp}-{n}.json"));
        n += 1;
    }
    let json = serde_json::to_string_pretty(msg)?;
    crate::durable_store::write_atomic(&target, json.as_bytes())
        .with_context(|| format!("не отложить ответ модели в {}", target.display()))?;
    Ok(target)
}

fn history_stem(history_path: &Path) -> String {
    history_path
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "cabinet".to_string())
}

/// Отложенные ответы модели того же кабинета, лежащие рядом с историей.
fn pending_files(history_path: &Path) -> Vec<PathBuf> {
    let Some(dir) = history_path.parent() else {
        return vec![];
    };
    let prefix = format!("{}.pending-", history_stem(history_path));
    let read_dir = match std::fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(_) => return vec![],
    };
    let mut found: Vec<PathBuf> = read_dir
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.is_file()
                && p.file_name()
                    .and_then(|n| n.to_str())
                    .map_or(false, |n| n.starts_with(&prefix) && n.ends_with(".json"))
        })
        .collect();
    found.sort();
    found
}

/// Добавить отложенные ответы модели в список сообщений по возрастанию отметки времени.
/// Возвращает файлы, которые были учтены: удаляет их ТОЛЬКО путь записи и ТОЛЬКО после успешного
/// сохранения. Нечитаемый отложенный файл не удаляется и не роняет чтение — о нём пишется warn.
fn merge_pending(history_path: &Path, messages: &mut Vec<ChatHistoryMessage>) -> Vec<PathBuf> {
    let mut picked: Vec<(PathBuf, ChatHistoryMessage)> = vec![];
    for file in pending_files(history_path) {
        match std::fs::read_to_string(&file)
            .ok()
            .and_then(|c| serde_json::from_str::<ChatHistoryMessage>(&c).ok())
        {
            Some(msg) => picked.push((file, msg)),
            None => warn!(
                "Отложенный ответ {} не прочитан — оставляю файл на диске, чтобы не потерять его \
                 содержимое",
                file.display()
            ),
        }
    }
    picked.sort_by(|a, b| a.1.ts.partial_cmp(&b.1.ts).unwrap_or(std::cmp::Ordering::Equal));
    let files = picked.iter().map(|(p, _)| p.clone()).collect();
    messages.extend(picked.into_iter().map(|(_, m)| m));
    files
}

/// Чтение истории ДЛЯ ПОКАЗА (экран кабинета). За ним записи того же файла не следует, поэтому
/// отказ чтения не прерывает открытие кабинета: пишем warn и показываем пусто. Молчаливой потери
/// при этом не возникает — сохранение идёт только через `save_message_at`, а он на отказе чтения
/// прерывается и ничего не затирает.
pub fn load_history(cabinet_id: &str) -> Result<Vec<ChatHistoryMessage>> {
    let path = history_path(cabinet_id)?;
    Ok(load_history_for_display(&path))
}

/// Чтение для показа: отказ не роняет экран, отложенные ответы модели видны наравне с историей.
/// Повторов здесь нет намеренно (за отказом не следует запись), а отложенные файлы НЕ удаляются —
/// замка мы не держим, и убирать их вправе только путь записи.
fn load_history_for_display(path: &Path) -> Vec<ChatHistoryMessage> {
    let mut messages = load_history_inner(path).unwrap_or_else(|e| {
        warn!(
            "История {} не прочитана, показываю пусто (файл НЕ тронут): {e:#}",
            path.display()
        );
        Vec::new()
    });
    let _ = merge_pending(path, &mut messages);
    messages
}

/// СТРОГОЕ чтение истории: отказ чтения возвращается ошибкой, а не пустым списком.
/// Развести по смыслу нужно было не саму функцию, а её вызовы — она служит и записи, и показу.
fn load_history_inner(path: &Path) -> Result<Vec<ChatHistoryMessage>> {
    // 🔴 Внешний аудит 2026-07-29 (High): битый JSON уходит в карантин, а не подменяется молча
    // пустым списком. 🔴 Батч C (C1): отказ ЧТЕНИЯ больше не приравнивается к пустоте — он
    // возвращается ошибкой, и вызывающий решает, прервать запись или показать пусто.
    Ok(crate::durable_store::load_json(path)?.into_value().unwrap_or_default())
}

pub fn clear_history(cabinet_id: &str) -> Result<()> {
    let path = history_path(cabinet_id)?;
    clear_history_at(&path)?;
    info!("Cleared history for {cabinet_id}");
    Ok(())
}

/// Ядро очистки под явным путём: сам файл истории И карантинные копии того же кабинета.
///
/// 🔴 Батч C (C8, Medium): очистка удаляла только `<кабинет>.json`, а карантинная копия с ПОЛНОЙ
/// перепиской оставалась на диске бессрочно — при том, что продукт сообщал об успешной очистке.
/// Удаление затирающее: это данные клиента, тем же способом, что и закрытие кабинета
/// (`manager::secure_delete_file`).
fn clear_history_at(path: &Path) -> Result<()> {
    if path.exists() {
        crate::session::manager::secure_delete_file(path).context("Failed to delete history file")?;
    }
    for bak in crate::durable_store::quarantine_copies_of(path) {
        match crate::session::manager::secure_delete_file(&bak) {
            Ok(_) => info!("Карантинная копия истории удалена: {}", bak.display()),
            // Одна неудача не отменяет остальные: занятый индексатором файл виден в журнале,
            // а не теряется молча вместе с обещанием «история очищена».
            Err(e) => warn!("Не удалена карантинная копия {}: {e}", bak.display()),
        }
    }
    // Тот же довод, что и для карантина: отложенный ответ модели — переписка клиента, и после
    // «очистить историю» он не имеет права остаться на диске.
    for pending in pending_files(path) {
        match crate::session::manager::secure_delete_file(&pending) {
            Ok(_) => info!("Отложенный ответ удалён вместе с историей: {}", pending.display()),
            Err(e) => warn!("Не удалён отложенный ответ {}: {e}", pending.display()),
        }
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

        let messages =
            load_history_inner(&path).expect("исправный файл истории читается без ошибки");
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

        let messages = load_history_inner(&path)
            .expect("битый JSON — это порча (карантин), а не отказ чтения");
        assert!(messages.is_empty(), "битый файл не парсится ни во что осмысленное");
        assert!(!path.exists(), "битый файл обязан уйти из исходного места в карантин");
        // 🔴 Правка батча C (C7): имя карантинной копии несёт отметку времени, поэтому
        // проверяется наличие копии, а не фиксированный путь `<имя>.corrupt.bak`.
        assert_eq!(
            crate::durable_store::quarantine_copies_of(&path).len(),
            1,
            "карантинная копия обязана существовать"
        );
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

        let copies = crate::durable_store::quarantine_copies_of(&path);
        assert_eq!(copies.len(), 1, "карантинная копия обязана быть ровно одна: {copies:?}");
        assert_eq!(
            std::fs::read_to_string(&copies[0]).unwrap(),
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
    ///
    /// 🔴 Правка батча C (2026-07-30), причина названа полностью — это НАХОДКА тиража, а не
    /// подгонка теста под код. С появлением межпроцессного замка (C4) и принятым порядком
    /// «замок СНАРУЖИ мьютекса» (поправка F-16) тридцать потоков ОДНОГО процесса конкурируют за
    /// файл, а не выстраиваются в очередь на мьютексе — ровно та плата, которую поправка F-16
    /// назвала известной и приняла. Бюджет ожидания при этом 5 × 100 мс, и при залповом старте
    /// 30 потоков часть из них его исчерпывает: прогон падал 3 раза из 3, потеряв ~10 записей.
    /// Это НЕ потеря данных — исчерпавший бюджет получает ЯВНУЮ ошибку «сообщение не сохранено,
    /// повторите отправку», то есть новый контракт соблюдён. В продукте залпа не бывает: пишут
    /// стриминг ответа и реплика клиента, то есть два сохранения, а не тридцать.
    ///
    /// Поэтому тест приведён к тому, что теперь является инвариантом: НИ ОДНО принятое сообщение
    /// не теряется, а отказ виден и повторяем — поток ведёт себя как фронт, повторяя отправку.
    /// Прежняя формулировка («тридцать одновременных сохранений обязаны пройти с первого раза»)
    /// отменена намеренно: с межпроцессным замком она требовала бы бюджета ожидания в секунды,
    /// а он лежит на пути из интерфейса и был сознательно урезан до полусекунды.
    ///
    /// 🔴 Второе следствие, тоже названное честно: после C4 этот тест больше НЕ является сторожем
    /// самого `WRITE_LOCK` — файловый замок сериализует тот же цикл и в пределах процесса, так
    /// что снятие мьютекса поведения не меняет. Мьютекс оставлен по требованию контракта (он
    /// дешевле файлового и снимает основную долю конкуренции), но доказательства мутацией у него
    /// теперь нет, и делать вид, что есть, нельзя.
    #[test]
    fn concurrent_save_message_does_not_lose_writes() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("concurrency-test.json");

        const THREADS: usize = 30;
        /// Сколько раз поток повторяет отправку, получив отказ по занятому замку. Фронт делает то
        /// же самое руками клиента; здесь повтор автоматический, чтобы тест не зависел от удачи.
        const RETRIES: usize = 40;

        let barrier = std::sync::Arc::new(std::sync::Barrier::new(THREADS));
        let handles: Vec<_> = (0..THREADS)
            .map(|i| {
                let barrier = barrier.clone();
                let path = path.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    let mut last: Option<String> = None;
                    for _ in 0..RETRIES {
                        match save_message_at(
                            &path,
                            ChatHistoryMessage {
                                role: "user".to_string(),
                                content: format!("msg-{i}"),
                                ts: i as f64,
                                is_auto_continue: None,
                                is_quick_reply: None,
                            },
                        ) {
                            Ok(()) => return,
                            Err(e) => last = Some(format!("{e:#}")),
                        }
                    }
                    panic!(
                        "сообщение msg-{i} не сохранено за {RETRIES} повторов — замок не \
                         освобождается вовсе, это уже не конкуренция: {}",
                        last.unwrap_or_default()
                    );
                })
            })
            .collect();
        for h in handles {
            h.join().unwrap();
        }

        let saved = load_history_inner(&path).expect("после конкурентных записей файл читается");
        assert_eq!(
            saved.len(),
            THREADS,
            "конкурентные сохранения не должны терять сообщения: каждое либо записано, либо \
             отклонено с ошибкой и повторено — молча пропасть не имеет права"
        );
        let mut seen: Vec<&str> = saved.iter().map(|m| m.content.as_str()).collect();
        seen.sort();
        seen.dedup();
        assert_eq!(
            seen.len(),
            THREADS,
            "каждое из {THREADS} сообщений обязано попасть в историю РОВНО один раз — повтор \
             после отказа не имеет права породить дубль"
        );
    }

    // ── Батч C (2026-07-30): межпроцессный замок записи + отказ чтения прерывает запись.

    fn msg(content: &str) -> ChatHistoryMessage {
        ChatHistoryMessage {
            role: "user".to_string(),
            content: content.to_string(),
            ts: 1711360000.0,
            is_auto_continue: None,
            is_quick_reply: None,
        }
    }

    fn answer(content: &str, ts: f64) -> ChatHistoryMessage {
        ChatHistoryMessage {
            role: "assistant".to_string(),
            content: content.to_string(),
            ts,
            is_auto_continue: None,
            is_quick_reply: None,
        }
    }

    /// 🔴 Сторож C1 №3 (негативный контроль) на реальном пути записи: истории нет → она
    /// создаётся из одного сообщения. Без этого случая «отказ прерывает запись» можно было бы
    /// удовлетворить, отказываясь всегда.
    #[test]
    fn save_message_at_creates_history_when_file_is_absent() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("econometrist.json");

        save_message_at(&path, msg("первое сообщение")).unwrap();

        let saved = load_history_inner(&path).unwrap();
        assert_eq!(saved.len(), 1, "запись на пустом месте обязана создать историю из одного сообщения");
        assert_eq!(saved[0].content, "первое сообщение");
    }

    /// 🔴 Сторож C1 №2 на реальном пути записи: файл истории занят монопольно (так его держит
    /// живой процесс), значит прочитать его нельзя — и запись ОБЯЗАНА прерваться. Прежний
    /// `unwrap_or_default()` в этом месте превращал отказ чтения в пустой список, и следующая
    /// строка затирала им всю переписку клиента.
    #[cfg(windows)]
    #[test]
    fn save_message_at_refuses_to_write_when_history_cannot_be_read() {
        use std::os::windows::fs::OpenOptionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("econometrist.json");
        let original = r#"[{"role":"user","content":"переписка клиента","ts":1711360000.0}]"#;
        std::fs::write(&path, original).unwrap();

        let held = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(0)
            .open(&path)
            .unwrap();

        let outcome = save_message_at(&path, msg("новое сообщение"));

        let err = outcome.expect_err(
            "нечитаемый файл истории обязан прервать запись: пустой список поверх него уничтожил \
             бы всю переписку клиента",
        );
        // 🔴 Отказ обязан прийти именно с ЧТЕНИЯ. Проверка не косметическая: без неё тест остаётся
        // зелёным и когда чтение молча вернуло пустоту — запись всё равно упадёт, просто позже, на
        // переименовании в занятый файл. Тогда сторож охранял бы целость файла, но НЕ развилку
        // «отказ чтения ≠ пустота», ради которой он написан.
        assert!(
            format!("{err:#}").contains("прочитать"),
            "запись обязана быть прервана отказом ЧТЕНИЯ, а не спотыкнуться позже о занятый файл: \
             {err:#}"
        );
        drop(held);
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            original,
            "файл истории обязан остаться нетронутым — ни записи, ни переноса в карантин"
        );
    }

    /// 🔴 Сторож C4: замок истории занят ДРУГИМ владельцем (второе окно продукта) — запись
    /// возвращает ошибку и файл истории НЕ изменён. Замок берётся из того же процесса другим
    /// дескриптором: для `share_mode(0)` это неотличимо от чужого процесса.
    /// Тест намеренно ждёт полный цикл повторов — он проверяет не только отказ, но и то, что
    /// отказ наступает по исчерпании попыток, а не мгновенно.
    #[cfg(windows)]
    #[test]
    fn save_message_at_refuses_when_history_lock_is_held_by_another_owner() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("econometrist.json");
        save_message_at(&path, msg("первое сообщение")).unwrap();
        let before = std::fs::read_to_string(&path).unwrap();

        // Владелец из «другого окна» держит замок всё время попытки.
        let held = crate::session::manager::open_session_lock(&history_lock_path(&path)).unwrap();

        let started = std::time::Instant::now();
        let outcome = save_message_at(&path, msg("сообщение второго окна"));
        let waited = started.elapsed();

        assert!(
            outcome.is_err(),
            "занятый замок обязан дать ОШИБКУ, а не запись без блокировки: потеря одного нового \
             сообщения обратима, потеря чужой реплики — нет"
        );
        assert!(
            waited >= HISTORY_LOCK_RETRY * (HISTORY_LOCK_ATTEMPTS - 1),
            "отказ обязан наступать по исчерпании повторов ({} × {} мс), а не мгновенно: реальный \
             конфликт длится единицы миллисекунд и обязан разрешиться ожиданием. Ждали {:?}",
            HISTORY_LOCK_ATTEMPTS,
            HISTORY_LOCK_RETRY.as_millis(),
            waited
        );
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            before,
            "файл истории обязан остаться байт в байт прежним — вторая запись не состоялась"
        );

        drop(held);
        save_message_at(&path, msg("сообщение после освобождения замка"))
            .expect("после освобождения замка запись обязана пройти");
        assert_eq!(load_history_inner(&path).unwrap().len(), 2);
    }

    /// 🔴 Поправка F-14 внешнего аудита к контракту: ответ модели дороже реплики человека — он
    /// получен платным вызовом и дословно не повторяется, поэтому при занятом замке он НЕ
    /// отклоняется, а откладывается в запасной файл. Проверяются все три звена: отложен, виден
    /// при чтении истории, возвращён в историю первым же удавшимся сохранением (и файл убран).
    #[cfg(windows)]
    #[test]
    fn model_answer_is_parked_when_lock_is_busy_and_returns_on_next_successful_save() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("econometrist.json");
        save_message_at(&path, msg("вопрос клиента")).unwrap();

        let held = crate::session::manager::open_session_lock(&history_lock_path(&path)).unwrap();
        save_message_at(&path, answer("платный ответ модели", 1711360001.0)).expect(
            "ответ модели при занятом замке обязан быть отложен, а не отклонён: повторить его \
             дословно нельзя",
        );
        drop(held);

        let parked = pending_files(&path);
        assert_eq!(parked.len(), 1, "ответ обязан лежать в запасном файле: {parked:?}");
        assert!(
            !std::fs::read_to_string(&path).unwrap().contains("платный ответ модели"),
            "в сам файл истории при занятом замке писать нельзя — это уничтожило бы сообщения \
             другого окна"
        );

        // До возвращения в историю отложенный ответ обязан быть ВИДЕН клиенту.
        let shown = load_history_for_display(&path);
        assert_eq!(
            shown.iter().map(|m| m.content.as_str()).collect::<Vec<_>>(),
            vec!["вопрос клиента", "платный ответ модели"],
            "чтение истории обязано показывать отложенный ответ — иначе клиент считает его \
             потерянным"
        );

        // Первое же удавшееся сохранение возвращает отложенное в историю.
        save_message_at(&path, msg("следующая реплика клиента")).unwrap();
        let saved = load_history_inner(&path).unwrap();
        assert_eq!(
            saved.iter().map(|m| m.content.as_str()).collect::<Vec<_>>(),
            vec!["вопрос клиента", "платный ответ модели", "следующая реплика клиента"],
            "отложенный ответ обязан вернуться в историю на своё место по времени"
        );
        assert!(
            pending_files(&path).is_empty(),
            "учтённый отложенный файл убирается — но только ПОСЛЕ успешной записи"
        );
    }

    /// 🔴 Сторож C8: «очистить историю» уносит и карантинные копии ТОГО ЖЕ кабинета, и отложенные
    /// ответы — иначе полная переписка остаётся в каталоге приложения бессрочно, а продукт
    /// сообщает об успехе. Чужой кабинет при этом не задет.
    #[test]
    fn clear_history_at_also_removes_quarantine_copies_of_the_same_cabinet() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("econometrist.json");
        std::fs::write(&path, "[]").unwrap();

        let own_old = tmp.path().join("econometrist.corrupt.bak"); // формат до C7
        let own_new = tmp.path().join("econometrist.20260730-101112000.corrupt.bak");
        let own_pending = tmp.path().join("econometrist.pending-20260730-101112000.json");
        let other = tmp.path().join("media-analyst.20260730-101112000.corrupt.bak");
        for f in [&own_old, &own_new, &own_pending, &other] {
            std::fs::write(f, "полная переписка клиента").unwrap();
        }

        clear_history_at(&path).unwrap();

        assert!(!path.exists(), "сам файл истории обязан быть удалён");
        assert!(!own_old.exists(), "карантинная копия прежнего формата обязана быть удалена");
        assert!(!own_new.exists(), "карантинная копия обязана быть удалена вместе с историей");
        assert!(
            !own_pending.exists(),
            "отложенный ответ модели — та же переписка клиента и обязан уйти вместе с историей"
        );
        assert!(
            other.exists(),
            "карантин ДРУГОГО кабинета трогать нельзя — очистка одного кабинета не удаляет чужую \
             переписку"
        );
    }

    /// Имя файла-замка выведено из имени кабинета и лежит рядом с историей — иначе два кабинета
    /// делили бы один замок (лишняя сериализация) или замок ушёл бы в другой каталог.
    #[test]
    fn history_lock_lives_next_to_history_and_is_named_after_the_cabinet() {
        let path = Path::new("X:").join("history").join("econometrist.json");
        let lock = history_lock_path(&path);

        assert_eq!(lock.parent(), path.parent(), "замок обязан лежать в каталоге истории");
        assert_eq!(
            lock.file_name().unwrap().to_string_lossy(),
            ".history-econometrist.lock"
        );
        assert_ne!(
            lock,
            history_lock_path(&Path::new("X:").join("history").join("media-analyst.json")),
            "у разных кабинетов обязаны быть разные замки"
        );
    }
}
