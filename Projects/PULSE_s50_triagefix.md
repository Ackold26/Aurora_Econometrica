# PULSE s50 triagefix

2026-09-27 03:34 – старт. Задача от team-lead: две правки по находкам внешнего аудита (Эконометрика):
1) подпись доли канала «продаж» → «медиа-вклада» (S7 заголовок раздела + заголовок слайда, знаменатель – весь медиа-вклад).
2) доля лидера на экранах приложения (панель выводов, шаг отчёта) – к одной десятой, единым JS-помощником (как в DecomposeStep.svelte).
Без вложенных агентов. Приёмка: pytest sidecar/econometrica/tests, vitest, npm run check. Два отдельных коммита.

План:
- найти все места «% продаж» в sidecar/econometrica и src (grep), решить по каждому – трогать/нет.
- поправить strings_ru.json, narrative_adapter.py, обновить тест test_channel_share_single_source.py.
- проверить заголовки на переполнение (aurora_pptx/check_overflow.py, text_metrics) – НЕ ослаблять сторожей.
- найти/создать общий JS-помощник для одной десятой доли, применить в insights-rules.js, ReportStep.svelte, DecomposeStep.svelte.
- добавить vitest на фикстуре 87.5%.
- прогнать приёмку, закоммитить.

Решения по местам «% продаж» (grep sidecar/econometrica + src, без dist/_internal):
- strings_ru.json:155-156,158 (s07_dominant/s07_top_n/s07_single) – ПРАВЛЮ: знаменатель _channel_share_pcts = весь медиа-вклад (sections.py:1334).
- narrative_adapter.py:604-605 (derive_action_headline, ветка portfolio) – ПРАВЛЮ: тот же channel_share_pcts (строка 582).
- aurora_pptx/builder.py:1593 (s04_section_divider, fallback без self.facts, метод вне потока build()) – ПРАВЛЮ для консистентности с реальной веткой выше (та же R-12 формула «медиа-вклада при бюджета»).
- aurora_pptx/builder.py:2251 (s07_action_table, fallback когда derive_action_headline вернул falsy) – ПРАВЛЮ: тот же паттерн топ-N.
- src/lib/program-help.js:94 (справка «Частые проблемы») – ПРАВЛЮ: «один канал даёт 90%+» – тот же сценарий доминирования в медиа-вкладе (мультиколлинеарность), не доля продаж.
- utils/kpi_display.py:104 (докстрока fmt_pct, исторический пример другого бага N1 округления) – НЕ ТРОГАЮ: не user-facing, комментарий про другую находку.
- src/lib/insights-rules.js:1607 basePctRounded/mediaPctRounded («X% продаж – базовые/вклад рекламы») – НЕ ТРОГАЮ: это доля БАЗЫ/МЕДИА в ПРОДАЖАХ (baseline_pct/100-baseline_pct), другая метрика, знаменатель – продажи, не медиа-вклад. Часть той же строки top.contribution_pct – ПРАВЛЮ (см. правку 2).
- src/lib/insights-rules.js:1645 «отъедают продажи»/«% от продаж» (signed_factor_contributions.pct) – НЕ ТРОГАЮ: доля влияния внешнего фактора от ПРОДАЖ, не доля канала в медиа-вкладе.
- ReportStep.svelte:413 «медиа даёт лишь ~X% продаж» (share = lift/mediaLift*100) – НЕ ТРОГАЮ: это доля итогового прироста от роста эффективности медиа (демпфер оптимизации), не доля канала в медиа-вкладе.
- ReportStep.svelte:397 «медиа даёт лишь...» соседняя строка topDriver уже была «медиа-вклада» – только форматирование поправлено (правка 2).
- insights-rules.js:1688 top3Sum.toFixed(0) «X% от всего медиа-эффекта» (сумма долей топ-3) – НЕ В СКОУПЕ задачи (не входит в перечисленные строки 1684/1830/2755/1607), тот же класс риска (сумма долей округляется отдельно от строк) – ОСТАВЛЕНО НЕТРОНУТЫМ, отмечаю для team-lead как потенциальный кандидат на отдельную правку.

Переполнение заголовков (после правки 1): «медиа-вклада» длиннее «продаж» на 8 симв. Затронуты s07_dominant/s07_top_n (веб) и derive_action_headline portfolio (презентация, тот же текст в _action_title). Прогоняю check_overflow ниже, сокращать буду хвост «– остальные рекомендованы к консолидации»/«- основная точка оптимизации портфеля» при необходимости.

03:36 – python -m pytest sidecar/econometrica/tests (полный, из корня) – 1775 passed, 2 skipped, 1 xfailed, EXIT:0. Переполнение НЕ пострадало (test_pptx_big_number_with_decimal_fits[87.5] зелёный, xfail только на открытом [100.0], как и было до правки). Заголовки не пришлось сокращать – текст помещается.

Правка 2 – общий помощник: src/lib/format-numbers.js:formatChannelSharePct(n, fallback='-') – зеркало Python utils/kpi_display.py:fmt_share_pct (f"{f:.1f}%"), фиксированная одна десятая без auto-detect дроби formatPct (иначе малая доля <1% умножилась бы на 100 повторно).
Подключено: DecomposeStep.svelte (строки 105, 214 – локальный channelSharePct(ch) как селектор значения остался, форматирование через общий помощник), insights-rules.js (1607 частично – top.contribution_pct, НЕ basePctRounded/mediaPctRounded; 1684; 1830; 2755→2759 после правки импорта), ReportStep.svelte (280, 397, 506).
НЕ трогала insights-rules.js:1688 (top3Sum.toFixed(0) «X% от всего медиа-эффекта») – вне перечня задачи (сумма долей топ-3, не доля отдельного канала), тот же класс риска остаётся открытым – кандидат на отдельную правку, сообщаю team-lead.

04:прогон vitest точечно:
- src/tests/report-step-channel-share-one-decimal.test.js (3 теста: письмо/интерпретация/FAQ) – 3 passed.
- src/lib/__tests__/insights-channel-share-one-decimal.test.js (decomposeInsights + reportInsights, фикстура 87.5/7.5/5.0) – 2 passed.

МУТАЦИЯ ВНЕСЕНА: src/lib/format-numbers.js:formatChannelSharePct – toFixed(1)→toFixed(0) (положительный контроль обоих новых vitest-файлов).
Результат мутации: 2 файла / 5 тестов – ВСЕ покраснели («88%» вместо «87.5%», см. Projects/_pytest.. нет, см. вывод vitest bz3b4x1js) – помощник реально проверяется тестами, не мёртвый обвес.
МУТАЦИЯ ОТКАЧЕНА: toFixed(0)→toFixed(1) обратно (по срочному указанию team-lead – другая сессия стартовала в этом же дереве, мутация не должна висеть). Прогоняю оба файла точечно ещё раз для подтверждения зелёного после отката.
