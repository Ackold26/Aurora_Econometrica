<script>
  /**
   * ValidateStep - Step 1 of the pipeline.
   * Runs econ_validate on the imported file, then shows:
   *   - TrafficLight for validation status / issues
   *   - ColumnMapper for role assignment (drag-drop)
   *   - CorrelationHeatmap for multicollinearity analysis
   *
   * Calls completeStep(1) when status is 'ok' or 'warning'.
   * Reads importData store to get the file path.
   *
   * @component ValidateStep
   */
  import { onMount } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import ColumnMapper from '$lib/components/pipeline/ColumnMapper.svelte';
  import TrafficLight from '$lib/components/pipeline/TrafficLight.svelte';
  import CorrelationHeatmap from '$lib/components/pipeline/CorrelationHeatmap.svelte';
  import ObjectiveSelector from '$lib/components/pipeline/ObjectiveSelector.svelte';
  import {
    importData, validateData, completeStep, setStepError,
    activeProjectId, expertMode, analysisObjective,
    analysisObjectiveLegacyShim,
    syncChannelCategoriesToMedia,
  } from '$lib/project-state.js';
  import { applyObjectiveToColumns, describeObjective, recomputeResultAfterObjective } from '$lib/objective-engine.js';
  import { setColumnRole, applyMapping, buildProjectUpdates, restoreExcludedColumns, isExcluded } from '$lib/column-roles.js';
  import ExpertValidatePanel from '$lib/components/pipeline/ExpertValidatePanel.svelte';
  import UnitCostsPanel from '$lib/components/pipeline/UnitCostsPanel.svelte';
  import ChannelCategoriesPanel from '$lib/components/pipeline/ChannelCategoriesPanel.svelte';
  import PipelineOnboarding from '$lib/components/pipeline/PipelineOnboarding.svelte';
  import { TOURS } from '$lib/pipeline-tours.js';
  import { shouldShowOnboarding } from '$lib/onboarding-state.js';
  import { get } from 'svelte/store';

  // Обучающий тур - запускается при первом визите на шаг, если
  // результат валидации отрендерен и тур не пройден ранее.
  let showOnboarding = $state(false);
  let onboardingChecked = false;

  // ── State ──────────────────────────────────────────
  let loading = $state(false);
  let errorMsg = $state('');

  /** @type {Set<string>} Dismissed/applied warning keys */
  let appliedFixes = $state(new Set());
  let showValidation = $state(true);
  let showRecs = $state(true);
  let showMapper = $state(true);

  // Reactively read from store - updates when InsightsPanel modifies column roles
  const result = $derived($validateData?.result ?? null);

  // ── Reactive store reads (Svelte 5 auto-subscribe) ─
  let hasFile = $derived(!!$importData?.file);

  // Recalculate stats based on current column roles (after insight actions)
  const activeMediaCount = $derived(result?.columns?.filter(/** @param {any} c */ c => c.role === 'media').length ?? 0);
  const excludedCount = $derived(result?.columns?.filter(/** @param {any} c */ c => c.role === 'unused').length ?? 0);

  // Columns currently excluded (role=unused) - for filtering warnings
  const excludedColumns = $derived(
    new Set((result?.columns ?? []).filter(/** @param {any} c */ c => c.role === 'unused').map(/** @param {any} c */ c => c.name))
  );

  // Warnings filtered: hide warnings for excluded columns
  const activeWarnings = $derived(
    (result?.warnings ?? []).filter(/** @param {any} w */ w => {
      if (!w.column) return true; // general warning, always show
      return !excludedColumns.has(w.column);
    })
  );

  let statusLabel = $derived.by(() => {
    if (!result) return '';
    if (activeWarnings.length === 0 && result.status !== 'error') return 'Валидация пройдена';
    if (result.status === 'error') return 'Обнаружены критические проблемы';
    return `Готово с предупреждениями (${activeWarnings.length})`;
  });

  // Key validation metrics - теперь в StepWrapper sticky header
  // (через derived store validationHeaderMetrics в project-state.js).
  // Здесь больше не дублируем расчёт.

  // Онбординг - запускается на mount даже без result: первый шаг тура
  // (selector=null) объясняет что ждёт на шаге; последующие шаги
  // querySelector'ят DOM - если target не найден, карточка центрируется.
  onMount(() => {
    if (typeof window === 'undefined') return;
    if (onboardingChecked) return;
    onboardingChecked = true;
    if (shouldShowOnboarding('validate')) {
      // 2 кадра чтобы ObjectiveSelector overlay успел смонтироваться
      requestAnimationFrame(() => {
        requestAnimationFrame(() => { showOnboarding = true; });
      });
    }
  });

  // ── Validate ───────────────────────────────────────
  /** @param {{ skipAutoRole?: boolean }} [opts] */
  async function runValidate(opts) {
    const imp = get(importData);
    if (!imp.file) {
      errorMsg = 'Сначала загрузите файл на шаге Импорт';
      return;
    }

    loading = true;
    errorMsg = '';
    appliedFixes = new Set();

    try {
      const projectId = get(activeProjectId);

      /** @type {any} */
      const res = await invoke('econ_validate', {
        filePath: imp.file,
        projectDir: projectId || null,
      });

      // Hard error (file not found, parse failure)
      if (res.status === 'error' && !res.columns) {
        errorMsg = res.message ?? 'Ошибка валидации';
        setStepError(1, errorMsg);
        return;
      }

      // Apply objective-based role filter (unless skipped)
      if (!opts?.skipAutoRole) {
        const obj = get(analysisObjective);
        const applied = applyObjectiveToColumns(res.columns ?? [], obj);
        res.columns = applied.columns;
        res.objective_applied = { objective: obj, excluded: applied.excluded, kept: applied.kept };
        // Recompute issues/status/verdict/ratio to reflect new role distribution
        recomputeResultAfterObjective(res);
      }

      // L1 (math-fix v1.4 Section C, 2026-04-29): restore explicit excluded set
      // from project.json - preserves user's «не использовать» decision across
      // re-validation. Auto-detected roles (validator) могут вернуть «media»
      // для канала который user explicitly excluded; explicit set is authoritative.
      if (projectId) {
        try {
          /** @type {any} */
          const project = await invoke('project_get', { projectId });
          if (project?.excluded_columns && Array.isArray(project.excluded_columns) && project.excluded_columns.length > 0) {
            res.columns = restoreExcludedColumns(res.columns ?? [], project.excluded_columns);
            recomputeResultAfterObjective(res);
          }
        } catch { /* best-effort - fresh project may not exist yet */ }
      }

      validateData.set({
        result: res,
        correlationMatrix: res.full_correlation_matrix ?? null,
        columnHistograms: null,
      });

      // Auto-complete if no critical issues
      if (res.status !== 'error') {
        completeStep(1);
      }
    } catch (e) {
      errorMsg = `Ошибка: ${e}`;
      setStepError(1, String(e));
    } finally {
      loading = false;
    }
  }

  /**
   * Objective selected from the overlay → set store and kick off validation.
   * @param {'roi' | 'effectiveness' | 'manual'} obj
   */
  function onObjectiveChosen(obj) {
    analysisObjectiveLegacyShim.set(obj);  // v2.0.0: routes к analysisMode store
    runValidate();
  }

  /**
   * Segmented control click - switch objective AFTER validation has run.
   * Re-runs validation from scratch so that columns excluded by the previous
   * objective are restored before the new objective is applied.
   * (Re-applying in-place didn't work because applyObjectiveToColumns only
   * sees columns with role='media' - after ROI, only budgets remain as media,
   * so a switch to 'effectiveness' would find no pairs to rearrange.)
   * @param {'roi' | 'effectiveness' | 'manual'} obj
   */
  function switchObjective(obj) {
    if (get(analysisObjective) === obj) return;
    analysisObjectiveLegacyShim.set(obj);  // v2.0.0: routes к analysisMode store
    runValidate();  // re-invoke Python validator → fresh columns → apply new objective
  }

  /** L1 (math-fix v1.4 Section C, 2026-04-29): unified persistence helper.
   *  Same call site как InsightsPanel.persistColumnRoles - single source of
   *  truth для what's saved к project.json (включая explicit excluded_columns).
   *  @param {any[]} columns */
  function persistColumnRoles(columns) {
    const projectId = get(activeProjectId);
    if (!projectId || !columns) return;
    const updates = buildProjectUpdates(columns);
    // Trust Level 3 (v1.1.0): cleanup orphaned channel_categories store entries.
    // Backend project.rs cleanup'ит project.json, но UI store должен sync immediately
    // чтобы ChannelCategoriesPanel badges не показывали удалённые каналы.
    syncChannelCategoriesToMedia(updates.media_columns);
    invoke('project_update', { projectId, updates }).catch(() => { /* best-effort */ });
  }

  /**
   * Перевести колонку в роль 'unused' (исключить из матрицы) на основе action
   * из warning. L1 refactor: использует setColumnRole shared helper для
   * vocabulary consistency с другими mutator paths.
   * @param {string} columnName
   */
  function excludeColumnByName(columnName) {
    const data = get(validateData);
    if (!data?.result?.columns || !columnName) return;
    const updatedCols = setColumnRole(data.result.columns, columnName, 'unused');
    const updatedResult = { ...data.result, columns: updatedCols };
    recomputeResultAfterObjective(updatedResult);
    validateData.set({ ...data, result: updatedResult });
    persistColumnRoles(updatedCols);
  }

  /** L1 refactor: ColumnMapper drag-drop / click → applyMapping shared helper.
   *  Pre-fix: inline duplication of mapping-to-role conversion logic.
   *  @param {any} mapping */
  function onMappingChange(mapping) {
    if (!mapping) return;
    const data = get(validateData);
    if (!data?.result?.columns || !Array.isArray(data.result.columns)) {
      // Persist mapping anyway (legacy path - no validation snapshot loaded yet)
      persistColumnRoles([
        ...(mapping.kpi ?? []).map((/** @type {string} */ n) => ({ name: n, role: 'kpi' })),
        ...(mapping.media ?? []).map((/** @type {string} */ n) => ({ name: n, role: 'media' })),
        ...(mapping.control ?? []).map((/** @type {string} */ n) => ({ name: n, role: 'control' })),
        ...(mapping.date ? [{ name: mapping.date, role: 'date' }] : []),
      ]);
      return;
    }
    // BUGFIX 2026-04-27 (preserved): ОБНОВЛЯЕМ validateData.columns[i].role
    // согласно user mapping. Безопасно благодаря парному fix в ColumnMapper:
    // $effect init использует "columns SET key" - re-init только при смене
    // column set (новый file), не при mutation roles.
    const updatedCols = applyMapping(data.result.columns, mapping);
    validateData.update(/** @param {any} d */ (d) => {
      if (!d?.result) return d;
      return { ...d, result: { ...d.result, columns: updatedCols } };
    });
    persistColumnRoles(updatedCols);
  }
