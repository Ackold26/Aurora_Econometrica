<script>
  /** @type {{count?: number, height?: string}} */
  let { count = 3, height = '120px' } = $props();
</script>

<div class="sk-grid">
  {#each Array(count) as _, i}
    <div class="sk-card" style="height: {height}; animation-delay: {i * 0.1}s">
      <div class="sk-accent"></div>
      <div class="sk-body">
        <div class="sk-line sk-line--title"></div>
        <div class="sk-line sk-line--text"></div>
        <div class="sk-line sk-line--short"></div>
      </div>
    </div>
  {/each}
</div>

<style>
  .sk-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 16px;
    width: 100%;
  }
  .sk-card {
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius);
    overflow: hidden;
    animation: sk-pulse 1.5s ease-in-out infinite;
  }
  @keyframes sk-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
  .sk-accent {
    height: 3px;
    background: linear-gradient(90deg, transparent, var(--border), transparent);
    animation: sk-shimmer 2s linear infinite;
    background-size: 200% 100%;
  }
  @keyframes sk-shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }
  .sk-body {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .sk-line {
    height: 12px;
    border-radius: 6px;
    background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-card-hover) 50%, var(--bg-tertiary) 75%);
    background-size: 200% 100%;
    animation: sk-shimmer 2s linear infinite;
  }
  .sk-line--title {
    width: 60%;
    height: 14px;
  }
  .sk-line--text {
    width: 90%;
  }
  .sk-line--short {
    width: 40%;
  }
</style>
