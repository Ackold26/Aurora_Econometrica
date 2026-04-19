<script>
  /**
   * Budget optimizer UI: per-channel sliders + KPI prediction + lock redistribution.
   * Client-side Hill computation (<0.1ms updates).
   * @component BudgetOptimizer
   */
  import { predictKPI } from '$lib/hill.js';
  import { CHANNEL_COLORS } from '$lib/hill.js';

  /**
   * @type {{
   *   channels: string[],
   *   scaledParams: Record<string, {alpha: number, gammaScaled: number, beta: number}>,
   *   channelBudgets: Record<string, number>,
   *   initialSpend: Record<string, number>,
   *   currentKPI: number,
   *   normalization?: {y_mean: number, y_std: number} | null,
   *   locked: boolean,
   *   onBudgetChange: (ch: string, val: number) => void,
   *   onOptimize: () => void,
   *   onReset: () => void,
   *   optimizing?: boolean,
   *   optimalBudgets?: Record<string, number> | null,
   * }}
   */
  let {
    channels,
    scaledParams,
    channelBudgets,
    initialSpend,
    currentKPI,
    normalization = null,
    locked,
    onBudgetChange,
    onOptimize,
    onReset,
    optimizing = false,
    optimalBudgets = null,
  } = $props();

  // Predicted KPI from current sliders — денормализован в исходные единицы.
  const predictedKPI = $derived(predictKPI(channelBudgets, scaledParams, normalization));
  const liftPct = $derived(currentKPI > 0 ? ((predictedKPI - currentKPI) / currentKPI * 100) : 0);
  const totalBudget = $derived(Object.values(channelBudgets).reduce((s, v) => s + v, 0));

  // Базовый текущий бюджет (initial spend) — для расчёта delta общего бюджета.
  const initialTotal = $derived(Object.values(initialSpend).reduce((s, /** @type {number} */ v) => s + v, 0));
  const budgetDeltaPct = $derived(initialTotal > 0 ? ((totalBudget - initialTotal) / initialTotal * 100) : 0);
  const budgetDeltaAbs = $derived(totalBudget - initialTotal);

  /**
   * Handle slider input — redistribute if locked.
   * @param {string} ch
   * @param {number} newValue
   */
  function handleSlider(ch, newValue) {
    if (locked) {
      const delta = newValue - channelBudgets[ch];
      const others = channels.filter(c => c !== ch);
      const othersTotal = others.reduce((s, c) => s + channelBudgets[c], 0);
      const updated = { ...channelBudgets };
      updated[ch] = newValue;
      for (const other of others) {
        const share = channelBudgets[other] / Math.max(othersTotal, 1);
        updated[other] = Math.max(0, channelBudgets[other] - delta * share);
      }
      for (const [c, v] of Object.entries(updated)) onBudgetChange(c, v);
    } else {
      onBudgetChange(ch, newValue);
    }
  }

  /**
   * Format number for display.
   * @param {number} v
   * @returns {string}
   */
  function fmt(v) {
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
    return Math.round(v).toString();
  }
</script>

