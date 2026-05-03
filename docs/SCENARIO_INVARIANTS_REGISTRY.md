# Scenario Engine Invariants Registry — formal spec

**Branch:** `math-fix-v1.0.13`
**Established:** 2026-05-03 (Phase A1 of engine audit extension)
**Property-based tests:** `tools/test_scenario_invariants.py` (131 tests)
**Edge cases:** `tools/test_scenario_edge_cases.py` (30 tests)
**Math refs:**
- `docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md` §2bis — 3-way alignment
- `docs/MATH_AUDIT_v1_3_PHASE_0_1.md` — chain rule context

---

## Purpose

Formal contract for `engines/scenario.py:predict_scenario`. Any refactor must
preserve these invariants; every new claim must be added here AND covered by a
property-based test.

---

## Invariants

### S1 — Per-period decomposition

```
predicted[t] == baseline_per_period + Σ_ch channel_contribution[ch][t]
```
Per-period sum identity within rounding tolerance (1.5%).

**Test:** `test_S1_per_period_decomposition` × 15 seeds.

---

### S2 — Total energy conservation

```
sum(predictions) == baseline_kpi + Σ_ch sum(channel_contribution[ch])
```
**Test:** `test_S2_total_energy_conservation` × 15 seeds.

---

### S3 — Sign / scale invariants

For positive media plan:
- `predicted_kpi > 0`
- `baseline_kpi > 0`
- `incremental_kpi >= 0` (media adds value, не subtracts)

**Test:** `test_S3_predictions_positive_and_incremental_nonneg` × 10 seeds.

---

### S4 — Money conservation

```
total_spend_money == Σ_ch per_channel_native[c] × unit_cost[c]
```
within 0.5% (round-2 tolerance).

**Test:** `test_S4_money_conservation` × 10 seeds.

---

### S5 — Single-period plan distribution

```
plan_n == 1  ∧  forecast_periods == N  →  output predictions length == N
                                          AND Σ media_plan[col] == input_total
```

**Note:** scenario engine **mutates** input `media_plan` dict in this case (rewrites
single-period entry к N-element list of `total/N`). UI callers should pass deep copy
to avoid surprises. See SCENARIO_DECOMPOSER_AUDIT_OUTCOME.md finding S-low1.

**Test:** `test_S5_single_period_distribution` × 5 seeds.

---

### S6 — Adstock semantics

For positive flat input + decay ∈ (0, 1):
- All adstock values ≥ 0
- `sum(adstock) ≥ sum(raw)` — carryover boost (Aurora geometric adstock convention)

**Test:** `test_S6_adstock_positive_and_carryover` × 20 seeds (pure math, no scenario).

---

### S7 — Hill saturation bounds

For finite `x_norm ≥ 0`: `0 ≤ hill(x_norm; α, γ) < 1` strictly.

**Test:** `test_S7_hill_bounds` × 20 seeds.

---

### S8 — Posterior CI ordering

When `posterior_samples` available (v1.2+ pickles):
```
predicted_kpi_ci_low ≤ predicted_kpi ≤ predicted_kpi_ci_high
incremental_kpi_ci_low ≤ incremental_kpi ≤ incremental_kpi_ci_high
lift_pct_ci_low ≤ lift_pct ≤ lift_pct_ci_high
```
within 5% margin (HDI ≠ percentile в edge cases).

**Test:** `test_S8_posterior_ci_ordering` × 10 seeds.

---

### S9 — ROAS CI consistency

```
roas_money_ci = incremental_kpi_ci / total_spend_money   (constant denominator)
```
Phase 1.9 fix (C2 audit 2026-04-26) introduced `_MIN_SPEND_FOR_ROAS_CI=100` floor
to prevent CI explosion at near-zero spend.

**Test:** `test_S9_roas_ci_consistency` × 10 seeds.

---

### S10 — Determinism

Two consecutive calls с identical config produce byte-identical predictions +
channel_contributions + totals.

**Test:** `test_S10_determinism`.

---

### S11 — Engine identity vs manual sum-of-Hill

Scenario's media KPI matches manual `Σ_ch β · sum(hill(adstock(x_t)/mean)) · y_std`
within 0.5% (extension of optimizer's I8 invariant).

**Test:** `test_S11_scenario_identity_with_manual_sum_of_hills` × 5 seeds.

---

### S12 — Forecast horizon decoupling

```
plan_n == 1  ∧  forecast_periods == N  →  n_periods == N  AND  len(predictions) == N
```

**Test:** `test_S12_forecast_horizon_length` × {4, 8, 12, 24, 52}.

---

### S13 — Money-mode coverage flag

```
units_fully_covered == True   →  total_spend_money is not None  AND  roas_money is not None
units_fully_covered == False  →  total_spend_money is None       AND  roas_money is None
```

**Tests:** `test_S13_money_mode_flag_when_partial_coverage`, `test_S13b_money_mode_flag_when_full_coverage`.

---

### S14 — Graceful errors with explicit error_codes

| Trigger | error_code |
|---|---|
| `media_plan == {}` | `MEDIA_PLAN_EMPTY` |
| `len(any plan list) == 0` | `MEDIA_PLAN_EMPTY` |
| Untrained channel в plan + spend > 0 | `UNTRAINED_CHANNEL` |
| `model_version == '1.0'` | `MODEL_OUTDATED` |
| `models/latest.pkl` missing | `MODEL_NOT_FOUND` |

Phase 3 audit fix added `error_code` к ранее-anonymous errors.

**Tests:** `test_S14_empty_plan_rejected`, `test_S14_untrained_channel_rejected`, `test_S14_model_not_found`.

---

## Multi-period plan handling (documented behavior)

Scenario engine sets `n_periods = max(plan_n, training_n_periods_default)` where
`training_n_periods_default = plan_n` (NOT training data length) **except** when
`plan_n == 1` (then training data length is read).

Implication: multi-period plan dictates n_periods. 5-month plan на 24-month
training → predictions have 5 periods. NOT auto-padded к training horizon. Use
single-period (length 1) input + `forecast_periods` to control horizon
explicitly.

**Tests:** `test_G1`, `test_G2`, `test_G3` в edge cases.

---

## Summary

| ID | Property | Test reference |
|---|---|---|
| S1 | Per-period decomposition | invariants × 15 |
| S2 | Total energy conservation | invariants × 15 |
| S3 | Sign / scale | invariants × 10 |
| S4 | Money conservation | invariants × 10 |
| S5 | Single-period distribution | invariants × 5 |
| S6 | Adstock semantics | invariants × 20 |
| S7 | Hill bounds | invariants × 20 |
| S8 | Posterior CI ordering | invariants × 10 |
| S9 | ROAS CI consistency | invariants × 10 |
| S10 | Determinism | 1 test |
| S11 | Engine identity vs manual | invariants × 5 |
| S12 | Forecast horizon decoupling | parametric × 5 |
| S13 | Money-mode coverage | 2 tests |
| S14 | Graceful errors | 3 tests |

Plus 30 edge cases в `tools/test_scenario_edge_cases.py` (8 batches A-H).

---

## How to add new invariant

1. Append к этому doc в same format (statement / rationale / test).
2. Add property test с pytest.parametrize for ≥10 seeds.
3. Update summary table.
4. Run `pytest tools/test_scenario_invariants.py -n auto`.
