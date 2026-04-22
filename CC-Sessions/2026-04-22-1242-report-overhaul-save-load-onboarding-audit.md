---
tags: [session, compressed, econometrica, report, save-load, onboarding, audit, xss-fixes]
type: session
updated: 2026-04-22
---
# Quick Reference
**Topic:** Крупная UX-итерация — Report step с интерпретацией/FAQ/HTML-экспортом, save/load `.aurora` архивов, обучающий режим на 5 шагов, настройки проектной директории. Плюс полный аудит security/stability с 8 находками и их закрытием.

**Key files (новые 5):**
- `src/lib/components/ExpandableCard.svelte` — fullscreen wrapper для chart'ов
- `src/lib/components/pipeline/PipelineOnboarding.svelte` — универсальный spotlight-тур
- `src/lib/onboarding-state.js` — store + persistence + helpers для туров
- `src/lib/pipeline-tours.js` — реестр туров (TOURS) для 5 шагов
- `sidecar/econometrica/engines/html_export.py` — standalone HTML-отчёт (ECharts CDN)

**Key files (модифицированные 16):** ReportStep / ValidateStep / ModelTrainingStep / DecomposeStep / OptimizeStep / UnitCostsPanel / ProjectSelector / ExpandableCard (new но часто правлен) / routes/settings/+page / routes/+page / server.py / pptx_export.py / econometrica.rs / project.rs / report.rs / user_config.rs / lib.rs

**Status:**
- ✅ Commit `010a39f` — основная волна (1904+/186-, 21 файл)
- ✅ Commit `2d58f14` — audit fixes (212+/28-, 6 файлов)
- ✅ Все 22 tasks completed (0-21)
- ✅ Push в master завершён, работает в dev (кроме sidecar-endpoints — нужен rebuild для HTML/PPTX scenarios slide)
- ⏳ Pending: sidecar rebuild для rc3; проверка на CLOUDEAI
- 📋 Follow-up идеи в roadmap (векторы A/B/C)

## Learnings

### Svelte 5 / Tauri-specific
- **Svelte 5 `$effect` не имеет return-cleanup** — нужно использовать `onDestroy` для listeners. `onKey` функция в component scope не пересоздаётся при re-runs эффекта → можно безопасно addEventListener/removeEventListener в $effect.
- **`{@html}` с интерполяцией user-controlled — XSS vector.** Channel names из xlsx попадали в bold-replace через `.replace('**', '<b>')` без escape. Защита: `escapeHtml` helper перед интерполяцией в derived store.
- **Inline style height override через CSS** требует `!important` — мой overlay `height: 70vh !important` побеждает Svelte-inline `style="height:280px"` в EChartBase. ECharts ResizeObserver подхватывает автоматически.
- **Svelte `$state` let vs plain let для onboardingChecked** — если НЕ $state, изменения не триггерят re-run эффекта. Это нужный паттерн когда хотим однократный фиреюг per-session (не per-data-change).

### Rust / Tauri
- **`projects_dir()` без AppHandle** через чтение `user_config.json` напрямую с диска через serde_json::Value — не требует рефакторинга всех 10+ call sites.
- **Zip archive atomic write через `.tmp` + rename** — защита от битых `.aurora` при panic/kill. Combined с streaming `std::io::copy` вместо `std::fs::read` для больших файлов.
- **Zip-slip защита через `entry.enclosed_name()`** — `None` возвращается для malformed paths (абсолютных, `..` segments).
- **`read_project` / `write_project` helpers** — reuse internal infrastructure для data_file нормализации при export/import.

### Python / FastAPI
- **`.format()` template bomb** — если user-controlled строка содержит `{` или `}`, `str.format()` падает с KeyError. Защита: escape `{` → `&#x7B;`, `}` → `&#x7D;` в _escape helper (HTML entity, безопасен в HTML).
- **`</script>` injection в JSON внутри `<script>` блока** — `json.dumps(ensure_ascii=False)` оставляет литеральный `</script>` → HTML-парсер закрывает script preamturely. Fix: `json.dumps(...).replace('</', '<\\/')` — обратный слэш в JSON игнорируется парсером.
- **FastAPI global exception handler + HTTPException** — по документации HTTPException идёт через свой более специфичный handler, `@app.exception_handler(Exception)` не ловит их. `if isinstance(StarletteHTTPException): raise exc` — safeguard на edge cases между версиями.

