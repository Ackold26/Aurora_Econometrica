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
    /// 🔴 CPD-10: исчерпана подписочная квота. Отдельно от `RateLimit` намеренно: ограничение
    /// частоты проходит само через минуты, а квота — нет, до конца расчётного окна. Свести их
    /// в одно значило бы обещать клиенту автоматический повтор, который никогда не сработает.
    UsageLimit,
    AuthError,
    NetworkError,
    Unknown(String),
}

impl ClaudeError {
    /// Whether this error type is worth retrying.
    ///
    /// 🔴 `UsageLimit` НЕ повторяется: квота не восстанавливается ожиданием в пределах запроса,
    /// и повтор лишь потратит время клиента, показав тот же отказ (эталон SA `ec6a89b`, OR `0d3f3fc`).
    pub fn is_retryable(&self) -> bool {
        matches!(self, ClaudeError::RateLimit | ClaudeError::Overloaded | ClaudeError::NetworkError)
    }
}

/// Classify a stderr line into a known error category.
pub fn classify_stderr(line: &str) -> Option<ClaudeError> {
    let lower = line.to_lowercase();

    // 🔴 CPD-10, порядок значим: квота проверяется ДО ограничения частоты. «Usage limit reached»
    // подстроку «rate limit» не содержит, но родственные формулировки поставщика меняются, и
    // ошибка отнесения здесь дороже обычного — клиенту пообещали бы автоматический повтор.
    // 🔴 Находка внешнего аудита (High): образец `limit reached` перехватывал ОБЫЧНОЕ ограничение
    // частоты — «Rate limit reached. Please retry after 60s» содержит его дословно. А поскольку
    // квота проверяется первой, повторяемая ошибка объявлялась неповторяемой, автоповтор не
    // срабатывал, и клиент читал «автоматического повтора не будет» — ложное утверждение о
    // причине (INV-50). Голое «limit reached» снято; оставлены формы, где сказано ЧЕЙ лимит.
    let mentions_rate = lower.contains("rate limit") || lower.contains("rate_limit");
    if !mentions_rate
        && (lower.contains("usage limit")
            || lower.contains("quota")
            || lower.contains("out of credits")
            || lower.contains("subscription limit"))
    {
        return Some(ClaudeError::UsageLimit);
    }
    if lower.contains("rate limit") || lower.contains("rate_limit") || lower.contains("429") {
        return Some(ClaudeError::RateLimit);
    }
    // 🔴 CPD-10: протухший вход. Формы СТРОГИЕ — голое слово «login» встречается в обычном
    // тексте (например, в разборе чужого кода), и широкий образец объявлял бы отказом входа
    // всё подряд. Негативный контроль на это есть в сторожах.
    if lower.contains("not logged in")
        || lower.contains("logged out")
        || lower.contains("claude login")
        || lower.contains("please log in")
        || lower.contains("/login")
    {
        return Some(ClaudeError::AuthError);
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
        // 🔴 CPD-10: текст честный в обе стороны — называет причину и НЕ обещает повтора,
        // потому что его не будет (is_retryable = false). Обещание «повторная попытка…»
        // здесь было бы ложным утверждением продукта о себе.
        ClaudeError::UsageLimit => coded(
            ErrorCode::CL010,
            "Исчерпан лимит подписки Claude. Работа возобновится после обновления лимита – \
             автоматического повтора не будет.",
        ),
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
        anyhow::bail!("[CL-LOCAL-ONLY] Включён режим «только локально» — облачный ИИ отключён, материалы не уходят с этой машины");
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
        // 🔴 Две РАЗНЫЕ оси, и порядок между ними не случаен (ADR-049 §4а). Сначала —
        // допустимо ли обращение к облачному ИИ вообще: локальная редакция, согласие,
        // тумблер «только локально». И лишь ВНУТРИ разрешённого решается вторая ось —
        // чей Claude Code исполняет работу. Поменять порядок значит спросить «каким
        // путём идти» там, где идти нельзя никаким.
        ensure_not_local_only(&app_handle)?;
        ensure_cloud_consent(&app_handle)?;

        // Развилка режима (ADR-049): решение принимается ВО ВРЕМЯ РАБОТЫ, не при сборке.
        // Признак `thin` отвечает лишь на вопрос «есть ли облачный путь в этом бинаре».
        let decision = crate::commands::execution_mode::resolve(&app_handle).await;
        info!(
            "Режим исполнения [{cabinet_id}]: {} ({})",
            decision.mode.human(),
            decision.source.as_str(),
        );

        #[cfg(feature = "thin")]
        if decision.mode == crate::commands::execution_mode::ExecutionMode::Cloud {
            // Исполнение кабинета — на нашем сервере, не локальный Claude CLI.
            // active_pids — часть локального мира: шлюз не спавнит процесс.
            // Модель доезжает до сервера: прежде тонкая поставка считала всё тем, что
            // решит сервер, и работала слабее полной незаметно для человека.
            let _ = &active_pids;
            let (sid, response_text) = crate::commands::gateway_executor::run_claude_gateway(
                work_dir, prompt, app_handle, cabinet_id, resume_session_id, suppress_export, model,
            ).await?;
            return Ok((sid, response_text));
        }

        // Локальный путь. 🔴 Его отказ НЕ переводит работу на шлюз — ни молча, ни
        // «разово»: человек выбрал этот режим ради того, чтобы Платформа Аврора не
        // участвовала в передаче (ADR-049 §4).
        match run_claude_inner(work_dir, prompt, app_handle, cabinet_id, resume_session_id, active_pids, false, suppress_export, model).await {
            Ok((sid, response_text)) => Ok((sid, response_text)),
            Err(e) => Err(local_failure(e)),
        }
    }
}

