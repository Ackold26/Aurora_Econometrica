---
tags: [session, compressed, audit, optimizer, scenario, decomposer]
type: session
updated: 2026-05-03
---

# Quick Reference

Single-day MAX session: closed all **5 etaps of optimizer-audit follow-up plan** (`~/.claude/plans/zazzy-tumbling-kettle.md` + `~/Desktop/optimizer-audit-followup-plan.md`). Replaced reactive «fix-when-customer-screams» (passes 6-18 на одном Кагоцеле) с proactive property-based verification across 3 engines.

**Topic:** audit-followup-complete-5-etaps
**Key files:**
- `tools/test_optimizer_invariants.py` (152 tests, I1-I8)
- `tools/test_scenario_invariants.py` (131 tests, S1-S14)
- `tools/test_decomposer_invariants.py` (114 tests, D1-D13)
- `tools/test_optimizer_real_pickle.py` (4 tests on Кагоцел xlsx)
- `tools/test_forecast_validation_hierarchical.py` (21 tests, helper)
- `sidecar/econometrica/utils/forecast_validation.py` (+`hierarchical_extrapolation_warning`)
- `sidecar/econometrica/engines/optimizer.py` (+F1 cumulative anchor + 5 error_codes)
- `sidecar/econometrica/engines/decomposer.py` (untrained detection + verdict preservation)
- `sidecar/econometrica/engines/scenario.py` (logger.warning + error_codes)
- `src-tauri/src/commands/econometrica.rs` (+prev_optimal arg)
- `src/lib/components/pipeline/OptimizeStep.svelte` (lastOptimalMoneyByChannel state)
- `docs/OPTIMIZER_INVARIANTS_REGISTRY.md`, `SCENARIO_INVARIANTS_REGISTRY.md`, `DECOMPOSER_INVARIANTS_REGISTRY.md`, `OPTIMIZER_ERROR_PATH_AUDIT.md`, `OPTIMIZER_SMOKE_MATRIX.md`, `SCENARIO_DECOMPOSER_AUDIT_OUTCOME.md`, `MATH_AUDIT_v2_PART2_OUTCOME.md`

**Status:**
- ✅ All 5 etaps done. **820 tests pass + 5 skipped в 21s parallel** (was ~150 pre-audit). 0 svelte errors. cargo clean.
- ✅ Branch `math-fix-v1.0.13` HEAD `d7ac143` pushed. 3 tags: `v1.0.13-optimizer-audit`, `v1.0.13-engine-audit-complete`, `v1.0.13-audit-followup-complete`.
- ⏳ Pending: v1.2.0 NSIS build/release, UI panel для hierarchical warning (1-2h Tauri+Svelte), Phase 2.6 reports.

---

## Learnings

### Audit methodology pattern (reusable для следующих движков/проектов)

Замена reactive workflow:
1. **Phase 1 — Math invariants:** derive formal mathematical laws engine must obey, write property-based tests с pytest.parametrize on random seeds. ~150 tests per engine.
2. **Phase 2 — Edge case matrix:** systematic batches (forecast validation, channel counts, unit-smell, What-if extremes, untrained mix, awareness caps, UnboundLocalError prevention, inflation edges, etc). ~30-50 tests per engine.
3. **Phase 3 — Error path scan:** AST walker + manual review — find missing error_codes, silent except blocks, unguarded divisions, sentinel access. Inline fixes for HIGH severity.
4. **Phase 4 — Smoke matrix:** ~12 representative production configs E2E. Cross-engine verification.
5. **Phase 5 — Docs + maintenance:** formal invariant registry per engine + audit outcome doc + inline `# invariant: I*` annotations.

**Key insight:** AST conditional-binding analysis в function-scope often gives many false positives (block-scope vs function-scope mismatch). Manual filter required to surface real UnboundLocalError risks.

### F1 cumulative anchor seeding (transitive chain monotonicity)

Pre-fix: optimizer's default_anchor mechanism floors result vs default(20/200) only. Customer widening sliders (e.g. 50/150 → 30/200 → 0/500) videl non-monotonic lift_pct sequence.

