<script>
  /**
   * AnalysisModeSelector - v2.0.0 wizard step: choose analysis mode.
   *
   * Manager mode (default): 2 cards - «ROI режим» / «Эффективность режим».
   * Expert mode ($expertMode === true): 3-я карточка «Смешанный (Expert)» появляется.
   *
   * Per §2 WIZARD_FLOW_v2_FINAL.md + PRE_FLIGHT_FIXES.md N1:
   *   'roi'           → все каналы в ₽, модель считает ROI / CPU.
   *   'effectiveness' → все каналы в физических метриках (TRP/показы/клики),
   *                     модель считает доли вклада в %.
   *   'mixed'         → поканальный выбор (только Expert mode).
   *
   * Dual-mode UX precedent: RatioInfoCard.svelte.
   * Styling: matches KPISelector.svelte premium tier-1 vocabulary.
   *
   * @component AnalysisModeSelector
   */

  import { CircleDollarSign, BarChart2, Settings2 } from 'lucide-svelte';
  import { analysisMode, expertMode } from '$lib/project-state.js';

  /** @typedef {'roi' | 'effectiveness' | 'mixed'} AnalysisMode */

  /**
   * @type {{
   *   onSelect?: ((mode: AnalysisMode) => void) | null
   * }}
   */
  const { onSelect = null } = $props();

  /** @type {string | null} */
  let hovered = $state(null);

  /** WhyThisStep expanding panel */
  let whyExpanded = $state(false);

  /** @param {AnalysisMode} mode */
  function handleSelect(mode) {
    analysisMode.set(mode);
    onSelect?.(mode);
  }

  /** @type {readonly {id: AnalysisMode, icon: any, title: string, subtitle: string, body: string[], expertOnly: boolean, tone: string, badge?: string}[]} */
  const cards = [
    {
      id: 'roi',
      icon: CircleDollarSign,
      title: 'ROI режим',
      subtitle: 'Все каналы в ₽',
      // v2.1.0 (пилот 2026-05-16): badge «90% моделей» - anchoring для бренд-менеджера,
      // подсказывает что это самый распространённый выбор.
      badge: '90% моделей',
      body: [
        // v2.1.0 (пилот 2026-05-16): унифицировано с «Эффективность» - «KPI любой».
        'KPI любой',
        'Модель считает ROI / CPU',
        'Подходит при точных данных бюджетов',
      ],
      expertOnly: false,
      tone: 'monetary',
    },
    {
      id: 'effectiveness',
      icon: BarChart2,
      title: 'Эффективность режим',
      subtitle: 'Все каналы в физических метриках (TRP, показы, клики)',
      body: [
        'KPI любой',
        'Модель считает доли вклада в %',
        'Подходит при непрозрачных бюджетах (агентские скидки, доступ только к GRP)',
      ],
      expertOnly: false,
      tone: 'physical',
    },
    {
      id: 'mixed',
      icon: Settings2,
      title: 'Смешанный (Expert)',
      subtitle: '⚠ Поканальный выбор единиц',
      body: [
        'Требует ставки конверсии для физ. каналов',
        'Точность ROI ±10-25% дополнительной неопределённости',
        'Только для опытных эконометристов и аналитиков',
      ],
      expertOnly: true,
      tone: 'expert',
    },
  ];

  /** Visible cards - expert-only hidden unless $expertMode */
  const visibleCards = $derived(
    cards.filter(c => !c.expertOnly || $expertMode)
  );
</script>

