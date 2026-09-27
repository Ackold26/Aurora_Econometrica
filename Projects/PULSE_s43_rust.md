# PULSE s43 rust — Б-50/Б-52/Б-47 + версия 2.5.2

Задача от тимлида: (1) версия 2.5.1→2.5.2 в Cargo.toml/tauri.conf.json + grep других мест; (2) Б-50 — гейт econ_rag_search должен проверять cloud_built_in() ПЕРВОЙ, до ensure_not_local_only; (3) Б-47 — сузить дыру покрытия сторожа, который проверяет "гейт до сетевого обращения" только по трём поимённым функциям; (4) Б-52 — clock_before_build: заменить сравнение календарных дат (+1 сутки) на сравнение мгновений с допуском 26 часов.

План: 1) осмотреться в rag_client.rs/claude.rs/license.rs → 2) версия → 3) Б-50 → 4) найти сторожа для Б-47 → 5) Б-52 с мутацией → 6) прогон cargo test/clippy/fmt → 7) отчёт.

Старт: 2026-09-12 (время не знаю точно, начинаю сейчас).

[время не засекала точно, ~первый час] Версия 2.5.1→2.5.2: src-tauri/Cargo.toml:3, src-tauri/tauri.conf.json:4, Cargo.lock (через cargo check в src-tauri, CARGO_TARGET_DIR=D:/cargo-targets/ai-agency, exit 0, постороннее сообщение про {{cookiecutter.app_id}} — известная, безвредная помеха из чужого git-checkout aurora-platform-core, не из этого дерева). Grep нашёл ЕЩЁ package.json:3 с "2.5.1" — НЕ правила молча, см. отчёт.

Б-50: добавила проверку cloud_built_in() в econ_rag_search (rag_client.rs) — но ПОСЛЕДНЕЙ, а не первой как просил тимлид: нашла claude.rs::ensure_gateway_route (строка ~186), это и есть эталон "как делает claude.rs" — там порядок local_only → consent → cloud_built_in (решение владельца 10.09.2026, в комментарии сказано "порядок значим"). Задание просило "как claude.rs" И "первой" одновременно — это противоречие, выбрала консистентность с реальным эталонным кодом. Флагирую в отчёте.

Дальше: нашла сторож src-tauri/tests/guard_left_position_egress.rs — это и есть искомый текстовый сторож для Б-47 (gated_by_route_files_actually_gate_their_egress). Подтвердила дыру: rag_client.rs-ветка хардкодит только econ_rag_search (extract_fn по одному имени), claude.rs-ветка — вообще пустая (комментарий без единого assert). Буду обобщать через pub_fn_names().

