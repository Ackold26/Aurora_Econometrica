<script>
  /**
   * KPISelector - v1.3.0 first sub-step of Validate (per ADR-015).
   *
   * User выбирает тип target KPI. Этот выбор определяет:
   * - kpi_kind (monetary | count) - влияет на verdicts, отчёты, метрики.
   * - Нужно ли поле value_per_count_unit на следующем sub-step.
   *
   * Emits onSelect(kpi_type) - parent сохраняет в store kpiKind.
   *
   * @component KPISelector
   */

  import {
    CircleDollarSign, DollarSign, TrendingUp,
    Package, Target, FileText, CreditCard, Repeat, Smartphone, PenLine,
    Info,
  } from 'lucide-svelte';

  /** @typedef {'sales' | 'revenue' | 'profit' | 'sales_packs' | 'leads' | 'registrations' | 'loyalty_cards' | 'subscriptions' | 'app_installs' | 'count_custom'} KPIType */

  const { onSelect, currentKPI } = $props();
  /** @type {string | null} */
  let hovered = $state(null);

  /** @type {Record<string, any>} */
  const iconMap = {
    sales:         CircleDollarSign,
    revenue:       DollarSign,
    profit:        TrendingUp,
    sales_packs:   Package,
    leads:         Target,
    registrations: FileText,
    loyalty_cards: CreditCard,
    subscriptions: Repeat,
    app_installs:  Smartphone,
    count_custom:  PenLine,
  };

  // Список KPI вариантов с UI metadata.
  // monetary group:
  const monetaryOptions = [
    { id: 'sales',   title: 'Выручка',  subtitle: 'продажи в ₽',     desc: 'Стандартный сценарий для CMO / CFO. Главная метрика - ROI каждого канала.' },
    { id: 'revenue', title: 'Доход',    subtitle: 'gross revenue',    desc: 'Аналог выручки. Применимо для бизнесов с явным revenue tracking.' },
    { id: 'profit',  title: 'Прибыль', subtitle: 'profit / маржа',   desc: 'Если хотите модель в gross/net profit вместо выручки.' },
  ];

  // count group:
  const countOptions = [
    { id: 'sales_packs',   title: 'Продажи в штуках', subtitle: 'упаковки / SKU',         desc: 'FMCG, фарма, ритейл - модель оценивает CPU (₽/упак) и сравнивает с маржой.' },
    { id: 'leads',         title: 'Лиды',              subtitle: 'заявки / обращения',      desc: 'B2B, страхование, услуги - главная метрика CPU = ₽ за лид. Сравнение с LTV × CR.' },
    { id: 'registrations', title: 'Регистрации',       subtitle: 'sign-ups',                desc: 'SaaS, e-commerce - модель оценивает стоимость одной регистрации.' },
    { id: 'loyalty_cards', title: 'Выданные карты',    subtitle: 'loyalty cards',           desc: 'Программы лояльности - CPU vs ценность (avg_basket × retention).' },
    { id: 'subscriptions', title: 'Подписки',          subtitle: 'subscriptions',           desc: 'SaaS, медиа - CPU vs MRR на подписку.' },
    { id: 'app_installs',  title: 'Установки',         subtitle: 'app installs',            desc: 'Mobile-first продукты - CPU vs LTV.' },
    { id: 'count_custom',  title: 'Свой KPI',          subtitle: 'custom counted metric',   desc: 'Любая считаемая метрика. Вы зададите label и ценность сами.' },
  ];

  /** @param {string} id */
  function handleSelect(id) {
    onSelect?.(id);
  }

  // v1.3.2: «Зачем этот шаг?» раскрывающаяся панель с объяснением выбора KPI.
  let whyExpanded = $state(false);
</script>