/// Отказ локального пути: причина остаётся дословной, к ней добавляется предложение
/// переключиться (ADR-049 §4). Заодно гасится ЛОКАЛЬНЫЙ выбор автоопределения — но не
/// явный выбор человека: тот сильнее любой отметки.
#[cfg(feature = "cloud_advisors")]
fn local_failure(error: anyhow::Error) -> anyhow::Error {
    let reason = error.to_string();
    crate::commands::execution_mode::mark_local_failed(&reason);
    anyhow::anyhow!(crate::commands::execution_mode::local_failure_text(&reason))
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

        // Фазы пайплайна идут тем же режимом, что и обычный вопрос (ADR-049): иначе одна
        // и та же работа частями уходила бы разными маршрутами — худший вид дефекта
        // «работает не в том режиме», потому что незаметен даже нам.
        let decision = crate::commands::execution_mode::resolve(&app_handle).await;
        info!(
            "Режим исполнения фазы [{cabinet_id}]: {} ({})",
            decision.mode.human(),
            decision.source.as_str(),
        );

        #[cfg(feature = "thin")]
        if decision.mode == crate::commands::execution_mode::ExecutionMode::Cloud {
            // Pipeline phases always suppress export/done - final output is built by
            // post-processor. Зеркалит suppress_done=true, suppress_export=true CLI-пути.
            let _ = &active_pids;
            let (sid, response_text) = crate::commands::gateway_executor::run_claude_pipeline_gateway(
                work_dir, prompt, app_handle, cabinet_id, resume_session_id,
            ).await?;
            return Ok((sid, response_text));
        }

        // Pipeline phases always suppress export - final output is built by post-processor
        match run_claude_inner(work_dir, prompt, app_handle, cabinet_id, resume_session_id, active_pids, true, true, None).await {
            Ok((sid, response_text)) => Ok((sid, response_text)),
            Err(e) => Err(local_failure(e)),
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

    // On Windows, npm CLIs are .cmd scripts - must run via cmd.exe /C.
    // Строку команды строит windows_cmd_command_line: путь ОТДЕЛЬНЫМ аргументом
    // ломался на именах учётных записей со знаками `&`, `^`, `(` — см. там.
    #[cfg(windows)]
    let mut cmd = {
        let mut c = Command::new("cmd");
        c.arg("/C");
        c.raw_arg(windows_cmd_command_line(&claude_path, &args));
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
        // Auto-save partial response before bailing (for debugging), unless suppressed.
        // 🔴 CPD-32, находка внешнего аудита (High): это ВТОРОЙ путь записи файла, и он писал
        // напрямую, минуя гейт содержимого. Сценарий: stderr дал повторяемую ошибку, а в буфере
        // stdout уже лежит «API Error: Connection closed» — текст отказа ложился клиенту файлом
        // ровно так же, как до починки, только с суффиксом `-partial`. Гейт обязан стоять на
        // КАЖДОМ пути записи, а не на самом заметном.
        if !suppress_export {
            let partial_text = result_text.unwrap_or(delta_text);
            match failure_notice_reason(&partial_text, prompt) {
                Some(reason) => warn!("Частичный ответ не сохранён [{cabinet_id}]: {reason}"),
                None => {
                    let slug = extract_command_slug(prompt);
                    let timestamp = chrono::Local::now().format("%Y%m%d-%H%M%S");
                    let filename = format!("{}-{}-partial.md", slug, timestamp);
                    let exports_dir = work_dir.join("exports");
                    let _ = std::fs::create_dir_all(&exports_dir);
                    let _ = std::fs::write(exports_dir.join(&filename), &partial_text);
                }
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
/// идентично независимо от того, ЧЕМ исполнен кабинет. Пустой текст и текст отказа канала файлом
/// НЕ сохраняются, но и не проглатываются: пользователь получает событие с причиной.
pub(crate) fn auto_save_response(
    app_handle: &tauri::AppHandle,
    work_dir: &Path,
    cabinet_id: &str,
    prompt: &str,
    final_text: &str,
    partial_suffix: bool,
) {
    // 🔴 Находка внешнего аудита (Medium): раньше здесь стоял ранний выход по пустоте — ДО гейта.
    // Канал, оборвавшийся до первого токена, уходил молча: ни файла, ни события, ровно тот
    // родственный дефект CPD-17 («файла нет, и никто не знает почему»), от которого гейт и
    // защищает. Пустота — частный случай «ответ не состоялся», и обрабатывается тем же путём.
    // 🔴 CPD-32: файл-результат не имеет права нести текст отказа. До правки единственным
    // условием была непустота, поэтому сообщение оборвавшегося канала сохранялось как отчёт —
    // с именем по шаблону команды, датой и признаками выполненной работы — и через неделю
    // становилось неотличимо от настоящего разбора, не открыв его. Отказ здесь ГРОМКИЙ:
    // молчаливый пропуск вернул бы нас к родственному дефекту «файла нет, и никто не знает
    // почему» (CPD-17).
    if let Some(reason) = failure_notice_reason(final_text, prompt) {
        warn!("Ответ не сохранён [{cabinet_id}]: {reason}");
        let _ = app_handle.emit(
            &format!("claude-stream-{cabinet_id}"),
            serde_json::json!({
                "type": "error",
                "message": "Ответ не дошёл целиком, файл не сохранён – повторите команду."
            })
            .to_string(),
        );
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

/// Порог, ниже которого текст не может быть содержательным ответом кабинета вместе с маркером
/// отказа. Ответы советника — развёрнутые разборы; сообщение об обрыве канала укладывается в
/// одну-две строки. Величина продуктовая, не научная, и намеренно щедрая.
const FAILURE_NOTICE_MAX_CHARS: usize = 400;

/// Потолок длины ЗАПРОСА, при котором работает исключение «маркер назван в самом вопросе».
/// Свободный вопрос человека — сотни символов; раскрытый шаблон слэш-команды — тысячи, и
/// случайная строка `Error:` внутри него не должна снимать гейт. Величина продуктовая.
const FAILURE_NOTICE_PROMPT_MAX_CHARS: usize = 2_000;

/// Маркеры отказа КАНАЛА (не содержания). Сверяются с началом текста, регистр не важен.
const FAILURE_NOTICE_MARKERS: &[&str] = &[
    "api error",
    "error:",
    "request timed out",
    "connection closed",
    "connection error",
    "stream closed",
    "fetch failed",
];

/// Символы разметки, которыми Claude CLI оборачивает начало сообщения об отказе. Срезаются
/// перед сверкой с маркерами: `**API Error**: Connection closed` — тот же отказ канала, но
/// `starts_with` о звёздочки спотыкается (находка внешнего аудита, Medium).
const MARKDOWN_LEAD_CHARS: &[char] = &['*', '_', '`', '#', '>', '~', '-', ' ', '\t'];

/// Является ли текст сообщением об отказе, а не ответом кабинета (CPD-32).
///
/// 🔴 Почему маркер И длина, а не «либо-либо». Предложение записи реестра допускало отказ по
/// одной лишь краткости, но короткий ответ бывает настоящим («Да, риск есть: пункт 4.2»), и
/// выбрасывать его — терять работу клиента. Маркер сам по себе тоже не доказательство: разбор
/// вопроса «что означает API Error 500» законно начинается этими словами, но он длинный.
/// Совпадение обоих признаков — короткий текст, начинающийся с маркера отказа канала, — не
/// оставляет места содержательному ответу.
///
/// 🔴 Третий признак — сам вопрос (находка внешнего аудита, Medium). Длина и маркер вдвоём всё
/// ещё выбрасывали настоящий короткий ответ, если пользователь спросил ПРО эту строку:
/// «переведи: Connection closed» → ответ начинается ровно маркером, укладывается в порог, и
/// клиент получал «ответ не дошёл» про дошедший ответ — ложное утверждение продукта о себе
/// (INV-50) плюс потеря работы. Если маркер есть в вопросе, ответ про него законен.
/// Плата названа честно: настоящий обрыв канала в разговоре ПРО ошибки не будет распознан и
/// ляжет файлом. Цена обратной ошибки выше — там теряется сделанная работа.
///
/// Возвращает причину для журнала, чтобы отказ можно было разобрать по следам, а не гадать.
fn failure_notice_reason(text: &str, prompt: &str) -> Option<&'static str> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Some("пустой ответ");
    }
    // Считаем символы, а не байты: у кириллицы их по два на символ, и порог в байтах
    // отрезал бы русские ответы вдвое раньше английских.
    if trimmed.chars().count() > FAILURE_NOTICE_MAX_CHARS {
        return None;
    }
    let head: String = trimmed
        .trim_start_matches(MARKDOWN_LEAD_CHARS)
        .chars()
        .take(80)
        .collect::<String>()
        .to_lowercase();
    let matched = FAILURE_NOTICE_MARKERS.iter().find(|m| head.starts_with(**m))?;
    // 🔴 Исключение действует только для КОРОТКОГО запроса — находка внешнего аудита (Medium).
    // В `run_claude` уезжает не то, что набрал клиент, а раскрытый шаблон слэш-команды целиком
    // (`resolve_slash_command`): тысячи символов инструкций. Строка `Error:` в любом шаблоне —
    // например будущее указание «если увидишь Error: …, сообщи» — снимала бы гейт для этой
    // команды навсегда и молча, возвращая CPD-32. Свободный вопрос человека в порог укладывается,
    // раскрытый шаблон — нет. Величина продуктовая, как и порог ответа, и помечена явно.
    if prompt.chars().count() <= FAILURE_NOTICE_PROMPT_MAX_CHARS
        && prompt.to_lowercase().contains(*matched)
    {
        return None;
    }
    Some("текст начинается маркером отказа канала и короче порога содержательности")
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

    /// 🔴 Сторож CPD-10 (блокирующий). До правки отказ по исчерпанной подписке и по протухшему
    /// входу не попадал ни в одну категорию, и наружу уходила СЫРАЯ английская строка CLI —
    /// отказ был подан не как отказ. Эталон линейки: SA `ec6a89b`, OR `0d3f3fc`.
    #[test]
    fn usage_limit_is_classified_and_never_retried() {
        for line in [
            "Claude usage limit reached. Try again after 3pm",
            "You have reached your quota for this billing period",
            "Error: out of credits",
        ] {
            let err = classify_stderr(line)
                .unwrap_or_else(|| panic!("отказ по квоте обязан классифицироваться: {line}"));
            assert_eq!(err, ClaudeError::UsageLimit, "строка: {line}");
            assert!(
                !err.is_retryable(),
                "квота не восстанавливается ожиданием — повтор лишь потратит время клиента"
            );
        }
    }

    /// 🔴 Порядок отнесения: квота идёт ДО ограничения частоты. Иначе клиенту пообещали бы
    /// автоматический повтор, которого не будет.
    #[test]
    fn usage_limit_wins_over_rate_limit() {
        assert_eq!(
            classify_stderr("Claude usage limit reached (429)"),
            Some(ClaudeError::UsageLimit),
            "исчерпанная подписка не имеет права быть принята за ограничение частоты"
        );
        assert_eq!(
            classify_stderr("rate limit exceeded, slow down"),
            Some(ClaudeError::RateLimit),
            "обычное ограничение частоты обязано остаться повторяемым"
        );
    }

    /// 🔴 Протухший вход — строгими формами. Негативный контроль обязателен: голое слово
    /// «login» встречается в обычном тексте, и широкий образец объявлял бы отказом входа всё
    /// подряд (требование самой записи реестра).
    #[test]
    fn stale_login_is_classified_by_strict_forms_only() {
        for line in [
            "You are not logged in. Run `claude login`",
            "Session logged out",
            "Please log in to continue",
        ] {
            assert_eq!(
                classify_stderr(line),
                Some(ClaudeError::AuthError),
                "протухший вход обязан классифицироваться: {line}"
            );
        }
        assert_ne!(
            classify_stderr("Описан порядок login в разделе README"),
            Some(ClaudeError::AuthError),
            "обычное упоминание слова «login» не имеет права считаться отказом входа"
        );
    }

    /// 🔴 Находка внешнего аудита (High): образец `limit reached` перехватывал ОБЫЧНОЕ ограничение
    /// частоты. Поскольку квота проверяется первой, повторяемая ошибка объявлялась неповторяемой,
    /// автоповтор не срабатывал, и клиент читал ложную причину.
    #[test]
    fn rate_limit_is_not_mistaken_for_a_subscription_quota() {
        for line in [
            "Rate limit reached. Please retry after 60s",
            "API rate limit reached for this organization",
        ] {
            let err = classify_stderr(line).unwrap_or_else(|| panic!("не классифицировано: {line}"));
            assert_eq!(
                err,
                ClaudeError::RateLimit,
                "ограничение частоты обязано остаться ограничением частоты: {line}"
            );
            assert!(err.is_retryable(), "иначе автоповтор не сработает и клиент прочтёт ложную причину");
        }
    }

    /// 🔴 Находка внешнего аудита (Medium): пустой ответ уходил молча — ранний выход стоял ДО
    /// гейта. Проверяется отсутствие возврата по пустоте между входом в автосохранение и гейтом.
    #[test]
    fn empty_answer_is_not_swallowed_before_the_gate() {
        let src = include_str!("claude.rs");
        let start = src.find("pub(crate) fn auto_save_response").expect("функция не найдена");
        let tail = &src[start..];
        let gate_at = tail.find("failure_notice_reason").expect("гейт не найден");
        let window = &tail[..gate_at];
        assert!(
            !window.contains("is_empty() {\n        return;"),
            "ранний выход по пустоте вернулся ДО гейта: оборвавшийся до первого токена канал снова \
             уйдёт молча — ни файла, ни события (родственный дефект CPD-17)"
        );
        assert!(
            failure_notice_reason("", "/mmm-report").is_some()
                && failure_notice_reason("   ", "/mmm-report").is_some(),
            "пустота обязана распознаваться самим гейтом, раз ранней проверки больше нет"
        );
    }

    /// Клиентский текст отказа по квоте не имеет права обещать повтор, которого не будет.
    #[test]
    fn usage_limit_message_promises_no_retry() {
        let text = user_message(&ClaudeError::UsageLimit);
        assert!(text.contains("CL-010"), "код отказа обязан быть назван: {text}");
        assert!(
            !text.contains("Повторная попытка"),
            "текст обещает автоматический повтор, которого не будет — ложное утверждение о себе: {text}"
        );
    }

    /// 🔴 Сторож CPD-32 (блокирующий, ложное утверждение продукта о себе). Эталонный случай —
    /// дословный текст из находки Legal Center 0.12.1: ответ оборвался, а продукт сохранил
    /// сообщение об обрыве как отчёт с именем по шаблону команды и датой.
    #[test]
    fn broken_channel_notice_is_not_a_result() {
        assert!(
            failure_notice_reason("API Error: Connection closed mid-response", "/mmm-report").is_some(),
            "сообщение об обрыве канала обязано быть распознано: иначе оно ляжет в папку клиента \
             файлом со всеми признаками выполненной работы"
        );
        assert!(failure_notice_reason("Error: request failed", "/mmm-report").is_some());
        assert!(failure_notice_reason("Request timed out after 600s", "/mmm-report").is_some());
        assert!(
            failure_notice_reason("   ", "/mmm-report").is_some(),
            "пустой ответ — тоже не результат"
        );
    }

    /// 🔴 Негативный контроль: короткий ответ бывает НАСТОЯЩИМ, и выбрасывать его — терять
    /// работу клиента. Без этого случая правило удовлетворялось бы отказом по одной краткости.
    #[test]
    fn short_but_real_answer_is_kept() {
        assert!(
            failure_notice_reason("Да, риск есть: пункт 4.2 договора.", "/contract").is_none(),
            "короткий содержательный ответ обязан сохраняться"
        );
        assert!(
            failure_notice_reason(
                "Вклад телевидения — 32 %, это верхняя граница правдоподобного диапазона.",
                "/mmm-decomposition"
            )
            .is_none()
        );
    }

    /// 🔴 Второй негативный контроль: маркер сам по себе не доказательство. Разбор вопроса
    /// «что означает API Error 500» законно начинается этими словами — но он длинный.
    #[test]
    fn long_explanation_starting_with_a_marker_is_kept() {
        let long_answer = format!(
            "API Error 500 — это ответ сервера, а не отказ вашего канала. {}",
            "Ниже разбор причин и порядок действий. ".repeat(12)
        );
        assert!(
            long_answer.chars().count() > FAILURE_NOTICE_MAX_CHARS,
            "фикстура обязана быть длиннее порога, иначе случай проверяет не то"
        );
        assert!(
            // 🔴 Вопрос намеренно БЕЗ маркера: иначе тест проходил бы по исключению «маркер есть
            // в вопросе» и перестал бы стеречь порог длины — сторож, написанный вместе с
            // починкой, наследует её послабление.
            failure_notice_reason(&long_answer, "/mmm-report").is_none(),
            "развёрнутый разбор не имеет права быть принят за отказ канала"
        );
    }

    /// 🔴 Порог считается в СИМВОЛАХ, не байтах: у кириллицы два байта на символ, и байтовый
    /// счёт отрезал бы русские ответы вдвое раньше английских — при этом на английских
    /// фикстурах разница не видна вовсе.
    #[test]
    fn threshold_counts_characters_not_bytes() {
        let russian = "Разбор ".repeat(40); // ~280 символов, но ~520 байт
        assert!(russian.chars().count() < FAILURE_NOTICE_MAX_CHARS);
        assert!(russian.len() > FAILURE_NOTICE_MAX_CHARS, "фикстура обязана быть длиннее в БАЙТАХ");
        assert!(
            failure_notice_reason(&format!("API Error: {russian}"), "/mmm-report").is_some(),
            "русский текст в пределах порога по символам обязан проверяться маркером так же, \
             как английский"
        );
    }

    /// 🔴 Находка внешнего аудита (Medium): `starts_with` спотыкается о разметку. Claude CLI
    /// оборачивает сообщение об отказе в markdown — `**API Error**: …` — и ни один маркер не
    /// совпадал, а значит текст отказа снова сохранялся клиенту отчётом (обход гейта CPD-32).
    #[test]
    fn markdown_wrapped_failure_notice_is_still_recognised() {
        for wrapped in [
            "**API Error**: Connection closed mid-response.",
            "`API Error: Connection closed`",
            "> Error: request failed",
            "### Request timed out after 600s",
            "- Connection closed",
        ] {
            assert!(
                failure_notice_reason(wrapped, "/mmm-report").is_some(),
                "разметка в начале не превращает отказ канала в результат работы: {wrapped}"
            );
        }
    }

    /// 🔴 Находка внешнего аудита (Medium): ложное срабатывание гейта выбрасывало НАСТОЯЩИЙ
    /// короткий ответ, когда пользователь спросил про саму строку ошибки, — и говорило клиенту
    /// «ответ не дошёл» про дошедший ответ (ложное утверждение о себе, INV-50, плюс потеря
    /// сделанной работы).
    #[test]
    fn short_answer_about_an_error_string_is_kept_when_the_question_named_it() {
        assert!(
            failure_notice_reason(
                "Connection closed — «соединение закрыто»: сервер разорвал канал.",
                "переведи: Connection closed"
            )
            .is_none(),
            "ответ на вопрос ПРО эту строку законно начинается ею же"
        );
        // Негативный контроль к тому же правилу: вопрос без маркера — гейт обязан сработать,
        // иначе исключение проглотило бы распознавание целиком.
        assert!(
            failure_notice_reason("Connection closed", "/mmm-report").is_some(),
            "без упоминания в вопросе это по-прежнему отказ канала"
        );
    }

    /// 🔴 Находка внешнего аудита (Medium): в гейт приходит не вопрос клиента, а РАСКРЫТЫЙ шаблон
    /// слэш-команды целиком. Строка `Error:` внутри шаблона снимала бы гейт для этой команды
    /// навсегда и молча — то есть текст отказа снова ложился бы клиенту файлом (CPD-32).
    /// Прежние тесты этого не ловили: они передавали `"/mmm-report"`, то есть мир, которого в
    /// продукте нет.
    #[test]
    fn a_marker_inside_an_expanded_command_template_does_not_disable_the_gate() {
        let template = format!(
            "# Команда /mmm-report\n\nСобери отчёт по модели.\n\
             Если увидишь Error: в журнале — опиши причину клиенту.\n{}",
            "Дополнительные указания по оформлению раздела. ".repeat(60)
        );
        assert!(
            template.chars().count() > FAILURE_NOTICE_PROMPT_MAX_CHARS,
            "фикстура обязана быть длиннее потолка запроса, иначе случай проверяет не то"
        );
        assert!(
            failure_notice_reason("Error: request failed", &template).is_some(),
            "маркер в длинном шаблоне команды не имеет права снимать гейт: иначе сообщение об \
             обрыве канала снова ляжет клиенту файлом-отчётом"
        );
        // Контроль обратной стороны: короткий вопрос человека исключение по-прежнему включает.
        assert!(
            failure_notice_reason("Error: request failed", "что значит Error: request failed")
                .is_none(),
            "для короткого запроса исключение обязано работать — ради него оно и заведено"
        );
    }

    /// 🔴 Сторож СВЯЗИ, а не только логики (урок Ф-04 внешнего аудита: вынесенная функция была
    /// покрыта, а её вызов — нет, и дефект жил дальше). Проверка обязана стоять МЕЖДУ входом в
    /// автосохранение и записью файла: если её вынести за пределы этого промежутка, распознавание
    /// останется рабочим, а отказ снова ляжет на диск отчётом.
    ///
    /// Тест разбирает собственный исходник — тот же приём, что у сторожа паритета ярусов
    /// качества (`test_mqs_tier_rust_single_source.py`), потому что вызов `auto_save_response`
    /// требует живого `AppHandle` и юнит-тестом не строится.
    #[test]
    fn auto_save_checks_whether_the_answer_happened_before_writing() {
        let src = include_str!("claude.rs");
        let start = src
            .find("pub(crate) fn auto_save_response")
            .expect("функция auto_save_response не найдена — разметка переехала");
        let tail = &src[start..];
        let write_at = tail
            .find("std::fs::write(&export_path")
            .expect("запись файла в auto_save_response не найдена — разметка переехала");
        let window = &tail[..write_at];

        assert!(
            window.contains("failure_notice_reason"),
            "между входом в автосохранение и записью файла нет проверки «состоялся ли ответ» — \
             сообщение об обрыве канала снова ляжет в папку клиента файлом с признаками \
             выполненной работы (CPD-32)"
        );
        assert!(
            window.contains("claude-stream-"),
            "отказ обязан быть ГРОМКИМ: молчаливый пропуск возвращает к родственному дефекту \
             «файла нет, и никто не знает почему» (CPD-17)"
        );
    }

    /// 🔴 Находка внешнего аудита (High): путей записи файла ДВА, а гейт стоял на одном.
    /// Ветка повторяемой ошибки пишет `-partial.md` напрямую через `std::fs::write`, минуя
    /// `auto_save_response`. Сценарий: stderr дал повторяемую ошибку, а в буфере stdout уже лежит
    /// «API Error: Connection closed» — текст отказа ложился клиенту файлом ровно как до починки.
    /// Сторож проверяет КАЖДУЮ запись в `exports`, а не только заметную.
    #[test]
    fn every_path_that_writes_an_export_passes_the_gate() {
        let src = include_str!("claude.rs");
        // 🔴 Окно берётся по СТРОКАМ, а не по байтовому смещению: срез вида `src[idx-700..idx]`
        // паникует, попав внутрь многобайтового символа кириллицы. Та же ловушка, от которой
        // защищает `FAILURE_NOTICE_MAX_CHARS` в самом продукте — поймана первым же прогоном.
        // 🔴 Образец собирается из частей: записанный целиком, он совпал бы с собственной строкой
        // этого теста, и сторож нашёл бы «незащищённую запись» в самом себе (поймано прогоном).
        let needle = concat!("std::fs::write(", "exports_dir");
        let lines: Vec<&str> = src.lines().collect();
        let mut unguarded = Vec::new();
        for (i, line) in lines.iter().enumerate() {
            if !line.contains(needle) || line.trim_start().starts_with("//") {
                continue;
            }
            let from = i.saturating_sub(15);
            // 🔴 Упоминание в КОММЕНТАРИИ гейтом не считается (находка внешнего аудита): иначе
            // сторож обходится строкой пояснения рядом с незащищённой записью — тот же способ
            // обмана, от которого соседний гейт защищается вырезанием комментариев.
            let guarded = lines[from..i].iter().any(|l| {
                let body = l.trim_start();
                !body.starts_with("//") && l.contains("failure_notice_reason")
            });
            if !guarded {
                unguarded.push(i + 1);
            }
        }
        assert!(
            unguarded.is_empty(),
            "запись выгрузки без гейта содержимого на строках {unguarded:?} — текст отказа снова \
             ляжет клиенту файлом-отчётом (CPD-32)"
        );
    }

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

    // ── Резолв бинаря: проверяется НАБЛЮДАЕМЫМ поведением find_claude_in ───────────
    //
    // 🔴 Прежний сторож сверял `candidate_names()` сам с собой и с резолвом связан не
    // был: возврат собственного массива в обход функции оставлял его зелёным. Здесь
    // вместо списка имён — подставной каталог с файлами-кандидатами, и проверяется то,
    // что резолв ВЕРНУЛ. Признак платформы передаётся параметром, поэтому оба порядка
    // (windows и не-windows) проверяются на любой машине, а не только на «своей».

    /// Положить файл-кандидат; на Unix — с битом исполнения, иначе резолв его не берёт.
    fn put_candidate(dir: &Path, name: &str) -> std::path::PathBuf {
        let path = dir.join(name);
        std::fs::write(&path, b"fake").expect("записать файл-кандидат");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755))
                .expect("бит исполнения");
        }
        path
    }

    /// На Windows `.exe`/`.cmd` обязаны выбираться ПЕРЕД `claude` без расширения:
    /// Unix-скрипт без расширения Windows не запускает (os error 193), и зонд ложно
    /// репортил локальный Claude Code недоступным, уводя работу на шлюз.
    #[test]
    fn resolve_prefers_native_exe_over_extensionless_script() {
        let dir = tempfile::tempdir().expect("временный каталог");
        for name in ["claude", "claude.cmd", "claude.exe"] {
            put_candidate(dir.path(), name);
        }
        let trusted = vec![dir.path().to_string_lossy().to_string()];
        let found = find_claude_in(&[dir.path().to_path_buf()], &trusted, true)
            .expect("резолв обязан найти бинарь");
        assert!(
            found.ends_with("claude.exe"),
            "выбран обязан быть claude.exe, а вернулось: {found}"
        );
    }

    /// Нативного `.exe` нет — берётся обёртка npm, но не скрипт без расширения.
    #[test]
    fn resolve_takes_cmd_wrapper_when_native_exe_absent() {
        let dir = tempfile::tempdir().expect("временный каталог");
        for name in ["claude", "claude.cmd"] {
            put_candidate(dir.path(), name);
        }
        let trusted = vec![dir.path().to_string_lossy().to_string()];
        let found = find_claude_in(&[dir.path().to_path_buf()], &trusted, true)
            .expect("резолв обязан найти бинарь");
        assert!(
            found.ends_with("claude.cmd"),
            "без claude.exe обязан выбираться claude.cmd, а вернулось: {found}"
        );
    }

    /// 🔴 Не-Windows: резолв обязан работать без `where`, которого на macOS и Linux
    /// нет. Прежний код звал `Command::new("where")` → ENOENT → локальный режим
    /// объявлялся недоступным навсегда, и работа уходила на шлюз.
    #[test]
    fn resolve_finds_binary_without_where_outside_windows() {
        let dir = tempfile::tempdir().expect("временный каталог");
        put_candidate(dir.path(), "claude");
        let trusted = vec![dir.path().to_string_lossy().to_string()];
        let found = find_claude_in(&[dir.path().to_path_buf()], &trusted, false)
            .expect("на не-Windows резолв обязан найти claude в PATH");
        assert!(found.ends_with("claude"), "вернулось: {found}");
    }

    /// Установка вне доверенных расположений — это ОТДЕЛЬНАЯ причина, а не «не найден»:
    /// человеку нельзя показывать «Claude Code не найден», когда он стоит и работает.
    #[test]
    fn resolve_names_untrusted_location_instead_of_not_found() {
        let dir = tempfile::tempdir().expect("временный каталог");
        put_candidate(dir.path(), "claude.exe");
        let failure = find_claude_in(&[dir.path().to_path_buf()], &[], true)
            .expect_err("вне доверенных расположений резолв обязан отказать");
        match failure {
            ResolveFailure::Untrusted(path) => {
                assert!(path.ends_with("claude.exe"), "причина обязана называть путь: {path}")
            }
            other => panic!("ожидался отказ по недоверенному расположению, получено: {other:?}"),
        }
    }

    /// Пустой PATH — честное «не найден».
    #[test]
    fn resolve_reports_not_found_when_nothing_installed() {
        let dir = tempfile::tempdir().expect("временный каталог");
        let trusted = vec![dir.path().to_string_lossy().to_string()];
        let failure = find_claude_in(&[dir.path().to_path_buf()], &trusted, true)
            .expect_err("пустой каталог не может дать бинарь");
        assert!(
            matches!(failure, ResolveFailure::NotFound),
            "ожидалось «не найден», получено: {failure:?}"
        );
    }

    /// 🔴 Один источник истины: файл, выбранный однажды, не меняется до явного сброса.
    /// Иначе зонд доказывает запускаемость одной установки, а работа идёт через другую.
    #[test]
    fn resolved_binary_stays_the_same_until_forgotten() {
        let dir = tempfile::tempdir().expect("временный каталог");
        let real = put_candidate(dir.path(), "claude.exe").to_string_lossy().to_string();

        forget_claude_binary();
        let first = remembered_or_resolve(|| Ok(real.clone())).expect("первый резолв");
        assert_eq!(first, real);

        let second = remembered_or_resolve(|| Ok("вторая-установка".to_string()))
            .expect("повторный резолв");
        assert_eq!(
            second, real,
            "повторный резолв обязан вернуть тот же файл, а вернул: {second}"
        );

        forget_claude_binary();
        let third = remembered_or_resolve(|| Ok("вторая-установка".to_string()))
            .expect("резолв после сброса");
        assert_eq!(third, "вторая-установка", "после сброса резолв обязан искать заново");
        forget_claude_binary();
    }

    // ── Строка команды для cmd /C ─────────────────────────────────────────────────

    /// 🔴 Маршрутный дефект: `&` в пути `cmd.exe` разбирал как оператор, зонд ложно
    /// репортил локальный Claude Code недоступным, и материалы уходили на шлюз.
    #[test]
    fn cmd_line_wraps_path_with_shell_operators_in_quotes() {
        let line = windows_cmd_command_line(r"C:\Users\A&B\AppData\Roaming\npm\claude.cmd", &["--version"]);
        assert_eq!(
            line, r#"""C:\Users\A&B\AppData\Roaming\npm\claude.cmd" --version""#,
            "вся команда обязана быть во внешних кавычках, путь — в своих"
        );
        assert!(line.starts_with("\"\""), "внешняя пара кавычек обязана открывать строку: {line}");
        assert!(line.ends_with('"'), "внешняя пара кавычек обязана закрывать строку: {line}");
    }

    /// Обычный путь и путь с пробелом обязаны остаться рабочими — правка не вправе
    /// чинить редкий случай ценой обычного.
    #[test]
    fn cmd_line_keeps_plain_and_spaced_paths_working() {
        let plain = windows_cmd_command_line(r"C:\npm\claude.cmd", &["--version"]);
        assert_eq!(plain, r#"""C:\npm\claude.cmd" --version""#);

        let spaced = windows_cmd_command_line(r"C:\Program Files\claude.exe", &["--version"]);
        assert_eq!(spaced, r#"""C:\Program Files\claude.exe" --version""#);
    }

    /// Аргумент со знаком-оператором или пробелом обязан уезжать в кавычках.
    #[test]
    fn cmd_line_quotes_arguments_that_need_it() {
        let line = windows_cmd_command_line(
            r"C:\npm\claude.cmd",
            &["--print", "--model", "имя со пробелом", "a&b"],
        );
        assert!(line.contains(" --print "), "простой флаг обрамлять не нужно: {line}");
        assert!(line.contains("\"имя со пробелом\""), "аргумент с пробелом обязан быть в кавычках: {line}");
        assert!(line.contains("\"a&b\""), "аргумент со знаком & обязан быть в кавычках: {line}");
    }
}

/// Порядок кандидатов имени бинаря по платформам.
///
/// На Windows нативный `.exe` и `.cmd`-скрипт идут ПЕРЕД `claude` без расширения:
/// npm кладёт рядом все три файла, а Unix-скрипт без расширения Windows не запускает
/// напрямую (os error 193). Зонд `probe_local` (execution_mode.rs) резолвил именно этот
/// путь первым и ложно репортил «Claude Code найден, но не запускается», уводя
/// автоопределение в облачный режим при рабочем локальном Claude Code.
///
/// Признак платформы — параметр, а не `cfg!` внутри: так порядок проверяется прогоном
/// на ЛЮБОЙ машине, а не только там, где он и так работает. Сторож под `#[cfg(windows)]`
/// молчит везде, где его не запускают.
pub(crate) fn candidate_names(windows: bool) -> &'static [&'static str] {
    if windows {
        &["claude.exe", "claude.cmd", "claude"]
    } else {
        &["claude"]
    }
}

/// Собрать строку команды для `cmd /C` так, чтобы знаки в пути не разбирались как
/// операторы оболочки.
///
/// 🔴 Маршрутный дефект (подтверждён прогоном 2026-08-09). Путь, переданный ОТДЕЛЬНЫМ
/// аргументом, Rust обрамляет кавычками только при пробеле или табуляции, а `cmd.exe`
/// разбирает `&`, `^`, `(`, `)` как операторы. Имя учётной записи Windows такие знаки
/// допускает: на пути вида `C:\Users\A&B\...\claude.cmd` запуск падал кодом 1 с
/// «"C:\Users\A" не является внутренней или внешней командой». Для зонда доступности
/// это означало ложное «локальный Claude Code недоступен» — и материалы клиента уходили
/// на шлюз при полностью рабочей локальной установке.
///
/// Форма выбрана по правилу самого `cmd.exe`: если строка после `/C` начинается с
/// кавычки и кавычек в ней больше двух, снимается ПЕРВАЯ и ПОСЛЕДНЯЯ, а остальное
/// разбирается как команда. Поэтому вся команда обрамляется внешней парой, а путь
/// внутри — своей: `""C:\A&B\claude.cmd" --version"`. Внутри кавычек `&` и `^` для
/// `cmd.exe` — обычные знаки. Прогон на временных каталогах с `&`, `^`, `(`, `%`,
/// апострофом, пробелом и сочетанием «пробел плюс &»: прежняя форма падала кодом 1 на
/// четырёх из них, эта проходит на всех — и для `.cmd`, и для файла без расширения.
///
/// Аргумент, содержащий сам знак кавычки, этой формой не передаётся: у `cmd.exe` нет
/// способа экранировать кавычку внутри такой строки. Ни один аргумент запуска Claude
/// Code её не содержит — это либо постоянные флаги, либо значения из белых списков,
/// либо идентификатор сессии, проверенный на состав знаков.
#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn windows_cmd_command_line(binary: &str, args: &[&str]) -> String {
    let mut line = String::with_capacity(binary.len() + 32);
    line.push('"'); // внешняя кавычка — её cmd.exe снимет
    line.push('"');
    line.push_str(binary);
    line.push('"');
    for arg in args {
        line.push(' ');
        let needs_quotes = arg.is_empty()
            || arg.chars().any(|c| {
                c.is_whitespace() || matches!(c, '&' | '^' | '|' | '<' | '>' | '(' | ')')
            });
        if needs_quotes {
            line.push('"');
            line.push_str(arg);
            line.push('"');
        } else {
            line.push_str(arg);
        }
    }
    line.push('"'); // парная внешняя
    line
}

/// Почему резолв не дал бинаря. Это разные ответы человеку: «нигде нет» он лечит
/// установкой, «нашли вне доверенных расположений» — переносом или явным выбором
/// режима, и путать их значит скрывать причину, по которой работа ушла на шлюз.
#[derive(Debug)]
pub(crate) enum ResolveFailure {
    NotFound,
    Untrusted(String),
}

/// Каталоги поиска — `PATH` процесса.
///
/// Раньше поиск шёл через `where`, которого на macOS и Linux нет: `Command::new("where")`
/// давал ENOENT, все кандидаты отбраковывались, и локальный режим объявлялся недоступным
/// навсегда. Штатный обход `PATH` работает одинаково всюду и заодно не ищет в текущем
/// каталоге, как это делает `where`.
fn path_dirs() -> Vec<std::path::PathBuf> {
    std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).collect())
        .unwrap_or_default()
}

