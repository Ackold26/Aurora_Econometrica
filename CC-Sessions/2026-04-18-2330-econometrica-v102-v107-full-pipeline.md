---
tags: [session, compressed, audit, dual-mode, insights, export, adstock, pptx, xlsx]
type: session
updated: 2026-04-18
---
# Quick Reference
Самая масштабная сессия Econometrica: 7 коммитов (v1.0.2→v1.0.7), 50+ файлов, все 12 фаз Next-Gen Plan реализованы. Ключевое: 13 незарегистрированных команд подключены, ребрендинг Analytics Hub→Econometrica, offline insights engine (30 правил), dual-mode (marketer/expert), miROAS, XLSX 6 листов с формулами+charts, PPTX 8 слайдов, Claude AI Tier 2, model versioning, ECharts lazy-init, adstock auto-select via BIC. Все Obsidian Mistakes верифицированы и покрыты.

Topic: Econometrica v1.0.2-v1.0.7 full pipeline
Key files: lib.rs, cabinet.rs, econometrica.rs, report.rs, project-state.js, insights-rules.js, InsightsPanel.svelte, OptimizeStep.svelte, ConfigPanel.svelte, EChartBase.svelte, ExpertValidatePanel.svelte, ExpertModelPanel.svelte, ExpertDecomposePanel.svelte, adstock_selector.py, pptx_export.py, server.py, manifest.json
Status: ALL 12 phases DONE. All Obsidian Mistakes covered. Next: live-тест с реальными данными, prod build (aurora-fix чеклист)

## Learnings

### Explore-агенты дают false positives
- hill.js `xSafe` — агент заявил undefined, на самом деле определён (строка 32)
- Gamma scaling — агент заявил mismatch, на самом деле модель на normalized data, optimizer/frontend оба используют `max(gamma*spend, 1)`
- **Правило:** ВСЕГДА верифицировать находки вручную

### mod.rs ≠ автоматическое включение .rs файлов
- project.rs и report.rs файлы существовали, но mod.rs НЕ содержал `pub mod project/report`
- cargo check поймал за 1 итерацию

### `<` в Svelte text = HTML parse error
- `Efficiency < 1.0x` → "Expected valid element name" → нужно `&lt;`

