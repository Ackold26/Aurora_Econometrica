//! Content updater for Aurora AI v2.
//!
//! Downloads updated vault files from Supabase Storage via the /content Edge Function.
//! Compares local content version with server version from /auth response.

use anyhow::{Context, Result};
use log::{info, warn, error};
use sha2::{Sha256, Digest};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use tauri::Emitter;

use crate::crypto;
use super::vault;

/// Supabase Edge Functions base URL (obfuscated at compile time).
fn supabase_url() -> String {
    obfstr::obfstr!("https://quzhkfvglqmppxcrindh.supabase.co/functions/v1").to_string()
}

/// HTTP request timeout for downloads (longer for large files).
const DOWNLOAD_TIMEOUT_SECS: u64 = 120;

// ── Local version tracking (legacy) ───────────────────────────

/// Path to local content version file.
fn version_file_path(app_config_dir: &Path) -> PathBuf {
    app_config_dir.join("content_version.txt")
}

/// Read the locally stored content version (e.g., "c5").
pub fn get_local_version(app_config_dir: &Path) -> Option<String> {
    let path = version_file_path(app_config_dir);
    std::fs::read_to_string(&path).ok().map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
}

/// Save the current content version locally.
pub fn set_local_version(app_config_dir: &Path, version: &str) -> Result<()> {
    let path = version_file_path(app_config_dir);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, version)?;
    Ok(())
}

// ── Per-cabinet vault version tracking ────────────────────────

/// Path to per-cabinet vault versions file.
fn vault_versions_path(app_config_dir: &Path) -> PathBuf {
    app_config_dir.join("vault-versions.json")
}

/// Map vault file stem to canonical cabinet ID (inverse of vault::vault_filename_pub).
fn stem_to_cabinet_id(stem: &str) -> &str {
    match stem {
        "creative-group" => "creative-director",
        other => other,
    }
}

/// Read per-cabinet vault versions. Returns empty map if file doesn't exist.
pub fn get_vault_versions(app_config_dir: &Path) -> HashMap<String, u32> {
    std::fs::read_to_string(vault_versions_path(app_config_dir))
        .ok()
        .and_then(|json| serde_json::from_str(&json).ok())
        .unwrap_or_default()
}

/// Update version for a specific cabinet in vault-versions.json.
pub fn set_vault_version(app_config_dir: &Path, cabinet_id: &str, version: u32) -> Result<()> {
    let mut versions = get_vault_versions(app_config_dir);
    versions.insert(cabinet_id.to_string(), version);
    let path = vault_versions_path(app_config_dir);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, serde_json::to_string_pretty(&versions)?)?;
    Ok(())
}

/// One-time migration from legacy content_version.txt to vault-versions.json.
/// Assigns the legacy global version to all existing vault files on disk.
/// No-op if vault-versions.json already exists.
pub fn migrate_from_legacy(app_config_dir: &Path, app_data_dir: &Path) -> Result<()> {
    if vault_versions_path(app_config_dir).exists() {
        return Ok(());
    }
    let Some(ver_str) = get_local_version(app_config_dir) else {
        return Ok(());
    };
    let ver: u32 = ver_str.trim_start_matches('c').parse().unwrap_or(0);
    if ver == 0 {
        return Ok(());
    }
    let mut versions: HashMap<String, u32> = HashMap::new();
    let vaults_dir = vault::vaults_dir(app_data_dir);
    if let Ok(entries) = std::fs::read_dir(&vaults_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().is_some_and(|ext| ext == "vault") {
                if let Some(stem) = path.file_stem() {
                    let cab_id = stem_to_cabinet_id(&stem.to_string_lossy()).to_string();
                    versions.insert(cab_id, ver);
                }
            }
        }
    }
    if !versions.is_empty() {
        let path = vault_versions_path(app_config_dir);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&path, serde_json::to_string_pretty(&versions)?)?;
        info!("Migrated {} vault versions from legacy (v{})", versions.len(), ver);
    }
    Ok(())
}

// ── Update check ───────────────────────────────────────────

