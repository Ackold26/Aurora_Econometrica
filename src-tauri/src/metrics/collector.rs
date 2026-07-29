use anyhow::{Context, Result};
use log::{debug, info, warn};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsageMetrics {
    pub total_sessions: u64,
    pub total_messages: u64,
    pub total_exports: u64,
    pub command_counts: HashMap<String, u32>,
    pub cabinets_used: Vec<String>,
    pub avg_response_time_secs: f64,
    pub first_use: Option<String>,
    pub last_use: Option<String>,
    /// Internal: accumulated response times for averaging
    #[serde(default)]
    response_time_sum_secs: f64,
    #[serde(default)]
    response_time_count: u64,
}

impl Default for UsageMetrics {
    fn default() -> Self {
        Self {
            total_sessions: 0,
            total_messages: 0,
            total_exports: 0,
            command_counts: HashMap::new(),
            cabinets_used: Vec::new(),
            avg_response_time_secs: 0.0,
            first_use: None,
            last_use: None,
            response_time_sum_secs: 0.0,
            response_time_count: 0,
        }
    }
}

fn metrics_path() -> Result<PathBuf> {
    // CPD-30: per-app каталог с одноразовым переносом legacy AIAgency\metrics — см. durable_store.
    Ok(crate::durable_store::app_state_dir("metrics")?.join("usage.json"))
}

fn now_iso() -> String {
    chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()
}

/// Thread-safe global metrics state
static METRICS: std::sync::LazyLock<Mutex<Option<UsageMetrics>>> =
    std::sync::LazyLock::new(|| Mutex::new(None));

fn with_metrics<F, R>(f: F) -> Result<R>
where
    F: FnOnce(&mut UsageMetrics) -> R,
{
    let mut guard = METRICS.lock().unwrap_or_else(|e| e.into_inner());
    if guard.is_none() {
        *guard = Some(load_from_disk()?);
    }
    let metrics = guard.as_mut().unwrap();
    let result = f(metrics);
    save_to_disk(metrics)?;
    Ok(result)
}

fn load_from_disk() -> Result<UsageMetrics> {
    let path = metrics_path()?;
    if !path.exists() {
        return Ok(UsageMetrics::default());
    }
    let content = std::fs::read_to_string(&path)?;
    let metrics: UsageMetrics = serde_json::from_str(&content).unwrap_or_else(|e| {
        warn!("Failed to parse metrics file: {e}, starting fresh");
        UsageMetrics::default()
    });
    Ok(metrics)
}

fn save_to_disk(metrics: &UsageMetrics) -> Result<()> {
    let path = metrics_path()?;
    let json = serde_json::to_string_pretty(metrics)?;
    std::fs::write(&path, json).context("Failed to write metrics")?;
    Ok(())
}

/// Record a new session open
pub fn record_session(cabinet_id: &str) -> Result<()> {
    with_metrics(|m| {
        m.total_sessions += 1;
        m.last_use = Some(now_iso());
        if m.first_use.is_none() {
            m.first_use = Some(now_iso());
        }
        if !m.cabinets_used.contains(&cabinet_id.to_string()) {
            m.cabinets_used.push(cabinet_id.to_string());
        }
        debug!("Metrics: session recorded for {cabinet_id}, total={}", m.total_sessions);
    })?;
    Ok(())
}

/// Record a message sent
pub fn record_message(command_slug: Option<&str>) -> Result<()> {
    with_metrics(|m| {
        m.total_messages += 1;
        m.last_use = Some(now_iso());
        if let Some(slug) = command_slug {
            *m.command_counts.entry(slug.to_string()).or_insert(0) += 1;
        }
    })?;
    Ok(())
}

/// Record response time
pub fn record_response_time(seconds: f64) -> Result<()> {
    with_metrics(|m| {
        m.response_time_sum_secs += seconds;
        m.response_time_count += 1;
        m.avg_response_time_secs = m.response_time_sum_secs / m.response_time_count as f64;
    })?;
    Ok(())
}

/// Record an export generated
pub fn record_export() -> Result<()> {
    with_metrics(|m| {
        m.total_exports += 1;
    })?;
    Ok(())
}

/// Get current metrics
pub fn get_metrics() -> Result<UsageMetrics> {
    let path = metrics_path()?;
    if !path.exists() {
        return Ok(UsageMetrics::default());
    }
    load_from_disk()
}

/// Reset all metrics
pub fn reset_metrics() -> Result<()> {
    let path = metrics_path()?;
    if path.exists() {
        std::fs::remove_file(&path)?;
    }
    let mut guard = METRICS.lock().unwrap_or_else(|e| e.into_inner());
    *guard = None;
    info!("Metrics reset");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metrics_serialize_deserialize() {
        let mut original = UsageMetrics::default();
        original.total_sessions = 42;
        original.total_messages = 100;
        original.total_exports = 5;
        original.command_counts.insert("ask".to_string(), 10);
        original.cabinets_used.push("cabinet-a".to_string());
        original.avg_response_time_secs = 1.5;
        original.first_use = Some("2026-01-01T00:00:00".to_string());
        original.last_use = Some("2026-03-25T12:00:00".to_string());

        let json = serde_json::to_string(&original).expect("serialize failed");
        let restored: UsageMetrics = serde_json::from_str(&json).expect("deserialize failed");

        assert_eq!(restored.total_sessions, original.total_sessions);
        assert_eq!(restored.total_messages, original.total_messages);
        assert_eq!(restored.total_exports, original.total_exports);
        assert_eq!(restored.command_counts, original.command_counts);
        assert_eq!(restored.cabinets_used, original.cabinets_used);
        assert!((restored.avg_response_time_secs - original.avg_response_time_secs).abs() < f64::EPSILON);
        assert_eq!(restored.first_use, original.first_use);
        assert_eq!(restored.last_use, original.last_use);
    }
}
