use anyhow::Result;

/// Clean up any leftover session directories from previous runs (crash recovery).
pub fn cleanup_stale_sessions() -> Result<()> {
    // CPD-30: per-app каталог (см. durable_store) — тот же вызов, что SessionManager::new()
    // (session/manager.rs), иначе очистка на старте не находила бы то, что создал менеджер.
    let sessions_dir = crate::durable_store::app_state_dir(crate::durable_store::SESSIONS_SUB)?;

    if !sessions_dir.exists() {
        return Ok(());
    }

    for entry in std::fs::read_dir(&sessions_dir)? {
        let entry = entry?;
        if entry.file_type()?.is_dir() {
            // Delete leftover session directories
            let _ = std::fs::remove_dir_all(entry.path());
        }
    }

    Ok(())
}
