# Decomposer Engine Invariants Registry — formal spec

**Branch:** `math-fix-v1.0.13`
**Established:** 2026-05-03 (Phase B1 of engine audit extension)
**Property-based tests:** `tools/test_decomposer_invariants.py` (114 tests)
**Edge cases:** `tools/test_decomposer_edge_cases.py` (27 tests)
**Math refs:**
- `docs/MATH_AUDIT_v1_3_PHASE_0_1.md` — mROAS chain rule (3-way alignment)
- `engines/decomposer.py:487-505` — energy conservation residual absorption

---

## Purpose

Formal contract for `engines/decomposer.py:decompose`. Сверяться при refactor.

---

## Invariants

### D1 — Energy conservation

```
total_sales == baseline + media_contribution   (within 1.5% rounding tolerance)
```
Guaranteed by post-audit fix (decomposer.py:487-505): residual absorbed into baseline:
```
residual_per_period = y_actual - model_predicted_per_period
baseline_per_period = raw_baseline + residual_per_period
```

**Test:** `test_D1_energy_conservation` × 15 seeds.

---

### D2 — Per-channel contribution sign

For positive `β` and positive raw spend:
```
contribution_ch >= 0   (Hill saturation ∈ [0, 1) — non-negative)
```

**Test:** `test_D2_contribution_sign_matches_beta` × 10 seeds.

---

### D3 — ROI compute identity

```
roi_ch == round(contribution_ch / spend_money_ch, 2)
spend_money_ch == 0  →  roi_ch == 0  (explicit guard)
```

**Test:** `test_D3_roi_compute_identity` × 15 seeds.

---

### D4 — mROAS alignment с optimizer (3-way alignment)

Both engines call `engines.optimizer._compute_mroas_money` с same inputs (current
spend, n_periods=train_n in analyst/decompose mode) → identical mROAS within 1e-3.

**Test:** `test_D4_mroas_alignment_with_optimizer` × 10 seeds. Cross-check via
`tools/test_optimizer_kagocel_redistribution.py` L4-4.

---

### D5 — Share-of-spend / share-of-effect totals

```
Σ share_of_spend ≈ 100%
Σ share_of_effect ≈ 100%
```
within 1.0pp tolerance (round-1 на shares).

**Test:** `test_D5_shares_sum_to_100` × 10 seeds.

---

### D6 — efficiency_gap identity

```
efficiency_gap_ch == round(share_of_effect_ch - share_of_spend_ch, 1)
```

**Test:** `test_D6_efficiency_gap_identity` × 10 seeds.

---

### D7 — Verdict thresholds

| ROI | Verdict | Tone |
|---|---|---|
| < 0.5 | Глубоко убыточный | bad |
| < 0.8 | Убыточный | bad |
| < 1.0 | На грани окупаемости | warn |
| > 50 + unit_smell | ROI завышен (не рубли?) | warn |
| > 100 | ROI нереалистичен (артефакт) | warn |
| > 5.0 (no smell) | Высокоэффективен | good |

Plus efficiency_gap fallback (gap < -10 → Перенасыщен; gap > +10 → Высокоэффективен).
Plus quantile mode (N ≥ 20 channels + portfolio benchmarks).
Plus wide-CI suffix «(широкий ROI-интервал)» when `roi_ci_high - roi_ci_low > roi`.

**Tests:** `test_D7_verdict_thresholds`, `test_D7_wide_ci_suffix`.

---

### D8 — Action vocabulary alignment

`compute_channel_action` shared helper между decomposer + optimizer + narrative
adapter. Action key ∈ `{Scale, Hold, Watch, Reduce, Cut, Uncertain}`. Each channel
has `action`, `action_label`, `action_tone`, `action_reasoning`, `action_priority`,
`action_confidence`.

**Test:** `test_D8_action_decoration_present` × 10 seeds.

---

### D9 — Time-series sum consistency

```
Σ_t time_series.channels[col][t] ≈ channels[col].contribution   (round-1 + round-0 → ≤1%)
```

**Test:** `test_D9_time_series_sum_consistency` × 10 seeds.

---

### D10 — Untrained channel zero-contribution + 'Не обучен' verdict

For channels marked untrained (via `params.untrained` OR `normalization.untrained_channels`):
- `contribution == 0.0`
- `verdict == 'Не обучен'`
- `action == 'Uncertain'` + `action_label == 'Не обучен'`
- `untrained == True`
- `ci_skip_reason == 'untrained_channel'`

**Inline fix 2026-05-03:** added `params.untrained OR col in untrained_channels`
guard (Bayesian engine marks via norm-list, OLS via params flag — pre-fix mismatch
gave Bayesian-trained untrained channels spurious contributions).

**Inline fix 2026-05-03:** preserve verdict 'Не обучен' через downstream
verdict + action loops (pre-fix `compute_roi_verdict` overwrote с 'Глубоко убыточный'
for roi=0).

**Test:** `test_D10_untrained_channel_zero_contribution`.

---

### D11 — Waterfall sums correctly

```
waterfall.values: [baseline, ch_1, ch_2, ..., total]
baseline + Σ ch_values ≈ total   (round-0 → ≤1.5% tolerance)
```

**Test:** `test_D11_waterfall_sums` × 10 seeds.

---

### D12 — Posterior ROI CI ordering

When `posterior_samples` available:
```
roi_ci_low ≤ roi ≤ roi_ci_high   (within 10% margin для HDI)
```

**Test:** `test_D12_posterior_roi_ci_ordering` × 10 seeds.

---

### D13 — Determinism

Two consecutive `decompose()` calls produce byte-identical output across all
fields (channels, baseline, total_sales, share_of_*, verdict, action).

**Test:** `test_D13_determinism`.

---

## Pickle compatibility

| `model_version` | Behavior |
|---|---|
| `'1.0'` | `MODEL_OUTDATED` error (z-score normalization deprecated) |
| `'1.0-ols'` | OLS small-data fallback. Frequentist β CI. No posterior CI. Warning shown. |
| `'1.1'` | Bayesian. No adstock posterior. Warning «переобучите». |
| `'1.1.5'` | Bayesian. Hardcoded adstock decay. Warning о carryover CI. |
| `'1.2'` | Bayesian + learnable adstock (current production). No warning. |
| `'1.3'` | Hierarchical Trust 3 (brand vs perf). Hierarchical metadata exposed. |

**Tests:** `test_A1` через `test_A6` в edge cases.

---

## Summary

| ID | Property | Test reference |
|---|---|---|
| D1 | Energy conservation | invariants × 15 |
| D2 | Contribution sign | invariants × 10 |
| D3 | ROI compute identity | invariants × 15 |
| D4 | mROAS alignment с optimizer | invariants × 10 |
| D5 | Share-of-spend/effect sums | invariants × 10 |
| D6 | efficiency_gap identity | invariants × 10 |
| D7 | Verdict thresholds | 2 tests |
| D8 | Action vocabulary | invariants × 10 |
| D9 | Time-series consistency | invariants × 10 |
| D10 | Untrained zero-contribution | 1 test (verifies 2 inline fixes) |
| D11 | Waterfall sums | invariants × 10 |
| D12 | Posterior ROI CI ordering | invariants × 10 |
| D13 | Determinism | 1 test |

Plus 27 edge cases в `tools/test_decomposer_edge_cases.py` (6 batches A-F).

---

## How to add new invariant

1. Append к этому doc в same format.
2. Add property test с pytest.parametrize for ≥10 seeds.
3. Update summary table.
4. Run `pytest tools/test_decomposer_invariants.py -n auto`.
