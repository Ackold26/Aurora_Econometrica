<script>
  /**
   * AppliedModeSummary - v2.0.0 read-only summary of applied analysis mode.
   *
   * Per §0.4 WIZARD_FLOW_v2_FINAL.md: in Manager mode, replaces PerChannelInputSelector
   * with a clean read-only summary of the mode that was chosen in AnalysisModeSelector.
   *
   * Shows:
   *   - Which mode is active (ROI / Effectiveness)
   *   - List of channels with inferred metric type
   *   - CTA to enable Expert mode for per-channel manual control
   *
   * Reads from:
   *   - $analysisMode — chosen mode store
   *   - $expertMode — to show/hide CTA
   *
   * Styling: matches KPISelector.svelte + RatioInfoCard.svelte premium tier-1 vocabulary.
   *
   * @component AppliedModeSummary
   */

  import {
    analysisMode, expertMode, unitCosts, unitCostInflation,
    // Phase 1.3 (v2.0.1) — persistence для UI mode preference + budget input restore.
    unitCostInputMode, budgetInputs,
  } from '$lib/project-state.js';
  import { pluralizeRu } from '$lib/utils/i18n.js';
  // Phase 1.1 (SSOT): unit label resolution через shared service.
  // Replaces inline unitLabel() regex — теперь one source of truth с
  // backend column_detection.unit_label_for(). Cache-with-fallback.
  import { unitLabelFor as unitLabel } from '$lib/services/classifier-patterns.js';

  /**
   * @typedef {{ name: string, detectedType: 'monetary' | 'physical' }} ChannelInfo
   * @typedef {{ label: string, isPhysical: boolean, incompatible: boolean, converted?: boolean }} ChannelLabelMeta
   */

  /**
   * @type {{
   *   channels?: ChannelInfo[],
   *   channelSums?: Record<string, number>,
   *   excludedChannelNames?: string[],
   *   onRestoreChannel?: (name: string) => void,
   * }}
   */
  const {
    channels = [],
    channelSums = {},
    excludedChannelNames = [],
    onRestoreChannel = undefined,
  } = $props();

  /** Phase 2.9: per-channel restore enabled when callback wired. */
  const hasRestoreAction = $derived(typeof onRestoreChannel === 'function');

  /** UX gap fix (v2.0.1): user не видит на «Метрики каналов» что-то excluded
   *  (например ratioRecommendation rule auto-excludes media с zeros% > 50%).
   *  Показываем pill «N исключено» с раскрывающимся списком имён. */
  let excludedExpanded = $state(false);

  // Phase 1.3 (v2.0.1): persistence promotion — modeFor + budgetInputs
  // promoted from local $state к shared stores. Sync через project.json
  // на save_kpi_settings (Phase 1.2 extended schema). Reload preserves
  // mode preference.

  /** Helper: канал «converted» если для него задан unit_cost > 0. */
  function isConverted(/** @type {string} */ name) {
    const uc = $unitCosts?.[name];
    return typeof uc === 'number' && uc > 0;
  }

  /** BUG #2 fix (v2.0.1): count каналов с physical unit в ROI mode БЕЗ
   *  установленного unit_cost. После ввода цены канал становится «converted»
   *  и больше не считается incompatible. */
  const incompatibleCount = $derived(
    $analysisMode === 'roi'
      ? channels.filter((/** @type {ChannelInfo} */ c) =>
          c.detectedType === 'physical' && !isConverted(c.name)
        ).length
      : 0
  );

  /** Есть ли хотя бы один physical канал в ROI mode (converted или нет).
   *  Используется чтобы показывать inline unit_cost inputs даже после
   *  конвертации — для редактирования. */
  const hasAnyPhysicalInRoi = $derived(
    $analysisMode === 'roi' && channels.some(
      (/** @type {ChannelInfo} */ c) => c.detectedType === 'physical'
    )
  );

  // Note: unitLabel() now imported from $lib/services/classifier-patterns.js
  // (Phase 1.1 SSOT — eliminates regex duplication со column_detection.py).

  /** Получить текущий mode для канала. Default — 'budget' (бренд-менеджер знает бюджет).
   *  Reads from $unitCostInputMode store (Phase 1.3 persistence). */
  function modeOf(/** @type {string} */ name) {
    return $unitCostInputMode[name] ?? 'budget';
  }

  /** @param {string} name @param {'budget' | 'unit'} mode */
  function setMode(name, mode) {
    unitCostInputMode.update((curr) => ({ ...curr, [name]: mode }));
  }

  /** Mode A: общий бюджет ₽ → derive unit_cost = budget / sum(units).
   *  Persists raw input в $budgetInputs store (survives reload). */
  function updateBudget(/** @type {string} */ name, /** @type {string} */ value) {
    const budget = parseFloat(value);
    if (!isFinite(budget) || budget <= 0) {
      // Clear stored budget + unit cost if invalid.
      budgetInputs.update((curr) => {
        const next = { ...curr };
        delete next[name];
        return next;
      });
      unitCosts.update((curr) => {
        const next = { ...curr };
        delete next[name];
        return next;
      });
      return;
    }
    budgetInputs.update((curr) => ({ ...curr, [name]: budget }));
    const sum = channelSums?.[name];
    if (!sum || sum <= 0) {
      // Budget stored, но derive не возможен без sum (sparse channel) —
      // leave unit_cost untouched, UI shows hint.
      return;
    }
    const derivedUnitCost = budget / sum;
    unitCosts.update((curr) => ({ ...curr, [name]: derivedUnitCost }));
  }

  /** Mode B: прямой ввод цены 1 единицы. */
  function updateUnitCost(/** @type {string} */ name, /** @type {string} */ value) {
    const num = parseFloat(value);
    if (!isFinite(num) || num <= 0) {
      unitCosts.update((curr) => {
        const next = { ...curr };
        delete next[name];
        return next;
      });
      return;
    }
    unitCosts.update((curr) => ({ ...curr, [name]: num }));
  }

  /** Mode B: годовой % роста стоимости. */
  function updateInflation(/** @type {string} */ name, /** @type {string} */ value) {
    const num = parseFloat(value);
    if (!isFinite(num)) {
      unitCostInflation.update((curr) => {
        const next = { ...curr };
        delete next[name];
        return next;
      });
      return;
    }
    unitCostInflation.update((curr) => ({ ...curr, [name]: num }));
  }

  /**
   * Slugify channel name для valid HTML attribute / test selector.
   * Converts Cyrillic and spaces to ASCII-safe dashes.
   * @param {string | undefined} name
   * @returns {string}
   */
  function slugify(name) {
    if (!name) return 'unnamed';
    return String(name)
      .toLowerCase()
      .replace(/[^\w-]+/g, '-')   // non-word → dash
      .replace(/^-+|-+$/g, '')    // trim leading/trailing dashes
      .replace(/-{2,}/g, '-')     // collapse multiple dashes
      .slice(0, 50) || 'unnamed';
  }

  /** Debounce helper — keyed по channel+field для per-input cancel. */
  /** @type {Record<string, ReturnType<typeof setTimeout>>} */
  let pendingTimers = {};

  /**
   * @param {string} key
   * @param {() => void} fn
   * @param {number} [delay]
   */
  function debounceCall(key, fn, delay = 150) {
    if (pendingTimers[key]) clearTimeout(pendingTimers[key]);
    pendingTimers[key] = setTimeout(() => {
      delete pendingTimers[key];
      fn();
    }, delay);
  }

  /** Debounced wrappers for template oninput handlers. */
  function updateBudgetDebounced(/** @type {string} */ name, /** @type {string} */ value) {
    debounceCall(`budget:${name}`, () => updateBudget(name, value));
  }
  function updateUnitCostDebounced(/** @type {string} */ name, /** @type {string} */ value) {
    debounceCall(`unit:${name}`, () => updateUnitCost(name, value));
  }
  function updateInflationDebounced(/** @type {string} */ name, /** @type {string} */ value) {
    debounceCall(`infl:${name}`, () => updateInflation(name, value));
  }

  /** Display formatter для preview суммы ₽ при mode='unit'. */
  function previewTotal(/** @type {string} */ name) {
    const uc = $unitCosts?.[name];
    const sum = channelSums?.[name];
    if (!uc || !sum) return null;
    return uc * sum;
  }

  /** Header text driven by $analysisMode */
  const headerText = $derived(
    $analysisMode === 'roi'
      ? 'Все каналы будут поданы в модель как ₽'
      : $analysisMode === 'effectiveness'
        ? 'Все каналы будут поданы в модель как физические метрики'
        : 'Каналы поданы в смешанном режиме (per-channel)'
  );

  /**
   * For each channel, infer the display label based on analysisMode.
   * In ROI mode — monetary каналы show «спенд в ₽», physical-only — warning
   * (incompatible: true). In effectiveness — все as physical. В mixed — as-is.
   *
   * BUG #2 fix (v2.0.1): physical unit (TRP, показы) нельзя интерпретировать
   * как ₽ без unit_cost. Помечаем incompatible с visual warning.
   *
   * @param {ChannelInfo} ch
   * @returns {ChannelLabelMeta}
   */
  function channelLabel(ch) {
    const isPhysical = ch.detectedType === 'physical';
    if ($analysisMode === 'roi') {
      if (isPhysical) {
        // Converted: unit_cost задан > 0 → канал готов к ROI расчёту.
        if (isConverted(ch.name)) {
          const uc = $unitCosts?.[ch.name] ?? 0;
          const ucFmt = uc >= 100
            ? uc.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
            : uc.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
          return {
            label: `${ucFmt} ${unitLabel(ch.name)} — конвертация в ₽`,
            isPhysical: false,
            incompatible: false,
            converted: true,
          };
        }
        return { label: '⚠ нужна конвертация в ₽ (общий бюджет или цена 1 ед.)', isPhysical: true, incompatible: true };
      }
      return { label: 'спенд в ₽', isPhysical: false, incompatible: false };
    }
    if ($analysisMode === 'effectiveness') {
      return {
        label: isPhysical ? 'физ. метрика' : 'конвертируется в физ.',
        isPhysical: true,
        incompatible: false,
      };
    }
    // mixed — show as-is
    return {
      label: isPhysical ? 'физ. метрика' : 'спенд в ₽',
      isPhysical,
      incompatible: false,
    };
  }

  function enableExpertMode() {
    expertMode.set(true);
  }
