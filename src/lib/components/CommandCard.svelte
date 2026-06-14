<script>
  import { getCommandMeta } from '$lib/command-meta.js';

  /**
   * @type {{
   *   command: string,
   *   label: string,
   *   group?: string,
   *   cabinetColor?: string,
   *   usageCount?: number,
   *   isFavorite?: boolean,
   *   highlighted?: boolean,
   *   animDelay?: number,
   *   onExecute?: (command: string) => void,
   *   onToggleFavorite?: (command: string) => void,
   * }}
   */
  let {
    command,
    label,
    group = '',
    cabinetColor = '#2E5BFF',
    usageCount = 0,
    isFavorite = false,
    highlighted = false,
    animDelay = 0,
    onExecute,
    onToggleFavorite,
  } = $props();

  const meta = $derived(getCommandMeta(command));
  const description = $derived(meta?.description || '');
  const example = $derived(meta?.example || '');
  const hasTooltip = $derived(!!(description || example));

  /** @param {MouseEvent} e */
  function handleContext(e) {
    e.preventDefault();
    if (onToggleFavorite) onToggleFavorite(command);
  }
</script>

<button
  class="cmd-card"
  class:highlighted
  class:favorite={isFavorite}
  class:hero={command === '/analytics'}
  style="--cab-color: {cabinetColor}; animation-delay: {animDelay}ms"
  onclick={() => onExecute?.(command)}
  oncontextmenu={handleContext}
  tabindex="0"
  role="gridcell"
  title={!hasTooltip ? label : undefined}
>
  {#if isFavorite}
    <span class="fav-star">★</span>
  {/if}

  <span class="cmd-label">{label}</span>

  {#if description}
    <span class="cmd-desc">{description}</span>
  {/if}

  {#if usageCount > 0}
    <span class="cmd-mastery">×{usageCount}</span>
  {/if}

  <!-- Hover tooltip (CSS-driven, 300ms delay) -->
  {#if hasTooltip}
    <div class="cmd-tooltip">
      <div class="tooltip-title">{label}</div>
      {#if description}
        <div class="tooltip-desc">{description}</div>
      {/if}
      {#if example}
        <div class="tooltip-example">
          <span class="tooltip-example-label">Пример:</span> {example}
        </div>
      {/if}
    </div>
  {/if}
</button>

<style>
  .cmd-card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 14px 16px;
    background: var(--bg-surface-quiet, rgba(20, 20, 30, 0.92));
    backdrop-filter: var(--blur-quiet, blur(8px));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
    border-radius: var(--radius-card);
    color: var(--text-primary, #EAEAF0);
    font-family: inherit;
    font-size: 13px;
    text-align: left;
    cursor: pointer;
    transition: var(--hover-timing);
    animation: card-appear 0.35s ease-out both;
    content-visibility: auto;
    contain-intrinsic-size: 120px 88px;
    min-height: 72px;
  }

  .cmd-card.hero {
    border-left: 3px solid var(--accent-primary);
    box-shadow: inset 3px 0 8px rgba(var(--accent-primary-rgb, 46, 91, 255), 0.12);
  }

  .cmd-card:hover {
    background: var(--bg-glass-hover, rgba(28,28,40,0.96));
    border-color: var(--cab-accent, var(--cab-color));
    transform: var(--hover-transform);
    box-shadow: var(--shadow-glow);
  }

  .cmd-card:active {
    transform: translateY(0) scale(0.97);
    transition-duration: 80ms;
  }

  .cmd-card:focus-visible {
    outline: 1.5px solid var(--accent-primary, #2E5BFF);
    outline-offset: 2px;
  }

  /* Smart highlighting when inbox has files */
  .cmd-card.highlighted {
    border-color: var(--cab-accent, var(--cab-color));
    box-shadow: 0 0 0 1px var(--cab-accent, var(--cab-color)), var(--shadow-glow);
  }

  /* ─── Content ─── */
  .cmd-label {
    font-weight: 600;
    font-size: 13.5px;
    line-height: 1.3;
  }

  .cmd-desc {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    line-height: 1.4;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .cmd-mastery {
    position: absolute;
    top: 8px;
    right: 10px;
    font-size: 10px;
    color: var(--text-muted, #7A7A90);
    background: var(--hover-bg);
    padding: 1px 6px;
    border-radius: 8px;
  }

  .fav-star {
    position: absolute;
    top: 8px;
    left: 10px;
    font-size: 10px;
    color: var(--accent-secondary, #CCFF00);
    opacity: 0.8;
  }

  /* ─── Tooltip ─── */
  .cmd-tooltip {
    position: absolute;
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
    background: var(--bg-tertiary, #1E1E2C);
    border: 1px solid var(--border, rgba(255,255,255,0.16));
    border-radius: 10px;
    padding: 10px 14px;
    max-width: 280px;
    min-width: 180px;
    z-index: 100;
    pointer-events: none;
    opacity: 0;
    transition: opacity 150ms ease-out;
    transition-delay: 0ms;
    box-shadow: var(--shadow-glow);
  }

  .cmd-card:hover .cmd-tooltip {
    opacity: 1;
    transition-delay: 300ms;
  }

  .tooltip-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, #EAEAF0);
    margin-bottom: 4px;
  }

  .tooltip-desc {
    font-size: 12px;
    color: var(--text-secondary, #A8A8B8);
    line-height: 1.45;
  }

  .tooltip-example {
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
    line-height: 1.4;
    font-style: italic;
  }

  .tooltip-example-label {
    font-style: normal;
    font-weight: 500;
    color: var(--text-secondary, #A8A8B8);
  }

</style>
