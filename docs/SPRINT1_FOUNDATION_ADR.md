# Sprint 1 Foundation — Architectural Decision Record

**Created:** 2026-04-26
**Status:** APPROVED (5 decisions confirmed Антоном) + RESEARCH-DRIVEN AMENDMENTS pending review
**Predecessor:** `docs/MATH_AUDIT_v1_3_PHASE_0_1.md`, `project_econometrica_sprint1_foundation.md` (memory)
**Branch:** `math-fix-v1.0.13` (or `master` after merge)

This ADR consolidates Sprint 1 Foundation architecture decisions for Aurora Econometrica's math evolution after v1.0.13 ship. Covers Phase 1.9 (Posterior CI propagation), Phase 1.1 (Joint adstock+Hill MCMC), and A4 (Pre-MCMC reliability).

---

## 1. Context

Aurora Econometrica v1.0.13 shipped 2026-04-26 with foundational math bugs closed (chain rule, narrative, optimizer trivial scaling). Now begins Sprint 1 Foundation — math evolution that's mandatory before:
- Sprint 2 small-data path (n=12-30)
- Sprint 3 Pharma Causal premium module

Without Sprint 1, downstream sprints build on broken uncertainty quantification, hardcoded adstock, and no model-fitness gates.

**Sequence:** 1.9 → 1.1 → A4, three separate ships v1.0.14/15/16. Justified because Phase 1.9 delivers immediate visible value (CI in reports) without breaking pickle compatibility, and Sprint 3 Pharma Causal absolutely requires honest CI for compliance narrative (ФЗ-38, ОРД, ФАС).

---

## 2. Decisions Recap (Антон confirmed 2026-04-26)

| # | Decision | Status |
|---|---|---|
| D1 | Adstock priors structure: hierarchical (b) | ⚠️ AMENDED by research (see §3) |
| D2 | Calendar: research до 31 мая, implementation после Платформы, ship 15-30 июня (v1.0.14) | ✅ confirmed |
| D3 | A4 audience: hybrid (c) — marketing summary + analyst expandable | ⚠️ AMENDED — budget недооценён, see §6 |
| D4 | Validation: Kagocel + Venarus + MMX + production pickles | ✅ confirmed, dataset metadata validated |
| D5 | Sequence: 1.9 → 1.1 → A4, 3 ships v1.0.14/15/16 | ✅ confirmed |

---

## 3. Research-Driven Amendments

### Amendment A1 (Phase 1.1) — Hierarchical structure: Beta-Beta → Logit-Normal

**Problem identified:** Beta-Beta `Beta(μ·κ, (1-μ)·κ)` reparameterization is academically clean but suffers from funnel geometry → divergences and 5-10× MCMC slowdown if not non-centered properly. Beta doesn't admit clean location-scale split for non-centering.

**Recommendation (Stan/PyMC discourse, Gelman):**

```python
# Logit-normal hierarchy (non-centers cleanly, no funnel)
mu_logit ~ Normal(-1.0, 0.7)        # sigmoid(-1.0) ≈ 0.27 — monthly TV-realistic
sigma_logit ~ HalfNormal(0.5)        # moderate channel dispersion
z_i ~ Normal(0, 1)                   # per-channel non-centered
decay_i = sigmoid(mu_logit + sigma_logit * z_i)  # bounded [0, 1]
```

**Trade-offs:**
- ✓ Non-centered by construction → no divergences from funnel
- ✓ Works seamlessly in NumPyro NUTS
- ✓ Cleanly extends to per-channel-type structure if needed (mu_logit_brand, mu_logit_perf)
- ✗ Less interpretable than Beta(μ, κ) — "logit space" is statistician language
- ✗ Slightly different prior shape — requires re-validating sensible decay range

**Decision pending Антона:** Pilot logit-normal vs Beta-Beta in 1-2h experiment (synthetic data, check divergences) before committing 12-15h to one. Default: logit-normal.

### Amendment A2 (Phase 1.1) — Monthly priors recalibration

**Problem identified:** Beta(2, 5) mean 0.29 is plausible only for TV. Digital monthly decay should be ≪ 0.1 (most digital carryover is within-period).

**Industry rule conversion (weekly → monthly):**
- TV weekly 0.3-0.8 → monthly 0.006-0.40
- Digital weekly 0.0-0.3 → monthly 0.000-0.008

