# Aurora AI Econometrica - Math Audit v1.1

**Date:** 2026-04-25
**Auditor:** Claude (Opus 4.7, autonomous session)
**Scope:** modeler, validator, decomposer, optimizer, scenario, adstock_selector, utils (saturation/adstock/diagnostics), JS Hill в aurora_html/interactive.py
**Prior work:** v1.0.12.5 output quality program complete (`HEAD a2fa0bc`)
**Trigger:** z-score Hill bug (live-test 2026-04-24) ставит под сомнение всю математику

---

## 1. Executive Summary

Audit identified **11 P0 (correctness-breaking) findings** and 6 P1 (methodologically questionable). Model trust is currently **NOT SUFFICIENT** for commercial ship. Multiple independent bugs converge on one outcome: reported results неверны even if they look plausible.

### Top 3 findings

1. **Decomposer ignores Hill saturation and adstock entirely (P0-3, P0-4).** Channel contributions computed as `|β_i| / Σ|β_j| × (total − baseline)` - proportional to coefficient magnitude only. Real MMM decomposition = `β × sat(adstock(x))`. Current formula approximates correct result only in degenerate cases. Baseline formula `total − predicted.sum() + predicted.mean() × n × 0.3` is mathematically nonsensical.

2. **Training-reconstruction inconsistency (P0-7).** Inside `pm.Model()` Hill uses `gammas[i]` directly. In manual posterior reconstruction (same `modeler.py`), Hill uses `gammas[i] × max(x, 1e-10)`. The y_pred used for R²/MAPE/diagnostics is computed with a DIFFERENT formula than the model was trained on. All reported fit metrics are wrong by this artifact.

3. **Three-way Hill formula drift across modules (P0-1/5/6/9).**
   - **Training:** `(x_norm)^α / ((x_norm)^α + γ^α)` with `x_norm = (x - mean)/std` (z-score)
   - **Scenario:** same z-score (matches training)
   - **Optimizer:** `raw_spend^α / (raw_spend^α + (γ × current_spend)^α)` (raw scale + scaled gamma - completely different)
   - **JS what-if slider:** `(spend/mean)^α / ((spend/mean)^α + γ^α)` (Robyn-style - also different)

   Four different Hill invocations for "the same" model. User gets different numbers from each.

### Shipping recommendation

**DO NOT ship v1.0.13 to commercial clients** until:
- P0-1 (Hill normalization) fixed per separate `project_econometrica_hill_normalization_root_fix` task
- P0-2 through P0-11 resolved as described в Section 4
- Behavior-pinning tests (`tools/test_math_correctness.py`) all PASS
- Live Kagocel run shows sensible sensitivity in scenarios and optimizer

### What audit deliberately avoided

- Fixing defects during audit (scope discipline; fixes are separate tasks with their own testing)
- Full MCMC-based synthetic tests (require post-Hill-fix baseline to be meaningful)
- Simulation-based calibration (SBC) - gold standard but weeks of compute

---

## 2. Methodology

- **Read pass:** single integrated pass through all math files (saves 3h vs separate R1+R2+R3 rounds in planv1.1). See audit file list in Section 6.
- **References cross-checked:**
  - **PyMC-Marketing** (`pymc-labs/pymc-marketing`) - closest semantic match (same PyMC stack, same Bayesian methodology). **Primary reference.**
  - **Robyn** (Meta, R) - https://facebookexperimental.github.io/Robyn/. Spend/mean normalization, geometric/Weibull adstock, saturation choices.
  - **Meridian** (Google, Python) - https://github.com/google/meridian - 2024 release, TensorFlow Probability.
  - LightweightMMM - archived 2024; historical reference only.
- **Behavior-pinning tests:** `tools/test_math_correctness.py` - captures current formula correctness on PURE (non-MCMC) math.
- **MCMC-based tests** (prior/posterior predictive, SBC) - deferred to post-Hill-fix session.

---

## 3. Per-formula Inventory + Findings

### 3.1 Media normalization (modeler.py:249-251)

**Formula:**
```python
X_media_norm = (X_media - media_means) / media_stds
```

**Inputs:** adstocked raw spend per channel × period. **Output:** z-scored spend, range approximately [-3, +3].

**References:**
- PyMC-Marketing: uses **spend / max_spend** (normalized to [0, 1])
- Robyn: uses **spend / mean(spend)** (Robyn-style) - positive scale centered at 1
- LightweightMMM (historic): **spend / median(spend)**

