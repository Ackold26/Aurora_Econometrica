<script>
  /**
   * CommandBrief - UI-панель параметров команды.
   * Показывается вместо CommandGrid при клике на команду с briefFields.
   * Собирает параметры и формирует текстовый бриф для отправки в Claude.
   *
   * @typedef {Object} BriefFieldOption
   * @property {string} value
   * @property {string} label
   * @property {boolean} [allowInput]
   * @property {string} [inputPlaceholder]
   *
   * @typedef {Object} BriefField
   * @property {string} id
   * @property {string} label
   * @property {'radio'|'checkboxes'|'text'} type
   * @property {BriefFieldOption[]} [options]
   * @property {string} [default]
   * @property {string[]} [defaults]
   * @property {string[]} [chips]
   * @property {string} [placeholder]
   */

  /**
   * @type {{
   *   command: string,
   *   fields: BriefField[],
   *   onRun: (text: string) => void,
   *   onCancel: () => void,
   * }}
   */
  let { command, fields, onRun, onCancel } = $props();

  /** @type {Record<string, any>} */
  let values = $state({});

  // Initialize field values from defaults when fields change
  $effect(() => {
    /** @type {Record<string, any>} */
    const init = {};
    for (const field of fields) {
      if (field.type === 'radio') {
        init[field.id] = field.default ?? field.options?.[0]?.value ?? '';
        // Reserve slots for inline inputs on allowInput options
        if (field.options) {
          for (const opt of field.options) {
            if (opt.allowInput) init[field.id + '_input'] = '';
          }
        }
      } else if (field.type === 'checkboxes') {
        init[field.id] = field.defaults ? [...field.defaults] : (field.options?.map(o => o.value) ?? []);
      } else if (field.type === 'text') {
        init[field.id] = '';
      }
    }
    values = init;
  });

  /**
   * @param {string} fieldId
   * @param {string} optValue
   */
  function toggleCheckbox(fieldId, optValue) {
    const current = [...(values[fieldId] ?? [])];
    const idx = current.indexOf(optValue);
    if (idx >= 0) current.splice(idx, 1);
    else current.push(optValue);
    values = { ...values, [fieldId]: current };
  }

  /**
   * Appends chip text to text field value.
   * @param {string} fieldId
   * @param {string} chip
   */
  function addChip(fieldId, chip) {
    const current = (values[fieldId] ?? '').trim();
    values = { ...values, [fieldId]: current ? `${current}, ${chip}` : chip };
  }

  /** Build final brief string from current field values. */
  function buildBrief() {
    const lines = [command];
    for (const field of fields) {
      const val = values[field.id];
      if (field.type === 'radio') {
        const opt = field.options?.find(o => o.value === val);
        if (opt?.allowInput) {
          const inputVal = (values[field.id + '_input'] ?? '').trim();
          lines.push(`${field.label}: ${inputVal || opt.label}`);
        } else {
          lines.push(`${field.label}: ${opt?.label ?? val}`);
        }
      } else if (field.type === 'checkboxes') {
        /** @type {string[]} */
        const selected = val ?? [];
        if (selected.length > 0) {
          const labels = selected.map(v => field.options?.find(o => o.value === v)?.label ?? v);
          lines.push(`${field.label}: ${labels.join(', ')}`);
        }
      } else if (field.type === 'text') {
        const text = (val ?? '').trim();
        if (text) lines.push(`${field.label}: ${text}`);
      }
    }
    return lines.join('\n');
  }

  // Disabled when no checkboxes are selected or radio allowInput is empty
  const canRun = $derived.by(() => {
    for (const field of fields) {
      if (field.type === 'checkboxes') {
        if ((values[field.id] ?? []).length === 0) return false;
      }
      if (field.type === 'radio' && field.options) {
        const selectedOpt = field.options.find(o => o.value === values[field.id]);
        if (selectedOpt?.allowInput) {
          if (!(values[field.id + '_input'] ?? '').trim()) return false;
        }
      }
    }
    return true;
  });
</script>

