<script>
  /**
   * StepPlanInputs — Wizard Step 4: task-specific plan inputs.
   *
   * 5 variants keyed by taskType:
   *   A) budget_optimization   — плановый бюджет + период + channel constraints
   *   B) inverse_optimization  — goal-seek: absolute or relative target + period
   *   C) what_if               — budget range: ±20% / ±50% / Custom + period
   *   D) forecast_planned_activities — upload planned activities file + optional non-media
   *   E) decompose-only        — no inputs; info card only
   *
   * РФ-monthly default per Q-fin-1 / INV-30.
   * Validation is per-variant; «Далее →» enabled only when valid.
   *
   * @component StepPlanInputs
   */

  import {
    DollarSign,
    Calendar,
    Target,
    Activity,
    FileLineChart,
    ChevronRight,
    Info,
    AlertCircle,
    CheckCircle,
    AlertTriangle,
  } from 'lucide-svelte';
  import { wizardState } from '$lib/wizard-state.js';
  import { kpiType } from '$lib/project-state.js';

  /**
   * @typedef {'budget_optimization'|'inverse_optimization'|'what_if'|'forecast_planned_activities'|'decompose-only'} TaskType
   */

  /**
   * @type {{
   *   taskType: TaskType,
   *   onSubmit: (data: Record<string, any>) => void,
   * }}
   */
  const { taskType, onSubmit } = $props();

  // ─── Shared: period state ───
  /** @type {number} */
  let periodCount = $state(12);
  /** @type {'months'|'weeks'} */
  let periodUnit  = $state('months'); // РФ-monthly default per Q-fin-1

  // ─── Variant A: budget_optimization ───
  /** @type {string} Budget in ₽ (string to allow empty) */
  let budgetInput  = $state('50000000');
  /** Show channel constraints table */
  let showChannelConstraints = $state(false);
  /** @type {Array<{channel: string, minPct: string, maxPct: string}>} */
  let channelConstraints = $state([]);

  // ─── Variant B: inverse_optimization ───
  /** @type {'absolute'|'relative'} */
  let goalType     = $state('relative');
  /** Absolute value (units) */
  let goalAbsolute = $state('');
  /** Relative increment, % */
  let goalRelative = $state('10');

  // ─── Variant C: what_if ───
  /** @type {'±20'|'±50'|'custom'} */
  let rangePreset  = $state('±50');
  let rangeFrom    = $state('');
  let rangeTo      = $state('');

  // ─── Variant D: forecast_planned_activities ───
  /** @type {File|null} */
  let uploadedFile = $state(null);
  /** @type {Array<{text: string, status: 'ok'|'warn'|'ignore'}>} */
  let fileValidations = $state([]);
  /** @type {'none'|'specify'} */
  let nonMediaPlan = $state('none');
  let nonMediaDistribution = $state('');
  let nonMediaTrade        = $state('');
  let nonMediaPrice        = $state('');

  // ─── Derived: kpi unit label for variant B ───
  const kpiUnitLabel = $derived.by(() => {
    const type = $kpiType;
    if (type === 'sales_packs') return 'упаковок';
    if (type === 'leads') return 'лидов';
    if (type === 'registrations') return 'регистраций';
    if (type === 'subscriptions') return 'подписок';
    if (type === 'app_installs') return 'установок';
    if (type === 'transactions') return 'транзакций';
    if (type === 'traffic') return 'визитов';
    return 'единиц';
  });

  // ─── Validation logic ───
  /** @type {string|null} */
  const validationError = $derived.by(() => {
    if (taskType === 'budget_optimization') {
      const v = parseFloat(budgetInput.replace(/\s/g, '').replace(',', '.'));
      if (!budgetInput || isNaN(v) || v <= 0) return 'Введите положительный бюджет в ₽';
      return null;
    }
    if (taskType === 'inverse_optimization') {
      if (goalType === 'absolute') {
        const v = parseFloat(goalAbsolute);
        if (!goalAbsolute || isNaN(v) || v <= 0) return 'Введите положительное целевое значение';
        return null;
      } else {
        const v = parseFloat(goalRelative);
        if (!goalRelative || isNaN(v) || v <= -100 || v >= 1000)
          return 'Введите прирост в диапазоне от -100% до +1000%';
        return null;
      }
    }
    if (taskType === 'what_if') {
      if (rangePreset === 'custom') {
        const lo = parseFloat(rangeFrom);
        const hi = parseFloat(rangeTo);
        if (!rangeFrom || isNaN(lo) || lo <= 0) return 'Введите нижнюю границу (₽)';
        if (!rangeTo  || isNaN(hi) || hi <= 0) return 'Введите верхнюю границу (₽)';
        if (lo >= hi) return 'Нижняя граница должна быть меньше верхней';
        return null;
      }
      return null;
    }
    if (taskType === 'forecast_planned_activities') {
      if (!uploadedFile) return 'Загрузите файл с плановыми активностями';
      return null;
    }
    // decompose-only — no validation
    return null;
  });

  const isValid = $derived(validationError === null);

  // ─── Handlers ───

  /** @param {Event} e */
  function handleFileUpload(e) {
    const input = /** @type {HTMLInputElement} */ (e.target);
    const file = input.files?.[0] ?? null;
    uploadedFile = file;
    if (file) {
      // Simulate validation feedback (real validation in backend)
      fileValidations = [
        { text: 'Каналы соответствуют trained model', status: 'ok' },
        { text: 'Период покрывает плановый горизонт', status: 'ok' },
        { text: 'Канал «Print» отсутствует в trained model — будет проигнорирован', status: 'warn' },
      ];
    } else {
      fileValidations = [];
    }
  }

  function handleSubmit() {
    if (!isValid) return;

    /** @type {Record<string, any>} */
    const data = {
      taskType,
      periodCount,
      periodUnit,
    };

    if (taskType === 'budget_optimization') {
      data.budgetRub = parseFloat(budgetInput.replace(/\s/g, '').replace(',', '.'));
      data.channelConstraints = showChannelConstraints ? channelConstraints : [];
    }
    if (taskType === 'inverse_optimization') {
      data.goalType     = goalType;
      data.goalAbsolute = goalType === 'absolute' ? parseFloat(goalAbsolute) : null;
      data.goalRelative = goalType === 'relative' ? parseFloat(goalRelative) : null;
    }
    if (taskType === 'what_if') {
      data.rangePreset = rangePreset;
      if (rangePreset === 'custom') {
        data.rangeFrom = parseFloat(rangeFrom);
        data.rangeTo   = parseFloat(rangeTo);
      }
    }
    if (taskType === 'forecast_planned_activities') {
      data.uploadedFileName = uploadedFile?.name ?? null;
      data.nonMediaPlan     = nonMediaPlan;
      if (nonMediaPlan === 'specify') {
        data.nonMediaDistribution = nonMediaDistribution;
        data.nonMediaTrade        = nonMediaTrade;
        data.nonMediaPrice        = nonMediaPrice;
      }
    }
    // decompose-only: no extra fields

    onSubmit(data);
  }

  /** @param {number} v */
  function formatRub(v) {
    if (!v || isNaN(v)) return '';
    return new Intl.NumberFormat('ru-RU').format(v);
  }
