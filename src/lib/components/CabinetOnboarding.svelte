<script>
  import { cabinetOnboarding, inboxFiles, messages } from '$lib/store.js';
  import {
    getOnboardingConfig,
    advanceOnboardingStep,
    completeOnboarding,
    skipOnboarding,
  } from '$lib/onboarding-config.js';

  /**
   * @type {{
   *   cabinetId: string,
   *   onExecuteCommand: (command: string) => void,
   *   onComplete: () => void,
   * }}
   */
  let { cabinetId, onExecuteCommand, onComplete } = $props();

  const config = $derived(getOnboardingConfig(cabinetId));
  // Read store directly for reactivity ($derived + get() inside function = NOT reactive)
  const currentStep = $derived($cabinetOnboarding[cabinetId]?.step ?? 0);
  const stepConfig = $derived(
    config && currentStep < config.steps.length ? config.steps[currentStep] : null
  );

  // Guard: track last advanced step to prevent double-advance in same effect cycle
  let lastAdvancedStep = -1;

  $effect(() => {
    if (!stepConfig || currentStep <= lastAdvancedStep) return;
    if (stepConfig.triggerCondition === 'hasFiles' && $inboxFiles.length > 0) {
      lastAdvancedStep = currentStep;
      advanceOnboardingStep(cabinetId);
    } else if (stepConfig.triggerCondition === 'hasResponse' && $messages.some(m => m.role === 'assistant')) {
      lastAdvancedStep = currentStep;
      advanceOnboardingStep(cabinetId);
    }
  });

  function handleComplete() {
    completeOnboarding(cabinetId);
    onComplete();
  }

  function handleSkip() {
    skipOnboarding(cabinetId);
    onComplete();
  }

  /** @param {string} cmd */
  function handleNextAction(cmd) {
    onExecuteCommand(cmd);
    handleComplete();
  }
</script>

