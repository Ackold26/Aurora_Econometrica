# Пульс — разведка режимов в Oracle

Задача своими словами: найти в репозитории Aurora AI Oracle реализацию трёхрежимной схемы
исполнения (локально/облачно/автоматический выбор), чтобы перенести её паттерн в Econometrica.
Смотрю только на чтение: редакции сборки, канал обновлений, ExecutionMode, поведение при
недоступности режима, согласие на облако, офлайн-редакцию, идентификаторы/миграцию данных.

План: 1) найти основное дерево Oracle (не архивное) → git log -1. 2) grep по package.json/
tauri*.conf.json/Cargo.toml на редакции. 3) grep updater.rs update_product_key. 4) grep
ExecutionMode/resolve/probe_local + settings UI. 5) grep молчаливого fallback + текст ошибки.
6) grep ensure_cloud_consent. 7) grep офлайн-редакция 152-ФЗ аналог. 8) grep identifier облачной
редакции + миграция данных.

СТАРТ: 2026-08-09 (время сессии)

Дерево: `_wt_oracle_master`, ветка `master`, tracking `origin/master`,
git log -1 = e2d9d51 (Merge, Sat Aug 8 00:01:31 2026 +0300, "merge(master): передача блока и правка по итогам аудита").
(Проверила также `_wt_oracle_gwsign` — фикс зонда probe_local поверх той же истории,
не влит в master; для отчёта беру master как основное дерево.)

ГОТОВО — все 7 пунктов найдены, отчёт отправлен team-lead.

---

# Задача 2 (2026-08-09) — план слияния редакций Econometrica

Своими словами: сейчас у Econometrica три редакции (обычная `com.aurora.econometrica`,
локальная 152-ФЗ `…econometrica.local`, тонкая/универсальная `…econometrica.thin`).
Владелец решил оставить две: универсальная (переносит паттерн Local/Cloud/Auto из Oracle +
тумблер офлайна) должна ЗАНЯТЬ МЕСТО обычной под identifier `com.aurora.econometrica` без
потери данных клиента; локальная 152-ФЗ остаётся отдельно. Нужен ПОШАГОВЫЙ ПЛАН слияния
(текст, без правок кода), с адресами файл:строка на каждый пункт из 6 вопросов team-lead.
🔴 src-tauri/ не трогать вообще (параллельная линия), только читать.

План разведки: 1) сравнить build-cloud.mjs (наш thin-сборщик) с оракуловским гейтом
checkBuildConfigKeepsProductIdentity. 2) grep tauri.thin.conf.json + com.aurora.econometrica.thin
по всему дереву (сборка/CI/доки/скрипты). 3) updater.rs update_product_key + cloud_advisors vs
thin — доказать код канала. 4) .github/workflows grep на редакции/признаки/identifier, приватность
репо aurora-platform-core. 5) собрать пошаговый план. 6) что лежит в %APPDATA%\com.aurora.econometrica
по коду (лицензия/проекты/кэш/настройки), нет ли путей завязанных на .thin.

СТАРТ: 2026-08-09 (продолжение сессии)

Дерево: `Aurora_Econometrica_thinwt`, ветка `master`, git log -1 = 325ad31 (сегодня, 20:57:44).
🔴 Рабочее дерево ГРЯЗНОЕ: uncommitted правки в claude.rs/execution_mode.rs/test_validator —
чужая параллельная линия (probe_local фикс + CPD-53 2я волна), НЕ трогала, только читала.

ГЛАВНАЯ НАХОДКА: слияние редакций (ADR-049, идентификатор, канал обновлений) уже СДЕЛАНО —
build.rs/updater.rs/build-cloud.mjs/execution_mode.rs все уже отражают целевое состояние
(universal=cloud+local под одним com.aurora.econometrica, local-152ФЗ отдельно). Это часть
большого слияния 22 веток (Projects/audit_merge/handoff.md, 04.08) + сегодняшний прогон
(Projects/merge_probes/gate_master_thin_2026-08-09.log — облачная поставка 403/0, зелено).
Нашла расхождение: Projects/PROGON_PC204_2026-08-08.md описывает СВЕЖУЮ сборку (коммит
4b478b7, уже ПОСЛЕ гейта лица продукта) с идентификатором .thin — противоречит коду.
Не смогла объяснить причину без доступа к самому инсталлятору — вынесла как открытый вопрос.

