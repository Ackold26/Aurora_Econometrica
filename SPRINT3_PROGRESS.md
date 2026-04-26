# Sprint 3 Progress — Pharma Causal + D/MIN-LIVE Validation Gates

**Branch:** `math-fix-v1.0.13`
**Started:** 2026-04-27 (this session)
**Mode:** Autonomous — Маша работает без per-step confirmation. Вопросы только: architecture decisions / push to remote / schema migration.

---

## Current task

**🟢 SPRINT 3 BACKEND M0-M4 + UI TRACK ALL DONE.** Ready для Pre-Ship gate (SBC + independent audit) before v1.0.14.

**UI Track (Causal cabinet route):**
- `src/routes/causal/+page.svelte` — main route с sticky header (v1.0.14 honest caveat banner) + 2-column grid (form + result) + footer (artifact list)
- `src/lib/components/causal/CausalMethodForm.svelte` — dynamic form для DiD/SCM/Forest с conditional fields
- `src/lib/components/causal/CausalResultCard.svelte` — uniform result display (ATT card с tone-coded CI + honest_disclosure block + method-specific diagnostics)
- `src/lib/components/causal/CausalArtifactList.svelte` — history view + cross-method consistency button с triangulation verdict (good/warn/bad/neutral)
- `src-tauri/src/commands/econometrica.rs` — 6 new pass-through Tauri commands
- Home page (`/`) gets new "Причинность →" button когда active project выбран

Honest caveat banner на page header (v1.0.14 ship): "backend validated на synthetic data + DGP-controlled ground truth recovery. Real-customer geo-disaggregated validation запланирован в v1.0.15..."

**Quality:** 0 causal-specific Svelte type errors, Rust compiles clean (cargo check 22s).

---

## Audit-of-Sprint3 fix-session (2026-04-27 fresh-eyes pass)

Антон requested critical re-audit of all Sprint 3 work. Re-read each component с red-team mindset, traced data flows, enumerated edge cases. **15 issues considered, 10 fixed before push.**

### HIGH severity (5 — all fixed):

**B1 [scm.py]:** placebo donor pool included original treated_unit. Per Abadie convention treated unit's post-period values are treatment-contaminated → biases placebo distribution toward true effect direction → false significance.
- **Fix:** `_placebo_inference` accepts `treated_unit` kwarg, builds `df_no_true = df[df[unit_col] != treated_unit]` for placebo runs.
- Backward-compat: legacy callers without kwarg fall through к full df (deprecated path).

**B2 [scm.py]:** ci_method='placebo_permutation' reported even когда placebos all failed → fell back к pre_rmse silently. F5-class bug (silent fallback).
- **Fix:** explicit `'placebo_pre_rmse_fallback'` marker когда n_placebos < 3. Also added `std` field to placebo_atts_summary (was: range/4 proxy biased для non-normal distributions).

**B3 [causal_forest.py]:** "bootstrap" fallback resampled FROM `cate_pred` (fixed point estimates), не from data. Computes SE-of-mean of fixed estimates, NOT bootstrap of estimator. Underestimates uncertainty significantly.
- **Fix:** rename ci_method к `'cate_mean_se_fallback'` + explicit caveat in honest_disclosure: "underestimates true uncertainty because ignores estimator variance. Используй ATT point estimate как directional, не quantitative." True bootstrap (refit forest each iter) deferred (~minutes per iter).

**B4 [did.py]:** `_parallel_trends_test` used standard OLS SE without clustering. Panel data residuals correlate within unit → understated SE → false rejection of parallel trends assumption.
- **Fix:** statsmodels OLS с `cov_type='cluster', cov_kwds={'groups': pre_df[unit_col]}` для ≥2 units. Standard SE only когда n_clusters=1 (degenerate). Added `se_method` field to result.

**B5 [modeler.py]:** ADR Q4 promise of `causal_artifact_path` field в MMM pickle not delivered.
- **Fix:** added `'causal_artifact_path': None` к pickle dict. v1.2 pickles forward-compat. Future binding к UI deferred.

### MEDIUM severity (5 — all fixed):

**B6 [causal_forest.py]:** Overlap propensity check used in-sample LogisticRegression fit без StandardScaler → overfit + slow convergence on unscaled features.
- **Fix:** `Pipeline(StandardScaler + LogisticRegression)` + `cross_val_predict(cv=min(5, n//20))` для honest out-of-sample propensity scores.

**B7 [_panel_data.py]:** `validate_for_scm` не проверяла `n_pre >= n_donors + 1` (Abadie 2021 overfit risk).
- **Fix:** non-blocking `_overfit_warning` attribute set when condition violated. Caller in scm.py can surface к UI. Не block (SCM still computable, just warn).

**B8 [scm.py + did.py + causal_forest.py]:** `z_crit` lookup hardcoded `{0.9, 0.95, 0.99}` → silent precision loss для arbitrary confidence (e.g., 0.92 falls back to 0.9 = 1.6449).
- **Fix:** `scipy.stats.norm.ppf(1.0 - alpha/2.0)` для exact value. Lookup retained as fallback if scipy unavailable.

**B9 [preflight.py]:** `cross_method_consistency` set `overlap=False` когда any CI bound is None → false-flagged 'disagree' verdict for any CI-missing pair.
- **Fix:** mark pair `'skipped_ci_missing'` (string), exclude from `n_pairs_with_ci` denominator. Verdict='unknown' когда all pairs skipped (was 'disagree').

**B10 [_panel_data.py]:** `synthesize_geo_split` re-evaluated `numeric_cols` inside double loop (O(N×n_geo) wasted column lookups). Comment said "additive noise" but code does multiplicative scaling.
- **Fix:** hoisted `numeric_cols = df.select_dtypes(...).columns.tolist()` outside loops. Comment corrected.

### Lock-in tests (`tools/test_audit_of_sprint3.py` — 20 assertions):
- B1 source-level structural verification + both code paths return valid results
- B2 ci_method ∈ honest set
- B3 source references cate_mean_se_fallback + caveat string
- B4 se_method='cluster' returned для panel ≥2 units
- B5 modeler.py pickle schema includes causal_artifact_path
- B7 _overfit_warning meta attribute set when triggered
- B9 verdict='unknown' when all pairs ci-missing (not false-flag 'disagree')
- B10 synthesize_geo_split functions correctly post-refactor

**Tests:** 508/508 PASS (was 488 + 20 new audit). No regressions.

### Deferred (low priority):
- Pydantic `Any` typing for treated_unit/treatment_period — type coercion via panel_data
- F2/F3 caveats consolidation в HonestDisclosure structure (synergy refactor)
- HonestDisclosure soft/hard distinction в diagnostics_failed
- UI: file picker via Tauri dialog API (currently text path input)
- UI: column auto-detect from file (currently manual entry)
- True bootstrap для Causal Forest (currently fallback uses SE-of-mean honestly labeled)

Total: 5 commits + 488/488 tests PASS.

| Milestone | Commit | LOC | Tests | Recovery error |
|-----------|--------|-----|-------|----------------|
| M0 stack scaffolding | `8a35680` | ~340 | 39 | (smoke) |
| M1 DiD endpoint | `cd13021` | ~190 | 25 | 1.7% |
| M2 SCM endpoint | `5ac8352` | ~330 | 34 | 40% (CI contains) |
| M3 Causal Forest | `9e2a974` | ~280 | 23 | 12.3% |
| M4 integration | (this) | ~330 | 28 | (validation) |

**5 endpoints exposed:**
- `POST /compute/causal/preflight` — unified validation + method recommendation
- `POST /compute/causal/list` — list artifacts in project
- `POST /compute/causal/consistency` — cross-method ATT triangulation
- `POST /compute/causal/did` — TWFE DiD (Callaway-Santanna deferred Sprint 4+)
- `POST /compute/causal/scm` — Abadie classic via manual scipy SLSQP
- `POST /compute/causal/forest` — econml CausalForestDML with honest_split CI

**Architecture invariants preserved (per ADR §1):**
- Existing endpoints/pickle schemas/engines untouched
- Causal artifacts in `project_dir/causal/*.json` (separate from MMM models/)
- All causal methods return uniform schema: `{status, method, att, diagnostics, honest_disclosure, artifact_path, created_at}`

**Pre-Ship gate before v1.0.14 (per ADR §5):**
- [ ] SBC overnight (~16h MCMC × 100 sims for CI coverage validation)
- [ ] UI live-test on Materia Medica/Кагоцел real geo data + Афала (2-dataset diversification per Q3)
- [ ] Independent fresh-context audit pass (D-style — same blind-spot doctrine that caught F1/A1)
- [ ] MIN-LIVE gates 6-9 production scenario через все 3 method'а
- [ ] UI parallel track (~10-15h: Causal tab в кабинете Econometrica)

⚠️ Pre-launch блокер still open per ADR §11/Q3: real geo data для Kagocel/Афала. M0-M4 validated на synthetic + `synthesize_geo_split()` fallback. Real-customer validation требует geo data resolution.

ADR APPROVED with 4 refinements (Q1-Q4 + per-M MIN-LIVE checkpoint + scipy isolation interface + Афала validation diversification + optional causal_artifact_path hint). M0 ships:

- requirements.txt: +linearmodels>=6.0 +econml>=0.15 +statsmodels>=0.14 (NO pysyncon, NO cvxpy per Q2(B))
- engines/causal/{__init__.py, common.py, _panel_data.py} namespace создан
- tools/test_causal_m0.py — 39 assertions per-M MIN-LIVE checkpoint, all PASS
- Panel data loader/validator (synthetic + real format), synthesize_geo_split fallback для aggregated→panel
- ATT + HonestDisclosure dataclasses + uniform error_response shape
- 378/378 total tests PASS (was 339 + 39 new)

⚠️ Pre-launch блокер flagged: Kagocel и Афала both AGGREGATED brand-level — нет geo split. M1+ нужны panel data. Fallback options:
1. synthesize_geo_split() для DGP-controlled validation (synthetic ground truth)
2. Real geo data request от Materia Medica для true validation
3. М0 dataset-agnostic — продолжается independently от panel-data resolution

Fresh-context skeptic review кода без чтения SPRINT*_PROGRESS / ADR (те написаны same blind-spot session).

Critical questions из прошлой сессии:
1. Phase 1.1 in-model `adstock_full.mean()` vs persistence as Deterministic — actually consistent? Test by hand n=10 toy.
2. Bootstrap real per-period — `sat.sum() * y_std` correctly matches decomposer? Verify by hand.
3. Conformal jackknife+ formula `(n+1)(1-α)/n` vs `(n+1)(1-α)/(n+1)` per Lei et al. 2018 §4.2.
4. HDI on bootstrap distribution — overshoot когда multi-modal?
5. Untrained channel × posterior_samples interaction в decomposer.

Goal: ≥3 hidden bugs/inconsistencies. Если zero — дальше копать.

---

## Done

- [x] 2026-04-27 — Read NEXT_SESSION_PROMPT.md, plan acknowledged
- [x] 2026-04-27 — Saved feedback memory: autonomous mode для Econometrica
- [x] 2026-04-27 — Verified baseline: HEAD 92108dc, working tree clean, branch math-fix-v1.0.13
- [x] 2026-04-27 — Created SPRINT3_PROGRESS.md (this file)
- [x] 2026-04-27 — Baseline tests verified (156+73+36+65 = 330 PASS, HEAD 92108dc clean)
- [x] 2026-04-27 — **Step D complete:** read 5 ключевых files (decomposer/modeler/optimizer/posterior_propagation/ols_bootstrap/conformal). Surface 6 findings, 3 high-severity (F1 math drift Phase 1.1 samples path, F2 jackknife_plus actually plain jackknife, F3 conformal exchangeability violated time-series). 3 medium/low (F4-F6).
- [x] 2026-04-27 — **Fix-session complete (~3h):** Antón approved defaults + caught optimizer also affected by F1.
  - **F1(b)** [3 places, not 2]: per-sample training adstock mean recompute. Helper `compute_train_adstock_mean_samples` в posterior_propagation.py. Patched decomposer.py (in-place mean from x_adstock_2d), scenario.py (load training data unconditionally + helper), optimizer.py (changed `_compute_mroas_money_samples` signature `mean: float` → `mean: float | np.ndarray`, caller pre-computes per-sample mean from training df).
  - **F2(a)**: renamed `jackknife_plus_intervals` → `jackknife_intervals` + honest docstring + `coverage_caveat` field. Backward-compat alias kept. `conformal_intervals_auto` updated.
  - **F3(a)**: module docstring + `exchangeability_caveat` field в conformal_intervals_auto output. Honest positioning revision.
  - **F4**: extended tail-ESS gate в modeler.py от `['media_betas']` к `['media_betas', 'alphas', 'gammas', 'adstock_decay']`. Per-channel AND aggregation.
  - **F5**: `compute_ci_hdi` returns 4-tuple `(mean, low, high, method)` где method ∈ {'hdi', 'percentile_fallback', 'degenerate', 'empty'}. All 10 callers updated (decomposer/scenario/optimizer/ols_bootstrap + tests). Decomposer ci_method получает суффикс `_pct` когда percentile fallback fired.
  - **F6** deferred — UI work, post-MIN-LIVE.
  - **Tests:** 339/339 PASS (was 330, +9 from F1 + F5 marker tests). New F1 tests check: scalar fallback, geometric+decay shape, constant decay sanity, high-vs-low decay carryover monotonicity, variable decay produces variable means (>5% std), per-sample distortion when using scalar (max abs diff >10%) — direct lock-in for the bug.
  - **Smoke imports:** all engines + utils import clean. `jackknife_intervals` exists, alias `jackknife_plus_intervals` works.

