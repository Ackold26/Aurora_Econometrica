<script>
  /**
   * ImportStep — Step 0 of the pipeline.
   * Drag-drop zone + Tauri dialog for xlsx/csv import.
   * Shows DataTable preview of first 20 rows after import.
   * Calls completeStep(0) on success, resetDownstream(0) on re-import.
   *
   * @component ImportStep
   */
  import { invoke } from '@tauri-apps/api/core';
  import { open } from '@tauri-apps/plugin-dialog';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { onMount } from 'svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import { importData, completeStep, resetDownstream, pipelineStepMeta, pipelineCurrentStep } from '$lib/project-state.js';
  import { get } from 'svelte/store';

  // ── State ──────────────────────────────────────────
  let filePath = $state('');
  let fileName = $state('');
  let loading = $state(false);
  let errorMsg = $state('');
  let isDragOver = $state(false);

  /** @type {string[]} */
  let previewHeaders = $state([]);
  /** @type {any[][]} */
  let previewRows = $state([]);
  /** @type {{rows: number, cols: number} | null} */
  let shape = $state(null);
  let sizeKb = $state(0);

  // Restore from memory store on mount (A4: data is memory-only)
  const stored = get(importData);
  if (stored.file) {
    filePath = stored.file;
    fileName = stored.file.split(/[\\/]/).pop() || '';
    if (stored.rows && stored.rows.length) {
      previewRows = stored.rows;
    }
  }

  // ── Tauri drag-drop listener ───────────────────────
  /** @type {(() => void) | null} */
  let unlistenDrop = null;

  onMount(() => {
    const win = getCurrentWindow();

    win.onDragDropEvent((event) => {
      const payload = event.payload;
      if (payload.type === 'over') {
        isDragOver = true;
      } else if (payload.type === 'leave') {
        isDragOver = false;
      } else if (payload.type === 'drop') {
        isDragOver = false;
        const paths = /** @type {any} */ (payload).paths ?? [];
        if (paths.length > 0) {
          const ext = paths[0].split('.').pop()?.toLowerCase();
          if (ext === 'xlsx' || ext === 'xls' || ext === 'csv') {
            loadFile(paths[0]);
          } else {
            errorMsg = 'Поддерживаются файлы .xlsx, .xls, .csv';
          }
        }
      }
    }).then(fn => { unlistenDrop = fn; });

    return () => { unlistenDrop?.(); };
  });

  // ── HTML5 drag visual feedback ─────────────────────
  /** @param {DragEvent} e */
  function onDragenter(e) {
    e.preventDefault();
    isDragOver = true;
  }

  /** @param {DragEvent} e */
  function onDragover(e) {
    e.preventDefault();
  }

  /** @param {DragEvent} e */
  function onDragleave(e) {
    e.preventDefault();
    isDragOver = false;
  }

  // ── File picker dialog ─────────────────────────────
  async function pickFile() {
    const selected = await open({
      multiple: false,
      filters: [{ name: 'Data files (xlsx, csv)', extensions: ['xlsx', 'xls', 'csv'] }],
    });
    if (typeof selected === 'string' && selected) {
      await loadFile(selected);
    }
  }

  // ── Core load logic ────────────────────────────────
  /** @param {string} path */
  async function loadFile(path) {
    const isReimport = !!filePath && filePath !== path;
    if (isReimport) {
      // Warn if model was trained (step 2 complete) — user loses training results
      const meta = get(pipelineStepMeta);
      if (meta[2]?.status === 'complete') {
        const ok = confirm('Результаты обучения модели будут сброшены. Продолжить?');
        if (!ok) return;
      }
      resetDownstream(0);
    }

    loading = true;
    errorMsg = '';
    previewRows = [];
    previewHeaders = [];
    shape = null;

    try {
      /** @type {any} */
      const result = await invoke('econ_data_preview', {
        filePath: path,
        nRows: 20,
      });

      if (result.status === 'error') {
        errorMsg = result.message ?? 'Ошибка загрузки файла';
        return;
      }

      filePath = path;
      fileName = result.file_name ?? path.split(/[\\/]/).pop() ?? '';
      previewHeaders = result.headers ?? [];
      previewRows = result.rows ?? [];
      sizeKb = result.size_kb ?? 0;
      shape = { rows: result.shape?.[0] ?? 0, cols: result.shape?.[1] ?? 0 };

      // A4: persist only file path + preview rows to memory store (not localStorage)
      const currentImport = get(importData);
      const updated = { ...currentImport, file: path, rows: result.rows, columns: result.dtypes };
      importData.set(updated);

      completeStep(0);
    } catch (e) {
      errorMsg = `Ошибка: ${e}`;
    } finally {
      loading = false;
    }
  }
</script>

