# PULSE — разведка: конкурентный разбор Econometrica

## Задача своими словами
Ищу все следы конкурентного сравнения Aurora AI Econometrica (MMM Optimizer) с рынком (в т.ч. Tamburin/TaMetrics) и список доработок продукта, вытекший из этого сравнения, разбитый на быстрые (уже сделанные) и среднесрочные (остаток, который сейчас интересует лида). Задача — только чтение, отчёт пишу параллельно в RECON_COMPETITORS_2026-08-16.md.

## План поиска
1. Память машины `C:\Users\ackol\.claude\projects\D--Docs-Aurora-Ai\memory\` — grep tamburin/конкурент/roadmap
2. Память соседнего проекта `C--Users-ackol\memory\`
3. `aurora-meta\` целиком
4. KB Obsidian (`kb-search.py`, ключевые слова)
5. Репозиторий продукта `Aurora_Econometrica_thinwt\Projects\` + grep по содержимому
6. Соседние копии Econometrica в `Dev\`
7. git log репозитория продукта

## Отметки по времени
- 02:04 — старт. Создан маячок и durable-отчёт RECON_COMPETITORS_2026-08-16.md.
- 02:05 — найден `reference_competitor_tamburin.md` (память машины) + первичный grep INDEX_econometrica.md.
- 02:06 — найден `AVRORA_METHODOLOGY_FINDINGS.md` в текущей рабочей копии (оказался НЕ про конкурентов — методология по книгам).
- 02:07 — найдены главные документы: `5_Документация/COMPETITIVE_TAMBURIN.md`, `5_Документация/ROADMAP_SAAS_MIGRATION.md`, `KB/Competitive/Aurora_vs_Tamburin.md` (дубль). Прочитаны целиком.
- 02:08 — прочитан `project_econometrica_session4.md` (сессия создания документов).
- 02:09 — найден и прочитан `project_econometrica_backlog.md` (текущий durable-бэклог, 20 дней) + `project_aurora_onepagers.md`.
- 02:10 — верификация по коду: OLS-fallback = ✅ закрыто (`ols_modeler.py` + git log), Mediascope/Adfox = ❌ не сделано (только справочные цифры), lift-калибровка = 🟡 движок есть (`ff7b92b`), UI под вопросом.
- 02:11 — отчёт RECON_COMPETITORS_2026-08-16.md дописан полностью, обход завершён.
