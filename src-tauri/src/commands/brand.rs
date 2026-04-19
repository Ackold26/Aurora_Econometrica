//! Filesystem-first Brand Layer for Aurora AI Creative Hub.
//!
//! Brands are stored as JSON files on disk. RAG server is an optional
//! enhancement for vector search — all CRUD operations work without Python.

use log::info;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::{Path, PathBuf};
use tauri::Manager;

const RAG_BASE: &str = "http://127.0.0.1:7420";

// ── Data Structures ──────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrandInfo {
    pub brand_id: String,
    pub name: String,
    #[serde(default)]
    pub industry: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrandStats {
    pub brand_id: String,
    pub documents: u64,
    pub raw_data_files: u64,
    #[serde(default)]
    pub vectors: u64,
    #[serde(default)]
    pub rag_available: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActiveBrandResponse {
    pub active_brand: Option<String>,
}

// ── Filesystem Helpers ───────────────────────────────────

/// Brands root: `%APPDATA%/<identifier>/brands/`
fn brands_dir(app_handle: &tauri::AppHandle) -> Result<PathBuf, String> {
    let config_dir = app_handle.path().app_config_dir().map_err(|e| e.to_string())?;
    let dir = config_dir.join("brands");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir)
}

/// Path to a specific brand: `brands/<brand_id>/brand.json`
fn brand_file(brands_dir: &Path, brand_id: &str) -> PathBuf {
    brands_dir.join(brand_id).join("brand.json")
}

/// Path to active brand marker: `brands/active_brand.json`
fn active_brand_file(brands_dir: &Path) -> PathBuf {
    brands_dir.join("active_brand.json")
}

/// Path to brand documents dir: `brands/<brand_id>/documents/`
fn brand_docs_dir(brands_dir: &Path, brand_id: &str) -> PathBuf {
    brands_dir.join(brand_id).join("documents")
}

/// Path to brand history dir: `brands/<brand_id>/history/`
fn brand_history_dir(brands_dir: &Path, brand_id: &str) -> PathBuf {
    brands_dir.join(brand_id).join("history")
}

/// Validate brand_id: no path traversal, no special chars.
fn validate_brand_id(brand_id: &str) -> Result<(), String> {
    if brand_id.is_empty() {
        return Err("Brand ID cannot be empty".to_string());
    }
    if brand_id.contains("..") || brand_id.contains('/') || brand_id.contains('\\')
        || brand_id.contains('\0')
    {
        return Err(format!("Invalid brand ID: {brand_id}"));
    }
    Ok(())
}

/// Read a brand from filesystem.
fn read_brand(brands_dir: &Path, brand_id: &str) -> Result<BrandInfo, String> {
    let path = brand_file(brands_dir, brand_id);
    let data = std::fs::read_to_string(&path)
        .map_err(|e| format!("Brand '{}' not found: {}", brand_id, e))?;
    serde_json::from_str(&data)
        .map_err(|e| format!("Failed to parse brand '{}': {}", brand_id, e))
}

/// Check if RAG server is reachable (non-blocking with short timeout).
async fn rag_available() -> bool {
    match reqwest::Client::new()
        .get(format!("{RAG_BASE}/health"))
        .timeout(std::time::Duration::from_secs(2))
        .send()
        .await
    {
        Ok(resp) => resp.status().is_success(),
        Err(_) => false,
    }
}

// ── Tauri Commands ───────────────────────────────────────

#[tauri::command]
pub async fn brand_list(app_handle: tauri::AppHandle) -> Result<Vec<BrandInfo>, String> {
    let dir = brands_dir(&app_handle)?;
    let mut brands = Vec::new();

    let entries = std::fs::read_dir(&dir).map_err(|e| e.to_string())?;
    for entry in entries.flatten() {
        if entry.file_type().is_ok_and(|ft| ft.is_dir()) {
            let brand_id = entry.file_name().to_string_lossy().to_string();
            if let Ok(brand) = read_brand(&dir, &brand_id) {
                brands.push(brand);
            }
        }
    }

    brands.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(brands)
}

