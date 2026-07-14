/**
 * Утилиты корреляционной матрицы.
 *
 * Отдельный модуль — чтобы логика обрезки подписей легко тестировалась
 * юнитами без монтирования компонента.
 */

/**
 * Умная обрезка длинного имени колонки для подписи оси.
 *
 * Алгоритм: берём «голову» (первые headLen символов) + «…» + «хвост» (последние tailLen
 * символов), если суммарная длина превысила maxLen. Хвост помогает различить колонки
 * с одинаковыми префиксами (performance_spend vs performance_clicks).
 *
 * Примеры (maxLen=14, headLen=7, tailLen=6):
 *   'performance_spend'  → 'perform…_spend'
 *   'performance_clicks' → 'perform…licks'   ← последние 6 с учётом хвоста
 *   'digital_spend'      → 'digital_spend'    ← 13 ≤ 14, не трогаем
 *   'category_sales'     → 'catego…_sales'
 *
 * @param {string} label     Исходное имя
 * @param {number} [maxLen=14] Максимальная длина результата включая «…»
 * @param {number} [headLen=7] Сколько символов брать от начала
 * @param {number} [tailLen=6] Сколько символов брать от конца
 * @returns {string}
 */
export function abbreviateLabel(label, maxLen = 14, headLen = 7, tailLen = 6) {
  // Аудит 2026-07-11: defensive-приведение — имя колонки теоретически может прийти
  // не-строкой (null/число), тогда .length/.slice бросали бы. Известное ограничение:
  // два имени с общими головой И хвостом ('perform…_spend') коллизируют — различает
  // tooltip полного имени (в вызывающем CorrelationHeatmap).
  const s = String(label ?? '');
  if (s.length <= maxLen) return s;
  const head = s.slice(0, headLen);
  const tail = s.slice(-tailLen);
  return `${head}…${tail}`;
}
