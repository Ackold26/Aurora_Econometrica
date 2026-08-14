pub mod commands;
pub mod crypto;
pub mod durable_store;
pub mod econ_sidecar;
pub mod errors;
pub mod metrics;
pub mod session;
pub mod sidecar_runtime;
pub mod win_acl;

use commands::{brand, cabinet, claude, content_pack, content_updater, feedback, license, online_auth, parser, rag_client, updater, user_config, vault};
use session::manager::SessionManager;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{Emitter, Manager};
#[allow(unused_imports)]
use log::{debug, error, info, warn};
#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// Application state shared across Tauri commands.
pub struct AppState {
    pub session_manager: SessionManager,
    /// Maps cabinet_id → PID of the running Claude process (if any).
    pub active_pids: Arc<Mutex<HashMap<String, u32>>>,
    /// Active workflow executions: execution_id → status ("running"/"completed"/"cancelled"/"failed")
    pub workflow_executions: Arc<Mutex<HashMap<String, String>>>,
    /// Set to true only when content packs pass Ed25519 manifest verification at startup.
    /// Dynamic loaders must check this before serving pack data.
    pub content_packs_verified: Arc<AtomicBool>,
}

// ============== Tauri Commands ==============

#[tauri::command]
async fn get_cabinets(_state: tauri::State<'_, Arc<AppState>>, app_handle: tauri::AppHandle) -> Result<Vec<cabinet::CabinetInfo>, String> {
    let local_data_dir = app_handle.path().app_local_data_dir().map_err(|e| e.to_string())?;

    #[cfg(debug_assertions)]
    if std::env::var("AIAGENCY_DEV").is_ok() {
        info!("[DEV] Bypassing license check");
        let packs_ok = _state.content_packs_verified.load(Ordering::Acquire);
        let all = if packs_ok {
            cabinet::get_cabinet_definitions_dynamic(&local_data_dir)
        } else {
            cabinet::get_cabinet_definitions()
        };
        // Filter by product type (same as prod) so single-cabinet products work in dev
        let product = online_auth::detect_product();
        let filtered = cabinet::filter_by_product(product, all);
        info!("[DEV] Returning {} cabinets for product '{}'", filtered.len(), product);
        return Ok(filtered);
    }

    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let app_version = env!("CARGO_PKG_VERSION");

    // ── Try online auth first ──
    let online = online_auth::authorize(&config_dir, app_version, "").await;

    if online.status == "ok" || online.status == "cached" {
        metrics::audit::log_event("online_auth", &format!("status={}, cabinets={}", online.status, online.cabinets.len()), true);

        // ── Auto-download missing vaults from server ──
        if let Some(ref cv) = online.content_version {
            let data_dir = app_handle.path().app_data_dir().map_err(|e| e.to_string())?;
            let vaults_dir = vault::vaults_dir(&data_dir);
            let product = online_auth::detect_product();

            // Collect vault filenames that are missing OR undecryptable locally
            let local_key = content_updater::derive_local_key(&config_dir).ok();
            let missing: Vec<String> = online.cabinets.iter()
                .map(|cab| vault::vault_filename_pub(cab))
                .filter(|fname| {
                    let path = vaults_dir.join(fname);
                    if !path.exists() {
                        return true; // missing
                    }
                    // Vault exists - verify it's decryptable with local key
                    if let Some(ref key) = local_key {
                        if let Ok(data) = std::fs::read(&path) {
                            if crypto::aes::decrypt(key, &data).is_err() {
                                warn!("Vault {} exists but cannot be decrypted - will re-download", fname);
                                return true; // corrupt or wrong key → re-download
                            }
                        }
                    }
                    false
                })
                .collect();

            if !missing.is_empty() {
                info!("Downloading {} missing vault(s) from server...", missing.len());
                // Реальные суммы от сервера, если он их прислал; иначе пустой объект —
                // как и раньше, чтобы старый сервер без vault_checksums не менял поведение
                // (download_updates журналирует пропуск сверки сам).
                let empty_checksums = serde_json::json!({});
                let checksums = online.vault_checksums.as_ref().unwrap_or(&empty_checksums);
                match content_updater::download_updates(&config_dir, &data_dir, product, cv, &missing, checksums, online.vault_versions.as_ref(), Some(&app_handle)).await {
                    Ok(updated) => info!("Downloaded {}/{} vault files", updated.len(), missing.len()),
                    Err(e) => warn!("Failed to download vaults: {e}"),
                }
            }

            // ── Version-based докачка (Батч 0, 2026-07-13): доставка ПРАВОК промптов
            // существующих кабинетов. Блок выше качает только missing/undecryptable
            // vault'ы (новые кабинеты) - обновление контента УЖЕ установленного
            // vault'а никогда не триггерилось. Сервер шлёт vault_versions per-cabinet
            // в /auth (Phase 5, online_auth.rs:159) - сверяем с локальными.
            if let Some(ref server_versions) = online.vault_versions {
                let stale: Vec<String> = content_updater::check_update_per_cabinet(&config_dir, server_versions)
                    .files_to_update
                    .into_iter()
                    .filter(|f| !missing.contains(f))
                    .collect();

                if !stale.is_empty() {
                    info!("Downloading {} vault(s) with newer prompt content...", stale.len());
                    // Реальные суммы от сервера, если он их прислал; иначе пустой объект —
                    // как и раньше, чтобы старый сервер без vault_checksums не менял поведение
                    // (download_updates журналирует пропуск сверки сам).
                    let empty_checksums = serde_json::json!({});
                    let checksums = online.vault_checksums.as_ref().unwrap_or(&empty_checksums);
                    match content_updater::download_updates(&config_dir, &data_dir, product, cv, &stale, checksums, Some(server_versions), Some(&app_handle)).await {
                        Ok(updated) => info!("Downloaded {}/{} updated vault files", updated.len(), stale.len()),
                        Err(e) => warn!("Failed to download versioned vault updates: {e}"),
                    }
                }
            }
        }

        let packs_ok = _state.content_packs_verified.load(Ordering::Acquire);
        let all_cabinets = if packs_ok {
            cabinet::get_cabinet_definitions_dynamic(&local_data_dir)
        } else {
            cabinet::get_cabinet_definitions()
        };
        let available: Vec<_> = all_cabinets.into_iter()
            .filter(|c| online.cabinets.contains(&c.id))
            .collect();
        info!("Cabinets loaded (online): {} available", available.len());
        return Ok(available);
    }

    if online.available && online.status == "blocked" {
        // Server explicitly denied - do NOT fallback to offline
        let msg = online.message.unwrap_or("Доступ заблокирован".to_string());
        metrics::audit::log_event("online_auth", &msg, false);
        warn!("Online auth blocked: {msg}");
        return Err(msg);
    }

    // ── Fallback to offline Ed25519 ──
    info!("Online auth unavailable, falling back to offline license");
    let license = license::License::load(&config_dir).map_err(|e| {
        warn!("Failed to load license: {e}");
        e.to_string()
    })?;
    let status = license.validate().map_err(|e| e.to_string())?;

    if !status.valid {
        let err = status.error.unwrap_or("Лицензия недействительна".to_string());
        metrics::audit::log_event("license_validate", &err, false);
        warn!("License invalid: {err}");
        return Err(err);
    }

    metrics::audit::log_event("license_validate", &format!("issued_to={}, days_remaining={}", status.issued_to, status.days_remaining), true);

    let packs_ok = _state.content_packs_verified.load(Ordering::Acquire);
    let all_cabinets = if packs_ok {
        cabinet::get_cabinet_definitions_dynamic(&local_data_dir)
    } else {
        cabinet::get_cabinet_definitions()
    };
    let available: Vec<_> = all_cabinets.into_iter()
        .filter(|c| status.cabinets.contains(&c.id))
        .collect();
    info!("Cabinets loaded (offline): {} available (license grants: {:?})", available.len(), status.cabinets);
    Ok(available)
}

#[tauri::command]
fn get_license_status(app_handle: tauri::AppHandle) -> Result<license::LicenseStatus, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let lic = license::License::load(&config_dir).map_err(|e| e.to_string())?;
    lic.validate().map_err(|e| e.to_string())
}

#[tauri::command]
fn import_license(path: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    match license::import_license(&path, &config_dir) {
        Ok(()) => {
            metrics::audit::log_event("license_import", &path, true);
            Ok(())
        }
        Err(e) => {
            metrics::audit::log_event("license_import", &format!("{}: {e}", path), false);
            Err(e.to_string())
        }
    }
}

/// Запасной путь доставки рабочих материалов кабинета — из файла, а не с сервера.
///
/// Нужен клиентам, у которых сеть режет или разбирает соединение (корпоративный
/// шлюз, проверка защищённых соединений антивирусом): без этого пути продукт у
/// них не открывается вовсе. На диске материалы лежат зашифрованными ключом
/// машины, поэтому просто скопировать файл в папку нельзя — шифруем здесь.
#[tauri::command]
fn import_cabinet_vault(path: String, app_handle: tauri::AppHandle) -> Result<String, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let data_dir = app_handle.path().app_data_dir().map_err(|e| e.to_string())?;

    // Второе значение — заменили ли уже лежавшие материалы: пользователь должен
    // узнать об этом из ответа, а не обнаружить потом.
    let result = (|| -> anyhow::Result<(String, bool)> {
        use anyhow::Context as _;
        // Имя берём ТОЛЬКО из последнего сегмента пути: защита от «..» и абсолютных путей.
        let filename = std::path::Path::new(&path)
            .file_name()
            .and_then(|n| n.to_str())
            .ok_or_else(|| anyhow::anyhow!("Не удалось прочитать имя файла"))?
            .to_ascii_lowercase();

        let stem = filename.strip_suffix(".vault").ok_or_else(|| {
            anyhow::anyhow!("Нужен файл кабинета с расширением .vault, выбран «{filename}»")
        })?;
        if stem.is_empty()
            || stem.len() > 40
            || !stem.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
        {
            anyhow::bail!("Недопустимое имя файла кабинета: «{filename}»");
        }

        // Ограничение размера проверяем ДО чтения: иначе выбранный по ошибке
        // многогигабайтный файл уже окажется в памяти целиком, и проверка
        // ничего не защитит (находка аудита M-2).
        const MAX_VAULT_BYTES: u64 = 200 * 1024 * 1024;
        let declared = std::fs::metadata(&path)
            .with_context(|| format!("Не удалось прочитать сведения о файле «{filename}»"))?
            .len();
        if declared > MAX_VAULT_BYTES {
            anyhow::bail!("Файл слишком велик для материалов кабинета ({} МБ)", declared / (1024 * 1024));
        }

        let raw = std::fs::read(&path)
            .with_context(|| format!("Не удалось прочитать файл «{filename}»"))?;

        // Проверяем, что это действительно наши материалы: gzip-архив, внутри
        // которого читается хотя бы одна запись. Иначе пользователь узнал бы об
        // ошибке только при открытии кабинета, уже без подсказки.
        {
            let gz = flate2::read::GzDecoder::new(std::io::Cursor::new(raw.as_slice()));
            let mut archive = tar::Archive::new(gz);
            let mut entries = archive
                .entries()
                .context("Файл не похож на материалы кабинета: архив не читается")?;
            match entries.next() {
                Some(Ok(_)) => {}
                Some(Err(e)) => anyhow::bail!("Файл повреждён: {e}"),
                None => anyhow::bail!("Файл пуст — в нём нет материалов кабинета"),
            }
        }

        let key = content_updater::derive_local_key(&config_dir)
            .context("Не удалось получить ключ этой машины")?;
        let encrypted = crypto::aes::encrypt(&key, &raw).context("Не удалось зашифровать материалы")?;

        let vaults_dir = vault::vaults_dir(&data_dir);
        std::fs::create_dir_all(&vaults_dir).context("Не удалось создать папку материалов")?;
        let dest = vaults_dir.join(&filename);
        let replaced = dest.exists();
        std::fs::write(&dest, &encrypted)
            .with_context(|| format!("Не удалось сохранить материалы в {}", dest.display()))?;

        // Версию импортированного файла мы не знаем, поэтому снимаем отметку:
        // иначе клиент считал бы эти материалы актуальными и обновление с
        // сервера к кабинету больше не пришло бы (находка аудита M-3).
        if let Err(e) = content_updater::forget_vault_version(&config_dir, &filename) {
            warn!("Не удалось снять отметку версии после импорта {filename}: {e:#}");
        }

        info!("Материалы кабинета импортированы вручную: {} ({} байт)", filename, raw.len());
        Ok((filename, replaced))
    })();

    match result {
        Ok((filename, replaced)) => {
            metrics::audit::log_event("vault_import", &filename, true);
            let replaced_note = if replaced {
                " Прежние материалы этого кабинета заменены."
            } else {
                ""
            };
            Ok(format!(
                "Материалы кабинета загружены из файла «{filename}».{replaced_note} Откройте кабинет заново."
            ))
        }
        Err(e) => {
            let msg = format!("{e:#}");
            metrics::audit::log_event("vault_import", &msg, false);
            Err(msg)
        }
    }
}

#[tauri::command]
async fn check_online_auth(app_handle: tauri::AppHandle) -> Result<online_auth::OnlineAuthStatus, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let app_version = env!("CARGO_PKG_VERSION");
    let status = online_auth::authorize(&config_dir, app_version, "").await;

    // Phase 5: fire-and-forget background update check after successful auth
    if status.status == "ok" {
        let handle = app_handle.clone();
        let s = status.clone();
        tokio::spawn(async move {
            if let Err(e) = check_all_updates(&handle, &s).await {
                warn!("Background update check failed: {e}");
            }
        });
    }

    Ok(status)
}

/// Phase 5 auto-update: triggered after successful online auth.
/// Downloads content packs and frontend bundle if server versions are newer.
async fn check_all_updates(
    app_handle: &tauri::AppHandle,
    auth: &online_auth::OnlineAuthStatus,
) -> anyhow::Result<()> {
    let local_data_dir = app_handle.path().app_local_data_dir()?;

    // 1. Content packs
    if let Some(server_pack_ver) = auth.content_pack_version {
        let local_ver = content_updater::get_local_content_pack_version(&local_data_dir);
        if server_pack_ver > local_ver {
            if let (Some(url), Some(checksum)) = (
                auth.content_pack_url.as_deref(),
                auth.content_pack_checksum.as_deref(),
            ) {
                info!(
                    "Content pack update: local={} server={}, downloading…",
                    local_ver, server_pack_ver
                );
                content_updater::download_content_pack(&local_data_dir, url, checksum, app_handle)
                    .await?;
            }
        }
    }

    // 2. Frontend bundle
    if let Some(server_fe_ver) = auth.frontend_version {
        let local_ver = content_updater::get_local_frontend_version(&local_data_dir);
        if server_fe_ver > local_ver {
            if let (Some(url), Some(checksum)) = (
                auth.frontend_url.as_deref(),
                auth.frontend_checksum.as_deref(),
            ) {
                info!(
                    "Frontend bundle update: local={} server={}, downloading…",
                    local_ver, server_fe_ver
                );
                content_updater::download_frontend_bundle_from_url(
                    &local_data_dir,
                    url,
                    checksum,
                    server_fe_ver,
                    app_handle,
                )
                .await?;
            }
        }
    }

    Ok(())
}

#[tauri::command]
async fn send_heartbeat(app_handle: tauri::AppHandle) -> Result<online_auth::HeartbeatResponse, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    match online_auth::send_heartbeat(&config_dir).await {
        Ok(resp) => Ok(resp),
        Err(e) => {
            warn!("Heartbeat failed: {e}");
            Err(e.to_string())
        }
    }
}

#[tauri::command]
fn get_instance_id(app_handle: tauri::AppHandle) -> Result<String, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    online_auth::get_or_create_instance_id(&config_dir).map_err(|e| e.to_string())
}

#[tauri::command]
fn check_content_update(
    server_version: Option<String>,
    server_checksums: serde_json::Value,
    app_handle: tauri::AppHandle,
) -> Result<content_updater::ContentUpdateStatus, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let data_dir = app_handle.path().app_data_dir().map_err(|e| e.to_string())?;
    Ok(content_updater::check_update(
        &config_dir,
        &data_dir,
        server_version.as_deref(),
        &server_checksums,
    ))
}

#[tauri::command]
async fn update_content(
    product: String,
    version: String,
    files: Vec<String>,
    checksums: serde_json::Value,
    app_handle: tauri::AppHandle,
) -> Result<Vec<String>, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let data_dir = app_handle.path().app_data_dir().map_err(|e| e.to_string())?;
    content_updater::download_updates(&config_dir, &data_dir, &product, &version, &files, &checksums, None, Some(&app_handle))
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_local_content_version(app_handle: tauri::AppHandle) -> Result<Option<String>, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    Ok(content_updater::get_local_version(&config_dir))
}

/// Отображаемая версия приложения.
///
/// 🔴 Буква «C» тонкой редакции убрана вместе с её отдельным каналом (ADR-049 §2):
/// поставка одна, и разные номера у одного и того же бинаря только путали бы. На
/// вопрос «где исполняется работа» отвечает признак режима на рабочем экране, а не
/// буква в номере версии — он к тому же меняется по ходу работы, чего номер не умеет.
#[tauri::command]
fn display_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
fn get_machine_id() -> Result<String, String> {
    let fp = crypto::fingerprint::get_machine_fingerprint().map_err(|e| e.to_string())?;
    let hash = crypto::fingerprint::hash_fingerprint(&fp);
    Ok(hash[..12].to_string())
}

#[tauri::command]
fn get_full_machine_hash() -> Result<String, String> {
    let fp = crypto::fingerprint::get_machine_fingerprint().map_err(|e| e.to_string())?;
    Ok(crypto::fingerprint::hash_fingerprint(&fp))
}

#[tauri::command]
fn get_raw_fingerprint() -> Result<String, String> {
    crypto::fingerprint::get_raw_fingerprint_hex().map_err(|e| e.to_string())
}

/// Tier 2 (Claude-усилитель инсайтов MMM): inline-вопрос об уже посчитанном
/// результате. Тонкий транспорт — готовый grounding-промпт строит фронт
/// (`tier2-context.js`, железные правила INV-50), здесь только пересылка через
/// ЕДИНЫЙ egress-чок-поинт `run_claude` (consent + feature-гейт наследуются;
/// в локальной редакции 152-ФЗ команда вернёт ошибку «egress отключён»).
///
/// Требует открытой сессии кабинета `econometrist` (work_dir с vault) — фронт
/// открывает его лениво при первом вопросе. Stateless (resume=None): каждый
/// ответ строится строго на текущих фактах в промпте, без памяти прошлых
/// вопросов — безопаснее для INV-50.
#[tauri::command]
async fn econ_ask_insight(
    prompt: String,
    state: tauri::State<'_, Arc<AppState>>,
    app_handle: tauri::AppHandle,
) -> Result<String, String> {
    if prompt.trim().is_empty() {
        return Err("[ASK-EMPTY] Пустой запрос к ИИ".to_string());
    }
    let cabinet_id = "econometrist";
    let work_dir = state
        .session_manager
        .get_work_dir(cabinet_id)
        .ok_or_else(|| {
            "[ASK-NO-SESSION] Кабинет эконометриста не открыт — откройте его, чтобы спросить ИИ."
                .to_string()
        })?;

    let user_model = app_handle
        .path()
        .app_config_dir()
        .ok()
        .map(|d| user_config::load(&d).model)
        .unwrap_or(None);

    claude::run_claude(
        &work_dir,
        &prompt,
        app_handle.clone(),
        cabinet_id.to_string(),
        None,  // stateless — без --resume
        state.active_pids.clone(),
        true,  // suppress_export — inline-вопрос, не сохранять в exports
        user_model,
    )
    .await
    .map(|(_session_id, response_text)| response_text)
    .map_err(|e| e.to_string())
}

