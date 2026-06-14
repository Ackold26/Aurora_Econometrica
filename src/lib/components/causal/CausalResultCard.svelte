<script>
  /**
   * CausalResultCard - отображает ATT + CI + diagnostics + honest_disclosure.
   * Universal - works для DiD/SCM/Forest output (uniform schema per ADR §4.3).
   * @component
   */
  import { Check, TriangleAlert, Search, ChartColumn } from 'lucide-svelte';

  /**
   * @typedef {{ result: any }} Props
   */
  /** @type {Props} */
  const { result } = $props();

  /** @type {Record<string, string>} */
  const METHOD_NAMES = {
    did_twfe: 'DiD (TWFE)',
    scm_abadie_classic: 'SCM (Abadie classic)',
    forest_wager_athey: 'Causal Forest (Wager-Athey)',
  };

  const att = $derived(result?.att);
  const diag = $derived(result?.diagnostics ?? {});
  const disclosure = $derived(result?.honest_disclosure ?? {});

  /** @param {any} x  @param {number} [dec] */
  function formatNumber(x, dec = 2) {
    if (x === null || x === undefined) return '-';
    if (typeof x !== 'number') return String(x);
    if (Math.abs(x) > 1000) return x.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
    return x.toFixed(dec);
  }

  /** @param {any} att */
  function attTone(att) {
    if (!att) return 'neutral';
    if (att.ci_low > 0 && att.ci_high > 0) return 'positive';
    if (att.ci_low < 0 && att.ci_high < 0) return 'negative';
    return 'inconclusive';
  }
</script>

