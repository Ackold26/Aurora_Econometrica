# Маячок: pre-build гейт Эконометрики 2.4.10 → 2.5.0

**Старт:** 2026-08-16 23:13 (по `date`)
**Исполнитель:** субагент pre-build gate
**Дерево запуска:** `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt`, ветка `feat/econ-p1-winning`

## Пересказ задачи своими словами

Владелец готовит выпуск 2.5.0 на живой прогон (PC204) и требует собирать только по скиллу `aurora-fix`.
Моя работа — прогнать ПРЕД-СБОРОЧНЫЙ чеклист скилла целиком по этому продукту и вынести вердикт:
сборка разрешена или запрещена. Ничего не собирать, не править, не удалять, не публиковать.
Отдельно установить фактами, из какого дерева собирать (тонкое vs канон) и что заберёт glob в поставку.

## План

1. Прочитать `SKILL.md` целиком + `references/products.md`. ✅
2. Установить деревья продукта на машине, найти собранный движок, состав `bundle.resources`.
3. Пройти проверки V1–V72 по группам, каждая — с фактом.
4. Отчёт разделом «## Отчёт» в этом файле + краткая сводка ведущей.

## Отметки

- 23:13 — старт, чтение скилла (1638 строк) + `references/products.md`.
- 23:15 — установлены деревья продукта, состав `bundle.resources`, свежесть движка.
- 23:18 — пройдены группы A–G, сервер опрошен (app_versions, content_versions).
- 23:21 — отчёт записан ниже.

---

# Отчёт

## Таблица проверок

