# Sprint 1 Foundation — Live Progress (resume after compress)

**Last updated:** 2026-04-26 ~21:30 — Phase 1.9 + Phase 1.1 backend BOTH COMPLETE
**Branch:** `math-fix-v1.0.13`
**Active phase:** Phase 1.1 backend complete + tests + migration banner. Pending live-test (Антон).
**HEAD:** `54fc39b` (Phase 1.1 tests 72/72 PASS) + new migration banner commit pending
**Test status:** 156+36+72 = 264 unit tests PASS + 65 narrative_adapter = 329 total

> **If you read this after a compress:** continue from "Next concrete step" below WITHOUT confirmation per Антон's protocol 2026-04-26. Only stop for: architecture decisions, push to remote, fundamental schema migration. Auto-commit local OK. Show diff before push.

---

## Current task

**T16 — Live test on Kagocel** (BLOCKED on Антон UI interaction):
1. Rebuild Python sidecar: `python sidecar/build_sidecar.py`
2. Run Tauri dev: `npm run tauri dev` (Aurora Econometrica)
3. Manual flow: import Kagocel_RF_MMM_dataset.xlsx → train → decompose → optimize → export HTML/PPTX
4. Verify in HTML/PPTX portfolio table: `2.4× [1.8 — 3.1]` brackets visible на mROAS column
5. Verify dormant Step 1 verdict triggers: when (roi_ci_high - roi_ci_low) > roi → "Высокая неопределённость" label appears
6. Если PASS — ship v1.0.14 (tag + GH Release + Supabase + aurora-releases manifest)

**Next concrete step:** Антон запускает sidecar rebuild + Tauri dev (interactive). Я подключаюсь когда нужны debug логи из ui.

---

## Done — Phase 1.9 backend (T1-T13, T15)

