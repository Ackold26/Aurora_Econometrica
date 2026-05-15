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
    analysisMode, expertMode, unitCosts, unitCostInflation, unitCostInputMode,
    budgetInputs,
  } from '$lib/project-state.js';
  import { pluralizeRu } from '$lib/utils/i18n.js';
  // Phase 1.1 (SSOT): unit label resolution через shared service.
  import { unitLabelFor as unitLabel } from '$lib/services/classifier-patterns.js';
  // Phase 2.1 (R3): extracted unit-cost editor presentational component.
  import UnitCostEditor from './UnitCostEditor.svelte';

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

  // Phase 2.1 (R3): editor handlers / debounce / slugify / preview moved
  // into UnitCostEditor.svelte child component (SRP). AppliedModeSummary
  // remains as orchestrator: applies modes, dispatches к editors, renders
  // channel summary list.

  /**
   * Phase 2.7: Apply same unit_cost + inflation across channels sharing
   * the same physical unit type (e.g. all «TRP» channels or all «CPM»
   * channels). Smart batch reduces friction (Audit U4).
   *
   * Stays в parent because requires `channels` list (siblings lookup) —
   * editor child только know about itself.
   *
   * @param {string} sourceChannelName Channel chosen as source of values.
   */
  function applyToSameType(sourceChannelName) {
    const sourceUc = $unitCosts?.[sourceChannelName];
    if (typeof sourceUc !== 'number' || sourceUc <= 0) return;
    const sourceLabel = unitLabel(sourceChannelName);
    const sourceInfl = $unitCostInflation?.[sourceChannelName];

    // Find sister physical channels с same unit label.
    const targets = channels
      .filter((/** @type {ChannelInfo} */ c) =>
        c.detectedType === 'physical'
        && c.name !== sourceChannelName
        && unitLabel(c.name) === sourceLabel
      )
      .map((c) => c.name);

    if (targets.length === 0) return;

    unitCosts.update((curr) => {
      const next = { ...curr };
      for (const t of targets) next[t] = sourceUc;
      return next;
    });
    if (typeof sourceInfl === 'number') {
      unitCostInflation.update((curr) => {
        const next = { ...curr };
        for (const t of targets) next[t] = sourceInfl;
        return next;
      });
    }
    // H-11 fix: copy source mode + budget input → targets вместо force='unit'.
    // Раньше: user в budget mode заполняет бюджет → click «Применить» → все
    // siblings силой переключались в unit mode с числом, которое они не вводили.
    // Now: mode передаётся как есть, plus budget value (если был) копируется.
    const sourceMode = $unitCostInputMode?.[sourceChannelName] ?? 'unit';
    unitCostInputMode.update((curr) => {
      const next = { ...curr };
      for (const t of targets) next[t] = sourceMode;
      return next;
    });
    if (sourceMode === 'budget') {
      const sourceBudget = $budgetInputs?.[sourceChannelName];
      if (typeof sourceBudget === 'number' && sourceBudget > 0) {
        budgetInputs.update((curr) => {
          const next = { ...curr };
          for (const t of targets) next[t] = sourceBudget;
          return next;
        });
      }
    }
  }

  /** Count of sister channels с same unit type as the given channel. */
  function siblingPhysicalCount(/** @type {string} */ name) {
    const label = unitLabel(name);
    return channels.filter((/** @type {ChannelInfo} */ c) =>
      c.detectedType === 'physical'
      && c.name !== name
      && unitLabel(c.name) === label
    ).length;
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
      <!-- Phase 2.1 (R3): UnitCostEditor extracted as child component.
           Parent dispatches per physical channel в ROI mode; child owns
           mode toggle / inputs / debouncing / preview rendering. -->
      <div class="uc-inputs" data-testid="uc-inputs" role="group" aria-label="Конвертация физических каналов в ₽">
        {#each channels as ch (ch.name)}
          {#if ch.detectedType === 'physical' && $analysisMode === 'roi'}
            <UnitCostEditor
              channel={ch}
              channelSum={channelSums?.[ch.name]}
              siblingCount={siblingPhysicalCount(ch.name)}
              onApplyToSameType={() => applyToSameType(ch.name)}
            />
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
  /* Phase 2.7 .uc-apply-same styling moved к UnitCostEditor.svelte (R3 extract) */

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

  /* Phase 2.1 (R3): uc-inputs container styling — children styled
     внутри UnitCostEditor.svelte component. */
  .uc-inputs {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
  }

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
