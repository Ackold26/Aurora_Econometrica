//! Content pack loader for Aurora AI.
//!
//! Loads JSON data files from %LOCALAPPDATA%/<id>/content-packs/,
//! verifies Ed25519 manifest signature, serves via IPC.
//! Falls back gracefully to hardcoded definitions if no packs installed.

use anyhow::{Context, Result};
use log::{info, warn};
use std::path::{Path, PathBuf};

use crate::crypto::content_sig;

/// Path to the content packs directory.
pub fn content_packs_dir(app_local_data_dir: &Path) -> PathBuf {
    app_local_data_dir.join("content-packs")
}

/// Verify content pack integrity.
///
/// Returns `Ok(true)` if packs are present and signature is valid.
/// Returns `Ok(false)` if no manifest found (first run / no packs installed).
/// Returns `Err` if manifest exists but signature or checksums fail (tampering).
pub fn verify_content_packs(app_local_data_dir: &Path) -> Result<bool> {
    let dir = content_packs_dir(app_local_data_dir);

    if !dir.join("manifest.json").exists() {
        info!("Content packs not found in {:?} — using fallback data", dir);
        return Ok(false);
    }

    match content_sig::verify_manifest(&dir) {
        Ok(manifest) => {
            info!(
                "Content packs verified: v{}, {} files, product={}",
                manifest.version,
                manifest.files.len(),
                manifest.product,
            );
            Ok(true)
        }
        Err(e) => {
            warn!("Content pack verification FAILED: {e}");
            Err(e)
        }
    }
}

/// Load a JSON content pack file by name.
///
/// Returns the raw JSON string. Assumes packs were verified at startup.
/// Validates filename to prevent path traversal.
pub fn load_pack_file(app_local_data_dir: &Path, filename: &str) -> Result<String> {
    if filename.contains("..") || filename.contains('/') || filename.contains('\\') {
        anyhow::bail!("Invalid pack filename: {}", filename);
    }

    let path = content_packs_dir(app_local_data_dir).join(filename);

    if !path.exists() {
        anyhow::bail!("Pack file not found: {}", filename);
    }

    std::fs::read_to_string(&path).context(format!("Failed to read pack file: {}", filename))
}

/// Return the path to a help HTML file from the content pack, or None if absent.
///
/// cabinet_id is validated to contain only alphanumeric chars, dashes, and underscores.
pub fn help_file_path(app_local_data_dir: &Path, cabinet_id: &str) -> Option<PathBuf> {
    if !cabinet_id
        .chars()
        .all(|c| c.is_alphanumeric() || c == '-' || c == '_')
    {
        return None;
    }

    let path = content_packs_dir(app_local_data_dir)
        .join("help")
        .join(format!("{}.html", cabinet_id));

    if path.exists() {
        Some(path)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_load_pack_file_path_traversal() {
        let dir = TempDir::new().unwrap();
        assert!(load_pack_file(dir.path(), "../secret.json").is_err());
        assert!(load_pack_file(dir.path(), "sub/file.json").is_err());
        assert!(load_pack_file(dir.path(), "sub\\file.json").is_err());
    }

    #[test]
    fn test_load_pack_file_not_found() {
        let dir = TempDir::new().unwrap();
        assert!(load_pack_file(dir.path(), "cabinets.json").is_err());
    }

    #[test]
    fn test_load_pack_file_valid() {
        let dir = TempDir::new().unwrap();
        let packs_dir = dir.path().join("content-packs");
        fs::create_dir_all(&packs_dir).unwrap();
        fs::write(packs_dir.join("test.json"), r#"{"ok":true}"#).unwrap();
        let content = load_pack_file(dir.path(), "test.json").unwrap();
        assert_eq!(content, r#"{"ok":true}"#);
    }

    #[test]
    fn test_help_file_path_validation() {
        let dir = TempDir::new().unwrap();
        // Invalid cabinet IDs return None without touching fs
        assert!(help_file_path(dir.path(), "../etc/passwd").is_none());
        assert!(help_file_path(dir.path(), "foo/bar").is_none());
    }

    #[test]
    fn test_verify_no_manifest_returns_false() {
        let dir = TempDir::new().unwrap();
        assert!(!verify_content_packs(dir.path()).unwrap());
    }
}
