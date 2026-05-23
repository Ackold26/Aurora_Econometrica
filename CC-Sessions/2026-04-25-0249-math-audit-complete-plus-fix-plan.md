---
tags: [session, compressed, math-audit, hill-fix, decomposer, reconstruction, optimizer, fix-plan]
type: session
updated: 2026-04-25
---
# Quick Reference

Math audit ПОЛНОСТЬЮ ЗАВЕРШЁН + написан 7-фазный fix plan + Phase 1 (reconstruction P0-7) уже SHIPPED. 11 P0 + 6 P1 + 5 P2 found, 4 fix tasks queued. Audit deliverables: `docs/MATH_AUDIT_v1_1.md` (575 строк), `MATH_AUDIT_HILL_FIX_COORDINATION.md`, `MATH_AUDIT_EXEC_SUMMARY.md`, `MATH_FIX_PLAN.md` (7-phase 20-26h plan), `tools/test_math_correctness.py` (64 assertions). HEAD `b6f6400` (Phase 1 done, P0-7 closed). Tags: `v1.0.12-pre-math-audit`, `v1.0.12-math-audit-done`. Pending: Phases 2-7 (Hill normalization, decomposer rewrite, optimizer rescale, validation, ship).

**Topic:** math-audit-complete-plus-fix-plan
**Key files:**
- `docs/MATH_AUDIT_v1_1.md` — full audit (per-formula inventory + findings + reference matrix)
- `docs/MATH_AUDIT_EXEC_SUMMARY.md` — 1-pager
- `docs/MATH_AUDIT_HILL_FIX_COORDINATION.md` — fix-task sequencing + acceptance criteria
- `docs/MATH_FIX_PLAN.md` — 7-phase execution plan (line-level diffs, commit templates)
- `tools/test_math_correctness.py` — 64 assertions (Phase 1 inverted P0-7 test)
- `sidecar/econometrica/engines/modeler.py` (Phase 1 edit: line 537 gamma_scaled removed)
- `C:/Users/ackol/Desktop/Aurora_Econometrica_Math_Fix_Session_Prompt.md` — startup prompt for new sessions

**Status:**
- ✅ Math audit complete (5 commits, R1-R5)
- ✅ Plan v1.2 written + self-audited (`~/.claude/plans/immutable-bouncing-noodle.md`)
- ✅ Fix plan written (`docs/MATH_FIX_PLAN.md`)
- ✅ Phase 1 SHIPPED (commit `b6f6400`, P0-7 reconstruction fix)
- 📋 Phase 2 pending (Hill normalization spend/mean — 6-9h)
- 📋 Phase 3 pending (Decomposer rewrite — 5-7h)
- 📋 Phase 4 pending (Optimizer rescale + P0-11 — 4-5h)
- 📋 Phase 5 pending (Post-fix validation + live-test — 2-3h)
- 📋 Phase 6 optional (P1 bundle scenario adstock + incremental ROAS — 3-5h)
- 📋 Phase 7 pending (Ship + tag v1.0.13-math-audited — 1-2h)
- 📋 Total remaining: 18-25h across 2-3 sessions

---

## Learnings

### Architecture / methodology

1. **Decomposer was never doing MMM decomposition.** `decomposer.py:62-65`:
   ```python
   contribution_pct = abs(params['beta']) / total_beta  # |β|/Σ|β|
   contribution = (total_sales - baseline) * contribution_pct
   ```
   Channel contribution = β-weighted proportion of total media sales. **Completely ignores Hill saturation, adstock carryover, AND spend level.** Real MMM = `β × sat(adstock(x)) × y_std` per period. Numerical results only accidentally close to truth when channels happen to be similarly saturated.

2. **Training-vs-reconstruction Hill formula drift (P0-7).** modeler.py training (line 312) uses raw `gammas[i]`. modeler.py reconstruction (line 537) used `gamma_scaled = gammas[i] × max(x)`. R²/MAPE shown to client computed from a model that was NOT trained — different formula. Audit found this; Phase 1 fixed (commit b6f6400). 3-line code change with major semantic impact.

3. **Four different Hill formulas for "the same" model:**
   - Training: z-score + raw γ (broken, P0-1)
   - Reconstruction: z-score + γ×max(x) (different bug, P0-7, NOW FIXED)
   - Optimizer: raw spend + γ×current_spend (P0-5/6)
   - JS what-if slider: spend/mean + raw γ (Robyn-style, already correct)

   Same model produces 4 different results depending on which artifact client looks at.

