<script>
  /**
   * ScenarioWizard - v2.0.0 main wizard orchestrator.
   *
   * Coordinates all 6 wizard steps, progress bar, navigation buttons,
   * WhyThisStep panel, cross-product escape banners, and loading state.
   *
   * Per WIZARD_FLOW_v2_FINAL.md §9.1 + §0.6 state lifecycle.
   *
   * @component ScenarioWizard
   */

  import { ChevronLeft, ChevronRight, SkipForward, Loader2, AlertTriangle, Info, Lightbulb } from 'lucide-svelte';
  import { fly, fade } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { wizardState, nextStep, prevStep, confirmPrevStep } from '$lib/wizard-state.js';
  import { analysisMode, expertMode } from '$lib/project-state.js';
  import { prefersReducedMotion } from '$lib/stores/a11y.js';

  import StepTaskIntent     from '$lib/components/pipeline/wizard/StepTaskIntent.svelte';
  import StepTargetConfirm  from '$lib/components/pipeline/wizard/StepTargetConfirm.svelte';
  import StepMediaConfirm   from '$lib/components/pipeline/wizard/StepMediaConfirm.svelte';
  // v2.0.0 audit fix (Frontend C5): integration of Steps 4-6 (previously stubs).
  import StepPlanInputs     from '$lib/components/pipeline/wizard/StepPlanInputs.svelte';
  import StepContextConfirm from '$lib/components/pipeline/wizard/StepContextConfirm.svelte';
  import StepSummary        from '$lib/components/pipeline/wizard/StepSummary.svelte';

  /**
   * @type {{
   *   onComplete?: ((data: Record<string, any>) => void) | null,
   *   onCancel?:   (() => void) | null
   * }}
   */
  const { onComplete = null, onCancel = null } = $props();

  // ─── Local UI state ───────────────────────────────────────────────────────

  /** WhyThisStep collapsible panel open */
  let whyExpanded = $state(false);

  /**
   * Pending back-nav invalidation warning (shown as inline dialog).
   * @type {import('$lib/wizard-state.js').InvalidationWarning | null}
   */
  let invalidationWarning = $state(null);

  // ─── Derived ──────────────────────────────────────────────────────────────

  /** @type {number} */
  const TOTAL_STEPS = 6;

  /** True when wizard is in AUTO_DETECTING loading state */
  const isLoading = $derived($wizardState.lifecycle === 'AUTO_DETECTING');

  /** True when wizard is frozen (RUNNING or COMPLETED) - read-only */
  const isFrozen = $derived(
    $wizardState.lifecycle === 'RUNNING' || $wizardState.lifecycle === 'COMPLETED'
  );

  /** Whether cross-product escape banner should be shown */
  const showEscapeBanner = $derived(
    !!$wizardState.escapeReason && $wizardState.lifecycle === 'ESCAPE'
  );

  /**
   * Step-specific WhyThisStep explanation text.
   * @type {Record<number, { title: string, body: string }>}
   */
  const whyThisStepText = {
    1: {
      title: 'Зачем выбирать тип задачи?',
      body: 'Тип задачи определяет, что именно программа будет оптимизировать. ' +
            'Бюджетная оптимизация ищет лучшее распределение между каналами. ' +
            'Обратная оптимизация рассчитывает минимальные затраты для достижения цели. ' +
            'Декомпозиция - только анализ прошлого, без оптимизации.',
    },
    2: {
      title: 'Зачем подтверждать целевую метрику?',
      body: 'Целевой показатель - это то, что модель пытается объяснить и оптимизировать. ' +
            'Если программа нашла несколько кандидатов (продажи в ₽ и в упаковках), ' +
            'вам нужно выбрать основной. Если KPI в штуках - укажите ценность единицы ' +
            'для расчёта финансовой отдачи каждого канала.',
    },
    3: {
      title: 'Зачем подтверждать медиа-входы?',
      body: 'Единицы медиа-активности определяют, что именно модель берёт как «вложения» ' +
            'каждого канала. Если часть каналов в ₽, а часть в физических метриках (TRP, ' +
            'показы, клики) - это «смешанный» режим, требующий ставок конверсии. ' +
            'Единый режим даёт более стабильные оценки ROI.',
    },
    4: {
      title: 'Зачем указывать плановые параметры?',
      body: 'Модель обучена на истории. Чтобы посчитать оптимизацию или прогноз, ' +
            'ей нужно знать горизонт (сколько периодов вперёд) и бюджет (в каком объёме). ' +
            'Эти параметры задают рамки задачи.',
    },
    5: {
      title: 'Зачем проверять контекстные факторы?',
      body: 'Помимо рекламы, на продажи влияют дистрибуция, конкуренты, цены, праздники. ' +
            'Если программа обнаружила такие данные в таблице, лучше их включить - ' +
            'иначе их вклад будет ошибочно приписан медиа-каналам.',
    },
    6: {
      title: 'Что происходит при запуске анализа?',
      body: 'Программа обучает байесовскую модель (MCMC, ~20-60 секунд), затем запускает ' +
            'декомпозицию и оптимизацию. После обучения автоматически проверяется ' +
            'сходимость (R-hat), бэктест на удержанных данных и PPC-валидация.',
    },
  };

  /**
   * @type {{ title: string, body: string } | null}
   */
  const currentWhyText = $derived(
    whyThisStepText[$wizardState.currentStep] ?? null
  );

  // ─── Escape banner content ─────────────────────────────────────────────────

  /**
   * @type {{ title: string, message: string, suggestion: string } | null}
   */
  const escapeBannerContent = $derived.by(() => {
    if (!$wizardState.escapeReason) return null;
    switch ($wizardState.escapeReason) {
      case 'history_short':
        return {
          title: 'Недостаточно данных для MMM',
          message: 'В вашем датасете менее 24 месяцев рекламной активности. ' +
                   'Для надёжного MMM нужна достаточная история.',
          suggestion: 'Рассмотрите Aurora Launch Planner - он работает с короткой историей через прокси-категорию.',
        };
      case 'launch_like':
        return {
          title: 'Мало рекламной активности',
          message: 'В вашем датасете менее 50% периодов с ненулевыми расходами. ' +
                   'MMM-модель не сможет надёжно идентифицировать отдачу каналов.',
          suggestion: 'Для запуска нового продукта лучше подходит Aurora Launch Planner с прокси-категорией.',
        };
      default:
        return {
          title: 'Данные не прошли проверку качества',
          message: 'Автоматический контроль качества обнаружил проблемы с данными.',
          suggestion: 'Включите режим эксперта, чтобы продолжить с текущими данными без автоматических ограничений.',
        };
    }
  });

  // ─── Navigation handlers ───────────────────────────────────────────────────

  function handleBack() {
    if (isFrozen || $wizardState.currentStep <= 1) return;
    const warning = prevStep();
    if (warning) {
      invalidationWarning = warning;
    }
  }

  function handleConfirmBack() {
    if (invalidationWarning) {
      confirmPrevStep(invalidationWarning);
      invalidationWarning = null;
    }
  }

  function handleCancelBack() {
    invalidationWarning = null;
  }

  /** Skip current step (for conditional steps with silent auto-confirm available) */
  function handleSkip() {
    if (isFrozen) return;
    nextStep({});
  }

  /** Enable Expert mode and close escape state */
  function handleExpertEscape() {
    expertMode.set(true);
    onCancel?.();
  }

  // ─── Step-specific data handlers ──────────────────────────────────────────

  /** @param {string} taskType */
  function handleStep1Select(taskType) {
    nextStep({ taskIntent: taskType });
  }

  /**
   * @param {{ column: string, kind: string, valuePerCountUnit?: number | null }} data
   */
  function handleStep2Confirm(data) {
    nextStep({ target: data });
  }

  /**
   * @param {Record<string, 'monetary' | 'physical'>} perChannelInput
   */
  function handleStep3Confirm(perChannelInput) {
    nextStep({ perChannelInput });
  }

  /** Generic next for steps 4-6 */
  function handleGenericNext() {
    if (isFrozen) return;
    nextStep({});
  }

  /** Step 6: Run analysis */
  function handleRun() {
    if (isFrozen) return;
    const allData = $wizardState.stepData;
    onComplete?.({
      ...allData,
      lifecycle: $wizardState.lifecycle,
      resolvedFactors: $wizardState.resolvedFactors,
    });
  }

  // ─── Derived helpers ──────────────────────────────────────────────────────

  const canGoBack = $derived(!isFrozen && $wizardState.currentStep > 1);
  const isLastStep = $derived($wizardState.currentStep >= 6);

  // ─── Step transition direction (v2.1.0 п.5.3: плавные переходы) ──────────
  // Отслеживаем направление перехода: forward (fly справа) vs back (fly слева).
  // prefers-reduced-motion → duration 0 (мгновенный crossfade).

  let prevStepIndex = $state($wizardState.currentStep);
  let transitionDirection = $state(/** @type {'forward' | 'back'} */ ('forward'));

  $effect(() => {
    const current = $wizardState.currentStep;
    if (current !== prevStepIndex) {
      transitionDirection = current > prevStepIndex ? 'forward' : 'back';
      prevStepIndex = current;
    }
  });

  const transitionDuration = $derived($prefersReducedMotion ? 0 : 280);
  const flyOffset = $derived($prefersReducedMotion ? 0 : (transitionDirection === 'forward' ? 32 : -32));

  /** Whether current step is conditionally skippable */
  const canSkip = $derived(
    $wizardState.currentStep === 2 || $wizardState.currentStep === 3 || $wizardState.currentStep === 5
  );

  /** Progress percent for visual bar */
  const progressPct = $derived(
    Math.round(($wizardState.currentStep / TOTAL_STEPS) * 100)
  );
