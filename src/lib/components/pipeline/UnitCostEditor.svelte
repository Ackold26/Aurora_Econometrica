<script>
  /**
   * UnitCostEditor — Phase 2.1 (R3) partial extract.
   *
   * Two-mode input controller для physical channel в ROI режиме:
   * - Mode A (budget): общий ₽-бюджет за период → derive unit_cost = budget / Σ(units)
   * - Mode B (unit): прямой ввод цены 1 ед. + годовой % роста стоимости
   *
   * State lives в shared stores (unitCosts / unitCostInflation /
   * unitCostInputMode / budgetInputs). Component = presentational + handlers.
   *
   * Decoupled from AppliedModeSummary parent — receives channel info as
   * props, parent decides which channels need editor (typically physical
   * channels в ROI mode).
   *
   * Future reuse: Launch Planner / Trade & Pricing когда они migrate к
   * Manager mode pattern (cross-product через aurora-platform-core).
   */
  import {
    unitCosts, unitCostInflation, unitCostInputMode, budgetInputs,
  } from '$lib/project-state.js';
  import { unitLabelFor as unitLabel } from '$lib/services/classifier-patterns.js';
  // H-09 (Phase 4.1 wire): industry-aware unit_cost подсказки.
  import { suggestUnitCostDefault } from '$lib/services/industry-cpp-defaults.js';

  /**
   * @typedef {{ name: string, detectedType: 'monetary' | 'physical' }} ChannelInfo
   */

  /**
   * @type {{
   *   channel: ChannelInfo,
   *   channelSum?: number,
   *   siblingCount?: number,
   *   industry?: string,
   *   onApplyToSameType?: () => void,
   * }}
   */
  const {
    channel,
    channelSum = undefined,
    siblingCount = 0,
    industry = 'unknown',
    onApplyToSameType = undefined,
  } = $props();

  /**
   * H-09: industry-aware suggestion для текущего канала. null если pattern
   * не определён (channel name не matches TRP/GRP/CPM/CPC/etc.).
   */
  const suggestion = $derived(suggestUnitCostDefault(channel.name, industry));

  /** Format suggestion value к compact human-readable string. */
  function formatSuggestion(/** @type {number} */ v) {
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${Math.round(v / 1000)}k`;
    return String(Math.round(v));
  }

  /** Confidence label для UI tooltip. */
  function confidenceLabel(/** @type {string} */ c) {
    return c === 'high' ? 'высокая точность'
      : c === 'medium' ? 'средняя точность'
      : 'низкая точность';
  }

  /** Получить текущий mode для канала. Default — 'budget' (audit U1). */
  function modeOf() {
    return $unitCostInputMode[channel.name] ?? 'budget';
  }

  /** @param {'budget' | 'unit'} mode */
  function setMode(mode) {
    unitCostInputMode.update((curr) => ({ ...curr, [channel.name]: mode }));
  }

  /** Канал «converted» если для него задан unit_cost > 0. */
  function isConverted() {
    const uc = $unitCosts?.[channel.name];
    return typeof uc === 'number' && uc > 0;
  }

  /** Mode A: общий бюджет ₽ → derive unit_cost = budget / sum(units). */
  function updateBudget(/** @type {string} */ value) {
    const budget = parseFloat(value);
    if (!isFinite(budget) || budget <= 0) {
      budgetInputs.update((curr) => {
        const next = { ...curr };
        delete next[channel.name];
        return next;
      });
      unitCosts.update((curr) => {
        const next = { ...curr };
        delete next[channel.name];
        return next;
      });
      return;
    }
    budgetInputs.update((curr) => ({ ...curr, [channel.name]: budget }));
    if (!channelSum || channelSum <= 0) return;
    const derivedUnitCost = budget / channelSum;
    unitCosts.update((curr) => ({ ...curr, [channel.name]: derivedUnitCost }));
  }

  /** Mode B: прямой ввод цены 1 единицы. */
  function updateUnitCost(/** @type {string} */ value) {
    const num = parseFloat(value);
    if (!isFinite(num) || num <= 0) {
      unitCosts.update((curr) => {
        const next = { ...curr };
        delete next[channel.name];
        return next;
      });
      return;
    }
    unitCosts.update((curr) => ({ ...curr, [channel.name]: num }));
  }

  /** Mode B: годовой % роста стоимости (CPP/CPM). */
  function updateInflation(/** @type {string} */ value) {
    const num = parseFloat(value);
    if (!isFinite(num)) {
      unitCostInflation.update((curr) => {
        const next = { ...curr };
        delete next[channel.name];
        return next;
      });
      return;
    }
    unitCostInflation.update((curr) => ({ ...curr, [channel.name]: num }));
  }

  /** Preview итоговая сумма ₽ при mode='unit'. */
  function previewTotal() {
    const uc = $unitCosts?.[channel.name];
    if (!uc || !channelSum) return null;
    return uc * channelSum;
  }

  /** Debounce per-input (keyed). Phase 2.4 — 150ms. */
  /** @type {Record<string, ReturnType<typeof setTimeout>>} */
  let pendingTimers = {};

  /** @param {string} key @param {() => void} fn */
  function debounceCall(key, fn, delay = 150) {
    if (pendingTimers[key]) clearTimeout(pendingTimers[key]);
    pendingTimers[key] = setTimeout(() => {
      delete pendingTimers[key];
      fn();
    }, delay);
  }

  function updateBudgetDebounced(/** @type {string} */ value) {
    debounceCall(`budget:${channel.name}`, () => updateBudget(value));
  }
  function updateUnitCostDebounced(/** @type {string} */ value) {
    debounceCall(`unit:${channel.name}`, () => updateUnitCost(value));
  }
  function updateInflationDebounced(/** @type {string} */ value) {
    debounceCall(`infl:${channel.name}`, () => updateInflation(value));
  }

  /** Slugify channel name для valid HTML attribute (Cyrillic compat). */
  function slugify(/** @type {string | undefined} */ name) {
    if (!name) return 'unnamed';
    return String(name)
      .toLowerCase()
      .replace(/[^\w-]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .replace(/-{2,}/g, '-')
      .slice(0, 50) || 'unnamed';
  }
</script>

<div
  class="uc-row"
  class:uc-row--converted={isConverted()}
  data-testid="uc-editor"
  data-channel={channel.name}
>
  <div class="uc-row-head">
    <span class="uc-channel">{channel.name}</span>
    <div class="uc-mode-toggle" role="tablist" aria-label="Способ конвертации">
      <button
        type="button"
        role="tab"
        aria-selected={modeOf() === 'budget'}
        class="uc-mode-btn"
        class:active={modeOf() === 'budget'}
        onclick={() => setMode('budget')}
      >Общий бюджет ₽</button>
      <button
        type="button"
        role="tab"
        aria-selected={modeOf() === 'unit'}
        class="uc-mode-btn"
        class:active={modeOf() === 'unit'}
        onclick={() => setMode('unit')}
      >Цена 1 ед. + инфляция</button>
    </div>
  </div>

  {#if modeOf() === 'budget'}
    <div class="uc-fields">
      <label class="uc-field">
        <span class="uc-field-label">Общий бюджет за период, ₽</span>
        <input
          type="number"
          min="0"
          step="any"
          inputmode="decimal"
          class="uc-input"
          placeholder={
            suggestion && channelSum
              ? `например, ${(suggestion.value * channelSum).toLocaleString('ru-RU')}`
              : 'например, 38 000 000'
          }
          value={$budgetInputs[channel.name] ?? ''}
          oninput={(/** @type {Event} */ e) => updateBudgetDebounced(/** @type {HTMLInputElement} */ (e.target).value)}
          data-testid="uc-budget-input-{slugify(channel.name)}"
          data-channel={channel.name}
        />
      </label>
      <p class="uc-preview">
        {#if channelSum && channelSum > 0 && $unitCosts?.[channel.name] && $unitCosts[channel.name] > 0}
          → {$unitCosts[channel.name].toLocaleString('ru-RU', { maximumFractionDigits: 2 })} {unitLabel(channel.name)}
          <span class="uc-preview-mute">
            (бюджет ÷ {channelSum.toLocaleString('ru-RU')} ед.)
          </span>
        {:else if !channelSum}
          <span class="uc-preview-mute">Сумма единиц канала недоступна — выберите режим «Цена 1 ед.»</span>
        {/if}
      </p>
    </div>
  {:else}
    {@const preview = previewTotal()}
    <div class="uc-fields uc-fields--unit">
      <label class="uc-field">
        <span class="uc-field-label">{unitLabel(channel.name)} (текущая)</span>
        <input
          type="number"
          min="0"
          step="any"
          inputmode="decimal"
          class="uc-input"
          placeholder={suggestion ? `~${formatSuggestion(suggestion.value)}` : '0'}
          value={$unitCosts?.[channel.name] ?? ''}
          oninput={(/** @type {Event} */ e) => updateUnitCostDebounced(/** @type {HTMLInputElement} */ (e.target).value)}
          data-testid="uc-unit-input-{slugify(channel.name)}"
          data-channel={channel.name}
        />
        {#if suggestion}
          <span
            class="uc-suggestion-hint"
            data-testid="uc-suggestion-hint"
            data-channel={channel.name}
            title="{confidenceLabel(suggestion.confidence)}{suggestion.source ? `, ${suggestion.source}` : ''}"
          >
            типично {formatSuggestion(suggestion.range.min)}–{formatSuggestion(suggestion.range.max)} ₽
          </span>
        {/if}
      </label>
      <label class="uc-field uc-field--narrow">
        <span class="uc-field-label">Рост стоимости, % / год</span>
        <input
          type="number"
          step="any"
          inputmode="decimal"
          class="uc-input"
          placeholder="обычно 0-20%, оставьте 0 если не знаете"
          value={$unitCostInflation?.[channel.name] ?? ''}
          oninput={(/** @type {Event} */ e) => updateInflationDebounced(/** @type {HTMLInputElement} */ (e.target).value)}
          data-testid="uc-infl-input-{slugify(channel.name)}"
          data-channel={channel.name}
        />
      </label>
      <p class="uc-preview">
        {#if preview !== null && preview > 0}
          → итоговая сумма за период:
          <strong>{preview.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽</strong>
          {#if $unitCostInflation?.[channel.name] && $unitCostInflation[channel.name] !== 0}
            <span class="uc-preview-mute">(до взвешивания по инфляции)</span>
          {/if}
        {/if}
      </p>
    </div>
  {/if}

  <!-- H-12 fix: «Применить ко всем такого же типа» visible в обоих режимах
       (budget + unit). В budget mode unit_cost derived из бюджета → isConverted()
       returns true → кнопка показывается. Аудит выявил что фича была невидима
       в budget mode → пользователи не находили её. -->
  {#if isConverted() && siblingCount > 0 && onApplyToSameType}
    <button
      type="button"
      class="uc-apply-same"
      onclick={onApplyToSameType}
      data-testid="uc-apply-same-btn-{slugify(channel.name)}"
      data-channel={channel.name}
    >
      Применить ко всем «{unitLabel(channel.name)}» ({siblingCount})
    </button>
  {/if}
</div>

<style>
  .uc-row {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px 12px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: 6px;
  }
  @media (prefers-reduced-motion: no-preference) {
    .uc-row {
      transition: border-color 0.18s, background 0.18s;
    }
  }
  .uc-row--converted {
    border-color: color-mix(in srgb, var(--success, #10B981) 32%, transparent);
    background: color-mix(in srgb, var(--success, #10B981) 4%, var(--bg-card, #181824));
  }
  .uc-row-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }
  .uc-channel {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .uc-mode-toggle {
    display: inline-flex;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 6px;
    overflow: hidden;
  }
  .uc-mode-btn {
    background: transparent;
    border: 0;
    padding: 5px 10px;
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    cursor: pointer;
  }
  @media (prefers-reduced-motion: no-preference) {
    .uc-mode-btn {
      transition: background 0.15s, color 0.15s;
    }
  }
  .uc-mode-btn + .uc-mode-btn {
    border-left: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
  }
  .uc-mode-btn:hover { color: var(--text-primary); }
  .uc-mode-btn.active {
    background: color-mix(in srgb, var(--gold, #c9a449) 14%, transparent);
    color: var(--gold, #c9a449);
    font-weight: 600;
  }
  .uc-fields {
    display: flex;
    gap: 12px;
    align-items: flex-end;
    flex-wrap: wrap;
  }
  .uc-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1 1 200px;
  }
  .uc-field--narrow { flex: 0 1 140px; }
  .uc-field-label {
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
    font-weight: 500;
  }
  /* H-09: industry-aware suggestion hint под input. */
  .uc-suggestion-hint {
    font-size: 10.5px;
    color: var(--text-muted, #7A7A90);
    font-style: italic;
    margin-top: 2px;
    cursor: help;
  }
  .uc-input {
    padding: 7px 10px;
    background: var(--bg-input, rgba(255,255,255,0.03));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 5px;
    color: var(--text-primary);
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
  @media (prefers-reduced-motion: no-preference) {
    .uc-input {
      transition: border-color 0.15s;
    }
  }
  .uc-input:focus {
    outline: none;
    border-color: var(--gold, #c9a449);
  }
  .uc-preview {
    margin: 4px 0 0;
    font-size: 12px;
    color: var(--success, #10B981);
    flex-basis: 100%;
  }
  .uc-preview strong { font-weight: 600; }
  .uc-preview-mute { color: var(--text-muted, #7A7A90); font-weight: 400; }

  .uc-apply-same {
    margin-top: 6px;
    background: transparent;
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 35%, transparent);
    color: var(--gold, #c9a449);
    font-size: 11px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 6px;
    cursor: pointer;
    align-self: flex-start;
  }
  @media (prefers-reduced-motion: no-preference) {
    .uc-apply-same {
      transition: background 0.15s, color 0.15s, transform 0.1s;
    }
    .uc-apply-same:hover {
      background: var(--gold, #c9a449);
      color: var(--bg-card, #181824);
    }
    .uc-apply-same:active {
      transform: scale(0.97);
    }
  }
</style>
