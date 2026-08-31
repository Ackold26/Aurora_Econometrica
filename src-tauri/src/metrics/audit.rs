use log::info;
use serde::Serialize;
use std::sync::Mutex;

static AUDIT_LOG: Mutex<Vec<AuditEntry>> = Mutex::new(Vec::new());
// Гонка записи в файл (найдена в живом прогоне 2026-09-01): AUDIT_LOG защищает только вектор
// в памяти и отпускается до записи на диск — параллельные append_to_file накладывали строки
// друг на друга. Отдельный замок, не расширяющий область AUDIT_LOG на время работы с диском.
static AUDIT_FILE_LOCK: Mutex<()> = Mutex::new(());

#[derive(Debug, Clone, Serialize)]
pub struct AuditEntry {
    pub timestamp: String,
    pub event: String,
    pub details: String,
    pub success: bool,
}

/// Record an audit event (license check, vault open, session activity, etc.)
pub fn log_event(event: &str, details: &str, success: bool) {
    let timestamp = chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%.3f").to_string();
    let entry = AuditEntry {
        timestamp: timestamp.clone(),
        event: event.to_string(),
        details: details.to_string(),
        success,
    };

    info!("[AUDIT] {event} | {details} | success={success}");

    if let Ok(mut log) = AUDIT_LOG.lock() {
        log.push(entry);
        // Keep last 1000 entries in memory
        if log.len() > 1000 {
            let excess = log.len() - 1000;
        log.drain(..excess);
        }
    }

    // Also persist to file (best-effort)
    let _ = append_to_file(event, details, success, &timestamp);
}

fn append_to_file(event: &str, details: &str, success: bool, timestamp: &str) -> std::io::Result<()> {
    // Сериализуем ротацию и запись одним замком — иначе один поток переименовывает файл
    // (rotate_if_large), пока другой в него пишет. Отравление замка не роняем: вся запись
    // в журнал и так best-effort (см. `let _ =` у вызывающего log_event).
    let _file_guard = AUDIT_FILE_LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner());

    // CPD-30: per-app каталог с одноразовым переносом legacy AIAgency\audit.log (лежал прямо в
    // корне legacy-каталога, sub="" — см. durable_store). Ошибка init/переноса здесь best-effort,
    // как и раньше был best-effort весь append_to_file (см. вызывающий log_event: `let _ =`).
    let audit_dir = match crate::durable_store::app_state_dir("") {
        Ok(d) => d,
        Err(_) => return Ok(()),
    };
    let audit_file = audit_dir.join("audit.log");
    // 🔴 Внешний аудит 2026-07-29 (High): ротация возвращена из донора — без неё audit.log рос
    // без предела (см. durable_store::rotate_if_large).
    crate::durable_store::rotate_if_large(&audit_file, 5 * 1024 * 1024);

    use std::io::Write;
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&audit_file)?;
    writeln!(file, "{}\t{}\t{}\t{}", timestamp, event, if success { "OK" } else { "FAIL" }, details)?;
    Ok(())
}

/// Get recent audit entries (for diagnostics).
pub fn get_recent(limit: usize) -> Vec<AuditEntry> {
    AUDIT_LOG
        .lock()
        .map(|log| {
            let start = log.len().saturating_sub(limit);
            log[start..].to_vec()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    /// Гонка записи (найдена в живом прогоне 2026-09-01, см. комментарий у AUDIT_FILE_LOCK):
    /// без замка на файл параллельные append_to_file накладывали строки друг на друга —
    /// метка времени/событие/итог слипались в одну строку или терялись. Бьём log_event из
    /// N потоков и проверяем, что дописалось ровно N ЦЕЛЫХ строк со своим маркером.
    /// durable_store::init() тестами не вызывается (см. session/mod.rs) — файл уходит в
    /// стабильный fallback-путь по имени пакета, не в боевой каталог продукта.
    #[test]
    fn concurrent_log_event_does_not_corrupt_file() {
        let audit_file = crate::durable_store::resolve_path("").join("audit.log");
        let marker = format!("race_test_{}", std::process::id());
        let before_len = std::fs::metadata(&audit_file).map(|m| m.len()).unwrap_or(0) as usize;

        const N: usize = 40;
        let threads: Vec<_> = (0..N)
            .map(|i| {
                let marker = marker.clone();
                std::thread::spawn(move || {
                    log_event(&marker, &format!("thread-{i:02}"), true);
                })
            })
            .collect();
        for t in threads {
            t.join().unwrap();
        }

        let mut content = String::new();
        std::fs::File::open(&audit_file)
            .unwrap()
            .read_to_string(&mut content)
            .unwrap();
        let appended = &content[before_len..];
        let matching: Vec<&str> = appended.lines().filter(|l| l.contains(&marker)).collect();
        assert_eq!(
            matching.len(),
            N,
            "ожидали {N} целых строк, получили {}: {:?}",
            matching.len(),
            matching
        );
        for line in &matching {
            let cols: Vec<&str> = line.split('\t').collect();
            assert_eq!(cols.len(), 4, "строка развалилась/слиплась: {line:?}");
        }
    }
}
