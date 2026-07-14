/**
 * KPI/mode-aware label & format helpers для insights / UI компонентов (v1.4.0).
 *
 * Frontend mirror of:
 *   - sidecar/econometrica/aurora_html/sections.py:_kpi_view
 *   - sidecar/econometrica/aurora_pptx/kpi_helpers.py
 *   - sidecar/econometrica/utils/kpi_labels.py
 *
 * Use:
 *   import { kpiView, fmtMetric, weightedPhrase } from '$lib/kpi-aware-formatting.js';
 *
 *   const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'leads', valuePerCountUnit: 80 });
 *   // → { kpiKind: 'count', mode: 'roi', metricShort: 'CPU', kpiType: 'leads', isLegacy: false, ... }
 *
 *   fmtMetric(0.0125, kpi);       // → '80 ₽/лид'
 *   weightedPhrase(0.0125, kpi);  // → 'CPU портфеля 80 ₽/лид'
 *   underBreakevenPhrase(kpi);    // → 'CPU > 80 ₽/лид (выше ценности)'
 *
 * @module kpi-aware-formatting
 */

import { getDisplay } from './kpi/kpi-display.js';

/**
 * @typedef {Object} KpiViewInput
 * @property {string} [kpiKind] - 'monetary' | 'count'
 * @property {string} [derivedMode] - 'roi' | 'effectiveness' | 'manual'
 * @property {number|null} [valuePerCountUnit] - ₽ per count unit (для count KPI)
 * @property {string} [valuePerCountUnitLabel]
 * @property {string|null} [kpiType] - паспортный тип KPI ('leads', 'sales_packs', 'sales', ...)
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
 * @property {string|null} kpiType
 * @property {string} cpuPerLabel
 */

const DEFAULT_LABELS = {
  metricLabel: 'ROI',
  metricShortLabel: 'ROI',
  targetUnitLabel: '₽',
  targetAxisLabel: 'Продажи, ₽',
};

/**
 * B3 audit fix (v1.3.2): derive labels из kpiKind+mode локально. Mirrors
 * Python utils/kpi_labels.py:metric_label/metric_short_label/etc. Используется
 * когда caller не передаёт labels (например InsightsPanel - только kpiKind/
 * mode/vpcu приходят из stores, labels не stored). Fallback к default ROI
 * labels для legacy ctx.
 *
 * Фаза 1b: когда kpiType задан — берём оси/единицы из паспорта getDisplay(kpiType).
 * Backward-compat: без kpiType — прежнее поведение (kind-only).
 *
 * @param {string} kpiKind
 * @param {string} mode
 * @param {string|null|undefined} [kpiType]
 * @returns {{ metricLabel: string, metricShortLabel: string, targetUnitLabel: string, targetAxisLabel: string, cpuPerLabel: string }}
 */
function deriveLabels(kpiKind, mode, kpiType) {
  // Паспортные оси — берём из реестра если kpiType задан и известен
  let passportAxisLabel = null;
  let passportUnitShort = null;
  let passportCpuPerLabel = '₽/ед.';

  if (kpiType) {
    try {
      const P = getDisplay(kpiType);
      passportAxisLabel = P.result_axis_label;
      passportUnitShort = P.result_unit_short;
      if (P.cpu_per_label) passportCpuPerLabel = P.cpu_per_label;
    } catch (_) {
      // неизвестный kpiType — graceful fallback
    }
  }

  if (mode === 'effectiveness') {
    return {
      metricLabel: 'Доля %',
      metricShortLabel: 'Доля',
      // Фикс бага: effectiveness раньше давал 'Продажи, ₽' даже для count.
      // Теперь — всегда паспортная ось (если kpiType задан), иначе kind-aware fallback.
      targetUnitLabel: passportUnitShort ?? (kpiKind === 'count' ? 'ед.' : '₽'),
      targetAxisLabel: passportAxisLabel ?? (kpiKind === 'count' ? 'Продажи, упак' : 'Продажи, ₽'),
      cpuPerLabel: passportCpuPerLabel,
    };
  }
  if (kpiKind === 'count') {
    return {
      metricLabel: `CPU, ${passportCpuPerLabel}`,
      metricShortLabel: 'CPU',
      targetUnitLabel: passportUnitShort ?? 'упак / ед.',
      targetAxisLabel: passportAxisLabel ?? 'Продажи, упак',
      cpuPerLabel: passportCpuPerLabel,
    };
  }
  return { ...DEFAULT_LABELS, cpuPerLabel: '₽/ед.' };
}

