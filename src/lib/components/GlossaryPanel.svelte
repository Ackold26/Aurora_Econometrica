<script>
  /**
   * GlossaryPanel - v1.3.0 раскрывающаяся боковая панель со словарём.
   * Open through Ctrl+K shortcut или icon в header.
   *
   * @component GlossaryPanel
   */

  import { GLOSSARY, getAllTerms, searchTerms, getTerm } from '$lib/glossary.js';
  import { X } from 'lucide-svelte';

  const { onClose, initialTerm = null } = $props();

  import { onMount, tick } from 'svelte';

  let query = $state('');
  /** @type {string | null} */
  let selectedTermId = $state(initialTerm ?? null);

  /** @type {HTMLInputElement | null} */
  let searchInputEl = null;
  /** @type {HTMLElement | null} */
  let panelEl = null;
  /** @type {Element | null} */
  let previousFocus = null;

  // UX audit v1.3.0: focus trap + restore focus on close (WCAG accessibility).
  onMount(() => {
    previousFocus = typeof document !== 'undefined' ? document.activeElement : null;
    (async () => {
      await tick();
      searchInputEl?.focus();
    })();
    return () => {
      if (previousFocus instanceof HTMLElement) {
        previousFocus.focus();
      }
    };
  });

  /** @type {Array<{id: string, term: string, short: string, long: string, example: string, related: string[]}>} */
  const filteredTerms = $derived(/** @type {any} */ (searchTerms(query)));
  /** @type {{id: string, term: string, short: string, long: string, example: string, related: string[]} | null} */
  const selectedTerm = $derived(selectedTermId ? /** @type {any} */ (getTerm(selectedTermId)) : null);

  /** @param {string} id */
  function selectTerm(id) {
    selectedTermId = id;
  }

  /** @param {KeyboardEvent} e */
  function handleKeydown(e) {
    if (e.key === 'Escape') {
      onClose?.();
      return;
    }
    // UX audit v1.3.0: focus trap - Tab loop внутри панели.
    if (e.key === 'Tab' && panelEl) {
      const focusable = panelEl.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = /** @type {HTMLElement} */ (focusable[0]);
      const last = /** @type {HTMLElement} */ (focusable[focusable.length - 1]);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="glossary-overlay" onclick={onClose}>
  <div
    class="glossary-panel"
    bind:this={panelEl}
    onclick={(e) => e.stopPropagation()}
    role="dialog"
    aria-modal="true"
    aria-labelledby="glossary-title"
  >
    <header class="panel-header">
      <h2 id="glossary-title">Словарь терминов</h2>
      <button type="button" class="close-btn" onclick={onClose} aria-label="Закрыть глоссарий"><X size={16} strokeWidth={1.5} /></button>
    </header>

    <input
      bind:this={searchInputEl}
      type="text"
      placeholder="Поиск термина..."
      aria-label="Поиск термина в словаре"
      bind:value={query}
      class="search-input"
    />

    <div class="panel-body">
      <aside class="term-list">
        <ul>
          {#each filteredTerms as term (term.id)}
            <li>
              <button
                type="button"
                class:active={selectedTermId === term.id}
                onclick={() => selectTerm(term.id)}
              >
                {term.term}
              </button>
            </li>
          {/each}
        </ul>
        {#if filteredTerms.length === 0}
          <p class="empty">Ничего не найдено</p>
        {/if}
      </aside>

      <main class="term-detail">
        {#if selectedTerm}
          <h3>{selectedTerm.term}</h3>
          <p class="short">{selectedTerm.short}</p>
          <h4>Подробнее</h4>
          <p>{selectedTerm.long}</p>
          {#if selectedTerm.example}
            <h4>Пример</h4>
            <p class="example">{selectedTerm.example}</p>
          {/if}
          {#if selectedTerm.related && selectedTerm.related.length > 0}
            <h4>Связанные термины</h4>
            <div class="related">
              {#each selectedTerm.related as relId}
                {@const rel = /** @type {{term: string} | null} */ (getTerm(relId))}
                {#if rel}
                  <button type="button" class="related-link" onclick={() => selectTerm(relId)}>
                    {rel.term}
                  </button>
                {/if}
              {/each}
            </div>
          {/if}
        {:else}
          <p class="hint">← Выберите термин слева</p>
        {/if}
      </main>
    </div>
  </div>
</div>

<style>
  .glossary-overlay {
    position: fixed;
    inset: 0;
    z-index: 9998;
    background: color-mix(in srgb, var(--bg-card) 60%, transparent);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: stretch;
    justify-content: flex-end;
  }
  .glossary-panel {
    background: var(--bg-card);
    border-left: 1px solid var(--border);
    width: 760px;
    max-width: 100vw;
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: 16px 20px;
    gap: 12px;
    box-shadow: -10px 0 40px rgba(0,0,0,0.3);
  }

  .panel-header { display: flex; justify-content: space-between; align-items: center; }
  .panel-header h2 { margin: 0; font-size: 18px; font-weight: 700; }
  .close-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 16px;
    padding: 4px 8px;
    border-radius: 6px;
    font: inherit;
  }
  .close-btn:hover { background: var(--bg-surface-quiet); color: var(--text-primary); }

  .search-input {
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-surface-quiet);
    color: var(--text-primary);
    font-size: 13px;
    font: inherit;
  }

  .panel-body {
    display: grid;
    grid-template-columns: 220px 1fr;
    gap: 16px;
    flex: 1;
    min-height: 0;
  }

  .term-list {
    overflow-y: auto;
    border-right: 1px solid var(--border-subtle);
    padding-right: 12px;
  }
  .term-list ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .term-list button {
    background: none;
    border: none;
    text-align: left;
    width: 100%;
    padding: 6px 8px;
    border-radius: 4px;
    color: var(--text-secondary);
    font-size: 12px;
    cursor: pointer;
    font: inherit;
    line-height: 1.3;
  }
  .term-list button:hover {
    background: var(--bg-surface-quiet);
    color: var(--text-primary);
  }
  .term-list button.active {
    background: color-mix(in srgb, var(--accent-primary) 12%, transparent);
    color: var(--accent-primary);
    font-weight: 600;
  }
  .empty { font-size: 12px; color: var(--text-muted); padding: 8px; }

  .term-detail {
    overflow-y: auto;
    padding-right: 8px;
  }
  .term-detail h3 {
    margin: 0 0 6px;
    font-size: 18px;
    color: var(--text-primary);
    font-weight: 700;
  }
  .term-detail .short {
    font-size: 14px;
    color: var(--text-primary);
    font-weight: 500;
    margin: 0 0 16px;
    line-height: 1.5;
  }
  .term-detail h4 {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin: 16px 0 6px;
    font-weight: 700;
  }
  .term-detail p {
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.55;
    margin: 0;
  }
  .example {
    padding: 10px 14px;
    background: color-mix(in srgb, var(--accent-primary) 4%, transparent);
    border-left: 3px solid var(--accent-primary);
    border-radius: 4px;
    font-style: italic;
  }
  .related {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .related-link {
    padding: 4px 10px;
    background: var(--bg-surface-quiet);
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 11px;
    color: var(--accent-primary);
    cursor: pointer;
    font: inherit;
  }
  .related-link:hover { background: color-mix(in srgb, var(--accent-primary) 12%, transparent); }

  .hint {
    text-align: center;
    color: var(--text-muted);
    font-size: 13px;
    margin-top: 40px;
  }
</style>
