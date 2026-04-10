<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { activeCabinet, messages, pendingCommand } from '$lib/store.js';
  import { isCreativeHub } from '$lib/creative-store.js';

  /** @type {{open: boolean, onClose: () => void}} */
  let { open, onClose } = $props();

  let query = $state('');
  let selectedIndex = $state(0);
  /** @type {HTMLInputElement|undefined} */
  let inputEl = $state(undefined);

  /** @type {Array<{id: string, label: string, description: string, type: 'nav'|'command'|'cabinet', cabinetId?: string, action: () => void}>} */
  let allItems = $state([]);

  const baseNavItems = [
    { id: 'nav-home', label: 'Главная', description: 'Вернуться на главную', type: /** @type {const} */ ('nav'), action: () => { goto('/'); onClose(); } },
    { id: 'nav-workflow', label: 'Workflows', description: 'Визуальный конструктор workflow', type: /** @type {const} */ ('nav'), action: () => { goto('/workflow'); onClose(); } },
    { id: 'nav-campaign', label: 'Кампании', description: 'Пошаговый режим кампании', type: /** @type {const} */ ('nav'), action: () => { goto('/campaign'); onClose(); } },
    { id: 'nav-data-chat', label: 'Data Chat', description: 'Вопросы и аналитика', type: /** @type {const} */ ('nav'), action: () => { goto('/data-chat'); onClose(); } },
    { id: 'nav-settings', label: 'Настройки', description: 'Параметры приложения', type: /** @type {const} */ ('nav'), action: () => { goto('/settings'); onClose(); } },
  ];
  let navItems = $derived([
    ...baseNavItems,
    ...($isCreativeHub ? [{ id: 'nav-brands', label: 'Бренды', description: 'Управление брендами', type: /** @type {const} */ ('nav'), action: () => { goto('/brands'); onClose(); } }] : []),
  ]);

  async function loadAllCommands() {
    try {
      const cabinets = await invoke('get_cabinets');
      /** @type {typeof allItems} */
      const items = [...navItems];

      for (const cab of cabinets) {
        // Cabinet entry
        items.push({
          id: `cab-${cab.id}`,
          label: cab.name,
          description: cab.description,
          type: 'cabinet',
          cabinetId: cab.id,
          action: async () => {
            try {
              await invoke('open_cabinet', { cabinetId: cab.id });
              activeCabinet.set(cab);
              messages.set([]);
              goto('/cabinet');
              onClose();
            } catch (err) { console.error(err); }
          },
        });

        // Commands for this cabinet
        const cmds = await invoke('get_cabinet_commands', { cabinetId: cab.id });
        for (const cmd of cmds) {
          items.push({
            id: `cmd-${cab.id}-${cmd.command}`,
            label: `${cmd.command}`,
            description: `${cmd.label} — ${cab.name}`,
            type: 'command',
            cabinetId: cab.id,
            action: async () => {
              try {
                await invoke('open_cabinet', { cabinetId: cab.id });
                activeCabinet.set(cab);
                messages.set([]);
                pendingCommand.set(cmd.command);
                goto('/cabinet');
                onClose();
              } catch (err) { console.error(err); }
            },
          });
        }
      }

      allItems = items;
    } catch {
      allItems = [...navItems];
    }
  }

  let filtered = $derived(
    query.trim()
      ? allItems.filter(item => {
          const q = query.toLowerCase();
          return item.label.toLowerCase().includes(q) ||
                 item.description.toLowerCase().includes(q);
        }).slice(0, 15)
      : allItems.slice(0, 15)
  );

  $effect(() => {
    if (open) {
      query = '';
      selectedIndex = 0;
      loadAllCommands();
      setTimeout(() => inputEl?.focus(), 50);
    }
  });

  $effect(() => {
    // Reset selection when filter changes
    if (filtered) selectedIndex = 0;
  });

  /** @param {KeyboardEvent} e */
  function handleKeydown(e) {
    if (e.key === 'Escape') {
      onClose();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, filtered.length - 1);
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, 0);
    }
    if (e.key === 'Enter' && filtered[selectedIndex]) {
      filtered[selectedIndex].action();
    }
  }

  const typeIcon = {
    nav: '→',
    cabinet: '◆',
    command: '/',
  };

  const typeLabel = {
    nav: 'Навигация',
    cabinet: 'Кабинет',
    command: 'Команда',
  };
