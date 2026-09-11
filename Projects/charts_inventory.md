# Инвентаризация графиков — chartsrecon (только чтение)

Дата: 11.09.2026. Рабочая папка: `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt`.

## РАЗДЕЛ В-доп (углублённо, по уточнению владельца 11.09 после первого прохода). Родные графики pptx

Уточнение владельца: графики в колоде — родные chart part'ы PowerPoint (со своей книгой данных,
клиент открывает "Изменить данные" в PowerPoint), НЕ растровые картинки. Ниже — детальный разбор.

### В-доп.1 Полный перечень графиков, реально живущих в колоде
Во всём `aurora_pptx/builder.py` ровно ДВА вызова `slide.shapes.add_chart(...)` (grep `add_chart` по builder.py — строки 1852 и, транзитивно через `make_timeline_area`, `charts.py:180`):

| № | Где на слайде (комментарий-карта `builder.py:279-281`) | Тип (`XL_CHART_TYPE`) | Данные | Функция/место |
|---|---|---|---|---|
| 1 | Слайд 6, "Action chart (mROAS)" — ROI/mROAS по каналам | `BAR_CLUSTERED` (горизонтальные столбцы) | `self.channels` → `mroas` на канал (или инверсия в CPU для kpi_kind="count", или доля для "effectiveness"), до 10 каналов, `builder.py:1836-1842` | построен ad-hoc прямо в `builder.py:1841-1949`, НЕ через `charts.py` |
| 2 | Слайд 8, "Action timeline" — декомпозиция по периодам | `AREA_STACKED` (стек площадей) | `self.decomposition_series`/`self.time_series` → `baseline` + до 6 каналов + до 2 вынесенных факторов (внешние/конкуренты), `builder.py:2415-2468` | `charts.py:94-160` функция `make_timeline_area`, вызов `builder.py:2422,2467` |

Слайд 7 ("Action table") — таблица портфеля, БЕЗ графика.
**Waterfall-декомпозиции и "Share of Spend vs Effect" в колоде НЕТ вообще** — соответствующие функции в `charts.py` (`make_waterfall` — судя по докстрингу файла строки 1-15, тип 1; функция share-of-spend, тип 3, `COLUMN_STACKED_100`, строки 68-91) существуют как код, но ни разу не вызываются из `builder.py` (grep их имён по builder.py — 0 совпадений); докстринг файла прямо называет их "Currently stubs" (`charts.py:14`).
Итого в отгружаемой колоде **2 родных графика**, не 4.

### В-доп.2 Образец кода — как строится реально используемый график (ROI/mROAS, слайд 6)
`builder.py:1838-1862`:
```python
chart_data = CategoryChartData()
# Reversed: PPTX bar chart renders first category at bottom
chart_data.categories = list(reversed(bar_labels))
# v1.3.2: series label per KPI.
chart_data.add_series(self.kpi["metric_short"], list(reversed(bar_values)))

bar_area_x = chart_x
bar_area_y = chart_y + 0.75
bar_area_w = chart_w
bar_area_h = 2.9

graphic_frame = slide.shapes.add_chart(
    XL_CHART_TYPE.BAR_CLUSTERED,
    Inches(bar_area_x), Inches(bar_area_y),
    Inches(bar_area_w), Inches(bar_area_h),
    chart_data,
)
chart = graphic_frame.chart
chart.has_legend = False
chart.has_title = False
```
Значения (`bar_values`) — обычные `float`, без округления перед вставкой (`builder.py:1815-1832`: `bar_values = [float(c.get("mroas") or 0) for c in by_mroas]`). Округление задаётся только форматом ПОДПИСИ (`data_labels.number_format`, см. В-доп.3) — числа в самой книге данных остаются полной точности, значит претензия "точность теряется при подготовке" для этого графика фактами не подтверждается.

Второй реальный график (`make_timeline_area`, `charts.py:94-160`) устроен иначе — через `CategoryChartData` со сжатыми датами по оси X и множественными сериями (`data.add_series` в цикле по каналам, строки 164-171), тип `XL_CHART_TYPE.AREA_STACKED`.

