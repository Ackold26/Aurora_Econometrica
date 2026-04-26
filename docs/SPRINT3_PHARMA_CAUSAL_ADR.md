# Sprint 3 Pharma Causal — Architectural Decision Record

**Created:** 2026-04-27
**Status:** DRAFT — pending Антон review
**Predecessor:** `docs/SPRINT1_FOUNDATION_ADR.md`, `project_econometrica_premium_avatars.md` (memory), `SPRINT3_PROGRESS.md`
**Branch:** `math-fix-v1.0.13` (or new `sprint3-pharma-causal` после approval)
**Estimated scope:** ~25-40h backend + ~10-15h UI parallel track

---

## 1. EXTEND-not-rewrite declaration

**Sprint 3 EXTENDS the existing Aurora Econometrica architecture. It does NOT rewrite or restructure existing engines/endpoints/pickle schemas.**

This is the **load-bearing decision** of this ADR — pin the existing FastAPI shape so MIN-LIVE coverage from Sprint 1+2 remains valid:

- ✅ All existing endpoints remain functional with **identical** request/response schemas: `/compute/train`, `/compute/decompose`, `/compute/optimize`, `/compute/scenario`, `/compute/preflight`, `/compute/recommend`, etc.
- ✅ Existing pickle versions (v1.0-ols, v1.1.5, v1.2) remain readable. Causal Sprint 3 introduces NEW artifacts in separate `causal/` subdir of project — **does not modify** `models/latest.pkl`.
- ✅ Existing engines (`modeler`, `decomposer`, `optimizer`, `scenario`, `ols_modeler`) get NO API breaks. Sprint 3 adds NEW engines in `engines/causal/` subdir.
- ✅ MIN-LIVE acceptance gates 1-5 (от 2026-04-27) remain valid as regression suite. Sprint 3 adds gates 6-9 для new endpoints без touching 1-5.

**Why this matters:** the F1 audit + audit-of-audit cycle taught us that math drift между training and inference paths is the dominant class-of-bug. Sprint 3 introducing parallel pickle schemas / dual-mode engines would multiply this surface area. Keep boundaries clean.

**What "extension" means concretely:**
- Add `engines/causal/{did,scm,causal_forest,common}.py` (new namespace, new files)
- Add `/compute/causal/{did,scm,forest}` endpoints (new namespace, new request models)
- Add `causal_results.json` artifact in `project_dir/causal/` (separate dir)
- Add Sprint 3 deps to `requirements.txt` (additive, no existing dep replacement)

---

## 2. Context

### 2.1 Pre-launch блокеры (from memory `project_econometrica_premium_avatars.md`)

All blockers closed as of 2026-04-26:
- ✅ **Geo-data в фарме у всех** — pharmaceutical clients track sales by geographic regions (cities/областей/regions) as industry standard. Required for SCM (need control regions) and DiD (need treatment vs control geo split).
- ✅ **Materia Medica/Кагоцел готов validate** — existing client с 31 weeks of geo-disaggregated data, можно использовать как первый causal validation case.

### 2.2 Why CAUSAL дополняет MMM

Existing MMM (Bayesian + OLS) answers: *"какой ROI у канала на агрегированных данных?"*

Causal Sprint 3 answers complementary questions:
- **DiD (Difference-in-Differences):** *"какой incremental эффект новой кампании в пилотных регионах vs контрольных?"* — для регионального A/B testing.
- **SCM (Synthetic Control Method):** *"что было бы в одном регионе если бы ТВ-флайт там не запустили?"* — для post-hoc оценки holdout markets.
- **Causal Forest (Wager-Athey HTE):** *"в каких сегментах эффект кампании был сильнее, и почему?"* — для heterogeneous treatment effects.

Эти три метода покрывают standard pharma marketing experimental designs (geo holdout, in-flight test markets, segmentation analysis) и дают causal claims, которые ФЗ-38 / ОРД / ФАС-compliant compliance narrative требует ("эффект подтверждён contrastive evidence", не только observational MMM correlation).

---

## 3. Stack decisions

