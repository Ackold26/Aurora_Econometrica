use anyhow::Result;
use log::info;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::Emitter;

use crate::errors::{coded_err, ErrorCode};

fn update_base_url() -> String {
    obfstr::obfstr!("https://ackold26.github.io/rosst-updates").to_string()
}

fn supabase_update_url() -> String {
    obfstr::obfstr!("https://quzhkfvglqmppxcrindh.supabase.co/functions/v1/app-update").to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VersionInfo {
    pub version: String,
    pub download_url: String,
    #[serde(default)]
    pub release_notes: String,
    #[serde(default)]
    pub mandatory: bool,
    #[serde(default)]
    pub checksum: String,
    #[serde(default)]
    pub min_version: String,
}

/// Check for updates via Supabase Edge Function.
async fn check_supabase(product: &str) -> Result<VersionInfo> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()?;

    let resp = client
        .post(&supabase_update_url())
        .json(&serde_json::json!({ "product": product }))
        .send()
        .await?;

    if !resp.status().is_success() {
        anyhow::bail!("Supabase /app-update returned {}", resp.status());
    }

    Ok(resp.json().await?)
}

/// Check for updates via GitHub Pages manifest (fallback).
async fn check_github_pages(product: &str) -> Result<VersionInfo> {
    let url = format!("{}/{}/latest.json", update_base_url(), product);

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()?;

    let resp = client.get(&url).send().await?;

    if !resp.status().is_success() {
        return Err(coded_err(ErrorCode::UP001, &format!("Update server returned {}", resp.status())));
    }

    Ok(resp.json().await?)
}

/// Check if a newer version is available.
/// Tries Supabase first, falls back to GitHub Pages.
/// Returns `Some(VersionInfo)` if update available, `None` if current.
pub async fn check_for_updates(current_version: &str) -> Result<Option<VersionInfo>> {
    let product = env!("CARGO_PKG_NAME");

    let info = match check_supabase(product).await {
        Ok(info) => info,
        Err(e) => {
            info!("UP005: Supabase update check failed ({}), falling back to GitHub Pages", e);
            check_github_pages(product).await?
        }
    };

    if is_newer(&info.version, current_version) {
        Ok(Some(info))
    } else {
        Ok(None)
    }
}

/// Download update .exe to a temp directory, emitting progress events.
pub async fn download_update(url: &str, app_handle: &tauri::AppHandle) -> Result<PathBuf> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(600))
        .build()?;

    let resp = client.get(url).send().await
        .map_err(|e| coded_err(ErrorCode::UP002, &format!("Download failed: {e}")))?;

    if !resp.status().is_success() {
        return Err(coded_err(ErrorCode::UP002, &format!("Download returned {}", resp.status())));
    }

    let total_size = resp.content_length().unwrap_or(0);
    let temp_dir = tempfile::Builder::new()
        .prefix("aurora-update-")
        .tempdir()
        .map_err(|e| coded_err(ErrorCode::UP002, &format!("Failed to create temp dir: {e}")))?;
    let temp_dir_path = temp_dir.keep();

    // Extract filename from URL
    let filename = url.rsplit('/').next().unwrap_or("update-setup.exe");
    let dest_path = temp_dir_path.join(filename);

    let mut file = tokio::fs::File::create(&dest_path).await?;
    let mut downloaded: u64 = 0;

    use tokio::io::AsyncWriteExt;
    let mut stream = resp.bytes_stream();
    use futures_util::StreamExt;

    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| coded_err(ErrorCode::UP002, &format!("Download stream error: {e}")))?;
        file.write_all(&chunk).await?;
        downloaded += chunk.len() as u64;

        // Emit progress
        let progress = if total_size > 0 { (downloaded as f64 / total_size as f64 * 100.0) as u32 } else { 0 };
        let _ = app_handle.emit("update-progress", serde_json::json!({
            "downloaded": downloaded,
            "total": total_size,
            "percent": progress
        }));
    }
    file.flush().await?;

    info!("Update downloaded: {} ({} bytes)", dest_path.display(), downloaded);
    Ok(dest_path)
}

