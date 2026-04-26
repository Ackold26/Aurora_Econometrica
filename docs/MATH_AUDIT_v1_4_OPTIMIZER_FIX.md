# Math Audit v1.4 — Optimizer false-convergence fix

**Created:** 2026-04-28
**Branch:** math-fix-v1.0.13 (HEAD will become v1.0.15)
**Predecessor:** docs/MATH_AUDIT_v1_3_PHASE_0_1.md
**Trigger:** Live-test Kagocel (n=31, 6 channels, 7 controls) на v1.0.14 NSIS installer показал что Optimizer возвращает `lift=0.0%` при ВСЕХ настройках (включая Min/Max 20/200 — Phase 0.1 рекомендованные defaults). Customer ship blocked.

Этот документ — audit-trail для исправления **false convergence bug** в SLSQP-based optimizer и формальное обоснование всех изменений в `engines/optimizer.py`.

---

## Empirical evidence (audit-of-audit, fresh-context, 2026-04-28)

Воспроизведено локально на реальном Kagocel pickle через прямой вызов `scipy.optimize.minimize`:

```
Pre-fix optimizer behaviour:

TEST 1: x_start = current allocation
  SLSQP success = True
  iterations    = 1                       ← false convergence at start point
  fun_at_start  = -8.1002
  fun_at_optimal = -8.1002                ← objective не сдвинулся
  lift          = +0.00%

TEST 2: x_start = extreme (small channels at upper bound, TRPs balances)
  fun_at_start = -10.3923
  lift relative to TEST 1 = +28.30%       ← real optimum существует
```

**Hypothesis space refuted:**

| Hypothesis | Status | Evidence |
|---|---|---|
| Constraint infeasibility | ❌ Refuted | sum_lower=718M ≤ target=3.59B ≤ sum_upper=7.18B |
| Hill saturation maxed out → derivative zero | ❌ Refuted | x_norm @current = 0.65-0.69 ≪ saturation; Hill' ≈ 0.534 |
| Frontend constraint pass-through | ❌ Refuted | Empirical traceback Svelte→Rust→FastAPI: 20/200 propagated correctly |
| MCMC config → bad posterior | ❌ Refuted | tail_ess_ok=True for all channels, decays plausible |

**Hypothesis confirmed:** numerical ill-conditioning + ineffective multi-start projection.

---

## Root cause analysis

### Bug 1 — bad numerical conditioning (PRIMARY)

Pre-fix optimizer работал в **native units**, equality constraint `Σ x_i × uc_i = M_target` в **money axis**.

For Kagocel scenario:
- Bounds spread native: 4420 (TRPs lower) → 2.14×10⁸ (OLV upper) = **48 461× spread**
- Gradient spread: ∂obj/∂TRPs ≈ 2.32e-5 / ∂obj/∂OLV ≈ 5.73e-9 = **4 050× spread**
- Constraint Jacobian uneven: uc_arr = [1, 1, 1, 1, 1, 150000]

SLSQP's BFGS-like inner Hessian approximation can't find correct step direction в high-conditioning regime. Result: at `x_start=current`, KKT condition `∇obj = λ × uc` сатуируется тривиально с λ→0 (numerical), `success=True`, no movement.

### Bug 2 — ineffective multi-start projection (SECONDARY)

Phase 0.1 hotfix #19 (commit `a3662a0`, 2026-04-26) добавил multi-start: 3 starts (current + 2 random perturbed). Implementation:

```python
perturbed = rng.uniform(bounds[i][0], bounds[i][1])  # native units
scale = money_target / sum(perturbed × uc_arr)        # rebalance
perturbed *= scale
perturbed = clip(perturbed, bounds_lower, bounds_upper)
```

**Failure mode demonstrated empirically:** для Kagocel, после scale + clip:
- TRPs bounds (4420, 44200) → uniform middle ≈ 24310 → after money-scaling (×0.91) ≈ 22122 ≈ current
- Each money channel similarly retracts к current after scaling

