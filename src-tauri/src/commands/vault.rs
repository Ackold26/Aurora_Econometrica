use anyhow::{Context, Result};
use log::warn;
use std::path::{Path, PathBuf};

use crate::errors::{coded, ErrorCode};

/// Sanitize cabinet_id to prevent path traversal attacks.
fn sanitize_cabinet_id(cabinet_id: &str) -> String {
    cabinet_id
        .replace(|c: char| !c.is_alphanumeric() && c != '-' && c != '_', "")
}

/// Get the per-app vaults directory path.
pub fn vaults_dir(app_data_dir: &Path) -> PathBuf {
    app_data_dir.join("vaults")
}

/// Legacy vaults directory - %PROGRAMDATA%\AIAgency\vaults\
fn legacy_vaults_dir() -> PathBuf {
    let program_data = std::env::var("PROGRAMDATA")
        .unwrap_or_else(|_| "C:\\ProgramData".to_string());
    PathBuf::from(program_data)
        .join("AIAgency")
        .join("vaults")
}

/// List available vault files.
pub fn list_vaults(app_data_dir: &Path) -> Result<Vec<String>> {
    let dir = vaults_dir(app_data_dir);
    let mut vaults = Vec::new();

    // Collect from per-app dir
    if dir.exists() {
        for entry in std::fs::read_dir(&dir)? {
            let entry = entry?;
            let path = entry.path();
            if path.extension().is_some_and(|ext| ext == "vault") {
                if let Some(stem) = path.file_stem() {
                    vaults.push(stem.to_string_lossy().to_string());
                }
            }
        }
    }

    // Also check legacy dir for vaults not yet migrated
    let legacy = legacy_vaults_dir();
    if legacy.exists() {
        for entry in std::fs::read_dir(&legacy)? {
            let entry = entry?;
            let path = entry.path();
            if path.extension().is_some_and(|ext| ext == "vault") {
                if let Some(stem) = path.file_stem() {
                    let name = stem.to_string_lossy().to_string();
                    if !vaults.contains(&name) {
                        vaults.push(name);
                    }
                }
            }
        }
    }

    Ok(vaults)
}

/// Map cabinet ID to vault filename (public, for content_updater).
pub fn vault_filename_pub(cabinet_id: &str) -> String {
    vault_filename(cabinet_id)
}

/// Map cabinet ID to vault filename (handles ID mismatches).
fn vault_filename(cabinet_id: &str) -> String {
    let safe_id = sanitize_cabinet_id(cabinet_id);
    let vault_id = match safe_id.as_str() {
        "creative-director" => "creative-group",
        other => other,
    };
    format!("{vault_id}.vault")
}

/// Resolve the vault file path, checking per-app dir first, then legacy.
/// Auto-migrates (copies) from legacy if found only there.
fn resolve_vault_path(cabinet_id: &str, app_data_dir: &Path) -> Option<PathBuf> {
    let safe_id = sanitize_cabinet_id(cabinet_id);
    let per_app_dir = vaults_dir(app_data_dir);

    // Check per-app dir first (mapped name, then original)
    let primary = per_app_dir.join(vault_filename(&safe_id));
    if primary.exists() {
        return Some(primary);
    }
    let fallback = per_app_dir.join(format!("{safe_id}.vault"));
    if fallback.exists() {
        return Some(fallback);
    }

    // Check legacy dir
    let legacy = legacy_vaults_dir();
    let legacy_primary = legacy.join(vault_filename(&safe_id));
    let legacy_fallback = legacy.join(format!("{safe_id}.vault"));

    let legacy_path = if legacy_primary.exists() {
        Some(legacy_primary)
    } else if legacy_fallback.exists() {
        Some(legacy_fallback)
    } else {
        None
    };

    // Auto-migrate: copy from legacy to per-app dir
    if let Some(ref src) = legacy_path {
        let fname = src.file_name().unwrap_or(std::ffi::OsStr::new("unknown.vault"));
        let dest = per_app_dir.join(fname);
        if let Err(e) = std::fs::create_dir_all(&per_app_dir) {
            warn!("Failed to create vault dir {}: {e}", per_app_dir.display());
        }
        if let Err(e) = std::fs::copy(src, &dest) {
            warn!("Failed to migrate vault from {} to {}: {e}", src.display(), dest.display());
        }
        if dest.exists() {
            return Some(dest);
        }
    }

    legacy_path
}

/// Check if a vault file exists for a cabinet.
pub fn vault_exists(cabinet_id: &str, app_data_dir: &Path) -> bool {
    resolve_vault_path(cabinet_id, app_data_dir).is_some()
}

/// Read a vault file.
pub fn read_vault(cabinet_id: &str, app_data_dir: &Path) -> Result<Vec<u8>> {
    let path = resolve_vault_path(cabinet_id, app_data_dir).ok_or_else(|| {
        let expected = vaults_dir(app_data_dir).join(vault_filename(cabinet_id));
        anyhow::anyhow!("{}", coded(ErrorCode::VT001, &format!("Failed to read vault: {}", expected.display())))
    })?;
    std::fs::read(&path)
        .with_context(|| coded(ErrorCode::VT001, &format!("Failed to read vault: {}", path.display())))
}

/// Pack a directory into an encrypted vault file.
pub fn pack_vault(
    source_dir: &Path,
    cabinet_id: &str,
    encryption_key: &[u8; 32],
    app_data_dir: &Path,
) -> Result<PathBuf> {
    let safe_id = sanitize_cabinet_id(cabinet_id);

    // Create tar.gz of the source directory
    let tar_gz_data = create_tar_gz(source_dir)?;

    // Encrypt
    let encrypted = crate::crypto::aes::encrypt(encryption_key, &tar_gz_data)?;

    // Write vault file to per-app dir
    let vault_dir = vaults_dir(app_data_dir);
    std::fs::create_dir_all(&vault_dir)?;
    let vault_path = vault_dir.join(format!("{safe_id}.vault"));
    std::fs::write(&vault_path, &encrypted)?;

    Ok(vault_path)
}

/// Create a tar.gz archive from a directory.
fn create_tar_gz(source_dir: &Path) -> Result<Vec<u8>> {
    let mut tar_data = Vec::new();
    {
        let encoder = flate2::write::GzEncoder::new(&mut tar_data, flate2::Compression::default());
        let mut tar_builder = tar::Builder::new(encoder);

        // Add all files relative to source_dir
        tar_builder
            .append_dir_all(".", source_dir)
            .context(coded(ErrorCode::VT003, "Failed to create tar archive"))?;

        let encoder = tar_builder.into_inner().context(coded(ErrorCode::VT004, "Failed to finalize tar"))?;
        encoder.finish().context(coded(ErrorCode::VT004, "Failed to finalize gzip"))?;
    }
    Ok(tar_data)
}
