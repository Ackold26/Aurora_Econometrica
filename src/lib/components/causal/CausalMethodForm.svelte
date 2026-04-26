<script>
  /**
   * CausalMethodForm — dynamic form для DiD/SCM/Causal Forest.
   * Renders fields based on selected method. Calls Rust invoke handler on submit.
   * @component
   */
  import { invoke } from '@tauri-apps/api/core';

  /**
   * @typedef {{
   *   method: 'did'|'scm'|'forest',
   *   projectDir: string,
   *   onResult: (result: any) => void,
   * }} Props
   */
  /** @type {Props} */
  let { method = $bindable('did'), projectDir = '', onResult } = $props();

  // Common fields
  let dataFile = $state('');
  let sheetName = $state('');
  let unitColumn = $state('');
  let timeColumn = $state('');
  let kpiColumn = $state('');

  // DiD-specific
  let treatmentColumn = $state('');
  let controlColumns = $state(''); // comma-separated

  // SCM-specific
  let treatedUnit = $state('');
  let treatmentPeriod = $state('');
  let runPlacebo = $state(true);

  // Forest-specific
  let featureColumns = $state(''); // comma-separated
  let confounderColumns = $state(''); // comma-separated

  let confidence = $state(0.9);
  let isRunning = $state(false);
  let errorMsg = $state('');

  const METHOD_LABELS = {
    did: 'DiD (TWFE)',
    scm: 'SCM (Abadie)',
    forest: 'Causal Forest',
  };

  const METHOD_HELP = {
    did: 'Difference-in-Differences с two-way fixed effects. Сравнивает treated и control units до/после treatment. Требует panel данные с treatment_column, ≥4 periods, ≥4 units, наличие control units.',
    scm: 'Synthetic Control Method (Abadie classic). Строит синтетический контроль для одного treated unit как взвешенную комбинацию donor units. Требует ≥6 pre-treatment periods, ≥3 donor units.',
    forest: 'Causal Forest (Wager-Athey 2018) для heterogeneous treatment effects. Surface которые сегменты получили больший эффект. Требует n≥100 observations + binary treatment + features.',
  };

  /** @param {string} s @returns {string[]} */
  function parseList(s) {
    return s.split(',').map(/** @param {string} x */ (x) => x.trim()).filter(Boolean);
  }

  /** @param {SubmitEvent} [event] */
  async function runMethod(event) {
    event?.preventDefault();
    errorMsg = '';
    if (!projectDir) {
      errorMsg = 'Не выбран project_dir';
      return;
    }
    if (!dataFile) {
      errorMsg = 'Укажи путь к файлу данных';
      return;
    }
    isRunning = true;
    try {
      let cmd = '';
      /** @type {Record<string, any>} */
      let cfg = {
        project_dir: projectDir,
        data_file: dataFile,
        kpi_column: kpiColumn,
        sheet_name: sheetName || null,
        confidence: Number(confidence) || 0.9,
      };

      if (method === 'did') {
        cmd = 'econ_causal_did';
        cfg.unit_column = unitColumn;
        cfg.time_column = timeColumn;
        cfg.treatment_column = treatmentColumn;
        cfg.control_columns = parseList(controlColumns);
      } else if (method === 'scm') {
        cmd = 'econ_causal_scm';
        cfg.unit_column = unitColumn;
        cfg.time_column = timeColumn;
        cfg.treated_unit = treatedUnit;
        cfg.treatment_period = treatmentPeriod;
        cfg.run_placebo = runPlacebo;
      } else if (method === 'forest') {
        cmd = 'econ_causal_forest';
        cfg.treatment_column = treatmentColumn;
        cfg.feature_columns = parseList(featureColumns);
        const conf = parseList(confounderColumns);
        cfg.confounder_columns = conf.length > 0 ? conf : null;
        cfg.unit_column = unitColumn || null;
        cfg.time_column = timeColumn || null;
      }

      const result = await invoke(cmd, { config: cfg });
      onResult(result);
    } catch (e) {
      errorMsg = String(e);
    } finally {
      isRunning = false;
    }
  }
</script>

