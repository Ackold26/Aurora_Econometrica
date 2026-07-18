//! Online authorization module for Aurora AI v2.
//!
//! Checks license validity against Supabase server.
//! Falls back to offline Ed25519 validation if server is unreachable.

use anyhow::Result;
use log::{info, warn};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::crypto::fingerprint;
use crate::crypto::auth_sig;
use std::sync::OnceLock;

// ── Configuration ──────────────────────────────────────────

/// Supabase Edge Functions base URL (obfuscated at compile time).
fn supabase_url() -> String {
    obfstr::obfstr!("https://quzhkfvglqmppxcrindh.supabase.co/functions/v1").to_string()
}

/// Cache validity period: 7 days in seconds.
///
/// Was 24h — слишком хрупко при прерывистой связи к Supabase: одно офлайн-окно
/// дольше 24 ч роняло лицензию, если offline-файл Ed25519 не импортирован (CLOUDEAI,
/// 2026-06-25 — все хосты недоступны, кэш протух, LI-001). Кэш хранит серверный
/// `expires_at`; доверие ему до 7 дней переживает недельный офлайн и сохраняет
/// контроль отзыва (отозванная лицензия переспросит сервер в течение недели).
const CACHE_TTL_SECS: u64 = 7 * 24 * 60 * 60;

/// Heartbeat interval: 4 hours in seconds.
pub const HEARTBEAT_INTERVAL_SECS: u64 = 4 * 60 * 60;

/// HTTP request timeout in seconds.
const REQUEST_TIMEOUT_SECS: u64 = 15;

// ── Data structures ────────────────────────────────────────

/// Map CARGO_PKG_NAME to product identifier for the server.
pub fn detect_product() -> &'static str {
    let pkg = env!("CARGO_PKG_NAME");
    match pkg {
        "rosst-ai-legal" => "legal",
        "rosst-ai-creative" => "creative",
        "rosst-ai-media" | "rosst-media-gui" => "media",
        "rosst-ai-docmaster" => "docmaster",
        "aurora-creative-hub" => "creative-hub",
        "aurora-econometrica-gui" => "econometrica",
        _ => "agency", // ai-agency-gui and any other → agency
    }
}

/// Returns true if the current build is Aurora AI Creative Hub.
pub fn is_creative_hub() -> bool {
    detect_product() == "creative-hub"
}

/// Returns true if the current build is Aurora AI Econometrica.
pub fn is_econometrica() -> bool {
    detect_product() == "econometrica"
}

/// Request body for POST /auth.
#[derive(Debug, Serialize)]
struct AuthRequest {
    fingerprint_hash: String,
    instance_id: String,
    session_id: String,
    app_version: String,
    content_version: String,
    hostname: String,
    product: String,
    /// Аудит-след согласия на облачную обработку (облачная редакция). Отсутствует, если
    /// согласие не давалось или для редакций/продуктов без него (skip → payload как раньше).
    #[serde(skip_serializing_if = "Option::is_none")]
    consent_terms_version: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    consent_accepted_at: Option<i64>,
}

/// Request body for POST /heartbeat.
#[derive(Debug, Serialize)]
struct HeartbeatRequest {
    fingerprint_hash: String,
    instance_id: String,
    session_id: String,
}

/// Server response from /auth endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthResponse {
    pub status: String,
    #[serde(default)]
    pub cabinets: Vec<String>,
    #[serde(default)]
    pub content_version: Option<String>,
    #[serde(default)]
    pub app_min_version: String,
    #[serde(default)]
    pub checksums: serde_json::Value,
    #[serde(default)]
    pub expires_at: Option<String>,
    #[serde(default)]
    pub message: Option<String>,
    #[serde(default)]
    pub update_required: bool,
    #[serde(default)]
    pub update_url: Option<String>,
    // v3 fields (Phase 5) - optional, ignored by older clients
    #[serde(default)]
    pub vault_versions: Option<std::collections::HashMap<String, u32>>,
    #[serde(default)]
    pub vault_checksums: Option<serde_json::Value>,
    #[serde(default)]
    pub content_pack_version: Option<u32>,
    #[serde(default)]
    pub content_pack_url: Option<String>,
    #[serde(default)]
    pub content_pack_checksum: Option<String>,
    #[serde(default)]
    pub frontend_version: Option<u32>,
    #[serde(default)]
    pub frontend_url: Option<String>,
    #[serde(default)]
    pub frontend_checksum: Option<String>,
    // SEC-1: Ed25519 signature of the "ok" response (AUTHSIG-v1 payload). Empty = server
    // does not sign yet (legacy/rollout). See crypto/auth_sig.rs.
    #[serde(default)]
    pub signature: String,
}

