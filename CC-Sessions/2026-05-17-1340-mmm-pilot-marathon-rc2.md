---
tags: [session, compressed, mmm-optimizer, v2.1.0-rc2, pilot, audit, ssot, unit-costs]
type: session
updated: 2026-05-17
---

# Quick Reference

Длинный pilot марафон Aurora MMM Optimizer v2.1.0-rc2 (16–17 мая 2026) с Антоном: 20+ commits через серию ручных pilot прогонов → 3-agent virtual-pilot audit → план v2 (audit-revised) → execution Этапов 0+1+2+3 + aurora-meta INVs → push на origin. Финальный HEAD `4b03a8b` (Aurora Econometrica) + `fc28960` (aurora-meta), всё запушено к origin.

**Topic:** mmm-pilot-marathon-rc2
**Branch:** `feat/v2.0.0-explicit-mode-wizard` (pushed) + `aurora-meta/main` (pushed)
**Status done:** SSOT ratio/MQS в 7 точках, stale model banner, KPI persistence, ADR-020 unit_costs at training + decomposer симметрия, KPI flow sync (available_kpi_types backend → KPISelector disabled cards), ChannelTimeline tooltip grouping 5 категорий, INV-36/INV-37 в aurora-meta, push выполнен.
**Status pending:** Этап 5 — tag `v2.1.0-rc2` + Pre-flight checklist items §6 aurora-meta; backlog v2.2.0 — `kpi_unit_cost` для ROI count→money, awareness KPI types (Phase A1a logit-Normal).

**Key files:**
- План: `C:\Users\ackol\.claude\plans\immutable-mixing-tide.md` (v2 audit-revised)
- Tracker: `C:\Users\ackol\.claude\plans\v2.1.0-rc2-execution-tracker.md`
- ADR: `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica\docs\adrs\ADR-020_unit_costs_at_training.md`
- Backend math: `sidecar/econometrica/engines/modeler.py`, `ols_modeler.py`, `decomposer.py`, `validator.py`, `server.py`
- Frontend SSOT: `src/lib/ratio-classifier.js`, `src/lib/project-state.js`, `src/lib/insights-rules.js`
- UI critical: `src/lib/components/MQSBadge.svelte`, `ChannelTimeline.svelte`, `KPISelector.svelte`, `ColumnMapperConfirm.svelte`, `ModelTrainingStep.svelte`, `ReportStep.svelte`, `DecomposeStep.svelte`, `ValidateStepV13.svelte`, `ConfigPanel.svelte`, `ExpertModelPanel.svelte`
- HTML export: `sidecar/econometrica/aurora_html/{builder.py,interactive.py,security.py,templates/layout.css}`
- PPTX export: `sidecar/econometrica/aurora_pptx/{builder.py,tokens.py}`
- Aurora-meta INVs: `D:\Docs\Aurora_Ai\aurora-meta\ENGINEERING_INVARIANTS.md` (v1.7)

---

## Learnings

### Mathematical / backend
- **Mixed mode (count KPI + monetary/physical media) требует pre-multiply media на unit_cost ПЕРЕД adstock** — иначе Hill saturation калибруется на смешанных шкалах. Нормализация (`media_means`) после pre-multiply делает priors valid (x_norm 0..1).
- **Training + load симметрия обязательна** для любого preprocessing — pickle хранит обработанные `media_means`, decomposer должен apply тот же transformation. Без этого X_media build при load инcons с обученной нормализацией → broken contribution.
- **Backend guards ПЕРЕД I/O**: `KPI_TYPE_NOT_IMPLEMENTED` guard стоял ПОСЛЕ `pd.read_excel` → тесты reject-cases требовали валидные fixtures для прохода до guard. Early-reject pattern ускоряет dev + тесты.

### Frontend / UX
- **SSOT override comprehensive coverage**: при создании frontend override (MQS из SSOT ratio) — grep ВСЕ display points ПЕРЕД commit'ом. Пилот: 5+ итераций «опять разночтения» потому что override делалась точечно (MQSBadge → ExpertModelPanel → ReportStep → reportInsights → ExpertMCMC).
- **Cached state snapshots требуют localStorage persistence** для banner-функционала после reload (lastTrainedConfig=null → modelStaleStatus.stale=false всегда).
- **NaN sanitize в 0, не reject** через `allow_nan=False` (ValueError ломает export, sanitize gracefully degrade).
- **Fallback CSS variables** обязательны когда external `aurora_html.css` build script может отсутствовать (был случай — секции HTML отчёта остались `opacity:0` потому что animation invalid без `--transition-base`).

