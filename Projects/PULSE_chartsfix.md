# PULSE chartsfix

Задача: 1) шаг декомпозиции — графики друг под другом (одна колонка), 2) шаг после обучения — разделить общую карточку "Разброс прогноза и остатки" на два самостоятельных графика со своим разворотом каждый, 3) починить фон разворота под тему + перевести цвета графиков (оси/сетка/подписи) на тема-зависимые значения через getBaseChartOption().

Область: только src/. НЕ трогать src-tauri/, sidecar/, tools/.

План:
- Шаг 1: прочитать DecomposeStep.svelte (.charts-grid ~1031-1038), поменять grid на одну колонку
- Шаг 2: прочитать ConvergenceDashboard.svelte:367, PPCScatter.svelte полностью (структура, .charts-row ~337-339, scatter ~71-158, remainder ~162-260)
- Шаг 3: разделить PPCScatter на два компонента/два блока разметки с двумя ExpandableCard, вынести общие вычисления
- Шаг 4: почитать ExpandableCard.svelte:227, echarts-setup.js:33-49, app.css темы (--bg-surface, --bg-surface-quiet)
- Шаг 5: починить фон оверлея (выбрать путь)
- Шаг 6: перевести цвета графиков PPCScatter/ConvergenceDashboard на тема-зависимые (getBaseChartOption + не хардкодить в option)
- Шаг 7: npm run check, отчёт

Старт: 2026-09-11 08:58

## Прогресс 09:10
- Шаг 1а ГОТОВО: DecomposeStep.svelte .charts-grid grid-template-columns 1fr 1fr → 1fr (строка ~1032). Файл завершён, не откатывать.
- Прочитан PPCScatter.svelte полностью (390 строк): scatterOption (строки 73-155) + residualsOption (159-273), разметка .charts-row (280-293), общие вычисления residuals/residualStats/r2Label/dwLabel/recencyColor используются в обоих.
- Прочитано начало ConvergenceDashboard.svelte (1-120): использует PPCScatter как <PPCScatter ppcData=.../> где-то около 367 (ещё не дошла до этой строки).
- Дальше: дочитать ConvergenceDashboard.svelte целиком (370-570, CSS), ExpandableCard.svelte, echarts-setup.js, app.css темы (--bg-surface/-quiet). Потом писать код.

## Прогресс 09:25
Прочитаны все нужные файлы (EChartBase.svelte, ExpandableCard.svelte:207-260, echarts-setup.js, app.css темы dark/light/fun строки 60-120,219-260,327-370).

Находки:
- EChartBase.svelte:37 `{...base, ...option}` — ПОВЕРХНОСТНОЕ слияние верхнего уровня. Если option задаёт свои xAxis/yAxis/title, они ПОЛНОСТЬЮ перекрывают base из getBaseChartOption(). Значит просто наличие getBaseChartOption недостаточно — сами хардкод-цвета в PPCScatter/ConvergenceDashboard заменяю на значения, читаемые из CSS-переменных темы (getComputedStyle), т.к. ECharts canvas не понимает var(--x) в строках цвета.
- --bg-surface НЕ объявлена нигде (подтверждено). --bg-surface-quiet объявлена во всех 3 темах и НЕПРОЗРАЧНА или почти непрозрачна везде: dark rgba(20,20,30,0.92), light #FFFFFF (100%), fun #EBE0C0 (100%) — значит просвечивание фону не создаёт риска. Решение: ExpandableCard.svelte:227 var(--bg-surface,...) → var(--bg-surface-quiet,...). Путь 1 (сущ. переменная), без объявления новой.
- --border-subtle корректно инвертируется по темам (dark rgba(255,255,255,.10) / light rgba(40,32,10,.14) / fun rgba(80,55,20,.20)) — годится заменить хардкод rgba(255,255,255,0.05-0.25) в осях/сетке/диагоналях.
- theme store (store.js:68) — обычный writable (Svelte 4 store), не rune. Для реактивности $derived.by на смену темы — подписываться через `$theme` внутри блока (как это уже делает EChartBase.svelte:112 `void $theme;`).

