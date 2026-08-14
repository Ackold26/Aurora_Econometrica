<script>
  import { page } from '$app/state';
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { activeBrand, activeWorkflow, workflowView, isCreativeHub } from '$lib/creative-store.js';
  import { activeCabinet, cloudConsentPromptOpen } from '$lib/store.js';
  import { toast } from '$lib/toast.js';
  import { estimateSavedTime, pluralRu } from '$lib/psy.js';
  import { Star } from 'lucide-svelte';
  import WorkflowGraph from '$lib/components/workflow/WorkflowGraph.svelte';
  import WorkflowCanvas from '$lib/components/workflow/WorkflowCanvas.svelte';
  import CanvasToolbar from '$lib/components/workflow/CanvasToolbar.svelte';
  import HintBubble from '$lib/components/workflow/HintBubble.svelte';
  import { HINTS } from '$lib/hints.js';

  /** @type {any} */
  let canvasRef = $state(undefined);

  /** @type {any} */
  let workflow = $state(null);
  let loading = $state(true);
  let editingName = $state(false);
  let showAddModal = $state(false);

  let addAfterId = $state(null);

  /** @type {Array<{id: string, name: string, icon: string, color: string}>} */
  let cabinets = $state([]);

  // Smart suggestions: routing table (which cabinet logically follows which)
  const nextSuggestions = {
    'communication-analyst': ['communication-strategist'],
    'communication-strategist': ['creative-director', 'copywriter'],
    'creative-director': ['copywriter', 'art-director', 'focus-groups'],
    'copywriter': ['focus-groups', 'art-director', 'lawyer-advertising'],
    'art-director': ['focus-groups', 'lawyer-advertising'],
    'focus-groups': ['copywriter', 'creative-director'],
    'media-analyst': ['communication-analyst', 'communication-strategist'],
    'lawyer-contracts': [],
    'lawyer-claims': [],
    'lawyer-advertising': [],
  };

  // Execution state
  /** @type {any} */
  let executionId = $state(null);
  let nodeStatuses = $state({});
  /** @type {any} */
  let executionStatus = $state(null); // 'running'|'completed'|'failed'|'cancelled'
  /** @type {any} */
  let unlistenExec = $state(null);

  // PSY-4: Celebration state
  let showCelebration = $state(false);
  /** @type {number|null} */
  let executionStartTime = $state(null);
  /** @type {{savedHours: string, efficiency: string, stepCount: number, timeSec: number}|null} */
  let celebrationData = $state(null);

  // Brief state
  let briefText = $state('');
  let briefExpanded = $state(false);
  let briefSaving = $state(false);

  // Export state
  let exporting = $state(false);

  async function saveBrief() {
    const brandId = $activeBrand?.brand_id || '';
    if (!workflow || !brandId) return;
    briefSaving = true;
    try {
      await invoke('campaign_set_brief', {
        brandId,
        campaignId: workflow.id,
        briefText,
        briefFilePaths: [],
      });
      workflow = { ...workflow, brief_text: briefText };
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    } finally {
      briefSaving = false;
    }
  }

  /**
   * Send desktop notification when pipeline completes or fails.
   * @param {string} name
   * @param {number} stepCount
   * @param {number} timeSec
   * @param {string} [error]
   */
  async function sendPipelineNotification(name, stepCount, timeSec, error) {
    try {
      const { isPermissionGranted, requestPermission, sendNotification } = await import('@tauri-apps/plugin-notification');
      let granted = await isPermissionGranted();
      if (!granted) {
        const perm = await requestPermission();
        granted = perm === 'granted';
      }
      if (!granted) return;
      if (error) {
        sendNotification({ title: 'Aurora AI - Pipeline failed', body: `"${name}" - ошибка: ${error}` });
      } else {
        const timeStr = timeSec < 60 ? `${timeSec}с` : `${Math.floor(timeSec / 60)}м ${timeSec % 60}с`;
        sendNotification({ title: 'Aurora AI - Pipeline завершён', body: `"${name}" - ${stepCount} ${pluralRu(stepCount, 'шаг', 'шага', 'шагов')}, ${timeStr}` });
      }
    } catch { /* notification not available */ }
  }

  /** Если ошибка выполнения — требование согласия на облачную обработку (бэкенд-гейт
   * run_claude_pipeline возвращает [CL-CONSENT]), открыть экран согласия. Единый
   * чок-поинт для workflow-пути (кабинет-путь покрыт гейтом /cabinet).
   * @param {unknown} err
   * @returns {boolean} true, если это случай согласия */
  function maybeCloudConsentPrompt(err) {
    if (err != null && String(err).includes('CL-CONSENT')) {
      cloudConsentPromptOpen.set(true);
      return true;
    }
    return false;
  }

  async function runPipeline() {
    const brandId = $activeBrand?.brand_id || '';
    if (!workflow || !brandId || executionStatus === 'running') return;
    if (briefText.trim() && briefText !== workflow.brief_text) {
      await saveBrief();
    }
    const stepCount = countSteps(workflow.workflow_steps);
    const mode = workflow.brief_text ? 'пайплайн (с контекстной цепочкой)' : 'workflow';
    if (!confirm(`Запустить ${mode} "${workflow.name}"?\n${stepCount} шагов`)) return;
    await save();
    try {
      const { listen } = await import('@tauri-apps/api/event');
      const cmd = workflow.brief_text ? 'workflow_execute_with_brief' : 'workflow_execute';
      executionId = await invoke(cmd, { brandId, workflowId: workflow.id });
      executionStatus = 'running';
      nodeStatuses = {};
      executionStartTime = Date.now();
      showCelebration = false;
      toast(workflow.brief_text ? 'Пайплайн запущен' : 'Workflow запущен', 'success');

      if (unlistenExec) /** @type {Function} */ (unlistenExec)();
      unlistenExec = await listen(`workflow-execution-${executionId}`, (event) => {
        const data = JSON.parse(/** @type {string} */ (event.payload));
        if (data.type === 'node-status') {
          nodeStatuses = { ...nodeStatuses, [data.node_id]: data.status };
          // Шаг выполнен, но не полностью: часть результатов не сохранилась. Раньше об этом
          // знал только журнал приложения, а человек видел ровно то же «готово», что и при
          // полном успехе, — и узнавал о потере, когда файлов уже не было.
          // Предупреждение приходит отдельным полем, а не особым значением статуса: иначе
          // незнакомое значение не отрисовалось бы ни выполненным, ни упавшим.
          if (data.warning) {
            toast(`Шаг завершён, но ${data.warning}`, 'warning', 8000);
          }
          updateStepStatus(workflow.workflow_steps, data.node_id, data.status);
          workflow = { ...workflow };
        } else if (data.type === 'execution-status') {
          executionStatus = data.status;
          if (data.status === 'completed') {
            const timeSec = executionStartTime ? Math.round((Date.now() - executionStartTime) / 1000) : 0;
            const sc = countSteps(workflow.workflow_steps);
            const saved = estimateSavedTime(sc, timeSec);
            celebrationData = { savedHours: saved.savedHours, efficiency: saved.efficiency, stepCount: sc, timeSec };
            showCelebration = true;
            sendPipelineNotification(workflow.name, sc, timeSec);
          } else if (data.status === 'failed') {
            if (maybeCloudConsentPrompt(data.error)) {
              toast('Нужно согласие на облачную обработку для кабинетов-советников', 'error', 6000);
            } else {
              toast(`Ошибка: ${data.error || ''}`, 'error');
            }
            sendPipelineNotification(workflow.name, 0, 0, data.error);
          }
        }
      });
    } catch (err) {
      if (maybeCloudConsentPrompt(err)) {
        toast('Нужно согласие на облачную обработку для кабинетов-советников', 'error', 6000);
      } else {
        toast(`Ошибка запуска: ${err}`, 'error');
      }
      executionStatus = null;
    }
  }

  async function exportZip() {
    const brandId = $activeBrand?.brand_id || '';
    if (!workflow || !brandId) return;
    exporting = true;
    try {
      const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
      const path = await saveDialog({
        defaultPath: `${workflow.name.replace(/[^a-zA-Zа-яА-Я0-9]/g, '_')}.zip`,
        filters: [{ name: 'ZIP Archive', extensions: ['zip'] }],
      });
      if (!path) { exporting = false; return; }
      await invoke('campaign_export_zip', { brandId, campaignId: workflow.id, outputPath: path });
      toast('Результаты экспортированы', 'success');
    } catch (err) {
      toast(`Ошибка экспорта: ${err}`, 'error');
    } finally {
      exporting = false;
    }
  }

  async function openExportsFolder() {
    const brandId = $activeBrand?.brand_id || '';
    if (!workflow || !brandId) return;
    try {
      await invoke('campaign_open_exports', { brandId, campaignId: workflow.id });
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    }
  }

  // Missing cabinets warning
  let missingSuggestion = $derived.by(() => {
    if (!workflow?.workflow_steps) return null;
    const usedCabinets = new Set();
    /** @param {any[]} steps */
    function collect(steps) {
      for (const s of steps) {
        if (s.type === 'single') usedCabinets.add(s.cabinet_id);
        if (s.type === 'parallel') s.branches.forEach(collect);
        if (s.type === 'loop') { collect(s.body); collect(s.review); }
      }
    }
    collect(workflow.workflow_steps);
    if (usedCabinets.has('copywriter') && !usedCabinets.has('lawyer-advertising')) {
      return 'Добавьте юридическую проверку рекламы (Юрист - Реклама)';
    }
    if (usedCabinets.has('creative-director') && !usedCabinets.has('focus-groups')) {
      return 'Добавьте тестирование концепции (Фокус-группы)';
    }
    return null;
  });

  // Load cabinets list once
  let cabinetsLoaded = $state(false);
  $effect(() => {
    if (cabinetsLoaded) return;
    cabinetsLoaded = true;
    invoke('get_cabinets').then((/** @type {any[]} */ result) => {
      cabinets = result.map(c => ({ id: c.id, name: c.name, icon: c.icon || '\u25C6', color: c.color || '#666' }));
    }).catch(() => { cabinets = []; });
  });

  // Load workflow when route changes. $effect tracks page.params.id.
  let lastLoadedId = $state('');
  $effect(() => {
    const routeId = page.params.id;
    if (routeId && routeId !== lastLoadedId) {
      lastLoadedId = routeId;
      loadWorkflow();
    }
    return () => {
      if (unlistenExec) { /** @type {Function} */ (unlistenExec)(); unlistenExec = null; }
      clearTimeout(/** @type {any} */ (saveTimeout));
    };
  });

  async function loadWorkflow() {
    const brandId = $activeBrand?.brand_id || '';
    if (!brandId) return;
    loading = true;
    try {
      const wf = await invoke('campaign_get', {
        brandId,
        campaignId: page.params.id,
      });
      workflow = wf;
      briefText = wf.brief_text || '';
      activeWorkflow.set(wf);
    } catch (err) {
      toast(`Workflow не найден: ${err}`, 'error');
      goto('/workflow');
    }
    loading = false;
  }

  async function save() {
    const brandId = $activeBrand?.brand_id || '';
    if (!workflow || !brandId) return;
    try {
      await invoke('workflow_save', {
        brandId,
        campaign: workflow,
      });
    } catch (err) {
      toast(`Ошибка сохранения: ${err}`, 'error');
    }
  }

  // Debounced auto-save with indicator
  /** @type {any} */
  let saveTimeout = null;
  let saveStatus = $state(''); // '' | 'saving' | 'saved'
  function scheduleAutoSave() {
    saveStatus = '';
    clearTimeout(saveTimeout);
    saveTimeout = setTimeout(async () => {
      saveStatus = 'saving';
      await save();
      saveStatus = 'saved';
      setTimeout(() => { if (saveStatus === 'saved') saveStatus = ''; }, 2000);
    }, 1000);
  }

  /** @param {any} step */
  function handleStepClick(step) {
    toast(`${step.label} (${step.cabinet_id})`, 'info', 1500);
  }

  // ── Execution ──

  async function runWorkflow() {
    const brandId = $activeBrand?.brand_id || '';
    if (!workflow || !brandId || executionStatus === 'running') return;
    const stepCount = countSteps(workflow.workflow_steps);
    if (!confirm(`Запустить workflow "${workflow.name}"?\n${stepCount} шагов будут выполнены последовательно.`)) return;
    await save();
    try {
      const { listen } = await import('@tauri-apps/api/event');
      executionId = await invoke('workflow_execute', {
        brandId,
        workflowId: workflow.id,
      });
      executionStatus = 'running';
      nodeStatuses = {};
      executionStartTime = Date.now();
      showCelebration = false;
      toast('Workflow запущен', 'success');

      // Listen for status events
      if (unlistenExec) /** @type {Function} */ (unlistenExec)();
      unlistenExec = await listen(`workflow-execution-${executionId}`, (event) => {
        const data = JSON.parse(/** @type {string} */ (event.payload));
        if (data.type === 'node-status') {
          nodeStatuses = { ...nodeStatuses, [data.node_id]: data.status };
          // Шаг выполнен, но не полностью: часть результатов не сохранилась. Раньше об этом
          // знал только журнал приложения, а человек видел ровно то же «готово», что и при
          // полном успехе, — и узнавал о потере, когда файлов уже не было.
          // Предупреждение приходит отдельным полем, а не особым значением статуса: иначе
          // незнакомое значение не отрисовалось бы ни выполненным, ни упавшим.
          if (data.warning) {
            toast(`Шаг завершён, но ${data.warning}`, 'warning', 8000);
          }
          updateStepStatus(workflow.workflow_steps, data.node_id, data.status);
          workflow = { ...workflow }; // trigger reactivity
        } else if (data.type === 'execution-status') {
          executionStatus = data.status;
          if (data.status === 'completed') {
            // PSY-4: показать celebration
            const timeSec = executionStartTime ? Math.round((Date.now() - executionStartTime) / 1000) : 0;
            const sc = countSteps(workflow.workflow_steps);
            const saved = estimateSavedTime(sc, timeSec);
            celebrationData = { savedHours: saved.savedHours, efficiency: saved.efficiency, stepCount: sc, timeSec };
            showCelebration = true;
            sendPipelineNotification(workflow.name, sc, timeSec);
          } else if (data.status === 'failed') {
            if (maybeCloudConsentPrompt(data.error)) {
              toast('Нужно согласие на облачную обработку для кабинетов-советников', 'error', 6000);
            } else {
              toast(`Workflow ошибка: ${data.error || ''}`, 'error');
            }
            sendPipelineNotification(workflow.name, 0, 0, data.error);
          }
        }
      });
    } catch (err) {
      if (maybeCloudConsentPrompt(err)) {
        toast('Нужно согласие на облачную обработку для кабинетов-советников', 'error', 6000);
      } else {
        toast(`Ошибка запуска: ${err}`, 'error');
      }
      executionStatus = null;
    }
  }

  async function cancelWorkflow() {
    if (!executionId) return;
    try {
      await invoke('workflow_control', { executionId, action: 'cancel' });
      executionStatus = 'cancelled';
      toast('Workflow отменён', 'info');
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    }
  }

  /** @param {Array<any>} steps @param {string} nodeId @param {string} status */
  function updateStepStatus(steps, nodeId, status) {
    if (!steps) return;
    for (const s of steps) {
      if (s.id === nodeId) { s.status = status; return; }
      if (s.type === 'parallel') s.branches.forEach(/** @param {any} b */ b => updateStepStatus(b, nodeId, status));
      if (s.type === 'loop') { updateStepStatus(s.body, nodeId, status); updateStepStatus(s.review, nodeId, status); }
    }
  }

  /** Count all Single steps recursively
   * @param {any[]} steps */
  function countSteps(steps) {
    if (!steps) return 0;
    let n = 0;
    for (const s of steps) {
      if (s.type === 'single') n++;
      else if (s.type === 'parallel') s.branches.forEach(/** @param {any} b */ b => { n += countSteps(b); });
      else if (s.type === 'loop') { n += countSteps(s.body) + countSteps(s.review); }
    }
    return n;
  }

  /** Get suggested cabinets based on the last step before addAfterId */
  function getSuggestedCabinets() {
    if (!workflow?.workflow_steps || !addAfterId) return [];
    const step = workflow.workflow_steps.find(/** @param {any} s */ s => s.id === addAfterId);
    if (!step || step.type !== 'single') return [];
    return /** @type {Record<string, string[]>} */ (nextSuggestions)[step.cabinet_id] || [];
  }

  /** @param {any} afterId */
  function handleAddStep(afterId) {
    addAfterId = afterId;
    showAddModal = true;
  }

  /** @param {string} cabinetId @param {string} cabinetName */
  function addStep(cabinetId, cabinetName) {
    if (!workflow?.workflow_steps) return;
    const newStep = {
      type: 'single',
      id: `s-${Date.now()}`,
      cabinet_id: cabinetId,
      command: null,
      label: cabinetName,
      status: 'idle',
    };

    if (addAfterId === null) {
      workflow.workflow_steps = [...workflow.workflow_steps, newStep];
    } else {
      const idx = workflow.workflow_steps.findIndex(/** @param {any} s */ s => s.id === addAfterId);
      if (idx >= 0) {
        workflow.workflow_steps = [
          ...workflow.workflow_steps.slice(0, idx + 1),
          newStep,
          ...workflow.workflow_steps.slice(idx + 1),
        ];
      } else {
        workflow.workflow_steps = [...workflow.workflow_steps, newStep];
      }
    }

    showAddModal = false;
    scheduleAutoSave();
  }

  /** @param {string} stepId */
  function handleRemoveStep(stepId) {
    if (!workflow?.workflow_steps) return;
    if (!confirm('Удалить этот шаг?')) return;
    workflow.workflow_steps = removeStepDeep(workflow.workflow_steps, stepId);
    scheduleAutoSave();
  }

  /** Recursively remove step by id from nested structure
   * @param {any[]} steps @param {string} stepId
   * @returns {any[]} */
  function removeStepDeep(steps, stepId) {
    return steps
      .filter(/** @param {any} s */ s => s.id !== stepId)
      .map(/** @param {any} s */ s => {
        if (s.type === 'parallel') {
          return { ...s, branches: s.branches.map(/** @param {any} b */ b => removeStepDeep(b, stepId)) };
        }
        if (s.type === 'loop') {
          return { ...s, body: removeStepDeep(s.body, stepId), review: removeStepDeep(s.review, stepId) };
        }
        return s;
      });
  }

  async function openHelp() {
    try {
      await invoke('open_help', { cabinetId: 'workflow-builder' });
    } catch {
      toast('Справка недоступна', 'error');
    }
  }

  /** @param {any} e */
  function updateName(e) {
    if (!workflow) return;
    workflow.name = e.target.value || 'Без названия';
    editingName = false;
    scheduleAutoSave();
  }
