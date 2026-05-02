<script>
  /**
   * UnitCostsPanel — Trust Level 2 (CPP-нормализация).
   *
   * Для медиа-каналов с не-денежными единицами (TRP/GRP/OTS/показ/охват)
   * запрашиваем стоимость 1 юнита в валюте KPI. Это позволяет считать ROI
   * корректно и сравнивать каналы в одной шкале.
   *
   * Дефолты по медиа-данным РФ 2026, согласованы с Антоном.
   * Для каналов в рублях input не показывается (unit_cost = 1.0 неявно).
   *
   * Key UX:
   * - Hydrate draft один раз при появлении каналов (потом не затираем пользовательский ввод).
   * - Кнопка «Сохранить» активна только когда есть dirty-изменения.
   * - После save инвалидируем decomposeData/optimizeData → banner «требуется пересчёт».
   * - Preview «22 100 × 250 000 = 5.5B ₽» сразу под вводом.
   * - Anomaly warning если введён CPP ≥10× отклоняется от дефолта.
   *
   * @component UnitCostsPanel
   */
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import {
    activeProjectId, activeProject, unitCosts, unitCostInflation,
    decomposeData, optimizeData, analysisObjective, forecastContext,
  } from '$lib/project-state.js';

  /** @type {{ columns: any[] }} */
  let { columns } = $props();

  // Дефолты CPP/CPM по медиа-данным РФ 2026 (согласованы с Антоном).
  // Порядок важен: более специфичные паттерны идут выше.
  const DEFAULTS = [
    { re: /(W\s*25[-– ]?54|25[-– ]?54).*TRP|TRP.*(W\s*25[-– ]?54|25[-– ]?54)/i, value: 250000, label: 'TV brand W 25-54 (250 000₽/TRP)' },
    { re: /(W\s*18[-– ]?44|18[-– ]?44).*TRP|TRP.*(W\s*18[-– ]?44|18[-– ]?44)/i, value: 180000, label: 'TV brand W 18-44 (180 000₽/TRP)' },
    { re: /(PERFORMANCE|ПЕРФ).*TRP|TRP.*(PERFORMANCE|ПЕРФ)/i, value: 120000, label: 'TV performance (120 000₽/TRP)' },
    { re: /TRP|РЕЙТИНГ/i, value: 250000, label: 'TV TRP (250 000₽/TRP, дефолт)' },
    { re: /GRP/i, value: 250000, label: 'GRP (≈ TRP, 250 000₽)' },
    { re: /RADIO|РАДИО/i, value: 30000, label: 'Radio GRP W 25-54 (30 000₽)' },
    { re: /(OOH|НАРУЖК)/i, value: 80, label: 'OOH CPT (80₽ за 1000 контактов)' },
    { re: /(CPM|ПОКАЗ|IMPRESSION)/i, value: 200, label: 'Digital CPM (200₽ за 1000 показов)' },
    { re: /OTS|ОХВАТ/i, value: 5, label: 'OTS (5₽ за охват, прикидка)' },
  ];
  // Автодетект — только «чистые» медиа-единицы (TRP/GRP/OTS и их русские аналоги).
  // Остальные не-денежные каналы (статьи/спецпроекты/показы/клики) пользователь
  // добавляет вручную через «+ Добавить канал» — там слишком много вариантов
  // именования чтобы надёжно ловить regex'ом, лучше явный выбор.
  const UNIT_HINT = /TRP|GRP|OTS|РЕЙТИНГ|ОХВАТ/i;
  // Money-каналы (бюджеты уже в рублях) — скрываются из dropdown «+ Добавить».
  // Маркеры: НДС / VAT / руб / ₽ / RUB. Unit cost = 1 для них бесcмыслен.
  const MONEY_HINT = /НДС|VAT|(?:^|[\s\(])руб|₽|RUB/i;

  /** @type {Record<string, string>} */
  const CATEGORY_HELP = {
    brand_reach: 'Brand-Reach — охватные каналы (TV/TRPs/OOH/радио), работают на долгосрочный brand-эффект.\n\nЧто это: строят знание и доверие к бренду, влияние раскрывается месяцами.\n\nКак читать: ROI интерпретируй как «вклад в базу + короткий эффект», не чистый инкремент. Сравнивай только с другими Brand-Reach каналами.',
    performance: 'Performance — каналы прямого отклика (Digital/Search/Social/контекст), работают на короткий инкремент.\n\nЧто это: закрывают спрос здесь и сейчас, эффект виден в пределах недель.\n\nКак читать: ROI — чистая отдача на рубль. Сравнивай с другими Performance каналами.',
  };

  /** @param {string} name */
  function suggestDefault(name) {
    const n = (name || '').toUpperCase();
    for (const d of DEFAULTS) {
      if (d.re.test(n)) return d;
    }
    return null;
  }

  // Формат с разделителями тысяч + EN-space (узкий пробел).
  /** @param {number | null | undefined} n */
  function fmt(n) {
    if (n == null || !Number.isFinite(n)) return '—';
    return Math.round(n).toLocaleString('ru-RU').replace(/,/g, ' ');
  }

  // Все media-каналы проекта — кандидаты для перевода в рубли.
  const allMediaChannels = $derived(
    (columns ?? []).filter(/** @param {any} c */ (c) => c.role === 'media')
  );

  // Подсказки автодетекта (TRP/GRP/OTS) — только для ссылки «Добавить все».
  const autoDetected = $derived(
    allMediaChannels.filter(/** @param {any} c */ (c) => UNIT_HINT.test(String(c.name || '')))
  );

  /**
   * Каналы, явно добавленные пользователем в панель. Hydrate из сохранённых
   * unit_costs; auto-detected предлагаются через отдельную ссылку, не
   * добавляются автоматически.
   * @type {string[]}
   */
  let selectedNames = $state([]);

  // Hydrate один раз при появлении списка медиа-каналов.
  let selectedHydrated = false;
  $effect(() => {
    if (selectedHydrated) return;
    if (allMediaChannels.length === 0) return;
    selectedHydrated = true;
    const stored = get(unitCosts) || {};
    const names = Object.keys(stored).filter(
      (k) => allMediaChannels.some(/** @param {any} c */ (c) => c.name === k)
    );
    selectedNames = names;
  });

  // Строки панели — media-каналы, которые пользователь добавил.
  const nonMoneyChannels = $derived(
    allMediaChannels.filter(/** @param {any} c */ (c) => selectedNames.includes(c.name))
  );

  // Не добавленные auto-detected — для ссылки «Добавить все TRP/GRP/OTS».
  const autoUnselected = $derived(
    autoDetected.filter(/** @param {any} c */ (c) => !selectedNames.includes(c.name))
  );

  // Для dropdown «+ Добавить канал» — media которых нет в selected И не в рублях.
  // Каналы с НДС/VAT/руб/₽/RUB в имени уже измеряются в деньгах — unit cost = 1
  // не требуется, не предлагаем их.
  const availableToAdd = $derived(
    allMediaChannels.filter(/** @param {any} c */ (c) =>
      !selectedNames.includes(c.name) && !MONEY_HINT.test(String(c.name || ''))
    )
  );

  /** @type {string} выбор в dropdown перед нажатием «Добавить».
      Автоподстановка первого auto-detected канала с UNIT_HINT — кнопка
      «Добавить» сразу активна, не ждёт ручного выбора option в dropdown. */
  let pendingAdd = $state('');
  $effect(() => {
    // Если pendingAdd пуст и есть звёздочный (auto-detected) канал в available —
    // preselect его. Не перетираем если пользователь уже выбрал что-то другое.
    if (pendingAdd) return;
    const starred = availableToAdd.find(
      /** @param {any} c */ (c) => UNIT_HINT.test(String(c.name || ''))
    );
    if (starred) pendingAdd = starred.name;
  });

  /** @param {string} name */
  function addChannel(name) {
    if (!name || selectedNames.includes(name)) return;
    selectedNames = [...selectedNames, name];
  }

  /** @param {string} name */
  function removeChannel(name) {
    selectedNames = selectedNames.filter((n) => n !== name);
    if (draft[name] !== undefined) {
      const { [name]: _removed, ...rest } = draft;
      draft = rest;
    }
    if (savedSnapshot[name] !== undefined) {
      const { [name]: _r, ...rest } = savedSnapshot;
      savedSnapshot = rest;
    }
  }

  function addAllAutoDetected() {
    for (const c of autoUnselected) addChannel(c.name);
  }

  // Сумма raw-spend канала из валидационного sample — для preview money.
  // validator.py пишет сумму в col.stats.sum.
  /** @param {string} name */
  function rawSumForChannel(name) {
    const col = (columns ?? []).find(/** @param {any} c */ (c) => c.name === name);
    const v = col?.stats?.sum;
    return (typeof v === 'number' && Number.isFinite(v)) ? v : null;
  }

  /** @type {Record<string, string>} рабочая копия инпутов (строки — для удобного ввода) */
  let draft = $state({});
  /** @type {Record<string, number>} последнее сохранённое состояние — для dirty-detect */
  let savedSnapshot = $state(/** @type {Record<string, number>} */ ({}));
  // Phase 2 audit pass 4 — per-channel annual inflation. UI input — string,
  // saved snapshot — number, dirty-detect mirror unit_costs pattern.
  /** @type {Record<string, string>} */
  let inflationDraft = $state({});
  /** @type {Record<string, number>} */
  let inflationSavedSnapshot = $state(/** @type {Record<string, number>} */ ({}));
  let saving = $state(false);
  /** @type {string} */
  let savedMsg = $state('');

  // Hydrate draft один раз при появлении/смене набора каналов. Не затираем ввод,
  // если пользователь уже что-то вводит (сверяем по Set имён).
  /** @type {string} сигнатура текущих каналов — для определения «нужна ли регидратация» */
  let lastChannelsSig = $state('');
  $effect(() => {
    const sig = nonMoneyChannels.map(/** @param {any} c */ (c) => c.name).sort().join('|');
    if (sig === lastChannelsSig) return; // тот же набор — не трогаем draft
    lastChannelsSig = sig;

    const stored = get(unitCosts) || {};
    const storedInfl = get(unitCostInflation) || {};
    /** @type {Record<string, string>} */
    const next = {};
    /** @type {Record<string, number>} */
    const snap = {};
    /** @type {Record<string, string>} */
    const nextInfl = {};
    /** @type {Record<string, number>} */
    const snapInfl = {};
    for (const ch of nonMoneyChannels) {
      const name = ch.name;
      if (stored[name] != null) {
        next[name] = String(stored[name]);
        snap[name] = stored[name];
      } else {
        const d = suggestDefault(name);
        // Дефолт — только в поле ввода (placeholder-like). Не кладём в snapshot,
        // чтобы видеть dirty, если пользователь примет дефолт нажатием «Сохранить».
        next[name] = d ? String(d.value) : '';
      }
      if (storedInfl[name] != null) {
        nextInfl[name] = String(storedInfl[name]);
        snapInfl[name] = storedInfl[name];
      } else {
        nextInfl[name] = '';
      }
    }
    draft = next;
    savedSnapshot = snap;
    inflationDraft = nextInfl;
    inflationSavedSnapshot = snapInfl;
  });

  /** Распарсить строку в положительное число. Пустая строка → null (=удалить). */
  /** @param {string} raw */
  function parseValue(raw) {
    const s = String(raw || '').replace(/\s+/g, '').replace(',', '.');
    if (s === '') return null;
    const v = parseFloat(s);
    return (Number.isFinite(v) && v > 0) ? v : null;
  }

  /** @type {Record<string, number>} текущие значения после парсинга (реактивные) */
  const parsed = $derived.by(() => {
    /** @type {Record<string, number>} */
    const out = {};
    for (const [k, v] of Object.entries(draft)) {
      const p = parseValue(v);
      if (p !== null) out[k] = p;
    }
    return out;
  });

  // Phase 2 audit pass 4 — parsed inflation per channel (numeric).
  /** @type {Record<string, number>} */
  const parsedInflation = $derived.by(() => {
    /** @type {Record<string, number>} */
    const out = {};
    for (const [k, v] of Object.entries(inflationDraft)) {
      const p = parseValue(v);
      if (p !== null) out[k] = p;
    }
    return out;
  });

  // Audit pass 5 fix (BUG B2): UnitCostsPanel живёт в ValidateStep — РАНЬШЕ
  // OptimizeStep в pipeline. Глобальный forecastContext store fetched только
  // в planner mode на OptimizeStep mount → UnitCostsPanel не видел multi-year
  // detection через стандартный workflow. Делаем independent fetch когда
  // pickle existed (after train).
  /** @type {any} */
  let localForecastContext = $state(null);
  $effect(() => {
    const pid = $activeProjectId;
    if (!pid) { localForecastContext = null; return; }
    (async () => {
      try {
        const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId: pid }));
        const ctx = /** @type {any} */ (await invoke('econ_forecast_context', { projectDir }));
        if (ctx?.status === 'ok') {
          localForecastContext = ctx;
          // Also populate global store для shared consumers
          forecastContext.set(ctx);
        } else {
          localForecastContext = null;
        }
      } catch {
        // Model not trained yet — silent fallback (input не показывается).
        localForecastContext = null;
      }
    })();
  });

  // Show inflation field только когда training data spans ≥2 years.
  // Reads localForecastContext (independent fetch) с fallback к global store.
  const isMultiYearTraining = $derived.by(() => {
    const ranges = (localForecastContext ?? $forecastContext)?.training_year_ranges;
    return Array.isArray(ranges) && ranges.length >= 2;
  });

  // Dirty-detect: draft отличается от savedSnapshot → есть что сохранять.
  const dirty = $derived.by(() => {
    const keysA = Object.keys(parsed);
    const keysB = Object.keys(savedSnapshot);
    if (keysA.length !== keysB.length) return true;
    for (const k of keysA) {
      if (Math.abs((parsed[k] ?? 0) - (savedSnapshot[k] ?? 0)) > 1e-9) return true;
    }
    // Phase 2 — also dirty when inflation rates changed
    const inflKeysA = Object.keys(parsedInflation);
    const inflKeysB = Object.keys(inflationSavedSnapshot);
    if (inflKeysA.length !== inflKeysB.length) return true;
    for (const k of inflKeysA) {
      if (Math.abs((parsedInflation[k] ?? 0) - (inflationSavedSnapshot[k] ?? 0)) > 1e-9) return true;
    }
    return false;
  });

  /** @param {string} name */
  function anomalyHint(name) {
    const def = suggestDefault(name);
    if (!def) return null;
    const val = parsed[name];
    if (val == null) return null;
    const ratio = val / def.value;
    if (ratio >= 10) return `В ${ratio.toFixed(1)}× выше рыночного — проверь единицы`;
    if (ratio <= 0.1) return `В ${(1 / ratio).toFixed(1)}× ниже рыночного — проверь единицы`;
    return null;
  }

  async function save() {
    const pid = get(activeProjectId);
    if (!pid) return;
    saving = true;
    savedMsg = '';
    try {
      // Money-каналы (те что НЕ в панели = native уже в деньгах) → unit_cost=1.
      // Без этого backend scenario.compare видит их как "не покрытые"
      // и падает в native-mode с warning, хотя для них 1₽/unit — корректно.
      /** @type {Record<string, number>} */
      const fullCosts = { ...parsed };
      for (const ch of allMediaChannels) {
        if (fullCosts[ch.name] == null) {
          fullCosts[ch.name] = 1.0;
        }
      }

      // Phase 2 audit pass 4 — persist per-channel inflation pct alongside.
      // null entries removed (zero inflation = same as not set).
      /** @type {Record<string, number>} */
      const fullInflation = {};
      for (const [k, v] of Object.entries(parsedInflation)) {
        if (v > 0) fullInflation[k] = v;
      }

      const info = /** @type {any} */ (await invoke('project_update', {
        projectId: pid,
        updates: {
          unit_costs: fullCosts,
          unit_cost_inflation_pct: Object.keys(fullInflation).length > 0 ? fullInflation : null,
        },
      }));
      activeProject.set(info);
      unitCosts.set(fullCosts);
      unitCostInflation.set(fullInflation);
      savedSnapshot = { ...parsed };
      inflationSavedSnapshot = { ...fullInflation };
      // Инвалидируем downstream результаты — старые числа больше не актуальны.
      decomposeData.set(null);
      optimizeData.set(null);
      savedMsg = '✓ Сохранено · Декомпозиция будет пересчитана автоматически';
      setTimeout(() => (savedMsg = ''), 5000);
    } catch (e) {
      savedMsg = 'Ошибка: ' + String(e);
    } finally {
      saving = false;
    }
  }

  function resetToDefaults() {
    /** @type {Record<string, string>} */
    const next = {};
    for (const ch of nonMoneyChannels) {
      const d = suggestDefault(ch.name);
      next[ch.name] = d ? String(d.value) : '';
    }
    draft = next;
  }
