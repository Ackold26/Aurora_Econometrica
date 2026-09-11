# Инвентаризация маршрута и egress — Aurora Econometrica thinwt

Только чтение. Каждое утверждение — с `файл:строка`. Дата инвентаризации: 10.09.2026.

---

## РАЗДЕЛ А. Механизм выбора маршрута

### А.1. Типы режимов (перечисления/константы)

Файл `src-tauri/src/commands/execution_mode.rs`:

- `pub enum ExecutionMode { Local, Cloud }` — `execution_mode.rs:45-50`. `as_str()`: `"local"`/`"cloud"` (`execution_mode.rs:53-58`); `parse()` обратно (`execution_mode.rs:60-66`); `human()` — текст для человека: `Local` → `"ваш Claude Code"`, `Cloud` → `"шлюз Авроры"` (`execution_mode.rs:71-76`).
- `pub enum ModeSource { Explicit, Auto }` — `execution_mode.rs:82-87` (откуда взялось решение).
- `pub struct ModeDecision { mode, source, explanation }` — `execution_mode.rs:102-106`.
- `pub struct ModeState { mode, source, explanation, explicit: Option<ExecutionMode>, cloud_built_in: bool, local_available: bool, cloud_refusal: String }` — `execution_mode.rs:110-124` (то, что уходит в интерфейс).

🔴 Обнаружена ВТОРАЯ, независимая ось выбора — `local_only: bool` в `UserConfig` (`user_config.rs:28-32`), отвечающая «обращаться ли к облачному ИИ вообще» (egress-гейт `ensure_not_local_only`, см. раздел В), в отличие от `execution_mode`, отвечающего «если обращаемся — чей Claude Code исполняет работу» (`user_config.rs:37-40` — комментарий в коде явно предупреждает не путать эти две оси).

Также обнаружена ТРЕТЬЯ смежная вещь — `cloud_consent: Option<CloudConsent>` (согласие на облачную обработку, юридически значимое, версионируется `CLOUD_CONSENT_TERMS_VERSION`) — `user_config.rs:24-27, 49-61, 74-78`. Требуется только если редакция облачная (`CLOUD_ADVISORS_ENABLED`, см. раздел Б.3).

### А.2. `resolve()` и правило приоритета `decide_with_history()`

`resolve(app_handle) -> ModeDecision` — `execution_mode.rs:381-395`:
1. Читает явный выбор человека `explicit_choice(app_handle)` (`execution_mode.rs:382`).
2. Если явный выбор ЕСТЬ — зонд локального Claude Code НЕ запускается (`local_ok = false`, `execution_mode.rs:385-386` — комментарий: «явный выбор сильнее любой доступности»).
3. Если явного выбора НЕТ — вызывается `local_available().await` (зонд, см. А.3) (`execution_mode.rs:388`).
4. Зовёт чистую функцию `decide_with_history(explicit, cloud_built_in(), local_ok, &why_not, local_engaged())` (`execution_mode.rs:390`).
5. Если итог — `Local`, отмечает `mark_local_engaged()` (`execution_mode.rs:391-393`).

`decide_with_history(explicit, cloud_built_in, local_ok, why_not, local_engaged) -> ModeDecision` — `execution_mode.rs:421-499`, порядок правил сверху вниз (строго последовательный, без дополнительного ветвления вызывающим кодом):
1. **Явный выбор человека (`execution_mode.rs:428-446`).** Если выбран `Cloud`, но в бинаре нет `cloud_built_in` — принудительно `Local` с объяснением «Облачный режим не входит в эту сборку» (`execution_mode.rs:432-440`). Иначе — берётся explicit как есть, источник `Explicit`.
2. **Локальный доступен и выбора нет (`execution_mode.rs:448-460`).** `local_ok == true` → `Local`, источник `Auto`, текст «материалы не проходят через серверы Платформы Аврора».
3. **Локальный уже был задействован в этом запуске программы (`execution_mode.rs:462-478`).** Если `local_engaged == true` (независимо от текущей доступности) → остаётся `Local`, источник `Auto`; в облако автоопределение НЕ переходит никогда (комментарий у `execution_mode.rs:27-34` и `461-466`: «асимметрия отказа» — находка внешнего аудита Critical).
4. **Ничего из выше и облачный путь есть в сборке (`execution_mode.rs:480-489`).** → `Cloud`, источник `Auto`.
5. **Иначе (`execution_mode.rs:491-498`).** → `Local`, источник `Auto`, текст «Облачного режима в этой сборке нет» (случай: локальный недоступен, `cloud_built_in=false`, явного выбора нет, локально ещё не работали).

