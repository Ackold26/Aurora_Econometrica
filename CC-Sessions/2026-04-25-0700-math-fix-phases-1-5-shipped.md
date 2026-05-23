# Math Fix Phases 1-5 SHIPPED — 2026-04-25 07:00

**Branch:** `math-fix-v1.0.13`
**HEAD:** `2ed4d1f` (Phase 5 validation suite)
**Phase tags:** `v1.0.13-rc1-phase1` → `v1.0.13-rc5-phase5`
**Safety tag:** `v1.0.12-pre-fix-bundle`
**Predecessor:** `2026-04-25-0530-output-quality-stage-c-complete-plus-audit.md`

## TL;DR

All 11 P0 defects from math audit closed in single autonomous session.
6 commits + 5 phase tags. **81/81 unit tests + 65/65 narrative_adapter PASS.**
Phase 7 (live-test Kagocel + ship to v1.0.13-math-audited) pending — needs
Python sidecar rebuild and manual UI verification.

## Commits

| Phase | Commit | LOC | Closes | Description |
|-------|--------|-----|--------|-------------|
| 1 | `b6f6400` | 2 files +25/-26 | P0-7 | modeler.py:537 — gamma_scaled removed, raw gamma matching training. Test inverted to parity (1e-9). |
| 2 | `c065868` | 5 files +80/-23 | P0-1, P0-2, P0-9 | Hill normalization spend/mean Robyn-style across modeler/scenario/optimizer/decomposer. Pickle schema: model_version='1.1', removed media_stds, added intercept_mean + control_betas_mean. JS already correct (verified). |
| 3 | `89fb9cd` (decomposer.py) + `b072411` (tests) | 1+1 file | P0-3, P0-4, P0-10 | Decomposer rewrite: per-period contribution = β × hill(adstock(x)/mean) × y_std. Baseline = intercept × y_std + y_mean + control_effect × y_std. |
| 4 | `7daa7c4` | 2 files +49/-32 | P0-5, P0-6, P0-11 | Optimizer total_response + marginal_roi + response_curves: spend/mean + raw gamma matching training. P0-11 mixed-units guard with MIXED_UNITS error code. |
| 5 | `2ed4d1f` | 1 file +147 | regression gate | 9 ship-gate assertions: scenario sensitivity (>5% delta), monotonicity, optimizer non-trivial allocation + better response, P0-11 4-case guard coverage. |

Plus 2 auto-snapshot commits: `89fb9cd` (compress, captured Phase 3 decomposer.py) + `40fe0e4` (memory reflection of Phase 2).

## Test progression

| Phase | Tests | Notes |
|-------|-------|-------|
| Baseline | 64/64 | Pre-fix bug-signature regression detectors PASS |
| After Phase 1 | 64/64 | P0-7 test inverted to parity |
| After Phase 2 | 65/65 | P0-2 inverted + new spend/mean property |
| After Phase 3 | 71/71 | +6 decomposer assertions (monotonicity, bounded total, saturation curvature, baseline formula) |
| After Phase 4 | 72/72 | P0-5/6 inverted to parity + half-saturation property |
| After Phase 5 | 81/81 | +9 ship-gate assertions (scenario, optimizer, P0-11 guard) |

`tools/test_narrative_adapter.py` 65/65 PASS — no output-quality regression.

## Key technical decisions

### Phase 2 — Pickle compat detection in 4 engines
All engines (modeler/scenario/optimizer/decomposer) check `model_version` field.
Old pickles (`'1.0'` or absent) rejected with `error_code='MODEL_OUTDATED'`.
UI must show "переобучите модель" prompt. Old `.pkl` files in `models/history/`
preserved automatically (5 last versions retained).

### Phase 3 — Adstock applied AT decompose time
Per-channel adstock matches training transformation. Adstock config retrieved
from `config.adstock_config` (saved in pickle). Falls back to 'geometric' if
missing (backward-compat for partial config schemas).

### Phase 4 — P0-11 mixed-units guard logic
Native-mode (`total_budget_money_target=None`) requires:
- All channels in money (uc=1.0 для всех), OR
- All channels in native units (uc≠1.0 для всех)
- Otherwise: `MIXED_UNITS` error.
Money-mode (`total_budget_money` provided) bypasses guard since constraint is
explicitly in rubles.

### Phase 5 — Pure-formula tests, no real pickle
Live-test on Kagocel data deferred to Phase 7 (manual). Synthetic tests use
realistic posteriors (alpha=1.5, gamma=1.0, beta=0.7, y_std=300, y_mean=500)
to produce >5% scenario delta and non-trivial optimizer allocation.

## Files modified

```
sidecar/econometrica/engines/modeler.py    (+13/-6)   Phase 1 + 2
sidecar/econometrica/engines/scenario.py   (+11/-3)   Phase 2
sidecar/econometrica/engines/optimizer.py  (+30/-13)  Phase 2 + 4
sidecar/econometrica/engines/decomposer.py (+98/-57)  Phase 2 + 3
tools/test_math_correctness.py             (+325/-60) Phases 1-5
```

## Pending for Phase 7 ship

1. **Live-test Kagocel** (2-3h):
   - `python sidecar/build_sidecar.py` (sidecar rebuild required per `feedback_sidecar_rebuild_required`)
   - `npm run tauri dev`
   - Import `D:/Docs/Aurora_Ai/TestData/Econometrica/Kagocel_RF_MMM_dataset.xlsx`
   - Validate → Train → Decompose → Optimize → Scenario flows
   - Expected: NUTS R-hat ≤ 1.05, no divergences. Scenario ±50% delta KPI > 5% (was 0.05% pre-fix on 2026-04-24 live-test). Optimizer non-trivial allocation. What-if slider matches scenario backend within 5%.
2. **Old .pkl rejection UX**: verify error_code='MODEL_OUTDATED' triggers clear "переобучите модель" prompt in UI (front needs to handle).
3. **PASHE_IT.MD update**: breaking change notice — old .pkl rejected.
4. **Tag** `v1.0.13-math-audited` after merge to master.
5. **GH Release + Supabase publish** — separate ship session.

## Risks for Phase 7

- **R-hat regression** with new prior+normalization combination: priors `Beta(3,3)` для gamma and `Gamma(5,3)` для alpha may need tuning post-spend/mean change. Mitigation: if R-hat > 1.05, switch gamma prior to `HalfNormal(0.5)`.
- **Decomposer energy conservation**: per-period sum should ≈ y_predicted. If divergence > 0.5%, debug control effect transformation (z-score retained for controls).
- **Optimizer SLSQP convergence**: if solver fails on real Kagocel data, fall back to L-BFGS-B method.

## Memory updates

- `project_econometrica_math_audit` → ALL 11 P0 SHIPPED, Phase 7 pending
- `project_econometrica_hill_normalization_root_fix` → DONE (Phase 2)
- `project_econometrica_reconstruction_fix` → DONE (Phase 1)
- `project_econometrica_decomposer_rewrite` → DONE (Phase 3)
- `project_econometrica_optimizer_rescale` → DONE (Phase 4)
- `MEMORY.md` priority entries refreshed