<div class="kpi-selector">
  <header class="intro">
    <h2>Что измеряем как итог?</h2>
    <p class="lead">
      Выберите целевой показатель - то, на что повлияли каналы рекламы.
      Этот выбор определяет, в каких единицах модель будет оценивать каждый канал.
      <button
        class="why-link"
        type="button"
        aria-expanded={whyExpanded}
        onclick={() => (whyExpanded = !whyExpanded)}
      >Зачем этот шаг? <span class="chevron" class:open={whyExpanded}>▾</span></button>
    </p>
    {#if whyExpanded}
      <div class="why-panel" role="region" aria-label="Подробное объяснение выбора KPI">
        <p><strong>Целевая метрика - это итог, на который влияют каналы рекламы.</strong> Выбор определяет, что модель будет считать «успехом», и в каких единицах оценит каждый канал:</p>
        <ul>
          <li>
            <strong>Деньги (₽):</strong> продажи, выручка, прибыль. Модель посчитает <strong>ROI</strong>: сколько рублей вернул каждый рубль вложений в канал. Подходит для CFO/CMO - финансовая отдача.
          </li>
          <li>
            <strong>Штуки:</strong> упаковки, лиды, регистрации, подписки, установки. Модель посчитает <strong>CPU</strong> (cost per unit): сколько рублей стоит привести одну единицу. Подходит для FMCG, фармы, B2B - где маржа на единицу известна.
          </li>
          <li>
            <strong>Custom counted metric:</strong> своя целевая метрика в штуках (звонки, заявки, customer-метрика). Подходит когда стандартные категории не описывают вашу задачу.
          </li>
        </ul>
        <p class="why-tip">
          <strong>Подсказка:</strong> выбирайте KPI, который вы реально измеряете и оптимизируете. Если бизнес считает в штуках (упаковки/лиды) - выбирайте «штуки», даже если у канала бюджет в рублях. Модель умеет связать «потратили N руб → продали K упаковок» (это и есть CPU).
        </p>
      </div>
    {/if}
  </header>

  <section class="group">
    <h3 class="group-title">
      <span class="group-icon"><CircleDollarSign size={16} strokeWidth={1.5} /></span>
      В рублях
    </h3>
    <div class="cards">
      {#each monetaryOptions as opt (opt.id)}
        <button
          type="button"
          class="card monetary"
          class:selected={currentKPI === opt.id}
          class:highlighted={hovered === opt.id}
          onmouseenter={() => hovered = opt.id}
          onmouseleave={() => hovered = null}
          onclick={() => handleSelect(opt.id)}
        >
          <div class="card-head">
            <span class="icon">
              <svelte:component this={iconMap[opt.id]} size={24} strokeWidth={1.5} />
            </span>
            <div>
              <h4>{opt.title}</h4>
              <span class="subtitle">{opt.subtitle}</span>
            </div>
          </div>
          <p class="desc">{opt.desc}</p>
        </button>
      {/each}
    </div>
  </section>

  <section class="group">
    <h3 class="group-title">
      <span class="group-icon"><Package size={16} strokeWidth={1.5} /></span>
      В штуках
    </h3>
    <div class="cards count-cards">
      {#each countOptions as opt (opt.id)}
        <button
          type="button"
          class="card count"
          class:selected={currentKPI === opt.id}
          class:highlighted={hovered === opt.id}
          onmouseenter={() => hovered = opt.id}
          onmouseleave={() => hovered = null}
          onclick={() => handleSelect(opt.id)}
        >
          <div class="card-head">
            <span class="icon">
              <svelte:component this={iconMap[opt.id]} size={24} strokeWidth={1.5} />
            </span>
            <div>
              <h4>{opt.title}</h4>
              <span class="subtitle">{opt.subtitle}</span>
            </div>
          </div>
          <p class="desc">{opt.desc}</p>
        </button>
      {/each}
    </div>
  </section>

  <footer class="note">
    <span class="info-icon"><Info size={14} strokeWidth={1.5} /></span>
    <span>Изменить выбор можно в любой момент - модель пересчитается с новыми метриками.</span>
  </footer>
</div>

<style>
  .kpi-selector {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px;
    max-width: 1280px;
    margin: 0 auto;
    width: 100%;
  }
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

  /* v1.3.2: «Зачем этот шаг?» раскрывающаяся панель - premium tier-1. */
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

  .group { display: flex; flex-direction: column; gap: 8px; }
  .group-title {
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .group-icon { display: flex; align-items: center; color: var(--text-muted); }

  .cards {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
  }
  .count-cards {
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  }
  @media (max-width: 1100px) {
    .cards { grid-template-columns: 1fr 1fr; }
  }
  @media (max-width: 700px) {
    .cards { grid-template-columns: 1fr; }
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 14px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-card, 12px);
    box-shadow: var(--shadow-card);
    cursor: pointer;
    text-align: left;
    color: inherit;
    font: inherit;
    transition: transform 0.15s, border-color 0.2s, box-shadow 0.2s, background 0.2s;
  }
  .card:hover,
  .card.highlighted {
    border-color: var(--accent-primary);
    box-shadow: var(--shadow-elevation-2);
    transform: translateY(-2px);
  }
  /* UX audit v1.3.0: stronger selected indication (был 8% opacity, almost invisible в dark theme). */
  .card.selected {
    border-color: var(--accent-primary);
    border-width: 2px;
    background: color-mix(in srgb, var(--accent-primary) 18%, transparent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-primary) 15%, transparent);
  }

  .card-head {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .icon { display: flex; align-items: center; justify-content: center; flex-shrink: 0; color: var(--text-secondary); }
  .card-head h4 {
    margin: 0;
    font-size: 15px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }
  /* UX audit v1.3.0: WCAG AA min 12px body text - было 10px (fail). */
  .subtitle {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .desc {
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-secondary);
    margin: 0;
  }
  .note {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 10px 14px;
    background: var(--bg-surface-quiet);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm, 8px);
    color: var(--text-secondary);
    font-size: 12px;
  }
  .info-icon { display: flex; align-items: center; flex-shrink: 0; color: var(--text-muted); }
</style>
