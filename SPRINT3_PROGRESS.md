# Sprint 3 Progress — Pharma Causal + D/MIN-LIVE Validation Gates

**Branch:** `math-fix-v1.0.13`
**Started:** 2026-04-27 (this session)
**Mode:** Autonomous — Маша работает без per-step confirmation. Вопросы только: architecture decisions / push to remote / schema migration.

---

## Current task

**Step D — Independent math review (3-5h time-box)**

Fresh-context skeptic review кода без чтения SPRINT*_PROGRESS / ADR (те написаны same blind-spot session).

Critical questions из прошлой сессии:
1. Phase 1.1 in-model `adstock_full.mean()` vs persistence as Deterministic — actually consistent? Test by hand n=10 toy.
2. Bootstrap real per-period — `sat.sum() * y_std` correctly matches decomposer? Verify by hand.
3. Conformal jackknife+ formula `(n+1)(1-α)/n` vs `(n+1)(1-α)/(n+1)` per Lei et al. 2018 §4.2.
4. HDI on bootstrap distribution — overshoot когда multi-modal?
5. Untrained channel × posterior_samples interaction в decomposer.

Goal: ≥3 hidden bugs/inconsistencies. Если zero — дальше копать.

---

## Done

- [x] 2026-04-27 — Read NEXT_SESSION_PROMPT.md, plan acknowledged
- [x] 2026-04-27 — Saved feedback memory: autonomous mode для Econometrica
- [x] 2026-04-27 — Verified baseline: HEAD 92108dc, working tree clean, branch math-fix-v1.0.13
- [x] 2026-04-27 — Created SPRINT3_PROGRESS.md (this file)

---

## Next concrete first step

1. Run baseline tests (330 PASS check) в parallel с D
2. Read `engines/modeler.py` (Phase 1.1 hierarchical adstock + scan logic) — code only, no docs
3. Read `engines/decomposer.py` (CI propagation + adstock_mean_posterior)
4. Read `engines/optimizer.py` (_compute_mroas_money + samples variant)
5. Read `utils/posterior_propagation.py` + `utils/ols_bootstrap.py` + `utils/conformal.py`
6. Document findings в этом файле (секция "D Findings") с code refs file:line
7. Surface ≥3 issues → discuss with Антон → decide which fix before MIN-LIVE

---

## Decisions log

| Date | Decision | Why |
|------|----------|-----|
| 2026-04-27 | Trust gate sequence D → MIN-LIVE → B | Previous session blind-spot: same Claude wrote + audited; C1/C-OLS-1 class bugs caught only post-hoc. Fresh context = independent reviewer. |
| 2026-04-27 | Autonomous mode in-session | Антон mandate — backend velocity не должна стопориться. Vопросы только по 3 темам. |
| 2026-04-27 | NOT reading SPRINT*_PROGRESS / ADR before D | Risk absorbing same blind spot patterns. Code-first review. |

---

## D Findings

_(populated as review proceeds)_

---

## MIN-LIVE Findings

_(populated после D done)_

---

## Sprint 3 Pharma Causal

_(populated после MIN-LIVE PASS)_

**Stack:** linearmodels (DiD Callaway-Sant'Anna) + econml (Causal Forest Wager-Athey) + pysyncon (SCM Abadie) + statsmodels base.

**ADR §1 must declare "EXTEND, not rewrite"** — pin existing FastAPI shape so MIN-LIVE coverage stays valid.

**Pre-Ship gate before v1.0.14:** SBC overnight + UI live-test on Kagocel + Materia Medica geo-data.
