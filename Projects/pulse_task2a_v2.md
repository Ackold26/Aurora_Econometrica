# Журнал задачи 2а (повтор) — гонка обновлений vault

## Своими словами
Механизм сетевого обновления зашифрованных файлов содержимого умеет портить данные при
одновременных вызовах: блокировка держит только скачивание, а замена файла с резервной копией
идёт без неё. Нужно сделать связку «скачал → сверил сумму → записал с откатом» неделимой для
одного целевого файла, научить программу подбирать при старте осиротевший `*.vault.bak`, и
починить срез приставки `sha256:` (сейчас режется до приведения к нижнему регистру).

## План
1. Базовый прогон `cargo test` — доказать рабочее окружение и цифру входа (ориентир 386/0).
2. Прочитать `content_updater.rs` (блокировка, `write_vault_with_rollback`, строка 779) и
   четыре точки вызова в `lib.rs`.
3. Задача 1 — область блокировки покрывает запись; сторож на одновременность + мутация.
4. Задача 2 — подбор осиротевшего резерва при старте; сторож + мутация.
5. Задача 3 — срез приставки после нижнего регистра; сторож на оба написания + мутация.
6. Итоговый прогон + поиск по сигнатуре класса дефекта в собственных правках.

## Отметки

- СТАРТ — журнал создан, приступаю к пункту 1.
- Запустила базовый прогон в фоне, вывод идёт в `Projects/gate_2a_baseline.log`. Занимает 3–6 минут.
- Прочитала: `content_updater.rs` строки 676–1029 (замки по адресу, `download_with_retries`,
  `normalize_checksum:779`, `atomic_write_bytes`, `write_vault_with_rollback:833`,
  `download_updates:904`); `lib.rs` строки 40–181 (вызовы 99 и 124), 390–429 (вызов 426),
  590–673 (вызов 646), 3573–3652 (блок `.setup()` — туда пойдёт подбор осиротевшего резерва);
  `vault.rs` (`vaults_dir`, `vault_filename_pub`).
- Базовый прогон завершён, код возврата 0. Файл журнала:
  `D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica_thinwt/Projects/gate_2a_baseline.log`.
  Строка оттуда: `test result: ok. 386 passed; 0 failed; 3 ignored; 0 measured; 0 filtered out;
  finished in 37.28s`. Ориентир 386/0 сошёлся — окружение рабочее.
- Задача 3 сделана в коде: `content_updater.rs::normalize_checksum` теперь сначала приводит строку
  к нижнему регистру, потом срезает приставку. Добавлены два сторожа:
  `normalize_checksum_strips_uppercase_prefix`, `normalize_checksum_strips_mixed_case_prefix`.
- Начинаю прогон по фильтру `normalize_checksum`, ~2 минуты (пересборка крейта).
- Прогон задачи 3 зелёный. Журнал: `Projects/gate_2a_task3_green.log`, строка оттуда:
  `test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 384 filtered out; finished in 0.01s`.
- Мутация задачи 3 проведена: вернула в `normalize_checksum` прежний порядок
  (`strip_prefix(...).to_lowercase()`). Журнал: `Projects/gate_2a_task3_mutant.log`, код возврата 101.
  Краснота по адресу — упали ровно оба новых сторожа, старые остались зелёными:
  `normalize_checksum_strips_uppercase_prefix` и `normalize_checksum_strips_mixed_case_prefix`,
  `panicked at content_updater.rs:2016` и `:2023`, `left: "sha256:abc123" right: "abc123"`,
  итог `test result: FAILED. 5 passed; 2 failed`.
- Мутация откачена, код `normalize_checksum` снова правильный.
- Задача 2 сделана в коде: `content_updater::restore_orphaned_vault_backups` (подбор `*.vault.bak`
  без рабочей пары) + вызов в `lib.rs` в блоке `.setup()` рядом с `migrate_from_legacy`.
  Поведение при двух файлах: оба оставлены, расхождение уходит в журнал. Сторожа — четыре штуки.
- Начинаю прогон по фильтру `orphaned|restore_orphaned|backup_beside`, ~2 минуты.
- Прогон задачи 2 зелёный. Журнал: `Projects/gate_2a_task2_green.log`, строка оттуда:
  `test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 391 filtered out; finished in 0.01s`.
