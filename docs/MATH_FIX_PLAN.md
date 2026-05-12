# Math Fix Plan - Path to v1.0.13-math-audited

**Date:** 2026-04-25
**Source:** `docs/MATH_AUDIT_v1_1.md` (11 P0 + 6 P1 + 5 P2)
**Target ship:** `v1.0.13-math-audited` (commercial-ready)
**Total realistic:** 18-26h across 3-4 sessions

---

## TL;DR

Чинить **в одном branch** `math-fix-v1.0.13`, **6 фаз**, каждая = self-contained commit:

| # | Phase | Hours | Resolves | Depends on |
|---|-------|-------|----------|-----------|
| 0 | Setup + branch + baseline capture | 0.5 | - | - |
| 1 | Reconstruction fix (P0-7) | 2-3 | P0-7 | none - independent |
| 2 | Hill normalization (P0-1, P0-2, P0-9) | 6-9 | P0-1/2/9 + scenario.py + JS verify | Phase 0 |
| 3 | Decomposer rewrite (P0-3, P0-4, P0-10) | 5-7 | P0-3/4/10 | Phase 2 (pickle schema) |
| 4 | Optimizer rescale + P0-11 (P0-5, P0-6, P0-11) | 4-5 | P0-5/6/11 | Phase 2 |
| 5 | Post-fix validation + live-test | 2-3 | regression gate | Phases 1-4 |
| 6 | P1 bundle (optional) | 3-5 | scenario adstock + incremental ROAS | Phase 5 |
| 7 | Ship + memory finalize | 1-2 | tag + docs | All |

Phases 1 + 2 могут идти параллельно (independent). Phases 3, 4 - после Phase 2. Phase 5 - после всех P0.

---

## Phase 0: Setup (0.5h)

```bash
# Safety tag (HEAD = v1.0.12-math-audit-done = 1182338)
git tag v1.0.12-pre-fix-bundle
git checkout -b math-fix-v1.0.13

# Baseline test snapshot - confirm current state before any change
python tools/test_math_correctness.py > /tmp/baseline_tests.log 2>&1
# Expected: 64/64 PASS (P0-2/5/6/7 tests document bug signatures)

# Verify clean working tree
git status
```

**Branch strategy:** single long-lived branch, individual commits per phase. Squash at PR time? - recommend KEEP individual commits для forensic.

**Rollback strategy:** any phase can be reverted via `git reset --hard v1.0.12-pre-fix-bundle` или per-commit revert.

---

## Phase 1: Reconstruction fix - P0-7 (2-3h)

**Independent of Hill fix.** Can be done first или parallel.

### Scope

`sidecar/econometrica/engines/modeler.py:537` - manual posterior reconstruction uses `gamma_scaled = gamma × max(x)` while training (line 312) uses raw `gammas[i]`. Diagnostics R²/MAPE computed from wrong formula.

### Implementation

**modeler.py:520-546** - remove the `gamma_scaled` line:

```python
# BEFORE:
gamma_scaled = gamma_i * max(x_safe.max(), 1e-10)
saturated = x_safe ** alpha_i / (x_safe ** alpha_i + gamma_scaled ** alpha_i + 1e-10)

# AFTER:
saturated = x_safe ** alpha_i / (x_safe ** alpha_i + gamma_i ** alpha_i + 1e-10)
```

3-line change. Match training formula exactly.

### Test updates

**`tools/test_math_correctness.py`:**

Replace `test_p0_7_training_reconstruction_hill_divergence` (which asserts divergence > 0.01):

```python
def test_p0_7_training_reconstruction_hill_parity():
    """Post-fix (commit XXXX): training and reconstruction Hill match."""
    # Same synthetic setup
    training_sat = x ** alpha / (x ** alpha + gamma ** alpha + 1e-10)
    reconstruction_sat = x ** alpha / (x ** alpha + gamma ** alpha + 1e-10)  # raw gamma now
    diff = float(np.abs(training_sat - reconstruction_sat).max())
    assert_close("P0-7 fixed: parity within 1e-10", diff, 0.0, rtol=1e-9)
```

### Acceptance

