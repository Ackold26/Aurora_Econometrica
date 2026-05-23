# Aurora MMM Optimizer Glossary v1.3.0

**20 critical terms MVP.** Phase B расширит до полного словаря (~40 терминов).

Каждый термин: `term`, `short` (1 sentence), `long` (3-5 sentences), `example`, `related` (cross-links).

---

## A - Основы модели

### 1. MMM (Marketing Mix Modeling)
- **short**: Метод эконометрики, который оценивает вклад каждого маркетингового канала в продажи.
- **long**: MMM использует исторические данные (бюджеты или контакты каналов + продажи) и строит математическую модель, которая разлагает продажи на базовый уровень и вклад каждого канала. Главная цель - понять «какой канал приносит результат» и «куда лучше переложить бюджет». Aurora использует Bayesian подход (NumPyro + JAX) с нелинейными преобразованиями (adstock, Hill).
- **example**: «За год потратили 100 млн ₽ на рекламу. MMM показывает, что TV дал 35% продаж, performance digital - 25%, retail media - 18%, остальные каналы - 22%. Теперь можно перераспределить бюджет в более эффективные каналы».
- **related**: adstock, Hill saturation, decomposition.

### 2. Bayesian inference (байесовский вывод)
- **short**: Подход, когда вместо одной оценки параметра модель даёт распределение возможных значений (с вероятностями).
- **long**: Классическая регрессия (frequentist) даёт точечную оценку коэффициента - например, «ROI канала = 1.5». Bayesian даёт распределение: «ROI с вероятностью 50% от 1.3 до 1.7, с вероятностью 90% от 1.0 до 2.0». Это честнее отражает неопределённость, особенно при малой выборке. Aurora использует NumPyro для эффективного семплирования (MCMC NUTS).
- **example**: «Модель показывает: ROI TV = 2.1 ± 0.3 (90% CI [1.6, 2.7]). Это значит, что мы уверены в положительном ROI, но точная цифра может быть от 1.6 до 2.7».
- **related**: posterior, MCMC, prior, posterior CI.

### 3. Prior (априорные знания)
- **short**: Что мы предполагаем о параметре до того, как увидели данные.
- **long**: В Bayesian подходе перед тем как смотреть данные, мы задаём ожидания: «коэффициент adstock TV вероятно между 0.5 и 0.9» (есть индустриальные benchmarks). После обучения модели prior сочетается с данными, и получается posterior (обновлённое распределение). Хорошие priors стабилизируют модель на малой выборке. Aurora использует Trust Level 3 - иерархические priors отдельно для brand и performance каналов.
- **example**: «Brand каналы (TV, OOH) имеют prior на decay logit µ=0.7 (длинный effect). Performance (контекст, биддинг) - prior µ=−1.4 (короткий effect). После обучения posterior обычно близок к prior, но adjusted по данным».
- **related**: Bayesian, posterior, hierarchical priors.

### 4. Posterior (апостериорное распределение)
- **short**: Что мы знаем о параметре после того, как обновили prior данными.
- **long**: Posterior - результат комбинации prior + likelihood (вероятность данных при разных параметрах). В Aurora это распределение представлено posterior samples (MCMC chain). Posterior CI = доверительный интервал на основе квантилей этих samples. Узкий posterior = данные сильно информируют модель; широкий = данные мало добавляют к prior.
- **example**: «Posterior на ROI TV: P5=1.4, P50=2.1, P95=2.9. Это значит, что наиболее вероятный ROI - 2.1, но с 90% уверенностью он от 1.4 до 2.9».
- **related**: prior, MCMC, posterior CI, Bayesian.

### 5. Posterior CI (Confidence Interval)
- **short**: Диапазон, в который параметр попадает с заданной вероятностью (типично 90%).
- **long**: 90% CI значит «с вероятностью 90% истинное значение лежит в этом интервале». В MMM мы используем CI для отображения uncertainty: «ROI = 1.5×, 90% CI [1.0, 2.1]» - то есть могло быть и 1.0×, и 2.1×. Когда CI шире самой оценки, в Aurora появляется suffix «(широкий ROI-интервал)» - значит данных недостаточно для точного вывода.
- **example**: «Узкий CI: ROI 2.1× [2.0, 2.2] = очень уверенно. Широкий CI: ROI 2.1× [0.5, 4.0] = по сути ничего не можем сказать кроме того, что положителен».
- **related**: posterior, Bayesian, MCMC.

