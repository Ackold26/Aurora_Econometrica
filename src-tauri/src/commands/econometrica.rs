//! Econometrica sidecar HTTP proxy commands.
//!
//! Forwards computation requests to the Python sidecar. Порт больше не
//! захардкожен — читается из `econ_sidecar::current_port()`, который устанавливается
//! через `sidecar_runtime::allocate_port()` (deterministic per-user).
//!
//! All heavy math (MCMC, optimization, charts) runs locally in Python — 0 Claude tokens.
//!
//! # v1.0.9: X-Expected-Session handshake
//! Каждый POST добавляет заголовок `X-Expected-Session: <uuid>`. Sidecar
//! возвращает 409 если session_id не совпадает (foreign sidecar после reset),
//! и тогда мы делаем re-handshake (ensure_alive) + retry один раз.

use serde_json::Value;
use log::{info, warn};
use std::sync::OnceLock;
use std::time::Duration;

use crate::econ_sidecar;

/// Базовый URL sidecar — динамический порт. Использовать только через эту функцию.
fn econ_url(path: &str) -> String {
    format!("{}{}", econ_sidecar::base_url(), path)
}

/// Добавляет заголовок X-Expected-Session если session_id известен.
fn with_session(rb: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
    if let Some(sid) = econ_sidecar::current_session_id() {
        rb.header("X-Expected-Session", sid)
    } else {
        rb
    }
}

/// Timeout for quick endpoints (validate, decompose, optimize, charts)
const QUICK_TIMEOUT_SECS: u64 = 60;

/// Timeout for long-running endpoints (MCMC training)
const TRAIN_TIMEOUT_SECS: u64 = 900; // 15 minutes

/// Static clients — avoid TLS bootstrap + connection pool setup per request.
static QUICK_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
static TRAIN_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
static HEALTH_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();

fn quick_client() -> &'static reqwest::Client {
    QUICK_CLIENT.get_or_init(|| reqwest::Client::builder()
        .timeout(Duration::from_secs(QUICK_TIMEOUT_SECS))
        .build().unwrap_or_default())
}

fn train_client() -> &'static reqwest::Client {
    TRAIN_CLIENT.get_or_init(|| reqwest::Client::builder()
        .timeout(Duration::from_secs(TRAIN_TIMEOUT_SECS))
        .build().unwrap_or_default())
}

fn health_client() -> &'static reqwest::Client {
    HEALTH_CLIENT.get_or_init(|| reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build().unwrap_or_default())
}

// ── Health ───────────────────────────────────────────

#[tauri::command]
pub async fn econ_health() -> Result<Value, String> {
    match health_client()
        .get(econ_url("/health"))
        .send()
        .await
    {
        Ok(resp) => resp.json::<Value>().await.map_err(|e| format!("Parse error: {e}")),
        Err(e) => Ok(serde_json::json!({
            "status": "unavailable",
            "error": format!("{e}"),
        })),
    }
}

// ── Compute ──────────────────────────────────────────

