<script>
  /**
   * TrafficLight — validation status indicator.
   * Displays green/yellow/red status with drill-down issues and per-column stats.
   *
   * @component TrafficLight
   */

  /**
   * @type {{
   *   status?: 'ok' | 'warning' | 'error',
   *   verdict?: string,
   *   issues?: any[],
   *   warnings?: any[],
   *   file?: {name: string, rows: number, cols: number, size_kb: number} | null,
   *   detected?: {kpi?: string[], media?: string[], control?: string[], date?: string|null, n_predictors?: number, ratio?: number, date_frequency?: string} | null,
   *   columns?: any[],
   * }}
   */
  let {
    status = 'ok',
    verdict = '',
    issues = [],
    warnings = [],
    file = null,
    detected = null,
    columns = [],
  } = $props();

  let showColumnStats = $state(false);

  const statusConfig = {
    ok:      { icon: '●', label: 'Готово',   color: '#22c55e', bg: 'rgba(34,197,94,0.10)',   border: 'rgba(34,197,94,0.30)'  },
    warning: { icon: '●', label: 'Предупреждения', color: '#f59e0b', bg: 'rgba(245,158,11,0.10)', border: 'rgba(245,158,11,0.30)' },
    error:   { icon: '●', label: 'Ошибки',   color: '#ef4444', bg: 'rgba(239,68,68,0.10)',  border: 'rgba(239,68,68,0.30)'  },
  };

  let cfg = $derived(statusConfig[status] ?? statusConfig.ok);

  /** @param {any} col */
  function roleLabel(col) {
    const map = /** @type {Record<string, string>} */ ({ kpi: '📈 KPI', media: '📺 Медиа', control: '🎛 Контроль', date: '📅 Дата', unknown: '❓' });
    return map[col.role] ?? col.role;
  }

  /** @param {number} cv */
  function cvClass(cv) {
    if (cv < 5) return 'val-bad';
    if (cv < 20) return 'val-warn';
    return 'val-ok';
  }

  /** @param {number} zeros */
  function zerosClass(zeros) {
    if (zeros > 60) return 'val-bad';
    if (zeros > 30) return 'val-warn';
    return 'val-ok';
  }

  const freqLabels = /** @type {Record<string, string>} */ ({
    daily:     'Ежедневно',
    weekly:    'Еженедельно',
    monthly:   'Ежемесячно',
    quarterly: 'Ежеквартально',
    unknown:   'Неизвестно',
  });
</script>

