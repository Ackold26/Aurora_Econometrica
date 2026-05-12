<script>
  import HintBubble from './HintBubble.svelte';
  import WorkflowGraph from './WorkflowGraph.svelte';
  import { HINTS } from '$lib/hints.js';

  /** @type {{steps: Array<any>, cabinets?: Array<{id: string, name: string, icon: string, color: string}>, onStepClick?: (step: any) => void, onAddStep?: (afterId: string|null) => void, onRemoveStep?: (stepId: string) => void, isRoot?: boolean}} */
  let { steps = [], cabinets = [], onStepClick, onAddStep, onRemoveStep, isRoot = false } = $props();

  /**
   * Get cabinet metadata by id from the cabinets prop.
   * Falls back to a neutral default if not found.
   * @param {string} cabinetId
   */
  function getCabinetMeta(cabinetId) {
    return cabinets.find(c => c.id === cabinetId) || { name: cabinetId, icon: '\u25C6', color: '#666' };
  }

  // Show structural hints only at root level
  let hasParallel = $derived(isRoot && steps.some(s => s.type === 'parallel'));
  let hasLoop = $derived(isRoot && steps.some(s => s.type === 'loop'));

  const statusIcon = { idle: '\u25CB', running: '\u25D0', done: '\u25CF', error: '\u2715' };
  const statusColor = {
    idle: 'var(--text-muted)',
    running: 'var(--accent-primary)',
    done: 'var(--success)',
    error: 'var(--danger)',
  };
</script>