### Тесты / Aurora-специфика
- **Aurora pickles через `engines.persistence.load_model_with_compat`**, не raw `pickle.load` (custom safe-format с persistent_id, INV-23a).
- **grep '^def ' module ПЕРЕД import в тестах** — функция `validate` vs реальное `validate_data` стоила лишней итерации.
- **AURORA_THEMES fallback должен включать `palette` key** (8 цветов) для ECharts builders — без этого `pal.palette[i]` undefined → TypeError → 3 из 5 графиков ломаются.

### Process
- **3-agent virtual-pilot audit pattern**: при крупном refactor session запускать параллельные Explore-агентов которые виртуально проходят user journey по коду и находят skipped bugs / scrytye проблемы. 17 findings → 12 closed, 5 backlog.
- **Plan-tracker pattern**: после каждого commit обновлять «Current task / Done / Next concrete first step», что даёт continuity после compress. Tracker file в `~/.claude/plans/` — read first при compress recovery.
- **Опираясь на feedback memory заранее** (perfectionism vs pragmatism, autonomous-then-manual): comprehensive Opus autonomous batches + ручной pilot тест Антона раз в N commits — не прерывать autonomous phase предложением «глянь в браузере».

---

## Decisions

### ADR-020 (Aurora Econometrica) — accepted 2026-05-17
**Mixed mode: pre-multiply media на unit_cost ПЕРЕД adstock в training + симметрично при load в decomposer.** Pickle получает `unit_costs_applied_at_training: bool` + `unit_costs_snapshot: dict[str, float]` для byte-identical reproducibility (INV-23a). Backward compat: pickles без flag → default False → legacy path. KPI count types (sales_packs / leads / etc.) разрешены через monetary Normal likelihood (β в native units); awareness types (aided_awareness / top_of_mind) reject через `KPI_TYPE_NOT_IMPLEMENTED` до Phase A1a logit-Normal. kpi_unit_cost для ROI count→money — backlog v2.2.0.

### INV-36 (aurora-meta v1.7)
**Backend training + load симметрия для data preprocessing.** Любое нетривиальное preprocessing в training (scaling, conversion, derived features) симметрично применяется при load обученного pickle (используя snapshot из pickle, не текущий config). Pair'd с INV-23a (forward-compat).

### INV-37 (aurora-meta v1.7)
**SSOT override comprehensive coverage перед commit.** При создании frontend SSOT-override — grep ВСЕ display points ПЕРЕД commit'ом. Шаблон: derived store/helper с single override logic, импортируемый всеми consumers. Sister к INV-22 (SSOT precedence).

### Push: as-is без squash
20 commits сохранили pilot tracing — каждый bug fix виден как atomic commit, git blame трассирует regression до конкретного pilot finding. Squash потерял бы эту ценность.

### Tag отложен до повторного pilot run
Hold v2.1.0-rc2 tag — wait Антон проверит regression на ту же data через pilot. После ack → annotated tag + Pre-flight checklist items §6 aurora-meta для INV-36/37 + memory entry.

---

## Pending

### High priority (next session)
- **Этап 5: tag v2.1.0-rc2** — после Антон ack повторного pilot run:
  - `git tag --list v2.1.0-rc2` → collision check, delete если есть
  - `git tag v2.1.0-rc2 -a -m "..."` + `git push origin v2.1.0-rc2`
  - Update `aurora-meta/ENGINEERING_INVARIANTS.md` §6 Pre-flight checklist: 2 items для INV-36 (training+load симметрия) + INV-37 (SSOT comprehensive coverage)
  - Memory entry в MEMORY.md о tag создании

