# Пульс: перенос глоссария и меток в Rust

## Задача (своими словами)
Переношу 6 функций/фич из `origin/feat/ai-insights-tier2` в текущую ветку `feat/econ-canon-p0`,
только в файлах `src-tauri/src/commands/report.rs` и `src/lib/components/pipeline/ReportStep.svelte`:
1. параметр `glossary` в `econ_export_xlsx`/`build_xlsx` (50 терминов вместо 11 зашитых, с fallback)
2. `clean_label()` — схлопывание переносов строк в именах каналов
3. `reliability_label()` — плашка надёжности модели в XLSX/MD
4. `verdict_display()` — локализованный вердикт со смягчением
5. `analysis_mode_label()` / `kpi_kind_label()` — метки режима анализа/типа KPI
6. `roi_unreliable()` — флаг «ROI ненадёжен» → «н/д» вместо битого числа

## План
1. Прочитать оригинал (git show origin/feat/ai-insights-tier2:...) и текущий report.rs целиком
2. Перенести функции по одной, с поиском мест применения в НАШЕМ файле (номера строк там другие)
3. Обновить ReportStep.svelte (импорт glossary.js + передача в invoke)
4. Мутационная проверка glossary (сломать → увидеть → откатить)
5. cargo test + npm run check, зафиксировать числа
6. Отчёт по всем 6 пунктам

## Статус
- Прочитала эталон (origin/feat/ai-insights-tier2:report.rs) и наш report.rs целиком по секциям
- Перенесены 6 хелперов (roi_unreliable, reliability_label, verdict_display, clean_label,
  analysis_mode_label, kpi_kind_label) в блок Helpers
- build_markdown: top_ch (фильтр roi_unreliable + clean_label), режим анализа, плашка
  надёжности, waterfall/ROI/CI/оптимизация таблицы – clean_label + roi_unreliable + verdict_display
- econ_export_xlsx/build_xlsx: добавлен параметр glossary: Option<Value>/Option<&Value>
- build_xlsx: meta_rows «Режим анализа», reliability caveat в Executive Summary,
  ROI каналов (roi_unreliable+verdict_display+сноска), Декомпозиция/Spend vs Effect/
  Динамика/Оптимизация/Данные – clean_label на именах каналов, Глоссарий – fallback+фронт
- cargo check – ОК, компилируется чисто
- ReportStep.svelte: добавлен import getAllTerms + поле glossary в invoke('econ_export_xlsx')
- Добавлено 7 регресс-тестов (перенос из origin) + функциональный тест глоссария через zip-чтение xlsx
- Мутационная проверка глоссария: сломала ветку (filter(|_| false)) → тест упал на нужной строке → откатила
- ФИНАЛ: cargo test 363 passed / 0 failed / 3 ignored (было 356, +7 новых тестов)
- ФИНАЛ: npm run check 0 ошибок, 177 предупреждений (все пред-существующие, не мои)
- Готово, отчёт передан team-lead
