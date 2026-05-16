<script>
  /**
   * StepTaskIntent - Wizard Step 1: choose task type (F4 factor).
   *
   * Per WIZARD_FLOW_v2_FINAL.md §2.1 - 5 options:
   *   1. budget_optimization       - Distribute planned budget
   *   2. inverse_optimization      - Reach a goal, find spend
   *   3. what_if                   - Find optimal budget size
   *   4. forecast_planned_activities - Forecast from planned activities (NEW v2.0.0)
   *   5. decompose-only            - Decompose past period only
   *
   * Cross-product checks:
   *   - Option 4 + history < 24 months → warn Aurora Launch Planner
   *   - Option 5 + no advertising history → warn wide intervals
   *
   * @component StepTaskIntent
   */

  import { Target, Goal, ScanSearch, FileLineChart, BarChart3, Info } from 'lucide-svelte';
  import { wizardState } from '$lib/wizard-state.js';

  /**
   * @type {{
   *   onSelect?: ((taskType: string) => void) | null
   * }}
   */
  const { onSelect = null } = $props();

  /** @type {string | null} */
  let selected = $state(null);

  /** @type {string | null} */
  let hovered = $state(null);

  // ─── Task option definitions ─────────────────────────────────────────────

  /**
   * @typedef {{
   *   id: string,
   *   icon: any,
   *   title: string,
   *   question: string,
   *   tooltip: string,
   *   tone: 'gold' | 'accent' | 'info' | 'neutral' | 'muted'
   * }} TaskOption
   */

  /** @type {readonly TaskOption[]} */
  const TASK_OPTIONS = [
    {
      id: 'budget_optimization',
      icon: Target,
      title: 'Распределить плановый бюджет',
      question: 'У меня бюджет на следующий период - как распределить между каналами?',
      tooltip: 'Прямая оптимизация (Robyn-style): модель находит распределение, максимизирующее KPI при заданном суммарном бюджете.',
      tone: 'gold',
    },
    {
      id: 'inverse_optimization',
      icon: Goal,
      title: 'Достичь цели - сколько потратить?',
      question: 'У меня целевой объём продаж - какой минимальный бюджет для его достижения?',
      tooltip: 'Обратная оптимизация: модель ищет минимальные вложения для достижения указанной цели по KPI.',
      tone: 'accent',
    },
    {
      id: 'what_if',
      icon: ScanSearch,
      title: 'Найти оптимальный размер бюджета',
      question: 'Имеет ли смысл наращивать бюджет? Где точка насыщения?',
      tooltip: 'What-if анализ: модель строит кривые отдачи в диапазоне бюджетов (базовый ±50%) и определяет точку marginal ROI.',
      tone: 'info',
    },
    {
      id: 'forecast_planned_activities',
      icon: FileLineChart,
      title: 'Прогноз по моему плану активностей',
      question: 'Я уже спланировал кампанию - что прогнозирует модель при этом плане?',
      tooltip: 'NEW v2.0.0: загрузите файл с плановыми активностями по каналам. Модель предскажет ожидаемый KPI с доверительными интервалами.',
      tone: 'neutral',
    },
    {
      id: 'decompose-only',
      icon: BarChart3,
      title: 'Декомпозировать прошлый период',
      question: 'Понять вклад каждого канала в прошлом периоде - без оптимизации.',
      tooltip: 'Только декомпозиция: модель оценивает исторические вклады (attribution) без шага оптимизации. Подходит для аудита прошлых кампаний.',
      tone: 'muted',
    },
  ];

  // ─── Cross-product warnings ──────────────────────────────────────────────

  /** History months from auto-detect results */
  const historyMonths = $derived(
    /** @type {number} */ ($wizardState.autoDetectResults?.data_signature?.history_months ?? 0)
  );

  /** Active advertising check from auto-detect */
  const activeAdvertisingPct = $derived(
    /** @type {number} */ ($wizardState.autoDetectResults?.data_signature?.active_advertising_pct ?? 1)
  );

  /**
   * Inline warning message for selected option, based on data signature.
   * @type {string | null}
   */
  const crossProductWarning = $derived.by(() => {
    if (!selected) return null;
    if (selected === 'forecast_planned_activities' && historyMonths > 0 && historyMonths < 24) {
      return 'Для прогноза нужна обученная модель - у вас данных мало (менее 24 месяцев). ' +
             'Aurora Launch Planner подойдёт лучше для нового продукта с прокси-категорией.';
    }
    if (selected === 'decompose-only' && activeAdvertisingPct < 0.5) {
      return 'Декомпозицию запустить можно, но при малой доле периодов с рекламой ' +
             'доверительные интервалы вкладов будут широкими.';
    }
    return null;
  });

  // ─── Handlers ────────────────────────────────────────────────────────────

  /** @param {string} id */
  function handleSelect(id) {
    selected = id;
    onSelect?.(id);
  }
</script>

