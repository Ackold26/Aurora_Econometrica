# Handoff — блок сессии 2026-07-20 (тонкая версия как модуль: крейт aurora_gateway + feature `thin`)

База аудита (двурепозиторный блок, base-sha hook не писался — cwd сессии не был git-репо, базы взяты явно и точны):
- **Econometrica**: `29eb8c8..03c2795` (5 коммитов на `feat/econ-thin-client` от origin/feat/econ-v2.3.0: `cdc90ae` deps/feature · `b1b5fbf` executor+ветвление · `533adef` conf/скрипт/updater · `a4a18a4` display_version · `03c2795` фикс стрим-эмитов).
- **aurora-platform-core**: `b65e9d0..00f635f` (2 коммита на `feat/gateway-transport-crate` от origin/main: `2bba87a` крейт aurora_gateway · `00f635f` carry-over aurora_fleet).
Оба diff'а конкатенированы в `Projects/audit.diff` (секции помечены `### REPO:`).

## 1. Цель блока

Построить фундамент «тонкой версии» продуктов Aurora (ADR-041): тот же код полной версии + Cargo feature `thin`, при котором Claude-кабинет-советник исполняется не локальным Claude CLI, а через SSH-gateway на сервере (узел Б) — пользовательский ПК без Claude Code. Пилот — Econometrica. Блок = общий транспорт-крейт `aurora_gateway` в aurora-platform-core (перенос боевого эталона thin-client/app) + подключение его в Econometrica за feature `thin` (адаптер `gateway_executor`, конфиг сборки, отдельный канал обновлений, отображаемая версия «2.4.0C»).

## 2. Ключевые инварианты

- **Default-сборка (без `--features thin`) байт-в-байт сохраняет прежнее поведение**: весь новый код за `#[cfg(feature="thin")]`; optional-зависимость aurora_gateway не компилируется; 197 существующих тестов зелёные без изменений (кроме осознанно расширенного `update_channel_matches_edition`).
- **thin собирается ПОВЕРХ default** (`cloud_advisors` остаётся ON); thin и локальная редакция (`--no-default-features`) НЕ сочетаются.
- **Consent-гейты (`ensure_not_local_only` + `ensure_cloud_consent`) исполняются ДО gateway-ветки** — ось Оффлайн/Онлайн: без согласия пользователя запрос не уходит на сервер.
- **При thin локальный CLI-путь статически недостижим**: `run_claude_inner`/`find_claude_binary`/`isolated_claude_config_dir` не вызываются (помечены `cfg_attr(allow(dead_code))` точечно).
- **Канал обновлений разведён машинно**: `update_product_key()` → `-thin` имеет высший приоритет (иначе тонкому клиенту приедет полный exe с локальным CLI-путём).
- **Сессии**: серверный label передаётся через существующий механизм `claude_session_id` (None → новый `tc-<cabinet>-<8hex>`; продолжение → тот же label; слэш-сброс продукта → новый label). Ноль нового клиентского состояния. Сервер сам HMAC-derive'ит session_key из принципала+кабинета+label (label — не секрет).
- **События чата**: канал `claude-stream-<cabinet>` принимает СТРОКУ (фронт делает `JSON.parse(event.payload)`); порядок thin-пути: `system/init` (снимает safety-таймер) → финальный `{"type":"result","result":<text>}` → `claude-done {exit_code:0}`; при `suppress_done` (pipeline) события не эмитятся.
- **Версии — чистый semver** внутри (Cargo/Tauri/NSIS); «C» добавляется ТОЛЬКО в отображении (`display_version()`), автоматически от cfg.
- **Крейт aurora_gateway — чистый синхронный rlib** (serde/serde_json/thiserror; без tokio/tauri); логика transport.rs = боевой эталон thin-client/app 1:1 (диф — 3 строки шапки); SSH-опции/лимиты/тайминги не менялись.
- **auto_save_response** — извлечение из run_claude_inner 1:1 (поведение автосохранения идентично для обоих исполнителей).

## 3. Осознанные компромиссы

