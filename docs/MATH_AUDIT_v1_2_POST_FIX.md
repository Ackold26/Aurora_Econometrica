# Math Audit v1.2 — Post-Fix Critical Review

**Date:** 2026-04-25
**Scope:** все commits в branch `math-fix-v1.0.13` (Phases 1-7 + post-audit hardening 58e6cf1)
**HEAD:** `aef2106` (before this audit)

---

## Executive Summary

Прошёл детальный обзор всех 8+ commit'ов math-fix серии. Найдено **8 потенциальных дефектов** в post-fix коде:

- 🔴 **2 P0** (real correctness bugs in edge cases)
- 🟡 **4 P1** (subtle inconsistencies / methodological)
- 🟢 **2 P2** (efficiency / docs)

---

## 🔴 P0 — Real bugs

### A1. Empty-channel scenario corruption (modeler.py:254)

**Code:**
```python
media_means = X_media.mean().replace(0, 1)  # avoid div/0 for empty channels
X_media_norm = X_media / media_means
```

**Bug:** if a channel has all zeros in training data, `mean=0` → silently replaced with 1. Pickle saves `media_means[col]=1`. In subsequent scenario:

```python
# scenario.py:117
mean = norm['media_means'].get(col, 1)  # = 1 from corrupted pickle
x_norm = spend_t_adstock / max(mean, 1e-10)  # = spend_t (raw scale!)
sat = hill_function([x_norm], alpha=p['alpha'], gamma=p['gamma'])  # saturated at huge x
contribution = p['beta'] * sat[0]  # β ≈ prior mean, sat≈1 → fake "prediction"
```

**Impact:** User submits a media plan with budget on a channel that had ZERO variance in training. β for that channel = prior (HalfNormal(0.3) mean ≈ 0.24). x_norm = raw spend (huge). Hill saturates ≈ 1. Output ≈ 0.24 × y_std contribution per period — looks plausible but is **fabricated** from prior, not learned.

**Severity:** P0 — silently produces fake predictions. UI doesn't surface that the channel was effectively a constant during training.

**Fix:** track which channels had zero variance, mark them in pickle, skip in scenario/optimizer.

---

### A2. Decomposer ROI thresholds calibrated for OLD broken decomposer

**Code (decomposer.py:218-244):**
```python
if roi > 50 and ch['unit_smell']:
    ch['verdict'] = 'ROI завышен (не рубли?)'
elif roi > 50:
    ch['verdict'] = 'ROI подозрительно высок'
elif roi < 0.8:
    ch['verdict'] = 'Убыточный'
elif roi < 1.0:
    ch['verdict'] = 'На грани окупаемости'
elif gap <= -10:
    ch['verdict'] = 'Перенасыщен'
...
```

**Bug:** these thresholds were calibrated for **pre-Phase-3** decomposer that used `|β|/Σ|β|` proportional. After Phase 3 fix, channel contribution = `β × hill(adstock(x)/mean) × y_std`. The numerical magnitude shifted. ROI = contribution / spend may now be in different range.

For channels that pre-fix had ROI ≈ 1.5 (correctly) and post-fix have ROI ≈ 0.8 (still correct, just lower attribution due to saturation), would now be flagged "Убыточный" — UI shows red banner for healthy channel.

**Impact:** false-positive verdicts → client confusion → lost trust в model.

**Severity:** P0 — visible to client, mis-categorizes channels.

**Fix:** recalibrate thresholds against post-fix Kagocel data OR move to relative thresholds (e.g., bottom-quartile ROI = "underperforming").

**Workaround for ship:** keep current thresholds, document in CHANGELOG that ROI scale shifted, advise client to compare against pre-fix only via incremental ROAS not absolute ROI.

---

## 🟡 P1 — Inconsistencies / methodological

### B1. Gamma floor inconsistency

| File | Line | Floor |
|------|------|-------|
| `scenario.py` | 120 | `max(p['gamma'], 0.01)` |
| `optimizer.py` | 126 | `max(p['gamma'], 1e-6)` |
| `decomposer.py` | 93 | `max(float(...), 1e-6)` |

**Impact:** for very small posterior γ (rare but possible), scenario returns different sat than optimizer/decomposer. Numerical precision concern only — γ = 0.001 vs 1e-6 differs 1000× in `γ^α` but Hill output near 1 either way.

**Fix:** standardize to `1e-6` everywhere.

### B2. Adstock config schema

modeler/scenario assume str (`adstock_config[col] = 'geometric'`).
decomposer post-audit added defensive isinstance check.

**Inconsistent.** Should standardize to str OR centralize parser in `utils/adstock.py`.

**Fix:** add `parse_adstock_type()` helper in utils.

### B3. Decomposer insight magic-0.5 multiplier (line 254)

```python
lift = abs(worst['efficiency_gap']) * 0.5
insight += f"...даст ожидаемый прирост +{lift:.1f}% продаж."
```

**Bug:** `efficiency_gap × 0.5` is fabricated heuristic, not from model. Tells client "expected lift +X%" without grounding в actual posterior or counterfactual scenario.

**Fix:** either remove the lift estimate from insight OR compute via real scenario simulation.

### B4. Scenario baseline doesn't include controls

**Code (scenario.py:104):**
```python
baseline_per_period = intercept_mean * y_std + y_mean  # constant!
```

vs decomposer (decomposer.py:154-165) includes `control_effect_per_period`.

**Impact:** Same training period scenario shows different baseline_kpi than decomposer. Inconsistency observable when user runs scenario on historical period (rare but possible flow).

**Acceptable for FUTURE scenarios** (no future control values). Document as expected.

---

## 🟢 P2 — Efficiency / docs

### C1. Modeler posterior means extracted twice
Lines 527 + 613 (intercept), 528 + 590 (media_betas), 529 + 591 (alphas), 530 + 592 (gammas). Wasted compute (small — already-cached InferenceData).

**Fix:** extract once after MCMC, reuse.

### C2. media_plan silent padding/truncation in scenario (lines 90-93)
User submits N periods, scenario silently pads with zeros if shorter or truncates if longer. No warning.

**Fix:** log warning, expose in result.

---

## Recommended fix scope

**Must-fix in this session:**
- **A1** Empty-channel detection — track in modeler, reject in scenario
- **B1** Gamma floor unification — 1-line fix per file

**Should-fix:**
- **B3** Decomposer insight — remove magic 0.5 (or compute properly)
- **B2** Adstock schema centralization — small refactor

**Document only:**
- **A2** ROI thresholds — needs Kagocel data recalibration (post-live-test)
- **B4** Scenario baseline — acceptable for forward use case
- **C1**, **C2** — efficiency / UX polish

---

## Testing strategy

For A1 (empty-channel): add test that simulates training data with zero-variance channel, verify:
1. Modeler flags channel в pickle (e.g., `untrained_channels: ['CH']`)
2. Scenario rejects spend > 0 for that channel with `UNTRAINED_CHANNEL` error code

For B1: add test that scenario/optimizer/decomposer produce same Hill output on edge γ=1e-7.

---

## Risk assessment

- **A1 likelihood:** Medium (only triggers if all-zero channel made it past validator into training)
- **A1 impact:** High (silent fake numbers shown to client)
- **A2 likelihood:** High (post-fix Kagocel data may have different ROI ranges; thresholds NOT recalibrated)
- **A2 impact:** Medium (visible UI mislabel, but numerical underlying correct)

**Conclusion:** A1 fix landed before commercial ship, A2 documented in CHANGELOG.
