/**
 * Objective-driven role application engine.
 *
 * Takes validator output columns and applies analysis-objective rules:
 *   - 'roi'           → keep budgets, exclude natural metrics per channel
 *   - 'effectiveness' → keep natural metrics (impressions/clicks/visits), exclude budgets
 *   - 'manual'        → no changes (user decides)
 *
 * Uses prefix-matching (shared with insights-rules.js) to pair cost/volume metrics.
 */

const VOLUME_KEYS = ['ПОКАЗ','ПРОСМОТР','КЛИК','ВИЗИТ','ПРОЧТЕН','GRP','TRP','OTS','IMPRESSION','CLICK','VIEW','VISIT','READ'];
const COST_KEYS = ['БЮДЖЕТ','РАСХОД','ЗАТРАТ','СТОИМОСТЬ','SPEND','COST','BUDGET','РУБ'];

/**
 * Extract a canonical channel prefix - letters only, truncated to a common stem
 * so "Спецпроекты" and "Спецпроект" group together, and "Статьи (прочтения)"
 * parses to the same stem as "Статьи Бюджет".
 * @param {string} leading
 * @returns {string}
 */
function canonicalPrefix(leading) {
  const match = leading.match(/^[А-ЯЁA-Z]+/);
  if (!match) return '';
  // Truncate to first 6 letters for lightweight stemming (handles Russian plural/singular)
  return match[0].slice(0, 6);
}

/**
 * @typedef {{ name: string, role?: string, [k: string]: any }} Column
 */

/**
 * Group media columns by channel prefix (e.g. "OLV", "Banners").
 * @param {Column[]} cols
 * @returns {Map<string, { volume: Column[], cost: Column[] }>}
 */
function groupByChannel(cols) {
  /** @type {Map<string, { volume: Column[], cost: Column[] }>} */
  const groups = new Map();

  for (const c of cols) {
    if (c.role !== 'media') continue; // only paired within media
    const upper = (c.name ?? '').toUpperCase();
    let prefix = '';
    let type = '';

    for (const k of VOLUME_KEYS) {
      const idx = upper.indexOf(k);
      if (idx > 0) { prefix = canonicalPrefix(upper.slice(0, idx)); type = 'volume'; break; }
    }
    if (!prefix) {
      for (const k of COST_KEYS) {
        const idx = upper.indexOf(k);
        if (idx > 0) { prefix = canonicalPrefix(upper.slice(0, idx)); type = 'cost'; break; }
      }
    }
    if (!prefix) continue;

    if (!groups.has(prefix)) groups.set(prefix, { volume: [], cost: [] });
    const g = /** @type {{ volume: Column[], cost: Column[] }} */ (groups.get(prefix));
    if (type === 'volume') g.volume.push(c);
    else g.cost.push(c);
  }

  return groups;
}

/**
 * Apply analysis objective to validator result columns.
 * Returns a new columns array with updated roles - does NOT mutate input.
 *
 * @param {Column[]} columns
 * @param {'roi' | 'effectiveness' | 'manual'} objective
 * @returns {{ columns: Column[], excluded: string[], kept: string[] }}
 */
export function applyObjectiveToColumns(columns, objective) {
  if (objective === 'manual' || !Array.isArray(columns)) {
    return { columns: columns ?? [], excluded: [], kept: [] };
  }

  // Deep-copy to avoid store mutation (per feedback_store_mutation rule)
  const next = columns.map(c => ({ ...c }));
  const groups = groupByChannel(next);

  /** @type {string[]} */
  const excluded = [];
  /** @type {string[]} */
  const kept = [];

  for (const [, g] of groups) {
    const hasCost = g.cost.length > 0;
    const hasVolume = g.volume.length > 0;
    if (!hasCost && !hasVolume) continue;

    // Quality override: if the preferred side is too sparse, fall back to the other side.
    const costZeros = g.cost[0]?.stats?.zeros_pct ?? 100;
    const volZeros = g.volume[0]?.stats?.zeros_pct ?? 100;
    const costTooSparse = hasCost && costZeros > 50 && costZeros > volZeros + 15;
    const volTooSparse  = hasVolume && volZeros > 50 && volZeros > costZeros + 15;

    /** @type {Column | null} */
    let keep = null;
    /** @type {Column[]} */
    let drop = [];

    if (objective === 'roi') {
      if (hasCost && !costTooSparse) {
        keep = g.cost[0];
        drop = [...g.cost.slice(1), ...g.volume];
      } else if (hasVolume) {
        // No budget or budget too sparse → keep volume as fallback
        keep = g.volume[0];
        drop = [...g.volume.slice(1), ...g.cost];
      }
    } else if (objective === 'effectiveness') {
      if (hasVolume && !volTooSparse) {
        keep = g.volume[0];
        drop = [...g.volume.slice(1), ...g.cost];
      } else if (hasCost) {
        keep = g.cost[0];
        drop = [...g.cost.slice(1), ...g.volume];
      }
    }

    if (keep) kept.push(keep.name);
    for (const d of drop) {
      d.role = 'unused';
      excluded.push(d.name);
    }
  }

  return { columns: next, excluded, kept };
}