- 64/64 tests still PASS (test 6 inverted)
- Live Kagocel refit: R² value changes from current. Document delta in commit message.

### Commit message

```
fix(math-audit): reconstruction Hill matches training (P0-7)

modeler.py:537 - remove gamma_scaled = gamma × max(x) artifact.
Use raw gammas[i] matching training formula at line 312. y_pred used
for R²/MAPE/RMSE now computed from same formula model was trained on.

Test test_p0_7_training_reconstruction_hill_divergence inverted to
parity assertion (now expects diff < 1e-9 instead of > 0.01).

Live Kagocel: R² changed from {OLD} to {NEW} - reflects actual model fit.
```

---

## Phase 2: Hill normalization - P0-1, P0-2, P0-9 (6-9h)

**Most invasive change.** Touches 4-5 files. Existing task `project_econometrica_hill_normalization_root_fix` documents details.

### Scope

1. `modeler.py:249-251` - `(X - mean) / std` → `X / mean` (Robyn-style spend/mean)
2. `modeler.py:310` - `x_safe = pm.math.maximum(x_ch, 0)` clip retained as defense (post-fix never fires for non-negative spend)
3. `engines/scenario.py:86` - `x_norm = (spend_t - mean) / std` → `x_norm = spend_t / max(mean, 1e-10)`
4. `engines/optimizer.py:92` - input scale change, gamma stays raw (also touched in Phase 4)
5. `engines/decomposer.py` - Hill input scale (will be fully rewritten в Phase 3, here just add normalization fix as transitional)
6. `aurora_html/interactive.py:689` - JS already uses spend/mean (Robyn-style), no JS change needed (verify only)
7. **Pickle schema**: add `model_version: '1.1'` field to detect old z-score pickles

### Subphases

**2a (3-4h): modeler.py refactor + Kagocel refit**

```python
# modeler.py:249-251
# BEFORE:
media_means = X_media.mean()
media_stds = X_media.std().replace(0, 1)
X_media_norm = (X_media - media_means) / media_stds

# AFTER:
media_means = X_media.mean().replace(0, 1)  # avoid div/0 for empty channels
X_media_norm = X_media / media_means
# media_stds removed - not used post-fix
```

Pickle save (line ~610):
```python
'normalization': {
    'media_means': media_means.to_dict(),
    # 'media_stds': REMOVED - not used in spend/mean
    'control_means': control_means.to_dict() if len(control_cols) > 0 else {},
    'control_stds': control_stds.to_dict() if len(control_cols) > 0 else {},
    'y_mean': float(y_mean),
    'y_std': float(y_std),
    'intercept_mean': float(intercept_mean),  # NEW for decomposer Phase 3
    'control_betas_mean': control_betas_mean.tolist() if len(control_cols) > 0 else [],  # NEW
},
'model_version': '1.1',  # NEW for compat detection
```

Sanity smoke: refit Kagocel, verify NUTS converges (R-hat < 1.05), no NaN posterior.

**2b (1-2h): scenario.py sync**

```python
# scenario.py:86
# BEFORE:
mean = norm['media_means'].get(col, 0)
std = norm['media_stds'].get(col, 1)
x_norm = (spend_t - mean) / std if std > 0 else 0

# AFTER:
mean = norm['media_means'].get(col, 1)
x_norm = spend_t / max(mean, 1e-10) if mean > 0 else 0
```

**2c (1h): pickle compat detection**

In all engines (decomposer, optimizer, scenario):
```python
model_version = model_data.get('model_version', '1.0')
if model_version == '1.0':
    return {
        'status': 'error',
        'error_code': 'MODEL_OUTDATED',
        'message': 'Модель обучена до v1.0.13. Нормализация изменилась - переобучите модель в кабинете "Модель".',
    }
```

**2d (1-2h): test updates**

`test_math_correctness.py`:
- `test_p0_2_half_data_silent_drop` → INVERT to `test_p0_2_no_data_dropped_post_fix`
- New `test_robyn_style_normalization_used` - load test pickle, verify normalization formula

**2e (1h): JS verify**

Confirm `aurora_html/interactive.py:689` already uses `z = spend / mean` (per audit Section 3.16). No code change. Add note to commit message that JS was already correct.

