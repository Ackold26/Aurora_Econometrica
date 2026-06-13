/**
 * Tree-shaken ECharts import for Aurora Econometrica.
 * Phase 3: Bar/Line/Scatter charts.
 * Phase 4: +GraphicComponent (draggable points), +DataZoomComponent (timeline slider).
 */
import * as echarts from 'echarts/core';
import { BarChart, LineChart, ScatterChart } from 'echarts/charts';
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  GraphicComponent,
  DataZoomComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { escapeHtml } from './html-escape.js';
export { escapeHtml }; // re-export для chart-компонентов (общий util tooltip-экранирования)

echarts.use([
  BarChart, LineChart, ScatterChart,
  TitleComponent, TooltipComponent, GridComponent, LegendComponent, MarkLineComponent,
  GraphicComponent, DataZoomComponent,
  CanvasRenderer,
]);

export { echarts };

/**
 * Build base ECharts option from current CSS custom properties.
 * Call on init and on theme change to sync chart colors with app theme.
 * @returns {import('echarts').EChartsOption}
 */
export function getBaseChartOption() {
  if (typeof window === 'undefined') {
    return { backgroundColor: 'transparent' };
  }
  const s = getComputedStyle(document.documentElement);
  const textColor = s.getPropertyValue('--text-primary').trim() || '#e2e8f0';
  const textSecondary = s.getPropertyValue('--text-secondary').trim() || '#94a3b8';
  const borderColor = s.getPropertyValue('--border-subtle').trim() || 'rgba(255,255,255,0.06)';

  return {
    backgroundColor: 'transparent',
    textStyle: { color: textColor },
    title: { textStyle: { color: textColor }, subtextStyle: { color: textSecondary } },
    legend: { textStyle: { color: textSecondary } },
    tooltip: chartTooltipDark(),
    xAxis: { axisLine: { lineStyle: { color: borderColor } }, axisLabel: { color: textSecondary }, splitLine: { lineStyle: { color: borderColor } } },
    yAxis: { axisLine: { lineStyle: { color: borderColor } }, axisLabel: { color: textSecondary }, splitLine: { lineStyle: { color: borderColor } } },
  };
}

/**
 * Universal dark tooltip option for ECharts.
 * Темный полупрозрачный фон + белый текст - читается одинаково в light/dark/fun темах.
 * Использует кастомный formatter, чтобы заголовок и подписи серий тоже были белыми
 * (без него ECharts красит их цветом серии - плохой контраст на тёмном фоне).
 *
 * @param {{
 *   trigger?: 'axis' | 'item',
 *   numberFormat?: (v: number) => string,
 *   suffix?: string,
 * }} [opts]
 * @returns {import('echarts').TooltipComponentOption}
 */
export function chartTooltipDark(opts = {}) {
  const { trigger = 'axis', numberFormat, suffix = '' } = opts;
  const fmt = numberFormat || ((/** @type {number} */ v) => Math.round(v).toLocaleString('ru-RU'));

  /**
   * @param {any} v
   * @returns {string}
   */
  const renderValue = (v) => {
    if (v == null || v === '') return '-';
    if (Array.isArray(v)) return v.map(renderValue).join(', ');
    const n = typeof v === 'number' ? v : Number(v);
    if (!Number.isFinite(n)) return String(v);
    return fmt(n) + suffix;
  };

  return {
    trigger,
    backgroundColor: 'rgba(15, 18, 28, 0.94)',
    borderColor: 'rgba(255, 255, 255, 0.14)',
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: '#ffffff', fontSize: 12 },
    extraCssText: 'box-shadow: 0 6px 20px rgba(0,0,0,0.45); border-radius: 6px;',
    axisPointer: {
      label: {
        color: '#ffffff',
        backgroundColor: 'rgba(15, 18, 28, 0.94)',
        borderColor: 'rgba(255, 255, 255, 0.14)',
      },
    },
    formatter: (/** @type {any} */ params) => {
      const arr = Array.isArray(params) ? params : [params];
      if (arr.length === 0) return '';
      const head = trigger === 'axis' && arr[0]?.axisValue != null
        ? `<div style="color:#fff;font-weight:600;margin-bottom:6px;">${escapeHtml(arr[0].axisValue)}</div>`
        : '';
      const rows = arr.map((p) => {
        const dot = `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${p.color};margin-right:8px;vertical-align:middle;"></span>`;
        const name = p.seriesName ?? p.name ?? '';
        const val = renderValue(p.value);
        return `<div style="color:#fff;line-height:1.5;">${dot}<span style="color:#fff;opacity:0.9;">${escapeHtml(name)}</span>&nbsp;&nbsp;<b style="color:#fff;">${val}</b></div>`;
      }).join('');
      return head + rows;
    },
  };
}
