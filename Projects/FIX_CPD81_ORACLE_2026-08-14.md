# CPD-81 в Aurora AI Oracle — отчёт

Дата: 2026-08-14/15. Дерево: `D:\Docs\Aurora_Ai\Dev\_wt_cpd81_oracle` (worktree), ветка `cpd81-oracle-fix`, ответвлена от `cpd77-oracle-fix` (HEAD `da3ee45`). Запись: `4c81b9c91adbafc97a1346fd2308a0249c5b0425`.

## Ветвление — обоснование

Тег `v0.4.5-oracle` (10.08) новее `v0.4.2-oracle` (28.07) по дате записи, но **не является предком `master`** — `master` стоит только на `v0.4.2`. Ветка `cpd77-oracle-fix` содержит `v0.4.5-oracle` как предка и коммит «Версия 0.4.7» — это выпускная ветка, где CPD-77 закрывали напрямую (не отдельной веткой), самое свежее состояние Oracle. Не занята другим worktree на момент старта — ответвился от неё, а не от `master`.

## Таблица носителей

| Файл:строка | Функция | Вердикт |
|---|---|---|
| `campaign.rs:474` | `persist_step_exports` | Полный класс (необратимость: `exports_dir` удаляется `close_session()` следующей строкой) |
| `campaign.rs:494` | `forward_exports_to_inbox` | Пара к предыдущей (необратимости своей нет — источник остаётся в архиве кампании, теряется контекст шага, не файл; эталон закрывает её тем же уровнем строгости) |
| `campaign.rs:527` | `campaign_set_brief` (вынесено в `copy_brief_files`) | Третий носитель класса, без необратимости (источник — файл на диске клиента, `campaign.brief_files` никем не читается обратно) |

Найдено собственным поиском (`let _ = std::fs::copy`, `grep brief`, ручной просмотр всех `fs::copy` в `src-tauri/src`), не только машинной проверкой — третий носитель (файлы брифа) машинная проверка не видит: там нет `read_dir`/`entry.file_type()`, на которые опирается её признак. Прочие `fs::copy` в `lib.rs`, `session/manager.rs`, `commands/brand.rs`, `commands/claude.rs`, `commands/data_migration.rs`, `commands/license.rs`, `commands/vault.rs`, `commands/updater.rs` — все либо пробрасывают `Result` через `?`/`match`/`if let Err`, либо (в `manager.rs:137,485,548`) не в цепочке безусловного добавления в список успеха. Ни один не подпадает под класс CPD-81.

## Что изменено

### `campaign.rs`

1. **`persist_step_exports`** (было `-> Vec<String>`, теперь `-> PersistExportsResult{copied, failed: Vec<(String,String)>, fatal: Option<String>}`):
   - `create_dir_all` каталога назначения — отказ ловится, идёт в `fatal`.
   - `read_dir` каталога выгрузок — отказ ловится, идёт в `fatal` («сохранять было нечего не потому, что файлов нет»).
   - определение типа записи (`entry.file_type()`) — отказ ловится, идёт в `failed`.
   - `fs::copy` — отказ идёт в `failed`, имя НЕ добавляется в `copied`.
   - лог `info!` печатает признак `ОТКАЗ: {reason}`, если `fatal` есть.

2. **`forward_exports_to_inbox`** (было `-> Vec<String>`, теперь `-> ForwardExportsResult{forwarded, failed, fatal}`) — зеркально по структуре, комментарий про НЕ-переименование при совпадении имени (входящие — рабочая папка запуска, не архив) перенесён без изменений.

3. **`campaign_set_brief`**: копирование вынесено в новую функцию `copy_brief_files(brief_dir: &Path, brief_file_paths: &[String]) -> BriefFilesResult{saved, failed}`. `create_dir_all` брифа: отказ — все пути сразу в `failed`. Несуществующий `src_path` — раньше пропускался молча, теперь идёт в `failed` с причиной «исходный файл не найден». `fs::copy` — отказ в `failed`, имя не в `saved`. Без поля `fatal` — осознанное решение эталона (тревога без потребителя обесценивает те, у которых он есть).

Отличия от эталона Econometrica: несущественные — `Mutex::lock().unwrap()` в Oracle используется как `unwrap_or_else(|e| e.into_inner())` (poison-recovery, было в Oracle до меня, не трогал), два теста эталона (`persist_step_exports_rerun_replaces_previous_file_not_versions_it`, `forward_exports_to_inbox_name_collision_overwrites_by_design`) **не перенесены** — они закрепляют поведение `unique_export_path`/анти-версионирование (Medium-5 аудита Econometrica), которого у Oracle никогда не было в первую очередь; перенос этих тестов означал бы либо ложное покрытие несуществующей логики, либо незапрошенный рефакторинг за пределами CPD-81.