### UX patterns (новые)
- **Derived interpretation text** с реальными цифрами проекта > generic ML-пояснения. `topDriver.name`, `basePct.toFixed(0)`, `underfundedChannels.map(c => c.name)` — user узнаёт **свой** проект.
- **Автогенерируемый FAQ с conditional pushes** — `if (mqs > 80) items.push(...)` — снимает до 80% support-вопросов. Каждый Q&A адаптирован под данные модели.
- **Recompute-banner вместо тупикового «пройдите шаги 1-4»** — умный detection `mData && (!dData || !oData)` + кнопка «Пересчитать» прямо на Report. Пользователь не возвращается назад в пайплайне.
- **Tab-based унифицированный cover letter** — вместо двух `<details>` (PPTX/XLSX) — один блок с табами PPTX/XLSX/HTML + кнопка copy. Устраняет дублирование текста писем.
- **Fullscreen-wrapper через placeholder** — inline content **не** ремонтируется, placeholder на месте, overlay монтирует новый render. ECharts dispose/init безболезненно.

### Security class patterns
- **User-controlled strings из xlsx** (channel names) — всегда escape перед HTML/JS context. Source: Validate step → `column.name` → `decompose.channels[].name` → renders.
- **JSON embedded в `<script>` блок** — обязательно пост-process через `</` → `<\/`.
- **`.format()` с user content** — избегать, использовать именованные replace или string.Template. Если нужно — escape `{` `}` в user data.

## Decisions

1. **Один большой commit** для основной волны (`010a39f`) — логичнее одного коммита на каждый под-feature, т.к. все связаны одной темой.
2. **Сохранить OptimizeOnboarding.svelte** как dead code — на случай регрессии + для быстрого отката без blame.
3. **HTML через CDN echarts**, не bundled — 15-30 KB vs 8.7 MB. Offline-кейс отложен до появления запроса.
4. **`.aurora` = zip**, расширение узнаваемое, принимается также `.zip` (filter 'aurora', 'zip').
5. **Новый project_id при import** = `imported-YYYYMMDD-HHMMSS` — избегает конфликтов имён.
6. **data_file при export ВНЕ project_dir** — копируется в архив `data/<basename>` + маркер в project.json. Альтернатива — null + description hint — слабее.
7. **XLA_FLAGS остаётся в server.py top-level** — рискованный к рефакторингу, но гарантирует правильный порядок до любого import jax.
8. **Pre-validation archive** через открытие zip + поиск project.json entry — минимальный overhead vs защита от мусорного распакования.
9. **Escape `{`/`}` как HTML entities в _escape** — защита от .format() и одновременно безопасно в HTML. Проще чем string.Template рефакторинг.
10. **Recompute с default bounds (50-150%)** — не восстанавливать custom expert settings. Если пользователь хочет tweaks — идёт на Optimize шаг явно.

## Pending

### Sidecar rebuild needed для полной функциональности
- HTML endpoint `/export/html` — Python, требует `python build_sidecar.py`
- PPTX слайд «Сравнение сценариев» — Python, требует rebuild
- PPTX слайд «Динамика по периодам» — Python, требует rebuild
- `_resolve_project_dir()` helper в server.py — требует rebuild чтобы `/export/pptx` и `/export/html` учитывали Settings override

**Когда rebuild:** вместе с готовностью к rc3 (ждём фидбэк по текущему dev + решение Антона публиковать ли новый installer).

### Отложенные идеи (roadmap векторы A/B/C)
- AI narrative через Claude CLI (A)
- PDF / Markdown экспорт (B)
- Кастомизация брендинга (B)
- Публичная ссылка через Supabase Storage (C)
- Сравнение моделей side-by-side (C)
- Offline-mode HTML (bundled echarts)
- Миграция существующих проектов при смене папки в Settings

