<script>
  /**
   * ModeDerivedExplanation - v1.3.0 final sub-step of Validate (per ADR-015).
   *
   * Показывает юзеру derived mode (ROI / Эффективность / Вручную) + plain-text
   * объяснение почему. Это «эпилог» Валидации - ничего не выбирает, только
   * подтверждает результат и переводит на следующий шаг.
   *
   * @component ModeDerivedExplanation
   */

  /** @typedef {'roi' | 'effectiveness' | 'manual'} DerivedMode */

  const {
    derivedMode,    // DerivedMode
    explanation,    // plain-text объяснение (с backend mode_inference.derive_mode_with_explanation)
    perChannelInput, // {channel: 'monetary'|'physical'} - для summary
    kpiKind,        // 'monetary' | 'count'
    onContinue,     // callback () - переход к Импорт/Модель
  } = $props();

  /** @type {Record<string, string>} */
  const modeIconMap = {
    roi: '💰',
    effectiveness: '📊',
    manual: '🎛️',
  };
  /** @type {Record<string, string>} */
  const modeNameMap = {
    roi: 'ROI',
    effectiveness: 'Эффективность',
    manual: 'Вручную (смешанный)',
  };

  // Подсчёт сводки по input metrics.
  const metricsSummary = $derived.by(() => {
    let monetary = 0;
    let physical = 0;
    for (const v of Object.values(perChannelInput || {})) {
      if (v === 'monetary') monetary++;
      if (v === 'physical') physical++;
    }
    return { monetary, physical, total: monetary + physical };
  });
</script>

<div class="mode-explanation">
  <header>
    <div class="mode-badge mode-{derivedMode}">
      <span class="mode-icon">{modeIconMap[derivedMode]}</span>
      <span class="mode-label">Режим модели: <strong>{modeNameMap[derivedMode]}</strong></span>
    </div>
  </header>

  <section class="explanation">
    <p>{explanation}</p>
  </section>

  <section class="summary">
    <h3>Сводка ваших выборов:</h3>
    <ul>
      <li>
        <span class="bullet">📈</span>
        Целевая метрика: <strong>{kpiKind === 'monetary' ? 'денежная (₽)' : 'считаемая (штуки)'}</strong>
      </li>
      <li>
        <span class="bullet">📊</span>
        Каналов: <strong>{metricsSummary.total}</strong>
        {#if metricsSummary.total > 0}
          ({metricsSummary.monetary > 0 ? `${metricsSummary.monetary} в ₽` : ''}{metricsSummary.monetary > 0 && metricsSummary.physical > 0 ? ', ' : ''}{metricsSummary.physical > 0 ? `${metricsSummary.physical} в контактах` : ''})
        {/if}
      </li>
    </ul>
  </section>

  {#if derivedMode === 'effectiveness' || derivedMode === 'manual'}
    <aside class="hint-box">
      <span class="emoji">💡</span>
      <div>
        <strong>Подсказка:</strong> в режиме {derivedMode === 'effectiveness' ? 'Эффективность' : 'Вручную'}
        сравнение каналов идёт через долю в продажах (sales share %).
        Если нужна оценка cost-effectiveness каналов между собой - на шаге Декомпозиция
        вы сможете добавить ценники контактов (CPM/CPC/CPP) для перехода к виртуальному ROI.
      </div>
    </aside>
  {/if}

  <footer class="actions">
    <button type="button" class="btn-primary" onclick={() => onContinue?.()}>
      Перейти к моделированию →
    </button>
  </footer>
</div>

<style>
  .mode-explanation {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px;
    max-width: 800px;
    margin: 0 auto;
    width: 100%;
  }
  header { display: flex; }
  .mode-badge {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    border-radius: 999px;
    background: var(--bg-card);
    border: 1.5px solid var(--accent-primary);
    color: var(--accent-primary);
  }
  .mode-badge.mode-effectiveness { color: var(--success, #4ade80); border-color: var(--success, #4ade80); }
  .mode-badge.mode-manual { color: var(--warning, #fbbf24); border-color: var(--warning, #fbbf24); }

  .mode-icon { font-size: 20px; }
  .mode-label { font-size: 13px; font-weight: 500; }
  .mode-label strong { font-weight: 700; }

  .explanation p {
    margin: 0;
    font-size: 14px;
    line-height: 1.6;
    color: var(--text-primary);
  }
  .summary h3 {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin: 0 0 8px;
    font-weight: 700;
  }
  .summary ul {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .summary li {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 13px;
    color: var(--text-secondary);
  }
  .summary li strong { color: var(--text-primary); font-weight: 600; }
  .bullet { font-size: 14px; line-height: 1; }

  .hint-box {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    padding: 12px 16px;
    background: color-mix(in srgb, var(--accent-primary) 6%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 22%, transparent);
    border-radius: var(--radius-card, 8px);
    font-size: 12px;
    line-height: 1.5;
    color: var(--text-secondary);
  }
  .hint-box .emoji { font-size: 18px; line-height: 1.2; }
  .hint-box strong { color: var(--text-primary); font-weight: 600; }

  .actions { display: flex; justify-content: flex-end; }
  .btn-primary {
    padding: 12px 22px;
    border-radius: var(--radius-btn, 8px);
    font-size: 14px;
    font-weight: 600;
    background: var(--accent-primary);
    color: #fff;
    border: 1px solid var(--accent-primary);
    cursor: pointer;
    font: inherit;
  }
</style>
