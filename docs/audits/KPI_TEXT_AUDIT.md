# KPI Text Audit (v1.3.0)

**Date:** 2026-05-12
**Owner:** Маша маленькая
**Scope:** все user-facing money-bound тексты в backend (sidecar/) и frontend (src/lib/) - outside reports (отчёты см. `REPORT_KPI_AUDIT.md`).

## Цель

Идентифицировать все места, где hardcoded money-семантика («ROI», «убыточный», «бюджет», «выручка», «рубл») и предложить **monetary** и **count** варианты для каждого.

## Карта изменений по файлам

### Backend (sidecar/econometrica/)

| Файл | Lines | Категория | Текущее | Monetary | Count |
|---|---|---|---|---|---|
| `engines/decomposer.py` | 29-34 | Thresholds comment | `ROI_DEEP_LOSS = 0.5  # < 0.5× = глубоко убыточный` | Same | Add comment: `CPU_VS_VALUE_DEEP_LOSS=2.0  # CPU > 2× value = глубоко убыточный` |
| `engines/decomposer.py` | 101 | CI suffix | `(широкий ROI-интервал)` | Same | `(широкий интервал CPU)` |
| `engines/decomposer.py` | 106 | Hard cap warn | `ROI завышен (не рубли?)` | Same | `CPU подозрительно низкий (проверьте единицы)` |
| `engines/decomposer.py` | 108 | Hard cap warn | `ROI нереалистичен (артефакт)` | Same | `CPU нереалистичен (артефакт)` |
| `engines/decomposer.py` | 110 | Deep loss | `Глубоко убыточный` | Same | `Глубоко убыточный (CPU > 2× ценности единицы)` |
| `engines/decomposer.py` | 113 | Breakeven | `На грани окупаемости` | Same | `На грани окупаемости (CPU близок к ценности)` |
| `engines/decomposer.py` | 629-630 | Sample text | `самый эффективный канал (ROI X×)` | Same | `даёт больше всего (CPU X ₽/упак)` |
| `engines/decomposer.py` | 686 | CI note | `Posterior CI на ROI/mROAS недоступны` | Same | `Posterior CI на CPU недоступны` |
| `engines/narrative_adapter.py` | 436 | Recommendation | `Сократить неэффективные каналы и сфокусировать бюджет` | Same | Same (term «бюджет» - universal про затраты) |
| `engines/narrative_adapter.py` | 462 | Recommendation | `даёт {pct}% продаж` | Same | Same |
| `engines/narrative_adapter.py` | 476 | Recommendation | `Сократить X и сфокусировать бюджет на Y` | Same | Same |
| `engines/narrative_adapter.py` | 595-596 | Comment | `доминирует бюджет` | Same | Same |

### Frontend (src/lib/) - top hotspots (30 files total)

