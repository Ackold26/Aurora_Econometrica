# Эвал-харнес кабинета econometrist

Детерминированные входы + автогрейдеры для консультационных команд кабинета
`New_AI_Agency/econometrist/` (`/interpret-model`, `/why-channel`,
`/explain-ratio`, `/next-quarter-plan`, `/data-gaps`). Позволяет измерить
эффект правки промпта/CLAUDE.md кабинета вместо гадания «стало лучше или
хуже» на глаз.

## ⚠️ Полный прогон расходует квоту Claude

`node run_eval.mjs` (без `--dry`) реально запускает `claude -p ... --model
sonnet` — один вызов на кейс, до 6 живых вызовов за прогон. Не гонять в
цикле, не встраивать в pre-commit хуки. `--dry` не звонит CLI вообще —
безопасен для CI и частых прогонов при правке харнеса.

## Как гонять

```bash
cd tools/cabinet_eval

# Только построить сообщения, без вызова CLI (быстро, для CI/отладки харнеса)
node run_eval.mjs --dry

# Полный живой прогон всех 6 кейсов (расходует квоту, ~180с таймаут на кейс)
node run_eval.mjs

# Один конкретный кейс (dry или живой)
node run_eval.mjs --dry --case interpret-model-full
node run_eval.mjs --case why-channel-trp-brand
```

Exit-код: `1`, если хотя бы один грейдер FAIL (или ошибка вызова CLI);
`0` — всё зелёное (для dry — если все сообщения построились без исключений).

Результат каждого прогона (сообщения, живой ответ CLI, вердикты всех
грейдеров) пишется в `results/<ISO-timestamp>.json` — папка в `.gitignore`
харнеса, в репозиторий не попадает.

## Как добавить кейс

1. Если нужна новая фикстура данных — положить `*.json` в `fixtures/`
   (короткое имя без расширения = ключ в `data` манифеста, например
   `fixtures/model-diagnostics.json` → ключ `"model-diagnostics"`).
2. Добавить объект в `fixtures/manifest.json` → `cases`:
   ```json
   {
     "id": "уникальный-id-кейса",
     "command": "interpret-model",      // имя slash-команды БЕЗ ведущего /
     "args": "",                         // аргументы команды (напр. имя канала для why-channel)
     "description": "Что проверяет этот кейс.",
     "data": ["model-diagnostics", "decomposition"]  // какие фикстуры приложить
   }
   ```
3. Ключ, отсутствующий в `data`, НЕ опускается молча — `build_message.mjs`
   передаёt его в `buildProjectDataBlock` как `null`, и та секция честно
   отрендерится «нет – шаг «X» не пройден» (воспроизводит реальный
   непройденный шаг пайплайна). Секция `[validation]` рендерится ВСЕГДА
   (даже без ключа в `data`) — так работает `buildProjectDataBlock`.
4. `node run_eval.mjs --dry --case <новый-id>` — проверить, что сообщение
   строится без ошибок, прежде чем тратить живой вызов CLI.

## Формат сообщения кейса

`build_message.mjs::buildMessage()` НЕ реализует свою логику инъекции
данных — прямой импорт продовой функции `buildProjectDataBlock` из
`src/lib/econ-project-context.js` (правило проекта №10, CLAUDE.md:
«Pipeline context — inject в message, не файл»). Итоговое сообщение:

```
/interpret-model

=== Данные проекта (приложены приложением) ===
[model-diagnostics]
{"engine":"ols",...}
[decomposition]
{"total_sales":11226057702.0,...}
[optimization]
нет – шаг «Оптимизация» не пройден
[validation]
{"ratio":3.7,"n_rows":48,...}
```