#[tauri::command]
pub async fn econ_validate(file_path: String, project_dir: Option<String>) -> Result<Value, String> {
    info!("econ_validate: {file_path}");
    let body = serde_json::json!({ "file_path": file_path, "project_dir": project_dir });
    post_json("/compute/validate", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_train(config: Value) -> Result<Value, String> {
    info!("econ_train: {:?}", config.get("kpi_column"));
    post_json("/compute/train", &config, train_client()).await
}

#[tauri::command]
pub async fn econ_decompose(project_dir: String, unit_costs: Option<Value>) -> Result<Value, String> {
    info!("econ_decompose: {project_dir}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "unit_costs": unit_costs,
    });
    post_json("/compute/decompose", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_optimize(
    project_dir: String,
    total_budget: Option<f64>,
    total_budget_money: Option<f64>,
    min_pct: Option<f64>,
    max_pct: Option<f64>,
    min_per_channel: Option<Value>,
    max_per_channel: Option<Value>,
    unit_costs: Option<Value>,
) -> Result<Value, String> {
    info!("econ_optimize: {project_dir}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "total_budget": total_budget,
        "total_budget_money": total_budget_money,
        // O1.1 (Phase 0.1 fix-session 2026-04-25): 50/150 → 20/200 для real optimization freedom.
        // See OptimizeStep.svelte for rationale + docs/MATH_AUDIT_v1_3_PHASE_0_1.md.
        "min_pct": min_pct.unwrap_or(20.0),
        "max_pct": max_pct.unwrap_or(200.0),
        "min_per_channel": min_per_channel,
        "max_per_channel": max_per_channel,
        "unit_costs": unit_costs,
    });
    post_json("/compute/optimize", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_scenario(
    project_dir: String,
    scenario_name: String,
    media_plan: Option<Value>,
    media_plan_file: Option<String>,
    unit_costs: Option<Value>,
) -> Result<Value, String> {
    info!("econ_scenario: {scenario_name}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "scenario_name": scenario_name,
        "media_plan": media_plan.unwrap_or(Value::Object(Default::default())),
        "media_plan_file": media_plan_file,
        "unit_costs": unit_costs,
    });
    post_json("/compute/scenario", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_compare(project_dir: String, unit_costs: Option<Value>) -> Result<Value, String> {
    let body = serde_json::json!({
        "project_dir": project_dir,
        "unit_costs": unit_costs,
    });
    post_json("/compute/compare", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_scenario_delete(project_dir: String, scenario_name: String) -> Result<Value, String> {
    info!("econ_scenario_delete: {scenario_name}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "scenario_name": scenario_name,
    });
    post_json("/compute/scenario/delete", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_awareness_forecast(config: Value) -> Result<Value, String> {
    info!("econ_awareness_forecast");
    post_json("/compute/awareness/forecast", &config, quick_client()).await
}

#[tauri::command]
pub async fn econ_awareness_sales(config: Value) -> Result<Value, String> {
    info!("econ_awareness_sales");
    post_json("/compute/awareness/sales", &config, quick_client()).await
}

// ── Async training ───────────────────────────────────

#[tauri::command]
pub async fn econ_train_start(config: Value) -> Result<Value, String> {
    info!("econ_train_start: {:?}", config.get("kpi_column"));
    post_json("/compute/train/start", &config, quick_client()).await
}

#[tauri::command]
pub async fn econ_train_progress() -> Result<Value, String> {
    with_session(health_client().get(econ_url("/compute/train/progress")))
        .send()
        .await
        .map_err(|e| format!("Вычислительный модуль недоступен: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("Ошибка парсинга ответа: {e}"))
}

#[tauri::command]
pub async fn econ_train_cancel(task_id: String) -> Result<Value, String> {
    info!("econ_train_cancel: {task_id}");
    with_session(quick_client().post(econ_url(&format!("/compute/train/cancel/{task_id}"))))
        .send()
        .await
        .map_err(|e| format!("Вычислительный модуль недоступен: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("Ошибка парсинга ответа: {e}"))
}

#[tauri::command]
pub async fn econ_train_result(task_id: String) -> Result<Value, String> {
    info!("econ_train_result: {task_id}");
    with_session(quick_client().get(econ_url(&format!("/compute/train/result/{task_id}"))))
        .send()
        .await
        .map_err(|e| format!("Вычислительный модуль недоступен: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("Ошибка парсинга ответа: {e}"))
}

// ── Data Preview ─────────────────────────────────────

#[tauri::command]
pub async fn econ_data_preview(file_path: String, n_rows: Option<u32>) -> Result<Value, String> {
    info!("econ_data_preview: {file_path}");
    let body = serde_json::json!({
        "file_path": file_path,
        "n_rows": n_rows.unwrap_or(20),
    });
    post_json("/compute/validate/preview", &body, quick_client()).await
}

// ── Charts ───────────────────────────────────────────

#[tauri::command]
pub async fn econ_chart(project_dir: String, chart_type: String) -> Result<Value, String> {
    let body = serde_json::json!({
        "project_dir": project_dir,
        "chart_type": chart_type,
    });
    post_json("/chart", &body, quick_client()).await
}

// ── Adstock Auto-Select ─────────────────────────────

#[tauri::command]
pub async fn econ_adstock_select(
    file_path: String,
    kpi_column: String,
    media_columns: Vec<String>,
) -> Result<Value, String> {
    info!("econ_adstock_select: {file_path}, kpi={kpi_column}, channels={}", media_columns.len());
    let body = serde_json::json!({
        "file_path": file_path,
        "kpi_column": kpi_column,
        "media_columns": media_columns,
    });
    post_json("/compute/adstock_select", &body, quick_client()).await
}

// ── PPTX Export ─────────────────────────────────────

#[tauri::command]
pub async fn econ_export_pptx(
    project_id: String,
    model_data: Value,
    decompose_data: Value,
    optimize_data: Value,
) -> Result<Value, String> {
    info!("econ_export_pptx: project={project_id}");
    // Передаём абсолютный project_dir чтобы sidecar находил scenarios/exports
    // в customizable папке (настраивается в Settings). Без этого Python
    // читал бы захардкоженный %APPDATA% путь, игнорируя Settings override.
    let project_dir = crate::commands::project::project_dir(&project_id)
        .map(|p| p.to_string_lossy().to_string())
        .ok();
    let body = serde_json::json!({
        "project_id": project_id,
        "project_dir": project_dir,
        "model_data": model_data,
        "decompose_data": decompose_data,
        "optimize_data": optimize_data,
    });
    post_json("/export/pptx", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_export_html(
    project_id: String,
    model_data: Value,
    decompose_data: Value,
    optimize_data: Value,
    project_name: Option<String>,
) -> Result<Value, String> {
    info!("econ_export_html: project={project_id}");
    let project_dir = crate::commands::project::project_dir(&project_id)
        .map(|p| p.to_string_lossy().to_string())
        .ok();
    let body = serde_json::json!({
        "project_id": project_id,
        "project_dir": project_dir,
        "model_data": model_data,
        "decompose_data": decompose_data,
        "optimize_data": optimize_data,
        "project_name": project_name.unwrap_or_else(|| "Marketing Mix Model".to_string()),
    });
    post_json("/export/html", &body, quick_client()).await
}

// ── Helper ───────────────────────────────────────────

/// POST with auto-recovery:
/// - connect/timeout errors → trigger sidecar respawn + retry once
/// - HTTP 409 (session mismatch) → re-handshake + retry once (foreign sidecar detected)
/// - 4xx/5xx с JSON body → pass through untouched (app errors, not sidecar issues)
async fn post_json(path: &str, body: &Value, client: &reqwest::Client) -> Result<Value, String> {
    let send_once = |c: &reqwest::Client, url: String| {
        let req = with_session(c.post(url).json(body));
        async move { req.send().await }
    };

    let resp = match send_once(client, econ_url(path)).await {
        Ok(r) => r,
        Err(e) if e.is_connect() || e.is_timeout() => {
            warn!("Sidecar unreachable on {path} ({e}) — attempting auto-respawn");
            if !econ_sidecar::ensure_alive().await {
                return Err(format!(
                    "Вычислительный модуль недоступен и не удалось автоматически перезапустить. \
                     Попробуй нажать «Перезапустить модуль» или проверь логи sidecar: {e}"
                ));
            }
            send_once(client, econ_url(path)).await.map_err(|e2| {
                warn!("Retry after respawn failed on {path}: {e2}");
                format!("Модуль перезапущен, но запрос всё ещё не проходит: {e2}")
            })?
        }
        Err(e) => {
            warn!("Econometrica sidecar request failed: {e}");
            return Err(format!("Ошибка запроса к модулю: {e}"));
        }
    };

    // v1.0.9: 409 Conflict → session mismatch → re-handshake + retry once
    if resp.status() == reqwest::StatusCode::CONFLICT {
        warn!(
            "Sidecar {path} returned 409 (session mismatch) — \
             re-handshake and retry"
        );
        // ensure_alive делает /health verify_handshake + respawn если чужой
        if !econ_sidecar::ensure_alive().await {
            return Err("Session mismatch: модуль не удалось переинициализировать".to_string());
        }
        let resp2 = send_once(client, econ_url(path)).await.map_err(|e| {
            warn!("Retry after 409 failed on {path}: {e}");
            format!("Запрос не прошёл после re-handshake: {e}")
        })?;
        return parse_resp(resp2, path).await;
    }

    parse_resp(resp, path).await
}

async fn parse_resp(resp: reqwest::Response, path: &str) -> Result<Value, String> {
    let status = resp.status();
    let text = resp.text().await.map_err(|e| format!("Не удалось прочитать ответ: {e}"))?;
    match serde_json::from_str::<Value>(&text) {
        Ok(v) => {
            if !status.is_success() {
                warn!("Sidecar {path} returned {status}: {}", &text[..text.len().min(500)]);
                let msg = v
                    .get("message")
                    .and_then(|m| m.as_str())
                    .unwrap_or("неизвестная ошибка");
                return Err(format!("Ошибка sidecar ({status}): {msg}"));
            }
            Ok(v)
        }
        Err(e) => {
            warn!("Sidecar {path} non-JSON {status}: {}", &text[..text.len().min(500)]);
            Err(format!(
                "Ошибка парсинга ответа ({status}): {e}. Тело: {}",
                &text[..text.len().min(200)]
            ))
        }
    }
}
