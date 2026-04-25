# Sprint 1 Foundation — Live Progress (resume after compress)

**Last updated:** 2026-04-26 ~18:30 — Phase 1.9 backend COMPLETE, awaits live-test
**Branch:** `math-fix-v1.0.13`
**Active phase:** Phase 1.9 backend done; T16 live-test pending Антона's UI interaction
**HEAD:** `1e77421` (test suite for Phase 1.9, 46 assertions)

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

**Total commits Phase 1.9: 9** on `math-fix-v1.0.13` branch.

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

## Phase 1.1 task list (queued, after 31 May Платформа)

Per ADR §5. Logit-normal hierarchy preferred over Beta-Beta (avoids funnel geometry).

| # | Task | Status |
|---|---|---|
| T1.1 | Logit-normal vs Beta-Beta pilot 2h synthetic | ⏳ |
| T1.2 | modeler hierarchical decay sampling в NUTS | ⏳ |
| T1.3 | utils/adstock.py accept dict of decays | ⏳ |
| T1.4 | All downstream — use sampled decays | ⏳ |
| T1.5 | Pickle schema bump v1.2 + decay_samples field | ⏳ |
| T1.6 | Migration messaging для v1.1.5 pickles | ⏳ |
| T1.7 | tools/test_sbc_adstock.py — Coverage Probability ≥85% | ⏳ |
| T1.8 | Live-test all 3 datasets (Kagocel/Venarus/MMX) | ⏳ |
| T1.9 | Pathfinder init NumPyro (T14 deferred from 1.9) | ⏳ |

**Phase 1.1 ETA:** 13-16h (per ADR §5)

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
