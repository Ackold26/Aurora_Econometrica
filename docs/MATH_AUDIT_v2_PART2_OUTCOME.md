# Math Audit v2.0 Part 2 — Outcome (γ recalibration + hierarchical thresholds)

**Branch:** `math-fix-v1.0.13`
**Established:** 2026-05-03 (Этап 5 of optimizer-audit follow-up plan)
**Plan ref:** `~/Desktop/optimizer-audit-followup-plan.md`, этап 5.
**Predecessor:** `MATH_AUDIT_v2_0_FORECAST_HORIZON.md` §7 L4/L5 deferred items.

---

## Executive summary

Phase 2.0 Part 2 закрывает 2 deferred lock decisions:

| Item | Original status | New status |
|---|---|---|
| **L4 — γ recalibration** | DEFAULT γ=0.3, recalibrate after real MMM training | ❌ **OBSOLETE** — architecture pivoted к tier-based в Phase 2 S3 synergy |
| **L5 — Hierarchical extrapolation threshold** | Generic warning shipped, quantitative threshold deferred | ✅ **LOCKED at 3× (M8 convention)** + helper shipped |

---

## L4 — γ recalibration → OBSOLETE

### Why obsolete

Original plan (MATH_AUDIT_v2_0 §5):
> If observed posterior CI width understates true epistemic uncertainty by factor f(ratio), fit:
> `f(r) ≈ 1 + γ × (r - 1)` where r = x_forecast / x_observed_p95
> Lock γ ∈ [0.2, 0.5] based on fit.

**Phase 2 audit pass 2 (2026-05-02) S3 synergy** уже заменила γ-based CI inflation на
tier-based `extrapolation_severity` (0/1/2/3) integrated в `verdict_tier`. См.
`utils/posterior_propagation.py:191` — leading comment:

> «Phase 2 S3 (audit pass 2 2026-05-02): extrapolation_severity gate replaces
> plan's separate inflate_extrapolation_uncertainty(γ=0.3) helper. Reuses
> Aurora's established 3-tier vocabulary вместо ad-hoc CI multiplier — single
> mental model для customer (model fit verdicts AND forecast verdicts in same
> taxonomy).»

The `inflate_extrapolation_uncertainty(γ)` helper was **never shipped** в код —
S3 synergy redirected это к existing 3-tier infrastructure до Phase 2.1 ship.

### Verification

```bash
$ grep -rn "inflate_extrapolation_uncertainty\|gamma.*=.*0\.3" sidecar/econometrica/
(no matches)
```

`extrapolation_severity` integrated с verdict_tier:
- 0 (in-zone, ≤ p95) → no effect
- 1 (p95 boundary) → no auto-downgrade (caller may annotate)
- 2 (p99 extrapolation) → force ≥ "Направленная" tier
- 3 (≥3× p99) → force "Высокая неопределённость"

Customer мental model preserved: same vocabulary для model fit AND forecast verdicts.

### Conclusion

**L4 closed via architectural pivot, not recalibration.** No code change needed
для Phase 2.0 Part 2. Documentation updated к reflect actual ship.

---

## L5 — Hierarchical extrapolation threshold

### Plan goal

> При hierarchical model + extreme budget extrapolation, β posterior shrinkage
> может pull brand top-performer estimates toward group mean, underestimating
> its true contribution. Customer должен be warned + cross-check с flat model.

### Synthetic experiment

`tools/audit_v2_part2_hierarchical.py` runs flat vs hierarchical optimization
comparison на synthetic data:
- 6 channels (3 brand с heterogeneous βs + 3 perf)
- Flat pickle: TV brand β=0.140 (top performer), other brand βs 0.045-0.060
- Hierarchical pickle: 50% pool shrinkage applied к brand βs (TV brand → 0.111,
  others pulled toward mean 0.082)
- Optimize at budget ratios {1×, 2×, 3×, 5×} с bounds 0%/500%
- Metrics: cosine similarity, L1 divergence, top-performer allocation diff

**Snapshot:** `docs/audit_v2_part2_hierarchical_results.json`

### Key finding: shrinkage preserves rankings → optimizer allocations identical

```
ratio | L1_div% | cos_sim | lift_flat | lift_hier | top_flat       | top_hier       | underest%
  1.0 |    0.00 |  1.0000 |      0.00 |      0.00 | 157,785,236    | 157,785,236    |       0.00
  2.0 |    0.00 |  1.0000 |     19.10 |     19.10 | 315,570,472    | 315,570,472    |       0.00
  3.0 |    0.00 |  1.0000 |     24.10 |     24.10 | 473,355,708    | 473,355,708    |       0.00
  5.0 |    0.00 |  1.0000 |     27.10 |     27.10 | 788,926,180    | 788,926,180    |       0.00
```

