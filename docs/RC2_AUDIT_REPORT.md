# RC2 Audit Report — Aurora MMM Optimizer v2.1.0
**Date:** 2026-05-16  
**Audited commits:** d7f0921, 128606b, ebd5853, f0116a6, 975ec0d, 892d2f0  
**Branch:** feat/v2.0.0-explicit-mode-wizard  
**Auditor:** Security & Quality Red-team (autonomous)

---

## Test Results

| Suite | Result |
|-------|--------|
| `pytest` (sidecar) | **281 passed, 2 warnings** |
| `vitest` (frontend) | **570 passed, 27 files** |
| `npm run check` (svelte-check) | **12 errors, 173 warnings** |

Notes:
- Holiday re-injection tests: 4/4 passed (new `test_decomposer_holiday_reinject.py`)
- 12 svelte-check errors: 1 new in RC2-changed files (ValidateStepV13 type annotation), 11 pre-existing in unrelated test file (`industry-cpp-defaults.test.js`)
- 0 test regressions introduced by RC2 commits

---

## Findings

### RC2-AUD-01
**Severity:** High  
**File:** `sidecar/econometrica/engines/decomposer.py` line 266  
**Task:** 4a (B-01)

**Description:** `logger` is used in the exception handler of the holiday re-injection block but is never defined at module level in `decomposer.py`. Two usages exist: line 266 (new RC2 code) and line 586 (pre-existing). Both will raise `NameError: name 'logger' is not defined` if their respective exception paths are triggered.

**PoC:** Trigger the exception path (e.g., `generate_holiday_dummies` raises `ImportError` when numpy is unavailable in edge environment). The except block calls `logger.warning(...)` -> `NameError` -> exception propagates uncaught -> decompose returns server error instead of graceful degradation.

**Fix:** Add `import logging; logger = logging.getLogger('econometrica')` at the top of `decomposer.py` (after existing imports, line ~25). This is the same pattern used in `modeler.py`.

---

### RC2-AUD-02
**Severity:** High  
**File:** `sidecar/econometrica/engines/decomposer.py` lines 253-273  
**Task:** 4a (B-01)

**Description:** The B-01 fix handles the case where `generate_holiday_dummies` raises an exception (removes holiday cols from `control_cols`). However, it does NOT handle the case where `date_col not in df.columns` — the outer guard silently skips the re-injection block entirely, leaving holiday columns in `control_cols` but absent from `df`. The subsequent `df[control_cols]` access at line 548 raises `KeyError`, crashing the decompose endpoint.

**PoC:** User renames the date column in their Excel file after training the model. The config `date_column` no longer matches `df.columns`. `holiday_cols_to_inject` is non-empty (model trained with holidays). Inner `if date_col in df.columns` is False -> block skipped -> `control_cols` still contains holiday names -> `df[control_cols].fillna(0)` raises `KeyError`.

**Fix:**
```python
if holiday_cols_to_inject:
    date_col = config.get('date_column', 'Дата')
    if date_col in df.columns:
        try:
            from utils.holiday_calendar_ru import generate_holiday_dummies
            holiday_df = generate_holiday_dummies(df[date_col])
            for hcol in holiday_cols_to_inject:
                if hcol not in df.columns and hcol in holiday_df.columns:
                    df[hcol] = holiday_df[hcol].values
        except Exception as exc:
            logger.warning('Decomposer: re-injection failed (%s).', exc)
            control_cols = [c for c in control_cols if c not in holiday_cols_to_inject]
    else:
        # date_col missing: cannot re-inject, must strip holiday cols from control_cols
        logger.warning(
            'Decomposer: date_col %r not in df.columns — cannot re-inject holidays. '
            'Stripping %d holiday cols from control_cols to prevent KeyError.',
            date_col, len(holiday_cols_to_inject)
        )
        control_cols = [c for c in control_cols if c not in holiday_cols_to_inject]
```

---

### RC2-AUD-03
**Severity:** Medium  
**File:** `src/lib/components/pipeline/ModeDerivedExplanation.svelte` lines 107-111  
**Task:** 4g (U-04)

**Description:** `ModeDerivedExplanation` reads ratio and nPredictors from `$validateData?.result?.detected?.ratio` and `?.detected?.n_predictors` — the stale backend-computed values from the initial `econ_validate` call. The B-02 fix (task 4b) created `validationHeaderMetrics` as the SSOT for live ratio (recomputed reactively as user changes column roles), but `ModeDerivedExplanation` was not updated to consume it. The pre-flight summary shown just before model training displays a ratio that may be outdated if the user excluded channels during the Validate step.

