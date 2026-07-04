<script>
  /**
   * Stacked area chart showing per-period contributions.
   * Baseline at bottom, channels stacked above.
   * DataZoom slider for period zoom (Phase 4, Plan 4A.6).
   * @component ChannelTimeline
   */
  import { onDestroy } from 'svelte';
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark, escapeHtml } from '$lib/echarts-setup.js';
  import { CHANNEL_COLORS } from '$lib/hill.js';

  /**
   * @type {{
   *   timeSeries: {
   *     dates: string[],
   *     baseline: number[],
   *     channels: Record<string, number[]>
   *   },
   *   signedFactors?: Record<string, {
   *     value: number, pct: number, type: string,
   *     beta_mean: number, per_period: number[]
   *   }>,
   *   decompositionSeries?: {
   *     dates: string[],
   *     series: Array<{ name: string, role: 'baseline'|'media'|'factor',
   *       type: string, group: string, side: 'positive'|'negative', data: number[] }>,
   *   },
   * }}
   */
  let { timeSeries, signedFactors = undefined, decompositionSeries = undefined } = $props();

  // v2.1.0 (пилот 2026-05-16): отрицательные signed factors (конкуренты,
  // цены, погода с отрицательным эффектом) показываем ниже нулевой линии
  // отдельным stack-group'ом - красно-оранжевая палитра, читается как
  // «отъедают продажи». Положительные controls (holiday + positive_control)
  // добавляются в общий positive stack.
  /** @type {Record<string, string>} */
  const FACTOR_COLORS = {
    signed_competitor: '#dc2626', // red-600
    signed_price:      '#ea580c', // orange-600
    signed_weather:    '#f59e0b', // amber-500
    signed_macro:      '#d97706', // amber-600
    holiday:           '#84cc16', // lime-500
    seasonality:       '#8b5cf6', // violet-500 — сезонность (цикл)
    positive_control:  '#06b6d4', // cyan-500
  };
  /** @type {Record<string, string>} */
  const FACTOR_LABELS = {
    signed_competitor: 'Конкуренты',
    signed_price:      'Цена',
    signed_weather:    'Погода',
    signed_macro:      'Макро-факторы',
    holiday:           'Праздники',
    seasonality:       'Сезонность',
    positive_control:  'Внешние факторы',
  };

  // FIX 2026-05-02: track currently hovered series для подсветки в tooltip.
  // Plain mutable (не $state) - closure formatter reads current value без
  // recompute derived option (иначе chart.setOption flicker'ит на каждом mouseover).
  let activeSeries = '';
  /** @type {number | null} */
  let activeSeriesIndex = null;
  /** @type {any} */
  let chartRef = null;

  /** @type {HTMLElement | null} */
  let cleanupDom = null;
  /** @type {((ev: MouseEvent) => void) | null} */
  let cleanupMouseMove = null;
  /** @type {(() => void) | null} */
  let cleanupMouseLeave = null;

  // AUDIT 2026-05-04: explicit listener cleanup - DOM listeners на chart container
  // НЕ удаляются ECharts.dispose(). Без этого - memory leak при switch проектов.
  onDestroy(() => {
    if (cleanupDom) {
      if (cleanupMouseMove) cleanupDom.removeEventListener('mousemove', cleanupMouseMove);
      if (cleanupMouseLeave) cleanupDom.removeEventListener('mouseleave', cleanupMouseLeave);
    }
    cleanupDom = null;
    cleanupMouseMove = null;
    cleanupMouseLeave = null;
  });

  /** @param {any} chart */
  function handleChartInit(chart) {
    chartRef = chart;
    // 2026-05-04: track активный слой через DOM mousemove + Y-coordinate matching.
    // Ранние попытки (mouseover/series, updateAxisPointer) не срабатывали для
    // stacked area: ECharts не отдаёт seriesIndex слоя под курсором - только
    // dataIndex по оси X. Решение: при mousemove считаем сумму stack'ов до
    // курсора по Y-координате, находим тот слой чья граница выше курсора.
    const dom = chart.getDom();
    if (!dom) return;
    cleanupDom = dom;

    /** Apply highlight + tooltip + legend для new active. */
    const applyActive = (/** @type {string} */ name, /** @type {number | null} */ idx) => {
      if (name === activeSeries) return;
      if (activeSeriesIndex != null) {
        chart.dispatchAction({ type: 'downplay', seriesIndex: activeSeriesIndex });
      }
      activeSeries = name;
      activeSeriesIndex = idx;
      if (idx != null) {
        chart.dispatchAction({ type: 'highlight', seriesIndex: idx });
      }
      // Force tooltip + legend rerender. setOption merge мode (notMerge=false)
      // подменяет formatter на свежий closure → ECharts инвалидирует кэш
      // и при следующем showTip перевызовет с актуальным activeSeries.
      chart.setOption({
        tooltip: buildTooltipOption(),
        legend: buildLegendOption(name),
      }, false);
    };

    // 2026-05-04 sync fix: dataIndex беру из ECharts updateAxisPointer event
    // (тот же snapped index что использует axisPointer/cross/tooltip). Раньше
    // я считал dataIndex напрямую из convertFromPixel - отличался от ECharts
    // snap → перекрестье на одном периоде, моя подсветка на соседнем. Теперь
    // оба источника синхронизированы.
    /** @type {{px: number, py: number} | null} */
    let lastMouse = null;

    /** @param {MouseEvent} ev */
    const onMouseMove = (ev) => {
      const rect = dom.getBoundingClientRect();
      lastMouse = { px: ev.clientX - rect.left, py: ev.clientY - rect.top };
      if (!chart.containPixel('grid', [lastMouse.px, lastMouse.py])) {
        if (activeSeries) applyActive('', null);
      }
    };
    dom.addEventListener('mousemove', onMouseMove);
    cleanupMouseMove = onMouseMove;

    chart.on('updateAxisPointer', (/** @type {any} */ params) => {
      if (!lastMouse) return;
      const axesInfo = params?.axesInfo;
      if (!Array.isArray(axesInfo) || axesInfo.length === 0) return;
      // ECharts отдаёт snapped value по xAxis - это и есть dataIndex для category axis.
      const xInfo = axesInfo.find(/** @type {(a: any) => boolean} */ (a) => a?.axisDim === 'x');
      const dataIndex = xInfo?.value;
      if (!Number.isFinite(dataIndex) || dataIndex < 0) return;

      const opt = chart.getOption();
      const allSeries = opt.series || [];
      if (!allSeries.length) return;

      // Y-coord курсора в data space (через convertFromPixel - snap не нужен).
      const yData = chart.convertFromPixel({ seriesIndex: 0 }, [lastMouse.px, lastMouse.py])[1];
      // Аудит #12 (#10): держим ДВА аккумулятора — положительный стек растёт от 0
      // вверх, отрицательный (конкуренты/цены ниже нуля, stack='negative') — от 0
      // вниз. Раньше был один cum от 0 вверх → полосы под нулём не подсвечивались.
      let cumPos = 0;
      let cumNeg = 0;
      let foundIdx = -1;
      let foundName = '';
      for (let i = 0; i < allSeries.length; i++) {
        const s = allSeries[i];
        const v = Number(s.data?.[dataIndex] ?? 0);
        const isNeg = s.stack === 'negative';
        if (isNeg) {
          const next = cumNeg + (Number.isFinite(v) ? v : 0); // v ≤ 0 → next ≤ cumNeg
          if (yData <= cumNeg && yData >= next) {
            foundIdx = i;
            foundName = s.name ?? '';
            break;
          }
          cumNeg = next;
        } else {
          const next = cumPos + (Number.isFinite(v) ? v : 0);
          if (yData >= cumPos && yData <= next) {
            foundIdx = i;
            foundName = s.name ?? '';
            break;
          }
          cumPos = next;
        }
      }
      if (foundName) {
        if (foundName !== activeSeries) applyActive(foundName, foundIdx);
      } else if (activeSeries) {
        applyActive('', null);
      }
    });

    const onMouseLeave = () => {
      lastMouse = null;
      if (activeSeries) applyActive('', null);
    };
    dom.addEventListener('mouseleave', onMouseLeave);
    cleanupMouseLeave = onMouseLeave;
  }

  /** Legend block - formatter подсвечивает активный пункт. Извлечён из option,
   *  чтобы handleChartInit мог обновлять только legend через setOption merge. */
  function buildLegendOption(/** @type {string} */ active) {
    return {
      type: 'scroll',
      textStyle: { color: '#94a3b8', fontSize: 11 },
      top: 4,
      pageTextStyle: { color: '#94a3b8' },
      formatter: (/** @type {string} */ name) =>
        active && name === active ? `▶ ${name}` : name,
    };
  }

  /** Tooltip block - formatter читает activeSeries из closure модуля.
   *  Переустанавливается через setOption merge на каждый смены активного слоя,
   *  чтобы ECharts инвалидировал кэш и перевызвал formatter с актуальным name. */
  function buildTooltipOption() {
    return {
      ...chartTooltipDark({ trigger: 'axis' }),
      axisPointer: { type: 'cross', label: { backgroundColor: 'rgba(15,18,28,0.94)', color: '#fff' } },
      extraCssText: 'max-height:420px;overflow:auto;max-width:380px',
      formatter: (/** @type {any[]} */ params) => {
        const total = params.reduce((s, p) => s + (p.value ?? 0), 0);
        const fmt = (/** @type {number} */ v) =>
          new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(Math.round(v));

        // Prefix regex для очистки seriesName в строках групп
        const PREFIX_RE = /^(Конкуренты|Праздники|Внешние|Цена|Погода|Макро-факторы):\s*/;

        /**
         * Классифицируем каждый элемент params по одной из 5 групп:
         *   'База' | 'Конкуренты' | 'Праздники' | 'Внешние' | 'Медиа'
         */
        const GROUP_ORDER = ['База', 'Медиа', 'Конкуренты', 'Праздники', 'Внешние'];

        /** @type {Map<string, Array<{p: any, cleanName: string}>>} */
        const groups = new Map(GROUP_ORDER.map(g => [g, []]));

        params.forEach(p => {
          const name = p.seriesName ?? '';
          let group;
          if (name === 'Базовый уровень') {
            group = 'База';
          } else if (name.startsWith('Конкуренты:')) {
            group = 'Конкуренты';
          } else if (name.startsWith('Праздники:')) {
            group = 'Праздники';
          } else if (
            name.startsWith('Внешние:') ||
            name.startsWith('Цена:') ||
            name.startsWith('Погода:') ||
            name.startsWith('Макро-факторы:')
          ) {
            group = 'Внешние';
          } else {
            group = 'Медиа';
          }
          const cleanName = name.replace(PREFIX_RE, '');
          groups.get(group)?.push({ p, cleanName });
        });

        // Заголовок с датой периода
        let html = `<div style="color:#fff;font-weight:600;margin-bottom:6px;">${escapeHtml(params[0]?.axisValue)}</div>`;

        // Блок активного слоя (highlight) — сохраняем поведение из v2.0
        const active = activeSeries ? params.find(p => p.seriesName === activeSeries) : null;
        if (active) {
          const aPct = total > 0 ? ((active.value / total) * 100).toFixed(1) : '0.0';
          html += `<div style="display:flex;align-items:center;gap:8px;background:linear-gradient(90deg,${active.color}33,transparent);border-left:3px solid ${active.color};padding:6px 8px;margin:0 -6px 6px -6px;border-radius:3px;">`
            + `<span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:${active.color};box-shadow:0 0 8px ${active.color};"></span>`
            + `<div style="display:flex;flex-direction:column;line-height:1.25;">`
            + `<span style="color:#fff;font-weight:700;font-size:13px;">${escapeHtml(active.seriesName)}</span>`
            + `<span style="color:rgba(255,255,255,0.85);font-size:12px;"><b>${fmt(active.value)}</b> &middot; ${aPct}% от периода</span>`
            + `</div></div>`;
        }

        // Группированные строки
        GROUP_ORDER.forEach(groupLabel => {
          const items = groups.get(groupLabel);
          if (!items || items.length === 0) return;

          const subtotal = items.reduce((s, { p }) => s + (p.value ?? 0), 0);
          const pct = total > 0 ? ((subtotal / total) * 100).toFixed(1) : '0.0';

          // Заголовок группы
          html += `<div style="font-weight:600;margin-top:6px;color:#94a3b8;font-size:11px">${groupLabel} · ${fmt(subtotal)} (${pct}%)</div>`;

          // Строки каналов внутри группы
          items.forEach(({ p, cleanName }) => {
            const isActive = activeSeries && activeSeries === p.seriesName;
            const dimmed = activeSeries && !isActive;
            const opacity = dimmed ? '0.45' : '1';
            html += `<div style="display:flex;justify-content:space-between;gap:10px;padding-left:8px;opacity:${opacity}${isActive ? ';font-weight:600' : ''}">`
              + `<span><span style="color:${p.color}">&#9679;</span> ${escapeHtml(cleanName)}</span>`
              + `<span style="font-variant-numeric:tabular-nums">${fmt(p.value)}</span>`
              + `</div>`;
          });
        });

        // Итог
        html += `<div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);font-weight:600;display:flex;justify-content:space-between">`
          + `<span>Итого</span><span>${fmt(total)}</span>`
          + `</div>`;

        return html;
      },
    };
  }

  /**
   * Аудит #12 (2026-06-07, INV-50): построить option из канонического
   * decomposition_series — ТОГО ЖЕ источника, что у всех отчётов. baseline здесь
   * уже уменьшен на вынесенные факторы → нет double-count положительных праздников
   * (он был в legacy-ветке: положительные factors добавлялись поверх полного
   * baseline). Имена серий держим в формате «{Группа}: {имя}» / «Базовый уровень»,
   * чтобы tooltip-группировка и highlight работали как прежде.
   * @param {{dates: string[], series: any[]}} ds
   */
  function buildCanonicalOption(ds) {
    const dates = ds.dates;
    /** @type {any[]} */
    const allSeries = [];
    let mediaIdx = 0;
    for (const s of ds.series) {
      let color;
      let name = s.name;
      const stack = s.side === 'negative' ? 'negative' : 'positive';
      if (s.role === 'baseline') {
        color = '#3b82f6';
        name = 'Базовый уровень';
      } else if (s.role === 'media') {
        color = CHANNEL_COLORS[(mediaIdx + 1) % CHANNEL_COLORS.length];
        mediaIdx++;
      } else {
        color = FACTOR_COLORS[s.type] ?? '#94a3b8';
        const groupLabel = FACTOR_LABELS[s.type] ?? s.group ?? 'Внешние';
        name = `${groupLabel}: ${s.name}`;
      }
      allSeries.push({
        name,
        type: 'line',
        stack,
        areaStyle: { opacity: s.role === 'media' ? 0.65 : 0.6, color },
        lineStyle: { width: 0 },
        symbol: 'none',
        data: s.data,
        itemStyle: { color },
        emphasis: { focus: 'series' },
      });
    }
    return {
      backgroundColor: 'transparent',
      tooltip: buildTooltipOption(),
      legend: buildLegendOption(activeSeries),
      grid: { left: 16, right: 16, top: 44, bottom: 56, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 25 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#94a3b8', fontSize: 11,
          formatter: (/** @type {number} */ v) => v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v),
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
      },
      dataZoom: [
        {
          type: 'slider', bottom: 4, height: 20,
          borderColor: 'rgba(255,255,255,0.1)',
          backgroundColor: 'rgba(255,255,255,0.04)',
          fillerColor: 'color-mix(in srgb, var(--accent-primary) 15%, transparent)',
          handleStyle: { color: '#3b82f6' },
          textStyle: { color: '#94a3b8', fontSize: 10 },
          start: 0, end: 100,
        },
        { type: 'inside' },
      ],
      series: allSeries,
    };
  }

  const option = $derived.by(() => {
    // Аудит #12: предпочитаем канонический decomposition_series (SSOT с отчётами).
    if (decompositionSeries?.series?.length && decompositionSeries?.dates?.length) {
      return buildCanonicalOption(decompositionSeries);
    }
    if (!timeSeries?.dates?.length) return {};

    const { dates, baseline, channels } = timeSeries;
    const channelNames = Object.keys(channels);
    const allSeries = [];

    // v2.1.0 (пилот 2026-05-16): разделим signedFactors на отдельные полосы,
    // чтобы юзер видел вклад конкурентов / цен / погоды / макро независимо.
    // ВАЖНО: бизнес-семантика типа важнее статистического знака beta.
    // signed_competitor / signed_price / signed_weather / signed_macro -
    // всегда выносим отдельной полосой (красно-оранжевая палитра) даже
    // если модель оценила beta > 0 (например, общий рост рынка с
    // конкурентами). Это даёт пользователю visibility «вот эффект внешнего
    // фактора», а его знак показывает выше/ниже нуля.
    /** @type {Array<{name: string, color: string, label: string, perPeriod: number[], goesNegative: boolean}>} */
    const externalFactors = [];
    let baselineAdjusted = baseline.slice();
    const SIGNED_TYPES = new Set([
      'signed_competitor', 'signed_price', 'signed_weather', 'signed_macro',
    ]);
    if (signedFactors && typeof signedFactors === 'object') {
      for (const [colName, fact] of Object.entries(signedFactors)) {
        if (!fact || !Array.isArray(fact.per_period)) continue;
        const total = Number(fact.value ?? 0);
        const type = String(fact.type ?? 'positive_control');
        const isSigned = SIGNED_TYPES.has(type);
        const isHoliday = type === 'holiday';
        // positive_control (distribution, trade_activity) оставляем внутри
        // baseline - это noise-like эффект, не интересный отдельно.
        if (!isSigned && !isHoliday) continue;
        const color = FACTOR_COLORS[type] ?? '#94a3b8';
        const groupLabel = FACTOR_LABELS[type] ?? 'Внешние';
        const label = `${groupLabel}: ${colName}`;
        // Определяем сторону отображения: если средний contribution
        // отрицательный → ниже нуля; иначе над baseline.
        // Используем mean per_period, не total value (округление до -0.0
        // ломало detection - см. пилот 2026-05-16).
        const mean = fact.per_period.length
          ? fact.per_period.reduce((s, v) => s + Number(v ?? 0), 0) / fact.per_period.length
          : 0;
        const goesNegative = mean < 0;
        if (goesNegative) {
          // Выносим из baseline и показываем ниже нуля.
          baselineAdjusted = baselineAdjusted.map(
            (v, t) => v - Number(fact.per_period[t] ?? 0),
          );
        }
        externalFactors.push({ name: label, color, label: groupLabel, perPeriod: fact.per_period, goesNegative });
      }
    }
    const negativeFactors = externalFactors.filter((f) => f.goesNegative);
    const positiveFactors = externalFactors.filter((f) => !f.goesNegative);

    // Baseline series (bottom) - использует "очищенный" baseline без
    // отрицательных factors. Когда signedFactors не передан - baseline
    // как раньше (backward-compat).
    allSeries.push({
      name: 'Базовый уровень',
      type: 'line',
      stack: 'positive',
      areaStyle: { opacity: 0.6, color: '#3b82f6' },
      lineStyle: { width: 0 },
      symbol: 'none',
      data: baselineAdjusted,
      itemStyle: { color: '#3b82f6' },
      emphasis: { focus: 'series' },
    });

    // Channel series
    channelNames.forEach((ch, idx) => {
      const color = CHANNEL_COLORS[(idx + 1) % CHANNEL_COLORS.length];
      allSeries.push({
        name: ch,
        type: 'line',
        stack: 'positive',
        areaStyle: { opacity: 0.65, color },
        lineStyle: { width: 0 },
        symbol: 'none',
        data: channels[ch],
        itemStyle: { color },
        emphasis: { focus: 'series' },
      });
    });

    // v2.1.0: положительные factors над media (holiday и т.п.)
    positiveFactors.forEach((f) => {
      allSeries.push({
        name: f.name,
        type: 'line',
        stack: 'positive',
        areaStyle: { opacity: 0.6, color: f.color },
        lineStyle: { width: 0 },
        symbol: 'none',
        data: f.perPeriod,
        itemStyle: { color: f.color },
        emphasis: { focus: 'series' },
      });
    });

    // v2.1.0: отрицательные factors ниже нулевой линии.
    // ECharts: для negative stack значения подаются как есть (отрицательные).
    // Отдельный stack name = 'negative' - не смешивается с positive.
    negativeFactors.forEach((f) => {
      allSeries.push({
        name: f.name,
        type: 'line',
        stack: 'negative',
        areaStyle: { opacity: 0.55, color: f.color },
        lineStyle: { width: 0 },
        symbol: 'none',
        // per_period от backend содержит signed значения - отрицательные
        // факторы дают отрицательные числа, ECharts отрисует ниже нуля.
        data: f.perPeriod,
        itemStyle: { color: f.color },
        emphasis: { focus: 'series' },
      });
    });

    return {
      backgroundColor: 'transparent',
      tooltip: buildTooltipOption(),
      legend: buildLegendOption(activeSeries),
      grid: { left: 16, right: 16, top: 44, bottom: 56, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 25 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#94a3b8', fontSize: 11,
          formatter: (/** @type {number} */ v) => v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v),
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
      },
      dataZoom: [
        {
          type: 'slider',
          bottom: 4,
          height: 20,
          borderColor: 'rgba(255,255,255,0.1)',
          backgroundColor: 'rgba(255,255,255,0.04)',
          fillerColor: 'color-mix(in srgb, var(--accent-primary) 15%, transparent)',
          handleStyle: { color: '#3b82f6' },
          textStyle: { color: '#94a3b8', fontSize: 10 },
          start: 0,
          end: 100,
        },
        { type: 'inside' },
      ],
      series: allSeries,
    };
  });
</script>

<EChartBase {option} height="280px" onInit={handleChartInit} />
