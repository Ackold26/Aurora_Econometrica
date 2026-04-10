<script>
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow';
  import { open as openDialog } from '@tauri-apps/plugin-dialog';
  import { activeCabinet, isLoading, panelWidth, inboxFiles as inboxFilesStore } from '$lib/store.js';

  /** @type {string[]} */
  let inboxFiles = $state([]);
  /** @type {string[]} */
  let exportFiles = $state([]);

  /** Technical file patterns hidden from exports list */
  const HIDDEN_EXPORT_PATTERNS = [
    /^scripts\//i,           // Python scripts folder
    /-params-.*\.json$/i,    // Model parameter files
    /-partial\.md$/i,        // Partial/failed responses
  ];

  /** @type {string[]} */
  let visibleExports = $derived(exportFiles.filter(f => !HIDDEN_EXPORT_PATTERNS.some(p => p.test(f))));
  let dragOver = $state(false);
  let urlInput = $state('');
  let openError = $state('');
  /** @type {{filename: string, size: number, content: string|null}|null} */
  let previewData = $state(null);
  /** @type {ReturnType<typeof setInterval>|undefined} */
  let refreshInterval;
  /** @type {HTMLDivElement|undefined} */
  let inboxZone;

  /** @param {MouseEvent} e */
  function startResize(e) {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = $panelWidth;
    /** @param {MouseEvent} e */
    function onMouseMove(e) {
      panelWidth.set(Math.min(500, Math.max(220, startWidth + (startX - e.clientX))));
    }
    function onMouseUp() {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }

  /** @param {string} filename */
  function isUrlFile(filename) {
    return filename.toLowerCase().endsWith('.url');
  }

  /** @param {string} str */
  function isValidUrl(str) {
    try {
        const u = new URL(str.trim());
        return u.protocol === 'http:' || u.protocol === 'https:';
    } catch { return false; }
  }

  async function refreshFiles() {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;

    try {
      inboxFiles = await invoke('list_inbox_files', { cabinetId });
      inboxFilesStore.set(inboxFiles);
      exportFiles = await invoke('list_export_files', { cabinetId });
    } catch {
      // ignore refresh errors
    }
  }

  /** @param {string} url */
  async function addUrl(url) {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId || !isValidUrl(url)) return;

    try {
      await invoke('add_url_to_inbox', { cabinetId, url: url.trim() });
      await refreshFiles();
    } catch (e) {
      console.error('Add URL failed:', e);
    }
  }

  async function handleUrlSubmit() {
    if (!urlInput.trim()) return;
    await addUrl(urlInput);
    urlInput = '';
  }

  /** @param {KeyboardEvent} e */
  function handleUrlKeydown(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleUrlSubmit();
    }
  }

  /** @param {ClipboardEvent} e */
  async function handlePaste(e) {
    const text = e.clipboardData?.getData('text/plain');
    if (text && isValidUrl(text)) {
      e.preventDefault();
      await addUrl(text);
    }
  }

  async function openHelp() {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      await invoke('open_help', { cabinetId });
    } catch (e) {
      console.error('Failed to open help:', e);
    }
  }

  async function pickFiles() {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      const selected = await openDialog({ multiple: true, directory: false });
      if (!selected) return;
      const paths = Array.isArray(selected) ? selected : [selected];
      await invoke('copy_to_inbox', { cabinetId, filePaths: paths });
      await refreshFiles();
    } catch (e) {
      console.error('Pick files failed:', e);
    }
  }

  /** @param {string} filename */
  async function showInboxInFolder(filename) {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      await invoke('show_inbox_in_folder', { cabinetId, filename });
    } catch (e) {
      console.error('Show inbox in folder failed:', e);
    }
  }

  /** @param {string} filename */
  async function deleteInboxFile(filename) {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;

    try {
      await invoke('delete_inbox_file', { cabinetId, filename });
      await refreshFiles();
    } catch (e) {
      console.error('Delete failed:', e);
    }
  }

  /** @param {string} filename */
  async function openExportFile(filename) {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;

    openError = '';
    try {
      await invoke('open_export_file', { cabinetId, filename });
    } catch (e) {
      console.error('Failed to open file:', e);
      openError = typeof e === 'string' ? e : `Не удалось открыть: ${filename}`;
      setTimeout(() => { openError = ''; }, 4000);
    }
  }

  /** @param {string} filename */
  async function showExportInFolder(filename) {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      await invoke('show_export_in_folder', { cabinetId, filename });
    } catch (e) {
      console.error('Show in folder failed:', e);
    }
  }

  /** @param {string} filename */
  async function deleteExportFile(filename) {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      await invoke('delete_export_file', { cabinetId, filename });
      await refreshFiles();
    } catch (e) {
      console.error('Delete export failed:', e);
    }
  }

  /** @param {string} filename */
  async function previewFile(filename) {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      const result = /** @type {[number, string|null]} */ (await invoke('preview_export_file', { cabinetId, filename }));
      previewData = { filename, size: result[0], content: result[1] };
    } catch (e) {
      console.error('Preview failed:', e);
    }
  }

  async function clearAllInbox() {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId || inboxFiles.length === 0) return;
    for (const file of [...inboxFiles]) {
      try { await invoke('delete_inbox_file', { cabinetId, filename: file }); } catch { /* skip */ }
    }
    await refreshFiles();
  }

  async function clearAllExports() {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId || exportFiles.length === 0) return;
    for (const file of [...exportFiles]) {
      try { await invoke('delete_export_file', { cabinetId, filename: file }); } catch { /* skip */ }
    }
    await refreshFiles();
  }

  /** @param {number} bytes */
  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' Б';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' КБ';
    return (bytes / (1024 * 1024)).toFixed(1) + ' МБ';
  }

  /** @param {HTMLElement|undefined} el @param {number} x @param {number} y */
  function isInsideElement(el, x, y) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }

  $effect(() => {
    let disposed = false;
    refreshFiles();
    refreshInterval = setInterval(refreshFiles, 5000);

    /** @type {(() => void)|undefined} */
    let unlistenExports;
    const cabinetId = $activeCabinet?.id;
    if (cabinetId) {
      listen(`exports-updated-${cabinetId}`, () => refreshFiles())
        .then(fn => { if (disposed) fn(); else unlistenExports = fn; });
    }

    const appWindow = getCurrentWebviewWindow();
    /** @type {(() => void)|undefined} */
    let unlisten;

    appWindow.onDragDropEvent((event) => {
      if (event.payload.type === 'over') {
        const { x, y } = event.payload.position;
        dragOver = isInsideElement(inboxZone, x, y);
      } else if (event.payload.type === 'drop') {
        const { x, y } = event.payload.position;
        if (isInsideElement(inboxZone, x, y)) {
          const cabinetId = $activeCabinet?.id;
          if (cabinetId && event.payload.paths?.length) {
            // Check if any paths look like URLs
            const urls = event.payload.paths.filter(p => isValidUrl(p));
            const files = event.payload.paths.filter(p => !isValidUrl(p));

            if (files.length) {
              invoke('copy_to_inbox', { cabinetId, filePaths: files })
                .then(() => refreshFiles())
                .catch((e) => console.error('Copy failed:', e));
            }
            for (const url of urls) {
              addUrl(url);
            }
          }
        }
        dragOver = false;
      } else if (event.payload.type === 'leave') {
        dragOver = false;
      }
    }).then((fn) => { if (disposed) fn(); else unlisten = fn; });

    return () => {
      disposed = true;
      clearInterval(refreshInterval);
      if (unlisten) unlisten();
      if (unlistenExports) unlistenExports();
    };
  });