### В-доп.3 Оформление
- **Цвета серий, график 1 (ROI/mROAS)** — `builder.py:1864-1868`: точка-герой (лучший канал) — `self.gold`, остальные — `self.deep_40`, оба через прямой цикл `for i, point in enumerate(series.points): point.format.fill.solid(); point.format.fill.fore_color.rgb = ...`. `self.gold`/`self.deep_40` — атрибуты экземпляра, заданы в `builder.py:212-217` через `hex_to_rgb(deep.get("100", "#0A1628"))` и т.п. (словарь темы `deep`/`gold` из content-pack, с ЛИТЕРАЛЬНЫМ hex-фолбэком на случай отсутствия ключа).
- **Цвета серий, график 2 (timeline)** — `charts.py:186-201`: baseline — `COLOR.brand.deep_40`, каналы — `COLOR.data.channel_colors[i % len(...)]` (циклическая палитра), факторы — `RGBColor.from_string(frgb or _FACTOR_RGB.get(ftype, '94A3B8'))`. `COLOR` — отдельный объект из `aurora_pptx/tokens.py` (`from .tokens import COLOR, FONT`, `charts.py:22`), собранный из того же файла токенов дизайна, но ЧЕРЕЗ ДРУГОЙ путь загрузки, чем `self.gold`/`self.deep_*` в `builder.py` (см. В-доп.4, п.1).
- **Подписи значений** — только на графике 1: `plot.has_data_labels = True` (`builder.py:1878`), формат по режиму KPI (`'0.0%'` / `'0" ₽/ед."'` / `'0.0"×"'`, строки 1880-1884), шрифт `Pt(10)`, `self.sans`, `self.deep_80` (1885-1887), позиция `XL_DATA_LABEL_POSITION.OUTSIDE_END` в `try/except` (1888-1892). График 2 (timeline) подписей значений НЕ имеет — только легенда.
- **Легенда** — график 1: `chart.has_legend = False` (1861, подписи заменяют легенду). График 2: `chart.has_legend = True; chart.legend.position = XL_LEGEND_POSITION.BOTTOM` (`charts.py:184-185`).
- **Шрифты/сетка/оси** — график 1: ad-hoc код прямо в `builder.py:1897-1918` (`cat_axis.tick_labels.font.*`, `cat_axis.format.line.fill.background()` — без линии оси; `val_axis.visible = False` — числовая ось скрыта вовсе, видны только подписи-числа на столбцах). График 2: через общий приватный хелпер `_style_chart_text(chart)` (`charts.py:26-38`, вызывается `charts.py:184`) — ставит шрифт/цвет `axis.tick_labels`, шрифт легенды.
- **Заголовков осей нет** ни у одного из двух графиков как отдельных элементов `chart` (`chart.has_title = False` явно на графике 1, строка 1862; заголовок слайда рисуется текстовым блоком до графика, не через `chart.chart_title`).

