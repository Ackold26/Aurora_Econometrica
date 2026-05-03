<script>
  /**
   * Response curves with draggable budget points — KILLER FEATURE.
   * A2: ResizeObserver recomputes graphic positions after chart.resize().
   * A3: clamp convertFromPixel to [0, maxSpend].
   * Bidirectional sync: sliders ↔ draggable points.
   * @component ResponseCurves
   */
  import { onMount } from 'svelte';
  import { hillFunction } from '$lib/hill.js';
  import { CHANNEL_COLORS } from '$lib/hill.js';

  /**
   * @type {{
   *   responseCurves: Record<string, {spend: number[], response: number[], current_x: number, optimal_x: number}>,
   *   channelBudgets: Record<string, number>,
   *   scaledParams: Record<string, {alpha: number, gammaScaled: number, beta: number}>,
   *   channels: string[],
   *   onBudgetChange: (ch: string, val: number) => void,
   *   unitCosts?: Record<string, number>,
   * }}
   */
  let { responseCurves, channelBudgets, scaledParams, channels, onBudgetChange, unitCosts = {} } = $props();

  /** Стоимость 1 юнита канала в ₽. 1.0 — канал уже в деньгах. */
  /** @param {string} ch */
  function uc(ch) {
    const v = unitCosts?.[ch];
    return (typeof v === 'number' && v > 0) ? v : 1.0;
  }

  /** @type {HTMLDivElement} */
  let container;
  /** @type {any} */
  let chart;
  /** @type {ResizeObserver | null} */
  let ro = null;
  /** True while user is dragging a point — suppresses $effect graphic rebuilds */
  let dragging = false;

  /**
   * Compute Y value on the curve at given spend X.
   * @param {string} ch
   * @param {number} x
   * @returns {number}
   */
  function responseAt(ch, x) {
    const p = scaledParams[ch];
    if (!p) return 0;
    return p.beta * hillFunction(x, p.alpha, p.gammaScaled);
  }

  /**
   * Linear interpolate Y on backend response curve at given native spend X.
   * Used для markPoint static positions (current_x / optimal_x). Backend
   * curve denormalized to KPI scale + adstock_factor → matches series Y axis.
   * @param {{spend: number[], response: number[]} | null | undefined} curve
   * @param {number} x — native spend
   * @returns {number}
   */
  function curveResponseAt(curve, x) {
    if (!curve || !curve.spend?.length) return 0;
    if (x <= curve.spend[0]) return curve.response[0];
    for (let i = 1; i < curve.spend.length; i++) {
      if (curve.spend[i] >= x) {
        const x0 = curve.spend[i - 1], y0 = curve.response[i - 1];
        const x1 = curve.spend[i], y1 = curve.response[i];
        const dx = x1 - x0;
        return dx > 0 ? y0 + (y1 - y0) * (x - x0) / dx : y0;
      }
    }
    return curve.response[curve.response.length - 1];
  }

  /**
   * Build graphic elements (draggable points) for all channels.
   * @returns {any[]}
   */
  function buildGraphic() {
    if (!chart) return [];
    return channels.map((ch, idx) => {
      const u = uc(ch);
      const xNative = channelBudgets[ch] ?? 0;
      const xMoney = xNative * u;              // ось графика в money
      // FIX 2026-05-02: точки строго на линии. Раньше использовали responseAt()
      // (локальная Hill через scaledParams) — могла давать значения, чуть
      // расходящиеся с backend response curve (разные normalization paths).
      // Теперь Y берём из backend curve interpolation — same source как линия.
      // Fallback к responseAt если curve missing (early render до response).
      const curveSrc = responseCurves?.[ch];
      const y = curveSrc && curveSrc.spend?.length
        ? curveResponseAt(curveSrc, xNative)
        : responseAt(ch, xNative);
      const px = chart.convertToPixel('grid', [xMoney, y]);
      if (!px) return null;
      const color = CHANNEL_COLORS[idx % CHANNEL_COLORS.length];
      const curve = responseCurves[ch];
      const maxSpendMoney = (curve ? Math.max(...curve.spend) : (channelBudgets[ch] ?? 0) * 2.5) * u;
      return {
        type: 'circle',
        id: `drag-${ch}`,
        // Reset position offset — prevents drag offset accumulation on rebuild
        position: [0, 0],
        shape: { cx: px[0], cy: px[1], r: 8 },
        style: { fill: color, stroke: '#fff', lineWidth: 2, opacity: 0.9 },
        draggable: 'horizontal',
        z: 100,
        ondragstart: () => { dragging = true; },
        ondrag: (/** @type {any} */ e) => {
          const dataCoord = chart.convertFromPixel('grid', [e.offsetX, e.offsetY]);
          const newMoney = Math.max(0, Math.min(dataCoord[0], maxSpendMoney));
          // Обратно в native для Hill/optimizer.
          onBudgetChange(ch, newMoney / u);
        },
        ondragend: () => { dragging = false; },
      };
    }).filter(Boolean);
  }

  /**
   * Audit pass 9 (Антон 2026-05-03 cont): x-axis max ТОЛЬКО от channelBudgets
   * (live slider state, forecast scale). Pre-fix (pass 6) включал curve.
   * current_x и curve.optimal_x — но `current_x = cur = float(df[col].sum())`
   * это TRAINING total native (multi-year sum), а `optimal_x` = FORECAST scale.
   * Mixing scales → x-axis инфлятилось к training scale (e.g. для «Малые
   * медиа» 4.3B training total → x-axis до 6.5B при реальном forecast budget
   * 1.787B). channelBudgets — live slider, всегда reflects current view
   * scale (forecast в planner mode, training в analyst). Max × 1.5 headroom.
   * Drag exceeding headroom auto-extended ECharts (graceful).
   * @returns {number | null}
   */
  function computeAdaptiveXMax() {
    let maxMoney = 0;
    for (const ch of channels) {
      const u = uc(ch);
      const cur = (channelBudgets[ch] ?? 0) * u;
      if (cur > maxMoney) maxMoney = cur;
    }
    // 1.5× headroom — место для drag вправо без обрезки + читаемая шкала
    return maxMoney > 0 ? maxMoney * 1.5 : null;
  }

  /**
   * Rebuild and set full chart option.
   */
  function rebuildChart() {
    if (!chart) return;

    const xAxisMax = computeAdaptiveXMax();

    const seriesList = channels.map((ch, idx) => {
      const curve = responseCurves?.[ch];
      const color = CHANNEL_COLORS[idx % CHANNEL_COLORS.length];
      const u = uc(ch);
      // Кривая рисуется в money по X (native × unit_cost) — все каналы на одной оси.
      const data = curve
        ? curve.spend.map((s, i) => [s * u, curve.response[i]])
        : [];

      // L5 extension (math-fix v1.4 Section C, 2026-04-28): static markers для
      // current_x (○ серый) + optimal_x (★ золотой). Pre-fix: только draggable
      // point показывал текущую позицию — customer не видел WHERE оптимум на
      // кривой. Post-fix: visual cue «отсюда → сюда» — после applyOptimal
      // draggable point переходит к ★, indicating «you're at optimum».
      /** @type {any[]} */
      const markData = [];
      if (curve && Number.isFinite(curve.current_x)) {
        markData.push({
          coord: [curve.current_x * u, curveResponseAt(curve, curve.current_x)],
          symbol: 'circle',
          symbolSize: 9,
          itemStyle: { color: 'rgba(148,163,184,0.85)', borderColor: '#fff', borderWidth: 1.5 },
          label: { show: false },
          tooltip: { formatter: () => `${ch} — текущий бюджет` },
        });
      }
      if (curve && Number.isFinite(curve.optimal_x)) {
        markData.push({
          coord: [curve.optimal_x * u, curveResponseAt(curve, curve.optimal_x)],
          symbol: 'pin',
          symbolSize: 26,
          // Audit fix (2026-04-29): removed symbolOffset [0, '-50%'] — pin's
          // anchor is bottom-tip by default, offset shifted tip away from data
          // coord (visual mismatch). Default behavior places tip ON the curve.
          itemStyle: { color, borderColor: '#fff', borderWidth: 2, opacity: 0.95 },
          label: { show: true, formatter: '★', color: '#fff', fontSize: 11, fontWeight: 'bold', position: 'inside' },
          tooltip: { formatter: () => `${ch} — оптимальный бюджет` },
        });
      }

      return {
        name: ch,
        type: 'line',
        data,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color },
        itemStyle: { color },
        emphasis: { focus: 'none' },
        markPoint: markData.length ? { data: markData, animation: false } : undefined,
      };
    });

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'none',
      },
      legend: {
        type: 'scroll',
        textStyle: { color: '#94a3b8', fontSize: 11 },
        top: 4,
        pageTextStyle: { color: '#94a3b8' },
      },
      grid: { left: 16, right: 16, top: 44, bottom: 32, containLabel: true },
      xAxis: {
        type: 'value',
        name: 'Бюджет, ₽',
        nameTextStyle: { color: '#64748b', fontSize: 10 },
        // Phase 2 audit pass 6 (Антон 2026-05-03): adaptive max — based на
        // largest channel budget × 1.5 (не на curve.spend native max which для
        // multi-year training может быть 100× больше реального бюджета).
        ...(xAxisMax != null ? { max: xAxisMax } : {}),
        axisLabel: {
          color: '#94a3b8', fontSize: 10,
          formatter: (/** @type {number} */ v) => v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v),
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
      },
      yAxis: {
        type: 'value',
        name: 'Эффект',
        nameTextStyle: { color: '#64748b', fontSize: 10 },
        axisLabel: {
          color: '#94a3b8', fontSize: 10,
          formatter: (/** @type {number} */ v) => v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v),
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
      },
      series: seriesList,
    }, true);

    // Set graphic after chart renders
    requestAnimationFrame(() => {
      const graphic = buildGraphic();
      chart.setOption({ graphic });
    });
  }

  onMount(() => {
    (async () => {
      const { echarts } = await import('$lib/echarts-setup.js');
      if (!container) return;
      const { getBaseChartOption } = await import('$lib/echarts-setup.js');
      chart = echarts.init(container);
      chart.setOption(getBaseChartOption());

      rebuildChart();

      // A2: recompute graphic positions after resize
      ro = new ResizeObserver(() => {
        chart?.resize();
        requestAnimationFrame(() => {
          const graphic = buildGraphic();
          if (chart && graphic.length) chart.setOption({ graphic });
        });
      });
      ro.observe(container);
    })();
    return () => {
      ro?.disconnect();
      chart?.dispose();
    };
  });

  // Reactive: when budgets change from sliders → update graphic positions
  // Skip during drag — the user is moving the point, don't snap it back
  $effect(() => {
    // Access channelBudgets to create dependency
    const _ = JSON.stringify(channelBudgets);
    if (!chart || dragging) return;
    requestAnimationFrame(() => {
      if (dragging) return;
      const graphic = buildGraphic();
      if (graphic.length) chart.setOption({ graphic });
    });
  });

  // Reactive: when responseCurves data changes → rebuild series
  $effect(() => {
    const _ = responseCurves;
    if (chart) rebuildChart();
  });
</script>

<div bind:this={container} style="width:100%;height:320px"></div>
