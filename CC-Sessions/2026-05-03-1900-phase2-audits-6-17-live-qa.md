---
tags: [session, compressed]
type: session
updated: 2026-05-03
---
# Quick Reference

Live QA сессия Aurora Econometrica Phase 2 на real customer pickle (Кагоцел РФ ММX 0305-26 multi-year + 25% historical inflation + planning mode). 12+ audit passes (6-17) cascaded — каждый user screenshot revealed new issue, я fixing iteratively. Math correctness + UX polish + multi-year inflation feature shipped.

**Topic:** phase2-audits-6-17-live-qa
**Branch:** `math-fix-v1.0.13` HEAD `2a0b1b0` (pushed origin)
**Test status:** 269/269 PASS, 0 svelte errors, 0 cargo warnings
**Status:** ✅ All 17 audit passes shipped + memory updated. 🟡 Pending: customer's monotonic verification после restart, Phase 2.6 reports, NSIS build/release, Phase 2.0 Part 2 (epistemic γ).
**Key files:** `optimizer.py`, `OptimizeStep.svelte`, `BudgetOptimizer.svelte`, `ResponseCurves.svelte`, `WaterfallChart.svelte`, `ConvergenceDashboard.svelte`, `UnitCostsPanel.svelte`, `ScenarioPlayground.svelte`, `DecomposeStep.svelte`, `insights-rules.js`, `validator.py`, `decomposer.py`, `scenario.py`, `server.py`, `project-state.js`, `project.rs`, `econometrica.rs`

## Learnings

### Math/Algorithm
1. **Hill-of-mean vs sum-of-Hills (M9 finding from prior session, ratified):** Aurora's optimizer was the outlier using Hill-of-mean approximation (single Hill eval × n_periods); scenario.py + decomposer.py use per-period sum-of-Hill. By Jensen's inequality: `hill(mean(x)) ≠ mean(hill(x))`. Difference up to 11% on short forecasts. Option C (per-period summation) corrects это в planning mode.

2. **SLSQP non-convex local-minima trap:** Aurora's optimizer SLSQP может застрять в local minima при wider bounds (extreme corners trap gradient). Multi-start best-of-N не гарантирует global. **Critical insight:** anchor design **only works if added as direct candidate** (not start point) — SLSQP в non-convex space может move AWAY from anchor.

3. **Multi-start parity для monotonic guarantee:** Anchor must use IDENTICAL multi-start strategy + IDENTICAL precision to main run, just within narrow_subset_bounds. 4 starts vs 14 starts (pass 16 vs main) leaves coverage gaps. Pass 17 fixed.

4. **Scale-mismatch везде:** training scale ≠ planning scale. Decomposer/optimizer/scenario internals имели inconsistencies: avgROI denominator (training spend) but text used planning budget; current_x = training total native vs optimal_x = forecast scale в response_curves; channelBudgets after optimize → forecast но curve.spend in mixed units.

5. **Per-channel constraints precedence dominates:** 3-level (per-channel > per-group > global) means widening globals doesn't loosen per-channel. Customer can be confused когда constraints persist. Orange banner crucial для disclosure.

6. **Inflation rollback weighted average (Phase 2 audit pass 4 cont):** customer enters current_cost (latest year) + annual_inflation_pct → backend computes `Σ year_cost × spend_share[year]` для accurate ROI на multi-year training data.

### Frontend/UX
7. **Aurora token system:** dark/light/sepia/fun themes via CSS vars (`--text-primary`, `--bg-card`, `--input-bg`, `--accent-glow`, `color-mix()`). Hardcoded fallbacks (`rgba(255,255,255,0.92)`) shadow real tokens на specific themes. Always test multi-theme.

8. **Backend echoes authoritative state, frontend reads:** When backend mutates data (inflation adjustment к unit_costs), it must echo adjusted state per channel. Frontend should prefer backend echo over store. Pre-fix: `effectiveUnitCosts = adjustedUnitCosts ?? store`.

9. **Scale-leakage между components:** state stored по training scale gets used в planning context → wrong numbers. Centralized derivable: `effectiveBaseBudget = planningBudgetMoney ?? currentTotalBudget`. All What-if/Forecast inflation/Optimize threading from this.

10. **ECharts gotchas:** auto-legend renders internal series names (`support`/`value`); table-layout:fixed cracks on missing colgroup col; default formatter 11-digit numbers clip in 60px container; default x/y auto-scale follows MAX data range, не channel-specific informative range.

## Decisions

