# FIX tidy-ui 2026-08-16 — снятие ложных обещаний в интерфейсе

Ветка: `feat/econ-p1-winning`. Ничего не коммичено, ветки не создавались.

## Пункт 1 — подсказки про интерполяцию пропусков

**Факт (подтверждён до правки):** движок заполняет пропуски нулём (`sidecar/econometrica/engines/modeler.py` `.fillna(0)`), интерполяции в коде нет. `validator.py:618-631` уже говорит правду для роли `media/control`: «При обучении они считаются нулём... Восстановления пропущенных значений в расчёте нет».

### `src/lib/data/tooltip-texts.js:137`
Было:
> «Пропуски (NaN) – строки без значений. В отличие от нулей, пропуски ломают регрессию. Программа интерполирует малые пробелы; при > 20% пропусков лучше исключить столбец.»

Стало:
> «Пропуски (NaN) – строки без значений. В отличие от нулей, пропуски ломают регрессию. При обучении они считаются нулём, то есть «активности не было» – восстановления пропущенных значений в расчёте нет, заполните их до обучения. При > 20% пропусков лучше исключить столбец.»

### `src/lib/insights-rules.js:752` (tip внутри правила «Пропуски >5%»)
Было:
> tip: «Линейная интерполяция заполнит небольшие пробелы. При >20% пропусков столбец лучше исключить или найти альтернативный источник.»

Стало:
> tip: «При обучении пропуски считаются нулём, то есть «активности не было» – восстановления пропущенных значений в расчёте нет, заполните их до обучения. При >20% пропусков столбец лучше исключить или найти альтернативный источник.»

Требования выполнены: короткое тире «–» (не «—»), русский без англицизмов, совет про >20% сохранён, смысл приведён к формулировке валидатора. Правки текстовые — юнит-тестами не покрыты, gate `npm run check` (0 ошибок) подтверждает валидность синтаксиса.

## Пункт 2 — карта для ИИ-советника, три формата отчёта

**Факт (подтверждён до правки):** три Rust-команды экспорта существуют (`econ_export_pptx`, `econ_export_xlsx`, `econ_export_html`), а `src/lib/program-help.js:67` называл только HTML. Этот файл уходит в `src/lib/tier2-context.js:18` в контекст советника.

`src/lib/program-help.js:67`
Было: `'7. Отчёт – выгрузка результата в HTML (печать/конвертация в PDF снаружи).'`
Стало: `'7. Отчёт – выгрузка результата в PPTX, XLSX или HTML (печать/конвертация в PDF снаружи).'`

## Пункт 3 — нерабочая кнопка «Excel (.xlsx) – сравнение»

**Факт (подтверждён до правки):** `exportToExcel` в `src/lib/scenario-export.js` звала `invoke('econ_export_scenarios_xlsx', …)` — такой Rust-команды в `src-tauri/src/` нет (grep — 0 совпадений). Вызов всегда падал в `catch`, пользователь всегда получал заглушку «Excel export временно недоступен».

Убрано (прецедент — PPTX-кнопка убрана 2026-08-03 тем же способом):
- `src/lib/components/pipeline/MultiScenarioPage.svelte`: импорт `exportToExcel` (был на `:29`), функция `handleExportExcel` (была на `:296-313`), пункт меню «Excel (.xlsx) - сравнение» (был на `:560-564`).
- `src/lib/scenario-export.js`: сама функция `exportToExcel` (JSDoc + тело, была на `:140-190`); заголовочный докстринг модуля обновлён (убрано упоминание Excel/XLSX как рабочей возможности, добавлена строка о причине удаления — «Rust-команда никогда не существовала, XLSX-выгрузка в бэклоге»).

CSV-выгрузка сценариев не тронута, работает как прежде.

Проверка ссылок:
```
grep -rn "exportToExcel\|econ_export_scenarios_xlsx" src/ src-tauri/
```
Результат — только ожидаемые упоминания: комментарий в `scenario-export.js` (объясняет удаление) и тест `scenario-export.test.js` (правился в пункте 4).

## Пункт 4 — сторож на фантомную функцию → сторож на отсутствие обещания

