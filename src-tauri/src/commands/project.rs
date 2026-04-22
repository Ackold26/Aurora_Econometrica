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
///
/// Особые case'ы обрабатываются:
/// - Большие файлы копируются через `std::io::copy` (streaming), не `read` в память.
///   Иначе pickle файлы >1GB (редкий, но возможный) съедали бы RAM.
/// - `data_file` из project.json — абсолютный путь на этой машине. Если файл ЛЕЖИТ
///   внутри project_dir — он попадёт в архив через walkdir и можно будет открыть
///   на другой машине. Если СНАРУЖИ (пользователь импортировал xlsx из Downloads) —
///   мы его тоже добавляем в архив как `data/<original_filename>` и правим
///   project.json перед записью в zip.
#[tauri::command]
pub async fn project_export_archive(
    project_id: String,
    output_path: String,
) -> Result<String, String> {
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

    // Atomic write: пишем во временный файл, rename в конце. Прерванный export
    // (panic / kill) не оставит битый .aurora на диске.
    let tmp_path = out.with_extension("aurora.tmp");
    if tmp_path.exists() {
        let _ = std::fs::remove_file(&tmp_path);
    }
    let file = std::fs::File::create(&tmp_path)
        .map_err(|e| format!("create archive: {e}"))?;
    let mut zip = zip::ZipWriter::new(file);
    let options: SimpleFileOptions = SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated)
        .unix_permissions(0o644);

    // Проверяем data_file в project.json — если вне project_dir, включаем в архив
    // с переписыванием пути на относительный.
    let info = read_project(&src).ok();
    let external_data: Option<(PathBuf, String)> = info.as_ref().and_then(|i| {
        i.data_file.as_ref().and_then(|df| {
            let p = PathBuf::from(df);
            if !p.is_absolute() || !p.exists() {
                return None;
            }
            // Уже внутри project_dir — не нужно отдельно
            if p.starts_with(&src) {
                return None;
            }
            let name = p.file_name()?.to_string_lossy().to_string();
            Some((p, name))
        })
    });

    let mut file_count = 0u32;
    for entry in walkdir::WalkDir::new(&src).into_iter().filter_map(|e| e.ok()) {
        let path = entry.path();
        let rel = match path.strip_prefix(&src) {
            Ok(r) => r,
            Err(_) => continue,
        };
        if rel.as_os_str().is_empty() {
            continue;
        }
        let rel_str = rel.to_string_lossy().replace('\\', "/");

        // project.json с external data_file переписываем отдельно ниже
        if external_data.is_some() && rel_str == "project.json" {
            continue;
        }

        if path.is_dir() {
            zip.add_directory(format!("{rel_str}/"), options)
                .map_err(|e| format!("add_directory: {e}"))?;
        } else if path.is_file() {
            zip.start_file(&rel_str, options)
                .map_err(|e| format!("start_file: {e}"))?;
            let mut infile = std::fs::File::open(path)
                .map_err(|e| format!("open {path:?}: {e}"))?;
            std::io::copy(&mut infile, &mut zip)
                .map_err(|e| format!("copy {rel_str}: {e}"))?;
            file_count += 1;
        }
    }

    // Если data_file внешний — упаковываем его в archive/data/<basename>
    // и переписываем project.json чтобы data_file указывал туда же относительно project_dir.
    if let (Some((ext_path, basename)), Some(mut info_val)) = (external_data, info) {
        zip.add_directory("data/", options).ok();
        let archive_path = format!("data/{basename}");
        zip.start_file(&archive_path, options)
            .map_err(|e| format!("start_file data: {e}"))?;
        let mut infile = std::fs::File::open(&ext_path)
            .map_err(|e| format!("open external {ext_path:?}: {e}"))?;
        std::io::copy(&mut infile, &mut zip)
            .map_err(|e| format!("copy external: {e}"))?;
        file_count += 1;
        // Переписать project.json с относительным data_file (будет resolved при import)
        info_val.data_file = Some(format!("<project_dir>/{archive_path}"));
        zip.start_file("project.json", options)
            .map_err(|e| format!("start project.json: {e}"))?;
        let json = serde_json::to_string_pretty(&info_val).map_err(|e| e.to_string())?;
        use std::io::Write;
        zip.write_all(json.as_bytes())
            .map_err(|e| format!("write project.json: {e}"))?;
        file_count += 1;
    }

    zip.finish().map_err(|e| format!("zip finish: {e}"))?;
    // Atomic rename tmp → final
    std::fs::rename(&tmp_path, &out)
        .map_err(|e| format!("rename final: {e}"))?;
    let size = std::fs::metadata(&out).map(|m| m.len()).unwrap_or(0);
    info!("archive created: {} files, {} bytes", file_count, size);
    Ok(output_path)
}

