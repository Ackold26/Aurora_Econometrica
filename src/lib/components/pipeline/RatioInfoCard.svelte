<script>
  /**
   * RatioInfoCard - v1.3.2 Validate шаг.
   *
   * Объясняет ratio данных (наблюдений / переменных) - critical metric для
   * статистической надёжности MMM. Manager mode: визуальный 3-zone indicator,
   * актуальное значение, рекомендация. Expert mode: detailed breakdown с
   * weakChannels per-name + расчёт «после исключения».
   *
   * Принцип Aurora (Антон 2026-05-13): manager mode primary (no jargon,
   * actionable hints), expert mode opt-in (raw stats, formulas, knobs).
   *
   * @component RatioInfoCard
   */

  /**
   * Props:
   * - ratio: текущее (например 2.4)
   * - nObs: кол-во наблюдений (строк)
   * - nPredictors: кол-во переменных в модели (media + control)
   * - weakChannelsCount: сколько каналов имеют >50% нулей
   * - weakChannelNames: имена weak каналов (expert mode)
   * - afterExcludeRatio: ratio после исключения weak (или null)
   * - expertMode: показывать подробный breakdown
   * - onApplyExclude: callback при нажатии «Применить рекомендацию»
   *
   * @type {{
   *   ratio: number,
   *   nObs: number,
   *   nPredictors: number,
   *   weakChannelsCount?: number,
   *   weakChannelNames?: string[],
   *   afterExcludeRatio?: number | null,
   *   expertMode?: boolean,
   *   onApplyExclude?: (() => void) | null,
   * }}
   */
  const {
    ratio,
    nObs,
    nPredictors,
    weakChannelsCount = 0,
    weakChannelNames = [],
    afterExcludeRatio = null,
    expertMode = false,
    onApplyExclude = null,
  } = $props();

  // v2.1.0 (пилот 2026-05-16): SSOT thresholds из ratio-classifier.js.
  // Раньше RatioInfoCard считала свою градацию (2/4/6 порогов) → label
  // расходился с sticky header / ModeDerivedExplanation. Теперь все 5
  // коридоров и тексты приходят из одной функции - гарантия консистентности.
  import { classifyRatio, RATIO_THRESHOLDS } from '$lib/ratio-classifier.js';

  const MIN_RATIO = RATIO_THRESHOLDS.ERROR;
  const RECOMMENDED_RATIO = RATIO_THRESHOLDS.WARNING;
  const IDEAL_RATIO = RATIO_THRESHOLDS.IDEAL;

  const ratioClass = $derived(classifyRatio(ratio));
  const statusMeta = $derived({
    label: ratioClass.label,
    tone: ratioClass.tone,
    short: ratioClass.description,
  });

  // Position для visual indicator (linear scale 0..ideal+2).
  const scaleMax = IDEAL_RATIO + 2;
  const indicatorPct = $derived(Math.min(100, (ratio / scaleMax) * 100));

  // Recommendation action - показать если есть weak channels и улучшение значимое.
  const canImprove = $derived(
    weakChannelsCount > 0 &&
    afterExcludeRatio != null &&
    afterExcludeRatio > ratio + 0.3 &&
    ratio < RECOMMENDED_RATIO
  );

  // Tooltip объясняет что такое Ratio + почему важно.
  const RATIO_HELP = [
    'Ratio (соотношение данных) - это N наблюдений / K переменных в модели.',
    '',
    'Например: 52 недели данных и 13 каналов рекламы → ratio 4:1 - на каждую',
    'переменную приходится 4 наблюдения. Чем выше ratio, тем надёжнее модель',
    'может оценить вклад каждого канала.',
    '',
    'Почему важно:',
    '• Низкий ratio (<2:1) - модель «выучит» отдельные точки вместо',
    '  закономерности (overfitting). Высокий R² здесь - артефакт.',
    '• Рекомендуемый ≥4:1 - модель надёжна, но интервалы шире желаемого.',
    '• Идеальный ≥6:1 - узкие доверительные интервалы, можно опираться',
    '  на абсолютные значения ROI/CPU.',
    '',
    'Как повысить: больше истории (≥52 недель), исключить неактивные',
    'каналы (>50% нулей), объединить близкие метрики одного канала.',
  ].join('\n');
</script>

