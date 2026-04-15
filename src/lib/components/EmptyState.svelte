<script>
  /** @type {{icon?: string, title?: string, description?: string, actionText?: string, onAction?: () => void}} */
  let { icon = '', title = '', description = '', actionText = '', onAction } = $props();
</script>

<div class="es-container">
  {#if icon}
    <div class="es-icon">{icon}</div>
  {/if}
  {#if title}
    <h3 class="es-title">{title}</h3>
  {/if}
  {#if description}
    <p class="es-description">{description}</p>
  {/if}
  {#if actionText && onAction}
    <button class="es-action" onclick={onAction}>{actionText}</button>
  {/if}
</div>

<style>
  .es-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 48px 24px;
    text-align: center;
    min-height: 200px;
  }
  .es-icon {
    font-size: 40px;
    margin-bottom: 16px;
    opacity: 0.5;
    filter: grayscale(0.3);
  }
  .es-title {
    font-size: var(--font-lg, 17px);
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 8px;
  }
  .es-description {
    font-size: var(--font-base, 14px);
    color: var(--text-muted);
    max-width: 320px;
    line-height: 1.6;
    margin-bottom: 20px;
  }
  .es-action {
    padding: 10px 22px;
    background: var(--accent-primary);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-sm);
    font-size: var(--font-sm, 13px);
    font-weight: 600;
    cursor: pointer;
    transition: all var(--transition-fast);
  }
  .es-action:hover {
    background: var(--accent-hover);
    transform: translateY(-1px);
  }
</style>
