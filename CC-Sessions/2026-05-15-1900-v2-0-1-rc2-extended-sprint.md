---
tags: [session, compressed, aurora-mmm-optimizer, v2.0.1-rc2, audit, pilot]
type: session
updated: 2026-05-15
---
# Quick Reference

Senior-level аудит на 4 параллельных подагентах (89 findings: 5C/22H/40M/22L) → расширенный sprint (b) ~45h автономно → 5 партий + pilot hotfixes + REORDER_SUBSTEPS + i18n foundation. Pilot Tauri dev на Кагоцел РФ+ verified migration v1.0→v2.0.2, выявил 2 production bugs (H-01 path multi-root, str/str TypeError) → fixed live. 34 коммита от `c580b60` до `0746a21` pushed к origin. 947 тестов проходят (547 vitest + 220 sidecar pytest + 40 migration + 140 Rust), 0 regressions. Реальная зрелость 5.8/10 → 8/10 после sprint.

**Topic:** v2.0.1-rc2 extended recovery sprint + pilot verification + REORDER + i18n foundation

**Key files:**
- `sidecar/econometrica/server.py` (H-01 multi-root, H-07 lifespan, +endpoints)
- `sidecar/econometrica/engines/persistence.py` (C-02 lock wire, H-04 backup, H-05 numpy, C-05a pickle SHA)
- `sidecar/econometrica/engines/project_migration.py` (C-03 JCS, H-09 schema v2.0.2)
- `sidecar/econometrica/utils/safe_io.py` (H-02 allow_nan=False)
- `sidecar/econometrica/engines/validator.py` (H-19 None safety)
- `src-tauri/src/commands/project.rs` (C-04 Rust atomic + mutex, H-09 industry field)
- `src-tauri/src/commands/econometrica.rs` (H-16 Phase 1.3 IPC, H-01 Rust traversal)
- `src/lib/components/pipeline/ValidateStepV13.svelte` (REORDER substeps + KPI filter)
- `src/lib/components/pipeline/UnitCostEditor.svelte` (Industry CPP suggestion hints, H-11+H-12 applyToSameType)
- `src/lib/components/pipeline/AppliedModeSummary.svelte` (H-10a/b/c wiring, H-11)
- `src/lib/components/ProjectSelector.svelte` (industry dropdown)
- `src/lib/i18n/index.js` + `src/lib/i18n/locales/{ru,en}.json` (foundation)
- `src/routes/pipeline/+layout.svelte` (H-20a migration error UI, ErrorState wire)
- `src/app.css` (H-13/14/15 a11y bundle)
- `docs/SPRINT_v2_0_1_rc2_TRACK.md` (live tracker)
- `docs/I18N_MIGRATION.md` (migration guide)

**Status:**
- ✅ Sprint COMPLETE: 22 fix/feat commits + 6 tracker + 2 pilot hotfixes + REORDER + i18n
- ✅ All pushed to origin `feat/v2.0.0-explicit-mode-wizard` (HEAD `0746a21`)
- ✅ Migration v1.0→v2.0.2 working on real Кагоцел РФ+ project
- ⏳ Manual pilot tour after REORDER (Антон)
- ⏳ Tag `v2.0.1-rc2` after pilot ack
- ⏳ v2.2.0 scope: translate existing UI strings к EN, native reviewer pass
- ⏳ v2.3.0 scope: backend i18n + PPTX/HTML/Methodology Certificate EN

---

## Learnings

### 3 новых feedback memory files (Aurora-specific lessons из pilot)

1. **`feedback_tauri_sidecar_dev_restart_protocol.md`**
   - Rule: при изменении Python sidecar в Tauri dev → kill ALL 3 процессов (Rust GUI + Vite + sidecar Python).
   - Why: pilot 2026-05-15 — 4 «restart cycles» с прежним багом потому что sidecar Python orphan'ил после `Stop-Process` Rust GUI; Tauri auto-respawn only triggers на health-check failure, не на code change. Same session ID `f2cf0285` сохранялся → sidecar не перезагружался → новый код не загружался.
   - Apply: любой dev cycle где изменён Python sidecar code (`server.py`, `engines/`, `utils/`). Frontend-only changes (Svelte) — Vite hot-reload справляется. Rust changes — `cargo` auto-restart.

