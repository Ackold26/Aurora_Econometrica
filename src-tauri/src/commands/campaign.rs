use log::{info, warn};
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

/// Корень кампаний — ЕДИНСТВЕННЫЙ источник пути для всех потребителей.
///
/// CPD-31 (2026-07-29): заведён ПРЕВЕНТИВНО, до какого-либо переезда каталога — путь
/// НЕ меняется этой правкой (переезд на общий корень результатов, как в Docs Lab,
/// INV-82 — отдельное решение владельца, не принято). Живой случай в Docs Lab:
/// `campaigns_dir` переехал, а `fix_interrupted_campaigns` осталась сканировать старый
/// `Desktop\AIAgency\campaigns` — смотрела туда, где кампаний уже нет, и тихо выходила
/// по `if !campaigns_root.exists()`. Кампании, зависшие в статусе «running» после
/// аварийного завершения, не помечались «прерванными» НИКОГДА. Здесь оба потребителя
/// уже согласованы (стоят на одном и том же пути) — но были СОГЛАСОВАНЫ НЕЗАВИСИМО,
/// двумя копиями одного и того же литерала; эта функция убирает копию, чтобы будущий
/// переезд не смог развести их молча.
pub fn campaigns_root() -> PathBuf {
    let user_profile = std::env::var("USERPROFILE")
        .unwrap_or_else(|_| "C:\\Users\\Default".to_string());
    PathBuf::from(&user_profile)
        .join("Desktop")
        .join("AIAgency")
        .join("campaigns")
}

