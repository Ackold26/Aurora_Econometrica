<script>
  /**
   * LoadingSkeleton — Phase 2.15 / Audit P-premium-feel.
   *
   * Shimmer placeholder для loading states (e.g. async fetch classifier
   * patterns, initial validation). Shows blocks at approximate content
   * proportions to reduce perceived wait time.
   *
   * Variants:
   * - 'card' (default) — single rounded block
   * - 'list' — N rows of skeleton items (use rows prop)
   * - 'channel-row' — mimics AppliedModeSummary channel-item visual
   *
   * Respects prefers-reduced-motion: no shimmer if user prefers reduced.
   */

  /**
   * @type {{
   *   variant?: 'card' | 'list' | 'channel-row',
   *   rows?: number,
   *   height?: number,
   *   width?: string,
   *   label?: string,
   * }}
   */
  const {
    variant = 'card',
    rows = 3,
    height = 48,
    width = '100%',
    label = 'Загрузка...',
  } = $props();
</script>

<div
  class="skeleton skeleton--{variant}"
  role="status"
  aria-label={label}
  aria-live="polite"
  data-testid="loading-skeleton"
>
  {#if variant === 'card'}
    <div class="skeleton-block" style:height="{height}px" style:width></div>
  {:else if variant === 'list'}
    {#each Array.from({ length: rows }) as _, i (i)}
      <div class="skeleton-block" style:height="{height}px"></div>
    {/each}
  {:else if variant === 'channel-row'}
    {#each Array.from({ length: rows }) as _, i (i)}
      <div class="skeleton-channel-row">
        <div class="skeleton-block skeleton-channel-name"></div>
        <div class="skeleton-block skeleton-channel-arrow"></div>
        <div class="skeleton-block skeleton-channel-value"></div>
      </div>
    {/each}
  {/if}
  <span class="sr-only">{label}</span>
</div>

<style>
  .skeleton {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
  }
  .skeleton-block {
    background: linear-gradient(
      90deg,
      color-mix(in srgb, var(--text-primary) 6%, transparent) 0%,
      color-mix(in srgb, var(--text-primary) 12%, transparent) 50%,
      color-mix(in srgb, var(--text-primary) 6%, transparent) 100%
    );
    background-size: 200% 100%;
    border-radius: 6px;
    min-height: 16px;
  }
  @media (prefers-reduced-motion: no-preference) {
    .skeleton-block {
      animation: shimmer 1.6s ease-in-out infinite;
    }
    @keyframes shimmer {
      0% { background-position: 200% 0; }
      100% { background-position: -200% 0; }
    }
  }
  .skeleton-channel-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 14px;
    border-bottom: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
  }
  .skeleton-channel-name { width: 140px; height: 14px; }
  .skeleton-channel-arrow { width: 12px; height: 12px; }
  .skeleton-channel-value { width: 90px; height: 14px; }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>