### `lib.rs`

- Вызов `forward_exports_to_inbox` (было `fwd.is_empty()`/`fwd.len()` на `Vec<String>`) — адаптирован под структуру: `fwd.forwarded`, добавлены `warn!` на `fwd.failed` и `fwd.fatal` (уровень `warn!`, не `error!` — источник остаётся в архиве кампании).
- Вызов `persist_step_exports` (было `let _files = ...` — результат отбрасывался целиком, даже хуже эталонного Vec<String>) — переименован в `persisted`, добавлены `error!` на `persisted.failed` и `persisted.fatal` **до** `close_session()` (комментарий воспроизведён из эталона — нет промежуточного состояния `emit_wf_status` под частичный неуспех, поэтому минимум — громкий лог).

## Доказательство мутацией (все три носителя)

1. **`persist_step_exports`**: временно `let _ = std::fs::copy(...); result.copied.push(name);` → `cargo test persist_step_exports_copy_failure_recorded_not_lost` → `FAILED`, `assertion failed: result.copied.is_empty()`. Правка возвращена, тест снова зелёный.
2. **`forward_exports_to_inbox`**: временно `let _ = std::fs::copy(...); result.forwarded.push(name);` → `cargo test forward_exports_to_inbox_copy_failure_recorded_not_lost` → `FAILED`, `assertion failed: result.forwarded.is_empty()`. Правка возвращена.
3. **`copy_brief_files`**: временно `let _ = std::fs::copy(...); result.saved.push(name);` → `cargo test copy_brief_files_failed_copy_never_gets_into_saved` → `FAILED`:
   ```
   left: ["занятый.docx", "обычный.md"]
   right: ["обычный.md"]
   ```
   Точное совпадение с эталонным описанием дефекта у Econometrica. Правка возвращена.

## Тесты (10 новых, все в `campaign.rs::tests`)

- `persist_step_exports_copy_failure_recorded_not_lost`
- `persist_step_exports_read_dir_failure_is_fatal_not_silent`
- `persist_step_exports_create_dir_failure_is_fatal`
- `persist_step_exports_success_has_no_fatal`
- `forward_exports_to_inbox_read_dir_failure_is_fatal_not_silent`
- `forward_exports_to_inbox_success`
- `forward_exports_to_inbox_copy_failure_recorded_not_lost`
- `copy_brief_files_failed_copy_never_gets_into_saved` (доказано мутацией)
- `copy_brief_files_missing_source_is_reported_not_skipped_silently`
- `copy_brief_files_success_has_no_failures`

Существующий тест `persist_step_exports_creates_dir` адаптирован под новый тип возврата (`result.copied` вместо `files.len()`), логика не менялась.

## Прогоны

| Момент | Результат |
|---|---|
| База (до правки, `git stash`) | 302 passed / 0 failed / 1 ignored |
| После правки, `campaign::` точечно | 17 passed / 0 failed |
| После правки, полный `cargo test --lib` | **312 passed / 0 failed / 1 ignored** |
| `cargo build --lib` | чисто, 4 предупреждения (все предсуществующие — `confusable_idents` в `updater.rs`, `unused_assignments` в `content_updater.rs`; не мои файлы) |

`CARGO_TARGET_DIR=D:/cargo-targets/oracle`. Каталог `src-tauri/python/` (gitignored, 2267 файлов) отсутствовал в свежем worktree — скопирован из основного дерева через `robocopy /E` (PowerShell), как предупреждал team-lead про грабли с бинарниками вне git.

## Что НЕ закрывает эта правка

- Не трогал `Medium-5`-подобные вопросы версионирования/переименования в Oracle — там их никогда не было, вне области CPD-81.
- Не проверял носители `fs::copy` в `lib.rs`/`session/manager.rs`/прочих командных модулях сверх грепа — они прошли классификацию по чтению кода (все пробрасывают `Result`), но отдельного построчного аудита каждого вызывающего пути (например, корректность обработки `Err` дальше по цепочке) не делал — это за пределами класса CPD-81 (там результат не отбрасывается, только сам факт).
- Не пушил, не сливал с `cpd77-oracle-fix` — работа только в своей ветке `cpd81-oracle-fix`, локальная запись.
- Не собирал полный `.exe`/`svelte-check` — только `cargo build --lib` + `cargo test --lib`, как и просил объём задачи (правка бэкенда).
