pub mod commands;
pub mod crypto;
pub mod econ_sidecar;
pub mod errors;
pub mod metrics;
pub mod session;

use commands::{brand, cabinet, claude, content_updater, feedback, license, online_auth, parser, updater, user_config, vault};
use session::manager::SessionManager;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager};
#[allow(unused_imports)]
use log::{debug, error, info, warn};

/// Application state shared across Tauri commands.
pub struct AppState {
    pub session_manager: SessionManager,
    /// Maps cabinet_id → PID of the running Claude process (if any).
    pub active_pids: Arc<Mutex<HashMap<String, u32>>>,
    /// Active workflow executions: execution_id → status ("running"/"completed"/"cancelled"/"failed")
    pub workflow_executions: Arc<Mutex<HashMap<String, String>>>,
}

// ============== Tauri Commands ==============

#[tauri::command]
async fn get_cabinets(_state: tauri::State<'_, Arc<AppState>>, app_handle: tauri::AppHandle) -> Result<Vec<cabinet::CabinetInfo>, String> {
    #[cfg(debug_assertions)]
    if std::env::var("AIAGENCY_DEV").is_ok() {
        info!("[DEV] Bypassing license check — returning all cabinets");
        return Ok(cabinet::get_cabinet_definitions());
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

            // Collect vault filenames that are missing locally
            let missing: Vec<String> = online.cabinets.iter()
                .map(|cab| vault::vault_filename_pub(cab))
                .filter(|fname| !vaults_dir.join(fname).exists())
                .collect();

            if !missing.is_empty() {
                info!("Downloading {} missing vault(s) from server...", missing.len());
                let checksums = serde_json::json!({});
                match content_updater::download_updates(&config_dir, &data_dir, product, cv, &missing, &checksums, Some(&app_handle)).await {
                    Ok(updated) => info!("Downloaded {}/{} vault files", updated.len(), missing.len()),
                    Err(e) => warn!("Failed to download vaults: {e}"),
                }
            }
        }

        let all_cabinets = cabinet::get_cabinet_definitions();
        let available: Vec<_> = all_cabinets.into_iter()
            .filter(|c| online.cabinets.contains(&c.id))
            .collect();
        info!("Cabinets loaded (online): {} available", available.len());
        return Ok(available);
    }

    if online.available && online.status == "blocked" {
        // Server explicitly denied — do NOT fallback to offline
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
        let err = status.error.unwrap_or("Invalid license".to_string());
        metrics::audit::log_event("license_validate", &err, false);
        warn!("License invalid: {err}");
        return Err(err);
    }

    metrics::audit::log_event("license_validate", &format!("issued_to={}, days_remaining={}", status.issued_to, status.days_remaining), true);

    let all_cabinets = cabinet::get_cabinet_definitions();
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

