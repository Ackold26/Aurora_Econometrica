<script>
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';

  /**
   * @type {{
   *   title: string,
   *   content: string,
   *   level?: number,
   *   onRefine?: (title: string) => void,
   * }}
   */
  let { title, content, level = 2, onRefine } = $props();

  let collapsed = $state(false);
  let copied = $state(false);

  /** @param {string} md */
  function renderMd(md) {
    return DOMPurify.sanitize(/** @type {string} */ (marked.parse(md)));
  }

  function copySection() {
    const text = title ? `## ${title}\n\n${content}` : content;
    navigator.clipboard.writeText(text);
    copied = true;
    setTimeout(() => { copied = false; }, 2000);
  }

  function handleRefine() {
    if (onRefine && title) onRefine(title);
  }
</script>

<div class="response-section" class:collapsed>
  {#if title}
    <div class="section-header" role="button" tabindex="0" onclick={() => collapsed = !collapsed} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); collapsed = !collapsed; } }}>
      <svg class="section-chevron" width="12" height="12" viewBox="0 0 12 12">
        <path d="M3 4.5l3 3 3-3" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      </svg>
      <span class="section-title">{title}</span>
      <div class="section-actions">
        <button class="section-action" onclick={(e) => { e.stopPropagation(); copySection(); }} title={copied ? 'Скопировано!' : 'Копировать'}>
          {copied ? '✓' : '⧉'}
        </button>
        {#if onRefine}
          <button class="section-action refine-action" onclick={(e) => { e.stopPropagation(); handleRefine(); }} title="Доработать">
            ✎
          </button>
        {/if}
      </div>
    </div>
  {/if}

  {#if !collapsed}
    <div class="section-content markdown-body">
      {@html renderMd(content)}
    </div>
  {/if}
</div>

<style>
  .response-section {
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
    border-radius: 10px;
    overflow: hidden;
    transition: border-color 150ms ease-out;
  }

  .response-section:hover {
    border-color: var(--border, rgba(255,255,255,0.16));
  }

  /* ─── Header ─── */
  .section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 10px 14px;
    background: var(--hover-bg);
    border: none;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.10));
    color: var(--text-primary, #EAEAF0);
    font-size: 13.5px;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    text-align: left;
    transition: background 150ms ease-out;
  }

  .section-header:hover {
    background: var(--hover-bg);
  }

  .collapsed .section-header {
    border-bottom: none;
  }

  .section-chevron {
    transition: transform 200ms ease-out;
    opacity: 0.5;
    flex-shrink: 0;
  }

  .collapsed .section-chevron {
    transform: rotate(-90deg);
  }

  .section-title {
    flex: 1;
  }

  /* ─── Actions ─── */
  .section-actions {
    display: flex;
    gap: 4px;
    opacity: 0;
    transition: opacity 150ms;
  }

  .section-header:hover .section-actions {
    opacity: 1;
  }

  .section-action {
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    color: var(--text-muted, #7A7A90);
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
    transition: all 150ms;
  }

  .section-action:hover {
    background: var(--hover-bg, rgba(255,255,255,0.10));
    color: var(--text-primary, #EAEAF0);
  }

  .refine-action:hover {
    color: var(--accent-primary, #2E5BFF);
  }

  /* ─── Content ─── */
  .section-content {
    padding: 12px 14px;
    font-size: 14px;
    line-height: 1.6;
    color: var(--text-primary, #EAEAF0);
  }

</style>
