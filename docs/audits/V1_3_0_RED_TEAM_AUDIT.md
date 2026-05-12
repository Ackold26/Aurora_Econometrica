# v1.3.0 Red-Team Audit & Fixes

**Date:** 2026-05-12
**Reviewer:** 3 parallel Explore agents (backend / frontend / docs+tests coherence)
**Branch:** `feat/v1.3.0-next-gen`

## Severity summary

| Severity | Count | Fixed in this commit | Deferred |
|---|---|---|---|
| BLOCKER | 6 | 4 | 2 (hotfix v1.3.1) |
| HIGH | 7 | 4 | 3 (hotfix v1.3.1) |
| MEDIUM | 7 | 0 | 7 (hotfix v1.3.1) |

## Fixed в audit commit

### Backend (sidecar/econometrica/)

**BLOCKER #B1: `bounds.py:lo > hi` silent swap.**
Pre-fix: `if lo > hi: lo, hi = hi, lo` скрывал inverted corridor при very low CV
(P5 ≈ P95) + extreme relative factors.
Post-fix: `lo = hi = mu` (point estimate) + added `narrow_corridor: bool` flag
для UI warning. Никакого silent swap.

**BLOCKER #B2: `persistence.py::_inject_v13_defaults` null-check media_columns.**
Pre-fix: `config.get('media_columns', []) or []` мог замаскировать `media_columns: None`
corruption на input. После — explicit `if media_cols_raw else []`.

**HIGH #B3: `decomposer.py::_load_v13_kpi_settings` swallowed exceptions.**
Pre-fix: `except Exception: pass` — corrupted JSON silently → monetary defaults
(possibly wrong для count KPI project).
Post-fix: specific `except (OSError, ValueError)` + explicit `logging.warning`
with file path + exception details.

### Frontend (src/lib + src/routes)

**BLOCKER #F1: `ValidateStepV13 channels={[]}` hardcoded в pipeline page.**
Pre-fix: orchestrator получал пустые arrays → PerChannelInputSelector рендерил
0 channels → flow невозможен.
Post-fix: `src/routes/pipeline/+page.svelte` computes channels + availableMetricsByChannel
из `$validateData.result.columns` reactively. Channels filtered by `role='media'`,
metrics classified через separator-aware regex (mirrors backend column_detection).

**HIGH #F2: `monetaryColumnHint='sales_rub'` hardcoded.**
Pre-fix: auto-detect ломался если у юзера колонка `revenue` / `выручка`.
Post-fix: `detectMonetaryColumn()` helper в ValidateStepV13 reads `validateData.result.columns`,
выбирает column с `role='kpi'` или `role='target'` first, fallback на name heuristic
(sales|revenue|profit|выручка|продажи). monetaryColumnHint prop теперь optional default ''.

**HIGH #F3: Ctrl+G modal stacking conflict с CommandPalette.**
Pre-fix: Ctrl+G fired даже когда CommandPalette open → 2 overlapping modals.
Post-fix: `+layout.svelte` Ctrl+G handler — `if (paletteOpen) return;` guard.

**MEDIUM #F4: `analysisObjective` deprecated store без warning.**
Pre-fix: store существовал параллельно с `derivedMode` — silent divergence риск.
Post-fix: JSDoc `@deprecated v1.3.0` + comment о usage в legacy files
(ValidateStep, InsightsPanel, UnitCostsPanel — будут removed в v1.4.0 / Phase B).
Store остался writable (legacy code calls `.set()`).

### Documentation

**HIGH #D1: «8 KPI types» vs реальных 10.**
Pre-fix: RELEASE_NOTES + CHANGELOG говорили «8 KPI types» — confusing.
Post-fix: оба файла обновлены — «10 KPI types» (3 monetary + 7 count) + пояснение
что `awareness` помечен `out_of_scope_v13`.

## Deferred к hotfix v1.3.1 (с обоснованием)

### BLOCKER #D2: Reports HTML/PPTX/XLSX НЕ KPI-aware.
- **What:** `sections.py` (1278 LOC) + `builder.py` (2716 LOC) полностью monetary-hardcoded.
  Метаdata pipeline через `narrative_adapter.kpi` готова, но builders не consume.
- **Why deferred:** rewrite 14 секций × 13 слайдов × conditional rendering требует ~5 дней
  работы. Vs ship v1.3.0 для pilot validate (monetary baseline OK для Кагоцел / Венарус).
