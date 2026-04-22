//! Econometrica report generation commands.
//!
//! econ_generate_report — Markdown report from MMM pipeline data.
//! econ_export_xlsx     — Multi-sheet XLSX export.
//! econ_open_exports    — Open project exports folder in OS file manager.

use chrono::Local;
use log::info;
use rust_xlsxwriter::{Format, Workbook};
use serde_json::Value;
use std::path::PathBuf;

// ── Helpers ──────────────────────────────────────────────────────────────────

/// Pull a fit metric out of `model.diagnostics`.
/// Backend nests them under `diagnostics.metrics.*` (with `mape_pct`),
/// older payloads kept them flat under `diagnostics.*`.
fn diag_metric(model: &Value, nested_key: &str, flat_key: &str) -> f64 {
    model["diagnostics"]["metrics"][nested_key]
        .as_f64()
        .or_else(|| model["diagnostics"][flat_key].as_f64())
        .unwrap_or(0.0)
}

/// Pull the model spec from diagnostics; if backend didn't supply one (old
/// trained models), fall back to the canonical Bayesian MMM spec hardcoded
/// here. Keep priors in sync with sidecar `utils/model_spec.py`.
fn model_spec_value(model: &Value) -> Value {
    let spec = &model["diagnostics"]["model_spec"];
    if spec.is_object() {
        return spec.clone();
    }
    serde_json::json!({
        "title": "Спецификация модели",
        "subtitle": "Байесовская Media Mix Model с Adstock и Hill saturation",
        "engine": "PyMC + NumPyro (JAX) NUTS",
        "formula": "Sales_t = β₀ + Σᵢ βᵢ · Hill(Adstock(Media_i,t), αᵢ, γᵢ) + Σⱼ γⱼ · Control_j,t + ε_t",
        "transformations": [
            {"name": "Hill (saturation)", "formula": "Hill(x, α, γ) = x^α / (x^α + γ^α)"},
            {"name": "Adstock (geometric)", "formula": "x'_t = x_t + λ · x'_{t-1}"},
            {"name": "Adstock (Weibull)", "formula": "x'_t = Σ θ₁^((k-1)^θ₂) · x_{t-k}"},
        ],
        "priors": [
            {"symbol": "β₀", "name": "intercept (базовые продажи)", "distribution": "Normal(0, 0.5)"},
            {"symbol": "βᵢ", "name": "media coefficients", "distribution": "HalfNormal(0.3)"},
            {"symbol": "αᵢ", "name": "Hill steepness", "distribution": "Gamma(5, 3)"},
            {"symbol": "γᵢ", "name": "Hill half-saturation", "distribution": "Beta(3, 3)"},
            {"symbol": "γⱼ", "name": "control coefficients", "distribution": "Normal(0, 0.3)"},
            {"symbol": "σ", "name": "noise (residual std)", "distribution": "HalfNormal(0.3)"},
        ],
        "inference": {
            "method": "NUTS (No-U-Turn Sampler) через NumPyro/JAX",
            "default_chains": 2, "default_draws": 500, "default_tune": 500,
        },
        "normalization": "Media и control нормализованы (X / max(X)); y нормализован к std=1.",
    })
}

/// Render the model spec block as a Markdown section.
fn render_spec_md(spec: &Value) -> String {
    let mut s = String::with_capacity(1024);
    let title = spec["title"].as_str().unwrap_or("Спецификация модели");
    let subtitle = spec["subtitle"].as_str().unwrap_or("");
    let engine = spec["engine"].as_str().unwrap_or("");
    let formula = spec["formula"].as_str().unwrap_or("");
    let normalization = spec["normalization"].as_str().unwrap_or("");

    s.push_str(&format!("## {title}\n\n"));
    if !subtitle.is_empty() {
        s.push_str(&format!("*{subtitle}*  \n"));
    }
    if !engine.is_empty() {
        s.push_str(&format!("**Движок инференса:** {engine}\n\n"));
    }

    s.push_str("### Формула\n\n");
    s.push_str("```\n");
    s.push_str(formula);
    s.push_str("\n```\n\n");

    if let Some(trs) = spec["transformations"].as_array() {
        s.push_str("### Трансформации\n\n");
        s.push_str("| Преобразование | Формула | Назначение |\n");
        s.push_str("|----------------|---------|------------|\n");
        for tr in trs {
            let name = tr["name"].as_str().unwrap_or("");
            let f = tr["formula"].as_str().unwrap_or("");
            let n = tr["note"].as_str().unwrap_or("");
            s.push_str(&format!("| {name} | `{f}` | {n} |\n"));
        }
        s.push('\n');
    }

    if let Some(priors) = spec["priors"].as_array() {
        s.push_str("### Priors (априорные распределения)\n\n");
        s.push_str("| Параметр | Имя | Распределение | Комментарий |\n");
        s.push_str("|----------|-----|---------------|-------------|\n");
        for p in priors {
            let sym = p["symbol"].as_str().unwrap_or("");
            let name = p["name"].as_str().unwrap_or("");
            let dist = p["distribution"].as_str().unwrap_or("");
            let note = p["note"].as_str().unwrap_or("");
            s.push_str(&format!("| {sym} | {name} | `{dist}` | {note} |\n"));
        }
        s.push('\n');
    }

    let inf = &spec["inference"];
    if inf.is_object() {
        let method = inf["method"].as_str().unwrap_or("");
        let chains = inf["default_chains"].as_u64().unwrap_or(0);
        let draws = inf["default_draws"].as_u64().unwrap_or(0);
        let tune = inf["default_tune"].as_u64().unwrap_or(0);
        let note = inf["note"].as_str().unwrap_or("");
        s.push_str("### Инференс\n\n");
        s.push_str(&format!("- **Метод:** {method}\n"));
        if chains > 0 {
            s.push_str(&format!("- **Цепочки/draws/tune:** {chains}/{draws}/{tune}\n"));
        }
        if !note.is_empty() {
            s.push_str(&format!("- {note}\n"));
        }
        s.push('\n');
    }

    if !normalization.is_empty() {
        s.push_str(&format!("> {normalization}\n\n"));
    }

    s.push_str("---\n\n");
    s
}

fn exports_dir(project_id: &str) -> Result<PathBuf, String> {
    // Использует customizable projects_dir() из project.rs — учитывает user-config
    // и env AURORA_PROJECTS_ROOT. Единый источник правды для путей.
    let dir = crate::commands::project::project_dir(project_id)?.join("exports");
    std::fs::create_dir_all(&dir).map_err(|e| format!("Failed to create exports dir: {e}"))?;
    Ok(dir)
}