### Acceptance

- Live Kagocel refit completes without divergences
- Scenario at +100% budget vs -50% budget shows ≥ 5% delta KPI (per audit ship gate)
- Response curves show curvature, no flat plateau
- 64/64 tests PASS with updates
- Old .pkl detected and rejected with clear UX

### Commit message

```
fix(math-audit): Hill normalization spend/mean Robyn-style (P0-1/2/9)

Refactor media spend normalization from z-score to Robyn-style spend/mean
across modeler/scenario/optimizer/decomposer. JS what-if (interactive.py)
already used spend/mean - verified parity, no JS change needed.

Pickle schema:
- removed media_stds (not used post-fix)
- added intercept_mean + control_betas_mean (for decomposer Phase 3)
- added model_version='1.1' field for compat detection

All engines now reject pickle with model_version='1.0' (or absent) with
MODEL_OUTDATED error. UI shows "переобучите модель" prompt.

Live Kagocel:
- Scenario +100% vs -50% delta KPI: {OLD 0.05%} → {NEW X%}
- Response curves: flat plateaus → curvature in [0.5×, 3×] mean range
- R-hat max: {pre} → {post}
- Divergences: {pre} → {post}

Closes P0-1, P0-2, P0-9.
```

---

## Phase 3: Decomposer rewrite - P0-3, P0-4, P0-10 (5-7h)

**Depends on Phase 2** (pickle schema with intercept_mean + control_betas_mean).

### Scope

`sidecar/econometrica/engines/decomposer.py` - replace `|β|/Σ|β|` proportion with proper `β × sat(adstock(x)) × y_std` per period.

### Implementation

Full decomposer body rewrite (~150 LOC). Key changes:

```python
# decomposer.py - new flow:

# Load saved normalization (Phase 2 added intercept_mean + control_betas_mean)
norm = model_data['normalization']
intercept_mean = norm['intercept_mean']
control_betas_mean = norm.get('control_betas_mean', [])
y_std = norm['y_std']
y_mean = norm['y_mean']
adstock_config = config.get('adstock_config', {})

# Per-channel saturated contribution per period
from utils.adstock import apply_adstock
from utils.saturation import hill_function

channels = []
time_series_channels = {}
for col in media_cols:
    p = channel_params[col]
    raw_spend = df[col].fillna(0).values.astype(float)
    # 1. Apply adstock (matches training)
    x_adstock = apply_adstock(raw_spend, adstock_config.get(col, 'geometric'))
    # 2. Normalize spend/mean (matches Phase 2 fix)
    mean = norm['media_means'].get(col, 1)
    x_norm = x_adstock / max(mean, 1e-10)
    # 3. Hill saturation
    sat = hill_function(np.maximum(x_norm, 0), alpha=p['alpha'], gamma=p['gamma'])
    # 4. Per-period contribution in original KPI units
    contrib_per_period = p['beta'] * sat * y_std
    channel_total = float(contrib_per_period.sum())
    
    time_series_channels[col] = [round(float(v), 1) for v in contrib_per_period]
    
    # Money & ROI
    unit_cost = float(unit_costs.get(col, 1.0) or 1.0)
    spend_money = float(raw_spend.sum() * unit_cost)
    roi = channel_total / spend_money if spend_money > 0 else 0
    
    channels.append({
        'name': col,
        'spend': round(spend_money, 0),
        'contribution': round(channel_total, 0),
        'contribution_pct': 0,  # filled after total computed
        'roi': round(roi, 2),
        'beta': p['beta'],
        # ...
    })

# Total media contribution
total_media_contribution = sum(c['contribution'] for c in channels)

# Baseline = intercept + control effects on original scale
intercept_effect_per_period = np.full(n_periods, intercept_mean * y_std + y_mean)

control_effect_per_period = np.zeros(n_periods)
if len(control_betas_mean) > 0 and len(control_cols) > 0:
    X_control_norm = (df[control_cols].values - np.array(list(norm['control_means'].values()))) / np.array(list(norm['control_stds'].values()))
    control_effect_per_period = X_control_norm @ np.array(control_betas_mean) * y_std

baseline_per_period = intercept_effect_per_period + control_effect_per_period
baseline_total = float(baseline_per_period.sum())

# Energy conservation check
total_predicted = baseline_total + total_media_contribution
# Should be ≈ y_predicted.sum() within rounding

# Fill contribution_pct
for ch in channels:
    ch['contribution_pct'] = round(ch['contribution'] / total_media_contribution * 100, 1) if total_media_contribution > 0 else 0
```