Итог приоритета: **явный выбор → (если локально уже работали в этом запуске — остаться локально) → рабочий локальный → облако (если есть в сборке) → локальный с отказом**.

### А.3. Автоопределение (поиск установленного Claude Code на машине)

Код зонда — `execution_mode.rs:203-297`:
- `local_available()` (`execution_mode.rs:213-220`) — публичная точка входа, использует кэш `LOCAL_PROBE` (TTL `PROBE_TTL = 120s`, `execution_mode.rs:140,153,188-201`); при промахе кэша зовёт `probe_local()`.
- `probe_local()` (`execution_mode.rs:252-297`) — резолвит бинарь через `crate::commands::claude::find_claude_binary_detailed()` (`execution_mode.rs:255`, реализация — см. раздел Б.1, `claude.rs`); при `ResolveFailure::Untrusted(path)` возвращает `(false, "Claude Code установлен вне доверенных расположений")` (`execution_mode.rs:257-263`); при прочей ошибке — `(false, "Claude Code на этой машине не найден")` (`execution_mode.rs:264-267`).
- Дальше запускает `probe_command(&binary)` с аргументом `--version` (`execution_mode.rs:270`, сборка команды — `execution_mode.rs:236-250`): на Windows — через `cmd /C` со строкой, построенной ОБЩИМ построителем `crate::commands::claude::windows_cmd_command_line` (`execution_mode.rs:241`, тот же построитель что у боевого запуска в `claude.rs`); таймаут ответа `PROBE_TIMEOUT = 6s` (`execution_mode.rs:144,277`).
- Успех/провал классифицируется на 4 исхода — `execution_mode.rs:278-296` (успешный код возврата → `(true, "")`; ненулевой код → «найден, но не запускается»; ошибка запуска → то же; таймаут → «не отвечает»).
- Никаких путей/переменных среды сам `execution_mode.rs` не перечисляет — конкретные пути поиска бинаря находятся в `find_claude_binary_detailed()` в `claude.rs` (см. раздел Б.1; не вошло в текущий срез по границам задания, но упомянуто явно как источник).

Асимметрия отказа (жёстко закодировано): `mark_local_failed(reason)` (`execution_mode.rs:304-306`) гасит ЛОКАЛЬНЫЙ выбор автоопределения, но не переводит в облако — переход возможен только через `decide_with_history` по правилу 4 выше, и только если `local_engaged == false`.

### А.4. Где хранится состояние выбора

Файл настроек — `user_config.json` в `app_config_dir()` (per-app каталог, определяется идентификатором сборки) — `user_config.rs:88-90` (`config_path`), чтение/запись — `user_config.rs:92-100+` (`load`/`save`, сигнатуры видны, полный код save не листался — не требовалось заданием).

- Ключ `execution_mode: Option<String>` в `UserConfig` (`user_config.rs:46`) — значения `"local"` / `"cloud"` / отсутствует (по умолчанию `None` = автоопределение, `user_config.rs:33-35`).
- Читает: `explicit_choice(app_handle)` — `execution_mode.rs:341-348` (загружает config, парсит `execution_mode.as_deref().and_then(ExecutionMode::parse)`).
- Пишет: `set_explicit_choice(app_handle, mode)` — `execution_mode.rs:351-373`: сохраняет `mode.map(|m| m.as_str().to_string())` в конфиг (`execution_mode.rs:361-362`); если выбран `Cloud` — снимает память о локальной вовлечённости `forget_local_engagement()` (`execution_mode.rs:365-367`, комментарий: «только явный выбор облака — согласие человека расширить круг видящих»).
- Отдельно, в памяти процесса (НЕ в файле): `LOCAL_ENGAGED: AtomicBool` (`execution_mode.rs:171`) — «шла ли работа этого запуска локальным путём хоть раз»; `LOCAL_PROBE: Mutex<Option<LocalProbe>>` (`execution_mode.rs:153`) — кэш зонда; `CLOUD_REFUSAL: Mutex<String>` (`execution_mode.rs:157`) — причина отказа шлюза по праву.

### А.5. Полный список мест, ветвящихся по режиму (`match`/`if` по типу маршрута)

