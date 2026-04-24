# Math Audit ↔ Hill Fix Coordination

**Date:** 2026-04-25
**Parent audit:** `docs/MATH_AUDIT_v1_1.md`
**Hill fix task:** `~/.claude/projects/D--Docs-Aurora-Ai/memory/project_econometrica_hill_normalization_root_fix.md`

---

## Purpose

Audit identified that Hill normalization refactor (P0-1) is **the pivot event** for multiple findings. This doc pins:

1. Which audit tests serve as **Hill-fix acceptance criteria**
2. Which audit findings **auto-resolve** when Hill fix lands
3. Which audit findings are **independent** and require separate fix tasks
4. Post-fix validation tests that should be added

---

## 1. Audit tests as Hill-fix acceptance criteria

From `tools/test_math_correctness.py`, these tests MUST still pass after Hill fix:

### Pure formula correctness (should pass at all times)
- `test_hill_bounds` — sat(0)=0, sat(∞)→1, sat(γ)=0.5
- `test_hill_monotonic_increasing` — 200 seeded random cases
- `test_hill_stability_large_x` — no overflow
- All adstock tests (geometric + Weibull)
- All y normalization roundtrip
- All diagnostics (R², MAPE, RMSE)
- `test_marginal_roi_matches_numerical_derivative`
- `test_robyn_style_hill_positive_domain` — **this explicitly tests the target fix formula**
- `test_js_style_hill_semantics` — **JS/Python parity test**, JS is already spend/mean; post-fix Python matches
- `test_column_role_kpi_detection`
- MQS bounds tests
- Prior predictive structural tests (gamma/alpha coverage)

### Tests that MUST fail after fix (explicit migration tripwires)

These tests are DOCUMENTED BUG SIGNATURES that pin current broken behavior:

#### `test_p0_2_half_data_silent_drop`
- **Current behavior:** z-scored N(0,1) spend + clip(·, 0) drops ~50% of periods
- **Post-fix behavior:** spend/mean always ≥ 0, clip never fires, 0% dropped
- **Migration:** test will fail after fix — update expected fraction to ~0% OR
  replace with `test_p0_2_fixed_clip_is_no_op` that asserts `sum(spend_clipped == 0) == sum(spend == 0)`

#### `test_p0_7_training_reconstruction_hill_divergence`
- **Current behavior:** training Hill uses raw gamma; reconstruction uses `gamma × x.max()` → diverge > 0.01
- **Post-fix behavior (P0-7 fixed separately — NOT by Hill fix alone):** both use raw gamma → diverge ≤ 1e-10
- **Migration:** after P0-7 fix, test will fail — invert assertion to `assert_close(training, reconstruction, rtol=1e-6)`
- **IMPORTANT:** P0-7 fix is INDEPENDENT of Hill fix. Hill fix could land without P0-7 fix and this test still passes (divergence remains). But Hill fix is RECOMMENDED to be bundled with P0-7 fix.

#### `test_p0_5_6_optimizer_vs_training_hill_divergence`
- **Current behavior:** optimizer uses raw spend + gamma × current_spend; training uses z-score + raw gamma
- **Post-fix behavior (P0-5/6 fixed separately):** optimizer uses spend/mean + raw gamma matching training
- **Migration:** after P0-5/6 fix, test will fail — invert to parity assertion
- **IMPORTANT:** P0-5/6 fix is INDEPENDENT. Optimizer could be left broken even after Hill fix (though bundle recommended).

---

## 2. Audit findings that auto-resolve with Hill fix

These findings **silently resolve** when normalization changes from z-score to spend/mean. No separate fix task needed — but regression tests must be updated:

### P0-1 Media normalization
- **Primary defect** — Hill fix directly resolves
- **Test updates:** remove z-score-based `x_safe = max(x, 0)` comments, add spend/mean documentation

### P0-2 Negative-z clip drops half of data
- **Consequence of z-score** — post-fix, spend/mean ≥ 0 always, clip becomes no-op
- **Test update:** flip `test_p0_2_half_data_silent_drop` assertion as above

### P0-9 JS/Python Hill drift
- **JS already uses spend/mean** (Robyn-style)
- **Post-fix:** Python joins same formula → 4-way alignment (training, scenario, optimizer, JS)
- **Test:** `test_js_style_hill_semantics` already PASSES — simply confirms post-fix consistency

---

## 3. Audit findings NOT resolved by Hill fix alone

These require **separate fix tasks**:

### P0-3 Decomposer uses |β|/Σ|β| proportional distribution
- **Independent of Hill** — decomposer has its own broken logic
- **Fix task:** `NEW — project_econometrica_decomposer_rewrite`
- **Acceptance criteria:**
  - New tests `test_decomposer_uses_saturation` and `test_decomposer_per_period_matches_saturated_contribution`
  - Live-test: Kagocel decomposition shows non-trivial contribution curvature (not just proportional to spend sum)

### P0-4 Decomposer baseline magic-0.3
- **Bundled with P0-3** (same task)
- **Acceptance:** baseline = `intercept × y_std + y_mean + control_effects × y_std` on original scale

