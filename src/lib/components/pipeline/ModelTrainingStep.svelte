<script>
  /**
   * Step 2: Model Training.
   * B1: vertical stack - ConfigPanel → TrainingProgress → MQSBadge + ConvergenceDashboard.
   * B2: no channel params table (Phase 4).
   * C5: error recovery with "Повторить" + "Изменить настройки".
   *
   * @component ModelTrainingStep
   */
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import {
    validateData, modelData, isComputing, computeStatus,
    completeStep, setStepError, resetDownstream, expertMode,
    modelStaleStatus,
  } from '$lib/project-state.js';
  import { mqsView } from '$lib/metric-views.js';
  import { TriangleAlert } from 'lucide-svelte';
  import ExpertModelPanel from '$lib/components/pipeline/ExpertModelPanel.svelte';
  import ConfigPanel from '$lib/components/ConfigPanel.svelte';
  import TrainingProgress from '$lib/components/pipeline/TrainingProgress.svelte';
  import ConvergenceDashboard from '$lib/components/pipeline/ConvergenceDashboard.svelte';
  import BacktestCard from '$lib/components/pipeline/BacktestCard.svelte';
  import MQSBadge from '$lib/components/MQSBadge.svelte';
  import PipelineOnboarding from '$lib/components/pipeline/PipelineOnboarding.svelte';
  import { TOURS } from '$lib/pipeline-tours.js';
  import { shouldShowOnboarding } from '$lib/onboarding-state.js';

  // Обучающий тур - запускается после обучения модели (stepState='trained'),
  // когда на экране и config, и результаты - все spotlight'ы находят свою цель.
  let showOnboarding = $state(false);
  let onboardingChecked = false;

  // ── State ──
  /** @type {'idle' | 'training' | 'trained' | 'error'} */
  let stepState = $state('idle');
  /** @type {string | null} */
  let activeTaskId = $state(null);
  /** @type {string | null} */
  let errorMessage = $state(null);
  /** @type {any | null} */
  let lastConfig = $state(null);

  // Current validation result (from Step 1) - реактивно через $validateData
  const validation = $derived($validateData?.result || null);

  // Current model diagnostics (if trained)
  const diagnostics = $derived($modelData?.diagnostics || null);

  // INV-50 анти-рецидив (2026-06-07): MQS через единый пост-train селектор
  // mqsView (честный backend cap по эффективным параметрам, как MQSBadge/диск/
  // отчёты). Фронт НЕ раскапывает score по media-ratio.
  const mqs = $derived(mqsView(diagnostics));

  // Онбординг - запуск когда модель обучена (есть и config, и результаты на экране).
  $effect(() => {
    if (typeof window === 'undefined') return;
    if (onboardingChecked) return;
    if (stepState !== 'trained' || !diagnostics) return;
    onboardingChecked = true;
    if (shouldShowOnboarding('model')) {
      requestAnimationFrame(() => { showOnboarding = true; });
    }
  });

  /** Estimate training duration in seconds from config - used for smooth progress interpolation */
  const estimatedSec = $derived.by(() => {
    if (!lastConfig) return 600;
    const mc = lastConfig.mcmc_override || { chains: 2, draws: 1000, tune: 500 };
    const channels = (lastConfig.media_columns || []).length || 4;
    const totalSamples = (mc.draws + mc.tune) * mc.chains;
    const secPerSample = 0.3 * Math.max(channels / 4, 1);
    return Math.max(60, totalSamples * secPerSample);
  });

  // ── Handlers ──

  const TASK_KEY = 'econ-training-task';

  // F3: Restore training state after browser refresh
  onMount(() => {
    const savedTaskId = localStorage.getItem(TASK_KEY);
    if (savedTaskId && stepState === 'idle') {
      (async () => {
        try {
          const progress = /** @type {any} */ (await invoke('econ_train_progress'));
          if (progress.status === 'running') {
            activeTaskId = savedTaskId;
            stepState = 'training';
            isComputing.set(true);
            computeStatus.set('Сэмплирование байесовских цепей...');
          } else if (progress.status === 'completed') {
            const result = /** @type {any} */ (await invoke('econ_train_result', { taskId: savedTaskId }));
            handleComplete(result);
          } else {
            localStorage.removeItem(TASK_KEY);
            // Stale task in storage but not running - reset compute flag
            isComputing.set(false);
            computeStatus.set('');
          }
        } catch {
          localStorage.removeItem(TASK_KEY);
          isComputing.set(false);
          computeStatus.set('');
        }
      })();
    } else if (stepState === 'idle') {
      // No saved task - ensure compute flag is clean when entering the step
      isComputing.set(false);
      computeStatus.set('');
    }
  });

  /**
   * A3: useAsyncTraining prop in ConfigPanel triggers this instead of sync econ_train.
   * @param {string} taskId
   */
  function handleTrainingStarted(taskId) {
    activeTaskId = taskId;
    stepState = 'training';
    errorMessage = null;  // clear прошлый error (stale из pipelineStepMeta/localStorage)
    setStepError(2, null); // сброс errored-статуса текущего шага, чтобы UI не показывал cached сообщение
    isComputing.set(true);
    computeStatus.set('Сэмплирование байесовских цепей...');
    try { localStorage.setItem(TASK_KEY, taskId); } catch { /* ignore */ }
    // Сброс downstream-шагов: при перетренировке Decompose/Optimize/Report устаревают.
    // Без этого на stepper'е оставались старые статусы (например ✕ от прошлой ошибки).
    resetDownstream(2);
  }

  /**
   * Called when TrainingProgress receives completed result.
   * @param {any} result
   */
  function handleComplete(result) {
    isComputing.set(false);
    computeStatus.set('');
    try { localStorage.removeItem(TASK_KEY); } catch { /* ignore */ }

    if (result.status === 'ok') {
      modelData.set({
        diagnostics: result.diagnostics,
        channelParams: result.channel_params,
        picklePath: result.model_path,
        normalization: result.normalization ?? null,
      });
      stepState = 'trained';
      completeStep(2);
      // Auto-scroll к секции с результатами через небольшую задержку,
      // чтобы успел появиться success-баннер и ConfigPanel свернул advanced.
      setTimeout(() => {
        const target = document.querySelector('#model-results-anchor');
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 600);
    } else {
      handleError(result.message || 'Ошибка обучения модели');
    }
  }

  /** Прокрутить страницу к секции результатов (вызывается из success-баннера). */
  function scrollToResults() {
    const target = document.querySelector('#model-results-anchor');
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  /**
   * @param {string} msg
   */
  function handleError(msg) {
    isComputing.set(false);
    computeStatus.set('');
    try { localStorage.removeItem(TASK_KEY); } catch { /* ignore */ }
    errorMessage = msg;
    stepState = 'error';
    setStepError(2, msg);
  }

  /** User clicked Stop during training - reset to idle, allow reconfigure */
  function handleStop() {
    isComputing.set(false);
    computeStatus.set('');
    try { localStorage.removeItem(TASK_KEY); } catch { /* ignore */ }
    errorMessage = null;
    stepState = 'idle';
  }

  /** Retry with same config - auto-starts training without manual Run click */
  async function retryTraining() {
    if (!lastConfig) {
      stepState = 'idle';
      return;
    }
    errorMessage = null;
    try {
      const start = /** @type {any} */ (await invoke('econ_train_start', { config: lastConfig }));
      handleTrainingStarted(start.task_id);
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    }
  }

  /** Go back to config to change settings */
  function editConfig() {
    errorMessage = null;
    stepState = 'idle';
    resetDownstream(1); // reset model + downstream
  }
</script>

<div class="model-training-step">

  <!-- v2.1.0 (пилот 2026-05-17): stale model banner. Если юзер изменил
       роли колонок в Валидации ПОСЛЕ обучения - текущие diagnostics и
       pickle содержат старую конфигурацию. -->
  {#if stepState === 'trained' && $modelStaleStatus?.stale}
    <div class="stale-banner" role="alert">
      <span class="stale-icon" aria-hidden="true"><TriangleAlert size={18} strokeWidth={1.5} /></span>
      <div class="stale-text">
        <strong>Конфигурация изменилась после обучения.</strong>
        {$modelStaleStatus.reason}
        {#if $modelStaleStatus.diff?.length}
          <ul class="stale-diff">
            {#each $modelStaleStatus.diff as line}<li>{line}</li>{/each}
          </ul>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Success banner (после тренировки) - заметная подсказка что результаты ниже. -->
  {#if stepState === 'trained' && diagnostics}
    {@const m = diagnostics.metrics ?? diagnostics}
    {@const rSq = m.r_squared ?? diagnostics.r_squared}
    {@const mScore = mqs?.score}
    {@const mLabel = mqs?.tierLabel ?? ''}
    <div class="success-banner">
      <span class="success-icon">✅</span>
      <div class="success-text">
        <strong>Модель обучена!</strong>
        {#if mScore != null}
          MQS = <b>{mScore.toFixed(0)}</b> ({mLabel}){#if rSq != null}, R² = <b>{rSq.toFixed(3)}</b>{/if}.
        {/if}
        Результаты ниже.
      </div>
      <button class="btn-scroll-results" onclick={scrollToResults}>↓ Смотреть детали</button>
    </div>
  {/if}

  <!-- ConfigPanel - always rendered (visibility) - A3: async flow via useAsyncTraining prop -->
  <div
    class="config-area"
    data-tour="model-config"
    data-tour-step="run-model"
    class:disabled={stepState === 'training'}
    style={stepState === 'training' ? 'pointer-events:none;opacity:0.5' : ''}
  >
    <ConfigPanel
      {validation}
      useAsyncTraining={true}
      onTrainingStarted={handleTrainingStarted}
      bind:lastConfig
      modelTrained={stepState === 'trained'}
    />
  </div>

  <!-- Training progress (while training) -->
  {#if stepState === 'training' && activeTaskId}
    <TrainingProgress
      taskId={activeTaskId}
      onComplete={handleComplete}
      onError={handleError}
      onStop={handleStop}
      {estimatedSec}
    />
  {/if}

  <!-- Error recovery (C5) -->
  {#if stepState === 'error' && errorMessage}
    <div class="error-banner">
      <span class="error-icon"><TriangleAlert size={16} strokeWidth={1.5} /></span>
      <span class="error-text">{errorMessage}</span>
      <div class="error-actions">
        <button class="btn-retry" onclick={retryTraining}>Повторить</button>
        <button class="btn-edit" onclick={editConfig}>Изменить настройки</button>
      </div>
    </div>
  {/if}

  <!-- Results (after training) - anchor для auto-scroll. -->
  {#if stepState === 'trained' && diagnostics}
    <div id="model-results-anchor"></div>
    <!-- MQS Badge -->
    {#if mqs}
      <div data-tour="model-mqs">
        <MQSBadge diagnostics={diagnostics} />
      </div>
    {/if}

    <!-- Convergence charts -->
    <div data-tour="model-convergence" data-tour-step="results-section">
      <ConvergenceDashboard {diagnostics} />
    </div>

    <!-- E1 (2026-07-03): backtest-витрина «модель vs факт» — проверка на
         удержанной истории. Ключ по picklePath: свежее обучение пересоздаёт
         карточку (перечитывает сохранённую витрину + пометку устаревания). -->
    {#key $modelData?.picklePath}
      <BacktestCard />
    {/key}

    {#if $expertMode}
      <ExpertModelPanel />
    {/if}
  {/if}

  {#if showOnboarding}
    <PipelineOnboarding
      steps={TOURS.model}
      stepKey="model"
      onDone={() => { showOnboarding = false; }}
    />
  {/if}

</div>

<style>
  .model-training-step {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px;
    box-sizing: border-box;
    /* Scroll handled by parent .pipeline-main - no nested overflow to avoid empty scroll area */
  }

  .config-area {
    transition: opacity 0.2s;
  }

  .success-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 18px;
    background: color-mix(in srgb, var(--success) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 35%, transparent);
    border-radius: 10px;
    animation: success-slide-in 0.4s ease-out;
  }

  /* v2.1.0 (пилот 2026-05-17): stale model warning banner. */
  .stale-banner {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 14px 18px;
    margin-bottom: 16px;
    background: color-mix(in srgb, var(--gold, #c9a449) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 35%, transparent);
    border-radius: 10px;
  }
  .stale-icon {
    font-size: 18px;
    line-height: 1.3;
    color: var(--gold, #c9a449);
    flex-shrink: 0;
  }
  .stale-text {
    flex: 1;
    font-size: 13px;
    line-height: 1.45;
    color: var(--text-primary, #e2e8f0);
  }
  .stale-text strong {
    color: var(--gold, #c9a449);
    margin-right: 4px;
  }
  .stale-diff {
    margin: 6px 0 0;
    padding-left: 18px;
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
  }
  @keyframes success-slide-in {
    from { opacity: 0; transform: translateY(-8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .success-icon { font-size: 20px; flex-shrink: 0; }
  .success-text {
    flex: 1;
    font-size: 13px;
    color: var(--text-primary);
    line-height: 1.5;
  }
  .success-text strong { color: var(--success); margin-right: 6px; }
  .success-text b { color: var(--text-primary); font-weight: 700; }
  .btn-scroll-results {
    flex-shrink: 0;
    padding: 7px 14px;
    background: var(--success);
    border: none;
    border-radius: 6px;
    color: white;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-scroll-results:hover { opacity: 0.9; }

  .error-banner {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
    border-radius: 10px;
  }

  .error-icon {
    font-size: 16px;
  }

  .error-text {
    font-size: 13px;
    color: #ef4444;
    line-height: 1.5;
  }

  .error-actions {
    display: flex;
    gap: 8px;
    margin-top: 4px;
  }

  .btn-retry, .btn-edit {
    padding: 7px 16px;
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    transition: opacity 0.15s;
  }

  .btn-retry {
    background: var(--accent-primary, #3b82f6);
    border: none;
    color: white;
    font-weight: 600;
  }

  .btn-edit {
    background: transparent;
    border: 1px solid rgba(255,255,255,0.15);
    color: var(--text-secondary, #94a3b8);
  }

  .btn-retry:hover { opacity: 0.85; }
  .btn-edit:hover { border-color: rgba(255,255,255,0.3); color: var(--text-primary, #e2e8f0); }

  /* v2.1.0 п.5.6: instant success banner appearance */
  @media (prefers-reduced-motion: reduce) {
    .success-banner {
      animation: none;
      opacity: 1;
      transform: none;
    }
  }
</style>