Three "random" starts collapse к neighborhood of current → SLSQP стартует close to existing local trap → returns same bad result.

---

## Fix strategy — 3 layers

### L1: money-axis rescaling (Fix Candidate 5 from AUDIT_PLAN_REVISIONS)

Pre-fix: optimize в native units, constraint в money.
Post-fix: optimize **always в money axis**, constraint trivializes к `Σ x_money = M_target`.

```python
def total_response_money(x_money):
    """x_money[i] in ₽; convert to native via /uc_arr[i] for Hill input."""
    total = 0
    for i, col in enumerate(media_cols):
        x_native_total = x_money[i] / uc_arr[i]
        x_avg_raw = x_native_total / n_periods
        x_avg_adstock = _flat_alloc_adstock_avg(x_avg_raw, n_periods, ...)
        x_norm = x_avg_adstock / mean
        total += beta * hill(x_norm, alpha, gamma) * n_periods
    return -total

bounds_money = [(cs * uc * min_pct, cs * uc * max_pct) ...]
constraints = [{'type': 'eq', 'fun': lambda x: sum(x) - money_target}]
```

**Conditioning improvement:** money bounds spread for Kagocel = 30M ÷ 6.6B ≈ 220× (vs 48 461× native). Gradient в money = ∂obj/∂x_money = (∂obj/∂x_native) / uc — uniform scale across channels.

### L2: channel-pivot + balancer multi-start (Fix Candidate 1)

**12-15 starts** покрывающих feasible region:

