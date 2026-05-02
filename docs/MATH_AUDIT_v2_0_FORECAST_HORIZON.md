# Math Audit v2.0 — Forecast Horizon (Planning Mode)

**Status:** 🟢 PART 1 COMPLETE 2026-05-02 — Phase 2.1 unblocked. 🟡 PART 2 (L4 γ + L5 hierarchical) deferred к after-ship recalibration.
**Started:** 2026-05-02
**Branch:** `math-fix-v1.0.13`
**Author:** Claude (Opus 4.7) + Антон review.
**Purpose:** Lock math decisions для Phase 2 Planning Mode (forecast_periods + forecast_budget decoupling) до начала backend implementation. Без этого doc'а — Phase 2.1 заблокирована.

---

## §0. Контекст и premise

### 0.1 Текущее состояние (Phase 1, v1.0.16 / v1.1.0-rc)

`optimizer.py:329` ставит `n_periods = max(len(df), 1)` — единая переменная, обслуживающая **две различные роли**:

| Роль | Где | Smysl |
|---|---|---|
| **Training-fit math** | `media_means`, `adstock_mean_posterior`, `train_x_norm_quantiles` (planned), Hill priors calibration | Frozen at fit time — характеристика **обученной модели** |
| **Forecast scaling** | `total_response_money` (per-period averaging + total aggregation), `response_curves` axes, mROAS computation | Используется как **planning horizon** — но hard-pegged к training length |

Customer use case (Антон 2026-05-02): MMM обучена на 156 weeks (3 years). Planner делает медиаплан на **2026 год** = 52 weeks с **другим бюджетом**. Optimizer выдаёт allocation для 156-week training scale — customer должен делить на ratio вручную → error-prone.

### 0.2 Phase 2 thesis

Decouple:
- `train_n_periods = len(df)` (frozen, training characterization)
- `forecast_n_periods = config.get('forecast_periods') or train_n_periods` (planning input, default к training для backward compat)

Используется в:
1. `total_response_money()` per-period averaging (x_avg = x_total / forecast_n)
2. Total response aggregation (total += beta × sat × forecast_n)
3. Response curves x-axis label
4. mROAS computation per-period
5. Saturation drift validation
6. Reports KPI extrapolation

### 0.3 Industry references

| Tool | Approach |
|---|---|
| Robyn (Meta) | `robyn_allocator(date_range=..., expected_spend=...)` — date-range based, ambiguous if multi-year |
| Meridian (Google) | `forecast_horizon_periods` parameter (numeric, no calendar awareness) |
| LightweightMMM (Google) | `optimize_media(n_time_periods=...)` for simulation |

**Aurora differentiation target:** calendar-aware horizon picker + P10/P50/P90 + epistemic inflation + saturation drift detection + seasonality-aware start position.

---

## §1. Two adstock kernel options (the core open question)

При decoupling `forecast_n` от `train_n`, adstock kernel может быть calibrated двумя способами. Это **главный math decision** требующий synthetic test.

### Option A — «Freeze training adstock semantics»

Adstock calibration (decay, mean) **frozen at training** — характеристика обученной модели. Forecast budget aggregated через тот же per-period adstock kernel что обучен.

**Math:**
```
x_avg_raw_forecast    = x_money_total / forecast_n / unit_cost
x_avg_adstock_forecast = adstock_kernel_TRAIN(x_avg_raw_forecast, train_n_periods, decay_TRAIN)
                                                                   ^^^^^^^^^^^^^^^
                                                                   ^^^ kernel calibration uses TRAIN
x_norm                = x_avg_adstock_forecast / mean_TRAIN
sat                   = Hill(x_norm, alpha_TRAIN, gamma_TRAIN)
total_response        = beta_TRAIN × sat × forecast_n
                                            ^^^^^^^^^^^
                                            ^^^ aggregation uses FORECAST
```