**Backend (`src-tauri/src/`):**
| файл:строка | что делает |
|---|---|
| `commands/claude.rs:194` | `resolve(&app_handle).await` — решение о маршруте перед прогоном (ветка `run_claude`, см. Б.1) |
| `commands/claude.rs:202` | `if decision.mode == ExecutionMode::Cloud` — переключение на путь шлюза |
| `commands/claude.rs:230-231` | `mark_local_failed` + `local_failure_text` при провале локального прогона |
| `commands/claude.rs:256` | `resolve(&app_handle).await` — второе место (вероятно `run_claude_pipeline` или аналог) |
| `commands/claude.rs:264` | `if decision.mode == ExecutionMode::Cloud` — второе место |
| `lib.rs:2530-2535` | tauri-команда `get_execution_mode` — отдаёт `ModeState` фронтенду |
| `lib.rs:2538-2549` | tauri-команда `set_execution_mode` — парсит строку, зовёт `set_explicit_choice` |
| `lib.rs:2553-2559` | tauri-команда `probe_local_claude` — сбрасывает кэш зонда, перечитывает состояние |
| `lib.rs:2511-2520` | tauri-команда `set_local_only` — ДРУГАЯ ось (см. А.1), пишет `local_only` в конфиг |
| `lib.rs:2479` | `"local_only": user_config::local_only_enabled(&config_dir)` — отдаётся в статус (см. `+layout.svelte`) |
| `commands/claude.rs:153-165` (диапазон, см. Б.3/В) | `ensure_not_local_only` — гейт по оси `local_only`, НЕ по `execution_mode` |
| `commands/rag_client.rs:80-90` (диапазон) | второй `ensure_not_local_only` (своя копия для RAG-клиента методологии) |

**Frontend (`src/`):**
| файл:строка | что делает |
|---|---|
| `routes/cabinet/+page.svelte:275-287` | `readExecutionMode()` — на входе в кабинет и по `window focus` зовёт `invoke('get_execution_mode')`, обновляет отображаемый признак маршрута |
| `routes/settings/+page.svelte:98-112` | `loadExecutionMode()` / `chooseExecutionMode(mode)` — читает/пишет `execution_mode` через `invoke('get_execution_mode' / 'set_execution_mode')` |
| `routes/settings/+page.svelte:123` | `probeLocalClaude` (перепроверка) → `invoke('probe_local_claude')` |
| `routes/settings/+page.svelte:136` | `invoke('set_local_only', { enabled: next })` — тумблер ДРУГОЙ оси |
| `routes/settings/+page.svelte:728,749,772` | 3 переключателя UI: `onchange={() => chooseExecutionMode('local'/'cloud'/'')}` (пустая строка = сброс к автоопределению) |
| `routes/+layout.svelte:232-237` | читает статус (объект с `cloud_advisors_enabled`, `consent_required`, `local_only`) — не сам `execution_mode`, а флаг редакции + согласие + ось `local_only` |

Дата отметки: 10.09.2026, ~23:45.

---

## РАЗДЕЛ Б. Путь ассистента

Файл `src-tauri/src/commands/claude.rs` (1854 строки).

### Б.1. `run_claude_inner` и спавн чужой программы

- `run_claude_inner(...)` — `claude.rs:339-423+` (сигнатура `claude.rs:339-349`, тело идёт дальше за пределами прочитанного среза, но точка спавна найдена).
- Резолв бинаря: `let claude_path = find_claude_binary()?;` — `claude.rs:350`.
- `find_claude_binary()` — `claude.rs:1837-1854`, оборачивает `find_claude_binary_detailed()` (`claude.rs:1830-1832`), которая зовёт `find_claude_in(&path_dirs(), &trusted_prefixes(), cfg!(windows))` через кэш `remembered_or_resolve` (`claude.rs:1805-1819`, кэш `RESOLVED_CLAUDE_BINARY` — `claude.rs:1803`).
  - Кандидаты имён: `["claude.exe", "claude.cmd", "claude"]` на Windows, `["claude"]` иначе — `claude.rs:1640-1646`.
  - Каталоги поиска — переменная среды `PATH` процесса (`std::env::split_paths`) — `claude.rs:1711-1715`.
  - Доверенные префиксы (куда согласны запускать найденный файл) — `claude.rs:1718-1741`: на Windows — `APPDATA`, `LOCALAPPDATA`, `USERPROFILE`, `PROGRAMFILES`, `PROGRAMFILES(X86)`; на прочих ОС — `/usr`, `/bin`, `/opt`, `/snap`, `$HOME`.
  - Если найден бинарь ВНЕ доверенных префиксов — `ResolveFailure::Untrusted(path)` (не «не найден») — `claude.rs:1791-1794`.
