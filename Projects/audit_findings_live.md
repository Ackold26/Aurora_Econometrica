## s55-fix (28.09) – аудит 942c4f7b..4101e8a0
старт: 2026-09-28 10:34:55
финиш: 2026-09-28 10:49:23 – итог C0 H0 M0 L3, отчёт AUDIT_s55_fix.md
sev | file:line | суть | сценарий
Low (переоценено с Medium) | engines/planning.py:_row_is_total | хвостовая строка «Среднее»/«Average» (средние по столбцам) не распознаётся: нет слова, суммы не совпадают; проверка данных – status=warning без критической | зонд det_probe P5/P5b/P5c → [], det_probe2 avg_date_label/avg_other_label → warning; дальше по чтению modeler.py:487 – падение разбора даты (подпись в колонке даты) или лишний период (дата пуста) – не прогонялось
повтор L-1 (долг, не новая) | engines/planning.py:214 | номер строки занижен для CSV с пустыми строками | зонд: blank_mid.csv 22 vs 23, blank_before_total.csv 22 vs 24; xlsx верно
Low | planning.py:_row_is_total | примечание со словом «сумм…/итог…» и хотя бы одним числом в строке – ложный отказ | зонд P16: date='* суммы за 4 недели', tv=4 → reason=word
Low | aurora_pptx/builder.py:2134-2150 | при надписи вместо диаграммы над пустой областью остаётся подпись «1.0× = безубыточность · выше = прибыльно» – ссылается на отсутствующие столбики | чтение кода + зонд m5_probe (сборка без падения, надпись есть)

## s51 (27.09)
старт: 2026-09-27 13:43:53
sev | file:line | суть | сценарий
Medium | src/lib/command-meta.js:167-172 (+ +layout.svelte:~190) | при недоступном/битом content-pack command-meta-data.json `_products` остаётся {} (command-meta.js:45) → известный продукт «econometrica» получает [] и кабинет econometrist исчезает; до правки JS отдавал уже отфильтрованный Rust-ом список (lib.rs:52) | get_content_pack rejects (подпись manifest устарела после правки pack без re-sign, CLAUDE.md §18) или JSON.parse бросает → catch в layout → кабинетов 0, хотя Rust уже ограничил список правильно
Medium | sidecar/econometrica/tests/test_frontier_share_of_samples_text.py:490 | сторож по исходнику не ловит третий (цензурированный) очаг: регэксп `round\(\(?share_\w+[^)]*\*\s*100\)` не совпадает с `round((share_floor + share_ceiling) * 100)` – `[^)]*` упирается во внутреннюю `)` | вернуть в frontier.py:~1158 прежний `round((share_floor + share_ceiling) * 100)` → тест зелёный, «0%»/«100%» возвращаются в caveat
нет находок | builder.py s10_methodology / _big_number | зонд hier+wide_branch, +12 каналов переноса, OLS+hier+wide → check() = [] | —
нет находок | report.rs Spend vs Effect | значения статические (не формулы), pct_fmt 0.0%, знаменатель движка = сумма channel_total по всем каналам (decomposer.py:960,1128) | —
финиш: 2026-09-27 (аудит s51 завершён)

# Внешний аудит s50 – живой журнал находок

Диапазон: 21526770..HEAD (без Projects/). Формат: severity | file:line | суть | сценарий

Medium | src/lib/insights-rules.js:1607,1684,1830,2755 + src/lib/components/pipeline/ReportStep.svelte:280,397,506 | доля лидера на экранах приложения всё ещё `contribution_pct.toFixed(0)` («88%»), а карточка DecomposeStep и отчёт теперь «87.5%» – цель «одно число на всех поверхностях экрана» не достигнута | decompose с лидером contribution_pct=87.5: InsightsPanel «Главный драйвер: Канал A (88% от медиа-вклада)» / «Высокая концентрация … 88%», DecomposeStep «Канал A даёт 87.5%», отчёт 87.5
Medium | sidecar/econometrica/engines/narrative_adapter.py:414-415 + aurora_html S7 (strings s07_dominant/s07_top_n) + tests/test_channel_share_single_source.py:680,691 | доля в МЕДИА-вкладе подписана как доля «продаж» («он даёт 87.5% продаж»), класс B1-fix R-12; новый сторож закрепляет неверную подпись ассертом | медиа 38% продаж, лидер 87.5% медиа-вклада → реально ~33% продаж, заголовок S7 говорит 87.5% продаж
Medium | sidecar/econometrica/aurora_pptx/builder.py:894-905,1757-1764 | крупное число «100.0%» (одноканальный портфель или лидер ≥99.95) наезжает на подпись на 0.2" – дефект известен (strict xfail), но уходит клиенту в поставку | проект с одним каналом → слайд 4 «100.0%» пересекает подпись; check_overflow даёт issue
Наблюдение | engines/narrative_adapter.py:_merge_channels | при коллизии имён (TV / "tv ") строки таблицы суммируются в 70.0 (движок считает выпавший канал в знаменателе); прежде перенормировка завышала TV до 71.4 – новое поведение честнее, корень – сама коллизия; не находка | проба: TV 50/tv 30/Digital 15/Radio 5 → строки 50.0/15.0/5.0
Наблюдение | aurora_pptx/builder.py:899 | нижний предел кегля фактически 68, не 72 (140−8k проходит 76→68) | косметика, не находка
Проверено: pytest test_channel_share_single_source.py – 14 passed, 1 xfailed (strict); vitest decompose-share-percent – 4 passed