Проверила: identity-гейт есть (build-cloud.mjs:433-484, портирован 1:1 с Oracle), НЕ покрыт
юнит-тестами (build-cloud.test.mjs — 0 упоминаний), функция НЕ экспортирована.
CI (.github/workflows/ci.yml) не собирает --features thin вообще; release job выключен (if: false).
aurora-platform-core — приватный репозиторий (GitHub API 404 анонимно), но нерелевантно:
ни один CI-путь его сегодня не тянет.
Данные клиента: license/user_config/session_cache — под app_config_dir() (уже единый
identifier), projects/ — под ОТДЕЛЬНЫМ CARGO_PKG_NAME-каталогом (не зависит от identifier
вообще, общий у всех редакций всегда). Риска потери не нашла.

ГОТОВО — отчёт отправлен team-lead.

---

# Задача 3 (2026-08-09, продолжение) — уточнение по гейту и по лицензии

team-lead не увидел полный текст прошлого отчёта (только сводку в журнале) — прошу переслать
целиком + точно ответить на 3 места: (1) вызывается ли гейт `checkBuildConfigKeepsProductIdentity`
фактически при `tauri:build:thin`, и почему не валит сборку при оверлее с productName/identifier;
(2) строгая проверка app_config_dir()/app_data_dir() при смене идентификатора — литеральные пути,
что внутри, доказательство отсутствия потерь при обновлении под тем же identifier, и явный список
потерь если бы выпустили под .thin; (3) когда и почему выключен release-job в CI (git blame),
собирается ли инсталлятор автоматически хоть как-то.

Нашла: гейт ВЫЗЫВАЕТСЯ (build-cloud.mjs:1098-1100, прямо перед spawn), видит forbidden fields
в tauri.thin.conf.json, но applied=false ВСЕГДА на стандартном пути (args для tauri build
build-cloud.mjs:1171-1178 никогда не содержат --config/basename оверлея, npm-скрипт передаёт
0 доп.аргументов) → печатает ⚠ info, не fail. Это ответ (б) из трёх вариантов team-lead.
Vault/content-pack (vault.rs:14, vaults_dir(app_data_dir)) тоже под app_data_dir() —
identifier-scoped, как и license/config. Release-job выключен коммитом 752027cb
(Anton, 2026-07-18 20:10:35, git blame подтверждён) — комментарий в файле дословно совпадает
с сообщением коммита. keepalive.yml — только пинг Supabase, инсталлятор не собирает.

ГОТОВО — уточнённый отчёт отправлен.

---

# Задача 4 (2026-08-09, продолжение) — распаковать и проверить установщик PC204

Разрешено читать за пределами дерева + распаковывать во временный каталог (не менять/не удалять
чужое). Цель: `_wt_econ_gwsign/target/release/bundle/nsis/Optimizer MMM_2.4.4_x64-setup.exe`
(нашла на месте, размер 8 432 095 байт — совпадает с описанием в PROGON_PC204, время Aug 8 02:23).
Ищу строку identifier внутри (com.aurora.econometrica / .thin / .local), отвечаю прямо какой.
Если .thin — ищу источник команды с --config в раннбуках/памяти. Плюс предлагаю сторож вне скрипта.

СТАРТ: 2026-08-09 (продолжение)

Распаковала 7z x → scratchpad/pc204_nsis_extract (249 файлов, NSIS-3 Unicode, всё ок).
Главный бинарник aurora-econometrica-gui.exe (15 818 752 байт). Байтовый поиск (Python,
ASCII+UTF-16LE): "com.aurora.econometrica" — РОВНО 1 вхождение на весь файл (offset 9574376,
слипшееся с соседней строкой "econometrica-sidecar" без разделителя — обычная линковка Rust,
не подмена). "com.aurora.econometrica.thin" — 0. "com.aurora.econometrica.local" — 0.
Подтвердила это ГЕНУИННО тонкая (cloud) сборка: aurora_gateway (3), AuroraCloudClient (1),
gateway_executor (2), cloud_advisors (1) — все внутри. VERSIONINFO (PE-ресурс, независимый
источник): ProductName/FileDescription = "Optimizer MMM", версия 2.4.4, CompanyName =
"Aurora Platform LLC" — тоже без .thin.