/// Прочитать все scenario JSON из project_dir/results/scenarios/.
/// Используется build_xlsx для листа «Сценарии». Порядок — по имени файла (стабильный).
fn read_scenarios(project_id: &str) -> Vec<Value> {
    let project_dir = match crate::commands::project::project_dir(project_id) {
        Ok(d) => d,
        Err(_) => return vec![],
    };
    let scenarios_dir = project_dir.join("results").join("scenarios");
    if !scenarios_dir.exists() {
        return vec![];
    }
    let entries = match std::fs::read_dir(&scenarios_dir) {
        Ok(e) => e,
        Err(_) => return vec![],
    };
    let mut files: Vec<PathBuf> = entries
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().and_then(|s| s.to_str()) == Some("json"))
        .collect();
    files.sort();
    files
        .iter()
        .filter_map(|p| std::fs::read_to_string(p).ok())
        .filter_map(|s| serde_json::from_str::<Value>(&s).ok())
        .collect()
}

// ── Markdown report ──────────────────────────────────────────────────────────

/// Build a full Markdown report from MMM pipeline data.
fn build_markdown(model: &Value, decompose: &Value, optimize: &Value) -> String {
    let mqs        = model["diagnostics"]["mqs"]["score"].as_f64().unwrap_or(0.0);
    let mqs_label  = model["diagnostics"]["mqs"]["tier_label"].as_str().unwrap_or("N/A");
    let r_squared  = diag_metric(model, "r_squared", "r_squared");
    let mape       = diag_metric(model, "mape_pct", "mape");
    let r_hat      = model["diagnostics"]["metrics"]["r_hat_max"]
        .as_f64()
        .or_else(|| model["diagnostics"]["r_hat"].as_f64());
    let lift       = optimize["expected_lift_pct"].as_f64().unwrap_or(0.0);
    let budget     = optimize["total_budget"].as_f64().unwrap_or(0.0);

    // Top ROI channel (by decompose channels)
    let top_ch = decompose["channels"].as_array()
        .and_then(|chs| {
            chs.iter()
                .max_by(|a, b| {
                    let ra = a["roi"].as_f64().unwrap_or(0.0);
                    let rb = b["roi"].as_f64().unwrap_or(0.0);
                    ra.partial_cmp(&rb).unwrap_or(std::cmp::Ordering::Equal)
                })
                .and_then(|c| c["name"].as_str())
        })
        .unwrap_or("N/A");

    let now = Local::now().format("%d.%m.%Y %H:%M").to_string();
    let mut md = String::with_capacity(4096);

    // ── Title ────────────────────────────────────────────────
    md.push_str("# Marketing Mix Model — Аналитический отчёт\n\n");
    md.push_str(&format!("*Сгенерировано: {now}*\n\n---\n\n"));

    // ── Executive Summary ────────────────────────────────────
    md.push_str("## EXECUTIVE SUMMARY\n\n");
    md.push_str(&format!("- **Качество модели (MQS):** {mqs:.1} — {mqs_label}\n"));
    md.push_str(&format!("- **R²:** {r_squared:.4} (объяснённая дисперсия: {:.1}%)\n", r_squared * 100.0));
    md.push_str(&format!("- **MAPE:** {mape:.2}%\n"));
    md.push_str(&format!("- **Ожидаемый прирост от оптимизации:** {:+.1}%\n", lift));
    md.push_str(&format!("- **Лучший канал по ROI:** {top_ch}\n"));
    if budget > 0.0 {
        md.push_str(&format!("- **Оптимизированный бюджет:** {budget:.0} руб.\n"));
    }
    md.push_str("\n---\n\n");

    // ── Model Quality ────────────────────────────────────────
    md.push_str("## Качество модели\n\n");
    md.push_str("| Метрика | Значение |\n");
    md.push_str("|---------|----------|\n");
    md.push_str(&format!("| MQS Score | {mqs:.1} |\n"));
    md.push_str(&format!("| MQS Tier | {mqs_label} |\n"));
    md.push_str(&format!("| R² | {r_squared:.4} |\n"));
    md.push_str(&format!("| MAPE | {mape:.2}% |\n"));
    if let Some(rh) = r_hat {
        md.push_str(&format!("| R-hat (сходимость MCMC) | {rh:.3} |\n"));
    }
    md.push_str("\n---\n\n");

    // ── Спецификация модели (formula + priors) ───────────────
    let spec = model_spec_value(model);
    md.push_str(&render_spec_md(&spec));

    // ── Decompose insight ────────────────────────────────────
    if let Some(insight) = decompose["insight"].as_str() {
        md.push_str("## БЛОК: Декомпозиция продаж\n\n");
        md.push_str(insight);
        md.push_str("\n\n");
    }

    if let Some(wf) = decompose["waterfall"].as_array() {
        md.push_str("### Вклады в продажи (Waterfall)\n\n");
        md.push_str("| Категория | Вклад | % |\n");
        md.push_str("|-----------|------:|--:|\n");
        for item in wf {
            let cat = item["category"].as_str().unwrap_or("—");
            let val = item["value"].as_f64().unwrap_or(0.0);
            let pct = item["contribution_pct"].as_f64().unwrap_or(0.0);
            md.push_str(&format!("| {cat} | {val:.0} | {pct:.1}% |\n"));
        }
        md.push('\n');
    }

    // ── Channel ROI ──────────────────────────────────────────
    if let Some(chs) = decompose["channels"].as_array() {
        md.push_str("## БЛОК: Инвестиции. ROI по каналам\n\n");
        md.push_str("| Канал | Расход | Вклад | ROI | Вердикт |\n");
        md.push_str("|-------|-------:|------:|----:|---------|\n");
        for ch in chs {
            let name   = ch["name"].as_str().unwrap_or("—");
            let spend  = ch["spend"].as_f64().unwrap_or(0.0);
            let contrib = ch["contribution"].as_f64().unwrap_or(0.0);
            let roi    = ch["roi"].as_f64().unwrap_or(0.0);
            let verdict = ch["verdict"].as_str().unwrap_or("—");
            md.push_str(&format!("| {name} | {spend:.0} | {contrib:.0} | {roi:.2}x | {verdict} |\n"));
        }
        md.push('\n');

        // ROI CI from model
        if let Some(params) = model["channelParams"].as_object() {
            md.push_str("### ROI с доверительными интервалами (95%)\n\n");
            md.push_str("| Канал | ROI | CI нижний | CI верхний |\n");
            md.push_str("|-------|----:|----------:|-----------:|\n");
            for (ch_name, p) in params {
                let roi    = p["roi"].as_f64().unwrap_or(0.0);
                let ci_lo  = p["roi_ci_lower"].as_f64().unwrap_or(0.0);
                let ci_hi  = p["roi_ci_upper"].as_f64().unwrap_or(0.0);
                md.push_str(&format!("| {ch_name} | {roi:.2}x | {ci_lo:.2}x | {ci_hi:.2}x |\n"));
            }
            md.push('\n');
        }
    }
    md.push_str("---\n\n");

    // ── Optimization ─────────────────────────────────────────
    if let Some(insight) = optimize["insight"].as_str() {
        md.push_str("## БЛОК: Оптимизация бюджета\n\n");
        md.push_str(insight);
        md.push_str("\n\n");
    }

    if let Some(opt_chs) = optimize["channels"].as_array() {
        md.push_str("### Текущее vs Оптимальное распределение\n\n");
        md.push_str("| Канал | Текущий | Оптимальный | Δ | Δ% |\n");
        md.push_str("|-------|--------:|------------:|--:|---:|\n");
        for ch in opt_chs {
            let name  = ch["name"].as_str().unwrap_or("—");
            let curr  = ch["current_spend"].as_f64().unwrap_or(0.0);
            let opt   = ch["optimal_spend"].as_f64().unwrap_or(0.0);
            let delta = opt - curr;
            let dpct  = if curr > 0.0 { delta / curr * 100.0 } else { 0.0 };
            let sign  = if delta >= 0.0 { "+" } else { "" };
            md.push_str(&format!("| {name} | {curr:.0} | {opt:.0} | {sign}{delta:.0} | {sign}{dpct:.1}% |\n"));
        }
        md.push('\n');
    }
    md.push_str("---\n\n");

    // ── Recommendations ──────────────────────────────────────
    md.push_str("## РЕКОМЕНДАЦИИ\n\n");
    if lift > 5.0 {
        md.push_str(&format!("- [ВЫСОКАЯ] Перераспределить бюджет согласно оптимальному плану — ожидаемый прирост **{lift:+.1}%**\n"));
    } else if lift > 0.0 {
        md.push_str(&format!("- [СРЕДНЯЯ] Рассмотреть корректировку бюджетного распределения — ожидаемый прирост {lift:+.1}%\n"));
    }
    if r_squared < 0.7 {
        md.push_str("- [СРЕДНЯЯ] R² ниже рекомендуемого порога 0.7 — рассмотреть добавление контрольных переменных\n");
    }
    if mqs < 60.0 {
        md.push_str("- [СРЕДНЯЯ] MQS Score ниже 60 — модель требует доработки или дополнительных данных\n");
    }
    if mqs >= 80.0 {
        md.push_str("- [ВЫСОКАЯ] Высокий MQS Score — результаты модели надёжны для принятия решений\n");
    }
    md.push_str(&format!("- [ВЫСОКАЯ] Приоритизировать канал **{top_ch}** — наивысший ROI в миксе\n"));
    md.push('\n');

    md
}

