# Optimizer Invariants Registry — formal spec

**Branch:** `math-fix-v1.0.13`
**Established:** 2026-05-03 (Phase 1+5 of optimizer audit)
**Plan ref:** `C:\Users\ackol\.claude\plans\zazzy-tumbling-kettle.md`
**Property-based tests:** `tools/test_optimizer_invariants.py`
**Math refs:**
- `docs/MATH_AUDIT_v1_3_PHASE_0_1.md` — mROAS chain rule
- `docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md` — Option C lock + L1

---

## Purpose

Capture invariants that the optimizer (`engines/optimizer.py`) must guarantee
across all production inputs. Each invariant has:
- formal mathematical statement
- rationale (why it must hold)
- property-based test reference
- known gaps / deferred work

**Use this doc as the canonical spec.** Any optimizer refactor must verify the
property-based tests still pass; any new invariant claim must be added here AND
covered by a property test.

---

## Invariants

### I1 — Monotonicity (paired widening)

**Statement:** For bound configurations `B_wide ⊇ B_narrow` over the same pickle:
```
optimal_response(B_wide) ≥ optimal_response(B_narrow) - tolerance
```

**Rationale:** Mathematical fact: `max_{x ∈ B_wide} f(x) ≥ max_{x ∈ B_narrow} f(x)`
when `B_narrow ⊆ B_wide`. Optimizer enforces via **default_anchor mechanism**
(passes 7-17, lines 708-918): if user widens past defaults (20/200), an
SLSQP solution computed in default-bounds is added directly as a candidate,
flooring the result.

**Test:** `test_I1_monotonicity_wider_bounds_dominate` × 20 seeds.

**Tolerance:** ±0.5pp on `expected_lift_pct` (numerical SLSQP slack).

---

### I2 — Conservation (sum equals target)

**Statement:**
```
| Σᵢ optimal_money[i] - money_target |  /  money_target  ≤  0.5%
```
where `money_target = config.total_budget_money` если задан, иначе
`Σᵢ current_money[i]`.

**Rationale:** SLSQP equality constraint `Σ x = money_target` (optimizer.py:635).
Tolerance accounts for `round(opt × uc, 0)` truncation on rubli scale.

**Test:** `test_I2_conservation_no_override` (20 seeds) +
`test_I2_conservation_with_override` (20 seeds, target = 1.5× current).

---

### I3 — Bounds satisfaction (per channel)

**Statement:** For each channel `i` with non-zero current spend:
```
current_money[i] × min_pct  ≤  optimal_money[i]  ≤  current_money[i] × max_pct
                                                                (within 0.5%)
```
Per-channel overrides take precedence (см. I7).

**Rationale:** SLSQP `bounds=` parameter (optimizer.py:608, 884). Resolved per
3-level precedence by `resolve_channel_bounds` (utils/optimizer_constraints.py).

**Test:** `test_I3_bounds_satisfaction` × 20 seeds.

---

### I4 — Backward compat: analyst-mode echo + determinism

**Statement:** When `forecast_periods` is None or absent:
1. `result.planning_mode == False`
2. `result.train_n_periods == result.forecast_n_periods == len(df)`
3. Three sequential calls produce **byte-identical** `optimal_spend_money` per channel
4. Hill-of-mean math preserved (no regression на v1.1.0 customer pickles)

**Rationale:** Phase 2 introduced Option C (per-period sum-of-Hills) только в planning
mode. Analyst mode preserves pre-Phase-2 Hill-of-mean approximation для byte-exact
backward compat — see `MATH_AUDIT_v2_0_FORECAST_HORIZON.md §2bis`.

**Test:** `test_I4_analyst_mode_echo_and_determinism`.

---

### I5 — Lift sign anchor floor (corollary of I1)

**Statement (anchor floor):** For any user bounds `(min_pct, max_pct)` widened past
defaults `(20%, 200%)`:
```
lift_pct(user_bounds) ≥ lift_pct(default 20/200) - 0.5pp
```

**Rationale:** Direct consequence of I1, via lift_pct rather than raw objective.
Anchor mechanism enforces this floor.

**Test:** `test_I5_lift_floor_at_default_anchor` × 5 seeds × 4 widenings.

---

#### ✅ I5b — Chain transitive monotonicity (FIXED 2026-05-03)

**Stronger property (now guaranteed):**
```
For chain B₁ ⊆ B₂ ⊆ ... ⊆ Bₙ with cumulative anchor seeding:
  lift_pct(B_{i+1}) ≥ lift_pct(B_i) - tolerance  ∀ i
```

**Status:** ✅ **F1 fix shipped 2026-05-03.** Cumulative anchor seeding implemented
в `optimizer.py` (search comment «F1 fix (2026-05-03 — Phase 5 follow-up)»).

**Mechanism:**
- `optimize()` accepts optional `prev_optimal: list[float]` config field
  (alias `prev_optimal_money`) — last call's `optimal_spend_money` per channel.
- When provided AND feasible в current bounds (per-channel + sum within 1%),
  added as **direct candidate** (no SLSQP rerun, just objective eval).