### Architectural
- **Pass 17 multi-start anchor design final:** identical strategy к main run в default_bounds (14 starts: current + 6 pivot_up + 6 balance + all_upper). Anchor result added as direct candidate → mathematically guaranteed monotonic improvement with widening bounds.
- **Per-channel response curve range (revert pass 13):** per-channel upper = `max(2×cur_money, 2×opt_money, fallback_max_money)` — better visual для cross-channel saturation comparison. Customer's earlier request (curves к concу) honoured for slider/optimal range, не forced global max.
- **Three-way mROAS unification:** single source = backend `ch.mroi_current` (canonical `_compute_mroas_money`). Status mapped from `ch.action` key (Scale/Hold/Reduce/Cut/Uncertain). Table = insights = action backend recommendation.
- **avgROI scale consistency:** insight text uses training spend (denominator avgROI) instead of planning budget. Disclaimer что ROI на training, для planning см. Прогноз KPI.
- **What-if reference budget:** `effectiveBaseBudget` (planning > training). UI label conditional: «Бюджет планирования» в planner mode, «Текущий бюджет» в analyst.

### UX / Visualization
- Step-level «Сбросить расчёты» в top-right header (preserves model + decompose + unit_costs).
- Compact Y-axis formatter (K/M/B) для ConvergenceDashboard.
- Table colgroup widths optimized для content (Канал 24% / Расходы+Вклад 11% each / ROI+Gap 7% each / Decay 11% / Вердикт 29%).
- Stray ECharts default legend on WaterfallChart explicitly hidden.
- Multi-year inflation UI: per-channel `%/год (история)` input в UnitCostsPanel.

## Pending

### Customer-side QA
1. **Restart Tauri** для Python sidecar reload (passes 12, 13, 15, 16, 17 — all backend changes).
2. **Verify monotonic improvement** в Optimize after restart — wider bounds (0/500) должен дать ≥ narrow (20/200).
3. **Manual QA на 3 customer pickles** (Kagocel, Венарус, MMX synthetic) — Phase 2.8 acceptance gate.

### Backend / Build
4. **Phase 2.6 reports** — HTML/PPTX/XLSX forecast section additions (~1 day).
5. **v1.2.0 NSIS build** + Supabase + rosst-updates `latest.json` + GH Release tag.
6. **Phase 2.0 Part 2** (post-ship calibration): epistemic γ recalibration с bootstrap CI (currently default 0.3) + hierarchical × extreme threshold.

### Frontend deferred
7. Phase 2.4 polish: `ResultInterpretation` extension, `QualityStampBadge` inline render, planning glossary i18n.
8. Phase 2.5 Min scenario library: ScenarioPlayground extension с save + 1-on-1 compare.

## Files Modified

### Python backend
- `sidecar/econometrica/engines/optimizer.py` — Phase 2 inflation adjustment, default-anchor (passes 7/9/12/16/17), response_curves per-channel upper, KPI-aware cap; pass 1 Option C planning_mode dispatch (earlier in session lineage)
- `sidecar/econometrica/engines/decomposer.py` — `unit_cost_inflation_pct` parameter
- `sidecar/econometrica/engines/scenario.py` — inflation adjustment + forecast_periods threading
- `sidecar/econometrica/engines/validator.py` — date_stats {min_date, max_date, unique_years, n_years}
- `sidecar/econometrica/engines/persistence.py` — Phase 2 fields setdefault + G2 inference helpers
- `sidecar/econometrica/server.py` — DecomposeRequest/OptimizeRequest/ScenarioRequest +unit_cost_inflation_pct + forecast_periods
- `sidecar/econometrica/utils/forecasting.py` (NEW) — Option C math layer
- `sidecar/econometrica/utils/forecast_validation.py` (NEW) — validation helpers
- `sidecar/econometrica/utils/unit_cost_inflation.py` (NEW) — inflation rollback math
- `sidecar/econometrica/utils/posterior_propagation.py` — verdict_tier extension с extrapolation_severity
- `sidecar/econometrica/utils/kpi_registry.py` — forecast_horizon_max_multiplier per KPI

### Rust Tauri
- `src-tauri/src/commands/econometrica.rs` — econ_optimize/decompose/scenario/forecast_context/forecast_scaling +new params
- `src-tauri/src/commands/project.rs` — ProjectInfo.unit_cost_inflation_pct field + project_update handler
- `src-tauri/src/lib.rs` — register new commands