Fix: backend accepts optional `prev_optimal: list[float]`, adds it as direct candidate (no SLSQP rerun, just objective eval). UI plumbing — Svelte stores `result.optimal_spend_money`, passes на следующий optimize call. Backend silently skips если infeasible в новых bounds.

Math: `min(candidates).fun` selection guarantees current run ≥ prev. Floor preserved transitively across chain.

### Decomposer untrained-channel double bug

Bug 1: Decomposer checked only `params.get('untrained')` (OLS-engine pattern), miss'ал `normalization.untrained_channels` list (Bayesian-engine pattern). Bayesian-trained pickles с zero-variance channels gave **spurious non-zero contributions** (channel processed normally → mean fallback к 1.0 → spurious Hill saturation).

Bug 2: Untrained ch_dict_untr set verdict='Не обучен' initially, **overwritten** by downstream `compute_roi_verdict` loop (roi=0 < 0.5 threshold → 'Глубоко убыточный'). Customer saw misleading «deep loss» label на каналах без training data.

Fix: extended `params.get('untrained') OR col in untrained_channels` guard + skip downstream verdict + action loops для `ch.get('untrained')`.

### Hierarchical L5 — synthetic experiment finding

Proportional pool shrinkage (50% pull для всех brand channels) **сохраняет channel rankings** → optimizer allocations identical между flat и hierarchical (cosine_sim=1.0 для всех ratios 1×-5×). Optimizer cares about β **ratios**, not absolutes.

**Real risk** = decompose ROI attribution underestimation. Top-performer brand channel β shrunk на ~21% при 50% pool → customer reads underestimated ROI и interprets «канал не работает» когда actually statistical artifact.

Threshold 3× для brand budget ratio matches Aurora's M8 saturation drift convention. Single threshold для spend-zone-warning AND hierarchical-pooling-warning preserves customer mental model.

### γ-recalibration → OBSOLETE

Phase 2 audit pass 2 (S3 synergy, 2026-05-02) уже заменила γ-based CI inflation на tier-based `extrapolation_severity` (0/1/2/3) integrated в `verdict_tier`. The `inflate_extrapolation_uncertainty(γ=0.3)` helper **никогда не shipped** в код. Single vocabulary preserved customer mental model.

### Scenario engine input mutation

`predict_scenario` мутирует input `media_plan` dict при `plan_n == 1` (rewrites single-period entry в N-element list of `total/N`). Caller's reference получает мутированный dict. UI должен pass deep copy или `structuredClone(plan)`. Documented + locked test `test_H2_input_dict_isolation_warning`.

### Multi-period plan не auto-padded

`training_n_periods = plan_n` by default; reads training data only when `plan_n == 1`. Multi-period plan dictates `n_periods` (5-month plan на 24-month MMM → 5 predictions, NOT auto-padded к 24).

---

## Decisions

1. **Этап 4 в MAX режиме за одну сессию** вместо разбиения на дни. Антон gave green light.
2. **Synthetic + real-pickle тесты** через single fixture builder `_optimizer_fixtures.py` shared across 4 test files.
3. **Phase 4 smoke matrix:** 12 configs C1-C12 покрывают analyst×planner×What-if × sales×awareness × money/mixed × inflation × per-channel/group × forecast horizons {8,12,26}.
4. **F1 fix включил UI plumbing** (Tauri arg + Svelte state) вместо backend-only. Решение: customer benefit материализуется только через UI cooperation.
5. **L4 closed via documentation** (no code change), L5 closed via standalone helper (no auto-injection в optimize() output — keep separation of concerns).
6. **Real-pickle test** использует OLS engine (~10sec) вместо Bayesian MCMC (heavy). Sufficient для smoke; full posterior tests deferred.
7. **Threshold 3× для hierarchical warning** locked via M8 convention parallel вместо deep recalibration experiment (synthetic showed shrinkage не differentiate optimizer allocations).
8. **Все коммиты pushed на remote** (math-fix-v1.0.13). 3 audit tags pushed.

---

## Pending

### Высокий приоритет (на следующую сессию)

