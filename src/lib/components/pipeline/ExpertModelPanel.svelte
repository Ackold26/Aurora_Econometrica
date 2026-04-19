<script>
  /**
   * Expert-only panel for ModelTrainingStep.
   * Shows: per-channel adstock details, MCMC diagnostics, convergence stats.
   * @component ExpertModelPanel
   */
  import { modelData } from '$lib/project-state.js';

  const diagnostics = $derived($modelData?.diagnostics);
  const channelParams = $derived($modelData?.channelParams);

  const paramRows = $derived.by(() => {
    if (!channelParams) return [];
    return Object.entries(channelParams).map(([name, p]) => ({
      name,
      alpha: /** @type {any} */ (p).alpha,
      gamma: /** @type {any} */ (p).gamma,
      beta: /** @type {any} */ (p).beta,
      roi: /** @type {any} */ (p).roi,
      roi_ci_lower: /** @type {any} */ (p).roi_ci_lower,
      roi_ci_upper: /** @type {any} */ (p).roi_ci_upper,
    }));
  });

  // ── Tooltip-помощь по каждому показателю и параметру: «что это» + «почему важно» ──
  const HELP = {
    rHat:  'R-hat (Gelman-Rubin) — мера сходимости параллельных цепей Markov Chain Monte Carlo.\n\nЧто это: насколько разные цепи пришли к одному распределению (1.0 = идеально, > 1.05 = не сошлись).\n\nПочему важно: если цепи не сошлись — оценки ROI и CI ненадёжны, результаты случайны.',
    divs:  'Дивергенции (divergences) — количество шагов сэмплера NUTS, которые «соскочили» с траектории.\n\nЧто это: индикатор сложной геометрии posterior — модель плохо параметризована или priors слишком широкие.\n\nПочему важно: при дивергенциях > 0 часть пространства параметров не исследована — оценки могут быть смещены. Цель = 0.',
    rSq:   'R² (коэффициент детерминации) — доля вариации KPI, объяснённая моделью.\n\nЧто это: 0 = модель не лучше среднего, 1 = идеальный fit. ≥ 0.7 — хорошо, ≥ 0.9 — отлично.\n\nПочему важно: показывает, насколько модель захватывает динамику продаж. Низкий R² = вы что-то упустили (промо, сезонность, конкуренты).',
    mape:  'MAPE (Mean Absolute Percentage Error) — средняя абсолютная ошибка прогноза в процентах.\n\nЧто это: на сколько процентов в среднем прогноз отличается от факта. < 10% — отлично, 10-20% — приемлемо, > 20% — плохо.\n\nПочему важно: дополняет R². Можно иметь высокий R² и большие отклонения в отдельных периодах — MAPE это ловит.',
    mqs:   'MQS (Model Quality Score) — агрегированная оценка качества модели от 0 до 100.\n\nЧто это: взвешенная комбинация R² (40%), MAPE (30%) и сходимости MCMC (30%). ≥ 80 = отлично, 60-80 = хорошо.\n\nПочему важно: одно число для быстрой оценки — стоит ли доверять выводам модели.',
    alpha: 'α (Hill steepness) — крутизна кривой насыщения для канала.\n\nЧто это: контролирует, как быстро отдача от рекламы выходит на плато. α ≈ 1-2 — типичная saturation (плавный изгиб).\n\nПочему важно: высокая α = резкий cutoff (после порога каждый рубль почти не работает); низкая α = плавная saturation (отдача снижается медленно). Влияет на оптимальный бюджет канала.',
    gamma: 'γ (Hill half-saturation) — точка половинного насыщения, нормализованная на максимум канала.\n\nЧто это: при каком уровне расхода канал даёт половину своего максимального эффекта. γ ≈ 0.5 = половина при середине бюджета.\n\nПочему важно: маленькая γ = канал быстро насыщается (нет смысла лить много денег); большая γ = ещё далеко до saturation, можно докупать.',
    beta:  'β (channel coefficient) — сила эффекта канала на нормализованной шкале.\n\nЧто это: posterior mean коэффициента в Bayesian-регрессии. Чем больше β — тем сильнее канал влияет на KPI per единицу бюджета (после Adstock и Hill).\n\nПочему важно: внутренний параметр модели; для маркетёра важнее производный ROI (см. справа). β полезен для сравнения «силы сигнала» каналов между собой.',
    roi:   'ROI (Return on Investment) — отдача на каждый рубль, вложенный в канал.\n\nЧто это: вклад канала в KPI / расход на канал. ROI = 2.5x означает «канал генерирует 2.5 рубля продаж на каждый вложенный рубль».\n\nПочему важно: главная метрика для перераспределения бюджета. Каналы с ROI < 1.0 — убыточные, > 2.0 — отличные.',
    roiCi: 'CI 95% (доверительный интервал ROI) — диапазон, где истинный ROI лежит с вероятностью 95%.\n\nЧто это: [нижняя, верхняя] граница из posterior distribution Bayesian-модели. Узкий интервал = высокая определённость, широкий = высокая неопределённость.\n\nПочему важно: показывает не точку, а РАЗБРОС оценки. Если CI = [0.8, 4.2] — мы плохо знаем ROI. Если CI = [2.1, 2.5] — оценка надёжна.',
  };

  /** Характеристика-метка для каждого показателя — как у MQS «96 (Отличное)». */
  /**
   * @param {number} v
   */
  function rHatLabel(v) {
    if (v == null || !Number.isFinite(v)) return { text: '—', tone: 'neutral' };
    if (v <= 1.01) return { text: 'Идеально', tone: 'good' };
    if (v <= 1.05) return { text: 'Приемлемо', tone: 'warn' };
    return { text: 'Не сошлось', tone: 'bad' };
  }
  /**
   * @param {number} v
   */
  function divsLabel(v) {
    if (v == null) return { text: '—', tone: 'neutral' };
    if (v === 0) return { text: 'Чисто', tone: 'good' };
    if (v < 10) return { text: 'Несколько', tone: 'warn' };
    return { text: 'Много', tone: 'bad' };
  }
  /**
   * @param {number} v
   */
  function rSqLabel(v) {
    if (v == null || !Number.isFinite(v)) return { text: '—', tone: 'neutral' };
    if (v >= 0.9) return { text: 'Очень сильный fit', tone: 'good' };
    if (v >= 0.7) return { text: 'Сильный fit', tone: 'good' };
    if (v >= 0.5) return { text: 'Средний fit', tone: 'warn' };
    return { text: 'Слабый fit', tone: 'bad' };
  }
  /**
   * @param {number} v
   */
  function mapeLabel(v) {
    if (v == null || !Number.isFinite(v)) return { text: '—', tone: 'neutral' };
    if (v < 5) return { text: 'Превосходно', tone: 'good' };
    if (v < 10) return { text: 'Отлично', tone: 'good' };
    if (v < 20) return { text: 'Приемлемо', tone: 'warn' };
    return { text: 'Высокая ошибка', tone: 'bad' };
  }
  /**
   * @param {number} v
   */
  function roiLabel(v) {
    if (v == null || !Number.isFinite(v)) return { text: '—', tone: 'neutral' };
    if (v >= 2) return { text: 'Высокий', tone: 'good' };
    if (v >= 1) return { text: 'Окупается', tone: 'warn' };
    return { text: 'Убыточный', tone: 'bad' };
  }
