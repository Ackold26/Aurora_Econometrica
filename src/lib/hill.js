/**
 * Client-side Hill function for budget optimizer.
 * A1: gamma MUST be pre-scaled before calling hillFunction:
 *     gammaScaled = Math.max(params.gamma * currentSpend, 1)
 * This matches optimizer.py:58 — `max(p['gamma'] * current_spend[col], 1)`.
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
export function marginalROI(x, alpha, gamma, beta) {
  const xSafe = Math.max(x, 1e-10);
  const gSafe = Math.max(gamma, 1e-10);
  const numerator = alpha * Math.pow(gSafe, alpha) * Math.pow(xSafe, alpha - 1);
  const denominator = Math.pow(Math.pow(xSafe, alpha) + Math.pow(gSafe, alpha), 2);
  return beta * numerator / denominator;
}

/**
 * Predict total KPI from budget allocation.
 * @param {Record<string, number>} budgets - {channelName: spendValue}
 * @param {Record<string, {alpha: number, gammaScaled: number, beta: number}>} scaledParams
 * @returns {number}
 */
export function predictKPI(budgets, scaledParams) {
  let total = 0;
  for (const [ch, spend] of Object.entries(budgets)) {
    const p = scaledParams[ch];
    if (!p) continue;
    total += p.beta * hillFunction(spend, p.alpha, p.gammaScaled);
  }
  return total;
}

/**
 * Build scaledParams from raw channelParams + currentSpend.
 * @param {Record<string, {alpha: number, gamma: number, beta: number}>} channelParams
 * @param {Record<string, number>} currentSpend - {channelName: totalSpend}
 * @returns {Record<string, {alpha: number, gammaScaled: number, beta: number}>}
 */
export function buildScaledParams(channelParams, currentSpend) {
  /** @type {Record<string, {alpha: number, gammaScaled: number, beta: number}>} */
  const result = {};
  for (const [ch, p] of Object.entries(channelParams)) {
    result[ch] = {
      alpha: p.alpha,
      gammaScaled: Math.max(p.gamma * (currentSpend[ch] ?? 0), 1),
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
