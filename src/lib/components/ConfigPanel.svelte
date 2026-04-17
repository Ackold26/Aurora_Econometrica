<script>
  /**
   * Model configuration panel with progressive disclosure.
   * Default: KPI dropdown + channels checkboxes + "Run" button.
   * Advanced (collapsible): adstock per channel, priors, MCMC params.
   *
   * @component ConfigPanel
   */
  import { invoke } from '@tauri-apps/api/core';
  import { activeProjectId, pipelineState, isComputing, computeStatus } from '$lib/project-state.js';
  import AdstockPreview from '$lib/components/AdstockPreview.svelte';

  /**
   * @type {{
   *   validation: any,
   *   onModelTrained?: (diagnostics: any) => void,
   *   useAsyncTraining?: boolean,
   *   onTrainingStarted?: (taskId: string) => void,
   *   lastConfig?: any,
   * }}
   */
  let {
    validation,
    onModelTrained,
    useAsyncTraining = false,
    onTrainingStarted,
    lastConfig = $bindable(null),
  } = $props();

  let showAdvanced = $state(false);

  // ── KPI selection ──
  let kpiOptions = $derived(
    validation?.columns?.filter(/** @param {any} c */ (c) => c.role === 'kpi').map(/** @param {any} c */ (c) => c.name) || []
  );
  let selectedKpi = $state('');

  // ── Media channels ──
  let mediaChannels = $derived(
    validation?.columns?.filter(/** @param {any} c */ (c) => c.role === 'media') || []
  );
  /** @type {Record<string, boolean>} */
  let channelEnabled = $state(/** @type {Record<string, boolean>} */ ({}));
  /** @type {Record<string, string>} */
  let channelAdstock = $state(/** @type {Record<string, string>} */ ({}));

  // Initialize from validation
  $effect(() => {
    if (validation?.columns) {
      const kpis = validation.columns.filter(/** @param {any} c */ (c) => c.role === 'kpi');
      if (kpis.length && !selectedKpi) selectedKpi = kpis[0].name;

      const media = validation.columns.filter(/** @param {any} c */ (c) => c.role === 'media');
      /** @type {Record<string, boolean>} */
      const enabled = {};
      /** @type {Record<string, string>} */
      const adstock = {};
      for (const ch of media) {
        enabled[ch.name] = !(ch.stats?.zeros_pct > 80);
        adstock[ch.name] = ch.adstock_type || 'geometric';
      }
      channelEnabled = enabled;
      channelAdstock = adstock;
    }
  });

  // ── Control variables ──
  let controlColumns = $derived(
    validation?.columns?.filter(/** @param {any} c */ (c) => c.role === 'control').map(/** @param {any} c */ (c) => c.name) || []
  );

  // ── MCMC params (advanced) ──
  let mcmcChains = $state(2);
  let mcmcDraws = $state(1000);
  let mcmcTune = $state(500);

  // ── Time estimate (heuristic: ~0.5s per draw × chains for Metropolis, ~0.15s for NUTS) ──
  const enabledCount = $derived(Object.values(channelEnabled).filter(Boolean).length);
  const estimateMinutes = $derived.by(() => {
    const chains = showAdvanced ? mcmcChains : 2;
    const draws = showAdvanced ? mcmcDraws : 1000;
    const tune = showAdvanced ? mcmcTune : 500;
    const totalSamples = (draws + tune) * chains;
    const secPerSample = 0.3 * Math.max(enabledCount / 4, 1); // scales with channels
    return Math.max(1, Math.round(totalSamples * secPerSample / 60));
  });

  // ── Actions ──
  async function trainModel() {
    const projectId = $activeProjectId;
    if (!projectId || !selectedKpi) return;

    const enabledChannels = Object.entries(channelEnabled)
      .filter(([, v]) => v)
      .map(([k]) => k);

    if (enabledChannels.length === 0) return;

    isComputing.set(true);
    computeStatus.set('Компилирую модель...');

    try {
      const projectDir = await invoke('project_get_dir', { projectId });

      // Update project config
      await invoke('project_update', {
        projectId,
        updates: {
          kpi_column: selectedKpi,
          media_columns: enabledChannels,
          control_columns: controlColumns,
        },
      });

      const config = {
        project_dir: projectDir,
        data_file: $pipelineState?.data?.file || '',
        kpi_column: selectedKpi,
        media_columns: enabledChannels,
        control_columns: controlColumns,
        date_column: validation?.detected?.date || 'date',
        adstock_config: Object.fromEntries(
          enabledChannels.map(ch => [ch, channelAdstock[ch] || 'geometric'])
        ),
        mcmc_override: showAdvanced ? { chains: mcmcChains, draws: mcmcDraws, tune: mcmcTune } : null,
      };

      // A3: async flow for pipeline (useAsyncTraining), sync flow for cabinet (backward compat)
      if (useAsyncTraining) {
        lastConfig = config;
        const start = await invoke('econ_train_start', { config });
        onTrainingStarted?.(start.task_id);
        // isComputing stays true — TrainingProgress component takes over
        return;
      }

      // ── Original sync flow (chat-first cabinet) — UNTOUCHED ──
      computeStatus.set('Обучаю модель (MCMC сэмплирование)...');

      const result = await invoke('econ_train', { config });

      if (result.status === 'ok') {
        computeStatus.set('Модель готова!');
        pipelineState.update(s => ({
          ...s,
          model: {
            trained: true,
            diagnostics: result.diagnostics,
            channelParams: result.channel_params,
            picklePath: result.model_path,
          },
        }));
        onModelTrained?.(result.diagnostics);
      } else {
        computeStatus.set(`Ошибка: ${result.message}`);
      }
    } catch (e) {
      computeStatus.set(`Ошибка: ${e}`);
    }

    setTimeout(() => {
      isComputing.set(false);
      computeStatus.set('');
    }, 3000);
  }
