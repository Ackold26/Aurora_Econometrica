<script>
  /**
   * Step 5: Report — Markdown & XLSX export from MMM pipeline data.
   * R1: Summary cards from modelData / decomposeData / optimizeData.
   * R2: econ_generate_report → Markdown file with Executive Summary preview.
   * R3: econ_export_xlsx → multi-sheet XLSX (5 sheets).
   * R4: completeStep(5) + triggerCompletion() on finish.
   * Layout: summary-cards → generate-card → complete-row.
   * @component ReportStep
   */
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import {
    activeProjectId,
    modelData,
    decomposeData,
    optimizeData,
    completeStep,
    setStepError,
    triggerCompletion,
  } from '$lib/project-state.js';

  /** @type {'idle' | 'generating-report' | 'generating-xlsx' | 'done' | 'error'} */
  let stepState = $state('idle');
  /** @type {string | null} */
  let errorMessage = $state(null);
  /** @type {string | null} */
  let reportPath = $state(null);
  /** @type {string | null} */
  let xlsxPath = $state(null);
  /** @type {string | null} */
  let pptxPath = $state(null);
  /** @type {string | null} */
  let executiveSummary = $state(null);

  // Reactive store reads
  const mData = $derived($modelData);
  const dData = $derived($decomposeData);
  const oData = $derived($optimizeData);

  // Summary card values
  const mqs      = $derived(/** @type {number|null} */ (mData?.diagnostics?.mqs?.score ?? null));
  const mqsLabel = $derived(/** @type {string} */ (mData?.diagnostics?.mqs?.tier_label ?? '—'));
  const rSq      = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.r_squared ?? mData?.diagnostics?.r_squared ?? null));
  const mape     = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.mape_pct ?? mData?.diagnostics?.mape ?? null));
  const lift     = $derived(/** @type {number|null} */ (oData?.expected_lift_pct ?? null));
  const budget   = $derived(/** @type {number|null} */ (oData?.total_budget ?? null));

  const hasData  = $derived(!!mData?.diagnostics && !!dData && !!oData);

  // ── Dynamic summary for cover email ─────────────────────────────────────────
  const ratio    = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.ratio ?? null));
  const rHat     = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.r_hat_max ?? null));
  const divergences = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.divergences ?? null));
  const basePct  = $derived(/** @type {number|null} */ (dData?.baseline_pct ?? null));
  const decChannels = $derived(/** @type {any[]} */ (dData?.channels ?? []));
  const nChannels = $derived(decChannels.length);
  const nPeriods = $derived((dData?.time_series?.dates ?? []).length);
  const topDriver = $derived(
    [...decChannels].sort((a, b) => (b.contribution_pct || 0) - (a.contribution_pct || 0))[0] ?? null
  );
  const suspiciousChannels = $derived(
    decChannels.filter(/** @param {any} c */ c => /подозрительно/i.test(c.verdict || ''))
  );
  const lossChannels = $derived(
    decChannels.filter(/** @param {any} c */ c => /убыточн/i.test(c.verdict || ''))
  );

  /** Краткое описание модели (2-3 предложения). */
  const modelSummary = $derived.by(() => {
    if (!mData?.diagnostics) return '';
    const parts = [];
    parts.push(`Bayesian Marketing Mix Model с ${nChannels} канал${nChannels > 4 ? 'ами' : nChannels > 1 ? 'ами' : 'ом'} медиа через Adstock (отложенный эффект) + Hill saturation (убывающая отдача).`);
    parts.push(`Оценка через MCMC-сэмплер${rHat != null ? `, R-hat = ${rHat.toFixed(3)}` : ''}${divergences != null ? `, дивергенций ${divergences}` : ''}.`);
    if (nPeriods > 0) parts.push(`База данных: ${nPeriods} период${nPeriods > 4 ? 'ов' : nPeriods > 1 ? 'а' : ''}${ratio != null ? `, Ratio наблюдений к параметрам ${ratio.toFixed(1)}:1` : ''}.`);
    return parts.join(' ');
  });

  /** Краткое описание результатов (2-3 предложения). */
  const resultsSummary = $derived.by(() => {
    if (!mData?.diagnostics) return '';
    const parts = [];
    if (mqs != null) parts.push(`Качество модели: MQS ${mqs.toFixed(0)} (${mqsLabel})${rSq != null ? `, R² ${rSq.toFixed(3)}` : ''}${mape != null ? `, MAPE ${mape.toFixed(1)}%` : ''}.`);
    if (basePct != null) parts.push(`Декомпозиция продаж: baseline ${basePct.toFixed(0)}%, медиа-вклад ${(100 - basePct).toFixed(0)}%.`);
    if (topDriver) parts.push(`Главный драйвер — ${topDriver.name} (${topDriver.contribution_pct?.toFixed(0) ?? '—'}% от медиа-вклада, ROI ${topDriver.roi?.toFixed(2) ?? '—'}×).`);
    if (lift != null) {
      if (lift > 5) parts.push(`Оптимизация обещает +${lift.toFixed(1)}% KPI при текущем бюджете.`);
      else if (lift > 0.5) parts.push(`Оптимизация: +${lift.toFixed(1)}% — план близок к оптимальному.`);
      else parts.push(`Оптимизация: прирост ≈0% — план уже оптимален в заданных ограничениях.`);
    }
    return parts.join(' ');
  });

  /** Ограничения моделирования. */
  const limitationsSummary = $derived.by(() => {
    if (!mData?.diagnostics) return '';
    const items = [];
    if (ratio != null && ratio < 2) {
      items.push(`Данных критически мало (Ratio ${ratio.toFixed(1)}:1 < 2:1) — высокий риск переобучения. ROI и декомпозицию рассматривайте как ориентир, не истину.`);
    } else if (ratio != null && ratio < 4) {
      items.push(`Данных мало (Ratio ${ratio.toFixed(1)}:1 < 4:1 рекомендуемых). Доверительные интервалы широкие, CI для отдельных каналов могут включать 0.`);
    }
    if (suspiciousChannels.length > 0) {
      const names = suspiciousChannels.map(/** @param {any} c */ c => c.name).join(', ');
      items.push(`Каналы с подозрительно высоким ROI (${names}) — скорее всего артефакт переобучения или смешанных единиц измерения; не используйте их абсолютные значения.`);
    }
    if (lossChannels.length > 0) {
      const names = lossChannels.map(/** @param {any} c */ c => c.name).join(', ');
      items.push(`Убыточные/перенасыщенные каналы: ${names}. Перед решениями о перераспределении проверьте корректность unit_costs.`);
    }
    items.push('Модель описывает историю — прогнозы чувствительны к изменению креатива, новым кампаниям и структурным сдвигам рынка.');
    items.push('Перед принятием решений — пилот 4-6 недель на части бюджета (20-30%) для валидации на практике.');
    return items;
  });

  // ── Helpers ────────────────────────────────────────────────────────────────

  /**
   * @param {number | null} n
   * @param {number} [dec]
   */
  function fmt(n, dec = 1) {
    if (n == null) return '—';
    return n.toFixed(dec);
  }

  /** @param {number | null} n */
  function fmtBudget(n) {
    if (!n) return '—';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + ' М';
    if (n >= 1_000)     return (n / 1_000).toFixed(0) + ' К';
    return n.toFixed(0);
  }

  /** @param {string} msg */
  function handleError(msg) {
    errorMessage = msg;
    stepState = 'error';
    setStepError(5, msg);
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  async function generateReport() {
    const pid = get(activeProjectId);
    if (!pid || !hasData) return;

    stepState = 'generating-report';
    errorMessage = null;

    try {
      const result = /** @type {any} */ (await invoke('econ_generate_report', {
        projectId:    pid,
        modelData:    get(modelData),
        decomposeData: get(decomposeData),
        optimizeData:  get(optimizeData),
      }));

      if (result.status === 'ok') {
        reportPath = result.path ?? null;
        executiveSummary = result.summary ?? null;
        stepState = 'done';
      } else {
        handleError(result.message ?? 'Ошибка генерации отчёта');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    }
  }

  async function exportXlsx() {
    const pid = get(activeProjectId);
    if (!pid || !hasData) return;

    stepState = 'generating-xlsx';
    errorMessage = null;

    try {
      const result = /** @type {any} */ (await invoke('econ_export_xlsx', {
        projectId:    pid,
        modelData:    get(modelData),
        decomposeData: get(decomposeData),
        optimizeData:  get(optimizeData),
      }));

      if (result.status === 'ok') {
        xlsxPath = result.path ?? null;
        stepState = 'done';
      } else {
        handleError(result.message ?? 'Ошибка XLSX экспорта');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    }
  }

  async function exportPptx() {
    const pid = get(activeProjectId);
    if (!pid || !hasData) return;

    stepState = 'generating-xlsx'; // reuse spinner state
    errorMessage = null;

    try {
      const result = /** @type {any} */ (await invoke('econ_export_pptx', {
        projectId:     pid,
        modelData:     get(modelData),
        decomposeData: get(decomposeData),
        optimizeData:  get(optimizeData),
      }));

      if (result.status === 'ok' || result.status === 'partial') {
        pptxPath = result.path ?? null;
        stepState = 'done';
        if (result.status === 'partial' && Array.isArray(result.failed_phases)) {
          console.warn('PPTX partial: failed phases =', result.failed_phases);
        }
      } else {
        handleError(result.message ?? 'Ошибка PPTX');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    }
  }

  async function openFolder() {
    const pid = get(activeProjectId);
    if (!pid) return;
    try {
      await invoke('econ_open_exports', { projectId: pid });
    } catch (/** @type {any} */ e) {
      console.error('Open folder error:', e);
    }
  }

  function finishAnalysis() {
    completeStep(5);
    triggerCompletion();
  }
</script>

<div class="report-step">

  <!-- Error banner -->
  {#if stepState === 'error' && errorMessage}
    <div class="error-banner">
      <span class="error-icon">⚠</span>
      <span class="error-text">{errorMessage}</span>
      <button class="btn-retry" onclick={() => { stepState = 'idle'; errorMessage = null; }}>
        Попробовать снова
      </button>
    </div>
  {/if}

  <!-- Summary cards -->
  {#if hasData}
    <div class="summary-cards">
      <div class="card-metric">
        <div class="metric-label">MQS Score</div>
        <div class="metric-value" class:good={mqs != null && mqs >= 60} class:warn={mqs != null && mqs < 60}>
          {fmt(mqs)}
        </div>
        <div class="metric-sub">{mqsLabel}</div>
      </div>

      <div class="card-metric">
        <div class="metric-label">R²</div>
        <div class="metric-value" class:good={rSq != null && rSq >= 0.7} class:warn={rSq != null && rSq < 0.7}>
          {fmt(rSq, 3)}
        </div>
        <div class="metric-sub">объяснённая дисперсия</div>
      </div>

      <div class="card-metric">
        <div class="metric-label">MAPE</div>
        <div class="metric-value" class:good={mape != null && mape < 10} class:warn={mape != null && mape >= 20}>
          {mape != null ? fmt(mape, 1) + '%' : '—'}
        </div>
        <div class="metric-sub">средняя ошибка прогноза</div>
      </div>

      <div class="card-metric">
        <div class="metric-label">Прирост от оптимизации</div>
        <div
          class="metric-value lift"
          class:positive={lift != null && lift > 0}
          class:negative={lift != null && lift < 0}
        >
          {lift != null ? (lift >= 0 ? '+' : '') + fmt(lift) + '%' : '—'}
        </div>
        <div class="metric-sub">при перераспределении</div>
      </div>

      <div class="card-metric">
        <div class="metric-label">Оптим. бюджет</div>
        <div class="metric-value">{fmtBudget(budget)}</div>
        <div class="metric-sub">руб.</div>
      </div>
    </div>
  {:else}
    <div class="no-data-banner">
      Данные предыдущих шагов недоступны — пройдите шаги 1–4.
    </div>
  {/if}

  <!-- Generate card -->
  <div class="card generate-card">
    <div class="card-title">Экспорт результатов</div>

    {#if stepState === 'idle' || stepState === 'error' || stepState === 'done'}
      {#if stepState === 'done'}
        <div class="success-section">
          <div class="success-header">
            <span class="success-icon">✅</span>
            <span class="success-title">Файл сохранён</span>
          </div>
          {#if xlsxPath}
            <div class="file-row">
              <span class="file-icon">📊</span>
              <span class="file-path">{xlsxPath}</span>
            </div>
          {/if}
          {#if pptxPath}
            <div class="file-row">
              <span class="file-icon">📽</span>
              <span class="file-path">{pptxPath}</span>
            </div>
          {/if}
          <div class="more-exports">
            <button class="btn-folder" onclick={openFolder}>📁 Открыть папку</button>
          </div>
          {#if executiveSummary}
            <div class="summary-preview">
              <div class="preview-title">Executive Summary</div>
              <pre class="preview-text">{executiveSummary}</pre>
            </div>
          {/if}
        </div>
      {/if}

      <div class="export-buttons">
        <button
          class="btn-export pptx"
          onclick={exportPptx}
          disabled={!hasData}
        >
          <span class="btn-icon">📽</span>
          {pptxPath ? 'PPTX — пересоздать' : 'Презентация (PPTX)'}
        </button>
        <button
          class="btn-export secondary"
          onclick={exportXlsx}
          disabled={!hasData}
        >
          <span class="btn-icon">📊</span>
          {xlsxPath ? 'XLSX — пересоздать' : 'Данные (XLSX)'}
        </button>
      </div>

      <div class="format-cards">
        <div class="format-card">
          <div class="format-card-header">
            <span class="format-icon">📽</span>
            <div class="format-title">PPTX — для презентации</div>
          </div>
          <p class="format-desc">
            Executive summary, спецификация модели (Bayesian MMM, Adstock, Hill), декомпозиция продаж,<br>
            ROI по каналам, оптимальное распределение, прогноз. С графиками и рекомендациями.
          </p>
          <details class="format-email">
            <summary>Сопроводительный текст для письма</summary>
            <p>Коллеги, прикладываю презентацию с результатами Marketing Mix Modeling.</p>
            {#if modelSummary}
              <p><b>Модель.</b> {modelSummary}</p>
            {/if}
            {#if resultsSummary}
              <p><b>Результаты.</b> {resultsSummary}</p>
            {/if}
            {#if limitationsSummary.length > 0}
              <p><b>Ограничения и оговорки.</b></p>
              <ul>
                {#each limitationsSummary as item}
                  <li>{item}</li>
                {/each}
              </ul>
            {/if}
            <p><b>Структура презентации:</b></p>
            <ul>
              <li>Executive summary — MQS, R², MAPE, прирост от оптимизации</li>
              <li>Спецификация модели — Bayesian MMM с Adstock + Hill saturation, MCMC-сэмплер, priors</li>
              <li>Декомпозиция продаж — вклад baseline vs медиа по каналам</li>
              <li>ROI-анализ — Share of Spend vs Share of Effect, Gap, Efficiency</li>
              <li>Оптимальное распределение бюджета с ожидаемым lift</li>
            </ul>
            <p>Готов обсудить детали и план пилота.</p>
          </details>
        </div>

        <div class="format-card">
          <div class="format-card-header">
            <span class="format-icon">📊</span>
            <div class="format-title">XLSX — для самостоятельной работы с данными</div>
          </div>
          <p class="format-desc">
            Executive Summary, спецификация модели, декомпозиция, ROI каналов, Spend vs Effect,<br>
            оптимизация, сырые time-series данные для построения собственных графиков, глоссарий.
          </p>
          <details class="format-email">
            <summary>Сопроводительный текст для письма</summary>
            <p>Во вложении — полные данные MMM-анализа для самостоятельной работы.</p>
            {#if modelSummary}
              <p><b>Модель.</b> {modelSummary}</p>
            {/if}
            {#if resultsSummary}
              <p><b>Результаты.</b> {resultsSummary}</p>
            {/if}
            {#if limitationsSummary.length > 0}
              <p><b>Ограничения и оговорки.</b></p>
              <ul>
                {#each limitationsSummary as item}
                  <li>{item}</li>
                {/each}
              </ul>
            {/if}
            <p><b>Структура файла:</b></p>
            <ul>
              <li><b>Executive Summary</b> — ключевые метрики качества модели</li>
              <li><b>Спецификация</b> — параметры модели (alpha, gamma, beta по каналам), priors, методология Bayesian MMM</li>
              <li><b>Декомпозиция</b> — вклад baseline и каждого канала в продажи</li>
              <li><b>ROI каналов</b> — ROI, Gap, Efficiency по каналам</li>
              <li><b>Spend vs Effect</b> — share of spend vs share of effect</li>
              <li><b>Оптимизация</b> — текущее vs оптимальное распределение</li>
              <li><b>Данные</b> — сырые time-series (KPI, baseline, вклад по каналам по периодам) — можно построить любые графики</li>
              <li><b>Глоссарий</b> — определения MMM-терминов</li>
            </ul>
            <p>Лист «Данные» особенно полезен: выделите нужные колонки → Вставка → Диаграмма.</p>
          </details>
        </div>
      </div>

    {:else if stepState === 'generating-report' || stepState === 'generating-xlsx'}
      <div class="generating-state">
        <div class="spinner"></div>
        <p>{stepState === 'generating-report' ? 'Генерирую отчёт…' : 'Создаю файл…'}</p>
      </div>
    {/if}
  </div>

  <!-- Complete step -->
  {#if stepState === 'done'}
    <div class="complete-row">
      <button class="btn-complete" onclick={finishAnalysis}>
        Завершить анализ ✓
      </button>
    </div>
  {/if}

</div>

<style>
  .report-step {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px;
    height: 100%;
    box-sizing: border-box;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.1) transparent;
  }

  /* ── Error banner ─────────────────────────────────────── */
  .error-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
    border-radius: 10px;
    flex-wrap: wrap;
  }
  .error-icon { font-size: 16px; flex-shrink: 0; }
  .error-text { flex: 1; font-size: 13px; color: #ef4444; }
  .btn-retry {
    padding: 6px 14px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 6px;
    color: white;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }

  /* ── Summary cards ────────────────────────────────────── */
  .summary-cards {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 8px;
  }
  @media (max-width: 1200px) {
    .summary-cards { grid-template-columns: repeat(3, 1fr); }
  }
  @media (max-width: 700px) {
    .summary-cards { grid-template-columns: repeat(2, 1fr); }
  }

  .card-metric {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 10px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .metric-label {
    font-size: 10px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: var(--text-secondary, #94a3b8);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .metric-value {
    font-size: 20px;
    font-weight: 700;
    font-family: monospace;
    color: var(--text-primary, #e2e8f0);
    line-height: 1.15;
  }
  .metric-value.good   { color: #22c55e; }
  .metric-value.warn   { color: #f59e0b; }
  .metric-value.lift.positive { color: #22c55e; }
  .metric-value.lift.negative { color: #ef4444; }
  .metric-sub {
    font-size: 10px;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .no-data-banner {
    padding: 14px 16px;
    background: color-mix(in srgb, var(--warning) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning) 25%, transparent);
    border-radius: 10px;
    font-size: 13px;
    color: #f59e0b;
    text-align: center;
  }

  /* ── Generate card ────────────────────────────────────── */
  .card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 20px;
  }
  .card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    margin-bottom: 16px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .generate-card { flex: 1; min-height: 0; }

  .export-buttons {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }
  .btn-export {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 20px;
    border: none;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
    white-space: nowrap;
  }
  .btn-export.primary {
    background: var(--accent-primary, #3b82f6);
    color: white;
  }
  .btn-export.secondary {
    background: color-mix(in srgb, var(--success) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
    color: #22c55e;
  }
  .btn-export.pptx {
    background: rgba(139,92,246,0.15);
    border: 1px solid rgba(139,92,246,0.3);
    color: #a78bfa;
  }
  .btn-export:hover:not(:disabled) { opacity: 0.85; }
  .btn-export:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-icon { font-size: 16px; }

  .export-hint {
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.6;
    margin: 0;
  }

  .format-cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-top: 14px;
  }
  @media (max-width: 900px) {
    .format-cards { grid-template-columns: 1fr; }
  }

  .format-card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 10px;
    padding: 14px 16px;
  }
  .format-card-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }
  .format-icon {
    font-size: 18px;
  }
  .format-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }
  .format-desc {
    font-size: 12.5px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.55;
    margin: 0 0 10px;
  }
  .format-email {
    margin-top: 8px;
    font-size: 12px;
  }
  .format-email summary {
    cursor: pointer;
    color: var(--accent-primary, #3b82f6);
    font-weight: 500;
    padding: 4px 0;
    list-style: none;
  }
  .format-email summary::before {
    content: '▸ ';
    font-size: 10px;
  }
  .format-email[open] summary::before {
    content: '▾ ';
  }
  .format-email summary:hover {
    text-decoration: underline;
  }
  .format-email p, .format-email ul {
    color: var(--text-secondary, #94a3b8);
    line-height: 1.55;
    margin: 8px 0;
  }
  .format-email ul {
    padding-left: 20px;
  }
  .format-email li {
    margin: 3px 0;
  }
  .format-email b {
    color: var(--text-primary, #e2e8f0);
  }

  /* ── Generating ───────────────────────────────────────── */
  .generating-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    padding: 48px 20px;
  }
  .generating-state p {
    font-size: 14px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }

  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner {
    width: 32px;
    height: 32px;
    border: 3px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-top-color: var(--accent-primary, #3b82f6);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  /* ── Success section ──────────────────────────────────── */
  .success-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .success-header {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .success-icon { font-size: 18px; }
  .success-title {
    font-size: 15px;
    font-weight: 600;
    color: #22c55e;
  }

  .file-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
  }
  .file-icon { font-size: 14px; flex-shrink: 0; }
  .file-path {
    font-size: 11px;
    font-family: monospace;
    color: var(--text-secondary, #94a3b8);
    word-break: break-all;
  }

  .more-exports {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .btn-more, .btn-folder {
    padding: 7px 14px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
  }
  .btn-more:hover, .btn-folder:hover {
    border-color: rgba(255,255,255,0.22);
    color: var(--text-primary, #e2e8f0);
  }

  /* ── Executive Summary preview ────────────────────────── */
  .summary-preview {
    background: color-mix(in srgb, var(--accent-primary) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 15%, transparent);
    border-radius: 10px;
    padding: 14px;
    max-height: 220px;
    overflow-y: auto;
    scrollbar-width: thin;
  }
  .preview-title {
    font-size: 10px;
    font-weight: 700;
    color: color-mix(in srgb, var(--accent-primary) 80%, transparent);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 10px;
  }
  .preview-text {
    font-size: 12px;
    font-family: inherit;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.7;
    white-space: pre-wrap;
    margin: 0;
  }

  /* ── Complete row ─────────────────────────────────────── */
  .complete-row {
    display: flex;
    justify-content: flex-end;
  }
  .btn-complete {
    padding: 12px 28px;
    background: linear-gradient(135deg, #22c55e, #16a34a);
    border: none;
    border-radius: 10px;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-complete:hover { opacity: 0.9; }
</style>
