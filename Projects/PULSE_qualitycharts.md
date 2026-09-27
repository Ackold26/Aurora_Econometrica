# PULSE — графики качества модели (pptx + веб-отчёт)

Задача: добавить графики качества обученной модели (факт/прогноз, остатки во времени, остатки/прогноз) в колоду pptx и веб-отчёт продукта Econometrica. Графики должны нести данные внутри себя (родной формат pptx/echarts) — картинку вставлять нельзя, matplotlib/plotly не тащим (крупная внешняя зависимость запрещена). Область работы: только sidecar/econometrica/, src/src-tauri/tools не трогать.

План:
1. Прочитать charts.py (образец стиля), builder.py (слайд качества ~1579, ~3200-3330), interactive.py (водопад ~408,493-496), sections.py (раздел качества).
2. Добавить новую функцию диаграммы в charts.py (линия факт/прогноз) для pptx, встроить в builder.py на слайд качества.
3. В веб-отчёте (aurora_html) добавить три графика через ECharts: факт/прогноз, остатки во времени, остатки/прогноз (scatter) — проверить поддержку scatter.
4. Подписи по-русски, без округления данных.
5. Тесты: график есть при данных / нет при отсутствии, данные совпадают с исходными. Мутационная проверка.
6. Прогон тестов движка, отчёт.

Старт: 11 сен 2026 г. 9:00

--- отметка 9:20 ---
Шаг 1 (адаптер) сделан: engines/narrative_adapter.py, функция _map_pipeline_to_builder_data,
после блока effective_parameters добавлен блок diagnostics["actual_vs_predicted"]
= {dates, actual, predicted, residuals}. Остатки считаются здесь один раз (a-p),
без округления. Дальше: график в веб-отчёт (ECharts), потом родной график в колоду,
потом тесты с мутациями.

--- отметка 9:45 ---
Шаг 2 (веб-отчёт) сделан:
- aurora_html/builder.py: payload["quality"] = self._quality_series() (новый метод, читает self.diagnostics["actual_vs_predicted"]).
- aurora_html/interactive.py: buildQualityAvpOption/buildQualityResidualsOption/buildQualityScatterOption (после buildWaterfallOption), 3 initChart(...) вызова в initAllCharts.
- aurora_html/sections.py: render_sources — quality_charts_html строится ТОЛЬКО если avp.dates/actual/predicted непусты, три chart-container блока с родными подписями chart-subtitle. Легенда — родная ECharts (legend:{{...}} в опции), не примитивы.
Дальше: родной график в колоду (charts.py + builder.py s11_sources), потом тесты с мутациями.

--- отметка 10:15 ---
Шаг 3 (родной график в колоду) сделан:
- aurora_pptx/charts.py: новая функция make_actual_vs_predicted (LINE_MARKERS, 2 серии
  Факт/Прогноз, родная легенда chart.legend BOTTOM, цвета через COLOR.brand.gold/deep_40).
- aurora_pptx/builder.py: self.quality_avp (гейт по данным, is_live), добавлен в _page_shift;
  новый метод s10e_quality_chart() — ОТДЕЛЬНЫЙ вставной слайд (по образцу backtest/gen_compare/
  promises/forecast), т.к. на существующем слайде "Данные и качество" измерено на боевой
  фикстуре Kagocel — свободной полосы для графика нет (0.25-0.38 дюйма). Вызов в build()
  после forecast, перед s06_action_chart.
Проверено вручную: собрал колоду с synthetic actual_vs_predicted (20 периодов) поверх
боевой фикстуры kagocel — 13 слайдов, check_overflow() = 0 issues, чарт нативный (LINE,
has_legend=True position=BOTTOM), значения точно совпадают с входом (без округления).
🔴 ПОБОЧНАЯ НАХОДКА: charts/generators.py использует matplotlib и уже даёт PNG-картинку,
встроенную в s_forecast_plan (add_picture) — то есть существующий код УЖЕ нарушает
правило "рисовальщиков изображений нет"/"картинку нельзя". Не трогал (не моя область
задачи), сообщил владельцу в отчёте.
Дальше: тесты с мутациями (адаптер, pptx-слайд, веб-отчёт), потом прогон полного набора тестов.

--- отметка 10:50 ---
Тесты написаны и промутированы (все поймали мутацию):
- tests/test_quality_charts_adapter.py (6 тестов, адаптер)
- tests/test_pptx_quality_chart.py (6 тестов, колода)
- tests/test_html_quality_charts.py (6 тестов, веб-отчёт)
Полный прогон движка порциями (6 чанков по алфавиту): 244+159+256+240+255+316 = 1470 passed,
2 skipped, 0 failed. Отправная точка была 1452/2/0 — разница ровно +18 = мои новые тесты.
🔴 По пути поймал регресс от СВОИХ правок: тест test_no_em_dash_in_client_text.py упал —
я вставил длинное тире "—" в два JS-комментария внутри interactive.py (внутри f-string,
весь бутстрап-скрипт — один Python string-литерал, тест это ловит). Исправил на короткое "–".
Работа сделана полностью. Пишу финальный отчёт.
