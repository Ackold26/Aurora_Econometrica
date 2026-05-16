<script>
  /**
   * StepContextConfirm - Wizard Step 5: non-media context factors confirmation.
   *
   * Per §2.5 WIZARD_FLOW_v2_FINAL.md:
   *   Conditional: shown only when ambiguous / unconfirmed non-media factors exist.
   *   If no factors detected, parent ScenarioWizard silently skips this step.
   *
   * Shows:
   *   - Auto-detected factors (silent, used - confidence ≥0.9)
   *   - Ambiguous factors needing confirmation (competitor_trp, price_average)
   *   - РФ-праздники count (auto-injected, always shown for transparency)
   *   - Planned non-media changes for the forecast period
   *
   * @component StepContextConfirm
   */

  import {
    CheckCircle,
    AlertTriangle,
    Info,
    ChevronRight,
    ChevronLeft,
  } from 'lucide-svelte';

  /**
   * @typedef {Object} AutoDetectedFactors
   * @property {{ detected: boolean, score_range?: string }} trade_activity
   * @property {{ detected: boolean }} distribution
   * @property {{ count: number }} holidays
   * @property {{ detected: boolean, column?: string }} competitors
   * @property {{ detected: boolean, column?: string, derivable?: boolean }} prices
   */

  /**
   * @type {{
   *   autoDetectedFactors: AutoDetectedFactors,
   *   onConfirm: (data: Record<string, any>) => void,
   *   onBack?: (() => void) | null,
   * }}
   */
  const {
    autoDetectedFactors,
    onConfirm,
    onBack = null,
  } = $props();

  // ─── Ambiguous factor decisions ───
  /** Use competitor activity in model */
  let useCompetitors = $state(true);
  /** Derive price from sales_rub / sales_packs */
  let usePriceDerived = $state(true);

  // ─── Planned non-media changes ───
  /** @type {'none'|'specify'} */
  let plannedNonMedia = $state('none');
  let plannedDistribution = $state('');
  let plannedTrade        = $state('');
  let plannedPrice        = $state('');

  // ─── Derived: has any ambiguous factor ───
  const hasAmbiguous = $derived(
    (autoDetectedFactors.competitors?.detected || false) ||
    (autoDetectedFactors.prices?.detected || autoDetectedFactors.prices?.derivable || false)
  );

  function handleConfirm() {
    onConfirm({
      useCompetitors: autoDetectedFactors.competitors?.detected ? useCompetitors : false,
      usePriceDerived: (autoDetectedFactors.prices?.detected || autoDetectedFactors.prices?.derivable)
        ? usePriceDerived
        : false,
      plannedNonMedia,
      plannedDistribution: plannedNonMedia === 'specify' ? plannedDistribution : null,
      plannedTrade: plannedNonMedia === 'specify' ? plannedTrade : null,
      plannedPrice: plannedNonMedia === 'specify' ? plannedPrice : null,
    });
  }
</script>