**Three options:**

**Option A (most honest, most work):** Per-channel-type priors via canonicalPrefix tagging (Aurora already has it):
- Brand TV/Banners: `mu_logit ~ Normal(-1.0, 0.7)` (decay ~0.27)
- Performance/Search/Retail Media: `mu_logit ~ Normal(-2.2, 0.5)` (decay ~0.10)

**Option B (simpler, current plan):** Single hierarchical pool with shifted mu prior:
- `mu_logit ~ Normal(-1.4, 0.7)` (sigmoid(-1.4) ≈ 0.20)
- Hierarchy lets data pull TV decay up + Digital down

**Option C (defer):** Keep `Beta(2, 5)` in v1, document overestimate, fix in v1.5. Risky for production.

**Recommendation:** Option B for v1 (simpler), Option A for v2 if A/B clients need precision. Validation strategy: run on Kagocel/Venarus/MMX, see if Option B's hierarchy correctly separates TV from Digital decay.

### Amendment A3 (Phase 1.9) — CI level: 95% → 90%

**Industry standard:** Meridian (Google), Recast, LightweightMMM all use **90% credible interval** by default. PyMC-Marketing uses 94% (deliberate anti-95% protest, not industry standard).

**Trade-off:** 90% gives tighter brackets that look more "actionable" to skeptical CMOs. 95% is more conservative. Aurora's clients are not used to either — education task either way.

**Decision:** Default 90% CI. Configurable in user settings (advanced) — toggle 80/90/95%.

**Activation in `compute_roi_verdict`:** dormant Step 1 already uses `(roi_ci_high - roi_ci_low) > roi`. This threshold (width > 1.0× point) coincides with industry CV<0.3 reliability rule for 90% CI. **Anchor confirmed.**

### Amendment A4 (Phase 1.9) — Storage: float64 → float32, no thinning

**Research consensus (Vehtari et al. 2021, Link & Eaton 2012):** Thinning is unnecessary and inefficient for percentile estimation. Unthinned chain gives more precise percentiles than any thinned subset.

**Storage math (revised):**
- Aurora: 8000 samples × 7 channels × 8 params × 4 bytes (float32) = **1.8 MB per pickle** (not 3.6 MB float64)
- Scenario expansion: 5 alternatives × 1.8 MB = 9 MB peak — manageable
- For derived KPI/scenario distributions: compute summary stats (mean, p5, p50, p95) and store summary, not 8000 raw samples

**Decision:**
- Persist channel posterior parameters (α, γ, β, intercept, control_betas) as float32, full 8000 samples
- For derived distributions (KPI per scenario, mROAS), store summary stats only (mean + percentiles)
- Tail-ESS check ≥ 100 × n_chains (Vehtari rule) before publishing CI; if fail, annotate "CI оценка нестабильна"

### Amendment A5 (Phase 1.9) — 3-tier verdict labels with conditional gates

**Recommended tiers (industry CV<0.3 anchored):**

| Tier | Width / Point Estimate | Verdict label | Action signal |
|---|---|---|---|
| Высокая точность | < 0.5 | "Уверенная оценка" | Доверять, оптимизировать |
| Средняя точность | 0.5 - 1.0 | "Направленная оценка" (matches existing convention) | Использовать как ориентир |
| Высокая неопределённость | > 1.0 | "Высокая неопределённость" (existing dormant) | Не оптимизировать; recommend test |

**Conditional gates (auto-downgrade):**
- `n_obs < 30` → force min "Средняя точность" (small-N can produce artificially tight CI)
- `R_hat > 1.05` → force "Высокая неопределённость" (model not converged)
- `Tail_ESS < 100 × n_chains` → annotate "CI оценка нестабильна"

These gates align with Phase 1.1 (Pre-MCMC reliability) but operate post-MCMC.

**Decision:** Implement 3-tier in Phase 1.9. Conditional gates feed into Phase 1.1 / A4 framework.

### Amendment A6 (A4) — Test naming and approach

**Problem identified:** "Yang's prior-data conflict test (2009)" cannot be confirmed in literature. Likely conflated with Gåsemyr-Natvig 2009 or other works.

