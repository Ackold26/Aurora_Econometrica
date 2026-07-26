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
use super::{content_pack, vault};

/// Supabase Edge Functions base URL (obfuscated at compile time).
fn supabase_url() -> String {
    obfstr::obfstr!("https://quzhkfvglqmppxcrindh.supabase.co/functions/v1").to_string()
}

// ── Устойчивость канала доставки (2026-07-26, разбор отказа у клиента) ──
//
// Обрыв TLS/тела на середине ответа — штатное поведение нестабильного канала
// (посредник закрывает сессию без close_notify; rustls внутри reqwest сообщает
// об этом как «error decoding response body»), а НЕ признак мёртвого сервера.
// Лечится повтором, а не увеличением таймаута: общий дедлайн на запрос рубит
// и исправную медленную докачку тоже (у клиента ошибка приходила ровно через
// 120 с — это срабатывал общий таймаут, а не отказ сервера).
//
// Файлы забираются ПО ЧАСТЯМ (HTTP Range), а не целиком. Причина — приёмка
// 2.4.1 на машине клиента 26.07.2026: повторы и раздельные таймауты работали,
// но не лечили, потому что посредник в сети клиента обрывает ответ примерно
// после 4 КБ. Файлы 2,0–2,9 КБ доходили все, 20 и 34 КБ — ни разу: 10 обрывов
// из 10 на 3251…5649 байт. Против такого порога бессильны и увеличенный
// таймаут, и любое число повторов — каждая попытка упирается в него заново.
// Единственное лечение — не просить у сервера кусок больше порога.
//
// Сервер, который частей не умеет (старая сборка функции, посторонний адрес),
// отвечает на запрос с Range кодом 200 и телом целиком — этот путь сохранён,
// поэтому правка обратно совместима.

/// Таймаут установки соединения.
const CONNECT_TIMEOUT_SECS: u64 = 20;

/// Таймаут ТИШИНЫ сокета: столько ждём очередную порцию данных.
/// Не общий дедлайн запроса — медленный, но живой канал не обрывается.
const READ_IDLE_TIMEOUT_SECS: u64 = 30;

/// Сколько раз пытаемся забрать файл при обрыве связи.
const DOWNLOAD_ATTEMPTS: u32 = 5;

/// Паузы перед повторами (секунды): даём каналу восстановиться.
const RETRY_BACKOFF_SECS: [u64; 4] = [2, 5, 10, 20];

/// Верхняя граница ОДНОЙ попытки. Общего дедлайна на запрос нет намеренно
/// (он рубит исправную медленную передачу), но и вовсе без границы попытка
/// зависнет навсегда, если сервер шлёт по байту чаще, чем раз в READ_IDLE:
/// таймаут тишины в такой передаче не срабатывает никогда (находка аудита H-4).
/// Значение с большим запасом: наши файлы — единицы–десятки КБ.
///
/// Бюджет считается на ОДИН запрос куска, а не на сборку файла целиком:
/// иначе исправная, но медленная докачка из полутора десятков кусков рубилась
/// бы на середине — ровно та ошибка, из-за которой отвергнут общий дедлайн.
const ATTEMPT_BUDGET_SECS: u64 = 180;

/// Размер куска при докачке по частям.
///
/// Два килобайта — заведомо ниже наблюдённого у клиента порога обрыва
/// (минимальный зафиксированный обрыв — 3251 байт), с запасом на разброс
/// порога у других посредников. Цена — лишние запросы: файл кабинета в 34 КБ
/// собирается за 17 обращений вместо одного.
const RANGE_CHUNK_BYTES: u64 = 2048;

/// Потолок предварительного резерва памяти под тело ответа.
///
/// Длину объявляет сервер, и доверять ей на слово нельзя: ответ со сломанным
/// или злонамеренным `Content-Length` заставил бы выделить память ДО чтения
/// хотя бы одного байта тела. Дальше буфер растёт естественно, по мере
/// поступления данных.
const MAX_PREALLOC_BYTES: u64 = 8 * 1024 * 1024;

/// Жёсткий потолок на тело одного ответа: дальше чтение обрывается ошибкой.
/// Через этот путь ходят файлы кабинетов и пакеты контента — запас огромен.
const MAX_BODY_BYTES: usize = 256 * 1024 * 1024;

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

/// Выбрать номер версии для записи в vault-versions.json после докачки кабинета.
///
/// Per-cabinet версия сервера (`vault_versions[cab_id]`) точнее глобального
/// content_version: счётчики независимы, и если vault-версия кабинета численно
/// обгоняет content_version (правка промптов без правки content-pack), запись
/// глобального номера оставляла бы `local < server` навсегда → клиент
/// перекачивал бы кабинет на КАЖДОМ старте. Fallback на content_version — для
/// missing-докачки новых кабинетов и старого сервера без vault_versions (нулевая
/// регрессия). Найдено внешним diff-аудитом Батча 0 (2026-07-13).
fn resolve_vault_version(
    cab_id: &str,
    vault_versions: Option<&HashMap<String, u32>>,
    content_version: &str,
) -> u32 {
    vault_versions
        .and_then(|vv| vv.get(cab_id).copied())
        .unwrap_or_else(|| content_version.trim_start_matches('c').parse().unwrap_or(0))
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
    let needs_update = !matches!(&local_ver, Some(lv) if lv == sv);

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

/// HTTP-клиент для докачек: без общего дедлайна на запрос, с раздельными
/// таймаутами соединения и тишины сокета (см. блок констант выше).
fn resilient_client() -> Result<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .connect_timeout(std::time::Duration::from_secs(CONNECT_TIMEOUT_SECS))
        .read_timeout(std::time::Duration::from_secs(READ_IDLE_TIMEOUT_SECS))
        .build()?)
}

/// Исход одной попытки скачивания.
enum FetchFailure {
    /// Связь: обрыв, таймаут, 5xx, 429 — имеет смысл повторить.
    Transient(anyhow::Error),
    /// Отказ по существу: 403 (нет лицензии), 404 (нет файла) — повтор не поможет.
    Fatal(anyhow::Error),
}