/// Cached auth response stored on disk.
#[derive(Debug, Serialize, Deserialize)]
struct CachedAuth {
    response: AuthResponse,
    cached_at: u64,  // Unix timestamp
    /// SEC-1: raw product the client sent when this response was signed by the server —
    /// needed to rebuild the AUTHSIG-v1 payload for signature re-verification at load time.
    /// Empty string = legacy cache written before signature re-verification (accepted, soft).
    #[serde(default)]
    product: String,
}

/// Server response from /heartbeat endpoint.
#[derive(Debug, Serialize, Deserialize)]
pub struct HeartbeatResponse {
    pub status: String,
    #[serde(default)]
    pub content_version: Option<String>,
    #[serde(default)]
    pub app_min_version: String,
}

/// Combined online auth status returned to the frontend.
#[derive(Debug, Clone, Serialize)]
pub struct OnlineAuthStatus {
    pub available: bool,          // true if server responded
    pub status: String,           // "ok", "blocked", "cached", "offline"
    pub cabinets: Vec<String>,
    pub content_version: Option<String>,
    pub app_min_version: String,
    pub expires_at: Option<String>,
    pub machine_id: String,
    pub message: Option<String>,
    pub update_required: bool,
    pub update_url: Option<String>,
    // v3 fields (Phase 5)
    pub vault_versions: Option<std::collections::HashMap<String, u32>>,
    pub content_pack_version: Option<u32>,
    pub content_pack_url: Option<String>,
    pub content_pack_checksum: Option<String>,
    pub frontend_version: Option<u32>,
    pub frontend_url: Option<String>,
    pub frontend_checksum: Option<String>,
}

// ── Session ID (per-launch, NOT persisted) ────────────────

/// Unique session ID generated once per application launch.
/// Used by the server to count concurrent sessions on the same machine.
static SESSION_ID: OnceLock<String> = OnceLock::new();

pub fn get_session_id() -> String {
    SESSION_ID
        .get_or_init(|| {
            let id = uuid::Uuid::new_v4().to_string();
            info!("Generated session ID: {}", &id[..8]);
            id
        })
        .clone()
}

// ── Instance ID ────────────────────────────────────────────

/// Get or create a persistent instance ID (UUID v4).
/// Stored in `<app_config_dir>/instance.id`.
pub fn get_or_create_instance_id(app_config_dir: &Path) -> Result<String> {
    let path = app_config_dir.join("instance.id");

    if path.exists() {
        let id = std::fs::read_to_string(&path)?.trim().to_string();
        if !id.is_empty() {
            return Ok(id);
        }
    }

    let id = uuid::Uuid::new_v4().to_string();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, &id)?;
    info!("Generated new instance ID: {}", &id[..8]);
    Ok(id)
}

// ── Cache ──────────────────────────────────────────────────

fn cache_path(app_config_dir: &Path) -> PathBuf {
    app_config_dir.join("session_cache.json")
}

/// SEC-1 (A1): статус срока действия подписанной лицензии.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ExpiryStatus {
    Valid,
    Expired,
    Missing,
}

