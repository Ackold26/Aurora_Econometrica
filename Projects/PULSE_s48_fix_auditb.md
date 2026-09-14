# PULSE s48 fix audit-b

## Задача (пересказ)
Внешний аудит блока нашёл три вещи. Форматтер суммы (_fmt_mln vs format_realloc_mln) уже
починен ведущей сессией. Мои три задачи:
1. Написать сторожа «формат суммы переброски живёт в одном месте» (класс проблемы, не имя функции).
   Показать два подхода с их слабыми местами, выбрать, доказать красное/зелёное с мутацией.
2. Проверить делом (не рассуждением) гипотезу аудитора: выгрузка графика картинкой в
   sidecar/econometrica/aurora_html/interactive.py (data-copy-chart) может снимать анимацию до
   первого кадра → пустой график. Использовать Playwright/Chromium, готовый HTML-отчёт.
3. Починить сторожа согласованности TRIAL_TERMS_REVISION — должен краснеть на однозначный номер
   редакции (например "2026-09-15.3"), зелёный на "2026-09-14.02".

## План
1. Изучить builder.py (сделано), format_realloc_mln, существующий сторож порога.
2. Задача 3 (проще, изолирована) — user_config.rs + сторож согласованности ревизии.
3. Задача 1 — новый тест-сторож формата суммы.
4. Задача 2 — зонд Playwright на реальном HTML-отчёте.
5. Прогоны: pytest sidecar (≥1686), cargo test trial (≥19).

## Старт: 14.09.2026, 9:48

## Задача 3 — ЗАКРЫТА (10:05)
Добавлен assert_eq!(number_part.len(), 2, ...) в trial_terms_revision_matches_frontend_checkbox_text
(user_config.rs, после парсинга u32). Красное показано на мутации "2026-09-15.3" (left:1 right:2,
паника со внятным текстом). Возврат к "2026-09-14.02" → 19/19 trial-тестов зелёные (cargo test trial).

## Задача 1 — ЗАКРЫТА (10:35)
Добавлен test_no_inline_reallocation_format_literal_outside_shared_source в
tests/test_reallocation_threshold_single_source.py. Подход B (носитель amount_mln/realloc
обязан быть обёрнут ИМЕННО format_realloc_mln) выбран против подхода A (формат-спецификатор
рядом со словом «млн» — отклонён, т.к. false positive на budget:.0f} млн и НЕ поймал бы
реальный дефект: слово «млн» и :.1f-спецификатор жили в разных строках/местах файла).
Красное показано на мутации builder.py (новая локальная _money_mut, другое имя, не _fmt_mln) —
поймана по классу. Мутация снята, git diff чист (grep _money_mut = 0). Зелёное: 4/4 в файле.

## Задача 2 — ЗАКРЫТА, гипотеза ПОДТВЕРЖДЕНА (11:10)
Зонд Playwright/Chromium на реальном отчёте mmm_report_20260914_093403.html: скопировал
отчёт, у одной копии добавил opt.animation = false перед exportChart.setOption (та же строка,
что и в правке), у другой оставил как было. Реальным кликом по [data-copy-chart] (не имитация
JS) скачал PNG через оба варианта:
- ДО правки: водопад полностью пуст — только оси, сетка и подписи чисел, ни одного столбца
  (доказано картинкой C:\Users\...\scratchpad\click_unfixed.png).
- ПОСЛЕ правки: все шесть столбцов водопада на месте, с цветом и подписями
  (click_fixed.png).
Находка НАСТОЯЩАЯ. Правка: sidecar/econometrica/aurora_html/interactive.py, строка после
`opt.backgroundColor = currentSurfaceColor();` — добавлено `opt.animation = false;` перед
`exportChart.setOption(opt, true);` (offscreen-инстанс выгрузки не нуждается в анимации
никогда — он снимается сразу после создания).

## Прогоны — ФИНАЛ (11:15)
python -m pytest sidecar/econometrica/tests -q → 1687 passed, 2 skipped (ожидаемо), 0 failed.
cargo test --manifest-path src-tauri/Cargo.toml trial → 19 passed, 0 failed (все 6 test-бинарей ok).
Дерево не оставлено в промежуточном состоянии — обе мутации (Rust-константа, builder.py
_money_mut) сняты и сверены git diff/grep. src/ не трогала. Записей не делала.

## ЗАВЕРШЕНО (11:16)

## Задача 4 (добавлена team-lead, важнее задачи 3) — ЗАКРЫТА (10:06)
Гонка: гейт trialConsentBlocking закрывал только клавиатуру (isKeydownOutsideBlockingOverlay +
capture-listener на 'keydown' в TrialConsentOverlay.svelte), девять обработчиков МЫШИ на
главной странице не проверялись вовсе.

Выбор: второй capture-listener той же формы, но на 'click' (не физическое перекрытие экрана).
Обоснование в комментарии в коде (TrialConsentOverlay.svelte): физическое перекрытие зависит
от z-index/stacking context и НЕ проверяемо в jsdom (нет layout-движка — программный клик
достигает цели независимо от визуального перекрытия), а capture-listener на 'click' — тот же
проверенный приём, что и у клавиатуры, ловит мышь+касание+Enter/Space одним узлом. Что НЕ
закрывает: навигацию не через событие 'click' (drag-and-drop, программный вызов без события
пользователя) — такого в базе сегодня нет.

Тест написан ДО правки (src/tests/trial-consent-overlay.test.js, новый describe "перехват
кликов МЫШЬЮ"). Красное на нынешнем коде показано: 2 из 4 новых тестов красные ровно там, где
проверяется блокировка (клик на фоне доходит до продуктового обработчика — до монтирования
окна и в установившемся состоянии). Правка: $effect с capture-listener на 'click' в
TrialConsentOverlay.svelte, переиспользует existing isKeydownOutsideBlockingOverlay (логика
общая, не только для клавиш). Зелёное: 43/43 (overlay+gate-race+global-shortcuts).
Тонкость 1 (окно условий рабочее) проверена: клик по чекбоксу внутри оверлея не гасится
(checkbox.checked===true), «Принимаю» зовёт accept_trial_consent.
Тонкость 2 (после согласия перекрытие снимается полностью) проверена: после
trialConsentPromptOpen.set(false) клик по фону снова доходит до продуктового обработчика.

## Прогоны — ФИНАЛ v2 (10:07)
npx vitest run → 1645 passed, 0 failed (127 файлов) — выше требуемых 1641.
pytest/cargo trial — без изменений с прошлого прогона (1687 passed / 19 passed), python/rust
файлы после того прогона не трогала.
