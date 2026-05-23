# Optimizer Error Path Audit - Phase 3 of Optimizer Audit

**Branch:** `math-fix-v1.0.13`
**Date:** 2026-05-03
**Author:** Claude (Opus 4.7) audit pass
**Plan ref:** `C:\Users\ackol\.claude\plans\zazzy-tumbling-kettle.md`, Phase 3.

**Scope (extended):**
- `sidecar/econometrica/engines/optimizer.py` (1276 LOC)
- `sidecar/econometrica/engines/scenario.py` (605 LOC)
- `sidecar/econometrica/engines/decomposer.py` (711 LOC)

**Methodology:**
1. Static AST walk via `tools/audit_optimizer_error_paths.py` for:
   - [C1] Conditionally-bound names referenced unconditionally (UnboundLocalError class)
   - [C2] `except X: pass` silent failures
   - [C4] Division operations с unguarded denominators
2. Manual line-level review for:
   - [C3] Early `return` paths missing required result schema fields
   - [C5] Sentinel-None access patterns
   - [C6] try/except completeness в state machines

---

## 📊 Findings Summary

| Severity | Count | Status |
|---|---|---|
| HIGH | 5 | ✅ Fixed inline |
| MEDIUM | 1 | ✅ Fixed inline |
| LOW | 4 | ✅ Documented (no action) |
| FALSE POSITIVE | ~50 | ✅ Triaged (AST scope-coarseness) |

---

## ✅ HIGH Severity (5) - Missing `error_code` в early-return paths

**Symptom:** UI/clients dispatch errors via `result.error_code`. Returns без error_code make these errors indistinguishable from non-typed failures, breaking error-path UX.

### F-H1 - `optimizer.py:272` model-not-found без error_code [FIXED]
```python
# Pre-fix
return {'status': 'error', 'message': 'Модель не найдена'}

# Post-fix
return {
    'status': 'error',
    'error_code': 'MODEL_NOT_FOUND',
    'message': 'Модель не найдена. Сначала обучите модель в кабинете «Данные и Модель».',
}
```

### F-H2 - `scenario.py:45` model-not-found без error_code [FIXED]
Same pattern - added `error_code='MODEL_NOT_FOUND'` + actionable message.

### F-H3 - `scenario.py:106` empty media plan без error_code [FIXED]
```python
return {'status': 'error', 'error_code': 'MEDIA_PLAN_EMPTY', 'message': '...'}
```

### F-H4 - `scenario.py:136` plan no data без error_code [FIXED]
Same code (MEDIA_PLAN_EMPTY) для двух semantically близких failure paths.

### F-H5 - `decomposer.py:170` model-not-found без error_code [FIXED]
Aligned с optimizer/scenario unified MODEL_NOT_FOUND code.

**Net effect:** UI now has 3 unified error_codes для cross-engine model/plan failures (`MODEL_NOT_FOUND`, `MEDIA_PLAN_EMPTY`, plus existing `MODEL_OUTDATED`).

---

## ✅ MEDIUM Severity (1) - Silent inflation failure в scenario.py

### F-M1 - `scenario.py:90` `except Exception: pass` silent inflation skip [FIXED]
Pre-fix: any exception in `apply_inflation_to_unit_costs` (data file read, date column missing, malformed inflation_pct dict) silently fell back to current_cost. Customer reports «inflation пропускается случайно» - no logs to debug.

Post-fix: добавлено `logger.warning(f"Scenario inflation adjustment failed: ..."`, `exc_info=True)`. Fallback behavior preserved (non-fatal). Same pattern как H1 audit fix в Phase 1.9 CI propagation (scenario.py:348-358).

---

## ℹ️ LOW Severity (4) - Acceptable silent excepts

These are intentional narrow-scope error swallowing с documented fallback semantics. Not changed.

| Location | Pattern | Rationale |
|---|---|---|
| `optimizer.py:890` | `except (np.linalg.LinAlgError, ValueError, RuntimeError): pass` inside anchor-multi-start SLSQP loop | Single-start failure does not affect remaining anchor candidates. Outer aggregation logs `_logger.warning` if all attempts fail. Acceptable. |
| `scenario.py:174` | `except (TypeError, ValueError): pass` для `int(forecast_periods_cfg)` coercion | Falls back к training_n_periods. Narrow exception, narrow scope. Acceptable. |
| `scenario.py:477` (`_sanitize_unit_costs`) | `except (TypeError, ValueError): pass` | Skips invalid float() conversions in user-supplied dict. Defensive sanitizer. Acceptable. |
| `decomposer.py:455` (decay quantile) | `except Exception: pass` | Optional Trust 3 metadata population - failure не должен брякнуть decompose flow. Acceptable. |

---

## 🚫 False positives - Triage

AST walker reported ~50 [C1] findings (conditionally-bound names referenced after conditional). Manual review showed **all are false positives** due to function-scope vs block-scope analysis coarseness:

- **References inside same conditional block as assignment** (e.g. `_kpi_type` line 354/380 - both inside `if forecast_periods_config is not None:` block).
- **For-loop body variables** (e.g. `cur, opt, mean_ch, a_type, uc, ch_dict` etc - assigned + referenced inside same `for col in media_cols:` iteration).
- **Pass-18 fixed cases** (`_default_anchor_enabled, _default_anchor_x_seed, _default_anchor_bounds`) - initialized BEFORE if-block per pre-existing fix, all references guarded by `if _default_anchor_enabled:`.

**Verdict:** No actual UnboundLocalError class bugs. Phase 1 invariant test (E1, J1) and Phase 2 edge-case tests (Batch J × 5 cases) validate this empirically - no UnboundLocalError surfaced in any synthesized scenario.

---

## 🔍 Manual review - Other categories

### [C3] Early-return state schema (18+ paths in optimize)
**Result:** All 11 status='error' returns в optimize() now include `error_code` after F-H1 fix. All 11 INFEASIBLE/UNIT_SMELL/INVALID/TOO_LONG/PER_GROUP error paths return well-formed dicts с (status, error_code, message). ✅

### [C4] NaN/Inf guards
Critical division operations checked manually:
- `optimizer.py:566` `x_avg_adstock / max(mean, 1e-10)` ✅ guarded
- `optimizer.py:567` `hill_function(..., gamma=max(p['gamma'], 1e-6))` ✅ guarded
- `optimizer.py:155, 246` mROAS chain rule `/ max(mean, 1e-10)` ✅ guarded
- `optimizer.py:990` `_max_abs_delta_money / max(money_target / max(n_ch, 1), 1.0)` ✅ guarded
- `scenario.py:219` `spend_t_adstock / max(mean, 1e-10) if mean > 0 else 0` ✅ guarded
- `scenario.py:312, 319` `denom = max(...)` ✅ guarded
- `scenario.py:399, 401` ROAS CI `/ total_spend_money` ✅ guarded by `_MIN_SPEND_FOR_ROAS_CI = 100.0`
- `decomposer.py:305, 414, 416` `mean_per_sample = np.maximum(..., 1e-10)` ✅ guarded

**Verdict:** 0 unprotected divisions found. All hot-path math operations have explicit floors. ✅

### [C5] Sentinel-None access patterns
- `posterior_samples` may be None (legacy v1.0/1.1 pickles) → all 11 access sites in optimizer.py + scenario.py + decomposer.py guarded by `if posterior_samples is not None:`. ✅
- `decay_pt`/`decay_samples`/`decay_point` may be None (Phase 1.1 fallback) → all 8 access sites guarded by `if decay is not None and adstock_type == 'geometric':` или ternary `{'alpha': float(decay_point)} if decay_point is not None else None`. ✅
- `mroi_current_ci_low` etc may be None → access sites in result_dict construction always inside `if posterior_samples is not None and ...:` guards. ✅

### [C6] try/except completeness
Optimizer `try:` blocks (3 occurrences):
1. Group hierarchy validation (line 511) - except → returns full schema. ✅
2. Default anchor setup (line 737) - except → logs warning, sets `_default_anchor_enabled = False`. ✅
3. Anchor full multi-start (line 845) - except → logs warning. ✅

Scenario `try:` blocks (4 occurrences):
1. Inflation apply (line 77, FIXED in F-M1) - except → now logs warning. ✅
2. Single-period distribution (line 147) - except → falls back к training_n_periods. ✅
3. n_periods coercion (line 170) - except → no-op (n_periods unchanged). ✅
4. CI computation (line 270) - except → logs warning, sets ci_low/high к None. ✅

Decomposer `try:` blocks: (1 occurrence)
1. Decay quantile metadata (line 450) - except → no-op. ✅ (LOW per F-L4)

**All try/except blocks have complete state setup.** ✅

---

## 📁 Files Modified

```
sidecar/econometrica/engines/optimizer.py   (+5 -1)   # F-H1
sidecar/econometrica/engines/scenario.py    (+25 -3)  # F-H2, F-H3, F-H4, F-M1
sidecar/econometrica/engines/decomposer.py  (+5 -1)   # F-H5
```

Total: 35 lines added, 5 removed across 3 files.

---

## ✅ Phase 3 Acceptance

- [x] AST walker covers optimizer.py + scenario.py + decomposer.py
- [x] All HIGH findings fixed inline (5)
- [x] MEDIUM findings fixed inline (1)
- [x] LOW findings documented (4)
- [x] False positives triaged with rationale (~50)
- [x] Existing test suite still passes (verified post-fix)
- [x] Audit doc complete с per-finding line-numbers + rationale + before/after diffs

**Phase 3 → DONE.** Ready for Phase 4 (smoke matrix).
