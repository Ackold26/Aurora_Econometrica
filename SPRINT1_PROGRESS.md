# Sprint 1 Foundation — Live Progress (resume after compress)

**Last updated:** 2026-04-26 ~17:30 (auto-updated after each commit)
**Branch:** `math-fix-v1.0.13`
**Active phase:** Phase 1.9 (Posterior CI propagation, ship v1.0.14)
**HEAD:** see `git log -1 --oneline`

> **If you read this after a compress:** continue from "Next concrete step" below WITHOUT confirmation per Антон's protocol 2026-04-26. Only stop for: architecture decisions, push to remote, fundamental schema migration. Auto-commit local OK. Show diff before push.

---

## Current task

**T9 (in progress):** aurora_html/sections.py — add CI bracket display in portfolio table. Format `2.4× [1.8 — 3.1]` with color tier (green<0.5 / amber 0.5-1 / red >1 relative width). CSS classes already added to layout.css.

**Next concrete step:** Fix sanity test assertion (ci-tier-warn was correct, my assert was wrong). Then commit T9. Then T10 (PPTX brackets).

---

## Done

| Task | Commit | Brief |
|---|---|---|
| T1 | (no code) | Baseline 257 unit tests PASS verified |
| T2 + T3 | `1757873` | modeler.py persist posterior_samples (float32, joint per channel) + bump model_version='1.1.5' + new utils/posterior_propagation.py (arviz.hdi, verdict_tier, conditional gates) |
| ADR | `8f96a7f` | docs/SPRINT1_FOUNDATION_ADR.md (~600 lines) |
| T4 | `11c3cda` | utils/saturation.py + hill_function_batch + hill_derivative_batch (numpy broadcasting) |
| T5 | (no code) | adstock.py — verified no batch needed for Phase 1.9 (decay hardcoded) |
| T6 | `63a78c4` | optimizer.py + _compute_mroas_money_samples vectorized + callsite mroi_current_ci_low/high |
| T7 | `80a266f` | decomposer.py CI propagation (main task) — activates dormant verdict Step 1 |
| T8 | `9ae2b01` | scenario.py CI on predicted_kpi/roas/lift_pct via posterior reconstruction |
| T11 | `a31c5f5` | narrative_adapter._merge_channels preserves CI fields (decompose roi_ci_*, optimize mroas_ci_*) |
| T9 (partial) | (uncommitted) | sections.py + layout.css — _fmt_x_with_ci helper + .ci-bracket CSS classes |

---

## Phase 1.9 task list (T1-T16)

| # | Task | Status |
|---|---|---|
| T1 | Baseline tests | ✅ |
| T2 | modeler.py samples + version bump | ✅ |
| T3 | utils/posterior_propagation.py | ✅ |
| T4 | utils/saturation.py batch | ✅ |
| T5 | utils/adstock.py verify | ✅ (no change) |
| T6 | optimizer.py samples helper + callsite | ✅ |
| T7 | decomposer.py CI propagation | ✅ |
| T8 | scenario.py CI on totals | ✅ |
| T9 | aurora_html sections + layout.css | 🟡 in progress |
| T10 | aurora_pptx brackets in PPTX | ⏳ next |
| T11 | narrative_adapter merge preserves CI | ✅ |
| T12 | server.py decomposition.json schema verify | ⏳ |
| T13 | tests/test_posterior_ci.py (new file) | ⏳ |
| T14 | Pathfinder init NumPyro | ⏳ |
| T15 | ArviZ integration | ✅ (done in T3) |
| T16 | Live-test Kagocel rebuild + verify brackets | ⏳ |

**Phase 1.9 ETA:** ~4-6h remaining (T9 finish + T10 + T13 + T14 + T16).

---

## Decisions log (chronological)

- **2026-04-26 ~14:00** Antón confirmed Sprint 1 Foundation 5 decisions (ADR §2). Sequence: 1.9 → 1.1 → A4 in 3 ships.
- **2026-04-26 ~15:00** Audit applied: B1 ArviZ.hdi accept, B2 Pathfinder accept, B3 Quick proxy A4.3 accept, B4 Unified Confidence Score REJECT (preserve 3-tier, MQS already 0-100), B7 Backtest framework DEFER to Sprint 1.5 v1.0.17.
- **2026-04-26 ~15:30** Sequence Hybrid (c) confirmed: Phase 1.9 NOW (8-12h windows), rest after Платформа 31 May. 3 ships v1.0.14/15/16.
- **2026-04-26 ~16:00** Joint posterior storage strategy: per-channel rows (n_channels, n_samples) shape preserves correlation. float32. No thinning (Vehtari rule).
- **2026-04-26 ~16:30** CI default 90% (matches Meridian/Recast/LightweightMMM). Dormant Step 1 width > 1.0 × point estimate threshold confirmed (CV<0.3 industry rule).
- **2026-04-26 ~17:30** Antón: 8-hour autonomous mode + SPRINT1_PROGRESS.md protocol. Auto-commit local OK including schema migration. Push always show diff.

---

## Open questions / risks

(none active — proceeding per ADR defaults)

---

## Files modified (cumulative Phase 1.9)

- `sidecar/econometrica/engines/modeler.py` (T2)
- `sidecar/econometrica/utils/posterior_propagation.py` (T3, NEW)
- `sidecar/econometrica/utils/saturation.py` (T4)
- `sidecar/econometrica/engines/optimizer.py` (T6)
- `sidecar/econometrica/engines/decomposer.py` (T7)
- `sidecar/econometrica/engines/scenario.py` (T8)
- `sidecar/econometrica/engines/narrative_adapter.py` (T11)
- `sidecar/econometrica/aurora_html/sections.py` (T9, partial uncommitted)
- `sidecar/econometrica/aurora_html/templates/layout.css` (T9, partial uncommitted)
- `docs/SPRINT1_FOUNDATION_ADR.md` (NEW)
- `SPRINT1_PROGRESS.md` (NEW, this file)

## Other refs

- Plan with full details: `C:/Users/ackol/Desktop/Sprint1_Foundation_PLAN.md`
- ADR: `docs/SPRINT1_FOUNDATION_ADR.md`
- Math: `docs/MATH_AUDIT_v1_3_PHASE_0_1.md`
