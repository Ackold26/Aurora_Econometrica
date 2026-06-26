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
use std::sync::OnceLock;

// ── Configuration ──────────────────────────────────────────

/// Supabase Edge Functions base URL (obfuscated at compile time).
fn supabase_url() -> String {
    obfstr::obfstr!("https://quzhkfvglqmppxcrindh.supabase.co/functions/v1").to_string()
}

/// Cache validity period: 7 days in seconds.
///
/// Was 24h — слишком хрупко при прерывистой связи к Supabase: одно офлайн-окно
/// >24h роняло лицензию, если offline-файл Ed25519 не импортирован (CLOUDEAI,
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
}

/// Cached auth response stored on disk.
#[derive(Debug, Serialize, Deserialize)]
struct CachedAuth {
    response: AuthResponse,
    cached_at: u64,  // Unix timestamp
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

fn save_cache(app_config_dir: &Path, response: &AuthResponse) -> Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let cached = CachedAuth {
        response: response.clone(),
        cached_at: now,
    };
    let json = serde_json::to_string(&cached)?;
    std::fs::write(cache_path(app_config_dir), json)?;
    Ok(())
}

fn load_cache(app_config_dir: &Path) -> Option<AuthResponse> {
    let path = cache_path(app_config_dir);
    let data = std::fs::read_to_string(&path).ok()?;
    let cached: CachedAuth = serde_json::from_str(&data).ok()?;

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

    if auth_response.status == "ok" {
        // Cache successful response
        if let Err(e) = save_cache(app_config_dir, &auth_response) {
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
