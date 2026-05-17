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
 * Predict total KPI from budget allocation.
 *
 * v2.1.0 (pilot D2 round 2 R02 2026-05-17): added `unitCostsAtTraining` param.
 * Если pickle обучался с ADR-020 pre-multiply (mixed units mode), backend
 * scaled media_means на uc_train. Frontend spend в native units → нужно
 * pre-multiply spend на uc_train ДО Hill (`hillFunction` уже использует
 * gammaScaled из buildScaledParams где scale = adstock_mean_posterior).
 * Без этого native spend / scaled gamma → x_norm ≈ 0 → KPI ≈ baseline.
 *
 * @param {Record<string, number>} budgets - {channelName: spendValue в native units}
 * @param {Record<string, {alpha: number, gammaScaled: number, beta: number}>} scaledParams
 * @param {{y_mean?: number, y_std?: number} | null} [normalization] - Денормализация
 *        в исходные единицы KPI (y = y_norm * y_std + y_mean). Без неё возвращается
 *        значение в normalized-шкале (≈0-2), бесполезное для отображения пользователю.
 * @param {Record<string, number> | null} [unitCostsAtTraining] - {channelName: uc_train}.
 *        Применяется как multiplier к spend ДО Hill (ADR-020 symmetry).
 *        Default 1.0 если ключ отсутствует - byte-exact backward compat для legacy.
 * @returns {number}
 */
export function predictKPI(budgets, scaledParams, normalization = null, unitCostsAtTraining = null) {
  let total = 0;
  for (const [ch, spend] of Object.entries(budgets)) {
    const p = scaledParams[ch];
    if (!p) continue;
    const ucTrain = (unitCostsAtTraining && typeof unitCostsAtTraining[ch] === 'number' && unitCostsAtTraining[ch] > 0)
      ? unitCostsAtTraining[ch] : 1.0;
    const scaledSpend = spend * ucTrain;
    total += p.beta * hillFunction(scaledSpend, p.alpha, p.gammaScaled);
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
