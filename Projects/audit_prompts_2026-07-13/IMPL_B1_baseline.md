# B1 — Baseline качества промптов кабинета econometrist (ДО правок)

**Продукт:** Optimizer MMM v2.3.0
**Репо:** `D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica_v230`
**Ветка:** `feat/econ-v2.3.0`
**HEAD:** `61a74ae552ea148f464556e4f6cc206998d65d3d` (2026-07-13 04:16:39 +0300,
«feat(delivery): оживить version-канал доставки промптов кабинета (Батч 0)»)
— промпты кабинета econometrist на этом коммите ЕЩЁ НЕ правлены, это и есть
baseline-состояние для сравнения после правок.

## Разведка харнеса (`tools/cabinet_eval/`)

Файлы: `README.md`, `run_eval.mjs`, `graders.mjs`, `build_message.mjs`,
`fixtures/manifest.json` + 4 fixture JSON (`model-diagnostics`,
`decomposition`, `optimization`, `validation`).

**6 кейсов манифеста** (покрывают 5 из 6 консультационных slash-команд
кабинета; `interpret-model` дважды — full + honesty-тест):

| id | command | что проверяет |
|---|---|---|
| `interpret-model-full` | `/interpret-model` | полный набор данных (4 шага пайплайна) |
| `interpret-model-no-optimization` | `/interpret-model` | тест честности: optimization отсутствует — ассистент обязан назвать недостающий шаг, не выдумать lift |
| `why-channel-trp-brand` | `/why-channel TRPs бренд (W 25-54)` | разбор одного канала |
| `explain-ratio-current` | `/explain-ratio` | разбор Ratio данные:предикторы |
| `next-quarter-plan-full` | `/next-quarter-plan` | тактический план квартала — САМЫЙ ТЯЖЁЛЫЙ (14075 симв. сообщения), стабильно упирается в таймаут ≥300с |
| `data-gaps-current` | `/data-gaps` | пробелы в данных |

Не покрыта харнесом: `/pilot-design` (нет кейса в манифесте), `/awareness-*`
(другой контракт входа — xlsx из inbox, не JSON-блок).

**Как запускается:** `node run_eval.mjs [--dry] [--case <id>]`, cwd раннера
не важен (сам вычисляет пути), но CLI-вызов делает `cwd = New_AI_Agency/econometrist/`
(там подхватывается CLAUDE.md кабинета как системный промпт + `.claude/commands/*.md`).
Реально спавнит `claude -p --model sonnet` через `cmd.exe /d /s /c` (Windows-обход
npm-shim), сообщение передаёт через stdin (не как argv — длинные сообщения бьются
о лимит командной строки Windows). Таймаут CLI на кейс — 300 000 мс (300с).

**Нужен ли egress:** да, полный (не `--dry`) прогон реально вызывает Claude CLI —
расходует квоту/баланс Anthropic. `--dry` только строит сообщения, CLI не трогает
(безопасен для CI и частых прогонов при правке харнеса).

**Детерминизм:** НЕТ. Живой прогон недетерминирован (LLM-ответ + `--dry` не
использует seed/temperature=0 контроль) — README прямо предупреждает «прогон
эвала недетерминирован — ОДИН прогон, не в цикле». `--dry` детерминирован
(чистая сборка сообщения из фикстур, без LLM).

**Как считаются скоры:** 5 автогрейдеров по умолчанию + 1 точечный
(`honesty_missing_step`, только на кейсе `interpret-model-no-optimization`):

| Грейдер | Проверяет |
|---|---|
| `numbers_grounded` | все числа ответа ⊆ числам приложенных фактов (INV-50 grounding guard, прямой импорт `collectGroundedNumbers`/`findUngroundedNumbers` из `src/lib/insights-grounding.js`); допуск на округление, знак-агностично, ignoreBelow=10; средний путь — производное число ОК если помечено маркером расчёта/оценки/методологии |
| `no_cli_artifacts` | нет предложений вызвать slash-команду, нет фразы «Все задачи выполнены» |
| `russian_language` | доля кириллицы >0.6 среди букв; нет цепочки >8 англ. слов подряд (кроме терминов-исключений: ROI, R-hat, MAPE, CI, MQS, adstock и т.п.) |
| `structure_takeaway` | первая содержательная строка <400 симв, не заголовок/список (вывод сразу); где-то есть блок действия/рекомендации (регэксп по ключевым фразам) |
| `no_env_paths` | нет `APPDATA`/абсолютных путей `C:\...` |
| `honesty_missing_step` (только `interpret-model-no-optimization`) | явно называет отсутствие шага «Оптимизация», не выдумывает lift |

