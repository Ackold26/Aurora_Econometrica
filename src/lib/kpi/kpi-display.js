// @ts-nocheck
/**
 * Обёртка над сгенерированным реестром KPI-паспортов.
 * Зеркалит API Python-модуля kpi_display.py.
 */
import { KPI_DISPLAY, KPI_DISPLAY_CURRENCY } from './kpi-display.generated.js';

/**
 * Русская плюрализация.
 * @param {number} n
 * @param {string[]} forms - [ед.ч., 2-4, 5+]
 * @returns {string}
 */
export function plural(n, forms) {
  const n10 = n % 10;
  const n100 = n % 100;
  if (n10 === 1 && n100 !== 11) return forms[0];
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return forms[1];
  return forms[2];
}

/**
 * Возвращает паспорт отображения для типа KPI.
 * Для 'count_custom' можно передать customForms (3 строки).
 * @param {string} kpiType
 * @param {string[] | null} [customForms]
 * @returns {object}
 */
export function getDisplay(kpiType, customForms = null) {
  if (!(kpiType in KPI_DISPLAY)) {
    const valid = Object.keys(KPI_DISPLAY).join(', ');
    throw new Error(`Неизвестный kpiType='${kpiType}'. Допустимые: ${valid}`);
  }
  const result = { ...KPI_DISPLAY[kpiType] };
  if (kpiType === 'count_custom' && customForms != null) {
    if (customForms.length !== 3) {
      throw new Error('customForms должен содержать ровно 3 строки');
    }
    result.result_forms = [...customForms];
    result.result_unit_short = customForms[0] ? customForms[0].split(' ')[0] : 'ед.';
  }
  return result;
}

/**
 * Возвращает символ валюты.
 * @returns {string}
 */
export function currencySymbol() {
  return KPI_DISPLAY_CURRENCY.symbol;
}

/**
 * Возвращает массив всех доступных типов KPI.
 * @returns {string[]}
 */
export function allDisplayTypes() {
  return Object.keys(KPI_DISPLAY);
}