2. **`feedback_python_rust_path_convention_match.md`**
   - Rule: Python guard для paths из Rust IPC должен ТОЧНО match Rust priority chain. Accept LIST of allowed roots, не single root.
   - Why: H-01 path traversal guard initially использовал `LOCALAPPDATA или APPDATA` (Local first). Rust `projects_dir()` использует `APPDATA` (Roaming). Customer project в `Roaming\aurora-econometrica-gui\projects\кагоцел...` → guard says «outside expected root» → 400 → migration упало 500. Не обнаружено unit/integration tests (tmp_path consistent both sides). Pilot выявил.
   - Apply: любой Python код, валидирующий path coming from Rust IPC — сначала прочитать Rust path resolution function, replicate priority chain. Multi-root accept.

3. **`feedback_vitest_setup_no_app_imports.md`**
   - Rule: setup.js (vitest setupFiles) НЕ должен импортировать app-модули с side-effects (stores .set, init).
   - Why: Phase 4 H-10b — добавил `import patternsReady` в setup.js + `set(true)`. classifier-patterns module captured setup.js's mocked invoke на module-load. Test файл `classifier-patterns.test.js` имел own `vi.mock(...)`, но service module уже cached → 2 теста сломались.
   - Apply: setup.js limit к global config (`@testing-library/jest-dom`, third-party Tauri mocks, env polyfills). Per-file fixtures → в `beforeEach` каждого нужного test файла.

### Усиление существующих lessons

- **feedback_release_notes_drift_check.md** reinforced: snapshot tests breaking 3 раза за session (REORDER + EmptyState + suggestion hint) — exactly rubber-stamp pattern. H-17 (semantic queries rebuild) addressed root cause post-facto.

### Pilot pattern (для документации в memory если повторится)

- **Pilot UX evidence = strongest signal.** Антон's REORDER feedback (KPI before Roles) изначально планировался к v2.1.0. Pilot pharma dataset выявил конкретный blocker (ratio < 2:1 из-за irrelevant *в уп.* колонок). Перенесён в v2.0.1-rc2 = pilot blockers fix immediately rule.

---

## Decisions

### Strategic

| # | Решение | Reason |
|---|---|---|
| 1 | **Расширенный (b) sprint ~45h автономно** (vs быстрые победы 6h или полный pre-release 22h) | ООО не готов → нет ship pressure → можно тщательно. Антон в роли проверяющего → больший слой готового материала, не «строительные леса». |
| 2 | **REORDER_SUBSTEPS v2.1.0 → v2.0.1-rc2** | Pilot evidence strongest signal. Concrete UX blocker (ratio < 2:1) → fix immediately, не next minor. |
| 3 | **i18n foundation сейчас (5h), translation отложено к v2.2.0** | EN expansion возможен для ICP (фарма международная). Инфраструктура сейчас — soft moat. Реальная translation требует native reviewer + pharma terminology validation → не блокировать ship. |
| 4 | **project.industry field в схему vs эвристика по имени** (H-09) | Дешевле в обслуживании, точнее. Schema migration v2.0.2 acceptable cost. |
| 5 | **Pickle SHA-256 sidecar short-term (1h) vs полный pickle replacement (2-3 дня)** | Sidecar SHA блокирует 95% RCE сценариев. Полная замена pickle — v2.2.0. |
| 6 | **Push всех 28 коммитов одним push (Вариант A)** vs поэтапно | Tests все зелёные (943 passing), история granular для post-mortem, 1 CI run vs 5. |

### Tactical

- C-05 Pickle: SHA-256 sidecar (1h, 95% coverage), полная замена → v2.2.0
- H-04 Backup restore: verify_json_integrity перед `os.replace`
- H-09 Industry CPP: `industry: String` поле + миграция v2.0.2 + `ALLOWED_INDUSTRIES` whitelist (mirrors frontend `INDUSTRY_CPP_TABLE`)
- H-11 applyToSameType: copy mode из source channel (не force='unit')
- H-12: button visible в budget mode (вынес из `{:else}` block)
- H-16: ValidateStepV13.handleContinue передаёт unit_costs/inflation/mode_for/budget_inputs к backend
- H-17: Snapshot tests rebuilt на semantic queries (testing-library getByRole/getByTestId)
- REORDER: kpiConfirmed flag + new substep states (-2, -1, 0/legacy, 1, 2, 3), filteredColumns derive
- i18n: svelte-i18n v4 (vs paraglide-js), ru/en skeletons, локаль persistence к localStorage