</script>

<div class="file-panel" style="width: {$panelWidth}px">
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="resize-handle" onmousedown={startResize}></div>
  <div class="file-section">
    <h3 class="file-section-title">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
      Входящие ({inboxFiles.length})
      <button class="section-clear-btn" onclick={clearAllInbox} disabled={inboxFiles.length === 0} title="Очистить входящие">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
        </svg>
      </button>
    </h3>
    <div class="file-list inbox-zone" class:drag-over={dragOver} bind:this={inboxZone} onpaste={handlePaste}>
      {#if inboxFiles.length === 0}
        <p class="file-empty">
          {#if dragOver}
            Отпустите для загрузки
          {:else}
            Перетащите файлы сюда
          {/if}
        </p>
      {:else}
        {#each inboxFiles as file}
          <div class="file-item">
            <span class="file-icon">
              {#if isUrlFile(file)}
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
                </svg>
              {:else}
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                </svg>
              {/if}
            </span>
            <span class="file-name" title={file}>{file}</span>
            {#if !$isLoading}
              <button class="export-action-btn" onclick={() => showInboxInFolder(file)} title="Показать в папке">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
                </svg>
              </button>
              <button class="delete-btn" onclick={() => deleteInboxFile(file)} title="Удалить">✕</button>
            {/if}
          </div>
        {/each}
      {/if}
    </div>
    <button class="pick-files-btn" onclick={pickFiles}>+ Выбрать файл</button>
    <div class="url-input-row">
      <input
        type="text"
        class="url-input"
        placeholder="Вставьте ссылку..."
        bind:value={urlInput}
        onkeydown={handleUrlKeydown}
        onpaste={handlePaste}
      />
      <button class="url-add-btn" onclick={handleUrlSubmit} disabled={!urlInput.trim() || !isValidUrl(urlInput)} title="Добавить ссылку">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
      </button>
    </div>
  </div>

  <div class="file-section">
    <h3 class="file-section-title">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
        <polyline points="17 8 12 3 7 8"/>
        <line x1="12" y1="3" x2="12" y2="15"/>
      </svg>
      Результаты ({visibleExports.length})
      <button class="section-clear-btn" onclick={clearAllExports} disabled={visibleExports.length === 0} title="Очистить результаты">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
        </svg>
      </button>
    </h3>
    <div class="file-list">
      {#if visibleExports.length === 0}
        <p class="file-empty">Результаты появятся здесь</p>
      {:else}
        {#each visibleExports as file}
          <div class="file-item export-item" title={file}>
            <span class="file-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: var(--success)">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </span>
            <span class="file-name export-name" role="button" tabindex="0" onclick={() => previewFile(file)} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') previewFile(file) }}>{file}</span>
            <button class="export-action-btn" onclick={() => showExportInFolder(file)} title="Показать в папке">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
              </svg>
            </button>
            <button class="export-action-btn export-delete-btn" onclick={() => deleteExportFile(file)} title="Удалить">✕</button>
          </div>
        {/each}
      {/if}
    </div>
  </div>

  {#if previewData}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="preview-overlay" onclick={() => previewData = null} onkeydown={(e) => { if (e.key === 'Escape') previewData = null }}>
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="preview-popup" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
        <div class="preview-header">
          <span class="preview-filename" title={previewData.filename}>{previewData.filename}</span>
          <span class="preview-size">{formatFileSize(previewData.size)}</span>
          <button class="preview-close" onclick={() => previewData = null}>✕</button>
        </div>
        {#if previewData.content}
          <pre class="preview-content">{previewData.content}</pre>
        {:else}
          <p class="preview-binary">Предпросмотр недоступен для этого формата</p>
        {/if}
        <div class="preview-actions">
          <button class="preview-btn" onclick={() => { if (previewData) openExportFile(previewData.filename); previewData = null; }}>Открыть</button>
          <button class="preview-btn preview-btn-secondary" onclick={() => { if (previewData) showExportInFolder(previewData.filename); previewData = null; }}>В папке</button>
        </div>
      </div>
    </div>
  {/if}

  {#if openError}
    <div class="open-error">{openError}</div>
  {/if}

  <div class="bottom-actions">
    <button class="action-btn help-btn" onclick={openHelp} title="Открыть справку">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="12" cy="12" r="10"/>
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
        <line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      Инструкция
    </button>
    <button class="action-btn refresh-btn" onclick={refreshFiles} title="Обновить файлы">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="23 4 23 10 17 10"/>
        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
      </svg>
    </button>
  </div>
</div>

<style>
  .file-panel {
    position: relative;
    flex-shrink: 0;
    border-left: 1px solid var(--border);
    background: var(--panel-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    display: flex;
    flex-direction: column;
    padding: 14px;
    gap: 14px;
    overflow-y: auto;
  }

  .resize-handle {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    cursor: col-resize;
    background: transparent;
    z-index: 10;
    transition: background var(--transition-fast);
  }

  .resize-handle:hover {
    background: rgba(46, 91, 255, 0.4);
  }

  .file-section-title {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
  }

  .section-clear-btn {
    margin-left: auto;
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    color: var(--text-muted);
    border-radius: 4px;
    cursor: pointer;
    opacity: 0.5;
    transition: all 0.15s ease;
    padding: 0;
  }

  .section-clear-btn:hover:not(:disabled) {
    opacity: 1;
    color: #EF4444;
    background: rgba(239, 68, 68, 0.1);
  }

  .section-clear-btn:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .file-list {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .inbox-zone {
    min-height: 56px;
    border: 1.5px dashed var(--border);
    border-radius: 8px;
    padding: 4px;
    transition: all var(--transition);
  }

  .inbox-zone.drag-over {
    border-color: var(--accent-primary);
    background: rgba(46, 91, 255, 0.07);
    box-shadow: 0 0 12px rgba(46, 91, 255, 0.15) inset;
  }

  .file-empty {
    font-size: 12px;
    color: var(--text-muted);
    padding: 8px;
    text-align: center;
    font-style: italic;
  }

  .file-item {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 5px 7px;
    border-radius: 6px;
    transition: background var(--transition-fast);
  }

  .file-item:hover {
    background: var(--hover-bg);
  }


  .file-icon {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    color: var(--text-muted);
  }

  .file-name {
    font-size: 12.5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    color: var(--text-secondary);
  }

  .delete-btn {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 11px;
    border-radius: 4px;
    cursor: pointer;
    opacity: 0;
    transition: all 0.15s ease;
  }

  .file-item:hover .delete-btn {
    opacity: 1;
  }

  .delete-btn:hover {
    background: rgba(239, 68, 68, 0.15);
    color: #EF4444;
  }

  .pick-files-btn {
    width: 100%;
    padding: 6px;
    background: var(--hover-bg);
    color: var(--text-muted);
    border: 1px dashed var(--border);
    border-radius: 6px;
    font-size: 11.5px;
    cursor: pointer;
    transition: all var(--transition-fast);
    margin-top: 4px;
  }

  .pick-files-btn:hover {
    background: rgba(46, 91, 255, 0.08);
    color: var(--text-secondary);
    border-color: rgba(46, 91, 255, 0.3);
  }

  .url-input-row {
    display: flex;
    gap: 4px;
    margin-top: 6px;
  }

  .url-input {
    flex: 1;
    padding: 6px 9px;
    background: var(--input-bg);
    color: var(--text-primary);
    border: 1px solid var(--input-border);
    border-radius: 6px;
    font-size: 12px;
    min-width: 0;
    transition: border-color var(--transition-fast);
  }

  .url-input:focus {
    border-color: rgba(46, 91, 255, 0.35);
  }

  .url-input::placeholder {
    color: var(--text-muted);
  }

  .url-add-btn {
    flex-shrink: 0;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    transition: all var(--transition-fast);
    color: var(--text-muted);
  }

  .url-add-btn:hover:not(:disabled) {
    background: rgba(46, 91, 255, 0.1);
    border-color: rgba(46, 91, 255, 0.3);
    color: var(--text-primary);
  }

  .url-add-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .bottom-actions {
    margin-top: auto;
    display: flex;
    gap: 6px;
  }

  .action-btn {
    padding: 7px 10px;
    background: var(--hover-bg);
    color: var(--text-muted);
    border-radius: var(--radius-sm);
    font-size: 12px;
    transition: all var(--transition-fast);
    border: 1px solid var(--border);
    cursor: pointer;
  }

  .action-btn:hover {
    background: var(--hover-bg);
    color: var(--text-secondary);
    border-color: rgba(255, 255, 255, 0.08);
  }

  .help-btn {
    flex: 1;
  }

  .refresh-btn {
    flex-shrink: 0;
  }

  .export-item {
    cursor: default;
  }

  .export-name {
    cursor: pointer;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12.5px;
    color: var(--text-secondary);
    transition: color var(--transition-fast);
  }

  .export-name:hover {
    color: #8EB4FF;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .export-action-btn {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 11px;
    border-radius: 4px;
    cursor: pointer;
    opacity: 0;
    transition: all 0.15s ease;
    padding: 0;
  }

  .export-item:hover .export-action-btn,
  .file-item:hover .export-action-btn {
    opacity: 1;
  }

  .export-action-btn:hover {
    background: var(--hover-bg);
    color: var(--text-primary);
  }

  .export-delete-btn:hover {
    background: rgba(239, 68, 68, 0.15);
    color: #EF4444;
  }

  /* ── Preview Popup ── */
  .preview-overlay {
    position: fixed;
    inset: 0;
    z-index: 100;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    animation: fadeIn 0.15s ease;
  }

  .preview-popup {
    background: var(--bg-secondary, #16161e);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    width: 90%;
    max-width: 440px;
    max-height: 70vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
    animation: slideUp 0.2s ease;
  }

  .preview-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 14px;
    border-bottom: 1px solid var(--hover-bg);
  }

  .preview-filename {
    flex: 1;
    font-size: 13px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .preview-size {
    font-size: 11px;
    color: var(--text-muted);
    flex-shrink: 0;
  }

  .preview-close {
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    color: var(--text-muted);
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    transition: all 0.15s ease;
  }

  .preview-close:hover {
    color: var(--text-primary);
    background: var(--hover-bg);
  }

  .preview-content {
    flex: 1;
    overflow: auto;
    padding: 12px 14px;
    font-size: 12px;
    font-family: var(--font-mono);
    line-height: 1.5;
    color: var(--text-secondary);
    white-space: pre-wrap;
    word-break: break-word;
    margin: 0;
    background: var(--code-bg);
  }

  .preview-binary {
    padding: 24px 14px;
    text-align: center;
    color: var(--text-muted);
    font-size: 13px;
    font-style: italic;
  }

  .preview-actions {
    display: flex;
    gap: 8px;
    padding: 12px 14px;
    border-top: 1px solid var(--hover-bg);
  }

  .preview-btn {
    flex: 1;
    padding: 8px 14px;
    background: linear-gradient(135deg, var(--accent-primary, #2E5BFF) 0%, #4A76FF 100%);
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .preview-btn:hover {
    filter: brightness(1.1);
  }

  .preview-btn-secondary {
    background: var(--hover-bg);
    color: var(--text-secondary);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .preview-btn-secondary:hover {
    background: rgba(255, 255, 255, 0.1);
    color: var(--text-primary);
    filter: none;
  }

  @keyframes slideUp {
    from { transform: translateY(12px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
  }

  .open-error {
    font-size: 12px;
    color: #EF4444;
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.2);
    border-radius: 6px;
    padding: 7px 10px;
    animation: fadeIn 0.2s ease;
  }
</style>
