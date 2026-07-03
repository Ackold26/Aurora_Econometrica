//! Econometrica sidecar HTTP proxy commands.
//!
//! Forwards computation requests to the Python sidecar. Порт больше не
//! захардкожен - читается из `econ_sidecar::current_port()`, который устанавливается
//! через `sidecar_runtime::allocate_port()` (deterministic per-user).
//!
//! All heavy math (MCMC, optimization, charts) runs locally in Python - 0 Claude tokens.
//!
//! # v1.0.9: X-Expected-Session handshake
//! Каждый POST добавляет заголовок `X-Expected-Session: <uuid>`. Sidecar
//! возвращает 409 если session_id не совпадает (foreign sidecar после reset),
//! и тогда мы делаем re-handshake (ensure_alive) + retry один раз.

use serde_json::Value;
use log::{info, warn};
use std::sync::OnceLock;
use std::time::Duration;

use crate::econ_sidecar;

/// Базовый URL sidecar - динамический порт. Использовать только через эту функцию.
fn econ_url(path: &str) -> String {
    format!("{}{}", econ_sidecar::base_url(), path)
}

/// Добавляет заголовок X-Expected-Session если session_id известен.
fn with_session(rb: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
    if let Some(sid) = econ_sidecar::current_session_id() {
        rb.header("X-Expected-Session", sid)
    } else {
        rb
    }
}

/// Timeout for quick endpoints (validate, decompose, optimize, charts)
const QUICK_TIMEOUT_SECS: u64 = 60;

/// Timeout for long-running endpoints (MCMC training)
const TRAIN_TIMEOUT_SECS: u64 = 900; // 15 minutes

/// Static clients - avoid TLS bootstrap + connection pool setup per request.
static QUICK_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
static TRAIN_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
static HEALTH_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();

fn quick_client() -> &'static reqwest::Client {
    QUICK_CLIENT.get_or_init(|| reqwest::Client::builder()
        .timeout(Duration::from_secs(QUICK_TIMEOUT_SECS))
        .build().unwrap_or_default())
}

fn train_client() -> &'static reqwest::Client {
    TRAIN_CLIENT.get_or_init(|| reqwest::Client::builder()
        .timeout(Duration::from_secs(TRAIN_TIMEOUT_SECS))
        .build().unwrap_or_default())
}

fn health_client() -> &'static reqwest::Client {
    HEALTH_CLIENT.get_or_init(|| reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build().unwrap_or_default())
}

// ── Health ───────────────────────────────────────────

#[tauri::command]
pub async fn econ_health() -> Result<Value, String> {
    match health_client()
        .get(econ_url("/health"))
        .send()
        .await
    {
        Ok(resp) => resp.json::<Value>().await.map_err(|e| format!("Parse error: {e}")),
        Err(e) => Ok(serde_json::json!({
            "status": "unavailable",
            "error": format!("{e}"),
        })),
    }
}

// ── Project migration (Phase 1.4) ────────────────────

/// Validate `project_dir` against path traversal (audit H-01).
///
/// Rejects paths containing `..` segments. Defense-in-depth before forwarding
/// к Python sidecar (который сам проверяет через `_assert_project_dir_safe`).
/// Этот guard ловит trivial attacks без round-trip к sidecar.
fn validate_project_dir(project_dir: &str) -> Result<(), String> {
    if project_dir.is_empty() {
        return Err("project_dir is empty".to_string());
    }
    let path = std::path::Path::new(project_dir);
    for component in path.components() {
        if matches!(component, std::path::Component::ParentDir) {
            return Err(format!(
                "project_dir traversal blocked (contains '..'): {project_dir}"
            ));
        }
    }
    Ok(())
}