/// Прочитать тело ответа порциями, отличая честное завершение от обрыва.
///
/// `res.bytes()` на оборванном потоке отдаёт то же самое «error decoding
/// response body» без единой цифры — по журналу клиента невозможно понять,
/// пришло 0 байт или почти всё. Поэтому читаем сами и сообщаем, сколько
/// успели получить и сколько обещал сервер.
async fn read_body_counted(mut res: reqwest::Response, what: &str) -> Result<Vec<u8>> {
    let declared = res.content_length();
    // Резерв ограничен сверху намеренно: заявленная сервером длина — это его
    // слово, а не факт, и по ней нельзя выделять память до чтения тела.
    let mut buf: Vec<u8> = match declared {
        Some(n) => Vec::with_capacity(n.min(MAX_PREALLOC_BYTES) as usize),
        None => Vec::new(),
    };

    loop {
        match res.chunk().await {
            Ok(Some(chunk)) => {
                buf.extend_from_slice(&chunk);
                if buf.len() > MAX_BODY_BYTES {
                    anyhow::bail!(
                        "{}: ответ превысил {} МБ и оборван — столько наши файлы не весят",
                        what,
                        MAX_BODY_BYTES / (1024 * 1024)
                    );
                }
            }
            Ok(None) => break,
            Err(e) => anyhow::bail!(
                "{}: поток оборван на {} байт (сервер обещал {}): {}",
                what,
                buf.len(),
                declared.map(|n| n.to_string()).unwrap_or_else(|| "неизвестно".into()),
                e
            ),
        }
    }

    // Усечение без ошибки сокета: посредник закрыл соединение «чисто».
    if let Some(n) = declared {
        if buf.len() as u64 != n {
            anyhow::bail!("{}: получено {} байт из обещанных {}", what, buf.len(), n);
        }
    }

    Ok(buf)
}

/// Что сервер ответил на запрос куска.
enum RangeReply {
    /// 206: кусок файла и полный размер, сообщённый в `Content-Range`.
    Part { bytes: Vec<u8>, total: u64 },
    /// 200: отдавать части сервер не умеет и прислал файл целиком.
    Whole(Vec<u8>),
}

/// Полный размер файла из заголовка `Content-Range` вида `bytes 0-2047/34165`.
fn parse_content_range_total(value: &str) -> Option<u64> {
    value.rsplit('/').next()?.trim().parse::<u64>().ok()
}

/// Запросить у сервера один кусок файла (границы включительные).
async fn request_range(
    client: &reqwest::Client,
    url: &str,
    start: u64,
    end: u64,
    what: &str,
) -> std::result::Result<RangeReply, FetchFailure> {
    let res = client
        .get(url)
        .header(reqwest::header::RANGE, format!("bytes={start}-{end}"))
        .send()
        .await
        .map_err(|e| FetchFailure::Transient(anyhow::anyhow!("{}: запрос не прошёл: {}", what, e)))?;

    let status = res.status();

    if status == reqwest::StatusCode::PARTIAL_CONTENT {
        let total = res
            .headers()
            .get(reqwest::header::CONTENT_RANGE)
            .and_then(|v| v.to_str().ok())
            .and_then(parse_content_range_total);
        // Кусок без внятного полного размера бесполезен: собрать по нему файл
        // нельзя — не с чем сверить итог, и усечение прошло бы незамеченным.
        let Some(total) = total else {
            return Err(FetchFailure::Transient(anyhow::anyhow!(
                "{}: сервер отдал часть файла, не сообщив полный размер",
                what
            )));
        };
        let bytes = read_body_counted(res, what).await.map_err(FetchFailure::Transient)?;
        return Ok(RangeReply::Part { bytes, total });
    }

    if status.is_success() {
        let bytes = read_body_counted(res, what).await.map_err(FetchFailure::Transient)?;
        return Ok(RangeReply::Whole(bytes));
    }

    let body = res.text().await.unwrap_or_default();
    let err = anyhow::anyhow!("Download failed for {}: HTTP {} - {}", what, status, body);
    // 5xx и 429 — сторона сервера/лимиты, повторяем. Прочие 4xx — по существу.
    Err(if status.is_server_error()
        || status == reqwest::StatusCode::TOO_MANY_REQUESTS
        || status == reqwest::StatusCode::REQUEST_TIMEOUT
    {
        FetchFailure::Transient(err)
    } else {
        FetchFailure::Fatal(err)
    })
}

/// Одна попытка забрать файл — по частям, кусками ниже порога обрыва.
///
/// Первый запрос всегда просит первый кусок. Сервер, умеющий отдавать части,
/// отвечает 206 и сообщает полный размер — дальше добираем до конца. Сервер,
/// который не умеет, отвечает 200 и телом целиком: это прежнее поведение,
/// сохранённое ради обратной совместимости.
async fn fetch_vault_once(
    client: &reqwest::Client,
    url: &str,
    filename: &str,
) -> std::result::Result<Vec<u8>, FetchFailure> {
    let first = attempt_with_budget(
        request_range(client, url, 0, RANGE_CHUNK_BYTES - 1, filename),
        filename,
    )
    .await?;

    let (mut buf, total) = match first {
        RangeReply::Whole(bytes) => return Ok(bytes),
        RangeReply::Part { bytes, total } => (bytes, total),
    };

    while (buf.len() as u64) < total {
        let start = buf.len() as u64;
        let end = (start + RANGE_CHUNK_BYTES - 1).min(total - 1);

        let reply = attempt_with_budget(
            request_range(client, url, start, end, filename),
            filename,
        )
        .await?;

        match reply {
            RangeReply::Part { bytes, total: reported } => {
                // Файл на сервере подменили посреди докачки — склеивать куски
                // разных версий нельзя, начинаем попытку заново.
                if reported != total {
                    return Err(FetchFailure::Transient(anyhow::anyhow!(
                        "{}: размер файла на сервере изменился при докачке ({} вместо {})",
                        filename,
                        reported,
                        total
                    )));
                }
                // Пустой кусок не сдвигает сборку с места: без этой проверки
                // цикл крутился бы вечно, запрашивая один и тот же байт.
                if bytes.is_empty() {
                    return Err(FetchFailure::Transient(anyhow::anyhow!(
                        "{}: сервер отдал пустой кусок с байта {} из {} — докачка не движется",
                        filename,
                        start,
                        total
                    )));
                }
                buf.extend_from_slice(&bytes);
            }
            RangeReply::Whole(bytes) => {
                // Сервер перестал понимать части на середине (смена узла,
                // посредник). Принимаем целый файл, только если он той длины,
                // о которой сервер сам сообщил в начале.
                if bytes.len() as u64 == total {
                    return Ok(bytes);
                }
                return Err(FetchFailure::Transient(anyhow::anyhow!(
                    "{}: на запрос куска пришёл файл целиком неверной длины ({} вместо {})",
                    filename,
                    bytes.len(),
                    total
                )));
            }
        }
    }

    if buf.len() as u64 != total {
        return Err(FetchFailure::Transient(anyhow::anyhow!(
            "{}: собрано {} байт из {}",
            filename,
            buf.len(),
            total
        )));
    }

    Ok(buf)
}

