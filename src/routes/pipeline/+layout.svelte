<script>
  /**
   * Pipeline shell layout.
   * C1: Guard — only accessible for econometrica product type.
   * C4: InsightsPanel width clamp(240px, 22%, 360px), auto-collapse < 1100px.
   * C5: Sidecar status indicator in footer.
   */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { invoke } from '@tauri-apps/api/core';
  import { productType } from '$lib/creative-store.js';
  import {
    pipelineCurrentStep,
    pipelineStepMeta,
    activeProjectId,
    activeProject,
    sidecarHealthy,
    sidecarStatus,
    isComputing,
    computeStatus,
    loadPipelineForProject,
  } from '$lib/project-state.js';
  import PipelineStepper from '$lib/components/pipeline/PipelineStepper.svelte';
  import InsightsPanel from '$lib/components/pipeline/InsightsPanel.svelte';

  let { children } = $props();

  // C1: Pipeline guard — econometrica only
  const isEconometrica = $derived($productType === 'econometrica');

  let insightsCollapsed = $state(false);
  let windowWidth = $state(typeof window !== 'undefined' ? window.innerWidth : 1200);

  // C4: Auto-collapse InsightsPanel when viewport < 1100px
  $effect(() => {
    if (windowWidth < 1100 && !insightsCollapsed) insightsCollapsed = true;
    if (windowWidth >= 1100 && insightsCollapsed) insightsCollapsed = false;
  });

  /** @param {number} step */
  function handleNavigate(step) {
    const meta = $pipelineStepMeta[step];
    if (!meta || meta.status === 'locked') return;
    pipelineCurrentStep.set(step);
  }

  function goBack() {
    const prev = $pipelineCurrentStep - 1;
    if (prev >= 0) pipelineCurrentStep.set(prev);
  }

  function goNext() {
    const next = $pipelineCurrentStep + 1;
    if (next < 6 && $pipelineStepMeta[next]?.status !== 'locked') {
      pipelineCurrentStep.set(next);
    }
  }

  // C5: Start sidecar and track its status in footer
  async function initSidecar() {
    sidecarStatus.set('Запуск...');
    try {
      await invoke('econ_sidecar_wait_ready', { timeoutMs: 15000 });
      sidecarHealthy.set(true);
      sidecarStatus.set('Готов');
    } catch (/** @type {any} */ err) {
      sidecarHealthy.set(false);
      sidecarStatus.set(`Ошибка: ${err}`);
    }
  }

  onMount(() => {
    // C1: redirect if not econometrica
    if (!isEconometrica) {
      goto('/');
      return;
    }

    // C4: resize handler
    function onResize() { windowWidth = window.innerWidth; }
    window.addEventListener('resize', onResize, { passive: true });

    // Load pipeline metadata for current project (A4: data never persisted)
    loadPipelineForProject($activeProjectId);

    // C5: initialise sidecar
    initSidecar();

    return () => window.removeEventListener('resize', onResize);
  });

  const canGoNext = $derived(
    $pipelineCurrentStep < 5 && $pipelineStepMeta[$pipelineCurrentStep + 1]?.status !== 'locked'
  );
</script>

{#if isEconometrica}
  <div class="pipeline-shell">
    <!-- Stepper header -->
    <PipelineStepper onNavigate={handleNavigate} />

    <!-- Body: main content + insights panel -->
    <div class="pipeline-body">
      <main class="pipeline-main">
        {@render children()}
      </main>

      <!-- C4: InsightsPanel with clamp(240px, 22%, 360px) -->
      <InsightsPanel
        collapsed={insightsCollapsed}
        onToggle={() => insightsCollapsed = !insightsCollapsed}
      />
    </div>

    <!-- Footer: navigation + C5 sidecar status -->
    <div class="pipeline-footer">
      <button
        class="nav-btn secondary"
        disabled={$pipelineCurrentStep === 0}
        onclick={goBack}
      >
        ◀ Назад
      </button>

      <div class="footer-center">
        {#if $isComputing}
          <span class="computing-indicator" role="status">
            ⟳ {$computeStatus || 'Обработка...'}
          </span>
        {/if}
      </div>

      <button
        class="nav-btn primary"
        disabled={!canGoNext}
        onclick={goNext}
      >
        Далее ▶
      </button>

      <!-- C5: Sidecar status dot -->
      <div
        class="sidecar-status"
        class:healthy={$sidecarHealthy}
        class:errored={!$sidecarHealthy && $sidecarStatus !== 'Запуск...'}
        title="Python sidecar: {$sidecarStatus}"
      >
        <span class="sidecar-dot"></span>
        <span class="sidecar-label">Python: {$sidecarStatus || '...'}</span>
      </div>
    </div>
  </div>
{/if}

<style>
  .pipeline-shell {
    display: flex;
    flex-direction: column;
    /* CLAUDE.md Rule 13: 100%, not 100vh */
    height: 100%;
    overflow: hidden;
  }

  .pipeline-body {
    flex: 1;
    display: flex;
    overflow: hidden;
    min-height: 0;
  }

  .pipeline-main {
    flex: 1;
    overflow: auto;
    position: relative;
    min-width: 0;
  }

  .pipeline-footer {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 24px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    flex-shrink: 0;
  }

  .footer-center {
    flex: 1;
    display: flex;
    justify-content: center;
    min-width: 0;
  }

  .computing-indicator {
    font-size: 12px;
    color: var(--accent-primary, #3b82f6);
    animation: pulse 1.5s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.45; }
  }

  .nav-btn {
    padding: 7px 18px;
    border-radius: 8px;
    border: none;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s;
    flex-shrink: 0;
  }
  .nav-btn.primary {
    background: var(--accent-primary, #3b82f6);
    color: #fff;
  }
  .nav-btn.primary:hover:not(:disabled) { background: #2563eb; }
  .nav-btn.secondary {
    background: rgba(255,255,255,0.07);
    color: var(--text-secondary, #94a3b8);
  }
  .nav-btn.secondary:hover:not(:disabled) { background: rgba(255,255,255,0.12); }
  .nav-btn:disabled { opacity: 0.32; cursor: not-allowed; }

  /* C5: Sidecar status */
  .sidecar-status {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-shrink: 0;
    margin-left: auto;
  }
  .sidecar-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: rgba(148,163,184,0.35);
    transition: background 0.3s, box-shadow 0.3s;
    flex-shrink: 0;
  }
  .sidecar-status.healthy .sidecar-dot {
    background: var(--success, #22c55e);
    box-shadow: 0 0 5px rgba(34,197,94,0.4);
  }
  .sidecar-status.errored .sidecar-dot {
    background: var(--error, #ef4444);
  }
  .sidecar-label {
    font-size: 11px;
    color: rgba(148,163,184,0.55);
    white-space: nowrap;
  }
</style>
