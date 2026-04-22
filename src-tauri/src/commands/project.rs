//! Econometrica project management.
//!
//! One project = one client/dataset + trained models + results + scenarios.
//! Stored in %APPDATA%/<identifier>/projects/ (filesystem-first, no RAG).

use log::info;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
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
    /// Trust Level 2: стоимость 1 юнита канала в валюте KPI (CPP/CPM).
    /// Для каналов в рублях — 1.0 или отсутствие записи.
    #[serde(default)]
    pub unit_costs: HashMap<String, f64>,
}

/// Get the projects root directory.
/// Priority: env AURORA_PROJECTS_ROOT > user_config.econometrica_projects_root > default.
/// Default: %APPDATA%/<identifier>/projects/
pub fn projects_dir() -> Result<PathBuf, String> {
    let appdata = std::env::var("APPDATA")
        .map_err(|_| "APPDATA not set".to_string())?;
    let identifier = env!("CARGO_PKG_NAME");

    // Env override — для тестов и advanced users.
    if let Ok(env_root) = std::env::var("AURORA_PROJECTS_ROOT") {
        if !env_root.trim().is_empty() {
            let dir = PathBuf::from(env_root.trim());
            std::fs::create_dir_all(&dir)
                .map_err(|e| format!("Failed to create projects dir (env): {e}"))?;
            return Ok(dir);
        }
    }

    // User-configured override — читаем user_config.json напрямую с диска
    // (без AppHandle — чтобы не менять сигнатуру во всех вызовах вверх по стеку).
    let config_dir = PathBuf::from(&appdata).join(identifier);
    let config_path = config_dir.join("user_config.json");
    if config_path.exists() {
        if let Ok(data) = std::fs::read_to_string(&config_path) {
            if let Ok(cfg) = serde_json::from_str::<serde_json::Value>(&data) {
                if let Some(root) = cfg.get("econometrica_projects_root").and_then(|v| v.as_str()) {
                    let trimmed = root.trim();
                    if !trimmed.is_empty() {
                        let dir = PathBuf::from(trimmed);
                        std::fs::create_dir_all(&dir)
                            .map_err(|e| format!("Failed to create projects dir (config): {e}"))?;
                        return Ok(dir);
                    }
                }
            }
        }
    }

    // Default
    let dir = PathBuf::from(appdata)
        .join(identifier)
        .join("projects");
    std::fs::create_dir_all(&dir).map_err(|e| format!("Failed to create projects dir: {e}"))?;
    Ok(dir)
}

pub fn project_dir(project_id: &str) -> Result<PathBuf, String> {
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
        unit_costs: HashMap::new(),
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
    if let Some(uc) = updates.get("unit_costs").and_then(|v| v.as_object()) {
        info.unit_costs = uc.iter()
            .filter_map(|(k, v)| v.as_f64().map(|f| (k.clone(), f)))
            .collect();
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

/// Восстановить все доступные результаты pipeline с диска в единый JSON.
/// Фронтенд читает его при активации проекта и заполняет стoры, чтобы ReportStep
/// и InsightsPanel не показывали «данных нет» при complete-статусе в stepper.
/// Отсутствующие файлы → соответствующее поле = null.
#[tauri::command]
pub async fn project_load_results(project_id: String) -> Result<Value, String> {
    let dir = project_dir(&project_id)?;
    if !dir.exists() {
        return Err("Проект не найден".to_string());
    }
    let results = dir.join("results");

    let read_json = |name: &str| -> Value {
        let path = results.join(name);
        if !path.exists() {
            return Value::Null;
        }
        std::fs::read_to_string(&path)
            .ok()
            .and_then(|s| serde_json::from_str::<Value>(&s).ok())
            .unwrap_or(Value::Null)
    };

    Ok(serde_json::json!({
        "validation":       read_json("validation.json"),
        "modelDiagnostics": read_json("model-diagnostics.json"),
        "decomposition":    read_json("decomposition.json"),
        "optimization":     read_json("optimization.json"),
    }))
}

// ── Archive import/export (.aurora) ──────────────────────────────────────────
//
// Save: упаковывает весь project_dir (data + models + results + scenarios + exports +
// project.json) в единый zip-архив с расширением .aurora. Клиент может передать его
// на другую машину / сохранить как бэкап.
//
// Load: распаковывает архив в новый project_id, перезаписывает поле id в project.json
// на новый (чтобы не было конфликта с существующим проектом того же имени). Возвращает
// new project_id, который фронтенд сразу активирует.

/// Экспорт проекта в zip-архив .aurora. Возвращает путь к созданному файлу.
/// output_path — обычно путь из dialog.save на фронте.
#[tauri::command]
pub async fn project_export_archive(
    project_id: String,
    output_path: String,
) -> Result<String, String> {
    use std::io::Write;
    use zip::write::SimpleFileOptions;

    let src = project_dir(&project_id)?;
    if !src.exists() {
        return Err("Проект не найден".to_string());
    }
    info!("project_export_archive: {} → {}", project_id, output_path);

    let out = PathBuf::from(&output_path);
    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("create parent: {e}"))?;
    }

    let file = std::fs::File::create(&out).map_err(|e| format!("create archive: {e}"))?;
    let mut zip = zip::ZipWriter::new(file);
    let options: SimpleFileOptions = SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated)
        .unix_permissions(0o644);

    // Пишем в архив относительные пути (без project_id как root), чтобы при распаковке
    // можно было восстановить в новый project_dir. root entry — файл project.json.
    let mut file_count = 0u32;
    for entry in walkdir::WalkDir::new(&src).into_iter().filter_map(|e| e.ok()) {
        let path = entry.path();
        let rel = path.strip_prefix(&src).map_err(|e| format!("strip_prefix: {e}"))?;
        if rel.as_os_str().is_empty() {
            continue;
        }
        let rel_str = rel.to_string_lossy().replace('\\', "/");
        if path.is_dir() {
            zip.add_directory(format!("{rel_str}/"), options)
                .map_err(|e| format!("add_directory: {e}"))?;
        } else if path.is_file() {
            zip.start_file(&rel_str, options)
                .map_err(|e| format!("start_file: {e}"))?;
            let data = std::fs::read(path).map_err(|e| format!("read {path:?}: {e}"))?;
            zip.write_all(&data).map_err(|e| format!("write {rel_str}: {e}"))?;
            file_count += 1;
        }
    }

    zip.finish().map_err(|e| format!("zip finish: {e}"))?;
    let size = std::fs::metadata(&out).map(|m| m.len()).unwrap_or(0);
    info!("archive created: {} files, {} bytes", file_count, size);
    Ok(output_path)
}