<div class="step-context-confirm">
  <header class="step-header">
    <h2 class="step-title">Дополнительные факторы, влияющие на продажи</h2>
    <p class="step-desc">
      Программа обнаружила следующие non-media факторы.
      Подтвердите какие использовать в модели.
    </p>
  </header>

  <div class="factors-list">

    <!-- ─── Trade activity (auto-detected, used) ─── -->
    {#if autoDetectedFactors.trade_activity?.detected}
      <div class="factor-row factor-auto">
        <span class="factor-status ok">
          <CheckCircle size={16} strokeWidth={2} />
        </span>
        <div class="factor-body">
          <span class="factor-name">Trade activity</span>
          {#if autoDetectedFactors.trade_activity.score_range}
            <span class="factor-meta">({autoDetectedFactors.trade_activity.score_range})</span>
          {:else}
            <span class="factor-meta">(баллы 0–5)</span>
          {/if}
          <span class="factor-tag tag-auto">auto-detected, использовать</span>
        </div>
      </div>
    {/if}

    <!-- ─── Distribution (auto-detected, used) ─── -->
    {#if autoDetectedFactors.distribution?.detected}
      <div class="factor-row factor-auto">
        <span class="factor-status ok">
          <CheckCircle size={16} strokeWidth={2} />
        </span>
        <div class="factor-body">
          <span class="factor-name">Дистрибуция</span>
          <span class="factor-tag tag-auto">auto-detected, использовать</span>
        </div>
      </div>
    {/if}

    <!-- ─── РФ-праздники (always auto-injected) ─── -->
    <div class="factor-row factor-auto">
      <span class="factor-status ok">
        <CheckCircle size={16} strokeWidth={2} />
      </span>
      <div class="factor-body">
        <span class="factor-name">
          {autoDetectedFactors.holidays?.count ?? 11} РФ-праздников
        </span>
        <span class="factor-meta">
          (Новый год / 8 марта / 9 мая / День России / Чёрная пятница / ...)
        </span>
        <span class="factor-tag tag-injected">auto-injected</span>
      </div>
    </div>

    <!-- ─── Competitor activity (ambiguous - confirm) ─── -->
    {#if autoDetectedFactors.competitors?.detected}
      <div class="factor-row factor-ambiguous">
        <span class="factor-status warn">
          <AlertTriangle size={16} strokeWidth={2} />
        </span>
        <div class="factor-body">
          <span class="factor-name">
            Активность конкурентов
            {#if autoDetectedFactors.competitors.column}
              <span class="factor-col-name">({autoDetectedFactors.competitors.column})</span>
            {:else}
              <span class="factor-col-name">(competitor_trp)</span>
            {/if}
          </span>
          <span class="factor-tag tag-ambiguous">обнаружено</span>
          <p class="factor-decision-q">Использовать в модели?</p>
          <div class="confirm-btns" role="group" aria-label="Использовать активность конкурентов">
            <button
              type="button"
              class="confirm-btn"
              class:selected={useCompetitors}
              onclick={() => (useCompetitors = true)}
              aria-pressed={useCompetitors}
            >
              <CheckCircle size={13} strokeWidth={2.5} />
              Да
            </button>
            <button
              type="button"
              class="confirm-btn confirm-btn-no"
              class:selected={!useCompetitors}
              onclick={() => (useCompetitors = false)}
              aria-pressed={!useCompetitors}
            >
              <span class="x-icon" aria-hidden="true">✗</span>
              Нет
            </button>
          </div>
        </div>
      </div>
    {/if}

    <!-- ─── Price (derivable - confirm) ─── -->
    {#if autoDetectedFactors.prices?.detected || autoDetectedFactors.prices?.derivable}
      <div class="factor-row factor-ambiguous">
        <span class="factor-status warn">
          <AlertTriangle size={16} strokeWidth={2} />
        </span>
        <div class="factor-body">
          <span class="factor-name">
            Цена
            {#if autoDetectedFactors.prices?.column}
              <span class="factor-col-name">({autoDetectedFactors.prices.column})</span>
            {:else}
              <span class="factor-col-name">(price_average)</span>
            {/if}
          </span>
          {#if autoDetectedFactors.prices?.derivable}
            <span class="factor-tag tag-ambiguous">derivable from sales_rub / sales_packs</span>
          {:else}
            <span class="factor-tag tag-ambiguous">обнаружено</span>
          {/if}
          <p class="factor-decision-q">
            {autoDetectedFactors.prices?.derivable
              ? 'Вычислить из sales_rub / sales_packs?'
              : 'Использовать в модели?'}
          </p>
          <div class="confirm-btns" role="group" aria-label="Использовать цену">
            <button
              type="button"
              class="confirm-btn"
              class:selected={usePriceDerived}
              onclick={() => (usePriceDerived = true)}
              aria-pressed={usePriceDerived}
            >
              <CheckCircle size={13} strokeWidth={2.5} />
              Да
            </button>
            <button
              type="button"
              class="confirm-btn confirm-btn-no"
              class:selected={!usePriceDerived}
              onclick={() => (usePriceDerived = false)}
              aria-pressed={!usePriceDerived}
            >
              <span class="x-icon" aria-hidden="true">✗</span>
              Нет
            </button>
          </div>
        </div>
      </div>
    {/if}

    <!-- ─── Info footer: no ambiguous factors ─── -->
    {#if !hasAmbiguous}
      <div class="info-banner" role="note">
        <Info size={15} strokeWidth={2} />
        Все обнаруженные факторы определены однозначно. Нажмите «Далее» для продолжения.
      </div>
    {/if}
  </div>

  <!-- ─── Planned non-media changes ─── -->
  <div class="planned-section">
    <h3 class="planned-title">Планируется ли изменение non-media в плановом периоде?</h3>

    <div class="radio-group">
      <label class="radio-row">
        <input type="radio" name="plannedNonMedia" value="none" bind:group={plannedNonMedia} />
        <span class="radio-label">Нет (по умолчанию)</span>
      </label>
      <label class="radio-row">
        <input type="radio" name="plannedNonMedia" value="specify" bind:group={plannedNonMedia} />
        <span class="radio-label">Да - указать плановые значения</span>
      </label>
    </div>

    {#if plannedNonMedia === 'specify'}
      <div class="planned-fields">
        <div class="planned-field">
          <label class="field-label-sm" for="p-distribution">Дистрибуция (плановая)</label>
          <input
            id="p-distribution"
            class="text-input"
            type="text"
            placeholder="0.85"
            bind:value={plannedDistribution}
          />
        </div>
        <div class="planned-field">
          <label class="field-label-sm" for="p-trade">Trade activity (плановая)</label>
          <input
            id="p-trade"
            class="text-input"
            type="text"
            placeholder="3.5"
            bind:value={plannedTrade}
          />
        </div>
        <div class="planned-field">
          <label class="field-label-sm" for="p-price">Цена (плановая, ₽)</label>
          <input
            id="p-price"
            class="text-input"
            type="text"
            placeholder="250"
            bind:value={plannedPrice}
          />
        </div>
      </div>
    {/if}
  </div>

  <!-- ─── Footer ─── -->
  <div class="step-footer">
    {#if onBack}
      <button type="button" class="btn-ghost btn-back" onclick={onBack}>
        <ChevronLeft size={15} strokeWidth={2} />
        Назад
      </button>
    {/if}
    <button type="button" class="btn-primary submit-btn" onclick={handleConfirm}>
      Далее
      <ChevronRight size={16} strokeWidth={2} />
    </button>
  </div>
</div>

<style>
  .step-context-confirm {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 20px 24px;
    max-width: 720px;
    margin: 0 auto;
    width: 100%;
  }

  /* ─── Header ─── */
  .step-header {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .step-title {
    font-size: 17px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0;
    letter-spacing: -0.01em;
  }
  .step-desc {
    font-size: 12.5px;
    color: var(--text-secondary);
    margin: 0;
    line-height: 1.5;
  }

  /* ─── Factors list ─── */
  .factors-list {
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    background: var(--bg-card, #181824);
    overflow: hidden;
  }

  .factor-row {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.05));
    transition: background 0.15s;
  }
  .factor-row:last-child {
    border-bottom: none;
  }
  .factor-auto {
    background: transparent;
  }
  .factor-ambiguous {
    background: color-mix(in srgb, var(--warning, #F59E0B) 4%, var(--bg-card, #181824));
  }

  /* ─── Status icon ─── */
  .factor-status {
    flex-shrink: 0;
    width: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding-top: 2px;
  }
  .factor-status.ok   { color: var(--success, #22c55e); }
  .factor-status.warn { color: var(--warning, #F59E0B); }

  /* ─── Factor body ─── */
  .factor-body {
    flex: 1;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .factor-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    white-space: nowrap;
  }
  .factor-col-name {
    font-size: 12px;
    font-weight: 400;
    color: var(--text-muted, #7A7A90);
    font-family: var(--font-mono, monospace);
  }
  .factor-meta {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
  }

  /* ─── Tags ─── */
  .factor-tag {
    display: inline-flex;
    align-items: center;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    white-space: nowrap;
  }
  .tag-auto {
    background: color-mix(in srgb, var(--success, #22c55e) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #22c55e) 30%, transparent);
    color: var(--success, #22c55e);
  }
  .tag-injected {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
    color: var(--accent-primary, #3b82f6);
  }
  .tag-ambiguous {
    background: color-mix(in srgb, var(--warning, #F59E0B) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 30%, transparent);
    color: var(--warning, #F59E0B);
  }

  /* ─── Confirm buttons ─── */
  .factor-decision-q {
    width: 100%;
    margin: 6px 0 4px;
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
  }

  .confirm-btns {
    display: flex;
    gap: 6px;
  }
  .confirm-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 12px;
    border-radius: var(--radius-sm, 8px);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    background: var(--bg-surface-quiet, rgba(20,20,30,0.92));
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
    font-family: inherit;
  }
  .confirm-btn:hover {
    border-color: var(--success, #22c55e);
    color: var(--success, #22c55e);
  }
  .confirm-btn.selected {
    border-color: var(--success, #22c55e);
    background: color-mix(in srgb, var(--success, #22c55e) 12%, var(--bg-card, #181824));
    color: var(--success, #22c55e);
  }
  .confirm-btn-no:hover {
    border-color: var(--danger, #ef4444);
    color: var(--danger, #ef4444);
  }
  .confirm-btn-no.selected {
    border-color: var(--danger, #ef4444);
    background: color-mix(in srgb, var(--danger, #ef4444) 10%, var(--bg-card, #181824));
    color: var(--danger, #ef4444);
  }
  .x-icon {
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
  }

  /* ─── Info banner ─── */
  .info-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    color: var(--accent-primary, #3b82f6);
    font-size: 12.5px;
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 8%, transparent);
  }

  /* ─── Planned non-media section ─── */
  .planned-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-card, 12px);
    background: var(--bg-surface-quiet, rgba(20,20,30,0.92));
  }
  .planned-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
  }

  /* ─── Radio group ─── */
  .radio-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .radio-row {
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
  }
  .radio-row input[type="radio"] {
    accent-color: var(--gold, #c9a449);
    width: 15px;
    height: 15px;
    flex-shrink: 0;
    cursor: pointer;
  }
  .radio-label {
    font-size: 12.5px;
    color: var(--text-secondary);
    font-weight: 500;
  }

  /* ─── Planned fields ─── */
  .planned-fields {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 12px;
  }
  @media (max-width: 600px) {
    .planned-fields { grid-template-columns: 1fr; }
  }
  .planned-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .field-label-sm {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-muted, #7A7A90);
  }
  .text-input {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    border-radius: var(--radius-sm, 8px);
    color: var(--text-primary);
    font-size: 13px;
    padding: 8px 10px;
    outline: none;
    transition: border-color 0.18s;
    font-family: inherit;
    width: 100%;
    box-sizing: border-box;
  }
  .text-input:focus {
    border-color: var(--gold, #c9a449);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--gold, #c9a449) 18%, transparent);
  }

  /* ─── Footer ─── */
  .step-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-top: 8px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }

  .btn-primary {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 10px 22px;
    background: var(--gold, #c9a449);
    color: #0a0a14;
    font-size: 14px;
    font-weight: 700;
    border: none;
    border-radius: var(--radius-sm, 8px);
    cursor: pointer;
    transition: background 0.15s, transform 0.1s;
    font-family: inherit;
    margin-left: auto;
  }
  .btn-primary:hover {
    background: color-mix(in srgb, var(--gold, #c9a449) 85%, white);
    transform: translateY(-1px);
  }

  .btn-ghost {
    background: none;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
    color: var(--text-muted, #7A7A90);
    font-size: 13px;
    font-weight: 500;
    padding: 8px 14px;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
    font-family: inherit;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .btn-ghost:hover {
    border-color: var(--border, rgba(255,255,255,0.1));
    color: var(--text-secondary);
  }
  /* .btn-back inherits .btn-ghost styles */

  .submit-btn {
    min-width: 120px;
    justify-content: center;
  }
</style>