<form class="causal-form" onsubmit={runMethod}>
  <div class="method-selector">
    {#each Object.entries(METHOD_LABELS) as [m, label]}
      <button
        type="button"
        class:active={method === m}
        onclick={() => (method = /** @type {'did'|'scm'|'forest'} */ (m))}
        disabled={isRunning}
      >
        {label}
      </button>
    {/each}
  </div>

  <p class="method-help">{METHOD_HELP[method]}</p>

  <div class="form-grid">
    <label>
      Файл данных (xlsx/csv)
      <input type="text" bind:value={dataFile} placeholder="C:/path/to/panel_data.xlsx" required />
    </label>

    <label>
      Sheet name (для xlsx, опционально)
      <input type="text" bind:value={sheetName} placeholder="например 'Афала'" />
    </label>

    <label>
      KPI column
      <input type="text" bind:value={kpiColumn} placeholder="kpi или 'Продажи в руб.'" required />
    </label>

    {#if method !== 'forest' || unitColumn || timeColumn}
      <label>
        Unit column (region/city)
        <input type="text" bind:value={unitColumn} placeholder="region" required={method !== 'forest'} />
      </label>

      <label>
        Time column
        <input type="text" bind:value={timeColumn} placeholder="period или 'date'" required={method !== 'forest'} />
      </label>
    {/if}

    {#if method === 'did' || method === 'forest'}
      <label>
        Treatment column (binary 0/1)
        <input type="text" bind:value={treatmentColumn} placeholder="treated" required />
      </label>
    {/if}

    {#if method === 'did'}
      <label>
        Control columns (comma-separated, опционально)
        <input type="text" bind:value={controlColumns} placeholder="x1, x2, x3" />
      </label>
    {/if}

    {#if method === 'scm'}
      <label>
        Treated unit (имя региона)
        <input type="text" bind:value={treatedUnit} placeholder="region_0" required />
      </label>

      <label>
        Treatment period (значение в time_column для split)
        <input type="text" bind:value={treatmentPeriod} placeholder="2024-06 или 13" required />
      </label>

      <label class="checkbox-label">
        <input type="checkbox" bind:checked={runPlacebo} />
        Запустить placebo permutation (для p-value)
      </label>
    {/if}

    {#if method === 'forest'}
      <label>
        Feature columns (heterogeneity drivers)
        <input type="text" bind:value={featureColumns} placeholder="age, income, region_size" required />
      </label>

      <label>
        Confounder columns (опционально)
        <input type="text" bind:value={confounderColumns} placeholder="seasonality, prior_brand_awareness" />
      </label>
    {/if}

    <label>
      Confidence (0-1)
      <input type="number" min="0.5" max="0.99" step="0.05" bind:value={confidence} />
    </label>
  </div>

  {#if errorMsg}
    <div class="error-banner">{errorMsg}</div>
  {/if}

  <button type="submit" class="submit-btn" disabled={isRunning}>
    {isRunning ? 'Считаю…' : `Запустить ${METHOD_LABELS[method]}`}
  </button>
</form>

<style>
  .causal-form {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    padding: 1.5rem;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.92));
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .method-selector {
    display: flex;
    gap: 0.5rem;
  }

  .method-selector button {
    flex: 1;
    padding: 0.625rem 1rem;
    border: 1px solid var(--border-default, #d1d5db);
    background: var(--bg-elevated, #fff);
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.875rem;
    transition: all 0.15s;
  }

  .method-selector button:hover:not(:disabled) {
    background: var(--bg-hover, #f3f4f6);
  }

  .method-selector button.active {
    background: var(--accent, #3b82f6);
    color: #fff;
    border-color: var(--accent, #3b82f6);
  }

  .method-help {
    margin: 0;
    padding: 0.75rem 1rem;
    background: var(--bg-info-soft, #eff6ff);
    border-left: 3px solid var(--accent, #3b82f6);
    color: var(--text-secondary, #4b5563);
    font-size: 0.875rem;
    line-height: 1.5;
    border-radius: 4px;
  }

  .form-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.875rem;
    color: var(--text-primary, #111827);
  }

  .checkbox-label {
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
  }

  input[type="text"], input[type="number"] {
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--border-default, #d1d5db);
    border-radius: 6px;
    font-size: 0.875rem;
    font-family: inherit;
  }

  .error-banner {
    padding: 0.75rem 1rem;
    background: var(--danger-soft, #fee2e2);
    color: var(--danger, #dc2626);
    border-radius: 6px;
    font-size: 0.875rem;
  }

  .submit-btn {
    align-self: flex-start;
    padding: 0.75rem 1.5rem;
    background: var(--accent, #3b82f6);
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 0.9375rem;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s;
  }

  .submit-btn:hover:not(:disabled) {
    background: var(--accent-hover, #2563eb);
  }

  .submit-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
