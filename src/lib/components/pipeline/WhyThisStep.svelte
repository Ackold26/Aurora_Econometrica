<script>
  /**
   * WhyThisStep — v1.3.0 skeleton (per ADR-015 P0.9 + Stage 4 educational).
   *
   * Раскрывающаяся секция с 4 блоками:
   * 1. Что мы делаем.
   * 2. Зачем это нужно.
   * 3. На что обратить внимание.
   * 4. Что будет дальше.
   *
   * Stage 2: skeleton — рендерит content из props. Stage 4: финальный content
   * через contextual-help.json + mastery-aware visibility (по default collapse
   * для intermediate/expert; expanded для novice).
   *
   * @component WhyThisStep
   */

  const {
    stepId,       // 'validate' | 'model' | 'decompose' | 'optimize' | 'report' | sub-step ID
    title = 'Зачем этот шаг?',
    whatWeDo,     // string
    whyNeed,      // string
    attentionTo,  // string[] (3-5 bullets)
    whatsNext,    // string
    defaultOpen = false, // override mastery default
  } = $props();

  let isOpen = $state(defaultOpen);

  function toggle() {
    isOpen = !isOpen;
  }
</script>

<details class="why-step" open={isOpen} ontoggle={toggle}>
  <summary>
    <span class="icon">💡</span>
    <span class="summary-text">{title}</span>
    <span class="chevron">{isOpen ? '▾' : '▸'}</span>
  </summary>
  <div class="content">
    {#if whatWeDo}
      <section>
        <h4>Что мы делаем</h4>
        <p>{whatWeDo}</p>
      </section>
    {/if}
    {#if whyNeed}
      <section>
        <h4>Зачем это нужно</h4>
        <p>{whyNeed}</p>
      </section>
    {/if}
    {#if attentionTo && attentionTo.length > 0}
      <section>
        <h4>На что обратить внимание</h4>
        <ul>
          {#each attentionTo as item}
            <li>{item}</li>
          {/each}
        </ul>
      </section>
    {/if}
    {#if whatsNext}
      <section>
        <h4>Что будет дальше</h4>
        <p>{whatsNext}</p>
      </section>
    {/if}
  </div>
</details>

<style>
  .why-step {
    background: color-mix(in srgb, var(--accent-primary) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 18%, transparent);
    border-radius: var(--radius-card, 10px);
    padding: 0;
    margin: 8px 0;
    overflow: hidden;
  }
  summary {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    cursor: pointer;
    user-select: none;
    list-style: none;
  }
  summary::-webkit-details-marker { display: none; }
  .icon { font-size: 16px; }
  .summary-text {
    flex: 1;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .chevron {
    font-size: 12px;
    color: var(--text-muted);
  }
  .content {
    padding: 0 14px 14px;
    border-top: 1px solid color-mix(in srgb, var(--accent-primary) 18%, transparent);
    background: var(--bg-card);
  }
  .content section {
    padding-top: 12px;
  }
  .content h4 {
    margin: 0 0 4px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--accent-primary);
    font-weight: 700;
  }
  .content p, .content ul {
    margin: 0;
    font-size: 13px;
    line-height: 1.55;
    color: var(--text-secondary);
  }
  .content ul { padding-left: 20px; }
  .content li { padding: 2px 0; }
</style>
