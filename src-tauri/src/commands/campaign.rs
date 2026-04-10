use log::info;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Campaign {
    pub id: String,
    pub brand_id: String,
    pub name: String,
    pub created_at: String,
    pub steps: Vec<CampaignStep>,
    #[serde(default = "default_campaign_type")]
    pub campaign_type: String, // "linear" | "workflow"
    #[serde(default)]
    pub workflow_steps: Option<Vec<WorkflowStep>>,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub template_id: Option<String>,
    // v0.6.0: Pipeline fields
    #[serde(default)]
    pub brief_text: String,
    #[serde(default)]
    pub brief_files: Vec<String>,
    #[serde(default)]
    pub status: String,              // "" | "draft" | "running" | "completed" | "failed" | "interrupted"
    #[serde(default)]
    pub started_at: Option<String>,
    #[serde(default)]
    pub completed_at: Option<String>,
    #[serde(default)]
    pub execution_id: Option<String>,
}

fn default_campaign_type() -> String {
    "linear".into()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CampaignStep {
    pub id: String,
    pub name: String,
    pub cabinet: String,
    pub status: String, // "pending", "in_progress", "completed"
    pub artifacts: Vec<String>,
}

// ── Workflow Step Tree Model ─────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum WorkflowStep {
    #[serde(rename = "single")]
    Single {
        id: String,
        cabinet_id: String,
        #[serde(default)]
        command: Option<String>,
        label: String,
        #[serde(default)]
        status: String, // "idle", "running", "done", "error"
    },
    #[serde(rename = "parallel")]
    Parallel {
        id: String,
        branches: Vec<Vec<WorkflowStep>>,
        #[serde(default)]
        status: String,
    },
    #[serde(rename = "loop")]
    Loop {
        id: String,
        body: Vec<WorkflowStep>,
        review: Vec<WorkflowStep>,
        #[serde(default = "default_max_iterations")]
        max_iterations: u32,
        #[serde(default)]
        status: String,
    },
}

fn default_max_iterations() -> u32 {
    2
}

// ── Workflow Template ────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowTemplate {
    pub id: String,
    pub name: String,
    pub description: String,
    pub category: String,
    pub icon: String,
    pub steps: Vec<WorkflowStep>,
    #[serde(default)]
    pub estimated_time_minutes: Option<u32>,
}

fn templates_dir() -> PathBuf {
    if cfg!(debug_assertions) {
        std::env::var("CARGO_MANIFEST_DIR")
            .ok()
            .map(|d| PathBuf::from(d).join("..").join("brand-hub").join("workflow-templates"))
            .unwrap_or_default()
    } else {
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_default()
            .join("brand-hub")
            .join("workflow-templates")
    }
}

/// Get campaigns directory for a brand. Uses "default" brand for non-Creative-Hub products.
pub fn campaigns_dir(brand_id: &str) -> PathBuf {
    let user_profile = std::env::var("USERPROFILE")
        .unwrap_or_else(|_| "C:\\Users\\Default".to_string());
    PathBuf::from(&user_profile)
        .join("Desktop")
        .join("AIAgency")
        .join("campaigns")
        .join(brand_id)
}

/// Ensure the "default" brand directory exists for products without Brand Hub.
pub fn ensure_default_brand() -> String {
    let brand_id = "default".to_string();
    let dir = campaigns_dir(&brand_id);
    let _ = std::fs::create_dir_all(&dir);
    brand_id
}

fn default_steps() -> Vec<CampaignStep> {
    vec![
        CampaignStep { id: "analytics".into(), name: "Аналитика".into(), cabinet: "communication-analyst".into(), status: "pending".into(), artifacts: vec![] },
        CampaignStep { id: "strategy".into(), name: "Стратегия".into(), cabinet: "communication-strategist".into(), status: "pending".into(), artifacts: vec![] },
        CampaignStep { id: "concept".into(), name: "Концепция".into(), cabinet: "creative-director".into(), status: "pending".into(), artifacts: vec![] },
        CampaignStep { id: "concept-test".into(), name: "Тест концепции".into(), cabinet: "focus-groups".into(), status: "pending".into(), artifacts: vec![] },
        CampaignStep { id: "texts".into(), name: "Тексты".into(), cabinet: "copywriter".into(), status: "pending".into(), artifacts: vec![] },
        CampaignStep { id: "visuals".into(), name: "Визуалы".into(), cabinet: "art-director".into(), status: "pending".into(), artifacts: vec![] },
        CampaignStep { id: "text-test".into(), name: "Тест текстов".into(), cabinet: "focus-groups".into(), status: "pending".into(), artifacts: vec![] },
        CampaignStep { id: "finalization".into(), name: "Финализация".into(), cabinet: "".into(), status: "pending".into(), artifacts: vec![] },
    ]
}

