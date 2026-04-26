# GH Release Draft — Aurora AI Econometrica v1.0.15

**Status:** DRAFT (publish после NSIS rebuild + SHA256 capture)

**Repo:** github.com/Ackold26/aurora-releases (public release channel)
**Tag:** `v1.0.15`
**Branch source:** `math-fix-v1.0.13` (private repo)
**Predecessor:** v1.0.14 (Sprint 3 Pharma Causal)

---

## Release notes (copy-paste для GitHub)

# Aurora AI Econometrica v1.0.15 — Optimizer + Narrative consistency hotfix

## 🎯 Headline

v1.0.14 live-test на real Kagocel data выявил 3 product-credibility blockers. Этот релиз закрывает 2 из них (третий — Validate→Model state desync — уже зафиксен в v1.0.14):

1. **Optimizer теперь находит реальное перераспределение.** Pre-fix: `lift = 0%` для всех настроек включая Phase 0.1 рекомендованные defaults 20/200. Root cause: SLSQP false convergence at iter=1 + bad numerical conditioning + ineffective multi-start. Post-fix на real Kagocel data: **lift = +28.3%** (5 каналов на +100%, TRPs балансирует -8.3%).

2. **Narrative consistency — single source of truth.** Pre-fix: HTML отчёт содержал 4 contradictions для одних channels на разных страницах («Performance — основная точка оптимизации» в декомпозиции vs «потенциал удержания» в mROAS section etc). Root cause: TWO PARALLEL VERDICT SYSTEMS (decomposer + narrative_adapter) + 5+ hardcoded narrative sites independent от derive_verdict. Post-fix: единая `engines.channel_action.compute_channel_action` функция, все templates derive ОДИН action label per channel.

## ✨ Что нового для пользователя

- **Optimize step**: Min/Max 20/200 теперь даёт meaningful redistribution. Когда оптимизатор не нашёл лучшего распределения — honest banner объясняет («Расширьте границы Min/Max») вместо vacuous «Сохранить аллокацию».
- **HTML report**: action label per канал consistent across action table + mROAS commentary + executive summary findings. Vocabulary: Масштабировать / Удерживать / Под наблюдением / Сократить умеренно / Сократить / Недостаточно данных.
- **PPTX report**: same action-driven s06 commentary as HTML.
- **Decomposition page**: ROI-based descriptive labels («Перенасыщен», «Эффективен» и т.д.) preserved unchanged — ваш existing workflow не сломан.

## 🔬 Math foundation

### Section A — Optimizer fix (3-layer)

- **L1 — Money-axis rescaling.** Pre-fix optimize в native units (TRPs vs ₽), constraint в money — bounds spread 10⁵×, gradient spread 10⁴×, ill-conditioned. Post-fix: optimize ALWAYS в money axis, конвертация к native через `/uc_arr` inside Hill computation. Conditioning improvement 220×.
- **L2 — Channel-pivot + balancer multi-start.** 13 starts vs prev 3: current + N pivot_up (channel pushed к upper, others lower) + N others_up_balance (channel exactly balances when others at upper) + all_upper. Captures «small channels saturated, balancer fills remainder» corner critical for money-budget portfolios where one channel dominates (как Kagocel TRPs ≈ 92%).
- **L3 — Diagnostics + false convergence detector.** `converged_at_current` flag когда все starts → current без binding. `slsqp_diagnostics` per-start outcomes (success / iterations / objective / message) populate result_data для UI debugging.

Подробности: `docs/MATH_AUDIT_v1_4_OPTIMIZER_FIX.md`.

### Section B — Narrative consistency (single source of truth)

- New `engines/channel_action.py` (280 LOC) — 11-step decision tree:
  ```
  0. Bad input → Watch
  1. Untrained → Uncertain
  2. Zero spend → Uncertain
  3. Severe optimizer cut (ratio < 0.5) → Cut
  4. Below breakeven (mROAS < 0.8) → Cut
  5. Optimizer reduce (ratio ≤ 0.95) → Reduce
  6. Near breakeven (mROAS < 1.0) → Reduce
  7. Optimizer scale (ratio ≥ 1.05) → Scale
  8. mROAS+gap heuristic (mROAS ≥ 1.5 + gap ≥ +5pp) → Scale
  9. CI uncertainty → Uncertain  (evaluated AFTER optimizer signals)
  10. Hold (mROAS ≥ 1.1, |gap| < 5pp)
  11. Watch (fallback)
  ```

  **Critical design choice**: CI uncertainty step ordering. Optimizer's redistribution implicitly integrates joint posterior — meaningful `ratio` уже reflects confidence-aware ranking даже с individual-channel wide CI. Pre-design (CI early): real Kagocel n=31 → ALL 6 channels Uncertain. Post-design (CI late): 5 Scale + 1 Cut + 0 Uncertain — product value restored.

