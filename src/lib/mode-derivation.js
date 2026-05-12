/**
 * Aurora Econometrica - frontend mode derivation v1.3.0 (per ADR-015).
 *
 * Pure-JS mirror of sidecar's `utils/mode_inference.derive_mode()`.
 * Used by UI components to compute derivedMode locally без roundtrip.
 *
 * Источники истины:
 * - Backend Python: sidecar/econometrica/utils/mode_inference.py
 * - ADR-015 (Mode as derived state).
 *
 * Use:
 *   import { deriveMode, isMixedMode } from '$lib/mode-derivation';
 *   const mode = deriveMode({ tv: 'monetary', olv: 'physical' });  // → 'manual'
 */

/**
 * Derive mode from per-channel input metrics.
 * @param {Record<string, 'monetary' | 'physical'>} perChannelInputs
 * @returns {'roi' | 'effectiveness' | 'manual'}
 */
export function deriveMode(perChannelInputs) {
  if (!perChannelInputs || Object.keys(perChannelInputs).length === 0) {
    return 'roi'; // default
  }

  const values = Object.values(perChannelInputs);

  // Validate.
  for (const v of values) {
    if (v !== 'monetary' && v !== 'physical') {
      throw new Error(`Invalid input metric: ${v}. Must be 'monetary' or 'physical'.`);
    }
  }

  const uniqueValues = new Set(values);

  if (uniqueValues.size === 1) {
    return uniqueValues.has('monetary') ? 'roi' : 'effectiveness';
  }

  return 'manual';
}

/**
 * Compute mode + plain-text explanation для UI.
 * @param {Record<string, 'monetary' | 'physical'>} perChannelInputs
 * @returns {{mode: string, explanation: string}}
 */
export function deriveModeWithExplanation(perChannelInputs) {
  const mode = deriveMode(perChannelInputs);
  const monetaryCount = Object.values(perChannelInputs).filter(v => v === 'monetary').length;
  const physicalCount = Object.values(perChannelInputs).filter(v => v === 'physical').length;
  const total = monetaryCount + physicalCount;

  let explanation;
  if (mode === 'roi') {
    explanation = `Все ${total} каналов измеряются в ₽-бюджетах. Модель работает в режиме ROI - оценивает возврат на инвестицию (₽ выручки / ₽ затрат).`;
  } else if (mode === 'effectiveness') {
    explanation = `Все ${total} каналов измеряются в физических контактах (показы / клики / GRP). Модель работает в режиме Эффективность - главная метрика сравнения каналов = доля в продажах. Для cost-effectiveness анализа можно добавить ценники контактов (CPM/CPC/CPP).`;
  } else {
    explanation = `Смешанный режим: ${monetaryCount} канала в ₽-бюджетах, ${physicalCount} канала в физических контактах. Cross-channel сравнение через долю в продажах. Для cost-effectiveness можно добавить ценники контактов на physical каналы (переход в virtual ROI).`;
  }

  return { mode, explanation };
}

/**
 * Is mixed mode (manual)?
 * @param {Record<string, 'monetary' | 'physical'>} perChannelInputs
 * @returns {boolean}
 */
export function isMixedMode(perChannelInputs) {
  return deriveMode(perChannelInputs) === 'manual';
}

/**
 * Mapping kpi_type → kpi_kind.
 * Mirror of sidecar's utils.kpi_registry.is_count_kpi() + is_monetary_kpi().
 *
 * @param {string} kpiType
 * @returns {'monetary' | 'count' | 'proportional'}
 */
export function kpiKindForType(kpiType) {
  const COUNT_TYPES = new Set([
    'sales_packs', 'leads', 'registrations', 'loyalty_cards',
    'subscriptions', 'app_installs', 'count_custom',
  ]);
  const MONETARY_TYPES = new Set(['sales', 'revenue', 'profit']);
  const PROPORTIONAL_TYPES = new Set(['awareness']);

  if (COUNT_TYPES.has(kpiType)) return 'count';
  if (MONETARY_TYPES.has(kpiType)) return 'monetary';
  if (PROPORTIONAL_TYPES.has(kpiType)) return 'proportional';
  return 'monetary'; // safe fallback
}

/**
 * Get UI label for value_per_count_unit field per KPI type.
 * Mirror of utils.kpi_registry.get_value_per_count_unit_label().
 *
 * @param {string} kpiType
 * @returns {string}
 */
export function valuePerCountUnitLabel(kpiType) {
  /** @type {Record<string, string>} */
  const LABELS = {
    sales_packs: 'Маржа на упаковку, ₽',
    leads: 'Ценность лида, ₽',
    registrations: 'Ценность регистрации, ₽',
    loyalty_cards: 'Ценность выданной карты, ₽',
    subscriptions: 'MRR на подписку, ₽',
    app_installs: 'Ценность установки, ₽',
    count_custom: 'Ценность единицы, ₽',
  };
  return LABELS[kpiType] ?? '';
}
