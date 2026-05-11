<script>
  /**
   * PerChannelInputSelector — v1.3.0 third sub-step of Validate (per ADR-015).
   *
   * Для каждого канала юзер выбирает: подаём в модель бюджет (₽) или физ. контакты
   * (показы / клики / GRP). Если доступна только одна метрика — radio автоматически
   * locked. Если обе доступны — юзер выбирает explicit.
   *
   * Emits onConfirm(perChannelInput) — dict {channel: 'monetary'|'physical'}.
   *
   * @component PerChannelInputSelector
   */

  /** @typedef {{
    monetary: string[],
    physical: string[],
  }} AvailableMetrics */

  const {
    channels,                   // ['tv', 'olv', 'performance', ...]
    availableMetricsByChannel,  // {channel: AvailableMetrics}
    currentSelection,           // {channel: 'monetary'|'physical'} | null
    onConfirm,                  // callback(perChannelInput)
  } = $props();

  // Initialize selection с smart defaults.
  /** @type {Record<string, string>} */
  let selection = $state(
    currentSelection
      ? { ...currentSelection }
      : Object.fromEntries(/** @type {string[]} */ (channels).map((/** @type {string} */ ch) => {
          const av = availableMetricsByChannel[ch] || { monetary: [], physical: [] };
          if (av.monetary.length > 0) return [ch, 'monetary'];
          if (av.physical.length > 0) return [ch, 'physical'];
          return [ch, 'monetary'];
        }))
  );

  /** @param {string} channel */
  function isLocked(channel) {
    const av = availableMetricsByChannel[channel] || { monetary: [], physical: [] };
    return (av.monetary.length === 0) || (av.physical.length === 0);
  }

  /** @param {string} channel @param {string} metric */
  function setMetric(channel, metric) {
    selection = { ...selection, [channel]: metric };
  }

  function handleConfirm() {
    onConfirm?.(selection);
  }
</script>

<div class="per-channel-selector">
  <header>
    <h2>Какие метрики каналов используем?</h2>
    <p class="lead">
      Для каждого канала выберите более надёжный источник данных:
      <strong>бюджет (₽)</strong> — точные деньги,
      или <strong>физические контакты</strong> (показы, клики, GRP) — точные охваты.
      Программа определит режим автоматически после вашего выбора.
      <button class="why-link" type="button">Зачем это? <span class="chevron">▾</span></button>
    </p>
  </header>

  <table class="channels-table">
    <thead>
      <tr>
        <th>Канал</th>
        <th>Доступные метрики</th>
        <th>Использовать</th>
      </tr>
    </thead>
    <tbody>
      {#each channels as ch (ch)}
        {@const av = availableMetricsByChannel[ch] || { monetary: [], physical: [] }}
        {@const locked = isLocked(ch)}
        <tr>
          <td class="channel-name">{ch}</td>
          <td class="available-metrics">
            {#if av.monetary.length > 0}
              <span class="metric-badge monetary" title={av.monetary.join(', ')}>
                ₽ {av.monetary.length === 1 ? av.monetary[0] : `${av.monetary.length} колонок`}
              </span>
            {/if}
            {#if av.physical.length > 0}
              <span class="metric-badge physical" title={av.physical.join(', ')}>
                📊 {av.physical.length === 1 ? av.physical[0] : `${av.physical.length} колонок`}
              </span>
            {/if}
            {#if av.monetary.length === 0 && av.physical.length === 0}
              <span class="missing">Колонки не найдены</span>
            {/if}
          </td>
          <td class="radio-cell">
            <label class:locked={locked && av.physical.length === 0}>
              <input
                type="radio"
                name="metric-{ch}"
                value="monetary"
                checked={selection[ch] === 'monetary'}
                disabled={av.monetary.length === 0}
                onchange={() => setMetric(ch, 'monetary')}
              />
              ₽ бюджет
            </label>
            <label class:locked={locked && av.monetary.length === 0}>
              <input
                type="radio"
                name="metric-{ch}"
                value="physical"
                checked={selection[ch] === 'physical'}
                disabled={av.physical.length === 0}
                onchange={() => setMetric(ch, 'physical')}
              />
              📊 контакты
            </label>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <footer class="actions">
    <button type="button" class="btn-primary" onclick={handleConfirm}>
      Подтвердить выбор →
    </button>
  </footer>
</div>

<style>
  .per-channel-selector {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px;
    max-width: 1100px;
    margin: 0 auto;
    width: 100%;
  }
  header h2 {
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 4px;
  }
  .lead {
    font-size: 12px;
    color: var(--text-secondary);
    margin: 0;
    line-height: 1.5;
  }
  .lead strong { color: var(--text-primary); font-weight: 600; }
  .why-link {
    background: none;
    border: none;
    color: var(--accent-primary);
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    text-decoration: underline dashed;
    padding: 0 4px;
  }
  .chevron { font-size: 9px; }

  .channels-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--bg-card);
    border-radius: var(--radius-card, 10px);
    overflow: hidden;
    border: 1px solid var(--border);
  }
  .channels-table th {
    text-align: left;
    padding: 10px 14px;
    background: var(--bg-surface-quiet);
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    font-weight: 700;
  }
  .channels-table td {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border-subtle);
    font-size: 13px;
    color: var(--text-primary);
    vertical-align: middle;
  }
  .channels-table tr:last-child td { border-bottom: none; }

  .channel-name { font-weight: 600; }
  .available-metrics { display: flex; gap: 8px; flex-wrap: wrap; }
  .metric-badge {
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-secondary);
  }
  .metric-badge.monetary {
    background: color-mix(in srgb, var(--accent-primary) 12%, transparent);
    color: var(--accent-primary);
  }
  .metric-badge.physical {
    background: color-mix(in srgb, var(--success, #4ade80) 12%, transparent);
    color: var(--success, #4ade80);
  }
  .missing { color: var(--text-muted); font-style: italic; font-size: 11px; }

  .radio-cell { display: flex; gap: 14px; }
  .radio-cell label {
    display: flex;
    gap: 6px;
    align-items: center;
    cursor: pointer;
    font-size: 12px;
    color: var(--text-secondary);
  }
  .radio-cell label.locked { color: var(--text-muted); cursor: not-allowed; }
  .radio-cell input[type="radio"]:disabled + * { color: var(--text-muted); }

  .actions {
    display: flex;
    justify-content: flex-end;
  }
  .btn-primary {
    padding: 10px 18px;
    border-radius: var(--radius-btn, 8px);
    font-size: 13px;
    font-weight: 600;
    background: var(--accent-primary);
    color: #fff;
    border: 1px solid var(--accent-primary);
    cursor: pointer;
    font: inherit;
  }
</style>
