<script>
  /**
   * ErrorState — Phase 2.15 / Audit P-premium-feel.
   *
   * Error display с retry affordance. Used когда backend returns 5xx
   * или sidecar unavailable. Replaces silent failures с inline message +
   * clear next action.
   *
   * Severity:
   * - 'warning' (default) — recoverable, retry available
   * - 'error' — critical, user action required
   *
   * Includes optional error_code (machine-readable) + human message +
   * optional retry button + optional detail expander.
   */

  /**
   * @type {{
   *   title?: string,
   *   message?: string,
   *   errorCode?: string,
   *   severity?: 'warning' | 'error',
   *   retryText?: string,
   *   onRetry?: () => void,
   *   detailText?: string,
   * }}
   */
  const {
    title = 'Ошибка',
    message = '',
    errorCode = '',
    severity = 'warning',
    retryText = 'Повторить',
    onRetry = undefined,
    detailText = '',
  } = $props();

  let showDetail = $state(false);
  const hasRetry = $derived(Boolean(onRetry));
  const hasDetail = $derived(Boolean(detailText));
</script>

<div
  class="error-state error-state--{severity}"
  role="alert"
  data-testid="error-state"
>
  <div class="error-icon" aria-hidden="true">
    {severity === 'error' ? '✕' : '⚠'}
  </div>
  <div class="error-content">
    <strong class="error-title">{title}</strong>
    {#if errorCode}
      <code class="error-code" data-testid="error-code">{errorCode}</code>
    {/if}
    {#if message}
      <p class="error-message">{message}</p>
    {/if}
    {#if hasDetail}
      <button
        type="button"
        class="error-detail-toggle"
        onclick={() => (showDetail = !showDetail)}
        aria-expanded={showDetail}
      >
        {showDetail ? 'Скрыть детали' : 'Показать детали'}
      </button>
      {#if showDetail}
        <pre class="error-detail" data-testid="error-detail">{detailText}</pre>
      {/if}
    {/if}
  </div>
  {#if hasRetry}
    <button
      type="button"
      class="error-retry"
      onclick={onRetry}
      data-testid="error-retry"
    >{retryText}</button>
  {/if}
</div>

<style>
  .error-state {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 14px 18px;
    border-radius: var(--radius-card, 12px);
    border: 1px solid;
    background: color-mix(in srgb, var(--warning, #F59E0B) 6%, transparent);
    border-color: color-mix(in srgb, var(--warning, #F59E0B) 32%, transparent);
  }
  .error-state--error {
    background: color-mix(in srgb, var(--danger, #EF4444) 6%, transparent);
    border-color: color-mix(in srgb, var(--danger, #EF4444) 38%, transparent);
  }
  .error-icon {
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    font-weight: 700;
    color: white;
    background: var(--warning, #F59E0B);
  }
  .error-state--error .error-icon {
    background: var(--danger, #EF4444);
  }
  .error-content {
    flex: 1;
    min-width: 0;
  }
  .error-title {
    display: block;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 4px;
  }
  .error-code {
    display: inline-block;
    padding: 1px 6px;
    margin-right: 6px;
    background: color-mix(in srgb, var(--text-primary) 8%, transparent);
    border-radius: 4px;
    font-family: var(--font-mono, ui-monospace, "Consolas", monospace);
    font-size: 11px;
    color: var(--text-secondary, #b6b6c5);
  }
  .error-message {
    margin: 0;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-secondary, #b6b6c5);
  }
  .error-detail-toggle {
    margin-top: 6px;
    background: transparent;
    border: none;
    color: var(--text-muted, #7A7A90);
    font-size: 11.5px;
    cursor: pointer;
    text-decoration: underline;
    padding: 0;
  }
  .error-detail {
    margin: 8px 0 0;
    padding: 8px 10px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: 6px;
    font-family: var(--font-mono, ui-monospace, "Consolas", monospace);
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
    max-height: 200px;
    overflow: auto;
    white-space: pre-wrap;
  }
  .error-retry {
    flex-shrink: 0;
    padding: 7px 14px;
    background: var(--warning, #F59E0B);
    color: var(--bg-card, #181824);
    border: none;
    border-radius: 6px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
  }
  .error-state--error .error-retry {
    background: var(--danger, #EF4444);
    color: white;
  }
  @media (prefers-reduced-motion: no-preference) {
    .error-retry {
      transition: background 0.15s, transform 0.1s;
    }
    .error-retry:hover {
      background: color-mix(in srgb, var(--warning, #F59E0B) 90%, white 10%);
    }
    .error-retry:active {
      transform: scale(0.97);
    }
  }
</style>