### Svelte frontend
- `src/lib/components/pipeline/OptimizeStep.svelte` — planning context derived (effectiveBaseBudget/Periods/Label), reset button, mode toggle, picker, theme tokens, planning_mode banner, mROAS table source
- `src/lib/components/pipeline/BudgetOptimizer.svelte` — adjustedUnitCosts prop preference
- `src/lib/components/pipeline/ResponseCurves.svelte` — adaptive xAxisMax via channelBudgets
- `src/lib/components/pipeline/WaterfallChart.svelte` — explicit legend:false
- `src/lib/components/pipeline/ConvergenceDashboard.svelte` — ExpandableCard wrapper, R²/MAPE HTML overlay (theme-contrastable), Y-axis compact formatter
- `src/lib/components/pipeline/UnitCostsPanel.svelte` — historical %/год input, per-year cost breakdown preview
- `src/lib/components/pipeline/ForecastHorizonPicker.svelte` (NEW) — preset + custom periods/budget с manual edit flag
- `src/lib/components/pipeline/ScenarioPlayground.svelte` — planning props threading
- `src/lib/components/pipeline/DecomposeStep.svelte` — table colgroup 7-col fix + word-wrap
- `src/lib/components/pipeline/DecomposeStep.svelte` — unit_cost_inflation_pct invoke threading
- `src/lib/insights-rules.js` — actionToStatus mapping, avgROI scale fix, decompose 100% rounding
- `src/lib/project-state.js` — planningMode/forecastConfig/forecastContext/unitCostInflation stores

### Tests + docs
- `tools/test_forecasting.py`, `tools/test_forecast_validation.py`, `tools/test_persistence_phase2.py`, `tools/test_server_phase2_endpoints.py`, `tools/test_phase2_synergies.py`, `tools/test_unit_cost_inflation.py` (all NEW from earlier passes)
- `docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md`, `docs/PLANNING_MODE_METHODOLOGY.md`, `docs/audit_v2_0_synthetic_results.json`

## Setup & Config Changes

- **Pickle schema additive (Phase 2):** `training_granularity`, `train_x_norm_quantiles`, `seasonality_detected`, `unit_cost_inflation_pct` — все additive, backward compat preserved (`#[serde(default)]` в Rust, `setdefault` в Python).
- **ProjectInfo Rust struct:** added `unit_cost_inflation_pct: HashMap<String, f64>` с #[serde(default)].
- **KPIConfig:** added `forecast_horizon_max_multiplier` + `forecast_horizon_warn_multiplier` (sales 2.0/1.5, awareness 1.5/1.2).
- **No version bumps:** stay в v2.0 schema (Phase 2 fields additive).

## Errors & Workarounds

### Critical found and fixed
- **B5 (CRITICAL persistence loss pass 5):** `project_update` Tauri handler не handled `unit_cost_inflation_pct` → values lost on save. Fixed: added field + handler + ProjectInfo struct.
- **Pass 6 money mismatch (1.787B ↔ 2.124B):** backend применил inflation adjustment, frontend recomputed via raw store. Fixed: `adjustedUnitCosts` derived от `ch.unit_cost` echo.
- **Pass 7-17 monotonic guarantee saga:**
  - Pass 7: anchor as start point — wrong, SLSQP could move away в non-convex space.
  - Pass 9: added partial fallback — still flawed.
  - Pass 12: anchor as direct candidate — correct concept, но reduced precision (maxiter=100, ftol=1e-6).
  - Pass 16: aligned precision (maxiter=200, ftol=1e-7), but anchor имел только 4 starts vs main's 14.
  - **Pass 17 (FINAL):** identical 14-start strategy в default_bounds. True monotonic guarantee.
- **Pass 14 (101%):** rounding both basePct=92.5 and mediaPct=7.5 up gives 93+8=101%. Fix: round basePct first, derive mediaPct = 100 - rounded.

### Per-channel constraints persistence
Customer's «У 4 каналов задан per-channel Мин/Макс» orange banner показывает что per-channel limits dominate globals (3-level precedence). Widening globals doesn't help для tej channels. Customer needs to click «Сбросить все» для apples-to-apples comparison.

## Full Session Notes

### Session Timeline (chronological)

**Audit pass 6** (`4a7e153`):
- **Trigger:** Customer screenshot — banner «Оптимизирую 1.787B», display «Общий бюджет 2.124B». Mismatch +19%.
- **Root cause:** Backend применил inflation adjustment к unit_costs (current 250k → weighted-avg ~200k). Frontend BudgetOptimizer recomputed via `$unitCosts` store (= current cost) → discrepancy.
- **Fix:** `adjustedUnitCosts` derived от backend's `ch.unit_cost` per channel echo. Used preferentially. Plus Response Curves x-axis adaptive (от channelBudgets, не curve.spend native max).