/// Человеческое объяснение, почему рабочие материалы не доехали, и что делать.
///
/// Раньше пользователю в любом случае сообщалось «связь обрывается при передаче
/// файла» — в том числе когда сервер отказал по существу (нет лицензии, нет
/// файла) или не отвечал вовсе (находка аудита M-5). Домысел вместо факта уводит
/// и пользователя, и поддержку по ложному следу.
fn delivery_failure_explanation(detail: &str) -> (&'static str, &'static str) {
    let d = detail.to_lowercase();

    // Код ищем ТОЛЬКО в форме «HTTP <код>»: голое вхождение «403» ловилось на
    // числе полученных байт («поток оборван на 4034 байт» содержит 403), и
    // пользователю показывалось «сервер не подтвердил право на кабинет» вместо
    // обрыва связи — поддержка уходила по ложному следу (находка аудита).
    // Наблюдённое окно обрывов 3251…5649 накрывает и 403, и 404.
    let has_http_code = |code: &str| d.contains(&format!("http {code}"));

    if has_http_code("403") || d.contains("лицензия") {
        return (
            "Сервер не подтвердил право на этот кабинет.",
            "• проверить срок действия лицензии в настройках;\n\
             • если срок в порядке – прислать отчёт диагностики в поддержку: кабинет мог быть не включён в вашу лицензию.",
        );
    }
    if has_http_code("404") || d.contains("не найден") || d.contains("не отдал файл") {
        return (
            "Нужного файла на сервере нет.",
            "• повторить открытие кабинета через несколько минут – файл может выкладываться прямо сейчас;\n\
             • если не помогает – прислать отчёт диагностики в поддержку.",
        );
    }
    if d.contains("недоступен") {
        return (
            "Сервер программы сейчас недоступен.",
            "• проверить подключение к интернету и повторить открытие кабинета;\n\
             • если компьютер работает в корпоративной сети с фильтрацией трафика – попросить администратора открыть доступ к серверу программы.",
        );
    }
    if d.contains("оборван") || d.contains("получено") || d.contains("не установилась") || d.contains("попыток") {
        return (
            "Связь с сервером обрывается при передаче файла.",
            "• проверить подключение к интернету и повторить открытие кабинета;\n\
             • если компьютер работает в корпоративной сети с фильтрацией трафика – попросить администратора открыть доступ к серверу программы;\n\
             • если не помогает – загрузить рабочие материалы из файла в настройках: их можно получить в поддержке.",
        );
    }

    (
        "Загрузка рабочих материалов не завершилась.",
        "• повторить открытие кабинета;\n\
         • если не помогает – выгрузить отчёт диагностики в настройках и прислать его в поддержку.",
    )
}

#[tauri::command]
async fn open_cabinet(
    cabinet_id: String,
    state: tauri::State<'_, Arc<AppState>>,
    app_handle: tauri::AppHandle,
) -> Result<String, String> {
    info!("Opening cabinet: {cabinet_id}");

    #[cfg(debug_assertions)]
    if std::env::var("AIAGENCY_DEV").is_ok() {
        let dev_root = std::env::var("AIAGENCY_DEV_CABINETS")
            .unwrap_or_else(|_| "New_AI_Agency".to_string());
        let cabinet_folder = cabinet::cabinet_folder_name(&cabinet_id);
        let source_dir = std::path::PathBuf::from(&dev_root).join(cabinet_folder);

        if !source_dir.exists() {
            return Err(format!("[DEV] Cabinet folder not found: {}", source_dir.display()));
        }

        let workspace = user_config::default_cabinet_workspace(&cabinet_id)?;

        info!("[DEV] Opening from {}", source_dir.display());
        let work_dir = state.session_manager
            .open_dev_session(&cabinet_id, &source_dir, &workspace)
            .map_err(|e| e.to_string())?;
        brand::write_brand_context(&work_dir, &app_handle).await;
        return Ok(work_dir.to_string_lossy().to_string());
    }

    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let data_dir = app_handle.path().app_data_dir().map_err(|e| e.to_string())?;

    // ── Try online auth to get cabinets list ──
    let app_version = env!("CARGO_PKG_VERSION");
    let online = online_auth::authorize(&config_dir, app_version, "").await;
    let allowed_cabinets: Vec<String>;

    if online.status == "ok" || online.status == "cached" {
        allowed_cabinets = online.cabinets;
    } else if online.available && online.status == "blocked" {
        let msg = online.message.unwrap_or("Доступ заблокирован".to_string());
        return Err(msg);
    } else {
        // Fallback to offline license
        let license = license::License::load(&config_dir).map_err(|e| e.to_string())?;
        let status = license.validate().map_err(|e| e.to_string())?;
        if !status.valid {
            return Err(status.error.unwrap_or("Лицензия недействительна".to_string()));
        }
        allowed_cabinets = status.cabinets;
    }

    if !allowed_cabinets.contains(&cabinet_id) {
        warn!("Cabinet '{cabinet_id}' not allowed (cabinets: {:?})", allowed_cabinets);
        // B2 (2026-07-03): русское сообщение вместо технического английского.
        return Err(format!("Кабинет «{cabinet_id}» не входит в вашу лицензию. Обратитесь в поддержку для расширения доступа."));
    }

    // ── Auto-download vault if missing ──
    let vault_filename = vault::vault_filename_pub(&cabinet_id);
    let vault_path = vault::vaults_dir(&data_dir).join(&vault_filename);

    if !vault_path.exists() {
        info!("Vault not found locally for {cabinet_id}, attempting server download...");
        // Причину неудачи держим при себе: без неё пользователь получал голое
        // «Failed to read vault: <путь>» (VT001) — техническую строку, из которой
        // не следует ни причина, ни что делать (разбор отказа у клиента 2026-07-26).
        let mut download_err: Option<String> = None;

        if let (Some(cv), true) = (&online.content_version, online.status == "ok" || online.status == "cached") {
            let product = online_auth::detect_product();
            let files = vec![vault_filename.clone()];
            // Реальные суммы от сервера, если он их прислал; иначе пустой объект —
            // как и раньше, чтобы старый сервер без vault_checksums не менял поведение
            // (download_updates журналирует пропуск сверки сам).
            let empty_checksums = serde_json::json!({});
            let checksums = online.vault_checksums.as_ref().unwrap_or(&empty_checksums);
            match content_updater::download_updates(&config_dir, &data_dir, product, cv, &files, checksums, online.vault_versions.as_ref(), Some(&app_handle)).await {
                Ok(updated) if !updated.is_empty() => info!("Downloaded {} vault files from server", updated.len()),
                Ok(_) => {
                    warn!("Vault download returned no files for {cabinet_id}");
                    download_err = Some("сервер не отдал файл кабинета".to_string());
                }
                Err(e) => {
                    warn!("Failed to download vault from server: {e:#}");
                    download_err = Some(format!("{e:#}"));
                }
            }
        } else {
            download_err = Some(format!("сервер лицензий недоступен (состояние связи: {})", online.status));
        }

        if !vault_path.exists() {
            let detail = download_err.unwrap_or_else(|| "причина неизвестна".to_string());
            error!("Кабинет {cabinet_id}: рабочие материалы не доставлены — {detail}");
            let (reason, hints) = delivery_failure_explanation(&detail);
            return Err(format!(
                "Не удалось загрузить рабочие материалы кабинета с сервера.\n\n\
                 {reason} Поэтому кабинет не открывается.\n\n\
                 Что можно сделать:\n\
                 {hints}\n\n\
                 Подробность для поддержки: кабинет {cabinet_id}, {detail}"
            ));
        }
    }

    // ── Read vault and open session ──
    let vault_data = vault::read_vault(&cabinet_id, &data_dir).map_err(|e| e.to_string())?;

    // Derive encryption key:
    // 1. Try local key (for vaults downloaded from server, encrypted by content_updater)
    // 2. Fallback to offline license key (for vaults packed by vault-pack)
    let key = match content_updater::derive_local_key(&config_dir) {
        Ok(local_key) => {
            // Verify this key works by trying to decrypt
            match crypto::aes::decrypt(&local_key, &vault_data) {
                Ok(_) => local_key,
                Err(_) => {
                    // Local key didn't work - try offline license key
                    let fp = crypto::fingerprint::get_machine_fingerprint().map_err(|e| e.to_string())?;
                    match license::License::load(&config_dir) {
                        Ok(lic) => match lic.salt_bytes() {
                            Ok(salt) => crypto::hkdf::derive_key(&fp, &salt).map_err(|e| e.to_string())?,
                            Err(e) => return Err(e.to_string()),
                        },
                        Err(e) => return Err(format!("Не удалось расшифровать данные кабинета: нет действующего ключа. {e}")),
                    }
                }
            }
        }
        Err(_) => {
            // No local salt - use offline license key
            let fp = crypto::fingerprint::get_machine_fingerprint().map_err(|e| e.to_string())?;
            let lic = license::License::load(&config_dir).map_err(|e| e.to_string())?;
            let salt = lic.salt_bytes().map_err(|e| e.to_string())?;
            crypto::hkdf::derive_key(&fp, &salt).map_err(|e| e.to_string())?
        }
    };

    // User workspace (configurable per cabinet)
    let workspace = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?;

    let work_dir = state.session_manager
        .open_session(&cabinet_id, &vault_data, &key, &workspace)
        .map_err(|e| {
            error!("Failed to open session for {cabinet_id}: {e}");
            e.to_string()
        })?;

    // Write brand context for Claude (best-effort, non-blocking)
    brand::write_brand_context(&work_dir, &app_handle).await;

    metrics::audit::log_event("cabinet_open", &cabinet_id, true);
    info!("Cabinet {cabinet_id} opened → {}", work_dir.display());
    let _ = metrics::collector::record_session(&cabinet_id);
    Ok(work_dir.to_string_lossy().to_string())
}

#[tauri::command]
fn close_cabinet(
    cabinet_id: String,
    state: tauri::State<'_, Arc<AppState>>,
) -> Result<(), String> {
    info!("Closing cabinet: {cabinet_id}");
    metrics::audit::log_event("cabinet_close", &cabinet_id, true);
    state.session_manager
        .close_session(&cabinet_id)
        .map_err(|e| {
            error!("Failed to close cabinet {cabinet_id}: {e}");
            e.to_string()
        })
}

/// Extract brief parameters from a multiline command message.
/// Input: "/analytics\nСлайды: Все\nАудитория: CEO, CMO\nДополнительно: Фокус"
/// Output: Some("Слайды: Все\nАудитория: CEO, CMO\nДополнительно: Фокус")
/// Returns None if message is single-line (no brief params).
fn extract_brief_params(message: &str) -> Option<String> {
    let trimmed = message.trim();
    if let Some(newline_pos) = trimmed.find('\n') {
        let params = trimmed[newline_pos + 1..].trim();
        if !params.is_empty() {
            return Some(params.to_string());
        }
    }
    None
}

/// Parse slide selection from brief params.
/// Looks for a line starting with "Слайды:" containing "Конкретные".
/// Parses the numbers/ranges after the last colon: "3, 7-10, 15" → [3, 7, 8, 9, 10, 15]
/// Returns None if slides are "Все" or no slide parameter found.
fn parse_slide_selection(params: &str) -> Option<Vec<u32>> {
    for line in params.lines() {
        let trimmed = line.trim();
        if !trimmed.starts_with("Слайды:") && !trimmed.starts_with("Слайды :") {
            continue;
        }
        let lower = trimmed.to_lowercase();
        if lower.contains("все") || lower.contains("all") {
            return None;
        }
        let list_part = trimmed.rsplit(':').next()?;
        let mut nums = Vec::new();
        for part in list_part.split(',') {
            let part = part.trim();
            let range_sep = if part.contains('–') { '–' } else { '-' };
            if let Some((start_s, end_s)) = part.split_once(range_sep) {
                if let (Ok(s), Ok(e)) = (start_s.trim().parse::<u32>(), end_s.trim().parse::<u32>()) {
                    for n in s..=e {
                        nums.push(n);
                    }
                }
            } else if let Ok(n) = part.parse::<u32>() {
                nums.push(n);
            }
        }
        if !nums.is_empty() {
            return Some(nums);
        }
    }
    None
}

/// Multi-phase analytics pipeline for large PPTX presentations.
/// Chains Phase 0 (map) → Phase 1 (detail chunks) → Phase 2 (synthesis) via --resume.
/// Returns (phase1_markdowns, synthesis_markdown, final_session_id).
#[allow(clippy::too_many_arguments)]
async fn run_analytics_pipeline(
    work_dir: &std::path::Path,
    overview: &str,
    chunk_split: &commands::pptx_processor::ChunkSplit,
    brief_params: Option<&str>,
    analytics_context: Option<&str>,
    app_handle: tauri::AppHandle,
    cabinet_id: &str,
    active_pids: Arc<std::sync::Mutex<std::collections::HashMap<String, u32>>>,
    state: &AppState,
) -> Result<(Vec<String>, String, Option<String>), String> {
    let total_phases = chunk_split.chunk_count + 2; // map + N chunks + synthesis
    let mut session_id: Option<String> = state.session_manager.get_claude_session_id(cabinet_id);
    let mut chunk_markdowns: Vec<String> = Vec::new();

    // Build parameters block for injection into phase prompts
    let params_block = brief_params.map(|p| {
        format!(
            "\n\n[ПАРАМЕТРЫ ЗАПУСКА ИЗ UI - ПРИОРИТЕТ НАД ДЕФОЛТАМИ]\n{}\n\
             Применяй эти параметры строго:\n\
             - Аудитория: писать ТОЛЬКО указанные уровни ([CEO]/[CMO]/[BM])\n\
             - Дополнительно: учесть как фокус во всех комментариях\n",
            p
        )
    }).unwrap_or_default();

    // Helper: emit pipeline phase event
    let emit_phase = |label: &str, index: usize| {
        let _ = app_handle.emit(
            &format!("claude-stream-{cabinet_id}"),
            serde_json::json!({
                "type": "pipeline_phase",
                "label": label,
                "phase_index": index,
                "total_phases": total_phases,
            }).to_string(),
        );
    };

    // ═══ PHASE 0: MAP ═══
    emit_phase("Сканирую структуру презентации...", 0);
    let analytics_block = analytics_context
        .map(|ctx| format!("\n\n{}", ctx))
        .unwrap_or_default();
    let phase0_prompt = format!(
        "[АНАЛИТИЧЕСКИЙ ПАЙПЛАЙН - ФАЗА 0: КАРТА]\n\n{}{}{}\n\n\
         Задача: определи тематические блоки презентации. Для каждого блока укажи:\n\
         - Название блока\n- Диапазон слайдов\n- Краткое описание\n\n\
         Затем сформулируй 3-5 гипотез для проверки при детальном анализе.\n\n\
         Формат:\n## СТРУКТУРА ПРЕЗЕНТАЦИИ\n## БЛОК: Название - слайды X-Y\n## ГИПОТЕЗЫ ДЛЯ ПРОВЕРКИ",
        overview,
        analytics_block,
        params_block
    );

    match commands::claude::run_claude_pipeline(work_dir, &phase0_prompt, app_handle.clone(), cabinet_id.to_string(), session_id.clone(), active_pids.clone()).await {
        Ok((sid, _phase0_text)) => {
            if let Some(s) = sid { session_id = Some(s.clone()); state.session_manager.set_claude_session_id(cabinet_id, s); }
        }
        Err(e) => {
            warn!("Pipeline Phase 0 failed: {e}");
            return Err(format!("Phase 0 (map) failed: {e}"));
        }
    }

    // ═══ PHASE 1: DETAIL CHUNKS ═══
    for (i, chunk_path) in chunk_split.chunk_files.iter().enumerate() {
        // Check if cancelled between chunks (cancel_claude kills process but pipeline loop continues)

        emit_phase(&format!("Анализирую чанк {}/{}...", i + 1, chunk_split.chunk_count), i + 1);

        // Read chunk data and inject directly into prompt (avoids file-read issues)
        let chunk_data = std::fs::read_to_string(chunk_path).unwrap_or_default();
        let phase1_prompt = format!(
            "[АНАЛИТИЧЕСКИЙ ПАЙПЛАЙН - ФАЗА 1: ДЕТАЛЬНЫЙ АНАЛИЗ]\n\
             Чанк {}/{}. Вот данные слайдов:\n\n{}{}\n\n\
             Для каждого слайда напиши на русском языке:\n\
             ## Слайд N: Заголовок\nЗАГОЛОВОК: ...\n\n[CEO] ...\n\n[CMO] ...\n\n[BM] ...\n\n\
             В конце - краткие итоги для слайдов этого чанка.",
            i + 1, chunk_split.chunk_count, chunk_data,
            params_block
        );

        let mut retry = 0;
        loop {
            match commands::claude::run_claude_pipeline(work_dir, &phase1_prompt, app_handle.clone(), cabinet_id.to_string(), session_id.clone(), active_pids.clone()).await {
                Ok((sid, chunk_response)) => {
                    if let Some(s) = sid { session_id = Some(s.clone()); state.session_manager.set_claude_session_id(cabinet_id, s); }
                    info!("Pipeline chunk {}/{} done, response {} bytes", i + 1, chunk_split.chunk_count, chunk_response.len());
                    chunk_markdowns.push(chunk_response);
                    break;
                }
                Err(e) if e.to_string().contains("retryable") && retry < 1 => {
                    retry += 1;
                    warn!("Pipeline chunk {}/{} retryable error, retry {retry}: {e}", i + 1, chunk_split.chunk_count);
                    tokio::time::sleep(std::time::Duration::from_secs(4)).await;
                    continue;
                }
                Err(e) => {
                    warn!("Pipeline chunk {}/{} failed, skipping: {e}", i + 1, chunk_split.chunk_count);
                    chunk_markdowns.push(format!("(Чанк {} пропущен: ошибка)", i + 1));
                    break;
                }
            }
        }
    }

    // ═══ PHASE 2: SYNTHESIS ═══
    emit_phase("Формирую Executive Summary и мосты...", total_phases - 1);

    let recap = commands::pptx_processor::generate_recap(&chunk_markdowns);
    let phase2_prompt = format!(
        "[АНАЛИТИЧЕСКИЙ ПАЙПЛАЙН - ФАЗА 2: СИНТЕЗ]\n\n\
         Ты проанализировал все {} слайдов с данными ({} чанков). \
         Вот краткий обзор:\n\n{}{}\n\n\
         Теперь напиши на русском языке:\n\
         ## EXECUTIVE SUMMARY\n5-7 тезисов по Pyramid Principle (главное → детали)\n\n\
         ## ОБЩИЙ ВЫВОД ПО ПРЕЗЕНТАЦИИ\nРазвёрнутый аналитический нарратив на ~1 страницу (4-6 абзацев): \
         что происходит на рынке, какие силы действуют, куда движется ситуация, \
         что это значит для бизнеса, стратегические развилки.\n\n\
         ## БЛОК: Название\nДля каждого блока: тезисы (bullets) + развёрнутый вывод (1-2 абзаца)\n\n\
         ## МОСТЫ\nМинимум 5 межтематических связей (каузальные цепочки)\n\n\
         ## РЕКОМЕНДАЦИИ\nСтратегические рекомендации с ICE-приоритизацией",
        chunk_split.data_slide_count, chunk_split.chunk_count, recap,
        params_block
    );

    let mut synthesis_md = String::new();
    match commands::claude::run_claude_pipeline(work_dir, &phase2_prompt, app_handle.clone(), cabinet_id.to_string(), session_id.clone(), active_pids.clone()).await {
        Ok((sid, synthesis_response)) => {
            if let Some(s) = sid { session_id = Some(s.clone()); state.session_manager.set_claude_session_id(cabinet_id, s); }
            info!("Pipeline Phase 2 done, synthesis {} bytes", synthesis_response.len());
            synthesis_md = synthesis_response;
        }
        Err(e) => {
            warn!("Pipeline Phase 2 (synthesis) failed: {e}");
            // Non-fatal: we still have Phase 1 notes
        }
    }

    Ok((chunk_markdowns, synthesis_md, session_id))
}

/// Resolve a slash-command message by reading the corresponding .md file
/// from .claude/commands/ and substituting $ARGUMENTS.
/// If not a slash-command or file not found, returns the original message.
fn resolve_slash_command(message: &str, work_dir: &std::path::Path) -> String {
    let trimmed = message.trim();
    if !trimmed.starts_with('/') {
        return message.to_string();
    }

    // Extract command name and arguments
    let first_line_end = trimmed.find('\n').unwrap_or(trimmed.len());
    let first_line = &trimmed[..first_line_end];
    let command_name = first_line.split_whitespace().next().unwrap_or("/");
    let cmd_slug = command_name.trim_start_matches('/');

    if cmd_slug.is_empty() {
        return message.to_string();
    }

    // Arguments = everything after the command name on first line + all subsequent lines
    let args_start = trimmed.find('\n').map(|p| p + 1).unwrap_or(trimmed.len());
    let arguments = if args_start < trimmed.len() {
        trimmed[args_start..].trim()
    } else {
        ""
    };

    // Try to read .claude/commands/{cmd_slug}.md
    let md_path = work_dir.join(".claude").join("commands").join(format!("{}.md", cmd_slug));
    if !md_path.exists() {
        debug!("No command file for /{cmd_slug}, passing raw message");
        return message.to_string();
    }

    match std::fs::read_to_string(&md_path) {
        Ok(template) => {
            let resolved = template.replace("$ARGUMENTS", arguments);
            info!("Resolved /{cmd_slug} command ({} bytes template, {} bytes args)", template.len(), arguments.len());
            resolved
        }
        Err(e) => {
            warn!("Failed to read command file {}: {e}", md_path.display());
            message.to_string()
        }
    }
}

