<script>
  /**
   * MigrationCompletedToast - Phase 2.16 / Audit P-customer-confidence.
   *
   * Visible briefly after successful project.json migration (Phase 1.4).
   * Builds customer trust: explicit signal that data was updated, what
   * changed, и где documented. Auto-dismisses after 10s; manual close ×.
   *
   * Triggered via prop binding from pipeline/+layout.svelte после
   * econ_migrate_project returns status='ok'.
   *
   * Reuses existing premium tier-1 visual vocabulary (gold accent +
   * subtle slide-in via prefers-reduced-motion-aware CSS).
   */
  import { onMount } from 'svelte';
  import { Check } from 'lucide-svelte';

  /**
   * @type {{
   *   show?: boolean,
   *   fromVersion?: string,
   *   toVersion?: string,
   *   movedCount?: number,
   *   onDismiss?: () => void,
   *   autoDismissMs?: number,
   * }}
   */
  const {
    show = false,
    fromVersion = '',
    toVersion = '',
    movedCount = 0,
    onDismiss = () => {},
    autoDismissMs = 10000,
  } = $props();

  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let dismissTimer = $state(undefined);

  $effect(() => {
    if (show && autoDismissMs > 0) {
      dismissTimer = setTimeout(() => onDismiss(), autoDismissMs);
      return () => {
        if (dismissTimer) clearTimeout(dismissTimer);
      };
    }
  });

  function handleClose() {
    if (dismissTimer) clearTimeout(dismissTimer);
    onDismiss();
  }
</script>

{#if show}
  <div
    class="migration-toast"
    role="status"
    aria-live="polite"
    data-testid="migration-completed-toast"
  >
    <div class="toast-icon" aria-hidden="true"><Check size={16} strokeWidth={2} /></div>
    <div class="toast-content">
      <strong class="toast-title">Проект обновлён до v{toVersion}</strong>
      <p class="toast-detail">
        {#if movedCount > 0}
          Переклассифицировано {movedCount}
          {movedCount === 1 ? 'столбец' : (movedCount < 5 ? 'столбца' : 'столбцов')}
          (SOM / SOV / share_of_*) - исключены из модели как derived metrics
          (избежание endogeneity).
        {:else}
          Формат данных обновлён без изменения классификации.
        {/if}
        <br />
        <span class="toast-meta">Предыдущая версия v{fromVersion} сохранена в backup-файле.</span>
      </p>
    </div>
    <button
      type="button"
      class="toast-close"
      onclick={handleClose}
      aria-label="Закрыть уведомление"
    >×</button>
  </div>
{/if}

<style>
  .migration-toast {
    position: fixed;
    bottom: 24px;
    right: 24px;
    max-width: 460px;
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 14px 18px;
    background: var(--bg-card, #181824);
    border: 1px solid color-mix(in srgb, var(--success, #10B981) 32%, transparent);
    border-left: 3px solid var(--success, #10B981);
    border-radius: var(--radius-card, 12px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
    z-index: 1000;
    color: var(--text-primary);
  }

  @media (prefers-reduced-motion: no-preference) {
    .migration-toast {
      animation: slide-in 0.3s ease-out;
    }
    @keyframes slide-in {
      from { transform: translateY(8px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
  }

  .toast-icon {
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--success, #10B981);
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 700;
  }
  .toast-content {
    flex: 1;
    min-width: 0;
  }
  .toast-title {
    display: block;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--success, #10B981);
    margin-bottom: 4px;
  }
  .toast-detail {
    margin: 0;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-secondary, #b6b6c5);
  }
  .toast-meta {
    font-size: 11.5px;
    color: var(--text-muted, #7A7A90);
  }
  .toast-close {
    flex-shrink: 0;
    background: transparent;
    border: none;
    color: var(--text-muted, #7A7A90);
    font-size: 20px;
    cursor: pointer;
    padding: 0 4px;
    line-height: 1;
    transition: color 0.15s;
  }
  .toast-close:hover {
    color: var(--text-primary);
  }
</style>
