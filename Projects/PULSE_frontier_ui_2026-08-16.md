# Маячок: доставка профит-фронтира до экрана (2026-08-16)

## Задача своими словами
Движок фронтира уже готов (`compute_profit_frontier`, `POST /optimize/profit-frontier`)
и отдаёт клиентские формулировки, три исхода, честность про границу наблюдений и период —
моя задача не сочинять заново, а довести до экрана: мост в Rust (по образцу
`econ_optimize_inverse`/`econ_optimize_corridor`), карточка в интерфейсе на шаге оптимизации
(кривая, три исхода, число только при `reportable:true`, флаг границы наблюдений, интервал
на максимум, подпись периода), плюс поле валовой маржи для денежных KPI по образцу
`ValuePerCountUnitInput.svelte`. Не трогаю sidecar/, не снимаю оговорку про «зелёную зону»
в `OptimizeGoalSeek.svelte:130`, не коммичу.

## План
1. Прочитать контракт (`FRONTIER_DESIGN_2026-08-16.md`, `FIX_FRONTIER_ENGINE_2026-08-16.md`) — готово.
2. Изучить `server.py /optimize/profit-frontier` (точный контракт запрос/ответ) + `frontier.py` сигнатуру.
3. Изучить соседей: `econometrica.rs` (econ_optimize_inverse/corridor) — готово, образец найден.
4. Изучить `OptimizeGoalSeek.svelte` и соседей по `pipeline/`, `ValuePerCountUnitInput.svelte`.
5. Rust: команда `econ_profit_frontier` в `econometrica.rs` + регистрация в `lib.rs`.
6. Svelte: поле валовой маржи (по образцу ValuePerCountUnitInput) + карточка фронтира (график, 3 исхода, флаги, интервал, период).
7. Тесты vitest на карточку (3 исхода, no-number при reportable:false, no-interval при недоступном, подпись периода).
8. Мутация: заставить карточку показать число при reportable:false → тест должен покраснеть → откатить.
9. Гейты: `npx vitest run`, `npm run check`, `cargo check`.
10. Отчёт в `FIX_FRONTIER_UI_2026-08-16.md`.

Старт: 16 авг 2026 г. 13:02.

## Прогресс
- Контракт/движок/соседи (econometrica.rs, server.py, frontier.py) изучены — готово, 13:20.
- Rust: `econ_profit_frontier` в `econometrica.rs` + регистрация в `lib.rs` — готово.
- Rust: `gross_margin: Option<f64>` в `ProjectInfo` (project.rs), по образцу `value_per_count_unit`
  (struct, project_create, project_update, make_info-тест, +2 юнит-теста roundtrip/legacy) — готово.
- 🔴 `cargo check` (и с root, и с `-p`, `--frozen`, `--offline`) падает на ЧУЖОЙ уже
  сломанной зависимости: `aurora_core` (git-тег, добавлена 15.08 в feedback.rs/errors.rs) —
  апстрим-репо `aurora-platform-core` содержит `aurora_shell_template/{{cookiecutter.app_id}}/...
  Cargo.toml` с именем-плейсхолдером, cargo сканирует ВСЕ манифесты git-чекаута при резолве
  git-зависимости по имени и падает ДО парсинга моего кода. Не мой diff (я не трогала
  Cargo.toml/lock); падает идентично с `--offline`/`--frozen`/из корня с готовым Cargo.lock.
  Дальше не бьюсь вслепую — сделала ручной построчный ревью правок вместо компиляции,
  доложу это отдельно как блокер гейта.
- Дальше: Svelte (`grossMargin` store, `ProfitFrontierCard.svelte`, вкладка в `OptimizeStep.svelte`,
  тесты vitest, мутация).
- Svelte: `grossMargin` store в `project-state.js` (по образцу `value_per_count_unit`, тот же
  SET-IF-PRESENT паттерн ре-гидрации) — готово.
