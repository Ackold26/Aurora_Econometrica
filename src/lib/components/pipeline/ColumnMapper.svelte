<script>
  /**
   * ColumnMapper - HTML5 drag-drop column role assignment.
   * Shows all columns on the left, 4 drop zones on the right (KPI/Media/Control/Date).
   * Auto-populated from validator's detected roles.
   * Emits {onmappingchange} when user reassigns a column.
   *
   * @component ColumnMapper
   */

  /**
   * @type {{
   *   columns?: any[],
   *   detected?: {kpi?: string[], media?: string[], control?: string[], date?: string|null},
   *   onmappingchange?: (mapping: {kpi: string[], media: string[], control: string[], date: string|null, unknown: string[]}) => void,
   * }}
   */
  let {
    columns = [],
    detected = {},
    onmappingchange = () => {},
  } = $props();

  // ── Zones ──────────────────────────────────────────
  // v2.1.0 (rc2 retry): унифицированные термины с ColumnMapperConfirm (Nielsen MMM).
  const ZONES = [
    { id: 'kpi',     label: 'Целевая метрика',  icon: '📈', desc: 'Целевой показатель (продажи, конверсии)' },
    { id: 'media',   label: 'Медиа-канал',      icon: '📺', desc: 'Расходы, контакты, показы, цены, промо' },
    { id: 'control', label: 'Контрольная',      icon: '🎛', desc: 'Сезонность, погода, конкуренты, SOV' },
    { id: 'date',    label: 'Дата',             icon: '📅', desc: 'Столбец с датой / периодом' },
  ];

  // ── Mapping state ──────────────────────────────────
  /** @type {{kpi: string[], media: string[], control: string[], date: string|null, unknown: string[]}} */
  let mapping = $state({
    kpi: [],
    media: [],
    control: [],
    date: null,
    unknown: [],
  });

  // Init from detected props + columns[i].role (source of truth когда задано).
  //
  // BUGFIX 2026-04-27 (Validate→Model state desync): init только когда columns SET
  // изменился (новый file uploaded), не на каждый prop change. Pre-fix: $effect
  // re-ran on каждой mutation validation prop → сбрасывал mapping к initial detected
  // roles → user reassignments терялись на ConfigPanel/Model шаге.
  //
  // BUGFIX 2026-05-01 (Insights ↔ Mapper sync): hash key теперь включает roles
  // (не только names). Pre-fix: InsightsPanel «Оставить бюджет» меняла
  // columns[i].role='unused', но column SET тот же → mapping не re-init →
  // mapper продолжал показывать excluded columns в media zone. Симптом:
  // SOCIAL «Оставить бюджет» сработал, RETAIL/PERFOR/СТАТЬИ той же кнопкой
  // визуально не убирали парные метрики из левой матрицы.
  // Fix: ключ включает (name, role) пары. Init использует columns[i].role
  // как priority source, fallback к detected. role='unused' → не попадает
  // ни в одну зону (исключено).
  let lastColumnsKey = $state('');
  $effect(() => {
    if (!columns.length) return;
    // Hash now includes (name, role) pair - roles changes (incl. external
    // mutations from InsightsPanel) trigger re-init.
    const key = columns
      .map(/** @param {any} c */ (c) => `${c.name}:${c.role ?? ''}`)
      .slice().sort().join('|');
    if (lastColumnsKey === key) return;
    lastColumnsKey = key;

    /** @type {string[]} */
    const kpi = [];
    /** @type {string[]} */
    const media = [];
    /** @type {string[]} */
    const ctrl = [];
    /** @type {string|null} */
    let date = null;
    /** @type {string[]} */
    const unknown = [];

    const detectedKpi = new Set(detected?.kpi ?? []);
    const detectedMedia = new Set(detected?.media ?? []);
    const detectedCtrl = new Set(detected?.control ?? []);
    const detectedDate = detected?.date ?? null;

    for (const c of columns) {
      const role = c.role;
      // Priority: explicit column.role (user/insights mutation) → detected (server) → unknown.
      if (role === 'kpi') kpi.push(c.name);
      else if (role === 'media') media.push(c.name);
      else if (role === 'control') ctrl.push(c.name);
      else if (role === 'date') date = c.name;
      else if (role === 'unused') {
        // Excluded - не попадает ни в одну zone (УЖЕ исключён, не показываем как unknown).
        continue;
      } else if (role === 'unknown') {
        unknown.push(c.name);
      } else {
        // role не задана → fallback к detected.
        if (detectedKpi.has(c.name)) kpi.push(c.name);
        else if (detectedMedia.has(c.name)) media.push(c.name);
        else if (detectedCtrl.has(c.name)) ctrl.push(c.name);
        else if (detectedDate === c.name) date = c.name;
        else unknown.push(c.name);
      }
    }

    mapping = { kpi, media, control: ctrl, date, unknown };
  });

  // Emit on every change
  $effect(() => {
    // Snapshot to avoid proxy issues
    onmappingchange({
      kpi:     [...mapping.kpi],
      media:   [...mapping.media],
      control: [...mapping.control],
      date:    mapping.date,
      unknown: [...mapping.unknown],
    });
  });

  // ── Click-to-assign (reliable alternative to drag-drop) ──
  /** @type {string | null} */
  let selectedColumn = $state(null);

  /** @param {string} colName */
  function selectColumn(colName) {
    selectedColumn = selectedColumn === colName ? null : colName;
  }

  /** @param {string} zoneId */
  function assignToZone(zoneId) {
    if (!selectedColumn) return;
    moveColumn(selectedColumn, zoneId);
    selectedColumn = null;
  }

  // ── Drag state ─────────────────────────────────────
  /** @type {string | null} */
  let dragging = $state(null);
  /** @type {string | null} */
  let dragOver = $state(null);

  /** @param {DragEvent} e @param {string} colName */
  function onDragstart(e, colName) {
    dragging = colName;
    e.dataTransfer?.setData('text/plain', colName);
    e.dataTransfer && (e.dataTransfer.effectAllowed = 'move');
  }

  function onDragend() {
    dragging = null;
    dragOver = null;
  }

  /** @param {DragEvent} e @param {string} zoneId */
  function onZoneDragover(e, zoneId) {
    e.preventDefault();
    e.dataTransfer && (e.dataTransfer.dropEffect = 'move');
    dragOver = zoneId;
  }

  function onZoneDragleave() {
    dragOver = null;
  }

  /** @param {DragEvent} e @param {string} zoneId */
  function onZoneDrop(e, zoneId) {
    e.preventDefault();
    dragOver = null;
    const colName = e.dataTransfer?.getData('text/plain') || dragging;
    if (!colName) return;

    moveColumn(colName, zoneId);
    dragging = null;
  }

  // ── Move logic ─────────────────────────────────────
  /**
   * Remove colName from all lists in mapping.
   * @param {{kpi: string[], media: string[], control: string[], date: string|null, unknown: string[]}} m
   * @param {string} colName
   */
  function removeFromAll(m, colName) {
    m.kpi = m.kpi.filter(/** @param {string} c */ c => c !== colName);
    m.media = m.media.filter(/** @param {string} c */ c => c !== colName);
    m.control = m.control.filter(/** @param {string} c */ c => c !== colName);
    if (m.date === colName) m.date = null;
    m.unknown = m.unknown.filter(/** @param {string} c */ c => c !== colName);
  }

  /** @param {string} colName @param {string} targetZone */
  function moveColumn(colName, targetZone) {
    const m = {
      kpi:     [...mapping.kpi],
      media:   [...mapping.media],
      control: [...mapping.control],
      date:    mapping.date,
      unknown: [...mapping.unknown],
    };
    removeFromAll(m, colName);

    if (targetZone === 'kpi')     m.kpi.push(colName);
    else if (targetZone === 'media')   m.media.push(colName);
    else if (targetZone === 'control') m.control.push(colName);
    else if (targetZone === 'date') {
      // date is single - push old date to unknown if exists
      if (m.date && m.date !== colName) m.unknown.push(m.date);
      m.date = colName;
    } else {
      m.unknown.push(colName);
    }

    mapping = m;
  }

  /** @param {string} colName */
  function returnToUnassigned(colName) {
    moveColumn(colName, 'unknown');
  }

  /** Helper: get assigned zone for a column
   * @param {string} colName
   */
  function getZone(colName) {
    if (mapping.kpi.includes(colName)) return 'kpi';
    if (mapping.media.includes(colName)) return 'media';
    if (mapping.control.includes(colName)) return 'control';
    if (mapping.date === colName) return 'date';
    return 'unknown';
  }

  /** @param {any} col */
  function confidenceLabel(col) {
    if (!col.confidence) return '';
    const pct = Math.round(col.confidence * 100);
    return `${pct}%`;
  }

  /** @param {any} col */
  function confidenceClass(col) {
    if (!col.confidence) return 'conf-unknown';
    if (col.confidence >= 0.8) return 'conf-high';
    if (col.confidence >= 0.5) return 'conf-mid';
    return 'conf-low';
  }

  /** @param {any} col */
  function zerosPct(col) {
    const z = col?.stats?.zeros_pct;
    if (z == null) return null;
    // Backend (validator.py) уже возвращает значение в процентах (e.g. 25.8).
    // Округляем до целого; 0 показываем тоже - для табличного выравнивания.
    return Math.round(z);
  }

  /** @param {number} pct */
  function zerosClass(pct) {
    if (pct < 30) return 'zeros-low';
    if (pct < 70) return 'zeros-mid';
    return 'zeros-high';
  }

  // Zone items derived
  let zoneItems = $derived({
    kpi:     mapping.kpi,
    media:   mapping.media,
    control: mapping.control,
    date:    mapping.date ? [mapping.date] : [],
    unknown: mapping.unknown,
  });

  // Column meta lookup
  /** @param {string} colName */
  function colMeta(colName) {
    return columns.find(c => c.name === colName) ?? { name: colName };
  }
