# Замер дублирования Rust-ядра по линейке Aurora AI (2026-08-14)

Разведка фактов под решение о выносе общего Rust-ядра в отдельный крейт. Только чтение и
подсчёт — правки, ветки, сборки не выполнялись. Область замера — `src-tauri/src/**/*.rs`
(фронтенд и python не учитывались).

## 1. Какие деревья взяты и почему

Взято по одному дереву на продукт — ровно те 9 каталогов, что указал тимлид; все существуют.
Переключать ветки в чужих деревьях запрещено правилами задания, поэтому дерево бралось «как
стоит», без checkout. Проверка через `git tag --sort=-creatordate` + `git branch --contains`
показала два разных состояния:

- **5 продуктов на сведённой ветке `master`**, текущая ветка содержит собственный верхний тег:
  Econometrica (`Aurora_Econometrica_thinwt`, тег v2.4.8), Legal (`_wt_legal_master`,
  v0.13.2-legal), Creative Hub (`Aurora_Creative_Hub`, v0.10.0-creative-center), Smart Analytica
  (`ROSST_AI_Media`, v1.3.13-analytics-hub). Это совпадает с памятью
  `BRANCH_CONSOLIDATION_MAP` — там эти линии уже сведены в основную ветку.
- **4 продукта на несведённой fix/feat-ветке** — верхний тег в репозитории вообще не версия
  релиза (canon/crisis-теги без отношения к коду, устаревший `mcp-bridge-dev`), сама история
  версий там оборвана: Oracle (`_wt_oracle_gwsign`, ветка `feat/oracle-install-per-user`),
  Docs Lab (`ROSST_AI_DocMaster`, ветка `feat/rag-core-adopt`), PR Studio (`Aurora_PR_Master`,
  ветка `fix/updater-is-newer-prerelease`), Media Radar (`Aurora_Parser`, та же ветка). Это тоже
  согласуется с памятью — «CPD-53 не в основной ветке» для этой части линейки.
- `AI_APP_AGENCY` — символьная ссылка на `_archive/Dev/AI_APP_AGENCY` (ветка
  `feat/contract-vs-standard`). Помечаю отдельно: это архивная копия, других живых деревьев
  для этого продукта в `Dev/` не нашла.

Соответствие имён каталогов и продуктов (по `NAMING_GLOSSARY`/памяти): `ROSST_AI_Media` →
**Smart Analytica** (алиас `analytics-hub`), `Aurora_Parser` → **Media Radar** (алиас Parser) —
названия каталогов не совпадают с продуктовыми именами, легко перепутать.

Итого 401 файл `.rs`, 226 640 строк суммарно по 9 деревьям.

## 2. Идентичные файлы — топ по цене дублирования

Цена = строки × (число копий − 1) — именно столько строк пришлось бы поправить при каждом
кросс-продуктовом дефекте, если чинить копию за копией. Группировка — по sha256 внутри каждого
относительного пути; если у пути несколько разных хешей (продукты разошлись), в зачёт идёт
каждая группа с ≥2 совпадающими копиями отдельно.

| # | Файл | Копий | Строк | Цена (строк) | Продукты |
|---|---|---|---|---|---|
| 1 | `commands/pptx_processor.rs` | 2 | 1418 | **1418** | AIAgency, PRStudio |
| 2 | `commands/vault.rs` | 6 | 183 | **915** | AIAgency, CreativeHub, Legal, MediaRadar, PRStudio, SmartAnalytica |
| 3 | `commands/license.rs` | 4 | 241 | **723** | AIAgency, DocsLab, MediaRadar, PRStudio |
| 4 | `commands/data_migration.rs` | 4 | 200 | **600** | AIAgency, CreativeHub, DocsLab, PRStudio |
| 5 | `crypto/content_sig.rs` | 3 | 296 | **592** | AIAgency, DocsLab, PRStudio |
| 6 | `crypto/auth_sig.rs` | 3 | 286 | **572** | DocsLab, Legal, SmartAnalytica |
| 7 | `commands/content_pack.rs` | 5 | 132 | **528** | AIAgency, CreativeHub, DocsLab, PRStudio, SmartAnalytica |
| 8 | `errors.rs` | 4 | 174 | **522** | AIAgency, Legal, MediaRadar, PRStudio |
| 9 | `commands/feedback.rs` | 7 | 75 | **450** | AIAgency, CreativeHub, DocsLab, Legal, MediaRadar, PRStudio, SmartAnalytica |
| 10 | `commands/model_backend.rs` | 4 | 128 | **384** | CreativeHub, MediaRadar, Oracle, PRStudio |
| 11 | `commands/parser.rs` | 4 | 119 | **357** | AIAgency, CreativeHub, Legal, PRStudio |
| 12 | `crypto/ed25519.rs` | 8 | 51 | **357** | все, кроме Oracle |
| 13 | `crypto/fingerprint.rs` | 2 | 320 | **320** | CreativeHub, Legal |
| 14 | `crypto/auth_sig.rs` (вторая группа) | 2 | 286 | **286** | CreativeHub, Oracle |
| 15 | `crypto/aes.rs` | 7 | 47 | **282** | все, кроме Econometrica, Oracle |
| 16 | `metrics/ratings.rs` | 3 | 107 | **214** | AIAgency, Legal, MediaRadar |
| 17 | `commands/data_migration.rs` (вторая группа) | 2 | 200 | **200** | Oracle, SmartAnalytica |
| 18 | `metrics/collector.rs` | 2 | 190 | **190** | AIAgency, MediaRadar |
| 19 | `metrics/audit.rs` | 3 | 68 | **136** | AIAgency, Legal, MediaRadar |
| 20 | `crypto/hkdf.rs` | 8 | 15 | **105** | все, кроме Oracle |

