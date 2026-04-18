<script>
  /**
   * Data table component for Econometrica.
   * Modes: 'preview' (read-only data overview) | 'scenario' (comparison table).
   *
   * @component DataTable
   */

  /**
   * @type {{
   *   mode?: 'preview' | 'scenario',
   *   headers?: string[],
   *   rows?: any[][],
   *   columns?: any[],
   *   highlightColumn?: string,
   *   title?: string,
   *   emptyMessage?: string,
   * }}
   */
  let {
    mode = 'preview',
    headers = [],
    rows = [],
    columns = [],
    highlightColumn = '',
    title = '',
    emptyMessage = 'Нет данных',
  } = $props();

  /** For preview mode: build from columns (validation result) */
  let previewHeaders = $derived(
    mode === 'preview' && columns.length
      ? ['Столбец', 'Тип', 'Min', 'Max', 'Mean', 'Нули %']
      : headers
  );

  /** @type {any[][]} */
  let previewRows = $derived(
    mode === 'preview' && columns.length
      ? columns.map(/** @param {any} c */ (c) => [
          c.name,
          c.role === 'kpi' ? '📈 KPI' : c.role === 'media' ? '📺 Медиа' : c.role === 'control' ? '🎛 Контроль' : c.role === 'date' ? '📅 Дата' : '—',
          c.stats?.min ?? '—',
          c.stats?.max ?? '—',
          c.stats?.mean ?? '—',
          c.stats?.zeros_pct != null ? `${c.stats.zeros_pct}%` : '—',
        ])
      : rows
  );

  let displayHeaders = $derived(previewHeaders);
  let displayRows = $derived(previewRows);

  /**
   * Format a cell value: numbers get thousand separators (display only).
   * @param {any} val
   * @returns {string}
   */
  function fmt(val) {
    if (val === null || val === undefined || val === '—') return '—';
    const n = typeof val === 'number' ? val : Number(val);
    if (!isNaN(n) && String(val).trim() !== '') {
      // Integer: no decimals; float: up to 2 decimals, trim trailing zeros
      const isInt = Number.isInteger(n) || (typeof val === 'string' && !String(val).includes('.'));
      return new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: 0,
        maximumFractionDigits: isInt ? 0 : 2,
      }).format(n);
    }
    return String(val);
  }
</script>

{#if title}
  <h4 class="table-title">{title}</h4>
{/if}

{#if displayRows.length === 0}
  <div class="table-empty">{emptyMessage}</div>
{:else}
  <div class="table-wrapper">
    <table class="data-table" class:scenario={mode === 'scenario'}>
      <thead>
        <tr>
          {#each displayHeaders as h, i}
            <th class:highlight={h === highlightColumn}>{h}</th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each displayRows as row}
          <tr>
            {#each row as cell, i}
              <td
                class:label={i === 0}
                class:highlight={displayHeaders[i] === highlightColumn}
                class:positive={typeof cell === 'string' && cell.startsWith('+')}
                class:negative={typeof cell === 'string' && cell.startsWith('-')}
                class:numeric={typeof cell === 'number' || (typeof cell === 'string' && !isNaN(Number(cell)) && cell.trim() !== '')}
              >
                {fmt(cell)}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .table-title {
    margin: 0 0 8px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }

  .table-empty {
    padding: 24px;
    text-align: center;
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
  }

  .table-wrapper {
    overflow-x: auto;
    border-radius: 8px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
  }

  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }

  th {
    padding: 8px 10px;
    text-align: left;
    background: rgba(0,0,0,0.3);
    color: var(--text-secondary, #94a3b8);
    font-weight: 500;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    white-space: nowrap;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }

  td {
    padding: 6px 10px;
    color: var(--text-primary, #e2e8f0);
    border-bottom: 1px solid rgba(255,255,255,0.03);
    white-space: nowrap;
  }

  td.label {
    font-weight: 500;
    color: var(--text-primary, #e2e8f0);
  }

  .highlight {
    background: rgba(59, 130, 246, 0.08);
  }

  td.positive { color: var(--success, #22c55e); }
  td.negative { color: var(--error, #ef4444); }
  td.numeric { text-align: right; font-variant-numeric: tabular-nums; font-size: 11.5px; }

  tr:hover td {
    background: rgba(255,255,255,0.03);
  }

  /* Scenario mode: wider cells, bolder values */
  .scenario td {
    font-size: 13px;
    padding: 8px 12px;
  }

  .scenario th {
    font-size: 12px;
    padding: 10px 12px;
  }

  .table-wrapper::-webkit-scrollbar { height: 4px; }
  .table-wrapper::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 2px; }
</style>
