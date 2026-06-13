/**
 * forecast-chart-format.js — форматтеры для MultiScenarioChart (тултип + легенда).
 *
 * Вынесены из компонента как ЧИСТЫЕ функции, чтобы юнит-тестировать без живого hover
 * (ECharts axis-tooltip не триггерится синтетическими событиями в headless). Образец
 * богатого тултипа — ChannelTimeline (дата-заголовок, цветные маркеры, значения).
 */
import { escapeHtml } from './html-escape.js';

/** Компактное число K/M/B (для осей и границ ДИ). */
export function compactNum(/** @type {number} */ v) {
  if (!Number.isFinite(v)) return '';
  const abs = Math.abs(v);
  if (abs >= 1e9) return (v / 1e9).toFixed(1) + 'B';
  if (abs >= 1e6) return (v / 1e6).toFixed(0) + 'M';
  if (abs >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return Math.round(v).toLocaleString('ru-RU');
}

/** Полное число с разделителями (для основной величины в тултипе). */
export function fmtFull(/** @type {number} */ v) {
  if (!Number.isFinite(v)) return '—';
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(Math.round(v));
}

/**
 * @typedef {{
 *   baseline: { name: string } | null,
 *   visibleScenarios: Array<{ name: string, predictions?: number[] }>,
 *   allDates: string[],
 *   cutoffIndex: number,
 *   baselineColor: string,
 *   scenarioColors: string[],
 * }} ChartCtx
 */

/** Одна строка тултипа: маркер + имя + значение (+ ДИ 90% веера). */
function tooltipRow(
  /** @type {string} */ color, /** @type {string} */ name, /** @type {number} */ v,
  /** @type {number|undefined} */ lo, /** @type {number|undefined} */ hi,
) {
  let s = '<div style="display:flex;align-items:baseline;gap:8px;margin:3px 0;">'
    + `<span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${color};flex-shrink:0;position:relative;top:1px;"></span>`
    + `<span style="color:rgba(255,255,255,0.82);font-size:12px;flex:1;">${escapeHtml(name)}</span>`
    + `<b style="color:#fff;font-size:12px;white-space:nowrap;">${fmtFull(v)}</b></div>`;
  if (Number.isFinite(lo) && Number.isFinite(hi)) {
    s += '<div style="margin:-2px 0 5px 17px;color:rgba(255,255,255,0.5);font-size:11px;">'
      + `ДИ&nbsp;90%: ${compactNum(/** @type {number} */ (lo))} – ${compactNum(/** @type {number} */ (hi))}</div>`;
  }
  return s;
}

/**
 * Богатый тултип forecast-графика: дата + метка история/прогноз + строка на серию
 * (baseline + видимые сценарии) с маркером, значением и ДИ 90% веера. Helper-серии
 * CI (`{name}_ci_low/high`) используются ТОЛЬКО как источник границ, не выводятся.
 *
 * @param {any} rawParams ECharts axis-trigger params (массив или один объект)
 * @param {ChartCtx} ctx
 * @returns {string} HTML ('' когда в точке нет значений)
 */
export function buildForecastTooltip(rawParams, ctx) {
  const params = Array.isArray(rawParams) ? rawParams : [rawParams];
  if (params.length === 0) return '';
  const { baseline, visibleScenarios, allDates, cutoffIndex, baselineColor, scenarioColors } = ctx;
  const date = params[0]?.axisValue ?? '';
  const idx = allDates.indexOf(date);
  const isForecast = cutoffIndex >= 0 && idx > cutoffIndex;

  /** @type {Record<string, number>} */
  const val = {};
  params.forEach((/** @type {any} */ p) => { if (p && p.seriesName != null) val[p.seriesName] = p.value; });

  let html = '<div style="display:flex;justify-content:space-between;gap:14px;align-items:center;margin-bottom:5px;">'
    + `<span style="color:#fff;font-weight:600;">${escapeHtml(date)}</span>`
    + '<span style="color:rgba(255,255,255,0.45);font-size:11px;text-transform:uppercase;letter-spacing:0.04em;">'
    + `${isForecast ? 'прогноз' : 'история'}</span></div>`;

  let hasRow = false;
  if (baseline && Number.isFinite(val[baseline.name])) {
    html += tooltipRow(baselineColor, baseline.name, val[baseline.name], undefined, undefined);
    hasRow = true;
  }
  visibleScenarios.forEach((sc, i) => {
    const v = val[sc.name];
    if (!Number.isFinite(v)) return;
    const color = scenarioColors[i % scenarioColors.length];
    html += tooltipRow(color, sc.name, v, val[`${sc.name}_ci_low`], val[`${sc.name}_ci_high`]);
    hasRow = true;
  });
  return hasRow ? html : '';
}

/**
 * Метка легенды: для сценария добавляет итоговый прогноз (endpoint) для быстрого ранга;
 * baseline и неизвестные — как есть.
 *
 * @param {string} name
 * @param {{ baseline: { name: string } | null, visibleScenarios: Array<{ name: string, predictions?: number[] }> }} ctx
 * @returns {string}
 */
export function forecastLegendLabel(name, ctx) {
  if (ctx.baseline && name === ctx.baseline.name) return name;
  const sc = ctx.visibleScenarios.find((s) => s.name === name);
  if (!sc) return name;
  // Последнее конечное значение без копии/reverse массива (горячий путь рендера легенды).
  const preds = sc.predictions ?? [];
  let last = null;
  for (let i = preds.length - 1; i >= 0; i--) {
    if (Number.isFinite(preds[i])) { last = preds[i]; break; }
  }
  return last != null ? `${name}  ·  ${compactNum(last)}` : name;
}