План правок (следующий шаг):
1. echarts-setup.js: добавить экспорт getAxisThemeColors() (textSecondary, borderSubtle, textPrimary) — переиспользуемый helper.
2. PPCScatter.svelte: импорт theme store + getAxisThemeColors, заменить хардкод в scatterOption/residualsOption (title/axis/grid), разбить на 2 компонента/карточки.
3. ConvergenceDashboard.svelte: заменить хардкод в rhatOption/avpOption аналогично; разметку Panel C заменить на два ExpandableCard.
4. ExpandableCard.svelte:227 — фон.
5. npm run check.

## Прогресс 09:40
- echarts-setup.js: добавлен export getAxisThemeColors() (textSecondary/textPrimary/borderSubtle/border/success из CSS-переменных темы). ГОТОВО, файл завершён.
- ExpandableCard.svelte:227 var(--bg-surface,#0f1115) → var(--bg-surface-quiet,#0f1115). ГОТОВО, файл завершён.
- Дальше: разбить PPCScatter.svelte на два самостоятельных графика (карточки "Разброс прогноза" + "Остатки"). Решение по архитектуре: PPCScatter.svelte остаётся (упрощается до scatter-only), новый файл PPCResidualsChart.svelte забирает график остатков. Оба вызываются из ConvergenceDashboard.svelte двумя отдельными ExpandableCard вместо одной общей.
- Найдены 2 теста, завязанные на старую структуру — потребуют мех. правки под новую (иначе сломаются): src/tests/ppc-scatter-sigma-band.test.js (импортирует PPCScatter, ищет "mean-2σ" — эта логика переезжает в PPCResidualsChart, тест переведу на новый импорт), src/tests/convergence-dashboard-ppc-panel.test.js (ищет текст "Разброс прогноза и остатки" — заголовок один, станет два: "Разброс прогноза" + "Остатки", тест обновлю на оба).

## Прогресс 09:55
- PPCScatter.svelte ПЕРЕПИСАН (scatter-only): убраны residuals/residualStats/dwLabel/residualsOption, .charts-row/.chart-cell(x2) → один .chart-cell, легенда без DW-бейджа. Цвета осей/сетки/подписей/диагонали переведены на getAxisThemeColors() (textSecondary/borderSubtle/border/success), реактивно на $theme. Файл ЗАВЕРШЁН.
- Новый файл PPCResidualsChart.svelte СОЗДАН: перенесены residuals/residualStats/dwLabel/residualsOption как есть (комментарий про баг sigma-band сохранён без изменений), цвета осей/подписей/zero-baseline переведены на getAxisThemeColors(), реактивно на $theme. Band fill (rgba(147,197,253,0.12)) и mean-line (#f59e0b) НЕ трогала — не белые, не ломаются на светлом фоне. Файл ЗАВЕРШЁН.
- Дальше: ConvergenceDashboard.svelte — импорт PPCResidualsChart, разметка Panel C на 2 ExpandableCard ("Разброс прогноза" / "Остатки"), разбить HELP.ppcChart на 2 текста, тема-цвета в rhatOption/avpOption. ЕЩЁ НЕ НАЧАТО в этом файле.

## Прогресс 10:15
- ConvergenceDashboard.svelte: импорт PPCResidualsChart + theme + getAxisThemeColors; rhatOption/avpOption переведены на getAxisThemeColors() (реактивно на $theme); HELP.ppcChart разбит на HELP.ppcScatterChart/HELP.ppcResidualsChart; Panel C/D — два ExpandableCard ("Разброс прогноза" / "Остатки") вместо одного. Файл ЗАВЕРШЁН.
- src/tests/convergence-dashboard-ppc-panel.test.js: обновлён под 2 заголовка (мех. правка, тест был завязан на старую структуру). Файл ЗАВЕРШЁН.
- src/tests/ppc-scatter-sigma-band.test.js: импорт/рендер переведены на PPCResidualsChart (та же проверка инварианта). Файл ЗАВЕРШЁН.
- grep подтвердил: нет других мест с "Разброс прогноза и остатки" на экране (кроме моего же исторического коммента) и нет мёртвых импортов в ConvergenceDashboard.
- Дальше: npm run check.

## ЗАВЕРШЕНО 09:52
npm run check: 0 ERRORS, 177 WARNINGS (столько же, сколько до правок) — новых предупреждений в тронутых файлах нет.
Полный отчёт: Projects/chartsfix_report.md.
