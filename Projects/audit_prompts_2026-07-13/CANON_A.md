# Срез A — geo-эксперименты и калибровка MMM. Aurora Econometrica / econometrist

Цель: найти дельту между каноном RAG-библиотеки (тема «Эконометрика и статистика») и текущими
промптами кабинета econometrist. Правки НЕ вносятся — только находки-кандидаты на ревью Антона.

Целевой репо подтверждён: `Aurora_Econometrica_v230` (identifier `com.aurora.econometrica`,
remote `github.com/Ackold26/Aurora_Econometrica`) — действующий продукт, не архив.

Прочитанные файлы кабинета: `New_AI_Agency/econometrist/.claude/commands/pilot-design.md`,
`.../mmm-model.md`, `.../mmm-decomposition.md`, `.../CLAUDE.md` (кабинета).
Проверка по всему кабинету (`grep -i "гео|regio|geo"`): единственное упоминание geo-подхода во всём
кабинете — одна строка в `pilot-design.md` («Гео-сплит (альтернатива)»). Иерархической geo-модели,
TBR-метода, CausalImpact/BSTS нет НИГДЕ (ни в mmm-model, ни в mmm-decomposition, ни в mmm-optimize,
ни в LEGACY_COMMANDS.md).

---

## Аспект 1 — Дизайн geo-эксперимента (TBR, Vaver & Koehler 2011)

**Тип: GAP.**

**Что в промпте сейчас** (`pilot-design.md`, раздел «Параметры пилота», строка 28):
> «Гео-сплит (альтернатива): 2 региона одинакового размера – один на текущий план, другой на
> оптимальный. Плюсы – параллельное сравнение; минусы – нужны сопоставимые регионы»

Это одна строка без метода: нет рандомизации, нет расчёта нужного числа гео, нет оценки
статистической мощности/ширины доверительного интервала ДО запуска, нет формальной модели
для анализа результата (просто «сравнить регионы»).

**Что канон требует:**
1. **Рандомизация гео** с возможным стратифицированием по размеру снижает ширину CI на ~10%.
2. **Формальная TBR-модель** (Time-Based Regression, Equation 1) с pretest/test периодами для
   анализа результата, а не наивное сравнение средних по двум регионам.
3. **Оценка мощности эксперимента ДО запуска** — раздел 5 «Design» показывает, как из pretest-данных
   заранее спрогнозировать ширину ROAS-интервала как функцию длины теста, test fraction и величины
   ad spend differential, и сравнить сценарии дизайна.

**Точная цитата** (прочитан весь текст книги, `Vaver_Koehler_2011...md`, разделы 2–3 и 5):
> «The next step is to randomly assign each geo to a control or treatment condition. Randomization
> is an important component of a successful experiment as it guards against potential hidden
> biases... It also may be helpful to constrain this random assignment in order to better balance
> the control and treatment geos across one or more characteristics or demographic variables. For
> example, we have found that grouping the geos by size prior to assignment can reduce the confidence
> interval of the ROAS measurement by 10%, or more.»

> «Design is a crucial aspect of running an effective geo experiment. Before beginning a test, it is
> helpful to understand how characteristics such as experiment length, test fraction, and magnitude
> of ad spend differential will impact the uncertainty of the ROAS measurement. This understanding
> allows for the design of an effective and efficient experiment... This process can be repeated
> across a number of different scenarios to evaluate and compare designs.»

Формальная модель для анализа (для справки, не для промпта дословно): `y_i,1 = β0 + β1·y_i,0 +
β2·δ_i + ε_i`, где `δ_i` — ad spend differential (Equation 1), а ROAS = β2 с доверительным
интервалом, сужающимся по мере накопления test-периода (Figure 2/5).

