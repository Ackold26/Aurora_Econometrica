<script>
  /**
   * InsightsPanel — AI insights sidebar for the pipeline.
   * C4: width clamp(240px, 22%, 360px), auto-collapse below 1100px.
   */

  /** @type {{ collapsed?: boolean, onToggle?: () => void, insights?: string[] }} */
  let { collapsed = false, onToggle, insights = [] } = $props();

  /** @type {string} */
  let question = $state('');

  const defaultInsights = [
    'Загрузите данные и запустите валидацию для получения AI-инсайтов.',
  ];

  const displayInsights = $derived(insights.length > 0 ? insights : defaultInsights);
</script>

<!-- C4: clamp(240px, 22%, 360px) set in CSS -->
<aside class="insights-panel" class:collapsed aria-label="AI Инсайты">
  <div class="panel-header">
    {#if !collapsed}
      <span class="panel-title">AI Инсайты</span>
    {/if}
    <button
      class="collapse-btn"
      onclick={onToggle}
      title={collapsed ? 'Развернуть' : 'Свернуть панель'}
      aria-label={collapsed ? 'Развернуть инсайты' : 'Свернуть инсайты'}
    >
      {collapsed ? '◀' : '▶'}
    </button>
  </div>

  {#if !collapsed}
    <div class="panel-body">
      <ul class="insights-list" role="list">
        {#each displayInsights as insight, i}
          <li class="insight-item" role="listitem">{insight}</li>
        {/each}
      </ul>

      <div class="ask-section">
        <input
          class="ask-input"
          type="text"
          placeholder="Задать вопрос AI..."
          bind:value={question}
          onkeydown={(e) => {
            if (e.key === 'Enter' && question.trim()) {
              // Phase 5: will dispatch to AI
              question = '';
            }
          }}
        />
      </div>
    </div>
  {/if}
</aside>

<style>
  /* C4: clamp(240px, 22%, 360px) */
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
  .insights-panel.collapsed {
    width: 34px;
    min-width: 34px;
  }

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
    font-size: 11px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    white-space: nowrap;
    overflow: hidden;
    flex: 1;
  }
  .collapse-btn {
    background: none;
    border: none;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer;
    font-size: 10px;
    padding: 3px 5px;
    border-radius: 4px;
    flex-shrink: 0;
    transition: background 0.15s;
    line-height: 1;
  }
  .collapse-btn:hover { background: rgba(255,255,255,0.07); }

  .panel-body {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    padding: 12px;
    gap: 10px;
    min-height: 0;
  }

  .insights-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex: 1;
  }
  .insight-item {
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.55;
    padding: 8px 10px;
    background: rgba(255,255,255,0.03);
    border-radius: 6px;
    border-left: 2px solid var(--accent-primary, #3b82f6);
  }

  .ask-section {
    margin-top: auto;
    flex-shrink: 0;
  }
  .ask-input {
    width: 100%;
    padding: 7px 10px;
    background: rgba(255,255,255,0.05);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    font-size: 12px;
    outline: none;
    box-sizing: border-box;
    transition: border-color 0.15s, background 0.15s;
  }
  .ask-input:focus {
    border-color: var(--accent-primary, #3b82f6);
    background: rgba(255,255,255,0.07);
  }
  .ask-input::placeholder { color: rgba(148,163,184,0.45); }
</style>
