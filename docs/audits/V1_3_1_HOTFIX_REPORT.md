# v1.3.1 Hotfix Report

**Date:** 2026-05-12
**Branch:** `hotfix/v1.3.1` (parent: `feat/v1.3.0-next-gen`)
**Commit:** `7f11eef`

## Scope

Hotfix v1.3.1 закрывает critical + high deferred items из 2-х audits:
- v1.3.0 red-team audit (technical/math)
- v1.3.0 UX audit (flow / insights / visual)

## Fixed в hotfix v1.3.1

### CRITICAL Math (red-team audit B6)

**Goal-Seek monotonicity guard.**
- `sidecar/econometrica/optimize/inverse.py::_verify_monotonicity()` - NEW helper.
- Probes forward(B) на 5 equally-spaced points перед bisection.
- Если non-monotonic (Hill saturation с non-convex кейс) → fail-fast с actionable
  error: «Forward не монотонна - non-convex Hill suspected, рассмотрите Expert Mode».
- `bisect_for_target()` теперь имеет `verify_monotonic=True` default + `monotonicity_check`
  audit trail в response.

### CRITICAL UX (audit C3)

**ColumnMapperConfirm - visible roles review.**
- `src/lib/components/pipeline/ColumnMapperConfirm.svelte` - NEW.
- Table показывает detected roles per колонке + dropdown override (kpi / media /
  control / date / excluded).
- Stats row: «🎯 KPI: 1 · 📊 Каналы: 7 · 🔧 Контроль: 0 · 📅 Дата: 1».
- Warning banners при KPI=0 или media=0 (предотвращает ошибки до Model step).
- Готов для embed после Import shell (next integration task).

### HIGH UX (audit H9)

**Recommendation Card pattern.**
- `src/lib/components/pipeline/RecommendationCard.svelte` - NEW. Primary actionable
  visual card. Props: icon / title / text / detail / primaryAction / secondaryAction /
  tone (info|success|warn).
- Linear-gradient background + primary border + glow box-shadow для visual weight.
- `DecomposeStep` integration:
  - Computes `primaryRecommendation` через `$derived`.
  - Algorithm: overspending channels (gap < -10%) + underspending (gap > 10%) →
    suggest reallocation «Переложите X ₽ из Y в Z (gap analysis)».
  - Edge case: все balanced → suggest top driver review.
  - Primary action button «Перейти в Оптимизацию» → `pipelineCurrentStep.set(4)`.

### MEDIUM UX (audit M)

**IntroTutorial keyboard navigation.**
- Arrow keys: Left/Right = prev/next slide.
- Enter = next.
- Escape = skip.
- `role="dialog"` + `aria-modal="true"` + `aria-labelledby="intro-title"` для screen readers.

## Quality после hotfix

- 157/157 v1.3 critical tests pass (kpi_registry, safe_corridor, pickle_compat,
  mode_inference, column_detection, auto_price, verdicts_kpi_aware, kpi_labels)
- 0 svelte-check errors
- Cargo не trogан (no Rust changes)

## Deferred к v1.3.2 (с обоснованием)

### Reports HTML/PPTX KPI-aware rewrite
- **What:** 9+ hardcoded ROI mentions в `aurora_html/sections.py` + similar в `aurora_pptx/builder.py`.
- **Why deferred:** Полный rewrite 14 секций × 13 слайдов с conditional rendering per (mode, kpi_kind) - ~2 дня dedicated работы. Не quick hotfix.
- **Mitigation:** `data.kpi.labels` метаdata уже передается через narrative_adapter (commit `52c9801`). v1.3.2 dedicated reports KPI-aware sprint.
- **Impact:** Reports show ROI labels even when KPI=count → confusing для count KPI users, но workflow не ломается (numbers correct, labels mismatch).

### insights-rules.js KPI-aware rewrite (UX audit H7)
- **What:** 8 rule templates × все имеют ROI logic. Для count KPI должны быть CPU/value comparison + share-based для effectiveness mode.
- **Why deferred:** Полный pass - добавить ctx param + branch logic в 8 функциях insights = 0.5-1 день. Полу-fix risky (mixed metrics в одном insight). Better atomic.
- **Mitigation:** RecommendationCard в DecomposeStep сделана KPI-agnostic (basis = efficiency_gap не ROI).

### ROIComparison не KPI-aware (UX audit H8)
- **What:** Component name + axis labels hardcoded на ROI / выручка.
- **Why deferred:** Component используется в DecomposeStep - rewrite требует тест на эффект на charts.
- **Mitigation:** В режиме Эффективность component still renders, числа корректны, только labels misleading.

### Frontend tests setup (red-team audit C1)
- **What:** 0 .test.js файлов для 16 new Svelte components.
- **Why deferred:** Vitest+testing-library setup + writing tests = 2+ дня dedicated.
- **Mitigation:** 0 svelte-check errors, type safety через JSDoc.

### ColumnMapperConfirm integration в Pipeline
- **What:** Component готов, но не embedded в pipeline page.
- **Why deferred:** Need to integrate перед KPISelector (step 1 sub-step -1) OR в Import shell.
  Это touches Pipeline routing + state management - нужна aligned discussion с user.
- **Mitigation:** Standalone component готов, can integrate в любой time без UI rewrite.

### Recommendation Card в OptimizeStep
- **What:** RecommendationCard есть в DecomposeStep, но не в OptimizeStep после forward optimize.
- **Why deferred:** OptimizeStep сложный (2900 LOC), есть много existing result UI components.
  Risk of breaking existing layout. v1.3.2 - careful integration.

## Финальный pipeline status

**16 commits на feature branches (15 v1.3.0 + 1 v1.3.1):**
- `feat/v1.3.0-next-gen`: 15 commits (Stage 0-5 + 2 audits)
- `hotfix/v1.3.1`: 1 commit (this hotfix)

**Quality metrics:**
- 969 backend tests pass / 5 known skipped
- 0 svelte-check errors
- Cargo check OK
- 0 regression на pickle compat / decomposer invariants / ROI verdict tests

**Ready for pilot validate** (monetary scenario primary). Reports KPI-aware + insights
KPI-aware = v1.3.2 sprint scope.

## Recommended next steps

1. **Pilot validate Кагоцел + Венарус** (manual action на feat/v1.3.0-next-gen ИЛИ
   merge hotfix/v1.3.1 → feat/v1.3.0-next-gen → tag).
2. **Tag v1.3.0** после approve.
3. **v1.3.2 sprint** (~3 дня):
   - Reports KPI-aware rewrite (sections.py + aurora_pptx/builder.py)
   - insights-rules.js KPI-aware (8 functions × ctx param)
   - ROIComparison KPI-aware rename
   - ColumnMapperConfirm integration в pipeline
   - RecommendationCard в OptimizeStep
   - Frontend tests setup (vitest + critical path coverage)
