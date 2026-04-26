# Sprint 2 + Sprint 1.5 (A4) — Live Progress

**Last updated:** 2026-04-27 ~01:00 — UI Method toggle work in progress
**Branch:** `math-fix-v1.0.13` (pushed)
**Active phase:** Backend полностью готов (Sprint 1+2+1.5 + 9 audit fixes). UI Method toggle в Train step — последний remaining Sprint 2 item.
**HEAD:** `7741017` (audit fix-session complete)

**Current task:** Sprint 2 small-data path EXTENSION — расширить OLS engine за пределами basic frequentist β CI.

**3 new features (per Антон clarification):**
1. Bootstrap ROI CI для OLS — refit OLS на N=200 bootstrap resamples, posterior-style ROI distribution с честным CI на ratios (не на parameters). Закрывает gap "у OLS только β CI, не ROI CI".
2. Predictive intervals на y forecasts — `ŷ ± t · σ · √(1 + x_new'(X'X)^(-1)x_new)` — для scenario predictions с honest uncertainty bounds.
3. OLS-specific diagnostics — leverage h_ii, Cook's distance, VIF (variance inflation factor) — стандартные small-N quality checks отсутствующие в Bayesian path.

**Next concrete step:** Add utils/ols_bootstrap.py с bootstrap_roi_ci function + extend ols_modeler.py diagnostics + integrate в decomposer для OLS pickles.

**UI Method toggle deferred:** требует frontend SvelteKit deep work (ConfigPanel+ModelTrainingStep wiring + Tauri command schema), отдельная задача.

**Audit fix-session 2026-04-27 (4 commits, 9 issues closed):**
- `1b29c6d` C1 Phase 1.1 mean-normalization mathematical drift eliminated
- `79dde5f` H5 mode validation + H1 scenario logging + C2 ROAS guard + C3 spend=0 semantics
- `f678463` H4 DRY adstock_factor + H3 OLS untrained exclude + H2 verdict gate + M1 decay key
- `9cb5751` S1 unified /compute/preflight endpoint (UI один call вместо 4)

**Fixes applied:**
- 🔴 C1: Phase 1.1 in-model mean normalization (5-15% ROI bias eliminated)
- 🔴 C2: ROAS CI division-by-near-zero guard (100₽ floor)
- 🔴 C3: spend=0 channels explicit ci=0 + skip reason marker
- 🟡 H1: scenario CI failure logger.warning (visibility)
- 🟡 H2: verdict_tier tail_ess_ok=None default (forces explicit caller)
- 🟡 H3: OLS untrained channels excluded from X matrix
- 🟡 H4: DRY adstock_factor_batch reuse в _compute_mroas_money_samples
- 🟡 H5: server.py mode validation whitelist (typo protection)
- 🟢 M1: per_channel_samples 'decay' key always present (None when missing)
- ✨ S1: unified /compute/preflight orchestrating recommend + quick_proxy + prior_predictive

**Test status:** 330 unit tests PASS (156+73+36+65). +1 new для M1 contract. Zero regressions.

> **Resume protocol:** if you see only summary after compress — read this file first, continue from "Next concrete step" without confirmation. Stop only for: architecture decisions, push to remote, schema migration. Auto-commit local OK.

---

## Current task

**🟢 SPRINT 2 + SPRINT 1.5 BACKEND COMPLETE.**

Все 6 commits сегодня в Sprint 2 + 1.5 session:
- `f385c77` OLS engine + recommend + SPRINT2_PROGRESS.md
- `669369c` Server endpoints /compute/recommend + decomposer banner для '1.0-ols'
- `1a6066d` Horseshoe priors opt-in (A3)
- `e4bce20` A4.1 prior predictive + A4.2 Nott KL backend
- `<latest>` B7 backtest framework skeleton

**Next concrete step:** UI integration + live-test (Антон).

**Pending для ship v1.0.16 (Sprint 2 + 1.5):**
1. Frontend SvelteKit: Mode toggle (Bayesian/OLS) в Train step
2. Frontend: Banner from /compute/recommend в Validate step
3. Frontend: A4 quick proxy + prior predictive results displayed (Tier 1/2/3)
4. Frontend: Backtest button в Report step + results display
5. Live-test on Kagocel/Venarus + small dataset (n<20) для OLS path
6. Ship v1.0.16 → tag + GH Release + Supabase

---

## Sprint 2 — Small-data path (~5-6h actual)

| # | Task | Status |
|---|---|---|
| S2.1 | engines/ols_modeler.py — OLS regression with hardcoded Hill defaults | ✅ `f385c77` |
| S2.2 | recommend_engine(n_obs, override) — auto-recommend Bayesian vs OLS | ✅ `f385c77` |
| S2.3 | Server endpoint /compute/train accepts mode='ols' | ✅ `669369c` |
| S2.4 | Decomposer banner для '1.0-ols' pickles | ✅ `669369c` |
| S2.5 | A3 Sparse priors (horseshoe) — config flag в Bayesian modeler | ✅ `1a6066d` |
| S2.6 | Auto-recommend banner /compute/recommend endpoint | ✅ `669369c` |
| S2.7 | Tests — smoke OLS round-trip + recommend thresholds | ✅ inline |

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
| A4.1 | Prior predictive checks utility | ✅ `e4bce20` |
| A4.2 | Nott KL divergence prior-data conflict | ✅ `e4bce20` |
| A4.3 (full) | Full SBC via simuk OR custom | ⏸ DEFER (long-running, ~16h MCMC) |
| B7 | Backtest framework skeleton | ✅ pending commit |
| Integration | Validator endpoint runs quick_proxy + A4.1 + A4.2 на data | ⏳ UI integration |

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
