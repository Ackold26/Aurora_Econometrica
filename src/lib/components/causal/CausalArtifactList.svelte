<script>
  /**
   * CausalArtifactList - history view + cross-method consistency button.
   * @component
   */
  import { invoke } from '@tauri-apps/api/core';

  /**
   * @typedef {{ projectDir?: string, refreshKey?: any, onSelect?: (a: any) => void }} Props
   */
  /** @type {Props} */
  let { projectDir = '', refreshKey, onSelect } = $props();

  /** @type {any[]} */
  let artifacts = $state([]);
  let isLoading = $state(false);
  /** @type {any} */
  let consistency = $state(null);
  let showConsistency = $state(false);

  /** @type {Record<string, string>} */
  const METHOD_NAMES = {
    did_twfe: 'DiD',
    scm_abadie_classic: 'SCM',
    forest_wager_athey: 'Forest',
  };

  async function refresh() {
    if (!projectDir) {
      artifacts = [];
      return;
    }
    isLoading = true;
    try {
      const result = await invoke('econ_causal_list', { projectDir });
      artifacts = result.artifacts || [];
    } catch (e) {
      console.error('list_causal_artifacts failed', e);
      artifacts = [];
    } finally {
      isLoading = false;
    }
  }

  async function checkConsistency() {
    if (!projectDir) return;
    try {
      consistency = await invoke('econ_causal_consistency', { projectDir });
      showConsistency = true;
    } catch (e) {
      console.error('consistency check failed', e);
    }
  }

  $effect(() => {
    refreshKey;
    projectDir;
    refresh();
  });

  /** @param {any} x  @param {number} [dec] */
  function formatNumber(x, dec = 2) {
    if (x === null || x === undefined) return '-';
    if (typeof x !== 'number') return String(x);
    if (Math.abs(x) > 1000) return x.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
    return x.toFixed(dec);
  }

  /** @param {string} v */
  function verdictClass(v) {
    /** @type {Record<string, string>} */
    const map = { agree: 'good', partial: 'warn', disagree: 'bad' };
    return map[v] || 'neutral';
  }
</script>

<div class="artifact-list">
  <header>
    <h3>📚 Артефакты ({artifacts.length})</h3>
    <div class="actions">
      <button onclick={refresh} disabled={isLoading} class="btn-ghost">
        {isLoading ? '...' : 'Обновить'}
      </button>
      {#if artifacts.length >= 2}
        <button onclick={checkConsistency} class="btn-primary">
          Cross-method consistency
        </button>
      {/if}
    </div>
  </header>

  {#if showConsistency && consistency}
    <div class="consistency-banner verdict-{verdictClass(consistency.consistency_verdict)}">
      <header>
        <strong>Triangulation: {consistency.consistency_verdict}</strong>
        <button class="close-btn" onclick={() => (showConsistency = false)}>×</button>
      </header>
      <p>{consistency.recommendation}</p>
      {#if consistency.methods_compared?.length >= 2}
        <p><strong>Compared methods:</strong> {consistency.methods_compared.join(', ')}</p>
        <p><strong>Max divergence:</strong> {formatNumber(consistency.max_relative_divergence * 100, 1)}%</p>
        <details>
          <summary>ATT values</summary>
          <ul>
            {#each Object.entries(consistency.att_values) as [m, v]}
              <li>
                <strong>{METHOD_NAMES[m] || m}:</strong>
                {formatNumber(v.point)}
                [{formatNumber(v.ci_low)}, {formatNumber(v.ci_high)}]
                ({v.ci_method})
              </li>
            {/each}
          </ul>
        </details>
      {/if}
    </div>
  {/if}

  {#if artifacts.length === 0 && !isLoading}
    <p class="empty-state">Артефактов пока нет. Запусти DiD, SCM или Causal Forest выше.</p>
  {:else}
    <ul class="artifacts">
      {#each artifacts as a}
        <button
          class="artifact-row"
          onclick={() => onSelect?.(a)}
          type="button"
        >
          <span class="method-tag method-{(a.method || '').split('_')[0]}">
            {METHOD_NAMES[a.method] || a.method}
          </span>
          <span class="att">
            ATT = <strong>{formatNumber(a.att_point)}</strong>
            <small>[{formatNumber(a.att_ci_low)}, {formatNumber(a.att_ci_high)}]</small>
          </span>
          <span class="ts">{a.created_at?.slice(0, 19).replace('T', ' ') || ''}</span>
        </button>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .artifact-list {
    padding: 1.5rem;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.92));
    border-radius: 12px;
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
  }

  h3 { margin: 0; font-size: 1rem; }

  .actions { display: flex; gap: 0.5rem; }

  .btn-ghost, .btn-primary {
    padding: 0.5rem 0.875rem;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.875rem;
  }

  .btn-ghost { background: transparent; border: 1px solid var(--border-default, #d1d5db); }
  .btn-primary { background: var(--accent, #3b82f6); color: #fff; border: none; }
  .btn-primary:hover { background: var(--accent-hover, #2563eb); }

  .consistency-banner {
    padding: 1rem;
    border-radius: 8px;
    margin-bottom: 1rem;
    font-size: 0.875rem;
  }

  .consistency-banner.verdict-good { background: var(--success-soft, #dcfce7); border-left: 4px solid var(--success, #16a34a); }
  .consistency-banner.verdict-warn { background: var(--warn-soft, #fef3c7); border-left: 4px solid var(--warn, #f59e0b); }
  .consistency-banner.verdict-bad { background: var(--danger-soft, #fee2e2); border-left: 4px solid var(--danger, #dc2626); }
  .consistency-banner.verdict-neutral { background: var(--bg-info-soft, #eff6ff); border-left: 4px solid var(--accent, #3b82f6); }

  .close-btn {
    background: none;
    border: none;
    font-size: 1.5rem;
    cursor: pointer;
    line-height: 1;
    padding: 0;
    color: var(--text-muted);
  }

  .empty-state {
    color: var(--text-muted, #9ca3af);
    font-size: 0.875rem;
    text-align: center;
    padding: 2rem;
  }

  .artifacts {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .artifact-row {
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 1rem;
    align-items: center;
    padding: 0.75rem 1rem;
    background: var(--bg-elevated, #fff);
    border: 1px solid var(--border-default, #e5e7eb);
    border-radius: 6px;
    cursor: pointer;
    text-align: left;
    font-family: inherit;
    font-size: 0.875rem;
  }

  .artifact-row:hover {
    background: var(--bg-hover, #f3f4f6);
    border-color: var(--accent, #3b82f6);
  }

  .method-tag {
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    color: #fff;
  }

  .method-tag.method-did { background: var(--accent, #3b82f6); }
  .method-tag.method-scm { background: var(--success, #16a34a); }
  .method-tag.method-forest { background: var(--purple, #8b5cf6); }

  .att small { color: var(--text-muted); font-weight: normal; }
  .ts { color: var(--text-muted, #9ca3af); font-size: 0.75rem; }
</style>
