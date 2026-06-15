use anyhow::Result;
use chrono::NaiveDate;
use log::warn;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

use crate::crypto::{ed25519, fingerprint};
use crate::errors::{coded, coded_err, ErrorCode};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct License {
    pub license_id: String,
    pub issued_to: String,
    pub expires_at: String,
    pub machine_fingerprint_hash: String,
    pub cabinets: Vec<String>,
    pub salt: String,       // base64-encoded
    pub signature: String,  // base64-encoded Ed25519 signature
}

#[derive(Debug, Clone, Serialize)]
pub struct LicenseStatus {
    pub valid: bool,
    pub issued_to: String,
    pub expires_at: String,
    pub days_remaining: i64,
    pub cabinets: Vec<String>,
    pub machine_id: String,
    pub error: Option<String>,
}

impl License {
    /// Load license from the per-app config directory.
    /// Primary: <app_config_dir>/license.json (per-app, Tauri v2 idiomatic)
    /// Fallback: legacy shared paths for migration
    pub fn load(app_config_dir: &Path) -> Result<Self> {
        let path = Self::resolve_license_path(app_config_dir)
            .ok_or_else(|| coded_err(ErrorCode::LI001, "License file not found. Please import your license in Settings."))?;
        let data = std::fs::read_to_string(&path)
            .map_err(|_| coded_err(ErrorCode::LI002, &format!("Cannot read license file at {}", path.display())))?;
        let license: License = serde_json::from_str(&data)?;

        // Migrate: if loaded from legacy path, copy to per-app dir
        let per_app_path = Self::license_path(app_config_dir);
        if path != per_app_path {
            if let Some(parent) = per_app_path.parent() {
                if let Err(e) = std::fs::create_dir_all(parent) {
                    warn!("Failed to create license dir {}: {e}", parent.display());
                }
            }
            if let Err(e) = std::fs::copy(&path, &per_app_path) {
                warn!("Failed to migrate license from {} to {}: {e}", path.display(), per_app_path.display());
            }
        }

        Ok(license)
    }

    /// Returns the path where license is currently stored.
    ///
    /// Primary: `<app_config_dir>/license.json` (Tauri v2 per-app idiomatic).
    ///
    /// Legacy fallbacks (`%APPDATA%\AIAgency\`, `%PROGRAMDATA%\AIAgency\`) -
    /// только с feature `legacy_aiagency_fallback`. По умолчанию включена
    /// ТОЛЬКО в AI_APP_AGENCY; в 9 форках (Econometrica, Legal, Creative и т.д.)
    /// feature отсутствует → legacy-ветки компилируются в zero-LOC.
    ///
    /// Почему: contamination из `%APPDATA%\AIAgency\license.json` (оставленной
    /// старой установкой Aurora Agency) подтягивалась в форкнутые продукты -
    /// юзер видел `Issued To: "Юрист"` в Econometrica с лицензии, которой в
    /// Supabase нет. См. memory/project_per_user_port_isolation.md.
    fn resolve_license_path(_app_config_dir: &Path) -> Option<PathBuf> {
        // 1. Per-app directory (always)
        let primary = Self::license_path(_app_config_dir);
        if primary.exists() {
            return Some(primary);
        }

        #[cfg(feature = "legacy_aiagency_fallback")]
        {
            // 2. Legacy: %APPDATA%\AIAgency\license.json
            let app_data = std::env::var("APPDATA")
                .unwrap_or_else(|_| "C:\\Users\\Default\\AppData\\Roaming".to_string());
            let legacy_appdata = PathBuf::from(app_data).join("AIAgency").join("license.json");
            if legacy_appdata.exists() {
                return Some(legacy_appdata);
            }
            // 3. Legacy: %PROGRAMDATA%\AIAgency\license.json
            let program_data = std::env::var("PROGRAMDATA")
                .unwrap_or_else(|_| "C:\\ProgramData".to_string());
            let legacy_programdata =
                PathBuf::from(program_data).join("AIAgency").join("license.json");
            if legacy_programdata.exists() {
                return Some(legacy_programdata);
            }
        }

        None
    }

    /// Per-app license path - <app_config_dir>/license.json
    pub fn license_path(app_config_dir: &Path) -> PathBuf {
        app_config_dir.join("license.json")
    }

    /// Get the salt as raw bytes.
    pub fn salt_bytes(&self) -> Result<Vec<u8>> {
        use base64::Engine;
        base64::engine::general_purpose::STANDARD
            .decode(&self.salt)
            .map_err(|e| coded_err(ErrorCode::LI004, &format!("Invalid salt base64: {e}")))
    }

