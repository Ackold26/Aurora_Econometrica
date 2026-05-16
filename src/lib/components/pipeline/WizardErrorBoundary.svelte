<script>
  /**
   * WizardErrorBoundary - production error UX для ScenarioWizard.
   *
   * Перехватывает runtime-ошибки (network failures, validation errors,
   * malformed data, backend timeout, async race conditions) через
   * <svelte:boundary>. Показывает graceful fallback UI с кнопкой reset.
   *
   * Post-ship: logErrorContext() расширить Sentry/telemetry endpoint.
   *
   * Стиль: same vocabulary as AnalysisModeSelector (gold accent,
   * sacred-lime hairlines, dark theme, premium tier-1 buttons).
   *
   * @component WizardErrorBoundary
   */

  import { AlertTriangle, RotateCcw } from 'lucide-svelte';
  import ScenarioWizard from './ScenarioWizard.svelte';
  import { resetWizard } from '$lib/wizard-state.js';

  /**
   * @type {{
   *   onComplete?: ((data: Record<string, any>) => void) | null,
   *   onCancel?:   (() => void) | null
   * }}
   */
  const { onComplete = null, onCancel = null } = $props();

  /** @type {Error | null} */
  let caughtError = $state(null);

  /** @type {boolean} */
  let isResetting = $state(false);

  /**
   * Logs error context for future Sentry integration (post-ship).
   * For now - structured console.error with context.
   * @param {Error} err
   */
  function logErrorContext(err) {
    console.error('[WizardErrorBoundary] Caught error:', {
      message: err.message,
      name: err.name,
      stack: err.stack,
      timestamp: new Date().toISOString(),
      // TODO: include $wizardState snapshot for debugging
    });
  }

  /**
   * Resets boundary state and reinitialises wizard via resetWizard().
   * Brief isResetting flag forces DOM teardown so child remounts cleanly.
   */
  async function handleReset() {
    isResetting = true;
    caughtError = null;
    resetWizard();
    // Micro-tick: let Svelte commit boundary teardown before remount.
    await Promise.resolve();
    isResetting = false;
  }
</script>

<svelte:boundary
  onerror={(/** @type {unknown} */ err) => {
    caughtError = /** @type {Error} */ (err instanceof Error ? err : new Error(String(err)));
    logErrorContext(caughtError);
  }}
>
  {#snippet failed(/** @type {unknown} */ error)}
    {@const errObj = /** @type {Error} */ (error instanceof Error ? error : new Error(String(error)))}
    <div class="error-boundary-fallback" role="alertdialog" aria-modal="false" aria-labelledby="eb-title">
      <div class="error-icon-wrap" aria-hidden="true">
        <AlertTriangle size={44} strokeWidth={1.5} />
      </div>

      <h2 class="error-title" id="eb-title">Ошибка в мастере настройки</h2>

      <p class="error-body">
        Возникла непредвиденная ошибка. Программа сохранила ваши данные -
        вы можете начать заново или вернуться к pipeline.
      </p>

      <div class="error-details" aria-label="Техническое описание ошибки">
        <span class="error-label">Детали</span>
        <code class="error-code">{errObj.message || 'Unknown error'}</code>
      </div>

      <div class="error-actions">
        <button
          type="button"
          class="btn btn-reset"
          onclick={handleReset}
          disabled={isResetting}
        >
          <RotateCcw size={15} strokeWidth={2} />
          {isResetting ? 'Перезапуск…' : 'Начать заново'}
        </button>

        <button
          type="button"
          class="btn btn-cancel"
          onclick={onCancel}
        >
          Закрыть мастер
        </button>
      </div>

      <p class="error-hint">
        Если ошибка повторяется - проверьте данные импорта или обратитесь в поддержку.
      </p>
    </div>
  {/snippet}

  {#if !isResetting}
    <ScenarioWizard {onComplete} {onCancel} />
  {/if}
</svelte:boundary>

<style>
  /* ─── Fallback container ─────────────────────────────────────────────── */
  .error-boundary-fallback {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    padding: 40px 32px 36px;
    min-height: 360px;
    max-width: 540px;
    margin: 40px auto;
    background: var(--bg-card, #181824);
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 30%, var(--border, rgba(255,255,255,0.08)));
    border-radius: var(--radius-card, 12px);
    box-shadow:
      0 0 0 1px color-mix(in srgb, var(--gold, #c9a449) 12%, transparent),
      0 8px 40px rgba(0, 0, 0, 0.5);
    text-align: center;
    position: relative;
    overflow: hidden;
  }

  /* Sacred-lime hairline top accent */
  .error-boundary-fallback::before {
    content: '';
    position: absolute;
    inset: 0 0 auto 0;
    height: 2px;
    background: linear-gradient(
      90deg,
      transparent 0%,
      var(--gold, #c9a449) 40%,
      var(--accent-secondary, #CCFF00) 70%,
      transparent 100%
    );
    border-radius: var(--radius-card, 12px) var(--radius-card, 12px) 0 0;
  }

  /* ─── Icon ───────────────────────────────────────────────────────────── */
  .error-icon-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 72px;
    height: 72px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--gold, #c9a449) 12%, var(--bg-secondary, #141420));
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 25%, transparent);
    color: var(--gold, #c9a449);
    flex-shrink: 0;
    margin-bottom: 4px;
  }

  /* ─── Typography ─────────────────────────────────────────────────────── */
  .error-title {
    margin: 0;
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary, #EAEAF0);
    letter-spacing: -0.015em;
    line-height: 1.25;
  }

  .error-body {
    margin: 0;
    font-size: 13px;
    line-height: 1.6;
    color: var(--text-secondary, #A8A8B8);
    max-width: 400px;
  }

  /* ─── Error details block ────────────────────────────────────────────── */
  .error-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    width: 100%;
    max-width: 420px;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--danger, #EF4444) 6%, var(--bg-secondary, #141420));
    border: 1px solid color-mix(in srgb, var(--danger, #EF4444) 20%, transparent);
    border-radius: 7px;
    text-align: left;
  }

  .error-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--danger, #EF4444) 60%, var(--text-secondary, #A8A8B8));
  }

  .error-code {
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-primary, #EAEAF0);
    word-break: break-word;
    white-space: pre-wrap;
  }

  /* ─── Action buttons ─────────────────────────────────────────────────── */
  .error-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: center;
    margin-top: 4px;
  }

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
    padding: 9px 18px;
    transition: background 0.15s, opacity 0.15s, transform 0.12s;
    white-space: nowrap;
  }

  .btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  /* Primary: gold - matches btn-run in ScenarioWizard */
  .btn-reset {
    background: var(--gold, #c9a449);
    color: #0c0c14;
  }

  .btn-reset:not(:disabled):hover {
    background: color-mix(in srgb, var(--gold, #c9a449) 85%, #fff);
    transform: translateY(-1px);
  }

  /* Secondary: same as btn-secondary in ScenarioWizard */
  .btn-cancel {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    color: var(--text-primary, #EAEAF0);
  }

  .btn-cancel:hover {
    border-color: var(--accent-primary, #2E5BFF);
    background: color-mix(in srgb, var(--accent-primary, #2E5BFF) 10%, var(--bg-card, #181824));
  }

  /* ─── Hint line ──────────────────────────────────────────────────────── */
  .error-hint {
    margin: 0;
    font-size: 11.5px;
    color: var(--text-secondary, #A8A8B8);
    opacity: 0.7;
    line-height: 1.5;
  }
</style>