</script>

<div class="config-panel">
  <h3 class="panel-title">Настройка модели</h3>

  <!-- KPI -->
  <div class="config-group">
    <label class="config-label">
      Целевой KPI
      <span class="config-hint">Что моделируем</span>
    </label>
    <select class="config-select" bind:value={selectedKpi}>
      {#each kpiOptions as kpi}
        <option value={kpi}>{kpi}</option>
      {/each}
    </select>
  </div>

  <!-- Media channels -->
  <div class="config-group">
    <label class="config-label">Медиа-каналы ({Object.values(channelEnabled).filter(Boolean).length})</label>
    <div class="channels-grid">
      {#each mediaChannels as ch}
        <label class="channel-item" class:disabled={ch.stats?.zeros_pct > 80}>
          <input type="checkbox" bind:checked={channelEnabled[ch.name]} />
          <span class="channel-name">{ch.name}</span>
          {#if ch.stats?.zeros_pct > 50}
            <span class="channel-warn" title="{ch.stats.zeros_pct}% нулей">{ch.stats.zeros_pct}%∅</span>
          {/if}
        </label>
      {/each}
    </div>
  </div>

  <!-- Adstock (inline, minimal) + AdstockPreview -->
  <div class="config-group">
    <label class="config-label">
      Adstock
      <span class="config-hint">Тип отложенного эффекта</span>
    </label>
    <div class="adstock-with-preview">
      <select class="config-select" onchange={(e) => {
        const val = /** @type {HTMLSelectElement} */ (e.target).value;
        const updated = {...channelAdstock};
        for (const ch of Object.keys(updated)) updated[ch] = val;
        channelAdstock = updated;
      }}>
        <option value="auto">Авто (digital=мгновенный, TV=отложенный)</option>
        <option value="geometric">Geometric (все каналы)</option>
        <option value="weibull">Weibull (все каналы)</option>
      </select>
      <AdstockPreview type={Object.values(channelAdstock)[0] === 'weibull' ? 'weibull' : 'geometric'} />
    </div>
  </div>

  <!-- Advanced (collapsible) -->
  <button class="advanced-toggle" onclick={() => showAdvanced = !showAdvanced}>
    {showAdvanced ? '▾' : '▸'} Расширенные настройки
  </button>

  {#if showAdvanced}
    <div class="advanced-section">
      <!-- Per-channel adstock -->
      <div class="config-group">
        <label class="config-label">Adstock по каналам</label>
        {#each Object.entries(channelEnabled).filter(([,v]) => v) as [ch]}
          <div class="adstock-row">
            <span class="adstock-name">{ch}</span>
            <select class="config-select-sm" bind:value={channelAdstock[ch]}>
              <option value="geometric">Geometric</option>
              <option value="weibull">Weibull</option>
            </select>
          </div>
        {/each}
      </div>

      <!-- MCMC params -->
      <div class="config-group">
        <label class="config-label">MCMC параметры</label>
        <div class="mcmc-grid">
          <label>Chains <input type="number" bind:value={mcmcChains} min="1" max="8" /></label>
          <label>Draws <input type="number" bind:value={mcmcDraws} min="500" max="10000" step="500" /></label>
          <label>Tune <input type="number" bind:value={mcmcTune} min="200" max="5000" step="100" /></label>
        </div>
      </div>
    </div>
  {/if}

  <!-- PSY: Commitment summary — user sees what THEY configured (IKEA Effect + Commitment) -->
  {#if selectedKpi && Object.values(channelEnabled).filter(Boolean).length > 0}
    <div class="config-summary">
      <span class="summary-label">Конфигурация:</span>
      KPI: <strong>{selectedKpi}</strong> | {Object.values(channelEnabled).filter(Boolean).length} каналов | Adstock: авто
    </div>
  {/if}

  <!-- Run button -->
  <button
    class="run-btn"
    onclick={trainModel}
    disabled={$isComputing || !selectedKpi || Object.values(channelEnabled).filter(Boolean).length === 0}
  >
    {#if $isComputing}
      <span class="spinner"></span> {$computeStatus || 'Обучаю модель...'}
    {:else}
      Запустить модель
    {/if}
  </button>
  {#if !$isComputing && enabledCount > 0}
    <p class="time-estimate">Оценка: ~{estimateMinutes} мин ({enabledCount} канал{enabledCount > 4 ? 'ов' : enabledCount > 1 ? 'а' : ''})</p>
  {/if}
</div>

<style>
  .config-panel {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 16px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-radius: 12px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
  }

  .panel-title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }

  .config-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .config-label {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary, #94a3b8);
    display: flex;
    justify-content: space-between;
  }

  .config-hint {
    font-weight: 400;
    opacity: 0.6;
  }

  .config-select, .config-select-sm {
    padding: 8px 10px;
    background: rgba(0,0,0,0.3);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    font-size: 13px;
    outline: none;
    position: relative;
    z-index: 10;
  }

  .config-select:focus, .config-select-sm:focus {
    border-color: var(--accent-primary, #3b82f6);
  }

  .config-select-sm { padding: 4px 8px; font-size: 12px; }

  .config-summary {
    padding: 8px 12px;
    background: rgba(59, 130, 246, 0.06);
    border: 1px solid rgba(59, 130, 246, 0.12);
    border-radius: 6px;
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.5;
  }

  .config-summary strong { color: var(--text-primary, #e2e8f0); }
  .summary-label { color: var(--accent-primary, #3b82f6); font-weight: 500; }

  .channels-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .channel-item {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    background: rgba(0,0,0,0.2);
    border-radius: 6px;
    font-size: 12px;
    color: var(--text-primary, #e2e8f0);
    cursor: pointer;
  }

  .channel-item.disabled { opacity: 0.5; }
  .channel-item input[type="checkbox"] { width: 14px; height: 14px; }
  .channel-warn { color: var(--warning, #f59e0b); font-size: 10px; }

  .adstock-with-preview {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .advanced-toggle {
    background: transparent;
    border: none;
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
    cursor: pointer;
    text-align: left;
    padding: 0;
  }

  .advanced-toggle:hover { color: var(--text-primary, #e2e8f0); }

  .advanced-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
    background: rgba(0,0,0,0.15);
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.04);
  }

  .adstock-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 2px 0;
  }

  .adstock-name { font-size: 12px; color: var(--text-primary, #e2e8f0); }

  .mcmc-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 8px;
  }

  .mcmc-grid label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
  }

  .mcmc-grid input {
    padding: 6px 8px;
    background: rgba(0,0,0,0.3);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 4px;
    color: var(--text-primary, #e2e8f0);
    font-size: 12px;
    width: 100%;
  }

  .run-btn {
    padding: 12px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 8px;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    transition: opacity 0.15s;
  }

  .run-btn:hover:not(:disabled) { opacity: 0.9; }
  .run-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .time-estimate {
    text-align: center;
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
    margin-top: 6px;
  }

  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }
</style>