// Авто-сохранение отчёта (.md → .docx/.pdf/.xlsx) подавляется ТОЛЬКО по явному
// suppress_export=true (промежуточные шаги auto-continue из ChatPanel). Часть команд
// econometrist отвечает в чат без self-export — им нужен именно этот авто-.md для
// карточки «Оформить отчёт»; команды с явным self-export (Write в exports/) получат
// дополнительный сырой .md-дубль — минорный побочный эффект, не потеря данных.
// Рудимент `|| starts_with('/')` снят 2026-07-24 (CPD-17, пришёл sync-коммитом 43d0a8f,
// глушил авто-.md для всех slash-команд).

#[tauri::command]
async fn send_message(
    cabinet_id: String,
    message: String,
    suppress_export: Option<bool>,
    state: tauri::State<'_, Arc<AppState>>,
    app_handle: tauri::AppHandle,
) -> Result<(), String> {
    let msg_preview = if message.len() > 80 {
        let end = (0..=80).rev().find(|&i| message.is_char_boundary(i)).unwrap_or(0);
        &message[..end]
    } else {
        &message
    };
    info!("send_message [{cabinet_id}]: \"{msg_preview}\"");

    // Record metrics
    let command_slug = if message.trim().starts_with('/') {
        message.trim()[1..].split_whitespace().next().map(|s| s.to_string())
    } else {
        None
    };
    let _ = metrics::collector::record_message(command_slug.as_deref());
    let msg_start = std::time::Instant::now();

    let work_dir = state.session_manager
        .get_work_dir(&cabinet_id)
        .ok_or("Cabinet session not open")?;

    // Sync Desktop inbox → workspace before running Claude
    state.session_manager
        .sync_inbox(&cabinet_id)
        .map_err(|e| e.to_string())?;

    // ── Slash-command detection (used for preprocessing, clean slate, session management) ──
    let is_slash_command = message.trim().starts_with('/');

    // PPTX Pipeline: preprocess the FIRST (largest) PPTX file for media-analyst cabinet
    let mut analytics_context: Option<String> = None;
    let mut pptx_filename: Option<String> = None;
    if cabinet_id == "media-analyst" && is_slash_command {
        let inbox_dir = work_dir.join("inbox");
        if inbox_dir.exists() {
            // Find the largest PPTX file in inbox (most likely the main presentation)
            let mut pptx_files: Vec<std::path::PathBuf> = Vec::new();
            if let Ok(entries) = std::fs::read_dir(&inbox_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.extension().is_some_and(|e| e.eq_ignore_ascii_case("pptx")) {
                        pptx_files.push(path);
                    }
                }
            }
            // Sort by size descending - preprocess the largest one
            pptx_files.sort_by(|a, b| {
                let sa = a.metadata().map(|m| m.len()).unwrap_or(0);
                let sb = b.metadata().map(|m| m.len()).unwrap_or(0);
                sb.cmp(&sa)
            });
            if let Some(largest) = pptx_files.first() {
                pptx_filename = largest.file_name().map(|n| n.to_string_lossy().to_string());
                let output_dir = work_dir.join("preprocessed");
                // Clean stale preprocessed data from previous runs
                if output_dir.exists() {
                    let _ = std::fs::remove_dir_all(&output_dir);
                }
                let _ = std::fs::create_dir_all(&output_dir);
                if pptx_files.len() > 1 {
                    warn!("Multiple PPTX in inbox ({}), preprocessing largest: {}", pptx_files.len(), largest.display());
                }
                match commands::pptx_processor::preprocess(largest, &output_dir) {
                    Ok(slides_json) => {
                        info!("PPTX preprocessed for media-analyst: {}", slides_json.display());
                        // Aurora Index: compute analytics from slides.json
                        let slides_path = output_dir.join("slides.json");
                        if let Ok(content) = std::fs::read_to_string(&slides_path) {
                            if let Ok(slides) = serde_json::from_str::<Vec<serde_json::Value>>(&content) {
                                let analytics = commands::pptx_processor::compute_analytics(&slides);
                                let analytics_path = output_dir.join("analytics.json");
                                let _ = std::fs::write(
                                    &analytics_path,
                                    serde_json::to_string_pretty(&analytics).unwrap_or_default(),
                                );
                                info!("Aurora Index: {} blocks, {} anomalies, {} trends, {} links",
                                    analytics.health.block_count, analytics.health.anomaly_count,
                                    analytics.trends.len(), analytics.health.cross_link_count);
                                analytics_context = Some(
                                    commands::pptx_processor::format_analytics_context(&analytics)
                                );
                            }
                        }
                    }
                    Err(e) => {
                        warn!("PPTX preprocess failed (non-critical): {e}");
                        // Notify frontend so user knows preprocessed data won't be available
                        let _ = app_handle.emit(
                            &format!("claude-stream-{cabinet_id}"),
                            serde_json::json!({
                                "type": "status",
                                "message": "Предобработка PPTX не удалась - анализ продолжится без структурированных данных из графиков"
                            }).to_string(),
                        );
                    }
                }
            }
        }
    }

    // ── Clean slate for slash-commands: fresh session, no stale context ──
    if is_slash_command {
        state.session_manager.clear_claude_session_id(&cabinet_id);
    }

    // Multi-phase pipeline for large presentations (>15 data slides)
    let is_analytics = message.trim().starts_with("/analytics") || message.trim().starts_with("/batch-analytics");
    // Extract CommandBrief parameters for pipeline injection
    let brief_params = extract_brief_params(&message);
    let selected_slides = brief_params.as_deref().and_then(parse_slide_selection);
    if let Some(ref params) = brief_params {
        info!("CommandBrief params detected: {} bytes", params.len());
        if let Some(ref slides) = selected_slides {
            info!("User selected specific slides: {:?}", slides);
        }
    }
    if cabinet_id == "media-analyst" && is_analytics {
        let slides_json_path = work_dir.join("preprocessed").join("slides.json");
        if slides_json_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&slides_json_path) {
                if let Ok(slides) = serde_json::from_str::<Vec<serde_json::Value>>(&content) {
                    // Count data slides AFTER applying user's slide selection filter
                    let data_count = slides.iter()
                        .filter(|s| s["type"] == "data")
                        .filter(|s| {
                            match &selected_slides {
                                Some(nums) => s["slide_num"].as_u64()
                                    .map(|n| nums.contains(&(n as u32)))
                                    .unwrap_or(false),
                                None => true,
                            }
                        })
                        .count();
                    if data_count > 15 {
                        info!("Large PPTX detected: {data_count} data slides → multi-phase pipeline");
                        let overview = commands::pptx_processor::generate_overview(&slides);
                        let preprocessed_dir = work_dir.join("preprocessed");
                        // 80KB per chunk - prompt piped via temp file, no cmd line limit
                                match commands::pptx_processor::split_into_chunks(&slides, &preprocessed_dir, 80_000, selected_slides.as_deref()) {
                            Ok(chunk_split) => {
                                let pipeline_result = run_analytics_pipeline(
                                    &work_dir, &overview, &chunk_split,
                                    brief_params.as_deref(),
                                    None, // analytics_context disabled: overwhelms Claude, causes format switch
                                    app_handle.clone(), &cabinet_id,
                                    state.active_pids.clone(),
                                    &state,
                                ).await;

                                match pipeline_result {
                                    Ok((phase_markdowns, synthesis_md, final_sid)) => {
                                        // Store session ID for future resume
                                        if let Some(sid) = final_sid {
                                            state.session_manager.set_claude_session_id(&cabinet_id, sid);
                                        }

                                        // Merge Phase 1 notes → notes.json
                                        let notes = commands::pptx_processor::merge_chunk_notes(&phase_markdowns);
                                        let exports_dir = work_dir.join("exports");
                                        let _ = std::fs::create_dir_all(&exports_dir);
                                        let _ = std::fs::create_dir_all(&preprocessed_dir);

                                        let notes_json_path = preprocessed_dir.join("notes.json");
                                        let _ = std::fs::write(&notes_json_path, serde_json::to_string_pretty(&notes).unwrap_or_default());

                                        // Save synthesis markdown
                                        let synthesis_path = preprocessed_dir.join("synthesis.md");
                                        let _ = std::fs::write(&synthesis_path, &synthesis_md);

                                        let styles_json = preprocessed_dir.join("styles.json");

                                        // Generate output files
                                        if let Some(ref fname) = pptx_filename {
                                            let pptx_path = work_dir.join("inbox").join(fname);
                                            let stem = std::path::Path::new(fname).file_stem()
                                                .map(|s| s.to_string_lossy().to_string())
                                                .unwrap_or_else(|| "output".to_string());

                                            let commented_pptx = exports_dir.join(format!("{}_commented.pptx", stem));
                                            let commentary_docx = exports_dir.join(format!("{}_commentary.docx", stem));

                                            // Inject notes into PPTX
                                            if let Err(e) = commands::pptx_processor::inject_notes(&pptx_path, &notes_json_path, &commented_pptx) {
                                                warn!("Pipeline inject_notes failed: {e}");
                                            }
                                            // Generate DOCX with synthesis
                                            if synthesis_md.trim().is_empty() {
                                                if let Err(e) = commands::pptx_processor::generate_docx(&pptx_path, &notes_json_path, &styles_json, &commentary_docx) {
                                                    warn!("Pipeline generate_docx failed: {e}");
                                                }
                                            } else if let Err(e) = commands::pptx_processor::generate_docx_with_synthesis(&pptx_path, &notes_json_path, &styles_json, &synthesis_path, &commentary_docx) {
                                                warn!("Pipeline generate_docx_with_synthesis failed: {e}");
                                            }
                                            // Add summary slides from synthesis
                                            if !synthesis_md.trim().is_empty() {
                                                let slides_json_path = preprocessed_dir.join("slides.json");
                                                match commands::pptx_processor::inject_summary_slides(
                                                    &commented_pptx, &synthesis_path, &styles_json, &slides_json_path, &commented_pptx
                                                ) {
                                                    Ok(_) => info!("Summary slides added to {}", commented_pptx.display()),
                                                    Err(e) => warn!("inject_summary_slides failed (non-critical): {e}"),
                                                }
                                            }
                                        }

                                        // Emit combined response to frontend
                                        let mut full_response = phase_markdowns.join("\n\n---\n\n");
                                        if !synthesis_md.trim().is_empty() {
                                            full_response.push_str("\n\n═══════════════════════════════════════\n\n");
                                            full_response.push_str(&synthesis_md);
                                        }
                                        let _ = app_handle.emit(
                                            &format!("claude-stream-{cabinet_id}"),
                                            serde_json::json!({ "type": "result", "result": full_response }).to_string(),
                                        );
                                        let _ = app_handle.emit(
                                            &format!("claude-done-{cabinet_id}"),
                                            serde_json::json!({ "exit_code": 0 }).to_string(),
                                        );

                                        // Sync exports + notify.
                                        // Находка внешнего аудита: имена незаписанных файлов
                                        // отбрасывались молча — гарантия «отказ виден» держалась
                                        // на одном вызове из трёх.
                                        match state.session_manager.sync_exports(&cabinet_id) {
                                            Ok(blocked) if !blocked.is_empty() => warn!(
                                                "Не обновлены в папке результатов [{cabinet_id}]: {}",
                                                blocked.join(", ")
                                            ),
                                            Ok(_) => {}
                                            Err(e) => warn!("Синхронизация выгрузок не прошла [{cabinet_id}]: {e}"),
                                        }
                                        let _ = app_handle.emit(&format!("exports-updated-{}", cabinet_id), ());

                                        let elapsed = msg_start.elapsed().as_secs_f64();
                                        info!("send_message [{cabinet_id}] pipeline complete ({elapsed:.1}s), {data_count} data slides, {} chunks", chunk_split.chunk_count);
                                        return Ok(());
                                    }
                                    Err(e) => {
                                        warn!("Pipeline failed, falling back to single-shot: {e}");
                                        // Cleanup leftover chunk files from failed pipeline
                                        if let Ok(entries) = std::fs::read_dir(&preprocessed_dir) {
                                            for entry in entries.flatten() {
                                                let name = entry.file_name().to_string_lossy().to_string();
                                                if name.starts_with("chunk_") && name.ends_with(".json") {
                                                    let _ = std::fs::remove_file(entry.path());
                                                }
                                            }
                                        }
                                        // Fall through to normal single-shot flow
                                    }
                                }
                            }
                            Err(e) => warn!("split_into_chunks failed: {e}"),
                        }
                    }
                }
            }
        }
    }

    // --resume only for free chat, never for slash-commands (already cleared above)
    let resume_session_id = if is_slash_command {
        None
    } else {
        state.session_manager.get_claude_session_id(&cabinet_id)
    };
    let is_continuation = !is_slash_command && state.session_manager.should_continue(&cabinet_id);
    debug!("Claude session resume_id={}, continuation={is_continuation}, work_dir={}",
        resume_session_id.as_deref().unwrap_or("none"), work_dir.display());

    // Resolve slash-command: read .md file and substitute $ARGUMENTS inline
    // Claude CLI --print mode may not process slash-commands from .claude/commands/
    let resolved_message = resolve_slash_command(&message, &work_dir);

    // Aurora Index context: full inject only for /aurora-index, skip for other commands
    // (full analytics context overwhelms /analytics and causes Claude to switch to diagnostic format)
    let is_aurora_index = message.trim().starts_with("/aurora-index");
    let _is_check = message.trim().starts_with("/check");
    let final_message = if is_aurora_index {
        // Aurora Index: inject both analytics context AND slides.json
        let slides_json_path = work_dir.join("preprocessed").join("slides.json");
        let mut parts = Vec::new();
        if let Some(ref ctx) = analytics_context {
            parts.push(ctx.clone());
        }
        if slides_json_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&slides_json_path) {
                info!("Injecting slides.json ({} bytes) into aurora-index message", content.len());
                parts.push(format!(
                    "[СЛАЙДЫ ПРЕЗЕНТАЦИИ - preprocessed/slides.json]\n{}\n[/СЛАЙДЫ ПРЕЗЕНТАЦИИ]\n\nДанные уже предоставлены выше. НЕ читать PPTX файлы из inbox напрямую.",
                    content
                ));
            }
        }
        if parts.is_empty() {
            resolved_message
        } else {
            parts.push(resolved_message);
            parts.join("\n\n")
        }
    } else if cabinet_id == "media-analyst" && is_slash_command {
        // Inject slides.json for ALL media-analyst slash commands (not just /analytics).
        // All commands need presentation data: /benchmark, /bridges, /action-title, etc.
        let slides_json_path = work_dir.join("preprocessed").join("slides.json");
        if slides_json_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&slides_json_path) {
                info!("Injecting slides.json ({} bytes) into message for {}", content.len(), cabinet_id);
                format!(
                    "[СЛАЙДЫ ПРЕЗЕНТАЦИИ - preprocessed/slides.json]\n{}\n[/СЛАЙДЫ ПРЕЗЕНТАЦИИ]\n\nДанные уже предоставлены выше. НЕ читать PPTX файлы из inbox напрямую.\n\n{}",
                    content,
                    resolved_message
                )
            } else {
                resolved_message
            }
        } else {
            resolved_message
        }
    } else {
        resolved_message
    };

    // Load user model preference
    let user_model = app_handle.path().app_config_dir().ok()
        .map(|d| user_config::load(&d).model)
        .unwrap_or(None);

    let max_retries = 2u32;
    let mut attempt = 0u32;
    let mut use_resume = resume_session_id.clone();
    #[allow(unused_assignments)]
    let mut last_response_text = String::new();
    loop {
        // On retry, don't use --resume (start fresh)
        let resume_for_attempt = if attempt == 0 { use_resume.clone() } else { None };

        let result = claude::run_claude(
            &work_dir,
            &final_message,
            app_handle.clone(),
            cabinet_id.clone(),
            resume_for_attempt,
            state.active_pids.clone(),
            suppress_export.unwrap_or(false),
            user_model.clone(),
        ).await;

        match result {
            Ok((new_session_id, response_text)) => {
                // Store session_id for future --resume
                if let Some(sid) = new_session_id {
                    state.session_manager.set_claude_session_id(&cabinet_id, sid);
                }
                last_response_text = response_text;
                break;
            }
            Err(e) if e.to_string().contains("retryable_error") && attempt < max_retries => {
                attempt += 1;
                let backoff = 2u64.pow(attempt); // 2s, 4s
                warn!("Retryable error for {cabinet_id}, attempt {attempt}/{max_retries}, backoff {backoff}s");
                // Clear partial response from previous attempt before retry
                let _ = app_handle.emit(
                    &format!("claude-stream-{cabinet_id}"),
                    serde_json::json!({ "type": "clear_response" }).to_string(),
                );
                let _ = app_handle.emit(
                    &format!("claude-stream-{cabinet_id}"),
                    serde_json::json!({
                        "type": "retry",
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "backoff_secs": backoff
                    }).to_string(),
                );
                tokio::time::sleep(std::time::Duration::from_secs(backoff)).await;
            }
            // Gateway-ошибки (feature `thin`, префикс [TC-GW-) — транспорт/сервер, НЕ отказ
            // resume: сброс контекста здесь ложно сообщал бы «Начинаю новую сессию», терял
            // живой серверный label при транзиентном сбое и делал лишний повторный вызов
            // (аудит 2026-07-20). Пусть падают в честную ошибку ниже — label сохраняется,
            // пользователь повторит отправку в тот же диалог. CLI-путь не задет (его ошибки
            // такого префикса не имеют).
            Err(e) if use_resume.is_some() && attempt == 0
                && !e.to_string().starts_with("[TC-GW-") =>
            {
                // --resume failed, try fresh session as fallback
                warn!("Resume failed for {cabinet_id}, retrying without resume: {e}");
                // Clear partial response from failed resume attempt
                let _ = app_handle.emit(
                    &format!("claude-stream-{cabinet_id}"),
                    serde_json::json!({ "type": "clear_response" }).to_string(),
                );
                let _ = app_handle.emit(
                    &format!("claude-stream-{cabinet_id}"),
                    serde_json::json!({
                        "type": "system",
                        "subtype": "resume_fallback",
                        "message": "Контекст диалога сброшен. Начинаю новую сессию."
                    }).to_string(),
                );
                use_resume = None;
                continue;
            }
            Err(e) => {
                error!("Claude run failed for {cabinet_id}: {e}");
                return Err(e.to_string());
            }
        }
    }

    // ─── Auto-postprocess: generate _commented.pptx + _commentary.docx ───
    // For media-analyst: parse Claude's response → split into slide notes + synthesis → create output files
    if cabinet_id == "media-analyst" && is_analytics {
        if let Some(fname) = pptx_filename.as_ref() {
        let exports_dir = work_dir.join("exports");
        let preprocessed_dir = work_dir.join("preprocessed");
        let response_md = last_response_text.clone();
        if !response_md.is_empty() {
            // Split response into slide notes and synthesis (Executive Summary, blocks, bridges, recommendations)
            let (notes_md, synthesis_md) = commands::pptx_processor::split_response_notes_and_synthesis(&response_md);
            let notes = commands::pptx_processor::parse_response_to_notes(&notes_md);
            if !notes.is_empty() {
                let pptx_path = work_dir.join("inbox").join(fname);
                let stem = std::path::Path::new(fname).file_stem()
                    .map(|s| s.to_string_lossy().to_string())
                    .unwrap_or_else(|| "output".to_string());

                let _ = std::fs::create_dir_all(&preprocessed_dir);
                let notes_json_path = preprocessed_dir.join("notes.json");
                let _ = std::fs::write(&notes_json_path, serde_json::to_string_pretty(&notes).unwrap_or_default());

                let commented_pptx = exports_dir.join(format!("{}_commented.pptx", stem));
                let commentary_docx = exports_dir.join(format!("{}_commentary.docx", stem));
                let styles_json = preprocessed_dir.join("styles.json");

                if pptx_path.exists() {
                    // Inject notes into PPTX
                    match commands::pptx_processor::inject_notes(&pptx_path, &notes_json_path, &commented_pptx) {
                        Ok(_) => info!("Auto-postprocess: created {}", commented_pptx.display()),
                        Err(e) => warn!("Auto-postprocess inject_notes failed: {e}"),
                    }
                    // Generate DOCX - with synthesis prefix if present
                    if synthesis_md.trim().is_empty() {
                        match commands::pptx_processor::generate_docx(&pptx_path, &notes_json_path, &styles_json, &commentary_docx) {
                            Ok(_) => info!("Auto-postprocess: created {} (no synthesis)", commentary_docx.display()),
                            Err(e) => warn!("Auto-postprocess generate_docx failed: {e}"),
                        }
                    } else {
                        let synthesis_path = preprocessed_dir.join("synthesis.md");
                        let _ = std::fs::write(&synthesis_path, &synthesis_md);
                        match commands::pptx_processor::generate_docx_with_synthesis(&pptx_path, &notes_json_path, &styles_json, &synthesis_path, &commentary_docx) {
                            Ok(_) => info!("Auto-postprocess: created {} (with synthesis)", commentary_docx.display()),
                            Err(e) => warn!("Auto-postprocess generate_docx_with_synthesis failed: {e}"),
                        }
                        // Add summary slides from synthesis
                        let slides_json_path = preprocessed_dir.join("slides.json");
                        match commands::pptx_processor::inject_summary_slides(
                            &commented_pptx, &synthesis_path, &styles_json, &slides_json_path, &commented_pptx
                        ) {
                            Ok(_) => info!("Auto-postprocess: summary slides added to {}", commented_pptx.display()),
                            Err(e) => warn!("inject_summary_slides failed (non-critical): {e}"),
                        }
                    }
                }
            } else {
                info!("Auto-postprocess: no slide sections found in response, skipping PPTX/DOCX generation");
            }
        }
        }
    }

    // Sync workspace exports → Desktop after Claude finishes.
    // 🔴 Находка внешнего аудита (Medium): занятый файл-приёмник (клиент открыл выданный .docx в
    // Word — os error 32) валил ВЕСЬ ответ, хотя работа советника уже сделана. Теперь отказ по
    // отдельным файлам не рвёт ответ, но и не проглатывается: клиент видит, что именно не
    // обновилось и почему (INV-50). Структурный отказ синхронизации по-прежнему отказ.
    match state.session_manager.sync_exports(&cabinet_id) {
        Ok(blocked) if !blocked.is_empty() => {
            warn!("Не обновлены в папке результатов [{cabinet_id}]: {}", blocked.join(", "));
            // 🔴 Тип события — `notice`, а НЕ `error` (находка внешнего аудита). Событие с типом
            // `error` фронт проводит через `getEmpathyError`, и без кода `[CL-NN]` заголовок
            // жёстко становится «Произошла ошибка», а точный текст уходит в подпись. Человек
            // читает первую строку — «ошибка» там, где ответ получен полностью: ровно то ложное
            // утверждение продукта о себе (INV-50), которое этот блок и выкорчёвывает.
            let _ = app_handle.emit(
                &format!("claude-stream-{cabinet_id}"),
                serde_json::json!({
                    "type": "notice",
                    "message": format!(
                        "Ответ получен. Не обновлены файлы в папке результатов: {}. \
                         Вероятная причина – файл открыт в другой программе. Закройте его, \
                         следующий ответ обновит файл.",
                        blocked.join(", ")
                    )
                })
                .to_string(),
            );
        }
        Ok(_) => {}
        Err(e) => return Err(e.to_string()),
    }

    // Auto-route artifacts to target cabinets' inboxes
    if let Err(e) = state.session_manager.auto_route_artifacts(&cabinet_id) {
        warn!("Auto-route failed for {cabinet_id}: {e}");
    }

    let elapsed = msg_start.elapsed().as_secs_f64();
    let _ = metrics::collector::record_response_time(elapsed);
    info!("send_message [{cabinet_id}] complete ({elapsed:.1}s)");

    // Notify frontend about new exports
    let _ = app_handle.emit(&format!("exports-updated-{}", cabinet_id), ());

    Ok(())
}