### Backlog v2.2.0
- **kpi_unit_cost flow** для ROI count→money conversion (count KPI → revenue в decomposer/optimizer):
  - UI input «Средняя цена единицы» на под-шаге «Метрики каналов»
  - Backend decomposer: `roi_money = contribution_count × kpi_unit_cost / spend_money`
  - Optimizer integration
- **Awareness KPI types** (aided_awareness / unaided_awareness / top_of_mind):
  - Phase A1a: logit-Normal likelihood + ceiling clipping + GaussianRandomWalk baseline drift в PyMC модели
  - 4-6 недель работы
- **ChannelTimeline filter signedFactors** по current validation columns (banner есть, но визуальный filter optional)
- **PPTX / HTML sections.py SSOT MQS** — backend читает raw `mqs_score` напрямую. Frontend pre-patch diagnostics перед invoke более правильный — отдельная сессия для refactor

### Open questions
- Build script `Standards/tokens/build.py --target python` отсутствует в этом репо. Sidecar fallback nested tokens обеспечивает рабочий PPTX/HTML без него, но финальный production build должен включать этот шаг. Координировать с Standards/ owners.

---

## Errors & workarounds

### 1. pickle.UnpicklingError в первой попытке test
**Symptom:** `_pickle.UnpicklingError: A load persistent id instruction was encountered, but no persistent_load function was specified.`
**Cause:** Aurora pickles saved через `engines.persistence` module с custom safe-format (INV-23a). Raw `pickle.load(open(...))` не работает.
**Fix:** `from engines.persistence import load_model_with_compat; model_data = load_model_with_compat(pickle_path)`.
**Memory:** `feedback_aurora_pickle_safe_load_in_tests.md`

### 2. KPI_TYPE_NOT_IMPLEMENTED guard placement
**Symptom:** test `test_awareness_kpi_still_rejected` упал на `FileNotFoundError: '/nonexistent.xlsx'` ДО guard.
**Cause:** Guard был ПОСЛЕ `pd.read_excel` в modeler.py.
**Fix:** Перенёс guard в самое начало `train_model` (early-reject ДО data file read) — test passes без fixture file.
**Memory:** `feedback_backend_guards_before_io.md`

### 3. ImportError `validate` vs `validate_data`
**Symptom:** `ImportError: cannot import name 'validate' from 'engines.validator'`
**Cause:** Реальное имя функции `validate_data`. Я предположила `validate` без grep.
**Fix:** `grep '^def ' engines/validator.py` показал правильное имя.
**Memory:** `feedback_grep_exact_imports_before_test_write.md`

### 4. AURORA_THEMES palette key missing
**Symptom:** HTML отчёт показывал только 2 из 5 графиков (mROAS + Share). Timeline, Waterfall, Optimize пропадали.
**Cause:** `pal.palette[i % pal.palette.length]` в interactive.py — `pal.palette` undefined в моём fallback `AURORA_THEMES`. TypeError → builder return invalid option → ECharts skip render.
**Fix:** Добавил `palette: [...]` (8 цветов) в fallback `light/dark/fun` theme objects.

### 5. PPTX tokens flat dict KeyError
**Symptom:** `KeyError: 'brand'` при импорте `aurora_pptx.tokens`.
**Cause:** Я написал fallback `COLORS = {'navy_deep': '#0A1628', ...}` flat. Реальный код доступа: `COLORS["brand"]["deep"]["100"]`.
**Fix:** Nested структура matching access patterns. Smoke test перед commit.
**Memory:** `feedback_fallback_verify_access_patterns.md`

### 6. NaN sanitize vs reject
**Symptom:** `json.dumps(allow_nan=False)` бросал ValueError на NaN в decompose data → entire HTML export flow ломался.
**Cause:** mroas / spend могут быть NaN если decomposer столкнулся с делением 0÷0.
**Fix:** Pre-sanitize NaN/Inf → 0 в `escape_js_embed` recursively. Gracefully degrade.
**Memory:** `feedback_nan_sanitize_not_reject.md`

### 7. CSS variables undefined → секции невидимы
**Symptom:** HTML отчёт показывал только TOC. `<main>` content существовал, но `opacity:0` навсегда.
**Cause:** `.section { animation: section-in 500ms var(--transition-base) forwards; opacity: 0; }`. `var(--transition-base)` undefined (aurora_html.css не сгенерирован) → animation invalid → opacity не переходит к 1.
**Fix:** Добавил fallback CSS variables в `layout.css` (`:root { --transition-base: 200ms ease-in-out; --bg: #ffffff; ... }`) + изменил `.section { opacity: 1; }` как default.