</script>

<aside class="applied-summary" aria-label="Применённый режим анализа">
  <header class="summary-header">
    <div class="header-left">
      <span class="kicker">ПРИМЕНЁННЫЙ РЕЖИМ</span>
      <h3 class="summary-title">{headerText}</h3>
    </div>
    <div class="mode-badge mode-badge--{$analysisMode}">
      {#if $analysisMode === 'roi'}
        ROI режим
      {:else if $analysisMode === 'effectiveness'}
        Эффективность
      {:else}
        Смешанный
      {/if}
    </div>
  </header>

  {#if channels.length > 0 || excludedChannelNames.length > 0}
    <div class="channel-counts" data-testid="channel-counts">
      <span class="count-pill count-pill--active">
        <strong>{channels.length}</strong>
        {pluralizeRu(channels.length, ['активный канал', 'активных канала', 'активных каналов'])}
      </span>
      {#if excludedChannelNames.length > 0}
        <button
          type="button"
          class="count-pill count-pill--excluded"
          aria-expanded={excludedExpanded}
          onclick={() => (excludedExpanded = !excludedExpanded)}
          data-testid="excluded-toggle"
        >
          <strong>⊘ {excludedChannelNames.length}</strong>
          {pluralizeRu(excludedChannelNames.length, ['исключён', 'исключено', 'исключено'])}
          <span class="count-chevron" class:open={excludedExpanded}>▾</span>
        </button>
      {/if}
    </div>
    {#if excludedExpanded && excludedChannelNames.length > 0}
      <div class="excluded-list" role="region" aria-label="Исключённые каналы" data-testid="excluded-list">
        <p class="excluded-hint">
          Эти каналы автоматически исключены из модели (обычно из-за &gt;50%
          нулей — низкая активность за период). {hasRestoreAction
            ? 'Кнопка «Вернуть» возвращает канал к role=media.'
            : 'Можно вернуть через шаг «Роли колонок» или применить «Сбросить шаг».'}
        </p>
        <ul class="excluded-items">
          {#each excludedChannelNames as name (name)}
            <li class="excluded-item">
              <span class="excluded-item-name">{name}</span>
              {#if hasRestoreAction}
                <button
                  type="button"
                  class="excluded-restore"
                  onclick={() => onRestoreChannel?.(name)}
                  data-testid="excluded-restore-btn"
                  data-channel={name}
                  aria-label="Вернуть канал «{name}» в модель"
                >↶ Вернуть</button>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}

  {#if channels.length > 0}
    {#if incompatibleCount > 0}
      <div class="incompat-banner" role="alert" data-testid="incompat-banner">
        <strong>⚠ {incompatibleCount}
          {pluralizeRu(incompatibleCount, ['канал', 'канала', 'каналов'])}</strong>
        с физическими метриками (TRP / показы / клики) — для ROI режима их нужно перевести в ₽.
        <br />
        Укажите для каждого:
        <strong>общий бюджет в ₽</strong> (если известен)
        либо <strong>стоимость 1 единицы + годовой % роста стоимости</strong>
        (если знаете). Модель сконвертирует автоматически.
        Или исключите канал из модели.
      </div>
    {/if}

    {#if hasAnyPhysicalInRoi}
      <!-- BUG #2 fix (v2.0.1): inline two-mode unit_cost inputs.
           Видны ВСЕГДА для physical каналов в ROI mode (даже когда уже converted)
           — чтобы пользователь мог редактировать unit_cost / переключать режим.
           Mode A (budget): общий ₽-бюджет за период → derive unit_cost = budget / Σ(units).
           Mode B (unit): прямой ввод цены 1 ед. + годовой % роста стоимости. -->
      <div class="uc-inputs" data-testid="uc-inputs" role="group" aria-label="Конвертация физических каналов в ₽">
        {#each channels as ch (ch.name)}
          {#if ch.detectedType === 'physical' && $analysisMode === 'roi'}
            {@const mode = modeOf(ch.name)}
            {@const ucValue = $unitCosts?.[ch.name]}
            {@const inflValue = $unitCostInflation?.[ch.name]}
            {@const sumValue = channelSums?.[ch.name]}
            {@const preview = previewTotal(ch.name)}
            <div class="uc-row" class:uc-row--converted={isConverted(ch.name)}>
              <div class="uc-row-head">
                <span class="uc-channel">{ch.name}</span>
                <div class="uc-mode-toggle" role="tablist" aria-label="Способ конвертации">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={mode === 'budget'}
                    class="uc-mode-btn"
                    class:active={mode === 'budget'}
                    onclick={() => setMode(ch.name, 'budget')}
                  >Общий бюджет ₽</button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={mode === 'unit'}
                    class="uc-mode-btn"
                    class:active={mode === 'unit'}
                    onclick={() => setMode(ch.name, 'unit')}
                  >Цена 1 ед. + инфляция</button>
                </div>
              </div>

              {#if mode === 'budget'}
                <div class="uc-fields">
                  <label class="uc-field">
                    <span class="uc-field-label">Общий бюджет за период, ₽</span>
                    <input
                      type="number"
                      min="0"
                      step="any"
                      inputmode="decimal"
                      class="uc-input"
                      placeholder="например, 38 000 000"
                      value={$budgetInputs[ch.name] ?? ''}
                      oninput={(/** @type {Event} */ e) => updateBudgetDebounced(ch.name, /** @type {HTMLInputElement} */ (e.target).value)}
                      data-testid="uc-budget-input-{slugify(ch.name)}"
                      data-channel={ch.name}
                    />
                  </label>
                  <p class="uc-preview">
                    {#if sumValue && sumValue > 0 && ucValue && ucValue > 0}
                      → {ucValue.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} {unitLabel(ch.name)}
                      <span class="uc-preview-mute">
                        (бюджет ÷ {sumValue.toLocaleString('ru-RU')} ед.)
                      </span>
                    {:else if !sumValue}
                      <span class="uc-preview-mute">Сумма единиц канала недоступна — выберите режим «Цена 1 ед.»</span>
                    {/if}
                  </p>
                </div>
              {:else}
                <div class="uc-fields uc-fields--unit">
                  <label class="uc-field">
                    <span class="uc-field-label">{unitLabel(ch.name)} (текущая)</span>
                    <input
                      type="number"
                      min="0"
                      step="any"
                      inputmode="decimal"
                      class="uc-input"
                      placeholder="0"
                      value={ucValue ?? ''}
                      oninput={(/** @type {Event} */ e) => updateUnitCostDebounced(ch.name, /** @type {HTMLInputElement} */ (e.target).value)}
                      data-testid="uc-unit-input-{slugify(ch.name)}"
                      data-channel={ch.name}
                    />
                  </label>
                  <label class="uc-field uc-field--narrow">
                    <span class="uc-field-label">Рост стоимости, % / год</span>
                    <input
                      type="number"
                      step="any"
                      inputmode="decimal"
                      class="uc-input"
                      placeholder="обычно 0-20%, оставьте 0 если не знаете"
                      value={inflValue ?? ''}
                      oninput={(/** @type {Event} */ e) => updateInflationDebounced(ch.name, /** @type {HTMLInputElement} */ (e.target).value)}
                      data-testid="uc-infl-input-{slugify(ch.name)}"
                      data-channel={ch.name}
                    />
                  </label>
                  <p class="uc-preview">
                    {#if preview && preview > 0}
                      → итоговая сумма за период:
                      <strong>{preview.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽</strong>
                      {#if inflValue && inflValue !== 0}
                        <span class="uc-preview-mute">(до взвешивания по инфляции)</span>
                      {/if}
                    {/if}
                  </p>
                </div>
              {/if}
            </div>
          {/if}
        {/each}
      </div>
    {/if}
    <ul class="channel-list" aria-label="Список каналов с типами метрик">
      {#each channels as ch (ch.name)}
        {@const meta = channelLabel(ch)}
        <li class="channel-item"
            class:incompatible={meta.incompatible}
            class:converted={meta.converted}>
          <span class="channel-name">{ch.name}</span>
          <span class="channel-arrow" aria-hidden="true">→</span>
          <span class="channel-metric"
                class:metric-physical={meta.isPhysical}
                class:metric-incompat={meta.incompatible}
                class:metric-converted={meta.converted}>
            {meta.label}
            {#if !meta.isPhysical && !meta.incompatible}
              <span class="check-mark" aria-label="Подтверждено">✓</span>
            {/if}
          </span>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="no-channels">
      Каналы определятся после импорта данных.
    </p>
  {/if}

  {#if !$expertMode}
    <div class="cta-block">
      <p class="cta-text">
        Нужен ручной выбор единиц per-канал? Включите Expert mode — появится
        полный контроль над каждым каналом.
      </p>
      <button type="button" class="btn-expert" onclick={enableExpertMode}>
        Управлять вручную → Включить Expert mode
      </button>
    </div>
  {:else}
    <p class="expert-active-note">
      <span class="expert-label-inline">EXPERT</span>
      Expert mode включён. Используйте PerChannelInputSelector для ручного управления.
    </p>
  {/if}
</aside>

<style>
  .applied-summary {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 18px 22px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    border-left-width: 3px;
    border-left-color: var(--gold, #c9a449);
    max-width: 920px;
  }

  /* ─── Header ─── */
  .summary-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    flex-wrap: wrap;
  }
  .header-left {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .kicker {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    color: var(--gold, #c9a449);
    text-transform: uppercase;
  }
  .summary-title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.4;
    letter-spacing: -0.01em;
  }

  /* ─── Mode badge ─── */
  .mode-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .mode-badge--roi {
    background: color-mix(in srgb, var(--gold, #c9a449) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 35%, transparent);
    color: var(--gold, #c9a449);
  }
  .mode-badge--effectiveness {
    background: color-mix(in srgb, var(--accent-primary, #2E5BFF) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary, #2E5BFF) 35%, transparent);
    color: var(--accent-primary, #2E5BFF);
  }
  .mode-badge--mixed {
    background: color-mix(in srgb, var(--warning, #F59E0B) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 35%, transparent);
    color: var(--warning, #F59E0B);
  }

  /* ─── Channel list ─── */
  .channel-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
    overflow: hidden;
  }
  .channel-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 14px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    background: transparent;
  }
  .channel-item:last-child { border-bottom: none; }
  .channel-item:nth-child(even) {
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
  }

  .channel-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    min-width: 120px;
    flex-shrink: 0;
  }
  .channel-arrow {
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
    flex-shrink: 0;
  }
  .channel-metric {
    font-size: 12.5px;
    color: var(--gold, #c9a449);
    display: flex;
    align-items: center;
    gap: 5px;
    font-weight: 500;
  }
  .channel-metric.metric-physical {
    color: var(--accent-primary, #2E5BFF);
  }
  .channel-metric.metric-incompat {
    color: var(--warning, #F59E0B);
    font-weight: 600;
  }
  .channel-list .channel-item.incompatible {
    background: color-mix(in srgb, var(--warning, #F59E0B) 6%, transparent);
    border-left: 2px solid var(--warning, #F59E0B);
  }
  .channel-list .channel-item.converted {
    background: color-mix(in srgb, var(--success, #10B981) 5%, transparent);
    border-left: 2px solid var(--success, #10B981);
  }
  .channel-metric.metric-converted {
    color: var(--success, #10B981);
    font-weight: 500;
  }
  .check-mark {
    font-size: 11px;
    color: var(--success, #10B981);
    font-weight: 700;
  }

  /* ─── UX gap fix v2.0.1: counts pills + excluded list ─── */
  .channel-counts {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  .count-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 11.5px;
    font-weight: 500;
    border: 1px solid transparent;
    background: transparent;
    cursor: default;
  }
  .count-pill strong { font-weight: 700; }
  .count-pill--active {
    background: color-mix(in srgb, var(--success, #10B981) 10%, transparent);
    border-color: color-mix(in srgb, var(--success, #10B981) 28%, transparent);
    color: var(--success, #10B981);
  }
  .count-pill--excluded {
    background: color-mix(in srgb, var(--text-muted, #7A7A90) 8%, transparent);
    border-color: color-mix(in srgb, var(--text-muted, #7A7A90) 25%, transparent);
    color: var(--text-secondary, #b6b6c5);
    cursor: pointer;
  }
  .count-pill--excluded:hover {
    background: color-mix(in srgb, var(--text-muted, #7A7A90) 14%, transparent);
    color: var(--text-primary);
  }
  .count-chevron {
    display: inline-block;
  }
  .count-chevron.open { transform: rotate(180deg); }

  .excluded-list {
    padding: 12px;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
  }
  .excluded-hint {
    margin: 0 0 8px;
    font-size: 12px;
    color: var(--text-secondary, #b6b6c5);
    line-height: 1.5;
  }
  .excluded-items {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .excluded-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 4px 3px 9px;
    border-radius: 10px;
    background: var(--bg-card, #181824);
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.18));
    color: var(--text-muted, #7A7A90);
    font-size: 11.5px;
  }
  .excluded-item-name {
    text-decoration: line-through;
    text-decoration-color: color-mix(in srgb, var(--text-muted, #7A7A90) 50%, transparent);
  }
  /* Phase 2.9: per-channel inline restore button */
  .excluded-restore {
    background: transparent;
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 35%, transparent);
    color: var(--gold, #c9a449);
    font-size: 10.5px;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 6px;
    cursor: pointer;
    line-height: 1.5;
  }
  @media (prefers-reduced-motion: no-preference) {
    .excluded-restore {
      transition: background 0.15s, color 0.15s, transform 0.1s;
    }
    .excluded-restore:hover {
      background: var(--gold, #c9a449);
      color: var(--bg-card, #181824);
    }
    .excluded-restore:active {
      transform: scale(0.96);
    }
  }

  /* ─── BUG #2 fix v2.0.1: incompatibility banner ─── */
  .incompat-banner {
    padding: 12px 14px;
    border-radius: 8px;
    background: color-mix(in srgb, var(--warning, #F59E0B) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 32%, transparent);
    color: var(--text-primary);
    font-size: 12.5px;
    line-height: 1.55;
  }
  .incompat-banner strong { color: var(--warning, #F59E0B); }

  /* ─── BUG #2 fix v2.0.1: inline two-mode unit_cost inputs ─── */
  .uc-inputs {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
  }
  .uc-row {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px 12px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: 6px;
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
    text-transform: none;
    font-weight: 500;
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

  /* ─── No channels placeholder ─── */
  .no-channels {
    margin: 0;
    font-size: 12.5px;
    color: var(--text-muted, #7A7A90);
    font-style: italic;
    padding: 10px 14px;
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
  }

  /* ─── CTA block ─── */
  .cta-block {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px 14px;
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, transparent);
    border-left: 2px solid var(--gold, #c9a449);
    border-radius: 0 4px 4px 0;
  }
  .cta-text {
    margin: 0;
    font-size: 12.5px;
    line-height: 1.55;
    color: var(--text-secondary);
  }
  .btn-expert {
    align-self: flex-start;
    padding: 8px 16px;
    border-radius: var(--radius-sm, 8px);
    background: var(--gold, #c9a449);
    color: var(--bg-card, #181824);
    border: none;
    font: inherit;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.03em;
    cursor: pointer;
  }
  .btn-expert:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 14px color-mix(in srgb, var(--gold, #c9a449) 35%, transparent);
  }
  .btn-expert:active {
    transform: translateY(0);
  }

  /* ─── Expert active note ─── */
  .expert-active-note {
    margin: 0;
    font-size: 12px;
    color: var(--text-muted, #7A7A90);
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: color-mix(in srgb, var(--warning, #F59E0B) 5%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 20%, transparent);
    border-radius: var(--radius-sm, 8px);
  }
  .expert-label-inline {
    display: inline-flex;
    align-items: center;
    padding: 1px 6px;
    border-radius: 3px;
    background: color-mix(in srgb, var(--warning, #F59E0B) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 40%, transparent);
    font-size: 8.5px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--warning, #F59E0B);
    flex-shrink: 0;
  }

  /* ─── Delight transitions — INV-12: only when motion is preferred ─── */
  @media (prefers-reduced-motion: no-preference) {
    .channel-item {
      transition: background 0.15s ease-out;
    }
    .uc-row {
      transition: border-color 0.25s ease-out, background 0.25s ease-out;
    }
    .excluded-list {
      transition: max-height 0.2s ease-out;
    }
    .uc-mode-btn {
      transition: background 0.15s ease-out, color 0.15s ease-out;
    }
    .count-pill--excluded {
      transition: background 0.15s ease-out, border-color 0.15s ease-out;
    }
    .uc-input {
      transition: border-color 0.15s ease-out;
    }
    .count-chevron {
      transition: transform 0.15s ease-out;
    }
    .btn-expert {
      transition: transform 0.15s ease-out, box-shadow 0.15s ease-out;
    }
  }
</style>