**Recommended actual test:** **Nott et al. 2016 prior-to-posterior KL divergence**:
- Compute KL(prior_i ‖ posterior_i) per channel β
- Calibrate by running prior predictive simulations + computing same KL distribution
- Threshold: γ = 0.05 (standard); tighten to γ = 0.01 on small N

**Renaming:** drop "Yang's test" terminology. Use "Aurora prior-data conflict diagnostic (Nott et al. 2016 KL divergence)."

**Decision:** Adopt Nott 2016 KL approach. Document as Aurora-specific implementation of standard methodology.

### Amendment A7 (A4) — Budget undersized: 15-19h → 32-38h

**Original estimate breakdown:**
- A4.1 prior predictive: 5h
- A4.2 Yang's test: 6-8h
- A4.3 identifiability simulation: 4-6h
- **Total: 15-19h**

**Realistic estimate (research-corrected):**
- A4.1 + UI integration: 6h
- A4.2 (Nott KL only, no Marshall-Spiegelhalter): 8h
- A4.3 (simuk wrapper + per-channel diagnostic): 6h
- **Tier framework UI + override path + Details panel + i18n: 8-10h** ← MISSING from original
- **Documentation + help system entries + IT-doc updates: 4h** ← MISSING from original
- **Total: 32-38h**

**Implication for sequence:** A4 ship date pushes from late July → mid August. v1.0.16 = 2026-08-15 ± 1 week.

**Decision:** Accept revised estimate. Calendar adjusted. Alternative — split A4 into v1.0.16 (math layers only, IT-facing) + v1.0.17 (UI + override + i18n) — but this fragments killer differentiator messaging. Recommend single ship.

### Amendment A8 (A4) — "Refuse to train" UX risk mitigation

**Problem identified:** No production MMM tool refuses to fit (Robyn, LightweightMMM, Recast, PyMC-Marketing all run on anything). Aurora hard-fail is genuinely novel + risk of "your tool is broken, the other one worked" support tickets.

**Mitigation pattern (FDA medical AI 2025 guidance):**
- **NEVER use "refuse" / "cannot"** — language: "Aurora paused training because…"
- **ALWAYS offer escape hatch:** "Override and train anyway with fragile-results banner stamped on every export"
- **Frame as differentiator:** "Aurora is the only MMM that tells you when it can't help — others silently hallucinate ROI"
- **Constructive language:** "Aurora needs more variation in TV/Digital spend to separate them" (constructive, tells what to do) vs "Data is insufficient" (defensive, blames user)

**Decision:** All hard-fail paths must have override-with-banner. No "refuse-or-die" UX anywhere in v1.

---

## 4. Phase 1.9 — Implementation Plan (8-12h, ship v1.0.14)

### Files & precise touchpoints

| File | Lines | Change | Hours |
|---|---|---|---|
| `engines/modeler.py` | 614-617 | Replace `.mean(dim=['chain', 'draw'])` with `.values` (full samples) — extract `media_betas_samples`, `alpha_samples`, `gamma_samples` as np.float32 arrays | 0.5 |
| `engines/modeler.py` | 638-655 | Persist `posterior_samples = {'media_betas': arr, 'alphas': arr, 'gammas': arr, 'intercept': arr, 'control_betas': arr}` in model_data dict | 0.5 |
| `engines/modeler.py` | 660 | Bump `model_version='1.1.5'` (Phase 1.9 schema; backward-compat for v1.1 — read without samples, fallback to point estimate with warning) | 0.1 |
| `engines/decomposer.py` | 154 | Load `posterior_samples = model_data.get('posterior_samples')` | 0.2 |
| `engines/decomposer.py` | 195-249 | Vectorize loop: compute contrib distribution через samples, populate `ch['contribution_ci_low']`, `ch['contribution_ci_high']`, `ch['roi_ci_low']`, `ch['roi_ci_high']`. Use 90% CI = percentiles [5, 95]. | 3.0 |
| `engines/decomposer.py` | 333-334 | Already passes CI to verdict ✓ — no change |
| `engines/decomposer.py` | 397-410 | Result schema: add `waterfall_ci_low/high` arrays for chart error bars | 0.5 |
| `engines/scenario.py` | (TBD) | KPI distribution с CI per scenario; store summary stats (mean, p5, p50, p95) | 1.5 |
| `engines/optimizer.py` | 71-130 | Vectorized variant `_compute_mroas_money_samples()` — accepts samples arrays, returns array of mROAS values | 1.0 |
| `engines/optimizer.py` | 451-476 | Callsite: compute `mroi_current_samples`, populate mean + ci_low/high in result | 0.5 |
| `engines/narrative_adapter.py` | 135 (`_merge_channels`) | Preserve CI fields через merge — usually automatic, verify | 0.3 |
| `aurora_html/sections.py` | (TBD) | Portfolio table: bracket display `2.4× [1.8 — 3.1]`, color badges (green/amber/red by tier) | 1.5 |
| `aurora_pptx/builder.py` | (TBD) | Same bracket display in PPTX tables | 1.0 |
| `tools/test_math_correctness.py` | (TBD) | CI invariance tests: percentiles stable under thinning, conditional gates correct, point estimate = posterior mean | 1.5 |

