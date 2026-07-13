# Срез C — Awareness-моделирование, временные ряды, причинность/контроли

Методолог: aurora-upgrade, срез C. Продукт: Aurora Econometrica (Optimizer MMM).
Файл НЕ трогает промпты — только находки для ревью.

Файлы среза:
- `New_AI_Agency/econometrist/.claude/commands/awareness-forecast.md`
- `New_AI_Agency/econometrist/.claude/commands/awareness-to-sales.md`
- `New_AI_Agency/econometrist/.claude/commands/mmm-model.md`
- `New_AI_Agency/econometrist/CLAUDE.md`

---

## Аспект 1 — Стационарность/коинтеграция временных рядов (Neusser)

**Тип:** GAP

**Раздел:** `mmm-model.md` шаг 4 (Python-скрипт: Prophet-декомпозиция → adstock →
Hill saturation → PyMC-Marketing MMM), пункт 6 (проверка диагностики: R-hat,
divergences, PPC). Также `awareness-forecast.md` шаг 3 (байесовская регрессия
awareness_t = f(adstock(media)) + trend + seasonality + natural_decay) и
`awareness-to-sales.md` шаг 3 (Sales = α + β₁×f(awareness) + β₂×price + β₃×distribution + ε).

**Сейчас:** ни один из трёх промптов не содержит проверки стационарности рядов
(продажи, медиа-затраты, awareness) ни до, ни после Prophet-декомпозиции тренда.
Регрессия строится сразу на уровнях рядов через PyMC-Marketing/байесовскую
регрессию. Diagnostics Checklist в CLAUDE.md (R-hat/ESS/divergences/PPC/R²/MAPE)
проверяет СХОДИМОСТЬ модели, но не проверяет предпосылку регрессии на
нестационарных уровнях.

**Канон требует:** при регрессии двух интегрированных (нестационарных, unit-root)
рядов друг на друга без коинтеграции регрессия ложная (spurious) — высокий R²
и значимые коэффициенты возникают даже для независимых случайных блужданий.
Neusser демонстрирует это симуляцией Монте-Карло на N=1000 независимых парах
рядов. Решение не «просто взять первые разности» — если ряды коинтегрированы,
регрессия на УРОВНЯХ осмысленна и первые разности теряют долгосрочную связь;
если не коинтегрированы — нужна другая спецификация (ECM/разности).

**Точная цитата:** «The spurious regression problem cannot be circumvented by
first testing for a unit root in Yt and Xt and then running the regression in
first differences in case of no rejection of the null hypothesis. The reason
being that a regression in the levels of Yt and Xt may be sensible even when
both variables are integrated. This is the case when both variables are
cointegrated.» — *Time Series Econometrics*, Klaus Neusser.

**Обоснование:** MMM-ряды (недельные продажи, медиа-бюджеты, GRP) типично трендовые
и потенциально нестационарные (растущий бренд, растущие бюджеты по годам).
Prophet вычитает тренд/сезонность ДО подачи в PyMC-Marketing MMM, что снижает,
но не устраняет риск: Prophet-тренд — гладкая детерминированная кривая, а не
тест на unit root; остаточный ряд после вычитания тренда может остаться
интегрированным (например, при структурных сдвигах — см. фрагмент Neusser про
supF-тест на structural breaks). Ratio-чеклист CLAUDE.md (обучение/MQS-кэп/пилот)
контролирует ДОСТАТОЧНОСТЬ данных, но не их СТАЦИОНАРНОСТЬ — это ортогональная
предпосылка регрессии, нигде не поименованная. Risk: ложно высокий R²/MQS на
двух совместно растущих рядах (бюджет ТВ растёт год к году + продажи растут
год к году — типичный кейс) может пройти Diagnostics Checklist (R²>0.8, R-hat<1.05)
и получить тир Good/Excellent, будучи артефактом общего тренда, а не причинной
связи. Прямое пересечение с MMM Diagnostics Checklist п. «R² > 0.8 · MAPE < 15%» —
чек-лист не защищён от этого класса ошибки.