| # | Статус | Факт |
|---|---|---|
| V1 Версии | **WARNING** | 2.4.10 в трёх местах согласованно: `src-tauri/tauri.conf.json:4`, `src-tauri/Cargo.toml:3`, `package.json:3`. Поднять до 2.5.0 надо все три + `tools/help_pdf_manifest.json:2`. Отдельно `sidecar/econometrica/version_info.txt` отстал ещё сильнее — там 2.4.8 |
| V2 Идентификатор | PASS | `com.aurora.econometrica` = канон |
| V3 APP_VERSION | PASS | Версия берётся у поставки: `+layout.svelte:94` `invoke('display_version')` (`lib.rs:445`), сравнение с `app_min_version` под охраной `appVersion &&` (:170); настройки — тем же источником. Константы нет |
| V52 productName | PASS | «Optimizer MMM» — не менялось с выданных клиентам 2.4.x |
| V4/V5 Хранилища | PASS | `New_AI_Agency/econometrist/` на месте |
| V6 PRODUCT_CABINETS | N/A | `tools/aurora-pack.py` в дереве нет |
| V28 cabinet.rs ↔ cabinets.json | PASS | econometrist: 8 команд, совпадение полное, расхождений 0 |
| V48/V54 Кабинеты | N/A | Один кабинет, срез-/алиас-кабинетов нет (`cabinet_folder_name` без нетождественных веток) |
| V7 Состав пакета | PASS (адаптир.) | 6 JSON + `manifest.sig` ровно 64 байта. Папки `help/` нет и не требуется: справка едет отдельным ресурсом `help-econometrica/*`, манифест её не перечисляет |
| V8 Суммы манифеста | PASS | 6/6 файлов сошлись по SHA-256, BOM нет |
| V53 Дрейф сервера | PASS | Репо `version: 7` = сервер `content_pack_version: 7` (строка `c3`, is_current). При равных номерах доп. признак — V8 зелёный, то есть манифест не разошёлся с файлами |
| V70 Порядок подписи | PASS + **WARNING** | Пакет подписан 13.07, с тех пор содержимое не менялось (V8) — рассинхрона нет. Но заслона в коде нет: `beforeBuildCommand` = `"npm run build"`, проверки пакета не зовёт |
| V72 Облачная сборка | **N/A (по коду, не по таблице)** | `tools/build-cloud.mjs:392,1168`: «Оверлей … БОЛЬШЕ НЕ ПРИМЕНЯЕТСЯ (ADR-049 §2)». Наложение у Эконометрики зовётся `tauri.thin.conf.json` (:411), в аргументы сборки не подставляется, лицо продукта держит `checkBuildConfigKeepsProductIdentity` (:1103). Файла `tauri.cloud.conf.json` нет и не нужно — требовать его было бы ложным блокером. Остатков прерванной облачной сборки нет: `Cargo.toml.pre-cloud` и `.cloud-build-running` отсутствуют, `aurora_gateway` в `Cargo.toml` — 0 совпадений |
| V9 Ресурсы существуют | PASS | Все 5 путей на месте: `help-econometrica/` (26 файлов), `sidecar/econometrica/`, `content-packs/`, `src-tauri/sidecar/pptx_pipeline.py`, `NOTICE.md` |
| V10 Пакет в бандле | PASS | `"../content-packs/*"` в `resources` |
| V69 Состав glob | **PASS по клиентским данным, WARNING по балласту** | Разбор ниже |
| V11 Хук NSIS | PASS | `src-tauri/installer_hooks.nsh`, UTF-8 **с BOM** (`efbbbf`) + CRLF (104/104) — makensis подхватит |
| V49 Снятие процессов | PASS | `NSIS_HOOK_PREINSTALL` и `NSIS_HOOK_PREUNINSTALL` оба несут `taskkill` по `econometrica-sidecar.exe` + `aurora-econometrica-gui.exe`, фильтр `USERNAME`, `/T /F`, `Sleep` между |
| V50 Без чёрных окон | PASS | `ExecWait '` — 0 совпадений, всё через `nsExec::` + `Pop $0` |
| V67 Без кракозябр | PASS | `nsExec::ExecToLog` — 0 совпадений; `taskkill`/`netsh` идут через `nsExec::Exec` |
| V51 Апдейтер/UX | PASS + **WARNING** | Окно успеха есть (`:82`, под `IfSilent +2`). Повышение прав — блокирующий `.status()` с `try … -ErrorAction Stop … catch { exit 1 }`, `stop_sidecar()` вызывается. 🔴 Установщик запускается с `-ArgumentList '/S'` **без `/R`** → после тихого обновления программа сама не стартует |
| V12 Справка | PASS | 26 файлов, включая `index/about/user-guide/error-codes/pipeline` + `econometrica.html` + `econ-nav.js` |
| V13 Движок | **BLOCKER** | Разбор ниже (свежесть) |
| V29 collect-data | PASS | Ни одного пакета из списка-риска без `--collect-all/--collect-data`: покрыты arviz (+`_base/_stats/_plots`), pymc, pymc_marketing, pytensor, scipy, sklearn, pandas, openpyxl, xarray, matplotlib, numba, statsmodels, jax, numpyro |
| V34 Обработчик 500 | PASS | `server.py:272` `@app.exception_handler(Exception)` |
| V35 Фильтр asyncio | PASS | `server.py:129–135`, точечный фильтр `_ProactorBasePipeTransport`, глушения `CRITICAL` нет |
| V36 XLA_FLAGS | PASS | `server.py:23` — до любого `import jax` (первый на :200) |
| V37 requirements | PASS | 55 строк, стек MMM закреплён |
| V38 Unicode-safe | PASS | `build_sidecar.py:23–27` |
| V39 Свежесть движка | **BLOCKER** | Разбор ниже |
| V14 Brand Hub | N/A | У продукта нет |
| V15 Иконка | PASS | `icon.ico` 47 088 байт |
| V20 Согласование путей | PASS | `_up_/sidecar/econometrica/…` (`econ_sidecar.rs:469`, с запасным путём :483), `_up_/content-packs` (`lib.rs:2105`), `help-econometrica` (`lib.rs:1992–2024`), `sidecar`/`_up_/sidecar` (`pptx_processor.rs:127`) |
| V21/V23 PPTX | PASS | `sidecar/pptx_pipeline.py` в `resources`, поиск умеет оба пути |
| V22 UTF-8 в питон | PASS | `pptx_processor.rs:170–171` — прямой запуск (не через `cmd /C`) + `PYTHONIOENCODING`/`PYTHONUTF8`; `pptx_pipeline.py:23–24` — `TextIOWrapper` |
| V16 Секреты | PASS | Ключ подписи и `aurora-secrets.env` на месте, `SUPABASE_SERVICE_ROLE_KEY` не пуст |
| V17 npm | PASS | `node_modules/.package-lock.json` (13.08) новее `package-lock.json` (02.08) — `npm ci` не нужен |
| V18 Захват exe | PASS | Ни `Optimizer`, ни `aurora-econometrica-gui`, ни `econometrica-sidecar` в списке процессов нет |
| V19 cargo check | SKIP | Прогнано ведущей: код возврата 0, `Finished` за 18 с |
| V26 Совместимость | PASS | Следует из зелёного `cargo check` |
| V27 Каталог пакета | PASS | Есть |
| V40 `{@html}` | PASS | 11 вставок, гейт `node tools/lint-xss.mjs` — код возврата 0 |
| V41/V44 Архивы | PASS | `project.rs:755,770` — потоковый `std::io::copy`, чтения файла целиком в память нет |
| V45 zip-slip | PASS | `project.rs:847` `entry.enclosed_name()` |
| V42/V43/V46 Питон | PASS | Ни `.format(`-бомб на пользовательских строках, ни `ensure_ascii=False` во встраиваемом JSON в `aurora_html/` не найдено |
| V47 serde default | PASS | Следует из зелёных 1173 тестов Rust на persisted-структурах |
| V55 Ключи продукта | PASS + **WARNING** | Собираемая (облачная) редакция шлёт `aurora-econometrica-gui` — строка в `app_versions` есть (2.4.9). Auth шлёт `econometrica` — строка есть (2.4.0, отстала, поднять на выпуске). 🔴 Локальная редакция (`--no-default-features`) шлёт `aurora-econometrica-gui-local` (`updater.rs:134–139`) — **такой строки в `app_versions` НЕТ**, её клиенты обновлений не увидят никогда |
| V56 Отпечаток машины | SKIP | Не проверяла (см. «что не проверено») |
| V57 Anti-rollback | SKIP | Не проверяла |
| V58 Сравнение версий | PASS | `updater.rs:602` `is_newer` разбирает базу и prerelease раздельно, stable > rc, `rc11 > rc2`; 9 тестов на границы |
| V59 IPC | PASS | 178 команд объявлено, все в `generate_handler!` (шесть «пропусков» — артефакт комментариев внутри списка, проверено вручную); событий с двоеточием нет |
| V60 Протечка вариантов | PASS | Справка содержит только свои страницы; чужих кабинетов нет |
| V61 Безопасность сборки | PASS | `withGlobalTauri` в базовом конфиге — 0 |
| V62 Окна процессов | PASS | 27 спавнов, все консольные — с `creation_flags(0x08000000)`. Четыре «находки» скрипта — ложные: два `kill` (не Windows), `ping` в тесте, `pptx_processor.rs:181` — ветка `#[cfg(not(windows))]` |
| V63 Подсев пакета | N/A (п.1–3) | Локальный пакет **не единственный** источник состава: `cabinet.rs:340` падает в вкомпилированный `get_cabinet_definitions()`. Замерзания на машине без сети не будет. П.4 (bundled ≥ сервера) — PASS через V53; п.6 — после сборки |
| V64 Загрузка vs пусто | PASS | `+page.svelte:53` `loading = !$cabinetsLoaded && !$licenseErrorStore` — по флагу завершения, не по длине списка |
| V65 Точечные glob | см. V69 | |
| V66 Изоляция CLI | PASS | `--safe-mode` отсутствует; `claude.rs:289` `isolated_claude_config_dir` внутри данных приложения, `:429` `.env_remove("CLAUDE_CONFIG_DIR")`, `:439–440` выставление |
| V68 Апдейтер/происхождение | PASS | `apply_update` (`:520`) первой строкой `ensure_launchable`; `is_verified` (`:410`) канонизирует, берёт хеш из реестра и **пере-читает файл сейчас**, все ветки отказа → `false`; обёртка `lib.rs:2675` `download_update(app)` **без** аргументов, фронт `UpdateBlockingOverlay.svelte:51` зовёт без объекта; `is_trusted_update_url` + `Policy::custom` ре-валидирует каждый переход; специфика продукта (UAC `.status()`, `stop_sidecar`, докачка `.part`, rc-aware `is_newer`) цела; тесты на месте, включая TOCTOU |
| V30 Публичный репозиторий | SKIP | Шаг выпуска, не сборки |