### P0-5/6 Optimizer Hill scale mismatch
- **Independent** — optimizer has own scale bug
- **Fix task:** `NEW — project_econometrica_optimizer_rescale`
- **Acceptance criteria:**
  - `test_p0_5_6_optimizer_vs_training_hill_divergence` inverted to parity
  - Live-test: optimizer at +100% budget vs -50% budget shows ≥ 5% delta lift
  - Optimizer non-trivial allocation (not uniform)

### P0-7 Training-reconstruction Hill drift
- **Independent** — reconstruction formula bug
- **Fix task:** `NEW — project_econometrica_reconstruction_fix`
- **Acceptance criteria:**
  - `test_p0_7_training_reconstruction_hill_divergence` inverted
  - R²/MAPE reported in diagnostics now reflect trained model (not alternate formula)

### P0-10 Per-period contribution proportional to raw spend
- **Bundled with P0-3** (same decomposer task)

### P0-11 Mixed-units constraint in optimizer
- **Lighter fix** — validator UX + optimizer guard
- **Could be bundled** with P0-5/6 task OR separate if preferred

---

## 4. Post-fix validation tests (to add to `test_math_correctness.py`)

After all P0 fixes land, add these tests (currently deferred):

### 4.1 Synthetic MCMC parameter recovery
```python
def test_synthetic_mcmc_param_recovery():
    """Generate data from known β/α/γ, fit model, assert posterior 90% CI
    covers true params."""
    # Single-channel, no controls, N=52 weeks
    # Fix seed, run NUMPYRO chains=2 draws=500 tune=500
    # Extract posterior α, γ, β — check CI coverage
```

### 4.2 Posterior predictive coverage
```python
def test_posterior_predictive_coverage():
    """Fit model on synthetic data, generate PPC samples, verify 90% CI
    covers observed y at ≥90% rate."""
    # Use arviz.loo or manual coverage computation
```

### 4.3 Scenario sensitivity (end-to-end)
```python
def test_scenario_budget_sensitivity_post_fix():
    """After Hill fix + optimizer fix: scenario at ±50% budget must show
    ≥ 5% delta KPI. Pre-fix: <0.1% delta (live-test 2026-04-24)."""
    # Run full pipeline on fixture, change budget, assert delta
```

### 4.4 Optimizer allocates non-trivially
```python
def test_optimizer_finds_nontrivial_allocation():
    """Optimizer on Kagocel-like fixture should NOT return uniform
    allocation — must prefer high-mROAS channels."""
```

### 4.5 What-if slider delta sensibility
```python
def test_what_if_delta_units():
    """JS what-if formula (replicated in Python) on ±50% spend change
    should return delta KPI of magnitude >1%."""
```

### 4.6 Decomposer energy conservation
```python
def test_decomposer_energy_conservation():
    """sum(channel contributions) + baseline ≈ total predicted (within 0.5%).
    After P0-3 fix, should hold; pre-fix it's unclear what's being summed."""
```

### 4.7 End-to-end reference check vs PyMC-Marketing
```python
def test_end_to_end_vs_pymc_marketing():
    """Fit same data with PyMC-Marketing MMM class + our modeler.
    Posterior means should agree within 10-20% (not exact due to priors)."""
    # Optional — heavy, requires pymc-marketing install
```

---

## 5. Suggested fix task sequencing

**Minimal ship path (to v1.0.13 commercial):**

1. **Hill fix** (`project_econometrica_hill_normalization_root_fix`) — blocks everything else
   - Duration: 7-12h (as estimated)
   - Resolves: P0-1, P0-2, P0-9 (auto)
   - Acceptance: all current `test_math_correctness.py` PASS except P0-2 test (which is updated in same PR)

2. **Bundle: Decomposer + Reconstruction + Optimizer rewrite** — same MMM-math session
   - Duration: 6-10h
   - Resolves: P0-3, P0-4, P0-5, P0-6, P0-7, P0-10
   - Acceptance:
     - All `test_math_correctness.py` tests updated (inversions applied)
     - New post-fix validation tests (Section 4) added and PASS
     - Live-test Kagocel shows sensible sensitivity

3. **P0-11 validator UX fix** — lightweight
   - Duration: 1-2h
   - Acceptance: validator rejects/warns on mixed-units budget

4. **(Optional) P1 bundle: scenario adstock + incremental ROAS**
   - Duration: 3-5h
   - Can ship as v1.0.13.1 if tight deadline

**Total pre-ship:** 14-24h across 2-3 dedicated sessions.

**Ship gate:** all P0 resolved, all audit tests PASS with expected-post-fix assertions, live Kagocel regenerate shows curvature in response curves + ≥ 5% scenario spread + non-trivial optimizer allocation.

---

## 6. Coordination notes

- Audit work is **done** — no further audit deliverables pending
- Fix implementation is **separate work** — not in audit scope
- This coordination doc is the handoff artifact; Hill-fix task owner consults it before starting
- Regression safety: `test_math_correctness.py` already committed; each fix task updates tests in SAME PR as fix (not separate)
- Memory updates: audit findings create NEW tasks (listed above); Hill fix task unchanged

**Audit stable baseline:** HEAD `12addcf` (after audit R3 commit). Safety tag: `v1.0.12-pre-math-audit`.
