# Math Audit v1.3 - Phase 0.1 Post-Audit Math Chain Rule Reference

**Created:** 2026-04-25
**Branch:** math-fix-v1.0.13
**Predecessor:** docs/MATH_AUDIT_v1_2_POST_FIX.md
**Trigger:** Live-test Kagocel выявил mROAS inconsistency между источниками. Глубокий audit показал что chain rule в `optimizer.py:255-258` неполный - отсутствует adstock factor и unit_cost normalization.

Этот документ - **single source of truth** для marginal ROAS computation. Любая ревизия mROAS в любом из движков (optimizer / decomposer / scenario / narrative) должна сверяться с этими формулами.

---

## 1. Definitions

| Symbol | Meaning | Units |
|---|---|---|
| `s` | total spend over n_periods (per channel) | native (TRP, ₽, clicks, ...) |
| `s_money` | total spend in money units | ₽ |
| `s_pp` | per-period average spend = s/n | native/period |
| `n` | number of training periods (e.g. 31 weeks) | - |
| `mean` | training-time mean of channel media volume | native/period |
| `θ` | geometric adstock decay (default 0.5) | - |
| `α, γ, β` | Hill saturation params (alpha, gamma, beta) | - |
| `y_std` | standard deviation of trained y (KPI) | KPI units |
| `unit_cost` | money cost per native unit (e.g. CPP for TRPs) | ₽/native |
| `adstock_avg(x, n, type)` | flat-allocation steady-state mean adstock | native/period |
| `hill(x_norm)` | `x_norm^α / (x_norm^α + γ^α)` | - (0..1) |
| `KPI` | predicted target variable (sales) | money units |

## 2. Forward chain (training-aware)

The training model fits:
```
y_t / y_std = intercept + Σ_ch β_ch · hill(x_norm_ch_t) + Σ_c β_c · z_t  +  ε
```

Where for media channel `ch`:
```
x_adstock_t = apply_adstock(raw_spend_t, type)        [length-n series]
x_norm_t    = x_adstock_t / mean
```

Optimizer (per `total_response` in `optimizer.py:182-192`) approximates this with **flat allocation**:
```
x_pp = s / n                                          [scalar per channel]
adstock_avg = _flat_alloc_adstock_avg(x_pp, n, type)  [scalar]
x_norm = adstock_avg / mean
contribution_normalized = β · hill(x_norm) · n        [normalized y units]
contribution_KPI        = contribution_normalized · y_std
```

This matches training **on average** for flat allocation. For non-flat allocation it's a steady-state approximation (clients don't expect per-period optimization).

## 3. Marginal ROAS - derivation

Marginal ROAS = `∂KPI(money) / ∂s(money)` evaluated at the current point.

### 3.1 Chain rule - money-axis

```
KPI(s) = β · hill(adstock_avg(s/n)/mean) · n · y_std

∂KPI/∂s = β · hill'(x_norm) · ∂x_norm/∂s · n · y_std

∂x_norm/∂s = ∂(adstock_avg(s/n)/mean)/∂s
           = (1/mean) · ∂(adstock_avg(s/n))/∂s
           = (1/mean) · adstock_factor · (1/n)         [chain rule on s/n]

   where adstock_factor := ∂(adstock_avg)/∂(x_pp)

⟹ ∂KPI/∂s = β · hill'(x_norm) · adstock_factor / mean · y_std
   (n cancels!)
```

This is `∂KPI(money)/∂s(native)`. To get **per-money** mROAS:
```
s_money = s_native · unit_cost
∂KPI/∂s_money = (∂KPI/∂s_native) / unit_cost
```

### 3.2 Final formula

```
mROAS = β · hill'(x_norm) · adstock_factor · y_std / mean / unit_cost
```

Units: KPI(money) per spend(money) = unitless ratio.

### 3.3 Hill derivative

```
hill(x) = x^α / (x^α + γ^α)
hill'(x) = α · γ^α · x^(α-1) / (x^α + γ^α)²
```

`saturation.py:marginal_roi()` already implements `β · hill'(x)` - use it (do not re-implement).

## 4. Adstock factor

Adstock factor = sensitivity of steady-state mean adstock to per-period input.

### 4.1 Geometric (analytical, exact)

For `geometric_adstock(x_t, alpha=θ)` defined as `result_t = x_t + θ · result_{t-1}`, with flat input `x_t = X` for all t:

```
result_0 = X
result_1 = X + θX = X(1+θ)
result_t = X · (1 + θ + θ² + ... + θ^t) = X · (1 - θ^(t+1))/(1-θ)

adstock_avg(X, n) = (1/n) · Σ_{t=0}^{n-1} X · (1 - θ^(t+1))/(1-θ)
                  = X · [n - θ·(1 - θ^n)/(1-θ)] / [n·(1-θ)]

∂adstock_avg/∂X = [n - θ·(1 - θ^n)/(1-θ)] / [n·(1-θ)]   (constant in X - linear adstock)
```

For typical θ=0.5, n=31: factor ≈ 1.935. For θ=0.5, n=10: factor ≈ 1.800. For θ=0, n=anything: factor = 1.0.

### 4.2 Weibull (numerical)

Weibull adstock is a convolution with PDF weights - also linear in X. Can be analytical but messy; use central difference:
```
eps = max(x_pp · 1e-4, 1e-9)
factor ≈ (adstock_avg(x_pp + eps) - adstock_avg(x_pp - eps)) / (2·eps)
```

Error bound: O(eps²) for smooth function. For our linear adstock, exact (modulo float).

### 4.3 'noop' / 'none'

For testing - no carryover. `adstock_avg(X, n) = X`, factor = 1.0.

## 5. Adstock params - invariant

**As of v1.0.13 (until Phase 1.1 makes them learnable):**

- Adstock parameters (`geometric.alpha=0.5`, `weibull.shape=2.0, scale=3.0`) are **library defaults**, not sampled in NUTS.
- Training (`modeler.py:240-244`) calls `apply_adstock(series, a_type)` with **type only** - no params override.
- Optimizer (`optimizer.py:111-120`) does the same.
- Scenario (`scenario.py`) does the same.

**Symmetry holds** between training and inference. No params loss bug - just a known limitation that adstock decay is hardcoded.

**Phase 1.1 (joint adstock+Hill MCMC) will:**
- Sample θ via `pm.Beta` prior
- Persist sampled mean to pickle
- Pass to all downstream engines

Until Phase 1.1, `compute_mroas_money()` uses defaults.

## 6. Edge cases

| Case | Behavior |
|---|---|
| `current_spend = 0` | mROAS undefined (no current point) → return 0 |
| `mean = 0` | division by zero → return 0 (no training signal) |
| `β = 0` | untrained channel → return 0 |
| `x_norm < 1e-10` | numerically zero → use 1e-10 floor |
| `unit_cost = 0` | absurd → return 0 (avoid div by zero, signal data error) |

## 7. Verification

Single source of truth: `engines/optimizer.py:_compute_mroas_money()`.

**Analytical test case** (`tools/test_math_correctness.py`):

```
α=1, γ=1, no adstock, β=100, n=10, mean=10, y_std=1000, unit_cost=5
cur = 100 (per period = 10, x_norm = 1)

hill(1) = 1/(1+1) = 0.5
hill'(1) = 1·1¹·1⁰ / (1¹+1¹)² = 1/4 = 0.25
adstock_factor = 1.0 (noop)

mROAS = 100 · 0.25 · 1 · 1000 / 10 / 5 = 500
```

Property tests:
- `unit_cost` invariance: `mroas(uc=K) · K = mroas(uc=1)` (constant)
- Monotonicity: `mROAS` decreases with spend in saturated zone
- Zero spend → 0

## 8. Historical fixes (что было сломано до Phase 0.1)

| Bug | Location | Pre-fix | Post-fix |
|---|---|---|---|
| Missing adstock factor | optimizer.py:257 | `mroi = mroi_norm · y_std / mean` | `· adstock_factor` added |
| Missing /unit_cost | optimizer.py:257 | per-native-spend (TRPs 1780×) | per-money (TRPs ~0.007×) |
| Typo `miroas` | narrative_adapter.py:196 | fall through на average ROI | `mroi_current` correctly read |
| JS marginalROI ≠ Python | OptimizeStep.svelte:910-945 | `gammaScaled = γ·spend` | deprecated, frontend reads backend |

## 9. Field naming convention

| Field | Source | Semantics |
|---|---|---|
| `mroi_current` | optimizer.py output | marginal ROAS in money-per-money at current allocation |
| `mroi_optimal` | optimizer.py output | marginal ROAS at optimized allocation |
| `mroas` | narrative_adapter merged channels | reads from `mroi_current` |
| `roi` | decomposer.py output | **average ROI** = contribution / spend (different metric!) |
| `avg_roi` | narrative_adapter merged | reads from `roi` (renamed for clarity) |

**Never confuse `roi` with `mroas`.** Reports must show both as separate columns when both are available.

---

**For future audits:** start from this doc + check `tools/test_math_correctness.py:test_compute_mroas_*`. If formula needs to change, update both the doc and the tests in the same commit.
