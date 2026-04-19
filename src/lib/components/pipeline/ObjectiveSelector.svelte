<script>
  /**
   * ObjectiveSelector — full-step selector for analysis objective (ROI / Effectiveness / Manual).
   * Shown before validation: the user's choice determines which metrics are kept in the model.
   *
   * Emits via onSelect(objective) — parent is responsible for calling validateData
   * and applying the objective-based role filtering.
   *
   * @component ObjectiveSelector
   */

  /**
   * @typedef {'roi' | 'effectiveness' | 'manual'} Objective
   */

  const { onSelect } = $props();

  /** @type {Objective | null} */
  let hovered = $state(null);
</script>

<div class="objective-selector">
  <header class="intro">
    <h2>С чего начнём: какая цель у анализа?</h2>
    <p class="lead">
      Перед тем как строить модель, важно определить — <strong>что именно вы измеряете</strong>.
      Этот выбор фундаментально меняет набор метрик, которые модель будет использовать, и смысл финального отчёта.
      <br>
      Проверьте 3 варианта ниже — можно переключить в любой момент, но от этого зависит всё дальнейшее.
    </p>
  </header>

  <div class="cards">
    <!-- ROI -->
    <button
      type="button"
      class="card card-roi"
      class:highlighted={hovered === 'roi'}
      onmouseenter={() => hovered = 'roi'}
      onmouseleave={() => hovered = null}
      onclick={() => onSelect?.('roi')}
    >
      <div class="card-head">
        <span class="icon">💰</span>
        <div>
          <h3>ROI</h3>
          <span class="tagline">финансовая отдача</span>
        </div>
        <span class="card-badge">80% моделей</span>
      </div>

      <div class="section">
        <h4>Когда выбирать</h4>
        <p>Когда нужно понять, какой канал приносит больше рублей выручки на вложенный рубль. Классический сценарий MMM для CMO, CFO — «окупаемость маркетинга».</p>
      </div>

      <div class="section">
        <h4>Что программа сделает</h4>
        <p>Оставит только <strong>денежные показатели</strong> (бюджеты, затраты). Показы, клики, визиты будут исключены как промежуточные метрики, коррелирующие с бюджетом.</p>
      </div>

      <div class="section">
        <h4>К чему приведёт</h4>
        <p>Модель выдаст <strong>ROI каждого канала</strong> — «1 рубль → X рублей выручки». На шаге Оптимизация сможете перераспределить бюджет для роста продаж.</p>
      </div>

      <div class="section typical">
        <h4>Типичные кейсы</h4>
        <p>FMCG, фарма, ритейл, e-commerce при задаче «куда вложить следующий миллион».</p>
      </div>

      <div class="cta">Выбрать ROI →</div>
    </button>

    <!-- EFFECTIVENESS -->
    <button
      type="button"
      class="card card-eff"
      class:highlighted={hovered === 'effectiveness'}
      onmouseenter={() => hovered = 'effectiveness'}
      onmouseleave={() => hovered = null}
      onclick={() => onSelect?.('effectiveness')}
    >
      <div class="card-head">
        <span class="icon">📊</span>
        <div>
          <h3>Эффективность</h3>
          <span class="tagline">физические контакты</span>
        </div>
      </div>

      <div class="section">
        <h4>Когда выбирать</h4>
        <p>Когда бюджеты неточные или непрозрачные (discount-пакеты, in-kind, гибридные закупки), но охват и активность известны. Или цель — оценить не стоимость, а <strong>вклад контакта</strong> в продажи.</p>
      </div>

      <div class="section">
        <h4>Что программа сделает</h4>
        <p>Оставит <strong>физические метрики</strong> — показы (для охватных), клики и визиты (для performance). Бюджеты исключит, чтобы модель оценивала чистый эффект контакта.</p>
      </div>

      <div class="section">
        <h4>К чему приведёт</h4>
        <p>Модель покажет <strong>вклад каждого контакта</strong> — например, «1000 показов OLV → 150 руб выручки». Отвечает на вопрос «какая реклама физически работает».</p>
      </div>

      <div class="section typical">
        <h4>Типичные кейсы</h4>
        <p>Бренд-строительство без жёсткой P&L-привязки, оценка креатива, гибридные медиа-закупки.</p>
      </div>

      <div class="cta">Выбрать Эффективность →</div>
    </button>

    <!-- MANUAL -->
    <button
      type="button"
      class="card card-manual"
      class:highlighted={hovered === 'manual'}
      onmouseenter={() => hovered = 'manual'}
      onmouseleave={() => hovered = null}
      onclick={() => onSelect?.('manual')}
    >
      <div class="card-head">
        <span class="icon">🔧</span>
        <div>
          <h3>Вручную</h3>
          <span class="tagline">гибридный микс</span>
        </div>
      </div>

      <div class="section">
        <h4>Когда выбирать</h4>
        <p>Когда у вас <strong>микс задач</strong>. Например, для OLV хотите видеть показы (где важен охват), а для Performance — бюджеты (CPC-механика завязана на деньги).</p>
      </div>

      <div class="section">
        <h4>Что программа сделает</h4>
        <p>Оставит все метрики, для каждой пары покажет две кнопки (бюджет / контакты). <strong>Выбор за вами</strong> — для каждого канала отдельно.</p>
      </div>

      <div class="section">
        <h4>К чему приведёт</h4>
        <p>Гибридная модель. Больше ручной работы, но максимальная точность под реальный микс каналов. <strong>Рекомендовано опытным специалистам</strong> с пониманием специфики каждого канала.</p>
      </div>

      <div class="section typical">
        <h4>Типичные кейсы</h4>
        <p>Опытные эконометристы, кастомные закупки, сложный медиамикс с несовместимыми метриками.</p>
      </div>

      <div class="cta">Выбрать вручную →</div>
    </button>
  </div>

  <footer class="note">
    <span class="info-icon">ℹ️</span>
    <span>Переключить цель можно в любой момент — программа пересоберёт набор метрик.</span>
  </footer>
