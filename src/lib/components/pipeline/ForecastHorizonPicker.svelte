<!--
  ForecastHorizonPicker — Phase 2 Planning Mode horizon selector.

  Audit pass 2 (2026-05-02): minimal viable per S6 unification — preset buttons +
  custom periods input + budget input. Calendar timeline + start_date picker
  deferred к Phase 2.5 (per L3 — REQUIRE start_date input only when seasonality
  detected; for v1.2.0 ship: surface seasonality warning via alert if needed).

  Smart suggestions derived from forecast-context endpoint:
    - granularity → preset labels (Год/Полугодие/Квартал/Custom)
    - train_n × max_multiplier → cap on custom periods input
    - seasonality detected → warning «требуется указать дату начала»

  Math reference: docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md §10 S6, L3.
-->
<script>
  import { forecastConfig, forecastContext } from '$lib/project-state.js';

  /** @type {{
   *   trainNPeriods: number,
   *   currentBudgetMoney: number,
   *   onChange?: (cfg: { periods: number, periodLabel: string, budgetMoney: number }) => void,
   * }} */
  let { trainNPeriods, currentBudgetMoney, onChange } = $props();

  // Periods-per-horizon-label resolved by granularity
  const presets = $derived.by(() => {
    const ctx = $forecastContext;
    const gran = ctx?.training_granularity || 'W';
    /** @type {Record<string, Record<string, number>>} */
    const map = {
      D: { 'Квартал': 90, 'Полугодие': 180, 'Год': 365 },
      W: { 'Квартал': 13, 'Полугодие': 26, 'Год': 52 },
      M: { 'Квартал': 3, 'Полугодие': 6, 'Год': 12 },
      Q: { 'Полугодие': 2, 'Год': 4 },
      Y: { '2 года': 2, '3 года': 3 },
    };
    return Object.entries(map[gran] ?? map.W).map(([label, n]) => ({ label, n }));
  });

  const maxMult = $derived($forecastContext?.forecast_horizon_max_multiplier ?? 2.0);
  const warnMult = $derived($forecastContext?.forecast_horizon_warn_multiplier ?? 1.5);
  const maxCustom = $derived(Math.floor(trainNPeriods * maxMult));
  const warnCustom = $derived(Math.floor(trainNPeriods * warnMult));

  let selectedPreset = $state(/** @type {string|null} */ (null));
  let customPeriods = $state(/** @type {number|null} */ (null));
  let budgetInput = $state(/** @type {number|null} */ (null));

  // Auto-suggest budget when periods change (proportional to training)
  /** @param {number | null} periods */
  function suggestBudget(periods) {
    if (!periods || periods < 1 || trainNPeriods < 1) return null;
    return Math.round(currentBudgetMoney * (periods / trainNPeriods));
  }

  /** @param {string} label @param {number} n */
  function selectPreset(label, n) {
    selectedPreset = label;
    customPeriods = n;
    if (budgetInput == null) budgetInput = suggestBudget(n);
    emitChange();
  }

  function onCustomChange() {
    selectedPreset = null;
    if (customPeriods != null && customPeriods > 0 && budgetInput == null) {
      budgetInput = suggestBudget(customPeriods);
    }
    emitChange();
  }

  function emitChange() {
    if (customPeriods == null || customPeriods < 1 || budgetInput == null || budgetInput <= 0) {
      forecastConfig.update(c => ({ ...c, periods: null, periodLabel: null, budgetMoney: null }));
      return;
    }
    // Audit pass 3 fix (BUG 19): force integer для Tauri Option<i64> compat.
    // step={1} on input не блокирует typed decimals в некоторых browsers.
    const periodsInt = Math.floor(Number(customPeriods));
    if (!Number.isFinite(periodsInt) || periodsInt < 1) {
      forecastConfig.update(c => ({ ...c, periods: null, periodLabel: null, budgetMoney: null }));
      return;
    }
    const cfg = {
      periods: periodsInt,
      periodLabel: selectedPreset || `${periodsInt} periods`,
      budgetMoney: budgetInput,
    };
    forecastConfig.update(c => ({ ...c, ...cfg }));
    onChange?.(cfg);
  }

  const seasonalityWarning = $derived.by(() => {
    const s = $forecastContext?.seasonality_detected;
    if (!s) return null;
    return `Обнаружена сезонность период=${s.period} (autocorr ${s.autocorr.toFixed(2)}). Прогноз с ${customPeriods} периодов даст разные результаты в зависимости от месяца старта — see methodology.`;
  });

  const horizonWarning = $derived.by(() => {
    if (customPeriods == null) return null;
    if (customPeriods > maxCustom) {
      return `Период ${customPeriods} превышает разрешённый максимум ${maxCustom} (${maxMult.toFixed(1)}× обучающего). Допущение стационарности нарушено.`;
    }
    if (customPeriods > warnCustom) {
      return `Период ${customPeriods} больше ${warnMult.toFixed(1)}× обучающего (${warnCustom}). Используйте только пропорции каналов; абсолютные ROI прогнозы менее точны.`;
    }
    return null;
  });