    /// Canonical JSON for signature verification (all fields except signature).
    fn canonical_json(&self) -> String {
        // Deterministic JSON: sorted keys, no signature field
        format!(
            r#"{{"cabinets":{cabinets},"expires_at":"{expires}","issued_to":"{issued}","license_id":"{id}","machine_fingerprint_hash":"{fp}","salt":"{salt}"}}"#,
            cabinets = serde_json::to_string(&self.cabinets).unwrap_or_else(|_| "[]".to_string()),
            expires = self.expires_at,
            issued = self.issued_to,
            id = self.license_id,
            fp = self.machine_fingerprint_hash,
            salt = self.salt,
        )
    }

    /// Validate the license: signature, machine fingerprint, expiry.
    pub fn validate(&self) -> Result<LicenseStatus> {
        let machine_fp = fingerprint::get_machine_fingerprint()?;
        let machine_fp_hash = fingerprint::hash_fingerprint(&machine_fp);
        let machine_id_short = machine_fp_hash[..12].to_string();

        // Parse expiry early so days_remaining is available in all branches
        let expires = NaiveDate::parse_from_str(&self.expires_at, "%Y-%m-%d")
            .map_err(|_| coded_err(ErrorCode::LI008, "Invalid expiry date format"))?;
        let today = chrono::Local::now().date_naive();
        let days_remaining = (expires - today).num_days();

        // Check machine binding
        if self.machine_fingerprint_hash != machine_fp_hash {
            return Ok(LicenseStatus {
                valid: false,
                issued_to: self.issued_to.clone(),
                expires_at: self.expires_at.clone(),
                days_remaining,
                cabinets: vec![],
                machine_id: machine_id_short,
                error: Some(coded(ErrorCode::LI006, "License is bound to a different machine")),
            });
        }

        // Sanity check: system clock must not be earlier than the build date
        const BUILD_TS: &str = env!("BUILD_TIMESTAMP");
        if let Ok(ts) = BUILD_TS.parse::<i64>() {
            if let Some(build_dt) = chrono::DateTime::from_timestamp(ts, 0) {
                let build_date = build_dt.date_naive();
                if today < build_date {
                    return Ok(LicenseStatus {
                        valid: false,
                        issued_to: self.issued_to.clone(),
                        expires_at: self.expires_at.clone(),
                        days_remaining,
                        cabinets: vec![],
                        machine_id: machine_id_short,
                        error: Some(coded(ErrorCode::LI009, "Системные часы выставлены некорректно. Проверьте дату и время.")),
                    });
                }
            }
        }

        if today > expires {
            return Ok(LicenseStatus {
                valid: false,
                issued_to: self.issued_to.clone(),
                expires_at: self.expires_at.clone(),
                days_remaining,
                cabinets: vec![],
                machine_id: machine_id_short,
                error: Some(coded(ErrorCode::LI005, "License has expired")),
            });
        }

        // Check Ed25519 signature
        let canonical = self.canonical_json();
        let sig_bytes = base64::Engine::decode(
            &base64::engine::general_purpose::STANDARD,
            &self.signature,
        )
        .map_err(|e| coded_err(ErrorCode::LI007, &format!("Invalid signature base64: {e}")))?;

        let sig_valid = ed25519::verify_signature(canonical.as_bytes(), &sig_bytes)
            .unwrap_or(false);
        if !sig_valid {
            return Ok(LicenseStatus {
                valid: false,
                issued_to: self.issued_to.clone(),
                expires_at: self.expires_at.clone(),
                days_remaining,
                cabinets: vec![],
                machine_id: machine_id_short,
                error: Some(coded(ErrorCode::LI007, "License signature is invalid")),
            });
        }

        Ok(LicenseStatus {
            valid: true,
            issued_to: self.issued_to.clone(),
            expires_at: self.expires_at.clone(),
            days_remaining,
            cabinets: self.cabinets.clone(),
            machine_id: machine_id_short,
            error: None,
        })
    }
}

