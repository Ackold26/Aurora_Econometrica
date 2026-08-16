# PULSE tidy-ui 2026-08-16

## Задача (своими словами)
Снять ложные обещания в интерфейсе Econometrica: (1) переписать две подсказки про интерполяцию пропусков — движок реально заполняет их нулём, интерполяции нет; (2) исправить карту для ИИ-советника — реально три формата отчёта (PPTX/XLSX/HTML), а не один HTML; (3) убрать нерабочую кнопку «Excel – сравнение» в MultiScenarioPage (команда `econ_export_scenarios_xlsx` не существует, всегда падает в catch); (4) переписать тест-сторож, который сейчас мокает успех несуществующей команды, на сторож «отсутствие обещания».

## План
1. Пункт 1 — tooltip-texts.js:137 + insights-rules.js:752
2. Пункт 2 — program-help.js:67
3. Пункт 3 — MultiScenarioPage.svelte (кнопка/handler/import) + scenario-export.js (exportToExcel)
4. Пункт 4 — scenario-export.test.js: прочитать образец PPTX-сторожа, переписать блок Excel, прогнать внести-поймать-откатить
5. Гейты: npm run test:unit -- --run, npm run check
6. Отчёт FIX_TIDY_UI_2026-08-16.md

## Отметки
- 12:10 — старт, PULSE создан, план готов.
- 12:14 — пункт 1 готов: tooltip-texts.js:137 и insights-rules.js:752 переписаны (нуль вместо интерполяции, восстановления нет, >20% совет сохранён).
- 12:14 — пункт 2 готов: program-help.js:67 — «PPTX, XLSX или HTML» вместо только HTML.
- 12:20 — пункт 3 готов: убраны кнопка/handleExportExcel/импорт в MultiScenarioPage.svelte, exportToExcel из scenario-export.js, обновлён докстринг модуля. grep подтвердил ноль ссылок вне теста (тест правится следующим пунктом).
- 12:25 — пункт 4 готов: Suite 6 в scenario-export.test.js заменена на сторож «модуль не экспортирует exportToExcel»; попутно нашла и починила аналогичный сломанный тест «Export dropdown contains Excel option» в multi-scenario-page.test.js (падал из-за удаления кнопки в п.3) — перевёрнут по образцу соседнего PPTX-сторожа. Внести-поймать-откатить: временно вернула кнопку в MultiScenarioPage.svelte + временную exportToExcel в scenario-export.js → оба новых теста покраснели (подтверждено выводом vitest) → откатила обе мутации → оба теста снова зелёные, полный прогон двух файлов 67/67 passed.
- 12:20 (после полного прогона) — гейты зелёные: vitest 1462/1462 passed (99 файлов), npm run check 0 ERRORS / 177 WARNINGS (все в нетронутых файлах). Отчёт дописан в FIX_TIDY_UI_2026-08-16.md. РАБОТА ЗАВЕРШЕНА.
