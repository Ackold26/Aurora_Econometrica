# Sprint 2 + Sprint 1.5 (A4) — Live Progress

**Last updated:** 2026-04-26 ~22:30 — Sprint 2 OLS modeler started
**Branch:** `math-fix-v1.0.13`
**Active phase:** Sprint 2 (small-data path, OLS fallback). Sprint 1.5 A4 backend queued next.
**HEAD:** `22d1410` (Phase 1.9+1.1 done) + new OLS commits coming

> **Resume protocol:** if you see only summary after compress — read this file first, continue from "Next concrete step" without confirmation. Stop only for: architecture decisions, push to remote, schema migration. Auto-commit local OK.

---

## Current task

**Sprint 2 OLS engine implementation:**
- ✅ engines/ols_modeler.py (~280 LOC) — train_ols + recommend_engine
- 🟡 Sanity test in progress (import error on test — minor)
- ⏳ Server endpoint integration (`/compute/train` route to ols_modeler when mode='ols')
- ⏳ Decomposer/optimizer/scenario backward compat для '1.0-ols' pickle version

**Next concrete step:** Fix sanity test import path → run train_ols on synthetic n=18 → confirm pickle loads in decomposer → commit Sprint 2 part 1.

---

## Sprint 2 — Small-data path (~5-6h actual)

| # | Task | Status |
|---|---|---|
| S2.1 | engines/ols_modeler.py — OLS regression with hardcoded Hill defaults | ✅ written |
| S2.2 | recommend_engine(n_obs, override) — auto-recommend Bayesian vs OLS | ✅ written |
| S2.3 | Server endpoint /compute/train accepts mode='ols' | ⏳ |
| S2.4 | Decomposer banner для '1.0-ols' pickles | ⏳ |
| S2.5 | A3 Sparse priors (horseshoe) — config flag в Bayesian modeler | ⏳ |
| S2.6 | Auto-recommend banner /compute/recommend endpoint | ⏳ |
| S2.7 | Tests — OLS round-trip, recommend_engine thresholds | ⏳ |

**Decisions:**
- 2026-04-26 ~22:00 — Антон: отдельная engine для OLS (НЕ режим внутри modeler.py). Done — engines/ols_modeler.py.
- 2026-04-26 ~22:00 — Антон: auto-recommend threshold n<20 strict OLS, 20-30 user choice, ≥30 Bayesian default. Done — recommend_engine().
- 2026-04-26 ~22:00 — Антон: ту же autonomous mode (8h, all commits, push exception).

**OLS schema (model_version='1.0-ols'):**
- Hill α=1.5, γ=0.5, decay=0.5 ALL hardcoded (small N can't estimate)
- channel_params: beta (from OLS), beta_se, beta_ci_low_freq, beta_ci_high_freq (frequentist 90% on β)
- ols_diagnostics: r_squared, adj_r_squared, mape, residual_std, beta_standard_errors
- Downstream engines treat as v1.1 path (point estimates only, no posterior CI)
- Migration banner: "OLS-режим: CI на ROI недоступны. Соберите n≥30 для Bayesian + honest CI."

---

## Sprint 1.5 — A4 main implementation (queued, ~5-7h actual)

| # | Task | Status |
|---|---|---|
| A4.1 | Prior predictive checks utility | ⏳ |
| A4.2 | Nott KL divergence prior-data conflict | ⏳ |
| A4.3 (full) | Full SBC via simuk OR custom | ⏳ defer (long-running) |
| B7 | Backtest framework skeleton | ⏳ |
| Integration | Validator endpoint runs quick_proxy + A4.1 + A4.2 на data | ⏳ |

**Note:** A4 quick proxy already done (commit `9cbba78` — Phase 1.1 prep). A4.1+A4.2 build on top.

---

## Plan after Sprint 2 + Sprint 1.5

1. Sprint 2 commits → ship as v1.0.16 candidate (OLS fallback for small-data clients)
2. Sprint 1.5 A4 backend → ship as v1.0.16 (A4 reliability gates)
3. Phase 2.9 Pareto multi-objective optimizer — defer
4. Sprint 3 Pharma Causal — после 31 May Платформа

---

## Files in scope (Sprint 2)

- `sidecar/econometrica/engines/ols_modeler.py` — NEW
- `sidecar/econometrica/server.py` — add /compute/recommend + /compute/train mode='ols' branch
- `sidecar/econometrica/engines/decomposer.py` — model_warning для '1.0-ols'
- `sidecar/econometrica/engines/modeler.py` — horseshoe priors flag
- `tools/test_ols_modeler.py` — NEW unit tests