**Verdict:** 🔴 **P0-1** - z-score places zero of Hill input at MEAN spend (not zero spend). Half the periods have `x_norm < 0` → clipped to 0 in training (line 310) → those periods contribute **zero media effect** silently. The Beta(3,3) gamma prior then places half-saturation at `γ ≈ 0.5` on z-scale ≈ 0.5 std above mean → any spend above ~2 std saturates completely. Documented in separate `project_econometrica_hill_normalization_root_fix`.

**Fix (external):** Robyn-style `X_media_norm = X_media / media_means`.

---

### 3.2 Negative-z clipping in training (modeler.py:310)

**Formula:**
```python
x_safe = pm.math.maximum(x_ch, 0)
```

**Semantic:** any `x < 0` in normalized spend → 0. With z-scored input, `x < 0` means "spend below mean" → silently dropped.

**Verdict:** 🔴 **P0-2** - ~50% of periods have below-mean spend. Training never sees their media effect. Model learns from "above-mean only" which is ~25 periods out of 52-week dataset. Post-Hill-fix to spend/mean, `x_norm ≥ 0` always (provided spend ≥ 0), so clip becomes no-op. But clip should stay as defense-in-depth against negative spend in scenarios. **The clip is a symptom of broken normalization, not independent bug.**

**Fix (consequence of P0-1):** after spend/mean, clip retained for defense but never triggered.

---

### 3.3 Training Hill formula (modeler.py:312)

**Formula:**
```python
saturated = x_safe ** alphas[i] / (x_safe ** alphas[i] + gammas[i] ** alphas[i] + 1e-10)
```

**Inputs:** `x_safe ≥ 0` (adstocked z-scored spend, clipped). `alphas[i] ~ Gamma(5, 3)` (mean 1.67, var 0.56). `gammas[i] ~ Beta(3, 3)` (mean 0.5, concentrated [0.2, 0.8]).

**Verdict:** 🟢 Formula structure correct (Hill/Michaelis-Menten form). 🔴 **Inputs semantically broken** (P0-1/P0-2). `1e-10` stability term prevents div/0 при всех zeros. Numerical safe.

---

### 3.4 Adstock application (modeler.py:237-244 + utils/adstock.py)

**Geometric:**
```python
result[t] = x[t] + alpha * result[t - 1]  # alpha defaults to 0.5
```

**Weibull:**
```python
weights = (shape/scale) * (lags/scale)^(shape-1) * exp(-(lags/scale)^shape)
weights = weights / weights.sum()   # normalize
result = convolve(x, weights)[:n]
```

**Verdict:**
- 🟢 Geometric recursion correct (standard Koyck lag).
- 🟢 Weibull PDF weights correct with normalization.
- 🔴 **P1-1** - **adstock parameters NEVER estimated by MCMC**. Training applies adstock as pre-processing with fixed defaults (alpha=0.5 geometric, shape=2/scale=3 Weibull). Real MMM (Robyn, PyMC-Marketing) **jointly estimates** adstock + Hill params. Our model is missing a whole layer of flexibility.

**Fix:** move adstock inside `pm.Model()`, sample `alpha_adstock ~ Beta(2, 2)` and `shape/scale` priors. Large refactor. Document as P1, plan separate task.

---

### 3.5 Posterior reconstruction (modeler.py:520-546)

**Formula:**
```python
gamma_scaled = gamma_i * max(x_safe.max(), 1e-10)
saturated = x_safe ** alpha_i / (x_safe ** alpha_i + gamma_scaled ** alpha_i + 1e-10)
```

vs training (line 312) which used raw `gammas[i]`.

**Verdict:** 🔴 **P0-7 CRITICAL** - manual reconstruction uses `gamma × x.max()` instead of `gamma`. This is a SEMANTIC CHANGE vs training formula.

Consequences:
- y_pred used for R², MAPE, RMSE is computed with wrong formula
- Diagnostics reported to client are based on inconsistent predictions
- Client sees "R² = 0.87" which was computed from a DIFFERENT model than was trained
- `pm.sample_posterior_predictive` would give correct (but slow) predictions; manual reconstruction diverges silently

**Fix:** remove `gamma_scaled = gamma_i * max(...)` line - use `gamma_i` directly matching training. Alternatively fall back to `pm.sample_posterior_predictive` with speed optimization (subsample 200 draws instead of 8000).

