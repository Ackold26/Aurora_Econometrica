# Sprint v2.0.1-rc2 — Sub-agent Research Reports

> Параллельные исследовательские отчёты подагентов Sonnet (read-only) для подготовки Партий 3 и 5.

## H-09: Industry CPP wiring к UnitCostEditor (Партия 3)

### A) Существующая `project.json` схема

**Rust:** `src-tauri/src/commands/project.rs:13-49` — struct `ProjectInfo`.

Текущие поля: `id`, `name`, `description`, `created_at`, `updated_at`, `kpi_column`, `media_columns`, `control_columns`, `data_file`, `unit_costs` (HashMap), `excluded_columns`, `channel_categories`, `unit_cost_inflation_pct`.

Поля `industry` нет нигде. Нет и в `project_update` (строки 196-259) — ни парсинга, ни сохранения.

**Python:** `sidecar/econometrica/engines/project_migration.py:36` — `TARGET_SCHEMA_VERSION = '2.0.1'`. Endpoint `/project/migrate` в `server.py:572` вызывает `migrate_project_file()`.

`schema_version` в Rust `ProjectInfo` отсутствует — JSON пишется serde, schema хранится только в Python.

### B) Create-project UI flow

**Единая точка:** `src/lib/components/ProjectSelector.svelte:117-134`, функция `createProject()`.

UI: один `<input type="text" placeholder="Название нового проекта...">` (строки 258-260), кнопка «Создать» (строка 262). Нет поля Period, нет Description — только Name.

IPC: `invoke('project_create', { name })` (строка 122). Rust-команда: единственный аргумент `name: String` (строка 142).

После создания: `activeProject.set(info)` — проект сразу активен.

**Второй путь создания:** `ImportStep.svelte:261` — auto-create при импорте CSV без существующего проекта (тоже только name).

**Где добавить industry-select:** секция `.project-create` (ProjectSelector.svelte:255-265), между input-именем и кнопкой «Создать». Расширить сигнатуру `project_create` в Rust.

### C) UnitCostEditor — placeholder injection points

Файл: `src/lib/components/pipeline/UnitCostEditor.svelte`

- **Строка 189** — режим budget: `placeholder="например, 38 000 000"`. Подставлять `suggestUnitCostDefault(channel.name, industry).value`.
- **Строка 218** — режим unit: `placeholder="0"`. Главный injection point: `placeholder="~{suggestion.value.toLocaleString()}"` + hint с confidence.
- **Строка 232** — инфляция: `placeholder="обычно 0-20%..."`. Industry не влияет.

UnitCostEditor НЕ импортирует `industry-cpp-defaults.js`. Модуль уже экспортирует нужные функции. Компонент получает `channel` prop (строки 36-41), но не `industry` — нужно добавить prop.

### D) Миграция v2.0.1 → v2.0.2

1. `project_migration.py:36`: `TARGET_SCHEMA_VERSION = '2.0.2'`
2. Расширить `needs_migration()`: добавить проверку `'industry' not in project_dict`
3. Расширить `apply_migration()`: `out.setdefault('industry', 'unknown')` перед обновлением schema_version
4. Update `test_project_migration.py:95-97`: assertion `assert after['industry'] == 'unknown'` + новый тест `test_adds_industry_default`
5. Endpoint `/project/migrate` уже существует — вызывается из `econometrica.rs:83`

**Edge case:** если проект уже имеет `industry` отличный от unknown — `setdefault` не перезапишет. Корректно.

### E) Затронутые файлы