/// Разбирает серверный expires_at (RFC3339) и сравнивает с текущим временем.
/// Missing = пусто/None/непарсимое (для подписанного "ok" это аномалия — нет границы срока).
fn license_expiry_status(expires_at: Option<&str>, now_unix: u64) -> ExpiryStatus {
    match expires_at {
        None => ExpiryStatus::Missing,
        Some("") => ExpiryStatus::Missing,
        Some(s) => match chrono::DateTime::parse_from_rfc3339(s) {
            Ok(dt) => {
                if dt.timestamp() < now_unix as i64 {
                    ExpiryStatus::Expired
                } else {
                    ExpiryStatus::Valid
                }
            }
            Err(_) => ExpiryStatus::Missing,
        },
    }
}

/// SEC-1: true if a cached response's recorded product differs from the CURRENT binary's
/// product — i.e. `session_cache.json` was carried over from a different Aurora product on
/// this machine (fingerprint matches, since it's the same machine — only the product differs).
/// Without this check, `load_cache` rebuilds the signed payload from `cached.product` (not the
/// running binary's product), so the re-verified signature still passes even though the wrong
/// product is loading someone else's cached grant. Empty `cached_product` = legacy cache
/// (written before this field existed) → not a mismatch, accepted for backward compatibility.
fn cache_product_mismatch(cached_product: &str, current_product: &str) -> bool {
    !cached_product.is_empty() && cached_product != current_product
}

fn save_cache(app_config_dir: &Path, response: &AuthResponse, product: &str) -> Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let cached = CachedAuth {
        response: response.clone(),
        cached_at: now,
        product: product.to_string(),
    };
    let json = serde_json::to_string(&cached)?;
    std::fs::write(cache_path(app_config_dir), json)?;
    Ok(())
}

fn load_cache(app_config_dir: &Path) -> Option<AuthResponse> {
    let path = cache_path(app_config_dir);
    let data = std::fs::read_to_string(&path).ok()?;
    let cached: CachedAuth = serde_json::from_str(&data).ok()?;

    // SEC-1: reject cache carried over from a DIFFERENT Aurora product on this machine —
    // fingerprint alone does not catch this (same machine, different product binary).
    let current_product = detect_product();
    if cache_product_mismatch(&cached.product, current_product) {
        match auth_sig::AUTH_SIG_ENFORCEMENT {
            auth_sig::Enforcement::Soft => {
                log::warn!(
                    "SEC-1: cache product mismatch (cached={}, binary={}) — принят (soft)",
                    cached.product, current_product
                );
            }
            auth_sig::Enforcement::Hard => {
                log::error!(
                    "SEC-1: cache product mismatch (cached={}, binary={}) — кэш отклонён (hard), нужен перезапрос онлайн",
                    cached.product, current_product
                );
                return None;
            }
        }
    }

    let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs();
    // Future-dated cached_at (часы сдвинуты назад / подделка файла кэша) — аномалия:
    // REJECT (форсим реальную перепроверку; offline Ed25519 ниже). Прямое вычитание
    // u64 паниковало бы в debug при cached_at > now (в release wrap > TTL отвергал
    // случайно). Mirror канона aurora_fleet (underflow guard) — не доверяем будущему кэшу.
    if cached.cached_at > now {
        return None;
    }
    if now - cached.cached_at > CACHE_TTL_SECS {
        info!("Auth cache expired (age: {}h)", (now - cached.cached_at) / 3600);
        return None;
    }

    // SEC-1: re-verify server signature against the CURRENT machine fingerprint — catches a
    // same-machine forge of session_cache.json (the forged file cannot carry a valid
    // signature without the server's private key).
    let current_fp_hash = fingerprint::get_machine_fingerprint()
        .map(|fp| fingerprint::hash_fingerprint(&fp))
        .unwrap_or_default();
    let auth_payload = auth_sig::build_auth_payload(
        &cached.response.status,
        &current_fp_hash,
        &cached.product,
        &cached.response.cabinets,
        cached.response.content_version.as_deref(),
        cached.response.expires_at.as_deref(),
    );
    let sig_ok = auth_sig::verify_auth_signature(&auth_payload, &cached.response.signature);
    match auth_sig::AUTH_SIG_ENFORCEMENT {
        auth_sig::Enforcement::Soft => {
            if cached.response.signature.is_empty() {
                log::info!("SEC-1: кэш без подписи (legacy/rollout) — принят (soft)");
            } else if !sig_ok {
                log::error!("SEC-1: кэш содержит подпись, но она НЕ валидна — принят (soft), требует разбора");
            } else {
                log::debug!("SEC-1: подпись кэша валидна");
            }
        }
        auth_sig::Enforcement::Hard => {
            if !sig_ok {
                log::error!("SEC-1: подпись кэша невалидна/отсутствует — кэш отклонён (hard), нужен перезапрос онлайн");
                return None;
            }
        }
    }

    // SEC-1 (A1): enforce expires_at against TTL alone not being enough — an online-replayed
    // signed "ok" could otherwise live in the cache until CACHE_TTL_SECS even after expiry.
    let expiry = license_expiry_status(cached.response.expires_at.as_deref(), now);
    match auth_sig::AUTH_SIG_ENFORCEMENT {
        auth_sig::Enforcement::Soft => match expiry {
            ExpiryStatus::Valid => log::debug!("SEC-1: кэш expires_at в силе"),
            ExpiryStatus::Expired => log::error!("SEC-1: кэш с истёкшим expires_at — принят (soft)"),
            ExpiryStatus::Missing => log::error!("SEC-1: кэш без expires_at — принят (soft)"),
        },
        auth_sig::Enforcement::Hard => {
            if expiry != ExpiryStatus::Valid {
                log::error!("SEC-1: кэш истёк или без expires_at — кэш отклонён (hard), нужен перезапрос онлайн");
                return None;
            }
        }
    }

    info!("Using cached auth response (age: {}m)", (now - cached.cached_at) / 60);
    Some(cached.response)
}