#[tauri::command]
async fn check_online_auth(app_handle: tauri::AppHandle) -> Result<online_auth::OnlineAuthStatus, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let app_version = env!("CARGO_PKG_VERSION");
    Ok(online_auth::authorize(&config_dir, app_version, "").await)
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
    content_updater::download_updates(&config_dir, &data_dir, &product, &version, &files, &checksums, Some(&app_handle))
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_local_content_version(app_handle: tauri::AppHandle) -> Result<Option<String>, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    Ok(content_updater::get_local_version(&config_dir))
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
            return Err(status.error.unwrap_or("Invalid license".to_string()));
        }
        allowed_cabinets = status.cabinets;
    }

    if !allowed_cabinets.contains(&cabinet_id) {
        warn!("Cabinet '{cabinet_id}' not allowed (cabinets: {:?})", allowed_cabinets);
        return Err(format!("Cabinet '{cabinet_id}' not included in license"));
    }

    // ── Auto-download vault if missing ──
    let vault_filename = vault::vault_filename_pub(&cabinet_id);
    let vault_path = vault::vaults_dir(&data_dir).join(&vault_filename);

    if !vault_path.exists() {
        info!("Vault not found locally for {cabinet_id}, attempting server download...");
        if let (Some(cv), true) = (&online.content_version, online.status == "ok" || online.status == "cached") {
            let product = online_auth::detect_product();
            let files = vec![vault_filename.clone()];
            let checksums = serde_json::json!({});
            match content_updater::download_updates(&config_dir, &data_dir, product, cv, &files, &checksums, Some(&app_handle)).await {
                Ok(updated) => info!("Downloaded {} vault files from server", updated.len()),
                Err(e) => warn!("Failed to download vault from server: {e}"),
            }
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
                    // Local key didn't work — try offline license key
                    let fp = crypto::fingerprint::get_machine_fingerprint().map_err(|e| e.to_string())?;
                    match license::License::load(&config_dir) {
                        Ok(lic) => match lic.salt_bytes() {
                            Ok(salt) => crypto::hkdf::derive_key(&fp, &salt).map_err(|e| e.to_string())?,
                            Err(e) => return Err(e.to_string()),
                        },
                        Err(e) => return Err(format!("Cannot decrypt vault: no valid key. {e}")),
                    }
                }
            }
        }
        Err(_) => {
            // No local salt — use offline license key
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

/// Multi-phase analytics pipeline for large PPTX presentations.
/// Chains Phase 0 (map) → Phase 1 (detail chunks) → Phase 2 (synthesis) via --resume.
/// Returns (phase1_markdowns, synthesis_markdown, final_session_id).
async fn run_analytics_pipeline(
    work_dir: &std::path::Path,
    overview: &str,
    chunk_split: &commands::pptx_processor::ChunkSplit,
    app_handle: tauri::AppHandle,
    cabinet_id: &str,
    active_pids: Arc<std::sync::Mutex<std::collections::HashMap<String, u32>>>,
    state: &AppState,
) -> Result<(Vec<String>, String, Option<String>), String> {
    let total_phases = chunk_split.chunk_count + 2; // map + N chunks + synthesis
    let mut session_id: Option<String> = state.session_manager.get_claude_session_id(cabinet_id);
    let mut chunk_markdowns: Vec<String> = Vec::new();

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
    let phase0_prompt = format!(
        "[АНАЛИТИЧЕСКИЙ ПАЙПЛАЙН — ФАЗА 0: КАРТА]\n\n{}\n\n\
         Задача: определи тематические блоки презентации. Для каждого блока укажи:\n\
         - Название блока\n- Диапазон слайдов\n- Краткое описание\n\n\
         Затем сформулируй 3-5 гипотез для проверки при детальном анализе.\n\n\
         Формат:\n## СТРУКТУРА ПРЕЗЕНТАЦИИ\n## БЛОК: Название — слайды X-Y\n## ГИПОТЕЗЫ ДЛЯ ПРОВЕРКИ",
        overview
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
            "[АНАЛИТИЧЕСКИЙ ПАЙПЛАЙН — ФАЗА 1: ДЕТАЛЬНЫЙ АНАЛИЗ]\n\
             Чанк {}/{}. Вот данные слайдов:\n\n{}\n\n\
             Для каждого слайда напиши на русском языке:\n\
             ## Слайд N: Заголовок\nACTION TITLE: ...\n\n[CEO] ...\n\n[CMO] ...\n\n[BM] ...\n\n\
             В конце — краткие итоги для слайдов этого чанка.",
            i + 1, chunk_split.chunk_count, chunk_data
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
        "[АНАЛИТИЧЕСКИЙ ПАЙПЛАЙН — ФАЗА 2: СИНТЕЗ]\n\n\
         Ты проанализировал все {} слайдов с данными ({} чанков). \
         Вот краткий обзор:\n\n{}\n\n\
         Теперь напиши на русском языке:\n\
         ## EXECUTIVE SUMMARY\n5-7 тезисов по Pyramid Principle (главное → детали)\n\n\
         ## ОБЩИЙ ВЫВОД ПО ПРЕЗЕНТАЦИИ\nРазвёрнутый аналитический нарратив на ~1 страницу (4-6 абзацев): \
         что происходит на рынке, какие силы действуют, куда движется ситуация, \
         что это значит для бизнеса, стратегические развилки.\n\n\
         ## БЛОК: Название\nДля каждого блока: тезисы (bullets) + развёрнутый вывод (1-2 абзаца)\n\n\
         ## МОСТЫ\nМинимум 5 межтематических связей (каузальные цепочки)\n\n\
         ## РЕКОМЕНДАЦИИ\nСтратегические рекомендации с ICE-приоритизацией",
        chunk_split.data_slide_count, chunk_split.chunk_count, recap
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

// Auto-save (.md → .docx/.pdf/.xlsx) suppressed for all slash-commands.
// Slash-commands produce their own exports; .md auto-save just duplicates chat content.

#[tauri::command]
async fn send_message(
    cabinet_id: String,
    message: String,
    suppress_export: Option<bool>,
    state: tauri::State<'_, Arc<AppState>>,
    app_handle: tauri::AppHandle,
) -> Result<(), String> {
    let msg_preview = if message.len() > 80 { &message[..80] } else { &message };
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

    // PPTX Pipeline: preprocess the FIRST (largest) PPTX file for media-analyst cabinet
    let is_file_command = message.trim().starts_with('/');
    let mut pptx_filename: Option<String> = None;
    if cabinet_id == "media-analyst" && is_file_command {
        let inbox_dir = work_dir.join("inbox");
        if inbox_dir.exists() {
            // Find the largest PPTX file in inbox (most likely the main presentation)
            let mut pptx_files: Vec<std::path::PathBuf> = Vec::new();
            if let Ok(entries) = std::fs::read_dir(&inbox_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.extension().map_or(false, |e| e.eq_ignore_ascii_case("pptx")) {
                        pptx_files.push(path);
                    }
                }
            }
            // Sort by size descending — preprocess the largest one
            pptx_files.sort_by(|a, b| {
                let sa = a.metadata().map(|m| m.len()).unwrap_or(0);
                let sb = b.metadata().map(|m| m.len()).unwrap_or(0);
                sb.cmp(&sa)
            });
            if let Some(largest) = pptx_files.first() {
                pptx_filename = largest.file_name().map(|n| n.to_string_lossy().to_string());
                let output_dir = work_dir.join("preprocessed");
                if pptx_files.len() > 1 {
                    warn!("Multiple PPTX in inbox ({}), preprocessing largest: {}", pptx_files.len(), largest.display());
                }
                match commands::pptx_processor::preprocess(largest, &output_dir) {
                    Ok(slides_json) => {
                        info!("PPTX preprocessed for media-analyst: {}", slides_json.display());
                    }
                    Err(e) => {
                        warn!("PPTX preprocess failed (non-critical): {e}");
                        // Notify frontend so user knows preprocessed data won't be available
                        let _ = app_handle.emit(
                            &format!("claude-stream-{cabinet_id}"),
                            serde_json::json!({
                                "type": "status",
                                "message": "Предобработка PPTX не удалась — анализ продолжится без структурированных данных из графиков"
                            }).to_string(),
                        );
                    }
                }
            }
        }
    }

    // Multi-phase pipeline for large presentations (>15 data slides)
    let is_analytics = message.trim().starts_with("/analytics") || message.trim().starts_with("/batch-analytics");
    if cabinet_id == "media-analyst" && is_analytics {
        let slides_json_path = work_dir.join("preprocessed").join("slides.json");
        if slides_json_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&slides_json_path) {
                if let Ok(slides) = serde_json::from_str::<Vec<serde_json::Value>>(&content) {
                    let data_count = slides.iter().filter(|s| s["type"] == "data").count();
                    if data_count > 15 {
                        info!("Large PPTX detected: {data_count} data slides → multi-phase pipeline");
                        let overview = commands::pptx_processor::generate_overview(&slides);
                        let preprocessed_dir = work_dir.join("preprocessed");
                        // 80KB per chunk — prompt piped via temp file, no cmd line limit
                                match commands::pptx_processor::split_into_chunks(&slides, &preprocessed_dir, 80_000) {
                            Ok(chunk_split) => {
                                let pipeline_result = run_analytics_pipeline(
                                    &work_dir, &overview, &chunk_split,
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

                                        // Sync exports + notify
                                        let _ = state.session_manager.sync_exports(&cabinet_id);
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

    // Use --resume with stored session ID for conversation continuity
    let resume_session_id = state.session_manager.get_claude_session_id(&cabinet_id);
    let is_continuation = state.session_manager.should_continue(&cabinet_id);
    debug!("Claude session resume_id={}, continuation={is_continuation}, work_dir={}",
        resume_session_id.as_deref().unwrap_or("none"), work_dir.display());

    let max_retries = 2u32;
    let mut attempt = 0u32;
    let mut use_resume = resume_session_id.clone();
    let mut last_response_text = String::new();
    loop {
        // On retry, don't use --resume (start fresh)
        let resume_for_attempt = if attempt == 0 { use_resume.clone() } else { None };

        let result = claude::run_claude(
            &work_dir,
            &message,
            app_handle.clone(),
            cabinet_id.clone(),
            resume_for_attempt,
            state.active_pids.clone(),
            suppress_export.unwrap_or(false) || message.trim().starts_with('/'),
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
            Err(e) if use_resume.is_some() && attempt == 0 => {
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
    if cabinet_id == "media-analyst" && pptx_filename.is_some() && is_analytics {
        let exports_dir = work_dir.join("exports");
        let preprocessed_dir = work_dir.join("preprocessed");
        let response_md = last_response_text.clone();
        if !response_md.is_empty() {
            // Split response into slide notes and synthesis (Executive Summary, blocks, bridges, recommendations)
            let (notes_md, synthesis_md) = commands::pptx_processor::split_response_notes_and_synthesis(&response_md);
            let notes = commands::pptx_processor::parse_response_to_notes(&notes_md);
            if !notes.is_empty() {
                let fname = pptx_filename.as_ref().unwrap();
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
                    // Generate DOCX — with synthesis prefix if present
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
                    }
                }
            } else {
                info!("Auto-postprocess: no slide sections found in response, skipping PPTX/DOCX generation");
            }
        }
    }

    // Sync workspace exports → Desktop after Claude finishes
    state.session_manager
        .sync_exports(&cabinet_id)
        .map_err(|e| e.to_string())?;

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
fn cancel_claude(cabinet_id: String, state: tauri::State<'_, Arc<AppState>>) -> Result<(), String> {
    let pid = state.active_pids.lock().unwrap_or_else(|e| e.into_inner()).get(&cabinet_id).copied();

    if let Some(pid) = pid {
        info!("Killing Claude process PID={pid} for cabinet={cabinet_id}");
        #[cfg(windows)]
        std::process::Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
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
fn get_cabinet_commands(cabinet_id: String) -> Vec<cabinet::CabinetCommand> {
    cabinet::get_commands_for_cabinet(&cabinet_id)
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
    // explorer /select requires the full path without extra escaping.
    // Use cmd /C with the full command string to handle Cyrillic/spaces correctly.
    let select_path = file_path.to_string_lossy();
    std::process::Command::new("cmd")
        .args(["/C", &format!("explorer /select,\"{}\"", select_path)])
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
fn save_chat_message(cabinet_id: String, role: String, content: String, ts: f64) -> Result<(), String> {
    session::history::save_message(
        &cabinet_id,
        session::history::ChatHistoryMessage { role, content, ts },
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
    let resource_path = app_handle
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("help")
        .join(format!("{}.html", cabinet_id));

    if !resource_path.exists() {
        return Err(format!("Help file not found for cabinet: {}", cabinet_id));
    }

    let path_str = resource_path.to_string_lossy().to_string();
    tauri_plugin_opener::open_path(&path_str, None::<&str>).map_err(|e| e.to_string())
}

#[tauri::command]
fn open_user_guide(app_handle: tauri::AppHandle) -> Result<(), String> {
    let resource_path = app_handle
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("help")
        .join("user-guide.html");

    // In dev mode resource_dir points to target/debug, so fall back to src-tauri/help/
    let path = if resource_path.exists() {
        resource_path
    } else {
        let dev_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("help")
            .join("user-guide.html");
        if dev_path.exists() {
            dev_path
        } else {
            return Err(format!("Файл инструкции не найден: {}", resource_path.display()));
        }
    };

    let path_str = path.to_string_lossy().to_string();
    tauri_plugin_opener::open_path(&path_str, None::<&str>).map_err(|e| e.to_string())
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

    // Filter cabinets by license (in dev mode — show all)
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
    with_mtime.sort_by(|a, b| b.0.cmp(&a.0));
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

    // No valid license — return empty (show nothing)
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
fn export_logs() -> Result<String, String> {
    let app_data = std::env::var("APPDATA").map_err(|_| "APPDATA environment variable is not set".to_string())?;
    let log_dir = std::path::PathBuf::from(&app_data)
        .join("com.rosst.ai-agency")
        .join("logs");
    Ok(log_dir.to_string_lossy().to_string())
}

#[tauri::command]
fn open_logs_folder() -> Result<(), String> {
    let path = export_logs()?;
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
async fn download_update(url: String, checksum: String, app: tauri::AppHandle) -> Result<String, String> {
    let path = updater::download_update(&url, &app)
        .await
        .map_err(|e| e.to_string())?;

    updater::verify_checksum(&path, &checksum)
        .map_err(|e| e.to_string())?;

    Ok(path.to_string_lossy().to_string())
}

#[tauri::command]
fn apply_update(installer_path: String) -> Result<(), String> {
    updater::apply_update(std::path::Path::new(&installer_path))
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
                            let source = std::path::PathBuf::from(&dev_root).join(&folder);
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
                    let claude_result = claude::run_claude(
                        &work_dir,
                        &msg,
                        app.clone(),
                        cabinet_id.clone(),
                        resume,
                        state.active_pids.clone(),
                        false,
                    )
                    .await;
                    if let Err(e) = claude_result {
                        let err = e.to_string();
                        emit_wf_status(&app, &exec_id, id, "error", Some(&err));
                        return Err(err);
                    }

                    let _ = state.session_manager.sync_exports(cabinet_id);
                    let _ = state.session_manager.auto_route_artifacts(cabinet_id);

                    // Pipeline: persist exports + summarize + forward to next step
                    if let Some(ref chain) = context_chain {
                        if let Some(work_dir) = state.session_manager.get_work_dir(cabinet_id) {
                            let exports_dir = work_dir.join("exports");
                            let mut chain_lock = chain.lock().unwrap();
                            let _files = commands::campaign::persist_step_exports(
                                &chain_lock.campaign_dir, id, &exports_dir,
                            );
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

// Econometrica sidecar lifecycle is managed by econ_sidecar.rs module.
// start/stop called from build_app() setup hook and on_window_event respectively.

#[tauri::command]
async fn econ_sidecar_wait_ready() -> bool {
    econ_sidecar::wait_for_sidecar_ready().await
}

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
    match std::process::Command::new(python)
        .arg("server.py")
        .current_dir(&rag_dir)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
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
        match std::process::Command::new(&exe_path)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
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
    match std::process::Command::new(python)
        .arg("server.py")
        .current_dir(&parser_dir)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
    {
        Ok(child) => {
            info!("Parser server started via python (PID={})", child.id());
            let lock = PARSER_PROCESS.get_or_init(|| Mutex::new(None));
            *lock.lock().unwrap() = Some(child);
        }
        Err(e) => warn!("Failed to start Parser server: {e}"),
    }
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
    });

    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .max_file_size(5_000_000) // 5 MB
                .rotation_strategy(tauri_plugin_log::RotationStrategy::KeepOne)
                .build(),
        )
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(state.clone())
        .setup(|app| {
            // Start Econometrica Python sidecar on app launch
            if commands::online_auth::is_econometrica() {
                let app_handle = app.handle().clone();
                econ_sidecar::start_sidecar(&app_handle);
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_cabinets,
            get_license_status,
            import_license,
            check_online_auth,
            send_heartbeat,
            get_instance_id,
            check_content_update,
            update_content,
            get_local_content_version,
            get_machine_id,
            get_full_machine_hash,
            get_raw_fingerprint,
            open_cabinet,
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
            preview_export_file,
            cancel_claude,
            pptx_preprocess,
            pptx_postprocess,
            save_chat_message,
            load_chat_history,
            clear_chat_history,
            get_usage_metrics,
            reset_metrics,
            rate_response,
            get_cabinet_ratings,
            copy_export_to_inbox,
            list_recent_exports,
            get_cabinet_path,
            set_cabinet_path,
            reset_cabinet_path,
            list_vault_status,
            export_logs,
            open_logs_folder,
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
            // Econometrica: project management
            commands::project::project_list,
            commands::project::project_create,
            commands::project::project_get,
            commands::project::project_update,
            commands::project::project_delete,
            commands::project::project_upload_data,
            commands::project::project_get_dir,
            commands::project::project_activate,
            commands::project::project_get_active,
            commands::project::project_stats,
            // Econometrica: sidecar lifecycle + compute proxy
            econ_sidecar_wait_ready,
            commands::econometrica::econ_health,
            commands::econometrica::econ_validate,
            commands::econometrica::econ_train,
            commands::econometrica::econ_decompose,
            commands::econometrica::econ_optimize,
            commands::econometrica::econ_scenario,
            commands::econometrica::econ_compare,
            commands::econometrica::econ_awareness_forecast,
            commands::econometrica::econ_awareness_sales,
            commands::econometrica::econ_chart,
            commands::econometrica::econ_data_preview,
        ])
        .on_window_event(move |window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<Arc<AppState>>();
                let _ = state.session_manager.close_all();
                // Idempotent shutdown — safe to call even if never started
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
    // Fix interrupted pipelines from previous session
    commands::campaign::fix_interrupted_campaigns();

    // FIX BUG-2: Auto-start RAG/Parser sidecars for Creative Hub
    if online_auth::is_creative_hub() {
        start_rag_server();
        start_parser_server();
    }

    // Econometrica sidecar is now started in build_app().setup() with app_handle context.

    match build_app() {
        Ok(()) => {}
        Err(e) => {
            let err_str = e.to_string();

            // WebView2 initialization failure — auto-clean cache and retry
            if err_str.contains("WebView2") || err_str.contains("0x8007139F") {
                clear_webview_cache();

                // Retry once after cache cleanup
                match build_app() {
                    Ok(()) => return,
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
                        show_error_dialog("Aurora AI Agency — Ошибка запуска", &msg);
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
                show_error_dialog("Aurora AI Agency — Ошибка запуска", &msg);
            }
        }
    }
}
