# Батч 0 — оживление доставки промптов кабинета (2026-07-13)

Ветка: `feat/econ-v2.3.0` (worktree). НЕ коммичу — правки в рабочем дереве.
Серверная часть (Supabase Edge Function `/auth`) — в репо нет, вне периметра.

## Предварительный разбор (перед правками)

- `online_auth.rs::OnlineAuthStatus` УЖЕ содержит `vault_versions: Option<HashMap<String,u32>>`
  (строка 159) и заполняется из `resp.vault_versions` во всех ветках `authorize()` —
  ok (352), blocked/denied (373: None), cached (400), offline (421: None).
  → Пункт 1 задачи 0.1 уже выполнен в коде, менять не пришлось.
- `content_updater::check_update_per_cabinet` (строка 197) и `download_updates` (строка 289) —
  подтверждены рабочими, тестов на `check_update_per_cabinet` не было до этой сессии.
- `lib.rs::get_cabinets` (строка 33-148) — auth-flow: докачка ТОЛЬКО missing/undecryptable
  vaults (69-96). Version-based докачка отсутствовала — это и есть дыра 0.1.2.
- Для 0.2: `has_verified_external_frontend` (lib.rs:2387) вызывает `verify_manifest`
  (signature+checksum проверка), но отбрасывает `ContentManifest.min_core_version` —
  `Ok(_) => true`. Нашёлся готовый кирпич: `updater::is_newer(remote, current)` —
  полное semver-сравнение с prerelease, покрыто тестами, но `fn` приватная (не `pub`).

## Задача 0.1 — проброс vault_versions + вызов сравнения версий

### Пункт 1 (проброс в OnlineAuthStatus)
Статус: УЖЕ СДЕЛАНО в коде до старта сессии. Проверено чтением online_auth.rs:91-166,
338-432. Поле `vault_versions` присутствует в структуре и заполняется во всех ветках.
Правок не вносил (задача была бы нарушением "хирургично" — трогать то, что уже работает).

### Пункт 2 (version-based докачка в lib.rs)
Статус: СДЕЛАНО.
`src-tauri/src/lib.rs:98-118` — новый блок ВНУТРИ `if let Some(ref cv) = online.content_version`,
сразу после блока докачки missing (был до строки 96/97).
Логика: если `online.vault_versions = Some(map)` → вызвать
`content_updater::check_update_per_cabinet(&config_dir, server_versions)`, взять
`files_to_update`, исключить те, что уже попали в `missing` (не дублировать download),
и если остаток непуст → `download_updates(&config_dir, &data_dir, product, cv, &stale, &checksums, Some(&app_handle))`.
Использован единый `cv` (content_version) как `version` для `download_updates` —
для econometrist (один кабинет) это корректно; per-cabinet версии в самом download
не нужны, т.к. `download_updates` сам пишет `set_vault_version` по факту скачивания
каждого файла (content_updater.rs:350-359), используя переданный `version` для ВСЕХ
файлов в батче. Ограничение: если у разных кабинетов на сервере РАЗНЫЕ версии
(map с разными числами), `download_updates` запишет местную версию = `cv` (единая
строка content_version), а не индивидуальный номер из `vault_versions[cabinet]`.
Для Econometrica (один кабинет `econometrist`) это не проблема. Для многокабинетных
продуктов (Agency/Creative Hub) при расхождении версий между кабинетами локальная
запись версии в vault-versions.json будет неточной (общий `cv`, не индивидуальный
номер) — file всё равно скачается правильный (per-file check в check_update_per_cabinet
корректен), просто последующее сравнение версий в vault-versions.json будет use
общий content_version вместо точного номера кабинета. Не усложнял по прямому указанию
задачи ("используй cv, отметь ограничение"). При None (сервер не шлёт vault_versions) —
блок не выполняется, поведение как раньше (регресса нет).

## Задача 0.2 — version-compare внешнего frontend-bundle

Статус: СДЕЛАНО (минимальная защита, механизм оказался очевиден).

Разбор: `verify_manifest()` (crypto/content_sig.rs) УЖЕ возвращает `ContentManifest`
с полем `min_core_version: String` (заполняется при сборке bundle на сервере),
но `has_verified_external_frontend` (lib.rs) отбрасывал результат через `Ok(_) => true` —
подпись+checksum проверялись, а совместимость с текущим .exe — нет.

Правка:
- `src-tauri/src/commands/updater.rs:292` — `fn is_newer` → `pub(crate) fn is_newer`
  (было приватным в модуле `updater`; единственная правка видимости, тело функции
  не тронуто). Функция уже существовала и покрыта тестами (rc-aware semver compare) —
  переиспользована вместо новой копии логики.
- `src-tauri/src/lib.rs:2418-2436` (после правки) — `has_verified_external_frontend`:
  ветка `Ok(manifest)` (было `Ok(_)`) сравнивает `manifest.min_core_version` с
  `env!("CARGO_PKG_VERSION")` через `updater::is_newer(&manifest.min_core_version, core_version)`.
  Если min_core_version бандла новее текущего .exe → бандл несовместим → `return false`
  (embedded используется). Обратный случай (бандл требует core той же версии или старше) —
  совместим, грузится как раньше.