/// Verify SHA256 checksum of a downloaded file.
pub fn verify_checksum(file_path: &std::path::Path, expected: &str) -> Result<()> {
    if expected.is_empty() {
        anyhow::bail!("Update checksum is missing - refusing to install unverified update");
    }

    // Strip "sha256:" prefix if present
    let expected_hash = expected.strip_prefix("sha256:").unwrap_or(expected);

    let data = std::fs::read(file_path)?;
    let hash = sha2::Sha256::digest(&data);
    let actual = hex::encode(hash);

    if actual != expected_hash.to_lowercase() {
        return Err(coded_err(ErrorCode::UP003, &format!(
            "Download integrity check failed. Expected: {}..., got: {}...",
            &expected_hash[..12.min(expected_hash.len())],
            &actual[..12]
        )));
    }

    info!("Checksum verified: {}", &actual[..16]);
    Ok(())
}

/// Launch the installer silently and exit the current process.
///
/// Phase 3.1 (2026-05-23): stop sidecar before launching installer.
/// Without this, `econometrica-sidecar.exe` holds `.pyd` file locks → NSIS
/// "Error opening file for writing" → installer skips locked files silently →
/// frontend new + sidecar old → silent functional gaps (memory: install-lock-issue).
/// NSIS PREINSTALL hook (installer_hooks.nsh) is the safety net for cases where
/// this Rust path is bypassed (manual installer run, watchdog respawn race).
pub fn apply_update(installer_path: &std::path::Path) -> Result<()> {
    if !installer_path.exists() {
        return Err(coded_err(ErrorCode::UP004, &format!("Installer not found: {}", installer_path.display())));
    }

    info!("Applying update: {}", installer_path.display());

    // Stop sidecar BEFORE launching installer so .pyd locks are released.
    // stop_sidecar is idempotent: no-op if sidecar never started or already exited.
    // Internally does graceful POST /shutdown → wait up to 5s → taskkill /T /F fallback.
    info!("Pre-update: stopping sidecar to release file locks");
    crate::econ_sidecar::stop_sidecar();

    // Launch installer with elevation via PowerShell Start-Process -Verb RunAs
    let installer_str = installer_path.display().to_string().replace('\'', "''");
    std::process::Command::new("powershell")
        .args([
            "-NoProfile", "-Command",
            &format!(
                "Start-Process -FilePath '{}' -ArgumentList '/S' -Verb RunAs",
                installer_str
            ),
        ])
        .spawn()
        .map_err(|e| coded_err(ErrorCode::UP004, &format!("Failed to launch installer: {e}")))?;

    // Brief pause so UI can show "Installing..." state before exit
    std::thread::sleep(std::time::Duration::from_secs(2));

    // Exit current process to allow installer to replace files
    std::process::exit(0);
}

/// Check if an update is required based on server response (v2 online path).
/// Returns VersionInfo built from the online auth data.
pub fn check_server_update(
    current_version: &str,
    app_min_version: &str,
    update_url: Option<&str>,
) -> Option<VersionInfo> {
    if !is_newer(app_min_version, current_version) {
        return None;
    }

    Some(VersionInfo {
        version: app_min_version.to_string(),
        download_url: update_url.unwrap_or("").to_string(),
        release_notes: String::new(),
        mandatory: true,
        checksum: String::new(),
        min_version: String::new(),
    })
}

/// Simple semver comparison: returns true if `remote` > `current`.
fn is_newer(remote: &str, current: &str) -> bool {
    let parse = |v: &str| -> Vec<u32> {
        v.trim_start_matches('v')
            .split('.')
            .filter_map(|s| s.parse().ok())
            .collect()
    };
    let r = parse(remote);
    let c = parse(current);
    r > c
}

use sha2::Digest;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_comparison() {
        assert!(is_newer("0.2.0", "0.1.0"));
        assert!(is_newer("1.0.0", "0.9.9"));
        assert!(is_newer("v0.1.1", "0.1.0"));
        assert!(!is_newer("0.1.0", "0.1.0"));
        assert!(!is_newer("0.0.9", "0.1.0"));
    }

    #[test]
    fn version_not_newer_than_self() {
        // Одинаковая версия НЕ является более новой
        assert!(!is_newer("0.2.0", "0.2.0"));
        assert!(!is_newer("1.0.0", "1.0.0"));
        assert!(!is_newer("v0.0.1", "0.0.1"));
    }
}
