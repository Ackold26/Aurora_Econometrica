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