- Спавн процесса — `claude.rs:410-422`: на Windows через `Command::new("cmd")` + `arg("/C")` + `raw_arg(windows_cmd_command_line(&claude_path, &args))` (`claude.rs:411-416`, построитель строки — `claude.rs:1672-1694`, экранирует `&^|<>()` внутри пути от разбора `cmd.exe` как операторов); на остальных ОС — `Command::new(&claude_path).args(&args)` (`claude.rs:417-422`).
- Аргументы запуска (собраны раньше, `claude.rs:353-397`): `--print --output-format stream-json --verbose --dangerously-skip-permissions`, опционально `--resume <session_id>`, `--model <alias>`, `--effort <уровень>`, финал `-p -` (промпт подаётся через stdin, не аргументом).
- Сам факт: **эту стороннюю программу (`claude` CLI, установленный клиентом отдельно) продукт лишь запускает и передаёт ей данные через stdin/stdout — исходящие обращения к Anthropic делает CLI, а не код продукта напрямую.** Кода, который бы сам слал HTTP на домены Anthropic, в `claude.rs` не найдено (искал `reqwest`/`http`/`anthropic` в файле — нет; см. раздел В).

### Б.2. Ветка шлюза (облачный путь)

- Развилка в `run_claude` — `claude.rs:194-220` и в `run_claude_pipeline` — `claude.rs:256-278` (обе функции структурно идентичны).
- Формируется решение `decision = execution_mode::resolve(&app_handle).await` (`claude.rs:194`, `256`).
- Если `decision.mode == ExecutionMode::Cloud` И собрано с `#[cfg(feature = "thin")]` (`claude.rs:201`, `263`) — вызывается:
  - `crate::commands::gateway_executor::run_claude_gateway(...)` — `claude.rs:208-210` (обычный прогон);
  - `crate::commands::gateway_executor::run_claude_pipeline_gateway(...)` — `claude.rs:268-270` (фаза пайплайна).
- Обе функции — в `src-tauri/src/commands/gateway_executor.rs` (110 140 байт, существует в дереве ВСЕГДА, но подключается в `mod.rs` только под признаком `thin`: `#[cfg(feature = "thin")] pub mod gateway_executor;` — `commands/mod.rs:16-17`).
- Внутри `gateway_executor.rs` сетевой слой делегирован внешнему приватному крейту `aurora_gateway::cloud` (импорт `gateway_executor.rs:29-33`: `CloudClient`, `DeviceIdentity`, `JobRequest`, `JobState` и др.) — сам HTTP-транспорт живёт НЕ в этом репозитории, а в `aurora-platform-core` (подключается по git-метке `aurora_gateway-v0.6.6`, см. раздел Г).
- Адрес входа шлюза: `gateway_base_url()` — `gateway_executor.rs:40-42`: `std::env::var("AURORA_CLOUD_URL").unwrap_or_else(|_| "https://rag.auroraai.pro/cloud".to_string())`. Переопределяется переменной среды `AURORA_CLOUD_URL` (для стендов).
- Если локальный путь выбран (или `thin` не собран) — вызов `run_claude_inner(...)` (`claude.rs:217`, `275`); при ошибке — `local_failure(e)` (`claude.rs:219`, `227-232`), который отмечает `execution_mode::mark_local_failed` и НЕ переводит на шлюз (см. раздел А.2 правило 3).

### Б.3. Граница признака `cloud_advisors` — полный список мест

`cloud_advisors` = «скомпилирована ли облачная редакция вообще» (кабинеты-советники на Anthropic существуют в бинаре). Это ОТДЕЛЬНЫЙ, более широкий признак, чем `thin` (шлюз): `cloud_advisors` определяет, есть ли путь к Claude ВООБЩЕ (локальный ИЛИ облачный), `thin` — есть ли именно облачный (шлюз) маршрут внутри уже разрешённого.

Полный список `#[cfg(feature = "cloud_advisors")]` / `#[cfg(not(feature = "cloud_advisors"))]` / `#![cfg_attr(not(feature = "cloud_advisors"), ...)]`, найденный поиском по `src-tauri/src`:

| файл:строка | что за граница |
|---|---|
| `commands/claude.rs:4` | `#![cfg_attr(not(feature = "cloud_advisors"), allow(dead_code))]` — глушит предупреждения о неиспользуемом коде в локальной сборке (весь cloud-only код модуля недостижим) |
| `commands/claude.rs:137` | `ensure_cloud_consent` существует только при `cloud_advisors` |
| `commands/claude.rs:152` | `ensure_not_local_only` существует только при `cloud_advisors` |
| `commands/claude.rs:177` | В `run_claude`: ветка `#[cfg(not(feature = "cloud_advisors"))]` — ранний `anyhow::bail!("[CL-LOCAL] Облачные кабинеты-советники отключены в локальной редакции (0 Claude egress)")`, ДО спавна Claude CLI |
| `commands/claude.rs:182` | В `run_claude`: ветка `#[cfg(feature = "cloud_advisors")]` — весь путь с гейтами + `resolve()` + спавн |
| `commands/claude.rs:227` | `local_failure()` существует только при `cloud_advisors` |
| `commands/claude.rs:243` | В `run_claude_pipeline`: тот же ранний bail при отсутствии `cloud_advisors` |
| `commands/claude.rs:248` | В `run_claude_pipeline`: тот же путь с гейтами при наличии `cloud_advisors` |
| `commands/cabinet.rs:120-121` | `filter_by_product("econometrica", ...)`: при `cloud_advisors` кабинет `econometrist` виден (`Some(&["econometrist"])`) |
| `commands/cabinet.rs:122-123` | Без `cloud_advisors`: `Some(&[])` — ноль advisor-кабинетов для продукта `econometrica` |
| `commands/cabinet.rs:611, 619` | Тестовые ветки (`cloud_edition_exposes_econometrist_advisor` / `local_edition_hides_all_advisor_cabinets`), не рантайм-код |
| `commands/rag_client.rs:7` | `#![cfg_attr(not(feature = "cloud_advisors"), allow(dead_code))]` — аналогично claude.rs, для RAG-клиента методологии |
| `commands/rag_client.rs:9` | `use log::{debug, warn};` — только при `cloud_advisors` (иначе не используется) |
| `commands/rag_client.rs:64` | `ensure_cloud_consent` (своя копия) — только при `cloud_advisors` |
| `commands/rag_client.rs:79` | `ensure_not_local_only` (своя копия) — только при `cloud_advisors` |
| `commands/rag_client.rs:101` | В `econ_rag_search`: без `cloud_advisors` — `Err("[RAG-LOCAL] Библиотека методологии недоступна в локальной редакции")` |
| `commands/rag_client.rs:106` | С `cloud_advisors` — полный путь: гейты + HTTP-запрос к RAG-серверу |

Плюс безусловная константа-зеркало: `pub const CLOUD_ADVISORS_ENABLED: bool = cfg!(feature = "cloud_advisors");` — `claude.rs:128-132`, читается тестом `cloud_advisors_const_matches_build_feature` (`cabinet.rs:627-633`) и раздаётся фронту через tauri-команду `get_cloud_consent_status` (`lib.rs:2472-2481`, поле `cloud_advisors_enabled` — `lib.rs:2476`).

🔴 Редакция локальная (152-ФЗ) = сборка БЕЗ `cloud_advisors` (`--no-default-features`, т.к. `default = ["cloud_advisors"]` в `Cargo.toml:17`) — это ЕДИНСТВЕННЫЙ способ дойти до нуля Claude egress: и `run_claude`/`run_claude_pipeline` (не спавнят CLI), и `filter_by_product` (не показывает кабинет econometrist), и `econ_rag_search` (не ходит на RAG-сервер) все три гасятся ОДНИМ признаком.

Дата отметки: 10.09.2026, ~23:50.

---

## РАЗДЕЛ В. Полный список исходящих обращений в сеть

Метод: grep по `reqwest`/`Client::new`/`.get(`/`.post(` по `src-tauri/src` (backend); grep по `fetch(`/`XMLHttpRequest`/`WebSocket`/`EventSource`/`@tauri-apps/plugin-http` по `src` (frontend); grep по адресам-строкам (`"https?://…"`) по обоим деревьям; чтение `src-tauri/capabilities/default.json` и всех `tauri*.conf.json`; поиск сетевых модулей Python (`import requests/httpx/urllib/socket`) в `sidecar/` с исключением сторонних зависимостей (`_internal/`, `dist/`).

### В.1. Таблица обращений

