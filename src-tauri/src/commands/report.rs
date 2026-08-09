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

use crate::commands::mqs_tiers;

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
        "unreliable" => "Модель ненадёжна – переброска отключена",
        "unknown" => "Надёжность модели не подтверждена",
        "" | "reliable" => "",
        _ => "Надёжность модели",
    }
}

/// 2026-08-07: optimization.json переживает переобучение (project.rs:631
/// безусловно читает файл с диска, project-state.js:1394 чистит только память,
/// project-state.js:1260 кладёт обратно) — отчёт может собрать диагностику от
/// НОВОЙ модели и результаты оптимизации от СТАРОЙ, и ничто на это не укажет
/// клиенту. Две независимые половины сверки (доработка 2026-08-08 — аудит
/// вскрыл слепоту первой половины к tools/recompute_mqs.py: он пересчитывает
/// диагностику БЕЗ переобучения, подпись модели остаётся той же, а вердикт
/// надёжности в диагностике уже новый, в замороженной оптимизации — старый):
/// (а) подписи модели — top-level "model_fingerprint" (64 hex) в
///     model-diagnostics.json (тут: model["diagnostics"]["model_fingerprint"])
///     и в optimization.json (optimize["model_fingerprint"]);
/// (б) живой вердикт model["diagnostics"]["model_reliability"]["verdict"]
///     против замороженного optimize["model_reliability"]["verdict"]
///     (регистронезависимо).
/// Рассинхрон = истина хотя бы по одной половине. Для каждой половины: обе
/// величины должны присутствовать и быть непустыми, иначе эта половина сверки
/// не делается (отсутствие поля — старый проект, законно, молчим; ложная
/// тревога дороже пропуска).
fn diagnostics_optimization_diverged(model: &Value, optimize: &Value) -> bool {
    let fingerprints_diverge = {
        let mf = model["diagnostics"]["model_fingerprint"].as_str().filter(|s| !s.is_empty());
        let of = optimize["model_fingerprint"].as_str().filter(|s| !s.is_empty());
        matches!((mf, of), (Some(a), Some(b)) if a != b)
    };
    let verdicts_diverge = {
        let mv = model["diagnostics"]["model_reliability"]["verdict"].as_str()
            .filter(|s| !s.is_empty()).map(|s| s.to_lowercase());
        let ov = optimize["model_reliability"]["verdict"].as_str()
            .filter(|s| !s.is_empty()).map(|s| s.to_lowercase());
        matches!((mv, ov), (Some(a), Some(b)) if a != b)
    };
    fingerprints_diverge || verdicts_diverge
}

/// Текст предупреждения VERBATIM — синхрон со стороной Python (сторож на шве).
/// Короткое тире «–» (U+2013), не длинное — линтер продукта валит длинное тире
/// в клиентском тексте. Доработка 2026-08-08: прежний текст («на другой
/// модели») стал неправдой для случая (б) — там модель ТА ЖЕ, разошлись
/// только вердикты диагностики и оптимизации по времени расчёта.
const FINGERPRINT_MISMATCH_TEXT: &str = "Диагностика модели и результаты оптимизации получены в разных расчётах – пересчитайте оптимизацию, прежде чем опираться на переброску бюджета.";

/// Волна 1 пункт 3 (2026-06-20): отображаемый вердикт-действие (рус) + honesty-
/// смягчение (решение 2a). Зеркалит engines.channel_action.soften_verdict_display
/// (Python) — Rust XLSX/MD читают results JSON напрямую, мимо Python-моста, поэтому
/// рус-локализацию и смягчение держим здесь. Глобальная надёжность модели смягчает
/// ДИРЕКТИВНОСТЬ, сохраняя НАПРАВЛЕНИЕ: reliable→«Увеличить»; uncertain/unknown→
/// «Увеличить (предв.)»; unreliable→«Требует переобучения». Снимает рассогласование
/// (прежде XLSX/MD писали англ. machine-key «Scale», PPTX – рус «Увеличить»).
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

/// Excel ограничивает содержимое ячейки 32 767 символами (rust_xlsxwriter
/// MAX_STRING_LEN) — запись строки длиннее лимита возвращает Err и роняет
/// весь build_xlsx через `?` (разведка 2026-08-07, scratchpad/pulse_xlsx_reach.md).
/// На сейчас (2026-08-07) определения глоссария приходят из фронта
/// (getAllTerms()) и максимум ≈ 400-800 символов, но источник — Value с фронта,
/// не статически проверяемый Rust-типом, поэтому страховка на будущее (заметки
/// аналитика, склейка полей и т.п.). Обрезка по границе символа (`.chars()`,
/// не байтов) - иначе кириллица/эмодзи ломаются на полуграфеме.
fn truncate_to_excel_cell_limit(s: &str) -> std::borrow::Cow<'_, str> {
    const XLSX_CELL_CHAR_LIMIT: usize = 32_767;
    if s.chars().count() <= XLSX_CELL_CHAR_LIMIT {
        std::borrow::Cow::Borrowed(s)
    } else {
        let mut truncated: String = s.chars().take(XLSX_CELL_CHAR_LIMIT - 1).collect();
        truncated.push('…');
        std::borrow::Cow::Owned(truncated)
    }
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
    ws.set_header(format!("&LAurora AI Econometrica – {sheet_name}&R&D"));
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

/// «Нет числа — нет подписи» (2026-07-26): дословно та же формулировка
/// отсутствия оценки, что в `aurora_pptx/builder.py` (карточка MQS слайда)
/// и `aurora_html/sections.py::render_sources` (карточка «Качество модели»).
/// Единая точка текста для XLSX и markdown-отчёта — разнобой формулировок
/// по поверхностям это тот же дефект в профиль.
const MQS_ABSENT_TEXT: &str = "Оценка не выполнялась для этого расчёта";

/// Значение ячейки MQS Score листа «Executive Summary» — либо реальное число,
/// либо честный текст отсутствия (никогда фиктивный 0.0).
enum MqsCell {
    Value(f64),
    Absent,
}