</script>

<div class="step-plan-inputs">
  <!-- ─────── Variant E: decompose-only ─────── -->
  {#if taskType === 'decompose-only'}
    <div class="info-card variant-info">
      <div class="info-card-icon"><FileLineChart size={32} strokeWidth={1.5} /></div>
      <div class="info-card-body">
        <h3 class="info-card-title">Декомпозиция работает без планов</h3>
        <p class="info-card-desc">
          Для декомпозиции прошлого периода плановые вводы не нужны.
          Модель использует только исторические данные.
          Нажмите «Далее →» чтобы перейти к подтверждению.
        </p>
      </div>
    </div>

  <!-- ─────── Variant A: budget_optimization ─────── -->
  {:else if taskType === 'budget_optimization'}
    <div class="section">
      <label class="field-label" for="budget-input">
        <DollarSign size={14} strokeWidth={2} />
        Плановый бюджет на следующий период
      </label>
      <div class="input-row">
        <input
          id="budget-input"
          class="text-input rub-input"
          type="text"
          inputmode="numeric"
          placeholder="50 000 000"
          bind:value={budgetInput}
          aria-describedby="budget-hint"
        />
        <span class="unit-label">₽</span>
      </div>
      <p id="budget-hint" class="field-hint">
        Ориентир: средний бюджет последней активной кампании — 50 млн ₽
      </p>
    </div>

    <div class="section">
      <label class="field-label">
        <Calendar size={14} strokeWidth={2} />
        Период оптимизации
      </label>
      <div class="period-row">
        <input
          class="text-input period-count"
          type="number"
          min="1"
          max="120"
          bind:value={periodCount}
          aria-label="Количество периодов"
        />
        <select class="select-input period-unit" bind:value={periodUnit} aria-label="Единица периода">
          <option value="months">месяцев</option>
          <option value="weeks">недель</option>
        </select>
      </div>
      <p class="field-hint">По умолчанию — 12 месяцев (РФ-стандарт MMM)</p>
    </div>

    <div class="section">
      <div class="toggle-row">
        <span class="field-label" style="margin-bottom:0;">
          <Activity size={14} strokeWidth={2} />
          Дополнительные ограничения по каналам?
        </span>
        <div class="btn-group">
          <button
            type="button"
            class="btn-secondary"
            class:active={!showChannelConstraints}
            onclick={() => (showChannelConstraints = false)}
          >
            Skip
          </button>
          <button
            type="button"
            class="btn-secondary"
            class:active={showChannelConstraints}
            onclick={() => (showChannelConstraints = true)}
          >
            Указать
          </button>
        </div>
      </div>

      {#if showChannelConstraints}
        <div class="constraints-panel">
          <p class="field-hint">Укажите min/max долю бюджета для каждого канала (%). Оставьте пустым для без ограничений.</p>
          <table class="constraints-table">
            <thead>
              <tr>
                <th>Канал</th>
                <th>Min, %</th>
                <th>Max, %</th>
              </tr>
            </thead>
            <tbody>
              {#each channelConstraints as row, i}
                <tr>
                  <td><input class="text-input small" type="text" bind:value={channelConstraints[i].channel} placeholder="TV" /></td>
                  <td><input class="text-input small" type="number" min="0" max="100" bind:value={channelConstraints[i].minPct} placeholder="0" /></td>
                  <td><input class="text-input small" type="number" min="0" max="100" bind:value={channelConstraints[i].maxPct} placeholder="100" /></td>
                </tr>
              {/each}
            </tbody>
          </table>
          <button
            type="button"
            class="btn-ghost add-row-btn"
            onclick={() => channelConstraints = [...channelConstraints, { channel: '', minPct: '', maxPct: '' }]}
          >
            + Добавить канал
          </button>
        </div>
      {/if}
    </div>

  <!-- ─────── Variant B: inverse_optimization ─────── -->
  {:else if taskType === 'inverse_optimization'}
    <div class="section">
      <label class="field-label">
        <Target size={14} strokeWidth={2} />
        Целевое значение
      </label>

      <div class="radio-group">
        <label class="radio-row">
          <input type="radio" name="goalType" value="absolute" bind:group={goalType} />
          <span class="radio-label">Абсолютное:</span>
          <input
            class="text-input inline-input"
            type="number"
            min="0"
            placeholder="100 000"
            bind:value={goalAbsolute}
            disabled={goalType !== 'absolute'}
            aria-label="Целевое значение в единицах"
          />
          <span class="unit-label">{kpiUnitLabel}</span>
        </label>

        <label class="radio-row">
          <input type="radio" name="goalType" value="relative" bind:group={goalType} />
          <span class="radio-label">Прирост:</span>
          <div class="relative-input-wrap">
            <span class="prefix-sign">+</span>
            <input
              class="text-input inline-input prefix-input"
              type="number"
              placeholder="10"
              bind:value={goalRelative}
              disabled={goalType !== 'relative'}
              aria-label="Прирост в процентах"
            />
          </div>
          <span class="unit-label">%</span>
        </label>
      </div>
      <p class="field-hint">По умолчанию: прирост +10%</p>
    </div>

    <div class="section">
      <label class="field-label">
        <Calendar size={14} strokeWidth={2} />
        Период
      </label>
      <div class="period-row">
        <input
          class="text-input period-count"
          type="number"
          min="1"
          max="120"
          bind:value={periodCount}
          aria-label="Количество периодов"
        />
        <select class="select-input period-unit" bind:value={periodUnit} aria-label="Единица периода">
          <option value="months">месяцев</option>
          <option value="weeks">недель</option>
        </select>
      </div>
      <p class="field-hint">По умолчанию — 12 месяцев</p>
    </div>

  <!-- ─────── Variant C: what_if ─────── -->
  {:else if taskType === 'what_if'}
    <div class="section">
      <label class="field-label">
        <Activity size={14} strokeWidth={2} />
        Диапазон бюджетов для сравнения
      </label>

      <div class="radio-group">
        <label class="radio-row">
          <input type="radio" name="rangePreset" value="±20" bind:group={rangePreset} />
          <span class="radio-label">Базовый ±20%</span>
        </label>
        <label class="radio-row">
          <input type="radio" name="rangePreset" value="±50" bind:group={rangePreset} />
          <span class="radio-label">Базовый ±50%</span>
        </label>
        <label class="radio-row">
          <input type="radio" name="rangePreset" value="custom" bind:group={rangePreset} />
          <span class="radio-label">Custom:</span>
          <span class="custom-range-inputs">
            от
            <input
              class="text-input inline-input"
              type="number"
              min="0"
              placeholder="20 000 000"
              bind:value={rangeFrom}
              disabled={rangePreset !== 'custom'}
              aria-label="Нижняя граница бюджета"
            />
            до
            <input
              class="text-input inline-input"
              type="number"
              min="0"
              placeholder="80 000 000"
              bind:value={rangeTo}
              disabled={rangePreset !== 'custom'}
              aria-label="Верхняя граница бюджета"
            />
            <span class="unit-label">₽</span>
          </span>
        </label>
      </div>
    </div>

    <div class="section">
      <label class="field-label">
        <Calendar size={14} strokeWidth={2} />
        Период
      </label>
      <div class="period-row">
        <input
          class="text-input period-count"
          type="number"
          min="1"
          max="120"
          bind:value={periodCount}
          aria-label="Количество периодов"
        />
        <select class="select-input period-unit" bind:value={periodUnit} aria-label="Единица периода">
          <option value="months">месяцев</option>
          <option value="weeks">недель</option>
        </select>
      </div>
      <p class="field-hint">По умолчанию — 12 месяцев</p>
    </div>

  <!-- ─────── Variant D: forecast_planned_activities ─────── -->
  {:else if taskType === 'forecast_planned_activities'}
    <div class="section">
      <label class="field-label">
        <FileLineChart size={14} strokeWidth={2} />
        Загрузите файл с плановыми активностями
      </label>

      <div class="upload-zone" class:has-file={uploadedFile !== null}>
        <label class="upload-label" for="plan-file-input">
          {#if uploadedFile}
            <CheckCircle size={20} strokeWidth={1.5} class="upload-icon ok" />
            <span class="upload-filename">{uploadedFile.name}</span>
            <span class="upload-replace">Заменить</span>
          {:else}
            <FileLineChart size={24} strokeWidth={1.5} class="upload-icon" />
            <span class="upload-prompt">Выбрать Excel</span>
            <span class="upload-hint">.xlsx — плановые активности по каналам</span>
          {/if}
        </label>
        <input
          id="plan-file-input"
          type="file"
          accept=".xlsx,.xls,.csv"
          class="file-input-hidden"
          onchange={handleFileUpload}
          aria-label="Файл плановых активностей"
        />
      </div>

      <div class="upload-actions">
        <a href="#template" class="btn-ghost btn-sm" onclick={(e) => e.preventDefault()}>
          Excel template
        </a>
        <button type="button" class="btn-ghost btn-sm">
          Manual entry
        </button>
      </div>

      {#if fileValidations.length > 0}
        <ul class="validation-list" role="list" aria-label="Результаты проверки файла">
          {#each fileValidations as item}
            <li class="validation-item validation-{item.status}">
              {#if item.status === 'ok'}
                <CheckCircle size={14} strokeWidth={2} />
              {:else if item.status === 'warn'}
                <AlertTriangle size={14} strokeWidth={2} />
              {:else}
                <Info size={14} strokeWidth={2} />
              {/if}
              {item.text}
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <div class="section">
      <label class="field-label">
        <Activity size={14} strokeWidth={2} />
        Изменения non-media в плановом периоде
      </label>

      <div class="radio-group">
        <label class="radio-row">
          <input type="radio" name="nonMediaPlan" value="none" bind:group={nonMediaPlan} />
          <span class="radio-label">Без изменений (по умолчанию)</span>
        </label>
        <label class="radio-row">
          <input type="radio" name="nonMediaPlan" value="specify" bind:group={nonMediaPlan} />
          <span class="radio-label">Указать плановые значения</span>
        </label>
      </div>

      {#if nonMediaPlan === 'specify'}
        <div class="non-media-fields">
          <label class="field-label-sm" for="nm-distribution">Дистрибуция (плановая)</label>
          <input
            id="nm-distribution"
            class="text-input"
            type="text"
            placeholder="0.85"
            bind:value={nonMediaDistribution}
          />
          <label class="field-label-sm" for="nm-trade">Trade activity (плановая)</label>
          <input
            id="nm-trade"
            class="text-input"
            type="text"
            placeholder="3.5"
            bind:value={nonMediaTrade}
          />
          <label class="field-label-sm" for="nm-price">Цена (плановая, ₽)</label>
          <input
            id="nm-price"
            class="text-input"
            type="text"
            placeholder="250"
            bind:value={nonMediaPrice}
          />
        </div>
      {/if}
    </div>
  {/if}

  <!-- ─────── Validation error ─────── -->
  {#if validationError !== null}
    <div class="error-banner" role="alert">
      <AlertCircle size={15} strokeWidth={2} />
      {validationError}
    </div>
  {/if}

  <!-- ─────── Submit ─────── -->
  <div class="step-footer">
    <button
      type="button"
      class="btn-primary submit-btn"
      onclick={handleSubmit}
      disabled={!isValid}
      aria-disabled={!isValid}
    >
      Далее
      <ChevronRight size={16} strokeWidth={2} />
    </button>
  </div>
</div>

<style>
  .step-plan-inputs {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 20px 24px;
    max-width: 720px;
    margin: 0 auto;
    width: 100%;
  }

  /* ─── Sections ─── */
  .section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .field-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 2px;
    cursor: default;
  }
  .field-label-sm {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
    margin: 6px 0 2px;
  }

  .field-hint {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    margin: 0;
    line-height: 1.5;
  }

  /* ─── Text inputs ─── */
  .text-input {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    border-radius: var(--radius-sm, 8px);
    color: var(--text-primary);
    font-size: 14px;
    padding: 9px 12px;
    outline: none;
    transition: border-color 0.18s;
    font-family: inherit;
    width: 100%;
    box-sizing: border-box;
  }
  .text-input:focus {
    border-color: var(--gold, #c9a449);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--gold, #c9a449) 20%, transparent);
  }
  .text-input:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .text-input.small {
    padding: 6px 8px;
    font-size: 12.5px;
  }

  .select-input {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    border-radius: var(--radius-sm, 8px);
    color: var(--text-primary);
    font-size: 14px;
    padding: 9px 12px;
    outline: none;
    cursor: pointer;
    font-family: inherit;
    transition: border-color 0.18s;
  }
  .select-input:focus {
    border-color: var(--gold, #c9a449);
  }

  /* ─── Layout helpers ─── */
  .input-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .input-row .text-input {
    flex: 1;
  }

  .period-row {
    display: flex;
    gap: 8px;
  }
  .period-count {
    width: 90px;
    flex: 0 0 90px;
  }
  .period-unit {
    flex: 1;
  }

  .unit-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary);
    white-space: nowrap;
    flex-shrink: 0;
  }

  .rub-input {
    max-width: 220px;
  }

  /* ─── Radio group ─── */
  .radio-group {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .radio-row {
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
  }
  .radio-row input[type="radio"] {
    accent-color: var(--gold, #c9a449);
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    cursor: pointer;
  }
  .radio-label {
    font-size: 13px;
    color: var(--text-secondary);
    font-weight: 500;
    white-space: nowrap;
  }

  .inline-input {
    width: 130px;
    flex: 0 0 130px;
  }

  .relative-input-wrap {
    position: relative;
    display: flex;
    align-items: center;
  }
  .prefix-sign {
    position: absolute;
    left: 10px;
    font-size: 14px;
    font-weight: 600;
    color: var(--gold, #c9a449);
    pointer-events: none;
    z-index: 1;
  }
  .prefix-input {
    padding-left: 22px !important;
  }

  .custom-range-inputs {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-secondary);
    flex-wrap: wrap;
  }

  /* ─── Channel constraints ─── */
  .constraints-panel {
    padding: 14px;
    background: var(--bg-surface-quiet, rgba(20,20,30,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .constraints-table {
    border-collapse: collapse;
    width: 100%;
    font-size: 12.5px;
  }
  .constraints-table th {
    text-align: left;
    color: var(--text-muted, #7A7A90);
    font-weight: 600;
    padding: 4px 8px 8px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  .constraints-table td {
    padding: 4px 8px;
  }

  /* ─── Toggle btn-group ─── */
  .toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }
  .btn-group {
    display: flex;
    gap: 4px;
  }

  /* ─── Upload zone ─── */
  .upload-zone {
    position: relative;
    border: 2px dashed var(--border, rgba(255,255,255,0.12));
    border-radius: var(--radius-card, 12px);
    background: var(--bg-card, #181824);
    transition: border-color 0.18s, background 0.18s;
    cursor: pointer;
  }
  .upload-zone:hover,
  .upload-zone:focus-within {
    border-color: var(--gold, #c9a449);
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, var(--bg-card, #181824));
  }
  .upload-zone.has-file {
    border-style: solid;
    border-color: var(--success, #22c55e);
  }
  .upload-label {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px 16px;
    cursor: pointer;
    min-height: 100px;
  }
  .upload-prompt {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .upload-hint {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
  }
  .upload-filename {
    font-size: 13px;
    font-weight: 600;
    color: var(--success, #22c55e);
  }
  .upload-replace {
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
    text-decoration: underline dashed;
    text-underline-offset: 2px;
  }
  .file-input-hidden {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
    width: 100%;
    height: 100%;
  }

  .upload-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }

  /* ─── File validation list ─── */
  .validation-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .validation-item {
    display: flex;
    align-items: flex-start;
    gap: 7px;    font-size: 12.5px;
    line-height: 1.5;
  }
  .validation-ok   { color: var(--success, #22c55e); }
  .validation-warn { color: var(--warning, #F59E0B); }
  .validation-ignore { color: var(--text-muted, #7A7A90); }

  /* ─── Non-media fields ─── */
  .non-media-fields {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px;
    background: var(--bg-surface-quiet, rgba(20,20,30,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
  }

  /* ─── Variant E info card ─── */
  .info-card {
    display: flex;
    gap: 16px;
    align-items: flex-start;
    padding: 20px;
    border-radius: var(--radius-card, 12px);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    background: var(--bg-card, #181824);
  }
  .variant-info {
    background: color-mix(in srgb, var(--gold, #c9a449) 6%, var(--bg-card, #181824));
    border-color: color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
  }
  .info-card-icon {
    flex-shrink: 0;
    width: 52px;
    height: 52px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 10px;
    background: color-mix(in srgb, var(--gold, #c9a449) 12%, var(--bg-secondary, #141420));
    color: var(--gold, #c9a449);
  }
  .info-card-body {
    flex: 1;
  }
  .info-card-title {
    font-size: 15px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0 0 6px;
  }
  .info-card-desc {
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.6;
    margin: 0;
  }

  /* ─── Buttons ─── */
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
    transition: background 0.15s, opacity 0.15s, transform 0.1s;
  }
  .btn-primary:hover:not(:disabled) {
    background: color-mix(in srgb, var(--gold, #c9a449) 85%, white);
    transform: translateY(-1px);
  }
  .btn-primary:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .btn-secondary {
    padding: 7px 14px;
    background: var(--bg-surface-quiet, rgba(20,20,30,0.92));
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    border-radius: var(--radius-sm, 8px);
    color: var(--text-secondary);
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
    font-family: inherit;
  }
  .btn-secondary:hover { border-color: var(--gold, #c9a449); color: var(--text-primary); }
  .btn-secondary.active {
    border-color: var(--gold, #c9a449);
    color: var(--gold, #c9a449);
    background: color-mix(in srgb, var(--gold, #c9a449) 10%, var(--bg-card, #181824));
    font-weight: 600;
  }

  .btn-ghost {
    background: none;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
    color: var(--text-muted, #7A7A90);
    font-size: 12px;
    font-weight: 500;
    padding: 6px 12px;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
    font-family: inherit;
    text-decoration: none;
  }
  .btn-ghost:hover { border-color: var(--border, rgba(255,255,255,0.1)); color: var(--text-secondary); }
  .btn-sm { padding: 5px 10px; font-size: 11.5px; }

  .add-row-btn {
    align-self: flex-start;
  }

  /* ─── Error banner ─── */
  .error-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--danger, #ef4444) 10%, var(--bg-card, #181824));
    border: 1px solid color-mix(in srgb, var(--danger, #ef4444) 40%, transparent);
    border-radius: var(--radius-sm, 8px);
    color: var(--danger, #ef4444);
    font-size: 12.5px;
    font-weight: 500;
  }

  /* ─── Footer ─── */
  .step-footer {
    display: flex;
    justify-content: flex-end;
    padding-top: 8px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }

  .submit-btn {
    min-width: 130px;
    justify-content: center;
  }
</style>