- **Ответ приходит целиком, без построчного стрима** → сервер работает job-моделью (202+poll), промежуточных токенов не отдаёт; UI умеет рендерить `result` без дельт. Живой стрим — фаза 2 (расширение движка).
- **Файлы-артефакты кабинета через gateway не передаются** (контракт отдаёт только имена) → советник econometrist на сервере без exec-прав файлов не создаёт; локальный экспорт ответа (.md+конвертации) делается клиентом из полученного текста. Доставка артефактов — фаза 2.
- **model/effort пользователя в thin не прокидываются** (сервер форсит sonnet/low) → расширение контракта `/run` отложено.
- **modes.rs (Mode-router 3 режимов) НЕ перенесён в крейт** → 2 из 3 режимов — заглушки (Resident: PLACEHOLDER-узел; Local: hardcoded ollama-заглушка), перенос тащил бы aurora_fleet+tokio+build.rs в «лёгкий» транспорт. Пилоту маршрутизация не нужна (один узел Б).
- **Untracked-копия крейта в основном дереве core** (`aurora-platform-core\aurora_gateway\`) → path-зависимость продукта должна работать до слияния ветки, а основное дерево занято чужой сессией (ветка feat/reg-pay-cabinets-jwt). Перед будущим pull копию убрать.
- **generate_session_label — не криптостойкий** (nanos+atomic counter+PID) → label не секрет и не капабилити: анти-hijack обеспечивает серверный HMAC-derive.
- **`AURORA_NODE_B` из env с константой-дефолтом 37.27.218.187** → адрес узла публичный, per-клиент выдача узлов — вместе с клиентским пакетом в фазе 2.

## 4. Зоны неуверенности

1. **События чата не проверены живым GUI** — набор init/result/done выведен из чтения ChatPanel.svelte и claude.rs (эмиттер CLI), но сборка .exe и реальный прогон не выполнялись; возможны расхождения в обработке прогресс-состояний (progressPhase/статусы) при полном отсутствии промежуточных assistant-дельт.
2. **Взаимодействие retry-loop send_message (lib.rs:1108–1156) с gateway-ошибками**: классификация retryable писалась под stderr локального CLI; тексты `[TC-GW-*]` могут попадать/не попадать под ретрай неожиданным образом (лишние повторные вызовы сервера или, наоборот, отсутствие ретрая на транзиенте).
3. **Протухание серверной сессии** (idle-TTL 3600с, LRU 64): клиент продолжит слать старый label — сервер молча создаст НОВУЮ сессию (resumed=false), контекст диалога потеряется без UI-уведомления (CLI-путь в аналогичной ситуации эмитит resume_fallback). Поведение корректно-безопасное, но UX-расхождение с полной версией.
4. **client_dir при dev-запуске**: путь `%APPDATA%\<identifier>\client` зависит от identifier, который подменяется только оверлеем tauri.thin.conf.json при сборке; `tauri dev --features thin` без оверлея будет искать пакет в базовом identifier — возможна путаница на e2e.
5. **Cargo.lock крейта существует в двух местах** (worktree-ветка core и untracked-копия в основном дереве) — при дрейфе версий зависимостей сборки могут разойтись до слияния ветки.

## 5. Затронутые файлы

**aurora-platform-core (ветка feat/gateway-transport-crate):**
- `aurora_gateway/Cargo.toml` — манифест нового крейта (serde/serde_json/thiserror).
- `aurora_gateway/src/lib.rs` — модуль+re-export'ы, док контракта.
- `aurora_gateway/src/transport.rs` — перенос боевого SSH-транспорта 1:1 (send_to_gateway, GatewayRequest/Response, TransportError, юнит-тесты).
- `aurora_fleet/src/{error,lib,license,online_auth}.rs` + `local_mode.rs` (новый) — carry-over аудит-фиксов 2026-07-06 с чужой ветки (отдельный коммит, к thin-логике не относится).

**Econometrica (ветка feat/econ-thin-client):**
- `src-tauri/Cargo.toml` — optional dep aurora_gateway + feature `thin`.
- `src-tauri/src/commands/gateway_executor.rs` (новый) — адаптер: label-сессии, spawn_blocking→send_to_gateway, маппинг ошибок [TC-GW-*], события init/result/done, локальный экспорт.
- `src-tauri/src/commands/claude.rs` — ветки `#[cfg(feature="thin")]` в run_claude/run_claude_pipeline; извлечение auto_save_response; cfg_attr(dead_code) ×3.
- `src-tauri/src/commands/mod.rs` — объявление модуля под cfg.
- `src-tauri/src/commands/updater.rs` — приоритет `-thin` в update_product_key + расширенный тест.
- `src-tauri/tauri.thin.conf.json` (новый) — оверлей identifier `com.aurora.econometrica.thin`.
- `package.json` — скрипт `tauri:build:thin`.
- `src-tauri/src/lib.rs` — команда `display_version` + регистрация.
- `src/routes/settings/+page.svelte` — источник версии → invoke('display_version') («2.4.0C»).
- `src-tauri/Cargo.lock` (корневой workspace-lock) — фиксация optional-зависимости.