### Pre-existing tech debt (не моё)
- `hill.js` + `insights-rules.js` — свои svelte-check errors (baseline_pct vs base_pct property mismatch, implicit any)
- OptimizeOnboarding.svelte dead code
- `asyncio` spam в sidecar.log: уже fixed в rc2 через surgical filter

### Возможные дальнейшие улучшения (не начаты)
- `recomputeDownstream` с empty unitCosts — передавать объект вместо null чтобы backend однозначно использовал текущие settings
- Permission-mode cleanup для unused CSS в +page.svelte (часть уже почистила)
- aurora-fix skill: V40+ правила для XSS hardening + archive safety + .format bomb

## Files Modified

### Новые (5)
| File | Lines | Purpose |
|------|-------|---------|
| src/lib/components/ExpandableCard.svelte | ~220 | Fullscreen wrapper + tourKey prop |
| src/lib/components/pipeline/PipelineOnboarding.svelte | ~280 | Generic spotlight tour |
| src/lib/onboarding-state.js | ~70 | Store + persistence + helpers |
| src/lib/pipeline-tours.js | ~120 | 5 tour definitions |
| sidecar/econometrica/engines/html_export.py | ~550 | Standalone HTML export |

### Значительно модифицированные (commit 010a39f + 2d58f14)
| File | ~Lines changed | Changes |
|------|:---:|---------|
| src/lib/components/pipeline/ReportStep.svelte | +906 | Recompute banner, unified cover, interpretation, FAQ, HTML export, escape XSS |
| src-tauri/src/commands/project.rs | +181 | projects_dir override, archive export/import w/ data_file normalization |
| src-tauri/src/commands/report.rs | +200 | Timeline sheet, scenarios sheet, read_scenarios helper |
| sidecar/econometrica/engines/pptx_export.py | +148 | Timeline slide, scenarios slide |
| sidecar/econometrica/server.py | +68 | HTML endpoint, _resolve_project_dir, project_dir param |
| src/routes/settings/+page.svelte | +140 | Onboarding block + projects dir block |
| src/lib/components/ProjectSelector.svelte | +142 | Archive save/load buttons |
| src-tauri/src/lib.rs | +79 | 5 new command registrations |
| src-tauri/src/commands/econometrica.rs | +19 | econ_export_html + project_dir in body |
| ...прочие | ~200 | wire-up onboarding, fixes, UnitCostsPanel money fill |

## Errors & Workarounds

### Errors resolved (in-flight)
1. **ReportStep hasData=false при обученной модели** — причина: UnitCostsPanel.save() делает `decomposeData.set(null); optimizeData.set(null)` для инвалидации. Пользователь потом приходит на Report → ничего нет. **Fixed:** recompute-кнопка на Report.
2. **Warning «Бюджеты в native-единицах»** появлялся несмотря на указанные CPP для TRP. Причина: UnitCostsPanel сохраняет в store только non-money каналы, backend видит money как не-покрытые (unit_cost=0). **Fixed:** UnitCostsPanel при save теперь записывает `unit_cost=1.0` для всех media каналов.
3. **Forecast table показывает `—` для money каналов** — впечатление что инфляция не применяется. На самом деле применяется к бюджету канала (oldU=1.0 × 1.08). **Fixed:** UI теперь показывает «+N% к бюджету» для money, tooltip объясняет.
4. **Tauri dev отказывался запускать** изначально из-за License Not Found. **Workaround:** `AIAGENCY_DEV=1` env var перед `npm run tauri dev`.
5. **Unused CSS selectors warnings** — почистила dead rules (`.pipeline-promo-skip`, `.coming-soon-badge`, `.format-email*`, `.btn-more`).

