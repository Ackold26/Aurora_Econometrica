# Пульс A — зонды CPD-08, CPD-10, CPD-12, CPD-13 для Aurora AI Econometrica (EC)

**Задача своими словами:** проверяю четыре клетки колонки EC в кросс-продуктном реестре дефектов
(`aurora-meta/CROSS_PRODUCT_DEFECT_REGISTRY.md`) на рабочей копии продукта
`D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_canon` (ветка feat/econ-canon-p0):
- CPD-08 — линейный IQR-детектор аномалий на скошенных рыночных данных (pptx_processor.rs::detect_anomalies)
- CPD-10 — классификация отказа Claude CLI по квоте/логину (commands/claude.rs::classify_stderr)
- CPD-12 — выбор лицензии по кабинету через .find() при мультилицензии (license.rs/online_auth.rs/supabase edge)
- CPD-13 — `\b` в JS/TS/Deno regex мёртв для кириллицы (src/, supabase/functions/)

Только зонды (команда + вывод + файл:строка), код не трогаю. Результат пишу по мере готовности в result_A.md.

**План:** прочитать разделы реестра по каждой записи → найти релевантные файлы в дереве EC → прочитать код → прогнать зонд (грep/арифметика/чтение логики) → зафиксировать статус ✅/🔴/⚪/🟡 в result_A.md.

**Старт:** 2026-08-03 15:30
- 15:35 CPD-08: прочитан detect_anomalies (pptx_processor.rs:826-886), прогнан эталонный арифм. зонд реестра [100,10,8,6,5] — 4/5 ложных high включая лидера. Подтверждено, путь до клиента через lib.rs:1060→format_analytics_context. Статус 🔴 записан в result_A.md. Перехожу к CPD-10 (claude.rs::classify_stderr).
- 15:42 CPD-10: classify_stderr — нет паттернов квоты/логина, ErrorCode только CL-001..008 (grep CL0(09|10|11) = 0). При None сырая строка CLI уходит клиенту как есть (claude.rs:434-440). Статус 🔴 записан. Перехожу к CPD-12 (license.rs/online_auth.rs — лицензия по .find()).
- 15:50 CPD-12: грep .find()/.first()/[0] на license.rs+online_auth.rs = 0 (расширенный по всему src-tauri тоже без license-selection). license.rs хранит одну лицензию (не список), /auth фильтрует по product на входе. Механика сервера (SQL EF) вне репо (только supabase/functions/content/index.ts). Статус 🟡 (нужен живой стенд) записан. Перехожу к CPD-13 (кириллица+\b).
- 16:05 CPD-13: нет ПДн-guard в EC вообще (⚪ по букве записи). НО нашла живую 3-ю реализацию класса: content-packs/classifier-data.json содержит 6 кириллических small-talk паттернов (^хай\b, ^пока\b, ^спс\b и др.) в chat-classifier.js — прогнала в node.js, ВСЕ никогда не матчат (эмпирика подтверждена), ASCII-паттерны (hi\b) работают. Статус 🟡 записан с разбором обеих частей. Все 4 клетки готовы, пишу финальный ответ team-lead.