1. **Release v1.2.0 NSIS build** — bump versions (Cargo.toml, tauri.conf.json, package.json к 1.2.0), build, SHA256, GitHub Release на `Ackold26/aurora-releases`, Supabase `app_versions` PATCH, `rosst-updates/aurora-econometrica/latest.json`, tag `v1.2.0`, verify auto-update. Скилл `aurora-release-update`.
2. **UI panel для hierarchical warning** (~1-2h cosmetic). Helper `hierarchical_extrapolation_warning()` готов + 21 unit test проходит. Нужно:
   - Tauri command `econ_hierarchical_warning` в `src-tauri/src/commands/econometrica.rs`
   - Python endpoint в `sidecar/server.py`
   - Svelte panel в `OptimizeStep.svelte` after successful planning-mode optimize

### Средний приоритет

3. **Pre-push git hook** — критические инварианты (~10 sec) перед push, защита от случайной публикации сломанного.
4. **GitHub Actions CI** — автозапуск 820 тестов при push к remote.
5. **Расширить real-pickle тесты** — Венарус, Мираторг, Афала из `D:/Docs/Aurora_Ai/TestData/Econometrica/` или `~/Desktop/Эконометрика - тестовые файлы/`.

### Низкий приоритет (long-term)

6. **Real Bayesian validation L5** — когда numpyro/PyMC environment ready + время на 30 bootstrap refits, эмпирически валидировать 50% shrinkage assumption.
7. **Phase 2.6 reports** — HTML/PPTX cards для planning mode (отдельный track).
8. **Em-dash sweep** — массовая замена «—» → «-» в 10 приложениях Aurora (отложено).

### Документы для следующей сессии

- `~/Desktop/aurora-econometrica-next-session-prompt.md` — самодостаточный промт для start-of-session
- `~/Desktop/optimizer-audit-followup-plan.md` — статус всех 5 этапов

---

## Full Session Notes

### Сессия timeline (2026-05-03)

**Начало:** Антон спросил о новом плане работ → собрал план `~/.claude/plans/zazzy-tumbling-kettle.md` (5-фазный optimizer audit, ~7-7.5 dev-days). Старт в MAX.

**Phase 1 — Math invariants (optimizer)** ⏱️~30мин:
- Прочитал optimizer.py 1272 LOC, forecasting.py, scenario.py, decomposer.py, MATH_AUDIT v1.3 + v2.0
- Написал `tools/test_optimizer_invariants.py` (~570 LOC, 152 tests, I1-I8)
- Found I5b chain transitive monotonicity violation (4 of 5 seeds fail) → marked xfail advisory
- Added `# invariant: I*` annotations в optimizer.py at 4 sites

**Phase 2 — Edge case matrix** ⏱️~25мин:
- Refactored `build_synthetic_pickle` к shared `_optimizer_fixtures.py`
- 11 batches × 54 tests: forecast validation rejection, channel counts, unit-smell, What-if extremes, pass-18 regression, anchor monotonicity, zero-spend, untrained mix, awareness caps, UnboundLocalError prevention, inflation edges
- All 54 pass in 12.5s

**Phase 3 — Error path scan** ⏱️~20мин:
- AST walker `tools/audit_optimizer_error_paths.py` (~250 LOC)
- 5 HIGH inline fixes: missing `error_code` в model-not-found / empty-plan returns (optimizer + scenario + decomposer × 5 paths). Unified codes `MODEL_NOT_FOUND` + `MEDIA_PLAN_EMPTY`
- 1 MED inline fix: silent inflation `except Exception: pass` в scenario.py:90 → `logger.warning(exc_info=True)`
- 0 actual UnboundLocalError class bugs (pass-18 fix already shipped)
- Doc `docs/OPTIMIZER_ERROR_PATH_AUDIT.md`

**Phase 4 — Smoke E2E matrix** ⏱️~15мин:
- 12 configs C1-C12 + scenario round-trip = 13 tests. All pass in 10s.
- Includes pass-18 regression lock-in (C12) + Кагоцел-shape proxy (C5/C12)

**Phase 5 — Docs + commit** ⏱️~10мин:
- `OPTIMIZER_INVARIANTS_REGISTRY.md` + `OPTIMIZER_SMOKE_MATRIX.md`
- Commit `a89b37a` (11 files, +3102/-7) + tag `v1.0.13-optimizer-audit`. Pushed.

