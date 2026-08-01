// Локальная редакция (152-ФЗ, сборка без feature `cloud_advisors`): cloud-only spawn-машинерия
// (run_claude_inner и приватные хелперы) недостижима — run_claude/run_claude_pipeline делают
// ранний bail. Глушим dead_code ТОЛЬКО для этой конфигурации; egress-гард — на входных функциях.
#![cfg_attr(not(feature = "cloud_advisors"), allow(dead_code))]

use anyhow::{Context, Result};
use log::{debug, error, info, warn};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use crate::errors::{coded, coded_err, ErrorCode};

/// A message in the Claude conversation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

/// Classified error types from Claude CLI stderr.
#[derive(Debug, Clone, PartialEq)]
pub enum ClaudeError {
    RateLimit,
    Overloaded,
    AuthError,
    NetworkError,
    Unknown(String),
}

impl ClaudeError {
    /// Whether this error type is worth retrying.
    pub fn is_retryable(&self) -> bool {
        matches!(self, ClaudeError::RateLimit | ClaudeError::Overloaded | ClaudeError::NetworkError)
    }
}

/// Classify a stderr line into a known error category.
pub fn classify_stderr(line: &str) -> Option<ClaudeError> {
    let lower = line.to_lowercase();

    if lower.contains("rate limit") || lower.contains("rate_limit") || lower.contains("429") {
        return Some(ClaudeError::RateLimit);
    }
    if lower.contains("overloaded") || lower.contains("529") || lower.contains("capacity") {
        return Some(ClaudeError::Overloaded);
    }
    if lower.contains("auth") || lower.contains("unauthorized") || lower.contains("401")
        || lower.contains("api key") || lower.contains("invalid key")
    {
        return Some(ClaudeError::AuthError);
    }
    if lower.contains("network") || lower.contains("econnrefused") || lower.contains("enotfound")
        || lower.contains("timeout") || lower.contains("dns")
    {
        return Some(ClaudeError::NetworkError);
    }
    if lower.contains("error") || lower.contains("failed") {
        return Some(ClaudeError::Unknown(line.to_string()));
    }

    None
}

/// Return a user-facing Russian message for a classified error (with error code).
pub fn user_message(err: &ClaudeError) -> String {
    match err {
        ClaudeError::RateLimit => coded(ErrorCode::CL004, "Превышен лимит запросов. Повторная попытка..."),
        ClaudeError::Overloaded => coded(ErrorCode::CL005, "Сервер перегружен. Повторная попытка..."),
        ClaudeError::AuthError => coded(ErrorCode::CL006, "Ошибка авторизации. Проверьте API-ключ."),
        ClaudeError::NetworkError => coded(ErrorCode::CL007, "Ошибка сети. Проверьте подключение к интернету."),
        ClaudeError::Unknown(msg) => {
            if msg.is_empty() { "[CL-008] Неизвестная ошибка Claude CLI".to_string() } else { msg.clone() }
        }
    }
}

/// Скомпилирована ли облачная редакция (кабинеты-советники на Anthropic, Claude egress).
/// Локальная редакция (152-ФЗ) собирается без feature `cloud_advisors` → `run_claude` и
/// `run_claude_pipeline` делают ранний bail ДО спавна Claude CLI; egress к Anthropic
/// статически недостижим (единственный путь спавна — `run_claude_inner` — за этим гейтом).
pub const CLOUD_ADVISORS_ENABLED: bool = cfg!(feature = "cloud_advisors");

/// Defense-in-depth: запретить egress к Anthropic, пока пользователь не дал согласие на
/// облачную обработку. Блокирующий экран согласия — на фронте; это бэкенд-страховка на
/// случай обхода UI. Тот же чок-поинт, что и egress-гард локальной редакции (run_claude*).
#[cfg(feature = "cloud_advisors")]
fn ensure_cloud_consent(app_handle: &tauri::AppHandle) -> Result<()> {
    let config_dir = app_handle
        .path()
        .app_config_dir()
        .map_err(|e| anyhow::anyhow!("app_config_dir: {e}"))?;
    if crate::commands::user_config::cloud_consent_required(&config_dir) {
        anyhow::bail!("[CL-CONSENT] Требуется согласие на облачную обработку перед использованием кабинетов-советников");
    }
    Ok(())
}

/// Defense-in-depth (runtime): запретить egress, если пользователь включил режим
/// «только локально» (данные не уходят). Тот же egress-чок-поинт, что и согласие.
/// Одна сборка, два режима: тумблер в Настройках пишет `local_only` в user_config.
#[cfg(feature = "cloud_advisors")]
fn ensure_not_local_only(app_handle: &tauri::AppHandle) -> Result<()> {
    let config_dir = app_handle
        .path()
        .app_config_dir()
        .map_err(|e| anyhow::anyhow!("app_config_dir: {e}"))?;
    if crate::commands::user_config::local_only_enabled(&config_dir) {
        anyhow::bail!("[CL-LOCAL-ONLY] Включён режим «только локально» — облачный ИИ отключён, данные не уходят на серверы");
    }
    Ok(())
}