/**
 * Build KPI view from raw stores / data dict. Defaults preserve v1.2 behavior.
 *
 * B3 audit fix: labels приоритизируются:
 *   1. Explicit input.labels (если caller передал - backend payload).
 *   2. Derived from kpiKind+mode+kpiType (когда labels не переданы - InsightsPanel
 *      путь). Mirrors Python kpi_labels.py logic.
 *   3. DEFAULT_LABELS (legacy fallback - kpiKind=monetary mode=roi).
 *
 * Фаза 1b: kpiType прокидывается в view для downstream-функций.
 *
 * @param {KpiViewInput|null|undefined} input
 * @returns {KpiView}
 */
export function kpiView(input) {
  const src = input || {};
  const kpiKind = src.kpiKind || 'monetary';
  const mode = src.derivedMode || 'roi';
  const kpiType = src.kpiType || null;
  // Merge order: defaults < derived (from kind+mode+kpiType) < explicit labels.
  const derived = deriveLabels(kpiKind, mode, kpiType);
  // cpuPerLabel идёт из derived (deriveLabels задаёт его во всех ветках) —
  // не дублируем явно, иначе значение перезаписывается (svelte-check).
  const labels = { ...DEFAULT_LABELS, ...derived, ...(src.labels || {}) };
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
    kpiType,
    cpuPerLabel: labels.cpuPerLabel || '₽/ед.',
  };
}

/**
 * Format single metric value per KPI/mode.
 *
 * B4 audit fix (v1.3.2): backend convention - per-channel mroas/roi всегда
 * mathematical ratio (KPI_units / ₽_spend). Для count это units/₽ (e.g.
 * 0.0125). CPU = 1/x. fmtMetric inverts при display.
 *
 * monetary roi: 1.5 → '1.50×' (no transform)
 * count: 0.0125 → '80 ₽/ед.' (inverted)
 * effectiveness fraction (0..1): 0.25 → '25.0%'
 * effectiveness >1: 25 → '25%'
 *
 * @param {number|null|undefined} value
 * @param {KpiView} kpi
 * @param {string} [fallback]
 * @returns {string}
 */
export function fmtMetric(value, kpi, fallback = '-') {
  if (value == null) return fallback;
  const f = Number(value);
  if (!Number.isFinite(f)) return fallback;
  if (kpi.mode === 'effectiveness') {
    return Math.abs(f) <= 1.0 ? `${(f * 100).toFixed(1)}%` : `${f.toFixed(0)}%`;
  }
  if (kpi.kpiKind === 'count') {
    // B4: invert units/₽ → CPU. Zero/negative → fallback (no signal).
    // Фаза 1b: используем kpi.cpuPerLabel ('₽/лид', '₽/упак.', ...) вместо '₽/ед.'
    if (f > 0) return `${(1 / f).toFixed(0)} ${kpi.cpuPerLabel || '₽/ед.'}`;
    return fallback;
  }
  return `${f.toFixed(2)}×`;
}

/**
 * Bare (number only) format для CI bracket inner values. См. fmtMetric inversion.
 *
 * @param {number|null|undefined} value
 * @param {KpiView} kpi
 * @returns {string}
 */
export function fmtMetricBare(value, kpi) {
  if (value == null) return '-';
  const f = Number(value);
  if (!Number.isFinite(f)) return '-';
  if (kpi.mode === 'effectiveness') {
    return Math.abs(f) <= 1.0 ? `${(f * 100).toFixed(1)}` : `${f.toFixed(0)}`;
  }
  if (kpi.kpiKind === 'count') {
    if (f > 0) return `${(1 / f).toFixed(0)}`;
    return '-';
  }
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
      // Фаза 1b: используем kpi.cpuPerLabel вместо '₽/ед.'
      return `CPU портфеля ${cpu.toFixed(0)} ${kpi.cpuPerLabel || '₽/ед.'}`;
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
    // Фаза 1b: используем kpi.cpuPerLabel вместо '₽/ед.'
    const label = kpi.cpuPerLabel || '₽/ед.';
    if (kpi.vpcu) return `CPU > ${kpi.vpcu.toFixed(0)} ${label} (выше ценности)`;
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
    // Фаза 1b: используем kpi.cpuPerLabel вместо '₽/ед.'
    const label = kpi.cpuPerLabel || '₽/ед.';
    if (kpi.vpcu) return `CPU ≤ ${(kpi.vpcu * 0.5).toFixed(0)} ${label} (вдвое ниже ценности)`;
    return 'CPU вдвое ниже ценности единицы';
  }
  return 'ROI ≥ 2×';
}
