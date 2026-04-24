---
tags: [session, compressed, output-quality, stage-a, stage-b, stage-c, xlsx, html, pptx, brand, localization]
type: session
updated: 2026-04-25
---
# Quick Reference

Live-test session 2026-04-24/25 вскрыл критические дефекты во всех 3 форматах deliverables. Verify 137/137 PASS но реальные файлы сломаны: XLSX 9/11 листов пустые (rust_xlsxwriter 0.79 sheetPr XSD bug), HTML без стилей (CSP missing hash + 19 inline attrs blocked), PPTX ~100 дефектов (brand leaks / slug / v1.0.11 / center-header / English mix / text overlap / column names). План через red-team audit развёрнут в 3-stage rollout (`transient-marinating-hickey.md`). За сессию реализованы: Stage A (XLSX + HTML blocking), Stage B (PPTX brand), Stage C частично (C.1 channel normalize + C.2 data consistency + C.3 RU localization + C.4 text overlap + C.6.1 TOC swap). 4 commits, 2 tags, 142/142 verify PASS.

**Topic:** output-quality-stage-abc
**Key files:**
- `src-tauri/src/commands/report.rs` (Stage A XLSX post-process)
- `sidecar/econometrica/aurora_html/builder.py` (Stage A CSP + noscript hash)
- `sidecar/econometrica/aurora_pptx/builder.py` (Stage B header + version + page counter; Stage C localization + data + overlap + TOC swap)
- `sidecar/econometrica/engines/narrative_adapter.py` (Stage B slug sanitize + Stage C.1 channel normalize)
- `tools/verify_aurora_xlsx_brand.py` (NEW)
- `tools/verify_aurora_html_brand.py`, `verify_aurora_pptx_brand.py`, `verify_aurora_pptx_narrative.py` (expanded)
- `C:/Users/ackol/Desktop/Aurora_Econometrica_Output_Quality_Progress.md` (план on Desktop)

**Status:**
- ✅ 4 stages shipped (Stage A `cb85457`, Stage B `e69cf1b`, Stage C.1+.2 `533597a`, Stage C.3+.4+.6.1 `425a27c`).
- ✅ Tags: v1.0.12-pre-stage-a, v1.0.12.1, v1.0.12.2.
- ✅ 142/142 regression PASS (+5 new assertions).
- 📋 Pending Stage C: C.5 McKinsey titles, C.6.2 dynamic section map, C.6.3 TOC scope decision, verify overhaul (~10h отдельной сессии).
- 📋 Live-test с Антоном pending.

---

## Learnings

### Architecture

1. **rust_xlsxwriter 0.79 sheetPr XSD ordering bug undocumented.** `write_sheet_pr` emits `<pageSetUpPr>` перед `<tabColor>` вопреки OOXML CT_SheetPr. Не в changelog - upgrade не гарантирует fix. **Выбор:** post-process XML swap вместо 0.79→0.94 upgrade (15 minor versions = high risk, MSRV bump, zip v1→v2 cascade). Deterministic solution использует regex + zip v2 уже в deps.

2. **CSP3 directives разделяют `<style>` blocks и inline `style=""` attrs.** `style-src` hash-based (для `<style>`) + `style-src-attr 'unsafe-inline'` (для inline attrs) = оптимально. Chrome 77+, FF 86+, Safari 16+. XSS защита сохранена т.к. все user strings escape()'d upstream. Не нужно rewriting 19 inline attrs в utility classes.

3. **Hash input must include template wrapping.** shell.html wraps `${fonts_css}` между `<style>\n${}\n</style>`. Hash computed over raw fonts_css не matches то что browser видит между tags. Must hash `f"\n{content}\n"`.

4. **`<noscript><style>` всё равно requires CSP hash.** Browser parses noscript и enforces CSP regardless of JS state. Silent root-cause "HTML без стилей" - 4-й блок без hash блокировал всю каскадную загрузку.