#[tauri::command]
pub async fn brand_create(
    brand_id: String,
    name: String,
    industry: String,
    description: String,
    app_handle: tauri::AppHandle,
) -> Result<BrandInfo, String> {
    validate_brand_id(&brand_id)?;
    let dir = brands_dir(&app_handle)?;
    let brand_dir = dir.join(&brand_id);

    if brand_dir.exists() {
        return Err(format!("Brand '{}' already exists", brand_id));
    }

    // Create brand directory structure
    std::fs::create_dir_all(&brand_dir).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(brand_docs_dir(&dir, &brand_id)).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(brand_history_dir(&dir, &brand_id)).map_err(|e| e.to_string())?;

    let brand = BrandInfo {
        brand_id: brand_id.clone(),
        name,
        industry,
        description,
        created_at: chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
    };

    let json = serde_json::to_string_pretty(&brand).map_err(|e| e.to_string())?;
    std::fs::write(brand_file(&dir, &brand_id), json).map_err(|e| e.to_string())?;

    info!("Brand created: {} ({})", brand.name, brand_id);

    // Best-effort RAG sync (non-blocking, ignore failures)
    if rag_available().await {
        let body = serde_json::json!({
            "brand_id": brand.brand_id,
            "name": brand.name,
            "industry": brand.industry,
            "description": brand.description,
        });
        let _ = reqwest::Client::new()
            .post(format!("{RAG_BASE}/brands"))
            .json(&body)
            .send()
            .await;
    }

    Ok(brand)
}

#[tauri::command]
pub async fn brand_get(brand_id: String, app_handle: tauri::AppHandle) -> Result<Value, String> {
    validate_brand_id(&brand_id)?;
    let dir = brands_dir(&app_handle)?;
    let brand = read_brand(&dir, &brand_id)?;
    serde_json::to_value(&brand).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn brand_activate(brand_id: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    validate_brand_id(&brand_id)?;
    let dir = brands_dir(&app_handle)?;

    // Verify brand exists
    if !brand_file(&dir, &brand_id).exists() {
        return Err(format!("Brand '{}' not found", brand_id));
    }

    let active = serde_json::json!({ "active_brand": brand_id });
    let json = serde_json::to_string_pretty(&active).map_err(|e| e.to_string())?;
    std::fs::write(active_brand_file(&dir), json).map_err(|e| e.to_string())?;

    info!("Brand activated: {}", brand_id);

    // Best-effort RAG sync
    if rag_available().await {
        let _ = reqwest::Client::new()
            .post(format!("{RAG_BASE}/brands/{brand_id}/activate"))
            .send()
            .await;
    }

    Ok(())
}

#[tauri::command]
pub async fn brand_get_active(app_handle: tauri::AppHandle) -> Result<ActiveBrandResponse, String> {
    let dir = brands_dir(&app_handle)?;
    let path = active_brand_file(&dir);

    if !path.exists() {
        return Ok(ActiveBrandResponse { active_brand: None });
    }

    let data = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    serde_json::from_str(&data).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn brand_stats(brand_id: String, app_handle: tauri::AppHandle) -> Result<BrandStats, String> {
    validate_brand_id(&brand_id)?;
    let dir = brands_dir(&app_handle)?;

    if !brand_file(&dir, &brand_id).exists() {
        return Err(format!("Brand '{}' not found", brand_id));
    }

    // Count documents on filesystem
    let docs_dir = brand_docs_dir(&dir, &brand_id);
    let documents = if docs_dir.exists() {
        std::fs::read_dir(&docs_dir)
            .map(|entries| entries.flatten().filter(|e| e.file_type().is_ok_and(|ft| ft.is_file())).count())
            .unwrap_or(0) as u64
    } else {
        0
    };

    // Count history files
    let hist_dir = brand_history_dir(&dir, &brand_id);
    let raw_data_files = if hist_dir.exists() {
        count_files_recursive(&hist_dir) as u64
    } else {
        0
    };

    // Try RAG for vector count
    let (vectors, rag_up) = if rag_available().await {
        match reqwest::Client::new()
            .get(format!("{RAG_BASE}/brands/{brand_id}/stats"))
            .timeout(std::time::Duration::from_secs(3))
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                let json: Value = resp.json().await.unwrap_or_default();
                (json["vectors"].as_u64().unwrap_or(0), true)
            }
            _ => (0, false),
        }
    } else {
        (0, false)
    };

    Ok(BrandStats {
        brand_id,
        documents,
        raw_data_files,
        vectors,
        rag_available: rag_up,
    })
}

