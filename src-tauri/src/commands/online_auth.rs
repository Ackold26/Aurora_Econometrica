//! Online authorization module for Aurora AI v2.
//!
//! Checks license validity against Supabase server.
//! Falls back to offline Ed25519 validation if server is unreachable.

use anyhow::Result;
use log::{error, info, warn};
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
/// дольше 24 ч роняло лицензию, если offline-файл Ed25519 не импортирован (CLOUDEAI,
/// 2026-06-25 — все хосты недоступны, кэш протух, LI-001). Кэш хранит серверный
/// `expires_at`; доверие ему до 7 дней переживает недельный офлайн и сохраняет
/// контроль отзыва (отозванная лицензия переспросит сервер в течение недели).
const CACHE_TTL_SECS: u64 = 7 * 24 * 60 * 60;

/// Срок доверия кэшу, подпись которого НЕ подтверждена (CPD-40, часть A-3).
///
/// Полные семь дней — плата за офлайн при ПОДТВЕРЖДЁННОЙ подписи. Ответ без подписи бывает
/// законным (сервер не подписал — ровно так отвечает сервер локальной редакции, проверено на
/// живом кэше `com.aurora.econometrica.local`), поэтому запрещать такой кэш совсем нельзя: у
/// людей отвалится офлайн. Но и доверять ему неделю нельзя: посредник, поднятый на полминуты,
/// оставляет поддельный грант, который переживает его уход. Сутки — компромисс: офлайн-день
/// сохранён, подделка не живёт неделю и тем более не становится бессрочной.
const CACHE_TTL_UNVERIFIED_SECS: u64 = 24 * 60 * 60;

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
    /// Подпись ответа нашим ключом (`AUTHSIG-v1`). Сервер её уже отдаёт; прежде
    /// продукт поле не объявлял, и оно молча терялось при разборе — а без него
    /// облачная поставка не может собрать билет доступа, потому что билет и ЕСТЬ
    /// подписанный ответ входа.
    #[serde(default)]
    pub signature: String,
}

/// Cached auth response stored on disk.
#[derive(Debug, Serialize, Deserialize)]
struct CachedAuth {
    response: AuthResponse,
    cached_at: u64,  // Unix timestamp
    /// CPD-40 (A-3): подтвердилась ли подпись сервера в момент записи кэша.
    ///
    /// Отсутствие поля (кэш, записанный прежней версией продукта) читается как `false` — то есть
    /// прежний кэш живёт по короткому сроку. Сторона сознательно мягкая: при первом же успешном
    /// входе онлайн кэш перезаписывается с подтверждением и снова получает полный срок.
    #[serde(default)]
    sig_verified: bool,
}

/// Что делать с ответом входа в зависимости от исхода проверки подписи (CPD-40, A-3).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CachePolicy {
    /// Подпись сошлась — полное доверие, полный срок кэша.
    Verified,
    /// Подписи нет вовсе: сервер не подписывает (раскатка) либо не смог подписать.
    /// Кэшируем, но на короткий срок — законный офлайн сохраняем, окно подделки режем.
    Unverified,
    /// Подпись ЕСТЬ и не сходится. Законного источника у такого ответа нет: сервер либо
    /// подписывает верно, либо не подписывает вовсе. Доступ в мягком режиме выдаём
    /// (мягкость — принятое решение), но на диск не пишем: подделка не переживёт сессию.
    Reject,
}

/// Решение о кэшировании ответа входа. Чистая функция — проверяется тестами напрямую.
fn cache_policy(signature: &str, sig_ok: bool) -> CachePolicy {
    if sig_ok {
        CachePolicy::Verified
    } else if signature.is_empty() {
        CachePolicy::Unverified
    } else {
        CachePolicy::Reject
    }
}

/// Срок доверия кэшу по признаку подтверждённой подписи (CPD-40, A-3). Чистая функция.
fn cache_ttl_secs(sig_verified: bool) -> u64 {
    if sig_verified {
        CACHE_TTL_SECS
    } else {
        CACHE_TTL_UNVERIFIED_SECS
    }
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
    /// Контрольные суммы vault-файлов от сервера (filename → hash), прокинутые
    /// из `AuthResponse::vault_checksums` без изменений. Поле объявлялось в
    /// `AuthResponse`, но терялось при сборке `OnlineAuthStatus` во всех ветках
    /// `authorize()` — сверка целостности при автоматической докачке была мертва
    /// целиком. См. `content_updater::normalize_checksum` для разбора формата
    /// (сервер этого продукта шлёт голый hex, без префикса `sha256:`).
    pub vault_checksums: Option<serde_json::Value>,
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

fn save_cache(app_config_dir: &Path, response: &AuthResponse, sig_verified: bool) -> Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let cached = CachedAuth {
        response: response.clone(),
        cached_at: now,
        sig_verified,
    };
    let json = serde_json::to_string(&cached)?;
    // Находка внешнего аудита (Info): запись была не атомарной — обрыв посреди неё оставлял
    // битый JSON, то есть отнимал офлайн у честного пользователя. Пишем во временный файл и
    // переименовываем (INV-42, тот же приём, что у эталона линейки).
    let path = cache_path(app_config_dir);
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, json)?;
    std::fs::rename(&tmp, &path)?;
    Ok(())
}

/// Приговор сохранённому ответу (CPD-40, находка внешнего аудита B-1). Чистая функция:
/// признак «подпись сошлась» приходит снаружи, поэтому все ветки проверяются без боевого ключа.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CacheVerdict {
    /// Годен, срок доверия — полный (подпись сошлась ЗДЕСЬ И СЕЙЧАС).
    AcceptVerified,
    /// Годен, но коротко: подписи в ответе нет вовсе (законный путь, так отвечает сервер
    /// локальной редакции).
    AcceptUnverified,
    /// Подпись ЕСТЬ и не сходится — сохранённый ответ подделан либо принадлежит другой машине.
    Forged,
}

/// Решение по сохранённому ответу. `sig_ok` вычисляется вызывающим — здесь только правило.
fn cache_verdict(signature: &str, sig_ok: bool) -> CacheVerdict {
    if sig_ok {
        CacheVerdict::AcceptVerified
    } else if signature.is_empty() {
        CacheVerdict::AcceptUnverified
    } else {
        CacheVerdict::Forged
    }
}

/// Сошлась ли подпись СОХРАНЁННОГО ответа на этой машине прямо сейчас.
///
/// 🔴 Отпечаток берётся живой, а продукт — из сборки: подменённый файл, снятый с другой машины
/// или из другого продукта линейки, подписи не даст. Отпечаток считается один раз за запуск
/// (`FINGERPRINT_CACHE`), поэтому проверка при каждом чтении кэша бесплатна.
fn cached_signature_matches(response: &AuthResponse) -> bool {
    let Ok(fp) = fingerprint::get_machine_fingerprint() else {
        return false;
    };
    let fp_hash = fingerprint::hash_fingerprint(&fp);
    let payload = crate::crypto::auth_sig::build_auth_payload(
        &response.status,
        &fp_hash,
        detect_product(),
        &response.cabinets,
        response.content_version.as_deref(),
        response.expires_at.as_deref(),
    );
    crate::crypto::auth_sig::verify_auth_signature(&payload, &response.signature)
}

