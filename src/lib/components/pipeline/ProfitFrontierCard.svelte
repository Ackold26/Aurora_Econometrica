<script>
  /**
   * ProfitFrontierCard - 2026-08-16: «сколько вообще тратить» (профит-фронтир).
   *
   * Отличается от Goal-Seek («сколько нужно под цель») и «От бюджета» («куда
   * вложить заданный бюджет») - отвечает на вопрос, который в продукте до сих
   * пор не звучал: где вообще потолок отдачи по деньгам.
   *
   * Все клиентские формулировки приходят из движка готовыми (`maximum.message`,
   * `period.note`, тексты отказов) - карточка не сочиняет числа заново, только
   * показывает. Три исхода максимума:
   *   - interior_observed - максимум внутри данных → число показываем.
   *   - beyond_observed    - максимум за границей наблюдений → числа НЕТ.
   *   - below_current      - максимум ниже текущего бюджета → число показываем.
   * `maximum.reportable` - единственный флаг, который решает, показывать ли
   * число максимума (contract: FRONTIER_DESIGN_2026-08-16.md).
   *
   * Для денежных KPI (кроме kpi_type='profit') нужна валовая маржа - поля для
   * неё в продукте не было; сделано по образцу ValuePerCountUnitInput.svelte
   * (ручной ввод + подтверждение + персист в project.json, тот же путь, что
   * value_per_count_unit).
   *
   * @component ProfitFrontierCard
   */
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import {
    activeProjectId,
    kpiType,
    kpiKind,
    valuePerCountUnit,
    grossMargin,
    unitCosts,
  } from '$lib/project-state.js';
  import { formatMoney } from '$lib/format-numbers.js';
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark } from '$lib/echarts-setup.js';
  import { TrendingUp, TriangleAlert, Info } from 'lucide-svelte';

  /** @type {'loading' | 'need_margin' | 'economics_blocked' | 'done' | 'error' | 'empty'} */
  let cardState = $state('loading');
  /** @type {any | null} */
  let result = $state(null);
  /** @type {string | null} */
  let message = $state(null);

  /** Поле ручного ввода валовой маржи, % (0-100 для юзера, в запрос уходит доля). */
  let marginPct = $state('');
  let marginBusy = $state(false);

  async function projectDir() {
    const projectId = get(activeProjectId);
    if (!projectId) return null;
    return /** @type {string} */ (await invoke('project_get_dir', { projectId }));
  }

  /** @param {number | null} marginOverride - доля (0..1), если только что введена. */
  async function fetchFrontier(marginOverride = null) {
    cardState = 'loading';
    message = null;
    try {
      const dir = await projectDir();
      if (!dir) { cardState = 'empty'; return; }
      const gm = marginOverride ?? get(grossMargin);
      const res = /** @type {any} */ (await invoke('econ_profit_frontier', {
        projectDir: dir,
        kpiType: get(kpiType),
        valuePerCountUnit: get(valuePerCountUnit),
        grossMargin: gm,
        unitCosts: get(unitCosts),
      }));
      if (res?.status === 'ok') {
        result = res;
        cardState = 'done';
        return;
      }
      if (res?.status === 'economics_required') {
        result = null;
        if (res.reason === 'monetary_margin_missing') {
          cardState = 'need_margin';
        } else {
          cardState = 'economics_blocked';
          message = res.message ?? 'Для этой метрики профит-фронтир недоступен.';
        }
        return;
      }
      // status === 'error' (MODEL_NOT_FOUND, DATA_FILE_MISSING, NO_CURRENT_BUDGET, FORWARD_FAILED)
      result = null;
      cardState = 'error';
      message = res?.message ?? 'Не удалось рассчитать профит-фронтир.';
    } catch (e) {
      const err = /** @type {{message?: string} | string} */ (e);
      result = null;
      cardState = 'error';
      message = typeof err === 'string' ? err : String(err?.message ?? err);
    }
  }

  onMount(() => { fetchFrontier(); });

  /** Подтверждение валовой маржи: персист в project.json (образец
   * ValuePerCountUnitInput → ConfigPanel), затем пересчёт с новым значением. */
  async function confirmMargin() {
    // type="number" в Svelte 5 биндит значение как number, не строку — но jsdom/ручной
    // ввод могут прислать строку с запятой (десятичный разделитель) - обрабатываем оба.
    const pct = typeof marginPct === 'number'
      ? marginPct
      : parseFloat(String(marginPct).replace(',', '.'));
    if (!isFinite(pct) || pct <= 0 || pct > 100) return;
    const fraction = pct / 100;
    marginBusy = true;
    try {
      const projectId = get(activeProjectId);
      if (projectId) {
        await invoke('project_update', {
          projectId,
          updates: { gross_margin: fraction },
        }).catch(() => { /* персист необязателен для расчёта - маржа уйдёт в запрос и так */ });
      }
      grossMargin.set(fraction);
      await fetchFrontier(fraction);
    } finally {
      marginBusy = false;
    }
  }

  // ── Кривая для графика (тот же способ, что ContinuationChart: EChartBase + markLine/markArea) ──
  const chartOption = $derived.by(() => {
    if (!result?.curve?.length) return {};
    /** @type {any[]} */
    const curve = result.curve;
    const observedFrontier = result.observed_frontier;
    const boundaryIdx = observedFrontier?.available ? observedFrontier.index : -1;

    const solidData = boundaryIdx >= 0
      ? curve.slice(0, boundaryIdx + 1).map((p) => [p.budget, p.profit])
      : [];
    const dashedData = boundaryIdx >= 0
      ? curve.slice(boundaryIdx).map((p) => [p.budget, p.profit])
      : curve.map((p) => [p.budget, p.profit]);

    const lastBudget = curve[curve.length - 1].budget;

    /** @type {any[]} */
    const series = [
      {
        name: 'Прибыль - в пределах данных',
        type: 'line',
        data: solidData,
        lineStyle: { color: '#4ade80', width: 2.5 },
        itemStyle: { color: '#4ade80' },
        symbol: 'none',
        z: 10,
        // Штриховка «не подтверждено данными» за границей наблюдений - markArea
        // на невидимой площади под дальней частью кривой (тот же приём, что CI-ribbon
        // в ContinuationChart: area заливка вместо реальной штриховки, которую echarts
        // нативно не поддерживает).
        markArea: (boundaryIdx >= 0 && boundaryIdx < curve.length - 1) ? {
          silent: true,
          itemStyle: { color: 'rgba(148,163,184,0.08)' },
          data: [[{ xAxis: observedFrontier.budget }, { xAxis: lastBudget }]],
        } : undefined,
      },
      {
        name: 'Прибыль - за границей наблюдений (не подтверждено данными)',
        type: 'line',
        data: dashedData,
        lineStyle: { color: '#4ade80', width: 2, type: 'dashed', opacity: 0.55 },
        itemStyle: { color: '#4ade80', opacity: 0.55 },
        symbol: 'none',
        z: 9,
      },
    ];

    // Текущий бюджет - вертикальная метка.
    if (result.current) {
      series.push(/** @type {any} */ ({
        name: '_current_',
        type: 'line',
        data: [],
        showInLegend: false,
        silent: true,
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{ xAxis: result.current.budget }],
          lineStyle: { color: 'rgba(255,255,255,0.4)', type: 'dashed', width: 1 },
          label: {
            show: true,
            position: 'insideEndTop',
            color: 'rgba(255,255,255,0.6)',
            fontSize: 10,
            formatter: 'Текущий бюджет',
          },
        },
      }));
    }

    // Максимум - точка, только когда его честно можно назвать.
    if (result.maximum?.reportable) {
      series.push(/** @type {any} */ ({
        name: '_maximum_',
        type: 'line',
        data: [],
        showInLegend: false,
        silent: true,
        markPoint: {
          symbol: 'pin',
          symbolSize: 34,
          itemStyle: { color: '#c9a449' },
          label: { color: '#0f172a', fontWeight: 700, fontSize: 10, formatter: 'Max' },
          data: [{ coord: [result.maximum.budget, result.maximum.profit] }],
        },
      }));

      // Правдоподобный диапазон положения максимума - вертикальная полоса.
      if (result.posterior_interval?.available) {
        series.push(/** @type {any} */ ({
          name: '_interval_',
          type: 'line',
          data: [],
          showInLegend: false,
          silent: true,
          markArea: {
            silent: true,
            itemStyle: { color: 'rgba(201,164,73,0.14)' },
            data: [[
              { xAxis: result.posterior_interval.low },
              { xAxis: result.posterior_interval.high },
            ]],
          },
        }));
      }
    }

    return {
      backgroundColor: 'transparent',
      grid: { left: '64px', right: '24px', top: '24px', bottom: '48px' },
      legend: {
        top: 0,
        left: 'left',
        icon: 'roundRect',
        itemWidth: 14,
        itemHeight: 4,
        textStyle: { color: '#94a3b8', fontSize: 10 },
        data: ['Прибыль - в пределах данных', 'Прибыль - за границей наблюдений (не подтверждено данными)'],
      },
      xAxis: {
        type: 'value',
        name: 'Бюджет, ₽',
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        axisLabel: { color: '#94a3b8', fontSize: 10, formatter: (/** @type {number} */ v) => formatMoney(v) },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        name: 'Прибыль, ₽',
        nameTextStyle: { color: '#94a3b8', fontSize: 10, align: 'right' },
        axisLabel: { color: '#94a3b8', fontSize: 10, formatter: (/** @type {number} */ v) => formatMoney(v) },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
        axisLine: { show: false },
      },
      tooltip: chartTooltipDark({ trigger: 'axis', numberFormat: (/** @type {number} */ v) => formatMoney(v) }),
      series,
    };
  });