| файл:строка | куда (домен/константа) | назначение | закрыто `ensure_not_local_only`? | закрыто `cloud_advisors`? |
|---|---|---|---|---|
| `commands/claude.rs` (спавн CLI, не сам HTTP) | нет прямого домена — спавнит `claude` CLI, который сам обращается к Anthropic | ассистент-советник кабинета | ДА (`ensure_not_local_only` — `claude.rs:189, 250`) | ДА (весь путь под `#[cfg(feature="cloud_advisors")]`) |
| `commands/gateway_executor.rs:41` (и тест-дубль `:1776`) | `https://rag.auroraai.pro/cloud` (переопределимо `AURORA_CLOUD_URL`) | шлюз Авроры — облачное исполнение кабинета-советника (ADR-048), транспорт — внешний крейт `aurora_gateway::cloud` | ДА (тот же чок-поинт `ensure_not_local_only`, т.к. вызывается только из уже прошедшего гейт `run_claude`/`run_claude_pipeline`) | ДА, и дополнительно только под `feature = "thin"` (`claude.rs:201, 263`) |
| `commands/rag_client.rs:118-121` | по умолчанию `http://127.0.0.1:8801` (`DEFAULT_RAG_URL`, `rag_client.rs:14`), переопределимо `AURORA_RAG_URL`; боевой адрес узла Б, вероятно `https://…` (не захардкожен — идёт из env) | библиотека методологии (эконометрическая RAG-библиотека на узле Б), поиск по запросу пользователя | ДА, свой `ensure_not_local_only` (`rag_client.rs:80-90`, вызов `rag_client.rs:108`) | ДА, вся команда `econ_rag_search` под `cloud_advisors` (`rag_client.rs:106`) |
| `commands/online_auth.rs:19` + `.rs:537-556` (`check_auth`/`authorize`, эндпоинт `/auth`) | `https://quzhkfvglqmppxcrindh.supabase.co/functions/v1/auth` | проверка лицензии при запуске (вызывается из `lib.rs:60` в `get_cabinets`, безусловно при каждом обращении к списку кабинетов вне dev-режима) | 🔴 НЕТ | 🔴 НЕТ (не под `cloud_advisors`; работает в ЛЮБОЙ редакции, включая локальную 152-ФЗ) |
| `commands/online_auth.rs:1195-1213` (`send_heartbeat`, эндпоинт `/heartbeat`) | тот же `supabase.co/functions/v1/heartbeat` | периодический heartbeat к серверу лицензий (команда `send_heartbeat`, `lib.rs:384-386`) | 🔴 НЕТ | 🔴 НЕТ |
| `commands/content_updater.rs:17-18` + вызовы `.get(` (`:473, 504`) | `https://quzhkfvglqmppxcrindh.supabase.co/functions/v1/content`, `/frontend-bundle` | докачка/обновление vault-файлов кабинетов и фронтенд-бандла с сервера (вызывается из `lib.rs:66-79`, часть того же безусловного блока `get_cabinets`) | 🔴 НЕТ | 🔴 НЕТ |
| `commands/updater.rs:14, 17-18` + `.get(`/`.post(` (`:80, 102, 239, 304`) | основной: `https://quzhkfvglqmppxcrindh.supabase.co/functions/v1/app-update`; запасной: `https://ackold26.github.io/rosst-updates` | проверка и скачивание обновлений .exe продукта | 🔴 НЕТ | 🔴 НЕТ |
| фронтенд `ImportStep.svelte:86` | `fetch('/sample-data/...')` | относительный путь к собственному статическому ресурсу приложения (НЕ egress наружу — под `connect-src 'self'` CSP) | н/п | н/п |
| `sidecar/econometrica/build_sidecar.py:237-298` | `urllib.request.urlopen(...)`, включая `http://127.0.0.1:{port}/health` | скрипт СБОРКИ sidecar (не рантайм-код продукта у клиента) — проверяет здоровье локального порта во время упаковки | н/п (не рантайм) | н/п |
| `commands/brand.rs:12`, `commands/parser.rs:8`, `econ_sidecar.rs:148,215,872`, `sidecar_runtime.rs:710` | `http://127.0.0.1:<порт>` (7420, 7421, 7430 и user-scoped варианты) | обращения к СОБСТВЕННЫМ локальным sidecar-процессам продукта (Parser HTTP-прокси, Econometrica MMM sidecar) — трафик не покидает машину | н/п (loopback, не сетевой egress) | н/п |

### В.2. 🔴 Обращения, НЕ закрытые ничем

Три канала работают **безусловно**, независимо от `execution_mode`, `local_only` и `cloud_advisors` — то есть присутствуют даже в локальной редакции (152-ФЗ, «0 Claude egress»):

1. **Проверка лицензии** — `commands/online_auth.rs`, функции `check_auth`/`authorize` (эндпоинт `/auth`) и `send_heartbeat` (эндпоинт `/heartbeat`), домен `quzhkfvglqmppxcrindh.supabase.co`. Вызывается из `lib.rs:60` при каждом запросе списка кабинетов (`get_cabinets`), кроме dev-режима (`AIAGENCY_DEV`, `lib.rs:40-54`, debug-сборка). Гейт `ensure_not_local_only`/`ensure_cloud_consent` в файле НЕ найден (искал `local_only`, `cloud_consent`, `ensure_not_local_only`, `ensure_cloud_consent`, `cfg(feature` — единственное совпадение, `online_auth.rs:500`, лишь ЧИТАЕТ `cloud_consent` для аудит-следа запроса, не блокирует его).
2. **Докачка контента (vault-файлов и фронтенд-бандла)** — `commands/content_updater.rs`, тот же домен `quzhkfvglqmppxcrindh.supabase.co/functions/v1`, эндпоинты `/content`, `/frontend-bundle`. Вызывается из того же безусловного блока `lib.rs:60-79+`. Гейтов в файле не найдено тем же поиском.
3. **Проверка и скачивание обновлений** — `commands/updater.rs`, домены `quzhkfvglqmppxcrindh.supabase.co/functions/v1/app-update` (основной) и `ackold26.github.io/rosst-updates` (запасной). Гейтов не найдено.

