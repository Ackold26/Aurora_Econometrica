ЕСЛИ МЕНЯ ОБОРВЁТ: git diff + строки МУТАЦИЯ + таблица разбора ниже

# ПУЛЬС s52 cifix

Задача: CI на master красный с 27.09 (первый красный 473f4967, последний зелёный bb5271d3). По каждому провалу (8 failed + 4 errors в Python Tests, 5 help-PDF в Test & Lint) установить: устаревший тест (запись+цитата) или регрессия; устаревшее – узко обновить, регрессию – чинить код с мутацией. Итог – Projects/CIFIX_s52.md.

План: 1) ci.yml, логи прогона; 2) по каждому провалу git log -S/-L в bb5271d3..HEAD; 3) правки; 4) мутации; 5) полный прогон как в CI; 6) отчёт.

Старт: 2026-09-27 14:54:49

## Разбор
- 14:57:45 ПРЕДПОСЫЛКА НЕВЕРНА: bb5271d3 «зелёный» 25.09 – это прогон workflow «Supabase Keepalive», не CI. Прогон CI на bb5271d3 (35466390641, 19.09) – failure. Последний зелёный CI – 934e5c41 (18.07). Диапазон поиска причин – 934e5c41..HEAD. Все 8F+4E воспроизведены локально.
- 14:59:58 holiday aliases: РЕГРЕССИЯ (упущение) – caf9a354 (13.09) добавил Пасху в HOLIDAY_DEFINITIONS без записи в _HOLIDAY_ALIASES. Чиню код. 11≠10 – УСТАРЕВШИЙ тест, тот же caf9a354 («13-е событие»), Пасха без date_range_v20.
- 14:59:58 rolling «—»: УСТАРЕВШИЙ – 80a1b8f2 (09.09) «76 длинных тире заменены на короткие в 13 файлах», строка window_label в диффе. Ожидание → ' – ' (с пробелами, чтобы не совпасть с запасной «периоды 1–3»).
- 15:00:42 KPI-вердикт: УСТАРЕВШИЙ – ffdc2b7b (08.09, High-1 аудита) перевёл пороги разрыва в пп (COUNT_GAP_HIGH_PP=10.0); тест передаёт 0.15 в старых долях. Ожидание не трогаю, вход → 15.0 пп.
- 15:03:45 PPTX +1 слайд (8 провалов: 4E fidelity + 4F backtest_slide): УСТАРЕВШИЕ. Бисекция по архивам 458 записей first-parent 934e5c41..HEAD: 4f995762 → 12, 05e745ff → 13. 05e745ff (13.09) «Шаг «Планирование» доезжает…»: слайд «Декомпозиция продаж» (s06b_decomposition_chart) при живом waterfall, условно (is_live+labels/values), родная диаграмма – не полупустой. Сторож записи в sidecar/tests/test_planning_section_reports.py (len(with)==len(without)+1).
- 15:07:13 help-PDF 5 FAIL: НЕ устаревший PDF и не регрессия справки – дефект проверки. Манифест (35a72f55, 14.09) хеширует сырые байты рабочего дерева; у 5 файлов локально w/lf, у 18 – w/crlf (git ls-files --eol), в индексе все LF. Раннер windows-latest с autocrlf=true выкатывает все в CRLF → 5 хешей LF не сходятся. Проверено: для всех 24 файлов manifest == sha(local); для 5 == sha(LF), для 19 == sha(CRLF). Содержимое PDF верно. Правка: нормализация CRLF→LF перед хешем в checker+builder, пересчёт только sources манифеста.
- 15:08:22 Правки тестов внесены (holiday 11, rolling ' – ', verdicts 15.0 пп, pptx 13/14/15 + проверка «Декомпозиция продаж»), код: алиасы Пасхи. Дальше help-PDF.
- 15:09:09 МУТАЦИЯ ВНЕСЕНА: tools/check_help_pdf_consistency.py: (хеш сырых байтов)
- 15:09:10 МУТАЦИЯ ОТКАЧЕНА: tools/check_help_pdf_consistency.py:
- 15:09:33 (предыдущая пара МУТАЦИЯ: sed не совпал, файл не менялся – подтверждено grep, строка 362 цела; повтор через python)
- 15:09:34 МУТАЦИЯ ВНЕСЕНА: tools/check_help_pdf_consistency.py:362 (хеш сырых байтов)
- 15:09:34 МУТАЦИЯ ОТКАЧЕНА: tools/check_help_pdf_consistency.py:362
- 15:09:50 МУТАЦИЯ ВНЕСЕНА: sidecar/econometrica/utils/holiday_calendar_ru.py:527 (ключ алиасов Пасхи испорчен)
- 15:09:53 МУТАЦИЯ ОТКАЧЕНА: sidecar/econometrica/utils/holiday_calendar_ru.py:527
- 15:10:16 АНОНС: полный прогон pytest как в CI (tools + sidecar/econometrica/tests), затем шаги работы check (линтеры, npm build, svelte-check, npm test, cargo test, clippy, xss) – >5 мин
- 15:11:57 Первый прогон -n auto остановлен: MemoryError (свободно <1 ГБ из 24, 65 процессов python у соседей). Перезапуск с -n 4 (в CI тоже 4 рабочих).
- 15:14:22 pytest tools (как в CI, -n 4): 2348 passed, 7 skipped, 0 failed, 0 errors. Ждём sidecar/tests.
- 15:15:31 pytest sidecar/econometrica/tests: 1784 passed, 2 skipped, 0 failed. АНОНС: шаги check, скрытые в CI за упавшим линтером (npm build, svelte-check, npm test, cargo test, clippy) – >5 мин
- 15:21:19 🔴 СКРЫТЫЙ ТРЕТИЙ СЛОЙ: в CI шаг «Prompt & delivery linters» красный с 13.09 14:24 (fc94298f) и маскирует следующие шаги. До него (31.08–13.09) в Test & Lint падал «Rust tests»: cargo не может склонировать приватную зависимость aurora_core (git Ackold26/aurora-platform-core, private=true, «failed to authenticate»). В ci.yml доступа нет → после моих правок Test & Lint останется красным на Rust tests. Нужен секрет/ключ развёртывания – решение владельца, не моё.
- 15:21:39 check локально: npm build EXIT 0; svelte-check 0 ошибок (182 предупр.); npm test 1666/1666. Ждём cargo test и clippy.
- 15:32:46 check локально: cargo test 0 failed, clippy exit 0. Все 6 групп провалов разобраны (1 регрессия – алиасы Пасхи, 1 дефект проверки – EOL в хеше help-PDF, остальные – устаревшие тесты). Файл Projects/CIFIX_s52.md харнесс записать не дал (запрет файлов-отчётов у субагента) – полный разбор в финальном ответе ведущему. Мутаций в дереве нет. Открыто: Rust tests в CI – приватная aurora_core без доступа (решение владельца).
ГОТОВО
- 15:33:58 auditfix предупредил: build-cloud.mjs подменял Cargo.toml 15:16–15:20; мой cargo test шёл 15:19–15:21 – результат ненадёжен. Перепрогон cargo test + clippy (-j 2) со сверкой хеша Cargo.toml до/после.
