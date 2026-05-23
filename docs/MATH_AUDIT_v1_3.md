# Math Audit v1.3 - Cross-Engine Hill Propagation Consistency

**Date:** 2026-04-25
**Trigger:** Phase 0.1 live-test reveal: optimizer trivial allocation (delta=0%), scenario ±50% identical KPI. Hot-fixes недостаточны - нужен systematic audit.
**Scope:** propagation consistency между 4 engines (modeler/decomposer/optimizer/scenario). Не estimation correctness (закрыто в v1.1 + v1.2 audits).

## Cross-engine matrix

| Aspect | modeler (training) | decomposer | optimizer | scenario |
|---|---|---|---|---|
| Хранилище spend | `df[col]` per-period values | `df[col]` per-period | `df[col].sum()` aggregate | `media_plan[col]` per-period list |
| Adstock | ✓ per channel: `apply_adstock(df[col].values)` | ✓ `apply_adstock(raw_spend_series)` | ❌ **NOT applied** | ✓ `apply_adstock(raw_arr)` per period |
| Hill input | per-period adstocked / mean | per-period adstocked / mean | **total spend / mean (aggregate)** | per-period adstocked / mean |
| Hill output processing | per-period × β | per-period × β × y_std → cum sum | sum across channels (no time) | per-period × β × y_std |
| Baseline + control | intercept × y_std + y_mean (per t) + Σβ_c × control_norm × y_std | same + residual absorption | ❌ **N/A** (only media in objective) | intercept × y_std + y_mean (per t), control assumed mean |
| n_periods aware | ✓ implicit (per-period iter) | ✓ `n_periods = len(df)` | ❌ **aggregates** | ✓ `n_periods = max(len(v) for v in plan.values())` |

## Findings

### F1 - Optimizer Hill input is total spend (CRITICAL P0)

**Code:** `optimizer.py:151-159 total_response`:
```python
def total_response(spend_vector):
    total = 0
    for i, col in enumerate(media_cols):
        mean = float(media_means.get(col, 1)) or 1
        x_norm = spend_vector[i] / max(mean, 1e-10)  # spend_vector = TOTAL
        sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 1e-6))
        total += p['beta'] * sat[0]
    return -total
```

**Problem:** `spend_vector[i]` - total over all periods (`current_spend = df[col].fillna(0).sum()`). `media_means[col]` - per-period mean. Hill expects per-period spend / per-period mean → ratio близкая к ~1× для типичного данных.

**Live data symptom:** TRPs current sum=22100, mean=712.89 → x_norm = **31×**.
- Hill(x=31, α=1.49, γ=0.49) ≈ **0.999**
- Hill(x=50) ≈ 0.9996
- Hill(x=100) ≈ 0.9999
- Practically flat asymptote; ∂sat/∂x ≈ 1e-9 → SLSQP видит objective gradient ≈ 0 → trivial allocation.

**Impact:** Optimizer fails on any data with concentrated channel (TV-heavy брenд) или скунутый mean (sparse spend with big bursts).

**Comparison:** scenario.py per-period:
```python
for t in range(n_periods):
    spend_t_adstock = float(adstocked_plan[col][t])
    x_norm = spend_t_adstock / max(mean, 1e-10)  # per-period: typical 0.5-3×
    sat = hill_function(...)
```

**Fix:** divide spend_vector by n_periods, multiply contribution by n_periods:
```python
n_periods = max(len(df), 1)  # add at top of optimize()

def total_response(spend_vector):
    total = 0
    for i, col in enumerate(media_cols):
        mean = float(media_means.get(col, 1)) or 1
        x_avg = spend_vector[i] / n_periods  # per-period equivalent
        x_norm = x_avg / max(mean, 1e-10)
        sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 1e-6))
        total += p['beta'] * sat[0] * n_periods  # × n_periods to match training scale
    return -total
```

Assumption: optimizer treats allocation as **flat per-period** (uniform over t). Acceptable simplification - actual per-period burst structure is given by current data, optimizer rebalances totals.

### F2 - Optimizer skips adstock (CRITICAL P0)

**Code:** `optimizer.py:151+` total_response не вызывает `apply_adstock`.
Training (modeler.py:243) и scenario (scenario.py:116) применяют adstock к spend перед Hill.

**Problem:** mROI и response_curves в optimizer оцениваются по **raw spend**, training учил модель на **adstocked spend**. Predictions inconsistent: optimizer says "+1 ₽ TRPs → +β·sat'(...)·y_std", но реально через adstock decay TV brand impact смазывается → effective dKPI меньше.

**Fix:** apply_adstock в total_response:
```python
def total_response(spend_vector):
    total = 0
    for i, col in enumerate(media_cols):
        # Recreate adstocked per-period series with flat alloc
        x_avg = spend_vector[i] / n_periods
        flat_series = np.full(n_periods, x_avg)
        a_type = adstock_config.get(col, 'geometric')
        adstocked = apply_adstock(flat_series, a_type)
        # adstocked steady-state = x_avg × 1/(1-α) for geometric, sum normalized to spend × adstock_factor
        # Иначе подсчёт через avg adstocked:
        x_norm = adstocked.mean() / max(mean, 1e-10)
        ...
```

Tradeoff: per-period iteration в optimizer slow если n_periods large. Можно использовать **steady-state approximation** для flat alloc: x_adstocked_steady = x_avg × adstock_factor (closed form для geometric).

