# PULSE — правка текстов и справки по аудиту (2026-08-16)

Старт: 16 авг 2026 г. 13:37:44

## Задача
Чиню находки внешнего аудита в клиентских текстах и справке (ветка `feat/econ-p1-winning`,
дерево `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt`).
Находки: F-03 (High), F-04 (Medium), F-05 (Medium) из `Projects\AUDIT_P1_FINDINGS_2026-08-16.md`.

## План
1. F-03 — числа справки о минимуме данных занижены (справка использует Ratio =
   строки/(каналы+контроли), продукт с 03.08 гейтит по эффективному числу параметров
   `n_params_effective_ols = n_predictors + 1`). Проверить validator.py:820-846, пересчитать
   числа во всех местах (index.html, faq.html, data-preparation.html — таблица «в абс. цифрах»).
2. F-04 — «пропуски считаются нулём» неверно для целевой метрики (kpi): периоды с пропуском
   исключаются из обучения целиком вместе с медиа-данными этих недель (validator.py:605-631).
   Различить роли в tooltip-texts.js:137, insights-rules.js:752, ExpertValidatePanel.svelte:145.
3. F-05 — два критерия объёма данных (длина ряда И ratio), нигде не сказано что их два.
   program-help.js:46-47 + index.html:112 (быстрый старт) должны сказать про оба критерия явно.
4. После HTML-правок: `python tools/build_help_pdf.py` → `python tools/check_help_pdf_consistency.py`.
5. Гейты: `npx vitest run` (baseline 1471 passed), `npm run check` (0 ошибок).
6. Отчёт по ходу в `Projects\FIX_AUDIT_TEXTS_2026-08-16.md`.

## Область (можно трогать)
`src-tauri/help-econometrica/*.html`, `src/lib/program-help.js`, `src/lib/data/tooltip-texts.js`,
`src/lib/insights-rules.js`, `src/lib/components/pipeline/ExpertValidatePanel.svelte`.
НЕ трогать `sidecar/` и `src-tauri/src/`.

## Прогресс
- [x] Читаю validator.py:820-846 и :605-631 (канон формул)
- [x] F-03 — пересчёт чисел и правка (index.html, faq.html, data-preparation.html)
- [x] F-04 — различение ролей в текстах (tooltip-texts.js, insights-rules.js, ExpertValidatePanel.svelte)
- [x] F-05 — явное указание «два критерия» (data-preparation.html, faq.html, index.html, program-help.js)
- [x] build_help_pdf + check_help_pdf_consistency (0 FAIL, 5 WARN не связаны с правкой)
- [x] vitest run (1468 passed 0 failed; целевые 131/131 зелёные)
- [x] npm run check (0 ERRORS, 177 pre-existing WARNINGS)
- [x] отчёт FIX_AUDIT_TEXTS_2026-08-16.md дописан

РАБОТА ЗАВЕРШЕНА — 16 авг 2026 г. 13:51.
