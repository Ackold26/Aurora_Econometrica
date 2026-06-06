//! Econometrica project management.
//!
//! One project = one client/dataset + trained models + results + scenarios.
//! Stored in %APPDATA%/<identifier>/projects/ (filesystem-first, no RAG).

use log::{info, warn};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock, RwLock};

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
    /// Для каналов в рублях - 1.0 или отсутствие записи.
    #[serde(default)]
    pub unit_costs: HashMap<String, f64>,
    /// L1 (math-fix v1.4 Section C, 2026-04-29): explicit excluded columns
    /// для cross-session restore. Pre-fix: excluded set was derived from
    /// "not in kpi/media/control/date" - fragile когда new columns появляются
    /// в re-validation (validator might detect them as media). Explicit list
    /// preserves user's «не использовать» decision across project reload.
    /// Backward compat: default empty for projects saved до v1.0.16.
    #[serde(default)]
    pub excluded_columns: Vec<String>,
    /// Trust Level 3 (v1.1.0): brand vs performance categorization per channel.
    /// Values: "brand" / "performance" / "mixed".
    /// Empty / all-mixed → backward compat single-prior path в modeler.
    /// ≥2 brand or ≥2 performance каналов → hierarchical priors включаются.
    /// Backward compat: default empty for projects saved до v1.1.0.
    #[serde(default)]
    pub channel_categories: HashMap<String, String>,
    /// Phase 2 audit pass 4 (2026-05-02): per-channel annual CPP/CPM inflation
    /// rate (%/year) для multi-year training data. Customer enters cost в
    /// последний год training; backend computes weighted-average через rollback.
    /// Backward compat: default empty (no adjustment) for legacy projects.
    #[serde(default)]
    pub unit_cost_inflation_pct: HashMap<String, f64>,
    /// H-09 (Phase 4.1 wire): industry для context-aware unit_cost suggestions.
    /// Values matching INDUSTRY_CPP_TABLE в src/lib/services/industry-cpp-defaults.js:
    /// pharma_otc / pharma_rx / fmcg / retail / saas / finance / b2b / unknown.
    /// Backward compat: default "unknown" — UI shows low-confidence generic ranges.
    /// Schema bump к v2.0.2 (project_migration.py).
    #[serde(default = "default_industry")]
    pub industry: String,
    /// LOAD-1 (2026-06-06): count-KPI train-входы, влияющие на posterior. Не
    /// персистились → reset при reload → re-train count-KPI давал иной posterior
    /// (re-train артефакт). `kpi_type` → competitor prior 0.0↔−0.3 (modeler.py:461);
    /// `kpi_kind`+`value_per_count_unit` → kpi_unit_cost (ROI money conversion).
    /// Persist здесь + ре-гидрация в activeProject.subscribe закрывают артефакт.
    /// Backward compat: None для legacy проектов (до этого фикса).
    #[serde(default)]
    pub kpi_type: Option<String>,
    #[serde(default)]
    pub kpi_kind: Option<String>,
    #[serde(default)]
    pub value_per_count_unit: Option<f64>,
    /// LOAD-1 (2026-06-07): режим анализа (`roi`/`effectiveness`/`mixed`). Влияет
    /// на cpp-гейт обучения: physical-канал в `roi`-режиме без unit_cost = ROI-артефакт.
    /// Не персистился → reset в `roi` на reload → effectiveness-проект (валидный с
    /// physical-метриками без ₽) ложно блокировался бы cpp-гейтом в trainModel.
    /// Persist здесь + ре-гидрация id-guard'ом закрывают это. Legacy без поля → None:
    /// front-енд НЕ применяет cpp-гейт к legacy-проектам (fail-open к pre-fix поведению,
    /// иначе гейт = регрессия на всех существующих effectiveness-проектах).
    /// Backward compat: None для legacy проектов (до этого фикса).
    #[serde(default)]
    pub analysis_mode: Option<String>,
    /// LOAD-1 (2026-06-07): per-channel toggle ВКЛ/ВЫКЛ из ConfigPanel (НЕ роль —
    /// media_columns это роль). Не персистился → reload ре-init из `zeros_pct>80`
    /// default → ручной disabled low-zeros канал РЕ-ВКЛЮЧАЛСЯ → re-train с иным
    /// набором media_columns = иная модель. Persist здесь + seed `resolveChannelEnabled`
    /// (persisted имеет приоритет над zeros-default) закрывают это.
    /// Backward compat: пустой для legacy → seed падает на zeros-default (pre-fix).
    #[serde(default)]
    pub model_channel_enabled: HashMap<String, bool>,
    /// LOAD-1 D-1 (2026-06-07): per-channel выбор метрики `monetary`/`physical`
    /// (ValidateStepV13 override детектора). Стал ВХОДОМ cpp-гейта обучения (тип канала =
    /// `per_channel_input[name] ?? detectChannelUnitType(name)`). Не персистился → reset на
    /// reload → гейт падал на детектор по имени → physical-имя+override='monetary'+no-cost+roi
    /// = ложный over-block валидного обучения. Persist здесь + ре-гидрация id-guard'ом дают
    /// гейту реальный выбор юзера, не эвристику имени. Backward compat: пустой для legacy.
    #[serde(default)]
    pub per_channel_input: HashMap<String, String>,
}

