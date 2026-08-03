# Пульс B — зонды CPD-15, CPD-23, CPD-24, CPD-32 для Econometrica

## Задача своими словами
Проверяю 4 клетки колонки Aurora AI Econometrica в реестре кросс-продуктных дефектов (`aurora-meta/CROSS_PRODUCT_DEFECT_REGISTRY.md`). Не чиню код — только зонд (команда + фактический вывод + файл:строка) на каждый пункт:
- CPD-15: кабинетный Claude CLI под --safe-mode теряет project-root CLAUDE.md / изоляция пользовательского слоя
- CPD-23: расхождение одного значения в двух местах (экран vs файл, Python-движок vs JS-интерфейс)
- CPD-24: надстрочная типографика теряется при конвертации (HTML→PDF, глоссарий, PPTX)
- CPD-32: сообщение об обрыве сохраняется как полноценный результат с шапкой продукта

## План
1. Прочитать записи реестра (строки указаны) для точных формулировок зонда
2. CPD-15 — проверить, есть ли у Econometrica кабинетный запуск Claude CLI вообще
3. CPD-23 — найти parity/single_source тесты в sidecar/econometrica/tests/, оценить покрытие
4. CPD-24 — проверить HTML→PDF, генератор глоссария, PPTX-сборщик на надстрочные знаки
5. CPD-32 — проверить путь сохранения результата на диск на предмет сохранения текста ошибки как результата
6. Писать в result_B.md по мере готовности каждой клетки

Старт: 2026-08-03 15:30

## Отметки
- 15:32 — прочитаны 4 записи реестра (CPD-15 257-354, CPD-23 438-449, CPD-24 450-477, CPD-32 842-866), выписаны точные зонды
- 15:35 — CPD-15: grep claude.rs подтвердил helper `isolated_claude_config_dir` вербатим (commit 244fccd в git log репо), safe-mode отсутствует, current_dir:378 до env-манипуляций, env_remove CLAUDE_CONFIG_DIR:384. Прочитан код 236-400: tmp-имя ФИКСИРОВАННОЕ (`.credentials.json.tmp`, не per-call) — совпадает с пометкой реестра «#6 не портирован у EC». Fail-open (#7): при None env остаётся REMOVED → откат на дефолтный ~/.claude оператора.
- 15:38 — подтвердил git log: репо на branch feat/econ-canon-p0, commit 244fccd "fix(security): CPD-15" в истории claude.rs — это канонический репо реестра
- 15:42 — CPD-23: нашёл sidecar/econometrica/tests/test_mqs_tier_single_source.py + test_mqs_tier_rust_single_source.py (MQS-паритет Python↔JS↔Rust↔PPTX/HTML) + test_inverse_cpp_ssot.py (CPP SSOT project.json vs pickle). Плюс 10 JS-гвардов в src/lib/__tests__ (ratio-single-source, kpi-contract-parity, decomposition-view-parity, metric-views, tier2-roi-base, goalseek-corridor-honesty, negative-baseline-insight, ratio-gate-and-holidays, breakeven-disabled-disclosure, chat-message-field-parity). Все — реальные прошлые инциденты того же корня, что CPD-23, уже пойманы и заперты регрессией.
- 15:50 — CPD-24: прочитан tools/build_help_pdf.py целиком — HTML→PDF идёт через headless Edge (реальный рендеринг браузером, не markup-strip текстовый экстрактор), extract_body() трогает только <script>. Прочитан tools/build_glossary.py + docs/GLOSSARY_v2_1_0.md — R²/R-hat используют ЛИТЕРАЛЬНЫЙ unicode-символ «²», slug-regex явно оставляет «²» в whitelist. PPTX builder.py — те же литеральные «²»/«θ²» в python-строках, не HTML sup-теги. docx-конвейера в EC нет вовсе (find не нашёл). Механики надстрочных HTML-тегов, теряемых при конвертации, в EC нет — риск CPD-24 относится к markup-based конвейерам (LG normative RAG), не к EC.
- 15:58 — CPD-32: grep нашёл ТОТ ЖЕ паттерн, что у LG: claude.rs:560 `let final_text = result_text.unwrap_or(delta_text);` → auto_save_response (claude.rs:575-608) пишет final_text в exports/ + convert_to_docx/pdf/xlsx БЕЗ проверки содержимого — единственный гейт `final_text.trim().is_empty()` (:583). Нет ни одного маркера отказа (grep "API Error"/MIN_MEANINGFUL — 0 совпадений). Тот же root, что подтверждённый LG-экземпляр, у EC даже без частичной защиты MIN_MEANINGFUL_BODY_CHARS, что была у LG (пусть и не на том рубеже).
- 16:05 — все 4 клетки записаны в result_B.md, работа завершена