- Мутация 2а проведена (ранний `return 0` — прежнее состояние «подбора нет вовсе»).
  Журнал: `Projects/gate_2a_task2_mutant_a.log`, код возврата 101. Краснота по адресу:
  `orphaned_backup_is_restored_when_working_file_missing`, `panicked at content_updater.rs:2206`,
  `assertion left == right failed: осиротевший резерв обязан вернуться на место, left: 0 right: 1`,
  итог `test result: FAILED. 3 passed; 1 failed`. Откачена.
- Мутация 2б проведена (снята защита «рабочий файл на месте» → резерв подменяет рабочий файл).
  Журнал: `Projects/gate_2a_task2_mutant_b.log`, код возврата 101. Краснота по адресу:
  `backup_beside_working_file_is_left_untouched`, `panicked at content_updater.rs:2226`,
  `assertion left == right failed: рабочий файл на месте — подменять его резервом нельзя,
  left: 1 right: 0`, итог `test result: FAILED. 3 passed; 1 failed`. Откачена.
- Задача 1 сделана в коде: замки по целевому файлу (`vault_write_locks`/`vault_lock_for`),
  функция `store_vault_guarded` (замок → ленивая подготовка → запись с откатом),
  enum `VaultStore`, enum `PrepareFailure` (чтобы отказ шифрования по-прежнему выходил наружу
  сразу, а сетевая неудача копилась в `last_error`), цикл `download_updates` перестроен на них.
  Тестовая пауза `pause_after_backup` вставлена в `write_vault_with_rollback` сразу после
  переименования в резерв; под `#[cfg(not(test))]` она пустая. Сторожа: тест гонки
  `concurrent_updates_of_one_vault_keep_the_reported_contents`, тест выживания кабинета
  `concurrent_failed_updates_leave_the_cabinet_in_place`, `vault_lock_is_keyed_by_target_file`,
  `rejected_preparation_never_touches_the_existing_vault`.
- Начинаю прогон по фильтру гонки, ~3 минуты (крупная пересборка).
- Первый прогон сторожей гонки зелёный: `Projects/gate_2a_task1_green.log`,
  `test result: ok. 7 passed; 0 failed; ... finished in 2.34s` (в фильтр попали и три чужих
  теста со словом concurrent — они не мои).
- Мутация гонки №1 (снят замок в `store_vault_guarded`): `Projects/gate_2a_task1_mutant.log`,
  код возврата 101. Упал `concurrent_updates_of_one_vault_keep_the_reported_contents`
  (`content_updater.rs:2411`, «на диске обязано лежать содержимое того вызова, что доложил
  об успешной записи»). Второй тест гонки при этом остался зелёным.
- 🔴 Находка: второй тест не ловил гонку, потому что при обоих негодных обновлениях откат
  первого возвращает прежний файл. Усилила: добавила вторую тестовую точку паузы
  `pause_before_unguarded_write` (путь «резерва не было», где неудачная запись заканчивается
  удалением файла). Теперь второй тест воспроизводит полную потерю кабинета.
- 🔴 Вторая находка, важнее: тесты писали паузу в ОДНО глобальное поле и затирали друг друга —
  прогон `Projects/gate_2a_task1_mutant2.log` показал красноту второго теста и ЗЕЛЁНЫЙ первый,
  хотя замка не было. То есть сторож плавал по вине обвеса, а не кода. Перевела обе паузы на
  список пар «имя файла → мс», каждый тест ставит и снимает свою запись.
- Прогон после исправления обвеса, замок на месте: `Projects/gate_2a_task1_green2.log`,
  `test result: ok. 7 passed; 0 failed; ... finished in 2.49s`.
- Мутация гонки №2 (замок снова снят, обвес исправлен): `Projects/gate_2a_task1_mutant3.log`,
  код возврата 101. Краснота ОБОИХ сторожей по адресу:
  `concurrent_updates_of_one_vault_keep_the_reported_contents` — `content_updater.rs:2469`,
  «на диске обязано лежать содержимое того вызова, что доложил об успешной записи»;
  `concurrent_failed_updates_leave_the_cabinet_in_place` — `content_updater.rs:2531`,
  «кабинет клиента обязан остаться на диске». Итог `test result: FAILED. 5 passed; 2 failed`.
- Повтор той же мутации: `Projects/gate_2a_task1_mutant3_repeat.log`, снова обе красные
  (`FAILED. 3 passed; 2 failed`) — краснота устойчивая, не случайная.
