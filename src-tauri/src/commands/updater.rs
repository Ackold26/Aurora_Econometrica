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
        .post(supabase_update_url())
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

/// Product-ключ канала обновлений.
///
/// D2 (2026-07-03, двухредакционная упаковка): локальная редакция
/// (`--no-default-features`, identifier com.aurora.econometrica.local)
/// обязана получать ТОЛЬКО локальные сборки — общий канал затянул бы
/// облачный exe поверх локального (в нём живёт Claude-канал → нарушение
/// «0 egress»). Суффикс «-local» разводит манифесты:
///   облачная:  aurora-econometrica-gui/latest.json
///   локальная: aurora-econometrica-gui-local/latest.json
/// Публикация локального манифеста — регламент aurora-release-update.
pub fn update_product_key() -> String {
    if cfg!(feature = "cloud_advisors") {
        env!("CARGO_PKG_NAME").to_string()
    } else {
        format!("{}-local", env!("CARGO_PKG_NAME"))
    }
}

/// Check if a newer version is available.
/// Tries Supabase first, falls back to GitHub Pages.
/// Returns `Some(VersionInfo)` if update available, `None` if current.
pub async fn check_for_updates(current_version: &str) -> Result<Option<VersionInfo>> {
    let product = &update_product_key();

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
        .map_err(|e| coded_err(ErrorCode::UP002, &format!("Не удалось загрузить обновление (проверьте подключение к интернету): {e}")))?;

    if !resp.status().is_success() {
        return Err(coded_err(ErrorCode::UP002, &format!("Сервер обновлений вернул ошибку {} — повторите позже.", resp.status())));
    }

    let total_size = resp.content_length().unwrap_or(0);
    let temp_dir = tempfile::Builder::new()
        .prefix("aurora-update-")
        .tempdir()
        .map_err(|e| coded_err(ErrorCode::UP002, &format!("Failed to create temp dir: {e}")))?;
    let temp_dir_path = temp_dir.keep();

    // Extract filename from URL — sanitize to a bare basename with a strict
    // whitelist: a manifest-controlled download_url must never place the .exe
    // outside temp (Windows `\`, drive letters, `..`), because apply_update
    // runs it elevated and the checksum comes from the same manifest — so it
    // is no barrier. (Backport of Oracle 891a80f.)
    let raw = url.rsplit(['/', '\\']).next().unwrap_or("");
    let filename = if !raw.is_empty()
        && raw.ends_with(".exe")
        && raw.bytes().all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
    {
        raw
    } else {
        "update-setup.exe"
    };
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
/// B2/B3 (2026-07-03): сообщения по-русски — уходят в errorMsg блокирующего
/// оверлея обновления, клиент должен понимать, что делать.
pub fn verify_checksum(file_path: &std::path::Path, expected: &str) -> Result<()> {
    if expected.is_empty() {
        anyhow::bail!("Контрольная сумма обновления отсутствует в манифесте — установка непроверенного файла отклонена. Повторите позже или обратитесь в поддержку.");
    }

    // Strip "sha256:" prefix if present
    let expected_hash = expected.strip_prefix("sha256:").unwrap_or(expected);

    let data = std::fs::read(file_path)?;
    let hash = sha2::Sha256::digest(&data);
    let actual = hex::encode(hash);

    if actual != expected_hash.to_lowercase() {
        return Err(coded_err(ErrorCode::UP003, &format!(
            "Файл обновления повреждён при загрузке (контрольная сумма не совпала: ожидалась {}…, получена {}…). Повторите загрузку.",
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
///
/// Phase 3.1 audit fix (2026-05-23): launch ordering changed to launch-then-shutdown.
/// Previous order (shutdown-then-launch с .spawn()) had UAC-denial regression — если
/// user clicks UAC «No», PowerShell .spawn() returns Ok (PS process started OK),
/// installer never elevated, но sidecar already killed → app в dead state. Fix:
/// PowerShell .status() blocking с -ErrorAction Stop catches UAC denial → return Err
/// → app stays functional → NSIS PREINSTALL hook fires later для actual sidecar kill
/// когда installer actually extracts.
pub fn apply_update(installer_path: &std::path::Path) -> Result<()> {
    if !installer_path.exists() {
        return Err(coded_err(ErrorCode::UP004, &format!("Файл установщика не найден: {}. Повторите загрузку обновления.", installer_path.display())));
    }

    info!("Applying update: {}", installer_path.display());

    // Launch installer with elevation. Block until PowerShell confirms UAC granted +
    // installer process actually spawned. PS exits 1 если UAC denied OR Start-Process
    // fails for any other reason → we return Err, sidecar stays alive, app functional.
    let installer_str = installer_path.display().to_string().replace('\'', "''");
    let ps_status = std::process::Command::new("powershell")
        .args([
            "-NoProfile", "-Command",
            &format!(
                "try {{ Start-Process -FilePath '{}' -ArgumentList '/S' -Verb RunAs -ErrorAction Stop }} catch {{ exit 1 }}",
                installer_str
            ),
        ])
        .status()
        .map_err(|e| coded_err(ErrorCode::UP004, &format!("Failed to launch PowerShell: {e}")))?;

    if !ps_status.success() {
        return Err(coded_err(
            ErrorCode::UP004,
            "Установщик не запустился (отказ в правах администратора). Приложение продолжает работать — повторите обновление и подтвердите запрос прав.",
        ));
    }

    info!("Installer elevated successfully; stopping sidecar to release file locks");

    // PS confirmed: installer process spawned with elevation, actively extracting in background.
    // NSIS PREINSTALL hook will kill sidecar via taskkill when extraction begins — этот
    // Rust call редundant но defense-in-depth: closes race window между installer process
    // creation и NSIS PREINSTALL execution, particularly если watchdog respawn happens.
    // stop_sidecar idempotent — no-op if NSIS already killed it.
    crate::econ_sidecar::stop_sidecar();

    // Brief pause so UI can show "Installing..." state before exit
    std::thread::sleep(std::time::Duration::from_secs(2));

    // Exit current process to allow installer to replace files
    std::process::exit(0);
}

/// Check if an update is required based on server response (v2 online path).
/// Returns VersionInfo built from the online auth data.
///
/// B3-аудит (2026-07-03): фронт эту команду НЕ вызывает — путь обязательного
/// обновления идёт через heartbeat → checkFullUpdate → `check_update` (полный
/// манифест С checksum). Мост оставлен для back-compat; НЕ строить на нём
/// установку: собранный здесь VersionInfo имеет ПУСТОЙ checksum → строгий
/// verify_checksum откажет (защита от непроверенных установок).
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

/// Semver comparison с учётом prerelease: returns true if `remote` > `current`.
///
/// Старая версия делала `split('.').filter_map(parse::<u32>)` и МОЛЧА отбрасывала
/// хвост `0-rc11` → "2.1.0-rc11" и "2.1.0-rc10" оба сводились к `[2,1]` → считались
/// равными → rc→rc авто-апдейт НИКОГДА не срабатывал (баг найден на rc10→rc11,
/// 2026-06-13). Теперь база и prerelease сравниваются раздельно:
///   - stable (без `-`) ранжируется ВЫШЕ любого prerelease той же базы (rank = u32::MAX);
///   - `rc11` > `rc10` (числовой хвост тега, не лексический — иначе "rc2" > "rc10");
///   - база ("2.1.0") доминирует над prerelease-рангом.
pub(crate) fn is_newer(remote: &str, current: &str) -> bool {
    fn parse(v: &str) -> (Vec<u32>, u32) {
        let v = v.trim_start_matches('v');
        let (base, pre_rank) = match v.split_once('-') {
            Some((b, tag)) => {
                // rc11 → 11, beta3 → 3, без цифр → 0. Всегда < u32::MAX (= release).
                let n = tag
                    .chars()
                    .filter(|c| c.is_ascii_digit())
                    .collect::<String>()
                    .parse()
                    .unwrap_or(0);
                (b, n)
            }
            None => (v, u32::MAX), // нет prerelease = stable релиз
        };
        let nums = base.split('.').filter_map(|s| s.parse().ok()).collect();
        (nums, pre_rank)
    }
    parse(remote) > parse(current)
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

    /// D2: канал обновлений согласован с редакцией сборки — облачная идёт
    /// по базовому ключу, локальная по «-local» (иначе локальным клиентам
    /// приедет облачный exe с Claude-каналом — нарушение «0 egress»).
    #[test]
    fn update_channel_matches_edition() {
        let key = update_product_key();
        if cfg!(feature = "cloud_advisors") {
            assert_eq!(key, env!("CARGO_PKG_NAME"));
            assert!(!key.ends_with("-local"));
        } else {
            assert_eq!(key, format!("{}-local", env!("CARGO_PKG_NAME")));
        }
    }

    // ── B3 (2026-07-03): ворота установки — verify_checksum ──────────────────

    fn tmp_file_with(content: &[u8]) -> std::path::PathBuf {
        let p = std::env::temp_dir().join(format!(
            "aurora-test-upd-{}.bin",
            uuid::Uuid::new_v4().simple()
        ));
        std::fs::write(&p, content).unwrap();
        p
    }

    /// Корректная сумма проходит; форма с префиксом sha256: (как в живом
    /// манифесте GitHub Pages/Supabase) — тоже.
    #[test]
    fn checksum_valid_passes_with_and_without_prefix() {
        let p = tmp_file_with(b"aurora update payload");
        let hash = hex::encode(sha2::Sha256::digest(b"aurora update payload"));
        verify_checksum(&p, &hash).expect("голый hex должен проходить");
        verify_checksum(&p, &format!("sha256:{hash}")).expect("sha256:-префикс должен проходить");
        // Регистр не важен: expected нормализуется to_lowercase (манифест мог отдать верхний).
        verify_checksum(&p, &hash.to_uppercase())
            .expect("верхний регистр ожидаемой суммы должен нормализоваться и проходить");
        let _ = std::fs::remove_file(&p);
    }

    /// Повреждённый файл (сумма не совпала) → отказ UP-003 с русским сообщением.
    #[test]
    fn checksum_mismatch_rejected_up003() {
        let p = tmp_file_with(b"corrupted download");
        let wrong = hex::encode(sha2::Sha256::digest(b"original payload"));
        let err = verify_checksum(&p, &wrong).expect_err("несовпадение суммы обязано отклоняться");
        let msg = err.to_string();
        assert!(msg.contains("UP-003"), "Ожидался код UP-003: {msg}");
        assert!(msg.contains("повреждён"), "Сообщение должно быть понятным по-русски: {msg}");
        let _ = std::fs::remove_file(&p);
    }

    /// Пустая сумма в манифесте → отказ от установки непроверенного файла
    /// (строгие ворота: обязательное обновление без checksum НЕ ставится).
    #[test]
    fn checksum_empty_refused() {
        let p = tmp_file_with(b"whatever");
        let err = verify_checksum(&p, "").expect_err("пустая сумма обязана отклоняться");
        assert!(err.to_string().contains("отклонена"), "Русское сообщение: {err}");
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn version_comparison_prerelease() {
        // rc → rc одной базы: раньше оба сводились к [2,1] и считались равными (баг rc10→rc11).
        assert!(is_newer("2.1.0-rc11", "2.1.0-rc10"));
        assert!(!is_newer("2.1.0-rc10", "2.1.0-rc11"));
        assert!(!is_newer("2.1.0-rc11", "2.1.0-rc11"));
        // числовой хвост, не лексический: rc2 < rc10
        assert!(!is_newer("2.1.0-rc2", "2.1.0-rc10"));
        assert!(is_newer("2.1.0-rc10", "2.1.0-rc2"));
        // stable > любой prerelease той же базы; prerelease < stable
        assert!(is_newer("2.1.0", "2.1.0-rc11"));
        assert!(!is_newer("2.1.0-rc11", "2.1.0"));
        // числовая база доминирует над prerelease-рангом
        assert!(is_newer("2.2.0-rc1", "2.1.0-rc11"));
        assert!(is_newer("2.1.0-rc1", "2.0.0"));
    }
}
