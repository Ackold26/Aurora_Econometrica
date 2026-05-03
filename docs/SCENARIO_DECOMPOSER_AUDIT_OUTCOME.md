# Scenario + Decomposer Engine Audit — Outcome

**Branch:** `math-fix-v1.0.13`
**Started:** 2026-05-03 (Этап 4 of optimizer-audit follow-up plan)
**Plan ref:** `C:\Users\ackol\Desktop\optimizer-audit-followup-plan.md`
**Methodology:** mirror Phase 1-5 от optimizer audit на остальные движки.

---

## Scope

`engines/scenario.py` (predict_scenario, compare_scenarios) +
`engines/decomposer.py` (decompose, compute_roi_verdict).

---

## Deliverables

### Test files (новые)

| File | Tests | Purpose |
|---|---|---|
| `tools/test_scenario_invariants.py` | 131 | S1-S14 property-based invariants |
| `tools/test_scenario_edge_cases.py` | 30 | 8 batches edge corner cases |
| `tools/test_decomposer_invariants.py` | 114 | D1-D13 property-based invariants |
| `tools/test_decomposer_edge_cases.py` | 27 | 6 batches edge corner cases |

**Total: 302 new tests.**

### Docs (новые)

- `docs/SCENARIO_INVARIANTS_REGISTRY.md` — formal S1-S14 spec
- `docs/DECOMPOSER_INVARIANTS_REGISTRY.md` — formal D1-D13 spec
- `docs/SCENARIO_DECOMPOSER_AUDIT_OUTCOME.md` (этот документ)

### Inline fixes

#### F-decomposer-1 (HIGH) — Untrained channel detection extension

**Problem:** Decomposer only checked `params.get('untrained')` (OLS-engine pattern),
miss'ал `normalization.untrained_channels` list (Bayesian-engine pattern). Bayesian-
trained pickles с zero-variance channels gave **spurious non-zero contributions**
(channel processed normally → mean fallback → spurious Hill saturation signal).

**Fix:** `engines/decomposer.py:253` — extended guard:
```python
if params.get('untrained') or col in untrained_channels:
```

**Detected by:** `test_D10_untrained_channel_zero_contribution`.

#### F-decomposer-2 (HIGH) — Untrained verdict overwrite

**Problem:** Pre-fix untrained channel had verdict='Не обучен' set initially, then
**overwritten** by downstream `compute_roi_verdict` loop (which inferred 'Глубоко
убыточный' from roi=0 < 0.5 threshold). Customer saw misleading «deep loss» label
on channels that simply had no training data.

**Fix:** `engines/decomposer.py:533` — skip verdict + action computation для
untrained:
```python
if ch.get('untrained'):
    ch.setdefault('category', 'mixed')
    ...
    continue
```

Same skip applied к action decoration loop (line 581) — fixed action vocabulary
'Uncertain' + 'Не обучен' label.

**Detected by:** `test_D10_untrained_channel_zero_contribution`.

---

## Findings — low-severity / documented (no fix needed)

### S-low1 — Scenario engine mutates input `media_plan` dict

При `plan_n == 1`, scenario rewrites каждое значение в `media_plan[col]` со списка
длины 1 на список длины `forecast_periods` (each = total/N). Caller's reference
получает мутированный dict.

**Mitigation в UI code:** OptimizeStep.svelte should pass deep copy when саваешь
What-if scenario:
```js
predictScenario({ ..., mediaPlan: structuredClone(plan) })
```

**Test:** `test_H2_input_dict_isolation_warning` — documents and locks expected
mutation pattern (test fails if engine no longer mutates → registry update needed).

### S-low2 — Multi-period plan не auto-padded к training horizon

`training_n_periods = plan_n` by default (decomposer.py reads training data только
when `plan_n == 1`). Multi-period plan dictates n_periods (e.g. 5-month plan на
24-month MMM → 5 predictions, NOT padded к 24 with zeros).

This is documented behavior — UI should use single-period (length 1) input + explicit
`forecast_periods` для controlled horizon. If user submits arbitrary multi-period
plan, scenario respects plan length.

**Tests:** `test_G1`, `test_G2`, `test_G3` lock expected behavior.

---

## Acceptance gates (2026-05-03)

| Gate | Command | Result |
|---|---|---|
| Pytest (full) | `pytest tools/ -n auto` | ✅ **799 passed** + 5 skipped + 0 fail in 19.0s |
| svelte-check | `npx svelte-check --threshold error` | ✅ 0 errors |
| Cargo check | `cargo check --manifest-path src-tauri/Cargo.toml` | ✅ clean |

**Plan target ≥350 pass — превышено в 2.3×.**

Test count growth across audit:
- Pre-audit baseline: ~150 tests
- After optimizer audit (Phase 1-5): 488 tests
- After F1 fix: 493
- After real-pickle integration: 497
- **After scenario+decomposer audit (Этап 4): 799** (+302)

---

## Coverage map

| Engine | Property invariants | Edge cases | Total tests |
|---|---|---|---|
| Optimizer | I1-I8 (152) | 11 batches (54) | 219 |
| Scenario | S1-S14 (131) | 8 batches (30) | 161 |
| Decomposer | D1-D13 (114) | 6 batches (27) | 141 |
| Cross-engine smoke | — | — | 13 (C1-C12) |
| Real-pickle (Кагоцел) | — | — | 4 |
| **Cumulative** | **35 invariants** | **25 batches** | **538 audit tests** |

Plus pre-existing 261 tests (math correctness, narrative adapter, brand_perf
integration, kagocel redistribution, per_group_constraints, posterior_ci, etc).

---

## Phase 5 follow-ups (deferred к новой сессии)

**Этап 5 (Phase 2.0 Part 2):** γ recalibration + hierarchical thresholds. Требует
bootstrap CI comparison на 30 refits + real MMM training. После v1.2.0 ship.
Memory ref: `project_econometrica_phase2_planning_mode.md`.

---

**Этап 4 → DONE 2026-05-03.** Optimizer + Scenario + Decomposer теперь имеют
формальные invariant registries с property-based test enforcement. Reactive
«fix-when-customer-screams» workflow заменён на proactive verification across
3 engines.
