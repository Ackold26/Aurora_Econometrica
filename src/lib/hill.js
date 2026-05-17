/**
 * Client-side Hill function for budget optimizer.
 * A1: gamma MUST be pre-scaled before calling hillFunction:
 *     gammaScaled = Math.max(params.gamma * currentSpend, 1)
 * This matches optimizer.py:58 - `max(p['gamma'] * current_spend[col], 1)`.
 *
 * @module hill
 */

/**
 * Hill saturation function. gamma must be pre-scaled.
 * @param {number} x - spend value
 * @param {number} alpha - steepness
 * @param {number} gamma - half-saturation point (pre-scaled)
 * @returns {number} saturated effect [0, 1]
 */
export function hillFunction(x, alpha, gamma) {
  const xSafe = Math.max(x, 0);
  const gSafe = Math.max(gamma, 1e-10);
  return Math.pow(xSafe, alpha) / (Math.pow(xSafe, alpha) + Math.pow(gSafe, alpha));
}

/**
 * Marginal ROI: derivative of Hill × beta. gamma must be pre-scaled.
 * @param {number} x - current spend
 * @param {number} alpha
 * @param {number} gamma - pre-scaled
 * @param {number} beta - channel coefficient
 * @returns {number}
 */
/**
 * Marginal ROI = ∂KPI/∂spend в точке x. Denomalization: returned value
 * - в нормализованной KPI-шкале (beta из priors). Чтобы получить в исходных
 * единицах KPI на рубль расхода, умножьте на y_std.
 *
 * @param {number} x
 * @param {number} alpha
 * @param {number} gamma
 * @param {number} beta
 * @param {{y_std?: number} | null} [normalization]
 * @returns {number}
 */
export function marginalROI(x, alpha, gamma, beta, normalization = null) {
  const xSafe = Math.max(x, 1e-10);
  const gSafe = Math.max(gamma, 1e-10);
  const numerator = alpha * Math.pow(gSafe, alpha) * Math.pow(xSafe, alpha - 1);
  const denominator = Math.pow(Math.pow(xSafe, alpha) + Math.pow(gSafe, alpha), 2);
  const normalized = beta * numerator / denominator;
  if (normalization && Number.isFinite(normalization.y_std)) {
    return normalized * (normalization.y_std ?? 1);
  }
  return normalized;
}

/**
 * Adstock carryover factor для flat per-period allocation. Approximates
 * `_flat_alloc_adstock_avg(x_pp, n) / x_pp` в `optimizer.py:42`. Для geometric
 * decay серии sum_{t=0..n-1} d^t / n converges к `1/(1-decay)` при n →∞.
 *
 * Frontend `predictKPI` использует это как multiplier на per_period spend
 * ДО Hill, чтобы input Hill match'ил backend `x_avg_adstock`. Без factor
 * frontend Hill input в 1.5-2× меньше backend для decay≈0.5 → understate lift.
 *
 * @param {number} decay - geometric decay parameter в [0, 1)
 * @param {number} n - число периодов
 * @returns {number} carryover factor ≥ 1
 */
function adstockFactor(decay, n) {
  if (!Number.isFinite(decay) || decay <= 0 || decay >= 1) return 1.0;
  if (!Number.isFinite(n) || n < 1) return 1.0;
  // closed-form mean of geometric adstock series:
  // mean = (1/n) * sum_{t=0..n-1} (1 - d^(t+1))/(1-d)
  //      = (1/(1-d)) * (1 - (d * (1 - d^n) / (n * (1-d))))
  // Для n >= 8 практически 1/(1-d). Используем точную формулу для small n.
  const dn = Math.pow(decay, n);
  const oneMinusD = 1 - decay;
  return (1 / oneMinusD) * (1 - (decay * (1 - dn)) / (n * oneMinusD));
}

/**
 * Predict total KPI from budget allocation.
 *
 * v2.1.0 (pilot D4 round 4 EDGE-D4-01 2026-05-17): добавлен `decays` параметр +
 * apply adstock carryover factor в perPeriodScaled. Без этого frontend Hill input
 * в 1.5-2× меньше backend для decay≈0.5 → currentKPI vs dData.total_sales
 * divergence 15-35%. Factor approximates `_flat_alloc_adstock_avg(x_pp, n)/x_pp`.
 *
 * v2.1.0 (pilot A3 round 3 REGR-2 2026-05-17): добавлен `nPeriods` параметр +
 * spend → per-period scale ДО Hill (matches backend `total_response_money` в
 * `optimizer.py:601-625` где `x_avg_raw = x_native_total / n_periods` сначала,
 * затем adstock+Hill, потом total × n_periods). Без этого frontend Hill
 * получал total_period_spend против per-period mean (adstock_mean_posterior)
 * → x/gamma off на n_periods× → saturation plateau → sliders unresponsive.
 *
 * v2.1.0 (pilot D2 round 2 R02 2026-05-17): добавлен `unitCostsAtTraining` -
 * pre-multiply spend ДО Hill для ADR-020 symmetry (mixed units pickles).
 *
 * @param {Record<string, number>} budgets - {channelName: spendValue в native units, TOTAL за все периоды}
 * @param {Record<string, {alpha: number, gammaScaled: number, beta: number}>} scaledParams
 * @param {{y_mean?: number, y_std?: number} | null} [normalization]
 * @param {Record<string, number> | null} [unitCostsAtTraining]
 * @param {number} [nPeriods] - default 1, backward compat.
 * @param {Record<string, number> | null} [decays] - {channelName: decay} для adstock factor.
 *        Если null - decay=0 fallback (adstock factor=1, no-op для noop adstock).
 *        Bayesian v1.2+: passes p.decay из channel_params. OLS DEFAULT_DECAY=0.5.
 * @returns {number}
 */
