# Батч 4-active — гигиена 8 активных команд econometrist (Optimizer MMM v2.3.0)

Ветка `feat/econ-v2.3.0` (worktree), НЕ закоммичено — рабочее дерево.
Периметр: `New_AI_Agency/econometrist/.claude/commands/{interpret-model,why-channel,explain-ratio,pilot-design,next-quarter-plan,data-gaps,awareness-forecast,awareness-to-sales}.md`

## 4.1 U+2014 → U+2013
Программная замена (python, UTF-8) во всех 8 файлах. Разбивка по файлам:
- interpret-model.md: 17
- why-channel.md: 20
- explain-ratio.md: 14
- pilot-design.md: 18
- next-quarter-plan.md: 19
- data-gaps.md: 18
- awareness-forecast.md: 4
- awareness-to-sales.md: 5
Итого 115 замен. Markdown-разделители таблиц (`---`) не задеты (это дефисы, не U+2014).

## 4.2 Единая языковая шапка
Первая строка всех 8 файлов приведена дословно к эталону:
`ЯЗЫК ОТВЕТА: РУССКИЙ. Все выводы, таблицы, рекомендации, статусы – на русском языке. Английский только для устоявшихся терминов: ROI, CPM, GRP, MQS, R-hat, MAPE, adstock.`
- 6 файлов (interpret-model, why-channel, explain-ratio, pilot-design, next-quarter-plan, data-gaps) имели укороченную шапку «ЯЗЫК ОТВЕТА: РУССКИЙ.» — расширены до эталона.
- 2 файла (awareness-forecast, awareness-to-sales) имели шапку в другом виде («…статусы – на русском языке. НЕ использовать английский (кроме терминов ROI, CPM, GRP).») — заменены на эталон целиком.

## 4.3 «Доверительный интервал»/CI → «правдоподобный диапазон»
8 замен в 4 файлах (клиентский вывод, числа/структура сохранены):
- explain-ratio.md:25 — «широкие CI» → «широкий правдоподобный диапазон»
- pilot-design.md:33-34 — «CI < 10%» → «правдоподобный диапазон уже 10%»; «ожидаемого CI» → «ожидаемого правдоподобного диапазона»
- awareness-forecast.md:17,20 — «доверительными интервалами» → «правдоподобным диапазоном»; «с CI» → «с правдоподобным диапазоном»
- awareness-to-sales.md:17,20,22 — «доверительными интервалами» → «правдоподобным диапазоном»; «[CI: Y%-Z%]» → «[правдоподобный диапазон: Y%-Z%]»; «[CI]» → «[правдоподобный диапазон]»

## 4.4 explain-ratio.md — suspicious_channels → smell_flags
explain-ratio.md:31: `suspicious_channels` (несуществующее поле) заменено на `smell_flags` — сверено с data-gaps.md:10 (`decomposition – smell_flags, unit_smell`), это реальное имя поля из инжекта decomposition. 1 замена.

## 4.5 Edge cases inbox для awareness-*
Добавлено по 3 строки после пункта 1 (чтение xlsx) в awareness-forecast.md и awareness-to-sales.md:
- пустой inbox → сообщить какой файл нужен, не идти дальше
- несколько xlsx → взять последний по дате изменения, назвать явно; при неочевидности — уточнить у пользователя
- нет обязательных столбцов (date/awareness_%/KPI) → назвать каких не хватает, пометить `[ОГРАНИЧЕНИЕ]`, данные не выдумывать
Без блокирующего паттерна «ОСТАНОВИСЬ» — обработка внутри рабочего потока команды, в стиле существующих маркеров кабинета (`[НЕ УКАЗАНО]`/`[ОГРАНИЧЕНИЕ]`).

## ГЕЙТ
- `node tools/cabinet_eval/run_eval.mjs --dry` → 6/6 кейсов, сообщения построены без ошибок (interpret-model-full, interpret-model-no-optimization, why-channel-trp-brand, explain-ratio-current, next-quarter-plan-full, data-gaps-current).
- Python-подсчёт U+2014 после правок: 0 во всех 8 файлах (interpret-model.md, why-channel.md, explain-ratio.md, pilot-design.md, next-quarter-plan.md, data-gaps.md, awareness-forecast.md, awareness-to-sales.md).

Статус: ЗАВЕРШЕНО. Не закоммичено (по заданию).