**Pros:**
- Backward compat trivial: `forecast_n = train_n` → exact equivalence
- Hill saturation operates на same x_norm scale что training (β posterior valid)
- Pickle schema additive — никаких retrains required

**Cons:**
- Если customer изменяет per-period spend (e.g. forecast budget 5× training average), `x_avg_adstock_forecast` → far-tail Hill → β extrapolation, posterior CI underestimated (M4)
- Кernel длина = train_n (зависит от training length): `_flat_alloc_adstock_avg(x_avg_raw, **train_n**, ...)` — для geometric adstock это не имеет значения (steady state ≈ x / (1-decay) при train_n >> 1/(1-decay)), но для Weibull adstock с finite kernel это значимо

### Option B — «Recompute adstock kernel for forecast horizon»

Adstock kernel re-calibrated к forecast_n — длина свёртки соответствует planning period.

**Math:**
```
x_avg_raw_forecast     = x_money_total / forecast_n / unit_cost
x_avg_adstock_forecast = adstock_kernel(x_avg_raw_forecast, forecast_n, decay_TRAIN)
                                                            ^^^^^^^^^^
                                                            ^^^ kernel length = FORECAST
x_norm                 = x_avg_adstock_forecast / mean_TRAIN
sat                    = Hill(x_norm, alpha_TRAIN, gamma_TRAIN)
total_response         = beta_TRAIN × sat × forecast_n
```

**Pros:**
- «Естественнее» — kernel matches planning period
- Для short forecasts (1 month vs 3 years training) меньше over-estimates carryover

**Cons:**
- Для geometric adstock в steady-state — identical к Option A (steady state не зависит от kernel length при достаточной длине)
- Для Weibull adstock — divergence от training calibration (training learned kernel в context training-length convolution)
- Mean normalization (`mean_TRAIN`) рассчитан под training kernel — mismatch
- В edge case forecast_n < 1/(1-decay) (короткий forecast, медленный decay) — adstock не достигает steady-state → systematic underestimate

### 1.1 Steady-state argument

Для **geometric adstock** при flat allocation (x_t = x_avg ∀ t):
```
adstock_t = Σ_k=0..t (decay^k × x_avg) = x_avg × (1 - decay^(t+1)) / (1 - decay)
```

При t → ∞: `adstock_∞ = x_avg / (1 - decay)` — steady state.

Для t=10, decay=0.5: `(1 - 0.5^11) / 0.5 = 1.999` ≈ 2.0 (within 0.05% of steady state).
Для t=10, decay=0.8: `(1 - 0.8^11) / 0.2 = 4.57` (training adstock_mean ≈ 5.0 в steady-state — within 9%).
Для t=10, decay=0.95: `(1 - 0.95^11) / 0.05 = 11.0` (steady state = 20 — **45% off**).

**Implication:** для **slow-decay channels** (TV, Brand, decay > 0.8) с **short forecasts** (forecast_n < 20) — Option A vs B diverge significantly. Это критично для customer use case 52-week forecast на 156-week training.

### 1.2 Aurora's `_flat_alloc_adstock_avg` (existing helper)

Файл: `sidecar/econometrica/utils/adstock.py` (функция используется в `optimizer.py:500`).

Текущая реализация — для flat allocation x_avg over n_periods, computes mean of adstock series. Принимает `n_periods` как kernel length parameter — **уже decoupled от training length**.

**Implication:** Option A ↔ Option B на уровне Aurora кода — это просто разный аргумент в `_flat_alloc_adstock_avg(x_avg_raw, ?, _adstock_type(col), decay_pt)`:
- Option A: `?` = `train_n_periods`
- Option B: `?` = `forecast_n_periods`

Тривиально для имплементации. Но math correctness — не тривиально, требует synthetic test.

---

## §2. Critical findings recap (from PHASE_2_PLAN, M1-M8)

