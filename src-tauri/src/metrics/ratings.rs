use anyhow::{Context, Result};
use log::{debug, warn};
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
    let local_app_data = std::env::var("LOCALAPPDATA")
        .unwrap_or_else(|_| "C:\\Users\\Default\\AppData\\Local".to_string());
    let dir = PathBuf::from(&local_app_data)
        .join("AIAgency")
        .join("metrics");
    std::fs::create_dir_all(&dir).context("Failed to create metrics directory")?;
    Ok(dir.join("ratings.json"))
}

fn load_ratings() -> Result<Vec<ResponseRating>> {
    let path = ratings_path()?;
    if !path.exists() {
        return Ok(vec![]);
    }
    let content = std::fs::read_to_string(&path)?;
    let ratings: Vec<ResponseRating> = serde_json::from_str(&content).unwrap_or_else(|e| {
        warn!("Failed to parse ratings: {e}");
        vec![]
    });
    Ok(ratings)
}

fn save_ratings(ratings: &[ResponseRating]) -> Result<()> {
    let path = ratings_path()?;
    let json = serde_json::to_string_pretty(ratings)?;
    std::fs::write(&path, json).context("Failed to write ratings")?;
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
