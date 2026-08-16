# Профит-фронтир на экране — отчёт (2026-08-16)

Ветка `feat/econ-p1-winning`, дерево `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt`.
Ничего не коммичено, `git add` не делался, веток не заводилось.
Контракт: `Projects/FRONTIER_DESIGN_2026-08-16.md`. Отчёт движка: `Projects/FIX_FRONTIER_ENGINE_2026-08-16.md`.
`sidecar/` не тронут.

## Что сделано

| Файл | Что |
|---|---|
| `src-tauri/src/commands/econometrica.rs` | новая команда `econ_profit_frontier` — мост к `POST /optimize/profit-frontier`, по образцу `econ_optimize_inverse` (тот же клиент `train_client()`, та же обработка ошибок через `post_json`) |
| `src-tauri/src/lib.rs` | регистрация `econ_profit_frontier` рядом с `econ_safe_corridor`/`econ_optimize_inverse` |
| `src-tauri/src/commands/project.rs` | `gross_margin: Option<f64>` в `ProjectInfo` — по образцу `value_per_count_unit` (struct-поле, `project_create`, `project_update`, тестовый `make_info`, +2 юнит-теста: roundtrip и legacy-совместимость) |
| `src/lib/project-state.js` | store `grossMargin` — по образцу `valuePerCountUnit`: та же ре-гидрация из `activeProject.subscribe` (SET-IF-PRESENT, id-guard), тот же сброс при деселекте проекта |
| `src/lib/components/pipeline/ProfitFrontierCard.svelte` | **новый** — карточка на шаге оптимизации |
| `src/lib/components/pipeline/OptimizeStep.svelte` | третья вкладка «Сколько тратить всего» рядом с «От бюджета»/«От цели» (`taskMode === 'frontier'`) |
| `src/tests/profit-frontier-card.test.js` | **новый**, 9 тестов |

## Карточка — что показывает

`ProfitFrontierCard.svelte` самодостаточна (как `BacktestCard.svelte`): сама читает
`activeProjectId`/`kpiType`/`kpiKind`/`valuePerCountUnit`/`grossMargin`/`unitCosts` из
`project-state.js`, сама вызывает `project_get_dir` + `econ_profit_frontier` на `onMount`.
Пропсов нет — в `OptimizeStep.svelte` подключена одной строкой `<ProfitFrontierCard />`.

- **График** — `EChartBase` (тот же способ, что `ContinuationChart.svelte`): сплошная линия
  прибыли до границы наблюдений (`observed_frontier.index`), дальше — пунктир приглушённой
  прозрачности + `markArea` серой заливки («не подтверждено данными» за границей, тот же приём,
  что CI-ribbon в `ContinuationChart` — area вместо нативной штриховки, которую echarts не
  поддерживает). `markLine` — текущий бюджет. `markPoint` — максимум, ТОЛЬКО когда
  `maximum.reportable === true`. `markArea` золотого тона — 90%-интервал на положение максимума,
  когда доступен.
- **Три исхода** — текст берётся дословно из `maximum.message` (движок формулирует, карточка не
  сочиняет). Три визуальных тона через CSS-классы `outcome-ok`/`outcome-info`/`outcome-warn` по
  `maximum.outcome`.
- **Число максимума** — рендерится только внутри `{#if result.maximum.reportable}`. Это и есть
  точка мутации (ниже).
- **`maximum.at_observed_frontier`** — отдельный флажок с иконкой предупреждения, если максимум
  пришёлся ровно на границу наблюдений (движок это поле отдаёт всегда, не только в этом случае).
- **Интервал на максимум** — при `posterior_interval.available` показываются числа диапазона;
  иначе — `posterior_interval.message` словами (МНК/малые данные, нет апостериорных выборок).
  Ни разу не подставляется ноль или тишина.
- **Подпись периода** — `period.note` (из движка, уже содержит «N периодов, не за один месяц»)
  выводится в подвале карточки при каждом успешном расчёте.
- **`allocation_note`** — оговорка про фиксированные пропорции каналов, тоже из движка.

## Поле валовой маржи

