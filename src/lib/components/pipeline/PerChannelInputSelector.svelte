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

  // v1.3.2: «Зачем это?» раскрывающаяся панель с объяснением выбора метрик.
  let whyExpanded = $state(false);

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
      <button
        class="why-link"
        type="button"
        aria-expanded={whyExpanded}
        onclick={() => (whyExpanded = !whyExpanded)}
      >Зачем это? <span class="chevron" class:open={whyExpanded}>▾</span></button>
    </p>
    {#if whyExpanded}
      <div class="why-panel" role="region" aria-label="Подробное объяснение">
        <p><strong>Выбор метрики определяет режим оценки модели:</strong></p>
        <ul>
          <li>
            <strong>Бюджет (₽)</strong> — модель посчитает ROI (return on investment): сколько рублей продаж приносит каждый рубль вложений.
            Подходит для каналов где деньги — главный input (Performance, Social Ads, OOH с фиксированной ценой).
          </li>
          <li>
            <strong>Физические контакты</strong> — модель посчитает CPU (cost per unit) и эффективность по охватам.
            Подходит для каналов где budget «грязный» (бартер, скидки, длинные контракты), но GRP/показы измеряются точно — TV, OLV, прямая реклама.
          </li>
        </ul>
        <p>
          <strong>Программа выберет режим автоматически:</strong>
        </p>
        <ul>
          <li>Все каналы → бюджет = режим <strong>ROI</strong> (monetary attribution).</li>
          <li>Все каналы → физические = режим <strong>Эффективность</strong> (share-based attribution).</li>
          <li>Смешанный выбор = режим <strong>Вручную</strong> (вы контролируете каждый канал).</li>
        </ul>
        <p class="why-tip">
          <strong>Правило:</strong> выбирайте более достоверный источник. Если бюджет канала точный — берите его.
          Если бюджет искажён бартером или скидками, но GRP/показы измеряются прозрачно — берите физический показатель.
        </p>
      </div>
    {/if}
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
        <tr class:row-monetary={selection[ch] === 'monetary'} class:row-physical={selection[ch] === 'physical'}>
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
  .why-link:hover { color: var(--gold, #c9a449); }
  .chevron {
    font-size: 9px;
    display: inline-block;
    transition: transform 0.2s;
  }
  .chevron.open { transform: rotate(180deg); }

  /* v1.3.2: «Зачем это?» раскрывающаяся панель — premium tier-1. */
  .why-panel {
    margin-top: 12px;
    padding: 14px 18px;
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, var(--bg-card, #0f172a));
    border-left: 2px solid var(--gold, #c9a449);
    border-radius: 0 6px 6px 0;
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--text-secondary);
  }
  .why-panel p { margin: 0 0 8px; }
  .why-panel p:last-child { margin-bottom: 0; }
  .why-panel ul {
    margin: 0 0 12px;
    padding-left: 18px;
  }
  .why-panel li { padding: 3px 0; }
  .why-panel strong { color: var(--text-primary); font-weight: 600; }
  .why-tip {
    margin-top: 10px !important;
    padding-top: 10px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    color: var(--text-primary);
  }

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
  /* UX audit v1.3.0: visual feedback на selected row (был только radio dot, легко промахнуться). */
  .channels-table tr.row-monetary {
    background: color-mix(in srgb, var(--accent-primary) 4%, transparent);
  }
  .channels-table tr.row-physical {
    background: color-mix(in srgb, var(--success, #4ade80) 4%, transparent);
  }
  .channels-table tbody tr:hover {
    background: color-mix(in srgb, var(--text-primary) 4%, transparent);
  }

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
  /* UX audit v1.3.0: clear disabled state (был просто muted color). */
  .radio-cell label.locked {
    color: var(--text-muted);
    cursor: not-allowed;
    opacity: 0.5;
    text-decoration: line-through;
  }
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
