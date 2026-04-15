<script>
  /** @type {{open?: boolean, title?: string, message?: string, confirmText?: string, cancelText?: string, danger?: boolean, onConfirm?: () => void, onCancel?: () => void}} */
  let { open = false, title = 'Подтверждение', message = '', confirmText = 'Да', cancelText = 'Отмена', danger = false, onConfirm, onCancel } = $props();

  function handleConfirm() {
    onConfirm?.();
  }
  function handleCancel() {
    onCancel?.();
  }
</script>

{#if open}
  <div class="cd-overlay" onclick={handleCancel} role="button" tabindex="-1" onkeydown={(e) => e.key === 'Escape' && handleCancel()}>
    <div class="cd-dialog" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title} tabindex="0">
      <h3 class="cd-title">{title}</h3>
      <p class="cd-message">{message}</p>
      <div class="cd-actions">
        <button class="cd-btn cd-btn--cancel" onclick={handleCancel}>{cancelText}</button>
        <button class="cd-btn" class:cd-btn--danger={danger} class:cd-btn--confirm={!danger} onclick={handleConfirm}>{confirmText}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .cd-overlay {
    position: fixed; inset: 0; z-index: 9999;
    background: var(--overlay-bg);
    backdrop-filter: var(--blur-quiet);
    display: flex; align-items: center; justify-content: center;
    animation: cd-fade-in 0.15s ease;
  }
  @keyframes cd-fade-in { from { opacity: 0; } }

  .cd-dialog {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 28px;
    max-width: 400px;
    width: 90%;
    box-shadow: var(--shadow);
    animation: cd-slide-up 0.2s ease;
  }
  @keyframes cd-slide-up { from { transform: translateY(12px); opacity: 0; } }

  .cd-title {
    font-size: var(--font-lg, 17px);
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 10px;
  }
  .cd-message {
    font-size: var(--font-base, 14px);
    color: var(--text-secondary);
    line-height: 1.6;
    margin-bottom: 24px;
  }
  .cd-actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
  }
  .cd-btn {
    padding: 8px 18px;
    border-radius: var(--radius-sm);
    font-size: var(--font-sm, 13px);
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    transition: all var(--transition-fast);
  }
  .cd-btn--cancel {
    background: transparent;
    border-color: var(--border);
    color: var(--text-secondary);
  }
  .cd-btn--cancel:hover {
    background: var(--hover-bg);
    color: var(--text-primary);
  }
  .cd-btn--confirm {
    background: var(--accent-primary);
    color: var(--text-on-accent, #fff);
  }
  .cd-btn--confirm:hover {
    background: var(--accent-hover);
  }
  .cd-btn--danger {
    background: var(--danger);
    color: var(--text-on-accent, #fff);
  }
  .cd-btn--danger:hover {
    background: var(--danger-hover);
  }
</style>