/// Прочитать сохранённый ответ, если он ещё годен. Возвращает его вместе с
/// возрастом в секундах. Молча: сообщения пишет тот, кто кэш применяет.
fn read_fresh_cache(app_config_dir: &Path) -> Option<(AuthResponse, u64)> {
    let path = cache_path(app_config_dir);
    let data = std::fs::read_to_string(&path).ok()?;
    let mut cached: CachedAuth = serde_json::from_str(&data).ok()?;

    let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs();
    // Future-dated cached_at (часы сдвинуты назад / подделка файла кэша) — аномалия:
    // REJECT (форсим реальную перепроверку; offline Ed25519 ниже). Прямое вычитание
    // u64 паниковало бы в debug при cached_at > now (в release wrap > TTL отвергал
    // случайно). Mirror канона aurora_fleet (underflow guard) — не доверяем будущему кэшу.
    if cached.cached_at > now {
        return None;
    }
    let age = now - cached.cached_at;

    // 🔴 CPD-40, находка внешнего аудита (High): доверие не имеет права держаться на признаке,
    // лежащем в ТОМ ЖЕ файле. Прежде срок брался из поля `sig_verified`, и достаточно было
    // написать в файл `"sig_verified": true` с любым содержимым ответа, чтобы получить неделю
    // полного доступа без сервера — часы при этом трогать не нужно. Подпись перепроверяется
    // ЗДЕСЬ, при каждом чтении; поле в файле осталось справочным и на решение не влияет.
    let verdict = cache_verdict(
        &cached.response.signature,
        cached_signature_matches(&cached.response),
    );
    let ttl = match verdict {
        CacheVerdict::Forged => {
            warn!(
                "SEC-1: подпись сохранённого ответа входа не сходится — файл отвергнут \
                 (подделка либо ответ с другой машины)"
            );
            return None;
        }
        CacheVerdict::AcceptVerified => cache_ttl_secs(true),
        CacheVerdict::AcceptUnverified => cache_ttl_secs(false),
    };
    if age > ttl {
        info!(
            "Auth cache expired (age: {}ч, потолок {}ч{})",
            age / 3600,
            ttl / 3600,
            if verdict == CacheVerdict::AcceptVerified { "" } else { ", подпись не подтверждена" }
        );
        return None;
    }

    // 🔴 Находка внешнего аудита (Medium): подпись покрывает шесть полей, а на диске лежит ВЕСЬ
    // ответ. Посредник, взявший законно подписанный ответ, может дописать свои адреса доставки —
    // подпись останется валидной. Из сохранённого ответа адреса и контрольные суммы доставки не
    // берутся вовсе: офлайн ничего не качает, а обновляться продукт вправе только по живому
    // ответу сервера.
    cached.response.content_pack_url = None;
    cached.response.content_pack_checksum = None;
    cached.response.frontend_url = None;
    cached.response.frontend_checksum = None;
    cached.response.update_url = None;

    Some((cached.response, age))
}

/// Лежит ли на диске ПОДТВЕРЖДЁННЫЙ и ещё не истёкший ответ. Нужна, чтобы неподписанный ответ
/// не понижал доверие уже имеющемуся (находка внешнего аудита).
fn verified_cache_is_fresh(app_config_dir: &Path) -> bool {
    let Ok(data) = std::fs::read_to_string(cache_path(app_config_dir)) else {
        return false;
    };
    let Ok(cached) = serde_json::from_str::<CachedAuth>(&data) else {
        return false;
    };
    let Ok(now) = SystemTime::now().duration_since(UNIX_EPOCH) else {
        return false;
    };
    let now = now.as_secs();
    if cached.cached_at > now || now - cached.cached_at > cache_ttl_secs(true) {
        return false;
    }
    cache_verdict(
        &cached.response.signature,
        cached_signature_matches(&cached.response),
    ) == CacheVerdict::AcceptVerified
}

/// Есть ли на руках годный сохранённый ответ — тихая проверка.
fn has_fresh_cache(app_config_dir: &Path) -> bool {
    read_fresh_cache(app_config_dir).is_some()
}

fn load_cache(app_config_dir: &Path) -> Option<AuthResponse> {
    let (response, age) = read_fresh_cache(app_config_dir)?;
    info!("Using cached auth response (age: {}m)", age / 60);
    Some(response)
}

// ── HTTP helpers ───────────────────────────────────────────

// ── Билет доступа к облачному шлюзу (ADR-048) ──────────────

/// Подтверждённый вход, лежащий в местном кэше.
///
/// Облачный модуль обращается сюда, а не разбирает файл кэша сам: здесь уже
/// проверены срок и принадлежность этому продукту. Своё чтение того же файла
/// означало бы вторую копию правил проверки — и рано или поздно они разошлись бы.
#[cfg(feature = "thin")]
pub fn cached_grant(app_config_dir: &Path) -> Option<AuthResponse> {
    load_cache(app_config_dir)
}

/// Собрать билет доступа к облачному шлюзу из подтверждённого входа.
///
/// Билет — это и есть ответ входа: сервер проверяет НАШУ подпись под ним, срок и
/// право на кабинет. Ничего нового подписывать не нужно, и отдельного секрета на
/// машине клиента не заводится.
///
/// 🔴 Отпечаток машины берётся здесь, а не из ответа: сервер подписывал ответ
/// вместе с отпечатком, и билет с чужим отпечатком просто не сойдётся по подписи —
/// то есть скопированный на другую машину файл кэша бесполезен.
#[cfg(feature = "thin")]
pub fn build_cloud_ticket(grant: &AuthResponse) -> Result<String> {
    use base64::Engine as _;

    let fp = fingerprint::get_machine_fingerprint()?;
    let ticket = serde_json::json!({
        "status": grant.status,
        "fingerprint_hash": fingerprint::hash_fingerprint(&fp),
        "product": detect_product(),
        "cabinets": grant.cabinets,
        "content_version": grant.content_version,
        "expires_at": grant.expires_at,
        "signature": grant.signature,
    });
    Ok(base64::engine::general_purpose::STANDARD.encode(serde_json::to_vec(&ticket)?))
}

fn build_client() -> Result<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(REQUEST_TIMEOUT_SECS))
        .build()?)
}

// ── Подпись исходящего запроса (CPD-141, ступень 2) ────────

