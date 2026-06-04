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

## Вердикт severity (ИСПРАВЛЕНО после audit-of-audit 2026-06-05): класс СМЕШАННЫЙ
> ⚠️ Первичный headline «весь класс — UI-fidelity» был НЕВЕРЕН (independent agent поймал). Класс смешанный.

**Большинство членов — UI-fidelity** (perChannelInput, analysisMode, unitCostInputMode, budgetInputs): money/physical
обработка канала при обучении определяется ТОЛЬКО durable `unit_costs`, который **на обучение модели НЕ влияет**
(backend подтверждает дословно: `sidecar/.../server.py:331-333` — «на обучение не влияет, Hill на нативных единицах»;
`analysis_mode`/`per_channel_input` вообще НЕ в train-конфиге). Сброс → неверный ROI-дисплей/пре-выбор, не posterior.

**НО ДВА члена — durable train-входы, сбрасываемые в НЕВЕРНЫЙ дефолт на reload → ЛАТЕНТНЫЙ RE-TRAIN АРТЕФАКТ:**
- **`kpiType`** (🔴 re-train artifact, НЕ UI-fidelity) — train-вход (`ConfigPanel:353`→TrainStartRequest:370),
  персистится в pickle (`modeler.py:1228`), **меняет байесовский prior**: competitor `_competitor_mu` = `0.0`
  (count/OTC) vs `−0.3` (monetary) (`modeler.py:461-464`, applied :474). Сброс в `'sales'` (monetary) на reload →
  count-KPI проект с competitor-контролями (как Кагоцел: «...конкуренты») при re-train → флип prior → **материально
  иной posterior**. + потеря `kpi_unit_cost` (valuePerCountUnit) = неверная ₽-конверсия.
- **`modelChannelEnabled`** (🟠 re-train artifact) — `enabledChannels`→`media_columns` train-входа (`ConfigPanel:340`,
  persist :316, lastTrainedConfig :373); НЕ персистится → ре-дефолт из `zeros_pct>80` на reload (`ConfigPanel:110`) →
  ручной отключённый low-zeros канал РЕ-ВКЛЮЧАЕТСЯ → re-train с иным набором каналов = иная модель.

**Латентность:** оба бьют ТОЛЬКО при re-train ПОСЛЕ reload (+ count-KPI / ручной disable); на монетарном Кагоцеле не
активно. ВАЖНО: `ConfigPanel.handleTrain` (254-365) **не имеет cpp-гейта** (он только на Валидации) → этот re-train
путь НЕ защищён chokepoint-guard'ом. → Артефакт-критичный для money/physical вход (`unit_costs`) durable, но
kpiType/modelChannelEnabled — durable train-входы с неверным reload-дефолтом. Deferred-группа = RE-TRAIN артефакт,
НЕ UI-fidelity (повышенный приоритет фикса).

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
| `kpiType` | econ_save_kpi_settings (мёртв) + train kpi_type | НЕТ | 🔴 **RE-TRAIN АРТЕФАКТ** (не UI): сброс в 'sales' → флип competitor prior 0.0↔−0.3 (modeler.py:461-464) на re-train count-KPI |
| `valuePerCountUnit`/`Source` | econ_save_kpi_settings (мёртв) + train kpi_unit_cost | НЕТ | 🟡 gap (count-KPI: ₽/ед. теряется) |
| `analysisMode` | **НЕ персистится** | НЕТ (`migrateV13ToV20` — нет prod-вызывателя, только тесты) | 🟠 gap (**effectiveness-проект reload** → 'roi' default → cpp-гейт требует unit_cost → Модель re-locks через shouldRelockModel; safe-direction, recoverable re-select) |
| `modelEngine` | НЕ персистится | ImportStep only (не на reload) | 🟢 minor (auto-recommend) |
| `modelChannelEnabled` | НЕ персистится | ConfigPanel mount re-init из media (zeros>80% default) | 🟠 **RE-TRAIN АРТЕФАКТ** (не «default»): ручной disabled low-zeros канал ре-включается → re-train иной media_columns (ConfigPanel:340) |
| `derivedMode` | derived из perChannelInput | НЕТ (downstream) | 🟢 derived (downstream perChannelInput) |
| `valuePerCountUnitSource` | econ_save_kpi_settings (мёртв) | НЕТ | 🟡 gap (provenance count-KPI, с valuePerCountUnit) |
| `hideEducationalHints` | **НЕ персистится** (нет localStorage, в отличие от expertMode) | НЕТ | 🟢 minor (educational toggle сброс на reload) |

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
+ modelChannelEnabled требует: (a) добавить поля в backend `ProjectInfo` + persist в project.json (ИЛИ оживить sidecar
save-path вместо мёртвого handleContinue); (b) frontend ре-гидрация в activeProject.subscribe. **Приоритет внутри
(ИСПРАВЛЕНО):** 🔴 `kpiType`+`valuePerCountUnit` (re-train артефакт — флип prior count-KPI) + 🟠 `modelChannelEnabled`
(re-train иной media set) — ВЫШЕ остальных; затем analysisMode (effectiveness-reload UI). Доп. защита: добавить
cpp-гейт в `ConfigPanel.handleTrain` (сейчас его там нет → re-train минует chokepoint-guard). Это отдельная сессия;
карта делает её исполнением, не расследованием.

## Audit-of-audit (2026-06-05, independent agent) — что исправлено в этой доке
- **CRITICAL:** headline «весь класс UI-fidelity» был неверен — `kpiType`+`modelChannelEnabled` = durable train-входы
  → re-train артефакт (исправлено выше: вердикт + 2 строки + приоритет). Shipped-фикс chosenKpiColumn НЕ затронут.
- **chosenKpiColumn фикс — SOUND:** 12 `activeProject.set`-сайтов, 3 mid-session (UnitCostsPanel/ChannelCategoriesPanel/
  +layout) ставят свежий post-write `info` с актуальным kpi_column → НЕ клоббит. Footgun (pre-existing): `handleRoleChange`
  persist fire-and-forget (ValidateStepV13:933) — суб-tick кросс-панель interleave теоретичен, не достижим в норме.
- **Тесты:** доказывают subscribe в изоляции, НЕ wiring `ConfigPanel:99-100` (reload→пре-выбор) — пре-существующее
  использование, приемлемо, но end-to-end не покрыт. NB: новый subscribe маскирует assert hydrate-пути (test :100
  теперь зелён из-за subscribe, не из-за hydrateRolesFromProjectIfEmpty).
- **unitCosts «OK»:** верно по коду, но ground-truth Кагоцел `unit_costs:{}` → непустая ре-гидрация тестом не прогнана.
- **Пропущенные сторы** добавлены в таблицу: derivedMode, valuePerCountUnitSource, hideEducationalHints.
- **Подтверждено SOUND:** dead-read claim (ProjectInfo по всем сайтам), analysisMode UI-fidelity (server.py:331-333).