#[tauri::command]
fn list_inbox_files(cabinet_id: String, app_handle: tauri::AppHandle) -> Result<Vec<String>, String> {
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let inbox = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("inbox");

    if !inbox.exists() {
        return Ok(vec![]);
    }

    let mut files = Vec::new();
    for entry in std::fs::read_dir(&inbox).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        if entry.file_type().is_ok_and(|ft| ft.is_file()) {
            files.push(entry.file_name().to_string_lossy().to_string());
        }
    }
    Ok(files)
}

#[tauri::command]
fn list_export_files(cabinet_id: String, app_handle: tauri::AppHandle) -> Result<Vec<String>, String> {
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let exports = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("exports");

    if !exports.exists() {
        return Ok(vec![]);
    }

    let mut files = Vec::new();
    for entry in std::fs::read_dir(&exports).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        if entry.file_type().is_ok_and(|ft| ft.is_file()) {
            files.push(entry.file_name().to_string_lossy().to_string());
        }
    }
    Ok(files)
}

#[tauri::command]
fn copy_to_inbox(cabinet_id: String, file_paths: Vec<String>, app_handle: tauri::AppHandle) -> Result<Vec<String>, String> {
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let inbox = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("inbox");

    std::fs::create_dir_all(&inbox).map_err(|e| e.to_string())?;

    let mut copied = Vec::new();
    for src in &file_paths {
        let src_path = std::path::Path::new(src);
        if let Some(name) = src_path.file_name() {
            let dest = inbox.join(name);
            if std::fs::copy(src_path, &dest).is_ok() {
                copied.push(name.to_string_lossy().to_string());
            }
        }
    }
    Ok(copied)
}

#[tauri::command]
fn get_export_file_path(cabinet_id: String, filename: String, app_handle: tauri::AppHandle) -> Result<String, String> {
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let file_path = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("exports")
        .join(&filename);

    if !file_path.exists() {
        return Err(format!("File not found: {}", filename));
    }

    Ok(file_path.to_string_lossy().to_string())
}

#[tauri::command]
fn add_url_to_inbox(cabinet_id: String, url: String, app_handle: tauri::AppHandle) -> Result<String, String> {
    // Validate URL
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return Err("Invalid URL: must start with http:// or https://".to_string());
    }
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let inbox = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("inbox");

    std::fs::create_dir_all(&inbox).map_err(|e| e.to_string())?;

    // Extract domain for filename
    let domain = url
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .split('/')
        .next()
        .unwrap_or("link")
        .replace("www.", "");

    // UUID for uniqueness (avoids collision risk of short hashes)
    let uid_full = uuid::Uuid::new_v4().to_string();
    let unique_id = &uid_full[..8];

    let filename = format!("{}_{}.url", domain, unique_id);
    let content = format!("[InternetShortcut]\nURL={}\n", url);

    let dest = inbox.join(&filename);
    std::fs::write(&dest, content).map_err(|e| e.to_string())?;

    Ok(filename)
}

#[tauri::command]
fn delete_inbox_file(cabinet_id: String, filename: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    // Path traversal protection
    if filename.contains("..") || filename.contains('/') || filename.contains('\\') {
        return Err("Invalid filename".to_string());
    }
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let file_path = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("inbox")
        .join(&filename);

    if !file_path.exists() {
        return Err(format!("File not found: {}", filename));
    }

    std::fs::remove_file(&file_path).map_err(|e| e.to_string())
}

#[tauri::command]
fn cancel_claude(
    cabinet_id: String,
    state: tauri::State<'_, Arc<AppState>>,
    #[allow(unused_variables)] app_handle: tauri::AppHandle,
) -> Result<(), String> {
    // 🔴 В тонкой поставке процессов модели на машине пользователя нет вовсе,
    // поэтому карта процессов ниже всегда пуста и отмена возвращала отказ ВСЕГДА —
    // кнопка «Остановить» была мнимой. Теперь отмена доходит ДО СЕРВЕРА: контракт
    // v1 её умеет, и работа действительно прекращается, а не продолжает жечь окно
    // подписки и держать место.
    #[cfg(feature = "thin")]
    if commands::gateway_executor::request_cancel(&app_handle, &cabinet_id) {
        info!("Облачное задание остановлено по кнопке [{cabinet_id}]");
        let _ = app_handle.emit(
            &format!("claude-stream-{cabinet_id}"),
            serde_json::json!({
                "type": "system",
                "subtype": "cloud_wait_cancelled",
                "message": "Работа остановлена на сервере."
            })
            .to_string(),
        );
        return Ok(());
    }

    let pid = state.active_pids.lock().unwrap_or_else(|e| e.into_inner()).get(&cabinet_id).copied();

    if let Some(pid) = pid {
        info!("Killing Claude process PID={pid} for cabinet={cabinet_id}");
        #[cfg(windows)]
        std::process::Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .spawn()
            .map_err(|e| e.to_string())?;
        #[cfg(not(windows))]
        std::process::Command::new("kill")
            .args(["-9", &pid.to_string()])
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(())
    } else {
        Err("No active Claude process".to_string())
    }
}

#[tauri::command]
fn show_inbox_in_folder(cabinet_id: String, filename: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    if filename.contains("..") || filename.contains('/') || filename.contains('\\') {
        return Err("Invalid filename".to_string());
    }
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let file_path = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("inbox")
        .join(&filename);

    if !file_path.exists() {
        return Err(format!("Файл не найден: {}", filename));
    }

    info!("Show inbox in folder: {}", file_path.display());
    // Open parent folder and select the file
    let parent = file_path.parent().unwrap_or(std::path::Path::new("."));
    std::process::Command::new("explorer")
        .arg(parent)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn get_cabinet_commands(cabinet_id: String, state: tauri::State<'_, Arc<AppState>>, app_handle: tauri::AppHandle) -> Vec<cabinet::CabinetCommand> {
    let packs_ok = state.content_packs_verified.load(Ordering::Acquire);
    match app_handle.path().app_local_data_dir() {
        Ok(dir) if packs_ok => cabinet::get_commands_dynamic(&dir, &cabinet_id),
        _ => cabinet::get_commands_for_cabinet(&cabinet_id),
    }
}

#[tauri::command]
fn open_export_file(
    cabinet_id: String,
    filename: String,
    app_handle: tauri::AppHandle,
) -> Result<(), String> {
    // Path traversal protection
    if filename.contains("..") || filename.contains('/') || filename.contains('\\') {
        return Err("Invalid filename".to_string());
    }
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let file_path = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("exports")
        .join(&filename);

    if !file_path.exists() {
        return Err(format!("Файл не найден: {}", filename));
    }

    let path_str = file_path.to_string_lossy().to_string();
    info!("Opening export file: {path_str}");
    tauri_plugin_opener::open_path(&path_str, None::<&str>).map_err(|e| e.to_string())
}

#[tauri::command]
fn show_export_in_folder(cabinet_id: String, filename: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    if filename.contains("..") || filename.contains('/') || filename.contains('\\') {
        return Err("Invalid filename".to_string());
    }
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let file_path = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("exports")
        .join(&filename);

    if !file_path.exists() {
        return Err(format!("Файл не найден: {}", filename));
    }

    info!("Show in folder: {}", file_path.display());
    // Use explorer.exe directly (not via cmd /C) to handle Cyrillic paths correctly
    std::process::Command::new("explorer")
        .arg("/select,")
        .arg(&file_path)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn delete_export_file(cabinet_id: String, filename: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    if filename.contains("..") || filename.contains('/') || filename.contains('\\') {
        return Err("Invalid filename".to_string());
    }
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let file_path = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("exports")
        .join(&filename);

    if !file_path.exists() {
        return Err(format!("Файл не найден: {}", filename));
    }

    info!("Deleting export file: {}", file_path.display());
    std::fs::remove_file(&file_path).map_err(|e| e.to_string())
}

#[tauri::command]
fn save_chat_message(
    cabinet_id: String,
    role: String,
    content: String,
    ts: f64,
    is_auto_continue: Option<bool>,
    is_quick_reply: Option<bool>,
) -> Result<(), String> {
    session::history::save_message(
        &cabinet_id,
        session::history::ChatHistoryMessage { role, content, ts, is_auto_continue, is_quick_reply },
    )
    .map_err(|e| e.to_string())
}

#[tauri::command]
fn load_chat_history(cabinet_id: String) -> Result<Vec<session::history::ChatHistoryMessage>, String> {
    session::history::load_history(&cabinet_id).map_err(|e| e.to_string())
}

#[tauri::command]
fn clear_chat_history(cabinet_id: String) -> Result<(), String> {
    session::history::clear_history(&cabinet_id).map_err(|e| e.to_string())
}

/// Каталоги workspace, которые чистятся при каждом запуске приложения (clean start).
/// ТОЛЬКО inbox: это исходники одного прогона, им незачем всплывать в следующем запуске.
/// "exports" здесь БЫТЬ НЕ ДОЛЖНО — это выдача клиента (готовые документы на его Рабочем
/// столе), результат человеческой работы, а не временный мусор сессии (CPD-69: тихо
/// стирались файлы клиента мимо корзины при каждом старте).
const WORKSPACE_DIRS_CLEARED_ON_START: &[&str] = &["inbox"];

/// Удаляет все файлы из перечисленных подкаталогов workspace. Возвращает число удалённых
/// файлов. Без AppHandle — чтобы поведение можно было проверить тестом на временном каталоге.
fn clear_workspace_dirs(workspace: &std::path::Path, dir_names: &[&str]) -> usize {
    let mut removed = 0;
    for dir_name in dir_names {
        let dir = workspace.join(dir_name);
        if dir.exists() {
            if let Ok(entries) = std::fs::read_dir(&dir) {
                for entry in entries.flatten() {
                    if std::fs::remove_file(entry.path()).is_ok() {
                        removed += 1;
                    }
                }
            }
        }
    }
    removed
}

/// Clear inbox files in the persistent workspace (clean start).
/// Files on Desktop are removed from the UI - user can re-add them.
/// Exports (client deliverables) are deliberately never touched here - see
/// WORKSPACE_DIRS_CLEARED_ON_START.
#[tauri::command]
fn clear_workspace_files(cabinet_id: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let workspace = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?;

    let removed = clear_workspace_dirs(&workspace, WORKSPACE_DIRS_CLEARED_ON_START);
    info!("Inbox cleared [{cabinet_id}]: {removed} file(s); exports (client deliverables) left untouched");
    Ok(())
}

/// Preprocess a PPTX file: extract text + chart data → slides.json + styles.json.
/// Returns JSON with paths to the generated files.
#[tauri::command]
fn pptx_preprocess(
    cabinet_id: String,
    filename: String,
    state: tauri::State<'_, Arc<AppState>>,
) -> Result<String, String> {
    let work_dir = state.session_manager
        .get_work_dir(&cabinet_id)
        .ok_or("Cabinet session not open")?;

    let pptx_path = work_dir.join("inbox").join(&filename);
    if !pptx_path.exists() {
        return Err(format!("PPTX file not found: {}", filename));
    }

    let output_dir = work_dir.join("preprocessed");
    let slides_json = commands::pptx_processor::preprocess(&pptx_path, &output_dir)
        .map_err(|e| e.to_string())?;

    // Read slides.json content to return to frontend
    let content = std::fs::read_to_string(&slides_json)
        .map_err(|e| format!("Failed to read slides.json: {e}"))?;

    Ok(content)
}

/// Post-process Claude response: inject notes into PPTX + generate DOCX.
/// Takes the raw markdown response, parses slide sections, writes outputs.
#[tauri::command]
fn pptx_postprocess(
    cabinet_id: String,
    filename: String,
    response_markdown: String,
    state: tauri::State<'_, Arc<AppState>>,
) -> Result<String, String> {
    let work_dir = state.session_manager
        .get_work_dir(&cabinet_id)
        .ok_or("Cabinet session not open")?;

    let pptx_path = work_dir.join("inbox").join(&filename);
    if !pptx_path.exists() {
        return Err(format!("PPTX file not found: {}", filename));
    }

    // Parse response into per-slide notes
    let notes = commands::pptx_processor::parse_response_to_notes(&response_markdown);
    if notes.is_empty() {
        return Err("No slide sections found in response (expected ## Слайд N: ...)".to_string());
    }

    let preprocessed_dir = work_dir.join("preprocessed");
    let exports_dir = work_dir.join("exports");
    std::fs::create_dir_all(&exports_dir).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&preprocessed_dir).map_err(|e| e.to_string())?;

    // Write notes.json for the pipeline
    let notes_json_path = preprocessed_dir.join("notes.json");
    let notes_json_str = serde_json::to_string_pretty(&notes).map_err(|e| e.to_string())?;
    std::fs::write(&notes_json_path, &notes_json_str).map_err(|e| e.to_string())?;

    let stem = std::path::Path::new(&filename)
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "output".to_string());

    let commented_pptx = exports_dir.join(format!("{}_commented.pptx", stem));
    let commentary_docx = exports_dir.join(format!("{}_commentary.docx", stem));
    let styles_json = preprocessed_dir.join("styles.json");

    let mut results = Vec::new();

    // Inject notes into PPTX
    match commands::pptx_processor::inject_notes(&pptx_path, &notes_json_path, &commented_pptx) {
        Ok(_) => results.push(format!("PPTX: {}", commented_pptx.display())),
        Err(e) => log::warn!("inject_notes failed: {e}"),
    }

    // Generate DOCX
    match commands::pptx_processor::generate_docx(&pptx_path, &notes_json_path, &styles_json, &commentary_docx) {
        Ok(_) => results.push(format!("DOCX: {}", commentary_docx.display())),
        Err(e) => log::warn!("generate_docx failed: {e}"),
    }

    Ok(serde_json::json!({
        "notes_count": notes.len(),
        "outputs": results,
    }).to_string())
}

#[tauri::command]
fn open_help(cabinet_id: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    // Sanitize: защита от path traversal через имя
    if !cabinet_id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return Err("Invalid help page id".to_string());
    }

    // 1. Try content pack help first
    if let Ok(local_data_dir) = app_handle.path().app_local_data_dir() {
        if let Some(path) = content_pack::help_file_path(&local_data_dir, &cabinet_id) {
            let path_str = path.to_string_lossy().to_string();
            return tauri_plugin_opener::open_path(&path_str, None::<&str>)
                .map_err(|e| e.to_string());
        }
    }

    // 2. Bundled resource (prod) - проверяем обе папки
    let filename = format!("{}.html", cabinet_id);
    if let Ok(res_dir) = app_handle.path().resource_dir() {
        if let Some(path) = ["help-econometrica", "help"]
            .iter()
            .map(|d| res_dir.join(d).join(&filename))
            .find(|p| p.exists())
        {
            return tauri_plugin_opener::open_path(path.to_string_lossy().to_string(), None::<&str>)
                .map_err(|e| e.to_string());
        }
    }

    // 3. Dev fallback - resource_dir в dev-режиме указывает на target/debug,
    // где help-econometrica/ может не быть. Читаем напрямую из src-tauri/.
    let dev_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("help-econometrica")
        .join(&filename);
    if dev_path.exists() {
        return tauri_plugin_opener::open_path(dev_path.to_string_lossy().to_string(), None::<&str>)
            .map_err(|e| e.to_string());
    }

    Err(format!("Help page not found: {}.html", cabinet_id))
}

#[tauri::command]
fn open_user_guide(app_handle: tauri::AppHandle) -> Result<(), String> {
    let resource_path = app_handle
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("help-econometrica")
        .join("index.html");

    // In dev mode resource_dir points to target/debug, so fall back to src-tauri/help-econometrica/
    let path = if resource_path.exists() {
        resource_path
    } else {
        let dev_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("help-econometrica")
            .join("index.html");
        if dev_path.exists() {
            dev_path
        } else {
            return Err(format!("Файл инструкции не найден: {}", resource_path.display()));
        }
    };

    let path_str = path.to_string_lossy().to_string();
    tauri_plugin_opener::open_path(&path_str, None::<&str>).map_err(|e| e.to_string())
}

