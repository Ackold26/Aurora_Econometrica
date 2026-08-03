# Пульс — карта экспорта результата клиенту (bundle map)

## Задача своими словами
Нужно найти фактическую цепочку «расчёт → экспорт → файл клиенту» в Econometrica (Tauri+SvelteKit+Python sidecar), чтобы понять куда встраивать блок сертификата методологии/воспроизводимости. Отвечаю только фактами: файл:строка + цитата, без догадок.

## План
1. Найти вызов decomposer.decompose(...) в server.py — эндпоинт, структура ответа.
2. Разобрать html_export.py / json_export.py / pptx_export.py — кто зовёт, вход/выход, report id в HTML.
3. Найти место под блок "Воспроизводимость и сертификат" в HTML и PPTX.
4. Найти seed/seed_source/random_seed, utils/seeding.py, diagnostics/mcmc_info.
5. Разобрать persistence_safe.py — manifest формат aurora-model.
6. Найти вызывающих save_v20_diagnostics (persistence.py:863) и model_version в modeler.py.

Пишу находки сразу в bundle_map.md по ходу.

## Отметки
- [старт] 2026-08-03 — создан пульс-файл, начинаю разведку структуры репозитория.
- нашла существующий, но НИГДЕ не вызываемый `engines/methodology_cert.py` — готовый движок сертификата, но осиротевший.
- разобрала `/compute/decompose`, `/export/pptx`, `/export/html` в server.py — точки входа найдены.
- нашла, что `save_v20_diagnostics` (persistence.py:863) не имеет живых вызывающих — model_version не бампается до 2.0.0 в проде.
- разобрала report_id (narrative_adapter.compute_report_id) — общий хеш для HTML и PPTX.
- ВАЖНО: aurora_pptx/layouts.py, master.py, tokens.py и др. — DEPRECATED (см. __init__.py docstring), реальный код в aurora_pptx/builder.py (4074 строк, класс AuroraPPTXBuilder). Не путать со стаб-файлами render_methodology/render_colophon в layouts.py (NotImplementedError - мёртвый код M3).
- разобрала persistence_safe.py manifest + utils/seeding.py — паспорт воспроизводимости.
- [готово] bundle_map.md написан полностью, все 6 разделов + «чего не нашла». Возвращаю сжатую выжимку team-lead.
