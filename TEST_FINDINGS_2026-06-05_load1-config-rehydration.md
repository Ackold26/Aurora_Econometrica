---
tags: [audit, load-1, rehydration, config-stores, durable]
type: audit-map
date: 2026-06-05
scope: ре-гидрация UI-config сторов при загрузке проекта (класс, вскрытый perChannelInput-находкой)
---
# LOAD-1 config-rehydration — аудит класса

**Запрос Антона:** «закрыть класс» (греп всех UI-config сторов + проверка ре-гидрации в
`restoreProjectResults`/`activeProject.subscribe`), пока контекст тёплый после perChannelInput.

**Метод:** code-only. Ground truth с диска: `ProjectInfo` struct (`src-tauri/src/commands/project.rs:14-57`) +
реальный `project.json` (`%APPDATA%/aurora-econometrica-gui/projects/<id>/`). Греп всех `<store>.set(` в `src/lib`
с классификацией контекста (user-action vs load/rehydration).

## Вердикт severity (КРИТИЧНО): весь класс — UI-fidelity, НЕ артефакт обучения
Train-конфиг (`ConfigPanel.svelte:336-365`, `econ_train_start({config})`) шлёт **durable** `unit_costs`,
`media_columns` (enabledChannels), `kpi_column`, `control_columns`, `channel_categories` — но НЕ `perChannelInput`,
НЕ `analysis_mode`, НЕ `kpiType` напрямую как режим. Money/physical обработка канала при обучении определяется
**только durable `unit_costs`**. → Потеря config-сторов на reload = неверный UI/пре-выбор/повторный re-config,
НЕ числовой артефакт. Артефакт-критичный вход (`unit_costs`) durable.

## Карта (что персистится / ре-гидрируется / вердикт)

| Стор | Персист | Ре-гидрация на load | Вердикт |
|---|---|---|---|
| roles (kpi/media/control/excluded) | project.json (project_update) | applyProjectRolesToColumns / validateData | ✅ OK |
| `unitCosts` | project.json | activeProject.subscribe:521 | ✅ OK |
| `unitCostInflation` | project.json | activeProject.subscribe | ✅ OK |
| `channelCategories` | project.json | activeProject.subscribe:558 | ✅ OK |
| `chosenKpiColumn` | kpi_column (durable) | **БЫЛ только reconstruction-путь** | ✅ **ИСПРАВЛЕН 2026-06-05** (см. ниже) |
| `unitCostInputMode` | только econ_save_kpi_settings (мёртв) | reads `p.unit_cost_input_mode` — НЕ в ProjectInfo → всегда `{}` | 🔴 dead read |
| `budgetInputs` | только econ_save_kpi_settings (мёртв) | reads `p.budget_inputs` — НЕ в ProjectInfo → всегда `{}` | 🔴 dead read |
| `perChannelInput` | только econ_save_kpi_settings (мёртв) | НЕТ | 🟡 gap (UI + cpp-гейт на reload падает на детектор) |
| `kpiKind` | только econ_save_kpi_settings (мёртв) | НЕТ (wizard re-derive на fresh) | 🟡 gap |
| `kpiType` | econ_save_kpi_settings (мёртв) + train kpi_type | НЕТ | 🟡 gap (**count-KPI re-train** после reload → 'sales' default) |
| `valuePerCountUnit`/`Source` | econ_save_kpi_settings (мёртв) + train kpi_unit_cost | НЕТ | 🟡 gap (count-KPI: ₽/ед. теряется) |
| `analysisMode` | **НЕ персистится** | НЕТ (`migrateV13ToV20` — нет prod-вызывателя, только тесты) | 🟠 gap (**effectiveness-проект reload** → 'roi' default → cpp-гейт требует unit_cost → Модель re-locks через shouldRelockModel; safe-direction, recoverable re-select) |
| `modelEngine` | НЕ персистится | ImportStep only (не на reload) | 🟢 minor (auto-recommend) |
| `modelChannelEnabled` | НЕ персистится | ConfigPanel mount re-init из media (zeros-default) | ✅ def. default (теряет ручные toggle'ы) |

## Двойной корень
1. **Мёртвый persist-путь:** `per_channel_input/kpi_kind/value_per_count_unit/mode_for/budget_inputs` пишутся ТОЛЬКО
   через `econ_save_kpi_settings`→sidecar, вызываемый из **мёртвого `handleContinue`** (ValidateStepV13:485, `onContinue`
   проброшен но не вызывается — кнопка стала инфо-строкой). → `v13_kpi.json` нет ни в одном проекте на диске.
2. **ProjectInfo gaps:** даже поля, что `activeProject.subscribe` пытается читать (`unit_cost_input_mode`/`budget_inputs`),
   отсутствуют в backend `ProjectInfo` struct → `p.*` всегда undefined (мёртвые чтения; комментарий 531-534 был
   аспирационным — «loader merges flat» не реализован).
3. **Никогда не персистились:** `analysisMode`, `kpiType` (как режим), `modelEngine`.

## Исправлено сейчас (derivable из durable, без backend)
**`chosenKpiColumn`** — ре-гидрация из durable `kpi_column` в `activeProject.subscribe` (project-state.js).
Раньше: только reconstruction-путь (`hydrateRolesFromProjectIfEmpty:904`); при validation.json present оставался null
→ после reload `ConfigPanel:100` брал `kpis[0].name` (первый алфавитно) вместо выбранного юзером KPI = воскрешение
бага, ради которого стор создан. Тест `project-roles-hydration.test.js` (+3). Гейты svelte 0E/171W · vitest 644.

## Отложено (коэрентный backend-таск, согласовано с Антоном — как perChannelInput)
Закрыть **dead-save группу** (perChannelInput/kpiKind/kpiType/valuePerCountUnit/inputMode/budgetInputs) + analysisMode
требует: (a) добавить поля в backend `ProjectInfo` + persist в project.json (ИЛИ оживить sidecar save-path вместо
мёртвого handleContinue); (b) frontend ре-гидрация в activeProject.subscribe. **Приоритет внутри:** analysisMode
(🟠 effectiveness-reload) + count-KPI пара (kpiType/valuePerCountUnit) — выше остальных. Это отдельная сессия;
карта выше делает её исполнением, не расследованием.
