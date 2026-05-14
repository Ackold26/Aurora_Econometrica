<script>
  /**
   * StepMediaConfirm — Wizard Step 3: confirm media input types (F3 factor).
   *
   * Per WIZARD_FLOW_v2_FINAL.md §2.3:
   *   - Table layout of detected channels with auto-detected input type + confidence
   *   - Best-practice warnings below with severity badges
   *   - Mode preview block: Все в ₽ / Все в физике / Смешанный (Expert only)
   *   - Silent auto-confirm if all channels in same unit AND no warnings
   *
   * @component StepMediaConfirm
   */

  import { CheckCircle, AlertTriangle, Info, ChevronDown, ChevronRight } from 'lucide-svelte';
  import { analysisMode, expertMode, perChannelInput } from '$lib/project-state.js';

  /**
   * @typedef {{
   *   name: string,
   *   detectedType: 'monetary' | 'physical',
   *   metric: string,
   *   confidence: number,
   *   format?: string
   * }} Channel
   */

  /**
   * @typedef {{
   *   channel: string,
   *   message: string,
   *   severity: 'info' | 'warn'
   * }} BestPracticeWarning
   */

  /**
   * @type {{
   *   channels?: Channel[],
   *   bestPracticeWarnings?: BestPracticeWarning[],
   *   onConfirm?: ((perChannelInput: Record<string, 'monetary' | 'physical'>) => void) | null
   * }}
   */
  const {
    channels = [],
    bestPracticeWarnings = [],
    onConfirm = null,
  } = $props();

  // ─── Silent auto-confirm check ───────────────────────────────────────────

  /**
   * True when all channels share the same detected type AND no warnings exist.
   * Per §2.3: «Silent auto-confirm if all channels in one unit AND no warnings».
   * @type {boolean}
   */
  const canSilentConfirm = $derived.by(() => {
    if (bestPracticeWarnings.length > 0) return false;
    if (channels.length === 0) return false;
    const first = channels[0].detectedType;
    return channels.every(c => c.detectedType === first);
  });

  /** @type {'monetary' | 'physical' | null} */
  const silentMode = $derived(
    canSilentConfirm
      ? channels[0]?.detectedType ?? 'monetary'
      : null
  );

  // ─── Local state ──────────────────────────────────────────────────────────

  /**
   * Per-channel override state. v2.0.0 audit fix (Frontend C2):
   * was `$state(Object.fromEntries(...channels))` — captured prop ONCE at mount.
   * If parent updates channels prop after mount, stale data. Now reactive via $effect.
   * @type {Record<string, 'monetary' | 'physical'>}
   */
  let channelOverrides = $state(/** @type {Record<string, 'monetary' | 'physical'>} */ ({}));
  $effect(() => {
    channelOverrides = Object.fromEntries(channels.map(c => [c.name, c.detectedType]));
  });

  /**
   * Currently open channel dropdown.
   * @type {string | null}
   */
  let openDropdown = $state(null);

  /**
   * Selected bulk mode radio.
   * @type {'monetary' | 'physical' | 'mixed'}
   */
  let bulkMode = $state(
    /** @returns {'monetary' | 'physical' | 'mixed'} */
    function initBulkMode() {
      if (silentMode) return silentMode;
      // Default recommendation based on data: majority wins
      const monetary = channels.filter(c => c.detectedType === 'monetary').length;
      const physical = channels.filter(c => c.detectedType === 'physical').length;
      if (physical > monetary) return 'physical';
      return 'monetary';
    }()
  );

  /** Whether user has confirmed */
  let confirmed = $state(false);

  // ─── Derived ─────────────────────────────────────────────────────────────

  /**
   * Current configuration description.
   * @type {string}
   */
  const configDescription = $derived.by(() => {
    const monetary = Object.values(channelOverrides).filter(v => v === 'monetary').length;
    const physical = Object.values(channelOverrides).filter(v => v === 'physical').length;
    if (monetary === channels.length) return 'Все каналы в ₽';
    if (physical === channels.length) return 'Все каналы в физических метриках';
    return `Смешанная (${monetary} канал${monetary !== 1 ? 'а' : ''} в ₽ + ${physical} физика)`;
  });

  /**
   * Recommended mode label.
   * @type {string}
   */
  const recommendedMode = $derived.by(() => {
    const physical = channels.filter(c => c.detectedType === 'physical').length;
    const monetary = channels.filter(c => c.detectedType === 'monetary').length;
    if (physical > monetary) return 'режим Эффективности (физические метрики)';
    if (monetary >= physical) return 'ROI режим (₽)';
    return 'режим Эффективности';
  });

  /**
   * Confidence badge tone.
   * @param {number} conf
   * @returns {'high' | 'med' | 'low'}
   */
  function confTone(conf) {
    if (conf >= 0.9) return 'high';
    if (conf >= 0.7) return 'med';
    return 'low';
  }

  /**
   * Human-readable detected type label.
   * @param {'monetary' | 'physical'} type
   * @param {string} metric
   */
  function typeLabel(type, metric) {
    if (type === 'monetary') return `Бюджет в ₽`;
    return `${metric} (физика)`;
  }

  // ─── Handlers ────────────────────────────────────────────────────────────

  /**
   * Apply bulk mode: set all channels to same type.
   * @param {'monetary' | 'physical' | 'mixed'} mode
   */
  function applyBulkMode(mode) {
    bulkMode = mode;
    if (mode === 'monetary') {
      channelOverrides = Object.fromEntries(channels.map(c => [c.name, 'monetary']));
    } else if (mode === 'physical') {
      channelOverrides = Object.fromEntries(channels.map(c => [c.name, 'physical']));
    }
    // 'mixed' keeps individual overrides as-is
  }

  /**
   * Override a single channel's type.
   * @param {string} channelName
   * @param {'monetary' | 'physical'} newType
   */
  function setChannelType(channelName, newType) {
    channelOverrides = { ...channelOverrides, [channelName]: newType };
    // If all channels now in same type, update bulkMode
    const allMonetary = Object.values(channelOverrides).every(v => v === 'monetary');
    const allPhysical = Object.values(channelOverrides).every(v => v === 'physical');
    if (allMonetary) bulkMode = 'monetary';
    else if (allPhysical) bulkMode = 'physical';
    else bulkMode = 'mixed';
    openDropdown = null;
  }

  /** Confirm and emit */
  function handleConfirm() {
    confirmed = true;
    // Sync to analysisMode store
    if (bulkMode === 'monetary') analysisMode.set('roi');
    else if (bulkMode === 'physical') analysisMode.set('effectiveness');
    else analysisMode.set('mixed');
    // Sync perChannelInput store
    perChannelInput.set(channelOverrides);
    onConfirm?.(channelOverrides);
  }

  /**
   * Toggle a channel dropdown open/close.
   * @param {string} name
   */
  function toggleDropdown(name) {
    openDropdown = openDropdown === name ? null : name;
  }