| Файл | Изменения | Effort |
|---|---|---|
| `src-tauri/src/commands/project.rs` | `industry: String` поле + `#[serde(default)]` + handler в project_update + project_create signature | S (2-3ч) |
| `src/lib/components/ProjectSelector.svelte` | `<select>` industry в `.project-create` | S (1-2ч) |
| `src/lib/components/pipeline/UnitCostEditor.svelte` | `industry` prop + импорт suggestUnitCostDefault + placeholder + hint | M (3-4ч) |
| `src/lib/components/pipeline/AppliedModeSummary.svelte` | Прокинуть `industry={$activeProject.industry}` | XS (30мин) |
| `src/lib/project-state.js` | Hydration `industry` (аналогично unit_cost_inflation_pct) | XS (30мин) |
| `sidecar/econometrica/engines/project_migration.py` | TARGET → 2.0.2 + миграция | S (1ч) |
| `sidecar/econometrica/tests/test_project_migration.py` | Новые assertions + тест-кейс | XS (30мин) |

**Итого: ~8-11 часов, 7-8 файлов.**

### F) Edge cases

1. **Existing project без `industry`** → `#[serde(default = "default_industry")]` где `fn default_industry() -> String { "unknown".into() }`. Backward compat гарантирован.
2. **Corrupt industry value** → `industry-cpp-defaults.js:134` уже обрабатывает `INDUSTRY_CPP_TABLE[industry] || INDUSTRY_CPP_TABLE.unknown` fallback. На уровне Rust добавить whitelist-валидацию аналогично `channel_categories`.
3. **Pre-migration project** → serde `default` вернёт `"unknown"` молча → UnitCostEditor покажет low-confidence ranges → пользователь не заметит деградации.
4. **Изменение industry post-input** → `validateUnitCost` ретроспективно покажет warning если values выходят за новый range. Non-destructive.
5. **ImportStep auto-create** (строка 261) — вызывает `project_create` без industry. Дефолт в Rust команде ИЛИ передавать `'unknown'` явно.

---

## H-17: Snapshot tests rebuild на semantic queries (Партия 5)

### A) Текущий тестовый кейс mapping

**Файл:** `src/tests/snapshots/applied-mode-summary.snapshot.test.js`
**External `.snap`:** `src/tests/snapshots/__snapshots__/applied-mode-summary.snapshot.test.js.snap`

Реальный код использует `toMatchSnapshot()` с external `.snap` (хотя комментарий в шапке говорит `.toMatchInlineSnapshot`).

| # | Кейс | Сценарий | Ключевой DOM |
|---|---|---|---|
| 1 | ROI + 1 physical TRP (unconverted) | 3 monetary + 1 physical + 4 excluded | incompat-banner ⚠ 1, uc-inputs с uc-editor для TRP, channel-list с `.incompatible` на TRP, excluded pill ⊘ 4, CTA block |
| 2 | ROI + TRPs converted | unitCosts={'TRPs бренд': 25000} | uc-row--converted, preview «25 000 ₽ за 1 TRP», `.converted` + `metric-converted`, НЕТ banner |
| 3 | Effectiveness mode | analysisMode=effectiveness | mode-badge--effectiveness, header «физические метрики», все = «конвертируется в физ.», НЕТ uc-inputs, НЕТ banner |
| 4 | Mixed + Expert | analysisMode=mixed, expertMode=true | mode-badge--mixed, header «смешанном режиме», monetary = «спенд в ₽ ✓», expert-active-note вместо CTA |
| 5 | Empty channels | channels=[], excluded=[] | НЕТ channel-counts, НЕТ list, `<p class="no-channels">`, CTA block |
| 6 | ROI no excluded | 2 monetary, excluded=[] | «2 активных канала» БЕЗ excluded pill, 2 «спенд в ₽», НЕТ banner |

Все 6 содержат hash `svelte-iytji5` (AppliedModeSummary) + `svelte-pt4i6h` (UnitCostEditor). Любой refactor → все 6 ломаются → rubber-stamp.

### B) Доступные инструменты

- `@testing-library/svelte` ^5.3.1 **установлен** (package.json devDependencies)
- `@testing-library/jest-dom` ^6.9.1 установлен, подключён через `src/tests/setup.js`
- В 10 из 18 тест-файлов уже используются `render`, `screen`, `fireEvent`
- `getByRole`, `getByText`, `queryByText`, `getByTestId` доступны без доп. установок
- `vi.addSnapshotSerializer` доступен в Vitest ^4.1.2