/// Spawn Claude Code CLI and stream output via Tauri events.
/// Returns (session_id, response_text) - session ID for --resume and full response text.
#[allow(clippy::too_many_arguments)]
pub async fn run_claude(
    work_dir: &Path,
    prompt: &str,
    app_handle: tauri::AppHandle,
    cabinet_id: String,
    resume_session_id: Option<String>,
    active_pids: Arc<Mutex<HashMap<String, u32>>>,
    suppress_export: bool,
    model: Option<String>,
) -> Result<(Option<String>, String)> {
    #[cfg(not(feature = "cloud_advisors"))]
    {
        let _ = (work_dir, prompt, app_handle, cabinet_id, resume_session_id, active_pids, suppress_export, model);
        anyhow::bail!("[CL-LOCAL] Облачные кабинеты-советники отключены в локальной редакции (0 Claude egress)");
    }
    #[cfg(feature = "cloud_advisors")]
    {
        ensure_not_local_only(&app_handle)?;
        ensure_cloud_consent(&app_handle)?;

        #[cfg(feature = "thin")]
        {
            // Тонкая версия: исполнение кабинета — SSH-gateway на узле Б, не локальный
            // Claude CLI. Гейты выше (local-only/consent) сохранены — данные всё равно
            // уходят на сервер. active_pids/model — часть локального CLI-мира, gateway
            // не спавнит процесс и не выбирает модель клиентской командой.
            // Модель теперь доезжает до сервера: прежде тонкая поставка считала всё
            // тем, что решит сервер, и работала слабее полной незаметно для человека.
            let _ = active_pids;
            let (sid, response_text) = crate::commands::gateway_executor::run_claude_gateway(
                work_dir, prompt, app_handle, cabinet_id, resume_session_id, suppress_export, model,
            ).await?;
            Ok((sid, response_text))
        }
        #[cfg(not(feature = "thin"))]
        {
            let (sid, response_text) = run_claude_inner(work_dir, prompt, app_handle, cabinet_id, resume_session_id, active_pids, false, suppress_export, model).await?;
            Ok((sid, response_text))
        }
    }
}

/// Run Claude for pipeline phase: suppress claude-done and exports, return (session_id, response_text).
pub async fn run_claude_pipeline(
    work_dir: &Path,
    prompt: &str,
    app_handle: tauri::AppHandle,
    cabinet_id: String,
    resume_session_id: Option<String>,
    active_pids: Arc<Mutex<HashMap<String, u32>>>,
) -> Result<(Option<String>, String)> {
    #[cfg(not(feature = "cloud_advisors"))]
    {
        let _ = (work_dir, prompt, app_handle, cabinet_id, resume_session_id, active_pids);
        anyhow::bail!("[CL-LOCAL] Облачные кабинеты-советники отключены в локальной редакции (0 Claude egress)");
    }
    #[cfg(feature = "cloud_advisors")]
    {
        ensure_not_local_only(&app_handle)?;
        ensure_cloud_consent(&app_handle)?;

        #[cfg(feature = "thin")]
        {
            // Pipeline phases always suppress export/done - final output is built by
            // post-processor. Зеркалит suppress_done=true, suppress_export=true CLI-пути.
            let _ = active_pids;
            let (sid, response_text) = crate::commands::gateway_executor::run_claude_pipeline_gateway(
                work_dir, prompt, app_handle, cabinet_id, resume_session_id,
            ).await?;
            Ok((sid, response_text))
        }
        #[cfg(not(feature = "thin"))]
        {
            // Pipeline phases always suppress export - final output is built by post-processor
            let (sid, response_text) = run_claude_inner(work_dir, prompt, app_handle, cabinet_id, resume_session_id, active_pids, true, true, None).await?;
            Ok((sid, response_text))
        }
    }
}