Сделано по образцу `ValuePerCountUnitInput.svelte`, но встроено инлайн в карточку (не отдельный
шаг мастера — маржа нужна только здесь, а не при валидации KPI):

- Когда движок отвечает `status: 'economics_required', reason: 'monetary_margin_missing'` —
  карточка показывает поле «Валовая маржа, %» + кнопку «Подтвердить».
- Подтверждение: (1) `invoke('project_update', { updates: { gross_margin } })` — персист в
  `project.json` тем же путём, что `value_per_count_unit` (`project.rs::ProjectInfo`, НЕ через
  sidecar — там для маржи хранилища ещё нет, и трогать `sidecar/` было нельзя); (2) `grossMargin`
  store обновляется; (3) пересчёт фронтира с новым значением сразу же, без перезагрузки страницы.
- Персист — best-effort (`.catch` тихий): даже если запись в `project.json` не удалась, значение
  всё равно уходит в текущий запрос расчёта — отказ хранения не блокирует ответ.
- Другие причины отказа (`count_value_missing`, `kpi_kind_unsupported`,
  `gross_margin_out_of_range`) — просто показывают `message` от движка, без графика.

## Решения, принятые самостоятельно (и почему)

1. **Третья вкладка, а не встраивание в `OptimizeGoalSeek`.** Профит-фронтир отвечает на третий,
   независимый вопрос («сколько вообще тратить», не «куда вложить заданное» и не «сколько под
   цель») — соседняя структура уже даёт паттерн (`task-pills` c `flex:1`, добавление третьей
   вкладки не потребовало правки CSS). Не трогала `OptimizeGoalSeek.svelte` и «зелёную зону» вовсе.
2. **`gross_margin` персистится через `project.json` (Rust), а не через `settings/v13_kpi.json`
   (sidecar).** `resolve_economics` в движке читает маржу из `economics` (запрос, приоритет 1) или
   `settings/v13_kpi.json` (приоритет 2) — но пути записи туда для маржи нет, а трогать
   `sidecar/server.py::project_save_kpi_settings` было запрещено заданием. Карточка отправляет
   `gross_margin` в запросе НА КАЖДЫЙ расчёт (режим `mode='request'`, наивысший приоритет в
   `resolve_economics`) — персист в `project.json` нужен только для того, чтобы поле не пустело
   при уходе со страницы и возврате, к самому расчёту он не обязателен.
3. **Точка максимума и markArea интервала — на положении по X (бюджет), не по Y.**
   `posterior_interval` — это интервал на ПОЛОЖЕНИЕ максимума (бюджет), не на величину прибыли в
   этой точке (контракт это явно оговаривает); поэтому `markArea` рисуется по оси бюджета, а не
   как вертикальный отрезок вокруг Y-значения.
4. **`solidData`/`dashedData` через дублирование граничной точки** — тот же приём непрерывности,
   что `cutoffValue` в `ContinuationChart.svelte` (граничная точка попадает в оба массива, чтобы
   линия не рвалась визуально на стыке «данные/не данные»).
5. **`{#if true}` как место мутации** — мутировала ИМЕННО условие вокруг `frontier-maximum-budget`
   (там, где число реально попадает в разметку), а не где-то в производной переменной.

## Мутация «внести-поймать-откатить»

`ProfitFrontierCard.svelte`: `{#if result.maximum.reportable}` → `{#if true}` (место, где число
максимума бюджета реально попадает в DOM). Прогон `profit-frontier-card.test.js`:

- **До мутации**: 9/9 зелёных.
- **С мутацией**: `beyond_observed → reportable=false, числа максимума НЕТ в разметке` покраснел
  (`expect(screen.queryByTestId('frontier-maximum-budget')).not.toBeInTheDocument()` не прошёл —
  число оказалось в разметке при `reportable: false`). 1 failed из 9, остальные 8 остались зелёными
  (мутация задела ровно то место, для которого писался тест, не больше).
- **После отката**: дословный откат строки, 9/9 зелёных.

## По ходу поймана и исправлена своя ошибка