/// Строит содержимое строки MQS Score (ячейки B5/C5) и строки «MQS Tier»
/// листа «Executive Summary» XLSX. Единая точка для build_xlsx — раньше
/// `model["diagnostics"]["mqs"]["score"].as_f64().unwrap_or(0.0)` превращал
/// несчитанную оценку в ноль, и лист печатал «MQS Score | 0 | Требует
/// доработки» - приговор модели вместо отметки, что её не оценивали.
/// Настоящий ноль (mqs == Some(0.0)) - валидное значение и сохраняется.
fn mqs_xlsx_row(mqs: Option<f64>, mqs_label: Option<&str>) -> (MqsCell, &'static str, String) {
    match mqs {
        Some(v) => {
            // Единый источник (INV-106 продолжение, 2026-07-27): раньше `grade`
            // (своя лестница 80/60) и `tier_line` (сырой mqs_label) были ДВУМЯ
            // независимыми ярлыками для одного и того же балла в одной строке
            // листа - ровно рецидив L16 внутри одной функции. Теперь оба берут
            // ОДИН резолвнутый ярлык канона (mqs_tiers).
            let grade = mqs_tiers::resolve_mqs_label(v, mqs_label);
            (MqsCell::Value(v), grade, format!("MQS Tier: {grade}"))
        }
        None => (MqsCell::Absent, "", MQS_ABSENT_TEXT.to_string()),
    }
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
        "subtitle": "Байесовская Media Mix Model с отложенным эффектом (adstock) и Hill-насыщением",
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
        "normalization": "Media нормализованы Robyn-style (spend / mean(spend) после отложенного эффекта (adstock)); control z-нормализованы; y нормализован к std=1.",
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

/// Прочитать данные прогноза из project_dir/results/planning.json и scenarios/*.json.
/// Возвращает None если файл не найден / невалидный JSON.
fn read_forecast(project_id: &str) -> Option<Value> {
    let project_dir = crate::commands::project::project_dir(project_id).ok()?;
    let planning_path = project_dir.join("results").join("planning.json");
    if !planning_path.exists() {
        return None;
    }
    let content = std::fs::read_to_string(&planning_path).ok()?;
    let mut planning: Value = serde_json::from_str(&content).ok()?;

    // Дополнительно подгружаем сценарии из results/scenarios/ (если есть)
    // и встраиваем как planning["scenarios"] если там пусто.
    if planning.get("scenarios").and_then(|s| s.as_array()).map(|a| a.is_empty()).unwrap_or(true) {
        let scenario_jsons = read_scenarios(project_id);
        if !scenario_jsons.is_empty() {
            planning["scenarios"] = serde_json::Value::Array(
                scenario_jsons.into_iter().map(|s| {
                    // Адаптируем формат сценария к формату прогноза
                    let totals = s.get("totals").cloned().unwrap_or_default();
                    let name = s["scenario_name"].as_str()
                        .or_else(|| s["name"].as_str())
                        .unwrap_or("Сценарий")
                        .to_string();
                    serde_json::json!({
                        "name": name,
                        "variant_id": s.get("variant_id"),
                        "total_kpi": totals.get("predicted_kpi").and_then(|v| v.as_f64()),
                        "total_spend_money": totals.get("total_spend_money").and_then(|v| v.as_f64()),
                        "roas_money": totals.get("roas_money").and_then(|v| v.as_f64()),
                    })
                }).collect()
            );
        }
    }

    Some(planning)
}

// ── Markdown report ──────────────────────────────────────────────────────────

/// Build a full Markdown report from MMM pipeline data.
fn build_markdown(model: &Value, decompose: &Value, optimize: &Value) -> String {
    // «Нет числа — нет подписи» (INV-106, 2026-07-26): mqs остаётся Option -
    // несчитанная оценка не должна превращаться в фиктивный 0.0 (см.
    // MQS_ABSENT_TEXT выше). Настоящий ноль (Some(0.0)) - валидное значение.
    let mqs        = model["diagnostics"]["mqs"]["score"].as_f64();
    let mqs_label  = model["diagnostics"]["mqs"]["tier_label"].as_str();
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
    // INV-50: исключаем roi_unreliable каналы — иначе битый ROI (unit_smell
    // «не рубли», артефакт единиц) коронуется «лучшим» и «Приоритизировать».
    // clean_label — имя может нести `\n` из исходных Excel-заголовков.
    let top_ch = decompose["channels"].as_array()
        .and_then(|chs| {
            chs.iter()
                .filter(|c| !roi_unreliable(c))
                .max_by(|a, b| {
                    let ra = a["roi"].as_f64().unwrap_or(0.0);
                    let rb = b["roi"].as_f64().unwrap_or(0.0);
                    ra.partial_cmp(&rb).unwrap_or(std::cmp::Ordering::Equal)
                })
                .and_then(|c| c["name"].as_str())
        })
        .map(clean_label)
        .unwrap_or_else(|| "н/д".to_string());

    let now = Local::now().format("%d.%m.%Y %H:%M").to_string();
    let mut md = String::with_capacity(4096);

    // ── Title ────────────────────────────────────────────────
    md.push_str("# Marketing Mix Model – Аналитический отчёт\n\n");
    md.push_str(&format!("*Сгенерировано: {now}*\n\n---\n\n"));

    // ── Executive Summary ────────────────────────────────────
    md.push_str("## EXECUTIVE SUMMARY\n\n");
    match mqs {
        Some(v) => md.push_str(&format!(
            "- **Качество модели (MQS):** {v:.1} – {}\n",
            mqs_tiers::resolve_mqs_label(v, mqs_label)
        )),
        None => md.push_str(&format!("- **Качество модели (MQS):** {MQS_ABSENT_TEXT}\n")),
    }
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
    // тот же текст, что в UI/HTML/PPTX. Заголовок-вердикт — reliability_label.
    {
        let mr_verdict = optimize["model_reliability"]["verdict"].as_str().unwrap_or("").to_lowercase();
        let mr_label = reliability_label(&mr_verdict);
        let mr_caveat = optimize["model_reliability"]["caveat_text"].as_str().unwrap_or("");
        if !mr_label.is_empty() && !mr_caveat.is_empty() {
            md.push_str(&format!("\n> ⚠ **{mr_label}.** {mr_caveat}\n"));
        }
    }
    // 2026-08-07/08: рассинхрон диагностики и оптимизации
    // (diagnostics_optimization_diverged: подпись модели ИЛИ вердикт надёжности) —
    // РЯДОМ с плашкой надёжности выше, не заменяет её (та про качество ЭТИХ
    // чисел, эта про то, что диагностика и оптимизация — из разных расчётов).
    if diagnostics_optimization_diverged(model, optimize) {
        md.push_str(&format!("\n> ⚠ {FINGERPRINT_MISMATCH_TEXT}\n"));
    }
    md.push_str("\n---\n\n");

    // ── Model Quality ────────────────────────────────────────
    md.push_str("## Качество модели\n\n");
    md.push_str("| Метрика | Значение |\n");
    md.push_str("|---------|----------|\n");
    match mqs {
        Some(v) => {
            md.push_str(&format!("| MQS Score | {v:.1} |\n"));
            md.push_str(&format!(
                "| MQS Tier | {} |\n",
                mqs_tiers::resolve_mqs_label(v, mqs_label)
            ));
        }
        None => md.push_str(&format!("| MQS | {MQS_ABSENT_TEXT} |\n")),
    }
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
            let cat = clean_label(item["category"].as_str().unwrap_or("-"));
            let val = item["value"].as_f64().unwrap_or(0.0);
            let pct = item["contribution_pct"].as_f64().unwrap_or(0.0);
            md.push_str(&format!("| {cat} | {val:.0} | {pct:.1}% |\n"));
        }
        md.push('\n');
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
            let name   = clean_label(ch["name"].as_str().unwrap_or("-"));
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
            md.push_str("### ROI с правдоподобными диапазонами (90%)\n\n");
            md.push_str("| Канал | ROI | Диапазон нижний | Диапазон верхний |\n");
            md.push_str("|-------|----:|----------:|-----------:|\n");
            for ch in chs_for_ci {
                let ch_name = clean_label(ch["name"].as_str().unwrap_or("-"));
                if roi_unreliable(ch) {
                    md.push_str(&format!("| {ch_name} | н/д | – | – |\n"));
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
            let name  = clean_label(ch["name"].as_str().unwrap_or("-"));
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
        md.push_str(&format!("- [ВЫСОКАЯ] Перераспределить бюджет согласно оптимальному плану – ожидаемый прирост **{lift:+.1}%**\n"));
    } else if lift > 0.0 {
        md.push_str(&format!("- [СРЕДНЯЯ] Рассмотреть корректировку бюджетного распределения – ожидаемый прирост {lift:+.1}%\n"));
    }
    if r_squared < 0.7 {
        md.push_str("- [СРЕДНЯЯ] R² ниже рекомендуемого порога 0.7 – рассмотреть добавление контрольных переменных\n");
    }
    // Вердикт по MQS печатается только когда оценка реально посчитана -
    // при отсутствии (mqs == None) нет основания ни для «требует доработки»,
    // ни для «надёжны» (было: фиктивный 0.0 всегда бил в первую ветку).
    // Пороги 60/80 заменены на канон MQS (85/70/55/40, mqs_tiers) - раньше
    // здесь жила третья, независимая лестница вдобавок к grade/tier_line.
    // "требует доработки" = tier weak/poor (дословно WEAK_TIERS из
    // utils/optimizer_honesty.py); "надёжны для решений" = tier good/excellent
    // (дословно mqsIsDependable из src/lib/mqs-tiers.js). Уровень «Приемлемое»
    // (2026-07-27, внешний аудит, Medium) раньше не получал НИ ОДНОЙ строки -
    // молчание в разделе рекомендаций читается как «замечаний нет», то есть
    // отсутствие вердикта работало как положительный. Была та же дыра и до
    // смещения порогов на канон (диапазон между старыми 60/80 тоже молчал) -
    // это давняя дыра, а не регресс правки порогов. `mqs_is_acceptable`
    // (mqs_tiers) закрывает середину: три предиката покрывают все пять
    // ступеней канона ровно по одному разу - см. регресс-тест в mqs_tiers.rs.
    if let Some(v) = mqs {
        if mqs_tiers::mqs_is_weak(v) {
            md.push_str("- [СРЕДНЯЯ] MQS Score на уровне «Слабое» или «Ненадёжное» – модель требует доработки или дополнительных данных\n");
        }
        if mqs_tiers::mqs_is_acceptable(v) {
            md.push_str("- [СРЕДНЯЯ] MQS Score на уровне «Приемлемое» – результаты пригодны для ориентировки, но не для точных решений\n");
        }
        if mqs_tiers::mqs_is_dependable(v) {
            md.push_str("- [ВЫСОКАЯ] MQS Score на уровне «Хорошее» и выше – результаты модели надёжны для принятия решений\n");
        }
    }
    md.push_str(&format!("- [ВЫСОКАЯ] Приоритизировать канал **{top_ch}** – наивысший ROI в миксе\n"));
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
    // Волна 3 (2026-06-20): глоссарий из фронта (SSOT glossary.js, 50 терминов).
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
    // Прогноз - опциональный. Лист «Прогноз» добавляется только при наличии данных.
    let forecast = read_forecast(&project_id);

    build_xlsx(&model_data, &decompose_data, &optimize_data, &scenarios, forecast.as_ref(), &project_id, &path, glossary.as_ref())?;

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
                "Базовый спрос".to_string()
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
            cols.push(("Базовый спрос".to_string(),
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

#[allow(clippy::too_many_arguments)]
fn build_xlsx(
    model: &Value,
    decompose: &Value,
    optimize: &Value,
    scenarios: &[Value],
    forecast: Option<&Value>,
    project_id: &str,
    path: &PathBuf,
    // Волна 3 (2026-06-20): глоссарий из фронта (SSOT glossary.js, 50 терминов);
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
        .set_title(format!("Aurora AI MMM – {client_label}"))
        .set_subject("Marketing Mix Model – аналитический отчёт")
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
        // Волна 3 (2026-06-20): метка режима анализа + типа KPI (контекст метрик).
        let mode_lbl = analysis_mode_label(&decompose["derived_mode"].as_str().unwrap_or("roi").to_lowercase());
        let kind_lbl = kpi_kind_label(&decompose["kpi_kind"].as_str().unwrap_or("monetary").to_lowercase());
        let mode_meta = if kind_lbl.is_empty() { mode_lbl.to_string() }
                        else { format!("{mode_lbl} · KPI: {kind_lbl}") };
        let meta_rows: &[(&str, String)] = &[
            ("Подготовлено для:", client_label.to_string()),
            ("Проект:",           project_id.to_string()),
            ("Дата:",             today),
            ("Версия:",           "v1.0.13".to_string()),
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
            ("ROI каналов",       "ROI по каналам с правдоподобным диапазоном"),
            ("Spend vs Effect",   "Доля бюджета vs доля эффекта"),
            ("Динамика",          "Еженедельная декомпозиция"),
            ("Оптимизация",       "Текущая vs оптимальная аллокация"),
            ("Прогноз",           "Прогноз KPI по периодам с ДИ и медиапланом"),
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

        // «Нет числа — нет подписи» (INV-106, 2026-07-26): mqs остаётся Option -
        // см. mqs_xlsx_row выше. Настоящий ноль (Some(0.0)) - валидное значение.
        let mqs       = model["diagnostics"]["mqs"]["score"].as_f64();
        let mqs_label = model["diagnostics"]["mqs"]["tier_label"].as_str();
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

        // MQS - строка 4 (B5/C5, см. define_name "MQS_Score" ниже) - отдельно
        // от общего вектора: при отсутствии оценки значение не выражается
        // числом f64 без лжи, и оценка-«вердикт» (col C) не рисуется вовсе.
        let (mqs_cell, mqs_grade, mqs_tier_line) = mqs_xlsx_row(mqs, mqs_label);
        ws.write(4, 0, "MQS Score").map_err(|e| format!("{e}"))?;
        match mqs_cell {
            MqsCell::Value(v) => { ws.write(4, 1, v).map_err(|e| format!("{e}"))?; }
            MqsCell::Absent => { ws.write(4, 1, MQS_ABSENT_TEXT).map_err(|e| format!("{e}"))?; }
        }
        ws.write(4, 2, mqs_grade).map_err(|e| format!("{e}"))?;

        let metrics: Vec<(&str, f64, &str)> = vec![
            ("R²", r_sq, if r_sq >= 0.8 { "Отлично" } else if r_sq >= 0.6 { "Хорошо" } else { "Слабо" }),
            ("MAPE (%)", mape, if mape <= 10.0 { "Отлично" } else if mape <= 20.0 { "Приемлемо" } else { "Высокая ошибка" }),
            ("Прирост от оптимизации (%)", lift, if lift > 10.0 { "Значительный" } else if lift > 3.0 { "Умеренный" } else { "Минимальный" }),
            ("Общий бюджет", budget, ""),
        ];
        for (i, (label, val, grade)) in metrics.iter().enumerate() {
            let row = (i + 5) as u32;
            ws.write(row, 0, *label).map_err(|e| format!("{e}"))?;
            ws.write(row, 1, *val).map_err(|e| format!("{e}"))?;
            ws.write(row, 2, *grade).map_err(|e| format!("{e}"))?;
        }
        ws.write(9, 0, mqs_tier_line).map_err(|e| format!("{e}"))?;
        if let Some(rh) = r_hat {
            ws.write(10, 0, format!("R-hat (сходимость): {rh:.4}")).map_err(|e| format!("{e}"))?;
        }
        // INV-50 F-DELIVERABLE-1 (2026-06-07): честная оговорка о тонких данных /
        // переобучении. Прежде клиентский XLSX показывал «MQS 70 Хорошо» без
        // предупреждения, хотя backend применил data-thinness cap. Формулировка
        // ЗЕРКАЛИТ utils/diagnostics.py::format_thinness_caveat (Python SSOT) —
        // Rust не импортирует Python, синхрон держим вручную (тест сверяет).
        let thinness_cap = model["diagnostics"]["mqs"]["thinness_cap"].as_f64();
        let ratio_eff = model["diagnostics"]["metrics"]["ratio"].as_f64();
        if let (Some(_cap), Some(ratio)) = (thinness_cap, ratio_eff) {
            // 🔴 Зеркало ДОСЛОВНОЕ. 2026-08-04: Python-сторона была переписана на
            // тон McElreath (не «артефакт переобучения» и не «результаты ненадёжны»,
            // а честно про механизм), а эта половина осталась прежней — клиент
            // получал в XLSX одну формулировку, в HTML и PPTX другую, причём
            // XLSX нёс ровно тот алармизм, от которого отказались. Сторожа,
            // обещанного комментарием выше, не существовало вовсе; теперь он есть:
            // sidecar/econometrica/tests/test_thinness_caveat_mirror.py
            let caveat = if ratio < 2.0 {
                format!("⚠ Данных мало (Ratio {ratio:.1}:1) – модель сильно опирается на априорные предположения, правдоподобный диапазон широкий, точечная надёжность ограничена.")
            } else {
                format!("⚠ Данных мало (Ratio {ratio:.1}:1 < 4:1) – модель сдержана, опирается на априорные предположения; правдоподобный диапазон будет широким.")
            };
            ws.write(11, 0, caveat).map_err(|e| format!("{e}"))?;
        }

        // Плашка надёжности модели — та же, что в Markdown (reliability_label +
        // caveat_text VERBATIM из optimization.json, SSOT optimizer_honesty, INV-50).
        // 🔴 До 2026-08-04 она доходила только до Markdown: при переносе функций
        // вызов в XLSX не был добавлен, хотя отчёт об этом утверждал обратное.
        // Поймано сторожем проводки (test_report_rs_wiring.py), а не глазами:
        // юнит-тест самой reliability_label был зелёным — функция цела, её просто
        // никто не звал на этом пути. Следствие для клиента: в XLSX не было
        // предупреждения о ненадёжной модели, а в Markdown и HTML было.
        {
            let mr_verdict = optimize["model_reliability"]["verdict"]
                .as_str().unwrap_or("").to_lowercase();
            let mr_label = reliability_label(&mr_verdict);
            let mr_caveat = optimize["model_reliability"]["caveat_text"]
                .as_str().unwrap_or("");
            if !mr_label.is_empty() && !mr_caveat.is_empty() {
                ws.write(12, 0, format!("⚠ {mr_label}. {mr_caveat}"))
                    .map_err(|e| format!("{e}"))?;
            }
        }

        // 2026-08-07/08: рассинхрон диагностики и оптимизации
        // (diagnostics_optimization_diverged: подпись модели ИЛИ вердикт надёжности) —
        // РЯДОМ с плашкой надёжности (строка 12), не поверх неё; строка 13 свободна.
        if diagnostics_optimization_diverged(model, optimize) {
            ws.write(13, 0, format!("⚠ {FINGERPRINT_MISMATCH_TEXT}"))
                .map_err(|e| format!("{e}"))?;
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
    if let Some(wf) = decompose["waterfall"].as_array() {
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

        for (i, item) in wf.iter().enumerate() {
            let row = (i + 3) as u32; // header at row 2 → data starts row 3
            let cat = clean_label(item["category"].as_str().unwrap_or("-"));
            let val = item["value"].as_f64().unwrap_or(0.0);
            ws.write(row, 0, cat).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, val, &num_fmt).map_err(|e| format!("{e}"))?;
            // Formula: contribution / total. Excel 1-based ref = row+1; total at total_row+1.
            let total_xlsx = wf.len() as u32 + 4; // ИТОГО row Excel 1-based
            ws.write_formula_with_format(row, 2, Formula::new(format!("=B{}/B${}", row + 1, total_xlsx)), &pct_fmt).map_err(|e| format!("{e}"))?;
        }
        // Total row (zero-based = wf.len() + 3 since data starts at 3 and runs wf.len() rows)
        let total_row = wf.len() as u32 + 3;
        ws.write_with_format(total_row, 0, "ИТОГО", &bold).map_err(|e| format!("{e}"))?;
        ws.write_formula_with_format(total_row, 1, Formula::new(format!("=SUM(B4:B{})", total_row)), &bold).map_err(|e| format!("{e}"))?;

        // Bar chart - categories at rows 3..wf.len()+2 (zero-based), values col B
        let mut chart = Chart::new(ChartType::Bar);
        chart.add_series()
            .set_categories(("Декомпозиция", 3, 0, wf.len() as u32 + 2, 0))
            .set_values(("Декомпозиция", 3, 1, wf.len() as u32 + 2, 1))
            .set_name("Вклад в продажи");
        chart.set_style(12); // Excel built-in style closest to Aurora hybrid (gradient navy/gold)
        chart.set_width(567).set_height(283); // matches XLSX_reference (15×7.5 cm)
        chart.title().set_name("Декомпозиция продаж");
        ws.insert_chart(total_row + 2, 0, &chart).map_err(|e| format!("{e}"))?;

        // Widths matching reference style
        ws.set_column_width(0, 35.71).map_err(|e| format!("{e}"))?;
        ws.set_column_width(1, 24.57).map_err(|e| format!("{e}"))?;
        ws.set_column_width(2, 18.0).map_err(|e| format!("{e}"))?;
    }

    // ── Sheet 3: ROI каналов + chart + conditional formatting ─
    if let Some(chs) = decompose["channels"].as_array() {
        let ws = wb.add_worksheet();
        ws.set_name("ROI каналов").map_err(|e| format!("{e}"))?;
        ws.set_tab_color(Color::RGB(GOLD));
        apply_base_cols(ws, &base_fmt)?;
        apply_print_setup(ws, "ROI каналов")?;
        write_brand_header(ws, "ROI каналов", 6)?;

        let headers = ["Канал", "Расход, ₽", "Вклад, ₽", "ROI", "Диапазон нижний", "Диапазон верхний", "Вердикт"];
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
            let name = clean_label(ch["name"].as_str().unwrap_or("-"));
            let spend = ch["spend"].as_f64().unwrap_or(0.0);
            let contrib = ch["contribution"].as_f64().unwrap_or(0.0);
            let verdict = ch["verdict"].as_str().unwrap_or("-");
            let ci_lo = ch["roi_ci_low"].as_f64().unwrap_or(0.0);
            let ci_hi = ch["roi_ci_high"].as_f64().unwrap_or(0.0);

            // Волна 1 Шаг 2: битый ROI (битые единицы / артефакт) не пишем числом —
            // абсурдные значения нельзя подавать клиенту как факт (INV-50). Признак —
            // helper roi_unreliable (зеркалит narrative_adapter._roi_unreliable; Python
            // мост сюда не доходит: Rust XLSX читает results JSON напрямую).
            let roi_bad = roi_unreliable(ch);

            ws.write(row, 0, name).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, spend, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, contrib, &num_fmt).map_err(|e| format!("{e}"))?;
            if roi_bad {
                ws.write(row, 3, "н/д*").map_err(|e| format!("{e}"))?;
                ws.write(row, 4, "–").map_err(|e| format!("{e}"))?;
                ws.write(row, 5, "–").map_err(|e| format!("{e}"))?;
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
            ws.write(note_row, 0, "* ROI н/д – единицы канала требуют проверки (не сопоставим с рублёвыми); сравнивайте по доле вклада.")
                .map_err(|e| format!("{e}"))?;
        }

        // Conditional formatting + chart: только при непустых каналах — при
        // chs.is_empty() last_row (= chs.len()+2 = 2) оказывается МЕНЬШЕ
        // first_row (= 3 хардкод) и add_conditional_format/insert_chart вернут
        // Err(RowColumnOrderError), что через `?` уронит build_xlsx целиком
        // (весь экспорт, а не только этот лист) — разведка 2026-08-07,
        // scratchpad/pulse_xlsx_reach.md. При нуле каналов лист собирается без
        // украшений (заголовки уже написаны выше), но книга сохраняется.
        if !chs.is_empty() {
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
        }

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
            let name = clean_label(ch["name"].as_str().unwrap_or("-"));
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

        // Тот же класс отказа, что на «ROI каналов»/«Оптимизация» (разведка
        // 2026-08-07, scratchpad/pulse_xlsx_reach.md): при chs.is_empty() эта
        // ветка выполняется (Some(пустой vec)), last_row=2 < first_row=3,
        // insert_chart вернул бы Err(диапазон перевёрнут) и уронил бы
        // build_xlsx целиком. Обнаружено ЖИВЬЁМ прогоном сторожа
        // build_xlsx_survives_empty_optimize_and_decompose_channels: гейт на
        // «ROI каналов» открыл путь сюда (раньше падало ещё ДО этого листа).
        if !chs.is_empty() {
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
        }

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
                ws.write_with_format(2, (j + 1) as u16, clean_label(header), &header_fmt)
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

            ws.write(row, 0, clean_label(name)).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, curr, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, opt, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 3, delta, &num_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 4, delta_pct, &pct_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 5, curr_roi, &roi_fmt).map_err(|e| format!("{e}"))?;
        }

        // Conditional formatting + chart: только при непустых каналах — при
        // opt_chs.is_empty() last_row (= opt_chs.len()+2 = 2) оказывается МЕНЬШЕ
        // first_row (= 3 хардкод) и add_conditional_format/insert_chart вернут
        // Err(RowColumnOrderError), что через `?` уронит build_xlsx целиком
        // (весь экспорт, а не только этот лист) — разведка 2026-08-07,
        // scratchpad/pulse_xlsx_reach.md. При нуле каналов лист собирается без
        // украшений (заголовки уже написаны выше), но книга сохраняется.
        let first_row = 3u32;
        let last_row = opt_chs.len() as u32 + 2;
        if !opt_chs.is_empty() {
            // Conditional formatting on delta columns (data rows 3..3+len-1)
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
        }

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

    // ── Sheet 5.3: Прогноз (if any) ──────────────────────────
    // Лист создаётся только при наличии planning.json / данных прогноза.
    // Содержит: таблицу периодов + сводку сравнения вариантов.
    if let Some(fc) = forecast {
        let fc_scenarios = fc.get("scenarios").and_then(|s| s.as_array());
        if fc_scenarios.map(|s| !s.is_empty()).unwrap_or(false) {
            let ws = wb.add_worksheet();
            ws.set_name("Прогноз").map_err(|e| format!("{e}"))?;
            ws.set_tab_color(Color::RGB(DEEP_80));
            apply_base_cols(ws, &base_fmt)?;
            apply_print_setup(ws, "Прогноз")?;
            write_brand_header(ws, "Прогноз KPI", 6)?;

            // ── Секция 1: Периодическая таблица базового/принятого варианта ──
            let accepted_id = fc.get("accepted_variant").and_then(|v| v.as_str());
            let fc_scens = fc_scenarios.unwrap(); // safe: checked above

            // Ищем принятый вариант, иначе первый
            let base_sc = fc_scens.iter()
                .find(|s| accepted_id.map(|id| s.get("variant_id").and_then(|v| v.as_str()) == Some(id)).unwrap_or(false))
                .or_else(|| fc_scens.first());

            let mut row: u32 = 2;
            ws.write_with_format(row, 0, "Период", &header_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, "Прогноз KPI", &header_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, "ДИ нижн.", &header_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 3, "ДИ верхн.", &header_fmt).map_err(|e| format!("{e}"))?;
            row += 1;

            if let Some(sc) = base_sc {
                let period_labels = sc.get("period_labels")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                let predictions = sc.get("predictions")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                let ci_low_list = sc.get("ci_low")
                    .or_else(|| sc.get("predictions_ci_low"))
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                let ci_high_list = sc.get("ci_high")
                    .or_else(|| sc.get("predictions_ci_high"))
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();

                let n_periods = predictions.len();
                for t in 0..n_periods {
                    let period_str = period_labels.get(t)
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();
                    let pred = predictions.get(t).and_then(|v| v.as_f64()).unwrap_or(0.0);
                    let ci_lo = ci_low_list.get(t).and_then(|v| v.as_f64());
                    let ci_hi = ci_high_list.get(t).and_then(|v| v.as_f64());

                    ws.write(row, 0, period_str.as_str()).map_err(|e| format!("{e}"))?;
                    ws.write_with_format(row, 1, pred, &num_fmt).map_err(|e| format!("{e}"))?;
                    if let Some(lo) = ci_lo {
                        ws.write_with_format(row, 2, lo, &num_fmt).map_err(|e| format!("{e}"))?;
                    }
                    if let Some(hi) = ci_hi {
                        ws.write_with_format(row, 3, hi, &num_fmt).map_err(|e| format!("{e}"))?;
                    }
                    row += 1;
                }
            }

            // ── Секция 2: Сводка сравнения вариантов ──────────────────────────
            row += 1;
            ws.write_with_format(row, 0, "Вариант", &header_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 1, "Прогноз KPI", &header_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 2, "Бюджет, ₽", &header_fmt).map_err(|e| format!("{e}"))?;
            ws.write_with_format(row, 3, "ROAS", &header_fmt).map_err(|e| format!("{e}"))?;
            row += 1;

            for sc in fc_scens.iter().take(10) {
                let name = sc.get("name")
                    .or_else(|| sc.get("title"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("-");
                let is_accepted = accepted_id.map(|id| {
                    sc.get("variant_id").and_then(|v| v.as_str()) == Some(id)
                }).unwrap_or(false);
                let display_name = if is_accepted { format!("★ {name}") } else { name.to_string() };
                let kpi = sc.get("total_kpi")
                    .or_else(|| sc.get("predicted_kpi"))
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0);
                let budget = sc.get("total_spend_money")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0);
                let roas = sc.get("roas_money").and_then(|v| v.as_f64());

                let row_fmt = if is_accepted { &bold } else { &base_fmt };
                ws.write_with_format(row, 0, display_name.as_str(), row_fmt).map_err(|e| format!("{e}"))?;
                ws.write_with_format(row, 1, kpi, &num_fmt).map_err(|e| format!("{e}"))?;
                ws.write_with_format(row, 2, budget, &num_fmt).map_err(|e| format!("{e}"))?;
                if let Some(r) = roas {
                    ws.write_with_format(row, 3, r, &roi_fmt).map_err(|e| format!("{e}"))?;
                }
                row += 1;
            }

            // ── Дисклеймер (gold italic) ────────────────────────────────────
            let disclaimers = fc.get("disclaimers").and_then(|v| v.as_array());
            if let Some(discs) = disclaimers {
                if !discs.is_empty() {
                    row += 1;
                    let note_fmt = Format::new()
                        .set_font_name("Inter")
                        .set_font_size(9)
                        .set_italic()
                        .set_font_color(Color::RGB(GOLD));
                    let disc_text: String = discs.iter()
                        .filter_map(|d| d.as_str())
                        .take(3)
                        .collect::<Vec<_>>()
                        .join(" · ");
                    ws.write_with_format(row, 0, format!("⚠ {disc_text}").as_str(), &note_fmt)
                        .map_err(|e| format!("{e}"))?;
                }
            }

            ws.set_column_width(0, 18.0).map_err(|e| format!("{e}"))?;
            ws.set_column_width(1, 20.0).map_err(|e| format!("{e}"))?;
            ws.set_column_width(2, 18.0).map_err(|e| format!("{e}"))?;
            ws.set_column_width(3, 14.0).map_err(|e| format!("{e}"))?;
        }
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
            let note = "⚠ ROAS в native-единицах (TRP/GRP + ₽) – несопоставим между \
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
        ws.write_with_format(2, 1, "Базовый спрос", &header_fmt).map_err(|e| format!("{e}"))?;
        for (i, name) in channel_names.iter().enumerate() {
            ws.write_with_format(2, (i + 2) as u16, clean_label(name), &header_fmt).map_err(|e| format!("{e}"))?;
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
        ws.write(explainer_row + 2, 0, "• Базовый спрос – часть KPI без медиа (органический спрос, сезонность, бренд).").map_err(|e| format!("{e}"))?;
        ws.write(explainer_row + 3, 0, "• Медиа-вклад = сумма по каналам. KPI = Базовый спрос + Медиа-вклад (то что модель объясняет).").map_err(|e| format!("{e}"))?;

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

        // Текст шкалы MQS собирается из канона (mqs_tiers::mqs_scale_text),
        // а не пишется числами руками - иначе поведение (grade/tier_line
        // выше в этом файле) и его описание в глоссарии расходятся молча.
        let mqs_glossary_text = format!(
            "Model Quality Score – комплексная оценка качества модели (0-100). {}.",
            mqs_tiers::mqs_scale_text()
        );
        // Волна 3 (2026-06-20): глоссарий из фронта (SSOT glossary.js, 50 терминов
        // {term, definition}). XLSX перестаёт быть «расходящимся глоссарием» —
        // единый источник glossary.js, Rust пассивно пишет переданное. Fallback на
        // встроенные 11 (канон терминологии этого файла, включая mqs_glossary_text
        // из mqs_tiers и «Правдоподобный диапазон» вместо «CI») — только при
        // отсутствии параметра (legacy-вызовы без поля).
        let fallback: &[(&str, &str)] = &[
            ("MQS", mqs_glossary_text.as_str()),
            ("R²", "Коэффициент детерминации – доля дисперсии KPI, объяснённая моделью. 1.0 = идеальная модель."),
            ("MAPE", "Mean Absolute Percentage Error – средняя абсолютная ошибка в %. <10% = отлично."),
            ("R-hat", "Статистика сходимости MCMC. Значение ~1.0 означает, что цепи сошлись. >1.05 = проблема."),
            ("ROI", "Return on Investment – отношение инкрементального вклада канала к его расходу. ROI 2.0x = каждый рубль приносит 2 рубля."),
            ("miROAS", "Marginal incremental ROAS – отдача от каждого СЛЕДУЮЩЕГО рубля. Показывает, стоит ли увеличивать расходы на канал."),
            ("Adstock", "Эффект запаздывания рекламы. TV-реклама влияет на продажи ещё 2-8 недель после показа."),
            ("Hill function", "Функция насыщения. Моделирует убывающую отдачу: первые рубли эффективнее последних."),
            // B1-fix R-07 (2026-07-03): фактический уровень интервалов движка —
            // 90% HDI (utils/posterior_propagation.DEFAULT_HDI_PROB=0.9);
            // «95%» в глоссарии — семейство F-18, не догрепанное b501708.
            ("Правдоподобный диапазон (90% HDI)", "Диапазон, в который истинное значение попадает с 90% вероятностью."),
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
                // Определение приходит с фронта (getAllTerms(), не статически
                // проверяемый тип) - страховка от превышения лимита ячейки Excel.
                ws.write(row, 1, truncate_to_excel_cell_limit(def).as_ref()).map_err(|e| format!("{e}"))?;
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
        // baseline переименован в "Базовый спрос" (Фаза 3 покрытия, 2026-07-25:
        // "Baseline" был голым англицизмом в клиентском XLSX — П8-2), факторы
        // присутствуют как колонки.
        assert_eq!(headers[0], "Базовый спрос");
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
        assert_eq!(headers, vec!["Базовый спрос", "TV"]);
    }

    // ── «Нет числа — нет подписи» (INV-106, 2026-07-26, находка 3) ──────────
    // Регресс-тест на дефект: несчитанный mqs.score превращался в фиктивный
    // 0.0 (`.unwrap_or(0.0)`) и markdown/XLSX печатали приговор модели
    // («Требует доработки», «MQS Score ниже 60») вместо честной отметки, что
    // оценку не считали. Настоящий ноль (mqs.score == Some(0.0)) обязан
    // оставаться валидным значением.

    #[test]
    fn markdown_mqs_absent_shows_honest_text_not_fake_zero() {
        let model = json!({"diagnostics": {}});
        let md = build_markdown(&model, &json!({}), &json!({}));
        assert!(
            md.contains(MQS_ABSENT_TEXT),
            "ожидалась честная формулировка отсутствия MQS в markdown"
        );
        assert!(
            !md.contains("Качество модели (MQS): 0.0"),
            "MQS отсутствует, но markdown печатает фиктивный 0.0 как приговор модели"
        );
        assert!(
            !md.contains("MQS Score на уровне «Слабое» или «Ненадёжное»"),
            "MQS отсутствует - рекомендация про низкий балл не должна печататься"
        );
        assert!(
            !md.contains("MQS Score на уровне «Хорошее» и выше"),
            "MQS отсутствует - рекомендация про высокий балл не должна печататься"
        );
    }

    #[test]
    fn markdown_mqs_present_shows_real_score() {
        // "Хорошее" - валидный канон-ярлык (dословно _MQS_TIERS), как реально
        // присылает бэкенд через utils.diagnostics.mqs_tier_info().
        let model = json!({"diagnostics": {"mqs": {"score": 70.0, "tier_label": "Хорошее"}}});
        let md = build_markdown(&model, &json!({}), &json!({}));
        assert!(md.contains("Качество модели (MQS):** 70.0 – Хорошее"));
        assert!(md.contains("| MQS Score | 70.0 |"));
        assert!(md.contains("| MQS Tier | Хорошее |"));
        assert!(!md.contains(MQS_ABSENT_TEXT));
    }

    #[test]
    fn markdown_mqs_alien_label_is_rejected_derived_from_score() {
        // "Хорошо" - устаревший/чужой ярлык (не "Хорошее" канона _MQS_TIERS).
        // Задача 2 (2026-07-27): внешний ярлык проверяется по набору канона,
        // непустой строки недостаточно - значение вне набора отбрасывается,
        // уровень пересчитывается из посчитанного балла.
        let model = json!({"diagnostics": {"mqs": {"score": 70.0, "tier_label": "Хорошо"}}});
        let md = build_markdown(&model, &json!({}), &json!({}));
        assert!(md.contains("Качество модели (MQS):** 70.0 – Хорошее"));
        assert!(md.contains("| MQS Tier | Хорошее |"));
        assert!(!md.contains("- Хорошо\n"), "чужой ярлык не должен доехать до клиента как есть");
    }

    #[test]
    fn markdown_mqs_real_zero_is_shown_not_treated_as_absent() {
        // Различаем «оценка равна нулю» и «оценки нет» - настоящий ноль
        // валиден и обязан идти в отчёт числом, с полагающейся рекомендацией.
        let model = json!({"diagnostics": {"mqs": {"score": 0.0, "tier_label": "Ненадёжное"}}});
        let md = build_markdown(&model, &json!({}), &json!({}));
        assert!(md.contains("Качество модели (MQS):** 0.0 – Ненадёжное"));
        assert!(
            md.contains("MQS Score на уровне «Слабое» или «Ненадёжное»"),
            "реальный низкий балл 0 (tier poor) обязан триггерить рекомендацию"
        );
        assert!(!md.contains(MQS_ABSENT_TEXT));
    }

    #[test]
    fn markdown_mqs_acceptable_tier_gets_honest_middle_recommendation() {
        // Внешний аудит, Medium (2026-07-27): уровень «Приемлемое» (канон
        // 55 <= score < 70) не получал НИ ОДНОЙ рекомендации - ветвление шло
        // только weak/poor и good/excellent. Молчание в разделе рекомендаций
        // читается клиентом как «замечаний нет» - отсутствие вердикта
        // работало как положительный. Регресс-тест на балле 60 (середина
        // диапазона «Приемлемое»).
        let model = json!({"diagnostics": {"mqs": {"score": 60.0, "tier_label": "Приемлемое"}}});
        let md = build_markdown(&model, &json!({}), &json!({}));
        assert!(
            md.contains("MQS Score на уровне «Приемлемое» – результаты пригодны для ориентировки, но не для точных решений"),
            "MQS 60 (tier acceptable) обязан получить честную среднюю рекомендацию, а не молчание"
        );
        assert!(
            !md.contains("MQS Score на уровне «Слабое» или «Ненадёжное»"),
            "балл 60 - не weak/poor, эта рекомендация не должна печататься"
        );
        assert!(
            !md.contains("MQS Score на уровне «Хорошее» и выше"),
            "балл 60 - не good/excellent, эта рекомендация не должна печататься"
        );
    }

    #[test]
    fn markdown_recommendations_use_short_dash_not_hyphen() {
        // Задача C (2026-07-27): клиентские строки блока РЕКОМЕНДАЦИИ обязаны
        // использовать короткое тире «–», не дефис-минус «-» (гейт гигиены
        // ловит длинное тире «—», дефис не ловит вовсе - фиксируется явным
        // регресс-тестом, а не только гейтом).
        let model = json!({
            "diagnostics": {"mqs": {"score": 40.0, "tier_label": "Слабое"}},
        });
        let decompose = json!({"channels": [{"name": "TV", "roi": 2.0}]});
        let optimize = json!({"expected_lift_pct": 8.0});
        let md = build_markdown(&model, &decompose, &optimize);
        let recs = &md[md.find("## РЕКОМЕНДАЦИИ").expect("раздел рекомендаций обязан быть в отчёте")..];
        assert!(
            !recs.contains(" - "),
            "в разделе рекомендаций остался дефис-минус вместо короткого тире:\n{recs}"
        );
    }

    #[test]
    fn xlsx_mqs_row_absent_is_honest_text() {
        let (cell, grade, tier_line) = mqs_xlsx_row(None, None);
        assert!(matches!(cell, MqsCell::Absent));
        assert_eq!(grade, "");
        assert_eq!(tier_line, MQS_ABSENT_TEXT);
    }

    #[test]
    fn xlsx_mqs_row_present_is_value_with_grade() {
        let (cell, grade, tier_line) = mqs_xlsx_row(Some(70.0), Some("Хорошее"));
        match cell {
            MqsCell::Value(v) => assert_eq!(v, 70.0),
            MqsCell::Absent => panic!("оценка присутствует - ожидался MqsCell::Value"),
        }
        assert_eq!(grade, "Хорошее");
        assert_eq!(tier_line, "MQS Tier: Хорошее");
    }

    #[test]
    fn xlsx_mqs_row_rejects_alien_label_derives_from_score() {
        // "Хорошо" не входит в набор канона ("Хорошее") - grade и tier_line
        // обязаны совпасть и взяться из балла, а не эхом чужого текста.
        let (_cell, grade, tier_line) = mqs_xlsx_row(Some(70.0), Some("Хорошо"));
        assert_eq!(grade, "Хорошее");
        assert_eq!(tier_line, "MQS Tier: Хорошее");
    }

    #[test]
    fn xlsx_mqs_row_missing_label_derives_from_score_not_literal_na() {
        // Балл посчитан, ярлыка от бэкенда нет вовсе (None) - раньше здесь
        // печаталось "N/A" (англицизм); теперь уровень считается из балла.
        let (_cell, grade, tier_line) = mqs_xlsx_row(Some(92.0), None);
        assert_eq!(grade, "Отличное");
        assert_eq!(tier_line, "MQS Tier: Отличное");
        assert!(!tier_line.contains("N/A"));
    }

    #[test]
    fn xlsx_mqs_row_real_zero_is_valid_value_not_absent() {
        let (cell, grade, _tier_line) = mqs_xlsx_row(Some(0.0), Some("Ненадёжное"));
        match cell {
            MqsCell::Value(v) => assert_eq!(v, 0.0),
            MqsCell::Absent => panic!("настоящий ноль - валидное значение, не отсутствие"),
        }
        assert_eq!(grade, "Ненадёжное");
    }

    // ── Перенос из origin/feat/ai-insights-tier2 (2026-08-04) ────────────────

    /// Заголовок плашки надёжности. Пустая строка ⇒ плашки нет (reliable/нет
    /// verdict); прочие verdict дают заголовок.
    #[test]
    fn reliability_label_gates_on_verdict() {
        assert_eq!(reliability_label(""), "");
        assert_eq!(reliability_label("reliable"), "");
        assert_eq!(reliability_label("uncertain"), "Ограниченная надёжность модели");
        assert_eq!(reliability_label("unreliable"), "Модель ненадёжна – переброска отключена");
        assert_eq!(reliability_label("unknown"), "Надёжность модели не подтверждена");
        assert_eq!(reliability_label("какой-то новый"), "Надёжность модели");
    }

    /// Honesty-смягчение вердикта: reliable→директивный; uncertain→«(предв.)»
    /// (направление сохранено); unreliable→нейтрализация.
    #[test]
    fn verdict_display_softens_by_reliability() {
        assert_eq!(verdict_display("Scale", "reliable"), "Увеличить");
        assert_eq!(verdict_display("Scale", ""), "Увеличить");
        assert_eq!(verdict_display("Scale", "uncertain"), "Увеличить (предв.)");
        assert_eq!(verdict_display("Cut", "unknown"), "Остановить (предв.)");
        assert_eq!(verdict_display("Watch", "uncertain"), "Наблюдать");
        assert_eq!(verdict_display("Scale", "unreliable"), "Требует переобучения");
    }

    /// Метки режима анализа + типа KPI. Неизвестное ⇒ пустая строка.
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

    /// Чистка `\n`/двойных пробелов в именах каналов (исходные Excel-заголовки) —
    /// иначе многострочные ячейки и рваный текст в отчёте.
    #[test]
    fn clean_label_collapses_whitespace() {
        assert_eq!(clean_label("Статьи Бюджет \nДО НДС до АК"), "Статьи Бюджет ДО НДС до АК");
        assert_eq!(clean_label("  TV  \n\n Digital "), "TV Digital");
        assert_eq!(clean_label("OLV"), "OLV");
    }

    /// Признак битого ROI: unit_smell ИЛИ маркер артефакта в тексте вердикта.
    #[test]
    fn roi_unreliable_detects_unit_smell_and_verdict_markers() {
        assert!(roi_unreliable(&json!({"unit_smell": true, "verdict": "Scale"})));
        assert!(roi_unreliable(&json!({"verdict": "ROI завышен из-за единиц"})));
        assert!(roi_unreliable(&json!({"verdict": "нереалистичный артефакт"})));
        assert!(!roi_unreliable(&json!({"unit_smell": false, "verdict": "Scale"})));
        assert!(!roi_unreliable(&json!({"verdict": "Hold"})));
    }

    /// Волна 3: глоссарий из фронта (SSOT glossary.js) — путь «у термина есть
    /// ТОЛЬКО short, definition нет» обязан реально попасть на лист «Глоссарий»
    /// через `.or_else(|| item["short"].as_str())` (report.rs, лист Глоссарий).
    /// Соседний тест glossary_xlsx_uses_frontend_terms_when_provided (:2548)
    /// покрывает только путь с полем definition — путь «только short» не был
    /// покрыт никем. Прежняя версия этого теста сравнивала литерал json! сам
    /// с собой, не вызывая build_xlsx вовсе — переписана на настоящую сборку
    /// XLSX и чтение листа «Глоссарий» из zip (приём — как в соседнем тесте).
    #[test]
    fn glossary_from_frontend_extraction() {
        fn xlsx_contains(path: &Path, needle: &str) -> bool {
            let bytes = std::fs::read(path).expect("read xlsx");
            let mut archive = zip::read::ZipArchive::new(Cursor::new(bytes)).expect("open xlsx zip");
            for i in 0..archive.len() {
                let mut entry = archive.by_index(i).expect("zip entry");
                let mut content = String::new();
                if entry.read_to_string(&mut content).is_err() {
                    continue;
                }
                if content.contains(needle) {
                    return true;
                }
            }
            false
        }

        let model = json!({"diagnostics": {"mqs": {"score": 70.0, "tier_label": "Хорошее"}}});
        let decompose = json!({"channels": [
            {"name": "TV", "spend": 100.0, "contribution": 150.0, "roi": 1.5}
        ]});
        let optimize = json!({"channels": [
            {"name": "TV", "current_spend_money": 100.0, "optimal_spend_money": 120.0}
        ]});
        // Термин фронта БЕЗ definition - только short.
        let glossary = json!([
            {"term": "Adstock", "short": "УникальныйКраткийТермин42"},
        ]);

        let path = std::env::temp_dir().join("aurora_glossary_short_only_test.xlsx");
        build_xlsx(&model, &decompose, &optimize, &[], None, "test", &path, Some(&glossary))
            .expect("build_xlsx с glossary (только short)");
        assert!(
            xlsx_contains(&path, "УникальныйКраткийТермин42"),
            "термин с ТОЛЬКО полем short обязан попасть в XLSX через .or_else(short)"
        );
        let _ = std::fs::remove_file(&path);
    }

    /// Мутационно проверено (2026-08-04, при переносе glossary из
    /// ai-insights-tier2): временно закомментировав ветку `if let Some(arr) =
    /// glossary...` в листе «Глоссарий» (build_xlsx) - тест падал на отсутствии
    /// маркерного термина фронта; вернув ветку - тест снова зелёный. Подтверждает,
    /// что параметр glossary реально доезжает до XLSX, а не тонет по пути
    /// econ_export_xlsx → build_xlsx → лист «Глоссарий».
    #[test]
    fn glossary_xlsx_uses_frontend_terms_when_provided() {
        fn xlsx_contains(path: &Path, needle: &str) -> bool {
            let bytes = std::fs::read(path).expect("read xlsx");
            let mut archive = zip::read::ZipArchive::new(Cursor::new(bytes)).expect("open xlsx zip");
            for i in 0..archive.len() {
                let mut entry = archive.by_index(i).expect("zip entry");
                let mut content = String::new();
                // Бинарные записи (напр. brand_mark.png) не UTF-8 - пропускаем, не паникуем.
                if entry.read_to_string(&mut content).is_err() {
                    continue;
                }
                if content.contains(needle) {
                    return true;
                }
            }
            false
        }

        let model = json!({"diagnostics": {"mqs": {"score": 70.0, "tier_label": "Хорошее"}}});
        let decompose = json!({"channels": [
            {"name": "TV", "spend": 100.0, "contribution": 150.0, "roi": 1.5}
        ]});
        // Sheet «Оптимизация» не гейтит conditional-format/chart на пустых
        // channels (в отличие от «ROI каналов»/«Spend vs Effect») - в проде
        // недостижимо (channels = цикл по media_cols ≥ 1), но пустой массив
        // здесь уронил бы диапазон chart (last_row < first_row). Не в объёме
        // переноса glossary - даём непустой optimize.channels, чтобы тест
        // проверял именно глоссарий, а не наступал на этот отдельный пробел.
        let optimize = json!({"channels": [
            {"name": "TV", "current_spend_money": 100.0, "optimal_spend_money": 120.0}
        ]});

        // Без glossary - лист «Глоссарий» обязан показать встроенный fallback-термин.
        let path_none = std::env::temp_dir().join("aurora_glossary_fallback_test.xlsx");
        build_xlsx(&model, &decompose, &optimize, &[], None, "test", &path_none, None)
            .expect("build_xlsx без glossary");
        assert!(
            xlsx_contains(&path_none, "Efficiency Index"),
            "без glossary лист «Глоссарий» обязан показать встроенный fallback-термин"
        );
        let _ = std::fs::remove_file(&path_none);

        // С glossary - термин фронта присутствует, fallback-термин пропадает.
        let glossary = json!([
            {"term": "УникальныйТестТермин42", "definition": "проверка передачи glossary с фронта"},
        ]);
        let path_some = std::env::temp_dir().join("aurora_glossary_frontend_test.xlsx");
        build_xlsx(&model, &decompose, &optimize, &[], None, "test", &path_some, Some(&glossary))
            .expect("build_xlsx с glossary");
        assert!(
            xlsx_contains(&path_some, "УникальныйТестТермин42"),
            "с glossary лист «Глоссарий» обязан показать переданный термин фронта"
        );
        assert!(
            !xlsx_contains(&path_some, "Efficiency Index"),
            "с непустым glossary встроенный fallback-термин не должен появляться"
        );
        let _ = std::fs::remove_file(&path_some);
    }

    /// Разведка 2026-08-07 (scratchpad/pulse_xlsx_reach.md, задача team-lead
    /// "зонд достижимости отказов XLSX") нашла: пустой decompose.channels/
    /// optimize.channels даёт last_row = chs.len() as u32 + 2 = 2, а first_row
    /// хардкожен 3u32 (report.rs, листы «ROI каналов»/«Оптимизация») →
    /// add_conditional_format/insert_chart возвращают Err(RowColumnOrderError),
    /// который через `?` рушит build_xlsx ЦЕЛИКОМ - книга вообще не сохраняется,
    /// клиент не получает файл (ни один из остальных 9+ листов). Достижимость
    /// с обычного UI-пути не доказана (ConfigPanel.svelte блокирует обучение
    /// с 0 каналов), но единственная защита - на фронте, не в бэкенде. Фикс:
    /// гейт `if !chs.is_empty()` вокруг блоков conditional-format/chart на этих
    /// двух листах - на нуле каналов лист собирается без украшений, но книга
    /// сохраняется целиком.
    /// Мутационно проверено (2026-08-07): временно убрав гейт `if
    /// !chs.is_empty()` на обоих листах (условие всегда true) - тест падал на
    /// `result.is_ok()` с текстом "First row or column in range is greater than
    /// last row or column" внутри Err; вернув гейт - тест снова зелёный.
    #[test]
    fn build_xlsx_survives_empty_optimize_and_decompose_channels() {
        let model = json!({"diagnostics": {"mqs": {"score": 70.0, "tier_label": "Хорошее"}}});
        let decompose = json!({"channels": []});
        let optimize = json!({"channels": []});

        let path = std::env::temp_dir().join("aurora_empty_channels_test.xlsx");
        let result = build_xlsx(&model, &decompose, &optimize, &[], None, "test", &path, None);
        assert!(
            result.is_ok(),
            "build_xlsx обязан пережить пустые decompose.channels/optimize.channels и \
             сохранить книгу целиком, а не вернуть Err: {:?}",
            result.err()
        );
        assert!(path.exists(), "книга обязана быть сохранена на диск даже при нуле каналов");
        let meta = std::fs::metadata(&path).expect("read metadata");
        assert!(meta.len() > 0, "сохранённый XLSX не должен быть пустым файлом");
        let _ = std::fs::remove_file(&path);
    }

    /// Та же разведка 2026-08-07: определение термина глоссария приходит с
    /// фронта (getAllTerms(), Value без статической проверки длины) и пишется
    /// в ячейку «Определение» листа «Глоссарий». Excel ограничивает ячейку
    /// 32 767 символами (rust_xlsxwriter MAX_STRING_LEN) - запись более длинной
    /// строки возвращает Err и роняет build_xlsx целиком тем же путём, что и
    /// пустые channels выше. На сейчас (2026-08-07) реальные определения не
    /// длиннее ≈800 символов - но источник не типобезопасен, страховка на
    /// будущее. Фикс: truncate_to_excel_cell_limit() обрезает по границе
    /// символа и дописывает «…», чтобы обрыв был виден клиенту.
    /// Мутационно проверено (2026-08-07): временно заменив вызов
    /// `truncate_to_excel_cell_limit(def).as_ref()` на голый `def` - тест падал
    /// на `result.is_ok()` с текстом "String exceeds Excel's limit of 32,767
    /// characters" внутри Err; вернув обрезку - тест снова зелёный.
    #[test]
    fn glossary_definition_truncated_to_excel_cell_limit() {
        fn xlsx_contains(path: &Path, needle: &str) -> bool {
            let bytes = std::fs::read(path).expect("read xlsx");
            let mut archive = zip::read::ZipArchive::new(Cursor::new(bytes)).expect("open xlsx zip");
            for i in 0..archive.len() {
                let mut entry = archive.by_index(i).expect("zip entry");
                let mut content = String::new();
                if entry.read_to_string(&mut content).is_err() {
                    continue;
                }
                if content.contains(needle) {
                    return true;
                }
            }
            false
        }

        let model = json!({"diagnostics": {"mqs": {"score": 70.0, "tier_label": "Хорошее"}}});
        let decompose = json!({"channels": [
            {"name": "TV", "spend": 100.0, "contribution": 150.0, "roi": 1.5}
        ]});
        let optimize = json!({"channels": [
            {"name": "TV", "current_spend_money": 100.0, "optimal_spend_money": 120.0}
        ]});

        // > предела ячейки Excel (32 767 симв.) - кириллица, чтобы проверить
        // обрезку именно по границе символа (chars()), не байтов.
        let too_long_def = "д".repeat(40_000);
        let glossary = json!([
            {"term": "СлишкомДлинныйТермин", "definition": too_long_def},
        ]);
        let path = std::env::temp_dir().join("aurora_glossary_overflow_test.xlsx");
        let result = build_xlsx(&model, &decompose, &optimize, &[], None, "test", &path, Some(&glossary));
        assert!(
            result.is_ok(),
            "build_xlsx обязан пережить определение глоссария длиннее лимита ячейки Excel: {:?}",
            result.err()
        );

        let expected_truncated = format!("{}…", "д".repeat(32_766));
        assert!(
            xlsx_contains(&path, &expected_truncated),
            "определение обязано быть обрезано ровно до лимита ячейки Excel (32767 симв. \
             включая завершающее многоточие)"
        );
        assert!(
            !xlsx_contains(&path, &too_long_def),
            "исходное необрезанное определение (40000 симв.) не должно попасть в ячейку - \
             иначе запись вернула бы Err и книга не сохранилась бы"
        );
        let _ = std::fs::remove_file(&path);
    }

    /// 2026-08-07/08: рассинхрон диагностики и оптимизации
    /// (diagnostics_optimization_diverged) — предупреждение обязано появиться в
    /// Markdown И в XLSX по любой из двух половин: (а) разные model_fingerprint,
    /// (б) те же подписи, но разошлись вердикты model_reliability (случай
    /// tools/recompute_mqs.py — диагностика пересчиталась без переобучения).
    /// Молчим, если обе стороны совпадают, и если сверяемого поля нет вовсе
    /// (старый проект). Мутационно проверено (обязательный шаг для этого
    /// проекта): временно заставив diagnostics_optimization_diverged всегда
    /// возвращать false - все ветки "должны предупредить" (и по подписи, и по
    /// вердикту) падали ровно на отсутствии текста предупреждения; вернув
    /// логику - тест снова зелёный.
    #[test]
    fn model_optimization_fingerprint_mismatch_warns_in_both_formats() {
        fn xlsx_contains(path: &Path, needle: &str) -> bool {
            let bytes = std::fs::read(path).expect("read xlsx");
            let mut archive = zip::read::ZipArchive::new(Cursor::new(bytes)).expect("open xlsx zip");
            for i in 0..archive.len() {
                let mut entry = archive.by_index(i).expect("zip entry");
                let mut content = String::new();
                if entry.read_to_string(&mut content).is_err() {
                    continue;
                }
                if content.contains(needle) {
                    return true;
                }
            }
            false
        }

        let decompose = json!({"channels": [
            {"name": "TV", "spend": 100.0, "contribution": 150.0, "roi": 1.5}
        ]});
        let optimize_channels = json!([
            {"name": "TV", "current_spend_money": 100.0, "optimal_spend_money": 120.0}
        ]);

        // Расходятся: диагностика и оптимизация - от разных моделей.
        let model_a = json!({"diagnostics": {"model_fingerprint": "aa".repeat(32)}});
        let optimize_b = json!({"model_fingerprint": "bb".repeat(32), "channels": optimize_channels});
        let md_diverge = build_markdown(&model_a, &decompose, &optimize_b);
        assert!(
            md_diverge.contains(FINGERPRINT_MISMATCH_TEXT),
            "Markdown обязан предупредить при разных model_fingerprint"
        );
        let path_diverge = std::env::temp_dir().join("aurora_fingerprint_diverge_test.xlsx");
        build_xlsx(&model_a, &decompose, &optimize_b, &[], None, "test", &path_diverge, None)
            .expect("build_xlsx diverge");
        assert!(
            xlsx_contains(&path_diverge, FINGERPRINT_MISMATCH_TEXT),
            "XLSX обязан предупредить при разных model_fingerprint"
        );
        let _ = std::fs::remove_file(&path_diverge);

        // Совпадают: молчим.
        let model_same = json!({"diagnostics": {"model_fingerprint": "cc".repeat(32)}});
        let optimize_same = json!({"model_fingerprint": "cc".repeat(32), "channels": optimize_channels});
        let md_same = build_markdown(&model_same, &decompose, &optimize_same);
        assert!(
            !md_same.contains(FINGERPRINT_MISMATCH_TEXT),
            "Markdown не должен предупреждать при одинаковых model_fingerprint"
        );
        let path_same = std::env::temp_dir().join("aurora_fingerprint_same_test.xlsx");
        build_xlsx(&model_same, &decompose, &optimize_same, &[], None, "test", &path_same, None)
            .expect("build_xlsx same");
        assert!(
            !xlsx_contains(&path_same, FINGERPRINT_MISMATCH_TEXT),
            "XLSX не должен предупреждать при одинаковых model_fingerprint"
        );
        let _ = std::fs::remove_file(&path_same);

        // Поля нет вовсе (старый проект): молчим.
        let model_absent = json!({"diagnostics": {}});
        let optimize_absent = json!({"channels": optimize_channels});
        let md_absent = build_markdown(&model_absent, &decompose, &optimize_absent);
        assert!(
            !md_absent.contains(FINGERPRINT_MISMATCH_TEXT),
            "Markdown не должен предупреждать когда поле отсутствует (старый проект)"
        );
        let path_absent = std::env::temp_dir().join("aurora_fingerprint_absent_test.xlsx");
        build_xlsx(&model_absent, &decompose, &optimize_absent, &[], None, "test", &path_absent, None)
            .expect("build_xlsx absent");
        assert!(
            !xlsx_contains(&path_absent, FINGERPRINT_MISMATCH_TEXT),
            "XLSX не должен предупреждать когда поле отсутствует (старый проект)"
        );
        let _ = std::fs::remove_file(&path_absent);

        // Подписи совпадают, но вердикты надёжности разошлись (случай
        // tools/recompute_mqs.py: диагностика пересчиталась без переобучения
        // модели) - предупреждение обязано появиться.
        let model_verdict_diverge = json!({"diagnostics": {
            "model_fingerprint": "dd".repeat(32),
            "model_reliability": {"verdict": "uncertain"}
        }});
        let optimize_verdict_diverge = json!({
            "model_fingerprint": "dd".repeat(32),
            "model_reliability": {"verdict": "reliable"},
            "channels": optimize_channels
        });
        let md_verdict_diverge = build_markdown(&model_verdict_diverge, &decompose, &optimize_verdict_diverge);
        assert!(
            md_verdict_diverge.contains(FINGERPRINT_MISMATCH_TEXT),
            "Markdown обязан предупредить при разных вердиктах model_reliability \
             (подписи модели те же)"
        );
        let path_verdict_diverge = std::env::temp_dir().join("aurora_verdict_diverge_test.xlsx");
        build_xlsx(&model_verdict_diverge, &decompose, &optimize_verdict_diverge, &[], None, "test", &path_verdict_diverge, None)
            .expect("build_xlsx verdict diverge");
        assert!(
            xlsx_contains(&path_verdict_diverge, FINGERPRINT_MISMATCH_TEXT),
            "XLSX обязан предупредить при разных вердиктах model_reliability \
             (подписи модели те же)"
        );
        let _ = std::fs::remove_file(&path_verdict_diverge);

        // Подписи и вердикты совпадают: молчим.
        let model_verdict_same = json!({"diagnostics": {
            "model_fingerprint": "ee".repeat(32),
            "model_reliability": {"verdict": "reliable"}
        }});
        let optimize_verdict_same = json!({
            "model_fingerprint": "ee".repeat(32),
            "model_reliability": {"verdict": "reliable"},
            "channels": optimize_channels
        });
        let md_verdict_same = build_markdown(&model_verdict_same, &decompose, &optimize_verdict_same);
        assert!(
            !md_verdict_same.contains(FINGERPRINT_MISMATCH_TEXT),
            "Markdown не должен предупреждать при одинаковых вердиктах model_reliability"
        );
        let path_verdict_same = std::env::temp_dir().join("aurora_verdict_same_test.xlsx");
        build_xlsx(&model_verdict_same, &decompose, &optimize_verdict_same, &[], None, "test", &path_verdict_same, None)
            .expect("build_xlsx verdict same");
        assert!(
            !xlsx_contains(&path_verdict_same, FINGERPRINT_MISMATCH_TEXT),
            "XLSX не должен предупреждать при одинаковых вердиктах model_reliability"
        );
        let _ = std::fs::remove_file(&path_verdict_same);

        // Вердикта нет в диагностике (старый проект), в оптимизации есть:
        // молчим - ложная тревога у существующих клиентов дороже пропуска.
        let model_verdict_absent = json!({"diagnostics": {
            "model_fingerprint": "ff".repeat(32)
        }});
        let optimize_verdict_absent = json!({
            "model_fingerprint": "ff".repeat(32),
            "model_reliability": {"verdict": "reliable"},
            "channels": optimize_channels
        });
        let md_verdict_absent = build_markdown(&model_verdict_absent, &decompose, &optimize_verdict_absent);
        assert!(
            !md_verdict_absent.contains(FINGERPRINT_MISMATCH_TEXT),
            "Markdown не должен предупреждать когда вердикта нет в диагностике \
             (старый проект)"
        );
        let path_verdict_absent = std::env::temp_dir().join("aurora_verdict_absent_test.xlsx");
        build_xlsx(&model_verdict_absent, &decompose, &optimize_verdict_absent, &[], None, "test", &path_verdict_absent, None)
            .expect("build_xlsx verdict absent");
        assert!(
            !xlsx_contains(&path_verdict_absent, FINGERPRINT_MISMATCH_TEXT),
            "XLSX не должен предупреждать когда вердикта нет в диагностике \
             (старый проект)"
        );
        let _ = std::fs::remove_file(&path_verdict_absent);

        // Регистр вердиктов различается ("Uncertain" vs "uncertain") - это
        // один и тот же вердикт, сверка регистронезависима: молчим.
        let model_verdict_case = json!({"diagnostics": {
            "model_fingerprint": "gg".repeat(32),
            "model_reliability": {"verdict": "Uncertain"}
        }});
        let optimize_verdict_case = json!({
            "model_fingerprint": "gg".repeat(32),
            "model_reliability": {"verdict": "uncertain"},
            "channels": optimize_channels
        });
        let md_verdict_case = build_markdown(&model_verdict_case, &decompose, &optimize_verdict_case);
        assert!(
            !md_verdict_case.contains(FINGERPRINT_MISMATCH_TEXT),
            "Markdown не должен предупреждать при различии только в регистре \
             вердикта ('Uncertain' vs 'uncertain')"
        );
        let path_verdict_case = std::env::temp_dir().join("aurora_verdict_case_test.xlsx");
        build_xlsx(&model_verdict_case, &decompose, &optimize_verdict_case, &[], None, "test", &path_verdict_case, None)
            .expect("build_xlsx verdict case-insensitive");
        assert!(
            !xlsx_contains(&path_verdict_case, FINGERPRINT_MISMATCH_TEXT),
            "XLSX не должен предупреждать при различии только в регистре \
             вердикта ('Uncertain' vs 'uncertain')"
        );
        let _ = std::fs::remove_file(&path_verdict_case);
    }
}
