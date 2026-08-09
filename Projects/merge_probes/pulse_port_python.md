# Пульс: перенос потерянных функций Python (sidecar/econometrica)

## Задача своими словами
Перенести три куска функциональности из образца `origin/feat/ai-insights-tier2` в текущую ветку `feat/econ-canon-p0`, только в файлах:
- engines/decomposer.py
- engines/channel_action.py
- engines/narrative_adapter.py
- aurora_html/sections.py
- aurora_pptx/builder.py
- tests/ (новые тесты)

1. Метка режима анализа (analysis_mode_label) и типа KPI (kpi_kind_label) — прокинуть из narrative_adapter.py в diagnostics, отрендерить в sections.py и builder.py (карточка источников/данных).
2. `_clean_name()` в decomposer.py — обернуть top['name']/worst['name'] в _build_channel_insight, не путать с _normalize_channel_name.
3. `soften_verdict_display` + VERDICT_DISPLAY_RU в channel_action.py — смягчение модальности вердикта канала по глобальной надёжности модели, подключить туда, где формируется канальный вердикт.

Не коммитить, не трогать другие каталоги. Тест на каждый перенос + мутационная проверка (сломать → красный → откатить). В конце прогнать pytest sidecar/econometrica/tests.

## План
1. Прочитать образец (git show origin/feat/ai-insights-tier2:<путь>) для всех трёх точек.
2. Прочитать текущий код в тех же местах.
3. Внести правки хирургически (не переписывать нашу архитектуру).
4. Написать/дописать тесты, проверить мутацией.
5. Прогнать полный набор тестов движка, зафиксировать числа.

## Старт
2026-08-04, начало работы.

## Готово
Все 3 переноса сделаны + тесты + мутационная проверка каждого (покраснели, откачены).
Полный прогон sidecar/econometrica/tests: 986 passed, 9 failed (все 9 — унаследованный
баг на HEAD, подтверждено git stash: идентичный список падений без моих правок),
1 skipped. Отчёт — в финальном сообщении команды.
