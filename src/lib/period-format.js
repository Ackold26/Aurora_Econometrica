/**
 * SSOT форматирования периода наблюдений с учётом гранулярности.
 *
 * Используется в ModeDerivedExplanation (порог-предупреждение) и ReportStep
 * (интерпретационные тексты). Единица и порог берутся из гранулярности,
 * не хардкодятся.
 */

/**
 * @typedef {'W' | 'M' | 'Q' | 'D' | string} Granularity
 */

/**
 * Текстовая единица периода («нед» / «мес» / «кв» / «пер») для данной гранулярности.
 *
 * @param {Granularity | null | undefined} granularity
 * @returns {string}
 */
export function periodUnit(granularity) {
  const g = (granularity ?? 'W').toUpperCase();
  if (g === 'W') return 'нед';
  if (g === 'M') return 'мес';
  if (g === 'Q') return 'кв';
  return 'пер';
}

/**
 * Рекомендуемый минимальный порог наблюдений для данной гранулярности.
 * Ниже порога — показывать предупреждение в UI.
 *
 * @param {Granularity | null | undefined} granularity
 * @returns {number}
 */
export function periodThreshold(granularity) {
  const g = (granularity ?? 'W').toUpperCase();
  if (g === 'W') return 52;
  if (g === 'M') return 24;
  if (g === 'Q') return 8;
  return 52; // дефолт — консервативный недельный порог
}

/**
 * Форматирует число наблюдений с правильной единицей и склонением.
 *
 * Примеры:
 *   formatPeriodLabel(36, 'W')  → «36 нед»
 *   formatPeriodLabel(12, 'M')  → «12 мес»
 *
 * @param {number} n - число наблюдений
 * @param {Granularity | null | undefined} granularity
 * @returns {string}
 */
export function formatPeriodLabel(n, granularity) {
  return `${n} ${periodUnit(granularity)}`;
}

/**
 * Русское склонение слова «период» с числом.
 * Вынесено из ReportStep.svelte (L13, math-fix v1.4 Section C, 2026-04-29).
 *
 * Примеры:
 *   ruPeriodForm(1)  → «1 период»
 *   ruPeriodForm(2)  → «2 периода»
 *   ruPeriodForm(21) → «21 период»
 *   ruPeriodForm(5)  → «5 периодов»
 *
 * @param {number} n
 * @returns {string}
 */
export function ruPeriodForm(n) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return `${n} период`;
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return `${n} периода`;
  return `${n} периодов`;
}