#[tauri::command]
pub fn campaign_create(brand_id: String, name: String) -> Result<Campaign, String> {
    let brand = if brand_id.is_empty() { ensure_default_brand() } else { brand_id };
    let dir = campaigns_dir(&brand);
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;

    let id = format!("campaign-{}", chrono::Local::now().format("%Y%m%d-%H%M%S"));
    let campaign = Campaign {
        id: id.clone(),
        brand_id: brand,
        name,
        created_at: chrono::Local::now().to_rfc3339(),
        steps: default_steps(),
        campaign_type: "linear".into(),
        workflow_steps: None,
        description: String::new(),
        template_id: None,
        brief_text: String::new(),
        brief_files: vec![],
        status: "draft".into(),
        started_at: None,
        completed_at: None,
        execution_id: None,
    };

    let path = dir.join(format!("{id}.json"));
    let json = serde_json::to_string_pretty(&campaign).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())?;

    Ok(campaign)
}

#[tauri::command]
pub fn campaign_list(brand_id: String) -> Result<Vec<Campaign>, String> {
    let brand = if brand_id.is_empty() { "default".to_string() } else { brand_id };
    let dir = campaigns_dir(&brand);
    if !dir.exists() {
        return Ok(vec![]);
    }

    let mut campaigns = Vec::new();
    for entry in std::fs::read_dir(&dir).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        if entry.path().extension().is_some_and(|ext| ext == "json") {
            let content = std::fs::read_to_string(entry.path()).map_err(|e| e.to_string())?;
            if let Ok(campaign) = serde_json::from_str::<Campaign>(&content) {
                campaigns.push(campaign);
            }
        }
    }
    campaigns.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    Ok(campaigns)
}

#[tauri::command]
pub fn campaign_get(brand_id: String, campaign_id: String) -> Result<Campaign, String> {
    let brand = if brand_id.is_empty() { "default".to_string() } else { brand_id };
    let path = campaigns_dir(&brand).join(format!("{campaign_id}.json"));
    if !path.exists() {
        return Err(format!("Campaign '{}' not found", campaign_id));
    }
    let content = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    serde_json::from_str(&content).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn campaign_update_step(
    brand_id: String,
    campaign_id: String,
    step_id: String,
    status: String,
) -> Result<Campaign, String> {
    let brand = if brand_id.is_empty() { "default".to_string() } else { brand_id };
    let path = campaigns_dir(&brand).join(format!("{campaign_id}.json"));
    if !path.exists() {
        return Err(format!("Campaign '{}' not found", campaign_id));
    }

    let content = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut campaign: Campaign = serde_json::from_str(&content).map_err(|e| e.to_string())?;

    let step = campaign.steps.iter_mut().find(|s| s.id == step_id);
    match step {
        Some(s) => s.status = status,
        None => return Err(format!("Step '{}' not found", step_id)),
    }

    let json = serde_json::to_string_pretty(&campaign).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())?;

    Ok(campaign)
}

// ── Workflow Commands ────────────────────────────────────

#[tauri::command]
pub fn workflow_templates() -> Result<Vec<WorkflowTemplate>, String> {
    let dir = templates_dir();
    if !dir.exists() {
        return Ok(vec![]);
    }
    let mut templates = Vec::new();
    for entry in std::fs::read_dir(&dir).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        if entry.path().extension().is_some_and(|ext| ext == "json") {
            let content = std::fs::read_to_string(entry.path()).map_err(|e| e.to_string())?;
            if let Ok(template) = serde_json::from_str::<WorkflowTemplate>(&content) {
                templates.push(template);
            }
        }
    }
    templates.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(templates)
}

