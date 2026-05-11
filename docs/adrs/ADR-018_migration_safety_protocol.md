# ADR-018: Migration Safety Protocol для Bundle Schema Bumps

**Status:** Accepted
**Date:** 2026-05-12
**Owner:** Маша маленькая (review Антон)
**Related:** ADR-017

## Context

В v1.3.0 schema bump → не нужен (per ADR-017). Но в Phase B (Platform Core migration) или будущих major releases structural changes неизбежны. Нужен **стандартный protocol** для безопасной migration .aurora bundles.

Известные риски destructive migration:
- Migration tool ломает bundle → data loss (unrecoverable если нет backup).
- Migration tool работает correctly но computes slightly different decompose/forward → клиент видит изменения и не понимает почему.
- Migration tool полу-успешен → bundle в inconsistent state.

## Decision

**Standard Migration Safety Protocol** для всех future bundle schema bumps:

### 1. Shadow-mode default

Migration tool работает в `--shadow-mode` (default):
1. Load old version bundle (read-only).
2. Save в parallel new version file: `bundle.v{NEW}.aurora`.
3. Re-run pipeline (model load → decompose → forward optimize) на new format.
4. Compute hash/checksum результатов decompose+optimize.
5. Compare с original → must match within `tolerance=1e-6`.
6. **Не trogать** оригинал. Юзер сам решает когда переключиться.

### 2. Auto-backup

При apply mode (`--apply`):
1. Сначала save backup: `bundle.aurora.bak.v{OLD}-{timestamp}`.
2. Запустить shadow-mode сначала + проверка match.
3. Если match — replace original. Если no match — abort + сохранить shadow для inspection.
4. Backup сохраняется минимум 30 дней.

### 3. Rollback

CLI флаг `--rollback` восстанавливает из backup:
```
tools/migrate_v??_to_v??.py rollback --bundle path/to/bundle.aurora
```
Выбирает самый свежий backup автоматически или указанный через `--backup-file`.

### 4. Dry-run

`--dry-run` reports what would be changed без apply.

### 5. Batch mode safety

`--batch` для миграции папки bundles:
- Каждый bundle обрабатывается independently (один failure не блокирует остальные).
- Summary report в конце: success/failed/skipped с reason per file.
- Прерывание (Ctrl-C) safely завершает текущий, не оставляет partial state.

### 6. Bundle integrity check на load

В `persistence.py::load_model_with_compat()`:
- Validate model_version присутствует.
- Validate required fields (kpi_column, media_columns) присутствуют.
- Sanity check значений (positive arrays where expected, no NaN в коэффициентах).
- Если broken — return `LoadResult(success=False, recovery_options=['restore_from_backup', 'reimport_data'])`.

### 7. History folder

`bundle.aurora.history/` (sibling папка):
- Хранит автоматические versioned snapshots (до 10 версий, configurable).
- `bundle.aurora.history/{timestamp}.aurora`.
- Создаётся автоматически перед save (rolling).
- Не пакуется в primary bundle (избегаем infinite size growth).

### 8. User-facing recovery UI

В Settings → «Резервные копии проекта»:
- List of all backups для текущего проекта.
- Кнопка «Восстановить» per backup с preview даты + размера.
- Кнопка «Сравнить с текущей версией» (diff decompose/forward output).

## Rationale

**Shadow-mode default:**

Worst case scenario — migration breaks bundle (silent corruption). Без shadow юзер видит broken data только через несколько часов work и теряет всё. С shadow — оригинал нетронут, юзер видит broken shadow и может report bug.

**Auto-backup:**

Защита от «migration tool сработал correctly но recompute дал чуть-чуть разные числа» — клиент видит difference, может откатиться.

**Rollback CLI:**

Без rollback option migration становится lock-in решением.

**Bundle integrity check:**

Catches corruption (disk errors, partial writes) до того, как broken bundle prосочится в downstream code paths.

**History folder:**

Защита от accidental overwrite (юзер случайно сохранил wrong values).

## Alternatives Considered

| Альтернатива | Отвергнуто потому что |
|---|---|
| Direct destructive migration (текущий стандарт) | Нет recovery; high risk |
| Shadow-only (без auto-backup) | Если оригинал случайно перезаписался — нет recovery |
| Auto-backup без shadow | Юзер не знает что migration produced different results до compare backup |
| Git versioning bundle | Bundle binary, git не оптимален |

## Consequences

**Positive:**
- Невозможно потерять данные через migration tool.
- Юзер всегда имеет recovery option.
- Bundle integrity issues catches раньше.

**Negative:**
- Дополнительный disk space для backups (~2× bundle size с history).
- Migration время x1.5-2 (shadow + compare).

**Neutral:**
- Применяется только при schema bumps. Regular save/load не affected.

## Implementation

**Применяется в v1.3.0 → НЕТ** (per ADR-017 — schema bump не нужен).

**Apply в первом будущем major release** (Phase B / v2.0):
- Создать `tools/migrate_v13_to_v20.py` (когда понадобится) по этому protocol.
- `sidecar/econometrica/engines/persistence.py::save_bundle()` — добавить auto-backup history folder rotation.
- `sidecar/econometrica/engines/persistence.py::load_model_with_compat()` — добавить integrity check.
- `src/lib/components/Settings/BackupRecovery.svelte` (NEW в Phase B) — UI.

**В v1.3.0** — реализуется только:
- Auto-backup history folder rotation в `save_bundle()` (защита от accidental overwrite).
- Bundle integrity check в `load_model_with_compat()`.

Остальное — Phase B deliverable.

## References

- Standard backup patterns (Apple Time Machine, git working tree).
- Aurora ADR-017 (Bundle schema v1.3 additive).
- Future Phase B Platform Core migration plan.