**Обоснование:** пилот в текущем виде — это по сути A/B «на глаз» без строгости рандомизации и без
предварительной оценки, хватит ли выбранных гео и длительности, чтобы вообще увидеть эффект
заявленного размера. Кабинет уже честен про статистическую значимость («короткий пилот не даст
правдоподобный диапазон уже 10%») — но это эмпирическое правило, не расчёт мощности. TBR даёт
инструмент оценить ДО запуска, а не гадать постфактум.

**РФ-контекст / применимость:** метод предполагает возможность geo-таргетинга рекламных кампаний
(digital, spot TV) — в РФ доступно для digital (Яндекс.Директ, VK Реклама — есть гео-таргетинг) и
частично для наружной/спот-ТВ. Для нацио­нальных кампаний без гео-таргетинга (федеральное ТВ без
региональных вставок) метод неприменим — важная оговорка, которой сейчас в промпте тоже нет.

**Размещение:** on-demand — это специфика ОДНОЙ команды (`pilot-design.md`), не сквозной принцип
кабинета. В `CLAUDE.md` (always-on) не место — раздувает системный промпт консультацией,
относящейся к одному сценарию из восьми команд.

---

## Аспект 2 — Калибровка MMM экспериментом (приоры / валидация модели)

**Тип: GAP (частичный) — механизм есть в общей форме (п.3.5 mmm-model.md), но без geo-специфики и
без явной связи с пилотом.**

**Что в промпте сейчас** (`mmm-model.md`, п. 3.5):
> «Калибровка priors из внешних источников. Если в inbox есть результаты A/B-теста, Geo-Lift или
> прошлого MMM по каналу – задай informative prior на β/ROAS этого канала с центром на внешней
> оценке (вноси как центр+разброс, не точку), тег [CALIBRATED]. Чем слабее данные канала, тем ценнее
> informative prior. Калибруй только из релевантного эксперимента того же бренда/категории (чужой
> рынок/период = смещение).»

Механизм калибровки приоров экспериментом уже заложен и методологически корректен (центр+разброс,
не точка; ограничение по релевантности бренда/категории). Это CONFIRM по своей сути.

**Чего не хватает — GAP:** нет обратной связи «пилот (`pilot-design.md`) → калибровка модели»
и нет формализованного объективного критерия качества калибровки (MAPE против эксперимента),
взвешенного вместе с точностью подгонки и разумностью декомпозиции — сейчас решение о том,
насколько сильно давить приор, полностью на усмотрение модели/кабинета, без метрики.

**Что канон добавляет сверх вшитого** (Robyn / Meta 2024, раздел 3.2 Model calibration, прочитан
полностью):
> «Robyn allows users to set two optimization objectives in addition to minimization of NRMSE:
> avoidance of extreme results... and minimization of calibration error, i.e., mean absolute
> percentage error (MAPE) against estimates from experiments or vetted attribution models...
> calibration serves as a method of identification that guides model estimations to align closer
> with a more accurate ground truth... This adjustment moves the estimates up the "incrementality
> spectrum," bringing them closer to RCT-based causal effect estimates.»

> «Note that, by default, the weights are set equally across objectives as (1, 1, 1) for NRMSE
> ("statistical error"), Decomp.RSSD ("business error"), and MAPE ("calibration error") respectively.»

**Обоснование:** канон формализует калибровку как ОДНУ из трёх взвешиваемых целей оптимизации
(наряду со статистической ошибкой подгонки и разумностью декомпозиции), а не только как настройку
приора вручную. Текущий промпт делает калибровку приора, но не даёт кабинету языка «насколько
хорошо модель совпала с экспериментом после переобучения» (MAPE.LIFT) — то есть нет шага
ПОСЛЕ пилота: пилот прошёл → есть факт → перекалибровать/провалидировать модель этим фактом
формальной метрикой, а не только субъективно.