/// Get campaigns directory for a brand. Uses "default" brand for non-Creative-Hub products.
pub fn campaigns_dir(brand_id: &str) -> PathBuf {
    campaigns_root().join(brand_id)
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

/// Итог `persist_step_exports`: что реально скопировалось и что не вышло.
///
/// CPD-81: раньше отказ `fs::copy` отбрасывался (`let _ =`), а имя файла всё равно
/// попадало в список «скопировано» — вызывающий код (`lib.rs`) не мог узнать о потере
/// и следующим шагом удалял рабочий каталог вместе с единственной копией файла.
#[derive(Debug, Default)]
pub struct PersistExportsResult {
    pub copied: Vec<String>,
    /// (имя файла, причина отказа)
    pub failed: Vec<(String, String)>,
    /// Отказ, при котором список `failed` НИЧЕГО не говорит о потере: до перебора
    /// файлов дело не дошло либо перебор оборвался.
    ///
    /// 🔴 Аудит 2.4.9, High-4. Отказ `fs::copy` был единственным обработанным из
    /// четырёх путей. Оставались проглоченными: `create_dir_all` каталога назначения,
    /// `read_dir` каталога выгрузок и определение типа записи. На всех трёх `failed`
    /// оставался пустым, `lib.rs` тревогу не печатал, в журнал шло успокаивающее
    /// «Persisted 0 exports for step X (0 failed)» — а следующей строкой
    /// `close_session` стирал рабочий каталог с единственной копией файлов. Живой
    /// источник такого отказа на Windows обыденный: антивирус или служба
    /// индексирования держит каталог `exports` ровно в момент завершения шага.
    pub fatal: Option<String>,
}

impl PersistExportsResult {
    /// Первый фатальный отказ побеждает: последующие — его следствия, и подменять
    /// ими исходную причину нельзя.
    fn set_fatal(&mut self, reason: String) {
        if self.fatal.is_none() {
            self.fatal = Some(reason);
        }
    }
}

/// Copy exports to persistent campaign directory BEFORE close_session.
pub fn persist_step_exports(campaign_dir: &Path, step_id: &str, exports_dir: &Path) -> PersistExportsResult {
    let dest = campaign_dir.join("steps").join(step_id);
    let mut result = PersistExportsResult::default();
    if let Err(e) = std::fs::create_dir_all(&dest) {
        // Копирование дальше почти наверняка тоже откажет, но перебор не обрываем:
        // отдельные файлы могут лечь, если каталог всё же существует (гонка), а
        // отказы попадут в `failed` поимённо.
        warn!(
            "Каталог для выгрузок шага не создан [шаг {step_id}]: {}: {e}",
            dest.display()
        );
        result.set_fatal(format!(
            "каталог назначения {} не создан: {e}",
            dest.display()
        ));
    }
    if exports_dir.exists() {
        let entries = match std::fs::read_dir(exports_dir) {
            Ok(entries) => Some(entries),
            Err(e) => {
                warn!(
                    "Каталог выгрузок не прочитан [шаг {step_id}]: {}: {e}",
                    exports_dir.display()
                );
                result.set_fatal(format!(
                    "каталог выгрузок {} не прочитан: {e} — сохранять было нечего не потому, что файлов нет",
                    exports_dir.display()
                ));
                None
            }
        };
        if let Some(entries) = entries {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                match entry.file_type() {
                    Ok(ft) if !ft.is_file() => continue,
                    Ok(_) => {}
                    Err(e) => {
                        // Тип записи неизвестен — молча пропустить нельзя: это может
                        // быть ровно тот файл, ради которого шаг и выполнялся.
                        warn!("Тип записи не определён [шаг {step_id}]: {name}: {e}");
                        result.failed.push((name, format!("тип записи не определён: {e}")));
                        continue;
                    }
                }
                // 🔴 Аудит 2.4.9, Medium-5. Здесь НЕ должно быть переименования через
                // `unique_export_path` — свежий файл шага обязан ЗАМЕЩАТЬ свой прежний
                // результат в том же `steps/<step_id>`.
                //
                // Каталог кампании строится из идентификатора СЦЕНАРИЯ, а не запуска
                // (`lib.rs`: `campaigns_dir(brand).join(&workflow_id)`), поэтому
                // повторный прогон того же сценария пишет в тот же каталог шага. С
                // переименованием там оставались обе версии — `report.md` устаревшая и
                // `report (2).md` свежая, — а `forward_exports_to_inbox` копирует
                // каталог ЦЕЛИКОМ во входящие следующего шага. Следующий кабинет
                // получал обе версии и рассуждал по обеим: молчаливая подача
                // противоречивых данных в клиентский результат — хуже перезаписи, от
                // которой защищались.
                //
                // Коллизии, ради которой вводилась защита, на живом пути нет:
                // единственный писатель в каталог выгрузок (`auto_save_response`) даёт
                // имена с секундной меткой и сам прогоняет их через
                // `unique_export_path`. То есть защищались от несуществующего, а
                // создавали существующую неоднозначность.
                //
                // Защита от ПОТЕРИ данных при этом не страдает — её обеспечивает
                // обработка отказа копирования ниже (`failed`) и признак `fatal`, а не
                // переименование. Эти две вещи легко перепутать, но они разные.
                let dest_path = dest.join(&name);
                match std::fs::copy(entry.path(), &dest_path) {
                    Ok(_) => result.copied.push(name),
                    Err(e) => {
                        warn!("Выгрузка не сохранена [шаг {step_id}]: {name}: {e}");
                        result.failed.push((name, e.to_string()));
                    }
                }
            }
        }
    }
    // Признак фатального отказа печатаем прямо здесь: «0 сохранено, 0 отказов»
    // выглядит как «файлов не было», а это неотличимо от «файлы были, но каталог
    // не прочитался» — ровно та подмена, из-за которой потеря шла молча.
    match &result.fatal {
        Some(reason) => info!(
            "Persisted {} exports for step {} ({} failed, ОТКАЗ: {reason})",
            result.copied.len(),
            step_id,
            result.failed.len()
        ),
        None => info!(
            "Persisted {} exports for step {} ({} failed)",
            result.copied.len(),
            step_id,
            result.failed.len()
        ),
    }
    result
}

