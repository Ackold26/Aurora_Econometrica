# MQS SSOT — перевод интерфейса на единый источник порогов (мой участок)

## Задача своими словами
В интерфейсе Econometrica живут четыре разные шкалы качества модели (MQS) — канон
85/70/55/40 из `mqs-tiers.js` (зеркало Python) и три самодельные лестницы 80/60 в
разных файлах, из-за чего один и тот же балл читается клиентом по-разному в соседних
окнах. Моя задача — перевести МОЙ участок дерева (8 файлов: insights-rules.js,
project-state.js, pipeline-tours.js, tooltip-texts.js, MQSBadge.svelte, ReportStep.svelte,
ExpertModelPanel.svelte, StepWrapper.svelte) на канон через `mqsTierInfo`/`mqsTone`/
`mqsIsDependable`/`mqsScaleText`, не трогая сам `mqs-tiers.js` и гард. Параллельно в
дереве работает другой агент над server.py/ConfigPanel/report.rs/ols_modeler — не мои
файлы, падения там не чиню.

## План
1. Прочитать `mqs-tiers.js` (сделано) — канон понятен.
2. Пройти по списку 21 нарушения файл за файлом, перевести на API канона.
3. Отдельно — прогнозный MQS (project-state.js:532, StepWrapper.svelte:53): перевести
   тоже, с оговоркой в тексте про «до обучения», отметить как расширение поверхности.
4. Прогнать гард → весь vitest → svelte-check, зафиксировать коды возврата.
5. Коммит своим pathspec, не пушить.

## Отметка старта
2026-07-26, ветка feat/econ-v2.3.0, HEAD 90eda78. pwd/toplevel совпадают с ТЗ.

## Пульс
- старт: план записан, приступаю к insights-rules.js
- insights-rules.js: готово, 6 мест (378, 1332/1338, 1458, 2266/2280-2282) переведены на
  mqsIsDependable/mqsTierInfo().tier; grep по файлу на голые сравнения mqs с числом чист.
- project-state.js:532: готово — mqsStatus 'ok'/'warn'/'bad' теперь строится из
  mqsTierInfo(mqs)?.tier (excellent/good→ok, acceptable→warn, weak/poor→bad), вокабуляр
  сохранён (совместим с CSS light-ok/light-warn/light-bad соседних chip'ов).
- pipeline-tours.js:79: готово — текст шкалы через mqsScaleText().
- tooltip-texts.js:82: готово — текст шкалы через mqsScaleText().