<div class="mode-selector">
  <header class="intro">
    <h2>Выберите режим анализа</h2>
    <p class="lead">
      Определяет, в каких единицах подаются медиа-каналы в модель.
      <button
        type="button"
        class="why-link"
        aria-expanded={whyExpanded}
        onclick={() => (whyExpanded = !whyExpanded)}
      >Зачем выбирать режим? <span class="chevron" class:open={whyExpanded}>▾</span></button>
    </p>

    {#if whyExpanded}
      <div class="why-panel" role="region" aria-label="Подробное объяснение выбора режима анализа">
        <p>
          <strong>Режим определяет единицы медиа-каналов</strong> - в чём вы подаёте активность
          каждого канала в модель. Это не зависит от выбранного KPI.
        </p>
        <ul>
          <li>
            <strong>ROI режим (₽):</strong> все каналы в рублях (бюджеты спенда). Модель напрямую
            оценивает финансовую отдачу - ROI (₽ выручки / ₽ вложений) или CPU (₽ за единицу KPI).
            Подходит когда данные бюджетов точные: прямые закупки или прозрачные агентские размещения.
          </li>
          <li>
            <strong>Эффективность режим (физика):</strong> каналы в физических метриках -
            TRP для ТВ, показы для Digital/OOH, клики для Performance. Модель считает
            вклад каждого канала в % от KPI, без пересчёта в деньги. Оптимален когда
            бюджеты непрозрачны (агентские скидки, ГРП по скидкам, доступ только к физическим метрикам).
          </li>
          <li>
            <strong>Смешанный (Expert):</strong> поканальный выбор единиц - часть каналов в ₽,
            часть в физических метриках. Требует указания ставок конверсии для физ. каналов
            (CPP/CPM). Добавляет ±10-25% неопределённости в ROI. Только для опытных аналитиков.
          </li>
        </ul>
        <p class="why-tip">
          <strong>Рекомендация:</strong> если сомневаетесь - выберите «Эффективность режим».
          Он даёт стабильные оценки вкладов даже при неточных бюджетных данных. Переключить
          режим можно в любой момент - модель пересчитается.
        </p>
      </div>
    {/if}
  </header>

  <div
    class="cards-grid"
    class:two-col={!$expertMode}
    class:three-col={$expertMode}
  >
    {#each visibleCards as card (card.id)}
      {@const CardIcon = card.icon}
      <button
        type="button"
        class="mode-card tone-{card.tone}"
        class:selected={$analysisMode === card.id}
        class:highlighted={hovered === card.id}
        onmouseenter={() => (hovered = card.id)}
        onmouseleave={() => (hovered = null)}
        onclick={() => handleSelect(card.id)}
        aria-pressed={$analysisMode === card.id}
      >
        <div class="card-head">
          <span class="card-icon" class:icon-expert={card.tone === 'expert'}>
            <CardIcon size={32} strokeWidth={1.5} />
          </span>
          {#if card.tone === 'expert'}
            <span class="expert-badge">EXPERT</span>
          {/if}
          <!-- v2.1.0 (rc2 пилот retry): «90% моделей» badge перенесён в
               правый верхний угол карточки (как EXPERT для Mixed),
               вместо рядом с заголовком. -->
          {#if card.badge && card.tone !== 'expert'}
            <span class="card-corner-badge" aria-label="Подсказка">{card.badge}</span>
          {/if}
        </div>

        <div class="card-body">
          <h3 class="card-title">{card.title}</h3>
          <p class="card-subtitle">{card.subtitle}</p>
          <ul class="card-features">
            {#each card.body as line}
              <li>{line}</li>
            {/each}
          </ul>
        </div>

        {#if $analysisMode === card.id}
          <div class="selected-indicator" aria-hidden="true"></div>
        {/if}
      </button>
    {/each}
  </div>

  {#if !$expertMode}
    <p class="expert-hint">
      Нужен поканальный выбор единиц? Включите
      <strong>режим эксперта</strong> в настройках — появится третий вариант.
    </p>
  {/if}
</div>

<style>
  .mode-selector {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px;
    max-width: 1280px;
    margin: 0 auto;
    width: 100%;
  }

  /* ─── Header ─── */
  .intro h2 {
    font-size: 18px;
    font-weight: var(--font-weight-heading, 600);
    color: var(--text-primary);
    margin: 0 0 4px;
    letter-spacing: -0.01em;
  }
  .intro .lead {
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1.5;
    margin: 0;
  }
  .why-link {
    background: none;
    border: none;
    color: var(--accent-primary);
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    padding: 0 4px;
    text-decoration: underline dashed;
    text-underline-offset: 2px;
  }
  .why-link:hover { color: var(--gold, #c9a449); }
  .chevron {
    font-size: 9px;
    display: inline-block;
    transition: transform 0.2s;
  }
  .chevron.open { transform: rotate(180deg); }

  /* ─── Why panel ─── */
  .why-panel {
    margin-top: 12px;
    padding: 14px 18px;
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, var(--bg-card, #0f172a));
    border-left: 2px solid var(--gold, #c9a449);
    border-radius: 0 6px 6px 0;
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--text-secondary);
  }
  .why-panel p { margin: 0 0 8px; }
  .why-panel p:last-child { margin-bottom: 0; }
  .why-panel ul { margin: 0 0 12px; padding-left: 18px; }
  .why-panel li { padding: 3px 0; }
  .why-panel strong { color: var(--text-primary); font-weight: 600; }
  .why-tip {
    margin-top: 10px !important;
    padding-top: 10px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    color: var(--text-primary);
  }

  /* ─── Cards grid ─── */
  .cards-grid {
    display: grid;
    gap: 12px;
  }
  .two-col   { grid-template-columns: 1fr 1fr; }
  .three-col { grid-template-columns: 1fr 1fr 1fr; }

  @media (max-width: 900px) {
    .two-col,
    .three-col { grid-template-columns: 1fr; }
  }

  /* ─── Mode card ─── */
  .mode-card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 18px 20px 20px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    box-shadow: var(--shadow-card, 0 2px 16px rgba(0,0,0,0.4));
    cursor: pointer;
    text-align: left;
    color: inherit;
    font: inherit;
    transition:
      transform 0.15s ease-out,
      border-color 0.18s ease,
      box-shadow 0.18s ease,
      background 0.18s ease;
    overflow: hidden;
  }

  .mode-card:hover,
  .mode-card.highlighted {
    border-color: var(--accent-primary);
    box-shadow: var(--shadow-elevation-2, 0 0 24px rgba(59,130,246,0.12));
    transform: translateY(-2px);
  }

  /* Monetary (ROI) card hover accent */
  .mode-card.tone-monetary:hover,
  .mode-card.tone-monetary.highlighted {
    border-color: var(--gold, #c9a449);
    box-shadow: 0 0 24px color-mix(in srgb, var(--gold, #c9a449) 20%, transparent);
  }

  /* Physical (Effectiveness) card hover accent */
  .mode-card.tone-physical:hover,
  .mode-card.tone-physical.highlighted {
    border-color: var(--accent-primary);
    box-shadow: var(--shadow-elevation-2);
  }

  /* Expert card hover accent */
  .mode-card.tone-expert:hover,
  .mode-card.tone-expert.highlighted {
    border-color: var(--warning, #F59E0B);
    box-shadow: 0 0 24px color-mix(in srgb, var(--warning, #F59E0B) 15%, transparent);
  }

  /* ─── Selected state: thick gold border + scale-up ─── */
  .mode-card.selected {
    border-color: var(--gold, #c9a449);
    border-width: 2px;
    background: color-mix(in srgb, var(--gold, #c9a449) 10%, var(--bg-card, #181824));
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--gold, #c9a449) 20%, transparent),
      0 4px 20px rgba(0,0,0,0.4);
    transform: scale(1.015);
  }

  /* Expert card selected: warning accent */
  .mode-card.tone-expert.selected {
    border-color: var(--warning, #F59E0B);
    background: color-mix(in srgb, var(--warning, #F59E0B) 8%, var(--bg-card, #181824));
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--warning, #F59E0B) 18%, transparent),
      0 4px 20px rgba(0,0,0,0.4);
  }

  /* ─── Card head: icon + optional badge ─── */
  .card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 8px;
  }
  .card-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 52px;
    height: 52px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--gold, #c9a449) 10%, var(--bg-secondary, #141420));
    color: var(--gold, #c9a449);
    flex-shrink: 0;
    transition: background 0.18s;
  }
  .card-icon.icon-expert {
    background: color-mix(in srgb, var(--warning, #F59E0B) 10%, var(--bg-secondary, #141420));
    color: var(--warning, #F59E0B);
  }
  .mode-card:hover .card-icon,
  .mode-card.highlighted .card-icon {
    background: color-mix(in srgb, var(--gold, #c9a449) 18%, var(--bg-secondary, #141420));
  }
  .mode-card.tone-expert:hover .card-icon,
  .mode-card.tone-expert.highlighted .card-icon {
    background: color-mix(in srgb, var(--warning, #F59E0B) 18%, var(--bg-secondary, #141420));
  }

  .expert-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 7px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--warning, #F59E0B) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 40%, transparent);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--warning, #F59E0B);
    flex-shrink: 0;
  }

  /* v2.1.0 (rc2 retry): «90% моделей» badge в правом верхнем углу карточки. */
  .card-corner-badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 8px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--accent-primary) 18%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 35%, transparent);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.02em;
    color: var(--accent-primary);
    flex-shrink: 0;
    white-space: nowrap;
  }

  /* ─── Card body ─── */
  .card-body {
    display: flex;
    flex-direction: column;
    gap: 6px;
    flex: 1;
  }
  /* v2.1.0 (пилот 2026-05-16): card-title-row для размещения title + badge на одной линии. */
  .card-title-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .card-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--accent-primary) 18%, transparent);
    color: var(--accent-primary);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 35%, transparent);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
    line-height: 1.4;
    white-space: nowrap;
  }
  .card-title {
    margin: 0;
    font-size: 16px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.01em;
    line-height: 1.2;
  }
  .card-subtitle {
    margin: 0;
    font-size: 11px;
    color: var(--gold, #c9a449);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 600;
    line-height: 1.4;
  }
  .mode-card.tone-expert .card-subtitle {
    color: var(--warning, #F59E0B);
  }
  .card-features {
    margin: 4px 0 0;
    padding-left: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .card-features li {
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-secondary);
    padding-left: 14px;
    position: relative;
  }
  .card-features li::before {
    content: '•';
    position: absolute;
    left: 2px;
    color: var(--text-muted, #7A7A90);
  }

  /* ─── Selected bottom indicator strip ─── */
  .selected-indicator {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--gold, #c9a449);
    border-radius: 0 0 var(--radius-card, 12px) var(--radius-card, 12px);
  }
  .mode-card.tone-expert .selected-indicator {
    background: var(--warning, #F59E0B);
  }

  /* ─── Expert hint footer ─── */
  .expert-hint {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    margin: 0;
    padding: 8px 12px;
    background: var(--bg-surface-quiet, rgba(20,20,30,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
    line-height: 1.5;
  }
  .expert-hint strong { color: var(--text-secondary); font-weight: 600; }
</style>
