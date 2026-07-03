<script>
  /**
   * GoalSeekResultCard - v1.3.0 inverse optimization result display (per ADR-014).
   *
   * Props:
   * - result: backend response from econ_optimize_inverse:
   *     achievable: boolean
   *     total_budget: {p10, p50, p90, method}
   *     distribution: {channel: budget}
   *     delta_vs_current: float
   *     p_hit_target: float
   *     iterations: int
   *     expected_sales: float
   *     fallback_max_sales / fallback_budget / message (if !achievable)
   *
   * @component GoalSeekResultCard
   */

  // UX audit v1.3.0: используем unified format helpers (вместо inline ad-hoc).
  import { formatMoney, formatDelta, formatCount } from '$lib/format-numbers.js';
  import { TriangleAlert } from 'lucide-svelte';

  const { result, kpiKind, targetSales } = $props();

  /** @param {number | null | undefined} n */
  function formatRub(n) {
    return formatMoney(n);
  }

  /** @param {number | null | undefined} n */
  function formatPct(n) {
    // C3-N4 (2026-07-03): движковый контракт inverse.py — delta_vs_current
    // ВСЕГДА доля (1.096 = +109.6%). Эвристика formatDelta/formatPct
    // «|n|>1 → уже процент» ломалась ровно при удвоении бюджета и выше:
    // живой прогон показал «260 млн → 545 млн (+1.1%)» вместо «+109.6%».
    if (n == null || !isFinite(n)) return '-';
    const pct = n * 100;
    return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`;
  }

  /** @param {number} n */
  function formatTarget(n) {
    if (kpiKind === 'monetary') return formatRub(n);
    return formatCount(n);
  }

  // #59 (2026-06-02): человекочитаемая метка метода CI вместо сырого backend-кода
  // (help-system принцип — без жаргона в user-facing тексте).
  /** @param {string | undefined} m */
  function methodLabel(m) {
    if (m === 'flat_response_fallback') return 'оценка при насыщении';
    if (m === 'point') return 'точечная оценка';
    if (m === 'delta') return 'дельта-метод';
    // Мат-аудит 2026-07-02: CI из апостериорного разброса модели (честная
    // неопределённость вместо прежней константы ±6.4%).
    if (m === 'delta_posterior') return 'дельта-метод по постериору';
    return 'бисекция';
  }

  // Мат-аудит 2026-07-02 (F-01): человекочитаемая строка каналов за диапазоном.
  /** @param {{name: string, ratio_vs_max: number | null}[]} channels */
  function extrapolationChannelsLabel(channels) {
    return (channels ?? [])
      .map((c) => (c.ratio_vs_max != null ? `${c.name} – ${c.ratio_vs_max}× исторического максимума` : c.name))
      .join(', ');
  }

  // OPP-02 (2026-07-03): «бюджет под вероятность» — процент уровня доверия
  // (result.confidence = 0.8 → «80%»), null = обычный медианный режим.
  const confidencePct = $derived(
    result?.confidence != null ? Math.round(result.confidence * 100) : null
  );
</script>

<div class="goal-seek-card" class:not-achievable={!result.achievable}>
  {#if result.achievable}
    <header class="card-header success">
      <span class="icon">✅</span>
      <h3>Цель достижима</h3>
    </header>

    <section class="main-figure">
      <div class="figure-label">
        {#if confidencePct != null}
          Бюджет под вероятность {confidencePct}%:
        {:else}
          Требуемый бюджет:
        {/if}
      </div>
      <div class="figure-value">{formatRub(result.total_budget.p50)}</div>
      {#if confidencePct != null}
        <div class="figure-confidence">
          Цель достигается не менее чем в {confidencePct}% сценариев модели
          {#if result.expected_sales_median != null}
            · типичный (медианный) прогноз при этом бюджете: <strong>{formatTarget(result.expected_sales_median)}</strong>
          {/if}
        </div>
      {/if}
      {#if result.total_budget.p10 != null && result.total_budget.p90 != null}
        <div class="figure-ci">
          80% доверительный интервал: {formatRub(result.total_budget.p10)} - {formatRub(result.total_budget.p90)}
        </div>
      {/if}
      {#if result.current_total_budget != null && result.current_total_budget > 0}
        <div class="baseline-comparison">
          Текущий бюджет: <strong>{formatRub(result.current_total_budget)}</strong>
          → Новый: <strong>{formatRub(result.total_budget.p50)}</strong>
          ({formatPct(result.delta_vs_current)})
        </div>
      {/if}
    </section>

    <!-- OPP-02 (INV-50): просили осторожный режим, но модель без апостериорных
         выборок (OLS/legacy) — честно говорим, что показан медианный расчёт. -->
    {#if result.confidence_unavailable}
      <section class="confidence-unavailable-note">
        <span class="note-icon"><TriangleAlert size={16} strokeWidth={1.5} /></span>
        <div class="note-body">
          <strong>Осторожный режим недоступен для этой модели</strong>
          <p>
            У модели нет апостериорных выборок (обучение без байесовского вывода),
            поэтому «бюджет под вероятность» посчитать нельзя. Показан обычный
            медианный расчёт – бюджет достигает цели примерно в половине сценариев.
          </p>
        </div>
      </section>
    {/if}

    {#if result.flat_response_fallback}
      <section class="saturation-note">
        <span class="note-icon">⚙️</span>
        <div class="note-body">
          <strong>Модель близка к насыщению</strong>
          <p>
            Бюджет найден, но каждый следующий рубль почти не увеличивает результат —
            отдача вышла на плато. Поэтому интервал требуемого бюджета широкий,
            а точное значение менее надёжно.
          </p>
          <p class="note-hint">
            💡 Прирост вероятнее получить перераспределением между каналами или
            подключением новых, чем увеличением общего бюджета.
          </p>
        </div>
      </section>
    {/if}

    <!-- Мат-аудит 2026-07-02 (F-01, INV-50): честная пометка экстраполяции —
         рекомендация требует трат выше наблюдавшихся в данных (Chan & Perry 2017:
         кривая отклика вне наблюдённого диапазона не подтверждена данными). -->
    {#if result.extrapolation && result.extrapolation.severity >= 1}
      <section class="extrapolation-note" class:critical={result.extrapolation.severity >= 2}>
        <span class="note-icon">📈</span>
        <div class="note-body">
          <strong>
            {result.extrapolation.severity >= 2 ? 'Сильная экстраполяция' : 'Экстраполяция за наблюдавшийся диапазон'}
          </strong>
          <p>
            Рекомендованные траты выходят за диапазон, на котором обучалась модель
            {#if result.extrapolation.channels?.length}
              : {extrapolationChannelsLabel(result.extrapolation.channels)}
            {/if}.
            Форма кривой отклика в этой зоне не подтверждена данными – фактический
            результат может заметно отличаться от прогноза.
          </p>
          {#if result.extrapolation.severity >= 2}
            <p class="note-hint">
              💡 Надёжнее наращивать бюджет поэтапно: частичное увеличение → новые
              данные → переобучение модели → следующий шаг.
            </p>
          {/if}
        </div>
      </section>
    {/if}

    <section class="metrics-row">
      <div class="metric">
        <div class="metric-label">Δ vs текущий</div>
        <div class="metric-value">{formatPct(result.delta_vs_current)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Вероятность достижения</div>
        <div class="metric-value">{(result.p_hit_target * 100).toFixed(0)}%</div>
      </div>
      <div class="metric">
        <div class="metric-label">Цель</div>
        <div class="metric-value">{formatTarget(result.target_sales ?? targetSales)}</div>
      </div>
    </section>

    {#if result.distribution && Object.keys(result.distribution).length > 0}
      {@const _totalDist = Object.values(result.distribution).reduce((s, b) => s + Number(b || 0), 0)}
      <section class="distribution">
        <h4>Распределение бюджета:</h4>
        {#if result.allocation_mode === 'proportional'}
          <p class="dist-note">Бюджет масштабирован при текущих пропорциях каналов (Goal-Seek отвечает «сколько нужно при нынешнем миксе»). Чтобы перераспределить между каналами, используйте прямой расчёт оптимизации.</p>
        {/if}
        <table>
          <thead>
            <tr>
              <th>Канал</th>
              <th class="num">Бюджет, ₽</th>
              <th class="num">Доля</th>
            </tr>
          </thead>
          <tbody>
            {#each Object.entries(result.distribution).sort((a, b) => b[1] - a[1]) as [channel, budget]}
              <tr>
                <td>{channel}</td>
                <td class="num">{formatRub(budget)}</td>
                <td class="num">{_totalDist > 0 ? `${((Number(budget) / _totalDist) * 100).toFixed(1)}%` : '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}

    {#if result.iterations}
      <footer class="card-footer">
        <span class="meta">Сошлось за {result.iterations} итераций · Метод: {methodLabel(result.total_budget.method)}</span>
      </footer>
    {/if}
  {:else}
    <header class="card-header warn">
      <span class="icon"><TriangleAlert size={18} strokeWidth={1.5} /></span>
      <h3>Цель недостижима в доступном диапазоне бюджета</h3>
    </header>

    <section class="fallback">
      <!-- 2026-06-07: число цели форматируем через formatTarget (как остальной UI:
           «12.7 млрд ₽»), а не сырой backend-message с «12730349434». Для случая
           budget-недостижимости компонуем текст из структурных полей; для прочих
           (non-convex Hill и т.п. — без чисел) показываем backend-message. -->
      {#if result.fallback_max_sales != null}
        <p>
          Цель <strong>{formatTarget(result.target_sales ?? targetSales)}</strong>
          {#if confidencePct != null}
            недостижима с вероятностью {confidencePct}% в доступном диапазоне бюджета.
          {:else}
            недостижима в доступном диапазоне бюджета.
          {/if}
        </p>
      {:else}
        <p>{result.message ?? 'Цель за пределами math-валидного диапазона модели.'}</p>
      {/if}
      {#if result.fallback_max_sales}
        <p class="fallback-detail">
          {#if confidencePct != null}
            Максимум продаж, достижимый с вероятностью {confidencePct}% при текущем миксе каналов:
          {:else}
            Максимум достижимых продаж при текущем миксе каналов:
          {/if}
          <strong>{formatTarget(result.fallback_max_sales)}</strong>
          (бюджет {formatRub(result.fallback_budget)}).
        </p>
      {/if}
      <p class="hint">
        💡 Снизьте цель до достижимой или включите расширение коридора в Эксперт-режиме
        (не рекомендуется без понимания рисков экстраполяции).
      </p>
    </section>
  {/if}
</div>

<style>
  .goal-seek-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-card, 12px);
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .goal-seek-card.not-achievable {
    border-color: color-mix(in srgb, var(--warning, #fbbf24) 40%, transparent);
    background: color-mix(in srgb, var(--warning, #fbbf24) 4%, transparent);
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .card-header.success { color: var(--success, #4ade80); }
  .card-header.warn { color: var(--warning, #fbbf24); }
  .card-header h3 { margin: 0; font-size: 15px; font-weight: 700; }
  .icon { font-size: 22px; }

  .main-figure {
    text-align: center;
    padding: 14px 0;
    border-bottom: 1px solid var(--border-subtle);
  }
  .figure-label { font-size: 12px; color: var(--text-muted); }
  .figure-value {
    font-size: 28px;
    font-weight: 700;
    color: var(--accent-primary);
    margin: 4px 0;
    letter-spacing: -0.02em;
  }
  .figure-ci { font-size: 11px; color: var(--text-secondary); }
  /* OPP-02: строка семантики осторожного режима под главной цифрой. */
  .figure-confidence {
    font-size: 11px;
    color: var(--text-secondary);
    margin-bottom: 2px;
  }
  .figure-confidence strong { color: var(--text-primary); font-weight: 600; }

  /* OPP-02 (INV-50): плашка «осторожный режим недоступен» — warning tier. */
  .confidence-unavailable-note {
    display: flex;
    gap: 12px;
    padding: 12px 14px;
    background: color-mix(in srgb, var(--warning, #fbbf24) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #fbbf24) 30%, transparent);
    border-radius: var(--radius-sm, 8px);
  }
  .confidence-unavailable-note .note-icon { line-height: 1.3; color: var(--warning, #fbbf24); }
  .confidence-unavailable-note .note-body { display: flex; flex-direction: column; gap: 4px; }
  .confidence-unavailable-note strong { font-size: 13px; font-weight: 600; color: var(--text-primary); }
  .confidence-unavailable-note p { margin: 0; font-size: 12px; line-height: 1.5; color: var(--text-secondary); }

  /* #59 (2026-06-02): баннер насыщения (flat response) — warning tier. */
  .saturation-note {
    display: flex;
    gap: 12px;
    padding: 12px 14px;
    background: color-mix(in srgb, var(--warning, #fbbf24) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #fbbf24) 30%, transparent);
    border-radius: var(--radius-sm, 8px);
  }
  .saturation-note .note-icon { font-size: 18px; line-height: 1.3; }
  .saturation-note .note-body { display: flex; flex-direction: column; gap: 4px; }
  .saturation-note strong { font-size: 13px; font-weight: 600; color: var(--text-primary); }
  .saturation-note p { margin: 0; font-size: 12px; line-height: 1.5; color: var(--text-secondary); }
  .saturation-note .note-hint { color: var(--text-primary); }

  /* Мат-аудит 2026-07-02 (F-01): баннер экстраполяции — warn tier; severity>=2 — danger. */
  .extrapolation-note {
    display: flex;
    gap: 12px;
    padding: 12px 14px;
    background: color-mix(in srgb, var(--warning, #fbbf24) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #fbbf24) 30%, transparent);
    border-radius: var(--radius-sm, 8px);
  }
  .extrapolation-note.critical {
    background: color-mix(in srgb, var(--danger, #ef4444) 8%, transparent);
    border-color: color-mix(in srgb, var(--danger, #ef4444) 30%, transparent);
  }
  .extrapolation-note .note-icon { font-size: 18px; line-height: 1.3; }
  .extrapolation-note .note-body { display: flex; flex-direction: column; gap: 4px; }
  .extrapolation-note strong { font-size: 13px; font-weight: 600; color: var(--text-primary); }
  .extrapolation-note p { margin: 0; font-size: 12px; line-height: 1.5; color: var(--text-secondary); }
  .extrapolation-note .note-hint { color: var(--text-primary); }

  .metrics-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }
  @media (max-width: 800px) {
    .metrics-row { grid-template-columns: 1fr; }
  }
  /* UX audit v1.3.0: baseline comparison row для контекста (был main figure без baseline). */
  .baseline-comparison {
    margin-top: 10px;
    font-size: 12px;
    color: var(--text-secondary);
    padding: 6px 10px;
    background: color-mix(in srgb, var(--accent-primary) 4%, transparent);
    border-radius: 6px;
    display: inline-block;
  }
  .baseline-comparison strong { color: var(--text-primary); font-weight: 600; }
  .metric {
    text-align: center;
    padding: 10px;
    background: var(--bg-surface-quiet);
    border-radius: var(--radius-sm, 8px);
  }
  .metric-label { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }
  .metric-value { font-size: 16px; font-weight: 700; color: var(--text-primary); }

  .distribution h4 {
    margin: 0 0 8px;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    font-weight: 700;
  }
  .dist-note {
    margin: 0 0 10px;
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-secondary);
  }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 6px 8px; border-bottom: 1px solid var(--border-subtle); }
  th {
    text-align: left;
    color: var(--text-muted);
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
  }
  .num { text-align: right; font-variant-numeric: tabular-nums; }

  .card-footer { display: flex; justify-content: flex-end; }
  .meta { font-size: 10px; color: var(--text-muted); }

  .fallback {
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-secondary);
  }
  .fallback p { margin: 0 0 8px; }
  .fallback strong { color: var(--text-primary); }
  .hint {
    padding: 8px 10px;
    background: color-mix(in srgb, var(--accent-primary) 6%, transparent);
    border-radius: var(--radius-sm, 6px);
    font-size: 12px;
  }
  .fallback-detail { color: var(--text-primary); }
</style>