</script>

<div class="step-media-confirm">
  <header class="intro">
    <h2>Подтвердите медиа-входы</h2>
    <p class="lead">
      Программа определила единицы каждого канала. Проверьте и при необходимости скорректируйте.
    </p>
  </header>

  <!-- ─── Silent auto-confirm banner ─────────────────────────────────────── -->
  {#if canSilentConfirm && !confirmed}
    <div class="silent-banner">
      <CheckCircle size={20} strokeWidth={1.5} />
      <span>
        Все каналы в одном формате ({silentMode === 'monetary' ? '₽' : 'физические метрики'}) — подтверждение автоматически.
      </span>
      <button type="button" class="btn btn-auto" onclick={handleConfirm}>
        Подтвердить <ChevronRight size={14} />
      </button>
    </div>
  {/if}

  <!-- ─── Channel table ──────────────────────────────────────────────────── -->
  {#if channels.length > 0}
    <div class="channel-table-wrap">
      <table class="channel-table">
        <thead>
          <tr>
            <th class="col-channel">Канал</th>
            <th class="col-detected">Auto-detected</th>
            <th class="col-confidence">Уверенность</th>
            <th class="col-action">Тип</th>
          </tr>
        </thead>
        <tbody>
          {#each channels as ch (ch.name)}
            {@const override = channelOverrides[ch.name] ?? ch.detectedType}
            <tr class="channel-row" class:row-changed={override !== ch.detectedType}>
              <td class="col-channel">
                <span class="channel-name">{ch.name}</span>
              </td>
              <td class="col-detected">
                <span class="detected-label">{typeLabel(ch.detectedType, ch.metric)}</span>
              </td>
              <td class="col-confidence">
                <span class="conf-badge conf-{confTone(ch.confidence)}">
                  {Math.round(ch.confidence * 100)}%
                </span>
              </td>
              <td class="col-action">
                <div class="dropdown-wrap">
                  <button
                    type="button"
                    class="dropdown-trigger"
                    class:changed={override !== ch.detectedType}
                    onclick={() => toggleDropdown(ch.name)}
                    aria-expanded={openDropdown === ch.name}
                    aria-haspopup="listbox"
                  >
                    <span class="type-tag type-{override}">
                      {override === 'monetary' ? '₽ рубли' : 'Физика'}
                    </span>
                    <ChevronDown size={12} />
                  </button>
                  {#if openDropdown === ch.name}
                    <div class="dropdown-menu" role="listbox">
                      <button
                        type="button"
                        class="dropdown-item"
                        class:item-active={override === 'monetary'}
                        role="option"
                        aria-selected={override === 'monetary'}
                        onclick={() => setChannelType(ch.name, 'monetary')}
                      >
                        ₽ Бюджет в рублях
                      </button>
                      <button
                        type="button"
                        class="dropdown-item"
                        class:item-active={override === 'physical'}
                        role="option"
                        aria-selected={override === 'physical'}
                        onclick={() => setChannelType(ch.name, 'physical')}
                      >
                        Физическая метрика ({ch.metric})
                      </button>
                    </div>
                  {/if}
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="no-channels">
      <Info size={16} strokeWidth={1.5} />
      <span>Медиа-каналы не обнаружены. Убедитесь, что данные содержат колонки с рекламными активностями.</span>
    </div>
  {/if}

  <!-- ─── Best-practice warnings ─────────────────────────────────────────── -->
  {#if bestPracticeWarnings.length > 0}
    <div class="warnings-section">
      <p class="warnings-title">Рекомендации по метрикам</p>
      <div class="warnings-list">
        {#each bestPracticeWarnings as w (w.channel + w.message)}
          <div class="warning-item sev-{w.severity}">
            {#if w.severity === 'warn'}
              <AlertTriangle size={13} strokeWidth={1.5} />
            {:else}
              <Info size={13} strokeWidth={1.5} />
            {/if}
            <div class="warning-body">
              {#if w.channel}
                <span class="warning-channel">{w.channel}:</span>
              {/if}
              <span class="warning-text">{w.message}</span>
              <span class="sev-badge sev-badge-{w.severity}">
                {w.severity === 'warn' ? 'рекомендация' : 'инфо'}
              </span>
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- ─── Mode preview + bulk selection ─────────────────────────────────── -->
  {#if channels.length > 0}
    <div class="mode-preview">
      <div class="mode-preview-header">
        <p class="mode-current">
          <strong>Текущая конфигурация:</strong> {configDescription}
        </p>
        <p class="mode-suggestion">
          Программа предлагает: <em>{recommendedMode}</em>
        </p>
      </div>

      <div class="bulk-options" role="radiogroup" aria-label="Выбор режима для всех каналов">
        <p class="bulk-label">Применить для всех каналов:</p>

        <label class="bulk-radio" class:bulk-selected={bulkMode === 'monetary'}>
          <input
            type="radio"
            name="bulk_mode"
            value="monetary"
            checked={bulkMode === 'monetary'}
            onchange={() => applyBulkMode('monetary')}
            class="sr-only"
          />
          <span class="radio-dot" aria-hidden="true"></span>
          <div class="bulk-radio-body">
            <span class="bulk-radio-title">Все каналы в ₽</span>
            <span class="bulk-radio-sub">Требует пересчёта TRP/OTS через стоимость пункта</span>
          </div>
        </label>

        <label class="bulk-radio" class:bulk-selected={bulkMode === 'physical'}>
          <input
            type="radio"
            name="bulk_mode"
            value="physical"
            checked={bulkMode === 'physical'}
            onchange={() => applyBulkMode('physical')}
            class="sr-only"
          />
          <span class="radio-dot" aria-hidden="true"></span>
          <div class="bulk-radio-body">
            <span class="bulk-radio-title">Все каналы в физических метриках</span>
            <span class="bulk-radio-sub">Эффективность — TRP, показы, клики. Рекомендовано при смешанных данных.</span>
          </div>
        </label>

        <label
          class="bulk-radio"
          class:bulk-selected={bulkMode === 'mixed'}
          class:bulk-disabled={!$expertMode}
          title={!$expertMode ? 'Доступно только в Expert mode' : ''}
        >
          <input
            type="radio"
            name="bulk_mode"
            value="mixed"
            checked={bulkMode === 'mixed'}
            disabled={!$expertMode}
            onchange={() => applyBulkMode('mixed')}
            class="sr-only"
          />
          <span class="radio-dot" aria-hidden="true"></span>
          <div class="bulk-radio-body">
            <span class="bulk-radio-title">
              Оставить смешанным
              <span class="expert-tag">EXPERT</span>
            </span>
            <span class="bulk-radio-sub">
              {#if $expertMode}
                Per-channel выбор выше. Требует ставок конверсии для физ. каналов.
              {:else}
                Включите Expert mode в настройках для доступа к этой опции.
              {/if}
            </span>
          </div>
        </label>
      </div>
    </div>
  {/if}

  <!-- ─── Confirm row ────────────────────────────────────────────────────── -->
  {#if channels.length > 0 && !confirmed}
    <div class="confirm-row">
      <button type="button" class="btn btn-confirm" onclick={handleConfirm}>
        Подтвердить конфигурацию <ChevronRight size={15} />
      </button>
      {#if bulkMode === 'mixed' && !$expertMode}
        <span class="confirm-note">Включите Expert mode для смешанного режима</span>
      {/if}
    </div>
  {:else if confirmed}
    <div class="confirmed-banner">
      <CheckCircle size={16} strokeWidth={1.5} />
      <span>Конфигурация каналов подтверждена ✓</span>
    </div>
  {/if}
</div>

<style>
  .step-media-confirm {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px 24px;
  }

  /* ─── Header ─── */
  .intro h2 {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0 0 4px;
    letter-spacing: -0.01em;
  }
  .lead {
    font-size: 12.5px;
    color: var(--text-secondary);
    margin: 0;
    line-height: 1.5;
  }

  /* ─── Silent banner ─── */
  .silent-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    background: color-mix(in srgb, var(--success, #22C55E) 7%, var(--bg-secondary, #141420));
    border: 1px solid color-mix(in srgb, var(--success, #22C55E) 30%, transparent);
    border-radius: 8px;
    font-size: 12.5px;
    color: var(--text-secondary);
  }
  .silent-banner > :global(svg) { color: var(--success, #22C55E); flex-shrink: 0; }
  .silent-banner > span { flex: 1; }

  /* ─── Channel table ─── */
  .channel-table-wrap {
    overflow-x: auto;
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: 9px;
  }
  .channel-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .channel-table thead {
    background: var(--bg-secondary, #141420);
  }
  .channel-table th {
    padding: 9px 14px;
    text-align: left;
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted, #7A7A90);
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    white-space: nowrap;
  }
  .channel-table td {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.04));
    vertical-align: middle;
  }
  .channel-row:last-child td { border-bottom: none; }
  .channel-row:hover { background: color-mix(in srgb, var(--accent-primary) 3%, transparent); }
  .channel-row.row-changed { background: color-mix(in srgb, var(--warning, #F59E0B) 4%, transparent); }

  .channel-name {
    font-weight: 700;
    color: var(--text-primary);
    font-size: 13.5px;
  }
  .detected-label {
    font-size: 12.5px;
    color: var(--text-secondary);
  }

  .conf-badge {
    font-size: 10px;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 4px;
  }
  .conf-high {
    background: color-mix(in srgb, var(--success, #22C55E) 15%, transparent);
    color: var(--success, #22C55E);
  }
  .conf-med {
    background: color-mix(in srgb, var(--warning, #F59E0B) 12%, transparent);
    color: var(--warning, #F59E0B);
  }
  .conf-low {
    background: color-mix(in srgb, var(--danger, #EF4444) 12%, transparent);
    color: var(--danger, #EF4444);
  }

  /* ─── Dropdown ─── */
  .dropdown-wrap {
    position: relative;
    display: inline-block;
  }
  .dropdown-trigger {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--bg-secondary, #141420);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: 6px;
    padding: 4px 8px;
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    color: var(--text-primary);
    transition: border-color 0.15s;
  }
  .dropdown-trigger:hover { border-color: var(--accent-primary); }
  .dropdown-trigger.changed { border-color: var(--warning, #F59E0B); }

  .type-tag {
    font-weight: 600;
    font-size: 11px;
    padding: 1px 5px;
    border-radius: 3px;
  }
  .type-monetary {
    background: color-mix(in srgb, var(--gold, #c9a449) 15%, transparent);
    color: var(--gold, #c9a449);
  }
  .type-physical {
    background: color-mix(in srgb, var(--accent-primary) 12%, transparent);
    color: var(--accent-primary);
  }

  .dropdown-menu {
    position: absolute;
    right: 0;
    top: calc(100% + 4px);
    min-width: 210px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.12));
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    z-index: 100;
    overflow: hidden;
  }
  .dropdown-item {
    display: block;
    width: 100%;
    padding: 9px 14px;
    background: none;
    border: none;
    text-align: left;
    font: inherit;
    font-size: 12.5px;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .dropdown-item:hover { background: var(--bg-secondary, #141420); color: var(--text-primary); }
  .dropdown-item.item-active {
    background: color-mix(in srgb, var(--accent-primary) 12%, transparent);
    color: var(--accent-primary);
    font-weight: 600;
  }

  /* ─── No channels ─── */
  .no-channels {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    background: var(--bg-secondary, #141420);
    border: 1px solid var(--border, rgba(255,255,255,0.06));
    border-radius: 8px;
    font-size: 12.5px;
    color: var(--text-secondary);
  }
  .no-channels > :global(svg) { flex-shrink: 0; color: var(--text-muted, #7A7A90); }

  /* ─── Warnings section ─── */
  .warnings-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .warnings-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted, #7A7A90);
    margin: 0;
  }
  .warnings-list { display: flex; flex-direction: column; gap: 5px; }
  .warning-item {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 8px 12px;
    border-radius: 7px;
    font-size: 12px;
    line-height: 1.5;
  }
  .warning-item > :global(svg) { flex-shrink: 0; margin-top: 1px; }
  .sev-warn {
    background: color-mix(in srgb, var(--warning, #F59E0B) 8%, var(--bg-secondary, #141420));
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 25%, transparent);
  }
  .sev-warn > :global(svg) { color: var(--warning, #F59E0B); }
  .sev-info {
    background: color-mix(in srgb, var(--accent-primary) 6%, var(--bg-secondary, #141420));
    border: 1px solid color-mix(in srgb, var(--accent-primary) 18%, transparent);
  }
  .sev-info > :global(svg) { color: var(--accent-primary); }
  .warning-body { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; flex: 1; }
  .warning-channel { font-weight: 700; color: var(--text-primary); }
  .warning-text { color: var(--text-secondary); }
  .sev-badge {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    padding: 1px 5px;
    border-radius: 3px;
  }
  .sev-badge-warn {
    background: color-mix(in srgb, var(--warning, #F59E0B) 15%, transparent);
    color: var(--warning, #F59E0B);
  }
  .sev-badge-info {
    background: color-mix(in srgb, var(--accent-primary) 12%, transparent);
    color: var(--accent-primary);
  }

  /* ─── Mode preview ─── */
  .mode-preview {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px 18px;
    background: var(--bg-secondary, #141420);
    border: 1px solid var(--border, rgba(255,255,255,0.07));
    border-radius: 9px;
  }
  .mode-preview-header { display: flex; flex-direction: column; gap: 3px; }
  .mode-current {
    font-size: 12.5px;
    color: var(--text-secondary);
    margin: 0;
  }
  .mode-current strong { color: var(--text-primary); }
  .mode-suggestion {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    margin: 0;
  }
  .mode-suggestion em { color: var(--gold, #c9a449); font-style: normal; }

  /* ─── Bulk radio options ─── */
  .bulk-options { display: flex; flex-direction: column; gap: 6px; }
  .bulk-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted, #7A7A90);
    margin: 0;
  }
  .bulk-radio {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 14px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.07));
    border-radius: 8px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  .bulk-radio:hover:not(.bulk-disabled) {
    border-color: var(--accent-primary);
  }
  .bulk-radio.bulk-selected {
    border-color: var(--gold, #c9a449);
    border-width: 2px;
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, var(--bg-card, #181824));
  }
  .bulk-radio.bulk-disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0,0,0,0);
    white-space: nowrap;
    border: 0;
  }
  .radio-dot {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 2px solid var(--border, rgba(255,255,255,0.2));
    flex-shrink: 0;
    margin-top: 2px;
    position: relative;
    transition: border-color 0.15s;
  }
  .bulk-radio.bulk-selected .radio-dot {
    border-color: var(--gold, #c9a449);
  }
  .bulk-radio.bulk-selected .radio-dot::after {
    content: '';
    position: absolute;
    inset: 3px;
    border-radius: 50%;
    background: var(--gold, #c9a449);
  }
  .bulk-radio-body { display: flex; flex-direction: column; gap: 2px; }
  .bulk-radio-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .bulk-radio-sub {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    line-height: 1.4;
  }
  .expert-tag {
    display: inline-flex;
    align-items: center;
    padding: 1px 5px;
    border-radius: 3px;
    background: color-mix(in srgb, var(--warning, #F59E0B) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 35%, transparent);
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: var(--warning, #F59E0B);
  }

  /* ─── Confirm row ─── */
  .confirm-row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .confirm-note {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    font-style: italic;
  }

  /* ─── Confirmed banner ─── */
  .confirmed-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--success, #22C55E) 7%, var(--bg-secondary, #141420));
    border: 1px solid color-mix(in srgb, var(--success, #22C55E) 30%, transparent);
    border-radius: 8px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--success, #22C55E);
  }

  /* ─── Buttons ─── */
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: none;
    border-radius: 7px;
    cursor: pointer;
    font: inherit;
    font-size: 13px;
    font-weight: 600;
    padding: 8px 16px;
    transition: background 0.15s, transform 0.12s;
    white-space: nowrap;
  }
  .btn-auto {
    background: var(--success, #22C55E);
    color: #0c0c14;
    flex-shrink: 0;
    padding: 6px 14px;
    font-size: 12px;
  }
  .btn-auto:hover { background: color-mix(in srgb, var(--success, #22C55E) 85%, #fff); transform: translateY(-1px); }
  .btn-confirm {
    background: var(--accent-primary);
    color: #fff;
  }
  .btn-confirm:hover { background: color-mix(in srgb, var(--accent-primary) 80%, #fff); transform: translateY(-1px); }
</style>