<aside class="ratio-card tone-{statusMeta.tone}" aria-label="Соотношение данных к переменным">
  <header class="card-header">
    <div class="header-left">
      <span class="kicker">КАЧЕСТВО ДАННЫХ</span>
      <h3 class="card-title">
        Соотношение данных
        <span class="help-icon" title={RATIO_HELP} aria-label="Что такое Ratio">?</span>
      </h3>
    </div>
    <div class="ratio-display">
      <span class="ratio-value">{ratio.toFixed(1)}<span class="ratio-suffix">:1</span></span>
      <span class="ratio-status">{statusMeta.label}</span>
    </div>
  </header>

  <!-- 3-zone visual indicator -->
  <div class="indicator-wrapper">
    <div class="indicator-track">
      <div class="zone zone-critical" style="width: {(MIN_RATIO / scaleMax) * 100}%"></div>
      <div class="zone zone-warning" style="width: {((RECOMMENDED_RATIO - MIN_RATIO) / scaleMax) * 100}%"></div>
      <div class="zone zone-acceptable" style="width: {((IDEAL_RATIO - RECOMMENDED_RATIO) / scaleMax) * 100}%"></div>
      <div class="zone zone-excellent" style="width: {((scaleMax - IDEAL_RATIO) / scaleMax) * 100}%"></div>
      <div class="indicator-marker" style="left: {indicatorPct}%" aria-hidden="true"></div>
    </div>
    <div class="indicator-scale">
      <span class="scale-tick" style="left: 0">0</span>
      <span class="scale-tick" style="left: {(MIN_RATIO / scaleMax) * 100}%">{MIN_RATIO}:1<small> мин</small></span>
      <span class="scale-tick" style="left: {(RECOMMENDED_RATIO / scaleMax) * 100}%">{RECOMMENDED_RATIO}:1<small> рек.</small></span>
      <span class="scale-tick" style="left: {(IDEAL_RATIO / scaleMax) * 100}%">{IDEAL_RATIO}:1<small> идеал</small></span>
    </div>
  </div>

  <p class="status-explain">{statusMeta.short}.</p>

  <!-- Action recommendation (manager-friendly) -->
  {#if canImprove && onApplyExclude}
    <div class="action-block">
      <p class="action-text">
        <strong>Достичь рекомендованного {RECOMMENDED_RATIO}:1:</strong>
        исключите {weakChannelsCount} канал{weakChannelsCount === 1 ? '' : weakChannelsCount < 5 ? 'а' : 'ов'}
        с большой долей нулей &rarr; ratio станет
        <strong>{afterExcludeRatio?.toFixed(1)}:1</strong>.
      </p>
      <button type="button" class="btn-apply" onclick={onApplyExclude}>
        Применить рекомендацию
      </button>
    </div>
  {:else if ratioClass.severity === 'success' || ratioClass.severity === 'info'}
    <p class="action-text minor">Данных достаточно. Никаких действий не требуется.</p>
  {:else if ratioClass.severity === 'error'}
    <p class="action-text minor">
      Чтобы повысить ratio: соберите больше истории (≥52 недель) и/или исключите малоактивные каналы, объедините близкие метрики.
    </p>
  {/if}

  <!-- Expert breakdown -->
  {#if expertMode}
    <div class="expert-block">
      <div class="expert-label">EXPERT BREAKDOWN</div>
      <dl class="expert-stats">
        <div><dt>Наблюдений</dt><dd>{nObs}</dd></div>
        <div><dt>Переменных в модели</dt><dd>{nPredictors}</dd></div>
        <!-- F-004 pilot (2026-05-18): single source of truth precision —
             везде .toFixed(1), как в big visual + ratio-value. -->
        <div><dt>Текущий ratio</dt><dd>{ratio.toFixed(1)}:1</dd></div>
        {#if afterExcludeRatio != null && Math.abs(afterExcludeRatio - ratio) >= 0.05}
          <!-- F-006 pilot (2026-05-18): скрываем поле когда weak уже исключены
               (delta < 0.05). Раньше показывало то же что «Текущий ratio» —
               вводило в заблуждение что есть улучшение.
               F-004: precision aligned с «Текущий ratio» (toFixed(1)). -->
          <div><dt>После исключения weak</dt><dd>{afterExcludeRatio.toFixed(1)}:1</dd></div>
        {/if}
      </dl>
      {#if weakChannelNames.length > 0}
        <p class="expert-note">
          <strong>Каналы с &gt;50% нулей ({weakChannelNames.length}):</strong>
          {weakChannelNames.join(', ')}.
        </p>
      {/if}
      <p class="expert-note">
        <strong>Thresholds:</strong> &lt;2:1 - overfit risk; 2-4:1 - модель работает, широкие CI;
        4-6:1 - надёжно; ≥6:1 - узкие CI, можно опираться на абсолютные значения.
      </p>
    </div>
  {/if}
</aside>

<style>
  .ratio-card {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px 22px;
    background: var(--bg-card, #0f172a);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: 6px;
    border-left-width: 3px;
    max-width: 920px;
  }
  .ratio-card.tone-danger  { border-left-color: var(--danger, #f87171); }
  .ratio-card.tone-warn    { border-left-color: var(--gold, #c9a449); }
  .ratio-card.tone-info    { border-left-color: var(--accent-primary, #6366f1); }
  .ratio-card.tone-success { border-left-color: var(--success, #4ade80); }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    flex-wrap: wrap;
  }
  .header-left { display: flex; flex-direction: column; gap: 2px; }
  .kicker {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    color: var(--gold, #c9a449);
    text-transform: uppercase;
  }
  .card-title {
    margin: 0;
    font-family: var(--font-serif, Georgia), serif;
    font-size: 18px;
    font-weight: 400;
    color: var(--text-primary);
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
  }
  /* v1.3.2: help-icon в h3 - premium tier-1 unobtrusive «?» tooltip */
  .card-title .help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--text-muted, #64748b) 16%, transparent);
    color: var(--text-secondary, #94a3b8);
    font-size: 10px;
    font-weight: 700;
    font-family: var(--font-sans), sans-serif;
    cursor: help;
    user-select: none;
    transition: background 0.15s, color 0.15s;
  }
  .card-title .help-icon:hover {
    background: color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
    color: var(--gold, #c9a449);
  }
  .ratio-display {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
  }
  .ratio-value {
    font-family: var(--font-serif, Georgia), serif;
    font-size: 32px;
    line-height: 1;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }
  .ratio-suffix {
    font-size: 18px;
    color: var(--text-muted);
    margin-left: 2px;
  }
  .ratio-status {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .tone-danger      .ratio-status { color: var(--danger, #f87171); }
  /* v2.1.0: warn-strong - между red и amber, для ratio 2-3 (Ниже минимума). */
  .tone-warn-strong .ratio-status { color: color-mix(in srgb, var(--danger, #f87171) 55%, var(--gold, #c9a449) 45%); }
  .tone-warn        .ratio-status { color: var(--gold, #c9a449); }
  .tone-info        .ratio-status { color: var(--accent-primary, #6366f1); }
  .tone-success     .ratio-status { color: var(--success, #4ade80); }
  .tone-neutral     .ratio-status { color: var(--text-muted, #64748b); }

  /* ─── 3-zone indicator track ─── */
  .indicator-wrapper { display: flex; flex-direction: column; gap: 14px; padding: 0 4px; }
  .indicator-track {
    position: relative;
    height: 8px;
    display: flex;
    border-radius: 3px;
    overflow: hidden;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
  }
  .zone.zone-critical   { background: color-mix(in srgb, var(--danger, #f87171) 35%, transparent); }
  .zone.zone-warning    { background: color-mix(in srgb, var(--gold, #c9a449) 30%, transparent); }
  .zone.zone-acceptable { background: color-mix(in srgb, var(--accent-primary, #6366f1) 25%, transparent); }
  .zone.zone-excellent  { background: color-mix(in srgb, var(--success, #4ade80) 30%, transparent); }

  .indicator-marker {
    position: absolute;
    top: -3px;
    width: 3px;
    height: 14px;
    background: var(--text-primary);
    border-radius: 1px;
    transform: translateX(-50%);
    box-shadow: 0 0 0 2px var(--bg-card, #0f172a);
  }

  .indicator-scale {
    position: relative;
    height: 22px;
    font-size: 9.5px;
    color: var(--text-muted, #64748b);
  }
  .scale-tick {
    position: absolute;
    transform: translateX(-50%);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .scale-tick small {
    color: var(--text-muted);
    font-size: 9px;
    margin-left: 2px;
    text-transform: lowercase;
  }
  .scale-tick:first-child { transform: translateX(0); }

  /* ─── Status explanation ─── */
  .status-explain {
    margin: 0;
    font-size: 12.5px;
    line-height: 1.55;
    color: var(--text-secondary);
  }

  /* ─── Action block (manager-friendly) ─── */
  .action-block {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px 14px;
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, transparent);
    border-left: 2px solid var(--gold, #c9a449);
    border-radius: 0 4px 4px 0;
  }
  .action-text {
    margin: 0;
    font-size: 12.5px;
    line-height: 1.55;
    color: var(--text-primary);
  }
  .action-text.minor {
    color: var(--text-muted);
    font-style: italic;
    padding: 4px 0;
  }
  .action-text strong { font-weight: 600; }
  .btn-apply {
    align-self: flex-start;
    padding: 8px 16px;
    border-radius: 3px;
    background: var(--text-primary);
    color: var(--bg-card, #0f172a);
    border: none;
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    cursor: pointer;
    transition: transform 0.15s;
  }
  .btn-apply:hover { transform: translateY(-1px); }

  /* ─── Expert breakdown ─── */
  .expert-block {
    margin-top: 4px;
    padding-top: 14px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .expert-label {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.16em;
    color: var(--gold, #c9a449);
    text-transform: uppercase;
  }
  .expert-stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 10px;
    margin: 0;
  }
  .expert-stats > div { display: flex; flex-direction: column; gap: 2px; }
  .expert-stats dt {
    font-size: 10px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
  }
  .expert-stats dd {
    margin: 0;
    font-size: 14px;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono, Consolas, monospace);
  }
  .expert-note {
    margin: 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-secondary);
  }
  .expert-note strong { color: var(--text-primary); font-weight: 600; }
</style>