/// Расположения, из которых мы согласны запускать найденный бинарь.
fn trusted_prefixes() -> Vec<String> {
    #[cfg(windows)]
    {
        [
            std::env::var("APPDATA").ok(),
            std::env::var("LOCALAPPDATA").ok(),
            std::env::var("USERPROFILE").ok(),
            std::env::var("PROGRAMFILES").ok(),
            std::env::var("PROGRAMFILES(X86)").ok(),
        ]
        .into_iter()
        .flatten()
        .collect()
    }
    #[cfg(not(windows))]
    {
        let mut dirs: Vec<String> =
            ["/usr", "/bin", "/opt", "/snap"].iter().map(|s| (*s).to_string()).collect();
        if let Ok(home) = std::env::var("HOME") {
            dirs.push(home);
        }
        dirs
    }
}

#[cfg(unix)]
fn is_runnable_file(path: &Path, windows: bool) -> bool {
    use std::os::unix::fs::PermissionsExt;
    let Ok(meta) = std::fs::metadata(path) else { return false };
    if !meta.is_file() {
        return false;
    }
    // Признак запуска на Unix — бит исполнения; на Windows его нет, и при проверке
    // windows-порядка на unix-машине он не спрашивается.
    windows || meta.permissions().mode() & 0o111 != 0
}