/// Extract Executive Summary block from markdown report.
fn extract_summary(report: &str) -> String {
    let start = match report.find("## EXECUTIVE SUMMARY") {
        Some(s) => s,
        None => return String::new(),
    };
    // Find next ## section after summary
    let tail = &report[start..];
    let end = tail[1..].find("\n---").map(|i| i + 1).unwrap_or(tail.len());
    tail[..end].chars().take(1000).collect()
}

// ── Tauri commands ────────────────────────────────────────────────────────────

/// Generate a Markdown MMM report and save it to the project's exports directory.
#[tauri::command]
pub async fn econ_generate_report(
    project_id: String,
    model_data: Value,
    decompose_data: Value,
    optimize_data: Value,
) -> Result<Value, String> {
    info!("econ_generate_report: project={project_id}");

    let exports = exports_dir(&project_id)?;
    let ts = Local::now().format("%Y%m%d_%H%M%S");
    let filename = format!("mmm_report_{ts}.md");
    let path = exports.join(&filename);

    let report = build_markdown(&model_data, &decompose_data, &optimize_data);
    let summary = extract_summary(&report);

    std::fs::write(&path, &report)
        .map_err(|e| format!("Ошибка записи отчёта: {e}"))?;

    info!("Report saved: {}", path.display());
    Ok(serde_json::json!({
        "status": "ok",
        "path": path.to_string_lossy(),
        "summary": summary,
    }))
}

/// Export MMM results to a multi-sheet XLSX file.
#[tauri::command]
pub async fn econ_export_xlsx(
    project_id: String,
    model_data: Value,
    decompose_data: Value,
    optimize_data: Value,
) -> Result<Value, String> {
    info!("econ_export_xlsx: project={project_id}");

    let exports = exports_dir(&project_id)?;
    let ts = Local::now().format("%Y%m%d_%H%M%S");
    let filename = format!("mmm_report_{ts}.xlsx");
    let path = exports.join(&filename);

    // Сценарии — опциональные. Если папки нет / JSON невалиден — пустой vec,
    // лист «Сценарии» просто не добавится.
    let scenarios = read_scenarios(&project_id);

    build_xlsx(&model_data, &decompose_data, &optimize_data, &scenarios, &path)?;

    info!("XLSX saved: {}", path.display());
    Ok(serde_json::json!({
        "status": "ok",
        "path": path.to_string_lossy(),
    }))
}

/// Open the project's exports folder in the OS file manager.
#[tauri::command]
pub async fn econ_open_exports(project_id: String) -> Result<(), String> {
    let exports = exports_dir(&project_id)?;
    if !exports.exists() {
        return Err("Папка экспортов не найдена".to_string());
    }

    #[cfg(windows)]
    {
        std::process::Command::new("explorer")
            .arg(exports.to_str().unwrap_or("."))
            .spawn()
            .map_err(|e| format!("Не удалось открыть папку: {e}"))?;
    }
    #[cfg(not(windows))]
    {
        std::process::Command::new("xdg-open")
            .arg(exports.to_str().unwrap_or("."))
            .spawn()
            .map_err(|e| format!("Не удалось открыть папку: {e}"))?;
    }

    Ok(())
}

// ── XLSX builder ──────────────────────────────────────────────────────────────

