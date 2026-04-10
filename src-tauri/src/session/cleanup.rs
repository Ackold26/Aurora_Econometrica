use anyhow::Result;
use std::path::PathBuf;

/// Clean up any leftover session directories from previous runs (crash recovery).
pub fn cleanup_stale_sessions() -> Result<()> {
    let local_app_data = std::env::var("LOCALAPPDATA")
        .unwrap_or_else(|_| "C:\\Users\\Default\\AppData\\Local".to_string());
    let sessions_dir = PathBuf::from(&local_app_data)
        .join("AIAgency")
        .join("sessions");

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