/// Сохранить PDF-справку (tools/build_help_pdf.py) в папку загрузок
/// пользователя. Econometrica доставляет справку БАНДЛОМ, не content-pack-
/// каналом (в отличие от Oracle/Legal - content-packs/help/ у продукта не
/// существует, content_pack::help_file_path всегда вернёт None), поэтому
/// здесь без приоритетной проверки content-pack - сразу resource_dir с dev-
/// фолбэком (тот же приём, что и open_user_guide() выше).
#[tauri::command]
fn save_help_pdf(app_handle: tauri::AppHandle) -> Result<String, String> {
    const PDF_NAME: &str = "econometrica-help.pdf";

    let resource_path = app_handle
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("help-econometrica")
        .join(PDF_NAME);

    // In dev mode resource_dir points to target/debug, so fall back to src-tauri/help-econometrica/
    let source_path = if resource_path.exists() {
        resource_path
    } else {
        let dev_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("help-econometrica")
            .join(PDF_NAME);
        if dev_path.exists() {
            dev_path
        } else {
            return Err(format!("PDF-справка не найдена: {}", resource_path.display()));
        }
    };

    let downloads_dir = app_handle.path().download_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&downloads_dir).map_err(|e| e.to_string())?;
    // Не перезатирать существующий файл (клиент мог аннотировать сохранённую
    // копию): при коллизии - суффикс (2), (3), …
    let base = "Aurora-AI-Econometrica-Справка";
    let mut dest_path = downloads_dir.join(format!("{base}.pdf"));
    let mut n = 2;
    while dest_path.exists() {
        dest_path = downloads_dir.join(format!("{base} ({n}).pdf"));
        n += 1;
    }
    std::fs::copy(&source_path, &dest_path).map_err(|e| e.to_string())?;

    Ok(dest_path.to_string_lossy().to_string())
}

// ============== Content Pack IPC ==============

#[tauri::command]
fn get_content_pack(pack_name: String, app_handle: tauri::AppHandle) -> Result<String, String> {
    // Validate filename
    if pack_name.contains("..") || pack_name.contains('/') || pack_name.contains('\\') {
        return Err(format!("Invalid pack name: {}", pack_name));
    }

    let local_data_dir = app_handle.path().app_local_data_dir().map_err(|e| e.to_string())?;
    match content_pack::load_pack_file(&local_data_dir, &pack_name) {
        Ok(data) => Ok(data),
        Err(_e) => {
            // Fallback: try bundled resources (content-packs shipped with installer)
            if let Ok(resource_dir) = app_handle.path().resource_dir() {
                // Tauri bundles "../content-packs/*" as "_up_/content-packs/*"
                let bundled = resource_dir.join("_up_").join("content-packs").join(&pack_name);
                if bundled.exists() {
                    info!("Loading content pack from bundled resources: {}", bundled.display());
                    return std::fs::read_to_string(&bundled).map_err(|e| e.to_string());
                }
                // Also try flat (in case resources path was changed)
                let flat = resource_dir.join(&pack_name);
                if flat.exists() {
                    info!("Loading content pack from bundled resources: {}", flat.display());
                    return std::fs::read_to_string(&flat).map_err(|e| e.to_string());
                }
            }

            // Dev fallback: try reading from project's content-packs/ directory
            #[cfg(debug_assertions)]
            {
                let dev_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .parent()
                    .unwrap_or(std::path::Path::new("."))
                    .join("content-packs")
                    .join(&pack_name);
                if dev_path.exists() {
                    info!("[DEV] Loading content pack from project: {}", dev_path.display());
                    return std::fs::read_to_string(&dev_path).map_err(|e| e.to_string());
                }
            }
            Err(_e.to_string())
        }
    }
}

// ── Dependency management ──────────────────────────────────

#[tauri::command]
fn check_pptx_dependencies() -> commands::pptx_processor::DependencyStatus {
    commands::pptx_processor::check_dependencies()
}

#[tauri::command]
fn install_pptx_dependencies(packages: Vec<String>) -> Result<String, String> {
    commands::pptx_processor::install_packages(&packages)
        .map(|n| format!("Установлено пакетов: {n}"))
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn verify_content_packs_status(app_handle: tauri::AppHandle) -> Result<bool, String> {
    let local_data_dir = app_handle.path().app_local_data_dir().map_err(|e| e.to_string())?;
    content_pack::verify_content_packs(&local_data_dir).map_err(|e| e.to_string())
}

// ============== File Preview ==============

#[tauri::command]
fn preview_export_file(cabinet_id: String, filename: String, app_handle: tauri::AppHandle) -> Result<(u64, String), String> {
    if filename.contains("..") || filename.contains('/') || filename.contains('\\') {
        return Err("Invalid filename".to_string());
    }
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let file_path = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?
        .join("exports")
        .join(&filename);

    if !file_path.exists() {
        return Err(format!("File not found: {}", filename));
    }

    let metadata = std::fs::metadata(&file_path).map_err(|e| e.to_string())?;
    let size = metadata.len();

    // Limit preview to 10MB to prevent OOM
    const MAX_PREVIEW_SIZE: u64 = 10 * 1024 * 1024;
    if size > MAX_PREVIEW_SIZE {
        return Ok((size, "[Файл слишком большой для предпросмотра]".to_string()));
    }

    // For binary formats, return only size
    let ext = filename.rsplit('.').next().unwrap_or("").to_lowercase();
    if matches!(ext.as_str(), "xlsx" | "docx" | "pdf" | "png" | "jpg" | "jpeg" | "gif" | "zip") {
        return Ok((size, String::new()));
    }

    // For text formats, return first 1000 chars
    let content = std::fs::read_to_string(&file_path).unwrap_or_default();
    let preview: String = content.chars().take(1000).collect();
    Ok((size, preview))
}

// ============== Cross-Cabinet File Sharing ==============

#[tauri::command]
fn copy_export_to_inbox(
    source_cabinet_id: String,
    filename: String,
    target_cabinet_id: String,
    app_handle: tauri::AppHandle,
) -> Result<(), String> {
    // Path traversal protection
    if filename.contains("..") || filename.contains('/') || filename.contains('\\') {
        return Err("Invalid filename".to_string());
    }
    cabinet::validate_cabinet_id(&source_cabinet_id)?;
    cabinet::validate_cabinet_id(&target_cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    let source_path = user_config::get_cabinet_workspace(&config_dir, &source_cabinet_id)?
        .join("exports")
        .join(&filename);

    if !source_path.exists() {
        return Err(format!("Source file not found: {}", filename));
    }

    let target_inbox = user_config::get_cabinet_workspace(&config_dir, &target_cabinet_id)?
        .join("inbox");

    std::fs::create_dir_all(&target_inbox).map_err(|e| e.to_string())?;
    let dest = target_inbox.join(&filename);
    std::fs::copy(&source_path, &dest).map_err(|e| e.to_string())?;

    info!("Copied {} from {} exports → {} inbox", filename, source_cabinet_id, target_cabinet_id);
    Ok(())
}

#[tauri::command]
async fn list_recent_exports(app_handle: tauri::AppHandle) -> Result<Vec<(String, String, String)>, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;

    // Filter cabinets by license (in dev mode - show all)
    let allowed_cabinets = get_allowed_cabinets(&config_dir).await;
    let all_cabinets = cabinet::get_cabinet_definitions();

    let mut exports: Vec<(String, String, String)> = Vec::new(); // (cabinet_id, filename, cabinet_name)

    for cab in &all_cabinets {
        if !allowed_cabinets.contains(&cab.id) {
            continue;
        }
        let workspace = user_config::get_cabinet_workspace(&config_dir, &cab.id);
        let exports_dir = match workspace {
            Ok(ws) => ws.join("exports"),
            Err(_) => continue,
        };
        if !exports_dir.exists() {
            continue;
        }
        if let Ok(entries) = std::fs::read_dir(&exports_dir) {
            for entry in entries.flatten() {
                if entry.file_type().is_ok_and(|ft| ft.is_file()) {
                    exports.push((
                        cab.id.clone(),
                        entry.file_name().to_string_lossy().to_string(),
                        cab.name.clone(),
                    ));
                }
            }
        }
    }

    // Collect modification times once, then sort (avoids O(n^2 log n) stat calls)
    let mut with_mtime: Vec<(std::time::SystemTime, String, String, String, std::path::PathBuf)> = exports
        .into_iter()
        .filter_map(|(cab_id, fname, cab_name)| {
            let ws = user_config::get_cabinet_workspace(&config_dir, &cab_id).ok()?;
            let path = ws.join("exports").join(&fname);
            let mtime = std::fs::metadata(&path).and_then(|m| m.modified()).unwrap_or(std::time::SystemTime::UNIX_EPOCH);
            Some((mtime, cab_id, fname, cab_name, path))
        })
        .collect();
    with_mtime.sort_by_key(|b| std::cmp::Reverse(b.0));
    with_mtime.truncate(20);
    let exports: Vec<(String, String, String)> = with_mtime.into_iter().map(|(_, id, f, n, _)| (id, f, n)).collect();

    Ok(exports)
}

// ============== Cabinet Path Configuration ==============

/// Get allowed cabinet IDs based on license. In dev mode returns all.
async fn get_allowed_cabinets(config_dir: &std::path::Path) -> Vec<String> {
    #[cfg(debug_assertions)]
    if std::env::var("AIAGENCY_DEV").is_ok() {
        return cabinet::get_cabinet_definitions().into_iter().map(|c| c.id).collect();
    }

    let app_version = env!("CARGO_PKG_VERSION");
    let online = online_auth::authorize(config_dir, app_version, "").await;

    if online.status == "ok" || online.status == "cached" {
        return online.cabinets;
    }

    // Fallback to offline license
    if let Ok(lic) = license::License::load(config_dir) {
        if let Ok(status) = lic.validate() {
            if status.valid {
                return status.cabinets;
            }
        }
    }

    // No valid license - return empty (show nothing)
    vec![]
}

#[tauri::command]
fn get_cabinet_path(cabinet_id: String, app_handle: tauri::AppHandle) -> Result<String, String> {
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let ws = user_config::get_cabinet_workspace(&config_dir, &cabinet_id)?;
    Ok(ws.to_string_lossy().to_string())
}

#[tauri::command]
fn set_cabinet_path(cabinet_id: String, path: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    cabinet::validate_cabinet_id(&cabinet_id)?;
    if path.is_empty() {
        return Err("Path cannot be empty".to_string());
    }
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let mut config = user_config::load(&config_dir);
    config.cabinet_paths.insert(cabinet_id, path);
    user_config::save(&config_dir, &config)
}

#[tauri::command]
fn reset_cabinet_path(cabinet_id: String, app_handle: tauri::AppHandle) -> Result<String, String> {
    cabinet::validate_cabinet_id(&cabinet_id)?;
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let mut config = user_config::load(&config_dir);
    config.cabinet_paths.remove(&cabinet_id);
    user_config::save(&config_dir, &config)?;
    let default = user_config::default_cabinet_workspace(&cabinet_id)?;
    Ok(default.to_string_lossy().to_string())
}

// ============== Model Settings Commands ==============

#[tauri::command]
fn get_model_settings(app_handle: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let config = user_config::load(&config_dir);
    Ok(serde_json::json!({
        "model": config.model.unwrap_or_else(|| "sonnet".to_string()),
        "effort": config.model_effort.unwrap_or_else(|| "medium".to_string()),
    }))
}

#[tauri::command]
fn set_model_settings(model: String, effort: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let mut config = user_config::load(&config_dir);
    config.model = if model == "sonnet" { None } else { Some(model) };
    config.model_effort = if effort == "medium" { None } else { Some(effort) };
    user_config::save(&config_dir, &config)
}

// ============== Cloud Processing Consent (облачная редакция) ==============

/// Статус согласия на облачную обработку для фронта: включена ли облачная редакция
/// и нужно ли показать блокирующий экран согласия.
#[tauri::command]
fn get_cloud_consent_status(app_handle: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    Ok(serde_json::json!({
        "cloud_advisors_enabled": claude::CLOUD_ADVISORS_ENABLED,
        "consent_required": user_config::cloud_consent_required(&config_dir),
        "terms_version": user_config::CLOUD_CONSENT_TERMS_VERSION,
        "local_only": user_config::local_only_enabled(&config_dir),
    }))
}

/// Зафиксировать согласие пользователя на облачную обработку (текущая версия условий).
/// Durable backend-persist — переживает очистку WebView2-кэша.
#[tauri::command]
fn accept_cloud_consent(app_handle: tauri::AppHandle) -> Result<(), String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let mut config = user_config::load(&config_dir);
    let accepted_at = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    config.cloud_consent = Some(user_config::CloudConsent {
        terms_version: user_config::CLOUD_CONSENT_TERMS_VERSION,
        accepted_at,
    });
    user_config::save(&config_dir, &config)
}

/// Отозвать согласие на облачную обработку. Graceful: MMM-анализ продолжает работать,
/// кабинеты-советники становятся недоступны (egress-гейт run_claude снова сработает)
/// до повторного согласия.
#[tauri::command]
fn withdraw_cloud_consent(app_handle: tauri::AppHandle) -> Result<(), String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let mut config = user_config::load(&config_dir);
    config.cloud_consent = None;
    user_config::save(&config_dir, &config)
}

/// Включить/выключить runtime-режим «только локально». Пишет `local_only` в
/// user_config; egress-гейт `run_claude` (ensure_not_local_only) читает его и
/// блокирует облачный ИИ, когда включено. Одна сборка, два режима.
#[tauri::command]
fn set_local_only(enabled: bool, app_handle: tauri::AppHandle) -> Result<(), String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let mut config = user_config::load(&config_dir);
    config.local_only = enabled;
    user_config::save(&config_dir, &config)
}

// ============== Режим исполнения советника (ADR-049) ==============
//
// 🔴 Отдельная ось от `local_only` выше. Тот отвечает «обращаться ли к облачному ИИ
// вообще» и может запретить обращение целиком; эти команды — «если обращаемся, чей
// Claude Code исполняет работу». Смешать их в одном переключателе значит предложить
// человеку выбирать между несравнимым.

/// Что действует сейчас и что доступно — для настроек и признака в рабочем экране.
#[tauri::command]
async fn get_execution_mode(
    app_handle: tauri::AppHandle,
) -> Result<commands::execution_mode::ModeState, String> {
    Ok(commands::execution_mode::state(&app_handle).await)
}

/// Явный выбор человека. Пустая строка возвращает к автоопределению.
#[tauri::command]
fn set_execution_mode(mode: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    let chosen = if mode.is_empty() {
        None
    } else {
        Some(
            commands::execution_mode::ExecutionMode::parse(&mode)
                .ok_or_else(|| format!("неизвестный режим исполнения: {mode}"))?,
        )
    };
    commands::execution_mode::set_explicit_choice(&app_handle, chosen)
}

/// Перепроверить локальный Claude Code сейчас: человек мог поставить его или войти,
/// не перезапуская программу.
#[tauri::command]
async fn probe_local_claude(
    app_handle: tauri::AppHandle,
) -> Result<commands::execution_mode::ModeState, String> {
    commands::execution_mode::forget_local_probe();
    Ok(commands::execution_mode::state(&app_handle).await)
}

// ============== Econometrica Projects Root ==============

/// Get current projects root path + default path for UI display.
#[tauri::command]
fn get_econometrica_projects_root(app_handle: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let config = user_config::load(&config_dir);
    let appdata = std::env::var("APPDATA").map_err(|_| "APPDATA not set".to_string())?;
    let identifier = env!("CARGO_PKG_NAME");
    let default_path = std::path::PathBuf::from(&appdata)
        .join(identifier)
        .join("projects");
    let current = config.econometrica_projects_root.clone()
        .unwrap_or_else(|| default_path.to_string_lossy().to_string());
    Ok(serde_json::json!({
        "current": current,
        "default": default_path.to_string_lossy(),
        "is_custom": config.econometrica_projects_root.is_some(),
    }))
}

/// Задать кастомную директорию для Econometrica-проектов.
/// Пустая строка = сбросить на дефолт. Существующие проекты НЕ переносятся -
/// они остаются в старой папке. Новый `projects_dir()` начнёт указывать на новую папку.
#[tauri::command]
fn set_econometrica_projects_root(path: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let mut config = user_config::load(&config_dir);
    let trimmed = path.trim().to_string();
    if trimmed.is_empty() {
        config.econometrica_projects_root = None;
    } else {
        // Проверка существования / попытка создать
        let p = std::path::PathBuf::from(&trimmed);
        std::fs::create_dir_all(&p)
            .map_err(|e| format!("Не удалось создать/проверить папку {trimmed}: {e}"))?;
        config.econometrica_projects_root = Some(trimmed);
    }
    user_config::save(&config_dir, &config)
}

/// Открыть текущую папку с проектами в проводнике.
#[tauri::command]
fn open_econometrica_projects_root(app_handle: tauri::AppHandle) -> Result<(), String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let config = user_config::load(&config_dir);
    let path = match config.econometrica_projects_root {
        Some(p) => std::path::PathBuf::from(p),
        None => {
            let appdata = std::env::var("APPDATA").map_err(|_| "APPDATA not set".to_string())?;
            let identifier = env!("CARGO_PKG_NAME");
            std::path::PathBuf::from(appdata).join(identifier).join("projects")
        }
    };
    let _ = std::fs::create_dir_all(&path);

    #[cfg(windows)]
    {
        std::process::Command::new("explorer")
            .arg(path.to_str().unwrap_or("."))
            .spawn()
            .map_err(|e| format!("Не удалось открыть папку: {e}"))?;
    }
    #[cfg(not(windows))]
    {
        std::process::Command::new("xdg-open")
            .arg(path.to_str().unwrap_or("."))
            .spawn()
            .map_err(|e| format!("Не удалось открыть папку: {e}"))?;
    }
    Ok(())
}

// ============== Metrics Commands ==============

#[tauri::command]
fn get_usage_metrics() -> Result<metrics::collector::UsageMetrics, String> {
    metrics::collector::get_metrics().map_err(|e| e.to_string())
}

#[tauri::command]
fn reset_metrics() -> Result<(), String> {
    metrics::collector::reset_metrics().map_err(|e| e.to_string())
}

#[tauri::command]
fn rate_response(
    cabinet_id: String,
    command_slug: Option<String>,
    rating: i8,
    response_time_secs: Option<f64>,
) -> Result<(), String> {
    let timestamp = chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string();
    metrics::ratings::rate_response(metrics::ratings::ResponseRating {
        cabinet_id,
        command_slug,
        timestamp,
        rating,
        response_time_secs,
    })
    .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_cabinet_ratings(cabinet_id: String) -> Result<metrics::ratings::CabinetRatingSummary, String> {
    metrics::ratings::get_cabinet_ratings(&cabinet_id).map_err(|e| e.to_string())
}

// ============== Vault Status ==============

#[tauri::command]
fn list_vault_status(app_handle: tauri::AppHandle) -> Result<Vec<(String, String, bool)>, String> {
    let data_dir = app_handle.path().app_data_dir().map_err(|e| e.to_string())?;
    let cabinets = cabinet::get_cabinet_definitions();
    let mut statuses = Vec::new();
    for cab in cabinets {
        let has_vault = vault::vault_exists(&cab.id, &data_dir);
        statuses.push((cab.id, cab.name, has_vault));
    }
    Ok(statuses)
}

// ============== Logs & Updates ==============

#[tauri::command]
fn export_logs(app_handle: &tauri::AppHandle) -> Result<String, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let log_dir = config_dir.join("logs");
    // Fallback: try %LOCALAPPDATA%/<identifier>/logs/
    if !log_dir.exists() {
        if let Ok(local_dir) = app_handle.path().app_local_data_dir() {
            let alt = local_dir.join("logs");
            if alt.exists() {
                return Ok(alt.to_string_lossy().to_string());
            }
        }
    }
    Ok(log_dir.to_string_lossy().to_string())
}