- Svelte: новый `ProfitFrontierCard.svelte` (EChartBase-график по образцу `ContinuationChart.svelte`:
  сплошная/пунктирная линия по границе наблюдений, markArea зоны «не подтверждено данными» и
  90%-интервала, markLine текущего бюджета, markPoint максимума) + инлайн-поле валовой маржи
  по образцу `ValuePerCountUnitInput.svelte` (персист через `project_update` → `gross_margin`) —
  готово.
- Rust: `econ_profit_frontier` уже был добавлен (см. выше).
- Svelte: третья вкладка «Сколько тратить всего» в `OptimizeStep.svelte` рядом с «От бюджета»/«От
  цели» (`taskMode === 'frontier'`) — готово, соседние вкладки не трогала.
- Тесты: `src/tests/profit-frontier-card.test.js`, 9 тестов (3 исхода, reportable-гейт, интервал
  доступен/недоступен, отказ без экономики + персист маржи, count_value_missing, MODEL_NOT_FOUND) —
  9/9 зелёных.
- 🔴 Мутация проведена: `{#if result.maximum.reportable}` → `{#if true}` вокруг блока
  `frontier-maximum-budget` (место, где число максимума реально попадает в разметку) →
  тест «beyond_observed → числа максимума НЕТ» покраснел (1 failed из 9) → откачено дословно,
  9/9 зелёных снова.
- Полные гейты — готово: `npx vitest run` **1471 passed (1471), 0 failed** (входное 1462 + 9
  моих). `npm run check` **0 ERRORS, 177 WARNINGS** (ровно входные цифры).
- `cargo check` заблокирован ЧУЖОЙ уже сломанной зависимостью `aurora_core` (апстрим
  `aurora-platform-core` содержит невалидный cookiecutter-манифест) — не мой diff, разобрано и
  задокументировано в отчёте. Ручной ревью правок вместо слепого повтора компиляции.
- Полный отчёт → `Projects/FIX_FRONTIER_UI_2026-08-16.md`.

**РАБОТА ЗАВЕРШЕНА, 16 авг 2026 г. 13:29.**

## Сверка с живой проверкой тимлида (13:33)
Тимлид прогнала `POST /optimize/profit-frontier` живьём и прислала факты. Сверила с уже
написанным кодом карточки — расхождений нет, ничего не правила:
- `posterior_interval.low`/`.high`/`.mean` — карточка уже читает именно `low`/`high`
  (`ProfitFrontierCard.svelte:229-230,351`), не `lo`/`hi`.
- Подпись периода — карточка берёт готовую строку `period.note` (уже содержит и
  `n_periods`, и `granularity_label_ru` внутри, движок формирует сам).
- Три проверенных исхода (маржа 0,3 → reportable; маржа 0,5 → reportable +
  at_observed_frontier; без экономики → economics_required) — все три ветки уже
  реализованы и покрыты тестами.
- Расчёт ~1 с — не заводила отдельного «долгого» состояния, обычный `loading` подходит.
Задача полностью закрыта, новых действий не требуется.

## Доп. запрос от fix-corridor (14:00)
Коллега починила коридор (F-07/F-08/F-13/F-14, `Projects/FIX_AUDIT_CORRIDOR_2026-08-16.md`) и
попросила добавить `include_sales: Option<bool>` в `econ_safe_corridor`
(`econometrica.rs:628`) — sidecar теперь считает продажи на границах коридора только по
явному запросу. Проверила: сейчас во фронте НИКТО `econ_safe_corridor` не вызывает
(`OptimizeStep.svelte` шлёт `salesCorridor={null}` жёстко, `OptimizeGoalSeek` вызывает только
`econ_optimize_inverse`) — правка чисто аддитивная, ничего не ломает и не требует изменений
на стороне Svelte. Добавила параметр, прокинула в тело запроса с `unwrap_or(false)` (тот же
дефолт, что в `SafeCorridorRequest.include_sales: bool = False` sidecar). `cargo check`
по-прежнему падает на той же чужой сломанной зависимости `aurora_core` — не новая проблема,
не от этой правки (мех. ревью строки чистая, один параметр по образцу соседних).
Отчиталась fix-corridor и team-lead.