4. **Hidden math layer never estimated.** `apply_adstock(...)` runs as numpy preprocessing BEFORE MCMC. `alpha=0.5` for geometric, `shape=2/scale=3` for Weibull — fixed defaults. Real MMM (Robyn, PyMC-Marketing, Meridian) jointly estimates adstock + Hill params. Our model misses entire dimension of flexibility (P1-1).

5. **Pre-commercial state allows breaking changes.** Антон confirmed 2026-04-24. Fixes can be cardinal — pickle schema migration, formula refactor, scenario semantic change. No backward-compat paralysis.

### Process

6. **Audit value: critical findings beyond known.** Trigger was z-score Hill (1 known bug). Audit found 10 MORE P0 ($\geq$ ship-blocking) defects. Hidden bugs accumulate when no formal review.

7. **Self-audit of plan reveals 23 defects.** Initial fix plan v1.1 had: factual errors (LMM archived, PyMC-Marketing not primary ref), logic errors (test-after-fix vs TDD), methodological gaps (no PPC, no SBC), missing scope (JS drift, .pkl integrity), estimation errors (11-17h optimistic vs 18-22h realistic). Critical self-review before execution catches issues cheap.

8. **Consolidating redundant docs saves time.** Original plan: 3 separate audit docs. Revised: 1 consolidated. Saved ~3h with no loss of fidelity.

9. **TDD vs test-after for refactor.** Tests-first approach pins current behavior; refactor failures map to semantic decisions explicitly. Test-after misses semantic drift in untested edge cases.

10. **Bug-signature regression detectors.** Tests that DOCUMENT current bug behavior, designed to FAIL after fix lands. Forces explicit acknowledgment when fix occurs (test inversion required). Pattern: P0-2/5/6/7 tests in test_math_correctness.py.

### Bayesian / MMM

11. **Beta(3,3) γ prior on z-score scale concentrates half-saturation at mean+0.5σ.** With z-score normalization, γ ≈ 0.5 → channels saturate at ~half-σ above mean → almost always above plateau. Combined with `clip(x, 0)` dropping below-mean periods to zero → catastrophic decomposition behavior.

12. **Posterior reconstruction gotcha.** `pm.sample_posterior_predictive` is canonically correct but slow on Windows without C compiler. Manual reconstruction faster but easy to get wrong (P0-7 was). Best practice: explicit parity test against `pm.sample_posterior_predictive` to validate manual.

13. **PyMC-Marketing as primary reference.** Same stack (PyMC + Bayesian), tested MMM class. Closer than Robyn/Meridian semantically. Should be #1 ref для cross-checks.

---

## Decisions

### Audit phase decisions

- **D1 Single integrated read pass (R1)** vs 3 separate rounds — saves 3h, single-source-of-truth doc
- **D2 Bug-signature regression tests** — explicit failure on fix lands, forces test inversion (vs silent change)
- **D3 NumPy-only prior predictive** для R3 (no PyMC compile) — fast, doesn't require working model
- **D4 Defer MCMC-based PPC/SBC** until post-Hill-fix — current model broken, PPC artifacts misleading
- **D5 Skip "fix-during-audit"** — strict scope discipline, fixes are separate tasks
- **D6 Reference order: PyMC-Marketing > Robyn > Meridian > LMM (archived)** — same-stack first

### Plan v1.2 decisions

- **D7 7 phases vs 5 rounds** — more granular, each phase = self-contained commit
- **D8 Phase 1+2 parallel-capable** (independent modules) — but sequential default
- **D9 Per-phase tags `v1.0.13-rcN`** — granular rollback
- **D10 Pickle compat = HARD REJECT** with clear UX, not auto-rebuild — simpler, explicit
- **D11 Decomposer needs intercept_mean + control_betas_mean in pickle** — Phase 2 saves them
- **D12 Optimizer P0-11 mixed-units guard inline** in Phase 4, not separate task
- **D13 P1 bundle (scenario adstock + incremental ROAS) marked OPTIONAL** for v1.0.13 — can ship in v1.0.13.1
- **D14 Live-test gate AFTER Phase 2** (not after Phase 1) — Phase 1 is independent, doesn't affect Kagocel results materially

### Execution decisions

- **D15 Phase 1 first** despite plan ordering Phase 2 first — Phase 1 is faster, lower risk, validates workflow
- **D16 Phase 1 implementation:** Option A (raw gamma) not Option B (`pm.sample_posterior_predictive` subsample) — simpler, zero perf cost
- **D17 Test inversion in same commit** as fix — atomic semantic migration

