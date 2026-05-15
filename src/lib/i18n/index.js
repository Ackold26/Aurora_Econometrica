/**
 * i18n entry point — Aurora MMM Optimizer.
 *
 * Foundation laid 2026-05-15 (sprint v2.0.1-rc2). На этой стадии translations
 * содержат skeletal placeholders — реальный перевод запланирован к v2.2.0+.
 *
 * Использование в Svelte компонентах:
 *
 *   <script>
 *     import { _ } from 'svelte-i18n';
 *     // вместо «Сохранить проект»:
 *     const label = $_('common.save');
 *   </script>
 *
 *   <button>{$_('pipeline.validate.confirm_roles')}</button>
 *
 * Использование вне компонентов (helpers / services):
 *
 *   import { translate } from '$lib/i18n';
 *   const msg = translate('errors.migration_failed', { count: 5 });
 *
 * Convention: ключи в формате `<area>.<context>.<concept>`, all lowercase
 * с underscores. Plurals через ICU MessageFormat (см. https://format-message.github.io/icu-message-format-for-translators/).
 *
 * Locale persistence: localStorage key `aurora-locale`. Defaults к 'ru' если
 * не задано. Tauri OS locale detection — будущее (v2.3.0).
 *
 * @module i18n
 */
import { addMessages, init, register, locale as svelteI18nLocale, _, isLoading } from 'svelte-i18n';
import { writable, derived, get } from 'svelte/store';
import { browser } from '$app/environment';

const SUPPORTED_LOCALES = /** @type {const} */ (['ru', 'en']);
const DEFAULT_LOCALE = 'ru';
const STORAGE_KEY = 'aurora-locale';

/**
 * @typedef {'ru' | 'en'} SupportedLocale
 */


// Lazy-load locale dictionaries through register (svelte-i18n style).
// Файлы должны быть импортированы async для tree-shaking.
register('ru', () => import('./locales/ru.json'));
register('en', () => import('./locales/en.json'));


/**
 * Получить активную локаль из localStorage или вернуть default.
 * @returns {SupportedLocale}
 */
function loadStoredLocale() {
  if (!browser) return DEFAULT_LOCALE;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && SUPPORTED_LOCALES.includes(/** @type {SupportedLocale} */ (stored))) {
      return /** @type {SupportedLocale} */ (stored);
    }
  } catch {
    // localStorage может быть unavailable.
  }
  return DEFAULT_LOCALE;
}


// Initial locale resolution — invoked once at module load.
const initialLocale = loadStoredLocale();

init({
  fallbackLocale: DEFAULT_LOCALE,
  initialLocale,
});


/**
 * Aurora-side locale store. Wraps svelte-i18n internal locale + persists к
 * localStorage. Use this в UI вместо direct svelte-i18n imports.
 *
 * @type {import('svelte/store').Writable<SupportedLocale>}
 */
export const locale = writable(initialLocale);

locale.subscribe((newLocale) => {
  if (!SUPPORTED_LOCALES.includes(newLocale)) return;
  svelteI18nLocale.set(newLocale);
  if (!browser) return;
  try {
    localStorage.setItem(STORAGE_KEY, newLocale);
  } catch {
    // best-effort
  }
});


/**
 * List of supported locales (read-only).
 * @type {readonly SupportedLocale[]}
 */
export const supportedLocales = SUPPORTED_LOCALES;


/**
 * Plain-function translation helper для usage вне компонентов
 * (services, utils, error handlers). Wraps get($_). NB: реактивности нет —
 * если locale меняется, вызывающий код должен пере-вычислить.
 *
 * Params типа InterpolationValues — accepts string / number / boolean /
 * Date / null. Object values нужно сначала coerce к string.
 *
 * @param {string} key
 * @param {Record<string, string | number | boolean | Date | null | undefined>} [params]
 * @returns {string}
 */
export function translate(key, params) {
  const t = /** @type {any} */ (get(_));
  if (typeof t === 'function') {
    return String(t(key, { values: params }));
  }
  return key;
}


/**
 * Convenience re-export — `_` store для Svelte template usage.
 * Components import as: `import { _ } from 'svelte-i18n'` directly OR
 * `import { _ } from '$lib/i18n'` (this is alias).
 */
export { _, isLoading };


/**
 * Re-export `derived` для consumers who нужны locale-aware computed values.
 * Example: `const greeting = derived(_, $t => $t('common.hello'))`.
 */
export { derived };
