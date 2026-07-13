# IMPL_B2 — Батч 2 аудита промптов Авроры (2026-07-13)

## 2.2 + 2.3 + частично 2.5 — program-help.js

Файл: `src/lib/program-help.js`

- Строка 8 (комментарий): «6 шагов» → «7 шагов».
- PROGRAM_OVERVIEW (строки 36-99, литералы уходящие в промпт):
  - «Пайплайн – 6 шагов:» → «Пайплайн – 7 шагов:», вставлен новый шаг
    «6. Планирование – квартальный медиаплан на основе модели: распределение
    бюджета по периодам с учётом сезонности и целей, опционально поверх
    оптимизации.» между Оптимизацией (5) и Отчётом (теперь 7). Порядок сверен
    с `project-state.js:74-82` PIPELINE_STEPS (import, validate, model,
    decompose, optimize, planning, report) и с STEP_TERMS/STEP в
    program-help.js/tier2-context.js (5=planning, 6=report) — уже были
    согласованы, только текстовая карта отставала.
  - «доверительный интервал» → «правдоподобный диапазон» (2 места: строка 47
    «шире доверительные интервалы» → «шире правдоподобные диапазоны»; строка
    72-73 «доверительный интервал (90%)» → «правдоподобный диапазон (90%)»,
    и следом «Широкий интервал» → «Широкий диапазон»). Больше вхождений
    термина в файле не найдено (grep чистый).
  - Заодно вся PROGRAM_OVERVIEW (все литералы) переведена с U+2014 «—» на
    U+2013 «–» (часть задачи 2.5, см. ниже) — правила это разрешают, т.к. эти
    строки прямо редактировались по 2.2/2.3.
- STEP_TERMS (строки 106-114) уже были 0..6 (7 шагов) — не менял, тест
  «все шаги 0..5 заданы» (program-help.test.js:107-111) проверяет подмножество
  0..5, шаг 6 существует дополнительно — тест не ломается, шаг 7 (report)
  и так был.
- Тест `src/lib/__tests__/program-help.test.js` — числа шагов там нигде явно
  не зашиты («6» не встречается), правка не потребовалась.

Проверено grep на остаток: U+2014 в program-help.js — только в комментариях
(строки 6,10,11,15,22,23,24,32,105,142). «Доверительн*» — 0 вхождений.

## 2.1 — страж INV-50 на scenarioInterpretation

Файл: `src/lib/components/pipeline/InsightsPanel.svelte`

Зеркалила паттерн askAI (строки ~420-430) на runScenario:
- Добавлено состояние `scenarioUngrounded` (аналог `askUngrounded`), сброс в
  `resetScenario()` и в начале `runScenario()`.
- После `scenarioInterpret = sanitizeAvroraText(await callAurora(interpPrompt))`
  добавлен вызов `findUngroundedNumbers(scenarioInterpret, { jsonFacts: [result, collinearWarn] })`
  — grounding source = весь объект результата `econ_scenario` (totals + прочее,
  зеркалит fullFacts из tier2-context.js) плюс текст оговорки о коллинеарности
  (её r≈0.NN легитимен для цитирования).
- UI: в блоке `{#if scenarioInterpret}` добавлен `⚠ Числа не сверены с
  моделью: ...` тем же классом `.ask-warn`, что и у askAnswer (строки ~760-767).
- `sanitizeAvroraText` не тронут — ground-проверка добавлена РЯДОМ, как
  просил Антон.

## 2.4 — нейтрализация инъекций «===»

Файлы: `src/lib/tier2-context.js`, `src/lib/components/pipeline/InsightsPanel.svelte`

Существующий хелпер `sanitizeMethodologyFragment` (tier2-context.js:352-357,
до правки — приватный, применялся только к выдержкам методологии) переименован
в **экспортированный** `sanitizePromptFragment` (та же логика: `={3,}`→`≈≈≈`,
переносы строк → пробел). Применён единообразно к:
- (а) вопросу пользователя — `buildTier2Prompt()`: `question = sanitizePromptFragment(userQuestion || '') || '<дефолт>'`.
- (б) tier1-инсайтам — `buildTier2Prompt()`, блок «Уже отмечено системой»:
  `ins.text` и `ins.tip` теперь пропускаются через `sanitizePromptFragment`
  перед вставкой (имена каналов приходят из пользовательских данных).
- (в) scenarioText — InsightsPanel.svelte, два места: `parseScenario()` перед
  `buildScenarioParsePrompt(sanitizePromptFragment(scenarioText), names)`, и
  `runScenario()` перед `factLines` (`Запрос пользователя: ${sanitizePromptFragment(scenarioText)}`).
  Импорт добавлен в существующую строку импорта из `$lib/tier2-context.js`.
- Место (методология, было единственным) — просто переключено на новое имя
  функции, поведение не изменилось.

Существующие тесты `tier2-context.test.js` (санитайз RAG-выдержек,
однострочные вопросы без «===») продолжают проходить логически — вопрос и
тексты инсайтов в тестах не содержат «===»/переносов, sanitize — no-op на них.

## 2.5 — U+2014 → U+2013 в промпт-литералах

Файлы: `tier2-context.js`, `program-help.js`, `scenario-advisor.js`

Разметила все строки с «—» в каждом файле, разделила на комментарии (JSDoc
`*`/`//`) — НЕ трогать, и строковые литералы, уходящие в промпт/клиенту —
менять. `program-help.js` — сделано в рамках 2.2/2.3 (все литералы
PROGRAM_OVERVIEW переведены на «–»). Осталось:
- `tier2-context.js`: 25 literal-вхождений (в массиве `TIER2_SYSTEM_RULES`,
  строки 264-322, и 2 в `parts.push(...)` заголовках секций, строки 372,379)
  → все заменены на «–». 18 вхождений в комментариях (строки 2,5,13,121,
  149-153,158,210,226,231,232,236-238,240) НЕ тронуты.
- `scenario-advisor.js`: 14 вхождений — 12 в JSDoc-комментариях (строки 20,
  21,27,28,32,36,57,99,104,143,152,193) НЕ тронуты; 2 literal → заменены:
  строка 48 (внутри `buildScenarioParsePrompt` — инструкция, уходящая в
  промпт для Claude при разборе NL-сценария) и строка 139
  `describeScenario()` возвращаемая строка (идёт в UI и в промпт через
  `scenarioConfirm`/factLines).

## Гейты

- `npm run check` (svelte-check): **0 ошибок**, 177 предупреждений (все
  предсуществующие — unused CSS selectors и a11y в файлах вне скоупа этого
  батча: +page.svelte, cabinet/+page.svelte, settings/+page.svelte,
  workflow/+page.svelte, data-chat/+page.svelte).
- `npm test` (vitest run): **78 файлов / 1263 теста — все passed**, включая
  `program-help.test.js` и `tier2-context.test.js` (не потребовали правок —
  ни один существующий тест не был завязан на «6 шагов» или литеральное
  U+2014, а вопросы/инсайты в тестах не содержат «===» — sanitize no-op).
  Никакие тесты не отключались.
