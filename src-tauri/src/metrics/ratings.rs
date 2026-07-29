use anyhow::{Context, Result};
use log::debug;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResponseRating {
    pub cabinet_id: String,
    pub command_slug: Option<String>,
    pub timestamp: String,
    pub rating: i8, // -1 (thumbs down) or 1 (thumbs up)
    pub response_time_secs: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CabinetRatingSummary {
    pub total_ratings: u64,
    pub positive: u64,
    pub negative: u64,
    pub satisfaction_pct: f64,
}

fn ratings_path() -> Result<PathBuf> {
    // CPD-30: per-app каталог с одноразовым переносом legacy AIAgency\metrics — тот же подкаталог,
    // что и usage.json (collector.rs), см. durable_store (повторный вызов app_state_dir("metrics")
    // дёшев — маркер уже стоит).
    Ok(crate::durable_store::app_state_dir("metrics")?.join("ratings.json"))
}

fn load_ratings() -> Result<Vec<ResponseRating>> {
    let path = ratings_path()?;
    // 🔴 Внешний аудит 2026-07-29 (High): битый JSON уходит в карантин, а не молча в vec![] —
    // см. durable_store::read_json_or_quarantine (донор).
    Ok(crate::durable_store::read_json_or_quarantine(&path).unwrap_or_default())
}

fn save_ratings(ratings: &[ResponseRating]) -> Result<()> {
    let path = ratings_path()?;
    let json = serde_json::to_string_pretty(ratings)?;
    // 🔴 Внешний аудит 2026-07-29 (High): атомарная запись (tmp + rename) вместо прямой —
    // см. durable_store::write_atomic (донор).
    crate::durable_store::write_atomic(&path, json.as_bytes()).context("Failed to write ratings")?;
    Ok(())
}

pub fn rate_response(rating: ResponseRating) -> Result<()> {
    let mut ratings = load_ratings()?;
    debug!("Rating saved: cabinet={}, rating={}", rating.cabinet_id, rating.rating);
    ratings.push(rating);
    // Cap at 2000 ratings
    if ratings.len() > 2000 {
        ratings = ratings.split_off(ratings.len() - 2000);
    }
    save_ratings(&ratings)?;
    Ok(())
}

pub fn get_cabinet_ratings(cabinet_id: &str) -> Result<CabinetRatingSummary> {
    let ratings = load_ratings()?;
    let cabinet_ratings: Vec<_> = ratings.iter()
        .filter(|r| r.cabinet_id == cabinet_id)
        .collect();

    let total = cabinet_ratings.len() as u64;
    let positive = cabinet_ratings.iter().filter(|r| r.rating > 0).count() as u64;
    let negative = cabinet_ratings.iter().filter(|r| r.rating < 0).count() as u64;
    let satisfaction_pct = if total > 0 {
        (positive as f64 / total as f64) * 100.0
    } else {
        0.0
    };

    Ok(CabinetRatingSummary {
        total_ratings: total,
        positive,
        negative,
        satisfaction_pct,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ratings_default_state() {
        let summary = CabinetRatingSummary {
            total_ratings: 0,
            positive: 0,
            negative: 0,
            satisfaction_pct: 0.0,
        };

        assert_eq!(summary.total_ratings, 0);
        assert_eq!(summary.positive, 0);
        assert_eq!(summary.negative, 0);
        assert!((summary.satisfaction_pct - 0.0).abs() < f64::EPSILON);
    }
}
