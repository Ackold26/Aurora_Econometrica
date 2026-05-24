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
  import Tooltip from '$lib/components/Tooltip.svelte';
  import GlossaryTerm from '$lib/components/GlossaryTerm.svelte';
  import { TOOLTIPS } from '$lib/data/tooltip-texts.js';

  /** @typedef {'sales' | 'revenue' | 'profit' | 'sales_packs' | 'leads' | 'registrations' | 'loyalty_cards' | 'subscriptions' | 'app_installs' | 'count_custom'} KPIType */

  /**
   * @type {{
   *   onSelect: (id: string) => void,
   *   currentKPI: string,
   *   availableKpiTypes?: string[] | null,
   * }}
   */
  // v2.1.0 (пилот 2026-05-17): availableKpiTypes - набор типов которые
  // соответствуют ролям колонок в данных. Frontend disable'ит cards вне
  // этого списка - юзер не может выбрать тип leads если backend нашёл
  // только target_monetary колонку. null = legacy backward compat (все
  // cards enabled).
  const { onSelect, currentKPI, availableKpiTypes = null } = $props();

  /** @param {string} id */
  function isDisabled(id) {
    if (!Array.isArray(availableKpiTypes) || availableKpiTypes.length === 0) {
      return false;
    }
    return !availableKpiTypes.includes(id);
  }
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
  // v2.1.0 (пилот 2026-05-16): убран дубликат «Доход» (kpi_type='revenue') -
  // для целевой аудитории (бренд-менеджер фармы / FMCG) различие между выручкой
  // и доходом бухгалтерское, не операционное. Старые проекты с kpi_type='revenue'
  // продолжают корректно загружаться через kpi_registry (backward compat).
  const monetaryOptions = [
    { id: 'sales',   title: 'Выручка',  subtitle: 'продажи в ₽',    desc: 'Сколько денег принесли продажи.\nГлавная метрика - ROI каждого канала.' },
    { id: 'profit',  title: 'Прибыль', subtitle: 'прибыль / маржа', desc: 'Если у вас есть прибыль с единицы товара\n- модель посчитает в прибыли, а не в выручке.' },
  ];

  // count group:
  const countOptions = [
    { id: 'sales_packs',   title: 'Продажи в штуках', subtitle: 'упаковки / SKU',         desc: 'FMCG, фарма, ритейл\n- модель оценивает CPU (₽/упак) и сравнивает с маржой.' },
    { id: 'leads',         title: 'Лиды',              subtitle: 'заявки / обращения',      desc: 'B2B, страхование, недвижимость\n- главная метрика CPU = ₽ за лид. Сравнение с LTV × CR.' },
    { id: 'registrations', title: 'Регистрации',       subtitle: 'регистрации',              desc: 'SaaS, e-commerce\n- модель оценивает стоимость одной регистрации.' },
    { id: 'loyalty_cards', title: 'Выданные карты',    subtitle: 'банковские и лояльности',  desc: 'Модель считает стоимость выпуска одной карты\nи сравнивает с LTV клиента.' },
    { id: 'subscriptions', title: 'Подписки',          subtitle: 'подписки',                 desc: 'SaaS, онлайн-кинотеатры и т.п.\n- CPU vs MRR на подписку.' },
    { id: 'app_installs',  title: 'Установки',         subtitle: 'установки приложений',     desc: 'Mobile-first продукты\n- CPU vs LTV.' },
    { id: 'count_custom',  title: 'Свой KPI',          subtitle: 'своя метрика',             desc: 'Любая считаемая метрика.\nВы зададите название и ценность сами.' },
  ];

  /** @param {string} id */
  function handleSelect(id) {
    if (isDisabled(id)) return;
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
            <strong>Деньги (₽):</strong> выручка или прибыль. Модель посчитает <GlossaryTerm termId="roi"><strong>ROI</strong></GlossaryTerm> - сколько рублей вернул каждый рубль, вложенный в канал. Подходит когда вы отвечаете перед руководством за финансовый результат.
          </li>
          <li>
            <strong>Штуки:</strong> упаковки, лиды, регистрации, подписки, установки. Модель посчитает <strong>стоимость одной единицы</strong> - сколько рублей нужно потратить, чтобы привести одну продажу / заявку. Подходит для фармы, FMCG, B2B - где известна маржа на единицу.
          </li>
          <li>
            <strong>Своя метрика:</strong> любой счётчик, который вы измеряете сами - звонки, заявки, своя клиентская метрика. Подходит когда стандартные категории не описывают вашу задачу.
          </li>
        </ul>
        <p class="why-tip">
          <strong>Подсказка:</strong> выбирайте KPI, который вы реально измеряете и оптимизируете. Если бизнес считает в штуках (упаковки / лиды) - выбирайте «штуки», даже если у канала бюджет в рублях. Модель умеет связать «потратили N рублей → продали K упаковок».
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
        {@const disabled = isDisabled(opt.id)}
        <Tooltip text={disabled ? 'В ваших данных нет колонки этого типа KPI' : TOOLTIPS[`kpi.${opt.id}`] ?? ''} position="top">
        <button
          type="button"
          class="card monetary"
          class:selected={currentKPI === opt.id}
          class:highlighted={hovered === opt.id}
          class:disabled
          disabled={disabled}
          onmouseenter={() => hovered = opt.id}
          onmouseleave={() => hovered = null}
          onclick={() => handleSelect(opt.id)}
          data-tour-step="kpi-{opt.id}"
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
        </Tooltip>
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
        {@const disabled = isDisabled(opt.id)}
        <Tooltip text={disabled ? 'В ваших данных нет колонки этого типа KPI' : TOOLTIPS[`kpi.${opt.id}`] ?? ''} position="top">
        <button
          type="button"
          class="card count"
          class:selected={currentKPI === opt.id}
          class:highlighted={hovered === opt.id}
          class:disabled
          disabled={disabled}
          onmouseenter={() => hovered = opt.id}
          onmouseleave={() => hovered = null}
          onclick={() => handleSelect(opt.id)}
          data-tour-step="kpi-{opt.id}"
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
        </Tooltip>
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

  /* v2.1.0 (пилот 2026-05-16): фиксированная ширина карточек внутри группы.
     Monetary (Выручка/Прибыль) - 2 широкие карточки 380px каждая.
     Count (штуки) - все 220px фиксированной ширины, auto-fill для переноса.
     Высота единая через min-height на .card. */
  .cards {
    display: grid;
    grid-template-columns: repeat(2, 380px);
    /* v2.1.0 (пилот 2026-05-16): gap 10px - одинаковый с count-cards. */
    gap: 10px;
    justify-content: start;
  }
  .count-cards {
    grid-template-columns: repeat(auto-fill, 235px);
  }

  /* v2.1.0 (пилот 2026-05-16): Tooltip wrapper по умолчанию inline-flex -
     не растягивается на ширину grid-колонки. Override чтобы каждая обёртка
     занимала всю свою колонку, и кнопка-карточка получала фиксированную ширину. */
  .cards :global(.tooltip-wrapper) {
    display: block;
    width: 100%;
  }
  .cards .card {
    width: 100%;
  }
  @media (max-width: 1100px) {
    .cards { grid-template-columns: repeat(2, minmax(280px, 360px)); }
  }
  @media (max-width: 700px) {
    .cards { grid-template-columns: 1fr; }
    .count-cards { grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 14px;
    /* v2.1.0 (пилот 2026-05-16): фиксированная высота - все карточки
       в группе одинаковые независимо от длины desc. */
    height: 150px;
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
  /* v2.1.0 (пилот 2026-05-17): disabled card когда availableKpiTypes
     не содержит этого типа KPI. Юзер не может выбрать leads если в
     данных только target_monetary колонка. */
  .card.disabled,
  .card:disabled {
    opacity: 0.35;
    cursor: not-allowed;
    pointer-events: none;
  }
  .card.disabled:hover {
    transform: none;
    border-color: var(--border-subtle, rgba(255,255,255,0.06));
    box-shadow: none;
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
    /* v2.1.0 (пилот 2026-05-16): \n в desc -> реальные переносы строки. */
    white-space: pre-line;
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