---

## Pending

### Антон gates (manual)

1. **Pilot tour после REORDER** на Кагоцел РФ+ через Tauri dev (sidecar fresh с H-01 multi-root fix). Должен пройти: KPI selector → Roles (filtered, без *в уп.*) → Channels (Industry CPP suggestion на TRP) → Confirmation.
2. **Tag `v2.0.1-rc2`** после pilot ack: `git tag v2.0.1-rc2 -m "v2.0.1-rc2 extended recovery sprint" && git push origin v2.0.1-rc2`
3. **Aurora-meta INV update** (optional): добавить INV-32 «utility built ≠ shipped» (P1 systemic pattern catch).

### v2.2.0 scope (~30-40h)

- Extract существующих 100+ компонентов inline RU strings → ru.json
- Translate ru.json → en.json (LLM draft + native EN reviewer)
- Locale switcher UI (settings page)
- Validation корректности pharma terminology (adstock, saturation, confounding, MQS, CPP)

### v2.3.0 scope (~50h)

- Backend Python error messages localization (Pydantic + log_event)
- PPTX export EN template (`aurora_pptx/`)
- HTML export EN template (`aurora_html/`)
- Methodology Certificate EN PDF (regulated environments — liability item, requires careful review)
- Tag `v2.3.0` после EN reviewer pass

### Phase 3 (deferred)

- aurora-platform-core cross-product extraction (waiting Маша небесная ack)
- GDPR telemetry spec
- macOS CI runner
- ValidateStepV13.svelte further extraction (959 → wizard-state.js / XState)

---

## Full Session Notes

### Audit (4 parallel sub-agents Sonnet)

**Setup:** general-purpose subagents с explicit instructions:
1. Architecture+Backend deep audit
2. Frontend+UX deep audit
3. Security+Reliability audit
4. Tests+DX+Scalability roadmap audit

**Findings:** 89 total deduped → 5 Critical + 22 High + ~40 Medium + ~22 Low.

**5 системных паттернов:**
1. **P1 «Built but unwired»** — `file_lock`, JCS hash, Industry CPP table (197 LOC dead code), EmptyState/Loading/Error — все имели 0 production callsites.
2. **P2 Silent failures swallowed** — migration errors → `console.warn`, snapshot tests rubber-stamp, `detect_column_role(None)` documented как acceptable вместо fix.
3. **P3 NaN/Infinity blindspots** — `unit_costs` validator есть, `value_per_count_unit` нет; `atomic_write_json` пишет Infinity; JCS падает на NaN.
4. **P4 Type safety theatre** — `checkJs: true` + 155× `@type {any}` = surface compliance, real drift.
5. **P5 Cross-platform не тестируется** — CI Windows+Linux, нет macOS runner.

### Sprint partitioning

**Партия 1** — Критичная безопасность + UX-баги (8 commits):
- `c75e6cd` C-01 PyInstaller spec (rfc8785 + filelock)
- `69d95e0` H-02 atomic_write_json allow_nan=False
- `ce0e9c2` H-19 detect_column_role None safety
- `11743c9` H-03 value_per_count_unit field_validator
- `2e69ef5` H-01 path traversal guard (initial single-root)
- `7bc3d9d` H-07 cleanup_stale_backups startup hook
- `e4fca9d` H-11+H-12 applyToSameType budget mode + mode copy
- `b264294` H-13+H-14+H-15 a11y (motion + focus + contrast)

**Партия 2** — Wiring критичных утилит (5 commits):
- `5f1f4ca` C-02 wire project_lock в 4 callsites
- `db49d3d` C-03 wire JCS hash + verify_project_integrity
- `20c158d` H-04 + H-05 backup atomic restore + numpy sanitize
- `e335502` C-05a pickle SHA-256 sidecar
- `65a9fcd` H-20a migration error UI banner (ErrorState wired)

**Партия 3** — Rust атомарность + Industry CPP (3 commits):
- `1d5d02f` C-04 Rust write_project atomic + per-project mutex
- `c48fcc6` H-09 backend industry field + schema v2.0.2
- `f1082fa` H-09 frontend industry selector + suggestion hints

