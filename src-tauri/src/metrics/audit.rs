use log::info;
use serde::Serialize;
use std::sync::Mutex;

static AUDIT_LOG: Mutex<Vec<AuditEntry>> = Mutex::new(Vec::new());

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
