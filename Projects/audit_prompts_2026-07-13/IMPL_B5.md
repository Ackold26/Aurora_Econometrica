# Батч 5 — вечная оборона (линтеры + CI + регламент)

Портированы 3 линтера из `../ROSST_AI_Legal_commercial/tools/` (та же сессия аудита
промптов, 2026-07-13, «один код, разные конфиги»), адаптированы под кабинет
econometrist. НЕ коммичено — оставлено в рабочем дереве по заданию.

## 5.1 — tools/lint_prompt_commands.py

Портирован и переписан под econometrist-конфиг (Legal-версия проверяет 3 кабинета
lawyer-* с секциями/мин-строками/pip-install-запретом — econometrist один кабинет
без этих проверок, зато с двумя новыми: термин CI + паттерн блокировки).

Периметр: `New_AI_Agency/econometrist/.claude/commands/*.md` (17 файлов) +
`CLAUDE.md` + `LEGACY_COMMANDS.md` = 19 файлов.

Проверки (FAIL):
- U+2014 запрещён (0 везде);
- «доверительный интервал»/«CI» запрещены в клиентском тексте — с исключением
  для цитаты термина внутри кавычек-«ёлочек» `«доверительный интервал»`
  (см. находку ниже — это не баг линтера, это точный дизайн);
- единая языковая шапка первой строкой файлов `.claude/commands/*.md` — сверена
  строка-в-строку с эталоном из задания, точное совпадение обязательно;
- паттерн блокировки «ОСТАНОВИСЬ»/«не продолжай»/«жди ввода»/«не генерируй»
  (точный, не substring «останов*» — не путать с легитимным «останови шаг Х»).

**Реальная находка при первом прогоне:** CLAUDE.md кабинета дважды использует
термин `«доверительный интервал»` — но ОБА раза внутри кавычек-«ёлочек», как
цитата в правиле «называй правдоподобным диапазоном, а не «доверительный
интервал»» (McElreath-обоснование, Батч 2 работа). Это не нарушение, а
инструкция, которая САМА запрещает термин. Наивный grep поймал бы это как FAIL
и заставил бы либо исказить формулировку правила, либо занести файл в грубый
whitelist (потеряв защиту от будущих реальных нарушений в CLAUDE.md). Решение:
точечное regex-исключение `CI_TERM_QUOTED_RE` — вырезает из текста ПЕРЕД
проверкой только конструкцию `«довер.*интервал»` целиком в кавычках, не трогая
голое упоминание термина вне кавычек. Узкое, не маскирующее исключение.

## 5.2 — tools/check_help_consistency.py

Переименован по смыслу (в Legal — «справка HTML <-> плитки <-> cabinet.rs»),
здесь готовой HTML-справки под econometrist нет → линтер сверяет **четыре**
источника истины активных команд:
`cabinet.rs` (блок `"econometrist" => vec![...]`) <-> `content-packs/cabinets.json`
(`cabinets[].id=="econometrist"`) <-> файлы-владельцы в `.claude/commands/*.md`
<-> `content-packs/command-meta-data.json` (описания для UI). Плюс U+2014=0 по
всем `content-packs/*.json`.

**Реальная находка:** `content-packs/psy-data.json` содержал 32× U+2014 (во
всех кабинетах, не только econometrist — lawyer-advertising, social-listening,
communication-strategist, art-director и т.д.; из них 2 — в
`insights.econometrist`). Разведка также отдельно установила, что
`/mmm-to-doc` и `/mmm-to-slides` (legacy-команды) не имеют записей в
command-meta-data.json — но это НЕ дефект в рамках этого линтера: проверяется
множество **активных** команд (`cabinet.rs` блок econometrist = 8), legacy
`/mmm-*` туда не входят по дизайну (они скрыты из UI, см. комментарий в
cabinet.rs и LEGACY_COMMANDS.md).

**Правка:** psy-data.json — все 32× `—` → `–` (короткое тире, канон Aurora,
символ-в-символ, длина файла не изменилась, LF line-endings сохранены).
content-pack правка → **re-sign обязателен** (сделан, см. ниже) → после этого
линтер 5.2 и 5.3 оба зелёные.

## 5.3 — tools/check_content_pack_sync.py

Портирован без изменений по существу (тонкая обёртка над
`tools/sign_content_pack.py --check`, который уже был портирован в этот репо
раньше, до Батча 5, с version 5→6). Только текст переименован под Optimizer MMM
вместо Legal Center.

## Re-sign после правки psy-data.json

```
python tools/sign_content_pack.py --bump
```
version 6 → 7. Все 6 паков синхронны, подпись валидна (проверено `--check`).
`npm run check` (svelte-check) после правки: 4138 files, 0 ERRORS (177
warnings — все предсуществующие, не связаны с psy-data.json).

## 5.4 — подключение в lefthook.yml

