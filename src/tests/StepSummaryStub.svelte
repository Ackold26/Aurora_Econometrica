<script>
  /**
   * StepSummaryStub - minimal test double for StepSummary.svelte.
   * Used by scenario-wizard.test.js to avoid diagnostics crash.
   */
  const { onRun = null, onEditExpert = null } = $props();
</script>

<div class="step-summary-stub">
  <button type="button" onclick={() => onRun?.()}>Запустить анализ</button>
  <button type="button" onclick={() => onEditExpert?.()}>Expert mode</button>
</div>