<div class="wf-graph">
  {#each steps as step, i (step.id)}
    {#if step.type === 'single'}
      {@const meta = getCabinetMeta(step.cabinet_id)}
      <div
        class="wf-step"
        class:wf-step--running={step.status === 'running'}
        class:wf-step--done={step.status === 'done'}
        class:wf-step--error={step.status === 'error'}
        style="--step-color: {meta.color}"
        role="button"
        tabindex="0"
        onclick={() => onStepClick?.(step)}
        onkeydown={(e) => e.key === 'Enter' && onStepClick?.(step)}
      >
        <div class="wf-step-accent"></div>
        <div class="wf-step-body">
          <span class="wf-step-status" style="color: {/** @type {Record<string, string>} */(statusColor)[step.status || 'idle']}">{/** @type {Record<string, string>} */(statusIcon)[step.status || 'idle']}</span>
          <span class="wf-step-icon">{meta.icon}</span>
          <div class="wf-step-info">
            <span class="wf-step-label">{step.label}</span>
            <span class="wf-step-cabinet">{meta.name}{step.command ? ` ${step.command}` : ''}</span>
          </div>
          {#if onRemoveStep}
            <button class="wf-step-remove" onclick={(e) => { e.stopPropagation(); onRemoveStep?.(step.id); }} title="Удалить">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
            </button>
          {/if}
        </div>
      </div>

    {:else if step.type === 'parallel'}
      <div class="wf-parallel-container">
        {#if hasParallel}
          <HintBubble hint={HINTS['wf-parallel-explain']} />
        {/if}
        <div class="wf-parallel-label">Параллельно</div>
        <div class="wf-parallel">
          {#each step.branches as branch, bi}
            <div class="wf-branch">
              <WorkflowGraph steps={branch} {cabinets} {onStepClick} {onRemoveStep} />
            </div>
          {/each}
        </div>
      </div>

    {:else if step.type === 'loop'}
      <div class="wf-loop-container">
        {#if hasLoop}
          <HintBubble hint={HINTS['wf-loop-explain']} />
        {/if}
        <div class="wf-loop-label">
          <span class="wf-loop-icon">\u21BA</span>
          Цикл (макс. {step.max_iterations} итераций)
        </div>
        <div class="wf-loop-body">
          <div class="wf-loop-section">
            <span class="wf-loop-section-label">Работа</span>
            <WorkflowGraph steps={step.body} {cabinets} {onStepClick} {onRemoveStep} />
          </div>
          <div class="wf-loop-arrow">\u2193 проверка \u2193</div>
          <div class="wf-loop-section">
            <span class="wf-loop-section-label">Ревью</span>
            <WorkflowGraph steps={step.review} {cabinets} {onStepClick} {onRemoveStep} />
          </div>
        </div>
      </div>
    {/if}

    <!-- Connector + Add button between steps -->
    {#if i < steps.length - 1}
      <div class="wf-connector-group">
        <div class="wf-connector"></div>
        {#if onAddStep}
          <button class="wf-add-btn" onclick={() => onAddStep?.(step.id)} title="Добавить шаг">+</button>
        {/if}
      </div>
    {/if}
  {/each}

  <!-- Add at end - always visible -->
  {#if onAddStep}
    <div class="wf-connector-group">
      {#if steps.length > 0}
        <div class="wf-connector"></div>
      {/if}
      <button class="wf-add-btn wf-add-btn--visible" onclick={() => onAddStep?.(steps[steps.length - 1]?.id || null)} title="Добавить шаг">+</button>
    </div>
  {/if}
</div>

<style>
  .wf-graph {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0;
  }

  /* ── Single Step ── */

  .wf-step {
    width: 100%;
    max-width: 400px;
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    -webkit-backdrop-filter: var(--blur-quiet);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.07));
    border-radius: var(--radius-lg);
    overflow: hidden;
    cursor: pointer;
    text-align: left;
    color: var(--text-primary);
    transition: all var(--transition-fast);
    position: relative;
  }

  .wf-step:hover {
    border-color: var(--border);
    transform: translateY(-1px);
    box-shadow: var(--shadow-card);
  }

  .wf-step--running {
    border-color: var(--step-color);
    box-shadow: 0 0 12px rgba(var(--step-color), 0.2);
    animation: step-pulse 2s ease-in-out infinite;
  }

  .wf-step--done {
    border-color: var(--success);
  }

  .wf-step--error {
    border-color: var(--danger);
  }

  @keyframes step-pulse {
    0%, 100% { box-shadow: 0 0 0 0 var(--accent-glow-strong); }
    50% { box-shadow: var(--shadow-glow); }
  }

  .wf-step-accent {
    height: 3px;
    background: var(--step-color);
  }

  .wf-step-body {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
  }

  .wf-step-status {
    font-size: 14px;
    flex-shrink: 0;
  }

  .wf-step-icon {
    font-size: 18px;
    flex-shrink: 0;
  }

  .wf-step-info {
    flex: 1;
    min-width: 0;
  }

  .wf-step-label {
    display: block;
    font-size: 13px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .wf-step-cabinet {
    display: block;
    font-size: 11px;
    color: var(--text-secondary);
    margin-top: 1px;
  }

  .wf-step-remove {
    padding: 4px;
    background: transparent;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: 4px;
    opacity: 0;
    transition: all 0.15s;
    flex-shrink: 0;
  }

  .wf-step:hover .wf-step-remove {
    opacity: 1;
  }

  .wf-step-remove:hover {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
  }

  /* ── Connector ── */

  .wf-connector-group {
    display: flex;
    flex-direction: column;
    align-items: center;
    position: relative;
  }

  .wf-connector {
    width: 2px;
    height: 20px;
    background: var(--border);
  }

  .wf-add-btn {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 1px dashed var(--border);
    background: transparent;
    color: var(--text-muted);
    font-size: 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
    opacity: 0;
  }

  .wf-connector-group:hover .wf-add-btn {
    opacity: 1;
  }

  .wf-add-btn:hover {
    border-color: var(--accent-primary);
    color: var(--accent-primary);
    background: var(--accent-glow);
  }

  .wf-add-btn--visible {
    opacity: 0.5;
  }

  .wf-add-btn--visible:hover {
    opacity: 1;
  }

  /* ── Parallel ── */

  .wf-parallel-container {
    width: 100%;
    max-width: 600px;
  }

  .wf-parallel-label {
    font-size: 11px;
    color: var(--text-muted);
    text-align: center;
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .wf-parallel {
    display: flex;
    gap: 16px;
    padding: 12px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-lg);
    background: var(--hover-bg);
  }

  .wf-branch {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  /* ── Loop ── */

  .wf-loop-container {
    width: 100%;
    max-width: 440px;
  }

  .wf-loop-label {
    font-size: 12px;
    color: var(--accent-primary);
    font-weight: 500;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .wf-loop-icon {
    font-size: 16px;
  }

  .wf-loop-body {
    border-left: 2px dashed var(--accent-primary);
    padding-left: 16px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }

  .wf-loop-section {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .wf-loop-section-label {
    font-size: 10px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
  }

  .wf-loop-arrow {
    font-size: 11px;
    color: var(--text-muted);
    padding: 4px 0;
  }
</style>
