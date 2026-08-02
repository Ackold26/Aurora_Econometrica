<script>
  /**
   * Async training progress display.
   * A2: sequential setTimeout polling (no setInterval overlap).
   * C4: component stays mounted when user navigates away - polling continues.
   *
   * @component TrainingProgress
   */
  import { onMount, onDestroy } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';

  /** @type {{ taskId: string, onComplete: (result: any) => void, onError: (msg: string) => void, onStop?: () => void, estimatedSec?: number }} */
  let { taskId, onComplete, onError, onStop, estimatedSec = 600 } = $props();

  let stopping = $state(false);
  /** When sampling phase started (epoch seconds from elapsedSec) */
  let samplingStartElapsed = $state(/** @type {number|null} */ (null));

  async function handleStop() {
    if (stopping) return;
    stopping = true;
    active = false;
    try {
      await invoke('econ_train_cancel', { taskId });
    } catch {
      /* ignore - user just wants UI back */
    }
    onStop?.();
  }

  let phase = $state('loading');
  let pct = $state(0);
  let elapsedSec = $state(0);
  let active = $state(true);

  /** Phase labels in Russian @type {Record<string, string>} */
  const PHASE_LABELS = {
    loading: 'Загрузка данных',
    compiling: 'Подготовка модели',
    sampling: 'Обучаем модель – байесовский расчёт',
    diagnostics: 'Проверка качества',
    saving: 'Сохранение результатов',
    complete: 'Готово',
  };

  /** Elapsed time formatted as "Xм Yс" */
  const elapsedLabel = $derived.by(() => {
    const m = Math.floor(elapsedSec / 60);
    const s = elapsedSec % 60;
    return m > 0 ? `${m}м ${s}с` : `${s}с`;
  });

  const phaseLabel = $derived(PHASE_LABELS[phase] || phase);

  /** A2: sequential polling - next poll only after current completes */
  async function poll() {
    if (!active) return;
    try {
      const p = await invoke('econ_train_progress');

      // Guard: sidecar `/progress` возвращает GLOBAL last-task state.
      // Первые poll'ы после mount (500ms) приходят до того как sidecar
      // переключил state на новую task → terminal status предыдущей
      // task показывается как error/done текущей. Игнорируем если task_id
      // не совпадает. Если task_id отсутствует (старая sidecar сборка) -
      // пропускаем только если статус terminal И pct=0 (idle предыдущей).
      const isStaleTerminal = (
        (p.task_id && p.task_id !== taskId) ||
        (!p.task_id && p.pct === 0 && p.status !== 'running')
      );

      if ((p.status === 'done' || (p.pct >= 100 && p.status !== 'running')) && !isStaleTerminal) {
        // Fetch result
        try {
          const result = await invoke('econ_train_result', { taskId });
          active = false;
          pct = 100;
          phase = 'complete';
          onComplete(result);
        } catch (e) {
          active = false;
          onError(String(e));
        }
        return;
      }

      if (p.status === 'error' && !isStaleTerminal) {
        active = false;
        try {
          const result = /** @type {any} */ (await invoke('econ_train_result', { taskId }));
          onError(result?.message || p.error || 'Ошибка обучения модели');
        } catch {
          onError(p.error || 'Ошибка обучения модели');
        }
        return;
      }

      if (p.status === 'cancelled' && !isStaleTerminal) {
        active = false;
        onStop?.();
        return;
      }

      if (p.task_id === taskId || p.status === 'running') {
        const newPhase = p.phase || phase;
        const serverPct = p.pct || pct;
        elapsedSec = Math.round(p.elapsed_sec || 0);

        if (newPhase === 'sampling') {
          if (samplingStartElapsed === null) samplingStartElapsed = elapsedSec;
          const samplingElapsed = elapsedSec - samplingStartElapsed;
          // Budget ~70% of estimatedSec for sampling (rest is loading/compile/diagnostics)
          const samplingBudget = Math.max(60, estimatedSec * 0.7);
          const sampleProgress = Math.min(samplingElapsed / samplingBudget, 0.97);
          // Interpolate from 25 → 85 during sampling
          pct = Math.max(serverPct, Math.round(25 + sampleProgress * 60));
        } else {
          pct = serverPct;
        }
        phase = newPhase;
      }
    } catch {
      // Sidecar temporarily unavailable - retry
    }

    // A2: schedule next poll AFTER this one finishes
    setTimeout(poll, 2000);
  }

  onMount(() => {
    // Rule 2: sync onMount, async in IIFE
    (() => { setTimeout(poll, 500); })();
    return () => { active = false; };
  });

  onDestroy(() => {
    active = false;
  });
</script>

<div class="training-progress">
  <div class="progress-header">
    <span class="progress-title">Обучение модели</span>
    <span class="elapsed">{elapsedLabel}</span>
  </div>

  <!-- Progress bar -->
  <div class="bar-track">
    <div
      class="bar-fill"
      class:pulse={phase === 'sampling'}
      style="width: {pct}%"
    ></div>
  </div>

  <div class="progress-footer">
    <span class="phase-label">{phaseLabel}</span>
    <span class="pct-label">{pct}%</span>
  </div>

  <button class="stop-btn" onclick={handleStop} disabled={stopping}>
    {stopping ? 'Останавливаю...' : '⏹ Остановить обучение'}
  </button>
</div>

<style>
  .training-progress {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px 20px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-radius: 12px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
  }

  .progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .progress-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }

  .elapsed {
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    font-variant-numeric: tabular-nums;
  }

  .bar-track {
    width: 100%;
    height: 8px;
    background: rgba(255,255,255,0.08);
    border-radius: 4px;
    overflow: hidden;
  }

  .bar-fill {
    height: 100%;
    background: var(--accent-primary, #3b82f6);
    border-radius: 4px;
    transition: width 300ms ease-out;
  }

  /* C5: pulse animation during long MCMC sampling phase */
  .bar-fill.pulse {
    animation: pulse-opacity 1.8s ease-in-out infinite;
  }

  @keyframes pulse-opacity {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.55; }
  }

  .progress-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .phase-label {
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
  }

  .pct-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--accent-primary, #3b82f6);
    font-variant-numeric: tabular-nums;
  }

  .stop-btn {
    margin-top: 4px;
    padding: 8px 14px;
    background: transparent;
    border: 1px solid var(--danger, #ef4444);
    color: var(--danger, #ef4444);
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 150ms ease;
  }

  .stop-btn:hover:not(:disabled) {
    background: var(--danger, #ef4444);
    color: #fff;
  }

  .stop-btn:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  /* v2.1.0 п.5.6: static bar fill when motion is reduced */
  @media (prefers-reduced-motion: reduce) {
    .bar-fill.pulse {
      opacity: 0.85;
    }
    .bar-fill {
      transition: none;
    }
  }
</style>