/// Импорт проекта из zip-архива .aurora. Распаковывает в новый project_id,
/// обновляет project.json (id, created_at — current). Возвращает новый project_id.
#[tauri::command]
pub async fn project_import_archive(archive_path: String) -> Result<Value, String> {
    let archive = PathBuf::from(&archive_path);
    if !archive.exists() {
        return Err("Файл архива не найден".to_string());
    }
    info!("project_import_archive: {}", archive_path);

    // Generate new project_id
    let timestamp = chrono::Local::now().format("%Y%m%d-%H%M%S").to_string();
    let new_id = format!("imported-{timestamp}");
    let dest = projects_dir()?.join(&new_id);

    if dest.exists() {
        return Err(format!("Целевая папка уже существует: {}", dest.display()));
    }
    std::fs::create_dir_all(&dest).map_err(|e| format!("create dest: {e}"))?;

    // Unzip
    let file = std::fs::File::open(&archive).map_err(|e| format!("open archive: {e}"))?;
    let mut zip = zip::ZipArchive::new(file).map_err(|e| format!("read zip: {e}"))?;
    let mut file_count = 0u32;
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i).map_err(|e| format!("zip entry {i}: {e}"))?;
        let enclosed = match entry.enclosed_name() {
            Some(p) => p.to_path_buf(),
            None => continue, // skip malformed paths (zip-slip protection)
        };
        let outpath = dest.join(&enclosed);
        if entry.is_dir() {
            std::fs::create_dir_all(&outpath).map_err(|e| format!("mkdir {outpath:?}: {e}"))?;
        } else {
            if let Some(parent) = outpath.parent() {
                std::fs::create_dir_all(parent).map_err(|e| format!("mkdir parent: {e}"))?;
            }
            let mut outfile = std::fs::File::create(&outpath)
                .map_err(|e| format!("create {outpath:?}: {e}"))?;
            std::io::copy(&mut entry, &mut outfile)
                .map_err(|e| format!("copy {enclosed:?}: {e}"))?;
            file_count += 1;
        }
    }
    info!("archive extracted: {} files into {}", file_count, dest.display());

    // Rewrite project.json → new id + touch updated_at
    let project_json_path = dest.join("project.json");
    if !project_json_path.exists() {
        // Убрать битый импорт
        let _ = std::fs::remove_dir_all(&dest);
        return Err("Архив не содержит project.json — это не проект Aurora Econometrica".to_string());
    }
    let data = std::fs::read_to_string(&project_json_path)
        .map_err(|e| format!("read project.json: {e}"))?;
    let mut info_val: Value = serde_json::from_str(&data)
        .map_err(|e| format!("parse project.json: {e}"))?;
    if let Some(obj) = info_val.as_object_mut() {
        obj.insert("id".to_string(), Value::String(new_id.clone()));
        obj.insert(
            "updated_at".to_string(),
            Value::String(chrono::Local::now().to_rfc3339()),
        );
    }
    std::fs::write(
        &project_json_path,
        serde_json::to_string_pretty(&info_val).map_err(|e| e.to_string())?,
    ).map_err(|e| format!("write project.json: {e}"))?;

    info!("project imported: new_id={}", new_id);
    Ok(serde_json::json!({
        "project_id": new_id,
        "info": info_val,
    }))
}