**PoC:** User starts with 5 media channels (ratio 2.4). Excludes 2 weak channels during ColumnMapperConfirm. Live ratio becomes 3.5:1 (tracked in `validationHeaderMetrics`). User reaches ModeDerivedExplanation. The "Quality Control" card shows 2.4:1 (stale) and "Ratio данных: 2.4 - Критически мало" while the sticky header (from StepWrapper/validationHeaderMetrics) shows 3.5:1. Inconsistent UX, user sees conflicting numbers.

**Fix:** Import `validationMetrics` from `$lib/project-state.js` and replace `detectedRatio` and `nPredictors` derivations with reads from the SSOT store:
```js
import { validateData, perChannelInput, unitCosts, analysisMode, kpiType, validationMetrics } from '$lib/project-state.js';
// Replace:
const detectedRatio = $derived(Number($validateData?.result?.detected?.ratio ?? 0));
const nPredictors = $derived(Number($validateData?.result?.detected?.n_predictors ?? (mediaColumns.length + controlColumns.length)));
// With:
const detectedRatio = $derived($validationMetrics?.ratio ?? 0);
const nPredictors = $derived($validationMetrics?.nPredictors ?? (mediaColumns.length + controlColumns.length));
```

---

### RC2-AUD-04
**Severity:** Medium  
**File:** `src/lib/insights-rules.js` line 565  
**Task:** 4f (U-03)

**Description:** `modelPreTrainingInsights()` reads ratio from `validateResult.detected?.ratio` (stale backend value). This function is called by `InsightsPanel.svelte` when showing pre-training insights on the Model step. After the B-02 fix, the live ratio is in `validationHeaderMetrics`, but pre-training insights still show the stale ratio for the ratio-warning insight (lines 590-601). A user who excluded channels to improve ratio will see the old (lower) ratio in model step insights.

**PoC:** Same as RC2-AUD-03 but in Model step InsightsPanel. After excluding 2 channels, ratio improves from 2.4 to 3.5. Validate step sticky header shows 3.5:1 (correct). User goes to Model step. Pre-training insights show "Ratio 2.4:1 - ниже идеала 4:1" (stale).

