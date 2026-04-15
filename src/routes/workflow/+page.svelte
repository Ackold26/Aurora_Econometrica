<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { activeBrand } from '$lib/creative-store.js';
  import { toast } from '$lib/toast.js';
  import { HINTS } from '$lib/hints.js';
  import HintBubble from '$lib/components/workflow/HintBubble.svelte';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';

  /** @type {any} */
  let deleteTarget = $state(null);

  async function openHelp() {
    try { await invoke('open_help', { cabinetId: 'workflow-builder' }); }
    catch { toast('Справка недоступна', 'error'); }
  }

  /** @type {Array<{id: string, name: string, description: string, category: string, icon: string}>} */
  let templates = $state([]);
  /** @type {Array<{id: string, brand_id: string, name: string, created_at: string, campaign_type: string}>} */
  let workflows = $state([]);
  let loading = $state(true);

  let lastBrandId = $state('__init__');
  $effect(() => {
    const brandId = $activeBrand?.brand_id || '';
    if (brandId !== lastBrandId) {
      lastBrandId = brandId;
      loadData(brandId);
    }
  });

  /** @param {string} brandId */
  async function loadData(brandId) {
    loading = true;
    try {
      const [tpls, campaigns] = await Promise.all([
        invoke('workflow_templates'),
        brandId ? invoke('campaign_list', { brandId }) : Promise.resolve([]),
      ]);
      templates = tpls;
      workflows = /** @type {typeof workflows} */ (campaigns).filter(/** @param {any} c */ c => c.campaign_type === 'workflow');
    } catch (err) {
      console.error(err);
    }
    loading = false;
  }

  /** @param {{id: string, name: string}} template */
  async function createFromTemplate(template) {
    const brandId = $activeBrand?.brand_id || '';
    if (!brandId) {
      toast('Сначала создайте или выберите бренд', 'error');
      goto('/brands');
      return;
    }
    try {
      const wf = await invoke('workflow_create', {
        brandId,
        name: template.name,
        templateId: template.id,
        workflowSteps: null,
      });
      goto(`/workflow/${wf.id}`);
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    }
  }

  async function createEmpty() {
    const brandId = $activeBrand?.brand_id || '';
    if (!brandId) {
      toast('Сначала создайте или выберите бренд', 'error');
      goto('/brands');
      return;
    }
    try {
      const wf = await invoke('workflow_create', {
        brandId,
        name: 'Новый workflow',
        templateId: null,
        workflowSteps: [],
      });
      goto(`/workflow/${wf.id}`);
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    }
  }

  /** @param {{id: string}} wf */
  function openWorkflow(wf) {
    goto(`/workflow/${wf.id}`);
  }

  /** @param {any} wf */
  function deleteWorkflow(wf) {
    deleteTarget = wf;
  }

  async function confirmDelete() {
    const wf = deleteTarget;
    deleteTarget = null;
    if (!wf) return;
    const brandId = $activeBrand?.brand_id || '';
    if (!brandId) return;
    try {
      await invoke('workflow_delete', { brandId, workflowId: wf.id });
      toast('Workflow удалён', 'success');
      loadData(brandId);
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    }
  }
</script>