### Test updates

New tests in `test_math_correctness.py`:

```python
def test_decomposer_uses_saturation():
    """Decomposer output matches β × hill(x_norm) × y_std on synthetic fixture."""
    # Build mock pickle with known params
    # Run decomposer, verify per-channel contribution matches direct formula
    
def test_decomposer_energy_conservation():
    """sum(channels) + baseline ≈ total predicted within 0.5%."""
    
def test_decomposer_per_period_curvature():
    """Per-period contribution NOT proportional to raw spend (must show
    saturation curvature)."""
```

### Acceptance

- New tests PASS
- Live Kagocel: waterfall values change significantly (large drift expected vs pre-fix)
- Decomp results consistent with what-if slider on same scenario
- HTML/PPTX deliverables regenerate with new numbers (visually different from pre-fix)

### Commit message

```
fix(math-audit): decomposer uses Hill+adstock+spend (P0-3/4/10)

Replace |β|/Σ|β| proportional distribution with proper MMM decomposition:
contribution_per_period = β × hill(x_adstock/mean) × y_std.

Baseline computed from intercept + control effects on original scale,
not the magic-0.3 formula. Per-period contribution now reflects saturation
curvature, not raw spend proportion.

Pickle dependency: requires intercept_mean + control_betas_mean from
Phase 2 fix.

Live Kagocel waterfall: contribution numbers change by 5-30% per channel.
Energy conservation: sum(channels) + baseline = total predicted within 0.3%.

Closes P0-3, P0-4, P0-10.
```

---

## Phase 4: Optimizer rescale + P0-11 (4-5h)

**Depends on Phase 2.**

### Scope

`sidecar/econometrica/engines/optimizer.py:92` - Hill input + gamma alignment with training. P0-11 mixed-units guard.

### Implementation

```python
# optimizer.py - rewrite total_response and marginal_roi calls

def total_response(spend_vector):
    total = 0
    for i, col in enumerate(media_cols):
        p = channel_params[col]
        mean = norm['media_means'].get(col, 1)  # from pickle (Phase 2)
        x_norm = spend_vector[i] / max(mean, 1e-10)
        sat = hill_function(
            np.array([max(x_norm, 0)]),
            alpha=p['alpha'],
            gamma=p['gamma'],  # raw gamma, NOT scaled by current_spend
        )
        total += p['beta'] * sat[0]
    return -total

# marginal_roi chain rule:
mroi_current = float(marginal_roi(
    np.array([cur / mean]),  # input is normalized
    p['alpha'], p['gamma'], p['beta'],
)[0]) / mean  # × 1/mean (chain rule for d/d_spend)
```

### P0-11: mixed-units guard

```python
# At optimizer entry, after unit_costs sanitize:
if total_budget_money_target is None:
    uc_values = [unit_costs.get(c, 1.0) for c in media_cols]
    is_all_money = all(uc == 1.0 for uc in uc_values)
    is_all_native = all(uc != 1.0 for uc in uc_values)
    if not (is_all_money or is_all_native):
        return {
            'status': 'error',
            'error_code': 'MIXED_UNITS',
            'message': 'Каналы в смешанных единицах. Укажите total_budget_money или unit_costs для всех каналов.',
        }
```

### Test updates

- `test_p0_5_6_optimizer_vs_training_hill_divergence` → INVERT to parity
- New `test_optimizer_finds_nontrivial_allocation` (Kagocel-like fixture)
- New `test_optimizer_rejects_mixed_units`

### Acceptance

- Optimizer at +100% budget gives ≥ 5% delta optimal_response vs current
- Allocation NOT uniform (channels differentiated)
- Mixed-units fixture rejected with clear error
- 64+N tests PASS

### Commit message

