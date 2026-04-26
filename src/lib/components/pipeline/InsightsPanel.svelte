<script>
  /**
   * InsightsPanel — Rule-based insights sidebar for the pipeline.
   * Tier 1: offline insights from insights-rules.js (always works).
   * Tier 2: Claude AI (online, optional) — Phase 10.
   * C4: width clamp(240px, 22%, 360px), auto-collapse below 1100px.
   */
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import { get } from 'svelte/store';
  import {
    pipelineCurrentStep, activeProjectId,
    importData, validateData, modelData, decomposeData, optimizeData, optimizeLiveState,
    analysisObjective, completeStep, setStepError,
  } from '$lib/project-state.js';
  import { recomputeResultAfterObjective } from '$lib/objective-engine.js';
  import { setColumnRolesBulk, buildProjectUpdates } from '$lib/column-roles.js';

  /** Persist column-role state к project.json (best-effort, non-blocking).
   *  L1 (math-fix v1.4 Section C, 2026-04-29): unified persistence — same call
   *  used by InsightsPanel.applyAction, ValidateStep.excludeColumnByName,
   *  ValidateStep.onMappingChange. Adds explicit excluded_columns list для
   *  cross-session restore.
   *  @param {any[]} columns */
  function persistColumnRoles(columns) {
    const projectId = get(activeProjectId);
    if (!projectId || !columns) return;
    const updates = buildProjectUpdates(columns);
    invoke('project_update', { projectId, updates }).catch(() => { /* best-effort */ });
  }
  import {
    importInsights, validateInsights, modelInsights, modelPreTrainingInsights, decomposeInsights, optimizeInsights, reportInsights,
  } from '$lib/insights-rules.js';

  /** @type {{ collapsed?: boolean, onToggle?: () => void }} */
  let { collapsed = false, onToggle } = $props();

  /**
   * Snapshot of what was done — enables undo.
   * Keyed by insight index; stores roles prior to apply + merge metadata.
   * @type {Map<number, { previousRoles: Record<string, string>, mergedName?: string }>}
   */
  let appliedActions = $state(new Map());

  /** Apply an insight action: modify column roles in validateData
   * @param {import('$lib/insights-rules.js').InsightAction} action
   * @param {number} idx
   */
  function applyAction(action, idx) {
    const val = $validateData;
    if (!val?.result?.columns) return;

    // L1 (math-fix v1.4 Section C, 2026-04-29): use shared setColumnRolesBulk
    // helper для consistent vocabulary с ColumnMapper drag-drop and
    // ValidateStep.excludeColumnByName. Single source of truth → no drift
    // между mutator paths (vocabulary, persistence, undo capture).
    /** @type {Record<string, string>} */
    const previousRoles = {};
    /** @type {string | undefined} */
    let mergedName;

    // Capture previous roles for undo BEFORE mutation
    const captureNames = action.type === 'keep_only' ? (action.exclude ?? []) : (action.columns ?? []);
    for (const col of val.result.columns) {
      if (captureNames.includes(col.name)) {
        previousRoles[col.name] = col.role || 'unknown';
      }
    }

    let nextColumns = val.result.columns;

    if (action.type === 'exclude') {
      nextColumns = setColumnRolesBulk(nextColumns, action.columns, 'unused');
    } else if (action.type === 'keep_only') {
      nextColumns = setColumnRolesBulk(nextColumns, action.exclude ?? [], 'unused');
    } else if (action.type === 'set_role') {
      nextColumns = setColumnRolesBulk(nextColumns, action.columns, 'kpi');
    } else if (action.type === 'merge') {
      // Audit fix (2026-04-29): detect name collision when customer creates
      // multiple merge actions с одинаковым default name «Объединённый канал».
      // Pre-fix: silent duplicate column entries → downstream lookups by name
      // hit first match, second merge effectively orphaned. Post-fix: auto-suffix
      // (Объединённый канал, Объединённый канал 2, Объединённый канал 3, ...).
      const baseName = action.mergedName || 'Объединённый канал';
      let candidateName = baseName;
      let suffix = 2;
      const existingNames = new Set(nextColumns.map(/** @param {any} c */ (c) => c.name));
      while (existingNames.has(candidateName)) {
        candidateName = `${baseName} ${suffix}`;
        suffix += 1;
      }
      mergedName = candidateName;
      const mergedCols = nextColumns.filter(/** @param {any} c */ (c) => action.columns.includes(c.name));
      const totalMean = mergedCols.reduce(/** @param {number} s @param {any} c */ (s, c) => s + (c.stats?.mean ?? 0), 0);
      const minZeros = Math.min(...mergedCols.map(/** @param {any} c */ (c) => c.stats?.zeros_pct ?? 100));
      nextColumns = setColumnRolesBulk(nextColumns, action.columns, 'unused');
      nextColumns = [...nextColumns, {
        name: mergedName,
        role: 'media',
        dtype: 'float64',
        confidence: 0.9,
        merged_from: [...action.columns],
        stats: { mean: totalMean, zeros_pct: minZeros, missing_pct: 0, min: 0, max: 0 },
      }];
    }

    const updated = { ...val, result: { ...val.result, columns: nextColumns } };
    recomputeResultAfterObjective(updated.result);
    syncStepLockAfterValidate(updated.result);
    validateData.set(updated);
    persistColumnRoles(updated.result.columns);

    const nextMap = new Map(appliedActions);
    nextMap.set(idx, { previousRoles, mergedName });
    appliedActions = nextMap;
  }

  /**
   * Undo an applied action — restore roles, remove merged column.
   * @param {number} idx
   */
  function revertAction(idx) {
    const snapshot = appliedActions.get(idx);
    if (!snapshot) return;
    const val = $validateData;
    if (!val?.result?.columns) return;

    const updated = { ...val, result: { ...val.result, columns: val.result.columns.map(/** @param {any} c */ c => ({ ...c })) } };

    // Restore previous roles
    for (const col of updated.result.columns) {
      if (col.name in snapshot.previousRoles) {
        col.role = snapshot.previousRoles[col.name];
      }
    }

    // Remove virtual merged column if this was a merge action
    if (snapshot.mergedName) {
      updated.result.columns = updated.result.columns.filter(/** @param {any} c */ c => c.name !== snapshot.mergedName);
    }

    recomputeResultAfterObjective(updated.result);
    syncStepLockAfterValidate(updated.result);
    validateData.set(updated);
    persistColumnRoles(updated.result.columns);
    const nextMap = new Map(appliedActions);
    nextMap.delete(idx);
    appliedActions = nextMap;
  }

  /**
   * Sync pipeline step-lock state with current validation result.
   * Called after any action that recomputes status (apply/revert).
   * If status becomes ok/warning → step 1 complete, step 2 ready (unlocks "Далее").
   * If status becomes error → step 1 error, step 2 locked.
   * @param {any} result
   */
  function syncStepLockAfterValidate(result) {
    if (!result) return;
    // Only sync if we're actually ON the validation step
    const step = $pipelineCurrentStep;
    if (step !== 1) return;
    if (result.status === 'error') {
      setStepError(1, 'Критические проблемы с данными');
    } else {
      completeStep(1);
    }
  }

  // Severity icons and colors
  const SEVERITY = /** @type {const} */ ({
    info:    { icon: 'i',  cls: 'sev-info' },
    success: { icon: '\u2713', cls: 'sev-success' },
    warning: { icon: '!',  cls: 'sev-warning' },
    error:   { icon: '\u2717', cls: 'sev-error' },
  });

  /** @type {import('$lib/insights-rules.js').Insight[]} */
  const insights = $derived.by(() => {
    const step = $pipelineCurrentStep;
    const imp = $importData;
    const val = $validateData;
    const mod = $modelData;
    const dec = $decomposeData;
    const opt = $optimizeData;
    const live = $optimizeLiveState;
    const objective = $analysisObjective; // ensure reactive subscription

    switch (step) {
      case 0: {
        if (!imp?.file) return [];
        const cols = imp.columns ?? [];
        const totalRows = imp.shape?.rows ?? imp.rows?.length ?? 0;
        const zeros = /** @type {Record<string, number>} */ ({});
        for (const c of cols) {
          if (c.stats?.zeros_pct > 0) zeros[c.name] = c.stats.zeros_pct;
        }
        return importInsights({
          rows: totalRows,
          cols: imp.shape?.cols ?? cols.length,
          columns: cols,
          zeros,
          fileName: imp.fileName ?? '',
        });
      }
      case 1: return validateInsights(val?.result, objective);
      case 2: {
        // If training hasn't produced diagnostics yet → educational/context insights
        if (!mod?.diagnostics) return modelPreTrainingInsights(val?.result);
        return modelInsights(mod);
      }
      case 3: return decomposeInsights(dec);
      case 4: return optimizeInsights(opt, {
        dec, mod,
        channelBudgets: live.channelBudgets,
        channelMinPct: live.channelMinPct,
        channelMaxPct: live.channelMaxPct,
        globalMinPct: live.globalMinPct,
        globalMaxPct: live.globalMaxPct,
      });
      case 5: return reportInsights({ mod, dec, opt });
      default: return [];
    }
  });

  /** @type {number | null} */
  let expandedTip = $state(null);

  // ── Drag-resize ──
  let panelWidth = $state(300);
  let isResizing = $state(false);

  /** @param {MouseEvent} e */
  function startResize(e) {
    if (collapsed) return;
    e.preventDefault();
    isResizing = true;
    const startX = e.clientX;
    const startW = panelWidth;

    /** @param {MouseEvent} moveEvt */
    function onMove(moveEvt) {
      const delta = startX - moveEvt.clientX;
      panelWidth = Math.max(200, Math.min(600, startW + delta));
    }
    function onUp() {
      isResizing = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }
</script>

<aside
  class="insights-panel"
  class:collapsed
  class:resizing={isResizing}
  style={collapsed ? '' : `width:${panelWidth}px`}
  aria-label="Инсайты"
>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="resize-handle" onmousedown={startResize}></div>
  <div class="panel-header">
    {#if !collapsed}
      <span class="panel-title">Инсайты</span>
      <span class="insight-count">{insights.length}</span>
    {/if}
    <button
      class="collapse-btn"
      onclick={onToggle}
      title={collapsed ? 'Развернуть' : 'Свернуть панель'}
      aria-label={collapsed ? 'Развернуть инсайты' : 'Свернуть инсайты'}
    >
      {collapsed ? '\u25C0' : '\u25B6'}
    </button>
  </div>

  {#if !collapsed}
    <div class="panel-body">
      {#if insights.length === 0}
        <p class="empty-hint">Загрузите данные для получения рекомендаций.</p>
      {:else}
        <ul class="insights-list" role="list">
          {#each insights as insight, i}
            <li class="insight-item {SEVERITY[insight.severity].cls}" role="listitem">
              <span class="sev-badge">{SEVERITY[insight.severity].icon}</span>
              <div class="insight-content">
                <span class="insight-text">{insight.text}</span>
                <div class="insight-actions-row">
                  {#if insight.tip}
                    <button
                      class="tip-toggle"
                      onclick={() => expandedTip = expandedTip === i ? null : i}
                    >
                      {expandedTip === i ? 'Скрыть' : 'Подробнее'}
                    </button>
                  {/if}
                  {#if insight.action && !appliedActions.has(i)}
                    <button
                      class="action-btn"
                      onclick={() => applyAction(insight.action, i)}
                    >
                      {insight.action.label || 'Применить'}
                    </button>
                  {/if}
                  {#if appliedActions.has(i)}
                    <button
                      class="revert-btn"
                      onclick={() => revertAction(i)}
                      title="Отменить применённое действие"
                    >
                      ✓ Применено · Отменить
                    </button>
                  {/if}
                </div>
                {#if expandedTip === i && insight.tip}
                  <p class="tip-text">{insight.tip}</p>
                {/if}
              </div>
            </li>
          {/each}
        </ul>
      {/if}

    </div>
  {/if}
</aside>

<style>
  .insights-panel {
    position: relative;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-left: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    overflow: hidden;
    flex-shrink: 0;
    transition: width 0.15s ease;
  }
  .insights-panel.resizing { transition: none; user-select: none; }
  .insights-panel.collapsed { width: 34px !important; min-width: 34px; }

  .resize-handle {
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 5px;
    cursor: col-resize;
    z-index: 20;
    background: transparent;
    transition: background 0.15s;
  }
  .resize-handle:hover,
  .resizing .resize-handle {
    background: var(--accent-primary, #3b82f6);
    opacity: 0.5;
  }
  .collapsed .resize-handle { display: none; }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 14px 12px;
    min-height: 52px;  /* match StepWrapper .step-header height (h2 + padding) */
    box-sizing: border-box;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    flex-shrink: 0;
    gap: 8px;
  }
  .panel-title {
    font-size: 11px; font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    text-transform: uppercase; letter-spacing: 0.06em;
    white-space: nowrap; flex: 1;
  }
  .insight-count {
    font-size: 10px; font-weight: 700;
    background: var(--accent-primary, #3b82f6);
    color: white; border-radius: 10px;
    padding: 1px 7px; min-width: 18px;
    text-align: center; flex-shrink: 0;
  }
  .collapse-btn {
    background: none; border: none;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer; font-size: 10px;
    padding: 3px 5px; border-radius: 4px;
    flex-shrink: 0; transition: background 0.15s; line-height: 1;
  }
  .collapse-btn:hover { background: rgba(255,255,255,0.07); }

  .panel-body {
    flex: 1; overflow-y: auto;
    display: flex; flex-direction: column;
    padding: 10px; gap: 8px; min-height: 0;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.08) transparent;
  }

  .empty-hint {
    font-size: 12px; color: var(--text-muted);
    text-align: center; padding: 20px 0; margin: 0;
  }

  .insights-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; flex: 1; }

  .insight-item {
    display: flex; gap: 8px; align-items: flex-start;
    font-size: 12px; line-height: 1.5;
    padding: 8px 10px; border-radius: var(--radius-sm, 6px);
    background: var(--bg-insight-base);
    border-left: 3px solid transparent;
    transition: background 0.2s;
  }
  .insight-item.sev-info    { border-left-color: var(--color-info, var(--accent-primary)); background: var(--bg-insight-info); }
  .insight-item.sev-success { border-left-color: var(--success); background: var(--bg-insight-success); }
  .insight-item.sev-warning { border-left-color: var(--warning); background: var(--bg-insight-warning); }
  .insight-item.sev-error   { border-left-color: var(--danger);  background: var(--bg-insight-error); }

  .sev-badge {
    width: 16px; height: 16px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 50%; font-size: 9px; font-weight: 700;
    flex-shrink: 0; margin-top: 1px;
  }
  .sev-info    .sev-badge { background: color-mix(in srgb, var(--color-info, var(--accent-primary)) 18%, transparent); color: var(--color-info, var(--accent-primary)); }
  .sev-success .sev-badge { background: color-mix(in srgb, var(--success) 18%, transparent);  color: var(--success); }
  .sev-warning .sev-badge { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
  .sev-error   .sev-badge { background: color-mix(in srgb, var(--danger) 18%, transparent);  color: var(--danger); }

  .insight-content { flex: 1; min-width: 0; }
  .insight-text { color: var(--text-secondary, #94a3b8); }

  .insight-actions-row {
    display: flex; gap: 8px; align-items: center; margin-top: 5px; flex-wrap: wrap;
  }

  .tip-toggle {
    background: none; border: none; padding: 0;
    font-size: 11px; color: var(--accent-primary, #3b82f6);
    cursor: pointer;
  }
  .tip-toggle:hover { text-decoration: underline; }

  .action-btn {
    padding: 5px 14px;
    background: var(--success);
    border: 1px solid var(--success);
    border-radius: var(--radius-chip, 5px);
    color: #fff;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    box-shadow: 0 1px 4px color-mix(in srgb, var(--success) 30%, transparent);
  }
  .action-btn:hover {
    background: color-mix(in srgb, var(--success) 85%, black);
    border-color: color-mix(in srgb, var(--success) 85%, black);
    transform: translateY(-1px);
    box-shadow: 0 3px 8px color-mix(in srgb, var(--success) 45%, transparent);
  }
  /* Error-severity actions get danger color for clarity */
  .sev-error .action-btn {
    background: var(--danger);
    border-color: var(--danger);
    box-shadow: 0 1px 4px color-mix(in srgb, var(--danger) 30%, transparent);
  }
  .sev-error .action-btn:hover {
    background: color-mix(in srgb, var(--danger) 85%, black);
    border-color: color-mix(in srgb, var(--danger) 85%, black);
    box-shadow: 0 3px 8px color-mix(in srgb, var(--danger) 45%, transparent);
  }

  .action-applied {
    font-size: 10px;
    color: var(--success);
    font-weight: 500;
  }

  .revert-btn {
    padding: 4px 10px;
    background: color-mix(in srgb, var(--success) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 36%, transparent);
    border-radius: var(--radius-chip, 5px);
    color: var(--success);
    font-size: 10px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }
  .revert-btn:hover {
    background: color-mix(in srgb, var(--warning) 18%, transparent);
    border-color: color-mix(in srgb, var(--warning) 55%, transparent);
    color: var(--warning);
  }

  .tip-text {
    font-size: 11px; color: var(--text-muted);
    line-height: 1.5; margin: 4px 0 0; padding: 6px 8px;
    background: rgba(255,255,255,0.02); border-radius: 4px;
    white-space: pre-line;
  }

</style>
