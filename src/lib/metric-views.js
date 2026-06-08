/**
 * metric-views.js — единый фронт-селектор отображаемых ПОСТ-train производных
 * метрик качества модели (MQS и effective ratio).
 *
 * ПОЧЕМУ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ (INV-50, анти-рецидив, 2026-06-07):
 * honesty-баг нечестного ratio всплывал ТРИЖДЫ (MQS-score → insight-панель →
 * письмо клиенту), несмотря на 2 точечных фикса — потому что одно и то же число
 * жило в N расходящихся местах, и баг всегда был в шве, где пост-train дисплей
 * читал ОПТИМИСТИЧНУЮ pre-train метрику вместо честной backend-effective.
 * Греп «всех мест» ловит существующие N, но не будущий N+1. Поэтому ВСЕ
 * пост-train потребители читают score/ratio ТОЛЬКО через эти селекторы →
 * N+1-й слой расхождения физически невозможен. Греп-гард
 * (metric-views.guard.test.js) запрещает сырой доступ `mqs.score`/`metrics.ratio`
 * в пост-train компонентах.
 *
 * ГРАНИЦА: pre-train метрики шага «Валидация» (validationHeaderMetrics.ratio =
 * obs/назначенные колонки ≈ 4.4; computeValidationMetrics().mqs прогноз) —
 * это ДРУГИЕ метрики, легитимны на своём экране и НЕ ходят через этот селектор.
 * Сюда они попадают лишь как явный `fallbackRatio` (помечается source='fallback').
 *
 * Источник истины обеих метрик — backend `sidecar/econometrica/utils/
 * diagnostics.py::generate_diagnostics_summary` (mqs.score капнут по эффективному
 * ratio; metrics.ratio = obs/effective_params, posterior contraction).
 */

/**
 * @typedef {Object} MqsView
 * @property {number} score        честный backend MQS (cap по эффективным параметрам)
 * @property {string} tierLabel    «Отличное»/«Хорошее»/…
 * @property {number|null} thinnessCap  50/70 если cap применён, иначе null
 * @property {string|null} color   цвет тира (для бейджа)
 */

/**
 * Единый пост-train источник MQS. Читать ЭТО, не `diagnostics.mqs.score`
 * напрямую: фронт больше НЕ раскапывает score по media-ratio (прежде выдавал
 * «Отличное 86» вместо честного «Хорошее 70»).
 * @param {any} diagnostics
 * @returns {MqsView|null} null когда модель не обучена / mqs отсутствует
 */
export function mqsView(diagnostics) {
  const mqs = diagnostics?.mqs;
  if (mqs == null) return null;
  const score = Number(mqs.score ?? NaN);
  if (!Number.isFinite(score)) return null;
  return {
    score,
    tierLabel: mqs.tier_label ?? '',
    thinnessCap: mqs.thinness_cap ?? null,
    color: mqs.color ?? null,
  };
}

/**
 * @typedef {Object} RatioView
 * @property {number} ratio        эффективный (obs/effective_params) ИЛИ fallback
 * @property {boolean} isThin      ratio < 4 (риск переобучения / широкие CI)
 * @property {boolean} isVeryThin  ratio < 2 (критически мало данных)
 * @property {number|null} nominal номинальный ratio (obs/n_params), прозрачность
 * @property {'effective'|'fallback'} source  откуда взято значение
 */

/**
 * Единый пост-train источник ratio наблюдений-к-параметрам. ПРИОРИТЕТ —
 * честный backend effective ratio (`diagnostics.metrics.ratio`). pre-train
 * media-ratio (`validationHeaderMetrics.ratio`) допустим ТОЛЬКО как `fallbackRatio`
 * и помечается `source='fallback'`. Так нечестный media-ratio (4.4) физически не
 * вытеснит честный effective (2.4) ни в одном пост-train дисплее, и `isThin`
 * (варнинг переобучения) совпадает с MQS-cap и backend-вердиктом.
 * @param {any} diagnostics
 * @param {number|null} [fallbackRatio]  pre-train ratio (только fallback)
 * @returns {RatioView|null} null когда нет ни backend-, ни fallback-значения
 */
export function ratioView(diagnostics, fallbackRatio = null) {
  // metrics.ratio (актуальный backend) приоритетно; diagnostics.ratio —
  // legacy-flat путь (старые pickle без metrics-обёртки), тот же effective ratio,
  // НЕ pre-train (pre-train media-ratio в diagnostics никогда не живёт).
  const eff = diagnostics?.metrics?.ratio ?? diagnostics?.ratio;
  /** @type {number|null} */
  let ratio = null;
  /** @type {'effective'|'fallback'} */
  let source = 'effective';
  if (typeof eff === 'number' && Number.isFinite(eff) && eff > 0) {
    ratio = eff;
  } else if (typeof fallbackRatio === 'number' && Number.isFinite(fallbackRatio) && fallbackRatio > 0) {
    ratio = fallbackRatio;
    source = 'fallback';
  }
  if (ratio == null) return null;
  const nominal = diagnostics?.metrics?.ratio_nominal;
  return {
    ratio,
    isThin: ratio < 4,
    isVeryThin: ratio < 2,
    nominal: typeof nominal === 'number' && Number.isFinite(nominal) ? nominal : null,
    source,
  };
}
