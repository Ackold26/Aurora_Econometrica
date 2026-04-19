//! One-time data migration when product identifier changes (ROSST → Aurora AI).
//!
//! Copies user data (license, vaults, salt, cache) from old app directory to new one.
//! Idempotent: skips if destination already has a license.json.
//! Copies (not moves) to allow rollback to the old version.

use log::{info, warn};
use std::path::{Path, PathBuf};

/// Map of old identifiers → new identifiers.
const IDENTIFIER_MIGRATIONS: &[(&str, &str)] = &[
    ("com.aiagency.desktop", "com.aurora.agency"),
    ("com.rosst.legal", "com.aurora.legal"),
    ("com.rosst.creative", "com.aurora.creative-hub"),
    ("com.rosst.media", "com.aurora.analytics-hub"),
    ("com.rosst.docmaster", "com.aurora.docmaster"),
    // com.aurora.creative-hub → com.aurora.creative-hub (no change, skip)
];

/// Files to copy from old config dir (%APPDATA%/<id>/).
const CONFIG_FILES: &[&str] = &[
    "license.json",
    "vault_salt.bin",
    "session_cache.json",
    "vault-versions.json",
    "content_version.txt",
    "instance.id",
    "audit.log",
];

/// Directories to copy from old config dir.
const CONFIG_DIRS: &[&str] = &["vaults"];

/// Directories to copy from old local data dir (%LOCALAPPDATA%/<id>/).
const LOCAL_DATA_DIRS: &[&str] = &["content-packs"];

/// Run one-time data migration from old identifier paths to current.
///
/// Called once at startup before Tauri app is built.
/// Finds the old identifier for the current product, checks if old data exists,
/// and copies it to the new location.
pub fn migrate_if_needed(current_identifier: &str) {
    let old_id = IDENTIFIER_MIGRATIONS
        .iter()
        .find(|(_, new)| *new == current_identifier)
        .map(|(old, _)| *old);

    let Some(old_identifier) = old_id else {
        return;
    };
    if old_identifier == current_identifier {
        return;
    }

    let appdata = std::env::var("APPDATA").ok();
    let localappdata = std::env::var("LOCALAPPDATA").ok();

    // Migrate config dir (%APPDATA%)
    if let Some(ref root) = appdata {
        let old_dir = PathBuf::from(root).join(old_identifier);
        let new_dir = PathBuf::from(root).join(current_identifier);

        if old_dir.exists() && !new_dir.join("license.json").exists() {
            info!(
                "Migrating config data: {} → {}",
                old_identifier, current_identifier
            );
            migrate_dir(&old_dir, &new_dir, CONFIG_FILES, CONFIG_DIRS);
        }
    }

    // Migrate local data dir (%LOCALAPPDATA%)
    if let Some(ref root) = localappdata {
        let old_dir = PathBuf::from(root).join(old_identifier);
        let new_dir = PathBuf::from(root).join(current_identifier);

        if old_dir.exists() && !new_dir.join("content-packs").exists() {
            info!(
                "Migrating local data: {} → {}",
                old_identifier, current_identifier
            );
            migrate_dir(&old_dir, &new_dir, &[], LOCAL_DATA_DIRS);
        }
    }
}

fn migrate_dir(old: &Path, new: &Path, files: &[&str], dirs: &[&str]) {
    let _ = std::fs::create_dir_all(new);

    for fname in files {
        let src = old.join(fname);
        let dst = new.join(fname);
        if src.exists() && !dst.exists() {
            match std::fs::copy(&src, &dst) {
                Ok(_) => info!("  Migrated: {}", fname),
                Err(e) => warn!("  Failed to migrate {}: {}", fname, e),
            }
        }
    }

    for dir_name in dirs {
        let src = old.join(dir_name);
        let dst = new.join(dir_name);
        if src.is_dir() && !dst.exists() {
            match copy_dir_recursive(&src, &dst) {
                Ok(n) => info!("  Migrated: {}/ ({} files)", dir_name, n),
                Err(e) => warn!("  Failed to migrate {}/: {}", dir_name, e),
            }
        }
    }
}

fn copy_dir_recursive(src: &Path, dst: &Path) -> std::io::Result<usize> {
    std::fs::create_dir_all(dst)?;
    let mut count = 0;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let s = entry.path();
        let d = dst.join(entry.file_name());
        if s.is_dir() {
            count += copy_dir_recursive(&s, &d)?;
        } else {
            std::fs::copy(&s, &d)?;
            count += 1;
        }
    }
    Ok(count)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn migrate_no_old_dir_is_noop() {
        // No old dir exists → nothing happens, no error
        migrate_if_needed("com.aurora.agency");
    }

    #[test]
    fn migrate_unknown_identifier_is_noop() {
        migrate_if_needed("com.unknown.product");
    }

    #[test]
    fn migrate_copies_files() {
        let tmp = TempDir::new().unwrap();
        let old = tmp.path().join("old-id");
        let new = tmp.path().join("new-id");
        std::fs::create_dir_all(&old).unwrap();
        std::fs::write(old.join("license.json"), b"test-license").unwrap();
        std::fs::write(old.join("vault_salt.bin"), b"salt-bytes-32chars-padded-here!x").unwrap();

        migrate_dir(&old, &new, CONFIG_FILES, &[]);

        assert!(new.join("license.json").exists());
        assert_eq!(
            std::fs::read_to_string(new.join("license.json")).unwrap(),
            "test-license"
        );
        assert!(new.join("vault_salt.bin").exists());
    }

    #[test]
    fn migrate_skips_if_dest_exists() {
        let tmp = TempDir::new().unwrap();
        let old = tmp.path().join("old-id");
        let new = tmp.path().join("new-id");
        std::fs::create_dir_all(&old).unwrap();
        std::fs::create_dir_all(&new).unwrap();
        std::fs::write(old.join("license.json"), b"old-license").unwrap();
        std::fs::write(new.join("license.json"), b"new-license").unwrap();

        migrate_dir(&old, &new, CONFIG_FILES, &[]);

        // Should NOT overwrite existing file
        assert_eq!(
            std::fs::read_to_string(new.join("license.json")).unwrap(),
            "new-license"
        );
    }

    #[test]
    fn migrate_copies_dirs_recursively() {
        let tmp = TempDir::new().unwrap();
        let old = tmp.path().join("old-id");
        let new = tmp.path().join("new-id");
        let vaults = old.join("vaults");
        std::fs::create_dir_all(&vaults).unwrap();
        std::fs::write(vaults.join("media-analyst.vault"), b"vault-data").unwrap();
        std::fs::write(vaults.join("creative-director.vault"), b"vault-data-2").unwrap();

        migrate_dir(&old, &new, &[], &["vaults"]);

        assert!(new.join("vaults").join("media-analyst.vault").exists());
        assert!(new.join("vaults").join("creative-director.vault").exists());
    }
}