**Никаких установок не нужно, только переписать тесты.**

### C) Replacement test structure (по каждому из 6)

**Кейс 1 — ROI + physical TRP unconverted:**
- `getByRole('region', { name: /Применённый режим анализа/ })`
- `getByRole('heading', { name: /Все каналы будут поданы в модель как ₽/ })`
- `getByTestId('incompat-banner')` содержит «⚠ 1»
- `getByTestId('uc-inputs')` → внутри `[data-testid="uc-editor"]` с `data-channel="TRPs бренд"`
- `getByRole('list', { name: /Список каналов/ })` 4 items
- `getByText('TRPs бренд').closest('li')` имеет класс `incompatible`
- `getByTestId('excluded-toggle')` «⊘ 4»
- `getByRole('button', { name: /Управлять вручную/ })`

**Кейс 2 — ROI + TRP converted:**
- `queryByTestId('incompat-banner')` is null
- `getByTestId('uc-editor')` имеет класс `uc-row--converted`
- `getByText(/25.*000.*₽.*1 TRP/)`
- `getByText('TRPs бренд').closest('li')` имеет класс `converted`

**Кейс 3 — Effectiveness:**
- `getByRole('heading', { name: /физические метрики/ })`
- Нет `incompat-banner`, нет `uc-inputs`
- `.mode-badge--effectiveness` содержит «Эффективность»
- Все `.channel-metric` «физ. метрика» / «конвертируется в физ.»

**Кейс 4 — Mixed + Expert:**
- `getByRole('heading', { name: /смешанном режиме/ })`
- `.mode-badge--mixed`
- `queryByRole('button', { name: /Управлять вручную/ })` is null
- `getByText(/Expert mode включён/)`

**Кейс 5 — Empty:**
- `getByText(/Каналы определятся после импорта данных/)`
- `queryByRole('list', { name: /Список каналов/ })` is null
- `queryByTestId('channel-counts')` is null

**Кейс 6 — ROI no excluded:**
- `getByTestId('channel-counts')` содержит «2»
- `queryByTestId('excluded-toggle')` is null

### D) Svelte-* serializer стратегия

Для большинства кейсов serializer **не нужен** — semantic queries работают независимо от svelte-hash.

Если нужен fallback structural snapshot — добавить в `src/tests/setup.js`:
```js
expect.addSnapshotSerializer({
  test: (val) => typeof val === 'string',
  print: (val) => JSON.stringify(
    val.replace(/\bsvelte-[a-z0-9]+\b/g, 'svelte-[hash]')
  ),
});
```

**Оптимальный путь:** полный отказ от `toMatchSnapshot()` в этих 6 кейсах. Serializer — только временный fallback.

### E) Effort breakdown

| Кейс | Complexity | Effort |
|---|---|---|
| 5 Empty | Низкая | ~20 мин |
| 6 ROI no excluded | Низкая | ~25 мин |
| 3 Effectiveness | Средняя | ~30 мин |
| 4 Mixed Expert | Средняя | ~30 мин |
| 1 ROI + physical unconverted | Высокая | ~45 мин |
| 2 ROI + TRP converted | Высокая | ~45 мин |
| **Итого** | | **~3 часа** |

Кейсы #1 и #2 разделяют 90% пропсов — удобнее писать вместе в одном describe.

### Available data-testid / aria-label

**AppliedModeSummary.svelte:**
- `data-testid`: `channel-counts`, `excluded-toggle`, `excluded-list`, `excluded-restore-btn`, `incompat-banner`, `uc-inputs`
- `aria-label`: «Список каналов с типами метрик», «Конвертация физических каналов в ₽», «Применённый режим анализа»

**UnitCostEditor.svelte:**
- `data-testid`: `uc-editor`, `uc-budget-input-{slug}`, `uc-unit-input-{slug}`, `uc-infl-input-{slug}`, `uc-apply-same-btn-{slug}`