#[tauri::command]
pub async fn brand_upload_doc(
    brand_id: String,
    file_path: String,
    app_handle: tauri::AppHandle,
) -> Result<Value, String> {
    validate_brand_id(&brand_id)?;
    let dir = brands_dir(&app_handle)?;

    if !brand_file(&dir, &brand_id).exists() {
        return Err(format!("Brand '{}' not found", brand_id));
    }

    let src = Path::new(&file_path);
    if !src.exists() {
        return Err(format!("File not found: {file_path}"));
    }

    let file_name = src
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| "document".to_string());

    // Copy to brand documents dir (filesystem-first)
    let docs = brand_docs_dir(&dir, &brand_id);
    std::fs::create_dir_all(&docs).map_err(|e| e.to_string())?;
    let dest = docs.join(&file_name);
    std::fs::copy(src, &dest).map_err(|e| e.to_string())?;

    info!("Document copied to brand {}: {}", brand_id, file_name);

    // Best-effort RAG indexing
    let mut rag_indexed = false;
    if rag_available().await {
        let file_bytes = tokio::fs::read(&file_path)
            .await
            .map_err(|e| format!("Failed to read file: {e}"))?;

        let part = reqwest::multipart::Part::bytes(file_bytes)
            .file_name(file_name.clone())
            .mime_str("application/octet-stream")
            .map_err(|e| format!("MIME error: {e}"))?;

        let form = reqwest::multipart::Form::new().part("file", part);

        if let Ok(resp) = reqwest::Client::new()
            .post(format!("{RAG_BASE}/brands/{brand_id}/upload"))
            .multipart(form)
            .send()
            .await
        {
            rag_indexed = resp.status().is_success();
        }
    }

    Ok(serde_json::json!({
        "filename": file_name,
        "rag_indexed": rag_indexed,
    }))
}

#[tauri::command]
pub async fn brand_search(
    brand_id: String,
    query: String,
    top_k: Option<u32>,
) -> Result<Value, String> {
    if !rag_available().await {
        return Err("RAG-сервер недоступен. Vector search требует запущенного RAG-сервера.".to_string());
    }

    let body = serde_json::json!({
        "query": query,
        "top_k": top_k.unwrap_or(10),
    });

    let resp = reqwest::Client::new()
        .post(format!("{RAG_BASE}/brands/{brand_id}/search"))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("RAG search failed: {e}"))?;

    if !resp.status().is_success() {
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("Search failed: {text}"));
    }

    resp.json::<Value>()
        .await
        .map_err(|e| format!("Failed to parse search results: {e}"))
}

