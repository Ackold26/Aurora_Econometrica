<script>
  import { page } from '$app/stores';
</script>

<div class="error-container">
  <div class="error-card">
    <h1 class="error-code">{$page.status}</h1>
    <p class="error-message">{$page.error?.message || 'Произошла непредвиденная ошибка'}</p>
    <button class="retry-btn" onclick={() => window.location.reload()}>
      Перезагрузить
    </button>
  </div>
</div>

<style>
  .error-container {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    background: var(--bg-primary, #1a1a2e);
    color: var(--text-primary, #e0e0e0);
    font-family: system-ui, -apple-system, sans-serif;
  }
  .error-card {
    text-align: center;
    padding: 2rem;
    max-width: 400px;
  }
  .error-code {
    font-size: 4rem;
    font-weight: 700;
    color: var(--accent, #818cf8);
    margin: 0 0 0.5rem;
  }
  .error-message {
    font-size: 1.1rem;
    opacity: 0.8;
    margin-bottom: 1.5rem;
  }
  .retry-btn {
    padding: 0.6rem 1.5rem;
    border: 1px solid var(--accent, #818cf8);
    background: transparent;
    color: var(--accent, #818cf8);
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.95rem;
    transition: background 0.2s;
  }
  .retry-btn:hover {
    background: rgba(129, 140, 248, 0.1);
  }
</style>