<div class="step-task-intent">
  <header class="intro">
    <h2>Что вы хотите получить от анализа?</h2>
    <p class="lead">
      Выберите задачу - программа настроит все параметры автоматически.
    </p>
  </header>

  <div class="cards-grid">
    {#each TASK_OPTIONS as opt (opt.id)}
      {@const Icon = opt.icon}
      <button
        type="button"
        class="task-card tone-{opt.tone}"
        class:selected={selected === opt.id}
        class:highlighted={hovered === opt.id}
        onmouseenter={() => (hovered = opt.id)}
        onmouseleave={() => (hovered = null)}
        onclick={() => handleSelect(opt.id)}
        aria-pressed={selected === opt.id}
        title={opt.tooltip}
      >
        <div class="card-top">
          <span class="card-icon">
            <Icon size={28} strokeWidth={1.5} />
          </span>
          {#if opt.id === 'forecast_planned_activities'}
            <span class="new-badge">NEW</span>
          {/if}
        </div>

        <div class="card-body">
          <h3 class="card-title">{opt.title}</h3>
          <p class="card-question">{opt.question}</p>
        </div>

        <!-- Tooltip hint (shown on hover in expert mode or always visible toggle) -->
        <div class="tooltip-area" aria-hidden="true">
          <Info size={12} strokeWidth={1.5} />
          <span class="tooltip-text">{opt.tooltip}</span>
        </div>

        {#if selected === opt.id}
          <div class="selected-strip" aria-hidden="true"></div>
        {/if}
      </button>
    {/each}
  </div>

  <!-- Cross-product warning -->
  {#if crossProductWarning}
    <div class="cross-warning" role="alert">
      <Info size={14} strokeWidth={1.5} />
      <span>{crossProductWarning}</span>
    </div>
  {/if}
</div>

<style>
  .step-task-intent {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px 24px;
  }

  /* ─── Header ─── */
  .intro h2 {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0 0 4px;
    letter-spacing: -0.01em;
  }
  .lead {
    font-size: 12.5px;
    color: var(--text-secondary);
    margin: 0;
    line-height: 1.5;
  }

  /* ─── Cards grid - 2 columns ─── */
  .cards-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  @media (max-width: 700px) {
    .cards-grid { grid-template-columns: 1fr; }
  }

  /* ─── Task card ─── */
  .task-card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px 18px 18px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    box-shadow: var(--shadow-card, 0 2px 16px rgba(0,0,0,0.4));
    cursor: pointer;
    text-align: left;
    color: inherit;
    font: inherit;
    overflow: hidden;
    transition:
      transform 0.15s ease-out,
      border-color 0.18s,
      box-shadow 0.18s,
      background 0.18s;
  }
  .task-card:hover,
  .task-card.highlighted {
    transform: translateY(-2px);
    border-color: var(--accent-primary);
    box-shadow: var(--shadow-elevation-2, 0 0 24px rgba(59,130,246,0.12));
  }

  /* Tone-specific hover accents */
  .task-card.tone-gold:hover,
  .task-card.tone-gold.highlighted {
    border-color: var(--gold, #c9a449);
    box-shadow: 0 0 24px color-mix(in srgb, var(--gold, #c9a449) 18%, transparent);
  }
  .task-card.tone-accent:hover,
  .task-card.tone-accent.highlighted {
    border-color: var(--accent-primary);
    box-shadow: var(--shadow-elevation-2);
  }

  /* Selected: gold border + scale + background tint */
  .task-card.selected {
    border-color: var(--gold, #c9a449);
    border-width: 2px;
    background: color-mix(in srgb, var(--gold, #c9a449) 8%, var(--bg-card, #181824));
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--gold, #c9a449) 18%, transparent),
      0 4px 20px rgba(0,0,0,0.4);
    transform: scale(1.012);
  }

  /* ─── Card top row: icon + optional badge ─── */
  .card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .card-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 46px;
    height: 46px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--gold, #c9a449) 10%, var(--bg-secondary, #141420));
    color: var(--gold, #c9a449);
    flex-shrink: 0;
    transition: background 0.18s;
  }
  .task-card:hover .card-icon,
  .task-card.highlighted .card-icon {
    background: color-mix(in srgb, var(--gold, #c9a449) 18%, var(--bg-secondary, #141420));
  }

  .new-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 6px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 50%, transparent);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--accent-primary);
    flex-shrink: 0;
  }

  /* ─── Card body ─── */
  .card-body {
    display: flex;
    flex-direction: column;
    gap: 5px;
    flex: 1;
  }
  .card-title {
    margin: 0;
    font-size: 15px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.01em;
    line-height: 1.25;
  }
  .card-question {
    margin: 0;
    font-size: 12.5px;
    color: var(--text-secondary);
    line-height: 1.5;
  }

  /* ─── Tooltip hint area ─── */
  .tooltip-area {
    display: flex;
    align-items: flex-start;
    gap: 5px;
    color: var(--text-muted, #7A7A90);
    font-size: 11px;
    line-height: 1.4;
    opacity: 0;
    transition: opacity 0.15s;
  }
  .task-card:hover .tooltip-area,
  .task-card.selected .tooltip-area {
    opacity: 1;
  }
  .tooltip-text {
    font-style: italic;
  }

  /* ─── Selected strip ─── */
  .selected-strip {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--gold, #c9a449);
    border-radius: 0 0 var(--radius-card, 12px) var(--radius-card, 12px);
  }

  /* ─── Cross-product warning ─── */
  .cross-warning {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--accent-primary) 8%, var(--bg-secondary, #141420));
    border-left: 2px solid var(--accent-primary);
    border-radius: 0 6px 6px 0;
    font-size: 12.5px;
    color: var(--text-secondary);
    line-height: 1.5;
  }
  .cross-warning > :global(svg) { flex-shrink: 0; color: var(--accent-primary); margin-top: 1px; }
</style>
