<script>
  /**
   * Step 2: Model Training.
   * B1: vertical stack — ConfigPanel → TrainingProgress → MQSBadge + ConvergenceDashboard.
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
  } from '$lib/project-state.js';
  import ExpertModelPanel from '$lib/components/pipeline/ExpertModelPanel.svelte';
  import ConfigPanel from '$lib/components/ConfigPanel.svelte';
  import TrainingProgress from '$lib/components/pipeline/TrainingProgress.svelte';
  import ConvergenceDashboard from '$lib/components/pipeline/ConvergenceDashboard.svelte';
  import MQSBadge from '$lib/components/MQSBadge.svelte';

  // ── State ──
  /** @type {'idle' | 'training' | 'trained' | 'error'} */
  let stepState = $state('idle');
  /** @type {string | null} */
  let activeTaskId = $state(null);
  /** @type {string | null} */
  let errorMessage = $state(null);
  /** @type {any | null} */
  let lastConfig = $state(null);

  // Current validation result (from Step 1)
  const validation = $derived(get(validateData)?.result || null);

  // Current model diagnostics (if trained)
  const diagnostics = $derived($modelData?.diagnostics || null);
  const mqs = $derived(diagnostics?.mqs || null);

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
            computeStatus.set('MCMC сэмплирование...');
          } else if (progress.status === 'completed') {
            const result = /** @type {any} */ (await invoke('econ_train_result', { taskId: savedTaskId }));
            handleComplete(result);
          } else {
            localStorage.removeItem(TASK_KEY);
          }
        } catch {
          localStorage.removeItem(TASK_KEY);
        }
      })();
    }
  });

  /**
   * A3: useAsyncTraining prop in ConfigPanel triggers this instead of sync econ_train.
   * @param {string} taskId
   */
  function handleTrainingStarted(taskId) {
    activeTaskId = taskId;
    stepState = 'training';
    isComputing.set(true);
    computeStatus.set('MCMC сэмплирование...');
    try { localStorage.setItem(TASK_KEY, taskId); } catch { /* ignore */ }
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
      });
      stepState = 'trained';
      completeStep(2);
    } else {
      handleError(result.message || 'Ошибка обучения модели');
    }
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

  /** Retry with same config — auto-starts training without manual Run click */
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

  <!-- ConfigPanel — always rendered (visibility) — A3: async flow via useAsyncTraining prop -->
  <div
    class="config-area"
    class:disabled={stepState === 'training'}
    style={stepState === 'training' ? 'pointer-events:none;opacity:0.5' : ''}
  >
    <ConfigPanel
      {validation}
      useAsyncTraining={true}
      onTrainingStarted={handleTrainingStarted}
      bind:lastConfig
    />
  </div>

  <!-- Training progress (while training) -->
  {#if stepState === 'training' && activeTaskId}
    <TrainingProgress
      taskId={activeTaskId}
      onComplete={handleComplete}
      onError={handleError}
    />
  {/if}

  <!-- Error recovery (C5) -->
  {#if stepState === 'error' && errorMessage}
    <div class="error-banner">
      <span class="error-icon">⚠</span>
      <span class="error-text">{errorMessage}</span>
      <div class="error-actions">
        <button class="btn-retry" onclick={retryTraining}>Повторить</button>
        <button class="btn-edit" onclick={editConfig}>Изменить настройки</button>
      </div>
    </div>
  {/if}

  <!-- Results (after training) -->
  {#if stepState === 'trained' && diagnostics}
    <!-- MQS Badge -->
    {#if mqs}
      <MQSBadge diagnostics={diagnostics} />
    {/if}

    <!-- Convergence charts -->
    <ConvergenceDashboard {diagnostics} />

    {#if $expertMode}
      <ExpertModelPanel />
    {/if}
  {/if}

</div>

<style>
  .model-training-step {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px;
    height: 100%;
    box-sizing: border-box;
    overflow-y: visible;
    overflow-x: visible;
  }

  .config-area {
    transition: opacity 0.2s;
  }

  .error-banner {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.25);
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
</style>
