# v1.0.16 Days Progress Tracker

**Branch:** `math-fix-v1.0.13` | **Started:** 2026-04-29 | **Mode:** autonomous

---

## Current Task

**Day 3 — Narrative cluster (L15, L14, L11, L12, L13, L2)** — pending

L15 SCQAR Answer/Action 01 inverted (cut_source / scale_destination)
L14 «Performance доминирует бюджет» (budget_dominator separate from leader)
L11 Channel name normalization в interpretation
L12 channels_by_action['Scale'] full list (not top-2)
L13 grammar fixes
L2 Decomposer descriptive verdict CI re-ordering

---

## Done

- ✅ **Day 0 (L10 critical regression)** — `00be01b` — pre-Day 1 fix
- ✅ **Day 1 — Optimize page UX cluster** — `8dca35c..c7b2dbc` (6 commits, 6 findings + audit hardening)
  - L4 three-way alignment decompose↔optimize↔narrative (mroi_current + action fields)
  - L5 auto-apply optimal к sliders + KPI live + Response Curves markers
  - L7 edge-case banners (baseline_zero / binding_constraints / converged_at_current)
  - L8 per-channel override warning
  - L21 backlog entry (lift_pct=None)
  - Audit-fix: legacy action migration, delta persistence, NaN guards, reasoning tooltip
  - Tests: 552/552 PASS (was 544 + 8 L4 lock-ins)

- ✅ **Day 2 — L1 Validate state sync** — pending push (single commit + 17 vitest lock-ins)
  - Rust schema migration: `ProjectInfo.excluded_columns: Vec<String>` (`#[serde(default)]` для backward compat)
  - New `src/lib/column-roles.js` shared utility (ROLES, isExcluded, setColumnRole, setColumnRolesBulk, applyMapping, deriveMapping, deriveExcludedColumns, restoreExcludedColumns, buildProjectUpdates)
  - Refactored InsightsPanel.applyAction + ValidateStep.excludeColumnByName + onMappingChange to use shared helper (vocabulary consistency)
  - Persistence: project.json gains `excluded_columns` field saved on every role change
  - Restore: ValidateStep.runValidate fetches project_get → restoreExcludedColumns to preserve user's «не использовать» across re-validation
  - Tests: 31/31 vitest PASS (14 pre-existing + 17 new L1 lock-ins, 3-mutator-path consistency verified)

---

## Next (concrete first step)

Read `sidecar/econometrica/engines/narrative_adapter.py` + `aurora_html/strings_ru.json` to identify L15 SCQAR Answer/Action 01 templates. Add `cut_source` and `scale_destination` to `_derive_narrative_facts` (currently uses `leader=top_contribution_channel` which can be small-budget Performance, not actual overspender like TRPs). Update HTML/PPTX templates to use new placeholders.

---

## Decisions log

- **2026-04-29 Day 1 verification:** Option D chosen для L4 (backend extends decompose to provide single-source-of-truth mROAS, NOT JS reimplementation). Mathematical identity vs duplication.
- **2026-04-29 Day 1 trade-off:** Live mROAS recomputation на slider drag отключена (была мат. broken — mixed units). Snapshot at last computed state. KPI prognosis remains live через separate `predictKPI`.
- **2026-04-29 Day 1 audit:** Legacy action vocabulary migration map в frontend (Russian primitive → ACTION_KEYS) — backward compat для projects saved on v1.0.15.
- **2026-04-29 Day 1 SA13 acknowledgment:** Lock-in tests невозможны для UI flows без Svelte e2e infra. Manual QA в release checklist для v1.0.16. e2e harness → v1.1 backlog.

---

## Day plan summary (per NEXT_SESSION_PROMPT_v1.0.16.md)

| Day | Findings | Hours | Status |
|-----|----------|-------|--------|
| 1 | L4, L5, L7, L8 + L10 (already done) | ~12h | ✅ DONE |
| 2 | L1 | 8-10h | ⏳ in progress |
| 3 | L15, L14, L11, L12, L13, L2 | ~9h | pending |
| 4 | L9 (quick disable), L18-L20, L16, L3 | ~7h | pending |
| 5 | Help docs (methodology.html, econometrica.html, index.html) | ~3h | pending |
| 6 | Sidecar rebuild + NSIS + ship (gh release + Supabase + PASHE_IT.MD) | ~3h | pending |

**Total estimated remaining:** ~30-32h.

---

## Push/commit policy (autonomous mode)

- Auto-commit local (no confirmation)
- Push к remote (origin/math-fix-v1.0.13) — show diff first → wait approval
- Architecture decisions / schema migration / push — questions to user
- Other decisions — proceed independently

## Compress recovery protocol

If session compressed (only summary visible):
1. Read this DAYS_PROGRESS.md first
2. Continue from "Next (concrete first step)" without confirmation
3. Update "Done" + "Next" after each commit