/// Итог `forward_exports_to_inbox` — зеркало [`PersistExportsResult`] по смыслу этой
/// функции: она не сохраняет в архив, а передаёт во входящие следующего шага.
///
/// CPD-81 (вторая функция того же класса): раньше отказ `fs::copy` отбрасывался
/// (`let _ =`), а имя файла всё равно попадало в список «передано» — вызывающий код
/// не мог узнать о потере. Источник (`persist_step_exports` уже сохранил его в
/// `campaign_dir/steps/...`) при отказе здесь не пропадает — только не появится во
/// входящих следующего шага, поэтому неполнота не необратима, но должна быть видна.
///
/// 🔴 Аудит 2.4.9, High-4: те же три проглоченных пути, что и в `persist_step_exports`
/// (`create_dir_all` каталога входящих, `read_dir` каталога-источника, определение типа
/// записи). Цена ошибки здесь ниже — файлы остаются в архиве кампании, теряется не
/// файл, а контекст очередного шага, — но молчание одинаково вредно: шаг рассуждает
/// на неполных входящих, и в журнале об этом нет ни строки.
#[derive(Debug, Default)]
pub struct ForwardExportsResult {
    pub forwarded: Vec<String>,
    /// (имя файла, причина отказа)
    pub failed: Vec<(String, String)>,
    /// Отказ, при котором пустой `forwarded` НЕ означает «передавать было нечего».
    pub fatal: Option<String>,
}

impl ForwardExportsResult {
    fn set_fatal(&mut self, reason: String) {
        if self.fatal.is_none() {
            self.fatal = Some(reason);
        }
    }
}

/// Forward exports from previous step to next step's inbox.
pub fn forward_exports_to_inbox(
    prev_exports_dir: &Path,
    next_workspace: &Path,
) -> ForwardExportsResult {
    let inbox = next_workspace.join("inbox");
    let mut result = ForwardExportsResult::default();
    if let Err(e) = std::fs::create_dir_all(&inbox) {
        warn!("Каталог входящих не создан: {}: {e}", inbox.display());
        result.set_fatal(format!("каталог входящих {} не создан: {e}", inbox.display()));
    }
    if prev_exports_dir.exists() {
        let entries = match std::fs::read_dir(prev_exports_dir) {
            Ok(entries) => Some(entries),
            Err(e) => {
                warn!(
                    "Каталог выгрузок предыдущего шага не прочитан: {}: {e}",
                    prev_exports_dir.display()
                );
                result.set_fatal(format!(
                    "каталог выгрузок предыдущего шага {} не прочитан: {e}",
                    prev_exports_dir.display()
                ));
                None
            }
        };
        if let Some(entries) = entries {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                match entry.file_type() {
                    Ok(ft) if !ft.is_file() => continue,
                    Ok(_) => {}
                    Err(e) => {
                        warn!("Тип записи не определён: {name}: {e}");
                        result
                            .failed
                            .push((name, format!("тип записи не определён: {e}")));
                        continue;
                    }
                }
                // Совпадение имени здесь не переименовывается (в отличие от
                // persist_step_exports/unique_export_path): входящие следующего
                // шага — рабочая папка одного запуска, а не архив кампании, и
                // повторная передача того же файла — обычный, а не аварийный
                // случай (перезапуск шага, повтор пайплайна). Счётчик в имени
                // только запутал бы Claude, читающего inbox.
                match std::fs::copy(entry.path(), inbox.join(&name)) {
                    Ok(_) => result.forwarded.push(name),
                    Err(e) => {
                        warn!("Выгрузка не передана во входящие: {name}: {e}");
                        result.failed.push((name, e.to_string()));
                    }
                }
            }
        }
    }
    result
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
    let result = copy_brief_files(&brief_dir, &brief_file_paths);
    if !result.failed.is_empty() {
        let names: Vec<&str> = result.failed.iter().map(|(n, _)| n.as_str()).collect();
        warn!(
            "Кампания {campaign_id}: {} файлов брифа не сохранено: {}",
            result.failed.len(),
            names.join(", ")
        );
    }
    campaign.brief_files = result.saved;

    let json = serde_json::to_string_pretty(&campaign).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())?;
    Ok(campaign)
}

