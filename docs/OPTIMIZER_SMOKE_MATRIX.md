# Optimizer Smoke Matrix — Phase 4 of audit

**Branch:** `math-fix-v1.0.13`
**Established:** 2026-05-03
**Test file:** `tools/test_optimizer_smoke_matrix.py`
**Plan ref:** `C:\Users\ackol\.claude\plans\zazzy-tumbling-kettle.md`, Phase 4.

---

## Purpose

E2E sanity matrix covering production combinations of optimizer features.
Each config exercises several feature axes simultaneously — finding integration
bugs that unit tests miss.

**Acceptance per config:**
1. `status='ok'` OR explicit `error_code` (no Python exceptions, no NaN/Inf)
2. `expected_lift_pct > -10%` (no catastrophic regression)
3. Bounds satisfied (`optimal_money ≥ 0`, finite)
4. Result dict has all required schema keys
5. mROAS values consistent с decompose ROI (sign/scale check, sample C5)
6. C5 + scenario round-trip (sanity workflow)

---

## Configuration matrix

| ID  | Mode    | KPI       | Units | Inflation | Per-channel             | Forecast | Source           |
|-----|---------|-----------|-------|-----------|-------------------------|----------|------------------|
| C1  | analyst | sales     | money | None      | None                    | None     | synthetic        |
| C2  | analyst | sales     | mixed | None      | partial                 | None     | synthetic        |
| C3  | analyst | sales     | mixed | 25%/yr    | None                    | None     | synthetic 2yr    |
| C4  | planner | sales     | mixed | None      | None                    | 12       | synthetic        |
| C5  | planner | sales     | mixed | 25%/yr    | partial 4ch             | 12       | Kagocel-shape    |
| C6  | planner | sales     | mixed | None      | per-group brand+perf    | 12       | hierarchical     |
| C7  | planner | sales     | mixed | 25%/yr    | per-group               | 26       | hierarchical 2yr |
| C8  | analyst | awareness | money | None      | None                    | None     | synthetic        |
| C9  | planner | awareness | money | None      | None                    | 8        | synthetic        |
| C10 | planner | sales     | mixed | 25%/yr    | per-channel + per-group | 12       | hierarchical 2yr |
| C11 | planner | sales     | money | None      | infeasible-narrow       | 12       | edge case        |
| C12 | What-if | sales     | mixed | 25%/yr    | partial                 | 12       | Kagocel + 0.5×   |

**+1 round-trip test:** C5 optimal allocation → `scenario.predict_scenario` → `compare_scenarios`.

**Total: 13 tests.**

### Feature coverage map

| Feature axis            | Configs covering                |
|-------------------------|---------------------------------|
| Analyst mode            | C1, C2, C3, C8                  |
| Planner mode            | C4, C5, C6, C7, C9, C10, C11    |
| What-if (money_target)  | C12                             |
| Sales KPI               | C1-C7, C10-C12                  |
| Awareness KPI           | C8, C9                          |
| Money-only units        | C1, C8, C9, C11                 |
| Mixed units             | C2-C7, C10, C12                 |
| Inflation 25%           | C3, C5, C7, C10, C12            |
| Per-channel constraints | C2, C5, C10, C12                |
| Per-group brand+perf    | C6, C7, C10                     |
| Hierarchical model      | C6, C7, C10                     |
| Forecast 8 weeks        | C9                              |
| Forecast 12 weeks       | C4, C5, C6, C10, C11, C12       |
| Forecast 26 weeks       | C7                              |
| Infeasible-narrow       | C11                             |
| pass-18 regression      | C12                             |

---

## How to add a new config

1. Identify a production scenario not covered above (consult feature coverage map).
2. Add a `def test_C{N}_...` function к `test_optimizer_smoke_matrix.py`.
3. Build pickle via `_optimizer_fixtures.py` helpers:
   - `build_synthetic_pickle(...)` — vanilla
   - `build_multi_year_pickle(...)` — for inflation tests
   - `build_kagocel_shape(...)` — Russian FMCG-realistic
   - `promote_to_hierarchical(...)` — Trust 3 brand/perf
4. Call `optimize(config, str(proj))` с your scenario config.
5. Validate via `_validate_smoke_ok(r, label)` или `_validate_smoke_error(r, label, codes)`.
6. Update this doc + feature coverage map.

---

## Customer pickle integration (deferred)

Plan §6 specifies: «1+ customer pickle (Кагоцел МMX) verifies real-data correctness».

**Status:** ⏸️ Pending customer pickle access (Антон provides path on request).

**Plan для integration:**
- Mark test с `@pytest.mark.requires_real_data` (per `pytest.ini` markers).
- Set env var `AURORA_TESTDATA_DIR` к directory containing customer pickle.
- Test loads pickle, runs C12-equivalent What-if config, asserts no regression.
- CI skips this test (no env var set); developer machines with the env var run it.

The `build_kagocel_shape` synthetic fixture in C5/C12 covers the **shape** —
6-channel mixed (1 native + 5 money), β asymmetry ~350×, decay 0.245, 2-year
horizon. Real pickle adds:
- Posterior structure variability (real chains, not synthetic noise)
- Variable per-channel mean/decay drift
- Real intercept mean / control series

These exposed bugs in passes 6-17 (memory-recorded). Synthetic shape catches
**class** of bugs; real pickle catches **specific** ones.

---

## Running

```bash
cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica

# Just smoke matrix
pytest tools/test_optimizer_smoke_matrix.py -v

# Full audit suite
pytest tools/test_optimizer_invariants.py \
       tools/test_optimizer_edge_cases.py \
       tools/test_optimizer_smoke_matrix.py \
       -n auto -v

# Full project tests (including pre-existing)
pytest tools/ -n auto --no-header -q
```

Expected (as of 2026-05-03 phase 5):
- **488 passed + 5 skipped + 4 xfailed advisory + 1 xpassed** in ~20s parallel.