</script>

<div class="wizard" class:frozen={isFrozen}>

  <!-- ─── Progress bar ─────────────────────────────────────────────────── -->
  <header class="wizard-header">
    <div class="progress-info">
      <span class="step-label">
        {#if isLoading}
          Анализирую данные...
        {:else if isFrozen}
          Анализ завершён
        {:else}
          Шаг {$wizardState.currentStep} из {TOTAL_STEPS}
        {/if}
      </span>
      {#if !isLoading && !isFrozen}
        <span class="step-pct">{progressPct}%</span>
      {/if}
    </div>
    <div class="progress-track" role="progressbar" aria-valuenow={progressPct} aria-valuemin={0} aria-valuemax={100}>
      <div class="progress-fill" style="width: {progressPct}%"></div>
    </div>
    <div class="step-dots" aria-hidden="true">
      {#each Array(TOTAL_STEPS) as _, i}
        <span
          class="dot"
          class:done={i + 1 < $wizardState.currentStep}
          class:active={i + 1 === $wizardState.currentStep}
        ></span>
      {/each}
    </div>
  </header>

  <!-- ─── Loading overlay ──────────────────────────────────────────────── -->
  {#if isLoading}
    <div class="loading-state">
      <Loader2 size={36} strokeWidth={1.5} class="spin-icon" />
      <p>Программа анализирует структуру ваших данных...</p>
      <p class="loading-sub">Классификация каналов, целевых метрик и контрольных факторов</p>
    </div>

  <!-- ─── Escape state ─────────────────────────────────────────────────── -->
  {:else if showEscapeBanner}
    {@const content = escapeBannerContent}
    {#if content}
      <div class="escape-banner">
        <div class="escape-icon">
          <AlertTriangle size={32} strokeWidth={1.5} />
        </div>
        <div class="escape-body">
          <h2 class="escape-title">{content.title}</h2>
          <p class="escape-message">{content.message}</p>
          <div class="escape-suggestion">
            <Info size={14} strokeWidth={1.5} />
            <span>{content.suggestion}</span>
          </div>
        </div>
        <div class="escape-actions">
          <button
            type="button"
            class="btn btn-secondary"
            onclick={handleExpertEscape}
          >
            Продолжить в режиме эксперта
          </button>
          <button
            type="button"
            class="btn btn-ghost"
            onclick={() => onCancel?.()}
          >
            Отмена
          </button>
        </div>
      </div>
    {/if}

  <!-- ─── Active wizard steps ───────────────────────────────────────────── -->
  {:else}
    <div class="wizard-content">

      <!-- Step components - v2.1.0 п.5.3: плавные переходы.
           {#key} форсит remount при смене currentStep, transition:fly даёт slide effect.
           prefers-reduced-motion → duration 0 + offset 0 (мгновенное появление). -->
      {#key $wizardState.currentStep}
        <div
          class="wizard-step-frame"
          in:fly={{ x: flyOffset, duration: transitionDuration, easing: cubicOut, delay: transitionDuration > 0 ? 60 : 0 }}
          out:fade={{ duration: transitionDuration / 2 }}
        >
          {#if $wizardState.currentStep === 1}
            <StepTaskIntent onSelect={handleStep1Select} />

          {:else if $wizardState.currentStep === 2}
            <StepTargetConfirm
              targetCandidates={$wizardState.autoDetectResults?.data_signature?.target_candidates ?? []}
              onConfirm={handleStep2Confirm}
            />

          {:else if $wizardState.currentStep === 3}
            <StepMediaConfirm
              channels={$wizardState.autoDetectResults?.data_signature?.channels ?? []}
              bestPracticeWarnings={$wizardState.autoDetectResults?.best_practice_warnings ?? []}
              onConfirm={handleStep3Confirm}
            />

          {:else if $wizardState.currentStep === 4}
            <StepPlanInputs
              taskType={$wizardState.stepData.step1?.taskType ?? 'budget_optimization'}
              onSubmit={(data) => { nextStep({ stepData: { step4: data } }); }}
            />

          {:else if $wizardState.currentStep === 5}
            <StepContextConfirm
              autoDetectedFactors={$wizardState.autoDetectResults?.data_signature ?? {}}
              onConfirm={(data) => { nextStep({ stepData: { step5: data } }); }}
            />

          {:else if $wizardState.currentStep >= 6}
            <StepSummary
              summary={/** @type {any} */ ($wizardState.stepData ?? {})}
              diagnostics={/** @type {any} */ (null)}
              onRun={handleRun}
              onEditExpert={() => { expertMode.set(true); }}
            />
          {/if}
        </div>
      {/key}

      <!-- ─── Cross-product hint banner (escape reason set but not in ESCAPE state) -->
      {#if $wizardState.escapeReason && !showEscapeBanner}
        {@const content = escapeBannerContent}
        {#if content}
          <div class="inline-hint-banner">
            <Lightbulb size={16} strokeWidth={1.5} class="hint-icon" />
            <span>{content.suggestion}</span>
            <button type="button" class="hint-expert-btn" onclick={handleExpertEscape}>
              Режим эксперта
            </button>
          </div>
        {/if}
      {/if}

      <!-- ─── WhyThisStep collapsible panel ──────────────────────────── -->
      {#if currentWhyText}
        <div class="why-section">
          <button
            type="button"
            class="why-toggle"
            aria-expanded={whyExpanded}
            onclick={() => (whyExpanded = !whyExpanded)}
          >
            <Lightbulb size={14} strokeWidth={1.5} />
            {currentWhyText.title}
            <span class="chevron" class:open={whyExpanded}>▾</span>
          </button>
          {#if whyExpanded}
            <div class="why-panel" role="region">
              <p>{currentWhyText.body}</p>
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <!-- ─── Invalidation warning dialog ─────────────────────────────── -->
    {#if invalidationWarning}
      <div class="invalidation-overlay" role="dialog" aria-modal="true">
        <div class="invalidation-dialog">
          <AlertTriangle size={20} strokeWidth={1.5} class="warn-icon" />
          <p class="invalidation-msg">{invalidationWarning.message}</p>
          <div class="invalidation-actions">
            <button type="button" class="btn btn-danger-sm" onclick={handleConfirmBack}>
              Да, изменить
            </button>
            <button type="button" class="btn btn-ghost" onclick={handleCancelBack}>
              Отмена
            </button>
          </div>
        </div>
      </div>
    {/if}

    <!-- ─── Navigation bar ────────────────────────────────────────────── -->
    {#if !isFrozen && $wizardState.lifecycle !== 'ESCAPE'}
      <footer class="wizard-nav">
        <button
          type="button"
          class="btn btn-ghost btn-nav"
          disabled={!canGoBack}
          onclick={handleBack}
          aria-label="Назад"
        >
          <ChevronLeft size={16} /> Назад
        </button>

        <div class="nav-right">
          {#if canSkip && !isLastStep}
            <button
              type="button"
              class="btn btn-ghost btn-nav"
              onclick={handleSkip}
              title="Пропустить этот шаг"
            >
              <SkipForward size={15} /> Пропустить
            </button>
          {/if}

          {#if isLastStep}
            <button type="button" class="btn btn-run" onclick={handleRun}>
              Запустить анализ
            </button>
          {:else}
            <button
              type="button"
              class="btn btn-primary btn-nav"
              onclick={handleGenericNext}
            >
              Далее <ChevronRight size={16} />
            </button>
          {/if}
        </div>
      </footer>
    {/if}
  {/if}
</div>

<style>
  /* ─── Wizard shell ─────────────────────────────────────────────────────── */
  .wizard {
    display: flex;
    flex-direction: column;
    gap: 0;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    box-shadow: var(--shadow-card, 0 2px 16px rgba(0,0,0,0.4));
    overflow: hidden;
    max-width: 900px;
    margin: 0 auto;
    width: 100%;
  }
  .wizard.frozen {
    opacity: 0.85;
    pointer-events: none;
  }

  /* ─── Header / Progress ──────────────────────────────────────────────── */
  .wizard-header {
    padding: 16px 24px 12px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    background: var(--bg-secondary, #141420);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .progress-info {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .step-label {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--gold, #c9a449);
  }
  .step-pct {
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
  }
  .progress-track {
    height: 3px;
    background: var(--border, rgba(255,255,255,0.08));
    border-radius: 2px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: var(--gold, #c9a449);
    border-radius: 2px;
    transition: width 0.4s ease;
  }
  .step-dots {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--border, rgba(255,255,255,0.12));
    transition: background 0.2s, transform 0.2s;
  }
  .dot.done {
    background: color-mix(in srgb, var(--gold, #c9a449) 60%, transparent);
  }
  .dot.active {
    background: var(--gold, #c9a449);
    transform: scale(1.35);
    box-shadow: 0 0 6px color-mix(in srgb, var(--gold, #c9a449) 50%, transparent);
  }

  /* ─── Loading state ──────────────────────────────────────────────────── */
  .loading-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 60px 24px;
    color: var(--text-secondary);
    text-align: center;
  }
  .loading-state p { margin: 0; font-size: 14px; }
  .loading-sub { font-size: 12px; color: var(--text-muted, #7A7A90); }
  :global(.spin-icon) { animation: spin 1.4s linear infinite; color: var(--gold, #c9a449); }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ─── Escape banner ──────────────────────────────────────────────────── */
  .escape-banner {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
    padding: 32px 28px;
  }
  .escape-icon {
    color: var(--warning, #F59E0B);
    display: flex;
  }
  .escape-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0 0 8px;
    letter-spacing: -0.01em;
  }
  .escape-message {
    font-size: 13.5px;
    color: var(--text-secondary);
    margin: 0 0 12px;
    line-height: 1.5;
  }
  .escape-suggestion {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--accent-primary) 8%, var(--bg-secondary, #141420));
    border-left: 2px solid var(--accent-primary);
    border-radius: 0 6px 6px 0;
    font-size: 12.5px;
    color: var(--text-secondary);
    line-height: 1.5;
  }
  .escape-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }

  /* ─── Wizard content ─────────────────────────────────────────────────── */
  .wizard-content {
    display: flex;
    flex-direction: column;
    gap: 0;
    flex: 1;
    min-height: 0;
  }

  /* v2.1.0 п.5.3 - обёртка вокруг {#key} для плавных переходов между шагами.
     Старый шаг исчезает с fade, новый въезжает справа (forward) или слева (back).
     overflow:hidden предотвращает «выпадание» содержимого за границу при transition. */
  .wizard-step-frame {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    width: 100%;
  }

  @media (prefers-reduced-motion: reduce) {
    .wizard-step-frame {
      /* Дополнительная страховка: даже если transition сработала, не двигаемся */
      transform: none !important;
    }
  }

  /* ─── Step placeholder (Phase B stubs) ──────────────────────────────── */
  .step-placeholder {
    padding: 40px 28px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
  }
  .step-placeholder h2 {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0;
    letter-spacing: -0.01em;
  }
  .step-placeholder-body {
    font-size: 13px;
    color: var(--text-secondary);
    margin: 0;
    line-height: 1.5;
  }

  /* ─── Inline cross-product hint banner ───────────────────────────────── */
  .inline-hint-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    background: color-mix(in srgb, var(--accent-primary) 6%, var(--bg-secondary, #141420));
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    font-size: 12.5px;
    color: var(--text-secondary);
  }
  :global(.hint-icon) { color: var(--gold, #c9a449); flex-shrink: 0; }
  .hint-expert-btn {
    background: none;
    border: 1px solid var(--accent-primary);
    color: var(--accent-primary);
    border-radius: 4px;
    padding: 2px 8px;
    font: inherit;
    font-size: 11px;
    cursor: pointer;
    transition: background 0.15s;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .hint-expert-btn:hover {
    background: color-mix(in srgb, var(--accent-primary) 15%, transparent);
  }

  /* ─── WhyThisStep ────────────────────────────────────────────────────── */
  .why-section {
    padding: 0 24px 12px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  .why-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    background: none;
    border: none;
    color: var(--text-muted, #7A7A90);
    cursor: pointer;
    font: inherit;
    font-size: 11.5px;
    padding: 10px 0 4px;
    text-decoration: underline dashed;
    text-underline-offset: 2px;
    transition: color 0.15s;
  }
  .why-toggle:hover { color: var(--gold, #c9a449); }
  .chevron {
    font-size: 9px;
    display: inline-block;
    transition: transform 0.2s;
    margin-left: auto;
  }
  .chevron.open { transform: rotate(180deg); }
  .why-panel {
    padding: 12px 16px;
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, var(--bg-card, #0f172a));
    border-left: 2px solid var(--gold, #c9a449);
    border-radius: 0 6px 6px 0;
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--text-secondary);
  }
  .why-panel p { margin: 0; }

  /* ─── Invalidation overlay ───────────────────────────────────────────── */
  .invalidation-overlay {
    position: absolute;
    inset: 0;
    background: rgba(0,0,0,0.6);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
    border-radius: inherit;
  }
  .invalidation-dialog {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    border-radius: 10px;
    padding: 20px 24px;
    max-width: 380px;
    width: 90%;
    display: flex;
    flex-direction: column;
    gap: 12px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  }
  :global(.warn-icon) { color: var(--warning, #F59E0B); }
  .invalidation-msg {
    font-size: 13px;
    color: var(--text-secondary);
    margin: 0;
    line-height: 1.5;
  }
  .invalidation-actions { display: flex; gap: 8px; }

  /* ─── Navigation bar ─────────────────────────────────────────────────── */
  .wizard-nav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 24px 16px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    background: var(--bg-secondary, #141420);
    gap: 10px;
  }
  .nav-right {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  /* ─── Buttons ────────────────────────────────────────────────────────── */
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: none;
    border-radius: 7px;
    cursor: pointer;
    font: inherit;
    font-size: 13px;
    font-weight: 600;
    padding: 8px 16px;
    transition: background 0.15s, opacity 0.15s, transform 0.12s;
    white-space: nowrap;
  }
  .btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }
  .btn-primary {
    background: var(--accent-primary);
    color: #fff;
  }
  .btn-primary:not(:disabled):hover {
    background: color-mix(in srgb, var(--accent-primary) 80%, #fff);
    transform: translateY(-1px);
  }
  .btn-run {
    background: var(--gold, #c9a449);
    color: #0c0c14;
    font-weight: 700;
    padding: 9px 20px;
  }
  .btn-run:hover {
    background: color-mix(in srgb, var(--gold, #c9a449) 85%, #fff);
    transform: translateY(-1px);
  }
  .btn-secondary {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    color: var(--text-primary);
  }
  .btn-secondary:hover {
    border-color: var(--accent-primary);
    background: color-mix(in srgb, var(--accent-primary) 10%, var(--bg-card, #181824));
  }
  .btn-ghost {
    background: transparent;
    color: var(--text-secondary);
    border: 1px solid transparent;
  }
  .btn-ghost:not(:disabled):hover {
    background: var(--bg-surface-quiet, rgba(20,20,30,0.92));
    border-color: var(--border, rgba(255,255,255,0.08));
  }
  .btn-danger-sm {
    background: color-mix(in srgb, var(--warning, #F59E0B) 15%, var(--bg-card, #181824));
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 40%, transparent);
    color: var(--warning, #F59E0B);
    font-size: 12px;
    padding: 6px 12px;
  }
  .btn-nav {
    font-size: 12.5px;
    padding: 7px 14px;
  }

  /* v2.1.0 п.5.6: static loading icon */
  @media (prefers-reduced-motion: reduce) {
    :global(.spin-icon) {
      animation: none;
    }
  }
</style>
