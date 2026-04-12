/**
 * Tree-shaken ECharts import for Aurora Econometrica.
 * Only the chart types needed in Phase 3 — lazy-loaded via dynamic import.
 * B3: GaugeChart excluded (Phase 4).
 */
import * as echarts from 'echarts/core';
import { BarChart, LineChart, ScatterChart } from 'echarts/charts';
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  BarChart, LineChart, ScatterChart,
  TitleComponent, TooltipComponent, GridComponent, LegendComponent, MarkLineComponent,
  CanvasRenderer,
]);

export { echarts };
