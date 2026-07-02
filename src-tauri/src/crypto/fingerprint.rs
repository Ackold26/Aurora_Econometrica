use anyhow::Result;
use log::info;
use sha2::{Digest, Sha256};
use std::sync::OnceLock;

use crate::errors::{coded_err, ErrorCode};

/// Cached fingerprint - WMI queries are expensive (~100ms each), called 6+ times per session.
static FINGERPRINT_CACHE: OnceLock<String> = OnceLock::new();

/// Whether a `Win32_DiskDrive` row represents a FIXED internal disk eligible to
/// contribute its serial to the machine fingerprint.
///
/// Removable / USB / FireWire media are excluded: they appear and disappear
/// between sessions, shift the Win32_DiskDrive enumeration, and would otherwise
/// silently change the selected serial → unstable fingerprint → "license not
/// found" (класс LIC-01). Три независимых сигнала, чтобы одно ошибочное поле не
/// пропустило съёмный диск: MediaType, InterfaceType, PNPDeviceID. Внутренние
/// NVMe/SATA не матчат ни один → serial типовой машины не меняется (существующие
/// лицензии целы).
#[cfg_attr(not(windows), allow(dead_code))]
fn disk_is_fixed_internal(
    media_type: Option<&str>,
    interface_type: Option<&str>,
    pnp_device_id: Option<&str>,
) -> bool {
    let removable = media_type.map_or(false, |m| {
        let m = m.to_ascii_lowercase();
        m.contains("removable") || m.contains("external")
    });
    let hot_plug_bus = interface_type.map_or(false, |i| {
        i.eq_ignore_ascii_case("USB") || i.eq_ignore_ascii_case("1394")
    });
    let usb_pnp = pnp_device_id.map_or(false, |p| {
        let p = p.to_ascii_uppercase();
        p.starts_with("USBSTOR") || p.starts_with("USB\\")
    });
    !removable && !hot_plug_bus && !usb_pnp
}

/// Collects machine-unique identifiers and produces a SHA-256 fingerprint.
/// Components: Machine UUID + Disk Serial + Motherboard Serial.
/// Result is cached after first computation (hardware doesn't change at runtime).
pub fn get_machine_fingerprint() -> Result<String> {
    if let Some(cached) = FINGERPRINT_CACHE.get() {
        return Ok(cached.clone());
    }
    let components = collect_hw_ids()?;
    let mut hasher = Sha256::new();
    for component in &components {
        hasher.update(component.as_bytes());
        hasher.update(b"|");
    }
    let hash = hasher.finalize();
    let fp = hex::encode(hash);
    let _ = FINGERPRINT_CACHE.set(fp.clone());
    Ok(fp)
}

#[cfg(windows)]
fn collect_hw_ids() -> Result<Vec<String>> {
    // Run WMI queries in a separate thread to avoid COM threading conflicts with Tauri
    std::thread::spawn(collect_hw_ids_inner)
        .join()
        .map_err(|_| coded_err(ErrorCode::FP001, "WMI thread panicked"))?
}

#[cfg(windows)]
fn collect_hw_ids_inner() -> Result<Vec<String>> {
    use serde::Deserialize;
    use wmi::{COMLibrary, WMIConnection};

    let com = COMLibrary::new().map_err(|e| coded_err(ErrorCode::FP002, &format!("COM init failed: {e}")))?;
    let wmi_con = WMIConnection::new(com).map_err(|e| coded_err(ErrorCode::FP002, &format!("WMI connect failed: {e}")))?;

    let mut ids = Vec::new();

    // Machine UUID
    #[derive(Deserialize)]
    #[serde(rename_all = "PascalCase")]
    struct CsProduct {
        #[serde(rename = "UUID")]
        uuid: String,
    }

    if let Ok(results) = wmi_con.raw_query::<CsProduct>("SELECT UUID FROM Win32_ComputerSystemProduct") {
        if let Some(item) = results.first() {
            let uuid = item.uuid.trim();
            info!("WMI UUID: {:?}", uuid);
            if !uuid.is_empty() {
                ids.push(format!("machine-uuid:{uuid}"));
            }
        }
    }

    // Disk serial (sorted by Index for deterministic selection across processes).
    // LIC-01: только FIXED внутренние диски дают serial — removable/USB media
    // сдвигают enumeration и меняют fingerprint между сессиями.
    #[derive(Deserialize)]
    #[serde(rename_all = "PascalCase")]
    struct DiskDrive {
        serial_number: Option<String>,
        index: u32,
        media_type: Option<String>,
        interface_type: Option<String>,
        #[serde(rename = "PNPDeviceID")]
        pnp_device_id: Option<String>,
    }

    let is_fixed = |d: &DiskDrive| {
        disk_is_fixed_internal(
            d.media_type.as_deref(),
            d.interface_type.as_deref(),
            d.pnp_device_id.as_deref(),
        )
    };

    if let Ok(mut results) = wmi_con.raw_query::<DiskDrive>(
        "SELECT SerialNumber, Index, MediaType, InterfaceType, PNPDeviceID FROM Win32_DiskDrive",
    ) {
        results.sort_by_key(|d| d.index);
        info!("WMI Win32_DiskDrive: {} disk(s)", results.len());
        let has_serial = |d: &DiskDrive| d.serial_number.as_ref().is_some_and(|s| !s.trim().is_empty());
        for (i, d) in results.iter().enumerate() {
            info!("  disk[{}]: Index={}, fixed={}, serial_present={}", i, d.index, is_fixed(d), has_serial(d));
        }
        // Предпочесть фиксированный внутренний диск с serial; fallback на любой
        // диск с serial, если фиксированного нет — сохраняет прежнее поведение
        // для типовой машины (внутренний уже был index 0) → лицензии целы.
        let chosen = results
            .iter()
            .find(|d| has_serial(d) && is_fixed(d))
            .or_else(|| results.iter().find(|d| has_serial(d)));
        if let Some(item) = chosen {
            let serial = item.serial_number.as_ref().unwrap().trim();
            ids.push(format!("disk-serial:{serial}"));
        }
    }

    // Motherboard serial
    #[derive(Deserialize)]
    #[serde(rename_all = "PascalCase")]
    struct BaseBoard {
        serial_number: Option<String>,
    }

    if let Ok(results) = wmi_con.raw_query::<BaseBoard>("SELECT SerialNumber FROM Win32_BaseBoard") {
        if let Some(item) = results.first() {
            if let Some(ref serial) = item.serial_number {
                let serial = serial.trim();
                info!("WMI BaseBoard serial: {:?}", serial);
                if !serial.is_empty() {
                    ids.push(format!("board-serial:{serial}"));
                }
            }
        }
    }

    if ids.is_empty() {
        return Err(coded_err(ErrorCode::FP001, "Failed to collect any hardware identifiers"));
    }

    info!("Fingerprint components ({}): {:?}", ids.len(), ids);
    Ok(ids)
}

