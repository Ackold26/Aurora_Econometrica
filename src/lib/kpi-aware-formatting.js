/**
 * KPI/mode-aware label & format helpers для insights / UI компонентов (v1.3.2).
 *
 * Frontend mirror of:
 *   - sidecar/econometrica/aurora_html/sections.py:_kpi_view
 *   - sidecar/econometrica/aurora_pptx/kpi_helpers.py
 *   - sidecar/econometrica/utils/kpi_labels.py
 *
 * Use:
 *   import { kpiView, fmtMetric, weightedPhrase } from '$lib/kpi-aware-formatting.js';
 *
 *   const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi', valuePerCountUnit: 80 });
 *   // → { kpiKind: 'count', mode: 'roi', metricShort: 'CPU', isLegacy: false, ... }
 *
 *   fmtMetric(120, kpi);          // → '120 ₽/ед.'
 *   weightedPhrase(0.0125, kpi);  // → 'CPU портфеля 80 ₽/ед.'
 *   underBreakevenPhrase(kpi);    // → 'CPU > 80 ₽/ед. (выше ценности)'
 *
 * @module kpi-aware-formatting
 */

/**
 * @typedef {Object} KpiViewInput
 * @property {string} [kpiKind] - 'monetary' | 'count'
 * @property {string} [derivedMode] - 'roi' | 'effectiveness' | 'manual'
 * @property {number|null} [valuePerCountUnit] - ₽ per count unit (для count KPI)
 * @property {string} [valuePerCountUnitLabel]
 * @property {Object} [labels] - { metricLabel, metricShortLabel, targetUnitLabel, targetAxisLabel }
 */

/**
 * @typedef {Object} KpiView
 * @property {string} kpiKind
 * @property {string} mode
 * @property {string} metricLabel
 * @property {string} metricShort
 * @property {string} targetUnit
 * @property {string} targetAxis
 * @property {number|null} vpcu
 * @property {string} vpcuLabel
 * @property {boolean} isLegacy
 */

const DEFAULT_LABELS = {
  metricLabel: 'ROI',
  metricShortLabel: 'ROI',
  targetUnitLabel: '₽',
  targetAxisLabel: 'Продажи, ₽',
};

/**
 * Build KPI view from raw stores / data dict. Defaults preserve v1.2 behavior.
 *
 * @param {KpiViewInput|null|undefined} input
 * @returns {KpiView}
 */
export function kpiView(input) {
  const src = input || {};
  const kpiKind = src.kpiKind || 'monetary';
  const mode = src.derivedMode || 'roi';
  const labels = { ...DEFAULT_LABELS, ...(src.labels || {}) };
  return {
    kpiKind,
    mode,
    metricLabel: labels.metricLabel,
    metricShort: labels.metricShortLabel,
    targetUnit: labels.targetUnitLabel,
    targetAxis: labels.targetAxisLabel,
    vpcu: src.valuePerCountUnit != null ? Number(src.valuePerCountUnit) : null,
    vpcuLabel: src.valuePerCountUnitLabel || '',
    isLegacy: kpiKind === 'monetary' && mode === 'roi',
  };
}

/**
 * Format single metric value per KPI/mode.
 *
 * monetary roi: 1.5 → '1.50×'
 * count: 120.5 → '120 ₽/ед.'
 * effectiveness fraction (0..1): 0.25 → '25.0%'
 * effectiveness >1: 25 → '25%'
 *
 * @param {number|null|undefined} value
 * @param {KpiView} kpi
 * @param {string} [fallback]
 * @returns {string}
 */
export function fmtMetric(value, kpi, fallback = '—') {
  if (value == null) return fallback;
  const f = Number(value);
  if (!Number.isFinite(f)) return fallback;
  if (kpi.mode === 'effectiveness') {
    return Math.abs(f) <= 1.0 ? `${(f * 100).toFixed(1)}%` : `${f.toFixed(0)}%`;
  }
  if (kpi.kpiKind === 'count') {
    return `${f.toFixed(0)} ₽/ед.`;
  }
  return `${f.toFixed(2)}×`;
}