<div class="budget-optimizer">
  <!-- Total budget display -->
  <div class="total-row">
    <span class="total-label">Общий бюджет</span>
    <span class="total-value">{fmt(totalBudget)} ₽</span>
    {#if Math.abs(budgetDeltaPct) >= 0.5}
      <span class="budget-delta" class:positive={budgetDeltaPct > 0} class:negative={budgetDeltaPct < 0}
            title="Изменение относительно текущего бюджета {fmt(initialTotal)} ₽">
        {budgetDeltaPct > 0 ? '+' : ''}{budgetDeltaPct.toFixed(0)}%
        <span class="budget-delta-abs">({budgetDeltaAbs > 0 ? '+' : ''}{fmt(Math.abs(budgetDeltaAbs))} ₽)</span>
      </span>
    {/if}
    <span class="lock-badge" class:locked title={locked ? 'Бюджет заблокирован — перераспределение' : 'Свободное изменение'}>
      {locked ? '🔒' : '🔓'}
    </span>
  </div>

  <!-- Channel sliders -->
  <div class="sliders">
    {#each channels as ch, idx}
      {@const cur = channelBudgets[ch] ?? 0}
      {@const opt = optimalBudgets?.[ch]}
      {@const delta = opt != null ? ((opt - cur) / Math.max(cur, 1) * 100) : null}
      {@const maxVal = (initialSpend[ch] ?? cur) * 2.5 || 1}
      {@const color = CHANNEL_COLORS[idx % CHANNEL_COLORS.length]}

      <div class="slider-row">
        <div class="ch-label" style="--color:{color}">{ch}</div>
        <input
          type="range"
          class="slider"
          min={0}
          max={maxVal}
          step={Math.max(maxVal / 200, 1)}
          value={cur}
          oninput={(e) => handleSlider(ch, parseFloat(/** @type {HTMLInputElement} */ (e.target).value))}
          style="--accent:{color}"
        />
        <span class="ch-value">{fmt(cur)} ₽</span>
        {#if delta != null}
          <span class="delta-badge" class:positive={delta > 0} class:negative={delta < 0}>
            {delta > 0 ? '+' : ''}{delta.toFixed(0)}%
          </span>
        {/if}
      </div>
    {/each}
  </div>

  <!-- KPI prediction card -->
  <div class="kpi-card">
    <div class="kpi-row">
      <span class="kpi-label">Прогноз KPI</span>
      <span class="kpi-value">{predictedKPI.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}</span>
    </div>
    {#if liftPct !== 0}
      <div class="lift-row">
        <span class="lift" class:positive={liftPct > 0} class:negative={liftPct < 0}>
          {liftPct > 0 ? '+' : ''}{liftPct.toFixed(1)}% к текущему
        </span>
      </div>
    {/if}
  </div>

  <!-- Action buttons -->
  <div class="actions">
    <button class="btn-optimize" onclick={onOptimize} disabled={optimizing}>
      {optimizing ? 'Оптимизирую...' : 'Оптимизировать'}
    </button>
    <button class="btn-reset" onclick={onReset}>Сбросить</button>
  </div>
</div>

<style>
  .budget-optimizer {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .total-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: rgba(255,255,255,0.04);
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.08);
  }
  .total-label { font-size: 12px; color: var(--text-secondary, #94a3b8); flex: 1; }
  .total-value { font-size: 14px; font-weight: 600; color: var(--text-primary, #e2e8f0); font-family: monospace; font-variant-numeric: tabular-nums; }
  .budget-delta {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    font-family: monospace;
    cursor: help;
  }
  .budget-delta.positive {
    background: color-mix(in srgb, var(--success) 14%, transparent);
    color: var(--success);
  }
  .budget-delta.negative {
    background: color-mix(in srgb, var(--danger) 14%, transparent);
    color: var(--danger);
  }
  .budget-delta-abs { font-size: 10px; opacity: 0.8; font-weight: 500; }
  .lock-badge { font-size: 14px; cursor: default; }

  .sliders {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .slider-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .ch-label {
    min-width: 100px;
    max-width: 100px;
    font-size: 11px;
    color: var(--color, #e2e8f0);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
  }

  .slider {
    flex: 1;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: rgba(255,255,255,0.1);
    border-radius: 2px;
    outline: none;
    cursor: pointer;
  }

  .slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--accent, #3b82f6);
    cursor: pointer;
    transition: transform 0.1s;
  }
  .slider::-webkit-slider-thumb:active { transform: scale(1.2); }

  .ch-value {
    min-width: 64px;
    text-align: right;
    font-size: 11px;
    font-family: monospace;
    color: var(--text-secondary, #94a3b8);
  }

  .delta-badge {
    min-width: 44px;
    text-align: center;
    font-size: 10px;
    font-family: monospace;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: 600;
  }
  .delta-badge.positive { background: color-mix(in srgb, var(--success) 12%, transparent); color: #22c55e; }
  .delta-badge.negative { background: color-mix(in srgb, var(--danger) 12%, transparent); color: #ef4444; }

  .kpi-card {
    padding: 12px 14px;
    background: color-mix(in srgb, var(--accent-primary) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-radius: 10px;
  }
  .kpi-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .kpi-label { font-size: 12px; color: var(--text-secondary, #94a3b8); }
  .kpi-value { font-size: 18px; font-weight: 700; color: var(--text-primary, #e2e8f0); font-family: monospace; }
  .lift-row { margin-top: 4px; }
  .lift { font-size: 12px; font-weight: 600; }
  .lift.positive { color: #22c55e; }
  .lift.negative { color: #ef4444; }

  .actions {
    display: flex;
    gap: 8px;
  }

  .btn-optimize {
    flex: 1;
    padding: 9px 16px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 8px;
    color: white;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-optimize:hover:not(:disabled) { opacity: 0.85; }
  .btn-optimize:disabled { opacity: 0.5; cursor: not-allowed; }

  .btn-reset {
    padding: 9px 16px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .btn-reset:hover { border-color: rgba(255,255,255,0.25); color: var(--text-primary, #e2e8f0); }
</style>