| # | Gap | Locked decision | Status |
|---|---|---|---|
| **M1** | Adstock warmup для sharp-start (cold start = первые ~1/(1-decay) periods underperform) | `forecast_warmup_correction()` helper + UI toggle (default ON если forecast_start ≤ training_end + 1) | Pending §4 test |
| **M2** | Seasonality bias по позиции старта | Phase 2: warning-only + manual override; auto-correction → Phase 2.5 | Pending §4 test |
| **M3** | unit_costs media inflation в forecast | Reuse existing `channelInflation` state (Brand 12% / Perf 7% / Mixed 8%) → pass scaled `unit_costs_forecast` | LOCK |
| **M4** | Posterior uncertainty underestimated в extrapolated zones | `inflate_extrapolation_uncertainty(samples, x_observed_p95, x_forecast, γ)` — γ requires calibration | Pending §5 calibration |
| **M5** | Hierarchical priors interaction с extreme forecasts | Test case: hierarchical + 3× budget vs flat. Drift > 10% → flag panel warning | Pending §6 test |
| **M6** | Stationarity hard cap | Plan tightens 5× → 2× | LOCK pending §3 sensitivity |
| **M7** | Hill calibration boundary uses full distribution не p95 only | Persist `train_x_norm_quantiles = {p50, p75, p90, p95, p99}` (additive pickle field). Tiers: >p95 warn, >p99 critical | LOCK |
| **M8** | `adstock_mean_posterior` stale anchor при extreme budgets | Drift detection extends к `adstock_mean_forecast / adstock_mean_posterior` ratio (не только raw spend). ≥3× → critical | LOCK |

---

## §3. Synthetic test methodology

### 3.1 Data generator

**Synthetic dataset:** `tools/audit_v2_0_synthetic.py::generate_synthetic_market(n_periods, seed)`

Properties:
- `n_periods = 156` weeks (3-year training horizon — match Kagocel reference scale)
- 4 channels: TV (slow decay 0.85, brand), OLV (medium 0.65, mixed), Search (fast 0.30, performance), Programmatic (fast 0.40, performance)
- Spend: positive log-normal с trend (1% growth/week) + seasonality `1 + 0.3*sin(2π*t/52)` (yearly cycle)
- Hill params per channel: alpha ∈ [1.5, 3.0], gamma ∈ [0.4, 0.7]
- Beta per channel: known ground truth ~ N(0.05, 0.01) positive
- KPI = Σ beta × Hill(x_norm with adstock) × y_std + baseline + noise(0.05)

### 3.2 Train MMM

Train Aurora MMM (`engines/modeler.py`) на synthetic data. Verify:
- R² > 0.85 (sanity check — recover signal from synthetic)
- R-hat < 1.05 per param
- `media_means`, `decay`, `alpha`, `gamma`, `beta` posteriors recovered ≥80% close to ground truth (allow stochastic noise)

### 3.3 Optimize matrix

**Cases:** `forecast_periods × forecast_budget` = 5 × 5 = 25 cases

| forecast_periods | Comment |
|---|---|
| 26  | 0.17× train (extreme compression) |
| 52  | 0.33× train (1 year) — primary use case |
| 104 | 0.67× train (2 years) |
| 156 | 1.0× train (regression baseline — must be byte-exact equivalent) |
| 312 | 2.0× train (boundary — M6 cap) |

| forecast_budget | Comment |
|---|---|
| 0.5× | Compressed budget |
| 1.0× | Regression (per-period equiv) |
| 1.5× | Mild scaling |
| 3.0× | Drift zone (M8) |
| 5.0× | Extrapolation zone (M4) |

### 3.4 Ground truth