**Reset button** (`3fbc3a2`):
- **Trigger:** «добавь на экран Оптимизации кнопку сбросить все рассчёты»
- **Placement:** top-right header (рядом с «? Показать тур»)
- **Naming:** «↻ Сбросить расчёты»
- **Confirm dialog** перед action. Resets optimize result + sliders + planning mode + What-if + Forecast inflation. Preserves model/decompose/unit_costs.

**Audit pass 7** (`e75fa39`):
- **Trigger:** Customer reported wider bounds (0/500) дают хуже optimum (4.6%) чем narrow (20/200) с 5.2%.
- **Cause analysis:** SLSQP non-convex trap, multi-start best-of-N не гарантирует global, per-channel precedence persistence.
- **Initial fix (flawed):** «default-bounds anchor» — SLSQP в default-bounds (intersection user's с 20-200%), result projected к user's bounds, used as additional multi-start start point.
- **Why flawed:** SLSQP в non-convex space может move AWAY from anchor, лending в worse local minimum в wider space.

**Audit pass 8** (`27d3244`):
- **Trigger:** Customer asked why mROAS table values ≠ banner insight values. TRPs «0.00×» в table но «193.89×» в banner.
- **Cause:** TWO different formulas под one label. Table = `ch.mroi_current` (backend canonical с adstock_factor + unit_cost normalization). Banner = frontend `marginalROI()` (raw Hill, без adstock factor). 100×+ разница.
- **Fix:** insights-rules.js использует `ch.mroi_current` directly. Single source of truth.
- **Bonus fix:** What-if `curMoney` was training currentSpend × unit_costs. In planner mode use `effectiveBaseBudget` (planning > training fallback).

**Audit pass 9** (`4d62bf1`):
- **Trigger:** Customer's «детальный технический аудит, найди ошибки + синергии».
- **3 issues:** insights status thresholds 1.5/0.8 hardcoded vs canonical compute_channel_action; pass 7 brittle (SLSQP failure path); response curves curve.current_x = training scale, optimal_x = forecast scale (mixing).
- **Fixes:** actionToStatus mapping (Scale→scale, Hold/Watch→stable, Reduce/Cut→saturated, Uncertain→unused); always add anchor seed (graceful failure); xMax только от channelBudgets.

**Y-axis fix** (`fd3ee70`):
- **Trigger:** Customer screenshot ConvergenceDashboard с Y-axis «00 000 000» (clipped).
- **Cause:** Default formatter `Math.round(v).toLocaleString('ru-RU')` produces «100 000 000» (11 chars × ~7px = 77px) but grid.left=60px container clipped.
- **Fix:** compact formatter K/M/B (4 chars).

**Table column widths** (`6df9c50`):
- **Trigger:** Customer «Детализация по каналам» Вердикт обрезался до 1-2 букв.
- **Cause:** colgroup имела только 6 col-widths для 7 столбцов. Decay column missing → table-layout:fixed cracked, residual distribution отдавала Вердикт 0%.
- **Fix:** added 7th col, redistributed widths (Канал 24% / Расходы+Вклад 11% / ROI+Gap 7% / Decay 11% / Вердикт 29%). Padding 10→8px, white-space:nowrap on th, word-wrap на td.

**Audit pass 12** (`88600d4`):
- **Trigger:** Customer повторил «не помогло» — 4.8% (20/200) → 3.7% (0/500) persistent.
- **Realization:** Pass 7 anchor as start point flawed. SLSQP в non-convex space может deviate.
- **Fix:** anchor as DIRECT candidate (без re-running SLSQP в user's bounds). x_default feasible в user's wider bounds (default ⊆ user) → its objective valid. min(candidates by .fun) automatically picks anchor если other candidates worse. Floor at default's objective guaranteed.

**Audit pass 13** (`5b8bcee`):
- **Trigger:** Customer «кривые всех медиа должны быть дорисованы до конца шкалы».
- **Fix:** `global_upper_money = max(cur_money*2, money_target*1.05) across channels`. Each channel's native upper extends к global / unit_cost.
- **Subsequent revert (pass 15):** this made curves squashed visually because most channels saturate в малой части global x-range.

**Audit pass 14** (`28c559d`):
- **Trigger:** Customer «проверь логику между графиками и инсайтами»
- **Bug:** «93% базовые + 8% медиа = 101%» — basePct=92.5 → toFixed «93», mediaPct=7.5 → toFixed «8», both round up.
- **Fix:** `basePctRounded = Math.round(basePct)`, `mediaPctRounded = 100 - basePctRounded`. Sum guaranteed = 100.
- **Bonus:** WaterfallChart stray «support / value» legend (default ECharts auto-legend). Fix: explicit `legend: { show: false }`.

**Audit pass 15** (`eee37bd`):
- **Trigger:** Customer screenshot Optimize step — «Средний ROI 0.18× с бюджетом 1.781B → медиа 842M». Math 842/1781=0.47, не 0.18.
- **Bug:** insights mixed scales. avgROI = totalContribDec/totalSpendDec (training, 842/4338=0.19). Text used totalBudgetMoney (planning 1.781B) → visual inconsistency.
- **Fix:** text shows training spend (matches avgROI denominator). Tip clarifies ROI на training, planning может отличаться.
- **Question 2:** «уверены ли в shape кривых» (резко в горизонт). Math correct (Hill с learned α + γ), but pass 13 visual artifact. Fix: revert к per-channel upper для better individual-curve detail.

**Audit pass 16** (`5dcec9d`):
- **Trigger:** Customer reported persistent 5.4 → 5.3 regression after pass 12.
- **Cause:** anchor SLSQP runs со снижой precision (maxiter=100, ftol=1e-6) vs main runs (maxiter=200, ftol=1e-7). Anchor мог сходиться на 0.1pp хуже.
- **Fix:** aligned precision + multi-start anchor (4 starts).
- **Still incomplete:** main run had 14 starts, anchor had 4. Coverage gap.

**Audit pass 17** (`2a0b1b0`):
- **Trigger:** «обдумай и проверь еще раз. скорректируй при необходимости»
- **Realization:** pass 16 anchor имел 4 starts vs main's 14 — could miss optimum found through specific start pattern.
- **Fix:** identical 14-start strategy в default_bounds (current + 6 pivot_up + 6 balance + all_upper). All SLSQP runs с same precision. Best of these = anchor candidate.
- **Math guarantee:** anchor's best ≥ user's narrow-bounds best (same problem structure, same coverage, same precision). True monotonic improvement.

### Customer screens / questions / answers

1. «бюджет планирования 1.787B, распределение 2.124B — почему?» → Pass 6 (effectiveUnitCosts)
2. «шкала Response Curves до 12000M при бюджете TRP 1564M» → Pass 6 adaptive xAxis
3. «добавь сбросить расчёты» → Reset button (placement: top-right, name: «↻ Сбросить расчёты»)
4. «расширил bounds — оптимизация хуже» → Pass 7 → 12 → 16 → 17 saga
5. «mROAS table ↔ insights не совпадают» → Pass 8 single source unification
6. «детальный аудит» → Pass 9 (status mapping, scale-correct curves)
7. «шкала с нулями» → Y-axis compact formatter
8. «таблица колонки» → Column widths fix
9. «кривые до конца шкалы» → Pass 13 (later reverted)
10. «проверь логику» → Pass 14 (rounding, legend)
11. «учти этот экран» → Pass 14 verification
12. «проверь Optimize logic» → Pass 15 (avgROI scale, curves shape)
13. «не помогает после restart» → Pass 16 (precision)
14. «обдумай и проверь ещё раз» → Pass 17 (full multi-start)

### Cumulative session statistics
- **Audit passes (this session 6-17):** 12
- **Audit passes (across whole Phase 2):** 17 (including earlier 1-5)
- **Commits this session:** ~20
- **Tests:** 269/269 PASS, 5 skipped
- **Files modified:** 25+
- **Customer-reported issues fixed:** 14
- **Memory updated:** MEMORY.md index entry + project_econometrica_phase2_planning_mode.md detailed section

### Repository state (end of session)
```
Branch: math-fix-v1.0.13
HEAD: 2a0b1b0 (pushed origin)
Working tree: clean
Memory: synced with session
```

### Next session triggers
- «manual QA» → run dev + customer pickles, verify monotonic
- «v1.2.0 ship» → bump version, NSIS, GH Release, Supabase
- «Phase 2.6 reports» → HTML/PPTX/XLSX forecast sections
- «Part 2» / «epistemic γ» → real MMM training + bootstrap CI calibration
- «restart issue» → Customer needs Tauri full restart for Python sidecar reload (всё latest backend changes)