- `min(candidates).fun` selection → если prev's objective ≤ current run's best,
  prev wins. Floor preserved transitively.

**UI contract:** frontend store retains `result.optimal_spend_money` from prior
optimize call; passes via `config.prev_optimal` when user widens bounds. Если
user narrows OR changes pickle/budget — skip (prev infeasible, silent skip with
log info message).

**Test:** `test_I5_chain_monotonic_with_cumulative_anchor` × 5 seeds — all pass
(was xfail для 4 of 5 без F1, all pass с F1).

---

### I6 — mROAS chain rule consistency

**Statement:** For all parameter combinations in domain:
```
| _compute_mroas_money(...)  -  finite_difference_KPI(s±ε) |
                                                            < 5×10⁻³  relative
```

where `_compute_mroas_money` returns the closed-form chain rule:
```
mROAS = β · hill'(x_norm) · adstock_factor · y_std / mean / unit_cost
```

**Math derivation:** `MATH_AUDIT_v1_3_PHASE_0_1.md §3` (closed-form chain rule)
+ `§4` (adstock factor exact form for geometric).

**Rationale:** mROAS is the partial derivative of KPI(money) w.r.t. spend(money).
Closed form must agree с numerical derivative to relative ~10⁻³ precision.

**Test:** `test_I6_mroas_finite_difference` × 50 random param combos covering
α ∈ [1, 3], γ ∈ [0.3, 0.8], β ∈ [0.02, 0.15], decay ∈ [0.1, 0.7],
unit_cost ∈ {1.0, [50, 500_000]}.

---

### I7 — Per-channel constraint precedence

**Statement:** 3-level precedence:
```
per-channel  >  per-group (brand/perf)  >  global
```

For channel `c` with current_money `m`:
```
if c in channel_min_pct:        bounds.lo = m × channel_min_pct[c]
elif category(c) == 'brand'  & brand_min_pct  set:  bounds.lo = m × brand_min_pct
elif category(c) == 'performance' & perf_min_pct set: bounds.lo = m × perf_min_pct
else:                                                 bounds.lo = m × global_min_pct
```
Same for `max`. Mixed/unknown categories → fall back к global.

**Rationale:** Customer mental model — per-channel locks override broader rules.
Implemented в `utils/optimizer_constraints.py:resolve_channel_bounds`.

**Test (E2E):** `test_I7_per_channel_overrides_global` × 10 seeds.
**Test (unit):** `test_optimizer_per_group_constraints.py` — 30 cases.

---

### I8 — Option C identity + scenario alignment

**Statement (identity):** `evaluate_flat_allocation_response(...)` (in `utils/forecasting.py`)
returns numerically identical result к the manual per-period `Σ β·hill(x_norm_t)`
loop matching `scenario.py:167-186` semantics.
```
| evaluate_flat - manual_sum_of_hills |  /  manual  ≤  10⁻⁹
```

**Statement (E2E consistency):** Optimizer planning-mode media response (best
objective × y_std) ≈ scenario.predict_scenario incremental KPI when scenario
runs the optimizer's optimal allocation as flat media plan.
```
| optimizer_media_kpi - scenario_incremental_kpi |  /  optimizer_media_kpi  ≤  1%
```

**Rationale:** Aurora's «3-way alignment» — optimizer ↔ scenario ↔ decomposer
all use sum-of-Hill per-period semantics в planning mode (M9 finding,
`MATH_AUDIT_v2_0_FORECAST_HORIZON.md §2bis`). Optimizer was the outlier до Phase 2;
Option C restored alignment.

**Test (identity):** `test_I8_option_c_per_period_identity`.
**Test (E2E):** `test_I8_planning_optimizer_scenario_consistency` × 5 seeds.

---

## Summary table

| ID | Property | Test | Status |
|---|---|---|---|
| I1 | Monotonicity (paired) | `test_I1_…` × 20 | ✅ |
| I2 | Conservation | `test_I2_…` × 20 + override × 20 | ✅ |
| I3 | Bounds satisfaction | `test_I3_…` × 20 | ✅ |
| I4 | Backward compat + determinism | `test_I4_…` | ✅ |
| I5a | Anchor floor | `test_I5_lift_floor_at_default_anchor` × 5×4 | ✅ |
| I5b | Chain transitive monotonicity | `test_I5_chain_monotonic_with_cumulative_anchor` × 5 | ✅ (F1 fix 2026-05-03) |
| I6 | mROAS chain rule | `test_I6_…` × 50 | ✅ |
| I7 | Constraint precedence | `test_I7_…` × 10 + 30 unit | ✅ |
| I8 | Option C identity + E2E | `test_I8_…` + × 5 | ✅ |

---

## How to add a new invariant

1. Append к this doc in same format (statement / rationale / test).
2. Add property-based test в `tools/test_optimizer_invariants.py` с pytest.parametrize
   for ≥10 seeds (or analytic param combos for math invariants).
3. Add inline `# invariant: see docs/OPTIMIZER_INVARIANTS_REGISTRY.md In` annotation
   в `engines/optimizer.py` at the implementation site.
4. Update summary table.
5. Run full suite: `pytest tools/ -n auto`.
