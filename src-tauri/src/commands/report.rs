//! Econometrica report generation commands.
//!
//! econ_generate_report - Markdown report from MMM pipeline data.
//! econ_export_xlsx     - Multi-sheet XLSX export.
//! econ_open_exports    - Open project exports folder in OS file manager.

use chrono::Local;
use log::info;
use rust_xlsxwriter::{DocProperties, Format, FormatAlign, FormatBorder, Workbook};
use serde_json::Value;
use std::io::{Cursor, Read, Write};
use std::path::{Path, PathBuf};

// ── Helpers ──────────────────────────────────────────────────────────────────

/// Канал с ненадёжным ROI (битые единицы / артефакт): unit_smell ИЛИ маркер
/// артефакта в тексте вердикта. Зеркалит narrative_adapter._roi_unreliable
/// (Python-мост сюда не доходит — Rust XLSX/MD читают results JSON напрямую).
/// Битый ROI нельзя подавать клиенту числом (INV-50) — билдер пишет «н/д».
fn roi_unreliable(ch: &Value) -> bool {
    if ch["unit_smell"].as_bool().unwrap_or(false) {
        return true;
    }
    let v = ch["verdict"].as_str().unwrap_or("").to_lowercase();
    v.contains("завышен")
        || v.contains("нереалистичн")
        || v.contains("артефакт")
        || v.contains("не рубл")
}

/// Волна 1 пункт 2 (2026-06-20): заголовок-вердикт плашки надёжности модели.
/// Зеркалит лейблы Python (narrative_adapter / sections.py / builder.py) — Rust
/// XLSX/MD читают optimization.json напрямую, мимо Python-моста. caveat_text сам
/// идёт VERBATIM из optimization.json (SSOT optimizer_honesty, INV-50) — здесь
/// только заголовок. Пустая строка ⇒ плашку не рисуем (verdict reliable/нет).
fn reliability_label(verdict: &str) -> &'static str {
    match verdict {
        "uncertain" => "Ограниченная надёжность модели",
        "unreliable" => "Модель ненадёжна — переброска отключена",
        "unknown" => "Надёжность модели не подтверждена",
        "" | "reliable" => "",
        _ => "Надёжность модели",
    }
}

/// Волна 1 пункт 3 (2026-06-20): отображаемый вердикт-действие (рус) + honesty-
/// смягчение (решение 2a). Зеркалит engines.channel_action.soften_verdict_display
/// (Python) — Rust XLSX/MD читают results JSON напрямую, мимо Python-моста, поэтому
/// рус-локализацию и смягчение держим здесь. Глобальная надёжность модели смягчает
/// ДИРЕКТИВНОСТЬ, сохраняя НАПРАВЛЕНИЕ: reliable→«Увеличить»; uncertain/unknown→
/// «Увеличить (предв.)»; unreliable→«Требует переобучения». Снимает рассогласование
/// (прежде XLSX/MD писали англ. machine-key «Scale», PPTX — рус «Увеличить»).
fn verdict_display(verdict_key: &str, reliability_verdict: &str) -> String {
    let base = match verdict_key {
        "Scale" => "Увеличить",
        "Hold" => "Держать",
        "Watch" => "Наблюдать",
        "Reduce" => "Сократить",
        "Cut" => "Остановить",
        "Uncertain" => "Недостаточно данных",
        other => other,
    };
    match reliability_verdict {
        "unreliable" => "Требует переобучения".to_string(),
        "uncertain" | "unknown" => {
            if verdict_key == "Uncertain" || verdict_key == "Watch" {
                base.to_string()
            } else {
                format!("{base} (предв.)")
            }
        }
        _ => base.to_string(),
    }
}

/// Волна 2 (2026-06-20): чистка мусора в клиентских метках. Имена каналов несут
/// `\n` и двойные пробелы из исходных Excel-заголовков («Статьи Бюджет \nДО НДС
/// до АК») — в отчёте это многострочные ячейки и рваный текст. Схлопывает любой
/// whitespace (вкл. переводы строк) в один пробел, обрезает края.
fn clean_label(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Волна 3 (2026-06-20): метка режима анализа + типа KPI (контекст метрик для
/// клиента). Зеркало Python (narrative_adapter). Rust XLSX/MD читают decompose
/// JSON напрямую. Пустая строка ⇒ метку не показываем.
fn analysis_mode_label(mode: &str) -> &'static str {
    match mode {
        "roi" => "ROI (деньги)",
        "effectiveness" => "Эффективность (доля вклада)",
        "mixed" | "expert" => "Смешанный (эксперт)",
        _ => "",
    }
}
fn kpi_kind_label(kind: &str) -> &'static str {
    match kind {
        "monetary" => "денежный",
        "count" => "количественный",
        _ => "",
    }
}

/// Transliterate Cyrillic to Latin per GOST 7.79-2000 System B, then strip to
/// ASCII-alphanumeric + underscore. Used for client-slug segment of XLSX
/// filename (Aurora_Econometrica_{slug}_Model_{date}_v{NN}.xlsx). Returns
/// empty string if no printable chars remain - caller falls back to legacy
/// mmm_report_{ts}.xlsx.
fn sanitize_slug(s: &str) -> String {
    let table: &[(char, &str)] = &[
        ('а', "a"), ('б', "b"), ('в', "v"), ('г', "g"), ('д', "d"),
        ('е', "e"), ('ё', "yo"), ('ж', "zh"), ('з', "z"), ('и', "i"),
        ('й', "j"), ('к', "k"), ('л', "l"), ('м', "m"), ('н', "n"),
        ('о', "o"), ('п', "p"), ('р', "r"), ('с', "s"), ('т', "t"),
        ('у', "u"), ('ф', "f"), ('х', "h"), ('ц', "c"), ('ч', "ch"),
        ('ш', "sh"), ('щ', "shch"), ('ъ', ""), ('ы', "y"), ('ь', ""),
        ('э', "e"), ('ю', "yu"), ('я', "ya"),
    ];
    let mut out = String::new();
    for ch in s.chars() {
        let lower = ch.to_lowercase().next().unwrap_or(ch);
        let is_upper = ch.is_uppercase();
        if let Some((_, repl)) = table.iter().find(|(k, _)| *k == lower) {
            // Preserve case on first char of transliterated pair
            let mut chars = repl.chars();
            if let Some(first) = chars.next() {
                if is_upper {
                    out.extend(first.to_uppercase());
                } else {
                    out.push(first);
                }
                out.extend(chars);
            }
        } else if ch.is_ascii_alphanumeric() {
            out.push(ch);
        } else if matches!(ch, ' ' | '-' | '_' | '.')
            && !out.ends_with('_') {
                out.push('_');
            }
        // Everything else is dropped
    }
    // Trim trailing underscores + truncate to 40 chars
    let trimmed = out.trim_matches('_').to_string();
    trimmed.chars().take(40).collect()
}

/// Scan exports directory for previous Aurora_Econometrica_{slug}_Model_*_v{NN}.xlsx
/// files, parse the max version number, return next. Default: 1.
fn detect_version(exports_dir: &Path, slug: &str) -> u32 {
    if slug.is_empty() { return 1; }
    let prefix = format!("Aurora_Econometrica_{slug}_Model_");
    let entries = match std::fs::read_dir(exports_dir) {
        Ok(e) => e,
        Err(_) => return 1,
    };
    let mut max_v: u32 = 0;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if !name_str.starts_with(&prefix) || !name_str.ends_with(".xlsx") { continue; }
        // Extract _v{NN}.xlsx suffix
        if let Some(v_pos) = name_str.rfind("_v") {
            let v_part = &name_str[v_pos + 2..name_str.len() - 5]; // strip "_v" ... ".xlsx"
            if let Ok(v) = v_part.parse::<u32>() {
                if v > max_v { max_v = v; }
            }
        }
    }
    max_v + 1
}

/// Apply the base Arial-10pt format to all typical data columns of a sheet so
/// bare `ws.write(row, col, val)` calls inherit font family/size without
/// per-cell formatting. Explicit-format cells retain their own set attributes
/// while inheriting unset column-level attributes (Format merging rule).
fn apply_base_cols(ws: &mut rust_xlsxwriter::Worksheet, fmt: &Format) -> Result<(), String> {
    for c in 0..20u16 {
        ws.set_column_format(c, fmt).map_err(|e| format!("{e}"))?;
    }
    Ok(())
}

/// Tier-1 print setup per Standards/04 §print: landscape, 1-page-wide fit,
/// gridlines off, header/footer with confidentiality + page numbers.
fn apply_print_setup(
    ws: &mut rust_xlsxwriter::Worksheet,
    sheet_name: &str,
) -> Result<(), String> {
    ws.set_print_gridlines(false);
    ws.set_landscape();
    ws.set_print_fit_to_pages(1, 0); // 1 wide, unlimited tall
    ws.set_margins(0.5, 0.5, 0.75, 0.75, 0.3, 0.3);
    ws.set_header(format!("&LAurora AI Econometrica - {sheet_name}&R&D"));
    ws.set_footer("&LConfidential | Aurora AI&CPage &P of &N&R&F");
    Ok(())
}

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
        "normalization": "Media нормализованы Robyn-style (spend / mean(spend) после adstock); control z-нормализованы; y нормализован к std=1.",
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
    // Использует customizable projects_dir() из project.rs - учитывает user-config
    // и env AURORA_PROJECTS_ROOT. Единый источник правды для путей.
    let dir = crate::commands::project::project_dir(project_id)?.join("exports");
    std::fs::create_dir_all(&dir).map_err(|e| format!("Failed to create exports dir: {e}"))?;
    Ok(dir)
}

