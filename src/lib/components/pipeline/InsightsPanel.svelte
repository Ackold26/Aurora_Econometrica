<script>
  /**
   * InsightsPanel - Rule-based insights sidebar for the pipeline.
   * Tier 1: offline insights from insights-rules.js (always works).
   * Tier 2: Claude AI (online, optional) - Phase 10.
   * C4: width clamp(240px, 22%, 360px), auto-collapse below 1100px.
   */
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import { get } from 'svelte/store';
  import { Check } from 'lucide-svelte';
  import {
    pipelineCurrentStep, activeProjectId,
    importData, validateData, modelData, decomposeData, optimizeData, optimizeLiveState,
    analysisObjective, completeStep, setStepError,
    kpiKind, derivedMode, valuePerCountUnit,
  } from '$lib/project-state.js';
  import { kpiView as buildKpiView } from '$lib/kpi-aware-formatting.js';
  import { recomputeResultAfterObjective } from '$lib/objective-engine.js';
  import { setColumnRolesBulk, buildProjectUpdates } from '$lib/column-roles.js';

  /** Persist column-role state к project.json (best-effort, non-blocking).
   *  L1 (math-fix v1.4 Section C, 2026-04-29): unified persistence - same call
   *  used by InsightsPanel.applyAction, ValidateStep.excludeColumnByName,
   *  ValidateStep.onMappingChange. Adds explicit excluded_columns list для
   *  cross-session restore.
   *  @param {any[]} columns */
  function persistColumnRoles(columns) {
    const projectId = get(activeProjectId);
    if (!projectId || !columns) return;
    const updates = buildProjectUpdates(columns);
    invoke('project_update', { projectId, updates }).catch(() => { /* best-effort */ });
  }
  import {
    importInsights, validateInsights, modelInsights, modelPreTrainingInsights, decomposeInsights, optimizeInsights, reportInsights,
    // v2.1.0 (rc2 U-05): функции по под-шагам Валидации.
    validateKpiInsights, validateRolesInsights, validateMetricsInsights, validateConfirmInsights,
  } from '$lib/insights-rules.js';
  // v2.1.0 (rc2 U-05): subStep store для контекстной маршрутизации.
  import { validateSubStep, analysisMode, perChannelInput, unitCosts, unitCostInputMode, budgetInputs, modelEnabledMediaNames, validationHeaderMetrics } from '$lib/project-state.js';
  // Tier 2 (Claude-усилитель инсайтов, «Phase 10»). Видим только в облачной
  // редакции с согласием и для продукта Econometrica.
  import { isEconometrica } from '$lib/creative-store.js';
  import { cloudConsent } from '$lib/store.js';
  import { buildTier2Context, buildTier2Prompt } from '$lib/tier2-context.js';
  import { findUngroundedNumbers } from '$lib/insights-grounding.js';

  /** @type {{ collapsed?: boolean, onToggle?: () => void }} */
  let { collapsed = false, onToggle } = $props();

  /**
   * Snapshot of what was done - enables undo.
   * Keyed by insight index; stores roles prior to apply + merge metadata.
   * @type {Map<number, { previousRoles: Record<string, string>, mergedName?: string }>}
   */
  let appliedActions = $state(new Map());

  /** Apply an insight action: modify column roles in validateData
   * @param {import('$lib/insights-rules.js').InsightAction} action
   * @param {number} idx
   */
  function applyAction(action, idx) {
    const val = $validateData;
    if (!val?.result?.columns) return;

    // L1 (math-fix v1.4 Section C, 2026-04-29): use shared setColumnRolesBulk
    // helper для consistent vocabulary с ColumnMapper drag-drop and
    // ValidateStep.excludeColumnByName. Single source of truth → no drift
    // между mutator paths (vocabulary, persistence, undo capture).
    /** @type {Record<string, string>} */
    const previousRoles = {};
    /** @type {string | undefined} */
    let mergedName;

    // Capture previous roles for undo BEFORE mutation
    const captureNames = action.type === 'keep_only' ? (action.exclude ?? []) : (action.columns ?? []);
    for (const col of val.result.columns) {
      if (captureNames.includes(col.name)) {
        previousRoles[col.name] = col.role || 'unknown';
      }
    }

    let nextColumns = val.result.columns;

    if (action.type === 'exclude') {
      nextColumns = setColumnRolesBulk(nextColumns, action.columns, 'unused');
    } else if (action.type === 'keep_only') {
      nextColumns = setColumnRolesBulk(nextColumns, action.exclude ?? [], 'unused');
    } else if (action.type === 'set_role') {
      nextColumns = setColumnRolesBulk(nextColumns, action.columns, 'kpi');
    } else if (action.type === 'merge') {
      // Audit fix (2026-04-29): detect name collision when customer creates
      // multiple merge actions с одинаковым default name «Объединённый канал».
      // Pre-fix: silent duplicate column entries → downstream lookups by name
      // hit first match, second merge effectively orphaned. Post-fix: auto-suffix
      // (Объединённый канал, Объединённый канал 2, Объединённый канал 3, ...).
      const baseName = action.mergedName || 'Объединённый канал';
      let candidateName = baseName;
      let suffix = 2;
      const existingNames = new Set(nextColumns.map(/** @param {any} c */ (c) => c.name));
      while (existingNames.has(candidateName)) {
        candidateName = `${baseName} ${suffix}`;
        suffix += 1;
      }
      mergedName = candidateName;
      const mergedCols = nextColumns.filter(/** @param {any} c */ (c) => action.columns.includes(c.name));
      const totalMean = mergedCols.reduce(/** @param {number} s @param {any} c */ (s, c) => s + (c.stats?.mean ?? 0), 0);
      const minZeros = Math.min(...mergedCols.map(/** @param {any} c */ (c) => c.stats?.zeros_pct ?? 100));
      nextColumns = setColumnRolesBulk(nextColumns, action.columns, 'unused');
      nextColumns = [...nextColumns, {
        name: mergedName,
        role: 'media',
        dtype: 'float64',
        confidence: 0.9,
        merged_from: [...action.columns],
        stats: { mean: totalMean, zeros_pct: minZeros, missing_pct: 0, min: 0, max: 0 },
      }];
    }

    const updated = { ...val, result: { ...val.result, columns: nextColumns } };
    recomputeResultAfterObjective(updated.result);
    syncStepLockAfterValidate(updated.result);
    validateData.set(updated);
    persistColumnRoles(updated.result.columns);

    const nextMap = new Map(appliedActions);
    nextMap.set(idx, { previousRoles, mergedName });
    appliedActions = nextMap;
  }

  /**
   * Undo an applied action - restore roles, remove merged column.
   * @param {number} idx
   */
  function revertAction(idx) {
    const snapshot = appliedActions.get(idx);
    if (!snapshot) return;
    const val = $validateData;
    if (!val?.result?.columns) return;

    const updated = { ...val, result: { ...val.result, columns: val.result.columns.map(/** @param {any} c */ c => ({ ...c })) } };

    // Restore previous roles
    for (const col of updated.result.columns) {
      if (col.name in snapshot.previousRoles) {
        col.role = snapshot.previousRoles[col.name];
      }
    }

    // Remove virtual merged column if this was a merge action
    if (snapshot.mergedName) {
      updated.result.columns = updated.result.columns.filter(/** @param {any} c */ c => c.name !== snapshot.mergedName);
    }

    recomputeResultAfterObjective(updated.result);
    syncStepLockAfterValidate(updated.result);
    validateData.set(updated);
    persistColumnRoles(updated.result.columns);
    const nextMap = new Map(appliedActions);
    nextMap.delete(idx);
    appliedActions = nextMap;
  }

  // v2.1.0 (rc2 retry): реактивный sync step-lock при ЛЮБОМ изменении
  // validateData (не только через insight actions). Раньше status menue
  // через UI-таблицу ColumnMapperConfirm не триггерил sync → header
  // показывал stale «Критические проблемы».
  $effect(() => {
    const result = $validateData?.result;
    if (!result) return;
    if ($pipelineCurrentStep !== 1) return;
    syncStepLockAfterValidate(result);
  });

  /**
   * Sync pipeline step-lock state with current validation result.
   * Called after any action that recomputes status (apply/revert).
   * If status becomes ok/warning → step 1 complete, step 2 ready (unlocks "Далее").
   * If status becomes error → step 1 error, step 2 locked.
   * @param {any} result
   */
  function syncStepLockAfterValidate(result) {
    if (!result) return;
    // Only sync if we're actually ON the validation step
    const step = $pipelineCurrentStep;
    if (step !== 1) return;
    // v2.1.0 (rc2 retry): пересчитываем effective status из current ролей
    // колонок (не stale result.status). Согласовано с validateInsights.
    const cols = Array.isArray(result.columns) ? result.columns : [];
    const kpiCount = cols.filter(/** @param {any} c */ c => c?.role === 'kpi').length;
    const mediaCount = cols.filter(/** @param {any} c */ c => c?.role === 'media').length;
    const controlCount = cols.filter(/** @param {any} c */ c => c?.role === 'control').length;
    const rows = result.file?.rows ?? result.detected?.rows ?? 0;
    const paramCount = mediaCount + controlCount;
    const liveRatio = rows > 0 && paramCount > 0 ? rows / paramCount : 0;

    // F-001 guard (pilot 2026-05-18): «2 KPI» error показывать только на
    // sub-step «Роли колонок» (-1) и позже - не на sub-step «Целевая метрика» (-2).
    // На -2 роли ещё не назначались пользователем; auto-detected result может
    // иметь 2 KPI cols - это нормально до шага Roles.
    const subStep = get(validateSubStep);
    const rolesVisible = subStep >= -1;

    let errorMsg = null;
    if (kpiCount === 0) errorMsg = 'Не выбрана целевая метрика';
    else if (kpiCount > 1 && rolesVisible) errorMsg = `Выбрано ${kpiCount} целевых метрик (нужна одна)`;
    else if (mediaCount === 0) errorMsg = 'Нет медиа-каналов';
    // SEV-1 (2026-06-02, поймано live-GUI): error/«Ошибка» шага только при ratio < 1
    // (df ≤ 0, модель не определяется - переменных ≥ наблюдений). При 1 ≤ ratio < 2
    // модель идентифицируема (директивно, приемлемо для пилота) - не «Ошибка»;
    // предупреждение «Критически мало» показывает RatioInfoCard. Согласовано с
    // ratio-classifier.js + insights-rules.js (порог DEGENERATE=1).
    else if (liveRatio > 0 && liveRatio < 1) errorMsg = `Ratio ${liveRatio.toFixed(1)}:1 - модель не определяется (переменных больше, чем точек данных)`;

    if (errorMsg) {
      setStepError(1, errorMsg);
    } else {
      // NAV-2/3A-FOOTER-BYPASS fix part 2 (Вариант B, 2026-06-04): НЕ разлочиваем Модель
      // здесь. Этот $effect срабатывает при ЛЮБОЙ чистой валидации (KPI+медиа+ratio≥1) на
      // шаге Валидация — раньше `completeStep(1)` разлочивал Модель сразу после подтверждения
      // ролей (subStep→2), до CPP-гейта и подшага «Подтверждение» → футер goNext перескакивал
      // на Модель с физ.каналами без unit_cost (ROI-артефакт). Параллельный источник к
      // autoRunValidate (закрыт там же). Теперь: только СНЯТЬ ошибку (если была) — разлок
      // Модели исключительно в ValidateStepV13.handlePerChannelConfirm (за CPP-гейтом).
      setStepError(1, null);
    }
  }

  // Severity icons and colors
  const SEVERITY = /** @type {const} */ ({
    info:    { icon: 'i',  cls: 'sev-info' },
    success: { icon: '\u2713', cls: 'sev-success' },
    warning: { icon: '!',  cls: 'sev-warning' },
    error:   { icon: '\u2717', cls: 'sev-error' },
  });

  /** @type {import('$lib/insights-rules.js').Insight[]} */
  const insights = $derived.by(() => {
    const step = $pipelineCurrentStep;
    const imp = $importData;
    const val = $validateData;
    const mod = $modelData;
    const dec = $decomposeData;
    const opt = $optimizeData;
    const live = $optimizeLiveState;
    const objective = $analysisObjective; // ensure reactive subscription
    // v1.3.2: KPI/mode view derived from project-state stores → passed to
    // insights functions для CPU/Доля labels вместо ROI/mROAS.
    const kpi = buildKpiView({
      kpiKind: $kpiKind,
      derivedMode: $derivedMode,
      valuePerCountUnit: $valuePerCountUnit,
    });

    switch (step) {
      case 0: {
        if (!imp?.file) return [];
        const cols = imp.columns ?? [];
        const totalRows = imp.shape?.rows ?? imp.rows?.length ?? 0;
        const zeros = /** @type {Record<string, number>} */ ({});
        for (const c of cols) {
          if (c.stats?.zeros_pct > 0) zeros[c.name] = c.stats.zeros_pct;
        }
        return importInsights({
          rows: totalRows,
          cols: imp.shape?.cols ?? cols.length,
          columns: cols,
          zeros,
          fileName: imp.fileName ?? '',
        });
      }
      case 1: {
        // v2.1.0 (rc2 U-05): контекстные инсайты по под-шагу Валидации.
        // На «1 Целевая метрика» инсайты про выбор режима/KPI (не про каналы),
        // на «2 Роли колонок» - текущая (общая) логика про каналы,
        // на «3 Метрики каналов» - подсказки конверсии для текущего режима,
        // на «4 Подтверждение» - готовность к обучению.
        const sub = $validateSubStep;
        const ctx = {
          analysisMode: $analysisMode,
          perChannelInput: $perChannelInput,
          unitCosts: $unitCosts,
          // F-007 pilot (2026-05-18): передаём mode/budget input state чтобы
          // «Все каналы готовы» insight не давал success когда юзер в budget
          // mode не ввёл сумму (UI status warning тогда корректно сигналит).
          unitCostInputMode: $unitCostInputMode,
          budgetInputs: $budgetInputs,
        };
        if (sub === -2) return validateKpiInsights(val?.result, ctx);
        if (sub === 2)  return validateMetricsInsights(val?.result, ctx);
        if (sub === 3)  return validateConfirmInsights(val?.result, ctx);
        // -1 (Роли колонок) и 0 / 1 (legacy) - общая validateInsights logic
        return validateRolesInsights(val?.result, objective);
      }
      case 2: {
        // If training hasn't produced diagnostics yet → educational/context insights.
        // v2.1.0 (пилот 2026-05-16): передаём active media каналы из ConfigPanel,
        // чтобы счётчик «10 медиаканалов» отражал реальные галочки (7), не все
        // media-роли. modelEnabledMediaNames пустой до Init шага Модель.
        if (!mod?.diagnostics) {
          const activeMedia = $modelEnabledMediaNames;
          return modelPreTrainingInsights(val?.result, activeMedia.length > 0 ? activeMedia : undefined);
        }
        // v2.1.0 (пилот 2026-05-16): передаём frontend SSOT ratio - Антон:
        // «ratio в расчёте было 3.9, на модели опять неверные ratio».
        // Backend m.ratio иногда расходится с тем что юзер видел на Валидации.
        const ssotRatio = $validationHeaderMetrics?.ratio;
        return modelInsights(mod, ssotRatio);
      }
      case 3: return decomposeInsights(dec, kpi);
      case 4: return optimizeInsights(opt, {
        dec, mod,
        channelBudgets: live.channelBudgets,
        channelMinPct: live.channelMinPct,
        channelMaxPct: live.channelMaxPct,
        globalMinPct: live.globalMinPct,
        globalMaxPct: live.globalMaxPct,
        kpi,
      });
      case 5: {
        // v2.1.0 (пилот 2026-05-17 audit C-3): передаём SSOT ratio чтобы
        // правая панель Отчёта показывала те же MQS/Ratio что плитка.
        const ssotRatio = $validationHeaderMetrics?.ratio;
        return reportInsights({ mod, dec, opt, kpi, ssotRatio });
      }
      default: return [];
    }
  });

  /** @type {number | null} */
  let expandedTip = $state(null);

  // ── Tier 2: «Спросить ИИ» (Claude-усилитель поверх детерминированных инсайтов) ──
  let askQuestion = $state('');
  let askAnswer = $state('');
  let askLoading = $state(false);
  let askError = $state('');
  /** @type {string[]} негрунд-числа из ответа (рантайм-страж INV-50) */
  let askUngrounded = $state(/** @type {string[]} */ ([]));

  // Видимость: облачная редакция + согласие дано + НЕ режим «только локально»
  // + продукт Econometrica.
  const canAsk = $derived(
    $cloudConsent.advisorsEnabled &&
      $cloudConsent.granted &&
      !$cloudConsent.localOnly &&
      $isEconometrica,
  );

  // Ответ ИИ относится к конкретному шагу пайплайна — сбрасывать при смене шага,
  // иначе пользователь видит ответ про декомпозицию на шаге оптимизации.
  $effect(() => {
    void $pipelineCurrentStep;
    askAnswer = '';
    askError = '';
    askUngrounded = [];
  });

  async function askAI() {
    if (askLoading) return;
    askError = '';
    askAnswer = '';
    askUngrounded = [];

    // Контекст текущего шага: факты модели + детерминированные Tier-1 инсайты.
    const ctx = buildTier2Context({
      step: $pipelineCurrentStep,
      tier1Insights: insights,
      val: $validateData,
      mod: $modelData,
      dec: $decomposeData,
      opt: $optimizeData,
    });
    const prompt = buildTier2Prompt(ctx, askQuestion);

    askLoading = true;
    try {
      let text;
      try {
        text = await invoke('econ_ask_insight', { prompt });
      } catch (e) {
        // Сессия кабинета эконометриста не открыта — открыть лениво и повторить.
        if (String(e).includes('ASK-NO-SESSION')) {
          await invoke('open_cabinet', { cabinetId: 'econometrist' });
          text = await invoke('econ_ask_insight', { prompt });
        } else {
          throw e;
        }
      }
      askAnswer = String(text || '').trim();
      // Рантайм-страж INV-50: числа в ответе должны быть в фактах модели.
      askUngrounded = findUngroundedNumbers(askAnswer, ctx.grounding).map((b) => b.raw);
    } catch (e) {
      const msg = String(e);
      askError = msg.includes('CONSENT')
        ? 'Нужно согласие на облачную обработку (см. настройки).'
        : msg.includes('LOCAL')
          ? 'Локальная редакция: ИИ-ассистент отключён (данные не уходят).'
          : msg.replace(/^\[?[A-Z-]+\]?\s*/, '');
    } finally {
      askLoading = false;
    }
  }

  // ── Drag-resize ──
  let panelWidth = $state(300);
  let isResizing = $state(false);

  /** @param {MouseEvent} e */
  function startResize(e) {
    if (collapsed) return;
    e.preventDefault();
    isResizing = true;
    const startX = e.clientX;
    const startW = panelWidth;

    /** @param {MouseEvent} moveEvt */
    function onMove(moveEvt) {
      const delta = startX - moveEvt.clientX;
      panelWidth = Math.max(200, Math.min(600, startW + delta));
    }
    function onUp() {
      isResizing = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }
</script>

<aside
  class="insights-panel"
  class:collapsed
  class:resizing={isResizing}
  style={collapsed ? '' : `width:${panelWidth}px`}
  aria-label="Инсайты"
>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="resize-handle" onmousedown={startResize}></div>
  <div class="panel-header">
    {#if !collapsed}
      <span class="panel-title">Инсайты</span>
      <span class="insight-count">{insights.length}</span>
    {/if}
    <button
      class="collapse-btn"
      onclick={onToggle}
      title={collapsed ? 'Развернуть' : 'Свернуть панель'}
      aria-label={collapsed ? 'Развернуть инсайты' : 'Свернуть инсайты'}
    >
      {collapsed ? '\u25C0' : '\u25B6'}
    </button>
  </div>

  {#if !collapsed}
    <div class="panel-body">
      {#if insights.length === 0}
        <p class="empty-hint">Загрузите данные для получения рекомендаций.</p>
      {:else}
        <ul class="insights-list" role="list">
          {#each insights as insight, i}
            <li class="insight-item {SEVERITY[insight.severity].cls}" role="listitem">
              <span class="sev-badge">{SEVERITY[insight.severity].icon}</span>
              <div class="insight-content">
                <span class="insight-text">{insight.text}</span>
                <div class="insight-actions-row">
                  {#if insight.tip}
                    <button
                      class="tip-toggle"
                      onclick={() => expandedTip = expandedTip === i ? null : i}
                    >
                      {expandedTip === i ? 'Скрыть' : 'Подробнее'}
                    </button>
                  {/if}
                  {#if insight.action && !appliedActions.has(i)}
                    <button
                      class="action-btn"
                      onclick={() => insight.action && applyAction(insight.action, i)}
                    >
                      {insight.action.label || 'Применить'}
                    </button>
                  {/if}
                  {#if appliedActions.has(i)}
                    <button
                      class="revert-btn"
                      onclick={() => revertAction(i)}
                      title="Отменить применённое действие"
                    >
                      <Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Применено · Отменить
                    </button>
                  {/if}
                </div>
                {#if expandedTip === i && insight.tip}
                  <p class="tip-text">{insight.tip}</p>
                {/if}
              </div>
            </li>
          {/each}
        </ul>
      {/if}

      {#if canAsk}
        <div class="ask-ai">
          <div class="ask-row">
            <input
              class="ask-input"
              type="text"
              placeholder="Спросить ИИ об этом результате…"
              bind:value={askQuestion}
              onkeydown={(e) => { if (e.key === 'Enter') askAI(); }}
              disabled={askLoading}
            />
            <button
              class="ask-btn"
              onclick={askAI}
              disabled={askLoading || insights.length === 0}
              title="Объяснит результат на основе фактов модели"
            >
              {askLoading ? '…' : 'Спросить'}
            </button>
          </div>
          {#if askError}
            <p class="ask-error">{askError}</p>
          {/if}
          {#if askAnswer}
            <div class="ask-answer">
              {#if askUngrounded.length > 0}
                <p class="ask-warn">⚠ Числа не сверены с моделью: {askUngrounded.join(', ')}</p>
              {/if}
              <p class="ask-text">{askAnswer}</p>
            </div>
          {/if}
        </div>
      {/if}

    </div>
  {/if}
</aside>

<style>
  .insights-panel {
    position: relative;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-left: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    overflow: hidden;
    flex-shrink: 0;
    transition: width 0.15s ease;
  }
  .insights-panel.resizing { transition: none; user-select: none; }
  .insights-panel.collapsed { width: 34px !important; min-width: 34px; }

  .resize-handle {
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 5px;
    cursor: col-resize;
    z-index: 20;
    background: transparent;
    transition: background 0.15s;
  }
  .resize-handle:hover,
  .resizing .resize-handle {
    background: var(--accent-primary, #3b82f6);
    opacity: 0.5;
  }
  .collapsed .resize-handle { display: none; }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 14px 12px;
    min-height: 52px;  /* match StepWrapper .step-header height (h2 + padding) */
    box-sizing: border-box;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    flex-shrink: 0;
    gap: 8px;
  }
  .panel-title {
    font-size: 11px; font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    text-transform: uppercase; letter-spacing: 0.06em;
    white-space: nowrap; flex: 1;
  }
  .insight-count {
    font-size: 10px; font-weight: 700;
    background: var(--accent-primary, #3b82f6);
    color: white; border-radius: 10px;
    padding: 1px 7px; min-width: 18px;
    text-align: center; flex-shrink: 0;
  }
  .collapse-btn {
    background: none; border: none;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer; font-size: 10px;
    padding: 3px 5px; border-radius: 4px;
    flex-shrink: 0; transition: background 0.15s; line-height: 1;
  }
  .collapse-btn:hover { background: rgba(255,255,255,0.07); }

  .panel-body {
    flex: 1; overflow-y: auto;
    display: flex; flex-direction: column;
    padding: 10px; gap: 8px; min-height: 0;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.08) transparent;
  }

  .empty-hint {
    font-size: 12px; color: var(--text-muted);
    text-align: center; padding: 20px 0; margin: 0;
  }

  .insights-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; flex: 1; }

  .insight-item {
    display: flex; gap: 8px; align-items: flex-start;
    font-size: 12px; line-height: 1.5;
    padding: 8px 10px; border-radius: var(--radius-sm, 6px);
    background: var(--bg-insight-base);
    border-left: 3px solid transparent;
    transition: background 0.2s;
  }
  .insight-item.sev-info    { border-left-color: var(--color-info, var(--accent-primary)); background: var(--bg-insight-info); }
  .insight-item.sev-success { border-left-color: var(--success); background: var(--bg-insight-success); }
  .insight-item.sev-warning { border-left-color: var(--warning); background: var(--bg-insight-warning); }
  .insight-item.sev-error   { border-left-color: var(--danger);  background: var(--bg-insight-error); }

  .sev-badge {
    width: 16px; height: 16px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 50%; font-size: 9px; font-weight: 700;
    flex-shrink: 0; margin-top: 1px;
  }
  .sev-info    .sev-badge { background: color-mix(in srgb, var(--color-info, var(--accent-primary)) 18%, transparent); color: var(--color-info, var(--accent-primary)); }
  .sev-success .sev-badge { background: color-mix(in srgb, var(--success) 18%, transparent);  color: var(--success); }
  .sev-warning .sev-badge { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
  .sev-error   .sev-badge { background: color-mix(in srgb, var(--danger) 18%, transparent);  color: var(--danger); }

  .insight-content { flex: 1; min-width: 0; }
  .insight-text { color: var(--text-secondary, #94a3b8); }

  .insight-actions-row {
    display: flex; gap: 8px; align-items: center; margin-top: 5px; flex-wrap: wrap;
  }

  .tip-toggle {
    background: none; border: none; padding: 0;
    font-size: 11px; color: var(--accent-primary, #3b82f6);
    cursor: pointer;
  }
  .tip-toggle:hover { text-decoration: underline; }

  .action-btn {
    padding: 5px 14px;
    background: var(--success);
    border: 1px solid var(--success);
    border-radius: var(--radius-chip, 5px);
    color: #fff;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    box-shadow: 0 1px 4px color-mix(in srgb, var(--success) 30%, transparent);
  }
  .action-btn:hover {
    background: color-mix(in srgb, var(--success) 85%, black);
    border-color: color-mix(in srgb, var(--success) 85%, black);
    transform: translateY(-1px);
    box-shadow: 0 3px 8px color-mix(in srgb, var(--success) 45%, transparent);
  }
  /* Error-severity actions get danger color for clarity */
  .sev-error .action-btn {
    background: var(--danger);
    border-color: var(--danger);
    box-shadow: 0 1px 4px color-mix(in srgb, var(--danger) 30%, transparent);
  }
  .sev-error .action-btn:hover {
    background: color-mix(in srgb, var(--danger) 85%, black);
    border-color: color-mix(in srgb, var(--danger) 85%, black);
    box-shadow: 0 3px 8px color-mix(in srgb, var(--danger) 45%, transparent);
  }

  .action-applied {
    font-size: 10px;
    color: var(--success);
    font-weight: 500;
  }

  .revert-btn {
    padding: 4px 10px;
    background: color-mix(in srgb, var(--success) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 36%, transparent);
    border-radius: var(--radius-chip, 5px);
    color: var(--success);
    font-size: 10px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }
  .revert-btn:hover {
    background: color-mix(in srgb, var(--warning) 18%, transparent);
    border-color: color-mix(in srgb, var(--warning) 55%, transparent);
    color: var(--warning);
  }

  .tip-text {
    font-size: 11px; color: var(--text-muted);
    line-height: 1.5; margin: 4px 0 0; padding: 6px 8px;
    background: rgba(255,255,255,0.02); border-radius: 4px;
    white-space: pre-line;
  }

  /* ── Tier 2: «Спросить ИИ» ── */
  .ask-ai {
    margin-top: 10px; padding-top: 10px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    display: flex; flex-direction: column; gap: 8px;
  }
  .ask-row { display: flex; gap: 6px; align-items: center; }
  .ask-input {
    flex: 1; min-width: 0;
    padding: 6px 9px;
    font-size: 12px; line-height: 1.4;
    color: var(--text-primary, #e2e8f0);
    background: var(--bg-surface-focus, rgba(20, 22, 30, 0.72));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: var(--radius-sm, 6px);
  }
  .ask-input:focus {
    outline: none;
    border-color: var(--accent-primary, #3b82f6);
  }
  .ask-input:disabled { opacity: 0.6; }
  .ask-btn {
    padding: 6px 12px;
    font-size: 11px; font-weight: 600;
    color: #fff;
    background: var(--accent-primary, #3b82f6);
    border: 1px solid var(--accent-primary, #3b82f6);
    border-radius: var(--radius-chip, 5px);
    cursor: pointer; flex-shrink: 0;
    transition: background 0.15s;
  }
  .ask-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--accent-primary, #3b82f6) 85%, black); }
  .ask-btn:disabled { opacity: 0.5; cursor: default; }
  .ask-error {
    margin: 0; font-size: 11px; line-height: 1.4;
    color: var(--danger, #ef4444);
  }
  .ask-answer {
    padding: 8px 10px;
    background: var(--bg-insight-info, rgba(59,130,246,0.06));
    border-left: 3px solid var(--color-info, var(--accent-primary, #3b82f6));
    border-radius: var(--radius-sm, 6px);
  }
  .ask-warn {
    margin: 0 0 6px;
    font-size: 11px; line-height: 1.4; font-weight: 600;
    color: var(--warning, #f59e0b);
  }
  .ask-text {
    margin: 0;
    font-size: 12px; line-height: 1.5;
    color: var(--text-secondary, #94a3b8);
    white-space: pre-line;
  }

</style>
