<script>
  /**
   * Expert-only panel for DecomposeStep.
   * Shows: Share of Spend vs Effect table, detailed channel stats.
   * @component ExpertDecomposePanel
   */
  import { decomposeData, modelData } from '$lib/project-state.js';

  const data = $derived($decomposeData);
  const mData = $derived($modelData);

  const shareTable = $derived.by(() => {
    if (!data?.channels) return [];
    const totalSpend = data.channels.reduce(/** @param {number} s @param {any} c */ (s, c) => s + (c.spend || 0), 0);
    const totalContrib = data.channels.reduce(/** @param {number} s @param {any} c */ (s, c) => s + (c.contribution || 0), 0);
    return data.channels.map(/** @param {any} ch */ (ch) => {
      const spendShare = totalSpend ? (ch.spend / totalSpend) * 100 : 0;
      const effectShare = totalContrib ? (ch.contribution / totalContrib) * 100 : 0;
      const efficiency = spendShare > 0 ? effectShare / spendShare : 0;
      return {
        name: ch.name,
        spend: ch.spend,
        contribution: ch.contribution,
        spendShare,
        effectShare,
        efficiency,
        roi: ch.roi,
        verdict: ch.verdict,
      };
    }).sort(/** @param {any} a @param {any} b */ (a, b) => b.efficiency - a.efficiency);
  });
</script>

<div class="expert-panel">
  {#if shareTable.length > 0}
    <div class="section-title">Share of Spend vs Share of Effect</div>
    <div class="share-scroll">
      <table>
        <thead>
          <tr>
            <th>Канал</th>
            <th>Расход</th>
            <th>% бюджета</th>
            <th>Вклад</th>
            <th>% эффекта</th>
            <th title="Effect Share / Spend Share">Efficiency</th>
            <th>ROI</th>
            <th>Вердикт</th>
          </tr>
        </thead>
        <tbody>
          {#each shareTable as row}
            <tr>
              <td>{row.name}</td>
              <td class="mono">{row.spend?.toFixed(0)}</td>
              <td class="mono">{row.spendShare.toFixed(1)}%</td>
              <td class="mono">{row.contribution?.toFixed(0)}</td>
              <td class="mono">{row.effectShare.toFixed(1)}%</td>
              <td class="mono" class:good={row.efficiency > 1.5} class:warn={row.efficiency < 0.7}>{row.efficiency.toFixed(2)}x</td>
              <td class="mono">{row.roi?.toFixed(2) ?? '—'}x</td>
              <td class="verdict">{row.verdict ?? '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="legend">
      Efficiency &gt; 1.0x = канал получает меньше бюджета, чем приносит эффекта (недоинвестирован).
      Efficiency &lt; 1.0x = канал перенасыщен — расходы выше вклада.
    </div>
  {/if}
</div>

<style>
  .expert-panel {
    display: flex; flex-direction: column; gap: 12px; margin-top: 24px;
    padding: 16px; border-radius: var(--radius-md, 10px);
    background: color-mix(in srgb, var(--danger) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--danger) 8%, transparent);
    position: relative;
  }
  .expert-panel::before {
    content: 'Экспертный режим';
    position: absolute;
    top: -8px;
    left: 12px;
    padding: 2px 8px;
    background: var(--bg-primary, #0C0C12);
    color: var(--danger);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border-radius: 4px;
  }
  .section-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: rgba(252,165,165,0.85); }
  .share-scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 11px; }
  th { text-align: left; padding: 6px 8px; color: var(--text-secondary, #94a3b8); border-bottom: 1px solid rgba(255,255,255,0.06); font-weight: 600; }
  td { padding: 5px 8px; color: var(--text-primary, #e2e8f0); border-bottom: 1px solid rgba(255,255,255,0.03); }
  .mono { font-family: monospace; }
  .good { color: #22c55e; }
  .warn { color: #f59e0b; }
  .verdict { font-size: 10px; color: var(--text-muted); }
  .legend { font-size: 10px; color: var(--text-muted); line-height: 1.5; padding: 8px; background: rgba(255,255,255,0.02); border-radius: 6px; }
</style>
