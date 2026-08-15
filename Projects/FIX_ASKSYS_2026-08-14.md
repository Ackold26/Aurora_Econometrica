# Реализация: снятие зависшего движка спрашивает систему, а не свою запись

Дата: 14–15.08.2026. Продукт: Aurora AI Econometrica.
Основание: `DESIGN_SIDECAR_KILL_2026-08-14.md` (проектное решение), зонд `PROBE_TCPTABLE_2026-08-14.md`.
Ветка: **`sidecar-ask-system`**, рабочая копия `D:\Docs\Aurora_Ai\Dev\_wt_asksys` (ответвлена от `master` `5c34d7a`).
Каталог сборки: `D:/cargo-targets/econ-asksys`.

## 1. Что реализовано

### 1.1 Системный слой — «кто слушает этот порт»

`src-tauri/src/sidecar_runtime.rs`

| Что | Где |
|---|---|
| `listening_port_owners(port) -> Vec<u32>` — публичный вход, заглушка для не-Windows | 461 |
| `win_impl::listening_port_owners_impl` — опрос ОБЕИХ таблиц, AF_INET + AF_INET6 | 900 |
| `win_impl::tcp_table_raw(af)` — двухфазный `GetExtendedTcpTable`, класс `TCP_TABLE_OWNER_PID_LISTENER`, обработка `ERROR_INSUFFICIENT_BUFFER` с повтором до 5 раз | 916 |
| `collect_v4` / `collect_v6` — разбор гибкого массива записей | ниже по файлу |
| `safe_entry_count` — число записей ограничивается тем, что реально прислано, а не только заявленным `dwNumEntries` (чтение за границей буфера в `unsafe` — это порча памяти, а не ошибка разбора) | там же |
| `local_port(raw)` — номер порта из сетевого порядка байт | там же |

Подпроцессов не порождается ни одного. Фичи `windows-sys` добавлены в `src-tauri/Cargo.toml`:
`Win32_NetworkManagement_IpHelper`, `Win32_Networking_WinSock` (версия 0.59 прежняя).

### 1.2 Чистая функция решения

| Что | Где |
|---|---|
| `SkipReason` — новый набор причин отказа (10 штук) | 160 |
| `canonical_path_for_compare(path)` — разрешение коротких имён 8.3 и символических ссылок | 311 |
| `PortHolderFacts<'a>` — снимок фактов для решения | 325 |
| `holder_worth_observing(holders, self_pid)` — первый рубеж ДО наблюдения | 352 |
| `should_kill_port_holder(facts, cfg, current_user)` — решение целиком | 391 |

Функция решения системных вызовов не делает вовсе: и оба перечня держателей, и свойства
процесса, и ожидаемый путь приходят снаружи уже готовыми. Именно поэтому каждая причина отказа
покрывается таблично.

Порядок проверок — ровно как в разделе 3 проекта:

1. держателей нет → `NoListener`; держателей несколько разных → `HolderAmbiguous`;
2. держатель — мы сами → `SelfPid` (до наблюдения, как требует проект);
3. дескриптор не открылся → `ObserveFailed`;
4. владелец неизвестен / чужой → `OwnerUnknown` / `OwnerMismatch`;
5. путь образа неизвестен → `ImageUnknown`; не совпал с движком этой установки →
   `ImagePathNotOurs`; при неизвестном ожидаемом пути — запасная сверка по имени → `ImageMismatch`;
6. переспрос: держатель сменился или исчез → `HolderChanged`;
7. `TerminateProcess` по удерживаемому дескриптору + ожидание выхода.

`holder_worth_observing` вызывается и напрямую системным слоем (для ленивого отсечения до
открытия дескриптора), и первым шагом самого решения — логика живёт в одном месте, не продублирована.

### 1.3 Точка применения

`src-tauri/src/econ_sidecar.rs`

| Что | Где |
|---|---|
| `expected_engine_image_path()` — ожидаемый путь образа из установки; в отладочной сборке `None` | 264 |
| `kill_port_holder(port)` — оркестровка: спросить → отсечь себя → удержать → переспросить → решить → снять | 301 |
| `kill_port_holder` заглушка для не-Windows | 401 |
| `resolve_bundled_exe(app_handle)` — ЕДИНЫЙ источник пути движка для запуска и для сверки | 414 |
| вызов из `start_sidecar` (ветка «рукопожатие не подтвердило наш движок») | 543 |
| вызов из `ensure_alive` (движок принимает TCP, но не отвечает по HTTP) | 688 |
| вызов из `force_restart` | 758 |