#[tauri::command]
pub fn brand_history_search(
    brand_id: String,
    query: String,
    app_handle: tauri::AppHandle,
) -> Result<Vec<Value>, String> {
    validate_brand_id(&brand_id)?;
    let dir = brands_dir(&app_handle)?;
    let history_dir = brand_history_dir(&dir, &brand_id);

    if !history_dir.exists() {
        return Ok(vec![]);
    }

    let query_lower = query.to_lowercase();
    let mut results = Vec::new();

    // Walk all subdirectories in history (cabinet-named folders)
    let entries = std::fs::read_dir(&history_dir).map_err(|e| e.to_string())?;
    for entry in entries.flatten() {
        if !entry.file_type().is_ok_and(|ft| ft.is_dir()) {
            continue;
        }
        let cabinet = entry.file_name().to_string_lossy().to_string();
        let cab_dir = entry.path();

        let mut files: Vec<_> = std::fs::read_dir(&cab_dir)
            .map_err(|e| e.to_string())?
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.path()
                    .extension()
                    .is_some_and(|ext| ext == "md" || ext == "json" || ext == "txt")
            })
            .collect();

        // Sort by modified time desc, take last 20
        files.sort_by(|a, b| {
            b.metadata()
                .and_then(|m| m.modified())
                .unwrap_or(std::time::SystemTime::UNIX_EPOCH)
                .cmp(
                    &a.metadata()
                        .and_then(|m| m.modified())
                        .unwrap_or(std::time::SystemTime::UNIX_EPOCH),
                )
        });
        files.truncate(20);

        for file_entry in files {
            let content = match std::fs::read_to_string(file_entry.path()) {
                Ok(c) => {
                    let truncated: String = c.chars().take(1000).collect();
                    truncated
                }
                Err(_) => continue,
            };

            let content_lower = content.to_lowercase();
            let match_count = content_lower.matches(&query_lower).count();
            if match_count == 0 {
                continue;
            }

            // Extract excerpt around first match (char-safe for Unicode)
            let chars: Vec<char> = content.chars().collect();
            let chars_lower: Vec<char> = content_lower.chars().collect();
            let query_chars: Vec<char> = query_lower.chars().collect();
            let char_pos = chars_lower
                .windows(query_chars.len())
                .position(|w| w == query_chars.as_slice())
                .unwrap_or(0);
            let start = char_pos.saturating_sub(50);
            let end = (char_pos + 200).min(chars.len());
            let excerpt: String = chars[start..end].iter().collect();

            let filename = file_entry.file_name().to_string_lossy().to_string();
            results.push(serde_json::json!({
                "cabinet": cabinet,
                "filename": filename,
                "excerpt": excerpt,
                "match_count": match_count,
            }));
        }
    }

    results.sort_by(|a, b| {
        b.get("match_count")
            .and_then(|v| v.as_u64())
            .unwrap_or(0)
            .cmp(&a.get("match_count").and_then(|v| v.as_u64()).unwrap_or(0))
    });
    results.truncate(10);

    Ok(results)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocInfo {
    pub filename: String,
    pub size: u64,
    pub modified_at: u64,
}

#[tauri::command]
pub async fn brand_update(
    brand_id: String,
    name: String,
    industry: String,
    description: String,
    app_handle: tauri::AppHandle,
) -> Result<BrandInfo, String> {
    validate_brand_id(&brand_id)?;
    let dir = brands_dir(&app_handle)?;
    let mut brand = read_brand(&dir, &brand_id)?;

    brand.name = name;
    brand.industry = industry;
    brand.description = description;
    // created_at preserved from existing

    let json = serde_json::to_string_pretty(&brand).map_err(|e| e.to_string())?;
    std::fs::write(brand_file(&dir, &brand_id), json).map_err(|e| e.to_string())?;

    info!("Brand updated: {} ({})", brand.name, brand_id);

    if rag_available().await {
        let body = serde_json::json!({
            "brand_id": brand.brand_id,
            "name": brand.name,
            "industry": brand.industry,
            "description": brand.description,
        });
        let _ = reqwest::Client::new()
            .post(format!("{RAG_BASE}/brands"))
            .json(&body)
            .send()
            .await;
    }

    Ok(brand)
}

#[tauri::command]
pub async fn brand_delete(
    brand_id: String,
    app_handle: tauri::AppHandle,
) -> Result<(), String> {
    validate_brand_id(&brand_id)?;
    let dir = brands_dir(&app_handle)?;
    let brand_dir = dir.join(&brand_id);

    if !brand_dir.exists() {
        return Err(format!("Brand '{}' not found", brand_id));
    }

    std::fs::remove_dir_all(&brand_dir).map_err(|e| e.to_string())?;

    // Clear active if deleted brand was active
    let active_path = active_brand_file(&dir);
    if active_path.exists() {
        if let Ok(data) = std::fs::read_to_string(&active_path) {
            if let Ok(active) = serde_json::from_str::<ActiveBrandResponse>(&data) {
                if active.active_brand.as_deref() == Some(&brand_id) {
                    let _ = std::fs::remove_file(&active_path);
                }
            }
        }
    }

    info!("Brand deleted: {}", brand_id);

    if rag_available().await {
        let _ = reqwest::Client::new()
            .delete(format!("{RAG_BASE}/brands/{brand_id}"))
            .send()
            .await;
    }

    Ok(())
}

