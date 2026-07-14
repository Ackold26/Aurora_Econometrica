# Батч 3a аудита промптов — фантомные контракты и ложные обещания

Дата: 2026-07-13. Ветка: feat/econ-v2.3.0 (worktree). НЕ закоммичено.

Файлы тронуты:
- `New_AI_Agency/econometrist/.claude/commands/mmm-to-doc.md` (3.2)
- `content-packs/command-meta-data.json` (3.3 — re-sign нужен, см. ниже)
- `src/lib/econ-project-context.js` (3.4)
- `New_AI_Agency/econometrist/.claude/commands/data-gaps.md` (3.4)
- `New_AI_Agency/econometrist/.claude/commands/next-quarter-plan.md` (3.5)

НЕ тронуты (по прямому запрету задачи): `New_AI_Agency/econometrist/CLAUDE.md`,
`src/lib/tier2-context.js`, `program-help.js`, `InsightsPanel.svelte`, `insights-grounding.js`.

## 3.2 — mmm-to-doc: честный контракт

`mmm-to-doc.md:5` обещал результат «готовый для импорта через /plan-to-doc».
Подтверждено CONFIRMED: `/plan-to-doc` (doc-master/.claude/commands/plan-to-doc.md)
принимает на вход только **медиаплан .xlsx + шаблон приложения к договору
(.doc/.docx)** — Markdown MMM-отчёт как источник не упомянут нигде в контракте
plan-to-doc. Плюс кабинет doc-master вообще недоступен продукту Econometrica:
`filter_by_product("econometrica", …)` (cabinet.rs:121) отдаёт только
`["econometrist"]` (облачная редакция) либо `[]` (локальная, без
`cloud_advisors`) — `doc-master` нет ни в одном случае.

Правка: убрано упоминание `/plan-to-doc` и импорта, переформулировано как
самодостаточный документ.

- `mmm-to-doc.md:3-5` было: «Экспортируй результаты MMM-анализа в формат
  документа для Docu-Master. Создай структурированный Markdown-отчёт, готовый
  для импорта в Aurora AI Docu-Master через команду /plan-to-doc.»
  Стало: «Экспортируй результаты MMM-анализа в формат документа. Создай
  структурированный Markdown-отчёт – готовый к сохранению, печати или передаче
  руководству без дополнительной обработки.»

## 3.3 — awareness-forecast: мета ≠ промпт

`content-packs/command-meta-data.json`, ключ `/awareness-forecast`, поле
`description` было «Прогноз awareness по медиаплану». Прочитан
`awareness-forecast.md:5`: вход — xlsx из inbox с обязательными столбцами
`date`, `awareness_%` (исторический трекинг awareness) + охватные медиа-затраты
(TV_GRP, OOH_Spend, Digital_Video_Impressions). Медиаплан не требуется и не
упомянут вовсе — вход это трекинговое исследование, не план размещения.

Правка: `description` → «Прогноз awareness по историческому трекингу».
Правка выполнена точечной заменой байт в минифицированном JSON (файл — одна
строка, `ensure_ascii`-эскейпинг), Python load/dump на весь файл не
применялся, чтобы не тронуть порядок/форматирование остальных 121 команды.
JSON-валидность проверена (`json.load` успешно, 122 команды на месте).

**🔴 content-packs/command-meta-data.json изменён → требуется re-sign перед
сборкой** (manifest.json ↔ файлы, manifest.sig). Re-sign НЕ выполнен в рамках
этой задачи.

## 3.4 — доставка warnings + smell_flags

Подтверждено CONFIRMED (S1): движок отдаёт `warnings` (`validator.py:834`,
`validate_data()` возвращает `result['warnings']` — список объектов с
`column`/`type`/`message`/`severity`), но `summarizeValidation()` в
`econ-project-context.js` их не включал в выжимку — `data-gaps.md` требует
`validation.warnings`, но блок его никогда не содержал.

Поле `suspicious_channels`, которое `data-gaps.md` просил из `decomposition`,
не существует нигде в движке/фронте — реальное поле `smell_flags`
(`decomposer.py:1293-1363`, объекты `{type, channel/channels, value, severity}`
на верхнем уровне `decomposition.result`).

Правки:
- `src/lib/econ-project-context.js:124` — в `summarizeValidation()` добавлена
  строка `warnings: r.warnings ?? null,` в объект `out` (между
  `high_correlations` и закрывающей скобкой). Схема инжекта не сломана: поле
  добавлено, не переименовано/не удалено; `hasAny`-проверка ниже не менялась и
  корректно учитывает новое поле через `Object.values(out)`.
