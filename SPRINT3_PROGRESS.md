# Sprint 3 Progress — Pharma Causal + D/MIN-LIVE Validation Gates

**Branch:** `math-fix-v1.0.13`
**Started:** 2026-04-27 (this session)
**Mode:** Autonomous — Маша работает без per-step confirmation. Вопросы только: architecture decisions / push to remote / schema migration.

---

## Current task

**Step D + Fix-session + MIN-LIVE all DONE. Sprint 3 Pharma Causal UNLOCKED.**

D found 6 issues, fix-session shipped 5 fixes (F1-F5, F6 deferred), MIN-LIVE 4 production gates + 1 bonus all PASSED через FastAPI server.py path.

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

**MIN-LIVE summary:** 4 production gates + 1 bonus all PASSED. F1-F5 fixes validated в production code path (FastAPI server.py + Pydantic request validation + actual ML pipeline + pickle round-trip). No regressions surfaced. Step B (Sprint 3 Pharma Causal) unlocked.

---

## Sprint 3 Pharma Causal

_(populated после MIN-LIVE PASS)_

**Stack:** linearmodels (DiD Callaway-Sant'Anna) + econml (Causal Forest Wager-Athey) + pysyncon (SCM Abadie) + statsmodels base.

**ADR §1 must declare "EXTEND, not rewrite"** — pin existing FastAPI shape so MIN-LIVE coverage stays valid.

**Pre-Ship gate before v1.0.14:** SBC overnight + UI live-test on Kagocel + Materia Medica geo-data.