### 6. MCMC (Markov Chain Monte Carlo)
- **short**: Алгоритм сэмплирования из посterior распределения, который позволяет получить много возможных значений параметра.
- **long**: MCMC генерирует цепочку samples: каждый следующий сэмпл строится на основе предыдущего по правилам, гарантирующим сходимость к истинному posterior. Aurora использует NUTS (No-U-Turn Sampler) - современный вариант MCMC, который эффективно работает на сложных распределениях. Обычно 4 цепочки × 1000 samples = 4000 sample posterior chain.
- **example**: «MCMC за ~2 минуты сэмплирует 4000 возможных значений β для каждого канала. На их основе считаются posterior CI и все downstream метрики».
- **related**: Bayesian, posterior, R-hat.

### 7. R-hat (Gelman-Rubin convergence diagnostic)
- **short**: Метрика, которая показывает, сошёлся ли MCMC. Значение < 1.05 = OK.
- **long**: R-hat сравнивает разброс между разными цепочками MCMC с разбросом внутри одной цепочки. Если они близки - все цепочки сошлись к одному распределению (модель валидна). Если R-hat > 1.05 - цепочки ещё не consistent, модель надо перезапустить с большим количеством samples или проверить identifiability. В Aurora отображается на шаге Model.
- **example**: «R-hat = 1.02 для всех β → OK. R-hat = 1.15 → не валидно, нужно больше samples или fix priors».
- **related**: MCMC, convergence.

## B - Нелинейные преобразования

### 8. Adstock (запаздывающий эффект)
- **short**: Эффект рекламы не исчезает мгновенно - он постепенно затухает с течением времени.
- **long**: Реклама на этой неделе влияет на продажи не только этой недели, но и следующих 2-12 (зависит от категории и канала). Geometric adstock - стандартная форма: `adstocked_t = X_t + decay × adstocked_{t-1}`. Aurora также поддерживает Weibull adstock - более гибкая форма с peak time + tail decay. Brand каналы (TV) имеют длинный adstock (decay 0.6-0.9), performance - короткий (0.1-0.3).
- **example**: «Если TV на неделе 1 = 100 GRP, decay = 0.7, то на неделе 2 ещё ощущается 70 GRP «остаточного», на неделе 3 - 49, и т.д. Полный effect TV дотягивается до 5-10 недель».
- **related**: Weibull adstock, Hill saturation.

### 9. Hill saturation (нелинейное насыщение)
- **short**: Каждый дополнительный рубль рекламы даёт меньше эффекта, чем предыдущий - это закон убывающей отдачи.
- **long**: Hill function: `f(X) = X / (K + X)` - нормирована между 0 и 1, K - половинная точка насыщения. При X ≪ K канал недонасыщен (каждый рубль даёт почти полный эффект). При X ≈ K - сбалансирован. При X ≫ K - перенасыщен (дополнительные рубли слабо дают результат). Светофор Aurora на шаге Optimize показывает положение каждого канала на Hill curve.
- **example**: «Performance канал с K=3M ₽: на текущем бюджете 8M ₽ канал перенасыщен (8>>3), дополнительные рубли мало дадут. Решение оптимизатора: перелить бюджет в недонасыщенные каналы».
- **related**: adstock, mROI, saturation traffic light.

### 10. mROI / mEffect (маржинальный эффект)
- **short**: Сколько даст следующий вложенный рубль (или показ / клик).
- **long**: В отличие от среднего ROI (общий эффект / общий бюджет), marginal - производная отклика по бюджету в текущей точке. Канал с высоким mROI = «вложи ещё рубль и получи много», низким = «канал перенасыщен, ещё рубль почти не нужен». Solver оптимизации перебалансирует бюджет до выравнивания mROI между каналами (Lagrange optimum).
- **example**: «Канал A: avg ROI = 1.8×, mROI = 0.5× (перенасыщен). Канал B: avg ROI = 1.5×, mROI = 2.3× (недонасыщен). Optimizer переложит часть бюджета из A в B».
- **related**: Hill saturation, ROI.

## C - Метрики оценки каналов

### 11. ROI (Return on Investment)
- **short**: Возврат на инвестицию - сколько ₽ выручки дал один ₽ затрат.
- **long**: ROI = вклад канала в продажи (₽) / затраты на канал (₽). Безразмерная метрика, сравнима между каналами с разной шкалой. ROI > 1.0 = канал окупается. В Aurora используется как главная метрика только для KPI=monetary (продажи в рублях / выручка). Для KPI=count (упаковки, лиды) ROI бессмыслен - используется CPU.
- **example**: «Канал TV: вклад 35М ₽, бюджет 25М ₽ → ROI = 1.4×, то есть каждый вложенный рубль вернул 1.4 рубля выручки».
- **related**: CPU, mROI, value_per_count_unit.

