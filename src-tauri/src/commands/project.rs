//! Econometrica project management.
//!
//! One project = one client/dataset + trained models + results + scenarios.
//! Stored in %APPDATA%/<identifier>/projects/ (filesystem-first, no RAG).

use log::info;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::{Path, PathBuf};

/// Project metadata (stored as project.json).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectInfo {
    pub id: String,
    pub name: String,
    pub description: String,
    pub created_at: String,
    pub updated_at: String,
    pub kpi_column: Option<String>,
    pub media_columns: Vec<String>,
    pub control_columns: Vec<String>,
    pub data_file: Option<String>,
}

/// Get the projects root directory: %APPDATA%/<identifier>/projects/
fn projects_dir() -> Result<PathBuf, String> {
    let appdata = std::env::var("APPDATA")
        .map_err(|_| "APPDATA not set".to_string())?;
    let identifier = env!("CARGO_PKG_NAME");
    let dir = PathBuf::from(appdata)
        .join(identifier)
        .join("projects");
    std::fs::create_dir_all(&dir).map_err(|e| format!("Failed to create projects dir: {e}"))?;
    Ok(dir)
}

fn project_dir(project_id: &str) -> Result<PathBuf, String> {
    let dir = projects_dir()?.join(project_id);
    Ok(dir)
}

fn read_project(dir: &Path) -> Result<ProjectInfo, String> {
    let path = dir.join("project.json");
    let data = std::fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read project.json: {e}"))?;
    serde_json::from_str(&data)
        .map_err(|e| format!("Invalid project.json: {e}"))
}

fn write_project(dir: &Path, info: &ProjectInfo) -> Result<(), String> {
    let path = dir.join("project.json");
    let json = serde_json::to_string_pretty(info)
        .map_err(|e| format!("Serialize error: {e}"))?;
    std::fs::write(&path, json)
        .map_err(|e| format!("Write error: {e}"))
}

fn now_iso() -> String {
    chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()
}

// ── Tauri commands ──────────────────────────────────

#[tauri::command]
pub async fn project_list() -> Result<Vec<ProjectInfo>, String> {
    let root = projects_dir()?;
    let mut projects = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&root) {
        for entry in entries.flatten() {
            if entry.file_type().map_or(false, |t| t.is_dir()) {
                if let Ok(info) = read_project(&entry.path()) {
                    projects.push(info);
                }
            }
        }
    }
    projects.sort_by(|a, b| b.updated_at.cmp(&a.updated_at)); // newest first
    Ok(projects)
}

#[tauri::command]
pub async fn project_create(name: String) -> Result<ProjectInfo, String> {
    let id = name.to_lowercase()
        .chars()
        .map(|c| if c.is_alphanumeric() || c == '-' { c } else { '-' })
        .collect::<String>()
        .trim_matches('-')
        .to_string();
    let id = if id.is_empty() { format!("project-{}", chrono::Utc::now().timestamp()) } else { id };
    let dir = project_dir(&id)?;
    if dir.exists() {
        return Err(format!("Проект «{name}» уже существует"));
    }

    // Create directory structure
    std::fs::create_dir_all(dir.join("data")).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(dir.join("models")).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(dir.join("results")).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(dir.join("results/scenarios")).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(dir.join("exports")).map_err(|e| e.to_string())?;

    let now = now_iso();
    let info = ProjectInfo {
        id: id.clone(),
        name,
        description: String::new(),
        created_at: now.clone(),
        updated_at: now,
        kpi_column: None,
        media_columns: Vec::new(),
        control_columns: Vec::new(),
        data_file: None,
    };
    write_project(&dir, &info)?;

    // Set as active
    set_active_project_inner(&id)?;

    info!("Created project: {id}");
    Ok(info)
}

#[tauri::command]
pub async fn project_get(project_id: String) -> Result<ProjectInfo, String> {
    let dir = project_dir(&project_id)?;
    if !dir.exists() {
        return Err(format!("Проект «{project_id}» не найден"));
    }
    read_project(&dir)
}

#[tauri::command]
pub async fn project_update(project_id: String, updates: Value) -> Result<ProjectInfo, String> {
    let dir = project_dir(&project_id)?;
    let mut info = read_project(&dir)?;

    if let Some(name) = updates.get("name").and_then(|v| v.as_str()) {
        info.name = name.to_string();
    }
    if let Some(desc) = updates.get("description").and_then(|v| v.as_str()) {
        info.description = desc.to_string();
    }
    if let Some(kpi) = updates.get("kpi_column").and_then(|v| v.as_str()) {
        info.kpi_column = Some(kpi.to_string());
    }
    if let Some(media) = updates.get("media_columns").and_then(|v| v.as_array()) {
        info.media_columns = media.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect();
    }
    if let Some(control) = updates.get("control_columns").and_then(|v| v.as_array()) {
        info.control_columns = control.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect();
    }
    if let Some(file) = updates.get("data_file").and_then(|v| v.as_str()) {
        info.data_file = Some(file.to_string());
    }

    info.updated_at = now_iso();
    write_project(&dir, &info)?;
    Ok(info)
}