### Content-packs manifest с несуществующими файлами
- manifest.json ссылался на 20+ help/*.html которые не существовали → verify_manifest() FAIL → content_packs_verified=false → dynamic packs никогда не загружались
- Fallback маскировал проблему

### aurora-pack.py PRODUCT_CABINETS
- Новый продукт требует добавления в dict, иначе argparse reject

### rust_xlsxwriter Formula type
- `write_formula(row, col, "=SUM()")` не работает — нужно `Formula::new(format!(...))`

### Obsidian Mistakes — живой чеклист
- 200+ mistakes, все релевантные для Econometrica проверены
- aurora-fix products.md содержал устаревшие данные (9 команд вместо 11, "нет модулей" хотя они есть)

## Solutions & Fixes

### 7 коммитов (v1.0.2→v1.0.7)

| Tag | Коммит | Файлов | Что |
|-----|--------|--------|-----|
| v1.0.2 | b56a369 | 24 | Pipeline fixes, ребрендинг, insights-rules.js, miROAS |
| v1.0.3 | bbfc451 | 9 | Dual-mode, 3 ExpertPanel, assisted pipeline |
| v1.0.4 | 208195a | 6 | XLSX 6 листов + formulas + charts, PPTX 8 slides |
| v1.0.5 | 31d7bd7 | 4 | Model versioning, crash recovery, ECharts lazy-init |
| v1.0.6 | c652c1a | 4 | Claude AI Tier 2, cross-product commands |
| v1.0.7 | 016288a | 5 | Adstock auto-select via BIC |

### Детали по фазам

**Phase 7A — Offline Insights:**
- `src/lib/insights-rules.js` — 5 функций, ~30 правил с severity + tips
- InsightsPanel.svelte — severity badges, expandable "Подробнее"

**Phase 7B — miROAS:**
- `marginalROI()` из hill.js уже существовала — просто показали в OptimizeStep
- Цветовая индикация: зелёный >1.5x, жёлтый 0.8-1.5x, красный <0.8x

**Phase 8 — Dual-Mode:**
- `expertMode` store в project-state.js (localStorage persisted)
- Toggle "Маркетолог/Эксперт" в pipeline header (фиолетовый)
- 3 ExpertPanel компонента: Validate (corr+VIF+stats), Model (MCMC+params), Decompose (spend vs effect)

**Phase 9 — Assisted Pipeline:**
- ValidateStep: auto-fix recommendations с dismiss buttons
- ImportStep: "Далее: Валидация" quick-nav
- Safe/risky split для auto-fixes

**Phase XLSX/PPTX:**
- report.rs полностью переписан: 6 листов, формулы (ROI=C/B, delta=C-B), charts (bar, column), conditional formatting (зелёный/красный), глоссарий 11 терминов
- pptx_export.py: 8 слайдов с python-pptx, Aurora AI брендинг, speaker notes
- ReportStep: 3 кнопки (MD + XLSX + PPTX)

**Phase 11 — Diagnostics:**
- modeler.py: model versioning (archive → models/history/, max 5)
- server.py: POST /compute/model_history
- pipeline/+layout.svelte: sidecar crash recovery (localStorage cleanup)
- EChartBase.svelte: step-aware lazy-init (dispose on leave)

**Phase 10+12 — AI + Cross-product:**
- InsightsPanel: Claude AI Tier 2 (online, optional, "Спросить AI")
- Graceful degradation: hides input if no Claude CLI
- /mmm-to-slides, /mmm-to-doc commands, content-packs v2

**Adstock auto-select:**
- adstock_selector.py: OLS geometric vs weibull, BIC comparison per channel
- Confidence: very_strong >10, strong >6, positive >2, weak <2
- ConfigPanel: auto-triggers in marketer mode, shows label

## Decisions

1. **Two-tier insights:** Tier 1 offline rules (80% value, 0% cost) + Tier 2 Claude optional
2. **Expert panels = lazy-loaded components:** 1 `{#if}` per step, not 75 scattered conditions
3. **Safe/risky auto-fix split:** Never auto-merge channels or auto-winsorize
4. **Assisted Pipeline, not One-Click:** Domain knowledge confirmation step
5. **Prompts not in content-packs:** manifest.sig bottleneck → vault instead
6. **Honest progress bar:** No fake 33% start for B2B tool
7. **Subtle feedback, not fireworks:** Green pulse, not animation for CFO
8. **miROAS = existing marginalROI():** Show, don't rebuild
9. **Trace plots server-side PNG:** Not 50-200MB JSON
10. **Cross-product via files:** No IPC between .exe → file convention
11. **XLSX formulas not values:** User can edit and formulas recalculate
12. **Adstock auto-select via BIC:** OLS quick test, not full Bayesian

## Pending

### For prod build (aurora-fix чеклист)
- V1: Version sync (Cargo.toml vs tauri.conf.json)
- V7-V8: Content-pack checksums verification
- V9-V10: Bundle resources (content-packs + sidecar in resources)
- V12: Help files for econometrica
- V13: Sidecar bundling
- V15: Icon quality check

### Future improvements (beyond current scope)
- Trace plots (matplotlib PNG server-side) — sidecar endpoint not yet created
- CI bands on waterfall chart — ECharts implementation
- Sensitivity analysis UI — "What if TV ROI is actually 2.0x?"
- Cross-product file convention: `%USERPROFILE%/Aurora AI/Exports/{product}/`
- Industry benchmarks overlay
- Undo for auto-fixes (previousState in store)

## Errors & Workarounds

### Explore agents rejected by user
- Антон отклонил 2 агента в начале → использовала Glob/Grep/Read напрямую
- Lesson: для этого проекта — прямые инструменты

### mod.rs missing project/report
- 14 cargo errors → 1 iteration fix (add 2 lines to mod.rs)

### Duplicate mcmcChains variables
- Added at line 31, already existed at 76 → grep found → removed

### `<` in Svelte template
- ExpertDecomposePanel → &lt; entity fix

### NotebookLM auth
- `nlm login` failed (Chrome DevTools) → Антон auth manually

### rust_xlsxwriter Formula
- 8 compilation errors → wrap all format!() in Formula::new()

### unused imports warning
- `use commands::{project, report}` → commands used via full path → removed from use

### aurora-fix products.md outdated
- econometrist: 9 → 11 commands
- V26 "no modules" note → updated to "synced"

## Full Session Notes

### Стратегические документы созданы
- Next-Gen Plan v2: `C:\Users\ackol\Desktop\Aurora Econometrica — Next-Gen Plan v2.md` (9 разделов)
- Критический аудит плана: 12 проблем найдены (K1-K4, D1-D4, U1-U3, P1-P5)
- PPTX/XLSX спецификация (10-12 слайдов, 7 листов)

### NotebookLM использован
- Notebook: `2e7d71d1-b5c1-4be4-be78-ca5105348172` (40 источников MMM 2025-2026)
- 3 запроса: AI+MMM, UX best practices, метрики/визуализации
- Ключевые инсайты: Bayesian = стандарт 2026, miROAS = killer metric, триангуляция MMM+incrementality

### Obsidian верификация
- 13 релевантных Mistakes проверены — все покрыты нашими фиксами
- aurora-fix skill.md и products.md обновлены

### Git log
```
016288a feat: adstock auto-select via BIC (marketer mode)          (tag: v1.0.7-adstock-autoselect)
c652c1a feat: Claude AI insights (Tier 2) + cross-product export   (tag: v1.0.6-ai-insights-crossproduct)
31d7bd7 feat: model versioning, sidecar crash recovery, lazy-init  (tag: v1.0.5-diagnostics)
208195a feat: professional XLSX (6 sheets, formulas, charts) + PPTX (tag: v1.0.4-xlsx-pptx-export)
bbfc451 feat: dual-mode (marketer/expert) + assisted pipeline UX   (tag: v1.0.3-dual-mode-assisted)
b56a369 feat: pipeline audit fixes, rebrand, insights engine, miROAS (tag: v1.0.2-audit-fixes-insights)
```

### Новые файлы созданы (13)
- `src/lib/insights-rules.js`
- `src/lib/components/pipeline/ExpertValidatePanel.svelte`
- `src/lib/components/pipeline/ExpertModelPanel.svelte`
- `src/lib/components/pipeline/ExpertDecomposePanel.svelte`
- `sidecar/econometrica/engines/pptx_export.py`
- `sidecar/econometrica/engines/adstock_selector.py`
- `content-packs/manifest.json` (rewritten)
- `content-packs/manifest.sig` (resigned v2)
- `content-packs/onboarding-data.json` (econometrist)
- `content-packs/command-meta-data.json` (+econometrica)
- `content-packs/cabinets.json` (+export commands)
- `C:\Users\ackol\Desktop\Aurora Econometrica — Next-Gen Plan v2.md`
- `CC-Sessions/2026-04-18-2200-econometrica-audit-dualmode-insights.md`