- Мутация откачена, замок в `store_vault_guarded` на месте.
- Начинаю итоговый полный прогон `cargo test`, ~4 минуты. Следом отдельно clippy (не вместе —
  параллель уже дважды давала средовой отказ в сетевых тестах).
- Первый итоговый полный прогон: `Projects/gate_2a_final_test.log` — `FAILED. 392 passed; 4 failed`,
  упали четыре СЕТЕВЫХ теста `content_updater`. Перепроверила их отдельно
  (`Projects/gate_2a_net_recheck.log`): `ok. 4 passed; 0 failed`. Повторный полный прогон
  `Projects/gate_2a_final_test2.log`: `ok. 396 passed; 0 failed; 3 ignored` — было 386, стало 396,
  ровно +10 моих сторожей.
- clippy: вариант `--all-targets` дал 8 замечаний, ВСЕ в чужих файлах (license.rs, online_auth.rs,
  user_config.rs, durable_store.rs, metrics/collector.rs, sidecar_runtime.rs), в моих — ни одного.
  CI гоняет clippy без `--all-targets`; в этом варианте
  (`Projects/gate_2a_clippy_ci.log`) — 0 замечаний, код возврата 0.
  Отдельно: первый прогон clippy упал на чужом `report.rs` (сосед правил файл 30 секунд назад,
  ошибка `E0061`, к моим правкам отношения не имеет).
- ФИНАЛЬНЫЙ ПРИЁМ выполнен. Сигнатура класса: «решение принимается по состоянию, которое может
  измениться до действия; состояние меняется вне блокировки». Поиск по своим правкам
  (`git diff -U0 | grep '^+' | grep exists/rename/remove_file/write/set_vault_version`) нашёл ДВА
  рецидива в моём же коде:
  (1) `restore_orphaned_vault_backups` — `working_path.exists()`, затем `rename`: появись рабочий
  файл в этой щели, резерв затёр бы его. Закрыла эксклюзивным созданием файла
  (`create_new(true)`), теперь решение не опирается на прочитанное раньше состояние.
  (2) `set_vault_version` в `download_updates` стоял ПОСЛЕ освобождения замка — номер версии
  менялся вне защищённой связки. Втянула под замок через `on_written` в `store_vault_guarded`.
- Контрольная мутация после перестройки: `Projects/gate_2a_task1_mutant4.log`,
  оба сторожа гонки красные (`FAILED. 0 passed; 2 failed`), адреса `content_updater.rs:2529` и `:2603`.
- 🔴 Регресс от МОИХ тестов, найден и починен. Полный прогон
  `Projects/gate_2a_final_test4.log`: `FAILED. 391 passed; 10 failed; finished in 274.23s` — десять
  сетевых тестов `content_updater`, ошибка `error sending request for url (http://127.0.0.1:...)`.
  Зонд причастности: прогон модуля с моими тестами — `Projects/gate_2a_net_recheck2.log`
  (`FAILED. 49 passed; 4 failed`), тот же прогон с `--skip concurrent_` —
  `Projects/gate_2a_net_recheck3.log` (`ok. 51 passed; 0 failed`). То есть виноваты были мои тесты:
  блокирующий сон в потоках рантайма мешал соседним сетевым тестам. Понизила нагрузку:
  `worker_threads` 4 → 2, паузы 400 → 200 мс, задержка старта второго вызова 150 → 80 мс.
  После этого модуль зелёный дважды: `Projects/gate_2a_net_recheck4.log` и `..._recheck5.log`
  (`ok. 53 passed; 0 failed`, 57 с и 37 с).
- Краснота при укороченных паузах проверена трижды подряд: `Projects/gate_2a_task1_mutant5.log`,
  три прогона, все `test result: FAILED. 0 passed; 2 failed` — сторож не стал плавающим.
- ИТОГ. Полный прогон `Projects/gate_2a_final_test5.log`, код возврата 0:
  `test result: ok. 401 passed; 0 failed; 3 ignored; 0 measured; 0 filtered out; finished in 37.23s`
  (401 = 386 на входе + 10 моих + 5 от соседней линии в `report.rs`).
  clippy `Projects/gate_2a_clippy_ci2.log`, код возврата 0, замечаний 0.
- Разбор гонки по факту чтения: замок в `download_with_retries` берётся по АДРЕСУ, а адрес несёт
  `version`/`product`/отпечаток машины. Два вызова разных версий дают разные адреса при одном и том
  же целевом файле — такой замок их не разводит вовсе. Значит ключ замка должен быть целевой файл.
