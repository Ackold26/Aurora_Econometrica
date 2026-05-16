<script>
  /**
   * Multi-scenario comparison route - v2.0.0 (ADR-019 §7).
   *
   * Page shown после Optimize stage когда у project есть ≥2 scenarios.
   * Embeds MultiScenarioPage с overlay chart, comparison table,
   * diff narratives, export actions.
   *
   * @route /pipeline/compare
   */
  import MultiScenarioPage from '$lib/components/pipeline/MultiScenarioPage.svelte';
  import { goto } from '$app/navigation';

  /**
   * TODO Phase E: wire actual scenarios от project state.
   * Currently empty array → empty state CTA «Добавьте сценарий чтобы сравнить».
   * @type {any[]}
   */
  let scenarios = $state([]);

  /** @type {any} */
  let baseline = $state(null);

  function handleAccept(/** @type {any} */ scenario) {
    // TODO Phase E: persist accepted scenario, navigate back к Optimize
    console.log('[Compare] Accept scenario:', scenario?.name);
    goto('/pipeline');
  }

  function handleDuplicate(/** @type {any} */ scenario) {
    // TODO Phase E: clone scenario, add к store
    console.log('[Compare] Duplicate scenario:', scenario?.name);
  }

  function handleDelete(/** @type {any} */ scenario) {
    // TODO Phase E: remove scenario from store
    console.log('[Compare] Delete scenario:', scenario?.name);
  }
</script>

<svelte:head>
  <title>Aurora MMM Optimizer - Сравнение сценариев</title>
</svelte:head>

<main class="compare-route">
  <header class="route-header">
    <button class="back-link" onclick={() => goto('/pipeline')}>← Назад к pipeline</button>
    <h1>Сравнение сценариев</h1>
  </header>

  <MultiScenarioPage
    {scenarios}
    {baseline}
    onAccept={handleAccept}
    onDuplicate={handleDuplicate}
    onDelete={handleDelete}
  />
</main>

<style>
  .compare-route {
    padding: 24px 32px;
    max-width: 1400px;
    margin: 0 auto;
  }
  .route-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
  }
  .route-header h1 {
    margin: 0;
    font-size: 22px;
    color: var(--text-primary);
  }
  .back-link {
    background: none;
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 6px 14px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px;
  }
  .back-link:hover {
    border-color: var(--gold, #c9a449);
    color: var(--gold, #c9a449);
  }
</style>
