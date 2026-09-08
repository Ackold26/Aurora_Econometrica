# PULSE — Инвентаризация демо-данных в поставке Econometrica

## Задача (своими словами)
Владелец хочет, чтобы все демо-данные, которые едут вместе с программой, показывали полный функционал — и построение модели, и прогноз по будущим медиа-активностям, при этом модель должна сходиться и давать значимую оптимизацию. Моя роль — только разведка: найти ВСЕ демо-наборы, которые реально едут клиенту (или используются в онбординге), описать их структуру (история/хвост медиаплана/разреженность каналов), и честно разметить пробелы. Ничего не править, не собирать, не обучать.

## План
1. tauri.conf.json → bundle.resources, содержимое resources/assets/static
2. Инструменты content-pack (verify-content-pack.mjs и соседи) — что входит в пакет
3. Поиск в src/ по демо/пример/образец/sample/try — онбординг
4. TestData/Planning_dataset.xlsx и подобные шаблоны
5. Установленная копия: %LOCALAPPDATA%, %APPDATA%\com.aurora.econometrica
6. D:\Docs\Aurora_Ai\TestData\Econometrica\ — пометить едет ли в поставку
7. Для каждого набора — структура (pandas/openpyxl): период, каналы, хвост медиаплана, разреженность

## Ход работы
- 23:46 — старт, создан маячок, план выше
- 23:50 — tauri.conf.json: bundle.resources = help-econometrica/*, ../sidecar/econometrica/**/*, ../content-packs/*, sidecar/pptx_pipeline.py, ../NOTICE.md. frontendDist = ../build (adapter-static, static/ копируется в build/ автоматически — это НЕ через bundle.resources, а через фронтенд-сборку).
- 23:52 — content-packs/*.json (cabinets, classifier, command-meta, onboarding, psy, themes) — конфиг кабинетов/онбординга, НЕ демо-датасеты.
- 23:55 — tools/generate_demo_samples.py — генератор "планового" демо (с хвостом-медипланом), 2 файла: synth_fmcg_brand, synth_otc_pharma → static/sample-data/planning/. Отдельно tools/synthetic_pilot_data.py — генератор SSOT-примеров (без хвоста), 4 файла → static/sample-data/ корень.
- 23:58 — pandas прочитан (системный Python312, D:\...\Programs\Python\Python312\python.exe). Структура всех 6 static/sample-data файлов снята.
- 00:05 — src/lib/components/pipeline/ImportStep.svelte: найдены 2 блока UI — «Попробовать на примере» (4 отрасли, downloadSample без subdir) и «Попробовать планирование на примере» (2 отрасли, subdir='planning/'). fetch('/sample-data/...') — подтверждает раздачу из frontendDist.
- 00:08 — build/sample-data/ (артефакт сборки) содержит те же 6 файлов — подтверждает, что static/ реально копируется в бандл.
- 00:10 — установленная копия %LOCALAPPDATA%\Optimizer MMM\help-econometrica\template_*.xlsx — 5 файлов, ВСЕ 0 строк (пустые бланки-шаблоны), включая template_pharma_rx.xlsx, для которого НЕТ ни базового, ни планового демо в static/sample-data.
- 00:12 — TestData/Econometrica/README.md подтверждает: Kagocel/Венарус/MMX — NDA-защищённые внутренние dev-датасеты, ЗАПРЕЩЕНО светить у других клиентов → НЕ едут в поставке (не в tauri.conf.json resources, не в static/).
- 00:15 — tools/test_sample_data_ssot.py: SSOT-гейт покрывает EXPECTED_SCHEMA только 4 корневых файла; planning/ подкаталог гейтом НЕ покрыт (комментарий в generate_demo_samples.py это прямо подтверждает).
- 00:18 — проверка разреженности (near-zero <5% среднего) по всем spend/натуральным колонкам во всех 6 файлах — везде умеренная «флайтинг»-пауза (3–37%), НЕТ буквальных нулей и нет каналов «почти всегда ноль».
- 00:20 — пишу итоговый отчёт DEMO_DATA_INVENTORY_2026-09-07.md.
- 00:25 — отчёт DEMO_DATA_INVENTORY_2026-09-07.md записан. Задача завершена (только чтение, ничего не правила, обучение не запускала).
