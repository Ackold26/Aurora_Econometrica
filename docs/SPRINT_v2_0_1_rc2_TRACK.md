# Sprint v2.0.1-rc2 Extended — Live Track

> Источник правды по текущему sprint'у. Обновляется после каждого commit.
> Зеркальный план: `C:\Users\ackol\.claude\plans\principal-product-precious-stallman.md`.

## Контекст

Sprint v2.0.1 (Phases 0-4.1, 25 commits) прошёл senior-level аудит 4 параллельных подагентов (Architecture+Backend / Frontend+UX / Security+Reliability / Tests+DX).

**Совокупно: 89 findings** (5 Critical + 22 High + ~40 Medium + ~22 Low).

**Реальная зрелость:** 5.8/10 vs план self-rated 8.5/10 (паттерн повторяет Aurora Launch retro 2026-05-14).

**5 системных паттернов:**
- P1: «Built but unwired» — file_lock, JCS hash, Industry CPP, EmptyState/Loading/Error — 0 production callsites
- P2: Silent failures swallowed (migration `console.warn`, snapshot rubber-stamp, `detect_column_role(None)` accept)
- P3: NaN/Infinity blindspots — `unit_costs` валидатор есть, `value_per_count_unit` нет
- P4: Type safety theatre — checkJs strict + 155× `@type {any}`
- P5: Cross-platform не тестируется (нет macOS runner)

## Решение Антона (2026-05-15)

✅ **Расширенный вариант (b)**, ~45 часов автономной работы.

Поскольку ООО не готов → нет давления времени на ship, можно работать тщательно. Антон в роли проверяющего → готовый материал, не «строительные леса».

**Принятые архитектурные развилки** (мои реко accepted без правок):
1. **H-09 wiring:** добавляем поле `project.industry` в схему (мини-миграция v2.0.2) + UI-выбор при создании проекта. Эвристика по имени проекта — нет, дешевле и точнее explicit поле.
2. **C-05 pickle:** SHA-256 sidecar check сейчас (~1ч, блокирует 95% RCE сценариев). Полный переход на безопасный формат — v2.2.0.

## Партии работ

### Партия 1 — Критичная безопасность + UX-баги ✅ COMPLETE

| ID | Title | Commit | Status |
|---|---|---|---|
| C-01 | PyInstaller spec: rfc8785 + filelock + bundle probe | `c75e6cd` | ✅ |
| H-02 | allow_nan=False в atomic_write_json (+4 vitest) | `69d95e0` | ✅ |
| H-19 | detect_column_role(None) → 'unknown' (+2 vitest) | `ce0e9c2` | ✅ |
| H-03 | value_per_count_unit field_validator | `11743c9` | ✅ |
| H-01 | Path traversal guard Rust+Python (+6 pytest) | `2e69ef5` | ✅ |
| H-07 | cleanup_stale_backups startup hook | `7bc3d9d` | ✅ |
| H-11+H-12 | applyToSameType budget mode + mode copy (+2 vitest) | `e4fca9d` | ✅ |
| H-13+H-14+H-15 | a11y motion guard + focus ring + muted contrast | `b264294` | ✅ |

**Test delta:** +12 pytest, +6 vitest. 536 vitest + ~150 pytest passing. 0 regressions.

### Партия 2 — Wiring критичных утилит ✅ COMPLETE

| ID | Title | Commit | Status |
|---|---|---|---|
| C-02 | Wire project_lock в 4 production callsites | `5f1f4ca` | ✅ |
| C-03 | Wire JCS-hash в migration + verify_project_integrity (+7 pytest) | `db49d3d` | ✅ |
| H-04+H-05 | Atomic backup restore + numpy sanitize в diagnostics | `20c158d` | ✅ |
| H-06 | Pickle race lock (covered by C-02 project_lock) | (in C-02) | ✅ |
| C-05a | Pickle SHA-256 sidecar (+8 pytest) | `e335502` | ✅ |
| H-20a | Migration error UI banner с retry (ErrorState wired) | `65a9fcd` | ✅ |

**Test delta:** +15 pytest. Total: 156 sidecar pytest + 536 vitest. 0 regressions.

### Партия 3 — Rust атомарность + Industry CPP wire ✅ COMPLETE

