<script>
  import { Check, X } from 'lucide-svelte';
  import { PIPELINE_STEPS, pipelineCurrentStep, pipelineStepMeta } from '$lib/project-state.js';
  import { stepIcons } from '$lib/step-icons.js';

  /** @type {{ onNavigate: (step: number) => void }} */
  let { onNavigate } = $props();
</script>

<nav class="pipeline-stepper" aria-label="Шаги pipeline">
  {#each PIPELINE_STEPS as step, i}
    {@const rawMeta = $pipelineStepMeta[i]}
    {@const isCurrent = i === $pipelineCurrentStep}
    {@const clickable = rawMeta.status !== 'locked'}
    <!-- Monotonic visual invariant:
         • i < curStep + не error → 'complete' (✓ галочка) - защищает от race
           где completeStep(0) не срабатывает при load-from-disk
         • i > curStep + был ранее 'complete' (данные на диске остались с прошлой
           итерации) → понижаем до 'ready', чтобы future шаги не "горели"
           зелёным когда пользователь ещё на N. Это даёт чёткий визуальный
           прогресс: пройденные → текущий → будущие.
         • i === curStep или error → keep raw. -->
    {@const effectiveStatus = rawMeta.status === 'error'
      ? 'error'
      : (i < $pipelineCurrentStep)
        ? 'complete'
        : (i > $pipelineCurrentStep && rawMeta.status === 'complete')
          ? 'ready'
          : rawMeta.status}

    {#if i > 0}
      <div class="connector" class:filled={i <= $pipelineCurrentStep || $pipelineStepMeta[i - 1]?.status === 'complete'}></div>
    {/if}

    <button
      class="step-node"
      class:ready={effectiveStatus === 'ready' && !isCurrent}
      class:active={isCurrent}
      class:complete={effectiveStatus === 'complete'}
      class:error={effectiveStatus === 'error'}
      class:locked={effectiveStatus === 'locked'}
      disabled={!clickable}
      onclick={() => clickable && onNavigate(i)}
      aria-current={isCurrent ? 'step' : undefined}
      title={rawMeta.errorMessage || step.labelRu}
    >
      <span class="node-circle">
        {#if effectiveStatus === 'complete'}<Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" />
        {:else if effectiveStatus === 'error'}<X size={14} strokeWidth={1.5} style="vertical-align: -0.15em" />
        {:else if effectiveStatus === 'locked'}-
        {:else}{@const StepIcon = stepIcons[step.id]}<StepIcon size={14} strokeWidth={1.5} style="vertical-align: -0.15em" />{/if}
      </span>
      <span class="node-label">{step.labelRu}</span>
    </button>
  {/each}
</nav>

<style>
  .pipeline-stepper {
    display: flex;
    align-items: center;
    padding: 10px 24px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    overflow-x: auto;
    scrollbar-width: none;
    flex-shrink: 0;
  }
  .pipeline-stepper::-webkit-scrollbar { display: none; }

  .connector {
    flex: 1;
    min-width: 12px;
    height: 2px;
    background: var(--border-subtle, rgba(255,255,255,0.1));
    transition: background 0.25s;
  }
  .connector.filled {
    background: var(--success, #22c55e);
  }

  .step-node {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    background: none;
    border: none;
    cursor: pointer;
    border-radius: 8px;
    transition: background 0.15s;
    flex-shrink: 0;
  }
  .step-node:hover:not(:disabled) {
    background: var(--hover-bg, rgba(255,255,255,0.05));
  }
  .step-node:disabled { cursor: default; }

  .node-circle {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    border: 2px solid var(--border-subtle, rgba(255,255,255,0.15));
    background: var(--bg-surface, rgba(20,23,34,0.7));
    transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
  }
  .node-label {
    font-size: 10px;
    color: var(--text-secondary, #94a3b8);
    white-space: nowrap;
    transition: color 0.2s;
  }

  /* locked */
  .step-node.locked .node-circle,
  .step-node.locked .node-label { opacity: 0.3; }

  /* ready - будущий шаг, доступный для клика, но не активный сейчас.
     Приглушаем чтобы пользователь видел: текущий = яркий, будущие = тусклые. */
  .step-node.ready .node-circle {
    border-color: var(--border-subtle, rgba(255,255,255,0.18));
    opacity: 0.55;
  }
  .step-node.ready .node-label {
    color: var(--text-muted, rgba(148,163,184,0.7));
    opacity: 0.7;
  }
  .step-node.ready:hover:not(:disabled) .node-circle { opacity: 0.9; }
  .step-node.ready:hover:not(:disabled) .node-label { opacity: 1; }

  /* complete (passed step) */
  .step-node.complete .node-circle {
    border-color: var(--success, #22c55e);
    background: color-mix(in srgb, var(--success) 12%, transparent);
    color: var(--success, #22c55e);
  }
  .step-node.complete .node-label { color: var(--success, #22c55e); }

  /* error */
  .step-node.error .node-circle {
    border-color: var(--danger, #ef4444);
    background: color-mix(in srgb, var(--danger) 12%, transparent);
    color: var(--danger, #ef4444);
  }
  .step-node.error .node-label { color: var(--danger, #ef4444); }

  /* active (current) - последним, чтобы перетирал complete/error visual.
     Когда current = ранее пройденный шаг (active+complete), всё равно
     показываем синий active-glow + ✓ галочку (галочка через {#if status==='complete'}). */
  .step-node.active .node-circle {
    border-color: var(--accent-primary, #3b82f6);
    background: color-mix(in srgb, var(--accent-primary) 18%, transparent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-primary) 25%, transparent);
    color: var(--accent-primary, #3b82f6);
  }
  .step-node.active .node-label {
    color: var(--accent-primary, #3b82f6);
    font-weight: var(--font-weight-heading, 600);
    opacity: 1;
  }
  /* Когда current ещё не закончен (active+ready/locked-after-active) - circle всё равно
     яркий, не приглушённый. Override .ready opacity. */
  .step-node.active .node-circle,
  .step-node.active .node-label { opacity: 1; }
</style>