/**
 * Recompute result.detected/issues/status after objective-driven role changes.
 * Mutates `result` in place (shallow-copy it beforehand if you want immutability).
 *
 * @param {any} result - validator output
 * @returns {any} same result, with updated detected/issues/status/verdict
 */
export function recomputeResultAfterObjective(result) {
  if (!result || !Array.isArray(result.columns)) return result;

  const cols = result.columns;
  const mediaNames = cols.filter(/** @param {any} c */ c => c.role === 'media').map(/** @param {any} c */ c => c.name);
  const controlNames = cols.filter(/** @param {any} c */ c => c.role === 'control').map(/** @param {any} c */ c => c.name);
  const kpiNames = cols.filter(/** @param {any} c */ c => c.role === 'kpi').map(/** @param {any} c */ c => c.name);
  const dateCol = cols.find(/** @param {any} c */ c => c.role === 'date')?.name ?? null;

  const nRows = result.file?.rows ?? 0;
  const nPredictors = mediaNames.length + controlNames.length;
  const ratio = nPredictors > 0 ? nRows / nPredictors : 0;

  // Drop stale issues/warnings about excluded columns
  const excluded = new Set(cols.filter(/** @param {any} c */ c => c.role === 'unused').map(/** @param {any} c */ c => c.name));
  /** @param {{ column?: string | null, type?: string }} w */
  const stillRelevant = (w) => {
    if (w.column && excluded.has(w.column)) return false;
    // 'insufficient_data' issue is ratio-based; always recompute
    if (w.type === 'insufficient_data') return false;
    return true;
  };
  /** @type {any[]} */
  const issues = (result.issues ?? []).filter(stillRelevant);
  /** @type {any[]} */
  const warnings = (result.warnings ?? []).filter(stillRelevant);

  // Re-add insufficient_data with current numbers
  if (ratio < 2 && nPredictors > 0) {
    issues.push({
      type: 'insufficient_data',
      message: `Ratio данных ${ratio.toFixed(1)}:1 - критически мало (минимум 4:1). Нужно больше наблюдений или меньше переменных`,
      severity: 'critical',
    });
  } else if (ratio < 4 && nPredictors > 0) {
    warnings.push({
      type: 'insufficient_data',
      message: `Ratio данных ${ratio.toFixed(1)}:1 - ниже рекомендуемых 4:1. Модель запустится, но с широкими доверительными интервалами`,
      severity: 'warning',
    });
  }

  // Derive status from recomputed issues
  const hasCritical = issues.some(/** @param {any} i */ i => i.severity === 'critical');
  const status = hasCritical ? 'error' : (warnings.length > 0 ? 'warning' : 'ok');

  // Update detected block
  result.detected = {
    ...(result.detected ?? {}),
    date: dateCol,
    kpi: kpiNames,
    media: mediaNames,
    control: controlNames,
    n_predictors: nPredictors,
    ratio: Number(ratio.toFixed(2)),
  };

  // Update verdict to reflect current state
  let verdict;
  if (status === 'error') verdict = 'Нужна доработка данных';
  else if (status === 'warning') verdict = 'Можно моделировать с оговорками';
  else verdict = 'Данные готовы к моделированию';

  result.issues = issues;
  result.warnings = warnings;
  result.status = status;
  result.verdict = verdict;

  return result;
}

/**
 * Describe what the objective will do - used for UI labels.
 * @param {'roi' | 'effectiveness' | 'manual'} objective
 */
export function describeObjective(objective) {
  switch (objective) {
    case 'roi':
      return 'Оставлены бюджеты, исключены показы/клики/визиты.';
    case 'effectiveness':
      return 'Оставлены физические метрики (показы/клики), исключены бюджеты.';
    case 'manual':
      return 'Все метрики оставлены - выбирайте сами в таблице ролей ниже.';
    default:
      return '';
  }
}
