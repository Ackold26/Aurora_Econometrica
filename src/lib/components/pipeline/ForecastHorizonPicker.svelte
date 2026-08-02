<!--
  ForecastHorizonPicker - Phase 2 Planning Mode horizon selector.

  Audit pass 2 (2026-05-02): minimal viable per S6 unification - preset buttons +
  custom periods input + budget input. Calendar timeline + start_date picker
  deferred к Phase 2.5 (per L3 - REQUIRE start_date input only when seasonality
  detected; for v1.2.0 ship: surface seasonality warning via alert if needed).

  Smart suggestions derived from forecast-context endpoint:
    - granularity → preset labels (Год/Полугодие/Квартал/Custom)
    - train_n × max_multiplier → cap on custom periods input
    - seasonality detected → warning «требуется указать дату начала»

  Math reference: docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md §10 S6, L3.
-->
<script>
  import { forecastConfig, forecastContext } from '$lib/project-state.js';
  import { ChartColumn } from 'lucide-svelte';

  /** @type {{
   *   trainNPeriods: number,
   *   currentBudgetMoney: number,
   *   onChange?: (cfg: { periods: number, periodLabel: string, budgetMoney: number }) => void,
   * }} */
  let { trainNPeriods, currentBudgetMoney, onChange } = $props();

  // FIX 2026-05-04: gate presets behind forecast_context load. Иначе
  // default 'W' presets показываются для **любой** granularity → customer
  // на monthly data (31 month training) кликает «Год 52» и получает
  // 4618М × 52/31 = 7746М (1.7× от training!). После загрузки context'а
  // presets рендерятся корректно (M → Год=12, Квартал=3, и т.п.).
  // AUDIT 2026-05-04: empty-string guard. `!= null` would accept '' (empty string)
  // от backend → presets show empty array → blank UI без spinner. Truthy check
  // catches both null/undefined and ''. Valid granularity values: 'D','W','M','Q','Y'.
  const granularityKnown = $derived(
    !!($forecastContext?.training_granularity)
  );

  // Periods-per-horizon-label resolved by granularity
  const presets = $derived.by(() => {
    const gran = $forecastContext?.training_granularity;
    if (!gran) return []; // gate - ждём context
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

  // v2.1.0 (pilot E3 round 3 R3-E01 2026-05-17): hydrate local state from
  // persisted $forecastConfig (E-H05 localStorage). Без этого после reload
  // picker UI отображался пустым, customer interaction triggered emitChange
  // с null'ами → store нулифицировался → planning state lost. IIFE для
  // одноразовой init из store (subscribers вытащат update'ы на load).
  let selectedPreset = $state(/** @type {string|null} */ (
    $forecastConfig?.periodLabel ?? null
  ));
  let customPeriods = $state(/** @type {number|null} */ (
    typeof $forecastConfig?.periods === 'number' && $forecastConfig.periods > 0
      ? $forecastConfig.periods : null
  ));
  let budgetInput = $state(/** @type {number|null} */ (
    typeof $forecastConfig?.budgetMoney === 'number' && $forecastConfig.budgetMoney > 0
      ? $forecastConfig.budgetMoney : null
  ));
  // Audit pass 4: track customer manual override. Когда true - preset clicks
  // НЕ переписывают custom бюджет. Customer может ввести независимый бюджет
  // (без привязки к training horizon).
  // F-018 (2026-05-18): флаг персистится в forecastConfig store (см. INV-22
  // sister rule). Раньше — `budgetInput !== null` → любой restored бюджет
  // (включая auto-suggested) считался manual → presets 3/6/12 после reload
  // давали same budget. Теперь read actual flag из store; default false если
  // legacy payload без поля.
  let budgetManuallyEdited = $state($forecastConfig?.budgetManuallyEdited === true);

  // Auto-suggest budget when periods change (proportional to training)
  /** @param {number | null} periods */
  function suggestBudget(periods) {
    if (!periods || periods < 1 || trainNPeriods < 1) return null;
    return Math.round(currentBudgetMoney * (periods / trainNPeriods));
  }

  // FIX 2026-05-04: forecast_context загружается асинхронно при переключении
  // в planner mode. До загрузки `trainNPeriods` = fallback 52 - если customer
  // успевает кликнуть пресет «Год 52» в этот момент, suggestBudget даёт
  // currentBudgetMoney × 52/52 = full training budget (нерасштабированный).
  // Когда context приходит, trainNPeriods обновляется до реального (например
  // 156 для 3-летних weekly), но budgetInput уже зафиксирован. $effect ниже
  // авто-пересчитывает suggestion когда trainNPeriods/currentBudgetMoney
  // меняются - при условии что customer не редактировал budget вручную.
  $effect(() => {
    if (budgetManuallyEdited) return;
    if (customPeriods == null || customPeriods < 1) return;
    if (trainNPeriods < 1 || currentBudgetMoney <= 0) return;
    // F-018 follow-up (2026-05-18): не пересчитываем auto-suggest пока
    // forecast_context не загрузился. Без этого gate parent OptimizeStep
    // передаёт fallback trainNPeriods=52 во время первого render после
    // reload → suggestBudget с wrong scale → overwrite корректно
    // восстановленного из localStorage budget. До F-018 это скрывалось
    // багом (budgetManuallyEdited всегда был true после reload).
    if (!granularityKnown) return;
    const fresh = suggestBudget(customPeriods);
    if (fresh != null && fresh !== budgetInput) {
      budgetInput = fresh;
      emitChange();
    }
  });

  /** @param {string} label @param {number} n */
  function selectPreset(label, n) {
    selectedPreset = label;
    customPeriods = n;
    // Audit pass 4 (Антон 2026-05-02): customer может ввести бюджет
    // независимо от training horizon. Если budgetManuallyEdited - preset
    // НЕ overwrites. Sticky manual budget. Reset через explicit button.
    if (!budgetManuallyEdited) {
      budgetInput = suggestBudget(n);
    }
    emitChange();
  }

  function resetBudgetToSuggested() {
    budgetManuallyEdited = false;
    if (customPeriods != null) {
      budgetInput = suggestBudget(customPeriods);
    }
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
      forecastConfig.update(c => ({ ...c, periods: null, periodLabel: null, budgetMoney: null, budgetManuallyEdited }));
      return;
    }
    // Audit pass 3 fix (BUG 19): force integer для Tauri Option<i64> compat.
    // step={1} on input не блокирует typed decimals в некоторых browsers.
    const periodsInt = Math.floor(Number(customPeriods));
    if (!Number.isFinite(periodsInt) || periodsInt < 1) {
      forecastConfig.update(c => ({ ...c, periods: null, periodLabel: null, budgetMoney: null, budgetManuallyEdited }));
      return;
    }
    const cfg = {
      periods: periodsInt,
      periodLabel: selectedPreset || `${periodsInt} periods`,
      budgetMoney: budgetInput,
    };
    // F-018 (2026-05-18): persist budgetManuallyEdited флаг чтобы preset
    // suggestion logic переживал reload (см. project-state.js comment).
    forecastConfig.update(c => ({ ...c, ...cfg, budgetManuallyEdited }));
    onChange?.(cfg);
  }

  const seasonalityWarning = $derived.by(() => {
    const s = $forecastContext?.seasonality_detected;
    if (!s) return null;
    if (customPeriods == null) {
      return `Обнаружена сезонность период=${s.period} (сила сигнала ${s.autocorr.toFixed(2)}). Выберите период планирования – он повлияет на результат в зависимости от месяца старта.`;
    }
    return `Обнаружена сезонность период=${s.period} (сила сигнала ${s.autocorr.toFixed(2)}). Прогноз с ${customPeriods} периодов даст разные результаты в зависимости от месяца старта – см. методологию.`;
  });

  // Audit pass 4 (Антон 2026-05-02): при denежной оценке медиа за multi-year
  // training, годовая инфляция 25-30% значительно меняет CPP/CPM. UI prep -
  // surface customer'у факт что обучение шло на нескольких годах.
  const trainingYearRanges = $derived(/** @type {Array<any>|null} */ ($forecastContext?.training_year_ranges ?? null));
  const isMultiYearTraining = $derived(
    Array.isArray(trainingYearRanges) && trainingYearRanges.length >= 2
  );
  const trainingYearsLabel = $derived.by(() => {
    if (!isMultiYearTraining || !trainingYearRanges) return null;
    const years = trainingYearRanges.map(/** @param {any} r */ (r) => r.year).filter(Boolean);
    if (years.length === 0) return null;
    return `${Math.min(...years)}–${Math.max(...years)} (${years.length} ${years.length < 5 ? 'года' : 'лет'})`;
  });

  // 5b (2026-05-04): training span human-friendly label. Customer часто mental
  // models as «training 3 года», но raw n_periods (31 month) - abstract число.
  // Human label: «обучение на 31 месяце ≈ 2 года 7 мес» - bridges gap.
  // Granularity → period word + approx span calculation.
  const trainingSpanLabel = $derived.by(() => {
    if (!granularityKnown || trainNPeriods < 1) return null;
    const gran = $forecastContext?.training_granularity;
    /** @type {Record<string, {periodPlural: (n: number) => string, perYear: number}>} */
    const meta = {
      D: { periodPlural: (n) => n === 1 ? 'день' : (n < 5 ? 'дня' : 'дней'), perYear: 365 },
      W: { periodPlural: (n) => n === 1 ? 'неделя' : (n < 5 ? 'недели' : 'недель'), perYear: 52 },
      M: { periodPlural: (n) => n === 1 ? 'месяц' : (n < 5 ? 'месяца' : 'месяцев'), perYear: 12 },
      Q: { periodPlural: (n) => n === 1 ? 'квартал' : (n < 5 ? 'квартала' : 'кварталов'), perYear: 4 },
      Y: { periodPlural: (n) => n === 1 ? 'год' : (n < 5 ? 'года' : 'лет'), perYear: 1 },
    };
    const m = meta[gran || 'W'];
    if (!m) return null;
    const periodWord = m.periodPlural(trainNPeriods);
    const years = trainNPeriods / m.perYear;
    let spanText;
    if (years >= 1) {
      const fullYears = Math.floor(years);
      const remainder = trainNPeriods - fullYears * m.perYear;
      if (remainder === 0) {
        spanText = `${fullYears} ${m.perYear === 1 ? (fullYears === 1 ? 'год' : (fullYears < 5 ? 'года' : 'лет')) : (fullYears === 1 ? 'год' : (fullYears < 5 ? 'года' : 'лет'))}`;
      } else {
        const remPeriodsWord = m.periodPlural(remainder);
        const yearWord = fullYears === 1 ? 'год' : (fullYears < 5 ? 'года' : 'лет');
        spanText = `${fullYears} ${yearWord} ${remainder} ${remPeriodsWord}`;
      }
    } else {
      spanText = `${trainNPeriods} ${periodWord}`;
    }
    return `Обучение на ${trainNPeriods} ${periodWord} (≈ ${spanText})`;
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

  {#if !granularityKnown}
    <div class="loading-presets" aria-live="polite">
      <span class="spinner" aria-hidden="true"></span>
      Определяем периодичность данных…
    </div>
  {:else}
  {#if trainingSpanLabel}
    <div class="training-span" aria-live="polite">
      <span class="training-span-icon" aria-hidden="true"><ChartColumn size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /></span>
      <span class="training-span-text">{trainingSpanLabel}</span>
    </div>
  {/if}
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
  {/if}

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
        disabled={!granularityKnown}
        placeholder={granularityKnown ? `до ${maxCustom}` : 'ожидание контекста…'}
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
            budgetManuallyEdited = true;
            emitChange();
          }}
          placeholder="авто"
        />
        <span class="budget-suffix">₽</span>
      </div>
      <div class="budget-meta">
        {#if budgetManuallyEdited}
          {@const suggested = suggestBudget(customPeriods)}
          <span class="budget-tag manual">ваше значение (изменено){#if suggested != null && suggested !== budgetInput} · предложено {suggested.toLocaleString('ru-RU')} ₽{/if}</span>
          <button type="button" class="budget-reset" onclick={resetBudgetToSuggested}>
            Сбросить к предложенному
          </button>
        {:else if budgetInput != null}
          <span class="budget-tag auto">Авто-предложено · можно изменить</span>
        {/if}
      </div>
    </label>
  </div>

  {#if isMultiYearTraining}
    <div class="info-multi-year">
      <span class="multi-year-icon" aria-hidden="true">📅</span>
      <div class="multi-year-body">
        <div class="multi-year-title">Обучение на нескольких годах: {trainingYearsLabel}</div>
        <div class="multi-year-text">
          Годовая медиаинфляция (CPP/CPM) могла значительно меняться год от года (типично 25–30% по РФ).
          Денежные оценки - средняя по training, не per-year split.
          <strong>Для года планирования используйте свой бюджет</strong> или применяйте инфляцию
          (раздел «Прогноз на период»).
          {#each trainingYearRanges as r}
            <span class="year-chip">{r.year}<span class="year-n">{r.n_periods}п.</span></span>
          {/each}
        </div>
      </div>
    </div>
  {/if}

  {#if seasonalityWarning}
    <div class="warn">{seasonalityWarning}</div>
  {/if}
  {#if horizonWarning}
    <div class:critical={customPeriods != null && customPeriods > maxCustom} class="warn">{horizonWarning}</div>
  {/if}

  {#if customPeriods != null && customPeriods >= 1 && budgetInput != null && budgetInput > 0}
    <div class="planning-summary">
      <span class="arrow" aria-hidden="true">↓</span>
      <span class="summary-text">
        Этот бюджет
        <strong>{budgetInput.toLocaleString('ru-RU')} ₽</strong>
        на <strong>{customPeriods}</strong> {customPeriods === 1 ? 'период' : customPeriods < 5 ? 'периода' : 'периодов'}
        будет использован для оптимизации
      </span>
    </div>
  {/if}
</section>

<style>
  .forecast-horizon-picker {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 16px 18px;
    border-radius: 14px;
    /* Same tokens как .block в OptimizeStep - интегрируется с остальными
       блоками (Текущий бюджет / Оптимизация распределения), не выделяется. */
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
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
    background: color-mix(in srgb, var(--text-primary) 6%, transparent);
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 180ms ease, border-color 180ms ease, color 180ms ease;
  }
  .preset:hover {
    background: color-mix(in srgb, var(--text-primary) 10%, transparent);
    color: var(--text-primary);
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
  .planning-summary {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    border-radius: 10px;
    background: var(--accent-glow);
    border: 1px solid var(--border-active);
    color: var(--text-primary);
    font-size: 0.88rem;
    line-height: 1.4;
  }
  .planning-summary .arrow {
    font-size: 1.2rem;
    color: var(--accent-text-light, var(--accent-primary));
    font-weight: 600;
  }
  .planning-summary strong { color: var(--accent-text-light, var(--accent-primary)); }
  .budget-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
    font-size: 0.78rem;
  }
  .budget-tag {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 6px;
    font-weight: 500;
  }
  .budget-tag.auto {
    background: color-mix(in srgb, var(--text-primary) 7%, transparent);
    color: var(--text-muted);
  }
  .budget-tag.manual {
    background: var(--accent-glow);
    color: var(--accent-text-light, var(--accent-primary));
  }
  .budget-reset {
    border: none;
    background: transparent;
    color: var(--text-secondary);
    text-decoration: underline;
    cursor: pointer;
    font-size: 0.78rem;
    padding: 0;
  }
  .budget-reset:hover { color: var(--text-primary); }

  /* Multi-year training disclosure (audit pass 4 Антон 2026-05-02) */
  .info-multi-year {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 12px 14px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--accent-secondary, #CCFF00) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-secondary, #CCFF00) 30%, transparent);
    color: var(--text-primary);
    font-size: 0.86rem;
    line-height: 1.5;
  }
  .info-multi-year .multi-year-icon { font-size: 1.2rem; line-height: 1; }
  .info-multi-year .multi-year-title {
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 4px;
  }
  .info-multi-year .multi-year-text strong { color: var(--text-primary); }
  .info-multi-year .year-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin: 4px 6px 0 0;
    padding: 2px 8px;
    border-radius: 12px;
    background: color-mix(in srgb, var(--text-primary) 8%, transparent);
    font-size: 0.78rem;
    font-weight: 500;
  }
  .info-multi-year .year-chip .year-n {
    color: var(--text-muted);
    font-weight: 400;
    font-size: 0.74rem;
  }

  .loading-presets {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    border-radius: 8px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
    border: 1px dashed var(--border-muted, rgba(255,255,255,0.12));
    color: var(--text-secondary);
    font-size: 0.88rem;
    margin: 8px 0;
  }
  .training-span {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-radius: 8px;
    background: color-mix(in srgb, var(--text-primary) 4%, transparent);
    color: var(--text-secondary);
    font-size: 0.84rem;
    line-height: 1.4;
    margin: 4px 0;
  }
  .training-span-icon { font-size: 0.95rem; line-height: 1; }
  .training-span-text { color: var(--text-primary); font-weight: 500; }
  .loading-presets .spinner {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 2px solid var(--border-muted, rgba(255,255,255,0.18));
    border-top-color: var(--accent-primary);
    animation: spinner-rotate 0.8s linear infinite;
  }
  @keyframes spinner-rotate {
    to { transform: rotate(360deg); }
  }

  /* v2.1.0 п.5.6: static spinner ring */
  @media (prefers-reduced-motion: reduce) {
    .loading-presets .spinner {
      border-color: color-mix(in srgb, var(--accent-primary) 70%, transparent);
    }
  }
</style>
