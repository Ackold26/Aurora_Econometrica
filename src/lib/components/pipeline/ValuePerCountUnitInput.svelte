<script>
  /**
   * ValuePerCountUnitInput — v1.3.0 second sub-step of Validate (если KPI = count).
   *
   * Per ADR-016: для count KPIs (sales_packs, leads, registrations, и т.д.) требуется
   * ввести «ценность одной единицы»: маржа на упаковку, ценность лида, MRR подписки.
   *
   * UI:
   * - Auto-suggested value (если backend смог посчитать ratio sales_rub / count_col).
   * - Manual override input.
   * - Warning при CV > 20%.
   * - Skip option (verdict для count KPI деградирует к нейтральным share-based).
   *
   * Emits onConfirm({value, source}) или onSkip().
   *
   * @component ValuePerCountUnitInput
   */

  const {
    kpiType,                    // 'sales_packs' | 'leads' | etc.
    label,                      // 'Маржа на упаковку, ₽' (из registry)
    autoValue,                  // {value, cv, warning} | null (из backend auto_detect)
    currentValue,               // существующий value (для re-open)
    onConfirm,                  // callback (value, source)
    onSkip,                     // callback () — без value, fallback на share-based
  } = $props();

  let manualValue = $state(currentValue ?? autoValue?.value ?? '');
  let useAuto = $state(autoValue?.value !== undefined && autoValue?.value !== null);

  const cvIsHigh = $derived(autoValue?.cv > 0.20);

  function handleConfirm() {
    const value = useAuto && autoValue?.value !== null && autoValue?.value !== undefined
      ? autoValue.value
      : parseFloat(manualValue);
    if (!isFinite(value) || value <= 0) {
      return;
    }
    onConfirm?.({
      value,
      source: useAuto ? 'auto' : 'manual',
    });
  }

  function handleSkip() {
    onSkip?.();
  }
</script>

<div class="value-input">
  <header>
    <h2>Какая ценность одной единицы?</h2>
    <p class="lead">
      Чтобы оценить «убыточный/окупаемый» по каналам, нужно знать ценность одной {kpiType === 'sales_packs' ? 'упаковки' : 'единицы KPI'} для бизнеса.
      <button class="why-link" type="button">Зачем это? <span class="chevron">▾</span></button>
    </p>
  </header>

  {#if autoValue?.value !== null && autoValue?.value !== undefined}
    <section class="auto-suggestion" class:warning={cvIsHigh}>
      <div class="suggestion-head">
        <span class="emoji">🎯</span>
        <div>
          <strong>Обнаружена ценность: {Math.round(autoValue.value)} ₽/единицу</strong>
          <span class="meta">на основе {autoValue.n_periods} периодов{autoValue.cv != null ? `, CV = ${(autoValue.cv * 100).toFixed(1)}%` : ''}</span>
        </div>
      </div>
      {#if autoValue.warning}
        <p class="warning-text">⚠ {autoValue.warning}</p>
      {/if}
      <label class="checkbox-label">
        <input type="checkbox" bind:checked={useAuto} />
        Использовать автоматическое значение
      </label>
    </section>
  {/if}

  <section class="manual-input">
    <label for="value-input-field" class="field-label">{label || 'Ценность единицы, ₽'}</label>
    <input
      id="value-input-field"
      type="number"
      step="0.01"
      min="0"
      placeholder="например, 80"
      bind:value={manualValue}
      disabled={useAuto && autoValue?.value !== null}
      class:disabled={useAuto}
    />
    <p class="hint">
      Эта величина — порог для сравнения CPU (стоимость одной единицы) каналов. Если CPU канала превышает её — канал убыточен.
    </p>
  </section>

  <footer class="actions">
    <button type="button" class="btn-secondary" onclick={handleSkip}>
      Пропустить — оценить только долю в продажах
    </button>
    <button
      type="button"
      class="btn-primary"
      onclick={handleConfirm}
      disabled={!manualValue && !useAuto}
    >
      Подтвердить →
    </button>
  </footer>
</div>

<style>
  .value-input {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px;
    max-width: 760px;
    margin: 0 auto;
    width: 100%;
  }
  header h2 {
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 4px;
  }
  .lead { font-size: 12px; color: var(--text-secondary); margin: 0; line-height: 1.5; }
  .why-link {
    background: none;
    border: none;
    color: var(--accent-primary);
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    padding: 0 4px;
    text-decoration: underline dashed;
    text-underline-offset: 2px;
  }
  .chevron { font-size: 9px; }

  .auto-suggestion {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 16px;
    background: color-mix(in srgb, var(--success, #4ade80) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #4ade80) 30%, transparent);
    border-radius: var(--radius-card, 10px);
  }
  .auto-suggestion.warning {
    background: color-mix(in srgb, var(--warning, #fbbf24) 12%, transparent);
    border-color: color-mix(in srgb, var(--warning, #fbbf24) 40%, transparent);
  }
  .suggestion-head { display: flex; gap: 10px; align-items: flex-start; }
  .emoji { font-size: 20px; line-height: 1.2; }
  .suggestion-head strong { display: block; font-size: 14px; color: var(--text-primary); }
  .meta {
    font-size: 11px;
    color: var(--text-muted);
    display: block;
    margin-top: 2px;
  }
  .warning-text {
    font-size: 12px;
    color: var(--warning, #fbbf24);
    margin: 0;
    padding: 0;
    line-height: 1.5;
  }
  .checkbox-label {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 12px;
    color: var(--text-secondary);
    cursor: pointer;
  }

  .manual-input { display: flex; flex-direction: column; gap: 6px; }
  .field-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .manual-input input {
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 14px;
    font: inherit;
  }
  .manual-input input.disabled,
  .manual-input input:disabled {
    background: var(--bg-surface-quiet);
    color: var(--text-muted);
    cursor: not-allowed;
  }
  .hint { font-size: 11px; color: var(--text-muted); margin: 0; line-height: 1.5; }

  .actions {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    margin-top: 8px;
  }
  .btn-primary, .btn-secondary {
    padding: 10px 18px;
    border-radius: var(--radius-btn, 8px);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    border: 1px solid transparent;
    font: inherit;
  }
  .btn-primary {
    background: var(--accent-primary);
    color: #fff;
  }
  .btn-primary:disabled {
    background: var(--bg-surface-quiet);
    color: var(--text-muted);
    cursor: not-allowed;
  }
  .btn-secondary {
    background: var(--bg-card);
    color: var(--text-secondary);
    border-color: var(--border);
  }
  .btn-secondary:hover { border-color: var(--accent-primary); color: var(--accent-primary); }
</style>