</script>

{#if $analysisObjective === 'roi' && allMediaChannels.length > 0}
  <section class="unit-costs">
    <div class="header">
      <div class="title">Стоимость юнита для каналов в не-денежных единицах</div>
      <div class="hint">
        Добавь каналы, измеряемые не в рублях (TRP, показы, статьи, спецпроекты),
        и укажи цену единицы <strong>в последнем году обучающих данных</strong>. Модель пересчитает их в рубли и даст корректный ROI.
        {#if isMultiYearTraining}
          <br>📅 <strong>Обучение охватывает несколько лет</strong> — задайте <em>исторический</em> темп инфляции CPP/CPM
          (по РФ типично 25–30% год к году). Backend пересчитает цену по обучающим периодам:
          текущая ÷ (1+rate)<sup>лет</sup> и применит weighted-average. 0 = цена не менялась.
          <br><span class="hint-secondary">⚠ Это <em>исторический</em> темп для training. Для прогноза будущего используйте <em>прогнозную</em> инфляцию в шаге «Оптимизация» (Блок D).</span>
        {/if}
        {#if $analysisObjective !== 'roi'}
          <br><em>Активно только в режиме «ROI» (см. Цель анализа).</em>
        {/if}
      </div>
    </div>

    {#if nonMoneyChannels.length > 0}
      <div class="rows">
        {#each nonMoneyChannels as ch}
          {@const def = suggestDefault(ch.name)}
          {@const val = parsed[ch.name]}
          {@const rawSum = rawSumForChannel(ch.name)}
          {@const preview = (val != null && rawSum != null) ? rawSum * val : null}
          {@const warn = anomalyHint(ch.name)}
          <div class="row" class:row-warn={!!warn}>
            <div class="row-name">
              {ch.name}
              {#if ch.category && CATEGORY_HELP[ch.category]}
                <span
                  class="cat-chip"
                  class:brand={ch.category === 'brand_reach'}
                  class:perf={ch.category === 'performance'}
                  title={CATEGORY_HELP[ch.category]}
                >
                  {ch.category === 'brand_reach' ? 'Brand-Reach' : 'Performance'}
                </span>
              {/if}
            </div>
            <div class="row-input">
              <input
                type="text"
                inputmode="decimal"
                bind:value={draft[ch.name]}
                placeholder={def ? String(def.value) : 'введи цену'}
                aria-label="Стоимость 1 юнита для {ch.name}"
              />
              <span class="unit">₽ за юнит</span>
              {#if isMultiYearTraining}
                <input
                  class="inflation-input"
                  type="text"
                  inputmode="decimal"
                  bind:value={inflationDraft[ch.name]}
                  placeholder="0"
                  aria-label="Историческая годовая инфляция CPP для {ch.name}"
                  title={'Исторический годовой темп роста стоимости юнита за период обучения (например 25 — для 25%/год). Backend пересчитает цену по training периодам: 2024 = current ÷ 1.25, 2023 = current ÷ 1.25², и т.д. 0 = цена не менялась.\n\nЭто НЕ прогнозная инфляция. Прогнозную (для forecast) задавайте в Блоке D на шаге «Оптимизация».'}
                />
                <span class="unit" title="Историческая инфляция. Прогнозная — в Блоке D на шаге «Оптимизация».">%/год (история)</span>
              {/if}
            </div>
            <div class="row-meta">
              {#if rawSum != null}
                <div class="row-default">
                  {fmt(rawSum)} юнит<span class="muted">(в загруженных данных)</span>
                  {#if def}
                    · <span title="Дефолт по медиа-данным РФ 2026">≈ {def.label}</span>
                  {/if}
                </div>
              {:else if def}
                <div class="row-default" title="Дефолт по медиа-данным РФ 2026">≈ {def.label}</div>
              {:else}
                <div class="row-default muted">Нет данных по объёму — укажи цену вручную</div>
              {/if}
              {#if preview != null}
                <div class="row-preview">
                  Эквивалент: <b>{fmt(rawSum)} × {fmt(val)} ₽ = {fmt(preview)} ₽</b>
                </div>
              {:else if val != null && rawSum == null}
                <div class="row-preview muted">
                  Цена <b>{fmt(val)} ₽</b> сохранена — общая сумма появится после валидации данных.
                </div>
              {/if}
              {#if warn}
                <div class="row-warn-msg">⚠ {warn}</div>
              {/if}
            </div>
            <button
              class="btn-remove"
              type="button"
              onclick={() => removeChannel(ch.name)}
              title="Убрать канал из списка"
              aria-label="Убрать {ch.name}"
            >✕</button>
          </div>
        {/each}
      </div>
    {/if}

    <!-- Добавление нового канала -->
    {#if availableToAdd.length > 0}
      <div class="add-row">
        <select class="add-select" bind:value={pendingAdd}>
          <option value="">+ Добавить канал для перевода в рубли…</option>
          {#each availableToAdd as c}
            <option value={c.name}>
              {UNIT_HINT.test(String(c.name || '')) ? '★ ' : ''}{c.name}
            </option>
          {/each}
        </select>
        <button
          class="btn-add"
          type="button"
          disabled={!pendingAdd}
          onclick={() => { addChannel(pendingAdd); pendingAdd = ''; }}
        >Добавить</button>
      </div>
    {/if}

    <!-- Hint: автодетект TRP/GRP/OTS -->
    {#if autoUnselected.length > 0 && nonMoneyChannels.length === 0}
      <button class="autodetect-hint" type="button" onclick={addAllAutoDetected}>
        Обнаружено {autoUnselected.length} {autoUnselected.length === 1 ? 'канал' : autoUnselected.length < 5 ? 'канала' : 'каналов'} с TRP/GRP/OTS — добавить все одним кликом
      </button>
    {/if}

    {#if nonMoneyChannels.length > 0}
      <div class="footer">
        <button class="btn-save" onclick={save} disabled={saving || !dirty}>
          {saving ? 'Сохраняю…' : (dirty ? 'Сохранить стоимости' : 'Нет изменений')}
        </button>
        <button class="btn-reset" type="button" onclick={resetToDefaults} disabled={saving} title="Вернуть рыночные дефолты для текущих каналов">
          ↺ Дефолты
        </button>
        {#if savedMsg}
          <span class="saved-msg" class:err={savedMsg.startsWith('Ошибка')}>{savedMsg}</span>
        {/if}
      </div>
    {/if}
  </section>
{/if}

<style>
  .unit-costs {
    padding: 14px 16px;
    background: color-mix(in srgb, var(--accent-primary) 5%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 18%, transparent);
    border-radius: 12px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .title {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-secondary, #94a3b8);
  }
  .hint {
    margin-top: 4px;
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.55;
  }
  .rows { display: flex; flex-direction: column; gap: 8px; }
  .row {
    display: grid;
    grid-template-columns: minmax(160px, 1.1fr) minmax(180px, auto) minmax(240px, 1.6fr) auto;
    align-items: center;
    gap: 12px;
    padding: 8px 10px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.6));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: 8px;
    transition: border-color 0.15s;
  }
  .row.row-warn { border-color: color-mix(in srgb, var(--warning, #f59e0b) 35%, transparent); }
  @media (max-width: 700px) {
    .row { grid-template-columns: 1fr; gap: 4px; }
  }
  .btn-remove {
    width: 26px;
    height: 26px;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 50%;
    color: var(--text-muted);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .btn-remove:hover {
    color: var(--danger, #ef4444);
    border-color: color-mix(in srgb, var(--danger, #ef4444) 40%, transparent);
    background: color-mix(in srgb, var(--danger, #ef4444) 8%, transparent);
  }

  .add-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .add-select {
    flex: 1;
    padding: 7px 10px;
    background: var(--bg-card, #0b0d13);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    font-size: 12.5px;
    outline: none;
  }
  .add-select:focus { border-color: var(--accent-primary, #3b82f6); }
  .btn-add {
    padding: 7px 14px;
    background: transparent;
    color: var(--text-secondary, #94a3b8);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  }
  .btn-add:hover:not(:disabled) {
    color: var(--accent-primary, #3b82f6);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 40%, transparent);
  }
  .btn-add:disabled { opacity: 0.4; cursor: not-allowed; }

  .autodetect-hint {
    align-self: flex-start;
    padding: 6px 12px;
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 8%, transparent);
    border: 1px dashed color-mix(in srgb, var(--accent-primary, #3b82f6) 35%, transparent);
    border-radius: 6px;
    color: var(--accent-primary, #3b82f6);
    font-size: 11.5px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    text-align: left;
  }
  .autodetect-hint:hover {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 14%, transparent);
  }
  .row-name {
    font-size: 13px;
    color: var(--text-primary, #e2e8f0);
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .cat-chip {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    padding: 1px 6px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--text-secondary) 12%, transparent);
    color: var(--text-secondary);
    cursor: help;
  }
  .cat-chip.brand {
    background: color-mix(in srgb, var(--warning, #f59e0b) 15%, transparent);
    color: var(--warning, #f59e0b);
  }
  .cat-chip.perf {
    background: color-mix(in srgb, var(--success, #10b981) 15%, transparent);
    color: var(--success, #10b981);
  }
  .row-input { display: flex; align-items: center; gap: 8px; }
  input[type="text"] {
    flex: 1;
    min-width: 0;
    padding: 6px 10px;
    background: var(--bg-card, #0b0d13);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
  input[type="text"]:focus {
    outline: none;
    border-color: var(--accent-primary, #3b82f6);
  }
  .unit { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
  /* Phase 2 audit pass 4 — annual inflation input (multi-year training only) */
  .inflation-input {
    width: 56px;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--input-border);
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
  .inflation-input:focus {
    outline: none;
    border-color: var(--border-active);
    box-shadow: 0 0 0 2px var(--accent-glow);
  }
  .hint-secondary {
    display: inline-block;
    margin-top: 4px;
    color: var(--text-muted);
    font-size: 11.5px;
    font-style: italic;
  }
  .row-meta { display: flex; flex-direction: column; gap: 2px; }
  .row-default { font-size: 11px; color: var(--text-secondary, #94a3b8); line-height: 1.3; }
  .row-default .muted { color: var(--text-muted); opacity: 0.8; margin-left: 4px; }
  .row-default.muted { opacity: 0.6; font-style: italic; color: var(--text-muted); }
  .row-preview {
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.3;
  }
  .row-preview.muted { color: var(--text-muted); font-style: italic; }
  .row-preview b { color: var(--text-primary, #e2e8f0); font-weight: 600; font-variant-numeric: tabular-nums; }
  .row-warn-msg {
    font-size: 11px;
    color: var(--warning, #f59e0b);
    font-weight: 500;
    margin-top: 2px;
  }
  .footer { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .btn-save {
    padding: 7px 18px;
    background: var(--accent-primary, #3b82f6);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s;
  }
  .btn-save:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-save:hover:not(:disabled) { background: var(--accent-hover, #2563eb); }
  .btn-reset {
    padding: 7px 14px;
    background: transparent;
    color: var(--text-secondary, #94a3b8);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 8px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }
  .btn-reset:hover:not(:disabled) {
    background: var(--hover-bg, rgba(255,255,255,0.04));
    color: var(--text-primary, #e2e8f0);
  }
  .btn-reset:disabled { opacity: 0.5; cursor: not-allowed; }
  .saved-msg { font-size: 12px; color: var(--success, #10b981); font-weight: 500; }
  .saved-msg.err { color: var(--danger, #ef4444); }
</style>