/// Изолированный CLAUDE_CONFIG_DIR для кабинетных сессий (V66/INV-92, вариант A).
/// Перенаправляет user-level слой claude CLI (settings/hooks/skills/plugins/MCP/sessions/credentials)
/// в отдельную папку → операторские/клиентские hooks/skills/MCP НЕ протекают в кабинет.
/// Project-уровень кабинета (work_dir/CLAUDE.md барьер+scope) СОХРАНЯЕТСЯ (грузится из cwd, CONFIG_DIR его не трогает).
/// Используется только из `run_claude_inner`, которая при feature `thin` недостижима
/// (gateway_executor заменяет её) — глушим dead_code точечно для этой конфигурации.
#[cfg_attr(feature = "thin", allow(dead_code))]
fn isolated_claude_config_dir(app_handle: &tauri::AppHandle) -> Option<std::path::PathBuf> {
    let iso = app_handle.path().app_local_data_dir().ok()?.join("claude-runtime");
    if let Err(e) = std::fs::create_dir_all(&iso) {
        warn!("V66: не удалось создать изолированный CLAUDE_CONFIG_DIR ({}): {e}", iso.display());
        return None;
    }
    let home = match app_handle.path().home_dir() {
        Ok(h) => h,
        Err(e) => {
            warn!("V66: home_dir недоступен, изоляция отменена (откат к дефолту ~/.claude): {e}");
            return None;
        }
    };
    {
        let src = home.join(".claude").join(".credentials.json");
        if src.exists() {
            let dst = iso.join(".credentials.json");
            let src_newer = match (
                src.metadata().and_then(|m| m.modified()),
                dst.metadata().and_then(|m| m.modified()),
            ) {
                (Ok(s), Ok(d)) => s > d,
                _ => !dst.exists(),
            };
            if !dst.exists() || src_newer {
                // Атомарная замена: temp + rename (rename атомарен на одном томе).
                let tmp = iso.join(".credentials.json.tmp");
                match std::fs::copy(&src, &tmp) {
                    Ok(_) => {
                        if let Err(e) = std::fs::rename(&tmp, &dst) {
                            warn!("V66: не удалось атомарно заменить OAuth credentials: {e}");
                            let _ = std::fs::remove_file(&tmp);
                        }
                    }
                    Err(e) => {
                        warn!("V66: не удалось перенести OAuth credentials в изоляцию: {e}");
                        let _ = std::fs::remove_file(&tmp);
                    }
                }
            }
        }
    }
    Some(iso)
}