### 3.1 Library choices

| Method | Library | Rationale |
|--------|---------|-----------|
| DiD (staggered adoption) | `linearmodels` | Implements Callaway-Sant'Anna 2021 (AER paper) — modern DiD with proper SE для staggered roll-outs typical в pharma marketing (regions onboard at different dates). Well-tested, NumPy/pandas native. |
| Causal Forest (HTE) | `econml` | Microsoft Research's library, Wager-Athey 2018 estimator (JASA), confidence intervals via honest splits. Pandas/scikit-learn integration. |
| SCM (Synthetic Control) | `pysyncon` | Abadie & Augmented SCM 2021, MIT-licensed Python port of Abadie's R `Synth`. Lightweight, no R dependency. |
| Panel data utilities | `statsmodels` | Already в transitive deps. Use для basic panel regression baseline. |

**Alternatives considered и rejected:**
- `DoubleML` (Chernozhukov et al.) for HTE — more sophisticated but heavier API surface, deferred Sprint 4.
- `causalimpact` (Google) for SCM — Bayesian variant, но R-port wraps GP regression that's redundant with our existing MCMC. `pysyncon` simpler.
- Custom DiD via PyMC — would proliferate parallel inference. Use `linearmodels` for first ship, могут добавить Bayesian DiD позже.

### 3.2 Dependency budget

Adding 3 deps. Current `requirements.txt` already has pandas/numpy/scipy/statsmodels/PyMC/arviz/JAX/numpyro. New:
- `linearmodels >= 6.0` (~2MB, depends on patsy already в transitive)
- `econml >= 0.15` (~5MB, sklearn already в transitive)
- `pysyncon >= 1.5` (~500KB, depends on cvxpy which adds ~10MB — biggest add)

**Total install size impact:** ~17MB. Build sidecar exe size impact (PyInstaller --collect-all): ~30-50MB. Acceptable per memory `feedback_econometrica_patterns.md` Phase 1.1 added similar magnitude.

---

## 4. New API surface

### 4.1 Endpoints (all extending existing FastAPI server.py)

```
POST /compute/causal/did        — Difference-in-Differences (Callaway-Sant'Anna)
POST /compute/causal/scm        — Synthetic Control Method (Abadie + Augmented)
POST /compute/causal/forest     — Causal Forest (Wager-Athey HTE)
POST /compute/causal/preflight  — Unified pre-causal data validation
GET  /compute/causal/list       — List existing causal results in project
```

### 4.2 Request schemas (Pydantic)

```python
class CausalDiDRequest(BaseModel):
    project_dir: str
    data_file: str  # panel data — long format (region, period, kpi, treated)
    treatment_column: str  # bool/int 0-1: treated в этом периоде
    geo_column: str  # region/city identifier
    time_column: str
    kpi_column: str
    control_columns: list[str] = []
    method: str = 'callaway_santanna'  # 'callaway_santanna' | 'twfe' (legacy)

class CausalSCMRequest(BaseModel):
    project_dir: str
    data_file: str
    treated_unit: str  # which region got treated
    treatment_period: str  # date split ISO format
    geo_column: str
    time_column: str
    kpi_column: str
    predictor_columns: list[str]  # для weight optimization
    method: str = 'augmented'  # 'classic' | 'augmented'

class CausalForestRequest(BaseModel):
    project_dir: str
    data_file: str
    treatment_column: str
    kpi_column: str
    feature_columns: list[str]  # heterogeneity features
    n_estimators: int = 200
    confidence: float = 0.9
```

### 4.3 Response schemas

Common output structure (all 3 endpoints):
```json
{
  "status": "ok|error",
  "method": "did_callaway_santanna",
  "att": {  // Average Treatment Effect on Treated
    "point": 1234.5,
    "ci_low": 800.0,
    "ci_high": 1700.0,
    "ci_method": "frequentist_se" | "bootstrap" | "conformal_residual"
  },
  "diagnostics": { /* method-specific */ },
  "honest_disclosure": {  // F2/F3 synergy — централизуем caveats
    "method_assumption": "...",
    "exchangeability_caveat": "...",
    "overlap_warning": "..."
  },
  "artifact_path": "project_dir/causal/did_2026-04-27_142000.json"
}
```