</script>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="palette-overlay" onclick={onClose}>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="palette" onclick={(e) => e.stopPropagation()} onkeydown={handleKeydown}>
      <div class="palette-search">
        <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input
          bind:this={inputEl}
          class="palette-input"
          type="text"
          placeholder="Поиск команд, кабинетов..."
          bind:value={query}
        />
        <kbd class="palette-kbd">ESC</kbd>
      </div>

      <div class="palette-results">
        {#if filtered.length === 0}
          <div class="palette-empty">Ничего не найдено</div>
        {:else}
          {#each filtered as item, i}
            <button
              class="palette-item"
              class:palette-item-selected={i === selectedIndex}
              onclick={item.action}
              onmouseenter={() => selectedIndex = i}
            >
              <span class="item-icon">{typeIcon[item.type]}</span>
              <div class="item-content">
                <span class="item-label">{item.label}</span>
                <span class="item-desc">{item.description}</span>
              </div>
              <span class="item-type">{typeLabel[item.type]}</span>
            </button>
          {/each}
        {/if}
      </div>

      <div class="palette-footer">
        <span><kbd>↑↓</kbd> навигация</span>
        <span><kbd>↵</kbd> выбрать</span>
        <span><kbd>esc</kbd> закрыть</span>
      </div>
    </div>
  </div>
{/if}

<style>
  .palette-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 15vh;
    z-index: 9998;
    animation: overlay-in 0.15s ease;
  }

  @keyframes overlay-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  .palette {
    width: 100%;
    max-width: 520px;
    background: var(--bg-secondary);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 14px;
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6);
    overflow: hidden;
    animation: palette-in 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  }

  @keyframes palette-in {
    from { opacity: 0; transform: translateY(-8px) scale(0.98); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .palette-search {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .search-icon {
    color: var(--text-muted);
    flex-shrink: 0;
  }

  .palette-input {
    flex: 1;
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 15px;
    outline: none;
    font-family: var(--font-sans);
  }

  .palette-input::placeholder {
    color: var(--text-muted);
  }

  .palette-kbd {
    font-size: 10px;
    font-family: var(--font-mono);
    color: var(--text-muted);
    background: rgba(255, 255, 255, 0.05);
    padding: 2px 6px;
    border-radius: 4px;
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .palette-results {
    max-height: 340px;
    overflow-y: auto;
    padding: 6px;
  }

  .palette-empty {
    padding: 24px;
    text-align: center;
    color: var(--text-muted);
    font-size: 13px;
  }

  .palette-item {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 8px 10px;
    background: transparent;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    text-align: left;
    color: var(--text-secondary);
    transition: background 0.1s ease;
  }

  .palette-item-selected {
    background: rgba(46, 91, 255, 0.1);
    color: var(--text-primary);
  }

  .item-icon {
    width: 20px;
    text-align: center;
    font-size: 12px;
    color: var(--text-muted);
    flex-shrink: 0;
  }

  .palette-item-selected .item-icon {
    color: var(--accent-primary);
  }

  .item-content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .item-label {
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .item-desc {
    font-size: 11px;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .item-type {
    font-size: 9.5px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    flex-shrink: 0;
    opacity: 0.6;
  }

  .palette-footer {
    display: flex;
    gap: 16px;
    padding: 8px 16px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    font-size: 10px;
    color: var(--text-muted);
  }

  .palette-footer kbd {
    font-family: var(--font-mono);
    font-size: 9px;
    background: rgba(255, 255, 255, 0.05);
    padding: 1px 5px;
    border-radius: 3px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    margin-right: 3px;
  }
</style>