Комментарии в коде (`user_config.rs:37-40`) явно называют причину архитектурно: ось `local_only`/`cloud_advisors` отвечает ТОЛЬКО на вопрос «обращаться ли к облачному ИИ» (Claude-советник + RAG-библиотека методологии); лицензия, контент-пак и апдейтер — отдельная инфраструктурная категория, вне этой оси по всей видимости НАМЕРЕННО (лицензия обязана проверяться даже в локальной редакции, иначе программа не запустится вовсе — см. `online_auth.rs:527-535` о защите первого запуска). Но задание требовало факт, а не намерение: по коду эти три канала не закрыты НИКАКИМ из двух известных рантайм-гейтов.

### В.3. Итоговый счёт

- Egress-точек с уникальным сетевым назначением, найденных поиском по исходникам: **7** (Claude CLI-спавн опосредованно → Anthropic; шлюз Авроры; RAG-библиотека методологии узла Б; лицензия/heartbeat; докачка контента; апдейтер основной канал; апдейтер запасной канал GitHub Pages). Локальные loopback-обращения к собственным sidecar-процессам (Parser, Econometrica MMM) в счёт не включены — трафик не покидает машину.
- Закрыты обеими осями (`ensure_not_local_only` + `cloud_advisors`): 3 (Claude CLI/локальный путь, шлюз Авроры, RAG-библиотека методологии).
- НЕ закрыты ничем: 3 (лицензия+heartbeat, докачка контента, апдейтер) — все три ведут на инфраструктуру Платформы Аврора (Supabase-проект `quzhkfvglqmppxcrindh`, плюс GitHub Pages запасным каналом апдейтера).

### В.4. Разрешённые домены на уровне Tauri-конфигурации

`src-tauri/capabilities/default.json` (`capabilities/default.json:6-22`) — список permissions НЕ содержит `http:*` (плагин `@tauri-apps/plugin-http` не подключён вовсе), т.е. фронтенду формально не выдано разрешение делать сетевые запросы через Tauri HTTP-plugin; весь показанный в разделе В.1 egress идёт из Rust-backend (`reqwest`), не из WebView.

`src-tauri/tauri.conf.json:15` — CSP: `connect-src 'self' https://ackold26.github.io http://localhost:7430`. Разрешает WebView-фетчи только к себе, к GitHub Pages (запасной канал апдейтера — хотя фактический fetch к нему делает backend, не webview) и к своему loopback sidecar-порту 7430 (Econometrica MMM, `econ_sidecar.rs:63,199`). Домен `quzhkfvglqmppxcrindh.supabase.co` и `rag.auroraai.pro` в CSP НЕ упомянуты — потому что запросы к ним отправляет Rust-backend, а не WebView (CSP их не касается).

Дата отметки: 10.09.2026, ~00:05 (11.09 по часам машины).

---

## РАЗДЕЛ Г. Две редакции сборки

### Г.1. Скрипты `package.json`

- `"tauri:build:local": "tauri build --config src-tauri/tauri.local.conf.json -- --no-default-features"` — `package.json:18`.
- `"tauri:build:thin": "node tools/build-cloud.mjs"` — `package.json:19`.
- Обычная `tauri build` (без npm-скрипта, штатная Tauri CLI команда) собирается с `Cargo.toml` как есть — признак `cloud_advisors` включён по умолчанию (`default = ["cloud_advisors"]`, `Cargo.toml:17`), признак `thin` отсутствует (объявлен только во фрагменте, см. Г.2).

### Г.2. Признаки Cargo

`src-tauri/Cargo.toml:12-34`:
- `default = ["cloud_advisors"]` (`Cargo.toml:17`).
- `cloud_advisors = []` (`Cargo.toml:20`) — «кабинеты-советники на Anthropic»; при выключении (`--no-default-features`) `run_claude`/`run_claude_pipeline` рано `bail!` (см. раздел Б.3), `filter_by_product` прячет `econometrist`, `econ_rag_search` недоступна.
- `legacy_aiagency_fallback = []` (`Cargo.toml:24`) — не относится к маршруту ассистента (legacy-лицензия для форков Agency), не разбирался подробно — вне рамок задания.
- Признак `thin` НЕ объявлен в `Cargo.toml` вовсе (намеренно, ADR-048, комментарий `Cargo.toml:25-34`) — он живёт только в `src-tauri/Cargo.cloud.fragment.toml:23-25`: `thin = ["dep:aurora_gateway"]`, и подключает зависимость `aurora_gateway` по git-метке (`Cargo.cloud.fragment.toml:47`: репозиторий `github.com/Ackold26/aurora-platform-core.git`, тег `aurora_gateway-v0.6.6`, фича крейта `cloud-http`).