**Recommendations to Антон** → he chose to do them in order. Switched to MEDIUM for commit, then HIGH for F1.

**Этап 1 (commit)** — already done above.

**Этап 2 — F1 cumulative anchor** ⏱️~25мин:
- Backend: `optimizer.py` accepts `prev_optimal` config field, adds as direct candidate
- Rust IPC: `econ_optimize` Tauri command + JSON body
- Svelte UI: `lastOptimalMoneyByChannel` $state, captured after success, passed via `prevOptimal`
- Test flip: `test_I5_chain_monotonic_advisory` (xfail) → `test_I5_chain_monotonic_with_cumulative_anchor` (passes 5/5)
- Commit `d8e19fd` (5 files, +115/-39). Pushed.

**Этап 3 — Real-pickle integration** ⏱️~20мин:
- Antон gave path к Кагоцел xlsx (`~/Desktop/Эконометрика - тестовые файлы/`)
- Found existing `D:/Docs/Aurora_Ai/TestData/Econometrica/Kagocel_RF_MMM_dataset.xlsx`
- Iteratively fixed KPI auto-discovery heuristic (бренд / факт patterns)
- 4 tests: C1 (analyst), C5 (planner+inflation+per-channel), C12 (What-if 0.5×), F1 (chain anchor). All pass on real Кагоцел в 4s.
- Extended `conftest.py` resolution chain: env var → default → Desktop fallback
- Commit `c51ff70` (2 files, +352/-9). Pushed.

**Этап 4 — Scenario + decomposer audit (MAX, 1 дев-день equivalent)** ⏱️~75мин:
- Phase A1 scenario invariants: 131 tests (S1-S14). 1 fail S5 → fixed (capture totals before predict_scenario mutation).
- Phase A2 scenario edge cases: 30 tests (8 batches A-H). 2 fails G1/G2 → fixed (multi-period plan dictates n_periods, not auto-padded — documented behavior).
- Phase B1 decomposer invariants: 114 tests (D1-D13). 1 fail D10 → 2 inline fixes (untrained detection extension + verdict/action preservation).
- Phase B2 decomposer edge cases: 27 tests (6 batches A-F). All pass.
- 3 docs: `SCENARIO_INVARIANTS_REGISTRY.md`, `DECOMPOSER_INVARIANTS_REGISTRY.md`, `SCENARIO_DECOMPOSER_AUDIT_OUTCOME.md`
- Commit `a207140` (9 files, +2600/-1). Tag `v1.0.13-engine-audit-complete`. Pushed.

**Этап 5 — Phase 2.0 Part 2** ⏱️~30мин:
- Discovered L4 γ-recalibration was ALREADY OBSOLETE (S3 synergy redirect к tier-based). No code change needed.
- L5: synthetic experiment `tools/audit_v2_part2_hierarchical.py` showed shrinkage doesn't differentiate optimizer allocations (proportional preservation of rankings). Real risk = decompose ROI attribution.
- Helper `hierarchical_extrapolation_warning()` shipped в `forecast_validation.py` с threshold 3× (M8 convention).
- 21 unit tests in `test_forecast_validation_hierarchical.py` — all pass.
- Doc `docs/MATH_AUDIT_v2_PART2_OUTCOME.md`
- Commit `d7ac143` (5 files, +886/-0). Tag `v1.0.13-audit-followup-complete`. Pushed.

### Files modified (cumulative)

**New tests (6 files):**
- `tools/test_optimizer_invariants.py` (152 tests)
- `tools/test_optimizer_edge_cases.py` (54 tests)
- `tools/test_optimizer_smoke_matrix.py` (13 tests)
- `tools/test_optimizer_real_pickle.py` (4 tests, requires_real_data marker)
- `tools/test_scenario_invariants.py` (131 tests)
- `tools/test_scenario_edge_cases.py` (30 tests)
- `tools/test_decomposer_invariants.py` (114 tests)
- `tools/test_decomposer_edge_cases.py` (27 tests)
- `tools/test_forecast_validation_hierarchical.py` (21 tests)

**New tools (2 files):**
- `tools/_optimizer_fixtures.py` — shared synthetic-pickle builders
- `tools/audit_optimizer_error_paths.py` — AST walker
- `tools/audit_v2_part2_hierarchical.py` — synthetic experiment harness