### F3 - Optimizer skips baseline+control в objective (MEDIUM P1)

**Code:** total_response only sums β×sat across media; baseline + control effect не входят.

**Problem:** absolute objective value mismatched с scenario.predicted_kpi. Для optimization (maximize media contrib subject budget) - formally OK (constants don't affect argmax). Но для UI display "expected lift %" - total_response value misleading.

**Fix:** add baseline + control_effect (constants under flat alloc), display predicted_kpi = baseline + Σβ·sat·y_std·n_periods.

### F4 - mROI computation chain (MEDIUM P1, blocked by F1+F2)

**Code:** `optimizer.py:215-221`: chain rule `mROI = ∂(β·hill)/∂x_norm × 1/mean × y_std`.

**Problem:** evaluated at x_norm = total/mean = 31× → ∂sat/∂x ≈ 0 → mROI tiny. После fix F1+F2 (avg per-period), x_norm ≈ 1× → ∂sat/∂x ≈ realistic.

**Fix:** auto-resolves когда F1 ship.

### F5 - Response curves drawn в saturation plateau (MEDIUM P1)

**Code:** `optimizer.py:244-250`: spend_range вокруг total spend → x_norm большой → flat S-curve.

**Fix:** auto-resolves с F1. Range должен быть в per-period scale ([0, 3×current_per_period]).

### F6 - Scenario media_plan padding (CRITICAL P0)

**Code:** `scenario.py:111-114`:
```python
if len(raw_arr) < n_periods:
    raw_arr = np.concatenate([raw_arr, np.zeros(n_periods - len(raw_arr))])
```

**Problem:** UI what-if (`OptimizeStep.svelte:431`) shлёт `mediaPlan[c.name] = [c.optimal_spend ?? 0]` - single-period array. Backend pads с zeros → effective annual spend = single period × 1 (rest zeros). Hill только в первом периоде есть spend → contribution тонкая → predicted KPI ≈ baseline-only.

**Symptom:** ±50% и +180% scenarios give similar predicted_kpi (390M) - оба dominated by baseline, media contrib микроскопическая.

**Fix:** при single-period plan → distribute evenly across n_periods (assume flat allocation, как training):
```python
if len(raw_arr) == 1:
    raw_arr = np.full(n_periods, raw_arr[0] / n_periods)  # split total across periods
elif len(raw_arr) < n_periods:
    # For partial план с кол-вом periods >1 → continue zero-padding (user explicit intent)
    raw_arr = np.concatenate([raw_arr, np.zeros(n_periods - len(raw_arr))])
```

**Альтернатива:** UI отправляет **per-period array length n_periods** с равномерным разбросом. Фрontend fix вместо backend.

### F7 - n_periods detection в scenario (MINOR)

**Code:** `scenario.py:99`: `n_periods = max(len(v) for v in media_plan.values())`.

**Problem:** UI sends single-period plan → n_periods = 1. Inside loop only t=0 executes → predicted = single-period only.

**Fix:** if все channels have n=1, use training n_periods (from len(df) loaded similarly). Combined fix с F6.

## Priority + Roadmap

### P0 ship blockers (для v1.0.13)

1. **F1+F2** (optimizer per-period + adstock) - ~2-3h. Single fix block.
2. **F6+F7** (scenario padding logic) - ~1h. Single fix block.

После F1+F2+F6+F7:
- Optimizer non-trivial allocation (Plan §0.1 acceptance) - должно PASS
- Scenario ±50% delta KPI ≥ 5% - PASS на TRPs-light (digital) data; на TRPs-heavy (Kagocel) saturation реальная, но slider покажет realistic delta (per-period x_norm now ~1× → Hill curvature visible)

### P1 polish (post-ship)

3. **F3** (baseline в optimizer objective) - UI display fix, документировать
4. **F4, F5** - auto-resolve

## Validation gate (после F1+F2+F6+F7 fix)

- [ ] **Synthetic test:** single-channel + flat priors → optimizer finds budget = β·max ratio (closed-form check)
- [ ] **Live Kagocel:** scenario ±50% TRPs → |delta KPI| > 0.5pp (currently 0%)
- [ ] **Optimizer non-trivial:** std(delta_pct)/mean > 0.05 на data с ROI spread > 5×
- [ ] **Scenario↔Optimizer consistency:** same allocation → same predicted_kpi (within 1%)
- [ ] **All 118 math tests still PASS**
- [ ] **No regression в decomposer.json energy conservation** (sum baseline+media=total)

## Связь с master plan

- Plan §1.1 (joint adstock+Hill MCMC) - addresses estimation, not propagation. Эти findings - orthogonal.
- Plan §2.6 (Live what-if WebAssembly) - тот UI элемент который F6 ломает. После fix F6 - JS Hill в HTML report тоже должен быть consistency-checked.

## Decision

Этот audit подтверждает: **необходим P0 fix F1+F2+F6+F7 ДО ship v1.0.13**. Без них:
- Optimizer trivial → клиент видит «оптимизатор не работает»
- Scenario insensitive → клиент видит «what-if не реагирует»

Это **показ-стопперы для commercial release**, не cosmetics.

**ETA fix:** 3-4h work + sidecar rebuild + live re-test.