/// Result of checking for content updates.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ContentUpdateStatus {
    pub update_available: bool,
    pub local_version: Option<String>,
    pub server_version: Option<String>,
    pub files_to_update: Vec<String>,
}

/// Check if a content update is available.
/// Compares local version with server version and checksums.
pub fn check_update(
    app_config_dir: &Path,
    app_data_dir: &Path,
    server_version: Option<&str>,
    server_checksums: &serde_json::Value,
) -> ContentUpdateStatus {
    let local_ver = get_local_version(app_config_dir);
    let server_ver = server_version.map(|s| s.to_string());

    // No server version means no content published yet
    let Some(ref sv) = server_ver else {
        return ContentUpdateStatus {
            update_available: false,
            local_version: local_ver,
            server_version: None,
            files_to_update: vec![],
        };
    };

    // If versions match, check individual file checksums
    let needs_update = match &local_ver {
        Some(lv) if lv == sv => false,
        _ => true,
    };

    let mut files_to_update = Vec::new();

    if let Some(checksums_obj) = server_checksums.as_object() {
        let vaults_dir = vault::vaults_dir(app_data_dir);
        for (filename, expected_hash) in checksums_obj {
            let expected = expected_hash.as_str().unwrap_or("");
            let local_path = vaults_dir.join(filename);

            let needs_download = if local_path.exists() && !expected.is_empty() {
                // Compare SHA-256
                match std::fs::read(&local_path) {
                    Ok(data) => {
                        let mut hasher = Sha256::new();
                        hasher.update(&data);
                        let local_hash = format!("{:x}", hasher.finalize());
                        local_hash != expected
                    }
                    Err(_) => true,
                }
            } else {
                true
            };

            if needs_download {
                files_to_update.push(filename.clone());
            }
        }
    }

    let update_available = needs_update || !files_to_update.is_empty();

    ContentUpdateStatus {
        update_available,
        local_version: local_ver,
        server_version: server_ver,
        files_to_update,
    }
}

/// Check which cabinets need updating based on per-cabinet server versions.
/// `server_versions`: cabinet_id → version number, e.g. `{"media-analyst": 5}`.
/// Use this when the server sends `vault_versions` in the /auth response.
pub fn check_update_per_cabinet(
    app_config_dir: &Path,
    server_versions: &HashMap<String, u32>,
) -> ContentUpdateStatus {
    let local_versions = get_vault_versions(app_config_dir);
    let files_to_update: Vec<String> = server_versions.iter()
        .filter(|(cab_id, &server_ver)| {
            local_versions.get(cab_id.as_str()).copied().unwrap_or(0) < server_ver
        })
        .map(|(cab_id, _)| vault::vault_filename_pub(cab_id))
        .collect();
    ContentUpdateStatus {
        update_available: !files_to_update.is_empty(),
        local_version: None,   // not used in per-cabinet mode
        server_version: None,  // not used in per-cabinet mode
        files_to_update,
    }
}

// ── Local encryption key ───────────────────────────────

/// Path to the local vault encryption salt.
fn salt_path(app_config_dir: &Path) -> PathBuf {
    app_config_dir.join("vault_salt.bin")
}

/// Get or create a persistent random salt (32 bytes) for local vault encryption.
fn get_or_create_salt(app_config_dir: &Path) -> Result<Vec<u8>> {
    let path = salt_path(app_config_dir);
    if path.exists() {
        let salt = std::fs::read(&path)?;
        if salt.len() == 32 {
            return Ok(salt);
        }
    }

    // Generate new random salt
    use rand::RngCore;
    let mut salt = vec![0u8; 32];
    rand::thread_rng().fill_bytes(&mut salt);

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, &salt)?;
    info!("Generated new vault encryption salt");
    Ok(salt)
}

/// Derive a local encryption key from machine fingerprint + local salt.
/// Used by content_updater (encrypt after download) and open_cabinet (decrypt before use).
pub fn derive_local_key(app_config_dir: &Path) -> Result<[u8; 32]> {
    let fp = crypto::fingerprint::get_machine_fingerprint()?;
    let salt = get_or_create_salt(app_config_dir)?;
    crypto::hkdf::derive_key(&fp, &salt)
}

