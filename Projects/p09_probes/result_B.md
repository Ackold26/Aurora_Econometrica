# Зонды CPD-15, CPD-23, CPD-24, CPD-32 — Aurora AI Econometrica (MMM Optimizer)

Рабочая копия: `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_canon`, ветка `feat/econ-canon-p0`.
Подтверждено git-историей, что это канонический репо реестра (`git log --oneline -- src-tauri/src/commands/claude.rs` содержит `244fccd fix(security): CPD-15`).

---

## CPD-15 — предлагаемый статус: ✅ (эталон, с двумя уже задокументированными в реестре оговорками)

**Зонд:** `grep -n "safe-mode\|isolated_claude_config_dir\|CLAUDE_CONFIG_DIR" src-tauri/src/commands/claude.rs`

**Вывод зонда:**
```
239:/// Изолированный CLAUDE_CONFIG_DIR для кабинетных сессий (V66/INV-92, вариант A).
246:fn isolated_claude_config_dir(app_handle: &tauri::AppHandle) -> Option<std::path::PathBuf> {
249:        warn!("V66: не удалось создать изолированный CLAUDE_CONFIG_DIR ...
384:        .env_remove("CLAUDE_CONFIG_DIR");
393:    if let Some(iso) = isolated_claude_config_dir(&app_handle) {
394:        cmd.env("CLAUDE_CONFIG_DIR", &iso);
```
Строка `"--safe-mode"` в массиве `args` (claude.rs:310-315) отсутствует — только `"--print", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"`.

**Адрес:** `src-tauri/src/commands/claude.rs:246-289` (helper), `:378` (`cmd.current_dir(work_dir)`), `:384` (`env_remove`), `:393-395` (условная установка изоляции).

**Разбор:** Три исхода реестра — это исход (в): «есть упрочнённый helper (атомарная замена credentials + env_remove + без safe-mode) – эталон». Все три условия подтверждены чтением кода 236-400:
1. safe-mode не стоит вовсе (V66 у EC никогда не применялся, канонический для EC helper внесён отдельным коммитом 244fccd);
2. `current_dir(work_dir)` стоит ДО манипуляций с окружением (:378) — барьер `work_dir/CLAUDE.md` грузится из cwd, изоляция его не трогает;
3. `env_remove("CLAUDE_CONFIG_DIR")` присутствует (:384), затем `isolated_claude_config_dir` ставит свой путь (:393-395);
4. атомарная замена credentials через copy+rename (:272-284) присутствует.

Но при чтении нашлись ДВЕ вещи, которые реестр уже называет открытым кросс-продуктным бэклогом (не новая находка, но подтверждаю их присутствие именно в EC):
- **#6 (не портирован у EC):** имя tmp-файла ФИКСИРОВАННОЕ — `iso.join(".credentials.json.tmp")` (:272), не `unique_credentials_tmp_suffix()` по счётчику, как в эталонном коде реестра. Два параллельных кабинета/чата в одном процессе теоретически делят один tmp-путь (гонка, не утечка — оператор один).
- **#7 (fail-open):** если `isolated_claude_config_dir` возвращает `None` (home_dir недоступен / create_dir_all упал), `env_remove("CLAUDE_CONFIG_DIR")` на строке 384 УЖЕ выполнен безусловно, а условная установка (:393) не срабатывает → дочерний процесс claude падает на ДЕФОЛТНЫЙ `~/.claude` оператора. Изоляция проваливается «в открытую», не заметно.

Живой аудит .exe (три теста из «Проверка», scope-отказ + инъекция-как-данные) НЕ проводился в рамках этого зонда — задача была статическим чтением кода, не сборкой/запуском продукта.

**Уверенность:** высокая на статическую часть (helper вербатим, safe-mode отсутствует, current_dir до env — всё видно в исходнике и совпадает буквально с тем, что уже записал реестр для EC). Средняя на «живой аудит PASS» — я его не повторял, полагаюсь на запись реестра 2026-07-19 + собственное подтверждение, что код с тех пор не менялся в этой части (нет более новых коммитов в claude.rs, трогающих helper).

---

## CPD-23 — предлагаемый статус: 🟢 (широко покрыто регрессией; полная инвентаризация «что НЕ покрыто» — за пределами зонда)

**Зонд:** поиск в `sidecar/econometrica/tests/` и `src/lib/__tests__/` файлов на `single_source`/`parity`/`ssot`/`guard`; чтение найденных тестов.