---

## Solutions & Fixes

### Audit R1: consolidated inventory (commit `0414306`)

`docs/MATH_AUDIT_v1_1.md` — 575 lines covering:
- Per-formula entries with code line, derivation, references, verdict
- 11 P0 / 6 P1 / 5 P2 findings
- Reference compliance matrix (Robyn/PyMC-Marketing/Meridian)
- Recommendations + ship gate criteria

### Audit R2: behavior-pinning tests (commit `e260362`)

`tools/test_math_correctness.py` — 55 assertions (then 64 after R3):
- Pure formulas: Hill bounds/monotonicity/stability, adstock recursion, y norm roundtrip, R²/MAPE/RMSE
- Marginal ROI = analytical derivative validated vs numerical
- P0-5/6/7 regression detectors (designed to fail post-fix)
- Robyn-style Hill positive-domain (post-fix target)
- JS↔Python Hill parity grid

### Audit R3: prior predictive (commit `12addcf`)

NumPy-only prior predictive (no MCMC compile):
```python
def _sample_priors(n_draws, n_channels, rng):
    return {
        "intercept": rng.normal(0, 0.5, size=n_draws),
        "media_betas": np.abs(rng.normal(0, 0.3, size=(n_draws, n_channels))),  # HalfNormal(0.3)
        "alphas": rng.gamma(shape=5, scale=1/3, size=(n_draws, n_channels)),
        "gammas": rng.beta(3, 3, size=(n_draws, n_channels)),
        "sigma": np.abs(rng.normal(0, 0.3, size=n_draws)),
    }
```

Tests: prior predictive sanity, gamma/alpha coverage, P0-2 half-data drop signature. 64/64 PASS.

### Audit R4: coordination doc (commit `5e36769`)

`docs/MATH_AUDIT_HILL_FIX_COORDINATION.md`:
- Tests as acceptance criteria (PASS at all times vs intentional inversion)
- Auto-resolved findings (P0-1, P0-2, P0-9 fold into Hill fix)
- Independent fix tasks: P0-3/4/10 (decomposer), P0-5/6/11 (optimizer), P0-7 (reconstruction)
- Post-fix validation test stubs (synthetic MCMC recovery, scenario sensitivity, optimizer non-trivial allocation)

### Audit R5: exec summary + tasks (commit `1182338`)

3 new memory tasks queued:
- `project_econometrica_decomposer_rewrite` (P0-3/4/10, 5-7h)
- `project_econometrica_reconstruction_fix` (P0-7, 2-3h)
- `project_econometrica_optimizer_rescale` (P0-5/6/11, 4-5h)

Tag `v1.0.12-math-audit-done`.

### Fix plan (commit `d45d4d6`)

`docs/MATH_FIX_PLAN.md` — 7-phase execution plan:
- Phase 0: Setup (0.5h)
- Phase 1: Reconstruction P0-7 (2-3h, INDEPENDENT)
- Phase 2: Hill normalization P0-1/2/9 (6-9h, MOST INVASIVE)
- Phase 3: Decomposer rewrite P0-3/4/10 (5-7h, depends on 2)
- Phase 4: Optimizer rescale + P0-11 (4-5h, depends on 2)
- Phase 5: Validation + live-test (2-3h)
- Phase 6: P1 bundle (3-5h, OPTIONAL)
- Phase 7: Ship (1-2h)

Total realistic: 20-26h across 3 sessions.

### Phase 1 SHIPPED (commit `b6f6400`)

`sidecar/econometrica/engines/modeler.py:537`:
```python
# BEFORE:
gamma_scaled = gamma_i * max(x_safe.max(), 1e-10)
saturated = x_safe ** alpha_i / (x_safe ** alpha_i + gamma_scaled ** alpha_i + 1e-10)

# AFTER (Phase 1):
saturated = x_safe ** alpha_i / (x_safe ** alpha_i + gamma_i ** alpha_i + 1e-10)
```

3-line change. Manual posterior reconstruction now matches training Hill formula. R²/MAPE/RMSE diagnostics computed from same formula as trained model.

Test inverted: `test_p0_7_training_reconstruction_hill_divergence` → `test_p0_7_training_reconstruction_hill_parity` (asserts diff < 1e-9 instead of > 0.01). 64/64 still PASS.

P0-7 CLOSED.

---

## Files Modified

### Committed

