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

fn exports_dir(project_id: &str) -> Result<PathBuf, String> {
    let appdata = std::env::var("APPDATA").map_err(|_| "APPDATA not set".to_string())?;
    let identifier = env!("CARGO_PKG_NAME");
    let dir = PathBuf::from(appdata)
        .join(identifier)
        .join("projects")
        .join(project_id)
        .join("exports");
    std::fs::create_dir_all(&dir).map_err(|e| format!("Failed to create exports dir: {e}"))?;
    Ok(dir)
}

// ── Markdown report ──────────────────────────────────────────────────────────

/// Build a full Markdown report from MMM pipeline data.
fn build_markdown(model: &Value, decompose: &Value, optimize: &Value) -> String {
    let mqs        = model["diagnostics"]["mqs"]["score"].as_f64().unwrap_or(0.0);
    let mqs_label  = model["diagnostics"]["mqs"]["tier_label"].as_str().unwrap_or("N/A");
    let r_squared  = model["diagnostics"]["r_squared"].as_f64().unwrap_or(0.0);
    let mape       = model["diagnostics"]["mape"].as_f64().unwrap_or(0.0);
    let r_hat      = model["diagnostics"]["r_hat"].as_f64();
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

    build_xlsx(&model_data, &decompose_data, &optimize_data, &path)?;

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

fn build_xlsx(model: &Value, decompose: &Value, optimize: &Value, path: &PathBuf) -> Result<(), String> {
    let mut wb = Workbook::new();
    let bold = Format::new().set_bold();

    // ── Sheet 1: Executive Summary ──────────────────────────
    {
        let ws = wb.add_worksheet();
        ws.set_name("Executive Summary")
            .map_err(|e| format!("XLSX sheet name error: {e}"))?;

        let mqs       = model["diagnostics"]["mqs"]["score"].as_f64().unwrap_or(0.0);
        let mqs_label = model["diagnostics"]["mqs"]["tier_label"].as_str().unwrap_or("N/A");
        let r_sq      = model["diagnostics"]["r_squared"].as_f64().unwrap_or(0.0);
        let mape      = model["diagnostics"]["mape"].as_f64().unwrap_or(0.0);
        let lift      = optimize["expected_lift_pct"].as_f64().unwrap_or(0.0);
        let budget    = optimize["total_budget"].as_f64().unwrap_or(0.0);

        ws.write_with_format(0, 0, "Marketing Mix Model Report", &bold)
            .map_err(|e| format!("{e}"))?;

        ws.write_with_format(2, 0, "Метрика", &bold)
            .map_err(|e| format!("{e}"))?;
        ws.write_with_format(2, 1, "Значение", &bold)
            .map_err(|e| format!("{e}"))?;

        let rows: &[(&str, String)] = &[
            ("MQS Score",             format!("{mqs:.1}")),
            ("MQS Tier",              mqs_label.to_string()),
            ("R²",                    format!("{r_sq:.4}")),
            ("MAPE (%)",              format!("{mape:.2}")),
            ("Прирост от оптим. (%)", format!("{lift:+.1}")),
            ("Общий бюджет",          format!("{budget:.0}")),
        ];
        for (i, (label, val)) in rows.iter().enumerate() {
            let row = (i + 3) as u32;
            ws.write(row, 0, *label).map_err(|e| format!("{e}"))?;
            ws.write(row, 1, val.as_str()).map_err(|e| format!("{e}"))?;
        }
        ws.set_column_width(0, 28).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 20).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 2: Decomposition ──────────────────────────────
    if let Some(wf) = decompose["waterfall"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("Декомпозиция").map_err(|e| format!("{e}"))?;

        ws.write_with_format(0, 0, "Категория",   &bold).map_err(|e| format!("{e}"))?;
        ws.write_with_format(0, 1, "Вклад",       &bold).map_err(|e| format!("{e}"))?;
        ws.write_with_format(0, 2, "% от общего", &bold).map_err(|e| format!("{e}"))?;

        for (i, item) in wf.iter().enumerate() {
            let row = (i + 1) as u32;
            let cat = item["category"].as_str().unwrap_or("—");
            let val = item["value"].as_f64().unwrap_or(0.0);
            let pct = item["contribution_pct"].as_f64().unwrap_or(0.0);
            ws.write(row, 0, cat).map_err(|e| format!("{e}"))?;
            ws.write(row, 1, val).map_err(|e| format!("{e}"))?;
            ws.write(row, 2, pct).map_err(|e| format!("{e}"))?;
        }
        ws.set_column_width(0, 25).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 16).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 16).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 3: Channel ROI ────────────────────────────────
    if let Some(chs) = decompose["channels"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("ROI каналов").map_err(|e| format!("{e}"))?;

        let headers = ["Канал", "Расход", "Вклад", "ROI", "CI нижний", "CI верхний", "Вердикт"];
        for (c, h) in headers.iter().enumerate() {
            ws.write_with_format(0, c as u16, *h, &bold).map_err(|e| format!("{e}"))?;
        }

        let ch_params = model["channelParams"].as_object();

        for (i, ch) in chs.iter().enumerate() {
            let row  = (i + 1) as u32;
            let name    = ch["name"].as_str().unwrap_or("—");
            let spend   = ch["spend"].as_f64().unwrap_or(0.0);
            let contrib = ch["contribution"].as_f64().unwrap_or(0.0);
            let roi     = ch["roi"].as_f64().unwrap_or(0.0);
            let verdict = ch["verdict"].as_str().unwrap_or("—");
            let (ci_lo, ci_hi) = ch_params
                .as_ref()
                .and_then(|p| p.get(name))
                .map(|p| (
                    p["roi_ci_lower"].as_f64().unwrap_or(0.0),
                    p["roi_ci_upper"].as_f64().unwrap_or(0.0),
                ))
                .unwrap_or((0.0, 0.0));

            ws.write(row, 0, name   ).map_err(|e| format!("{e}"))?;
            ws.write(row, 1, spend  ).map_err(|e| format!("{e}"))?;
            ws.write(row, 2, contrib).map_err(|e| format!("{e}"))?;
            ws.write(row, 3, roi    ).map_err(|e| format!("{e}"))?;
            ws.write(row, 4, ci_lo  ).map_err(|e| format!("{e}"))?;
            ws.write(row, 5, ci_hi  ).map_err(|e| format!("{e}"))?;
            ws.write(row, 6, verdict).map_err(|e| format!("{e}"))?;
        }
        ws.set_column_width(0, 20).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 4: Optimization ───────────────────────────────
    if let Some(opt_chs) = optimize["channels"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("Оптимизация").map_err(|e| format!("{e}"))?;

        let headers = ["Канал", "Текущий бюджет", "Оптимальный бюджет", "Δ", "Δ%", "Текущий ROI"];
        for (c, h) in headers.iter().enumerate() {
            ws.write_with_format(0, c as u16, *h, &bold).map_err(|e| format!("{e}"))?;
        }

        for (i, ch) in opt_chs.iter().enumerate() {
            let row     = (i + 1) as u32;
            let name    = ch["name"].as_str().unwrap_or("—");
            let curr    = ch["current_spend"].as_f64().unwrap_or(0.0);
            let opt     = ch["optimal_spend"].as_f64().unwrap_or(0.0);
            let curr_roi = ch["current_roi"].as_f64().unwrap_or(0.0);
            let delta   = opt - curr;
            let dpct    = if curr > 0.0 { delta / curr * 100.0 } else { 0.0 };

            ws.write(row, 0, name    ).map_err(|e| format!("{e}"))?;
            ws.write(row, 1, curr    ).map_err(|e| format!("{e}"))?;
            ws.write(row, 2, opt     ).map_err(|e| format!("{e}"))?;
            ws.write(row, 3, delta   ).map_err(|e| format!("{e}"))?;
            ws.write(row, 4, dpct    ).map_err(|e| format!("{e}"))?;
            ws.write(row, 5, curr_roi).map_err(|e| format!("{e}"))?;
        }
        ws.set_column_width(0, 20).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 18).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 20).map_err(|e| format!("{e}"))?;
    }

    wb.save(path).map_err(|e| format!("XLSX save error: {e}"))?;
    Ok(())
}
