<script>
  import { invoke } from '@tauri-apps/api/core';
  import { activeCabinet, favoriteCommands, inboxFiles, cabinetCommands } from '$lib/store.js';
  import { getCommandMeta, getFileCommands } from '$lib/command-meta.js';
  import { get } from 'svelte/store';
  import CommandCard from './CommandCard.svelte';

  /**
   * @type {{
   *   cabinetId?: string,
   *   onExecute?: (command: string) => void,
   *   visibleCommands?: string[],
   * }}
   */
  let { cabinetId = '', onExecute, visibleCommands = undefined } = $props();

  /** Show all commands even if visibleCommands filter is active */
  let showAll = $state(false);

  // Reset showAll when cabinet changes
  $effect(() => {
    void cabinetId;
    showAll = false;
  });

  /** @type {Array<{command: string, label: string, group: string}>} */
  let commands = $state([]);
  let loadError = $state(false);
  let retryCounter = $state(0);

  // Load commands when cabinet changes or retry
  $effect(() => {
    const _retry = retryCounter; // dependency trigger
    if (!cabinetId) { commands = []; return; }
    loadError = false;
    invoke('get_cabinet_commands', { cabinetId })
      .then(cmds => { commands = /** @type {any[]} */ (cmds); cabinetCommands.set(cmds); })
      .catch(() => { loadError = true; commands = []; });
  });

  // File-aware commands for smart highlighting
  const fileCommands = $derived(getFileCommands(cabinetId));
  const hasInboxFiles = $derived($inboxFiles.length > 0);

  // Favorites for this cabinet
  const favs = $derived(new Set($favoriteCommands));

  // Quick Access: favorites + recent (inline, max 4)
  const quickItems = $derived.by(() => {
    const pinned = commands.filter(c => favs.has(c.command));
    return pinned.slice(0, 4);
  });

  // Filtered commands (novice mode)
  const displayCommands = $derived(
    visibleCommands && visibleCommands.length > 0 && !showAll
      ? commands.filter(c => visibleCommands.includes(c.command))
      : commands
  );

  // Group commands
  const grouped = $derived.by(() => {
    if (displayCommands.length === 0) return [];
    if (displayCommands.length < 8) return [{ name: '', commands: displayCommands, collapsed: false }];

    // Group by group field
    /** @type {Map<string, any[]>} */
    const map = new Map();
    for (const cmd of displayCommands) {
      const g = cmd.group || 'Основные';
      if (!map.has(g)) map.set(g, []);
      map.get(g)?.push(cmd);
    }

    const groups = [...map.entries()].map(([name, cmds]) => ({
      name, commands: cmds, collapsed: false,
    }));

    // Auto-collapse least used group if 3+ groups
    if (groups.length >= 3) {
      groups[groups.length - 1].collapsed = true;
    }

    return groups;
  });

  /** @type {Record<string, boolean>} */
  let collapsedState = $state({});

  // Loading timeout - show empty state after 5 seconds of skeleton
  let loadingTooLong = $state(false);
  $effect(() => {
    if (commands.length === 0 && !loadError && cabinetId) {
      loadingTooLong = false;
      const t = setTimeout(() => { loadingTooLong = true; }, 5000);
      return () => clearTimeout(t);
    }
  });

  /** @param {string} groupName */
  function toggleGroup(groupName) {
    collapsedState = { ...collapsedState, [groupName]: !collapsedState[groupName] };
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

  // Init collapsed state from grouped
  $effect(() => {
    /** @type {Record<string, boolean>} */
    const init = {};
    for (const g of grouped) {
      if (g.collapsed && !(g.name in collapsedState)) {
        init[g.name] = true;
      }
    }
    if (Object.keys(init).length > 0) {
      collapsedState = { ...collapsedState, ...init };
    }
  });
</script>

<div class="command-grid-container">
  {#if loadError}
    <div class="grid-error">
      <p>Команды недоступны</p>
      <button class="retry-btn" onclick={() => { retryCounter++; }}>Повторить</button>
    </div>

  {:else if commands.length === 0}
    {#if loadingTooLong}
      <div class="grid-error">
        <p>Команды не найдены для этого кабинета</p>
      </div>
    {:else}
      <div class="grid-loading">
        <div class="grid-skeleton"></div>
        <div class="grid-skeleton"></div>
        <div class="grid-skeleton"></div>
      </div>
    {/if}

  {:else}
    <!-- Cabinet orientation -->
    {#if $activeCabinet?.description}
      <p class="grid-intro">{$activeCabinet.description} - выберите команду или введите запрос.</p>
    {/if}

    <!-- Quick Access (pinned favorites) -->
    {#if quickItems.length > 0}
      <div class="quick-access">
        <span class="quick-label">Quick:</span>
        {#each quickItems as item (item.command)}
          <button class="quick-chip" onclick={() => onExecute?.(item.command)}>
            <span class="quick-star">★</span> {item.label}
          </button>
        {/each}
      </div>
    {/if}

    <!-- Command groups -->
    {#each grouped as group, gi (group.name || gi)}
      {#if group.name && grouped.length > 1}
        <button class="group-header" onclick={() => toggleGroup(group.name)}>
          <span class="group-name">{group.name}</span>
          <span class="group-count">{group.commands.length}</span>
          <svg class="group-chevron" class:collapsed={collapsedState[group.name]} width="12" height="12" viewBox="0 0 12 12">
            <path d="M3 4.5l3 3 3-3" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
          </svg>
        </button>
      {/if}

      {#if !collapsedState[group.name]}
        <div class="command-grid" role="grid">
          {#each group.commands as cmd, ci (cmd.command)}
            <CommandCard
              command={cmd.command}
              label={cmd.label}
              group={cmd.group}
              cabinetColor={$activeCabinet?.color}
              usageCount={0}
              isFavorite={favs.has(cmd.command)}
              highlighted={hasInboxFiles && fileCommands.includes(cmd.command)}
              animDelay={(gi * group.commands.length + ci) * 45}
              onExecute={onExecute}
              onToggleFavorite={toggleFavorite}
            />
          {/each}
        </div>
      {/if}
    {/each}

    <!-- Novice mode: show hidden commands count -->
    {#if visibleCommands && !showAll && commands.length > displayCommands.length}
      <button class="show-more-btn" onclick={() => { showAll = true; }}>
        Ещё {commands.length - displayCommands.length} команд
      </button>
    {/if}
  {/if}
</div>

<style>
  .command-grid-container {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px 20px;
    overflow-y: auto;
    flex: 1;
  }

  /* ─── Intro / Orientation ─── */
  .grid-intro {
    font-size: 13px;
    color: var(--text-muted, #7A7A90);
    line-height: 1.5;
    animation: fadeIn 0.4s ease-out;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  /* ─── Quick Access ─── */
  .quick-access {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
  }

  .quick-label {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted, #7A7A90);
    margin-right: 4px;
  }

  .quick-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 12px;
    background: var(--hover-bg);
    border: 1px solid var(--accent-glow-strong);
    border-radius: var(--radius-btn);
    color: var(--text-secondary, #A8A8B8);
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    transition: all 150ms ease-out;
  }

  .quick-chip:hover {
    background: var(--accent-glow);
    border-color: var(--accent-glow-strong);
    color: var(--text-primary, #EAEAF0);
  }

  .quick-chip:active {
    transform: scale(0.95);
    transition-duration: 80ms;
  }

  .quick-star {
    font-size: 10px;
    color: var(--accent-secondary, #CCFF00);
  }

  /* ─── Group header ─── */
  .group-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 4px;
    background: none;
    border: none;
    color: var(--text-muted, #7A7A90);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    cursor: pointer;
    font-family: inherit;
    transition: color 150ms;
  }

  .group-name::before {
    content: '';
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    margin-right: 6px;
    background: var(--accent-primary);
    vertical-align: middle;
  }

  .group-header:nth-of-type(2) .group-name::before {
    background: var(--color-info, var(--accent-primary));
  }

  .group-header:hover {
    color: var(--text-secondary, #A8A8B8);
  }

  .group-count {
    font-size: 10px;
    opacity: 0.5;
    font-weight: 400;
  }

  .group-chevron {
    transition: transform 200ms ease-out;
    opacity: 0.5;
  }

  .group-chevron.collapsed {
    transform: rotate(-90deg);
  }

  /* ─── Command grid ─── */
  .command-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 8px;
  }

  /* ─── Loading / Error ─── */
  .grid-loading {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 8px;
  }

  .grid-skeleton {
    height: 80px;
    border-radius: 12px;
    background: linear-gradient(90deg, var(--bg-card, #181824) 25%, var(--bg-card-hover, #22222F) 50%, var(--bg-card, #181824) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s linear infinite;
  }

  .grid-error {
    text-align: center;
    padding: 32px;
    color: var(--text-muted, #7A7A90);
    font-size: 14px;
  }

  .retry-btn {
    margin-top: 12px;
    padding: 6px 16px;
    background: var(--accent-primary, #2E5BFF);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-btn);
    font-size: 13px;
    font-family: inherit;
    cursor: pointer;
  }

  .retry-btn:hover {
    filter: brightness(1.1);
  }

  /* ─── Show more (novice mode) ─── */
  .show-more-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    padding: 8px;
    background: none;
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.10));
    border-radius: var(--radius-btn);
    color: var(--text-muted, #7A7A90);
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    transition: all 150ms ease-out;
    margin-top: 4px;
  }

  .show-more-btn:hover {
    border-color: var(--accent-glow-strong);
    color: var(--accent-primary, #2E5BFF);
    background: var(--hover-bg);
  }
</style>
