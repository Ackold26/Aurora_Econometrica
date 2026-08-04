# Живой журнал внешнего аудита (post_audit.diff)

Формат: severity | file:line | суть | сценарий отказа

High | sidecar/econometrica/tests/test_report_rs_wiring.py:90-95 | сторож проводки обманывается сохранённым, но обезвреженным вызовом | ДОКАЗАНО МУТАЦИЕЙ: 3 реальных вызова clean_label заменены на `{ let _dead = clean_label(x); x }` — результат отброшен, дальше идёт сырое значение; сторож 7 passed. Клиент снова получает имена каналов с переносами строк, набор зелёный.

Medium | sidecar/econometrica/tests/test_thinness_caveat_mirror.py:588 | сравнение зеркала ОДНОСТОРОННЕЕ: overlap = |py∩rs| / |py| | Rust-формулировку можно ДОПОЛНИТЬ любым текстом при 100% overlap. Дописать «Результаты использовать нельзя» (нет в списке трёх запретных оборотов) → сторож зелёный, клиент получает в XLSX алармизм, отсутствующий в HTML/PPTX — ровно тот дефект, ради которого сторож написан.

Medium | sidecar/econometrica/tests/test_thinness_caveat_mirror.py:622 | запрет отброшенных оборотов сверяет ТОЧНЫЕ строки | «результаты ненадёжные» / «результаты не надёжны» / «риск переобучения высокий» проходят насквозь.

Medium | sidecar/econometrica/tests/test_glossary_seam_parity.py:348-360 | порог «≥20 терминов» при заявленных 50 | поломка build_glossary.py, отдающая 25 терминов, оставляет сторож зелёным; клиент получает половину листа «Глоссарий».

Low | sidecar/econometrica/tests/test_thinness_caveat_mirror.py:557,578 | ветви оговорки сопоставляются по ПОРЯДКУ в файле (idx0=критическая) | появление третьей строки «⚠ Данных…» выше по report.rs сдвигает индексы → ложное срабатывание либо сверка не тех пар.

Low | sidecar/econometrica/tests/test_glossary_seam_parity.py:334-345 | test_rust_keeps_builtin_fallback ищет "MQS"/"Adstock" в ЛЮБОМ месте продакшн-кода | запасной список можно вырезать, оставив эти строки в другом месте — сторож зелёный, лист «Глоссарий» пуст при вызове без параметра.

Low | sidecar/econometrica/tests/test_css_comments_do_not_swallow_rules.py:181 | порог live >= total*0.5 не отражает исходный дефект | для app.css проглоченный @font-face не меняет счёт переменных вовсе; ловит только соседний тест баланса /* */.

## Проверено, дефектным не признано
- Зона 2 (строка 12 XLSX): раскладка листа Executive Summary — 0-2 шапка, 3 заголовки, 4 MQS, 5-8 метрики, 9 tier, 10 R-hat, 11 оговорка, 12 плашка; ниже только ширины колонок. Строка 12 свободна при любых входах. Пустой optimize["model_reliability"] → Null → as_str() None → "" → плашка не пишется, паники нет.
- Зона 5 (удаление шести файлов): synth_retail_chain.xlsx вытеснен synth_retail_ecom.xlsx (test_sample_data_ssot.py:119); synthetic_truth_reference.py строит путь динамически (PILOTS / cfg['file']), но cfg['file'] = synth_retail_ecom.xlsx. Оба DiagnosticsPanel и StepSummaryStub — живых импортов нет.
- Зона 1(б): все пять переписанных примеров смысл сохранили, арифметика цела (2,1/15 = 14%).
- Зона 1(а) по глоссарию: «Кагоцел»/«Анаферон» отсутствуют в docs/GLOSSARY_v2_1_0.md, docs/glossary.json, src/lib/glossary.js, src-tauri/help-econometrica/glossary.html.
- §18 CLAUDE.md: правок content-packs/*.json в диффе нет → re-sign не задет.

## Требует проверки (не находки)
- PDF-справка src-tauri/help-econometrica/econometrica-help.pdf — клиентский артефакт, текст сжат, поиском по имени не проверяется ни автором, ни мной.
- Имя клиента живо в docs/ вне глоссария (CHANGELOG_v2.1.0-rc1.md:147, BUILD_WINDOWS_v2_1_0.md:141,169, PILOT_SCENARIO_KAGOCEL.md, audits/*, adrs/ADR-020:96) — вопрос в том, что из docs/ уезжает в поставку.
- test_glossary_seam_parity.py::_call_window берёт 25 строк ВНИЗ от строки с invoke( — форма вызова в ReportStep.svelte не читалась.
