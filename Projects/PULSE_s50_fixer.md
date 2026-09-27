# PULSE s50 fixer

## Задача (пересказ)
Две правки в Optimizer MMM (Econometrica), дерево thinwt, ветка master, без вложенных агентов.
1. Перенести коммит 44961d01 (CPD-84: неопознанный продукт получает пустой список кабинетов) с ветки feat/econ-kpi-units в master через cherry-pick, доказать цитатой кода, что Эконометрика сама не станет «неопознанным продуктом» (map_pkg_to_product → ключ Эконометрики → filter_by_product возвращает кабинет econometrist), добавить тест если его нет, положительный контроль мутацией.
2. Доля вклада канала в таблице каналов округляется до целого в двух местах (sections.py:1385, builder.py:1194-1195) — тот же класс дефекта, что находка 5 аудита s47 (уже закрыта в fmt_share_pct с одной десятой). Привести к единому форматированию с одной десятой, тесты с пропорцией 87.5/7.5/5.0 = сумма 100.0, положительный контроль мутацией.
Приёмка: ядро (build-cloud.mjs --test, было 629/0) + движок pytest (было 1755/0/2 skipped) — 0 упавших. Два отдельных коммита, без push.

## План
1. git show 44961d01 целиком, проверить merge-tree.
2. cherry-pick, найти CARGO_PKG_NAME/map_pkg_to_product для Эконометрики, доказать cfg-ветки cloud_advisors, добавить тест при необходимости.
3. Мутация-проверка (правка 1): вернуть `_ => None`, прогнать тест модуля, откатить.
4. Прочитать sections.py/builder.py окружение, fmt_share_pct докстринг, привести к общему форматированию.
5. Тесты правки 2 + мутация-проверка.
6. Полная приёмка (ядро + движок).
7. Два коммита.

## Журнал
- 2026-09-27 02:00:41 — старт, дерево прочитано, git status снят (чужие незакоммиченные файлы не трогаю).
- 2026-09-27 02:06 — cherry-pick 44961d01 → master прошёл БЕЗ конфликтов (auto-merge обоих файлов), новый хэш 6a7d3b61.
- 2026-09-27 02:07 — доказательство: Cargo.toml `[package] name = "aurora-econometrica-gui"`; online_auth.rs имеет явную ветку `"aurora-econometrica-gui" => "econometrica"` ДО `_` (не тронута пикапом); cabinet.rs `filter_by_product` имеет явные cfg-ветки `"econometrica" => Some(&["econometrist"])` (cloud_advisors) / `Some(&[])` (без фичи) ДО `_` (тоже не тронуты). Значит правка `_ => Some(&[])` Эконометрику не задевает.
- 2026-09-27 02:10 — 6 тестов цепочки (включая 2 новых) прогнаны без мутации — все ok (`cargo test --lib` в src-tauri, фильтр по именам).
- МУТАЦИЯ ВНЕСЕНА: src-tauri/src/commands/cabinet.rs:139, `_ => Some(&[])` → `_ => None` (откат CPD-84).
- Тест `unnamed_product_key_falls_through_to_empty_not_to_all_cabinets` покраснел (13 из 13 кабинетов вместо 0) — мутация поймана.
- МУТАЦИЯ ОТКАЧЕНА: cabinet.rs:139 обратно `_ => Some(&[])`. Тест снова ok. Правка 1 завершена, коммит пока не сделан (сначала правка 2).
- 2026-09-27 02:10 — Правка 2: добавлена share_pct_value в utils/kpi_display.py, переписаны sections.py:1385/1404 и builder.py:1194-1195 через неё (одна десятая, без "%" — он в шапке). Добавлены тесты: tests/test_kpi_display_registry.py (TestSharePctValueRounding, 3 теста) и tests/test_report_text_kpi_aware.py (TestActionTableShareOneDecimal, 2 теста: HTML + PPTX rows). Целевой прогон `python -m pytest sidecar/econometrica/tests/test_kpi_display_registry.py sidecar/econometrica/tests/test_report_text_kpi_aware.py -q` — 45 passed.
- МУТАЦИЯ ВНЕСЕНА: sidecar/econometrica/aurora_html/sections.py:~1387 `share_pct = _share_pct_value(...)` → временно `int(round(...))`; builder.py:~1194 аналогично.
- Оба мутанта покраснели одинаково: [88.0, 8.0, 5.0] вместо [87.5, 7.5, 5.0] — мутация поймана в обоих местах (HTML и PPTX).
- МУТАЦИЯ ОТКАЧЕНА: оба файла обратно на share_pct_value(...). Повторный целевой прогон — 45 passed. Правка 2 завершена. Далее — полная приёмка (ядро + движок), затем два коммита.
- Примечание для образцов: Projects/_demo_samples_s49/ после этой правки устарели по столбцу «Доля» (были целые %, теперь одна десятая) — образцы не пересобирал (вне задачи).
- 2026-09-27 02:11 — ухожу в прогон ядра `node tools/build-cloud.mjs --test` (~5-15 минут), в фоне, вывод в файл.
- 2026-09-27 02:15 — ядро завершилось, EXIT_CODE=0: 634 passed / 0 failed / 4 ignored (было 629/0 — ровно +5 новых тестов Rust: 3 из cherry-pick + 2 моих). Параллельно движок `python -m pytest sidecar/econometrica/tests` — EXIT_CODE=0: 1760 passed / 2 skipped / 0 failed (было 1755/0/2 skipped — ровно +5 новых тестов pytest). Оба прогона зелёные, приёмка пройдена. Перехожу к двум коммитам.
- 2026-09-27 02:18 — секреты в git diff проверены (grep sk-ant-/ghp_/xoxb-/AIza/gho_/eyJ) — 0 совпадений. Два коммита сделаны своими pathspec, без push:
  1. `be1d569a` test(econometrica): CPD-84 — имя пакета Эконометрики опознаётся (только online_auth.rs, тесты).
  2. `af8c2015` fix(отчёт): доля вклада канала с одной десятой — вторая точка класса находки 5 аудита s47 (kpi_display.py, sections.py, builder.py, 2 тестовых файла).
  (Cherry-pick `6a7d3b61` — отдельный, третий коммит, сообщение исходное сохранено.)