#[tauri::command]
fn open_logs_folder(app_handle: tauri::AppHandle) -> Result<(), String> {
    let path = export_logs(&app_handle)?;
    let log_path = std::path::Path::new(&path);
    if !log_path.exists() {
        let _ = std::fs::create_dir_all(log_path);
    }
    #[cfg(windows)]
    std::process::Command::new("explorer")
        .arg(&path)
        .spawn()
        .map_err(|e| e.to_string())?;
    #[cfg(not(windows))]
    std::process::Command::new("xdg-open")
        .arg(&path)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn export_diagnostics(app_handle: tauri::AppHandle) -> Result<String, String> {
    let config = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let data = app_handle.path().app_data_dir().map_err(|e| e.to_string())?;
    let local = app_handle.path().app_local_data_dir().map_err(|e| e.to_string())?;

    let report = commands::diagnostics::collect_report(&config, &data, &local);

    // Save to Desktop (Tauri resolver → USERPROFILE fallback → config dir)
    let desktop = app_handle.path().desktop_dir()
        .or_else(|_| std::env::var("USERPROFILE")
            .map(|p| std::path::PathBuf::from(p).join("Desktop"))
            .map_err(|e| tauri::Error::Anyhow(e.into())))
        .unwrap_or_else(|_| config.clone());

    let now = chrono::Local::now();
    let filename = format!("Aurora_Diagnostics_{}.txt", now.format("%Y-%m-%d_%H%M%S"));
    // CPD-70: секундная точность таймстемпа не спасает от коллизии при двух экспортах
    // диагностики подряд (например по просьбе поддержки) — повторный экспорт не должен
    // молча стереть предыдущий файл на Рабочем столе клиента.
    let filepath = commands::unique_export_path(&desktop.join(&filename));

    std::fs::write(&filepath, &report).map_err(|e| format!("Failed to write: {e}"))?;

    // Also save a copy to the logs folder (accessible via "Open Logs Folder").
    // Имя берём из итогового filepath (после возможного переименования выше), чтобы копия
    // в logs соответствовала копии на Desktop; отдельно прогоняем через unique_export_path,
    // т.к. коллизия в logs_dir не обязана совпадать с коллизией на Desktop.
    let logs_dir = export_logs(&app_handle).unwrap_or_default();
    if !logs_dir.is_empty() {
        let logs_path = std::path::Path::new(&logs_dir);
        let _ = std::fs::create_dir_all(logs_path);
        let logs_filename = filepath.file_name().unwrap_or_else(|| std::ffi::OsStr::new(&filename));
        let logs_copy_path = commands::unique_export_path(&logs_path.join(logs_filename));
        let _ = std::fs::write(&logs_copy_path, &report);
    }

    info!("Diagnostics exported: {}", filepath.display());
    metrics::audit::log_event("export_diagnostics", &filepath.to_string_lossy(), true);

    Ok(filepath.to_string_lossy().to_string())
}

#[tauri::command]
async fn check_update() -> Result<Option<updater::VersionInfo>, String> {
    let current = env!("CARGO_PKG_VERSION");
    updater::check_for_updates(current)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn check_server_update(app_min_version: String, update_url: Option<String>) -> Option<updater::VersionInfo> {
    let current = env!("CARGO_PKG_VERSION");
    updater::check_server_update(current, &app_min_version, update_url.as_deref())
}

#[tauri::command]
async fn download_update(app: tauri::AppHandle) -> Result<String, String> {
    // SEC-04: url и checksum из серверного манифеста, НЕ с фронта.
    let current = env!("CARGO_PKG_VERSION");
    let info = updater::check_for_updates(current).await.map_err(|e| e.to_string())?.ok_or_else(|| "Обновление недоступно".to_string())?;
    let path = updater::download_update(&info.download_url, &app).await.map_err(|e| e.to_string())?;
    updater::verify_checksum(&path, &info.checksum).map_err(|e| e.to_string())?;
    Ok(path.to_string_lossy().to_string())
}

#[tauri::command]
fn apply_update(installer_path: String) -> Result<(), String> {
    updater::apply_update(std::path::Path::new(&installer_path))
        .map_err(|e| e.to_string())
}

// ============== Frontend Externalization (Phase 3) ==============

/// Handle requests to the custom aurora:// protocol.
///
/// Serves files from the active external frontend directory in %LOCALAPPDATA%.
/// Falls back to the embedded fallback page if the directory is missing.
///
/// Security: rejects ".." path traversal and symlinks outside the frontend dir.
fn handle_aurora_protocol(
    app: &tauri::AppHandle,
    request: tauri::http::Request<Vec<u8>>,
) -> tauri::http::Response<Vec<u8>> {
    use tauri::http::Response;

    // aurora://localhost/some/path → "some/path"
    let uri = request.uri().to_string();
    let raw_path = uri
        .strip_prefix("aurora://localhost/")
        .or_else(|| uri.strip_prefix("aurora://localhost"))
        .unwrap_or("")
        .trim_start_matches('/');

    let path = if raw_path.is_empty() || raw_path == "/" { "index.html" } else { raw_path };

    // Block path traversal
    if path.contains("..") {
        return Response::builder()
            .status(403)
            .header("Content-Type", "text/plain")
            .body(b"Forbidden".to_vec())
            .unwrap_or_default();
    }

    let data_dir = match app.path().app_local_data_dir() {
        Ok(d) => d,
        Err(_) => return serve_aurora_fallback(),
    };

    let version_file = data_dir.join("current_frontend_version.txt");
    let version = match std::fs::read_to_string(&version_file) {
        Ok(v) => v.trim().to_string(),
        Err(_) => return serve_aurora_fallback(),
    };
    if version.is_empty() {
        return serve_aurora_fallback();
    }

    let frontend_dir = data_dir.join(format!("frontend-{}", version));
    let file_path = frontend_dir.join(path);

    // Symlink protection: resolved path must stay inside frontend_dir
    if let (Ok(canonical), Ok(canonical_dir)) = (file_path.canonicalize(), frontend_dir.canonicalize()) {
        if !canonical.starts_with(&canonical_dir) {
            return Response::builder()
                .status(403)
                .header("Content-Type", "text/plain")
                .body(b"Path outside frontend directory".to_vec())
                .unwrap_or_default();
        }
    }

    if !file_path.exists() {
        // SPA fallback: serve index.html for unknown routes (client-side routing)
        let index = frontend_dir.join("index.html");
        if index.exists() {
            if let Ok(content) = std::fs::read(&index) {
                return Response::builder()
                    .status(200)
                    .header("Content-Type", "text/html; charset=utf-8")
                    .body(content)
                    .unwrap_or_default();
            }
        }
        return Response::builder()
            .status(404)
            .header("Content-Type", "text/plain")
            .body(format!("Not found: {path}").into_bytes())
            .unwrap_or_default();
    }

    let content = match std::fs::read(&file_path) {
        Ok(c) => c,
        Err(e) => return Response::builder()
            .status(500)
            .header("Content-Type", "text/plain")
            .body(format!("Read error: {e}").into_bytes())
            .unwrap_or_default(),
    };

    let mime = match path.rsplit('.').next() {
        Some("html") => "text/html; charset=utf-8",
        Some("js") | Some("mjs") => "application/javascript",
        Some("css") => "text/css",
        Some("json") => "application/json",
        Some("png") => "image/png",
        Some("jpg") | Some("jpeg") => "image/jpeg",
        Some("svg") => "image/svg+xml",
        Some("ico") => "image/x-icon",
        Some("woff2") => "font/woff2",
        Some("woff") => "font/woff",
        Some("ttf") => "font/ttf",
        _ => "application/octet-stream",
    };

    Response::builder()
        .status(200)
        .header("Content-Type", mime)
        .body(content)
        .unwrap_or_default()
}

/// Serve the embedded fallback HTML (included at compile time).
fn serve_aurora_fallback() -> tauri::http::Response<Vec<u8>> {
    let html = include_str!("fallback.html");
    tauri::http::Response::builder()
        .status(200)
        .header("Content-Type", "text/html; charset=utf-8")
        .body(html.as_bytes().to_vec())
        .unwrap_or_default()
}

/// Returns true if a valid (signature-verified) external frontend exists in app_local_data_dir.
fn has_verified_external_frontend(data_dir: &std::path::Path) -> bool {
    let version_file = data_dir.join("current_frontend_version.txt");
    let version = match std::fs::read_to_string(&version_file) {
        Ok(v) => v.trim().to_string(),
        Err(_) => return false,
    };
    if version.is_empty() { return false; }

    let frontend_dir = data_dir.join(format!("frontend-{}", version));
    match crypto::content_sig::verify_manifest(&frontend_dir) {
        Ok(manifest) => {
            // Батч 0 (2026-07-13): манифест может требовать core-версию новее текущего
            // .exe (min_core_version) - без этой проверки старый внешний OTA-бандл
            // навсегда перекрывал бы embedded frontend после апдейта .exe с новыми
            // промптами/JS (OTA-канал не достаёт до кода, вшитого в exe). Используем
            // готовое semver-сравнение из updater (rc-aware, покрыто тестами).
            let core_version = env!("CARGO_PKG_VERSION");
            if updater::is_newer(&manifest.min_core_version, core_version) {
                warn!(
                    "External frontend {} requires core >= {} but running {} - using embedded",
                    version, manifest.min_core_version, core_version
                );
                return false;
            }
            info!("External frontend verified: {}", version);
            true
        }
        Err(e) => {
            warn!("External frontend verification failed (using embedded): {e}");
            false
        }
    }
}

/// Delete old frontend-vN directories (all versions older than the current one).
/// Called at startup to reclaim disk space.
fn cleanup_old_frontend_dirs(data_dir: &std::path::Path) {
    let version_file = data_dir.join("current_frontend_version.txt");
    let current = match std::fs::read_to_string(&version_file) {
        Ok(v) => v.trim().to_string(),
        Err(_) => return,
    };
    let current_n = current.trim_start_matches('v').parse::<u32>().unwrap_or(0);
    if current_n == 0 { return; }

    if let Ok(entries) = std::fs::read_dir(data_dir) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if let Some(ver_str) = name.strip_prefix("frontend-v") {
                // Also skip staging dirs (contain a '-')
                if ver_str.contains('-') { continue; }
                if let Ok(n) = ver_str.parse::<u32>() {
                    if n < current_n {
                        match std::fs::remove_dir_all(entry.path()) {
                            Ok(_) => info!("Removed old frontend dir: {}", name),
                            Err(e) => warn!("Failed to remove old frontend dir {}: {e}", name),
                        }
                    }
                }
            }
        }
    }
}

/// IPC command: download and install the latest frontend bundle from the server.
/// Called from the fallback page when external frontend is missing or corrupted.
#[tauri::command]
async fn repair_frontend(app_handle: tauri::AppHandle) -> Result<(), String> {
    let data_dir = app_handle.path().app_local_data_dir().map_err(|e| e.to_string())?;
    let product = online_auth::detect_product();
    content_updater::download_frontend_bundle(&data_dir, product, &app_handle)
        .await
        .map_err(|e| e.to_string())
}

// ============== App Entry ==============

/// Show a native Windows MessageBox. Works even when WebView2 is broken.
#[cfg(windows)]
fn show_error_dialog(title: &str, message: &str) {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr;

    let wide_title: Vec<u16> = OsStr::new(title).encode_wide().chain(Some(0)).collect();
    let wide_msg: Vec<u16> = OsStr::new(message).encode_wide().chain(Some(0)).collect();

    #[link(name = "user32")]
    extern "system" {
        fn MessageBoxW(hwnd: *mut std::ffi::c_void, text: *const u16, caption: *const u16, utype: u32) -> i32;
    }

    const MB_OK: u32 = 0x0000_0000;
    const MB_ICONERROR: u32 = 0x0000_0010;

    unsafe {
        MessageBoxW(ptr::null_mut(), wide_msg.as_ptr(), wide_title.as_ptr(), MB_OK | MB_ICONERROR);
    }
}

#[cfg(not(windows))]
fn show_error_dialog(_title: &str, message: &str) {
    eprintln!("{message}");
}

// ============== Product Type ==============

#[tauri::command]
fn ensure_default_brand(app_handle: tauri::AppHandle) -> Result<(), String> {
    brand::ensure_default_brand(&app_handle)
}

#[tauri::command]
fn get_product_type() -> String {
    online_auth::detect_product().to_string()
}

// ============== Workflow Execution Engine ==============

#[tauri::command]
async fn workflow_execute(
    brand_id: String,
    workflow_id: String,
    state: tauri::State<'_, Arc<AppState>>,
    app_handle: tauri::AppHandle,
) -> Result<String, String> {
    // Load workflow
    let wf = commands::campaign::campaign_get(brand_id.clone(), workflow_id.clone())?;
    let steps = wf.workflow_steps.ok_or("Not a workflow (no workflow_steps)")?;

    let exec_id = format!("exec-{}", chrono::Local::now().format("%Y%m%d-%H%M%S"));
    info!("Workflow execution starting: {exec_id} for {workflow_id}");

    // Mark as running
    {
        let mut execs = state.workflow_executions.lock().unwrap();
        execs.insert(exec_id.clone(), "running".into());
    }

    let exec_id_clone = exec_id.clone();
    let state_inner = state.inner().clone();
    let app = app_handle.clone();

    // Spawn execution in background
    tokio::spawn(async move {
        let result = execute_workflow_steps(
            steps,
            state_inner.clone(),
            app.clone(),
            exec_id_clone.clone(),
            None, // No context chain for standalone workflows
        )
        .await;

        let final_status = match &result {
            Ok(_) => "completed",
            Err(_) => "failed",
        };

        // Update status
        {
            let mut execs = state_inner.workflow_executions.lock().unwrap();
            execs.insert(exec_id_clone.clone(), final_status.into());
        }

        // Notify frontend
        let _ = app.emit(
            &format!("workflow-execution-{exec_id_clone}"),
            serde_json::json!({
                "type": "execution-status",
                "status": final_status,
                "error": result.err()
            })
            .to_string(),
        );

        info!("Workflow execution {exec_id_clone}: {final_status}");
    });

    Ok(exec_id)
}

#[tauri::command]
async fn workflow_execute_with_brief(
    brand_id: String,
    workflow_id: String,
    state: tauri::State<'_, Arc<AppState>>,
    app_handle: tauri::AppHandle,
) -> Result<String, String> {
    use commands::campaign::{ContextChain, campaigns_dir};

    let mut wf = commands::campaign::campaign_get(brand_id.clone(), workflow_id.clone())?;
    let steps = wf.workflow_steps.clone().ok_or("Not a workflow")?;

    let exec_id = format!("exec-{}", chrono::Local::now().format("%Y%m%d-%H%M%S"));
    info!("Pipeline execution starting: {exec_id} for {workflow_id}");

    // Update campaign status
    wf.status = "running".into();
    wf.started_at = Some(chrono::Local::now().to_rfc3339());
    wf.execution_id = Some(exec_id.clone());
    let _ = commands::campaign::workflow_save(brand_id.clone(), wf.clone());

    {
        let mut execs = state.workflow_executions.lock().unwrap();
        execs.insert(exec_id.clone(), "running".into());
    }

    // Build context chain
    let brand_name = brand_id.clone(); // TODO: resolve from brand store
    let campaign_dir = campaigns_dir(if brand_id.is_empty() { "default" } else { &brand_id })
        .join(&workflow_id);
    let _ = std::fs::create_dir_all(&campaign_dir);

    let context_chain = Arc::new(Mutex::new(ContextChain {
        brief_text: wf.brief_text.clone(),
        brand_name,
        step_summaries: Vec::new(),
        campaign_dir: campaign_dir.clone(),
    }));

    // Copy brief files to first step inbox (will be handled during execution)
    let _brief_files_dir = campaign_dir.join("brief-files");

    let exec_id_clone = exec_id.clone();
    let state_inner = state.inner().clone();
    let app = app_handle.clone();
    let wf_id = workflow_id.clone();
    let b_id = brand_id.clone();

    tokio::spawn(async move {
        let result = execute_workflow_steps(
            steps,
            state_inner.clone(),
            app.clone(),
            exec_id_clone.clone(),
            Some(context_chain),
        )
        .await;

        let final_status = match &result {
            Ok(_) => "completed",
            Err(_) => "failed",
        };

        {
            let mut execs = state_inner.workflow_executions.lock().unwrap();
            execs.insert(exec_id_clone.clone(), final_status.into());
        }

        // Update campaign status on disk
        if let Ok(mut campaign) = commands::campaign::campaign_get(b_id.clone(), wf_id.clone()) {
            campaign.status = final_status.into();
            campaign.completed_at = Some(chrono::Local::now().to_rfc3339());
            let _ = commands::campaign::workflow_save(b_id, campaign);
        }

        let _ = app.emit(
            &format!("workflow-execution-{exec_id_clone}"),
            serde_json::json!({
                "type": "execution-status",
                "status": final_status,
                "error": result.err()
            })
            .to_string(),
        );

        info!("Pipeline execution {exec_id_clone}: {final_status}");
    });

    Ok(exec_id)
}

