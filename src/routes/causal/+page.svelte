<script>
  /**
   * Causal - Sprint 3 Pharma Causal cabinet route.
   *
   * Layout:
   *   - Sticky header: title + project context + v1.0.14 disclosure banner
   *   - Left: CausalMethodForm (DiD / SCM / Forest selector + dynamic form)
   *   - Right: latest CausalResultCard (если запущено)
   *   - Bottom: CausalArtifactList (history + cross-method consistency)
   *
   * Все эти 3 компонента уже сами по себе пишут к sidecar через invoke;
   * route - простой контейнер + project context.
   */
  import { TriangleAlert } from 'lucide-svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import CausalMethodForm from '$lib/components/causal/CausalMethodForm.svelte';
  import CausalResultCard from '$lib/components/causal/CausalResultCard.svelte';
  import CausalArtifactList from '$lib/components/causal/CausalArtifactList.svelte';
  import { activeProjectId } from '$lib/project-state.js';

  let projectDir = $state('');
  /** @type {'did'|'scm'|'forest'} */
  let method = $state('did');
  /** @type {any} */
  let latestResult = $state(null);
  let refreshKey = $state(0);

  // Resolve project_dir from activeProjectId via Rust command
  $effect(() => {
    const pid = $activeProjectId;
    if (!pid) {
      projectDir = '';
      return;
    }
    invoke('project_get_dir', { projectId: pid })
      .then((dir) => { projectDir = String(dir); })
      .catch((e) => { console.error('project_get_dir failed', e); projectDir = ''; });
  });

  /** @param {any} result */
  function onResult(result) {
    latestResult = result;
    refreshKey++; // trigger artifact list refresh
  }

  /** @param {any} artifact */
  function onSelectArtifact(artifact) {
    // Load full artifact JSON via fetch - for now just show summary
    // (UI can be extended to load full payload via project API)
    latestResult = {
      status: 'ok',
      method: artifact.method,
      att: {
        point: artifact.att_point,
        ci_low: artifact.att_ci_low,
        ci_high: artifact.att_ci_high,
        ci_method: artifact.ci_method,
        confidence: 0.9,
      },
      diagnostics: { _from_history: true },
      honest_disclosure: {},
      created_at: artifact.created_at,
      artifact_path: artifact.path,
    };
  }
</script>

<div class="causal-page">
  <header class="page-header">
    <a href="/" class="header-logo-link" title="На главную" aria-label="Aurora AI – на главную">
      <img src="/logo-horizon.png" alt="Aurora AI" class="header-logo" />
    </a>
    <div class="title-row">
      <h1>Причинность</h1>
      <span class="version-tag">Sprint 3 backend M0-M4 · v1.0.14-rc</span>
    </div>
    <p class="subtitle">
      Causal inference поверх MMM: <strong>DiD</strong> для geo-holdout tests,
      <strong>SCM</strong> для post-hoc holdout markets, <strong>Causal Forest</strong>
      для heterogeneous treatment effects по сегментам.
    </p>

    <div class="caveat-banner">
      <strong><TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> v1.0.14 honest caveat:</strong> backend validated на synthetic data + DGP-controlled
      ground truth recovery. Real-customer geo-disaggregated validation запланирован в v1.0.15
      после получения Materia Medica regional data + treatment markers. Используй с осторожностью
      на real client data - assumptions (parallel-trends, convex-hull, overlap) проверяй вручную
      через honest_disclosure блок ниже.
    </div>

    {#if !projectDir}
      <div class="warn-banner">
        <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Не выбран активный project. Перейди в раздел «Проекты» и выбери проект перед запуском
        causal методов.
      </div>
    {:else}
      <p class="project-info">📁 Активный project: <code>{projectDir}</code></p>
    {/if}
  </header>

  <main class="page-grid">
    <section class="form-section">
      <CausalMethodForm bind:method {projectDir} {onResult} />
    </section>

    <section class="result-section">
      {#if latestResult}
        <CausalResultCard result={latestResult} />
      {:else}
        <div class="placeholder">
          <p>Результат появится здесь после запуска метода.</p>
          <p class="hint">Выбери метод слева, заполни форму, нажми «Запустить».</p>
        </div>
      {/if}
    </section>
  </main>

  <footer class="history-section">
    <CausalArtifactList {projectDir} {refreshKey} onSelect={onSelectArtifact} />
  </footer>
</div>

<style>
  .causal-page {
    max-width: 1400px;
    margin: 0 auto;
    padding: 1.5rem 2rem 3rem;
    height: 100%;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .page-header h1 {
    margin: 0 0 0.25rem;
    font-size: 1.75rem;
    font-weight: 600;
  }

  .title-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }

  .header-logo-link {
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    line-height: 0;
    margin-bottom: 14px;
  }
  .header-logo {
    height: 48px;
    width: auto;
  }

  .version-tag {
    font-size: 0.75rem;
    padding: 0.25rem 0.5rem;
    background: var(--bg-info-soft, #eff6ff);
    color: var(--accent, #3b82f6);
    border-radius: 4px;
  }

  .subtitle {
    margin: 0 0 1rem;
    color: var(--text-secondary, #4b5563);
    font-size: 0.9375rem;
    line-height: 1.5;
  }

  .caveat-banner {
    padding: 1rem 1.25rem;
    background: var(--warn-soft, #fef3c7);
    border-left: 4px solid var(--warn, #f59e0b);
    border-radius: 6px;
    font-size: 0.875rem;
    line-height: 1.5;
    color: var(--text-primary);
    margin-bottom: 1rem;
  }

  .warn-banner {
    padding: 0.75rem 1rem;
    background: var(--danger-soft, #fee2e2);
    color: var(--danger, #dc2626);
    border-radius: 6px;
    font-size: 0.875rem;
  }

  .project-info {
    margin: 0;
    font-size: 0.8125rem;
    color: var(--text-muted, #6b7280);
  }

  .project-info code {
    background: var(--bg-elevated, #f9fafb);
    padding: 0.125rem 0.375rem;
    border-radius: 3px;
    font-size: 0.75rem;
  }

  .page-grid {
    display: grid;
    grid-template-columns: minmax(360px, 1fr) 1fr;
    gap: 1.5rem;
    align-items: start;
  }

  @media (max-width: 1024px) {
    .page-grid { grid-template-columns: 1fr; }
  }

  .placeholder {
    padding: 3rem 2rem;
    text-align: center;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.5));
    border-radius: 12px;
    border: 2px dashed var(--border-default, #d1d5db);
    color: var(--text-muted, #9ca3af);
  }

  .placeholder p { margin: 0.5rem 0; }
  .hint { font-size: 0.875rem; }
</style>
