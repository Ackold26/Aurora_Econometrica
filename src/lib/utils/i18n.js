/**
 * Русскоязычные утилиты локализации.
 */

/**
 * Russian plural form helper using Intl.PluralRules.
 * @param {number} n
 * @param {[string, string, string]} forms - [one, few, many] формы
 * @returns {string}
 */
export function pluralizeRu(n, forms) {
  const pr = new Intl.PluralRules('ru');
  const category = pr.select(n);
  // RU: one / few / many / other → forms[0|1|2]
  switch (category) {
    case 'one': return forms[0];
    case 'few': return forms[1];
    default: return forms[2];
  }
}
