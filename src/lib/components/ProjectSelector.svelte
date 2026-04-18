<script>
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import { activeProjectId, activeProject, resetPipeline } from '$lib/project-state.js';

  /** @type {any[]} */
  let projects = $state([]);
  let showCreate = $state(false);
  let newName = $state('');
  let loading = $state(false);

  onMount(() => {
    loadProjects();
    loadActiveProject();
  });

  async function loadProjects() {
    try {
      projects = await invoke('project_list');
    } catch (e) {
      console.error('Failed to load projects:', e);
    }
  }

  async function loadActiveProject() {
    // Skip backend restore if user explicitly started a "new analysis" via ?new=1
    if (typeof window !== 'undefined' &&
        new URLSearchParams(window.location.search).get('new') === '1') {
      return;
    }
    try {
      const id = await invoke('project_get_active');
      if (id) {
        activeProjectId.set(id);
        const info = await invoke('project_get', { projectId: id });
        activeProject.set(info);
      }
    } catch { /* no active project */ }
  }

  /** @param {string} id */
  async function selectProject(id) {
    try {
      await invoke('project_activate', { projectId: id });
      const info = await invoke('project_get', { projectId: id });
      activeProject.set(info);      // Set BEFORE reset to avoid UI flash
      activeProjectId.set(id);
      resetPipeline();

      // Load pipeline stats
      const stats = await invoke('project_stats', { projectId: id });
      // TODO: populate pipelineState from stats
    } catch (e) {
      console.error('Failed to select project:', e);
    }
  }

  /**
   * Delete a project from disk. If it's the active one, clear active state.
   * @param {string} id
   * @param {string} name
   * @param {Event} e
   */
  async function deleteProject(id, name, e) {
    e.stopPropagation();
    const confirmed = confirm(`Удалить проект «${name}»? Все связанные данные (импорт, модель, отчёты) будут удалены безвозвратно.`);
    if (!confirmed) return;
    try {
      await invoke('project_delete', { projectId: id });
      projects = projects.filter(p => p.id !== id);
      if ($activeProjectId === id) {
        activeProjectId.set(null);
        activeProject.set(null);
      }
    } catch (err) {
      console.error('Delete failed:', err);
      alert(`Не удалось удалить проект: ${err}`);
    }
  }

  async function createProject() {
    const name = newName.trim();
    if (!name) return;
    loading = true;
    try {
      const info = await invoke('project_create', { name });
      activeProjectId.set(info.id);
      activeProject.set(info);
      // NOTE: do NOT resetPipeline() here — creating a project while importing
      // would nuke the user's current work. Reset only on explicit project switch.
      projects = [...projects, info];
      showCreate = false;
      newName = '';
    } catch (e) {
      console.error('Create failed:', e);
    }
    loading = false;
  }
</script>

<div class="project-selector">
  {#if $activeProject}
    <button class="project-btn" onclick={() => showCreate = !showCreate}>
      <span class="project-icon">📊</span>
      <span class="project-name">{$activeProject.name}</span>
      <span class="project-chevron">▾</span>
    </button>
  {:else}
    <button class="project-btn empty" onclick={() => showCreate = true}>
      <span class="project-icon">+</span>
      <span class="project-name">Создать проект</span>
    </button>
  {/if}

  {#if showCreate}
    <div class="project-dropdown">
      {#each projects as p}
        <div class="project-item-row" class:active={$activeProjectId === p.id}>
          <button
            class="project-item"
            onclick={() => { selectProject(p.id); showCreate = false; }}
          >
            <span class="item-name">{p.name}</span>
            <span class="item-date">{p.updated_at?.slice(0, 10)}</span>
          </button>
          <button
            class="item-delete"
            title="Удалить проект"
            aria-label="Удалить проект «{p.name}»"
            onclick={(e) => deleteProject(p.id, p.name, e)}
          >
            🗑
          </button>
        </div>
      {/each}

      <div class="project-create">
        <input
          type="text"
          placeholder="Название нового проекта..."
          bind:value={newName}
          onkeydown={(e) => e.key === 'Enter' && createProject()}
        />
        <button class="create-btn" onclick={createProject} disabled={loading || !newName.trim()}>
          {loading ? '...' : 'Создать'}
        </button>
      </div>
    </div>
  {/if}
</div>

<style>
  .project-selector {
    position: relative;
  }

  .project-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 8px;
    color: var(--text-primary, #e2e8f0);
    font-size: 13px;
    cursor: pointer;
    transition: background 0.15s;
    width: 100%;
    text-align: left;
  }

  .project-btn:hover {
    background: var(--bg-surface-hover, rgba(255,255,255,0.06));
  }

  .project-btn.empty {
    border-style: dashed;
    color: var(--text-secondary, #94a3b8);
  }

  .project-icon { font-size: 16px; }
  .project-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .project-chevron { opacity: 0.5; font-size: 10px; }

  .project-dropdown {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    min-width: 100%;
    width: max-content;
    max-width: 520px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.96));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 8px;
    padding: 6px;
    z-index: 50;
    max-height: 400px;
    overflow-y: auto;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }

  .project-item .item-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .project-item-row {
    display: flex;
    align-items: center;
    gap: 4px;
    border-radius: 6px;
    transition: background 0.15s;
  }
  .project-item-row:hover { background: color-mix(in srgb, var(--accent-primary) 8%, transparent); }
  .project-item-row.active {
    background: color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 40%, transparent);
  }

  .project-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex: 1;
    min-width: 0;
    gap: 12px;
    padding: 8px 10px;
    background: transparent;
    border: none;
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    cursor: pointer;
    font-size: 13px;
    text-align: left;
  }

  .item-delete {
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    border-radius: 6px;
    color: var(--text-muted);
    font-size: 14px;
    cursor: pointer;
    opacity: 0.5;
    transition: all 0.15s;
  }
  .item-delete:hover {
    background: color-mix(in srgb, var(--danger) 15%, transparent);
    color: var(--danger);
    opacity: 1;
  }

  .item-date { font-size: 11px; opacity: 0.5; }

  .project-create {
    display: flex;
    gap: 6px;
    padding: 8px 6px 4px;
    border-top: 1px solid rgba(255,255,255,0.06);
    margin-top: 4px;
  }

  .project-create input {
    flex: 1;
    padding: 6px 10px;
    background: rgba(0,0,0,0.3);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    font-size: 12px;
    outline: none;
  }

  .project-create input:focus {
    border-color: var(--accent-primary, #3b82f6);
  }

  .create-btn {
    padding: 6px 12px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 6px;
    color: white;
    font-size: 12px;
    cursor: pointer;
  }

  .create-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