### 12. CPU (Cost Per Unit)
- **short**: Сколько ₽ затрат приходится на одну единицу целевой метрики (одну упаковку / лид / регистрацию).
- **long**: CPU = затраты на канал / прирост целевой count метрики, который дал этот канал. Используется когда KPI = count (немонетарный). Сравнивается с **value_per_count_unit** (маржа на упаковку, ценность лида, MRR на подписку): если CPU < value → канал прибыльный, если CPU > value → убыточный. Aurora показывает CPU для каждого канала и сравнивает с user-провереnned value.
- **example**: «Канал Performance: бюджет 4М ₽, прирост 80 000 упак продаж → CPU = 50 ₽/упак. Маржа = 80 ₽/упак → канал прибыльный (CPU < margin)».
- **related**: ROI, value_per_count_unit, KPI kind.

### 13. value_per_count_unit (ценность единицы)
- **short**: Сколько ₽ для бизнеса стоит одна единица целевой count-метрики.
- **long**: Для разных KPI label адаптируется: «Маржа на упаковку» (sales_packs), «Ценность лида» (leads), «MRR на подписку» (subscriptions), «Ценность выданной карты» (loyalty_cards), и т.д. Это пороговое значение для сравнения с CPU: если канал даёт upak за CPU выше value - он убыточен. Aurora может auto-suggest на основе данных (например, margin = sales_rub × (1 − COGS_ratio) / sales_packs).
- **example**: «sales_packs KPI, цена упаковки = 200 ₽, COGS = 40% → margin = 200 × 0.6 = 120 ₽/упак. Любой канал с CPU > 120 ₽/упак убыточен».
- **related**: CPU, KPI kind, count KPI.

### 14. Sales contribution share
- **short**: Доля канала в общих продажах (%).
- **long**: Единственная безразмерная метрика, которая корректно сравнивает каналы в режиме Эффективность (где деньги не в модели). Считается как (вклад канала / общие продажи) × 100%. Используется как главная метрика когда mode = Эффективность и cross-channel cost-effectiveness невозможен (разные физ. единицы каналов: показы, клики, GRP).
- **example**: «TV: вклад 35М ₽ из 100М ₽ общих → 35% share. OLV: вклад 20М ₽ → 20% share. Лидер - TV. Это сравнение работает независимо от того, в каких единицах подавали каналы».
- **related**: mode Эффективность, native units.

## D - Архитектура v1.3.0

### 15. KPI kind
- **short**: Тип целевой метрики: monetary (рубли) или count (штуки чего-то).
- **long**: В v1.3.0 KPI делятся на два класса. **monetary**: target в рублях (sales_rub, revenue, profit, GMV). Главная метрика канала - ROI. **count**: target в штуках (sales_packs, leads, registrations, loyalty_cards, subscriptions, app_installs, custom). Главная метрика канала - CPU vs value_per_count_unit. Вердикты «убыточный/окупаемый» работают в обоих, просто через разные формулы.
- **example**: «Проект с KPI = sales_packs → kpi_kind = count → CPU column, value_per_count_unit = маржа на упаковку. Проект с KPI = revenue → kpi_kind = monetary → ROI column».
- **related**: CPU, ROI, value_per_count_unit, count KPI.

### 16. Derived mode
- **short**: Режим модели (ROI / Эффективность / Вручную), который вычисляется автоматически на основе выбранных юзером метрик каналов.
- **long**: В v1.3.0 mode перестал быть explicit toggle (как в v1.2). Юзер выбирает KPI + per-channel input metric (бюджет vs показы) на шаге Валидация, и mode выводится: все ₽ → ROI, все физ. → Эффективность, смешанные → Вручную. Это совпадает с industry standard (Robyn, PyMC-Marketing). Senior эконометристы могут включить Expert Mode для явного выбора.
- **example**: «TV в ₽, OLV в показах, Performance в ₽ - derived mode = Вручную. Все 7 каналов в ₽ - derived mode = ROI».
- **related**: mode ROI, mode Эффективность, KPI kind.

### 17. Safe corridor
- **short**: Математически валидный диапазон бюджета / цели, в котором модель даёт надёжные рекомендации.
- **long**: Hill saturation параметры обучены на наблюдаемых значениях канала [X_min, X_max]. За пределами этого диапазона функция формально определена, но posterior CI расширяется кратно, оценки теряют точность. Aurora считает safe corridor per канал: `[max(P5, 0.5·µ), min(P95, 1.5·µ)]` (MVP формула на базе Robyn / Hanssens 2003 / Jin 2017). Аналогично для цели Goal-Seek. На слайдере Aurora отображает 🟢/🟡/🔴 зоны.
- **example**: «Канал TV: исторический бюджет [10М ₽, 30М ₽], среднее = 20М ₽. Safe corridor: [max(P5, 10М), min(P95, 30М)] = [10М, 30М]. Бюджет 50М ₽ - экстраполяция (red zone), рекомендации не валидны».
- **related**: Hill saturation, extrapolation warning, ADR-014.

