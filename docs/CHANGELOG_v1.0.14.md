# Aurora AI Econometrica v1.0.14 — Pharma Causal + Math Audit Hardening

**Date:** 2026-04-27
**Branch:** `math-fix-v1.0.13` (Sprint 3 work) → tag `v1.0.14`
**Predecessor:** v1.0.13 (math audit baseline)

---

## 🎯 Headline features

### 1. Sprint 3 Pharma Causal — новый causal-inference модуль

Поверх MMM добавлены три causal-метода для оценки причинно-следственных эффектов маркетинговых кампаний — критично для pharma compliance narrative (ФЗ-38, ОРД, ФАС):

- **Difference-in-Differences (DiD)** — TWFE estimator via `linearmodels` для geo-holdout tests. Cluster-robust SE, parallel-trends test, Goodman-Bacon staggered detection.
- **Synthetic Control Method (SCM)** — Abadie classic via manual scipy SLSQP (без cvxpy). Placebo permutation inference. Pre-treatment RMSE diagnostics, weight Herfindahl index.
- **Causal Forest (Wager-Athey 2018)** — heterogeneous treatment effects via `econml.dml.CausalForestDML`. Honest-split CI, propensity overlap check (cross-validated).

Доступ через новый раздел **«Причинность»** в кабинете Econometrica (`/causal` route).

### 2. F1-F5 math fixes (Phase 1.1 audit)

- **F1**: Phase 1.1 mean normalization — fixed math drift between training (per-draw `adstock_full[s,:].mean()`) and CI propagation paths. CI shape now correctly reflects per-sample uncertainty when adstock decay varies across posterior draws.
- **F2**: `jackknife_plus_intervals` renamed → `jackknife_intervals` (function actually implemented plain jackknife, не Barber 2021 jackknife+). Honest docstring + `coverage_caveat` field.
- **F3**: Conformal exchangeability disclaimer для time-series data — vanilla coverage не guaranteed для non-stationary marketing data per Barber 2022.
- **F4**: Tail-ESS gate расширен от β only к {β, α, γ, adstock_decay} per-channel AND.
- **F5**: `compute_ci_hdi` returns 4-tuple `(mean, low, high, method)` — UI propagates `_pct` suffix к ci_method когда percentile fallback fired.

### 3. Audit hardening (3 levels of fresh-context audit)

D → audit-of-audit → audit-of-Sprint3 — **5 high-severity bugs caught** that single-pass writer-as-auditor had missed:
- A1 (F1 scenario fallback к raw_plan когда training data unavailable)
- A2 (F5 OR semantic для contrib+roi method aggregation)
- B1 (SCM placebo donor pool included original treated unit)
- B3 (Causal Forest "bootstrap" was disguised SE-of-mean)
- B4 (DiD parallel-trends test без clustered SE)

Plus 5 medium fixes (B6-B10): cross-validated propensity, n_pre vs n_donors warning, scipy.stats.norm.ppf для arbitrary confidence, cross_method_consistency null-CI handling, synthesize_geo_split refactor.

---

## ⚠️ Honest disclosures (read carefully для clients)

### Synthetic-only validation для v1.0.14

Causal endpoints validated ONLY на synthetic data + DGP-controlled ground truth recovery (508/508 tests PASS). Recovery errors:
- DiD: 1.7% (tight)
- SCM: CI contains true value (loose tolerance per Abadie)
- Causal Forest: 12.3%

**Real-customer validation запланирован v1.0.15** после получения geo-disaggregated data от Materia Medica (request template отправлен, см. `docs/MATERIA_MEDICA_GEO_DATA_REQUEST.md`).

UI page header показывает яркий caveat banner для всех причинных вычислений на real client data.

### Coverage caveats

Все causal endpoints возвращают `honest_disclosure` field с явными assumptions:
- DiD: parallel-trends, no-anticipation, SUTVA, common-shocks. **TWFE biased для staggered adoption** — текущий v1.0.14 detects + flags staggered scenarios, true Callaway-Santanna estimator deferred к Sprint 4+.
- SCM: convex-hull, donor-pool quality, stable composition. Plain jackknife (без +) для inference — empirically reasonable но без finite-sample coverage guarantee.
- Causal Forest: CIA, positivity/overlap, SUTVA, honest splits.
- All: exchangeability ослаблена для time-series marketing data.

### Conformal coverage (OLS path)

Per F2/F3 audit: vanilla split-conformal и jackknife coverage guarantees требуют exchangeability — marketing time-series violates это. Aurora positioning revised от "math-guaranteed coverage" к "honest distribution-free PI с calibration evidence + clear caveats".

