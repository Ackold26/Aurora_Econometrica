# v1.0.16 Days Progress Tracker

**Branch:** `math-fix-v1.0.13` | **Started:** 2026-04-29 | **Mode:** autonomous

---

## Current Task

**Day 4 — Settings + L9 quick disable + MQS (L9, L18-L20, L16, L3)** — pending

L9 disable «Фиксировать бюджет» checkbox + tooltip + budget_mode forward-compat
L18-L20 Settings page cleanup (remove license file block, rename, remove version content)
L16 MQS labels mismatch backend single source
L3 Slider 0₽ preview fix per-channel range

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

- ✅ **Day 3 — Narrative cluster** — pending push (single commit, 6 findings closed)
  - L15 cut_source/scale_destination — narrative_adapter._derive_narrative_facts adds new fields, sections.py + builder.py use action-driven subjects вместо leader/hero. Real Kagocel verification: cut_source=TRPs (correct overspender), scale_destination=Performance.
  - L14 budget_dominator — separate field from contribution leader. complication template now reads «{TRPs} занимает 92.3% бюджета, но даёт 10.5% эффекта» (honest contradiction framing). Fallback template для balanced portfolios.
  - L11 channel name normalization — display_name field added к decomposer + optimizer ch_dict (calls _normalize_channel_name). ReportStep.svelte interpretation block uses dispName(c) helper.
  - L12 channels_by_action['Scale']/Cut full lists — removed `[:2]` slice in sections.py action_03 + builder.py action_03. Customer sees full picture (5 каналов на Kagocel вместо 2).
  - L13 grammar — Russian period plural form (1 период / 2-4 периода / 5+ периодов с правильными edge cases для 21/31). MAPE «менее 10%» вместо «меньше десятой части».
  - L2 verdict CI re-ordering — wide-CI suffix «(низкая уверенность)» appended к existing verdict вместо suppressing к 'Высокая неопределённость'. Customer sees descriptive label AND uncertainty disclosure.
  - Tests: 37/37 roi_verdict (was 36 + 1 new), 552+/552+ across full suite

- ✅ **Day 2 — L1 Validate state sync** — pending push (single commit + 17 vitest lock-ins)
  - Rust schema migration: `ProjectInfo.excluded_columns: Vec<String>` (`#[serde(default)]` для backward compat)
  - New `src/lib/column-roles.js` shared utility (ROLES, isExcluded, setColumnRole, setColumnRolesBulk, applyMapping, deriveMapping, deriveExcludedColumns, restoreExcludedColumns, buildProjectUpdates)
  - Refactored InsightsPanel.applyAction + ValidateStep.excludeColumnByName + onMappingChange to use shared helper (vocabulary consistency)
  - Persistence: project.json gains `excluded_columns` field saved on every role change
  - Restore: ValidateStep.runValidate fetches project_get → restoreExcludedColumns to preserve user's «не использовать» across re-validation
  - Tests: 31/31 vitest PASS (14 pre-existing + 17 new L1 lock-ins, 3-mutator-path consistency verified)

---

## Next (concrete first step)

Read `src/lib/components/pipeline/OptimizeStep.svelte` line ~905 (Фиксировать бюджет checkbox). Disable input + add tooltip «Запланировано в v1.1». Add forward-compat `budget_mode: Literal['fixed'] = 'fixed'` field в OptimizeRequest (Pydantic, sidecar/econometrica/server.py).

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
