<script>
  /**
   * TrafficLight - validation status indicator.
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

  import { validateData } from '$lib/project-state.js';
  import { fmtNum } from '$lib/fmt.js';

  let showColumnStats = $state(false);

  // ── Inline role editor ──
  /** @type {string|null} */
  let editingCol = $state(null);
  const ROLE_OPTS = [
    { id: 'media', icon: '📺', label: 'Медиа' },
    { id: 'kpi', icon: '📈', label: 'KPI' },
    { id: 'control', icon: '🎛', label: 'Внешние' },
    { id: 'date', icon: '📅', label: 'Дата' },
    { id: 'unused', icon: '🚫', label: 'Исключить' },
  ];
  /** @param {string} colName @param {string} newRole */
  function setRole(colName, newRole) {
    const val = $validateData;
    if (!val?.result?.columns) return;
    validateData.set({
      ...val,
      result: { ...val.result, columns: val.result.columns.map(/** @param {any} c */ c => c.name === colName ? { ...c, role: newRole } : c) },
    });
    editingCol = null;
  }

  const statusConfig = {
    ok:      { icon: '●', label: 'Готово',   color: '#22c55e', bg: 'color-mix(in srgb, var(--success) 10%, transparent)',   border: 'color-mix(in srgb, var(--success) 30%, transparent)'  },
    warning: { icon: '●', label: 'Предупреждения', color: '#f59e0b', bg: 'color-mix(in srgb, var(--warning) 10%, transparent)', border: 'color-mix(in srgb, var(--warning) 30%, transparent)' },
    error:   { icon: '●', label: 'Ошибки',   color: '#ef4444', bg: 'color-mix(in srgb, var(--danger) 10%, transparent)',  border: 'color-mix(in srgb, var(--danger) 30%, transparent)'  },
  };

  let cfg = $derived(statusConfig[status] ?? statusConfig.ok);

  /** @param {any} col */
  function roleLabel(col) {
    const map = /** @type {Record<string, string>} */ ({ kpi: '📈 KPI', media: '📺 Медиа', control: '🎛 Внешние', date: '📅 Дата', unused: '🚫', unknown: '?' });
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
          <span
            class="help-icon"
            title="Ratio - соотношение числа наблюдений к числу независимых переменных (rows / (media + control)). Показывает есть ли у модели достаточно данных, чтобы надёжно оценить вклад каждого канала.&#10;&#10;Пороги:&#10;• &lt;2:1 - критически мало, модель не сойдётся&#10;• 2–4:1 - работает, но с широкими доверительными интервалами&#10;• ≥4:1 - идеал (на 1 переменную ≥4 наблюдения)&#10;• ≥10:1 - отличная надёжность&#10;&#10;Почему важно: чем меньше Ratio, тем больше шума в оценках ROI. Решения при низком Ratio: увеличить историю данных (перейти к недельным вместо месячных), исключить малозначимые каналы, объединить парные метрики."
          >?</span>
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
              <th>
                Min
                <span class="help-icon" title="Минимальное значение в столбце. Показывает нижнюю границу диапазона данных. Если Min = 0, значит столбец содержит нули (часто - периоды без активности канала).">?</span>
              </th>
              <th>
                Max
                <span class="help-icon" title="Максимальное значение в столбце. Верхняя граница диапазона. Сравнение Min/Max даёт представление о размахе значений.">?</span>
              </th>
              <th>
                Mean
                <span class="help-icon" title="Среднее арифметическое значение по столбцу. Для бюджетов - средний расход за период, для показов - среднее число контактов.">?</span>
              </th>
              <th>
                CV%
                <span class="help-icon" title="Коэффициент вариации - отношение стандартного отклонения к среднему, в процентах. CV &lt;10% - стабильный канал, 10-50% - нормальная изменчивость, &gt;50% - сильные колебания (пульсирующие кампании, запуск-пауза). Низкий CV на малом объёме данных может означать что модель не увидит эффекта канала.">?</span>
              </th>
              <th>
                Нули%
                <span class="help-icon" title="Доля строк с нулевым значением. Высокий процент нулей = канал неактивен значительную часть времени. &gt;80% - кандидат на исключение или объединение с другим каналом.">?</span>
              </th>
              <th>
                Пропуски
                <span class="help-icon" title="Количество строк с отсутствующим значением (NaN). В отличие от нулей, пропуски ломают регрессию. Программа интерполирует небольшие пробелы, при &gt;20% пропусков столбец лучше исключить.">?</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {#each columns as col}
              {#if col.stats}
                <tr class:excluded={col.role === 'unused'}>
                  <td class="col-name">{col.name}</td>
                  <td class="col-role">
                    {#if editingCol === col.name}
                      <div class="role-picker-inline">
                        {#each ROLE_OPTS as opt}
                          <button class="rp-btn" class:active={col.role === opt.id} onclick={() => setRole(col.name, opt.id)}>{opt.icon} {opt.label}</button>
                        {/each}
                        <button class="rp-btn rp-close" onclick={() => editingCol = null}>✕</button>
                      </div>
                    {:else}
                      <button class="role-click" class:unknown={!col.role || col.role === 'unknown'} onclick={() => editingCol = col.name} title="Нажмите для изменения">{roleLabel(col)}</button>
                    {/if}
                  </td>
                  <td class="mono">{fmtNum(col.stats.min)}</td>
                  <td class="mono">{fmtNum(col.stats.max)}</td>
                  <td class="mono">{fmtNum(col.stats.mean)}</td>
                  <td class="mono {cvClass(col.stats.cv)}">{fmtNum(col.stats.cv, { decimals: 1 })}%</td>
                  <td class="mono {zerosClass(col.stats.zeros_pct)}">{fmtNum(col.stats.zeros_pct, { decimals: 1 })}%</td>
                  <td class="mono {col.stats.nulls > 0 ? 'val-warn' : ''}">{fmtNum(col.stats.nulls)}</td>
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
    color: var(--text-secondary);
  }

  .file-sep {
    font-size: 10px;
    color: rgba(71, 85, 105, 0.5);
  }

  .freq {
    color: var(--text-primary);
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

  .det-chip.kpi     { background: color-mix(in srgb, var(--success) 12%, transparent);  color: var(--text-primary); border: 1px solid color-mix(in srgb, var(--success) 30%, transparent); }
  .det-chip.media   { background: color-mix(in srgb, var(--accent-primary) 12%, transparent); color: var(--text-primary); border: 1px solid color-mix(in srgb, var(--accent-primary) 30%, transparent); }
  .det-chip.control { background: rgba(168,85,247,0.12); color: var(--text-primary); border: 1px solid rgba(168,85,247,0.3); }
  .det-chip.date    { background: rgba(20,184,166,0.12); color: var(--text-primary); border: 1px solid rgba(20,184,166,0.3); }
  .det-chip.ratio   { background: rgba(71,85,105,0.15);  color: var(--text-primary); border: 1px solid rgba(71,85,105,0.3); }
  .det-chip.ratio-bad { background: color-mix(in srgb, var(--danger) 12%, transparent); color: var(--text-primary); border-color: color-mix(in srgb, var(--danger) 30%, transparent); }
  .det-chip.ratio-ok  { background: color-mix(in srgb, var(--success) 12%, transparent); color: var(--text-primary); border-color: color-mix(in srgb, var(--success) 30%, transparent); }

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
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
    color: var(--text-primary, #e2e8f0);
  }

  .issue-item.warning {
    background: color-mix(in srgb, var(--warning) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning) 25%, transparent);
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
    border-color: color-mix(in srgb, var(--accent-primary) 40%, transparent);
    background: color-mix(in srgb, var(--accent-primary) 6%, transparent);
    color: var(--text-primary);
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
    color: var(--text-secondary);
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

  tr.excluded td { opacity: 0.5; text-decoration: line-through; }

  .help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 13px;
    height: 13px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--accent-primary) 20%, transparent);
    color: var(--accent-primary);
    font-size: 9px;
    font-weight: 700;
    margin-left: 4px;
    cursor: help;
    vertical-align: middle;
    line-height: 1;
  }
  .help-icon:hover {
    background: var(--accent-primary);
    color: #fff;
  }

  .role-click {
    background: none; border: 1px solid transparent; border-radius: 4px;
    color: var(--accent-primary, #3b82f6); font-size: 10px; cursor: pointer;
    padding: 1px 6px; transition: all 0.12s;
  }
  .role-click:hover { border-color: var(--accent-primary, #3b82f6); background: color-mix(in srgb, var(--accent-primary) 8%, transparent); }
  .role-click.unknown {
    color: var(--warning, #f59e0b); border: 1px dashed var(--warning, #f59e0b);
    animation: pulse-q 2s infinite;
  }
  @keyframes pulse-q { 0%,100% { border-color: color-mix(in srgb, var(--warning) 30%, transparent); } 50% { border-color: color-mix(in srgb, var(--warning) 80%, transparent); } }

  .role-picker-inline {
    display: flex; gap: 2px; flex-wrap: wrap;
  }
  .rp-btn {
    padding: 2px 6px; border: none; border-radius: 3px;
    background: rgba(255,255,255,0.06); color: var(--text-primary, #e2e8f0);
    font-size: 10px; cursor: pointer; white-space: nowrap;
  }
  .rp-btn:hover { background: rgba(255,255,255,0.12); }
  .rp-btn.active { background: color-mix(in srgb, var(--accent-primary) 20%, transparent); }
  .rp-close { color: var(--text-muted, #64748b); }

  td.col-role { color: var(--text-secondary); }

  .val-ok   { color: var(--success, #16a34a) !important; }
  .val-warn { color: var(--warning, #d97706) !important; }
  .val-bad  { color: var(--danger, #dc2626) !important; }
</style>