// При feature `thin` вызовы run_claude_inner заменены веткой gateway_executor
// (см. run_claude/run_claude_pipeline выше) — функция становится недостижимой
// в этой конфигурации; глушим dead_code точечно, не трогая остальной модуль.
#[cfg_attr(feature = "thin", allow(dead_code))]
#[allow(clippy::too_many_arguments)]
async fn run_claude_inner(
    work_dir: &Path,
    prompt: &str,
    app_handle: tauri::AppHandle,
    cabinet_id: String,
    resume_session_id: Option<String>,
    active_pids: Arc<Mutex<HashMap<String, u32>>>,
    suppress_done: bool,
    suppress_export: bool,
    model: Option<String>,
) -> Result<(Option<String>, String)> {
    let claude_path = find_claude_binary()?;
    info!("Launching Claude CLI: {claude_path}, cabinet={cabinet_id}, resume={}", resume_session_id.as_deref().unwrap_or("none"));

    let mut args = vec![
        "--print", "--output-format", "stream-json",
        // Vault workspace is an isolated temp dir with pre-approved CLAUDE.md tool allowlists.
        // Permission prompts would block the non-interactive process, so we skip them.
        "--verbose", "--dangerously-skip-permissions",
    ];
    // Use --resume with explicit session ID (reliable) instead of --continue (fragile in --print mode)
    let resume_id_owned: String;
    if let Some(ref sid) = resume_session_id {
        // Validate session_id format: alphanumeric + _ + -, max 100 chars
        if sid.len() <= 100 && sid.chars().all(|c| c.is_alphanumeric() || c == '_' || c == '-') {
            resume_id_owned = sid.clone();
            args.push("--resume");
            args.push(&resume_id_owned);
        } else {
            log::warn!("Invalid session_id format (len={}, skipping --resume)", sid.len());
        }
    }
    // Model selection from user config
    let model_id_owned: String;
    if let Some(ref m) = model {
        // Передаём CLI-алиас, а не pinned snapshot-id: alias резолвится в АКТУАЛЬНУЮ
        // версию модели в момент запуска → продукт авто-подхватывает новые поколения
        // (opus/sonnet/haiku) без правки кода. Принцип: всегда latest любой модели.
        model_id_owned = match m.as_str() {
            "opus" => "opus".to_string(),
            "haiku" => "haiku".to_string(),
            _ => "sonnet".to_string(),
        };
        args.push("--model");
        args.push(&model_id_owned);
    }
    // Нажим (effort): из user_config (low|medium|high|xhigh|max), дефолт medium.
    // Применяется ко ВСЕМ вызовам модели. Раньше выпадашка в Настройках сохранялась,
    // но --effort не доходил до CLI (мёртвый контрол) — теперь дотянут. Whitelist
    // защищает от мусора в конфиге.
    let effort_owned: String = app_handle
        .path()
        .app_config_dir()
        .ok()
        .and_then(|d| crate::commands::user_config::load(&d).model_effort)
        .filter(|e| matches!(e.as_str(), "low" | "medium" | "high" | "xhigh" | "max"))
        .unwrap_or_else(|| "medium".to_string());
    args.push("--effort");
    args.push(&effort_owned);
    // Always write prompt to temp file and pipe via stdin.
    // Reasons: (1) Windows cmd line limit = 32767 chars, slides.json can be 100KB+
    // (2) cmd /C with Cyrillic args corrupts on cp1251 Windows
    // (3) stdin pipe is the most reliable cross-platform approach
    let prompt_file = work_dir.join(".pipeline_prompt.md");
    std::fs::write(&prompt_file, prompt).context("Failed to write prompt file")?;
    args.push("-p");
    args.push("-"); // read prompt from stdin

    // On Windows, npm CLIs are .cmd scripts - must run via cmd.exe /C
    #[cfg(windows)]
    let mut cmd = {
        let mut c = Command::new("cmd");
        c.arg("/C").arg(&claude_path).args(&args);
        c
    };
    #[cfg(not(windows))]
    let mut cmd = {
        let mut c = Command::new(&claude_path);
        c.args(&args);
        c
    };

    cmd.current_dir(work_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .stdin(Stdio::piped()) // pipe prompt from file via stdin
        .env_remove("CLAUDECODE")
        .env_remove("ANTHROPIC_API_KEY") // Force OAuth (subscription) instead of API credits
        .env_remove("CLAUDE_CONFIG_DIR");

    // Hide console window on Windows
    #[cfg(windows)]
    {
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    // CPD-15 / V66: изолировать user-слой оператора (~/.claude) от кабинета клиента.
    if let Some(iso) = isolated_claude_config_dir(&app_handle) {
        cmd.env("CLAUDE_CONFIG_DIR", &iso);
    }

    let mut child = cmd.spawn()
        .with_context(|| coded(ErrorCode::CL002, &format!("Failed to launch Claude CLI: {}", claude_path)))?;

    let pid = child.id();
    debug!("Claude process spawned (pid={:?})", pid);
    if let Some(pid) = pid {
        active_pids.lock().unwrap_or_else(|e| e.into_inner()).insert(cabinet_id.clone(), pid);
    }

    // Feed prompt via stdin, then close (so Claude knows input is done)
    if let Some(mut stdin) = child.stdin.take() {
        let prompt_data = std::fs::read(&prompt_file).unwrap_or_default();
        tokio::spawn(async move {
            use tokio::io::AsyncWriteExt;
            let _ = stdin.write_all(&prompt_data).await;
            let _ = stdin.shutdown().await;
        });
    }

    let stdout = child.stdout.take().context(coded(ErrorCode::CL003, "Failed to capture stdout"))?;
    let stderr = child.stderr.take().context(coded(ErrorCode::CL003, "Failed to capture stderr"))?;

    let reader = BufReader::new(stdout);
    let mut lines = reader.lines();

    // Stream stderr in background - classify errors, log warnings, forward to frontend
    let stderr_handle = app_handle.clone();
    let stderr_cabinet_id = cabinet_id.clone();
    let classified_errors: Arc<Mutex<Vec<ClaudeError>>> = Arc::new(Mutex::new(Vec::new()));
    let classified_errors_clone = classified_errors.clone();
    let stderr_task = tokio::spawn(async move {
        let stderr_reader = BufReader::new(stderr);
        let mut stderr_lines = stderr_reader.lines();
        while let Some(line) = stderr_lines.next_line().await.unwrap_or(None) {
            if !line.trim().is_empty() {
                warn!("[claude stderr / {stderr_cabinet_id}] {line}");

                let classified = classify_stderr(&line);
                let message = if let Some(ref err) = classified {
                    classified_errors_clone.lock().unwrap_or_else(|e| e.into_inner()).push(err.clone());
                    user_message(err)
                } else {
                    line.clone()
                };

                let error_json = serde_json::json!({
                    "type": "error",
                    "message": message
                });
                let _ = stderr_handle.emit(
                    &format!("claude-stream-{stderr_cabinet_id}"),
                    error_json.to_string(),
                );
            }
        }
    });

    // Accumulate response text for auto-save
    let mut delta_text = String::new();
    let mut result_text: Option<String> = None;
    let mut captured_session_id: Option<String> = None;
    let mut line_count = 0usize;
    let mut timed_out = false;

    // 30-minute timeout for the entire Claude execution
    let stream_future = async {
        while let Some(line) = lines.next_line().await? {
            if line.trim().is_empty() {
                continue;
            }
            line_count += 1;

            // Parse JSON stream to extract text for auto-save and session_id for --resume
            if let Ok(json) = serde_json::from_str::<serde_json::Value>(&line) {
                // Capture session_id from init message for future --resume
                if json["type"] == "system" && json["subtype"] == "init" {
                    if let Some(sid) = json.get("session_id")
                        .or_else(|| json.get("sessionId"))
                        .and_then(|v| v.as_str())
                    {
                        info!("Captured Claude session_id: {sid}");
                        captured_session_id = Some(sid.to_string());
                    }
                }
                if json["type"] == "content_block_delta" {
                    if let Some(text) = json["delta"]["text"].as_str() {
                        delta_text.push_str(text);
                    }
                }
                if json["type"] == "result" {
                    if let Some(r) = json["result"].as_str() {
                        if !r.trim().is_empty() {
                            result_text = Some(r.to_string());
                        }
                    }
                }
            }

            let _ = app_handle.emit(
                &format!("claude-stream-{cabinet_id}"),
                line,
            );
        }
        Ok::<(), anyhow::Error>(())
    };

    let timeout_duration = std::time::Duration::from_secs(30 * 60);
    if tokio::time::timeout(timeout_duration, stream_future).await.is_err() {
        timed_out = true;
        warn!("Claude process timed out after 30 minutes [{cabinet_id}]");
        // Kill the process on timeout
        if let Some(pid) = active_pids.lock().unwrap_or_else(|e| e.into_inner()).get(&cabinet_id).copied() {
            #[cfg(windows)]
            { let _ = std::process::Command::new("taskkill").args(["/F", "/T", "/PID", &pid.to_string()]).creation_flags(0x08000000).spawn(); }
            #[cfg(not(windows))]
            { let _ = std::process::Command::new("kill").args(["-9", &pid.to_string()]).spawn(); }
        }
        let timeout_msg = coded(ErrorCode::CL008, "Превышено время выполнения (30 минут). Процесс остановлен.");
        let _ = app_handle.emit(
            &format!("claude-stream-{cabinet_id}"),
            serde_json::json!({ "type": "error", "message": timeout_msg }).to_string(),
        );
    }

    let _ = stderr_task.await;
    let status = child.wait().await?;
    active_pids.lock().unwrap_or_else(|e| e.into_inner()).remove(&cabinet_id);
    let exit_code = if timed_out { -2 } else { status.code().unwrap_or(-1) };
    info!("Claude done [{cabinet_id}]: exit={exit_code}, lines={line_count}, timed_out={timed_out}");

    // Check for retryable errors
    let errors = classified_errors.lock().unwrap_or_else(|e| e.into_inner());
    let has_retryable = errors.iter().any(|e| e.is_retryable());
    drop(errors);

    // Retryable errors: bail BEFORE emitting claude-done.
    // The retry loop in send_message will call run_claude again.
    // Emitting claude-done here would cause the frontend to save partial/duplicate responses.
    if has_retryable && exit_code != 0 {
        // Auto-save partial response before bailing (for debugging), unless suppressed
        if !suppress_export {
            let partial_text = result_text.unwrap_or(delta_text);
            if !partial_text.trim().is_empty() {
                let slug = extract_command_slug(prompt);
                let timestamp = chrono::Local::now().format("%Y%m%d-%H%M%S");
                let filename = format!("{}-{}-partial.md", slug, timestamp);
                let exports_dir = work_dir.join("exports");
                let _ = std::fs::create_dir_all(&exports_dir);
                let _ = std::fs::write(exports_dir.join(&filename), &partial_text);
            }
        }
        anyhow::bail!("retryable_error");
    }

    if !suppress_done {
        let _ = app_handle.emit(
            &format!("claude-done-{cabinet_id}"),
            serde_json::json!({ "exit_code": exit_code }),
        );
    }

    // Auto-save response to exports/ (including partial results on timeout)
    // Skip saving for auto-continue intermediate responses (suppress_export=true)
    let final_text = result_text.unwrap_or(delta_text);
    if !suppress_export {
        auto_save_response(&app_handle, work_dir, &cabinet_id, prompt, &final_text, timed_out);
    } else {
        debug!("Skipped auto-save for auto-continue response [{cabinet_id}]");
    }

    Ok((captured_session_id, final_text))
}

/// Сохранить финальный текст ответа в exports/ (+ конвертации docx/pdf/xlsx + событие
/// exports-updated). Общий хелпер: вызывается из `run_claude_inner` (локальный Claude CLI)
/// и из `gateway_executor` (feature `thin`, SSH-транспорт) — поведение автосохранения
/// идентично независимо от того, ЧЕМ исполнен кабинет. Ничего не делает при пустом тексте
/// (зеркалит прежнюю проверку `!final_text.trim().is_empty()`).
pub(crate) fn auto_save_response(
    app_handle: &tauri::AppHandle,
    work_dir: &Path,
    cabinet_id: &str,
    prompt: &str,
    final_text: &str,
    partial_suffix: bool,
) {
    if final_text.trim().is_empty() {
        return;
    }
    let slug = extract_command_slug(prompt);
    let timestamp = chrono::Local::now().format("%Y%m%d-%H%M%S");
    let suffix = if partial_suffix { "-partial" } else { "" };
    let filename = format!("{}-{}{}.md", slug, timestamp, suffix);
    let exports_dir = work_dir.join("exports");
    let _ = std::fs::create_dir_all(&exports_dir);
    let export_path = exports_dir.join(&filename);

    match std::fs::write(&export_path, final_text) {
        Ok(_) => {
            info!("Auto-saved response: {}", export_path.display());
            let _ = crate::metrics::collector::record_export();
            convert_to_docx(&export_path);
            convert_to_pdf(&export_path);
            convert_to_xlsx(&export_path);
            let _ = app_handle.emit(
                &format!("exports-updated-{cabinet_id}"),
                serde_json::json!({}),
            );
        }
        Err(e) => warn!("Failed to auto-save response: {e}"),
    }
}

/// Extract a short slug from the user prompt for use in the filename.
/// "/ad-variants some extra text" → "ad-variants"
/// "some free text" → "response"
fn extract_command_slug(prompt: &str) -> String {
    let trimmed = prompt.trim();
    if let Some(rest) = trimmed.strip_prefix('/') {
        rest.split_whitespace()
            .next()
            .unwrap_or("response")
            .to_string()
    } else {
        "response".to_string()
    }
}

/// Convert a .md file to .docx using pandoc (if available).
/// Silently skips if pandoc is not installed.
fn convert_to_docx(md_path: &std::path::Path) {
    let docx_path = md_path.with_extension("docx");

    #[cfg(windows)]
    let pandoc_cmd = "pandoc";
    #[cfg(not(windows))]
    let pandoc_cmd = "pandoc";

    let mut docx_cmd = std::process::Command::new(pandoc_cmd);
    docx_cmd.args([
        md_path.to_string_lossy().as_ref(),
        "-o",
        docx_path.to_string_lossy().as_ref(),
        "--from", "markdown",
        "--to", "docx",
    ]);
    #[cfg(windows)]
    docx_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    match docx_cmd
        .output()
    {
        Ok(output) if output.status.success() => {
            info!("Converted to docx: {}", docx_path.display());
        }
        Ok(output) => {
            warn!(
                "pandoc failed: {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Err(_) => {
            debug!("pandoc not available - skipping docx conversion");
        }
    }
}

/// Convert Markdown tables in a .md file to .xlsx (if tables found).
/// Convert column index (0-based) to Excel letter (A, B, ..., Z, AA, AB...).
fn col_to_letter(col: usize) -> String {
    let mut result = String::new();
    let mut n = col;
    loop {
        result.insert(0, (b'A' + (n % 26) as u8) as char);
        if n < 26 { break; }
        n = n / 26 - 1;
    }
    result
}

fn convert_to_xlsx(md_path: &std::path::Path) {
    let content = match std::fs::read_to_string(md_path) {
        Ok(c) => c,
        Err(_) => return,
    };

    // Find markdown tables (lines with |)
    let mut tables: Vec<Vec<Vec<String>>> = Vec::new();
    let mut current_table: Vec<Vec<String>> = Vec::new();

    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('|') && trimmed.ends_with('|') {
            // Skip separator lines (|---|---|)
            if trimmed.chars().all(|c| c == '|' || c == '-' || c == ':' || c == ' ') {
                continue;
            }
            let cells: Vec<String> = trimmed
                .trim_matches('|')
                .split('|')
                .map(|s| s.trim().to_string())
                .collect();
            current_table.push(cells);
        } else if !current_table.is_empty() {
            if current_table.len() >= 2 {
                tables.push(std::mem::take(&mut current_table));
            } else {
                current_table.clear();
            }
        }
    }
    if current_table.len() >= 2 {
        tables.push(current_table);
    }

    if tables.is_empty() {
        return;
    }

    let xlsx_path = md_path.with_extension("xlsx");
    let mut workbook = rust_xlsxwriter::Workbook::new();

    for (i, table) in tables.iter().enumerate() {
        let sheet_name = if i == 0 { "Sheet1".to_string() } else { format!("Sheet{}", i + 1) };
        let worksheet = workbook.add_worksheet();
        let _ = worksheet.set_name(&sheet_name);

        let header_format = rust_xlsxwriter::Format::new()
            .set_bold()
            .set_background_color(rust_xlsxwriter::Color::RGB(0x1E1E2C))
            .set_font_color(rust_xlsxwriter::Color::RGB(0xEAEAF0))
            .set_border(rust_xlsxwriter::FormatBorder::Thin);

        let num_cols = table.first().map_or(0, |r| r.len());
        let num_data_rows = table.len().saturating_sub(1); // exclude header

        // Track which columns contain numeric data
        let mut numeric_cols: Vec<bool> = vec![false; num_cols];

        for (row_idx, row) in table.iter().enumerate() {
            for (col_idx, cell) in row.iter().enumerate() {
                if row_idx == 0 {
                    let _ = worksheet.write_string_with_format(
                        row_idx as u32,
                        col_idx as u16,
                        cell,
                        &header_format,
                    );
                } else {
                    // Try to write as number first
                    let cleaned = cell.replace(',', ".").replace(['%', ' ', '\u{a0}'], "");
                    if let Ok(num) = cleaned.parse::<f64>() {
                        let _ = worksheet.write_number(row_idx as u32, col_idx as u16, num);
                        if col_idx < numeric_cols.len() {
                            numeric_cols[col_idx] = true;
                        }
                    } else {
                        let _ = worksheet.write_string(row_idx as u32, col_idx as u16, cell);
                    }
                }
            }
        }

        // --- Freeze top row (header always visible) ---
        let _ = worksheet.set_freeze_panes(1, 0);

        // --- Auto-filter on header row ---
        if num_cols > 0 {
            let _ = worksheet.autofilter(0, 0, table.len() as u32 - 1, (num_cols - 1) as u16);
        }

        // --- Auto-fit column widths ---
        for col in 0..num_cols {
            let max_len = table.iter()
                .map(|row| row.get(col).map_or(0, |c| c.len()))
                .max()
                .unwrap_or(8);
            let width = (max_len as f64 * 1.2).clamp(8.0, 50.0);
            let _ = worksheet.set_column_width(col as u16, width);
        }

        // --- Formulas: SUM row for numeric columns (if 3+ data rows) ---
        if num_data_rows >= 3 {
            let sum_row = table.len() as u32;
            let sum_format = rust_xlsxwriter::Format::new()
                .set_bold()
                .set_border_top(rust_xlsxwriter::FormatBorder::Double);

            for (col, &is_numeric) in numeric_cols.iter().enumerate().take(num_cols) {
                if is_numeric {
                    let col_letter = col_to_letter(col);
                    let formula_str = format!("=SUM({}2:{}{})", col_letter, col_letter, table.len());
                    let formula = rust_xlsxwriter::Formula::new(&formula_str);
                    let _ = worksheet.write_formula_with_format(
                        sum_row, col as u16, &formula, &sum_format,
                    );
                } else if col == 0 {
                    let _ = worksheet.write_string_with_format(sum_row, 0, "Итого", &sum_format);
                }
            }
        }

        // --- Conditional formatting: color scale on numeric columns ---
        for (col, &is_numeric) in numeric_cols.iter().enumerate().take(num_cols) {
            if is_numeric && num_data_rows >= 2 {
                let cf = rust_xlsxwriter::ConditionalFormat3ColorScale::new()
                    .set_minimum_color(rust_xlsxwriter::Color::RGB(0xF8696B))  // red (low)
                    .set_midpoint_color(rust_xlsxwriter::Color::RGB(0xFFEB84)) // yellow (mid)
                    .set_maximum_color(rust_xlsxwriter::Color::RGB(0x63BE7B)); // green (high)
                let _ = worksheet.add_conditional_format(
                    1, col as u16,
                    num_data_rows as u32, col as u16,
                    &cf,
                );
            }
        }
    }

    match workbook.save(&xlsx_path) {
        Ok(_) => info!("Converted to xlsx: {} ({} table(s))", xlsx_path.display(), tables.len()),
        Err(e) => debug!("xlsx conversion failed: {e}"),
    }
}

/// Convert a .md file to .pdf using pandoc (if available).
/// Silently skips if pandoc is not installed or conversion fails.
fn convert_to_pdf(md_path: &std::path::Path) {
    let pdf_path = md_path.with_extension("pdf");

    let mut pdf_cmd = std::process::Command::new("pandoc");
    pdf_cmd.args([
        md_path.to_string_lossy().as_ref(),
        "-o",
        pdf_path.to_string_lossy().as_ref(),
        "--from", "markdown",
        "--to", "pdf",
        "--pdf-engine=wkhtmltopdf",
    ]);
    #[cfg(windows)]
    pdf_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    match pdf_cmd
        .output()
    {
        Ok(output) if output.status.success() => {
            info!("Converted to pdf: {}", pdf_path.display());
        }
        Ok(output) => {
            debug!(
                "pandoc pdf conversion failed (non-critical): {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Err(_) => {
            debug!("pandoc/wkhtmltopdf not available - skipping pdf conversion");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slug_from_slash_command() {
        assert_eq!(extract_command_slug("/ad-variants"), "ad-variants");
        assert_eq!(extract_command_slug("/analytics"), "analytics");
        assert_eq!(extract_command_slug("/contract-сравнить"), "contract-сравнить");
    }

    #[test]
    fn slug_from_slash_command_with_args() {
        assert_eq!(extract_command_slug("/cycle some extra text"), "cycle");
        assert_eq!(extract_command_slug("/qa check this file"), "qa");
    }

    #[test]
    fn slug_from_free_text() {
        assert_eq!(extract_command_slug("проверь этот договор"), "response");
        assert_eq!(extract_command_slug("hello world"), "response");
    }

    #[test]
    fn slug_from_empty_and_whitespace() {
        assert_eq!(extract_command_slug(""), "response");
        assert_eq!(extract_command_slug("   "), "response");
        assert_eq!(extract_command_slug("  /strategy  "), "strategy");
    }

    #[test]
    fn slug_from_bare_slash() {
        assert_eq!(extract_command_slug("/"), "response");
    }

    #[test]
    fn classify_rate_limit() {
        assert_eq!(classify_stderr("Error: rate limit exceeded"), Some(ClaudeError::RateLimit));
        assert_eq!(classify_stderr("HTTP 429 Too Many Requests"), Some(ClaudeError::RateLimit));
    }

    #[test]
    fn classify_overloaded() {
        assert_eq!(classify_stderr("API is overloaded, please retry"), Some(ClaudeError::Overloaded));
        assert_eq!(classify_stderr("HTTP 529"), Some(ClaudeError::Overloaded));
    }

    #[test]
    fn classify_auth() {
        assert_eq!(classify_stderr("Unauthorized: invalid API key"), Some(ClaudeError::AuthError));
        assert_eq!(classify_stderr("401 auth error"), Some(ClaudeError::AuthError));
    }

    #[test]
    fn classify_network() {
        assert_eq!(classify_stderr("ECONNREFUSED 127.0.0.1"), Some(ClaudeError::NetworkError));
        assert_eq!(classify_stderr("network timeout connecting to API"), Some(ClaudeError::NetworkError));
    }

    #[test]
    fn classify_none_for_normal_lines() {
        assert_eq!(classify_stderr("Processing file..."), None);
        assert_eq!(classify_stderr(""), None);
    }

    #[test]
    fn retryable_errors() {
        assert!(ClaudeError::RateLimit.is_retryable());
        assert!(ClaudeError::Overloaded.is_retryable());
        assert!(ClaudeError::NetworkError.is_retryable());
        assert!(!ClaudeError::AuthError.is_retryable());
        assert!(!ClaudeError::Unknown("test".to_string()).is_retryable());
    }
}

/// Find the Claude CLI binary and validate it's in a trusted location.
/// Используется только из `run_claude_inner` — недостижима при feature `thin`, см. там.
#[cfg_attr(feature = "thin", allow(dead_code))]
fn find_claude_binary() -> Result<String> {
    let candidates = ["claude", "claude.cmd", "claude.exe"];

    // Trusted directory prefixes (case-insensitive on Windows)
    let trusted_prefixes: Vec<String> = [
        std::env::var("APPDATA").ok(),
        std::env::var("LOCALAPPDATA").ok(),
        std::env::var("USERPROFILE").ok(),
        std::env::var("PROGRAMFILES").ok(),
        std::env::var("PROGRAMFILES(X86)").ok(),
    ]
    .into_iter()
    .flatten()
    .map(|p| p.to_lowercase())
    .collect();

    for name in &candidates {
        let mut where_cmd = std::process::Command::new("where");
        where_cmd.arg(name);
        #[cfg(windows)]
        where_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        if let Ok(output) = where_cmd.output() {
            if output.status.success() {
                let path = String::from_utf8_lossy(&output.stdout);
                if let Some(first_line) = path.lines().next() {
                    if !first_line.trim().is_empty() {
                        let resolved = first_line.trim().to_string();
                        let lower = resolved.to_lowercase();

                        if trusted_prefixes.iter().any(|prefix| lower.starts_with(prefix)) {
                            debug!("Claude binary found: {resolved}");
                            return Ok(resolved);
                        }
                        warn!("Claude binary at untrusted location: {resolved} - skipping");
                    }
                }
            }
        }
    }

    error!("Claude Code CLI not found in PATH");
    Err(coded_err(ErrorCode::CL001, "Claude Code CLI not found. Install it: npm install -g @anthropic-ai/claude-code"))
}
