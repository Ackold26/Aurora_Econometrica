# Math Fix Post-Audit Hardening — 2026-04-25 09:00

**Branch:** `math-fix-v1.0.13`
**HEAD:** `58e6cf1` (post-audit hardening) + 2 follow-up commits
**Tags:** `v1.0.13-math-audited` (3a654f2) + `v1.0.13.1-post-audit-hardening` (58e6cf1)
**Predecessor:** `2026-04-25-0700-math-fix-phases-1-5-shipped.md`

## TL;DR

Self-review of Phases 1-7 found **4 hidden defects** that automated tests didn't catch:

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | CRITICAL | Decomposer waterfall: baseline + sum(channels) ≠ total_sales when R²<1 | Residual variance absorbed into baseline (Robyn convention) |
| 2 | HIGH | mROI/response_curves в y_norm scale, не KPI/spend (off by y_std factor 10-1000×) | × y_std multiplier added |
| 3 | MEDIUM | adstock_config schema inconsistency (decomposer handled both str+dict, others only str) | Standardize on str, defensive isinstance fallback |
| 4 | MEDIUM | Optimizer bounds=(0,0) для zero-spend channels (current=0 → permanently locked) | bounds = (0, total_budget × max_pct / n_ch) for new channels |

All 4 closed. **112/112 unit tests PASS** (added 2 new tests: mROI KPI-scale parity vs numerical derivative + zero-spend bounds).

## Defect details

### #1 Decomposer energy conservation (CRITICAL)

**Pre-fix code:**
```python
baseline_per_period = intercept_per_period + control_effect_per_period
baseline_total = float(baseline_per_period.sum())
```

**Issue:** Model fit is not perfect (R² typically 0.7-0.95). The waterfall display
showed:
- Baseline (intercept + controls)
- + sum(channel contributions)
- = "Итого" labeled as `total_sales = y_actual.sum()`

But the math:
- `baseline + sum(channels) = y_predicted.sum()` (model output)
- `≠ y_actual.sum()` (ground truth)

So the waterfall bars literally didn't add up to the displayed total. Visual
inconsistency — auditors would catch this in production.

