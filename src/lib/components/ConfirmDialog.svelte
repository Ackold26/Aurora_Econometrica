<script>
  /**
   * Confirm dialog через native HTML5 <dialog> - встроенный focus trap,
   * Escape-handling, ::backdrop pseudo, a11y правильный.
   *
   * @component ConfirmDialog
   */
  /** @type {{open?: boolean, title?: string, message?: string, confirmText?: string, cancelText?: string, danger?: boolean, onConfirm?: () => void, onCancel?: () => void}} */
  let { open = false, title = 'Подтверждение', message = '', confirmText = 'Да', cancelText = 'Отмена', danger = false, onConfirm, onCancel } = $props();

  /** @type {HTMLDialogElement | undefined} */
  let dialogEl = $state();

  // Reactive sync: prop `open` → показываем/скрываем native dialog
  $effect(() => {
    if (!dialogEl) return;
    if (open && !dialogEl.open) {
      dialogEl.showModal();
    } else if (!open && dialogEl.open) {
      dialogEl.close();
    }
  });

  function handleConfirm() {
    onConfirm?.();
  }

  /** @param {Event} e */
  function handleCancel(e) {
    e.preventDefault(); // browser close-on-backdrop не должен скипнуть onCancel
    onCancel?.();
  }

  /** Backdrop click → cancel. Dialog сам по клику вне не закрывается - ловим вручную. */
  /** @param {MouseEvent} e */
  function onDialogClick(e) {
    if (e.target === dialogEl) {
      onCancel?.();
    }
  }
</script>

<dialog
  bind:this={dialogEl}
  oncancel={handleCancel}
  onclick={onDialogClick}
  class="cd-dialog"
  aria-labelledby="cd-title"
>
  <h3 class="cd-title" id="cd-title">{title}</h3>
  <p class="cd-message">{message}</p>
  <div class="cd-actions">
    <button type="button" class="cd-btn cd-btn--cancel" onclick={() => onCancel?.()}>{cancelText}</button>
    <button type="button" class="cd-btn" class:cd-btn--danger={danger} class:cd-btn--confirm={!danger} onclick={handleConfirm}>{confirmText}</button>
  </div>
</dialog>

<style>
  dialog.cd-dialog {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg, 12px);
    padding: 28px;
    max-width: 400px;
    width: 90%;
    color: var(--text-primary);
    box-shadow: var(--shadow, 0 24px 60px rgba(0, 0, 0, 0.6));
    /* native centering via margin:auto */
  }
  dialog.cd-dialog:not([open]) { display: none; }
  dialog.cd-dialog[open] {
    animation: cd-slide-up 0.2s ease;
  }
  dialog.cd-dialog::backdrop {
    background: var(--overlay-bg, rgba(0, 0, 0, 0.55));
    backdrop-filter: var(--blur-quiet, blur(4px));
    animation: cd-fade-in 0.15s ease;
  }
  @keyframes cd-slide-up { from { transform: translateY(12px); opacity: 0; } }
  @keyframes cd-fade-in { from { opacity: 0; } }

  .cd-title {
    font-size: var(--font-lg, 17px);
    font-weight: 700;
    color: var(--text-primary);
    margin: 0 0 10px 0;
  }
  .cd-message {
    font-size: var(--font-base, 14px);
    color: var(--text-secondary);
    line-height: 1.6;
    margin: 0 0 24px 0;
  }
  .cd-actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
  }
  .cd-btn {
    padding: 8px 18px;
    border-radius: var(--radius-sm, 6px);
    font-size: var(--font-sm, 13px);
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    font-family: inherit;
    transition: all var(--transition-fast, 0.15s);
  }
  .cd-btn--cancel {
    background: transparent;
    border-color: var(--border);
    color: var(--text-secondary);
  }
  .cd-btn--cancel:hover {
    background: var(--hover-bg, rgba(255, 255, 255, 0.04));
    color: var(--text-primary);
  }
  .cd-btn--confirm {
    background: var(--accent-primary);
    color: var(--text-on-accent, #fff);
  }
  .cd-btn--confirm:hover {
    background: var(--accent-hover, color-mix(in srgb, var(--accent-primary) 85%, white));
  }
  .cd-btn--danger {
    background: var(--danger);
    color: var(--text-on-accent, #fff);
  }
  .cd-btn--danger:hover {
    background: var(--danger-hover, color-mix(in srgb, var(--danger) 85%, white));
  }

  /* v2.1.0 п.5.6: instant dialog appearance */
  @media (prefers-reduced-motion: reduce) {
    dialog.cd-dialog[open] {
      animation: none;
      opacity: 1;
      transform: none;
    }
    dialog.cd-dialog::backdrop {
      animation: none;
      opacity: 1;
    }
  }
</style>
