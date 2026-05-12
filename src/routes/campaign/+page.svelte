<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { activeBrand } from '$lib/creative-store.js';

  /** @type {Array<any>} */
  let campaigns = $state([]);
  let showCreate = $state(false);
  let newName = $state('');
  let creating = $state(false);
  let error = $state('');

  function getBrandId() {
    return $activeBrand?.brand_id || '';
  }

  async function loadCampaigns() {
    try {
      campaigns = await invoke('campaign_list', { brandId: getBrandId() });
    } catch { campaigns = []; }
  }

  async function createCampaign() {
    if (!newName.trim()) return;
    creating = true;
    error = '';
    try {
      await invoke('campaign_create', { brandId: getBrandId(), name: newName.trim() });
      newName = '';
      showCreate = false;
      await loadCampaigns();
    } catch (err) {
      error = String(err);
    } finally {
      creating = false;
    }
  }

  /** @param {any} campaign */
  async function openCampaign(campaign) {
    goto(`/campaign`);
  }

  loadCampaigns();
</script>

<div class="campaign-page">
  <div class="campaign-container">
    <div class="campaign-header">
      <button class="back-link" onclick={() => goto('/')}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
        Назад
      </button>
      <h1 class="campaign-title">Кампании</h1>
      {#if $activeBrand}
        <span class="campaign-brand">{$activeBrand.name}</span>
      {/if}
    </div>

    <div class="campaign-actions">
      {#if showCreate}
        <div class="create-form">
          <input
            class="create-input"
            type="text"
            placeholder="Название кампании..."
            bind:value={newName}
            onkeydown={(e) => e.key === 'Enter' && createCampaign()}
          />
          <button class="btn-create" onclick={createCampaign} disabled={creating || !newName.trim()}>
            {creating ? '...' : 'Создать'}
          </button>
          <button class="btn-cancel" onclick={() => showCreate = false}>Отмена</button>
        </div>
        {#if error}
          <div class="create-error">{error}</div>
        {/if}
      {:else}
        <button class="btn-new" onclick={() => showCreate = true}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Новая кампания
        </button>
      {/if}
    </div>

    {#if campaigns.length === 0}
      <div class="empty-state">
        <p class="empty-text">Нет кампаний</p>
        <p class="empty-hint">Кампания - пошаговый workflow через кабинеты: аналитика → стратегия → концепция → тексты → визуалы → тестирование</p>
      </div>
    {:else}
      <div class="campaigns-list">
        {#each campaigns as campaign}
          <div class="campaign-card">
            <div class="campaign-card-header">
              <span class="campaign-card-name">{campaign.name}</span>
              <span class="campaign-card-type">{campaign.campaign_type === 'workflow' ? 'Workflow' : 'Линейная'}</span>
            </div>
            <div class="campaign-card-meta">
              <span>{campaign.steps?.length || 0} шагов</span>
              <span>{new Date(campaign.created_at).toLocaleDateString('ru-RU')}</span>
            </div>
            <div class="campaign-steps-bar">
              {#each campaign.steps || [] as step}
                <div class="step-dot" class:step-completed={step.status === 'completed'} class:step-active={step.status === 'in_progress'} title={step.name}></div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

<style>
  .campaign-page {
    min-height: 100vh;
    display: flex;
    justify-content: center;
    padding: 32px 24px;
    background: var(--bg-primary);
  }

  .campaign-container { width: 100%; max-width: 640px; }

  .campaign-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
  }

  .back-link {
    display: flex;
    align-items: center;
    gap: 5px;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 500;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    transition: color 0.15s ease;
  }

  .back-link:hover { color: var(--text-primary); }

  .campaign-title {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.02em;
  }

  .campaign-brand {
    font-size: 12px;
    color: var(--text-muted);
    background: color-mix(in srgb, var(--success) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 20%, transparent);
    padding: 2px 10px;
    border-radius: 12px;
  }

  .campaign-actions { margin-bottom: 20px; }

  .btn-new {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    background: var(--accent-primary);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-btn);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-new:hover { filter: brightness(1.15); }

  .create-form { display: flex; gap: 8px; align-items: center; }

  .create-input {
    flex: 1;
    padding: 8px 12px;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-input);
    color: var(--text-primary);
    font-size: 13px;
    outline: none;
  }

  .create-input:focus { border-color: var(--accent-primary); }

  .btn-create {
    padding: 8px 16px;
    background: var(--success);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-btn);
    font-size: 13px;
    cursor: pointer;
  }

  .btn-create:disabled { opacity: 0.4; cursor: not-allowed; }

  .btn-cancel {
    padding: 8px 12px;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: var(--radius-btn);
    color: var(--text-muted);
    font-size: 13px;
    cursor: pointer;
  }

  .create-error { margin-top: 8px; font-size: 12px; color: color-mix(in srgb, var(--danger) 65%, transparent); }

  .empty-state { text-align: center; padding: 40px 20px; }
  .empty-text { font-size: 14px; color: var(--text-secondary); margin-bottom: 8px; }
  .empty-hint { font-size: 12px; color: var(--text-muted); line-height: 1.5; }

  .campaigns-list { display: flex; flex-direction: column; gap: 12px; }

  .campaign-card {
    padding: 16px;
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    border: 1px solid var(--hover-bg);
    border-radius: 12px;
  }

  .campaign-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }

  .campaign-card-name { font-size: 14px; font-weight: 600; }

  .campaign-card-type {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    background: var(--hover-bg);
    padding: 2px 8px;
    border-radius: 4px;
  }

  .campaign-card-meta {
    display: flex;
    gap: 16px;
    font-size: 11px;
    color: var(--text-muted);
    margin-bottom: 10px;
  }

  .campaign-steps-bar {
    display: flex;
    gap: 4px;
  }

  .step-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--border);
    transition: background 0.2s;
  }

  .step-completed { background: var(--success); }
  .step-active { background: var(--accent-primary); animation: pulse 1.5s infinite; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
</style>