{#if result?.status === 'error'}
  <div class="error-card">
    <h3>❌ Ошибка</h3>
    <p><strong>Code:</strong> {result.error_code || 'UNKNOWN'}</p>
    <p>{result.message}</p>
  </div>
{:else if result?.status === 'ok'}
  <div class="result-card">
    <header>
      <h3>{METHOD_NAMES[result.method] || result.method}</h3>
      <span class="ts">{result.created_at?.slice(0, 19).replace('T', ' ') || ''}</span>
    </header>

    <!-- ATT block -->
    <div class="att-block tone-{attTone(att)}">
      <div class="att-label">Average Treatment Effect (ATT)</div>
      <div class="att-point">{formatNumber(att?.point)}</div>
      <div class="att-ci">
        {Math.round((att?.confidence ?? 0.9) * 100)}% CI:
        <span class="ci-bracket">
          [{formatNumber(att?.ci_low)}, {formatNumber(att?.ci_high)}]
        </span>
        <span class="ci-method">({att?.ci_method})</span>
      </div>
      {#if att && att.ci_low > 0 && att.ci_high > 0}
        <div class="att-verdict positive"><Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Эффект статистически значим (CI больше 0)</div>
      {:else if att && att.ci_low < 0 && att.ci_high < 0}
        <div class="att-verdict negative"><TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Эффект отрицательный (CI меньше 0)</div>
      {:else}
        <div class="att-verdict inconclusive">- Эффект неоднозначен (CI пересекает 0)</div>
      {/if}
    </div>

    <!-- Honest disclosure -->
    {#if disclosure?.method}
      <details open class="disclosure-block">
        <summary><Search size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Honest disclosure ({disclosure.method})</summary>
        <div class="disclosure-content">
          {#if disclosure.assumptions?.length}
            <div class="disclosure-section">
              <strong>Assumptions:</strong>
              <ul>{#each disclosure.assumptions as a}<li>{a}</li>{/each}</ul>
            </div>
          {/if}

          {#if disclosure.diagnostics_passed?.length}
            <div class="disclosure-section">
              <strong class="ok"><Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Diagnostics passed:</strong>
              <ul>{#each disclosure.diagnostics_passed as d}<li class="ok">{d}</li>{/each}</ul>
            </div>
          {/if}

          {#if disclosure.diagnostics_failed?.length}
            <div class="disclosure-section warn">
              <strong><TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Diagnostics failed:</strong>
              <ul>{#each disclosure.diagnostics_failed as d}<li>{d}</li>{/each}</ul>
            </div>
          {/if}

          {#if disclosure.caveats?.length}
            <div class="disclosure-section warn">
              <strong>Caveats:</strong>
              <ul>{#each disclosure.caveats as c}<li>{c}</li>{/each}</ul>
            </div>
          {/if}

          {#if disclosure.references?.length}
            <div class="disclosure-section">
              <strong>References:</strong>
              <ul>{#each disclosure.references as r}<li><em>{r}</em></li>{/each}</ul>
            </div>
          {/if}
        </div>
      </details>
    {/if}

    <!-- Method-specific diagnostics -->
    <details class="diagnostics-block">
      <summary><ChartColumn size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Diagnostics</summary>
      <div class="diagnostics-content">
        {#if result.method === 'did_twfe'}
          <p><strong>n_observations:</strong> {diag.n_observations} ({diag.n_entities} units × {diag.n_periods} periods)</p>
          <p><strong>R²:</strong> {formatNumber(diag.r_squared, 4)}</p>
          <p><strong>p-value:</strong> {formatNumber(diag.p_value, 4)}</p>
          <p><strong>Staggered adoption:</strong> {diag.is_staggered ? '⚠ Yes (TWFE biased)' : 'No'}</p>
          {#if diag.parallel_trends_test}
            <p><strong>Parallel-trends test:</strong> {diag.parallel_trends_test.detail}</p>
          {/if}
        {:else if result.method === 'scm_abadie_classic'}
          <p><strong>Treated unit:</strong> {diag.treated_unit}</p>
          <p><strong>Treatment period:</strong> {diag.treatment_period}</p>
          <p><strong>Pre-RMSE:</strong> {formatNumber(diag.pre_treatment_rmse)} (ratio {formatNumber(diag.pre_treatment_rmse_ratio, 3)})</p>
          <p><strong>Effective donors:</strong> {formatNumber(diag.effective_n_donors, 1)} (HHI {formatNumber(diag.weight_hhi, 3)})</p>
          {#if diag.placebo_test?.p_value !== null && diag.placebo_test?.p_value !== undefined}
            <p><strong>Placebo p-value:</strong> {formatNumber(diag.placebo_test.p_value, 4)} ({diag.placebo_test.n_placebos} placebos)</p>
          {/if}
          {#if diag.donor_weights}
            <p><strong>Donor weights:</strong></p>
            <ul class="weights-list">
              {#each Object.entries(diag.donor_weights) as [u, w]}
                {#if w > 0.01}
                  <li>{u}: {formatNumber(w, 3)}</li>
                {/if}
              {/each}
            </ul>
          {/if}
        {:else if result.method === 'forest_wager_athey'}
          <p><strong>n:</strong> {diag.n_observations} obs, {diag.n_features} features, {diag.n_estimators} trees</p>
          <p><strong>Heterogeneity strength:</strong> {formatNumber(diag.heterogeneity_strength, 3)}</p>
          {#if diag.cate_summary}
            <p><strong>CATE distribution:</strong> q10={formatNumber(diag.cate_summary.q10)}, median={formatNumber(diag.cate_summary.median)}, q90={formatNumber(diag.cate_summary.q90)}</p>
          {/if}
          {#if diag.overlap_check}
            <p><strong>Overlap:</strong> {diag.overlap_check.detail}</p>
          {/if}
          {#if diag.feature_importance}
            <p><strong>Feature importance:</strong></p>
            <ul class="weights-list">
              {#each Object.entries(diag.feature_importance) as [f, imp]}
                <li>{f}: {formatNumber(imp, 3)}</li>
              {/each}
            </ul>
          {/if}
        {/if}
      </div>
    </details>

    {#if result.artifact_path}
      <p class="artifact-path">💾 Artifact: <code>{result.artifact_path}</code></p>
    {/if}
  </div>
{/if}

<style>
  .result-card, .error-card {
    padding: 1.5rem;
    background: var(--bg-surface-focus, rgba(255, 255, 255, 0.96));
    border-radius: 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    margin-bottom: 1rem;
  }

  .error-card {
    border-left: 4px solid var(--danger, #dc2626);
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 1rem;
  }

  h3 {
    margin: 0;
    font-size: 1.125rem;
  }

  .ts {
    font-size: 0.75rem;
    color: var(--text-muted, #9ca3af);
  }

  .att-block {
    padding: 1.25rem;
    border-radius: 10px;
    margin-bottom: 1rem;
  }

  .att-block.tone-positive { background: var(--success-soft, #dcfce7); border: 1px solid var(--success, #22c55e); }
  .att-block.tone-negative { background: var(--danger-soft, #fee2e2); border: 1px solid var(--danger, #dc2626); }
  .att-block.tone-inconclusive { background: var(--warn-soft, #fef3c7); border: 1px solid var(--warn, #f59e0b); }

  .att-label { font-size: 0.875rem; color: var(--text-secondary); margin-bottom: 0.25rem; }
  .att-point { font-size: 2rem; font-weight: 600; line-height: 1; margin-bottom: 0.5rem; }
  .att-ci { font-size: 0.875rem; color: var(--text-secondary); }
  .ci-bracket { font-family: 'JetBrains Mono', monospace; font-weight: 500; }
  .ci-method { color: var(--text-muted); font-size: 0.75rem; }
  .att-verdict { margin-top: 0.5rem; font-weight: 500; font-size: 0.875rem; }
  .att-verdict.positive { color: var(--success, #16a34a); }
  .att-verdict.negative { color: var(--danger, #dc2626); }
  .att-verdict.inconclusive { color: var(--warn, #ca8a04); }

  details { margin-bottom: 1rem; }
  summary { cursor: pointer; padding: 0.5rem; font-weight: 500; user-select: none; }
  .disclosure-content, .diagnostics-content { padding: 0.5rem 1rem; }
  .disclosure-section { margin-bottom: 0.75rem; font-size: 0.875rem; }
  .disclosure-section.warn { color: var(--warn, #b45309); }
  .disclosure-section ul { margin: 0.25rem 0; padding-left: 1.25rem; }
  .disclosure-section li.ok { color: var(--success, #16a34a); }
  .weights-list { font-family: 'JetBrains Mono', monospace; font-size: 0.875rem; }
  .artifact-path { font-size: 0.75rem; color: var(--text-muted, #9ca3af); margin-top: 0.5rem; }
  code { background: var(--bg-elevated, #f9fafb); padding: 0.125rem 0.375rem; border-radius: 3px; font-size: 0.75rem; }
</style>
