# Пульс: CPD-81 в Docs Lab (2026-08-14)

## Задача своими словами
В `ROSST_AI_DocMaster` (`src-tauri/src/commands/campaign.rs`) есть класс дефекта CPD-81: `let _ = std::fs::copy(...)` глотает отказ копирования, а имя файла всё равно попадает в список «успешно передано» — вызывающий код и журнал не узнают о потере, следом рабочий каталог удаляется. `persist_step_exports` уже вылечена (по записям e26f2c8/acf82f2) – нужно проверить. `forward_exports_to_inbox` – НЕ вылечена, лечить по эталону Эконометрики (`ForwardExportsResult{forwarded,failed,fatal}`). Плюс разобрать подозрительную строку ~543 (третье copy) – тот ли класс.

## План
1. Изучить эталон Эконометрики (записи 1414259, 5457a89, 68b30be) + разборы FIX_AUDIT249/FIX_CPD81_FORWARD в дереве thinwt.
2. Прочитать `campaign.rs` в Docs Lab целиком: обе функции + окрестность строки 543 + все вызывающие.
3. grep по всему src-tauri на образец `let _ = std::fs::copy` и списки «сохранено/передано».
4. Установить факт: выпускная ветка (git tag + git branch --contains).
5. Создать git worktree `_wt_cpd81_docslab` с новой веткой `cpd81-docslab-fix` от выпускной ветки.
6. Прогнать базовые тесты ДО правки, зафиксировать число.
7. Внести правку в forward_exports_to_inbox (+ строку 543 если тот же класс), обновить всех вызывающих.
8. Написать 5 тестов (отказ copy, read_dir, create_dir_all, штатный путь, мутационный тест с осью мутации).
9. Прогнать тесты, доказать мутацией (временно вернуть дефект → тест падает → зафиксировать вывод → вернуть правку).
10. Записать отчёт FIX_CPD81_DOCSLAB_2026-08-14.md.
11. Отчитаться сжато команде.

## Отметки
- [старт] 2026-08-14 – пульс создан, начинаю изучение эталона и кода.
- Изучен эталон полностью: 1414259 (persist_step_exports), 5457a89 (forward_exports_to_inbox первая правка), 68b30be (High-4: fatal, три пути отказа, Medium-5). Финальный образец функции — в текущем campaign.rs thinwt (строки 598-686).
- Docs Lab campaign.rs прочитан: persist_step_exports (458-498) — ДЕЙСТВИТЕЛЬНО вылечена (свой, более простой уровень: Vec<String>, warn! на отказ copy, ранний возврат на create_dir_all, БЕЗ fatal-поля и без различения read_dir/type-отказов — работающий, но неполный вариант эталона). forward_exports_to_inbox (501-517) — НЕ вылечена, чистый CPD-81. Строка ~543 (campaign_set_brief, saved_files.push безусловно) — тот же низкоуровневый паттерн (список лжёт), НО источник после отказа НЕ удаляется (файл с диска пользователя никуда не девается) и `brief_files` сейчас нигде не читается downstream (`_brief_files_dir` в lib.rs:2780 — с подчёркиванием, неиспользуемая; фича "will be handled during execution" не реализована). Решение: тот же класс низкоуровнево, но не полный CPD-81 (нет необратимости) — починю минимально (честный список, без push при отказе + warn!), без структуры-результата и без теста (campaign_set_brief бьёт по реальному APPDATA через campaigns_root(), не тестируется дёшево без рефактора вне рамок задачи).
- Выпускная ветка установлена фактом: только `feat/rag-core-adopt` содержит метку v0.12.4-docs-lab (остальные — нет). Worktree создан: D:/Docs/Aurora_Ai/Dev/_wt_cpd81_docslab, ветка cpd81-docslab-fix, от feat/rag-core-adopt@5238b20.
- Базовый прогон ДО правки: 389 passed; 0 failed; 1 ignored (lib.rs unittests), main.rs 0 тестов, doc-tests 0/1 ignored. Один тестовый бинарь (нет отдельного guard-файла в tests/, в отличие от Эконометрики).
- Правка внесена: forward_exports_to_inbox → ForwardExportsResult{forwarded,failed,fatal} по эталону 68b30be (три пути отказа: create_dir_all, read_dir, entry.file_type(), плюс сам copy). Вызывающий lib.rs:2939 обновлён (forwarded/failed/fatal, warn! перед продолжением). Третий носитель campaign_set_brief (строка ~608) починен минимально (честный список + warn!, без структуры-результата — не тот же уровень необратимости, обоснование в отчёте).
- Добавлено 4 теста (не 5 отдельных — ось мутации проверяется на тесте пункта 1 как в идиоме этого файла, см. failed_copy_never_gets_into_the_persisted_list): success / read_dir failure / create_dir failure / copy failure (windows-only, через open_session_lock, тот же приём что уже в файле).
- Прогон после правки: 393 passed; 0 failed; 1 ignored (+4 от базы 389, ровно новые тесты). Предупреждения компилятора (2: is_check, last_response_text) — те же, что были в базовом прогоне, не мои.
- Доказательство мутацией: временно вернула дефектный образец (`let _ = std::fs::copy(...); result.forwarded.push(name);`) в forward_exports_to_inbox. Точечный прогон `failed_copy_never_gets_into_the_forwarded_list` → FAILED, паника: "файл, который не удалось передать, попал в список переданных: [\"второй.md\", \"занятый.docx\"]" (campaign.rs:961). Правку вернула, лог сохранён в cpd81_mutation_proof.log.
- Финальный прогон подтвердил восстановление: 393 passed; 0 failed; 1 ignored.
- Запись изменений сделана поимённым git add (campaign.rs, lib.rs, 4 лог-файла) → коммит 9fce428 в ветке cpd81-docslab-fix. Проверено git log -1 + git status (working tree clean).
- Отчёт FIX_CPD81_DOCSLAB_2026-08-14.md дописан целиком, хеш вставлен.
- ЗАДАЧА ЗАВЕРШЕНА. Отчитываюсь команде.
