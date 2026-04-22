<script>
  /**
   * Модалка выбора второго проекта для сравнения. Показывает все проекты
   * кроме activeProjectId, с фильтрацией по имени. Single-select → onSelect(id).
   *
   * @component ProjectPickerModal
   */
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';

  /** @type {{ open: boolean, excludeId: string | null, onSelect: (id: string, info: any) => void, onCancel: () => void }} */
  let { open, excludeId, onSelect, onCancel } = $props();

  /** @type {any[]} */
  let projects = $state([]);
  let loading = $state(false);
  let query = $state('');
  /** @type {string | null} */
  let errorMsg = $state(null);

  onMount(() => {
    loadProjects();
  });

  // Перезагружаем список когда открывается модалка (могли добавиться новые)
  $effect(() => {
    if (open) loadProjects();
  });

  async function loadProjects() {
    loading = true;
    errorMsg = null;
    try {
      projects = /** @type {any[]} */ (await invoke('project_list'));
    } catch (e) {
      errorMsg = `Не удалось загрузить проекты: ${e}`;
    }
    loading = false;
  }

  const filtered = $derived(
    projects
      .filter((p) => p.id !== excludeId)
      .filter((p) => {
        if (!query.trim()) return true;
        const q = query.trim().toLowerCase();
        return (
          (p.name || '').toLowerCase().includes(q) ||
          (p.id || '').toLowerCase().includes(q) ||
          (p.kpi_column || '').toLowerCase().includes(q)
        );
      })
  );

  /** @param {any} p */
  function pick(p) {
    onSelect(p.id, p);
  }

  /** @param {KeyboardEvent} e */
  function onOverlayKey(e) {
    if (e.key === 'Escape') onCancel();
  }
</script>

{#if open}
  <div
    class="pm-overlay"
    onclick={onCancel}
    role="button"
    tabindex="-1"
    onkeydown={onOverlayKey}
  >
    <div
      class="pm-dialog"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
      role="dialog"
      aria-modal="true"
      aria-label="Выбрать проект для сравнения"
      tabindex="0"
    >
      <h3 class="pm-title">⚖ Выбрать проект для сравнения</h3>
      <p class="pm-sub">
        Будет открыт side-by-side отчёт. Активный проект не переключится.
      </p>

      <input
        class="pm-search"
        type="text"
        placeholder="Поиск по имени, KPI..."
        bind:value={query}
        autofocus
      />

      {#if loading}
        <div class="pm-state">Загрузка...</div>
      {:else if errorMsg}
        <div class="pm-state pm-err">{errorMsg}</div>
      {:else if filtered.length === 0}
        <div class="pm-state">
          {#if projects.filter((p) => p.id !== excludeId).length === 0}
            Других проектов нет — создайте второй проект, чтобы сравнивать.
          {:else}
            Ничего не найдено. Попробуйте другой запрос.
          {/if}
        </div>
      {:else}
        <div class="pm-list">
          {#each filtered as p (p.id)}
            <button class="pm-item" onclick={() => pick(p)}>
              <div class="pm-item-main">
                <span class="pm-name">{p.name || p.id}</span>
                <span class="pm-kpi">{p.kpi_column || '—'}</span>
              </div>
              <div class="pm-item-meta">
                <span class="pm-date">{(p.updated_at || '').slice(0, 10)}</span>
                <span class="pm-media">{(p.media_columns || []).length} каналов</span>
              </div>
            </button>
          {/each}
        </div>
      {/if}

      <div class="pm-actions">
        <button class="pm-btn pm-btn--cancel" onclick={onCancel}>Отмена</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .pm-overlay {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: var(--overlay-bg, rgba(0, 0, 0, 0.55));
    backdrop-filter: var(--blur-quiet, blur(4px));
    display: flex;
    align-items: center;
    justify-content: center;
    animation: pm-fade-in 0.15s ease;
  }
  @keyframes pm-fade-in {
    from { opacity: 0; }
  }
  .pm-dialog {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg, 12px);
    padding: 24px;
    max-width: 520px;
    width: 92%;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    box-shadow: var(--shadow);
    animation: pm-slide-up 0.2s ease;
  }
  @keyframes pm-slide-up {
    from { transform: translateY(12px); opacity: 0; }
  }
  .pm-title {
    font-size: var(--font-lg, 17px);
    font-weight: 700;
    color: var(--text-primary);
    margin: 0 0 6px 0;
  }
  .pm-sub {
    font-size: var(--font-sm, 13px);
    color: var(--text-secondary);
    margin: 0 0 14px 0;
    line-height: 1.5;
  }
  .pm-search {
    width: 100%;
    padding: 9px 12px;
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    color: var(--text-primary);
    font-size: 13px;
    outline: none;
    margin-bottom: 12px;
  }
  .pm-search:focus {
    border-color: var(--accent-primary);
  }
  .pm-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 14px;
    min-height: 120px;
    max-height: 360px;
  }
  .pm-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 12px;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
    border-radius: var(--radius-sm, 6px);
    color: var(--text-primary);
    font-family: inherit;
    font-size: 13px;
    text-align: left;
    cursor: pointer;
    transition: all 0.15s;
  }
  .pm-item:hover {
    background: color-mix(in srgb, var(--accent-primary) 10%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary) 40%, transparent);
  }
  .pm-item-main {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }
  .pm-name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pm-kpi {
    font-size: 11px;
    color: var(--text-secondary);
  }
  .pm-item-meta {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
    font-size: 11px;
    color: var(--text-muted, #94a3b8);
    flex-shrink: 0;
  }
  .pm-state {
    padding: 24px 12px;
    text-align: center;
    color: var(--text-secondary);
    font-size: 13px;
  }
  .pm-err {
    color: var(--danger, #ef4444);
  }
  .pm-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  .pm-btn {
    padding: 8px 18px;
    border-radius: var(--radius-sm, 6px);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    font-family: inherit;
  }
  .pm-btn--cancel {
    background: transparent;
    border-color: var(--border);
    color: var(--text-secondary);
  }
  .pm-btn--cancel:hover {
    background: var(--hover-bg, rgba(255, 255, 255, 0.04));
    color: var(--text-primary);
  }
</style>
