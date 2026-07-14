# Срез B — MCMC-диагностика и сходимость байесовской MMM. Aurora Econometrica / econometrist

Цель: найти дельту между каноном RAG-библиотеки (тема «Эконометрика и статистика») и текущими
промптами кабинета econometrist. Правки НЕ вносятся — только находки-кандидаты на ревью Антона.

Целевой репо подтверждён: `Aurora_Econometrica_v230` (identifier `com.aurora.econometrica`) —
действующий продукт, не архив.

Прочитанные файлы кабинета: `New_AI_Agency/econometrist/CLAUDE.md` (полностью, включая
«MMM Diagnostics Checklist» и «Model Quality Score»), `.claude/commands/mmm-model.md` (полностью,
legacy-расчётная команда — Claude сам пишет и запускает Python/PyMC-Marketing),
`.claude/commands/interpret-model.md` (полностью, консультационная команда без вычислений).

Книги: `Betancourt_2016_Diagnosing_HMC_EBFMI_arXiv_1604.00695`,
`Betancourt_2017_Conceptual_Introduction_to_HMC_arXiv_1701.02434`,
`Vehtari_2021_Improved_Rhat_ESS_Convergence_arXiv_1903.08008`, `Bayesian_Workflow_-_Andrew_Gelman`.

**Предварительный вывод:** кабинет — зрелый по этому срезу. R-hat 1.01/ESS≥400/E-BFMI≥0.3/
divergences-протокол/prior+posterior predictive check уже вшиты дословно с корректной атрибуцией
логики (не текстом цитаты, но по существу). Большинство аспектов — CONFIRM. Найдено 2 предметных GAP.

---

## Аспект 1 — Порог R-hat (rank-normalized, 1.01 vs старый 1.1)

**Тип: CONFIRM.**

**Что в промпте сейчас** (`CLAUDE.md` кабинета, MMM Diagnostics Checklist, строка 144):
> «rank-normalized split-R̂ < 1.01 для всех параметров (Vehtari et al. 2021; на Windows-Metropolis
> 1.01 недостижим → 1.05 минимум-приемлемый). Минимум 4 цепи»

и `mmm-model.md` строка 27: «R-hat < 1.05 для всех параметров» (шаг проверки диагностики).

**Канон:** Vehtari et al. 2021 действительно рекомендует rank-normalized split-R̂ < 1.01, явно
называя это ужесточением относительно старого порога Gelman & Rubin (1992) — 1.1/1.2.

**Точная цитата** (прочитан фрагмент, Section 2 «Recommendations for practice»):
> «In Section 4, we propose modifications to R̂ based on rank-normalizing and folding the posterior
> draws, only using the sample if R̂ < 1.01. This threshold is much tighter than the one recommended
> by Gelman and Rubin (1992), reflecting lessons learnt over more than 25 years of use... In addition,
> we recommend running at least four chains by default.»

**Обоснование:** кабинет уже на актуальном каноне (1.01), не на устаревшем 1.1 — гипотеза
«CONFLICT если кабинет на старом 1.1» из ТЗ не подтвердилась. Отступление до 1.05 явно и обоснованно
привязано к техническому ограничению Windows-Metropolis (PyTensor без C-компилятора → NUTS
недоступен/крайне медленный, см. `LEGACY_COMMANDS.md:21`) — не небрежность, а осознанный компромисс
с оговоркой в тексте. Минимум 4 цепи тоже уже требуется явно. Не менять.

**Размещение:** N/A (правки нет).

---

## Аспект 2 — ESS (bulk/tail, порог 400)

**Тип: CONFIRM.**

**Что в промпте сейчас** (`CLAUDE.md`, строка 140 и Diagnostics Checklist строка 145):
> «Помимо R-hat учитывай bulk-ESS и tail-ESS ≥ 400 (Vehtari et al. 2021 – при ESS < 400 сам R̂
> ненадёжен)... bulk-ESS и tail-ESS ≥ 400 для каждого параметра. Низкий ESS при хорошем R̂ = плохое
> перемешивание»

**Канон:** порог 400 — суммарный ESS по умолчательной настройке 4 цепей, ниже которого R̂
неинформативен.

**Точная цитата** (прочитан фрагмент, Section 2):
> «...with the minimum recommended setup of four parallel chains, the total ESS should be at least
> 400 before we expect R̂ to be useful.» Также рисунки 3/13/37 и текст: «The dashed line shows the
> recommended threshold of 400» — bulk-ESS и tail-ESS раздельно, оба против этого порога.

**Обоснование:** кабинет требует ОБА (bulk И tail), не только R-hat — это дельта сверх гипотезы ТЗ
«только R-hat» из аспекта 2. Полное соответствие канону, формулировка «сам R̂ ненадёжен» при низком
ESS дословно повторяет логику Vehtari. Не менять.

**Размещение:** N/A (правки нет).

---

## Аспект 3 — Divergences / E-BFMI (несмещённость HMC)

**Тип: CONFIRM.**

