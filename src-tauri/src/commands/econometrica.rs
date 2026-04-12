//! Econometrica sidecar HTTP proxy commands.
//!
//! Forwards computation requests to the Python sidecar at :7430.
//! All heavy math (MCMC, optimization, charts) runs locally in Python — 0 Claude tokens.

use serde_json::Value;
use log::{info, warn};

const ECON_BASE: &str = "http://127.0.0.1:7430";

/// Timeout for quick endpoints (validate, decompose, optimize, charts)
const QUICK_TIMEOUT_SECS: u64 = 60;

/// Timeout for long-running endpoints (MCMC training)
const TRAIN_TIMEOUT_SECS: u64 = 900; // 15 minutes

fn client(timeout_secs: u64) -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(timeout_secs))
        .build()
        .unwrap_or_else(|_| reqwest::Client::new())
}

// ── Health ───────────────────────────────────────────

#[tauri::command]
pub async fn econ_health() -> Result<Value, String> {
    match client(5)
        .get(format!("{ECON_BASE}/health"))
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
    post_json("/compute/validate", &body, QUICK_TIMEOUT_SECS).await
}

#[tauri::command]
pub async fn econ_train(config: Value) -> Result<Value, String> {
    info!("econ_train: {:?}", config.get("kpi_column"));
    post_json("/compute/train", &config, TRAIN_TIMEOUT_SECS).await
}

#[tauri::command]
pub async fn econ_decompose(project_dir: String) -> Result<Value, String> {
    info!("econ_decompose: {project_dir}");
    let body = serde_json::json!({ "project_dir": project_dir });
    post_json("/compute/decompose", &body, QUICK_TIMEOUT_SECS).await
}

#[tauri::command]
pub async fn econ_optimize(project_dir: String, total_budget: Option<f64>,
                           min_pct: Option<f64>, max_pct: Option<f64>) -> Result<Value, String> {
    info!("econ_optimize: {project_dir}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "total_budget": total_budget,
        "min_pct": min_pct.unwrap_or(50.0),
        "max_pct": max_pct.unwrap_or(150.0),
    });
    post_json("/compute/optimize", &body, QUICK_TIMEOUT_SECS).await
}

#[tauri::command]
pub async fn econ_scenario(project_dir: String, scenario_name: String,
                           media_plan: Option<Value>, media_plan_file: Option<String>) -> Result<Value, String> {
    info!("econ_scenario: {scenario_name}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "scenario_name": scenario_name,
        "media_plan": media_plan.unwrap_or(Value::Object(Default::default())),
        "media_plan_file": media_plan_file,
    });
    post_json("/compute/scenario", &body, QUICK_TIMEOUT_SECS).await
}

#[tauri::command]
pub async fn econ_compare(project_dir: String) -> Result<Value, String> {
    let body = serde_json::json!({ "project_dir": project_dir });
    post_json("/compute/compare", &body, QUICK_TIMEOUT_SECS).await
}

#[tauri::command]
pub async fn econ_awareness_forecast(config: Value) -> Result<Value, String> {
    info!("econ_awareness_forecast");
    post_json("/compute/awareness/forecast", &config, QUICK_TIMEOUT_SECS).await
}

#[tauri::command]
pub async fn econ_awareness_sales(config: Value) -> Result<Value, String> {
    info!("econ_awareness_sales");
    post_json("/compute/awareness/sales", &config, QUICK_TIMEOUT_SECS).await
}

// ── Async training ───────────────────────────────────

#[tauri::command]
pub async fn econ_train_start(config: Value) -> Result<Value, String> {
    info!("econ_train_start: {:?}", config.get("kpi_column"));
    post_json("/compute/train/start", &config, QUICK_TIMEOUT_SECS).await
}

#[tauri::command]
pub async fn econ_train_progress() -> Result<Value, String> {
    client(5)
        .get(format!("{ECON_BASE}/compute/train/progress"))
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
    client(QUICK_TIMEOUT_SECS)
        .get(format!("{ECON_BASE}/compute/train/result/{task_id}"))
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
    post_json("/compute/validate/preview", &body, QUICK_TIMEOUT_SECS).await
}

// ── Charts ───────────────────────────────────────────

#[tauri::command]
pub async fn econ_chart(project_dir: String, chart_type: String) -> Result<Value, String> {
    let body = serde_json::json!({
        "project_dir": project_dir,
        "chart_type": chart_type,
    });
    post_json("/chart", &body, QUICK_TIMEOUT_SECS).await
}

// ── Helper ───────────────────────────────────────────

async fn post_json(path: &str, body: &Value, timeout_secs: u64) -> Result<Value, String> {
    let resp = client(timeout_secs)
        .post(format!("{ECON_BASE}{path}"))
        .json(body)
        .send()
        .await
        .map_err(|e| {
            warn!("Econometrica sidecar request failed: {e}");
            format!("Вычислительный модуль недоступен. Убедитесь, что Python sidecar запущен: {e}")
        })?;

    resp.json::<Value>()
        .await
        .map_err(|e| format!("Ошибка парсинга ответа: {e}"))
}