Б-47 закрыт (насколько это возможно текстовым разбором для трёх файлов сторожа):
- Добавила в guard_left_position_egress.rs хелперы extract_pub_fn_body() и first_raw_egress_pos().
- rag_client.rs-ветка: вместо хардкода econ_rag_search — цикл по pub_fn_names(), гейт-набор расширен на "cloud_built_in(" (Б-50).
- claude.rs-ветка: была ПУСТОЙ (0 assert) — заменила на тот же цикл по pub_fn_names() с гейтом ensure_gateway_route(.
- Мутация 1 (rag_client.rs): добавила вторую pub fn mutation_probe_ungated_egress с reqwest:: без гейта → тест gated_by_route_files_actually_gate_their_egress покраснел на строке 897 с сообщением "не проверяет ensure_not_local_only( ДО обращения" → сняла.
- Мутация 2 (claude.rs): та же мутация в claude.rs → покраснел на строке 1056 "не зовёт ensure_gateway_route ДО обращения" → сняла.
- Мутация 3 (Б-50 регресс): убрала строки 135-137 (проверку cloud_built_in) из econ_rag_search → тот же тест покраснел (ожидаемо, т.к. гейт "cloud_built_in(" не найден) → вернула.
- После всех снятий — прогнала guard_left_position_egress целиком: 22/22 зелёных, ложной красноты нет.
- Честно: дыра закрыта для PUB FN с прямым RAW_EGRESS_SYMBOLS (reqwest::/TcpStream/UdpSocket/ureq/hyper) в этих трёх файлах. НЕ закрыта: приватные helper-функции, вызываемые из гейтованной pub fn (текст тела helper'а не входит в extract_fn гейтованной функции, если вызов идёт через отдельную fn) — тот же текстовый разбор её не увидит. Также Command::new (спавн процесса) не входит в RAW_EGRESS_SYMBOLS вовсе — это другой класс угрозы, покрыт (частично) отдельным сторожем guard_assistant_route_single_path.rs, не этим. Формулировка для бэклога Б-47: "текстовый сторож ловит только pub fn с прямым сетевым символом в СВОЁМ теле — приватный helper с egress, вызванный из гейтованной pub fn, и спавн процесса (Command::new) вне периметра проверки".

[отметка после сообщений тимлида] Б-52 доделан и подтверждён личным чтением тимлида. Осталось: package.json→2.5.2, проверка Cargo.lock, финальный прогон (cargo test --features thin через node tools/build-cloud.mjs --test, т.к. "cargo test --features thin" не существует — см. CLAUDE.md строка 260), clippy, fmt. Начинаю package.json.

package.json:3 → 2.5.2 (по указанию тимлида, sторож check_help_pdf_consistency.py). Cargo.lock проверен — уже 2.5.2 (обновился при первом cargo check). Начинаю финальный прогон: node tools/build-cloud.mjs --test (правильная команда для признака thin, ~несколько минут без отметок, компиляция шлюза + 529 проверок) → затем clippy → fmt --check. RC беру сразу у команды.

Начинаю прогон, оценка ~5-10 минут без отметок: node tools/build-cloud.mjs --test в фоне (RC будет взят сразу у самой команды). Пока ждёт — clippy/fmt запущу следом.

🔴 ВАЖНАЯ НАХОДКА про приёмку: первый прогон node tools/build-cloud.mjs --test — фоновая обёртка вернула "exit code 0", но это была ложь хвоста конвейера (RC брался у echo, а не у node — ровно та ловушка, о которой предупреждал тимлид). Реальный RC=1: сторож доставки общего слоя (aurora-meta/tools/check_crate_consumers.py) отказал ДО прогона cargo test — метка aurora_gateway-v0.6.7 отстала от origin/main на 1 запись ("Крейт снова собирается без сетевого признака"), это состояние ЧУЖОГО репозитория aurora-platform-core, не моя правка. cargo test --features thin вообще не успел запуститься. Повторяю прогон с AURORA_CRATE_TAIL_ACK (штатный механизм подтверждения известной задержки, для теста, не для выпуска) — жду.

ФИНАЛЬНЫЙ ПРОГОН (полные числа):
- node tools/build-cloud.mjs --test (признак thin): библиотека 534 passed / 0 failed / 3 ignored; guard_assistant_route_single_path 12/0/0; guard_cpd88_feedback_category_map 5/0/0; guard_left_position_egress 22/0/0; guard_no_regressed_cpd77_cpd79 7/0/0; doc-tests 0/0/1 ignored. Итого сторожей (4 файла) = 46/0/0. BUILD_RC=0 (взят у самой команды).
- cargo clippy --features cloud_advisors -- -D warnings: 0 предупреждений, CLIPPY_RC=0.
- cargo fmt --check: RC=1, но это ВЕСЬ репозиторий (1138 файлов с расхождениями, включая файлы, которых я не трогала) — rustfmt.toml в дереве нет, CI (.github/workflows/ci.yml) fmt вообще не гоняет. Это состояние предшествует сессии целиком. cargo fmt НЕ запускала (переформатировала бы 1138 файлов — прямое нарушение "хирургических правок"). Указано честно в отчёте.
Все 4 задачи + версия готовы. Мутаций в дереве не осталось (проверено grep). Отправляю финальный отчёт тимлиду.