#[tauri::command]
pub fn brand_list_docs(
    brand_id: String,
    app_handle: tauri::AppHandle,
) -> Result<Vec<DocInfo>, String> {
    validate_brand_id(&brand_id)?;
    let dir = brands_dir(&app_handle)?;
    let docs_dir = brand_docs_dir(&dir, &brand_id);

    if !docs_dir.exists() {
        return Ok(vec![]);
    }

    let mut docs = Vec::new();
    for entry in std::fs::read_dir(&docs_dir).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        if entry.file_type().is_ok_and(|ft| ft.is_file()) {
            let meta = entry.metadata().map_err(|e| e.to_string())?;
            let modified_at = meta
                .modified()
                .ok()
                .and_then(|t| t.duration_since(std::time::SystemTime::UNIX_EPOCH).ok())
                .map(|d| d.as_secs())
                .unwrap_or(0);
            docs.push(DocInfo {
                filename: entry.file_name().to_string_lossy().to_string(),
                size: meta.len(),
                modified_at,
            });
        }
    }

    docs.sort_by(|a, b| b.modified_at.cmp(&a.modified_at));
    Ok(docs)
}

#[tauri::command]
pub async fn brand_delete_doc(
    brand_id: String,
    filename: String,
    app_handle: tauri::AppHandle,
) -> Result<(), String> {
    validate_brand_id(&brand_id)?;
    if filename.contains("..") || filename.contains('/') || filename.contains('\\') || filename.contains('\0') {
        return Err("Invalid filename".to_string());
    }

    let dir = brands_dir(&app_handle)?;
    let file_path = brand_docs_dir(&dir, &brand_id).join(&filename);

    if !file_path.exists() {
        return Err(format!("Document not found: {}", filename));
    }

    std::fs::remove_file(&file_path).map_err(|e| e.to_string())?;
    info!("Document deleted from brand {}: {}", brand_id, filename);

    if rag_available().await {
        let _ = reqwest::Client::new()
            .delete(format!("{RAG_BASE}/brands/{brand_id}/documents/{filename}"))
            .send()
            .await;
    }

    Ok(())
}

#[tauri::command]
pub async fn brand_health() -> Result<bool, String> {
    Ok(rag_available().await)
}

#[tauri::command]
pub async fn data_chat_deep(
    brand_id: String,
    question: String,
    context_markdown: String,
    app_handle: tauri::AppHandle,
    state: tauri::State<'_, std::sync::Arc<crate::AppState>>,
) -> Result<(), String> {
    validate_brand_id(&brand_id)?;
    // Create temp workspace with unique ID for concurrent safety
    let local_app = std::env::var("LOCALAPPDATA")
        .unwrap_or_else(|_| std::env::var("TEMP").unwrap_or_else(|_| ".".to_string()));
    let session_id = format!("data-chat-{}", uuid::Uuid::new_v4().to_string().split('-').next().unwrap_or("0"));
    let base = std::path::PathBuf::from(local_app)
        .join("AIAgency")
        .join(&session_id);
    std::fs::create_dir_all(&base).map_err(|e| e.to_string())?;

    // Write CLAUDE.md (system prompt for data analyst)
    let claude_md = format!(
        r#"# Data Chat — Аналитик Brand Hub

Ты — аналитик данных Brand Hub для бренда "{brand_id}". Отвечай на русском языке.

## Контекст
В файле `context.md` содержатся данные бренда из Brand Hub: профиль, результаты поиска, история кабинетов.

## Правила
- Отвечай конкретно, с цифрами и фактами из контекста
- Если данных недостаточно — скажи об этом честно
- Используй markdown для форматирования
- Не выдумывай данные, которых нет в контексте
- Давай практические рекомендации на основе данных
"#
    );
    std::fs::write(base.join("CLAUDE.md"), &claude_md).map_err(|e| e.to_string())?;

    // Write context.md
    std::fs::write(base.join("context.md"), &context_markdown).map_err(|e| e.to_string())?;

    // Create .claude dir for settings
    let claude_dir = base.join(".claude");
    std::fs::create_dir_all(&claude_dir).map_err(|e| e.to_string())?;

    // Run Claude with the question
    // FIX BUG-1: 5th arg is Option<String> (resume_session_id), not bool
    let cabinet_id = "data-chat".to_string();
    let result = crate::commands::claude::run_claude(
        &base,
        &question,
        app_handle,
        cabinet_id,
        None, // no resume — fresh session each time
        state.active_pids.clone(),
        false,
        None, // model — use default
    )
    .await;

    // Cleanup always, even on error
    let _ = std::fs::remove_dir_all(&base);

    result.map(|_| ()).map_err(|e| e.to_string())
}

