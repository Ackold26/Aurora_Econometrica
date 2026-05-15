/**
 * Русскоязычные утилиты локализации.
 *
 * NB v2.0.1-rc2: ВРЕМЕННО keeping pluralizeRu отдельно от полного i18n
 * framework (`$lib/i18n/`). Когда сделаем полную migration к svelte-i18n
 * (Phase 2 v2.2.0), pluralization будет через ICU MessageFormat плюрал
 * формы внутри translation keys. До тех пор pluralizeRu остаётся как
 * standalone helper для inline русских strings.
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
