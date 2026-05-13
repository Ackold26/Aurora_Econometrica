<script>
  /**
   * StepTargetConfirm — Wizard Step 2: confirm target metric (F2 factor).
   *
   * Per WIZARD_FLOW_v2_FINAL.md §2.2:
   *   - Single candidate ≥ 0.95 confidence → silent auto-confirm card + auto-advance hint
   *   - Multiple candidates → radio list for disambiguation
   *   - count KPI → additional field «Ценность единицы, ₽»
   *
   * @component StepTargetConfirm
   */

  import { CheckCircle, Info, ChevronRight } from 'lucide-svelte';
  import { kpiKind, kpiType, expertMode } from '$lib/project-state.js';

  /**
   * @typedef {{
   *   column: string,
   *   kind: 'target_monetary' | 'target_count',
   *   confidence: number,
   *   kpi_type?: string
   * }} TargetCandidate
   */

  /**
   * @type {{
   *   targetCandidates?: TargetCandidate[],
   *   onConfirm?: ((data: { column: string, kind: string, valuePerCountUnit?: number | null }) => void) | null
   * }}
   */
  const {
    targetCandidates = [],
    onConfirm = null,
  } = $props();

  // ─── Derived helpers ──────────────────────────────────────────────────────

  const CONFIDENCE_THRESHOLD = 0.95;

  /** True when single confident candidate — show auto-confirm card */
  const isSilentConfirm = $derived(
    targetCandidates.length === 1 && targetCandidates[0]?.confidence >= CONFIDENCE_THRESHOLD
  );

  /** True when multiple candidates — show radio list */
  const isDisambiguous = $derived(targetCandidates.length > 1);

  // ─── Local state ──────────────────────────────────────────────────────────

  /**
   * Currently selected column.
   * @type {string | null}
   */
  let selectedColumn = $state(
    targetCandidates.length > 0 ? targetCandidates[0].column : null
  );

  /**
   * Value per count unit input (₽). Only relevant for count KPI.
   * @type {number | null}
   */
  let valuePerCountUnit = $state(null);

  /** Manual column override (from «другое» fallback) */
  let manualColumn = $state('');

  /** Whether user confirmed (for silent auto-confirm card advancement) */
  let confirmed = $state(false);

  // ─── Derived ─────────────────────────────────────────────────────────────

  /** The resolved candidate matching selectedColumn */
  const selectedCandidate = $derived(
    targetCandidates.find(c => c.column === selectedColumn) ?? null
  );

  /** Whether selected KPI is count-kind → need value_per_count_unit */
  const isCountKPI = $derived(
    selectedCandidate?.kind === 'target_count'
  );

  /**
   * Auto-suggest hint for value per unit based on KPI type.
   * Manager mode shows generic; Expert shows per-type specific.
   * @type {string}
   */
  const valueSuggestHint = $derived.by(() => {
    const type = selectedCandidate?.kpi_type ?? '';
    if ($expertMode) {
      if (type === 'sales_packs')   return 'Маржа на упаковку. Для OTC фарма обычно 30–150 ₽/упак.';
      if (type === 'leads')         return 'Ценность лида: рекомендуем LTV × Conversion Rate (CR).';
      if (type === 'registrations') return 'Ценность регистрации: avg LTV × CR в платящих.';
      if (type === 'subscriptions') return 'MRR на новую подписку (первый месяц).';
      if (type === 'app_installs')  return 'Ценность установки: LTV × retention rate.';
    }
    return 'Укажите среднюю ценность одной единицы KPI в рублях (например, маржа или LTV).';
  });

  /**
   * Readable label for the «Ценность единицы» input field.
   * Manager mode — generic. Expert — per-type.
   * @type {string}
   */
  const valueLabel = $derived.by(() => {
    if (!$expertMode) return 'Ценность одной единицы, ₽';
    const type = selectedCandidate?.kpi_type ?? '';
    if (type === 'sales_packs')   return 'Маржа на упаковку, ₽';
    if (type === 'leads')         return 'Ценность лида = LTV × CR, ₽';
    if (type === 'subscriptions') return 'Ценность подписки (MRR), ₽';
    if (type === 'app_installs')  return 'Ценность установки (LTV × retention), ₽';
    return 'Ценность единицы KPI, ₽';
  });

  /**
   * Confidence badge color class.
   * @param {number} conf
   * @returns {'high' | 'med' | 'low'}
   */
  function confTone(conf) {
    if (conf >= 0.9) return 'high';
    if (conf >= 0.7) return 'med';
    return 'low';
  }

  /**
   * Human-readable confidence label.
   * @param {number} conf
   */
  function confLabel(conf) {
    return `${Math.round(conf * 100)}%`;
  }

  /**
   * Kind display label.
   * @param {'target_monetary' | 'target_count'} kind
   */
  function kindLabel(kind) {
    return kind === 'target_monetary' ? 'Денежный (₽)' : 'Штучный';
  }

  // ─── Handlers ────────────────────────────────────────────────────────────

  /**
   * Handle radio selection of a candidate.
   * @param {string} col
   */
  function selectCandidate(col) {
    selectedColumn = col;
  }

  /** Confirm and emit data */
  function handleConfirm() {
    if (!selectedColumn) return;
    confirmed = true;
    const candidate = selectedCandidate;
    onConfirm?.({
      column: selectedColumn,
      kind: candidate?.kind ?? 'target_monetary',
      valuePerCountUnit: isCountKPI ? valuePerCountUnit : null,
    });
    // Sync KPI stores
    if (candidate) {
      kpiKind.set(candidate.kind === 'target_monetary' ? 'monetary' : 'count');
      kpiType.set(candidate.kpi_type ?? (candidate.kind === 'target_monetary' ? 'sales' : 'sales_packs'));
    }
  }