/// Итог копирования файлов брифа в каталог кампании.
///
/// 🔴 CPD-81, третий носитель класса (найден 14.08.2026 линией Legal Center — в ИХ дереве и
/// сразу же проверен в нашем, где он тоже был жив, хотя дефект уже числился закрытым).
/// Прежний код отбрасывал результат `fs::copy` и добавлял имя в список сохранённых
/// безусловно, а исходный путь, которого не оказалось на диске, пропускал вовсе — без следа
/// ни в списке сохранённых, ни в журнале.
///
/// Необратимости здесь нет, и потому уровень правки проще, чем у `persist_step_exports`:
/// источник — файл на диске пользователя, выбранный им в окне выбора, и после отказа он
/// никуда не девается; `campaign.brief_files` сегодня никем не читается обратно
/// (`lib.rs` держит `_brief_files_dir` неиспользуемым). Признака фатального отказа тут не
/// заводится сознательно: тревога, у которой нет потребителя, обесценивает те, у которых он
/// есть. Закрывается ровно ложь списка — и она закрывается полностью.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct BriefFilesResult {
    /// Имена файлов, которые действительно лежат в каталоге брифа.
    pub saved: Vec<String>,
    /// (имя либо исходный путь, причина отказа)
    pub failed: Vec<(String, String)>,
}