- `New_AI_Agency/econometrist/.claude/commands/data-gaps.md:11` — заменено
  `suspicious_channels` → `smell_flags`.

Найдено, но НЕ тронуто (вне заявленного объёма задачи 3.4 — только
`econ-project-context.js` и `data-gaps.md`): `explain-ratio.md:31` тоже
упоминает `suspicious_channels` в тексте («Есть ли smell-флаги переобучения
(ROI > 50×, suspicious_channels)»). Тот же фантом-термин, другой файл — не
трогал, отмечаю на будущее.

## 3.5 — next-quarter-plan: разгрузка + фантомы

Все 4 дефекта подтверждены при чтении файла:

- (а) `[scenarios]` — секция была в списке источников (`next-quarter-plan.md:11`
  было), инжект (`econ-project-context.js`, `ECON_DATA_COMMANDS`) её не
  собирает вообще (нет такого блока в `buildProjectDataBlock`). Убрана строка
  `- scenarios — сохранённые пользователем сценарии (если есть)`.
- (б) `next-quarter-plan.md:22` (было) — «брать из optimization.json»: такого
  файла в контракте консультационных команд нет, данные приходят секцией
  `[optimization]` в сообщении (см. `econ-project-context.js`). Заменено на
  «брать из секции [optimization] в сообщении».
- (в) `next-quarter-plan.md:42` (было) — сломанная фраза «(исходя из что
  ratio, что basе, что suspicious ROI)», смешение латиницы/кириллицы в
  «basе» (лат. b-a-s-e + кир. е). Исправлено на «(исходя из ratio, из
  baseline, из подозрительного ROI)».
- (г) Перегруз контракта: 5 обязательных секций, из них раздел 1 требовал
  таблицу «Канал × квартальный план» с масштабированием ×3 мес по каждому
  каналу — в связке с остальными секциями это и есть источник таймаута
  ≥300с (сам харнес `run_eval.mjs` уже поднял таймаут для кейса
  `next-quarter-plan-full` с 180с до 300с из-за этого). Правка: контракт
  разбит на «Обязательный костяк» (секции 1-4, без помесячной детализации по
  каналам — раздел 1 теперь явно требует ОДНУ квартальную цифру на канал) и
  «Опционально» (новая секция 5 — помесячная разбивка по каналам, включается
  ТОЛЬКО по прямому запросу пользователя; бывшая секция 5 «что собрать к
  следующей сборке» стала секцией 6, осталась обязательной и лёгкой).

Живьём `next-quarter-plan` НЕ гонял (запрещено заданием — timeout ≥300с).

## Гейт

- `node tools/cabinet_eval/run_eval.mjs --dry` — **PASS**, 6/6 кейсов, все
  сообщения построены без ошибок (interpret-model-full,
  interpret-model-no-optimization, why-channel-trp-brand,
  explain-ratio-current, next-quarter-plan-full, data-gaps-current).
- `npm run check` (svelte-check) — **0 ERRORS**, 177 warnings (все
  предсуществующие, не по теме правки — CSS unused selectors / a11y в
  несвязанных .svelte-файлах).
- `npm test` (vitest, полный прогон) — **1263 passed / 78 test files, 0
  failed**. Точечно: `src/lib/__tests__/econ-project-context.test.js` — 16/16
  passed (включая существующий тест `validation-секция (сверка контракта
  S1<->S2, 2026-07-12)`, который правку `warnings` не ломает — тест не
  проверял отсутствие поля).

## Спорное / оставленное на решение

- `explain-ratio.md:31` содержит тот же фантом `suspicious_channels` — вне
  явного объёма 3.4, не тронуто (см. выше).
- В `next-quarter-plan.md` разгрузка (г) — компромисс: убрал ПРИНУДИТЕЛЬНОЕ
  требование помесячной таблицы по каждому каналу как обязательной секции,
  оставил её опциональной по запросу. Это меняет поведение по умолчанию
  (короче ответ), но сохраняет доступность детализации при явном запросе —
  ценность плана не потеряна, потеряна только принудительная тяжесть.
  `run_eval.mjs` кейс `next-quarter-plan-full` в `--dry` строит сообщение
  штатно (14281 симв.) — реальный прогон живьём не делал (запрещено), поэтому
  фактическое время ответа после разгрузки не измерено в этой сессии.
- Оставшийся в файле `next-quarter-plan.md` U+2014 («—») в НЕ тронутых мной
  строках (23 вхождения) — это существующий стиль файла до правки, вне
  объёма задачи (правило короткого тире применил только к своим новым
  вставкам).