**Вывод зонда:**
```
sidecar/econometrica/tests/test_mqs_tier_rust_single_source.py
sidecar/econometrica/tests/test_mqs_tier_single_source.py
sidecar/econometrica/tests/test_inverse_cpp_ssot.py
src/lib/__tests__/ratio-single-source.guard.test.js
src/lib/__tests__/kpi-contract-parity... (через kpi-contract-parity.test.js в src/tests/)
src/lib/__tests__/decomposition-view-parity... (src/tests/decomposition-view-parity.test.js)
src/lib/__tests__/metric-views.guard.test.js
src/lib/__tests__/tier2-roi-base.guard.test.js
src/lib/__tests__/goalseek-corridor-honesty.guard.test.js
src/lib/__tests__/negative-baseline-insight.guard.test.js
src/lib/__tests__/ratio-gate-and-holidays.guard.test.js
src/lib/__tests__/breakeven-disabled-disclosure.guard.test.js
src/lib/__tests__/chat-message-field-parity.coverage.test.js
```

**Адрес:** `sidecar/econometrica/tests/test_mqs_tier_single_source.py`, `test_mqs_tier_rust_single_source.py`, `test_inverse_cpp_ssot.py` + `src/lib/__tests__/*.guard.test.js` (список выше) + `src/tests/kpi-contract-parity.test.js`, `src/tests/decomposition-view-parity.test.js`.

**Разбор:** У EC этот класс дефекта — не гипотеза, а история. Докстринги тестов документируют РЕАЛЬНЫЕ прошлые инциденты ровно того же корня, что CPD-23:
- MQS-порог показывал разный ярлык («Хорошее» vs «приемлемо») на HTML/PPTX слайде против единого источника (`test_mqs_tier_single_source.py`, инцидент L16 2026-04-29, рецидив 2026-07-25/26);
- та же лестница разошлась ТРЕТИЙ раз в Rust-слое отчётов (`report.rs` держал свою 80/60 в 4 местах — вердикт XLSX, 2 рекомендации markdown, глоссарий) — найдено внешним аудитом 2026-07-27, зафиксировано `test_mqs_tier_rust_single_source.py`, который структурно парсит `mqs_tiers.rs::MQS_TIERS` и сверяет порог-в-порог/ярлык-в-ярлык/цвет-в-цвет с питоновским каноном, и отдельно гарантирует, что `report.rs` больше НЕ содержит голых чисел лестницы;
- CPP (цена единицы) считалась по-разному для вкладок «От бюджета» и «От цели» (training-frozen pickle vs текущий `project.json`) — `test_inverse_cpp_ssot.py` держит SSOT-приоритет (`override > project.json > pickle`) через `_resolve_current_unit_costs`.

Плюс 10 JS-side гвардов на конкретные метрики (ratio, KPI-контракт, decomposition view, tier2 ROI base, goalseek corridor, negative baseline insight, breakeven disclosure, chat-message field parity) — это заметно более зрелая защита от класса CPD-23, чем «есть ли вообще что-то» в среднем по линейке.

Задача просила «оценить, какие величины НЕ покрыты» — это по объёму отдельный полноценный аудит (нужно выписать ВСЕ поверхности по методу самого CPD-23, п.1 проверки), что выходит за рамки зонда. В рамках зонда нашёл ТРИ независимо задокументированных исторических инцидента и минимум 13 регрессионных тестов-гвардов — реестр сейчас держит EC как «?», это явно занижает фактическое состояние; корректнее — 🟢 с пометкой «известные инциденты закрыты структурно, полная инвентаризация непокрытых метрик не проводилась».

**Уверенность:** средняя. Высокая на «то, что нашёл — реально и подтверждено кодом+докстрингами инцидентов»; средняя на полноту (не выписывал ВСЕХ клиентских поверхностей продукта, как требует пункт 1 методики проверки самого CPD-23 — это отдельная работа по объёму, не влезающая в зонд).

---

## CPD-24 — предлагаемый статус: ⚪ не применимо

**Зонд:**
```
grep -rn "<sup>|²|R\^2" sidecar/econometrica/aurora_pptx sidecar/econometrica/aurora_html docs/GLOSSARY_v2_1_0.md
grep -n "²" tools/build_glossary.py
find sidecar/econometrica src-tauri/src -iname "*docx*"   # искал docx/rtf-конвертер
```

**Вывод зонда:** искал HTML/RTF-разметку надстрочного индекса (`<sup>`, `<span class="...">` вокруг цифры), которая могла бы теряться при конвертации в текст — по механике CPD-24 (LG, потеря `<span class="W9">1</span>` при HTML/RTF→текст). Не нашёл ни одного такого конвейера у EC:
- `tools/build_help_pdf.py` — HTML→PDF идёт через headless Microsoft Edge (`--print-to-pdf`), это полноценный рендеринг браузером готовой DOM, а не текстовый экстрактор; `extract_body()` (:500-503) вырезает только `<script>`, разметку внутри body не трогает — надстрочные теги, если бы были, отрендерились бы визуально корректно.
- `tools/build_glossary.py` + `docs/GLOSSARY_v2_1_0.md` — источник глоссария markdown, надстрочные величины (R², R-hat) записаны ЛИТЕРАЛЬНЫМ unicode-символом «²» прямо в тексте, не HTML-тегом; slug-regex (`build_glossary.py:178`) явно держит «²» в whitelist символов при генерации id (`r"[^\w\s²Ѐ-ӿ-]"`) — конвейер md→json→html→js несёт символ как обычный печатный знак на всех трёх выходах.
- `sidecar/econometrica/aurora_pptx/builder.py` — R²/θ² тоже литеральные unicode-символы в python-строках (`"R²"`, `"θ²·x_{t-2}"`), не markup, парсить/терять нечего.
- docx-конвейера в EC нет вовсе (`find` по `*docx*` в sidecar и src-tauri/src — пусто).