/// Migrate project.json к schema_version 2.0.1 (Phase 1.4 / Audit P-03).
///
/// Sync migration: reclassifies SOM/SOV/share_of_* columns from
/// control_columns → excluded_columns per BUG #3 fix. Idempotent —
/// repeated calls return `status: 'no_migration_needed'`.
///
/// Pre-mutation backup `.pre_2.0.1` с SHA-256 (recoverable on failure).
/// Atomic write через safe_io. NB: sync version; async modal UI defer к v2.0.2.
///
/// Path traversal guard (H-01): rejects paths containing `..` segments before
/// forwarding к Python.
#[tauri::command]
pub async fn econ_migrate_project(project_dir: String) -> Result<Value, String> {
    info!("econ_migrate_project: {project_dir}");
    validate_project_dir(&project_dir)?;
    let body = serde_json::json!({ "project_dir": project_dir });
    post_json("/project/migrate", &body, quick_client()).await
}

// ── Static asset (Phase 1.1 SSOT) ────────────────────

/// SSOT classifier patterns export для frontend (Phase 1.1).
///
/// Frontend (src/lib/services/classifier-patterns.js) calls this once
/// на startup, caches result. Replaces regex duplication между Python
/// и Svelte components.
#[tauri::command]
pub async fn econ_classifier_patterns() -> Result<Value, String> {
    let url = econ_url("/api/static/classifier-patterns-v1.json");
    match with_session(quick_client().get(&url)).send().await {
        Ok(resp) => parse_resp(resp, "/api/static/classifier-patterns-v1.json").await,
        Err(e) => Err(format!("Не удалось получить classifier patterns: {e}")),
    }
}


// ── Compute ──────────────────────────────────────────

/// LOAD-1 (B2): резолв аргумента `project_dir` команды econ_validate в абсолютный
/// путь, чтобы sidecar сохранял `results/validation.json` в папку проекта.
///
/// Корень бага: фронт (ValidateStepV13 / legacy ValidateStep) шлёт **bare
/// project_id** как `project_dir`. Sidecar делал `Path(project_dir)/results/...`
/// → относительный CWD сайдкара → запись «успешна», но не в `%APPDATA%/.../projects/<id>/`.
/// `find` validation.json = 0 файлов → реоткрытие проекта показывало пустую Валидацию.
/// Decompose/Optimize не страдали, т.к. фронт резолвит путь через `project_get_dir`
/// ПЕРЕД вызовом. B2 — один SSOT-резолв в Rust: чинит обоих вызывающих и все
/// будущие econ_validate без дрейфа (vs B1 — резолв в 2 местах фронта).
///
/// - `None` / пусто → `None` (валидация без сохранения — допустимо).
/// - Уже абсолютный путь → passthrough (backward-compat: .aurora импорт, старый код).
/// - Относительный (bare project_id) → `project_dir(id)` (как econ_export_pptx:438),
///   под `validate_project_dir` guard (path-traversal `..`).
fn resolve_project_dir_arg(project_dir: Option<String>) -> Result<Option<String>, String> {
    match project_dir {
        None => Ok(None),
        Some(pd) if pd.trim().is_empty() => Ok(None),
        Some(pd) if std::path::Path::new(&pd).is_absolute() => Ok(Some(pd)),
        Some(pd) => {
            validate_project_dir(&pd)?; // guard ДО резолва (defense-in-depth)
            let abs = crate::commands::project::project_dir(&pd)
                .map(|p| p.to_string_lossy().to_string())?;
            Ok(Some(abs))
        }
    }
}