При proportional shrinkage (50% pool pull для всех brand channels) ranking сохраняется
(TV brand still highest β=0.111 vs OOH 0.071 vs OLV 0.064) → optimizer allocations
identical.

### Real risk: decompose ROI attribution underestimation

Optimizer cares about β **ratios** (gradient direction); decompose/scenario care
about β **absolute values** (KPI numbers).

При hier shrinkage с TV brand 0.140 → 0.111 (≈21% drop), customer-facing reports:
- ROI per period для TV brand: contribution = β × hill × y_std → ≈21% lower
- mROAS (marginal ROAS) для TV brand: ≈21% lower
- Channel ranking by ROI preserved, но absolute value misleading

Customer может interpret «TV не работает» когда actually hierarchical pulled top
performer toward mean.

### Threshold lock — 3× (M8 convention)

Threshold **3.0** для brand budget ratio matches Aurora's M8 saturation drift
detection convention (см. `forecast_validation.saturation_drift_check`):
> ratio_spend ≥ 3.0 → severity='critical'

Consistency: same threshold for spend-zone-warning AND hierarchical-pooling-warning
→ single mental model для customer.

### Helper shipped

`utils/forecast_validation.hierarchical_extrapolation_warning()` — conditional
warning helper:

```python
def hierarchical_extrapolation_warning(
    model_data: dict,
    *,
    forecast_budget_money: float,
    train_total_money: float,
    brand_drift_threshold: float = 3.0,
) -> dict | None:
    """Conditional warning о hierarchical pooling underestimation."""
    ...
    return {
        'severity': 'warn',
        'message_ru': '...',
        'category_filter': 'brand',
        'forecast_ratio': ratio,
        'brand_channels': brand_channels,
        'threshold': brand_drift_threshold,
    }
```

Returns `None` for:
- Non-hierarchical models
- No brand channels
- Ratio ≤ threshold
- Invalid training budget

### Tests

`tools/test_forecast_validation_hierarchical.py` — **21 tests:**
- 8 categorical edge cases (None paths)
- 1 above-threshold trigger
- 1 boundary check (3× exactly → None)
- 2 custom threshold parametric
- 2 message format checks
- 7 ratio sweep (parametric 1×→100×)

**21/21 PASS in 2.46s.**

### UI integration

Helper is **standalone** — UI panel должен call it после optimize() в planning
mode. Not auto-injected в optimize() output to keep separation of concerns.

Recommended call site (Svelte): `OptimizeStep.svelte` → after successful optimize,
read pickle metadata, call helper, display secondary warning panel если warning
returned.

```js
// Frontend pseudo-code
const warning = await invoke('econ_hierarchical_warning', {
  projectDir,
  forecastBudgetMoney: totalBudgetMoney,
  trainTotalMoney: currentMoney,
});
if (warning) showWarningBanner(warning.message_ru);
```

Tauri command + Rust IPC stub deferred к UX session (optional polish; helper
itself is production-ready).

---

## Acceptance gates (2026-05-03)

| Gate | Command | Result |
|---|---|---|
| Pytest | `pytest tools/ -n auto` | ✅ **820 passed** + 5 skipped |
| svelte-check | `npx svelte-check --threshold error` | ✅ 0 errors |
| Cargo check | `cargo check` | ✅ clean |

Helper tests: 21/21 PASS in 2.46s parallel.

---

## Files Modified

```
sidecar/econometrica/utils/forecast_validation.py    (+65 LOC)   # helper added
tools/audit_v2_part2_hierarchical.py                  (+~350 LOC) # exploratory harness
tools/test_forecast_validation_hierarchical.py        (+~170 LOC) # 21 tests
docs/audit_v2_part2_hierarchical_results.json         (snapshot)
docs/MATH_AUDIT_v2_PART2_OUTCOME.md                   (этот файл)
```

---

## Future work (not blocking ship)

1. **UI panel integration** — Tauri `econ_hierarchical_warning` command + Svelte
   panel в `OptimizeStep.svelte`. Cosmetic UX polish (~1-2 hours).
2. **Real Bayesian MCMC validation** — when customer data available + numpyro/PyMC
   environment ready, refit 30 bootstrapped models and validate 50% shrinkage
   assumption empirically. Currently synthetic estimate is theory-driven.
3. **Decompose-side warning duplication** — currently helper called from optimizer
   path; могло бы be also called в decompose() для legacy report scenarios.

---

**Этап 5 → DONE 2026-05-03.** L4 obsolete confirmed; L5 quantitative threshold
shipped via helper + tests + docs. All 5 etaps of optimizer-audit follow-up plan
закрыты в одной MAX session.