</script>

<div class="step-target-confirm">
  <header class="intro">
    <h2>Какой целевой показатель будем оптимизировать?</h2>
    <p class="lead">
      Программа обнаружила следующие кандидаты. Выберите основной показатель — то,
      что вы хотите объяснить и улучшить.
    </p>
  </header>

  <!-- ─── Silent auto-confirm: single high-confidence candidate ──────────── -->
  {#if isSilentConfirm}
    {@const cand = targetCandidates[0]}
    <div class="auto-confirm-card" class:confirmed>
      <div class="auto-confirm-icon">
        <CheckCircle size={28} strokeWidth={1.5} />
      </div>
      <div class="auto-confirm-body">
        <p class="auto-confirm-label">Обнаружен однозначный показатель:</p>
        <p class="auto-confirm-col">{cand.column}</p>
        <div class="meta-row">
          <span class="kind-tag">{kindLabel(cand.kind)}</span>
          <span class="conf-badge conf-{confTone(cand.confidence)}">
            {confLabel(cand.confidence)} уверенность
          </span>
        </div>
      </div>
      {#if !confirmed}
        <button
          type="button"
          class="btn btn-auto-confirm"
          onclick={handleConfirm}
        >
          Подтвердить <ChevronRight size={15} />
        </button>
      {:else}
        <span class="confirmed-label">Подтверждено ✓</span>
      {/if}
    </div>

  <!-- ─── Disambiguation: multiple candidates ────────────────────────────── -->
  {:else if isDisambiguous || targetCandidates.length > 0}
    <div class="radio-list" role="radiogroup" aria-label="Выбор целевого показателя">
      {#each targetCandidates as cand (cand.column)}
        <label
          class="radio-item"
          class:radio-selected={selectedColumn === cand.column}
        >
          <input
            type="radio"
            name="target_column"
            value={cand.column}
            checked={selectedColumn === cand.column}
            onchange={() => selectCandidate(cand.column)}
            class="sr-only"
          />
          <span class="radio-dot" aria-hidden="true"></span>
          <div class="radio-content">
            <span class="radio-col">{cand.column}</span>
            <div class="radio-meta">
              <span class="kind-tag">{kindLabel(cand.kind)}</span>
              <span class="conf-badge conf-{confTone(cand.confidence)}">
                {confLabel(cand.confidence)}
              </span>
              {#if targetCandidates[0] === cand}
                <span class="rec-badge">рекомендовано</span>
              {/if}
            </div>
          </div>
        </label>
      {/each}

      <!-- Manual fallback -->
      <label class="radio-item radio-manual">
        <input
          type="radio"
          name="target_column"
          value="__manual__"
          checked={selectedColumn === '__manual__'}
          onchange={() => selectCandidate('__manual__')}
          class="sr-only"
        />
        <span class="radio-dot" aria-hidden="true"></span>
        <div class="radio-content">
          <span class="radio-col">Выбрать вручную из колонок</span>
          {#if selectedColumn === '__manual__'}
            <input
              type="text"
              class="manual-input"
              placeholder="Название колонки..."
              bind:value={manualColumn}
              oninput={() => { if (manualColumn) selectedColumn = manualColumn; }}
            />
          {/if}
        </div>
      </label>
    </div>

  <!-- ─── No candidates detected ──────────────────────────────────────── -->
  {:else}
    <div class="no-candidates">
      <Info size={18} strokeWidth={1.5} />
      <div>
        <p class="no-cand-title">Целевой показатель не обнаружен автоматически</p>
        <p class="no-cand-body">
          Введите название колонки с вашим KPI вручную:
        </p>
        <input
          type="text"
          class="manual-input standalone"
          placeholder="Например: sales_packs, revenue_rub..."
          bind:value={manualColumn}
          oninput={() => { if (manualColumn) selectedColumn = manualColumn; }}
        />
      </div>
    </div>
  {/if}

  <!-- ─── Count KPI: value per unit input ────────────────────────────────── -->
  {#if isCountKPI && selectedColumn && selectedColumn !== '__manual__'}
    <div class="count-value-section">
      <label class="count-label" for="value-per-unit">
        {valueLabel}
      </label>
      <div class="count-input-row">
        <input
          id="value-per-unit"
          type="number"
          class="count-input"
          min="0"
          step="0.01"
          placeholder="0.00"
          bind:value={valuePerCountUnit}
        />
        <span class="currency-suffix">₽</span>
      </div>
      <p class="count-hint">
        <Info size={12} strokeWidth={1.5} />
        {valueSuggestHint}
      </p>
    </div>
  {/if}

  <!-- ─── Confirm button (multi-candidate mode) ────────────────────────── -->
  {#if !isSilentConfirm && selectedColumn}
    <div class="confirm-row">
      <button
        type="button"
        class="btn btn-confirm"
        disabled={isCountKPI && valuePerCountUnit == null}
        onclick={handleConfirm}
        title={isCountKPI && valuePerCountUnit == null ? 'Укажите ценность единицы' : ''}
      >
        Подтвердить выбор <ChevronRight size={15} />
      </button>
      {#if isCountKPI && valuePerCountUnit == null}
        <span class="confirm-warn">Укажите ценность единицы для расчёта CPU</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .step-target-confirm {
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

  /* ─── Auto-confirm card ─── */
  .auto-confirm-card {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 18px 20px;
    background: color-mix(in srgb, var(--gold, #c9a449) 6%, var(--bg-secondary, #141420));
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
    border-radius: var(--radius-card, 12px);
    transition: border-color 0.2s, background 0.2s;
  }
  .auto-confirm-card.confirmed {
    border-color: color-mix(in srgb, var(--success, #22C55E) 40%, transparent);
    background: color-mix(in srgb, var(--success, #22C55E) 5%, var(--bg-secondary, #141420));
  }
  .auto-confirm-icon {
    color: var(--gold, #c9a449);
    flex-shrink: 0;
    display: flex;
    align-items: center;
  }
  .auto-confirm-card.confirmed .auto-confirm-icon {
    color: var(--success, #22C55E);
  }
  .auto-confirm-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .auto-confirm-label {
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0;
  }
  .auto-confirm-col {
    font-size: 17px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0;
    font-family: var(--font-mono, monospace);
  }
  .meta-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .confirmed-label {
    font-size: 12px;
    font-weight: 700;
    color: var(--success, #22C55E);
    white-space: nowrap;
  }

  /* ─── Radio list ─── */
  .radio-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .radio-item {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 12px 16px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: 9px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  .radio-item:hover {
    border-color: var(--accent-primary);
    background: color-mix(in srgb, var(--accent-primary) 5%, var(--bg-card, #181824));
  }
  .radio-item.radio-selected {
    border-color: var(--gold, #c9a449);
    border-width: 2px;
    background: color-mix(in srgb, var(--gold, #c9a449) 6%, var(--bg-card, #181824));
  }
  .radio-manual {
    opacity: 0.8;
  }
  .radio-dot {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 2px solid var(--border, rgba(255,255,255,0.2));
    background: transparent;
    flex-shrink: 0;
    margin-top: 2px;
    transition: border-color 0.15s, background 0.15s;
    position: relative;
  }
  .radio-item.radio-selected .radio-dot {
    border-color: var(--gold, #c9a449);
  }
  .radio-item.radio-selected .radio-dot::after {
    content: '';
    position: absolute;
    inset: 3px;
    border-radius: 50%;
    background: var(--gold, #c9a449);
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
  .radio-content {
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1;
  }
  .radio-col {
    font-size: 14px;
    font-weight: 700;
    color: var(--text-primary);
    font-family: var(--font-mono, monospace);
  }
  .radio-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  /* ─── Badges ─── */
  .kind-tag {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted, #7A7A90);
    padding: 1px 5px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: 4px;
  }
  .conf-badge {
    font-size: 10px;
    font-weight: 700;
    padding: 1px 5px;
    border-radius: 4px;
    letter-spacing: 0.02em;
  }
  .conf-high {
    background: color-mix(in srgb, var(--success, #22C55E) 15%, transparent);
    color: var(--success, #22C55E);
    border: 1px solid color-mix(in srgb, var(--success, #22C55E) 35%, transparent);
  }
  .conf-med {
    background: color-mix(in srgb, var(--warning, #F59E0B) 12%, transparent);
    color: var(--warning, #F59E0B);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 30%, transparent);
  }
  .conf-low {
    background: color-mix(in srgb, var(--danger, #EF4444) 12%, transparent);
    color: var(--danger, #EF4444);
    border: 1px solid color-mix(in srgb, var(--danger, #EF4444) 30%, transparent);
  }
  .rec-badge {
    font-size: 10px;
    font-style: italic;
    color: var(--gold, #c9a449);
  }

  /* ─── Manual input ─── */
  .manual-input {
    width: 100%;
    margin-top: 6px;
    padding: 6px 10px;
    background: var(--bg-secondary, #141420);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: 6px;
    color: var(--text-primary);
    font: inherit;
    font-size: 13px;
    outline: none;
    transition: border-color 0.15s;
  }
  .manual-input:focus { border-color: var(--accent-primary); }
  .manual-input.standalone { max-width: 360px; }

  /* ─── No candidates ─── */
  .no-candidates {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 16px;
    background: var(--bg-secondary, #141420);
    border: 1px solid var(--border, rgba(255,255,255,0.06));
    border-radius: 9px;
    color: var(--text-muted, #7A7A90);
  }
  .no-cand-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0 0 4px;
  }
  .no-cand-body {
    font-size: 12.5px;
    color: var(--text-secondary);
    margin: 0 0 8px;
  }

  /* ─── Count KPI value section ─── */
  .count-value-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 16px 18px;
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, var(--bg-secondary, #141420));
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 20%, transparent);
    border-radius: 9px;
  }
  .count-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .count-input-row {
    display: flex;
    align-items: center;
    gap: 8px;
    max-width: 200px;
  }
  .count-input {
    flex: 1;
    padding: 8px 10px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: 6px;
    color: var(--text-primary);
    font: inherit;
    font-size: 15px;
    font-weight: 700;
    text-align: right;
    outline: none;
    transition: border-color 0.15s;
    /* Remove number spinners */
    -moz-appearance: textfield;
  }
  .count-input::-webkit-outer-spin-button,
  .count-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  .count-input:focus { border-color: var(--gold, #c9a449); }
  .currency-suffix {
    font-size: 16px;
    font-weight: 700;
    color: var(--gold, #c9a449);
  }
  .count-hint {
    display: flex;
    align-items: flex-start;
    gap: 5px;
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    margin: 2px 0 0;
    line-height: 1.5;
    font-style: italic;
  }
  .count-hint > :global(svg) { flex-shrink: 0; margin-top: 1px; }

  /* ─── Confirm row ─── */
  .confirm-row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .confirm-warn {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    font-style: italic;
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
    transition: background 0.15s, opacity 0.15s, transform 0.12s;
    white-space: nowrap;
  }
  .btn:disabled { opacity: 0.35; cursor: not-allowed; }

  .btn-auto-confirm {
    background: var(--gold, #c9a449);
    color: #0c0c14;
    padding: 8px 18px;
    flex-shrink: 0;
  }
  .btn-auto-confirm:hover {
    background: color-mix(in srgb, var(--gold, #c9a449) 85%, #fff);
    transform: translateY(-1px);
  }
  .btn-confirm {
    background: var(--accent-primary);
    color: #fff;
  }
  .btn-confirm:not(:disabled):hover {
    background: color-mix(in srgb, var(--accent-primary) 80%, #fff);
    transform: translateY(-1px);
  }
</style>