// ── HTTP helpers ───────────────────────────────────────────

fn build_client() -> Result<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(REQUEST_TIMEOUT_SECS))
        .build()?)
}

// ── Main auth flow ─────────────────────────────────────────

/// Attempt online authorization against Supabase.
/// Returns Ok(AuthResponse) on success, or Err if server unreachable.
pub async fn check_auth(
    app_config_dir: &Path,
    app_version: &str,
    content_version: &str,
) -> Result<AuthResponse> {
    let fp = fingerprint::get_machine_fingerprint()?;
    let fp_hash = fingerprint::hash_fingerprint(&fp);
    let instance_id = get_or_create_instance_id(app_config_dir)?;

    let hostname = std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .unwrap_or_default();

    // Аудит-след согласия на облачную обработку: читаем зафиксированное согласие из
    // durable-конфига и прикладываем к auth-запросу (сервер пишет в audit_log).
    let (consent_terms_version, consent_accepted_at) =
        match crate::commands::user_config::load(app_config_dir).cloud_consent {
            Some(c) => (Some(c.terms_version), Some(c.accepted_at)),
            None => (None, None),
        };

    let req = AuthRequest {
        fingerprint_hash: fp_hash,
        instance_id,
        session_id: get_session_id(),
        app_version: app_version.to_string(),
        content_version: content_version.to_string(),
        hostname,
        product: detect_product().to_string(),
        consent_terms_version,
        consent_accepted_at,
    };

    let client = build_client()?;
    let url = format!("{}/auth", supabase_url());

    info!("Online auth: POST {}", url);

    let res = client
        .post(&url)
        .json(&req)
        .send()
        .await?;

    let status_code = res.status();
    let body = res.text().await?;

    let auth_response: AuthResponse = serde_json::from_str(&body)
        .map_err(|e| anyhow::anyhow!("Failed to parse auth response: {e}, body: {body}"))?;

    // SEC-1: verify server signature of the "ok" response before trusting it.
    // fp_hash / req.product were moved into `req` above — read them back from `req` (not
    // consumed by `.json(&req)`, which only borrows it), matching what the server signed
    // (server-side product migration must not affect the signed payload).
    if auth_response.status == "ok" {
        let auth_payload = auth_sig::build_auth_payload(
            &auth_response.status,
            &req.fingerprint_hash,
            &req.product,
            &auth_response.cabinets,
            auth_response.content_version.as_deref(),
            auth_response.expires_at.as_deref(),
        );
        let sig_ok = auth_sig::verify_auth_signature(&auth_payload, &auth_response.signature);
        match auth_sig::AUTH_SIG_ENFORCEMENT {
            auth_sig::Enforcement::Soft => {
                if auth_response.signature.is_empty() {
                    log::info!("SEC-1: /auth 'ok' без подписи (rollout) — принят (soft)");
                } else if !sig_ok {
                    log::error!("SEC-1: /auth подпись присутствует, но НЕ валидна — принят (soft), требует разбора");
                } else {
                    log::debug!("SEC-1: /auth подпись валидна");
                }
            }
            auth_sig::Enforcement::Hard => {
                if !sig_ok {
                    log::error!("SEC-1: /auth подпись невалидна/отсутствует — ОТКАЗ (hard)");
                    return Err(anyhow::anyhow!("SEC-1: /auth response signature invalid or missing"));
                }
            }
        }

        // SEC-1 (A1): enforce expires_at — a signed "ok" with an expired/missing bound must
        // not be trusted forever; TTL alone (load_cache) does not cover a live online replay.
        let now_unix = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        let expiry = license_expiry_status(auth_response.expires_at.as_deref(), now_unix);
        match auth_sig::AUTH_SIG_ENFORCEMENT {
            auth_sig::Enforcement::Soft => match expiry {
                ExpiryStatus::Valid => log::debug!("SEC-1: /auth expires_at в силе"),
                ExpiryStatus::Expired => log::error!("SEC-1: /auth подписанный 'ok' с истёкшим expires_at — принят (soft)"),
                ExpiryStatus::Missing => log::error!("SEC-1: /auth подписанный 'ok' без expires_at — принят (soft)"),
            },
            auth_sig::Enforcement::Hard => {
                if expiry != ExpiryStatus::Valid {
                    log::error!("SEC-1: /auth лицензия истекла или без expires_at — ОТКАЗ (hard)");
                    return Err(anyhow::anyhow!("SEC-1: license expired or missing expires_at"));
                }
            }
        }
    }

    if auth_response.status == "ok" {
        // Cache successful response
        if let Err(e) = save_cache(app_config_dir, &auth_response, &req.product) {
            warn!("Failed to cache auth response: {e}");
        }
        info!("Online auth: OK, cabinets: {:?}", auth_response.cabinets);
    } else {
        warn!("Online auth: {} (HTTP {}): {:?}",
            auth_response.status, status_code,
            auth_response.message);
    }

    Ok(auth_response)
}

