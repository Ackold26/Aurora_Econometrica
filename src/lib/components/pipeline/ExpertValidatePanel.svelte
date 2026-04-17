<script>
  /**
   * Expert-only panel for ValidateStep.
   * Shows: correlation heatmap, VIF table, data quality stats.
   * @component ExpertValidatePanel
   */
  import CorrelationHeatmap from '$lib/components/pipeline/CorrelationHeatmap.svelte';
  import { validateData } from '$lib/project-state.js';

  const result = $derived($validateData?.result);
  const corrMatrix = $derived($validateData?.correlationMatrix);

  /** @type {Array<{name: string, vif: number}>} */
  const vifTable = $derived.by(() => {
    if (!result?.columns) return [];
    return result.columns
      .filter(/** @param {any} c */ (c) => c.role === 'media' && c.stats?.vif != null)
      .map(/** @param {any} c */ (c) => ({ name: c.name, vif: c.stats.vif }))
      .sort(/** @param {any} a @param {any} b */ (a, b) => b.vif - a.vif);
  });

  const dataStats = $derived.by(() => {
    if (!result?.columns) return [];
    return result.columns.map(/** @param {any} c */ (c) => ({
      name: c.name,
      role: c.role,
      dtype: c.dtype ?? '—',
      missing: c.stats?.missing_pct?.toFixed(1) ?? '0',
      zeros: c.stats?.zeros_pct?.toFixed(1) ?? '0',
      mean: c.stats?.mean?.toFixed(2) ?? '—',
      std: c.stats?.std?.toFixed(2) ?? '—',
    }));
  });
</script>

<div class="expert-panel">
  <div class="section-title">Корреляционная матрица</div>
  {#if corrMatrix}
    <CorrelationHeatmap correlationMatrix={corrMatrix} />
  {:else}
    <p class="empty">Запустите валидацию для отображения</p>
  {/if}

  {#if vifTable.length > 0}
    <div class="section-title">VIF (Variance Inflation Factor)</div>
    <table class="vif-table">
      <thead><tr><th>Канал</th><th>VIF</th><th>Статус</th></tr></thead>
      <tbody>
        {#each vifTable as row}
          <tr class:high={row.vif > 10} class:medium={row.vif > 5 && row.vif <= 10}>
            <td>{row.name}</td>
            <td class="mono">{row.vif.toFixed(1)}</td>
            <td>{row.vif > 10 ? 'Мультиколлинеарность' : row.vif > 5 ? 'Умеренная' : 'Норма'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if dataStats.length > 0}
    <div class="section-title">Статистика столбцов</div>
    <div class="stats-scroll">
      <table class="stats-table">
        <thead><tr><th>Столбец</th><th>Роль</th><th>Тип</th><th>Пропуски %</th><th>Нули %</th><th>Среднее</th><th>Std</th></tr></thead>
        <tbody>
          {#each dataStats as row}
            <tr>
              <td>{row.name}</td>
              <td class="role-badge">{row.role}</td>
              <td class="mono">{row.dtype}</td>
              <td class="mono" class:warn={parseFloat(row.missing) > 5}>{row.missing}</td>
              <td class="mono" class:warn={parseFloat(row.zeros) > 80}>{row.zeros}</td>
              <td class="mono">{row.mean}</td>
              <td class="mono">{row.std}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .expert-panel { display: flex; flex-direction: column; gap: 16px; margin-top: 16px; }
  .section-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: rgba(167,139,250,0.8); }
  .empty { font-size: 12px; color: rgba(148,163,184,0.5); }

  table { width: 100%; border-collapse: collapse; font-size: 11px; }
  th { text-align: left; padding: 6px 8px; color: var(--text-secondary, #94a3b8); border-bottom: 1px solid rgba(255,255,255,0.06); font-weight: 600; }
  td { padding: 5px 8px; color: var(--text-primary, #e2e8f0); border-bottom: 1px solid rgba(255,255,255,0.03); }
  .mono { font-family: monospace; }
  .warn { color: #f59e0b; }
  tr.high td { background: rgba(239,68,68,0.06); }
  tr.medium td { background: rgba(245,158,11,0.04); }
  .role-badge { font-size: 10px; color: var(--accent-primary, #3b82f6); }
  .stats-scroll { overflow-x: auto; }
</style>