**Fix:** Pass `validationHeaderMetrics` value as parameter to `modelPreTrainingInsights`, or have the caller pass the live ratio separately. Alternatively, compute ratio inline from `cols` (like `validateInsights` now does):
```js
const ratio = (rows > 0 && paramCount > 0) ? rows / paramCount : 0;
// instead of:
const ratio = validateResult.detected?.ratio ?? 0;
```
Note: `rows` from `validateResult.file?.rows` is not stale (row count doesn't change). `paramCount` from filtered `cols` is live (roles update in place).

---

### RC2-AUD-05
**Severity:** Medium  
**File:** `src/lib/project-state.js` lines 311-328, and `src/lib/components/pipeline/StepWrapper.svelte` line 37  
**Task:** 4c (B-03)

**Description:** The B-03 fix introduces `ratioSeverity` and `ratioMessage` fields (5-level granularity: error/warning-high/warning/info/success) in `validationHeaderMetrics`. However, these new fields are **never read by any component** in the codebase. `StepWrapper.svelte` still uses `validationMetrics.ratioStatus` (the old 3-level: ok/warn/bad) for its badge styling. `RatioInfoCard.svelte` has its own independent 4-level threshold logic. `ModeDerivedExplanation.svelte` has yet another independent 3-level derivation.

The new `ratioSeverity`/`ratioMessage` fields are defined but dead — they provide no UX value until wired to a component.

**Additionally:** The `ratioStatus` thresholds in `validationHeaderMetrics` are inconsistent with `ratioSeverity`: `ratioStatus` 'ok' = ratio >= 10, while `ratioSeverity` 'success' = ratio >= 5. For ratio 5.0-9.9, the header badge shows 'warn' (orange) while the message says 'success' (Хорошее соотношение). Contradictory signals.

**PoC:** ratio = 6.0 -> `ratioStatus = 'warn'` (orange badge in StepWrapper) -> `ratioSeverity = 'success'` -> `ratioMessage = 'Хорошее соотношение для надёжной модели'`. User sees orange badge with "good" text simultaneously.

**Fix (immediate):** Align `ratioStatus` thresholds with `ratioSeverity` or make `ratioStatus` derive from `ratioSeverity`:
```js
const ratioStatus = ratioSeverity === 'success' || ratioSeverity === 'info' ? 'ok'
  : ratioSeverity === 'warning' ? 'warn'
  : 'bad';
```
**Fix (complete):** Wire `ratioSeverity`/`ratioMessage` to `StepWrapper` badge and `ModeDerivedExplanation` quality card.

---

### RC2-AUD-06
**Severity:** Low  
**File:** `src/lib/components/pipeline/ValidateStepV13.svelte` line 289-295  
**Task:** 4d (U-01)

**Description:** `prevSubStepIdx` is initialized as `$state(subStep)` where `subStep` initial value is in range `{-2, -1, 0}`. TypeScript/JSDoc infers the type as `-2 | -1 | 0`. The subsequent assignment `prevSubStepIdx = current` (where `current = subStep` which can be 1, 2, or 3) causes `svelte-check` to report: `Type '0 | 3 | 1 | 2 | -1 | -2' is not assignable to type '0 | -1 | -2'`. This is confirmed as the only new svelte-check error from RC2 changes.

**PoC:** `npm run check` reports ERROR at `ValidateStepV13.svelte:295`.

**Fix:**
```js
/** @type {-2 | -1 | 0 | 1 | 2 | 3} */
let prevSubStepIdx = $state(/** @type {-2 | -1 | 0 | 1 | 2 | 3} */ (subStep));
```

---

### RC2-AUD-07
**Severity:** Low  
**File:** `src/lib/components/pipeline/ModeDerivedExplanation.svelte` line 363  
**Task:** 4g (U-04)

**Description:** Dead ternary expression in the quality card status rendering. Both branches of the ternary return identical values:
```svelte
{ratioStatus !== 'ok' && ratioStatus !== 'warn' ? ratioStatusLabel[ratioStatus] : ratioStatusLabel[ratioStatus]}
```
The ternary condition does nothing — both the true and false branches evaluate `ratioStatusLabel[ratioStatus]`. This was likely intended to have different text for 'bad' vs other statuses but was not completed.

**PoC:** Any ratio value renders the same text regardless of condition evaluation.

**Fix:** Remove the ternary:
```svelte
<span class="qc-status">{ratioStatusLabel[ratioStatus]}</span>
```
Or if distinct text was intended for the bad case, supply it:
```svelte
<span class="qc-status">{ratioStatus === 'bad' ? 'Критически мало' : ratioStatusLabel[ratioStatus]}</span>
```

---

### RC2-AUD-08
**Severity:** Low  
**File:** `src/lib/insights-rules.js` lines 187-189  
**Task:** 4f (U-03)

**Description:** `weakRatio` (ratio after hypothetically excluding all weak channels) is computed as:
```js
const weakRatio = totalRows / Math.max(mediaCols.length - weakNames.length + controlCols.length, 1);
```
When ALL media channels are weak (`weakNames.length === mediaCols.length`) AND there are no control columns, the denominator becomes `Math.max(0, 1) = 1`, giving `weakRatio = totalRows` (e.g., 24). This is shown in the tip text as "после исключения ratio 24:1" — a misleadingly optimistic number that implies after exclusion the model would be in great shape, when in reality there are 0 media channels and the model cannot train.

**PoC:** Dataset with 24 rows, 2 media channels both with 100% zeros (off-season campaign), 0 controls. `weakRatio = 24/1 = 24.0`. Tip shows "exclude 2 channels with >50% zeros (after exclusion ratio 24:1)". User excludes both channels. Model cannot train.

**Fix:** Add a guard:
```js
const remainingMedia = mediaCols.length - weakNames.length;
const weakRatio = weakNames.length > 0 && remainingMedia > 0
  ? totalRows / Math.max(remainingMedia + controlCols.length, 1)
  : null;
// In tip: show weakRatio only when non-null
```

---

### RC2-AUD-09
**Severity:** Low  
**File:** `src/lib/components/pipeline/ValidateStepV13.svelte` lines 36-40  
**Task:** Overall code quality

**Description:** `project-state.js` is imported twice in `ValidateStepV13.svelte` with separate `import { ... }` blocks (lines 23-28 and 36-40). While this works in JS (imports are deduplicated by the bundler), it is technically redundant and can cause confusion. The second import was added by the RC2 changes (task 4d imports `analysisObjective`, `expertMode`, `analysisMode`, `unitCosts`, etc.) without merging with the first block.

**Fix:** Merge both import blocks from `$lib/project-state.js` into a single import statement.

---

### RC2-AUD-10 (Security)
**Severity:** Low (defense-in-depth adequate)  
**File:** `sidecar/econometrica/engines/decomposer.py` lines 250-261  
**Task:** 4a (B-01)

**Description:** `holiday_cols_to_inject` is read from `model_data` (pickle file on disk). A user with write access to their project's `models/latest.pkl` could theoretically craft a `normalization.holiday_cols_injected` list with arbitrary strings. However, the injection is gated by `if hcol in holiday_df.columns` where `holiday_df` is generated from `generate_holiday_dummies` (calendar-based, fixed set of ~12 predefined holiday column names). Arbitrary injected names would simply fail the check and be skipped — no arbitrary column insertion is possible through this path.

**PoC:** Attacker modifies pickle to set `holiday_cols_injected: ["../../../etc/passwd"]`. The string is not present in `holiday_df.columns` (calendar-generated) -> no insertion into `df` -> safe.

**Fix:** No fix required. The calendar gate provides adequate defense-in-depth.

---

## Summary Table

| ID | Severity | Area | Task | Status |
|----|----------|------|------|--------|
| RC2-AUD-01 | **High** | `decomposer.py` logger undefined | B-01 | Open |
| RC2-AUD-02 | **High** | Missing date_col path — KeyError crash | B-01 | Open |
| RC2-AUD-03 | **Medium** | ModeDerivedExplanation stale ratio | U-04 | Open |
| RC2-AUD-04 | **Medium** | modelPreTrainingInsights stale ratio | U-03 | Open |
| RC2-AUD-05 | **Medium** | ratioSeverity dead + ratioStatus threshold mismatch | B-03 | Open |
| RC2-AUD-06 | Low | ValidateStepV13 prevSubStepIdx type error | U-01 | Open |
| RC2-AUD-07 | Low | Dead ternary in ModeDerivedExplanation | U-04 | Open |
| RC2-AUD-08 | Low | weakRatio misleading when all media weak | U-03 | Open |
| RC2-AUD-09 | Low | Duplicate import block in ValidateStepV13 | U-01/U-04 | Open |
| RC2-AUD-10 | Low (sec) | Security: holiday_cols_to_inject injection | B-01 | Closed (safe) |

**Severity counts:** 0 Critical, 2 High, 3 Medium, 5 Low (1 closed)

---

## Pilot Go/No-Go Assessment

**CAN REPEAT PILOT WITH CONDITIONS: Yes (with blocking fixes)**

### Must fix before next pilot session (2 High):

**RC2-AUD-01 + RC2-AUD-02** both in `decomposer.py`. These are the highest risk items:
- AUD-01: if any exception occurs during holiday re-injection (even transient), `logger.warning` crashes with `NameError` — graceful degradation fails, user sees cryptic error
- AUD-02: if user's date column name doesn't match config (e.g., renamed Excel), all models with holidays crash on decompose — complete regression of the B-01 fix

Both are single-file fixes, ~5 lines each. Fix time: ~10 minutes.

### Can pilot with known limitations (3 Medium):

- **AUD-03/04:** Pre-flight summary and model-step insights show stale ratio after channel exclusions. Visual inconsistency (different numbers on screen), but doesn't block modeling. User sees the correct ratio in the sticky header (StepWrapper reads SSOT).
- **AUD-05:** For ratio 5-10, badge says "warn" but text says "good". Minor confusing UX. ratioSeverity/ratioMessage are computed but displayed nowhere — the new 5-level graduation is effectively invisible.

### Non-blocking (5 Low):

Type annotation error in svelte-check (AUD-06), dead ternary (AUD-07), misleading tip text edge case (AUD-08), cosmetic code (AUD-09), and security non-issue (AUD-10).

---

## Econometric Notes

**Severity hierarchy (U-03/4f):** Correct. The new logic of "join paired metrics first, then convert physical to monetary, then collect more data, then exclude only weak channels" is econometrically sound. Omitted variable bias warning for exclusion of major channels (TV, OLV, Banners) is appropriate.

**Ratio thresholds:** The 5-level scale (error <2, warning-high 2-3, warning 3-4, info 4-5, success >=5) aligns with industry MMM guidance. The threshold for "error" at ratio <2:1 is appropriate for Bayesian models with informative priors (which can technically run at ratio 1.5:1 but yield unreliable posteriors).

**Holiday re-injection (B-01):** Approach is correct — re-generating holidays from the same calendar function used at training time guarantees bit-identical dummy encoding. No drift from different holiday generators.

**Single SSOT for ratio (B-02):** Architecturally sound. The derived store pattern in Svelte is the correct approach. The incomplete adoption (AUD-03/04/05) should be completed systematically.
