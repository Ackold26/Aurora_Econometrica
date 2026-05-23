/**
 * Number formatting utilities - Russian locale, Excel-style thousand separators.
 */

const RU_FULL = new Intl.NumberFormat('ru-RU', {
  maximumFractionDigits: 2,
});
const RU_INT = new Intl.NumberFormat('ru-RU', {
  maximumFractionDigits: 0,
});
const RU_COMPACT = new Intl.NumberFormat('ru-RU', {
  maximumFractionDigits: 3,
});

/**
 * Format a number in Russian locale with non-breaking thin spaces between thousands:
 *   12345678.9 → "12 345 678,9"
 * Handles null / NaN / string inputs.
 * @param {number | string | null | undefined} n
 * @param {{ decimals?: number, placeholder?: string }} [opts]
 * @returns {string}
 */
export function fmtNum(n, opts = {}) {
  const { decimals, placeholder = '-' } = opts;
  if (n == null || n === '' || n === '-') return placeholder;
  const num = typeof n === 'string' ? parseFloat(n.replace(',', '.')) : n;
  if (!Number.isFinite(num)) return placeholder;

  // Very small fractional numbers: keep 3 decimals
  if (Math.abs(num) > 0 && Math.abs(num) < 1) {
    if (decimals != null) return num.toLocaleString('ru-RU', { maximumFractionDigits: decimals });
    return RU_COMPACT.format(num);
  }

  // Integers: no decimals
  if (Number.isInteger(num)) return RU_INT.format(num);

  // Default: up to 2 decimals
  if (decimals != null) return num.toLocaleString('ru-RU', { maximumFractionDigits: decimals });
  return RU_FULL.format(num);
}

/**
 * Format a percentage value (already 0-100 scale).
 * @param {number | string | null | undefined} n
 * @returns {string}
 */
export function fmtPct(n) {
  if (n == null || n === '') return '-';
  const num = typeof n === 'string' ? parseFloat(n.replace(',', '.')) : n;
  if (!Number.isFinite(num)) return '-';
  return `${num.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`;
}