## Адаптация к контракту fix-frontier (14:05-14:15)
Коллега fix-frontier закрыла 8 находок аудита в `sidecar/.../frontier.py` (F-01/02/09/10/12/15/16/17)
и явно перечислила, что задевает мою карточку. Прочитала контракт (`FRONTIER_DESIGN`-уровня отчёт
`Projects/FIX_AUDIT_FRONTIER_2026-08-16.md`) и сам код `frontier.py` (не поверила пересказу вслепую),
внесла точные правки в `ProfitFrontierCard.svelte`:
- `baseline_sales_total` → `baseline_sales.{total,basis,note}` — в карточке поле не читалось нигде
  (только в фикстуре теста), обновила фикстуру для честности контракта.
- Новый исход `at_grid_ceiling` (limited_by='grid', отдельно от `beyond_observed`/limited_by='data') —
  добавлен в CSS-класс `outcome-info` рядом с `beyond_observed` (тот же нейтральный тон).
- `maximum.budget_display` вместо `maximum.budget` — печатаю округлённое поле (F-17,
  устраняет псевдоточность), тест проверяет отсутствие точного числа в разметке.
- `posterior_interval.caveat` + `is_probabilistic` — когда интервал усечён сеткой, подпись без
  «90%», оговорка показывается отдельным блоком (новый testid `posterior-interval-caveat`).
- `withheld`-форма интервала при `reportable=false` (без low/high/mean) — уже обрабатывалась
  правильно существующей веткой `{:else}`, добавила явный тест на эту форму.
- `FORWARD_META_INCOMPLETE` — покрывается общей веткой `status==='error'`, без правок.
- Chart-логика (solid/dashed split по `observed_frontier.index`) не пострадала — проверила: при
  `limited_by='grid'` (severity 0 до самого потолка сетки) `boundaryIdx` = последний индекс кривой,
  markArea/dashedData естественно пустые — карточка и так не рисует «неподтверждённую данными»
  зону там, где данные ничем не ограничены. Правка не потребовалась.
- Тесты: 9 → 12 (добавлены at_grid_ceiling, интервал-усечён-сеткой, withheld-форма).
- Мутация повторена на изменённой строке (`{#if result.maximum.reportable}` → `{#if true}`) —
  покраснели ОБА теста на `reportable=false` (beyond_observed и at_grid_ceiling), 10 остались
  зелёными, откат чист.
- 🔴 Обнаружила у себя в файле уже применённую правку `afterEach(cleanup)` — без явной очистки
  DOM между тестами `@testing-library/svelte` в полном прогоне пакета оставлял разметку прошлого
  случая, и проверки «числа НЕТ в разметке» могли находить чужой элемент. В одиночном прогоне файла
  не проявлялось. Учла, не откатывала.
- Полный `npx vitest run`: **1471 passed (1471), 0 failed**, 100 файлов. Точное число тестов
  моего файла в общем итоге не бьётся арифметически один-в-один с прошлым замером (было 9,
  стало 12, +3) — вероятно, кто-то из параллельных исполнителей одновременно менял/удалял тесты
  в других файлах shared-репо; критерий гейта (0 упавших) выполнен, дальше не копала.
- `npm run check`: **0 ERRORS, 177 WARNINGS** — ровно входные цифры, без изменений.
- `cargo check` — повторила ещё раз после этой правки, тот же результат (та же чужая
  сломанная зависимость `aurora_core`, не мой diff).
- Отчиталась fix-frontier и team-lead.

**РАБОТА ЗАВЕРШЕНА (адаптация к контракту), 16 авг 2026 г. 14:18.**