/// Заголовки подписи для ОДНОЙ попытки. `None` означает «подписи не будет».
///
/// 🔴 Метка времени и одноразовое число берутся здесь, внутри, — значит на каждый вызов свои.
/// Поэтому звать эту функцию надо на КАЖДОЙ попытке цикла повторов, а не один раз до него:
/// к третьей попытке пауза состарила бы метку на шесть секунд (расхождение часов на сервере),
/// а повтор с тем же одноразовым числом сервер вправе счесть воспроизведением, если первая
/// попытка до него всё-таки дошла, а ответ потерялся.
///
/// 🔴 `None` — это не ошибка, а разрешение идти без подписи: ступень отказа не создаёт
/// (см. шапку `crypto::request_sig`). Поэтому здесь нет ни одного `Result` и ни одного
/// `unwrap`: каждая неудача складывается в `None`, и вызывающий отправляет запрос как прежде.
fn заголовки_подписи(
    ключ: &crate::crypto::request_sig::DeviceKey,
    url: &str,
    метод: &str,
    тело: &[u8],
    отпечаток: &str,
) -> Option<[(&'static str, String); 4]> {
    use crate::crypto::request_sig as подпись;

    // 🔴 Только `signed_path_for_edge`: приставку `/functions/v1` посредник срезает ДО функции,
    // сервер видит `/auth`. Путь, собранный руками, дал бы подпись над строкой, которой на
    // сервере не будет. Замерено боем 30.08, из кода не выводится.
    let путь = подпись::signed_path_for_edge(url)?;
    let метка = подпись::now_unix_string()?;
    let одноразовое = подпись::new_nonce()?;
    let свёртка = подпись::body_sha256_hex(тело);
    // 🔴 `_checked`, а не голая сборка: поле с собственным разделителем протокола сдвинуло бы
    // разбор на сервере (восемь полей вместо семи), и подпись молча считалась бы не от того.
    let строка = подпись::build_request_payload_checked(
        метод,
        &путь,
        &метка,
        &одноразовое,
        &свёртка,
        отпечаток,
    )?;

    let заголовки = [
        (подпись::HEADER_DEVICE, ключ.public_b64()),
        (подпись::HEADER_TIMESTAMP, метка),
        (подпись::HEADER_NONCE, одноразовое),
        (подпись::HEADER_SIGNATURE, ключ.sign(&строка)),
    ];
    // 🔴 Значение, негодное для заголовка, отравило бы сборщик запроса, и `send()` вернул бы
    // ошибку — то есть ступень создала бы ОТКАЗ, чего ей нельзя. Значения наши и берутся из
    // закреплённых алфавитов (base64, шестнадцатеричные, десятичные), так что случиться это
    // не может; проверка стоит здесь, чтобы «не может» держалось кодом, а не рассуждением.
    if заголовки
        .iter()
        .any(|(_, значение)| значение.is_empty() || !значение.bytes().all(|b| (0x21..=0x7E).contains(&b)))
    {
        return None;
    }
    Some(заголовки)
}

/// Собрать запрос входа: тело — ТЕ САМЫЕ байты, что пойдут в сеть, плюс подпись, если она
/// собралась.
///
/// 🔴 Байты приходят готовыми и уходят в тело как есть. Так свёртка и отправляемое тело
/// физически один и тот же массив, а не две сериализации, которые сегодня совпадают, а завтра
/// разойдутся: `.json(&req)` сериализует внутри себя, и подпись считалась бы от одной строки,
/// а проверялась от другой — локальные тесты такого не видят, ломается только бой.
///
/// `тело = None` (сериализация не удалась) и `ключ = None` (ключ не завёлся) — законные случаи:
/// запрос собирается как раньше, без подписи. Отказа отсюда не бывает.
fn собрать_запрос(
    client: &reqwest::Client,
    url: &str,
    req: &AuthRequest,
    тело: Option<&[u8]>,
    ключ: Option<&crate::crypto::request_sig::DeviceKey>,
) -> reqwest::RequestBuilder {
    let Some(байты) = тело else {
        // Своими руками тело не собралось — идём прежним путём. Подписывать нечего: свёртка
        // от байт, которых у нас нет, была бы выдумкой.
        return client.post(url).json(req);
    };
    let mut запрос = client
        .post(url)
        .header(reqwest::header::CONTENT_TYPE, "application/json")
        .body(байты.to_vec());
    if let Some(ключ) = ключ {
        // 🔴 Отпечаток — тот же, что уходит в теле (инвариант R12): сервер ищет закрепление по
        // тому же значению, которое подписано.
        // 🔴 Отпечаток подписывается В НИЖНЕМ РЕГИСТРЕ, потому что именно так его берёт сервер:
        // он один раз считает `fingerprint_hash.toLowerCase()` и подставляет ЭТО значение и в отбор
        // строки закрепления, и в каноническую строку (инвариант R12 в функции входа). Сегодня
        // расхождения нет — `hash_fingerprint` возвращает `hex::encode`, то есть всегда нижний, —
        // но полагаться на это молча нельзя: клиент, приславший верхний регистр, подписал бы одну
        // строку, а сервер проверял бы другую. Сейчас цена такой промашки — вердикт
        // `request_bad_signature` в журнале, после закрытия старого пути (шаг 5) — отказ честному
        // клиенту, то есть ровно то, чего этот контур не имеет права делать.
        // Это то же по природе правило, что и подъём процентных троек в `request_sig`: обе стороны
        // нормализуют значение одинаково, иначе подпись расходится при внешне верном коде.
        let отпечаток_для_подписи = req.fingerprint_hash.to_ascii_lowercase();
        if let Some(заголовки) = заголовки_подписи(ключ, url, "POST", байты, &отпечаток_для_подписи) {
            for (имя, значение) in заголовки {
                запрос = запрос.header(имя, значение);
            }
        }
    }
    запрос
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

    // Ключ устройства берём ОДИН раз: он один и тот же для всех попыток, а `load_or_create` —
    // обращение к диску. Каталог тот же, из которого читается сохранённый ответ (`has_fresh_cache`).
    //
    // 🔴 Не завёлся — идём без подписи и без единого слова наружу. Сервер неподписанный запрос
    // принимает как прежде; отказ невиновному дороже пропуска виноватого.
    let ключ_устройства = match crate::crypto::request_sig::DeviceKey::load_or_create(app_config_dir)
    {
        Ok(ключ) => Some(ключ),
        Err(e) => {
            warn!("CPD-141: ключ устройства недоступен ({e}) — запрос уйдёт без подписи");
            None
        }
    };

    // 🔴 Тело сериализуем САМИ и ОДИН раз, до цикла. Сами — потому что свёртка обязана считаться
    // от тех самых байт, которые уйдут в сеть, а `.json(&req)` сериализует внутри себя. Один раз —
    // потому что на всех попытках тело обязано быть одним и тем же; меняются только метка времени
    // и одноразовое число, и они пересчитываются внутри цикла.
    let тело = match serde_json::to_vec(&req) {
        Ok(байты) => Some(байты),
        Err(e) => {
            warn!("CPD-141: тело запроса не сериализовано ({e}) — запрос уйдёт без подписи");
            None
        }
    };

    // Повторы при обрыве связи (разбор отказа у клиента 2026-07-26): ответ
    // сервера крошечный, но на нестабильном канале рвался и он —
    // «error decoding response body» приходило и сюда. Кэш спасает только
    // того, у кого он уже есть; на первом запуске кэша нет, и один
    // неудачный запрос означал бы «программа не запускается».
    //
    // Число попыток зависит от того, есть ли чем подстраховаться (находка
    // аудита M-1): с годным сохранённым ответом на руках хватает одной, и
    // старт при недоступной сети остаётся быстрым — иначе путь «связи нет,
    // берём сохранённое» удлинялся втрое вместе с паузами между попытками.
    // Без кэша (первый запуск) пробуем трижды: там цена отказа — «программа
    // не открывается вовсе».
    const AUTH_ATTEMPTS: u32 = 3;
    let attempts = if has_fresh_cache(app_config_dir) { 1 } else { AUTH_ATTEMPTS };
    let mut last_err: Option<anyhow::Error> = None;
    let mut response: Option<(reqwest::StatusCode, String)> = None;

    for attempt in 1..=attempts {
        // 🔴 Запрос собирается ЗДЕСЬ, внутри цикла, на каждой попытке — вместе с подписью:
        // метка времени и одноразовое число обязаны быть свои у каждой попытки. Байты тела при
        // этом те же самые: они взяты один раз до цикла и сюда только передаются.
        let sent = собрать_запрос(&client, &url, &req, тело.as_deref(), ключ_устройства.as_ref())
            .send()
            .await;
        match sent {
            Ok(res) => {
                let status_code = res.status();
                match res.text().await {
                    Ok(body) => {
                        response = Some((status_code, body));
                        break;
                    }
                    Err(e) => last_err = Some(anyhow::anyhow!("ответ оборван: {e}")),
                }
            }
            Err(e) => last_err = Some(anyhow::anyhow!("{e}")),
        }
        if attempt < attempts {
            warn!("Online auth: попытка {attempt}/{attempts} не удалась ({:#}) — повтор", last_err.as_ref().unwrap());
            tokio::time::sleep(std::time::Duration::from_secs(2 * attempt as u64)).await;
        }
    }

    let (status_code, body) = match response {
        Some(v) => v,
        None => return Err(last_err.unwrap_or_else(|| anyhow::anyhow!("Online auth: связь с сервером не установилась"))),
    };

    let auth_response: AuthResponse = serde_json::from_str(&body)
        .map_err(|e| anyhow::anyhow!("Failed to parse auth response: {e}, body: {body}"))?;

    // 🔴 CPD-40 (SEC-1 + A-3): подпись ответа входа ПРОВЕРЯЕТСЯ. До этой правки продукт объявлял
    // поле `signature`, но не сверял его ни с чем: поддельный ответ посредника принимался как
    // настоящий и ложился в кэш на неделю. Сервер ответ подписывает — проверено на живом ответе
    // этой машины (зонд `live_auth_signature_probe`): канонизация payload сходится с серверной
    // байт в байт при `product = detect_product()`.
    //
    // Режим МЯГКИЙ: исход проверки не решает, дать ли доступ (иначе расхождение формата разом
    // отняло бы лицензии у всех), он решает судьбу КЭША — что именно останется на диске после
    // ухода посредника.
    let mut policy = CachePolicy::Unverified;
    if auth_response.status == "ok" {
        let payload = crate::crypto::auth_sig::build_auth_payload(
            &auth_response.status,
            &req.fingerprint_hash,
            &req.product,
            &auth_response.cabinets,
            auth_response.content_version.as_deref(),
            auth_response.expires_at.as_deref(),
        );
        let sig_ok =
            crate::crypto::auth_sig::verify_auth_signature(&payload, &auth_response.signature);
        policy = cache_policy(&auth_response.signature, sig_ok);
        match crate::crypto::auth_sig::AUTH_SIG_ENFORCEMENT {
            crate::crypto::auth_sig::Enforcement::Soft => match policy {
                CachePolicy::Verified => info!("SEC-1: подпись ответа входа подтверждена"),
                CachePolicy::Unverified => warn!(
                    "SEC-1: ответ входа без подписи — доступ выдан (мягкий режим), \
                     срок доверия кэшу сокращён до суток"
                ),
                CachePolicy::Reject => error!(
                    "SEC-1: подпись ответа входа НЕ сходится — доступ выдан (мягкий режим), \
                     но на диск ответ не пишется: подделка не переживёт эту сессию"
                ),
            },
            // 🔴 Находка внешнего аудита (Medium): в жёстком режиме нельзя валить обе ветки
            // одним условием. «Подписи нет вовсе» — путь ЗАКОННЫЙ, и он живой прямо сейчас:
            // сервер локальной редакции отвечает без подписи (проверено живым кэшем
            // `com.aurora.econometrica.local`). Переключение константы без второй половины
            // работы отняло бы вход у таких сборок, а мягкий режим этого не показал бы —
            // там тот же случай пишется обычным предупреждением. Причины разведены, чтобы
            // отказ был диагностируем, а не «подпись не подтверждена» на оба разных случая.
            crate::crypto::auth_sig::Enforcement::Hard => match policy {
                CachePolicy::Verified => {}
                CachePolicy::Unverified => anyhow::bail!(
                    "[SEC-1] сервер не подписал ответ входа — доступ не выдан (жёсткий режим)"
                ),
                CachePolicy::Reject => anyhow::bail!(
                    "[SEC-1] подпись ответа входа не сходится — доступ не выдан"
                ),
            },
        }
    }

    if auth_response.status == "ok" {
        // 🔴 CPD-40 (A-3): ответ с ПРИСУТСТВУЮЩЕЙ, но неверной подписью на диск не пишем.
        // Прежде на диск ложилось всё, поэтому посредник, поднятый на полминуты, оставлял
        // поддельный грант (чужие кабинеты, срок до 2099 года), и тот переживал его уход: при
        // первом отказе сети кэш отдавал подделку. Доступ в этой сессии выдаётся по-прежнему —
        // мягкость это принятое решение, — но подделка больше не персистентна. Ответ БЕЗ подписи
        // кэшируется на короткий срок (законный путь «сервер не подписывает» не ломаем).
        match policy {
            CachePolicy::Reject => {
                error!(
                    "SEC-1 (A-3): ответ входа с неверной подписью НЕ кэширован — доступ выдан \
                     (мягкий режим), но подделка не переживёт эту сессию"
                );
            }
            // 🔴 Находка внешнего аудита (Medium): ответ БЕЗ подписи молча затирал
            // ПОДТВЕРЖДЁННЫЙ грант — доверие падало с недели до суток, а вместе с ним уезжали
            // кабинеты: у `AuthResponse` все поля, кроме статуса, со значением по умолчанию,
            // поэтому телом `{"status":"ok"}` дело и ограничивается. Сценарий не выдуманный:
            // подмена ответа в сети либо сервер, временно переставший подписывать. Понижения не
            // допускаем, пока подтверждённый ответ на диске ещё в силе.
            CachePolicy::Unverified if verified_cache_is_fresh(app_config_dir) => {
                warn!(
                    "SEC-1: ответ без подписи НЕ заменил подтверждённый сохранённый ответ — \
                     доверие не понижается"
                );
            }
            CachePolicy::Verified | CachePolicy::Unverified => {
                let verified = policy == CachePolicy::Verified;
                if let Err(e) = save_cache(app_config_dir, &auth_response, verified) {
                    warn!("Failed to cache auth response: {e}");
                }
            }
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
                    vault_checksums: resp.vault_checksums,
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
                    vault_checksums: None,
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
                    vault_checksums: cached.vault_checksums,
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
                    vault_checksums: None,
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

    /// 🔴 `sig_verified` задаётся явно, а не берётся по умолчанию: от него зависит СРОК доверия
    /// (CPD-40, A-3), и тест недельной границы, записанный кэшем без подписи, проверял бы
    /// суточную — оставаясь при этом зелёным.
    /// Синтаксически годная, но заведомо неверная подпись: 64 нулевых байта в base64.
    /// Настоящую подпись в тесте не сделать — закрытый ключ у сервера, — а для ветки
    /// «подпись есть и не сходится» этого достаточно.
    fn base64_of_zero_signature() -> String {
        use base64::{engine::general_purpose::STANDARD, Engine};
        STANDARD.encode([0u8; 64])
    }

    fn write_cache_with_age(dir: &Path, cached_at: u64, sig_verified: bool) {
        let cached = CachedAuth { response: sample_response(), cached_at, sig_verified };
        std::fs::write(cache_path(dir), serde_json::to_string(&cached).unwrap()).unwrap();
    }

    /// Свежий кэш (после успешной онлайн-активации) читается — офлайн-окно
    /// до 7 дней не роняет лицензию (сценарий «офлайн fallback, кэш есть»).
    #[test]
    fn cache_roundtrip_fresh_ok() {
        let dir = tmp_dir();
        save_cache(&dir, &sample_response(), true).unwrap();
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
        write_cache_with_age(&dir, now - CACHE_TTL_SECS - 60, true);
        assert!(load_cache(&dir).is_none(), "кэш старше TTL обязан отвергаться");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Перевод часов назад / подделка кэша: cached_at в будущем → REJECT
    /// (anti-rollback guard; прямое вычитание u64 паниковало бы в debug).
    #[test]
    fn cache_future_dated_rejected() {
        let dir = tmp_dir();
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        write_cache_with_age(&dir, now + 3600, true);
        assert!(load_cache(&dir).is_none(), "кэш из будущего обязан отвергаться");
        let _ = std::fs::remove_dir_all(&dir);
    }

    // ── CPD-40 (A-3): поддельный грант входа не переживает сессию ──────────────

    /// Подпись сошлась → полное доверие.
    #[test]
    fn cache_policy_verified_when_signature_ok() {
        assert_eq!(cache_policy("YWJjZGVm", true), CachePolicy::Verified);
    }

    /// 🔴 Ядро A-3: подпись ЕСТЬ, но не сходится → на диск не пишем вовсе. Ровно этот случай
    /// оставлял поддельный грант посредника, переживавший его уход.
    #[test]
    fn cache_policy_rejects_present_but_invalid_signature() {
        assert_eq!(cache_policy("AAAAAAAA", false), CachePolicy::Reject);
    }

    /// Подписи нет вовсе (сервер не подписывает или не смог) → кэшируем, но коротко. Запрещать
    /// этот случай нельзя: у законных пользователей отвалился бы офлайн. Путь наблюдаем живьём —
    /// сервер локальной редакции отвечает без подписи (`com.aurora.econometrica.local`).
    #[test]
    fn cache_policy_unverified_when_signature_absent() {
        assert_eq!(cache_policy("", false), CachePolicy::Unverified);
    }

    /// Срок доверия: подтверждённой подписи — неделя, неподтверждённой — сутки. Числа
    /// литеральные, а не через те же константы, иначе тест проверял бы сам себя.
    #[test]
    fn cache_ttl_shorter_without_verified_signature() {
        assert_eq!(cache_ttl_secs(true), 7 * 24 * 60 * 60, "подтверждённая — неделя");
        assert_eq!(cache_ttl_secs(false), 24 * 60 * 60, "неподтверждённая — сутки");
        assert!(cache_ttl_secs(false) < cache_ttl_secs(true));
    }

    /// 🔴 Ядро находки внешнего аудита (High): признак `sig_verified` в файле БОЛЬШЕ НЕ ДАЁТ
    /// доверия. Прежде достаточно было написать в кэш `"sig_verified": true`, чтобы получить
    /// недельный срок без сервера и без правки часов; теперь подпись перепроверяется при чтении,
    /// и двухдневный кэш без настоящей подписи отвергается, что бы ни стояло в файле.
    #[test]
    fn the_flag_in_the_file_no_longer_buys_a_week() {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        let two_days = 2 * 24 * 60 * 60;

        let dir = tmp_dir();
        write_cache_with_age(&dir, now - two_days, true); // подписи в ответе нет, флаг подняли
        assert!(
            load_cache(&dir).is_none(),
            "кэш без настоящей подписи обязан жить сутки, сколько бы ни утверждал файл о себе"
        );
        let _ = std::fs::remove_dir_all(&dir);

        // Позитивный контроль: часовой кэш без подписи по-прежнему годен — офлайн у честных
        // пользователей не отнят, отвергается именно ПРОСРОЧЕННЫЙ.
        let fresh = tmp_dir();
        write_cache_with_age(&fresh, now - 3600, false);
        assert!(
            load_cache(&fresh).is_some(),
            "свежий кэш без подписи обязан читаться: путь «сервер не подписывает» законный"
        );
        let _ = std::fs::remove_dir_all(&fresh);
    }

    /// 🔴 Кэш с ПРИСУТСТВУЮЩЕЙ, но неверной подписью отвергается независимо от возраста: у такого
    /// файла нет законного источника. Свежесть его не спасает — иначе подделка жила бы сутки.
    #[test]
    fn cache_with_a_present_but_wrong_signature_is_rejected_even_when_fresh() {
        let dir = tmp_dir();
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        let mut response = sample_response();
        response.signature = base64_of_zero_signature();
        let cached = CachedAuth { response, cached_at: now - 60, sig_verified: true };
        std::fs::write(cache_path(&dir), serde_json::to_string(&cached).unwrap()).unwrap();

        assert!(
            load_cache(&dir).is_none(),
            "подпись есть и не сходится — сохранённый ответ подделан либо снят с чужой машины"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Правило приговора без боевого ключа: признак «подпись сошлась» приходит снаружи.
    #[test]
    fn cache_verdict_rules() {
        assert_eq!(cache_verdict("YWJjZGVm", true), CacheVerdict::AcceptVerified);
        assert_eq!(cache_verdict("", false), CacheVerdict::AcceptUnverified);
        assert_eq!(cache_verdict("YWJjZGVm", false), CacheVerdict::Forged);
    }

    /// 🔴 Находка внешнего аудита (Medium): подпись покрывает шесть полей, а на диске лежит весь
    /// ответ — законно подписанный ответ можно дополнить своими адресами доставки. Из кэша адреса
    /// и контрольные суммы не берутся вовсе.
    #[test]
    fn delivery_addresses_never_come_from_the_cache() {
        let dir = tmp_dir();
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        let mut response = sample_response();
        response.content_pack_url = Some("https://evil.example/pack.zip".to_string());
        response.content_pack_checksum = Some("sha256:deadbeef".to_string());
        response.frontend_url = Some("https://evil.example/frontend.zip".to_string());
        response.frontend_checksum = Some("sha256:deadbeef".to_string());
        response.update_url = Some("https://evil.example/setup.exe".to_string());
        let cached = CachedAuth { response, cached_at: now - 60, sig_verified: false };
        std::fs::write(cache_path(&dir), serde_json::to_string(&cached).unwrap()).unwrap();

        let loaded = load_cache(&dir).expect("свежий кэш обязан читаться");
        assert_eq!(loaded.content_pack_url, None, "адрес пакета содержимого не из кэша");
        assert_eq!(loaded.content_pack_checksum, None);
        assert_eq!(loaded.frontend_url, None, "адрес бандла фронта не из кэша — там исполняемый код");
        assert_eq!(loaded.frontend_checksum, None);
        assert_eq!(loaded.update_url, None, "адрес обновления не из кэша");
        assert_eq!(loaded.cabinets, vec!["econometrist".to_string()], "подписанные поля остаются");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 🔴 Находка внешнего аудита (Medium): жёсткий режим не имеет права валить одним условием
    /// два разных случая — «подпись не сходится» (подделка) и «подписи нет вовсе» (законный путь,
    /// живой прямо сейчас: сервер локальной редакции не подписывает). Иначе переключение
    /// константы молча отнимет вход у таких сборок, а мягкий режим этого не покажет.
    #[test]
    fn hard_mode_tells_the_two_refusals_apart() {
        let src = include_str!("online_auth.rs");
        // 🔴 Окно берём по СТРОКАМ, а не байтовым смещением: срез вида `src[at..at+900]`
        // паникует, попав внутрь многобайтового символа кириллицы — поймано первым же прогоном
        // (та же ловушка, что у сторожей в claude.rs).
        // 🔴 И ищем ТОЛЬКО в коде продукта, отрезав тестовый модуль: иначе образец совпадает с
        // собственной строкой этого теста, окно берётся вокруг неё, обе искомые фразы находятся
        // в соседних ассертах — и сторож остаётся зелёным при обезвреженном коде. Поймано
        // мутацией: она «не покраснела», хотя жёсткая ветка была сведена к одному условию.
        let src = &src[..src.find("#[cfg(test)]").unwrap_or(src.len())];
        let lines: Vec<&str> = src.lines().collect();
        let at = lines
            .iter()
            .position(|l| l.contains("Enforcement::Hard => match policy"))
            .expect("жёсткая ветка сведена обратно к одному условию — два разных отказа снова \
                    неразличимы");
        let window = lines[at..(at + 12).min(lines.len())].join("\n");
        let window = window.as_str();
        assert!(
            window.contains("сервер не подписал"),
            "отказ по отсутствию подписи обязан называться своей причиной"
        );
        assert!(
            window.contains("не сходится"),
            "отказ по неверной подписи обязан называться своей причиной"
        );
    }

    /// Находка внешнего аудита (Medium): неподписанный ответ не имеет права понижать доверие
    /// уже подтверждённому. Проверяем обе стороны правила на доступных данных: подтверждённого
    /// кэша без боевого ключа не создать, поэтому здесь — что кэш БЕЗ подписи подтверждённым не
    /// считается (иначе правило заблокировало бы обновление кэша навсегда).
    #[test]
    fn an_unsigned_cache_does_not_count_as_verified() {
        let dir = tmp_dir();
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        write_cache_with_age(&dir, now - 60, true);
        assert!(
            !verified_cache_is_fresh(&dir),
            "кэш без настоящей подписи не подтверждён — иначе продукт перестал бы обновлять его \
             вовсе, поверив признаку в файле"
        );
        let _ = std::fs::remove_dir_all(&dir);

        // Сторож СВЯЗИ: сама ветка защиты от понижения обязана стоять в `check_auth` — чистая
        // функция выше без неё бесполезна.
        // Ищем только в коде продукта: строка-образец есть и в этом тесте, и без обрезки
        // сторож находил бы сам себя (та же ловушка, что у сторожа жёсткого режима).
        let src = include_str!("online_auth.rs");
        let src = &src[..src.find("#[cfg(test)]").unwrap_or(src.len())];
        assert!(
            src.contains("CachePolicy::Unverified if verified_cache_is_fresh"),
            "ответ без подписи снова затирает подтверждённый грант: доверие падает с недели до \
             суток, а кабинеты уезжают вместе с ним"
        );
    }

    /// 🔴 Сторож СВЯЗИ: чтение кэша обязано САМО сверять подпись. Если проверку вынести, чистые
    /// функции выше останутся зелёными, а доверие снова будет держаться на признаке из файла.
    #[test]
    fn reading_the_cache_verifies_the_signature_itself() {
        let src = include_str!("online_auth.rs");
        let start = src
            .find("fn read_fresh_cache")
            .expect("функция read_fresh_cache не найдена — разметка переехала");
        let tail = &src[start..];
        let end = tail[1..].find("\nfn ").map(|i| i + 1).unwrap_or(tail.len());
        let window = &tail[..end];

        assert!(
            window.contains("cached_signature_matches"),
            "чтение кэша не сверяет подпись: достаточно будет написать в файл «подпись \
             подтверждена», чтобы получить недельный доступ без сервера"
        );
        assert!(
            window.contains("CacheVerdict::Forged"),
            "ветка «подпись есть и не сходится → отвергнуть» обязана быть в самом чтении кэша"
        );
    }

    /// Обратная совместимость: кэш, записанный ПРЕЖНЕЙ версией продукта, поля `sig_verified` не
    /// имеет. Он обязан читаться (не падать разбором) и жить по короткому сроку — при первом же
    /// успешном входе онлайн перезапишется с подтверждением и вернёт полный.
    #[test]
    fn legacy_cache_without_the_field_is_read_as_unverified() {
        let dir = tmp_dir();
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        let legacy = serde_json::json!({
            "response": sample_response(),
            "cached_at": now - 2 * 24 * 60 * 60,
        });
        std::fs::write(cache_path(&dir), serde_json::to_string(&legacy).unwrap()).unwrap();
        assert!(
            load_cache(&dir).is_none(),
            "прежний кэш без признака подписи обязан считаться неподтверждённым"
        );

        std::fs::write(
            cache_path(&dir),
            serde_json::to_string(&serde_json::json!({
                "response": sample_response(),
                "cached_at": now - 3600,
            }))
            .unwrap(),
        )
        .unwrap();
        assert!(
            load_cache(&dir).is_some(),
            "часовой прежний кэш обязан читаться: разбор без поля не имеет права падать"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 🔴 Сторож СВЯЗИ (урок Ф-04: вынесенная функция покрыта, а её вызов — нет). Чистые функции
    /// выше ничего не стоят, если `check_auth` перестанет сверять подпись или писать кэш мимо
    /// политики. Разбор собственного исходника — тот же приём, что у сторожей гейта в `claude.rs`.
    #[test]
    fn check_auth_verifies_the_signature_and_saves_through_the_policy() {
        let src = include_str!("online_auth.rs");
        let start = src
            .find("pub async fn check_auth")
            .expect("функция check_auth не найдена — разметка переехала");
        let tail = &src[start..];
        let save_at = tail
            .find("save_cache(app_config_dir")
            .expect("запись кэша в check_auth не найдена — разметка переехала");
        let window = &tail[..save_at];

        assert!(
            window.contains("verify_auth_signature"),
            "между разбором ответа и записью кэша нет проверки подписи: поддельный ответ \
             посредника снова ляжет на диск как настоящий (CPD-40)"
        );
        assert!(
            window.contains("cache_policy("),
            "судьба кэша обязана решаться политикой, а не одним лишь статусом ответа"
        );
        assert!(
            window.contains("CachePolicy::Reject"),
            "ветка «подпись есть и не сходится → не писать» обязана существовать в самом \
             check_auth, иначе подделка снова переживёт сессию"
        );
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

    // ── Подпись исходящего запроса входа (CPD-141, ступень 2) ────────────────────────────────

    const АДРЕС_ВХОДА: &str = "https://ref.supabase.co/functions/v1/auth";

    fn образец_запроса() -> AuthRequest {
        AuthRequest {
            fingerprint_hash: "a".repeat(64),
            instance_id: "инстанс-1".to_string(),
            session_id: "сессия-1".to_string(),
            app_version: "2.4.5".to_string(),
            content_version: "7".to_string(),
            hostname: "МАШИНА".to_string(),
            product: "econometrica".to_string(),
            consent_terms_version: Some(3),
            consent_accepted_at: Some(1_788_000_000),
        }
    }

    fn значение_заголовка(запрос: &reqwest::Request, имя: &str) -> Option<String> {
        запрос.headers().get(имя).map(|v| v.to_str().unwrap().to_string())
    }

    /// Сходится ли подпись из заголовков готового запроса с канонической строкой, собранной
    /// над УКАЗАННЫМ путём и над телом самого запроса.
    fn подпись_сходится_над_путём(запрос: &reqwest::Request, путь: &str, отпечаток: &str) -> bool {
        use base64::{engine::general_purpose::STANDARD, Engine};
        use crate::crypto::request_sig as подпись;
        use ed25519_dalek::{Signature, Verifier, VerifyingKey};

        let тело = запрос.body().and_then(|b| b.as_bytes()).expect("тело запроса");
        let строка = подпись::build_request_payload(
            "POST",
            путь,
            &значение_заголовка(запрос, подпись::HEADER_TIMESTAMP).expect("метка времени"),
            &значение_заголовка(запрос, подпись::HEADER_NONCE).expect("одноразовое число"),
            &подпись::body_sha256_hex(тело),
            отпечаток,
        );
        let открытый: [u8; 32] = STANDARD
            .decode(значение_заголовка(запрос, подпись::HEADER_DEVICE).expect("открытый ключ"))
            .unwrap()
            .try_into()
            .unwrap();
        let подпись_байты: [u8; 64] = STANDARD
            .decode(значение_заголовка(запрос, подпись::HEADER_SIGNATURE).expect("подпись"))
            .unwrap()
            .try_into()
            .unwrap();
        VerifyingKey::from_bytes(&открытый)
            .unwrap()
            .verify(строка.as_bytes(), &Signature::from_bytes(&подпись_байты))
            .is_ok()
    }

    /// 🔴 Свёртка обязана считаться от ТЕХ ЖЕ байт, которые уйдут в сеть.
    ///
    /// Тело берётся из ГОТОВОГО запроса (`Request::body`), а не из переменной теста: так
    /// проверяется реальная отправка, а не наше представление о ней. Сериализация — настоящая,
    /// от `AuthRequest`, а не выдуманная строка: у настоящей есть и кириллица, и пропускаемые
    /// поля согласия, и порядок полей структуры.
    #[test]
    fn свёртка_считается_от_тех_же_байт_что_уходят_в_сеть() {
        use crate::crypto::request_sig as подпись;

        let dir = tmp_dir();
        let ключ = подпись::DeviceKey::load_or_create(&dir).expect("ключ заводится");
        let req = образец_запроса();
        let байты = serde_json::to_vec(&req).expect("тело сериализуется");
        let client = reqwest::Client::new();

        let запрос = собрать_запрос(&client, АДРЕС_ВХОДА, &req, Some(&байты), Some(&ключ))
            .build()
            .expect("запрос обязан собираться");

        let ушедшие = запрос.body().and_then(|b| b.as_bytes()).expect("тело обязано быть у запроса");
        assert_eq!(
            ушедшие,
            байты.as_slice(),
            "🔴 в сеть обязаны уйти те самые байты, от которых считалась свёртка"
        );
        assert_eq!(
            значение_заголовка(&запрос, "content-type").as_deref(),
            Some("application/json"),
            "тело отправляется байтами, значит тип содержимого проставляем сами"
        );
        assert!(
            подпись_сходится_над_путём(&запрос, "/auth", &req.fingerprint_hash),
            "🔴 подпись обязана сходиться над свёрткой ТЕЛА ЗАПРОСА: если подписано одно, \
             а отправлено другое, сервер увидит негодную подпись, а локальные тесты — нет"
        );

        // Контроль: над телом с одним лишним байтом та же подпись сойтись не имеет права —
        // иначе проверка выше ничего не значит.
        let mut подделка = байты.clone();
        подделка.push(b' ');
        let чужая = собрать_запрос(&client, АДРЕС_ВХОДА, &req, Some(&подделка), Some(&ключ))
            .build()
            .unwrap();
        let строка_чужая = подпись::build_request_payload(
            "POST",
            "/auth",
            &значение_заголовка(&чужая, подпись::HEADER_TIMESTAMP).unwrap(),
            &значение_заголовка(&чужая, подпись::HEADER_NONCE).unwrap(),
            &подпись::body_sha256_hex(&байты),
            &req.fingerprint_hash,
        );
        {
            use base64::{engine::general_purpose::STANDARD, Engine};
            use ed25519_dalek::{Signature, Verifier, VerifyingKey};
            let открытый: [u8; 32] = STANDARD
                .decode(значение_заголовка(&чужая, подпись::HEADER_DEVICE).unwrap())
                .unwrap()
                .try_into()
                .unwrap();
            let подпись_байты: [u8; 64] = STANDARD
                .decode(значение_заголовка(&чужая, подпись::HEADER_SIGNATURE).unwrap())
                .unwrap()
                .try_into()
                .unwrap();
            assert!(
                VerifyingKey::from_bytes(&открытый)
                    .unwrap()
                    .verify(строка_чужая.as_bytes(), &Signature::from_bytes(&подпись_байты))
                    .is_err(),
                "свёртка ДРУГОГО тела не имеет права сходиться — иначе проверка слепа"
            );
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 🔴 ГЛАВНЫЙ ИНВАРИАНТ: ступень подписи не создаёт отказа.
    ///
    /// Четыре способа не собрать подпись — путь не разбирается, поле содержит разделитель
    /// протокола, ключ не завёлся, тело не сериализовалось. В каждом случае запрос обязан
    /// СОБРАТЬСЯ и уйти, только без заголовков подписи. Ни `build()`, ни отсутствие тела,
    /// ни паника здесь недопустимы.
    #[test]
    fn ступень_подписи_не_создаёт_отказа() {
        use crate::crypto::request_sig as подпись;

        let dir = tmp_dir();
        let ключ = подпись::DeviceKey::load_or_create(&dir).expect("ключ заводится");
        let client = reqwest::Client::new();
        let req = образец_запроса();
        let байты = serde_json::to_vec(&req).expect("тело сериализуется");

        // Поле с собственным разделителем протокола: `build_request_payload_checked` откажет.
        let с_разделителем = AuthRequest { fingerprint_hash: "abc\ndef".to_string(), ..образец_запроса() };
        let байты_с_разделителем = serde_json::to_vec(&с_разделителем).expect("тело сериализуется");

        // Путь, который не разбирается, до сборщика запроса не доходит: `reqwest` сам отвергает
        // относительную цель (`RelativeUrlWithoutBase`) раньше нас, а боевой адрес всегда
        // абсолютный. Поэтому эта ветвь проверяется на самом помощнике — она обязана давать
        // «подписи не будет», а не панику и не ошибку.
        assert!(
            заголовки_подписи(&ключ, "не-адрес", "POST", &байты, &req.fingerprint_hash).is_none(),
            "🔴 неразбираемый адрес обязан означать «идём без подписи», а не отказ"
        );

        let случаи: Vec<(&str, reqwest::Request)> = vec![
            (
                "разделитель протокола в поле",
                собрать_запрос(
                    &client,
                    АДРЕС_ВХОДА,
                    &с_разделителем,
                    Some(&байты_с_разделителем),
                    Some(&ключ),
                )
                .build()
                .expect("запрос обязан собраться и без подписи"),
            ),
            (
                "ключ устройства не завёлся",
                собрать_запрос(&client, АДРЕС_ВХОДА, &req, Some(&байты), None)
                    .build()
                    .expect("запрос обязан собраться и без подписи"),
            ),
            (
                "тело не сериализовалось",
                собрать_запрос(&client, АДРЕС_ВХОДА, &req, None, Some(&ключ))
                    .build()
                    .expect("запрос обязан собраться и без подписи"),
            ),
        ];

        for (случай, запрос) in случаи {
            assert!(
                запрос.body().and_then(|b| b.as_bytes()).is_some_and(|b| !b.is_empty()),
                "🔴 «{случай}»: запрос обязан уйти с телом — отказ невиновному дороже пропуска виноватого"
            );
            for имя in [
                подпись::HEADER_DEVICE,
                подпись::HEADER_TIMESTAMP,
                подпись::HEADER_NONCE,
                подпись::HEADER_SIGNATURE,
            ] {
                assert!(
                    значение_заголовка(&запрос, имя).is_none(),
                    "🔴 «{случай}»: подписи нет, значит и заголовка {имя} быть не должно — \
                     половина подписи хуже её отсутствия"
                );
            }
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 🔴 Подписывается `/auth`, а не `/functions/v1/auth`: приставку посредник срезает ДО
    /// функции. Замерено боем 30.08, из кода не выводится — потому проверяется на РЕАЛЬНОМ
    /// запросе, а не только в модуле подписи.
    #[test]
    fn подписывается_путь_без_приставки_посредника() {
        use crate::crypto::request_sig as подпись;

        let dir = tmp_dir();
        let ключ = подпись::DeviceKey::load_or_create(&dir).expect("ключ заводится");
        let client = reqwest::Client::new();
        let req = образец_запроса();
        let байты = serde_json::to_vec(&req).expect("тело сериализуется");

        let запрос = собрать_запрос(&client, АДРЕС_ВХОДА, &req, Some(&байты), Some(&ключ))
            .build()
            .expect("запрос обязан собираться");

        assert!(
            подпись_сходится_над_путём(&запрос, "/auth", &req.fingerprint_hash),
            "🔴 сервер видит «/auth» — над ним и обязана сходиться подпись"
        );
        assert!(
            !подпись_сходится_над_путём(&запрос, "/functions/v1/auth", &req.fingerprint_hash),
            "🔴 приставка посредника в подпись не входит: подписав её, клиент не сойдётся \
             у сервера ни одним запросом"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 🔴 Отпечаток подписывается в НИЖНЕМ регистре — так его берёт сервер (`toLowerCase()`
    /// один раз, и это же значение идёт и в отбор закрепления, и в каноническую строку, R12).
    /// Сегодня клиент и так шлёт нижний (`hex::encode`), поэтому проверка ставится на СЛУЧАЙ,
    /// которого сегодня не бывает: тело с верхним регистром. Иначе правило живёт только в
    /// комментарии, а промашка проявится не отказом сборки, а тихим расхождением подписи —
    /// сегодня вердиктом в журнале, после закрытия старого пути отказом честному клиенту.
    #[test]
    fn отпечаток_подписывается_в_нижнем_регистре() {
        use crate::crypto::request_sig as подпись;

        let dir = tmp_dir();
        let ключ = подпись::DeviceKey::load_or_create(&dir).expect("ключ заводится");
        let client = reqwest::Client::new();

        let mut req = образец_запроса();
        req.fingerprint_hash = "AB".repeat(32); // верхний регистр — то, чего сегодня не бывает
        let байты = serde_json::to_vec(&req).expect("тело сериализуется");

        let запрос = собрать_запрос(&client, АДРЕС_ВХОДА, &req, Some(&байты), Some(&ключ))
            .build()
            .expect("запрос обязан собираться");

        let нижний = req.fingerprint_hash.to_ascii_lowercase();
        assert!(
            подпись_сходится_над_путём(&запрос, "/auth", &нижний),
            "🔴 сервер считает каноническую строку от отпечатка в нижнем регистре — \
             над ним и обязана сходиться подпись"
        );
        assert!(
            !подпись_сходится_над_путём(&запрос, "/auth", &req.fingerprint_hash),
            "🔴 подпись над отпечатком «как прислали» не сойдётся у сервера ни одним запросом"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 🔴 Метка времени и одноразовое число — свои у каждой попытки, значит подпись
    /// пересчитывается на каждой. Один раз подписанный запрос к третьей попытке уехал бы с
    /// меткой возрастом шесть секунд, а повтор с тем же одноразовым числом сервер вправе счесть
    /// воспроизведением.
    #[test]
    fn одноразовое_число_и_подпись_свои_у_каждой_попытки() {
        use crate::crypto::request_sig as подпись;

        let dir = tmp_dir();
        let ключ = подпись::DeviceKey::load_or_create(&dir).expect("ключ заводится");
        let req = образец_запроса();
        let байты = serde_json::to_vec(&req).expect("тело сериализуется");

        let первая = заголовки_подписи(&ключ, АДРЕС_ВХОДА, "POST", &байты, &req.fingerprint_hash)
            .expect("подпись собирается");
        let вторая = заголовки_подписи(&ключ, АДРЕС_ВХОДА, "POST", &байты, &req.fingerprint_hash)
            .expect("подпись собирается");

        let одноразовое = |набор: &[(&'static str, String); 4]| {
            набор.iter().find(|(имя, _)| *имя == подпись::HEADER_NONCE).unwrap().1.clone()
        };
        let подпись_из = |набор: &[(&'static str, String); 4]| {
            набор.iter().find(|(имя, _)| *имя == подпись::HEADER_SIGNATURE).unwrap().1.clone()
        };

        assert_ne!(
            одноразовое(&первая),
            одноразовое(&вторая),
            "🔴 одноразовое число обязано быть новым на каждой попытке"
        );
        assert_ne!(
            подпись_из(&первая),
            подпись_из(&вторая),
            "🔴 подпись обязана пересчитываться: строка другая — значит и подпись другая"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 🔴 Сторож СВЯЗИ (тот же приём, что у сторожа подписи ответа выше, урок Ф-04): проверки
    /// над `собрать_запрос` ничего не стоят, если сам вызов уедет ИЗ цикла повторов. Подпись,
    /// собранная один раз до цикла и разосланная всем трём попыткам, компилируется и проходит
    /// все проверки поведения — ловится только местом вызова.
    #[test]
    fn подпись_собирается_внутри_цикла_повторов_а_тело_до_него() {
        let src = include_str!("online_auth.rs");
        let start = src
            .find("pub async fn check_auth")
            .expect("функция check_auth не найдена — разметка переехала");
        let tail = &src[start..];

        let цикл = tail
            .find("for attempt in 1..=attempts {")
            .expect("цикл повторов не найден — разметка переехала");
        let конец_цикла = tail
            .find("let (status_code, body) = match response")
            .expect("разбор ответа после цикла не найден — разметка переехала");
        let сборка = tail
            .find("собрать_запрос(&client")
            .expect("🔴 запрос больше не собирается в check_auth");
        let тело = tail
            .find("serde_json::to_vec(&req)")
            .expect("🔴 тело больше не сериализуется явно — свёртка считалась бы не от тех байт");
        let ключ = tail
            .find("DeviceKey::load_or_create(app_config_dir)")
            .expect("🔴 ключ устройства больше не берётся в check_auth");

        assert!(
            цикл < сборка && сборка < конец_цикла,
            "🔴 сборка запроса обязана быть ВНУТРИ цикла повторов: метка времени и одноразовое \
             число обязаны быть свои у каждой попытки"
        );
        assert!(
            тело < цикл,
            "🔴 тело обязано сериализоваться ОДИН раз до цикла: байты у всех попыток одни и те же"
        );
        assert!(
            ключ < цикл,
            "ключ устройства один на все попытки — читать его с диска в цикле незачем"
        );
        assert!(
            !tail[цикл..конец_цикла].contains(".json(&req)"),
            "🔴 в цикле не должно остаться отправки через `.json(&req)`: она сериализует тело \
             сама, и свёртка считалась бы не от уходящих байт"
        );
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
