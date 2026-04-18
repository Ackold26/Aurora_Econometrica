<script>
  /**
   * Scenario Playground — minimal MVP (~80 lines).
   * B1: Save current budget as scenario + compare table. No xlsx upload (ScenarioCompare handles that).
   * @component ScenarioPlayground
   */
  import { invoke } from '@tauri-apps/api/core';
  import { activeProjectId, sessionStats } from '$lib/project-state.js';
  import { get } from 'svelte/store';
  import DataTable from '$lib/components/DataTable.svelte';

  /** @type {{ channelBudgets: Record<string, number>, channels: string[] }} */
  let { channelBudgets, channels } = $props();

  /** @type {'idle' | 'saving' | 'comparing'} */
  let status = $state('idle');
  /** @type {string | null} */
  let errorMsg = $state(null);
  /** @type {any | null} */
  let comparison = $state(null);
  let scenarioName = $state('');

  async function saveScenario() {
    const projectId = get(activeProjectId);
    if (!projectId) return;
    status = 'saving';
    errorMsg = null;
    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const name = scenarioName.trim() || `scenario-${Date.now()}`;
      /** @type {Record<string, number[]>} */
      const mediaPlan = {};
      for (const ch of channels) mediaPlan[ch] = [channelBudgets[ch] ?? 0];

      const result = /** @type {any} */ (await invoke('econ_scenario', {
        projectDir,
        scenarioName: name,
        mediaPlan,
      }));
      if (result.status === 'ok') {
        scenarioName = '';
        sessionStats.update(s => ({ ...s, scenarioCount: s.scenarioCount + 1 }));
        await loadComparison();
      } else {
        errorMsg = result.message || 'Ошибка сохранения';
      }
    } catch (/** @type {any} */ e) {
      errorMsg = String(e);
    }
    status = 'idle';
  }

  async function loadComparison() {
    const projectId = get(activeProjectId);
    if (!projectId) return;
    status = 'comparing';
    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const result = /** @type {any} */ (await invoke('econ_compare', { projectDir }));
      if (result.status === 'ok') {
        comparison = result.comparison || null;
      }
    } catch { /* silent */ }
    status = 'idle';
  }
</script>

<div class="scenario-playground">
  <div class="save-row">
    <input
      class="name-input"
      type="text"
      placeholder="Название сценария (необязательно)"
      bind:value={scenarioName}
    />
    <button
      class="btn-save"
      onclick={saveScenario}
      disabled={status !== 'idle'}
    >
      {status === 'saving' ? 'Сохраняю...' : 'Сохранить сценарий'}
    </button>
    {#if comparison}
      <button class="btn-compare" onclick={loadComparison} disabled={status !== 'idle'}>
        {status === 'comparing' ? '...' : 'Обновить'}
      </button>
    {:else}
      <button class="btn-compare" onclick={loadComparison} disabled={status !== 'idle'}>
        Сравнить сценарии
      </button>
    {/if}
  </div>

  {#if errorMsg}
    <div class="error">{errorMsg}</div>
  {/if}

  {#if comparison}
    <DataTable
      mode="scenario"
      title="Сравнение сценариев"
      headers={comparison.headers}
      rows={comparison.rows}
      highlightColumn={comparison.headers?.[1]}
    />
  {/if}
</div>

<style>
  .scenario-playground {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .save-row {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }

  .name-input {
    flex: 1;
    min-width: 160px;
    padding: 8px 12px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 7px;
    color: var(--text-primary, #e2e8f0);
    font-size: 13px;
    outline: none;
  }
  .name-input:focus { border-color: color-mix(in srgb, var(--accent-primary) 40%, transparent); }
  .name-input::placeholder { color: var(--text-secondary, #94a3b8); }

  .btn-save {
    padding: 8px 14px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 7px;
    color: white;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition: opacity 0.15s;
  }
  .btn-save:hover:not(:disabled) { opacity: 0.85; }
  .btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

  .btn-compare {
    padding: 8px 14px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 7px;
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
  }
  .btn-compare:hover:not(:disabled) { border-color: rgba(255,255,255,0.25); color: var(--text-primary, #e2e8f0); }
  .btn-compare:disabled { opacity: 0.5; cursor: not-allowed; }

  .error {
    font-size: 12px;
    color: #ef4444;
    padding: 6px 10px;
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border-radius: 6px;
  }
</style>
