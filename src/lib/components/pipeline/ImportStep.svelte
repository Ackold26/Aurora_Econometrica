<script>
  /**
   * ImportStep - Step 0 of the pipeline.
   * Drag-drop zone + Tauri dialog for xlsx/csv import.
   * Shows DataTable preview of first 20 rows after import.
   * Calls completeStep(0) on success, resetDownstream(0) on re-import.
   *
   * @component ImportStep
   */
  import { invoke } from '@tauri-apps/api/core';
  import { open, save } from '@tauri-apps/plugin-dialog';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { onMount } from 'svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Tooltip from '$lib/components/Tooltip.svelte';
  import { TOOLTIPS } from '$lib/data/tooltip-texts.js';
  import PipelineOnboarding from '$lib/components/pipeline/PipelineOnboarding.svelte';
  import { TOURS } from '$lib/pipeline-tours.js';
  import { shouldShowOnboarding } from '$lib/onboarding-state.js';
  import { importData, completeStep, resetDownstream, pipelineStepMeta, pipelineCurrentStep, activeProjectId, activeProject, resetPipeline, modelEngine } from '$lib/project-state.js';
  import { TriangleAlert, ChartColumn, Target, Check, Package } from 'lucide-svelte';
  import { get } from 'svelte/store';

  // Обучающий тур - запускается на mount, независимо от состояния импорта.
  let showOnboarding = $state(false);
  let onboardingChecked = false;

  // Загрузка ранее сохранённого проекта из .aurora архива. После успешного
  // импорта активируется новый project_id и происходит resetPipeline → система
  // сама подхватит results/models/decompose/optimize через restoreProjectResults.
  let importingArchive = $state(false);
  /** @type {string} */
  let archiveMsg = $state('');

  async function loadSavedProject() {
    if (importingArchive) return;
    importingArchive = true;
    archiveMsg = '';
    try {
      const selected = await open({
        filters: [{ name: 'Aurora Project', extensions: ['aurora', 'zip'] }],
        multiple: false,
        title: 'Выбрать .aurora архив проекта',
      });
      if (!selected || typeof selected !== 'string') {
        importingArchive = false;
        return;
      }
      const result = /** @type {any} */ (await invoke('project_import_archive', {
        archivePath: selected,
      }));
      const newId = result.project_id;
      const info = result.info;

      await invoke('project_activate', { projectId: newId });
      activeProject.set(info);
      activeProjectId.set(newId);
      resetPipeline(newId);  // передаём id → restore result JSONs
      archiveMsg = `✓ Проект «${info.name ?? newId}» загружен. Следующие шаги подхватят результаты автоматически.`;
      setTimeout(() => { archiveMsg = ''; }, 8000);
    } catch (e) {
      archiveMsg = `Ошибка: ${e}`;
      setTimeout(() => { archiveMsg = ''; }, 8000);
    } finally {
      importingArchive = false;
    }
  }

  // ── Скачивание синтетического примера ──────────────
  // Фикс 2026-06-07: `<a download>` не работает в WebView2 (нет браузерного
  // «Сохранить как» → клик = no-op). Заменено на нативный save-dialog + запись
  // через Rust (save_sample_file). Байты берём fetch'ем своего же bundled-asset.
  /** @type {string} */
  let sampleMsg = $state('');
  /** @type {string} */
  let savedSamplePath = $state('');
  let savingSample = $state(false);

  /** @param {string} filename @param {string} label */
  async function downloadSample(filename, label) {
    if (savingSample) return;
    savingSample = true;
    sampleMsg = '';
    savedSamplePath = '';
    try {
      const resp = await fetch(`/sample-data/${filename}`);
      if (!resp.ok) throw new Error('файл не найден в сборке');
      const bytes = Array.from(new Uint8Array(await resp.arrayBuffer()));
      const outputPath = await save({
        defaultPath: filename,
        filters: [{ name: 'Excel', extensions: ['xlsx'] }],
        title: `Сохранить пример: ${label}`,
      });
      if (!outputPath) { savingSample = false; return; } // отмена
      const finalPath = /** @type {string} */ (await invoke('save_sample_file', { outputPath, contents: bytes }));
      savedSamplePath = finalPath;
      sampleMsg = `✓ Сохранено: ${finalPath}`;
    } catch (e) {
      sampleMsg = `Ошибка сохранения: ${e}`;
      savedSamplePath = '';
      setTimeout(() => { sampleMsg = ''; }, 9000);
    } finally {
      savingSample = false;
    }
  }

  async function revealSample() {
    if (!savedSamplePath) return;
    try { await invoke('reveal_path', { path: savedSamplePath }); } catch { /* no-op */ }
  }

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

  /** v1.1.0+: derived helpers для engine selector.
   *  FIX: nRows ТОЛЬКО из shape.rows (real backend response). Раньше fallback
   *  на previewRows.length (20 - preview limit) приводил к ложной OLS-рекомендации
   *  для проектов с ≥30 строк когда shape ещё/уже не загружен.
   *  Если shape null → nRows=0 → recommendOls=false → engine не меняется. */
  const nRows = $derived(/** @type {{rows: number} | null} */ (shape)?.rows ?? 0);
  const recommendOls = $derived(nRows > 0 && nRows < 30);

  /** v1.0.16: автоматический выбор движка на основе объёма данных.
   *  n<30 → OLS (small-data), n≥30 → Bayesian. Customer обычно не управляет
   *  вручную - система делает выбор сама, чтобы избежать неправильного
   *  соотношения engine к данным.
   *  v2.1.0 pilot polish (2026-05-17): для borderline (20 ≤ n < 30) customer
   *  может override. userOverrodeEngine флаг блокирует auto-set после ручного
   *  выбора (localStorage persists override через session).
   *  v2.1.0 pilot R2 (2026-05-17 A2-03): key scoped per activeProjectId,
   *  иначе global key никогда не очищается → новый проект импортируется с
   *  unwanted override от старого. При смене проекта key другой → fresh state. */
  /** @param {string | null} projectId */
  function overrideKey(projectId) {
    return projectId ? `aurora.modelEngineOverride.${projectId}` : 'aurora.modelEngineOverride.__noproject__';
  }
  const userOverrodeEngine = $derived.by(() => {
    if (typeof window === 'undefined') return false;
    const pid = $activeProjectId;
    try { return localStorage.getItem(overrideKey(pid)) === '1'; } catch { return false; }
  });
  $effect(() => {
    if (nRows <= 0) return;
    if (userOverrodeEngine) return; // user явно выбрал - не перезаписываем
    modelEngine.set(recommendOls ? 'ols' : 'bayesian');
  });

  /** Записать override (вызывается из interactive engine card click). */
  /** @param {'bayesian' | 'ols'} engine */
  function selectEngineOverride(engine) {
    if (typeof window !== 'undefined') {
      try { localStorage.setItem(overrideKey($activeProjectId), '1'); } catch {}
    }
    modelEngine.set(engine);
  }

  // Restore from memory store on mount (A4: data is memory-only)
  const stored = get(importData);
  if (stored.file) {
    filePath = stored.file;
    fileName = stored.file.split(/[\\/]/).pop() || '';
    if (stored.rows && stored.rows.length) {
      previewRows = stored.rows;
    }
    // FIX: restore shape from store. Без этого после navigate-out/in shape=null →
    // nRows fallback к previewRows.length (20 - preview limit) → recommendOls=true →
    // OLS выбирается на проектах с ≥30 строк (баг увиденный в скрине).
    if (stored.shape && typeof stored.shape.rows === 'number') {
      shape = { rows: stored.shape.rows, cols: stored.shape.cols ?? 0 };
    }
    if (stored.columns && Array.isArray(stored.columns)) {
      previewHeaders = stored.columns.map(/** @param {any} c */ (c) => c.name ?? c);
    }
  }

  /**
   * Build auto project name from a file name.
   * Format: "{brand} ММХ {DDMM-YY}" - e.g. "Кагоцел РФ ММХ 1804-26".
   * Brand = first meaningful fragment before separators (_, +, -, «данные», etc).
   * @param {string} fileName
   * @returns {string}
   */
  function buildProjectName(fileName) {
    const stem = fileName.replace(/\.(xlsx|xls|csv)$/i, '').trim();
    // Cut off at first separator-ish marker so we keep only the brand part
    const brandMatch = stem.split(/[_+-–]|\s(?:данны|data|model|эконометрик|анализ|отчёт|план)/i)[0];
    const brand = (brandMatch || stem || 'Проект').trim().replace(/\s+/g, ' ').slice(0, 40);
    const d = new Date();
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const yy = String(d.getFullYear()).slice(-2);
    return `${brand} ММХ ${dd}${mm}-${yy}`;
  }

  // ── Tauri drag-drop listener ───────────────────────
  /** @type {(() => void) | null} */
  let unlistenDrop = null;

  onMount(() => {
    const win = getCurrentWindow();

    // Онбординг - запускаем с отложенной постановкой флага, чтобы DOM
    // успел отрисоваться (intro-options, drop-zone должны быть в DOM для
    // querySelector).
    if (!onboardingChecked && shouldShowOnboarding('import')) {
      onboardingChecked = true;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => { showOnboarding = true; });
      });
    }

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
      // Warn if model was trained (step 2 complete) - user loses training results
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
      // result.dtypes is a dict {col: dtype}, normalize to array [{name, dtype}]
      const columnsArray = result.dtypes
        ? Object.entries(result.dtypes).map(([name, dtype]) => ({ name, dtype }))
        : (result.headers ?? []).map((/** @type {string} */ h) => ({ name: h }));

      const currentImport = get(importData);
      const updated = {
        ...currentImport,
        file: path,
        rows: result.rows,
        columns: columnsArray,
        shape: { rows: result.shape?.[0] ?? 0, cols: result.shape?.[1] ?? 0 },
        fileName: result.file_name ?? path.split(/[\\/]/).pop() ?? '',
      };
      importData.set(updated);

      // Auto-create project if none exists - eliminates the "проект не выбран" block later.
      // Format: "{brand} ММХ {DDMM-YY}" - e.g. "Кагоцел РФ ММХ 1804-26".
      // If a project with that name already exists (Rust throws "уже существует"),
      // append (2), (3)… until a fresh name is found, OR activate the existing one.
      if (!get(activeProjectId)) {
        const baseName = buildProjectName(result.file_name ?? path.split(/[\\/]/).pop() ?? '');
        let created = false;
        for (let i = 0; i < 30 && !created; i++) {
          const candidate = i === 0 ? baseName : `${baseName} (${i + 1})`;
          try {
            const info = /** @type {any} */ (await invoke('project_create', { name: candidate }));
            if (info?.id) {
              activeProjectId.set(info.id);
              activeProject.set(info);
              created = true;
            }
          } catch (projErr) {
            const msg = String(projErr);
            if (!msg.includes('уже существует')) {
              console.error('Auto-create project failed:', projErr);
              break; // unknown error - stop retrying
            }
            // else loop: try next suffix
          }
        }
      }

      completeStep(0);
    } catch (e) {
      errorMsg = `Ошибка: ${e}`;
    } finally {
      loading = false;
    }
  }
