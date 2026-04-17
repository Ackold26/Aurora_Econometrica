<script>
  /**
   * InsightsPanel — Rule-based insights sidebar for the pipeline.
   * Tier 1: offline insights from insights-rules.js (always works).
   * Tier 2: Claude AI (online, optional) — Phase 10.
   * C4: width clamp(240px, 22%, 360px), auto-collapse below 1100px.
   */
  import {
    pipelineCurrentStep,
    importData, validateData, modelData, decomposeData, optimizeData,
  } from '$lib/project-state.js';
  import {
    importInsights, validateInsights, modelInsights, decomposeInsights, optimizeInsights,
  } from '$lib/insights-rules.js';

  /** @type {{ collapsed?: boolean, onToggle?: () => void }} */
  let { collapsed = false, onToggle } = $props();

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
        if (!imp?.columns) return [];
        const zeros = /** @type {Record<string, number>} */ ({});
        for (const c of (imp.columns ?? [])) {
          if (c.stats?.zeros_pct > 0) zeros[c.name] = c.stats.zeros_pct;
        }
        return importInsights({ rows: imp.rows?.length ?? 0, cols: imp.columns?.length ?? 0, columns: imp.columns ?? [], zeros });
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
</script>

<aside class="insights-panel" class:collapsed aria-label="Инсайты">
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
                {#if insight.tip}
                  <button
                    class="tip-toggle"
                    onclick={() => expandedTip = expandedTip === i ? null : i}
                  >
                    {expandedTip === i ? 'Скрыть' : 'Подробнее'}
                  </button>
                  {#if expandedTip === i}
                    <p class="tip-text">{insight.tip}</p>
                  {/if}
                {/if}
              </div>
            </li>
          {/each}
        </ul>
      {/if}

      <div class="ask-section">
        <input
          class="ask-input"
          type="text"
          placeholder="Задать вопрос AI..."
          bind:value={question}
          onkeydown={(e) => {
            if (e.key === 'Enter' && question.trim()) {
              // Phase 10: Claude AI Tier 2
              question = '';
            }
          }}
        />
      </div>
    </div>
  {/if}
</aside>

<style>
  .insights-panel {
    width: clamp(240px, 22%, 360px);
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-left: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    transition: width 0.2s ease, min-width 0.2s ease;
    overflow: hidden;
    flex-shrink: 0;
  }
  .insights-panel.collapsed { width: 34px; min-width: 34px; }

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
    font-size: 12px; color: rgba(148,163,184,0.5);
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

  .tip-toggle {
    background: none; border: none; padding: 0;
    font-size: 11px; color: var(--accent-primary, #3b82f6);
    cursor: pointer; margin-top: 4px; display: block;
  }
  .tip-toggle:hover { text-decoration: underline; }

  .tip-text {
    font-size: 11px; color: rgba(148,163,184,0.65);
    line-height: 1.5; margin: 4px 0 0; padding: 6px 8px;
    background: rgba(255,255,255,0.02); border-radius: 4px;
  }

  .ask-section { margin-top: auto; flex-shrink: 0; }
  .ask-input {
    width: 100%; padding: 7px 10px;
    background: rgba(255,255,255,0.05);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 6px; color: var(--text-primary, #e2e8f0);
    font-size: 12px; outline: none; box-sizing: border-box;
    transition: border-color 0.15s;
  }
  .ask-input:focus { border-color: var(--accent-primary, #3b82f6); }
  .ask-input::placeholder { color: rgba(148,163,184,0.45); }
</style>