### В-доп.4 Оценка фактами (по запросу владельца — только наблюдения с адресом, без выводов "хорошо/плохо")
1. **Два независимых пути загрузки одних и тех же токенов цвета.** График 1 берёт цвет через `self.gold`/`self.deep_*`, присвоенные в конструкторе `Builder.__init__` (`builder.py:212-217`) из словаря темы с литеральными hex-фолбэками (`"#0A1628"`, `"#94A3B8"` и т.п. прямо в вызове `.get(key, "#...")`). График 2 берёт цвет через отдельно импортированный `COLOR` из `aurora_pptx/tokens.py` (`charts.py:22`, `COLOR.brand.deep_40`, `COLOR.data.channel_colors`). Это два разных программных пути к цвету для одной и той же колоды — не единая точка правки палитры.
2. **Стилизация осей/шрифта продублирована, а не переиспользована.** `charts.py:26-38` — функция `_style_chart_text(chart)`, написанная как общий помощник. Она вызывается для графика 2 (`charts.py:184`) и была бы применима и к графику 1 (тот же набор атрибутов `category_axis`/`value_axis`/`legend`), но график 1 в `builder.py:1897-1918` не вызывает `_style_chart_text`, а заново вручную повторяет ту же логику настройки шрифта осей отдельным кодом (`cat_axis.tick_labels.font.size = Pt(10)` и т.д. — сравни с `charts.py:29-38`, тот же набор из трёх свойств на `chart.category_axis`/`value_axis`).
3. **Обрезание длинных подписей категорий реализовано только в одном из двух графиков.** В `make_timeline_area` есть явная функция `_short(name)` (`charts.py:157-161`), обрезающая имя серии до 21-22 символов с многоточием — специально "чтобы легенда была читаемой" (докстринг строки 138-139 того же файла). У графика 1 (ROI/mROAS) аналогичной обрезки НЕТ: `bar_labels = [c.get("name") or "-" for c in by_mroas]` (`builder.py:1826` для ветки count, `1832` для остальных) передаётся в `chart_data.categories` без усечения — при длинных названиях каналов подписи категорий на узкой полосе (`bar_area_h = 2.9` дюйма на всю высоту графика с до 10 категорий, `builder.py:1848-1850`) кодом ничем не защищены от наложения/обрезки PowerPoint'ом.
4. **Точность данных при вставке не теряется** ни у одного из двух графиков (см. В-доп.2) — округление есть только в форматной строке подписи (`number_format`), сырые значения в книге данных chart part'а хранятся как есть (`float`, без `round()`).
5. **Пустые/отсутствующие данные не приводят к пустому графику молча** — у обоих есть явные ветки на этот случай, но по-разному:
   - график 1: если `self.channels` пусто/ложно — код подставляет фиксированный демонстрационный набор `bar_labels = ["Digital video", "Search", "TV", "OOH", "Social", "Print"]`, `bar_values = [1.9, 1.7, 1.5, 1.2, 1.0, 0.7]` (`builder.py:1830-1832`, комментарий "Kagocel pilot bars for preview / wireframe mode") — то есть при отсутствии реальных данных строится РЕАЛЬНЫЙ (не пустой) график, но с чужими цифрами примера, а не индикацией "нет данных"; ничего в самом слайде не помечает эти числа как демо-данные.
   - график 2: если условие `(ds and ds.get("series")) or (ts and ts.get("dates") and ts.get("baseline"))` ложно (`builder.py:2415`) — родной график вообще НЕ строится; вместо него выполняется отдельная ветка `builder.py:2487+` ("Legacy preview/wireframe path"), которая рисует стилизованные прямоугольники через `self._rect(...)` (не `add_chart`) — то есть здесь при отсутствии данных вместо родного графика подставляется другой визуал, не "пустой график".
Оба поведения задокументированы в коде как намеренный "preview/wireframe mode" (сквозной паттерн, тот же комментарий "Kagocel pilot" встречается ещё в ~15 местах `builder.py` для других секций колоды) — то есть это не забытый частный случай, а системная конвенция всего файла.

### В-доп.5 Какие типы родных графиков доступны в установленной версии библиотеки
`requirements.txt:35`: `python-pptx>=0.6.21`; фактически установлена `python-pptx 1.0.2` (проверено `python -c "import pptx; print(pptx.__version__)"`).
Проверка перечня `XL_CHART_TYPE` в этой версии (`python -c "from pptx.enum.chart import XL_CHART_TYPE; ..."`) показала наличие: `XY_SCATTER`, `XY_SCATTER_LINES`, `XY_SCATTER_LINES_NO_MARKERS`, `XY_SCATTER_SMOOTH`, `XY_SCATTER_SMOOTH_NO_MARKERS`, `LINE`, `LINE_MARKERS`, `LINE_MARKERS_STACKED`, `LINE_MARKERS_STACKED_100`, `LINE_STACKED`, `LINE_STACKED_100`, `THREE_D_LINE`.
То есть **разброс (`XY_SCATTER`) и линия с маркерами (`LINE_MARKERS`) родными средствами установленной библиотеки поддерживаются** — построить "остатки против прогноза" (scatter) и/или линию остатков во времени с маркерами штатным `add_chart` технически можно.
При этом класс `XyChartData` (нужен именно для scatter/XY-графиков, в отличие от `CategoryChartData`) **импортирован, но нигде не используется**: `charts.py:19` — `from pptx.chart.data import CategoryChartData, XyChartData`; `grep "XyChartData(" по всем *.py aurora_pptx` — 0 совпадений создания экземпляра. Сейчас в колоде нет ни одного XY/scatter-графика — оба реально работающих графика используют `CategoryChartData`.