**Важная оговорка:** движок Aurora Econometrica детерминированный (сам считает MCMC), кабинет
econometrist — только консультационный слой поверх готовых результатов («Сами вычисления MMM Claude
не выполняет»). Значит, эта находка релевантна не столько тексту консультационных промптов
econometrist, сколько ДВИЖКУ (Rust/Python sidecar) — за пределами того, что правит этот срез аудита.
Для кабинета единственное действие — явно завершить цикл «пилот → возврат факта → предложение
пересчитать/перекалибровать модель», чего сейчас в `pilot-design.md` нет (пилот заканчивается
чек-листом запуска, не описывает шаг «когда пилот завершён, дай факт обратно в /mmm-model»).

**Размещение:** on-demand, в `pilot-design.md` (раздел после «Чек-лист запуска» — что делать когда
пилот завершён) + возможно короткая ссылка в описании `/mmm-model` о повторном запуске с
CALIBRATED-приором из факта пилота. Не always-on — это шаг одного workflow, не сквозной принцип.

---

## Аспект 3 — Причинная оценка эффекта кампании (CausalImpact / BSTS, Brodersen 2015)

**Тип: GAP.**

**Что в промпте сейчас:** ничего. `pilot-design.md` предлагает сравнение «KPI в пилоте vs forecast
из модели при новом миксе» только как содержательное правило (выше/ниже правдоподобного диапазона
модели) — без метода, дающего контрфактуальный прогноз «что было бы без вмешательства» и
доверительный интервал вокруг самого эффекта. `mmm-decomposition.md` и остальные команды тоже не
содержат оценки инкрементального эффекта отдельной кампании через синтетический контроль.

**Что канон даёт** (Brodersen et al. 2015, прочитан Introduction + разделы 2–3 полностью):
> «This paper proposes to infer causal impact on the basis of a diffusion-regression state-space
> model that predicts the counterfactual market response in a synthetic control that would have
> occurred had no intervention taken place... state space models make it possible to (i) infer the
> temporal evolution of attributable impact, (ii) incorporate empirical priors on the parameters in
> a fully Bayesian treatment, and (iii) flexibly accommodate multiple sources of variation.»

> «The causal impact of a treatment is the difference between the observed value of the response and
> the (unobserved) value that would have been obtained under the alternative treatment... the causal
> effect of interest is the difference between the observed series and the series that would have
> been observed had the intervention not taken place.»

Ключевая практическая деталь для пилота: результат — не точка, а posterior-распределение эффекта с
расширяющимся во времени доверительным интервалом (чем дальше от начала вмешательства, тем шире),
и авторы прямо указывают порог значимости через пересечение нуля кумулятивным интервалом:
> «Here, the 95% credible interval of the cumulative impact crosses the zero-line about five months
> after the intervention, at which point we would no longer declare a significant overall effect.»

