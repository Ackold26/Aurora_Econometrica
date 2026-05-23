<script>
  /**
   * RecommendationCard - v1.3.1 primary actionable recommendation visual card.
   *
   * Per UX audit findings: actionable «главная рекомендация» спрятана в tip-текстах
   * InsightsPanel. RecommendationCard вытаскивает её как **primary visual element**.
   *
   * Render after Decompose / Optimize / Goal-Seek с main takeaway:
   *   🎯 Главная рекомендация
   *   Перелейте 5.2М ₽ из X в Y → +2.1М ₽ выручки
   *   [Применить в Оптимизацию] [Что если?]
   *
   * @component RecommendationCard
   */

  const {
    icon = null,
    title = 'Главная рекомендация',
    text = '',
    detail = '',
    primaryAction = null,
    secondaryAction = null,
    tone = 'info',
  } = $props();

  // v2.0.0 audit fix: was `const` capturing initial prop value (Svelte 5 anti-pattern)
  // Now reactive via $derived - updates когда parent passes new icon.
  const isComponent = $derived(typeof icon === 'function');
</script>

<div class="recommendation-card tone-{tone}">
  <div class="rec-header">
    <span class="rec-icon">
      {#if isComponent}
        {@const IconComponent = icon}
        <IconComponent size={22} strokeWidth={1.5} />
      {:else if icon}
        {icon}
      {/if}
    </span>
    <h3>{title}</h3>
  </div>
  {#if text}
    <p class="rec-text">{text}</p>
  {/if}
  {#if detail}
    <p class="rec-detail">{detail}</p>
  {/if}
  {#if primaryAction || secondaryAction}
    <div class="rec-actions">
      {#if primaryAction}
        <button type="button" class="btn-primary" onclick={primaryAction.onClick}>
          {primaryAction.label} →
        </button>
      {/if}
      {#if secondaryAction}
        <button type="button" class="btn-secondary" onclick={secondaryAction.onClick}>
          {secondaryAction.label}
        </button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .recommendation-card {
    padding: 16px 20px;
    border-radius: 12px;
    border: 1px solid var(--accent-primary);
    background: linear-gradient(135deg,
      color-mix(in srgb, var(--accent-primary) 8%, transparent),
      color-mix(in srgb, var(--accent-primary) 3%, transparent));
    box-shadow: 0 4px 16px color-mix(in srgb, var(--accent-primary) 12%, transparent);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .recommendation-card.tone-success {
    border-color: var(--success, #4ade80);
    background: linear-gradient(135deg,
      color-mix(in srgb, var(--success, #4ade80) 10%, transparent),
      color-mix(in srgb, var(--success, #4ade80) 3%, transparent));
    box-shadow: 0 4px 16px color-mix(in srgb, var(--success, #4ade80) 12%, transparent);
  }
  .recommendation-card.tone-warn {
    border-color: var(--warning, #fbbf24);
    background: linear-gradient(135deg,
      color-mix(in srgb, var(--warning, #fbbf24) 10%, transparent),
      color-mix(in srgb, var(--warning, #fbbf24) 3%, transparent));
    box-shadow: 0 4px 16px color-mix(in srgb, var(--warning, #fbbf24) 12%, transparent);
  }
  .rec-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .rec-icon { display: flex; align-items: center; flex-shrink: 0; font-size: 22px; line-height: 1; color: var(--text-primary); }
  .rec-header h3 {
    margin: 0;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 700;
    color: var(--text-primary);
  }
  .rec-text {
    margin: 0;
    font-size: 16px;
    line-height: 1.5;
    color: var(--text-primary);
    font-weight: 500;
  }
  .rec-detail {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-secondary);
  }
  .rec-actions {
    display: flex;
    gap: 10px;
    margin-top: 4px;
    flex-wrap: wrap;
  }
  .btn-primary, .btn-secondary {
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    font: inherit;
    transition: background 0.15s, border-color 0.15s;
  }
  .btn-primary {
    background: var(--accent-primary);
    color: #fff;
    border-color: var(--accent-primary);
  }
  .btn-secondary {
    background: var(--bg-card);
    color: var(--text-secondary);
    border-color: var(--border);
  }
  .btn-secondary:hover { border-color: var(--accent-primary); color: var(--accent-primary); }
</style>