`confirmMargin()` изначально делал `marginPct.replace(',', '.')` — но `bind:value` на
`<input type="number">` в Svelte 5 отдаёт `marginPct` числом, не строкой, и `.replace` на числе
падает (`TypeError`). Поймано первым же прогоном теста на подтверждение маржи (не в проде — тест
сразу показал unhandled rejection). Исправлено: `typeof marginPct === 'number' ? marginPct :
parseFloat(String(marginPct).replace(',', '.'))` — работает и для числа (реальный браузер), и для
строки с запятой (на случай нестандартного ввода/окружения).

## 🔴 Гейт `cargo check` — заблокирован ЧУЖОЙ уже сломанной зависимостью, не моим diff

Пыталась запустить `cargo check` (из `src-tauri/`, из корня с готовым `Cargo.lock`, с `-p`,
`--offline`, `--frozen`) — во всех вариантах одна и та же ошибка ДО парсинга моего кода:

```
error: invalid character `{` in package name: `{{cookiecutter.app_id}}`
 --> ...\aurora-platform-core-...\aurora_shell_template\{{cookiecutter.app_id}}\src-tauri\Cargo.toml:2:8
```

Разобрала, а не просто отступила. Причина: зависимость `aurora_core` (git-тег
`aurora_core-v0.1.0`, добавлена 15.08.2026 в `feedback.rs`/`errors.rs` — трассирующий срез общего
Rust-слоя Aurora, «CRATE_DESIGN_2026-08-15.md») подключена БЕЗ явного `path =` в `Cargo.toml`.
Для такой git-зависимости cargo обязан просканировать ВСЕ `Cargo.toml` в чекауте репозитория
`aurora-platform-core`, чтобы найти пакет с именем `aurora_core` — и падает на манифесте
шаблона `aurora_shell_template/{{cookiecutter.app_id}}/...` (плейсхолдер cookiecutter, не
предназначен для реального парсинга cargo). Это ломает `cargo check` для ЛЮБОГО потребителя
этой git-зависимости на этой ветке, независимо от моих правок — я ничего не меняла в
`Cargo.toml`/`Cargo.lock`, и ошибка возникает на этапе резолва графа зависимостей, ДО компиляции
моего кода. Подтверждено: `--offline`/`--frozen`/из корня с существующим `Cargo.lock` — тот же
результат, значит дело не в свежем сетевом фетче.

**Не мой доступ чинить** (внешний репозиторий `aurora-platform-core`). Вместо слепого повтора —
сделала ручной построчный ревью правок в `econometrica.rs`/`lib.rs`/`project.rs` (сигнатуры,
скобки, типы, единственная непарная замена в `lib.rs` — точка вставки одной строки без сдвига
остального списка). Кандидат в `aurora-meta/CROSS_PRODUCT_DEFECT_REGISTRY.md` — решение не моё,
доложила отдельно.

## Гейты

- `npx vitest run` (весь пакет): **1471 passed (1471), 0 failed** — входное 1462 + 9 моих
  (`profit-frontier-card.test.js`), 100 файлов тестов, все зелёные. Фоновые unhandled-rejection
  предупреждения (`ResizeObserver is not defined`, `zrender clearRect null`) — тот же pre-existing
  разрыв окружения jsdom, что документирован в `multi-scenario-chart.test.js` («ECharts canvas
  initialisation is async and does not run in jsdom»); не мой код его порождает, тесты они не
  проваливают.
- `npm run check`: **0 ERRORS, 177 WARNINGS** — ровно входные цифры, ни одного нового
  предупреждения не добавлено моими файлами.
- `cargo check` — заблокирован сторонней проблемой (см. выше), не прогнан.

## Что осталось следующему шагу (не моя область)

1. `cargo check`/сборка — дождаться починки апстрим-репозитория `aurora-platform-core`
   (убрать/переименовать `aurora_shell_template/{{cookiecutter.app_id}}` либо явно указать
   `path =` для git-зависимости `aurora_core`, чтобы cargo не сканировал весь чекаут).
2. Оговорка `OptimizeGoalSeek.svelte:130` про «зелёную зону» — не трогала по заданию, снимается
   отдельным решением про основания коридора (расхождение №2 в отчёте движка).

---

**РАБОТА ЗАВЕРШЕНА, 16 авг 2026 г. 13:30.**