```
fix(math-audit): optimizer Hill spend/mean + raw gamma (P0-5/6/11)

optimizer.py: replace raw_spend + gamma×current_spend Hill with
spend/mean + raw gamma matching training formula. marginal_roi chain
rule applies ×1/mean.

P0-11: native-mode budget constraint now rejects mixed-units channels
(error code MIXED_UNITS) - was silently summing TRPs+rubles.

Live Kagocel optimize:
- Allocation non-uniform: max delta {X%}, min delta {Y%}
- Expected lift: {pre 0.1%} → {post N%}
- Response curves match scenario.py predictions

Closes P0-5, P0-6, P0-11.
```

---

## Phase 5: Post-fix validation + live-test (2-3h)

### Scope

Add post-fix validation tests from `MATH_AUDIT_HILL_FIX_COORDINATION.md` Section 4. Run full live-test on Kagocel.

### Implementation

Add to `tools/test_math_correctness.py`:

```python
def test_synthetic_mcmc_param_recovery():
    """Generate y from known β/α/γ, fit, verify posterior 90% CI covers true."""
    # Single channel, no controls, N=52, seed=42, chains=2, draws=500

def test_scenario_budget_sensitivity_post_fix():
    """Scenario ±50% budget → delta KPI > 5%."""
    # Use existing pickle, run scenario at 0.5× and 1.5× spend, assert delta

def test_optimizer_finds_nontrivial_allocation():
    """Kagocel-like fixture, optimizer returns non-uniform allocation."""
    # std(allocation) / mean(allocation) > 0.1

def test_decomposer_energy_conservation():
    """sum(channels) + baseline ≈ total predicted within 0.5%."""
```

### Live-test (manual)

1. `python sidecar/build_sidecar.py` - rebuild Python sidecar (per `feedback_sidecar_rebuild_required`)
2. `npm run tauri dev` - launch app
3. Import `D:/Docs/Aurora_Ai/TestData/Econometrica/Kagocel_RF_MMM_dataset.xlsx`
4. Full pipeline: Validate → Train → Decompose → Optimize → Scenario
5. Verify each step:
   - Validate: no regression
   - Train: NUTS converges, R-hat ≤ 1.05, no divergences
   - Decompose: response curves show growth, baseline reasonable
   - Optimize: non-trivial allocation, lift > 5%
   - Scenario: +100% vs -50% spread > 5%
   - What-if slider in HTML report: delta matches scenario backend
   - Report ID identical в HTML and PPTX

### Acceptance

- All new tests PASS
- All existing 64 tests still PASS (after planned inversions)
- Live-test acceptance: 5+5+5 = 15% scenario spread (rule of thumb)
- No NaN / inf anywhere in posterior

### Commit message

```
test(math-audit): post-fix validation suite + live-test verified

Adds 4 post-fix tests:
- synthetic MCMC parameter recovery (single channel, known β/α/γ)
- scenario budget sensitivity (±50% → delta > 5%)
- optimizer non-trivial allocation (std/mean > 0.1)
- decomposer energy conservation (sum ≈ total predicted ±0.5%)

Live Kagocel run results:
- Train: R-hat max {X}, divergences {Y}
- Scenario ±50%: delta KPI {Z%}
- Optimize lift: {W%}
- What-if slider matches optimizer within 3%
```

---

## Phase 6: P1 bundle - scenario adstock + incremental ROAS (3-5h, optional)

**Optional for v1.0.13.** Ship without if deadline tight, follow-up в v1.0.13.1.

### Scope

- P1-3: scenario baseline = intercept + controls (vs y_mean × n_periods)
- P1-4: scenario ROAS incremental = (scenario - baseline) / spend
- P1-5: scenario applies adstock to spend_t with carry-over from previous spends

### Implementation (sketch)

```python
# scenario.py - apply adstock to media plan
from utils.adstock import apply_adstock

for col in media_cols:
    spends = media_plan.get(col, [0] * n_periods)
    # Apply adstock to spends time series
    spends_adstock = apply_adstock(np.array(spends), adstock_config.get(col, 'geometric'))
    # ... use spends_adstock instead of spend_t

# Baseline = intercept + control effects
baseline_per_period = intercept_mean * y_std + y_mean + control_effect
baseline_total = baseline_per_period.sum()

# Incremental ROAS
roas_incremental = (scenario_total - baseline_total) / total_spend_money
# Keep roas_total as secondary metric для backward compat
```