/// Копирует файлы брифа в каталог кампании, честно разделяя удавшееся и нет.
///
/// Вынесено из `campaign_set_brief` отдельной функцией ради проверяемости: сама команда
/// строит путь через `campaigns_dir` → корень результатов пользователя, то есть в тесте
/// писала бы в настоящую папку на рабочем столе. Приём заимствован у линии Legal Center,
/// закрывшей этот же носитель в тот же день.
pub fn copy_brief_files(brief_dir: &Path, brief_file_paths: &[String]) -> BriefFilesResult {
    let mut result = BriefFilesResult::default();
    if let Err(e) = std::fs::create_dir_all(brief_dir) {
        // Каталог не создан — копировать некуда, и это касается ВСЕХ путей сразу.
        for src_path in brief_file_paths {
            result
                .failed
                .push((src_path.clone(), format!("каталог брифа не создан: {e}")));
        }
        return result;
    }
    for src_path in brief_file_paths {
        let src = Path::new(src_path);
        if !src.exists() {
            result
                .failed
                .push((src_path.clone(), "исходный файл не найден".to_string()));
            continue;
        }
        let Some(name) = src.file_name() else {
            result
                .failed
                .push((src_path.clone(), "в пути нет имени файла".to_string()));
            continue;
        };
        let name = name.to_string_lossy().to_string();
        match std::fs::copy(src, brief_dir.join(&name)) {
            Ok(_) => result.saved.push(name),
            Err(e) => result.failed.push((name, e.to_string())),
        }
    }
    result
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
    // Путь берётся из общего источника, а не собирается заново — CPD-31: если корень
    // когда-нибудь переедет (как уже случилось в Docs Lab, INV-82), обе функции
    // обязаны узнать об этом одновременно, а не молча разойтись.
    let campaigns_root = campaigns_root();
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

    /// CPD-31: единственный источник пути (campaigns_root) — превентивно, до переезда.
    /// Живой прецедент — Docs Lab (dd4c652): campaigns_dir переехал на общий корень
    /// результатов, а fix_interrupted_campaigns осталась сканировать старый путь —
    /// сканировала пустоту и выходила молча, кампании в статусе «running» никогда не
    /// помечались «прерванными». Здесь оба потребителя пока согласованы (общий старый
    /// путь), но были согласованы НЕЗАВИСИМО — сторож ловит будущее расхождение.
    #[test]
    fn campaigns_dir_lives_under_the_root_that_recovery_scans() {
        // 🔴 Внешний аудит 2026-07-29 (High): прежняя версия этого теста была ТАВТОЛОГИЕЙ —
        // `root.join(x).starts_with(root)` истинно всегда, а сам код восстановления тест не
        // читал вовсе. Имя утверждало то, чего проверка не делала: подмена пути внутри
        // `fix_interrupted_campaigns` оставляла сторож зелёным, и исходный дефект возвращался.
        // Теперь проверяется главное — что восстановление берёт корень из общей функции.
        let root = campaigns_root();
        let brand_dir = campaigns_dir("default");
        assert!(
            brand_dir.starts_with(&root),
            "каталог бренда {} обязан лежать под корнем {}",
            brand_dir.display(),
            root.display()
        );

        let src = include_str!("campaign.rs");
        let recovery_start = src
            .find("pub fn fix_interrupted_campaigns")
            .expect("функция восстановления не найдена — разметка модуля переехала");
        let recovery_body = &src[recovery_start..(recovery_start + 900).min(src.len())];
        let recovery_code: String = recovery_body
            .lines()
            .map(|line| line.trim_start())
            .filter(|line| !line.starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");
        assert!(
            recovery_code.contains("campaigns_root()"),
            "fix_interrupted_campaigns обязана брать корень из campaigns_root(), а не собирать \
             путь заново — иначе переезд корня разведёт запись и восстановление молча"
        );
    }

    /// Вторая половина того же сторожа: путь обязан собираться РОВНО В ОДНОМ месте —
    /// внутри campaigns_root(). Не «нигде», как в Docs Lab (там корень уже переехал на
    /// общий Aurora_AI, и старое имя каталога пропало из модуля целиком) — здесь путь
    /// этой правкой НЕ переезжает (CPD-31 — только подготовка, решение о переезде не
    /// принято), поэтому campaigns_root() легитимно продолжает строить прежний путь,
    /// но ровно один раз. Проверка идёт по ИСХОДНИКУ, потому что сравнение значений
    /// выше не увидит второй, независимый источник — сравниваются РЕЗУЛЬТАТЫ, а не то,
    /// откуда они взялись.
    #[test]
    fn campaigns_path_built_in_exactly_one_place() {
        let src = include_str!("campaign.rs");
        let marker = concat!(".join(", "\"", "AIAgency", "\"", ")");
        let occurrences = src.matches(marker).count();
        assert_eq!(
            occurrences, 1,
            "путь до общего каталога кампаний должен собираться РОВНО в одном месте \
             (внутри campaigns_root), а найдено вхождений: {occurrences}. Второй независимый \
             источник развалится молча при будущем переезде корня, как это уже было в Docs Lab"
        );
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

        let result = persist_step_exports(&campaign_dir, "step-1", &exports);
        assert_eq!(result.copied, vec!["report.md".to_string()]);
        assert!(result.failed.is_empty());
        assert!(campaign_dir.join("steps").join("step-1").join("report.md").exists());
    }

    /// Аудит 2.4.9, Medium-5: повторный прогон шага ЗАМЕЩАЕТ свой прежний результат,
    /// а не копит версии рядом.
    ///
    /// Прежний тест закреплял обратное — файл ложился как `report (2).md`, прежний
    /// оставался, — и это было неверное ожидание: каталог кампании строится из
    /// идентификатора сценария, а `forward_exports_to_inbox` копирует его целиком,
    /// поэтому следующий шаг получал во входящие обе версии сразу.
    #[test]
    fn persist_step_exports_rerun_replaces_previous_file_not_versions_it() {
        let tmp = tempfile::tempdir().unwrap();
        let campaign_dir = tmp.path().join("campaign-1");
        let dest = campaign_dir.join("steps").join("step-1");
        std::fs::create_dir_all(&dest).unwrap();
        std::fs::write(dest.join("report.md"), "СТАРЫЙ").unwrap();

        let exports = tmp.path().join("exports");
        std::fs::create_dir_all(&exports).unwrap();
        std::fs::write(exports.join("report.md"), "НОВЫЙ").unwrap();

        let result = persist_step_exports(&campaign_dir, "step-1", &exports);
        assert_eq!(
            result.copied,
            vec!["report.md".to_string()],
            "в списке успешных ровно одно имя — и ровно то, что лежит на диске"
        );
        assert!(result.failed.is_empty());
        assert!(result.fatal.is_none());

        // Свежий результат замещает устаревший.
        assert_eq!(
            std::fs::read_to_string(dest.join("report.md")).unwrap(),
            "НОВЫЙ"
        );
        // Второй версии рядом не появилось — иначе следующий шаг получил бы во
        // входящие обе и рассуждал по противоречивым данным.
        assert!(
            !dest.join("report (2).md").exists(),
            "версия со счётчиком рядом с замещённым файлом появляться не должна"
        );
        assert_eq!(
            std::fs::read_dir(&dest).unwrap().count(),
            1,
            "в каталоге шага обязан остаться ровно один файл"
        );
    }

    /// CPD-81: отказ копирования — имя НЕ попадает в copied и попадает в failed.
    ///
    /// Отказ воспроизведён так: каталог "step-1" подменён файлом, поэтому
    /// fs::create_dir_all внутри функции
    /// молча не создаст вложенный путь, а fs::copy откажет, потому что родитель
    /// целевого пути — не каталог. Портируемо между Windows и Unix.
    #[test]
    fn persist_step_exports_copy_failure_recorded_not_lost() {
        let tmp = tempfile::tempdir().unwrap();
        let campaign_dir = tmp.path().join("campaign-1");
        let steps_dir = campaign_dir.join("steps");
        std::fs::create_dir_all(&steps_dir).unwrap();
        std::fs::write(steps_dir.join("step-1"), "занято файлом").unwrap();

        let exports = tmp.path().join("exports");
        std::fs::create_dir_all(&exports).unwrap();
        std::fs::write(exports.join("report.md"), "# Report").unwrap();

        let result = persist_step_exports(&campaign_dir, "step-1", &exports);
        assert!(result.copied.is_empty());
        assert_eq!(result.failed.len(), 1);
        assert_eq!(result.failed[0].0, "report.md");
    }

    /// Аудит 2.4.9 (High-4), обязательный контроль: каталог выгрузок подменён файлом →
    /// `read_dir` падает → признак фатального отказа непуст.
    ///
    /// До правки этот путь давал `copied=[]`, `failed=[]` и запись в журнале
    /// «Persisted 0 exports for step X (0 failed)», после которой `close_session`
    /// стирал рабочий каталог с единственной копией файлов шага.
    #[test]
    fn persist_step_exports_read_dir_failure_is_fatal_not_silent() {
        let tmp = tempfile::tempdir().unwrap();
        let campaign_dir = tmp.path().join("campaign-1");
        // Место каталога выгрузок занято обычным файлом: `exists()` истинно,
        // `read_dir` откажет. Портируемо между Windows и Unix.
        let exports = tmp.path().join("exports");
        std::fs::write(&exports, "не каталог").unwrap();

        let result = persist_step_exports(&campaign_dir, "step-1", &exports);

        assert!(result.copied.is_empty());
        assert!(result.failed.is_empty(), "поимённого списка здесь быть и не может");
        assert!(
            result.fatal.is_some(),
            "отказ чтения каталога выгрузок обязан быть виден вызывающему"
        );
        assert!(result.fatal.unwrap().contains("не прочитан"));
    }

    /// Тот же класс: каталог назначения создать не удалось (место занято файлом).
    /// Признак фатального отказа непуст ещё до перебора файлов.
    #[test]
    fn persist_step_exports_create_dir_failure_is_fatal() {
        let tmp = tempfile::tempdir().unwrap();
        let campaign_dir = tmp.path().join("campaign-1");
        let steps_dir = campaign_dir.join("steps");
        std::fs::create_dir_all(&steps_dir).unwrap();
        std::fs::write(steps_dir.join("step-1"), "занято файлом").unwrap();

        let exports = tmp.path().join("exports");
        std::fs::create_dir_all(&exports).unwrap();
        std::fs::write(exports.join("report.md"), "# Report").unwrap();

        let result = persist_step_exports(&campaign_dir, "step-1", &exports);

        assert!(result.copied.is_empty());
        assert!(
            result.fatal.is_some(),
            "отказ создания каталога назначения обязан быть виден вызывающему"
        );
        // Поимённый отказ копирования при этом никуда не делся — оба сигнала на месте.
        assert_eq!(result.failed.len(), 1);
    }

    /// Штатный путь фатального признака не выставляет — иначе тревога обесценится.
    #[test]
    fn persist_step_exports_success_has_no_fatal() {
        let tmp = tempfile::tempdir().unwrap();
        let campaign_dir = tmp.path().join("campaign-1");
        let exports = tmp.path().join("exports");
        std::fs::create_dir_all(&exports).unwrap();
        std::fs::write(exports.join("report.md"), "# Report").unwrap();

        let result = persist_step_exports(&campaign_dir, "step-1", &exports);
        assert_eq!(result.copied, vec!["report.md".to_string()]);
        assert!(result.fatal.is_none());
    }

    /// Та же проверка для второй функции того же класса: каталог-источник подменён
    /// файлом → `read_dir` падает → признак отказа непуст, пустой `forwarded` больше
    /// не читается как «передавать было нечего».
    #[test]
    fn forward_exports_to_inbox_read_dir_failure_is_fatal_not_silent() {
        let tmp = tempfile::tempdir().unwrap();
        let prev_exports = tmp.path().join("prev-exports");
        std::fs::write(&prev_exports, "не каталог").unwrap();
        let next_workspace = tmp.path().join("next-workspace");

        let result = forward_exports_to_inbox(&prev_exports, &next_workspace);

        assert!(result.forwarded.is_empty());
        assert!(result.failed.is_empty());
        assert!(result.fatal.is_some(), "отказ чтения источника обязан быть виден");
    }

    /// Штатная передача: файл доезжает во входящие, признаков отказа нет.
    #[test]
    fn forward_exports_to_inbox_success() {
        let tmp = tempfile::tempdir().unwrap();
        let prev_exports = tmp.path().join("prev-exports");
        std::fs::create_dir_all(&prev_exports).unwrap();
        std::fs::write(prev_exports.join("summary.md"), "итог шага").unwrap();
        let next_workspace = tmp.path().join("next-workspace");

        let result = forward_exports_to_inbox(&prev_exports, &next_workspace);

        assert_eq!(result.forwarded, vec!["summary.md".to_string()]);
        assert!(result.failed.is_empty());
        assert!(result.fatal.is_none());
        assert!(next_workspace.join("inbox").join("summary.md").exists());
    }

    /// Отказ копирования во входящие: место каталога входящих занято файлом, поэтому
    /// `create_dir_all` откажет, а следом откажет и копирование — имя НЕ попадает в
    /// «передано», отказ виден и поимённо, и фатальным признаком.
    #[test]
    fn forward_exports_to_inbox_copy_failure_recorded_not_lost() {
        let tmp = tempfile::tempdir().unwrap();
        let prev_exports = tmp.path().join("prev-exports");
        std::fs::create_dir_all(&prev_exports).unwrap();
        std::fs::write(prev_exports.join("summary.md"), "итог шага").unwrap();

        let next_workspace = tmp.path().join("next-workspace");
        std::fs::create_dir_all(&next_workspace).unwrap();
        std::fs::write(next_workspace.join("inbox"), "занято файлом").unwrap();

        let result = forward_exports_to_inbox(&prev_exports, &next_workspace);

        assert!(result.forwarded.is_empty());
        assert_eq!(result.failed.len(), 1);
        assert_eq!(result.failed[0].0, "summary.md");
        assert!(result.fatal.is_some());
        // Источник цел: здесь потери данных нет, теряется контекст шага.
        assert!(prev_exports.join("summary.md").exists());
    }

    /// CPD-81 (вторая функция): при совпадении имени файл во входящих ПЕРЕЗАПИСЫВАЕТСЯ
    /// намеренно (без unique_export_path) — повторная передача того же файла считается
    /// обычным случаем (перезапуск шага), решение обосновано в комментарии над функцией.
    #[test]
    fn forward_exports_to_inbox_name_collision_overwrites_by_design() {
        let tmp = tempfile::tempdir().unwrap();
        let prev_exports = tmp.path().join("prev-exports");
        std::fs::create_dir_all(&prev_exports).unwrap();
        std::fs::write(prev_exports.join("summary.md"), "НОВЫЙ").unwrap();

        let next_workspace = tmp.path().join("next-workspace");
        let inbox = next_workspace.join("inbox");
        std::fs::create_dir_all(&inbox).unwrap();
        std::fs::write(inbox.join("summary.md"), "СТАРЫЙ").unwrap();

        let result = forward_exports_to_inbox(&prev_exports, &next_workspace);
        assert_eq!(result.forwarded, vec!["summary.md".to_string()]);
        assert!(result.failed.is_empty());
        assert_eq!(std::fs::read_to_string(inbox.join("summary.md")).unwrap(), "НОВЫЙ");
    }

    /// CPD-81, третий носитель: файл, который не удалось скопировать, НЕ попадает в список
    /// сохранённых.
    ///
    /// Ось мутации: вернуть `let _ = std::fs::copy(...)` с безусловным
    /// `saved.push(name)` — тест обязан покраснеть.
    ///
    /// Отказ подстроен честно: на месте будущего файла заранее создан КАТАЛОГ с тем же
    /// именем, поэтому `fs::copy` отказывает по-настоящему, а не имитацией. Соседний файл
    /// при этом копируется штатно — один отказ не должен топить остальные.
    #[test]
    fn copy_brief_files_failed_copy_never_gets_into_saved() {
        let tmp = tempfile::tempdir().unwrap();
        let src_dir = tmp.path().join("источник");
        std::fs::create_dir_all(&src_dir).unwrap();
        let занятый = src_dir.join("занятый.docx");
        let обычный = src_dir.join("обычный.md");
        std::fs::write(&занятый, "бриф").unwrap();
        std::fs::write(&обычный, "бриф").unwrap();

        let brief_dir = tmp.path().join("brief-files");
        std::fs::create_dir_all(brief_dir.join("занятый.docx")).unwrap();

        let result = copy_brief_files(
            &brief_dir,
            &[
                занятый.to_string_lossy().to_string(),
                обычный.to_string_lossy().to_string(),
            ],
        );

        assert_eq!(
            result.saved,
            vec!["обычный.md".to_string()],
            "в списке сохранённых обязан остаться только тот файл, что реально скопирован"
        );
        assert_eq!(result.failed.len(), 1);
        assert_eq!(result.failed[0].0, "занятый.docx");
    }

    /// Исходного файла нет на диске: раньше он пропускался молча — ни в сохранённых, ни в
    /// отказах, ни в журнале. Теперь виден поимённо.
    #[test]
    fn copy_brief_files_missing_source_is_reported_not_skipped_silently() {
        let tmp = tempfile::tempdir().unwrap();
        let brief_dir = tmp.path().join("brief-files");
        let нет_такого = tmp.path().join("нет-такого.docx");

        let result = copy_brief_files(&brief_dir, &[нет_такого.to_string_lossy().to_string()]);

        assert!(result.saved.is_empty());
        assert_eq!(result.failed.len(), 1, "пропуск обязан быть виден");
        assert!(result.failed[0].1.contains("не найден"));
    }

    /// Штатный путь отказов не выдумывает — иначе предупреждение обесценится.
    #[test]
    fn copy_brief_files_success_has_no_failures() {
        let tmp = tempfile::tempdir().unwrap();
        let src = tmp.path().join("бриф.md");
        std::fs::write(&src, "текст брифа").unwrap();
        let brief_dir = tmp.path().join("brief-files");

        let result = copy_brief_files(&brief_dir, &[src.to_string_lossy().to_string()]);

        assert_eq!(result.saved, vec!["бриф.md".to_string()]);
        assert!(result.failed.is_empty());
        assert!(brief_dir.join("бриф.md").exists());
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