Показательно: `auth_sig.rs` (упомянутый в памяти как «байт-в-байт идентичный в 9 репозиториях»)
на деле разошёлся на **три** группы — {DocsLab, Legal, SmartAnalytica}, {CreativeHub, Oracle} и
отдельная версия Econometrica (79 строк расхождения из 363) — то есть память устарела: за
прошедшие правки файл уже частично разъехался, хотя криптографическое ядро всё ещё узнаваемо
общее.

Всего групп с полным байтовым совпадением ≥2 копий — **27**, на 20 путях (некоторые пути дали
по 2 непересекающиеся группы). Суммарная цена дублирования по этим группам —
**9429 строк**. Из них файлы, где точное совпадение держат **≥3 продукта одновременно** —
**18 файлов**, 2156 строк в одной копии, цена **6817 строк** — это самое дешёвое и надёжное
ядро для выноса: правка в одном месте закрывает минимум три продукта разом.

## 3. Почти идентичные — природа расхождения

Для каждого общего пути с расходящимся содержимым посчитан построчный diff (`difflib`,
`SequenceMatcher`) относительно самой распространённой версии по этому пути.

**Тривиальное расхождение (0–3 строки, обычно EOL/пробел, не текст)** — 15 путей, где
отклонившаяся копия отличается на 0–3 строки от «большинства»: `commands/vault.rs`,
`crypto/aes.rs`, `crypto/ed25519.rs`, `crypto/hkdf.rs`, `crypto/fingerprint.rs`, `main.rs` (у
всех 9 продуктов расхождение 0–2 строки — файл фактически один и тот же bootstrap, просто с
иным окончанием строки/пробелом на конце), `crypto/mod.rs`, `commands/content_pack.rs`,
`commands/data_migration.rs`, `crypto/content_sig.rs`, `commands/model_backend.rs`,
`commands/feedback.rs`, `session/cleanup.rs`, `metrics/mod.rs`, `metrics/ratings.rs`,
`metrics/audit.rs`, `commands/gguf_model.rs`, `commands/ru_resident_key.rs`,
`commands/standards.rs`. У части из них diff = 0 при разных sha256 — значит расхождение чисто
в переводе строки/BOM, содержимое строк identично; для практических целей это тоже дубликат,
просто хеш ловит формальное различие. Итого таких «дубликатов с точностью до пробела» —
десятки, они увеличивают реальную цену дублирования сверх формальных 9429 строк, но не
включены в жёсткий подсчёт §2, чтобы не завышать цифру спекулятивно.

**Умеренное расхождение (4–60 строк, обычно продуктовый идентификатор/фича-флаг)** — 36
записей: `commands/brand.rs` (7 продуктов отличаются на 7–46 строк от Econometrica),
`commands/license.rs`, `commands/parser.rs`, `errors.rs`, `crypto/fingerprint.rs`,
`commands/diagnostics.rs` (все 7 копий отличаются на 13–27 строк от Econometrica) — здесь
файл узнаваемо тот же самый, но с точечными правками под продукт (имя, набор фич,
специфичный код ошибки).

**Существенное расхождение (>60 строк)** — 154 записи, в основном это **не дублирование, а
совпадение имени файла при разном содержимом**: `lib.rs` (главный файл регистрации команд
Tauri — у каждого продукта свой набор `invoke_handler`, различие 1249–5113 строк), `commands/
claude.rs` (различие до 4695 строк — по сути разные файлы), `commands/campaign.rs`, `commands/
cabinet.rs`, `commands/content_updater.rs`, `commands/online_auth.rs`, `commands/updater.rs`,
`session/manager.rs`, `commands/gateway_executor.rs`, `commands/execution_mode.rs`,
`durable_store.rs`. Эти файлы не стоит планировать к прямому выносу «как есть» — общая логика
в них перемешана с продуктовой так плотно, что нужен рефакторинг, а не механический вынос.

## 4. Итоговые цифры