</div>

<style>
  .objective-selector {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px;
    max-width: 1280px;
    margin: 0 auto;
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    overflow: hidden;
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
    max-width: 1180px;
    margin: 0;
  }
  .intro strong { color: var(--text-primary); font-weight: 600; }

  .cards {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    flex: 1;
    min-height: 0;
  }

  @media (max-width: 1100px) {
    .cards { grid-template-columns: 1fr; }
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-card, 14px);
    box-shadow: var(--shadow-card);
    cursor: pointer;
    text-align: left;
    color: inherit;
    font: inherit;
    transition: transform var(--hover-timing, 200ms ease-out), border-color 0.2s, box-shadow 0.2s, background 0.2s;
    overflow: hidden;
  }
  .card:hover,
  .card.highlighted {
    border-color: var(--accent-primary);
    box-shadow: var(--shadow-elevation-2);
    transform: var(--hover-transform, translateY(-2px));
  }

  .card-roi:hover,
  .card-roi.highlighted {
    background: var(--card-bg-lemon, var(--bg-card));
    border-color: var(--card-accent-lemon, var(--accent-primary));
  }
  .card-eff:hover,
  .card-eff.highlighted {
    background: var(--card-bg-sage, var(--bg-card));
    border-color: var(--card-accent-sage, var(--success));
  }
  .card-manual:hover,
  .card-manual.highlighted {
    background: var(--card-bg-lavender, var(--bg-card));
    border-color: var(--card-accent-lavender, var(--accent-primary));
  }

  .card-head {
    display: flex;
    align-items: center;
    gap: 14px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border-subtle);
  }
  .icon {
    font-size: 32px;
    line-height: 1;
    flex-shrink: 0;
  }
  .card-head h3 {
    margin: 0;
    font-size: var(--font-xl, 20px);
    font-weight: var(--font-weight-heading, 700);
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }
  .tagline {
    font-size: var(--font-xs, 11px);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .card-badge {
    margin-left: auto;
    padding: 3px 8px;
    background: color-mix(in srgb, var(--accent-primary) 18%, transparent);
    color: var(--accent-primary);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 40%, transparent);
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.02em;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .section { display: flex; flex-direction: column; gap: 4px; }
  .section h4 {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    margin: 0;
  }
  .section p {
    font-size: var(--font-sm, 13px);
    color: var(--text-secondary);
    line-height: 1.55;
    margin: 0;
  }
  .section p strong { color: var(--text-primary); font-weight: 600; }

  .section.typical p {
    font-style: italic;
    color: var(--text-muted);
  }

  .cta {
    margin-top: auto;
    padding: 10px 16px;
    text-align: center;
    background: color-mix(in srgb, var(--accent-primary) 14%, transparent);
    color: var(--accent-primary);
    border-radius: var(--radius-btn, 8px);
    font-weight: 600;
    font-size: var(--font-sm, 13px);
    transition: background 0.15s;
  }
  .card:hover .cta,
  .card.highlighted .cta {
    background: var(--accent-primary);
    color: #fff;
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
    font-size: var(--font-sm, 13px);
  }
  .info-icon { font-size: 16px; flex-shrink: 0; }
</style>