---

## 📦 New API endpoints (extends, не replaces)

Per ADR §1 EXTEND-not-rewrite — все existing endpoints работают идентично. Sprint 3 добавляет 6 новых endpoints в `/compute/causal/*` namespace:

```
POST /compute/causal/preflight     — applicable methods + recommendation
POST /compute/causal/list          — artifacts history в project
POST /compute/causal/consistency   — cross-method ATT triangulation verdict
POST /compute/causal/did           — TWFE Callaway-Santanna staggered detection
POST /compute/causal/scm           — Abadie classic Synthetic Control
POST /compute/causal/forest        — Wager-Athey Causal Forest
```

Causal artifacts persisted в `project_dir/causal/<method>_<timestamp>.json` — separate от `models/latest.pkl` per ADR Q4 (independent lifecycles).

MMM pickle schema получает optional `causal_artifact_path` field (None по default) — backward-compat: legacy readers ignore via `.get()`.

---

## 🔧 Backwards compatibility

### Pickle schema
- v1.2 pickles (current production): forward-compat ✓
- v1.1.5 pickles: forward-compat (Phase 1.9 path active, no decay learnable) ✓
- v1.1 pickles: forward-compat (no posterior CI, point estimates only) ✓
- v1.0-ols pickles: forward-compat (Sprint 2 small-data path) ✓
- v1.0 pickles: REJECTED (был removed в v1.0.13)

### API
- All existing endpoints + request/response schemas IDENTICAL.
- New `causal_artifact_path` field в pickle dict: optional, None default. Existing readers unaffected.

### Bundle size impact
- Added: linearmodels (~2MB), econml (~5MB), statsmodels (already transitive).
- NO pysyncon, NO cvxpy per ADR Q2(B) — manual scipy SLSQP for SCM weights via `_solve_scm_weights()` interface.
- Estimated installer growth: ~30-50MB (PyInstaller --collect-all для new deps).

---

## 🧪 Testing

**508/508 assertions PASS** across 10 test files:
- `test_math_correctness.py` — 156 (math invariants from v1.0.13 baseline)
- `test_posterior_ci.py` — 82 (F1/F5 + Phase 1.1 CI propagation)
- `test_roi_verdict.py` — 36 (ROI thresholds + verdict tier classification)
- `test_narrative_adapter.py` — 65 (PPTX/HTML brand consistency)
- `test_causal_m0.py` — 39 (panel data loaders + dataclasses)
- `test_causal_m1.py` — 25 (DiD recovery 1.7% error)
- `test_causal_m2.py` — 34 (SCM recovery + placebo inference)
- `test_causal_m3.py` — 23 (Causal Forest + heterogeneity)
- `test_causal_m4.py` — 28 (preflight + consistency triangulation)
- `test_audit_of_sprint3.py` — 20 (B1-B10 lock-in)

---

## 📋 Migration checklist для existing projects

1. ✅ **No re-train required.** v1.2 pickles работают без изменений.
2. ✅ **Existing scenarios + decompose results** unchanged.
3. ⚠️ **Старые projects не получат `causal_artifact_path` field в pickle** — это лишь optional hint, никаких функциональных последствий.
4. ✅ **New «Причинность» tab** появится автоматически на home page когда active project выбран.
5. ⚠️ **Causal methods требуют panel-format data** (long: unit × time × kpi × treatment). Если у вас агрегированные brand-level данные — пока используй synthetic geo split helper, ждите v1.0.15 для real-data validation case-study.

---

## 🎁 Sprint 3 ADR + Materia Medica request

- `docs/SPRINT3_PHARMA_CAUSAL_ADR.md` — полный architectural decision record (12 sections, 4 confirmed refinements Q1-Q4, M0-M4 plan)
- `docs/MATERIA_MEDICA_GEO_DATA_REQUEST.md` — шаблон запроса regional data для Антона (минимальные требования по каждому методу + privacy notes)

---

## 🔮 Roadmap (v1.0.15+)

- **Real-customer validation case-study** на Materia Medica/Кагоцел/Афала regional data
- **UI polish**: file picker через Tauri dialog, column auto-detect from xlsx
- **Synergy refactors**: F2/F3 caveats consolidation в HonestDisclosure, soft/hard distinction в diagnostics_failed
- **True bootstrap для Causal Forest** (currently `cate_mean_se_fallback` honestly labeled)
- **Callaway-Santanna staggered DiD** estimator (currently TWFE + staggered detection flag)
- **Weighted/block conformal** для time-series exchangeability (currently disclaimer + honest caveat)