### 8. SSOT MQS rolling discovery (5+ iterations)
**Symptom:** «опять разночтения» от Антона на одном экране (success banner / плитка / инсайт / Ratio details / Экспертный режим / Report шапка / reportInsights).
**Cause:** SSOT override (frontend ratio ≥ 4 → use raw_score без backend thinness_cap=50) применялся точечно к каждому display point по мере того как Антон находил.
**Fix:** Финальный audit batch покрыл 7 точек через grep `metrics.ratio\|mqs.score\|tier_label`.
**Memory:** `feedback_ssot_comprehensive_coverage.md` + INV-37 в aurora-meta v1.7.

### 9. Encoding traps на Windows console (cp1251)
**Symptom:** `python -c "import json..."` показал кириллицу как «���-�� ��������» при debug чтения decomposition.json.
**Workaround:** Использовал f.read() с explicit encoding='utf-8', содержимое правильное несмотря на console display.

### 10. lastTrainedConfig после reload — null
**Symptom:** Stale model banner не появлялся после Tauri окна reload.
**Cause:** `lastTrainedConfig` writable(null) не persisted. После reload store = null → modelStaleStatus.stale всегда false.
**Fix:** localStorage persist через manual subscribe + initial value через IIFE.
**Memory:** `feedback_stale_state_persistence_invalidation.md`

---

## Full Session Notes

### Timeline

**Pre-этой сессии (16 мая, evening) - 60+ commits pilot марафон с Антоном:**
- Серия ручных pilot прогонов: Импорт → Валидация → Модель → Декомпозиция → Оптимизация → Отчёт
- Antон находил баги через screenshots, я fixила пошагово
- Закрыто 16+ tasks вручную: ratio classifier 5 коридоров, MQS override, stale model banner, KPI persistence, outlier detection, holidays info, negative signed factors, NaN sanitization, AURORA_THEMES fallback, PPTX tokens fallback, etc.

**Эта сессия (17 мая) — finalization phase:**

#### Phase 1: Audit 3-agent
Запустил 3 параллельных Explore-агентов для virtual-pilot по коду:
- Agent 1: Import + Validation
- Agent 2: Model + Decompose + Optimize
- Agent 3: Report + Export (HTML/PPTX/XLSX)

Output: **17 findings**, из которых 9 must-fix закрыто immediate batch commit `9d4470c`, 8 — отложено для системного refactor.

#### Phase 2: Plan formulation
Антон попросил детальный технический анализ-аудит плана. Я провела self-critique:
- **Открытие #1**: `TrainRequest` schema не имеет `kpi_type` поля. ConfigPanel не передаёт. Backend всегда default'ит 'sales'. Pilots с count KPI silently fall-back через monetary path.
- **Открытие #2**: Decomposer должен **симметрично** apply unit_costs при load (а не «skip» как я сначала написала в плане).
- **Открытие #3**: count KPI guard в modeler.py line 192 reject всё кроме 'sales' — нужно relax (split awareness-only reject).
- **Открытие #4**: `unit_costs_snapshot` в pickle для byte-identical reproducibility (INV-23a).

Финальный план v2: `C:\Users\ackol\.claude\plans\immutable-mixing-tide.md` (audit-revised, 5 этапов).

#### Phase 3: Execution (5 commits)

**Этап 0 — Prerequisites:**
- Read modeler.py / decomposer.py / validator.py для точных line numbers
- Wrote **ADR-020** (`docs/adrs/ADR-020_unit_costs_at_training.md`) — commit `9a344e3`
- INV grep: max=35, reserved INV-36 + INV-37

