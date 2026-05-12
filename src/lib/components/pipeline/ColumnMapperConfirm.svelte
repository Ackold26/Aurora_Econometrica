<script>
  /**
   * ColumnMapperConfirm — v1.3.1 / restyled v1.3.2.
   *
   * UX audit findings: ValidateStepV13 (new derived mode flow) НЕ показывает
   * ColumnMapper drag-drop (v1.2 feature). Backend auto-detects role через
   * column_detection.py, но юзер не видит / не подтверждает.
   *
   * Этот компонент показывает **detected roles в read-only table** с возможностью
   * override через dropdown. После confirm → переход к KPISelector.
   *
   * v1.3.2 restyle: removed emoji pictograms (🎯📊🔧📅❌⚠), replaced с premium
   * tier-1 typographic system — color-coded role badges (no emoji), serif/sans
   * split, sacred-lime header accent, mono font для column identifiers.
   * Matches Aurora deliverable brand styling.
   *
   * @component ColumnMapperConfirm
   */

  const {
    columns = [],     // [{name, role, kind}]
    onConfirm,        // (mapping: Record<string, string>) => void
  } = $props();

  /** @type {Record<string, string>} */
  let overrides = $state({});

  const ROLES = /** @type {const} */ (['kpi', 'media', 'control', 'date', 'excluded']);
  /** @type {Record<string, {label: string, hint: string, tone: string}>} */
  const ROLE_META = {
    kpi:      { label: 'Целевая метрика', hint: 'KPI — что объясняем',  tone: 'gold'    },
    media:    { label: 'Медиа-канал',     hint: 'затраты или активность', tone: 'accent' },
    control:  { label: 'Контрольная',     hint: 'не-медиа фактор',        tone: 'neutral'},
    date:     { label: 'Дата',            hint: 'временной ряд',           tone: 'mono'   },
    excluded: { label: 'Не использовать', hint: 'игнорируем в модели',     tone: 'muted'  },
  };

  /**
   * Canonical role → UI vocabulary mapping. Backend column-roles.js uses
   * 6 roles (kpi/media/control/date/unused/unknown); UI displays 5
   * (kpi/media/control/date/excluded). unused/unknown/null → excluded.
   *
   * @param {string} colName
   * @returns {string}
   */
  function effectiveRole(colName) {
    if (overrides[colName] !== undefined) return overrides[colName];
    const col = columns.find((/** @type {any} */ c) => c.name === colName);
    const canonical = col?.role;
    if (canonical === 'unused' || canonical === 'unknown' || canonical == null) {
      return 'excluded';
    }
    // Защита от unknown role values (defensive — production выдаёт только canonical 6).
    if (!ROLES.includes(/** @type {any} */ (canonical))) {
      return 'excluded';
    }
    return canonical;
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
  <header class="card-header">
    <span class="kicker">ШАГ 1 ИЗ 4 · РОЛИ КОЛОНОК</span>
    <h2>Подтвердите роли</h2>
    <div class="sacred-lime" aria-hidden="true"></div>
    <p class="lead">
      Программа автоматически распознала роли колонок в данных.
      Проверьте таблицу — измените, если что-то определено неверно.
    </p>
  </header>

  <div class="summary-row">
    {#each ROLES as r}
      <div class="stat-pill tone-{ROLE_META[r].tone}" class:empty={stats[r] === 0}>
        <span class="dot" aria-hidden="true"></span>
        <span class="stat-label">{ROLE_META[r].label}</span>
        <span class="stat-value">{stats[r]}</span>
      </div>
    {/each}
  </div>

  {#if stats.kpi === 0}
    <div class="attention-banner" role="alert">
      <span class="attention-mark" aria-hidden="true"></span>
      <div class="attention-body">
        <strong>Целевая метрика не определена.</strong>
        Выберите её в таблице ниже — модель не сможет работать без целевого KPI.
      </div>
    </div>
  {/if}
  {#if stats.media === 0}
    <div class="attention-banner" role="alert">
      <span class="attention-mark" aria-hidden="true"></span>
      <div class="attention-body">
        <strong>Медиа-каналы не обнаружены.</strong>
        Без каналов модель не сможет построить декомпозицию.
      </div>
    </div>
  {/if}

  <div class="table-wrapper">
    <table>
      <thead>
        <tr>
          <th scope="col" class="th-name">Колонка</th>
          <th scope="col" class="th-kind">Тип данных</th>
          <th scope="col" class="th-role">Роль в модели</th>
        </tr>
      </thead>
      <tbody>
        {#each columns as col (col.name)}
          {@const role = effectiveRole(col.name)}
          <tr class="role-{role}">
            <td class="col-name">{col.name}</td>
            <td class="col-kind">{col.kind ?? '—'}</td>
            <td class="col-role">
              <div class="role-cell">
                <span class="role-dot tone-{ROLE_META[role].tone}" aria-hidden="true"></span>
                <select
                  value={role}
                  aria-label="Роль колонки {col.name}"
                  onchange={(e) => setOverride(col.name, /** @type {HTMLSelectElement} */ (e.target).value)}
                >
                  {#each ROLES as r}
                    <option value={r}>{ROLE_META[r].label}</option>
                  {/each}
                </select>
              </div>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <footer class="card-footer">
    <p class="footer-note">
      Все изменения применяются после подтверждения. Дальше — выбор целевого KPI.
    </p>
    <button type="button" class="btn-confirm" onclick={handleConfirm}>
      Подтвердить роли
      <span class="btn-arrow" aria-hidden="true">→</span>
    </button>
  </footer>
</div>

<style>
  .column-mapper-confirm {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 28px 32px;
    max-width: 1100px;
    margin: 0 auto;
    width: 100%;
    color: var(--text-primary);
  }

  /* ─── Header (Aurora deliverable kicker + h2 + lime) ─── */
  .card-header {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 64ch;
  }
  .kicker {
    font-family: var(--font-sans, system-ui), sans-serif;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    color: var(--gold, #c9a449);
    text-transform: uppercase;
  }
  .card-header h2 {
    margin: 0;
    font-family: var(--font-serif, Georgia), serif;
    font-size: 24px;
    font-weight: 400;
    line-height: 1.2;
    letter-spacing: -0.01em;
    color: var(--text-primary);
  }
  .sacred-lime {
    width: 48px;
    height: 2px;
    background: var(--lime, #b8e043);
    margin-top: 4px;
    margin-bottom: 4px;
  }
  .lead {
    margin: 0;
    font-size: 13px;
    line-height: 1.55;
    color: var(--text-secondary);
  }

  /* ─── Summary stat pills (no emoji, color-coded dots) ─── */
  .summary-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }
  .stat-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px 6px 10px;
    border-radius: 4px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    font-size: 11px;
    line-height: 1;
    transition: opacity 0.15s, border-color 0.15s;
  }
  .stat-pill.empty {
    opacity: 0.45;
  }
  .stat-pill .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .stat-pill.tone-gold .dot    { background: var(--gold, #c9a449); }
  .stat-pill.tone-accent .dot  { background: var(--accent-primary, #6366f1); }
  .stat-pill.tone-neutral .dot { background: var(--text-secondary, #94a3b8); }
  .stat-pill.tone-mono .dot    { background: var(--text-muted, #64748b); }
  .stat-pill.tone-muted .dot   { background: rgba(148,163,184,0.4); }
  .stat-pill .stat-label {
    color: var(--text-secondary);
    letter-spacing: 0.02em;
  }
  .stat-pill .stat-value {
    color: var(--text-primary);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    margin-left: 2px;
  }

  /* ─── Attention banner (replaces warning emoji) ─── */
  .attention-banner {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    padding: 12px 14px;
    border-left: 2px solid var(--gold, #c9a449);
    background: color-mix(in srgb, var(--gold, #c9a449) 6%, transparent);
    border-radius: 0 4px 4px 0;
  }
  .attention-mark {
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: var(--gold, #c9a449);
    margin-top: 7px;
    flex-shrink: 0;
  }
  .attention-body {
    flex: 1;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-primary);
  }
  .attention-body strong {
    font-weight: 600;
    margin-right: 4px;
  }

  /* ─── Table (premium tier-1, hairline borders) ─── */
  .table-wrapper {
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  thead th {
    text-align: left;
    padding: 10px 0 8px;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--text-muted, #64748b);
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  .th-name { width: 35%; }
  .th-kind { width: 20%; }
  .th-role { width: 45%; }

  tbody td {
    padding: 11px 0;
    border-bottom: 1px solid var(--border-faint, rgba(255,255,255,0.03));
    font-size: 13px;
    vertical-align: middle;
  }
  tbody tr:last-child td {
    border-bottom: none;
  }

  .col-name {
    font-family: var(--font-mono, 'JetBrains Mono', Consolas, monospace);
    font-size: 12.5px;
    font-weight: 500;
    color: var(--text-primary);
  }
  .col-kind {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: lowercase;
    letter-spacing: 0.02em;
  }

  /* Row tint tied к role (subtle, premium — не chrome-bright) */
  tr.role-kpi      { background: color-mix(in srgb, var(--gold, #c9a449) 4%, transparent); }
  tr.role-media    { background: color-mix(in srgb, var(--accent-primary, #6366f1) 3%, transparent); }
  tr.role-excluded { opacity: 0.5; }

  /* Role cell — dot + native select */
  .role-cell {
    display: inline-flex;
    align-items: center;
    gap: 10px;
  }
  .role-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .role-dot.tone-gold    { background: var(--gold, #c9a449); }
  .role-dot.tone-accent  { background: var(--accent-primary, #6366f1); }
  .role-dot.tone-neutral { background: var(--text-secondary, #94a3b8); }
  .role-dot.tone-mono    { background: var(--text-muted, #64748b); }
  .role-dot.tone-muted   { background: rgba(148,163,184,0.4); }

  select {
    appearance: none;
    padding: 6px 26px 6px 10px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 3px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.03));
    color: var(--text-primary);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    min-width: 200px;
    transition: border-color 0.15s, background 0.15s;
    background-image:
      linear-gradient(45deg, transparent 50%, var(--text-muted) 50%),
      linear-gradient(135deg, var(--text-muted) 50%, transparent 50%);
    background-position:
      calc(100% - 13px) 50%,
      calc(100% - 8px) 50%;
    background-size: 5px 5px, 5px 5px;
    background-repeat: no-repeat;
  }
  select:hover {
    border-color: var(--gold, #c9a449);
    background-color: color-mix(in srgb, var(--gold, #c9a449) 4%, transparent);
  }
  select:focus {
    outline: none;
    border-color: var(--gold, #c9a449);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--gold, #c9a449) 20%, transparent);
  }

  /* ─── Footer (premium CTA) ─── */
  .card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
    padding-top: 8px;
  }
  .footer-note {
    margin: 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-muted);
    font-style: italic;
    flex: 1;
    min-width: 200px;
  }
  .btn-confirm {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 11px 22px;
    border-radius: 3px;
    background: var(--text-primary);
    color: var(--bg-card, #0f172a);
    border: none;
    font: inherit;
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: 0.04em;
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
  }
  .btn-confirm:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
  }
  .btn-confirm .btn-arrow {
    font-family: var(--font-serif, Georgia), serif;
    font-size: 14px;
    transition: transform 0.15s;
  }
  .btn-confirm:hover .btn-arrow {
    transform: translateX(3px);
  }
</style>
