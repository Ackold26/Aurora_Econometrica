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

  import { analysisMode, expertMode, unitCosts, unitCostInflation } from '$lib/project-state.js';

  /**
   * @typedef {{ name: string, detectedType: 'monetary' | 'physical' }} ChannelInfo
   * @typedef {{ label: string, isPhysical: boolean, incompatible: boolean, converted?: boolean }} ChannelLabelMeta
   */

  /**
   * @type {{
   *   channels?: ChannelInfo[],
   *   channelSums?: Record<string, number>,
   *   excludedChannelNames?: string[],
   * }}
   */
  const { channels = [], channelSums = {}, excludedChannelNames = [] } = $props();

  /** UX gap fix (v2.0.1): user не видит на «Метрики каналов» что-то excluded
   *  (например ratioRecommendation rule auto-excludes media с zeros% > 50%).
   *  Показываем pill «N исключено» с раскрывающимся списком имён. */
  let excludedExpanded = $state(false);

  /** Local UI-only state: ввод режим per канал ('budget' = общий ₽-бюджет;
   *  'unit' = цена 1 ед. + инфляция CPP/CPM). Default 'unit' — соответствует
   *  существующему flow прошлых версий (unitCosts + unitCostInflation stores).
   * @type {Record<string, 'budget' | 'unit'>} */
  let modeFor = $state(/** @type {Record<string, 'budget' | 'unit'>} */ ({}));

  /** Local UI-only mirror of «общий бюджет, ₽» input для каждого канала.
   *  Хранится отдельно (а не derived из unitCost × sum), чтобы пользователь
   *  мог переключаться между modes без потери введённого значения.
   * @type {Record<string, string>} */
  let budgetInputs = $state(/** @type {Record<string, string>} */ ({}));

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

  /** Detect human-readable unit label («за 1 TRP» / «за 1000 показов» / etc.)
   *  из имени канала для отображения подписи рядом с input. */
  function unitLabel(/** @type {string} */ name) {
    const lower = (name || '').toLowerCase();
    if (/(trp|трп)/.test(lower)) return '₽ за 1 TRP';
    if (/(grp|грп)/.test(lower)) return '₽ за 1 GRP';
    if (/(impression|показ)/.test(lower)) return '₽ за 1000 показов (CPM)';
    if (/(click|клик)/.test(lower)) return '₽ за 1 клик (CPC)';
    if (/(visit|визит)/.test(lower)) return '₽ за 1 визит';
    if (/(view|просмотр)/.test(lower)) return '₽ за 1 просмотр';
    if (/(reach|охват)/.test(lower)) return '₽ за 1000 охвата';
    if (/(прочтен)/.test(lower)) return '₽ за 1 прочтение';
    return '₽ за 1 единицу';
  }

  /** Получить текущий mode для канала. Default — 'unit' (как в прошлых версиях). */
  function modeOf(/** @type {string} */ name) {
    return modeFor[name] ?? 'unit';
  }

  /** @param {string} name @param {'budget' | 'unit'} mode */
  function setMode(name, mode) {
    modeFor = { ...modeFor, [name]: mode };
  }

  /** Mode A: общий бюджет ₽ → derive unit_cost = budget / sum(units). */
  function updateBudget(/** @type {string} */ name, /** @type {string} */ value) {
    budgetInputs = { ...budgetInputs, [name]: value };
    const budget = parseFloat(value);
    const sum = channelSums?.[name];
    if (!isFinite(budget) || budget <= 0 || !sum || sum <= 0) {
      // Clear unit cost if invalid.
      unitCosts.update((curr) => {
        const next = { ...curr };
        delete next[name];
        return next;
      });
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

  /** Mode B: годовая инфляция CPP/CPM (%). */
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
        {channels.length === 1 ? 'активный канал' : channels.length < 5 ? 'активных канала' : 'активных каналов'}
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
          {excludedChannelNames.length === 1 ? 'исключён' : 'исключено'}
          <span class="count-chevron" class:open={excludedExpanded}>▾</span>
        </button>
      {/if}
    </div>
    {#if excludedExpanded && excludedChannelNames.length > 0}
      <div class="excluded-list" role="region" aria-label="Исключённые каналы" data-testid="excluded-list">
        <p class="excluded-hint">
          Эти каналы автоматически исключены из модели (обычно из-за &gt;50%
          нулей — низкая активность за период). Можно вернуть через шаг
          <strong>«Роли колонок»</strong> или применить «Сбросить шаг».
        </p>
        <ul class="excluded-items">
          {#each excludedChannelNames as name (name)}
            <li class="excluded-item">{name}</li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}

  {#if channels.length > 0}
    {#if incompatibleCount > 0}
      <div class="incompat-banner" role="alert" data-testid="incompat-banner">
        <strong>⚠ {incompatibleCount}
          {incompatibleCount === 1
            ? 'канал'
            : incompatibleCount < 5 ? 'канала' : 'каналов'}</strong>
        с физическими метриками (TRP / показы / клики) — для ROI режима их нужно перевести в ₽.
        <br />
        Укажите для каждого:
        <strong>общий бюджет в ₽</strong> (если известен)
        либо <strong>стоимость 1 единицы + годовую инфляцию CPP/CPM</strong>
        (как в предыдущих версиях). Модель сконвертирует автоматически с учётом инфляции
        или исключите канал из модели.
      </div>
    {/if}

    {#if hasAnyPhysicalInRoi}
      <!-- BUG #2 fix (v2.0.1): inline two-mode unit_cost inputs.
           Видны ВСЕГДА для physical каналов в ROI mode (даже когда уже converted)
           — чтобы пользователь мог редактировать unit_cost / переключать режим.
           Mode A (budget): общий ₽-бюджет за период → derive unit_cost = budget / Σ(units).
           Mode B (unit): прямой ввод цены 1 ед. + годовая инфляция CPP/CPM
             — как в прошлых версиях (UnitCostsPanel pattern). -->
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
                      value={budgetInputs[ch.name] ?? ''}
                      oninput={(/** @type {Event} */ e) => updateBudget(ch.name, /** @type {HTMLInputElement} */ (e.target).value)}
                      data-testid="uc-budget-input-{ch.name}"
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
                      oninput={(/** @type {Event} */ e) => updateUnitCost(ch.name, /** @type {HTMLInputElement} */ (e.target).value)}
                      data-testid="uc-unit-input-{ch.name}"
                    />
                  </label>
                  <label class="uc-field uc-field--narrow">
                    <span class="uc-field-label">Инфляция, % / год</span>
                    <input
                      type="number"
                      step="any"
                      inputmode="decimal"
                      class="uc-input"
                      placeholder="0"
                      value={inflValue ?? ''}
                      oninput={(/** @type {Event} */ e) => updateInflation(ch.name, /** @type {HTMLInputElement} */ (e.target).value)}
                      data-testid="uc-infl-input-{ch.name}"
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
    transition: background 0.15s;
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
  .channel-item.incompatible {
    background: color-mix(in srgb, var(--warning, #F59E0B) 6%, transparent) !important;
    border-left: 2px solid var(--warning, #F59E0B);
  }
  .channel-item.converted {
    background: color-mix(in srgb, var(--success, #10B981) 5%, transparent) !important;
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
    transition: background 0.15s, border-color 0.15s;
  }
  .count-pill--excluded:hover {
    background: color-mix(in srgb, var(--text-muted, #7A7A90) 14%, transparent);
    color: var(--text-primary);
  }
  .count-chevron {
    transition: transform 0.15s;
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
    padding: 3px 9px;
    border-radius: 10px;
    background: var(--bg-card, #181824);
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.18));
    color: var(--text-muted, #7A7A90);
    font-size: 11.5px;
    text-decoration: line-through;
    text-decoration-color: color-mix(in srgb, var(--text-muted, #7A7A90) 50%, transparent);
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
    transition: border-color 0.18s, background 0.18s;
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
    transition: background 0.15s, color 0.15s;
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
    transition: border-color 0.15s;
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
    transition: transform 0.15s ease-out, box-shadow 0.15s ease-out;
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
</style>