**Этап 1 — unit_costs at training:** commit `d7c1232`
- `server.py`: TrainRequest + TrainStartRequest получают `kpi_type: str = 'sales'`
- `modeler.py`: early reject awareness types, relax sales/count/profit, pre-multiply media в X_media build + x_norm quantiles, pickle gets `unit_costs_applied_at_training` + `unit_costs_snapshot`
- `ols_modeler.py`: симметричный apply + pickle flag
- `decomposer.py`: симметричный pre-multiply при load с `raw_spend_series_native` backup ДО pre-multiply (избегаем double-multiply в `spend_money = native × unit_cost`)
- `ConfigPanel.svelte`: `kpi_type: get(kpiType) || 'sales'` в payload
- `tests/test_modeler_unit_costs.py`: 5 functional pytest (default_no_op, snapshot_persisted, inverse_scale_beta, kpi_type_count_passes, awareness_kpi_still_rejected)

**Этап 3 — ChannelTimeline tooltip grouping:** commit `78c185a` (Sonnet sub-agent под Opus supervision)
- 5 категорий: База / Медиа / Конкуренты / Праздники / Внешние
- Subtotals + Итого
- Active series highlight preserved
- `extraCssText: 'max-height:420px;overflow:auto;max-width:380px'` для overflow guard
- cleanName убирает prefix через regex

**Этап 2 — KPI flow sync:** commit `4b03a8b`
- `validator.py`: result dict получает `available_kpi_types: sorted(set)` основанный на classify_column колонок. Fallback на все 7 типов если backend не нашёл явный target_*
- `KPISelector.svelte`: prop `availableKpiTypes: string[] | null`, disabled state с tooltip
- `ValidateStepV13.svelte`: передаёт `availableKpiTypes={$validateData?.result?.available_kpi_types ?? null}`
- `tests/test_validator_available_kpi_types.py`: 3 functional pytest

**aurora-meta INVs:** commit `fc28960`
- INV-36 — Backend training + load симметрия для data preprocessing
- INV-37 — SSOT override comprehensive coverage перед commit
- History v1.7

#### Phase 4: Push
- Aurora Econometrica: 20 commits `4d997ba..4b03a8b` → `origin/feat/v2.0.0-explicit-mode-wizard`
- aurora-meta: 1 commit `775ae1b..fc28960` → `origin/main`

### Diff stats (aggregate)
**Aurora Econometrica:** 34 файла, **+2020 / -255 строк**
- `src/lib/insights-rules.js` (+249)
- `src/lib/components/pipeline/ChannelTimeline.svelte` (+205)
- `src/lib/project-state.js` (+169)
- `src/lib/components/pipeline/ColumnMapperConfirm.svelte` (+154)
- `src/lib/ratio-classifier.js` (+119, new file)
- `src/lib/components/pipeline/ModeDerivedExplanation.svelte` (+98)
- + 28 других файлов

### Тесты
**Baseline:** 570 vitest + 281 pytest
**Final:** 570 vitest + **289 pytest** (+8 functional tests across modeler unit_costs / validator available_kpi_types)
**svelte-check:** 0 errors maintained

### Key files modified (alphabetical)

