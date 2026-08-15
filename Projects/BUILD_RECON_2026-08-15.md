# Разведка сборочной инфраструктуры Aurora AI (2026-08-15)

Только чтение. Деревья: `Aurora_Econometrica_thinwt`, `ROSST_AI_Legal`, `ROSST_AI_DocMaster`,
`Aurora_Creative_Hub`, `ROSST_AI_Media`, `Aurora_Oracle`, `Aurora_PR_Master`, `Aurora_Parser`,
`AI_APP_AGENCY` (все — `D:\Docs\Aurora_Ai\Dev\`) + отдельный репозиторий крейта `aurora-llm`.

---

## 1. Настройка Cargo у каждого продукта

Проверено: `.cargo/config.toml` в корне дерева, в `src-tauri/`, и глобальный `C:\Users\ackol\.cargo\config.toml` (а также `config` без расширения).

**Результат — нет ни одного файла ни на одном из уровней, ни у одного продукта, ни у aurora-llm, ни глобально у пользователя.** Ни зеркала реестра, ни `offline = true`, ни сетевых настроек, ни кэша — Cargo работает целиком на настройках по умолчанию (crates.io напрямую).

Локально установлено: `rustc 1.96.0 (ac68faa20 2026-05-25)`, `cargo 1.96.0 (30a34c682 2026-05-25)`.

## 2. vendor/

Проверено в корне и в `src-tauri/` каждого продукта. **Папки `vendor/` нет нигде.** Зависимости не завендорены — сборка тянет исходники непосредственно с crates.io при каждой чистой сборке (либо из локального кэша `~/.cargo/registry`, который в дереве продукта не лежит).

## 3. Офлайн-сборка

Поиск `offline`/`оффлайн`/`без сети` в `package.json`, `*.ps1`, `*.sh`, `Makefile` каждого продукта (и aurora-llm) — **ноль совпадений везде**. Флага `--offline` ни в одном сборочном скрипте нет. В `CLAUDE.md` продуктов слово «офлайн» встречается только в другом смысле — «локальная (0-egress) редакция» Econometrica про исходящий сетевой трафик к Anthropic/Cloud.ru, а не про офлайн-сборку Cargo.

## 4. Сборка в CI

`.github/workflows/` есть у 7 из 9 продуктов: `Aurora_Econometrica_thinwt`, `ROSST_AI_Legal`, `ROSST_AI_DocMaster`, `Aurora_Creative_Hub`, `ROSST_AI_Media`, `Aurora_Oracle`, `AI_APP_AGENCY` — у каждого по два файла: `ci.yml` и `keepalive.yml`. **У `Aurora_PR_Master` и `Aurora_Parser` папки `.github/workflows/` нет вовсе** (CI отсутствует как факт, не «отключён»).

Прочитан `ci.yml` дословно (`Aurora_Econometrica_thinwt`, идентичен по структуре во всех 7):
- Job `check` (windows-latest): `dtolnay/rust-toolchain@stable` (без пина версии) → `actions/cache@v4` кэширует `~/.cargo/registry`, `~/.cargo/git`, `target` по ключу `hashFiles('**/Cargo.lock')` → `npm ci` → линтеры промптов → `cargo test --manifest-path src-tauri/Cargo.toml` → `cargo clippy ... -D warnings`.
- Job `python-tests` (ubuntu-latest) и `help-sync` (ubuntu-latest) — не Rust.
- Job `release` (windows-latest, нужен tauri-cli, `cargo tauri build`, публикация в `Ackold26/rosst-updates` + Supabase) — **явно отключён:** `if: false`, с комментарием в коде:
  > «ОТКЛЮЧЁН (2026-07-18, санкция Антона): job собирает exe БЕЗ build_sidecar.py (python-бандл 970MB не собирается в CI) → артефакт с неполным sidecar, без смоук-гейта INV-96. Канонический релиз-канал — локальная сборка по регламенту aurora-release-update + публикация в Ackold26/aurora-releases.»

Вывод по CI продуктов: сборка тестов/clippy идёт онлайн с crates.io (кэш по Cargo.lock, не vendor), а **фактический релизный установщик через CI не собирается вообще** — только локально на машине разработчика.

**Живой статус запусков CI (прошли ли последние прогоны) не проверялся** — это требует `gh` CLI/сетевого запроса к GitHub API, вне рамок локальной файловой разведки, см. раздел «Не выяснено».

`aurora-llm` имеет отдельный, более развитый набор workflow (4 файла, не 2):
- `build.yml` — линт+тест (`cargo fmt --check`, `cargo clippy -D warnings`, `cargo build --workspace --all-targets`, `cargo test --workspace`, coverage через `cargo-llvm-cov`) на Linux всегда, на macOS/Windows — matrix только для PR/main/dispatch. Toolchain явно пинуется: `dtolnay/rust-toolchain@stable` с `toolchain: "1.94"`.
- `release.yml` — триггер по тегам `v*.*.*` / `v*.*.*-rc.*` или `workflow_dispatch`. Собирает `cargo build --release --workspace` на Linux/macOS/Windows, переименовывает бинарь `aurora-llm`/`aurora-llm.exe` с суффиксом платформы и публикует **draft** GitHub Release. Дословно из комментариев в файле: «Currently: builds cross-platform binaries, uploads as artifacts, creates a draft GitHub Release»; «TODO(W4.1): Add packaging (DEB/RPM, macOS zip, Windows zip), SHA256 sums, and signing here»; «Skeleton release — W4 packaging not yet complete». Бинарники сейчас **не подписаны и не упакованы**.
- `audit.yml` — ежедневный `cargo audit --deny warnings` (RustSec advisory database, требует сети к crates.io/RustSec).
- `network-policy.yml` — заглушка (`# TODO(W3.3): Real network policy integration test`), сейчас просто билд + опциональный тест с несуществующим ещё feature-флагом `network-policy-test` (`continue-on-error: true`).

## 5. Как подключены зависимости-исключения (не с crates.io)

Проверены дословно **все 9** `src-tauri/Cargo.toml` (grep по `git\s*=`, `path\s*=`, `registry\s*=` по всему файлу, не только рядом с `[dependencies]`).

**Результат: ни одной строки `git =`, `path =` или `registry =` ни в одном из 9 `src-tauri/Cargo.toml`. Прецедентов подключения крейта не с crates.io напрямую в src-tauri — ноль.**

Однако у 7 из 9 продуктов (`Aurora_Econometrica_thinwt`, `ROSST_AI_Legal`, `ROSST_AI_DocMaster`, `Aurora_Creative_Hub`, `ROSST_AI_Media`, `Aurora_Oracle`, `AI_APP_AGENCY`) есть **корневой `Cargo.toml`**, объявляющий Cargo-workspace:
```toml
[workspace]
members = [
  "src-tauri",
  "tools/license-generator",
  "tools/vault-packer",
  "tools/get-fingerprint",
]
resolver = "2"
```
(дословно у всех 7 совпадает; `Aurora_Parser` — workspace только из `["src-tauri"]`; `Aurora_PR_Master` — корневого `Cargo.toml` нет вообще, `src-tauri/Cargo.toml` сам по себе, вне workspace). Члены `tools/*` — самостоятельные бинарные крейты внутри того же репозитория (`path = "src/main.rs"` для `[[bin]]`, пустые/минимальные `[dependencies]`), они не подключены как зависимость к `src-tauri` через `path =` — это соседние по workspace, но не связанные графом зависимостей крейты. То есть path-зависимости в Aurora используются только для организации нескольких бинарников одного репозитория в один workspace, а не для переиспользования кода между репозиториями.

**Единственный реальный прецедент межрепозиторийного переиспользования кода (aurora-llm) устроен не через Cargo вообще**, см. §8.

## 6. Подмодули

`.gitmodules` — проверено у всех 9 продуктов и у `aurora-llm`. **Нет ни у одного.**

## 7. Версия Rust

`rust-version` — проверено по всему `src-tauri/Cargo.toml` (не только рядом с `[package]`) у всех 9 продуктов. **Ни один продукт не задаёт `rust-version`.** Требования не расходятся просто потому, что их нет — ни верхнего, ни нижнего порога сборка продуктов сегодня не фиксирует.

`aurora-llm/Cargo.toml` — единственный, где версия зафиксирована явно:
```toml
[workspace.package]
...
rust-version = "1.94"
```
и в CI `aurora-llm` (`build.yml`, `release.yml`, `network-policy.yml`) toolchain жёстко пинуется `"1.94"`. Локально установленный `rustc 1.96.0` выше этого порога — конфликта сегодня нет, но ограничение одностороннее: если общий крейт унаследует MSRV=1.94 от aurora-llm, а какой-то из 9 продуктов/CI-раннеров стоит на более старом toolchain (в CI продуктов версия не пинуется — берётся `stable` на момент прогона), несовместимость не будет видна до реальной попытки собрать.

## 8. Устройство aurora-llm как крейта-продукта

Отдельный репозиторий `github.com/Ackold26/aurora-llm` (подтверждено `git remote -v`). Cargo-workspace из трёх членов:

```toml
[workspace]
members = ["crates/llm-core", "crates/llm-cli", "crates/llm-test-utils"]
resolver = "2"
[workspace.package]
version = "0.9.0-rc.7"
edition = "2021"
rust-version = "1.94"
```

- `crates/llm-core` → пакет `aurora-llm-core`, библиотека (протокольные типы, `LlmProvider`, адаптеры, retry, аудит, credentials). `publish` не задан (по умолчанию публикуем).
- `crates/llm-cli` → пакет `aurora-llm`, бинарь `[[bin]] name = "aurora-llm"`, зависит от `llm-core` через `path = "../llm-core"` (внутриworkspace).
- `crates/llm-test-utils` → `publish = false`, dev-only, тоже зависит от `llm-core` через `path =`.

Ни в одном из трёх `Cargo.toml`, ни в корневом — **нет шага `cargo publish` ни в одном workflow**. На crates.io ничего не публикуется.

**Версионирование — git-теги**, дословно: `v0.9.0-rc.1` … `v0.9.0-rc.7` (7 тегов, семантика `vMAJOR.MINOR.PATCH[-rc.N]`), триггерят `release.yml`.

**Доставка потребителям сегодня — НЕ через Cargo.** `release.yml` собирает `cargo build --release --workspace` на трёх платформах и заливает готовый бинарь `aurora-llm`/`aurora-llm.exe` как asset **draft**-релиза на GitHub (без подписи, без пакетирования — см. TODO в §4). Единственная найденная точка интеграции с продуктами — `ROSST_AI_DocMaster/src-tauri/src/commands/bridge.rs`:
```rust
//! Жизненный цикл локального шлюза aurora-llm (ADR-026 срез 2A + HIGH-2 lifecycle).
...
/// Путь к бинарю aurora-llm: env `AURORA_LLM_BIN` → (прод: bundled — TODO упаковки).
fn resolve_gateway_bin() -> Option<PathBuf> { ... }
...
async fn spawn_gateway(...) -> Result<()> {
    let bin = resolve_gateway_bin().context(
        "бинарь aurora-llm не найден — задайте AURORA_LLM_BIN (в проде поставляется в комплекте)",
    )?;
    ...
    cmd.spawn().context("спавн aurora-llm serve")?;
```
Продукт спавнит `aurora-llm serve --transport http` как отдельный процесс и общается с ним по HTTP (`AURORA_LLM_AUTH_TOKEN` в env, `/health`, `POST /shutdown`). Это **процесс-сайдкар**, не Cargo-зависимость: `aurora-llm-core`/`aurora-llm-cli` не встречаются как `git =`/`path =` ни в одном `Cargo.toml` продукта (см. §5). Путь к бинарю в dev берётся из переменной окружения; путь для прод-сборки помечен в самом коде как `TODO упаковки` — то есть даже этот, единственный, канал доставки не завершён. Из 9 продуктов только `ROSST_AI_DocMaster` вообще ссылается на `aurora-llm`/`aurora_llm` в исходниках Rust — у остальных восьми (включая `Aurora_Econometrica_thinwt`, где формально должен быть тот же MMM-пайплайн) такой интеграции в коде не найдено.

Ни один из 9 продуктов не объявляет `externalBin` в `src-tauri/tauri.conf.json` (проверено у всех 9 — совпадений нет), то есть штатный Tauri-механизм sidecar-бандлинга (`bundle.externalBin`) для aurora-llm тоже не задействован — интеграция целиком на ручном спавне процесса.

---

## Ключевая находка вне восьми пунктов: как код сегодня фактически расходится между репозиториями

Это не было прямым вопросом, но обнаружилось по ходу и напрямую относится к вопросу «как доставлять» — потому что это уже работающий, хотя и не Cargo-based, канал.

`CLAUDE.md` в корне пяти продуктов почти дословно совпадает, а сам текст описывает механизм:

> «Продукты (один код, разные конфиги) ... Варианты отличаются ТОЛЬКО: `tauri.conf.json` (productName, identifier), `Cargo.toml` (name), `main.rs` (lib name).»
> «6. Синхронизация 4 репо — ОБЯЗАТЕЛЬНО clean build. При копировании исходников в Aurora-варианты — удалять `build/`, `.svelte-kit/`, `node_modules/.vite/` перед rebuild.»
> «17. Git-теги — обязательно при каждом значимом изменении ... Формат: `v{версия}-{краткое-описание}`. Хранить минимум 5 последних тегов для возможности отката.»

Проверено по хешу файла: `ROSST_AI_Legal/CLAUDE.md` и `AI_APP_AGENCY/CLAUDE.md` — **побайтово идентичны** (md5 `09c2647fd70063118354b4dabbaa6925`). `Aurora_Econometrica_thinwt`, `Aurora_Creative_Hub`, `ROSST_AI_Media` — та же структура текста, но с собственными добавлениями (разные md5). Первые 15 строк у `ROSST_AI_DocMaster` и `Aurora_PR_Master` совпадают с этим же шаблоном дословно.

То есть сегодня общий код между этими продуктами (не только 9429 строк из замера дублирования, а вся GUI-оболочка вокруг) **расходится копированием исходников между независимыми репозиториями вручную**, с git-тегами как точкой отката, а не каким-либо Cargo-механизмом.

Ровно наоборот у двух продуктов — `Aurora_Oracle` и `Aurora_Parser` — это зафиксировано явным текстом в их собственных `CLAUDE.md`:
- `Aurora_Oracle`: «Отдельная кодовая база (fork из Analytics Hub). **НЕ входит в sync вариантов.**»
- `Aurora_Parser`: отдельная архитектура (Dashboard вместо кабинетов, свой Python sidecar на FastAPI, SQLite, был утерян и частично восстановлен 2026-04-13) — не имеет отношения к семейству копируемого кода вовсе.

---

## Таблица: продукт × сборочная инфраструктура

| Продукт | Репозиторий (origin) | Свой `.cargo/config` | `vendor/` | CI (`ci.yml`+`keepalive.yml`) | Нестандартные зависимости в `src-tauri/Cargo.toml` | `rust-version` | Root workspace | Cargo.lock закоммичен |
|---|---|---|---|---|---|---|---|---|
| Aurora_Econometrica_thinwt | `Ackold26/Aurora_Econometrica` | нет | нет | есть | нет | не задан | да (src-tauri + 3×tools) | да (root) |
| ROSST_AI_Legal | `Ackold26/ROSST_AI_Legal` | нет | нет | есть | нет | не задан | да (src-tauri + 3×tools) | да (root) |
| ROSST_AI_DocMaster | `Ackold26/ROSST_AI_DocMaster` | нет | нет | есть | нет | не задан | да (src-tauri + 3×tools) | да (root) |
| Aurora_Creative_Hub | `Ackold26/Aurora_Creative_Hub` | нет | нет | есть | нет | не задан | да (src-tauri + 3×tools) | да (root) |
| ROSST_AI_Media | `Ackold26/ROSST_AI_Media` | нет | нет | есть | нет | не задан | да (src-tauri + 3×tools) | да (root) |
| Aurora_Oracle | `Ackold26/Aurora_Oracle` | нет | нет | есть | нет | не задан | да (src-tauri + 3×tools) | да (root) |
| Aurora_PR_Master | `Ackold26/Aurora_PR_Master` | нет | нет | **нет** | нет | не задан | **нет** | да (src-tauri, не root) |
| Aurora_Parser | `Ackold26/Aurora_Parser` | нет | нет | **нет** | нет | не задан | да (только src-tauri) | да (root) |
| AI_APP_AGENCY | `Ackold26/AI_APP_AGENCY` | нет | нет | есть | нет | не задан | да (src-tauri + 3×tools) | да (root) |
| **aurora-llm** (крейт) | `Ackold26/aurora-llm` | нет | нет | есть (4 файла: build/release/audit/network-policy) | — (сам крейт, не потребитель) | **1.94** (workspace) | да (3 крейта) | не проверялось отдельно |

Примечание: `ROSST_AI_Media` дополнительно содержит осиротевшую папку `.claude/worktrees/agent-ab38a14708c6927f0/` — параллельную рабочую копию с собственным `Cargo.toml`/`src-tauri/Cargo.toml` (похоже, недоубранный агентский worktree). Не учтена в таблице, отмечена как шум.

---

## Чего выяснить не удалось и почему

1. **Живой статус CI-прогонов** (проходят ли `ci.yml` сейчас, зелёные ли последние билды) — не проверялось. Требует `gh api`/сетевого запроса к GitHub, что выходит за рамки «только чтение локальной файловой системы», прямо не разрешено в задании (задание просит смотреть на файлы workflow, не на историю запусков).
2. **Фактическое содержимое `~/.cargo/registry`/`~/.cargo/git` кэша** (какие крейты реально скачаны, стоит ли там что-то нестандартное вроде уже засунутого вручную пути) — не проверялось; задание просило конфигурацию Cargo, а не содержимое кэша, и залезать в системный кэш без явного запроса посчитала избыточным для «только чтение».
3. **`keepalive.yml`** — файл найден у 7 продуктов и его наличие зафиксировано, но содержимое не прочитано (по названию — вероятно, cron-пинг против засыпания GitHub Actions на бесплатном тарифе; не относится к вопросу доставки крейта, поэтому не тратила на это чтение).
4. **Есть ли где-то ещё, вне этих 9+1 деревьев на диске, репозиторий для варианта «Aurora AI Creative»** (`com.rosst.creative`, упомянут в таблице продуктов внутри `CLAUDE.md`, но такого каталога в `D:\Docs\Aurora_Ai\Dev\` нет) — не искала за пределами перечисленных в задании деревьев, это было прямо вне периметра.
5. **`Aurora_Econometrica_thinwt`** — сама папка называется `_thinwt`, что похоже на git worktree с суффиксом (по аналогии с `_wt_*` в дереве `Dev/`), но при этом имеет собственный `.git/` с origin `Aurora_Econometrica.git` и это единственная папка с таким именем (нет отдельной `Aurora_Econometrica` рядом в списке — есть `Aurora_Econometrica_archive_2026-05-09`, `Aurora_Econometrica_avrora`, `Aurora_Econometrica_canon`, `Aurora_Econometrica_Trade_and_Pricing`, `Aurora_Econometrica_v230`). Не выясняла, какая из них канонический ствол, а какая — ветка/архив; для задачи разведки сборочной инфраструктуры это не влияло на факты (Cargo-конфигурация в `_thinwt` проверена как есть), но для решения о размещении общего крейта отношения между этими каталогами может иметь значение — ведущему стоит уточнить отдельно, если понадобится.

## Что из найденного ограничивает выбор способа доставки

- **Нет ни одного прецедента `git =`/`path =`/`registry =` зависимости ни в одном из 9 `src-tauri/Cargo.toml`.** Любой выбор в пользу Cargo-git-зависимости или отдельного внутреннего registry будет первым в своём роде для этой линейки продуктов — не имеет existing pattern, на который можно опереться при отладке проблем интеграции.
- **Единственный существующий канал переиспользования кода между независимыми репозиториями (aurora-llm) устроен как отдельно скомпилированный бинарь-сайдкар, доставляемый через draft GitHub Release, а не как Cargo-зависимость** — и даже этот канал сегодня подключён только у одного продукта из девяти (`ROSST_AI_DocMaster`), путём ручного `Command::spawn()` по пути из переменной окружения, а не через официальный Tauri `externalBin`. Прод-упаковка этого бинаря в установщик прямо помечена в коде как незавершённая (`TODO упаковки`).
- **Второй существующий канал — прямое копирование исходников между 5+ репозиториями («синхронизация N репо»)**, зафиксированное текстом в `CLAUDE.md` этих продуктов как обязательная процедура с git-тегами для отката. Это ближе к «vendored copy», чем к «монорепо» или «git-зависимость», и уже привычно команде как рабочий процесс.
- **Ни у одного продукта нет `.cargo/config.toml`, `vendor/`, офлайн-флагов.** Сборка сегодня полностью зависит от прямого доступа к crates.io в момент `cargo build`/`cargo test`; какой бы способ доставки крейта ни был выбран, он ляжет на инфраструктуру, которая уже не изолирована от сети.
- **`rust-version` не зафиксирован ни в одном из 9 продуктов, но зафиксирован (1.94) у `aurora-llm`.** Формального конфликта версий сегодня нет (локальный `rustc` 1.96 выше порога), но и явной защиты от расхождения нет ни у одного продукта — если общий крейт унаследует MSRV от aurora-llm, а сборочный раннер/машина какого-то продукта окажется на более старой версии, это всплывёт только в момент сборки, не раньше.
- **CI собирает `cargo test`/`cargo clippy` онлайн с crates.io** (кэш `actions/cache` по хешу `Cargo.lock`, не vendor) у 7 из 9 продуктов; у `Aurora_PR_Master` и `Aurora_Parser` CI нет вовсе — значит любой способ доставки, полагающийся на CI-проверку синхронности крейта (например, git-тег + workflow-проверка версии), для этих двух продуктов не сработает без добавления CI с нуля.
- **Релизная сборка установщика в CI продуктов отключена (`if: false`)** — канонический релизный процесс целиком локальный (машина разработчика, по регламенту `aurora-release-update`). Значит доставка крейта тоже должна работать в локальной сборке разработчика, а не полагаться на облачный CI как на источник правды для финального артефакта.
- **9 отдельных git-репозиториев, каждый с собственным закоммиченным `Cargo.lock`** (кроме `Aurora_PR_Master`, где `Cargo.lock` лежит не в корне, а в `src-tauri/`, потому что там нет root workspace) — то есть версии зависимостей уже пинуются независимо по каждому репозиторию; общий крейт добавит десятую точку версионирования, которую тоже нужно будет держать синхронно с этими девятью.