---

### 3.6 Diagnostics (utils/diagnostics.py)

**Formulas:**
- R² = `1 - SS_res / SS_tot` - standard.
- MAPE = `mean(|y - ŷ| / |y|) × 100` with `y != 0` mask - safe.
- RMSE = `sqrt(mean((y - ŷ)^2))` - standard.

**Verdict:**
- 🟢 Formulas correct.
- 🔴 **Consequence of P0-7:** inputs (y_pred) are wrong → outputs wrong.
- 🟡 **P2-1:** R² can go negative if model is very bad; current code returns `float(...)` not clamped. Not a bug but surprising for UI (says "R² = -0.3").

---

### 3.7 Model Quality Score (utils/diagnostics.py:29-88)

**Formula:**
```python
raw_mqs = r2_score * 0.4 + mape_score * 0.3 + convergence_score * 0.3
mqs = min(raw_mqs, thinness_cap)  # cap 50/70 if ratio < 2/4
```

where:
- `r2_score = min(100, max(0, r² × 100))`
- `mape_score = min(100, max(0, 100 - mape × 2))`
- `convergence_score ∈ {100, 70, 30}` based on r_hat and divergences

**Verdict:**
- 🟢 MQS is internal scoring, not pretending to be industry-standard.
- 🟡 **P2-2:** weights 0.4/0.3/0.3 arbitrary, no citation. No published MMM quality composite. Document as internal convention.
- 🟢 Thinness cap at ratio < 4 matches "observations-to-parameters ≥ 4" heuristic from MMM literature.
- 🟡 **P2-3:** `mape_score = 100 - mape × 2` means MAPE 50% → 0 score, MAPE 25% → 50 score. Linear mapping arbitrary.

**Fix:** document weights rationale in methodology doc. Consider exposing component scores separately rather than composite.

---

### 3.8 Decomposer baseline (decomposer.py:50)

**Formula:**
```python
baseline = float(y_actual.sum() - y_predicted.sum()) + float(y_predicted.mean() * len(y_actual) * 0.3)
```

**Decoded:** `baseline = (Σy_actual - Σy_predicted) + (mean(y_predicted) × n × 0.3)`

**Verdict:** 🔴 **P0-4 CRITICAL** - formula is mathematically nonsensical.

- `Σy_actual - Σy_predicted` = residual sum (should be ~0 for good model, positive/negative for biased model).
- Adding `0.3 × mean × n = 0.3 × Σy_predicted` is magic numeric - where does 0.3 come from? Undocumented.
- Proper MMM baseline = `intercept × y_std + y_mean + control_effects` (on original scale).

**Consequences:** "baseline" in every deliverable is wrong. All channel contribution shares are wrong by this offset.

**Fix:** compute baseline from posterior:
```python
baseline_per_period = intercept * y_std + y_mean + Σ(control_beta_i × x_control_norm_i) * y_std
baseline_total = baseline_per_period.sum()
```

---

### 3.9 Decomposer channel contributions (decomposer.py:62-65)

**Formula:**
```python
total_beta = sum(abs(channel_params[c]['beta']) for c in media_cols)
contribution_pct = abs(params['beta']) / total_beta
contribution = (total_sales - baseline) * contribution_pct
```

**Verdict:** 🔴 **P0-3 CATASTROPHIC** - channel contribution is computed as `|β_i| / Σ|β_j| × total_media_sales`. This **completely ignores**:

1. **Hill saturation** - a channel with large β but highly saturated spend contributes LESS than β suggests
2. **Adstock** - delayed carryover effect not captured
3. **Spend level** - a channel with β=1 but tiny spend contributes less than β=0.1 with huge spend

This is NOT MMM decomposition. It's just a β-weighted distribution of total media effect. Results are wrong by arbitrary factors.

**Proper MMM decomposition:**
```python
for i, col in enumerate(media_cols):
    x_ch_norm = X_media_norm[col].values  # same as training
    sat = hill_function(max(x_ch_norm, 0), alpha=p['alpha'], gamma=p['gamma'])
    contribution_per_period = p['beta'] * sat * y_std  # in original KPI units
    contribution_total = contribution_per_period.sum()
```

**Fix:** rewrite decomposer to use actual saturated contribution per period, then sum.

---

### 3.10 Decomposer per-period contribution (decomposer.py:172-182)