**Что в промпте сейчас** (`CLAUDE.md` Diagnostics Checklist, строки 146–147; `mmm-model.md` строка 28):
> «Divergences: при наличии движок отрабатывает протокол (target_accept↑ → non-centered при
> иерархии → проверка funnel). Только NUTS; на Metropolis divergences не возникают»
> «E-BFMI ≥ ~0.3 (energy diagnostic, только NUTS): низкий E-BFMI – патологичная геометрия, лечится
> non-centered параметризацией. На Windows-Metropolis недоступна – опора на R̂/ESS/trace»

**Канон:** порог E-BFMI 0.3 и рецепт non-centered параметризации — прямая рекомендация Betancourt.

**Точная цитата** (прочитан фрагмент, Betancourt_2017, §6.2 «Diagnosing Poor Exploration»):
> «Empirically, values of this energy Bayesian fraction of missing information below 0.3 have proven
> problematic, although more theoretical work is needed to formalize any exact threshold.»

Divergent transitions как индикатор смещения (не просто «плохая сходимость», а систематическая
недо-выборка областей высокой кривизны) — из Betancourt_2016/2017; protokol target_accept↑ →
non-centered — стандартная рекомендация того же корпуса (Betancourt & Girolami 2019, цитируется
внутри Vehtari 2021 как источник для funnel-геометрии).

**Обоснование:** аспект из ТЗ («проверяет ли кабинет divergences и E-BFMI как ОБЯЗАТЕЛЬНУЮ
диагностику несмещённости») — да, оба пункта чек-листа обязательны (не опциональны), с верно
привязанным порогом и верно описанным механизмом отказа (patalogical geometry → non-centered).
Оговорка про Windows-Metropolis (E-BFMI недоступна вне NUTS) технически корректна и уже явно
прописана. Не менять.

**Размещение:** N/A (правки нет).

---

## Аспект 4 — Bayesian workflow (Gelman): predictive checks и fake-data simulation

**Тип: GAP** (частичный — prior/posterior predictive check есть, SBC/fake-data parameter recovery
отсутствует).

**Что в промпте сейчас:**
- `mmm-model.md` шаг 4.5: «Prior predictive check ДО MCMC: `pm.sample_prior_predictive()` →
  проверь, что симулированные продажи неотрицательны и в правдоподобном бизнес-диапазоне...»
- `mmm-model.md` шаг 6: «Posterior predictive check: predicted vs actual» + Diagnostics Checklist
  строка 149 в CLAUDE.md: «Posterior predictive check: predicted vs actual совпадают»
- **Нет нигде**: симуляции данных из ИЗВЕСТНЫХ параметров ДО обучения на реальных данных, проверки,
  что модель/семплер восстанавливает эти известные параметры (parameter recovery / калибровка
  алгоритма вывода). Grep по `mmm-model.md` и `CLAUDE.md`: ни «fake data», ни «simulation-based
  calibration», ни «recover», ни «известные параметры» не встречаются.

**Канон:** Bayesian Workflow (Gelman) выделяет это в отдельную Chapter 14 «Simulation-based
calibration checking» — метод, качественно отличный от prior/posterior predictive check: тот
проверяет правдоподобие данных, SBC проверяет, что САМА процедура вывода (модель + семплер) не
смещена и корректно восстанавливает параметры, когда истина известна.

**Точная цитата** (прочитан фрагмент, Chapter 14):
> «There is a formal, and at times practical, issue when comparing the result of Bayesian inference,
> a posterior distribution, to a single (true) parameter vector... Using a single simulated dataset
> to test a model will not necessarily "work," even if the computational algorithm is working
> correctly... A more comprehensive approach is simulation-based calibration checking (SBC)... the
> model parameters are drawn from the prior; then data are simulated conditional on these parameter
> values; then the [model is fit and posterior compared to the known truth].»

Дополняющая цитата (Chapter 16, «Coding a series of models: simulated data of movie ratings»,
итоговый принцип метода):
> «At every step of the way, we understood our model and its inferences through fake-data
> simulation.»

**Обоснование:** это ровно тот класс ошибки, который prior/posterior predictive check НЕ ловит —
семплер может систематически недооценивать/переоценивать конкретный параметр (например, форму
Hill-saturation при коротком ряде — эта проблема уже описана в CLAUDE.md п.3 как «Jin 2017: занижение
до ~40%», но диагностируется только post-hoc через оговорку, а не проверяется fake-data прогоном ДО
работы с реальными данными клиента). Применимо именно к `mmm-model.md` — это legacy-команда, где
Claude сам пишет Python и запускает MCMC (не консультационная роль поверх готового движка), значит
технически может добавить шаг «прогнать пайплайн на синтетических данных с известным ROI/adstock до
финального прогона» без выхода за рамки роли кабинета.

**Риск/применимость:** полный SBC (сотни повторных прогонов с разными θ из приора) вычислительно
дорог и избыточен для одноразового MMM-пайплайна маркетингового агентства — это инструмент авторов
метода/пакетов, не типовой рабочий процесс консультанта на клиентских данных. Урезанная,
соразмерная версия — ОДИН прогон fake-data recovery (не полный SBC): смоделировать продажи из
модели с заданными коэффициентами (ROI/adstock), прогнать через тот же pipeline и проверить, что
posterior накрывает заданные значения — это соответствует «duck test» из той же книги (Ch.12) и
уже структурно близко к тому, что кабинет делает для prior predictive (только с фиксацией params).