Каждый грейдер возвращает `{name, pass, details}`. Итог прогона — PASS/FAIL
таблица в консоль + полный JSON в `results/<ISO-timestamp>.json` (эта папка
в `.gitignore` харнеса, не коммитится).

## Dry-прогон (проверка целостности харнеса)

`node run_eval.mjs --dry` — ЗЕЛЁНЫЙ, все 6 сообщений строятся без исключений:

| Кейс | Размер сообщения |
|---|---|
| interpret-model-full | 12870 симв. |
| interpret-model-no-optimization | 8838 симв. |
| why-channel-trp-brand | 12887 симв. |
| explain-ratio-current | 2845 симв. |
| next-quarter-plan-full | 14075 симв. |
| data-gaps-current | 10035 симв. |

## Egress-проба (ШАГ 2)

**Первая попытка — env по умолчанию (`ANTHROPIC_API_KEY` установлен в
окружении раннера):** прямой прогон `node run_eval.mjs --case
explain-ratio-current` → `[CLI FAIL] exit code 1`. JSON-результат раннера не
прокидывает `stdout`/`stderr` наружу при `!cliResult.ok` (только `reason:
"exit code 1"`) — пришлось продиагностировать напрямую.

**Прямой минимальный пробой CLI** (`echo "..." | claude -p --model sonnet`,
cwd кабинета, env по умолчанию):
```
⚠ claude.ai connectors are disabled because ANTHROPIC_API_KEY or another
  auth source is set and takes precedence over your claude.ai login
Credit balance is too low
```
Диагноз: баланс `ANTHROPIC_API_KEY` исчерпан — подтверждает предположение
задания.

**Fallback `env -u ANTHROPIC_API_KEY`** (прямой минимальный пробой):
```
Привет, Антон! Я Маша, твой ИИ-напарник по разработке...
```
Egress через claude.ai-подписку ЖИВ.

**Итог пробы (`env -u ANTHROPIC_API_KEY node run_eval.mjs --case explain-ratio-current`):**
живой ответ получен, egress через claude.ai-подписку рабочий сквозь весь путь
раннера (spawn `cmd.exe` → `claude -p --model sonnet`, stdin). Результат кейса
вошёл в общий baseline (см. таблицу ниже) — отдельно повторно не гонялся.

## ШАГ 3 — полный прогон baseline (egress жив)

Egress подтверждён рабочим только через `env -u ANTHROPIC_API_KEY` (баланс
`ANTHROPIC_API_KEY` в окружении раннера исчерпан — `Credit balance is too low`).
Все живые прогоны ниже выполнены с этим обходом.

`next-quarter-plan-full` из общего прогона ИСКЛЮЧЁН (см. задание — стабильно
упирается в timeout ≥300с) — прогоняется отдельно с осознанием риска TIMEOUT,
без ожидания сверх разумного.

## ШАГ 4 — снимок промптов (сделан)

Скопирован текущий (baseline, HEAD 61a74ae) корпус промптов кабинета в
`tools/cabinet_eval/results/baseline-2026-07-13/prompts-snapshot/econometrist/`:
- `CLAUDE.md` (36133 байт — системный промпт кабинета)
- `.claude/commands/*.md` — все 17 файлов (8 консультационных: `interpret-model`,
  `why-channel`, `explain-ratio`, `next-quarter-plan`, `data-gaps`, `pilot-design`,
  `awareness-forecast`, `awareness-to-sales`; 9 legacy-расчётных: `mmm-prepare`,
  `mmm-model`, `mmm-decomposition`, `mmm-optimize`, `mmm-scenarios`, `mmm-report`,
  `mmm-full`, `mmm-to-doc`, `mmm-to-slides`).

`LEGACY_COMMANDS.md` в снимок НЕ включён — задание называет только
`CLAUDE.md` + `.claude/commands/*.md`, этот файл документация о legacy-команде,
не промпт.

