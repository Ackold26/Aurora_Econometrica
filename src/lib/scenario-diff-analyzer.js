/**
 * Scenario Diff Analyzer — auto-generates Russian narrative comparisons
 * between MMM optimization scenarios.
 *
 * Per WIZARD_FLOW_v2_FINAL.md §4.2 DiffAnalyzer.
 * Pure JS module, no external deps.
 *
 * @module scenario-diff-analyzer
 *
 * @example
 * import { generateDiffNarratives } from '$lib/scenario-diff-analyzer.js';
 * const lines = generateDiffNarratives([planA, planB, optimized], baseline);
 * // → ['План B даёт +27.3% KPI при +40% budget vs Базовый — высокая marginal стоимость роста.',
 * //    'Aurora-optimized превосходит План А на +6.4% при том же бюджете...']
 */

/**
 * @typedef {Object} Scenario
 * @property {string} id
 * @property {string} name
 * @property {number} budget - Total budget in ₽
 * @property {number} predictedKpi - Predicted KPI value
 * @property {number} [ciLow] - CI 90% lower bound
 * @property {number} [ciHigh] - CI 90% upper bound
 * @property {Record<string, number>} [perChannelAllocation] - Channel name → allocation fraction (0..1)
 * @property {string[]} [dates]
 * @property {number[]} [predictions]
 */

/**
 * @typedef {Object} ChannelDiff
 * @property {string} channel
 * @property {number} fromAlloc - Allocation fraction in source scenario
 * @property {number} toAlloc - Allocation fraction in target scenario
 * @property {number} deltaAbs - Absolute diff (toAlloc - fromAlloc)
 * @property {number} deltaPct - Relative diff in percentage points
 */

// ──────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Format a percentage delta for Russian narrative, e.g. +27.3% or -5.1%.
 * @param {number} delta - Absolute delta (already ×100 if representing percentage points)
 * @param {number} [decimals]
 * @returns {string}
 */
function fmtPct(delta, decimals = 1) {
  const sign = delta >= 0 ? '+' : '';
  return `${sign}${delta.toFixed(decimals)}%`;
}

/**
 * Format budget in millions of ₽.
 * @param {number} rub
 * @returns {string}
 */
function fmtBudget(rub) {
  if (!Number.isFinite(rub) || rub === 0) return '0 ₽';
  const m = rub / 1_000_000;
  if (m >= 1) return `${m.toFixed(m >= 10 ? 0 : 1)} млн ₽`;
  const k = rub / 1_000;
  return `${k.toFixed(0)} тыс. ₽`;
}

/**
 * Compute KPI delta % between two scenario KPI values.
 * Returns NaN when base is 0.
 * @param {number} base
 * @param {number} target
 * @returns {number} percent delta
 */
function kpiDeltaPct(base, target) {
  if (!base) return NaN;
  return ((target - base) / Math.abs(base)) * 100;
}

/**
 * Compute budget delta % between two scenario budgets.
 * @param {number} base
 * @param {number} target
 * @returns {number} percent delta
 */
function budgetDeltaPct(base, target) {
  if (!base) return NaN;
  return ((target - base) / Math.abs(base)) * 100;
}

/**
 * Marginal efficiency label (KPI% per Budget%).
 * @param {number} kpiDelta
 * @param {number} budgetDelta
 * @returns {string}
 */
function marginalLabel(kpiDelta, budgetDelta) {
  if (!Number.isFinite(budgetDelta) || Math.abs(budgetDelta) < 0.5) return 'тот же бюджет';
  const ratio = Math.abs(kpiDelta / budgetDelta);
  if (ratio < 0.5) return 'низкая marginal отдача';
  if (ratio < 0.9) return 'умеренная marginal отдача';
  if (ratio < 1.5) return 'пропорциональная отдача';
  return 'высокая marginal отдача';
}

/**
 * Find top-2 channel shifts by absolute delta for narrative.
 * @param {ChannelDiff[]} diffs
 * @returns {string}
 */