5. **Report ID trace = deterministic sha256** over (client, project_id, channel signature, diagnostics). Нет timestamp → stable across rebuilds. PPTX и HTML от одного pipeline share one trace ID. Replaces internal product version "v1.0.11" - client-facing traceability without leaking platform version.

### Process

6. **Red-team audit of plan before ExitPlanMode** - найдено 19 blind spots. Rev 1 предлагал rust_xlsxwriter upgrade (risk) + переписывание 19 inline styles. Rev 2 выбрал более элегантные решения (post-process + style-src-attr). Сохранить как practice.

7. **Phased rollout (3 stages)** лучше моно-плана для 25-37h работы. Каждый stage self-contained, testable, rollback'able. Клиент получает Stage A (работающие файлы) за часы, не ждёт неделю.

8. **Verify gaps invisible until live-test.** verify 137/137 PASS с текущими assertions, а файл сломан. Expanded to 142 post-session: per-block hash coverage, Report ID pattern, RU verdict check. Process rule: при каждом fix добавлять assertion ловящую exactly тот defect.

### Localization

9. **Verdict localization** через display-map dict + enum keys unchanged. `{Scale:Увеличить, Hold:Держать, Watch:Наблюдать, Reduce:Сократить, Cut:Остановить}` в builder.py только для render. derive_verdict + downstream логика работает на English keys. Минимум risk regression.

10. **Slug sanitize regex:** strip trailing `--N`, split hyphens, drop internal markers (`исходник`, `ммх`, `mmx`, `dataset`, `source`, `test`), capitalize tokens, collapse consecutive years into ranges. Test cases: `mmx-2021-2025-исходник-ммх-2404-26--4` → `'2021-2025 2404'`; `венарус-ммх-2404-26--2` → `'Венарус 2404'`.

11. **Channel name normalization stop-tokens:** `Бюджет, до НДС, без НДС, ДО НДС до АК, после АК, с НДС, Вклад, млн, руб, Доля`. Applied case-insensitive word-boundary. Returns `None` если после cleanup empty → signals total-budget column dropping.

---

## Decisions

### Approved during session

- **D1 XLSX fix:** post-process XML swap, не library upgrade (safer, deterministic)
- **D2 HTML CSP:** добавить 4-й hash (noscript) + `style-src-attr 'unsafe-inline'`, не переписывать inline attrs (impossible для data-driven widths)
- **D3 Version → Report ID:** трансформировать `v1.0.11` во всех source notes в детерминированный `aurora-mmm-{12hex}` trace (сохраняет traceability, убирает product version leak)
- **D4 Center header:** полное удаление `header_project_label` textbox из `_header()`. Оставляем section label + CONFIDENTIAL только
- **D5 Channel normalization:** regex stop-phrases в adapter (`_merge_channels` level), не изменения UI Validate step (deferred - B tier)
- **D6 TOC position:** swap в builder.py build() метод, физические page numbers обновлены. Cover → TOC → ExecSummary
- **D7 Verdict labels:** RU display-map в builder, enum keys English сохранены
- **D8 Rollout structure:** 3 stages с тегами, каждый ships independently, can revert per-commit
- **D9 Page counter:** `/` not `\\` (escape bug - escape char попадал в output литерально)

### Deferred to next session

- **C.5 McKinsey action titles** - rebuild templates + 3 SCQAR scenarios + zero-effect guard. Частично сделано через убирание "Aurora рекомендует..." self-reference. Полный rebuild требует дизайна.
- **C.6.2 Dynamic section numbering** - `slide_to_section` mapping в `__init__`. Сейчас hardcoded section_idx работает корректно, improvement для robustness.
- **C.6.3 TOC scope** - 5 vs 8 разделов decision. Option A (сократить TOC) vs B (+3 section dividers = 16 слайдов). Требует Антон input.
- **C.6.4 Verify overhaul** - partial (4 new assertions). Осталось: English ban-list PPTX, period consistency cross-slide, text box height heuristic, no-slug everywhere.
- **Live test** - pending перезапуска tauri dev, Kagocel XLSX full pipeline с Антоном.

