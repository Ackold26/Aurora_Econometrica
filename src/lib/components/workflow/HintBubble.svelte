<script>
  import { dismissHint, dismissedHints, hintsEnabled } from '$lib/hints.js';

  /**
   * @type {{
   *   hint: {id: string, text: string, detail?: string},
   *   position?: 'top'|'bottom'|'inline',
   *   show?: boolean
   * }}
   */
  let { hint, position = 'inline', show = true } = $props();

  let expanded = $state(false);
  let visible = $derived(show && $hintsEnabled && !$dismissedHints.has(hint.id));

  function dismiss() {
    dismissHint(hint.id);
  }
</script>

{#if visible}
  <div class="hint" class:hint--top={position === 'top'} class:hint--bottom={position === 'bottom'}>
    <div class="hint-icon">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>
      </svg>
    </div>
    <div class="hint-content">
      <span class="hint-text">{hint.text}</span>
      {#if hint.detail}
        {#if expanded}
          <span class="hint-detail">{hint.detail}</span>
        {:else}
          <button class="hint-more" onclick={() => expanded = true}>Подробнее</button>
        {/if}
      {/if}
    </div>
    <button class="hint-dismiss" onclick={dismiss} title="Скрыть подсказку">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
    </button>
  </div>
{/if}

<style>
  .hint {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 10px 12px;
    background: rgba(46, 91, 255, 0.06);
    border: 1px solid rgba(46, 91, 255, 0.12);
    border-radius: 10px;
    animation: hint-enter 0.3s ease-out;
    margin: 8px 0;
  }

  .hint--top {
    margin-top: 0;
  }

  .hint--bottom {
    margin-bottom: 0;
  }

  @keyframes hint-enter {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .hint-icon {
    color: var(--accent-primary);
    flex-shrink: 0;
    margin-top: 1px;
  }

  .hint-content {
    flex: 1;
    min-width: 0;
  }

  .hint-text {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-primary);
    line-height: 1.4;
  }

  .hint-detail {
    display: block;
    font-size: 11px;
    color: var(--text-secondary);
    line-height: 1.5;
    margin-top: 4px;
  }

  .hint-more {
    display: inline;
    font-size: 11px;
    color: var(--accent-primary);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    margin-left: 4px;
  }

  .hint-more:hover {
    text-decoration: underline;
  }

  .hint-dismiss {
    flex-shrink: 0;
    padding: 2px;
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: 4px;
    opacity: 0.5;
    transition: all 0.15s;
  }

  .hint-dismiss:hover {
    opacity: 1;
    color: var(--text-secondary);
    background: rgba(255, 255, 255, 0.05);
  }
</style>