</script>

<div class="expert-panel">
  {#if diagnostics}
    {@const m = diagnostics.metrics ?? diagnostics}
    {@const rHat = m.r_hat_max ?? diagnostics.r_hat}
    {@const divs = m.divergences ?? diagnostics.divergences ?? 0}
    {@const rSq = m.r_squared ?? diagnostics.r_squared}
    {@const mape = m.mape_pct ?? diagnostics.mape}
    {@const mqsScore = diagnostics.mqs?.score}
    {@const mqsTier = diagnostics.mqs?.tier_label ?? ''}
    {@const rh = rHatLabel(rHat)}
    {@const dv = divsLabel(divs)}
    {@const rsq = rSqLabel(rSq)}
    {@const mp = mapeLabel(mape)}
    <div class="section-title">Диагностика Markov Chain Monte Carlo</div>
    <div class="diag-grid">
      <div class="diag-item">
        <span class="diag-label">R-hat (max)<span class="help-icon" title={HELP.rHat}>?</span></span>
        <span class="diag-value" class:good={rh.tone === 'good'} class:warn={rh.tone === 'warn'} class:bad={rh.tone === 'bad'}>
          {rHat?.toFixed(4) ?? '—'}
        </span>
        <span class="diag-tier" class:good={rh.tone === 'good'} class:warn={rh.tone === 'warn'} class:bad={rh.tone === 'bad'}>
          {rh.text}
        </span>
      </div>
      <div class="diag-item">
        <span class="diag-label">Дивергенции<span class="help-icon" title={HELP.divs}>?</span></span>
        <span class="diag-value" class:good={dv.tone === 'good'} class:warn={dv.tone === 'warn'} class:bad={dv.tone === 'bad'}>
          {divs ?? 0}
        </span>
        <span class="diag-tier" class:good={dv.tone === 'good'} class:warn={dv.tone === 'warn'} class:bad={dv.tone === 'bad'}>
          {dv.text}
        </span>
      </div>
      <div class="diag-item">
        <span class="diag-label">R²<span class="help-icon" title={HELP.rSq}>?</span></span>
        <span class="diag-value" class:good={rsq.tone === 'good'} class:warn={rsq.tone === 'warn'} class:bad={rsq.tone === 'bad'}>
          {rSq?.toFixed(4) ?? '—'}
        </span>
        <span class="diag-tier" class:good={rsq.tone === 'good'} class:warn={rsq.tone === 'warn'} class:bad={rsq.tone === 'bad'}>
          {rsq.text}
        </span>
      </div>
      <div class="diag-item">
        <span class="diag-label">MAPE<span class="help-icon" title={HELP.mape}>?</span></span>
        <span class="diag-value" class:good={mp.tone === 'good'} class:warn={mp.tone === 'warn'} class:bad={mp.tone === 'bad'}>
          {mape?.toFixed(2) ?? '—'}%
        </span>
        <span class="diag-tier" class:good={mp.tone === 'good'} class:warn={mp.tone === 'warn'} class:bad={mp.tone === 'bad'}>
          {mp.text}
        </span>
      </div>
      <div class="diag-item">
        <span class="diag-label">MQS<span class="help-icon" title={HELP.mqs}>?</span></span>
        <span class="diag-value" class:good={mqsScore >= 80} class:warn={mqsScore >= 60 && mqsScore < 80} class:bad={mqsScore < 60}>
          {mqsScore?.toFixed(0) ?? '—'}
        </span>
        <span class="diag-tier" class:good={mqsScore >= 80} class:warn={mqsScore >= 60 && mqsScore < 80} class:bad={mqsScore < 60}>
          {mqsTier}
        </span>
      </div>
    </div>
  {/if}

  {#if paramRows.length > 0}
    <div class="section-title">Параметры каналов (posterior means)</div>
    <div class="params-scroll">
      <table class="params-table">
        <thead>
          <tr>
            <th>Канал</th>
            <th>α<span class="help-icon" title={HELP.alpha}>?</span></th>
            <th>γ<span class="help-icon" title={HELP.gamma}>?</span></th>
            <th>β<span class="help-icon" title={HELP.beta}>?</span></th>
            <th>ROI<span class="help-icon" title={HELP.roi}>?</span></th>
            <th>CI 95%<span class="help-icon" title={HELP.roiCi}>?</span></th>
          </tr>
        </thead>
        <tbody>
          {#each paramRows as row}
            <tr>
              <td>{row.name}</td>
              <td class="mono">{row.alpha?.toFixed(3) ?? '—'}</td>
              <td class="mono">{row.gamma?.toFixed(4) ?? '—'}</td>
              <td class="mono">{row.beta?.toFixed(4) ?? '—'}</td>
              <td class="mono" class:good={row.roi > 2} class:warn={row.roi < 1}>{row.roi?.toFixed(2) ?? '—'}x</td>
              <td class="mono ci">[{row.roi_ci_lower?.toFixed(2) ?? '?'}, {row.roi_ci_upper?.toFixed(2) ?? '?'}]</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .expert-panel {
    display: flex; flex-direction: column; gap: 16px; margin-top: 24px;
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

  .diag-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
  .diag-item {
    display: flex; flex-direction: column; gap: 2px;
    padding: 10px 12px; border-radius: 8px;
    background: color-mix(in srgb, var(--text-primary) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-primary) 8%, transparent);
  }
  .diag-label {
    font-size: 10px;
    color: var(--text-secondary);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .diag-value {
    font-size: 18px;
    font-weight: 700;
    font-family: monospace;
    color: var(--text-primary);
    line-height: 1.2;
  }
  .diag-tier {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-secondary);
    margin-top: 2px;
  }
  .diag-value.good, .diag-tier.good { color: var(--success); }
  .diag-value.warn, .diag-tier.warn { color: var(--warning); }
  .diag-value.bad,  .diag-tier.bad  { color: var(--danger); }

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

  .params-scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th {
    text-align: left;
    padding: 6px 8px;
    color: var(--text-secondary);
    border-bottom: 1px solid color-mix(in srgb, var(--text-primary) 10%, transparent);
    font-weight: 600;
  }
  th .help-icon { margin-left: 4px; vertical-align: middle; }
  td {
    padding: 5px 8px;
    color: var(--text-primary);
    border-bottom: 1px solid color-mix(in srgb, var(--text-primary) 5%, transparent);
  }
  .mono { font-family: monospace; }
  .good { color: var(--success); }
  .warn { color: var(--warning); }
  .ci { color: var(--text-muted); font-size: 10px; }
</style>