**Frontend:**
- `src/lib/components/MQSBadge.svelte` (SSOT MQS override + Ratio details)
- `src/lib/components/ConfigPanel.svelte` (kpi_type + chosenKpiColumn + trainModel double-click guard + modelChannelEnabled sync + adstock re-fetch)
- `src/lib/components/pipeline/ChannelTimeline.svelte` (signedFactors negative stack + tooltip grouping)
- `src/lib/components/pipeline/ColumnMapper.svelte` (terminology unification)
- `src/lib/components/pipeline/ColumnMapperConfirm.svelte` (mode-aware иерархия + zeros>80% guard + volume column)
- `src/lib/components/pipeline/DecomposeStep.svelte` (signedFactors prop + stale banner)
- `src/lib/components/pipeline/ExpertModelPanel.svelte` (SSOT MQS override)
- `src/lib/components/pipeline/ExpertValidatePanel.svelte` (terminology)
- `src/lib/components/pipeline/InsightsPanel.svelte` (ssotRatio prop в 3 case'а)
- `src/lib/components/pipeline/KPISelector.svelte` (availableKpiTypes + disabled cards)
- `src/lib/components/pipeline/ModeDerivedExplanation.svelte` (SSOT classification + info-row вместо кнопки + столбец Объём)
- `src/lib/components/pipeline/ModelTrainingStep.svelte` (SSOT MQS + stale banner)
- `src/lib/components/pipeline/RatioInfoCard.svelte` (SSOT label/tone)
- `src/lib/components/pipeline/ReportStep.svelte` (SSOT MQS in shape header)
- `src/lib/components/pipeline/TrafficLight.svelte` (terminology unification)
- `src/lib/components/pipeline/ValidateStepV13.svelte` (chosenKpiColumn + availableKpiTypes prop + outlier guards)
- `src/lib/insights-rules.js` (modelInsights ratio SSOT + decomposeInsights competitors + reportInsights SSOT + catastrophe warning + holidays auto-injection info + outlier detection)
- `src/lib/project-state.js` (validationMetrics SSOT + modelChannelEnabled + chosenKpiColumn + lastTrainedConfig + modelStaleStatus)
- `src/lib/ratio-classifier.js` (NEW, 5-band SSOT)
- `src/routes/pipeline/+layout.svelte` (Далее блокировка до confirm ролей)

**Backend (sidecar/econometrica):**
- `engines/decomposer.py` (re-injection holidays + signed_factor_contributions + симметричный unit_costs apply)
- `engines/modeler.py` (early KPI guard + unit_costs apply + pickle flag/snapshot + x_norm quantiles)
- `engines/ols_modeler.py` (симметричный unit_costs apply)
- `engines/persistence.py` (relative import fix для sidecar bundling)
- `engines/validator.py` (severity градация + available_kpi_types + outlier-friendly thresholds)
- `server.py` (TrainRequest schema + kpi_type)
- `tests/test_modeler_unit_costs.py` (5 functional, NEW)
- `tests/test_validator_available_kpi_types.py` (3 functional, NEW)
- `aurora_html/builder.py` + `interactive.py` + `security.py` + `templates/layout.css` (CSS fallback variables, NaN sanitization, AURORA_THEMES palette key, KPI-aware mROAS formatter)
- `aurora_pptx/builder.py` + `tokens.py` (nested fallback tokens когда aurora_tokens build script не запущен)

**Docs:**
- `docs/adrs/ADR-020_unit_costs_at_training.md` (NEW, 103 lines)
- `D:\Docs\Aurora_Ai\aurora-meta\ENGINEERING_INVARIANTS.md` (INV-36 + INV-37 + History v1.7)

**Plans (~/.claude/plans/):**
- `immutable-mixing-tide.md` (v2 audit-revised plan, NEW)
- `v2.1.0-rc2-execution-tracker.md` (live tracker, NEW)

**Memory (~/.claude/projects/D--Docs-Aurora-Ai/memory/):**
- `feedback_aurora_pickle_safe_load_in_tests.md` (NEW)
- `feedback_backend_guards_before_io.md` (NEW)
- `feedback_grep_exact_imports_before_test_write.md` (NEW)
- `feedback_ssot_comprehensive_coverage.md` (NEW)
- `feedback_fallback_verify_access_patterns.md` (NEW)
- `feedback_nan_sanitize_not_reject.md` (NEW)
- `feedback_stale_state_persistence_invalidation.md` (NEW)
- `MEMORY.md` updated с 2026-05-17 entry

### Sub-agents использовано
- 3 Explore agents (Phase 1 audit, параллельно) → 17 findings
- 1 Sonnet sub-agent (Этап 3 tooltip grouping) → audited Opus вручную, accepted
- Все остальное Opus 4.7 max (core math + critical fixes + reviewer)

### Cross-product impact
- **INV-36** применим ко всей Aurora линейке: любой backend ML pipeline где preprocessing happens at training должен симметрично применяться при load
- **INV-37** SSOT pattern применим к любому frontend product с backend-frontend overrides (Aurora Launch, Data Studio, etc.)
- **Aurora pickles safe-format** — особенность которая распространится при унификации Aurora линейки storage

### Branch state
**Pushed:** `feat/v2.0.0-explicit-mode-wizard` @ `4b03a8b` (Aurora Econometrica), `main` @ `fc28960` (aurora-meta)
**Working tree:** clean
**Untracked plans/tracker:** локальные в `~/.claude/plans/` — не часть repo