**Обоснование:** это ровно инструмент под задачу «прогноз→факт» из `pilot-design.md» — но нужен
control-ряд (необработанные гео/каналы/рынки), в отличие от TBR (Vaver-Koehler) BSTS/CausalImpact НЕ
требует случайного эксперимента и подходит даже когда гео-сплит невозможен (единая национальная
кампания без geo-таргетинга) — это восполняет именно тот пробел, где TBR из Аспекта 1 неприменим по
РФ-специфике (федеральное ТВ). Сейчас правило пилота «выше/ниже нижней границы правдоподобного
диапазона» — это эвристика без формальной контрфактуальной модели и без явного учёта тренда/сезонности
пост-фактум, то есть точность оценки инкрементального эффекта пилота ниже, чем могла бы быть.

**РФ-контекст:** метод общий (эконометрика временных рядов), юрисдикционных ограничений нет; нужны
непострадавшие control-ряды (другие бренды категории, немедийные регионы, экономические индикаторы) —
доступность зависит от данных клиента, это ограничение практики, не канона.

**Размещение:** on-demand — новый под-раздел `pilot-design.md` «Как измерять» (сейчас там короткая
эвристика без метода) ИЛИ отдельная новая команда `/pilot-evaluate` (пост-фактум оценка пилота).
Само наличие такого шага в принципе стоит явно перечислить в `CLAUDE.md` в списке консультационных
команд, если решат делать отдельную команду — но сам метод и формулы не имеют смысла тащить в
always-on.

---

## Аспект 4 — Geo-уровневая иерархия (Sun 2017)

**Тип: GAP.**

**Что в промпте сейчас:** региональная декомпозиция не поддерживается нигде в кабинете. Диагностика,
декомпозиция и оптимизация в `mmm-model.md`/`mmm-decomposition.md`/`CLAUDE.md` — целиком
национальный/агрегированный уровень (один временной ряд KPI, каналы, adstock). Контракт данных
(`CLAUDE.md`, «Контракт данных») тоже не предусматривает секцию по гео в блоке «Данные проекта».

**Что канон даёт** (Sun 2017, Abstract + Introduction, прочитаны полностью):
> «Current practice usually utilizes data aggregated at a national level, which often suffers from
> small sample size and insufficient variation in the media spend. When sub-national data is
> available, we propose a geo-level Bayesian hierarchical media mix model (GBHMMM), and demonstrate
> that the method generally provides estimates with tighter credible intervals compared to a model
> with national level data alone... Under some weak conditions, the geo-level model can reduce ad
> targeting bias.»

> «The geo-level variability in the data is crucial for the geo-level model to outperform a
> national-level model... The marketing spend at the geo level generally has a wider range than that
> at the national level, which is critical to MMM as insufficient variation often leads to
> extrapolation issues.»

**Обоснование:** это ПРЯМОЕ попадание в существующий, уже вшитый в кабинет принцип
«Запрет экстраполяции за наблюдаемый диапазон» (`CLAUDE.md`, п.3: «Кривую отклика нельзя достраивать
за пределы наблюдённых затрат... Chan & Perry 2017») — Sun 2017 даёт РЕШЕНИЕ именно этой проблемы:
если данные есть на гео-уровне, диапазон трат шире и экстраполяция требуется реже. Сейчас кабинет
только диагностирует проблему узкого диапазона (тег [ЭКСТРАПОЛЯЦИЯ]), но не предлагает Geo-уровневую
иерархию как выход, когда данные это позволяют. Также совпадает с тонким-рядом-смещает-кривую
(п.3, Jin 2017) — geo-уровень увеличивает эффективный размер выборки без сбора данных за более
длинный период.

**Важная оговорка (SHIFTED-DOMAIN, не чистый GAP):** это не консультационная правка текста, а
архитектурное расширение ДВИЖКА (сам GBHMMM — hierarchical model в PyMC, не то, что кабинет
econometrist может «посоветовать» без данных на входе). Контракт данных кабинета сейчас в принципе
не транспортирует гео-разрез (`decomposition`/`optimization` секции блока — только по каналам и
времени, не по регионам). Значит находка на грани домена этого среза (промпты consultant-уровня) и
домена движка/архитектуры данных — фиксирую как GAP уровня продукта, не как правку одного файла
промпта.

**Размещение:** если Антон решит делать региональную декомпозицию — это НЕ бюджет CLAUDE.md
econometrist-кабинета, а отдельная фича движка (новая секция контракта данных `[geo-decomposition]`
+ новая консультационная команда `/geo-breakdown`). Для текущего среза — фиксация пробела, не диф
промпта.

---

## Сводка

Разобрано 4 аспекта: 3 чистых GAP (1, 3, 4) + 1 частичный GAP при существующем CONFIRM-ядре (2).
0 CONFLICT, 0 N/A. Наибольший рычаг — Аспект 1 (TBR-дизайн пилота) и Аспект 3 (CausalImpact пост-оценка) —
оба закрывают дыру ровно в той команде (`pilot-design.md`), которая уже существует и уже претендует
на эту роль, но делает её эвристически. Аспект 4 — архитектурный, не для этого среза применения.