**Total: ~12h** (slightly over 8-10h estimate due to vectorization complexity in decomposer + tests).

### Backward compatibility

- v1.0/v1.1 pickles (no `posterior_samples` field): fallback to point estimate, show banner "CI недоступны — переобучите для honest uncertainty"
- v1.1.5 pickles: full CI display
- Phase 1.1 will bump to v1.2 (adstock samples)

### Validation

- Synthetic test: known posterior → manually compute percentiles → match Aurora's CI computation
- Kagocel re-fit + verify CI brackets visible in HTML/PPTX
- Verify Step 1 dormant gate triggers on noisy synthetic data (wide CI)
- Tail-ESS gate test: artificially poison sampling, expect "CI оценка нестабильна" annotation

---

## 5. Phase 1.1 — Implementation Plan (12-15h, ship v1.0.15)

### Pre-implementation pilot (2h, blocking)

**Logit-normal vs Beta-Beta comparison on synthetic data:**
- Generate synthetic 7-channel monthly data with known decay (mix of TV-like 0.4 and Digital-like 0.05)
- Fit both parameterizations in NumPyro
- Compare: divergences count, sampling time, recovery accuracy
- Outcome: if logit-normal divergences ≤ Beta-Beta and time ≤ 1.2× → adopt logit-normal. Else fallback Beta-Beta.

### Files & touchpoints (assuming logit-normal adopted)

| File | Change | Hours |
|---|---|---|
| `engines/modeler.py` | Add hierarchical decay sampling: `mu_logit`, `sigma_logit`, `z_i` per channel; replace hardcoded `apply_adstock(x, type)` with `apply_adstock(x, type, decay=sigmoid(mu+sigma·z))` | 4-5 |
| `utils/adstock.py` | `apply_adstock` accepts optional `decay` param (overrides default 0.5/2.0/3.0) | 1 |
| `engines/decomposer.py` | Use sampled decays, propagate uncertainty (already vectorized for Phase 1.9) | 1.5 |
| `engines/scenario.py` + `engines/optimizer.py` | Same: use posterior decay samples | 1.5 |
| `engines/optimizer.py` `_compute_mroas_money` | adstock_factor uses posterior mean decay (not hardcoded 0.5) | 0.5 |
| `tools/test_math_correctness.py` | Verify decay recovery on synthetic | 1 |
| `tools/test_sbc_adstock.py` (NEW) | Coverage Probability test: 90% CI should contain truth ≥ 85% across simulations | 2-3 |
| `engines/modeler.py` (pickle) | Bump `model_version='1.2'`, add `decay_samples` field | 0.5 |
| `aurora_html/sections.py` (methodology section) | Update spec: "adstock decay learnable, hierarchical pooled" | 0.5 |
| Migration messaging | "Re-train recommended — model trained with hardcoded adstock" banner for v1.1.5 pickles | 0.5 |

**Total: 13-16h** (tight to budget). Pilot 2h reduces risk.

### Hyperprior calibration (Antонов choice for v1)

```python
# Recommended for monthly geometric (Option B from §3.A2):
mu_logit ~ Normal(-1.4, 0.7)  # sigmoid(-1.4) ≈ 0.20 mean decay
sigma_logit ~ HalfNormal(0.5)  # moderate dispersion
z_i ~ Normal(0, 1)             # per-channel non-centered

decay_i = sigmoid(mu_logit + sigma_logit * z_i)
```

