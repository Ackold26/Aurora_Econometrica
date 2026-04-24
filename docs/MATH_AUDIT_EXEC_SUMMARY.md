# Aurora AI Econometrica Math Audit — Executive Summary

**Date:** 2026-04-25 | **Version:** v1.1 | **Target release:** v1.0.13

---

## 🚨 Ship recommendation

**DO NOT ship v1.0.13 to commercial clients.** Audit identified **11 correctness-breaking (P0) defects** across the MMM math pipeline. Current model produces plausible-looking but numerically incorrect results. Pre-commercial status gives window to fix правильно.

---

## 3 critical findings

### 1. Decomposer is not MMM decomposition
`decomposer.py:62-65` distributes contribution as `|β_i| / Σ|β_j| × total`. This is β-weighted proportion, **not** `β × saturation(adstock(spend))`. Ignores Hill saturation, adstock carry-over, AND spend level entirely. Every "channel contribution" number in every deliverable is wrong by arbitrary factors.

### 2. Four different Hill formulas for "the same" model
Training uses z-scored spend + raw γ. Reconstruction (R²/MAPE diagnostics) uses z-score + γ×max(x). Optimizer uses raw spend + γ×current_spend. JS what-if slider uses Robyn-style spend/mean + raw γ. Same posterior, **four different saturation curves.** Client sees different numbers depending on which artifact they look at.

### 3. Diagnostics computed from wrong formula
`modeler.py:537` manual reconstruction uses different Hill than training (line 312). The R² = 0.87 shown to client was computed from a model that was NOT trained. The training model's actual R² is unknown until `pm.sample_posterior_predictive` is used (which was avoided for speed).

---

## Full finding count

| Severity | Count | Categories |
|----------|-------|------------|
| 🔴 P0 (ship-blocking) | 11 | Hill scale, decomposer, reconstruction, optimizer, JS drift |
| 🟡 P1 (methodology) | 6 | Adstock not estimated, scenario ROAS total vs incremental, adstock missing from scenario |
| 🟢 P2 (doc debt) | 5 | MQS weights undocumented, no VIF check, R² not clamped |

See `MATH_AUDIT_v1_1.md` for per-formula detail.

---

## Path to ship

### Required (14-24h, 2-3 sessions)

1. **Hill fix** (7-12h) — `project_econometrica_hill_normalization_root_fix` (existing task).
   Resolves P0-1, P0-2, P0-9 automatically.

2. **Bundle: Decomposer + Reconstruction + Optimizer rewrite** (6-10h) — 3 new tasks:
   - `project_econometrica_decomposer_rewrite` (P0-3, P0-4, P0-10)
   - `project_econometrica_reconstruction_fix` (P0-7)
   - `project_econometrica_optimizer_rescale` (P0-5, P0-6, P0-11)

3. **Validator UX fix** (1-2h) — mixed-units warning for P0-11.

### Recommended for same release (3-5h)

4. Scenario adstock + incremental ROAS (P1-3/4/5 bundled).

### Deferred to later releases

- P1-1 joint adstock MCMC estimation (large refactor, v1.1)
- P2 documentation debt
- VIF validator (P2-4)

---

## Ship gate criteria

Before tagging `v1.0.13-math-audited`:

- [ ] All P0 findings resolved via fix tasks
- [ ] `tools/test_math_correctness.py` 64/64 → updated after fixes, still PASS
- [ ] Post-fix validation tests added (synthetic MCMC recovery, PPC coverage, scenario sensitivity)
- [ ] Live Kagocel regenerate shows:
  - Response curves show growth zone (not flat plateaus)
  - Scenario +100% vs -50% → ≥ 5% delta KPI (not 0.05% как pre-fix)
  - Optimizer returns non-trivial allocation (not uniform)
  - JS what-if slider delta matches backend optimizer delta (within 5%)
  - Report ID unified HTML↔PPTX (already v1.0.12.5)

---

## Audit deliverables

| File | Purpose |
|------|---------|
| `docs/MATH_AUDIT_v1_1.md` | Full per-formula inventory + findings + reference matrix |
| `docs/MATH_AUDIT_HILL_FIX_COORDINATION.md` | Fix-task sequencing + acceptance criteria |
| `docs/MATH_AUDIT_EXEC_SUMMARY.md` | This 1-pager |
| `tools/test_math_correctness.py` | 64 assertions: pure formula correctness + 3 bug-signature regression detectors |

---

## Git anchors

- Safety tag: `v1.0.12-pre-math-audit`
- Audit complete: tag `v1.0.12-math-audit-done` (added this commit)
- Ship target: `v1.0.13-math-audited` (after fixes + live-test PASS)