/// Full auth flow: try online → fallback to cache → return status.
/// Does NOT fall back to Ed25519 (that's handled by the caller in lib.rs).
pub async fn authorize(
    app_config_dir: &Path,
    app_version: &str,
    content_version: &str,
) -> OnlineAuthStatus {
    let machine_id = fingerprint::get_machine_fingerprint()
        .map(|fp| {
            let hash = fingerprint::hash_fingerprint(&fp);
            hash[..12].to_string()
        })
        .unwrap_or_else(|_| "unknown".to_string());

    // Try online auth
    match check_auth(app_config_dir, app_version, content_version).await {
        Ok(resp) => {
            if resp.status == "ok" {
                OnlineAuthStatus {
                    available: true,
                    status: "ok".to_string(),
                    cabinets: resp.cabinets,
                    content_version: resp.content_version,
                    app_min_version: resp.app_min_version,
                    expires_at: resp.expires_at,
                    machine_id,
                    message: None,
                    update_required: resp.update_required,
                    update_url: resp.update_url,
                    vault_versions: resp.vault_versions,
                    content_pack_version: resp.content_pack_version,
                    content_pack_url: resp.content_pack_url,
                    content_pack_checksum: resp.content_pack_checksum,
                    frontend_version: resp.frontend_version,
                    frontend_url: resp.frontend_url,
                    frontend_checksum: resp.frontend_checksum,
                }
            } else {
                // Server responded but denied access
                OnlineAuthStatus {
                    available: true,
                    status: resp.status,
                    cabinets: vec![],
                    content_version: None,
                    app_min_version: resp.app_min_version,
                    expires_at: None,
                    machine_id,
                    message: resp.message,
                    update_required: false,
                    update_url: None,
                    vault_versions: None,
                    content_pack_version: None,
                    content_pack_url: None,
                    content_pack_checksum: None,
                    frontend_version: None,
                    frontend_url: None,
                    frontend_checksum: None,
                }
            }
        }
        Err(e) => {
            warn!("Online auth failed: {e}");

            // Try cache
            if let Some(cached) = load_cache(app_config_dir) {
                info!("Using cached auth (server unreachable)");
                OnlineAuthStatus {
                    available: false,
                    status: "cached".to_string(),
                    cabinets: cached.cabinets,
                    content_version: cached.content_version,
                    app_min_version: cached.app_min_version,
                    expires_at: cached.expires_at,
                    machine_id,
                    message: Some("Работа по кэшу (сервер недоступен)".to_string()),
                    update_required: cached.update_required,
                    update_url: cached.update_url,
                    vault_versions: cached.vault_versions,
                    content_pack_version: cached.content_pack_version,
                    content_pack_url: cached.content_pack_url,
                    content_pack_checksum: cached.content_pack_checksum,
                    frontend_version: cached.frontend_version,
                    frontend_url: cached.frontend_url,
                    frontend_checksum: cached.frontend_checksum,
                }
            } else {
                // No cache - caller should try offline Ed25519
                OnlineAuthStatus {
                    available: false,
                    status: "offline".to_string(),
                    cabinets: vec![],
                    content_version: None,
                    app_min_version: "0.3.2".to_string(),
                    expires_at: None,
                    machine_id,
                    message: Some("Сервер недоступен, кэш отсутствует".to_string()),
                    update_required: false,
                    update_url: None,
                    vault_versions: None,
                    content_pack_version: None,
                    content_pack_url: None,
                    content_pack_checksum: None,
                    frontend_version: None,
                    frontend_url: None,
                    frontend_checksum: None,
                }
            }
        }
    }
}

