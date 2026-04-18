<script>
  import { PIPELINE_STEPS, pipelineCurrentStep, pipelineStepMeta } from '$lib/project-state.js';

  /** @type {{ onNavigate: (step: number) => void }} */
  let { onNavigate } = $props();
</script>

<nav class="pipeline-stepper" aria-label="Шаги pipeline">
  {#each PIPELINE_STEPS as step, i}
    {@const meta = $pipelineStepMeta[i]}
    {@const isCurrent = i === $pipelineCurrentStep}
    {@const clickable = meta.status !== 'locked'}

    {#if i > 0}
      <div class="connector" class:filled={$pipelineStepMeta[i - 1]?.status === 'complete'}></div>
    {/if}

    <button
      class="step-node"
      class:ready={meta.status === 'ready' && !isCurrent}
      class:active={isCurrent}
      class:complete={meta.status === 'complete'}
      class:error={meta.status === 'error'}
      class:locked={meta.status === 'locked'}
      disabled={!clickable}
      onclick={() => clickable && onNavigate(i)}
      aria-current={isCurrent ? 'step' : undefined}
      title={meta.errorMessage || step.labelRu}
    >
      <span class="node-circle">
        {#if meta.status === 'complete'}✓
        {:else if meta.status === 'error'}✕
        {:else if meta.status === 'locked'}—
        {:else}{step.icon}{/if}
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

  /* ready */
  .step-node.ready .node-circle { border-color: color-mix(in srgb, var(--accent-primary) 50%, transparent); }
  .step-node.ready .node-label { color: var(--text-primary, #e2e8f0); }

  /* active (current) */
  .step-node.active .node-circle {
    border-color: var(--accent-primary, #3b82f6);
    background: color-mix(in srgb, var(--accent-primary) 15%, transparent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-primary) 20%, transparent);
  }
  .step-node.active .node-label {
    color: var(--accent-primary, #3b82f6);
    font-weight: var(--font-weight-heading, 600);
  }

  /* complete */
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
</style>