</script>

<div class="import-step">

  <!-- Import mode chooser - показывается только когда файла ещё нет -->
  {#if !filePath && !loading}
    <div class="import-intro">
      <h2 class="intro-title">Начать работу с проектом</h2>
      <p class="intro-body">
        Выберите один из двух вариантов - загрузите файл данных для <b>нового анализа</b>
        или откройте <b>ранее сохранённый проект</b>, чтобы продолжить работу с него.
      </p>

      <!-- 1. Карточка «Новый проект» - описание, без кнопки (кнопка = dropzone ниже) -->
      <div class="intro-card">
        <div class="intro-card-header">
          <div class="intro-card-icon">📁</div>
          <div class="intro-card-title">Новый проект</div>
        </div>
        <div class="intro-card-body">
          Загрузите xlsx/csv с историческими данными - пройдёте полный цикл
          MMM-анализа: валидация → модель → декомпозиция → оптимизация → отчёт.
        </div>
      </div>

      <!-- 2. Dropzone - единый путь загрузки данных для нового проекта -->
      <div
        class="drop-zone drop-zone--inline"
        class:drag-over={isDragOver}
        role="button"
        tabindex="0"
        aria-label="Зона перетаскивания файла"
        data-tour-step="import-file"
        ondragenter={onDragenter}
        ondragover={onDragover}
        ondragleave={onDragleave}
        onclick={pickFile}
        onkeydown={(e) => e.key === 'Enter' && pickFile()}
      >
        <div class="drop-content">
          <div class="drop-icon">📂</div>
          <p class="drop-label">Перетащите файл сюда</p>
          <p class="drop-hint">или нажмите для выбора</p>
          <p class="drop-formats">.xlsx · .xls · .csv</p>
        </div>
      </div>

      <!-- 3. Карточка «Попробовать на примере» - для пользователя без своих данных -->
      <div class="intro-card">
        <div class="intro-card-header">
          <div class="intro-card-icon">📥</div>
          <div class="intro-card-title">Попробовать на примере</div>
        </div>
        <div class="intro-card-body">
          Скачайте готовый файл для одной из четырёх отраслей. Он работает
          <strong>двояко</strong>:
          <br>• <strong>как пример</strong> — перетащите в зону загрузки выше и
          пройдите весь pipeline без правок (данные синтетические, но реалистичные);
          <br>• <strong>как образец-шаблон</strong> — откройте в Excel, замените
          значения своими реальными данными, сохранив структуру (те же колонки,
          роли и единицы измерения, что нужны модели).
        </div>
        <div class="sample-grid">
          <button class="sample-btn" type="button" disabled={savingSample}
            onclick={() => downloadSample('synth_fmcg_brand.xlsx', 'FMCG бренд')}>
            <span class="sample-icon">🛒</span>
            <span class="sample-label">FMCG бренд</span>
            <span class="sample-hint">Выручка ₽, ТВ, цифра, наружка, performance</span>
          </button>
          <button class="sample-btn" type="button" disabled={savingSample}
            onclick={() => downloadSample('synth_otc_pharma.xlsx', 'OTC фарма')}>
            <span class="sample-icon">💊</span>
            <span class="sample-label">OTC фарма</span>
            <span class="sample-hint">Упаковки, ТВ TRP, аптеки, цифра</span>
          </button>
          <button class="sample-btn" type="button" disabled={savingSample}
            onclick={() => downloadSample('synth_real_estate.xlsx', 'Недвижимость')}>
            <span class="sample-icon">🏠</span>
            <span class="sample-label">Недвижимость</span>
            <span class="sample-hint">Лиды, ТВ, наружка, цифра, performance</span>
          </button>
          <button class="sample-btn" type="button" disabled={savingSample}
            onclick={() => downloadSample('synth_retail_ecom.xlsx', 'Ритейл / e-com')}>
            <span class="sample-icon">🏪</span>
            <span class="sample-label">Ритейл / e-com</span>
            <span class="sample-hint">Выручка ₽, ТВ, цифра, наружка, retail media</span>
          </button>
        </div>
        {#if sampleMsg}
          <div class="sample-msg" class:err={!savedSamplePath}>
            <span>{sampleMsg}</span>
            {#if savedSamplePath}
              <button class="sample-reveal" type="button" onclick={revealSample}>📂 Открыть папку</button>
            {/if}
          </div>
        {/if}
      </div>

      <!-- 4. Карточка «Загрузить сохранённый проект» -->
      <div class="intro-card">
        <div class="intro-card-header">
          <div class="intro-card-icon"><Package size={24} strokeWidth={1.5} style="vertical-align: -0.15em" /></div>
          <div class="intro-card-title">Загрузить сохранённый проект</div>
        </div>
        <div class="intro-card-body">
          Откройте <code>.aurora</code> архив с ранее завершённым анализом -
          данные, модель, декомпозиция, оптимизация и сценарии восстановятся
          на тот же шаг, где вы закончили.
        </div>
        <button class="intro-btn secondary" onclick={loadSavedProject} disabled={importingArchive}>
          {#if importingArchive}Загрузка…{:else}<Package size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Выбрать .aurora архив{/if}
        </button>
        <p class="intro-btn-hint">принимаются .aurora и .zip</p>
      </div>

      {#if archiveMsg}
        <p class="archive-msg" class:archive-err={archiveMsg.startsWith('Ошибка')}>{archiveMsg}</p>
      {/if}
    </div>
  {/if}

  <!-- Drop zone (states: loading / file-ready) - показывается ПОСЛЕ выбора файла -->
  {#if filePath || loading}
    <div
      class="drop-zone"
      class:drag-over={isDragOver}
      class:has-file={!!filePath && !loading}
      role="button"
      tabindex="0"
      aria-label="Файл загружен, зона замены"
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
          <div class="file-icon"><ChartColumn size={28} strokeWidth={1.5} /></div>
          <p class="file-name">{fileName}</p>
          {#if shape}
            <p class="file-meta">{shape.rows} строк × {shape.cols} столбцов · {sizeKb} KB</p>
          {/if}
          <p class="change-hint">Нажмите или перетащите другой файл, чтобы заменить</p>
        </div>
      {/if}
    </div>
  {/if}

  <!-- Error message -->
  {#if errorMsg}
    <div class="error-banner">
      <span class="error-icon"><TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /></span>
      {errorMsg}
    </div>
  {/if}

  <!-- DataTable preview -->
  {#if previewRows.length > 0 && !loading}
    {@const allowOverride = nRows >= 20 && nRows < 30}
    <div class="preview-section">
      <div class="preview-header">
        <h4>Предпросмотр данных</h4>
        <span class="preview-badge">первые 20 строк</span>
      </div>
      <!-- v2.1.0 (пилот 2026-05-16): ограничение высоты превью внутренним
           scroll, чтобы кнопка "Далее: Валидация" и блок "Тип моделирования"
           помещались на первый экран. -->
      <div class="preview-table-wrap">
        <DataTable
          headers={previewHeaders}
          rows={previewRows}
          emptyMessage="Нет данных для отображения"
        />
      </div>

      <!-- v1.0.16+: автоматический выбор движка на основе n_rows.
           n<30 → OLS (small-data fallback, closed-form, ~2-5 сек),
           n≥30 → Bayesian (full NUTS posterior, ~20-60 сек).
           UI: ОБА варианта показаны рядом, выбранный подсвечен accent-цветом,
           не выбранный - muted.
           v2.1.0 pilot polish (2026-05-17): для borderline (20 ≤ n < 30) карточки
           interactive - user может override (auto-OLS → Bayesian) с warning'ом
           о divergences. Для n < 20 (точно мало) или n ≥ 30 (точно много) -
           автовыбор без override. (`allowOverride` declared at parent {#if} scope.) -->
      <div class="engine-section">
        <div class="engine-section-header">
          <Tooltip text={TOOLTIPS['import.modeling_type']} position="top">
            <span class="engine-section-title" style="cursor:help; border-bottom: 1px dotted currentColor;">Тип моделирования</span>
          </Tooltip>
          {#if nRows > 0}
            <span class="engine-section-meta">
              {#if allowOverride}
                выбрано автоматически по {nRows} наблюдениям - можно изменить (на свой риск)
              {:else}
                выбрано автоматически по {nRows} наблюдениям
              {/if}
            </span>
          {:else}
            <span class="engine-section-meta">ожидание данных…</span>
          {/if}
        </div>
        <div class="engine-cards">
          <button
            type="button"
            class="engine-card"
            class:engine-card-active={$modelEngine === 'bayesian'}
            class:engine-card-muted={$modelEngine !== 'bayesian'}
            class:engine-card-interactive={allowOverride}
            disabled={!allowOverride || $modelEngine === 'bayesian'}
            onclick={() => { if (allowOverride) selectEngineOverride('bayesian'); }}
            aria-pressed={$modelEngine === 'bayesian'}
            aria-label="Выбрать Bayesian MMM"
          >
            <div class="engine-card-head">
              <span class="engine-card-icon"><Target size={20} strokeWidth={1.5} /></span>
              <Tooltip text={TOOLTIPS['import.bayesian']} position="top">
                <div class="engine-card-name" style="cursor:help;">Полное Bayesian MMM</div>
              </Tooltip>
              {#if $modelEngine === 'bayesian'}
                <span class="engine-card-badge engine-card-badge-active"><Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Выбрано</span>
              {:else if allowOverride}
                <span class="engine-card-badge engine-card-badge-muted">Можно выбрать</span>
              {:else}
                <span class="engine-card-badge engine-card-badge-muted">Доступно при n ≥ 30</span>
              {/if}
            </div>
            <p class="engine-card-desc">
              Золотой стандарт MMM-эконометрики. NUTS-сэмплер (NumPyro) оценивает полное апостериорное распределение для параметров каждого канала: корректные доверительные интервалы ROI и mROAS, устойчивость к выбросам, калиброванная неопределённость. Для решений с финансовыми последствиями.
            </p>
            {#if allowOverride && $modelEngine !== 'bayesian'}
              <p class="engine-card-warn">
                <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> При n &lt; 30 Bayesian-сэмплер может расходиться (divergences &gt; 0) и давать ненадёжные posterior'ы. Рекомендуем OLS.
              </p>
            {/if}
          </button>
          <button
            type="button"
            class="engine-card"
            class:engine-card-active={$modelEngine === 'ols'}
            class:engine-card-muted={$modelEngine !== 'ols'}
            class:engine-card-interactive={allowOverride}
            disabled={!allowOverride || $modelEngine === 'ols'}
            onclick={() => { if (allowOverride) selectEngineOverride('ols'); }}
            aria-pressed={$modelEngine === 'ols'}
            aria-label="Выбрать OLS MMM"
          >
            <div class="engine-card-head">
              <span class="engine-card-icon">⚡</span>
              <Tooltip text={TOOLTIPS['import.ols']} position="top">
                <div class="engine-card-name" style="cursor:help;">Упрощённое OLS-MMM</div>
              </Tooltip>
              {#if $modelEngine === 'ols'}
                <span class="engine-card-badge engine-card-badge-active"><Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Выбрано</span>
              {:else if allowOverride}
                <span class="engine-card-badge engine-card-badge-muted">Можно выбрать</span>
              {:else}
                <span class="engine-card-badge engine-card-badge-muted">Используется при n &lt; 30</span>
              {/if}
            </div>
            <p class="engine-card-desc">
              Small-data fallback. OLS-регрессия с аналитическим решением и bootstrap-доверительными интервалами (частотный подход): численно стабильное решение ценой статистической мощности. Для пилотных проектов и предварительного анализа - рекомендации трактовать как направление, а не точное число.
            </p>
          </button>
        </div>
      </div>

      <button
        class="quick-btn"
        onclick={() => pipelineCurrentStep.set(1)}
      >
        Далее: Валидация →
      </button>
    </div>
  {/if}

  {#if showOnboarding}
    <PipelineOnboarding
      steps={TOURS.import}
      stepKey="import"
      onDone={() => { showOnboarding = false; }}
    />
  {/if}

</div>

<style>
  .import-step {
    display: flex;
    flex-direction: column;
    /* v2.1.0 (пилот 2026-05-16): сокращены gap и padding, убран overflow-y
       (родительский .pipeline-main владеет scroll) - чтобы кнопка
       "Далее: Валидация" помещалась на первый экран без обрезки. */
    gap: 14px;
    padding: 16px 24px;
    box-sizing: border-box;
  }

  /* ── Drop zone ── */
  .drop-zone {
    /* v2.1.0: 180px -> 140px для пустой dropzone (без файла). */
    min-height: 140px;
    border: 2px dashed var(--dropzone-border);
    border-radius: var(--radius-card, 16px);
    background: var(--dropzone-bg);
    box-shadow: var(--shadow-card);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s, transform 0.15s, box-shadow 0.2s;
    flex-shrink: 0;
  }

  .drop-zone:hover,
  .drop-zone:focus-visible {
    border-color: var(--border-active);
    background: var(--bg-card-hover);
    outline: none;
  }

  .drop-zone.drag-over {
    border-color: var(--accent-primary);
    background: var(--accent-glow);
    transform: scale(1.01);
  }

  .drop-zone.has-file {
    border-style: solid;
    border-color: color-mix(in srgb, var(--success) 45%, transparent);
    background: color-mix(in srgb, var(--success) 6%, var(--bg-card));
    /* v2.1.0 (пилот 2026-05-16): когда файл загружен - компактная карточка
       вместо 120px воздуха. */
    min-height: 0;
  }
  .drop-zone.has-file .drop-content {
    padding: 14px 24px;
  }

  /* Inline dropzone - компактная, живёт внутри intro-chooser между карточками */
  .drop-zone--inline {
    min-height: 140px;
    box-shadow: none;
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 6%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
  }
  .drop-zone--inline:hover,
  .drop-zone--inline:focus-visible {
    border-color: var(--accent-primary, #3b82f6);
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 10%, transparent);
  }
  .drop-zone--inline .drop-content { padding: 22px 24px; }

  .drop-zone.has-file:hover {
    border-color: var(--border-active);
    background: var(--bg-card-hover);
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
    color: var(--text-muted);
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
    color: var(--success, #22c55e);
    margin: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: min(85vw, 1100px);
  }

  .file-meta {
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }

  .change-hint {
    font-size: 11px;
    color: var(--text-muted);
    margin: 6px 0 0;
    font-style: italic;
  }

  /* ── Spinner ── */
  .spinner {
    width: 32px;
    height: 32px;
    border: 3px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
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
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
    border-radius: 10px;
    font-size: 13px;
    color: var(--danger);
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

  /* v2.1.0 (пилот 2026-05-16): ограничение высоты табличного предпросмотра
     внутренним scroll. Раньше таблица показывала все 20 строк подряд,
     отжимая блок "Тип моделирования" и кнопку "Далее" за пределы экрана.
     290px = около 8 строк видны сразу, остальное прокручивается внутри. */
  .preview-table-wrap {
    max-height: 290px;
    overflow: auto;
    border-radius: 12px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
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
    background: color-mix(in srgb, var(--accent-primary) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-radius: 20px;
    color: var(--accent-primary);
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

  /* v1.1.0+: Engine auto-selection - две карточки рядом (Bayesian | OLS),
     выбранная подсвечена accent-цветом, не выбранная в muted state. */
  .engine-section {
    margin-top: 16px;
  }
  .engine-section-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 10px;
    padding: 0 4px;
  }
  .engine-section-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    letter-spacing: 0.02em;
  }
  .engine-section-meta {
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
    font-style: italic;
  }
  .engine-cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  @media (max-width: 760px) {
    .engine-cards { grid-template-columns: 1fr; }
  }
  .engine-card {
    /* v2.1.0 pilot polish: <button> в режиме card — сброс default button styles. */
    padding: 14px 16px;
    border-radius: 10px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    transition: opacity 0.15s, border-color 0.15s, transform 0.1s;
    text-align: left;
    font: inherit;
    color: inherit;
    width: 100%;
    cursor: default;
    appearance: none;
  }
  .engine-card-interactive:not(:disabled) { cursor: pointer; }
  .engine-card-interactive:not(:disabled):hover {
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, var(--border-subtle, rgba(255,255,255,0.08)));
    transform: translateY(-1px);
  }
  .engine-card-interactive:not(:disabled):focus-visible {
    outline: 2px solid var(--accent-primary, #3b82f6);
    outline-offset: 2px;
  }
  .engine-card:disabled {
    cursor: default;
  }
  .engine-card-warn {
    margin: 8px 0 0 0;
    padding: 6px 10px;
    background: color-mix(in srgb, var(--warning, #f59e0b) 8%, transparent);
    border-left: 2px solid var(--warning, #f59e0b);
    border-radius: 4px;
    font-size: 11px;
    line-height: 1.45;
    color: var(--warning, #f59e0b);
  }
  .engine-card-active {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 10%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 45%, transparent);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
  }
  .engine-card-muted {
    opacity: 0.55;
  }
  .engine-card-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
    flex-wrap: wrap;
  }
  .engine-card-icon { font-size: 20px; flex-shrink: 0; }
  .engine-card-name {
    flex: 1;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    min-width: 140px;
  }
  .engine-card-badge {
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 10.5px;
    font-weight: 500;
    letter-spacing: 0.02em;
    white-space: nowrap;
  }
  .engine-card-badge-active {
    background: color-mix(in srgb, var(--success, #22c55e) 18%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #22c55e) 35%, transparent);
    color: var(--success);
  }
  .engine-card-badge-muted {
    background: color-mix(in srgb, var(--text-secondary, #94a3b8) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-secondary, #94a3b8) 22%, transparent);
    color: var(--text-secondary, #94a3b8);
  }
  .engine-card-desc {
    margin: 0;
    font-size: 12px;
    line-height: 1.55;
    color: var(--text-secondary, #94a3b8);
  }

  /* legacy selector classes (unused after v1.0.16 auto-selection refactor)
     kept for CSS compatibility - to remove in next cleanup pass */
  .engine-selector {
    margin-top: 16px;
    padding: 16px 18px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 10px;
  }
  .engine-title {
    margin: 0 0 12px 0;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }
  .engine-options { display: flex; flex-direction: column; gap: 10px; }
  .engine-radio {
    display: flex;
    gap: 12px;
    padding: 12px 14px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .engine-radio:hover {
    background: rgba(255,255,255,0.06);
    border-color: rgba(255,255,255,0.16);
  }
  .engine-radio.active {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 12%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 40%, transparent);
  }
  .engine-radio input[type="radio"] {
    appearance: none;
    width: 16px; height: 16px;
    border-radius: 50%;
    border: 2px solid rgba(255,255,255,0.3);
    margin: 2px 0 0 0;
    cursor: pointer;
    position: relative;
    flex-shrink: 0;
  }
  .engine-radio.active input[type="radio"] { border-color: var(--accent-primary, #3b82f6); }
  .engine-radio.active input[type="radio"]::after {
    content: ''; position: absolute;
    top: 50%; left: 50%; transform: translate(-50%, -50%);
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--accent-primary, #3b82f6);
  }
  .engine-content { flex: 1; }
  .engine-label {
    display: flex; align-items: center; gap: 8px;
    font-size: 13.5px; font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    margin-bottom: 4px;
  }
  .engine-icon { font-size: 16px; }
  .engine-recommend {
    margin-left: auto;
    padding: 2px 8px;
    background: color-mix(in srgb, var(--success, #22c55e) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #22c55e) 30%, transparent);
    border-radius: 12px;
    color: var(--success);
    font-size: 10.5px;
    font-weight: 500;
    letter-spacing: 0.02em;
  }
  .engine-desc {
    margin: 0;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-secondary, #94a3b8);
  }

  /* ── Import mode chooser (New project / Load archive) ────────────── */
  .import-intro {
    margin: 0 auto 24px auto;
    max-width: 720px;
    width: 100%;
    padding: 24px 28px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border: 1px solid var(--border);
    border-radius: 14px;
    box-shadow: var(--shadow-card);
  }
  .intro-title {
    margin: 0 0 8px 0;
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
  }
  .intro-body {
    margin: 0 0 20px 0;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 1.6;
  }
  .import-intro > .intro-card,
  .import-intro > .drop-zone--inline {
    margin-top: 14px;
  }
  /* Визуальный разрыв между «Новый проект» блоком (dropzone) и
     «Загрузить сохранённый проект». «или» посередине + бóльший отступ,
     чтобы читалось как ОТДЕЛЬНАЯ секция. */
  .import-intro > .drop-zone--inline + .intro-card {
    margin-top: 56px;
    position: relative;
  }
  .import-intro > .drop-zone--inline + .intro-card::before {
    content: 'или';
    position: absolute;
    top: -32px;
    left: 50%;
    transform: translateX(-50%);
    padding: 4px 14px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    color: var(--text-muted, #94a3b8);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-weight: 600;
    z-index: 1;
  }
  .import-intro > .drop-zone--inline + .intro-card::after {
    content: '';
    position: absolute;
    top: -22px;
    left: 0;
    right: 0;
    height: 1px;
    background: var(--border-subtle, rgba(255, 255, 255, 0.1));
  }
  .intro-card {
    padding: 18px 20px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: var(--shadow-elevation-1);
    display: flex;
    flex-direction: column;
    gap: 10px;
    transition: border-color 0.15s, background 0.15s, box-shadow 0.15s, transform 0.15s;
  }
  .intro-card:hover {
    box-shadow: var(--shadow-elevation-2);
    transform: translateY(-1px);
  }
  .intro-card:hover {
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 35%, transparent);
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 8%, transparent);
  }
  .intro-card-header {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .intro-card-icon { font-size: 28px; line-height: 1; }
  .intro-card-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .intro-card-body {
    flex: 1;
    font-size: 13px;
    line-height: 1.55;
    color: var(--text-secondary);
  }
  .intro-card-body code {
    background: rgba(255,255,255,0.08);
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 12px;
  }
  .intro-btn {
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s, border-color 0.15s;
    font-family: inherit;
    margin-top: 6px;
  }
  .intro-btn.primary {
    background: var(--accent-primary, #3b82f6);
    color: white;
    border: 1px solid var(--accent-primary, #3b82f6);
  }
  .intro-btn.secondary {
    background: transparent;
    color: var(--text-primary);
    border: 1px solid var(--border, rgba(255,255,255,0.2));
  }
  .intro-btn.secondary:hover:not(:disabled) {
    border-color: var(--accent-primary, #3b82f6);
    color: var(--accent-primary, #3b82f6);
  }
  .intro-btn:hover:not(:disabled) { opacity: 0.9; }
  .intro-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .intro-btn-hint {
    margin: 2px 0 0 0;
    font-size: 11px;
    color: var(--text-muted);
    font-style: italic;
  }
  .sample-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-top: 12px;
  }
  .sample-btn {
    display: grid;
    grid-template-columns: auto 1fr;
    grid-template-rows: auto auto;
    column-gap: 10px;
    row-gap: 2px;
    align-items: center;
    padding: 10px 12px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    text-decoration: none;
    color: var(--text-primary);
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease;
    /* button-reset (раньше был <a>): шрифт/выравнивание/нативная хромировка */
    font: inherit;
    text-align: left;
    width: 100%;
    appearance: none;
    -webkit-appearance: none;
  }
  .sample-btn:disabled { opacity: 0.5; cursor: default; }

  .sample-msg {
    margin-top: 10px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    font-size: 13px;
    color: var(--text-secondary);
  }
  .sample-msg.err { color: #ff6b6b; }
  .sample-reveal {
    font: inherit;
    font-size: 12px;
    padding: 4px 10px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 6px;
    color: var(--text-primary);
    cursor: pointer;
  }
  .sample-reveal:hover { background: rgba(255,255,255,0.1); }
  .sample-btn:hover, .sample-btn:focus-visible {
    background: rgba(255,255,255,0.07);
    border-color: rgba(255,255,255,0.18);
    outline: none;
  }
  .sample-icon {
    grid-row: 1 / span 2;
    font-size: 20px;
    line-height: 1;
  }
  .sample-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .sample-hint {
    font-size: 11px;
    color: var(--text-muted);
  }
  .archive-msg {
    margin: 14px 0 0 0;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--success, #22c55e) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #22c55e) 30%, transparent);
    border-radius: 8px;
    color: var(--success, #22c55e);
    font-size: 13px;
    line-height: 1.5;
    word-break: break-word;
  }
  .archive-msg.archive-err {
    background: color-mix(in srgb, var(--danger, #ef4444) 10%, transparent);
    border-color: color-mix(in srgb, var(--danger, #ef4444) 30%, transparent);
    color: var(--danger, #ef4444);
  }

  /* v2.1.0 п.5.6: static spinner ring */
  @media (prefers-reduced-motion: reduce) {
    .spinner {
      border-color: color-mix(in srgb, var(--accent-primary) 70%, transparent);
    }
  }
</style>