| Commit | Tag | Files | Description |
|--------|-----|-------|-------------|
| `0414306` | — | docs/MATH_AUDIT_v1_1.md (NEW, 575 lines) | R1 consolidated inventory + findings |
| `e260362` | — | tools/test_math_correctness.py (NEW) | R2 55 assertions, behavior-pinning tests |
| `12addcf` | — | tools/test_math_correctness.py (+9) | R3 numpy prior predictive |
| `5e36769` | — | docs/MATH_AUDIT_HILL_FIX_COORDINATION.md (NEW) | R4 coordination + acceptance criteria |
| `1182338` | `v1.0.12-math-audit-done` | docs/MATH_AUDIT_EXEC_SUMMARY.md (NEW) + 3 new memory task files | R5 exec summary + fix backlog |
| `d45d4d6` | — | docs/MATH_FIX_PLAN.md (NEW, 639 lines) | 7-phase fix execution plan |
| `b6f6400` | — | sidecar/econometrica/engines/modeler.py (3 lines), tools/test_math_correctness.py (test inversion) | Phase 1: P0-7 reconstruction fix |

### Non-tracked

- `~/.claude/plans/immutable-bouncing-noodle.md` — plan v1.2 with self-audit changelog
- `C:/Users/ackol/Desktop/Aurora_Econometrica_Math_Fix_Session_Prompt.md` — startup prompt for new sessions

### Memory updates

- `project_econometrica_math_audit.md` — AUDIT COMPLETE
- `project_econometrica_decomposer_rewrite.md` (NEW) — P0-3/4/10 fix task
- `project_econometrica_reconstruction_fix.md` (NEW) — P0-7 fix task (now DONE per Phase 1)
- `project_econometrica_optimizer_rescale.md` (NEW) — P0-5/6/11 fix task
- `MEMORY.md` — priority entries updated

---

## Setup & Config Changes

- Git tags:
  - `v1.0.12-pre-math-audit` (safety, before audit work)
  - `v1.0.12-math-audit-done` (after R5)
  - (planned) `v1.0.13-rcN` per phase, `v1.0.13-math-audited` after ship
- Git branch: master (Phase 1 committed direct; future phases recommend `math-fix-v1.0.13` branch per plan)
- No infrastructure changes
- No Supabase / GH Release publication
- lefthook pre-commit (V40 AST linter) green for all commits

---

## Pending

### Immediate next session

**Continue from `MATH_FIX_PLAN.md` Phase 2** (Hill normalization, 6-9h):

1. Phase 2a: `modeler.py:249-251` z-score → spend/mean
2. Phase 2b: `scenario.py:86` sync
3. Phase 2c: pickle schema add `intercept_mean` + `control_betas_mean` + `model_version='1.1'`
4. Phase 2d: test updates (`test_p0_2_half_data_silent_drop` → invert)
5. Phase 2e: JS verify (no change needed)

Then live-test refit Kagocel — gate before Phase 3/4.

### Subsequent sessions

- Phase 3: Decomposer rewrite (5-7h, depends on Phase 2)
- Phase 4: Optimizer rescale (4-5h, depends on Phase 2)
- Phase 5: Validation + live-test (2-3h)
- Phase 7: Ship + memory finalize (1-2h)

Phase 6 (P1 bundle) optional — can ship in v1.0.13.1.

### Open issues / unknowns

- Hill fix may regress NUTS R-hat — reserve buffer for prior tuning if needed (Beta(3,3) → HalfNormal(0.5) candidate)
- Pickle migration UX — decide if "переобучить" button needed in UI
- Live-test reveal: if >2 new P0 found post-fix, stop + re-plan

### Orthogonal P0 tracks (not blocking math fix)

- `project_em_dash_cleanup_sweep` — text cleanup across 10 apps

---

## Errors & Workarounds

### Audit phase

- **Plan-mode workflow:** ExitPlanMode rejected when user wanted critique → write critique inline + rewrite plan + retry. Workflow lesson: always offer critique opportunity before exiting plan mode.
- **Auto-mode reminder collision:** "Exited Auto Mode" reminder appeared during plan mode work. Plan mode supersedes — followed plan mode rules, ignored auto-mode banner.
- **Token budget for audit doc:** 575-line audit doc is large but readable; chose consolidated single doc over 3 separate (per self-audit finding).

### Phase 1 execution

- User executed Phase 1 themselves (commit b6f6400) — included test inversion in same commit (atomic semantic migration, per D17 decision).

### Test infrastructure

