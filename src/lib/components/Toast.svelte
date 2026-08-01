<script>
  import { onMount } from 'svelte';

  /** @type {{message: string, type?: 'success'|'error'|'warning'|'info', duration?: number, onClose: () => void}} */
  let { message, type = 'info', duration = 3000, onClose } = $props();

  onMount(() => {
    const timer = setTimeout(onClose, duration);
    return () => clearTimeout(timer);
  });
</script>

<div class="toast toast-{type}" role="alert">
  <span class="toast-icon">
    {#if type === 'success'}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>
    {:else if type === 'warning'}
      <!-- 🔴 Предупреждение — свой знак и своя рамка. Прежде вид «предупреждение»
           объявлялся при вызове, но не существовал ни в типах, ни в стилях: сообщение
           о расхождении версий методики показывалось как обычная справка, а проверка
           типов фронта краснела. Инвариант «расхождение доходит до человека» держится
           текстом И видом. -->
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
    {:else if type === 'error'}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
    {:else}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
    {/if}
  </span>
  <span class="toast-msg">{message}</span>
  <button class="toast-close" onclick={onClose} aria-label="Закрыть">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
  </button>
</div>

<style>
  .toast {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: var(--bg-glass);
    backdrop-filter: var(--blur-focus);
    -webkit-backdrop-filter: var(--blur-focus);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: var(--shadow-glow);
    font-size: 12.5px;
    color: var(--text-primary);
    animation: toast-in 0.25s ease;
    max-width: 360px;
  }

  .toast-success { border-color: color-mix(in srgb, var(--success) 30%, transparent); }
  .toast-success .toast-icon { color: var(--success); }

  .toast-error { border-color: color-mix(in srgb, var(--danger) 30%, transparent); }
  .toast-error .toast-icon { color: var(--danger); }

  .toast-warning { border-color: color-mix(in srgb, var(--warning, #d98324) 45%, transparent); }
  .toast-warning .toast-icon { color: var(--warning, #d98324); }

  .toast-info .toast-icon { color: var(--accent-primary); }

  .toast-icon {
    display: flex;
    flex-shrink: 0;
  }

  .toast-msg { flex: 1; }

  .toast-close {
    display: flex;
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 2px;
    opacity: 0.6;
    transition: opacity 0.15s;
  }

  .toast-close:hover { opacity: 1; }

  @keyframes toast-in {
    from { opacity: 0; transform: translateY(8px) scale(0.96); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  /* v2.1.0 п.5.6: instant toast appearance */
  @media (prefers-reduced-motion: reduce) {
    .toast {
      animation: none;
      opacity: 1;
      transform: none;
    }
  }
</style>
