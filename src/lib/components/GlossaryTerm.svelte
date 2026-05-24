<script>
  /**
   * GlossaryTerm — wraps a term с first-appearance dotted underline + hover/click popup.
   *
   * Phase 3 Day 2 Task 4 of help-system audit (v2.1.0-rc6).
   *
   * Behavior:
   * - On mount: проверяет sessionStorage key `aurora.glossary.shown.<termId>`. Если absent —
   *   set it и render dotted underline. Если present — render plain text (skip underline).
   * - Hover / click on underlined term показывает popup с term.short + кнопку «Полное определение».
   * - Кнопка триггерит full GlossaryPanel через `showGlossaryPanel` + pre-selects term через
   *   `glossaryInitialTerm` store.
   *
   * Usage:
   *   <GlossaryTerm termId="adstock">adstock</GlossaryTerm>
   *   <GlossaryTerm termId="hill_saturation">Hill saturation</GlossaryTerm>
   *
   * @component GlossaryTerm
   */
  import { onMount } from 'svelte';
  import { getTerm } from '$lib/glossary.js';
  import { showGlossaryPanel, glossaryInitialTerm } from '$lib/project-state.js';

  /** @type {{ termId: string, children?: any }} */
  const { termId, children } = $props();

  /** @type {{ id: string, term: string, short: string, long: string, example: string, related: string[] } | null} */
  const term = $derived(/** @type {any} */ (getTerm(termId)));

  let showUnderline = $state(false);
  let popupOpen = $state(false);

  onMount(() => {
    if (!term) return;
    if (typeof sessionStorage === 'undefined') return;
    const key = `aurora.glossary.shown.${termId}`;
    if (!sessionStorage.getItem(key)) {
      showUnderline = true;
      sessionStorage.setItem(key, '1');
    }
  });

  function handleClick(/** @type {MouseEvent | KeyboardEvent} */ event) {
    event.stopPropagation();
    popupOpen = !popupOpen;
  }

  function handleKeydown(/** @type {KeyboardEvent} */ event) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleClick(event);
    } else if (event.key === 'Escape' && popupOpen) {
      popupOpen = false;
    }
  }

  function handleMouseEnter() { popupOpen = true; }
  function handleMouseLeave() { popupOpen = false; }

  function openFullGlossary() {
    popupOpen = false;
    glossaryInitialTerm.set(termId);
    showGlossaryPanel.set(true);
  }
</script>

{#if term && showUnderline}
  <span
    class="glossary-term"
    onclick={handleClick}
    onkeydown={handleKeydown}
    onmouseenter={handleMouseEnter}
    onmouseleave={handleMouseLeave}
    role="button"
    tabindex="0"
    aria-label={`Глоссарий: ${term.term}`}
    aria-haspopup="dialog"
    aria-expanded={popupOpen}
  >{@render children?.()}{#if popupOpen}<span class="glossary-popup" role="tooltip">
        <span class="popup-title">{term.term}</span>
        <span class="popup-short">{term.short}</span>
        <button type="button" class="popup-full-link" onclick={openFullGlossary}>
          Полное определение →
        </button>
      </span>{/if}</span>
{:else}
  {@render children?.()}
{/if}

<style>
  .glossary-term {
    position: relative;
    border-bottom: 1px dotted color-mix(in srgb, var(--accent-primary, #6366f1) 60%, transparent);
    cursor: help;
    color: inherit;
    transition: border-color 0.15s;
    display: inline;
  }
  .glossary-term:hover,
  .glossary-term:focus-visible {
    border-bottom-color: var(--accent-primary, #6366f1);
    outline: none;
  }
  .glossary-popup {
    position: absolute;
    bottom: calc(100% + 6px);
    left: 0;
    z-index: 100;
    min-width: 240px;
    max-width: 320px;
    padding: 10px 12px;
    background: var(--bg-surface-focus, rgba(20, 22, 30, 0.96));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    display: flex;
    flex-direction: column;
    gap: 6px;
    backdrop-filter: blur(12px);
    text-align: left;
    pointer-events: auto;
    cursor: default;
  }
  .popup-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    line-height: 1.3;
  }
  .popup-short {
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.45;
  }
  .popup-full-link {
    margin-top: 4px;
    align-self: flex-start;
    background: none;
    border: none;
    padding: 0;
    color: var(--accent-primary, #6366f1);
    font-size: 11px;
    font-weight: 500;
    cursor: pointer;
    font-family: inherit;
    line-height: 1.3;
  }
  .popup-full-link:hover {
    text-decoration: underline;
  }
</style>