function describeTopShifts(diffs) {
  const significant = diffs.filter(d => Math.abs(d.deltaPct) >= 3);
  if (significant.length === 0) return '';
  const top2 = significant.slice(0, 2);
  const parts = top2.map(d => {
    const dir = d.deltaAbs > 0 ? '↑' : '↓';
    return `${d.channel} ${dir}${Math.abs(d.deltaPct).toFixed(0)} пп`;
  });
  return `основные сдвиги: ${parts.join(', ')}`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Public API
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Generate narrative comparison между scenarios.
 *
 * Each narrative is a concrete 1-2 sentence string in Russian with real numbers.
 * If baseline is provided — each scenario is compared to it first.
 * Then scenarios are compared pairwise (each vs Aurora-optimized if present,
 * else vs the first/best scenario).
 *
 * @param {Scenario[]} scenarios
 * @param {Scenario | null} [baseline]
 * @returns {string[]} Array of narrative strings
 *
 * @example
 * generateDiffNarratives([planA, planB, optimized], baseline)
 * // → ['План B даёт +27.3% KPI при +40% budget vs Базовый — высокая marginal отдача.',
 * //    'Aurora-optimized превосходит План А на +6.4% при том же бюджете...']
 */
export function generateDiffNarratives(scenarios, baseline = null) {
  if (!scenarios || scenarios.length === 0) return [];

  /** @type {string[]} */
  const narratives = [];

  // ── Section 1: each scenario vs baseline ────────────────────────────────────
  if (baseline) {
    for (const sc of scenarios) {
      if (sc.id === baseline.id) continue;

      const kpiDelta = kpiDeltaPct(baseline.predictedKpi, sc.predictedKpi);
      const budDelta = budgetDeltaPct(baseline.budget, sc.budget);
      const margEff = marginalLabel(kpiDelta, budDelta);

      if (!Number.isFinite(kpiDelta)) continue;

      const kpiStr = fmtPct(kpiDelta);
      const channelDiffs = computePerChannelDiff(baseline, sc);
      const shiftStr = describeTopShifts(channelDiffs);

      let line = `${sc.name}: ${kpiStr} KPI`;

      if (Number.isFinite(budDelta) && Math.abs(budDelta) >= 0.5) {
        line += ` при ${fmtPct(budDelta)} budget (${fmtBudget(sc.budget)})`;
      } else {
        line += ` при том же бюджете`;
      }

      line += ` vs ${baseline.name} — ${margEff}`;
      if (shiftStr) line += `. ${shiftStr.charAt(0).toUpperCase() + shiftStr.slice(1)}.`;
      else line += '.';

      narratives.push(line);
    }
  }

  // ── Section 2: Aurora-optimized vs best user plan ────────────────────────────
  const auroraOpt = scenarios.find(s =>
    s.name.toLowerCase().includes('aurora') ||
    s.name.toLowerCase().includes('оптим') ||
    s.id === 'aurora-optimized'
  );

  // Identify «best user plan» — highest KPI among non-Aurora scenarios, excluding baseline
  const userPlans = scenarios.filter(s =>
    s !== auroraOpt && (!baseline || s.id !== baseline.id)
  );

  if (auroraOpt && userPlans.length > 0) {
    // Sort by KPI descending
    const sorted = [...userPlans].sort((a, b) => b.predictedKpi - a.predictedKpi);
    const bestUser = sorted[0];

    const kpiDelta = kpiDeltaPct(bestUser.predictedKpi, auroraOpt.predictedKpi);
    const budDelta = budgetDeltaPct(bestUser.budget, auroraOpt.budget);

    if (Number.isFinite(kpiDelta) && Math.abs(kpiDelta) >= 0.1) {
      const channelDiffs = computePerChannelDiff(bestUser, auroraOpt);
      const shiftStr = describeTopShifts(channelDiffs);

      let line = '';
      if (kpiDelta > 0) {
        line = `${auroraOpt.name} превосходит ${bestUser.name} на ${fmtPct(kpiDelta)}`;
      } else {
        line = `${auroraOpt.name} уступает ${bestUser.name} на ${fmtPct(Math.abs(kpiDelta))}`;
      }

      if (Number.isFinite(budDelta) && Math.abs(budDelta) >= 0.5) {
        line += ` при ${fmtPct(budDelta)} budget`;
      } else {
        line += ` при том же бюджете`;
      }

      if (shiftStr) line += `. ${shiftStr.charAt(0).toUpperCase() + shiftStr.slice(1)}.`;
      else line += '.';

      narratives.push(line);
    }
  }

  // ── Section 3: cross-scenario insight — best efficiency ─────────────────────
  const allForEff = [
    ...(baseline ? [baseline] : []),
    ...scenarios,
  ].filter(s => s.budget > 0 && s.predictedKpi > 0);

  const best = findBestEfficiencyScenario(allForEff);
  if (best && allForEff.length >= 2) {
    const worst = allForEff.reduce((a, b) =>
      (b.predictedKpi / b.budget) < (a.predictedKpi / a.budget) ? b : a
    );
    if (best.id !== worst.id) {
      const effBest = best.predictedKpi / best.budget * 1_000_000;
      const effWorst = worst.predictedKpi / worst.budget * 1_000_000;
      if (Number.isFinite(effBest) && Number.isFinite(effWorst) && effWorst > 0) {
        const effRatio = effBest / effWorst;
        if (effRatio > 1.05) {
          narratives.push(
            `Наибольшая эффективность бюджета у «${best.name}»: ` +
            `${effBest.toFixed(0)} KPI/млн ₽ vs ${effWorst.toFixed(0)} у «${worst.name}» ` +
            `(в ${effRatio.toFixed(1)}× эффективнее).`
          );
        }
      }
    }
  }

  return narratives.length > 0
    ? narratives
    : ['Недостаточно данных для автоматического сравнения сценариев.'];
}

/**
 * Compute per-channel reallocation diff between two scenarios.
 *
 * @param {Scenario} from - Source scenario
 * @param {Scenario} to - Target scenario
 * @returns {ChannelDiff[]} Sorted by |deltaAbs| descending
 *
 * @example
 * computePerChannelDiff(baseline, planA)
 * // → [{ channel: 'TV', fromAlloc: 0.40, toAlloc: 0.25, deltaAbs: -0.15, deltaPct: -15 }, ...]
 */
export function computePerChannelDiff(from, to) {
  const fromAlloc = from?.perChannelAllocation ?? {};
  const toAlloc = to?.perChannelAllocation ?? {};

  // Union of all channel keys
  const channels = new Set([
    ...Object.keys(fromAlloc),
    ...Object.keys(toAlloc),
  ]);

  /** @type {ChannelDiff[]} */
  const diffs = [];

  for (const channel of channels) {
    const fa = fromAlloc[channel] ?? 0;
    const ta = toAlloc[channel] ?? 0;
    const deltaAbs = ta - fa;
    // deltaPct = delta in percentage points (alloc is 0..1, so ×100)
    const deltaPct = deltaAbs * 100;

    diffs.push({ channel, fromAlloc: fa, toAlloc: ta, deltaAbs, deltaPct });
  }

  // Sort by |deltaAbs| descending
  diffs.sort((a, b) => Math.abs(b.deltaAbs) - Math.abs(a.deltaAbs));

  return diffs;
}

/**
 * Identify the scenario with the highest KPI-per-budget ratio (best efficiency).
 *
 * @param {Scenario[]} scenarios
 * @returns {Scenario | null} Highest KPI-per-budget scenario, or null if empty
 *
 * @example
 * findBestEfficiencyScenario([baseline, planA, planB, auroraOpt])
 * // → auroraOpt  (if it has highest KPI/₽)
 */
export function findBestEfficiencyScenario(scenarios) {
  if (!scenarios || scenarios.length === 0) return null;

  const valid = scenarios.filter(s =>
    s.budget > 0 && Number.isFinite(s.predictedKpi) && s.predictedKpi > 0
  );
  if (valid.length === 0) return null;

  return valid.reduce((best, sc) => {
    const effBest = best.predictedKpi / best.budget;
    const effSc = sc.predictedKpi / sc.budget;
    return effSc > effBest ? sc : best;
  });
}