#[tauri::command]
pub fn workflow_create(
    brand_id: String,
    name: String,
    template_id: Option<String>,
    workflow_steps: Option<Vec<WorkflowStep>>,
) -> Result<Campaign, String> {
    let brand = if brand_id.is_empty() { ensure_default_brand() } else { brand_id };
    let dir = campaigns_dir(&brand);
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;

    let steps = if let Some(ref tid) = template_id {
        let tpl_path = templates_dir().join(format!("{tid}.json"));
        if tpl_path.exists() {
            let content = std::fs::read_to_string(&tpl_path).map_err(|e| e.to_string())?;
            let template: WorkflowTemplate =
                serde_json::from_str(&content).map_err(|e| e.to_string())?;
            Some(template.steps)
        } else {
            workflow_steps
        }
    } else {
        workflow_steps
    };

    let id = format!("workflow-{}", chrono::Local::now().format("%Y%m%d-%H%M%S"));
    let campaign = Campaign {
        id: id.clone(),
        brand_id: brand,
        name,
        created_at: chrono::Local::now().to_rfc3339(),
        steps: vec![],
        campaign_type: "workflow".into(),
        workflow_steps: Some(steps.unwrap_or_default()),
        description: String::new(),
        template_id,
        brief_text: String::new(),
        brief_files: vec![],
        status: "draft".into(),
        started_at: None,
        completed_at: None,
        execution_id: None,
    };

    let path = dir.join(format!("{id}.json"));
    let json = serde_json::to_string_pretty(&campaign).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())?;

    Ok(campaign)
}

