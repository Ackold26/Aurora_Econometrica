# PULSE s46 guard behavior

## Задача (своими словами)
Кнопка "Сообщить о проблеме" (FeedbackReportButton.svelte, feedback.js, pipeline/+layout.svelte)
добавлена в 6 шагов мастера + шапку, плюс кнопка "Загрузить файл лицензии" в settings —
ни одной проверки фронтенда не добавлено (1578 тестов как было). Нужно 3 поведенческих
теста vitest: (1) кнопка обращения вызывает open_feedback_form с ekran+oshibka, (2) кнопка
стоит в каждом из 6 шагов ошибки, (3) кнопка лицензии зовёт импорт. Каждый тест доказать
двумя мутациями: (а) удаление вызова — красный; (б) мёртвое действие при живом тексте
(if(false)/ранний return) — тоже красный (главная проверка от текстовых сторожей).

## План
1. Разведка: feedback.js (прочитан), FeedbackReportButton.svelte, layout.svelte, 6 Step-компонентов, settings/+page.svelte (импорт лицензии).
2. Написать тесты в src/lib/components/__tests__ или рядом (vitest конвенция проекта).
3. Прогнать npm test — сверить число (было 1578/115).
4. Для каждого теста — применить мутацию (а) и (б), зафиксировать дословный вывод, откатить.
5. npm run check.
6. git commit локально (без push).
7. Отчёт в Projects/GUARD_BEHAVIOR_s46.md + короткий ответ team-lead.

Старт: 2026-09-13 (время сессии не указано системой, отмечаю шаги последовательно).

## Ход
- feedback-report-button.test.js (3 теста, зелёные) — покрывает п.1: ekran/oshibka/отказ.
- settings-import-license-button.test.js (2 теста, зелёные) — покрывает п.3.
- Начинаю п.2: 6 шагов мастера. Подтверждено разведкой: ImportStep клик по .drop-zone--inline
  (pickFile), ValidateStep клик по ObjectiveSelector .card-roi (runValidate), ModelTrainingStep
  через моки ConfigPanel/TrainingProgress (__mocks__), DecomposeStep клик .btn-idle-run,
  OptimizeStep клик .btn-run, ReportStep клик .btn-export-unified. Для каждого веду к реальному
  errorMessage/errorMsg через мок invoke, не текстом.

- Все 6 файлов-тестов написаны и проверены по отдельности зелёными:
  feedback-report-button.test.js (3), settings-import-license-button.test.js (2),
  error-feedback-buttons-import-validate.test.js (2), error-feedback-buttons-decompose-report.test.js (2),
  error-feedback-buttons-optimize-model.test.js (2). Итого 11 новых тестов.
  Каждый ведёт компонент к РЕАЛЬНОЙ ошибке через мок invoke/open, не читает текст файла.
- Запущен полный `npx vitest run` в фоне (ушёл за 120с) — жду итоговое число прошедших/файлов.

- 20:1x - полный `npx vitest run` в фоне завис/долго идёт (>20 мин, обычно 2-3). Убиваю его,
  гейты оставляю оркестратору. Перехожу к точечным прогонам своих 5 файлов + мутационной
  проверке (б) "текст цел, действие мертво" по каждой из шести кнопочных проверок.
