# Правка CPD-81 в Docs Lab (ROSST_AI_DocMaster)

Дата: 14.08.2026. Дерево: `D:\Docs\Aurora_Ai\Dev\_wt_cpd81_docslab` (worktree),
ветка `cpd81-docslab-fix`.

## Носители класса — поиск по всему `src-tauri/src/`

Поиск `grep -rn "let _ = std::fs::copy"` по всему `src-tauri/src/` дал ровно 3 совпадения
на момент старта — все в `src-tauri/src/commands/campaign.rs`:

| Строка (до правки) | Функция | Вердикт |
|---|---|---|
| 458–498 (сама функция) | `persist_step_exports` | **Уже вылечена** до меня (записи `e26f2c8`/`acf82f2`). Проверила фактом: возвращает `Vec<String>` без структуры-результата, но `match std::fs::copy(...)` честен — имя попадает в `copied` только при успехе, отказ идёт `warn!`. Отдельно обработан отказ `create_dir_all` (ранний возврат `Vec::new()`). Это более простой уровень, чем финальный эталон Эконометрики (нет `fatal`, нет различения `read_dir`/`file_type()`), но сама ложь списка закрыта. Не трогала — вне рамок задачи (команда прямо указала считать её вылеченной и перепроверить, не чинить заново).
| 510 | `forward_exports_to_inbox` | **Была НЕ вылечена** — чистый CPD-81: `let _ = std::fs::copy(entry.path(), inbox.join(&name)); forwarded.push(name);`. Починена этой правкой.
| 543 | `campaign_set_brief` (копирование файлов брифа) | Тот же низкоуровневый паттерн (`saved_files.push(...)` безусловно), но **не полный класс CPD-81** — см. разбор ниже. Починена минимально.

Других носителей (по образцу `let _ = std::fs::copy` и по спискам «сохранено/передано» —
проверила также `std::fs::rename`, отдельного грепа на подобные конструкции с переносом
имени в список без проверки результата не нашла) в `src-tauri/src/` нет.

## Правка 1 (основная): `forward_exports_to_inbox`

`src-tauri/src/commands/campaign.rs`. Новая сигнатура — точная копия эталона Эконометрики
(запись `68b30be`, финальное состояние в `campaign.rs` дерева thinwt строки 598–686):

```rust
#[derive(Debug, Default)]
pub struct ForwardExportsResult {
    pub forwarded: Vec<String>,
    pub failed: Vec<(String, String)>,
    pub fatal: Option<String>,
}

pub fn forward_exports_to_inbox(
    prev_exports_dir: &Path,
    next_workspace: &Path,
) -> ForwardExportsResult
```

Закрыты все четыре проглоченных пути отказа:
1. `create_dir_all(&inbox)` — отказ → `fatal`, перебор не обрывается (копирование
   отдельных файлов может ещё пройти при гонке).
2. `read_dir(prev_exports_dir)` — отказ → `fatal`, пустой `forwarded` перестаёт
   читаться как «передавать было нечего».
3. `entry.file_type()` — отказ идёт в `failed` поимённо (тип записи неизвестен —
   молча пропустить нельзя, это может быть искомый файл).
4. `fs::copy` — сам исходный дефект: отказ теперь в `failed`, НЕ в `forwarded`.

Отличий от эталона по существу нет — код скопирован дословно (имена полей, структура,
порядок проверок, тексты предупреждений на русском по образцу). Единственное
техническое отличие: в Docs Lab нет отдельного файла-сторожа
`tests/guard_no_regressed_cpd77_cpd79.rs` — только один тестовый бинарь `lib.rs`.

## Вызывающий — `lib.rs:2939`

Единственный вызывающий (пайплайн, передача выгрузок между шагами воркфлоу). До правки:

```rust
let fwd = commands::campaign::forward_exports_to_inbox(&last.path(), &work_dir);
if !fwd.is_empty() {
    info!("Forwarded {} files to {}", fwd.len(), cabinet_id);
}
```

После — разобраны все три поля, по уровню журнала как в эталоне (`warn!`, не `error!`:
источник остаётся в архиве кампании `campaign_dir/steps/<шаг>`, его на этом пути никто
не удаляет — теряется контекст следующего шага, не результат работы клиента):

```rust
let fwd = commands::campaign::forward_exports_to_inbox(&last.path(), &work_dir);
if !fwd.forwarded.is_empty() {
    info!("Forwarded {} files to {}", fwd.forwarded.len(), cabinet_id);
}
if !fwd.failed.is_empty() {
    let names: Vec<&str> = fwd.failed.iter().map(|(n, _)| n.as_str()).collect();
    warn!("Не переданы во входящие [{cabinet_id}] {} выгрузок: {}", fwd.failed.len(), names.join(", "));
}
if let Some(reason) = &fwd.fatal {
    warn!("Передача выгрузок во входящие [{cabinet_id}] не состоялась: {reason}");
}
```

Других вызывающих `forward_exports_to_inbox` в кодовой базе нет (проверено грепом по
всему `src-tauri/src/`).

## Правка 2 (третий носитель): `campaign_set_brief` — строка ~543 (была)