For v2 (Option A): split into `mu_logit_brand` and `mu_logit_perf` based on `canonicalPrefix` tagging.

### Geometric only in v1

Defer learnable Weibull. Aurora's `adstock_selector.py` BIC selection still works (selects geometric vs weibull at type level) — just decay parameter is learnable for selected type. Weibull params (shape, scale) remain hardcoded in v1.0.15.

### Coverage Probability gate (Sprint 1 milestone)

Run synthetic SBC on 100 simulations × 3 datasets (Kagocel-like, Venarus-like, MMX-like):
- For each simulation: generate data with known decay, fit, check 90% CI contains truth
- Pass: ≥ 85% coverage across all channels in all datasets
- Fail: any channel < 70% coverage → not identifiable, hard-fail

If fails on Kagocel n=36: fallback to per-channel-type priors (Option A) or push Phase 1.1 to Sprint 2.

---

## 6. A4 Pre-MCMC Reliability — Implementation Plan (32-38h, ship v1.0.16)

### Phase A4.1 — Prior Predictive Checks (5-6h)

| File | Change |
|---|---|
| `engines/modeler.py` | Pre-MCMC: `pm.sample_prior_predictive(samples=500)` → compute coverage of y_observed |
| `engines/validator.py` (new function `prior_predictive_check`) | Order-of-magnitude validation, sign validation, IQR overlap |
| Validate UI step | New section "Reliability check" with prior-predictive plot |
| Threshold: 50% coverage = hard threshold (reject), 80% = warning, 95% = pass |

### Phase A4.2 — Prior-Data Conflict (Nott KL divergence, 8h)

| File | Change |
|---|---|
| `engines/validator.py` | Function `prior_data_conflict_kl()` computing KL(prior ‖ posterior) per channel β |
| Calibration via prior predictive simulations | Run 50 prior-predictive sims, compute null KL distribution, compare actual KL |
| Threshold: γ = 0.05 (standard); γ = 0.01 on n < 50 (tightened) |
| Soft-fail message | "Aurora's industry priors disagree with your data — possibly nonstandard category. Treat results as exploratory." |

### Phase A4.3 — Identifiability Simulation (6h)

| File | Change |
|---|---|
| `tools/sbc_identifiability.py` (new) | Use `simuk` (arviz-devs official wrapper) to run SBC |
| Per-channel diagnostic | Coverage Probability ≥ 85% (warning), ≥ 70% (hard-fail per-channel) |
| Output: which channel(s) non-identifiable + recommendation (more data, lift study, drop channel) |
| Run mode: dev-time (cached) + per-dataset (~6-8 min on Kagocel-scale) |

### UI Integration (8-10h)

**Validate step new section "Reliability check":**

```
✅ Tier 1 — Reliable
   Aurora successfully validated your data. Treat ROI estimates as decision-grade.

⚠️  Tier 2 — Directional
   Aurora has caveats. Use estimates for direction, not exact budget reallocation.
   [Show details ▼]
   - TV channel: Coverage Probability 78% (target 85%)
   - Performance channel: Coverage Probability 94% ✓
   - Recommendation: collect 8+ more periods OR run TV pulse experiment

🛑 Tier 3 — Insufficient
   Aurora needs more data variation before reliable channel separation.
   Specifically: Statyi and Performance are too collinear (correlation 0.94).
   [Override and train anyway →] (with fragile-results banner)
   [Show details ▼]
   - Yang KL p-value: 0.003 (significant prior-data conflict)
   - Identifiability: Statyi 65% recovery, Performance 71% recovery
   - Suggestion: try with weaker priors (sigma 0.5 → 0.8) OR drop Statyi
```

### Documentation (4h)

- Update `aurora_html` glossary: добавить "вероятный диапазон", "интервал неопределённости", "симуляция модели", "коэффициент покрытия"
- IT-doc PASHE_IT.MD: section "Что значит когда Aurora отказывается обучаться"
- Help system: новый раздел "Reliability framework" с tier-of-confidence объяснением
- README / methodology section: cite Nott 2016, Talts 2018, IPCC AR5 framework

### Tier Framework Specification