// ── Default Brand ────────────────────────────────────────

/// Creates a "default" brand if none exist. Used by non-Creative-Hub products
/// so that workflows have a brand context without user interaction.
pub fn ensure_default_brand(app_handle: &tauri::AppHandle) -> Result<(), String> {
    let dir = brands_dir(app_handle)?;

    // Check if any brand exists
    let has_brands = std::fs::read_dir(&dir)
        .map(|entries| {
            entries
                .flatten()
                .any(|e| e.file_type().is_ok_and(|ft| ft.is_dir()))
        })
        .unwrap_or(false);

    if has_brands {
        return Ok(());
    }

    // Create default brand
    let brand = BrandInfo {
        brand_id: "default".to_string(),
        name: "Default".to_string(),
        industry: String::new(),
        description: "Автоматически созданный бренд по умолчанию".to_string(),
        created_at: chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
    };

    let brand_dir = dir.join("default");
    std::fs::create_dir_all(&brand_dir).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(brand_docs_dir(&dir, "default")).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(brand_history_dir(&dir, "default")).map_err(|e| e.to_string())?;

    let json = serde_json::to_string_pretty(&brand).map_err(|e| e.to_string())?;
    std::fs::write(brand_file(&dir, "default"), json).map_err(|e| e.to_string())?;

    // Activate it
    let active = serde_json::json!({ "active_brand": "default" });
    let active_json = serde_json::to_string_pretty(&active).map_err(|e| e.to_string())?;
    std::fs::write(active_brand_file(&dir), active_json).map_err(|e| e.to_string())?;

    info!("Default brand created and activated");
    Ok(())
}

// ── Brand Context Injection ──────────────────────────────

/// Reads active brand from filesystem, writes `.brand_hub_context.json`
/// to workspace. Called from `open_cabinet`. If RAG is available, adds
/// `"rag_available": true`.
pub async fn write_brand_context(work_dir: &Path, app_handle: &tauri::AppHandle) {
    let dir = match brands_dir(app_handle) {
        Ok(d) => d,
        Err(_) => return,
    };

    // Read active brand
    let active_path = active_brand_file(&dir);
    if !active_path.exists() {
        return;
    }

    let active_data = match std::fs::read_to_string(&active_path) {
        Ok(d) => d,
        Err(_) => return,
    };

    let active: ActiveBrandResponse = match serde_json::from_str(&active_data) {
        Ok(a) => a,
        Err(_) => return,
    };

    let brand_id = match active.active_brand {
        Some(id) if !id.is_empty() => id,
        _ => return,
    };

    // Read brand profile
    let brand = match read_brand(&dir, &brand_id) {
        Ok(b) => b,
        Err(_) => return,
    };

    // Count docs
    let docs_dir = brand_docs_dir(&dir, &brand_id);
    let doc_count = if docs_dir.exists() {
        std::fs::read_dir(&docs_dir)
            .map(|e| e.flatten().filter(|e| e.file_type().is_ok_and(|ft| ft.is_file())).count())
            .unwrap_or(0)
    } else {
        0
    };

    let rag_up = rag_available().await;

    let context = serde_json::json!({
        "brand_id": brand.brand_id,
        "name": brand.name,
        "industry": brand.industry,
        "description": brand.description,
        "documents": doc_count,
        "rag_available": rag_up,
    });

    let path = work_dir.join(".brand_hub_context.json");
    if let Ok(json) = serde_json::to_string_pretty(&context) {
        let _ = std::fs::write(&path, json);
        info!("Brand context written: {}", path.display());
    }
}