**Вердикт: тот же низкоуровневый паттерн, но НЕ полный класс CPD-81.**

Совпадает с CPD-81: `saved_files.push(name.to_string_lossy().to_string())` шло
безусловно после `let _ = std::fs::copy(src, brief_dir.join(name))` — список
`campaign.brief_files` мог лгать о том, что реально лежит в `brief-files/`.

Не совпадает с CPD-81 по определяющему признаку — **необратимости**:
- Источник (`src_path`) — путь на диске пользователя вне рабочей папки продукта
  (выбирается нативным диалогом). После отказа копирования он никуда не девается:
  ни один код на этом пути его не удаляет. Это принципиально отличается от
  `persist_step_exports`/`forward_exports_to_inbox`, где следом стирается рабочая
  папка (`close_session`) или где список идёт основанием считать пайплайн
  выполненным.
- `campaign.brief_files` сейчас **нигде не читается обратно**: проверила грепом
  `brief_files|brief-files|brief_dir` по всему `src/` (фронтенд) и `src-tauri/src/`
  (бэкенд) — единственное дополнительное упоминание, `lib.rs:2780`
  `let _brief_files_dir = campaign_dir.join("brief-files");`, явно помечено
  подчёркиванием как неиспользуемая переменная, с комментарием «will be handled
  during execution» — то есть фича чтения брифа из файлов не реализована, список
  сейчас decorative, живого потребителя лжи нет.

Раз консеквенции сегодня нет, но паттерн тот же и дешёв к починке — закрыла его тем же
уровнем, что уже применён в этом файле к `persist_step_exports` (честный список без
структуры-результата, `warn!` на отказ), **без** введения `ForwardExportsResult`-подобной
структуры — это было бы избыточно для функции, у которой нет соседнего необратимого шага,
который нужно предварять журналом:

```rust
match std::fs::copy(src, brief_dir.join(name)) {
    Ok(_) => saved_files.push(name.to_string_lossy().to_string()),
    Err(e) => warn!(
        "Кампания {campaign_id}: файл брифа «{}» не сохранён в {} ({e})",
        name.to_string_lossy(), brief_dir.display()
    ),
}
```

**Без теста.** `campaign_set_brief` — полноценная `#[tauri::command]`, путь берётся из
`campaigns_dir()` → `campaigns_root()` → `user_config::results_root()`, который указывает
на реальный `%USERPROFILE%\Desktop\Aurora_AI\...` пользователя (не инжектируется,
не мокается). Юнит-тест на неё писал бы (или читал) в настоящую пользовательскую папку —
это либо загрязнение реального каталога результатов, либо рефакторинг `campaigns_dir`
под внедряемый корень, а это уже не хирургическая правка CPD-81, а отдельная задача по
тестируемости команды. Оставила без теста, зафиксировав это ограничение здесь и в
итоговом списке ниже.

## Изменённые вызывающие (полный список — смена возвращаемого типа меняет договор)

`forward_exports_to_inbox`: единственный вызывающий — `lib.rs:2939` (см. выше). Больше
никто в кодовой базе эту функцию не вызывает (проверено грепом).

`persist_step_exports` и `campaign_set_brief` возвращаемый тип не меняли — договор
прежний, вызывающих не трогала (кроме тела `campaign_set_brief`, где сигнатура снаружи та
же — `Result<Campaign, String>`).

## Тесты (4, не 5 — ось мутации проверена не отдельным тестом)

Добавлены в `campaign.rs::tests`, идиома этого файла (не эталона Эконометрики буквально):
для «чистого» отказа копирования (без примеси отказа `create_dir_all`) здесь уже
принят приём с реальной эксклюзивной блокировкой файла (`crate::session::manager::
open_session_lock`, Windows-only, `share_mode(0)`) — именно так уже был написан
`failed_copy_never_gets_into_the_persisted_list` для `persist_step_exports` до меня.
Использовала тот же приём вместо приёма эталона «занять место каталогом файлом»
(тот конфликтует сразу с `create_dir_all` и не даёт чистого сценария «только copy
отказал»).

1. `forward_exports_to_inbox_success` — штатный путь: `forwarded` содержит имя,
   `failed`/`fatal` пусты, файл реально лежит в `next_workspace/inbox`.
2. `failed_copy_never_gets_into_the_forwarded_list` (`#[cfg(windows)]`) — отказ
   копирования: `inbox` создан заранее, целевой файл заблокирован
   (`open_session_lock`, эксклюзивно), второй файл рядом копируется штатно. Имя
   заблокированного НЕ в `forwarded`, ЕСТЬ в `failed`; второй файл — в `forwarded`
   (один отказ не топит остальные); источник в архиве кампании цел. Комментарий над
   тестом содержит ось мутации.
3. `forward_exports_to_inbox_read_dir_failure_is_fatal_not_silent` — каталог-источник
   подменён обычным файлом → `read_dir` падает → `fatal` непуст, `forwarded`/`failed`
   пусты (поимённого списка здесь и не может быть).
