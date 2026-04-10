<script>
  import { getCategorizedCabinets } from '$lib/command-meta.js';

  /**
   * @type {{
   *   cabinets?: Array<{id: string, name: string, description: string, icon: string, color: string}>,
   *   activeCabinetId?: string|null,
   *   onSelect?: (cabinet: any) => Promise<void>,
   *   collapsed?: boolean,
   *   onToggleCollapse?: () => void,
   * }}
   */
  let { cabinets = [], activeCabinetId = null, onSelect, collapsed = false, onToggleCollapse } = $props();

  /** @type {string|null} */
  let loadingId = $state(null);

  const navMode = $derived(
    cabinets.length <= 1 ? 'hidden' : cabinets.length <= 5 ? 'tabs' : 'sidebar'
  );

  const categorized = $derived(getCategorizedCabinets(cabinets));

  /** @param {any} cabinet */
  async function handleSelect(cabinet) {
    if (loadingId || cabinet.id === activeCabinetId) return;
    loadingId = cabinet.id;
    try {
      if (onSelect) await onSelect(cabinet);
    } finally {
      loadingId = null;
    }
  }
</script>

<nav class="nav-rail" data-mode={navMode} class:collapsed>
  {#if navMode === 'tabs'}
    <!-- Horizontal tab bar for 2-5 cabinets -->
    {#each cabinets as cab (cab.id)}
      <button
        class="nav-item"
        class:active={cab.id === activeCabinetId}
        class:loading={cab.id === loadingId}
        disabled={!!loadingId}
        style="--cab-color: {cab.color}"
        onclick={() => handleSelect(cab)}
        title={cab.description}
      >
        <span class="nav-icon">{cab.icon}</span>
        <span class="nav-label">{cab.name}</span>
        {#if cab.id === loadingId}
          <span class="nav-spinner"></span>
        {/if}
      </button>
    {/each}

  {:else if navMode === 'sidebar'}
    <!-- Vertical sidebar for 6+ cabinets -->
    <div class="nav-scroll">
      {#each categorized as group (group.name)}
        {#if !collapsed}
          <div class="nav-category">{group.name}</div>
        {/if}
        {#each group.items as cab (cab.id)}
          <button
            class="nav-item"
            class:active={cab.id === activeCabinetId}
            class:loading={cab.id === loadingId}
            disabled={!!loadingId}
            style="--cab-color: {cab.color}"
            onclick={() => handleSelect(cab)}
            title={collapsed ? cab.name : cab.description}
          >
            <span class="nav-icon">{cab.icon}</span>
            {#if !collapsed}
              <span class="nav-label">{cab.name}</span>
            {/if}
            {#if cab.id === loadingId}
              <span class="nav-spinner"></span>
            {/if}
          </button>
        {/each}
      {/each}
    </div>

    <!-- Collapse toggle -->
    <button class="nav-collapse-btn" onclick={onToggleCollapse} title={collapsed ? 'Развернуть' : 'Свернуть'}>
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d={collapsed ? 'M6 3l5 5-5 5' : 'M10 3l-5 5 5 5'} stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
  {/if}
</nav>

<style>
  /* ─── Base ─── */
  .nav-rail {
    display: flex;
    flex-shrink: 0;
    background: var(--bg-secondary);
    transition: width 200ms ease-out;
    z-index: 10;
  }

  .nav-rail[data-mode="hidden"] {
    display: none;
  }

  /* ─── Tab mode (horizontal, 2-5 cabs) ─── */
  .nav-rail[data-mode="tabs"] {
    flex-direction: row;
    height: 44px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
    padding: 0 12px;
    gap: 2px;
    align-items: stretch;
    overflow-x: auto;
  }

  .nav-rail[data-mode="tabs"] .nav-item {
    flex-direction: row;
    gap: 8px;
    padding: 0 14px;
    border-radius: 0;
    border-bottom: 2px solid transparent;
    height: 100%;
  }

  .nav-rail[data-mode="tabs"] .nav-item.active {
    border-bottom-color: var(--cab-color);
    background: rgba(255, 255, 255, 0.04);
  }

  .nav-rail[data-mode="tabs"] .nav-item:hover:not(.active):not(:disabled) {
    background: rgba(255, 255, 255, 0.04);
  }

  /* ─── Sidebar mode (vertical, 6+ cabs) ─── */
  .nav-rail[data-mode="sidebar"] {
    flex-direction: column;
    width: 220px;
    border-right: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
    padding: 8px 0;
  }

  .nav-rail[data-mode="sidebar"].collapsed {
    width: 48px;
  }

  .nav-scroll {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 0 6px;
  }

  /* ─── Category labels ─── */
  .nav-category {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted, #7A7A90);
    padding: 16px 10px 4px;
    user-select: none;
  }

  .nav-category:first-child {
    padding-top: 4px;
  }

  /* ─── Nav items ─── */
  .nav-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 10px;
    border-radius: 8px;
    border: none;
    background: transparent;
    color: var(--text-secondary, #A8A8B8);
    font-size: 13px;
    font-family: inherit;
    cursor: pointer;
    transition: all 150ms ease-out;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: left;
    width: 100%;
    position: relative;
  }

  .nav-item:hover:not(.active):not(:disabled) {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-primary, #EAEAF0);
  }

  .nav-item.active {
    background: rgba(46, 91, 255, 0.10);
    color: var(--text-primary, #EAEAF0);
  }

  .nav-rail[data-mode="sidebar"] .nav-item.active {
    border-left: 3px solid var(--cab-color);
    padding-left: 7px;
  }

  .nav-item:disabled {
    opacity: 0.5;
    cursor: default;
  }

  /* ─── Icon ─── */
  .nav-icon {
    flex-shrink: 0;
    font-size: 15px;
    width: 20px;
    text-align: center;
  }

  /* ─── Label ─── */
  .nav-label {
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    min-width: 0;
  }

  /* ─── Collapsed sidebar: center icon ─── */
  .nav-rail.collapsed .nav-item {
    justify-content: center;
    padding: 8px;
  }

  .nav-rail.collapsed .nav-icon {
    font-size: 17px;
  }

  /* ─── Loading spinner ─── */
  .nav-spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255, 255, 255, 0.15);
    border-top-color: var(--cab-color);
    border-radius: 50%;
    animation: nav-spin 600ms linear infinite;
    flex-shrink: 0;
  }

  @keyframes nav-spin {
    to { transform: rotate(360deg); }
  }

  /* ─── Collapse toggle button ─── */
  .nav-collapse-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 32px;
    margin: 4px 6px 6px;
    border: none;
    background: transparent;
    color: var(--text-muted, #7A7A90);
    border-radius: 6px;
    cursor: pointer;
    transition: all 150ms ease-out;
  }

  .nav-collapse-btn:hover {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-secondary, #A8A8B8);
  }

  /* ─── Scrollbar ─── */
  .nav-scroll::-webkit-scrollbar {
    width: 3px;
  }
  .nav-scroll::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 2px;
  }
  .nav-scroll::-webkit-scrollbar-thumb:hover {
    background: rgba(255, 255, 255, 0.2);
  }

  /* ─── Light theme ─── */
  :global([data-theme="light"]) .nav-rail {
    background: var(--bg-secondary, #EEEEF0);
  }
  :global([data-theme="light"]) .nav-item:hover:not(.active):not(:disabled) {
    background: rgba(0, 0, 0, 0.04);
  }
  :global([data-theme="light"]) .nav-item.active {
    background: rgba(46, 91, 255, 0.08);
  }
</style>