### Г.3. Что делает `tools/build-cloud.mjs` (`tauri:build:thin`)

- Константа `CLOUD_FEATURE = 'thin'` — `tools/build-cloud.mjs:386`.
- Временно склеивает `Cargo.toml` (бэкап → `Cargo.toml.pre-cloud`) с `Cargo.cloud.fragment.toml` (логика склейки — `tools/build-cloud.mjs:1112-1151`), восстанавливает на любом пути выхода (`SIGINT/SIGTERM/SIGHUP/SIGBREAK/exit`/необработанное исключение) — раздел комментария `tools/build-cloud.mjs:22-40`.
- Финальная команда сборки — `tools/build-cloud.mjs:1290-1297`: `tauri build ... -- --features thin` (**БЕЗ** `--no-default-features`) — то есть у итогового бинаря включены ОБА признака: `cloud_advisors` (default) И `thin` (добавлен явно). Значит **поставка `tauri:build:thin` содержит оба маршрута ассистента одновременно** — локальный Claude Code клиента (через `cloud_advisors`) и шлюз Авроры (через `thin`), выбор между ними делается во время работы через `execution_mode` (раздел А). Название npm-скрипта («тонкая», thin) относится к признаку Cargo, а не к тому, что локальный путь исключён.
- Также запускает `checkFrontendTypes()` перед сборкой (`tools/build-cloud.mjs:1301`) и поддерживает флаги `--check` (только компиляция) и `--test` (прогон тестов облачного пути) — `tools/build-cloud.mjs:1272-1275`.

### Г.4. Что делает `tauri:build:local`

- `tauri build --config src-tauri/tauri.local.conf.json -- --no-default-features` (`package.json:18`) — явно гасит `cloud_advisors` (и тем самым весь Claude-путь, локальный и облачный, целиком недостижим — ни `run_claude`, ни `econ_rag_search`, ни кабинет `econometrist` в списке). Признак `thin` не запрашивается и не может быть включён (он требует `dep:aurora_gateway`, которой тут просто нет в графе).
- `tauri.local.conf.json` — оверлей конфигурации (согласно `CLAUDE.md` проекта, не перепроверялось построчно в этом задании: другой `productName`/`identifier`, `com.aurora.econometrica.local`).

### Г.5. Какая редакция поставляется клиенту

Из `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt\CLAUDE.md` (раздел «Сборка», НЕ перепроверено этой инвентаризацией живым прогоном — только прочитано как документ проекта, отдельно от кода): поставка клиенту собирается ТОЛЬКО `npm run tauri:build:thin`; штатная `npm run tauri build` даёт «поставку без шлюза» (это НЕ клиентская поставка); `npm run tauri:build:local` — отдельная локальная редакция для 152-ФЗ. Файл датирован 17.08.2026, дальнейших изменений после этой даты по коду не проверялось (задание — только код, а не CLAUDE.md).

### Г.6. Определение редакции в рантайме

Из уже найденного в разделах А и Б:
- `commands/claude.rs:132`: `pub const CLOUD_ADVISORS_ENABLED: bool = cfg!(feature = "cloud_advisors");` — статическая константа, вкомпилированная в бинарь; читаема из Rust-кода везде.
- `commands/execution_mode.rs:131-133`: `pub fn cloud_built_in() -> bool { cfg!(feature = "thin") }` — то же самое для признака `thin`.
- Фронту доступны ОБА индикатора через разные tauri-команды: `get_cloud_consent_status` → поле `cloud_advisors_enabled` (`lib.rs:2476`); `get_execution_mode` → `ModeState.cloud_built_in` (`execution_mode.rs:118, 510`, отдаётся `lib.rs:2530-2535`). Прямого единого поля «редакция: thin/local/normal» одной строкой не найдено — редакция вычисляется комбинацией этих двух булевых флагов (оба `true` = поставка клиенту; `cloud_advisors=true, thin=false` = проверочная сборка без шлюза; `cloud_advisors=false` = локальная 152-ФЗ редакция, `thin` в этом случае недостижим по построению).

Дата отметки: 10.09.2026 (по системным часам — уже 11.09), ~00:15.