4. `forward_exports_to_inbox_create_dir_failure_is_fatal` — каталог входящих подменён
   файлом, источник **намеренно отсутствует** (не создан вовсе), поэтому перебор
   файлов не выполняется — `fatal` непуст, `failed` чисто пуст (в отличие от
   `persist_step_exports_create_dir_failure_is_fatal` эталона, где `failed` тоже
   непуст из-за смешения сценариев). Это даёт по-настоящему изолированный сигнал
   именно на отказ `create_dir_all`.

## Доказательство мутацией

Временно вернула в `forward_exports_to_inbox` дефектный образец:
```rust
let _ = std::fs::copy(entry.path(), inbox.join(&name));
result.forwarded.push(name);
```
вместо `match { Ok(_) => ..., Err(e) => ... }`. Точечный прогон:

```
cargo test --manifest-path src-tauri/Cargo.toml --lib failed_copy_never_gets_into_the_forwarded_list
```

Результат — тест красный:
```
test commands::campaign::tests::failed_copy_never_gets_into_the_forwarded_list ... FAILED
thread '...' panicked at src-tauri\src\commands\campaign.rs:961:9:
файл, который не удалось передать, попал в список переданных: ["второй.md", "занятый.docx"]
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 393 filtered out
```
Полный журнал: `Projects/cpd81_mutation_proof.log` (в рабочей копии). После — правка
возвращена, полный прогон подтвердил восстановление (см. ниже).

## Числа прогонов

- `CARGO_TARGET_DIR="D:/cargo-targets/docs-lab"` (не `ai-agency` — та занята параллельной
  работой по прямому запрету команды). Один тестовый бинарь (`lib.rs`), нет отдельного
  файла-сторожа в `tests/` (в отличие от Эконометрики).
- **До правки** (`Projects/cpd81_baseline_test.log`): `unittests src\lib.rs` — **389
  passed; 0 failed; 1 ignored**. `main.rs` — 0 тестов. Doc-tests — 0 passed, 1 ignored.
- **После правки** (`Projects/cpd81_after_fix_test.log`): **393 passed; 0 failed;
  1 ignored** — ровно +4 (мои новые тесты), ни одного упавшего и ни одного пропавшего.
- **После возврата от мутационной проверки** (`Projects/cpd81_final_test.log`): та же
  цифра — **393 passed; 0 failed; 1 ignored** — восстановление подтверждено.
- Компилятор: 2 предупреждения (`unused variable: is_check`, `value assigned to
  last_response_text is never read`) — присутствовали уже в базовом прогоне до моих
  правок (проверила: те же строки, `lib.rs:1239` и `lib.rs:1304`), не мои. Новых
  предупреждений правка не добавила.

## Ветка

Ответвилась от `feat/rag-core-adopt` — установлено фактом: `git tag --sort=-creatordate`
дал последней меткой Docs Lab `v0.12.4-docs-lab`; `git branch --contains v0.12.4-docs-lab -a`
вернул единственную ветку — `feat/rag-core-adopt` (плюс её remote-копию). Остальные локальные
ветки (`cpd77-docslab-fix`, `feat/model-backend-poc`, `fix/dm-resilient-download`,
`fix/docslab-cpd44-resume-fallback`, `fix/docslab-probe-local`, `master` и др.) эту метку не
содержат — неоднозначности не было, выбор единственный.

Рабочая копия: `D:/Docs/Aurora_Ai/Dev/_wt_cpd81_docslab` (создана через `git worktree add`,
основное дерево `ROSST_AI_DocMaster` не трогала — там ветка `feat/rag-core-adopt` с 38
незаписанными файлами, работать в ней было запрещено).

Ветка: `cpd81-docslab-fix`, ответвлена от `feat/rag-core-adopt@5238b20`.

Хеш записи: `9fce428` (проверено: `git log -1 --oneline` и `git status` после коммита —
запись легла, рабочее дерево чистое).

## Чего правка НЕ закрывает

1. **`persist_step_exports` не приведена к полному уровню эталона** (нет `fatal`, нет
   различения `read_dir`/`file_type()`-отказов) — она уже честна по главному критерию
   (список не лжёт), и команда прямо просила её не трогать повторно, а перепроверить
   факт. Довести её до полного эталона High-4 — отдельная, не запрошенная сейчас правка.
2. **`campaign_set_brief` (файлы брифа) не покрыта тестом** — см. обоснование выше
   (реальный `%USERPROFILE%`, не мокается без отдельного рефакторинга).
3. **UI/интерфейс не получает сигнала о неполной передаче** — только журнал (`warn!`),
   как и в эталоне для этой же функции. Видимый пользователю индикатор частичного
   переноса контекста между шагами — отдельная UX-задача поверх `emit_wf_status`.
4. **Ветка `cpd77-docslab-fix` и её рабочая копия не тронуты** — отдельный незакрытый
   регресс, вне рамок этой задачи, по прямому указанию команды.
5. Других носителей класса CPD-81 (по образцу `let _ = std::fs::copy` с последующим
   безусловным добавлением в список) в `src-tauri/src/` не нашла — поиск был по всему
   дереву, не только по указанным файлам.