#[tauri::command]
pub async fn econ_validate(file_path: String, project_dir: Option<String>) -> Result<Value, String> {
    info!("econ_validate: {file_path}");
    let resolved_dir = resolve_project_dir_arg(project_dir)?;
    let body = serde_json::json!({ "file_path": file_path, "project_dir": resolved_dir });
    post_json("/compute/validate", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_train(config: Value) -> Result<Value, String> {
    info!("econ_train: {:?}", config.get("kpi_column"));
    post_json("/compute/train", &config, train_client()).await
}

#[tauri::command]
pub async fn econ_decompose(
    project_dir: String,
    unit_costs: Option<Value>,
    // Phase 2 audit pass 4 - per-channel annual CPP/CPM inflation rates.
    unit_cost_inflation_pct: Option<Value>,
    // v2.1.0 (ADR-021): ценность единицы count KPI (₽/уп., ₽/лид).
    // None = ROI в native units. Override pickle snapshot for already-trained
    // models когда юзер задаёт value позже.
    kpi_unit_cost: Option<f64>,
) -> Result<Value, String> {
    info!("econ_decompose: {project_dir}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "unit_costs": unit_costs,
        "unit_cost_inflation_pct": unit_cost_inflation_pct,
        "kpi_unit_cost": kpi_unit_cost,
    });
    post_json("/compute/decompose", &body, quick_client()).await
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn econ_optimize(
    project_dir: String,
    total_budget: Option<f64>,
    total_budget_money: Option<f64>,
    min_pct: Option<f64>,
    max_pct: Option<f64>,
    min_per_channel: Option<Value>,
    max_per_channel: Option<Value>,
    // F.2 (D.3 frontend): per-group constraints (Trust 3 brand vs performance).
    // None = optimizer falls back к global. Mixed channels всегда наследуют global.
    brand_min_pct: Option<f64>,
    brand_max_pct: Option<f64>,
    perf_min_pct: Option<f64>,
    perf_max_pct: Option<f64>,
    unit_costs: Option<Value>,
    // Phase 2 (Planning Mode) - opt-in. None = analyst mode (current behavior
    // preserved byte-exact). Some(int) = Option C per-period Hill summation.
    forecast_periods: Option<i64>,
    forecast_period_label: Option<String>,
    // Phase 2 audit pass 4 - per-channel annual CPP/CPM inflation rates.
    unit_cost_inflation_pct: Option<Value>,
    // F1 fix 2026-05-03 (Phase 5 follow-up audit): prior optimize call's
    // optimal_spend_money per channel - backend uses as direct candidate
    // anchor для transitive chain monotonicity (invariant I5b).
    // None = first-call OR pickle/budget changed → backend skips silently.
    prev_optimal: Option<Value>,
    // v2.1.0 (ADR-021): money lift для count KPI.
    kpi_unit_cost: Option<f64>,
) -> Result<Value, String> {
    info!("econ_optimize: {project_dir}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "total_budget": total_budget,
        "total_budget_money": total_budget_money,
        // O1.1 (Phase 0.1 fix-session 2026-04-25): 50/150 → 20/200 для real optimization freedom.
        // See OptimizeStep.svelte for rationale + docs/MATH_AUDIT_v1_3_PHASE_0_1.md.
        "min_pct": min_pct.unwrap_or(20.0),
        "max_pct": max_pct.unwrap_or(200.0),
        "min_per_channel": min_per_channel,
        "max_per_channel": max_per_channel,
        "brand_min_pct": brand_min_pct,
        "brand_max_pct": brand_max_pct,
        "perf_min_pct": perf_min_pct,
        "perf_max_pct": perf_max_pct,
        "unit_costs": unit_costs,
        "forecast_periods": forecast_periods,
        "forecast_period_label": forecast_period_label,
        "unit_cost_inflation_pct": unit_cost_inflation_pct,
        "prev_optimal": prev_optimal,
        "kpi_unit_cost": kpi_unit_cost,
    });
    post_json("/compute/optimize", &body, quick_client()).await
}

// ─── Phase 2 (Planning Mode) - preview endpoints ───────────────────────────

#[tauri::command]
pub async fn econ_forecast_context(project_dir: String) -> Result<Value, String> {
    info!("econ_forecast_context: {project_dir}");
    let body = serde_json::json!({ "project_dir": project_dir });
    post_json("/compute/forecast-context", &body, quick_client()).await
}

/// A3/OPP-08 (2026-07-03, решение по месту): фронт эту команду НЕ вызывает —
/// потребность «план vs история» покрыта доставкой extrapolation-маркеров
/// прямо в результаты goal-seek (F-01), сценариев (F-04) и forward-оптимизации
/// (OPP-03). Endpoint /compute/forecast-scaling остаётся внутренним API
/// (контур математики масштабирования, ~10 тестов: test_phase2_synergies G5,
/// test_server_phase2_endpoints); мост сохранён как кандидат для E1
/// backtest-витрины (ROADMAP v3). НЕ считать этот мост «фичей с UI».
#[tauri::command]
pub async fn econ_forecast_scaling(
    project_dir: String,
    forecast_periods: i64,
    forecast_budget_money: Option<f64>,
) -> Result<Value, String> {
    info!("econ_forecast_scaling: {project_dir} periods={forecast_periods}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "forecast_periods": forecast_periods,
        "forecast_budget_money": forecast_budget_money,
    });
    post_json("/compute/forecast-scaling", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_hierarchical_warning(
    project_dir: String,
    forecast_budget_money: f64,
    train_total_money: Option<f64>,
) -> Result<Value, String> {
    info!("econ_hierarchical_warning: {project_dir} budget={forecast_budget_money} train_total={train_total_money:?}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "forecast_budget_money": forecast_budget_money,
        "train_total_money": train_total_money,
    });
    post_json("/compute/hierarchical-warning", &body, quick_client()).await
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn econ_scenario(
    project_dir: String,
    scenario_name: String,
    media_plan: Option<Value>,
    media_plan_file: Option<String>,
    unit_costs: Option<Value>,
    // Phase 2 (audit pass 4) - planning context. None = analyst (legacy: distribute
    // single-period totals по training_n_periods). Some(int) = planning (distribute
    // по forecast_periods, matching optimizer planner mode).
    forecast_periods: Option<i64>,
    forecast_period_label: Option<String>,
    // Phase 2 audit pass 4 - per-channel annual CPP/CPM inflation rates.
    unit_cost_inflation_pct: Option<Value>,
    // v2.1.0 (ADR-021): money equivalents для count KPI scenario forecast.
    kpi_unit_cost: Option<f64>,
) -> Result<Value, String> {
    info!("econ_scenario: {scenario_name}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "scenario_name": scenario_name,
        "media_plan": media_plan.unwrap_or(Value::Object(Default::default())),
        "media_plan_file": media_plan_file,
        "unit_costs": unit_costs,
        "forecast_periods": forecast_periods,
        "forecast_period_label": forecast_period_label,
        "unit_cost_inflation_pct": unit_cost_inflation_pct,
        "kpi_unit_cost": kpi_unit_cost,
    });
    post_json("/compute/scenario", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_compare(project_dir: String, unit_costs: Option<Value>) -> Result<Value, String> {
    let body = serde_json::json!({
        "project_dir": project_dir,
        "unit_costs": unit_costs,
    });
    post_json("/compute/compare", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_scenario_delete(project_dir: String, scenario_name: String) -> Result<Value, String> {
    info!("econ_scenario_delete: {scenario_name}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "scenario_name": scenario_name,
    });
    post_json("/compute/scenario/delete", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_awareness_forecast(config: Value) -> Result<Value, String> {
    info!("econ_awareness_forecast");
    post_json("/compute/awareness/forecast", &config, quick_client()).await
}

#[tauri::command]
pub async fn econ_awareness_sales(config: Value) -> Result<Value, String> {
    info!("econ_awareness_sales");
    post_json("/compute/awareness/sales", &config, quick_client()).await
}

// ── Async training ───────────────────────────────────

#[tauri::command]
pub async fn econ_train_start(config: Value) -> Result<Value, String> {
    info!("econ_train_start: {:?}", config.get("kpi_column"));
    post_json("/compute/train/start", &config, quick_client()).await
}

#[tauri::command]
pub async fn econ_train_progress() -> Result<Value, String> {
    with_session(health_client().get(econ_url("/compute/train/progress")))
        .send()
        .await
        .map_err(|e| format!("Вычислительный модуль недоступен: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("Ошибка парсинга ответа: {e}"))
}

#[tauri::command]
pub async fn econ_train_cancel(task_id: String) -> Result<Value, String> {
    info!("econ_train_cancel: {task_id}");
    with_session(quick_client().post(econ_url(&format!("/compute/train/cancel/{task_id}"))))
        .send()
        .await
        .map_err(|e| format!("Вычислительный модуль недоступен: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("Ошибка парсинга ответа: {e}"))
}

#[tauri::command]
pub async fn econ_train_result(task_id: String) -> Result<Value, String> {
    info!("econ_train_result: {task_id}");
    with_session(quick_client().get(econ_url(&format!("/compute/train/result/{task_id}"))))
        .send()
        .await
        .map_err(|e| format!("Вычислительный модуль недоступен: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("Ошибка парсинга ответа: {e}"))
}

// ── Data Preview ─────────────────────────────────────

#[tauri::command]
pub async fn econ_data_preview(file_path: String, n_rows: Option<u32>) -> Result<Value, String> {
    info!("econ_data_preview: {file_path}");
    let body = serde_json::json!({
        "file_path": file_path,
        "n_rows": n_rows.unwrap_or(20),
    });
    post_json("/compute/validate/preview", &body, quick_client()).await
}

// ── Trust Level 3: Channel Categorization (v1.1.0) ─────

#[tauri::command]
pub async fn econ_categorize_channels(channels: Vec<String>) -> Result<Value, String> {
    let body = serde_json::json!({ "channels": channels });
    post_json("/utils/auto_suggest_categories", &body, quick_client()).await
}

// ── Charts ───────────────────────────────────────────

#[tauri::command]
pub async fn econ_chart(project_dir: String, chart_type: String) -> Result<Value, String> {
    let body = serde_json::json!({
        "project_dir": project_dir,
        "chart_type": chart_type,
    });
    post_json("/chart", &body, quick_client()).await
}

// ── Adstock Auto-Select ─────────────────────────────

#[tauri::command]
pub async fn econ_adstock_select(
    file_path: String,
    kpi_column: String,
    media_columns: Vec<String>,
) -> Result<Value, String> {
    info!("econ_adstock_select: {file_path}, kpi={kpi_column}, channels={}", media_columns.len());
    let body = serde_json::json!({
        "file_path": file_path,
        "kpi_column": kpi_column,
        "media_columns": media_columns,
    });
    post_json("/compute/adstock_select", &body, quick_client()).await
}

// ── PPTX Export ─────────────────────────────────────

#[tauri::command]
pub async fn econ_export_pptx(
    project_id: String,
    model_data: Value,
    decompose_data: Value,
    optimize_data: Value,
) -> Result<Value, String> {
    info!("econ_export_pptx: project={project_id}");
    // Передаём абсолютный project_dir чтобы sidecar находил scenarios/exports
    // в customizable папке (настраивается в Settings). Без этого Python
    // читал бы захардкоженный %APPDATA% путь, игнорируя Settings override.
    let project_dir = crate::commands::project::project_dir(&project_id)
        .map(|p| p.to_string_lossy().to_string())
        .ok();
    let body = serde_json::json!({
        "project_id": project_id,
        "project_dir": project_dir,
        "model_data": model_data,
        "decompose_data": decompose_data,
        "optimize_data": optimize_data,
    });
    post_json("/export/pptx", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_export_html(
    project_id: String,
    model_data: Value,
    decompose_data: Value,
    optimize_data: Value,
    project_name: Option<String>,
) -> Result<Value, String> {
    info!("econ_export_html: project={project_id}");
    let project_dir = crate::commands::project::project_dir(&project_id)
        .map(|p| p.to_string_lossy().to_string())
        .ok();
    let body = serde_json::json!({
        "project_id": project_id,
        "project_dir": project_dir,
        "model_data": model_data,
        "decompose_data": decompose_data,
        "optimize_data": optimize_data,
        "project_name": project_name.unwrap_or_else(|| "Marketing Mix Model".to_string()),
    });
    post_json("/export/html", &body, quick_client()).await
}

// ──────────────────────────────────────────────────────────────────
// Sprint 3 Pharma Causal - frontend invokers (per ADR §1 EXTEND-not-rewrite)
// All causal endpoints вызываются через единый pass-through pattern: frontend
// builds request JSON, Rust forwards to FastAPI sidecar, returns Value verbatim.
// ──────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn econ_causal_preflight(config: Value) -> Result<Value, String> {
    info!("econ_causal_preflight");
    post_json("/compute/causal/preflight", &config, quick_client()).await
}

#[tauri::command]
pub async fn econ_causal_list(project_dir: String) -> Result<Value, String> {
    info!("econ_causal_list: {project_dir}");
    let body = serde_json::json!({ "project_dir": project_dir });
    post_json("/compute/causal/list", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_causal_consistency(project_dir: String) -> Result<Value, String> {
    info!("econ_causal_consistency: {project_dir}");
    let body = serde_json::json!({ "project_dir": project_dir });
    post_json("/compute/causal/consistency", &body, quick_client()).await
}

#[tauri::command]
pub async fn econ_causal_did(config: Value) -> Result<Value, String> {
    info!("econ_causal_did");
    post_json("/compute/causal/did", &config, quick_client()).await
}

#[tauri::command]
pub async fn econ_causal_scm(config: Value) -> Result<Value, String> {
    info!("econ_causal_scm");
    post_json("/compute/causal/scm", &config, quick_client()).await
}

#[tauri::command]
pub async fn econ_causal_forest(config: Value) -> Result<Value, String> {
    info!("econ_causal_forest");
    post_json("/compute/causal/forest", &config, quick_client()).await
}

// ── Helper ───────────────────────────────────────────

/// POST with auto-recovery:
/// - connect/timeout errors → trigger sidecar respawn + retry once
/// - HTTP 409 (session mismatch) → re-handshake + retry once (foreign sidecar detected)
/// - 4xx/5xx с JSON body → pass through untouched (app errors, not sidecar issues)
async fn post_json(path: &str, body: &Value, client: &reqwest::Client) -> Result<Value, String> {
    let send_once = |c: &reqwest::Client, url: String| {
        let req = with_session(c.post(url).json(body));
        async move { req.send().await }
    };

    let resp = match send_once(client, econ_url(path)).await {
        Ok(r) => r,
        Err(e) if e.is_connect() || e.is_timeout() => {
            warn!("Sidecar unreachable on {path} ({e}) - attempting auto-respawn");
            if !econ_sidecar::ensure_alive().await {
                return Err(format!(
                    "Вычислительный модуль недоступен и не удалось автоматически перезапустить. \
                     Попробуй нажать «Перезапустить модуль» или проверь логи sidecar: {e}"
                ));
            }
            send_once(client, econ_url(path)).await.map_err(|e2| {
                warn!("Retry after respawn failed on {path}: {e2}");
                format!("Модуль перезапущен, но запрос всё ещё не проходит: {e2}")
            })?
        }
        Err(e) => {
            warn!("Econometrica sidecar request failed: {e}");
            return Err(format!("Ошибка запроса к модулю: {e}"));
        }
    };

    // v1.0.9: 409 Conflict → session mismatch → re-handshake + retry once
    if resp.status() == reqwest::StatusCode::CONFLICT {
        warn!(
            "Sidecar {path} returned 409 (session mismatch) - \
             re-handshake and retry"
        );
        // ensure_alive делает /health verify_handshake + respawn если чужой
        if !econ_sidecar::ensure_alive().await {
            return Err("Session mismatch: модуль не удалось переинициализировать".to_string());
        }
        let resp2 = send_once(client, econ_url(path)).await.map_err(|e| {
            warn!("Retry after 409 failed on {path}: {e}");
            format!("Запрос не прошёл после re-handshake: {e}")
        })?;
        return parse_resp(resp2, path).await;
    }

    parse_resp(resp, path).await
}

// ─── v1.3.0 endpoints (per ADR-014, ADR-015, ADR-016) ─────────────────────

#[tauri::command]
pub async fn econ_safe_corridor(
    project_dir: String,
    relative_lo_factor: Option<f64>,
    relative_hi_factor: Option<f64>,
) -> Result<Value, String> {
    info!("econ_safe_corridor: {project_dir}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "relative_lo_factor": relative_lo_factor.unwrap_or(0.5),
        "relative_hi_factor": relative_hi_factor.unwrap_or(1.5),
    });
    post_json("/optimize/corridor", &body, quick_client()).await
}

/// A3/OPP-05 (2026-07-03): preflight-проверка данных ДО запуска обучения.
/// Endpoint /compute/preflight существовал с S1-аудита (engine recommend +
/// quick_proxy + prior_predictive → overall_tier), но не имел Rust-команды и
/// UI — «вычисленная, но не доставленная честность» (мат-аудит F-13 закрыл
/// in-train страховку; этот гейт показывает предупреждение ДО кнопки).
/// prior_predictive 300 samples ≈ 5-15 c → train_client.
#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn econ_preflight(
    project_dir: String,
    file_path: String,
    media_columns: Vec<String>,
    control_columns: Option<Vec<String>>,
    kpi_column: String,
    date_column: Option<String>,
    adstock_config: Option<Value>,
    mode_override: Option<String>,
    skip_prior_predictive: Option<bool>,
) -> Result<Value, String> {
    info!("econ_preflight: project_dir={project_dir}, channels={}", media_columns.len());
    let body = serde_json::json!({
        "project_dir": project_dir,
        "file_path": file_path,
        "media_columns": media_columns,
        "control_columns": control_columns.unwrap_or_default(),
        "kpi_column": kpi_column,
        "date_column": date_column.unwrap_or_else(|| "date".to_string()),
        "adstock_config": adstock_config.unwrap_or_else(|| serde_json::json!({})),
        "mode_override": mode_override,
        "skip_prior_predictive": skip_prior_predictive.unwrap_or(false),
    });
    post_json("/compute/preflight", &body, train_client()).await
}

#[tauri::command]
pub async fn econ_optimize_inverse(
    project_dir: String,
    target_sales: f64,
    kpi_kind: Option<String>,
    mode: Option<String>,
    max_budget: Option<f64>,
    min_budget: Option<f64>,
    // OPP-02 (2026-07-03): «бюджет под вероятность» — None = медианный режим
    // (back-compat), Some(0.8) = квантильная бисекция P(hit) >= 80%.
    confidence: Option<f64>,
) -> Result<Value, String> {
    info!("econ_optimize_inverse: project_dir={project_dir}, target={target_sales}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "target_sales": target_sales,
        "kpi_kind": kpi_kind.unwrap_or_else(|| "monetary".to_string()),
        "mode": mode.unwrap_or_else(|| "roi".to_string()),
        "max_budget": max_budget,
        "min_budget": min_budget,
        "confidence": confidence,
    });
    // Inverse + bisection может занимать до 10s - use train_client с longer timeout.
    post_json("/optimize/inverse", &body, train_client()).await
}

#[tauri::command]
pub async fn econ_auto_detect_price(
    project_dir: String,
    monetary_column: String,
    count_column: String,
    cv_warn_threshold: Option<f64>,
) -> Result<Value, String> {
    info!("econ_auto_detect_price: {project_dir} {monetary_column}/{count_column}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "monetary_column": monetary_column,
        "count_column": count_column,
        "cv_warn_threshold": cv_warn_threshold.unwrap_or(0.20),
    });
    post_json("/project/auto_price", &body, quick_client()).await
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn econ_save_kpi_settings(
    project_dir: String,
    value_per_count_unit: Option<f64>,
    value_per_count_unit_label: Option<String>,
    value_per_count_unit_source: Option<String>,
    per_channel_input: Option<Value>,
    kpi_kind: Option<String>,
    // H-16 (audit): Phase 1.3 stores не персистировались — frontend сетит
    // unitCostInputMode + budgetInputs + unitCosts + unitCostInflation, но
    // econ_save_kpi_settings командой эти fields передавать не позволяла.
    // Reload → стэйт терялся.
    unit_costs: Option<Value>,
    unit_cost_inflation: Option<Value>,
    mode_for: Option<Value>,
    budget_inputs: Option<Value>,
) -> Result<Value, String> {
    info!("econ_save_kpi_settings: {project_dir}");
    let body = serde_json::json!({
        "project_dir": project_dir,
        "value_per_count_unit": value_per_count_unit,
        "value_per_count_unit_label": value_per_count_unit_label.unwrap_or_default(),
        "value_per_count_unit_source": value_per_count_unit_source,
        "per_channel_input": per_channel_input,
        "kpi_kind": kpi_kind.unwrap_or_else(|| "monetary".to_string()),
        // H-16: Phase 1.3 persistence — pass through new fields.
        "unit_costs": unit_costs,
        "unit_cost_inflation": unit_cost_inflation,
        "mode_for": mode_for,
        "budget_inputs": budget_inputs,
    });
    post_json("/project/save_kpi_settings", &body, quick_client()).await
}

async fn parse_resp(resp: reqwest::Response, path: &str) -> Result<Value, String> {
    let status = resp.status();
    let text = resp.text().await.map_err(|e| format!("Не удалось прочитать ответ: {e}"))?;
    match serde_json::from_str::<Value>(&text) {
        Ok(v) => {
            if !status.is_success() {
                warn!("Sidecar {path} returned {status}: {}", &text[..text.len().min(500)]);
                let msg = v
                    .get("message")
                    .and_then(|m| m.as_str())
                    .unwrap_or("неизвестная ошибка");
                return Err(format!("Ошибка sidecar ({status}): {msg}"));
            }
            Ok(v)
        }
        Err(e) => {
            warn!("Sidecar {path} non-JSON {status}: {}", &text[..text.len().min(500)]);
            Err(format!(
                "Ошибка парсинга ответа ({status}): {e}. Тело: {}",
                &text[..text.len().min(200)]
            ))
        }
    }
}

#[cfg(test)]
mod resolve_project_dir_tests {
    use super::resolve_project_dir_arg;

    #[test]
    fn none_stays_none() {
        assert_eq!(resolve_project_dir_arg(None).unwrap(), None);
    }

    #[test]
    fn empty_becomes_none() {
        assert_eq!(resolve_project_dir_arg(Some("".into())).unwrap(), None);
        assert_eq!(resolve_project_dir_arg(Some("   ".into())).unwrap(), None);
    }

    #[test]
    fn absolute_path_passthrough_backward_compat() {
        // .aurora импорт / старый код шлёт уже абсолютный путь — не трогаем.
        #[cfg(windows)]
        let abs = r"C:\Users\x\AppData\Roaming\app\projects\proj-1";
        #[cfg(not(windows))]
        let abs = "/home/x/.local/share/app/projects/proj-1";
        assert_eq!(
            resolve_project_dir_arg(Some(abs.into())).unwrap(),
            Some(abs.to_string())
        );
    }

    #[test]
    fn traversal_blocked() {
        let err = resolve_project_dir_arg(Some("../../etc/passwd".into())).unwrap_err();
        assert!(err.contains("traversal"), "ожидали traversal guard, got: {err}");
    }

    #[test]
    fn bare_id_resolves_to_absolute_ending_with_id() {
        // bare project_id → абсолютный путь, оканчивающийся на id (как econ_export_pptx).
        let id = "кагоцел-load1-test-проект";
        let resolved = resolve_project_dir_arg(Some(id.into())).unwrap().unwrap();
        let path = std::path::Path::new(&resolved);
        assert!(path.is_absolute(), "ожидали абсолютный путь, got: {resolved}");
        assert_eq!(
            path.file_name().and_then(|s| s.to_str()),
            Some(id),
            "путь должен оканчиваться на project_id"
        );
        assert!(path.to_string_lossy().contains("projects"));
    }
}
