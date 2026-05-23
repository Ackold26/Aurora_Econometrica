# Phase 2 (Planning Mode v1.2.0) — Backend + Frontend Foundation Shipped

**Date:** 2026-05-02 (afternoon-evening continuation of morning live-test polish session)
**Branch:** `math-fix-v1.0.13`
**Start HEAD:** `6b7b273` (compressed log live-test polish + Phase 2 plan)
**End HEAD:** `bbe5274` (Phase 2.7 + 2.8 deliverables)
**Commits:** 8 atomic, all local until push.

## Outcome

Phase 2 (Planning Mode = forecast horizon decoupling) backend + frontend foundation + tests + customer methodology shipped. v1.2.0 candidate. Pending: visual UX QA + manual QA on 3 customer pickles + Phase 2.6 reports + NSIS build/release.

## Commits

```
bbe5274  test(phase-2.7+2.8): synergy integration tests + customer methodology doc
0527211  feat(phase-2.3): planning mode UI foundation — toggle + horizon picker
2e0cc2e  feat(phase-2.1): API + Tauri shim + preview endpoints (Step 4)
8f88e7b  feat(phase-2.1): pickle additive fields + G2 legacy migration (Step 3)
b84bec8  feat(phase-2.1): forecast validation helpers + S3/S7 synergies (Step 2)
224d882  feat(phase-2.1): planning mode dispatch — Option C math layer (Step 1)
edcdb5f  docs(phase-2.0): audit pass 2 — L1 REVISED to Option C + 8 synergies
5b6438a  docs(phase-2.0): math audit — forecast horizon kernel decision LOCK
```

## Critical math finding — M9

**Aurora's existing 3-way alignment claim was structurally incomplete.** Cross-check `scenario.py:167-186` + `decomposer.py:289-292` revealed:

| Engine | Hill evaluation |
|---|---|
| scenario.py | per-period sum-of-Hill ✓ |
| decomposer.py | per-period sum-of-Hill ✓ |
| optimizer.py | **Hill-of-mean approximation** (outlier) |

By Jensen's inequality `hill(mean(x)) ≠ mean(hill(x))` — divergence up to 11% on short forecasts.

**L1 REVISED:** Planning mode → Option C (per-period Hill summation matching scenario engine). Analyst mode preserves current Hill-of-mean for byte-exact backward compat. Restores **true** 3-way alignment in planning mode. Performance cost ~12ms negligible.

## 8 synergies wired (S1-S8)

| ID | Description | Status |
|---|---|---|
| S1 | `utils/forecasting.py:evaluate_flat_allocation_response` shared helper | ✅ |
| S2 | Conformal-in-planning для OLS pickles (P10/P90 без posterior) | ✅ wired backend |
| S3 | `verdict_tier()` extension с `extrapolation_severity` gate | ✅ |
| S4 | HTML methodology reuse instead of KaTeX bundle | 🟡 backend ready, UI deferred |
| S5 | `QualityStampBadge` as render of existing diagnostics | 🟡 deferred |
| S6 | Unified `ChannelStateTable` (drift + binding + alloc) | 🟡 deferred |
| S7 | KPI registry coupling — sales 2.0× / awareness 1.5× horizon caps | ✅ |
| S8 | Pickle bump scope-limited (no reserved future fields) | ✅ |

## 7 plan gaps closed (G1-G7)

- G1 — `_compute_mroas_money` + `_compute_mroas_money_samples` + response curves thread `forecast_n_periods` (4 + 3 sites)
- G2 — Legacy pickle migration helpers `infer_*_at_load` для granularity, x_norm quantiles, seasonality
- G3 — `resolve_warning_priority` critical/warn/info composition
- G4 — SLSQP cancellation specified (between multi-starts only, honest UX text)
- G5 — Integration tests covering synergy paths (12 tests)
- G6 — Synthetic harness disclaimer (flat-training mean approximation)
- G7 — Drift detection raw spend AND adstock ratio (M8 implementation)

## Metrics

- **Tests:** 162 baseline → **252 PASS** (+90 new) + 5 skipped (env/feature gated)
- **svelte-check:** 0 errors (138 pre-existing warnings unchanged)
- **cargo check:** ✓ no warnings
- **LOC delta:** ~+2820 across 16 files (4 new modules, 4 new test files, 2 new docs)
- **Backward compat:** Analyst mode byte-exact (no `forecast_periods` → identical to v1.1.0). Legacy v1.3 pickles work via G2 lazy inference.

## Phase 2 budget delta

Plan revised from 13 → ~10 dev-days through audit pass 2 synergies. Actual session work compressed via:
- Standalone analytical harness (Phase 2.0 Part 1) closed L1/L2/L3 in ~1 hour vs 1.5 days planned
- S4/S5/S6 collapsed to follow-up phase (UI polish post-foundation)
- Phase 2.6 reports deferred к follow-up

## Pending для v1.2.0 ship gate

1. **Manual QA** на Kagocel + Венарус + MMX synthetic (forecast=train_n regression baseline + 1.5× warn + 2.5× hard reject)
2. **Visual UX verification** — `npm run tauri dev`, exercise mode toggle + ForecastHorizonPicker rendering
3. **Phase 2.6 reports** — HTML/PPTX/XLSX forecast section additions (~1 day)
4. **v1.2.0 NSIS build** + GH Release tag + Supabase app_versions PATCH + rosst-updates `latest.json`
5. **Phase 2.4 polish** (deferred) — inline ResultInterpretation extension, QualityStampBadge inline render, planning glossary i18n
6. **Phase 2.5 Min scenario library** (deferred) — ScenarioPlayground extension с save + 1-on-1 compare

## Phase 2.0 Part 2 (post-ship calibration)

Triggers после v1.2.0 ship на ≥1 customer pickle:
- L4 epistemic γ — recalibrate с bootstrap CI comparison (currently default γ=0.3 conservative)
- L5 hierarchical × extreme forecast — quantitative threshold (currently generic warning)

## Critical artifacts

- `docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md` — 480-line audit, §1-§10 + L1-L9 lock decisions, audit pass 2 amendments
- `docs/PLANNING_MODE_METHODOLOGY.md` — 9-section customer-facing methodology
- `tools/audit_v2_0_synthetic.py` — standalone harness (300 LOC, runnable)
- `docs/audit_v2_0_synthetic_results.json` — 25-case Option A vs B vs ground truth + cap sensitivity + seasonality bias
- `C:/Users/ackol/Desktop/PHASE_2_PLAN_DELTA_audit_pass_2.md` — comprehensive Phase 2 plan delta + revised sequencing

## Next session triggers

- «manual QA» / «live test» → run dev server + customer pickles, surface drift detection
- «v1.2.0 ship» → bump version, build NSIS, update GH Release + Supabase + rosst-updates
- «Phase 2.6 reports» → HTML/PPTX/XLSX forecast section additions
- «Part 2» / «epistemic γ» / «hierarchical extreme» → real MMM training + bootstrap CI calibration