**Факт (подтверждён до правки):** `src/tests/scenario-export.test.js:315-341` (`describe('exportToExcel - invoke mock')`) мокал `invoke` успехом и проверял путь, которого в продукте никогда не было — зелёный всегда, ничего не защищал.

**Что сделала:**
1. Прочитала образец перевёрнутого PPTX-сторожа в `src/tests/multi-scenario-page.test.js:339-350` (комментарий с датой/причиной + `expect(screen.queryByText(/PPTX/)).not.toBeInTheDocument()`).
2. В `src/tests/scenario-export.test.js`: убрала импорт `exportToExcel`, убрала весь блок Suite 6 (4 теста-фантома), заменила на модульный сторож:
   ```js
   describe('scenario-export module - no exportToExcel (removed 2026-08-16)', () => {
     it('does not export exportToExcel (backend econ_export_scenarios_xlsx never existed)', () => {
       expect(scenarioExportModule.exportToExcel).toBeUndefined();
     });
   });
   ```
   Обновила докстринг заголовка файла (пункт про `exportToExcel` заменён на пункт про отсутствие экспорта).
3. **Побочная находка (не в списке пунктов, но прямое следствие пункта 3):** в `src/tests/multi-scenario-page.test.js:330-337` был тест `'Export dropdown contains Excel option'`, который после удаления кнопки в пункте 3 стал бы падать. Починила по тому же образцу — перевернула в сторож отсутствия:
   ```js
   it('Export dropdown does not offer Excel (no working backend command)', async () => {
     ...
     expect(screen.queryByText(/Excel/)).not.toBeInTheDocument();
   });
   ```
   с тем же стилем комментария, что у соседнего PPTX-сторожа (дата, причина, ссылка на прецедент).

**Проверка «внести-поймать-откатить» (выполнена, красное реально наблюдалось):**
- Мутация 1: временно вернула пункт меню `<button>Excel (.xlsx) - сравнение</button>` в `MultiScenarioPage.svelte` (без обработчика).
- Мутация 2: временно вернула `export async function exportToExcel() { return { stub: true }; }` в `scenario-export.js`.
- Прогон `npx vitest run src/tests/scenario-export.test.js src/tests/multi-scenario-page.test.js` → **2 failed из 67**, оба новых сторожа:
  - `does not export exportToExcel (...)` — `AssertionError: expected [AsyncFunction exportToExcel] to be undefined`
  - `Export dropdown does not offer Excel (...)` — нашёл кнопку в DOM, `expect(...).not.toBeInTheDocument()` упал.
- Откатила обе мутации.
- Повторный прогон тех же двух файлов → **67 passed (67)**.

## Гейты (числа)

```
npx vitest run   →  Test Files  99 passed (99) | Tests  1462 passed (1462)
npm run check    →  4158 FILES  0 ERRORS  177 WARNINGS  31 FILES_WITH_PROBLEMS
```

Входные значения для сравнения: было ~1423 теста / 0 ошибок типов. Ошибок типов по-прежнему 0 (совпадает). Число тестов **выросло** (1423 → 1462), не уменьшилось — падений объяснять не нужно по правилам гейта, но для полноты: чистый эффект моих правок на количество тестов — минус 3 (Suite 6: было 4 теста-фантома → стал 1 сторож), название одного теста в multi-scenario-page.test.js изменено без изменения счётчика. Разница с базовым числом (~1423) — за счёт остального объёма веток/сессий в общем репозитории, не моих правок; все 177 warnings из `check` — в файлах, не тронутых этой задачей (`+page.svelte`, `cabinet/+page.svelte`, `settings/+page.svelte`, `workflow/+page.svelte`, `data-chat/+page.svelte`), pre-existing.

## Затронутые файлы
- `src/lib/data/tooltip-texts.js`
- `src/lib/insights-rules.js`
- `src/lib/program-help.js`
- `src/lib/components/pipeline/MultiScenarioPage.svelte`
- `src/lib/scenario-export.js`
- `src/tests/scenario-export.test.js`
- `src/tests/multi-scenario-page.test.js` (побочная правка — сломанный тест-следствие пункта 3)

РАБОТА ЗАВЕРШЕНА 16 авг 2026 г. 12:20:43