### Potential bugs found in audit (commit 2d58f14)
| # | Severity | Issue | Fix |
|:-:|----------|-------|-----|
| 1 | 🔴 XSS | {@html} in ReportStep with channel names | escapeHtml() helper |
| 2 | 🔴 XSS | </script> injection via charts_json | replace('</', '<\\/') |
| 3 | 🔴 Runtime | .format() bomb with `{}` in channel name | escape { } in _escape |
| 4 | 🟠 Data | Python endpoints ignored Settings dir | Rust передаёт project_dir в body |
| 5 | 🟠 Data | Archive data_file cross-machine broken | Copy external data to archive/data/ + marker |
| 6 | 🟠 Robust | Archive export non-atomic | .tmp + rename |
| 7 | 🟠 Robust | Archive export OOM on large files | std::io::copy streaming |
| 8 | 🟠 Robust | Archive import no pre-validation | Check project.json ДО unzip |

## Full Session Notes

### Phase 1: Context re-activation
Сессия началась после компрессии предыдущей (v1.0.9-rc2 stability). Антон запустил dev — увидел 2 баг:
1. «Перейти к командам» — кнопка на главной, которую нужно убрать до возврата к работе с кабинетами
2. Decompose charts: Waterfall / ROI / Timeline нужен fullscreen expand

### Phase 2: ExpandableCard + 3 графиков Decompose
- Удалила кнопку «Перейти к командам» + очистила unused CSS
- Создала `ExpandableCard.svelte` — универсальный wrapper:
  - Inline-render в page + overlay-render при `expanded=true`
  - Placeholder на inline-месте когда в overlay (избежать double-render of canvas)
  - `onKey` (Escape) + click-outside + кнопка крестик
  - `tourKey` prop для data-tour атрибута (для будущего онбординга)
- Применила к 3 карточкам Decompose + таблице channels
- Центровка overlay: `display: flex; align-items: center; justify-content: center` + `.overlay-content { flex: 1; }`
- **Итерация с Антоном по высоте**: изначально график прижимался вверху → добавила `align-items: center`; потом «сделай выше» → `70vh` → потом «только в fullscreen» (уточнение) → `height: 70vh !important` с `!important` чтобы перебить inline EChartBase style

### Phase 3: Timeline в экспортах (PPTX + XLSX)
- PPTX `pptx_export.py`: Slide 5.5 «Динамика по периодам» через `XL_CHART_TYPE.AREA_STACKED`. Baseline первой series (muted color), каналы в том же порядке что decompose.channels
- XLSX `report.rs`: Sheet «Динамика» через `ChartType::AreaStacked`. Колонки A=date, B=Base, C+=каналы. Headers formatted, chart inserted после данных

### Phase 4: Сравнение сценариев в экспортах (PPTX + XLSX + HTML)
- Добавила `read_scenarios(project_id)` helper в Rust — читает `project_dir/results/scenarios/*.json`
- XLSX: Sheet «Сценарии» с best ROAS зелёным bold, auto-detect money vs native homogeneity
- PPTX (Python): Slide 6.5 через `slide.shapes.add_table` (native pptx), тот же паттерн
- Scenarios передаются Python'ом через чтение файлов (не через JSON body) — оптимальнее для большого числа сценариев

### Phase 5: Detailed audit при запросе «значительно доработать Отчёт»
Антон показал screenshot Report шага с 2 кнопками + описаниями, ссылка на фидбэк Радомира «долго вкуривать». Предложила 3 вектора доработки (UX-first / content-first / tech-first). Антон выбрал 7 конкретных задач:
- Bug hasData (recompute-banner)
- Unified сопроводительный (один блок, 3 таба)
- Interpretation для маркетолога
- FAQ автогенерируемый
- HTML как 3-й экспорт
- Save/Load .aurora
- Settings dir

### Phase 6: Report UX-рефакторинг (interpretation + FAQ)
- 5 секций интерпретации: «что делает модель» / «качество» / «структура продаж» / «что улучшить» / «практические шаги»
- FAQ: 8 возможных Q&A с conditional pushes (основанных на mqs/rhat/topDriver/lossChannels/basePct/lift/ratio)
- Unified cover letter с табами PPTX/XLSX/HTML + кнопка «📋 Скопировать текст» через `navigator.clipboard.writeText`
- Полный CSS: `.info-block`, `.info-toggle`, `.cover-format-tabs`, `.faq-q::before` (+/−), `.interp-h`
- **Markdown bold в derived:** через regex replace на {@html} рендере

