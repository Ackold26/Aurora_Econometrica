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
  import { theme, toggleTheme } from '$lib/store.js';
  import {
    pipelineCurrentStep,
    pipelineStepMeta,
    activeProjectId,
    activeProject,
    expertMode,
    sidecarHealthy,
    sidecarStatus,
    isComputing,
    computeStatus,
    loadPipelineForProject,
    validateData,
    importData,
  } from '$lib/project-state.js';
  import PipelineStepper from '$lib/components/pipeline/PipelineStepper.svelte';
  import InsightsPanel from '$lib/components/pipeline/InsightsPanel.svelte';
  import ProjectSelector from '$lib/components/ProjectSelector.svelte';

  let { children } = $props();

  // C1: Pipeline guard — econometrica only
  const isEconometrica = $derived($productType === 'econometrica');

  let userCollapsed = $state(false); // явное намерение пользователя
  let windowWidth = $state(typeof window !== 'undefined' ? window.innerWidth : 1200);

  // C4: Auto-collapse on small screens; on large — уважаем userCollapsed
  const insightsCollapsed = $derived(windowWidth < 1100 ? true : userCollapsed);

  function toggleInsights() {
    if (windowWidth >= 1100) userCollapsed = !userCollapsed;
  }

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

    // Crash recovery: if training was in progress but sidecar restarted
    const savedTask = typeof localStorage !== 'undefined' ? localStorage.getItem('econ-training-task') : null;
    if (savedTask) {
      try {
        const progress = /** @type {any} */ (await invoke('econ_train_progress'));
        if (progress.status !== 'running') {
          // Sidecar lost state — clean up stale task
          localStorage.removeItem('econ-training-task');
        }
      } catch {
        localStorage.removeItem('econ-training-task');
      }
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

    // Check for ?new=1 — user clicked "Новый проект в Pipeline" on home
    const forceNew = typeof window !== 'undefined'
      && new URLSearchParams(window.location.search).get('new') === '1';

    if (forceNew) {
      // Clean slate: ignore backend-stored active project, stay at step 0
      activeProjectId.set(null);
      activeProject.set(null);
      pipelineCurrentStep.set(0);
    } else if (!$activeProjectId) {
      // Restore active project from backend if not already set
      (async () => {
        try {
          const id = /** @type {string|null} */ (await invoke('project_get_active'));
          if (id) {
            activeProjectId.set(id);
            const info = await invoke('project_get', { projectId: id });
            activeProject.set(info);
            loadPipelineForProject(id);
          }
        } catch { /* no active project yet */ }
      })();
    } else {
      // Load pipeline metadata for current project (A4: data never persisted)
      loadPipelineForProject($activeProjectId);
    }

    // C5: initialise sidecar
    initSidecar();

    return () => window.removeEventListener('resize', onResize);
  });

  const canGoNext = $derived(
    $pipelineCurrentStep < 5 && $pipelineStepMeta[$pipelineCurrentStep + 1]?.status !== 'locked'
  );

  // Objective overlay is open: step 1 (validate) with no validation result yet
  const isObjectiveOverlay = $derived(
    $pipelineCurrentStep === 1 && !$validateData?.result
  );

  // Hide insights panel when there's no data to comment on yet
  const hideInsightsPanel = $derived(
    isObjectiveOverlay ||
    ($pipelineCurrentStep === 0 && !$importData?.file)
  );
</script>

