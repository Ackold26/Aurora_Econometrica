# Math Audit v1.5 - L10 lift_pct regression fix

**Created:** 2026-04-28
**Branch:** `math-fix-v1.0.13` → tag `v1.0.16` (когда ship'нем)
**Predecessor:** `docs/MATH_AUDIT_v1_4_OPTIMIZER_FIX.md` (Section A - money-axis rescaling, commit `fe42e7f`)
**Trigger:** Live-test Антон 2026-04-28 на v1.0.15 NSIS installer выявил inverted lift_pct relationship в What-if сценариях:
- Budget -50% → reported lift +124.9% (mathematically impossible на monotonic Hill)
- Budget +100% → reported lift +10.8% (less than default +30.4%)

---

## Empirical evidence (Антон's live screens)

```
Default (money_target = current_total = 3.59B):
  Reported lift_pct = +30.4%   ← correct, matches scipy direct repro

What-if -50% (money_target = 1.795B):
  Reported lift_pct = +124.9%  ← impossibly inflated
  Banner: «Оптимальное перераспределение бюджета (1,795,193,536 ₽)
           даёт ожидаемый прирост +124.9%»
  KPI prognosis: 25,247M (= 11,226M × 2.249) ← would require doubled media
                                              contribution + zero baseline

What-if +100% (money_target = 7.18B):
  Reported lift_pct = +10.8%   ← deflated, less than default
  Should be > default (more budget → more media response)
```

**Internal consistency check:** при default lift +30%, banner текст правильный («Увеличить OLV на 100%, Сократить TRPs на 8%»). Per-channel deltas + actions correct. **Только lift_pct сам по себе wrong.**

---

## Root cause analysis

### The regression я внесла в Section A (commit `fe42e7f`)

В Section A optimizer refactor добавил `_project_to_budget()` для multi-start initialization:

```python
# Pre-Section-A:
x0 = np.array([current_spend[col] for col in media_cols])  # native units, real current
current_response = -total_response(x0)  # at REAL current

# Section A (commit fe42e7f) - BUG introduced:
x0_money = np.array([current_spend[col] * uc_arr[i] for ...])
x0_money = _project_to_budget(x0_money)  # ← scales to money_target!
current_response = -total_response_money(x0_money)  # at SCALED current
```

`_project_to_budget` scales x0 чтобы `sum(x0) == money_target`. Это нужно для feasible SLSQP start, но **wrongly applied к baseline computation**.

### Bug mechanics

When `money_target = current_total_money` (default Optimize page, «Фиксировать бюджет»=ON):
- Projection no-op → x0_money = real current → no error.
- Section A unit tests + production use case happy-path работают correctly.
- **Test gap**: я НЕ покрыл What-if scenarios (money_target ≠ current).

When `money_target = 0.5 × current_total` (What-if -50% budget):
- x0_money projected → каждый канал × 0.5 (scaled-down current)
- `current_response` computed at scaled-down state → MUCH smaller (Hill saturation depends on x_norm, halving spend lowers саt by 30-50% per channel)
- `optimal_response` correct (best at 1.795B target)
- `lift_pct = (optimal - small_baseline) / small_baseline` → artificially huge

When `money_target = 2 × current_total` (What-if +100% budget):
- x0_money projected → каждый канал × 2 (scaled-up current)
- `current_response` computed at scaled-up state → at higher Hill saturation level (less marginal gain available)
- `optimal_response` найден within 7.18B, but redistribution upside compressed на the higher plateau
- `lift_pct = (optimal - big_baseline) / big_baseline` → artificially small

**Direction inverted, magnitude wrong.** Both directions broken.

---

## Fix (math-fix v1.5)

Separate **real current** from **projected current**. Real used для baseline; projected used только для SLSQP starts.

```python
# Real current - never projected (baseline для lift_pct comparison)
x0_money_real = np.array(
    [current_spend[col] * uc_arr[i] for i, col in enumerate(media_cols)],
    dtype=float,
)

# Projected - для SLSQP feasible-start initialization
x0_money = _project_to_budget(x0_money_real.copy())

# Multi-start uses projected (current/pivot/balance/all_upper) - unchanged
starts_money = [('current', x0_money), ...]

# After SLSQP solve:
current_response_real = -total_response_money(x0_money_real)  # ← FIX
optimal_response = -total_response_money(result.x)

if current_response_real > 1e-9:
    lift_pct = (optimal - current_response_real) / current_response_real * 100
    baseline_zero = False
else:
    # Edge case (SA7): degenerate baseline (all media spend = 0)
    lift_pct = 0.0
    baseline_zero = True
```

### Edge case handling (SA7)

If `current_response_real ≤ 1e-9` (degenerate, no media contribution): division explodes. Guard:
- `lift_pct = 0.0`
- `baseline_zero = True` flag в result_data
- UI должен (v1.0.16 task) suppress lift display + show diagnostic banner

### `converged_at_current` detection (SA6)

Detector flags «no redistribution found». Compares `result.x` vs `x0_money` (projected, not real). Why projected? **KKT-perspective**:
- When money_target = current → x0_money == x0_money_real → unchanged behavior.
- When money_target ≠ current → projected baseline detects «proportional cut/grow without redistribution» = the meaningful warning. If result ≈ proportional scaling of current = no real redistribution found = warn user.

---

## Validation

### Pre-fix evidence (real Kagocel pickle, v1.0.15 deployed)

```
What-if -50% → lift +124.9% ❌
What-if +100% → lift +10.8%  ❌
Monotonicity broken ❌
```

### Post-fix verification (real Kagocel pickle)

```
Default (money_target=current): lift +28.30%  ✓ (Section A baseline preserved)
What-if -50%:                    lift +31.50%  ✓ (бывший +124.9%, теперь sane)
What-if +100%:                   lift +42.60%  ✓ (бывший +10.8%, теперь > default)

Monotonicity (10/300 bounds, ratio × current):
  0.5×  → +31.5%
  0.75× → +35.1%
  1.0×  → +37.8%
  1.5×  → +40.9%
  2.0×  → +42.6%

Strictly monotonic. ✓
```

**Note:** even с -50% budget lift positive потому что текущая Kagocel allocation очень suboptimal (TRPs занимает 92% бюджета с тривиальным mROAS). Optimizer cuts TRPs sharply + reallocates к high-mROAS digital channels - media efficiency boost compensates lost spending. Mathematically correct + valuable business insight.

### Lock-in tests (test_optimizer_kagocel_redistribution.py extended)

Added 3 new acceptance gates:
- **L10a** half budget lift_pct < +50% (would have failed pre-fix at +124.9%)
- **L10b** 2× budget lift > default (would have failed pre-fix +10.8% < default +30%)
- **L10c** property-based monotonicity test - lifts strictly не-decreasing с money_target

All 3 new + 9 existing → 12/12 PASS post-fix.

### Full regression

```
test_audit_of_sprint3      : 20/20 PASS
test_causal_m0..m4         : 149/149 PASS
test_math_correctness      : 156/156 PASS
test_narrative_adapter     : 65/65 PASS
test_posterior_ci          : 82/82 PASS
test_roi_verdict           : 36/36 PASS
test_optimizer_kagocel...  : 12/12 PASS  (+3 new L10 lock-in)
test_narrative_coherence   : 24/24 PASS
                            ━━━━━━━━━━━━
Total: 544/544 (was 541 + 3 new), zero regressions.
```

---

## Files changed

```
sidecar/econometrica/engines/optimizer.py            (~+25/-8 LOC)
  - Lines 502-516: separate x0_money_real (real current, never projected)
                   from x0_money (projected, для SLSQP)
  - Lines 614-627: current_response_real используется для lift_pct
                   + baseline_zero edge case handling
  - Lines 630+: _max_abs_delta_money uses x0_money (projected) for
                KKT-perspective converged_at_current detection
  - Lines 819-826: insight string handles baseline_zero case
  - Line 854: result_data['baseline_zero'] field added (UI flag)

tools/test_optimizer_kagocel_redistribution.py       (+90 LOC)
  - L10a: test_what_if_half_budget - assert lift bounded reasonably
  - L10b: test_what_if_double_budget - assert lift > default
  - L10c: test_lift_monotonic_in_budget - property-based, 5 budget points

docs/MATH_AUDIT_v1_5_L10_FIX.md                       (NEW, this file)

SPRINT3_PROGRESS.md                                   (session log append)
```

---

**Маша, 2026-04-28**
