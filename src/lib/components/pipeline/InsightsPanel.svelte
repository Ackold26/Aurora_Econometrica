<script>
  /**
   * InsightsPanel — Rule-based insights sidebar for the pipeline.
   * Tier 1: offline insights from insights-rules.js (always works).
   * Tier 2: Claude AI (online, optional) — Phase 10.
   * C4: width clamp(240px, 22%, 360px), auto-collapse below 1100px.
   */
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import {
    pipelineCurrentStep,
    importData, validateData, modelData, decomposeData, optimizeData,
  } from '$lib/project-state.js';
  import {
    importInsights, validateInsights, modelInsights, decomposeInsights, optimizeInsights,
  } from '$lib/insights-rules.js';

  /** @type {{ collapsed?: boolean, onToggle?: () => void }} */
  let { collapsed = false, onToggle } = $props();

  /** @type {Set<number>} */
  let appliedActions = $state(new Set());

  /** Apply an insight action: modify column roles in validateData
   * @param {import('$lib/insights-rules.js').InsightAction} action
   * @param {number} idx
   */
  function applyAction(action, idx) {
    const val = $validateData;
    if (!val?.result?.columns) return;

    const updated = { ...val, result: { ...val.result, columns: val.result.columns.map(/** @param {any} c */ c => ({ ...c })) } };

    if (action.type === 'exclude') {
      for (const col of updated.result.columns) {
        if (action.columns.includes(col.name)) col.role = 'unused';
      }
    } else if (action.type === 'keep_only') {
      const toExclude = action.exclude ?? [];
      for (const col of updated.result.columns) {
        if (toExclude.includes(col.name)) col.role = 'unused';
      }
    } else if (action.type === 'set_role') {
      for (const col of updated.result.columns) {
        if (action.columns.includes(col.name)) col.role = 'kpi';
      }
    } else if (action.type === 'merge') {
      // Mark originals as unused, add virtual merged column
      const mergedName = action.mergedName || 'Объединённый канал';
      const mergedCols = updated.result.columns.filter(/** @param {any} c */ c => action.columns.includes(c.name));

      // Sum stats from merged columns
      const totalMean = mergedCols.reduce(/** @param {number} s @param {any} c */ (s, c) => s + (c.stats?.mean ?? 0), 0);
      const minZeros = Math.min(...mergedCols.map(/** @param {any} c */ c => c.stats?.zeros_pct ?? 100));

      for (const col of updated.result.columns) {
        if (action.columns.includes(col.name)) col.role = 'unused';
      }

      // Add virtual merged column
      updated.result.columns.push({
        name: mergedName,
        role: 'media',
        dtype: 'float64',
        confidence: 0.9,
        merged_from: [...action.columns],
        stats: { mean: totalMean, zeros_pct: minZeros, missing_pct: 0, min: 0, max: 0 },
      });
    }

    validateData.set(updated);
    appliedActions = new Set([...appliedActions, idx]);
  }

  /** @type {string} */
  let question = $state('');

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
      case 1: return validateInsights(val?.result);
      case 2: return modelInsights(mod);
      case 3: return decomposeInsights(dec);
      case 4: return optimizeInsights(opt);
      default: return [];
    }
  });

  /** @type {number | null} */
  let expandedTip = $state(null);

  // ── Tier 2: Claude AI (online, optional) ──
  let aiLoading = $state(false);
  /** @type {string | null} */
  let aiResponse = $state(null);
  let aiAvailable = $state(false);

  // Check if Claude CLI exists on mount
  import { onMount } from 'svelte';
  onMount(() => {
    invoke('get_product_type').then(() => { aiAvailable = true; }).catch(() => {});
  });


  /** Build context string from current pipeline data for AI prompt */
  function buildContext() {
    const step = $pipelineCurrentStep;
    const parts = [];
    const mod = $modelData;
    const dec = $decomposeData;
    const opt = $optimizeData;

    if (mod?.diagnostics) {
      const d = mod.diagnostics;
      parts.push(`Model: MQS=${d.mqs?.score?.toFixed(0)}, R²=${d.r_squared?.toFixed(3)}, MAPE=${d.mape?.toFixed(1)}%, R-hat=${d.r_hat?.toFixed(3)}`);
    }
    if (mod?.channelParams) {
      const chs = Object.entries(mod.channelParams).map(([n, p]) =>
        `${n}: ROI=${/** @type {any} */(p).roi?.toFixed(2)}x, alpha=${/** @type {any} */(p).alpha?.toFixed(2)}, beta=${/** @type {any} */(p).beta?.toFixed(3)}`
      );
      parts.push(`Channels: ${chs.join('; ')}`);
    }
    if (dec) {
      parts.push(`Base sales: ${dec.base_pct?.toFixed(0)}%`);
    }
    if (opt) {
      parts.push(`Optimization lift: ${opt.expected_lift_pct?.toFixed(1)}%`);
    }
    return parts.join('\n');
  }

  async function askAI() {
    const q = question.trim();
    if (!q) return;
    question = '';
    aiLoading = true;
    aiResponse = null;

    const context = buildContext();
    const prompt = `Ты — эконометрист-аналитик Aurora AI. Пользователь задаёт вопрос о результатах Marketing Mix Model.\n\nКонтекст модели:\n${context}\n\nВопрос: ${q}\n\nОтветь кратко (3-5 предложений), на русском, с конкретными рекомендациями.`;

    try {
      const result = /** @type {any} */ (await invoke('send_message', {
        cabinetId: 'econometrist',
        message: prompt,
        suppressExport: true,
      }));
      // send_message streams via events, but also returns final text
      aiResponse = typeof result === 'string' ? result : 'Ответ получен. Посмотрите в чате кабинета.';
    } catch (/** @type {any} */ e) {
      aiResponse = `Ошибка: ${e}. Убедитесь что Claude CLI установлен и авторизован.`;
    } finally {
      aiLoading = false;
    }
  }

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
                    <span class="action-applied">✓ Применено</span>
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

      {#if aiResponse}
        <div class="ai-response">
          <div class="ai-label">AI</div>
          <p class="ai-text">{aiResponse}</p>
          <button class="ai-dismiss" onclick={() => aiResponse = null}>x</button>
        </div>
      {/if}

      <div class="ask-section">
        <input
          class="ask-input"
          type="text"
          placeholder={aiAvailable ? 'Спросить AI...' : 'AI недоступен (нет Claude CLI)'}
          bind:value={question}
          disabled={aiLoading || !aiAvailable}
          onkeydown={(e) => {
            if (e.key === 'Enter' && question.trim()) askAI();
          }}
        />
        {#if aiLoading}
          <div class="ai-spinner"></div>
        {/if}
      </div>
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
    padding: 10px 10px 8px;
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
    padding: 8px 10px; border-radius: 6px;
    background: rgba(255,255,255,0.025);
    border-left: 3px solid transparent;
  }
  .insight-item.sev-info    { border-left-color: #3b82f6; }
  .insight-item.sev-success { border-left-color: #22c55e; }
  .insight-item.sev-warning { border-left-color: #f59e0b; }
  .insight-item.sev-error   { border-left-color: #ef4444; }

  .sev-badge {
    width: 16px; height: 16px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 50%; font-size: 9px; font-weight: 700;
    flex-shrink: 0; margin-top: 1px;
  }
  .sev-info    .sev-badge { background: rgba(59,130,246,0.15); color: #3b82f6; }
  .sev-success .sev-badge { background: rgba(34,197,94,0.15);  color: #22c55e; }
  .sev-warning .sev-badge { background: rgba(245,158,11,0.15); color: #f59e0b; }
  .sev-error   .sev-badge { background: rgba(239,68,68,0.15);  color: #ef4444; }

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
    padding: 3px 10px;
    background: rgba(34,197,94,0.12);
    border: 1px solid rgba(34,197,94,0.3);
    border-radius: 5px;
    color: #4ade80;
    font-size: 10px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }
  .action-btn:hover {
    background: rgba(34,197,94,0.22);
    border-color: rgba(34,197,94,0.5);
  }

  .action-applied {
    font-size: 10px;
    color: #22c55e;
    font-weight: 500;
  }

  .tip-text {
    font-size: 11px; color: var(--text-muted);
    line-height: 1.5; margin: 4px 0 0; padding: 6px 8px;
    background: rgba(255,255,255,0.02); border-radius: 4px;
  }

  .ai-response {
    position: relative;
    padding: 10px; border-radius: 6px;
    background: rgba(139,92,246,0.06);
    border: 1px solid rgba(139,92,246,0.2);
  }
  .ai-label {
    font-size: 9px; font-weight: 700; text-transform: uppercase;
    color: #a78bfa; letter-spacing: 0.06em; margin-bottom: 4px;
  }
  .ai-text { font-size: 12px; color: var(--text-primary, #e2e8f0); line-height: 1.5; margin: 0; }
  .ai-dismiss {
    position: absolute; top: 4px; right: 6px;
    background: none; border: none; color: var(--text-muted);
    font-size: 12px; cursor: pointer; padding: 2px 4px;
  }
  .ai-spinner {
    width: 14px; height: 14px;
    border: 2px solid rgba(139,92,246,0.2);
    border-top-color: #a78bfa;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
  }
  @keyframes spin { to { transform: translateY(-50%) rotate(360deg); } }

  .ask-section { margin-top: auto; flex-shrink: 0; position: relative; }
  .ask-input {
    width: 100%; padding: 7px 10px;
    background: rgba(255,255,255,0.05);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 6px; color: var(--text-primary, #e2e8f0);
    font-size: 12px; outline: none; box-sizing: border-box;
    transition: border-color 0.15s;
  }
  .ask-input:focus { border-color: var(--accent-primary, #3b82f6); }
  .ask-input::placeholder { color: var(--text-muted); }
</style>