export function predictKPI(budgets, scaledParams, normalization = null, unitCostsAtTraining = null, nPeriods = 1, decays = null) {
  let total = 0;
  const n = (typeof nPeriods === 'number' && nPeriods >= 1) ? nPeriods : 1;
  for (const [ch, spend] of Object.entries(budgets)) {
    const p = scaledParams[ch];
    if (!p) continue;
    const ucTrain = (unitCostsAtTraining && typeof unitCostsAtTraining[ch] === 'number' && unitCostsAtTraining[ch] > 0)
      ? unitCostsAtTraining[ch] : 1.0;
    const decayCh = (decays && typeof decays[ch] === 'number' && decays[ch] > 0 && decays[ch] < 1)
      ? decays[ch] : 0;
    // Per-period spend × uc_train × adstock_factor → matches backend x_avg_adstock.
    const perPeriodScaled = ((spend * ucTrain) / n) * adstockFactor(decayCh, n);
    // Hill output - per-period saturation. Total contribution = sat × n_periods.
    total += p.beta * hillFunction(perPeriodScaled, p.alpha, p.gammaScaled) * n;
  }
  if (normalization && Number.isFinite(normalization.y_std) && Number.isFinite(normalization.y_mean)) {
    return total * (normalization.y_std ?? 1) + (normalization.y_mean ?? 0);
  }
  return total;
}

/**
 * Build scaledParams from raw channelParams + currentSpend.
 *
 * v2.1.0 (ADR-020 pilot A 2026-05-17): `meanForScale` параметр позволяет передать
 * `adstock_mean_posterior` per channel - тот же mean что backend использует для
 * Hill normalization. Без этого gammaScaled = γ × currentSpend approximation
 * расходится с backend для mixed-units каналов (TRPs где training mean в ₽-eq).
 *
 * @param {Record<string, {alpha: number, gamma: number, beta: number, adstock_mean_posterior?: number}>} channelParams
 * @param {Record<string, number>} currentSpend - {channelName: totalSpend}
 * @param {Record<string, number>} [meanForScale] - optional {channelName: adstock_mean_posterior or media_mean}.
 *        Если задан - используется как divisor scale (matches backend training).
 *        Если null/missing для канала - fallback к старому `γ × currentSpend`.
 * @returns {Record<string, {alpha: number, gammaScaled: number, beta: number}>}
 */
export function buildScaledParams(channelParams, currentSpend, meanForScale = undefined) {
  /** @type {Record<string, {alpha: number, gammaScaled: number, beta: number}>} */
  const result = {};
  for (const [ch, p] of Object.entries(channelParams)) {
    // Prefer adstock_mean_posterior (Bayesian v1.2+) from channel_params - canonical
    // backend Hill scale. Fallback к explicit meanForScale prop. Last fallback -
    // legacy approximation γ × currentSpend (works for monetary-only profiles).
    const meanFromParams = (p && typeof p.adstock_mean_posterior === 'number' && p.adstock_mean_posterior > 0)
      ? p.adstock_mean_posterior : null;
    const meanFromProp = (meanForScale && typeof meanForScale[ch] === 'number' && meanForScale[ch] > 0)
      ? meanForScale[ch] : null;
    const meanCanonical = meanFromParams ?? meanFromProp;
    const scale = meanCanonical !== null ? meanCanonical : (currentSpend[ch] ?? 0);
    result[ch] = {
      alpha: p.alpha,
      gammaScaled: Math.max(p.gamma * scale, 1),
      beta: p.beta,
    };
  }
  return result;
}

export const CHANNEL_COLORS = [
  '#3b82f6', // blue
  '#22c55e', // green
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // violet
  '#06b6d4', // cyan
  '#f97316', // orange
  '#84cc16', // lime
  '#ec4899', // pink
  '#14b8a6', // teal
];