#[cfg(not(unix))]
fn is_runnable_file(path: &Path, _windows: bool) -> bool {
    std::fs::metadata(path).map(|m| m.is_file()).unwrap_or(false)
}

fn is_trusted(path: &str, prefixes: &[String], case_insensitive: bool) -> bool {
    if case_insensitive {
        let lower = path.to_lowercase();
        prefixes.iter().any(|p| lower.starts_with(&p.to_lowercase()))
    } else {
        prefixes.iter().any(|p| path.starts_with(p.as_str()))
    }
}

/// Сам поиск — без обращения к среде, поэтому проверяется подставным каталогом.
fn find_claude_in(
    dirs: &[std::path::PathBuf],
    trusted: &[String],
    windows: bool,
) -> std::result::Result<String, ResolveFailure> {
    let mut untrusted: Option<String> = None;
    for name in candidate_names(windows) {
        for dir in dirs {
            let candidate = dir.join(name);
            if !is_runnable_file(&candidate, windows) {
                continue;
            }
            let resolved = candidate.to_string_lossy().to_string();
            if is_trusted(&resolved, trusted, windows) {
                debug!("Claude binary found: {resolved}");
                return Ok(resolved);
            }
            warn!("Claude binary at untrusted location: {resolved} - skipping");
            untrusted.get_or_insert(resolved);
        }
    }
    match untrusted {
        Some(path) => Err(ResolveFailure::Untrusted(path)),
        None => Err(ResolveFailure::NotFound),
    }
}