#[tauri::command]
pub fn workflow_save(brand_id: String, campaign: Campaign) -> Result<(), String> {
    let brand = if brand_id.is_empty() { "default".to_string() } else { brand_id };
    let path = campaigns_dir(&brand).join(format!("{}.json", campaign.id));
    let json = serde_json::to_string_pretty(&campaign).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn workflow_delete(brand_id: String, workflow_id: String) -> Result<(), String> {
    let brand = if brand_id.is_empty() { "default".to_string() } else { brand_id };
    let path = campaigns_dir(&brand).join(format!("{workflow_id}.json"));
    if path.exists() {
        std::fs::remove_file(&path).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn campaign_to_workflow(brand_id: String, campaign_id: String) -> Result<Campaign, String> {
    let brand = if brand_id.is_empty() { "default".to_string() } else { brand_id.clone() };
    let campaign = campaign_get(brand.clone(), campaign_id)?;
    if campaign.campaign_type == "workflow" {
        return Ok(campaign);
    }

    let workflow_steps: Vec<WorkflowStep> = campaign.steps.iter()
        .filter(|s| !s.cabinet.is_empty())
        .map(|s| WorkflowStep::Single {
            id: s.id.clone(),
            cabinet_id: s.cabinet.clone(),
            command: None,
            label: s.name.clone(),
            status: "idle".into(),
        })
        .collect();

    let dir = campaigns_dir(&brand);
    let id = format!("workflow-{}", chrono::Local::now().format("%Y%m%d-%H%M%S"));
    let new_wf = Campaign {
        id: id.clone(),
        brand_id: brand,
        name: format!("{} (workflow)", campaign.name),
        created_at: chrono::Local::now().to_rfc3339(),
        steps: vec![],
        campaign_type: "workflow".into(),
        workflow_steps: Some(workflow_steps),
        description: format!("Конвертировано из кампании {}", campaign.name),
        template_id: None,
        brief_text: String::new(),
        brief_files: vec![],
        status: "draft".into(),
        started_at: None,
        completed_at: None,
        execution_id: None,
    };

    let path = dir.join(format!("{id}.json"));
    let json = serde_json::to_string_pretty(&new_wf).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())?;

    Ok(new_wf)
}

// ── Pipeline: Context Chain ──────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextChain {
    pub brief_text: String,
    pub brand_name: String,
    pub step_summaries: Vec<(String, String)>, // (label, summary)
    pub campaign_dir: PathBuf,
}

impl ContextChain {
    /// Build text prefix to inject into Claude message.
    pub fn build_message_prefix(&self) -> String {
        let mut prefix = String::from("[КОНТЕКСТ ПАЙПЛАЙНА]\n");
        if !self.brief_text.is_empty() {
            prefix.push_str(&format!("Бриф: {}\n", self.brief_text));
        }
        if !self.brand_name.is_empty() {
            prefix.push_str(&format!("Бренд: {}\n", self.brand_name));
        }
        if !self.step_summaries.is_empty() {
            prefix.push_str("Предыдущие шаги:\n");
            for (i, (label, summary)) in self.step_summaries.iter().enumerate() {
                let truncated: String = summary.chars().take(500).collect();
                prefix.push_str(&format!("{}. {}: {}\n", i + 1, label, truncated));
            }
        }
        prefix.push_str("Файлы предыдущих шагов находятся в inbox/\n");
        prefix.push_str("[/КОНТЕКСТ ПАЙПЛАЙНА]\n\n");
        prefix
    }
}

/// Summarize step exports: read first 300 chars of up to 3 newest .md/.txt files.
pub fn summarize_step_exports(exports_dir: &Path) -> String {
    if !exports_dir.exists() {
        return "Нет экспортированных файлов".into();
    }
    let mut files: Vec<_> = std::fs::read_dir(exports_dir)
        .into_iter()
        .flatten()
        .flatten()
        .filter(|e| {
            e.file_type().is_ok_and(|ft| ft.is_file())
                && e.path()
                    .extension()
                    .is_some_and(|ext| ext == "md" || ext == "txt")
        })
        .collect();
    files.sort_by(|a, b| {
        b.metadata().and_then(|m| m.modified()).unwrap_or(std::time::SystemTime::UNIX_EPOCH)
            .cmp(&a.metadata().and_then(|m| m.modified()).unwrap_or(std::time::SystemTime::UNIX_EPOCH))
    });
    files.truncate(3);

    let mut parts = Vec::new();
    for f in &files {
        let name = f.file_name().to_string_lossy().to_string();
        if let Ok(content) = std::fs::read_to_string(f.path()) {
            let preview: String = content.chars().take(300).collect();
            parts.push(format!("- {}: {}", name, preview));
        }
    }
    if parts.is_empty() {
        "Файлы созданы, но без текстового содержимого".into()
    } else {
        parts.join("\n")
    }
}

/// Copy exports to persistent campaign directory BEFORE close_session.
pub fn persist_step_exports(campaign_dir: &Path, step_id: &str, exports_dir: &Path) -> Vec<String> {
    let dest = campaign_dir.join("steps").join(step_id);
    let _ = std::fs::create_dir_all(&dest);
    let mut copied = Vec::new();
    if exports_dir.exists() {
        if let Ok(entries) = std::fs::read_dir(exports_dir) {
            for entry in entries.flatten() {
                if entry.file_type().is_ok_and(|ft| ft.is_file()) {
                    let name = entry.file_name().to_string_lossy().to_string();
                    let _ = std::fs::copy(entry.path(), dest.join(&name));
                    copied.push(name);
                }
            }
        }
    }
    info!("Persisted {} exports for step {}", copied.len(), step_id);
    copied
}

/// Forward exports from previous step to next step's inbox.
pub fn forward_exports_to_inbox(prev_exports_dir: &Path, next_workspace: &Path) -> Vec<String> {
    let inbox = next_workspace.join("inbox");
    let _ = std::fs::create_dir_all(&inbox);
    let mut forwarded = Vec::new();
    if prev_exports_dir.exists() {
        if let Ok(entries) = std::fs::read_dir(prev_exports_dir) {
            for entry in entries.flatten() {
                if entry.file_type().is_ok_and(|ft| ft.is_file()) {
                    let name = entry.file_name().to_string_lossy().to_string();
                    let _ = std::fs::copy(entry.path(), inbox.join(&name));
                    forwarded.push(name);
                }
            }
        }
    }
    forwarded
}

// ── Pipeline Commands ────────────────────────────────────

#[tauri::command]
pub fn campaign_set_brief(
    brand_id: String,
    campaign_id: String,
    brief_text: String,
    brief_file_paths: Vec<String>,
) -> Result<Campaign, String> {
    let brand = if brand_id.is_empty() { "default".to_string() } else { brand_id };
    let path = campaigns_dir(&brand).join(format!("{campaign_id}.json"));
    let content = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut campaign: Campaign = serde_json::from_str(&content).map_err(|e| e.to_string())?;

    campaign.brief_text = brief_text;

    // Copy brief files to campaign directory
    let brief_dir = campaigns_dir(&brand).join(&campaign_id).join("brief-files");
    let _ = std::fs::create_dir_all(&brief_dir);
    let mut saved_files = Vec::new();
    for src_path in &brief_file_paths {
        let src = Path::new(src_path);
        if src.exists() {
            if let Some(name) = src.file_name() {
                let _ = std::fs::copy(src, brief_dir.join(name));
                saved_files.push(name.to_string_lossy().to_string());
            }
        }
    }
    campaign.brief_files = saved_files;

    let json = serde_json::to_string_pretty(&campaign).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())?;
    Ok(campaign)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CampaignStatus {
    pub status: String,
    pub current_step: Option<String>,
    pub completed_steps: usize,
    pub total_steps: usize,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
}

#[tauri::command]
pub fn campaign_get_status(brand_id: String, campaign_id: String) -> Result<CampaignStatus, String> {
    let campaign = campaign_get(brand_id, campaign_id)?;
    let total = campaign.workflow_steps.as_ref().map(|s| count_single_steps(s)).unwrap_or(0);
    Ok(CampaignStatus {
        status: if campaign.status.is_empty() { "draft".into() } else { campaign.status },
        current_step: None,
        completed_steps: 0, // updated by pipeline execution events
        total_steps: total,
        started_at: campaign.started_at,
        completed_at: campaign.completed_at,
    })
}

fn count_single_steps(steps: &[WorkflowStep]) -> usize {
    steps.iter().map(|s| match s {
        WorkflowStep::Single { .. } => 1,
        WorkflowStep::Parallel { branches, .. } => branches.iter().map(|b| count_single_steps(b)).sum(),
        WorkflowStep::Loop { body, review, .. } => count_single_steps(body) + count_single_steps(review),
    }).sum()
}

#[tauri::command]
pub fn campaign_export_zip(
    brand_id: String,
    campaign_id: String,
    output_path: String,
) -> Result<String, String> {
    let brand = if brand_id.is_empty() { "default".to_string() } else { brand_id };
    let campaign = campaign_get(brand.clone(), campaign_id.clone())?;
    let steps_dir = campaigns_dir(&brand).join(&campaign_id).join("steps");

    let file = std::fs::File::create(&output_path).map_err(|e| e.to_string())?;
    let mut zip = zip::ZipWriter::new(file);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);

    // Generate summary.md
    let mut summary = format!("# {}\n\n", campaign.name);
    if !campaign.brief_text.is_empty() {
        summary.push_str(&format!("## Бриф\n{}\n\n", campaign.brief_text));
    }
    summary.push_str("## Шаги\n\n");

    if steps_dir.exists() {
        if let Ok(step_dirs) = std::fs::read_dir(&steps_dir) {
            let mut step_entries: Vec<_> = step_dirs.flatten().collect();
            step_entries.sort_by_key(|e| e.file_name());

            for (i, step_entry) in step_entries.iter().enumerate() {
                let step_name = step_entry.file_name().to_string_lossy().to_string();
                let folder = format!("{:02}-{}", i + 1, step_name);
                summary.push_str(&format!("### {}. {}\n", i + 1, step_name));

                if let Ok(files) = std::fs::read_dir(step_entry.path()) {
                    for file_entry in files.flatten() {
                        if file_entry.file_type().is_ok_and(|ft| ft.is_file()) {
                            let fname = file_entry.file_name().to_string_lossy().to_string();
                            let zip_path = format!("{}/{}", folder, fname);
                            zip.start_file(&zip_path, options).map_err(|e| e.to_string())?;
                            let bytes = std::fs::read(file_entry.path()).map_err(|e| e.to_string())?;
                            std::io::Write::write_all(&mut zip, &bytes).map_err(|e| e.to_string())?;
                            summary.push_str(&format!("- {}\n", fname));
                        }
                    }
                }
                summary.push('\n');
            }
        }
    }

    // Write summary.md
    zip.start_file("summary.md", options).map_err(|e| e.to_string())?;
    std::io::Write::write_all(&mut zip, summary.as_bytes()).map_err(|e| e.to_string())?;

    zip.finish().map_err(|e| e.to_string())?;
    info!("Campaign exported: {} → {}", campaign_id, output_path);
    Ok(output_path)
}

