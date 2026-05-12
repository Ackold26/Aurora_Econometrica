# ADR-017: Bundle Schema v1.3 (Additive Fields, без Schema Bump)

**Status:** Accepted
**Date:** 2026-05-12
**Owner:** Маша маленькая (review Антон)
**Related:** ADR-015, ADR-016, ADR-018

## Context

В v1.3.0 нужно сохранить новые per-project поля:
- `kpi_kind`: monetary | count | proportional.
- `per_channel_input`: dict {channel: 'monetary'|'physical'}.
- `derived_mode`: cached 'roi'|'effectiveness'|'manual'.
- `value_per_count_unit`: float.
- `value_per_count_unit_label`: string (например, «Маржа на упаковку»).
- `value_per_count_unit_source`: 'auto'|'manual'|'imported'.
- `goal_seek_history`: list of past goal-seek runs.
- `safe_corridor_cache`: cached bounds (invalidate on retrain).

В первой версии плана предлагался **schema bump v1.3 → v2.0** для маркировки major changes. После 2nd-pass audit (2026-05-12) решено:

## Decision

**Schema bump → ОТКАЗ.** Версия bundle остаётся `v1.3` (уже занят Trust Level 3 marker из v1.1.0).

Все новые поля v1.3.0 - **strictly additive**:
- Старые v1.2 bundles читаются с `defaults injected in memory`.
- Сохраняются в новом формате при следующем save (no migration tool).
- Не используется `tools/migrate_v12_to_v20.py` (отменён).

### Schema (v1.3 additive)

```json
{
  "id": "string",
  "name": "string",
  "kpi_column": "string|null",
  "media_columns": ["string"],
  "control_columns": ["string"],
  "data_file": "string|null",
  "unit_costs": {"channel": 1.0},
  "excluded_columns": ["string"],
  "channel_categories": {"ch": "brand"},
  "unit_cost_inflation_pct": {"ch": 0.05},

  // v1.3.0 NEW additive fields (defaults if absent)
  "kpi_kind": "monetary",          // default for v1.2 bundles
  "per_channel_input": {            // empty dict = inferred from analysisObjective
    "tv": "monetary",
    "olv": "physical"
  },
  "derived_mode": "roi",            // cached, recomputed on load if absent
  "value_per_count_unit": 80.0,     // optional, only for kpi_kind=count
  "value_per_count_unit_label": "Маржа на упаковку",
  "value_per_count_unit_source": "auto|manual|imported",
  "goal_seek_history": [],          // append-only log
  "safe_corridor_cache": null       // recomputed on demand
}
```

### Pickle compat ladder

В `engines/persistence.py::load_model_with_compat()`:

```python
def load_model_with_compat(path):
    data = pickle.load(open(path, 'rb'))
    schema = data.get('model_version', 'v1.0')

    # Existing ladder v1.0 → v1.0-ols → v1.1 → v1.1.1 → v1.2 → v1.3 (Trust Level 3)

    # v1.3.0 additions (in-memory inject, никаких version bumps)
    if 'kpi_kind' not in data:
        data['kpi_kind'] = 'monetary'  # default

    if 'per_channel_input' not in data:
        # Infer from старое analysisObjective field
        objective = data.get('analysisObjective', 'roi')
        media = data.get('media_columns', [])
        if objective == 'roi':
            data['per_channel_input'] = {ch: 'monetary' for ch in media}
        elif objective == 'effectiveness':
            data['per_channel_input'] = {ch: 'physical' for ch in media}
        else:  # manual
            data['per_channel_input'] = data.get('per_channel_metric_choices', {ch: 'monetary' for ch in media})

    if 'derived_mode' not in data:
        # Recompute из per_channel_input
        inputs = data['per_channel_input']
        if all(v == 'monetary' for v in inputs.values()):
            data['derived_mode'] = 'roi'
        elif all(v == 'physical' for v in inputs.values()):
            data['derived_mode'] = 'effectiveness'
        else:
            data['derived_mode'] = 'manual'

    if 'value_per_count_unit' not in data and data['kpi_kind'] == 'count':
        # Auto-suggest using sales_rub / sales_packs если есть
        data['value_per_count_unit'] = compute_auto_value(data)
        data['value_per_count_unit_source'] = 'auto'

    return data
```

## Rationale

**Почему не v2.0 bump:**

1. **Не destructive.** Все изменения - добавление полей. v1.2 → v1.3.0 формально совместимо (старые читаются с defaults).
2. **Меньше работы.** Не нужен migration tool, не нужны fixtures, не нужны regression проверки v2.0 ↔ v1.2.
3. **Less anxious UX для пилотов.** Кагоцел/Венарус видят «v1.2 → v1.3» автоматически при save, не нужно объяснять «мажорное обновление».
4. **Backward write compatibility.** v1.3.0 bundle, открытый в v1.2.0 (hypothetical downgrade scenario), теряет только новые поля - модель работает (per-channel selection деградирует в текущий `analysisObjective`).

**Почему не v1.4 bump:**

`v1.3` уже занят Trust Level 3 marker (v1.1.0 changelog). Семантически v1.3.0 расширяет v1.3 schema без структурных изменений - bump не нужен. Bumping к v1.4 создаст ложное впечатление structural change.

**Почему не сохранять только в новом формате (no defaults injection):**

Тогда v1.2 bundles ломаются (decompose/optimize не знают `kpi_kind`, fallback на money-bound). Default injection в memory сохраняет 100% backward compat.

## Alternatives Considered

| Альтернатива | Отвергнуто потому что |
|---|---|
| **v2.0 bump + migration tool** | Излишне destructive; user-facing version jump неоправдан; +3 дня работы |
| **v1.4 bump (additive marker)** | Семантически incorrect - нет structural изменений |
| **Только новые поля без default injection** | v1.2 bundles ломаются на новых code paths |
| **Strict `version` field в bundle** | Не было раньше, добавлять сейчас - структурное изменение, отложено |

## Consequences

**Positive:**
- Нулевой риск destructive migration.
- Минимум работы (-3 дня от 1st-pass plan).
- v1.2 ↔ v1.3 forward + backward compat.
- Пилот UX: «open старый файл → работает».

**Negative:**
- Bundle не имеет explicit `version` field - versioning через pickle internal `model_version`. Не явное.
- Defaults в memory скрывают что юзер не задал значение явно (mitigated через `value_per_count_unit_source='auto'` flag).

**Neutral:**
- Если в Phase B понадобится structural change - введём explicit `bundle_version: "2.0"` тогда.

## Implementation

- `sidecar/econometrica/engines/persistence.py::load_model_with_compat()` - добавить v1.3.0 additive fields injection.
- `src-tauri/src/commands/project.rs::ProjectInfo` - расширить struct с 7 новыми Optional fields.
- `tools/migrate_v12_to_v20.py` - **NOT CREATED**.
- Существующие 552 теста - passable без изменений (defaults compatible).

## References

- ADR-015 (Mode as derived state) - derived_mode field.
- ADR-016 (KPI kinds) - kpi_kind + value_per_count_unit fields.
- ADR-018 (Migration safety protocol) - для future structural bumps.
- Existing schema ladder: `engines/persistence.py::load_model_with_compat()`.