### Phase 7: HTML-отчёт
Создала `sidecar/econometrica/engines/html_export.py`:
- Template engine через `str.format()` с escaped `{{ }}` в CSS/JS
- ECharts 5 через CDN (https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js)
- 5 графиков: waterfall bars, ROI horizontal bars (цветовая разметка), Share Spend vs Effect, stacked-area timeline с dataZoom, optimize comparison
- KPI-панель (8 cards) + channel table + scenarios block (conditional)
- CSS variables dark theme, responsive @media query
- Ключевая деталь: backend.html использует те же ECharts options что ChannelTimeline frontend — для визуальной консистентности

Rust команда `econ_export_html`, endpoint `/export/html` в server.py. Frontend: 3-я кнопка «🌐 Интерактивный (HTML)» синего цвета, 3-я карточка описания.

### Phase 8: Save/Load .aurora архивов
- `project_export_archive(project_id, output_path)`: walkdir → zip Deflated → all files под project_dir. Initial version читала файлы целиком через `std::fs::read` (OOM risk для больших pickle) — fixed в audit через `std::io::copy` streaming.
- `project_import_archive(archive_path)`: zip-slip защита через `entry.enclosed_name()`, new project_id = `imported-{timestamp}`, rewrite project.json (id + updated_at).
- Initial version НЕ валидировал content архива — fixed в audit через pre-open zip + поиск project.json.
- Initial version НЕ обрабатывал external data_file — fixed в audit: export копирует external data в архив `data/<basename>` + маркер `<project_dir>/...`; import resolve'ит маркер на dest или null для absolute несуществующих.

UI: 2 кнопки в ProjectSelector dropdown (под «+ создать»). `dialog.save` с extension `.aurora`, safe filename (Unicode letters allowed).