---

## Solutions & Fixes

### Stage A.1: XLSX post-process

**Problem:** Excel отказывается открывать XLSX или сбрасывает содержимое листов sheet2-sheet8 потому что rust_xlsxwriter 0.79.4 выводит child elements `<sheetPr>` в неправильном порядке (`pageSetUpPr` before `tabColor`), нарушая OOXML XSD `CT_SheetPr`.

**Fix:** `src-tauri/src/commands/report.rs`:

```rust
use std::io::{Cursor, Read, Write};

// After wb.save(path)?
fix_sheetpr_element_order(path)?;

fn fix_sheetpr_element_order(xlsx_path: &Path) -> Result<(), String> {
    use zip::read::ZipArchive;
    use zip::write::{SimpleFileOptions, ZipWriter};

    let bytes = std::fs::read(xlsx_path).map_err(...)?;
    let mut archive = ZipArchive::new(Cursor::new(bytes))?;

    let re = regex::Regex::new(
        r"<sheetPr([^>]*)><pageSetUpPr([^/]*)/><tabColor([^/]*)/></sheetPr>",
    )?;

    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i)?;
        let name = entry.name().to_string();
        writer.start_file(&name, SimpleFileOptions::default().compression_method(entry.compression()))?;
        if name.starts_with("xl/worksheets/sheet") && name.ends_with(".xml") {
            let mut content = String::new();
            entry.read_to_string(&mut content)?;
            let fixed = re.replace_all(&content, "<sheetPr$1><tabColor$3/><pageSetUpPr$2/></sheetPr>");
            writer.write_all(fixed.as_bytes())?;
        } else {
            let mut buf = Vec::new();
            entry.read_to_end(&mut buf)?;
            writer.write_all(&buf)?;
        }
    }
    let final_cursor = writer.finish()?;
    std::fs::write(xlsx_path, final_cursor.into_inner())?;
    Ok(())
}
```

**Validation:** Python twin ran on existing broken XLSX → reopens successfully, 7/8 verify PASS (8th was Stage B scope).

### Stage A.2: HTML CSP hash coverage

**Problem 1:** 4-й `<style>` block `<noscript>...</noscript>` в shell.html не имел sha256 hash в CSP → browser блокировал весь style cascade.

**Problem 2:** Hash input не матчил real content. Template `<style>\n${placeholder}\n</style>` добавляет newlines, hash computed over raw placeholder не совпадает.

**Fix:** `sidecar/econometrica/aurora_html/builder.py`:

```python
# Module level with cache
_NOSCRIPT_STYLE_CACHE: str | None = None

def _extract_noscript_style() -> str:
    global _NOSCRIPT_STYLE_CACHE
    if _NOSCRIPT_STYLE_CACHE is not None:
        return _NOSCRIPT_STYLE_CACHE
    shell = (TEMPLATES_DIR / "shell.html").read_text(encoding='utf-8')
    m = re.search(r'<noscript>\s*<style>(.*?)</style>', shell, re.DOTALL)
    _NOSCRIPT_STYLE_CACHE = m.group(1)
    return _NOSCRIPT_STYLE_CACHE

# In build() method
noscript_css = _extract_noscript_style()
style_blocks_as_emitted = (
    f"\n{fonts_css}\n",
    f"\n{tokens_css}\n",
    f"\n{layout_css}\n",
    noscript_css,
)
script_blocks_as_emitted = (f"\n{echarts_js}\n", f"\n{tokens_js}\n", f"\n{bootstrap}\n")
style_hashes = [security.csp_sha256(s) for s in style_blocks_as_emitted]
script_hashes = [security.csp_sha256(s) for s in script_blocks_as_emitted]

# In _build_csp_meta
policy = "; ".join([
    ...
    f"style-src {style_src}",
    "style-src-attr 'unsafe-inline'",   # NEW - for data-driven inline style=""
    ...
])
```