ВЫВОД: установщик собран под БАЗОВЫМ identifier com.aurora.econometrica. Открытый вопрос
закрыт — вариант team-lead (5): «в записи прогона употребили старое имя пути по привычке,
дефекта нет». Ничего не удаляла, не меняла — только распаковка в scratchpad.

ГОТОВО — финальный ответ отправлен.

---

# Задача 5 (2026-08-09, продолжение) — реализовать сторож редакции (первая правка кода в сессии)

Разрешено писать код (наконец не только чтение): `tools/check-installer-edition.mjs` +
тесты `tools/__tests__/check-installer-edition.test.mjs`, коммит узким pathspec.
`src-tauri/` и перечисленные чужие файлы — не трогала.

Ключевая находка ПО ХОДУ реализации: первая версия границы префикса (по алфавиту символов
identifier'а) была НЕВЕРНА — `&'static str` в Rust не нуль-терминированы, и живой PC204-бинарник
это доказал (`com.aurora.econometricaeconometrica-sidecar` без разделителя). Переделала на
подавление по РЕЕСТРУ известных identifier'ов вместо алфавита — поймала это САМА, до отправки
кода, прогоном на реальных данных, а не мнением. Расписала в шапке файла как отвергнутый подход.

Прогоны (все в файлы, без `| tail`):
- `Projects/gate_installer_guard.log` / `_full_suite_2026-08-09.log` — 13/13, потом 55/55 вместе
  с build-cloud.test.mjs (регрессии нет).
- Мутация 1 (негативная проверка → `for (const id of [])`) — `Projects/gate_installer_guard_mutation_negative_removed.log`:
  ровно 1 тест красный, точно по адресу.
- Мутация 2 (подавление вложенных → `longerKnown = []`) — `Projects/gate_installer_guard_mutation_prefix_suppression_removed.log`:
  ровно 4 теста красных, все связанные с ловушкой префикса, остальные 9 зелёные.
- Живой PC204-установщик: сырой `.exe` — сторож ОТКАЗАЛ (найдено 0 identifier'ов вообще!).
  Причина — NSIS/LZMA solid-архив, полезная нагрузка сжата, побайтовый поиск по сырому
  установщику бессилен в принципе (проверила: даже заведомо известные строки типа "Nullsoft"
  находятся, а "Optimizer MMM"/"aurora_gateway" — нет). На РАСПАКОВАННОМ бинарнике
  (`aurora-econometrica-gui.exe`, тот же файл что смотрела руками в задаче 4) — universal
  подтверждён (1 вхожд.), local корректно отклонён. Лог: `gate_installer_guard_live_pc204.log`
  (отказ на сыром) + `_extracted.log` (успех на распакованном).
- Локальную 152-ФЗ редакцию НЕ нашла нигде на диске (искала во всех cargo-targets/econ*,
  _wt_econ*, Aurora_Econometrica*, !Aurora_V2_installators) — честно доложила, не выдумывала.
- Бонус: нашла подлинный ДО-мержевый `Optimizer MMM_2.4.3-thin_x64-setup.exe` в
  `!Aurora_V2_installators/` — распаковала, прогнала как universal → корректный отказ по
  чужому `.thin` НА РЕАЛЬНЫХ (не синтетических) данных. Лог: `gate_installer_guard_live_thin243_negative_control.log`.

Коммит `21d72b1` (master, НЕ запушено): `tools/check-installer-edition.mjs` (новый),
`tools/__tests__/check-installer-edition.test.mjs` (новый), `tools/build-cloud.mjs`
(+5 строк комментария у checkBuildConfigKeepsProductIdentity). Staged узко, проверила
`git diff --cached --stat` перед коммитом — только мои 3 файла, чужие правки (src-tauri,
sidecar, tools/test_validator_numeric_role_gate.py) не задеты.

ГОТОВО — отчёт с находкой про сжатие NSIS отправлен team-lead.

