# Sprint 4+ Trust Level 3 — Brand vs Performance Split

**Started:** 2026-04-27
**Branch:** math-fix-v1.0.13
**Plan:** `C:\Users\ackol\.claude\plans\bright-jingling-pebble.md`
**Target ship:** v1.1.0 (architectural change — major bump)

---

## Current Status

**Phase:** A — Investigation
**In progress:** Setup status file + read current modeler state
**Blocking:** None
**Next concrete step:** Mock notebook tools/probe_hierarchical_split.py — synthetic test что NumPyro JAX hierarchical sampling сходится на 36×5 fixture

---

## Done

- [x] 2026-04-27 Plan approved (`bright-jingling-pebble.md`)
- [x] 2026-04-27 Audit добавлен в plan (24 issues найдено в code-trace)
- [x] 2026-04-27 Status file создан (`Sprint4_Trust_Level.md`)

---

## Decisions Log

### 2026-04-27 — Architectural

- **Brand adstock = stronger geometric, NOT weibull** (Critical Audit issue A). Weibull в-model = Phase 1.5 task, не bridge-able. Brand mu_logit ~ Normal(0.7, 0.3) → effective decay ≈ 0.67 ≈ 12 weeks half-life monthly data. Saves 10-15h.
- **Backend endpoint вместо JS port** (issue H) — `POST /utils/auto_suggest_categories`. Single source of truth = Python.
- **Optimizer untouched** (issue Q) — already correct via posterior chain rule.
- **Identifiability fallback** (issue B) — N<2 в группе → канал demoted к mixed с UI warning.
- **Non-centered reparam betas обязателен** (issue C) — z-score pattern из Phase 1.1.
- **Pickle compat helper** (issue E) — `engines/persistence.py:load_model_with_compat`, все downstream consumers через него.

### 2026-04-27 — Versioning

- **v1.1.0 major bump** (architectural change, new schema). НЕ patch.
- Mixed category = fallback к single prior path (current behavior preserved).

---

## Next steps queue

1. Phase A — investigation: probe hierarchical NumPyro JAX
2. Phase B — failing tests first (13 split + 10 categorization + compat + prior predictive + validation set)
3. Phase C — backend implementation (channel_categorization util + persistence helper + modeler hierarchical + decomposer compat + server endpoint)
4. Phase D — frontend (project.rs schema + ValidateStep badges + DecomposeStep grouping + Report integration)
5. Phase E — multi-client validation (Kagocel + Венарус + edge cases)
6. Phase F — documentation (math audit auto-gen + CHANGELOG + Help)
7. Phase G — ship (alpha gate + NSIS + GH Release + rosst-updates + Supabase)

---

## Commits

(empty — about to start)