**Адрес:** механики нет — искал HTML/RTF-конвертер с markup-based надстрочными тегами в PDF/глоссарий/PPTX конвейерах EC, нашёл только browser-рендеринг (Edge print) и литеральные unicode-символы напрямую в исходных строках/markdown.

**Разбор:** Корень CPD-24 — конвертер, который извлекает ТЕКСТ из HTML/RTF и по дороге теряет разметку (`<span>`) вокруг надстрочного индекса. У EC такого шага нет: единственная HTML→PDF конвертация рендерит браузером (визуально верно по построению), а везде, где нужна надстрочная нотация в других форматах — она уже литеральный символ в исходнике, не разметка, которую можно потерять при конвертации. Это принципиально другой домен и от легал-норм (EC не цитирует статьи законов), и от механики потери разметки.

**Уверенность:** высокая. Проверил все три поверхности, которые задание просило проверить явно (HTML→PDF, генератор глоссария, PPTX-сборщик), нашёл единый паттерн (никакой markup-конвертации надстрочных знаков нет вообще) по всем трём.

---

## CPD-32 — предлагаемый статус: 🔴 подтверждён (тот же корень, что LG, статически, без запуска .exe)

**Зонд:** `grep -n "auto_save_and_convert\|unwrap_or(delta_text)\|final_text\|MIN_MEANINGFUL\|API Error" src-tauri/src/commands/claude.rs`

**Вывод зонда:**
```
538:            let partial_text = result_text.unwrap_or(delta_text);
560:    let final_text = result_text.unwrap_or(delta_text);
562:        auto_save_response(&app_handle, work_dir, &cabinet_id, prompt, &final_text, timed_out);
583:    if final_text.trim().is_empty() {
594:    match std::fs::write(&export_path, final_text) {
598:        convert_to_docx(&export_path);
599:        convert_to_pdf(&export_path);
600:        convert_to_xlsx(&export_path);
```
`MIN_MEANINGFUL` и `API Error` — 0 совпадений в файле.

**Адрес:** `src-tauri/src/commands/claude.rs:560-567` (`final_text`), `:575-608` (`auto_save_response`), `:594-600` (запись + тройная конвертация).

**Разбор:** Ровно та же форма, что подтверждённый инцидент у Legal Center. `final_text = result_text.unwrap_or(delta_text)` — то, что накопилось в потоковом JSON от процесса Claude CLI (поля `content_block_delta`/`result`), без разбора, состоялся ли ответ или канал оборвался. Единственный гейт перед записью — `final_text.trim().is_empty()` (:583): пропускает ЛЮБОЙ непустой текст, включая сообщение вида «API Error: Connection closed mid-response», которое (по механике, задокументированной у LG) может прийти в тех же JSON-полях, что обычный текст ответа. После записи `.md` файл сразу проходит `convert_to_docx`/`convert_to_pdf`/`convert_to_xlsx` (:598-600) — то есть ошибочный текст размножается ещё в три формата. У EC даже нет частичной защиты, которая была (пусть и не на том рубеже) у LG — `MIN_MEANINGFUL_BODY_CHARS`: в claude.rs EC такой константы нет вообще, `grep` не нашёл.

Отдельно заметил: на retryable-error пути (:536-548) `partial_text` тоже пишется в `exports/*-partial.md` тем же способом — без проверки содержимого, только non-empty.

Живое воспроизведение (пункты 1 и 3 методики проверки реестра — grep по реальным клиентским exports на «API Error», обрыв канала на реальном прогоне) НЕ делал: нет доступа к клиентской машине с историей exports, а обрыв канала вживую потребовал бы либо запуска продукта, либо правки кода для инъекции строки — задача явно про зонд без сборки/изменения продукта.

**Уверенность:** средняя-высокая. Высокая на «код структурно идентичен подтверждённому у LG дефекту и гейта по содержимому нет вовсе» (это то, что просит пункт 2 методики проверки, и он дал однозначный результат). Средняя на «баг обязательно проявится в проде именно так» — это зависит от того, действительно ли Claude CLI в этой конкретной сборке способен вернуть текст обрыва канала как валидное поле `result`/`content_block_delta`, а не как отдельно классифицируемую (`classified_errors`) ошибку с другим кодом выхода — этого я не проверял (потребовало бы воспроизведения реального обрыва сети во время запроса).