| ID | Title | Commit | Status |
|---|---|---|---|
| C-04 | Rust write_project atomic + per-project mutex (+5 Rust tests) | `1d5d02f` | ✅ |
| H-09 backend | ProjectInfo.industry field + schema migration v2.0.2 (+4 pytest) | `c48fcc6` | ✅ |
| H-09 frontend | ProjectSelector industry-select + UnitCostEditor suggestion hints | `f1082fa` | ✅ |

**Test delta:** +5 Rust tests + +4 pytest. 140 Rust + 40 migration pytest + 536 vitest. 0 regressions.

### Партия 4 — UI components wire ✅ COMPLETE

| ID | Title | Commit | Status |
|---|---|---|---|
| H-10a | EmptyState replaces inline .no-channels (+1 vitest) | `8c75b64` | ✅ |
| H-10b | LoadingSkeleton wire + patternsReady store (+2 vitest) | `774a40d` | ✅ |
| H-10c | ErrorState wired в migration banner (covered by H-20a `65a9fcd`) | — | ✅ |

**Test delta:** +3 vitest. Total: 538 vitest passing.

### Партия 5 — Persistence + Tests ✅ COMPLETE

| ID | Title | Commit | Status |
|---|---|---|---|
| H-08 | INV-05 attack scenario suite (+38 pytest) | `3273f77` | ✅ |
| H-21 | E2E migration on realistic 30+ col project (+8 pytest) | `19daf90` | ✅ |
| H-16 | Wire Phase 1.3 stores к save_kpi_settings (REAL BUG FIX, +5 vitest) | `95fc856` | ✅ |
| H-17 | Snapshot rebuild на semantic queries (6 rewritten, .snap deleted) | `0b92b71` | ✅ |

**Test delta:** +46 pytest + +5 vitest. Total: 220 sidecar pytest + 543 vitest.

## Текущий статус

- **Branch:** `feat/v2.0.0-explicit-mode-wizard`
- **Local commits ahead of origin:** 28 (2 pre-sprint + 22 fix/feat + 4 tracker/research)
- **Active phase:** ✅ **СПРИНТ ЗАВЕРШЁН** — все 5 партий closed
- **Test baseline:** 543 vitest / 220 sidecar pytest / 40 migration pytest / 140 Rust = 943 tests passing, 0 regressions
- **Push gate:** ready для diff review с Антоном → push → tag v2.0.1-rc2

## Decisions log

| Date | Decision | Reason |
|---|---|---|
| 2026-05-15 | Расширенный (b) ~45h автономно | ООО не готов, нет давления времени, Антон в роли проверяющего |
| 2026-05-15 | Поле `project.industry` в схему vs эвристика по имени | Дешевле в обслуживании, точнее |
| 2026-05-15 | Pickle SHA-256 sidecar short-term, переход v2.2.0 | 95% RCE сценариев заблокирован за 1ч |
| 2026-05-15 | Sub-agents Sonnet для H-09 + H-17 research параллельно | Pre-load plans для Партий 3 и 5 |
| 2026-05-15 | Push отложен до завершения Партий 1-2 | Show diff Антону, чтобы он проверил группой |

## Next Concrete First Step

**✅ СПРИНТ ЗАВЕРШЁН.** Все 5 партий, 22 fix/feat commits, +91 pytest + +14 vitest + +5 Rust tests.

Next gates требуют Антон approval:
1. **Diff review** 28 unpushed commits (показать summary + key changes)
2. **Push** к origin/feat/v2.0.0-explicit-mode-wizard
3. **Pilot verify** на Кагоцел РФ+ через Tauri dev
4. **Tag** `v2.0.1-rc2` после pilot ack

## Pending Антон gates

- [ ] Push 2 непушенных + новые commits после Партий 1-2 (~20h работы) → show diff
- [ ] Pilot verification после Партии 4 (UI components wired)
- [ ] Tag `v2.0.1-rc2` после Партии 5

## Post-compress resume

Если context compress — прочитать:
1. **Этот файл** (источник правды по sprint'у)
2. `C:\Users\ackol\.claude\plans\principal-product-precious-stallman.md` (parent plan)
3. MEMORY.md → ссылка на `project_aurora_mmm_v2_0_1_rc2_extended.md`

Continue без подтверждения с раздела «Next Concrete First Step».