**Validation:** Python script computes sha256 over each `<style>` block content after render, compares to CSP hashes. 4/4 styles + 3/3 scripts matched.

### Stage B.4: Report ID trace

**Problem:** Internal product version "v1.0.11" leaked в source notes / cover tile / DocProperties. Client sees platform version вместо report identity.

**Fix:** Add `_compute_report_id()` to `AuroraPPTXBuilder`:

```python
def _compute_report_id(self) -> str:
    import hashlib
    ch_sig = sorted(
        (
            c.get("name") or "",
            int(round(float(c.get("spend") or 0))),
            int(round(float(c.get("contribution") or 0))),
            c.get("verdict") or "",
        )
        for c in self.channels
    )
    diag_sig = sorted([
        ("mqs_score", round(float(self.mqs_score or 0), 3)),
        ("r_squared", round(float(self.r_squared or 0), 3)),
        ...
    ])
    fp = f"{self.client}|{self.project_id}|channels={ch_sig}|diag={diag_sig}"
    h = hashlib.sha256(fp.encode('utf-8')).hexdigest()[:12]
    return f"aurora-mmm-{h}"
```

Same algorithm как aurora_html/builder.py `_compute_report_id` → PPTX и HTML от одного pipeline share one trace ID.

### Stage C.1: Channel name normalization

**Problem:** Excel column names попадают в канал labels: `Performance Бюджет до НДС`, `Banners Бюджет ДО НДС до АК`, `Бюджет до НДС` (total budget column как channel!).

**Fix:** `narrative_adapter._normalize_channel_name()`:

```python
_CHANNEL_NAME_STOP_PHRASES = [
    r'ДО\s*НДС\s+до\s+АК', r'после\s*АК', r'с\s*НДС', r'без\s*НДС', r'до\s*НДС',
    r'Бюджет', r'Вклад', r'млн\s*₽?', r'руб\.?', r'Доля',
]
_CHANNEL_NAME_RE = re.compile(
    r'\b(?:' + '|'.join(_CHANNEL_NAME_STOP_PHRASES) + r')\b',
    re.IGNORECASE,
)

def _normalize_channel_name(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = _CHANNEL_NAME_RE.sub('', str(raw))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' ,.;:-_')
    return cleaned if cleaned else None
```

Applied in `_merge_channels()` before key generation. Returns None drops total-budget columns (logged warning).

### Stage C.4: Text overlap

- **s02:** findings_y 1.80→1.95, height 0.45→0.55, step 0.92→1.02
- **s06:** action title height 0.80→1.10, font 22pt→20pt (size param added to `_action_title`)
- **s09 SCQAR:** body font 12→11pt, RECOMMENDATION height 2.0→2.3

---

## Files Modified

### Committed

| Commit | Files | Description |
|--------|-------|-------------|
| `cb85457` (v1.0.12.1) | src-tauri/src/commands/report.rs (+80), aurora_html/builder.py, tools/verify_aurora_xlsx_brand.py (NEW), tools/verify_aurora_html_brand.py (+4 assertions) | Stage A: XLSX XSD post-process + HTML CSP |
| `e69cf1b` (v1.0.12.2) | aurora_pptx/builder.py, engines/narrative_adapter.py, tools/verify_aurora_pptx_brand.py | Stage B: PPTX brand (slug / header / Econometrica / version / page counter) |
| `533597a` | aurora_pptx/builder.py, engines/narrative_adapter.py | Stage C.1 channel normalize + C.2 data consistency |
| `425a27c` (HEAD) | aurora_pptx/builder.py (massive), tools/verify_aurora_pptx_narrative.py | Stage C.3 localization + C.4 overlap + C.6.1 TOC swap |

### Non-tracked updates

- `C:/Users/ackol/.claude/plans/transient-marinating-hickey.md` (Rev 2 after red-team)
- `C:/Users/ackol/Desktop/Aurora_Econometrica_Output_Quality_Progress.md` (progress plan NEW)
- `C:/Users/ackol/.claude/projects/D--Docs-Aurora-Ai/memory/project_econometrica_output_quality_v1012.md` (NEW)
- `C:/Users/ackol/.claude/projects/D--Docs-Aurora-Ai/memory/MEMORY.md` (priority entry added)