</script>

<div class="column-mapper">
  <header class="mapper-heading">
    <h3 class="mapper-title">Назначение ролей столбцов</h3>
    <p class="mapper-subtitle">
      Распределите столбцы по четырём ролям: <strong>Целевая метрика</strong> · <strong>Медиа-канал</strong> · <strong>Контрольная</strong> · <strong>Дата</strong>.
      Нажмите на столбец - выберите одну из ролей. Двойной клик по назначенному чипу возвращает его в неназначенные.
    </p>
  </header>

  <!-- Unassigned columns -->
  <div class="unassigned-section">
    <div class="section-header">
      <span class="section-title">Столбцы</span>
      <span class="section-hint">{selectedColumn ? `Выбрано: ${selectedColumn} - нажмите на зону ниже` : 'Нажмите на столбец, затем на нужную зону'}</span>
    </div>
    <div class="columns-list">
      {#each columns as col (col.name)}
        {@const zone = getZone(col.name)}
        {#if zone === 'unknown'}
          <div
            class="col-chip unassigned"
            class:selected={selectedColumn === col.name}
            role="button"
            tabindex="0"
            title="Нажмите для назначения роли"
            onclick={() => selectColumn(col.name)}
            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectColumn(col.name); } }}
          >
            <span class="chip-name">{col.name}</span>
            <span class="chip-dtype">{col.dtype}</span>
          </div>
          {#if selectedColumn === col.name}
            <div class="inline-role-picker">
              {#each ZONES as z}
                <button class="quick-role-btn zone-{z.id}" onclick={() => { moveColumn(col.name, z.id); selectedColumn = null; }}>
                  {z.icon} {z.label}
                </button>
              {/each}
              <button class="quick-role-btn zone-unused" onclick={() => { moveColumn(col.name, 'unknown'); selectedColumn = null; }}>
                ✕
              </button>
            </div>
          {/if}
        {:else}
          <!-- Assigned - shown in zone, greyed out here -->
          <div class="col-chip assigned" title="Назначен: {zone}">
            <span class="chip-name">{col.name}</span>
            <span class="chip-zone-badge zone-{zone}">{ZONES.find(z => z.id === zone)?.icon}</span>
          </div>
        {/if}
      {/each}

      {#if columns.length === 0}
        <p class="empty-cols">Загрузите файл на шаге Импорт</p>
      {/if}
    </div>
  </div>

  <!-- Drop zones -->
  <div class="zones-grid">
    {#each ZONES as zone (zone.id)}
      {@const items = /** @type {string[]} */ ((/** @type {Record<string, string[]>} */(zoneItems))[zone.id] ?? [])}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="zone"
        class:drag-over={dragOver === zone.id}
        class:click-target={!!selectedColumn}
        role="group"
        aria-label="Зона {zone.label}"
        onclick={() => assignToZone(zone.id)}
      >
        <div class="zone-header">
          <span class="zone-icon">{zone.icon}</span>
          <div>
            <div class="zone-label">{zone.label}</div>
            <div class="zone-desc">{zone.desc}</div>
          </div>
          <span class="zone-count">{items.length}</span>
        </div>

        <div class="zone-items">
          {#each items as name (name)}
            {@const meta = colMeta(name)}
            {@const zp = zerosPct(meta)}
            <div
              class="zone-chip"
              role="button"
              tabindex="0"
              title="Двойной клик - вернуть в неназначенные"
              ondblclick={() => returnToUnassigned(name)}
              onkeydown={(e) => { if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); returnToUnassigned(name); } }}
            >
              <span class="chip-name">{name}</span>
              <div class="chip-stats">
                <span
                  class="conf-badge {meta.confidence ? confidenceClass(meta) : 'conf-empty'}"
                  title={meta.confidence ? `Уверенность автодетекции: ${confidenceLabel(meta)}. Программа распознаёт роль по имени столбца (например, «бюджет», «показы», «продажи»). Чем выше %, тем точнее определение.` : 'Автодетекция не определила роль'}
                >{meta.confidence ? confidenceLabel(meta) : '-'}</span>
                <span
                  class="zeros-badge {zp != null ? zerosClass(zp) : 'zeros-empty'}"
                  title={zp != null ? `Доля строк с нулевым значением - ${zp}% от общего количества. <30% - канал работает регулярно. 30-70% - пульсирующая активность (всплески). >70% - разреженный канал, рекламные импульсы редки; модель плохо разделит его эффект, но отказываться не обязательно.` : 'Статистика нулей недоступна'}
                >{zp != null ? `${zp}%` : '-'}</span>
              </div>
              <button
                class="remove-btn"
                aria-label="Убрать {name}"
                onclick={() => returnToUnassigned(name)}
              >×</button>
            </div>
          {/each}

          {#if items.length === 0}
            <div class="zone-empty">Перетащите сюда</div>
          {/if}
        </div>
      </div>
    {/each}
  </div>

</div>

<style>
  .mapper-heading {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 0 4px 8px;
    border-bottom: 1px solid var(--border-subtle);
    margin-bottom: 4px;
  }
  .mapper-title {
    margin: 0;
    font-size: 15px;
    font-weight: var(--font-weight-heading, 600);
    color: var(--text-primary);
    letter-spacing: -0.005em;
  }
  .mapper-subtitle {
    margin: 0;
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.45;
  }

  .column-mapper {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  /* ── Unassigned ── */
  .unassigned-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .section-header {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }

  .section-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-secondary, #94a3b8);
  }

  .section-hint {
    font-size: 11px;
    color: var(--text-muted);
    font-style: italic;
  }

  .columns-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 10px;
    background: var(--bg-tertiary, rgba(15, 23, 42, 0.35));
    border-radius: 10px;
    min-height: 46px;
    border: 1px solid var(--border, rgba(71, 85, 105, 0.25));
  }

  .empty-cols {
    font-size: 12px;
    color: var(--text-muted);
    margin: 0;
    align-self: center;
    font-style: italic;
  }

  /* ── Chips ── */
  .col-chip {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 12px;
    cursor: grab;
    user-select: none;
    transition: opacity 0.15s, transform 0.12s;
  }

  .col-chip.unassigned {
    background: var(--bg-card, color-mix(in srgb, var(--accent-primary) 10%, transparent));
    border: 1px solid var(--border, color-mix(in srgb, var(--accent-primary) 25%, transparent));
    color: var(--text-primary);
  }

  .col-chip.unassigned:hover {
    background: var(--bg-card-hover, color-mix(in srgb, var(--accent-primary) 18%, transparent));
    border-color: var(--accent-primary, color-mix(in srgb, var(--accent-primary) 45%, transparent));
  }

  .col-chip.selected {
    background: color-mix(in srgb, var(--success) 20%, transparent);
    border-color: color-mix(in srgb, var(--success) 60%, transparent);
    color: #4ade80;
    box-shadow: 0 0 8px color-mix(in srgb, var(--success) 25%, transparent);
  }

  .inline-role-picker {
    display: flex;
    gap: 3px;
    margin-top: -2px;
    margin-bottom: 4px;
  }
  .quick-role-btn {
    padding: 3px 8px;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 5px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    color: var(--text-primary, #e2e8f0);
    font-size: 10px;
    cursor: pointer;
    transition: all 0.12s;
    white-space: nowrap;
  }
  .quick-role-btn:hover { background: rgba(255,255,255,0.1); }
  .quick-role-btn.zone-kpi:hover { border-color: #22c55e; background: color-mix(in srgb, var(--success) 12%, transparent); }
  .quick-role-btn.zone-media:hover { border-color: #3b82f6; background: color-mix(in srgb, var(--accent-primary) 12%, transparent); }
  .quick-role-btn.zone-control:hover { border-color: #a855f7; background: rgba(168,85,247,0.12); }
  .quick-role-btn.zone-date:hover { border-color: #14b8a6; background: rgba(20,184,166,0.12); }
  .quick-role-btn.zone-unused { color: var(--text-muted, #64748b); }

  .col-chip.assigned {
    background: var(--bg-secondary, rgba(71, 85, 105, 0.2));
    border: 1px solid var(--border-subtle, rgba(71, 85, 105, 0.25));
    color: var(--text-secondary);
    cursor: default;
  }

  .col-chip.dragging {
    opacity: 0.45;
    transform: scale(0.95);
    cursor: grabbing;
  }

  .chip-name {
    font-weight: 500;
  }

  .chip-dtype {
    font-size: 10px;
    opacity: 0.6;
  }

  .chip-zone-badge {
    font-size: 12px;
  }

  /* ── Zones grid ── */
  .zones-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }

  .zone {
    background: var(--bg-card, rgba(15, 23, 42, 0.4));
    border: 1.5px dashed var(--border, rgba(71, 85, 105, 0.35));
    border-radius: 12px;
    padding: 12px;
    min-height: 100px;
    transition: border-color 0.15s, background 0.15s;
  }

  .zone.click-target {
    border-color: color-mix(in srgb, var(--success) 50%, transparent);
    cursor: pointer;
    animation: zone-pulse 1.5s ease-in-out infinite;
  }
  @keyframes zone-pulse { 0%,100% { border-color: color-mix(in srgb, var(--success) 30%, transparent); } 50% { border-color: color-mix(in srgb, var(--success) 70%, transparent); } }
  .zone.click-target:hover {
    background: color-mix(in srgb, var(--success) 6%, transparent);
    border-color: color-mix(in srgb, var(--success) 80%, transparent);
  }

  .zone.drag-over {
    border-color: #3b82f6;
    background: color-mix(in srgb, var(--accent-primary) 8%, transparent);
    border-style: solid;
  }

  .zone-header {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 10px;
  }

  .zone-icon {
    font-size: 18px;
    line-height: 1;
    flex-shrink: 0;
    margin-top: 1px;
  }

  .zone-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }

  .zone-desc {
    font-size: 10px;
    color: var(--text-secondary);
    margin-top: 1px;
  }

  .zone-count {
    margin-left: auto;
    font-size: 11px;
    font-weight: 700;
    color: var(--text-muted);
    background: var(--bg-tertiary, rgba(71, 85, 105, 0.25));
    border-radius: 10px;
    padding: 1px 7px;
  }

  .zone-items {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .zone-empty {
    font-size: 11px;
    color: var(--text-muted);
    text-align: center;
    padding: 8px 0;
    font-style: italic;
  }

  /* ── Zone chips ── */
  .zone-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    background: rgba(30, 41, 59, 0.6);
    border: 1px solid rgba(71, 85, 105, 0.3);
    border-radius: 8px;
    font-size: 12px;
    color: var(--text-primary, #e2e8f0);
    cursor: grab;
    user-select: none;
    transition: background 0.12s;
  }

  .zone-chip:hover {
    background: rgba(51, 65, 85, 0.6);
  }

  .zone-chip.dragging {
    opacity: 0.4;
    cursor: grabbing;
  }

  .zone-chip .chip-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .remove-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
    border-radius: 3px;
    flex-shrink: 0;
    transition: color 0.12s;
  }

  .remove-btn:hover {
    color: #ef4444;
  }

  /* ── Confidence badge ── */
  .conf-badge {
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 10px;
    font-weight: 600;
    flex-shrink: 0;
  }

  .conf-high {
    background: color-mix(in srgb, var(--success) 15%, transparent);
    color: #86efac;
    border: 1px solid color-mix(in srgb, var(--success) 25%, transparent);
  }

  .conf-mid {
    background: rgba(251, 191, 36, 0.12);
    color: #fcd34d;
    border: 1px solid rgba(251, 191, 36, 0.2);
  }

  .conf-low {
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    color: #fca5a5;
    border: 1px solid color-mix(in srgb, var(--danger) 20%, transparent);
  }

  .conf-unknown {
    display: none;
  }

  /* Stats grid: два фиксированных столбца (confidence + zeros) для табличного
     выравнивания. Каждый столбец - same width, оба badges всегда присутствуют
     (placeholder "-" если данных нет). */
  .chip-stats {
    display: grid;
    grid-template-columns: 44px 44px;
    gap: 4px;
    flex-shrink: 0;
    align-items: center;
  }
  .chip-stats .conf-badge,
  .chip-stats .zeros-badge {
    margin: 0;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }

  /* Zeros% badge - стиль аналогичен conf-badge. */
  .zeros-badge {
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 10px;
    font-weight: 600;
    flex-shrink: 0;
  }
  .zeros-low {
    background: color-mix(in srgb, var(--success) 12%, transparent);
    color: #86efac;
    border: 1px solid color-mix(in srgb, var(--success) 22%, transparent);
  }
  .zeros-mid {
    background: rgba(251, 191, 36, 0.10);
    color: #fcd34d;
    border: 1px solid rgba(251, 191, 36, 0.18);
  }
  .zeros-high {
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    color: #fca5a5;
    border: 1px solid color-mix(in srgb, var(--danger) 20%, transparent);
  }
  /* Placeholder для отсутствующих данных - убирает визуальный «провал» */
  .conf-empty,
  .zeros-empty {
    background: transparent;
    color: var(--text-muted, rgba(148,163,184,0.5));
    border: 1px dashed color-mix(in srgb, var(--text-muted) 25%, transparent);
  }

  /* v2.1.0 п.5.6: static zone-pulse click target border */
  @media (prefers-reduced-motion: reduce) {
    .zone.click-target {
      border-color: color-mix(in srgb, var(--success) 70%, transparent);
    }
  }
</style>
