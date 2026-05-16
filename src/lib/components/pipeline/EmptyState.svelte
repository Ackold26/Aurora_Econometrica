<script>
  /**
   * EmptyState - Phase 2.15 / Audit P-premium-feel.
   *
   * Reusable component for «no data yet» scenarios. Replaces inline
   * «Каналы определятся после импорта данных» style messages с
   * consistent visual vocabulary.
   *
   * Variants:
   * - 'info' (default) - neutral grey, just informative
   * - 'action' - выделен gold accent, has primary CTA
   *
   * Includes optional icon (SVG inline or text emoji) + title + body +
   * optional CTA button.
   *
   * Usage:
   *   <EmptyState
   *     title="Импортируйте данные"
   *     body="После импорта мы автоматически определим типы колонок..."
   *     variant="action"
   *     ctaText="Импортировать"
   *     onCta={() => goto('/pipeline?step=import')}
   *   />
   */

  /**
   * @type {{
   *   title?: string,
   *   body?: string,
   *   icon?: string,
   *   variant?: 'info' | 'action',
   *   ctaText?: string,
   *   onCta?: () => void,
   *   compact?: boolean,
   * }}
   */
  const {
    title = '',
    body = '',
    icon = '',
    variant = 'info',
    ctaText = '',
    onCta = undefined,
    compact = false,
  } = $props();

  const hasCta = $derived(Boolean(ctaText && onCta));
</script>

<div
  class="empty-state empty-state--{variant}"
  class:compact
  role="status"
  data-testid="empty-state"
>
  {#if icon}
    <div class="empty-icon" aria-hidden="true">{icon}</div>
  {/if}
  {#if title}
    <h3 class="empty-title">{title}</h3>
  {/if}
  {#if body}
    <p class="empty-body">{body}</p>
  {/if}
  {#if hasCta}
    <button type="button" class="empty-cta" onclick={onCta} data-testid="empty-state-cta">
      {ctaText}
    </button>
  {/if}
</div>

<style>
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 8px;
    padding: 32px 24px;
    border: 1px dashed var(--border-subtle, rgba(255, 255, 255, 0.12));
    border-radius: var(--radius-card, 12px);
    background: color-mix(in srgb, var(--text-primary) 1%, transparent);
  }
  .empty-state.compact {
    padding: 16px 14px;
    gap: 4px;
  }
  .empty-state--action {
    border-color: color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
    border-style: solid;
    background: color-mix(in srgb, var(--gold, #c9a449) 3%, transparent);
  }
  .empty-icon {
    font-size: 22px;
    color: var(--text-muted, #7A7A90);
    line-height: 1;
  }
  .empty-state--action .empty-icon {
    color: var(--gold, #c9a449);
  }
  .empty-title {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .empty-body {
    margin: 0;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-secondary, #b6b6c5);
    max-width: 360px;
  }
  .empty-cta {
    margin-top: 4px;
    padding: 7px 14px;
    background: var(--gold, #c9a449);
    color: var(--bg-card, #181824);
    border: none;
    border-radius: 6px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
  }
  @media (prefers-reduced-motion: no-preference) {
    .empty-cta {
      transition: background 0.15s;
    }
    .empty-cta:hover {
      background: color-mix(in srgb, var(--gold, #c9a449) 90%, white 10%);
    }
  }
</style>