<div class="traffic-light" style="--status-color:{cfg.color}; --status-bg:{cfg.bg}; --status-border:{cfg.border}">

  <!-- Status indicator -->
  <div class="status-bar">
    <div class="indicator">
      <span class="dot" style="color:{cfg.color}; text-shadow: 0 0 8px {cfg.color}88">{cfg.icon}</span>
      <div class="status-text">
        <span class="status-label">{cfg.label}</span>
        <span class="verdict">{verdict}</span>
      </div>
    </div>

    {#if file}
      <div class="file-info">
        <span class="file-stat">{file.rows} строк</span>
        <span class="file-sep">·</span>
        <span class="file-stat">{file.cols} столбцов</span>
        <span class="file-sep">·</span>
        <span class="file-stat">{file.size_kb} KB</span>
        {#if detected?.date_frequency && detected.date_frequency !== 'unknown'}
          <span class="file-sep">·</span>
          <span class="file-stat freq">{freqLabels[detected.date_frequency] ?? detected.date_frequency}</span>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Detected summary -->
  {#if detected}
    <div class="detected-row">
      {#if detected.kpi?.length}
        <span class="det-chip kpi">📈 KPI: {detected.kpi.join(', ')}</span>
      {/if}
      {#if detected.media?.length}
        <span class="det-chip media">📺 Медиа: {detected.media.length} канал{detected.media.length === 1 ? '' : 'ов'}</span>
      {/if}
      {#if detected.control?.length}
        <span class="det-chip control">🎛 Контроль: {detected.control.length}</span>
      {/if}
      {#if detected.date}
        <span class="det-chip date">📅 {detected.date}</span>
      {/if}
      {#if detected.ratio}
        <span class="det-chip ratio" class:ratio-bad={detected.ratio < 4} class:ratio-ok={detected.ratio >= 10}>
          Ratio: {detected.ratio}:1
        </span>
      {/if}
    </div>
  {/if}

  <!-- Issues (critical) -->
  {#if issues.length > 0}
    <div class="issue-list">
      {#each issues as issue}
        <div class="issue-item critical">
          <span class="issue-icon">🔴</span>
          <span class="issue-msg">{issue.message}</span>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Warnings -->
  {#if warnings.length > 0}
    <div class="issue-list">
      {#each warnings as w}
        <div class="issue-item warning">
          <span class="issue-icon">🟡</span>
          <div class="issue-msg">
            {w.message}
            {#if w.action}
              <span class="issue-action">[{w.action === 'merge' ? 'объединить' : w.action === 'exclude' ? 'исключить' : w.action}]</span>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Column stats toggle -->
  {#if columns.length > 0}
    <button class="toggle-stats" onclick={() => (showColumnStats = !showColumnStats)}>
      {showColumnStats ? '▲' : '▼'} Статистика по столбцам ({columns.filter(c => c.stats).length})
    </button>

    {#if showColumnStats}
      <div class="col-stats-table">
        <table>
          <thead>
            <tr>
              <th>Столбец</th>
              <th>Роль</th>
              <th>Min</th>
              <th>Max</th>
              <th>Mean</th>
              <th title="Коэффициент вариации">CV%</th>
              <th>Нули%</th>
              <th>Пропуски</th>
            </tr>
          </thead>
          <tbody>
            {#each columns as col}
              {#if col.stats}
                <tr>
                  <td class="col-name">{col.name}</td>
                  <td class="col-role">{roleLabel(col)}</td>
                  <td>{col.stats.min}</td>
                  <td>{col.stats.max}</td>
                  <td>{col.stats.mean}</td>
                  <td class={cvClass(col.stats.cv)}>{col.stats.cv}%</td>
                  <td class={zerosClass(col.stats.zeros_pct)}>{col.stats.zeros_pct}%</td>
                  <td class={col.stats.nulls > 0 ? 'val-warn' : ''}>{col.stats.nulls}</td>
                </tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}

</div>

<style>
  .traffic-light {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
    background: var(--status-bg);
    border: 1px solid var(--status-border);
    border-radius: 12px;
  }

  /* ── Status bar ── */
  .status-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }

  .indicator {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .dot {
    font-size: 22px;
    line-height: 1;
  }

  .status-text {
    display: flex;
    flex-direction: column;
  }

  .status-label {
    font-size: 13px;
    font-weight: 700;
    color: var(--status-color);
  }

  .verdict {
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
  }

  .file-info {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .file-stat {
    font-size: 11px;
    color: rgba(148, 163, 184, 0.7);
  }

  .file-sep {
    font-size: 10px;
    color: rgba(71, 85, 105, 0.5);
  }

  .freq {
    color: #93c5fd;
    font-weight: 500;
  }

  /* ── Detected row ── */
  .detected-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .det-chip {
    font-size: 11px;
    padding: 2px 9px;
    border-radius: 20px;
    font-weight: 500;
  }

  .det-chip.kpi     { background: rgba(34,197,94,0.12);  color: var(--text-primary); border: 1px solid rgba(34,197,94,0.3); }
  .det-chip.media   { background: rgba(59,130,246,0.12); color: var(--text-primary); border: 1px solid rgba(59,130,246,0.3); }
  .det-chip.control { background: rgba(168,85,247,0.12); color: var(--text-primary); border: 1px solid rgba(168,85,247,0.3); }
  .det-chip.date    { background: rgba(20,184,166,0.12); color: var(--text-primary); border: 1px solid rgba(20,184,166,0.3); }
  .det-chip.ratio   { background: rgba(71,85,105,0.15);  color: var(--text-primary); border: 1px solid rgba(71,85,105,0.3); }
  .det-chip.ratio-bad { background: rgba(239,68,68,0.12); color: var(--text-primary); border-color: rgba(239,68,68,0.3); }
  .det-chip.ratio-ok  { background: rgba(34,197,94,0.12); color: var(--text-primary); border-color: rgba(34,197,94,0.3); }

  /* ── Issues ── */
  .issue-list {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .issue-item {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    padding: 6px 10px;
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.5;
  }

  .issue-item.critical {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.25);
    color: var(--text-primary, #e2e8f0);
  }

  .issue-item.warning {
    background: rgba(245, 158, 11, 0.08);
    border: 1px solid rgba(245, 158, 11, 0.25);
    color: var(--text-primary, #e2e8f0);
  }

  .issue-icon { flex-shrink: 0; font-size: 13px; margin-top: 1px; }
  .issue-msg  { flex: 1; }
  .issue-action {
    font-size: 10px;
    margin-left: 6px;
    opacity: 0.65;
    font-style: italic;
  }

  /* ── Toggle stats ── */
  .toggle-stats {
    background: none;
    border: 1px solid rgba(71, 85, 105, 0.3);
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer;
    text-align: left;
    transition: border-color 0.15s, background 0.15s;
    width: fit-content;
  }

  .toggle-stats:hover {
    border-color: rgba(59, 130, 246, 0.4);
    background: rgba(59, 130, 246, 0.06);
    color: #93c5fd;
  }

  /* ── Column stats table ── */
  .col-stats-table {
    overflow-x: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
  }

  th {
    text-align: left;
    padding: 5px 8px;
    color: rgba(148, 163, 184, 0.6);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid rgba(71, 85, 105, 0.2);
    white-space: nowrap;
  }

  td {
    padding: 4px 8px;
    color: var(--text-secondary, #94a3b8);
    border-bottom: 1px solid rgba(71, 85, 105, 0.1);
    white-space: nowrap;
  }

  td.col-name {
    color: var(--text-primary, #e2e8f0);
    font-weight: 500;
    max-width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  td.col-role { color: rgba(148, 163, 184, 0.7); }

  .val-ok   { color: #86efac !important; }
  .val-warn { color: #fcd34d !important; }
  .val-bad  { color: #fca5a5 !important; }
</style>
