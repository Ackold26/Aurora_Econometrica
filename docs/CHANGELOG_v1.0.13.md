# Aurora AI Econometrica v1.0.13 — Math Audit Release

**Date:** 2026-04-25
**Branch:** `math-fix-v1.0.13` → `master`
**Tag:** `v1.0.13-math-audited`

## ⚠️ BREAKING CHANGES (read before deploy)

### Pickle compatibility (P0-1/2/9)

Models trained on v1.0.12 and earlier (`model_version='1.0'` or absent) are **REJECTED** by all engines (modeler / decomposer / optimizer / scenario). Old pickles cannot be reused — they used z-score normalization which was methodologically broken.

**Error code returned:** `MODEL_OUTDATED`
**Error message:** "Модель обучена до v1.0.13. Нормализация изменилась — переобучите модель в кабинете 'Модель'."

**Migration path:**
1. After update, user reopens existing project
2. Decompose / Optimize / Scenario step shows MODEL_OUTDATED error
3. User clicks "Переобучить" в кабинете "Модель"
4. New pickle saved with `model_version='1.1'`, all subsequent steps work

**Old scenario JSON files** in `results/scenarios/` are migrated on-the-fly by `compare_scenarios()` — display works but ROAS marked `roas_method='total'` (legacy semantic). New scenarios use `roas_method='incremental'` (industry standard).

---

## 🟢 Closed defects

### P0 (correctness-breaking) — 11 closed

- **P0-1** Hill normalization: z-score → `spend / mean` (Robyn-style) — `modeler.py:249-251`
- **P0-2** Negative-z silent data drop — auto-resolved (clip never fires post-fix)
- **P0-3** Decomposer `|β|/Σ|β|` proportional → proper `β × hill(adstock(x)/mean) × y_std` per period — `decomposer.py`
- **P0-4** Decomposer baseline magic-0.3 → `intercept_mean × y_std + y_mean + control_effects × y_std` — `decomposer.py`
- **P0-5/6** Optimizer `raw_spend + γ × current_spend` → `spend/mean + raw γ` matching training — `optimizer.py`
- **P0-7** Reconstruction `gamma × max(x)` → raw gamma matching training — `modeler.py:537`
- **P0-9** 4-way Hill drift (training/reconstruction/optimizer/JS) → unified to spend/mean + raw γ
- **P0-10** Per-period contribution proportional to raw spend → saturated per-period contribution — `decomposer.py`
- **P0-11** Mixed-units optimizer constraint → `MIXED_UNITS` error guard — `optimizer.py`

### P1 (methodology) — 3 closed (Phase 6)

- **P1-3** Scenario baseline = intercept-based (was `y_mean × n`)
- **P1-4** Scenario ROAS = incremental (was total — overstated by 5×+)
- **P1-5** Scenario applies adstock to spend timeline (was missing carryover)

### P1 (methodology) — 3 deferred to v1.1

- P1-1 Adstock parameters jointly estimated by MCMC (large refactor)
- P1-2 Validator UX for mixed-units
- P1-6 MQS weights uncalibrated

### P2 (doc debt) — 5 deferred

R² clamping, MQS weights rationale, MAPE→score mapping, VIF validator, adstock selector hyperparam search.

---

## 📦 Pickle schema v1.1

Added fields:
- `model_version: '1.1'` (compat detection)
- `normalization.intercept_mean` (for decomposer + scenario baseline)
- `normalization.control_betas_mean` (for decomposer baseline + control effect)

Removed fields:
- `normalization.media_stds` (not used in spend/mean normalization)

Engines that read pickle and check version:
- `engines/modeler.py` (writes new format)
- `engines/decomposer.py`
- `engines/optimizer.py`
- `engines/scenario.py`

---

## 🆕 New result fields (scenario)