<div class="page">
  <header class="page-header">
    <button class="back-btn" onclick={() => goto('/')}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
    </button>
    <h1>Workflows</h1>
    {#if $activeBrand}
      <span class="brand-badge">{$activeBrand.name}</span>
    {/if}
    <button class="help-btn" onclick={openHelp} title="Справка">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
    </button>
  </header>

  <!-- Welcome hint -->
  <HintBubble hint={HINTS['wf-welcome']} />

  <!-- No brand hint -->
  {#if !$activeBrand}
    <HintBubble hint={HINTS['wf-need-brand']} />
  {/if}

  <!-- Templates -->
  <section class="section">
    <h2 class="section-title">Шаблоны</h2>
    <HintBubble hint={HINTS['wf-templates']} />
    <div class="template-grid">
      {#each templates as tpl}
        <button class="template-card" onclick={() => createFromTemplate(tpl)}>
          <span class="template-icon">{tpl.icon}</span>
          <span class="template-name">{tpl.name}</span>
          <span class="template-desc">{tpl.description}</span>
        </button>
      {/each}
      <button class="template-card template-card--empty" onclick={createEmpty}>
        <span class="template-icon">+</span>
        <span class="template-name">Пустой workflow</span>
        <span class="template-desc">Создать с нуля</span>
      </button>
    </div>
  </section>

  <!-- Existing workflows -->
  <section class="section">
    <h2 class="section-title">Мои workflows</h2>
    {#if loading}
      <div class="loading-placeholder">Загрузка...</div>
    {:else if workflows.length === 0}
      <EmptyState icon="🔧" title="Нет созданных workflows" description="Выберите шаблон выше или создайте пустой workflow" />
    {:else}
      <div class="workflow-list">
        {#each workflows as wf}
          <div class="workflow-item">
            <button class="workflow-item-main" onclick={() => openWorkflow(wf)}>
              <span class="workflow-name">{wf.name}</span>
              <span class="workflow-date">{new Date(wf.created_at).toLocaleDateString('ru-RU')}</span>
            </button>
            <button class="workflow-delete" onclick={() => deleteWorkflow(wf)} title="Удалить">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4h8v2M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </section>
</div>

<ConfirmDialog
  open={!!deleteTarget}
  title="Удалить workflow"
  message={`Удалить workflow "${deleteTarget?.name}"? Это действие нельзя отменить.`}
  confirmText="Удалить"
  danger={true}
  onConfirm={confirmDelete}
  onCancel={() => deleteTarget = null}
/>

<style>
  .page {
    max-width: 720px;
    margin: 0 auto;
    padding: 32px 24px;
    min-height: 100vh;
  }

  .page-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 32px;
  }

  .page-header h1 {
    font-size: 22px;
    font-weight: 600;
  }

  .back-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .back-btn:hover {
    border-color: var(--accent-primary);
    color: var(--accent-primary);
  }

  .help-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.15s;
    flex-shrink: 0;
  }

  .help-btn:hover {
    color: var(--accent-primary);
    border-color: var(--accent-glow-strong);
  }

  .brand-badge {
    margin-left: auto;
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 6px;
    background: var(--accent-glow);
    color: var(--accent-primary);
    border: 1px solid var(--accent-glow-strong);
  }

  .section {
    margin-bottom: 32px;
  }

  .section-title {
    font-size: 14px;
    font-weight: var(--font-weight-heading);
    color: var(--text-secondary);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .template-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }

  .template-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 16px;
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.07));
    border-radius: var(--radius-card);
    cursor: pointer;
    text-align: left;
    transition: var(--hover-timing);
    color: var(--text-primary);
  }

  .template-card:hover {
    border-color: var(--accent-primary);
    transform: var(--hover-transform);
    box-shadow: var(--shadow-elevation-2);
  }

  .template-card--empty {
    border-style: dashed;
    opacity: 0.7;
  }

  .template-card--empty:hover {
    opacity: 1;
  }

  .template-icon {
    font-size: 24px;
    line-height: 1;
  }

  .template-name {
    font-size: 14px;
    font-weight: 600;
  }

  .template-desc {
    font-size: 11px;
    color: var(--text-secondary);
    line-height: 1.4;
  }

  .workflow-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .workflow-item {
    display: flex;
    align-items: center;
    border-radius: var(--radius-sm);
    overflow: hidden;
  }

  .workflow-item-main {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.05));
    border-radius: var(--radius-sm);
    cursor: pointer;
    color: var(--text-primary);
    transition: all 0.15s ease;
  }

  .workflow-item-main:hover {
    border-color: var(--border);
    background: var(--bg-glass-hover);
  }

  .workflow-name {
    font-size: 14px;
    font-weight: 500;
  }

  .workflow-date {
    font-size: 12px;
    color: var(--text-muted);
  }

  .workflow-delete {
    padding: 8px;
    margin-left: 4px;
    background: transparent;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: 6px;
    transition: all 0.15s ease;
  }

  .workflow-delete:hover {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
  }


  .loading-placeholder {
    padding: 20px;
    text-align: center;
    color: var(--text-muted);
    font-size: 13px;
  }
</style>
