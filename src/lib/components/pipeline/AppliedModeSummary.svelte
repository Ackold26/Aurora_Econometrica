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

  import { analysisMode, expertMode } from '$lib/project-state.js';

  /**
   * @typedef {{ name: string, detectedType: 'monetary' | 'physical' }} ChannelInfo
   */

  /**
   * @type {{
   *   channels?: ChannelInfo[]
   * }}
   */
  const { channels = [] } = $props();

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
   * In ROI mode — all show as monetary (₽). In effectiveness — all as physical.
   * In mixed — show detected type.
   *
   * @param {ChannelInfo} ch
   * @returns {{ label: string, isPhysical: boolean }}
   */
  function channelLabel(ch) {
    if ($analysisMode === 'roi') {
      return { label: 'спенд в ₽', isPhysical: false };
    }
    if ($analysisMode === 'effectiveness') {
      return { label: ch.detectedType === 'physical' ? 'физ. метрика' : 'конвертируется в физ.', isPhysical: true };
    }
    // mixed — show as-is
    if (ch.detectedType === 'monetary') {
      return { label: 'спенд в ₽', isPhysical: false };
    }
    return { label: 'физ. метрика', isPhysical: true };
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

  {#if channels.length > 0}
    <ul class="channel-list" aria-label="Список каналов с типами метрик">
      {#each channels as ch (ch.name)}
        {@const meta = channelLabel(ch)}
        <li class="channel-item">
          <span class="channel-name">{ch.name}</span>
          <span class="channel-arrow" aria-hidden="true">→</span>
          <span class="channel-metric" class:metric-physical={meta.isPhysical}>
            {meta.label}
            {#if !meta.isPhysical}
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
  .check-mark {
    font-size: 11px;
    color: var(--success, #10B981);
    font-weight: 700;
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