{#if config && stepConfig}
  <div class="cabinet-onboarding">
    <!-- Step content -->
    {#key currentStep}
      <div class="step-content">
        {#if stepConfig.id === 'upload'}
          <div class="onboarding-step upload-step">
            <div class="drop-illustration">
              <svg width="64" height="64" viewBox="0 0 64 64" fill="none" aria-hidden="true">
                <rect x="8" y="16" width="48" height="36" rx="4" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/>
                <path d="M32 44V28M32 28L25 35M32 28L39 35" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                <rect x="20" y="10" width="24" height="4" rx="2" fill="currentColor" opacity="0.5"/>
              </svg>
              <p class="step-title">{stepConfig.title}</p>
              <p class="step-desc">{stepConfig.description}</p>
              <div class="visual-hint">
                <span class="hint-before">22 слайда</span>
                <span class="hint-arrow">→</span>
                <span class="hint-after">5 ключевых выводов</span>
              </div>
            </div>
          </div>

        {:else if stepConfig.id === 'analyze'}
          <div class="onboarding-step analyze-step">
            <p class="step-title">{stepConfig.title}</p>
            <p class="step-desc">{stepConfig.description}</p>
            {#if stepConfig.focusCommand}
              <button
                class="focused-command"
                onclick={() => onExecuteCommand(/** @type {string} */ (stepConfig.focusCommand))}
              >
                <span class="command-name">{stepConfig.focusCommand}</span>
                <span class="command-action">Запустить анализ →</span>
              </button>
            {/if}
          </div>

        {:else if stepConfig.id === 'result'}
          <div class="onboarding-step result-step">
            <div class="success-icon" aria-hidden="true">✓</div>
            <p class="step-title">{stepConfig.title}</p>
            <p class="step-desc">{stepConfig.description}</p>
            {#if stepConfig.nextActions?.length}
              <div class="next-actions">
                <p class="next-label">Попробуйте также:</p>
                {#each stepConfig.nextActions as cmd}
                  <button class="next-chip" onclick={() => handleNextAction(cmd)}>
                    {cmd}
                  </button>
                {/each}
              </div>
            {/if}
            <button class="complete-btn" onclick={handleComplete}>Готово</button>
          </div>
        {/if}
      </div>
    {/key}

    <!-- Progress dots -->
    <div class="progress-dots">
      {#each config.steps as _, i}
        <span class="dot" class:filled={i <= currentStep}></span>
      {/each}
      <span class="step-counter">Шаг {currentStep + 1} из {config.steps.length}</span>
    </div>

    <!-- Navigation -->
    <div class="nav-row">
      {#if currentStep < config.steps.length - 1}
        <button class="next-step-btn" onclick={() => advanceOnboardingStep(cabinetId)}>Далее →</button>
      {/if}
      <button class="skip-btn" onclick={handleSkip}>Пропустить</button>
    </div>
  </div>
{/if}

<style>
  .cabinet-onboarding {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 20px;
    padding: 32px 24px;
    position: relative;
    animation: onboardingIn 300ms ease-out both;
  }

  @keyframes onboardingIn {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .step-content {
    width: 100%;
    max-width: 360px;
    animation: onboardingIn 200ms ease-out both;
  }

  /* ── Upload step ── */
  .upload-step {
    text-align: center;
  }

  .drop-illustration {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 32px 24px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.08));
    border-radius: var(--radius-lg, 14px);
    border: 1.5px dashed var(--border);
    color: var(--text-secondary, rgba(255,255,255,0.6));
  }

  .drop-illustration svg {
    color: var(--accent-primary, #2E5BFF);
    opacity: 0.9;
  }

  .visual-hint {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
    font-size: 12px;
    opacity: 0.6;
  }

  .hint-arrow {
    color: var(--accent-primary, #2E5BFF);
    opacity: 1;
  }

  /* ── Analyze step ── */
  .analyze-step {
    text-align: center;
    padding: 28px 24px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.08));
    border-radius: var(--radius-lg, 14px);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
  }

  .focused-command {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 12px 16px;
    background: var(--accent-primary, #2E5BFF);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-btn);
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    transition: opacity 150ms;
    margin-top: 4px;
  }

  .focused-command:hover {
    opacity: 0.88;
  }

  .command-name {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 13px;
  }

  .command-action {
    font-size: 13px;
    opacity: 0.9;
  }

  /* ── Result step ── */
  .result-step {
    text-align: center;
    padding: 28px 24px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.08));
    border-radius: var(--radius-lg, 14px);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
  }

  .success-icon {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: var(--accent-glow-strong);
    color: var(--accent-primary, #2E5BFF);
    font-size: 22px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .next-actions {
    width: 100%;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
    margin-top: 4px;
  }

  .next-label {
    width: 100%;
    font-size: 12px;
    color: var(--text-secondary, rgba(255,255,255,0.5));
    margin: 0 0 2px;
  }

  .next-chip {
    padding: 6px 12px;
    background: var(--accent-glow);
    color: var(--accent-primary, #2E5BFF);
    border: 1px solid var(--accent-glow-strong);
    border-radius: var(--radius-chip);
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 12px;
    cursor: pointer;
    transition: background 150ms;
  }

  .next-chip:hover {
    background: var(--accent-glow-strong);
  }

  .complete-btn {
    padding: 10px 28px;
    background: var(--accent-primary, #2E5BFF);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-btn);
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: opacity 150ms;
    margin-top: 4px;
  }

  .complete-btn:hover {
    opacity: 0.88;
  }

  /* ── Shared text ── */
  .step-title {
    font-size: 16px;
    font-weight: var(--font-weight-heading);
    color: var(--text-primary, rgba(255,255,255,0.92));
    margin: 0;
  }

  .step-desc {
    font-size: 13px;
    color: var(--text-secondary, rgba(255,255,255,0.6));
    margin: 0;
    line-height: 1.5;
  }

  /* ── Progress dots ── */
  .progress-dots {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--border);
    transition: background 200ms;
  }

  .dot.filled {
    background: var(--accent-primary, #2E5BFF);
  }

  .step-counter {
    font-size: 11px;
    color: var(--text-secondary, rgba(255,255,255,0.4));
    margin-left: 4px;
  }

  /* ── Navigation row ── */
  .nav-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .next-step-btn {
    padding: 6px 18px;
    background: var(--accent-primary, #2E5BFF);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-btn);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: opacity 150ms;
  }

  .next-step-btn:hover {
    opacity: 0.88;
  }

  /* ── Skip ── */
  .skip-btn {
    background: none;
    border: 1px solid var(--border);
    color: var(--text-secondary, rgba(255,255,255,0.55));
    font-size: 12px;
    cursor: pointer;
    padding: 6px 14px;
    border-radius: var(--radius-btn);
    transition: all 150ms;
  }

  .skip-btn:hover {
    color: var(--text-primary, rgba(255,255,255,0.85));
    border-color: var(--border);
    background: var(--hover-bg);
  }

  /* v2.1.0 п.5.6: instant appearance, no slide-in */
  @media (prefers-reduced-motion: reduce) {
    .onboarding-card,
    .step-content {
      animation: none;
      opacity: 1;
      transform: none;
    }
  }
</style>