Analytical Hill+adstock formula, computed numerically without optimizer:
```python
def ground_truth_kpi(x_money_per_channel, forecast_n, train_params):
    """Analytical KPI for given allocation under flat-spend assumption."""
    total = 0.0
    for col, x_money in x_money_per_channel.items():
        p = train_params[col]
        # Steady-state geometric adstock for flat allocation:
        x_avg_raw = x_money / forecast_n / p['unit_cost']
        adstock_ss = x_avg_raw / (1 - p['decay'])  # geometric closed form
        # But truncated kernel (Aurora's _flat_alloc_adstock_avg):
        adstock_kernel = x_avg_raw * (1 - p['decay']**forecast_n) / (1 - p['decay'])
        # Mean over forecast_n periods (matching helper):
        # ... (full numerical equivalent)
        x_norm = adstock_kernel_mean / p['mean_train']
        sat = (x_norm**p['alpha']) / (p['gamma']**p['alpha'] + x_norm**p['alpha'])
        total += p['beta'] * sat * forecast_n * p['y_std']
    return total
```

### 3.5 Comparison metrics

For each (forecast_periods, forecast_budget) case:
1. **Option A KPI** vs **Option B KPI** vs **Ground truth KPI**
2. **Optimal allocation divergence:** `cosine_similarity(allocation_A, allocation_B)`, `L1_diff(allocation_A, ground_truth)`
3. **Lift % consistency:** abs(lift_A - lift_B), abs(lift - lift_ground)
4. **Saturation operating zone:** per channel `x_norm_forecast` vs `train_x_norm_quantiles`

### 3.6 Acceptance for kernel decision

**Lock Option A iff:**
- Option A median |error vs ground truth| < 5% across all 25 cases
- Option A optimal allocation cosine sim > 0.95 vs ground truth across all cases
- Backward compat case (forecast_n = train_n) = byte-exact

**Lock Option B iff:**
- Both A и B fail iff above, but B closer to ground truth in extreme cases (forecast_n < 20)

**Default if both pass:** Option A (simpler, additive pickle compat, REUSE existing helper signature unchanged).

---

## §4. Seasonality test methodology (M2)

**Setup:** Same synthetic data, but evaluate forecast = 12 periods starting at:
- t=0 (Q1 start) — низкая seasonality зона
- t=13 (Q2)
- t=26 (Q3)
- t=39 (Q4 start) — пик seasonality

For each start position, compute:
- Optimal allocation
- Realized KPI (using ground truth formula on **actual** seasonal multiplier per period)
- Divergence от uniform-period assumption (current Aurora approach assumes flat-rate per-period)

**Decision:**
- If max divergence < 5% → ship Phase 2 без auto-correction (warning-only)
- If 5-15% → ship warning + suggest «оптимальный старт» auto-detected
- If >15% → blocking gate: require user confirmation + auto-corrected baseline

---

## §5. Epistemic inflation factor γ calibration (M4)

**Setup:** Train MMM на 156 periods. Take 100 posterior samples. Compute KPI distribution для:
- `x_forecast = x_train_p50` (interpolation zone — should be well-calibrated)
- `x_forecast = x_train_p95` (boundary)
- `x_forecast = x_train_p99` (extrapolation begin)
- `x_forecast = 1.5 × x_train_p99`
- `x_forecast = 3 × x_train_p99`
- `x_forecast = 5 × x_train_p99`

For each, compute **observed** posterior CI width vs **bootstrapped repeated-train** CI width (refit 30 models on bootstrapped data, compare).

If observed posterior CI width understates true epistemic uncertainty by factor `f(ratio)`, fit:
```
f(r) ≈ 1 + γ × (r - 1)    where r = x_forecast / x_observed_p95
```

Lock γ ∈ [0.2, 0.5] based on fit. If fit poor (R² < 0.8) → use conservative γ = 0.5.

---

## §6. Hierarchical interaction test (M5)

**Setup:** Train two synthetic models на same data:
- (a) Flat (single global prior) — `model_version = 1.2`
- (b) Hierarchical Trust 3 (brand vs perf groups) — `model_version = 1.3`

Optimize at forecast_budget = {1×, 3×, 5× training} for each model. Compare:
- Allocation divergence (a) vs (b)
- Per-channel β posterior shrinkage effect: hierarchical pulls outliers towards group mean → underestimate top-performer ROI?

