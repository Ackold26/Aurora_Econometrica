# Отчёт: правки по внешнему аудиту s46 (обращение через форму)

Файлы: `src-tauri/src/commands/feedback.rs`, `src-tauri/src/commands/execution_mode.rs`,
`src/lib/feedback.js`, `src/lib/program-help.js`, `src/lib/updateErrorText.js`,
`src/lib/updateErrorText.guard.test.js`, `src/lib/__tests__/program-help.test.js`,
`src/routes/settings/+page.svelte`, `src-tauri/help-econometrica/error-codes.html`,
`src-tauri/src/commands/updater.rs`, `src-tauri/src/lib.rs`.

## 1. [ВЫСОКАЯ] Вычистка пути рвётся на пробеле

`sanitize_error_text` / `path_pattern` (`feedback.rs:109-142`). Стоп-класс `\s"'()<>` заменён
на `"'()<>,\r\n` (пробел разрешён, добавлены запятая/переводы строки); первая альтернатива
паттерна расширена до `[A-Za-z]:[\\/]` (прямой и обратный слеш). Замена сделана через
`replace_all` с замыканием: хвостовой знак препинания (`.,;:!?`) на конце совпадения
отрезается от «пути» и остаётся ПОСЛЕ метки `[путь]`, не поглощается.

Доказано новым тестом `sanitize_error_text_handles_space_slash_unc_quote_and_trailing_punct`
(`feedback.rs`), дословный вывод (`cargo test` — 12/12 в модуле, включая старый
`sanitize_error_text_scrubs_windows_path`):

```
1. пробел:   "не удалось открыть C:\Users\Иван Петров\Documents\отчёт.xlsx"
             → "не удалось открыть [путь]"                    (Петров не утёк)
2. слеши:    "не удалось открыть D:/Docs/Users/Анна/data/план.csv"
             → "не удалось открыть [путь]"                    (Анна не утекла)
3. UNC:      "нет доступа \\SERVER\Общая папка\Иванова\план.xlsx"
             → "нет доступа [путь]"                            (Иванова не утекла)
4. кавычки:  "см. \"C:\Users\Anna\file.xlsx\" подробнее"
             → "см. \"[путь]\" подробнее"                      (Anna не утекла, кавычки на месте)
5. точка:    "не удалось открыть C:\Users\Иван\file.xlsx."
             → "не удалось открыть [путь]."                    (точка осталась ПОСЛЕ метки)
```

## 2. [ВЫСОКАЯ] Подпись «Сейчас: …» называла 4 поля из 7

