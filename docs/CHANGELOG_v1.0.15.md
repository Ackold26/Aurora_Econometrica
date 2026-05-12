# Aurora AI Econometrica v1.0.15 - Optimizer + Narrative consistency hotfix

**Date:** 2026-04-28
**Branch:** `math-fix-v1.0.13` → tag `v1.0.15`
**Predecessor:** v1.0.14 (Sprint 3 Pharma Causal + math audit hardening)

---

## 🎯 Customer-facing fixes

v1.0.14 NSIS installer (189MB, SHA256 `31822fae...110c51`) был установлен на боевой машине пользователя для live-test на real Kagocel data. Тест выявил **3 product-credibility blockers**, два из которых v1.0.15 закрывает (третий - Validate→Model state desync - был зафиксен в v1.0.14 commit `0eeb715` уже).

### 1. Optimizer теперь находит реальное перераспределение

**Pre-fix:** Optimizer на defaults Min/Max 20/200 (Phase 0.1 рекомендованные) возвращал **lift = 0.0%** для всех настроек - silent false convergence.

**Post-fix:** Real Kagocel pickle через optimizer outputs **lift = +28.3%** с meaningful redistribution (5 каналов на +100%, TRPs -8.30%).

**Root cause** (math-audit v1.4):
- **Bad numerical conditioning.** SLSQP оптимизировал в native units (TRPs vs ₽ - bounds spread 10⁵×, gradient spread 10⁴×). При current allocation success=True at iter=1 - false convergence.
- **Ineffective multi-start.** Phase 0.1 hotfix #19 (random uniform + scale + clip) collapsed perturbations к neighborhood of current - SLSQP стартовал close к existing local trap.

**Fix** - 3-layer:
- **L1 - Money-axis rescaling.** Optimizer теперь работает в money axis, конвертирует к native через `/uc_arr` inside Hill computation. Bounds + constraint оба uniform money scale → conditioning improvement 220× (was 48 461×).
- **L2 - Channel-pivot + balancer multi-start.** 13 starts: current + N pivot_up (each channel pushed к upper bound, others к lower) + N others_up_balance (each channel exactly balances when all others at upper) + all_upper. Captures «small channels saturated, balancer fills remainder» corner - оптимальная shape для money-constrained portfolios where one large channel dominates budget (как Kagocel TRPs ≈ 92% bud).
- **L3 - Diagnostics + false convergence detector.** `converged_at_current` flag + `slsqp_diagnostics` (per-start outcomes) populate result_data. UI surfaces honest banner вместо vacuous «Сохранить аллокацию».

Подробности: `docs/MATH_AUDIT_v1_4_OPTIMIZER_FIX.md`.

### 2. Narrative consistency - single source of truth

**Pre-fix:** HTML отчёт показывал 4 contradictions для одних и тех же channels на разных страницах:
- «Performance - основная точка оптимизации» (Декомпозиция) vs «потенциал удержания» (mROAS)
- «Social - явный потенциал scale-up» (commentary) vs «HOLD» verdict (table)
- «Топ-2 канала портфеля» referent unclear
- ROI/mROAS определения technically inaccurate

**Post-fix:** Все verdicts + commentary derive ONE action label per channel, shown identically across HTML table + commentary + findings.

**Root cause:** TWO PARALLEL VERDICT SYSTEMS:
- `decomposer.compute_roi_verdict` (16 ROI-based labels)
- `narrative_adapter.derive_verdict` (5 mROAS+ratio labels)
- Plus 5+ hardcoded narrative sites generating commentary independently от derive_verdict (sections.py:526-541, builder.py:1395-1430)

**Fix** - `engines/channel_action.py` (NEW, 280 LOC) - single function `compute_channel_action(channel)` с 11-step decision tree. All narrative sites refactored к использованию `ch.action_label` + `ch.action_reasoning` decorated by narrative_adapter.

**Vocabulary** (5 backward compat + 1 new):
- `Scale` - Масштабировать
- `Hold` - Удерживать
- `Watch` - Под наблюдением
- `Reduce` - Сократить умеренно
- `Cut` - Сократить
- `Uncertain` - Недостаточно данных (NEW)

**Critical design choice - CI uncertainty step ordering.** Optimizer's redistribution implicitly integrates joint posterior (mROAS samples per channel), so meaningful `ratio` (≥1.05 OR ≤0.95) reflects already-confidence-aware ranking даже с individual-channel wide CI. Только когда optimizer не двигает + CI wide → Uncertain. Это restores product value на small-N data (Kagocel n=31): post-fix 5 Scale + 1 Cut + 0 Uncertain.