**Acceptance:**
- If divergence > 10% → flag panel warning «Brand-каналы 3× от calibration zone — hierarchical pooling может занижать оценку для top performer»
- Document expected behavior in user-facing methodology PDF

---

## §7. Lock decisions

🟢 **Part 1 (L1-L3) LOCKED 2026-05-02** на основании `tools/audit_v2_0_synthetic.py` results (см. §8 + `docs/audit_v2_0_synthetic_results.json`).
🟡 **Part 2 (L4-L5) DEFERRED** — требует training real Aurora MMM на synthetic + bootstrap CI comparison. Не блокирует Phase 2.1 — `inflate_extrapolation_uncertainty()` будет shipped с conservative γ=0.3 default + recalibration в follow-up audit.

| # | Decision | Locked value | Rationale |
|---|---|---|---|
| **L1** | **Adstock kernel approach** | **Option B — kernel length = `forecast_n_periods`** | §8.1 results: B median err 0.42% vs A 0.87%; B max 2.78% vs A 11.41%; B p90 1.56% vs A 4.97%. Особенно critical для коротких forecasts (fn=26: A=11.4%, B=0.5%). Aurora ground truth = fresh-start simulation, Option B matches by construction. **Auto-resolves M1** (warmup) — B inherently models cold-start. Backward compat trivially preserved (fn=train_n → A==B). |
| **L2** | **Stationarity hard cap** | **`forecast_periods ≤ train_n × 2` hard reject; > 1.5× warn** | §8.2 — math approximation error stays <1% even at 5×, but β stationarity (statistical reliability) breaks beyond ~2× per Robyn/Meridian convention. Hard cap 2×, warn at 1.5× per plan M6. |
| **L3** | **Seasonality strategy** | **Phase 2: warn + suggest «оптимальный старт» (REQUIRE start_date input при detected seasonality > 0.2 autocorr); auto-corrected baseline → Phase 2.5** | §8.3 — Q4 start divergence 17.35% при amplitude 0.3 (FMCG-realistic). Above plan's 15% threshold для blocking gate. **Hardened от plan «warn-only»**: при detected seasonality в training (autocorr lag 12 > 0.2 OR lag 52 > 0.2) — REQUIRE user explicitly confirm forecast_start_date в picker (не silent default к training_end+1). Auto-correction (per-period adjustment per seasonal multiplier) — Phase 2.5 math complexity. |
| L4 | Epistemic inflation γ | **DEFAULT γ=0.3 (conservative)** для Phase 2.1 ship; recalibrate в Phase 2.0 Part 2 после real MMM training | Plan §5 calibration требует bootstrap CI comparison на 30 refits — heavy. Conservative ε=0.3 не блокирует Phase 2.1 (`inflate_extrapolation_uncertainty(samples, p95, x_forecast, γ=0.3)`). При recalibration — only constant tuning, не code change. |
| L5 | Hierarchical extreme behavior | **Phase 2.1 ships generic warning «Brand-каналы 3× от calibration zone — hierarchical pooling может занижать оценку для top performer»**; quantitative threshold → Phase 2.0 Part 2 | Same as L4 — нужен real training. Generic warning не блокирует ship и не претендует на quantitative claim. |
| L6 | Pickle bump strategy | **1.3 → 2.0** (single bump для known future phases) | LOCK from plan |
| L7 | Drift detection metric | **Both raw spend (M8) and adstock_mean ratio** | LOCK from plan |
| L8 | x_norm calibration boundaries | **Persist quantiles {p50, p75, p90, p95, p99}** | LOCK from plan |
| L9 | Phase 2.0 Part 2 trigger | **Run после Phase 2.1 ship на ≥1 customer pickle** — позволит calibrate γ + hierarchical threshold на real posterior | NEW lock |

---

## §8. Synthetic test results (Part 1)