fn execute_workflow_steps(
    steps: Vec<commands::campaign::WorkflowStep>,
    state: Arc<AppState>,
    app: tauri::AppHandle,
    exec_id: String,
    context_chain: Option<Arc<Mutex<commands::campaign::ContextChain>>>,
) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<(), String>> + Send>> {
    Box::pin(async move {
        for step in steps.iter() {
            // Check if cancelled
            {
                let execs = state.workflow_executions.lock().unwrap();
                if execs.get(&exec_id).map(|s| s.as_str()) == Some("cancelled") {
                    return Err("Workflow cancelled".into());
                }
            }

            match step {
                commands::campaign::WorkflowStep::Single {
                    ref id,
                    ref cabinet_id,
                    ref command,
                    ref label,
                    ..
                } => {
                    emit_wf_status(&app, &exec_id, id, "running", None);
                    info!("Workflow step [{id}]: opening {cabinet_id}");

                    // Open cabinet session if not already open
                    if state.session_manager.get_work_dir(cabinet_id).is_none() {
                        #[cfg(debug_assertions)]
                        if std::env::var("AIAGENCY_DEV").is_ok() {
                            let dev_root = std::env::var("AIAGENCY_DEV_CABINETS")
                                .unwrap_or_else(|_| "New_AI_Agency".to_string());
                            let folder = commands::cabinet::cabinet_folder_name(cabinet_id);
                            let source = std::path::PathBuf::from(&dev_root).join(folder);
                            let workspace =
                                user_config::default_cabinet_workspace(cabinet_id)
                                    .map_err(|e| e.to_string())?;
                            if let Err(e) = state
                                .session_manager
                                .open_dev_session(cabinet_id, &source, &workspace)
                            {
                                let err = e.to_string();
                                emit_wf_status(&app, &exec_id, id, "error", Some(&err));
                                return Err(err);
                            }
                        }

                        // Prod mode: open via vault
                        #[cfg(not(debug_assertions))]
                        {
                            let config_dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
                            let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
                            let vault_data = vault::read_vault(cabinet_id, &data_dir).map_err(|e| e.to_string())?;
                            let key = match content_updater::derive_local_key(&config_dir) {
                                Ok(local_key) => {
                                    match crate::crypto::aes::decrypt(&local_key, &vault_data) {
                                        Ok(_) => local_key,
                                        Err(_) => {
                                            let fp = crate::crypto::fingerprint::get_machine_fingerprint().map_err(|e| e.to_string())?;
                                            let lic = license::License::load(&config_dir).map_err(|e| e.to_string())?;
                                            let salt = lic.salt_bytes().map_err(|e| e.to_string())?;
                                            crate::crypto::hkdf::derive_key(&fp, &salt).map_err(|e| e.to_string())?
                                        }
                                    }
                                }
                                Err(_) => {
                                    let fp = crate::crypto::fingerprint::get_machine_fingerprint().map_err(|e| e.to_string())?;
                                    let lic = license::License::load(&config_dir).map_err(|e| e.to_string())?;
                                    let salt = lic.salt_bytes().map_err(|e| e.to_string())?;
                                    crate::crypto::hkdf::derive_key(&fp, &salt).map_err(|e| e.to_string())?
                                }
                            };
                            let workspace = user_config::get_cabinet_workspace(&config_dir, cabinet_id)?;
                            if let Err(e) = state.session_manager.open_session(cabinet_id, &vault_data, &key, &workspace) {
                                let err = e.to_string();
                                emit_wf_status(&app, &exec_id, id, "error", Some(&err));
                                return Err(err);
                            }
                        }
                    }

                    // Build message (with optional pipeline context prefix)
                    let base_msg = command
                        .as_deref()
                        .unwrap_or("Выполни задачу согласно контексту в inbox")
                        .to_string();
                    let msg = if let Some(ref chain) = context_chain {
                        let chain_lock = chain.lock().unwrap();
                        format!("{}{}", chain_lock.build_message_prefix(), base_msg)
                    } else {
                        base_msg
                    };

                    // Pipeline: forward previous step exports to current inbox
                    if let Some(ref chain) = context_chain {
                        if let Some(work_dir) = state.session_manager.get_work_dir(cabinet_id) {
                            let chain_lock = chain.lock().unwrap();
                            if let Some((_prev_label, _)) = chain_lock.step_summaries.last().map(|(l, s)| {
                                // Find step_id from label (simplified: use last persisted step dir)
                                (l.clone(), s.clone())
                            }) {
                                // Find last persisted step's exports
                                let steps_dir = chain_lock.campaign_dir.join("steps");
                                if steps_dir.exists() {
                                    if let Ok(entries) = std::fs::read_dir(&steps_dir) {
                                        if let Some(last) = entries.filter_map(|e| e.ok()).last() {
                                            let fwd = commands::campaign::forward_exports_to_inbox(&last.path(), &work_dir);
                                            if !fwd.is_empty() {
                                                info!("Forwarded {} files to {}", fwd.len(), cabinet_id);
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Sync inbox, run Claude, sync exports
                    if let Err(e) = state.session_manager.sync_inbox(cabinet_id) {
                        let err = e.to_string();
                        emit_wf_status(&app, &exec_id, id, "error", Some(&err));
                        return Err(err);
                    }

                    let work_dir = match state.session_manager.get_work_dir(cabinet_id) {
                        Some(d) => d,
                        None => {
                            emit_wf_status(
                                &app,
                                &exec_id,
                                id,
                                "error",
                                Some("Session not open"),
                            );
                            return Err("Session not open".into());
                        }
                    };

                    // Write brand context before Claude run
                    brand::write_brand_context(&work_dir, &app).await;

                    // run_claude: resume_session_id = should_continue session id
                    let resume = state.session_manager.get_claude_session_id(cabinet_id);
                    let wf_model = app.path().app_config_dir().ok()
                        .map(|d| user_config::load(&d).model)
                        .unwrap_or(None);
                    let claude_result = claude::run_claude(
                        &work_dir,
                        &msg,
                        app.clone(),
                        cabinet_id.clone(),
                        resume,
                        state.active_pids.clone(),
                        false,
                        wf_model,
                    )
                    .await;
                    if let Err(e) = claude_result {
                        let err = e.to_string();
                        emit_wf_status(&app, &exec_id, id, "error", Some(&err));
                        return Err(err);
                    }

                    // Находка внешнего аудита: отказ по отдельным файлам отбрасывался молча.
                    match state.session_manager.sync_exports(cabinet_id) {
                        Ok(blocked) if !blocked.is_empty() => warn!(
                            "Не обновлены в папке результатов [{cabinet_id}]: {}",
                            blocked.join(", ")
                        ),
                        Ok(_) => {}
                        Err(e) => warn!("Синхронизация выгрузок не прошла [{cabinet_id}]: {e}"),
                    }
                    let _ = state.session_manager.auto_route_artifacts(cabinet_id);

                    // Pipeline: persist exports + summarize + forward to next step
                    if let Some(ref chain) = context_chain {
                        if let Some(work_dir) = state.session_manager.get_work_dir(cabinet_id) {
                            let exports_dir = work_dir.join("exports");
                            let mut chain_lock = chain.lock().unwrap();
                            let persisted = commands::campaign::persist_step_exports(
                                &chain_lock.campaign_dir, id, &exports_dir,
                            );
                            // CPD-81: раньше отказ копирования тонул в `let _ =`, а следующей
                            // строкой close_session() стирал рабочий каталог — единственная
                            // копия файла терялась без следа, шаг рапортовал "done". Здесь нет
                            // состояния emit_wf_status под частичный неуспех шага (есть только
                            // running/error/done — ни одно не подходит для «шаг выполнен, но
                            // часть выгрузок не сохранена»), поэтому минимум — громкий лог
                            // ДО удаления рабочего каталога, чтобы потеря была видна в журнале.
                            if !persisted.failed.is_empty() {
                                let names: Vec<&str> = persisted.failed.iter().map(|(n, _)| n.as_str()).collect();
                                error!(
                                    "Выгрузки шага [{id}] не сохранены и будут потеряны при удалении рабочего каталога: {}",
                                    names.join(", ")
                                );
                            }
                            let summary = commands::campaign::summarize_step_exports(&exports_dir);
                            chain_lock.step_summaries.push((label.clone(), summary));
                        }
                    }

                    let _ = state.session_manager.close_session(cabinet_id);

                    emit_wf_status(&app, &exec_id, id, "done", None);
                    info!("Workflow step [{id}]: {label} complete");
                }

                commands::campaign::WorkflowStep::Parallel {
                    ref id,
                    ref branches,
                    ..
                } => {
                    emit_wf_status(&app, &exec_id, id, "running", None);

                    let mut handles: Vec<tokio::task::JoinHandle<Result<(), String>>> = Vec::new();
                    for branch in branches.iter() {
                        let s = state.clone();
                        let a = app.clone();
                        let eid = exec_id.clone();
                        let b = branch.clone();
                        let cc = context_chain.clone();
                        handles.push(tokio::spawn(async move {
                            execute_workflow_steps(b, s, a, eid, cc).await
                        }));
                    }

                    for h in handles {
                        if let Err(e) = h.await.map_err(|e| e.to_string())? {
                            emit_wf_status(&app, &exec_id, id, "error", Some(&e));
                            return Err(e);
                        }
                    }

                    emit_wf_status(&app, &exec_id, id, "done", None);
                }

                commands::campaign::WorkflowStep::Loop {
                    ref id,
                    ref body,
                    ref review,
                    max_iterations,
                    ..
                } => {
                    for i in 0..*max_iterations {
                        let iter_label = format!("{}/{}", i + 1, max_iterations);
                        emit_wf_status(
                            &app,
                            &exec_id,
                            id,
                            &format!("iterating {iter_label}"),
                            None,
                        );

                        execute_workflow_steps(
                            body.clone(),
                            state.clone(),
                            app.clone(),
                            exec_id.clone(),
                            context_chain.clone(),
                        )
                        .await?;
                        execute_workflow_steps(
                            review.clone(),
                            state.clone(),
                            app.clone(),
                            exec_id.clone(),
                            context_chain.clone(),
                        )
                        .await?;
                    }
                    emit_wf_status(&app, &exec_id, id, "done", None);
                }
            }
        }
        Ok(())
    })
}

fn emit_wf_status(
    app: &tauri::AppHandle,
    exec_id: &str,
    node_id: &str,
    status: &str,
    error: Option<&str>,
) {
    let _ = app.emit(
        &format!("workflow-execution-{exec_id}"),
        serde_json::json!({
            "type": "node-status",
            "node_id": node_id,
            "status": status,
            "error": error
        })
        .to_string(),
    );
}

#[tauri::command]
fn workflow_control(
    execution_id: String,
    action: String,
    state: tauri::State<'_, Arc<AppState>>,
) -> Result<(), String> {
    let mut execs = state.workflow_executions.lock().unwrap();
    match action.as_str() {
        "cancel" => {
            execs.insert(execution_id, "cancelled".into());
            Ok(())
        }
        "pause" => {
            execs.insert(execution_id, "paused".into());
            Ok(())
        }
        "resume" => {
            execs.insert(execution_id, "running".into());
            Ok(())
        }
        _ => Err(format!("Unknown action: {action}")),
    }
}

// ============== RAG/Parser Sidecar Lifecycle ==============

static RAG_PROCESS: std::sync::OnceLock<Mutex<Option<std::process::Child>>> =
    std::sync::OnceLock::new();
static PARSER_PROCESS: std::sync::OnceLock<Mutex<Option<std::process::Child>>> =
    std::sync::OnceLock::new();

fn start_rag_server() {
    let rag_dir = if cfg!(debug_assertions) {
        std::env::var("CARGO_MANIFEST_DIR")
            .ok()
            .map(|d| std::path::PathBuf::from(d).join("..").join("brand-hub").join("rag-server"))
            .unwrap_or_default()
    } else {
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_default()
            .join("brand-hub")
            .join("rag-server")
    };

    let server_py = rag_dir.join("server.py");
    if !server_py.exists() {
        warn!("RAG server not found at {}", server_py.display());
        return;
    }

    let python = if cfg!(windows) { "python" } else { "python3" };
    let mut rag_cmd = std::process::Command::new(python);
    rag_cmd
        .arg("server.py")
        .current_dir(&rag_dir)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    #[cfg(windows)]
    rag_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    match rag_cmd.spawn()
    {
        Ok(child) => {
            info!("RAG server started (PID={})", child.id());
            let lock = RAG_PROCESS.get_or_init(|| Mutex::new(None));
            *lock.lock().unwrap() = Some(child);
        }
        Err(e) => warn!("Failed to start RAG server: {e}"),
    }
}

fn start_parser_server() {
    let base = if cfg!(debug_assertions) {
        std::env::var("CARGO_MANIFEST_DIR")
            .ok()
            .map(|d| std::path::PathBuf::from(d).join("..").join("brand-hub"))
            .unwrap_or_default()
    } else {
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_default()
            .join("brand-hub")
    };

    // Try bundled exe first (PyInstaller), fallback to python
    let exe_path = base.join("dist").join("aurora-parser").join("aurora-parser.exe");
    if exe_path.exists() {
        let mut parser_exe_cmd = std::process::Command::new(&exe_path);
        parser_exe_cmd
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
        #[cfg(windows)]
        parser_exe_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        match parser_exe_cmd.spawn()
        {
            Ok(child) => {
                info!("Parser server started from exe (PID={})", child.id());
                let lock = PARSER_PROCESS.get_or_init(|| Mutex::new(None));
                *lock.lock().unwrap() = Some(child);
                return;
            }
            Err(e) => warn!("Failed to start Parser exe: {e}, falling back to python"),
        }
    }

    // Fallback: run with Python
    let parser_dir = base.join("parser");
    let server_py = parser_dir.join("server.py");
    if !server_py.exists() {
        warn!("Parser server not found at {}", server_py.display());
        return;
    }

    let python = if cfg!(windows) { "python" } else { "python3" };
    let mut parser_py_cmd = std::process::Command::new(python);
    parser_py_cmd
        .arg("server.py")
        .current_dir(&parser_dir)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    #[cfg(windows)]
    parser_py_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    match parser_py_cmd.spawn()
    {
        Ok(child) => {
            info!("Parser server started via python (PID={})", child.id());
            let lock = PARSER_PROCESS.get_or_init(|| Mutex::new(None));
            *lock.lock().unwrap() = Some(child);
        }
        Err(e) => warn!("Failed to start Parser server: {e}"),
    }
}

#[tauri::command]
async fn econ_sidecar_wait_ready(timeout_ms: Option<u64>) -> bool {
    let _ = timeout_ms; // reserved for future use
    econ_sidecar::wait_for_sidecar_ready().await
}

/// Force-restart the econometrica sidecar. Called from UI "Перезапустить модуль" button.
/// Clears banned cooldown, kills any zombie process, spawns fresh, waits for health.
#[tauri::command]
async fn econ_sidecar_restart() -> Result<(), String> {
    econ_sidecar::force_restart().await
}


fn stop_rag_server() {
    if let Some(lock) = RAG_PROCESS.get() {
        if let Some(mut child) = lock.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
            info!("RAG server stopped");
        }
    }
}

fn stop_parser_server() {
    if let Some(lock) = PARSER_PROCESS.get() {
        if let Some(mut child) = lock.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
            info!("Parser server stopped");
        }
    }
}

/// Clear WebView2 cache for all known app identifiers.
fn clear_webview_cache() {
    let identifiers = [
        "com.aiagency.desktop",
        "com.rosst.creative",
        "com.rosst.legal",
        "com.rosst.media",
        "com.aurora.creative-hub",
        "com.aurora.analytics-hub",
        "com.aurora.econometrica",
    ];

    if let Some(local_app_data) = std::env::var_os("LOCALAPPDATA") {
        let base = std::path::PathBuf::from(local_app_data);
        for id in &identifiers {
            let cache_dir = base.join(id).join("EBWebView");
            if cache_dir.exists() {
                let _ = std::fs::remove_dir_all(&cache_dir);
            }
        }
    }
}

/// Build and run the Tauri application, returning any error instead of panicking.
fn build_app() -> Result<(), String> {
    // Clean up stale sessions from previous runs
    let _ = session::cleanup::cleanup_stale_sessions();

    let session_manager = SessionManager::new()
        .map_err(|e| format!("Failed to initialize session manager: {e}"))?;
    let state = Arc::new(AppState {
        session_manager,
        active_pids: Arc::new(Mutex::new(HashMap::new())),
        workflow_executions: Arc::new(Mutex::new(HashMap::new())),
        content_packs_verified: Arc::new(AtomicBool::new(false)),
    });

    let builder = tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .max_file_size(5_000_000) // 5 MB
                .rotation_strategy(tauri_plugin_log::RotationStrategy::KeepOne)
                .build(),
        )
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init());

    // MCP Bridge — DOM-driven визуальный аудит (visual-audit skill).
    // ТОЛЬКО dev (#[cfg(debug_assertions)]) → сервер не стартует в release.
    // bind 127.0.0.1 (НЕ дефолтный 0.0.0.0:9223) — порт не открывается в сеть.
    #[cfg(debug_assertions)]
    let builder = builder.plugin(
        tauri_plugin_mcp_bridge::Builder::new()
            .bind_address("127.0.0.1")
            .build(),
    );

    builder
        // Phase 3: Custom protocol for external frontend
        .register_uri_scheme_protocol("aurora", |ctx, req| handle_aurora_protocol(ctx.app_handle(), req))
        .setup(|app| {
            let local_data_dir = app.path().app_local_data_dir().ok();

            // CPD-30: страховочный повторный init() — обычно уже отработал раньше, в run()
            // (см. LOCALAPPDATA+TAURI_ENV_IDENTIFIER там), до cleanup_stale_sessions() и
            // SessionManager::new() в build_app(). OnceLock::set() второй раз молча не сработает,
            // если первый уже прошёл; если LOCALAPPDATA был недоступен там — сработает здесь через
            // штатный app_local_data_dir(). Без ни одного из двух — фолбэк по CARGO_PKG_NAME (см.
            // durable_store::base_dir()), тоже per-app, но не под каталогом, что чистит деинсталлятор.
            if let Some(ref ldd) = local_data_dir {
                durable_store::init(ldd.clone());

                // 🔴 Батч C (C10, Medium): единственный ВНЕШНИЙ источник правды об идентификаторе
                // — `app_local_data_dir()` — до сих пор молча выбрасывался: `durable_store::init`
                // уже отработал в `run()`, второй `OnceLock::set` ничего не делает. А сторож
                // `build_identifier_matches_tauri_conf` живёт в системе координат самого дефекта:
                // он сверяет значение СВОИМ разбором `tauri.conf.json`, тем же приёмом, что и
                // `build.rs`, — ошибись разбор одинаково в обоих местах, тест зелёный, а состояние
                // уходит в каталог, которого Tauri не знает (content-packs и claude-runtime при
                // этом остаются в настоящем). Сверяем факт с фактом.
                // 🔴 Здесь же покрывается ЛОКАЛЬНАЯ редакция (`com.aurora.econometrica.local`,
                // оверлей `TAURI_CONFIG`): `app_local_data_dir()` считает каталог по СЛИТОЙ
                // конфигурации, то есть отвалившийся разбор оверлея в `build.rs` виден именно
                // отсюда. Ронять на клиенте нельзя: расхождение — не повод не запускать продукт,
                // но оно обязано быть видно в журнале.
                if let Some(mismatch) =
                    durable_store::describe_base_mismatch(ldd, &durable_store::resolve_path(""))
                {
                    warn!("durable_store: {mismatch}");
                }
            }

            // One-time migration: content_version.txt → vault-versions.json
            if let (Some(config_dir), Some(data_dir)) = (
                app.path().app_config_dir().ok(),
                app.path().app_data_dir().ok(),
            ) {
                if let Err(e) = commands::content_updater::migrate_from_legacy(&config_dir, &data_dir) {
                    warn!("vault-versions migration failed: {e}");
                }

                // Подобрать резерв кабинета, осиротевший после записи, прерванной
                // снятием процесса или отказом машины: рабочего файла нет, а целый
                // `*.vault.bak` лежит рядом. Без этого шага кабинет оставался пустым
                // до следующей удачной докачки — то есть без сети не открывался вовсе.
                let restored = commands::content_updater::restore_orphaned_vault_backups(&data_dir);
                if restored > 0 {
                    info!("Из резерва возвращено рабочих файлов кабинетов: {restored}");
                }
            }

            // Content pack verification - result stored in AppState for dynamic loaders
            if let Some(ref ldd) = local_data_dir {
                let packs_ok = match commands::content_pack::verify_content_packs(ldd) {
                    Ok(true) => { info!("Content packs verified at startup"); true }
                    Ok(false) => { info!("No content packs at startup - using hardcoded fallback"); false }
                    Err(e) => { warn!("Content pack integrity check FAILED at startup: {e}"); false }
                };
                // Propagate to AppState so dynamic loaders can check without re-verifying
                if let Some(s) = app.try_state::<Arc<AppState>>() {
                    s.content_packs_verified.store(packs_ok, Ordering::Release);
                }
                // Cleanup stale old frontend versions on startup
                cleanup_old_frontend_dirs(ldd);
            }

            // Determine window URL: verified external frontend or embedded fallback
            let use_external = local_data_dir.as_ref()
                .map(|d| has_verified_external_frontend(d))
                .unwrap_or(false);

            let url = if use_external {
                info!("Loading external frontend via aurora:// protocol");
                tauri::WebviewUrl::CustomProtocol(
                    tauri::Url::parse("aurora://localhost/").expect("valid aurora URL")
                )
            } else {
                info!("Loading embedded frontend (no verified external frontend)");
                tauri::WebviewUrl::App("index.html".into())
            };

            tauri::WebviewWindowBuilder::new(app, "main", url)
                .title("Aurora AI Econometrica - MMM Optimizer")
                .inner_size(1280.0, 820.0)
                .min_inner_size(900.0, 600.0)
                .center()
                .maximized(true)
                .build()?;

            // v1.0.9: quarantine legacy AIAgency license files (contamination from
            // старых Aurora Agency installations). Не использует их - просто
            // переименовывает в .bak чтобы убрать из будущих диагностик.
            license::quarantine_legacy_files();

            // Start Econometrica Python sidecar (FastAPI - dynamic per-user port)
            econ_sidecar::start_sidecar(app.handle());
            // Proactive watchdog - respawns sidecar on freeze/crash during runtime
            econ_sidecar::spawn_watchdog();

            Ok(())
        })
        .manage(state.clone())
        .invoke_handler(tauri::generate_handler![
            get_cabinets,
            get_license_status,
            import_license,
            import_cabinet_vault,
            check_online_auth,
            send_heartbeat,
            get_instance_id,
            check_content_update,
            update_content,
            get_local_content_version,
            display_version,
            get_machine_id,
            get_full_machine_hash,
            get_raw_fingerprint,
            open_cabinet,
            econ_ask_insight,
            rag_client::econ_rag_search,
            set_local_only,
            get_execution_mode,
            set_execution_mode,
            probe_local_claude,
            close_cabinet,
            send_message,
            list_inbox_files,
            list_export_files,
            copy_to_inbox,
            get_export_file_path,
            add_url_to_inbox,
            delete_inbox_file,
            show_inbox_in_folder,
            get_cabinet_commands,
            open_export_file,
            show_export_in_folder,
            delete_export_file,
            open_help,
            open_user_guide,
            save_help_pdf,
            get_content_pack,
            check_pptx_dependencies,
            install_pptx_dependencies,
            verify_content_packs_status,
            preview_export_file,
            cancel_claude,
            pptx_preprocess,
            pptx_postprocess,
            save_chat_message,
            load_chat_history,
            clear_chat_history,
            clear_workspace_files,
            get_usage_metrics,
            reset_metrics,
            rate_response,
            get_cabinet_ratings,
            copy_export_to_inbox,
            list_recent_exports,
            get_cabinet_path,
            set_cabinet_path,
            reset_cabinet_path,
            get_econometrica_projects_root,
            set_econometrica_projects_root,
            open_econometrica_projects_root,
            get_model_settings,
            set_model_settings,
            get_cloud_consent_status,
            accept_cloud_consent,
            withdraw_cloud_consent,
            list_vault_status,
            // export_logs removed - now internal helper, open_logs_folder uses it
            open_logs_folder,
            export_diagnostics,
            check_update,
            check_server_update,
            download_update,
            apply_update,
            feedback::submit_feedback,
            // Campaign & Workflow commands
            commands::campaign::campaign_create,
            commands::campaign::campaign_list,
            commands::campaign::campaign_get,
            commands::campaign::campaign_update_step,
            commands::campaign::workflow_templates,
            commands::campaign::workflow_create,
            commands::campaign::workflow_save,
            commands::campaign::workflow_delete,
            commands::campaign::campaign_to_workflow,
            // Brand commands (filesystem-first)
            brand::brand_list,
            brand::brand_create,
            brand::brand_get,
            brand::brand_activate,
            brand::brand_get_active,
            brand::brand_stats,
            brand::brand_upload_doc,
            brand::brand_search,
            brand::brand_history_search,
            brand::brand_health,
            brand::brand_update,
            brand::brand_delete,
            brand::brand_list_docs,
            brand::brand_delete_doc,
            brand::data_chat_deep,
            // Parser commands (HTTP proxy to sidecar)
            parser::parser_run,
            parser::parser_run_platform,
            parser::parser_status,
            parser::parser_history,
            parser::parser_health,
            // Workflow execution engine
            workflow_execute,
            workflow_execute_with_brief,
            workflow_control,
            // Pipeline commands
            commands::campaign::campaign_set_brief,
            commands::campaign::campaign_get_status,
            commands::campaign::campaign_export_zip,
            commands::campaign::campaign_open_exports,
            // Product type + default brand for frontend
            get_product_type,
            ensure_default_brand,
            // Phase 3: frontend repair from fallback page
            repair_frontend,
            // Econometrica pipeline commands
            econ_sidecar_wait_ready,
            econ_sidecar_restart,
            commands::econometrica::econ_health,
            commands::econometrica::econ_classifier_patterns,
            commands::econometrica::econ_migrate_project,
            commands::econometrica::econ_validate,
            commands::econometrica::econ_train,
            commands::econometrica::econ_train_start,
            commands::econometrica::econ_train_progress,
            commands::econometrica::econ_train_result,
            commands::econometrica::econ_train_cancel,
            commands::econometrica::econ_decompose,
            commands::econometrica::econ_optimize,
            // A3/OPP-05 (2026-07-03): preflight-гейт до кнопки «Обучить»
            commands::econometrica::econ_preflight,
            // A4/OPP-04 (2026-07-03): интервалы оптимального сплита (Jin 2017)
            commands::econometrica::econ_optimize_split_ci,
            // E1 (2026-07-03): backtest-витрина «модель vs факт» (rolling-origin)
            commands::econometrica::econ_backtest,
            // E3 (2026-07-03): жизненный цикл модели - история/сравнение/дрейф
            commands::econometrica::econ_model_history,
            commands::econometrica::econ_generation_compare,
            commands::econometrica::econ_drift_check,
            // E4 (2026-07-03): прогнозы-обещания («Зафиксировать прогноз»)
            commands::econometrica::econ_promises_list,
            commands::econometrica::econ_promise_create,
            commands::econometrica::econ_promises_check,
            // v1.3.0 - Goal-Seek + Safe Corridor + Auto-Price + KPI Settings (ADR-014..017)
            commands::econometrica::econ_safe_corridor,
            commands::econometrica::econ_optimize_inverse,
            commands::econometrica::econ_auto_detect_price,
            commands::econometrica::econ_save_kpi_settings,
            commands::econometrica::econ_forecast_context,
            commands::econometrica::econ_forecast_scaling,
            commands::econometrica::econ_hierarchical_warning,
            commands::econometrica::econ_scenario,
            commands::econometrica::econ_compare,
            commands::econometrica::econ_scenario_delete,
            commands::econometrica::econ_awareness_forecast,
            commands::econometrica::econ_awareness_sales,
            commands::econometrica::econ_chart,
            commands::econometrica::econ_data_preview,
            commands::econometrica::econ_export_pptx,
            commands::econometrica::econ_export_html,
            commands::econometrica::econ_adstock_select,
            // Trust Level 3 (v1.1.0) - channel categorization
            commands::econometrica::econ_categorize_channels,
            // Sprint 3 Pharma Causal - 6 endpoints pass-through
            commands::econometrica::econ_causal_preflight,
            commands::econometrica::econ_causal_list,
            commands::econometrica::econ_causal_consistency,
            commands::econometrica::econ_causal_did,
            commands::econometrica::econ_causal_scm,
            commands::econometrica::econ_causal_forest,
            // Planning mode commands (feat/econ-planning-mode)
            commands::econometrica::econ_download_media_plan_template,
            commands::econometrica::econ_confirm_media_plan,
            commands::econometrica::econ_save_planning,
            // Project management commands
            commands::project::project_list,
            commands::project::project_create,
            commands::project::project_get,
            commands::project::project_update,
            commands::project::project_delete,
            commands::project::project_upload_data,
            commands::project::project_activate,
            commands::project::project_get_active,
            commands::project::project_get_dir,
            commands::project::project_stats,
            commands::project::project_load_results,
            commands::project::project_load_comparison,
            commands::project::project_export_archive,
            commands::project::project_import_archive,
            // Report generation commands
            commands::report::econ_generate_report,
            commands::report::econ_export_xlsx,
            commands::report::econ_open_exports,
            commands::report::save_sample_file,
            commands::report::reveal_path,
        ])
        .on_window_event(move |window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<Arc<AppState>>();
                let _ = state.session_manager.close_all();
                // Idempotent shutdown - safe to call even if never started
                stop_rag_server();
                stop_parser_server();
                econ_sidecar::stop_sidecar();
            }
        })
        .run(tauri::generate_context!())
        .map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Record app start time for diagnostics uptime
    commands::diagnostics::mark_app_start();

    // One-time data migration for identifier rename (ROSST → Aurora AI v0.8.0)
    // 🔴 МИНА — НЕ переводить на `AURORA_APP_IDENTIFIER` без решения владельца (Р-1, 2026-07-30).
    // Переменной `TAURI_ENV_IDENTIFIER` не существует (CPD-33), поэтому `tauri_id` ВСЕГДА равен
    // запасному "com.aurora.agency". Из-за этого `migrate_if_needed` всё время отрабатывает ЧУЖУЮ
    // пару таблицы IDENTIFIER_MIGRATIONS (com.aiagency.desktop → com.aurora.agency), а заявленные
    // переносы вида com.rosst.legal → com.aurora.legal не выполнялись НИ РАЗУ ни у одного клиента.
    // Почему это мина: рядом теперь стоит починенная переменная под новым именем
    // (AURORA_APP_IDENTIFIER, кладёт build.rs), и «унификация имён» выглядит естественным шагом —
    // но она разом ОЖИВИТ спящий перенос license.json и vault_salt.bin у всех продуктов линейки.
    // 🔴 Удалять вызов тоже нельзя: для офлайн-клиента, ставящего новую версию поверх очень старой,
    // это необратимое изменение поведения. Сначала зонд — что реально установлено у пилотных
    // клиентов и была ли повторная выдача лицензий (папка `2_Выдача_лицензий`).
    let tauri_id = option_env!("TAURI_ENV_IDENTIFIER").unwrap_or("com.aurora.agency");
    commands::data_migration::migrate_if_needed(tauri_id);

    // CPD-30: инициализация per-app базы durable_store ДО build_app() — cleanup_stale_sessions()
    // и SessionManager::new() (session/{cleanup,manager}.rs) вызываются раньше .setup() hook,
    // где обычно становится доступен app.path().app_local_data_dir().
    // %LOCALAPPDATA%\<identifier> — ровно то значение, что вернул бы app_local_data_dir() (тот же
    // идентификатор, та же база), просто вычисленное вручную, без ожидания AppHandle. Без этого
    // durable_store ушёл бы в фолбэк по CARGO_PKG_NAME (см. durable_store::base_dir()) — тоже
    // per-app, но не под каталогом, который чистит деинсталлятор.
    // 🔴 Внешний аудит 2026-07-29 (Critical): база инициализируется ТОЛЬКО когда идентификатор
    // пришёл из переменной сборки. Прежде здесь стоял `tauri_id`, у которого ОБЩИЙ фолбэк
    // "com.aurora.agency": при сборке без tauri CLI (прямой `cargo build`, сборка в CI без
    // tauri-cli) ВСЕ продукты линейки получали ОДНУ базу — и CPD-30 воспроизводился в новом
    // каталоге, уже с маркером и перенесённой историей, то есть тише прежнего. Страховочный
    // init в `.setup()` не спасал: OnceLock уже установлен здесь.
    //
    // 🔴 Вторая волна того же аудита: у той правки условие не выполнялось НИКОГДА.
    // `TAURI_ENV_IDENTIFIER` не выставляет никто — ни сборщик Tauri (он задаёт TAURI_ENV_ARCH,
    // _DEBUG, _FAMILY, _PLATFORM, _PLATFORM_TYPE, _PLATFORM_VERSION, _TARGET_TRIPLE и только их),
    // ни `build.rs`, ни задание сборки. Значит `durable_store::init` не вызывался ни разу, и всё
    // состояние уходило в запасной каталог по имени пакета — доказано на диске: каталог
    // `%LOCALAPPDATA%\aurora-econometrica-gui` с перенесённой историей вместо
    // `…\com.aurora.econometrica`. Коллизии продуктов там нет (имя пакета своё у каждого форка),
    // но каталог не тот, где лежат остальные данные приложения, и его не чистит деинсталлятор —
    // то есть заявленное в этом самом комментарии не выполнялось. Теперь идентификатор кладёт в
    // бинарь наш `build.rs` (читает `tauri.conf.json`, а для локальной редакции — оверлей
    // `TAURI_CONFIG` из `tauri.local.conf.json`), под собственным именем — чтобы его снова не
    // приняли за переменную, которую якобы выставляет кто-то снаружи. Сторож —
    // `durable_store::tests::build_identifier_matches_tauri_conf`.
    if let Some(local_app_data) = std::env::var_os("LOCALAPPDATA") {
        let build_identifier = env!("AURORA_APP_IDENTIFIER");
        durable_store::init(std::path::PathBuf::from(local_app_data).join(build_identifier));
    }

    // Fix interrupted pipelines from previous session
    commands::campaign::fix_interrupted_campaigns();

    // FIX BUG-2: Auto-start RAG/Parser sidecars for Creative Hub
    if online_auth::is_creative_hub() {
        start_rag_server();
        start_parser_server();
    }

    match build_app() {
        Ok(()) => {}
        Err(e) => {
            let err_str = e.to_string();

            // WebView2 initialization failure - auto-clean cache and retry
            if err_str.contains("WebView2") || err_str.contains("0x8007139F") {
                clear_webview_cache();

                // Retry once after cache cleanup
                match build_app() {
                    Ok(()) => (),
                    Err(retry_err) => {
                        let msg = format!(
                            "Приложение не смогло запуститься после очистки кэша WebView2.\n\n\
                             Ошибка: {}\n\n\
                             Попробуйте:\n\
                             1. Перезагрузить компьютер\n\
                             2. Переустановить приложение\n\
                             3. Обратиться в техподдержку",
                            retry_err
                        );
                        show_error_dialog("Aurora AI Econometrica - Ошибка запуска", &msg);
                    }
                }
            } else {
                let msg = format!(
                    "Приложение не смогло запуститься.\n\n\
                     Ошибка: {}\n\n\
                     Попробуйте:\n\
                     1. Перезагрузить компьютер\n\
                     2. Переустановить приложение\n\
                     3. Обратиться в техподдержку",
                    err_str
                );
                show_error_dialog("Aurora AI Econometrica - Ошибка запуска", &msg);
            }
        }
    }
}

#[cfg(test)]
mod delivery_failure_tests {
    use super::*;

    /// Причина отказа обязана следовать из факта, а не быть одной на все случаи
    /// (находка аудита M-5): домысел уводит по ложному следу и пользователя,
    /// и поддержку.
    #[test]
    fn reason_follows_the_actual_failure() {
        let (reason, _) = delivery_failure_explanation(
            "econometrist.vault: поток оборван на 4278 байт (сервер обещал 34165)",
        );
        assert!(reason.contains("обрывается"), "обрыв связи: {reason}");

        // Число полученных байт не должно приниматься за код ответа: наблюдённое
        // окно обрывов 3251…5649 накрывает и 403, и 404 (находка аудита).
        for bytes in ["4034", "4045", "5403", "4404"] {
            let (reason, _) = delivery_failure_explanation(&format!(
                "econometrist.vault: поток оборван на {bytes} байт (сервер обещал 34165)"
            ));
            assert!(
                reason.contains("обрывается"),
                "обрыв на {bytes} байт принят за код ответа: {reason}"
            );
        }

        let (reason, hints) = delivery_failure_explanation(
            "Download failed for econometrist.vault: HTTP 403 Forbidden - Лицензия не найдена",
        );
        assert!(reason.contains("право"), "отказ по лицензии: {reason}");
        assert!(hints.contains("лицензии"), "совет обязан быть про лицензию: {hints}");

        let (reason, _) = delivery_failure_explanation(
            "Download failed for econometrist.vault: HTTP 404 - Файл не найден",
        );
        assert!(reason.contains("нет"), "файла нет на сервере: {reason}");

        let (reason, _) =
            delivery_failure_explanation("сервер лицензий недоступен (состояние связи: offline)");
        assert!(reason.contains("недоступен"), "сервер не отвечает: {reason}");

        // Неизвестная причина не должна выдавать себя за известную.
        let (reason, _) = delivery_failure_explanation("причина неизвестна");
        assert!(
            !reason.contains("обрывается") && !reason.contains("недоступен"),
            "неизвестная причина обязана оставаться нейтральной: {reason}"
        );
    }

    /// В клиентском тексте — короткое тире, без кодов и путей.
    #[test]
    fn client_text_keeps_typography() {
        for detail in [
            "поток оборван на 100 байт",
            "HTTP 403",
            "HTTP 404",
            "сервер лицензий недоступен",
            "что-то ещё",
        ] {
            let (reason, hints) = delivery_failure_explanation(detail);
            for text in [reason, hints] {
                assert!(!text.contains('—'), "длинное тире в клиентском тексте: {text}");
                assert!(!text.contains(".vault"), "имя файла в клиентском тексте: {text}");
                assert!(!text.contains("HTTP"), "технический код в клиентском тексте: {text}");
            }
        }
    }
}

#[cfg(test)]
mod brief_tests {
    use super::*;

    #[test]
    fn extract_params_multiline() {
        let msg = "/analytics\nСлайды: Все (без перебивок)\nАудитория: CEO, CMO";
        let params = extract_brief_params(msg);
        assert!(params.is_some());
        let p = params.unwrap();
        assert!(p.contains("Слайды: Все"));
        assert!(p.contains("Аудитория: CEO, CMO"));
    }

    #[test]
    fn extract_params_single_line() {
        assert_eq!(extract_brief_params("/analytics"), None);
        assert_eq!(extract_brief_params("/check"), None);
    }

    #[test]
    fn extract_params_empty_after_command() {
        assert_eq!(extract_brief_params("/analytics\n\n"), None);
    }

    #[test]
    fn parse_slides_specific_range() {
        let params = "Слайды: Конкретные: 3, 7-10, 15\nАудитория: CEO";
        let result = parse_slide_selection(params);
        assert_eq!(result, Some(vec![3, 7, 8, 9, 10, 15]));
    }

    #[test]
    fn parse_slides_en_dash() {
        let params = "Слайды: Конкретные: 3, 7–10";
        let result = parse_slide_selection(params);
        assert_eq!(result, Some(vec![3, 7, 8, 9, 10]));
    }

    #[test]
    fn parse_slides_all() {
        let params = "Слайды: Все (без перебивок и оглавлений)\nАудитория: CEO";
        assert_eq!(parse_slide_selection(params), None);
    }

    #[test]
    fn parse_slides_no_param() {
        let params = "Аудитория: CEO, CMO\nДополнительно: Фокус на digital";
        assert_eq!(parse_slide_selection(params), None);
    }

    #[test]
    fn parse_slides_single() {
        let params = "Слайды: Конкретные: 5";
        assert_eq!(parse_slide_selection(params), Some(vec![5]));
    }
}

#[cfg(test)]
mod resolve_slash_tests {
    use super::*;

    /// Боевой путь консультационных команд эконометриста: фронт приклеивает блок
    /// «=== Данные проекта ===» к сообщению, resolve_slash_command должен ДОСТАВИТЬ
    /// его в промпт через $ARGUMENTS. Эвал-харнес шлёт message мимо send_message,
    /// поэтому именно этот тест закрывает регрессию доставки данных (Critical
    /// 2026-07-12: без $ARGUMENTS в шаблоне блок данных молча отбрасывался).
    #[test]
    fn resolve_injects_project_data_when_placeholder_present() {
        let dir = tempfile::tempdir().unwrap();
        let cmd_dir = dir.path().join(".claude").join("commands");
        std::fs::create_dir_all(&cmd_dir).unwrap();
        std::fs::write(
            cmd_dir.join("interpret-model.md"),
            "Осмысли модель.\n\n---\n\n$ARGUMENTS",
        )
        .unwrap();

        let message = "/interpret-model\n\n=== Данные проекта (приложены приложением) ===\n[model-diagnostics]\n{\"mqs\": 72}";
        let resolved = resolve_slash_command(message, dir.path());

        assert!(resolved.contains("=== Данные проекта"), "блок данных должен доехать до промпта");
        assert!(resolved.contains("72"), "числа модели должны попасть в промпт");
        assert!(resolved.contains("Осмысли модель."), "инструкция шаблона сохранена");
        assert!(!resolved.contains("$ARGUMENTS"), "плейсхолдер должен быть заменён");
    }

    /// Контракт-документация: БЕЗ $ARGUMENTS в шаблоне arguments (блок данных)
    /// теряется — именно так возник Critical. Тест фиксирует причину и защищает
    /// инвариант ниже (реальные промпты обязаны содержать $ARGUMENTS).
    #[test]
    fn resolve_without_placeholder_drops_arguments() {
        let dir = tempfile::tempdir().unwrap();
        let cmd_dir = dir.path().join(".claude").join("commands");
        std::fs::create_dir_all(&cmd_dir).unwrap();
        let template = "Инструкция без плейсхолдера.";
        std::fs::write(cmd_dir.join("legacy-cmd.md"), template).unwrap();

        let message = "/legacy-cmd\n\n=== Данные проекта ===\n{\"x\": 1}";
        let resolved = resolve_slash_command(message, dir.path());

        assert_eq!(resolved, template, "без $ARGUMENTS хвост сообщения отбрасывается");
        assert!(!resolved.contains("Данные проекта"), "данные не доехали — это и был баг");
    }

    /// Регресс-детектор варианта A: каждая консультационная команда эконометриста,
    /// получающая блок данных проекта (ECON_DATA_COMMANDS во фронте), ОБЯЗАНА иметь
    /// $ARGUMENTS в своём .md — иначе доставка данных снова молча сломается.
    #[test]
    fn econometrist_consult_commands_have_arguments_placeholder() {
        let base = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../New_AI_Agency/econometrist/.claude/commands");
        let commands = [
            "interpret-model",
            "why-channel",
            "explain-ratio",
            "pilot-design",
            "next-quarter-plan",
            "data-gaps",
        ];
        for cmd in commands {
            let path = base.join(format!("{cmd}.md"));
            let content = std::fs::read_to_string(&path)
                .unwrap_or_else(|e| panic!("не прочитать {}: {e}", path.display()));
            assert!(
                content.contains("$ARGUMENTS"),
                "команда /{cmd} должна содержать $ARGUMENTS для доставки блока данных проекта",
            );
        }
    }
}

#[cfg(test)]
mod workspace_clear_tests {
    use super::*;

    /// CPD-69: очистка при старте обязана трогать inbox и обязана НЕ трогать exports —
    /// это готовые документы клиента, а не временный мусор сессии.
    #[test]
    fn start_cleanup_removes_inbox_but_keeps_export_deliverables() {
        let dir = tempfile::tempdir().unwrap();
        let workspace = dir.path();
        let inbox = workspace.join("inbox");
        let exports = workspace.join("exports");
        std::fs::create_dir_all(&inbox).unwrap();
        std::fs::create_dir_all(&exports).unwrap();

        std::fs::write(inbox.join("source.pptx"), b"source").unwrap();
        std::fs::write(exports.join("Заключение.docx"), b"deliverable 1").unwrap();
        std::fs::write(exports.join("Письмо.docx"), b"deliverable 2").unwrap();

        let removed = clear_workspace_dirs(workspace, WORKSPACE_DIRS_CLEARED_ON_START);

        assert_eq!(removed, 1, "должен быть удалён ровно один файл (из inbox)");
        assert!(
            std::fs::read_dir(&inbox).unwrap().next().is_none(),
            "inbox обязан быть пуст после очистки при старте"
        );
        assert!(
            exports.join("Заключение.docx").exists(),
            "выдача клиента не должна исчезать при запуске приложения"
        );
        assert!(
            exports.join("Письмо.docx").exists(),
            "выдача клиента не должна исчезать при запуске приложения"
        );
    }

    /// Структурный сторож: exports не должна вернуться в список очистки по невнимательности
    /// при будущей правке (например, при добавлении нового служебного каталога рядом).
    #[test]
    fn exports_must_never_be_listed_for_start_cleanup() {
        assert!(
            !WORKSPACE_DIRS_CLEARED_ON_START.contains(&"exports"),
            "exports — выдача клиента, её нельзя чистить при запуске (CPD-69)"
        );
    }
}
// rebuild
// icon refresh
