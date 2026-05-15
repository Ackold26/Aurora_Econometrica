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

### Партия 1 — Критичная безопасность + UX-баги (~4-5ч) ⏳ В ОЧЕРЕДИ

| ID | Title | Effort | Status |
|---|---|---|---|
| C-01 | PyInstaller spec: `rfc8785` + `filelock` + smoke probe | 10min | ⏳ |
| H-01 | Path traversal guard (Rust + Python) | 30min | ⏳ |
| H-02 | `allow_nan=False` в atomic_write_json | 10min | ⏳ |
| H-03 | `value_per_count_unit` field_validator (NaN/Inf/neg/>1e9) | 15min | ⏳ |
| H-07 | `cleanup_stale_backups` startup lifespan call | 15min | ⏳ |
| H-11 | applyToSameType копирует mode из source channel | 15min | ⏳ |
| H-12 | applyToSameType visible в budget mode | 60min | ⏳ |
| H-13 | `pulse-anim` в `@media (prefers-reduced-motion)` | 15min | ⏳ |
| H-14 | `:focus-visible` ring на custom buttons | 60min | ⏳ |
| H-15 | `--text-muted` ratio fix (3.8 → 4.5+) | 10min | ⏳ |
| H-19 | `detect_column_role(None)` fix + regression test | 30min | ⏳ |

### Партия 2 — Wiring критичных утилит (~6-7ч) ⏳ В ОЧЕРЕДИ

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
- **Local commits ahead of origin:** 2 (`c580b60` Phase 2.1, `3dee1eb` Phase 4.1)
- **Sub-agents running:** 2 (H-09 research, H-17 research)
- **Active phase:** Подготовка к Партии 1
- **Plan status:** 🟢 APPROVED (расширенный b)

## Decisions log

| Date | Decision | Reason |
|---|---|---|
| 2026-05-15 | Расширенный (b) ~45h автономно | ООО не готов, нет давления времени, Антон в роли проверяющего |
| 2026-05-15 | Поле `project.industry` в схему vs эвристика по имени | Дешевле в обслуживании, точнее |
| 2026-05-15 | Pickle SHA-256 sidecar short-term, переход v2.2.0 | 95% RCE сценариев заблокирован за 1ч |
| 2026-05-15 | Sub-agents Sonnet для H-09 + H-17 research параллельно | Pre-load plans для Партий 3 и 5 |
| 2026-05-15 | Push отложен до завершения Партий 1-2 | Show diff Антону, чтобы он проверил группой |

## Next Concrete First Step

**Партия 1, шаг 1 — C-01 PyInstaller spec.**

Acceptance criteria:
- `sidecar/econometrica/build_sidecar.py` содержит `--hidden-import=rfc8785 --collect-data=rfc8785 --hidden-import=filelock --collect-data=filelock`
- Startup bundle-check loop (`server.py:112-131`) пробует `import rfc8785` + `import filelock` + log warn если не находит
- Commit local (engineering-ledger): `fix(c-01): bundle rfc8785 + filelock in PyInstaller spec`

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
