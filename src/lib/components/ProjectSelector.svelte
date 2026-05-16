<script>
  import { invoke } from '@tauri-apps/api/core';
  import { save as saveDialog, open as openDialog } from '@tauri-apps/plugin-dialog';
  import { onMount } from 'svelte';
  import { activeProjectId, activeProject, resetPipeline } from '$lib/project-state.js';
  import ProjectPickerModal from '$lib/components/comparison/ProjectPickerModal.svelte';
  import ModelComparisonView from '$lib/components/comparison/ModelComparisonView.svelte';

  /** @type {any[]} */
  let projects = $state([]);
  let showCreate = $state(false);
  let newName = $state('');
  /**
   * H-09: industry selection при создании проекта. Default 'unknown' →
   * UnitCostEditor показывает generic low-confidence ranges. Customer
   * выбирает specific industry для targeted suggestions (Mediascope 2024).
   */
  let newIndustry = $state('unknown');
  let loading = $state(false);
  let archiving = $state(false);
  /** @type {string} */
  let archiveMsg = $state('');

  // ── Comparison flow ──────────────────────────────────────────────────
  /** @type {string | null} */
  let comparePrimaryId = $state(null);   // при клике «⚖» на проекте - сохраняем его id
  let pickerOpen = $state(false);
  /** @type {{ primaryId: string, secondaryId: string } | null} */
  let comparisonOpen = $state(null);

  /** @param {string} id @param {Event} e */
  function startCompare(id, e) {
    e.stopPropagation();
    comparePrimaryId = id;
    pickerOpen = true;
    showCreate = false;
  }
  /** @param {string} secondaryId */
  function onPickerSelect(secondaryId) {
    pickerOpen = false;
    if (comparePrimaryId) {
      comparisonOpen = { primaryId: comparePrimaryId, secondaryId };
    }
  }
  function onPickerCancel() {
    pickerOpen = false;
    comparePrimaryId = null;
  }
  function onComparisonClose() {
    comparisonOpen = null;
    comparePrimaryId = null;
  }

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
      resetPipeline(id);             // передаём id чтобы restore перечитал results

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
      // H-09: pass industry для context-aware unit_cost suggestions.
      const info = await invoke('project_create', {
        name,
        industry: newIndustry || 'unknown',
      });
      activeProjectId.set(info.id);
      activeProject.set(info);
      // NOTE: do NOT resetPipeline() here - creating a project while importing
      // would nuke the user's current work. Reset only on explicit project switch.
      projects = [...projects, info];
      showCreate = false;
      newName = '';
      newIndustry = 'unknown';
    } catch (e) {
      console.error('Create failed:', e);
    }
    loading = false;
  }

  /** Экспорт текущего активного проекта в .aurora архив. */
  async function exportCurrentProject() {
    if (!$activeProject || archiving) return;
    const safeName = ($activeProject.name || 'project')
      .replace(/[^\p{L}\p{N}._ -]/gu, '_')
      .slice(0, 100);
    const suggested = `${safeName}.aurora`;
    archiving = true;
    archiveMsg = '';
    try {
      const outputPath = await saveDialog({
        defaultPath: suggested,
        filters: [{ name: 'Aurora Project', extensions: ['aurora', 'zip'] }],
        title: 'Сохранить проект как архив',
      });
      if (!outputPath) {
        archiving = false;
        return;
      }
      await invoke('project_export_archive', {
        projectId: $activeProjectId,
        outputPath,
      });
      archiveMsg = `✓ Сохранено: ${outputPath}`;
      setTimeout(() => { archiveMsg = ''; }, 6000);
    } catch (e) {
      archiveMsg = `Ошибка: ${e}`;
      setTimeout(() => { archiveMsg = ''; }, 8000);
    } finally {
      archiving = false;
    }
  }

  /** Импорт проекта из .aurora архива - создаёт новый project_id и активирует. */
  async function importProjectFromArchive() {
    if (archiving) return;
    archiving = true;
    archiveMsg = '';
    try {
      const selected = await openDialog({
        filters: [{ name: 'Aurora Project', extensions: ['aurora', 'zip'] }],
        multiple: false,
        title: 'Выбрать .aurora архив проекта',
      });
      if (!selected || typeof selected !== 'string') {
        archiving = false;
        return;
      }
      const result = /** @type {any} */ (await invoke('project_import_archive', {
        archivePath: selected,
      }));
      const newId = result.project_id;
      const info = result.info;

      // Активировать импортированный проект
      await invoke('project_activate', { projectId: newId });
      activeProject.set(info);
      activeProjectId.set(newId);
      resetPipeline(newId);          // передаём id → restore result JSONs
      projects = [...projects, info];
      showCreate = false;
      archiveMsg = `✓ Проект «${info.name ?? newId}» импортирован`;
      setTimeout(() => { archiveMsg = ''; }, 6000);

      // Перезагрузить полный список с диска (чтобы подхватить existing сохранёнки)
      await loadProjects();
    } catch (e) {
      archiveMsg = `Ошибка импорта: ${e}`;
      setTimeout(() => { archiveMsg = ''; }, 8000);
    } finally {
      archiving = false;
    }
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
            class="item-compare"
            title="Сравнить с другим проектом"
            aria-label="Сравнить проект «{p.name}» с другим"
            onclick={(e) => startCompare(p.id, e)}
          >
            ⚖
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
        <!-- H-09: industry selector для смарт-подсказок unit_cost (Phase 4.1 wire) -->
        <select
          class="industry-select"
          bind:value={newIndustry}
          title="Отрасль - для подсказок типичной стоимости 1 ед. медиа"
          aria-label="Отрасль проекта"
        >
          <option value="unknown">- Отрасль -</option>
          <option value="pharma_otc">Фарма OTC</option>
          <option value="pharma_rx">Фарма Rx</option>
          <option value="fmcg">FMCG</option>
          <option value="retail">Розница</option>
          <option value="saas">SaaS / Digital</option>
          <option value="finance">Финансы</option>
          <option value="b2b">B2B</option>
        </select>
        <button class="create-btn" onclick={createProject} disabled={loading || !newName.trim()}>
          {loading ? '...' : 'Создать'}
        </button>
      </div>

      <div class="project-archive-row">
        {#if $activeProject}
          <button
            class="archive-btn"
            onclick={exportCurrentProject}
            disabled={archiving}
            title="Сохранить активный проект в один .aurora файл (данные + модель + результаты + сценарии)"
          >
            💾 Сохранить как архив
          </button>
        {/if}
        <button
          class="archive-btn"
          onclick={importProjectFromArchive}
          disabled={archiving}
          title="Загрузить ранее сохранённый .aurora файл как новый проект"
        >
          📦 Загрузить из архива
        </button>
      </div>
      {#if archiveMsg}
        <div class="archive-msg" class:archive-err={archiveMsg.startsWith('Ошибка')}>
          {archiveMsg}
        </div>
      {/if}
    </div>
  {/if}
</div>

<ProjectPickerModal
  open={pickerOpen}
  excludeId={comparePrimaryId}
  onSelect={(id) => onPickerSelect(id)}
  onCancel={onPickerCancel}
/>

{#if comparisonOpen}
  <ModelComparisonView
    primaryId={comparisonOpen.primaryId}
    secondaryId={comparisonOpen.secondaryId}
    onClose={onComparisonClose}
  />
{/if}

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

  .item-delete, .item-compare {
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
  .item-compare:hover {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 15%, transparent);
    color: var(--accent-primary, #3b82f6);
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

  /* H-09: industry selector для smart unit_cost suggestions. */
  .industry-select {
    padding: 6px 10px;
    background: var(--bg-input, rgba(255,255,255,0.03));
    color: var(--text-primary);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
    border-radius: 6px;
    font-size: 12.5px;
    cursor: pointer;
    flex: 0 0 130px;
  }
  .industry-select:focus {
    outline: none;
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

  .project-archive-row {
    display: flex;
    gap: 6px;
    padding: 10px 12px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    flex-wrap: wrap;
  }

  .archive-btn {
    flex: 1;
    min-width: 140px;
    padding: 7px 10px;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    color: var(--text-secondary, #94a3b8);
    border-radius: 6px;
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    transition: all 0.15s;
    text-align: left;
  }
  .archive-btn:hover:not(:disabled) {
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 40%, transparent);
    color: var(--text-primary, #e2e8f0);
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 8%, transparent);
  }
  .archive-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .archive-msg {
    padding: 8px 12px;
    color: var(--success, #22c55e);
    font-size: 11px;
    line-height: 1.4;
    word-break: break-all;
  }
  .archive-msg.archive-err { color: var(--danger, #ef4444); }
</style>
