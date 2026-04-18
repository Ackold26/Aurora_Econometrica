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
        <button
          class="project-item"
          class:active={$activeProjectId === p.id}
          onclick={() => { selectProject(p.id); showCreate = false; }}
        >
          <span class="item-name">{p.name}</span>
          <span class="item-date">{p.updated_at?.slice(0, 10)}</span>
        </button>
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
    right: 0;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.96));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 8px;
    padding: 4px;
    z-index: 50;
    max-height: 300px;
    overflow-y: auto;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }

  .project-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    padding: 8px 10px;
    background: transparent;
    border: none;
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    cursor: pointer;
    font-size: 13px;
    text-align: left;
  }

  .project-item:hover { background: rgba(255,255,255,0.06); }
  .project-item.active { background: var(--accent-primary, #3b82f6); color: white; }

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
