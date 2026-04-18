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
  const rSq      = $derived(/** @type {number|null} */ (mData?.diagnostics?.r_squared ?? null));
  const lift     = $derived(/** @type {number|null} */ (oData?.expected_lift_pct ?? null));
  const budget   = $derived(/** @type {number|null} */ (oData?.total_budget ?? null));

  const hasData  = $derived(!!mData?.diagnostics && !!dData && !!oData);

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

      if (result.status === 'ok') {
        pptxPath = result.path ?? null;
        stepState = 'done';
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

    {#if stepState === 'idle' || stepState === 'error'}
      <div class="export-buttons">
        <button
          class="btn-export primary"
          onclick={generateReport}
          disabled={!hasData}
        >
          <span class="btn-icon">📄</span>
          Сгенерировать отчёт (Markdown)
        </button>
        <button
          class="btn-export secondary"
          onclick={exportXlsx}
          disabled={!hasData}
        >
          <span class="btn-icon">📊</span>
          Данные (XLSX)
        </button>
        <button
          class="btn-export pptx"
          onclick={exportPptx}
          disabled={!hasData}
        >
          <span class="btn-icon">📽</span>
          Презентация (PPTX)
        </button>
      </div>
      <p class="export-hint">
        PPTX — 8 слайдов с графиками и рекомендациями.
        XLSX — 6 листов с формулами, графиками и глоссарием.
        Markdown — текстовый отчёт для email.
      </p>

    {:else if stepState === 'generating-report'}
      <div class="generating-state">
        <div class="spinner"></div>
        <p>Генерирую Markdown отчёт...</p>
      </div>

    {:else if stepState === 'generating-xlsx'}
      <div class="generating-state">
        <div class="spinner"></div>
        <p>Создаю XLSX...</p>
      </div>

    {:else if stepState === 'done'}
      <div class="success-section">
        <div class="success-header">
          <span class="success-icon">✅</span>
          <span class="success-title">Файл сохранён</span>
        </div>

        {#if reportPath}
          <div class="file-row">
            <span class="file-icon">📄</span>
            <span class="file-path">{reportPath}</span>
          </div>
        {/if}
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
          {#if !reportPath}
            <button class="btn-more" onclick={generateReport}>📄 Markdown</button>
          {/if}
          {#if !xlsxPath}
            <button class="btn-more" onclick={exportXlsx}>📊 XLSX</button>
          {/if}
          {#if !pptxPath}
            <button class="btn-more" onclick={exportPptx}>📽 PPTX</button>
          {/if}
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
    background: rgba(239,68,68,0.08);
    border: 1px solid rgba(239,68,68,0.25);
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
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
  }
  @media (max-width: 900px) {
    .summary-cards { grid-template-columns: repeat(2, 1fr); }
  }

  .card-metric {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .metric-label {
    font-size: 11px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary, #94a3b8);
  }
  .metric-value {
    font-size: 24px;
    font-weight: 700;
    font-family: monospace;
    color: var(--text-primary, #e2e8f0);
    line-height: 1.2;
  }
  .metric-value.good   { color: #22c55e; }
  .metric-value.warn   { color: #f59e0b; }
  .metric-value.lift.positive { color: #22c55e; }
  .metric-value.lift.negative { color: #ef4444; }
  .metric-sub {
    font-size: 11px;
    color: var(--text-muted);
  }

  .no-data-banner {
    padding: 14px 16px;
    background: rgba(245,158,11,0.08);
    border: 1px solid rgba(245,158,11,0.25);
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
    background: rgba(34,197,94,0.15);
    border: 1px solid rgba(34,197,94,0.3);
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
    border: 3px solid rgba(59,130,246,0.2);
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
    background: rgba(59,130,246,0.04);
    border: 1px solid rgba(59,130,246,0.15);
    border-radius: 10px;
    padding: 14px;
    max-height: 220px;
    overflow-y: auto;
    scrollbar-width: thin;
  }
  .preview-title {
    font-size: 10px;
    font-weight: 700;
    color: rgba(59,130,246,0.8);
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