- `tools/test_math_correctness.py` runs from repo root: `python tools/test_math_correctness.py`. Path fix: `sys.path.insert(0, str(SIDECAR / "econometrica"))` для импорта `utils.saturation` etc.
- cp1251 console UnicodeEncodeError на Cyrillic prints — `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.
- Lefthook pre-commit V40 lint green после всех commits.

---

## Full Session Notes

### Timeline (compressed)

1. **Session continuation from output-quality work** — output quality v1.0.12.5 just shipped, audit triggered by user request "проведи детальный аудит математики".

2. **Plan creation:**
   - Read existing memory (`project_econometrica_math_audit.md`, `project_econometrica_hill_normalization_root_fix.md`)
   - Quick file size scan (modeler 728, validator 403, decomposer 252, optimizer 196, scenario 291, adstock 131)
   - Wrote plan v1.1 to `~/.claude/plans/immutable-bouncing-noodle.md`
   - User asked for self-audit of plan → wrote 23-defect critique → rewrote as v1.2

3. **User said "реализуй план в режиме максимальной автономности"** → executed:
   - Phase 0: safety tag `v1.0.12-pre-math-audit`
   - R1: read all engine files (modeler/validator/decomposer/optimizer/scenario/adstock_selector/utils), wrote `docs/MATH_AUDIT_v1_1.md` 575 lines, commit
   - R2: wrote `tools/test_math_correctness.py` 55 assertions, fixed 1 test (input scaling), commit
   - R3: added 9 numpy-only prior predictive tests, commit (64/64 PASS)
   - R4: wrote `docs/MATH_AUDIT_HILL_FIX_COORDINATION.md`, commit
   - R5: wrote `docs/MATH_AUDIT_EXEC_SUMMARY.md`, created 3 new memory tasks, updated existing math_audit memory, MEMORY.md priority, tag `v1.0.12-math-audit-done`, commit

4. **User asked "как все исправить? нужен план"** → wrote `docs/MATH_FIX_PLAN.md` (639 lines, 7 phases, line-level diffs).

5. **User asked "выведи полную ссылку на план"** → provided absolute path.

6. **User asked "подготовь промт для начала работ"** → wrote `Aurora_Econometrica_Math_Fix_Session_Prompt.md` to Desktop.

7. **User executed Phase 1 themselves** (commit `b6f6400`) — modeler.py:537 fixed, test inverted, P0-7 closed.

8. **/compress** invoked — this session log.

### Key files changed across audit

- `sidecar/econometrica/engines/modeler.py:537` (Phase 1: -3 lines manual reconstruction divergence)
- `tools/test_math_correctness.py` (NEW): 64 assertions, includes test inversion as Phase 1 lands
- `docs/MATH_AUDIT_v1_1.md` (NEW, 575 lines): consolidated audit
- `docs/MATH_AUDIT_EXEC_SUMMARY.md` (NEW): 1-pager
- `docs/MATH_AUDIT_HILL_FIX_COORDINATION.md` (NEW): coordination
- `docs/MATH_FIX_PLAN.md` (NEW, 639 lines): execution plan

### Risk/rollback posture

- Safety tag `v1.0.12-pre-math-audit` preserves pre-audit state
- `v1.0.12-math-audit-done` preserves post-audit pre-fix state
- Phase 1 commit `b6f6400` self-contained, revertable
- Future phases recommend per-phase tags for granular rollback
- Test infrastructure `test_math_correctness.py` documents current behavior — failures after future fixes signal explicit migration decision needed

---

## Related Sessions

- `2026-04-25-0530-output-quality-stage-c-complete-plus-audit.md` — predecessor (output quality v1.0.12.5)
- `2026-04-25-0012-output-quality-stage-abc.md` — output quality Stage A+B+C earlier session

## Related Memory

- `project_econometrica_math_audit.md` — AUDIT COMPLETE status
- `project_econometrica_hill_normalization_root_fix.md` — primary P0 fix (Phase 2 target)
- `project_econometrica_decomposer_rewrite.md` — NEW P0 task (Phase 3 target)
- `project_econometrica_reconstruction_fix.md` — NEW P0 task (Phase 1 DONE)
- `project_econometrica_optimizer_rescale.md` — NEW P0 task (Phase 4 target)
- `feedback_shared_helpers_prevent_drift.md` — directly applicable to Hill drift

## Git State

- Branch: master
- HEAD: `b6f6400` (Phase 1 done)
- Tags this session: `v1.0.12-math-audit-done` (after R5)
- 7 commits ahead of `v1.0.12.5`: audit R1-R5 + fix plan + Phase 1
- Working tree: clean
