<script>
  /**
   * InlineHelpIcon — v1.3.0 skeleton (per ADR-015 P0.9 + Stage 4 educational).
   *
   * Маленькая (i)-иконка рядом с полем, по hover/click показывает tooltip:
   * - короткий текст (1-2 предложения).
   * - link «Подробнее в глоссарии» → откроет GlossaryPanel с relevant term.
   *
   * Stage 2: skeleton. Stage 4: финальный content через field-tooltips.json
   * и интеграция с GlossaryPanel.
   *
   * @component InlineHelpIcon
   */

  const {
    tooltip,        // short text (1-2 sentences)
    glossaryTerm,   // optional: term ID для глоссария (для Stage 4)
    position = 'top', // 'top' | 'bottom' | 'left' | 'right'
  } = $props();

  let isOpen = $state(false);
  let triggerEl;

  /** @param {Event | undefined} e */
  function toggle(e) {
    e?.stopPropagation();
    isOpen = !isOpen;
  }

  /** @param {KeyboardEvent} e */
  function closeOnEscape(e) {
    if (e.key === 'Escape') {
      isOpen = false;
    }
  }
</script>

<svelte:window onkeydown={closeOnEscape} />

<span class="help-trigger" bind:this={triggerEl}>
  <button
    type="button"
    class="icon-btn"
    onclick={toggle}
    onmouseenter={() => isOpen = true}
    onmouseleave={() => isOpen = false}
    aria-label="Подсказка"
    aria-expanded={isOpen}
  >
    ⓘ
  </button>
  {#if isOpen && tooltip}
    <span class="tooltip tooltip-{position}" role="tooltip">
      <span class="tooltip-text">{tooltip}</span>
      {#if glossaryTerm}
        <a href="#glossary-{glossaryTerm}" class="glossary-link">
          Подробнее в глоссарии →
        </a>
      {/if}
    </span>
  {/if}
</span>

<style>
  .help-trigger {
    position: relative;
    display: inline-flex;
    vertical-align: middle;
  }
  .icon-btn {
    background: none;
    border: none;
    cursor: help;
    padding: 0 2px;
    font-size: 13px;
    color: var(--text-muted);
    transition: color 0.15s;
  }
  .icon-btn:hover,
  .icon-btn:focus {
    color: var(--accent-primary);
    outline: none;
  }
  .tooltip {
    position: absolute;
    z-index: 100;
    min-width: 200px;
    max-width: 320px;
    padding: 8px 12px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    box-shadow: var(--shadow-elevation-2, 0 8px 24px rgba(0,0,0,0.15));
    font-size: 12px;
    line-height: 1.4;
    color: var(--text-primary);
  }
  .tooltip-top {
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
  }
  .tooltip-bottom {
    top: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
  }
  .tooltip-text {
    display: block;
    color: var(--text-primary);
  }
  .glossary-link {
    display: block;
    margin-top: 4px;
    font-size: 11px;
    color: var(--accent-primary);
    text-decoration: none;
  }
  .glossary-link:hover { text-decoration: underline; }
</style>