---

## 1. Вердикт: **СБОРКА ЗАПРЕЩЕНА**

Один блокирующий дефект, всё остальное — предупреждения.

🔴 **[V13/V39] Собранный движок протух на три дня и не содержит работы, ради которой делается 2.5.0.**
`sidecar/econometrica/econometrica-sidecar.exe` собран **13.08 в 04:38**, а исходники правились по **16.08**. Новее двоичного файла — 27 файлов, и это ровно линия «выигрывать»: `optimize/frontier.py`, `optimize/inverse.py`, `optimize/bounds.py`, `engines/json_export.py`, `engines/modeler.py`, `engines/methodology_cert.py`, `utils/data_fingerprint.py`, `utils/repro_tolerance.py`, `server.py` (146 КБ, 16.08 13:52) + 12 файлов проверок.

Что это значит на машине владельца: установщик поставится зелёным, окно откроется, а профит-фронтир, обратная оптимизация и воспроизводимость будут отвечать кодом от 13-го — то есть либо отсутствовать, либо давать ответ старой формы на новый запрос оболочки. `npm run tauri build` движок **не пересобирает**, страж свежести (`build_sidecar.py:377–400`) живёт внутри сборки движка и при сборке установщика не исполняется — поэтому дефект тихий.

**Лечение:** до сборки установщика прогнать `python sidecar/econometrica/build_sidecar.py` и дождаться `[OK] Freshness verified`. Заодно поднять в `version_info.txt` `filevers`/`prodvers`/обе строки на 2.5.0 — сейчас там 2.4.8, и это попадёт в свойства файла у клиента.