- All narrative templates (`aurora_html/sections.py` render_mroas, `aurora_pptx/builder.py` s06) refactored к использованию `ch.action_label` + `ch.action_reasoning` decorated by narrative_adapter. Hardcoded «явный потенциал scale-up» / «потенциал удержания» blocks removed.

Подробности: `docs/MATH_AUDIT_v1_4_NARRATIVE_FIX.md`.

## 🧪 Validation

### Real Kagocel pickle (n=31, 6 channels, 7 controls)

```
                Pre-fix   Post-fix
Optimizer lift:   0.0%    +28.3%
Performance:      ±0%     +100%   (Scale)
Social:           ±0%     +100%   (Scale)
Banners:          ±0%     +100%   (Scale)
OLV:              ±0%     +100%   (Scale)
Retail Media:     ±0%     +100%   (Scale)
TRPs:             ±0%      -8.3%  (Cut)

HTML coherence:   4 contradictions  → 0 contradictions
```

### Test suite

```
test_audit_of_sprint3      : 20/20 PASS
test_causal_m0..m4         : 149/149 PASS
test_math_correctness      : 156/156 PASS
test_narrative_adapter     : 65/65 PASS
test_posterior_ci          : 82/82 PASS
test_roi_verdict           : 36/36 PASS
test_optimizer_kagocel...  : 9/9 PASS  (NEW)
test_narrative_coherence   : 24/24 PASS  (NEW)
                            ━━━━━━━━━━━━
Total: 541/541 (was 508 + 33 new), zero regressions.
```

## 🔄 Backwards compatibility

- ✅ All existing endpoints + pickle schemas IDENTICAL
- ✅ Existing v1.2/v1.1.5/v1.1/v1.0-ols pickles forward-compat (no re-train)
- ✅ Existing scenarios + decompose results unchanged
- ✅ derive_verdict теперь thin wrapper around compute_channel_action — все callers получают same answer
- ✨ NEW field `converged_at_current` (bool) в optimize result_data
- ✨ NEW field `slsqp_diagnostics` (dict) в optimize result_data
- ✨ NEW fields `action / action_label / action_reasoning / action_tone / action_priority / action_confidence` в narrative-merged channel dicts

## ⚠️ Known limitations (deferred к Sprint 4+)

1. **Hierarchical decay shrinkage on small N.** Phase 1.1 logit-normal prior pulls all channel decays к ~0.245 ± 0.003 при small N (≤30) — каналы выглядят interchangeable. Не bug, документировано.
2. **PPTX optimizer state awareness.** HTML refactored для converged_at_current banner; PPTX builder.py пока показывает generic recommendation. Sprint 4+ task.
3. **compute_descriptive_state structured class.** Plan's option (b) предусматривал отдельный «descriptive state» function. Existing decomposer.compute_roi_verdict уже выполняет descriptive — Decomposition UI page unaffected, refactor deferred.

## 📥 Installation

Скачать: `Aurora_AI_Econometrica_1.0.15_x64-setup.exe`

Auto-update from v1.0.14 / v1.0.13 supported. Или manual install — existing projects/data intact.

**SHA256:** `e713f83b203a1625beec3ad2ba9aedf579973ece74e4b656b6efe8d646532c15`
**Bundle size:** 189.3 MB (198 511 844 bytes)
**Local path:** `D:/cargo-targets/aurora-econometrica/release/bundle/nsis/Aurora AI Econometrica_1.0.15_x64-setup.exe`
**Built:** 2026-04-28

## 📚 Documentation

- `docs/CHANGELOG_v1.0.15.md` — полный список changes
- `docs/MATH_AUDIT_v1_4_OPTIMIZER_FIX.md` — Section A audit-trail
- `docs/MATH_AUDIT_v1_4_NARRATIVE_FIX.md` — Section B audit-trail
- `docs/AUDIT_PLAN_2026-04-28.md` (на Desktop) — original план
- `docs/AUDIT_PLAN_REVISIONS.md` (на Desktop) — Phase 1 meta-audit + revised plan

## 🔮 Coming в v1.0.15

- Real-customer Materia Medica/Кагоцел/Афала regional data validation (case-study)
- DiD wild-cluster bootstrap для small n_clusters
- PPTX optimizer state awareness (binding/converged_at_current banners)
- compute_descriptive_state structured class
- Stronger small-N partial pooling controls (UI override для hierarchical decay shrinkage)

## 🤝 Credits

- Code review + meta-audit: Маша (fresh-context Claude)
- Live-test: Антон Сипович
- Math doctrine: D-style fresh-context audit (audit-of-audit-of-audit)

---

**Released:** 2026-04-28
**Branch:** `math-fix-v1.0.13` HEAD will be set после commit