/// Прочитать все scenario JSON из project_dir/results/scenarios/.
/// Используется build_xlsx для листа «Сценарии». Порядок - по имени файла (стабильный).
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
    // 5c followup (2026-05-24): same money-axis fix as XLSX Executive Summary
    // (line 803). `total_budget` is native-sum (mixed TRPs + ₽ = arithmetic
    // garbage). Use money-axis aggregates → matches UI Block A semantics.
    let budget = optimize["total_current_money"].as_f64()
        .or_else(|| optimize["total_budget_money"].as_f64())
        .or_else(|| {
            decompose["channels"].as_array().map(|chs| {
                chs.iter().map(|c| c["spend"].as_f64().unwrap_or(0.0)).sum()
            })
        })
        .unwrap_or(0.0);

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
    md.push_str("# Marketing Mix Model - Аналитический отчёт\n\n");
    md.push_str(&format!("*Сгенерировано: {now}*\n\n---\n\n"));

    // ── Executive Summary ────────────────────────────────────
    md.push_str("## EXECUTIVE SUMMARY\n\n");
    md.push_str(&format!("- **Качество модели (MQS):** {mqs:.1} - {mqs_label}\n"));
    // Волна 3 (2026-06-20): метка режима анализа + типа KPI (контекст метрик).
    {
        let md_mode = analysis_mode_label(&decompose["derived_mode"].as_str().unwrap_or("roi").to_lowercase());
        let md_kind = kpi_kind_label(&decompose["kpi_kind"].as_str().unwrap_or("monetary").to_lowercase());
        if !md_mode.is_empty() {
            let kpi_part = if md_kind.is_empty() { String::new() } else { format!(" · KPI: {md_kind}") };
            md.push_str(&format!("- **Режим анализа:** {md_mode}{kpi_part}\n"));
        }
    }
    md.push_str(&format!("- **R²:** {r_squared:.4} (объяснённая дисперсия: {:.1}%)\n", r_squared * 100.0));
    md.push_str(&format!("- **MAPE:** {mape:.2}%\n"));
    md.push_str(&format!("- **Ожидаемый прирост от оптимизации:** {:+.1}%\n", lift));
    md.push_str(&format!("- **Лучший канал по ROI:** {top_ch}\n"));
    if budget > 0.0 {
        md.push_str(&format!("- **Оптимизированный бюджет:** {budget:.0} руб.\n"));
    }
    // Волна 1 пункт 2 (2026-06-20): плашка надёжности модели (verdict != reliable).
    // caveat_text VERBATIM из optimization.json (SSOT optimizer_honesty, INV-50) —
    // тот же текст, что в UI/HTML/PPTX. Rust читает optimize JSON напрямую (мимо
    // Python-моста) → плашка-зеркало. Заголовок-вердикт — reliability_label.
    {
        let mr_verdict = optimize["model_reliability"]["verdict"].as_str().unwrap_or("").to_lowercase();
        let mr_label = reliability_label(&mr_verdict);
        let mr_caveat = optimize["model_reliability"]["caveat_text"].as_str().unwrap_or("");
        if !mr_label.is_empty() && !mr_caveat.is_empty() {
            md.push_str(&format!("\n> ⚠ **{mr_label}.** {mr_caveat}\n"));
        }
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

    // Волна 2 фикс (2026-06-20): waterfall = объект {labels, values, types}
    // (прежде .as_array() на объекте → секция Waterfall молча терялась в MD).
    if let Some(wf) = decompose["waterfall"].as_object() {
        let labels = wf.get("labels").and_then(|v| v.as_array());
        let values = wf.get("values").and_then(|v| v.as_array());
        let types = wf.get("types").and_then(|v| v.as_array());
        if let (Some(labels), Some(values)) = (labels, values) {
            md.push_str("### Вклады в продажи (Waterfall)\n\n");
            md.push_str("| Категория | Вклад | % |\n");
            md.push_str("|-----------|------:|--:|\n");
            let total_val = types
                .and_then(|t| t.iter().position(|x| x.as_str() == Some("total")))
                .and_then(|i| values.get(i)).and_then(|v| v.as_f64())
                .unwrap_or(0.0);
            // Аудит 2026-06-20: fallback-знаменатель исключает total-элемент (иначе
            // при наличии total в values сумма завышена) — консистентно с XLSX.
            let denom = if total_val != 0.0 { total_val }
                        else {
                            match types {
                                Some(t) => values.iter().enumerate()
                                    .filter(|(i, _)| t.get(*i).and_then(|x| x.as_str()) != Some("total"))
                                    .filter_map(|(_, v)| v.as_f64()).sum(),
                                None => values.iter().filter_map(|v| v.as_f64()).sum(),
                            }
                        };
            for (i, lab) in labels.iter().enumerate() {
                let cat = clean_label(lab.as_str().unwrap_or("-"));
                let val = values.get(i).and_then(|v| v.as_f64()).unwrap_or(0.0);
                let pct = if denom != 0.0 { val / denom * 100.0 } else { 0.0 };
                md.push_str(&format!("| {cat} | {val:.0} | {pct:.1}% |\n"));
            }
            md.push('\n');
        }
    }

    // ── Channel ROI ──────────────────────────────────────────
    // Волна 1 пункт 3 (2026-06-20): honesty-смягчение вердикта (решение 2a) —
    // verdict_display несёт рус + «(предв.)» при не-reliable модели.
    let mr_v_md = optimize["model_reliability"]["verdict"].as_str().unwrap_or("").to_lowercase();
    if let Some(chs) = decompose["channels"].as_array() {
        md.push_str("## БЛОК: Инвестиции. ROI по каналам\n\n");
        md.push_str("| Канал | Расход | Вклад | ROI | Вердикт |\n");
        md.push_str("|-------|-------:|------:|----:|---------|\n");
        for ch in chs {
            let name   = ch["name"].as_str().unwrap_or("-");
            let spend  = ch["spend"].as_f64().unwrap_or(0.0);
            let contrib = ch["contribution"].as_f64().unwrap_or(0.0);
            let verdict = ch["verdict"].as_str().unwrap_or("-");
            // INV-50: битый ROI (артефакт единиц) не пишем числом.
            let roi_cell = if roi_unreliable(ch) {
                "н/д".to_string()
            } else {
                format!("{:.2}x", ch["roi"].as_f64().unwrap_or(0.0))
            };
            let vshow = verdict_display(verdict, &mr_v_md);
            md.push_str(&format!("| {name} | {spend:.0} | {contrib:.0} | {roi_cell} | {vshow} |\n"));
        }
        md.push('\n');

        // ROI CI from decompose channels (5c fix 2026-05-04 - was reading from
        // model["channelParams"] with typo `ci_lower/upper` → defaulting к 0).
        if let Some(chs_for_ci) = decompose["channels"].as_array() {
            md.push_str("### ROI с доверительными интервалами (90%)\n\n");
            md.push_str("| Канал | ROI | CI нижний | CI верхний |\n");
            md.push_str("|-------|----:|----------:|-----------:|\n");
            for ch in chs_for_ci {
                let ch_name = ch["name"].as_str().unwrap_or("-");
                if roi_unreliable(ch) {
                    md.push_str(&format!("| {ch_name} | н/д | — | — |\n"));
                } else {
                    let roi   = ch["roi"].as_f64().unwrap_or(0.0);
                    let ci_lo = ch["roi_ci_low"].as_f64().unwrap_or(0.0);
                    let ci_hi = ch["roi_ci_high"].as_f64().unwrap_or(0.0);
                    md.push_str(&format!("| {ch_name} | {roi:.2}x | {ci_lo:.2}x | {ci_hi:.2}x |\n"));
                }
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
        // 5c followup (2026-05-24): same money-axis fix as XLSX «Оптимизация»
        // (line 1251). Native `current_spend`/`optimal_spend` mix TRPs+₽ под
        // column header "₽" = lying. Read money-axis с fallback к native (legacy
        // pickles без _money suffix variants).
        md.push_str("### Текущее vs Оптимальное распределение (₽)\n\n");
        md.push_str("| Канал | Текущий, ₽ | Оптимальный, ₽ | Δ, ₽ | Δ% |\n");
        md.push_str("|-------|-----------:|---------------:|-----:|---:|\n");
        for ch in opt_chs {
            let name  = ch["name"].as_str().unwrap_or("-");
            let curr  = ch["current_spend_money"].as_f64()
                .unwrap_or_else(|| ch["current_spend"].as_f64().unwrap_or(0.0));
            let opt   = ch["optimal_spend_money"].as_f64()
                .unwrap_or_else(|| ch["optimal_spend"].as_f64().unwrap_or(0.0));
            let delta = opt - curr;
            let dpct  = if curr.abs() > 1e-9 { delta / curr * 100.0 } else { 0.0 };
            let sign  = if delta >= 0.0 { "+" } else { "" };
            md.push_str(&format!("| {name} | {curr:.0} | {opt:.0} | {sign}{delta:.0} | {sign}{dpct:.1}% |\n"));
        }
        md.push('\n');
    }
    md.push_str("---\n\n");

    // ── Recommendations ──────────────────────────────────────
    md.push_str("## РЕКОМЕНДАЦИИ\n\n");
    if lift > 5.0 {
        md.push_str(&format!("- [ВЫСОКАЯ] Перераспределить бюджет согласно оптимальному плану - ожидаемый прирост **{lift:+.1}%**\n"));
    } else if lift > 0.0 {
        md.push_str(&format!("- [СРЕДНЯЯ] Рассмотреть корректировку бюджетного распределения - ожидаемый прирост {lift:+.1}%\n"));
    }
    if r_squared < 0.7 {
        md.push_str("- [СРЕДНЯЯ] R² ниже рекомендуемого порога 0.7 - рассмотреть добавление контрольных переменных\n");
    }
    if mqs < 60.0 {
        md.push_str("- [СРЕДНЯЯ] MQS Score ниже 60 - модель требует доработки или дополнительных данных\n");
    }
    if mqs >= 80.0 {
        md.push_str("- [ВЫСОКАЯ] Высокий MQS Score - результаты модели надёжны для принятия решений\n");
    }
    md.push_str(&format!("- [ВЫСОКАЯ] Приоритизировать канал **{top_ch}** - наивысший ROI в миксе\n"));
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
    // Волна 3 (2026-06-20): глоссарий из фронта (SSOT glossary.js, 47 терминов).
    // Option → старые вызовы без поля дают None → fallback на встроенные 11.
    glossary: Option<Value>,
) -> Result<Value, String> {
    info!("econ_export_xlsx: project={project_id}");

    let exports = exports_dir(&project_id)?;
    let date = Local::now().format("%Y-%m-%d").to_string();
    // Tier-1 filename convention per Standards/04_XLSX_STANDARD §file-naming.
    // client_name derived from project_id until pipeline surfaces a stable
    // display name in model_data.meta (TBD v1.0.12).
    let slug = sanitize_slug(&project_id);
    let filename = if slug.is_empty() {
        // Fallback for edge cases (empty/all-non-alpha project_id).
        let ts = Local::now().format("%Y%m%d_%H%M%S");
        format!("mmm_report_{ts}.xlsx")
    } else {
        let version = detect_version(&exports, &slug);
        format!("Aurora_Econometrica_{slug}_Model_{date}_v{version:02}.xlsx")
    };
    let path = exports.join(&filename);

    // Сценарии - опциональные. Если папки нет / JSON невалиден - пустой vec,
    // лист «Сценарии» просто не добавится.
    let scenarios = read_scenarios(&project_id);

    build_xlsx(&model_data, &decompose_data, &optimize_data, &scenarios, &project_id, &path, glossary.as_ref())?;

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

/// Сохранить байты (напр. синтетический пример xlsx, переданный фронтом через
/// fetch+arrayBuffer) в выбранный пользователем путь. Атомарная запись: tmp+rename,
/// прерванная запись не оставит битый файл. Возвращает финальный путь.
/// Фикс 2026-06-07: `<a download>` не работает в WebView2 → нативный save-dialog
/// на фронте даёт output_path, эта команда пишет файл.
#[tauri::command]
pub fn save_sample_file(output_path: String, contents: Vec<u8>) -> Result<String, String> {
    let out = PathBuf::from(&output_path);
    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("создать папку: {e}"))?;
    }
    let tmp = out.with_extension("xlsx.tmp");
    if tmp.exists() {
        let _ = std::fs::remove_file(&tmp);
    }
    std::fs::write(&tmp, &contents).map_err(|e| format!("запись: {e}"))?;
    std::fs::rename(&tmp, &out).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("переименование: {e}")
    })?;
    Ok(output_path)
}

/// Открыть проводник с выделением файла (кнопка «Открыть папку» после сохранения).
#[tauri::command]
pub fn reveal_path(path: String) -> Result<(), String> {
    let p = PathBuf::from(&path);
    if !p.exists() {
        return Err("Файл не найден".to_string());
    }
    #[cfg(windows)]
    {
        std::process::Command::new("explorer")
            .arg("/select,")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Не удалось открыть папку: {e}"))?;
    }
    #[cfg(not(windows))]
    {
        let dir = p.parent().unwrap_or(&p);
        std::process::Command::new("xdg-open")
            .arg(dir)
            .spawn()
            .map_err(|e| format!("Не удалось открыть папку: {e}"))?;
    }
    Ok(())
}

// ── XLSX builder ──────────────────────────────────────────────────────────────