</script>

<section class="forecast-horizon-picker">
  <h3>Период планирования</h3>

  <div class="presets" role="group" aria-label="Быстрый выбор периода">
    {#each presets as preset}
      <button
        type="button"
        class="preset"
        class:active={selectedPreset === preset.label}
        onclick={() => selectPreset(preset.label, preset.n)}
      >
        <span class="preset-label">{preset.label}</span>
        <span class="preset-n">{preset.n} периодов</span>
      </button>
    {/each}
  </div>

  <div class="custom-row">
    <label>
      <span>Своё значение (периодов)</span>
      <input
        type="number"
        bind:value={customPeriods}
        oninput={onCustomChange}
        min={1}
        max={maxCustom}
        step={1}
        placeholder={`до ${maxCustom}`}
      />
    </label>
    <label>
      <span>Бюджет периода (₽)</span>
      <div class="budget-input-wrapper">
        <input
          class="budget-input"
          type="text"
          inputmode="numeric"
          value={budgetInput != null ? budgetInput.toLocaleString('ru-RU') : ''}
          oninput={(e) => {
            // @ts-ignore
            const raw = String(e.target.value || '').replace(/\D/g, '');
            budgetInput = raw === '' ? null : Number(raw);
            emitChange();
          }}
          placeholder="авто"
        />
        <span class="budget-suffix">₽</span>
      </div>
    </label>
  </div>

  {#if seasonalityWarning}
    <div class="warn">{seasonalityWarning}</div>
  {/if}
  {#if horizonWarning}
    <div class:critical={customPeriods != null && customPeriods > maxCustom} class="warn">{horizonWarning}</div>
  {/if}
</section>

<style>
  .forecast-horizon-picker {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px 20px;
    border-radius: 12px;
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    margin-bottom: 12px;
  }
  h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  .presets {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }
  .preset {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 3px;
    padding: 10px 16px;
    border-radius: 10px;
    border: 1px solid var(--border-subtle);
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 180ms ease, border-color 180ms ease, color 180ms ease;
  }
  .preset:hover {
    background: var(--bg-card-hover);
    color: var(--text-primary);
    border-color: var(--border-subtle);
  }
  .preset.active {
    background: var(--accent-glow);
    border-color: var(--border-active);
    color: var(--accent-text-light, var(--accent-primary));
    box-shadow: 0 1px 3px var(--accent-glow-strong);
  }
  .preset-label { font-weight: 600; font-size: 0.95rem; }
  .preset-n { font-size: 0.78rem; color: var(--text-muted); }
  .preset.active .preset-n { color: var(--accent-text-light, var(--accent-primary)); opacity: 0.85; }
  .custom-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }
  .custom-row label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 0.85rem;
    color: var(--text-secondary);
  }
  .custom-row input,
  .custom-row .budget-input {
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid var(--input-border);
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 0.95rem;
    font-variant-numeric: tabular-nums;
    transition: border-color 160ms ease, box-shadow 160ms ease;
  }
  .custom-row input:focus,
  .custom-row .budget-input:focus {
    outline: none;
    border-color: var(--border-active);
    box-shadow: 0 0 0 3px var(--accent-glow);
  }
  .budget-input-wrapper {
    position: relative;
    display: flex;
    align-items: stretch;
  }
  .budget-input {
    flex: 1;
    padding-right: 28px;
  }
  .budget-suffix {
    position: absolute;
    right: 12px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--text-muted);
    font-size: 0.9rem;
    pointer-events: none;
  }
  .warn {
    padding: 10px 14px;
    border-radius: 8px;
    background: rgba(217, 119, 6, 0.12);
    border-left: 3px solid #f59e0b;
    color: var(--text-primary);
    font-size: 0.86rem;
    line-height: 1.5;
  }
  .warn.critical {
    background: rgba(239, 68, 68, 0.14);
    border-left-color: #ef4444;
  }
</style>