### 18. Goal-Seek (inverse optimization)
- **short**: Дана цель продаж, найти минимальный бюджет, который её достигает.
- **long**: Двойственная задача к forward optimization. Forward: дан бюджет → max продажи. Inverse / Goal-Seek: дана цель S* → min бюджет B такой, что S(B) ≥ S*. Aurora использует бисекцию по бюджету (forward функция монотонна → ищем минимальный B где S(B) ≥ S*). Posterior CI на требуемый бюджет - через bracketing P10/P90 bands posterior. Если цель за пределами safe corridor - Aurora выдаёт «недостижимо» + альтернативу.
- **example**: «Текущие продажи 100М ₽. Цель: 110М ₽ (+10%). Goal-Seek: требуемый бюджет 95М ₽ (текущий 85М ₽), Δ=+12%. P(hit)=78%».
- **related**: forward optimize, safe corridor, bisection.

### 19. mode ROI vs mode Эффективность
- **short**: ROI = все каналы измеряются в ₽. Эффективность = все в физ. контактах.
- **long**: ROI mode: input - бюджеты каналов (₽), модель оценивает ROI в ₽/₽. Сильно зависит от точности бюджетных данных. Эффективность mode: input - показы / клики / GRP, модель оценивает sales share %. Подходит когда бюджеты «грязные» (бартер, in-kind, скидки), но трафик меряется точно. Mixed (Вручную) - per-channel выбор. В v1.3.0 mode выводится автоматически из per-channel input metrics.
- **example**: «Все 7 каналов в ₽ → ROI mode. TV в ₽, OLV в показах → Вручную mode. Все в показах/GRP → Эффективность mode».
- **related**: derived mode, KPI kind.

### 20. Hierarchical priors (Trust Level 3)
- **short**: Brand и Performance каналы имеют разные prior на adstock и эффект, потому что они работают по-разному.
- **long**: В v1.1.0 Aurora добавил иерархические priors per channel group. Brand каналы (TV, OOH, premium video) - длинный adstock (decay logit µ=0.7), prior на эффект через бренд-метрики. Performance (контекст, ретаргетинг, бартер performance) - короткий adstock (logit µ=−1.4), prior на effect более узкий. Mixed channels - среднее. Это улучшает identifiability и убирает «уравнивание» каналов разной природы.
- **example**: «TV в Aurora ожидает 4-12 нед эффекта, performance ожидает 1-3 нед. Если данные показывают обратное - посterior сместится, но prior помогает на малых выборках».
- **related**: prior, adstock, Bayesian.

---

## Cross-reference graph (для UI cross-links)

```
MMM → adstock, Hill, decomposition
Bayesian → prior, posterior, MCMC, R-hat
adstock → Hill, mROI
Hill → adstock, mROI, saturation
mROI → Hill, ROI, CPU
ROI → CPU, value_per_count_unit, mROI
CPU → ROI, value_per_count_unit, KPI kind
value_per_count_unit → CPU, count KPI
KPI kind → monetary, count, CPU, ROI
derived mode → mode ROI, mode Эффективность, KPI kind
safe corridor → Hill, extrapolation, ADR-014
Goal-Seek → forward optimize, safe corridor, bisection
mode ROI ↔ mode Эффективность → derived mode, KPI kind
hierarchical priors → prior, adstock, Trust Level 3
```

## Phase B candidates (выйти из MVP)

20+ дополнительных терминов для Phase B полного словаря:
- frequentist statistics, null hypothesis, p-value
- prediction interval, conformal prediction
- bootstrap, Delta method
- SLSQP solver, multi-start optimization
- DiD (difference-in-differences), causal inference
- synthetic control, counterfactual
- transfer learning, donor library, recipient brand
- BVAR, DLM, state-space models
- conformal jackknife+, distribution-free uncertainty
- prior predictive check, posterior predictive check
- elasticity, log-log model
- Pareto multi-objective optimization
- Trust Level 1/2/3 (full explanation)
- Weibull learnable, geometric vs Weibull adstock
- expert mode, mastery progression
- bundle schema, .aurora format
- granularity (daily/weekly/monthly)
- seasonality detection, autocorrelation