**Размещение:** `mmm-model.md` шаг 2 или 2.1 (рядом с backdoor-проверкой) —
добавить пункт проверки остаточного тренда/стационарности ПОСЛЕ Prophet-вычитания,
до спецификации MMM. Либо в CLAUDE.md MMM Diagnostics Checklist — отдельный
пункт «остаточная нестационарность после детрендирования не подтверждена».

---

## Аспект 2 — Awareness→sales как причинная цепь (Pearl / Hernán-Robins)

**Тип:** CONFLICT (частичный — промпт содержит оговорку, но не даёт процедуры)

**Раздел:** `awareness-to-sales.md` шаг 5, последний пункт «Ограничение
каузальности» (строка 29).

**Сейчас:** промпт уже помечает связь awareness→sales тегом `[ASSUMED-CAUSAL]`
и текстом признаёт: «front-door через медиатор awareness теоретически возможен,
но требует полной медиации эффекта media→продажи без общих неизмеримых причин —
в MMM почти всегда нарушено (awareness и продажи делят сезонность/дистрибуцию)».
Это качественно верная формулировка условий front-door (Pearl). Однако сама
регрессионная спецификация в шаге 3 — прямая нелинейная регрессия
Sales = α + β₁×f(awareness) + β₂×price + β₃×distribution + ε — не является ни
backdoor-adjustment (нет явного перечисления путей awareness↔sales, откуда взялись
именно price/distribution как закрывающий набор), ни front-door-процедурой
(две подрегрессии P(M|A)·P(Y|M,A) с суммированием, как того требует формула
front-door). То есть текст ПРИЗНАЁТ проблему идентификации, но КОД делает
обычную множественную регрессию и выдаёт β₁ как «эластичность» без явной
привязки к тому, какой идентификационной стратегии она соответствует.

