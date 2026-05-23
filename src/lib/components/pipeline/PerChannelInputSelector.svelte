<script>
  /**
   * PerChannelInputSelector - v1.3.0 third sub-step of Validate (per ADR-015).
   *
   * Для каждого канала юзер выбирает: подаём в модель бюджет (₽) или физ. контакты
   * (показы / клики / GRP). Если доступна только одна метрика - radio автоматически
   * locked. Если обе доступны - юзер выбирает explicit.
   *
   * Emits onConfirm(perChannelInput) - dict {channel: 'monetary'|'physical'}.
   *
   * ADR-019 §1: visible ТОЛЬКО в Expert mode. В Manager mode родитель рендерит
   * AppliedModeSummary вместо этого компонента. Данный guard - defense-in-depth.
   *
   * @component PerChannelInputSelector
   */

  import { expertMode, analysisMode } from '$lib/project-state.js';

  // Mode-aware заголовки и тексты (U-02/4e).
  const modeHeading = $derived(
    $analysisMode === 'roi'
      ? 'Все каналы в модели будут в рублях'
      : $analysisMode === 'effectiveness'
        ? 'Все каналы в модели будут в физических контактах'
        : 'Поканальный выбор единиц'
  );

  const modeLead = $derived(
    $analysisMode === 'roi'
      ? 'Если у канала есть бюджет — используйте ₽-бюджет. Если только физические контакты (TRP, показы, клики) — укажите цену 1 единицы или общий бюджет за период, и Aurora сконвертирует. Без денежного эквивалента ROI канала математически не определён.'
      : $analysisMode === 'effectiveness'
        ? 'Если у канала есть только бюджет — можем конвертировать обратно через обычную цену контакта (CPP/CPM). Деньги как сырая метрика в этом режиме не дают долей вклада в KPI.'
        : 'Каждый канал в той единице, в которой данные более надёжны. Точность ROI ±10–25% за счёт смешения единиц.'
  );

  // Метки радио-опций адаптируются к режиму.
  const monetaryLabel = $derived(
    $analysisMode === 'effectiveness' ? '₽ бюджет + цена контакта' : '₽ бюджет'
  );

  const physicalLabel = $derived(
    $analysisMode === 'roi' ? '📊 контакты + цена' : '📊 контакты'
  );

  /** @typedef {{
    monetary: string[],
    physical: string[],
  }} AvailableMetrics */

  const {
    channels,                   // ['tv', 'olv', 'performance', ...]
    availableMetricsByChannel,  // {channel: AvailableMetrics}
    columnStats = {},           // v1.3.2: {colName: {zeros_pct, missing_pct}}
    currentSelection,           // {channel: 'monetary'|'physical'} | null
    onConfirm,                  // callback(perChannelInput)
  } = $props();

  /**
   * v1.3.2: aggregate stats для group of columns. Возвращает min zeros / max
   * missing / average чтобы быстро сравнить «чистоту» monetary vs physical
   * option per channel.
   * @param {string[]} colNames
   * @returns {{ zeros: number, missing: number, count: number } | null}
   */
  function aggregateStats(colNames) {
    if (!colNames || colNames.length === 0) return null;
    let zerosSum = 0;
    let missingSum = 0;
    let count = 0;
    for (const name of colNames) {
      const s = columnStats[name];
      if (!s) continue;
      zerosSum += Number(s.zeros_pct ?? 0);
      missingSum += Number(s.missing_pct ?? 0);
      count += 1;
    }
    if (count === 0) return null;
    return {
      zeros: zerosSum / count,
      missing: missingSum / count,
      count,
    };
  }

  /**
   * Determine рекомендованный choice (monetary vs physical) per channel based
   * on data quality. Lower zeros% = более надёжный источник.
   * @param {string} channel
   * @returns {'monetary' | 'physical' | null}
   */
  function recommendedChoice(channel) {
    const av = availableMetricsByChannel[channel] || { monetary: [], physical: [] };
    const monAgg = aggregateStats(av.monetary);
    const physAgg = aggregateStats(av.physical);
    if (!monAgg && !physAgg) return null;
    if (!monAgg) return 'physical';
    if (!physAgg) return 'monetary';
    // Recommend option с lower zeros% (cleaner data).
    if (Math.abs(monAgg.zeros - physAgg.zeros) < 5) return null;  // tie
    return monAgg.zeros < physAgg.zeros ? 'monetary' : 'physical';
  }

  // Initialize selection с smart defaults.
  /** @type {Record<string, string>} */
  let selection = $state(
    currentSelection
      ? { ...currentSelection }
      : Object.fromEntries(/** @type {string[]} */ (channels).map((/** @type {string} */ ch) => {
          const av = availableMetricsByChannel[ch] || { monetary: [], physical: [] };
          if (av.monetary.length > 0) return [ch, 'monetary'];
          if (av.physical.length > 0) return [ch, 'physical'];
          return [ch, 'monetary'];
        }))
  );

  // v1.3.2: «Зачем это?» раскрывающаяся панель с объяснением выбора метрик.
  let whyExpanded = $state(false);

  /** @param {string} channel */
  function isLocked(channel) {
    const av = availableMetricsByChannel[channel] || { monetary: [], physical: [] };
    return (av.monetary.length === 0) || (av.physical.length === 0);
  }

  /** @param {string} channel @param {string} metric */
  function setMetric(channel, metric) {
    selection = { ...selection, [channel]: metric };
  }

  function handleConfirm() {
    onConfirm?.(selection);
  }