/// Переименовать найденный legacy license file в `.bak`, чтобы убрать его
/// из контаминации будущих диагностик. Никогда не **использует** этот файл,
/// только изолирует. Graceful fail на любых ошибках (permission, ACL).
///
/// Запускать на cold start приложения (после попытки online auth).
/// Идемпотентно: если `.bak` уже есть, не делает ничего.
pub fn quarantine_legacy_files() {
    let candidates = [
        std::env::var("APPDATA")
            .ok()
            .map(|p| PathBuf::from(p).join("AIAgency").join("license.json")),
        std::env::var("PROGRAMDATA")
            .ok()
            .map(|p| PathBuf::from(p).join("AIAgency").join("license.json")),
    ];
    for candidate in candidates.into_iter().flatten() {
        if !candidate.exists() {
            continue;
        }
        let bak = candidate.with_file_name("license.legacy.bak");
        if bak.exists() {
            // Уже quarantined - ничего не делаем
            continue;
        }
        match std::fs::rename(&candidate, &bak) {
            Ok(_) => log::info!(
                "Legacy license quarantined: {} → {}",
                candidate.display(),
                bak.display()
            ),
            Err(e) => log::debug!(
                "Quarantine skipped ({}): {e} - probably permission/ACL issue, not fatal",
                candidate.display()
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn license_verify_signature_invalid() {
        // Подпись неправильной длины - ed25519::verify_signature вернёт ошибку
        let garbage_short: &[u8] = b"not-a-real-signature";
        let result = crate::crypto::ed25519::verify_signature(b"test data", garbage_short);
        assert!(result.is_err(), "Garbage signature of wrong length should return Err");

        // Подпись правильной длины (64 байта), но невалидная - вернёт Ok(false)
        let garbage_64 = [0xABu8; 64];
        let result = crate::crypto::ed25519::verify_signature(b"test data", &garbage_64);
        assert!(result.is_ok(), "64-byte garbage should not cause Err");
        assert!(!result.unwrap(), "64-byte garbage signature should not verify as valid");
    }

    #[test]
    fn expired_subscription_license_rejected_li005() {
        // Срочная лицензия (режим годовой подписки): по истечении срока validate() обязана
        // вернуть valid=false с кодом LI005. Привязываемся к РЕАЛЬНОМУ отпечатку машины, чтобы
        // пройти проверку machine-binding (она раньше проверки срока) и дойти до неё. expires в
        // прошлом → ветка LI005 (раньше проверки подписи), поэтому подпись может быть пустой.
        // Если отпечаток недоступен в среде — тест корректно пропускается.
        let Ok(fp) = fingerprint::get_machine_fingerprint() else { return; };
        let fp_hash = fingerprint::hash_fingerprint(&fp);
        let lic = License {
            license_id: "TEST-EXPIRED".into(),
            issued_to: "Pilot Co".into(),
            expires_at: "2020-01-01".into(), // срок в прошлом
            machine_fingerprint_hash: fp_hash,
            cabinets: vec!["econometrist".into()],
            salt: String::new(),
            signature: String::new(),
        };
        let status = lic.validate().expect("validate() возвращает Ok даже для недействительных лицензий");
        let actual_err = status.error.clone().unwrap_or_default();
        // Security property: истёкшая лицензия отклонена, а срок распознан как прошедший
        // (days_remaining возвращается во всех ветках, поэтому проверка устойчива).
        assert!(!status.valid, "Истёкшая лицензия должна быть отклонена, ошибка: {actual_err:?}");
        assert!(status.days_remaining < 0, "days_remaining должен быть отрицательным для истёкшей лицензии");
        // На машине с корректными часами (сборка в прошлом) причина отказа — именно истечение
        // LI-005. В окружении, где сборка «из будущего» относительно системных часов, раньше
        // срабатывает LI-009 (anti-rollback) — это тоже корректный отказ.
        if !actual_err.contains("LI-009") {
            assert!(actual_err.contains("LI-005"), "Ожидался LI-005, фактически: {actual_err:?}");
        }
    }

    /// Без feature `legacy_aiagency_fallback` resolve_license_path НЕ должен
    /// возвращать legacy path, даже если файл реально существует.
    #[cfg(not(feature = "legacy_aiagency_fallback"))]
    #[test]
    fn resolve_license_path_no_legacy_when_feature_off() {
        // Создаём temp app_config_dir где НЕТ license.json
        let tmp = std::env::temp_dir().join(format!(
            "aurora-test-license-{}",
            uuid::Uuid::new_v4().simple()
        ));
        fs::create_dir_all(&tmp).unwrap();
        // primary не существует
        assert!(!tmp.join("license.json").exists());

        // Feature off → resolve должен вернуть None даже если legacy есть
        // (мы НЕ создаём реальный legacy в %APPDATA% чтобы не портить среду;
        // тест проверяет логику: primary нет → None без feature)
        let resolved = License::resolve_license_path(&tmp);
        assert!(
            resolved.is_none(),
            "Без feature legacy_aiagency_fallback resolve должен вернуть None"
        );

        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn quarantine_legacy_noop_if_missing() {
        // Файла нет → функция ничего не делает и не падает
        quarantine_legacy_files(); // smoke test - не должно паниковать
    }
}

/// Import a license file from a given path into the per-app config directory.
/// Verifies the license signature and machine binding before saving.
pub fn import_license(source_path: &str, app_config_dir: &Path) -> Result<()> {
    let source = PathBuf::from(source_path);
    let dest = License::license_path(app_config_dir);

    let data = std::fs::read_to_string(&source)?;
    let license: License = serde_json::from_str(&data)
        .map_err(|e| coded_err(ErrorCode::LI003, &format!("Invalid license file: {e}")))?;

    // Verify signature and machine binding before saving
    let status = license.validate()
        .map_err(|e| coded_err(ErrorCode::LI010, &format!("License validation error: {e}")))?;
    if !status.valid {
        let reason = status.error.unwrap_or("Unknown error".to_string());
        return Err(coded_err(ErrorCode::LI010, &format!("License is not valid: {reason}")));
    }

    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::copy(&source, &dest)?;
    Ok(())
}