/// Ограничить один запрос сверху (H-4). Истечение бюджета — это связь,
/// а не отказ по существу: считаем повторяемым.
async fn attempt_with_budget<T, F>(fut: F, what: &str) -> std::result::Result<T, FetchFailure>
where
    F: std::future::Future<Output = std::result::Result<T, FetchFailure>>,
{
    match tokio::time::timeout(std::time::Duration::from_secs(ATTEMPT_BUDGET_SECS), fut).await {
        Ok(r) => r,
        Err(_) => Err(FetchFailure::Transient(anyhow::anyhow!(
            "{}: попытка не уложилась в {} с — передача идёт слишком медленно",
            what,
            ATTEMPT_BUDGET_SECS
        ))),
    }
}

/// Скачать vault-файл с сервера, переживая обрывы канала.
async fn download_vault_file(
    fingerprint_hash: &str,
    product: &str,
    version: &str,
    filename: &str,
) -> Result<Vec<u8>> {
    let client = resilient_client()?;

    let url = format!(
        "{}/content?fingerprint_hash={}&product={}&version={}&file={}",
        supabase_url(), fingerprint_hash, product, version, filename
    );

    info!("Downloading vault: {}", filename);

    let mut last_err: Option<anyhow::Error> = None;

    for attempt in 1..=DOWNLOAD_ATTEMPTS {
        match fetch_vault_once(&client, &url, filename).await {
            Ok(bytes) => {
                if attempt > 1 {
                    info!("Vault {} получен с попытки {}/{} ({} байт)", filename, attempt, DOWNLOAD_ATTEMPTS, bytes.len());
                }
                return Ok(bytes);
            }
            Err(FetchFailure::Fatal(e)) => {
                error!("Скачивание {} отклонено сервером: {:#}", filename, e);
                return Err(e);
            }
            Err(FetchFailure::Transient(e)) => {
                warn!("Скачивание {}: попытка {}/{} не удалась: {:#}", filename, attempt, DOWNLOAD_ATTEMPTS, e);
                last_err = Some(e);
                if attempt < DOWNLOAD_ATTEMPTS {
                    let idx = ((attempt - 1) as usize).min(RETRY_BACKOFF_SECS.len() - 1);
                    tokio::time::sleep(std::time::Duration::from_secs(RETRY_BACKOFF_SECS[idx])).await;
                }
            }
        }
    }

    Err(last_err.unwrap_or_else(|| anyhow::anyhow!("{}: скачивание не удалось", filename)))
        .with_context(|| format!("{}: связь с сервером не установилась за {} попыток", filename, DOWNLOAD_ATTEMPTS))
}

/// Скачать произвольный файл (пакет контента, бандл фронтенда) с теми же
/// гарантиями, что и vault: без общего дедлайна, с повторами при обрыве.
/// Пакеты весят десятки мегабайт — на слабом канале общий таймаут в 120 с
/// рубил их гарантированно, даже когда передача исправно шла.
async fn download_url_resilient(url: &str, what: &str) -> Result<Vec<u8>> {
    let client = resilient_client()?;
    let mut last_err: Option<anyhow::Error> = None;

    for attempt in 1..=DOWNLOAD_ATTEMPTS {
        match fetch_vault_once(&client, url, what).await {
            Ok(bytes) => {
                if attempt > 1 {
                    info!("{} получен с попытки {}/{} ({} байт)", what, attempt, DOWNLOAD_ATTEMPTS, bytes.len());
                }
                return Ok(bytes);
            }
            Err(FetchFailure::Fatal(e)) => {
                error!("Скачивание {} отклонено сервером: {:#}", what, e);
                return Err(e);
            }
            Err(FetchFailure::Transient(e)) => {
                warn!("Скачивание {}: попытка {}/{} не удалась: {:#}", what, attempt, DOWNLOAD_ATTEMPTS, e);
                last_err = Some(e);
                if attempt < DOWNLOAD_ATTEMPTS {
                    let idx = ((attempt - 1) as usize).min(RETRY_BACKOFF_SECS.len() - 1);
                    tokio::time::sleep(std::time::Duration::from_secs(RETRY_BACKOFF_SECS[idx])).await;
                }
            }
        }
    }

    Err(last_err.unwrap_or_else(|| anyhow::anyhow!("{}: скачивание не удалось", what)))
        .with_context(|| format!("{}: связь с сервером не установилась за {} попыток", what, DOWNLOAD_ATTEMPTS))
}

