import { getDisplay as _getKpiDisplay } from './kpi/kpi-display.js';

/**
 * Aurora Econometrica - unified number formatting (v1.3.0).
 *
 * Создан per UX audit v1.3.0 - единая convention vs хаос:
 *   GoalSeekResultCard форматировала "5 804 223 012 ₽" (полная запись),
 *   WaterfallChart использовала "5M / 804K" (compact).
 *   ROI отображался "1.50×" в одних местах, "1.5×" в других.
 *
 * Правила:
 *   - Деньги > 1 млн → compact (5.8 млн ₽).
 *   - ROI всегда 2 decimals (1.50×).
 *   - CPU - 0 decimals (120 ₽/ед.).
 *   - Percentages 1 decimal (25.0%).
 *   - Null/undefined → '-' (em dash, not '-').
 */

/**
 * Format currency value (₽).
 * Compact format для > 1M, full format для < 1M.
 * @deprecated для значений результата KPI — используй formatKpiValue; formatMoney только для явно-денежных величин (затраты, бюджет, spend).
 * @param {number | null | undefined} n
 * @param {{compact?: boolean, decimals?: number}} [opts]
 */
export function formatMoney(n, opts = {}) {
  if (n == null || !isFinite(n)) return '-';
  const { compact = true, decimals = null } = opts;
  const abs = Math.abs(n);

  if (compact) {
    if (abs >= 1e9) return `${(n / 1e9).toFixed(decimals ?? 1)} млрд ₽`;
    if (abs >= 1e6) return `${(n / 1e6).toFixed(decimals ?? 1)} млн ₽`;
    if (abs >= 1e3) return `${(n / 1e3).toFixed(decimals ?? 0)} тыс. ₽`;
  }
  return `${Math.round(n).toLocaleString('ru-RU')} ₽`;
}

/**
 * Format ROI value (always 2 decimals + ×).
 * @param {number | null | undefined} n
 */
export function formatROI(n) {
  if (n == null || !isFinite(n)) return '-';
  return `${n.toFixed(2)}×`;
}

/**
 * Format CPU value (₽/ед.) - 0 decimals.
 * @param {number | null | undefined} n
 */
export function formatCPU(n) {
  if (n == null || !isFinite(n)) return '-';
  return `${Math.round(n).toLocaleString('ru-RU')} ₽/ед.`;
}

/**
 * Format percentage. Input 0.25 → "25.0%". Input 25 → "25.0%" (auto detect).
 * @param {number | null | undefined} n
 * @param {{decimals?: number, sign?: boolean}} [opts]
 */
export function formatPct(n, opts = {}) {
  if (n == null || !isFinite(n)) return '-';
  const { decimals = 1, sign = false } = opts;
  // If |n| <= 1 - assume fraction (0.25). Else - percentage already (25).
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  // UX audit fix: no +0% spurious sign.
  const prefix = sign && pct > 0 ? '+' : '';
  return `${prefix}${pct.toFixed(decimals)}%`;
}

/**
 * Format count (single integer with thousand separators).
 * @param {number | null | undefined} n
 * @param {string} [unitLabel]  e.g. 'упак' / 'лидов' / 'ед.'
 */
export function formatCount(n, unitLabel = 'ед.') {
  if (n == null || !isFinite(n)) return '-';
  return `${Math.round(n).toLocaleString('ru-RU')} ${unitLabel}`;
}

/**
 * KPI-aware metric formatting - dispatches based on kpi_kind / mode.
 * @param {number | null | undefined} value
 * @param {{kpi_kind?: string, mode?: string}} ctx
 */
export function formatMetric(value, ctx = {}) {
  const { kpi_kind = 'monetary', mode = 'roi' } = ctx;
  if (value == null || !isFinite(value)) return '-';
  if (mode === 'effectiveness') return formatPct(value, { decimals: 1 });
  if (kpi_kind === 'count') return formatCPU(value);
  return formatROI(value);
}

/**
 * Format delta (e.g. "+12.3% vs текущий" / "−5.0%").
 * @param {number | null | undefined} n  fractional delta (0.12 → +12.0%)
 */
export function formatDelta(n) {
  if (n == null || !isFinite(n)) return '-';
  return formatPct(n, { sign: true });
}

/**
 * Format big count number compactly (e.g. impressions 1.5M).
 * @param {number | null | undefined} n
 * @param {string} [unitLabel]
 */
export function formatCountCompact(n, unitLabel = '') {
  if (n == null || !isFinite(n)) return '-';
  const abs = Math.abs(n);
  const suffix = unitLabel ? ` ${unitLabel}` : '';
  if (abs >= 1e9) return `${(n / 1e9).toFixed(1)} млрд${suffix}`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)} млн${suffix}`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(0)} тыс.${suffix}`;
  return `${Math.round(n).toLocaleString('ru-RU')}${suffix}`;
}

/**
 * Format spend / budget — ВСЕГДА валюта (₽).
 * Семантически отличается от formatKpiValue: затраты — деньги для любого KPI,
 * даже если целевая метрика count (лиды, упаковки).
 *
 * @param {number | null | undefined} n
 * @param {{compact?: boolean, decimals?: number}} [opts]
 * @returns {string}
 */
export function formatSpend(n, opts = {}) {
  return formatMoney(n, opts);
}

/**
 * Format KPI result value по паспорту kpiType:
 *   - monetary (sales, revenue, profit) → compact ₽ (например «5,8 млрд ₽»)
 *   - count (leads, sales_packs, ...) → компактное число + короткая единица из паспорта
 *     (например «5,8 млн упак.», «1,2 млн лид.»)
 *   - неизвестный/отсутствующий kpiType → formatMoney (safe fallback)
 *
 * @param {number | null | undefined} n
 * @param {{ kpiType?: string | null }} ctx
 * @param {{compact?: boolean, decimals?: number}} [opts]
 * @returns {string}
 */
export function formatKpiValue(n, ctx = {}, opts = {}) {
  if (n == null || !isFinite(n)) return '-';
  const { kpiType } = ctx;
  if (!kpiType) return formatMoney(n, opts);

  let P = null;
  try {
    P = _getKpiDisplay(kpiType);
  } catch (_) {
    return formatMoney(n, opts);
  }

  if (P.kpi_kind === 'monetary') {
    return formatMoney(n, opts);
  }
  if (P.kpi_kind === 'count') {
    return formatCountCompact(n, P.result_unit_short || 'ед.');
  }
  // proportional / unknown → money fallback
  return formatMoney(n, opts);
}
