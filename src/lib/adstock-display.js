/**
 * Утилита отображения типа adstock в Эксперт-режиме.
 *
 * Отдельный модуль — чтобы логика резолвинга легко тестировалась юнитами.
 */

/**
 * @typedef {'geometric' | 'weibull' | 'auto'} AdstockRawType
 */

/**
 * Человекочитаемые метки типов adstock для опций селекта.
 * @type {Record<AdstockRawType, string>}
 */
export const ADSTOCK_LABELS = {
  geometric: 'Геометрический – быстрое затухание',
  weibull:   'Вейбулл – долгий след',
  auto:      'Авто (подберётся при обучении)',
};

/**
 * Возвращает отображаемое значение (value) для <select> канала в Эксперт-режиме:
 * - до обучения при 'auto'  → 'auto'
 * - после обучения при 'auto' → '<resolvedType>_auto' (особый маркер → отображается как «X – авто-подбор»)
 * - явный тип (не auto)     → сам тип без изменений
 *
 * Примечание: resolvedType берётся из diagnostics.channel_adstock_types[channel],
 * когда бэкенд поддерживает его проброс в diagnostics (будущее расширение).
 * Пока diagnostics не содержит channel_adstock_types — resolvedType приходит как null.
 *
 * @param {string} rawType       Тип, выбранный пользователем: 'auto'|'geometric'|'weibull'
 * @param {string | null | undefined} resolvedType  Тип из pickle после обучения (null = не обучено / не доступно)
 * @returns {string}  Значение для атрибута value опции
 */
export function resolveAdstockDisplayValue(rawType, resolvedType) {
  if (rawType !== 'auto') return rawType;
  if (!resolvedType) return 'auto';
  // resolvedType задан → показываем резолвнутый тип с пометкой авто-подбора
  return `${resolvedType}_auto`;
}

/**
 * Человекочитаемая метка для отображения в селекте (используется в title/placeholder).
 *
 * @param {string} displayValue  Результат resolveAdstockDisplayValue
 * @returns {string}
 */
export function adstockDisplayLabel(displayValue) {
  if (displayValue === 'auto')          return 'Авто (подберётся при обучении)';
  if (displayValue === 'geometric')     return 'Геометрический – быстрое затухание';
  if (displayValue === 'weibull')       return 'Вейбулл – долгий след';
  if (displayValue === 'geometric_auto') return 'Геометрический – авто-подбор';
  if (displayValue === 'weibull_auto')   return 'Вейбулл – авто-подбор';
  return displayValue;
}