</script>

<div class="validate-step">

  <!-- Objective selector overlay - shown before first validation -->
  {#if hasFile && !result && !loading}
    <ObjectiveSelector onSelect={onObjectiveChosen} />
  {:else if !hasFile}
    <div class="action-bar">
      <p class="no-file-hint">Сначала загрузите файл на шаге «Импорт»</p>
    </div>
  {:else}
    <!-- Action bar (post-validation) -->
    <div class="action-bar">
      <button
        class="run-btn"
        disabled={loading}
        onclick={() => runValidate()}
      >
        {#if loading}
          <span class="btn-spinner"></span>
          Анализирую…
        {:else}
          🔄 Перезапустить валидацию
        {/if}
      </button>

      {#if result}
        <span class="status-pill status-{result.status}">{statusLabel}</span>
      {/if}
    </div>
  {/if}

  <!-- Error -->
  {#if errorMsg}
    <div class="error-banner">⚠️ {errorMsg}</div>
  {/if}

  <!-- Objective selector: ROI / Effectiveness / Manual -->
  {#if result}
    <div class="objective-bar" role="radiogroup" aria-label="Цель анализа">
      <span class="objective-label">Цель анализа:</span>
      <div class="objective-segments">
        <button
          class="objective-seg"
          class:active={$analysisObjective === 'roi'}
          role="radio"
          aria-checked={$analysisObjective === 'roi'}
          onclick={() => switchObjective('roi')}
          title="Измеряем возврат инвестиций - оставляем бюджеты"
        >
          💰 ROI
          <span class="objective-sub">бюджеты</span>
        </button>
        <button
          class="objective-seg"
          class:active={$analysisObjective === 'effectiveness'}
          role="radio"
          aria-checked={$analysisObjective === 'effectiveness'}
          onclick={() => switchObjective('effectiveness')}
          title="Измеряем эффективность медиа - оставляем показы/клики/визиты"
        >
          📊 Эффективность
          <span class="objective-sub">показы/клики</span>
        </button>
        <button
          class="objective-seg"
          class:active={$analysisObjective === 'manual'}
          role="radio"
          aria-checked={$analysisObjective === 'manual'}
          onclick={() => switchObjective('manual')}
          title="Выбираете метрику для каждого канала вручную"
        >
          🔧 Вручную
          <span class="objective-sub">per-канал</span>
        </button>
      </div>
      {#if result.objective_applied?.excluded?.length > 0}
        <span class="objective-hint">
          {describeObjective($analysisObjective)} Исключено: {result.objective_applied.excluded.length}.
        </span>
      {:else if $analysisObjective === 'manual'}
        <span class="objective-hint">{describeObjective('manual')}</span>
      {/if}
    </div>
    <div class="results-stack">

      <!-- TrafficLight -->
      <section class="section-full" data-tour="validation-result">
        <button class="section-toggle" onclick={() => showValidation = !showValidation}>
          <span>{showValidation ? '▼' : '▶'}</span>
          <h4 class="section-title">Результат валидации</h4>
        </button>
        {#if showValidation}
          <TrafficLight
            status={activeWarnings.length === 0 && result.status !== 'error' ? 'ok' : result.status}
            verdict={result.verdict}
            issues={result.issues ?? []}
            warnings={activeWarnings}
            file={result.file ?? null}
            detected={result.detected ?? null}
            columns={result.columns ?? []}
          />
          {#if excludedCount > 0}
            <div class="excluded-badge">{excludedCount} столбц{excludedCount > 4 ? 'ов' : excludedCount > 1 ? 'а' : ''} исключен{excludedCount > 1 ? 'о' : ''} по рекомендациям</div>
          {/if}
        {/if}
      </section>

      <!-- Auto-fix suggestions -->
      {#if activeWarnings.length > 0}
        <section class="section-full" data-tour="validation-recs">
          <button class="section-toggle" onclick={() => showRecs = !showRecs}>
            <span>{showRecs ? '▼' : '▶'}</span>
            <h4 class="section-title">Рекомендации ({activeWarnings.length})</h4>
          </button>
          {#if showRecs}
          <div class="fix-list">
            {#each activeWarnings as warn}
              {#if !appliedFixes.has((warn.column ?? '') + warn.type)}
                <div class="fix-item fix-{warn.severity}">
                  <span class="fix-text">{warn.message}</span>
                  {#if warn.action === 'exclude' && warn.column}
                    <button class="fix-btn" onclick={() => {
                      excludeColumnByName(warn.column);
                      appliedFixes = new Set([...appliedFixes, (warn.column ?? '') + warn.type]);
                    }}>Исключить</button>
                  {:else if warn.action === 'merge'}
                    <button class="fix-btn" onclick={() => {
                      appliedFixes = new Set([...appliedFixes, (warn.column ?? '') + warn.type]);
                    }} title="Объединение каналов вручную через ColumnMapper">Понятно</button>
                  {:else}
                    <button class="fix-btn" onclick={() => {
                      appliedFixes = new Set([...appliedFixes, (warn.column ?? '') + warn.type]);
                    }}>Принять</button>
                  {/if}
                </div>
              {/if}
            {/each}
          </div>
          {/if}
        </section>
      {/if}

      <!-- Trust Level 2: unit_costs для не-денежных каналов -->
      <section class="section-full" data-tour="unit-costs">
        <UnitCostsPanel columns={result.columns ?? []} />
      </section>

      <!-- Trust Level 3 (v1.1.0): brand vs performance categorization -->
      <section class="section-full" data-tour="channel-categories">
        <ChannelCategoriesPanel columns={result.columns ?? []} />
      </section>

      <!-- ColumnMapper -->
      <section class="section-full" data-tour="column-mapper">
        <button class="section-toggle" onclick={() => showMapper = !showMapper}>
          <span>{showMapper ? '▼' : '▶'}</span>
          <h4 class="section-title">Назначение столбцов</h4>
        </button>
        {#if showMapper}
        <p class="section-hint">
          Нажмите на столбец → выберите роль. Или перетащите в нужную зону.
        </p>
        <ColumnMapper
          columns={result.columns ?? []}
          detected={result.detected ?? {}}
          onmappingchange={onMappingChange}
        />
        {/if}
      </section>

      <!-- Correlation heatmap -->
      {#if result.full_correlation_matrix?.labels?.length >= 2}
        <section class="section-full">
          <CorrelationHeatmap
            correlationMatrix={result.full_correlation_matrix}
            highCorrelations={result.high_correlations ?? []}
          />
        </section>
      {/if}

    </div>
  {/if}
  <!-- Idle-state removed: replaced by full-screen ObjectiveSelector overlay above -->


  {#if $expertMode}
    <ExpertValidatePanel />
  {/if}

  {#if showOnboarding}
    <PipelineOnboarding
      steps={TOURS.validate}
      stepKey="validate"
      onDone={() => { showOnboarding = false; }}
    />
  {/if}

</div>

<style>
  .validate-step {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 24px;
    height: 100%;
    box-sizing: border-box;
    overflow-y: auto;
  }

  /* ── Action bar ── */
  /* ── Objective selector (ROI / Effectiveness / Manual) ── */
  .objective-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 14px;
    background: var(--bg-surface-quiet);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-card, 12px);
    flex-shrink: 0;
    flex-wrap: wrap;
  }
  .objective-label {
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
    flex-shrink: 0;
  }
  .objective-segments {
    display: flex;
    gap: 4px;
    padding: 3px;
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-btn, 8px);
  }
  .objective-seg {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    padding: 6px 12px;
    background: transparent;
    border: none;
    border-radius: calc(var(--radius-btn, 8px) - 2px);
    color: var(--text-secondary);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  .objective-seg:hover:not(.active) {
    background: var(--hover-bg);
    color: var(--text-primary);
  }
  .objective-seg.active {
    background: color-mix(in srgb, var(--accent-primary) 15%, transparent);
    color: var(--accent-primary);
    font-weight: var(--font-weight-heading, 600);
  }
  .objective-sub {
    font-size: 11px;
    font-weight: 400;
    opacity: 0.75;
  }
  .objective-hint {
    font-size: 12px;
    color: var(--text-muted);
    margin-left: 4px;
    font-style: italic;
  }

  .action-bar {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
    flex-shrink: 0;
  }

  .no-file-hint {
    font-size: 13px;
    color: var(--text-muted);
    margin: 0;
    font-style: italic;
  }

  .run-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 20px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 10px;
    color: var(--text-on-accent, #fff);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s, transform 0.1s;
  }

  .run-btn:hover:not(:disabled) {
    background: var(--accent-hover, #2563eb);
    transform: translateY(-1px);
  }

  .run-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .btn-spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(147, 197, 253, 0.2);
    border-top-color: #93c5fd;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    flex-shrink: 0;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .status-pill {
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 20px;
  }

  /* Key metrics переехали в StepWrapper.svelte sticky header */

  .excluded-badge {
    margin-top: 8px;
    font-size: 11px;
    color: #4ade80;
    padding: 4px 10px;
    background: color-mix(in srgb, var(--success) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 20%, transparent);
    border-radius: 6px;
    display: inline-block;
  }

  .status-ok      { background: color-mix(in srgb, var(--success) 15%, transparent);  color: var(--text-primary); border: 1px solid color-mix(in srgb, var(--success) 35%, transparent); }
  .status-warning { background: color-mix(in srgb, var(--warning) 15%, transparent); color: var(--text-primary); border: 1px solid color-mix(in srgb, var(--warning) 35%, transparent); }
  .status-error   { background: color-mix(in srgb, var(--danger) 15%, transparent);  color: var(--text-primary); border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent); }

  /* ── Error ── */
  .error-banner {
    padding: 10px 16px;
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
    border-radius: 10px;
    font-size: 13px;
    color: #fca5a5;
    flex-shrink: 0;
  }

  /* ── Results grid ── */
  .results-stack {
    display: flex;
    flex-direction: column;
    gap: 12px;
    width: 100%;
  }

  .section-full {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
  }

  .section-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    background: none;
    border: none;
    cursor: pointer;
    padding: 4px 0;
    color: var(--text-secondary, #94a3b8);
  }
  .section-toggle:hover { color: var(--text-primary, #e2e8f0); }
  .section-toggle span { font-size: 10px; width: 14px; }

  .section-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin: 0;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }

  .section-hint {
    font-size: 11px;
    color: var(--text-muted);
    margin: 0;
    font-style: italic;
    line-height: 1.5;
  }

  /* ── Idle ── */
  .fix-list { display: flex; flex-direction: column; gap: 6px; }
  .fix-item {
    display: flex; align-items: center; gap: 10px; padding: 8px 12px;
    border-radius: 6px;
    background: color-mix(in srgb, var(--warning) 6%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning) 20%, transparent);
    border-left: 3px solid #f59e0b;
  }
  .fix-item.fix-critical { border-left-color: #ef4444; background: color-mix(in srgb, var(--danger) 6%, transparent); border-color: color-mix(in srgb, var(--danger) 20%, transparent); }
  .fix-text { flex: 1; font-size: 12px; color: var(--text-primary, #e2e8f0); line-height: 1.4; }
  .fix-btn {
    padding: 6px 16px;
    border-radius: var(--radius-btn, 6px);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 45%, transparent);
    background: color-mix(in srgb, var(--accent-primary) 18%, transparent);
    color: var(--accent-primary);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
    box-shadow: 0 1px 3px color-mix(in srgb, var(--accent-primary) 15%, transparent);
  }
  .fix-btn:hover {
    background: var(--accent-primary);
    color: #fff;
    border-color: var(--accent-primary);
    transform: translateY(-1px);
    box-shadow: 0 2px 6px color-mix(in srgb, var(--accent-primary) 30%, transparent);
  }
  .fix-item.fix-critical .fix-btn {
    border-color: color-mix(in srgb, var(--danger) 45%, transparent);
    background: color-mix(in srgb, var(--danger) 18%, transparent);
    color: var(--danger);
    box-shadow: 0 1px 3px color-mix(in srgb, var(--danger) 15%, transparent);
  }
  .fix-item.fix-critical .fix-btn:hover {
    background: var(--danger);
    color: #fff;
    border-color: var(--danger);
  }

  .idle-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 48px 32px;
    text-align: center;
    flex: 1;
  }

  .idle-icon { font-size: 48px; line-height: 1; filter: grayscale(0.4); }

  .idle-text {
    font-size: 14px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }

  .idle-hint {
    font-size: 12px;
    color: var(--text-muted);
    margin: 0;
    max-width: 380px;
    line-height: 1.6;
  }

  /* v2.1.0 п.5.6: static spinner ring */
  @media (prefers-reduced-motion: reduce) {
    .spinner {
      border-color: color-mix(in srgb, var(--accent-primary) 70%, transparent);
    }
  }
</style>