- Чужие незакоммиченные файлы дерева (.impeccable/hook.cache.json, PULSE_s45/s46, SAMPLES_s49, tokens.generated.css, множество Projects/*) — не тронуты, git status подтверждён после коммитов.
- 2026-09-27 02:17 — правка от лидера ДО этой точки уже после моей приёмки: комментарий «CARGO_PKG_NAME в тесте недоступен» неверен, env!() работает в тестах так же. Заменяю жёсткую строку "aurora-econometrica-gui" на env!("CARGO_PKG_NAME") в обоих новых тестах online_auth.rs — так тест ловит будущее переименование пакета, а не подтверждает сегодняшнюю строку.
- Целевой прогон (`cargo test --lib` с фильтром по 2 именам) — ok, 2 passed.
- МУТАЦИЯ ВНЕСЕНА: src-tauri/src/commands/online_auth.rs, ветка `map_pkg_to_product`: `"aurora-econometrica-gui" => "econometrica"` → временно `"переименовали-пакет" => "econometrica"` (имитация будущего переименования пакета без правки Cargo.toml).
- Оба теста покраснели: left="unknown"/[] вместо "econometrica"/["econometrist"] — мутация поймана (это и есть смысл замены на env!()).
- МУТАЦИЯ ОТКАЧЕНА: ветка обратно `"aurora-econometrica-gui" => "econometrica"`. Целевой прогон 2 passed. Ухожу в повторную полную приёмку ядра.
- 2026-09-27 — повторная полная приёмка ядра завершилась, EXIT_CODE=0: 634 passed / 0 failed / 4 ignored (те же числа, что и до правки — замена строки на env!() поведение не меняет). Новый коммит `21526770` (НЕ amend) поверх be1d569a. Секреты в git diff проверены — 0 совпадений. Хук lefthook — зелёный.
- ЗАВЕРШЕНО (с учётом правки ревьюера). Всего 4 коммита: 6a7d3b61 (cherry-pick) → be1d569a (тест v1) → af8c2015 (доля вклада) → 21526770 (тест v2, env!()). Приёмка ядра прогнана дважды, оба раза 634/0/4. Приёмка движка — один раз, 1760/2/0 (не затронута правкой env!(), перепрогонять не требовалось).
- Существующие тесты cabinet.rs:611-624 (`cloud_edition_exposes_econometrist_advisor` / `local_edition_hides_all_advisor_cabinets`) уже проверяют полную цепочку ключ→кабинеты для обеих cfg-редакций. НЕ проверено: имя пакета→ключ продукта для Эконометрики (map_pkg_to_product появился только в этом пикапе, тест коммита покрывает только agency/unknown). Добавляю тест в online_auth.rs.
