<script>
  import { invoke } from '@tauri-apps/api/core';
  import { activeCabinet, isLoading, pendingCommand, panelWidth, favoriteCommands } from '$lib/store.js';
  import { get } from 'svelte/store';

  /** @type {Array<{group: string, label: string, command: string}>} */
  let commands = $state([]);
  /** @type {Record<string, boolean>} */
  let collapsedGroups = $state({});
  const specialGroups = ['Спец. режимы'];
  let searchTerm = $state('');

  $effect(() => {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) {
      commands = [];
      return;
    }
    invoke('get_cabinet_commands', { cabinetId }).then((/** @type {Array<{group: string, label: string, command: string}>} */ cmds) => {
      commands = cmds;
      /** @type {Record<string, boolean>} */
      const groups = {};
      for (const g of specialGroups) {
        groups[g] = true;
      }
      collapsedGroups = groups;
    }).catch(() => {
      commands = [];
    });
  });

  /** @param {string} cmd */
  function isFavorite(cmd) {
    return $favoriteCommands.includes(cmd);
  }

  /** @param {string} cmd */
  function toggleFavorite(cmd) {
    const current = get(favoriteCommands);
    if (current.includes(cmd)) {
      favoriteCommands.set(current.filter(c => c !== cmd));
    } else {
      favoriteCommands.set([...current, cmd]);
    }
  }

  let filtered = $derived(
    searchTerm.trim()
      ? commands.filter(c =>
          c.label.toLowerCase().includes(searchTerm.trim().toLowerCase()) ||
          c.command.toLowerCase().includes(searchTerm.trim().toLowerCase())
        )
      : commands
  );

  /** Get favorite commands from the current command list */
  let favorites = $derived(
    commands.filter(c => $favoriteCommands.includes(c.command))
  );

  function getGroups() {
    /** @type {string[]} */
    const seen = [];
    /** @type {Record<string, Array<{group: string, label: string, command: string}>>} */
    const map = {};
    for (const cmd of filtered) {
      if (!map[cmd.group]) {
        map[cmd.group] = [];
        seen.push(cmd.group);
      }
      map[cmd.group].push(cmd);
    }
    return seen.map(g => ({ name: g, commands: map[g] }));
  }

  /** @param {string} name */
  function toggleGroup(name) {
    collapsedGroups = { ...collapsedGroups, [name]: !collapsedGroups[name] };
  }

  /** @param {string} command */
  function executeCommand(command) {
    if ($isLoading) return;
    pendingCommand.set(command);
  }
</script>

