# Aurora Econometrica — Math Reference (living doc)

**Purpose:** centralized math reference for all model components. Versioned sections per release.
Replaces sprawled MATH_AUDIT_v1_*.md files (single source of truth).

**Last updated:** 2026-04-28 (v1.2.0 development — Awareness KPI + Weibull Learnable)

---

## Table of Contents

- [KPI Registry (v2.0+)](#kpi-registry-v20)
- [Awareness KPI Engine (v1.2.0)](#awareness-kpi-engine-v120)
- [Weibull Learnable Adstock (v1.2.0)](#weibull-learnable-adstock-v120)
- [Trust Level 3 Hierarchical Brand/Performance (v1.1.0)](#trust-level-3-hierarchical-brandperformance-v110)
- [Phase 1.1 Adstock decay sampling (v1.0.13+)](#phase-11-adstock-decay-sampling-v1013)
- [Hill saturation normalization (v1.0.12+)](#hill-saturation-normalization-v1012)

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
- brand_mu_logit_prior=(1.4, 0.4) → sigmoid≈0.80 → ~26wk effective half-life
- perf_mu_logit_prior=(-0.7, 0.5) → sigmoid≈0.33 → ~3wk half-life

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

Standard Weibull (λ scale, k shape) suffers identifiability:
- λ=4, k=1 (exponential) ≈ λ=2, k=2 (Rayleigh) для small samples → posterior bimodal.

**Fix:** reparameterize as `(peak_week, tail_decay)`:
- `peak_week`: where Weibull peaks (mode). Interpretable: «эффект достигает пика на N-й неделе».
- `tail_decay`: tail rate (Beta-like 0..1). Interpretable: «насколько быстро затухает хвост».

**Conversion (closed-form):**
```python
k = 1.0 + 1.0 / max(tail_decay, 0.05)   # tail_decay → k
lam = peak_week / ((k - 1) / k) ** (1.0 / k)  # mode → λ (для k > 1)
```

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
- `brand_mu_logit ~ Normal(0.7, 0.3)` → sigmoid≈0.67 → ~12 wk half-life
- `perf_mu_logit ~ Normal(-1.4, 0.7)` → sigmoid≈0.20 → ~1.3 wk
- `mixed_mu_logit ~ Normal(-1.4, 0.7)` (semantic compat)

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

## References

- Plan: `~/.claude/plans/bright-wandering-neumann.md`
- Status: `D:/Docs/Aurora_Ai/Awareness_KPI_track_Weibull_Adstock.md`
- Code:
  - `sidecar/econometrica/engines/modeler.py` (main MCMC)
  - `sidecar/econometrica/engines/decomposer.py` (downstream extraction)
  - `sidecar/econometrica/engines/optimizer.py` (chain rule)
  - `sidecar/econometrica/utils/kpi_registry.py` (KPI configs)
  - `sidecar/econometrica/utils/backend_check.py` (JAX availability)
  - `sidecar/econometrica/engines/persistence.py` (pickle v2.0)
- Tests:
  - `tools/test_kpi_registry.py`
  - `tools/test_backend_check.py`
  - `tools/test_pickle_compat.py`
  - `tools/test_regression_pin_kagocel.py`
  - `tools/test_weibull_recovery.py`
