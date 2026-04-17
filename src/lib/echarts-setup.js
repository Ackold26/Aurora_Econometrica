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
    tooltip: {
      backgroundColor: 'rgba(30, 33, 44, 0.95)',
      borderColor,
      textStyle: { color: textColor },
    },
    xAxis: { axisLine: { lineStyle: { color: borderColor } }, axisLabel: { color: textSecondary }, splitLine: { lineStyle: { color: borderColor } } },
    yAxis: { axisLine: { lineStyle: { color: borderColor } }, axisLabel: { color: textSecondary }, splitLine: { lineStyle: { color: borderColor } } },
  };
}