#[tauri::command]
pub async fn project_delete(project_id: String) -> Result<(), String> {
    let dir = project_dir(&project_id)?;
    if dir.exists() {
        trash::delete(&dir).unwrap_or_else(|_| {
            // Fallback if trash unavailable (CI/headless)
            let _ = std::fs::remove_dir_all(&dir);
        });
        info!("Deleted project: {project_id}");
    }
    Ok(())
}

#[tauri::command]
pub async fn project_upload_data(project_id: String, file_path: String) -> Result<Value, String> {
    let dir = project_dir(&project_id)?;
    let src = PathBuf::from(&file_path);
    if !src.exists() {
        return Err(format!("Файл не найден: {file_path}"));
    }

    let filename = src.file_name()
        .ok_or("Invalid filename")?
        .to_string_lossy()
        .to_string();
    let dst = dir.join("data").join(&filename);
    std::fs::copy(&src, &dst).map_err(|e| format!("Copy failed: {e}"))?;

    // Update project metadata
    let mut info = read_project(&dir)?;
    info.data_file = Some(dst.to_string_lossy().to_string());
    info.updated_at = now_iso();
    write_project(&dir, &info)?;

    info!("Uploaded data to project {project_id}: {filename}");
    Ok(serde_json::json!({
        "filename": filename,
        "path": dst.to_string_lossy(),
        "size_kb": src.metadata().map(|m| m.len() / 1024).unwrap_or(0),
    }))
}

#[tauri::command]
pub async fn project_get_dir(project_id: String) -> Result<String, String> {
    let dir = project_dir(&project_id)?;
    if !dir.exists() {
        return Err(format!("Проект «{project_id}» не найден"));
    }
    Ok(dir.to_string_lossy().to_string())
}

// ── Active project ──────────────────────────────────

fn active_project_path() -> Result<PathBuf, String> {
    Ok(projects_dir()?.join("active_project.json"))
}

fn set_active_project_inner(project_id: &str) -> Result<(), String> {
    let path = active_project_path()?;
    let json = serde_json::json!({ "active_project": project_id });
    let serialized = serde_json::to_string_pretty(&json)
        .map_err(|e| format!("Serialize error: {e}"))?;
    std::fs::write(&path, serialized)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn project_activate(project_id: String) -> Result<(), String> {
    let dir = project_dir(&project_id)?;
    if !dir.exists() {
        return Err(format!("Проект «{project_id}» не найден"));
    }
    set_active_project_inner(&project_id)?;
    info!("Activated project: {project_id}");
    Ok(())
}

#[tauri::command]
pub async fn project_get_active() -> Result<Option<String>, String> {
    let path = active_project_path()?;
    if !path.exists() {
        return Ok(None);
    }
    let data = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let json: Value = serde_json::from_str(&data).map_err(|e| e.to_string())?;
    Ok(json.get("active_project").and_then(|v| v.as_str()).map(|s| s.to_string()))
}

#[tauri::command]
pub async fn project_stats(project_id: String) -> Result<Value, String> {
    let dir = project_dir(&project_id)?;
    if !dir.exists() {
        return Err(format!("Проект не найден"));
    }

    let has_data = dir.join("data").read_dir()
        .map(|mut d| d.any(|_| true))
        .unwrap_or(false);
    let has_model = dir.join("models").join("latest.pkl").exists();
    let has_decomposition = dir.join("results").join("decomposition.json").exists();
    let has_optimization = dir.join("results").join("optimization.json").exists();
    let n_scenarios = dir.join("results").join("scenarios")
        .read_dir()
        .map(|d| d.flatten().filter(|e| e.path().extension().map_or(false, |ext| ext == "json")).count())
        .unwrap_or(0);

    Ok(serde_json::json!({
        "has_data": has_data,
        "has_model": has_model,
        "has_decomposition": has_decomposition,
        "has_optimization": has_optimization,
        "n_scenarios": n_scenarios,
        "pipeline_step": if !has_data { 0 }
            else if !has_model { 1 }
            else if !has_decomposition { 2 }
            else { 3 },
    }))
}