`HEADLINE_LOCAL` (`execution_mode.rs:241`). Дописаны три недостающих поля: версия Windows,
шаг мастера, текст последней ошибки — с явной оговоркой, что шаг и текст ошибки едут ТОЛЬКО
при нажатии «Сообщить о проблеме» в окне ошибки. Заодно поправлены два настоящих перевода
строки `\n    ` внутри той же строковой константы (находка №3 того же аудита, тот же литерал)
— заменены на обычные пробелы, литерал теперь продолжается только через `\` в конце строки, как
и выше в той же константе. Длинного тире не использовано (проверено `grep '—'` — 0 совпадений
в самой подписи).

Новый текст: «Сейчас: материалы не покидают эту машину – ИИ-ассистент отключён. Наружу уходят
только проверка лицензии, обновления программы и докачка содержимого кабинетов и оболочки.
Отдельно: форма обращения в поддержку открывается в браузере по вашему нажатию – в неё
программа подставляет название, версию, отпечаток машины, время и версию Windows, а при
нажатии «Сообщить о проблеме» в окне ошибки – ещё и шаг мастера с текстом ошибки.»

Сторож `guard_left_position_egress` прогнан после правки: **22/22 зелёных**
(`all_three_allowed_calls_exist_in_sources_and_are_named_to_the_person` и
`no_egress_beyond_the_three_named_and_the_gated_assistant` в их числе). Модульные тесты
`execution_mode::` — 16/16 (включая `left_headline_names_all_three_allowed_calls`).

## 3. Замена `support@auroraai.pro` → `sales@auroraai.pro`

Было 13 вхождений в 10 файлах (не 34 — фактически найденное меньше оценки владельца, остальные
help-страницы `.html` упоминают `auroraai.pro` только как имя сайта, не как почту). Заменено
во всех: `src/lib/feedback.js`, `src/lib/program-help.js`, `src/lib/updateErrorText.js`,
`src/lib/updateErrorText.guard.test.js` (сторож), `src/lib/__tests__/program-help.test.js`
(сторож), `src/routes/settings/+page.svelte`, `src-tauri/help-econometrica/error-codes.html`,
`src-tauri/src/commands/feedback.rs`, `src-tauri/src/commands/updater.rs` (включая сторож
`msg.contains("support@auroraai.pro")` → `sales@…`), `src-tauri/src/lib.rs`.

Дополнительно заменено в двух хвостовых `.bak-чистка` файлах (`src/routes/settings/+page.svelte.bak-чистка`,
`src-tauri/src/lib.rs.bak-чистка`) — они не часть сборки, но входят в требуемый пустой grep по
`src`/`src-tauri` без исключений, поэтому тоже приведены к единому адресу.

`rag.auroraai.pro` и `auroraai.pro` как имя сайта в подвалах — не трогал.

Вывод после правки:
```
$ grep -rn "support@auroraai" src src-tauri
(пусто, код возврата 1)
```
Было 13, стало 0 (было support@), 15 — sales@auroraai (13 в исходных + 2 в .bak-хвостах).

## 4. Проверка скрытых полей не смотрела на значения

Цикл в `link_carries_all_four_fields_and_is_encoded` (`feedback.rs`) проверял только
`link.contains("{field}=")`, без проверки значения — пустое `versiya=` проходило. Добавлена
проверка непустого значения по формулировке из задачи: «поля в ссылке нет – законно
(необязательные не подставляем пустыми); имя поля есть – значение обязано быть непустым»
(для обязательных пяти полей — безусловная проверка).

Доказано мутацией: `percent_encode(env!("CARGO_PKG_VERSION"))` временно заменён на
`percent_encode("")` в `feedback_form_link`. Дословный вывод:

```
running 12 tests
test ...link_carries_all_four_fields_and_is_encoded ... FAILED
test ...feedback_link_carries_all_four_hidden_fields_encoded ... FAILED
thread '...link_carries_all_four_fields_and_is_encoded' panicked at feedback.rs:448:13:
поле versiya ушло в ссылку пустым: https://forms.yandex.ru/...?produkt=econometrica&versiya=&...
test result: FAILED. 10 passed; 2 failed
```
Мутация откачена, `cargo test --lib feedback::` снова 12/12 зелёных.

## 5. Нет сторожа на российский адрес формы

Добавлен тест `feedback_form_url_stays_the_russian_service` (`feedback.rs`): проверяет, что
`FEEDBACK_FORM_URL` начинается с `https://forms.yandex.ru/` и не содержит имени прежнего
сервиса. Имя чужого сервиса собрано из кусков (`format!("{}.{}.{}", "docs", "google", "com")`),
чтобы сторож не краснел сам на себе.

Доказано мутацией: `FEEDBACK_FORM_URL` временно заменён на
`"https://docs.google.com/forms/d/e/mutation-proof/viewform"`. Дословный вывод:

```
running 13 tests
test commands::feedback::tests::feedback_form_url_stays_the_russian_service ... FAILED
... остальные 12 ... ok
thread '...feedback_form_url_stays_the_russian_service' panicked at feedback.rs:424:9:
адрес формы обязан быть российским сервисом forms.yandex.ru: https://docs.google.com/forms/d/e/mutation-proof/viewform
test result: FAILED. 12 passed; 1 failed
```
Только новый сторож покраснел, остальные 12 остались зелёными. Мутация откачена.

## Числа гейтов

- `cargo test` (весь `src-tauri`): **520 lib + 12 + 5 + 22 + 7 = 566 прошли, 0 упавших**
  (аудит держал базу `guard_left_position_egress` 22/22 и `guard_cpd88...` 5/5 — совпадает;
  lib-тестов было меньше на 2 новых: `sanitize_error_text_handles_space_slash_unc_quote_and_trailing_punct`
  и `feedback_form_url_stays_the_russian_service`).
- `npm run check`: **0 ошибок, 183 предупреждения** — как и было в базе аудита.
- `python -m pytest test_no_em_dash_in_client_text.py`: **17/17** — не тронуто моими правками
  (в клиентском тексте нигде не использовал длинное тире).
- `npm test`: **1586/1589 в общем прогоне, файл сборки 120/120 не изменился числом**; три
  падения — в `src/tests/settings-import-license-button.test.js` и
  `src/tests/feedback-report-button.test.js` (разные файлы в разных прогонах), это чужая
  область (третий исполнитель, правило «не трогай `src/tests/»). Прогнал оба файла ИЗОЛИРОВАННО
  — оба зелёные (5/5), значит это гонка с конкурентной правкой в общем репозитории (метод
  `concurrent_session_collision_shared_repo`), не регрессия от моих правок. Итог 1589 не
  уменьшился, новых JS-тестов я не добавлял (только текст email в двух существующих).

## Не входило в задачу, но замечено по пути

Находка №3 аудита (два настоящих перевода строки `\n    ` в `HEADLINE_LOCAL`) устранена
попутно правкой №2 — это тот же литерал, который я всё равно переписывал.