## 2. Из какого дерева собирать: **`Aurora_Econometrica_thinwt`** (после пересборки движка)

Обход всех деревьев продукта на машине:

| Дерево | Ветка | Движок | Клиентские данные в путях ресурсов |
|---|---|---|---|
| `Aurora_Econometrica` (основное) | `feat/econ-kpi-units` | 11.07 | 🔴 **ЕСТЬ: 12 каталогов** `кагоцел-рф-…` прямо в `sidecar/econometrica/` |
| `Aurora_Econometrica_canon` | `feat/econ-canon-p0` | 08.08 | нет |
| `Aurora_Econometrica_thinwt` | `feat/econ-p1-winning` | 13.08 (протух) | нет |

**Опасение о «тонком дереве без движка» здесь не подтвердилось.** В `_thinwt` лежит полная раскладка PyInstaller: `econometrica-sidecar.exe` 67 МБ + `_internal/` 912 МБ + `dist/` 938 МБ. Пустоты glob не забандлит; доказательство от противного — установщик 2.4.10 собран 15.08 из этого дерева и весит 258 648 371 байт, ровно в ряду 2.4.8 (258 663 553) и 2.4.9 (258 549 884).

**А вот второе опасение подтвердилось полностью, только не в том дереве.** В основном `Aurora_Econometrica` каталоги клиентских проектов «кагоцел-рф-…» (мая) **живы на диске до сих пор**. `resources` содержит `"../sidecar/econometrica/**/*"` — сборка оттуда положила бы данные клиента в установщик и разослала бы их всем получателям. Дефект CPD-16, ровно тот, из-за которого решили не собирать из основного дерева. Ничего не трогала — называю: `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica\sidecar\econometrica\кагоцел-рф-*` и `…\кагоцел-рф--данные-для-эконометрики-*`.

