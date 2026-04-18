<script>
  /**
   * ValidateStep — Step 1 of the pipeline.
   * Runs econ_validate on the imported file, then shows:
   *   - TrafficLight for validation status / issues
   *   - ColumnMapper for role assignment (drag-drop)
   *   - CorrelationHeatmap for multicollinearity analysis
   *
   * Calls completeStep(1) when status is 'ok' or 'warning'.
   * Reads importData store to get the file path.
   *
   * @component ValidateStep
   */
  import { invoke } from '@tauri-apps/api/core';
  import ColumnMapper from '$lib/components/pipeline/ColumnMapper.svelte';
  import TrafficLight from '$lib/components/pipeline/TrafficLight.svelte';
  import CorrelationHeatmap from '$lib/components/pipeline/CorrelationHeatmap.svelte';
  import {
    importData, validateData, completeStep, setStepError,
    activeProjectId, expertMode,
  } from '$lib/project-state.js';
  import ExpertValidatePanel from '$lib/components/pipeline/ExpertValidatePanel.svelte';
  import { get } from 'svelte/store';

  // ── State ──────────────────────────────────────────
  let loading = $state(false);
  let errorMsg = $state('');

  /** @type {Set<string>} Dismissed/applied warning keys */
  let appliedFixes = $state(new Set());

  // Reactively read from store — updates when InsightsPanel modifies column roles
  const result = $derived($validateData?.result ?? null);

  // ── Reactive store reads (Svelte 5 auto-subscribe) ─
  let hasFile = $derived(!!$importData?.file);

  // Recalculate stats based on current column roles (after insight actions)
  const activeMediaCount = $derived(result?.columns?.filter(/** @param {any} c */ c => c.role === 'media').length ?? 0);
  const excludedCount = $derived(result?.columns?.filter(/** @param {any} c */ c => c.role === 'unused').length ?? 0);

  // Columns currently excluded (role=unused) — for filtering warnings
  const excludedColumns = $derived(
    new Set((result?.columns ?? []).filter(/** @param {any} c */ c => c.role === 'unused').map(/** @param {any} c */ c => c.name))
  );

  // Warnings filtered: hide warnings for excluded columns
  const activeWarnings = $derived(
    (result?.warnings ?? []).filter(/** @param {any} w */ w => {
      if (!w.column) return true; // general warning, always show
      return !excludedColumns.has(w.column);
    })
  );

  let statusLabel = $derived.by(() => {
    if (!result) return '';
    if (activeWarnings.length === 0 && result.status !== 'error') return 'Валидация пройдена';
    if (result.status === 'error') return 'Обнаружены критические проблемы';
    return `Готово с предупреждениями (${activeWarnings.length})`;
  });

  // ── Validate ───────────────────────────────────────
  async function runValidate() {
    const imp = get(importData);
    if (!imp.file) {
      errorMsg = 'Сначала загрузите файл на шаге Импорт';
      return;
    }

    loading = true;
    errorMsg = '';

    try {
      const projectId = get(activeProjectId);

      /** @type {any} */
      const res = await invoke('econ_validate', {
        filePath: imp.file,
        projectDir: projectId || null,
      });

      // Hard error (file not found, parse failure)
      if (res.status === 'error' && !res.columns) {
        errorMsg = res.message ?? 'Ошибка валидации';
        setStepError(1, errorMsg);
        return;
      }

      // Save to store — result is $derived from store, updates reactively
      validateData.set({
        result: res,
        correlationMatrix: res.full_correlation_matrix ?? null,
        columnHistograms: null,
      });

      // Auto-complete if no critical issues
      if (res.status !== 'error') {
        completeStep(1);
      }
    } catch (e) {
      errorMsg = `Ошибка: ${e}`;
      setStepError(1, String(e));
    } finally {
      loading = false;
    }
  }

  /** @param {any} mapping */
  function onMappingChange(mapping) {
    const projectId = get(activeProjectId);
    if (!projectId || !mapping) return;
    invoke('project_update', {
      projectId,
      updates: {
        kpi_column: mapping.kpi?.[0] ?? null,
        media_columns: mapping.media ?? [],
        control_columns: mapping.control ?? [],
      },
    }).catch(() => { /* best-effort persist */ });
  }