// ── Tests (B2 2026-07-03: матрица офлайн-кэша) ─────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp_dir() -> PathBuf {
        let d = std::env::temp_dir().join(format!(
            "aurora-test-cache-{}",
            uuid::Uuid::new_v4().simple()
        ));
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn sample_response() -> AuthResponse {
        serde_json::from_str(
            r#"{"status":"ok","cabinets":["econometrist"],"app_min_version":"0.1.0","checksums":{}}"#,
        )
        .unwrap()
    }

    /// Батч 0 (2026-07-13): сервер шлёт `vault_versions` per-cabinet в /auth (Phase 5) -
    /// проверяем, что старые клиенты (без этого поля в ответе) не падают на десериализации
    /// (`#[serde(default)]`), а новые корректно читают карту версий.
    #[test]
    fn auth_response_deserializes_vault_versions() {
        let json = r#"{"status":"ok","cabinets":["econometrist"],"app_min_version":"0.1.0",
            "checksums":{},"vault_versions":{"econometrist":5,"media-analyst":2}}"#;
        let resp: AuthResponse = serde_json::from_str(json).unwrap();
        let versions = resp.vault_versions.expect("vault_versions must deserialize");
        assert_eq!(versions.get("econometrist"), Some(&5));
        assert_eq!(versions.get("media-analyst"), Some(&2));
    }

    /// Обратная совместимость: сервер БЕЗ vault_versions (старая версия Edge Function) -
    /// поле обязано остаться None, а не падать на missing field.
    #[test]
    fn auth_response_missing_vault_versions_defaults_none() {
        let resp = sample_response();
        assert_eq!(resp.vault_versions, None);
    }

    fn write_cache_with_age(dir: &Path, cached_at: u64) {
        let cached = CachedAuth { response: sample_response(), cached_at, product: String::new() };
        std::fs::write(cache_path(dir), serde_json::to_string(&cached).unwrap()).unwrap();
    }

    /// Свежий кэш (после успешной онлайн-активации) читается — офлайн-окно
    /// до 7 дней не роняет лицензию (сценарий «офлайн fallback, кэш есть»).
    #[test]
    fn cache_roundtrip_fresh_ok() {
        let dir = tmp_dir();
        save_cache(&dir, &sample_response(), "econometrica").unwrap();
        let loaded = load_cache(&dir).expect("свежий кэш должен читаться");
        assert_eq!(loaded.status, "ok");
        assert_eq!(loaded.cabinets, vec!["econometrist".to_string()]);
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Протухший кэш (старше 7 дней) отвергается → caller уйдёт в Ed25519.
    /// Контроль отзыва: отозванная лицензия не живёт на кэше дольше недели.
    #[test]
    fn cache_expired_ttl_rejected() {
        let dir = tmp_dir();
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        write_cache_with_age(&dir, now - CACHE_TTL_SECS - 60);
        assert!(load_cache(&dir).is_none(), "кэш старше TTL обязан отвергаться");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Перевод часов назад / подделка кэша: cached_at в будущем → REJECT
    /// (anti-rollback guard; прямое вычитание u64 паниковало бы в debug).
    #[test]
    fn cache_future_dated_rejected() {
        let dir = tmp_dir();
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        write_cache_with_age(&dir, now + 3600);
        assert!(load_cache(&dir).is_none(), "кэш из будущего обязан отвергаться");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Кэша нет → None (caller уходит в offline Ed25519) — без паники.
    #[test]
    fn cache_missing_none() {
        let dir = tmp_dir();
        assert!(load_cache(&dir).is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Повреждённый кэш-файл → graceful None, не падение приложения.
    #[test]
    fn cache_corrupted_graceful_none() {
        let dir = tmp_dir();
        std::fs::write(cache_path(&dir), b"{ broken json").unwrap();
        assert!(load_cache(&dir).is_none(), "битый кэш обязан отвергаться молча");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// instance.id: создаётся один раз и переживает повторные вызовы
    /// (сценарий «переустановка»: config-dir сохраняется → id стабилен).
    #[test]
    fn instance_id_stable_across_calls() {
        let dir = tmp_dir();
        let a = get_or_create_instance_id(&dir).unwrap();
        let b = get_or_create_instance_id(&dir).unwrap();
        assert_eq!(a, b, "instance.id обязан быть стабильным");
        assert!(!a.is_empty());
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// B2 «активация онлайн» полу-боем: authorize() против ЖИВОГО Supabase
    /// с чистым config-dir. #[ignore] — сетевой, гонять вручную:
    /// `cargo test online_auth_live -- --ignored --nocapture`.
    /// Ожидания: сервер ответил (status ok|blocked|denied — известный),
    /// либо офлайн-деградация в «offline» без паники. На машине с
    /// зарегистрированным fingerprint (машина Антона) — status=ok + cabinets.
    #[test]
    #[ignore = "network: живой Supabase, гонять вручную"]
    fn online_auth_live_roundtrip() {
        let dir = tmp_dir();
        let rt = tokio::runtime::Runtime::new().unwrap();
        let status = rt.block_on(authorize(&dir, env!("CARGO_PKG_VERSION"), ""));
        eprintln!(
            "online-live: available={} status={} cabinets={:?} msg={:?}",
            status.available, status.status, status.cabinets, status.message
        );
        let known = ["ok", "cached", "offline", "blocked", "denied", "unknown_machine"];
        assert!(
            known.contains(&status.status.as_str()),
            "Неизвестный статус авторизации: {}", status.status
        );
        if status.status == "ok" {
            assert!(!status.cabinets.is_empty(), "При ok сервер обязан вернуть кабинеты");
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    // ── SEC-1 (A1): license_expiry_status ────────────────────

    /// Future expires_at must be Valid.
    #[test]
    fn license_expiry_valid_future() {
        let now_unix = 1_800_000_000u64; // ~2027
        assert_eq!(
            license_expiry_status(Some("2099-01-01T00:00:00Z"), now_unix),
            ExpiryStatus::Valid
        );
    }

    /// Past expires_at must be Expired.
    #[test]
    fn license_expiry_expired_past() {
        let now_unix = 1_800_000_000u64;
        assert_eq!(
            license_expiry_status(Some("2020-01-01T00:00:00Z"), now_unix),
            ExpiryStatus::Expired
        );
    }

    /// None expires_at must be Missing (no boundary at all).
    #[test]
    fn license_expiry_missing_none() {
        let now_unix = 1_800_000_000u64;
        assert_eq!(license_expiry_status(None, now_unix), ExpiryStatus::Missing);
    }

    /// Empty-string expires_at must be Missing.
    #[test]
    fn license_expiry_missing_empty() {
        let now_unix = 1_800_000_000u64;
        assert_eq!(license_expiry_status(Some(""), now_unix), ExpiryStatus::Missing);
    }

    /// Unparseable expires_at must be Missing (no valid boundary), not a panic.
    #[test]
    fn license_expiry_unparseable() {
        let now_unix = 1_800_000_000u64;
        assert_eq!(license_expiry_status(Some("garbage"), now_unix), ExpiryStatus::Missing);
    }

    /// SEC-1 (A1) regression: the REAL server format is RFC3339 with fractional seconds AND a
    /// numeric offset (`+00:00`), not `Z` — e.g. license.expires_at = "2029-04-04T23:53:07.549+00:00".
    /// If parse_from_rfc3339 rejected it, license_expiry_status → Missing → Hard would refuse ALL
    /// valid licenses. This pins that the real format parses to Valid/Expired, never Missing.
    #[test]
    fn license_expiry_real_server_format() {
        let now_unix = 1_800_000_000u64; // ~2027-01
        assert_eq!(
            license_expiry_status(Some("2029-04-04T23:53:07.549+00:00"), now_unix),
            ExpiryStatus::Valid,
            "реальный формат сервера (ms + числовой offset) должен парситься как Valid, не Missing"
        );
        assert_eq!(
            license_expiry_status(Some("2021-06-08T12:30:00.123+00:00"), now_unix),
            ExpiryStatus::Expired,
            "истёкший в реальном формате сервера должен быть Expired"
        );
    }

    // ── SEC-1 (cache-product fix): cache_product_mismatch ────

    /// Different product recorded in cache vs current binary → mismatch.
    #[test]
    fn cache_product_mismatch_detected() {
        assert!(cache_product_mismatch("media", "econometrica"));
    }

    /// Same product → no mismatch.
    #[test]
    fn cache_product_match_no_mismatch() {
        assert!(!cache_product_mismatch("econometrica", "econometrica"));
    }

    /// Empty cached product = legacy cache (written before this field existed) → accepted,
    /// not treated as a mismatch.
    #[test]
    fn cache_product_empty_legacy_no_mismatch() {
        assert!(!cache_product_mismatch("", "econometrica"));
    }
}

// ── Heartbeat ──────────────────────────────────────────────

/// Send heartbeat to server. Returns updated content/app versions if available.
pub async fn send_heartbeat(app_config_dir: &Path) -> Result<HeartbeatResponse> {
    let fp = fingerprint::get_machine_fingerprint()?;
    let fp_hash = fingerprint::hash_fingerprint(&fp);
    let instance_id = get_or_create_instance_id(app_config_dir)?;

    let req = HeartbeatRequest {
        fingerprint_hash: fp_hash,
        instance_id,
        session_id: get_session_id(),
    };

    let client = build_client()?;
    let url = format!("{}/heartbeat", supabase_url());

    let res = client
        .post(&url)
        .json(&req)
        .send()
        .await?;

    let body = res.text().await?;
    let response: HeartbeatResponse = serde_json::from_str(&body)?;

    info!("Heartbeat: status={}", response.status);
    Ok(response)
}