### В-доп.6 Общий источник рядов между колодой и веб-отчётом
Оба построителя не готовят данные независимо с нуля — есть общий модуль-адаптер: `engines/narrative_adapter.py`.
- `engines/pptx_export.py:33-46` явно документирует это: "Narrative content ... promoted to shared module so HTML builder consumes the same business-logic ... Re-exported here for backward compat" — и реэкспортирует `_map_pipeline_to_builder_data`, `derive_verdict`, `_derive_narrative_facts`, `_merge_channels` из `narrative_adapter`.
- `engines/html_export.py:30` импортирует ТУ ЖЕ функцию: `from .narrative_adapter import _map_pipeline_to_builder_data`.
- Скалярные диагностики качества (`mqs_score`, `r_squared`, `mape_pct`, `r_hat_max`, `ess_min`) собираются в общий словарь `diagnostics` внутри `narrative_adapter.py:977-1000` один раз и используются обоими выходами (в pptx читаются как `self.r_squared` и т.п., в html — как `ctx["diagnostics"][...]`).
- 🔴 Но именно ряд `actual_vs_predicted` (массивы `actual`/`predicted`, нужные для scatter/остатков) через `narrative_adapter.py` НЕ прокидывается: `grep "actual_vs_predicted" по narrative_adapter.py` — 0 совпадений. Он существует в исходном `diagnostics` от движка (`engines/modeler.py:1538-1542`, см. Раздел В.3 ниже), но в `builder_data`/`ctx`, которые получают оба построителя отчётов, сейчас не попадает — если добавлять такой график, сырые ряды нужно новой строкой прокинуть через `narrative_adapter._map_pipeline_to_builder_data` (по образцу того, как туда уже прокинуты скалярные `r_squared`/`r_hat_max`), а не изобретать отдельный путь данных для каждого из двух выходов.

## РАЗДЕЛ А. Графики интерфейса

### А.1 «Разброс прогноза и остатки» (шаг обучения модели)
- Карточка: `src\lib\components\pipeline\ConvergenceDashboard.svelte:367` — `<ExpandableCard title="Разброс прогноза и остатки">`, внутри — `<PPCScatter {ppcData} />` (одна карточка на ОБА графика, не две).
- Оба графика рисует `src\lib\components\pipeline\PPCScatter.svelte`:
  - левый («Факт vs Прогноз», scatter+диагональ) — `scatterOption`, строки 71-158;
  - правый («Остатки», линия+полоса mean±2σ) — `residualsOption`, строки 162-260.
  - Оба рендерятся через `EChartBase` (`src\lib\components\charts\EChartBase.svelte`) — библиотека **ECharts** (`src\lib\echarts-setup.js`).
  - Вёрстка рядом: `PPCScatter.svelte:315` класс `.charts-row` → `display: grid; grid-template-columns: 1fr 1fr;` (строки 337-339), брейкпоинт на колонку только `@media (max-width: 640px)` (341-343).
  - Оба графика — общий проп `ppcData`, общий `<ExpandableCard>`: разворот на весь экран **один на оба сразу**, независимого разворота каждого графика нет (нет двух `ExpandableCard`, есть один, оборачивающий компонент с внутренней сеткой).

### А.2 Шаг декомпозиции
- `src\lib\components\pipeline\DecomposeStep.svelte:662-686`:
  - `ExpandableCard title="Декомпозиция продаж"` (waterfall, во всю ширину, строка 663) — рисует `WaterfallChart.svelte` через `EChartBase` (`WaterfallChart.svelte:17,181`, тип bar).
  - Далее `<div class="charts-grid">` (строка 667) с ДВУМЯ ОТДЕЛЬНЫМИ `ExpandableCard`:
    - `title="Расходы vs Эффект"` (669) → `ChannelComparisonChart.svelte` (через `EChartBase`);
    - `title="Динамика по периодам"` (672) → `ChannelTimeline.svelte` (через `EChartBase`).
  - `.charts-grid` определён в `DecomposeStep.svelte:1031-1038`: `display: grid; grid-template-columns: 1fr 1fr; gap: 16px;`, стек в 1 колонку только `@media (max-width: 900px)`.
  - Здесь у каждого графика УЖЕ отдельный `ExpandableCard` → разворот на полный экран уже независим у соседей (это уже так в коде, не нужно чинить).