**[V69] Балласт в `_thinwt` (WARNING, не блокирует):** glob заберёт `dist/` (938 МБ — второй экземпляр того же движка, рантаймом не читается), `.hypothesis/` (2,1 МБ кэш проверок), `__pycache__/`, `tests/` (4,5 МБ, 102 файла проверок). Клиентских данных, CSV и кириллических каталогов — ноль (проверено поиском).
🔴 **Если решишь сузить glob — сделай это отдельным шагом, не в этом выпуске.** Установщик резко похудеет, и пост-сборочная проверка P1 («меньше предыдущего → BLOCKER») даст ложную тревогу, а отличить «убрали балласт» от «выпали ресурсы» будет уже нечем.

## 3. Точный список правок перед сборкой (вносишь ты)

**Обязательные:**
1. `python sidecar/econometrica/build_sidecar.py` — пересобрать движок, дождаться `[OK] Freshness verified`. Без этого сборка бессмысленна.
2. `sidecar/econometrica/version_info.txt` — `filevers=(2, 5, 0, 0)`, `prodvers=(2, 5, 0, 0)`, `StringStruct('FileVersion', '2.5.0.0')`, `StringStruct('ProductVersion', '2.5.0.0')` (сейчас 2.4.8 в четырёх местах). Правку сделать **до** пункта 1 — она вкомпилируется в движок.
3. Версия 2.4.10 → 2.5.0 в трёх местах: `src-tauri/tauri.conf.json:4`, `src-tauri/Cargo.toml:3`, `package.json:3`.
4. `tools/help_pdf_manifest.json:2` — `"version": "2.5.0"` (если справка перегенерируется, номер приедет сам; если нет — поднять руками, иначе PDF справки будет представляться прошлой версией).

**Желательные (не блокируют, но дешёвые):**
5. `updater.rs` — добавить `/R` к аргументам установщика (`-ArgumentList '/S','/R'`), иначе после тихого обновления программа у клиента не стартует сама. Это тот самый класс «обновилось и ничем не закончилось», по которому уже был отчёт владельца в Docs Lab.
6. `src-tauri/help-econometrica/install.html:46` — в тексте стоит имя файла `Optimizer MMM_2.4.0_x64-setup.exe`, ведёт клиента к позапрошлой версии.
7. `tauri.conf.json` → `"beforeBuildCommand": "npm run check:manifest && npm run build"` — заслон V70 на будущее (скрипт `check:manifest` в `package.json` уже есть).

**На выпуске (после сборки, не сейчас):** поднять **обе** строки `app_versions` — `aurora-econometrica-gui` (её спрашивает клиент) и `econometrica` (2.4.0, отстала). И решить судьбу отсутствующей строки `aurora-econometrica-gui-local`: если локальная редакция у клиентов есть, её канал обновлений мёртв.

## 4. Что я НЕ проверила и почему

- **V19 `cargo check`** — прогнан ведущей (код 0, 18 с), повторно не гоняла по прямому указанию.
- **Полный прогон проверок** (1333 движок / 1471 фронт / типы) — прогнан ведущей, не повторяла.
- **V56 отпечаток машины, V57 anti-rollback** — не читала `fingerprint.rs` и код проверки даты сборки. Причина: обе про лицензирование, обе неизменны в этой ветке (109 изменённых файлов — движок, фронт, Rust-обвязка расчёта, справка; `crypto/` среди них нет), и обе не влияют на решение «собирать или нет». Если хочешь полноты — это ещё десять минут.
- **V30 публичный репозиторий, P1–P9** — фаза выпуска, а не сборки; по границам задачи не трогала.
- **V53 сверка tar.gz пакета с серверной суммой** — номера и целостность манифеста сошлись; побайтовая сверка архива с `content_pack_checksum` относится к шагу публикации.
- **V63 п.6 (полнота встроенного пакета в staging), V50 пост-проверка окон, V66 п.4 (живой барьер кабинета), V68 п.7–8 (живое обновление)** — все после сборки, по определению.
- **Ничего не собирала, не правила, не удаляла, не публиковала** — по границам задачи.