/// Путь, уже выбранный в этом запуске программы.
///
/// 🔴 Один источник истины о том, КАКОЙ файл мы берём. Зонд доступности
/// (`execution_mode::probe_local`) и боевой запуск обязаны говорить об одном и том же
/// файле: иначе зонд доказывает запускаемость одной установки, а работа идёт через
/// другую — и человек видит «локальный режим доступен» ровно перед отказом.
static RESOLVED_CLAUDE_BINARY: Mutex<Option<String>> = Mutex::new(None);

fn remembered_or_resolve(
    resolve: impl FnOnce() -> std::result::Result<String, ResolveFailure>,
) -> std::result::Result<String, ResolveFailure> {
    let mut guard = RESOLVED_CLAUDE_BINARY.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(path) = guard.as_ref() {
        if Path::new(path).is_file() {
            return Ok(path.clone());
        }
        // Файл исчез: установку снесли или переставили — ищем заново.
        guard.take();
    }
    let resolved = resolve()?;
    *guard = Some(resolved.clone());
    Ok(resolved)
}

/// Забыть выбранный путь. Зовётся вместе со сбросом зонда: клиент мог поставить или
/// переставить Claude Code, не перезапуская программу.
pub(crate) fn forget_claude_binary() {
    if let Ok(mut guard) = RESOLVED_CLAUDE_BINARY.lock() {
        guard.take();
    }
}

/// Найти Claude CLI с разбором причины отказа — для зонда доступности.
pub(crate) fn find_claude_binary_detailed() -> std::result::Result<String, ResolveFailure> {
    remembered_or_resolve(|| find_claude_in(&path_dirs(), &trusted_prefixes(), cfg!(windows)))
}

/// Find the Claude CLI binary and validate it's in a trusted location.
/// Используется только из `run_claude_inner` — недостижима при feature `thin`, см. там.
#[cfg_attr(feature = "thin", allow(dead_code))]
pub(crate) fn find_claude_binary() -> Result<String> {
    find_claude_binary_detailed().map_err(|failure| match failure {
        ResolveFailure::NotFound => {
            error!("Claude Code CLI not found in PATH");
            coded_err(
                ErrorCode::CL001,
                "Claude Code CLI not found. Install it: npm install -g @anthropic-ai/claude-code",
            )
        }
        ResolveFailure::Untrusted(path) => {
            error!("Claude Code CLI found outside trusted locations: {path}");
            coded_err(
                ErrorCode::CL001,
                &format!("Claude Code CLI found outside trusted locations: {path}"),
            )
        }
    })
}