Подробности: `docs/MATH_AUDIT_v1_4_NARRATIVE_FIX.md`.

### 3. Honest «converged at current» banner

Когда optimizer возвращает current allocation без binding constraints (false convergence at boundary) - UI banner объясняет:
> «Оптимизатор сошёлся на текущем распределении - лучшее решение при заданных границах не найдено. Это может означать что границы Min/Max задают слишком узкий коридор либо текущая аллокация уже близка к локальному оптимуму. Расширьте границы (10/300% рекомендуется) или используйте экспертный режим.»

Замещает vacuous «Сохранить аллокацию» который маскировал the issue.

---

## 🧪 Validation

### Real Kagocel pickle (production validation)

```
v1.0.14: lift=0%, table verdicts/commentary contradictions
v1.0.15:
  Optimizer:
    lift = +28.3%
    converged = True
    converged_at_current = False
    n_starts = 9, n_converged = 9

  Per-channel actions (HTML table + commentary identical):
    Performance  | mROAS=9.83  | Δ +100%  | Scale
    Social       | mROAS=10.49 | Δ +100%  | Scale
    Banners      | mROAS=1.08  | Δ +100%  | Scale
    OLV          | mROAS=1.04  | Δ +100%  | Scale
    Retail Media | mROAS=7.41  | Δ +100%  | Scale
    TRPs         | mROAS=0.03  | Δ -8.3%  | Cut
```

Antón's product mandate «понять что изменить» - restored.

### Test suite

```
test_audit_of_sprint3      : 20/20 PASS
test_causal_m0..m4         : 149/149 PASS
test_math_correctness      : 156/156 PASS
test_narrative_adapter     : 65/65 PASS
test_posterior_ci          : 82/82 PASS
test_roi_verdict           : 36/36 PASS
test_optimizer_kagocel...  : 9/9 PASS  (NEW lock-in for Optimizer fix)
test_narrative_coherence   : 24/24 PASS  (NEW lock-in for Narrative fix)
                            ━━━━━━━━━━━━
Total: 541/541 (was 508 v1.0.14, +33 new)
```

---

## ⚠️ Known limitations (deferred к Sprint 4+)

1. **Hierarchical decay shrinkage on small N.** Phase 1.1 logit-normal prior pulls all channel decays к ~0.245 ± 0.003 при small N (≤30) - каналы выглядят interchangeable. Не bug, документировано.

2. **PPTX optimizer state awareness.** HTML refactored для converged_at_current banner; PPTX builder.py пока показывает generic recommendation. Sprint 4+ task.

3. **compute_descriptive_state structured class.** Plan's option (b) предусматривал отдельный «descriptive state» function рядом с prescriptive action. Existing decomposer.compute_roi_verdict уже выполняет descriptive - Decomposition UI page unaffected, refactor deferred.

---

## 📦 Files changed (since v1.0.14)

```
sidecar/econometrica/engines/optimizer.py          (Section A - money-axis + multi-start, ~+185/-100)
sidecar/econometrica/engines/channel_action.py     (NEW Section B - single source of truth, 280 LOC)
sidecar/econometrica/engines/narrative_adapter.py  (Section B - derive_verdict migration)
sidecar/econometrica/aurora_html/sections.py       (Section B - render_mroas + banners)
sidecar/econometrica/aurora_pptx/builder.py        (Section B - s06 commentary)
tools/test_optimizer_kagocel_redistribution.py     (NEW Section A - 9 lock-in tests)
tools/test_narrative_coherence.py                  (NEW Section B - 24 lock-in tests)
docs/MATH_AUDIT_v1_4_OPTIMIZER_FIX.md              (NEW Section A audit-trail)
docs/MATH_AUDIT_v1_4_NARRATIVE_FIX.md              (NEW Section B audit-trail)
package.json + Cargo.toml + tauri.conf.json        (1.0.14 → 1.0.15)
SPRINT3_PROGRESS.md                                 (session log)
```

---

## 🚀 Upgrade path

- **In-app auto-update**: open Aurora Econometrica, prompted к v1.0.15.
- **Manual download**: GitHub Release v1.0.15 (link в Settings → About).
- **No data migration required.** Existing pickles (v1.2 schema) continue working без re-train.

---

**Маша, 2026-04-28**