</script>

<div class="validate-step">

  <!-- Action bar -->
  <div class="action-bar">
    {#if !hasFile}
      <p class="no-file-hint">Сначала загрузите файл на шаге «Импорт»</p>
    {:else}
      <button
        class="run-btn"
        disabled={loading}
        onclick={runValidate}
      >
        {#if loading}
          <span class="btn-spinner"></span>
          Анализирую…
        {:else if result}
          🔄 Перезапустить валидацию
        {:else}
          ▶ Запустить валидацию
        {/if}
      </button>

      {#if result}
        <span class="status-pill status-{result.status}">{statusLabel}</span>
      {/if}
    {/if}
  </div>

  <!-- Error -->
  {#if errorMsg}
    <div class="error-banner">⚠️ {errorMsg}</div>
  {/if}

  <!-- Results -->
  {#if result}
    <div class="results-grid">

      <!-- TrafficLight -->
      <section class="section">
        <h4 class="section-title">Результат валидации</h4>
        <TrafficLight
          status={activeWarnings.length === 0 && result.status !== 'error' ? 'ok' : result.status}
          verdict={result.verdict}
          issues={result.issues ?? []}
          warnings={activeWarnings}
          file={result.file ?? null}
          detected={result.detected ?? null}
          columns={result.columns?.filter(/** @param {any} c */ c => c.role !== 'unused') ?? []}
        />
        {#if excludedCount > 0}
          <div class="excluded-badge">{excludedCount} столбц{excludedCount > 4 ? 'ов' : excludedCount > 1 ? 'а' : ''} исключен{excludedCount > 1 ? 'о' : ''} по рекомендациям</div>
        {/if}
      </section>

      <!-- Auto-fix suggestions -->
      {#if activeWarnings.length > 0}
        <section class="section section-wide">
          <h4 class="section-title">Рекомендации ({activeWarnings.length})</h4>
          <div class="fix-list">
            {#each activeWarnings as warn}
              {#if !appliedFixes.has(warn.column + warn.type)}
                <div class="fix-item fix-{warn.severity}">
                  <span class="fix-text">{warn.message}</span>
                  {#if warn.action === 'exclude'}
                    <button class="fix-btn" onclick={() => {
                      appliedFixes = new Set([...appliedFixes, warn.column + warn.type]);
                    }}>Понятно</button>
                  {:else if warn.action === 'merge'}
                    <button class="fix-btn" onclick={() => {
                      appliedFixes = new Set([...appliedFixes, warn.column + warn.type]);
                    }}>Понятно</button>
                  {:else}
                    <button class="fix-btn" onclick={() => {
                      appliedFixes = new Set([...appliedFixes, (warn.column ?? '') + warn.type]);
                    }}>Принять</button>
                  {/if}
                </div>
              {/if}
            {/each}
          </div>
        </section>
      {/if}

      <!-- ColumnMapper -->
      <section class="section">
        <h4 class="section-title">Назначение столбцов</h4>
        <p class="section-hint">
          Роли определены автоматически. Перетащите для коррекции.
          Двойной клик по назначенному — убрать.
        </p>
        <ColumnMapper
          columns={result.columns ?? []}
          detected={result.detected ?? {}}
          onmappingchange={onMappingChange}
        />
      </section>

      <!-- Correlation heatmap -->
      {#if result.full_correlation_matrix?.labels?.length >= 2}
        <section class="section section-wide">
          <CorrelationHeatmap
            correlationMatrix={result.full_correlation_matrix}
            highCorrelations={result.high_correlations ?? []}
          />
        </section>
      {/if}

    </div>

  {:else if !loading && hasFile}
    <!-- Idle -->
    <div class="idle-state">
      <div class="idle-icon">🔍</div>
      <p class="idle-text">Нажмите «Запустить валидацию» для анализа данных</p>
      <p class="idle-hint">
        Автоматическое определение KPI, медиа-каналов и дат.
        Проверка качества, мультиколлинеарности, соотношения данных.
      </p>
    </div>
  {/if}

  {#if $expertMode}
    <ExpertValidatePanel />
  {/if}

</div>

<style>
  .validate-step {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 24px;
    height: 100%;
    box-sizing: border-box;
    overflow-y: auto;
  }

  /* ── Action bar ── */
  .action-bar {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
    flex-shrink: 0;
  }

  .no-file-hint {
    font-size: 13px;
    color: rgba(148, 163, 184, 0.5);
    margin: 0;
    font-style: italic;
  }

  .run-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 20px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 10px;
    color: var(--text-on-accent, #fff);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s, transform 0.1s;
  }

  .run-btn:hover:not(:disabled) {
    background: var(--accent-hover, #2563eb);
    transform: translateY(-1px);
  }

  .run-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .btn-spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(147, 197, 253, 0.2);
    border-top-color: #93c5fd;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    flex-shrink: 0;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .status-pill {
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 20px;
  }

  .excluded-badge {
    margin-top: 8px;
    font-size: 11px;
    color: #4ade80;
    padding: 4px 10px;
    background: rgba(34,197,94,0.08);
    border: 1px solid rgba(34,197,94,0.2);
    border-radius: 6px;
    display: inline-block;
  }

  .status-ok      { background: rgba(34,197,94,0.15);  color: var(--text-primary); border: 1px solid rgba(34,197,94,0.35); }
  .status-warning { background: rgba(245,158,11,0.15); color: var(--text-primary); border: 1px solid rgba(245,158,11,0.35); }
  .status-error   { background: rgba(239,68,68,0.15);  color: var(--text-primary); border: 1px solid rgba(239,68,68,0.35); }

  /* ── Error ── */
  .error-banner {
    padding: 10px 16px;
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 10px;
    font-size: 13px;
    color: #fca5a5;
    flex-shrink: 0;
  }

  /* ── Results grid ── */
  .results-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }

  .section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .section-wide {
    grid-column: 1 / -1;
  }

  .section-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }

  .section-hint {
    font-size: 11px;
    color: rgba(148, 163, 184, 0.5);
    margin: 0;
    font-style: italic;
    line-height: 1.5;
  }

  /* ── Idle ── */
  .fix-list { display: flex; flex-direction: column; gap: 6px; }
  .fix-item {
    display: flex; align-items: center; gap: 10px; padding: 8px 12px;
    border-radius: 6px;
    background: rgba(245, 158, 11, 0.06);
    border: 1px solid rgba(245, 158, 11, 0.2);
    border-left: 3px solid #f59e0b;
  }
  .fix-item.fix-critical { border-left-color: #ef4444; background: rgba(239,68,68,0.06); border-color: rgba(239,68,68,0.2); }
  .fix-text { flex: 1; font-size: 12px; color: var(--text-primary, #e2e8f0); line-height: 1.4; }
  .fix-btn {
    padding: 4px 12px; border-radius: 5px; border: 1px solid rgba(255,255,255,0.12);
    background: rgba(255,255,255,0.05); color: var(--text-secondary, #94a3b8);
    font-size: 11px; cursor: pointer; white-space: nowrap; transition: all 0.15s;
  }
  .fix-btn:hover { background: rgba(255,255,255,0.1); color: var(--text-primary, #e2e8f0); }

  .idle-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 48px 32px;
    text-align: center;
    flex: 1;
  }

  .idle-icon { font-size: 48px; line-height: 1; filter: grayscale(0.4); }

  .idle-text {
    font-size: 14px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }

  .idle-hint {
    font-size: 12px;
    color: rgba(148, 163, 184, 0.5);
    margin: 0;
    max-width: 380px;
    line-height: 1.6;
  }
</style>