/// Колонки листа «Динамика по периодам» (аудит #12, INV-50).
///
/// Источник — канонический `decomposition_series` (baseline_reduced + media +
/// вынесенные signed/holiday факторы), ТОТ ЖЕ набор, что в программе и остальных
/// отчётах. Fallback на `time_series` (baseline + media) для legacy-проектов без
/// поля. Возвращает (даты, [(заголовок, значения по периодам)]).
fn decomposition_timeline_columns(decompose: &Value) -> (Vec<String>, Vec<(String, Vec<f64>)>) {
    let dates: Vec<String> = decompose
        .get("decomposition_series").and_then(|d| d.get("dates")).and_then(|d| d.as_array())
        .or_else(|| decompose.get("time_series").and_then(|ts| ts.get("dates")).and_then(|d| d.as_array()))
        .map(|arr| arr.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect())
        .unwrap_or_default();

    let columns: Vec<(String, Vec<f64>)> = if let Some(series) = decompose
        .get("decomposition_series").and_then(|d| d.get("series")).and_then(|s| s.as_array())
    {
        series.iter().filter_map(|s| {
            let role = s.get("role").and_then(|r| r.as_str()).unwrap_or("");
            let header = if role == "baseline" {
                "Baseline".to_string()
            } else {
                s.get("name").and_then(|n| n.as_str())?.to_string()
            };
            let data = s.get("data").and_then(|d| d.as_array())
                .map(|a| a.iter().map(|x| x.as_f64().unwrap_or(0.0)).collect::<Vec<f64>>())
                .unwrap_or_default();
            Some((header, data))
        }).collect()
    } else if let Some(ts) = decompose.get("time_series") {
        // Legacy: baseline + media channels (старое поведение).
        let mut cols: Vec<(String, Vec<f64>)> = Vec::new();
        if let Some(bl) = ts.get("baseline").and_then(|b| b.as_array()) {
            cols.push(("Baseline".to_string(),
                bl.iter().map(|x| x.as_f64().unwrap_or(0.0)).collect()));
        }
        let channel_order: Vec<String> = decompose["channels"].as_array()
            .map(|arr| arr.iter().filter_map(|c| c["name"].as_str().map(|s| s.to_string())).collect())
            .unwrap_or_default();
        if let Some(ch_map) = ts.get("channels").and_then(|c| c.as_object()) {
            for name in &channel_order {
                let data = ch_map.get(name).and_then(|a| a.as_array())
                    .map(|a| a.iter().map(|x| x.as_f64().unwrap_or(0.0)).collect::<Vec<f64>>())
                    .unwrap_or_default();
                cols.push((name.clone(), data));
            }
        }
        cols
    } else {
        Vec::new()
    };

    (dates, columns)
}

