<script>
  /**
   * KPISelector — v1.3.0 first sub-step of Validate (per ADR-015).
   *
   * User выбирает тип target KPI. Этот выбор определяет:
   * - kpi_kind (monetary | count) — влияет на verdicts, отчёты, метрики.
   * - Нужно ли поле value_per_count_unit на следующем sub-step.
   *
   * Emits onSelect(kpi_type) — parent сохраняет в store kpiKind.
   *
   * @component KPISelector
   */

  /** @typedef {'sales' | 'revenue' | 'profit' | 'sales_packs' | 'leads' | 'registrations' | 'loyalty_cards' | 'subscriptions' | 'app_installs' | 'count_custom'} KPIType */

  const { onSelect, currentKPI } = $props();
  /** @type {string | null} */
  let hovered = $state(null);

  // Список KPI вариантов с UI metadata.
  // monetary group:
  const monetaryOptions = [
    { id: 'sales', icon: '💰', title: 'Выручка', subtitle: 'продажи в ₽', desc: 'Стандартный сценарий для CMO / CFO. Главная метрика — ROI каждого канала.' },
    { id: 'revenue', icon: '💵', title: 'Доход', subtitle: 'gross revenue', desc: 'Аналог выручки. Применимо для бизнесов с явным revenue tracking.' },
    { id: 'profit', icon: '📈', title: 'Прибыль', subtitle: 'profit / маржа', desc: 'Если хотите модель в gross/net profit вместо выручки.' },
  ];

  // count group:
  const countOptions = [
    { id: 'sales_packs', icon: '📦', title: 'Продажи в штуках', subtitle: 'упаковки / SKU', desc: 'FMCG, фарма, ритейл — модель оценивает CPU (₽/упак) и сравнивает с маржой.' },
    { id: 'leads', icon: '🎯', title: 'Лиды', subtitle: 'заявки / обращения', desc: 'B2B, страхование, услуги — главная метрика CPU = ₽ за лид. Сравнение с LTV × CR.' },
    { id: 'registrations', icon: '📝', title: 'Регистрации', subtitle: 'sign-ups', desc: 'SaaS, e-commerce — модель оценивает стоимость одной регистрации.' },
    { id: 'loyalty_cards', icon: '💳', title: 'Выданные карты', subtitle: 'loyalty cards', desc: 'Программы лояльности — CPU vs ценность (avg_basket × retention).' },
    { id: 'subscriptions', icon: '🔁', title: 'Подписки', subtitle: 'subscriptions', desc: 'SaaS, медиа — CPU vs MRR на подписку.' },
    { id: 'app_installs', icon: '📱', title: 'Установки', subtitle: 'app installs', desc: 'Mobile-first продукты — CPU vs LTV.' },
    { id: 'count_custom', icon: '✍️', title: 'Свой KPI', subtitle: 'custom counted metric', desc: 'Любая считаемая метрика. Вы зададите label и ценность сами.' },
  ];

  /** @param {string} id */
  function handleSelect(id) {
    onSelect?.(id);
  }
</script>

<div class="kpi-selector">
  <header class="intro">
    <h2>Что измеряем как итог?</h2>
    <p class="lead">
      Выберите целевой показатель — то, на что повлияли каналы рекламы.
      Этот выбор определяет, в каких единицах модель будет оценивать каждый канал.
      <button class="why-link" type="button">Зачем этот шаг? <span class="chevron">▾</span></button>
    </p>
  </header>

  <section class="group">
    <h3 class="group-title"><span class="group-icon">💰</span> В рублях</h3>
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
            <span class="icon">{opt.icon}</span>
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
    <h3 class="group-title"><span class="group-icon">📦</span> В штуках</h3>
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
            <span class="icon">{opt.icon}</span>
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
    <span class="info-icon">ℹ️</span>
    <span>Изменить выбор можно в любой момент — модель пересчитается с новыми метриками.</span>
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
  .chevron { font-size: 9px; }

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
  .group-icon { font-size: 16px; }

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
  .icon { font-size: 24px; line-height: 1; }
  .card-head h4 {
    margin: 0;
    font-size: 15px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }
  /* UX audit v1.3.0: WCAG AA min 12px body text — было 10px (fail). */
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
  .info-icon { font-size: 14px; }
</style>