**Formula:**
```python
ts_contrib = [(float(s) / total_raw * ch_contribution) for s in spend_per_period]
```

**Verdict:** 🔴 **P0-10** - per-period contribution distributed **proportionally to raw spend**, ignoring Hill saturation. A week with 2× typical spend gets ~2× contribution, but real MMM would give <2× due to saturation. Timeline band chart in PPTX/HTML consequently mismatched.

**Fix:** per-period contribution = β × sat(adstock(x_t)) × y_std using posterior-mean params.

---

### 3.11 Optimizer Hill invocation (optimizer.py:92)

**Formula:**
```python
sat = hill_function(
    np.array([spend_vector[i]]),  # RAW spend in native units
    alpha=p['alpha'],
    gamma=max(p['gamma'] * current_spend[col], 1),  # SCALED gamma by current raw spend
)
```

**Verdict:** 🔴 **P0-5 + P0-6 + P0-11** - **triple inconsistency** with training:

1. Training Hill receives **z-scored** spend; optimizer Hill receives **raw** spend. 1000× difference in scale.
2. Training gamma is `gammas[i]` (unitless, posterior ∈ [0.2, 0.8]); optimizer gamma is `p['gamma'] × current_spend` (in raw spend units, so billions of rubles for TV). Completely different quantity.
3. `max(..., 1)` floor - what does "1" mean? 1 ruble? 1 TRP? Depends on channel units - inconsistent semantics.

Optimizer finds "optimal" budget but the Hill curve it's optimizing over doesn't match the trained model. Results are garbage that happens to look reasonable on chart.

**Consequences:**
- "+12% predicted lift" is fabricated from wrong formula
- Scenario inconsistency between optimize step and scenario step (they use different formulas)
- Response curves drawn from optimizer show wrong saturation shape

**Fix:** optimizer must apply **same normalization** as training. After Hill fix:
```python
x_norm = spend_vector[i] / media_means[col]
sat = hill_function(max(x_norm, 0), alpha=p['alpha'], gamma=p['gamma'])
```

---

### 3.12 Optimizer budget constraint (optimizer.py:109)

**Formula:**
```python
constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x) - total_budget}]
```

**Verdict:** 🟡 **P1-2** - constraint sums channels in **native units**. If TV is in TRPs and Digital is in rubles, `sum(TRPs, rubles) = meaningless`. Money-mode branch (line 103-107) correctly multiplies by `unit_costs` - that's the right path. Native-mode only valid if all channels already in same unit.

**Fix:** reject native-mode budget constraint if `unit_costs` aren't all 1.0 (all-money) or all non-1.0 (all-native of same scale). Warn user в UI.

---

### 3.13 Marginal ROI (utils/saturation.py:26-43)

**Formula:**
```python
numerator = alpha * gamma^alpha * x^(alpha-1)
denominator = (x^alpha + gamma^alpha)^2
mroi = beta * numerator / (denominator * delta)
```

**Derivation:** `d/dx [β × x^α / (x^α + γ^α)] = β × α × γ^α × x^(α-1) / (x^α + γ^α)^2`. **Correct derivative.** `delta` is optional scaling factor (=1 default).

**Verdict:** 🟢 Formula correct. 🔴 **Same input scale issue as P0-5 when called from optimizer** - mroi at raw spend scale doesn't match training scale.

**Fix:** consequence of P0-5 fix.

---

### 3.14 Scenario prediction loop (scenario.py:76-95)

**Formula:**
```python
x_norm = (spend_t - mean) / std if std > 0 else 0
sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 0.01))
contribution = p['beta'] * sat[0]
total_effect += contribution
predicted = total_effect * y_std + y_mean
```

**Verdict:**
- 🟢 Uses **same z-score** as training (consistent pre-Hill-fix).
- 🔴 **Consequence of P0-1** - relies on broken training normalization. Will need updating post-Hill-fix (spend/mean).
- 🔴 **Skips adstock** - scenario.py doesn't call `apply_adstock` on spend_t before Hill. Training applies adstock; scenario doesn't. For delayed-effect channels (TV/OOH), scenario underestimates contribution in early periods.
- 🟡 **P1-3** - scenario baseline = `y_mean × n_periods` (line 98), not intercept-based. Same issue as decomposer P0-4 simplified.