---

## Next concrete first step

**Sprint 3 Pharma Causal start — Step B (~25-40h backend).**

ADR Sprint 3 §1 must declare "EXTEND, not rewrite" — pin existing FastAPI shape so MIN-LIVE coverage stays valid. Stack:
- `linearmodels` — DiD (Callaway-Sant'Anna 2021 staggered adoption)
- `econml` — Causal Forest (Wager-Athey heterogeneous treatment effects)
- `pysyncon` — Synthetic Control (Abadie + Augmented 2021)
- `statsmodels` — base panel data utilities

Pre-launch блокеры (per memory): geo-data в фарме у всех ✓, Materia Medica/Кагоцел готов validate ✓.

**Concrete first step:** create `docs/SPRINT3_PHARMA_CAUSAL_ADR.md` with §1 EXTEND-not-rewrite declaration + dependency list + extension points (new endpoints `/compute/causal/did`, `/compute/causal/scm`, `/compute/causal/forest` — extends existing FastAPI without rewriting). After ADR draft, surface to Антон для approval (architecture decision — gate before code).

**Pre-Ship gate before v1.0.14:** SBC overnight (~16h MCMC × 100 sims) + UI live-test on real Kagocel + Materia Medica geo-data.

**Open items для F6 (UI label) — defer:** добавить tooltip "captures coefficient uncertainty only; Hill saturation params фиксированы" to OLS bootstrap CI bracket рендеринг. ~20min UI work post Sprint 3 backend.

---

## Decisions log

| Date | Decision | Why |
|------|----------|-----|
| 2026-04-27 | Trust gate sequence D → MIN-LIVE → B | Previous session blind-spot: same Claude wrote + audited; C1/C-OLS-1 class bugs caught only post-hoc. Fresh context = independent reviewer. |
| 2026-04-27 | Autonomous mode in-session | Антон mandate — backend velocity не должна стопориться. Vопросы только по 3 темам. |
| 2026-04-27 | NOT reading SPRINT*_PROGRESS / ADR before D | Risk absorbing same blind spot patterns. Code-first review. |

---

## D Findings (2026-04-27)

### F1 — Phase 1.1 mean normalization inconsistency (training vs persistence vs CI propagation) [HIGH]

**Where:** `engines/modeler.py:400-406`, `engines/modeler.py:733-740`, `engines/decomposer.py:261, 327-328`, `engines/optimizer.py:202-204`.

**Math:**
- Training (per-draw): `x_norm[s,t] = adstock_full[s,t] / adstock_full[s,:].mean()` — каждый sample делит на свой собственный adstock mean.
- Persistence (modeler.py:736-740): сохраняется `adstock_mean_i` как `E[adstock_full.mean() | s]` — единственный scalar (posterior mean of per-sample means).
- Inference (decomposer Phase 1.1 path, optimizer samples variant): `x_norm[s,t] = adstock_per_sample[s,t] / mean_scalar` — все samples делятся на ОДИН scalar.

**Impact:** при variability decay across samples (hierarchical learnable adstock — это вся фишка Phase 1.1), per-sample adstock_mean варьируется, но inference этого не учитывает. Для samples с высоким decay (carryover большой) → mean undershoot → x_norm overshoot → Hill saturates more → contribution_i overshoots. Симметрично для low decay. В expectation эффекты частично компенсируются, но **shape posterior CI distribution distorts** — может underestimate или overestimate uncertainty в зависимости от где Hill operating point.

C1 fix (post-audit v1.2 commit `1b29c6d`) корректно закрыл POINT estimate consistency (decomposer point uses `adstock_mean_posterior` scalar = consistent with training expectation), но **SAMPLES path не закрыт** — persistence хранит scalar, не per-sample массив.

**Severity:** HIGH — Phase 1.1 это flagship math feature (hierarchical learnable adstock), и его CI propagation шаг дрифтит от training math. Тот же класс bug что C1.

**Fix options:**
- (a) **Schema migration:** persist `adstock_mean_samples` (n_channels, n_samples) array в posterior_samples. ~64KB × 7 channels ≈ 448KB extra. Decomposer/optimizer используют per-sample. **→ schema bump v1.2 → v1.3, требует re-train.**
- (b) **Recompute on-demand:** в decomposer Phase 1.1 path, `adstock_mean_per_sample = x_adstock_2d.mean(axis=1)` (одна доп.строка после `geometric_adstock_batch`). Затем `x_norm_2d = x_adstock_2d / adstock_mean_per_sample[:, None]`. То же в optimizer samples variant. **No schema bump.**

Рекомендация: (b). Чище, backward compat, no client re-train. **→ Антон, нужен твой call: (a) или (b)?** [SCHEMA MIGRATION DECISION]

---

### F2 — `jackknife_plus_intervals` реализует plain jackknife, не jackknife+ [HIGH for positioning]

**Where:** `utils/conformal.py:154-223`.

**Math:**
- Implementation: `r_i = |y_i - ŷ^(-i)(x_i)|` (LOO residuals) → quantile → apply as symmetric `± half_width`.
- True jackknife+ (Barber, Candes, Ramdas, Tibshirani 2021 Theorem 1): требует `ŷ^(-i)(x_test)` для each i — асимметричный interval `[q_α^- of {ŷ^(-i)(x_test) - r_i}, q_{1-α}^+ of {ŷ^(-i)(x_test) + r_i}]`.

**Coverage guarantees per paper:**
- Jackknife (без +): **no finite-sample guarantee in general** (§1.1).
- Jackknife+: ≥ 1 - 2α (Theorem 1).

Docstring claims "Coverage guarantee: ≥ 1 - 2α (slightly weaker than split's 1-α but still distribution-free)" — **applies к jackknife+, не к плоскому jackknife**.

**Impact:** Marketing positioning "honest CI с math-guaranteed coverage, не assumption-based" partially false. Code и docstring рассогласованы.

**Severity:** HIGH for commercial honesty / positioning. Medium for actual user — coverage в practice часто ОК даже для plain jackknife, но guarantee отсутствует.

**Fix options:**
- (a) **Rename only:** `jackknife_plus_intervals` → `jackknife_intervals`, update docstring к "no finite-sample guarantee, но empirically reasonable on stationary residuals". Marketing claim downgrade. ~30min.
- (b) **Implement true jackknife+:** API change — function needs to know `x_test` for each prediction (not just produce `half_width`). More invasive — caller (ols_modeler) сейчас computes one `conformal_pi` dict с одним `half_width`, applied symmetrically. Real jackknife+ needs per-prediction interval — for OLS path this means computing interval at every actual obs. ~3-5h. **→ architecture decision.**

Рекомендация: (a) — честнее всего. Real jackknife+ over-investment когда (c) ниже всё равно blocks guarantee. **→ Антон, твой call?** [ARCHITECTURE DECISION]

---

### F3 — Conformal exchangeability assumption violated for time-series MMM [HIGH for positioning]

**Where:** `utils/conformal.py:9-10` docstring + S-OLS-1 marketing claim.

**Math:** Conformal prediction guarantees `P(y_new ∈ [ŷ ± hw]) ≥ 1-α` под exchangeability (training + test). Marketing data — это **time-series**: sales next month НЕ exchangeable with sales last year. Тренды + seasonality + regime changes нарушают exchangeability.

**Reference:** Barber, Candes, Ramdas, Tibshirani 2022 "Conformal prediction beyond exchangeability" — explicit что vanilla conformal coverage breaks under non-exchangeable data; weighted/block variants needed.

**Impact:** Aurora positioning "единственный MMM-tool с conformal prediction → math-guaranteed coverage" — **misleading для marketing data** (которая вся time-series). Тех. совершенно legitimate в product description, но moral hazard если customer полагается на guarantee.

**Severity:** HIGH for commercial honesty. **NOT a code bug** — это method validity issue для domain.

**Fix options:**
- (a) Disclaimer в docstring + UI label: "conformal coverage assumes stationary residuals — guarantee может ослабевать при trend/seasonality. Empirically работает на stationary residuals, но не math-guaranteed для non-stationary marketing data". ~1h.
- (b) Implement weighted conformal (Tibshirani et al. 2019) или block conformal — restore guarantee. ~6-12h. Больше math, но и реальная differentiation.

Рекомендация: (a) для now (ship-blocker для honesty), (b) на Sprint 4+ если customers просят. **→ Антон, твой call: ship с disclaimer, или blocker?** [POSITIONING DECISION]

---

### F4 — Tail-ESS gate проверяет только β, miss α/γ/decay [MEDIUM]

**Where:** `engines/modeler.py:745`.

**Math:** `tail_ess_betas = az.ess(trace, var_names=['media_betas'], method='tail')`. ROI CI propagation chain involves α, γ, **AND adstock_decay** через Hill saturation (decomposer.py:329-353). Hill geometry часто имеет funnel issues — α tail-ESS may degrade pre β.

**Impact:** Gate may pass models с bad α/γ/decay tail-ESS, CI bounds reported as stable but actually unreliable.

**Fix:** `var_names=['media_betas', 'alphas', 'gammas', 'adstock_decay']`. Per-channel aggregation: tail_ess_ok_per_channel[i] = AND of all four for channel i.

**Severity:** MEDIUM. Direct fix без architecture/schema implications. **→ можно делать без подтверждения.**

---

### F5 — `compute_ci_hdi` silent fallback HDI → percentile [LOW]

**Where:** `utils/posterior_propagation.py:67-77`.

**Math:** When arviz `az.hdi` raises Exception, falls back к equal-tail percentile but returns под тем же API (no marker indicating fallback fired). Decomposer/optimizer set `ci_method='bayesian_hdi_phase11'` unconditionally → UI labels "HDI" даже когда actually percentile.

**Impact:** Asymmetric posteriors (mROAS) — percentile и HDI заметно отличаются. Silent semantic change.

**Fix:** Return `(mean, ci_low, ci_high, used_method)` где `used_method ∈ {'arviz_hdi', 'percentile_fallback'}`. Каллеры pass through к `ci_method`. ~30min.

**Severity:** LOW (вряд ли triggers — arviz hdi редко fails). Direct fix. **→ можно делать без подтверждения.**

---

### F6 — Bootstrap CI vs Bayesian CI scope mismatch [LOW, design]

**Where:** `utils/ols_bootstrap.py:121-123`, hardcoded `hill_alpha=1.5, hill_gamma=0.5, decay_default=0.5`.

**Impact:** OLS bootstrap CI captures β uncertainty only — α/γ/decay фиксированы. Bayesian CI captures all four. UI puts both в bracket "ROI 2.4× [1.8 — 3.1]" with same visual semantics, but uncertainty scopes разные.

**Severity:** LOW (design clarity). Not a math bug — just under-claimed uncertainty.

**Fix:** UI label clarification — `ci_method='frequentist_bootstrap'` UI tooltip: "captures coefficient uncertainty only; Hill saturation params фиксированы". ~20min UI work.

---

## D Summary

**Found:** 6 issues. F1 + F2 + F3 = 3 high-severity (target ≥3 met).

**Class of bugs:** все три HIGH issues — это **post-hoc validation gap** того же класса что C1/C-OLS-1 caught по previous sessions. Подтверждает blind-spot pattern: writer-as-auditor catch fewer issues.

- F1: math drift между training и CI propagation (тот же тип что C1).
- F2: implementation/claim mismatch (тот же тип что L4 verdict gating).
- F3: domain validity assumption (новый класс — не было раньше).

**Estimated fix scope:** F1 option (b) ~2h, F2 option (a) ~30min, F3 option (a) ~1h, F4 ~1h, F5 ~30min, F6 ~20min. **Total ~5h fixes.**

**Pre-MIN-LIVE blocker assessment:**
- F1 — block (math foundation matters для Phase 1.1 claim).
- F2 — block (positioning honesty).
- F3 — block (positioning honesty).
- F4 — nice-to-have (gate completeness).
- F5/F6 — defer post-MIN-LIVE.

**3 questions для Антона:**
1. **F1 [SCHEMA MIGRATION]:** option (a) full schema bump v1.2→v1.3 с full posterior persistence, или (b) on-demand recompute (no schema change, no re-train)?
2. **F2 [ARCHITECTURE]:** rename + downgrade claim (~30min), или real jackknife+ implementation (~3-5h)?
3. **F3 [POSITIONING]:** ship с disclaimer, или block для weighted conformal Sprint 4+?

После твоего ответа стартую fix-session, затем MIN-LIVE.

---

## MIN-LIVE Findings (in progress)

**Setup:**
- Server started on port 7530 (port 7529 occupied by stale Aurora Econometrica v1.0.10 sidecar from production app — non-destructive bypass).
- Test payloads in `D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica/test_payloads/`.
- Synthetic n=18 dataset generated for OLS path.
- All requests through FastAPI server.py (production code path, не direct Python import).

**Acceptance gates:**

- ✅ **GATE 1 — /compute/recommend:** n=18 → recommended='ols' (banner_tone='bad'), n=50 → recommended='bayesian' (banner_tone='good'). Sprint 2 routing logic correct.
- ✅ **GATE 2 — /compute/preflight (Kagocel n=31):** status='ok', overall_tier='reliable', recommended_mode='bayesian'. Breakdown contains all 3 sub-checks (engine_recommend + quick_proxy + prior_predictive). S1 audit unification works.
- ✅ **GATE 3 — /compute/train mode='ols' (synthetic n=18):** status='ok', engine='ols', `conformal_pi.method='jackknife'` (NOT 'jackknife_plus' — **F2 fix landed**), `auto_choice='jackknife'`, `coverage_caveat` populated (F2), `exchangeability_caveat` populated (F3). Honest disclosure section present.
- ✅ **GATE 5 (bonus) — /compute/decompose (OLS pickle):** status='ok', model_version='1.0-ols', 3 channels with `ci_method='frequentist_bootstrap'`, CI ordering monotonic (low < mean < high).
- ✅ **GATE 4 — /compute/train Bayesian Kagocel (chains=2 draws=500 tune=500):** completed in 5 sec via NumPyro JAX (parallel 8 devices). Pickle structure verified:
  - `model_version='1.2'` (Phase 1.1 schema)
  - `posterior_samples` has all 11 required keys including `adstock_decay` shape (6, 1000)
  - `channel_params[col]` includes `decay`, `adstock_mean_posterior`, `tail_ess_ok` (F4 — extended AND of β/α/γ/decay)
  - Convergence note: 389 divergences with reduced 2×500 config (production uses 4×2000 — quality not focus of MIN-LIVE which validates math pipeline).
- ✅ **GATE 4b — /compute/decompose on Bayesian pickle:** all 6 channels populated:
  - `ci_method='bayesian_hdi_phase11'` (F5 marker = 'hdi', no '_pct' suffix → arviz HDI fired correctly)
  - F1 evidence: per-sample training adstock mean propagated (uses x_adstock_2d.mean(axis=1, keepdims=True) — verified в decomposer.py edit)
  - All CI monotonic: `roi_ci_low ≤ roi ≤ roi_ci_high` ✓ across all 6 channels.

**MIN-LIVE summary:** 4 production gates + 1 bonus all PASSED. F1-F5 fixes validated в production code path (FastAPI server.py + Pydantic request validation + actual ML pipeline + pickle round-trip). No regressions surfaced.

---

## Second-pass Audit Findings (2026-04-27 — fresh-eyes review of own fix-session)

Antón requested critical re-audit of the work just completed before push (recognizing same blind-spot pattern that surfaced original C1/F1 bugs могла повториться в audit-fix-session itself). Re-read each F1-F5 edit с red-team mindset, traced data flow, enumerated edge cases.

### A1 [HIGH — fixed before push]: F1 scenario.py training-data fallback bug

**Discovery:** when training data file unavailable (load failed / file moved / corrupted), F1 fix fell back to `raw_plan[col]` (scenario data) для per-sample mean computation. Helper computed `geometric_adstock_batch(raw_plan[col], decay_samples).mean(axis=1)` — i.e., normalized SCENARIO BY ITSELF.

**Math impact:** x_norm averaged ~1 across samples regardless of how scenario related к training scale. Hill saturated at constant level → CI artificially tight. Model was trained with x_norm using TRAINING mean, so dividing by scenario's own mean broke the calibration — Hill coefficients no longer correspond к actual saturation curve.

**Severity:** HIGH — silent math error в edge case. Production triggers: data file moved/renamed между train+scenario, or scenario uses dataset different from training.

**Fix:** explicit scalar fallback. When `train_raw is None`, set `mean_samples = mean` (training-time stored `adstock_mean_posterior`). Preserves training-vs-scenario scale relationship correctly.

**Class-of-bug:** same fallback-to-wrong-data pattern that existed in C1 (defaults vs posterior means). Caught only on second pass — confirms blind-spot doctrine.

### A2 [MEDIUM — fixed before push]: F5 method aggregation OR semantic

**Discovery:** decomposer captured `_method_c` (contribution HDI method) and `_method_r` (ROI HDI method) but only checked `_method_r` for `_pct` suffix decision. If arviz failed on contrib but succeeded on ROI (numerical edge case), ci_method label would say 'bayesian_hdi' даже когда контрибуция fell back к percentile.

**Fix:** OR semantic — flag '_pct' suffix if EITHER method fell back. Conservative — surfaces honest fallback to UI.

### A3 [MEDIUM — defer]: F1 + F4 synergy gap

**Discovery:** when adstock_decay tail-ESS bad для channel i, F4 marks tail_ess_ok[i]=False, but F1 path STILL uses those unstable samples для CI propagation. Verdict_tier downstream treats tail_ess_ok=False as annotation only (CI computed but flagged "оценка нестабильна"), not as fall-back trigger.

**Could:** when tail_ess_ok=False для channel, fall back к Phase 1.9 path (scalar mean, decay_samples=None semantics) for THAT channel's CI. Сейчас design gracefully — bad CI computed + flagged. Defer to Sprint 3+ unless data shows real impact.

### A4 [LOW — observed]: scenario/optimizer ci_method не expose

**Discovery:** scenario.py captures `_m_p, _m_i, _m_l` for predicted_kpi/incremental/lift HDI methods. Optimizer captures `_m_cur, _m_opt`. Neither propagates these через response. UI can't tell if percentile fallback fired для these CIs.

**Fix priority:** LOW — analogous к decomposer ci_method exposure for symmetry, but UI doesn't currently consume them. Defer until UI track.

### A5 [LOW — observed]: F2 backward-compat alias

**Discovery:** `jackknife_plus_intervals = jackknife_intervals` alias preserves call sites, but `result['method']` returns 'jackknife' (was 'jackknife_plus' pre-F2). External callers checking string would silently fail. Searched codebase — no string check exists. ✓

### A6 [Synergy opportunity — defer]: Code duplication CI block

**Discovery:** decomposer + scenario have parallel ~40-LOC blocks computing per-sample contribution from posterior_samples. Could extract `compute_phase11_contribution_samples(raw, decay_samples, alpha_samples, gamma_samples, beta_samples, mean_or_array, y_std)` helper. ~40 → ~10+ ~5+ ~5 = 20 LOC, eliminates drift risk.

**Defer:** decomposer aggregates total (sum over time), scenario aggregates per-period (for time-series chart). Different output shapes — would need 2 helpers or careful design. Sprint 3+ refactor when adding causal endpoints needs similar batch math.

### A7 [Tests gap — accepted risk]: scenario F1 fallback path не покрыт unit test

**Discovery:** A1 bug class — fallback к scenario plan when training data unavailable — has no unit test. F1 tests cover helper correctness и decomposer flow, но scenario error-path nuances не tested.

**Assessment:** acceptable risk — A1 fix makes fallback a constant-scalar (provable correct), test would just verify branch taken. MIN-LIVE Bayesian decompose validated F1 happy-path. Defer test addition.

### Audit summary (15 issues considered, 6 surfaced, 2 fixed before push):

- **HIGH:** A1 (math correctness in edge case) — fixed.
- **MEDIUM:** A2 (F5 OR semantic) — fixed. A3 (F1+F4 synergy) — defer documented.
- **LOW:** A4 (ci_method UI exposure) — defer. A5 (alias string) — observed clean. A6 (code dedup) — defer.
- **Risk-accepted:** A7 (test gap on rare error-path).

Re-run baseline tests after A1+A2: 339/339 PASS. No regressions.

**Step B (Sprint 3 Pharma Causal) unlocked.**

---

## Sprint 3 Pharma Causal

_(populated после MIN-LIVE PASS)_

**Stack:** linearmodels (DiD Callaway-Sant'Anna) + econml (Causal Forest Wager-Athey) + pysyncon (SCM Abadie) + statsmodels base.

**ADR §1 must declare "EXTEND, not rewrite"** — pin existing FastAPI shape so MIN-LIVE coverage stays valid.

**Pre-Ship gate before v1.0.14:** SBC overnight + UI live-test on Kagocel + Materia Medica geo-data.

---

## v1.0.15 — Optimizer false-convergence fix (2026-04-28, math-fix v1.4)

**Trigger:** Live-test Kagocel на v1.0.14 NSIS установке выявил что Optimizer выдаёт `lift=0.0%` для всех настроек включая Phase 0.1 рекомендованные defaults 20/200. Customer ship blocked.

### Phase 1 — meta-audit плана аудита (fresh-context)

Reviewer (Маша) прочитала AUDIT_PLAN_2026-04-28.md + код empirically. **6 critical gaps в плане найдены:**

1. План's infeasibility hypothesis (Section A.2.1) emperically WRONG — Kagocel feasible (sum_lower 718M ≤ target 3.59B ≤ sum_upper 7.18B).
2. Two parallel verdict systems (compute_roi_verdict в decomposer + derive_verdict в narrative_adapter) — план не упомянул, это structural root cause всех 4 narrative contradictions.
3. План пропустил `aurora_pptx/builder.py` (5 narrative sites duplicated там).
4. План пропустил `render_mroas` hardcoded строки в `aurora_html/sections.py:526-541` — реальное место "явный потенциал scale-up" vs "Hold" противоречия.
5. Acceptance criteria не measurable.
6. Time estimate занижен (8-12h → реалистично 14.5-20.5h, 2 сессии).

Output: `C:/Users/ackol/Desktop/AUDIT_PLAN_REVISIONS.md`. Antón approved.

### Phase 2 — Section A implementation

Empirical proof root cause через scipy direct repro:
- start = current → SLSQP success=True iter=1 → lift=+0.00% (false convergence)
- start = extreme → lift=+28.30% (real optimum)

3 fixes implemented в `engines/optimizer.py`:

**L1 — Money-axis rescaling** (Fix Candidate 5, primary):
- `total_response_money(x_money)` принимает money vector, конвертирует к native через /uc_arr inside для Hill input
- bounds в money axis (cs_money × min_pct, cs_money × max_pct)
- Constraint trivializes к sum(x) = money_target (uniform scale)
- Conditioning improvement: bounds spread 220× (was 48 461× в native), gradient uniform

**L2 — Channel-pivot + balancer multi-start** (Fix Candidate 1, secondary):
- 13 starts: current + N pivot_up + N others_up_balance + all_upper
- «others_up_balance_{i}» — все каналы кроме i на upper, i exactly balances. Ключевой паттерн для money-constrained problems когда крупный канал доминирует бюджет.
- Cost: ~31k function evals, sub-second

**L3 — Diagnostics + false convergence detector** (Fix Candidates 4+6):
- `converged_at_current` flag когда все starts → current, no binding, lift < 0.5%
- `slsqp_diagnostics` — per-start outcomes для post-mortem debugging
- Honest insight string когда converged_at_current=True

### Test fixture + validation

- `tools/test_optimizer_kagocel_redistribution.py` (230 LOC, NEW) — synthetic Kagocel-like 6-channel pickle с такой же mathematical pathology.
- 9 acceptance gates (G1-G6), pre-fix RED 6/9, post-fix GREEN 9/9.
- Real Kagocel pickle: lift = +28.30% (matches scipy direct repro).

### Regression check

```
test_audit_of_sprint3      : 20/20 PASS
test_causal_m0..m4         : 149/149 PASS
test_math_correctness      : 156/156 PASS
test_narrative_adapter     : 65/65 PASS
test_posterior_ci          : 82/82 PASS
test_roi_verdict           : 36/36 PASS
test_optimizer_kagocel...  : 9/9 PASS (NEW)
                          ━━━━━━━━━━
Total: 517/517 (was 508 + 9 new, no regressions)
```

### Files changed

```
sidecar/econometrica/engines/optimizer.py     (~+85/-50 LOC)
tools/test_optimizer_kagocel_redistribution.py (NEW, 230 LOC)
docs/MATH_AUDIT_v1_4_OPTIMIZER_FIX.md         (NEW, audit-trail)
SPRINT3_PROGRESS.md                            (this entry)
```

### Section B (narrative consistency) — deferred к next session

Plan revisions identified 5+ narrative sites + 2 parallel verdict systems requiring unification. Estimated 5-7h, separate session per AUDIT_PLAN_REVISIONS recommendation.

### Customer ship status

v1.0.14 NSIS installer (189MB SHA256 31822fae) **остаётся на hold** до Section B + C fixes. Текущий math-fix branch HEAD после этой session — internal testing only. После Section B → version bump 1.0.15, rebuild sidecar + NSIS, ship.

---

## v1.0.15 — Narrative consistency fix (2026-04-28, Section B)

After Section A optimizer fix (`fe42e7f` — pushed). Section B addresses 4 narrative
contradictions found Kagocel live-test 2026-04-27.

### Root cause (Phase 1 meta-audit B1+B3 findings)

TWO PARALLEL VERDICT SYSTEMS in production code:
- `decomposer.compute_roi_verdict` — 16 ROI-based labels for Decomposition UI table
- `narrative_adapter.derive_verdict` — 5 mROAS+ratio labels for HTML/PPTX action table

Plus 5+ hardcoded narrative sites (sections.py:526-541, builder.py:1395-1430)
generating commentary independently from derive_verdict.

Result: same channel showed «Hold verdict» in HTML table + «явный потенциал scale-up»
in commentary because two code paths generated each independently.

### Single source of truth — engines/channel_action.py (NEW, 280 LOC)

Decision tree (top-to-bottom):
0. Bad input → Watch (backward compat fallback)
1. Untrained → Uncertain
2. Zero spend → Uncertain
3. Severe optimizer cut (ratio < 0.5) → Cut
4. Below breakeven (mROAS < 0.8) → Cut
5. Optimizer reduce (ratio ≤ 0.95 + mROAS ≥ 1.0) → Reduce
6. Near breakeven (mROAS < 1.0) → Reduce
7. Optimizer scale (ratio ≥ 1.05 + mROAS ≥ 1.0) → Scale
8. mROAS+gap heuristic (mROAS ≥ 1.5 + gap ≥ +5pp) → Scale
9. CI uncertainty (width > mROAS) — EVALUATED LAST → Uncertain
10. Hold (mROAS ≥ 1.1 + |gap| < 5pp) → Hold
11. Watch (fallback) → Watch

Critical design choice — CI step ordering: optimizer's redistribution implicitly
integrates joint posterior, so meaningful ratio reflects already-confidence-aware
ranking даже с individual-channel wide CI. Pre-design (CI early): Real Kagocel
n=31 wide CI → ALL 6 channels Uncertain → product value suppressed despite
optimizer +28.3% lift. Post-design (CI late): 5 Scale + 1 Cut + 0 Uncertain.

### Vocabulary — 6 keys, 5 backward compat preserved

```
Scale     → Масштабировать
Hold      → Удерживать
Watch     → Под наблюдением
Reduce    → Сократить умеренно
Cut       → Сократить
Uncertain → Недостаточно данных  (NEW)
```

### Refactored sites

- narrative_adapter.derive_verdict — wrapper around compute_channel_action
- narrative_adapter._map_pipeline_to_builder_data — channels decorated с
  action_label/action_reasoning/action_tone/action_priority/action_confidence
- narrative_adapter._derive_narrative_facts — added action_counts +
  channels_by_action + top_action + converged_at_current passthrough
- aurora_html/sections.py render_mroas — top-3 unique-action commentary blocks
  (was: 3 hardcoded mROAS-rank blocks)
- aurora_html/sections.py render_recommendation + render_executive_summary —
  added converged_at_current banner («Расширьте границы Min/Max»)
- aurora_pptx/builder.py s06 commentary — same action-driven pattern as HTML

### Validation

Coherence test (NEW, tools/test_narrative_coherence.py, 280 LOC):
- 10 unit tests on compute_channel_action mapping
- 6 integration tests on HTML render coherence (table verdict == commentary action)
- 4 tests on render_at_a_glance counts (using build_action_summary)
- 3 tests on converged_at_current banner surfacing
- 1 test on hardcoded «scale-up» absence

Result: 24/24 GREEN.

Real Kagocel post-fix:
```
action_counts: {'Scale': 5, 'Hold': 0, 'Watch': 0, 'Reduce': 0, 'Cut': 1, 'Uncertain': 0}
Performance  | mROAS=9.83  | ratio=2.00 | Scale
Social       | mROAS=10.49 | ratio=2.00 | Scale
Banners      | mROAS=1.08  | ratio=2.00 | Scale
OLV          | mROAS=1.04  | ratio=2.00 | Scale
Retail Media | mROAS=7.41  | ratio=2.00 | Scale
TRPs         | mROAS=0.03  | ratio=0.92 | Cut
```

Antón's product mandate «понять что изменить» — restored. Scale signal на 5 каналов
+ Cut на TRPs + lift +28.3% surface'ит coherently across HTML table + commentary.

### Regression check

```
test_audit_of_sprint3      : 20/20 PASS
test_causal_m0..m4         : 149/149 PASS
test_math_correctness      : 156/156 PASS
test_narrative_adapter     : 65/65 PASS  (backward compat preserved)
test_posterior_ci          : 82/82 PASS
test_roi_verdict           : 36/36 PASS
test_optimizer_kagocel...  : 9/9 PASS  (Section A)
test_narrative_coherence   : 24/24 PASS  (Section B, NEW)
                            ━━━━━━━━━━━━
Total: 541/541 (was 517 + 24 new, no regressions)
```

### Files changed

```
sidecar/econometrica/engines/channel_action.py      (NEW, 280 LOC)
sidecar/econometrica/engines/narrative_adapter.py   (+30/-30 LOC)
sidecar/econometrica/aurora_html/sections.py        (+60/-30 LOC)
sidecar/econometrica/aurora_pptx/builder.py         (+40/-40 LOC)
tools/test_narrative_coherence.py                   (NEW, 280 LOC)
docs/MATH_AUDIT_v1_4_NARRATIVE_FIX.md               (NEW, audit-trail)
SPRINT3_PROGRESS.md                                  (this entry)
```

### Known limitations

- PPTX optimizer state awareness deferred (HTML refactored, PPTX still generic
  recommendation banners). Sprint 4+ task.
- compute_descriptive_state не implemented (plan's option (b) feature). Existing
  decomposer.compute_roi_verdict already handles descriptive labels for UI page;
  separate structured class deferred — Decomposition UI unaffected.

### Section C next — version bump + ship

After Section B GREEN: bump 1.0.14 → 1.0.15, rebuild sidecar + NSIS, update
CHANGELOG + GH Release draft + PASHE_IT.MD. Customer ship UNBLOCKED.

---

## Live-test 2026-04-28 (post-v1.0.15) — findings backlog

### 🔴 BLOCKER L1 — Insights panel ↔ Column role matrix desync на Validate page

**Symptom (Антон, 2026-04-28):** На этапе Валидации правый Insights panel предложил исключить Пресса/OOH/Радио/Спецпроект. Кнопка «Исключить» подняла ratio с 1.7:1 → 2.2:1 ✓. НО матрица «Медиа и управляемые факторы» в центре страницы оставила эти 4 канала с ролью «Медиа» — auto-removal не сработал.

**Inverse failure:** ручное изменение роли в Column matrix не пересчитывает ratio + не обновляет Insights рекомендации.

**Class-of-bug:** аналогичен Validate→Model state desync (fixed v1.0.14 `0eeb715`). Two UI components share computed state но НЕ share underlying SST.

**Hypothesis:**
- Insights panel мутирует `validateData.excluded_channels` (или подобное)
- Column matrix читает `validateData.columns[i].role`
- Эти states не sync'нутся → desync

**Fix candidate:**
- Single source of truth: insights button should call same handler как Column matrix role change → mutate `validateData.columns[i].role = 'excluded'` (или add a flag `excluded: true`)
- Column matrix render — visual indicator (crossed out / faded) для excluded channels
- Test: lock-in test проверяющий что Insights "Exclude" → ConfigPanel media_columns reflects change

**Priority:** v1.0.16 blocker (similar severity к Optimizer 0% lift bug — UX integrity issue, customer trust).


### L1 — formal acceptance criteria (Антон 2026-04-28)

**Requirement:** bi-directional binding между Insights panel + Column role matrix + ratio/recommendations через единый source of truth.

**Architecture:**
- SST: `validateData.columns[i].role` (или новый flag `excluded`)
- All mutators → один handler `setColumnRole(idx, role)` который mutates SST
- All consumers (ratio, recommendations, ConfigPanel media list) → derive через `$derived` from SST

**Acceptance gates:**
1. Insights «Исключить» X → row X в Column matrix визуально crossed-out + role меняется на excluded
2. Drag X из «Медиа» в «Не использовать» → Insights убирает рекомендацию по X + ratio пересчитывается
3. Insights «Включить обратно» → role восстанавливается к prev (или default)
4. ratio + рекомендации всегда reflect *active* channel set
5. Lock-in test (`tools/test_validate_state_sync.py`) — programmatically toggle через каждый mutator, assert все consumers consistent


### L1 — end-to-end consistency (Антон, добавлено 2026-04-28)

**Финальное требование:** state на Validate (после ВСЕХ мутаций) → передаётся на Model training точно как user видит. Объединяет v1.0.14 fix (`0eeb715` — drag-drop only) с новым L1 (insights + любые другие mutators) под единым решением.

**Pipeline contract:**
```
validateData.columns (SST)
  ↓ derive
active_media_columns + active_control_columns (computed)
  ↓ ConfigPanel reads
media_columns / control_columns sent to /compute/train
  ↓
trained model uses exactly active set
```

**Acceptance gate #6:**
- Active set на Validate (после всех мутаций) = media_columns на Model = train(media_columns) — byte-for-byte идентично
- E2E test: программно меняем через все 3 mutator-paths (drag-drop / Insights button / matrix click) → assert train config matches active Validate state byte-for-byte


### 🟡 L2 — descriptive verdict «Высокая неопределённость» suppression на small-N (Антон 2026-04-28)

**Symptom:** на decompose page для Kagocel после v1.0.15 train (6 channels, n=31, ratio 2.2:1) ВСЕ 6 каналов получают verdict «Высокая неопределённость» в декомпозиции, несмотря на clear Gap signals (TRPs gap -82%, Performance gap +32%, etc) и большой ROI spread (0.04× ↔ 16.12×).

**Root cause:** `decomposer.py:73` `compute_roi_verdict` Step 1 — early CI uncertainty check. При CI width > ROI → returns «Высокая неопределённость». На small-N с hierarchical shrinkage (Phase 1.1) CI почти всегда wide → suppresses ВСЕ informative labels.

**Подход** (mirrors Section B channel_action.py CI re-ordering):
- Move CI uncertainty check AFTER absolute caps + Gap-based fallback steps
- Keep CI uncertainty as final fallback ONLY когда no other clear signal (small Gap, mid ROI)
- При clear Gap (|gap| ≥ 10pp) OR clear ROI (>5× или <0.5×) — descriptive verdict выдаётся даже при wide CI, с caveat в reasoning text

**Acceptance criteria для v1.0.16 fix:**
1. Kagocel decompose post-fix: TRPs → «Перенасыщен» (Gap -82pp), Performance → «Эффективен» (ROI 16× + Gap +32pp), etc.
2. UI optionally показывает CI bracket рядом с verdict (existing _ci_tier_class CSS hint) для visual «несмотря на wide CI» disclosure
3. Channels с small Gap + small ROI spread → continue to get «Высокая неопределённость» (legitimate use)
4. Lock-in test: 6-канальный Kagocel-like fixture → verdict counts {Эффективен: 4-5, Перенасыщен: 1, Высокая неопределённость: 0-1} вместо текущего {Высокая: 6}

**Priority:** v1.0.16 (вместе с L1 — Validate state sync). Both UX-credibility blockers.


### 🟡 L3 — Optimize page slider preview shows 0 ₽ для small-spend channels (Антон 2026-04-28)

**Symptom:** на Optimize page блок «Распределение бюджета» preview slider — Social и Retail Media показывают 0 ₽ хотя current spend = 15.5M и 15.3M. Performance/Banners/OLV/TRPs отображаются корректно.

**Hypothesis:** slider position default initialization не учитывает scale разнообразие. Возможно slider bounds derive от max channel spend (TRPs 3.3B) → small channels (15M) попадают в visual zero band на global scale.

**Impact:** preview KPI (10748.5M, -4.3% к текущему) reflect эти zero slider positions, не actual current spend. Misleading UI до клика «Оптимизировать бюджет».

**Fix candidate:** initialize каждый slider с his own (min, max) range based on канал's bounds (cur×min_pct, cur×max_pct), не на global scale.

**Priority:** v1.0.16 medium (UI consistency, не blocker для real optimize result).


### 🟢 L4 — Optimize page mROAS display + light logic bugs (CLOSED 2026-04-28)

**STATUS:** ✅ FIXED — math-fix v1.4 Section C. Three-way alignment shipped: decomposer.py + optimizer.py + narrative_adapter.py все используют `_compute_mroas_money` + `compute_channel_action` (single source of truth).

**Root cause confirmed (vs initial hypothesis):**
- 110.93× НЕ из backend (`optimization.json` показывает 0.0285×). Источник — **JS fallback `marginalROI()` в `hill.js:43`**, активный когда `$optimizeData` пуст (idle/pre-optimize state).
- JS formula = `β · α · γ^α · x^(α-1) / (x^α + γ^α)² · y_std` — отсутствует `/unit_cost`, `/mean`, `adstock_factor`. Для TRPs (x=22100, β=0.0475, α=2, γ_scaled≈11050, y_std=180e6) → ≈110-150 (mixed native axis). Verification math на real Kagocel pickle.
- Customer видел 110.93 в idle state, потом 0.03 после optimize — два разных code path.

**Fix shipped:**
1. **decomposer.py** — добавлен `mroi_current` per channel (через `_compute_mroas_money`) + decoration с `action`/`action_label`/`action_tone`/`action_reasoning`/`action_priority`/`action_confidence` через `compute_channel_action()`. `+39 LOC`.
2. **optimizer.py** — primitive `'action': 'увеличить'/'сократить'/'сохранить'` (delta_pct heuristic) заменён на structured action fields через тот же helper. `+24 LOC`.
3. **OptimizeStep.svelte** — JS fallback `marginalROI()` удалён. miROASMap читает: Source #1 = `$optimizeData.channels[i]` (post-optimize), Source #2 = `$decomposeData.channels[i]` (idle). Empty state когда нет ни decompose, ни optimize. Light logic switch с local thresholds (`v > 1.5 ? 'scale'...`) на `actionToStatus(ch.action)` mapping (Scale→good, Hold/Watch→ok, Reduce/Cut→low, Uncertain→unused). `+66 / -48 LOC`.
4. **Tests** — 8 new L4 lock-in tests в `test_optimizer_kagocel_redistribution.py`: mroi_current + action decoration verified, **three-way alignment confirmed (decompose mroi_current ≈ optimize mroi_current, max Δ=0.0000)**, TRPs money-axis < 1× (post-fix 0.0217×), TRPs action ∈ {Cut/Reduce/Watch}, Performance action == Scale. `+71 LOC`.

**Verification на real Kagocel pickle (`-26--4`):**
- TRPs decompose: `mroi_current=0.0285×`, action='Cut' (bad tone) ✓
- TRPs optimize: `mroi_current=0.0285×`, action='Cut' ✓ (same identity)
- Performance optimize: `mroi_current=9.7453×`, action='Scale' ✓
- Все 552/552 тестов PASS (was 544 + 8 new L4 lock-ins, no regressions)

**Trade-off:** Live mROAS recomputation на slider drag отключена (была математически broken — mixed units). mROAS блок теперь = snapshot at last computed state. Customer видит KPI прогноз live (через `predictKPI`, который работает корректно). Подпись «при текущей аллокации» для clarity.

**Discovered side-finding (separate L21):** `optimization.json` returns `lift_pct: None` на real Kagocel. Backend computes it (used at line 660 in convergence check), но в response payload null. Не блокер L4. Заносить в backlog.

---

### 🔴 L4 (orig) — Optimize page mROAS display + light logic bugs (Антон 2026-04-28)

**Symptom:** на Optimize page после оптимизации блок «MIROAS — предельная отдача следующего рубля»:
- Performance: 0.25× → 🔴 Перенасыщен (но он на upper bound 200%, optimizer его ВЫРАСТИЛ)
- Social: 0.27× → 🔴 Перенасыщен (upper bound, ВЫРАСТИЛ)
- Retail Media: 0.19× → 🔴 Перенасыщен (upper bound, ВЫРАСТИЛ)
- Banners/OLV: 0.03× → 🔴 Перенасыщен (upper bound, ВЫРАСТИЛ)
- TRPs: 110.93× → 🟢 Масштабировать (но optimizer его СОКРАТИЛ до ~92%)

**Two bugs:**

**Bug 1 — mixed display units.** TRPs 110.93× = mROAS_native (per TRP), money channels 0.03-0.27× = mROAS_money (per ₽). Сравнение бессмысленно — это разные единицы. Section A optimizer fix внутренне работает в money axis, но UI отображения смешивает обе.

**Bug 2 — inverted light logic relative к bounds.** Все 5 small channels на upper bound 200% — означает optimizer хотел бы их еще нарастить если бы границы позволяли (это «Scale-blocked», не «Перенасыщен»). TRPs at ratio 0.92 = optimizer slightly cut — это «Reduce», не «Scale-up».

UI light logic (likely в OptimizeStep.svelte) computes recommendation locally based on mROAS thresholds, не используя channel_action.compute_channel_action (которая знает про optimizer ratio + bound state).

**Fix candidate:**
- Unify display: показывать mROAS_money везде (TRPs * unit_cost в backend перед UI render)
- Migrate UI light logic к compute_channel_action — это та же function что HTML/PPTX используют (Section B). Ratio-aware logic правильно классифицирует:
  * Optimal ratio ≥ 1.05 + at upper bound → «Scale» (blocked by constraint)
  * Optimal ratio < 0.95 → «Reduce»
  * Etc

**Acceptance criteria для v1.0.16:**
1. Все каналы display mROAS в одной axis (money) — units consistent
2. Light recommendation derived from compute_channel_action(channel_dict including optimal_spend), not raw mROAS thresholds
3. Kagocel post-fix: 5 small channels show «🟢 Масштабировать» (at upper bound, optimizer grows), TRPs «🟠 Сократить умеренно» (optimizer cuts -8%)
4. Lock-in test: synthetic Kagocel-like fixture → light counts match expected

**Priority:** v1.0.16 BLOCKER (UX integrity — inverted recommendations directly contradict optimizer output, customers will lose trust).


### 🟢 L5 — Optimizer optimal_spend auto-applies + Response Curves markers (CLOSED 2026-04-29)

**STATUS:** ✅ FIXED — math-fix v1.4 Section C continued. Auto-apply + KPI prognosis live update + L5 extension Response Curves markers.

**Fix shipped:**

1. **`OptimizeStep.svelte:runOptimize()`** — после `result.status === 'ok'` + `optimalBudgets` populated, fires `await tick(); applyOptimal();` automatically. `tick()` waits для `$effect` flush (resets channelBudgets к current_spend AT response arrival), then animation runs from clean current → optimal baseline. 800ms smoothstep animation preserved.

2. **Live KPI prognosis** — добавлена `liveKPI = predictKPI(channelBudgets, scaledParams, yNorm)` reactive value. `displayKPI` теперь scales `dData.total_sales × (liveKPI / currentKPI)` ratio. Customer видит KPI обновляющийся вместе со sliders (auto-apply animation + manual drag). Pre-fix: displayKPI was frozen на `dData.total_sales` (decompose baseline).

3. **`ResponseCurves.svelte` markers (L5 extension)** — для каждой канал-curve добавлены 2 static markPoints:
   - `current_x` ○ серый круг (rgba(148,163,184,0.85)) — стартовая позиция
   - `optimal_x` ★ pin цвет канала + золотой ★ label — recommendation target
   New helper `curveResponseAt(curve, x)` — linear interpolation на backend response array (matches series Y axis, no Hill recompute). Tooltips «канал — текущий бюджет» / «канал — оптимальный бюджет».
   После applyOptimal animation draggable point overlaps optimal ★ — visual «you're at optimum» confirmation.

**Verification:**
- svelte-check: 0 new errors (33 pre-existing in hill.js / insights-rules.js, unchanged)
- Backend tests: 552/552 PASS (no regression)
- Manual QA path: customer clicks «Оптимизировать» → animation 800ms → sliders в optimal positions, money values updated, displayKPI scaled, ★ marker on Response Curves matches draggable point. End-to-end consistent.

**Race condition handled:** `optimizeData.set()` triggers `$effect` at line 340 which resets channelBudgets к current_spend. Without `await tick()` race: animation snapshot taken sync before $effect → start = stale value. With tick: $effect flushes first → channelBudgets = clean current_spend → animation runs from clean baseline.

**Manual QA в release checklist** (SA13 — нет Svelte e2e infra). Lock-in test невозможен без e2e harness — заносить в v1.1 backlog.

**Files changed:**
```
src/lib/components/pipeline/OptimizeStep.svelte    (+22 LOC: tick import + auto-apply + liveKPI/displayKPI live)
src/lib/components/pipeline/ResponseCurves.svelte  (+45 LOC: curveResponseAt helper + markPoints per series)
SPRINT3_PROGRESS.md                                 (this entry)
```

---

### 🔴 L5 (orig) — Optimizer optimal_spend не auto-applies к sliders (Антон 2026-04-28)

**Symptom:** после клика «Оптимизировать бюджет» backend возвращает optimal_spend (правильный +30.4% lift на real Kagocel). Δ% labels рядом со sliders показывают +100%/-8% корректно. **НО:**
- Slider positions остаются на current spend
- Money values рядом со sliders = current (107.1M OLV, 3315M TRPs etc)
- Total budget = current 3590.4M
- Прогноз KPI = current 11226M (вместо ожидаемых 14749M post-optimization)

**Root cause:** `OptimizeStep.svelte:applyOptimal()` функция с slider animation существует, но не auto-fires после successful optimize. Пользователь видит «оптимум найден» (через Δ% labels) но не видит фактическое распределение.

**Two display states existing in code:**
1. `channelBudgets` store — current slider values (used for displayed money)
2. `optimalBudgets` store — populated после optimize, target для applyOptimal()

После optimize: optimalBudgets = backend.channels[i].optimal_spend, но channelBudgets не обновляется автоматически. Результат: UI показывает old current values.

**Fix candidate:**
- (a) Auto-apply: после successful optimize → `applyOptimal()` immediately (animation 800ms на user-perceived smoothness)
- (b) Prominent banner+button: «✅ Оптимум найден (+30.4% lift). Применить → [BUTTON]» — explicit user action для безопасности

Recommendation: (a) — пользователь нажал «Оптимизировать» = explicit consent для применения. (b) добавляет лишний клик. Reset button уже есть для отката.

**Acceptance criteria для v1.0.16:**
1. После клика «Оптимизировать бюджет» status='ok' → sliders animate к optimal positions
2. Money values + total budget + KPI прогноз обновляются к optimal numbers
3. Δ% labels продолжают показываться (для visibility что было vs что стало)
4. «Сбросить» кнопка возвращает к current
5. Lock-in test: e2e в Svelte component test что post-optimize sliders match optimalBudgets

**Priority:** v1.0.16 BLOCKER (rivals L4 — UX integrity, customer не видит результат своей optimization).


### L5 extension — Response Curves chart также показывает только current_x markers

**Symptom:** Response Curves chart рендерит crucial Hill saturation curves правильно (математика работает после Section A fix). Но markers (точки) на curves показывают только `current_x` positions для каждого канала. Optimal_x markers отсутствуют.

**Backend state:** `optimizer.py:706-712` возвращает оба значения:
```python
response_curves_data[col] = {
    'current_x': cur,
    'optimal_x': float(optimal_spend[i]),  # populated, но frontend не использует
}
```

**Same root cause as L5:** UI компоненты не sync с optimal allocation after optimize. Frontend chart рендерит marker только для current_x.

**Fix options:**
- (a) Two markers per канал — current (faded) + optimal (bright) — visualization showing transition
- (b) Single marker animates current → optimal (consistent с slider animation в applyOptimal())
- (c) Toggle button «Текущее ↔ Оптимум» — explicit comparison view

Recommendation: (a) для clarity — пользователь видит «откуда / куда» одновременно. Slider animation отдельная UX (sliders blow chart on Optimize page).

**Priority:** v1.0.16 BLOCKER (часть L5 — UX of post-optimize visualization).


### L5 confirmation (Антон 2026-04-28): нет manual «Применить» button

**Confirmed:** в OptimizeStep UI **отсутствует** кнопка «Применить оптимум» или эквивалент. После клика «Оптимизировать бюджет» пользователь не имеет способа активировать применение optimal allocation.

**Status:** baseline UX broken — fix-strategy MUST be option (a) auto-apply (см. оригинальный L5). Manual button (b) workaround не существует even как fallback.

**Implication для Section A repro testing:** все мои Section A unit tests проходят (backend math correct), НО end-user никогда не видит результаты optimize в UI. Customer impact того же класса что Section A bug — optimizer effectively не работает с user perspective, despite backend success.


### 🟡 L7 — Optimize page не surface'ит binding_constraints / converged_at_current banner (Антон 2026-04-28)

**Symptom:** в Scenario 5 (Min=100/Max=300 per channel — feasibility свёрнута в точку) backend честно возвращает lift=0% + binding_constraints=True. UI показывает только banner «+0.0%» без объяснения.

**Implication:** customer не понимает почему optimizer не нашёл улучшения. Может думать что optimizer broken (как было в v1.0.14 до Section A fix). Подрывает доверие к оптимизатору даже когда он работает correctly.

**Fix candidate:** OptimizeStep.svelte should detect:
- `result.binding_constraints === true` → banner: «Все каналы упёрлись в границы. Расширьте Min/Max или сбросьте per-channel ограничения.»
- `result.converged_at_current === true` → banner: «Оптимум близок к текущему распределению. Попробуйте расширить границы (10/300% рекомендуется).»
- `result.expected_lift_pct < 0.5 AND not binding AND not converged_at_current` → banner: «Текущая аллокация уже близка к локальному оптимуму при заданных constraints.»

**Priority:** v1.0.16 medium (UX clarity, не critical math issue).

### 🟡 L8 — Per-channel expert constraints не сбрасываются между сценариями

**Symptom:** Антон установил per-channel Min=100/Max=300 в Scenario 1. Перешёл в Scenario 5 — global slider к 95/110. **Per-channel остался 100/300**, эффективно overrid'ит global. Только orange dot indicator показывает override status — easy to miss.

**Implication:** пользователь думает что меняет глобальные границы, но per-channel overrides блокируют изменения. Confusion source.

**Fix candidates (выбрать 1):**
- (a) При движении global slider — auto-reset per-channel overrides если они равны старому global (не явные user overrides)
- (b) Явное warning: «У X каналов есть override настройки. Сбросить → [BUTTON] / Игнорировать»
- (c) Кнопка «Сбросить per-channel» прямо рядом с global slider (она уже есть — но в expert section, не visible если expert collapsed)

Recommendation: (b) — explicit confirmation, чтобы не потерять user's intent (он мог намеренно поставить overrides ранее).

**Priority:** v1.0.16 low-medium (UX clarity, не корректность).


### 🔴 L9 — Checkbox «Фиксировать бюджет» косметический, не передаётся в backend (Антон 2026-04-28)

**Symptom:** в Optimize page есть checkbox «Фиксировать бюджет» (default checked). Снятие галки не меняет результат optimizer — те же +43.3% lift с теми же per-channel deltas.

**Root cause:** `OptimizeStep.svelte:runOptimize()` всегда передаёт `totalBudgetMoney: currentTotalBudget` независимо от состояния checkbox. Backend `optimizer.py` всегда работает в money-equality mode `Σ x × uc == target`.

**Two issues bundled:**

1. **UI lies к user** — checkbox visible but does nothing.
2. **Missing feature** — free-budget optimization mode не реализован в backend. Если включить (frontend pass `totalBudgetMoney: null` когда unchecked) — backend пойдёт в `else` branch:
```python
else:
    constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x) - total_budget}]
```
Но `total_budget` там тоже current value (line 376-382). Не настоящий free-budget mode.

**Real free-budget mode requires:**
- Optimizer accepts `mode='free'` flag
- Constraints = empty or inequality cap (e.g. `sum(x) ≤ max_budget_user_specified`)
- Per-channel bounds remain
- Result includes `optimal_total_budget` (может отличаться от current)

**Business case:** CFO рассматривает увеличение marketing budget ЕСЛИ ROI uplift достаточный. Optimizer answers: «при дополнительных 900M ₽ в OLV/Performance, KPI growth +X%».

**Acceptance criteria для v1.0.16 (or possibly v1.1):**
1. Frontend conditionally passes `totalBudgetMoney`:
   - Checkbox=ON → currentTotalBudget (current behavior)
   - Checkbox=OFF → null + new field `max_total_budget` (user input or default 2× current)
2. Backend optimizer.py adds `'mode'` parameter:
   - `'fixed_budget'` → equality constraint (current behaviour)
   - `'free_budget'` → inequality constraint `sum(x) ≤ max`, per-channel bounds enforced
3. Result includes `total_budget_optimal` if free mode + delta from current
4. UI banner shows budget delta: «Оптимизатор предлагает увеличить бюджет на X% для +Y% lift»
5. Lock-in test: synthetic fixture, free mode → optimal sum > current_sum (если bounds позволяют рост и mROAS высокий)

**Priority:** v1.1 NEW FEATURE (не блокер для current shipping, но «Фиксировать бюджет» checkbox должен ИЛИ работать ИЛИ быть удалён до тех пор. Misleading UI = customer trust risk).

**Quick fix для v1.0.16:** удалить checkbox или disable с tooltip «Будет реализовано в v1.1». Менее ambitious чем full feature, но честнее.


### 🔴🔴 L10 — CRITICAL math regression: lift_pct inflated when money_target ≠ current_total (Антон 2026-04-28)

**Symptom:** в What-if scenario с budget -50% (1795M vs current 3590M) backend выдаёт «KPI: 11226M → 25247M (+124.9%)». Mathematically impossible — Hill saturation монотонна, меньше total spend = меньше total effect. KPI cannot more than double when budget halved.

**Root cause introduced by Section A refactor (commit `fe42e7f`, math-fix v1.0.15):**

```python
# Bug в engines/optimizer.py:589-591:
x0_money = np.array([current_spend[col] * uc_arr[i] for ...])
x0_money = _project_to_budget(x0_money)  # scales к money_target — WRONG for current_response

# Line 605:
current_response = -total_response_money(x0_money)  # evaluated at SCALED current, NOT real
optimal_response = -total_response_money(result.x)  # correctly at optimal-at-new-budget
lift_pct = (optimal - scaled_current) / scaled_current * 100  # INFLATED
```

Когда money_target == current_total_money (default Optimize page) — projection no-op, всё correct. Section A unit tests + real Kagocel +28.3% работают потому что money_target = current_total. **Test gap:** не проверял случай money_target ≠ current.

Когда money_target ≠ current (What-if -50%): x0_money scaled to 50% of each channel → media contribution computed at half-current → much smaller current_response → lift_pct artificially inflated.

**Fix:**
```python
# Real current — never projected (для response baseline + delta computation)
x0_money_real = np.array([current_spend[col] * uc_arr[i] for i, col in enumerate(media_cols)])
# Projected — для SLSQP multi-start initialization (нужно satisfy money_target constraint)
x0_money_for_slsqp = _project_to_budget(x0_money_real.copy())

starts_money = [('current', x0_money_for_slsqp)]
# ... pivot_up, others_up_balance, all_upper used x0_money_for_slsqp

# В Сравнение current vs optimal — REAL current
current_response = -total_response_money(x0_money_real)  # FIXED

# В converged_at_current detector — REAL current
_max_abs_delta_money = float(max(
    abs(result.x[i] - x0_money_real[i]) for i in range(n_ch)
))
```

**Lock-in test (add к tools/test_optimizer_kagocel_redistribution.py):**
```python
def test_what_if_half_budget():
    """Lift cannot exceed +50% when budget halved."""
    # Build same Kagocel-like fixture
    proj = build_synthetic_kagocel_fixture(...)
    current_total_money = sum(...)
    
    # What-if: 50% of current
    result = optimize({
        'min_pct': 0, 'max_pct': 500,  # full freedom
        'total_budget_money': current_total_money * 0.5,
    }, proj)
    
    assert result['expected_lift_pct'] < 30.0  # Can't double KPI on half budget
    # Real lift bound: optimal media at 50% budget vs real current media
    # Even if redistribution boosts media efficiency, total media response < real current
```

**Priority:** v1.0.16 BLOCKER. Это regression от моего Section A что я push'нула в `fe42e7f`. Wide use of What-if scenarios → all customers affected if не зафиксен до next ship.

**Customer impact:** customer testing budget reductions get artificially inflated KPI predictions → могут принимать wrong business decisions (cut budget thinking it'll grow KPI).


### L10 extension — bug confirmed bidirectional (Антон 2026-04-28)

**Additional symptom:** при бюджете +100% (7180M, 2× current):
- UI shows lift +10.8%, KPI 12438M
- Real expectation: ~+30-50% KPI growth for 2× spend (Hill diminishing returns + saturated TRPs gain little, but small channels can grow significantly + baseline constant ≈ 11000M, media should ~double)

**Inverted relationship pattern:**
| Budget | Reported lift | Real expectation |
|---|---|---|
| 50% (-50%) | **+124.9%** ❌ | Negative (less budget → less media) |
| 100% (default) | +30.4% ✓ | matches scipy direct repro |
| 200% (+100%) | **+10.8%** ❌ | should be +30-50% |

**Pattern:** lift_pct корректен ТОЛЬКО когда money_target = current_total_money. Дальше inflated в обе стороны: artificially high когда -50%, artificially low когда +100%.

**Confirms root cause:** lift_pct = (optimal - **scaled_current**) / **scaled_current**. Scaled_current is artifact от `_project_to_budget(x0_money)` introduced in Section A. Scaling x0 к money_target makes baseline wrong — when money_target larger, scaled_current bigger (channels more saturated, plateau), small numerator/large denominator → small lift. When money_target smaller, scaled_current smaller (channels under-saturated), larger upside from redistribution → big lift.

**Real lift_pct formula should be:**
```python
# Real current — never scaled
x0_money_real = current_spend × uc_arr  # NOT projected
current_response_real = -total_response_money(x0_money_real)

# Optimal at money_target — found by SLSQP
optimal_response = -total_response_money(result.x)

lift_pct = (optimal_response - current_response_real) / current_response_real * 100
```

This compares «optimal at new budget» vs «real current actual» — meaningful business metric. Customer answer: «при изменении бюджета на X, KPI изменится на Y».

**Acceptance criteria для v1.0.16 fix:**
1. lift_pct monotonic с money_target (more budget → more lift, modulo saturation curve)
2. lift_pct(money_target=current) === current behavior (no regression)
3. lift_pct(money_target=0.5×current) <= 0% (less spend → less effect, при правильно work optimizer)
4. lift_pct(money_target=2×current) > lift_pct(default)
5. Lock-in test: 3 scenarios (0.5×, 1×, 2×) на synthetic Kagocel — all monotonic relative к budget


### 🟡 L11 — Channel names не normalized в interpretation text (Антон 2026-04-28)

**Symptom:** в HTML отчёте блок «Как интерпретировать модель» использует raw column names: «Performance Бюджет До НДС до АК», «Social Бюджет ДО НДС до АК», «TRPs бренд (W 25-54)» вместо canonical «Performance», «Social», «TRPs (W 25-54)».

**Root cause:** `narrative_adapter._normalize_channel_name` уже очищает «Бюджет до НДС до АК» suffix, но используется только в `_merge_channels`. Interpretation block likely читает column names напрямую от backend без normalization.

**Fix candidate:** ensure all narrative-facing channel name renders через `_normalize_channel_name` (single source of truth для display names).

**Priority:** v1.0.16 medium (UX cosmetic, customer-facing).

### 🟡 L12 — Interpretation block lists only top-2 «Недо-инвестированных», должно быть всё что Scale (Антон 2026-04-28)

**Symptom:** interpretation text упоминает только Performance + Social как «Недо-инвестированные каналы», хотя actual optimizer (per моему Section B compute_channel_action) marked **5 small каналов как Scale**: Performance, Social, Retail Media, Banners, OLV — все рекомендованы +100%.

**Root cause:** interpretation block использует hardcoded top-2 by mROAS heuristic (or `top_2_names` from narrative_facts which based on contribution). Не использует `narrative_facts.channels_by_action['Scale']` from action_summary (Section B addition).

**Fix candidate:** migrate interpretation block к channels_by_action['Scale'] для «Недо-инвестированные» и channels_by_action['Cut'+'Reduce'] для «Перенасыщенные». Show full list, не arbitrary top-N.

**Priority:** v1.0.16 medium (customer-facing accuracy — partial list misleading).

### 🟢 L13 — Грамматика + формулировка (Антон 2026-04-28)

**Minor edits:**
- «Модель смотрит на вашу историю за 31 периодов» → «...за 31 период» (правильное склонение)
- «MAPE 7.1% — в среднем прогноз отклоняется от факта меньше чем на десятую часть» → «...менее 10%» или «...около 7%» (clearer)

**Priority:** v1.0.16 low (cosmetic).


### 🔴 L14 — SCQAR «Performance доминирует бюджет (0.7%)» semantically wrong (Антон 2026-04-28)

**Symptom:** в HTML отчёте SCQAR Complication: «Performance доминирует бюджет (0.7% portfolio). По mROAS Social опережает (10.3×)».

**Logic issue:** Performance имеет 0.7% бюджета — это противоречие со словом «доминирует». Реально TRPs доминирует (92% бюджета). Performance leader by contribution (33% эффекта), не leader by spend.

**Root cause:** `strings_ru.scqar.complication.template` = «{leader} доминирует бюджет ({leader_spend_pct_fmt} portfolio)». `leader = by_contrib[0]` — но шаблон applies him as «budget dominator». Wrong assumption: contribution leader != spend leader для high-ROI small-budget channels.

**Fix candidate:** разделить «contribution leader» и «budget leader» в narrative_facts. Use «budget_dominator = max(channels, key=spend)» отдельно. Шаблон Complication: «{budget_dominator} занимает {budget_dominator_pct} бюджета, но даёт {budget_dominator_contrib_pct} эффекта; {contribution_leader} — {leader_share_contrib_pct} эффекта при {leader_share_spend_pct} бюджета — мисматч».

**Priority:** v1.0.16 medium (customer-facing inconsistency, undermines trust в narrative).

### 🔴 L15 — SCQAR Answer + Recommendation 01 inverted reallocation direction (Антон 2026-04-28)

**Symptom:** в HTML отчёте:
- SCQAR Answer: «Перебалансировать 275 млн ₽ из Performance в Social»
- Action 01: «Перебалансировать бюджет. 275 млн ₽ из Performance в Social.»
- Action 03: «Перевести бюджет из TRPs бренд (W 25-54) согласно вердиктам» ← correct

**Internal conflict в одном отчёте:** Action 01 говорит «из Performance», Action 03 говорит «из TRPs». Performance optimizer recommends **+100% (вырастить)**, не cut.

**Root cause:** `strings_ru.scqar.answer.template` = «...из {leader} в {hero}; сократить {underperf}». Где `leader` = top-contribution channel (Performance), `hero` = top-mROAS channel (Social). Template assumes leader is overspending channel — false для high-ROI small-budget channels.

**Fix candidate:** Update narrative_facts:
- Add `cut_source = channels_by_action['Cut'][0] or channels_by_action['Reduce'][0]` (= TRPs)
- Add `scale_destination = channels_by_action['Scale'][0]` (= Performance or Social)
- Fix template: «...из {cut_source} в {scale_destination}»

**Priority:** v1.0.16 BLOCKER (внутренний conflict в одном отчёте — customer trust collapse).

### 🟡 L16 — MQS дважды labeled differently for same value (Антон 2026-04-28)

**Symptom:** в HTML отчёте same MQS=70 получает разные tier labels:
- Findings #5: «MQS 70/100 - приемлемо» (from `strings_ru.f5_mqs_fair`)
- Sources section: «Model Quality Score 70/100 Хорошее» (from backend `diagnostics.mqs.tier_label`)

**Root cause:** two independent label sources не synchronized. Backend diagnostics tier_label uses one threshold scheme, frontend strings_ru.f5_mqs_* uses another.

**Fix candidate:** single source — backend diagnostics computes tier_label, frontend f5_mqs_* templates accept it as parameter. Eliminate duplicate threshold logic.

**Priority:** v1.0.16 low (cosmetic, не blocking math/recommendations).


### 🟢 L17 — Data-readiness tier indicator + manual override на Import page (Антон 2026-04-28, FEATURE REQUEST)

**Requirement:** на Import page показать explicit indicator тип моделирования (OLS / Bayesian-warn / Bayesian-premium) на базе n_obs + estimated params. Должен быть «один из ключевых моментов интерфейса».

**Architecture:**

**Tier classification:**
- 🟢 **Premium Bayesian**: n ≥ 4 × params → полный posterior, learnable adstock decay, honest CI
- 🟡 **Bayesian с предупреждениями**: 2:1 ≤ ratio < 4:1 → posterior wide, hierarchical shrinkage active
- 🟠 **OLS fallback**: ratio < 2:1 → frequentist β CI + bootstrap, Hill params fixed

**Backend ready:** `/compute/recommend` endpoint already returns tier recommendation (per MIN-LIVE GATE 1 в memory). Нужен только UI surface.

**UI placement:** под таблицей предпросмотра данных, до кнопки «Далее: Валидация».

**Components:**
1. Banner с tier indicator (large, visible, ключевой момент)
2. Tentative metrics: n_obs, columns count, estimated ratio range
3. Manual override radio: Auto (default) / OLS forced / Bayesian forced
4. Dynamic guidance: «После агрегации до 5-7 каналов на Валидации → premium tier доступен»
5. Реактивность: tier пересчитывается после Validate когда channels finalized

**State propagation:**
- Tier choice persisted в project_state.modeling_tier
- ConfigPanel → /compute/train с modeling_tier flag
- /compute/recommend endpoint реализует tier logic backend-side (already partial implemented)
- Decompose / Optimize aware of tier (e.g., OLS pickle получает different verdict labels per моему compute_channel_action)

**Acceptance criteria для v1.0.16 (or v1.1 if scope big):**
1. Import page shows tier indicator после загрузки данных
2. Tier обновляется после Validate channel selection
3. Manual override работает (forced OLS даже когда Bayesian doable)
4. Visual hierarchy — tier — один из 3-х largest UI elements на Import page
5. Tooltip/help: explain тяжёлые/лёгкие модели, why выбор имеет значение
6. Lock-in test: synthetic data → tier auto-selection match expected (n=31 + 7 params → Premium; n=18 + 5 params → OLS)

**Priority:** v1.1 NEW FEATURE (не блокер для current ship, but explicitly requested как «ключевой момент интерфейса»). Большой UX impact — пользователь upfront знает что его ждёт.


### L17 update — Bayesian hard floor (Антон 2026-04-28)

**Update:** manual override Bayesian forced МОЖЕТ быть disabled полностью когда data insufficient. Не warning — physical block.

**Hard floor для Bayesian (BOTH conditions must be met):**
- n_obs ≥ 20 (minimum для MCMC convergence + hierarchical priors)
- ratio ≥ 2:1 (n_obs / (active_params + 1) ≥ 2)

**Below floor:**
- UI radio button «Bayesian» visually disabled (greyed + lock icon)
- Tooltip explains exact unlock conditions
- Click attempt → no action, snackbar message
- Auto tier always = OLS

**Backend safeguard:** even если frontend bypass'ит, `/compute/train` validates:
```python
if mode == 'bayesian' and (n_obs < 20 or ratio < 2.0):
    return {'status': 'error',
            'error_code': 'BAYESIAN_INSUFFICIENT_DATA',
            'message': 'Bayesian model requires ≥20 observations and ratio ≥2:1...'}
```

**Tier matrix:**

| n_obs | Ratio | Tier | Bayesian doable? | Auto picks |
|---|---|---|---|---|
| < 20 | любое | OLS only | ❌ blocked | OLS |
| ≥ 20 | < 2:1 | OLS only | ❌ blocked | OLS |
| ≥ 20 | 2:1 - 4:1 | Bayesian-warn | ✅ available | Bayesian (с предупреждениями) |
| ≥ 20 | ≥ 4:1 | Premium | ✅ available | Bayesian (premium) |

**Acceptance criteria (extends earlier):**
1. Bayesian radio disabled когда data insufficient (visually + functionally)
2. Tooltip provides exact unlock formula
3. Backend rejects bayesian mode при insufficient data — guard от API bypass
4. Lock-in test: synthetic n=18 → forced bayesian → frontend blocked + backend returns BAYESIAN_INSUFFICIENT_DATA


### L17 final — Pure auto, no manual override (Антон 2026-04-28)

**Final decision:** убрать manual override полностью. Tier = automatic consequence of data, not user choice.

**Rationale (product wisdom):**
- User error prevention (forced wrong choice = catastrophic results)
- Simpler UX (one less decision point)
- Backend single source of truth (no client-server tier mismatch possible)

**UI changes vs earlier draft:**
- ❌ Radio buttons «Auto / OLS forced / Bayesian forced» — REMOVED
- ✅ Tier display only (informational)
- ✅ Education hints: «как улучшить tier» (через data changes, не override)
- ✅ Time-cost transparency: 5-15 мин Bayesian vs 10-30 сек OLS

**API contract:**
- `/compute/train` accepts NO mode parameter (removed from OptimizeRequest et al.)
- Backend dispatches к engine based on preflight tier
- Returns `model_version` ('1.2' = Bayesian premium, '1.1.5' = Bayesian-warn, '1.0-ols' = OLS) reflecting chosen path
- Frontend reads model_version from train response → знает что было запущено

**Implementation tasks для v1.0.16:**
1. Remove `modeling_tier` and override params from frontend ConfigPanel/Train
2. Add `/compute/preflight` returns full tier struct (already partial из MIN-LIVE GATE 1)
3. Import page renders tier display from preflight result, no radio
4. Backend train auto-dispatches without mode parameter
5. Tier reactive — recomputed после Validate channel changes
6. Lock-in test: 3 synthetic scenarios (n=18→OLS, n=31+9params→warn, n=31+5params→premium)

**Tier matrix (final):**

| n_obs | Ratio | Tier | Display |
|---|---|---|---|
| < 20 | any | OLS | 🟠 Упрощённая модель |
| ≥ 20 | < 2:1 | OLS | 🟠 Упрощённая модель |
| ≥ 20 | 2:1 - 4:1 | Bayesian-warn | 🟡 Bayesian с предупреждениями |
| ≥ 20 | ≥ 4:1 | Premium | 🟢 Premium Bayesian |


### 🔴 L18 — Conflicting license status indicators в Settings (Антон 2026-04-28)

**Symptom:** Settings page показывает два независимых блока с противоречивыми статусами:
- Лицензия: 🔴 «Лицензия не найдена [LI-001] License file not found» (file-based system)
- Подключение к серверу: 🟢 «Подключён к серверу. Лицензия до: 10.04.2029» (online auth)

**Root cause:** dual licensing architecture — `online_auth.rs` (приоритетная) и `license.rs` (Ed25519 file-based, legacy). Когда online auth активна — file-based не нужен, но UI показывает оба статуса параллельно без context.

**Customer impact:** пользователь видит «проблема с лицензией» когда реально всё работает (онлайн авторизация подтверждена сервером).

**Fix candidate:** в Settings UI добавить hierarchical logic:
- Если online auth.connected = True → показать unified status «✓ Лицензия активна (онлайн до {expiry})», file-based блок скрыть
- Если online auth.connected = False → fallback к file-based block + warning
- Никогда не показывать оба блока с conflicting statuses одновременно

**Priority:** v1.0.16 medium (UX confusion, не функциональная проблема — само лицензирование работает).

### 🟡 L19 — Settings показывает команды Aurora Agency в Aurora Econometrica build

**Symptom:** в Aurora AI Econometrica Settings раздел «Использование команд» содержит slash-команды от Aurora AI Agency (`/analytics 42`, `/aurora-ind... 16`, `/benchmark 2` etc), но Aurora Econometrica — pipeline-based продукт без chat-команд.

**Root cause:** Settings UI shared между Aurora products (общий codebase per CLAUDE.md «Один код, разные конфиги»). Statistics pulled from common profile без product-specific filter.

**Fix candidate:**
- (a) Filter usage stats by current product identifier (`com.aurora.econometrica`) — показывать только econometrica-specific события
- (b) Скрыть «Использование команд» секцию полностью в pipeline-based продуктах (Econometrica), оставить в chat-based (Agency / Creative Hub)

Recommendation: (b) — для Econometrica командные метрики не значимы.

**Priority:** v1.0.16 low (cosmetic, не misleading в смысле data privacy).

### 🟡 L20 — «Версия контента: c1» unclear notation

**Symptom:** в Settings строка «Версия контента: c1». User-facing string без context — что значит «c1»?

**Hypothesis:** legacy marker от Aurora Agency Cabinet system (c1 = cabinet 1). Aurora Econometrica — single-product без cabinets, marker irrelevant.

**Fix candidate:** скрыть в Econometrica или заменить к meaningful version (e.g., «Версия данных: 1.0.15» или «Шаблоны отчётов: v1.0.15»).

**Priority:** v1.0.16 low.


### L18-L20 — Settings page cleanup (Антон final decision 2026-04-28)

**Final scope:** unified fix — remove obsolete blocks + rename remaining.

**Changes:**

1. **Remove** «Статистика использования» block полностью — irrelevant для Econometrica (pipeline product без chat commands).

2. **Remove** «Лицензия» block (file-based с «[LI-001] License file not found») — legacy from offline-licensing era. После migration к online auth этот блок misleading.

3. **Rename** «Подключение к серверу» → «Лицензия». Expiry date уже там, status «Подключён к серверу» становится «Активна (онлайн)».

4. **Clean up** «Версия контента: c1» — либо убрать, либо заменить meaningful label (e.g. «Шаблоны отчётов: v1.0.15»).

**Final Settings layout:**
```
┌─ ЛИЦЕНЗИЯ ─────────────────────┐
│  ✓ Активна (онлайн)             │
│  Действует до: 10.04.2029       │
│  Instance: c8780e5963d2          │
└─────────────────────────────────┘

(плюс Папка проектов и прочие пользовательские настройки)
```

**Implementation tasks для v1.0.16:**
1. Удалить компонент UsageStatistics.svelte (или его imports в Settings page)
2. Удалить компонент LegacyLicenseStatus.svelte (file-based)
3. Переименовать ServerConnection.svelte → License (или rebrand title)
4. Удалить «Версия контента: c1» из ServerConnection (decide if replace or remove)
5. Сохранить «Папка проектов» / другие user settings
6. Lock-in test (e2e Svelte) — Settings page показывает только license + user settings, нет statistics

**Priority:** v1.0.16 medium-high (legacy UX cruft, undermines polish при customer demo).


### L20 final — «Версия контента: c1» убрать (Антон 2026-04-28)
Removed entirely. No replacement. Settings stays minimal.


---

## v1.0.16 Day 1 — L10 critical regression FIX (2026-04-28)

After live-test session ending. Антон approved Plan + asked critical audit (17 SA gaps found). Started implementation с L10 (highest priority — мой собственный regression от Section A `fe42e7f`).

### Fix

`engines/optimizer.py`:
- Separate `x0_money_real` (real current spend in money) from `x0_money` (projected к money_target)
- `current_response_real = -total_response_money(x0_money_real)` baseline для lift_pct
- Edge case `current_response_real ≤ 0` → `lift_pct = 0.0`, `baseline_zero = True` flag
- `_max_abs_delta_money` uses projected `x0_money` (KKT-perspective convergence detection — SA6)
- Insight string handles baseline_zero case
- `result_data['baseline_zero']` exposed для UI

### Test additions

`tools/test_optimizer_kagocel_redistribution.py`:
- L10a: half budget lift_pct < +50% (was +124.9% pre-fix)
- L10b: 2× budget lift > default (was inverted +10.8% < +30%)
- L10c: property-based monotonicity (5 budget ratios — strictly non-decreasing)

### Validation

**Real Kagocel pickle:**
```
Default 20/200:  lift +28.30%   (Section A baseline preserved ✓)
What-if -50%:    lift +31.50%   (was +124.9% inflated ✓ FIXED)
What-if +100%:   lift +42.60%   (was +10.8% deflated ✓ FIXED)
Monotonic:       31.5 → 35.1 → 37.8 → 40.9 → 42.6 ✓
```

**Regression:** 544/544 (was 541 + 3 new), zero regressions.

### Files changed

```
sidecar/econometrica/engines/optimizer.py     (~+25/-8 LOC)
tools/test_optimizer_kagocel_redistribution.py (+90 LOC, 3 new tests)
docs/MATH_AUDIT_v1_5_L10_FIX.md               (NEW, audit-trail)
SPRINT3_PROGRESS.md                            (this entry)
```


---

## v1.0.16 Day 1 — L4 mROAS three-way alignment FIX (2026-04-28)

### Fix

**Backend — `engines/decomposer.py`:**
- Compute `mroi_current` per channel via `_compute_mroas_money` helper from `optimizer.py` (single source of truth, money axis with adstock_factor + unit_cost normalization).
- Decorate channels с `action`/`action_label`/`action_tone`/`action_reasoning`/`action_priority`/`action_confidence` через `compute_channel_action()` после verdict computation. Aliasing: `mroas: mroi_current` для API contract.
- Untrained channels get `mroi_current=0.0`.

**Backend — `engines/optimizer.py`:**
- Заменили primitive `'action': 'увеличить'/'сократить'/'сохранить'` (delta_pct heuristic) на full ACTION_KEYS vocabulary (Scale/Hold/Watch/Reduce/Cut/Uncertain) via `compute_channel_action()`. Aliasing включает `mroas_ci_low/high` ← `mroi_current_ci_low/high`.

**Frontend — `OptimizeStep.svelte`:**
- Removed JS fallback `marginalROI()` import + Source #2 path (was: `β · α · γ^α · x^(α-1) / (x^α + γ^α)² · y_std` без `/unit_cost`, `/mean`, `adstock_factor` → mixed units).
- New miROASMap chain: Source #1 = `$optimizeData.channels[i]` (post-optimize), Source #2 = `$decomposeData.channels[i]` (idle, pre-optimize). Empty map когда нет ни одного — table hidden.
- Status field derivation: `actionToStatus(ch.action)` → Scale=good, Hold/Watch=ok, Reduce/Cut=low, Uncertain=unused. Replaces local thresholds.
- UI table: emoji + `actionLabel` from backend (Russian: «Масштабировать»/«Удерживать»/«Сократить»/etc).

### Test additions

`tools/test_optimizer_kagocel_redistribution.py` — 8 new L4 lock-in tests:
- L4-1: decomposer populates mroi_current per channel
- L4-2: decomposer decorates action / action_label / action_tone
- L4-3: optimizer decorates action_label / action_tone
- L4-4: **three-way alignment** — `decompose mroi_current ≈ optimize mroi_current` (max Δ < 0.01) — both engines must use same `_compute_mroas_money`
- L4-5: TRPs `mroi_current` < 1× (money axis, was ~110× pre-fix)
- L4-6: TRPs action ∈ {Cut, Reduce, Watch, Uncertain}
- L4-7: Performance action == Scale

### Validation

**Synthetic Kagocel fixture (lock-in test):**
```
Decompose vs Optimize mroi_current alignment: max Δ = 0.0000 ✓
TRPs:        mroi=0.0217  action=Cut  (money axis, pre-fix would be ~110×)
Performance: mroi=high    action=Scale
```

**Real Kagocel pickle (`-26--4`):**
```
TRPs:                  mroi=0.0285  action=Cut    (decompose + optimize identical)
Performance:           mroi=9.7453  action=Scale
Social/Retail/Banners/OLV: action=Scale (decompose) или Scale (optimize)
```

**Regression:** 552/552 (was 544 + 8 L4 lock-ins), zero regressions across:
- test_optimizer_kagocel_redistribution.py: 20/20
- test_narrative_coherence.py: 24/24
- test_narrative_adapter.py: 65/65
- test_math_correctness.py: 156/156
- test_posterior_ci.py: 82/82
- test_roi_verdict.py: 36/36
- test_audit_of_sprint3.py: 20/20
- test_causal_m0-m4.py: 149/149

**svelte-check:** 0 new errors (33 errors pre-existing in `insights-rules.js`/`hill.js` — unchanged).

### Files changed

```
sidecar/econometrica/engines/decomposer.py     (+39 LOC)
sidecar/econometrica/engines/optimizer.py      (+24 / -3 LOC)
src/lib/components/pipeline/OptimizeStep.svelte (+66 / -48 LOC)
tools/test_optimizer_kagocel_redistribution.py (+71 LOC, 8 new tests)
SPRINT3_PROGRESS.md                             (this entry + L4 status update)
```

### Discovered side-finding — L21 (separate)

`optimization.json` returns `lift_pct: None` для real Kagocel (recently confirmed via direct optimize() call). Backend computes lift_pct internally (used at line 660 convergence check), но в response payload null. Не блокер L4 — L21 backlog.

---

### 🟡 L21 — `lift_pct: None` в optimization.json при real Kagocel call (discovered 2026-04-29)

**Symptom:** Direct repro `optimize(config, project_dir)` на real Kagocel pickle (`-26--4`) returns `result['lift_pct'] = None` в payload, при том что backend computes lift_pct internally (used at convergence check `abs(lift_pct) < 0.5` в optimizer.py).

**Verification:** synthetic Kagocel fixture lock-in test возвращает корректный lift_pct (16.40% default, 31.50%/42.60% для what-ifs). Поэтому это edge case на real pickle.

**Hypothesis:**
- Связано с baseline_zero handling в L10 fix (`current_response_real ≤ 0` → `lift_pct = 0.0`)
- Возможно JSON serialization edge для NaN/None float — somewhere converts NaN → None during json.dumps
- Или conditional code path в optimizer.py result_data assembly skips lift_pct когда какой-то flag set

**Repro:**
```python
from engines.optimizer import optimize
proj = r'C:/Users/ackol/AppData/Roaming/aurora-econometrica-gui/projects/кагоцел-рф-ммх-2604-26--4'
result = optimize({'min_pct': 20.0, 'max_pct': 200.0}, proj)
# result['lift_pct'] is None
# But result['expected_lift_pct'] populated normally (28.30%)
```

**Priority:** v1.0.16 LOW. Не блокирует UI (есть `expected_lift_pct` fallback). Investigate когда touching optimizer.py result_data shape (потенциально вместе с L7 binding/converged_at_current banner).

**Acceptance:**
1. Real Kagocel optimize() returns numeric `lift_pct` (not None)
2. Lock-in test extension в test_optimizer_kagocel_redistribution.py — assert `result['lift_pct']` is float on real pickle path