**Размещение:** on-demand (в `mmm-model.md`, не в CLAUDE.md) — это шаг конкретно расчётного
пайплайна legacy-команды, не общий принцип, применимый к каждому клиентскому запросу; в always-on
CLAUDE.md раздувать не нужно, эффект на бюджет системного промпта был бы непропорционален пользе для
консультационных команд (7 из 8 команд в UI вообще не запускают MCMC).

---

## Аспект 5 (доп., не в исходном ТЗ) — Rank plots вместо trace plots

**Тип: GAP.**

**Что в промпте сейчас** (`CLAUDE.md` Diagnostics Checklist строка 148, Стандарт качества п.2):
> «Trace plots стабильны («мохнатая гусеница», нет дрейфа)»
> «Модель сходится?» – R-hat, ESS bulk/tail, trace»

**Канон:** Vehtari et al. 2021 прямо предлагает rank plots ВЗАМЕН trace plots как визуальную
диагностику по умолчанию — не дополнение, а замену с объяснённой причиной (trace plots «сжимаются
в мохнатое пятно» на длинных цепях и теряют информативность, rank plots устойчивы к длине цепи).

**Точная цитата** (прочитан фрагмент, Section 4.5 «Diagnostic visualizations»):
> «Extending the idea of using ranks instead of the original parameter values, we propose using rank
> plots for each chain instead of trace plots. Rank plots... are histograms of the ranked posterior
> draws (ranked over all chains) plotted separately for each chain. If all of the chains are
> targeting the same posterior, we expect the ranks in each chain to be uniform, whereas if one
> chain has a different location or scale parameter, this will be reflected in the deviation from
> uniformity... As compared to trace plots, rank plots don't tend to squeeze to a fuzzy mess when
> used with long chains.»

**Обоснование:** кабинет и Claude (при выполнении legacy-команды `mmm-model.md`) физически не
«смотрят» на графики глазами — диагностика идёт через текстовые метрики из pickle/xlsx, а
«стабильность trace plot» для LLM-агента без зрения на артефакт малопроверяема практически (нет
установленного способа прочитать PNG-график и оценить дрейф надёжнее, чем числовую rank-статистику).
Rank-based диагностика уже частично встроена (rank-normalized R̂), поэтому расширение на rank plots
органично продолжает тот же принцип и даёт агенту численно проверяемый критерий (доля попаданий в
равномерное распределение по бинам) вместо визуальной оценки «мохнатости», которую текстовый агент
объективно оценить не может.

**Риск/применимость:** практическая реализация не тривиальна для LLM без зрения — либо считать
количественный тест на равномерность рангов (Cramér–von Mises / χ²) программно и печатать число, либо
экспортировать rank-plot PNG и не полагаться на визуальную оценку самим Claude. Формулировка правки
должна это учитывать (заменить туманное «trace plots стабильны» на конкретную проверяемую метрику),
не просто подставить слово «rank plot» вместо «trace plot».

**Размещение:** always-on (CLAUDE.md Diagnostics Checklist) — это тот же слой, где уже живёт
R-hat/ESS/E-BFMI, правка точечная (одна строка чек-листа), нагрузка на бюджет пренебрежимая.

---

## Отброшено / N/A

- Полный аппарат SBC (Cook/Gelman/Rubin 2006, Talts et al. 2020) с формальным p-value χ²-тестом по
  батчу симуляций — избыточен для продукта; учтён urезанной формой в Аспекте 4.
- MCSE (Monte Carlo standard error, Vehtari §4.4) — отдельная метрика, не запрошена в ТЗ и не
  фигурирует в промптах; сигнал в библиотеку не требуется (Vehtari уже в корпусе), но как отдельный
  потенциальный аспект среза не разбирался — оставлен вне бюджета ≤8 находок этого среза.

---

## Сводка (строка на находку, лимит ≤8)

- [CONFIRM] R-hat порог — кабинет уже на 1.01/1.05-Windows, не устаревшем 1.1 — Vehtari 2021
- [CONFIRM] ESS bulk/tail ≥400 — оба требуются явно, не только R-hat — Vehtari 2021
- [CONFIRM] Divergences + E-BFMI≥0.3 — обязательная диагностика с верным протоколом — Betancourt 2016/2017
- [GAP] mmm-model.md — нет fake-data parameter recovery (SBC) до обучения на реальных данных — Bayesian Workflow (Gelman), Ch.14
- [GAP] CLAUDE.md Diagnostics Checklist — «trace plots стабильны» вместо rank plots / численного критерия — Vehtari 2021 §4.5

**Итог среза B:** 5 находок (3 CONFIRM, 2 GAP), 0 CONFLICT. Кабинет методологически зрелый по
MCMC-диагностике — оба GAP точечные и узкие (on-demand/малая always-on правка), не системный пробел.