### Что закрывает и что НЕ закрывает эта правка (честно)
Прямой сценарий из постановки ("после обновления .exe с новыми JS-промптами старый
внешний бандл продолжает их перекрывать") этой правкой НЕ закрывается: у старого
бандла min_core_version низкий → `is_newer(старый_min_core, новый_exe)` = false →
бандл пройдёт проверку и продолжит грузиться, поведение не меняется. Правка защищает
ОБРАТНЫЙ и более разрушительный сценарий: сервер публикует OTA-бандл с min_core_version
ВЫШЕ текущего .exe (клиент ещё не обновился) — раньше такой бандл слепо загружался бы
и мог сломать приложение (JS ждёт IPC-команды, которых нет в старом core); теперь
корректно отклоняется.

Для прямого сценария нужен ОБРАТНЫЙ источник истины — "какой номер frontend-бандла
вшит в ТЕКУЩИЙ .exe как embedded" — чтобы сравнивать его с `current_frontend_version.txt`
внешнего OTA и предпочитать embedded, если он новее. Такой константы в кодовой базе
не нашлось: `CARGO_PKG_VERSION` — версия релиза (semver), а `frontend_version` в
online_auth.rs — независимый u32-счётчик бандла (Phase 5). Изобретать сопоставление
"релиз X ⇒ frontend vN" вслепую — риск сломать загрузку frontend, поэтому не делал
(по прямому указанию постановки при неочевидности). Рекомендация на следующий батч:
завести build-time константу (build.rs → env!) с номером frontend-бандла, встроенного
в текущий .exe на момент сборки, сравнивать с `current_frontend_version.txt`. Требует
правки процесса сборки, не только Rust — вне безопасного периметра этой сессии.

## Задача 0.4 — тесты «внести-поймать-откатить»

Разбор: `check_update_per_cabinet` уже была ПОЛНОСТЬЮ покрыта тестами ДО этой сессии
(`content_updater.rs:830-884`, 4 теста: needs_update, up_to_date, no_local_version,
empty_server) — ровно те сценарии, что просило ТЗ (локальная < сервер → в
files_to_update; равная → не кладёт). Дублировать не стал (хирургично, не раздувать).

Добавлено:
- `src-tauri/src/commands/online_auth.rs` (модуль `tests`, после `sample_response()`) —
  два новых теста:
  1. `auth_response_deserializes_vault_versions` — JSON с `vault_versions` десериализуется
     в `AuthResponse.vault_versions`, значения по кабинетам читаются верно.
  2. `auth_response_missing_vault_versions_defaults_none` — старый /auth ответ БЕЗ поля
     `vault_versions` (обратная совместимость, `#[serde(default)]`) → `None`, не паника.

## Гейт

`cargo test` (CARGO_TARGET_DIR=D:/cargo-targets/ai-agency): **190 passed; 0 failed; 1 ignored**
(было 188 до сессии + 2 новых `auth_response_*` теста). Оба новых теста подтверждены
отдельным прогоном (`cargo test auth_response_`) — зелёные.

`cargo clippy -- -D warnings`: **7 ошибок**, но ВСЕ предсуществующие на ветке ДО моих
правок — проверено `git stash` + повторный прогон на чистом дереве (идентичный набор
из 7). Локации: `online_auth.rs:26-28` (doc quote line, комментарий про CACHE_TTL_SECS,
я его не трогал), `report.rs:281` (filter_map→map), `fingerprint.rs:27,31,34`
(map_or→is_some_and). Мои правки (lib.rs, updater.rs:292, online_auth.rs тесты) НЕ
добавили ни одной новой ошибки — нуль-регрессия. Не чинил чужой clippy-долг вне
периметра задачи (правило «хирургично», не запрошено).

## Блокеры вне периметра

- **Серверная часть**: Supabase Edge Function `/auth` (генерация `vault_versions` per-
  cabinet в ответе) — в этом репо кода нет. Клиент готов ЧИТАТЬ и РЕАГИРОВАТЬ на поле,
  но реально доедет обновление только когда сервер начнёт его слать (и слать корректные
  номера версий per-cabinet, не общий content_version).
- **Живой прогон**: изменения не проверены end-to-end против живого Supabase (нет
  доступа/не запрашивалось). `cargo test`/`clippy` гарантируют логику юнитов, но не
  подтверждают реальную доставку правки промпта до установленного клиента.

## Итог diff

`git diff --stat`: 3 файла, +58/-2.
- `src-tauri/src/commands/online_auth.rs` (+21) — 2 новых теста десериализации.
- `src-tauri/src/commands/updater.rs` (+1/-1) — `is_newer` → `pub(crate)`.
- `src-tauri/src/lib.rs` (+37/-1) — version-based докачка vault'ов (0.1.2) +
  min_core_version проверка внешнего frontend (0.2).
