<script>
  /**
   * ColumnMapperConfirm — v1.3.1 hotfix.
   *
   * UX audit findings: ValidateStepV13 (new derived mode flow) НЕ показывает
   * ColumnMapper drag-drop (v1.2 feature). Backend auto-detects role через
   * column_detection.py, но юзер не видит / не подтверждает.
   *
   * Этот компонент показывает **detected roles в read-only table** с возможностью
   * override через dropdown. После confirm → переход к KPISelector.
   *
   * @component ColumnMapperConfirm
   */

  const {
    columns = [],     // [{name, role, kind}]
    onConfirm,        // (mapping: Record<string, string>) => void
  } = $props();

  /** @type {Record<string, string>} */
  let overrides = $state({});

  const ROLES = ['kpi', 'media', 'control', 'date', 'excluded'];
  /** @type {Record<string, string>} */
  const ROLE_LABELS = {
    kpi: '🎯 Целевая метрика',
    media: '📊 Медиа-канал',
    control: '🔧 Контрольная',
    date: '📅 Дата',
    excluded: '❌ Не использовать',
  };

  /**
   * @param {string} colName
   * @returns {string}
   */
  function effectiveRole(colName) {
    if (overrides[colName] !== undefined) return overrides[colName];
    const col = columns.find((/** @type {any} */ c) => c.name === colName);
    return col?.role ?? 'excluded';
  }

  /** @param {string} colName @param {string} newRole */
  function setOverride(colName, newRole) {
    overrides = { ...overrides, [colName]: newRole };
  }

  function handleConfirm() {
    /** @type {Record<string, string>} */
    const mapping = {};
    for (const col of columns) {
      mapping[col.name] = effectiveRole(col.name);
    }
    onConfirm?.(mapping);
  }

  const stats = $derived.by(() => {
    /** @type {Record<string, number>} */
    const counts = { kpi: 0, media: 0, control: 0, date: 0, excluded: 0 };
    for (const col of columns) {
      counts[effectiveRole(col.name)] = (counts[effectiveRole(col.name)] ?? 0) + 1;
    }
    return counts;
  });
</script>

<div class="column-mapper-confirm">
  <header>
    <h3>Подтвердите роли колонок</h3>
    <p>
      Программа автоматически распознала роли колонок в ваших данных.
      Проверьте таблицу — измените, если что-то определено неверно.
    </p>
  </header>

  <div class="summary-row">
    <span class="stat stat-kpi">🎯 KPI: <strong>{stats.kpi}</strong></span>
    <span class="stat stat-media">📊 Каналы: <strong>{stats.media}</strong></span>
    <span class="stat stat-control">🔧 Контроль: <strong>{stats.control}</strong></span>
    <span class="stat stat-date">📅 Дата: <strong>{stats.date}</strong></span>
    <span class="stat stat-excluded">❌ Не используется: <strong>{stats.excluded}</strong></span>
  </div>

  {#if stats.kpi === 0}
    <div class="warning-banner">
      ⚠ KPI не определён. Выберите целевую метрику (выручка / продажи в штуках / лиды) в таблице ниже.
    </div>
  {/if}
  {#if stats.media === 0}
    <div class="warning-banner">
      ⚠ Медиа-каналы не обнаружены. Без каналов модель не сможет построить декомпозицию.
    </div>
  {/if}

  <div class="table-wrapper">
    <table>
      <thead>
        <tr>
          <th>Колонка</th>
          <th>Тип данных</th>
          <th>Роль (определено / можно изменить)</th>
        </tr>
      </thead>
      <tbody>
        {#each columns as col (col.name)}
          {@const role = effectiveRole(col.name)}
          <tr class="role-{role}">
            <td class="col-name">{col.name}</td>
            <td class="col-kind">{col.kind ?? '—'}</td>
            <td>
              <select
                value={role}
                onchange={(e) => setOverride(col.name, /** @type {HTMLSelectElement} */ (e.target).value)}
              >
                {#each ROLES as r}
                  <option value={r}>{ROLE_LABELS[r]}</option>
                {/each}
              </select>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <footer>
    <button type="button" class="btn-primary" onclick={handleConfirm}>
      Подтвердить роли →
    </button>
  </footer>
</div>

<style>
  .column-mapper-confirm {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 20px 24px;
    max-width: 1100px;
    margin: 0 auto;
    width: 100%;
  }
  header h3 {
    margin: 0 0 6px;
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
  }
  header p {
    margin: 0;
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.5;
  }
  .summary-row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    font-size: 12px;
    color: var(--text-secondary);
  }
  .stat {
    padding: 6px 12px;
    border-radius: 999px;
    background: var(--bg-surface-quiet);
    border: 1px solid var(--border-subtle);
  }
  .stat strong { color: var(--text-primary); font-weight: 600; }
  .warning-banner {
    padding: 10px 12px;
    background: color-mix(in srgb, var(--warning, #fbbf24) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #fbbf24) 30%, transparent);
    border-radius: 6px;
    font-size: 12px;
    color: var(--warning, #fbbf24);
  }
  .table-wrapper {
    overflow-x: auto;
    border-radius: 10px;
    border: 1px solid var(--border);
  }
  table { width: 100%; border-collapse: collapse; }
  th {
    text-align: left;
    padding: 10px 12px;
    background: var(--bg-surface-quiet);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    font-weight: 700;
    border-bottom: 1px solid var(--border);
  }
  td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-subtle);
    font-size: 13px;
    vertical-align: middle;
  }
  tr:last-child td { border-bottom: none; }
  .col-name { font-weight: 600; color: var(--text-primary); }
  .col-kind { color: var(--text-muted); font-size: 12px; }
  tr.role-kpi { background: color-mix(in srgb, var(--accent-primary) 6%, transparent); }
  tr.role-media { background: color-mix(in srgb, var(--success, #4ade80) 4%, transparent); }
  tr.role-excluded { opacity: 0.5; }
  select {
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 12px;
    font: inherit;
    cursor: pointer;
    min-width: 200px;
  }
  footer {
    display: flex;
    justify-content: flex-end;
    margin-top: 4px;
  }
  .btn-primary {
    padding: 10px 20px;
    border-radius: 8px;
    background: var(--accent-primary);
    color: #fff;
    border: 1px solid var(--accent-primary);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    font: inherit;
  }
</style>
