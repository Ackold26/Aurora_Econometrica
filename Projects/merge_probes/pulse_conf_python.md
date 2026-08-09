# Пульс: разведка конфликтов tier2, группа Python

**Задача своими словами:** перед слиянием ветки origin/feat/ai-insights-tier2 (июнь) в текущую рабочую копию (feat/econ-canon-p0, август) — только чтение — по 7 python-файлам движка Econometrica сравнить обе стороны, найти функции/имена, которые есть только у них, проверить не переехали ли они в другое место современного дерева, и отдельно точно локализовать analysis_mode_label / kpi_kind_label (известная потеря — метки режима анализа и типа KPI, защищают клиента от неверного прочтения ROI vs доля вклада).

**План:** по каждому файлу — wc -l обеих сторон → список def/class/CONST через grep → comm разница → для разницы grep по всему дереву (переехало?) → определение +описание. Отдельно — точный адрес analysis_mode_label/kpi_kind_label у них.

**Старт:** отметка времени начала работы.

---
Обновление 1: wc -l обеих сторон по всем 7 файлам — наша сторона крупнее везде.
Обновление 2: top-level имена сравнены (comm) по всем 7 файлам. Найдены theirs-only имена в narrative_adapter.py (4), decomposer.py (1), channel_action.py (1). diagnostics.py, optimizer_honesty.py, sections.py, builder.py — пустой diff (наша полнее).
Обновление 3: для каждого theirs-only имени — определение + grep по всему дереву на переезд. _fmt_period_label/_infer_frequency → СУПЕРСЕДED свежей _derive_data_coverage (narrative_adapter.py:762, B1-fix R-02 2026-07-03, месяц позже их Волны 2). _ROI_ARTEFACT_MARKERS/_roi_unreliable → генуинная потеря, наша hero-фильтрация уже, чем их Волна 1 Шаг 2. _clean_name (decomposer) → генуинная потеря, имена каналов не чистятся от \n. soften_verdict_display (channel_action) → генуинная потеря целиком, вместе со всем контуром verdict_display/verdict_modality/roi_unreliable/roi_caveat в narrative_adapter.
Обновление 4: analysis_mode_label/kpi_kind_label точно локализованы у них (narrative_adapter.py:914-927, потребители sections.py:1587-1594, builder.py:280-281+2857-2861). Подтверждено 0 у нас, найдена точная точка вставки в нашем builder.py (data_info на 3267-3282).
Обновление 5: strings_ru.json — 0 ключей только у них. Готово, отчёт отправлен.