<div class="import-step">

  <!-- Drop zone -->
  <div
    class="drop-zone"
    class:drag-over={isDragOver}
    class:has-file={!!filePath && !loading}
    role="button"
    tabindex="0"
    aria-label="Зона перетаскивания файла"
    ondragenter={onDragenter}
    ondragover={onDragover}
    ondragleave={onDragleave}
    onclick={pickFile}
    onkeydown={(e) => e.key === 'Enter' && pickFile()}
  >
    {#if loading}
      <div class="drop-content">
        <div class="spinner"></div>
        <p class="drop-label">Загрузка…</p>
      </div>
    {:else if filePath}
      <div class="drop-content file-ready">
        <div class="file-icon">📊</div>
        <p class="file-name">{fileName}</p>
        {#if shape}
          <p class="file-meta">{shape.rows} строк × {shape.cols} столбцов · {sizeKb} KB</p>
        {/if}
        <p class="change-hint">Нажмите или перетащите другой файл, чтобы заменить</p>
      </div>
    {:else}
      <div class="drop-content">
        <div class="drop-icon">📂</div>
        <p class="drop-label">Перетащите файл сюда</p>
        <p class="drop-hint">или нажмите для выбора</p>
        <p class="drop-formats">.xlsx · .xls · .csv</p>
      </div>
    {/if}
  </div>

  <!-- Error message -->
  {#if errorMsg}
    <div class="error-banner">
      <span class="error-icon">⚠️</span>
      {errorMsg}
    </div>
  {/if}

  <!-- DataTable preview -->
  {#if previewRows.length > 0 && !loading}
    <div class="preview-section">
      <div class="preview-header">
        <h4>Предпросмотр данных</h4>
        <span class="preview-badge">первые 20 строк</span>
      </div>
      <DataTable
        headers={previewHeaders}
        rows={previewRows}
        emptyMessage="Нет данных для отображения"
      />

      <button
        class="quick-btn"
        onclick={() => pipelineCurrentStep.set(1)}
      >
        Далее: Валидация →
      </button>
    </div>
  {/if}

</div>

<style>
  .import-step {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 24px;
    height: 100%;
    box-sizing: border-box;
    overflow-y: auto;
  }

  /* ── Drop zone ── */
  .drop-zone {
    min-height: 180px;
    border: 2px dashed rgba(59, 130, 246, 0.3);
    border-radius: 16px;
    background: rgba(15, 23, 42, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s, transform 0.15s;
    flex-shrink: 0;
  }

  .drop-zone:hover,
  .drop-zone:focus-visible {
    border-color: rgba(59, 130, 246, 0.7);
    background: rgba(59, 130, 246, 0.06);
    outline: none;
  }

  .drop-zone.drag-over {
    border-color: #3b82f6;
    background: rgba(59, 130, 246, 0.12);
    transform: scale(1.01);
  }

  .drop-zone.has-file {
    border-style: solid;
    border-color: rgba(34, 197, 94, 0.4);
    background: rgba(34, 197, 94, 0.04);
    min-height: 120px;
  }

  .drop-zone.has-file:hover {
    border-color: rgba(59, 130, 246, 0.6);
    background: rgba(59, 130, 246, 0.06);
  }

  /* ── Drop content ── */
  .drop-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 32px 24px;
    text-align: center;
  }

  .drop-icon {
    font-size: 44px;
    line-height: 1;
    filter: grayscale(0.3);
  }

  .drop-label {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    margin: 0;
  }

  .drop-hint {
    font-size: 13px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }

  .drop-formats {
    font-size: 11px;
    color: rgba(148, 163, 184, 0.5);
    margin: 4px 0 0;
    letter-spacing: 0.05em;
  }

  /* ── File ready state ── */
  .file-ready {
    gap: 6px;
    padding: 24px;
  }

  .file-icon {
    font-size: 36px;
    line-height: 1;
  }

  .file-name {
    font-size: 15px;
    font-weight: 600;
    color: #22c55e;
    margin: 0;
    word-break: break-all;
    max-width: 400px;
  }

  .file-meta {
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }

  .change-hint {
    font-size: 11px;
    color: rgba(148, 163, 184, 0.45);
    margin: 6px 0 0;
    font-style: italic;
  }

  /* ── Spinner ── */
  .spinner {
    width: 32px;
    height: 32px;
    border: 3px solid rgba(59, 130, 246, 0.2);
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ── Error ── */
  .error-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 10px;
    font-size: 13px;
    color: #fca5a5;
    flex-shrink: 0;
  }

  .error-icon {
    flex-shrink: 0;
  }

  /* ── Preview section ── */
  .preview-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
    flex: 1;
  }

  .preview-header {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-shrink: 0;
  }

  .preview-header h4 {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .preview-badge {
    font-size: 10px;
    padding: 2px 8px;
    background: rgba(59, 130, 246, 0.12);
    border: 1px solid rgba(59, 130, 246, 0.2);
    border-radius: 20px;
    color: #93c5fd;
    letter-spacing: 0.04em;
  }

  .quick-btn {
    align-self: flex-end;
    margin-top: 8px;
    padding: 10px 24px;
    background: var(--accent-primary, #3b82f6);
    border: none; border-radius: 8px;
    color: white; font-size: 13px; font-weight: 600;
    cursor: pointer; transition: opacity 0.15s;
  }
  .quick-btn:hover { opacity: 0.85; }
</style>
