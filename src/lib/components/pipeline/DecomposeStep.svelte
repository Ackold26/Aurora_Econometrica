<script>
  /**
   * Step 3: Sales Decomposition.
   * B2: auto-runs on mount if no decomposeData yet.
   * Layout: insight banner → waterfall (full width) → grid: ROI (50%) | timeline (50%).
   * @component DecomposeStep
   */
  import { onMount } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import {
    activeProjectId,
    decomposeData,
    completeStep,
    setStepError,
    isComputing,
    computeStatus,
    expertMode,
  } from '$lib/project-state.js';
  import WaterfallChart from '$lib/components/pipeline/WaterfallChart.svelte';
  import ROIComparison from '$lib/components/pipeline/ROIComparison.svelte';
  import ExpertDecomposePanel from '$lib/components/pipeline/ExpertDecomposePanel.svelte';
  import ChannelTimeline from '$lib/components/pipeline/ChannelTimeline.svelte';

  /** @type {'idle' | 'loading' | 'done' | 'error'} */
  let stepState = $state('idle');
  /** @type {string | null} */
  let errorMessage = $state(null);

  const data = $derived($decomposeData);

  async function runDecompose() {
    const projectId = get(activeProjectId);
    if (!projectId) { errorMessage = 'Проект не выбран'; stepState = 'error'; return; }

    stepState = 'loading';
    isComputing.set(true);
    computeStatus.set('Декомпозиция продаж...');
    errorMessage = null;

    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId }));
      const result = /** @type {any} */ (await invoke('econ_decompose', { projectDir }));

      if (result.status === 'ok') {
        decomposeData.set(result);
        stepState = 'done';
        completeStep(3);
      } else {
        handleError(result.message || 'Ошибка декомпозиции');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    } finally {
      isComputing.set(false);
      computeStatus.set('');
    }
  }

  /** @param {string} msg */
  function handleError(msg) {
    errorMessage = msg;
    stepState = 'error';
    setStepError(3, msg);
    // isComputing/computeStatus cleared in finally block
  }

  // B2: auto-run on mount if no data yet
  onMount(() => {
    (async () => {
      if (!get(decomposeData)) {
        await runDecompose();
      } else {
        stepState = 'done';
      }
    })();
  });
</script>

<div class="decompose-step">

  <!-- Loading state -->
  {#if stepState === 'loading'}
    <div class="loading-banner">
      <div class="spinner"></div>
      <span>Анализирую вклад каналов...</span>
    </div>
  {/if}

  <!-- Error banner -->
  {#if stepState === 'error' && errorMessage}
    <div class="error-banner">
      <span class="error-icon">⚠</span>
      <span class="error-text">{errorMessage}</span>
      <button class="btn-retry" onclick={runDecompose}>Повторить</button>
    </div>
  {/if}

  <!-- Results -->
  {#if stepState === 'done' && data}

    <!-- Insight banner -->
    {#if data.insight}
      <div class="insight-banner">
        <span class="insight-icon">💡</span>
        <p class="insight-text">{data.insight}</p>
        <button class="btn-rerun" onclick={runDecompose} title="Пересчитать">↺</button>
      </div>
    {/if}

    <!-- Waterfall — full width -->
    <div class="card">
      <div class="card-title">Декомпозиция продаж</div>
      <WaterfallChart waterfall={data.waterfall} />
    </div>

    <!-- Two-column: ROI | Timeline -->
    <div class="charts-grid">
      <div class="card">
        <div class="card-title">Расходы vs Эффект</div>
        <ROIComparison channels={data.channels} />
      </div>
      <div class="card">
        <div class="card-title">Динамика по периодам</div>
        {#if data.time_series?.dates?.length}
          <ChannelTimeline timeSeries={data.time_series} />
        {:else}
          <div class="no-data">Нет данных для временного ряда</div>
        {/if}
      </div>
    </div>

    <!-- Channel table -->
    <div class="card">
      <div class="card-title">Детализация по каналам</div>
      <div class="channel-table">
        <table>
          <thead>
            <tr>
              <th>Канал</th>
              <th>Расходы</th>
              <th>Вклад</th>
              <th>ROI</th>
              <th>Gap</th>
              <th>Вердикт</th>
            </tr>
          </thead>
          <tbody>
            {#each data.channels as ch}
              <tr>
                <td class="ch-name">{ch.name}</td>
                <td>{ch.spend.toLocaleString('ru-RU')}</td>
                <td>{ch.contribution.toLocaleString('ru-RU')}</td>
                <td class:roi-good={ch.roi > 1.5} class:roi-mid={ch.roi >= 0.8 && ch.roi <= 1.5} class:roi-bad={ch.roi < 0.8}>
                  {ch.roi.toFixed(2)}×
                </td>
                <td class:gap-pos={ch.efficiency_gap > 0} class:gap-neg={ch.efficiency_gap < 0}>
                  {ch.efficiency_gap > 0 ? '+' : ''}{ch.efficiency_gap}%
                </td>
                <td>{ch.verdict}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

  {/if}

  {#if $expertMode}
    <ExpertDecomposePanel />
  {/if}

</div>

<style>
  .decompose-step {
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

  .loading-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 18px 20px;
    background: color-mix(in srgb, var(--accent-primary) 6%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 15%, transparent);
    border-radius: 10px;
    color: var(--text-secondary, #94a3b8);
    font-size: 14px;
  }

  .spinner {
    width: 20px;
    height: 20px;
    border: 2px solid color-mix(in srgb, var(--accent-primary) 30%, transparent);
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

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
  .btn-retry:hover { opacity: 0.85; }

  .insight-banner {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 14px 16px;
    background: color-mix(in srgb, var(--accent-primary) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-radius: 10px;
  }
  .insight-icon { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
  .insight-text { flex: 1; font-size: 13px; color: var(--text-secondary, #94a3b8); line-height: 1.6; margin: 0; }
  .btn-rerun {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 16px;
    cursor: pointer;
    padding: 0 4px;
    line-height: 1;
    flex-shrink: 0;
    transition: color 0.15s;
  }
  .btn-rerun:hover { color: var(--text-secondary, #94a3b8); }

  .card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 16px;
  }
  .card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .charts-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  @media (max-width: 900px) {
    .charts-grid { grid-template-columns: 1fr; }
  }

  .no-data {
    padding: 24px;
    text-align: center;
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
  }

  .channel-table {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  th {
    text-align: left;
    padding: 6px 10px;
    color: var(--text-muted);
    font-weight: 500;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }
  td {
    padding: 7px 10px;
    color: var(--text-primary, #e2e8f0);
    border-bottom: 1px solid rgba(255,255,255,0.04);
  }
  .ch-name { font-weight: 500; }
  .roi-good { color: #22c55e; font-weight: 600; }
  .roi-mid { color: #f59e0b; }
  .roi-bad { color: #ef4444; }
  .gap-pos { color: #22c55e; }
  .gap-neg { color: #ef4444; }
</style>