#[tauri::command]
pub fn campaign_open_exports(brand_id: String, campaign_id: String) -> Result<(), String> {
    let brand = if brand_id.is_empty() { "default".to_string() } else { brand_id };
    let steps_dir = campaigns_dir(&brand).join(&campaign_id).join("steps");
    let _ = std::fs::create_dir_all(&steps_dir);
    #[cfg(windows)]
    std::process::Command::new("explorer")
        .arg(steps_dir.to_string_lossy().as_ref())
        .spawn()
        .map_err(|e| e.to_string())?;
    #[cfg(not(windows))]
    std::process::Command::new("xdg-open")
        .arg(steps_dir.to_string_lossy().as_ref())
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Scan for campaigns stuck in "running" status (app crashed) and set to "interrupted".
pub fn fix_interrupted_campaigns() {
    let user_profile = std::env::var("USERPROFILE").unwrap_or_default();
    let campaigns_root = PathBuf::from(&user_profile)
        .join("Desktop")
        .join("AIAgency")
        .join("campaigns");
    if !campaigns_root.exists() {
        return;
    }
    if let Ok(brands) = std::fs::read_dir(&campaigns_root) {
        for brand_entry in brands.flatten() {
            if let Ok(files) = std::fs::read_dir(brand_entry.path()) {
                for file_entry in files.flatten() {
                    if file_entry.path().extension().is_some_and(|ext| ext == "json") {
                        if let Ok(content) = std::fs::read_to_string(file_entry.path()) {
                            if let Ok(mut campaign) = serde_json::from_str::<Campaign>(&content) {
                                if campaign.status == "running" {
                                    campaign.status = "interrupted".into();
                                    if let Ok(json) = serde_json::to_string_pretty(&campaign) {
                                        let _ = std::fs::write(file_entry.path(), json);
                                        info!("Fixed interrupted campaign: {}", campaign.id);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_campaign_has_8_steps() {
        let steps = default_steps();
        assert_eq!(steps.len(), 8);
    }

    #[test]
    fn ensure_default_brand_returns_default() {
        assert_eq!(ensure_default_brand(), "default");
    }

    #[test]
    fn context_chain_message_prefix() {
        let chain = ContextChain {
            brief_text: "Launch product X".into(),
            brand_name: "TestBrand".into(),
            step_summaries: vec![
                ("Аналитика".into(), "Market size $10B".into()),
                ("Стратегия".into(), "Go premium".into()),
            ],
            campaign_dir: std::path::PathBuf::from("/tmp"),
        };
        let prefix = chain.build_message_prefix();
        assert!(prefix.contains("Launch product X"));
        assert!(prefix.contains("TestBrand"));
        assert!(prefix.contains("Аналитика"));
        assert!(prefix.contains("Market size $10B"));
    }

    #[test]
    fn persist_step_exports_creates_dir() {
        let tmp = tempfile::tempdir().unwrap();
        let campaign_dir = tmp.path().join("campaign-1");
        let exports = tmp.path().join("exports");
        std::fs::create_dir_all(&exports).unwrap();
        std::fs::write(exports.join("report.md"), "# Report").unwrap();

        let files = persist_step_exports(&campaign_dir, "step-1", &exports);
        assert_eq!(files.len(), 1);
        assert!(campaign_dir.join("steps").join("step-1").join("report.md").exists());
    }

    #[test]
    fn summarize_step_exports_caps() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::write(tmp.path().join("a.md"), "Short").unwrap();
        std::fs::write(tmp.path().join("b.txt"), "Also short").unwrap();
        let summary = summarize_step_exports(tmp.path());
        assert!(summary.contains("a.md") || summary.contains("b.txt"));
    }

    #[test]
    fn campaign_backward_compat() {
        // Old campaign JSON without new fields should deserialize fine
        let json = r#"{"id":"c1","brand_id":"x","name":"Test","created_at":"2026","steps":[],"campaign_type":"linear"}"#;
        let campaign: Campaign = serde_json::from_str(json).unwrap();
        assert!(campaign.brief_text.is_empty());
        assert!(campaign.status.is_empty());
        assert!(campaign.execution_id.is_none());
    }

    #[test]
    fn workflow_step_serialization() {
        let step = WorkflowStep::Single {
            id: "test".into(),
            cabinet_id: "copywriter".into(),
            command: Some("/write".into()),
            label: "Write".into(),
            status: "idle".into(),
        };
        let json = serde_json::to_string(&step).unwrap();
        assert!(json.contains("\"type\":\"single\""));

        let parallel = WorkflowStep::Parallel {
            id: "p1".into(),
            branches: vec![vec![step]],
            status: "idle".into(),
        };
        let json = serde_json::to_string(&parallel).unwrap();
        assert!(json.contains("\"type\":\"parallel\""));
    }
}