### Phase 9: Settings: кастомная папка проектов
- `UserConfig +econometrica_projects_root: Option<String>`
- `projects_dir()` priority: env `AURORA_PROJECTS_ROOT` > user_config > default (`%APPDATA%\<identifier>\projects\`)
- Читает user_config **напрямую с диска через serde_json::Value** — без AppHandle, чтобы не рефакторить 10+ call sites
- Rust commands: `get_/set_/open_econometrica_projects_root`
- Settings UI: current path + «📂 Открыть» / «📁 Выбрать» / «↺ Сбросить»

Следствие: `exports_dir` и `read_scenarios` в report.rs теперь используют `project::project_dir()` как единый источник правды.

### Phase 10: Обучающий режим (онбординг на все 5 шагов)
- `onboarding-state.js`: store `onboardingEnabled` + `shouldShowOnboarding(stepKey)` + `markOnboardingDone(stepKey)` + `resetAllOnboarding()`. Persistence в localStorage.
- `pipeline-tours.js`: реестр TOURS (validate/model/decompose/optimize/report), 4-5 шагов в каждом
- `PipelineOnboarding.svelte`: универсальный spotlight (из OptimizeOnboarding).
- Wire-up: ValidateStep / ModelTrainingStep / DecomposeStep / OptimizeStep / ReportStep — $effect guard с правильным условием (data available / stepState=trained для модели)
- Data-tour атрибуты в ключевых блоках (validation-result, unit-costs, column-mapper, model-config, model-mqs, decompose-*, report-exports)
- Settings UI: toggle + кнопка сброса прогресса
- OptimizeStep мигрирован с OptimizeOnboarding (старый файл остался как dead code)

### Phase 11: Bug fixes (frontend)
- **Money-каналы Forecast**: UI вместо `—` показывает «+N% к бюджету» с tooltip
- **UnitCostsPanel save**: записывает `unit_cost=1` для **всех** media (не только non-money) — исправляет warning при сравнении сценариев в ₽
- **Recompute banner**: при `mData && (!dData || !oData)` — умное сообщение + кнопка «Пересчитать» которая вызывает `econ_decompose` → `econ_optimize` последовательно с current unit_costs

### Phase 12: Main commit + memory update
- Commit `010a39f` (1904+/186-, 21 файл, 5 новых)
- Обновила MEMORY.md, project_econometrica_report_roadmap.md
- Создала `feedback_econometrica_patterns.md` — 9 переиспользуемых паттернов

### Phase 13: Audit (по запросу)
Антон попросил детальный аудит. Прошла по всем изменениям критически, нашла 8 проблем:

**XSS (3):**
1. ReportStep interpretation через {@html} с channel names — user xlsx → HTML inject
2. charts_json в html_export.py: `</script>` в channel name закрывал script
3. `.format()` template bomb: `{}` в channel name → KeyError

**Data consistency (2):**
4. Python endpoints игнорировали Settings override для projects dir
5. Archive data_file cross-machine broken (abs path не работал на другой машине)

**Robustness (3):**
6. Archive export non-atomic → битый .aurora при panic
7. Archive export OOM на больших файлах (std::fs::read в память)
8. Archive import без pre-validation → мусорные zip засоряли

Плюс 2 typing errors (@param {KeyboardEvent}, @param {unknown}).

Все закрыты в commit `2d58f14` (212+/28-). Python syntax ok, Rust cargo check clean, svelte-check — только pre-existing errors.

### Phase 14: Финальное обновление памяти + документация
- Дополнила project_econometrica_report_roadmap.md разделом "Audit fixes"
- Все 22 tasks completed
- Этот compressed session log

## Commits

- `a99b126` — chore(.gitignore): build logs (previous session)
- `25f689d` — docs(session): compressed log (previous session)
- `010a39f` — Report overhaul + save/load + onboarding (THIS session main)
- `2d58f14` — audit fixes (THIS session follow-up)

Current HEAD: `2d58f14` master, pushed в github.com/Ackold26/Aurora_Econometrica.

## Key commands reference

```bash
# Dev mode with license bypass
cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica
AIAGENCY_DEV=1 CARGO_TARGET_DIR="D:/cargo-targets/econometrica" npm run tauri dev

# Use custom projects dir (alternative to Settings UI)
AURORA_PROJECTS_ROOT="D:/MyProjects" AIAGENCY_DEV=1 npm run tauri dev

# Rust check after backend changes
CARGO_TARGET_DIR="D:/cargo-targets/econometrica" cargo check --manifest-path src-tauri/Cargo.toml

# Svelte check after frontend changes
npx svelte-check --tsconfig ./jsconfig.json

# Python syntax check after sidecar changes
python -c "import ast; ast.parse(open('sidecar/econometrica/server.py', encoding='utf-8').read())"

# Test HTML export manually
python -c "
import sys; sys.path.insert(0, 'sidecar/econometrica/engines')
import html_export
result = html_export.build_html(model_data={}, decompose_data={}, optimize_data={},
    output_path='/tmp/test.html', scenarios=[], project_name='Test')
print(result)
"

# Env rollback при регрессии multi-core MCMC
setx AURORA_MCMC_CHAIN_METHOD vectorized
setx AURORA_MCMC_CORES 1
setx AURORA_NUTS_BACKEND pymc
```

## Env flags registry (cumulative)

- `AIAGENCY_DEV=1` — dev mode bypass license
- `AURORA_PROJECTS_ROOT=<path>` — override econometrica_projects_root
- `AURORA_MCMC_CORES=N` — force N JAX host devices (default min(cpu, 8))
- `AURORA_MCMC_CHAIN_METHOD=parallel|vectorized|sequential` — override autodetect
- `AURORA_NUTS_BACKEND=auto|numpyro|pymc` — sampler backend
- `AURORA_SIDECAR_LEGACY_PORT=1` — bypass port discovery, hardcoded 7430
- `AURORA_SKIP_HANDSHAKE=1` — /health без session validation