{#if isEconometrica}
  <div class="pipeline-shell">
    <!-- Stepper header with project selector -->
    <div class="pipeline-header">
      <!-- Project selector visible only on Import step (where it's relevant) -->
      {#if $pipelineCurrentStep === 0}
        <div class="project-area">
          <ProjectSelector />
        </div>
      {:else}
        <!-- Keep header layout stable but show a read-only chip after import -->
        <div class="project-area">
          {#if $activeProject}
            <span class="project-chip" title="Активный проект — переключение доступно на шаге «Импорт»">
              📊 {$activeProject.name}
            </span>
          {/if}
        </div>
      {/if}
      <PipelineStepper onNavigate={handleNavigate} />
      <div class="header-right">
        {#if $pipelineCurrentStep >= 1 && !isObjectiveOverlay}
          <button
            class="mode-toggle"
            class:expert={$expertMode}
            onclick={() => expertMode.update(v => !v)}
            title={$expertMode ? 'Переключить в режим маркетолога' : 'Переключить в экспертный режим'}
          >
            {$expertMode ? 'Эксперт' : 'Маркетолог'}
          </button>
        {/if}
        <button class="header-icon-btn" title="Переключить тему" onclick={toggleTheme}>
          {#if $theme === 'dark'}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          {:else if $theme === 'light'}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
          {:else}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke-linecap="round" stroke-width="2"><path d="M2 19 A10 10 0 0 1 22 19" stroke="#e74c3c"/><path d="M4.5 19 A7.5 7.5 0 0 1 19.5 19" stroke="#f39c12"/><path d="M7 19 A5 5 0 0 1 17 19" stroke="#2ecc71"/><path d="M9.5 19 A2.5 2.5 0 0 1 14.5 19" stroke="#3498db"/></svg>
          {/if}
        </button>
        <a href="/settings" class="header-icon-btn" title="Настройки">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </a>
      </div>
    </div>

    <!-- Body: main content + insights panel -->
    <div class="pipeline-body">
      <main class="pipeline-main">
        {@render children()}
      </main>

      <!-- InsightsPanel: shown only when there's data to comment on (not on empty Import, not on Objective overlay) -->
      {#if !hideInsightsPanel}
        <InsightsPanel
          collapsed={insightsCollapsed}
          onToggle={toggleInsights}
        />
      {/if}
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

  .pipeline-header {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 16px;
    flex-shrink: 0;
  }
  .pipeline-header > :global(*:nth-child(1)) { justify-self: start; }
  .pipeline-header > :global(*:nth-child(2)) { justify-self: center; }
  .pipeline-header > :global(*:nth-child(3)) { justify-self: end; }

  .project-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    font-size: 12px;
    color: var(--text-secondary);
    background: var(--bg-surface-quiet);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm, 6px);
    cursor: default;
    white-space: nowrap;
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .project-area {
    flex-shrink: 0;
    min-width: 260px;
    max-width: 360px;
    padding: 8px 0 8px 16px;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-right: 16px;
    flex-shrink: 0;
  }

  .header-icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    color: var(--text-muted, #94a3b8);
    border-radius: var(--radius-sm, 6px);
    transition: all 0.15s;
    text-decoration: none;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
  }
  .header-icon-btn:hover {
    color: var(--text-primary, #e2e8f0);
    background: var(--bg-tertiary, rgba(255,255,255,0.06));
  }

  .mode-toggle {
    padding: 5px 14px;
    min-width: 100px;
    text-align: center;
    border-radius: 14px;
    border: 1px solid color-mix(in srgb, var(--accent-primary) 35%, transparent);
    background: color-mix(in srgb, var(--accent-primary) 10%, transparent);
    color: #93c5fd;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.03em;
    cursor: pointer;
    transition: all 0.25s;
  }
  .mode-toggle:hover { background: color-mix(in srgb, var(--accent-primary) 18%, transparent); }
  .mode-toggle.expert {
    background: color-mix(in srgb, var(--danger) 12%, transparent);
    border-color: color-mix(in srgb, var(--danger) 40%, transparent);
    color: #fca5a5;
  }
  .mode-toggle.expert:hover { background: color-mix(in srgb, var(--danger) 20%, transparent); }

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
  .nav-btn:disabled { opacity: var(--disabled-opacity, 0.32); cursor: not-allowed; }

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
    box-shadow: 0 0 5px color-mix(in srgb, var(--success) 40%, transparent);
  }
  .sidecar-status.errored .sidecar-dot {
    background: var(--error, #ef4444);
  }
  .sidecar-label {
    font-size: 11px;
    color: var(--text-muted);
    white-space: nowrap;
  }
</style>
