# Handoff — блок «аудит-фиксы кабинета + петля харнеса (средний путь INV-50)»

> База аудита: `d0a87a9` (HEAD начала сессии, оценочная — base-SHA hook не сработал).
> Diff: аудит-фиксы 5 находок (avrora `d0a87a9..fdd47e9`) + консолидация type-фиксы
> (`57d5e21..8ecfae5`). Консолидация (merge kpi+avrora, version bump 2.3.0, разрешение
> конфликтов lefthook/InsightsPanel) — механическая, в diff не включена.

## 1. Цель блока
Кабинет-эконометрист (Claude консультирует ПОВЕРХ детерминированного MMM-pipeline) —
две волны правок: (а) исправление 5 находок внешнего аудита предыдущего блока
(доставка данных проекта в команды через `$ARGUMENTS`, дорезка телеметрии декомпозиции,
согласование 7-шаговой шкалы шагов, края humanizeSource, оживление focusChannelType);
(б) петля эвал-харнеса — «средний путь INV-50»: производные числа (суммы долей,
отношения, пересчёты) разрешены в ответе ассистента, ЕСЛИ помечены как расчёт/оценка;
непомеченная выдумка — по-прежнему нарушение.

## 2. Ключевые инварианты
- **INV-50 (страж чисел):** число в ответе LLM либо ⊆ приложенным фактам, либо помечено
  маркером расчёта (`≈`/`~`/«оценка»/«если»/«в N раз»/«вместе») или методологии
  (cap/порог/покрытие). Прод-страж `insights-grounding.js` НЕ тронут — калибровка
  среднего пути живёт в ОБЁРТКЕ грейдера харнеса (`graders.mjs::numbersGrounded`),
  не в проде.
- **Доставка данных:** ChatPanel клеит блок «=== Данные проекта ===» к сообщению;
  `resolve_slash_command` (Rust) подставляет его в `$ARGUMENTS` командного .md.
  Без `$ARGUMENTS` в шаблоне — данные теряются (это была Critical).
- **Шкала шагов:** `STEP` (tier2-context.js) согласован с 7-шаговой PIPELINE_STEPS
  (0 import … 5 planning, 6 report). Три таблицы (STEP, rag-query STEP_TERMS,
  program-help STEP_TERMS) должны совпадать по индексам.
- **Эвал недетерминирован:** полный прогон харнеса — инструмент диагностики, НЕ бинарный
  гейт (LLM в каждом прогоне отвечает иначе); детерминированный dry-режим — для CI.
- JS+JSDoc (не TS). Гейты консолидации: svelte-check 0 · vitest 1263 · cargo 188.

## 3. Осознанные компромиссы
- **Средний путь как контекстная эвристика:** негрунд-число оправдывается маркером в
  ±45 симв. `~`/`≈` — очень частые маркеры → модель может пометить и выдумку, и она
  пройдёт. Принято: помеченное = честно (не выдаётся за факт). Цена — грейдер мягче
  строгого INV-50.
- **Калибровка в грейдере, не в проде:** обёртка над `findUngroundedNumbers` вместо
  правки прод-стража. Причина — не трогать порт-компонент INV-50; slash-команды кабинета
  в рантайме стражем и так не проверяются (только Tier-2 askAI). Цена — расхождение
  строгости харнес↔прод-страж.
- **focusChannelType оживлён эвристикой `detectChannelType`** (основы слов reach/perf),
  а не удалён. Мисфайр возможен (напр. «директор» → performance), но это лишь ДОБАВКА
  терминов к RAG-запросу — цена ошибки мала.
- **structure_takeaway окно 12 строк, потолок 400 симв** — подобрано под реальные
  форматы ответов (карточки, заголовки в начале). Порог эмпирический.

## 4. Зоны неуверенности
1. **`isJustifiedNumber` regex-границы** (`graders.mjs`): `(?<![\d]|\d[.,])N(?![\d]|[.,]\d)`
   — отделяет пунктуацию-запятую от десятичного разделителя. Проверить края: число в
   начале строки, число с двумя точками, отрицательные, число внутри слова.
2. **Согласование шкал STEP** (tier2-context.js / rag-query.js / program-help.js):
   три таблицы индексированы вручную. Проверить, что на КАЖДОМ шаге 0-6 все три дают
   согласованный домен (не разъехались снова).
3. **`humanizeSource` формат ГОД_Автор** (rag-query.js): при `beforeYear` пусто берётся
   ведущая фамилия из afterYear. Проверить: несколько ведущих фамилий (Chan_Perry после
   года), фамилия-паттерн ложно матчит слово названия.
4. **`kpiView` labels merge** (kpi-aware-formatting.js): убран явный `cpuPerLabel: '₽/ед.'`
   — теперь только из `derived`. Проверить: все ветки `deriveLabels` реально возвращают
   cpuPerLabel (effectiveness/count/else), иначе поле пропадёт.

## 5. Затронутые файлы (роль)
- `src-tauri/src/lib.rs` — resolve_slash_tests (3 Rust-теста доставки данных).
- `New_AI_Agency/econometrist/.claude/commands/*.md` — $ARGUMENTS в 6 команд + средний путь.
- `New_AI_Agency/econometrist/CLAUDE.md` — правило среднего пути + запрет slash в тексте.
- `src/lib/econ-project-context.js` — stripDecompTelemetry (дорезка графики декомпозиции).
- `src/lib/rag-query.js` — STEP_TERMS 7-шаг, humanizeSource края, detectChannelType.
- `src/lib/tier2-context.js` — STEP enum 7-шаг + case PLANNING.
- `src/lib/program-help.js` — STEP_TERMS 7-шаг (третья таблица).
- `src/lib/components/pipeline/InsightsPanel.svelte` — detectChannelType в askAI.
- `tools/cabinet_eval/graders.mjs` — numbersGrounded средний путь, structure_takeaway.
- `tools/cabinet_eval/build_message.mjs` — buildFacts вырезка графики (симметрия промпту).
- `tools/cabinet_eval/run_eval.mjs` — CLI-таймаут 300с.
- `src/lib/kpi/kpi-display.js` — @typedef KpiDisplay (консолидация type-фикс).
- `src/lib/kpi-aware-formatting.js` — KpiViewInput.kpiType null + дубль cpuPerLabel.
