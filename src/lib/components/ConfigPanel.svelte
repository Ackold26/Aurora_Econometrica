<script>
  /**
   * Model configuration panel with progressive disclosure.
   * Default: KPI dropdown + channels checkboxes + "Run" button.
   * Advanced (collapsible): adstock per channel, priors, MCMC params.
   *
   * @component ConfigPanel
   */
  import { invoke } from '@tauri-apps/api/core';
  import { activeProjectId, pipelineState, importData, isComputing, computeStatus, expertMode } from '$lib/project-state.js';
  import AdstockPreview from '$lib/components/AdstockPreview.svelte';

  /**
   * @type {{
   *   validation: any,
   *   onModelTrained?: (diagnostics: any) => void,
   *   useAsyncTraining?: boolean,
   *   onTrainingStarted?: (taskId: string) => void,
   *   lastConfig?: any,
   *   modelTrained?: boolean,
   * }}
   */
  let {
    validation,
    onModelTrained,
    useAsyncTraining = false,
    onTrainingStarted,
    lastConfig = $bindable(null),
    modelTrained = false,
  } = $props();

  let showAdvanced = $state(false);

  // Auto-expand advanced when Expert mode is turned on (но не если модель уже обучена —
  // после тренировки сворачиваем чтобы пользователь видел результаты ниже).
  $effect(() => {
    if ($expertMode && !modelTrained) showAdvanced = true;
  });

  // После завершения обучения свернуть Расширенные настройки — освобождаем место
  // для блока с результатами (auto-scroll прокручивает вниз к диагностике).
  let prevTrained = false;
  $effect(() => {
    if (modelTrained && !prevTrained) {
      showAdvanced = false;
    }
    prevTrained = modelTrained;
  });

  // ── Custom dropdown state ──
  let kpiOpen = $state(false);
  let adstockOpen = $state(false);
  /** @type {HTMLElement|null} */
  let kpiAnchor = $state(null);
  /** @type {HTMLElement|null} */
  let adstockAnchor = $state(null);

  /** @param {'kpi'|'adstock'} which @param {HTMLElement} anchor */
  function openDropdown(which, anchor) {
    if (which === 'kpi') { kpiOpen = !kpiOpen; adstockOpen = false; kpiAnchor = anchor; }
    else { adstockOpen = !adstockOpen; kpiOpen = false; adstockAnchor = anchor; }
  }

  /** @param {HTMLElement|null} anchor */
  function getDropdownStyle(anchor) {
    if (!anchor) return '';
    const r = anchor.getBoundingClientRect();
    return `position:fixed;left:${r.left}px;top:${r.bottom + 4}px;width:${r.width}px;z-index:9999;`;
  }

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
        adstock[ch.name] = 'auto';
      }
      channelEnabled = enabled;
      channelAdstock = adstock;
    }
  });

  // ── Adstock auto-select (marketer mode) ──
  let adstockAutoSelected = $state(false);
  let adstockAutoLabel = $state('');

  $effect(() => {
    // In marketer mode: auto-select adstock via BIC when KPI + channels ready
    if ($expertMode || adstockAutoSelected || !selectedKpi) return;
    const enabledChannels = Object.entries(channelEnabled).filter(([, v]) => v).map(([k]) => k);
    if (enabledChannels.length === 0) return;
    const filePath = $importData?.file || $pipelineState?.data?.file;
    if (!filePath) return;

    (async () => {
      try {
        const result = /** @type {any} */ (await invoke('econ_adstock_select', {
          filePath, kpiColumn: selectedKpi, mediaColumns: enabledChannels,
        }));
        if (result.status === 'ok' && result.selections) {
          /** @type {Record<string, string>} */
          const updated = { ...channelAdstock };
          const labels = [];
          for (const [ch, sel] of Object.entries(result.selections)) {
            const s = /** @type {any} */ (sel);
            updated[ch] = s.type;
            labels.push(`${ch}: ${s.type === 'weibull' ? 'Weibull' : 'Geometric'}`);
          }
          channelAdstock = updated;
          adstockAutoSelected = true;
          adstockAutoLabel = labels.join(', ');
        }
      } catch { /* sidecar not ready yet — use defaults */ }
    })();
  });

  // ── Adstock dropdown options ──
  const adstockOptions = [
    { value: 'auto', label: 'Авто (digital=мгновенный, TV=отложенный)' },
    { value: 'geometric', label: 'Geometric (все каналы)' },
    { value: 'weibull', label: 'Weibull (все каналы)' },
  ];
  const currentAdstock = $derived(Object.values(channelAdstock)[0] || 'auto');
  const currentAdstockLabel = $derived(adstockOptions.find(o => o.value === currentAdstock)?.label || adstockOptions[0].label);

  // ── Control variables ──
  let controlColumns = $derived(
    validation?.columns?.filter(/** @param {any} c */ (c) => c.role === 'control').map(/** @param {any} c */ (c) => c.name) || []
  );

  // ── MCMC params (advanced) ──
  // Defaults bumped 2026-04-19 → 4/2000/2000.
  // На JAX/NUTS со tight priors это секунды для типового медиаплана,
  // но даёт надёжный R-hat (4 цепи) и точные ROI CI (2000 draws).
  let mcmcChains = $state(4);
  let mcmcDraws = $state(2000);
  let mcmcTune = $state(2000);

  // ── Time estimate (heuristic: ~0.5s per draw × chains for Metropolis, ~0.15s for NUTS) ──
  const enabledCount = $derived(Object.values(channelEnabled).filter(Boolean).length);
  const estimateMinutes = $derived.by(() => {
    const chains = showAdvanced ? mcmcChains : 4;
    const draws = showAdvanced ? mcmcDraws : 2000;
    const tune = showAdvanced ? mcmcTune : 2000;
    const totalSamples = (draws + tune) * chains;
    const secPerSample = 0.3 * Math.max(enabledCount / 4, 1); // scales with channels
    return Math.max(1, Math.round(totalSamples * secPerSample / 60));
  });

  // Auto-warning when defaults may be slow for the current project shape.
  // Triggers for big models (>10 channels) — fewer draws/chains могут сильно ускорить.
  const heavyModelWarn = $derived(enabledCount > 10);

  // ── Actions ──
  async function trainModel() {
    const projectId = $activeProjectId;
    if (!projectId) {
      computeStatus.set('Ошибка: проект не выбран. Создайте проект на шаге Импорт.');
      setTimeout(() => computeStatus.set(''), 5000);
      return;
    }
    if (!selectedKpi) {
      computeStatus.set('Ошибка: не выбран целевой KPI.');
      setTimeout(() => computeStatus.set(''), 4000);
      return;
    }

    const enabledChannels = Object.entries(channelEnabled)
      .filter(([, v]) => v)
      .map(([k]) => k);

    if (enabledChannels.length === 0) {
      computeStatus.set('Ошибка: не выбрано ни одного медиа-канала.');
      setTimeout(() => computeStatus.set(''), 4000);
      return;
    }

    const dataFile = $importData?.file || $pipelineState?.data?.file || '';
    if (!dataFile) {
      computeStatus.set('Ошибка: файл данных не найден. Вернитесь на шаг Импорт и загрузите файл заново.');
      setTimeout(() => computeStatus.set(''), 6000);
      return;
    }

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
        data_file: dataFile,
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
      computeStatus.set('Обучаю модель (Markov Chain Monte Carlo сэмплирование)...');

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
    <button
      class="config-select dropdown-trigger"
      bind:this={kpiAnchor}
      onclick={(e) => openDropdown('kpi', e.currentTarget)}
    >
      <span>{selectedKpi || '— выберите KPI —'}</span>
      <span class="dropdown-arrow" class:open={kpiOpen}>▾</span>
    </button>
    {#if kpiOpen}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="dropdown-overlay" onclick={() => kpiOpen = false}></div>
      <div class="dropdown-list" style={getDropdownStyle(kpiAnchor)}>
        {#each kpiOptions as kpi}
          <button class="dropdown-item" class:selected={kpi === selectedKpi} onclick={() => { selectedKpi = kpi; kpiOpen = false; }}>
            {kpi}
          </button>
        {/each}
        {#if kpiOptions.length === 0}
          <span class="dropdown-empty">Нет доступных KPI</span>
        {/if}
      </div>
    {/if}
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
      <button
        class="config-select dropdown-trigger"
        bind:this={adstockAnchor}
        onclick={(e) => openDropdown('adstock', e.currentTarget)}
      >
        <span>{currentAdstockLabel}</span>
        <span class="dropdown-arrow" class:open={adstockOpen}>▾</span>
      </button>
      {#if adstockOpen}
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="dropdown-overlay" onclick={() => adstockOpen = false}></div>
        <div class="dropdown-list" style={getDropdownStyle(adstockAnchor)}>
          {#each adstockOptions as opt}
            <button class="dropdown-item" class:selected={currentAdstock === opt.value} onclick={() => {
              const updated = {...channelAdstock};
              for (const ch of Object.keys(updated)) updated[ch] = opt.value;
              channelAdstock = updated;
              adstockOpen = false;
            }}>
              {opt.label}
            </button>
          {/each}
        </div>
      {/if}
      <AdstockPreview type={Object.values(channelAdstock)[0] === 'weibull' ? 'weibull' : 'geometric'} />
    </div>
  </div>

  <!-- Advanced (collapsible) — only in Expert mode -->
  {#if $expertMode}
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
          <label class="config-label">Параметры Markov Chain Monte Carlo</label>
          <div class="mcmc-grid">
            <label>
              <span class="mcmc-label-row">
                Chains
                <span class="help-icon" title="Количество параллельных цепей Markov Chain Monte Carlo. Дефолт 4 — надёжная диагностика сходимости (R-hat). На JAX/NUTS параллелятся в один вызов, почти не замедляют обучение. Минимум 2 — для R-hat нужны хотя бы 2 независимые цепи.">?</span>
              </span>
              <input type="number" bind:value={mcmcChains} min="1" max="8" />
            </label>
            <label>
              <span class="mcmc-label-row">
                Draws
                <span class="help-icon" title="Число основных выборок на каждую цепь (после разогрева). 2000 — стандарт. 500 — быстрый прогон для проверки. 5000+ — для публикации. Чем больше — тем точнее ROI-оценки и уже доверительные интервалы.">?</span>
              </span>
              <input type="number" bind:value={mcmcDraws} min="500" max="10000" step="500" />
            </label>
            <label>
              <span class="mcmc-label-row">
                Tune
                <span class="help-icon" title="Warmup: число выборок для настройки step-size сэмплера. 1000 — стандарт. При низком ratio (меньше 4:1) увеличьте до 2000. Эти выборки отбрасываются и не влияют на финальный результат.">?</span>
              </span>
              <input type="number" bind:value={mcmcTune} min="200" max="5000" step="100" />
            </label>
          </div>
        </div>
      </div>
    {/if}
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
    class:trained={modelTrained && !$isComputing}
    onclick={trainModel}
    disabled={$isComputing || !selectedKpi || Object.values(channelEnabled).filter(Boolean).length === 0}
  >
    {#if $isComputing}
      <span class="spinner"></span> {$computeStatus || 'Обучаю модель...'}
    {:else if modelTrained}
      ✓ Обучено · Перетренировать
    {:else}
      Запустить модель
    {/if}
  </button>
  {#if !$isComputing && enabledCount > 0}
    <p class="time-estimate">Оценка: ~{estimateMinutes} мин ({enabledCount} канал{enabledCount > 4 ? 'ов' : enabledCount > 1 ? 'а' : ''})</p>
  {/if}
  {#if heavyModelWarn && !showAdvanced}
    <p class="heavy-warn">
      Большая модель (&gt;10 каналов). Дефолт 4 цепи × 2000 draws точный, но может занять минуту.
      Можно снизить в «Расширенных» до 2 цепей × 1000 draws — будет в разы быстрее.
    </p>
  {/if}
  {#if adstockAutoSelected && !$expertMode}
    <p class="adstock-auto-label">Adstock: {adstockAutoLabel} (авто по BIC)</p>
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
  }

  .config-select:focus, .config-select-sm:focus {
    border-color: var(--accent-primary, #3b82f6);
  }

  .config-select-sm { padding: 4px 8px; font-size: 12px; }

  /* Custom dropdown */
  .dropdown-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    cursor: pointer;
    text-align: left;
  }
  .dropdown-trigger:hover { border-color: rgba(255,255,255,0.2); }
  .dropdown-arrow { font-size: 10px; opacity: 0.6; transition: transform 0.15s; }
  .dropdown-arrow.open { transform: rotate(180deg); }

  .dropdown-overlay {
    position: fixed;
    inset: 0;
    z-index: 9998;
  }

  .dropdown-list {
    background: #1e2130;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    overflow: hidden;
    max-height: 240px;
    overflow-y: auto;
  }

  .dropdown-item {
    display: block;
    width: 100%;
    padding: 9px 12px;
    background: none;
    border: none;
    color: var(--text-primary, #e2e8f0);
    font-size: 13px;
    text-align: left;
    cursor: pointer;
    transition: background 0.1s;
  }
  .dropdown-item:hover { background: rgba(255,255,255,0.07); }
  .dropdown-item.selected { background: color-mix(in srgb, var(--accent-primary) 15%, transparent); color: #93c5fd; }

  .dropdown-empty {
    display: block;
    padding: 9px 12px;
    font-size: 12px;
    color: var(--text-muted, #64748b);
  }

  .config-summary {
    padding: 8px 12px;
    background: color-mix(in srgb, var(--accent-primary) 6%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 12%, transparent);
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
    border: 1px solid color-mix(in srgb, var(--danger) 40%, transparent);
    border-radius: var(--radius-sm, 6px);
    color: var(--danger);
    font-size: 12px;
    font-weight: 600;
    padding: 6px 12px;
    cursor: pointer;
    text-align: left;
    padding: 0;
  }

  .advanced-toggle:hover { color: var(--text-primary, #e2e8f0); }

  .advanced-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 14px;
    background: color-mix(in srgb, var(--danger) 4%, transparent);
    border-radius: var(--radius-md, 8px);
    border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--danger) 8%, transparent);
    position: relative;
  }
  .advanced-section::before {
    content: 'Экспертный режим';
    position: absolute;
    top: -8px;
    left: 12px;
    padding: 2px 8px;
    background: var(--bg-primary, #0C0C12);
    color: var(--danger);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border-radius: 4px;
  }

  /* Tooltip icon for MCMC params */
  .help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--accent-primary) 20%, transparent);
    color: var(--accent-primary);
    font-size: 10px;
    font-weight: 700;
    margin-left: 6px;
    cursor: help;
    vertical-align: middle;
    line-height: 1;
  }
  .help-icon:hover {
    background: var(--accent-primary);
    color: #fff;
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
  .mcmc-label-row {
    display: inline-flex;
    align-items: center;
    gap: 2px;
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
    transition: background 0.2s, color 0.2s, border 0.2s;
  }
  /* После тренировки: меняем стиль чтобы пользователь сразу понял — действие изменилось. */
  .run-btn.trained {
    background: transparent;
    border: 1px solid var(--success);
    color: var(--success);
  }
  .run-btn.trained:hover:not(:disabled) {
    background: color-mix(in srgb, var(--success) 12%, transparent);
  }

  .run-btn:hover:not(:disabled) { opacity: 0.9; }
  .run-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .time-estimate {
    text-align: center;
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
    margin-top: 6px;
  }
  .heavy-warn {
    text-align: center;
    font-size: 11px;
    line-height: 1.4;
    color: var(--text-secondary, #94a3b8);
    background: color-mix(in srgb, #f59e0b 12%, transparent);
    border: 1px solid color-mix(in srgb, #f59e0b 30%, transparent);
    border-radius: 8px;
    padding: 8px 12px;
    margin-top: 6px;
  }
  .adstock-auto-label {
    text-align: center;
    font-size: 10px;
    color: rgba(139,92,246,0.7);
    margin-top: 4px;
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