Служебная телеметрия `optimization.slsqp_diagnostics` и
`optimization.response_curves` вырезается автоматически (внутри
`buildProjectDataBlock`) — она не факты для интерпретации, а отладочная
диагностика оптимизатора; в реальном инжекте контекста кабинета этих
полей тоже не будет. `[validation]` — не сырой `validation.json`, а узкая
выжимка (`ratio`, `n_rows`, `date_frequency`, списки колонок по ролям,
`high_correlations`) через `summarizeValidation()` внутри
`econ-project-context.js`; фикстура `validation.json` в этом харнесе
оборачивается в `{ result: ... }` перед передачей — контракт
`buildProjectDataBlock` ожидает содержимое стора `validateData` целиком,
не голый `ValidationResult`.

Если `src/lib/econ-project-context.js` изменится (новая секция, другой
формат «нет – шаг…» и т.п.) — харнес подхватит это автоматически при
следующем прогоне, без правки `build_message.mjs`.

## Что меряет каждый грейдер (`graders.mjs`)

| Грейдер | Что проверяет | На каких кейсах |
|---|---|---|
| `numbers_grounded` | Каждое число ответа (кроме мелких целых <10 — годы/шаги/счёт) найдено среди чисел приложенных фактов, с допуском на округление и знак-агностично (INV-50, прямой импорт `collectGroundedNumbers`/`findUngroundedNumbers` из `src/lib/insights-grounding.js` — тот же guard, что рантайм-страж Tier-2) | все |
| `no_cli_artifacts` | Нет предложений вызвать slash-команду (`/mmm-optimize` и т.п.) и нет служебной фразы «Все задачи выполнены» — консультационный ответ, не шаг pipeline | все |
| `russian_language` | Доля кириллицы среди буквенных символов > 0.6; нет цепочки >8 английских слов подряд (термины-исключения — ROI, R-hat, MAPE, CI, MQS, adstock и т.п. — не считаются) | все |
| `structure_takeaway` | Первая строка ответа короткая (<250 симв.) и не заголовок/список (вывод сразу, не в конце); где-то в тексте есть блок действия (регэксп «Что сделать\|Что улучшить\|Что собрать\|Рекомендаци\|Действи\|Следующий шаг\|Приоритет\|Стоит\|Совет») | все |
| `honesty_missing_step` | Ответ явно называет отсутствие шага «Оптимизация», а не молчит/выдумывает цифры lift | только `interpret-model-no-optimization` |
| `no_env_paths` | Нет `APPDATA`/`%APPDATA%` и нет абсолютных путей вида `C:\...` — путь workspace не должен утекать пользователю в текст | все |

`DEFAULT_GRADERS` в `graders.mjs` — это первые пять (без `honesty_missing_step`);
runner навешивает `honestyMissingStep` точечно только на свой кейс
(`EXTRA_GRADERS_BY_CASE` в `run_eval.mjs`).

## ✅ Расхождение контракта — закрыто (найдено при S4, исправлено S1)

Изначально все 6 консультационных slash-команд кабинета (`.claude/commands/
{interpret-model,why-channel,explain-ratio,next-quarter-plan,data-gaps,
pilot-design}.md`) заканчивались требованием `В конце: «Все задачи
выполнены.»` — той же служебной фразой, которую грейдер `no_cli_artifacts`
считает CLI-артефактом, недопустимым в консультационном ответе. Живой прогон
S4 поймал это как гарантированный FAIL `no_cli_artifacts`. Фраза убрана из
всех 6 команд (расчётные `mmm-*`/`awareness-*` её сохраняют — там она уместна,
это их legacy-роль как шагов pipeline). Ровно то, для чего эвал-харнес и
строится: находка живого прогона → правка промпта → грейдер подтверждает.

## Структура

```
tools/cabinet_eval/
├── README.md              — этот файл
├── .gitignore              — исключает results/
├── build_message.mjs       — сборка сообщения кейса (импорт buildProjectDataBlock)
├── graders.mjs             — 6 автогрейдеров + INV-50 grounding guard
├── run_eval.mjs            — runner (CLI-вызов, --case, --dry, отчёт)
├── fixtures/
│   ├── manifest.json        — 6 кейсов
│   ├── model-diagnostics.json
│   ├── decomposition.json
│   ├── optimization.json
│   └── validation.json
└── results/                 — прогоны (.gitignore, не в репозитории)
```