fn build_xlsx(
    model: &Value,
    decompose: &Value,
    optimize: &Value,
    scenarios: &[Value],
    project_id: &str,
    path: &PathBuf,
    // Волна 3 (2026-06-20): глоссарий из фронта (SSOT glossary.js, 47 терминов);
    // None → fallback на встроенные 11.
    glossary: Option<&Value>,
) -> Result<(), String> {
    use rust_xlsxwriter::{Chart, ChartType, Color, ConditionalFormatCell, ConditionalFormatCellRule, Formula, Image};

    // ── Tier-1 brand tokens (mirror Standards/tokens/tokens.json) ────────────
    // Keep in sync with const block; duplicated here (not imported) because
    // cross-crate SSOT for Rust tokens is out of scope for v1.0.11 (A2 defer).
    const DEEP_100: u32 = 0x0A1628;
    const DEEP_80:  u32 = 0x1E3A5F; // header bg
    const DEEP_60:  u32 = 0x547090;
    const DEEP_20:  u32 = 0xD6DFE8;
    #[allow(dead_code)] const GOLD: u32 = 0xC5A46D;
    const GO:       u32 = 0x269924; // ROI ≥ 2 / positive delta
    const STOP:     u32 = 0xED2124; // ROI < 1
    const BERRY:    u32 = 0xD3086F; // negative delta
    const WHITE:    u32 = 0xFFFFFF;

    let mut wb = Workbook::new();

    // ── Workbook metadata (DocProperties) ────────────────────────────────────
    // Visible in Excel: File → Info → Properties.
    // client_label derived from project_id until pipeline surfaces a stable
    // display name in model_data.meta (TBD v1.0.12). Empty project_id falls
    // back to "Client" so DocProperties title is never malformed.
    let client_label = if project_id.is_empty() { "Client" } else { project_id };
    let props = DocProperties::new()
        .set_title(format!("Aurora AI MMM - {client_label}"))
        .set_subject("Marketing Mix Model - аналитический отчёт")
        .set_author("Aurora AI Econometrica")
        .set_company("Aurora AI")
        .set_category("Econometrics")
        .set_keywords("MMM, marketing-mix, ROI, optimization")
        .set_comment(format!(
            "Generated by Aurora AI Econometrica v1.0.11, project {project_id}"
        ));
    wb.set_properties(&props);

    // ── Format library ────────────────────────────────────────────────────────
    // base_fmt seeds every derived Format via .clone() - column-level formats
    // in rust_xlsxwriter do NOT cascade to cells with explicit format, so all
    // font-family/size inheritance must happen at Format construction time.
    // Inter font matches HTML/PPTX hybrid design system (fallback to Aptos
    // for older Office installs without Inter - Excel auto-substitutes).
    let base_fmt = Format::new().set_font_name("Inter").set_font_size(10);
    let bold = base_fmt.clone().set_bold();

    // Brand header форматы - applied на Row 0+1 каждого листа.
    // Row 0: AURORA AI wordmark (gold) | sheet title (Lora) | Конфиденциально (right)
    // Row 1: solid gold stripe (3px)
    let brand_aurora_fmt = Format::new()
        .set_font_name("Inter")
        .set_font_size(10)
        .set_bold()
        .set_font_color(Color::RGB(GOLD))
        .set_align(FormatAlign::Center)
        .set_align(FormatAlign::VerticalCenter);
    let brand_title_fmt = Format::new()
        .set_font_name("Lora")
        .set_font_size(13)
        .set_font_color(Color::RGB(DEEP_100))
        .set_align(FormatAlign::Center)
        .set_align(FormatAlign::VerticalCenter);
    let brand_conf_fmt = Format::new()
        .set_font_name("Inter")
        .set_font_size(9)
        .set_italic()
        .set_font_color(Color::RGB(DEEP_60))
        .set_align(FormatAlign::Center)
        .set_align(FormatAlign::VerticalCenter);
    let brand_stripe_fmt = Format::new().set_background_color(Color::RGB(GOLD));

    // Helper closure: применяет brand header (Row 0+1) на любом листе.
    // Row 0: AURORA AI (left) | sheet_title (center) | Конфиденциально (right)
    // Row 1: solid gold stripe across `stripe_cols` cols (varies per sheet
    // per XLSX_reference: Спецификация=4, Cover=3, ExecSummary=8, default=6).
    // Row 0 height = 21.75pt; Row 1 height = 3.0pt (per reference).
    let write_brand_header = |ws: &mut rust_xlsxwriter::Worksheet, sheet_title: &str, stripe_cols: u16| -> Result<(), String> {
        ws.write_with_format(0, 0, "AURORA AI", &brand_aurora_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(0, 1, sheet_title, &brand_title_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(0, 2, "Конфиденциально", &brand_conf_fmt).map_err(|e| format!("{e}"))?;
        for col in 0..stripe_cols {
            ws.write_with_format(1, col, "", &brand_stripe_fmt).map_err(|e| format!("{e}"))?;
        }
        ws.set_row_height(0, 21.75).map_err(|e| format!("{e}"))?;
        ws.set_row_height(1, 3.0).map_err(|e| format!("{e}"))?;
        Ok(())
    };
    // header_fmt: navy bg + white text + gold underline (hybrid signature combo).
    let header_fmt = base_fmt.clone()
        .set_bold()
        .set_font_size(11)
        .set_background_color(Color::RGB(DEEP_80))
        .set_font_color(Color::RGB(WHITE))
        .set_align(FormatAlign::Center)
        .set_align(FormatAlign::VerticalCenter)
        .set_border_bottom(FormatBorder::Medium)
        .set_border_bottom_color(Color::RGB(GOLD));
    #[allow(dead_code)]
    let _subheader_fmt = base_fmt.clone()
        .set_italic()
        .set_font_size(9)
        .set_font_color(Color::RGB(DEEP_60));
    // Per XLSX_reference: numeric data cells are horizontally + vertically
    // centered. Text-label cells (col A on most sheets) stay default left.
    let pct_fmt = base_fmt.clone()
        .set_num_format("0.0%")
        .set_align(FormatAlign::Center)
        .set_align(FormatAlign::VerticalCenter);
    let num_fmt = base_fmt.clone()
        .set_num_format("#,##0")
        .set_align(FormatAlign::Center)
        .set_align(FormatAlign::VerticalCenter);
    #[allow(dead_code)]
    let _num_neg_fmt = base_fmt.clone().set_num_format("#,##0;(#,##0)");
    let roi_fmt = base_fmt.clone()
        .set_num_format("0.00\"x\"")
        .set_align(FormatAlign::Center)
        .set_align(FormatAlign::VerticalCenter);

    // ── Sheet 0: Cover ───────────────────────────────────────────────────────
    // Standards/04 §structural-elements: MERGE FORBIDDEN. Use
    // FormatAlign::CenterAcross so Excel visually centers across empty
    // cells A1:D1 without an actual merge.
    // Internal hyperlinks to sheets deferred to v1.0.12 - tab bar already
    // provides navigation; TOC here gives content overview.
    {
        let ws = wb.add_worksheet();
        ws.set_name("Обзор").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(GOLD));

        // Row 0: Aurora AI kicker (matches XLSX_reference - 3-col centerAcross + vertical center).
        let kicker_fmt = Format::new()
            .set_font_name("Inter")
            .set_font_size(11)
            .set_bold()
            .set_font_color(Color::RGB(GOLD))
            .set_align(FormatAlign::CenterAcross)
            .set_align(FormatAlign::VerticalCenter);
        ws.write_with_format(0, 0, "AURORA AI", &kicker_fmt)
            .map_err(|e| format!("{e}"))?;
        for col in 1..3u16 {
            ws.write_with_format(0, col, "", &kicker_fmt).map_err(|e| format!("{e}"))?;
        }
        ws.set_row_height(0, 25.5).map_err(|e| format!("{e}"))?;

        // Row 1: main hero title - Lora 28pt centerAcross 3 cols + vertical center.
        let title_fmt = Format::new()
            .set_font_name("Lora")
            .set_font_size(28)
            .set_font_color(Color::RGB(DEEP_100))
            .set_align(FormatAlign::CenterAcross)
            .set_align(FormatAlign::VerticalCenter);
        // 5d (audit-iter 2026-05-04): leading spaces чтобы title не overlap'ил logo
        // в верхнем левом (col=0 row=0). Customer-edited reference XLSX showed
        // 10-12 spaces leading. Logo width ≈ 70px ≈ 10 char widths в default font.
        ws.write_with_format(1, 0, "          Marketing Mix Model Report", &title_fmt)
            .map_err(|e| format!("{e}"))?;
        for col in 1..3u16 {
            ws.write_with_format(1, col, "", &title_fmt).map_err(|e| format!("{e}"))?;
        }
        ws.set_row_height(1, 36.0).map_err(|e| format!("{e}"))?;

        // 5d (2026-05-04 + audit-iter 2026-05-04): Aurora full gold-accent sigil PNG
        // в верхнем левом углу Обзор sheet (column A, rows 1-2 area). Customer
        // reference: customer-edited XLSX show image at col=0 row=0 with small offset,
        // spans A1-A2 height. Replaces previous top-right placement.
        // Compile-time embedding через include_bytes! - no runtime IO.
        let brand_png_bytes = include_bytes!("../../assets/brand_mark.png");
        match Image::new_from_buffer(brand_png_bytes) {
            Ok(brand_img) => {
                // 1024×1024 source → ≈ 70×70 px display (covers ~A1:A2 vertical span).
                let scaled = brand_img.set_scale_width(0.07).set_scale_height(0.07);
                if let Err(e) = ws.insert_image_with_offset(0, 0, &scaled, 22, 14) {
                    log::warn!("XLSX brand mark insert failed: {e}");
                }
            }
            Err(e) => {
                log::warn!("XLSX brand mark image decode failed: {e}");
            }
        }

        // Row 2: Gold accent stripe - 3 cols (per reference).
        let stripe_fmt = Format::new().set_background_color(Color::RGB(GOLD));
        for col in 0..3u16 {
            ws.write_with_format(2, col, "", &stripe_fmt).map_err(|e| format!("{e}"))?;
        }
        ws.set_row_height(2, 3.95).map_err(|e| format!("{e}"))?;

        let label_fmt = base_fmt.clone().set_bold().set_font_color(Color::RGB(DEEP_60));
        let value_fmt = base_fmt.clone().set_font_color(Color::RGB(DEEP_100));

        let today = Local::now().format("%d.%m.%Y").to_string();
        // Волна 3 (2026-06-20): версия модели — РЕАЛЬНАЯ из прогона (прежде зашито
        // «v1.0.13», устаревшее; реальная model_version = напр. 1.2). Источник —
        // decompose.model_version (fallback model.model_version), «—» если нет.
        let model_ver = decompose["model_version"].as_str()
            .or_else(|| model["model_version"].as_str())
            .map(|v| format!("v{v}"))
            .unwrap_or_else(|| "—".to_string());
        // Волна 3 (2026-06-20): метка режима анализа + типа KPI (контекст метрик).
        let mode_lbl = analysis_mode_label(&decompose["derived_mode"].as_str().unwrap_or("roi").to_lowercase());
        let kind_lbl = kpi_kind_label(&decompose["kpi_kind"].as_str().unwrap_or("monetary").to_lowercase());
        let mode_meta = if kind_lbl.is_empty() { mode_lbl.to_string() }
                        else { format!("{mode_lbl} · KPI: {kind_lbl}") };
        let meta_rows: &[(&str, String)] = &[
            ("Подготовлено для:", client_label.to_string()),
            ("Проект:",           project_id.to_string()),
            ("Дата:",             today),
            ("Версия модели:",    model_ver),
            ("Режим анализа:",    mode_meta),
            ("Гриф:",             "Конфиденциально".to_string()),
        ];
        for (i, (k, v)) in meta_rows.iter().enumerate() {
            let row = (i + 4) as u32; // start at row 5 (after kicker/title/stripe + spacer)
            ws.write_with_format(row, 0, *k, &label_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, v.as_str(), &value_fmt).map_err(|e| format!("{e}"))?;
        }

        // Section heading "Содержание" at row 11 (was 9 - shifted +2 for kicker)
        let toc_heading_fmt = base_fmt.clone()
            .set_bold()
            .set_font_size(12)
            .set_background_color(Color::RGB(DEEP_80))
            .set_font_color(Color::RGB(WHITE));
        ws.write_with_format(11, 0, "Содержание", &toc_heading_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(11, 1, "", &toc_heading_fmt).map_err(|e| format!("{e}"))?;

        let toc: &[(&str, &str)] = &[
            ("Executive Summary", "Ключевые метрики: MQS, R², MAPE, прирост, бюджет"),
            ("Спецификация",      "Формула Bayesian MMM и априоры"),
            ("Декомпозиция",      "Вклад каналов в продажи"),
            ("ROI каналов",       "ROI по каналам с CI"),
            ("Spend vs Effect",   "Доля бюджета vs доля эффекта"),
            ("Динамика",          "Еженедельная декомпозиция"),
            ("Оптимизация",       "Текущая vs оптимальная аллокация"),
            ("Сценарии",          "Сравнение сохранённых сценариев"),
            ("Данные",            "Полный временной ряд для аналитика"),
            ("Глоссарий",         "Определения терминов"),
        ];
        let sheet_fmt = base_fmt.clone().set_bold().set_font_color(Color::RGB(DEEP_100));
        let desc_fmt  = base_fmt.clone().set_font_color(Color::RGB(DEEP_60));
        for (i, (sheet, desc)) in toc.iter().enumerate() {
            let row = (10 + i) as u32;
            ws.write_with_format(row, 0, *sheet, &sheet_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, *desc,  &desc_fmt).map_err(|e| format!("{e}"))?;
        }

        // Widths from XLSX_reference.xlsx - A=22.14, B=41.29, C=21.86
        ws.set_column_width(0, 22.14).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 41.29).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 21.86).map_err(|e| format!("{e}"))?;
    }
    let _ = DEEP_20; // retained for Commit B2 zebra striping use

    // ── Sheet 1: Executive Summary ──────────────────────────
    {
        let ws = wb.add_worksheet();
        ws.set_name("Executive Summary").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(DEEP_80));
        apply_base_cols(ws, &base_fmt)?;
        apply_print_setup(ws, "Executive Summary")?;

        let mqs       = model["diagnostics"]["mqs"]["score"].as_f64().unwrap_or(0.0);
        let mqs_label = model["diagnostics"]["mqs"]["tier_label"].as_str().unwrap_or("N/A");
        let r_sq      = diag_metric(model, "r_squared", "r_squared");
        let mape      = diag_metric(model, "mape_pct", "mape");
        let r_hat     = model["diagnostics"]["metrics"]["r_hat_max"]
            .as_f64()
            .or_else(|| model["diagnostics"]["r_hat"].as_f64());
        let lift      = optimize["expected_lift_pct"].as_f64().unwrap_or(0.0);
        // 5c (2026-05-04) FIX: total_budget - это native sum (mixed units TRPs+₽
        // = арифметический мусор). Use total_current_money - money equivalent
        // = sum of channel spend × unit_cost (matches UI Block A «Текущий бюджет»).
        let budget = optimize["total_current_money"].as_f64()
            .or_else(|| optimize["total_budget_money"].as_f64())
            .or_else(|| {
                // Legacy fallback: aggregate from decompose channels (.spend = money)
                decompose["channels"].as_array().map(|chs| {
                    chs.iter().map(|c| c["spend"].as_f64().unwrap_or(0.0)).sum()
                })
            })
            .unwrap_or(0.0);

        write_brand_header(ws, "Executive Summary", 8)?;

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
        ws.write(9, 0, format!("MQS Tier: {mqs_label}")).map_err(|e| format!("{e}"))?;
        if let Some(rh) = r_hat {
            ws.write(10, 0, format!("R-hat (сходимость): {rh:.4}")).map_err(|e| format!("{e}"))?;
        }
        // INV-50 F-DELIVERABLE-1 (2026-06-07): честная оговорка о тонких данных.
        // Прежде клиентский XLSX показывал «MQS 70 Хорошо» без предупреждения,
        // хотя backend применил data-thinness cap. Формулировка ЗЕРКАЛИТ
        // utils/diagnostics.py::format_thinness_caveat (Python SSOT) — Rust не
        // импортирует Python, синхрон держим вручную (тест сверяет). Тон по
        // McElreath (2026-06-20): тонкие данные ≠ «артефакт переобучения»; priors
        // регуляризуют, интервалы честно широкие.
        let thinness_cap = model["diagnostics"]["mqs"]["thinness_cap"].as_f64();
        let ratio_eff = model["diagnostics"]["metrics"]["ratio"].as_f64();
        if let (Some(_cap), Some(ratio)) = (thinness_cap, ratio_eff) {
            let caveat = if ratio < 2.0 {
                format!("⚠ Данных мало (Ratio {ratio:.1}:1) — их совсем немного: модель сильно опирается на априорные отраслевые знания, оценки ориентировочные. Доверяйте доверительным интервалам, а не точечным цифрам.")
            } else {
                format!("⚠ Данных мало (Ratio {ratio:.1}:1 < 4:1): модель намеренно сдержана — опирается на априорные отраслевые знания, поэтому доверительные интервалы широкие. Это честная неопределённость, а не ошибка; с ростом данных интервалы сузятся.")
            };
            ws.write(11, 0, caveat).map_err(|e| format!("{e}"))?;
        }
        // Волна 1 пункт 2 (2026-06-20): плашка надёжности модели на строке 12 (под
        // thinness caveat). caveat_text VERBATIM из optimization.json (SSOT
        // optimizer_honesty, INV-50) — тот же текст, что в UI/HTML/PPTX/MD. Rust
        // читает optimize JSON напрямую (мимо Python-моста) → зеркало пути.
        {
            let mr_verdict = optimize["model_reliability"]["verdict"].as_str().unwrap_or("").to_lowercase();
            let mr_label = reliability_label(&mr_verdict);
            let mr_caveat = optimize["model_reliability"]["caveat_text"].as_str().unwrap_or("");
            if !mr_label.is_empty() && !mr_caveat.is_empty() {
                ws.write(12, 0, format!("⚠ {mr_label}. {mr_caveat}")).map_err(|e| format!("{e}"))?;
            }
        }

        // Widths from XLSX_reference.xlsx - A:C = 26.43
        ws.set_column_width(0, 26.43).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 26.43).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 26.43).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 1.5: Спецификация модели ──────────────────────
    {
        let ws = wb.add_worksheet();
        ws.set_name("Спецификация").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(DEEP_80));
        apply_base_cols(ws, &base_fmt)?;
        apply_print_setup(ws, "Спецификация")?;

        let spec = model_spec_value(model);
        let title = spec["title"].as_str().unwrap_or("Спецификация модели");
        let subtitle = spec["subtitle"].as_str().unwrap_or("");
        let engine = spec["engine"].as_str().unwrap_or("");
        let formula = spec["formula"].as_str().unwrap_or("");
        let normalization = spec["normalization"].as_str().unwrap_or("");

        // Brand header (4-col stripe per XLSX_reference)
        write_brand_header(ws, "Спецификация модели", 4)?;
        let _ = title; // brand title overrides
        if !engine.is_empty() && !subtitle.is_empty() {
            ws.write(2, 0, format!("{subtitle} · Движок: {engine}")).map_err(|e| format!("{e}"))?;
        } else if !subtitle.is_empty() {
            ws.write(2, 0, subtitle).map_err(|e| format!("{e}"))?;
        } else if !engine.is_empty() {
            ws.write(2, 0, format!("Движок: {engine}")).map_err(|e| format!("{e}"))?;
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
                ws.write(row, 1, format!("{chains} / {draws} / {tune}")).map_err(|e| format!("{e}"))?;
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

        // Widths - Спецификация (B = 4.81 cm = 26.0; C = 6.80 cm ≈ 36.72 char, per Антон)
        ws.set_column_width(0, 24.57).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 26.00).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 36.72).map_err(|e| format!("{e}"))?;
        ws.set_column_width(3, 67.86).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 2: Декомпозиция + waterfall chart ─────────────
    // Волна 2 фикс (2026-06-20): waterfall = ОБЪЕКТ {labels, values, types}
    // (параллельные массивы; types: baseline|channel|total). Прежде Rust ждал
    // массив объектов [{category,value}] → .as_array()=None → лист «Декомпозиция»
    // МОЛЧА терялся в XLSX (положительная канарейка: лист обязан существовать).
    if let Some(wf) = decompose["waterfall"].as_object() {
        let labels: Vec<String> = wf.get("labels").and_then(|v| v.as_array())
            .map(|a| a.iter().map(|x| clean_label(x.as_str().unwrap_or("-"))).collect())
            .unwrap_or_default();
        let values: Vec<f64> = wf.get("values").and_then(|v| v.as_array())
            .map(|a| a.iter().map(|x| x.as_f64().unwrap_or(0.0)).collect())
            .unwrap_or_default();
        let types: Vec<String> = wf.get("types").and_then(|v| v.as_array())
            .map(|a| a.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect())
            .unwrap_or_default();

        // Аудит 2026-06-20: требуем равенство ВСЕХ ТРЁХ длин (прежде проверялись
        // только labels==values → при битом types: values[i] panic / zip молча
        // терял строки). Неравенство → лист пропускается безопасно (как не-объект).
        if !labels.is_empty() && labels.len() == values.len() && labels.len() == types.len() {
            let ws = wb.add_worksheet();
            ws.set_name("Декомпозиция").map_err(|e| format!("{e}"))?;
            ws.set_tab_color(Color::RGB(DEEP_80));
            apply_base_cols(ws, &base_fmt)?;
            apply_print_setup(ws, "Декомпозиция")?;
            write_brand_header(ws, "Декомпозиция", 6)?;

            // Header row offset by 2 (brand header occupies rows 0+1).
            ws.write_with_format(2, 0, "Категория",  &header_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(2, 1, "Вклад, ₽",    &header_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(2, 2, "% от общего", &header_fmt).map_err(|e| format!("{e}"))?;

            // Знаменатель % = элемент типа 'total' (если есть), иначе сумма не-total.
            let total_val = types.iter().position(|t| t == "total")
                .and_then(|i| values.get(i).copied())  // .get вместо [i] — без panic при рассинхроне
                .unwrap_or_else(|| values.iter().zip(types.iter())
                    .filter(|(_, t)| t.as_str() != "total").map(|(v, _)| *v).sum());

            // Data rows = всё кроме 'total' (total выносим в ИТОГО ниже).
            let mut row = 3u32;
            for ((lab, val), ty) in labels.iter().zip(values.iter()).zip(types.iter()) {
                if ty == "total" { continue; }
                ws.write(row, 0, lab.as_str()).map_err(|e| format!("{e}"))?;
                ws.write_with_format(row, 1, *val, &num_fmt).map_err(|e| format!("{e}"))?;
                let pct = if total_val != 0.0 { val / total_val } else { 0.0 };
                ws.write_with_format(row, 2, pct, &pct_fmt).map_err(|e| format!("{e}"))?;
                row += 1;
            }
            let last_data_row = row - 1; // zero-based индекс последней data-строки
            // ИТОГО — значение из waterfall.total (точнее, чем SUM: baseline+channels
            // может расходиться с total на округление).
            ws.write_with_format(row, 0, "ИТОГО", &bold).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, total_val, &bold).map_err(|e| format!("{e}"))?;

            // Bar chart — только data-строки (3..=last_data_row), значения col B.
            // Аудит 2026-06-20: guard last_data_row >= 3 — иначе при waterfall без
            // data-строк (все элементы 'total') диапазон (3..2) невалиден.
            if last_data_row >= 3 {
                let mut chart = Chart::new(ChartType::Bar);
                chart.add_series()
                    .set_categories(("Декомпозиция", 3, 0, last_data_row, 0))
                    .set_values(("Декомпозиция", 3, 1, last_data_row, 1))
                    .set_name("Вклад в продажи");
                chart.set_style(12); // Excel built-in style closest to Aurora hybrid (gradient navy/gold)
                chart.set_width(567).set_height(283); // matches XLSX_reference (15×7.5 cm)
                chart.title().set_name("Декомпозиция продаж");
                ws.insert_chart(row + 2, 0, &chart).map_err(|e| format!("{e}"))?;
            }

            // Widths matching reference style
            ws.set_column_width(0, 35.71).map_err(|e| format!("{e}"))?;
            ws.set_column_width(1, 24.57).map_err(|e| format!("{e}"))?;
            ws.set_column_width(2, 18.0).map_err(|e| format!("{e}"))?;
        }
    }

    // ── Sheet 3: ROI каналов + chart + conditional formatting ─
    if let Some(chs) = decompose["channels"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("ROI каналов").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(GOLD));
        apply_base_cols(ws, &base_fmt)?;
        apply_print_setup(ws, "ROI каналов")?;
        write_brand_header(ws, "ROI каналов", 6)?;

        let headers = ["Канал", "Расход, ₽", "Вклад, ₽", "ROI", "CI нижний", "CI верхний", "Вердикт"];
        for (c, h) in headers.iter().enumerate() {
            ws.write_with_format(2, c as u16, *h, &header_fmt).map_err(|e| format!("{e}"))?;
        }
        // Волна 1 пункт 3 (2026-06-20): honesty-смягчение вердикта (решение 2a) —
        // verdict_display несёт рус + «(предв.)» при не-reliable модели.
        let mr_v = optimize["model_reliability"]["verdict"].as_str().unwrap_or("").to_lowercase();

        // 5c (2026-05-04) FIX: CI fields live in decompose.channels[i].roi_ci_low/high,
        // NOT в model["channelParams"] (modeler output не содержит CI). Pre-fix Rust
        // читал из wrong source с typo (ci_lower vs ci_low) → CI=0 для всех каналов.
        for (i, ch) in chs.iter().enumerate() {
            let row = (i + 3) as u32;
            let name = ch["name"].as_str().unwrap_or("-");
            let spend = ch["spend"].as_f64().unwrap_or(0.0);
            let contrib = ch["contribution"].as_f64().unwrap_or(0.0);
            let verdict = ch["verdict"].as_str().unwrap_or("-");
            let ci_lo = ch["roi_ci_low"].as_f64().unwrap_or(0.0);
            let ci_hi = ch["roi_ci_high"].as_f64().unwrap_or(0.0);

            // Волна 1 Шаг 2: битый ROI (битые единицы / артефакт) не пишем числом —
            // абсурдные 18500× нельзя подавать клиенту как факт (INV-50). Признак —
            // helper roi_unreliable (зеркалит narrative_adapter._roi_unreliable; Python
            // мост сюда не доходит: Rust XLSX читает results JSON напрямую).
            let roi_bad = roi_unreliable(ch);

            ws.write(row, 0, name).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, spend, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, contrib, &num_fmt).map_err(|e| format!("{e}"))?;
            if roi_bad {
                ws.write(row, 3, "н/д*").map_err(|e| format!("{e}"))?;
                ws.write(row, 4, "—").map_err(|e| format!("{e}"))?;
                ws.write(row, 5, "—").map_err(|e| format!("{e}"))?;
            } else {
                let roi = if spend > 0.0 { contrib / spend } else { 0.0 };
                ws.write_with_format(row, 3, roi, &roi_fmt).map_err(|e| format!("{e}"))?;
                ws.write_with_format(row, 4, ci_lo, &roi_fmt).map_err(|e| format!("{e}"))?;
                ws.write_with_format(row, 5, ci_hi, &roi_fmt).map_err(|e| format!("{e}"))?;
            }
            ws.write(row, 6, verdict_display(verdict, &mr_v)).map_err(|e| format!("{e}"))?;
        }
        // Сноска-пояснение «н/д*» (если был хоть один битый ROI-канал).
        if chs.iter().any(roi_unreliable) {
            let note_row = chs.len() as u32 + 4;
            ws.write(note_row, 0, "* ROI н/д — единицы канала требуют проверки (не сопоставим с рублёвыми); сравнивайте по доле вклада.")
                .map_err(|e| format!("{e}"))?;
        }

        // Conditional formatting: ROI > 2 = green, ROI < 1 = red (data rows 3..3+len)
        let first_row = 3u32;
        let last_row = chs.len() as u32 + 2;
        let green_cond = ConditionalFormatCell::new()
            .set_rule(ConditionalFormatCellRule::GreaterThanOrEqualTo(2.0))
            .set_format(Format::new().set_font_color(Color::RGB(GO)));
        let red_cond = ConditionalFormatCell::new()
            .set_rule(ConditionalFormatCellRule::LessThan(1.0))
            .set_format(Format::new().set_font_color(Color::RGB(STOP)));
        ws.add_conditional_format(first_row, 3, last_row, 3, &green_cond).map_err(|e| format!("{e}"))?;
        ws.add_conditional_format(first_row, 3, last_row, 3, &red_cond).map_err(|e| format!("{e}"))?;

        // ROI bar chart
        let mut chart = Chart::new(ChartType::Bar);
        chart.add_series()
            .set_categories(("ROI каналов", first_row, 0, last_row, 0))
            .set_values(("ROI каналов", first_row, 3, last_row, 3))
            .set_name("ROI");
        chart.set_style(12);
        chart.set_width(567).set_height(283); // matches XLSX_reference (15×7.5 cm)
        chart.title().set_name("ROI по каналам");
        ws.insert_chart(last_row + 2, 0, &chart).map_err(|e| format!("{e}"))?;

        // Widths - ROI каналов (A = 4.4 cm ≈ 23.76; C = 3.91 cm; D = 2.2 cm, per Антон)
        ws.set_column_width(0, 23.76).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 36.43).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 21.14).map_err(|e| format!("{e}"))?;
        ws.set_column_width(3, 11.88).map_err(|e| format!("{e}"))?;
        ws.set_column_width(4, 25.29).map_err(|e| format!("{e}"))?;
        ws.set_column_width(5, 25.29).map_err(|e| format!("{e}"))?;
        ws.set_column_width(6, 25.29).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 4: Share of Spend vs Effect (NEW) ─────────────
    if let Some(chs) = decompose["channels"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("Spend vs Effect").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(DEEP_80));
        apply_base_cols(ws, &base_fmt)?;
        apply_print_setup(ws, "Spend vs Effect")?;
        write_brand_header(ws, "Бюджет vs Эффект", 6)?;

        let headers = ["Канал", "Расход, ₽", "% бюджета", "Вклад, ₽", "% эффекта", "Efficiency"];
        for (c, h) in headers.iter().enumerate() {
            ws.write_with_format(2, c as u16, *h, &header_fmt).map_err(|e| format!("{e}"))?;
        }

        let total_spend: f64 = chs.iter().map(|c| c["spend"].as_f64().unwrap_or(0.0)).sum();
        let total_contrib: f64 = chs.iter().map(|c| c["contribution"].as_f64().unwrap_or(0.0)).sum();

        for (i, ch) in chs.iter().enumerate() {
            let row = (i + 3) as u32;
            let name = ch["name"].as_str().unwrap_or("-");
            let spend = ch["spend"].as_f64().unwrap_or(0.0);
            let contrib = ch["contribution"].as_f64().unwrap_or(0.0);
            let spend_pct = if total_spend > 0.0 { spend / total_spend } else { 0.0 };
            let effect_pct = if total_contrib > 0.0 { contrib / total_contrib } else { 0.0 };

            // 5c (2026-05-04) FIX: same formula-result issue. rust_xlsxwriter
            // does not evaluate Excel formulas → cached result=0 на open.
            // Compute Efficiency inline → static value, matches UI display.
            let efficiency = if spend_pct > 1e-9 { effect_pct / spend_pct } else { 0.0 };

            ws.write(row, 0, name).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, spend, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, spend_pct, &pct_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 3, contrib, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 4, effect_pct, &pct_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 5, efficiency, &roi_fmt).map_err(|e| format!("{e}"))?;
        }

        // Clustered bar chart: spend% vs effect% (data rows 3..3+len-1)
        let first_row = 3u32;
        let last_row = chs.len() as u32 + 2;
        let mut chart = Chart::new(ChartType::Column);
        chart.add_series()
            .set_categories(("Spend vs Effect", first_row, 0, last_row, 0))
            .set_values(("Spend vs Effect", first_row, 2, last_row, 2))
            .set_name("% бюджета");
        chart.add_series()
            .set_categories(("Spend vs Effect", first_row, 0, last_row, 0))
            .set_values(("Spend vs Effect", first_row, 4, last_row, 4))
            .set_name("% эффекта");
        chart.set_style(12);
        chart.set_width(567).set_height(283); // matches XLSX_reference (15×7.5 cm)
        chart.title().set_name("Доля бюджета vs Доля эффекта");
        ws.insert_chart(last_row + 2, 0, &chart).map_err(|e| format!("{e}"))?;

        // Widths - Spend vs Effect (A:C = 3.50 cm ≈ 18.90 char, per Антон)
        ws.set_column_width(0, 18.90).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 18.90).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 18.90).map_err(|e| format!("{e}"))?;
        ws.set_column_width(3, 14.71).map_err(|e| format!("{e}"))?;
        ws.set_column_width(4, 20.71).map_err(|e| format!("{e}"))?;
        ws.set_column_width(5, 15.71).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 4.5: Динамика по периодам (stacked area) ──────
    // Аудит #12 (2026-06-07, INV-50): колонки = канонический decomposition_series
    // (baseline_reduced + media + вынесенные signed/holiday факторы), ТОТ ЖЕ набор,
    // что в программе (ChannelTimeline) и остальных отчётах. Fallback на
    // time_series (baseline + media) для legacy-проектов без поля.
    {
        let (dates, columns) = decomposition_timeline_columns(decompose);

        if !dates.is_empty() && !columns.is_empty() {
            let ws = wb.add_worksheet();
            ws.set_name("Динамика").map_err(|e| format!("{e}"))?;
            ws.set_tab_color(Color::RGB(DEEP_80));
            apply_base_cols(ws, &base_fmt)?;
            apply_print_setup(ws, "Динамика")?;
            write_brand_header(ws, "Динамика по периодам", 6)?;

            // Header row at row 2
            ws.write_with_format(2, 0, "Дата", &header_fmt).map_err(|e| format!("{e}"))?;
            for (j, (header, _)) in columns.iter().enumerate() {
                ws.write_with_format(2, (j + 1) as u16, header.as_str(), &header_fmt)
                    .map_err(|e| format!("{e}"))?;
            }
            let last_col = columns.len() as u16; // индекс последней колонки данных

            // Data rows starting at row 3
            let first_data_row = 3u32;
            let n_periods = dates.len() as u32;
            let last_data_row = first_data_row + n_periods - 1;
            for (i, d) in dates.iter().enumerate() {
                let row = first_data_row + i as u32;
                ws.write(row, 0, d.as_str()).map_err(|e| format!("{e}"))?;
                for (j, (_, data)) in columns.iter().enumerate() {
                    let v = data.get(i).copied().unwrap_or(0.0);
                    ws.write_with_format(row, (j + 1) as u16, v, &num_fmt).map_err(|e| format!("{e}"))?;
                }
            }

            // Stacked area chart
            let mut chart = Chart::new(ChartType::AreaStacked);
            for c in 1..=last_col {
                chart.add_series()
                    .set_categories(("Динамика", first_data_row, 0, last_data_row, 0))
                    .set_values(("Динамика", first_data_row, c, last_data_row, c))
                    .set_name(("Динамика", 2, c));
            }
            chart.set_style(12);
            chart.set_width(567).set_height(283); // matches XLSX_reference (15×7.5 cm)
            chart.title().set_name("Декомпозиция продаж по периодам");
            let chart_anchor_row = last_data_row + 2;
            ws.insert_chart(chart_anchor_row, 0, &chart).map_err(|e| format!("{e}"))?;

            // Widths - Динамика (A = 2.5; B = 2.68; C = 2.44 cm, per Антон)
            ws.set_column_width(0, 13.5).map_err(|e| format!("{e}"))?;
            if last_col >= 1 {
                ws.set_column_width(1, 14.47).map_err(|e| format!("{e}"))?;
            }
            if last_col >= 2 {
                ws.set_column_width(2, 13.18).map_err(|e| format!("{e}"))?;
            }
            for c in 3..=last_col {
                ws.set_column_width(c, 39.29).map_err(|e| format!("{e}"))?;
            }
        }
    }

    // ── Sheet 5: Оптимизация + chart + formulas ─────────────
    if let Some(opt_chs) = optimize["channels"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("Оптимизация").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(GOLD));
        apply_base_cols(ws, &base_fmt)?;
        apply_print_setup(ws, "Оптимизация")?;
        write_brand_header(ws, "Оптимизация бюджета", 6)?;

        let headers = ["Канал", "Текущий, ₽", "Оптимальный, ₽", "Δ, ₽", "Δ %", "Текущий ROI"];
        for (c, h) in headers.iter().enumerate() {
            ws.write_with_format(2, c as u16, *h, &header_fmt).map_err(|e| format!("{e}"))?;
        }

        // 5c (2026-05-04) FIX: pre-fix Rust read native fields (current_spend,
        // optimal_spend) → mixed units (TRPs + ₽) под column header «₽» = lying.
        // Now: read money-axis fields (current_spend_money, optimal_spend_money)
        // что matches UI Block B display + sheet header semantics.
        // Δ formulas were written without computed result → Excel showed 0 для всех.
        // Now compute Δ + Δ% inline в Rust → static values, Excel doesn't recalc.
        // Текущий ROI: optimizer не возвращает 'current_roi' field → было 0.0
        // fallback. Now fetch from decompose.channels[name].roi (canonical source).
        // AUDIT 2026-05-04: normalize channel names (trim whitespace) для resilient
        // lookup. Pre-fix: minor inconsistency (trailing space) → silent fallback к
        // ROI=0.0 → customer видит 0.00× для valid channel.
        let normalize_name = |s: &str| s.trim().to_string();
        let decompose_roi_by_name: std::collections::HashMap<String, f64> =
            decompose["channels"].as_array()
                .map(|chs| {
                    chs.iter()
                        .filter_map(|c| {
                            let n = normalize_name(c["name"].as_str()?);
                            let r = c["roi"].as_f64()?;
                            Some((n, r))
                        })
                        .collect()
                })
                .unwrap_or_default();

        for (i, ch) in opt_chs.iter().enumerate() {
            let row = (i + 3) as u32;
            let name = ch["name"].as_str().unwrap_or("-");
            // Prefer money-axis fields (post-2025-04 schema). Fallback к native
            // в legacy pickles без _money suffix variants.
            let curr = ch["current_spend_money"].as_f64()
                .unwrap_or_else(|| ch["current_spend"].as_f64().unwrap_or(0.0));
            let opt = ch["optimal_spend_money"].as_f64()
                .unwrap_or_else(|| ch["optimal_spend"].as_f64().unwrap_or(0.0));
            let delta = opt - curr;
            let delta_pct = if curr.abs() > 1e-9 { delta / curr } else { 0.0 };
            let curr_roi = decompose_roi_by_name.get(&normalize_name(name)).copied().unwrap_or(0.0);

            ws.write(row, 0, name).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, curr, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, opt, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 3, delta, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 4, delta_pct, &pct_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 5, curr_roi, &roi_fmt).map_err(|e| format!("{e}"))?;
        }

        // Conditional formatting on delta columns (data rows 3..3+len-1)
        let first_row = 3u32;
        let last_row = opt_chs.len() as u32 + 2;
        let green_d = ConditionalFormatCell::new()
            .set_rule(ConditionalFormatCellRule::GreaterThan(0.0))
            .set_format(Format::new().set_font_color(Color::RGB(GO)));
        let red_d = ConditionalFormatCell::new()
            .set_rule(ConditionalFormatCellRule::LessThan(0.0))
            .set_format(Format::new().set_font_color(Color::RGB(BERRY)));
        ws.add_conditional_format(first_row, 3, last_row, 3, &green_d).map_err(|e| format!("{e}"))?;
        ws.add_conditional_format(first_row, 3, last_row, 3, &red_d).map_err(|e| format!("{e}"))?;
        ws.add_conditional_format(first_row, 4, last_row, 4, &green_d).map_err(|e| format!("{e}"))?;
        ws.add_conditional_format(first_row, 4, last_row, 4, &red_d).map_err(|e| format!("{e}"))?;

        // Clustered bar: current vs optimal
        let mut chart = Chart::new(ChartType::Column);
        chart.add_series()
            .set_categories(("Оптимизация", first_row, 0, last_row, 0))
            .set_values(("Оптимизация", first_row, 1, last_row, 1))
            .set_name("Текущий");
        chart.add_series()
            .set_categories(("Оптимизация", first_row, 0, last_row, 0))
            .set_values(("Оптимизация", first_row, 2, last_row, 2))
            .set_name("Оптимальный");
        chart.set_style(12);
        chart.set_width(567).set_height(283); // matches XLSX_reference (15×7.5 cm)
        chart.title().set_name("Текущий vs Оптимальный бюджет");
        ws.insert_chart(last_row + 2, 0, &chart).map_err(|e| format!("{e}"))?;

        // 5c (2026-05-04) FIX: same formula-result issue - рrust_xlsxwriter writes
        // formulas with default cached result=0, Excel showed 0+0 для ИТОГО.
        // Compute sums in Rust + write as static values.
        let total_r = last_row + 1;
        let curr_sum: f64 = opt_chs.iter()
            .map(|c| c["current_spend_money"].as_f64()
                .unwrap_or_else(|| c["current_spend"].as_f64().unwrap_or(0.0)))
            .sum();
        let opt_sum: f64 = opt_chs.iter()
            .map(|c| c["optimal_spend_money"].as_f64()
                .unwrap_or_else(|| c["optimal_spend"].as_f64().unwrap_or(0.0)))
            .sum();
        let bold_num = bold.clone()
            .set_num_format("#,##0")
            .set_align(FormatAlign::Center)
            .set_align(FormatAlign::VerticalCenter);
        ws.write_with_format(total_r, 0, "ИТОГО", &bold).map_err(|e| format!("{e}"))?;
        ws.write_with_format(total_r, 1, curr_sum, &bold_num).map_err(|e| format!("{e}"))?;
        ws.write_with_format(total_r, 2, opt_sum, &bold_num).map_err(|e| format!("{e}"))?;

        let lift = optimize["expected_lift_pct"].as_f64().unwrap_or(0.0);
        ws.write(total_r + 1, 0, "Ожидаемый прирост").map_err(|e| format!("{e}"))?;
        ws.write(total_r + 1, 1, format!("{lift:+.1}%")).map_err(|e| format!("{e}"))?;

        // Widths - Оптимизация (A = 5.33; C = 3.57 cm ≈ 19.28, per Антон)
        ws.set_column_width(0, 28.78).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 39.29).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 19.28).map_err(|e| format!("{e}"))?;
        ws.set_column_width(3, 18.43).map_err(|e| format!("{e}"))?;
        ws.set_column_width(4, 18.43).map_err(|e| format!("{e}"))?;
        ws.set_column_width(5, 18.43).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 5.5: Сценарии (if any) ─────────────────────────
    // Метрики × сценарии. Если у всех scenarios есть roas_money - показываем
    // деньги (homogeneous), иначе native (смешанные единицы) с пометкой.
    if !scenarios.is_empty() {
        let ws = wb.add_worksheet();
        ws.set_name("Сценарии").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(DEEP_80));
        apply_base_cols(ws, &base_fmt)?;
        apply_print_setup(ws, "Сценарии")?;
        write_brand_header(ws, "Сценарии бюджета", 6)?;

        let homogeneous_money = scenarios.iter()
            .all(|s| s["totals"]["roas_money"].as_f64().is_some());
        let budget_label = if homogeneous_money { "Бюджет, ₽" } else { "Бюджет (native)" };
        let roas_label = if homogeneous_money { "ROAS, ₽" } else { "ROAS (native)" };
        let spend_field = if homogeneous_money { "total_spend_money" } else { "total_spend" };
        let roas_field = if homogeneous_money { "roas_money" } else { "roas" };

        // Header: Метрика | scenario1 | scenario2 | ... at row 2
        ws.write_with_format(2, 0, "Метрика", &header_fmt).map_err(|e| format!("{e}"))?;
        for (i, s) in scenarios.iter().enumerate() {
            let name = s["scenario_name"].as_str().unwrap_or("-");
            ws.write_with_format(2, (i + 1) as u16, name, &header_fmt).map_err(|e| format!("{e}"))?;
        }

        // Rows starting at 3
        let rows: Vec<(&str, &str, &Format)> = vec![
            ("Прогноз KPI", "predicted_kpi", &num_fmt),
            (budget_label, spend_field, &num_fmt),
            (roas_label, roas_field, &roi_fmt),
        ];
        for (i, (label, field, fmt)) in rows.iter().enumerate() {
            let row = (i + 3) as u32;
            ws.write(row, 0, *label).map_err(|e| format!("{e}"))?;
            for (j, s) in scenarios.iter().enumerate() {
                let v = s["totals"][*field].as_f64().unwrap_or(0.0);
                ws.write_with_format(row, (j + 1) as u16, v, fmt).map_err(|e| format!("{e}"))?;
            }
        }
        let lift_row = (rows.len() + 3) as u32;
        ws.write(lift_row, 0, "Лифт vs baseline").map_err(|e| format!("{e}"))?;
        for (j, s) in scenarios.iter().enumerate() {
            let lift = s["totals"]["lift_pct"].as_f64().unwrap_or(0.0);
            ws.write(lift_row, (j + 1) as u16, format!("+{lift:.1}%")).map_err(|e| format!("{e}"))?;
        }

        // Подсветить зелёным лучший ROAS (ROAS в row offset+2 = 5)
        let roas_row = 5u32; // brand 0+1, header 2, KPI 3, Budget 4, ROAS 5
        let best_idx = scenarios.iter().enumerate()
            .max_by(|(_, a), (_, b)| {
                let ra = a["totals"][roas_field].as_f64().unwrap_or(0.0);
                let rb = b["totals"][roas_field].as_f64().unwrap_or(0.0);
                ra.partial_cmp(&rb).unwrap_or(std::cmp::Ordering::Equal)
            })
            .map(|(i, _)| i);
        if let Some(bi) = best_idx {
            // 5c (2026-05-04) FIX: best_fmt was missing num_format → cell showed
            // raw decimal "2.42" while others "2.42x" (roi_fmt applied). Inherit
            // roi_fmt's "0.00\"x\"" pattern + add bold/green emphasis.
            let best_fmt = base_fmt.clone()
                .set_num_format("0.00\"x\"")
                .set_font_color(Color::RGB(GO))
                .set_bold()
                .set_align(FormatAlign::Center)
                .set_align(FormatAlign::VerticalCenter);
            let v = scenarios[bi]["totals"][roas_field].as_f64().unwrap_or(0.0);
            ws.write_with_format(roas_row, (bi + 1) as u16, v, &best_fmt)
                .map_err(|e| format!("{e}"))?;
        }

        if !homogeneous_money {
            let note_row = (rows.len() + 5) as u32;
            let note_fmt = Format::new()
                .set_font_color(Color::RGB(0xF59E0B))
                .set_italic();
            let note = "⚠ ROAS в native-единицах (TRP/GRP + ₽) - несопоставим между \
                        каналами разных единиц. Укажи CPP в блоке «Проверка» для перевода в ₽.";
            ws.merge_range(
                note_row, 0,
                note_row, scenarios.len() as u16,
                note, &note_fmt
            ).map_err(|e| format!("{e}"))?;
        }

        ws.autofit();
    }

    // ── Sheet: Данные (сырой time-series для графиков) ───────
    {
        let ws = wb.add_worksheet();
        ws.set_name("Данные").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(DEEP_80));
        apply_base_cols(ws, &base_fmt)?;
        apply_print_setup(ws, "Данные")?;
        write_brand_header(ws, "Сырые данные · time-series", 6)?;

        let ts = &decompose["time_series"];
        let dates = ts["dates"].as_array().cloned().unwrap_or_default();
        let baseline = ts["baseline"].as_array().cloned().unwrap_or_default();
        let channels_ts = ts["channels"].as_object().cloned().unwrap_or_default();
        let channel_names: Vec<String> = channels_ts.keys().cloned().collect();

        // Header row at row 2
        ws.write_with_format(2, 0, "Период", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(2, 1, "Baseline", &header_fmt).map_err(|e| format!("{e}"))?;
        for (i, name) in channel_names.iter().enumerate() {
            ws.write_with_format(2, (i + 2) as u16, name.as_str(), &header_fmt).map_err(|e| format!("{e}"))?;
        }
        let total_col = (channel_names.len() + 2) as u16;
        let kpi_col = total_col + 1;
        ws.write_with_format(2, total_col, "Медиа-вклад", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(2, kpi_col, "KPI (факт+модель)", &header_fmt).map_err(|e| format!("{e}"))?;

        // Data rows starting at row 3
        let n_periods = dates.len();
        for t in 0..n_periods {
            let row = (t + 3) as u32;
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

        // Headline explainer at row n_periods+5
        let explainer_row = (n_periods + 5) as u32;
        ws.write_with_format(explainer_row, 0, "Как использовать лист:", &bold).map_err(|e| format!("{e}"))?;
        ws.write(explainer_row + 1, 0, "• Выделите колонки «Период» + нужные → Вставка → Диаграмма → получите график вклада канала по времени.").map_err(|e| format!("{e}"))?;
        ws.write(explainer_row + 2, 0, "• Baseline - часть KPI без медиа (органический спрос, сезонность, бренд).").map_err(|e| format!("{e}"))?;
        ws.write(explainer_row + 3, 0, "• Медиа-вклад = сумма по каналам. KPI = Baseline + Медиа-вклад (то что модель объясняет).").map_err(|e| format!("{e}"))?;

        // Widths - Данные (A = 1 cm ≈ 5.4 char; D = 2.2 cm ≈ 11.88 char, per Антон)
        ws.set_column_width(0, 5.4).map_err(|e| format!("{e}"))?;   // Период - 1 см
        ws.set_column_width(1, 13.61).map_err(|e| format!("{e}"))?; // Baseline - 2.52 см
        ws.set_column_width(2, 32.71).map_err(|e| format!("{e}"))?; // первый канал
        ws.set_column_width(3, 11.88).map_err(|e| format!("{e}"))?; // второй канал - 2.2 см
        for c in 4..total_col { ws.set_column_width(c, 32.71).map_err(|e| format!("{e}"))?; }
        ws.set_column_width(total_col, 26.71).map_err(|e| format!("{e}"))?;
        ws.set_column_width(kpi_col, 32.57).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 6: Глоссарий (NEW) ────────────────────────────
    {
        let ws = wb.add_worksheet();
        ws.set_name("Глоссарий").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(DEEP_80));
        apply_base_cols(ws, &base_fmt)?;
        apply_print_setup(ws, "Глоссарий")?;
        write_brand_header(ws, "Глоссарий терминов", 2)?;
        // Override A1 для Глоссария - Антон хочет "Aurora AI" в proper case
        ws.write_with_format(0, 0, "Aurora AI", &brand_aurora_fmt).map_err(|e| format!("{e}"))?;

        ws.write_with_format(2, 0, "Термин", &header_fmt).map_err(|e| format!("{e}"))?;
        ws.write_with_format(2, 1, "Определение", &header_fmt).map_err(|e| format!("{e}"))?;

        // Волна 3 (2026-06-20): глоссарий из фронта (SSOT glossary.js, 47 терминов
        // {term, definition}). XLSX перестаёт быть «4-м расходящимся глоссарием» —
        // единый источник glossary.js, Rust пассивно пишет переданное. Fallback на
        // встроенные 11 — только при отсутствии параметра (legacy-вызовы).
        let fallback: &[(&str, &str)] = &[
            ("MQS", "Model Quality Score - комплексная оценка качества модели (0-100). >80 = отлично, 60-80 = хорошо, <60 = требует доработки."),
            ("R²", "Коэффициент детерминации - доля дисперсии KPI, объяснённая моделью. 1.0 = идеальная модель."),
            ("MAPE", "Mean Absolute Percentage Error - средняя абсолютная ошибка в %. <10% = отлично."),
            ("R-hat", "Статистика сходимости MCMC. Значение ~1.0 означает, что цепи сошлись. >1.05 = проблема."),
            ("ROI", "Return on Investment - отношение инкрементального вклада канала к его расходу. ROI 2.0x = каждый рубль приносит 2 рубля."),
            ("miROAS", "Marginal incremental ROAS - отдача от каждого СЛЕДУЮЩЕГО рубля. Показывает, стоит ли увеличивать расходы на канал."),
            ("Adstock", "Эффект запаздывания рекламы. TV-реклама влияет на продажи ещё 2-8 недель после показа."),
            ("Hill function", "Функция насыщения. Моделирует убывающую отдачу: первые рубли эффективнее последних."),
            ("CI (95%)", "Доверительный интервал - диапазон, в который истинное значение попадает с 95% вероятностью."),
            ("Base sales", "Продажи без рекламного воздействия (органический спрос, бренд-эффект, сезонность)."),
            ("Efficiency Index", "Отношение доли эффекта к доле бюджета. >1.0 = канал эффективнее среднего."),
        ];
        let mut row = 3u32;
        if let Some(arr) = glossary.and_then(|g| g.as_array()).filter(|a| !a.is_empty()) {
            for item in arr {
                let term = item["term"].as_str().unwrap_or("-");
                let def = item["definition"].as_str()
                    .or_else(|| item["short"].as_str())
                    .unwrap_or("");
                ws.write_with_format(row, 0, term, &bold).map_err(|e| format!("{e}"))?;
                ws.write(row, 1, def).map_err(|e| format!("{e}"))?;
                row += 1;
            }
        } else {
            for (term, def) in fallback.iter() {
                ws.write_with_format(row, 0, *term, &bold).map_err(|e| format!("{e}"))?;
                ws.write(row, 1, *def).map_err(|e| format!("{e}"))?;
                row += 1;
            }
        }
        // Widths - Глоссарий (A = 3 cm; B = 19.2 cm; C hidden, per Антон)
        ws.set_column_width(0, 16.2).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 103.68).map_err(|e| format!("{e}"))?;
        ws.set_column_hidden(2).map_err(|e| format!("{e}"))?;
    }

    // ── Named ranges (tier-1 anchor; analyst drill-back) ─────────────────────
    // Only single-cell names - multi-row ranges brittle on variable channel
    // counts (audit M1). `define_name` is ignored if referenced sheet/row
    // never materialized (Executive Summary always present).
    wb.define_name("MQS_Score",    "='Executive Summary'!$B$5")
        .map_err(|e| format!("define_name MQS_Score: {e}"))?;
    wb.define_name("Total_Budget", "='Executive Summary'!$B$9")
        .map_err(|e| format!("define_name Total_Budget: {e}"))?;

    wb.save(path).map_err(|e| format!("XLSX save error: {e}"))?;

    // Post-process: fix sheetPr child element order to match OOXML XSD schema.
    // rust_xlsxwriter 0.79 emits <pageSetUpPr> BEFORE <tabColor>, but XSD
    // CT_SheetPr requires: tabColor → outlinePr → pageSetUpPr. Excel strict
    // validation rejects the sheet content → opens recovery dialog and strips
    // all data from affected sheets (9 of 11 broken). We swap back to correct
    // order here in-place.
    fix_sheetpr_element_order(path)?;
    Ok(())
}