Добавлены 3 hook'а в `pre-commit` (после существующего `cabinet-drift-guard`,
тот же стиль `glob:`+`run:`, `parallel: true` секции не тронут):
- `prompt-lint` — glob `New_AI_Agency/econometrist/**`
- `help-consistency` — glob по 4 источникам (`content-packs/cabinets.json`,
  `content-packs/command-meta-data.json`, `src-tauri/src/commands/cabinet.rs`,
  `New_AI_Agency/econometrist/.claude/commands/*.md`)
- `content-pack-sync` — glob `content-packs/*.json`

`npx lefthook validate` → «All good».

## 5.4 — подключение в ci.yml

Добавлен шаг «Prompt & delivery linters» в job `check` (windows-latest), между
«Install frontend dependencies» и «Build frontend» — та же точка вставки, что
в Legal ci.yml. `python -m pip install --quiet cryptography` (нужен
sign_content_pack.py для Ed25519) + все 3 линтера, `shell: bash`.

`python -c "import yaml; yaml.safe_load(...)"` — оба файла (`lefthook.yml`,
`.github/workflows/ci.yml`) валидный YAML.

## 5.5 — внести-поймать-откатить (все три линтера)

**prompt-lint:** внесён U+2014 в `why-channel.md` (дописана строка) → FAIL
поймал (`найден символ длинного тире «—» (1×)`) → откат. ⚠️ Урок: первый откат
вручную через Python `write_text()` без `newline=''` конвертировал ВЕСЬ файл в
CRLF на Windows (git status показал `M` при пустом `git diff` — byte-diff
показал `\n`→`\r\n` на 52 байта) — исправлено через `git checkout --
<файл>` (чистое побайтовое восстановление). После отката — PASS (19/19 OK).
Для help-consistency и content-pack-sync тестов сразу использован `git
checkout --` вместо ручной записи.

**help-consistency:** временно удалена запись `/why-channel` из
`command-meta-data.json` (`d['commands'].pop('/why-channel')`) → FAIL поймал
(`есть в cabinet.rs, нет описания в command-meta-data.json: /why-channel`,
плюс сохранявшийся на тот момент реальный psy-data.json дефект — оба FAIL
видны одновременно, линтер не останавливается на первой находке) → `git
checkout -- content-packs/command-meta-data.json` → PASS (8=8=8). re-sign НЕ
трогался в этом тесте (файл идентичен HEAD после отката, manifest не менялся).

**content-pack-sync:** временно изменён 1 байт в `cabinets.json`
(`0EA5E9`→`0EA5E8`, цвет иконки в hex) → FAIL поймал (`MISMATCH cabinets.json:
manifest=ae34415f5fcb факт=f77973f62b82`) → `git checkout --
content-packs/cabinets.json` → PASS (`content-pack синхронен: version 6...`).
re-sign НЕ трогался — файл восстановлен побайтово идентичным HEAD.

Все три теста выполнены ДО правки psy-data.json/re-sign (на version 6),
результат затем перепроверен на version 7 (см. «ГЕЙТ» ниже) — оба состояния
зелёные, тесты валидны для финальной конфигурации линтеров (код линтеров
между тестами не менялся).

## 5.6 — регламент в CLAUDE.md репо

Добавлен раздел «### 18. Регламент правки промптов и доставки» (по образцу
Legal §18, адаптирован под econometrist/MMM: правка промпта кабинета →
lint_prompt_commands.py 0 FAIL; правка content-pack → sign_content_pack.py
--bump ОБЯЗАТЕЛЕН + check_content_pack_sync OK; три линтера в CI и pre-commit,
не обходить --no-verify без причины).

## ГЕЙТ (финальная проверка, после psy-data.json fix + re-sign version 7)

```
python tools/lint_prompt_commands.py       → OK 19/19, exit 0
python tools/check_help_consistency.py      → OK (8=8=8, U+2014 не найден), exit 0
python tools/check_content_pack_sync.py     → content-pack синхронен: version 7, exit 0
npx lefthook validate                       → All good
python -c "import yaml; yaml.safe_load(open('lefthook.yml'))"           → OK
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" → OK
npm run check (svelte-check)                → 4138 files, 0 ERRORS
```

Внести-поймать-откатить — 3/3 линтера подтверждено способны реально падать
(не мёртвый обвес).

## Изменённые/созданные файлы

| Файл | Назначение |
|---|---|
| `tools/lint_prompt_commands.py` | НОВЫЙ — линтер 5.1, порт из Legal + econometrist-конфиг |
| `tools/check_help_consistency.py` | НОВЫЙ — линтер 5.2, четверное совпадение команд |
| `tools/check_content_pack_sync.py` | НОВЫЙ — линтер 5.3, обёртка sign_content_pack.py --check |
| `lefthook.yml` | + 3 pre-commit hook'а (prompt-lint, help-consistency, content-pack-sync) |
| `.github/workflows/ci.yml` | + шаг «Prompt & delivery linters» в job check |
| `content-packs/psy-data.json` | ПРАВКА — 32× U+2014 → U+2013 (реальный дефект, найден линтером 5.2) |
| `content-packs/manifest.json`, `manifest.sig` | re-sign после правки psy-data.json, version 6→7 |
| `CLAUDE.md` (репо) | + раздел «### 18. Регламент правки промптов и доставки» |
