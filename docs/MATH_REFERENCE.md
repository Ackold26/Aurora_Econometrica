# Aurora Econometrica — Math Reference (living doc)

**Purpose:** centralized math reference for all model components. Versioned sections per release.
Replaces sprawled MATH_AUDIT_v1_*.md files (single source of truth).

**Last updated:** 2026-04-28 (v1.2.0 development — Awareness KPI + Weibull Learnable; doc-extension session)

---

## Table of Contents

**Foundations**
- [Glossary (notation & terms)](#glossary-notation--terms)
- [Numerical example end-to-end (synthetic 5-channel)](#numerical-example-end-to-end-synthetic-5-channel)

**Per-component math**
- [KPI Registry (v2.0+)](#kpi-registry-v20)
- [Awareness KPI Engine (v1.2.0)](#awareness-kpi-engine-v120)
- [Weibull Learnable Adstock (v1.2.0)](#weibull-learnable-adstock-v120)
- [Trust Level 3 Hierarchical Brand/Performance (v1.1.0)](#trust-level-3-hierarchical-brandperformance-v110)
- [Phase 1.1 Adstock decay sampling (v1.0.13+)](#phase-11-adstock-decay-sampling-v1013)
- [Hill saturation normalization (v1.0.12+)](#hill-saturation-normalization-v1012)
- [Decomposer (downstream extraction)](#decomposer-downstream-extraction)
- [Optimizer (SLSQP + chain rule)](#optimizer-slsqp--chain-rule)

**Uncertainty quantification**
- [Conformal Prediction (S-OLS-1)](#conformal-prediction-s-ols-1)
- [Bootstrap ROI CI (small-N OLS path)](#bootstrap-roi-ci-small-n-ols-path)

**Robustness & operations**
- [Numerical stability & edge cases](#numerical-stability--edge-cases)
- [Prior predictive check (sanity gate)](#prior-predictive-check-sanity-gate)
- [Diagnostics gate (ship vs warn vs info)](#diagnostics-gate-ship-vs-warn-vs-info)
- [Identifiability appendix — Weibull reparam](#identifiability-appendix--weibull-peak_week-tail_decay-reparam)
- [Pickle migration runbook](#pickle-migration-runbook)

**Context**
- [Literature & industry comparison](#literature--industry-comparison)
- [Versioning policy для самого документа](#versioning-policy-для-самого-документа)

---

## Glossary (notation & terms)

**Symbols (используются повсюду в этом документе и в коде):**

| Symbol | Meaning | Where learned / set |
|--------|---------|---------------------|
| `β` (beta) | channel coefficient — effect on KPI per unit adstocked+saturated spend | learned via MCMC, hierarchical (Trust 3) |
| `γ` (gamma) | Hill half-saturation point (saturation = 50% где `x_norm = γ`) | learned, prior `Beta(3,3)` for sales |
| `α` (alpha) | Hill steepness exponent (S-curve sharpness) | learned, prior `HalfNormal(2)` typical |
| `θ` (theta) | geometric adstock decay rate (`x_t + θ·x_{t-1}`), `θ ∈ [0,1]` | learned via Phase 1.1 logit-normal hierarchical |
| `λ` (lambda) | Weibull scale parameter | derived из `(peak_week, tail_decay)` reparam |
| `k` | Weibull shape parameter | derived из `tail_decay` |
| `σ` (sigma) | observation noise std-dev (Normal likelihood) | learned, prior `HalfNormal` |
| `μ_logit` | hierarchical prior mean on logit-decay scale | KPI_REGISTRY constant |
| `T` | number of training periods | data-driven |
| `y_std`, `y_mean` | KPI normalization constants | computed once from training, saved в pickle |
| `mean(spend)` | per-channel mean используется в spend/mean Hill normalization (Robyn-style) | computed once, saved в pickle |
| `Hill'` | derivative `∂hill/∂x_norm` (closed form, batch-vectorized) | computed analytically |

**Acronyms:**

| Term | Expansion | Note |
|------|-----------|------|
| MMM | Marketing Mix Modeling | вся область |
| KPI | Key Performance Indicator | здесь sales OR awareness; future leads/NPS |
| MCMC | Markov Chain Monte Carlo | NUTS sampler через NumPyro JAX backend |
| HDI | Highest Density Interval | Bayesian credible region (asymmetric-correct) — output Bayesian path и Bootstrap |
| CI | Confidence Interval | формально frequentist; в API/UI Aurora имя `ci_low/ci_high` используется и для HDI bounds (legacy compat) — реальная семантика зависит от path (Bayesian → HDI, OLS+conformal → PI half-width) |
| ESS | Effective Sample Size | bulk + tail измеряются отдельно |
| R-hat (Ȓ) | Gelman-Rubin convergence diagnostic | <1.05 well-mixed, ≥1.1 fail |
| BFMI | Bayesian Fraction of Missing Information | energy-based diagnostic |
| VIF | Variance Inflation Factor | multicollinearity threshold |
| ROI | Return On Investment | `contribution_money / spend_money` |
| mROAS | marginal Return On Ad Spend | `∂outcome/∂spend` (chain rule в optimizer) |
| PI | Prediction Interval | Conformal output; шире чем CI на β |
| ADVI | Automatic Differentiation Variational Inference | fallback sampler если NUTS fails |
| HKDF | HMAC-based Key Derivation Function | crypto, не математика модели |

**Concepts:**

- **Adstock** — temporal carry-over медиа-эффекта на следующие периоды. Geometric: instant peak, exponential decay. Weibull: delayed peak (mode > 0), flexible tail.
- **Hill saturation** — diminishing returns S-curve `hill(x) = x^α / (x^α + γ^α)`. Bounded [0, 1].
- **Three-way alignment** — modeler / decomposer / optimizer используют идентичную формулу `β × hill(adstock(x)/mean) × y_std`. Регрессия test предотвращает drift.
- **Conformal** — distribution-free prediction interval (см. [соответствующий раздел](#conformal-prediction-s-ols-1)).

---

## Numerical example end-to-end (synthetic 5-channel)

**Goal:** провести одно наблюдение через весь pipeline на синтетических данных. Каждое промежуточное число зафиксировано — это якорь для понимания и для regression-test.

**Setup:**
- T = 52 weeks, 5 channels: `TV_brand`, `Digital_perf`, `Sponsorship_brand`, `Search_perf`, `OOH_brand`
- KPI = sales, ₽
- Sample week 26 (mid-flight): TV=200k, Digital=80k, Spons=50k, Search=120k, OOH=30k
- True params (synthetic generator):
  - `β = [0.45, 0.32, 0.18, 0.40, 0.12]`
  - `γ = [0.40, 0.30, 0.50, 0.25, 0.35]`
  - `α = [1.5, 1.2, 1.8, 1.0, 1.4]`
  - `θ = [0.65, 0.30, 0.55, 0.20, 0.45]` (geometric decay)
  - `intercept = 0.10`, `σ = 0.15`
  - `y_mean = 8.0M`, `y_std = 1.5M`

### Step 1 — adstock (TV_brand, week 26)

`adstock_t = x_t + θ·adstock_{t-1}` (geometric).

Trace последних 8 недель (raw → adstocked):
```
w19  150k  →  150.0k     (initial)
w20  180k  →  180 + 0.65·150  =  277.5k
w21  220k  →  220 + 0.65·277.5 =  400.4k
w22  150k  →  150 + 0.65·400.4 =  410.3k
w23  100k  →  100 + 0.65·410.3 =  366.7k
w24  180k  →  180 + 0.65·366.7 =  418.4k
w25  200k  →  200 + 0.65·418.4 =  472.0k
w26  200k  →  200 + 0.65·472.0 =  506.8k   ← week 26 adstocked TV
```

### Step 2 — Hill normalization

`mean(adstocked_TV) ≈ 470k` (training mean across 52 weeks, saved в pickle).

`x_norm = adstocked / mean = 506.8k / 470k ≈ 1.078`

### Step 3 — Hill saturation

```
hill = x_norm^α / (x_norm^α + γ^α)
     = 1.078^1.5 / (1.078^1.5 + 0.40^1.5)
     = 1.119 / (1.119 + 0.253)
     = 1.119 / 1.372
     ≈ 0.8156
```

**Interpretation:** TV at week 26 находится на 81.6% saturation — diminishing-returns territory.

### Step 4 — channel contribution (week 26, normalized scale)

`contribution_norm[TV, w26] = β_TV × hill = 0.45 × 0.8156 = 0.367`

Аналогично для остальных 4 каналов (опущено для краткости). Сумма:
```
Σ media_contribution_w26_norm ≈ 0.367 + 0.215 + 0.094 + 0.180 + 0.041 = 0.897
```

### Step 5 — predicted KPI (week 26)

```
y_pred_norm = intercept + Σ media + Σ control
            = 0.10 + 0.897 + 0.0
            = 0.997
y_pred_money = y_pred_norm × y_std + y_mean
             = 0.997 × 1.5M + 8.0M
             ≈ 9.50M ₽
```

### Step 6 — ROI for TV_brand (training period total)

```
total_contribution_TV_norm  = Σ_t β_TV · hill(adstock_t / mean)        ≈ 19.3
total_contribution_TV_money = total_norm × y_std                        = 19.3 × 1.5M = 28.95M ₽
total_spend_TV_money        = Σ_t raw_spend_t × unit_cost               = 8.4M ₽   (unit_cost=1)
ROI_TV = contribution / spend                                            ≈ 3.45×
```

**Verdict (decomposer.compute_roi_verdict):** `ROI=3.45` > `ROI_BREAKEVEN=1.0` AND < `ROI_HIGH_ABS=5.0` → tone='good', label по efficiency_gap (Step 4 fallback в hybrid verdict).

### Step 7 — что делает optimizer

Базовое allocation 8.4M на TV. mROAS:
```
∂y/∂spend_TV = β_TV × Hill'(adstock_avg/mean) × (1/mean) × ∂adstock_avg/∂spend
```
Аналитический расчёт для week-26 sample:
- `Hill'(x=1.078, γ=0.40, α=1.5) = α · γ^α · x^(α-1) / (x^α + γ^α)²`
  = `1.5 · 0.253 · 1.038 / (1.119 + 0.253)²` ≈ `0.394 / 1.882` ≈ **0.209**
- `∂adstock_avg/∂spend_per_period` для θ=0.65, n=52 weeks (closed form `optimizer.py:73-81`):
  `factor = [n - θ·(1-θ^n)/(1-θ)] / [n·(1-θ)]`
  = `(52 - 0.65·(1-0)/0.35) / (52·0.35)`
  = `(52 - 1.857) / 18.2` ≈ **2.76**
  (для θ=0.30 тот же factor ≈ 1.42 — short-memory channel)

mROAS_TV (point) и mROAS_Search (point) сравниваются — если `mROAS_TV > mROAS_Search`, SLSQP сдвигает ₽1 с Search на TV. Итерирует пока все mROAS не выровняются (либо упрутся в bounds). **Точные значения mROAS зависят от посемплированных β** — в каждой итерации оптимизатор использует posterior mean β̂ (или draw-by-draw в full-posterior mode, см. H11).

### Reproducibility

Этот пример НЕ закодирован в test-файле как-есть (numbers округлены для читаемости). Точная numerical recovery — `tools/test_weibull_recovery.py` + Trust 3 regression pin (`tools/test_regression_pin_kagocel.py`).

---

## KPI Registry (v2.0+)

**Module:** `sidecar/econometrica/utils/kpi_registry.py`

**Purpose:** centralize per-KPI configuration (likelihood, hyperpriors, ceiling, baseline drift)
для extensibility (future: leads, NPS, conversions без modeler.py refactor).

**Pattern:**
```python
KPI_REGISTRY = {
    'sales': KPIConfig(
        name='sales', likelihood='normal', ceiling=None,
        brand_mu_logit_prior=(0.7, 0.3),    # Trust 3 frozen
        perf_mu_logit_prior=(-1.4, 0.7),
        ...
    ),
    'awareness': KPIConfig(
        name='awareness', likelihood='logit_normal', ceiling=100,
        brand_mu_logit_prior=(1.4, 0.4),    # ~26wk decay
        ...
    ),
}
```

**Why frozen dataclass:** prevents accidental mutation между runs (defensive).

**Sales values regression-guarded:** `tools/test_kpi_registry.py::test_sales_config_priors_match_trust3_frozen` ensures Trust 3 baseline не drifts.

---

## Awareness KPI Engine (v1.2.0)

**Status:** 🧪 Experimental until A1b real-data validation.

### Why awareness ≠ sales

| Aspect | Sales | Awareness |
|--------|-------|-----------|
| Outcome distribution | Continuous unbounded | Bounded [0, 100] % |
| Likelihood | Normal | logit-Normal (M1) |
| Saturation | Soft Hill asymptote | Hard ceiling at 100% (M4) |
| Baseline | Stationary intercept | GaussianRandomWalk drift (M2) |
| Brand decay | ~12 weeks | ~26 weeks (recall curve) |
| Performance impact | Direct conversion | Indirect echo (~4 weeks) |
| Multicollinearity threshold | VIF > 5 warning | VIF > 10 warning (M5) |

### Likelihood layer (M1 fix)

For bounded outcomes, Normal likelihood predicts <0% или >100% — wrong.

**Fix:** logit-transform before Normal likelihood:
```python
y_logit = log(y / (ceiling - y))
mu_logit = log(y_pred / (ceiling - y_pred))
pm.Normal('y_obs', mu=mu_logit, sigma=σ, observed=y_logit)
```

**Hard cap (numerical stability):**
```python
y_pred_safe = pt.clip(y_pred, 0.01, ceiling - 0.01)
```

### Baseline drift (M2 fix)

Awareness has long memory (campaigns 6 months ago affect today). Single intercept assumes stationary mean — wrong для real awareness data.

**Fix:** Gaussian random walk component:
```python
drift_sigma = pm.HalfNormal('drift_sigma', sigma=0.1)
baseline_drift = pm.GaussianRandomWalk('baseline_drift', sigma=drift_sigma, shape=T)
y_pred = intercept + baseline_drift + media_contribution + control_contribution
```

### Temporal aggregation (M3 fix)

Brand tracker waves typically every 2-3 months. MMM на weekly media → temporal mismatch.

**Modes:**
- `'wave'`: masked likelihood (only observation weeks contribute)
- `'monthly_interpolated'`: linear interp между waves → continuous series (default)
- `'weekly_estimate'`: caller provides weekly directly

### Hill saturation для awareness (M4 fix)

Awareness saturation hard ceiling at 100%, не soft asymptote. Tighter γ + steeper n.

```python
# KPI_REGISTRY['awareness']:
gammas_alpha=2.0, gammas_beta=5.0  # Beta(2, 5), mean=0.286 (early saturation)
# vs sales: Beta(3, 3), mean=0.5 (mid-saturation)
```

### Multicollinearity (M5 fix)

Brand activities highly correlated (TV + sponsorship + PR). Awareness attribution harder than sales.

**Fix:** VIF check в Validate step. Warning threshold:
- Sales: VIF > 5
- Awareness: VIF > 10 (allow more collinearity given inherent brand activity overlap)

### Decay calibration

`KPI_REGISTRY['awareness']`:
- brand_mu_logit_prior=(1.4, 0.4) → sigmoid≈0.80 → ~26wk effective duration
- perf_mu_logit_prior=(-0.7, 0.5) → sigmoid≈0.33 → ~3wk

«Effective duration» = ~1% remaining (см. footnote¹ в Trust 3 section). Строгий half-life для θ=0.80 = `log(0.5)/log(0.80) ≈ 3.1 wk`.

**Note:** Starting calibration. A1b real-data validation refines per-vertical (FMCG vs B2B vs healthcare may differ).

---

## Weibull Learnable Adstock (v1.2.0)

**Status:** Phase B implementation in progress.

### Why learnable Weibull

Geometric adstock = instant peak, exponential decay (`x_t + decay × x_{t-1}`). Adequate для most digital channels (peak in week 0).

Weibull adstock = delayed peak (mode at week N>0), flexible tail. Critical для:
- TV ad recall (peak weeks 2-4 после exposure)
- Sponsorship/PR (delayed brand response)
- Awareness build-up (long horizon)

Pre-v1.2.0: Weibull pre-computed с hardcoded `decay=0.5` (modeler.py:451-453). Не adaptive к data.

### Reparameterization (H7 fix)

Standard Weibull (λ scale, k shape) suffers identifiability — на small/noisy data близкие likelihood-ы между «exponential-like» (k≈1) и «delayed-peak» (k>1) regimes → posterior bimodal или ridge-degenerate. Подробности и точный signature см. [Identifiability appendix](#identifiability-appendix--weibull-peak_week-tail_decay-reparam).

**Fix:** reparameterize as `(peak_week, tail_decay)`:
- `peak_week`: where Weibull peaks (mode). Interpretable: «эффект достигает пика на N-й неделе».
- `tail_decay`: tail rate (Beta-like 0..1). Interpretable: «насколько быстро затухает хвост».

**Conversion (closed-form):**
```python
k = 1.0 + 1.0 / max(tail_decay, 0.05)   # tail_decay → k
lam = peak_week / ((k - 1) / k) ** (1.0 / k)  # mode → λ (для k > 1)
```

**Design constraint — k всегда ≥ 2:**
- При `tail_decay = 1` (Beta-max): `k = 1 + 1/1 = 2` (Rayleigh, минимум)
- При `tail_decay → 0` (floored at 0.05): `k → 1 + 1/0.05 = 21` (sharp peak, максимум)
- ⇒ Weibull learnable mode **всегда** имеет delayed peak (mode > 0) и tail decays sub-exponentially fast.
- **Не подходит** для каналов с instant peak (digital perf) — там use `adstock_type='geometric'`.
- Обоснование: учитываемая семантика «зачем нужен Weibull» = TV/Sponsorship с физической задержкой эффекта; geometric покрывает k=1 случай отдельно.

**Hyperpriors:**

| Mode | peak_week prior | tail_decay prior |
|------|-----------------|------------------|
| Sales | HalfNormal(σ=4) | Beta(2, 8), mean=0.2 |
| Awareness | HalfNormal(σ=8) | Beta(2, 12), mean=0.14 (slower tail) |

### Discrete kernel via survival function (H8 fix)

PDF discretization at integer weeks loses probability mass (integration error).

**Fix:** survival function differences:
```python
S(t) = exp(-(t/λ)^k)
kernel[t] = S(t) - S(t+1)   # accurate discrete probability mass
kernel_normalized = kernel / sum(kernel)   # identifiability — sum=1
```

### Convolution implementation (H6 fix)

❌ **Wrong:** `pt.signal.conv.conv2d` — designed для image 2D convolution, API mismatch.
✅ **Right:** Toeplitz matrix multiplication.

```python
# Precomputed indices outside scan (one-time setup):
T = X.shape[0]
idx = pt.maximum(0, pt.arange(T)[:, None] - pt.arange(T)[None, :])
mask = (pt.arange(T)[:, None] >= pt.arange(T)[None, :]) & (idx < max_decay)

# Per-draw (cheap):
M = pt.where(mask, kernel_normalized[idx], 0.0)
X_adstock = pt.dot(M, X)
```

**Adaptive max_decay (H9):**
```python
max_decay = min(T // 4, 52)
```

### JAX mandatory (H10)

Toeplitz convolution в pt.scan на CPU = unbearable MCMC time.
Required: `jax + numpyro` installed. Check enforced by `utils/backend_check.enforce_jax_for_weibull()`.

If unavailable → `BackendUnavailableError` with actionable hint (install command или channel switch).

### Warm-start MLE (R2)

Cold-start MCMC convergence slow на high-dimensional Weibull params.

**Fix:** Initialize via scipy MLE estimate:
```python
from scipy.stats import weibull_min

adstocked_default = apply_geometric_default(X[col], decay=0.5)
init_lam, init_k = weibull_min.fit(adstocked_default)
initvals[f'weibull_peak_week_{col}'] = lam_to_peak_week(init_lam, init_k)
```

Speeds MCMC convergence 2-3× (target measurement в B4.3 benchmark).

### Optimizer chain rule (B2.5 simplification)

Linearity wrt spend gives clean derivative:
```
∂adstock_avg / ∂spend = sum(kernel_normalized) = 1.0  (since normalized)
∂outcome / ∂spend = β × Hill'(adstock_avg) × 1.0
```

**Same complexity as geometric.** No numerical central diff needed.

### Per-draw vs posterior mean trade-off (H11)

| Mode | When | Speed |
|------|------|-------|
| Posterior mean | Interactive optimization sliders | Fast (10× speed-up) |
| Full per-draw | Final acceptance test | Accurate (full uncertainty) |

UI toggle «Use full posterior» для accuracy mode.

### Recovery acceptance criteria (B4.1)

Synthetic recovery test (`tools/test_weibull_recovery.py`):
- True params: peak_week=3, tail_decay=0.5
- Recovered: peak_week ±1 week, tail_decay ±20%
- R-hat<1.05 для both hyperparameters

### Performance benchmarks (B4.3)

To be measured:

| Setup | Channels | All Geometric | 50% Weibull | All Weibull |
|-------|----------|---------------|-------------|-------------|
| MCMC wall-clock | 5 | TBD | TBD | TBD |
| MCMC wall-clock | 10 | TBD | TBD | TBD |
| MCMC wall-clock | 20 | TBD | TBD | TBD |
| ESS/sec | varies | TBD | TBD | TBD |

Threshold: if >3× slower → UI warning.

---

## Trust Level 3 Hierarchical Brand/Performance (v1.1.0)

**Status:** Shipped 2026-04-27. **Frozen** через KPI_REGISTRY['sales'].

См. `docs/MATH_AUDIT_v1_6_BRAND_PERFORMANCE_SPLIT.md` (legacy ref). Constants migrated к KPI_REGISTRY.

Hierarchical priors (modeler.py:408-411 → KPI_REGISTRY['sales']):
- `brand_mu_logit ~ Normal(0.7, 0.3)` → sigmoid≈0.67 → ~12 wk effective duration¹
- `perf_mu_logit ~ Normal(-1.4, 0.7)` → sigmoid≈0.20 → ~1.3 wk
- `mixed_mu_logit ~ Normal(-1.4, 0.7)` (semantic compat)

> ¹ **Convention note:** «half-life» в коде/комментариях Aurora обозначает «время, за которое impulse response падает до ~1% peak» (effective contribution duration, MMM-domain heuristic), НЕ строгий period-of-half-decay. Строгий half-life для θ=0.67 = `log(0.5)/log(0.67) ≈ 1.7 wk`; для θ=0.80 ≈ 3.1 wk. Цифры 12 wk / 26 wk соответствуют ~1% remaining (`log(0.01)/log(θ)`). Это унаследованная convention из kpi_registry.py:73 + modeler.py:405 — НЕ менять без широкого audit (имена в комментариях используются повсюду).

Group-conditional sigma (modeler.py:367-369):
- brand: HalfNormal(0.7) wider
- perf: HalfNormal(0.3) tighter
- mixed: HalfNormal(0.4)

Non-centered z-reparam: `betas = sigma_per_channel × z` — avoid funnel на small N.

R-hat gate threshold = 1.1 (Bayesian standard).

---

## Phase 1.1 Adstock decay sampling (v1.0.13+)

logit-normal parameterization для per-channel decay (35% faster, R-hat 1.000 vs 1.020 geometric, ESS 5× better).

```python
adstock_sigma_logit = pm.HalfNormal('adstock_sigma_logit', sigma=1.0)
adstock_z = pm.Normal('adstock_z', mu=0.0, sigma=1.0, shape=len(media_cols))
adstock_decay = pm.Deterministic(
    'adstock_decay',
    pm.math.sigmoid(mu_vec + adstock_sigma_logit * adstock_z),
)
```

---

## Hill saturation normalization (v1.0.12+)

Hill curve: `saturated = x^α / (x^α + γ^α)` (S-curve).

**Pre-v1.0.12 bug:** z-score normalization → γ in negative range, broke saturation interpretation.

**Fix (Robyn-style):** spend / mean(spend) normalization. γ stays in [0, 1]. Documented в `docs/MATH_AUDIT_v1_3_PHASE_0_1.md`.

`gammas ~ Beta(3, 3)` (modeler.py:389) — frozen в KPI_REGISTRY['sales'].

---

## Decomposer (downstream extraction)

**Module:** `sidecar/econometrica/engines/decomposer.py`

### Per-period contribution (Phase 3 — P0-3/4/10 fix)

Pre-v1.0.13 bug: `contribution = |β|/Σ|β| × (total - baseline)` — игнорировал adstock, saturation, time. Post-fix честная формула:

```python
contribution_per_period[c, t] = β_c × hill(adstock_c[t] / mean_c, γ_c, α_c) × y_std
```

**Identity (по построению):**
```
baseline_per_period[t] + Σ_c contribution_per_period[c, t]
    == y_pred_per_period[t] × y_std + y_mean
```

### Baseline reconstruction

```python
baseline_per_period[t] = intercept × y_std + y_mean + control_effect[t] × y_std
```

`y_mean` присутствует как additive term, не multiplicative — это исправление P0-10 (раньше `+ 0.3 × predicted.mean × n` создавал double-counting).

### ROI verdict (hybrid 4-step, post-L2 refactor 2026-04-29)

`compute_roi_verdict()` ordering:

1. **Wide-CI flag** (computed first, applied as suffix at end):
   - if `roi > 0` AND `(roi_ci_high - roi_ci_low) > roi` → флаг `wide_ci=True`
   - в финале suffix `« (низкая уверенность)»` плюс tone='warn' если был 'good'
   - **Pre-L2 bug:** wide CI блокировал ВСЕ informative labels на small-N → user не видел "Перенасыщен" / "Высокоэффективен". Post-L2: descriptive verdict + honest CI disclosure suffix.

2. **Absolute hard caps** (regardless of category):

| Condition | Verdict | Tone |
|-----------|---------|------|
| `roi > 50` AND `unit_smell` | "ROI завышен (не рубли?)" | warn |
| `roi > 100` | "ROI нереалистичен (артефакт)" | warn |
| `roi < 0.5` | "Глубоко убыточный" | bad |
| `roi < 0.8` | "Убыточный" | bad |
| `roi < 1.0` | "На грани окупаемости" | warn |

3. **Category-relative quantile** (только если `n_channels ≥ 20` AND portfolio quantiles доступны).

4. **Efficiency gap fallback** — `share_of_effect - share_of_spend` (пп):
   - gap < -10 → перенасыщен
   - gap < -5 → слабее своей доли
   - gap > +10 → высокоэффективен
   - gap > +5 → эффективен

### Frozen constants (decomposer.py:29-39)

```python
ROI_DEEP_LOSS=0.5  ROI_LOSS=0.8  ROI_BREAKEVEN=1.0  ROI_HIGH_ABS=5.0
ROI_UNIT_SMELL_FLOOR=50.0  ROI_ARTIFACT=100.0
GAP_OVERSAT=-10.0  GAP_UNDER=-5.0  GAP_HIGH=10.0  GAP_GOOD=5.0
QUANTILE_MIN_N=20
```

Calibration sources документированы в `docs/ROI_THRESHOLDS.md`.

---

## Optimizer (SLSQP + chain rule)

**Module:** `sidecar/econometrica/engines/optimizer.py`

### Chain rule for mROAS (F0.2 fix, Phase 0.1)

**Money-scale (`mROAS` ≡ `∂y_money/∂spend_money`):**
```
mROAS = y_std × β × Hill'(adstock_avg/mean, γ, α) × (1/mean) × ∂adstock_avg/∂spend
```

**Normalized-scale (`∂y_norm/∂spend`, internal computation):**
```
∂y_norm/∂spend = β × Hill'(adstock_avg/mean, γ, α) × (1/mean) × ∂adstock_avg/∂spend
```

Множитель `y_std` нужен для перехода из z-score y_norm обратно в money. `y_mean` отсутствует в derivative (это additive constant, исчезает при дифференцировании).

Где:
- `Hill'(x, γ, α) = α · γ^α · x^(α-1) / (x^α + γ^α)²` — closed form, batch-vectorized в `utils/saturation.hill_derivative_batch`
- `∂adstock_avg/∂spend` для **geometric** (closed form, `optimizer.py:73-81`):
  ```
  factor = [n - θ·(1 - θ^n) / (1 - θ)] / [n · (1 - θ)]
  ```
  Это **constant в spend** — линейный adstock. Безопасно вынести из inner loop.
- для **weibull** (после нормализации `Σ kernel = 1`): `factor = 1.0` (fall-back на central diff если decay недоступен)
- для **noop / none**: `factor = 1.0`

**Boundary guards:**
- `0 < θ < 1` enforced — иначе fallback `factor=1.0`.
- `n_periods < 1` → `factor = 0.0`.

### Flat allocation assumption

Optimizer оперирует с total spend per channel (scalar), Hill ожидает per-period adstocked. Compromise: `raw_t = total / n_periods` повторяется → adstocked → mean. Семантически совпадает с тем, что Hill видел в training (если данные близки к stationary). Формальное обоснование `docs/MATH_AUDIT_v1_3_PHASE_0_1.md §4`.

### SLSQP setup

- **Equality constraint:** `Σ_c spend_c = total_budget` (если задан)
- **Inequality constraints:**
  - `channel_min[c] ≤ spend_c ≤ channel_max[c]`
  - per-group (Trust 3+): `brand_min/max`, `perf_min/max` — resolved через `utils/optimizer_constraints.resolve_channel_bounds()` (3-level precedence: per-channel > per-group > global)

### Per-draw vs posterior mean (H11)

| Mode | When | Speed | Output |
|------|------|-------|--------|
| Posterior mean | Interactive sliders, real-time UI | Fast (1 SLSQP run) | point estimate |
| Full per-draw | Final acceptance + uncertainty band | 100-500× slower (~1000 SLSQP runs) | distribution + HDI |

UI toggle "Use full posterior" для accuracy mode. Default = posterior mean.

---

## Conformal Prediction (S-OLS-1)

**Module:** `sidecar/econometrica/utils/conformal.py`

Aurora — единственный коммерческий MMM-инструмент с distribution-free prediction intervals на OLS path.

**OLS path triggering** (`ols_modeler.py`):
- `n < 20` — strict OLS only (Bayesian unreliable, refused)
- `20 ≤ n < 30` — user choice (default OLS, Bayesian opt-in)
- `n ≥ 30` — Bayesian default (но user может явно выбрать OLS)

**Conformal variants** (auto-selected внутри `conformal_intervals_auto`, ortogonально OLS-path triggering):

```
n < 30   →  jackknife        # plain LOO residual quantile
n ≥ 30   →  split_conformal  # 70/30 train/calibration split
```

В практике large-N (`n ≥ 30`) split_conformal используется когда user явно opt-in'ил OLS на больших данных.

### Split-conformal procedure

1. Случайное разделение: train (70%) + calibration (30%)
2. OLS fit на train: `β̂ = (X_train' X_train)⁻¹ X_train' y_train`
3. Predict на calibration → `|residuals|`
4. Compute `q_index`:
   - `q_index = ⌈(n_cal + 1) · (1 - α)⌉`
   - `q_index = clip(q_index, 1, n_cal)` (safety bounds — small-N edge cases где формула выдаёт q_index > n_cal)
5. `half_width = sort(|residuals|)[q_index - 1]`
6. PI для нового x_test: `ŷ_new ± half_width`

**Empirical coverage** на calibration set возвращается как sanity-check (должен быть ≈ 1-α).

### Coverage caveats (F2 + F3 honest disclosure)

`conformal.py` экспортирует обе оговорки в UI/report — это **обязательная** часть positioning.

**F3 — exchangeability violated:**
Conformal coverage `P(y ∈ PI) ≥ 1-α` гарантирована **только** при exchangeable training+test. Marketing time-series (тренд + сезонность + regime changes) → exchangeability нарушена. Vanilla split-conformal coverage **не математически гарантирована** на non-stationary данных. Empirically работает после adstock+Hill снимают autocorrelation, но без formal guarantee.

**F2 — plain jackknife (NOT jackknife+):**
`jackknife_intervals` возвращает один симметричный `half_width`, а не test-point-dependent intervals из Barber 2021. **Plain jackknife не имеет finite-sample coverage guarantee** в общем случае (Barber 2021 §1.1). Эмпирически разумно на stationary residuals — useful как honest small-N alternative к split, но без 1-2α math guarantee.

**Aurora positioning (post-audit revision 2026-04-27):**
> "honest distribution-free PI с calibration evidence на marketing data + clear caveats про exchangeability и plain-jackknife semantics" — НЕ "math-guaranteed coverage".

Real guarantee требует weighted/block conformal + true jackknife+ (Sprint 4+ enhancement).

### Insufficient-N guards

```python
if n < 12:           return None, reason='insufficient_data'
if n_cal < 4:        return None, reason='cal_too_small'
if singular_train:   return None, reason='singular_train'
```

UI показывает honest reason — не молчит и не возвращает фантомные intervals.

### References (encoded в коде)

- Vovk, Gammerman, Shafer 2005 *Algorithmic Learning in a Random World*
- Angelopoulos, Bates 2021 *A Gentle Introduction to Conformal Prediction* (arXiv:2107.07511)
- Lei, G'Sell, Rinaldo, Tibshirani, Wasserman 2018
- Barber, Candes, Ramdas, Tibshirani 2021 *Predictive inference with the jackknife+*
- Barber, Candes, Ramdas, Tibshirani 2022 *Conformal prediction beyond exchangeability*

---

## Bootstrap ROI CI (small-N OLS path)

**Module:** `sidecar/econometrica/utils/ols_bootstrap.py`

Frequentist β CI (`β ± t·SE`) ≠ ROI CI. Hill non-linearity + ratio амплифицирует/дампит β uncertainty в ROI bounds. Bootstrap закрывает gap.

### Procedure

```
for i in 1..N (default N=200):
    resample (X_i, y_i) with replacement from training
    refit OLS: β_i = (X_i' X_i)⁻¹ X_i' y_i
    compute ROI_i per channel (post-C-OLS-1 fix — real per-period):
        contribution_per_period_i[t] = β_i · hill(adstock_t / mean, γ, α) · y_std
        contribution_total_i = Σ_t contribution_per_period_i[t]
        ROI_i = contribution_total_i / (raw_spend_total · unit_cost)
HDI bounds: compute_ci_hdi(ROI_distribution, prob=0.9)
```

### Critical fixes (audit 2026-04-27)

- **C-OLS-1:** real per-period adstock+Hill в bootstrap (matches decomposer exactly). Pre-fix: `hill_at_one ≈ hill(1.0)` constant approximation создавала Jensen's-inequality bias 10-30% drift между bootstrap CI и decomposer point estimate. UI показывал "ROI 2.4 [bootstrap 1.5—2.0]" где 2.4 outside CI — confusing.
- **C-OLS-2:** explicit success mask — `LinAlgError` iterations не загрязняют percentile нулями.
- **M-OLS-1:** возврат HDI bounds (asymmetric-correct через `compute_ci_hdi`) вместо raw percentile — semantic parity с Bayesian path.

### Cost

~5–30 sec для n=18, 5 channels. Acceptable: 1-сек training + 30-сек CI = honest small-data analysis.

### Reference

Efron 1979 *Bootstrap methods* — стандартная frequentist альтернатива Bayesian posterior CI на small N.

---

## Numerical stability & edge cases

Один реестр всех guard'ов и где они применяются. Каждый защищает от наблюдённого ранее бага — не теоретическая paranoia.

### Logit transform (awareness mode)

```python
y_safe = pt.clip(y, 0.01, ceiling - 0.01)       # log(0) и log(neg) защита
y_logit = pt.log(y_safe / (ceiling - y_safe))
```

`y=0` или `y=ceiling` без clip → ±∞ в logit → MCMC divergence на первой итерации.

### Hill saturation (zero spend / zero mean)

```python
x_norm = adstocked / max(mean, 1e-9)              # mean=0 канал-данных
hill = x_norm**α / (x_norm**α + γ**α + 1e-12)     # γ=0 edge защищён
```

В HTML report ранее ловили `media_mean=0 → NaN propagation` (Sprint 5 post-audit, commit `b68cf5b` 2026-04-27). Защита: 5 div-by-zero guards в `what_if.js`.

### Geometric adstock (boundary θ)

```python
if not (0.0 < θ < 1.0):
    return 1.0   # adstock factor degenerate — treat как noop
```

θ=0 — нет переноса, θ=1 — бесконечная память (numerical instability в long horizon).

### Conformal (insufficient N)

См. соответствующий раздел — `n<12`, `n_cal<4`, `singular_train` обрабатываются явно.

### Weibull discretization

```python
kernel[t] = S(t) - S(t+1)
kernel /= sum(kernel)   # identifiability + защита от integration drift
```

### MCMC sampler chain (auto-fallback)

```
numpyro_jax (primary) → pymc_nuts → ADVI → ERROR
```

**Metropolis-Hastings явно ИСКЛЮЧЁН** — на Adstock+Hill geometry даёт `R-hat > 2.0` (false-green выводы). Explicit comment `modeler.py:484`: «Adstock/Hill он даёт r_hat > 2.0 (ложный зелёный результат…)».

### Pickle version comparison

`_parse_version()` парсит `'X.Y'`/`'X.Y.Z'` → tuple. Защищает от lex-compare bug (`'1.10' < '1.3'` ложно `True` при string compare). `'1.0-ols'` обрабатывается отдельно через regex.

---

## Prior predictive check (sanity gate)

**Что:** до увидения данных запустить N сэмплов из priors, посчитать predicted KPI distribution → проверить реалистичность.

**Зачем:** обнаруживает абсурдные prior choices (например `β ~ Normal(0, 100)` → predictions ±1000% от реальности).

**Recommended pattern (TODO Sprint 4+, пока не enforced):**

```python
with model:
    prior_samples = pm.sample_prior_predictive(samples=1000)

y_pred_prior = prior_samples.prior_predictive['y_obs'].values

# Sanity assertions для awareness:
assert np.percentile(y_pred_prior, 5)  > 0       # ≥ 0 awareness
assert np.percentile(y_pred_prior, 95) < 100      # ≤ ceiling
# Sanity для sales:
assert np.std(y_pred_prior) < 5 * np.std(y_observed)  # not absurdly diffuse
```

**Status (2026-04-28):** не integrated в pipeline. Priors validated через:
- `test_kpi_registry.py::test_sales_config_priors_match_trust3_frozen` — frozen-values regression guard
- `test_regression_pin_kagocel.py` — synthetic pickle hash drift detection

Полноценная prior predictive simulation — задача Z (post-ship telemetry/regression) в плане.

---

## Diagnostics gate (ship vs warn vs info)

| Diagnostic | Threshold | Action | Source |
|------------|-----------|--------|--------|
| `R-hat` (any param) | > 1.1 | **BLOCK ship** — return error, recommend longer chains | Gelman-Rubin 1992 (legacy convention) |
| `R-hat` (Trust 3 hyperparameters) | > 1.05 | **WARN UI** — `hierarchical_rhat_warning` field | modeler.py:670 |
| `R-hat` (any param) | 1.05 – 1.10 | **INFO** — show в diagnostics panel | convention |
| `divergent transitions` | > 5% draws | **WARN** — recommend reparam (z-score non-centered already applied) | NUTS standard |
| `ESS_bulk` | < 400 | **WARN** — chains недостаточно informative | Vehtari et al. 2021 |
| `ESS_tail` | < 400 | **WARN** — extreme quantiles unreliable | Vehtari et al. 2021 |
| `BFMI` | < 0.3 | **WARN** — energy mismatch, posterior geometry hard | Betancourt 2018 |
| Posterior predictive p-value | < 0.05 OR > 0.95 | **INFO** — model misspecification suspect | convention |

> **Note on R-hat threshold:** Vehtari et al. 2021 ("Rank-normalization, folding, and localization") recommends **stricter R-hat < 1.01** для improved Ȓ statistic. Aurora использует более lenient `1.1` (Gelman-Rubin 1992 historical convention), что разумно для production MMM где occasionally noisy posteriors допустимы. Sprint 4+ enhancement: tighten к 1.01 после real-world coverage validation.

### Why R-hat=1.1 is BLOCK (not WARN)

На практике observed: NUTS, который не сходится к R-hat<1.1 на Aurora's Hill+Adstock geometry — либо чистый bug в data, либо catastrophic prior mismatch. **Honest "model refused to train"** > silent fallback с garbage output (это и есть Aurora competitive moat vs Robyn / LightweightMMM).

### Why Metropolis-Hastings banned

См. modeler.py:484 explicit comment. На Adstock+Hill MH даёт `R-hat > 2.0` с false-green output. Если NUTS+ADVI оба падают — лучше honest error чем фантомные результаты.

### Hierarchical-specific gate (Trust 3)

`per_param_rhat` отдельно для `mu_logit_brand`, `mu_logit_perf`, `sigma_brand`, `sigma_perf`, `mu_logit_mixed` — если max > 1.05 → `hierarchical_rhat_warning` к UI. Tier-1 standard для hierarchical models.

---

## Identifiability appendix — Weibull (peak_week, tail_decay) reparam

### Problem (standard λ, k parameterization)

Posterior bimodal на small-N с noisy data: типичный сценарий — данные weakly differentiate между «exponential-like» (k≈1, monotone decay) и «delayed-peak» (k>1, mode at week N>0) regimes. Например `(λ=8, k=1.0)` и `(λ=4, k=1.6)` могут давать сопоставимый likelihood на T<26 — MCMC одинаково часто выбирает оба моды → **ESS обвал**, `R-hat > 1.5`.

Verifiable signature: trace plot `λ` или `k` показывает chain-jumping между двумя clusters. Posterior pair-plot `(λ, k)` → bimodal blobs (не один компактный сгусток).

Кроме того: ridge identifiability — `λ ↑ + k ↓` одновременно сохраняют похожий kernel shape (есть направление в (λ,k) plane вдоль которого likelihood плоский) → posterior degenerate ridge даже когда unimodal.

### Solution

Reparameterize в interpretable space:
- `peak_week ~ HalfNormal(σ=4)` — мода kernel («когда эффект максимален»)
- `tail_decay ~ Beta(2, 8)` — скорость затухания хвоста (Beta-mean 0.2)

Conversion (closed-form):
```python
k = 1.0 + 1.0 / max(tail_decay, 0.05)
λ = peak_week / ((k - 1) / k) ** (1.0 / k)   # для k > 1; mode formula
```

### Why это работает (intuition)

- `peak_week` имеет **глобальный smooth one-to-one mapping** к kernel mode → unimodal posterior на parameter of interest.
- `tail_decay ∈ (0, 1]` ограничен → исключает k<1 (monotone decreasing kernel — ad recall не растёт с задержкой → physically implausible).
- Joint prior `(peak_week, tail_decay)` — unimodal по построению → posterior unimodal под weakly identified data.

### Verification (TODO B4)

- **Recovery test (B4.1):** synthetic true `(peak=3, decay=0.5)` → recovered `peak ± 1 week`, `decay ± 20%`, `R-hat < 1.05`. Acceptance gate.
- **Bimodal stress test:** генерить data с **двумя истинными modes** (peak=2,decay=0.8) AND (peak=4,decay=0.3) → проверить что posterior НЕ bimodal (если bimodal — reparam не справился, fallback на (λ, k) с stronger prior).
- **Trace plots:** все Weibull params должны показать stable chains после warmup, без jumping.

---

## Pickle migration runbook

**Module:** `sidecar/econometrica/engines/persistence.py`

### Version ladder (canonical)

| Version | Released | Schema additions | Compat |
|---------|----------|------------------|--------|
| `1.0` | initial | base fields | rejected by decomposer guard (`MODEL_OUTDATED`) |
| `1.0-ols` | Sprint 2 | small-data fallback (point estimates, no posterior CI) | accepted, OLS path |
| `1.1` | v1.0.13 | spend/mean Hill normalization (был z-score) | full pipeline |
| `1.1.1` | Phase 1.1 | hierarchical adstock decay (logit-normal, sampled per channel) | full pipeline |
| `1.2` | v1.0.16 | post-audit fixes, three-way alignment | full pipeline |
| `1.3` | v1.1.0 (Trust 3) | `channel_categories` field | brand/perf split UI |
| `2.0` | v1.2.0 (dev) | additive optional: `kpi_type`, `kpi_likelihood`, `awareness_aggregation_mode`, `channel_adstock_types`, `weibull_params_per_channel`, `comparison_baseline_posterior`, `feature_flags_used` | awareness + Weibull |

### Load contract — `load_model_with_compat()`

При загрузке всегда инжектируются defaults (persistence.py:72-82):
```python
model_data.setdefault('model_version', '1.0')             # legacy
model_data.setdefault('channel_categories', {})           # pre-Trust3
model_data.setdefault('kpi_type', 'sales')                # pre-v2.0
model_data.setdefault('kpi_likelihood', 'normal')
model_data.setdefault('awareness_aggregation_mode', None)
model_data.setdefault('channel_adstock_types', {})        # default per-channel = geometric
model_data.setdefault('weibull_params_per_channel', {})
model_data.setdefault('comparison_baseline_posterior', None)
model_data.setdefault('feature_flags_used', [])
```

### Save policy

- Новые pickle всегда пишутся с **актуальной** `model_version` после успешного training.
- **Старые pickle на диске НЕ upgrade'ятся автоматически** — defaults injected в memory, но read-only artifact preserves original. Защищает от accidental corruption на shared storage.
- Implicit upgrade происходит только когда user открывает старый проект и запускает Save (modeler.py пишет с current schema).

### Version comparison helper

`_parse_version(s)` — regex `(\d+)\.(\d+)(?:\.(\d+))?` → `(major, minor, patch)` tuple.

**Why explicit parser:** string `<` comparison broken — `'1.10' < '1.3'` лексикографически True (audit fix). Также legacy `'1.0-ols'` обрабатывается через `_VERSION_RE.match` (берёт первое числовое совпадение).

### Decomposer/Optimizer rejection rules

- `decomposer.py` отклоняет `model_version < '1.1'` → returns `MODEL_OUTDATED` error → UI шлёт user retrain.
- `optimizer.py` принимает `>= 1.1` (с graceful fallback на `decay=0.5` если `< 1.1.1`).
- `narrative_adapter.py` версия-aware для Trust 3 sections (skip brand/perf split если `< 1.3`).

---

## Literature & industry comparison

### Where Aurora aligns с Robyn / LightweightMMM / Meridian

- **Hill saturation + geometric adstock** — ядро всех трёх. Aurora использует тот же functional form.
- **spend/mean normalization** — Robyn-style. Aurora migrated в v1.0.12 после z-score bug (см. `MATH_AUDIT_v1_3_PHASE_0_1.md`).
- **Hierarchical priors** — LightweightMMM группирует channels; Aurora Trust 3 эквивалент.
- **NumPyro JAX backend** — LightweightMMM default; Aurora primary с v1.0.9 (190s → 20s training, 9.5× speedup).

### Where Aurora differs (positioning moat)

| Feature | Aurora | Robyn | LightweightMMM | Meridian |
|---------|:------:|:-----:|:--------------:|:--------:|
| Distribution-free PI (Conformal) | ✅ S-OLS-1 | ❌ | ❌ | ❌ |
| Bootstrap ROI HDI (small-N OLS) | ✅ | ❌ | ❌ | ❌ |
| Pre-MCMC reliability gate | ✅ Sprint 1 | ❌ | ❌ | ❌ |
| Brand vs Performance hierarchical split | ✅ Trust 3 | ⚠️ partial | ❌ | ✅ |
| Awareness KPI engine | 🚧 v1.2.0 dev | ❌ | ❌ | ❌ |
| Weibull learnable adstock (in-MCMC) | 🚧 v1.2.0 dev | ⚠️ pre-computed | ❌ | ⚠️ pre-computed |
| Honest "model refused to train" | ✅ Metropolis ban | ❌ silent fallback | ❌ | ❌ |
| Three-way alignment (modeler/decomposer/optimizer) | ✅ regression-pinned | ⚠️ manual | ⚠️ manual | ✅ |

### Key references (academic)

- **Jin et al. 2017** "Bayesian methods for media mix modeling" (Google) — Hill+adstock baseline
- **Chan, Perry 2017** "Challenges and opportunities in MMM" — hierarchical priors motivation
- **Vehtari et al. 2021** "Rank-normalization, folding, and localization: An improved Ȓ" — наш R-hat
- **Jin et al. 2023** "Meridian: Geo-level MMM" (Google) — geo extension (Aurora не имеет; вне scope)
- **Bahadori et al. 2024** "End-to-end MMM with deep learning" — alternative parametric form (вне scope)
- **Barber et al. 2021/2022** — conformal prediction theory (см. соответствующий раздел)
- **Efron 1979** — bootstrap (см. соответствующий раздел)

---

## Versioning policy для самого документа

### Lifecycle

- **Living doc** — math правда as-of HEAD. Изменения встраиваются вместе с code change в same commit.
- **Per-release snapshot** — git tag (`v1.x.x`) фиксирует state. Откат: `git checkout <tag> -- docs/MATH_REFERENCE.md`.
- **Section versioning** — каждый major раздел помечен `(vX.Y.Z)` в заголовке. При breaking math change → новый heading, старое в `## Legacy` block если still relevant for archival pickles.

### Update protocol

1. Math change в коде → одновременный update раздела в этом файле (same commit).
2. Если added new section → добавить entry в TOC (top of file).
3. Cross-link к code (`module.py:line`) и к relevant test file.
4. Update `**Last updated:**` line at top.
5. Commit с `docs:` prefix → не triggers automation, но облегчает grep-history.

### Sprawl prevention (E5 fix)

Эта doc заменяет `MATH_AUDIT_v1_*.md` series. Старые audit-doc оставлены как git artifacts — НЕ редактируются.

`docs/` содержит **только**:
- `MATH_REFERENCE.md` (этот файл) — single source of truth
- `ROI_THRESHOLDS.md` — calibration sources для constants в decomposer
- per-release `CHANGELOG_vX.Y.Z.md`
- per-feature ADR (например `SPRINT3_PHARMA_CAUSAL_ADR.md`)

**НЕ создавать** `MATH_AUDIT_v1_8.md` или подобное. Findings → MATH_REFERENCE update.

### Relationship с CHANGELOG

CHANGELOG отвечает на вопрос «**что изменилось**» (user-facing).
MATH_REFERENCE отвечает на вопрос «**как это считается сейчас**» (developer/auditor-facing).
ADR отвечает на вопрос «**почему этот выбор**» (architectural rationale).

---

## References

- Plan: `~/.claude/plans/bright-wandering-neumann.md`
- Status: `D:/Docs/Aurora_Ai/Awareness_KPI_track_Weibull_Adstock.md`
- Code:
  - `sidecar/econometrica/engines/modeler.py` (main MCMC)
  - `sidecar/econometrica/engines/decomposer.py` (downstream extraction + ROI verdict)
  - `sidecar/econometrica/engines/optimizer.py` (SLSQP + chain rule)
  - `sidecar/econometrica/engines/ols_modeler.py` (small-N OLS path)
  - `sidecar/econometrica/utils/kpi_registry.py` (KPI configs)
  - `sidecar/econometrica/utils/backend_check.py` (JAX availability)
  - `sidecar/econometrica/utils/conformal.py` (S-OLS-1 distribution-free PI)
  - `sidecar/econometrica/utils/ols_bootstrap.py` (Bootstrap ROI HDI)
  - `sidecar/econometrica/utils/optimizer_constraints.py` (per-group bounds)
  - `sidecar/econometrica/utils/adstock.py` (geometric + Weibull math layer)
  - `sidecar/econometrica/utils/saturation.py` (Hill + derivative)
  - `sidecar/econometrica/utils/posterior_propagation.py` (HDI computation)
  - `sidecar/econometrica/engines/persistence.py` (pickle v2.0 schema)
- Tests:
  - `tools/test_kpi_registry.py`
  - `tools/test_backend_check.py`
  - `tools/test_pickle_compat.py`
  - `tools/test_regression_pin_kagocel.py`
  - `tools/test_weibull_recovery.py`