`predict_scenario()` returns:
- `totals.incremental_kpi` — primary scenario delta (= predicted - baseline)
- `totals.roas` — incremental ROAS (PRIMARY, was total/spend)
- `totals.roas_money` — incremental money ROAS
- `totals.roas_total` — legacy total/spend (back-compat)
- `totals.roas_money_total` — legacy total/money
- `totals.roas_method='incremental'` — semantic marker
- `model_version` — for UI badge

`compare_scenarios()`:
- Old scenarios get `roas_method='total'` flag during migration
- UI can disambiguate old vs new ROAS semantics

---

## 🧪 Test coverage

`tools/test_math_correctness.py` — **95/95 PASS** post-fix
`tools/test_narrative_adapter.py` — 65/65 PASS (output quality, unchanged)

Test categories:
1. Hill saturation (bounds, monotonicity, stability) — 8 tests
2. Adstock (geometric, Weibull, dispatch) — 7 tests
3. y normalization roundtrip — 6 tests
4. Diagnostics (R², MAPE, RMSE) — 5 tests
5. Marginal ROI = analytical derivative — 5 tests
6. P0-7 fixed: training-vs-reconstruction parity — 2 tests
7. P0-5/6 fixed: optimizer-vs-training parity — 1 test
8. Robyn-style Hill positive domain — 3 tests
9. MQS bounds + thinness cap — 5 tests
10. JS↔Python Hill parity — 4 tests
11. Prior predictive (numpy) — 9 tests
12. Decomposer post-fix — 6 tests
12b. Phase 5 ship gate — 8 tests
13. Validator column role — 5 tests
14. Phase 6: scenario adstock + incremental ROAS — 14 tests

**Pre-fix bug-signature regression detectors** (P0-2/5/6/7) inverted to parity assertions — explicit migration tripwires that confirm fixes landed.

---

## 🚀 Ship gate (live-test pending)

Before `v1.0.13-math-audited` declared shipped:

- [x] All P0 closed via Phase 1-4 commits
- [x] All P1-3/4/5 closed via Phase 6
- [x] 95/95 math + 65/65 narrative_adapter tests PASS
- [ ] **Live Kagocel test** (PENDING):
  - `python sidecar/build_sidecar.py` rebuild
  - `npm run tauri dev`
  - Import Kagocel XLSX → train → decompose → optimize → scenario → export
  - Verify response curves show curvature, scenario ±50% delta KPI ≥ 5%, optimizer non-trivial allocation, what-if matches scenario backend
- [ ] **PASHE_IT.MD update** (PENDING) — add v1.0.13 breaking-change section to client IT doc

---

## 📁 Audit artifacts (preserved)

- `docs/MATH_AUDIT_v1_1.md` — full inventory + findings (575 lines)
- `docs/MATH_AUDIT_HILL_FIX_COORDINATION.md` — fix sequencing + acceptance criteria
- `docs/MATH_AUDIT_EXEC_SUMMARY.md` — 1-pager
- `docs/MATH_FIX_PLAN.md` — 7-phase execution plan
- `docs/CHANGELOG_v1.0.13.md` — this file
- `tools/test_math_correctness.py` — 95-assertion regression suite

## Git history

```
v1.0.12-pre-fix-bundle  d45d4d6  Safety anchor before any fix
v1.0.12-math-audit-done 1182338  Audit R5 complete
v1.0.13-rc1-phase1      b6f6400  P0-7 reconstruction fix
v1.0.13-rc2-phase2      c065868  P0-1/2/9 Hill normalization
v1.0.13-rc3-phase3      89fb9cd  P0-3/4/10 decomposer rewrite
v1.0.13-rc4-phase4      7daa7c4  P0-5/6/11 optimizer rescale
v1.0.13-rc5-phase5      2ed4d1f  Phase 5 ship gate validation
v1.0.13-rc6-phase6      13a0d9c  P1-3/4/5 scenario adstock + incremental ROAS
v1.0.13-math-audited    HEAD     Final ship after live-test PASS
```