fn default_industry() -> String {
    "unknown".to_string()
}

/// Get the projects root directory.
/// Priority: env AURORA_PROJECTS_ROOT > user_config.econometrica_projects_root > default.
/// Default: %APPDATA%/<identifier>/projects/
pub fn projects_dir() -> Result<PathBuf, String> {
    let appdata = std::env::var("APPDATA")
        .map_err(|_| "APPDATA not set".to_string())?;
    let identifier = env!("CARGO_PKG_NAME");

    // Env override - для тестов и advanced users.
    if let Ok(env_root) = std::env::var("AURORA_PROJECTS_ROOT") {
        if !env_root.trim().is_empty() {
            let dir = PathBuf::from(env_root.trim());
            std::fs::create_dir_all(&dir)
                .map_err(|e| format!("Failed to create projects dir (env): {e}"))?;
            return Ok(dir);
        }
    }

    // User-configured override - читаем user_config.json напрямую с диска
    // (без AppHandle - чтобы не менять сигнатуру во всех вызовах вверх по стеку).
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

/// C-04: atomic write through tmp-file + rename pattern.
///
/// Raw `std::fs::write` non-atomic: power loss или antivirus quarantine между
/// write и flush → truncated project.json без recovery. Pattern (тот же что
/// Python safe_io.atomic_write_json):
///   1. Serialize к json string
///   2. Open `<path>.tmp` для write
///   3. write_all + sync_all (fsync equivalent — bytes на disk)
///   4. Close
///   5. fs::rename(tmp, target) — atomic on same volume
fn write_project(dir: &Path, info: &ProjectInfo) -> Result<(), String> {
    use std::io::Write;
    let path = dir.join("project.json");
    let json = serde_json::to_string_pretty(info)
        .map_err(|e| format!("Serialize error: {e}"))?;
    let tmp = path.with_extension("json.tmp");
    {
        let mut f = std::fs::File::create(&tmp)
            .map_err(|e| format!("Open tmp: {e}"))?;
        f.write_all(json.as_bytes())
            .map_err(|e| format!("Write tmp: {e}"))?;
        f.sync_all().map_err(|e| format!("Sync tmp: {e}"))?;
    }
    std::fs::rename(&tmp, &path)
        .map_err(|e| format!("Rename tmp→target: {e}"))
}

/// C-04: per-project mutex registry для serialize read-modify-write pairs.
///
/// Raw read_project + write_project — TOCTOU race: user edits name while data
/// upload runs concurrently → second write reads pre-mutation state, overwrites
/// first commit. Per-project Arc<Mutex<()>> — concurrent writes на разные projects
/// независимы; concurrent writes на same project serialize.
static PROJECT_MUTEXES: OnceLock<RwLock<HashMap<String, Arc<Mutex<()>>>>> = OnceLock::new();

fn project_mutex(project_id: &str) -> Arc<Mutex<()>> {
    let map = PROJECT_MUTEXES.get_or_init(|| RwLock::new(HashMap::new()));
    // Fast path: read lock на existing entry.
    {
        let r = map.read().expect("PROJECT_MUTEXES poisoned");
        if let Some(m) = r.get(project_id) {
            return m.clone();
        }
    }
    // Slow path: insert under write lock.
    let mut w = map.write().expect("PROJECT_MUTEXES poisoned");
    w.entry(project_id.to_string())
        .or_insert_with(|| Arc::new(Mutex::new(())))
        .clone()
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
            if entry.file_type().is_ok_and(|t| t.is_dir()) {
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
pub async fn project_create(name: String, industry: Option<String>) -> Result<ProjectInfo, String> {
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
    // H-09: industry whitelist (mirrors INDUSTRY_CPP_TABLE keys в frontend).
    let industry_validated = match industry.as_deref() {
        Some("pharma_otc") | Some("pharma_rx") | Some("fmcg") | Some("retail")
        | Some("saas") | Some("finance") | Some("b2b") | Some("unknown")
            => industry.unwrap(),
        _ => "unknown".to_string(),
    };
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
        excluded_columns: Vec::new(),
        channel_categories: HashMap::new(),
        unit_cost_inflation_pct: HashMap::new(),
        industry: industry_validated,
        kpi_type: None,
        kpi_kind: None,
        value_per_count_unit: None,
        analysis_mode: None,
        model_channel_enabled: HashMap::new(),
        per_channel_input: HashMap::new(),
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
    // C-04 TOCTOU guard: serialize read+write pair с per-project mutex.
    let mtx = project_mutex(&project_id);
    let _guard = mtx.lock().expect("project mutex poisoned");
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
        // Trust Level 3 (Critical Audit issue J): cleanup orphaned channel_categories
        // entries when media columns change (rename/delete).
        let media_set: std::collections::HashSet<&String> = info.media_columns.iter().collect();
        info.channel_categories.retain(|k, _| media_set.contains(k));
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
    // Phase 2 audit pass 5 fix (BUG B5): persist unit_cost_inflation_pct map.
    // Pre-fix: project_update silently ignored this key → values lost после
    // save reload. Now: explicit handler + null support (clears map).
    if let Some(infl_v) = updates.get("unit_cost_inflation_pct") {
        if infl_v.is_null() {
            info.unit_cost_inflation_pct.clear();
        } else if let Some(obj) = infl_v.as_object() {
            info.unit_cost_inflation_pct = obj.iter()
                .filter_map(|(k, v)| v.as_f64().map(|f| (k.clone(), f)))
                .collect();
        }
    }
    // L1 persistence (math-fix v1.4 Section C): explicit excluded_columns set
    if let Some(excluded) = updates.get("excluded_columns").and_then(|v| v.as_array()) {
        info.excluded_columns = excluded.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect();
    }
    // Trust Level 3 (v1.1.0): channel_categories persistence.
    // Validate values на server side - only accept brand/performance/mixed.
    if let Some(cats) = updates.get("channel_categories").and_then(|v| v.as_object()) {
        let allowed: std::collections::HashSet<&str> = ["brand", "performance", "mixed"].iter().copied().collect();
        info.channel_categories = cats.iter()
            .filter_map(|(k, v)| {
                v.as_str().and_then(|s| {
                    if allowed.contains(s) { Some((k.clone(), s.to_string())) } else { None }
                })
            })
            .collect();
    }
    // H-09: industry update — whitelist same как в project_create.
    if let Some(ind) = updates.get("industry").and_then(|v| v.as_str()) {
        let allowed = ["pharma_otc", "pharma_rx", "fmcg", "retail", "saas", "finance", "b2b", "unknown"];
        if allowed.contains(&ind) {
            info.industry = ind.to_string();
        }
    }
    // LOAD-1 (2026-06-06): persist count-KPI train-входы (kpi_type→prior, kpi_kind+
    // value_per_count_unit→kpi_unit_cost). Без них re-train после reload давал иной
    // posterior. value_per_count_unit: null очищает (переключение с count на monetary).
    if let Some(kt) = updates.get("kpi_type").and_then(|v| v.as_str()) {
        info.kpi_type = Some(kt.to_string());
    }
    if let Some(kk) = updates.get("kpi_kind").and_then(|v| v.as_str()) {
        info.kpi_kind = Some(kk.to_string());
    }
    if let Some(vpcu) = updates.get("value_per_count_unit") {
        if vpcu.is_null() {
            info.value_per_count_unit = None;
        } else if let Some(f) = vpcu.as_f64() {
            info.value_per_count_unit = Some(f);
        }
    }
    // LOAD-1 (2026-06-07): persist analysis_mode (roi/effectiveness/mixed) → cpp-гейт
    // обучения переживает reload. Без него effectiveness-проект reset в roi → ложный блок.
    if let Some(am) = updates.get("analysis_mode").and_then(|v| v.as_str()) {
        info.analysis_mode = Some(am.to_string());
    }
    // LOAD-1 (2026-06-07): persist per-channel toggle (ВКЛ/ВЫКЛ) → reload не ре-включает
    // ручной disabled канал. Замена целиком (карта тоглов из ConfigPanel — полная).
    if let Some(mce) = updates.get("model_channel_enabled").and_then(|v| v.as_object()) {
        info.model_channel_enabled = mce.iter()
            .filter_map(|(k, v)| v.as_bool().map(|b| (k.clone(), b)))
            .collect();
    }
    // LOAD-1 D-1 (2026-06-07): persist per-channel метрику → cpp-гейт на reload судит
    // по реальному выбору юзера, не по детектору имени. Замена целиком (карта из ValidateStep).
    if let Some(pci) = updates.get("per_channel_input").and_then(|v| v.as_object()) {
        info.per_channel_input = pci.iter()
            .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
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

    // Update project metadata — C-04 TOCTOU guard.
    let mtx = project_mutex(&project_id);
    let _guard = mtx.lock().expect("project mutex poisoned");
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
    use std::io::Write;
    let path = active_project_path()?;
    let json = serde_json::json!({ "active_project": project_id });
    let serialized = serde_json::to_string_pretty(&json)
        .map_err(|e| format!("Serialize error: {e}"))?;
    // C-04: atomic write via tmp + rename (тот же pattern что write_project).
    let tmp = path.with_extension("json.tmp");
    {
        let mut f = std::fs::File::create(&tmp).map_err(|e| e.to_string())?;
        f.write_all(serialized.as_bytes()).map_err(|e| e.to_string())?;
        f.sync_all().map_err(|e| e.to_string())?;
    }
    std::fs::rename(&tmp, &path)
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
        return Err("Проект не найден".to_string());
    }

    let has_data = dir.join("data").read_dir()
        .map(|mut d| d.any(|_| true))
        .unwrap_or(false);
    let has_model = dir.join("models").join("latest.pkl").exists();
    let has_decomposition = dir.join("results").join("decomposition.json").exists();
    let has_optimization = dir.join("results").join("optimization.json").exists();
    let n_scenarios = dir.join("results").join("scenarios")
        .read_dir()
        .map(|d| d.flatten().filter(|e| e.path().extension().is_some_and(|ext| ext == "json")).count())
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
        // Defense-in-depth (2026-06-04 fresh-train аудит): НЕ молчать при ошибке
        // парса. Раньше `.ok()...unwrap_or(Null)` молча терял данные, если Python
        // писал NaN/Inf (невалидный JSON) → Отчёт «модель не загружена» без следа.
        // Python-сторона теперь NaN-safe (sanitize_nonfinite); этот лог ловит рецидив.
        match std::fs::read_to_string(&path) {
            Ok(s) => match serde_json::from_str::<Value>(&s) {
                Ok(v) => v,
                Err(e) => {
                    warn!("project_load_results: '{name}' parse failed → null ({e}). Возможно NaN/Inf в JSON.");
                    Value::Null
                }
            },
            Err(e) => {
                warn!("project_load_results: '{name}' read failed → null ({e}).");
                Value::Null
            }
        }
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
/// output_path - обычно путь из dialog.save на фронте.
///
/// Особые case'ы обрабатываются:
/// - Большие файлы копируются через `std::io::copy` (streaming), не `read` в память.
///   Иначе pickle файлы >1GB (редкий, но возможный) съедали бы RAM.
/// - `data_file` из project.json - абсолютный путь на этой машине. Если файл ЛЕЖИТ
///   внутри project_dir - он попадёт в архив через walkdir и можно будет открыть
///   на другой машине. Если СНАРУЖИ (пользователь импортировал xlsx из Downloads) -
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

    // Проверяем data_file в project.json - если вне project_dir, включаем в архив
    // с переписыванием пути на относительный.
    let info = read_project(&src).ok();
    let external_data: Option<(PathBuf, String)> = info.as_ref().and_then(|i| {
        i.data_file.as_ref().and_then(|df| {
            let p = PathBuf::from(df);
            if !p.is_absolute() || !p.exists() {
                return None;
            }
            // Уже внутри project_dir - не нужно отдельно
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

    // Если data_file внешний - упаковываем его в archive/data/<basename>
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
///   Если нет - early return, не засоряем файловую систему.
/// - data_file может быть `<project_dir>/data/foo.xlsx` (новый формат с внешним data)
///   или абсолютный путь (старые архивы). Нормализуем: заменяем маркер на dest/,
///   если absolute - проверяем что файл есть, иначе set to None.
#[tauri::command]
pub async fn project_import_archive(archive_path: String) -> Result<Value, String> {
    let archive = PathBuf::from(&archive_path);
    if !archive.exists() {
        return Err("Файл архива не найден".to_string());
    }
    info!("project_import_archive: {}", archive_path);

    // ── Pre-validation ──────────────────────────────────────────────────────
    // Открываем zip и проверяем структуру ДО распаковки. Если это не проект
    // Aurora - выбрасываем без создания destination папки.
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
            return Err("Архив не содержит project.json - это не проект Aurora Econometrica".to_string());
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
                // Абсолютный путь с другой машины - проваливается
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
// Не меняет active_project - это read-only операция. Один Rust-вызов читает
// оба проекта, что исключает race если один из них переименуется/удалится
// между двумя последовательными invoke на frontend.

fn load_snapshot(project_id: &str) -> Result<Value, String> {
    let dir = project_dir(project_id)?;
    if !dir.exists() {
        return Err(format!("Проект «{project_id}» не найден"));
    }
    load_snapshot_from_dir(&dir)
}

/// Pure-функция чтения snapshot'а из директории проекта.
/// Не зависит от project_id / projects_dir() - для тестируемости.
fn load_snapshot_from_dir(dir: &Path) -> Result<Value, String> {
    if !dir.exists() {
        return Err(format!("Директория не найдена: {}", dir.display()));
    }
    let info = read_project(dir)?;
    let results = dir.join("results");

    let read_json = |name: &str| -> Value {
        let path = results.join(name);
        if !path.exists() {
            return Value::Null;
        }
        // Defense-in-depth (2026-06-04 fresh-train аудит): НЕ молчать при ошибке
        // парса. Раньше `.ok()...unwrap_or(Null)` молча терял данные, если Python
        // писал NaN/Inf (невалидный JSON) → Отчёт «модель не загружена» без следа.
        // Python-сторона теперь NaN-safe (sanitize_nonfinite); этот лог ловит рецидив.
        match std::fs::read_to_string(&path) {
            Ok(s) => match serde_json::from_str::<Value>(&s) {
                Ok(v) => v,
                Err(e) => {
                    warn!("project_load_results: '{name}' parse failed → null ({e}). Возможно NaN/Inf в JSON.");
                    Value::Null
                }
            },
            Err(e) => {
                warn!("project_load_results: '{name}' read failed → null ({e}).");
                Value::Null
            }
        }
    };

    // Лимит сценариев для comparison - снимок 50 последних (по mtime) чтобы
    // не блокировать FastAPI handler при 100+ сценариев. Фронт показывает
    // warning если scenarios_total > scenarios.len.
    const SCENARIO_LIMIT: usize = 50;
    let scenarios_dir = results.join("scenarios");
    let mut scenarios: Vec<Value> = Vec::new();
    let mut total_scenarios_count = 0usize;
    if scenarios_dir.exists() {
        if let Ok(entries) = std::fs::read_dir(&scenarios_dir) {
            let mut entries_with_mtime: Vec<(PathBuf, std::time::SystemTime)> = entries
                .flatten()
                .filter_map(|e| {
                    let p = e.path();
                    if p.extension().and_then(|x| x.to_str()) != Some("json") {
                        return None;
                    }
                    let mtime = e.metadata().ok()?.modified().ok()?;
                    Some((p, mtime))
                })
                .collect();
            // Sort newest first (mtime desc)
            entries_with_mtime.sort_by_key(|b| std::cmp::Reverse(b.1));
            total_scenarios_count = entries_with_mtime.len();
            entries_with_mtime.truncate(SCENARIO_LIMIT);
            for (p, _) in entries_with_mtime {
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
        "scenarios_total":  total_scenarios_count,
    }))
}

/// Читает снимки двух проектов атомарно для сравнения. Не меняет active_project.
/// Возвращаемый объект: `{ primary: Snapshot, secondary: Snapshot }`, где каждый
/// snapshot = `{ info, modelDiagnostics, decomposition, optimization, validation,
/// scenarios }`. Отсутствующие файлы → соответствующее поле = null (для scenarios
/// - пустой массив).
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

// ── Tests ──────────────────────────────────────────────────────────────────
#[cfg(test)]
mod comparison_tests {
    use super::*;
    use std::fs;
    use std::path::Path;
    use tempfile::TempDir;

    /// Создаёт минимальную валидную структуру проекта в tmp dir.
    /// `scenario_count` > 0 → в results/scenarios кладутся N JSON-файлов
    /// с убывающим mtime (последний файл - самый свежий).
    fn make_project(dir: &Path, scenario_count: usize) {
        let info = serde_json::json!({
            "id": "test-project",
            "name": "Test",
            "description": "",
            "created_at": "2026-04-23T00:00:00Z",
            "updated_at": "2026-04-23T00:00:00Z",
            "kpi_column": null,
            "media_columns": [],
            "control_columns": [],
            "data_file": null,
            "unit_costs": {},
        });
        fs::write(dir.join("project.json"), info.to_string()).unwrap();

        if scenario_count > 0 {
            let scenarios = dir.join("results").join("scenarios");
            fs::create_dir_all(&scenarios).unwrap();
            for i in 0..scenario_count {
                // Имя кодирует индекс - поможет позже проверить порядок.
                let path = scenarios.join(format!("scenario_{i:04}.json"));
                fs::write(&path, format!(r#"{{"idx":{i}}}"#)).unwrap();
                // Выставляем mtime: более высокий индекс = более свежий.
                let mtime = std::time::SystemTime::UNIX_EPOCH
                    + std::time::Duration::from_secs(1_700_000_000 + i as u64);
                filetime::set_file_mtime(&path, filetime::FileTime::from_system_time(mtime)).ok();
            }
        }
    }

    #[test]
    fn nonexistent_dir_returns_err() {
        let tmp = TempDir::new().unwrap();
        let missing = tmp.path().join("does-not-exist");
        let result = load_snapshot_from_dir(&missing);
        assert!(result.is_err(), "nonexistent dir должен вернуть Err, got {result:?}");
    }

    #[test]
    fn zero_scenarios_returns_empty_array() {
        let tmp = TempDir::new().unwrap();
        make_project(tmp.path(), 0);
        let snapshot = load_snapshot_from_dir(tmp.path()).expect("valid project");
        assert_eq!(snapshot["scenarios"].as_array().unwrap().len(), 0);
        assert_eq!(snapshot["scenarios_total"].as_u64().unwrap(), 0);
    }

    #[test]
    fn limits_to_50_newest_by_mtime() {
        let tmp = TempDir::new().unwrap();
        make_project(tmp.path(), 100);
        let snapshot = load_snapshot_from_dir(tmp.path()).expect("valid project");
        let scenarios = snapshot["scenarios"].as_array().unwrap();
        assert_eq!(scenarios.len(), 50, "должно быть ровно 50 сценариев");
        assert_eq!(snapshot["scenarios_total"].as_u64().unwrap(), 100);
        // Проверяем что выбраны именно 50 свежих (индексы 50-99).
        // Порядок внутри массива - от newest (idx=99) к старейшим (idx=50).
        let first_idx = scenarios[0]["idx"].as_u64().unwrap();
        let last_idx = scenarios[49]["idx"].as_u64().unwrap();
        assert_eq!(first_idx, 99, "первый = самый свежий");
        assert_eq!(last_idx, 50, "50-й = граница");
    }
}

// ── C-04 atomic write_project + mutex tests ──
#[cfg(test)]
mod atomic_write_tests {
    use super::*;
    use tempfile::TempDir;

    fn make_info(id: &str, name: &str) -> ProjectInfo {
        ProjectInfo {
            id: id.to_string(),
            name: name.to_string(),
            description: String::new(),
            created_at: "2026-05-15T00:00:00Z".to_string(),
            updated_at: "2026-05-15T00:00:00Z".to_string(),
            kpi_column: None,
            media_columns: vec![],
            control_columns: vec![],
            data_file: None,
            unit_costs: HashMap::new(),
            excluded_columns: vec![],
            channel_categories: HashMap::new(),
            unit_cost_inflation_pct: HashMap::new(),
            industry: "unknown".to_string(),
            kpi_type: None,
            kpi_kind: None,
            value_per_count_unit: None,
            analysis_mode: None,
            model_channel_enabled: HashMap::new(),
            per_channel_input: HashMap::new(),
        }
    }

    #[test]
    fn write_project_atomic_no_tmp_leftover() {
        let tmp = TempDir::new().unwrap();
        let info = make_info("test", "Test");
        write_project(tmp.path(), &info).expect("write OK");
        assert!(tmp.path().join("project.json").exists());
        // No `.tmp` leftover после успешной atomic write.
        assert!(!tmp.path().join("project.json.tmp").exists());
    }

    #[test]
    fn write_project_roundtrip_preserves_fields() {
        let tmp = TempDir::new().unwrap();
        let mut info = make_info("rt", "Round-trip");
        info.media_columns = vec!["tv_spend".to_string(), "olv_impressions".to_string()];
        info.unit_costs.insert("tv_spend".to_string(), 1.0);
        write_project(tmp.path(), &info).unwrap();
        let loaded = read_project(tmp.path()).unwrap();
        assert_eq!(loaded.media_columns, info.media_columns);
        assert_eq!(loaded.unit_costs.get("tv_spend"), Some(&1.0));
    }

    #[test]
    fn write_project_roundtrip_preserves_count_kpi_train_inputs() {
        // LOAD-1 (2026-06-06): count-KPI train-входы должны переживать save/reload.
        let tmp = TempDir::new().unwrap();
        let mut info = make_info("ck", "Count KPI");
        info.kpi_type = Some("sales_packs".to_string());
        info.kpi_kind = Some("count".to_string());
        info.value_per_count_unit = Some(150.0);
        write_project(tmp.path(), &info).unwrap();
        let loaded = read_project(tmp.path()).unwrap();
        assert_eq!(loaded.kpi_type.as_deref(), Some("sales_packs"));
        assert_eq!(loaded.kpi_kind.as_deref(), Some("count"));
        assert_eq!(loaded.value_per_count_unit, Some(150.0));
    }

    #[test]
    fn read_project_legacy_json_without_count_kpi_fields_defaults_none() {
        // Backward compat: legacy project.json (до фикса) не имеет новых полей →
        // serde(default) → None (не падение десериализации).
        let tmp = TempDir::new().unwrap();
        let legacy = r#"{
            "id": "legacy", "name": "Legacy", "description": "",
            "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-01T00:00:00Z",
            "kpi_column": "sales", "media_columns": ["tv"], "control_columns": [],
            "data_file": null
        }"#;
        std::fs::write(tmp.path().join("project.json"), legacy).unwrap();
        let loaded = read_project(tmp.path()).unwrap();
        assert_eq!(loaded.kpi_type, None);
        assert_eq!(loaded.kpi_kind, None);
        assert_eq!(loaded.value_per_count_unit, None);
        assert_eq!(loaded.kpi_column.as_deref(), Some("sales"));
    }

    #[test]
    fn write_project_roundtrip_preserves_analysis_mode() {
        // LOAD-1 (2026-06-07): analysis_mode должен переживать save/reload (cpp-гейт).
        let tmp = TempDir::new().unwrap();
        let mut info = make_info("am", "Analysis Mode");
        info.analysis_mode = Some("effectiveness".to_string());
        write_project(tmp.path(), &info).unwrap();
        let loaded = read_project(tmp.path()).unwrap();
        assert_eq!(loaded.analysis_mode.as_deref(), Some("effectiveness"));
    }

    #[test]
    fn write_project_roundtrip_preserves_model_channel_enabled() {
        // LOAD-1 (2026-06-07): toggle-карта каналов должна переживать save/reload.
        let tmp = TempDir::new().unwrap();
        let mut info = make_info("mce", "Channel Toggle");
        info.model_channel_enabled.insert("tv_trp".to_string(), false);
        info.model_channel_enabled.insert("digital_spend".to_string(), true);
        write_project(tmp.path(), &info).unwrap();
        let loaded = read_project(tmp.path()).unwrap();
        assert_eq!(loaded.model_channel_enabled.get("tv_trp"), Some(&false));
        assert_eq!(loaded.model_channel_enabled.get("digital_spend"), Some(&true));
    }

    #[test]
    fn write_project_roundtrip_preserves_per_channel_input() {
        // LOAD-1 D-1 (2026-06-07): per-channel метрика должна переживать save/reload (cpp-гейт).
        let tmp = TempDir::new().unwrap();
        let mut info = make_info("pci", "Per Channel Input");
        info.per_channel_input.insert("tv_trp".to_string(), "monetary".to_string());
        info.per_channel_input.insert("digital".to_string(), "physical".to_string());
        write_project(tmp.path(), &info).unwrap();
        let loaded = read_project(tmp.path()).unwrap();
        assert_eq!(loaded.per_channel_input.get("tv_trp").map(|s| s.as_str()), Some("monetary"));
        assert_eq!(loaded.per_channel_input.get("digital").map(|s| s.as_str()), Some("physical"));
    }

    #[test]
    fn read_project_legacy_json_without_per_channel_input_defaults_empty() {
        // Backward compat: legacy без поля → serde(default) → пустая карта → гейт падает
        // на detectChannelUnitType (pre-D-1 поведение). NB: гейт enforce только при
        // analysis_mode persisted (D-2 fail-open), legacy → ungated.
        let tmp = TempDir::new().unwrap();
        let legacy = r#"{
            "id": "legacy", "name": "Legacy", "description": "",
            "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-01T00:00:00Z",
            "kpi_column": "sales", "media_columns": ["tv"], "control_columns": [],
            "data_file": null
        }"#;
        std::fs::write(tmp.path().join("project.json"), legacy).unwrap();
        let loaded = read_project(tmp.path()).unwrap();
        assert!(loaded.per_channel_input.is_empty());
    }

    #[test]
    fn read_project_legacy_json_without_model_channel_enabled_defaults_empty() {
        // Backward compat: legacy без поля → serde(default) → пустая карта →
        // seed resolveChannelEnabled падает на zeros-default (pre-fix поведение).
        let tmp = TempDir::new().unwrap();
        let legacy = r#"{
            "id": "legacy", "name": "Legacy", "description": "",
            "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-01T00:00:00Z",
            "kpi_column": "sales", "media_columns": ["tv"], "control_columns": [],
            "data_file": null
        }"#;
        std::fs::write(tmp.path().join("project.json"), legacy).unwrap();
        let loaded = read_project(tmp.path()).unwrap();
        assert!(loaded.model_channel_enabled.is_empty());
    }

    #[test]
    fn read_project_legacy_json_without_analysis_mode_defaults_none() {
        // D-2 (адверс. дизайн-аудит 2026-06-07): legacy project.json без analysis_mode →
        // serde(default) → None. Фронт-енд по None НЕ применяет cpp-гейт (fail-open),
        // иначе гейт = регрессия на существующих effectiveness-проектах.
        let tmp = TempDir::new().unwrap();
        let legacy = r#"{
            "id": "legacy", "name": "Legacy", "description": "",
            "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-01T00:00:00Z",
            "kpi_column": "sales", "media_columns": ["tv"], "control_columns": [],
            "data_file": null
        }"#;
        std::fs::write(tmp.path().join("project.json"), legacy).unwrap();
        let loaded = read_project(tmp.path()).unwrap();
        assert_eq!(loaded.analysis_mode, None);
    }

    #[test]
    fn project_mutex_returns_same_arc_for_same_id() {
        let m1 = project_mutex("p1");
        let m2 = project_mutex("p1");
        assert!(Arc::ptr_eq(&m1, &m2), "same project_id → same mutex Arc");
    }

    #[test]
    fn project_mutex_returns_different_arc_for_different_ids() {
        let m1 = project_mutex("alpha");
        let m2 = project_mutex("beta");
        assert!(!Arc::ptr_eq(&m1, &m2), "different ids → independent mutexes");
    }

    #[test]
    fn project_mutex_serializes_concurrent_locks_same_id() {
        use std::sync::atomic::{AtomicU32, Ordering};
        use std::thread;

        let counter = Arc::new(AtomicU32::new(0));
        let max_concurrent = Arc::new(AtomicU32::new(0));

        let handles: Vec<_> = (0..8)
            .map(|_| {
                let counter = counter.clone();
                let max_concurrent = max_concurrent.clone();
                thread::spawn(move || {
                    let mtx = project_mutex("shared");
                    let _g = mtx.lock().unwrap();
                    let cur = counter.fetch_add(1, Ordering::SeqCst) + 1;
                    max_concurrent.fetch_max(cur, Ordering::SeqCst);
                    std::thread::sleep(std::time::Duration::from_millis(10));
                    counter.fetch_sub(1, Ordering::SeqCst);
                })
            })
            .collect();
        for h in handles {
            h.join().unwrap();
        }
        // Только один thread должен держать lock в любой момент.
        assert_eq!(max_concurrent.load(Ordering::SeqCst), 1,
            "concurrent count must never exceed 1 (mutex serialization)");
    }
}
