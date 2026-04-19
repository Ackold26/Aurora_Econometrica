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
        gap: effectShare - spendShare,
        roi: ch.roi,
        verdict: ch.verdict,
        verdict_tone: ch.verdict_tone || 'neutral',
      };
    }).sort(/** @param {any} a @param {any} b */ (a, b) => b.efficiency - a.efficiency);
  });

  // Help-tooltips: «что это» + «почему важно»
  const HELP = {
    spend:      'Расход — суммарный бюджет канала за весь анализируемый период (в исходной валюте/единицах).\n\nПочему важно: основа для расчёта ROI и доли бюджета. Если у канала единицы измерения не рубли (TRP, GRP, показы) — ROI и Efficiency будут искажены.',
    spendPct:   '% бюджета — доля канала в общем медиа-бюджете.\n\nПочему важно: показывает «сколько вы вложили в канал». Сравните с % эффекта — если бюджет > эффекта, канал перенасыщен.',
    contrib:    'Вклад — оценка вклада канала в продажи (в рублях продаж).\n\nПочему важно: вклад делится на расход → ROI. Это и есть деньги, которые принесла реклама.',
    effectPct:  '% эффекта — доля канала в общем медиа-вкладе в продажи.\n\nПочему важно: главный показатель силы канала. Сравнивайте с % бюджета — если эффект > бюджета, канал недоинвестирован (можно докрутить).',
    gap:        'Gap — разрыв между долей эффекта и долей бюджета (effect% − spend%).\n\n+10% и выше: канал работает сильно эффективнее своей доли бюджета — кандидат на докрутку.\n0 ± 5%: сбалансирован.\n−10% и ниже: канал перенасыщен — каждый дополнительный рубль даёт меньше отдачи, чем у среднего канала.',
    efficiency: 'Efficiency = % эффекта / % бюджета. Прямой индикатор окупаемости относительно средней по миксу.\n\n> 1.5×: канал «недоинвестирован» — приносит больше эффекта, чем потребляет бюджета. Перебросить сюда деньги — выгодно.\n< 0.7×: канал перенасыщен — расходы выше вклада. Сократить или пересмотреть креатив/таргетинг.',
    roi:        'ROI = вклад / расход. Сколько рублей продаж приносит каждый вложенный рубль.\n\nROI ≥ 2× = отлично. 1-2× = окупается. < 1× = убыточен.\n\nВнимание: если канал не в рублях (TRP, показы), ROI становится бессмысленно большим — нужна нормализация единиц.',
    verdict:    'Вердикт — комбинированная оценка канала по ROI и Gap. Учитывает не только сырой ROI, но и эффективность относительно своей доли бюджета.\n\n«ROI завышен» → подозрение на смешанные единицы (канал не в рублях).',
  };

  /** @param {number} n */
  const fmtInt = (n) => (Number.isFinite(n) ? Math.round(n).toLocaleString('ru-RU') : '—');
  /** @param {number} n */
  const fmtPct = (n) => (Number.isFinite(n) ? n.toFixed(1) + '%' : '—');
  /** @param {number} n */
  const fmtX   = (n) => (Number.isFinite(n) ? n.toFixed(2) + '×' : '—');
</script>

<div class="expert-panel">
  {#if shareTable.length > 0}
    <div class="section-title">Share of Spend vs Share of Effect</div>
    <div class="share-scroll">
      <table>
        <colgroup>
          <col style="width: 20%" />
          <col style="width: 11%" />
          <col style="width: 9%" />
          <col style="width: 12%" />
          <col style="width: 9%" />
          <col style="width: 9%" />
          <col style="width: 9%" />
          <col style="width: 9%" />
          <col style="width: 12%" />
        </colgroup>
        <thead>
          <tr>
            <th>Канал</th>
            <th class="num">Расход<span class="help-icon" title={HELP.spend}>?</span></th>
            <th class="num">% бюджета<span class="help-icon" title={HELP.spendPct}>?</span></th>
            <th class="num">Вклад<span class="help-icon" title={HELP.contrib}>?</span></th>
            <th class="num">% эффекта<span class="help-icon" title={HELP.effectPct}>?</span></th>
            <th class="num">Gap<span class="help-icon" title={HELP.gap}>?</span></th>
            <th class="num">Efficiency<span class="help-icon" title={HELP.efficiency}>?</span></th>
            <th class="num">ROI<span class="help-icon" title={HELP.roi}>?</span></th>
            <th>Вердикт<span class="help-icon" title={HELP.verdict}>?</span></th>
          </tr>
        </thead>
        <tbody>
          {#each shareTable as row}
            <tr>
              <td>{row.name}</td>
              <td class="mono num">{fmtInt(row.spend)}</td>
              <td class="mono num">{fmtPct(row.spendShare)}</td>
              <td class="mono num">{fmtInt(row.contribution)}</td>
              <td class="mono num">{fmtPct(row.effectShare)}</td>
              <td class="mono num" class:good={row.gap >= 5} class:warn={row.gap <= -5}>
                {row.gap > 0 ? '+' : ''}{fmtPct(row.gap)}
              </td>
              <td class="mono num" class:good={row.efficiency > 1.5} class:warn={row.efficiency < 0.7}>
                {fmtX(row.efficiency)}
              </td>
              <td class="mono num" class:good={row.roi > 2} class:warn={row.roi < 1}>
                {fmtX(row.roi)}
              </td>
              <td class="verdict" class:tone-good={row.verdict_tone === 'good'} class:tone-warn={row.verdict_tone === 'warn'} class:tone-bad={row.verdict_tone === 'bad'}>
                {row.verdict ?? '—'}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="legend">
      <b>Gap</b> = % эффекта − % бюджета. <b>Efficiency</b> = % эффекта ÷ % бюджета.
      Положительный Gap (или Efficiency &gt; 1×) = канал работает сильнее своей доли бюджета (недоинвестирован).
      Отрицательный Gap (Efficiency &lt; 1×) = канал перенасыщен — расходы выше вклада.
      Подсказки по каждой колонке — наведи курсор на «?».
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
  table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12px; }
  th {
    text-align: left;
    padding: 6px 8px;
    color: var(--text-secondary);
    border-bottom: 1px solid color-mix(in srgb, var(--text-primary) 10%, transparent);
    font-weight: 600;
    white-space: nowrap;
  }
  th.num, td.num { text-align: right; }
  th .help-icon { margin-left: 4px; vertical-align: middle; }
  td {
    padding: 5px 8px;
    color: var(--text-primary);
    border-bottom: 1px solid color-mix(in srgb, var(--text-primary) 5%, transparent);
  }
  .mono { font-family: 'SF Mono', 'JetBrains Mono', Consolas, monospace; font-variant-numeric: tabular-nums; }
  .good { color: var(--success); }
  .warn { color: var(--warning); }
  .verdict {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-muted);
    white-space: nowrap;
  }
  .verdict.tone-good { color: var(--success); }
  .verdict.tone-warn { color: var(--warning); }
  .verdict.tone-bad  { color: var(--danger); }
  .legend {
    font-size: 11px;
    line-height: 1.6;
    color: var(--text-secondary);
    padding: 10px 12px;
    background: color-mix(in srgb, var(--text-primary) 4%, transparent);
    border-radius: 6px;
  }
  .legend b { color: var(--text-primary); font-weight: 600; }
  .help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--text-secondary) 18%, transparent);
    color: var(--text-secondary);
    font-size: 10px;
    font-weight: 700;
    cursor: help;
    user-select: none;
    transition: background 0.15s, color 0.15s;
  }
  .help-icon:hover {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
    color: var(--accent-primary, #3b82f6);
  }
</style>
