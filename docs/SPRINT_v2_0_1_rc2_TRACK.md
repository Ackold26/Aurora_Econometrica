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

### Партия 2 — Wiring критичных утилит (~6-7ч) 🔄 В РАБОТЕ

| ID | Title | Effort | Status |
|---|---|---|---|
| C-02 | Wire `project_lock` в 4 callsites (save_kpi/migrate/save_v20/clear_cache) | 90min | ⏳ |
| C-03 | Wire JCS-hash в save/load `project.json` (`_jcs_sha256` field) | 90min | ⏳ |
| C-05a | Pickle SHA-256 sidecar check (`latest.pkl.sha256`) | 60min | ⏳ |
| H-04 | Backup restore: `os.replace` + checksum verify pre-restore | 60min | ⏳ |
| H-05 | Numpy types sanitize в `save_v20_diagnostics` | 60min | ⏳ |
| H-06 | Pickle race lock в `save_v20_diagnostics`/`clear_sensitivity_cache` | 60min | ⏳ |
| H-20a | Migration error surface к UI (не `console.warn`) | 30min | ⏳ |

### Партия 3 — Rust атомарность + Industry CPP wire (~10ч) ⏳ ИССЛЕДУЕТСЯ

| ID | Title | Effort | Status |
|---|---|---|---|
| C-04 | Rust `write_project` atomic + per-project mutex | 3h | ⏳ |
| H-09 | Wire `industry-cpp-defaults.js` к UnitCostEditor (поле industry + миграция + placeholder/tooltip) | 6h | 🔬 sub-agent research |

### Партия 4 — UI components wire (~8ч) ⏳ В ОЧЕРЕДИ

| ID | Title | Effort | Status |
|---|---|---|---|
| H-10a | EmptyState заменяет inline `.no-channels` в AppliedModeSummary | 1h | ⏳ |
| H-10b | LoadingSkeleton при `ensurePatternsLoaded` initial fetch | 3h | ⏳ |
| H-10c | ErrorState на sidecar 5xx в ValidateStepV13 | 4h | ⏳ |

### Партия 5 — Persistence + Tests (~14ч) ⏳ ИССЛЕДУЕТСЯ

| ID | Title | Effort | Status |
|---|---|---|---|
| H-16 | Verify `unit_cost_input_mode` + `budgetInputs` persistence end-to-end | 4h | ⏳ |
| H-17 | Snapshot tests rebuild на semantic queries + svelte-* serializer | 8h | 🔬 sub-agent research |
| H-21 | E2E migration test (pytest integration, не Tauri) | 6h | ⏳ |
| H-08 | Минимум 5 INV-05 attack-scenario тестов | 3h | ⏳ |

## Текущий статус

- **Branch:** `feat/v2.0.0-explicit-mode-wizard`
- **Local commits ahead of origin:** 12 (`c580b60` Phase 2.1, `3dee1eb` Phase 4.1, `7b9fe01` track, `4252591` research + 8 Партия-1 фиксов)
- **Sub-agents:** done (H-09 + H-17 research saved в docs/SPRINT_v2_0_1_rc2_subagent_research.md)
- **Active phase:** Партия 2 — wiring critical utilities
- **Plan status:** 🟢 APPROVED (расширенный b)
- **Test baseline:** 536 vitest / ~165 pytest passing, 0 regressions

## Decisions log

| Date | Decision | Reason |
|---|---|---|
| 2026-05-15 | Расширенный (b) ~45h автономно | ООО не готов, нет давления времени, Антон в роли проверяющего |
| 2026-05-15 | Поле `project.industry` в схему vs эвристика по имени | Дешевле в обслуживании, точнее |
| 2026-05-15 | Pickle SHA-256 sidecar short-term, переход v2.2.0 | 95% RCE сценариев заблокирован за 1ч |
| 2026-05-15 | Sub-agents Sonnet для H-09 + H-17 research параллельно | Pre-load plans для Партий 3 и 5 |
| 2026-05-15 | Push отложен до завершения Партий 1-2 | Show diff Антону, чтобы он проверил группой |

## Next Concrete First Step

**Партия 2, шаг 1 — C-02 wire `project_lock` в production callsites.**

Acceptance criteria:
- `with project_lock(project_dir):` обёрнут вокруг read-modify-write в 4 endpoint'ах:
  - `project_save_kpi_settings` (server.py:~2006)
  - `project_migrate_endpoint` (server.py:~604)
  - `save_v20_diagnostics` (persistence.py:~515)
  - `clear_sensitivity_cache` (persistence.py:~696)
- Regression test: 2 concurrent calls на same project — один блокирует другого
- Commit: `fix(c-02): wire project_lock to save/migrate/diagnostics endpoints`

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
