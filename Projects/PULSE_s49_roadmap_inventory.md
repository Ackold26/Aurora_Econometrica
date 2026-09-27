# PULSE s49 — опись задач развития Econometrica (roadmap inventory)

Задача (своими словами): собрать полную фактическую опись открытых долгов и задач развития продукта
Aurora AI Econometrica (Optimizer MMM) — долги из handoff/аудитов, TODO/FIXME по слоям кода, состояние
планов (CANON_P0 и др.), состав клиентских отчётов (html/pptx) и что в них упрощено, автоматические
и ручные сторожа стиля текста, незакрытые кросс-продуктовые дефекты (CPD), и список «ждёт владельца».
Режим — только чтение, ничего не менять, тяжёлых прогонов и сборок не делать.

План:
1. Прочитать Projects/handoff.md, NEXT_SESSION_PROMPT.md, аудиты s47/s48, GATES_s47.md
2. grep TODO/FIXME/HACK/XXX/заглушк/временно/отложен/не реализован/known limitation/пока не по src/, src-tauri/, sidecar/
3. Найти планы/ADR/PRD по Эконометрике в репо и aurora-meta/, отдельно CANON_P0.md
4. Просмотреть aurora_html/ и aurora_pptx/ — состав разделов отчёта, места-заглушки
5. Найти сторожей стиля текста (правдоподобный диапазон, доверительный интервал, verify_*_narrative, contrast_audit, build_glossary.py)
6. Найти реестр кросс-продуктовых дефектов в памяти, выписать CPD по Эконометрике
7. Собрать «ждёт владельца» из handoff/NEXT_SESSION_PROMPT/памяти INDEX_econometrica.md
8. Записать Projects/INVENTORY_s49_roadmap.md, отчитаться team-lead

[11:07] Старт. Создан маячок.

[11:45] Прочитаны handoff.md, NEXT_SESSION_PROMPT.md, AUDIT_s48_external.md, audit_findings_live_s48b.md, AUDIT_s47_external.md, GATES_s47.md — долги и находки выписаны.
[12:05] grep TODO/FIXME/... по src/, src-tauri/src/, sidecar/econometrica/ (исключены dist/_internal/venv/target) — 64/59/35 находок, содержательные отобраны.
[12:15] Найден CANON_P0 (D:\Docs\Aurora_Ai\PLAN_MMM_CANON_P0_2026-08-02.md, вне репо) — подтверждён как незакрытая автономка. Просмотрены COMMERCIAL_READINESS_ROADMAP.md и другие docs/*PLAN*.
[12:25] Состав HTML/PPTX отчёта выписан по функциям render_*/sXX_*. Сторожа стиля текста найдены (em_dash, contrast, narrative verify, build_glossary).
[12:35] Кросс-продуктовые дефекты: прогнан py aurora-meta/scripts/registry-count.py --details (только чтение), выписаны CPD с EC:🔴 (18) и EC:🟡 (11). Найдено противоречие CPD-116 (реестр устарел против handoff.md).
[12:40] Собран список "ждёт владельца" из памяти и файлов сессии.
[12:45] Записан Projects/INVENTORY_s49_roadmap.md. Заминка: EPERM uv_spawn на Bash/PowerShell/Grep/Glob на ~5 минут (транзиент, восстановилось само) — задержало сбор сторожей стиля.
[12:47] Готова отчитаться team-lead.