Ожидаемый путь берётся из `app_handle.path().resolve(...)` тем же способом, каким движок
запускается: `resolve_bundled_exe` теперь вызывают и `spawn_bundled_exe`, и
`expected_engine_image_path`. Разъехаться этим двум местам нельзя — иначе собственный зомби
перестал бы сниматься молча.

## 2. Что упразднено и чем доказано, что оно стало мёртвым

| Что убрано | Чем доказано |
|---|---|
| `should_kill(state, observed, cfg, user)` целиком | Единственный вызов был в `kill_sidecar_from_state`; тот заменён на `kill_port_holder`. Поиск по `src/` и `tests/` даёт ноль упоминаний |
| `KILL_TIME_TOLERANCE_AFTER_SECS` / `BEFORE_SECS` и вся сверка времени | Использовались только внутри `should_kill` |
| `SkipReason::CreatedOutsideWindow`, `StartedAtUnparsable`, `CreationTimeUnknown`, `ImagePathMismatch` | Порождались только упразднёнными проверками |
| `SkipReason::InvalidPid`, `ProductMismatch`, `StateUserMismatch` | Сверяли ПОЛЯ ФАЙЛА СОСТОЯНИЯ (`pid`, `product`, `user`); файл перестал быть основанием. Пользовательское измерение теперь закрыто строже — сверкой владельца РЕАЛЬНОГО процесса (`OwnerMismatch`), продуктовое — сверкой полного пути образа |
| `kill_sidecar_from_state` (обе редакции — Windows и не-Windows) | Заменена на `kill_port_holder` |
| `kill_known_sidecar` | Была тонкой обёрткой «прочитать файл → снять по записи»; читать файл больше не требуется |
| Medium-8: `stem.starts_with(hint)` для СОБСТВЕННОГО образа продукта | См. раздел 4 |

Проверка на остаточные ссылки (включая комментарии) — пусто:

```
grep -rn "kill_known_sidecar\|kill_sidecar_from_state\|CreatedOutsideWindow\|StartedAtUnparsable\
\|CreationTimeUnknown\|ImagePathMismatch\|KILL_TIME_TOLERANCE\|should_kill(" src/ tests/
```

Единственное найденное упоминание было в шапке сторожа `guard_no_regressed_cpd77_cpd79.rs:12`
(ссылка на имя функции в объяснении) — обновлено на `kill_port_holder`.

**Что НЕ удалено, хотя проект разрешал:**

* `ObservedProcess.created_at` — проект оставил на усмотрение исполнителя. Оставлено: поле
  диагностическое, его снимает тот же единственный `OpenProcess`, и живой тест на нём проверяет,
  что наблюдение вообще работает. Стоимости не добавляет.
* `SidecarState.image_path`, `started_at`, `pid` — остаются в файле состояния как справочные
  (журнал, разбор случая у клиента), как и предписано разделом 4. Комментарии у полей переписаны:
  теперь там прямо сказано, что основанием для снятия они быть перестали.
* `is_our_process_and_user` — была мёртвой ДО моей правки (ни одного вызова в `src/`), поэтому не
  трогала; обновлена только ссылка в её пояснении с `should_kill` на `should_kill_port_holder`.

## 3. Как закрыт риск 1 (расхождение написания пути)

Закрыт в два слоя.

**Слой 1, системный** — `canonical_path_for_compare` (`sidecar_runtime.rs:311`) применяется к
ОБЕИМ сторонам до сравнения: к ожидаемому пути в `expected_engine_image_path` и к наблюдаемому в
`kill_port_holder`. Он разрешает короткие имена 8.3 (`PROGRA~1`), символические ссылки и
относительные звенья — то, что строковой нормализацией не снимается. Если разрешить не удалось,
возвращается исходная строка (отказ безопасный).