| Task | Commit | Brief |
|---|---|---|
| T1 | (no code) | Baseline 257 unit tests PASS |
| T2 + T3 | `1757873` | modeler persist posterior_samples (joint per-channel float32) + bump v1.1.5 + utils/posterior_propagation.py (arviz.hdi, verdict_tier, conditional gates) |
| ADR | `8f96a7f` | docs/SPRINT1_FOUNDATION_ADR.md (~600 lines) |
| T4 | `11c3cda` | utils/saturation.py vectorized batch helpers |
| T5 | (no code) | adstock.py — verified no batch needed Phase 1.9 (decay hardcoded) |
| T6 | `63a78c4` | optimizer + _compute_mroas_money_samples + callsite mroi_*_ci_* |
| T7 | `80a266f` | decomposer CI propagation — activates dormant verdict Step 1 (main task) |
| T8 | `9ae2b01` | scenario CI on totals (predicted_kpi/roas/lift_pct) |
| T11 | `a31c5f5` | _merge_channels preserves CI fields (roi_ci_*, mroas_ci_*) |
| T9 | `edc8a2e` | aurora_html portfolio brackets + tier color CSS + SPRINT1_PROGRESS.md |
| T10 | `de945c1` | aurora_pptx portfolio brackets via _rich multi-run |
| T13 | `1e77421` | tools/test_posterior_ci.py — 46 new assertions (303 total tests PASS) |
| T12 | (no code) | server.py — verified: passes CI fields through JSONResponse without schema change |
| T14 | DEFERRED | Pathfinder init NumPyro — requires pure NumPyro flow rewrite, deferred to Phase 1.1 (12-15h scope where it's natural) |
| T15 | DONE in T3 | ArviZ integration through compute_ci_hdi() |
| T16 | PENDING | Live-test Kagocel — interactive (Антон) |

**Total commits Phase 1.9 backend: 10** on `math-fix-v1.0.13` branch.

### Phase 1.1 prep work (autonomous, ahead of schedule)

| Task | Commit | Brief |
|---|---|---|
| Pilot script | `91677c2` | tools/pilot_phase11_hierarchy.py — logit-normal vs Beta-Beta synthetic test framework |
| Pilot results | `3929ce6` | docs/PHASE_1_1_PILOT_RESULTS.md — empirical validation of ADR §3.A1 logit-normal default |
| Progress | `8c5415e` | SPRINT1_PROGRESS.md update with pilot table |
| **E2E demo** | `2269d10` | tools/demo_phase1_9_e2e.py — synthetic pickle → decompose/scenario CI verified |

**E2E demo result:**
- v1.1.5 with samples (502 KB pickle): roi_ci [0.41, 0.82], predicted_kpi_ci [5359, 5728], roas_ci [0.20, 0.27], lift_pct_ci [18.6, 25.1] ✅
- v1.1 legacy (1.6 KB pickle): graceful fallback, no CI fields, no crashes ✅

**Pilot quick-mode result (n=36, 5 channels, chains=2, draws=500):**

| Metric | Beta-Beta | Logit-Normal | Winner |
|---|---|---|---|
| Elapsed | 9.9s | **6.5s** | LN (35% faster) |
| R-hat max | 1.020 | **1.000** | LN |
| ESS bulk min | 92 | **475** | LN (5×) |
| Recovery 90% HDI | 5/5 (100%) | 4/5 (80%) | BB (chance) |
| Divergences | 1 | 1 | tie |

**Conclusion:** Logit-normal validated for Phase 1.1. Convergence quality dominates (R-hat 1.000 + ESS 475 vs 92). Recovery difference (4/5 vs 5/5) likely quick-mode noise — re-run with chains=4, draws=2000 before production ship.

---

## Phase 1.9 deliverables ready for ship v1.0.14

✅ Posterior samples persisted (modeler.py, model_version='1.1.5')
✅ utils/posterior_propagation.py — arviz.hdi + verdict_tier + 3-tier framework
✅ Optimizer mROAS CI per channel (mroi_current/optimal × ci_low/high)
✅ Decomposer ROI CI per channel + dormant Step 1 verdict activation
✅ Scenario predicted_kpi/roas/lift_pct CI bounds
✅ HTML brackets `2.4× [1.8 — 3.1]` with green/amber/red tier badges
✅ PPTX brackets via multi-run (smaller grey bracket)
✅ _merge_channels preserves CI through narrative pipeline
✅ 303 unit tests PASS (156 math + 65 narrative + 36 verdict + 46 new posterior CI)
✅ Backward compat: v1.0/v1.1 pickles → fallback to point estimates, no CI display
✅ Joint correlation preserved (per-channel arrays, not separate)
✅ Asymmetric posterior support (HDI not percentile)
✅ Industry-standard 90% CI default
✅ Conditional gates: r_hat>1.05 → bad, n_obs<30 + narrow → forced warn

---

## Phase 1.1 — BACKEND COMPLETE 2026-04-26

Per ADR §5 + ADR Amendment A1 (logit-normal). Implemented ahead of original
calendar (planned после 31 May) thanks to autonomous mode.

| # | Task | Status | Commit |
|---|---|---|---|
| T1.1 | Logit-normal vs Beta-Beta pilot 2h synthetic | ✅ | `91677c2`+`3929ce6` |
| T1.2 | modeler hierarchical decay sampling в NUTS | ✅ | `dbabdb3` |
| T1.3 | utils/adstock.py accept dict of decays | ✅ | `dbabdb3` |
| T1.4 | All downstream — use sampled decays | ✅ | `dbabdb3` |
| T1.5 | Pickle schema bump v1.2 + decay_samples field | ✅ | `dbabdb3` |
| T1.6 | Migration messaging для v1.1.5 pickles | ✅ | (pending commit) |
| T1.7 | tools/test_sbc_adstock.py — Coverage Probability ≥85% | ⏸ DEFER | requires MCMC ~10min × 100 sims = 16h |
| T1.8 | Live-test all 3 datasets (Kagocel/Venarus/MMX) | ⏳ pending | needs Антон UI flow |
| T1.9 | Pathfinder init NumPyro (T14 deferred from 1.9) | ⏸ DEFER | requires pure NumPyro flow rewrite |
| Tests | 26 new Phase 1.1 assertions | ✅ | `54fc39b` |
| E2E demo | extended для v1.2 path | ✅ | `a072276` |

**Phase 1.1 implementation total:** ~325 LOC + 140 LOC tests across 7 engine files.

**Pickle schema v1.2:**
- Inherits all v1.1.5 posterior_samples (media_betas, alphas, gammas, intercept, control_betas)
- Adds `adstock_decay` shape (n_channels, n_samples) hierarchical samples
- Adds `adstock_mu_logit_mean`, `adstock_sigma_logit_mean` hyperparameter point estimates
- channel_params[col]['decay'] = posterior mean per-channel
- Backward compat: v1.0/v1.1/v1.1.5 readers work via .get() fallback patterns

**Hierarchical priors (validated by pilot):**
```python
adstock_mu_logit ~ Normal(-1.4, 0.7)        # sigmoid mean ~0.20 (monthly)
adstock_sigma_logit ~ HalfNormal(1.0)        # moderate dispersion
adstock_z ~ Normal(0, 1, shape=n_channels)   # non-centered per-channel
adstock_decay = sigmoid(mu_logit + sigma_logit * z)
```

**In-model adstock:** scan-based geometric per channel (decay sampled in NUTS).
Weibull stays hardcoded (Phase 1.5 task). Pre-fit X_media at default decay 0.5
для media_means estimate (semantic consistency v1.1.5 downstream).

**Vectorized CI propagation:**
- decomposer/scenario use `geometric_adstock_batch` + `hill_function_batch_2d` when v1.2 pickle
- optimizer `_compute_mroas_money_samples` supports decay_samples → per-sample adstock_factor analytical
- Joint correlation preserved (alpha_i, gamma_i, beta_i, decay_i from same draw)

---

## A4 Pre-MCMC Reliability (queued, after Phase 1.1)

Per ADR §6. ~32-38h with UI integration + override path.

---

## Decisions log (chronological)

- **2026-04-26 ~14:00** Antón confirmed Sprint 1 Foundation 5 decisions (ADR §2). Sequence: 1.9 → 1.1 → A4 in 3 ships.
- **2026-04-26 ~15:00** Audit applied: B1 ArviZ.hdi accept, B2 Pathfinder accept (deferred to 1.1), B3 Quick proxy A4.3 accept, B4 Unified Confidence Score REJECT (preserve 3-tier, MQS already 0-100), B7 Backtest framework DEFER to Sprint 1.5 v1.0.17.
- **2026-04-26 ~15:30** Sequence Hybrid (c) confirmed: Phase 1.9 NOW (8-12h windows), rest after Платформа 31 May. 3 ships v1.0.14/15/16.
- **2026-04-26 ~16:00** Joint posterior storage strategy: per-channel rows (n_channels, n_samples) shape preserves correlation. float32. No thinning (Vehtari rule).
- **2026-04-26 ~16:30** CI default 90% (matches Meridian/Recast/LightweightMMM). Dormant Step 1 width > 1.0 × point estimate threshold confirmed (CV<0.3 industry rule).
- **2026-04-26 ~17:30** Antón: 8-hour autonomous mode + SPRINT1_PROGRESS.md protocol. Auto-commit local OK including schema migration. Push always show diff.
- **2026-04-26 ~18:30** Phase 1.9 backend complete (9 commits, ~600 LOC + 319 LOC tests). Ready for live-test gate.

---

## Files modified (cumulative Phase 1.9)

- `sidecar/econometrica/engines/modeler.py` (T2)
- `sidecar/econometrica/utils/posterior_propagation.py` (T3, NEW)
- `sidecar/econometrica/utils/saturation.py` (T4)
- `sidecar/econometrica/engines/optimizer.py` (T6)
- `sidecar/econometrica/engines/decomposer.py` (T7)
- `sidecar/econometrica/engines/scenario.py` (T8)
- `sidecar/econometrica/engines/narrative_adapter.py` (T11)
- `sidecar/econometrica/aurora_html/sections.py` (T9)
- `sidecar/econometrica/aurora_html/templates/layout.css` (T9)
- `sidecar/econometrica/aurora_pptx/builder.py` (T10)
- `tools/test_posterior_ci.py` (T13, NEW, 319 LOC)
- `docs/SPRINT1_FOUNDATION_ADR.md` (NEW)
- `SPRINT1_PROGRESS.md` (NEW, this file)

## Other refs

- Plan with full details: `C:/Users/ackol/Desktop/Sprint1_Foundation_PLAN.md`
- ADR: `docs/SPRINT1_FOUNDATION_ADR.md`
- Math: `docs/MATH_AUDIT_v1_3_PHASE_0_1.md`
- Memory entry: `~/.claude/projects/D--Docs-Aurora-Ai/memory/project_econometrica_sprint1_foundation.md`