fn build_xlsx(model: &Value, decompose: &Value, optimize: &Value, scenarios: &[Value], path: &PathBuf) -> Result<(), String> {
    use rust_xlsxwriter::{Chart, ChartType, Color, ConditionalFormatCell, ConditionalFormatCellRule, Formula};

    let mut wb = Workbook::new();
    let bold = Format::new().set_bold();
    let header_fmt = Format::new()
        .set_bold()
        .set_background_color(Color::RGB(0x1E212C))
        .set_font_color(Color::RGB(0x94A3B8))
        .set_border_bottom(rust_xlsxwriter::FormatBorder::Thin);
    let pct_fmt = Format::new().set_num_format("0.0%");
    let num_fmt = Format::new().set_num_format("#,##0");
    let roi_fmt = Format::new().set_num_format("0.00\"x\"");

    // ── Sheet 1: Executive Summary ──────────────────────────
    {
        let ws = wb.add_worksheet();
        ws.set_name("Executive Summary").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(0x3B82F6));

        let mqs       = model["diagnostics"]["mqs"]["score"].as_f64().unwrap_or(0.0);
        let mqs_label = model["diagnostics"]["mqs"]["tier_label"].as_str().unwrap_or("N/A");
        let r_sq      = diag_metric(model, "r_squared", "r_squared");
        let mape      = diag_metric(model, "mape_pct", "mape");
        let r_hat     = model["diagnostics"]["metrics"]["r_hat_max"]
            .as_f64()
            .or_else(|| model["diagnostics"]["r_hat"].as_f64());
        let lift      = optimize["expected_lift_pct"].as_f64().unwrap_or(0.0);
        let budget    = optimize["total_budget"].as_f64().unwrap_or(0.0);

        ws.write_with_format(0, 0, "Marketing Mix Model — Аналитический отчёт", &bold).map_err(|e| format!("{e}"))?;
        ws.write(1, 0, &format!("Дата: {}", chrono::Local::now().format("%d.%m.%Y"))).map_err(|e| format!("{e}"))?;

        ws.write_with_format(3, 0, "Метрика", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(3, 1, "Значение", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(3, 2, "Оценка", &header_fmt).map_err(|e| format!("{e}"))?;

        let metrics: Vec<(&str, f64, &str)> = vec![
            ("MQS Score", mqs, if mqs >= 80.0 { "Отлично" } else if mqs >= 60.0 { "Хорошо" } else { "Требует доработки" }),
            ("R²", r_sq, if r_sq >= 0.8 { "Отлично" } else if r_sq >= 0.6 { "Хорошо" } else { "Слабо" }),
            ("MAPE (%)", mape, if mape <= 10.0 { "Отлично" } else if mape <= 20.0 { "Приемлемо" } else { "Высокая ошибка" }),
            ("Прирост от оптимизации (%)", lift, if lift > 10.0 { "Значительный" } else if lift > 3.0 { "Умеренный" } else { "Минимальный" }),
            ("Общий бюджет", budget, ""),
        ];
        for (i, (label, val, grade)) in metrics.iter().enumerate() {
            let row = (i + 4) as u32;
            ws.write(row, 0, *label).map_err(|e| format!("{e}"))?;
            ws.write(row, 1, *val).map_err(|e| format!("{e}"))?;
            ws.write(row, 2, *grade).map_err(|e| format!("{e}"))?;
        }
        ws.write(9, 0, &format!("MQS Tier: {mqs_label}")).map_err(|e| format!("{e}"))?;
        if let Some(rh) = r_hat {
            ws.write(10, 0, &format!("R-hat (сходимость): {rh:.4}")).map_err(|e| format!("{e}"))?;
        }

        ws.set_column_width(0, 30).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 18).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 20).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 1.5: Спецификация модели ──────────────────────
    {
        let ws = wb.add_worksheet();
        ws.set_name("Спецификация").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(0x8B5CF6));

        let spec = model_spec_value(model);
        let title = spec["title"].as_str().unwrap_or("Спецификация модели");
        let subtitle = spec["subtitle"].as_str().unwrap_or("");
        let engine = spec["engine"].as_str().unwrap_or("");
        let formula = spec["formula"].as_str().unwrap_or("");
        let normalization = spec["normalization"].as_str().unwrap_or("");

        ws.write_with_format(0, 0, title, &bold).map_err(|e| format!("{e}"))?;
        ws.write(1, 0, subtitle).map_err(|e| format!("{e}"))?;
        if !engine.is_empty() {
            ws.write(2, 0, &format!("Движок: {engine}")).map_err(|e| format!("{e}"))?;
        }

        ws.write_with_format(4, 0, "Формула", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write(5, 0, formula).map_err(|e| format!("{e}"))?;

        // Transformations block
        let mut row: u32 = 7;
        ws.write_with_format(row, 0, "Преобразование", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(row, 1, "Формула", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(row, 2, "Назначение", &header_fmt).map_err(|e| format!("{e}"))?;
        row += 1;
        if let Some(trs) = spec["transformations"].as_array() {
            for tr in trs {
                ws.write(row, 0, tr["name"].as_str().unwrap_or("")).map_err(|e| format!("{e}"))?;
                ws.write(row, 1, tr["formula"].as_str().unwrap_or("")).map_err(|e| format!("{e}"))?;
                ws.write(row, 2, tr["note"].as_str().unwrap_or("")).map_err(|e| format!("{e}"))?;
                row += 1;
            }
        }

        // Priors table
        row += 1;
        ws.write_with_format(row, 0, "Параметр", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(row, 1, "Имя", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(row, 2, "Распределение", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(row, 3, "Комментарий", &header_fmt).map_err(|e| format!("{e}"))?;
        row += 1;
        if let Some(priors) = spec["priors"].as_array() {
            for p in priors {
                ws.write(row, 0, p["symbol"].as_str().unwrap_or("")).map_err(|e| format!("{e}"))?;
                ws.write(row, 1, p["name"].as_str().unwrap_or("")).map_err(|e| format!("{e}"))?;
                ws.write(row, 2, p["distribution"].as_str().unwrap_or("")).map_err(|e| format!("{e}"))?;
                ws.write(row, 3, p["note"].as_str().unwrap_or("")).map_err(|e| format!("{e}"))?;
                row += 1;
            }
        }

        // Inference
        let inf = &spec["inference"];
        if inf.is_object() {
            row += 1;
            ws.write_with_format(row, 0, "Инференс", &header_fmt).map_err(|e| format!("{e}"))?;
            row += 1;
            if let Some(m) = inf["method"].as_str() {
                ws.write(row, 0, "Метод").map_err(|e| format!("{e}"))?;
                ws.write(row, 1, m).map_err(|e| format!("{e}"))?;
                row += 1;
            }
            let chains = inf["default_chains"].as_u64().unwrap_or(0);
            let draws  = inf["default_draws"].as_u64().unwrap_or(0);
            let tune   = inf["default_tune"].as_u64().unwrap_or(0);
            if chains > 0 {
                ws.write(row, 0, "Chains / draws / tune").map_err(|e| format!("{e}"))?;
                ws.write(row, 1, &format!("{chains} / {draws} / {tune}")).map_err(|e| format!("{e}"))?;
                row += 1;
            }
            if let Some(note) = inf["note"].as_str() {
                ws.write(row, 0, note).map_err(|e| format!("{e}"))?;
                row += 1;
            }
        }

        if !normalization.is_empty() {
            row += 1;
            ws.write(row, 0, normalization).map_err(|e| format!("{e}"))?;
        }

        ws.set_column_width(0, 18).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 32).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 30).map_err(|e| format!("{e}"))?;
        ws.set_column_width(3, 55).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 2: Декомпозиция + waterfall chart ─────────────
    if let Some(wf) = decompose["waterfall"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("Декомпозиция").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(0x22C55E));

        ws.write_with_format(0, 0, "Категория", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(0, 1, "Вклад", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(0, 2, "% от общего", &header_fmt).map_err(|e| format!("{e}"))?;

        for (i, item) in wf.iter().enumerate() {
            let row = (i + 1) as u32;
            let cat = item["category"].as_str().unwrap_or("—");
            let val = item["value"].as_f64().unwrap_or(0.0);
            ws.write(row, 0, cat).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, val, &num_fmt).map_err(|e| format!("{e}"))?;
            // Formula: contribution / total
            let total_row = wf.len() as u32 + 2;
            ws.write_formula(row, 2, Formula::new(format!("=B{}/B${}", row + 1, total_row))).map_err(|e| format!("{e}"))?;
        }
        // Total row
        let total_row = wf.len() as u32 + 1;
        ws.write_with_format(total_row, 0, "ИТОГО", &bold).map_err(|e| format!("{e}"))?;
        ws.write_formula_with_format(total_row, 1, Formula::new(format!("=SUM(B2:B{})", total_row)), &bold).map_err(|e| format!("{e}"))?;

        // Bar chart
        let mut chart = Chart::new(ChartType::Bar);
        chart.add_series()
            .set_categories(("Декомпозиция", 1, 0, wf.len() as u32, 0))
            .set_values(("Декомпозиция", 1, 1, wf.len() as u32, 1))
            .set_name("Вклад в продажи");
        chart.set_width(600).set_height(350);
        chart.title().set_name("Декомпозиция продаж");
        ws.insert_chart(total_row + 2, 0, &chart).map_err(|e| format!("{e}"))?;

        ws.set_column_width(0, 25).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 16).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 14).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 3: ROI каналов + chart + conditional formatting ─
    if let Some(chs) = decompose["channels"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("ROI каналов").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(0xF59E0B));

        let headers = ["Канал", "Расход", "Вклад", "ROI", "CI нижний", "CI верхний", "Вердикт"];
        for (c, h) in headers.iter().enumerate() {
            ws.write_with_format(0, c as u16, *h, &header_fmt).map_err(|e| format!("{e}"))?;
        }

        let ch_params = model["channelParams"].as_object();

        for (i, ch) in chs.iter().enumerate() {
            let row = (i + 1) as u32;
            let name = ch["name"].as_str().unwrap_or("—");
            let spend = ch["spend"].as_f64().unwrap_or(0.0);
            let contrib = ch["contribution"].as_f64().unwrap_or(0.0);
            let verdict = ch["verdict"].as_str().unwrap_or("—");
            let (ci_lo, ci_hi) = ch_params.as_ref()
                .and_then(|p| p.get(name))
                .map(|p| (p["roi_ci_lower"].as_f64().unwrap_or(0.0), p["roi_ci_upper"].as_f64().unwrap_or(0.0)))
                .unwrap_or((0.0, 0.0));

            ws.write(row, 0, name).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, spend, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, contrib, &num_fmt).map_err(|e| format!("{e}"))?;
            // ROI formula
            ws.write_formula_with_format(row, 3, Formula::new(format!("=IF(B{r}>0,C{r}/B{r},0)", r = row + 1)), &roi_fmt).map_err(|e| format!("{e}"))?;
            ws.write(row, 4, ci_lo).map_err(|e| format!("{e}"))?;
            ws.write(row, 5, ci_hi).map_err(|e| format!("{e}"))?;
            ws.write(row, 6, verdict).map_err(|e| format!("{e}"))?;
        }

        // Conditional formatting: ROI > 2 = green, ROI < 1 = red
        let last_row = chs.len() as u32;
        let green_cond = ConditionalFormatCell::new()
            .set_rule(ConditionalFormatCellRule::GreaterThanOrEqualTo(2.0))
            .set_format(Format::new().set_font_color(Color::RGB(0x22C55E)));
        let red_cond = ConditionalFormatCell::new()
            .set_rule(ConditionalFormatCellRule::LessThan(1.0))
            .set_format(Format::new().set_font_color(Color::RGB(0xEF4444)));
        ws.add_conditional_format(1, 3, last_row, 3, &green_cond).map_err(|e| format!("{e}"))?;
        ws.add_conditional_format(1, 3, last_row, 3, &red_cond).map_err(|e| format!("{e}"))?;

        // ROI bar chart
        let mut chart = Chart::new(ChartType::Bar);
        chart.add_series()
            .set_categories(("ROI каналов", 1, 0, last_row, 0))
            .set_values(("ROI каналов", 1, 3, last_row, 3))
            .set_name("ROI");
        chart.set_width(550).set_height(300);
        chart.title().set_name("ROI по каналам");
        ws.insert_chart(last_row + 2, 0, &chart).map_err(|e| format!("{e}"))?;

        ws.set_column_width(0, 20).map_err(|e| format!("{e}"))?;
        for c in 1..7u16 { ws.set_column_width(c, 15).map_err(|e| format!("{e}"))?; }
    }

    // ── Sheet 4: Share of Spend vs Effect (NEW) ─────────────
    if let Some(chs) = decompose["channels"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("Spend vs Effect").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(0x8B5CF6));

        let headers = ["Канал", "Расход", "% бюджета", "Вклад", "% эффекта", "Efficiency"];
        for (c, h) in headers.iter().enumerate() {
            ws.write_with_format(0, c as u16, *h, &header_fmt).map_err(|e| format!("{e}"))?;
        }

        let total_spend: f64 = chs.iter().map(|c| c["spend"].as_f64().unwrap_or(0.0)).sum();
        let total_contrib: f64 = chs.iter().map(|c| c["contribution"].as_f64().unwrap_or(0.0)).sum();

        for (i, ch) in chs.iter().enumerate() {
            let row = (i + 1) as u32;
            let name = ch["name"].as_str().unwrap_or("—");
            let spend = ch["spend"].as_f64().unwrap_or(0.0);
            let contrib = ch["contribution"].as_f64().unwrap_or(0.0);
            let spend_pct = if total_spend > 0.0 { spend / total_spend } else { 0.0 };
            let effect_pct = if total_contrib > 0.0 { contrib / total_contrib } else { 0.0 };

            ws.write(row, 0, name).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, spend, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, spend_pct, &pct_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 3, contrib, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 4, effect_pct, &pct_fmt).map_err(|e| format!("{e}"))?;
            // Efficiency formula = effect_share / spend_share
            ws.write_formula_with_format(row, 5, Formula::new(format!("=IF(C{r}>0,E{r}/C{r},0)", r = row + 1)), &roi_fmt).map_err(|e| format!("{e}"))?;
        }

        // Clustered bar chart: spend% vs effect%
        let last_row = chs.len() as u32;
        let mut chart = Chart::new(ChartType::Column);
        chart.add_series()
            .set_categories(("Spend vs Effect", 1, 0, last_row, 0))
            .set_values(("Spend vs Effect", 1, 2, last_row, 2))
            .set_name("% бюджета");
        chart.add_series()
            .set_categories(("Spend vs Effect", 1, 0, last_row, 0))
            .set_values(("Spend vs Effect", 1, 4, last_row, 4))
            .set_name("% эффекта");
        chart.set_width(600).set_height(350);
        chart.title().set_name("Share of Spend vs Share of Effect");
        ws.insert_chart(last_row + 2, 0, &chart).map_err(|e| format!("{e}"))?;

        ws.set_column_width(0, 20).map_err(|e| format!("{e}"))?;
        for c in 1..6u16 { ws.set_column_width(c, 15).map_err(|e| format!("{e}"))?; }
    }

    // ── Sheet 4.5: Динамика по периодам (stacked area) ──────
    // Cols: A=date, B=Base, C..=channels[]. Порядок каналов = decompose.channels[].name
    // (так же как на UI и в PPTX), чтобы цвета/легенда были выдержаны единообразно.
    if let Some(time_series) = decompose.get("time_series") {
        let dates = time_series["dates"].as_array();
        let baseline = time_series["baseline"].as_array();
        let channels_map = time_series["channels"].as_object();
        let channel_order: Vec<String> = decompose["channels"].as_array()
            .map(|arr| arr.iter().filter_map(|c| c["name"].as_str().map(|s| s.to_string())).collect())
            .unwrap_or_default();

        if let (Some(dates), Some(channels_map)) = (dates, channels_map) {
            if !dates.is_empty() && (!channel_order.is_empty() || baseline.is_some()) {
                let ws = wb.add_worksheet();
                ws.set_name("Динамика").map_err(|e| format!("{e}"))?;
                ws.set_tab_color(Color::RGB(0x14B8A6));

                // Header row
                ws.write_with_format(0, 0, "Дата", &header_fmt).map_err(|e| format!("{e}"))?;
                let mut col_idx: u16 = 1;
                if baseline.is_some() {
                    ws.write_with_format(0, col_idx, "Base", &header_fmt).map_err(|e| format!("{e}"))?;
                    col_idx += 1;
                }
                for name in &channel_order {
                    ws.write_with_format(0, col_idx, name.as_str(), &header_fmt).map_err(|e| format!("{e}"))?;
                    col_idx += 1;
                }
                let last_col = col_idx.saturating_sub(1);

                // Data rows
                let n_periods = dates.len() as u32;
                for (i, d) in dates.iter().enumerate() {
                    let row = (i + 1) as u32;
                    ws.write(row, 0, d.as_str().unwrap_or("")).map_err(|e| format!("{e}"))?;
                    let mut c: u16 = 1;
                    if let Some(bl) = baseline {
                        let v = bl.get(i).and_then(|x| x.as_f64()).unwrap_or(0.0);
                        ws.write_with_format(row, c, v, &num_fmt).map_err(|e| format!("{e}"))?;
                        c += 1;
                    }
                    for name in &channel_order {
                        let v = channels_map
                            .get(name)
                            .and_then(|a| a.as_array())
                            .and_then(|a| a.get(i))
                            .and_then(|x| x.as_f64())
                            .unwrap_or(0.0);
                        ws.write_with_format(row, c, v, &num_fmt).map_err(|e| format!("{e}"))?;
                        c += 1;
                    }
                }

                // Stacked area chart — каждая колонка = отдельная series
                let mut chart = Chart::new(ChartType::AreaStacked);
                for c in 1..=last_col {
                    chart.add_series()
                        .set_categories(("Динамика", 1, 0, n_periods, 0))
                        .set_values(("Динамика", 1, c, n_periods, c))
                        .set_name(("Динамика", 0, c));
                }
                chart.set_width(720).set_height(400);
                chart.title().set_name("Декомпозиция продаж по периодам");
                let chart_anchor_row = (n_periods + 2) as u32;
                ws.insert_chart(chart_anchor_row, 0, &chart).map_err(|e| format!("{e}"))?;

                ws.set_column_width(0, 14).map_err(|e| format!("{e}"))?;
                for c in 1..=last_col { ws.set_column_width(c, 14).map_err(|e| format!("{e}"))?; }
            }
        }
    }

    // ── Sheet 5: Оптимизация + chart + formulas ─────────────
    if let Some(opt_chs) = optimize["channels"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("Оптимизация").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(0x0EA5E9));

        let headers = ["Канал", "Текущий", "Оптимальный", "Δ", "Δ%", "Текущий ROI"];
        for (c, h) in headers.iter().enumerate() {
            ws.write_with_format(0, c as u16, *h, &header_fmt).map_err(|e| format!("{e}"))?;
        }

        for (i, ch) in opt_chs.iter().enumerate() {
            let row = (i + 1) as u32;
            let name = ch["name"].as_str().unwrap_or("—");
            let curr = ch["current_spend"].as_f64().unwrap_or(0.0);
            let opt = ch["optimal_spend"].as_f64().unwrap_or(0.0);
            let curr_roi = ch["current_roi"].as_f64().unwrap_or(0.0);

            ws.write(row, 0, name).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, curr, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, opt, &num_fmt).map_err(|e| format!("{e}"))?;
            // Delta formula
            ws.write_formula_with_format(row, 3, Formula::new(format!("=C{r}-B{r}", r = row + 1)), &num_fmt).map_err(|e| format!("{e}"))?;
            // Delta% formula
            ws.write_formula_with_format(row, 4, Formula::new(format!("=IF(B{r}>0,D{r}/B{r},0)", r = row + 1)), &pct_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 5, curr_roi, &roi_fmt).map_err(|e| format!("{e}"))?;
        }

        // Conditional formatting: delta > 0 green, < 0 red
        let last_row = opt_chs.len() as u32;
        let green_d = ConditionalFormatCell::new()
            .set_rule(ConditionalFormatCellRule::GreaterThan(0.0))
            .set_format(Format::new().set_font_color(Color::RGB(0x22C55E)));
        let red_d = ConditionalFormatCell::new()
            .set_rule(ConditionalFormatCellRule::LessThan(0.0))
            .set_format(Format::new().set_font_color(Color::RGB(0xEF4444)));
        ws.add_conditional_format(1, 3, last_row, 3, &green_d).map_err(|e| format!("{e}"))?;
        ws.add_conditional_format(1, 3, last_row, 3, &red_d).map_err(|e| format!("{e}"))?;
        ws.add_conditional_format(1, 4, last_row, 4, &green_d).map_err(|e| format!("{e}"))?;
        ws.add_conditional_format(1, 4, last_row, 4, &red_d).map_err(|e| format!("{e}"))?;

        // Clustered bar: current vs optimal
        let mut chart = Chart::new(ChartType::Column);
        chart.add_series()
            .set_categories(("Оптимизация", 1, 0, last_row, 0))
            .set_values(("Оптимизация", 1, 1, last_row, 1))
            .set_name("Текущий");
        chart.add_series()
            .set_categories(("Оптимизация", 1, 0, last_row, 0))
            .set_values(("Оптимизация", 1, 2, last_row, 2))
            .set_name("Оптимальный");
        chart.set_width(600).set_height(350);
        chart.title().set_name("Текущий vs Оптимальный бюджет");
        ws.insert_chart(last_row + 2, 0, &chart).map_err(|e| format!("{e}"))?;

        // Totals + lift
        let total_r = last_row + 1;
        ws.write_with_format(total_r, 0, "ИТОГО", &bold).map_err(|e| format!("{e}"))?;
        ws.write_formula_with_format(total_r, 1, Formula::new(format!("=SUM(B2:B{})", last_row + 1)), &bold).map_err(|e| format!("{e}"))?;
        ws.write_formula_with_format(total_r, 2, Formula::new(format!("=SUM(C2:C{})", last_row + 1)), &bold).map_err(|e| format!("{e}"))?;

        let lift = optimize["expected_lift_pct"].as_f64().unwrap_or(0.0);
        ws.write(total_r + 1, 0, "Ожидаемый прирост").map_err(|e| format!("{e}"))?;
        ws.write(total_r + 1, 1, &format!("{lift:+.1}%")).map_err(|e| format!("{e}"))?;

        ws.set_column_width(0, 20).map_err(|e| format!("{e}"))?;
        for c in 1..6u16 { ws.set_column_width(c, 16).map_err(|e| format!("{e}"))?; }
    }

    // ── Sheet 5.5: Сценарии (if any) ─────────────────────────
    // Метрики × сценарии. Если у всех scenarios есть roas_money — показываем
    // деньги (homogeneous), иначе native (смешанные единицы) с пометкой.
    if !scenarios.is_empty() {
        let ws = wb.add_worksheet();
        ws.set_name("Сценарии").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(0xEC4899));

        let homogeneous_money = scenarios.iter()
            .all(|s| s["totals"]["roas_money"].as_f64().is_some());
        let budget_label = if homogeneous_money { "Бюджет (₽)" } else { "Бюджет (native)" };
        let roas_label = if homogeneous_money { "ROAS (₽)" } else { "ROAS (native)" };
        let spend_field = if homogeneous_money { "total_spend_money" } else { "total_spend" };
        let roas_field = if homogeneous_money { "roas_money" } else { "roas" };

        // Header: Метрика | scenario1 | scenario2 | ...
        ws.write_with_format(0, 0, "Метрика", &header_fmt).map_err(|e| format!("{e}"))?;
        for (i, s) in scenarios.iter().enumerate() {
            let name = s["scenario_name"].as_str().unwrap_or("—");
            ws.write_with_format(0, (i + 1) as u16, name, &header_fmt).map_err(|e| format!("{e}"))?;
        }

        // Rows: Прогноз KPI | Бюджет | ROAS | Лифт vs baseline
        let rows: Vec<(&str, &str, &Format)> = vec![
            ("Прогноз KPI", "predicted_kpi", &num_fmt),
            (budget_label, spend_field, &num_fmt),
            (roas_label, roas_field, &roi_fmt),
        ];
        for (i, (label, field, fmt)) in rows.iter().enumerate() {
            let row = (i + 1) as u32;
            ws.write(row, 0, *label).map_err(|e| format!("{e}"))?;
            for (j, s) in scenarios.iter().enumerate() {
                let v = s["totals"][*field].as_f64().unwrap_or(0.0);
                ws.write_with_format(row, (j + 1) as u16, v, *fmt).map_err(|e| format!("{e}"))?;
            }
        }
        // Lift row — строки формата "+N%"
        let lift_row = (rows.len() + 1) as u32;
        ws.write(lift_row, 0, "Лифт vs baseline").map_err(|e| format!("{e}"))?;
        for (j, s) in scenarios.iter().enumerate() {
            let lift = s["totals"]["lift_pct"].as_f64().unwrap_or(0.0);
            ws.write(lift_row, (j + 1) as u16, format!("+{lift:.1}%")).map_err(|e| format!("{e}"))?;
        }

        // Подсветить зелёным лучший ROAS
        let roas_row = 3u32; // 0=header, 1=KPI, 2=Budget, 3=ROAS
        let best_idx = scenarios.iter().enumerate()
            .max_by(|(_, a), (_, b)| {
                let ra = a["totals"][roas_field].as_f64().unwrap_or(0.0);
                let rb = b["totals"][roas_field].as_f64().unwrap_or(0.0);
                ra.partial_cmp(&rb).unwrap_or(std::cmp::Ordering::Equal)
            })
            .map(|(i, _)| i);
        if let Some(bi) = best_idx {
            let best_fmt = Format::new()
                .set_font_color(Color::RGB(0x22C55E))
                .set_bold();
            let v = scenarios[bi]["totals"][roas_field].as_f64().unwrap_or(0.0);
            ws.write_with_format(roas_row, (bi + 1) as u16, v, &best_fmt)
                .map_err(|e| format!("{e}"))?;
        }

        // Note про homogeneity для native-mixed случая
        if !homogeneous_money {
            let note_row = (rows.len() + 3) as u32;
            let note_fmt = Format::new()
                .set_font_color(Color::RGB(0xF59E0B))
                .set_italic();
            let note = "⚠ ROAS в native-единицах (TRP/GRP + ₽) — несопоставим между \
                        каналами разных единиц. Укажи CPP в блоке «Проверка» для перевода в ₽.";
            ws.merge_range(
                note_row, 0,
                note_row, scenarios.len() as u16,
                note, &note_fmt
            ).map_err(|e| format!("{e}"))?;
        }

        ws.set_column_width(0, 22).map_err(|e| format!("{e}"))?;
        for c in 1..=(scenarios.len() as u16) {
            ws.set_column_width(c, 20).map_err(|e| format!("{e}"))?;
        }
    }

    // ── Sheet: Данные (сырой time-series для графиков) ───────
    {
        let ws = wb.add_worksheet();
        ws.set_name("Данные").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(0x22C55E));

        let ts = &decompose["time_series"];
        let dates = ts["dates"].as_array().cloned().unwrap_or_default();
        let baseline = ts["baseline"].as_array().cloned().unwrap_or_default();
        let channels_ts = ts["channels"].as_object().cloned().unwrap_or_default();
        let channel_names: Vec<String> = channels_ts.keys().cloned().collect();

        // Header row
        ws.write_with_format(0, 0, "Период", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(0, 1, "Baseline", &header_fmt).map_err(|e| format!("{e}"))?;
        for (i, name) in channel_names.iter().enumerate() {
            ws.write_with_format(0, (i + 2) as u16, name.as_str(), &header_fmt).map_err(|e| format!("{e}"))?;
        }
        let total_col = (channel_names.len() + 2) as u16;
        let kpi_col = total_col + 1;
        ws.write_with_format(0, total_col, "Медиа-вклад", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(0, kpi_col, "KPI (факт+модель)", &header_fmt).map_err(|e| format!("{e}"))?;

        // Data rows
        let n_periods = dates.len();
        for t in 0..n_periods {
            let row = (t + 1) as u32;
            if let Some(s) = dates.get(t).and_then(|v| v.as_str()) {
                ws.write(row, 0, s).map_err(|e| format!("{e}"))?;
            }
            let b = baseline.get(t).and_then(|v| v.as_f64()).unwrap_or(0.0);
            ws.write_with_format(row, 1, b, &num_fmt).map_err(|e| format!("{e}"))?;
            let mut media_total = 0.0;
            for (i, name) in channel_names.iter().enumerate() {
                let v = channels_ts[name].as_array()
                    .and_then(|arr| arr.get(t))
                    .and_then(|x| x.as_f64())
                    .unwrap_or(0.0);
                ws.write_with_format(row, (i + 2) as u16, v, &num_fmt).map_err(|e| format!("{e}"))?;
                media_total += v;
            }
            ws.write_with_format(row, total_col, media_total, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, kpi_col, b + media_total, &num_fmt).map_err(|e| format!("{e}"))?;
        }

        // Headline explainer
        let explainer_row = (n_periods + 3) as u32;
        ws.write_with_format(explainer_row, 0, "Как использовать лист:", &bold).map_err(|e| format!("{e}"))?;
        ws.write(explainer_row + 1, 0, "• Выделите колонки «Период» + нужные → Вставка → Диаграмма → получите график вклада канала по времени.").map_err(|e| format!("{e}"))?;
        ws.write(explainer_row + 2, 0, "• Baseline — часть KPI без медиа (органический спрос, сезонность, бренд).").map_err(|e| format!("{e}"))?;
        ws.write(explainer_row + 3, 0, "• Медиа-вклад = сумма по каналам. KPI = Baseline + Медиа-вклад (то что модель объясняет).").map_err(|e| format!("{e}"))?;

        ws.set_column_width(0, 14).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 14).map_err(|e| format!("{e}"))?;
        for c in 2..kpi_col + 1 { ws.set_column_width(c, 16).map_err(|e| format!("{e}"))?; }
    }

    // ── Sheet 6: Глоссарий (NEW) ────────────────────────────
    {
        let ws = wb.add_worksheet();
        ws.set_name("Глоссарий").map_err(|e| format!("{e}"))?;

        ws.write_with_format(0, 0, "Термин", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(0, 1, "Определение", &header_fmt).map_err(|e| format!("{e}"))?;

        let terms: &[(&str, &str)] = &[
            ("MQS", "Model Quality Score — комплексная оценка качества модели (0-100). >80 = отлично, 60-80 = хорошо, <60 = требует доработки."),
            ("R²", "Коэффициент детерминации — доля дисперсии KPI, объяснённая моделью. 1.0 = идеальная модель."),
            ("MAPE", "Mean Absolute Percentage Error — средняя абсолютная ошибка в %. <10% = отлично."),
            ("R-hat", "Статистика сходимости MCMC. Значение ~1.0 означает, что цепи сошлись. >1.05 = проблема."),
            ("ROI", "Return on Investment — отношение инкрементального вклада канала к его расходу. ROI 2.0x = каждый рубль приносит 2 рубля."),
            ("miROAS", "Marginal incremental ROAS — отдача от каждого СЛЕДУЮЩЕГО рубля. Показывает, стоит ли увеличивать расходы на канал."),
            ("Adstock", "Эффект запаздывания рекламы. TV-реклама влияет на продажи ещё 2-8 недель после показа."),
            ("Hill function", "Функция насыщения. Моделирует убывающую отдачу: первые рубли эффективнее последних."),
            ("CI (95%)", "Доверительный интервал — диапазон, в который истинное значение попадает с 95% вероятностью."),
            ("Base sales", "Продажи без рекламного воздействия (органический спрос, бренд-эффект, сезонность)."),
            ("Efficiency Index", "Отношение доли эффекта к доле бюджета. >1.0 = канал эффективнее среднего."),
        ];
        for (i, (term, def)) in terms.iter().enumerate() {
            let row = (i + 1) as u32;
            ws.write_with_format(row, 0, *term, &bold).map_err(|e| format!("{e}"))?;
            ws.write(row, 1, *def).map_err(|e| format!("{e}"))?;
        }
        ws.set_column_width(0, 18).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 80).map_err(|e| format!("{e}"))?;
    }

    wb.save(path).map_err(|e| format!("XLSX save error: {e}"))?;
    Ok(())
}