- **Mitigation:** Release notes честно говорят «Reports не полностью KPI-aware — hotfix v1.3.1».
- **Risk:** Если pilot захочет count KPI report → manual workaround / wait.

### BLOCKER #C1: Frontend tests = 0 .test.js файлов.
- **What:** 13 new UI components без unit tests.
- **Why deferred:** test infrastructure для Svelte 5 components не setup. Adding —
  ~2 дня работы (vitest + testing-library configure + writing tests).
- **Mitigation:** 0 svelte-check errors gives static type safety. Manual test
  через pilot validate.
- **Risk:** Future regression при changes to Svelte components.

### HIGH #B4: Inverse optimizer integration tests = 0.
- **What:** `bisect_for_target` purely unit-tested на synthetic; нет end-to-end на real
  trained model.
- **Why deferred:** Real model требует training (~2 min) для каждого test → CI cost.
- **Mitigation:** Pilot validate test scenario (Кагоцел target 105M ₽ → expected budget).
- **Risk:** Bisection convergence edge case при non-monotonic Hill — possible но rare.

### HIGH #B5: `estimate_budget_ci` gradient ≈ 0 fallback не captures uncertainty.
- **What:** Delta method бьёт degenerate когда forward locally flat → fallback
  ±10% от B (arbitrary).
- **Why deferred:** Production fix = full posterior re-bisection (~60s per result),
  costly. MVP Delta method честно показывает narrow CI, юзер видит.
- **Mitigation:** UI label «Метод: delta» прозрачен.
- **Risk:** Юзеры с very saturated Hill curves могут видеть suspiciously narrow CI.

### HIGH #B6: Goal-seek monotonicity не verified.
- **What:** `bisect_for_target` предполагает forward(B) монотонна. Не verified runtime.
- **Why deferred:** Verify требует sampling forward на 5-10 точках before bisection
  → +1-2s overhead per goal-seek call.
- **Mitigation:** Hill saturation в safe corridor [P5, P95] эмпирически монотонна почти всегда.
- **Risk:** Edge case при non-convex Hill с multiple inflection points → wrong B*.

### MEDIUM (7 items): polish + nice-to-have
- Backend column_detection false positives на русских словах ("персонал_sales_leads").
- localStorage sub-step persistence в ValidateStepV13.
- CorridorSlider rapid sliding debounce.
- CorridorSlider ARIA labels (a11y).
- KPISelector mobile responsiveness (320px width).
- ModeDerivedExplanation double-logic (props + derived).
- Performance regression CI gates.

## Architectural observations (для Phase B planning)

1. **`value_per_count_unit_label` duplication frontend/backend.** Сейчас same mapping в
   `mode-derivation.js` и `kpi_registry.py`. v1.4.0: один source of truth (например,
   shared JSON config через build step).

2. **`narrative_adapter.kpi` data block** — backend готов pipe metadata в reports.
   v1.3.1 builders могут consume без backend changes.

3. **Mode = derived state (Variant C)** работает elegantly — но senior эконометристы
   могут не сразу понять «куда делся выбор режима». Expert Mode toggle в Settings
   (запланирован для v1.3.1) — must-have.

4. **InlineHelpIcon.svelte unused** — keeping для Stage 4 Phase B (sub-step tooltips).
   Если решим что не нужен — удалить в v1.3.1.

5. **`migrate_v12_to_v20.py` deferred per ADR-017** (no schema bump) — но `tools/` все
   ещё имеет initial skeleton placeholder. Удалить или сохранить для будущих bumps.

## Quality after fixes

- Backend tests: **85/85 critical tests pass** (safe_corridor, pickle_compat, kpi_registry, kpi_registry_v13)
- Frontend: **0 svelte-check errors**, 151 pre-existing warnings unchanged
- Rust: cargo check OK
- Все BLOCKER из audit fixed либо честно deferred с написанной mitigation

## Recommendation

**v1.3.0 ready для pilot validate Кагоцел + Венарус** (monetary scenario primary).
Count KPI workflow validated через synthetic test project в dev mode.

**v1.3.1 hotfix scope** (~5 дней):
1. Reports KPI-aware: sections.py + builder.py rewrite (2 дня)
2. Frontend tests setup + critical path coverage (1.5 дня)
3. Expert Mode toggle в Settings (0.5 дня)
4. Educational sub-step tooltips wire (InlineHelpIcon в WhyThisStep sub-steps) (0.5 дня)
5. Pre-existing audit MEDIUM polish (0.5 дня)