// ── Download ───────────────────────────────────────────────

/// Download a single vault file from the server.
async fn download_vault_file(
    fingerprint_hash: &str,
    product: &str,
    version: &str,
    filename: &str,
) -> Result<Vec<u8>> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(DOWNLOAD_TIMEOUT_SECS))
        .build()?;

    let url = format!(
        "{}/content?fingerprint_hash={}&product={}&version={}&file={}",
        supabase_url(), fingerprint_hash, product, version, filename
    );

    info!("Downloading vault: {}", filename);

    let res = client.get(&url).send().await?;

    if !res.status().is_success() {
        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        anyhow::bail!("Download failed for {}: HTTP {} — {}", filename, status, body);
    }

    let bytes = res.bytes().await?;
    Ok(bytes.to_vec())
}

/// Download and save all updated vault files.
/// Returns the list of successfully updated files.
/// If `app_handle` is provided, emits "vault-download-progress" events.
pub async fn download_updates(
    app_config_dir: &Path,
    app_data_dir: &Path,
    product: &str,
    version: &str,
    files: &[String],
    checksums: &serde_json::Value,
    app_handle: Option<&tauri::AppHandle>,
) -> Result<Vec<String>> {
    let fp = crate::crypto::fingerprint::get_machine_fingerprint()?;
    let fp_hash = crate::crypto::fingerprint::hash_fingerprint(&fp);

    // Derive local encryption key (fingerprint + local salt)
    let local_key = derive_local_key(app_config_dir)?;

    let vaults_dir = vault::vaults_dir(app_data_dir);
    std::fs::create_dir_all(&vaults_dir)
        .context("Failed to create vaults directory")?;

    let mut updated = Vec::new();

    for (idx, filename) in files.iter().enumerate() {
        // Emit progress event
        if let Some(handle) = app_handle {
            let _ = handle.emit("vault-download-progress", serde_json::json!({
                "file": filename,
                "current": idx + 1,
                "total": files.len(),
            }));
        }
        match download_vault_file(&fp_hash, product, version, filename).await {
            Ok(data) => {
                // Verify checksum if available (against unencrypted data from server)
                if let Some(expected) = checksums.get(filename).and_then(|v| v.as_str()) {
                    if !expected.is_empty() {
                        let mut hasher = Sha256::new();
                        hasher.update(&data);
                        let actual = format!("{:x}", hasher.finalize());
                        if actual != expected {
                            error!(
                                "Checksum mismatch for {}: expected {}..., got {}...",
                                filename,
                                &expected[..12.min(expected.len())],
                                &actual[..12]
                            );
                            continue;
                        }
                    }
                }

                // Encrypt with local key before saving to disk
                let encrypted = crypto::aes::encrypt(&local_key, &data)
                    .with_context(|| format!("Failed to encrypt vault: {}", filename))?;

                let dest = vaults_dir.join(filename);
                std::fs::write(&dest, &encrypted)
                    .with_context(|| format!("Failed to write vault file: {}", dest.display()))?;

                info!("Updated vault: {} ({} bytes plain → {} bytes encrypted)", filename, data.len(), encrypted.len());
                updated.push(filename.clone());

                // Track per-cabinet version in vault-versions.json
                if let Some(stem) = filename.strip_suffix(".vault") {
                    let cab_id = stem_to_cabinet_id(stem);
                    let ver_num: u32 = version.trim_start_matches('c').parse().unwrap_or(0);
                    if ver_num > 0 {
                        if let Err(e) = set_vault_version(app_config_dir, cab_id, ver_num) {
                            warn!("Failed to record per-cabinet version for {}: {}", cab_id, e);
                        }
                    }
                }
            }
            Err(e) => {
                error!("Failed to download {}: {}", filename, e);
            }
        }
    }

    // Update local version if all files downloaded successfully
    if updated.len() == files.len() {
        set_local_version(app_config_dir, version)?;
        info!("Content version updated to {}", version);
    } else {
        warn!(
            "Partial update: {}/{} files downloaded. Version NOT updated.",
            updated.len(),
            files.len()
        );
    }

    Ok(updated)
}