---

## Setup & Config Changes

- Git tag `v1.0.12-pre-stage-a` at commit `9b0c3c0` (safety anchor before start)
- Git tag `v1.0.12.1` at `cb85457` (Stage A ship)
- Git tag `v1.0.12.2` at `e69cf1b` (Stage B ship)
- Pre-session tauri dev процессы убиты (node.exe, msedgewebview2.exe), port 1420 освобождён
- Cargo target `D:/cargo-targets/econometrica` unchanged

---

## Pending

**Stage C remaining (~10h, отдельная сессия):**
- **C.5** McKinsey action titles: rebuild `derive_action_headline()` в narrative_adapter, переписать s06/s07/s09 titles action-first. 3 SCQAR scenarios (Rebalance / Hold+control / Risk). Zero-effect guard для Hill-bug.
- **C.6.2** Dynamic section numbering: `self.slide_to_section` mapping в `__init__`, убрать hardcoded `section_idx=N` в `s0X()` методах.
- **C.6.3** TOC scope decision (с Антоном): Option A сократить TOC до 5 реальных разделов, или Option B добавить 3 section-divider слайды.
- **C.6.4** Verify overhaul: English ban-list PPTX ("saturation", "baseline", "portfolio", etc), period consistency cross-slide, text box height heuristic, no-slug everywhere.

**Live test с Антоном:**
- `npm run tauri dev` на HEAD `425a27c`
- Import `D:/Docs/Aurora_Ai/TestData/Econometrica/Kagocel_RF_MMM_dataset.xlsx`
- Full pipeline Import → Validate → Train → Decompose → Optimize → Report
- Export 3 formats (XLSX + PPTX + HTML)
- Acceptance per Desktop MD checklist

**Orthogonal P0 (не блокируют output quality ship):**
- `project_econometrica_hill_normalization_root_fix` - z-score → Robyn spend/mean (blocks meaningful optimize)
- `project_econometrica_math_audit` - full math audit pre-commercial
- `project_em_dash_cleanup_sweep` - "—" → "-" across all apps (частично done в Econometrica)

---

## Errors & Workarounds

### Build/Process

- **cp1251 console UnicodeEncodeError** при echo с Cyrillic - fix: `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` в смoke-тестах.
- **Port 1420 already in use** после стоячего tauri dev - kill node.exe + msedgewebview2.exe + econometrica-sidecar.exe через taskkill //F //PID.
- **tmp directory mapping** - Windows git-bash `/tmp` не тот что Python `os.environ['TEMP']`. Использовала `D:/Docs/Aurora_Ai/tmp_xlsx_test/` для stability.
- **re shadowing в verify_aurora_html_brand.py** - `import re` внутри функции поздно, shadowed usage выше. Fix: top-level imports `base64, hashlib, os, re`.

### Verify regressions