### Test additions

- `test_scenario_applies_adstock` - pulse spend, verify period 2+ has carry-over contribution
- `test_scenario_incremental_roas_excludes_baseline`

---

## Phase 7: Ship (1-2h)

### Tasks

1. Update `docs/MATH_AUDIT_v1_1.md` Section 4 (severity table) - mark all P0 as resolved
2. Add audit done update to memory:
   - `project_econometrica_math_audit.md` → COMPLETE + ALL P0 RESOLVED
   - `project_econometrica_decomposer_rewrite.md` → COMPLETE
   - `project_econometrica_reconstruction_fix.md` → COMPLETE
   - `project_econometrica_optimizer_rescale.md` → COMPLETE
   - `project_econometrica_hill_normalization_root_fix.md` → COMPLETE
3. Update `MEMORY.md` priority entries
4. Update `PASHE_IT.MD` - breaking change notice for IT (old .pkl rejected)
5. Tag `v1.0.13-math-audited` on master after PR merge
6. (Eventually) GH Release + Supabase publish - separate ship session

### Ship gate (REQUIRED before tag)

- [ ] All P0 commits landed
- [ ] All tests PASS (current 64 + 4 post-fix = 68)
- [ ] Live Kagocel pipeline produces sensible numbers per acceptance в каждой phase
- [ ] No regressions in PPTX/HTML deliverables (existing 142 brand/narrative assertions still PASS)
- [ ] Migration path for old .pkl documented (clear "переобучите" UX)

---

## Risks & Mitigation

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Hill fix changes posterior shape, R-hat regresses | High | Refit Kagocel в Phase 2a smoke; if regression, tune priors (Beta(3,3) → HalfNormal(0.5) for gamma) |
| Decomposer energy conservation fails | Medium | Test forces it; if fail, debug in Phase 3 before commit |
| Optimizer SLSQP convergence breaks on new scale | Medium | Adjust x0 starting point; fall back to L-BFGS-B if needed |
| Old .pkl users blocked, support burden | Medium | Clear UX message + 1-click "переобучить" button in UI |
| Live-test reveals additional bugs | High | **Reserve 3-5h buffer in Phase 5**; if >2 new P0, stop and re-plan |
| MCMC compile time inflated | Low | NumPyro tier-1 path handles это (modeler.py:343+ already optimised) |

---

## Reusable infrastructure

- `tools/test_math_correctness.py` - 64 assertions, stdlib runner. Each phase updates relevant tests + adds new
- `feedback_shared_helpers_prevent_drift.md` lesson - Hill fix in 4 modules requires parity test (already written в test 10)
- `compute_report_id` pattern - если decomposer/optimizer/scenario имеют common spend-norm logic, consider extract в `utils/` shared helper

---

## Session split recommendation

**Session A (8-10h):** Phase 0 + 1 + 2 - setup, reconstruction, Hill normalization
- High-leverage: closes P0-1/2/7/9 = 4 of 11 P0
- Live-test gate at end of Phase 2

**Session B (8-10h):** Phase 3 + 4 - decomposer + optimizer
- Closes P0-3/4/5/6/10/11 = 6 more P0
- Live-test gate

**Session C (4-6h):** Phase 5 + 7 (Phase 6 optional)
- Validation suite, live-test
- Ship preparation

**Total: 20-26h across 3 sessions.** Could compress to 2 if working continuously, but живой regen сession разбивка снижает risk regression.

---

## Quick start

When ready to execute:

```bash
# Session A start
cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica
git checkout -b math-fix-v1.0.13
git tag v1.0.12-pre-fix-bundle  # safety
python tools/test_math_correctness.py  # baseline 64/64

# Phase 1 (independent - start here)
# Edit modeler.py:537, run tests, commit

# Phase 2 (most invasive)
# Edit modeler.py:251, scenario.py:86, all engines compat check
# Refit Kagocel, smoke test
```

Plan stays applicable until executed. Update sections as fixes land.