### 4.4 Pickle / artifact schema

Causal results stored как JSON в `project_dir/causal/` — **NOT** pickle, **NOT** in `models/latest.pkl`. Reasons:
1. Causal artifacts are dataset-specific, не reusable across projects.
2. JSON readable by humans + non-Python tools (R analysts may консьюм).
3. Avoids pickle schema conflicts с MMM `model_version` versioning.

Naming: `did_<timestamp>.json`, `scm_<timestamp>.json`, `forest_<timestamp>.json`. Each call adds new file (no overwriting). UI can list all causal experiments per project.

---

## 5. Pre-Ship gate before v1.0.14

Before shipping Sprint 3 к customers, gate sequence:

1. **SBC (Simulation-Based Calibration) overnight** — ~16h MCMC × 100 sims на synthetic data with known ground truth ATT. Verify CI coverage matches nominal (90% CI captures true ATT in ≥85% sims). Reference: Talts, Betancourt, Simpson, Vehtari 2018 "Validating Bayesian inference algorithms with simulation-based calibration" arXiv:1804.06788.

2. **UI live-test on Materia Medica/Кагоцел real geo data** — end-to-end DiD + SCM + Causal Forest на 31-week pharmaceutical dataset с known regional flights. Manual sanity check ATT magnitude.

3. **Independent fresh-context audit pass** (D-style review) — same blind-spot doctrine as F1/A1: spawn fresh-context Claude session, read causal/* engines code only, surface ≥3 hidden bugs. Sprint 1+2 audit cycle showed this catches real issues.

4. **MIN-LIVE gates 6-9** — analogous к Sprint 1+2 acceptance gates но для causal endpoints.

Block ship if any gate fails. Per memory `feedback_econometrica_patterns.md` — backend velocity без validation gates = same C1/F1/A1 class regressions.

---

## 6. Phased delivery (M0-M4, ~25-40h backend)

### M0 — Stack + scaffolding (~3h)
- Add 3 deps к requirements.txt + freeze test
- Create `engines/causal/{__init__,common}.py` namespace
- Create `engines/causal/_panel_data.py` — utility for loading panel-format data + validation
- Smoke test imports work in current PyInstaller bundle config

### M1 — DiD endpoint (~6-8h)
- `engines/causal/did.py` — Callaway-Sant'Anna estimator wrapping linearmodels
- `/compute/causal/did` endpoint + Pydantic request model
- Honest disclosure: parallel-trends assumption, common-shock assumption
- Unit tests на synthetic data with known DGP
- Gate 6: MIN-LIVE на Materia Medica synthetic DiD scenario

### M2 — SCM endpoint (~7-10h)
- `engines/causal/scm.py` — wrap pysyncon Augmented SCM
- `/compute/causal/scm` endpoint
- Pre-treatment fit diagnostics (RMSE pre-treatment должен быть «good»)
- Honest disclosure: convex-hull assumption, donor-pool quality
- Gate 7: MIN-LIVE Pittsburg-style holdout test

### M3 — Causal Forest endpoint (~8-12h)
- `engines/causal/causal_forest.py` — wrap econml CausalForestDML
- `/compute/causal/forest` endpoint
- HTE visualization payload — feature importance, treatment effect distribution
- Honest disclosure: positivity / overlap assumption
- Gate 8: MIN-LIVE на segmented Кагоцел data

### M4 — Integration + cross-method consistency (~3-5h)
- `/compute/causal/preflight` — unified validation across methods
- Cross-method comparison: ATT from DiD vs SCM should agree within CI overlap
- Honest disclosure aggregator: list assumptions checked vs unverified
- Gate 9: end-to-end pharma scenario через все 3 method'а

UI parallel track (~10-15h, otherwise независим): new "Причинность" tab в кабинете Econometrica, 3 sub-screens (DiD / SCM / Forest), artifact list view.

---

## 7. Honest Disclosure Synergy (F2/F3 follow-on)

Sprint 3 reinforces the F2/F3 idealization theme — every causal method returns explicit `honest_disclosure` field. UI surfaces these каveats:

- **DiD parallel-trends:** "Effect estimate valid only if pre-treatment trends parallel between treated и control regions. Visual inspection и placebo test recommended."
- **SCM convex-hull:** "Synthetic control valid только если treated unit's pre-treatment characteristics are в convex hull of donor pool. RMSE pre/post comparison surfaces violations."
- **Causal Forest overlap:** "Heterogeneous treatment effects identified только когда there's positivity (P(T=1|X) ∈ (0,1) for all X). Histogram of propensity scores surfaces violations."
- **All methods exchangeability/SUTVA:** "Treatment in one region ne влияет на others. May be violated for spillover regions."

This makes Aurora Causal honest about its assumptions, не "magic causal MMM" claim.

---

## 8. Open questions for Антон (decision gates)

### Q1 [SCOPE] Phased ship vs single ship?

**Option A:** Ship M1 (DiD only) as v1.0.14 alpha → customer feedback → M2-M4 later.
**Option B:** Ship M0-M4 together as v1.0.14, longer backend window но cohesive launch.

Recommendation: **Option B** — DiD alone без SCM/Forest looks like incomplete causal toolkit. Customer would ask "почему только DiD?" and we'd need to explain. Better single launch.

### Q2 [DEPENDENCY BUDGET] cvxpy bundling

`pysyncon` requires `cvxpy` (~10MB extra). Alternatives:
**Option A:** Accept cvxpy bundle size hit для proper SCM optimization.
**Option B:** Implement Augmented SCM optimization manually using `scipy.optimize.minimize` — ~50 LOC, avoids cvxpy. Slightly less robust но manageable.

Recommendation: **Option B** — keep bundle lean, scipy уже в deps, manual implementation gives us full control over numerical edge cases (which cvxpy may obscure).

### Q3 [VALIDATION DATA] kagocel-only or multi-client?

Pre-ship gate requires real-data validation. Options:
**Option A:** Kagocel only (existing client, low overhead).
**Option B:** Kagocel + Materia Medica + 1 more pharma client (broader coverage but coordination overhead).

Recommendation: **Option A** для v1.0.14 ship → expand validation post-ship. Don't over-engineer pre-ship gate.

### Q4 [ARCHITECTURE] Pickle separation vs unified

Should causal artifacts EVER touch `models/latest.pkl`?

**Option A** (proposed in §4.4): Separate `causal/*.json` always. Clean boundary.
**Option B:** Allow optional reference от model_data['linked_causal_artifact'] = 'causal/did_xxx.json'. Audit trail showing which model + which causal study go together.

Recommendation: **Option A** для now, **Option B** as Sprint 4+ enhancement когда pattern is proven. Don't pre-design coupling.

---

## 9. Risks & mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Library API drift (linearmodels/econml) | Medium | Pin versions explicitly, add CI dep-update test. |
| PyInstaller bundle bloat | Medium | Use --exclude-modules for unused submodules; profile before/after install. |
| Causal Forest slow on n>10k | Low | Add timeout + n_estimators cap + progress reporting. |
| Geo-data not standardized across clients | High | Pre-load validation в `_panel_data.py`. Reject malformed input early с clear error. |
| Same blind-spot pattern as F1/A1 | High | Mandatory fresh-context independent audit before ship (per §5 gate 3). |

---

## 10. Approval criteria

This ADR is APPROVED when Антон confirms:
- [ ] §1 EXTEND-not-rewrite declaration accepted (load-bearing — no further architecture changes до Sprint 4)
- [ ] §3.1 library choices confirmed
- [ ] §6 phased delivery sequence and time budget acceptable
- [ ] Q1-Q4 decisions made (default recommendations: B/B/A/A)
- [ ] Branch decision: continue on `math-fix-v1.0.13` or new `sprint3-pharma-causal`?

После approval → start M0 (~3h) автономно, Антон reviews after M0 ships local commit.