1. `current` — baseline (preserves Phase 0.1 hotfix #19 intent)
2. `pivot_up_{i}` для каждого канала i — channel i на upper, остальные на lower, project к budget. Captures «push one channel» corner.
3. `others_up_balance_{i}` для каждого i — все остальные каналы на upper, channel i exactly balances budget. **Это ключевой паттерн для money-constrained problems** — ловит «small channels saturated, balancer fills remainder» который для Kagocel-shape (TRPs ≈ 92% budget) и есть real optimum.
4. `all_upper` — pure scaling start, projection равномерно тянет всех вниз.

Cost: 13 starts × 200 iter × ~12 obj evals = ~31k function evaluations, sub-second на Kagocel.

### L3: false convergence detector + diagnostics (Fix Candidates 4+6)

**`converged_at_current` flag** в result_data:
```python
converged_at_current = (
    result.success
    and not binding_constraints
    and abs(lift_pct) < 0.5
    and max_normalized_delta < 0.01  # all channels < 1% of average money
)
```

Когда все 13 starts converge к practically current allocation БЕЗ binding — это symptom настоящего corner case (либо local trap либо truly optimal current). Narrative_adapter может surface honest banner.

**`slsqp_diagnostics`** — per-start outcomes (success, iterations, objective_at_start/optimal, message) для post-mortem debugging:
```json
{
  "n_starts": 13,
  "n_converged": 9,
  "best_objective": -10.392,
  "attempts": [{"start_name": "current", "success": true, "iterations": 1, ...}, ...]
}
```

UI can show «Optimizer пробовал 13 стартовых точек, лучший lift +28.3%» — transparency для doubting customers.

---

## Validation

### Test fixture (synthetic Kagocel-like)

Создан `tools/test_optimizer_kagocel_redistribution.py` — synthetic 6-channel pickle с такой же mathematical pathology (TRPs uc=150000, money channels uc=1, bounds spread 10⁵×, mROAS asymmetry ~350×). Self-contained — building DataFrame + pickle in tempdir.

**6 acceptance gates:**
- G1 lift_pct ≥ 5%
- G2a/b/c performance/social/retail_media delta ≥ +5%
- G3 TRPs delta ≤ -3%
- G4 optimization_converged = True
- G5 status == 'ok'
- G6 insight non-vacuous

### Pre-fix test outcome (RED)

```
3 passed, 6 failed.
G1: lift_pct ≥ 5.0 (got 0.00) — FAILED
G2a/b/c: all +0.00% — FAILED
G3: tv_trps delta = +0.00% — FAILED
G6: insight «прирост +0.0%» — FAILED
```

### Post-fix test outcome (GREEN)

```
9 passed, 0 failed.
G1: lift_pct = 16.40 ✓
G2a: performance +100% ✓
G2b: social +100% ✓
G2c: retail_media +100% ✓
G3: tv_trps_brand -8.40% ✓
```

### Real Kagocel pickle (production-style validation)

```
lift_pct: 28.3%                          ← matches scipy direct repro
converged: True
binding: False
converged_at_current: False
n_starts: 9 n_converged: 9
best_objective: -10.3923

OLV         : 107M -> 214M (+100.00%)    ← upper bound
Banners     : 113M -> 227M (+100.00%)    ← upper bound
Social      : 15M  -> 30M  (+100.00%)    ← upper bound
RetailMedia : 15M  -> 30M  (+100.00%)    ← upper bound
Performance : 23M  -> 47M  (+100.00%)    ← upper bound
TRPs        : 3.31B -> 3.04B (-8.30%)    ← balances budget

KKT condition satisfied: at optimum, mROAS_money ≈ Lagrange multiplier для interior channels.
TRPs at interior (not binding) → mROAS = λ = 0.032
Small channels at upper bound → mROAS_money падает (Hill saturation deeper) but they're at constraint, λ-condition не applies.
```

### Regression check — все предыдущие тесты

```
test_audit_of_sprint3      : 20/20 PASS
test_causal_m0             : 39/39 PASS
test_causal_m1             : 25/25 PASS
test_causal_m2             : 34/34 PASS
test_causal_m3             : 23/23 PASS
test_causal_m4             : 28/28 PASS
test_math_correctness      : 156/156 PASS
test_narrative_adapter     : 65/65 PASS
test_posterior_ci          : 82/82 PASS
test_roi_verdict           : 36/36 PASS
test_optimizer_kagocel...  : 9/9 PASS (NEW)
                            ━━━━━━━━━━
Total: 517/517 (was 508 + 9 new, no regressions)
```

---

## Known limitations / out-of-scope

1. **Hierarchical decay shrinkage on small N.** Phase 1.1 logit-normal prior pulled все decays Kagocel к ~0.245 ± 0.003 — не bug, но UX implication: при small N (≤30) prior dominates posterior → каналы выглядят interchangeable → CI overlap → «Высокая неопределённость» verdict для всех. Documented but not fixed (требует prior recalibration или Sprint 4+ stronger shrinkage controls).

2. **Multi-start cost scaling.** Текущие 13 starts достаточны для n_ch ≤ 10. При больших portfolios (15+ каналов) может потребоваться cap (e.g. only top-K pivots from greedy mROAS rank) для удержания sub-second wall-clock.

3. **Non-money mode (all uc=1).** Refactor работает unchanged — money == native когда все uc=1. Tests cover both cases.

4. **Native-only constraint mode (legacy).** Pre-fix имел path `constraints = {sum x = total_budget}` (native sum). После refactor — money path unconditionally. Native-only mode обрабатывается тривиально (когда all uc=1). Совсем mixed-units без money_target — uncovered (see line 357-374 unit_smell guard — продолжает блокировать invalid configs).

---

## Narrative implications (Section B context)

`converged_at_current` flag должен подключиться к `narrative_adapter._derive_narrative_facts()` и render_recommendation/render_executive_summary в HTML/PPTX. Это часть Section B follow-up session (separate audit).

Текущий fix добавляет `converged_at_current=True` в insight string (минимальная честная формулировка) но full SCQAR/findings integration ждёт verdict-system unification (план's Section B).

---

## Files changed

```
sidecar/econometrica/engines/optimizer.py     (refactor lines ~398-595, +85/-50 LOC)
tools/test_optimizer_kagocel_redistribution.py (NEW, 230 LOC)
docs/MATH_AUDIT_v1_4_OPTIMIZER_FIX.md         (NEW, this file)
SPRINT3_PROGRESS.md                            (append session log)
```

---

**Маша, 2026-04-28**
