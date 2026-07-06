<script>
  /**
   * ModeDerivedExplanation - v2.1.0 pre-flight summary (U-04 / задача 4g).
   *
   * Переписан как полноценный «pre-flight summary» перед обучением модели
   * (пилот 2026-05-16: старая версия показывала 3 строки текста + 1 цифру).
   *
   * 5 секций:
   *   1. Шапка — режим / KPI / период
   *   2. Медиа-каналы — таблица с ролями, единицами, суммами
   *   3. Внешние факторы — chip-tags controls
   *   4. Исключённые колонки — accordion с причинами
   *   5. Контроль качества — ratio, период, параметры
   *   6. Финальная кнопка с estimated time
   *
   * Refs: docs/RC2_REMEDIATION_PLAN.md задача 4g
   * Refs: docs/PILOT_FINDINGS_CONSOLIDATED.md U-04
   *
   * @component ModeDerivedExplanation
   */

  import { validateData, perChannelInput, unitCosts, analysisMode, kpiType, validationMetrics } from '$lib/project-state.js';
  // v2.1.0 (пилот 2026-05-16): SSOT-классификатор ratio для согласованности
  // меток в Контроле качества с RatioInfoCard и sticky header.
  import { classifyRatio, severityTo3Tier } from '$lib/ratio-classifier.js';
  import { periodUnit, periodThreshold } from '$lib/period-format.js';
  import RatioInfoCard from './RatioInfoCard.svelte';

  /** @typedef {'roi' | 'effectiveness' | 'mixed'} AnalysisMode */

  const {
    // v2.1.0 (пилот 2026-05-16): unused - локальная кнопка заменена на
    // info-строку, реальный переход через глобальную "Далее ▶".
    // Prop оставлен для backward-compat с ValidateStepV13.
    onContinue: _onContinue = undefined,
    // legacy props (backward compat — ValidateStepV13 ещё передаёт их)
    derivedMode: _derivedMode = undefined,
    explanation: _explanation = undefined,
    perChannelInput: _perChannelInputProp = undefined,
    kpiKind: _kpiKind = undefined,
  } = $props();

  // ─── KPI label registry (mirror KPISelector) ───────────────────────
  /** @type {Record<string, string>} */
  const KPI_LABELS = {
    sales:         'Выручка (₽)',
    revenue:       'Доход (₽)',
    profit:        'Прибыль (₽)',
    sales_packs:   'Продажи в штуках',
    leads:         'Лиды',
    registrations: 'Регистрации',
    loyalty_cards: 'Выданные карты',
    subscriptions: 'Подписки',
    app_installs:  'Установки',
    count_custom:  'Свой KPI',
  };

  /** @type {Record<string, string>} */
  const MODE_LABELS = {
    roi:           'ROI',
    effectiveness: 'Эффективность',
    mixed:         'Смешанный (Expert)',
  };

  /** @type {Record<AnalysisMode, string>} */
  const MODE_DESC = {
    roi:           'Все каналы в ₽-бюджетах — модель оценивает ROI (₽ выручки / ₽ затрат)',
    effectiveness: 'Все каналы в физических контактах — модель оценивает долю в продажах',
    mixed:         'Смешанный ввод — кросс-канальное сравнение через долю в продажах',
  };

  // ─── Derived data from stores ──────────────────────────────────────

  const currentMode = $derived($analysisMode ?? /** @type {AnalysisMode} */ ('roi'));
  const currentKpiType = $derived($kpiType ?? 'sales');
  const kpiLabel = $derived(KPI_LABELS[currentKpiType] ?? currentKpiType);

  const allColumns = $derived(
    /** @type {any[]} */ ($validateData?.result?.columns ?? [])
  );

  // Медиа-каналы (role='media')
  const mediaColumns = $derived(allColumns.filter(c => c?.role === 'media'));

  // Controls (role='control')
  const controlColumns = $derived(allColumns.filter(c => c?.role === 'control'));

  // Исключённые/неиспользуемые колонки
  const unusedColumns = $derived(
    allColumns.filter(c => c?.role === 'unused' || c?.role === 'excluded')
  );

  // Число наблюдений и дата-диапазон
  const nObs = $derived(
    Number($validateData?.result?.file?.rows ?? 0)
  );

  /** Дата-статистика из date-колонки (если есть) */
  const dateStats = $derived.by(() => {
    const dateCols = allColumns.filter(c => c?.role === 'date');
    if (!dateCols.length) return null;
    return dateCols[0]?.date_stats ?? null;
  });

  /** Форматирование даты YYYY-MM-DD → MM.YYYY */
  /** @param {string} iso */
  function fmtDate(iso) {
    if (!iso) return '';
    const [y, m] = iso.split('-');
    return `${m}.${y}`;
  }

  // v2.1.0 (RC2-AUD-03 fix): читаем ratio из SSOT validationMetrics, не из
  // stale `detected.ratio` (которое было посчитано один раз при первом
  // econ_validate и не пересчитывается при frontend exclusions).
  const detectedRatio = $derived($validationMetrics?.ratio ?? 0);
  const nPredictors = $derived(
    $validationMetrics?.nPredictors ?? (mediaColumns.length + controlColumns.length)
  );

  // v2.1.0 (пилот 2026-05-16, стандартизация ratio): label и tone приходят
  // из ratio-classifier SSOT. Раньше использовался свой mini-mapping
  // (ok/warn/bad → 'Хорошее'/'Приемлемое'/'Критически мало') - 2.8 ratio
  // показывал «Критически мало», что противоречит severity warning-high.
  const ratioClass = $derived(classifyRatio(detectedRatio));
  const ratioStatus = $derived(severityTo3Tier(ratioClass.severity));
  const ratioStatusLabel = $derived(ratioClass.label);

  // ─── Таблица медиа-каналов ─────────────────────────────────────────

  /**
   * Для каждого медиа-канала — юнит-тип, cost, сумма.
   */
  const mediaTableRows = $derived.by(() => {
    return mediaColumns.map((col) => {
      const name = col.name ?? '';
      const unitType = $perChannelInput?.[name] ?? 'monetary';
      const cost = $unitCosts?.[name] ?? null;
      const rawSum = col?.stats?.sum ?? null;

      // Рублёвая сумма за период
      let totalRub = null;
      if (typeof rawSum === 'number') {
        if (unitType === 'monetary') {
          totalRub = rawSum;
        } else if (unitType === 'physical' && cost != null && cost > 0) {
          totalRub = rawSum * cost;
        }
      }

      return { name, unitType, cost, rawSum, totalRub };
    });
  });

  /** Итого по всем каналам в ₽ (где доступно) */
  const totalMediaRub = $derived(
    mediaTableRows.reduce((acc, r) => {
      if (r.totalRub != null) return acc + r.totalRub;
      return acc;
    }, 0)
  );

  /** Есть ли хоть одна строка с рублёвым итогом */
  const hasAnyRub = $derived(mediaTableRows.some(r => r.totalRub != null));

  /** Форматирование числа → читаемый вид */
  /** @param {number} n */
  function fmtNumber(n) {
    if (n == null) return '—';
    if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)} млрд`;
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} млн`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)} тыс`;
    return n.toFixed(0);
  }

  // ─── Причина исключения колонки ────────────────────────────────────
  /** @param {any} col */
  function unusedReason(col) {
    const warnings = $validateData?.result?.warnings ?? [];
    // Ищем предупреждение для этой колонки
    const w = warnings.find((/** @type {any} */ w) => w?.column === col.name);
    if (w?.type === 'high_zeros') return `${col?.stats?.zeros_pct ?? ''}% нулей — слишком мало данных`;
    if (w?.type === 'low_variance') return 'Вариативность <5% — канал не информативен';
    if (col?.role === 'excluded') return 'Исключена пользователем';
    return 'Не используется в модели';
  }

  // ─── Предупреждение по периоду ─────────────────────────────────────
  // F-A1-6: единица и порог из гранулярности, не хардкод «52 нед».
  const granularity = $derived(
    $validateData?.result?.detected?.date_frequency ?? 'W'
  );
  const granPeriodUnit = $derived(periodUnit(granularity));
  const granPeriodThreshold = $derived(periodThreshold(granularity));
  const periodWarn = $derived(nObs > 0 && nObs < granPeriodThreshold);
</script>

<div class="preflight-summary">

  <!-- ─── 1. Шапка ─────────────────────────────── -->
  <header class="summary-header">
    <div class="mode-badge mode-{currentMode}" aria-label="Режим модели">
      <span class="badge-label">Режим модели</span>
      <strong class="badge-mode">{MODE_LABELS[currentMode] ?? currentMode}</strong>
    </div>

    <div class="header-meta">
      <div class="meta-row">
        <span class="meta-key">Целевая метрика:</span>
        <span class="meta-val">{kpiLabel}</span>
      </div>
      <div class="meta-row">
        <span class="meta-key">Период:</span>
        <span class="meta-val">
          {#if nObs > 0}
            {nObs} наблюдений
            {#if dateStats?.min_date && dateStats?.max_date}
              <span class="date-range">
                (с {fmtDate(dateStats.min_date)} по {fmtDate(dateStats.max_date)})
              </span>
            {/if}
            {#if periodWarn}
              <span class="badge-warn" title="Рекомендуем ≥{granPeriodThreshold} {granPeriodUnit} для надёжных результатов">
                &lt;{granPeriodThreshold} {granPeriodUnit}
              </span>
            {/if}
          {:else}
            —
          {/if}
        </span>
      </div>
    </div>

    <p class="mode-desc">{MODE_DESC[currentMode] ?? ''}</p>
  </header>

  <!-- ─── 2. Медиа-каналы (таблица) ───────────────── -->
  <section class="summary-section" aria-labelledby="media-heading">
    <h3 class="section-heading" id="media-heading">
      Медиа-каналы
      <span class="count-badge">{mediaColumns.length}</span>
    </h3>

    {#if mediaColumns.length === 0}
      <p class="empty-note">Медиа-каналы не обнаружены — проверьте шаг Импорт.</p>
    {:else}
      <div class="table-wrap">
        <table class="media-table">
          <thead>
            <tr>
              <th>Канал</th>
              <th>Роль</th>
              <th>Единица</th>
              {#if hasAnyRub}
                <th class="col-right">Итого за период</th>
              {/if}
            </tr>
          </thead>
          <tbody>
            {#each mediaTableRows as row (row.name)}
              <tr>
                <td class="col-name">{row.name}</td>
                <td>
                  <span class="chip chip-media">Медиа-канал</span>
                </td>
                <td class="col-unit">
                  {#if row.unitType === 'monetary'}
                    <span class="unit-label monetary">спенд в ₽</span>
                  {:else}
                    <span class="unit-label physical">физ. контакты</span>
                    {#if row.cost != null}
                      <span class="unit-hint">({row.cost.toLocaleString('ru')} ₽/ед)</span>
                    {/if}
                  {/if}
                </td>
                {#if hasAnyRub}
                  <td class="col-right col-sum">
                    {#if row.totalRub != null}
                      {fmtNumber(row.totalRub)} ₽
                    {:else if row.rawSum != null}
                      <span class="sum-units">{fmtNumber(row.rawSum)} ед</span>
                    {:else}
                      —
                    {/if}
                  </td>
                {/if}
              </tr>
            {/each}
          </tbody>
          {#if hasAnyRub && mediaTableRows.length > 1}
            <tfoot>
              <tr class="row-total">
                <td colspan={hasAnyRub ? 3 : 3}>ИТОГО медиа</td>
                <td class="col-right">
                  {#if totalMediaRub > 0}
                    {fmtNumber(totalMediaRub)} ₽
                  {:else}
                    —
                  {/if}
                </td>
              </tr>
            </tfoot>
          {/if}
        </table>
      </div>
    {/if}
  </section>

  <!-- ─── 3. Внешние факторы (controls) ───────────── -->
  {#if controlColumns.length > 0}
    <section class="summary-section" aria-labelledby="controls-heading">
      <h3 class="section-heading" id="controls-heading">
        Внешние факторы
        <span class="count-badge">{controlColumns.length}</span>
        <span
          class="help-icon"
          title="Контрольные переменные — сезонность, праздники, промо-активности. Они объясняют движение KPI, не связанное с медиа-расходами."
          aria-label="Что такое внешние факторы"
        >?</span>
      </h3>
      <div class="chips-row" role="list" aria-label="Список контрольных переменных">
        {#each controlColumns as col (col.name)}
          <span class="chip chip-control" role="listitem">{col.name}</span>
        {/each}
      </div>
    </section>
  {/if}

  <!-- ─── 4. Исключённые колонки (accordion) ───────── -->
  {#if unusedColumns.length > 0}
    <section class="summary-section" aria-labelledby="excluded-heading">
      <details class="excluded-accordion">
        <summary class="excluded-summary" id="excluded-heading">
          <h3 class="section-heading inline">
            Исключённые колонки
            <span class="count-badge count-muted">{unusedColumns.length}</span>
          </h3>
          <span class="accordion-hint">развернуть ▾</span>
        </summary>
        <div class="excluded-list">
          {#each unusedColumns as col (col.name)}
            <div class="excluded-row">
              <span class="excluded-name">{col.name}</span>
              <span class="excluded-reason">{unusedReason(col)}</span>
            </div>
          {/each}
        </div>
      </details>
    </section>
  {/if}

  <!-- ─── 5. Контроль качества ────────────────────── -->
  <section class="summary-section" aria-labelledby="quality-heading">
    <h3 class="section-heading" id="quality-heading">Контроль качества</h3>

    <div class="quality-grid">
      <!-- Ratio -->
      <div class="quality-card tone-{ratioStatus}" aria-label="Запас данных">
        <span class="qc-label">Запас данных (Ratio)</span>
        <span class="qc-value">{detectedRatio > 0 ? detectedRatio.toFixed(1) + ':1' : '—'}</span>
        <span class="qc-status">{ratioStatusLabel}</span>
      </div>

      <!-- Период -->
      <div class="quality-card {periodWarn ? 'tone-warn' : 'tone-ok'}" aria-label="Период">
        <span class="qc-label">Период</span>
        <span class="qc-value">{nObs > 0 ? nObs + ' нед' : '—'}</span>
        <span class="qc-status">{periodWarn ? '< 52 нед' : nObs >= 104 ? 'Отлично' : 'Достаточно'}</span>
      </div>

      <!-- Каналы -->
      <div class="quality-card tone-ok" aria-label="Каналы">
        <span class="qc-label">Каналов</span>
        <span class="qc-value">{mediaColumns.length}</span>
        <span class="qc-status">медиа</span>
      </div>

      <!-- Параметров -->
      <div class="quality-card tone-ok" aria-label="Переменных">
        <span class="qc-label">Переменных</span>
        <span class="qc-value">{nPredictors > 0 ? nPredictors : mediaColumns.length + controlColumns.length}</span>
        <span class="qc-status">в модели</span>
      </div>
    </div>

    <!-- Полный RatioInfoCard для детального объяснения (compact) -->
    {#if detectedRatio > 0 && nObs > 0 && nPredictors > 0}
      <div class="ratio-card-wrap">
        <RatioInfoCard
          ratio={detectedRatio}
          nObs={nObs}
          nPredictors={nPredictors}
          expertMode={false}
        />
      </div>
    {/if}
  </section>

  <!-- ─── 6. Информирующая строка (не кнопка - см. fix 2026-05-16) ─── -->
  <footer class="summary-footer">
    <div class="footer-hint">
      Все параметры можно изменить на шаге Декомпозиция после обучения.
    </div>
    <!-- v2.1.0 (пилот 2026-05-16): Антон: «Перейти к моделированию не должна
         быть кнопкой - сейчас нажимается без эффекта, дублирует "Далее ▶".
         Должна быть информирующая строка без взаимодействия». Глобальная
         кнопка "Далее ▶" в footer'е делает реальный переход. -->
    <div class="next-hint" aria-live="polite">
      <span class="next-hint-text">Вы готовы переходить к обучению модели</span>
    </div>
  </footer>
</div>

<style>
  /* ─── Layout ─────────────────────────────────────── */
  .preflight-summary {
    display: flex;
    flex-direction: column;
    gap: 0;
    max-width: 860px;
    margin: 0 auto;
    width: 100%;
    font-family: var(--font-sans, system-ui, sans-serif);
  }

  /* ─── Header ─────────────────────────────────────── */
  .summary-header {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 24px 24px 20px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
    border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
  }

  .mode-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
    border-radius: 999px;
    border: 1.5px solid var(--accent-primary, #6366f1);
    background: color-mix(in srgb, var(--accent-primary, #6366f1) 8%, transparent);
    width: fit-content;
  }
  .mode-badge.mode-effectiveness {
    border-color: var(--success, #4ade80);
    background: color-mix(in srgb, var(--success, #4ade80) 8%, transparent);
  }
  .mode-badge.mode-mixed {
    border-color: var(--warning, #fbbf24);
    background: color-mix(in srgb, var(--warning, #fbbf24) 8%, transparent);
  }
  .badge-label {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-muted, #64748b);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .badge-mode {
    font-size: 13px;
    font-weight: 700;
    color: var(--accent-primary, #6366f1);
  }
  .mode-badge.mode-effectiveness .badge-mode { color: var(--success, #4ade80); }
  .mode-badge.mode-mixed .badge-mode { color: var(--warning, #fbbf24); }

  .header-meta {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .meta-row {
    display: flex;
    gap: 8px;
    align-items: baseline;
    font-size: 13px;
    flex-wrap: wrap;
  }
  .meta-key {
    color: var(--text-muted, #64748b);
    font-weight: 500;
    min-width: 130px;
    flex-shrink: 0;
  }
  .meta-val {
    color: var(--text-primary, #f1f5f9);
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .date-range {
    color: var(--text-secondary, #94a3b8);
    font-weight: 400;
    font-size: 12px;
  }
  .badge-warn {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 700;
    background: color-mix(in srgb, var(--warning, #fbbf24) 15%, transparent);
    color: var(--warning, #fbbf24);
    border: 1px solid color-mix(in srgb, var(--warning, #fbbf24) 35%, transparent);
    cursor: help;
  }
  .mode-desc {
    margin: 0;
    font-size: 12.5px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.5;
    font-style: italic;
  }

  /* ─── Section common ──────────────────────────────── */
  .summary-section {
    padding: 20px 24px;
    border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
  }
  .section-heading {
    margin: 0 0 14px;
    font-family: var(--font-serif, Georgia, serif);
    font-size: 16px;
    font-weight: 400;
    color: var(--text-primary, #f1f5f9);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .section-heading.inline {
    margin: 0;
    font-size: 14px;
  }

  .count-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 20px;
    height: 20px;
    padding: 0 5px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--accent-primary, #6366f1) 15%, transparent);
    color: var(--accent-primary, #6366f1);
    font-size: 11px;
    font-weight: 700;
    font-family: var(--font-sans, system-ui, sans-serif);
  }
  .count-badge.count-muted {
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
    color: var(--text-muted, #64748b);
  }

  .help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--text-muted, #64748b) 16%, transparent);
    color: var(--text-secondary, #94a3b8);
    font-size: 10px;
    font-weight: 700;
    font-family: var(--font-sans, system-ui, sans-serif);
    cursor: help;
    user-select: none;
  }
  .help-icon:hover {
    background: color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
    color: var(--gold, #c9a449);
  }

  .empty-note {
    margin: 0;
    font-size: 13px;
    color: var(--text-muted, #64748b);
    font-style: italic;
  }

  /* ─── Media table ─────────────────────────────────── */
  .table-wrap {
    overflow-x: auto;
    border-radius: 4px;
    border: 1px solid var(--border, rgba(255,255,255,0.08));
  }
  .media-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
    color: var(--text-secondary, #94a3b8);
  }
  .media-table thead tr {
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
  }
  .media-table th {
    padding: 8px 12px;
    text-align: left;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted, #64748b);
    border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
    white-space: nowrap;
  }
  .media-table td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.05));
    vertical-align: middle;
  }
  .media-table tbody tr:last-child td { border-bottom: none; }
  .media-table tbody tr:hover { background: var(--bg-surface-quiet, rgba(255,255,255,0.03)); }

  .col-name {
    color: var(--text-primary, #f1f5f9);
    font-weight: 500;
    font-size: 13px;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .col-unit { white-space: nowrap; }
  .col-right { text-align: right; white-space: nowrap; }
  .col-sum {
    color: var(--text-primary, #f1f5f9);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    font-size: 13px;
  }
  .sum-units {
    color: var(--text-muted, #64748b);
    font-weight: 400;
  }

  .media-table tfoot .row-total td {
    padding: 10px 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted, #64748b);
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
    border-top: 1px solid var(--border, rgba(255,255,255,0.08));
    border-bottom: none;
  }
  .media-table tfoot .row-total .col-right {
    color: var(--text-primary, #f1f5f9);
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }

  /* chips */
  .chip {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.03em;
    white-space: nowrap;
  }
  .chip-media {
    background: color-mix(in srgb, var(--accent-primary, #6366f1) 10%, transparent);
    color: var(--accent-primary, #6366f1);
    border: 1px solid color-mix(in srgb, var(--accent-primary, #6366f1) 25%, transparent);
  }

  .unit-label {
    font-size: 12px;
    font-weight: 500;
  }
  .unit-label.monetary { color: var(--success, #4ade80); }
  .unit-label.physical { color: var(--accent-primary, #6366f1); }
  .unit-hint {
    font-size: 10.5px;
    color: var(--text-muted, #64748b);
    margin-left: 4px;
  }

  /* ─── Controls chips ──────────────────────────────── */
  .chips-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chip-control {
    background: color-mix(in srgb, var(--gold, #c9a449) 10%, transparent);
    color: var(--gold, #c9a449);
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 25%, transparent);
  }

  /* ─── Excluded accordion ──────────────────────────── */
  .excluded-accordion {
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: 4px;
    overflow: hidden;
  }
  .excluded-summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    cursor: pointer;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.03));
    list-style: none;
    user-select: none;
  }
  .excluded-summary::-webkit-details-marker { display: none; }
  .excluded-summary::marker { display: none; }
  .accordion-hint {
    font-size: 11px;
    color: var(--text-muted, #64748b);
    white-space: nowrap;
  }
  details[open] .accordion-hint { display: none; }
  .excluded-list {
    padding: 8px 0;
    border-top: 1px solid var(--border, rgba(255,255,255,0.08));
  }
  .excluded-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 14px;
    font-size: 12px;
    flex-wrap: wrap;
  }
  .excluded-row:hover { background: rgba(255,255,255,0.02); }
  .excluded-name {
    color: var(--text-secondary, #94a3b8);
    font-weight: 500;
    min-width: 120px;
  }
  .excluded-reason {
    color: var(--text-muted, #64748b);
    font-style: italic;
    font-size: 11.5px;
  }

  /* ─── Quality grid ────────────────────────────────── */
  .quality-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 10px;
    margin-bottom: 16px;
  }
  .quality-card {
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 12px 14px;
    border-radius: 4px;
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    background: var(--bg-card, #0f172a);
    border-left-width: 3px;
  }
  .quality-card.tone-ok  { border-left-color: var(--success, #4ade80); }
  .quality-card.tone-warn { border-left-color: var(--warning, #fbbf24); }
  .quality-card.tone-bad { border-left-color: var(--danger, #f87171); }

  .qc-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-muted, #64748b);
  }
  .qc-value {
    font-size: 22px;
    font-weight: 700;
    font-family: var(--font-serif, Georgia, serif);
    color: var(--text-primary, #f1f5f9);
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .qc-status {
    font-size: 10.5px;
    color: var(--text-secondary, #94a3b8);
  }

  .ratio-card-wrap {
    margin-top: 4px;
  }

  /* ─── Footer ──────────────────────────────────────── */
  .summary-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    padding: 20px 24px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.02));
  }
  .footer-hint {
    font-size: 12px;
    color: var(--text-muted, #64748b);
    font-style: italic;
    max-width: 300px;
  }
  /* v2.1.0 (пилот 2026-05-16): информирующая строка вместо кнопки.
     Без cursor / hover / border / background-accent - чтобы пользователь
     не пытался кликнуть и не думал, что это интерактивный элемент.
     Реальный переход выполняет глобальная "Далее ▶" в footer'е layout'а. */
  .next-hint {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-radius: var(--radius-btn, 6px);
    background: var(--bg-surface-quiet, rgba(255,255,255,0.03));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    color: var(--text-secondary, #94a3b8);
    font-size: 12.5px;
    font-weight: 400;
    line-height: 1.3;
    white-space: nowrap;
    cursor: default;
    user-select: text;
  }
  .next-hint-text {
    color: var(--text-secondary, #94a3b8);
  }

  /* ─── Responsive ─────────────────────────────────── */
  @media (max-width: 600px) {
    .summary-header,
    .summary-section,
    .summary-footer { padding-left: 16px; padding-right: 16px; }
    .meta-key { min-width: 110px; }
    .quality-grid { grid-template-columns: repeat(2, 1fr); }
    .summary-footer { flex-direction: column; align-items: flex-start; }
    .footer-hint { max-width: none; }
  }
</style>
