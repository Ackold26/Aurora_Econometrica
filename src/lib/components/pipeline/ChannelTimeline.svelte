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
  import {
    TOP_GROUP_ORDER, TOP_GROUP_DISPLAY, fallbackTopGroup,
    presentTopGroups, planViewSeries, seasonalityPctOfBase, symmetricPctBound,
  } from '$lib/decomposition-view.js';

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
   *       type: string, group: string, top_group?: string,
   *       side: 'positive'|'negative', data: number[], pct_of_base?: number[] }>,
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
    category:          '#10b981', // emerald-500 — спрос категории/рынка (Фаза Б)
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
    category:          'Категория',
    positive_control:  'Внешние факторы',
  };

  // Т3 (2026-07-04): tooltip группирует по 4 ВЕРХНИМ группам из SSOT (поле
  // top_group в decomposition_series), а не по хрупкому префиксу имени серии
  // (раньше «Сезонность:» падала в «Медиа» — фикс cea50a6). seriesTopGroup
  // заполняется при построении option (buildCanonicalOption); formatter читает.
  // Константы порядка/подписей и fallback вынесены в decomposition-view.js
  // (SSOT + vitest-покрытие тождества свёртки — svelte-check контракты не ловит).
  /** @type {Record<string, string>} name серии → top_group (БАЗА/МЕДИА/ВНЕШНИЕ ФАКТОРЫ/КОНКУРЕНТЫ) */
  let seriesTopGroup = {};

  // Т3.1 drill-down: раскрытые верхние группы (Set top_group). По умолчанию всё
  // свёрнуто — 4 агрегированные полосы. Клик по chip/полосе разворачивает группу
  // в под-компоненты. Тождество (свёрнутая Σ == развёрнутая) держит planViewSeries.
  /** @type {Set<string>} */
  let expanded = $state(new Set());
  // Т3.2: показывать сезонную кривую ±% к базе (правая ось) — ключевая подача
  // Антона «февраль +60% к базе» (мультипликативно, хотя модель аддитивна).
  let showSeasonalityPct = $state(true);

  // Имя серии сезонной %-кривой — маркер для tooltip/highlight (семантика %, не ₽).
  const SEASONALITY_PCT_NAME = 'Сезонность, % к базе';

  // Цвета агрегированных полос верхнего уровня (свёрнутый вид).
  /** @type {Record<string, string>} */
  const GROUP_COLORS = {
    'БАЗА': '#3b82f6',             // blue (как базовая линия)
    'МЕДИА': '#22c55e',           // green — суммарный медиа-вклад
    'ВНЕШНИЕ ФАКТОРЫ': '#f59e0b', // amber
    'КОНКУРЕНТЫ': '#dc2626',      // red (как конкуренты)
  };

  /** Toggle раскрытия верхней группы. @param {string} g */
  function toggleGroup(g) {
    const next = new Set(expanded);
    if (next.has(g)) next.delete(g); else next.add(g);
    expanded = next; // reassignment → Svelte 5 reactivity
  }

  // Метаданные для chips-панели (какие группы есть, есть ли сезонность) —
  // только для canonical-пути; legacy signedFactors без drill-down.
  const viewModel = $derived.by(() => {
    const ds = decompositionSeries;
    if (ds?.series?.length && ds?.dates?.length) {
      return {
        canonical: true,
        groups: presentTopGroups(ds),
        hasSeasonality: seasonalityPctOfBase(ds) != null,
      };
    }
    return { canonical: false, groups: /** @type {string[]} */ ([]), hasSeasonality: false };
  });

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
    // Т3.1: клик по полосе разворачивает/сворачивает её верхнюю группу (drill-down
    // помимо chips). Клик по под-компоненту раскрытой группы — сворачивает обратно.
    // Сезонная %-кривая помечена silent → её клики сюда не приходят.
    chart.on('click', (/** @type {any} */ params) => {
      const tg = seriesTopGroup[params?.seriesName];
      if (tg && TOP_GROUP_ORDER.includes(tg)) toggleGroup(tg);
    });
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
        // Т3.2: сезонная %-кривая живёт на второй оси (проценты) — не часть
        // стека, пропускаем в Y-сопоставлении слоёв.
        if (s.name === SEASONALITY_PCT_NAME) continue;
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
        // Т3.2: сезонная %-кривая (вторая ось, семантика %) — отделяем от стек-полос;
        // в total/группы/подсветку не входит, показывается своей строкой.
        const pctPoint = params.find(p => p.seriesName === SEASONALITY_PCT_NAME);
        const stackParams = params.filter(p => p.seriesName !== SEASONALITY_PCT_NAME);

        const total = stackParams.reduce((s, p) => s + (p.value ?? 0), 0);
        const fmt = (/** @type {number} */ v) =>
          new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(Math.round(v));

        // Prefix regex для очистки seriesName в строках групп (отображение под-компонента).
        const PREFIX_RE = /^(Конкуренты|Праздники|Сезонность|Внешние|Цена|Погода|Макро-факторы|Категория):\s*/;

        // Т3-шаг (2026-07-04): группируем по 4 ВЕРХНИМ группам из SSOT (top_group),
        // а не по префиксу имени. Праздники и Сезонность → под БАЗА (решение Антона);
        // Цена/Погода/Макро/Категория/Дистрибуция → ВНЕШНИЕ ФАКТОРЫ. seriesTopGroup
        // заполнен при построении option; для legacy (нет поля) — fallback по имени.
        // В свёрнутом виде группа = одна строка-агрегат («База»), в развёрнутом — под-компоненты.
        /** @type {Map<string, Array<{p: any, cleanName: string}>>} */
        const groups = new Map(TOP_GROUP_ORDER.map(g => [g, []]));

        stackParams.forEach(p => {
          const name = p.seriesName ?? '';
          const tg = seriesTopGroup[name] ?? fallbackTopGroup(name);
          const cleanName = name.replace(PREFIX_RE, '');
          (groups.get(tg) ?? groups.get('ВНЕШНИЕ ФАКТОРЫ'))?.push({ p, cleanName });
        });

        // Заголовок с датой периода
        let html = `<div style="color:#fff;font-weight:600;margin-bottom:6px;">${escapeHtml(params[0]?.axisValue)}</div>`;

        // Блок активного слоя (highlight) — сохраняем поведение из v2.0
        const active = activeSeries ? stackParams.find(p => p.seriesName === activeSeries) : null;
        if (active) {
          const aPct = total > 0 ? ((active.value / total) * 100).toFixed(1) : '0.0';
          html += `<div style="display:flex;align-items:center;gap:8px;background:linear-gradient(90deg,${active.color}33,transparent);border-left:3px solid ${active.color};padding:6px 8px;margin:0 -6px 6px -6px;border-radius:3px;">`
            + `<span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:${active.color};box-shadow:0 0 8px ${active.color};"></span>`
            + `<div style="display:flex;flex-direction:column;line-height:1.25;">`
            + `<span style="color:#fff;font-weight:700;font-size:13px;">${escapeHtml(active.seriesName)}</span>`
            + `<span style="color:rgba(255,255,255,0.85);font-size:12px;"><b>${fmt(active.value)}</b> &middot; ${aPct}% от периода</span>`
            + `</div></div>`;
        }

        // Группированные строки (порядок 4 верхних групп)
        TOP_GROUP_ORDER.forEach(groupKey => {
          const items = groups.get(groupKey);
          if (!items || items.length === 0) return;

          const subtotal = items.reduce((s, { p }) => s + (p.value ?? 0), 0);
          const pct = total > 0 ? ((subtotal / total) * 100).toFixed(1) : '0.0';

          // Заголовок группы (человекочитаемый: «Внешние факторы», не «ВНЕШНИЕ ФАКТОРЫ»)
          const groupLabel = TOP_GROUP_DISPLAY[groupKey] ?? groupKey;
          html += `<div style="font-weight:600;margin-top:6px;color:#94a3b8;font-size:11px">${groupLabel} · ${fmt(subtotal)} (${pct}%)</div>`;

          // Аудит Т3 (А-1): свёрнутая группа приходит ОДНОЙ агрегат-серией с
          // именем == groupLabel; заголовок уже несёт её сумму и % — дочерняя
          // строка дублировала бы то же число («База · 990» + «База 990»).
          const isCollapsedAggregate =
            items.length === 1 && (items[0].p.seriesName ?? '') === groupLabel;
          if (isCollapsedAggregate) return;

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

        // Итог (по стек-полосам)
        html += `<div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);font-weight:600;display:flex;justify-content:space-between">`
          + `<span>Итого</span><span>${fmt(total)}</span>`
          + `</div>`;

        // Т3.2: сезонность как множитель к базе — отдельной строкой (не в Итого).
        if (pctPoint && Number.isFinite(Number(pctPoint.value))) {
          const pv = Number(pctPoint.value);
          html += `<div style="margin-top:4px;display:flex;justify-content:space-between;gap:10px;color:#8b5cf6;font-size:12px">`
            + `<span>&#9679; Сезонность к базе</span><span style="font-weight:600">${pv > 0 ? '+' : ''}${pv.toFixed(1)}%</span>`
            + `</div>`;
        }

        return html;
      },
    };
  }

  /**
   * Presentation одного под-компонента (member) → цвет + отображаемое имя.
   * Воспроизводит прежнюю логику: baseline blue «Базовый уровень», media из
   * CHANNEL_COLORS по порядку, factor из FACTOR_COLORS с префиксом «{Группа}: имя».
   * @param {any} p PlanSeries kind='member'
   * @param {{ i: number }} mediaIdx мутируемый счётчик медиа (порядок цветов)
   */
  function memberDisplay(p, mediaIdx) {
    if (p.role === 'baseline') return { color: '#3b82f6', name: 'Базовый уровень' };
    if (p.role === 'media') {
      const color = CHANNEL_COLORS[(mediaIdx.i + 1) % CHANNEL_COLORS.length];
      mediaIdx.i++;
      return { color, name: p.name };
    }
    const color = FACTOR_COLORS[p.type] ?? '#94a3b8';
    const groupLabel = FACTOR_LABELS[p.type] ?? 'Внешние';
    // Аудит Т3 (А-3): агрегированный фактор SSOT может называться как своя
    // группа (Фурье → ключ «Сезонность») — префикс дал бы дубль
    // «Сезонность: Сезонность» в легенде/highlight.
    return { color, name: p.name === groupLabel ? groupLabel : `${groupLabel}: ${p.name}` };
  }

  /** Правая ось для сезонной %-кривой (Т3.2) — violet, симметрична вокруг 0
   *  (аудит А-4: min=-bound/max=+bound центрируют нулевую линию — волна ±%
   *  читается как отклонение от базы, а не смещённый диапазон по данным).
   *  @param {number} bound симметричная граница (symmetricPctBound) */
  function seasonalityAxis(bound) {
    return {
      type: 'value',
      position: 'right',
      name: '% к базе',
      nameTextStyle: { color: '#8b5cf6', fontSize: 10, align: 'right' },
      min: -bound,
      max: bound,
      axisLabel: {
        color: '#8b5cf6', fontSize: 10,
        formatter: (/** @type {number} */ v) => `${v > 0 ? '+' : ''}${v}%`,
      },
      axisLine: { show: true, lineStyle: { color: 'rgba(139,92,246,0.35)' } },
      splitLine: { show: false },
    };
  }

  /** Аудит Т3 (А-2): текущее окно dataZoom (start/end, %) — сохраняем при
   *  перестройке option. Toggle drill-down/тумблер пересоздают option, а
   *  EChartBase применяет его с notMerge → без этого зум юзера сбрасывался бы
   *  на каждый клик по chip/полосе (регрессия Т3 — до drill-down option менялся
   *  только при смене данных). */
  function currentZoomWindow() {
    try {
      if (chartRef && !chartRef.isDisposed?.()) {
        const dz = chartRef.getOption?.()?.dataZoom;
        const s = Array.isArray(dz) ? dz[0] : null;
        if (s && Number.isFinite(s.start) && Number.isFinite(s.end)) {
          return { start: s.start, end: s.end };
        }
      }
    } catch { /* chart в переходном состоянии — дефолт */ }
    return { start: 0, end: 100 };
  }

  /**
   * Аудит #12 (2026-06-07, INV-50) + Т3 (2026-07-04): option из канонического
   * decomposition_series (SSOT с отчётами) через planViewSeries — свёрнутый вид
   * 4 полос (drill-down по expanded) + сезонная %-кривая на второй оси. baseline
   * здесь уже уменьшен на вынесенные факторы → нет double-count. Имена держим в
   * формате «{Группа}: {имя}» / «Базовый уровень» / человекочитаемое имя группы,
   * чтобы tooltip-группировка и highlight работали.
   * @param {{dates: string[], series: any[]}} ds
   */
  function buildCanonicalOption(ds) {
    const dates = ds.dates;
    const { plan } = planViewSeries(ds, expanded);
    /** @type {any[]} */
    const allSeries = [];
    seriesTopGroup = {}; // сброс перед заполнением из текущего SSOT
    const mediaIdx = { i: 0 };

    for (const p of plan) {
      let color;
      let name;
      if (p.kind === 'group') {
        // Свёрнутая агрегированная полоса верхнего уровня.
        color = GROUP_COLORS[p.topGroup] ?? '#94a3b8';
        name = p.name; // человекочитаемое «База»/«Медиа»/«Внешние факторы»/«Конкуренты»
      } else {
        const d = memberDisplay(p, mediaIdx);
        color = d.color;
        name = d.name;
      }
      const stack = p.side === 'negative' ? 'negative' : 'positive';
      seriesTopGroup[name] = p.topGroup;
      allSeries.push({
        name,
        type: 'line',
        stack,
        areaStyle: { opacity: p.kind === 'group' ? 0.55 : (p.role === 'media' ? 0.65 : 0.6), color },
        lineStyle: { width: 0 },
        symbol: 'none',
        data: p.data,
        itemStyle: { color },
        emphasis: { focus: 'series' },
      });
    }

    // Т3.2: сезонная кривая ±% к базе — поверх стека, вторая ось, независимо от
    // свёртки (pct_of_base из SSOT). Исключена из tooltip-total/групп/highlight
    // как семантически иная (проценты, не ₽) — см. buildTooltipOption / highlight.
    const pct = showSeasonalityPct ? seasonalityPctOfBase(ds) : null;
    const hasPct = Array.isArray(pct) && pct.length > 0;
    if (hasPct) {
      allSeries.push({
        name: SEASONALITY_PCT_NAME,
        type: 'line',
        yAxisIndex: 1,
        data: pct,
        symbol: 'circle',
        symbolSize: 4,
        smooth: true,
        lineStyle: { width: 2, color: '#8b5cf6', type: 'dashed' },
        itemStyle: { color: '#8b5cf6' },
        z: 10,
        emphasis: { disabled: true },
        silent: true, // не участвует в highlight/click-drill
      });
    }

    const mainYAxis = {
      type: 'value',
      axisLabel: {
        color: '#94a3b8', fontSize: 11,
        formatter: (/** @type {number} */ v) => v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v),
      },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
    };
    const zoom = currentZoomWindow();

    return {
      backgroundColor: 'transparent',
      tooltip: buildTooltipOption(),
      legend: buildLegendOption(activeSeries),
      grid: { left: 16, right: hasPct ? 52 : 16, top: 44, bottom: 56, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 25 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
        axisTick: { show: false },
      },
      yAxis: hasPct ? [mainYAxis, seasonalityAxis(symmetricPctBound(pct))] : mainYAxis,
      dataZoom: [
        {
          type: 'slider', bottom: 4, height: 20,
          borderColor: 'rgba(255,255,255,0.1)',
          backgroundColor: 'rgba(255,255,255,0.04)',
          fillerColor: 'color-mix(in srgb, var(--accent-primary) 15%, transparent)',
          handleStyle: { color: '#3b82f6' },
          textStyle: { color: '#94a3b8', fontSize: 10 },
          // А-2: сохраняем окно зума юзера через перестройки option (drill-toggle)
          start: zoom.start, end: zoom.end,
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

    // Legacy-путь (signedFactors, старый формат без top_group): tooltip-группировка
    // работает через fallbackTopGroup по префиксу имени серии («Группа: имя»).
    seriesTopGroup = {};

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

<div class="timeline-wrap">
  <!-- Т3.1: chips-раскрытие 4 верхних групп + тумблер сезонной %-кривой.
       Только для canonical decomposition_series; legacy signedFactors без drill-down. -->
  {#if viewModel.canonical && (viewModel.groups.length > 1 || viewModel.hasSeasonality)}
    <div class="drill-chips" role="group" aria-label="Детализация декомпозиции">
      <span class="drill-hint">Детализация:</span>
      {#each viewModel.groups as g (g)}
        <button
          type="button"
          class="chip"
          class:active={expanded.has(g)}
          data-drill={g}
          aria-pressed={expanded.has(g)}
          onclick={() => toggleGroup(g)}
          title={expanded.has(g) ? `Свернуть под-компоненты: ${TOP_GROUP_DISPLAY[g] ?? g}` : `Развернуть под-компоненты: ${TOP_GROUP_DISPLAY[g] ?? g}`}
        >
          {TOP_GROUP_DISPLAY[g] ?? g}
          <span class="chip-caret" aria-hidden="true">{expanded.has(g) ? '▾' : '▸'}</span>
        </button>
      {/each}
      {#if viewModel.hasSeasonality}
        <button
          type="button"
          class="chip chip-season"
          class:active={showSeasonalityPct}
          data-drill="seasonality-pct"
          aria-pressed={showSeasonalityPct}
          onclick={() => { showSeasonalityPct = !showSeasonalityPct; }}
          title="Сезонная кривая ± % к базе (правая ось): «февраль +60% к базе»"
        >
          <span class="chip-dot" aria-hidden="true"></span>
          Сезонность, %
        </button>
      {/if}
    </div>
  {/if}
  <EChartBase {option} height="280px" onInit={handleChartInit} />
</div>

<style>
  .timeline-wrap {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .drill-chips {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .drill-hint {
    font-size: 11px;
    color: var(--text-muted, #64748b);
    margin-right: 2px;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 500;
    color: var(--text-secondary, #94a3b8);
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.1));
    border-radius: 999px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s, color 0.15s;
  }
  .chip:hover {
    color: var(--text-primary, #e2e8f0);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 45%, transparent);
  }
  .chip.active {
    color: var(--text-primary, #e2e8f0);
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 14%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 55%, transparent);
  }
  .chip-caret {
    font-size: 9px;
    opacity: 0.75;
  }
  .chip-season.active {
    background: color-mix(in srgb, #8b5cf6 16%, transparent);
    border-color: color-mix(in srgb, #8b5cf6 55%, transparent);
    color: #c4b5fd;
  }
  .chip-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #8b5cf6;
    box-shadow: 0 0 6px rgba(139, 92, 246, 0.6);
  }
</style>