</script>

<div class="editor">
  <header class="editor-header">
    <button class="back-btn" aria-label="Назад к списку" onclick={() => { activeWorkflow.set(null); goto('/workflow'); }}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
    </button>

    {#if editingName}
      <input
        class="name-input"
        value={workflow?.name || ''}
        onblur={updateName}
        onkeydown={(e) => e.key === 'Enter' && updateName(e)}
      />
    {:else}
      <button class="name-display" onclick={() => editingName = true}>
        {workflow?.name || 'Загрузка...'}
      </button>
    {/if}

    {#if $activeBrand}
      <span class="brand-badge">{$activeBrand.name}</span>
    {/if}

    {#if executionStatus === 'running'}
      <button class="cancel-btn" onclick={cancelWorkflow}>Отменить</button>
    {:else if executionStatus === 'completed'}
      <button class="export-btn" onclick={exportZip} disabled={exporting}>{exporting ? '...' : 'Экспорт ZIP'}</button>
      <button class="export-btn" onclick={openExportsFolder}>Открыть папку</button>
      <button class="run-btn" onclick={runPipeline} disabled={!workflow?.workflow_steps?.length}>Перезапустить</button>
    {:else}
      <button class="run-btn" onclick={runPipeline} disabled={!workflow?.workflow_steps?.length}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        {briefText.trim() ? 'Пайплайн' : 'Запустить'}
      </button>
    {/if}
    <button class="save-btn" onclick={save}>Сохранить</button>
    <button class="help-btn" onclick={openHelp} title="Справка по Workflow Builder">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
    </button>
    {#if saveStatus === 'saving'}
      <span class="save-indicator">Сохранение...</span>
    {:else if saveStatus === 'saved'}
      <span class="save-indicator save-indicator--done">Сохранено</span>
    {/if}
  </header>

  <!-- Brief panel (collapsible) -->
  <div class="brief-panel" class:expanded={briefExpanded}>
    <button class="brief-toggle" onclick={() => briefExpanded = !briefExpanded}>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="transform: rotate({briefExpanded ? 90 : 0}deg); transition: transform 0.15s"><path d="M9 18l6-6-6-6"/></svg>
      <span>Бриф {briefText.trim() ? `(${briefText.trim().split(/\s+/).length} слов)` : '(пусто)'}</span>
    </button>
    {#if briefExpanded}
      <div class="brief-content">
        <textarea
          class="brief-textarea"
          bind:value={briefText}
          placeholder="Опишите задачу... Бриф передаётся каждому шагу пайплайна как контекст."
          rows="4"
          onblur={saveBrief}
        ></textarea>
        {#if briefSaving}
          <span class="brief-saving">Сохранение...</span>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Smart suggestion banner -->
  {#if missingSuggestion}
    <div class="suggestion-banner">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      {missingSuggestion}
    </div>
    <div class="hints-area">
      <HintBubble hint={HINTS['wf-suggestion-banner']} />
    </div>
  {/if}

  <!-- Execution status bar -->
  {#if executionStatus}
    <div class="exec-bar" class:exec-running={executionStatus === 'running'} class:exec-done={executionStatus === 'completed'} class:exec-error={executionStatus === 'failed'}>
      {#if executionStatus === 'running'}
        <span class="exec-spinner"></span> Выполняется...
      {:else if executionStatus === 'completed'}
        Workflow завершён
      {:else if executionStatus === 'failed'}
        Ошибка выполнения
      {:else if executionStatus === 'cancelled'}
        Отменён
      {/if}
    </div>
  {/if}

  {#if loading}
    <div class="loading">Загрузка workflow...</div>
  {:else if workflow?.workflow_steps}
    <!-- Contextual hints -->
    <div class="hints-area">
      {#if !executionStatus}
        <HintBubble hint={HINTS['wf-editor-intro']} />
        {#if workflow.workflow_steps.length === 0}
          <HintBubble hint={HINTS['wf-add-step']} />
        {/if}
        {#if workflow.workflow_steps.length > 0}
          <HintBubble hint={HINTS['wf-run-button']} />
        {/if}
        <HintBubble hint={HINTS['wf-name-edit']} />
      {:else if executionStatus === 'running'}
        <HintBubble hint={HINTS['wf-execution-running']} />
      {:else if executionStatus === 'completed'}
        <HintBubble hint={HINTS['wf-execution-done']} />
      {/if}
    </div>
    <div class="graph-container">
      {#if $workflowView === 'canvas'}
        <div class="canvas-toolbar-wrap">
          <CanvasToolbar
            zoom={canvasRef?.getZoom?.() ?? 1}
            view={$workflowView}
            onZoomIn={() => canvasRef?.zoomIn?.()}
            onZoomOut={() => canvasRef?.zoomOut?.()}
            onFitAll={() => canvasRef?.fitAll?.()}
            onResetLayout={() => canvasRef?.resetLayout?.()}
            onToggleView={() => workflowView.set($workflowView === 'canvas' ? 'simple' : 'canvas')}
          />
        </div>
        <WorkflowCanvas
          bind:this={canvasRef}
          steps={workflow.workflow_steps}
          onStepClick={handleStepClick}
          onRemoveStep={(id) => handleRemoveStep(id)}
        />
      {:else}
        <div class="view-toggle">
          <button class="toggle-btn" onclick={() => workflowView.set('canvas')} title="Canvas View">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M5 8v2a4 4 0 0 0 4 4h2m8-6v2a4 4 0 0 1-4 4h-2"/></svg>
          </button>
        </div>
        <WorkflowGraph
          steps={workflow.workflow_steps}
          {cabinets}
          onStepClick={handleStepClick}
          onAddStep={handleAddStep}
          onRemoveStep={handleRemoveStep}
          isRoot={true}
        />
      {/if}
    </div>
  {:else}
    <div class="empty">
      <p>Workflow пуст</p>
      <p class="empty-hint">Добавьте первый шаг - выберите кабинет, который начнёт работу</p>
      <button class="add-first-btn" onclick={() => handleAddStep(null)}>+ Добавить первый шаг</button>
    </div>
  {/if}
</div>

<!-- Add Step Modal -->
<svelte:window onkeydown={(e) => { if (e.key === 'Escape' && showAddModal) showAddModal = false; }} />

{#if showAddModal}
  <div class="modal-overlay" onclick={() => showAddModal = false} role="button" tabindex="-1" onkeydown={(e) => e.key === 'Escape' && (showAddModal = false)}>
    <div class="modal" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Добавить шаг" tabindex="0">
      <h3 class="modal-title">Добавить шаг</h3>
      {#if getSuggestedCabinets().length > 0}
        <div class="suggested-label">Рекомендуемые</div>
        <div class="cabinet-grid">
          {#each cabinets.filter(c => getSuggestedCabinets().includes(c.id)) as cab}
            <button class="cabinet-option cabinet-option--suggested" onclick={() => addStep(cab.id, cab.name)}>
              <span class="cabinet-option-icon">{cab.icon}</span>
              <span class="cabinet-option-name">{cab.name}</span>
              <span class="suggested-badge"><Star size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /></span>
            </button>
          {/each}
        </div>
        <div class="suggested-label" style="margin-top: 12px">Все кабинеты</div>
      {/if}
      <div class="cabinet-grid">
        {#each cabinets as cab}
          <button class="cabinet-option" onclick={() => addStep(cab.id, cab.name)}>
            <span class="cabinet-option-icon">{cab.icon}</span>
            <span class="cabinet-option-name">{cab.name}</span>
          </button>
        {/each}
      </div>
    </div>
  </div>
{/if}

<!-- PSY-4: Celebration Overlay -->
{#if showCelebration && celebrationData}
  <div class="celebration-overlay" onclick={() => showCelebration = false} role="button" tabindex="-1" onkeydown={(e) => e.key === 'Escape' && (showCelebration = false)}>
    <div class="celebration-card" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Workflow завершён" tabindex="0">
      <div class="celebration-confetti">
        {#each Array(12) as _, i}
          <span class="confetti-piece" style="--delay: {i * 0.12}s; --x: {(i * 37) % 100}%; --hue: {(i * 30) % 360}"></span>
        {/each}
      </div>

      <div class="celebration-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
          <polyline points="22 4 12 14.01 9 11.01"/>
        </svg>
      </div>

      <h2 class="celebration-title">Workflow завершён!</h2>
      <p class="celebration-subtitle">{workflow?.name || 'Workflow'}</p>

      <div class="celebration-stats">
        <div class="stat-item">
          <span class="stat-value">{celebrationData.stepCount}</span>
          <span class="stat-label">{pluralRu(celebrationData.stepCount, 'шаг', 'шага', 'шагов')}</span>
        </div>
        <div class="stat-divider"></div>
        <div class="stat-item">
          <span class="stat-value">{celebrationData.timeSec < 60 ? `${celebrationData.timeSec}с` : `${Math.floor(celebrationData.timeSec / 60)}м ${celebrationData.timeSec % 60}с`}</span>
          <span class="stat-label">выполнение</span>
        </div>
        <div class="stat-divider"></div>
        <div class="stat-item stat-item--accent">
          <span class="stat-value">{celebrationData.savedHours}</span>
          <span class="stat-label">сэкономлено</span>
        </div>
      </div>

      <p class="celebration-efficiency">Эффективность: {celebrationData.efficiency} экономии времени</p>

      <div class="celebration-actions">
        <button class="celebration-btn celebration-btn--secondary" onclick={() => showCelebration = false}>
          Закрыть
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .editor {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  .editor-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 24px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.05));
    position: sticky;
    top: 0;
    z-index: 10;
    background: var(--bg-primary);
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
    flex-shrink: 0;
  }

  .back-btn:hover {
    border-color: var(--accent-primary);
    color: var(--accent-primary);
  }

  .name-display {
    font-size: 16px;
    font-weight: 600;
    background: transparent;
    border: none;
    color: var(--text-primary);
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 6px;
    transition: background 0.15s;
  }

  .name-display:hover {
    background: var(--hover-bg);
  }

  .name-input {
    font-size: 16px;
    font-weight: 600;
    background: var(--hover-bg);
    border: 1px solid var(--accent-primary);
    color: var(--text-primary);
    padding: 4px 8px;
    border-radius: 6px;
    outline: none;
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

  .save-btn {
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 500;
    background: var(--accent-primary);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: opacity 0.15s;
  }

  .save-btn:hover {
    opacity: 0.85;
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

  .save-indicator {
    font-size: 11px;
    color: var(--text-muted);
    flex-shrink: 0;
  }

  .save-indicator--done {
    color: var(--success);
  }

  .empty-hint {
    font-size: 12px;
    color: var(--text-muted);
    max-width: 300px;
    text-align: center;
    line-height: 1.4;
  }

  .graph-container {
    flex: 1;
    padding: 32px 24px;
    overflow-y: auto;
    display: flex;
    justify-content: center;
    position: relative;
  }

  .canvas-toolbar-wrap {
    position: absolute;
    top: 12px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10;
  }

  .view-toggle {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 5;
  }

  .toggle-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--hover-bg);
    color: var(--text-secondary, #aaa);
    cursor: pointer;
  }

  .toggle-btn:hover {
    background: var(--accent-glow);
    color: var(--text-primary, #fff);
  }

  .hints-area {
    padding: 0 24px;
    max-width: 500px;
    margin: 0 auto;
  }

  .loading, .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    font-size: 14px;
    gap: 12px;
  }

  .add-first-btn {
    padding: 8px 20px;
    font-size: 13px;
    border: 1px dashed var(--border);
    background: transparent;
    color: var(--text-secondary);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.15s;
  }

  .add-first-btn:hover {
    border-color: var(--accent-primary);
    color: var(--accent-primary);
  }

  /* ── Modal ── */

  .modal-overlay {
    position: fixed;
    inset: 0;
    background: var(--overlay-bg);
    backdrop-filter: var(--blur-quiet);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }

  .modal {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-xl);
    padding: 24px;
    max-width: 480px;
    width: 90%;
    box-shadow: var(--shadow-glow);
  }

  .modal-title {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 16px;
  }

  .cabinet-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }

  .cabinet-option {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    cursor: pointer;
    text-align: left;
    transition: all 0.15s;
    font-size: 13px;
  }

  .cabinet-option:hover {
    border-color: var(--accent-primary);
    background: var(--hover-bg);
  }

  .cabinet-option--suggested {
    border-color: var(--accent-glow-strong);
    background: var(--hover-bg);
    position: relative;
  }

  .cabinet-option-icon {
    font-size: 18px;
  }

  .cabinet-option-name {
    font-weight: 500;
  }

  .suggested-badge {
    color: var(--accent-primary);
    font-size: 10px;
    margin-left: auto;
  }

  .suggested-label {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
  }

  /* ── Run / Cancel buttons ── */

  .run-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 500;
    background: var(--success);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: opacity 0.15s;
  }

  .run-btn:hover { opacity: 0.85; }
  .run-btn:disabled { opacity: 0.4; cursor: default; }

  .export-btn {
    padding: 6px 14px;
    background: color-mix(in srgb, var(--success) 15%, transparent);
    color: var(--success);
    border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.8rem;
    font-weight: 500;
  }
  .export-btn:hover { background: color-mix(in srgb, var(--success) 25%, transparent); }
  .export-btn:disabled { opacity: 0.4; cursor: default; }

  /* ── Brief panel ── */

  .brief-panel {
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }

  .brief-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 24px;
    width: 100%;
    background: none;
    border: none;
    color: var(--text-secondary, #aaa);
    font-size: 0.8rem;
    cursor: pointer;
    text-align: left;
    font-family: inherit;
  }
  .brief-toggle:hover { color: var(--text-primary); background: var(--hover-bg); }

  .brief-content {
    padding: 0 24px 16px;
    position: relative;
  }

  .brief-textarea {
    width: 100%;
    padding: 10px 12px;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-primary, #fff);
    font-size: 0.85rem;
    font-family: inherit;
    outline: none;
    resize: vertical;
  }
  .brief-textarea:focus { border-color: var(--brand-gradient-start); }

  .brief-saving {
    position: absolute;
    right: 32px;
    bottom: 24px;
    font-size: 0.7rem;
    color: var(--text-tertiary, #888);
  }

  .cancel-btn {
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 500;
    background: var(--danger);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: opacity 0.15s;
  }

  .cancel-btn:hover { opacity: 0.85; }

  /* ── Suggestion banner ── */

  .suggestion-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    font-size: 12px;
    color: var(--warning);
    background: color-mix(in srgb, var(--warning) 6%, transparent);
    border-bottom: 1px solid color-mix(in srgb, var(--warning) 15%, transparent);
  }

  /* ── Execution status bar ── */

  .exec-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 500;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.05));
  }

  .exec-running { color: var(--accent-primary); background: var(--hover-bg); }
  .exec-done { color: var(--success); background: color-mix(in srgb, var(--success) 5%, transparent); }
  .exec-error { color: var(--danger); background: color-mix(in srgb, var(--danger) 5%, transparent); }

  .exec-spinner {
    width: 12px;
    height: 12px;
    border: 2px solid var(--accent-glow-strong);
    border-top-color: var(--accent-primary);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ── PSY-4: Celebration Overlay ── */
  .celebration-overlay {
    position: fixed;
    inset: 0;
    background: var(--overlay-bg);
    backdrop-filter: var(--blur-quiet);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 200;
    animation: fadeIn 0.3s ease;
  }

  .celebration-card {
    position: relative;
    background: var(--bg-secondary);
    border: 1px solid color-mix(in srgb, var(--success) 20%, transparent);
    border-radius: 20px;
    padding: 40px 48px;
    max-width: 420px;
    width: 90%;
    text-align: center;
    box-shadow: var(--shadow-glow);
    overflow: hidden;
    animation: celebrationSlideUp 0.4s ease;
  }

  @keyframes celebrationSlideUp {
    from { opacity: 0; transform: translateY(30px) scale(0.95); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .celebration-confetti {
    position: absolute;
    inset: 0;
    pointer-events: none;
    overflow: hidden;
  }

  .confetti-piece {
    position: absolute;
    top: -10px;
    left: var(--x);
    width: 8px;
    height: 8px;
    background: hsl(var(--hue), 80%, 65%);
    border-radius: 2px;
    animation: confettiFall 2s var(--delay) ease-out forwards;
    opacity: 0;
  }

  @keyframes confettiFall {
    0% { opacity: 1; transform: translateY(0) rotate(0deg); }
    100% { opacity: 0; transform: translateY(350px) rotate(720deg); }
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  .celebration-icon {
    margin-bottom: 16px;
    animation: celebrationPop 0.5s 0.2s ease both;
  }

  @keyframes celebrationPop {
    0% { transform: scale(0); }
    60% { transform: scale(1.15); }
    100% { transform: scale(1); }
  }

  .celebration-title {
    font-size: 22px;
    font-weight: 700;
    color: var(--success);
    margin: 0 0 4px;
  }

  .celebration-subtitle {
    font-size: 14px;
    color: var(--text-muted);
    margin: 0 0 24px;
  }

  .celebration-stats {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 20px;
    margin-bottom: 16px;
  }

  .stat-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }

  .stat-value {
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
  }

  .stat-item--accent .stat-value {
    color: var(--accent-secondary);
  }

  .stat-label {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .stat-divider {
    width: 1px;
    height: 32px;
    background: var(--border);
  }

  .celebration-efficiency {
    font-size: 12px;
    color: var(--text-secondary);
    margin: 0 0 24px;
    padding: 8px 16px;
    background: color-mix(in srgb, var(--accent-secondary) 6%, transparent);
    border-radius: 8px;
    border: 1px solid color-mix(in srgb, var(--accent-secondary) 10%, transparent);
  }

  .celebration-actions {
    display: flex;
    gap: 10px;
    justify-content: center;
  }

  .celebration-btn {
    padding: 10px 24px;
    font-size: 13px;
    font-weight: 500;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.15s;
  }

  .celebration-btn--secondary {
    background: var(--hover-bg);
    color: var(--text-secondary);
    border: 1px solid var(--border);
  }

  .celebration-btn--secondary:hover {
    background: var(--border);
    color: var(--text-primary);
  }

  /* v2.1.0 п.5.6: hide confetti + static celebration state */
  @media (prefers-reduced-motion: reduce) {
    .confetti-piece {
      display: none;
    }
    .celebration-overlay {
      opacity: 1;
    }
    .celebration-icon {
      transform: scale(1);
    }
  }
</style>