**Канон требует:** front-door формула — не «регрессия с медиатором как
предиктором», а произведение/свёртка двух условных распределений: P(y|do(a)) =
Σ_m P(m|a) Σ_a' P(y|m,a') P(a'), при условии что M полностью медиирует эффект A→Y
и не делит неизмеримых причин ни с A, ни с Y. Обычная регрессия Y на A и M
одновременно (как в шаге 3 промпта: Sales на awareness и контроли) — это НЕ
front-door adjustment, а стандартная попытка «controlling for mediator»,
которая при наличии общего конфаундера U между A и Y (Technical Point 7.4)
даёт смещённую оценку.

**Точная цитата:** «The causal diagram in Figure 7.14 depicts a setting in which
the treatment A and the binary outcome Y share an unmeasured cause U, and in
which there is a variable M that fully mediates the effect of A on Y and that
shares no unmeasured causes with either A or Y. Under this causal structure, a
data analyst cannot directly [identify the effect via backdoor adjustment,
but can via front-door].» — *Causal Inference: What If*, Hernán & Robins,
Technical Point 7.4 (см. также Pearl, *Causal Inference in Statistics: A Primer*,
Theorem 3.3.1, Backdoor Criterion — определение блокировки путей и запрет
кондиционирования на потомках X).

**Обоснование:** промпт сам называет корректное условие (полная медиация,
отсутствие общих неизмеримых причин) и сам констатирует, что оно «в MMM почти
всегда нарушено» — но не делает вывод для СПЕЦИФИКАЦИИ модели. Раз front-door
неприменим и backdoor тоже не установлен явным перечислением путей (в отличие
от `mmm-model.md` шаг 2.1, где backdoor-проверка формализована пошагово — «(1)
перечисли пути... (2) классифицируй... (3) выдели backdoor... (4) закрой»),
у `awareness-to-sales.md` НЕТ аналогичной формализованной процедуры отбора
price/distribution как контролей — они попадают в модель по эвристике
«использовать если есть в данных» (шаг 2, строка 14), не по анализу графа.
Итог: тег `[ASSUMED-CAUSAL]` в выводе честен, но путь ДО тега (какая именно
регрессия дала число) не соответствует ни одной канонической identification
strategy — риск, что число «эластичность +1pp awareness = +X% продаж» читается
клиентом как оценка эффекта, хотя оговорка спрятана в конце промпта, а не в
структуре скрипта.

**Размещение:** `awareness-to-sales.md` шаг 2/3 — либо явный backdoor-перечень
путей awareness↔sales (по аналогии с `mmm-model.md` 2.1) перед тем как задавать
price/distribution как контроли, либо явное признание в результате (не только
в конце промпта, но как заголовок вывода): «оценка НЕ идентифицирует причинный
эффект awareness на продажи — только регрессионную ассоциацию при контроле на
price/distribution».

---

## Аспект 3 — Backdoor-контроли: что канон добавляет сверх вшитого

**Тип:** CONFIRM (с одним узким GAP)

**Раздел:** `CLAUDE.md` п.5 Red Teaming (Collider Bias, M-bias, Descendant/proxy
коллайдера — строки 55–57); `mmm-model.md` шаг 2.1 (формализованная
backdoor-процедура).

**Сейчас:** промпт уже содержит все три канонических паттерна из Pearl/Hernán-Robins:
collider bias («conditioning on a collider always induces an association between
its causes»), M-bias (пример «лояльность бренда»), descendant/proxy коллайдера
(`brand_search`). Формулировки в CLAUDE.md почти дословно совпадают с формулой
Hernán-Robins.

**Канон требует (сверх уже вшитого):** Hernán-Robins Chapter 18 (Technical Point,
Figure 18.6) явно разбирает ОБЩЕЕ заблуждение практиков — «commonly believed
that an estimator that adjusts for all available pretreatment covariates will
minimize the bias. However, this belief is wrong» — и демонстрирует, что даже
ДОТРЕАТМЕНТНАЯ (temporally preceding) переменная L может быть коллайдером и
внести selection bias при контроле. Это конкретно закрывает лазейку, которую
промпт не проговаривает явно: критерий «выбирай контроли, которые случились ДО
медиа-воздействия» (temporal precedence) — распространённая эвристика в
MMM-практике (control только на price/distribution/season, потому что они
«очевидно предшествуют») — САМ ПО СЕБЕ недостаточен, если такая переменная —
коллайдер на пути между двумя другими причинами.

**Точная цитата:** «it is commonly believed that an estimator that adjusts for
all available pretreatment covariates will minimize the bias. However, this
belief is wrong for two separate reasons. Consider the causal diagram of
Figure 18.6 (same as Figure 7.4), which includes a pre-treatment variable L.
Because L is a collider on a path from A to Y, adjusting for it will introduce
selection bias» — *Causal Inference: What If*, Hernán & Robins, Chapter 18.

**Обоснование:** CLAUDE.md п.5 перечисляет M-bias и collider примерами
(«лояльность бренда», «brand_search»), но не формулирует общий тезис «temporal
precedence ≠ безопасность контроля» — то есть Red Teaming вопросы у Claude
корректны как ИНСТАНС-проверки, но не содержат общего предупреждения, что
интуиция «control for everything measured before treatment» (стандартная
практика в MMM при выборе control-столбцов — price/distribution/search обычно
трактуют как «безопасные», потому что предшествуют) сама по себе ошибочна.

**Размещение:** `CLAUDE.md` п.5, после строки 57 (Descendant/proxy) — короткое
дополнение к Red Teaming: «pretreatment ≠ безопасный контроль» как отдельный
пункт наравне с M-bias.

---

## Аспект 4 — Awareness-моделирование количественно (S-кривая охвата, ESOV)

**Тип:** CONFLICT (числовое несоответствие цитируемой книге)

**Раздел:** `awareness-forecast.md` шаг 3, пункт «ESOV-модуль (Binet & Field):
ΔSOV → Δawareness (каждые 10pp ESOV ≈ 0.5-0.7pp роста SOM/год)» (строка 18).

**Сейчас:** промпт цитирует Binet&Field и приводит числовой коэффициент
«10pp ESOV ≈ 0.5-0.7pp роста SOM/год», но подписывает эффект как ΔSOV→Δawareness
(рост ЗНАНИЯ бренда), хотя число в скобках — про SOM (Share of Market, доля
РЫНКА), не про awareness.

**Канон требует:** каноническая формула Binet&Field — «annual market share growth
is proportional to 0.05 × ESOV» (то есть каждый 1pp ESOV ≈ 0.05pp роста SOM/год,
что на горизонте 10pp ESOV даёт ≈0.5pp роста SOM/год — нижняя граница диапазона
промпта верна для НИЖНЕЙ оценки, но источник — не про awareness, а прямо про
market share). Более того, в источнике указано, что связь УСИЛИЛАСЬ в цифровую
эпоху: «Campaigns prior to 2002 typically drove 0.03 points of annual share
growth per point of ESOV, whereas campaigns since [2002] drove...» (более
высокий коэффициент) — промпт даёт единую константу без разбивки по эпохе/каналу.

**Точная цитата:** «Market share growth per annum is strongly related to Extra
Share of Voice (ESOV) i.e. share of voice minus share of market... On average,
across all categories, annual market share growth is proportional to 0.05 x
[ESOV]» — *The Long and the Short of It*, Les Binet & Peter Field (Ten Thoughts
from Section 2, п.1 и п.7).

**Обоснование:** это не мелкая опечатка масштаба — ESOV в оригинале канона
объясняет ДИНАМИКУ ДОЛИ РЫНКА (SOM), а не awareness. Использовать этот
коэффициент как прокси для роста awareness — методологическая подмена: SOM и
awareness — разные метрики с разной динамикой (SOM зависит также от
дистрибуции, цены, промо; awareness — чисто когнитивная метрика трекинга).
Модуль называется «ESOV-модуль: ΔSOV → Δawareness», но канон даёт ΔSOV → ΔSOM.
Если цель шага — спрогнозировать awareness, ESOV-эвристика Binet&Field —
не тот механизм (она про долю рынка, не про трекинг знания бренда); если цель —
спрогнозировать SOM, то шаг находится не в том промпте (`awareness-forecast`,
не `awareness-to-sales`) и коэффициент дан без разбивки по эре/категории,
которую даёт сам источник.

**Что канон НЕ даёт (честный N/A):** прямой количественной модели «adstock
awareness» или явной S-кривой awareness от затрат в проверенных фрагментах
Binet&Field/Sharp/Katz не встретилось — обе книги про эффективность в терминах
SOM/продаж/fame, а не про построение регрессионной кривой awareness_t =
f(adstock). Weibull-adstock и natural decay в промпте (строки 17, 19) —
инженерное решение вне прочитанных фрагментов канона, оценить не могу
(гейт домена → N/A по этой части).

**Размещение:** `awareness-forecast.md` строка 18 — либо переименовать модуль
в «ESOV→SOM (не awareness)» и явно развести с задачей прогноза awareness,
либо, если удерживать связь с awareness, заменить ссылку на Binet&Field
коэффициент SOM на признание отсутствия канонической ESOV→awareness формулы
и пометить весь коэффициент `[ASSUMED]` вместо неявной атрибуции книге.

---

## Итог по срезу

4 из 4 аспектов дали содержательные находки: 1 чистый GAP (стационарность),
1 CONFLICT частичный (front-door признан текстом, но не отражён в спецификации
регрессии), 1 CONFIRM с узким дополнением (temporal precedence ≠ безопасность),
1 CONFLICT числовой (ESOV-коэффициент атрибутирован не той метрике). Никаких
находок РФ-специфики/ПДн в рамках среза C не обнаружено (N/A по INV-38/50 —
разве что INV-50 (честность метрик) косвенно усилен находкой 4: коэффициент
выдаётся под чужим ярлыком, что противоречит «не приукрашивать/не путать метрики».