</script>

<div class="frontier-card" data-testid="profit-frontier-card">
  <header class="card-header">
    <span class="icon"><TrendingUp size={18} strokeWidth={1.5} /></span>
    <h3>Сколько вообще тратить</h3>
  </header>
  <p class="lead">
    Прямой расчёт и Goal-Seek отвечают «куда вложить» и «сколько нужно под цель». Этот
    расчёт отвечает на третий вопрос - есть ли вообще смысл наращивать бюджет дальше, и
    если да, то где потолок отдачи.
  </p>

  {#if cardState === 'loading'}
    <div class="state-loading">Считаем кривую прибыли...</div>
  {:else if cardState === 'empty'}
    <div class="state-loading">Откройте проект, чтобы увидеть профит-фронтир.</div>
  {:else if cardState === 'need_margin'}
    <section class="margin-input" data-testid="margin-input">
      <p class="margin-lead">
        Метрика проекта денежная (выручка/продажи в рублях) - чтобы посчитать прибыль, а
        не оборот, нужна валовая маржа: доля прибыли в рубле продаж. Без неё «оптимум по
        обороту» был бы неправдой - оборот растёт с бюджетом всегда.
      </p>
      <div class="margin-row">
        <label for="gross-margin-field" class="field-label">Валовая маржа, %</label>
        <input
          id="gross-margin-field"
          type="number"
          step="0.1"
          min="0"
          max="100"
          placeholder="например, 30"
          bind:value={marginPct}
        />
        <button
          type="button"
          class="btn-primary"
          disabled={marginBusy || !marginPct}
          onclick={confirmMargin}
        >
          {marginBusy ? 'Считаем...' : 'Подтвердить →'}
        </button>
      </div>
      <p class="hint">Например, 30 - если из каждого рубля продаж 30 копеек остаётся прибылью после себестоимости.</p>
    </section>
  {:else if cardState === 'economics_blocked'}
    <div class="state-blocked">
      <span class="note-icon"><Info size={16} strokeWidth={1.5} /></span>
      <p>{message}</p>
    </div>
  {:else if cardState === 'error'}
    <div class="state-error" role="alert">
      <span class="note-icon"><TriangleAlert size={16} strokeWidth={1.5} /></span>
      <p>{message}</p>
    </div>
  {:else if cardState === 'done' && result}
    <EChartBase option={chartOption} height="280px" />

    <section class="outcome" class:outcome-ok={result.maximum.outcome === 'interior_observed'}
      class:outcome-info={result.maximum.outcome === 'beyond_observed' || result.maximum.outcome === 'at_grid_ceiling'}
      class:outcome-warn={result.maximum.outcome === 'below_current'}
      data-testid="frontier-outcome">
      <p class="outcome-message">{result.maximum.message}</p>
      {#if result.maximum.reportable}
        <div class="outcome-figure" data-testid="frontier-maximum-budget">
          <span class="figure-label">Максимум прибыли при бюджете:</span>
          <!-- 2026-08-16 (F-17, fix-frontier): budget_display - округлённое до
               разрешения сетки число для экрана, budget (точное) не печатаем -
               псевдоточность иначе вернулась бы через карточку. -->
          <span class="figure-value">{formatMoney(result.maximum.budget_display, { compact: false })}</span>
        </div>
      {/if}
      {#if result.maximum.at_observed_frontier}
        <p class="frontier-flag" data-testid="frontier-at-boundary-flag">
          <TriangleAlert size={13} strokeWidth={1.5} style="vertical-align: -0.15em" />
          Максимум пришёлся на саму границу наблюдений.
        </p>
      {/if}
    </section>

    <section class="interval" data-testid="posterior-interval">
      {#if result.posterior_interval?.available}
        <p>
          <!-- 2026-08-16 (F-12, fix-frontier): интервал, усечённый расчётной сеткой
               (is_probabilistic=false), - не вероятностное утверждение, подпись
               без «90%». -->
          {#if result.posterior_interval.is_probabilistic === false}
            Диапазон положения максимума (ограничен расчётной сеткой):
          {:else}
            Правдоподобный диапазон положения максимума (90%):
          {/if}
          <strong>{formatMoney(result.posterior_interval.low, { compact: false })} – {formatMoney(result.posterior_interval.high, { compact: false })}</strong>
        </p>
        {#if result.posterior_interval.caveat}
          <p class="interval-caveat" data-testid="posterior-interval-caveat">{result.posterior_interval.caveat}</p>
        {/if}
      {:else}
        <p class="interval-unavailable">{result.posterior_interval?.message ?? 'Интервал на положение максимума недоступен.'}</p>
      {/if}
    </section>

    <section class="current-row">
      <span>Текущий бюджет: <strong>{formatMoney(result.current.budget, { compact: false })}</strong></span>
      <span>Прибыль при текущем бюджете: <strong>{formatMoney(result.current.profit, { compact: false })}</strong></span>
    </section>

    <footer class="period-note" data-testid="frontier-period">{result.period?.note}</footer>
    {#if result.allocation_note}
      <p class="allocation-note">{result.allocation_note}</p>
    {/if}
  {/if}
</div>

<style>
  .frontier-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-card, 12px);
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .card-header { display: flex; align-items: center; gap: 10px; color: var(--text-primary); }
  .card-header h3 { margin: 0; font-size: 15px; font-weight: 700; }
  .lead { font-size: 12px; color: var(--text-secondary); margin: 0; line-height: 1.5; }

  .state-loading { font-size: 12px; color: var(--text-muted); padding: 20px 0; text-align: center; }

  .margin-input { display: flex; flex-direction: column; gap: 10px; }
  .margin-lead { font-size: 12px; color: var(--text-secondary); margin: 0; line-height: 1.5; }
  .margin-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .field-label { font-size: 12px; font-weight: 600; color: var(--text-primary); }
  .margin-row input {
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 13px;
    width: 100px;
    font: inherit;
  }
  .hint { font-size: 11px; color: var(--text-muted); margin: 0; line-height: 1.5; }
  .btn-primary {
    padding: 8px 16px;
    background: var(--accent-primary);
    color: #fff;
    border: 1px solid var(--accent-primary);
    border-radius: var(--radius-btn, 8px);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    font: inherit;
  }
  .btn-primary:disabled { background: var(--bg-surface-quiet); color: var(--text-muted); border-color: var(--border); cursor: not-allowed; }

  .state-blocked, .state-error {
    display: flex;
    gap: 10px;
    padding: 12px 14px;
    border-radius: var(--radius-sm, 8px);
    font-size: 12px;
    line-height: 1.5;
  }
  .state-blocked { background: color-mix(in srgb, var(--accent-primary) 6%, transparent); color: var(--text-secondary); }
  .state-error { background: color-mix(in srgb, var(--danger, #f87171) 10%, transparent); color: var(--danger, #f87171); }
  .state-blocked p, .state-error p { margin: 0; }

  .outcome { padding: 12px 14px; border-radius: var(--radius-sm, 8px); background: var(--bg-surface-quiet); display: flex; flex-direction: column; gap: 6px; }
  .outcome-ok { border: 1px solid color-mix(in srgb, var(--success, #4ade80) 30%, transparent); }
  .outcome-info { border: 1px solid color-mix(in srgb, var(--accent-primary) 25%, transparent); }
  .outcome-warn { border: 1px solid color-mix(in srgb, var(--warning, #fbbf24) 35%, transparent); }
  .outcome-message { margin: 0; font-size: 13px; line-height: 1.55; color: var(--text-primary); }
  .outcome-figure { display: flex; gap: 8px; align-items: baseline; }
  .figure-label { font-size: 11px; color: var(--text-muted); }
  .figure-value { font-size: 18px; font-weight: 700; color: var(--accent-primary); }
  .frontier-flag { margin: 0; font-size: 11px; color: var(--warning, #fbbf24); }

  .interval { font-size: 12px; color: var(--text-secondary); }
  .interval p { margin: 0; line-height: 1.5; }
  .interval strong { color: var(--text-primary); }
  .interval-unavailable { color: var(--text-muted); }
  .interval-caveat { margin: 4px 0 0; font-size: 11px; color: var(--warning, #fbbf24); line-height: 1.5; }

  .current-row { display: flex; gap: 18px; flex-wrap: wrap; font-size: 12px; color: var(--text-secondary); }
  .current-row strong { color: var(--text-primary); }

  .period-note { font-size: 11px; color: var(--text-muted); line-height: 1.5; }
  .allocation-note { font-size: 11px; color: var(--text-muted); line-height: 1.5; margin: 0; }
</style>
