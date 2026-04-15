<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow';
  import { activeBrandId, setActiveBrand, updateBrand, deleteBrand, isCreativeHub } from '$lib/creative-store.js';
  import { toast } from '$lib/toast.js';

  let brandId = $derived(/** @type {string} */ ($page.params.id || ''));

  /** @type {any} */
  let brand = $state(null);
  /** @type {any} */
  let stats = $state(null);
  /** @type {Array<{filename: string, size: number, modified_at: number}>} */
  let docs = $state([]);
  let loading = $state(true);

  // Edit state
  let editing = $state(false);
  let editName = $state('');
  let editIndustry = $state('');
  let editDescription = $state('');
  let saving = $state(false);

  // Upload state
  let uploading = $state(false);

  // Delete state
  let showDeleteConfirm = $state(false);
  let deleting = $state(false);

  // Drag-drop
  let dragOver = $state(false);
  /** @type {HTMLElement|undefined} */
  let docsZone = $state(undefined);

  // Route guard
  onMount(() => {
    if (!$isCreativeHub) { goto('/'); }
  });

  let lastLoadedId = $state('__init__');
  $effect(() => {
    const id = brandId;
    if (id && id !== lastLoadedId) {
      lastLoadedId = id;
      loadBrand(id);
    }
  });

  // Drag-drop listener
  $effect(() => {
    const appWindow = getCurrentWebviewWindow();
    /** @type {(() => void)|undefined} */
    let unlisten;

    appWindow.onDragDropEvent((event) => {
      if (event.payload.type === 'over') {
        const { x, y } = event.payload.position;
        dragOver = isInsideElement(docsZone, x, y);
      } else if (event.payload.type === 'drop') {
        const { x, y } = event.payload.position;
        if (isInsideElement(docsZone, x, y) && event.payload.paths?.length) {
          handleDroppedFiles(event.payload.paths);
        }
        dragOver = false;
      } else if (event.payload.type === 'leave') {
        dragOver = false;
      }
    }).then(fn => { unlisten = fn; });

    return () => { if (unlisten) unlisten(); };
  });

  /** @param {HTMLElement|undefined} el @param {number} x @param {number} y */
  function isInsideElement(el, x, y) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }

  /** @param {number} bytes */
  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' Б';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' КБ';
    return (bytes / (1024 * 1024)).toFixed(1) + ' МБ';
  }

  /** @param {string} id */
  async function loadBrand(id) {
    loading = true;
    try {
      brand = await invoke('brand_get', { brandId: id });
      stats = await invoke('brand_stats', { brandId: id });
      docs = /** @type {typeof docs} */ (await invoke('brand_list_docs', { brandId: id }));
    } catch (err) {
      toast(`Бренд не найден: ${err}`, 'error');
      goto('/brands');
    } finally {
      loading = false;
    }
  }

  async function activateBrand() {
    try {
      await setActiveBrand(brandId);
      toast(`Бренд "${brand?.name}" активирован`, 'success');
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    }
  }

  // ── Editing ──

  function startEdit() {
    editName = brand?.name || '';
    editIndustry = brand?.industry || '';
    editDescription = brand?.description || '';
    editing = true;
  }

  function cancelEdit() {
    editing = false;
  }

  async function saveEdit() {
    if (!editName.trim()) { toast('Имя обязательно', 'error'); return; }
    saving = true;
    try {
      brand = await updateBrand(brandId, editName.trim(), editIndustry.trim(), editDescription.trim());
      editing = false;
      toast('Бренд обновлён', 'success');
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    } finally {
      saving = false;
    }
  }

  // ── Documents ──

  async function uploadDocument() {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog');
      const selected = /** @type {any} */ (await open({
        multiple: true,
        filters: [
          { name: 'Документы', extensions: ['pdf', 'docx', 'txt', 'md', 'csv', 'json', 'xlsx'] },
          { name: 'Все файлы', extensions: ['*'] },
        ],
      }));
      if (!selected) return;
      const paths = Array.isArray(selected) ? selected : [selected];
      await uploadFiles(paths.map(p => typeof p === 'string' ? p : p.path));
    } catch (err) {
      toast(`Ошибка загрузки: ${err}`, 'error');
    }
  }

  /** @param {string[]} paths */
  async function handleDroppedFiles(paths) {
    await uploadFiles(paths);
  }

  /** @param {string[]} paths */
  async function uploadFiles(paths) {
    uploading = true;
    let count = 0;
    for (const filePath of paths) {
      try {
        await invoke('brand_upload_doc', { brandId, filePath });
        count++;
      } catch (err) {
        toast(`Ошибка: ${err}`, 'error');
      }
    }
    if (count > 0) {
      toast(`${count} документ(ов) добавлено`, 'success');
    }
    docs = /** @type {typeof docs} */ (await invoke('brand_list_docs', { brandId }));
    stats = await invoke('brand_stats', { brandId });
    uploading = false;
  }

  /** @param {string} filename */
  async function deleteDoc(filename) {
    try {
      await invoke('brand_delete_doc', { brandId, filename });
      docs = /** @type {typeof docs} */ (await invoke('brand_list_docs', { brandId }));
      stats = await invoke('brand_stats', { brandId });
      toast(`"${filename}" удалён`, 'success');
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    }
  }

  // ── Delete Brand ──

  async function confirmDelete() {
    deleting = true;
    try {
      await deleteBrand(brandId);
      toast('Бренд удалён', 'success');
      goto('/brands');
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    } finally {
      deleting = false;
      showDeleteConfirm = false;
    }
  }
