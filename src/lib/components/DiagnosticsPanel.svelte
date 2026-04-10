<script>
  /**
   * Diagnostics & results panel.
   * Shows matplotlib charts (base64 PNG) with actionable insights below.
   *
   * @component DiagnosticsPanel
   */
  import { invoke } from '@tauri-apps/api/core';
  import { activeProjectId, chartImages, pipelineState } from '$lib/project-state.js';

  /** @type {{ chartType: string, title?: string, insight?: string }} */
  let { chartType, title = '', insight = '' } = $props();

  let loading = $state(false);
  let error = $state('');

  let chartSrc = $derived($chartImages[chartType] || '');

  async function loadChart() {
    const projectId = $activeProjectId;
    if (!projectId) return;

    loading = true;
    error = '';
    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const result = /** @type {any} */ (await invoke('econ_chart', { projectDir, chartType }));
      if (result.status === 'ok' && result.chart) {
        chartImages.update(/** @param {any} c */ (c) => ({ ...c, [chartType]: result.chart }));
      } else {
        error = result.message || 'Не удалось загрузить график';
      }
    } catch (e) {
      error = `${e}`;
    }
    loading = false;
  }
</script>

<div class="diagnostics-panel">
  {#if title}
    <h4 class="panel-title">{title}</h4>
  {/if}

  {#if chartSrc}
    <img
      class="chart-img"
      src="data:image/png;base64,{chartSrc}"
      alt={title || chartType}
    />
  {:else if loading}
    <div class="chart-placeholder">
      <span class="spinner"></span> Генерирую график...
    </div>
  {:else if error}
    <div class="chart-error">{error}</div>
  {:else}
    <button class="load-btn" onclick={loadChart}>
      📊 Показать {title || chartType}
    </button>
  {/if}

  {#if insight}
    <div class="insight-box">
      <span class="insight-icon">💡</span>
      <p class="insight-text">{insight}</p>
    </div>
  {/if}
</div>

<style>
  .diagnostics-panel {
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 16px;
  }

  .panel-title {
    margin: 0 0 12px;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }

  .chart-img {
    width: 100%;
    border-radius: 8px;
  }

  .chart-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 40px;
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
  }

  .chart-error {
    padding: 16px;
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.2);
    border-radius: 8px;
    color: var(--error, #ef4444);
    font-size: 12px;
  }

  .load-btn {
    width: 100%;
    padding: 16px;
    background: rgba(0,0,0,0.15);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s;
  }

  .load-btn:hover {
    border-color: var(--accent-primary, #3b82f6);
    color: var(--text-primary, #e2e8f0);
    background: rgba(59, 130, 246, 0.05);
  }

  .insight-box {
    display: flex;
    gap: 10px;
    margin-top: 12px;
    padding: 12px 14px;
    background: rgba(59, 130, 246, 0.06);
    border: 1px solid rgba(59, 130, 246, 0.12);
    border-radius: 8px;
  }

  .insight-icon { font-size: 16px; flex-shrink: 0; }

  .insight-text {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-primary, #e2e8f0);
  }

  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.2);
    border-top-color: var(--accent-primary, #3b82f6);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }
</style>
