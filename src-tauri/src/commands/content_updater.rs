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

/// Supabase Edge Functions base URL.
fn supabase_url() -> String {
    "https://quzhkfvglqmppxcrindh.supabase.co/functions/v1".to_string()
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

/// Потолок на СОБРАННЫЙ из кусков файл (находка аудита H-2).
///
/// Полный размер приходит из чужого `Content-Range`, и до этой проверки он
/// ничем не ограничивался: ответ `bytes 0-2047/999999999999` заставлял клиент
/// крутить сотни миллионов запросов, наращивая память и удерживая замок
/// адреса, а вызов открытия кабинета не возвращался никогда.
const MAX_ASSEMBLED_BYTES: u64 = 64 * 1024 * 1024;

/// Файл крупнее этого забираем одним запросом, не кусками (находка аудита H-3).
///
/// Дробление придумано против посредника, режущего соединение после ~4 КБ, и
/// годится для файлов кабинетов в десятки килобайт. Бандл интерфейса весит
/// полтора мегабайта — это 734 запроса, каждый с полным TLS-рукопожатием, и
/// единственный сбой откатывал бы сборку в ноль. Для таких файлов прежний
/// путь честнее: один запрос, повторы при обрыве.
const RANGE_MAX_FILE_BYTES: u64 = 512 * 1024;

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

/// Забыть записанную версию кабинета после ручного импорта материалов из файла.
///
/// Версию импортированного файла мы не знаем: он мог быть получен в поддержке
/// неделю назад. Оставить прежнюю отметку — значит выдать неизвестные материалы
/// за актуальные, и обновление с сервера к этому кабинету больше не придёт
/// никогда (находка аудита M-3). Без отметки клиент при следующем запуске
/// спросит сервер и докачает, если там новее.
pub fn forget_vault_version(app_config_dir: &Path, filename: &str) -> Result<()> {
    let Some(stem) = filename.strip_suffix(".vault") else {
        return Ok(());
    };
    let cab_id = stem_to_cabinet_id(stem);

    let mut versions = get_vault_versions(app_config_dir);
    if versions.remove(cab_id).is_none() {
        return Ok(());
    }
    std::fs::write(
        vault_versions_path(app_config_dir),
        serde_json::to_string_pretty(&versions)?,
    )?;
    info!("Отметка версии кабинета {} снята: материалы загружены из файла", cab_id);
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
        // Соединения НЕ переиспользуются намеренно. Замер на машине клиента
        // 26.07.2026: посредник считает объём НА СОЕДИНЕНИЕ — пропускает первые
        // ~4 КБ, после чего перестаёт передавать данные, НЕ закрывая сокет
        // (получено 4168 байт, дальше тишина до истечения таймаута). С общим
        // пулом докачка по частям обесценивалась: второй кусок уходил в то же
        // соединение и упирался в тот же порог — ровно поэтому версия с кусками
        // по 2 КБ не разблокировала клиента.
        .pool_max_idle_per_host(0)
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

/// Забрать файл одним запросом, без дробления: для крупных файлов, где
/// куски по 2 КБ дали бы сотни рукопожатий (находка аудита H-3).
async fn fetch_whole(
    client: &reqwest::Client,
    url: &str,
    what: &str,
) -> std::result::Result<Vec<u8>, FetchFailure> {
    let res = client
        .get(url)
        .send()
        .await
        .map_err(|e| FetchFailure::Transient(anyhow::anyhow!("{}: запрос не прошёл: {}", what, e)))?;

    let status = res.status();
    if status.is_success() {
        return read_body_counted(res, what).await.map_err(FetchFailure::Transient);
    }

    let body = res.text().await.unwrap_or_default();
    let err = anyhow::anyhow!("Download failed for {}: HTTP {} - {}", what, status, body);
    Err(if status.is_server_error()
        || status == reqwest::StatusCode::TOO_MANY_REQUESTS
        || status == reqwest::StatusCode::REQUEST_TIMEOUT
    {
        FetchFailure::Transient(err)
    } else {
        FetchFailure::Fatal(err)
    })
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

    // Полный размер назвал сервер, и верить ему на слово нельзя: ответ вида
    // `bytes 0-2047/999999999999` крутил бы цикл сотни миллионов раз, наращивая
    // память и удерживая замок адреса (находка аудита H-2).
    if total > MAX_ASSEMBLED_BYTES {
        return Err(FetchFailure::Fatal(anyhow::anyhow!(
            "{}: сервер объявил размер {} байт — больше допустимых {} МБ",
            filename,
            total,
            MAX_ASSEMBLED_BYTES / (1024 * 1024)
        )));
    }

    // Крупный файл собирать кусками по 2 КБ бессмысленно: сотни рукопожатий,
    // и любой сбой откатывает в ноль. Берём прежним путём — одним запросом
    // с повторами (находка аудита H-3).
    if total > RANGE_MAX_FILE_BYTES {
        info!(
            "{}: {} байт — крупный файл, забираем одним запросом, без дробления",
            filename, total
        );
        return fetch_whole(client, url, filename).await;
    }

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

/// Свежие результаты загрузок под общим замком.
///
/// В журнале клиента при старте видно по четыре-шесть подряд запросов
/// авторизации и по четыре параллельные загрузки ОДНОГО файла: команду
/// `get_cabinets` дёргают сразу несколько экранов, и каждый вызов начинал
/// качать одно и то же. На слабом канале это прямой вред — обращения мешают
/// друг другу. Замок выстраивает их в очередь, а короткая память результатов
/// отдаёт уже скачанное вместо повторного обращения к серверу.
type UrlLocks = std::sync::Mutex<HashMap<String, std::sync::Arc<tokio::sync::Mutex<()>>>>;
type RecentDownloads = std::sync::Mutex<HashMap<String, (std::time::Instant, std::sync::Arc<Vec<u8>>)>>;

/// Замки по адресу файла. Одинаковые загрузки идут по очереди, разные —
/// по-прежнему параллельно: общий замок на весь транспорт заставил бы файлы
/// ждать чужих повторов, а они длятся до полуминуты.
fn url_locks() -> &'static UrlLocks {
    static LOCKS: std::sync::OnceLock<UrlLocks> = std::sync::OnceLock::new();
    LOCKS.get_or_init(|| std::sync::Mutex::new(HashMap::new()))
}

/// Память о только что полученных файлах.
fn recent_downloads() -> &'static RecentDownloads {
    static RECENT: std::sync::OnceLock<RecentDownloads> = std::sync::OnceLock::new();
    RECENT.get_or_init(|| std::sync::Mutex::new(HashMap::new()))
}

/// Сколько только что скачанный файл считается свежим.
/// Покрывает всплеск вызовов при старте, но не переживает его надолго:
/// обновление, вышедшее через минуту, клиент увидит.
const RECENT_DOWNLOAD_TTL_SECS: u64 = 30;

/// Взять замок этого адреса, попутно выбросив те, за которые никто не держится.
fn lock_for(url: &str) -> std::sync::Arc<tokio::sync::Mutex<()>> {
    let mut locks = url_locks().lock().unwrap_or_else(|e| e.into_inner());
    locks.retain(|_, l| std::sync::Arc::strong_count(l) > 1);
    locks.entry(url.to_string()).or_default().clone()
}

/// Отдать файл, полученный только что, если он ещё свеж.
fn take_recent(url: &str) -> Option<Vec<u8>> {
    let mut recent = recent_downloads().lock().unwrap_or_else(|e| e.into_inner());
    recent.retain(|_, (at, _)| at.elapsed().as_secs() < RECENT_DOWNLOAD_TTL_SECS);
    recent.get(url).map(|(_, bytes)| bytes.as_ref().clone())
}

/// Скачать файл, переживая обрывы канала: повторы с нарастающей паузой,
/// докачка по частям, память о только что полученном.
async fn download_with_retries(url: &str, what: &str) -> Result<Vec<u8>> {
    // Замок берётся ДО проверки памяти: иначе два одновременных вызова оба
    // увидели бы пустоту и оба пошли бы в сеть — ровно тот дребезг, что лечим.
    let lock = lock_for(url);
    let _guard = lock.lock().await;

    if let Some(bytes) = take_recent(url) {
        info!("{}: файл получен только что — берём готовый, к серверу не идём", what);
        return Ok(bytes);
    }

    let client = resilient_client()?;
    let mut last_err: Option<anyhow::Error> = None;

    for attempt in 1..=DOWNLOAD_ATTEMPTS {
        match fetch_vault_once(&client, url, what).await {
            Ok(bytes) => {
                if attempt > 1 {
                    info!("{} получен с попытки {}/{} ({} байт)", what, attempt, DOWNLOAD_ATTEMPTS, bytes.len());
                }
                recent_downloads()
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .insert(
                        url.to_string(),
                        (std::time::Instant::now(), std::sync::Arc::new(bytes.clone())),
                    );
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

/// Нормализовать контрольную сумму от сервера: убрать необязательный префикс
/// `sha256:` и привести к нижнему регистру перед сравнением с локально
/// посчитанным hex SHA-256.
///
/// У этого продукта сервер отдаёт суммы vault-файлов голым hex, без префикса —
/// на все четыре файла в манифесте расхождения формата сегодня нет. Нормализация
/// всё равно применяется как страховка: у Legal Center те же по смыслу суммы
/// приходят с префиксом `sha256:`, оба продукта берут их из одного и того же
/// конвейера подготовки content-pack, и молчаливое расхождение формата на любой
/// стороне не должно ронять докачку. Приём уже доказан в проде в
/// `commands/updater.rs::verify_checksum` — тот же strip_prefix + lower-case, но
/// здесь применяется к байтам vault-файла в памяти, а не к файлу .exe на диске.
///
/// 🔴 Порядок шагов важен: приставка срезается ПОСЛЕ приведения к нижнему регистру.
/// Обратный порядок (как было до правки) режет только точное написание `sha256:`,
/// а `SHA256:` или `Sha256:` остаются в строке — сравнение с посчитанным hex тогда
/// не сходится никогда, и файл молча отбрасывается на каждой докачке. Сегодня наш
/// сервер шлёт голый hex, то есть дефект не бьёт; правка снимает мину до того, как
/// формат суммы на любой стороне конвейера сменится.
fn normalize_checksum(expected: &str) -> String {
    let lowered = expected.to_lowercase();
    lowered.strip_prefix("sha256:").unwrap_or(&lowered).to_string()
}

/// Скачать vault-файл с сервера, переживая обрывы канала.
async fn download_vault_file(
    fingerprint_hash: &str,
    product: &str,
    version: &str,
    filename: &str,
) -> Result<Vec<u8>> {
    let url = format!(
        "{}/content?fingerprint_hash={}&product={}&version={}&file={}",
        supabase_url(), fingerprint_hash, product, version, filename
    );

    info!("Downloading vault: {}", filename);
    download_with_retries(&url, filename).await
}

/// Скачать произвольный файл (пакет контента, бандл фронтенда) с теми же
/// гарантиями, что и vault: без общего дедлайна, с повторами при обрыве.
/// Пакеты весят десятки мегабайт — на слабом канале общий таймаут в 120 с
/// рубил их гарантированно, даже когда передача исправно шла.
async fn download_url_resilient(url: &str, what: &str) -> Result<Vec<u8>> {
    download_with_retries(url, what).await
}

/// Atomic write helper: write to `<dest>.tmp` then rename to dest.
/// Prevents partial-write corruption from process kill or OS crash. The tmp
/// file lives in the same directory as dest so rename is a metadata-only
/// operation on a single filesystem.
fn atomic_write_bytes(dest: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut tmp_name = dest
        .file_name()
        .unwrap_or_default()
        .to_os_string();
    tmp_name.push(".tmp");
    let tmp = dest.with_file_name(tmp_name);
    std::fs::write(&tmp, bytes)?;
    if let Err(e) = std::fs::rename(&tmp, dest) {
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }
    Ok(())
}

/// Write a freshly encrypted vault to `dest` with rollback safety, then prove
/// it by decrypting it back. Returns `true` on success (dest now holds the new,
/// verified-readable vault); `false` if the write or the trial decryption
/// failed, in which case any pre-existing vault at `dest` is restored and
/// `dest` is left exactly as it was before this call.
///
/// Sync and network-free by design: `download_updates` is the only caller in
/// production, but the rollback path itself needs no HTTP client to test.
fn write_vault_with_rollback(dest: &Path, encrypted: &[u8], local_key: &[u8; 32], filename: &str) -> bool {
    // Rollback safety: if a vault already exists at dest, back it up before
    // replacing it. A version-update download (as opposed to a missing-file
    // download) always overwrites a working file, so a corrupted replacement
    // must not strand the user without the cabinet they had a moment ago.
    let backup_path = dest.with_extension("vault.bak");
    let had_backup = dest.exists();
    if had_backup {
        if let Err(e) = std::fs::rename(dest, &backup_path) {
            error!("Failed to back up existing vault {} before replacing: {e}", dest.display());
            return false;
        }
        // Тестовая пауза ровно в самом опасном месте — см. pause_after_backup.
        // В сборке для клиента вызов пуст.
        pause_after_backup(filename);
    } else {
        // Вторая тестовая точка: путь «резерва не было», на котором неудачная
        // запись заканчивается удалением файла. См. pause_before_unguarded_write.
        pause_before_unguarded_write(filename);
    }

    // DAT-02: atomic write protects against partial vault ciphertext from
    // process kill mid-download. Without atomic semantics a partial file fails
    // AES-GCM decryption → vault stuck corrupt until manual deletion. tempfile
    // + rename guarantees readers see either old (no file) or new (full file).
    if let Err(e) = atomic_write_bytes(dest, encrypted) {
        if had_backup {
            let _ = std::fs::rename(&backup_path, dest);
            warn!("Vault write failed for {}, restored previous version: {e}", filename);
        }
        error!("Failed to write vault file {}: {e}", dest.display());
        return false;
    }

    // Trial decrypt: confirm the freshly written file is actually usable
    // before trusting it. Catches truncated/corrupt downloads that still
    // passed the checksum check upstream (e.g. a bit flip introduced during
    // re-encryption) or a stale/wrong local key.
    let decrypt_ok = std::fs::read(dest)
        .ok()
        .map(|bytes| crypto::aes::decrypt(local_key, &bytes).is_ok())
        .unwrap_or(false);

    if !decrypt_ok {
        if had_backup {
            match std::fs::rename(&backup_path, dest) {
                Ok(_) => warn!(
                    "Vault update failed trial decryption for {}, rolled back to previous version",
                    filename
                ),
                Err(e) => error!(
                    "Vault update failed trial decryption for {} AND rollback failed: {e}",
                    filename
                ),
            }
        } else {
            warn!(
                "Vault update failed trial decryption for {} (no previous version to roll back to)",
                filename
            );
            let _ = std::fs::remove_file(dest);
        }
        return false;
    }

    if had_backup {
        let _ = std::fs::remove_file(&backup_path);
    }
    true
}

/// Пауза между переименованием прежнего файла в резерв и записью нового — только
/// для тестов, и только для того файла, который тест назвал сам.
///
/// Окно между этими двумя шагами измеряется микросекундами: тест «как повезёт»
/// сторожем не является, красноту он показывает раз в сотню прогонов. Пауза делает
/// окно широким и одинаковым на любой машине. Привязка к имени файла держит её
/// строго в своём тесте — соседние тесты, что пишут другие файлы, не тормозят.
/// 🔴 Хранится СПИСКОМ по именам файлов, а не одним значением: тесты идут
/// параллельно в одном процессе, и одно общее поле они затирали бы друг другу —
/// пауза чужого теста молча отменяла бы свою, а сторож гонки становился плавающим
/// (поймано на второй мутации: краснота ушла из-за соседнего теста, а не из-за кода).
#[cfg(test)]
static BACKUP_PAUSES: std::sync::Mutex<Vec<(String, u64)>> = std::sync::Mutex::new(Vec::new());

#[cfg(test)]
fn pause_after_backup(filename: &str) {
    // Замок отпускается до сна: иначе спящий держал бы список и остановил соседей.
    let ms = BACKUP_PAUSES
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .find(|(name, _)| name == filename)
        .map(|(_, ms)| *ms);
    if let Some(ms) = ms {
        std::thread::sleep(std::time::Duration::from_millis(ms));
    }
}

/// В сборке для клиента паузы нет — вызов исчезает при сборке.
#[cfg(not(test))]
#[inline(always)]
fn pause_after_backup(_filename: &str) {}

/// Пауза на втором опасном пути — когда резерва не было, и неудачная запись
/// заканчивается удалением файла. Тоже только для тестов и только для названного
/// файла: она позволяет показать самый тяжёлый исход гонки — кабинет исчезает с
/// диска целиком, потому что один вызов удаляет файл, который другой только что
/// вернул из своего резерва.
#[cfg(test)]
static NO_BACKUP_PAUSES: std::sync::Mutex<Vec<(String, u64)>> = std::sync::Mutex::new(Vec::new());

#[cfg(test)]
fn pause_before_unguarded_write(filename: &str) {
    let ms = NO_BACKUP_PAUSES
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .find(|(name, _)| name == filename)
        .map(|(_, ms)| *ms);
    if let Some(ms) = ms {
        std::thread::sleep(std::time::Duration::from_millis(ms));
    }
}

/// В сборке для клиента паузы нет — вызов исчезает при сборке.
#[cfg(not(test))]
#[inline(always)]
fn pause_before_unguarded_write(_filename: &str) {}

/// Замки по ЦЕЛЕВОМУ файлу кабинета.
///
/// Замок `lock_for` разводит одинаковые скачивания, но ключ у него — адрес, а в
/// адрес входят продукт, версия и отпечаток машины. Два вызова с разными версиями
/// одного и того же кабинета получают разные адреса, расходятся по разным замкам —
/// и пишут при этом в ОДИН файл. Точек вызова `download_updates` четыре, две из них
/// срабатывают при старте почти одновременно, поэтому ключ здесь — путь файла.
type PathLocks = std::sync::Mutex<HashMap<PathBuf, std::sync::Arc<tokio::sync::Mutex<()>>>>;

fn vault_write_locks() -> &'static PathLocks {
    static LOCKS: std::sync::OnceLock<PathLocks> = std::sync::OnceLock::new();
    LOCKS.get_or_init(|| std::sync::Mutex::new(HashMap::new()))
}

/// Взять замок целевого файла, попутно выбросив те, за которые никто не держится.
fn vault_lock_for(dest: &Path) -> std::sync::Arc<tokio::sync::Mutex<()>> {
    let mut locks = vault_write_locks().lock().unwrap_or_else(|e| e.into_inner());
    locks.retain(|_, l| std::sync::Arc::strong_count(l) > 1);
    locks.entry(dest.to_path_buf()).or_default().clone()
}

/// Чем закончилась попытка положить файл кабинета на место.
#[derive(Debug, PartialEq, Eq)]
enum VaultStore {
    /// Записан и прочитан обратно: размер исходных данных и размер шифротекста.
    Written { plain_len: usize, encrypted_len: usize },
    /// Контрольная сумма не сошлась — до записи дело не дошло.
    Rejected,
    /// Запись не удалась; прежний файл, если он был, возвращён на место.
    Failed,
}

/// Неделимая половина обновления одного кабинета: под замком ЦЕЛЕВОГО файла
/// добыть готовые к записи байты и записать их с откатом.
///
/// 🔴 Зачем замок именно здесь. `write_vault_with_rollback` переименовывает прежний
/// файл в резерв, а потом пишет новый — и решение «резерв был» принимает по тому,
/// существует ли файл. Два вызова на один кабинет расходятся ровно в этой щели:
/// первый уже увёл файл в резерв, второй видит пустое место, считает «резерва не
/// было» и пишет без страховки. Дальше первый откатывается на свой резерв и стирает
/// написанное вторым — а второй уже доложил об успехе, и его номер версии ушёл в
/// `vault-versions.json`. Кабинет остаётся со старым содержимым, и докачка больше
/// никогда не повторится: по номеру версии он «свежий».
///
/// `prepare` — скачивание со сверкой суммы и шифрованием. Оно ленивое: работа
/// начинается только внутри, когда замок уже взят, поэтому под замком лежит вся
/// связка «скачать → сверить → записать», а не одна запись. `Ok(None)` от него
/// значит «сумма не сошлась, писать нечего».
///
/// Порядок замков всегда один: сначала этот, по целевому файлу, потом внутренний
/// по адресу (`download_with_retries`). Обратного порядка в коде нет, поэтому
/// встречной блокировки не возникает.
async fn store_vault_guarded<E>(
    dest: &Path,
    filename: &str,
    local_key: &[u8; 32],
    prepare: impl std::future::Future<Output = std::result::Result<Option<(usize, Vec<u8>)>, E>>,
    on_written: impl FnOnce(),
) -> std::result::Result<VaultStore, E> {
    let lock = vault_lock_for(dest);
    let _guard = lock.lock().await;

    let Some((plain_len, encrypted)) = prepare.await? else {
        return Ok(VaultStore::Rejected);
    };

    let encrypted_len = encrypted.len();
    if write_vault_with_rollback(dest, &encrypted, local_key, filename) {
        // 🔴 Отметка об успехе ставится ПОД ТЕМ ЖЕ замком. Останься она снаружи —
        // номер версии кабинета менялся бы вне защищённой связки, то есть ровно
        // тем же способом, что и дефект, который здесь чинится: файл и его номер
        // обязаны меняться вместе, иначе номер может обогнать содержимое.
        on_written();
        Ok(VaultStore::Written { plain_len, encrypted_len })
    } else {
        Ok(VaultStore::Failed)
    }
}

/// Почему подготовка файла к записи не удалась.
///
/// Разделение нужно, чтобы сохранить прежний смысл ответа `download_updates`:
/// неудача связи копится в `last_error` и не мешает остальным файлам, а отказ
/// шифрования выходит наружу немедленно — повторять его бессмысленно.
enum PrepareFailure {
    /// Файл не доехал с сервера.
    Download(anyhow::Error),
    /// Данные доехали, но зашифровать их локальным ключом не удалось.
    Encrypt(anyhow::Error),
}

/// Расширение резервной копии, которую оставляет за собой `write_vault_with_rollback`.
const VAULT_BACKUP_SUFFIX: &str = ".vault.bak";

/// Подобрать резервные копии кабинетов, осиротевшие после прерванной записи.
///
/// `write_vault_with_rollback` сам возвращает резерв на место — но только если
/// дошёл до конца своего пути. Снятие процесса, отключение питания или отказ
/// машины между переименованием прежнего файла в `*.vault.bak` и записью нового
/// оставляют кабинет БЕЗ рабочего файла, хотя целый резерв лежит рядом. Подобрать
/// его до этой правки было некому: следующий запуск видел только отсутствие файла
/// и шёл качать заново — а без сети кабинет просто не открывался.
///
/// Возвращает число файлов, возвращённых на место.
///
/// 🔴 Ничего не удаляет. Если рядом с резервом лежит и рабочий файл, оба остаются
/// нетронутыми, а расхождение уходит в журнал. Такая пара — обычный след записи,
/// прерванной уже ПОСЛЕ появления нового файла (резерв не успели убрать), и там
/// рабочий файл новее резерва: подменять его старым — значит откатывать клиента
/// без спроса. Обратный случай (рабочий файл негоден, резерв цел) тоже покрыт, но
/// другим путём: проверка расшифровки при выдаче списка кабинетов помечает такой
/// файл к повторной докачке. Молча стирать резерв нельзя тем более — это данные
/// клиента, и когда сеть недоступна, он единственный уцелевший источник кабинета.
pub fn restore_orphaned_vault_backups(app_data_dir: &Path) -> usize {
    let vaults_dir = vault::vaults_dir(app_data_dir);
    let entries = match std::fs::read_dir(&vaults_dir) {
        Ok(entries) => entries,
        // Папки ещё нет — первый запуск, подбирать нечего. Не отказ.
        Err(_) => return 0,
    };

    let mut restored = 0usize;
    for entry in entries.flatten() {
        let backup_path = entry.path();
        let Some(name) = backup_path.file_name().and_then(|n| n.to_str()) else {
            continue;
        };
        let Some(working_name) = name.strip_suffix(".bak") else {
            continue;
        };
        if !name.ends_with(VAULT_BACKUP_SUFFIX) {
            continue;
        }

        let working_path = vaults_dir.join(working_name);
        if working_path.exists() {
            warn!(
                "Рядом с рабочим файлом {} лежит резерв {} — оба оставлены нетронутыми, \
                 запись когда-то прервалась после подмены файла",
                working_name, name
            );
            continue;
        }

        // 🔴 Тот же класс дефекта, что чинится замком выше: между проверкой и
        // действием состояние успевает измениться. Простое переименование затёрло
        // бы рабочий файл, появись он в этой щели (докачка идёт своим чередом), —
        // поэтому имя занимается эксклюзивно: создание либо удаётся, либо честно
        // отказывает, и решение принимается не по прочитанному раньше состоянию.
        let mut file = match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&working_path)
        {
            Ok(file) => file,
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                warn!(
                    "Рабочий файл {} появился, пока разбирался резерв {} — оба оставлены нетронутыми",
                    working_name, name
                );
                continue;
            }
            Err(e) => {
                error!("Не удалось занять имя {} для возврата из резерва: {e}", working_name);
                continue;
            }
        };

        let written = std::fs::read(&backup_path).and_then(|bytes| {
            use std::io::Write as _;
            file.write_all(&bytes)?;
            file.sync_all()
        });
        drop(file);

        match written {
            Ok(()) => {
                if let Err(e) = std::fs::remove_file(&backup_path) {
                    warn!(
                        "Рабочий файл {} возвращён, но резерв {} убрать не удалось: {e}",
                        working_name, name
                    );
                }
                restored += 1;
                info!(
                    "Рабочий файл кабинета {} возвращён из резерва: прошлая запись оборвалась",
                    working_name
                );
            }
            Err(e) => {
                // Убираем свой же недоделанный файл; резерв остаётся нетронутым.
                let _ = std::fs::remove_file(&working_path);
                error!(
                    "Не удалось вернуть {} из резерва {}: {e}",
                    working_name, name
                );
            }
        }
    }

    restored
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
        let dest = vaults_dir.join(filename);

        // Подготовка файла к записи. Работа ленивая: она начнётся внутри
        // store_vault_guarded, когда замок целевого файла уже взят, — поэтому
        // «скачать → сверить сумму → записать с откатом» неделимо относительно
        // одновременных вызовов на тот же кабинет.
        let prepare = async {
            let data = download_vault_file(&fp_hash, product, version, filename)
                .await
                .map_err(PrepareFailure::Download)?;

            // Verify checksum if available (against unencrypted data from server)
            match checksums.get(filename).and_then(|v| v.as_str()) {
                Some(expected) if !expected.is_empty() => {
                    let expected_norm = normalize_checksum(expected);
                    let mut hasher = Sha256::new();
                    hasher.update(&data);
                    let actual = format!("{:x}", hasher.finalize());
                    if actual != expected_norm {
                        error!(
                            "Checksum mismatch for {}: expected {}..., got {}...",
                            filename,
                            &expected_norm[..12.min(expected_norm.len())],
                            &actual[..12]
                        );
                        return Ok(None);
                    }
                }
                _ => {
                    // Принцип проекта — «никаких молчаливых пропусков». Раньше это
                    // ветвление отсутствовало вовсе: при пустых/недостающих суммах
                    // сверка пропускалась без единой строки в журнале. warn!, не
                    // error! — это ожидаемый деградированный путь (старый сервер без
                    // vault_checksums, либо файл вне присланной карты сумм), а не
                    // отказ; поведение не меняется — файл всё равно принимается,
                    // иначе обновление сломалось бы у клиентов на сервере, ещё не
                    // публикующем vault_checksums.
                    warn!(
                        "Нет контрольной суммы для {} от сервера — файл принят без проверки целостности",
                        filename
                    );
                }
            }

            // Encrypt with local key before saving to disk
            let encrypted = crypto::aes::encrypt(&local_key, &data)
                .with_context(|| format!("Failed to encrypt vault: {}", filename))
                .map_err(PrepareFailure::Encrypt)?;

            Ok(Some((data.len(), encrypted)))
        };

        // Track per-cabinet version in vault-versions.json — номер из
        // per-cabinet карты сервера, а не глобального content_version
        // (см. resolve_vault_version: рассинхрон двух счётчиков иначе
        // зациклил бы докачку кабинета на каждом старте). Ставится под замком
        // целевого файла, сразу после удачной записи — см. store_vault_guarded.
        let record_version = || {
            if let Some(stem) = filename.strip_suffix(".vault") {
                let cab_id = stem_to_cabinet_id(stem);
                let ver_num = resolve_vault_version(cab_id, vault_versions, version);
                if ver_num > 0 {
                    if let Err(e) = set_vault_version(app_config_dir, cab_id, ver_num) {
                        warn!("Failed to record per-cabinet version for {}: {}", cab_id, e);
                    }
                }
            }
        };

        match store_vault_guarded(&dest, filename, &local_key, prepare, record_version).await {
            Ok(VaultStore::Written { plain_len, encrypted_len }) => {
                info!("Updated vault: {} ({} bytes plain → {} bytes encrypted)", filename, plain_len, encrypted_len);
                updated.push(filename.clone());
            }
            // Сумма не сошлась либо запись не удалась: новую версию не пишем —
            // следующая проверка повторит докачку. Причина уже в журнале.
            Ok(VaultStore::Rejected) | Ok(VaultStore::Failed) => continue,
            // Зашифровать не удалось — отказ по существу, повторять нечего:
            // выходим наружу сразу, как и до появления замка.
            Err(PrepareFailure::Encrypt(e)) => return Err(e),
            Err(PrepareFailure::Download(e)) => {
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

        // Сторож ловит ЗАЦИКЛИВАНИЕ, а не медлительность, поэтому запас большой:
        // пять повторов сами по себе выжидают 37 с пауз, и граница в минуту
        // срабатывала на загруженной машине как ложная тревога.
        let err = tokio::time::timeout(
            std::time::Duration::from_secs(180),
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

    #[tokio::test]
    async fn parallel_downloads_of_same_file_reach_server_once() {
        // Дребезг из журнала клиента: команду за списком кабинетов дёргают
        // несколько экранов сразу, и один файл начинал качаться четырежды.
        let body = sample_body(1500);
        let (url, hits) = spawn_test_server(vec![Scenario::RangeAware {
            body: body.clone(),
            threshold: PROXY_THRESHOLD,
        }])
        .await;

        let (first, second) = tokio::join!(
            download_url_resilient(&url, "файл кабинета"),
            download_url_resilient(&url, "файл кабинета"),
        );

        assert_eq!(first.unwrap(), body);
        assert_eq!(second.unwrap(), body, "второй вызов обязан получить тот же файл");
        assert_eq!(
            hits.load(std::sync::atomic::Ordering::SeqCst),
            1,
            "одновременные запросы одного файла обязаны дойти до сервера один раз"
        );
    }

    /// Живая проверка против БОЕВОГО сервера: клиентский код обязан собрать
    /// файл кабинета кусками с того самого адреса, куда ходит продукт.
    ///
    /// Тесты выше гоняют наш собственный тестовый сервер — то есть проверяют
    /// клиент против нашего же представления о том, как отвечает Supabase.
    /// Этот разрыв закрывается только обращением к настоящему адресу.
    ///
    /// В обычный прогон не входит (ходит в сеть и требует действующей
    /// лицензии). Запуск:
    /// `AURORA_PROBE_FINGERPRINT=<хеш отпечатка> cargo test -- --ignored ranged_download_against_production`
    #[tokio::test]
    #[ignore = "ходит в сеть, нужна действующая лицензия"]
    async fn ranged_download_against_production() {
        let Ok(fp) = std::env::var("AURORA_PROBE_FINGERPRINT") else {
            panic!("нужен AURORA_PROBE_FINGERPRINT — хеш отпечатка машины с действующей лицензией");
        };
        let url = format!(
            "{}/content?fingerprint_hash={}&product=econometrica&version=c3&file=econometrist.vault",
            supabase_url(),
            fp
        );

        let got = download_with_retries(&url, "econometrist.vault")
            .await
            .expect("файл кабинета обязан собраться с боевого сервера");

        assert_eq!(got.len(), 34165, "собран файл не того размера");
        assert_eq!(
            format!("{:x}", Sha256::digest(&got)),
            "6ce228e6b2bc85d1903f5d5abdf1595a84a9ce9dfe5f78e787ab96993eed540f",
            "содержимое разошлось с тем, что отдаёт сервер целиком"
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
    fn forget_vault_version_clears_only_that_cabinet() {
        let dir = TempDir::new().unwrap();
        set_vault_version(dir.path(), "econometrist", 7).unwrap();
        set_vault_version(dir.path(), "lawyer-claims", 3).unwrap();

        forget_vault_version(dir.path(), "econometrist.vault").unwrap();

        let left = get_vault_versions(dir.path());
        assert!(
            !left.contains_key("econometrist"),
            "отметка импортированного кабинета обязана сниматься, иначе обновление к нему не придёт"
        );
        assert_eq!(left.get("lawyer-claims"), Some(&3), "соседние кабинеты трогать нельзя");
    }

    #[test]
    fn forget_vault_version_maps_file_stem_to_cabinet() {
        let dir = TempDir::new().unwrap();
        // Файл creative-group.vault принадлежит кабинету creative-director.
        set_vault_version(dir.path(), "creative-director", 5).unwrap();

        forget_vault_version(dir.path(), "creative-group.vault").unwrap();

        assert!(
            !get_vault_versions(dir.path()).contains_key("creative-director"),
            "имя файла обязано приводиться к имени кабинета"
        );
    }

    #[test]
    fn forget_vault_version_is_quiet_when_nothing_to_forget() {
        let dir = TempDir::new().unwrap();
        forget_vault_version(dir.path(), "econometrist.vault").unwrap();
        forget_vault_version(dir.path(), "не-наш-файл.txt").unwrap();
        assert!(get_vault_versions(dir.path()).is_empty());
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

    // ── normalize_checksum ──────────────────────────────────────────────────

    #[test]
    fn normalize_checksum_bare_hex_unchanged() {
        assert_eq!(normalize_checksum("abc123"), "abc123");
    }

    #[test]
    fn normalize_checksum_strips_sha256_prefix() {
        assert_eq!(normalize_checksum("sha256:abc123"), "abc123");
    }

    #[test]
    fn normalize_checksum_lowercases_uppercase_hex() {
        assert_eq!(normalize_checksum("ABC123"), "abc123");
        assert_eq!(normalize_checksum("sha256:ABC123"), "abc123");
    }

    #[test]
    fn normalize_checksum_empty_string() {
        assert_eq!(normalize_checksum(""), "");
    }

    /// Сторож порядка шагов: приставка обязана срезаться и в верхнем регистре.
    /// Пока срез шёл ДО приведения к нижнему регистру, `SHA256:` оставался в
    /// строке целиком, сумма не сходилась ни разу и файл отбрасывался молча.
    #[test]
    fn normalize_checksum_strips_uppercase_prefix() {
        assert_eq!(normalize_checksum("SHA256:ABC123"), "abc123");
        assert_eq!(normalize_checksum("SHA256:abc123"), "abc123");
    }

    /// Смешанное написание приставки — тот же сторож с другой стороны.
    #[test]
    fn normalize_checksum_strips_mixed_case_prefix() {
        assert_eq!(normalize_checksum("Sha256:AbC123"), "abc123");
        assert_eq!(normalize_checksum("ShA256:abc123"), "abc123");
    }

    #[test]
    fn normalize_checksum_prefixed_and_bare_forms_match() {
        // Сервер этого продукта шлёт голый hex; у Legal Center та же по смыслу
        // сумма приходит с префиксом и в другом регистре. После нормализации
        // обе формы одной и той же суммы обязаны совпасть.
        let bare = normalize_checksum("d41d8cd98f00b204e9800998ecf8427e");
        let prefixed = normalize_checksum("sha256:D41D8CD98F00B204E9800998ECF8427E");
        assert_eq!(bare, prefixed);
    }

    // ── write_vault_with_rollback ───────────────────────────────────────────────

    #[test]
    fn write_vault_rollback_restores_previous_on_bad_decrypt() {
        let dir = TempDir::new().unwrap();
        let dest = dir.path().join("media-analyst.vault");
        let key = [7u8; 32];

        // Seed an existing, genuinely decryptable vault.
        let good_plain = b"previous cabinet contents";
        let good_encrypted = crate::crypto::aes::encrypt(&key, good_plain).unwrap();
        std::fs::write(&dest, &good_encrypted).unwrap();

        // "Download" that is not valid ciphertext for this key - simulates a
        // corrupted transfer or a re-encryption bug, without needing a network mock.
        let bad_bytes = b"not valid aes-gcm ciphertext".to_vec();

        let ok = write_vault_with_rollback(&dest, &bad_bytes, &key, "media-analyst.vault");

        assert!(!ok, "write_vault_with_rollback must report failure for undecryptable data");
        let restored = std::fs::read(&dest).unwrap();
        assert_eq!(restored, good_encrypted, "dest must be restored to the exact previous vault bytes");
        assert!(!dest.with_extension("vault.bak").exists(), "backup file must be cleaned up after restore");
    }

    #[test]
    fn write_vault_rollback_does_not_touch_vault_versions_json_on_failure() {
        let config_dir = TempDir::new().unwrap();
        let vault_dir = TempDir::new().unwrap();
        let dest = vault_dir.path().join("media-analyst.vault");
        let key = [7u8; 32];

        set_vault_version(config_dir.path(), "media-analyst", 2).unwrap();
        let good_encrypted = crate::crypto::aes::encrypt(&key, b"previous contents").unwrap();
        std::fs::write(&dest, &good_encrypted).unwrap();

        let bad_bytes = b"garbage".to_vec();
        let ok = write_vault_with_rollback(&dest, &bad_bytes, &key, "media-analyst.vault");
        assert!(!ok);

        // download_updates only calls set_vault_version when write_vault_with_rollback
        // succeeds; this test locks in that vault-versions.json is untouched by the
        // rollback path itself, matching the caller's `continue`-before-set_vault_version.
        let versions = get_vault_versions(config_dir.path());
        assert_eq!(versions.get("media-analyst"), Some(&2), "local version record must be unchanged after a failed update");
    }

    #[test]
    fn write_vault_rollback_removes_new_file_when_no_previous_existed() {
        let dir = TempDir::new().unwrap();
        let dest = dir.path().join("media-analyst.vault");
        let key = [7u8; 32];
        assert!(!dest.exists());

        let bad_bytes = b"garbage".to_vec();
        let ok = write_vault_with_rollback(&dest, &bad_bytes, &key, "media-analyst.vault");

        assert!(!ok);
        assert!(!dest.exists(), "no vault existed before, so the failed write must not leave one behind");
    }

    #[test]
    fn write_vault_rollback_succeeds_with_valid_ciphertext() {
        let dir = TempDir::new().unwrap();
        let dest = dir.path().join("media-analyst.vault");
        let key = [7u8; 32];

        let old_encrypted = crate::crypto::aes::encrypt(&key, b"old contents").unwrap();
        std::fs::write(&dest, &old_encrypted).unwrap();

        let new_encrypted = crate::crypto::aes::encrypt(&key, b"new contents").unwrap();
        let ok = write_vault_with_rollback(&dest, &new_encrypted, &key, "media-analyst.vault");

        assert!(ok);
        let on_disk = std::fs::read(&dest).unwrap();
        assert_eq!(on_disk, new_encrypted);
        assert!(!dest.with_extension("vault.bak").exists(), "backup must be removed after a successful update");
    }

    // ── Гонка одновременных обновлений одного кабинета ────────────────────────
    //
    // Точек вызова download_updates четыре, две из них срабатывают при старте
    // почти одновременно. Сторожа ниже держат связку «добыть байты → записать с
    // откатом» неделимой для одного целевого файла.

    /// Включить паузу после переименования в резерв — для одного имени файла.
    /// Свою запись каждый тест ставит и снимает сам, чужие не трогает.
    fn set_backup_pause(filename: &str, ms: u64) {
        let mut pauses = BACKUP_PAUSES.lock().unwrap_or_else(|e| e.into_inner());
        pauses.retain(|(name, _)| name != filename);
        pauses.push((filename.to_string(), ms));
    }

    fn clear_backup_pause(filename: &str) {
        BACKUP_PAUSES
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .retain(|(name, _)| name != filename);
    }

    /// Включить паузу на пути «резерва не было» — для одного имени файла.
    fn set_no_backup_pause(filename: &str, ms: u64) {
        let mut pauses = NO_BACKUP_PAUSES.lock().unwrap_or_else(|e| e.into_inner());
        pauses.retain(|(name, _)| name != filename);
        pauses.push((filename.to_string(), ms));
    }

    fn clear_no_backup_pause(filename: &str) {
        NO_BACKUP_PAUSES
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .retain(|(name, _)| name != filename);
    }

    #[test]
    fn vault_lock_is_keyed_by_target_file() {
        let a = vault_lock_for(Path::new("C:/vaults/media-analyst.vault"));
        let b = vault_lock_for(Path::new("C:/vaults/media-analyst.vault"));
        let other = vault_lock_for(Path::new("C:/vaults/econometrist.vault"));

        assert!(
            std::sync::Arc::ptr_eq(&a, &b),
            "один и тот же файл обязан получать один и тот же замок — иначе два вызова разных версий разойдутся"
        );
        assert!(
            !std::sync::Arc::ptr_eq(&a, &other),
            "разные кабинеты не должны ждать друг друга"
        );
    }

    /// 🔴 Сторож гонки. Два вызова обновляют один кабинет: первый несёт негодные
    /// байты (обязан откатиться на прежний файл), второй — настоящее обновление.
    ///
    /// Одновременность делается детерминированной паузой в самом опасном месте —
    /// между переименованием прежнего файла в резерв и записью нового
    /// (`pause_after_backup`, только под тестами и только для этого имени файла).
    /// Без такой паузы окно шириной в микросекунды ловится раз в сотню прогонов,
    /// то есть сторожем не является.
    ///
    /// Без замка второй вызов видит пустое место (первый уже увёл файл в резерв),
    /// считает «резерва не было», пишет своё и докладывает об успехе — а первый,
    /// проснувшись, откатывается на резерв и стирает написанное. На диске старое
    /// содержимое, номер версии в vault-versions.json — новый, докачка больше
    /// никогда не повторится.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn concurrent_updates_of_one_vault_keep_the_reported_contents() {
        let dir = TempDir::new().unwrap();
        let dest = dir.path().join("race-cabinet.vault");
        let key = [11u8; 32];

        let previous = crate::crypto::aes::encrypt(&key, b"previous cabinet contents").unwrap();
        std::fs::write(&dest, &previous).unwrap();

        let broken = b"not valid aes-gcm ciphertext".to_vec();
        let fresh = crate::crypto::aes::encrypt(&key, b"fresh cabinet contents").unwrap();

        set_backup_pause("race-cabinet.vault", 200);

        let first = {
            let dest = dest.clone();
            let broken = broken.clone();
            tokio::spawn(async move {
                store_vault_guarded(
                    &dest,
                    "race-cabinet.vault",
                    &key,
                    async move { Ok::<_, std::convert::Infallible>(Some((broken.len(), broken))) },
                    || {},
                )
                .await
                .unwrap()
            })
        };

        // Дать первому дойти до опасного места: файл уже уведён в резерв.
        tokio::time::sleep(std::time::Duration::from_millis(80)).await;

        let second = {
            let dest = dest.clone();
            let fresh_bytes = fresh.clone();
            tokio::spawn(async move {
                store_vault_guarded(
                    &dest,
                    "race-cabinet.vault",
                    &key,
                    async move {
                        Ok::<_, std::convert::Infallible>(Some((fresh_bytes.len(), fresh_bytes)))
                    },
                    || {},
                )
                .await
                .unwrap()
            })
        };

        let first_res = first.await.unwrap();
        let second_res = second.await.unwrap();
        clear_backup_pause("race-cabinet.vault");

        assert_eq!(first_res, VaultStore::Failed, "негодные байты обязаны быть отвергнуты");
        assert!(
            matches!(second_res, VaultStore::Written { .. }),
            "настоящее обновление обязано записаться, получено {second_res:?}"
        );

        let on_disk = std::fs::read(&dest).unwrap();
        assert_eq!(
            on_disk, fresh,
            "на диске обязано лежать содержимое того вызова, что доложил об успешной записи"
        );
        assert!(
            !dest.with_extension("vault.bak").exists(),
            "резерв не должен остаться сиротой после обеих записей"
        );
    }

    /// 🔴 Второй сторож той же гонки — самый тяжёлый исход: кабинет исчезает с
    /// диска целиком. Оба вызова несут негодные байты и обязаны откатиться.
    ///
    /// Без замка: первый увёл рабочий файл в резерв; второй видит пустое место,
    /// считает «резерва не было», и его неудачная запись заканчивается удалением
    /// файла — того самого, который первый только что вернул из своего резерва.
    /// У клиента не остаётся ни рабочего файла, ни резерва, и кабинет не
    /// открывается вовсе, пока нет сети. Обе паузы нужны, чтобы эти два пути
    /// сошлись в нужном порядке на любой машине.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn concurrent_failed_updates_leave_the_cabinet_in_place() {
        let dir = TempDir::new().unwrap();
        let dest = dir.path().join("race-survive.vault");
        let key = [13u8; 32];

        let previous = crate::crypto::aes::encrypt(&key, b"cabinet the client works with").unwrap();
        std::fs::write(&dest, &previous).unwrap();

        set_backup_pause("race-survive.vault", 200);
        set_no_backup_pause("race-survive.vault", 200);

        let first = {
            let dest = dest.clone();
            tokio::spawn(async move {
                store_vault_guarded(
                    &dest,
                    "race-survive.vault",
                    &key,
                    async move {
                        let bytes = b"garbage one".to_vec();
                        Ok::<_, std::convert::Infallible>(Some((bytes.len(), bytes)))
                    },
                    || {},
                )
                .await
                .unwrap()
            })
        };

        tokio::time::sleep(std::time::Duration::from_millis(80)).await;

        let second = {
            let dest = dest.clone();
            tokio::spawn(async move {
                store_vault_guarded(
                    &dest,
                    "race-survive.vault",
                    &key,
                    async move {
                        let bytes = b"garbage two".to_vec();
                        Ok::<_, std::convert::Infallible>(Some((bytes.len(), bytes)))
                    },
                    || {},
                )
                .await
                .unwrap()
            })
        };

        assert_eq!(first.await.unwrap(), VaultStore::Failed);
        assert_eq!(second.await.unwrap(), VaultStore::Failed);
        clear_backup_pause("race-survive.vault");
        clear_no_backup_pause("race-survive.vault");

        assert!(dest.exists(), "кабинет клиента обязан остаться на диске");
        assert_eq!(
            std::fs::read(&dest).unwrap(),
            previous,
            "после двух неудачных обновлений на месте обязан лежать прежний рабочий файл"
        );
    }

    /// Сумма не сошлась — до записи дело не доходит, прежний файл не тронут.
    #[tokio::test]
    async fn rejected_preparation_never_touches_the_existing_vault() {
        let dir = TempDir::new().unwrap();
        let dest = dir.path().join("media-analyst.vault");
        let key = [17u8; 32];
        let previous = crate::crypto::aes::encrypt(&key, b"previous contents").unwrap();
        std::fs::write(&dest, &previous).unwrap();

        // Отметка об успехе не должна ставиться, когда записи не было.
        let recorded = std::sync::atomic::AtomicBool::new(false);
        let outcome = store_vault_guarded(
            &dest,
            "media-analyst.vault",
            &key,
            async { Ok::<_, std::convert::Infallible>(None) },
            || recorded.store(true, std::sync::atomic::Ordering::SeqCst),
        )
        .await
        .unwrap();

        assert_eq!(outcome, VaultStore::Rejected);
        assert!(
            !recorded.load(std::sync::atomic::Ordering::SeqCst),
            "номер версии не должен записываться, когда файл не записан"
        );
        assert_eq!(std::fs::read(&dest).unwrap(), previous);
        assert!(!dest.with_extension("vault.bak").exists());
    }

    // ── restore_orphaned_vault_backups ────────────────────────────────────────
    //
    // Сторожа подбора резерва, осиротевшего после прерванной записи. Гейт против
    // возврата состояния «рабочего файла нет, целый резерв лежит рядом, подобрать
    // его некому» — кабинет тогда не открывается вовсе, пока нет сети.

    #[test]
    fn orphaned_backup_is_restored_when_working_file_missing() {
        let data_dir = TempDir::new().unwrap();
        let vaults = vault::vaults_dir(data_dir.path());
        std::fs::create_dir_all(&vaults).unwrap();
        let backup = vaults.join("media-analyst.vault.bak");
        std::fs::write(&backup, b"prior cabinet bytes").unwrap();

        let restored = restore_orphaned_vault_backups(data_dir.path());

        assert_eq!(restored, 1, "осиротевший резерв обязан вернуться на место");
        let working = vaults.join("media-analyst.vault");
        assert_eq!(
            std::fs::read(&working).unwrap(),
            b"prior cabinet bytes",
            "содержимое резерва обязано доехать до рабочего файла без изменений"
        );
        assert!(!backup.exists(), "после возврата резерв не должен оставаться на диске");
    }

    #[test]
    fn backup_beside_working_file_is_left_untouched() {
        let data_dir = TempDir::new().unwrap();
        let vaults = vault::vaults_dir(data_dir.path());
        std::fs::create_dir_all(&vaults).unwrap();
        let working = vaults.join("media-analyst.vault");
        let backup = vaults.join("media-analyst.vault.bak");
        std::fs::write(&working, b"current cabinet bytes").unwrap();
        std::fs::write(&backup, b"previous cabinet bytes").unwrap();

        let restored = restore_orphaned_vault_backups(data_dir.path());

        assert_eq!(restored, 0, "рабочий файл на месте — подменять его резервом нельзя");
        assert_eq!(
            std::fs::read(&working).unwrap(),
            b"current cabinet bytes",
            "рабочий файл обязан остаться ровно таким, каким был"
        );
        assert_eq!(
            std::fs::read(&backup).unwrap(),
            b"previous cabinet bytes",
            "резерв — данные клиента, молча удалять его нельзя"
        );
    }

    #[test]
    fn restore_orphaned_backups_is_quiet_without_vaults_dir() {
        let data_dir = TempDir::new().unwrap();
        assert_eq!(restore_orphaned_vault_backups(data_dir.path()), 0);
    }

    #[test]
    fn restore_orphaned_backups_ignores_foreign_files() {
        let data_dir = TempDir::new().unwrap();
        let vaults = vault::vaults_dir(data_dir.path());
        std::fs::create_dir_all(&vaults).unwrap();
        // Обрывок атомарной записи и посторонний резерв не от vault-файла:
        // ни тот, ни другой не должны превратиться в рабочий файл кабинета.
        std::fs::write(vaults.join("media-analyst.vault.tmp"), b"half written").unwrap();
        std::fs::write(vaults.join("notes.txt.bak"), b"not a cabinet").unwrap();

        let restored = restore_orphaned_vault_backups(data_dir.path());

        assert_eq!(restored, 0);
        assert!(!vaults.join("media-analyst.vault").exists(), "обрывок записи не подменяет кабинет");
        assert!(!vaults.join("notes.txt").exists(), "посторонний файл не восстанавливается");
        assert!(vaults.join("media-analyst.vault.tmp").exists(), "чужие файлы не трогаем");
        assert!(vaults.join("notes.txt.bak").exists(), "чужие файлы не трогаем");
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