// ── Utilities ────────────────────────────────────────────

fn count_files_recursive(dir: &Path) -> usize {
    walkdir::WalkDir::new(dir)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file())
        .count()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn brand_info_serialization() {
        let brand = BrandInfo {
            brand_id: "test-brand".to_string(),
            name: "Test Brand".to_string(),
            industry: "Tech".to_string(),
            description: "Test".to_string(),
            created_at: "2026-04-05T12:00:00".to_string(),
        };
        let json = serde_json::to_string(&brand).unwrap();
        let parsed: BrandInfo = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.brand_id, "test-brand");
        assert_eq!(parsed.name, "Test Brand");
    }

    #[test]
    fn brand_stats_defaults() {
        let json = r#"{"brand_id": "x", "documents": 5, "raw_data_files": 0}"#;
        let stats: BrandStats = serde_json::from_str(json).unwrap();
        assert_eq!(stats.vectors, 0);
        assert!(!stats.rag_available);
    }

    #[test]
    fn active_brand_response_empty() {
        let json = r#"{"active_brand": null}"#;
        let resp: ActiveBrandResponse = serde_json::from_str(json).unwrap();
        assert!(resp.active_brand.is_none());
    }

    #[test]
    fn brand_file_path_structure() {
        let dir = PathBuf::from("/tmp/brands");
        let path = brand_file(&dir, "my-brand");
        assert!(path.to_string_lossy().contains("my-brand"));
        assert!(path.to_string_lossy().ends_with("brand.json"));
    }

    #[test]
    fn brand_create_and_read_filesystem() {
        let tmp = tempfile::tempdir().unwrap();
        let brands = tmp.path().join("brands");
        std::fs::create_dir_all(&brands).unwrap();

        let brand_id = "test";
        let brand_dir = brands.join(brand_id);
        std::fs::create_dir_all(&brand_dir).unwrap();

        let brand = BrandInfo {
            brand_id: brand_id.to_string(),
            name: "Test".to_string(),
            industry: "SaaS".to_string(),
            description: "Desc".to_string(),
            created_at: "2026-04-05".to_string(),
        };
        let json = serde_json::to_string_pretty(&brand).unwrap();
        std::fs::write(brand_file(&brands, brand_id), &json).unwrap();

        let loaded = read_brand(&brands, brand_id).unwrap();
        assert_eq!(loaded.name, "Test");
        assert_eq!(loaded.industry, "SaaS");
    }

    #[test]
    fn active_brand_file_roundtrip() {
        let tmp = tempfile::tempdir().unwrap();
        let brands = tmp.path().join("brands");
        std::fs::create_dir_all(&brands).unwrap();

        let active = serde_json::json!({ "active_brand": "my-brand" });
        std::fs::write(active_brand_file(&brands), serde_json::to_string(&active).unwrap()).unwrap();

        let data = std::fs::read_to_string(active_brand_file(&brands)).unwrap();
        let resp: ActiveBrandResponse = serde_json::from_str(&data).unwrap();
        assert_eq!(resp.active_brand, Some("my-brand".to_string()));
    }

    #[test]
    fn brand_update_preserves_created_at() {
        let tmp = tempfile::tempdir().unwrap();
        let brands = tmp.path().join("brands");
        let brand_dir = brands.join("test");
        std::fs::create_dir_all(&brand_dir).unwrap();

        let brand = BrandInfo {
            brand_id: "test".into(),
            name: "Old".into(),
            industry: "Tech".into(),
            description: "Desc".into(),
            created_at: "2026-01-01T00:00:00".into(),
        };
        std::fs::write(brand_file(&brands, "test"), serde_json::to_string_pretty(&brand).unwrap()).unwrap();

        // Simulate update: read, modify, write
        let mut loaded = read_brand(&brands, "test").unwrap();
        loaded.name = "New Name".into();
        std::fs::write(brand_file(&brands, "test"), serde_json::to_string_pretty(&loaded).unwrap()).unwrap();

        let result = read_brand(&brands, "test").unwrap();
        assert_eq!(result.name, "New Name");
        assert_eq!(result.created_at, "2026-01-01T00:00:00"); // preserved
    }

    #[test]
    fn brand_delete_removes_dir() {
        let tmp = tempfile::tempdir().unwrap();
        let brands = tmp.path().join("brands");
        let brand_dir = brands.join("to-delete");
        std::fs::create_dir_all(brand_dir.join("documents")).unwrap();
        std::fs::write(brand_file(&brands, "to-delete"), r#"{"brand_id":"to-delete","name":"X"}"#).unwrap();

        assert!(brand_dir.exists());
        std::fs::remove_dir_all(&brand_dir).unwrap();
        assert!(!brand_dir.exists());
    }

    #[test]
    fn brand_delete_clears_active() {
        let tmp = tempfile::tempdir().unwrap();
        let brands = tmp.path().join("brands");
        std::fs::create_dir_all(&brands).unwrap();

        let active = serde_json::json!({ "active_brand": "my-brand" });
        std::fs::write(active_brand_file(&brands), serde_json::to_string(&active).unwrap()).unwrap();

        // Simulate: active == deleted → remove file
        let data = std::fs::read_to_string(active_brand_file(&brands)).unwrap();
        let resp: ActiveBrandResponse = serde_json::from_str(&data).unwrap();
        if resp.active_brand.as_deref() == Some("my-brand") {
            std::fs::remove_file(active_brand_file(&brands)).unwrap();
        }
        assert!(!active_brand_file(&brands).exists());
    }

    #[test]
    fn doc_list_and_delete() {
        let tmp = tempfile::tempdir().unwrap();
        let brands = tmp.path().join("brands");
        let docs = brands.join("test").join("documents");
        std::fs::create_dir_all(&docs).unwrap();
        std::fs::write(docs.join("report.pdf"), "fake pdf").unwrap();
        std::fs::write(docs.join("notes.md"), "# notes").unwrap();

        let entries: Vec<_> = std::fs::read_dir(&docs).unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().is_ok_and(|ft| ft.is_file()))
            .collect();
        assert_eq!(entries.len(), 2);

        std::fs::remove_file(docs.join("report.pdf")).unwrap();
        let remaining: Vec<_> = std::fs::read_dir(&docs).unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().is_ok_and(|ft| ft.is_file()))
            .collect();
        assert_eq!(remaining.len(), 1);
    }

    #[test]
    fn validate_brand_id_rejects_traversal() {
        assert!(validate_brand_id("../etc").is_err());
        assert!(validate_brand_id("foo/bar").is_err());
        assert!(validate_brand_id("foo\\bar").is_err());
        assert!(validate_brand_id("").is_err());
        assert!(validate_brand_id("valid-brand").is_ok());
        assert!(validate_brand_id("my_brand_123").is_ok());
    }

    #[test]
    fn count_files_recursive_works() {
        let tmp = tempfile::tempdir().unwrap();
        let sub = tmp.path().join("sub");
        std::fs::create_dir_all(&sub).unwrap();
        std::fs::write(tmp.path().join("a.txt"), "a").unwrap();
        std::fs::write(sub.join("b.txt"), "b").unwrap();
        assert_eq!(count_files_recursive(tmp.path()), 2);
    }
}