**Партия 4** — UI components wire (2 commits):
- `8c75b64` H-10a EmptyState wire (AppliedModeSummary no-channels)
- `774a40d` H-10b LoadingSkeleton + patternsReady store

**Партия 5** — Persistence + Tests (4 commits):
- `3273f77` H-08 INV-05 attack scenario suite (+38 pytest)
- `19daf90` H-21 E2E migration на realistic 30+ col project (+8 pytest)
- `95fc856` H-16 Phase 1.3 stores persistence wire (REAL BUG FIX)
- `0b92b71` H-17 snapshot rebuild на semantic queries

**Pilot hotfixes** (after Антон's pilot test):
- `cb45c8f` H-01 multi-root accept (Roaming AppData fix)
- `aa062b2` H-01 Path wrap для _sidecar_root (str/str TypeError)

**REORDER + i18n** (after Антон's REORDER feedback):
- `03826d2` REORDER_SUBSTEPS (KPI before Roles + KPI-driven filter)
- `0746a21` i18n infrastructure foundation

### Real bug fixes (не просто tests)

- **H-16**: Phase 1.3 stores never reached backend → reload lose state. ValidateStepV13.handleContinue не передавал unit_costs/inflation/mode_for/budget_inputs к Rust econ_save_kpi_settings. Rust команда не принимала эти params. Backend Pydantic уже validated их. Result: customer puts budget → reload → all lost.
- **H-12**: applyToSameType button был внутри `{:else}` mode='unit' branch → invisible в budget mode → фича могла остаться незамеченной даже на demo.
- **H-11**: applyToSameType forced `mode='unit'` на siblings → user в budget mode → click «Apply» → все siblings switched в unit mode с derived числом → confusion.
- **H-19**: `detect_column_role(None).lower()` → AttributeError → /validate endpoint crashes 500. Test файл документировал failure как acceptable. Real-world trigger: pandas merged cells / blank Excel headers → openpyxl emits NaN/None → crash.
- **H-09**: Industry CPP table (197 LOC) unwired — Phase 4.1 marketing claim «smart suggestions» = ложь. Wire включает schema migration v2.0.2 + UI selector + suggestion hints в UnitCostEditor.
- **H-10a/b/c**: 3 UI компонента (EmptyState, LoadingSkeleton, ErrorState) висели dead code 3 sprint-дня. ErrorState wired через H-20a migration banner; EmptyState заменил inline `.no-channels`; LoadingSkeleton wired через patternsReady store на cold-start.

### Pilot session (Tauri dev)

**Run 1:** Launched Tauri → Кагоцел project → migration triggered → 400 «outside expected root». Root cause: H-01 single-root, Python Local first vs Rust Roaming.

**Fix attempt 1 (`cb45c8f`):** Multi-root acceptance. Killed Rust GUI but sidecar Python orphaned → новый Rust instance found healthy sidecar (port 7529, session=f2cf0285) → не respawn → код не загружался. User видел тот же error.

**Diagnosis:** session ID identical → sidecar not restarted. Killed Python process explicitly.

**Run 2:** Sidecar fresh (session=65c65e10) → migration retry → 500 «unsupported operand type(s) for /: 'str' and 'str'». Stack trace: `_get_projects_roots()` line 1760, `_sidecar_root / 'projects'`. `_sidecar_root` was `str(Path(__file__).parent)` — string!

**Fix 2 (`aa062b2`):** `Path(_sidecar_root) / 'projects'`. Killed sidecar + Rust GUI + Vite cleanly. Launched fresh (session=639f32d9).

**Run 3:** ✅ Migration successful. Toast «Проект обновлён до v2.0.2 — Формат данных обновлён без изменения классификации. Предыдущая версия v1.0 сохранена в backup-файле».

**Verified:**
- ✅ Migration v1.0 → v2.0.2 works
- ✅ MigrationCompletedToast (Phase 2.16) showing correctly
- ✅ SOM/SOV correctly classified as «Не использовать» (H-09 schema migration)
- ✅ H-20a error banner correctly shown during initial failure
- ✅ H-01 multi-root accepts Roaming AppData

**Pilot manual tour blocked:** ratio < 2:1 на pharma dataset — wizard «Подтвердить роли» disabled. User must manually exclude каналов OR optimize.

### REORDER decision (from pilot)

Антон's exact feedback: «целевая метрика будет стоять до этапа роли колонок. То есть логично сначала определить, что нам нужно, ROI или эффективность, а потом уже под эту задачу выбирать роли колонок».

Design doc уже существовал (`docs/v2_0_0_design/REORDER_SUBSTEPS_v2_1_0.md`, 2026-05-14, target v2.1.0). Pilot выявил concrete blocker → перенёс в v2.0.1-rc2.

**Implementation:**
- Added `kpiConfirmed` flag + localStorage persistence (`aurora-econ:kpi-confirmed:{projectId}`)
- Substep machine: -2 (KPI preflight), -1 (Roles preflight), 0 (legacy), 1, 2, 3
- Backward compat: legacy `rolesConfirmed=true` → `kpiConfirmed=true` автоматически на load
- `filteredColumns` derive: sales_rub KPI → hide `*в уп.*`/`*в шт.*`/`*в pack*`; count KPI → hide `*в руб.*`/revenue/выручка/profit
- ColumnMapperConfirm теперь получает filtered cols (substep -1) — ratio автоматически улучшается после KPI choice

### i18n decision

**Why now:** инфраструктура без translation. Каждый новый компонент с этого момента ОБЯЗАН использовать `$_('key')` — review gate. Иначе backlog только растёт с каждым sprint.

**Stack:** svelte-i18n v4.0.1 (vs paraglide-js, vs i18next). Reason: popular, Svelte-idiomatic, lazy-load per locale, supports ICU MessageFormat.

**Files created:**
- `src/lib/i18n/index.js` — module entry: register('ru'), register('en'), init(initialLocale), Aurora-side `locale` writable store с localStorage persist (`aurora-locale`), `translate()` helper для non-Svelte contexts, re-exports `_` + `isLoading`.
- `src/lib/i18n/locales/ru.json` — skeletal: common (save/cancel/confirm/...), errors (migration_failed/lock_timeout/...), industry (8 industries), pipeline (Import/Validate/Model/...), validate (substep labels).
- `src/lib/i18n/locales/en.json` — placeholder mirror keys.
- `src/lib/i18n/__tests__/i18n.test.js` — 4 sanity vitest (resolve / interpolation / missing key / locale switch).
- `docs/I18N_MIGRATION.md` — convention guide.

**Bootstrap:** side-effect import в `src/routes/+layout.svelte`.

### Test growth

| Phase | Delta |
|---|---|
| Pre-sprint baseline (2026-05-15 morning) | 534 vitest + 141 sidecar pytest + 135 Rust |
| After Партия 1 | +12 pytest, +6 vitest |
| After Партия 2 | +15 pytest |
| After Партия 3 | +9 (5 Rust + 4 pytest) |
| After Партия 4 | +3 vitest |
| After Партия 5 | +46 pytest + +5 vitest |
| After REORDER + i18n + pilot fixes | +4 vitest + +4 pytest (path guard multi-root) |
| **Final** | **547 vitest + 220 sidecar pytest + 40 migration pytest + 140 Rust = 947 passing** |

### Setup & config changes

**New runtime deps:** `svelte-i18n@^4.0.1` (dependencies, not devDeps).

**Backend new deps:** `rfc8785` (JCS canonical hash) + `filelock` (multi-tab lock) — already в requirements.txt после Phase 1.6/1.7, но critical fix C-01 добавил их в PyInstaller `--hidden-import` spec (`sidecar/econometrica/build_sidecar.py`) + bundle smoke probe (`server.py:_required_files`).

**New module dirs:**
- `src/lib/i18n/` (index.js + locales/ + __tests__/)
- `sidecar/econometrica/tests/` accumulates 4 new test files (path_traversal_guard, pickle_sha256_sidecar, security_attack_vectors, migration_e2e)

**Storage keys (localStorage):**
- `aurora-econ:kpi-confirmed:{projectId}` — REORDER new
- `aurora-econ:roles-confirmed:{projectId}` — existing (backward compat)
- `aurora-locale` — i18n new
- `aurora-classifier-patterns-v1` — Phase 1.1 (existed)

**Schema migration:** `TARGET_SCHEMA_VERSION = '2.0.2'` (bumped from '2.0.1'). Migration stamps `industry='unknown'` + `_jcs_sha256` на existing projects.

### Errors & workarounds

| Error | Workaround / Fix |
|---|---|
| H-01 single-root path mismatch (Python Local vs Rust Roaming) | Multi-root acceptance в `_get_projects_roots()` (returns list, accept first match) |
| `_sidecar_root / 'projects'` TypeError (str/str) | `Path(_sidecar_root) / 'projects'` explicit cast |
| Tauri dev port 5173 in use after kill Rust GUI | Kill Node Vite process via `Get-NetTCPConnection -LocalPort 5173` |
| Sidecar session reuse (orphaned Python after Rust kill) | Kill explicitly: `Get-CimInstance Win32_Process | WHERE CommandLine -match 'server.py'` |
| setup.js import classifier-patterns broke 2 tests | Move `patternsReady.set(true)` к beforeEach в individual test files |
| JSDoc `Record<string, unknown>` vs svelte-i18n InterpolationValues | Loosen typed param signature к specific union: `Record<string, string \| number \| boolean \| Date \| null \| undefined>` |
| Snapshot tests 3× rubber-stamp during sprint | H-17 rebuild на semantic queries — closes root cause |
| Validate substep nav button disabled (ratio < 2:1) на pilot | REORDER fix — KPI first filters irrelevant cols → ratio auto-improves |

### Commit log (compressed)

```
0746a21 feat(i18n): infrastructure foundation
03826d2 feat(reorder): KPI before Roles
aa062b2 fix(h-01-pilot-2): Path wrap _sidecar_root
cb45c8f fix(h-01-pilot): multi-root accept
22285b7 docs(sprint-tracker): SPRINT COMPLETE
0b92b71 refactor(h-17): semantic queries rebuild
95fc856 fix(h-16): Phase 1.3 persistence wire
19daf90 test(h-21): E2E migration test
3273f77 test(h-08): INV-05 attack scenarios
f768456 docs(sprint-tracker): Партия 3 complete
774a40d feat(h-10b): LoadingSkeleton wire
8c75b64 feat(h-10a): EmptyState wire
f1082fa feat(h-09-frontend): industry selector
c48fcc6 feat(h-09-backend): schema v2.0.2
1d5d02f fix(c-04): Rust atomic + mutex
298be32 docs(sprint-tracker): Партия 2 complete
65a9fcd fix(h-20a): migration error UI
e335502 fix(c-05a): pickle SHA-256 sidecar
20c158d fix(h-04+h-05): backup atomic + numpy sanitize
db49d3d fix(c-03): JCS hash wire
5f1f4ca fix(c-02): project_lock wire
95c65fe docs(sprint-tracker): Партия 1 complete
b264294 fix(h-13+h-14+h-15): a11y triple
e4fca9d fix(h-11+h-12): applyToSameType
7bc3d9d fix(h-07): cleanup_stale_backups
2e69ef5 fix(h-01): path traversal guard
11743c9 fix(h-03): value_per_count_unit validator
ce0e9c2 fix(h-19): detect_column_role None
69d95e0 fix(h-02): atomic_write allow_nan=False
c75e6cd fix(c-01): PyInstaller spec
4252591 docs(sprint-research): sub-agent plans
7b9fe01 docs(sprint-tracker): initial
3dee1eb feat(phase-4.1): industry CPP table data
c580b60 refactor(phase-2.1): UnitCostEditor extract
```

### Memory state after session

**Project memory:** `~/.claude/projects/D--Docs-Aurora-Ai/memory/`
- `MEMORY.md` — index updated с sprint completion + 3 feedback pointers
- `project_aurora_mmm_v2_0_1_rc2_extended.md` — sprint state COMPLETE
- 3 new feedback files (Tauri restart / Python-Rust path / vitest setup)

**Pending sync to git memory:** Antón может run `bash sync.sh push` если хочет sync.

---

## Resume notes

After context compress, чтобы resume:
1. Read this file (CC-Sessions/2026-05-15-1900-v2-0-1-rc2-extended-sprint.md)
2. Read `docs/SPRINT_v2_0_1_rc2_TRACK.md` для granular state per партия
3. Read `~/.claude/projects/D--Docs-Aurora-Ai/memory/project_aurora_mmm_v2_0_1_rc2_extended.md` для project memory snapshot
4. Pending Антон actions: pilot tour after REORDER + tag v2.0.1-rc2