**Слой 2, чистый** — `image_path_matches` приводит разделители к `\`, отбрасывает `\\?\` и
`\\?\UNC\`, сравнивает без учёта регистра. Приведение разделителей добавлено этой правкой:
`canonicalize` и `QueryFullProcessImageNameW` дают разные формы.

Текст теста (`sidecar_runtime.rs`, модуль `tests`):

```rust
/// 🔴 Самое вероятное место тихого регресса «зомби перестал сниматься». Прежде обе
/// строки происходили из ОДНОГО источника: путь снимался у живого процесса и им же
/// записывался в файл состояния. Теперь источника два — путь установки и путь
/// запущенного процесса, — и разойтись они могут в написании, оставаясь одним и тем
/// же файлом: префикс `\\?\` (его всегда добавляет `std::fs::canonicalize` и никогда
/// не добавляет `QueryFullProcessImageNameW`), регистр (пути Windows
/// регистронезависимы), разделители.
///
/// Направление отказа здесь БЕЗОПАСНОЕ (зомби просто не снимется), потому и тихое —
/// поймать его может только этот тест.
#[test]
fn kill_our_engine_despite_path_spelling_difference() {
    let holders = [HOLDER];

    let spellings = [
        format!(r"\\?\{OUR_IMAGE}"),
        OUR_IMAGE.to_uppercase(),
        OUR_IMAGE.replace('\\', "/"),
        format!(r"\\?\{}", OUR_IMAGE.to_uppercase()),
        format!("  {OUR_IMAGE}  "),
    ];

    for spelling in &spellings {
        let obs = observed(spelling);
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&obs), &holders, Some(OUR_IMAGE)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Kill,
            "написание «{spelling}» обязано считаться тем же файлом, что и «{OUR_IMAGE}»"
        );

        // И в обратную сторону: разойтись может ожидаемый путь, а не наблюдаемый.
        let obs_plain = observed(OUR_IMAGE);
        assert_eq!(
            should_kill_port_holder(
                &facts(&holders, Some(&obs_plain), &holders, Some(spelling)),
                &KILL_CFG,
                OUR_USER
            ),
            KillVerdict::Kill,
            "ожидаемый путь в написании «{spelling}» обязан совпасть с «{OUR_IMAGE}»"
        );
    }
}
```

Плюс `image_path_matches_normalizes_case_separators_and_verbatim_prefix` (строковый уровень) и
`canonical_path_for_compare_resolves_existing_path_and_survives_missing_one` (системный уровень:
реальный путь канонизируется и по-прежнему совпадает с исходным; несуществующий возвращается как есть).

## 4. Тесты

### 4.1 Что добавлено (20 проверок вместо 18 упразднённых)

**Первый рубеж:** `skip_when_nobody_listens_on_the_port`, `zero_pid_is_not_a_holder`,
`skip_when_holder_is_our_own_shell`, `duplicate_rows_of_one_process_are_one_holder`,
`skip_when_several_different_processes_hold_the_port`.

**Наблюдение и сверка:** `kill_when_holder_is_our_engine`, `skip_when_handle_did_not_open`,
`skip_when_process_owner_is_another_user`, `skip_when_owner_unavailable`,
`skip_when_image_path_unavailable`.

**🔴 Контроль главного дефекта CPD-79:** `skip_foreign_process_holding_our_port` — чужой процесс
того же пользователя, ДЕЙСТВИТЕЛЬНО держащий наш порт, между опросами не менявшийся, отсекается
только полным путём образа. `skip_engine_of_other_product_edition` (High-1) и
`stable_foreign_holder_is_still_not_killed` — рядом.

**🔴 Риск 1:** `kill_our_engine_despite_path_spelling_difference`,
`image_path_matches_normalizes_case_separators_and_verbatim_prefix`,
`canonical_path_for_compare_resolves_existing_path_and_survives_missing_one`.

**🔴 Гонка:** `skip_when_holder_changed_between_probes`, `skip_when_holder_disappeared_between_probes`.

**Запасная сверка:** `kill_dev_python_engine_by_image_name_when_expected_path_unknown`,
`skip_foreign_python_by_image_in_release_config`, `empty_expected_path_falls_back_to_image_name_check`.

**Полнота журнала:** `every_skip_reason_is_reachable_and_distinctly_worded` — все 10 причин
перечислены, ни у двух нет одинакового пояснения, `Display` совпадает с пояснением. Раздел 6
проекта требует, чтобы каждая причина отказа попадала в журнал отдельной формулировкой.

**Живые процессы (только Windows):**
* `listening_port_owners_finds_real_listener` — открывается НАСТОЯЩИЙ слушающий сокет, система
  обязана назвать наш процесс держателем. Доказывает, что системный вызов работает внутри
  продукта, а не только в зонде.
* `listening_port_owners_empty_for_free_port` — обратная сторона: у свободного порта держателей
  нет (без этого предыдущий тест прошёл бы и на функции «верни все процессы машины»).
* `listening_port_owners_finds_ipv6_listener` — 🔴 риск 3, двойной стек (см. 6.1).
* `held_process_observes_and_terminates_real_process` — оставлен без изменений: порождается
  настоящий процесс, снимается по удерживаемому дескриптору.

### 4.2 Упразднённые тесты и чем заменены

| Убран | Почему | Заменён на |
|---|---|---|
| `kill_our_process_created_just_before_state_write`, `kill_our_process_created_slightly_after_state_write` | Проверяли окно времени, которого больше нет | `kill_when_holder_is_our_engine` |
| `skip_when_pid_reused_after_reboot` | Проверял CPD-79 через окно времени | 🔴 `skip_foreign_process_holding_our_port` — тот же дефект, новое основание |
| `skip_when_process_predates_state_file`, `kill_window_boundaries_are_inclusive`, `kill_window_is_asymmetric` | Целиком про окно времени | — (проверяемого поведения больше нет) |
| `skip_when_creation_time_unavailable` | Время создания в решении не участвует | `skip_when_handle_did_not_open` (ObserveFailed) |
| `skip_when_started_at_unparsable`, `started_at_with_timezone_offset_is_normalized` | `started_at` в решении не участвует | — |
| `skip_when_pid_is_zero` | Номер брался из записи; теперь его называет система | `zero_pid_is_not_a_holder` |
| `skip_when_state_belongs_to_another_product` | Файл состояния не основание | `skip_engine_of_other_product_edition` (сверка пути) |
| `skip_when_state_file_belongs_to_another_user` | То же | `skip_when_process_owner_is_another_user` (владелец реального процесса — строже) |
| `skip_foreign_python_by_creation_time_in_dev_config` | Держался на времени создания | — (см. 7.2, честный остаток) |
| `kill_zombie_from_legacy_state_without_image_path` | Про обратную совместимость поля в файле | `kill_dev_python_engine_by_image_name_when_expected_path_unknown` (тот же откат на имя образа) |

Тесты файла состояния (`state_file_roundtrip`, `state_file_without_image_path_reads_with_empty_field`,
`read_state_file_*`) оставлены: роль переподключения у файла сохранена целиком.

### 4.3 Проверка, что тесты СПОСОБНЫ падать (внести-поймать-откатить)

| Внесённый дефект | Кто покраснел |
|---|---|
| Убрана сверка полного пути образа | `skip_foreign_process_holding_our_port`, `skip_engine_of_other_product_edition`, `stable_foreign_holder_is_still_not_killed` (3) |
| Убрано приведение разделителей в `image_path_matches` | `kill_our_engine_despite_path_spelling_difference`, `image_path_matches_normalizes_case_separators_and_verbatim_prefix` (2) |
| Убран переспрос держателя | `skip_when_holder_changed_between_probes`, `skip_when_holder_disappeared_between_probes` (2) |
| Убрана защита от самоубийства | `skip_when_holder_is_our_own_shell` (1) |
| Опрос только IPv4 (риск 3) | `listening_port_owners_finds_ipv6_listener` (1) |
| Возвращён `starts_with` для собственного образа (Medium-8) | `image_matches_does_not_accept_renamed_copies_of_our_engine` (1) |

🔴 Первый прогон мутации «только IPv4» **не поймал никто** — теста на двойной стек не было.
Пробел закрыт добавлением `listening_port_owners_finds_ipv6_listener`, мутация перепрогнана и
поймана. Это единственное место, где мои же тесты пропустили дефект.

## 5. Числа прогонов

| Момент | Основной набор | Сторож CPD-77/CPD-79 |
|---|---|---|
| **База** (`master` `5c34d7a`, до правки) | 453 passed / 0 failed / 3 ignored | 7 passed / 0 failed |
| **После правки** | **458 passed / 0 failed / 3 ignored** | **7 passed / 0 failed** |

Вывод прогона сторожа:

```
test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.07s
```

Сторож зелёный: новый код `netstat`/`findstr`/`tasklist`/`icacls` не порождает — системный вызов
ими не является, а `GetExtendedTcpTable` в списке запрещённых образцов не значится и значиться
не должен.

Сборка чистая: **ноль предупреждений** в отладочном профиле, `cargo check --release` — тоже
ноль ошибок и предупреждений (проверено отдельно: `SIDECAR_IMAGE_HINTS` в релизе компилируется
как пустой список).

**Один прогон был красным по среде.** Полный прогон в момент высокой нагрузки машины дал
11 падений, все в `commands::content_updater::tests` с одинаковым симптомом
`error sending request for url (http://127.0.0.1:96xx/file)` — клиент не смог подключиться к
собственному тестовому серверу. Доказано, что это среда, а не правка: точечный прогон в один
поток дал **53 passed / 0 failed**, повторный полный прогон — 0 падений. Порты у этих тестов
эфемерные (`bind("127.0.0.1:0")`), коллизии с соседними агентами по номеру порта нет; причина —
голодание асинхронного планировщика под нагрузкой. Мой код `content_updater` не касается.

## 6. Найденное в проекте

Фактических ошибок («код так не работает, вызов такого не даёт») в проекте **не найдено** —
описанный алгоритм реализуем ровно как написан, вызовы ведут себя как заявлено зондом.
Найдены три неполноты, каждая потребовала решения:

### 6.1 Проект предполагает ОДНОГО держателя порта

Раздел 3 пишет `держатель = слушатель_порта(port)` в единственном числе. На деле
`GetExtendedTcpTable` может вернуть несколько записей на один номер порта, принадлежащих РАЗНЫМ
процессам (двойной стек: один держит `0.0.0.0:N` по IPv4, другой `[::]:N` по IPv6). Проект не
говорит, какого из них снимать.

**Решение:** введена отдельная причина отказа `HolderAmbiguous` — при нескольких разных
держателях не снимаем никого. Направление отказа безопасное (порт удержан → `allocate_port`
возьмёт свободный), а альтернатива — угадывать, кого убить, то есть ровно тот дефект, ради
которого всё делается. Записи ОДНОГО процесса (движок может попасть в таблицу дважды) при этом
схлопываются и держателем остаётся один — иначе снятие сломалось бы на пустом месте.

Штатно неоднозначности нет: движок слушает `127.0.0.1` (`sidecar/econometrica/server.py:2956`),
то есть даёт ровно одну запись IPv4.

### 6.2 Проект не заметил ещё две точки вызова

Раздел проекта называет точкой применения только `start_sidecar:484-492`. Но снятие зомби шло
через `kill_known_sidecar`, а её вызывают ещё `ensure_alive` (движок принимает TCP, но молчит по
HTTP) и `force_restart`. Пока эти две точки опираются на `should_kill`, упразднить окно времени
по разделу 4 **невозможно** — константы остались бы живыми.

**Решение:** переведены на новую конструкцию обе. Это не расширение задачи, а её минимальное
условие: обе точки вызываются под `if tcp_responsive(port)`, то есть снимают ровно держателя
порта — новая конструкция подходит им точнее прежней.

### 6.3 Medium-8 закрыт проектом только на основном пути

Раздел 4 объявляет Medium-8 (`stem.starts_with(hint)`) упразднённым, обосновывая это тем, что
сравнение идёт по полному пути. Верно для основного пути. Но запасной путь — сверка по имени
образа при неизвестном ожидаемом пути — остался, и `starts_with` в нём жил: под него подпадали
`econometrica-sidecar-backup.exe`, `econometrica-sidecar-old.exe` и любая переименованная копия
рядом с движком.

**Решение:** совпадение по началу имени оставлено ТОЛЬКО для сторонних интерпретаторов
(`extra_image_hints`, где оно и было нужно: `python` ↔ `python3` отличаются суффиксом), для
собственного образа продукта сверка строгая. Тест
`image_matches_does_not_accept_renamed_copies_of_our_engine`, мутация проверена.

### 6.4 Побочное наблюдение (не правила)

Раздел 4 объявляет Medium-9 («файл состояния стирается даже когда снять не решились») отпавшим.
Подтверждаю: `delete_state_file` после `kill_port_holder` в `start_sidecar` остался безусловным,
и это теперь безвредно — опознание зомби от файла не зависит, систему можно спросить при любом
следующем запуске. Код не трогала.

## 7. 🔴 Чего эта правка НЕ закрывает

### 7.1 Не проверено вживую

* **Живое воспроизведение сценария «падение → перезагрузка → переиспользование номера»** — как и
  раньше, руками не воспроизводится. Проверено только тестами.
* **Kaspersky против этих правок не проверялся ни разу.** Правка уменьшает число порождаемых
  процессов (разведка исчезла совсем), но поведенческий вердикт антивируса — эмпирический факт,
  а не следствие рассуждения.
* **Настоящий зомби-движок на настоящей машине не снимался.** Живые тесты доказывают, что
  система называет держателя порта и что процесс снимается по удерживаемому дескриптору, — но
  это два разных теста, а не один сквозной прогон «зомби-движок занял порт → снят».
  Сквозной прогон — за приёмкой ведущего.
* **RDP / несколько пользователей на одной машине** — сверка владельца покрыта только таблично.
* **Установка с длинным путём, коротким именем 8.3 или на сетевом диске** — канонизация покрыта
  тестом на существующем пути, но на настоящей установке с `PROGRA~1` не проверялась.

### 7.2 Осознанно оставленные слабости

* **Отладочная сборка стала мягче.** Раньше чужой `python.exe` в отладочной сборке отсекался
  временем создания; теперь при неизвестном ожидаемом пути сверка идёт по имени образа, а
  `SIDECAR_IMAGE_HINTS` в отладочной сборке содержит `python`/`pythonw`. То есть чужой Jupyter,
  ДЕРЖАЩИЙ наш порт, в отладочной сборке будет снят. Это прямо следует из риска 2 проекта.
  Отладочные сборки клиентам не уезжают, в релизе список пуст и сверка идёт по полному пути.
* **Релизная сборка без собранного движка** (`resolve_bundled_exe` вернул `None`) откатывается на
  сверку по имени образа с пустым списком дополнительных имён — снимется только процесс с именем
  ровно `econometrica-sidecar.exe`. Направление безопасное.
* **`stop_sidecar` по-прежнему снимает деревом** через порождение системной утилиты
  (`econ_sidecar.rs`, ветка `graceful == false`). Гонки номера там нет (процесс держится как
  `Child`), но поведенческий образец для антивируса остался. Проект это прямо оставил за
  границей (раздел 9), не трогала.
* **Запасной путь `kill_process_tree_fallback`** тоже порождает системную утилиту — оставлен по
  разделу 5 проекта, срабатывает только при отказе `TerminateProcess`.
* **`HolderAmbiguous` может помешать снять своего зомби** на машине, где посторонний процесс
  занял тот же номер порта в другом семействе адресов. Редко, отказ безопасный, в журнале виден
  отдельной формулировкой.

### 7.3 Не сделано намеренно

* **Перенос в Docs Lab и Smart Analytica** — отдельная задача ПОСЛЕ приёмки (раздел 8 проекта).
  `sidecar_runtime.rs` объявлен каноническим файлом для 10 продуктов и синхронизируется через
  `sync_variants.py`; в этой ветке изменён только экземпляр Econometrica.
* **Слияние в `master`, отправка на сервер** — не делались, как и предписано.

## 8. Запись

* Ветка: **`sidecar-ask-system`**
* Хеш записи: **`17a6a24`**
* Файлы: `src-tauri/Cargo.toml`, `src-tauri/src/sidecar_runtime.rs`,
  `src-tauri/src/econ_sidecar.rs`, `src-tauri/tests/guard_no_regressed_cpd77_cpd79.rs`
* Все четыре добавлены поимённо. Запись трогает ровно эти файлы и никакие другие
  (`git show --stat HEAD`).
* 🔴 **`master` за время работы ушёл вперёд** — на момент сдачи там `ea4d31d`
  («частичная потеря результатов шага доходит до человека»), моя ветка ответвлена от `5c34d7a`,
  как и было предписано. Сведение — за ведущим; пересечений по файлам с `ea4d31d` мои правки не
  имеют (`sidecar_runtime.rs`, `econ_sidecar.rs`, сторож, `Cargo.toml`).
* Не отправлялось на сервер, не сливалось.