### А.3 Полный перечень графиков интерфейса, обёрнутых в `ExpandableCard` (grep `ExpandableCard title=` по `src`):
| Файл:строка | Заголовок карточки | Компонент/движок |
|---|---|---|
| `ConvergenceDashboard.svelte:320` | R-hat по параметрам | `EChartBase` (bar), опция `rhatOption` строки 27-70 |
| `ConvergenceDashboard.svelte:334` | Факт vs Прогноз | `EChartBase` (line/scatter), опция `avpOption` (см. блок 300-358) |
| `ConvergenceDashboard.svelte:367` | Разброс прогноза и остатки | `PPCScatter.svelte` → 2× `EChartBase` внутри (см. А.1) |
| `DecomposeStep.svelte:663` | Декомпозиция продаж | `WaterfallChart.svelte` → `EChartBase` |
| `DecomposeStep.svelte:669` | Расходы vs Эффект | `ChannelComparisonChart.svelte` → `EChartBase` |
| `DecomposeStep.svelte:672` | Динамика по периодам | `ChannelTimeline.svelte` → `EChartBase` |
| `MultiScenarioChart.svelte:331` | заголовок динамический (`chartTitle`) | `EChartBase` |
| `OptimizeStep.svelte:2502` | Response Curves | `EChartBase` |

Прочие графические компоненты, использующие `EChartBase` (grep `EChartBase|<svg viewBox` по `src\lib\components\pipeline`): `SensitivityTornado.svelte:15,276`, `ChannelComparisonChart.svelte`, `ProfitFrontierCard.svelte`, `ContinuationChart.svelte`, `ChannelTimeline.svelte`, `WaterfallChart.svelte:17,181`, `MultiScenarioChart.svelte` — все на ECharts.
`CorrelationHeatmap.svelte` — grep `EChartBase|<svg` не дал совпадений: это НЕ ECharts и не свой SVG, а собственная HTML/CSS-раскладка (тепловая карта на div-сетке); не обёрнут в `ExpandableCard` (не встречается в списке А.3).

Вывод А: единственная используемая в интерфейсе библиотека графиков — **ECharts** через общий враппер `EChartBase.svelte`, кроме `CorrelationHeatmap.svelte` (своя HTML/CSS-вёрстка, не график в строгом смысле).

## РАЗДЕЛ Б. Разворот на полный экран

### Б.1 Механизм
`src\lib\components\ExpandableCard.svelte` — не `:fullscreen`, не браузерный API, а свой компонент-оверлей на `$state(false) expanded` (строка 24) + `{#if expanded}` рендерит `<div class="overlay">` (fixed, `position: fixed; inset: 0; z-index: 1000;`, строки 208-220) с фоном-блюром. Esc и клик по backdrop сворачивают (строки 26-48). `body.overflow = 'hidden'` пока открыт (37).

### Б.2 Почему оверлей всегда тёмный — причина найдена в коде
`ExpandableCard.svelte:227`: `background: var(--bg-surface, #0f1115);` — фон оверлея.
Проверка (`grep -- "--bg-surface:" по всему src`) показала: переменная **`--bg-surface` НИГДЕ не объявлена** ни в `src\app.css`, ни в `src\tokens.generated.css`, ни где-либо ещё в `src`. Есть только `--bg-surface-quiet` и `--bg-surface-focus` (`app.css:102-103` тёмная тема, `228-229` светлая, `336-337` «фан»). Раз `--bg-surface` не определена ни для одного `[data-theme]`, CSS всегда падает на fallback-значение `#0f1115` (тёмный) из самого `var(...)` — **вне зависимости от выбранной темы**. Это прямая причина: не «жёстко зашитый цвет» вообще, а фолбэк несуществующей переменной, который де-факто работает как жёстко зашитый цвет.
Остальные переменные оверлея (`--text-primary` в строке 246, `--border` в 228) — определены на все три темы (см. Б.4) и реально переключаются; несовпадение фона (всегда тёмный) с текстом (цвет по теме) даёт визуально «половинчатую» тему у оверлея.
Фон подложки `.overlay` (212): `color-mix(in srgb, #000 58%, transparent)` — тоже хардкод, но это подложка-затемнение снаружи карточки, а не тело карточки.