{#if commands.length > 0}
  <div class="command-panel" style="--cabinet-color: {$activeCabinet?.color || '#6366f1'}">
    <h3 class="command-title">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
      </svg>
      Команды
    </h3>

    <!-- Search -->
    <div class="search-wrap">
      <svg class="search-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      <input
        class="search-input"
        type="text"
        placeholder="Найти команду..."
        bind:value={searchTerm}
      />
      {#if searchTerm}
        <button class="search-clear" onclick={() => { searchTerm = ''; }}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      {/if}
    </div>

    <!-- Favorites group (only when not searching) -->
    {#if !searchTerm && favorites.length > 0}
      <div class="command-group">
        <div class="group-header">
          <span class="group-name fav-label">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" stroke="none">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
            </svg>
            Избранное
          </span>
        </div>
        <div class="command-grid" class:wide={$panelWidth > 350}>
          {#each favorites as cmd}
            <button
              class="command-btn fav-btn"
              onclick={() => executeCommand(cmd.command)}
              disabled={$isLoading}
              title={cmd.command}
            >
              {cmd.label}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Command groups (or flat search results) -->
    {#if searchTerm}
      {#if filtered.length === 0}
        <p class="no-results">Ничего не найдено</p>
      {:else}
        <div class="command-grid" class:wide={$panelWidth > 350}>
          {#each filtered as cmd}
            <div class="cmd-with-fav">
              <button
                class="command-btn"
                onclick={() => executeCommand(cmd.command)}
                disabled={$isLoading}
                title={cmd.command}
              >
                {cmd.label}
              </button>
              <button class="fav-star" class:starred={isFavorite(cmd.command)} onclick={() => toggleFavorite(cmd.command)} title={isFavorite(cmd.command) ? 'Убрать из избранного' : 'В избранное'}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill={isFavorite(cmd.command) ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="2">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
              </button>
            </div>
          {/each}
        </div>
      {/if}
    {:else}
      {#each getGroups() as group}
        <div class="command-group">
          {#if specialGroups.includes(group.name)}
            <button class="group-header collapsible" onclick={() => toggleGroup(group.name)}>
              <span class="group-name">{group.name}</span>
              <span class="group-chevron" class:collapsed={collapsedGroups[group.name]}>▾</span>
            </button>
          {:else}
            <div class="group-header">
              <span class="group-name">{group.name}</span>
            </div>
          {/if}

          {#if !collapsedGroups[group.name]}
            <div class="command-grid" class:wide={$panelWidth > 350}>
              {#each group.commands as cmd}
                <div class="cmd-with-fav">
                  <button
                    class="command-btn"
                    onclick={() => executeCommand(cmd.command)}
                    disabled={$isLoading}
                    title={cmd.command}
                  >
                    {cmd.label}
                  </button>
                  <button class="fav-star" class:starred={isFavorite(cmd.command)} onclick={() => toggleFavorite(cmd.command)} title={isFavorite(cmd.command) ? 'Убрать из избранного' : 'В избранное'}>
                    <svg width="10" height="10" viewBox="0 0 24 24" fill={isFavorite(cmd.command) ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="2">
                      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                    </svg>
                  </button>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/each}
    {/if}
  </div>
{/if}

<style>
  .command-panel {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .command-title {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 2px;
  }

  /* ── Search ── */
  .search-wrap {
    display: flex;
    align-items: center;
    gap: 5px;
    background: var(--input-bg);
    border: 1px solid var(--input-border);
    border-radius: 6px;
    padding: 4px 8px;
    margin-bottom: 4px;
    transition: border-color var(--transition-fast);
  }

  .search-wrap:focus-within {
    border-color: var(--accent-glow-strong);
  }

  .search-icon {
    color: var(--text-muted);
    flex-shrink: 0;
    opacity: 0.6;
  }

  .search-input {
    flex: 1;
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 11.5px;
    min-width: 0;
    outline: none;
  }

  .search-input::placeholder {
    color: var(--text-muted);
  }

  .search-clear {
    width: 16px;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: 3px;
    flex-shrink: 0;
    padding: 0;
  }

  .search-clear:hover {
    color: var(--text-primary);
    background: var(--hover-bg);
  }

  .no-results {
    font-size: 11px;
    color: var(--text-muted);
    text-align: center;
    padding: 12px 0;
    font-style: italic;
  }

  /* ── Groups ── */
  .command-group {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .group-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: none;
    border: none;
    padding: 0;
    cursor: default;
  }

  .group-header.collapsible {
    cursor: pointer;
    width: 100%;
    color: inherit;
    font: inherit;
  }

  .group-header.collapsible:hover .group-name {
    color: var(--text-muted);
  }

  .group-name {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 2px;
  }

  .fav-label {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--accent-secondary);
    opacity: 0.8;
  }

  .group-chevron {
    font-size: 9px;
    color: var(--text-muted);
    opacity: 0.5;
    transition: transform 0.18s ease;
  }

  .group-chevron.collapsed {
    transform: rotate(-90deg);
  }

  /* ── Command Grid ── */
  .command-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 3px;
  }

  .cmd-with-fav {
    position: relative;
  }

  .command-btn {
    width: 100%;
    padding: 6px 8px;
    background: transparent;
    color: var(--text-secondary);
    border: 1px solid var(--input-border);
    border-radius: 6px;
    font-size: 11.5px;
    cursor: pointer;
    text-align: center;
    transition: all var(--transition-fast);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .command-btn:hover:not(:disabled) {
    background: var(--hover-bg);
    border-color: var(--border-active);
    border-left: 2px solid var(--cabinet-color);
    color: var(--text-primary);
  }

  .command-btn:active:not(:disabled) {
    opacity: 0.8;
    transform: scale(0.97);
  }

  .command-btn:disabled {
    opacity: 0.45;
    cursor: default;
  }

  .fav-btn {
    border-color: color-mix(in srgb, var(--accent-secondary) 15%, transparent);
  }

  .fav-btn:hover:not(:disabled) {
    border-left-color: var(--accent-secondary);
  }

  /* ── Favorite Star ── */
  .fav-star {
    position: absolute;
    top: 2px;
    right: 2px;
    width: 16px;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--transition-fast), color var(--transition-fast);
    padding: 0;
  }

  .cmd-with-fav:hover .fav-star {
    opacity: 0.6;
  }

  .fav-star:hover {
    opacity: 1 !important;
    color: var(--accent-secondary);
  }

  .fav-star.starred {
    opacity: 1;
    color: var(--accent-secondary);
  }

  .command-grid.wide {
    grid-template-columns: 1fr;
  }

  .command-grid.wide .command-btn {
    white-space: normal;
    text-align: left;
  }
</style>