| Файл | Категория | Что менять |
|---|---|---|
| `insights-rules.js` | Insights templates (8 функций) | 4×8 matrix параметризация по (mode, kpi_kind) |
| `objective-engine.js` | Mode descriptions | DEPRECATE entire file (заменён mode-derivation.js) |
| `components/pipeline/DecomposeStep.svelte` | Verdict table + headers | KPI/mode-aware conditional колонок (CPU vs ROI vs share) |
| `components/pipeline/ExpertDecomposePanel.svelte` | Expert verdict view | Same logic |
| `components/pipeline/OptimizeStep.svelte` | Sensitivity, sliders | KPI-aware labels (₽ ↔ count) |
| `components/pipeline/BudgetOptimizer.svelte` | Бюджет slider | Conditional label |
| `components/pipeline/ResponseCurves.svelte` | Y-axis label | Conditional «Продажи, ₽» / «Продажи, упак» |
| `components/pipeline/ROIComparison.svelte` | Title, columns | Whole component KPI-aware |
| `components/pipeline/TrafficLight.svelte` | Tones | OK as is (generic) |
| `components/pipeline/UnitCostsPanel.svelte` | Money-bound labels | Conditional за счёт mode |
| `components/pipeline/ValidateStep.svelte` | ObjectiveSelector embed | Full rewrite per ADR-015 |
| `components/pipeline/ObjectiveSelector.svelte` | 3 cards text | DEPRECATE (заменён KPISelector + PerChannelInputSelector) |
| `components/pipeline/ImportStep.svelte` | Pre-flight checks | Add count KPI support |
| `components/pipeline/ColumnMapper.svelte` | Role labels | Add explicit kpi_kind hint в KPI role |
| `components/pipeline/ChannelCategoriesPanel.svelte` | Categories text | OK as is |
| `components/pipeline/MQSBadge.svelte` | Quality score | OK as is (model quality) |
| `components/pipeline/OptimizeOnboarding.svelte` | Tour текст | Rewrite KPI-aware |
| `components/pipeline/ForecastHorizonPicker.svelte` | Horizon text | Conditional money/count |
| `components/pipeline/ExpertModelPanel.svelte` | Priors descriptions | OK (mathematical) |
| `components/pipeline/ExpertValidatePanel.svelte` | KPI metadata | Add kpi_kind display |
| `components/pipeline/ConvergenceDashboard.svelte` | R-hat etc | OK (mathematical) |
| `components/pipeline/ScenarioPlayground.svelte` | Scenario text | KPI-aware |
| `components/pipeline/TrustBanner.svelte` | Trust message | Add KPI context |
| `components/comparison/ModelComparisonView.svelte` | Comparison metrics | Add CPU/ROI conditional |
| `components/OnboardingOverlay.svelte` | Step 1 intro | Already updated 2026-05-12 |
| `pipeline-tours.js` | Tour highlights | KPI-aware tours |
| `hill.js` | Math labels | OK (math) |
| `psy.js` | UX psy messages | Review for KPI sensitivity |
| `project-state.js` | Store names | Replace `analysisObjective` → `derivedMode`/`kpiKind`/`perChannelInput` |

## Структурный план изменений (Stage 2-3-4)

### Stage 2 (Validate + Decompose)
- `decomposer.py` verdict table refactor (Lines 27-148).
- `insights-rules.js` 4×8 matrix.
- `DecomposeStep.svelte`, `ExpertDecomposePanel.svelte` conditional rendering.
- `ValidateStep.svelte` полный rewrite (KPISelector + PerChannelInputSelector + ModeDerivedExplanation).
- `objective-engine.js` → `mode-derivation.js`.

### Stage 3 (Optimize + Reports)
- `OptimizeStep.svelte`, `BudgetOptimizer.svelte` KPI/mode-aware.
- `ResponseCurves.svelte` axis labels conditional.
- `ROIComparison.svelte` → переименовать в `ChannelComparisonTable.svelte` (more generic).
- `narrative_adapter.py` recommendations.

### Stage 4 (Educational + Polish)
- `OptimizeOnboarding.svelte`, `pipeline-tours.js` - KPI-aware tour content.
- Custom glossary entries для CPU, value_per_count_unit, derived mode.

## Открытые вопросы для последующих этапов

1. **`narrative_adapter.py` - sentence templates с {var} interpolation.** Можно ли держать одну шаблонную строку с {metric_name} param (=ROI или CPU)? Решение: Stage 3 - `compose_recommendation(kpi_kind, ...)` helper.

2. **`hill.js` визуализация Hill curve.** Y-axis всегда target (выручка ₽ или count). X-axis - input (₽ или native units). Labels conditional.

3. **`MQSBadge.svelte`** - model quality score, не зависит от KPI. Оставить как есть.

4. **`TrustBanner.svelte`** - добавить KPI-aware context («модель работает в режиме CPU vs ценность лида»).

## Грубая оценка работы

- Backend texts: ~6 часов (decomposer + narrative_adapter refactor).
- Frontend UI texts: ~12 часов (30 .svelte files × KPI-aware rewrite).
- Insights rules: ~3 часа (4×8 matrix).
- Locale strings (strings_ru.json + strings_en.json): ~3 часа.

**Total: ~24 часа = 3 рабочих дня work, разнесённых между Stages 2-3-4.**