### Б.3 Разворачивается ли пара графиков целиком или по отдельности
Для «Разброс прогноза и остатки» — целиком (см. А.1: один `ExpandableCard` на оба графика; `.overlay-content :global(> *)` в `ExpandableCard.svelte:279-284` растягивает единственного прямого потомка — `.ppc-scatter`, у которого `.charts-row` остаётся `grid-template-columns: 1fr 1fr` и в развёрнутом виде тоже, кроме ширины <640px).
Для декомпозиции — уже по отдельности (два `ExpandableCard`, см. А.2), это в коде уже так работает.

### Б.4 Устройство тем
- Хранение выбора: `src\lib\store.js:68` — `export const theme = createPersistentStore('ai-agency-theme', 'dark')`.
- Переключение: `cycleTheme()` (`store.js:140-145`) — цикл `dark → light → fun → dark`.
- Применение к DOM: `src\routes\+layout.svelte:136-143` — подписка на `theme`; если `t === 'dark'` → `document.documentElement.removeAttribute('data-theme')` (тёмная тема = отсутствие атрибута = состояние по умолчанию), иначе `setAttribute('data-theme', t)` (`'light'`/`'fun'`).
- Переменные цвета в `src\app.css`: базовые (тёмная тема, по умолчанию) — `:root { ... }` строки 35+ (`--text-primary` 62, `--border` 70, `--bg-surface-quiet` 102, `--bg-surface-focus` 103); светлая — `[data-theme="light"] { ... }` строки 219+ (`--text-primary` 243, `--border` 259, `--bg-surface-quiet` 228); «фан» — `[data-theme="fun"] { ... }` строки 327+ (`--text-primary` 361, `--border` 367, `--bg-surface-quiet` 336).
- Графики (ECharts) в `PPCScatter.svelte` и `ConvergenceDashboard.svelte` **не используют** эти переменные — они задают цвета осей/сетки/подписей литералами (`#94a3b8`, `rgba(255,255,255,0.05)` и т.п., см. `PPCScatter.svelte:104-158,178-260`, `ConvergenceDashboard.svelte:34-70`) напрямую в объекте `option`, а не через готовый тема-зависимый `getBaseChartOption()` (`src\lib\echarts-setup.js:33-49`, читает `--text-primary`/`--text-secondary`/`--border-subtle` из `getComputedStyle(document.documentElement)`). `EChartBase.svelte:37` делает `chart.setOption({ ...base, ...option })` — JS-спред на верхнем уровне, поэтому ключи (`xAxis`, `yAxis`, `title`, `tooltip`), заданные литералами в `option`, полностью перекрывают тема-зависимые значения из `base` уже при первой отрисовке. Значит эти конкретные графики оформлены под тёмную тему постоянно, независимо от общего переключателя (это отдельная, более широкая причина «не по теме», чем п. Б.2 — тот только про фон/рамку самого оверлея).

## РАЗДЕЛ В. Отчёты

### В.1 Колода (pptx)
- Строится в `sidecar\econometrica\aurora_pptx\builder.py` (раздел про качество модели/данные — слайд "Источники и качество", intro строка 1579 `"Метрики качества модели и спецификация"`, сама MQS-карточка строки ~3200-3330).
- Сейчас на этом слайде — только ЧИСЛА/ТЕКСТ: большая цифра MQS (3247-3260), текстовые метрики `R²`, `MAPE`, `R-hat`, `ESS` (строки 3316-3330 и повтор 3081-3090) — **никакого графика** (ни actual-vs-predicted, ни остатков) на этом слайде нет.
- Как в колоду попадают изображения/графики вообще: `sidecar\econometrica\aurora_pptx\charts.py` — **нативные PPTX-диаграммы** через `python-pptx` `slide.shapes.add_chart(...)` (не растровые картинки, не matplotlib): `make_roi_bar` (строки 40-59, `BAR_CLUSTERED`), плюс по докстрингу файла (строки 1-15) ещё Waterfall (`BAR_STACKED`), Share of Spend vs Effect (`COLUMN_CLUSTERED`), Timeline (`AREA_STACKED`).
- Реально ВЫЗЫВАЕТСЯ из `builder.py` только один из четырёх — `make_timeline_area` (импорт `builder.py:2422`, вызов `builder.py:2467`, для слайда декомпозиции/timeline). `make_roi_bar` и прочие функции `charts.py` по докстрингу файла помечены "Currently stubs" и grep вызовов из `builder.py` их не находит — то есть на практике задействован только timeline-график из декомпозиции, MQS-слайд графиков не строит вообще.

