/**
 * Aurora Econometrica - Glossary v1.3.0 (skeleton).
 *
 * 20 critical терминов MVP per docs/GLOSSARY_TERMS.md.
 * Stage 4 educational: full content + GlossaryPanel UI + Ctrl+K shortcut.
 *
 * Structure:
 *   term: { id, term, short, long, example, related: [] }
 *
 * Use:
 *   import { GLOSSARY, getTerm } from '$lib/glossary';
 *   const t = getTerm('hill_saturation'); // returns full term object or null
 */

/** @type {Record<string, {id: string, term: string, short: string, long: string, example: string, related: string[]}>} */
export const GLOSSARY = {
  mmm: {
    id: 'mmm',
    term: 'MMM (Marketing Mix Modeling)',
    short: 'Метод эконометрики, оценивающий вклад каждого маркетингового канала в продажи.',
    long: 'MMM использует исторические данные (бюджеты или контакты каналов + продажи) и строит математическую модель, которая разлагает продажи на базовый уровень и вклад каждого канала. Главная цель - понять «какой канал приносит результат» и «куда лучше переложить бюджет». Aurora использует Bayesian подход (NumPyro + JAX) с нелинейными преобразованиями (adstock, Hill).',
    example: 'За год потратили 100 млн ₽ на рекламу. MMM показывает: TV дал 35% продаж, performance digital - 25%, retail media - 18%. Теперь можно перераспределить бюджет в более эффективные каналы.',
    related: ['adstock', 'hill_saturation', 'decomposition'],
  },
  adstock: {
    id: 'adstock',
    term: 'Adstock (запаздывающий эффект)',
    short: 'Эффект рекламы не исчезает мгновенно - постепенно затухает с течением времени.',
    long: 'Реклама на этой неделе влияет на продажи не только этой недели, но и следующих 2-12. Geometric adstock - стандартная форма: adstocked_t = X_t + decay × adstocked_{t-1}. Brand каналы (TV) имеют длинный adstock (decay 0.6-0.9), performance - короткий (0.1-0.3).',
    example: 'TV на неделе 1 = 100 GRP, decay = 0.7 → неделя 2 ещё ощущается 70 GRP остаточного, неделя 3 - 49. Полный effect TV дотягивается до 5-10 недель.',
    related: ['hill_saturation', 'weibull_adstock'],
  },
  hill_saturation: {
    id: 'hill_saturation',
    term: 'Hill saturation (нелинейное насыщение)',
    short: 'Каждый дополнительный рубль рекламы даёт меньше эффекта, чем предыдущий - закон убывающей отдачи.',
    long: 'Hill function: f(X) = X / (K + X), нормирована между 0 и 1, K - половинная точка насыщения. При X ≪ K канал недонасыщен. При X ≈ K - сбалансирован. При X ≫ K - перенасыщен. Светофор Aurora на шаге Optimize показывает положение каждого канала.',
    example: 'Performance канал с K=3M ₽: на текущем бюджете 8M ₽ канал перенасыщен. Optimizer переложит бюджет в недонасыщенные каналы.',
    related: ['adstock', 'mroi', 'saturation_traffic_light'],
  },
  bayesian: {
    id: 'bayesian',
    term: 'Bayesian inference (байесовский вывод)',
    short: 'Подход, когда вместо одной оценки параметра модель даёт распределение возможных значений.',
    long: 'Frequentist даёт точечную оценку («ROI канала = 1.5»). Bayesian даёт распределение: «ROI с вероятностью 50% от 1.3 до 1.7». Это честнее отражает неопределённость, особенно при малой выборке. Aurora использует NumPyro для эффективного семплирования (MCMC NUTS).',
    example: 'Модель: ROI TV = 2.1 ± 0.3 (90% CI [1.6, 2.7]). Мы уверены в положительном ROI, но точная цифра может быть от 1.6 до 2.7.',
    related: ['posterior', 'mcmc', 'prior'],
  },
  prior: {
    id: 'prior',
    term: 'Prior (априорные знания)',
    short: 'Что мы предполагаем о параметре до того, как увидели данные.',
    long: 'В Bayesian подходе перед тем как смотреть данные, задаём ожидания: «коэффициент adstock TV вероятно между 0.5 и 0.9» (есть индустриальные benchmarks). После обучения prior сочетается с данными, и получается posterior. Хорошие priors стабилизируют модель на малой выборке.',
    example: 'Brand каналы prior на decay logit µ=0.7 (длинный effect). Performance - prior µ=−1.4 (короткий effect).',
    related: ['bayesian', 'posterior', 'hierarchical_priors'],
  },
  posterior: {
    id: 'posterior',
    term: 'Posterior (апостериорное распределение)',
    short: 'Что мы знаем о параметре после того, как обновили prior данными.',
    long: 'Posterior - результат комбинации prior + likelihood. В Aurora это распределение представлено posterior samples (MCMC chain). Узкий posterior = данные сильно информируют модель; широкий = данные мало добавляют к prior.',
    example: 'Posterior на ROI TV: P5=1.4, P50=2.1, P95=2.9. Наиболее вероятный ROI 2.1, с 90% уверенностью от 1.4 до 2.9.',
    related: ['prior', 'mcmc', 'posterior_ci'],
  },
  mcmc: {
    id: 'mcmc',
    term: 'MCMC (Markov Chain Monte Carlo)',
    short: 'Алгоритм сэмплирования из posterior распределения.',
    long: 'MCMC генерирует цепочку samples: каждый следующий строится на основе предыдущего по правилам, гарантирующим сходимость к истинному posterior. Aurora использует NUTS - современный вариант. Обычно 4 цепочки × 1000 samples = 4000 sample posterior chain.',
    example: 'MCMC за ~2 минуты сэмплирует 4000 возможных значений β для каждого канала. На их основе считаются posterior CI.',
    related: ['bayesian', 'posterior', 'r_hat'],
  },
  r_hat: {
    id: 'r_hat',
    term: 'R-hat (Gelman-Rubin convergence diagnostic)',
    short: 'Метрика, которая показывает, сошёлся ли MCMC. Значение < 1.05 = OK.',
    long: 'R-hat сравнивает разброс между разными цепочками MCMC с разбросом внутри одной цепочки. Если они близки - все сошлись (модель валидна). R-hat > 1.05 → цепочки не consistent, надо больше samples или fix priors.',
    example: 'R-hat = 1.02 для всех β → OK. R-hat = 1.15 → не валидно.',
    related: ['mcmc'],
  },
  roi: {
    id: 'roi',
    term: 'ROI (Return on Investment)',
    short: 'Сколько ₽ выручки дал один ₽ затрат.',
    long: 'ROI = вклад канала в продажи (₽) / затраты на канал (₽). Безразмерная метрика, сравнима между каналами. ROI > 1.0 = канал окупается. В Aurora используется как главная метрика только для KPI=monetary. Для KPI=count ROI бессмыслен - используется CPU.',
    example: 'TV: вклад 35М ₽, бюджет 25М ₽ → ROI = 1.4×.',
    related: ['cpu', 'mroi', 'value_per_count_unit', 'kpi_kind'],
  },
  cpu: {
    id: 'cpu',
    term: 'CPU (Cost Per Unit)',
    short: 'Сколько ₽ затрат приходится на одну единицу целевой метрики.',
    long: 'CPU = затраты на канал / прирост целевой count метрики. Используется когда KPI = count (немонетарный). Сравнивается с value_per_count_unit: если CPU < value → канал прибыльный, если CPU > value → убыточный.',
    example: 'Performance: бюджет 4М ₽, прирост 80 000 упак → CPU = 50 ₽/упак. Маржа = 80 ₽/упак → канал прибыльный.',
    related: ['roi', 'value_per_count_unit', 'kpi_kind'],
  },
  value_per_count_unit: {
    id: 'value_per_count_unit',
    term: 'value_per_count_unit (ценность единицы)',
    short: 'Сколько ₽ для бизнеса стоит одна единица целевой count-метрики.',
    long: 'Для разных KPI label адаптируется: «Маржа на упаковку» (sales_packs), «Ценность лида» (leads), «MRR на подписку» (subscriptions), и т.д. Пороговое значение для сравнения с CPU.',
    example: 'sales_packs, цена 200 ₽, COGS 40% → margin = 120 ₽/упак. Канал с CPU > 120 ₽/упак убыточен.',
    related: ['cpu', 'kpi_kind'],
  },
  sales_share: {
    id: 'sales_share',
    term: 'Sales contribution share',
    short: 'Доля канала в общих продажах (%).',
    long: 'Единственная безразмерная метрика, которая корректно сравнивает каналы в режиме Эффективность (где деньги не в модели). Считается как вклад канала / общие продажи × 100%. Используется как главная метрика когда cross-channel cost-effectiveness невозможен.',
    example: 'TV вклад 35М из 100М общих → 35% share. Лидер - TV. Сравнение работает независимо от единиц каналов.',
    related: ['mode_effectiveness', 'native_units'],
  },
  kpi_kind: {
    id: 'kpi_kind',
    term: 'KPI kind',
    short: 'Тип целевой метрики: monetary (рубли) или count (штуки чего-то).',
    long: 'monetary: target в рублях (sales_rub, revenue, profit, GMV). Главная метрика канала - ROI. count: target в штуках (sales_packs, leads, registrations, loyalty_cards, subscriptions, app_installs, custom). Главная метрика - CPU vs value_per_count_unit.',
    example: 'Проект с KPI = sales_packs → kpi_kind = count → CPU column, value_per_count_unit = маржа.',
    related: ['cpu', 'roi', 'value_per_count_unit'],
  },
  derived_mode: {
    id: 'derived_mode',
    term: 'Derived mode',
    short: 'Режим модели, который вычисляется автоматически из per-channel input metrics.',
    long: 'В v1.3.0 mode перестал быть explicit toggle. Юзер выбирает KPI + per-channel input на Валидации, mode выводится: все ₽ → ROI, все физ. → Эффективность, mixed → Вручную. Совпадает с industry standard (Robyn, PyMC-Marketing).',
    example: 'TV в ₽, OLV в показах, Performance в ₽ → derived mode = Вручную. Все 7 каналов в ₽ → derived mode = ROI.',
    related: ['mode_roi', 'mode_effectiveness', 'kpi_kind'],
  },
  safe_corridor: {
    id: 'safe_corridor',
    term: 'Safe corridor',
    short: 'Математически валидный диапазон бюджета / цели, в котором модель даёт надёжные рекомендации.',
    long: 'Hill saturation параметры обучены на наблюдаемых значениях [X_min, X_max]. За пределами posterior CI расширяется кратно. Aurora считает safe corridor per канал: max(P5, 0.5·µ) до min(P95, 1.5·µ) (MVP формула на базе Robyn / Hanssens 2003). На слайдере 🟢🟡🔴 zones.',
    example: 'TV: исторический бюджет [10М, 30М], среднее = 20М. Safe corridor: [10М, 30М]. Бюджет 50М - экстраполяция (red zone).',
    related: ['hill_saturation', 'goal_seek'],
  },
  goal_seek: {
    id: 'goal_seek',
    term: 'Goal-Seek (inverse optimization)',
    short: 'Дана цель продаж, найти минимальный бюджет, который её достигает.',
    long: 'Двойственная задача к forward optimization. Aurora использует бисекцию по бюджету (forward функция монотонна → ищем минимальный B где S(B) ≥ S*). Posterior CI на требуемый бюджет - через bracketing P10/P90 bands. Если цель за пределами safe corridor - выдаёт «недостижимо».',
    example: 'Текущие продажи 100М ₽. Цель: 110М ₽ (+10%). Goal-Seek: требуемый бюджет 95М ₽, Δ=+12%. P(hit)=78%.',
    related: ['forward_optimize', 'safe_corridor'],
  },
  mode_roi: {
    id: 'mode_roi',
    term: 'Mode ROI',
    short: 'Режим, в котором все каналы измеряются в ₽.',
    long: 'Input - бюджеты каналов (₽), модель оценивает ROI ₽/₽. Сильно зависит от точности бюджетных данных. В v1.3.0 mode выводится автоматически из per-channel input metrics.',
    example: 'Все 7 каналов в ₽ → ROI mode → ROI columns в декомпозиции.',
    related: ['derived_mode', 'mode_effectiveness', 'roi'],
  },
  mode_effectiveness: {
    id: 'mode_effectiveness',
    term: 'Mode Эффективность',
    short: 'Режим, в котором все каналы измеряются в физических контактах.',
    long: 'Input - показы / клики / GRP, модель оценивает sales share %. Подходит когда бюджеты «грязные» (бартер, in-kind, скидки), но трафик меряется точно. Cross-channel сравнение только через share %.',
    example: 'Все каналы в показах/GRP → Эффективность mode → share columns вместо ROI.',
    related: ['derived_mode', 'mode_roi', 'sales_share'],
  },
  hierarchical_priors: {
    id: 'hierarchical_priors',
    term: 'Hierarchical priors (Trust Level 3)',
    short: 'Brand и Performance каналы имеют разные prior, потому что работают по-разному.',
    long: 'В v1.1.0 Aurora добавил иерархические priors per channel group. Brand каналы (TV, OOH, premium video) - длинный adstock (decay logit µ=0.7). Performance - короткий (µ=−1.4). Это улучшает identifiability на малых выборках.',
    example: 'TV ожидает 4-12 нед эффекта, performance - 1-3 нед. Если данные показывают обратное - posterior сместится.',
    related: ['prior', 'adstock', 'bayesian'],
  },
  mroi: {
    id: 'mroi',
    term: 'mROI / mEffect (маржинальный эффект)',
    short: 'Сколько даст следующий вложенный рубль (или показ / клик).',
    long: 'Производная отклика по бюджету в текущей точке (vs средний ROI = общий эффект / общий бюджет). Канал с высоким mROI = «вложи ещё рубль и получи много», низким = перенасыщен. Solver оптимизации перебалансирует бюджет до выравнивания mROI между каналами (Lagrange optimum).',
    example: 'Канал A: avg ROI 1.8×, mROI 0.5× (перенасыщен). Канал B: avg ROI 1.5×, mROI 2.3× (недонасыщен). Optimizer переложит из A в B.',
    related: ['hill_saturation', 'roi'],
  },
};

/**
 * Get term object by ID. Returns null if not found.
 * @param {string} termId
 * @returns {object | null}
 */
export function getTerm(termId) {
  return GLOSSARY[termId] ?? null;
}

/**
 * Get all terms as array (for search/listing UI).
 * @returns {Array<object>}
 */
export function getAllTerms() {
  return Object.values(GLOSSARY);
}

/**
 * Search terms by text query (in term name + short description).
 * @param {string} query
 * @returns {Array<object>}
 */
export function searchTerms(query) {
  if (!query) return getAllTerms();
  const q = query.toLowerCase();
  const all = /** @type {Array<{id: string, term: string, short: string, long: string, example: string, related: string[]}>} */ (getAllTerms());
  return all.filter(
    (t) =>
      t.term.toLowerCase().includes(q) ||
      t.short.toLowerCase().includes(q)
  );
}