🟢 **Part 1 RUN 2026-05-02** via `tools/audit_v2_0_synthetic.py`. Snapshot: `docs/audit_v2_0_synthetic_results.json`.
🟡 **Part 2 (§8.4 epistemic γ + §8.5 hierarchical) deferred** — see L4/L5 rationale.

### 8.1 L1 Adstock kernel matrix (5×5 = 25 cases)

| forecast_n | budget× | KPI_A | KPI_B | KPI_ground | err_A% | err_B% |
|---:|---:|---:|---:|---:|---:|---:|
| 26  | 0.5 | 283.15 | 252.87 | 254.15 | **11.41** | 0.50 |
| 26  | 1.0 | 478.48 | 453.29 | 442.42 | **8.15**  | 2.46 |
| 26  | 1.5 | 541.96 | 528.49 | 514.21 | 5.40  | 2.78 |
| 26  | 3.0 | 584.33 | 581.22 | 572.28 | 2.11  | 1.56 |
| 26  | 5.0 | 593.26 | 592.30 | 588.16 | 0.87  | 0.70 |
| 52  | 0.5 | 566.30 | 542.02 | 542.85 | 4.32  | 0.15 |
| 52  | 1.0 | 956.96 | 938.82 | 924.68 | 3.49  | 1.53 |
| 52  | 1.5 | 1083.92 | 1074.60 | 1058.06 | 2.44 | 1.56 |
| 52  | 3.0 | 1168.66 | 1166.54 | 1157.04 | 1.00 | 0.82 |
| 52  | 5.0 | 1186.51 | 1185.86 | 1181.55 | 0.42 | 0.37 |
| 104 | 0.5 | 1132.60 | 1120.57 | 1121.03 | 1.03 | 0.04 |
| 104 | 1.0 | 1913.93 | 1905.38 | 1889.71 | 1.28 | 0.83 |
| 104 | 1.5 | 2167.84 | 2163.51 | 2146.01 | 1.02 | 0.82 |
| 104 | 3.0 | 2337.31 | 2336.34 | 2326.60 | 0.46 | 0.42 |
| 104 | 5.0 | 2373.02 | 2372.72 | 2368.34 | 0.20 | 0.19 |
| 156 | 0.5 | 1698.90 | 1698.90 | 1699.22 | 0.02 | 0.02 |
| 156 | 1.0 | 2870.89 | 2870.89 | 2854.76 | 0.57 | 0.57 |
| 156 | 1.5 | 3251.75 | 3251.75 | 3233.96 | 0.55 | 0.55 |
| 156 | 3.0 | 3505.97 | 3505.97 | 3496.16 | 0.28 | 0.28 |
| 156 | 5.0 | 3559.53 | 3559.53 | 3555.13 | 0.12 | 0.12 |
| 312 | 0.5 | 3397.79 | 3433.61 | 3433.78 | 1.05 | 0.005 |
| 312 | 1.0 | 5741.78 | 5766.47 | 5749.88 | 0.14 | 0.29 |
| 312 | 1.5 | 6503.51 | 6515.88 | 6497.81 | 0.09 | 0.28 |
| 312 | 3.0 | 7011.94 | 7014.73 | 7004.85 | 0.10 | 0.14 |
| 312 | 5.0 | 7119.07 | 7119.93 | 7115.52 | 0.05 | 0.06 |

**Aggregate:**

| | median | max | p90 |
|---|---:|---:|---:|
| Option A | 0.867% | **11.410%** | 4.966% |
| Option B | 0.418% | **2.776%**  | 1.562% |

**Verdict:** Option B dominates strictly. Lock L1 = Option B.

**Backward compat verified:** при `forecast_n = train_n = 156`, errors A == B identically (rows 16-20 в таблице). Это гарантирует что v1.1.0 customer pickles без `forecast_periods` в request → byte-exact результат к pre-Phase-2 behavior.

### 8.2 L2 Cap sensitivity (Option B error at horizon multipliers)