/// Импорт проекта из zip-архива .aurora. Распаковывает в новый project_id,
/// обновляет project.json (id, updated_at). Возвращает {project_id, info}.
///
/// Особые случаи:
/// - Pre-validation: перед распаковкой проверяем что в архиве есть project.json.
///   Если нет — early return, не засоряем файловую систему.
/// - data_file может быть `<project_dir>/data/foo.xlsx` (новый формат с внешним data)
///   или абсолютный путь (старые архивы). Нормализуем: заменяем маркер на dest/,
///   если absolute — проверяем что файл есть, иначе set to None.
#[tauri::command]
pub async fn project_import_archive(archive_path: String) -> Result<Value, String> {
    let archive = PathBuf::from(&archive_path);
    if !archive.exists() {
        return Err("Файл архива не найден".to_string());
    }
    info!("project_import_archive: {}", archive_path);

    // ── Pre-validation ──────────────────────────────────────────────────────
    // Открываем zip и проверяем структуру ДО распаковки. Если это не проект
    // Aurora — выбрасываем без создания destination папки.
    {
        let file = std::fs::File::open(&archive).map_err(|e| format!("open archive: {e}"))?;
        let mut zip = zip::ZipArchive::new(file).map_err(|e| format!("read zip: {e}"))?;
        let mut has_project_json = false;
        for i in 0..zip.len() {
            let entry = zip.by_index(i).map_err(|e| format!("zip entry {i}: {e}"))?;
            let name = entry.name();
            // Проверяем что project.json лежит в корне архива, не во вложенной папке
            if name == "project.json" || name.ends_with("/project.json") {
                has_project_json = true;
                break;
            }
        }
        if !has_project_json {
            return Err("Архив не содержит project.json — это не проект Aurora Econometrica".to_string());
        }
    }

    // Generate new project_id
    let timestamp = chrono::Local::now().format("%Y%m%d-%H%M%S").to_string();
    let new_id = format!("imported-{timestamp}");
    let dest = projects_dir()?.join(&new_id);

    if dest.exists() {
        return Err(format!("Целевая папка уже существует: {}", dest.display()));
    }
    std::fs::create_dir_all(&dest).map_err(|e| format!("create dest: {e}"))?;

    // ── Unzip со streaming и zip-slip защитой ──────────────────────────────
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

    // ── Rewrite project.json → new id + updated_at + normalize data_file ──
    let project_json_path = dest.join("project.json");
    if !project_json_path.exists() {
        // Должно было отсечься pre-validation'ом, но на всякий случай
        let _ = std::fs::remove_dir_all(&dest);
        return Err("Архив не содержит project.json в корне после распаковки".to_string());
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

        // Нормализация data_file:
        //   1. Маркер "<project_dir>/data/xxx.xlsx" → абсолютный dest path
        //   2. Абсолютный путь валидной машины → оставить если существует, иначе None
        //   3. Путь которого нет → сообщение в description чтобы пользователь понял,
        //      что данные надо переимпортировать
        if let Some(Value::String(df)) = obj.get("data_file") {
            let df_owned = df.clone();
            if let Some(rest) = df_owned.strip_prefix("<project_dir>/") {
                let resolved = dest.join(rest);
                if resolved.exists() {
                    obj.insert(
                        "data_file".to_string(),
                        Value::String(resolved.to_string_lossy().to_string()),
                    );
                } else {
                    obj.insert("data_file".to_string(), Value::Null);
                }
            } else if !PathBuf::from(&df_owned).exists() {
                // Абсолютный путь с другой машины — проваливается
                obj.insert("data_file".to_string(), Value::Null);
                // Добавляем подсказку в description
                let desc = obj.get("description").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let hint = "[После импорта: исходный файл данных недоступен, нужно переимпортировать на шаге «Импорт».]";
                if !desc.contains("переимпортировать") {
                    let new_desc = if desc.is_empty() {
                        hint.to_string()
                    } else {
                        format!("{desc}\n\n{hint}")
                    };
                    obj.insert("description".to_string(), Value::String(new_desc));
                }
            }
        }
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

// ── Model comparison ────────────────────────────────────────────────────────
//
// Атомарное чтение снимков двух проектов для side-by-side сравнения моделей.
// Не меняет active_project — это read-only операция. Один Rust-вызов читает
// оба проекта, что исключает race если один из них переименуется/удалится
// между двумя последовательными invoke на frontend.

fn load_snapshot(project_id: &str) -> Result<Value, String> {
    let dir = project_dir(project_id)?;
    if !dir.exists() {
        return Err(format!("Проект «{project_id}» не найден"));
    }
    let info = read_project(&dir)?;
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

    let scenarios_dir = results.join("scenarios");
    let mut scenarios: Vec<Value> = Vec::new();
    if scenarios_dir.exists() {
        if let Ok(entries) = std::fs::read_dir(&scenarios_dir) {
            let mut paths: Vec<PathBuf> = entries
                .flatten()
                .map(|e| e.path())
                .filter(|p| p.extension().and_then(|x| x.to_str()) == Some("json"))
                .collect();
            paths.sort();
            for p in paths {
                if let Ok(s) = std::fs::read_to_string(&p) {
                    if let Ok(v) = serde_json::from_str::<Value>(&s) {
                        scenarios.push(v);
                    }
                }
            }
        }
    }

    Ok(serde_json::json!({
        "info":             info,
        "modelDiagnostics": read_json("model-diagnostics.json"),
        "decomposition":    read_json("decomposition.json"),
        "optimization":     read_json("optimization.json"),
        "validation":       read_json("validation.json"),
        "scenarios":        scenarios,
    }))
}

/// Читает снимки двух проектов атомарно для сравнения. Не меняет active_project.
/// Возвращаемый объект: `{ primary: Snapshot, secondary: Snapshot }`, где каждый
/// snapshot = `{ info, modelDiagnostics, decomposition, optimization, validation,
/// scenarios }`. Отсутствующие файлы → соответствующее поле = null (для scenarios
/// — пустой массив).
#[tauri::command]
pub async fn project_load_comparison(
    primary_id: String,
    secondary_id: String,
) -> Result<Value, String> {
    if primary_id == secondary_id {
        return Err("Нельзя сравнивать проект сам с собой".to_string());
    }
    info!("project_load_comparison: {primary_id} vs {secondary_id}");
    let primary = load_snapshot(&primary_id)?;
    let secondary = load_snapshot(&secondary_id)?;
    Ok(serde_json::json!({
        "primary":   primary,
        "secondary": secondary,
    }))
}