```
Tier 1 — Reliable (green):
  - A4.1: prior predictive coverage 50-95%
  - A4.2: KL γ ≥ 0.05
  - A4.3: Coverage Probability ≥ 85% all channels

Tier 2 — Directional (amber):
  - Any one of:
    - A4.1: coverage < 50% OR 100%
    - A4.2: γ ∈ [0.01, 0.05]
    - A4.3: 70% ≤ Coverage Probability < 85% (any channel)

Tier 3 — Insufficient (red, override available):
  - A4.2: γ < 0.01
  - A4.3: Coverage Probability < 70% (any channel)
```

**Total A4: 32-38h** (UI + override + i18n + docs included).

---

## 7. Validation Strategy

### Datasets (validated 2026-04-26)

| Dataset | n_obs | Channels | Frequency | Use |
|---|---|---|---|---|
| Kagocel | 36 | 7 + TRPs | monthly | Small-N stress test (worst case) |
| Venarus | 51 | 7 + TRPs | monthly | Medium-N primary validate |
| MMX (Афала) | 47 | 5 + TRPs | monthly | Materia Medica brand 1 |
| MMX (Афалаза) | 49 | 5 + TRPs + SOV | monthly | Materia Medica brand 2 |
| MMX (Импаза) | 43 | 5 + TRPs | monthly | Materia Medica brand 3 |

**Bonus:** MMX 3 brands × ~45 obs = real multi-product data within Materia Medica portfolio. Reserve for Sprint 5 Aurora multi-product joint estimation (B3) — not used in Sprint 1.

### Per-phase validation gates

**Phase 1.9 (CI propagation):**
- Synthetic: known posterior → CI computation matches manual percentiles
- Kagocel re-fit → CI brackets visible in HTML/PPTX, no broken layout
- Tail-ESS gate triggers correctly on poisoned sampling

**Phase 1.1 (Joint MCMC):**
- Synthetic SBC: 100 simulations, ≥ 85% Coverage Probability all channels
- Kagocel: convergence (R-hat ≤ 1.05, divergences = 0), decay recovery sensible
- Venarus: same gates + check hierarchical pooling separates TV vs Digital
- MMX × 3 brands: identifiability, no per-brand catastrophic failure
- Performance: total training time ≤ 60s on Kagocel (was 20s pre-fix, 1.75-3× expected)

**A4 (Reliability):**
- Synthetic "good data": all 3 layers pass → Tier 1
- Synthetic "borderline data" (small N, weak signal): Tier 2 with warnings
- Synthetic "bad data" (collinear, no variation): Tier 3 with override available
- Manual UX walkthrough: tier verdicts readable for marketing director, expandable for analyst

---

## 8. Calendar (revised)

```
2026-04-26 → 05-31 — Research deep dive (DONE) + windows of preparation work
                     | Параллельно: Платформа Аврора (юр+фин+sales)
2026-05-31 — Платформа go-live
2026-06-01 → 06-15 — Buffer для post-launch fixes Платформы
2026-06-15 → 06-25 — Implementation Phase 1.9 (12h) + ship v1.0.14
2026-06-25 → 07-15 — Pilot logit-normal (2h) + Implementation Phase 1.1 (13-16h) + ship v1.0.15
2026-07-15 → 08-15 — Implementation A4 (32-38h, includes UI/override/docs) + ship v1.0.16
2026-08-15+ — Sprint 3 Pharma Causal start (with full Sprint 1 Foundation)
```

**Risk:** Sprint 3 push from late July → mid August due to A4 budget revision. Acceptable trade-off — A4 is the killer differentiator and 32-38h includes UI integration that turns "refuse to train" from bug → feature.

---

## 9. Open Questions for Антона

1. **Hierarchical structure (Amendment A1):** approve logit-normal pilot before committing to Beta-Beta? Default: pilot logit-normal (2h), commit logit-normal if divergences/time better.

2. **Monthly priors (Amendment A2):** Option A (per-channel-type, more honest, more work — needs `canonicalPrefix` tagging integration) vs Option B (single hierarchy with shifted prior, simpler)? Default: Option B for v1.0.15, Option A as v2 enhancement.

3. **CI level (Amendment A3):** confirm 90% as default (matches Meridian/Recast/LightweightMMM)? Or stay 95% for compliance-narrative use?

