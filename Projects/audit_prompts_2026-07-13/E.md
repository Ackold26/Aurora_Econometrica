# E — сквозной аудит каналов доставки промптов (2026-07-13)

Вопрос: «промпт в репо = промпт у клиента?» Оценки 1–5 ставятся КАНАЛАМ доставки.

## Слой 1: системный промпт + 17 команд econometrist (vault-канал) — зрелость 2 / эффективность 3

**Карта канала:**
- Источник в репо: `New_AI_Agency/econometrist/CLAUDE.md` + `.claude/commands/*.md` (17 файлов).
- Упаковка: `tools/vault-packer/src/main.rs:191-224` (PackAll) → `econometrist.vault` (AES-256-GCM, ключ = HKDF(fingerprint, salt лицензии)). Ручной шаг, вне сборки .exe.
- **Vault НЕ входит в bundle .exe**: `src-tauri/tauri.conf.json:33-39` — resources только help-econometrica, sidecar, content-packs, pptx_pipeline.py, NOTICE.md. Установленный .exe промптов кабинета НЕ содержит. Ответ на ключевой вопрос: конфликта bundle↔vault НЕ существует — vault единственный источник, «выигрывает» всегда vault.
- Доставка клиенту: OTA-загрузка из Supabase `/content` (`content_updater.rs:257-284` download_vault_file) → шифрование локальным ключом → `%APPDATA%\com.aurora.econometrica\vaults\econometrist.vault` (`content_updater.rs:339-345`).
- Порядок фолбэков при чтении (`vault.rs:82-125` resolve_vault_path): per-app `vaults/` (mapped имя → исходное) → legacy `%PROGRAMDATA%\AIAgency\vaults\` (авто-миграция копированием). 
- Распаковка в workspace: `session/manager.rs:69-193` open_session (tar.gz → temp → workspace; манифеста/подписи содержимого vault нет — целостность даёт только AES-GCM tag).
- Runtime-мутация промпта: `manager.rs:163-176` — к CLAUDE.md ДОПИСЫВАЕТСЯ блок «Ограничения доступа к файлам» → промпт у клиента = репо + суффикс (задокументированное расхождение, by design).

**Триггер обновления у клиента (РАЗРЫВ):**
- `lib.rs:61-97` (get_cabinets): вауты качаются ТОЛЬКО если файл отсутствует ИЛИ не расшифровывается локальным ключом. Версия НЕ сравнивается.
- `lib.rs:426-441` (open_cabinet): докачка только если `!vault_path.exists()`.
- `content_updater::check_update_per_cabinet` (`content_updater.rs:197-214`) — вызывается ТОЛЬКО из тестов; `vault_versions` из /auth ответа (`online_auth.rs:352,400`) никем не потребляется.
- Tauri-команды `check_content_update`/`update_content` (`lib.rs:264-292`) из фронтенда НЕ вызываются (grep по src/ — 0 вхождений).
- `authorize(&config_dir, app_version, "")` — клиент шлёт серверу content_version="" (`lib.rs:56,402`), сервер не знает версию клиента.
- Чексуммы при автозагрузке passed как `{}` (`lib.rs:91,435`) → download без верификации checksum (только HTTPS+AES).

**Вывод:** правка промпта econometrist доедет ТОЛЬКО до (а) новых установок, (б) клиентов с битым/отсутствующим vault. Существующий клиент с валидным vault НЕ получит обновление промпта никогда (нет ни версионного, ни checksum-триггера в живом коде).

### Находки слоя 1
- [high] src-tauri/src/lib.rs:69-87 — vault-обновление триггерится только missing/undecryptable; version-based канал мёртв (check_update_per_cabinet только в тестах content_updater.rs:831+; vault_versions из /auth не потребляется) → опубликованное обновление промпта НЕ доезжает до живых клиентов.
- [medium] src-tauri/src/lib.rs:91,435 — checksums `{}` при автозагрузке vault: download_updates пишет vault без проверки checksum (content_updater.rs:322 «if available» — недоступен).
- [medium] src-tauri/src/lib.rs:402 — content_version в auth-запросе всегда "" → сервер лишён возможности форсировать доставку контента конкретному клиенту.
- [low] src-tauri/src/session/manager.rs:163-176 — CLAUDE.md у клиента ≠ CLAUDE.md в репо (append «Ограничения доступа»); by design, но при сверке хешей репо↔клиент это надо учитывать.
- [low] tools/vault-packer/src/main.rs:112 — packer кладёт в tar ВСЁ содержимое папки кабинета, включая LEGACY_COMMANDS.md (New_AI_Agency/econometrist/LEGACY_COMMANDS.md) — легаси-промпты уезжают клиенту в workspace.

## Слой 2: UI-мета content-packs/ (cabinets.json, command-meta-data.json, themes.json, psy/classifier/onboarding) — зрелость 3 / эффективность 4

**Карта канала:**
- Источник в репо: `content-packs/*.json` + `manifest.json` + `manifest.sig` (Ed25519, ОТДЕЛЬНЫЙ ключ от лицензионного — `crypto/content_sig.rs:14-22`; rollback-защита MIN_CONTENT_VERSION=1, content_sig.rs:22).
- Канал 1 (bundle): `src-tauri/tauri.conf.json:36` — `../content-packs/*` в resources → `_up_/content-packs/` внутри установки. Доезжает ТОЛЬКО пересборкой .exe. Читается как фолбэк `get_content_pack` (lib.rs:1722-1735) БЕЗ проверки подписи/manifest.
- Канал 2 (OTA, ЖИВОЙ — в отличие от vault-слоя): `check_all_updates` (lib.rs:194-216): server_pack_ver > local_ver → download tar.gz → checksum → `verify_manifest` (Ed25519 + SHA-256 каждого файла + anti-traversal) ДО атомарного свопа (content_updater.rs:412-489). Версии server-side из `/auth` (online_auth.rs:353-355).
- Триггер OTA: ТОЛЬКО команда `check_online_auth` (lib.rs:179, гейт `status=="ok"` — кэшированный "cached" НЕ триггерит), а её вызывает ТОЛЬКО `settings/+page.svelte:313`. Старт приложения и get_cabinets `check_all_updates` НЕ зовут.
- Потребители: Rust — cabinets.json → `get_cabinet_definitions_dynamic`/`get_commands_dynamic` при packs_ok, иначе hardcoded (lib.rs:99-104, 1429-1433); JS — `+layout.svelte:163-167` (command-meta/psy/classifier/onboarding/themes) с фолбэком на встроенные дефолты.
- Верификация на старте: `verify_content_packs` → AtomicBool `content_packs_verified` (lib.rs:3161-3168). Нет manifest = Ok(false) = fallback (первая установка так и живёт: инсталлятор пак в LOCALAPPDATA НЕ копирует, data_migration.rs:35,77 переносит только со старого identifier).

**ФАКТИЧЕСКАЯ сверка хешей (выполнена 2026-07-13, Get-FileHash):**
- themes.json actual `sha256:74d3f15e45bb22b290d7cda5e373bdea68d6e43e5439120ad88432c4bab0f366` ≠ manifest `sha256:3082ab5ebe46cb3820ac5b2f4112385964f5968b088907fd499e06d48a23e7a5` — РАССИНХРОН (themes.json правлен после подписания manifest v5, timestamp 1781487354).
- Остальные 5 файлов (cabinets, classifier-data, command-meta-data, onboarding-data, psy-data) — сходятся.

### Находки слоя 2
- [high] content-packs/manifest.json:1 vs content-packs/themes.json — SHA-256 рассинхрон (actual 74d3f15e… ≠ manifest 3082ab5e…): пак, упакованный из репо as-is, провалит verify_manifest у клиента → OTA UI-меты отвергнется (fail-closed, но обновление не доедет); bundled themes.json в .exe ≠ подписанной v5 → каналы 1 и 2 везут РАЗНЫЕ themes.
- [medium] src-tauri/src/lib.rs:179 + src/routes/settings/+page.svelte:313 — единственный триггер OTA контент-паков = открытие Настроек при свежем онлайн-«ok»; клиент, не заходящий в Настройки, обновление UI-меты не получит никогда.
- [medium] src-tauri/src/lib.rs:1712-1754 — get_content_pack НЕ проверяет флаг content_packs_verified: при FAILED-верификации (тампер) JSON-мета из LOCALAPPDATA всё равно отдаётся фронту, тогда как Rust-слой откатился на hardcoded → расщепление источников UI.
- [low] src-tauri/src/lib.rs:1722-1735 — bundled-фолбэк читает пак без проверки manifest.sig (терпимо: внутри инсталлятора, но канал несамопроверяем).
- [low] src-tauri/src/commands/data_migration.rs:35 — first-run не разворачивает bundled пак в LOCALAPPDATA: до первого OTA Rust-мета = hardcoded, JS-мета = bundled JSON — две редакции меты в одном .exe.

## Слой 3: промпты Авроры (src/lib/*.js) + списки команд (cabinet.rs) — зрелость 3 / эффективность 4

**Карта канала:**
- Промпты Авроры живут во фронтенд-JS: `src/lib/tier2-context.js` (grounding Tier-2), `scenario-advisor.js:39-53` (buildScenarioParsePrompt), `insights-grounding.js`, `data-chat-engine.js`, `rag-query.js`, `econ-project-context.js`. Шлются через `econ_ask_insight` (lib.rs:329-366) → `run_claude` в workspace econometrist → системный промпт = vault-CLAUDE.md (слой 1).
- Канал 1 (основной): SvelteKit build → `frontendDist: "../build"` (tauri.conf.json:10) → ВШИТ в .exe. Доезжает пересборкой + exe-OTA (updater.rs).
- Канал 2 (существует в коде!): внешний frontend-бандл OTA — `check_all_updates` (lib.rs:219-239) → `download_frontend_bundle_from_url` (content_updater.rs:593+, verify_manifest) → `frontend-vN/` + `current_frontend_version.txt`; грузится через протокол aurora:// если `has_verified_external_frontend` (lib.rs:2387-2406, 3174-3187). Утверждение «JS-промпты доезжают ТОЛЬКО пересборкой .exe» строго НЕВЕРНО — но канал под тем же узким триггером (Настройки + свежий «ok»), и работоспособность зависит от публикации frontend_version на сервере.
- **РАЗРЫВ приоритета:** если внешний frontend когда-либо ставился, `has_verified_external_frontend`=true грузит его БЕЗ сравнения с версией встроенного (lib.rs:3174-3187 — только verify, никакого version-compare embedded↔external; min_core_version из манифеста нигде не проверяется, content_sig.rs:63-133). Свежая правка JS-промпта, доехавшая пересборкой .exe, будет молча ПЕРЕКРЫТА старым внешним бандлом.
- Списки команд: hardcoded кортежи `cabinet.rs:146-278` (пересборка) ПЕРЕКРЫВАЮТСЯ cabinets.json из content-pack (`get_commands_dynamic` cabinet.rs:344-353) при packs_ok → список команд обновляем OTA, а сами .md-промпты команд — vault-канал (мёртвый, слой 1). Сверка репо: hardcoded econometrist 8 команд == cabinets.json 8 команд == подмножество 17 vault .md — сейчас согласовано.

### Находки слоя 3
- [high] src-tauri/src/lib.rs:3174-3187 + 2387-2406 — установленный внешний frontend-бандл грузится вместо встроенного БЕЗ version-compare (и min_core_version не проверяется): обновление .exe не вернёт клиенту новые JS-промпты Авроры, пока жив старый frontend-vN — тихий откат правок промптов.
- [medium] cabinet.rs:344-353 + слой 1 — расщепление каналов «список команд (content-pack OTA, живой) vs тело промпта (vault OTA, мёртвый)»: новая команда, доехавшая в cabinets.json, у старого клиента не имеет .md в vault → «Unknown skill» на витрине.
- [low] src/lib/scenario-advisor.js:39-53 и родственные — интенты-промпты Авроры дублируют контракт INV-50 с vault-CLAUDE.md; при рассинхроне версий (exe новый, vault старый) правила могут противоречить — не дефект сейчас, но следствие мёртвого vault-канала.

## Слой 4: две редакции (облачная default vs локальная --no-default-features) — зрелость 3 / эффективность 4

**Карта канала:**
- Оверлей `src-tauri/tauri.local.conf.json` меняет ТОЛЬКО productName + identifier (`com.aurora.econometrica.local`); CARGO_PKG_NAME общий → `detect_product()` = "econometrica" в ОБЕИХ редакциях (online_auth.rs:48).
- exe-OTA развед ён: `update_product_key()` (updater.rs:77-83) добавляет «-local» → отдельный манифест `aurora-econometrica-gui-local/latest.json`; закреплено тестом update_channel_matches_edition (updater.rs:341-349). Публикация двух манифестов — процедурная обязанность (регламент aurora-release-update).
- Наборы промптов: локальная = 0 Claude egress (`run_claude` bail без feature cloud_advisors), RAG отключён (rag_client.rs:101-105), advisor-кабинет скрыт `filter_by_product` (cabinet.rs:120-123, cfg-гейт).
- **РАЗРЫВ:** auth-запрос (online_auth.rs:279-289) НЕ несёт признака редакции (product одинаков, identifier не передаётся) → сервер не отличает локальный клиент от облачного. В прод-пути get_cabinets (lib.rs:100-107) фильтрация ТОЛЬКО по online.cabinets с сервера — `filter_by_product` (единственный cfg-гейт редакции) применяется ЛИШЬ в dev-ветке (lib.rs:47) и diagnostics; JS-фильтр (command-meta.js:150-154) читает products из ОБЩЕГО content-pack («econometrica»: ["econometrist"]) и тоже не знает редакции. Если сервер выдаст локальному клиенту cabinets:["econometrist"] — локальная 152-ФЗ редакция ПОКАЖЕТ кабинет-советник и скачает econometrist.vault (промпты лягут на диск), а работать он не сможет (bail). Защита редакции держится на серверной конфигурации лицензий, не на клиенте.
- Разные identifier → раздельные %APPDATA%/%LOCALAPPDATA% → у каждой редакции свой content-pack и свой триггер OTA (визит в Настройки). Если локальные клиенты не зарегистрированы на сервере (auth≠ok) — UI-мета локальной редакции обновляется ТОЛЬКО пересборкой .exe, облачной — ещё и OTA: правка доедет одной редакции и не доедет другой.

### Находки слоя 4
- [medium] src-tauri/src/commands/online_auth.rs:279-289 + lib.rs:100-107 — клиент не сообщает редакцию, а прод-путь get_cabinets не применяет filter_by_product: показ advisor-кабинета и доставка vault-промптов в локальную 152-ФЗ редакцию блокируются только серверной конфигурацией, не бинарём.
- [medium] updater.rs:74-76 — паритет редакций держится на ручной публикации ДВУХ exe-манифестов и (для UI-меты) на разных identifier-путях: пропуск публикации local-манифеста = редакции разъезжаются по промптам молча (задокументировано, теста/гейта на публикацию нет).
- [low] content-packs/command-meta-data.json (products.econometrica) — один пак на обе редакции без флага редакции: локальная редакция получает описания/категории advisor-команд, которых у неё нет.

## Слой 5: dev/prod-развилка (AIAGENCY_DEV, AIAGENCY_DEV_CABINETS) — зрелость 5 / эффективность 5

**Карта:**
- Все 4 точки AIAGENCY_DEV (lib.rs:37 get_cabinets, :377 open_cabinet, :1908 get_allowed_cabinets, :2678 workflow) — под `#[cfg(debug_assertions)]` (lib.rs:36, 376, 1907, 2677) → в release-бинаре ветка dev-промптов из папки New_AI_Agency СТАТИЧЕСКИ отсутствует, env-переменная у клиента ничего не включит.
- Dev-фолбэк content-pack из репо (lib.rs:1739-1750) — тоже `#[cfg(debug_assertions)]`.
- Release-достижимые env-тумблеры проверены: AURORA_SIDECAR_LEGACY_PORT / AURORA_SKIP_HANDSHAKE (sidecar_runtime.rs:198-216, документированные safety valves, промптов не касаются), AURORA_PROJECTS_ROOT (project.rs:136, путь проектов), AURORA_RAG_URL (rag_client.rs:118, валидируется validate_rag_url:31-49 — https или localhost). Подмены источника промптов через env в release НЕТ.
- AURORA_SMOKE_LICENSE — только в #[test] (license.rs:417-420).

### Находки слоя 5
- Находок нет: dev-развилка исключена статически, компиляционный гейт + env-var (двойная защита). Единственный остаток: [low] tauri.dev.conf.json/withGlobalTauri вынесен в dev-overlay по INV-52 — соблюдено (базовый tauri.conf.json:12-17 без withGlobalTauri).

## Итоговая карта доставки (все слои)

| Слой | Канал | Триггер обновления | Фолбэки (порядок) | Разрывы |
|---|---|---|---|---|
| Системный промпт + команды econometrist (.md) | vault AES-GCM ← Supabase /content | только missing/undecryptable vault; version-канал мёртв | per-app vaults/ → legacy PROGRAMDATA (миграция) | правка промпта НЕ доезжает до живых клиентов |
| UI-мета (cabinets/command-meta/themes…) | content-pack tar.gz OTA (Ed25519+SHA256, atomic swap) + bundle .exe | ТОЛЬКО открытие Настроек при свежем auth«ok» | LOCALAPPDATA pack → bundled _up_/ (без подписи) → hardcoded (Rust) / JS-дефолты | themes.json рассинхрон с manifest v5; get_content_pack игнорирует флаг верификации |
| Промпты Авроры (JS) | embedded build в .exe; + внешний frontend-бандл OTA | пересборка .exe; frontend-OTA — тот же узкий триггер | external frontend-vN (если verified) ПЕРЕКРЫВАЕТ embedded без version-compare | старый внешний бандл тихо откатывает exe-правки промптов |
| Списки команд | hardcoded cabinet.rs + override cabinets.json (pack OTA) | как UI-мета | pack → hardcoded | список команд OTA-живой, тела промптов — мёртвый vault → «Unknown skill» |
| Редакции облачная/локальная | два exe-манифеста (-local), общий product в auth | ручная публикация обоих манифестов | — | сервер не отличает редакции; filter_by_product нет в прод-пути |
| Dev-развилка | — | — | — | нет (статически исключена) |