</script>

{#if $expertMode}
<div class="per-channel-selector">
  <header>
    <h2>{modeHeading}</h2>
    <p class="lead">
      {modeLead}
      <button
        class="why-link"
        type="button"
        aria-expanded={whyExpanded}
        onclick={() => (whyExpanded = !whyExpanded)}
      >Зачем это? <span class="chevron" class:open={whyExpanded}>▾</span></button>
    </p>
    {#if whyExpanded}
      <div class="why-panel" role="region" aria-label="Подробное объяснение">
        {#if $analysisMode === 'roi'}
          <p><strong>Почему все каналы в рублях в режиме ROI?</strong></p>
          <p>
            ROI — это возврат на инвестиции: сколько рублей продаж приносит каждый рубль вложений.
            Для расчёта ROI модели нужен <em>денежный эквивалент</em> каждого канала.
          </p>
          <ul>
            <li>
              <strong>Есть бюджет (₽)</strong> — используйте напрямую. Это самый чистый вариант.
            </li>
            <li>
              <strong>Есть только физические контакты (TRP, показы, клики)</strong> — укажите цену 1 единицы
              или общий бюджет за период. Aurora выполнит конвертацию автоматически.
            </li>
          </ul>
          <p class="why-tip">
            <strong>Важно:</strong> если ни бюджета, ни цены контакта нет — ROI канала математически не определён.
            Модель либо исключит канал, либо использует контрольную оценку.
          </p>
        {:else if $analysisMode === 'effectiveness'}
          <p><strong>Почему все каналы в физических контактах в режиме Эффективности?</strong></p>
          <p>
            Режим Эффективности измеряет <em>доли вклада</em> каналов в KPI (продажи, знание, трафик).
            Единица — контакты, GRP, показы: именно они создают «давление» на потребителя.
          </p>
          <ul>
            <li>
              <strong>Есть физические контакты</strong> — используйте напрямую. Это корректная единица для share-attribution.
            </li>
            <li>
              <strong>Есть только бюджет (₽)</strong> — укажите типичную цену контакта (CPP/CPM).
              Aurora конвертирует бюджет в контакты для выравнивания шкал.
            </li>
          </ul>
          <p class="why-tip">
            <strong>Важно:</strong> рубли как <em>сырая</em> метрика в этом режиме не показывают доли вклада —
            только косвенно через стоимость. Без конвертации через цену контакта результаты будут искажены.
          </p>
        {:else}
          <p><strong>Поканальный выбор единиц (режим Эксперт):</strong></p>
          <p>
            Каждый канал можно настроить индивидуально — в той единице, в которой данные надёжнее.
          </p>
          <ul>
            <li>
              <strong>Бюджет (₽)</strong> — если деньги точные (Performance, Social Ads, OOH с фиксированной ценой).
            </li>
            <li>
              <strong>Физические контакты</strong> — если бюджет непрозрачен (агентские скидки), но GRP / показы измерены точно (TV, OLV).
            </li>
          </ul>
          <p class="why-tip">
            <strong>Предупреждение:</strong> смешение единиц вносит погрешность ±10–25% в точность ROI.
            Используйте этот режим осознанно, когда единообразие данных невозможно.
          </p>
        {/if}
      </div>
    {/if}
  </header>

  <table class="channels-table">
    <thead>
      <tr>
        <th>Канал</th>
        <th>Доступные метрики</th>
        <th>Использовать</th>
      </tr>
    </thead>
    <tbody>
      {#each channels as ch (ch)}
        {@const av = availableMetricsByChannel[ch] || { monetary: [], physical: [] }}
        {@const locked = isLocked(ch)}
        {@const monAgg = aggregateStats(av.monetary)}
        {@const physAgg = aggregateStats(av.physical)}
        {@const recommended = recommendedChoice(ch)}
        <tr class:row-monetary={selection[ch] === 'monetary'} class:row-physical={selection[ch] === 'physical'}>
          <td class="channel-name">{ch}</td>
          <td class="available-metrics">
            {#if av.monetary.length > 0}
              <span class="metric-badge monetary" title={av.monetary.join(', ')}>
                ₽ {av.monetary.length === 1 ? av.monetary[0] : `${av.monetary.length} колонок`}
              </span>
            {/if}
            {#if av.physical.length > 0}
              <span class="metric-badge physical" title={av.physical.join(', ')}>
                📊 {av.physical.length === 1 ? av.physical[0] : `${av.physical.length} колонок`}
              </span>
            {/if}
            {#if av.monetary.length === 0 && av.physical.length === 0}
              <span class="missing">Колонки не найдены</span>
            {/if}
          </td>
          <td class="radio-cell">
            <label
              class:locked={locked && av.physical.length === 0}
              class:recommended={recommended === 'monetary'}
            >
              <input
                type="radio"
                name="metric-{ch}"
                value="monetary"
                checked={selection[ch] === 'monetary'}
                disabled={av.monetary.length === 0}
                onchange={() => setMetric(ch, 'monetary')}
              />
              <span class="radio-label-text">{monetaryLabel}</span>
              {#if monAgg}
                <span class="quality-stat {monAgg.zeros > 50 ? 'q-bad' : monAgg.zeros > 25 ? 'q-warn' : 'q-good'}"
                  title="Среднее по {monAgg.count} колон{monAgg.count === 1 ? 'ке' : 'кам'}: {monAgg.zeros.toFixed(0)}% нулей, {monAgg.missing.toFixed(0)}% пропусков.">
                  {monAgg.zeros.toFixed(0)}% нулей
                </span>
              {/if}
              {#if recommended === 'monetary'}
                <span class="reco-tag" title="Рекомендуем - у бюджета меньше нулей чем у физических метрик.">рек.</span>
              {/if}
            </label>
            <label
              class:locked={locked && av.monetary.length === 0}
              class:recommended={recommended === 'physical'}
            >
              <input
                type="radio"
                name="metric-{ch}"
                value="physical"
                checked={selection[ch] === 'physical'}
                disabled={av.physical.length === 0}
                onchange={() => setMetric(ch, 'physical')}
              />
              <span class="radio-label-text">{physicalLabel}</span>
              {#if physAgg}
                <span class="quality-stat {physAgg.zeros > 50 ? 'q-bad' : physAgg.zeros > 25 ? 'q-warn' : 'q-good'}"
                  title="Среднее по {physAgg.count} колон{physAgg.count === 1 ? 'ке' : 'кам'}: {physAgg.zeros.toFixed(0)}% нулей, {physAgg.missing.toFixed(0)}% пропусков.">
                  {physAgg.zeros.toFixed(0)}% нулей
                </span>
              {/if}
              {#if recommended === 'physical'}
                <span class="reco-tag" title="Рекомендуем - у физических метрик меньше нулей чем у бюджета.">рек.</span>
              {/if}
            </label>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <footer class="actions">
    <button type="button" class="btn-primary" onclick={handleConfirm}>
      Подтвердить выбор →
    </button>
  </footer>
</div>
{/if}

<style>
  .per-channel-selector {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px;
    max-width: 1100px;
    margin: 0 auto;
    width: 100%;
  }
  header h2 {
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 4px;
  }
  .lead {
    font-size: 12px;
    color: var(--text-secondary);
    margin: 0;
    line-height: 1.5;
  }
  .lead strong { color: var(--text-primary); font-weight: 600; }
  .why-link {
    background: none;
    border: none;
    color: var(--accent-primary);
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    text-decoration: underline dashed;
    padding: 0 4px;
  }
  .why-link:hover { color: var(--gold, #c9a449); }
  .chevron {
    font-size: 9px;
    display: inline-block;
    transition: transform 0.2s;
  }
  .chevron.open { transform: rotate(180deg); }

  /* v1.3.2: «Зачем это?» раскрывающаяся панель - premium tier-1. */
  .why-panel {
    margin-top: 12px;
    padding: 14px 18px;
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, var(--bg-card, #0f172a));
    border-left: 2px solid var(--gold, #c9a449);
    border-radius: 0 6px 6px 0;
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--text-secondary);
  }
  .why-panel p { margin: 0 0 8px; }
  .why-panel p:last-child { margin-bottom: 0; }
  .why-panel ul {
    margin: 0 0 12px;
    padding-left: 18px;
  }
  .why-panel li { padding: 3px 0; }
  .why-panel strong { color: var(--text-primary); font-weight: 600; }
  .why-tip {
    margin-top: 10px !important;
    padding-top: 10px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    color: var(--text-primary);
  }

  .channels-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--bg-card);
    border-radius: var(--radius-card, 10px);
    overflow: hidden;
    border: 1px solid var(--border);
  }
  .channels-table th {
    text-align: left;
    padding: 10px 14px;
    background: var(--bg-surface-quiet);
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    font-weight: 700;
  }
  .channels-table td {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border-subtle);
    font-size: 13px;
    color: var(--text-primary);
    vertical-align: middle;
  }
  .channels-table tr:last-child td { border-bottom: none; }
  /* UX audit v1.3.0: visual feedback на selected row (был только radio dot, легко промахнуться). */
  .channels-table tr.row-monetary {
    background: color-mix(in srgb, var(--accent-primary) 4%, transparent);
  }
  .channels-table tr.row-physical {
    background: color-mix(in srgb, var(--success, #4ade80) 4%, transparent);
  }
  .channels-table tbody tr:hover {
    background: color-mix(in srgb, var(--text-primary) 4%, transparent);
  }

  .channel-name { font-weight: 600; }
  .available-metrics { display: flex; gap: 8px; flex-wrap: wrap; }
  .metric-badge {
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-secondary);
  }
  .metric-badge.monetary {
    background: color-mix(in srgb, var(--accent-primary) 12%, transparent);
    color: var(--accent-primary);
  }
  .metric-badge.physical {
    background: color-mix(in srgb, var(--success, #4ade80) 12%, transparent);
    color: var(--success, #4ade80);
  }
  .missing { color: var(--text-muted); font-style: italic; font-size: 11px; }

  .radio-cell { display: flex; gap: 14px; }
  .radio-cell label {
    display: flex;
    gap: 6px;
    align-items: center;
    cursor: pointer;
    font-size: 12px;
    color: var(--text-secondary);
  }
  /* UX audit v1.3.0: clear disabled state (был просто muted color). */
  .radio-cell label.locked {
    color: var(--text-muted);
    cursor: not-allowed;
    opacity: 0.5;
    text-decoration: line-through;
  }
  .radio-cell input[type="radio"]:disabled + * { color: var(--text-muted); }

  /* v1.3.2: quality-stat badge per radio option - zeros% preview. */
  .quality-stat {
    display: inline-flex;
    align-items: center;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    line-height: 1.4;
    font-variant-numeric: tabular-nums;
    border: 1px solid transparent;
    cursor: help;
    white-space: nowrap;
  }
  .quality-stat.q-good {
    background: color-mix(in srgb, var(--success, #4ade80) 10%, transparent);
    border-color: color-mix(in srgb, var(--success, #4ade80) 25%, transparent);
    color: var(--success, #4ade80);
  }
  .quality-stat.q-warn {
    background: color-mix(in srgb, var(--gold, #c9a449) 10%, transparent);
    border-color: color-mix(in srgb, var(--gold, #c9a449) 25%, transparent);
    color: var(--gold, #c9a449);
  }
  .quality-stat.q-bad {
    background: color-mix(in srgb, var(--danger, #f87171) 10%, transparent);
    border-color: color-mix(in srgb, var(--danger, #f87171) 25%, transparent);
    color: var(--danger, #f87171);
  }

  /* v1.3.2: «рек.» recommendation tag для option с лучшей data quality. */
  .reco-tag {
    display: inline-flex;
    align-items: center;
    padding: 1px 6px;
    border-radius: 3px;
    background: color-mix(in srgb, var(--gold, #c9a449) 18%, transparent);
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 40%, transparent);
    color: var(--gold, #c9a449);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    cursor: help;
  }
  .radio-cell label.recommended {
    color: var(--text-primary);
  }
  .radio-cell label.recommended .radio-label-text {
    font-weight: 600;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
  }
  .btn-primary {
    padding: 10px 18px;
    border-radius: var(--radius-btn, 8px);
    font-size: 13px;
    font-weight: 600;
    background: var(--accent-primary);
    color: #fff;
    border: 1px solid var(--accent-primary);
    cursor: pointer;
    font: inherit;
  }
</style>