4. **A4 budget revision (Amendment A7):** accept 32-38h vs 15-19h initial? Push Sprint 3 to mid August? Alternative: split A4 into two ships (math layers v1.0.16, UI v1.0.17) — fragments killer differentiator messaging.

5. **A4 override pattern (Amendment A8):** confirm ALL hard-fail paths have override-with-banner? Implies clients can ignore Aurora and train anyway with fragile-results stamp on exports.

6. **Phase 1.9 backward compat:** v1.0/v1.1 pickles fallback to point-estimate-only with banner — OR force re-train on load (more aggressive)? Default: fallback (less disruption).

7. **MMX multi-product opportunity:** MMX has 3 Materia Medica brands × ~45 obs in one dataset. Reserve for Sprint 5 (B3 multi-product joint), or use as Phase 1.1 hierarchical adstock validation now? Default: reserve.

---

## 10. References

### Aurora internal
- `docs/MATH_AUDIT_v1_3_PHASE_0_1.md` — chain rule reference
- `docs/MATH_FIX_PLAN.md` — Phase 0 fix plan
- `project_econometrica_sprint1_foundation.md` (memory) — original 5 decisions
- `project_econometrica_phase01_livetest_findings.md` (memory) — v1.0.13 ship status
- `project_econometrica_premium_avatars.md` (memory) — Sprint 3 Pharma Causal context

### External (Phase 1.1)
- [PyMC-Marketing adstock](https://github.com/pymc-labs/pymc-marketing/blob/main/pymc_marketing/mmm/components/adstock.py)
- [Google Meridian priors](https://developers.google.com/meridian/docs/advanced-modeling/default-prior-distributions)
- [LightweightMMM models.py](https://github.com/google/lightweight_mmm/blob/main/lightweight_mmm/models.py)
- [Sun et al. 2017 — Hierarchical Bayesian MMM](https://research.google.com/pubs/archive/45999.pdf)
- [Talts et al. 2018 — SBC](https://arxiv.org/abs/1804.06788)
- [Bayesian Hierarchical MMM in PyMC (TDS)](https://towardsdatascience.com/bayesian-hierarchical-marketing-mix-modeling-in-pymc-684f6024e57a/)

### External (Phase 1.9)
- [Meridian Analyzer API](https://developers.google.com/meridian/reference/api/meridian/analysis/analyzer/Analyzer)
- [Vehtari et al. 2021 — Improved R-hat for MCMC convergence](https://avehtari.github.io/rhat_ess/rhat_ess.html)
- [Link & Eaton 2012 — On Thinning of Chains in MCMC](https://besjournals.onlinelibrary.wiley.com/doi/10.1111/j.2041-210X.2011.00131.x)
- [Wilke — Visualizing Uncertainty](https://clauswilke.com/dataviz/visualizing-uncertainty.html)
- [Bounteous MMM Explained (CV<30 reliability rule)](https://www.bounteous.com/insights/2022/09/28/marketing-mix-modeling-mmm-explained/)

### External (A4)
- [Nott et al. 2016 — Prior-data conflict via prior-to-posterior divergence](https://arxiv.org/pdf/1611.00113)
- [Egidi et al. 2022 — Avoiding prior-data conflict](https://onlinelibrary.wiley.com/doi/full/10.1002/cjs.11637)
- [Gabry, Simpson, Vehtari, Betancourt, Gelman 2019 — Visualization in Bayesian Workflow](https://rss.onlinelibrary.wiley.com/doi/full/10.1111/rssa.12378)
- [Gelman et al. 2020 — Bayesian Workflow](https://arxiv.org/abs/2011.01808)
- [simuk — PyMC SBC implementation](https://github.com/arviz-devs/simuk)
- [IPCC AR5 uncertainty guidance](https://www.ipcc.ch/site/assets/uploads/2017/08/AR5_Uncertainty_Guidance_Note.pdf)
- [GRADE communicating uncertainty (Cochrane)](https://pmc.ncbi.nlm.nih.gov/articles/PMC6073922/)
- [FDA 2025 AI guidance — abstention emphasis](https://www.alignmt.ai/post/what-fda-s-ai-guidance-really-demands)
- [Royal Society 2019 — Communicating uncertainty](https://royalsocietypublishing.org/rsos/article/6/5/181870/95102/Communicating-uncertainty-about-facts-numbers-and)