### В.2 Веб-отчёт (`sidecar/econometrica/aurora_html/`)
- `aurora_html\__init__.py:7` — технология: **инлайновый ECharts (SVG-рендерер) + встроенные шрифты WOFF2**, т.е. та же библиотека, что и в интерфейсе.
- `aurora_html\interactive.py:408,493-496` — реально собран и подключён **только один интерактивный график — waterfall** (`buildWaterfallOption`, `initChart('chart-waterfall', ...)`). Других `initChart(...)` вызовов/`buildXxxOption` функций в файле нет.
- Раздел про качество модели (`aurora_html\sections.py`, MQS-блок строки 615-1004) выводит только текст/число (`mqs_score`, `r_squared` фигурируют в prose и в findings-шаблонах, например строки 3316-3330-эквивалент для HTML — `f5_mqs*` шаблоны) — интерактивного или картиночного графика качества модели в HTML-отчёте сейчас нет.

### В.3 Какие данные о качестве модели уже посчитаны и доступны движку
| Величина | Где считается/лежит | Всегда или по условию |
|---|---|---|
| `actual` / `predicted` (факт vs прогноз, с датами) | `engines\modeler.py:1538-1542` → `diagnostics['actual_vs_predicted'] = {'actual': [...], 'predicted': [...], 'dates': [...]}` | всегда после обучения (байесовская ветка) |
| Остатки (факт − прогноз) | НЕ хранятся отдельным полем; клиент считает на лету из actual/predicted (`PPCScatter.svelte:31-34`, `residuals = actual[i] - predicted[i]`) | производная величина, легко посчитать из actual_vs_predicted |
| `R²` | `diagnostics['metrics']['r_squared']` (читается в `ConvergenceDashboard.svelte:183` и `aurora_pptx\builder.py:3081` и др.) | всегда |
| `MAPE` (in-sample) | `diagnostics['metrics']` → `self.mape_pct` в pptx (`builder.py:316,3082`) | всегда |
| `R-hat` (max, по параметрам) | `diagnostics['per_param_rhat']` (`modeler.py:1494`), max — `self.r_hat_max` в pptx (`builder.py:3090`) | всегда (байесовская ветка, MCMC) |
| `ESS` (эффективный размер выборки) | `self.ess_min` (`builder.py:3299-3301`) | всегда (байесовская ветка) |
| Бэктест/отложенные данные (`mape_model`, `mape_naive_best`) | `engines\backtest.py`, читается в `builder.py:3640-3650` | по условию (если бэктест запускался) |
| `Durbin-Watson` (устойчивость остатков) | **НЕ считается нигде в движке** — прямо зафиксировано комментарием `ConvergenceDashboard.svelte:175`: «durbin_watson в движке нигде не считается — не передаём» | не существует |
| Сезонность (обнаружена/период/автокорр.) | `diagnostics['seasonality']` (`modeler.py:1508-1516`) | по условию (если сезонность считалась) |

### В.4 Есть ли в движке готовый рисовальщик изображений (matplotlib/plotly/kaleido)
**Нет.** Проверка `grep "matplotlib|plotly|kaleido"` по `aurora_pptx/*.py` и `aurora_html/*.py` — 0 совпадений. Единственные два канала вывода графики — (а) нативные объекты диаграмм PowerPoint через `python-pptx add_chart` (`aurora_pptx\charts.py`) и (б) инлайновый ECharts/SVG в HTML-отчёте (`aurora_html`). Растрового рендерера (картинки PNG из данных) в движке не найдено — поэтому «повторить графики интерфейса 1-в-1 как картинку» готового инструмента нет; путь либо через нативные pptx-диаграммы (для колоды), либо через тот же ECharts (для веб-отчёта, раз библиотека уже там встроена и инлайнится).