/// Download and save all updated vault files.
/// Returns the list of successfully updated files.
/// If `app_handle` is provided, emits "vault-download-progress" events.
// 8 параметров — все суть данные докачки (пути, product/version, files,
// checksums, per-cabinet версии, app_handle); группировать в struct избыточно
// для внутренней функции с 4 фиксированными call-site.
#[allow(clippy::too_many_arguments)]
pub async fn download_updates(
    app_config_dir: &Path,
    app_data_dir: &Path,
    product: &str,
    version: &str,
    files: &[String],
    checksums: &serde_json::Value,
    vault_versions: Option<&HashMap<String, u32>>,
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
    let mut last_error: Option<anyhow::Error> = None;

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

                // Track per-cabinet version in vault-versions.json — номер из
                // per-cabinet карты сервера, а не глобального content_version
                // (см. resolve_vault_version: рассинхрон двух счётчиков иначе
                // зациклил бы докачку кабинета на каждом старте).
                if let Some(stem) = filename.strip_suffix(".vault") {
                    let cab_id = stem_to_cabinet_id(stem);
                    let ver_num = resolve_vault_version(cab_id, vault_versions, version);
                    if ver_num > 0 {
                        if let Err(e) = set_vault_version(app_config_dir, cab_id, ver_num) {
                            warn!("Failed to record per-cabinet version for {}: {}", cab_id, e);
                        }
                    }
                }
            }
            Err(e) => {
                error!("Failed to download {}: {}", filename, e);
                // Причину держим при себе: без неё вызывающий видит пустой
                // список и сообщает пользователю «сервер не отдал файл», хотя
                // на деле оборвалась передача на N байт (находка аудита H-1).
                last_error = Some(e);
            }
        }
    }

    // Ни один файл не доехал, и причина известна — отдаём её наружу, а не
    // пустой список: иначе пользователь получает домысел вместо факта (H-1).
    if updated.is_empty() && !files.is_empty() {
        if let Some(e) = last_error {
            return Err(e);
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

// ── Content Pack Version ───────────────────────────────────

/// Read the locally installed content pack version from its manifest.json.
/// Returns 0 if no content packs are installed yet.
pub fn get_local_content_pack_version(app_local_data_dir: &Path) -> u32 {
    let manifest_path = content_pack::content_packs_dir(app_local_data_dir).join("manifest.json");
    std::fs::read_to_string(&manifest_path)
        .ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .and_then(|v| v["version"].as_u64())
        .map(|v| v as u32)
        .unwrap_or(0)
}

/// Read the locally installed frontend bundle version.
/// Returns 0 if no frontend bundle is installed yet.
pub fn get_local_frontend_version(app_local_data_dir: &Path) -> u32 {
    let version_file = app_local_data_dir.join("current_frontend_version.txt");
    std::fs::read_to_string(&version_file)
        .ok()
        .and_then(|s| s.trim().trim_start_matches('v').parse::<u32>().ok())
        .unwrap_or(0)
}

// ── Content Pack Download (Phase 5) ───────────────────────

/// Download and install a content pack from a direct URL.
///
/// Downloads tar.gz, verifies SHA-256 checksum, verifies Ed25519 manifest
/// signature, then atomically installs it as the new content-packs directory.
pub async fn download_content_pack(
    app_local_data_dir: &Path,
    url: &str,
    expected_checksum: &str,
    app_handle: &tauri::AppHandle,
) -> Result<()> {
    info!("Downloading content pack from URL");
    let _ = app_handle.emit("content-pack-update-progress", serde_json::json!({ "stage": "connecting" }));

    let bytes = download_url_resilient(url, "пакет контента").await?;
    info!("Downloaded content pack ({} bytes)", bytes.len());

    // Verify bundle checksum
    if !expected_checksum.is_empty() {
        let hash = format!("sha256:{:x}", Sha256::digest(&bytes));
        if hash != expected_checksum {
            anyhow::bail!(
                "Content pack checksum mismatch: expected {}, got {}",
                expected_checksum,
                hash
            );
        }
    }

    let _ = app_handle.emit("content-pack-update-progress", serde_json::json!({
        "stage": "extracting",
        "bytes": bytes.len(),
    }));

    // Extract to staging directory
    let staging_dir = app_local_data_dir.join("content-packs-new");
    if staging_dir.exists() {
        std::fs::remove_dir_all(&staging_dir)
            .context("Failed to remove stale content-pack staging dir")?;
    }
    std::fs::create_dir_all(&staging_dir)
        .context("Failed to create content-pack staging dir")?;

    let cursor = std::io::Cursor::new(bytes.as_slice());
    let gz = flate2::read::GzDecoder::new(cursor);
    let mut archive = tar::Archive::new(gz);
    archive.unpack(&staging_dir)
        .context("Failed to unpack content pack")?;

    // Verify manifest signature BEFORE making it live
    crate::crypto::content_sig::verify_manifest(&staging_dir)
        .context("Content pack manifest verification failed")?;

    let _ = app_handle.emit("content-pack-update-progress", serde_json::json!({ "stage": "installing" }));

    // Atomic swap: current → backup, new → current
    let current_dir = content_pack::content_packs_dir(app_local_data_dir);
    let backup_dir = app_local_data_dir.join("content-packs-old");

    if current_dir.exists() {
        if backup_dir.exists() {
            let _ = std::fs::remove_dir_all(&backup_dir);
        }
        std::fs::rename(&current_dir, &backup_dir)
            .context("Failed to backup current content packs")?;
    }
    std::fs::rename(&staging_dir, &current_dir)
        .context("Failed to install new content packs")?;
    let _ = std::fs::remove_dir_all(&backup_dir); // best-effort cleanup

    info!("Content pack installed successfully");
    Ok(())
}

// ── Frontend Bundle Download ───────────────────────────────

/// Download and install a frontend bundle from the server.
///
/// Downloads a tar.gz archive containing the SvelteKit build output,
/// verifies manifest.sig, then atomically installs it as the next
/// versioned frontend directory in app_local_data_dir.
///
/// On success the version pointer (`current_frontend_version.txt`) is updated.
/// The caller should prompt the user to restart the app.
///
/// NOTE: The `/frontend-bundle` Edge Function is implemented in Phase 5.
pub async fn download_frontend_bundle(
    app_local_data_dir: &Path,
    product: &str,
    app_handle: &tauri::AppHandle,
) -> Result<()> {
    let url = format!("{}/frontend-bundle?product={}", supabase_url(), product);

    info!("Downloading frontend bundle: product={}", product);

    let _ = app_handle.emit("frontend-repair-progress", serde_json::json!({ "stage": "connecting" }));

    let bytes = download_url_resilient(&url, "бандл фронтенда").await
        .map_err(|e| {
            // Отсутствие бандла на сервере — отдельный случай для вызывающего.
            if format!("{:#}", e).contains("HTTP 404") {
                anyhow::anyhow!("Frontend bundle not available on server for product={}", product)
            } else {
                e
            }
        })?;
    info!("Downloaded frontend bundle ({} bytes)", bytes.len());

    let _ = app_handle.emit("frontend-repair-progress", serde_json::json!({
        "stage": "extracting",
        "bytes": bytes.len(),
    }));

    // Compute next version number
    let version_file = app_local_data_dir.join("current_frontend_version.txt");
    let current_v = std::fs::read_to_string(&version_file).unwrap_or_else(|_| "v0".to_string());
    let next_n = current_v.trim().trim_start_matches('v')
        .parse::<u32>()
        .unwrap_or(0)
        .saturating_add(1);
    let next_version = format!("v{}", next_n);

    // Extract to staging directory
    let staging_dir = app_local_data_dir.join(format!("frontend-{}-staging", next_version));
    if staging_dir.exists() {
        std::fs::remove_dir_all(&staging_dir)
            .context("Failed to remove stale staging dir")?;
    }
    std::fs::create_dir_all(&staging_dir)
        .context("Failed to create staging dir")?;

    let cursor = std::io::Cursor::new(bytes.as_slice());
    let gz = flate2::read::GzDecoder::new(cursor);
    let mut archive = tar::Archive::new(gz);
    archive.unpack(&staging_dir)
        .context("Failed to unpack frontend bundle")?;

    // Verify manifest signature BEFORE making it live
    crate::crypto::content_sig::verify_manifest(&staging_dir)
        .context("Frontend bundle manifest verification failed")?;

    info!("Frontend staging verified - installing as {}", next_version);

    let _ = app_handle.emit("frontend-repair-progress", serde_json::json!({
        "stage": "installing",
        "version": next_version,
    }));

    // Move staging → final directory
    let final_dir = app_local_data_dir.join(format!("frontend-{}", next_version));
    if final_dir.exists() {
        std::fs::remove_dir_all(&final_dir)?;
    }
    std::fs::rename(&staging_dir, &final_dir)
        .context("Failed to move staged frontend into place")?;

    // Atomically update version pointer (write tmp, then rename)
    let tmp_version = version_file.with_extension("tmp");
    std::fs::write(&tmp_version, &next_version)?;
    std::fs::rename(&tmp_version, &version_file)?;

    info!("Frontend bundle installed: {}", next_version);
    Ok(())
}

/// Download and install a frontend bundle from a direct URL with checksum verification.
///
/// Phase 5 variant: accepts pre-signed URL + checksum + explicit version number
/// from the /auth response, rather than constructing the URL from the product name.
pub async fn download_frontend_bundle_from_url(
    app_local_data_dir: &Path,
    url: &str,
    expected_checksum: &str,
    version: u32,
    app_handle: &tauri::AppHandle,
) -> Result<()> {
    info!("Downloading frontend bundle v{} from URL", version);
    let _ = app_handle.emit("frontend-repair-progress", serde_json::json!({ "stage": "connecting" }));

    let bytes = download_url_resilient(url, "бандл фронтенда").await?;
    info!("Downloaded frontend bundle ({} bytes)", bytes.len());

    // Verify bundle checksum
    if !expected_checksum.is_empty() {
        let hash = format!("sha256:{:x}", Sha256::digest(&bytes));
        if hash != expected_checksum {
            anyhow::bail!(
                "Frontend bundle checksum mismatch: expected {}, got {}",
                expected_checksum,
                hash
            );
        }
    }

    let _ = app_handle.emit("frontend-repair-progress", serde_json::json!({
        "stage": "extracting",
        "bytes": bytes.len(),
    }));

    // Extract to staging directory
    let next_version = format!("v{}", version);
    let staging_dir = app_local_data_dir.join(format!("frontend-{}-staging", next_version));
    if staging_dir.exists() {
        std::fs::remove_dir_all(&staging_dir)
            .context("Failed to remove stale frontend staging dir")?;
    }
    std::fs::create_dir_all(&staging_dir)
        .context("Failed to create frontend staging dir")?;

    let cursor = std::io::Cursor::new(bytes.as_slice());
    let gz = flate2::read::GzDecoder::new(cursor);
    let mut archive = tar::Archive::new(gz);
    archive.unpack(&staging_dir)
        .context("Failed to unpack frontend bundle")?;

    // Verify manifest signature BEFORE making it live
    crate::crypto::content_sig::verify_manifest(&staging_dir)
        .context("Frontend bundle manifest verification failed")?;

    info!("Frontend staging verified - installing as {}", next_version);
    let _ = app_handle.emit("frontend-repair-progress", serde_json::json!({
        "stage": "installing",
        "version": &next_version,
    }));

    // Move staging → final directory
    let final_dir = app_local_data_dir.join(format!("frontend-{}", next_version));
    if final_dir.exists() {
        std::fs::remove_dir_all(&final_dir)?;
    }
    std::fs::rename(&staging_dir, &final_dir)
        .context("Failed to move staged frontend into place")?;

    // Atomically update version pointer
    let version_file = app_local_data_dir.join("current_frontend_version.txt");
    let tmp_version_file = version_file.with_extension("tmp");
    std::fs::write(&tmp_version_file, &next_version)?;
    std::fs::rename(&tmp_version_file, &version_file)?;

    // Cleanup old versions (keep current and one previous)
    cleanup_old_frontend_versions(app_local_data_dir, version);

    info!("Frontend bundle v{} installed, restart required", version);
    app_handle.emit("frontend-updated", version)?;
    Ok(())
}

/// Remove frontend-vN directories older than (current_version - 1).
fn cleanup_old_frontend_versions(app_local_data_dir: &Path, current_version: u32) {
    if current_version < 2 {
        return;
    }
    let keep_from = current_version.saturating_sub(1);
    if let Ok(entries) = std::fs::read_dir(app_local_data_dir) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let s = name.to_string_lossy();
            if let Some(suffix) = s.strip_prefix("frontend-v") {
                // Skip staging dirs
                if suffix.ends_with("-staging") {
                    continue;
                }
                if let Ok(ver) = suffix.parse::<u32>() {
                    if ver < keep_from {
                        let _ = std::fs::remove_dir_all(entry.path());
                        info!("Removed old frontend version: {}", s);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use tempfile::TempDir;

    // ── Устойчивость докачки (разбор отказа у клиента 2026-07-26) ─────────────
    //
    // Гейт против возврата хрупкого загрузчика: обрыв тела обязан лечиться
    // повтором, отказ по существу (403/404) — не должен порождать повторов.

    /// Что тестовый сервер делает с очередным соединением.
    #[derive(Clone)]
    enum Scenario {
        /// Отдать тело целиком.
        Full(Vec<u8>),
        /// Объявить Content-Length, отдать только часть и закрыть сокет.
        Truncated(Vec<u8>, usize),
        /// Ответить кодом состояния без тела.
        Status(u16),
        /// Посредник из сети клиента: сервер умеет отдавать части, но всё, что
        /// длиннее порога, обрывается на нём. Куски ниже порога проходят.
        RangeAware { body: Vec<u8>, threshold: usize },
        /// Сервер без поддержки частей: на Range отвечает 200 и телом целиком,
        /// но тот же порог обрыва действует (старая сборка функции).
        NoRangeSupport { body: Vec<u8>, threshold: usize },
        /// Отдаёт пустой кусок: сборка не двигается с места.
        EmptyChunk { total: usize },
        /// На втором и следующих кусках сообщает другой полный размер:
        /// файл на сервере подменили посреди докачки.
        ShiftingTotal { body: Vec<u8> },
    }

    /// Границы из заголовка `Range` запроса (включительные).
    fn requested_range(req: &str) -> Option<(usize, usize)> {
        let line = req.lines().find(|l| l.to_ascii_lowercase().starts_with("range:"))?;
        let spec = line.split('=').nth(1)?.trim();
        let (s, e) = spec.split_once('-')?;
        Some((s.trim().parse().ok()?, e.trim().parse().ok()?))
    }

    /// Поднять локальный сервер, отрабатывающий сценарии по очереди.
    /// Возвращает базовый адрес и счётчик принятых соединений.
    async fn spawn_test_server(
        scenarios: Vec<Scenario>,
    ) -> (String, std::sync::Arc<std::sync::atomic::AtomicUsize>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let hits = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let hits_srv = hits.clone();

        tokio::spawn(async move {
            let mut idx = 0usize;
            loop {
                let (mut sock, _) = match listener.accept().await {
                    Ok(v) => v,
                    Err(_) => return,
                };
                hits_srv.fetch_add(1, std::sync::atomic::Ordering::SeqCst);

                // Дочитываем запрос до пустой строки, иначе клиент увидит reset.
                let mut buf = [0u8; 1024];
                let read = sock.read(&mut buf).await.unwrap_or(0);
                let req = String::from_utf8_lossy(&buf[..read]).to_string();

                let scenario = scenarios
                    .get(idx)
                    .cloned()
                    .unwrap_or_else(|| scenarios.last().cloned().unwrap());
                idx += 1;

                match scenario {
                    Scenario::Full(body) => {
                        let head = format!(
                            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                            body.len()
                        );
                        let _ = sock.write_all(head.as_bytes()).await;
                        let _ = sock.write_all(&body).await;
                    }
                    Scenario::Truncated(body, cut) => {
                        let head = format!(
                            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                            body.len()
                        );
                        let _ = sock.write_all(head.as_bytes()).await;
                        let _ = sock.write_all(&body[..cut]).await;
                    }
                    Scenario::Status(code) => {
                        let head = format!(
                            "HTTP/1.1 {} STATUS\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                            code
                        );
                        let _ = sock.write_all(head.as_bytes()).await;
                    }
                    Scenario::RangeAware { body, threshold } => {
                        let total = body.len();
                        let (start, end) = match requested_range(&req) {
                            Some((s, e)) => (s.min(total), e.min(total - 1)),
                            // Range не запрошен — отдаём целиком и упираемся в порог.
                            None => (0, total - 1),
                        };
                        let piece = &body[start..=end];
                        let status = if requested_range(&req).is_some() { 206 } else { 200 };
                        let mut head = format!(
                            "HTTP/1.1 {} OK\r\nContent-Length: {}\r\nAccept-Ranges: bytes\r\nConnection: close\r\n",
                            status,
                            piece.len()
                        );
                        if status == 206 {
                            head.push_str(&format!("Content-Range: bytes {}-{}/{}\r\n", start, end, total));
                        }
                        head.push_str("\r\n");
                        let _ = sock.write_all(head.as_bytes()).await;
                        // Порог посредника: всё, что длиннее, обрывается на нём.
                        let cut = piece.len().min(threshold);
                        let _ = sock.write_all(&piece[..cut]).await;
                    }
                    Scenario::NoRangeSupport { body, threshold } => {
                        let head = format!(
                            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                            body.len()
                        );
                        let _ = sock.write_all(head.as_bytes()).await;
                        let cut = body.len().min(threshold);
                        let _ = sock.write_all(&body[..cut]).await;
                    }
                    Scenario::EmptyChunk { total } => {
                        let (start, end) = requested_range(&req).unwrap_or((0, 0));
                        let head = format!(
                            "HTTP/1.1 206 OK\r\nContent-Length: 0\r\nContent-Range: bytes {}-{}/{}\r\nConnection: close\r\n\r\n",
                            start, end, total
                        );
                        let _ = sock.write_all(head.as_bytes()).await;
                    }
                    Scenario::ShiftingTotal { body } => {
                        let total = body.len();
                        let (start, end) = requested_range(&req).unwrap_or((0, total - 1));
                        let end = end.min(total - 1);
                        let piece = &body[start..=end];
                        // Первый кусок честен, дальше полный размер «уезжает».
                        let reported = if start == 0 { total } else { total + 4096 };
                        let head = format!(
                            "HTTP/1.1 206 OK\r\nContent-Length: {}\r\nContent-Range: bytes {}-{}/{}\r\nConnection: close\r\n\r\n",
                            piece.len(), start, end, reported
                        );
                        let _ = sock.write_all(head.as_bytes()).await;
                        let _ = sock.write_all(piece).await;
                    }
                }
                let _ = sock.shutdown().await;
            }
        });

        (format!("http://{}/file", addr), hits)
    }

    #[tokio::test]
    async fn download_survives_broken_stream() {
        let body: Vec<u8> = (0..4096u32).map(|i| (i % 251) as u8).collect();
        let (url, hits) = spawn_test_server(vec![
            Scenario::Truncated(body.clone(), 1000),
            Scenario::Full(body.clone()),
        ])
        .await;

        let got = download_url_resilient(&url, "тестовый файл").await.unwrap();

        assert_eq!(got, body, "после повтора файл должен прийти целиком");
        assert_eq!(
            hits.load(std::sync::atomic::Ordering::SeqCst),
            2,
            "обрыв обязан приводить ровно к одному повтору"
        );
    }

    #[tokio::test]
    async fn truncated_body_is_not_accepted_as_success() {
        // Сервер всегда рвёт поток — обязаны получить ошибку, а не обрезанный файл.
        //
        // Честная оговорка (находка аудита M-4): здесь ошибку возвращает сам
        // слой HTTP — он видит объявленный Content-Length и ранний конец
        // соединения. Наша сверка длины в read_body_counted до срабатывания
        // не доходит и остаётся вторым слоем защиты: сценария «длина объявлена,
        // байт меньше, при этом обрыв чистый» протокол HTTP не допускает.
        // Собственная сверка итога проверяется на докачке по частям — там полный
        // размер берётся из Content-Range, и он наш, а не чужой
        // (см. `ranged_download_rejects_shifting_total` и `..._empty_chunk`).
        let body: Vec<u8> = vec![7u8; 2048];
        let (url, _hits) = spawn_test_server(vec![Scenario::Truncated(body, 512)]).await;

        let err = download_url_resilient(&url, "тестовый файл").await.unwrap_err();
        let text = format!("{:#}", err);

        assert!(
            text.contains("байт"),
            "ошибка обязана называть, сколько байт получено: {text}"
        );
    }

    // ── Докачка по частям (порог обрыва у клиента, 2026-07-26) ────────────────

    /// Размер файла кабинета, на котором вскрылся отказ у клиента.
    const VAULT_SIZE: usize = 34165;

    /// Порог посредника: середина наблюдённого разброса обрывов (3251…5649).
    const PROXY_THRESHOLD: usize = 4096;

    fn sample_body(len: usize) -> Vec<u8> {
        (0..len).map(|i| (i % 251) as u8).collect()
    }

    #[tokio::test]
    async fn ranged_download_assembles_file_above_proxy_threshold() {
        // Главный гейт всей правки: файл заметно больше порога обрыва обязан
        // собраться кусками. Ровно этот файл (34 КБ) не доезжал у клиента ни
        // разу за две недели.
        let body = sample_body(VAULT_SIZE);
        let (url, hits) = spawn_test_server(vec![Scenario::RangeAware {
            body: body.clone(),
            threshold: PROXY_THRESHOLD,
        }])
        .await;

        let got = download_url_resilient(&url, "файл кабинета").await.unwrap();

        assert_eq!(got, body, "файл обязан собраться из кусков без потерь");
        let expected_chunks =
            (VAULT_SIZE as u64).div_ceil(RANGE_CHUNK_BYTES) as usize;
        assert_eq!(
            hits.load(std::sync::atomic::Ordering::SeqCst),
            expected_chunks,
            "лишние обращения к серверу — признак повторов, которых быть не должно"
        );
    }

    #[tokio::test]
    async fn whole_file_download_fails_at_the_same_threshold() {
        // Обратная сторона того же гейта: при том же пороге загрузка целиком
        // не проходит. Без неё первый тест доказывал бы лишь то, что сервер
        // исправен, а не то, что лечит именно докачка по частям.
        let body = sample_body(VAULT_SIZE);
        let (url, _hits) = spawn_test_server(vec![Scenario::NoRangeSupport {
            body,
            threshold: PROXY_THRESHOLD,
        }])
        .await;

        let err = download_url_resilient(&url, "файл кабинета").await.unwrap_err();
        let text = format!("{:#}", err);

        assert!(
            text.contains("байт"),
            "в ошибке обязано быть число полученных байт: {text}"
        );
    }

    #[tokio::test]
    async fn small_file_needs_one_request() {
        // Файлы меньше куска не должны дорожать: у клиента такие доезжали и
        // раньше, и лишние обращения им ни к чему.
        let body = sample_body(1500);
        let (url, hits) = spawn_test_server(vec![Scenario::RangeAware {
            body: body.clone(),
            threshold: PROXY_THRESHOLD,
        }])
        .await;

        let got = download_url_resilient(&url, "мелкий файл").await.unwrap();

        assert_eq!(got, body);
        assert_eq!(
            hits.load(std::sync::atomic::Ordering::SeqCst),
            1,
            "файл короче куска обязан приходить одним запросом"
        );
    }

    #[tokio::test]
    async fn server_without_range_support_still_works() {
        // Обратная совместимость: пока серверная правка не доехала (или адрес
        // посторонний), клиент обязан работать по-прежнему.
        let body = sample_body(9000);
        let (url, hits) = spawn_test_server(vec![Scenario::Full(body.clone())]).await;

        let got = download_url_resilient(&url, "файл со старого сервера").await.unwrap();

        assert_eq!(got, body, "сервер без поддержки частей обязан работать как раньше");
        assert_eq!(hits.load(std::sync::atomic::Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn ranged_download_rejects_empty_chunk() {
        // Пустой кусок не сдвигает сборку: без проверки цикл крутился бы вечно,
        // запрашивая один и тот же байт.
        let (url, _hits) = spawn_test_server(vec![Scenario::EmptyChunk { total: VAULT_SIZE }]).await;

        let err = tokio::time::timeout(
            std::time::Duration::from_secs(60),
            download_url_resilient(&url, "файл кабинета"),
        )
        .await
        .expect("пустой кусок обязан прерывать сборку, а не зацикливать её")
        .unwrap_err();

        assert!(
            format!("{:#}", err).contains("не движется"),
            "ошибка обязана называть причину: {err:#}"
        );
    }

    #[tokio::test]
    async fn ranged_download_rejects_shifting_total() {
        // Файл на сервере подменили посреди докачки — склеивать куски разных
        // версий нельзя: получился бы правдоподобный, но битый файл.
        let (url, _hits) = spawn_test_server(vec![Scenario::ShiftingTotal {
            body: sample_body(VAULT_SIZE),
        }])
        .await;

        let err = download_url_resilient(&url, "файл кабинета").await.unwrap_err();

        assert!(
            format!("{:#}", err).contains("изменился"),
            "ошибка обязана называть причину: {err:#}"
        );
    }

    #[test]
    fn content_range_total_is_parsed() {
        assert_eq!(parse_content_range_total("bytes 0-2047/34165"), Some(34165));
        assert_eq!(parse_content_range_total("bytes 34000-34164/34165"), Some(34165));
        // 416 сообщает полный размер тем же заголовком.
        assert_eq!(parse_content_range_total("bytes */34165"), Some(34165));
        // Полный размер неизвестен серверу — склеивать нечего, доверять нельзя.
        assert_eq!(parse_content_range_total("bytes 0-2047/*"), None);
        assert_eq!(parse_content_range_total("мусор"), None);
    }

    #[tokio::test]
    async fn client_error_is_not_retried() {
        let (url, hits) = spawn_test_server(vec![Scenario::Status(403)]).await;

        let err = download_url_resilient(&url, "тестовый файл").await.unwrap_err();

        assert!(format!("{:#}", err).contains("403"));
        assert_eq!(
            hits.load(std::sync::atomic::Ordering::SeqCst),
            1,
            "отказ по существу (403) не должен порождать повторы"
        );
    }

    #[tokio::test]
    async fn server_error_is_retried() {
        let body: Vec<u8> = vec![3u8; 128];
        let (url, hits) = spawn_test_server(vec![Scenario::Status(503), Scenario::Full(body.clone())]).await;

        let got = download_url_resilient(&url, "тестовый файл").await.unwrap();

        assert_eq!(got, body);
        assert_eq!(hits.load(std::sync::atomic::Ordering::SeqCst), 2);
    }

    // ── Local version (legacy) ────────────────────────────────────────────────

    #[test]
    fn test_get_local_version_no_file() {
        let dir = TempDir::new().unwrap();
        assert_eq!(get_local_version(dir.path()), None);
    }

    #[test]
    fn test_set_and_get_local_version() {
        let dir = TempDir::new().unwrap();
        set_local_version(dir.path(), "c5").unwrap();
        assert_eq!(get_local_version(dir.path()), Some("c5".to_string()));
        // Overwrite
        set_local_version(dir.path(), "c8").unwrap();
        assert_eq!(get_local_version(dir.path()), Some("c8".to_string()));
    }

    // ── Per-cabinet vault versions ────────────────────────────────────────────

    #[test]
    fn test_get_vault_versions_no_file() {
        let dir = TempDir::new().unwrap();
        let versions = get_vault_versions(dir.path());
        assert!(versions.is_empty());
    }

    #[test]
    fn test_set_and_get_vault_versions() {
        let dir = TempDir::new().unwrap();
        set_vault_version(dir.path(), "media-analyst", 5).unwrap();
        set_vault_version(dir.path(), "creative-director", 3).unwrap();

        let versions = get_vault_versions(dir.path());
        assert_eq!(versions.get("media-analyst"), Some(&5));
        assert_eq!(versions.get("creative-director"), Some(&3));
        assert_eq!(versions.get("social-listening"), None);
    }

    #[test]
    fn test_set_vault_version_overwrites_previous() {
        let dir = TempDir::new().unwrap();
        set_vault_version(dir.path(), "media-analyst", 1).unwrap();
        set_vault_version(dir.path(), "media-analyst", 7).unwrap();

        let versions = get_vault_versions(dir.path());
        assert_eq!(versions.get("media-analyst"), Some(&7));
        assert_eq!(versions.len(), 1);
    }

    #[test]
    fn resolve_vault_version_prefers_per_cabinet_over_global() {
        let mut vv = HashMap::new();
        vv.insert("econometrist".to_string(), 12u32);
        // per-cabinet версия сервера (12) важнее глобального content_version (c6→6)
        assert_eq!(resolve_vault_version("econometrist", Some(&vv), "c6"), 12);
        // кабинет отсутствует в карте → fallback на content_version
        assert_eq!(resolve_vault_version("media-analyst", Some(&vv), "c6"), 6);
        // старый сервер без vault_versions (None) → content_version (нулевая регрессия)
        assert_eq!(resolve_vault_version("econometrist", None, "c6"), 6);
        // битый content_version → 0 (не паникует; запись версии тогда пропускается)
        assert_eq!(resolve_vault_version("x", None, "cabc"), 0);
    }

    // ── Migration from legacy ────────────────────────────────────────────────

    #[test]
    fn test_migrate_noop_if_vault_versions_exists() {
        let dir = TempDir::new().unwrap();
        // Pre-create vault-versions.json
        std::fs::write(dir.path().join("vault-versions.json"), r#"{"media-analyst":3}"#).unwrap();
        // Should be a no-op - file should not be modified
        migrate_from_legacy(dir.path(), dir.path()).unwrap();
        let versions = get_vault_versions(dir.path());
        assert_eq!(versions.get("media-analyst"), Some(&3));
        assert_eq!(versions.len(), 1);
    }

    #[test]
    fn test_migrate_noop_if_no_legacy_version() {
        let dir = TempDir::new().unwrap();
        // Neither content_version.txt nor vault-versions.json
        migrate_from_legacy(dir.path(), dir.path()).unwrap();
        assert!(!dir.path().join("vault-versions.json").exists());
    }

    #[test]
    fn test_migrate_creates_vault_versions_from_legacy() {
        let config_dir = TempDir::new().unwrap();
        let data_dir = TempDir::new().unwrap();

        // Setup: content_version.txt = "c5"
        set_local_version(config_dir.path(), "c5").unwrap();

        // Create some .vault files on disk
        let vaults_dir = data_dir.path().join("vaults");
        std::fs::create_dir_all(&vaults_dir).unwrap();
        std::fs::write(vaults_dir.join("media-analyst.vault"), b"encrypted").unwrap();
        std::fs::write(vaults_dir.join("creative-group.vault"), b"encrypted").unwrap();

        migrate_from_legacy(config_dir.path(), data_dir.path()).unwrap();

        let versions = get_vault_versions(config_dir.path());
        // media-analyst → version 5
        assert_eq!(versions.get("media-analyst"), Some(&5));
        // creative-group maps to creative-director via stem_to_cabinet_id
        assert_eq!(versions.get("creative-director"), Some(&5));
    }

    #[test]
    fn test_migrate_skips_non_vault_files() {
        let config_dir = TempDir::new().unwrap();
        let data_dir = TempDir::new().unwrap();

        set_local_version(config_dir.path(), "c2").unwrap();
        let vaults_dir = data_dir.path().join("vaults");
        std::fs::create_dir_all(&vaults_dir).unwrap();
        std::fs::write(vaults_dir.join("media-analyst.vault"), b"data").unwrap();
        std::fs::write(vaults_dir.join("readme.txt"), b"not a vault").unwrap();
        std::fs::write(vaults_dir.join("config.json"), b"{}").unwrap();

        migrate_from_legacy(config_dir.path(), data_dir.path()).unwrap();

        let versions = get_vault_versions(config_dir.path());
        assert_eq!(versions.len(), 1);
        assert!(versions.contains_key("media-analyst"));
    }

    // ── Per-cabinet update check ─────────────────────────────────────────────

    #[test]
    fn test_check_update_per_cabinet_needs_update() {
        let dir = TempDir::new().unwrap();
        set_vault_version(dir.path(), "media-analyst", 1).unwrap();
        set_vault_version(dir.path(), "creative-director", 3).unwrap();

        // Server: media-analyst bumped to 2, creative-director still 3
        let mut server = HashMap::new();
        server.insert("media-analyst".to_string(), 2u32);
        server.insert("creative-director".to_string(), 3u32);

        let status = check_update_per_cabinet(dir.path(), &server);
        assert!(status.update_available);
        assert!(status.files_to_update.iter().any(|f| f.contains("media-analyst")),
            "media-analyst must be in files_to_update");
        assert!(!status.files_to_update.iter().any(|f| f.contains("creative")),
            "creative-director must NOT be in files_to_update (already up to date)");
    }

    #[test]
    fn test_check_update_per_cabinet_up_to_date() {
        let dir = TempDir::new().unwrap();
        set_vault_version(dir.path(), "media-analyst", 5).unwrap();

        let mut server = HashMap::new();
        server.insert("media-analyst".to_string(), 5u32);

        let status = check_update_per_cabinet(dir.path(), &server);
        assert!(!status.update_available);
        assert!(status.files_to_update.is_empty());
    }

    #[test]
    fn test_check_update_per_cabinet_no_local_version() {
        let dir = TempDir::new().unwrap();
        // Local has no version for this cabinet → treat as 0 → needs update

        let mut server = HashMap::new();
        server.insert("media-analyst".to_string(), 1u32);

        let status = check_update_per_cabinet(dir.path(), &server);
        assert!(status.update_available);
        assert!(!status.files_to_update.is_empty());
    }

    #[test]
    fn test_check_update_per_cabinet_empty_server() {
        let dir = TempDir::new().unwrap();
        set_vault_version(dir.path(), "media-analyst", 3).unwrap();

        let server: HashMap<String, u32> = HashMap::new();
        let status = check_update_per_cabinet(dir.path(), &server);
        assert!(!status.update_available);
        assert!(status.files_to_update.is_empty());
    }

    // ── Local content pack / frontend version ─────────────────────────────────

    #[test]
    fn test_get_local_content_pack_version_no_manifest() {
        let dir = TempDir::new().unwrap();
        assert_eq!(get_local_content_pack_version(dir.path()), 0);
    }

    #[test]
    fn test_get_local_content_pack_version_from_manifest() {
        let dir = TempDir::new().unwrap();
        let packs_dir = dir.path().join("content-packs");
        std::fs::create_dir_all(&packs_dir).unwrap();
        std::fs::write(
            packs_dir.join("manifest.json"),
            r#"{"format_version":1,"layer":"content","version":7,"min_core_version":"0.7.0","product":"test","timestamp":1000,"files":{}}"#,
        ).unwrap();
        assert_eq!(get_local_content_pack_version(dir.path()), 7);
    }

    #[test]
    fn test_get_local_frontend_version_no_file() {
        let dir = TempDir::new().unwrap();
        assert_eq!(get_local_frontend_version(dir.path()), 0);
    }

    #[test]
    fn test_get_local_frontend_version_from_file() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("current_frontend_version.txt"), "v3").unwrap();
        assert_eq!(get_local_frontend_version(dir.path()), 3);
    }

    #[test]
    fn test_get_local_frontend_version_without_v_prefix() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("current_frontend_version.txt"), "5").unwrap();
        assert_eq!(get_local_frontend_version(dir.path()), 5);
    }
}
