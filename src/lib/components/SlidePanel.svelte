<script>
  import { cleanSlideTitle } from '$lib/response-parser.js';
  import { pendingCommand } from '$lib/store.js';
  import ResponseSection from './ResponseSection.svelte';

  /**
   * @type {{
   *   sections: import('$lib/response-parser.js').ResponseSection[],
   *   onClose: () => void,
   * }}
   */
  let { sections, onClose } = $props();

  let selectedIndex = $state(0);
  let copied = $state(false);
  let panelWidth = $state(300);

  /** @param {MouseEvent} e */
  function startResize(e) {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = panelWidth;
    /** @param {MouseEvent} e */
    function onMouseMove(e) {
      panelWidth = Math.min(500, Math.max(200, startWidth + (e.clientX - startX)));
    }
    function onMouseUp() {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }

  /** @type {{ num: number, name: string }[]} */
  let cleanTitles = $derived(sections.map(s => cleanSlideTitle(s.title)));

  let safeIndex = $derived(Math.min(selectedIndex, sections.length - 1));
  let selectedSection = $derived(sections[safeIndex] || sections[0]);

  /** @param {KeyboardEvent} e */
  function handleListKeydown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, sections.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, 0);
    } else if (e.key === 'Escape') {
      e.stopPropagation();
      onClose();
    }
  }

  function copyAll() {
    const text = sections.map(s => `## ${s.title}\n\n${s.content}`).join('\n\n---\n\n');
    navigator.clipboard.writeText(text);
    copied = true;
    setTimeout(() => { copied = false; }, 2000);
  }

  /** @param {string} title */
  function handleRefine(title) {
    pendingCommand.set(`Доработай раздел "${title}": `);
  }
</script>

<div class="slide-panel" role="complementary" aria-label="Содержание презентации" style="width: {panelWidth}px">
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="sp-resize-handle" onmousedown={startResize}></div>
  <!-- Header -->
  <div class="sp-header">
    <div class="sp-header-text">
      <span class="sp-title">Содержание</span>
      <span class="sp-subtitle">{sections.length} слайдов</span>
    </div>
    <div class="sp-actions">
      <button class="sp-btn" onclick={copyAll} title={copied ? 'Скопировано!' : 'Копировать всё'}>
        {copied ? '✓' : '⧉'}
      </button>
      <button class="sp-btn sp-close" onclick={onClose} title="Закрыть (Esc)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
      </button>
    </div>
  </div>

  <!-- Slide list -->
  <div class="sp-section-label">Слайды</div>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div class="sp-list" tabindex="0" onkeydown={handleListKeydown} role="listbox" aria-label="Список слайдов">
    {#each cleanTitles as t, i}
      <button
        class="sp-item"
        class:active={i === safeIndex}
        onclick={() => selectedIndex = i}
        role="option"
        aria-selected={i === safeIndex}
      >
        <span class="sp-num">{t.num || i + 1}</span>
        <span class="sp-name">{t.name}</span>
      </button>
    {/each}
  </div>

  <!-- Divider + Detail label -->
  <div class="sp-divider"></div>
  <div class="sp-section-label">Комментарий</div>

  <!-- Detail -->
  <div class="sp-detail">
    {#if selectedSection}
      <ResponseSection
        title={selectedSection.title}
        content={selectedSection.content}
        level={selectedSection.level}
        onRefine={handleRefine}
      />
    {/if}
  </div>
</div>

<style>
  .slide-panel {
    display: flex;
    flex-direction: column;
    min-width: 200px;
    max-width: 500px;
    height: 100%;
    border-right: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
    background: var(--bg-surface-quiet, rgba(18, 18, 24, 0.92));
    backdrop-filter: var(--blur-quiet, blur(8px));
    -webkit-backdrop-filter: var(--blur-quiet, blur(8px));
    flex-shrink: 0;
    overflow: hidden;
    position: relative;
  }

  .sp-resize-handle {
    position: absolute;
    top: 0;
    right: -3px;
    width: 6px;
    height: 100%;
    cursor: col-resize;
    z-index: 10;
  }

  .sp-resize-handle:hover {
    background: var(--accent-primary, #2E5BFF);
    opacity: 0.4;
  }

  /* ── Header ── */
  .sp-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
    flex-shrink: 0;
  }

  .sp-header-text {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .sp-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, #EAEAF0);
  }

  .sp-subtitle {
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
  }

  .sp-section-label {
    padding: 6px 14px 4px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted, #7A7A90);
    flex-shrink: 0;
  }

  .sp-actions {
    display: flex;
    gap: 4px;
  }

  .sp-btn {
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    color: var(--text-muted, #7A7A90);
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    transition: all 150ms;
  }

  .sp-btn:hover {
    background: var(--hover-bg, rgba(255,255,255,0.10));
    color: var(--text-primary, #EAEAF0);
  }

  /* ── List ── */
  .sp-list {
    max-height: 40%;
    overflow-y: auto;
    flex-shrink: 0;
    outline: none;
  }

  .sp-item {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 6px 14px;
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
    color: var(--text-primary, #EAEAF0);
    font-size: 12.5px;
    font-family: inherit;
    cursor: pointer;
    text-align: left;
    transition: all 120ms;
  }

  .sp-item:hover {
    background: rgba(255,255,255,0.04);
  }

  .sp-item.active {
    border-left-color: var(--accent-primary, #2E5BFF);
    background: rgba(46, 91, 255, 0.08);
  }

  .sp-num {
    width: 24px;
    text-align: right;
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
  }

  .sp-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ── Divider ── */
  .sp-divider {
    height: 1px;
    background: var(--border-subtle, rgba(255,255,255,0.10));
    flex-shrink: 0;
  }

  /* ── Detail ── */
  .sp-detail {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
  }

  /* ── Scrollbar ── */
  .sp-list::-webkit-scrollbar,
  .sp-detail::-webkit-scrollbar {
    width: 4px;
  }

  .sp-list::-webkit-scrollbar-thumb,
  .sp-detail::-webkit-scrollbar-thumb {
    background: rgba(255,255,255,0.12);
    border-radius: 2px;
  }

  /* ── Light theme ── */
  :global([data-theme="light"]) .slide-panel {
    background: rgba(255, 255, 255, 0.95);
  }

  :global([data-theme="light"]) .sp-item:hover {
    background: rgba(0,0,0,0.04);
  }

  :global([data-theme="light"]) .sp-item.active {
    background: rgba(46, 91, 255, 0.06);
  }

  /* ── Mobile overlay ── */
  @media (max-width: 768px) {
    .slide-panel {
      position: absolute;
      right: 0;
      top: 0;
      bottom: 0;
      width: 85%;
      max-width: 360px;
      z-index: 50;
      box-shadow: -4px 0 24px rgba(0,0,0,0.3);
    }
  }
</style>