**Fix:** Standard MMM convention (Robyn, LightweightMMM, Meridian) absorbs
unexplained variance into baseline (it's "stuff media didn't explain"):

```python
model_predicted_per_period = intercept + media_contrib + control_eff
residual = y_actual - model_predicted
baseline_per_period = intercept + control_eff + residual  # absorbs residual
```

**Test:** Synthetic 12-period 2-channel pickle. Assert:
- `|baseline + media - total| / total < 1%` (totals)
- `|baseline_t + sum(channels_t) - actual_t| / actual_t < 5%` per period

### #2 mROI/response_curves in KPI scale (HIGH)

**Pre-fix code:**
```python
mroi_current = float(marginal_roi(...)[0]) / max(mean_ch, 1e-10)
```

**Issue:** `marginal_roi` returns d(β·hill(x_norm))/d(x_norm) — derivative in
y_norm units. The chain rule for d(KPI)/d(spend):

```
d(KPI)/d(spend) = d(KPI)/d(KPI_norm) × d(KPI_norm)/d(x_norm) × d(x_norm)/d(spend)
                = y_std × marginal_roi × (1/mean)
```

Pre-fix multiplied by 1/mean (chain rule for spend) but FORGOT y_std (denormalization).
Result: displayed mROI in y_norm/spend, off by factor of y_std (typically 10-1000×).

**Fix:** Add y_std multiplier in optimizer.py for both mROI and response_curves.

**Test:** Numerical derivative `(kpi(s+ε) - kpi(s-ε))/(2ε)` vs analytical formula
at x = mean. rtol=0.01.

### #3 adstock_config schema (MEDIUM)

**Pre-fix decomposer.py inline ternary:**
```python
a_type = adstock_config.get(col, {}).get('type', 'geometric') if isinstance(adstock_config.get(col), dict) else adstock_config.get(col, 'geometric')
```

**Issue:** Inconsistent with modeler.py and scenario.py which assume
`adstock_config[col]` is `str`. The dict-with-'type' branch was speculative
(no schema documents this), reading code is harder.

**Fix:** Explicit isinstance branches with fallback. Tolerate both formats
for forward-compat but standardize on str.

### #4 Optimizer bounds=(0,0) for zero-spend channels (MEDIUM)

**Pre-fix:**
```python
bounds = [
    (current_spend[col] * channel_min(col), current_spend[col] * channel_max(col))
    for col in media_cols
]
```

**Issue:** If a channel had `current=0` (e.g., new channel being tested), bounds
= (0, 0). SLSQP locks it at zero. User can never get optimizer recommendation
for new channels.

**Fix:** Zero-spend channels get bounds = (0, total_budget × max_pct / n_channels).
Reasonable default that lets optimizer redistribute up to ~30-50% of budget if
new channel has high marginal ROI.

**Test:** Verify bounds[zero_spend_channel][1] > 0 with computed fallback value.

## Test coverage progression

| Stage | Tests | Notes |
|-------|-------|-------|
| Phase 5 baseline | 81/81 | Initial post-fix validation |
| + Phase 6 (auto-applied) | 95/95 | scenario adstock + incremental ROAS |
| + Phase 7 docs | 95/95 | CHANGELOG only, no tests |
| + Energy conservation test | 109/109 | per-period + totals |
| + mROI KPI scale + zero bounds | 112/112 | Self-audit fixes #2 + #4 |

## Files modified (post-audit)

```
sidecar/econometrica/engines/decomposer.py  (+15/-2)   energy conservation + adstock schema
sidecar/econometrica/engines/optimizer.py   (+27/-9)   mROI × y_std + bounds + response × y_std
tools/test_math_correctness.py              (+~80)     3 new tests
```

## Architectural improvements identified (not yet shipped)

These are **observations from the audit**, not active defects:

1. **DRY: intercept_mean computed twice in modeler.py** (line 522 in try-block + line 613 for pickle save). Refactor to compute once, reuse.

2. **modeler.py adstock_config not propagated through training**. User can specify type per channel but not hyperparameters (alpha, shape, scale). They use defaults. Document this as feature limitation OR support config schema for hyperparameters.

3. **scenario.py adstock starts with no carryover from training-end state**. Greenfield assumption — scenario period 1 ignores past adstock build-up. Document as design decision OR pass training-end adstock state as initial condition.

4. **Phase 5 ship-gate tests are pure-formula**. Real Kagocel pickle integration tests would catch e2e bugs that synthetic data misses. Add `tests/integration/` directory.

5. **mROI / response curves precomputed at decompose time, displayed at optimize time**. If user changes unit_costs between decompose and optimize, response curves use stale unit_costs. Either invalidate cache OR recompute at display.

These are P2 follow-ups, not blocking ship.

## Ship gate update

`v1.0.13-math-audited` tag is on `3a654f2` (before post-audit hardening).
**Recommend re-tag to `58e6cf1`** OR add explicit `v1.0.13.1` ship.

For commercial ship, use `v1.0.13.1-post-audit-hardening` (HEAD) — includes
all 4 hardening fixes.

## Lessons learned

1. **Self-review catches what tests don't.** The 4 issues had test coverage
   for related behaviors but not for the specific failure modes:
   - Energy conservation test wasn't there because pure-formula tests don't
     load real pickle.
   - mROI scale test passed when comparing analytical-vs-numerical of
     marginal_roi function, not testing the integration in optimizer's display.
   - adstock schema discrepancy not caught because both formats produce
     'geometric' when keys missing.
   - bounds=(0,0) issue not caught because synthetic test data had non-zero
     current spend for all channels.

2. **`feedback_shared_helpers_prevent_drift` lesson applies.** mROI displayed
   in optimizer is "shared" with response_curves and what-if. After Phase 4,
   only optimizer was patched; what-if HTML JS uses its own formula (correct,
   verified in Phase 2). Need integration tests across all 3 sites.

3. **Auto-process mediated changes need checkpoint.** Auto-snapshot commits
   captured my code changes between commits. Beneficial (no lost work) but
   makes diff history less linear. Future: explicit checkpoint at each phase
   boundary.

## Pending for ship (unchanged from previous session)

1. Live-test Kagocel (rebuild sidecar + npm tauri dev)
2. PASHE_IT.MD breaking change notice
3. Consider re-tag `v1.0.13-math-audited` → 58e6cf1 OR ship `v1.0.13.1`
4. GH Release + Supabase publish
