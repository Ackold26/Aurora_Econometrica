//! Parser server HTTP proxy commands.
//!
//! Forwards requests to the Parser sidecar at :7421.
//! Only functional when Creative Hub is running with Python.

use serde_json::Value;

const PARSER_BASE: &str = "http://127.0.0.1:7421";

#[tauri::command]
pub async fn parser_run(brand_id: String) -> Result<Value, String> {
    let resp = reqwest::Client::new()
        .post(format!("{PARSER_BASE}/parse/{brand_id}"))
        .send()
        .await
        .map_err(|e| format!("Parser server unavailable: {e}"))?;
    resp.json::<Value>()
        .await
        .map_err(|e| format!("Failed to parse response: {e}"))
}

#[tauri::command]
pub async fn parser_run_platform(brand_id: String, platform: String) -> Result<Value, String> {
    let resp = reqwest::Client::new()
        .post(format!("{PARSER_BASE}/parse/{brand_id}/{platform}"))
        .send()
        .await
        .map_err(|e| format!("Parser server unavailable: {e}"))?;
    resp.json::<Value>()
        .await
        .map_err(|e| format!("Failed to parse response: {e}"))
}

#[tauri::command]
pub async fn parser_status() -> Result<Value, String> {
    let resp = reqwest::Client::new()
        .get(format!("{PARSER_BASE}/status"))
        .send()
        .await
        .map_err(|e| format!("Parser server unavailable: {e}"))?;
    resp.json::<Value>()
        .await
        .map_err(|e| format!("Failed to parse response: {e}"))
}

#[tauri::command]
pub async fn parser_history(brand_id: String) -> Result<Value, String> {
    let resp = reqwest::Client::new()
        .get(format!("{PARSER_BASE}/history/{brand_id}"))
        .send()
        .await
        .map_err(|e| format!("Parser server unavailable: {e}"))?;
    resp.json::<Value>()
        .await
        .map_err(|e| format!("Failed to parse response: {e}"))
}

#[tauri::command]
pub async fn parser_health() -> Result<bool, String> {
    match reqwest::Client::new()
        .get(format!("{PARSER_BASE}/health"))
        .timeout(std::time::Duration::from_secs(3))
        .send()
        .await
    {
        Ok(resp) => Ok(resp.status().is_success()),
        Err(_) => Ok(false),
    }
}