**New docs (8 files в `docs/`):**
- `OPTIMIZER_INVARIANTS_REGISTRY.md`, `SCENARIO_INVARIANTS_REGISTRY.md`, `DECOMPOSER_INVARIANTS_REGISTRY.md`, `OPTIMIZER_ERROR_PATH_AUDIT.md`, `OPTIMIZER_SMOKE_MATRIX.md`, `SCENARIO_DECOMPOSER_AUDIT_OUTCOME.md`, `MATH_AUDIT_v2_PART2_OUTCOME.md`, `audit_v2_part2_hierarchical_results.json` (snapshot)

**Modified engines (3 files):**
- `sidecar/econometrica/engines/optimizer.py` — F1 + 1 error_code + 4 inline annotations
- `sidecar/econometrica/engines/scenario.py` — 3 error_codes + logger.warning
- `sidecar/econometrica/engines/decomposer.py` — 1 error_code + untrained guard + verdict/action preservation

**Modified utils (1 file):**
- `sidecar/econometrica/utils/forecast_validation.py` — `hierarchical_extrapolation_warning()` helper
- `sidecar/econometrica/utils/optimizer_constraints.py` — no changes

**Modified Tauri (1 file):**
- `src-tauri/src/commands/econometrica.rs` — `prev_optimal: Option<Value>` arg

**Modified Svelte (1 file):**
- `src/lib/components/pipeline/OptimizeStep.svelte` — `lastOptimalMoneyByChannel` state + reset on project change + invoke arg

**Conftest (1 file):**
- `tools/conftest.py` — `_resolve_testdata_dir()` resolution chain extension

### Setup & config changes

- `AURORA_TESTDATA_DIR` env var resolution chain extended: env → default → Desktop fallback
- All audit changes на `math-fix-v1.0.13` branch (no main merge yet — pending v1.2.0 ship)

### Errors & workarounds

1. **Console mojibake** (`������`) при печати cyrillic in Bash: Python pandas reads UTF-8 correctly, just display issue. Workaround: `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` в standalone scripts.
2. **CRLF warnings** на Windows при git add: cosmetic, ignore.
3. **Pre-commit hook v40-xss XSS lint** runs cleanly на all commits.
4. **Push policy:** push only after explicit user approval. Антон confirmed via «делай» / «продолжай».
5. **AST scope mismatch:** function-scope analysis gives ~50 false positives. Manual filter required to surface real UnboundLocalError risks.
6. **Scenario engine input mutation:** caught by S5 test. Fix → capture totals BEFORE predict_scenario.

### Acceptance gates (final, 2026-05-03)

| Gate | Result |
|---|---|
| `pytest tools/ -n auto` | **820 passed + 5 skipped** в 21s |
| `npx svelte-check --threshold error` | 0 errors (142 pre-existing warnings) |
| `cargo check --manifest-path src-tauri/Cargo.toml --quiet` | clean |
| Real-data Кагоцел tests | 4/4 PASS в 4s |
| Helper unit tests | 21/21 PASS в 2.5s |

### Test count growth

| Stage | Tests | Δ |
|---|---|---|
| Pre-audit | ~150 | — |
| After Phase 1-5 optimizer audit | 488 | +338 |
| After F1 fix | 493 | +5 |
| After real-pickle | 497 | +4 |
| After scenario+decomposer audit | 799 | +302 |
| After Phase 2.0 Part 2 (final) | **820** | +21 |

**559 dedicated audit tests** + 261 pre-existing.

### Workflow shift

Reactive «fix-when-customer-screams» (passes 6-18 reactive за неделю на одном Кагоцеле) → proactive property-based verification across 3 engines pre-ship. Регрессии теперь ловятся автотестами до отправки клиенту.

### Next-session entry

**Promt:** `~/Desktop/aurora-econometrica-next-session-prompt.md` (self-contained, copy-pasteable). Содержит контекст проекта, итоги аудита, 6 приоритетов, команды быстрого старта, особенности окружения. Quick-start: `pytest tools/ -n auto` should give 820 passed in ~21s.