</script>

<div class="brand-page">
  <header class="brand-header">
    <button class="back-btn" onclick={() => goto('/brands')}>← Бренды</button>
    {#if brand}
      <h1>{brand.name}</h1>
      {#if $activeBrandId !== brandId}
        <button class="activate-btn" onclick={activateBrand}>Активировать</button>
      {:else}
        <span class="active-badge">Активный</span>
      {/if}
      <button class="delete-btn" onclick={() => showDeleteConfirm = true}>Удалить</button>
    {/if}
  </header>

  {#if loading}
    <div class="loading">Загрузка...</div>
  {:else if brand}
    <div class="brand-content">
      <!-- Info Section -->
      <section class="info-section">
        <div class="section-header-row">
          <h2>Информация</h2>
          {#if !editing}
            <button class="edit-btn" onclick={startEdit}>Редактировать</button>
          {/if}
        </div>

        {#if editing}
          <div class="edit-form">
            <label class="field">
              <span>Название <span class="required">*</span></span>
              <input type="text" bind:value={editName} maxlength="100" />
            </label>
            <label class="field">
              <span>Индустрия</span>
              <input type="text" bind:value={editIndustry} />
            </label>
            <label class="field">
              <span>Описание</span>
              <textarea bind:value={editDescription} rows="3"></textarea>
            </label>
            <div class="edit-actions">
              <button class="btn-secondary" onclick={cancelEdit}>Отмена</button>
              <button class="btn-primary" onclick={saveEdit} disabled={saving || !editName.trim()}>
                {saving ? 'Сохранение...' : 'Сохранить'}
              </button>
            </div>
          </div>
        {:else}
          <div class="info-grid">
            <div class="info-item">
              <span class="label">ID</span>
              <span class="value">{brand.brand_id}</span>
            </div>
            {#if brand.industry}
              <div class="info-item">
                <span class="label">Индустрия</span>
                <span class="value">{brand.industry}</span>
              </div>
            {/if}
            {#if brand.description}
              <div class="info-item full">
                <span class="label">Описание</span>
                <span class="value">{brand.description}</span>
              </div>
            {/if}
          </div>
        {/if}
      </section>

      <!-- Stats Section -->
      <section class="stats-section">
        <h2>Статистика</h2>
        <div class="stats-grid">
          <div class="stat-card">
            <span class="stat-value">{stats?.documents ?? 0}</span>
            <span class="stat-label">Документов</span>
          </div>
          <div class="stat-card">
            <span class="stat-value">{stats?.raw_data_files ?? 0}</span>
            <span class="stat-label">Файлов истории</span>
          </div>
          {#if $isCreativeHub}
            <div class="stat-card">
              <span class="stat-value">{stats?.vectors ?? 0}</span>
              <span class="stat-label">Векторов</span>
            </div>
            <div class="stat-card">
              <span class="stat-value rag-status" class:rag-up={stats?.rag_available}>
                {stats?.rag_available ? 'Online' : 'Offline'}
              </span>
              <span class="stat-label">RAG</span>
            </div>
          {/if}
        </div>
      </section>

      <!-- Docs Section -->
      <section class="docs-section" class:drag-over={dragOver} bind:this={docsZone}>
        <div class="docs-header">
          <h2>Документы</h2>
          <div class="docs-actions">
            {#if uploading}
              <span class="uploading-badge">Загрузка...</span>
            {/if}
            <button class="upload-btn" onclick={uploadDocument} disabled={uploading}>
              + Загрузить
            </button>
          </div>
        </div>

        {#if docs.length === 0}
          <div class="docs-empty">
            <p>Перетащите файлы сюда или нажмите «Загрузить»</p>
          </div>
        {:else}
          <div class="doc-list">
            {#each docs as doc (doc.filename)}
              <div class="doc-item">
                <div class="doc-info">
                  <span class="doc-name">{doc.filename}</span>
                  <span class="doc-meta">{formatFileSize(doc.size)}</span>
                </div>
                <button class="doc-delete" onclick={() => deleteDoc(doc.filename)} title="Удалить">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
              </div>
            {/each}
          </div>
        {/if}
      </section>
    </div>
  {/if}
</div>

<!-- Delete Confirmation -->
{#if showDeleteConfirm}
  <div class="overlay" role="dialog">
    <div class="confirm-card">
      <h2>Удалить бренд?</h2>
      <p>Бренд "{brand?.name}" будет удалён вместе со всеми документами и историей. Это действие необратимо.</p>
      <div class="confirm-actions">
        <button class="btn-secondary" onclick={() => showDeleteConfirm = false}>Отмена</button>
        <button class="btn-danger" onclick={confirmDelete} disabled={deleting}>
          {deleting ? 'Удаление...' : 'Удалить'}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .brand-page { padding: 24px; max-width: 800px; margin: 0 auto; height: 100%; overflow-y: auto; }

  .brand-header { display: flex; align-items: center; gap: 12px; margin-bottom: 32px; }
  .brand-header h1 { flex: 1; font-size: 1.5rem; font-weight: var(--font-weight-heading); color: var(--text-primary, #fff); margin: 0; }
  .back-btn { background: none; border: 1px solid var(--border); color: var(--text-secondary, #aaa); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
  .back-btn:hover { background: var(--hover-bg); color: var(--text-primary, #fff); }
  .activate-btn { background: linear-gradient(135deg, var(--brand-gradient-start), var(--brand-gradient-end)); color: var(--text-on-accent, #fff); border: none; padding: 6px 16px; border-radius: var(--radius-btn); cursor: pointer; font-weight: 500; font-size: 0.85rem; }
  .active-badge { background: var(--brand-gradient-start); color: var(--text-on-accent, #fff); font-size: 0.75rem; padding: 4px 10px; border-radius: var(--radius-chip); font-weight: 500; }
  .delete-btn { background: none; border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent); color: var(--danger); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; }
  .delete-btn:hover { background: color-mix(in srgb, var(--danger) 10%, transparent); }

  .loading { text-align: center; padding: 48px; color: var(--text-secondary, #aaa); }
  .brand-content { display: flex; flex-direction: column; gap: 24px; }

  /* Sections */
  section h2 { font-size: 1rem; font-weight: var(--font-weight-heading); color: var(--text-primary, #fff); margin: 0; }
  .info-section, .stats-section, .docs-section { background: var(--hover-bg); border: 1px solid var(--hover-bg); border-radius: var(--radius-card); padding: 20px; }
  .section-header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }

  /* Info */
  .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .info-item { display: flex; flex-direction: column; gap: 4px; }
  .info-item.full { grid-column: 1 / -1; }
  .label { font-size: 0.75rem; color: var(--text-tertiary, #888); text-transform: uppercase; letter-spacing: 0.05em; }
  .value { font-size: 0.9rem; color: var(--text-primary, #fff); }

  /* Edit */
  .edit-btn { background: none; border: 1px solid var(--border); color: var(--text-secondary, #aaa); padding: 4px 12px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; }
  .edit-btn:hover { background: var(--hover-bg); color: var(--text-primary, #fff); }
  .edit-form { display: flex; flex-direction: column; gap: 12px; }
  .field { display: flex; flex-direction: column; gap: 4px; }
  .field span { font-size: 0.85rem; color: var(--text-secondary, #aaa); }
  .required { color: var(--danger); }
  .field input, .field textarea { background: var(--hover-bg); border: 1px solid var(--border); border-radius: var(--radius-input); padding: 8px 12px; color: var(--text-primary, #fff); font-size: 0.9rem; font-family: inherit; outline: none; }
  .field input:focus, .field textarea:focus { border-color: var(--brand-gradient-start); }
  .edit-actions { display: flex; justify-content: flex-end; gap: 8px; }
  .btn-primary { background: linear-gradient(135deg, var(--brand-gradient-start), var(--brand-gradient-end)); color: var(--text-on-accent, #fff); border: none; padding: 8px 20px; border-radius: var(--radius-btn); cursor: pointer; font-weight: 500; }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-secondary { background: var(--hover-bg); color: var(--text-primary, #fff); border: 1px solid var(--border); padding: 8px 20px; border-radius: var(--radius-btn); cursor: pointer; }

  /* Stats */
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; }
  .stat-card { background: var(--hover-bg); border: 1px solid var(--hover-bg); border-radius: 8px; padding: 16px; text-align: center; }
  .stat-value { display: block; font-size: 1.5rem; font-weight: 700; color: var(--text-primary, #fff); margin-bottom: 4px; }
  .stat-label { font-size: 0.75rem; color: var(--text-tertiary, #888); }
  .rag-status { font-size: 0.9rem !important; }
  .rag-up { color: var(--success); }

  /* Docs */
  .docs-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .docs-header h2 { margin: 0; }
  .docs-actions { display: flex; align-items: center; gap: 8px; }
  .uploading-badge { font-size: 0.75rem; color: var(--accent-text-light); animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  .upload-btn { background: color-mix(in srgb, var(--brand-gradient-start) 15%, transparent); color: var(--accent-text-light); border: 1px solid color-mix(in srgb, var(--brand-gradient-start) 30%, transparent); padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
  .upload-btn:hover { background: color-mix(in srgb, var(--brand-gradient-start) 25%, transparent); }
  .upload-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .docs-empty { text-align: center; padding: 32px; color: var(--text-secondary, #aaa); font-size: 0.9rem; border: 2px dashed var(--border); border-radius: 8px; }

  .doc-list { max-height: 320px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
  .doc-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--hover-bg); border-radius: 6px; }
  .doc-item:hover { background: var(--hover-bg); }
  .doc-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .doc-name { font-size: 0.85rem; color: var(--text-primary, #fff); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .doc-meta { font-size: 0.7rem; color: var(--text-tertiary, #888); }
  .doc-delete { background: none; border: none; color: var(--text-tertiary, #888); cursor: pointer; padding: 4px; border-radius: 4px; opacity: 0; transition: opacity 0.15s; }
  .doc-item:hover .doc-delete { opacity: 1; }
  .doc-delete:hover { color: var(--danger); background: color-mix(in srgb, var(--danger) 10%, transparent); }

  /* Drag-drop */
  .docs-section.drag-over { border-color: var(--brand-gradient-start); box-shadow: 0 0 0 2px color-mix(in srgb, var(--brand-gradient-start) 30%, transparent), inset 0 0 20px color-mix(in srgb, var(--brand-gradient-start) 5%, transparent); }

  /* Delete confirmation */
  .overlay { position: fixed; inset: 0; background: var(--overlay-bg); display: flex; align-items: center; justify-content: center; z-index: 1000; backdrop-filter: var(--blur-quiet); }
  .confirm-card { background: var(--bg-surface, #1a1a2e); border: 1px solid var(--border); border-radius: 16px; padding: 32px; width: 90%; max-width: 420px; }
  .confirm-card h2 { margin: 0 0 12px; font-size: 1.2rem; color: var(--text-primary, #fff); }
  .confirm-card p { color: var(--text-secondary, #aaa); font-size: 0.9rem; line-height: 1.5; margin: 0 0 24px; }
  .confirm-actions { display: flex; justify-content: flex-end; gap: 8px; }
  .btn-danger { background: var(--danger); color: var(--text-on-accent, #fff); border: none; padding: 8px 20px; border-radius: var(--radius-btn); cursor: pointer; font-weight: 500; }
  .btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