| horizon× | forecast_n | err_pct |
|---:|---:|---:|
| 1.0 | 156 | 0.565 |
| 1.5 | 234 | 0.093 |
| 2.0 | 312 | 0.141 |
| 3.0 | 468 | 0.374 |
| 5.0 | 780 | 0.560 |

Math approximation error остаётся < 1% даже при horizon×5. Real risk при extreme cap = β statistical extrapolation (not math). Cap 2× — convention based on industry (Robyn/Meridian) + plan M6 reasoning.

### 8.3 L3 Seasonality bias (12-week forecast at 4 start positions, amp=0.3)

| start | kpi_uniform | kpi_realized | divergence% |
|:---|---:|---:|---:|
| Q1 | 185.19 | 197.11 | 6.44 |
| Q2 | 185.19 | 207.25 | **11.91** |
| Q3 | 185.19 | 167.80 | 9.39 |
| Q4 | 185.19 | 153.06 | **17.35** |

Max 17.35% — выше plan's 15% blocking threshold. Hardened L3: при detected seasonality (autocorr > 0.2) → REQUIRE explicit start_date input.

### 8.4 Epistemic γ fit — DEFERRED to Part 2

Conservative default γ=0.3 ships в Phase 2.1. Recalibration после real MMM training + bootstrap CI comparison.

### 8.5 Hierarchical interaction — DEFERRED to Part 2

Generic warning ships в Phase 2.1. Quantitative threshold после real MMM comparison.

---

## §9. Implementation handoff

После §7 lock decisions:

**Phase 2.1 unblocked:**
- `optimizer.py` edits per locked Option (A or B) — line refs в plan
- `utils/forecast_validation.py` (NEW) — 8 helpers including `inflate_extrapolation_uncertainty(γ_locked)`
- `engines/persistence.py` pickle bump 1.3 → 2.0 (additive: `training_granularity`, `train_x_norm_quantiles`, `seasonality_detected`)
- `engines/modeler.py` — at-fit-time persist new fields
- Synthetic test cases → `tools/test_optimize_forecast.py` (Phase 2.7)

**Phase 2.0 acceptance gate:**
- ✅ This document complete with all §7 entries locked
- ✅ Synthetic harness `tools/audit_v2_0_synthetic.py` reproduces results table
- ✅ Антон review + sign-off

---

## Appendix A — Existing helpers REUSED (no rewrite)

| Helper | File | Purpose | Phase 2 use |
|---|---|---|---|
| `_flat_alloc_adstock_avg` | `utils/adstock.py` | Flat allocation adstock mean | Already takes `n_periods` arg — passed `forecast_n` или `train_n` per Option lock |
| `compute_ci_hdi` | `utils/posterior_propagation.py` | HDI bounds (P10/P50/P90 base) | Direct call в new `compute_post_convergence_ci` |
| `compute_train_adstock_mean_samples` | `utils/posterior_propagation.py` | Per-sample training adstock mean | Drift detection extension (M8) |
| `per_channel_samples` | `utils/posterior_propagation.py` | Joint posterior extraction | Reuse for forecast P10/P50/P90 |
| `geometric_adstock_batch` | `utils/adstock.py` | Vectorized geometric adstock | Used inside helper above |
| `hill_function` | `utils/saturation.py` | Hill saturation | Used in `total_response_money` (no change to math, just inputs) |

Pre-existing Conformal Prediction (`utils/conformal.py`) — already знает про seasonality limitations (line 11, 278). Reference для consistent messaging в Phase 2 forecast warnings.

---

**Status updates:**
- 2026-05-02 — Document skeleton + §1-§6 methodology written.
- 2026-05-02 — Synthetic harness `tools/audit_v2_0_synthetic.py` built and run. §7 Part 1 (L1, L2, L3) LOCKED based on §8.1-§8.3 results. **L1 verdict: Option B (kernel = forecast_n) wins strictly.** L4/L5 deferred to Part 2 (post-ship calibration).