/// Rewrite xl/worksheets/sheet*.xml inside the XLSX zip to put <tabColor>
/// BEFORE <pageSetUpPr> in <sheetPr>. No-op for sheets that have only one
/// (or neither) element. Uses `zip` and `regex` crates already in deps.
///
/// Post-audit (2026-04-25): writes to a sibling `.tmp` file then
/// `std::fs::rename` over the target, so a crash mid-write leaves the
/// original file intact instead of a half-overwritten corrupted XLSX.
fn fix_sheetpr_element_order(xlsx_path: &Path) -> Result<(), String> {
    use zip::read::ZipArchive;
    use zip::write::{SimpleFileOptions, ZipWriter};

    let bytes = std::fs::read(xlsx_path)
        .map_err(|e| format!("post-process read {xlsx_path:?}: {e}"))?;
    let mut archive = ZipArchive::new(Cursor::new(bytes))
        .map_err(|e| format!("post-process zip open: {e}"))?;

    // Matches <sheetPr [attrs]><pageSetUpPr .../><tabColor .../></sheetPr>
    // and emits <sheetPr [attrs]><tabColor .../><pageSetUpPr .../></sheetPr>.
    // Only triggers when both elements present in the wrong order. Idempotent
    // when order is already correct (no match → no replacement).
    let re = regex::Regex::new(
        r"<sheetPr([^>]*)><pageSetUpPr([^/]*)/><tabColor([^/]*)/></sheetPr>",
    )
    .map_err(|e| format!("post-process regex: {e}"))?;

    let out_buf: Vec<u8> = Vec::with_capacity(archive.len() * 4096);
    let mut writer = ZipWriter::new(Cursor::new(out_buf));

    for i in 0..archive.len() {
        let mut entry = archive
            .by_index(i)
            .map_err(|e| format!("post-process entry {i}: {e}"))?;
        let name = entry.name().to_string();
        let options = SimpleFileOptions::default().compression_method(entry.compression());

        let is_worksheet =
            name.starts_with("xl/worksheets/sheet") && name.ends_with(".xml");

        writer
            .start_file(&name, options)
            .map_err(|e| format!("post-process start {name}: {e}"))?;

        if is_worksheet {
            let mut content = String::new();
            entry
                .read_to_string(&mut content)
                .map_err(|e| format!("post-process read {name}: {e}"))?;
            let fixed =
                re.replace_all(&content, "<sheetPr$1><tabColor$3/><pageSetUpPr$2/></sheetPr>");
            writer
                .write_all(fixed.as_bytes())
                .map_err(|e| format!("post-process write {name}: {e}"))?;
        } else {
            let mut content = Vec::with_capacity(entry.size() as usize);
            entry
                .read_to_end(&mut content)
                .map_err(|e| format!("post-process read {name}: {e}"))?;
            writer
                .write_all(&content)
                .map_err(|e| format!("post-process write {name}: {e}"))?;
        }
    }

    let final_cursor = writer
        .finish()
        .map_err(|e| format!("post-process zip finish: {e}"))?;

    // Atomic write: stage to `<path>.tmp`, then rename. On Windows rename
    // over an existing file requires `fs::rename` which performs a
    // ReplaceFile equivalent on modern Windows (atomic on same volume).
    let tmp_path = xlsx_path.with_extension("xlsx.tmp");
    std::fs::write(&tmp_path, final_cursor.into_inner())
        .map_err(|e| format!("post-process write staged {tmp_path:?}: {e}"))?;
    std::fs::rename(&tmp_path, xlsx_path).map_err(|e| {
        // Best-effort cleanup of the staged file on rename failure so the
        // exports folder doesn't accrete stale .tmp turds.
        let _ = std::fs::remove_file(&tmp_path);
        format!("post-process rename {tmp_path:?} → {xlsx_path:?}: {e}")
    })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// Аудит #12: лист «Динамика» XLSX берёт ПОЛНЫЙ набор факторов из
    /// canonical decomposition_series (baseline + media + вынесенные factors),
    /// тот же, что в программе и HTML/PPTX отчётах.
    #[test]
    fn timeline_columns_from_decomposition_series() {
        let decompose = json!({
            "channels": [{"name": "TV"}, {"name": "Digital"}],
            "time_series": {
                "dates": ["w1", "w2"],
                "baseline": [100.0, 100.0],
                "channels": {"TV": [10.0, 12.0], "Digital": [5.0, 6.0]},
            },
            "decomposition_series": {
                "dates": ["w1", "w2"],
                "series": [
                    {"name": "Базовый уровень", "role": "baseline", "type": "baseline", "data": [80.0, 78.0]},
                    {"name": "TV", "role": "media", "type": "media", "data": [10.0, 12.0]},
                    {"name": "Digital", "role": "media", "type": "media", "data": [5.0, 6.0]},
                    {"name": "Продажи в уп. конкуренты", "role": "factor", "type": "signed_competitor", "side": "negative", "data": [-8.0, -3.0]},
                    {"name": "holiday_valentine", "role": "factor", "type": "holiday", "side": "positive", "data": [13.0, 7.0]},
                ],
            },
        });
        let (dates, cols) = decomposition_timeline_columns(&decompose);
        assert_eq!(dates, vec!["w1", "w2"]);
        let headers: Vec<&str> = cols.iter().map(|(h, _)| h.as_str()).collect();
        // baseline переименован в "Baseline", факторы присутствуют как колонки.
        assert_eq!(headers[0], "Baseline");
        assert!(headers.contains(&"TV") && headers.contains(&"Digital"));
        assert!(headers.contains(&"Продажи в уп. конкуренты"));
        assert!(headers.contains(&"holiday_valentine"));
        assert_eq!(cols.len(), 5);
    }

    /// Legacy-проект без decomposition_series → fallback baseline + media.
    #[test]
    fn timeline_columns_legacy_fallback() {
        let decompose = json!({
            "channels": [{"name": "TV"}],
            "time_series": {
                "dates": ["w1", "w2"],
                "baseline": [100.0, 100.0],
                "channels": {"TV": [10.0, 12.0]},
            },
        });
        let (dates, cols) = decomposition_timeline_columns(&decompose);
        assert_eq!(dates.len(), 2);
        let headers: Vec<&str> = cols.iter().map(|(h, _)| h.as_str()).collect();
        assert_eq!(headers, vec!["Baseline", "TV"]);
    }

    /// Волна 1 пункт 2: заголовок плашки надёжности. Пустая строка ⇒ плашки нет
    /// (reliable/нет verdict, решение 1b); прочие verdict дают заголовок. Лейблы
    /// зеркалят Python (sections.py/builder.py); caveat_text идёт verbatim отдельно.
    #[test]
    fn reliability_label_gates_on_verdict() {
        assert_eq!(reliability_label(""), "");
        assert_eq!(reliability_label("reliable"), "");
        assert_eq!(reliability_label("uncertain"), "Ограниченная надёжность модели");
        assert_eq!(reliability_label("unreliable"), "Модель ненадёжна — переброска отключена");
        assert_eq!(reliability_label("unknown"), "Надёжность модели не подтверждена");
        assert_eq!(reliability_label("какой-то новый"), "Надёжность модели");
    }

    /// Волна 1 пункт 3: honesty-смягчение вердикта (решение 2a). Зеркало Python
    /// soften_verdict_display: reliable→директивный; uncertain→«(предв.)»
    /// (направление сохранено); unreliable→нейтрализация.
    #[test]
    fn verdict_display_softens_by_reliability() {
        assert_eq!(verdict_display("Scale", "reliable"), "Увеличить");
        assert_eq!(verdict_display("Scale", ""), "Увеличить");
        assert_eq!(verdict_display("Scale", "uncertain"), "Увеличить (предв.)");
        assert_eq!(verdict_display("Cut", "unknown"), "Остановить (предв.)");
        // нейтральные — без суффикса
        assert_eq!(verdict_display("Watch", "uncertain"), "Наблюдать");
        // unreliable → направление не показываем
        assert_eq!(verdict_display("Scale", "unreliable"), "Требует переобучения");
    }

    /// Волна 3: метки режима анализа + типа KPI (зеркало Python). Неизвестное ⇒
    /// пустая строка (метку не показываем).
    #[test]
    fn analysis_and_kpi_labels() {
        assert_eq!(analysis_mode_label("roi"), "ROI (деньги)");
        assert_eq!(analysis_mode_label("effectiveness"), "Эффективность (доля вклада)");
        assert_eq!(analysis_mode_label("expert"), "Смешанный (эксперт)");
        assert_eq!(analysis_mode_label("xyz"), "");
        assert_eq!(kpi_kind_label("monetary"), "денежный");
        assert_eq!(kpi_kind_label("count"), "количественный");
        assert_eq!(kpi_kind_label("xyz"), "");
    }

    /// Волна 2: чистка `\n`/двойных пробелов в именах каналов (исходные Excel-
    /// заголовки) — иначе многострочные ячейки и рваный текст в отчёте.
    #[test]
    fn clean_label_collapses_whitespace() {
        assert_eq!(clean_label("Статьи Бюджет \nДО НДС до АК"), "Статьи Бюджет ДО НДС до АК");
        assert_eq!(clean_label("  TV  \n\n Digital "), "TV Digital");
        assert_eq!(clean_label("OLV"), "OLV");
    }

    /// Волна 2: waterfall = ОБЪЕКТ {labels, values, types} (прежде Rust ждал массив
    /// → лист «Декомпозиция» молча терялся). Проверяем, что объектный формат
    /// распознаётся как объект (as_object), а старый массив — нет.
    #[test]
    fn waterfall_is_object_not_array() {
        let wf = json!({
            "labels": ["Baseline", "TV", "Итого"],
            "values": [80.0, 20.0, 100.0],
            "types": ["baseline", "channel", "total"],
        });
        let obj = wf.as_object().expect("waterfall должен читаться как объект");
        assert_eq!(obj.get("labels").unwrap().as_array().unwrap().len(), 3);
        assert!(wf.as_array().is_none(), "объектный waterfall не должен быть массивом");
        // total-элемент находится по типу
        let types: Vec<&str> = obj["types"].as_array().unwrap().iter()
            .map(|t| t.as_str().unwrap()).collect();
        assert_eq!(types.iter().position(|t| *t == "total"), Some(2));
    }

    /// Волна 3: глоссарий из фронта (SSOT glossary.js) — извлечение term/definition
    /// (логика Sheet 6). definition с fallback на short; пустой/None → fallback-ветка.
    #[test]
    fn glossary_from_frontend_extraction() {
        let g = json!([
            {"term": "ROAS", "definition": "возврат на рекламные расходы"},
            {"term": "Adstock", "short": "остаточный эффект"},
        ]);
        let arr = g.as_array().unwrap();
        assert_eq!(arr[0]["term"].as_str().unwrap(), "ROAS");
        assert_eq!(arr[0]["definition"].as_str().unwrap(), "возврат на рекламные расходы");
        // definition отсутствует → fallback на short
        let def = arr[1]["definition"].as_str().or_else(|| arr[1]["short"].as_str());
        assert_eq!(def, Some("остаточный эффект"));
        // пустой / отсутствующий глоссарий → ветка fallback (filter отсекает пустой)
        let empty: Option<Value> = Some(json!([]));
        assert!(empty.as_ref().and_then(|x| x.as_array()).filter(|a| !a.is_empty()).is_none());
        let none: Option<Value> = None;
        assert!(none.as_ref().and_then(|x| x.as_array()).filter(|a| !a.is_empty()).is_none());
    }
}