/**
 * Bare (number only) format для CI bracket inner values.
 *
 * @param {number|null|undefined} value
 * @param {KpiView} kpi
 * @returns {string}
 */
export function fmtMetricBare(value, kpi) {
  if (value == null) return '—';
  const f = Number(value);
  if (!Number.isFinite(f)) return '—';
  if (kpi.mode === 'effectiveness') {
    return Math.abs(f) <= 1.0 ? `${(f * 100).toFixed(1)}` : `${f.toFixed(0)}`;
  }
  if (kpi.kpiKind === 'count') return `${f.toFixed(0)}`;
  return `${f.toFixed(2)}`;
}

/**
 * Portfolio-aggregate phrase per KPI/mode.
 *
 * Narrative adapter всегда отдаёт weighted_roi = contrib / spend. Для
 * count KPI это units/₽ (обратное к CPU); инвертируем.
 *
 * monetary roi: 'ROI портфеля 1.50×'
 * count: 'CPU портфеля 80 ₽/ед.'
 * effectiveness: 'Средняя доля каналов в портфеле'
 *
 * @param {number|null|undefined} weightedValue
 * @param {KpiView} kpi
 * @returns {string}
 */
export function weightedPhrase(weightedValue, kpi) {
  if (weightedValue == null) return '';
  const wv = Number(weightedValue);
  if (!Number.isFinite(wv)) return '';
  if (kpi.mode === 'effectiveness') {
    return 'Средняя доля каналов в портфеле';
  }
  if (kpi.kpiKind === 'count') {
    if (wv > 0) {
      const cpu = 1 / wv;
      return `CPU портфеля ${cpu.toFixed(0)} ₽/ед.`;
    }
    return 'CPU портфеля недоступен';
  }
  return `ROI портфеля ${wv.toFixed(2)}×`;
}

/**
 * Условие «канал убыточен» для текстов рекомендаций.
 *
 * monetary roi: 'mROAS < 1×'
 * count: 'CPU > {vpcu} ₽/ед. (выше ценности)'
 * effectiveness: 'доля < бенчмарка'
 *
 * @param {KpiView} kpi
 * @returns {string}
 */
export function underBreakevenPhrase(kpi) {
  if (kpi.mode === 'effectiveness') return 'доля < бенчмарка';
  if (kpi.kpiKind === 'count') {
    if (kpi.vpcu) return `CPU > ${kpi.vpcu.toFixed(0)} ₽/ед. (выше ценности)`;
    return 'CPU > ценности единицы (убыточно)';
  }
  return 'mROAS < 1×';
}

/**
 * Build channel metric phrase (ROI vs CPU vs share) для текстов рекомендаций.
 *
 * Использует ch.mroas или ch.roi (mroas первичен). Если оба null → null.
 *
 * @param {{name?: string, mroas?: number, roi?: number}} ch
 * @param {KpiView} kpi
 * @returns {{ short: string, value: string }|null}
 */
export function channelMetricPhrase(ch, kpi) {
  if (!ch) return null;
  const v = ch.mroas ?? ch.roi;
  if (v == null) return null;
  return {
    short: kpi.metricShort,
    value: fmtMetric(v, kpi),
  };
}

/**
 * Per-channel benchmark «отличная отдача» threshold message.
 *
 * @param {KpiView} kpi
 * @returns {string}
 */
export function topMetricBenchmark(kpi) {
  if (kpi.mode === 'effectiveness') return 'Доля ≥ 30%';
  if (kpi.kpiKind === 'count') {
    if (kpi.vpcu) return `CPU ≤ ${(kpi.vpcu * 0.5).toFixed(0)} ₽/ед. (вдвое ниже ценности)`;
    return 'CPU вдвое ниже ценности единицы';
  }
  return 'ROI ≥ 2×';
}