<div class="brief-panel">
  <!-- Header -->
  <div class="brief-header">
    <button class="brief-back" onclick={onCancel} title="Назад к командам">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
    </button>
    <span class="brief-command">{command}</span>
    <span class="brief-hint">настройте параметры и запустите</span>
  </div>

  <!-- Fields -->
  <div class="brief-fields">
    {#each fields as field (field.id)}
      <div class="brief-field">
        <span class="field-label">{field.label}</span>

        {#if field.type === 'radio' && field.options}
          <div class="radio-group">
            {#each field.options as opt (opt.value)}
              <label class="radio-option" class:selected={values[field.id] === opt.value}>
                <input
                  type="radio"
                  name={field.id}
                  value={opt.value}
                  checked={values[field.id] === opt.value}
                  onchange={() => { values = { ...values, [field.id]: opt.value }; }}
                />
                <span class="option-label">{opt.label}</span>
                {#if opt.allowInput && values[field.id] === opt.value}
                  <input
                    type="text"
                    class="inline-input"
                    placeholder={opt.inputPlaceholder ?? ''}
                    value={values[field.id + '_input'] ?? ''}
                    oninput={(e) => { values = { ...values, [field.id + '_input']: /** @type {HTMLInputElement} */ (e.currentTarget).value }; }}
                  />
                {/if}
              </label>
            {/each}
          </div>

        {:else if field.type === 'checkboxes' && field.options}
          <div class="checkbox-group">
            {#each field.options as opt (opt.value)}
              <label class="checkbox-option" class:selected={(values[field.id] ?? []).includes(opt.value)}>
                <input
                  type="checkbox"
                  checked={(values[field.id] ?? []).includes(opt.value)}
                  onchange={() => toggleCheckbox(field.id, opt.value)}
                />
                <span class="option-label">{opt.label}</span>
              </label>
            {/each}
          </div>

        {:else if field.type === 'text'}
          <textarea
            class="text-field"
            placeholder={field.placeholder ?? ''}
            rows="2"
            oninput={(e) => { values = { ...values, [field.id]: /** @type {HTMLTextAreaElement} */ (e.currentTarget).value }; }}
          >{values[field.id] ?? ''}</textarea>
          {#if field.chips && field.chips.length > 0}
            <div class="chip-row">
              {#each field.chips as chip (chip)}
                <button type="button" class="chip" onclick={() => addChip(field.id, chip)}>
                  {chip}
                </button>
              {/each}
            </div>
          {/if}
        {/if}
      </div>
    {/each}
  </div>

  <!-- Actions -->
  <div class="brief-actions">
    <button class="cancel-btn" onclick={onCancel}>Отмена</button>
    <button class="run-btn" onclick={() => onRun(buildBrief())} disabled={!canRun}>
      Запустить анализ
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <path d="M5 12h14M12 5l7 7-7 7"/>
      </svg>
    </button>
  </div>
</div>

<style>
  .brief-panel {
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow: hidden;
    padding: 20px;
    animation: briefIn 200ms ease-out;
  }

  @keyframes briefIn {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  /* ── Header ── */
  .brief-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 20px;
    flex-shrink: 0;
  }

  .brief-back {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm, 6px);
    background: transparent;
    border: 1px solid var(--border, rgba(255,255,255,0.10));
    color: var(--text-muted, #7A7A90);
    cursor: pointer;
    transition: all var(--transition-fast, 150ms);
    flex-shrink: 0;
  }

  .brief-back:hover {
    background: var(--bg-tertiary, rgba(255,255,255,0.04));
    color: var(--text-primary, #EAEAF0);
    border-color: var(--border);
  }

  .brief-command {
    font-size: 15px;
    font-weight: var(--font-weight-heading);
    color: var(--accent-primary, #2E5BFF);
    font-family: var(--font-mono, 'JetBrains Mono', monospace);
    letter-spacing: -0.01em;
  }

  .brief-hint {
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
    margin-left: auto;
    white-space: nowrap;
  }

  /* ── Fields ── */
  .brief-fields {
    display: flex;
    flex-direction: column;
    gap: 20px;
    overflow-y: auto;
    flex: 1;
    padding-right: 2px;
  }

  .brief-field {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .field-label {
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--text-muted, #7A7A90);
  }

  /* ── Radio ── */
  .radio-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .radio-option {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 8px 12px;
    border-radius: var(--radius-chip);
    border: 1px solid transparent;
    cursor: pointer;
    transition: all var(--transition-fast, 150ms);
    user-select: none;
  }

  .radio-option:hover {
    background: var(--bg-card-hover, rgba(255,255,255,0.03));
  }

  .radio-option.selected {
    border-color: var(--accent-glow-strong);
    background: var(--accent-glow);
  }

  .radio-option input[type="radio"] {
    accent-color: var(--accent-primary, #2E5BFF);
    width: 14px;
    height: 14px;
    flex-shrink: 0;
    cursor: pointer;
  }

  /* ── Checkboxes ── */
  .checkbox-group {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
  }

  .checkbox-option {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 7px 13px;
    border-radius: var(--radius-chip);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    background: var(--bg-card, #181824);
    cursor: pointer;
    transition: all var(--transition-fast, 150ms);
    user-select: none;
  }

  .checkbox-option:hover {
    border-color: var(--accent-glow-strong);
    background: var(--hover-bg);
  }

  .checkbox-option.selected {
    border-color: var(--border-active);
    background: var(--accent-glow);
  }

  .checkbox-option input[type="checkbox"] {
    accent-color: var(--accent-primary, #2E5BFF);
    width: 13px;
    height: 13px;
    flex-shrink: 0;
    cursor: pointer;
  }

  .option-label {
    font-size: 12.5px;
    color: var(--text-secondary, #A8A8B8);
    transition: color var(--transition-fast, 150ms);
  }

  .radio-option.selected .option-label,
  .checkbox-option.selected .option-label {
    color: var(--text-primary, #EAEAF0);
  }

  /* ── Inline input (for radio "Конкретные") ── */
  .inline-input {
    flex: 1;
    min-width: 0;
    background: var(--input-bg, rgba(255,255,255,0.05));
    border: 1px solid var(--input-border, rgba(255,255,255,0.12));
    color: var(--text-primary, #EAEAF0);
    padding: 4px 10px;
    border-radius: var(--radius-input);
    font-size: 12px;
    font-family: inherit;
    transition: border-color var(--transition-fast, 150ms);
  }

  .inline-input:focus {
    outline: none;
    border-color: var(--border-active);
    box-shadow: 0 0 0 2px var(--accent-glow);
  }

  /* ── Text field ── */
  .text-field {
    background: var(--input-bg, rgba(255,255,255,0.05));
    border: 1px solid var(--input-border, rgba(255,255,255,0.12));
    color: var(--text-primary, #EAEAF0);
    padding: 10px 12px;
    border-radius: var(--radius-input);
    font-size: 13px;
    font-family: inherit;
    resize: none;
    line-height: 1.5;
    transition: border-color var(--transition-fast, 150ms);
  }

  .text-field::placeholder {
    color: var(--text-muted, #7A7A90);
  }

  .text-field:focus {
    outline: none;
    border-color: var(--border-active);
    box-shadow: 0 0 0 2px var(--accent-glow);
  }

  /* ── Chips ── */
  .chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }

  .chip {
    padding: 4px 11px;
    border-radius: var(--radius-chip);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    background: transparent;
    color: var(--text-muted, #7A7A90);
    font-size: 11.5px;
    font-family: inherit;
    cursor: pointer;
    transition: all var(--transition-fast, 150ms);
  }

  .chip:hover {
    border-color: var(--accent-glow-strong);
    color: var(--text-secondary, #A8A8B8);
    background: var(--hover-bg);
  }

  .chip:active {
    transform: scale(0.95);
    transition-duration: 60ms;
  }

  /* ── Actions ── */
  .brief-actions {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding-top: 16px;
    border-top: 1px solid var(--border, rgba(255,255,255,0.08));
    margin-top: 16px;
    flex-shrink: 0;
  }

  .cancel-btn {
    padding: 9px 18px;
    border-radius: var(--radius-btn);
    border: 1px solid var(--border, rgba(255,255,255,0.10));
    background: transparent;
    color: var(--text-secondary, #A8A8B8);
    font-size: 13px;
    font-family: inherit;
    cursor: pointer;
    transition: all var(--transition-fast, 150ms);
  }

  .cancel-btn:hover {
    background: var(--hover-bg, rgba(255,255,255,0.04));
    color: var(--text-primary, #EAEAF0);
    border-color: var(--border);
  }

  .run-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 20px;
    border-radius: var(--radius-btn);
    border: none;
    background: var(--gradient-primary);
    color: white;
    font-size: 13px;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    transition: all var(--transition-fast, 150ms);
  }

  .run-btn:hover:not(:disabled) {
    transform: translateY(-1px);
    filter: brightness(1.1);
    box-shadow: var(--shadow-glow);
  }

  .run-btn:active:not(:disabled) {
    transform: scale(0.97);
    transition-duration: 60ms;
  }

  .run-btn:disabled {
    opacity: 0.35;
    cursor: default;
  }
</style>