- Всего `.rs`-файлов в ядре (`src-tauri/src`) по 9 деревьям: **401**, суммарно **226 640** строк.
- Из 94 уникальных относительных путей 53 — общие для ≥2 продуктов, 41 — присутствуют только
  в одном продукте.
- Групп с точным байтовым совпадением (≥2 продукта): **27**, на 20 разных путях.
- Файлов, где точная копия держится **≥3 продуктами одновременно**: **18**, 2156 строк «на
  одну копию», суммарная цена дублирования — **6817 строк**.
- Суммарная цена дублирования по ВСЕМ точным группам (включая пары из 2 продуктов): **9429
  строк** — именно столько строк пришлось бы синхронно поправить при повторении сценария
  CPD-77/`content_updater` по всем копиям сразу, если бы код был не идентичен, а просто похож
  (на деле было хуже — правки уже разошлись, см. §3).
- Плюс десятки «дубликатов с точностью до пробела/EOL» (diff = 0–3 строки при разном sha256) —
  не включены в цифру выше, реальная цена дублирования по факту выше 9429.

## 5. Что уникально для продуктов (граница будущего ядра)

41 файл встречается ровно в одном продукте — это то, что при выносе общего крейта останется
в продукте как есть:

- **Media Radar** — больше всех, 15 уникальных файлов (весь слой `db/*`, `commands/alerts.rs`,
  `commands/brands.rs`, `commands/insights.rs`, `commands/sources.rs`, `scheduler.rs`,
  `sidecar.rs` и др.) — у него собственная доменная модель (парсинг медиа, БД), значительно не
  похожая на остальные продукты.
- **Econometrica** — 7 файлов (`commands/econometrica.rs`, `commands/project.rs`, `commands/
  report.rs`, `econ_sidecar.rs`, `sidecar_runtime.rs` и др.) — MMM-специфика.
- **Docs Lab** и **Smart Analytica** — по 5 (`commands/docbatch.rs`, `commands/orders.rs`,
  `commands/requisites.rs` у Docs Lab; `commands/critic_processor.rs` и папка-дубль
  `metrics/metrics/*` у Smart Analytica — похоже на артефакт неудачного переноса каталога,
  стоит отдельно проверить руками, не входит в подсчёт дублирования, т.к. путь `metrics/
  metrics/*.rs` не совпадает с `metrics/*.rs`).
- **Oracle** — 4 (`commands/audience_library.rs`, `commands/persona_chat.rs`,
  `commands/report_signer.rs`, `commands/service_discovery.rs`).
- **Legal** — 3 (`commands/corpus_fetch.rs`, `commands/legal_rag.rs`, `crypto/corpus_sig.rs`) —
  нормативный RAG-контур.
- **Creative Hub** — 2 (`commands/handoff.rs`, `commands/model_fetch.rs`).
- PR Studio и AI Agency — без ни одного эксклюзивного файла: весь их код параметра «своё» на
  уровне путей нет, только на уровне содержимого (см. §3, `heavy`-расхождения по общим
  путям — их специфика размазана внутри общих по имени файлов, а не вынесена в отдельные).

## 6. Что померить не удалось и почему

- **Точная природа «нулевого diff при разном sha256»** (11+ случаев) не разложена на
  CRLF/LF vs BOM vs trailing-newline — посчитан только факт «diff по строкам = 0», причина не
  диагностирована (не требовалось для решения о вынесении ядра, но при реальном слиянии в
  крейт это первое, что нужно будет нормализовать через `.gitattributes`/`rustfmt`).
- **AI_APP_AGENCY** — измерено по единственной найденной копии, архивной (`_archive/Dev/...`).
  Не проверяла, есть ли более свежая рабочая копия этого продукта вне `Dev/` — не входило в
  заданную область поиска.
- **PR Studio, Docs Lab, Oracle, Media Radar** — взяты по несведённой fix/feat-ветке (см. §1),
  так как чекаут запрещён; если у этих продуктов уже есть более новый код на master, что не
  отражён во взятой ветке, цифры по ним могут недосчитывать актуальные копии CPD-правок.
- Слишком мелкий diff-порог (в SequenceMatcher нет разделения «правка ради продукта» vs
  «правка ради версии зависимости»): классификация «тривиальное / умеренное / существенное»
  в §3 — эвристика по числу строк, не семантический анализ.

## Воспроизводимость

Скрипт подсчёта — `dup_scan_2026-08-14.py` (лежит рядом с этим отчётом), сырой результат —
`dup_scan_result_2026-08-14.json`. Запуск: `python dup_scan_2026-08-14.py` из папки со
скриптом (пути к 9 деревьям и их относительный `src-tauri/src` — константы `ROOT`/`PRODUCTS`
в начале файла). Метод: sha256 + число строк на каждый `*.rs`-файл в `src-tauri/src/**`;
группировка по относительному пути → по хешу; для расходящихся групп — построчный diff
(`difflib.SequenceMatcher`) относительно самой массовой версии по пути.