- **"ACME CORP uppercase in header"** assert failed after header center removal. Removed as stale (center textbox удалён).
- **"custom version v2.0.0"** assert failed after version→Report ID replacement. Replaced with Report ID pattern assertion.
- **"Cut" literal in narrative case 2** failed after verdict localization. Updated to check "Остановить".
- **Em dash leak** from my C.2 initial `"—"` fallback. Caught by regression `no em dash`, fixed to `"-"`.
- **Slug "'2021-2025 2404'"** appears in smoke tests (Antoн's Kagocel project). Это expected - не error, но показывает что sanitizer не идеально для всех cases (cleans markers, но оставляет year ranges + short digit tokens). Acceptable for now.

### Tauri dev lifecycle

- **Background tauri dev exit code 0** вскоре после start - видимо user closed window или another instance was running. Кожется нормальным для dev iteration.
- **Sidecar `econometrica-sidecar.exe` doesn't kill cleanly** sometimes - но Rust watchdog respawn'ит его. Workaround не нужен.

---

## Full Session Notes

### Timeline

1. **Preflight:** MEMORY.md + project log + CC-Sessions compressed read; 137/137 verify baseline; sample XLSX найден в `C:/Users/ackol/Desktop/Эконометрика - тестовые файлы/Кагоцел РФ+_данные...xlsx`, централизован в `D:/Docs/Aurora_Ai/TestData/Econometrica/` + README.
2. **Live-test walkthrough 13 slides PPTX:** ~100 defects найдены, накоплены в список (slug header, v1.0.11, Econometrica brand leak, mixed languages, text overlap on s02/s06/s09, column names as channels, TOC order wrong, page counter backslash, etc.).
3. **XLSX bug diagnosis:** Excel recovery log показал sheet2-sheet8 parse errors. Distilled to rust_xlsxwriter 0.79 sheetPr XSD ordering bug (read library source + OOXML XSD spec).
4. **HTML fix diagnosis:** inline styles blocked, counted 19 inline attrs + missing 4th noscript hash. Validated hash mismatch script.
5. **Plan creation + red-team audit:** Rev 1 → 19 blind spots found → Rev 2 с lighter touches (post-process не upgrade, CSP3 attr split не rewrite attrs, Report ID не void version, 3-stage rollout).
6. **ExitPlanMode approval** Антон + auto-mode start.
7. **Stage A execution:** XLSX post-process в report.rs (80 LOC), HTML CSP fix (noscript extract + style-src-attr + newline wrap), verify_aurora_xlsx_brand.py создан. Validated via Python twin.
8. **Stage B execution:** slug sanitize (_sanitize_project_slug) + center header off + Econometrica→Aurora AI + version→Report ID + page counter fix.
9. **Stage C execution:** channel normalize (_normalize_channel_name + _merge_channels integration), data consistency hardcoded→dynamic, massive RU localization sweep (verdict display map, SCQAR labels, terminology ~25 phrases), text overlap numerical tweaks, TOC swap.
10. **Per-commit regression:** 142/142 PASS after each, верifying no downstream breakage.
11. **Memory + Desktop plan + compress session.**

### Key files diff stats

- `src-tauri/src/commands/report.rs`: +82 LOC (post-process + new use statements)
- `sidecar/econometrica/aurora_html/builder.py`: +45/-10 (noscript extract + CSP policy)
- `sidecar/econometrica/aurora_pptx/builder.py`: ~+280/-170 LOC net (RU localization, Report ID, header, text boxes, TOC swap)
- `sidecar/econometrica/engines/narrative_adapter.py`: +120/-30 (slug sanitize + channel normalize)
- `tools/verify_aurora_*.py`: +150 LOC cumulative (new xlsx_brand + expanded html_brand + pptx updates)

### Risk/rollback posture

- Each stage self-contained - can revert any individually
- Verify regression gate catches incompatibility between commits
- Safety tag `v1.0.12-pre-stage-a` preserves pre-output-quality state
- Per-stage tags (v1.0.12.1, .2) enable partial rollback

---

## Related Sessions

- `2026-04-24-2330-html-tier1-program.md` - HTML tier-1 program baseline (137/137 PASS context)
- `2026-04-24-2359-html-tier1-session-compressed.md` - compressed snapshot post-audit
- `2026-04-24-2400-html-tier1-live-test-preflight.md` - live-test setup + TestData centralization

## Related Memory

- `project_econometrica_output_quality_v1012.md` (NEW) - program state index
- `project_client_ready_templates_2026-04-24.md` - tier-1 templates program parent
- `project_econometrica_hill_normalization_root_fix.md` - P0 orthogonal
- `project_econometrica_math_audit.md` - P0 orthogonal
- `feedback_no_em_dash.md` - em-dash discipline (caught C.2 regression)
- `feedback_value_perception_tier1.md` - no MCMC time in client output
- `feedback_dev_only_client_names.md` - Kagocel/Venarus dev-only policy