#[cfg(target_os = "macos")]
fn collect_hw_ids() -> Result<Vec<String>> {
    let mut ids = Vec::new();

    // IOPlatformUUID via ioreg
    if let Ok(output) = std::process::Command::new("ioreg")
        .args(["-rd1", "-c", "IOPlatformExpertDevice"])
        .output()
    {
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines() {
            if line.contains("IOPlatformUUID") {
                if let Some(uuid) = line.split('"').nth(3) {
                    let uuid = uuid.trim();
                    if !uuid.is_empty() {
                        ids.push(format!("machine-uuid:{uuid}"));
                    }
                }
            }
        }
    }

    // Disk serial via diskutil
    if let Ok(output) = std::process::Command::new("diskutil")
        .args(["info", "disk0"])
        .output()
    {
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines() {
            if line.contains("Disk / Partition UUID") || line.contains("Volume UUID") {
                if let Some(serial) = line.split(':').nth(1) {
                    let serial = serial.trim();
                    if !serial.is_empty() {
                        ids.push(format!("disk-serial:{serial}"));
                        break;
                    }
                }
            }
        }
    }

    // Board serial via system_profiler
    if let Ok(output) = std::process::Command::new("system_profiler")
        .args(["SPHardwareDataType"])
        .output()
    {
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines() {
            if line.contains("Serial Number") {
                if let Some(serial) = line.split(':').nth(1) {
                    let serial = serial.trim();
                    if !serial.is_empty() {
                        ids.push(format!("board-serial:{serial}"));
                    }
                }
            }
        }
    }

    if ids.is_empty() {
        return Err(coded_err(ErrorCode::FP001, "Failed to collect any hardware identifiers on macOS"));
    }

    Ok(ids)
}

#[cfg(not(any(windows, target_os = "macos")))]
fn collect_hw_ids() -> Result<Vec<String>> {
    Err(coded_err(ErrorCode::FP003, "Machine fingerprinting is only supported on Windows and macOS"))
}

/// Return the raw fingerprint string (before hashing) for admin tooling.
/// This is the concatenation of hardware IDs that gets hashed into the machine fingerprint.
pub fn get_raw_fingerprint_hex() -> Result<String> {
    let components = collect_hw_ids()?;
    let raw = components.join("|");
    Ok(hex::encode(raw.as_bytes()))
}

/// Produce a hex-encoded SHA-256 hash of a fingerprint string (for license matching).
pub fn hash_fingerprint(fingerprint: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(fingerprint.as_bytes());
    hex::encode(hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fixed_internal_disk_passes() {
        // Внутренний NVMe/SATA — ни один сигнал removable не матчит.
        assert!(disk_is_fixed_internal(Some("Fixed hard disk media"), Some("SCSI"), Some("SCSI\\DISK&VEN")));
        // Отсутствующие поля → трактуем как fixed (fallback безопасен, лицензии целы).
        assert!(disk_is_fixed_internal(None, None, None));
    }

    #[test]
    fn removable_disk_excluded() {
        // Любого одного сигнала достаточно, чтобы исключить съёмный носитель.
        assert!(!disk_is_fixed_internal(Some("Removable Media"), None, None));
        assert!(!disk_is_fixed_internal(Some("External hard disk media"), None, None));
        assert!(!disk_is_fixed_internal(None, Some("USB"), None));
        assert!(!disk_is_fixed_internal(None, Some("1394"), None));
        assert!(!disk_is_fixed_internal(None, None, Some("USBSTOR\\DISK&VEN_SANDISK")));
        assert!(!disk_is_fixed_internal(None, None, Some("USB\\VID_...")));
    }
}