**Fix:** post-Hill-fix, also:
1. Apply adstock to spend_t in scenario (needs carry-over from previous period spend)
2. Baseline from intercept + control effects, not y_mean

---

### 3.15 Scenario ROAS (scenario.py:105, 116-120)

**Formula:**
```python
roas_native = scenario_total / total_spend_native
roas_money = scenario_total / total_spend_money
```

**Verdict:** 🟡 **P1-4** - **ROAS is total-KPI / spend, NOT incremental**. Industry standard MMM reports ROAS as `(scenario_kpi - baseline_kpi) / spend`. Current formula overstates ROAS by including the baseline (which would exist without any media).

Example: baseline 80M, media contribution 20M, spend 10M. Current ROAS = 100/10 = 10×. Industry standard = 20/10 = 2×. **5× overstate.**

**Fix:** `roas_incremental = (scenario_total - baseline_total) / spend`. Keep `roas_total` as secondary metric if needed.

---

### 3.16 JS Hill in what-if slider (interactive.py:689-693)

**Formula:**
```javascript
var z = spend / mean;
var za = Math.pow(z, p.alpha);
var ga = Math.pow(p.gamma, p.alpha);
var sat = za / (za + ga);
```

**Verdict:** 🔴 **P0-9 SHARED-HELPER DRIFT** - JS uses **spend/mean** (Robyn-style, correct per Hill fix target). Python training uses **z-score** (broken). Python optimizer uses **raw spend**. Four DIFFERENT Hill formulas for same model.

Client opens HTML report: what-if slider shows Hill with one formula. Opens PPTX: sees optimizer allocation based on different formula. Runs Python scenario CLI: gets third set of numbers. Inconsistent by design.

Post Hill fix, Python training → spend/mean, optimizer → spend/mean, scenario → spend/mean, JS → spend/mean. All converge. Audit confirms JS is already prepared for the fix - no JS change needed when Python catches up.

**Fix (external to audit):** Hill fix task applies spend/mean to Python side. Verify JS unchanged via parity test.

**Recommendation:** extract Hill formula to shared source (comments in JS + Python referring to same equation), and add parity test that runs JS Hill via Node subprocess and Python Hill on same grid, assert equal. This is the `compute_report_id` pattern applied again.

---

### 3.17 Optimizer x0 initial guess (optimizer.py:97)

**Formula:**
```python
x0 = np.array([current_spend[col] * total_budget / total_current for col in media_cols])
```

**Verdict:** 🟢 Proportional scaling - safe starting point inside feasible region.

---

### 3.18 Validator correlation detection (validator.py:329-352)

**Formula:**
```python
corr_df = df[numeric_cols].corr()
for i, c1 in enumerate(numeric_cols):
    for j, c2 in enumerate(numeric_cols):
        if i < j and abs(corr_df.loc[c1, c2]) > 0.8:
            high_correlations.append(...)
```

**Verdict:**
- 🟢 Pearson correlation + threshold 0.8 - standard heuristic.
- 🟡 **P2-4 identifiability partial** - pairwise correlation catches 2-way collinearity but misses **multicollinearity** (3+ variables near-linear combination). For real MMM should use **VIF (variance inflation factor)** - `VIF_i = 1 / (1 - R²_i)` where `R²_i` is R² of regressing channel i on all other channels. VIF > 5 flags issue, > 10 critical.

**Fix:** add VIF check to validator. Moderate effort.

---

### 3.19 Adstock selector BIC (adstock_selector.py:83-85)

**Formula:**
```python
bic = n * np.log(max(rss / n, 1e-10)) + k * np.log(n)  # k=2 (intercept + slope)
```

**Verdict:**
- 🟢 BIC formula correct (Schwartz criterion).
- 🟢 Standard use case (lower BIC = better model).
- 🟡 **P2-5:** selection uses simple OLS (no adstock params estimated), picks between `geometric(α=0.5)` vs `weibull(shape=2, scale=3)` **with fixed defaults**. Doesn't explore the hyperparameter space.
- Related to P1-1: adstock hyperparams never optimized.

---

### 3.20 Training-scenario consistency

Across training, scenario, optimizer, decomposer, and JS - five invocations of Hill saturation applied to spend. Per audit:

| Module | Normalization | Gamma scaling |
|--------|---------------|---------------|
| Training (modeler.py:312) | z-score | raw `gammas[i]` |
| Reconstruction (modeler.py:537) | z-score | `gammas[i] × x.max()` ❌ |
| Decomposer (implicit via proportion) | - | N/A (doesn't use Hill) ❌ |
| Scenario (scenario.py:86-89) | z-score | raw `p['gamma']` ✓ matches training |
| Optimizer (optimizer.py:92) | **raw spend** | `p['gamma'] × current_spend` ❌ |
| JS what-if (interactive.py:689) | **spend/mean** | raw `p['gamma']` ❌ |

**Only scenario matches training.** Reconstruction, decomposer, optimizer, JS all diverge.

---

## 4. Findings by Severity

### 🔴 P0 - Correctness-breaking (ship-blocking)

| ID | Location | Summary | Fix owner |
|----|----------|---------|-----------|
| P0-1 | modeler.py:251 | z-score normalization → Hill broken | Hill fix task |
| P0-2 | modeler.py:310 | clip(x, 0) drops half of periods silently | Auto-resolved by P0-1 fix |
| P0-3 | decomposer.py:62-65 | Contribution = |β|/Σ|β|, ignores saturation+adstock+spend | NEW task: `econometrica_decomposer_rewrite` |
| P0-4 | decomposer.py:50 | Baseline = nonsensical formula with magic 0.3 | Same task as P0-3 |
| P0-5 | optimizer.py:92 | Hill input = raw spend (training uses z-score) | NEW task: `econometrica_optimizer_rescale` |
| P0-6 | optimizer.py:92 | gamma × current_spend (training uses raw gamma) | Same as P0-5 |
| P0-7 | modeler.py:537 | Reconstruction Hill differs from training Hill | NEW task: `econometrica_reconstruction_fix` |
| P0-8 | N/A | (merged into P0-7) | - |
| P0-9 | interactive.py:689 | JS Hill = spend/mean; Python = z-score → drift | Auto-resolved by Hill fix |
| P0-10 | decomposer.py:172-182 | Per-period contribution proportional to raw spend (no saturation) | Same as P0-3 |
| P0-11 | optimizer.py:109 | Mixed-units sum in native-mode constraint | Validator + money-mode default |

### 🟡 P1 - Methodologically questionable

| ID | Location | Summary | Suggestion |
|----|----------|---------|-----------|
| P1-1 | modeler.py:237-244 | Adstock params NOT estimated by MCMC, fixed defaults | Large refactor - move adstock inside pm.Model() |
| P1-2 | optimizer.py:109 | Mixed-units native constraint | Force money-mode |
| P1-3 | scenario.py:98 | Baseline = y_mean × n_periods (vs intercept-based) | Align with P0-4 fix |
| P1-4 | scenario.py:116-120 | ROAS total vs incremental | Add incremental ROAS as primary metric |
| P1-5 | scenario.py | Scenario doesn't apply adstock | Add adstock pre-processing |
| P1-6 | utils/diagnostics.py:51 | MQS weights 0.4/0.3/0.3 uncalibrated | Document rationale |

### 🟢 P2 - Documentation debt

| ID | Location | Summary |
|----|----------|---------|
| P2-1 | utils/diagnostics.py:13 | R² not clamped (can be negative) |
| P2-2 | utils/diagnostics.py | MQS weights arbitrary |
| P2-3 | utils/diagnostics.py:45 | MAPE→score linear mapping arbitrary |
| P2-4 | validator.py:329-352 | No VIF check (pairwise only) |
| P2-5 | adstock_selector.py | OLS selector with fixed adstock hyperparams |

---

## 5. Reference Compliance Matrix

| Formula | Our | PyMC-Marketing | Robyn | Meridian | Verdict |
|---------|-----|----------------|-------|----------|---------|
| Media normalization | z-score ❌ | spend/max | spend/mean | Bayesian hierarchical | 🔴 non-standard |
| Hill saturation | `x^α/(x^α+γ^α)` | same structure | same | same | 🟢 form OK, 🔴 inputs broken |
| Gamma prior | Beta(3,3) | usually Beta/HalfNormal on positive scale | LogNormal | Uniform(0, 1) | 🟡 reasonable post-fix |
| Alpha prior | Gamma(5,3) mean 1.67 | Gamma(3,1) mean 3 | Uniform(0.5, 3) | HalfNormal | 🟡 slight bias low |
| Adstock estimation | pre-computed ❌ | jointly MCMC | jointly MCMC | jointly MCMC | 🔴 ours misses flexibility |
| Decomposition | `\|β\|/Σ\|β\|` ❌ | `β×sat(adstock(x))` | same | same | 🔴 our formula wrong |
| ROAS | total/spend | incremental | incremental | incremental | 🟡 our overstates |
| MCMC backend | NumPyro tier-1, PyTensor fallback | NumPyro/PyMC native | Stan | TensorFlow Probability | 🟢 modern |

---

## 6. Files Audited

| File | LOC | Status |
|------|-----|--------|
| `sidecar/econometrica/engines/modeler.py` | 728 | 🔴 3 P0, 1 P1 |
| `sidecar/econometrica/engines/validator.py` | 403 | 🟢 1 P2 (VIF) |
| `sidecar/econometrica/engines/decomposer.py` | 252 | 🔴 3 P0 |
| `sidecar/econometrica/engines/optimizer.py` | 196 | 🔴 3 P0, 1 P1 |
| `sidecar/econometrica/engines/scenario.py` | 291 | 🔴 1 P0 consequence, 3 P1 |
| `sidecar/econometrica/engines/adstock_selector.py` | 131 | 🟢 1 P2 |
| `sidecar/econometrica/utils/saturation.py` | 58 | 🟢 pure formulas correct |
| `sidecar/econometrica/utils/adstock.py` | 67 | 🟢 formulas correct |
| `sidecar/econometrica/utils/diagnostics.py` | 136 | 🟡 3 P2 |
| `sidecar/econometrica/aurora_html/interactive.py` (JS) | ~230 | 🔴 1 P0 drift (auto-resolves) |

---

## 7. Recommendations

### Must-fix pre-v1.0.13 ship

1. **Hill normalization** (`project_econometrica_hill_normalization_root_fix`) - in progress
2. **Decomposer rewrite** - new task, detailed in Section 3.8, 3.9, 3.10
3. **Optimizer rescale** - new task, detailed in Section 3.11
4. **Reconstruction fix** - new task, detailed in Section 3.5

### Should-fix v1.0.13 or v1.0.13.1

5. Scenario adstock + incremental ROAS (P1-3, P1-4, P1-5) - bundled task
6. Joint adstock estimation (P1-1) - large refactor, could be v1.1

### Nice-to-fix v1.0.14+

7. VIF validator (P2-4)
8. MQS rationale docs (P1-6, P2-2, P2-3)
9. Adstock selector refinement (P2-5)
10. R² clamping in UI (P2-1)

### Process improvements

- Extract Hill formula to shared source with JS mirror comment - add parity test (per `feedback_shared_helpers_prevent_drift`)
- Post-fix: full prior/posterior predictive checks (deferred from this audit due to pre-fix baseline being meaningless)
- Eventually: SBC (simulation-based calibration) - ship criterion для v2

---

## 8. Test Coverage

- `tools/test_math_correctness.py` (this audit) - pure formula tests (no MCMC required):
  - Hill monotonicity, bounds, half-saturation
  - Adstock geometric recursion, Weibull normalization
  - y normalization roundtrip
  - MAPE guard, R² standard
  - Marginal ROI = analytical derivative
  - Training-reconstruction Hill-gamma divergence detector (regression test that catches P0-7 re-introduction)

- Deferred to post-Hill-fix:
  - Synthetic MCMC parameter recovery (single channel, known β/α/γ → fit → assert close)
  - Prior predictive plausibility
  - Posterior predictive coverage
  - Scenario sensitivity regression (+100% vs -50% budget)
  - Optimizer non-trivial allocation regression
  - What-if slider delta sensibility

---

## 9. Audit Process Notes

- **Scope respect:** audit did NOT fix defects (separate tasks). Exception: none - no inline fixes made.
- **Reference claims:** citations are from public MMM literature knowledge; URLs pinned in Section 2. Formal version-pinning deferred to fix tasks.
- **Unit tests:** pure-formula tests added to `tools/test_math_correctness.py`; MCMC tests intentionally deferred until post-fix when baseline is meaningful.
- **Time spent:** ~4-5h of audit (read + analyze + document), vs planned 18-22h. Savings came from (a) single integrated pass vs 3 rounds, (b) deferring MCMC tests post-fix.
- **Peer review:** not performed (solo session). Recommended before ship: second-pass review of findings.

---

**Audit complete 2026-04-25.** All findings filed. Fix execution is separate work per dedicated task docs.
