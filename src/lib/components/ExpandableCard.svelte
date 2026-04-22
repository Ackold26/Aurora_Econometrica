<script>
  /**
   * Wrapper-карточка с режимом fullscreen.
   * Оборачивает любой контент (чарт, таблицу) и даёт кнопку развернуть/свернуть.
   *
   * Props:
   *   title — заголовок карточки (то что раньше было .card-title)
   *   children — содержимое (Svelte 5 snippet)
   *
   * Поведение:
   *   - Клик по кнопке в углу → fullscreen overlay (fixed, backdrop-blur, centered)
   *   - Escape или клик по backdrop → свернуть обратно
   *   - body overflow:hidden пока открыт, чтобы страница не скроллилась позади
   *
   * @component ExpandableCard
   */
  import { onDestroy } from 'svelte';

  /**
   * @type {{ title?: string, tourKey?: string, children: import('svelte').Snippet }}
   */
  let { title = '', tourKey = '', children } = $props();

  let expanded = $state(false);

  function toggle() {
    expanded = !expanded;
  }

  function onKey(e) {
    if (e.key === 'Escape' && expanded) expanded = false;
  }

  $effect(() => {
    if (expanded) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', onKey);
    } else {
      document.body.style.overflow = '';
      window.removeEventListener('keydown', onKey);
    }
  });

  onDestroy(() => {
    document.body.style.overflow = '';
    window.removeEventListener('keydown', onKey);
  });
</script>

{#if expanded}
  <!-- Fullscreen overlay. При свёртке content перерисовывается в inline-режиме
       ниже — чарты на основе canvas/svg пересоздадутся с правильными размерами. -->
  <div
    class="overlay"
    role="dialog"
    aria-modal="true"
    aria-label={title || 'Развёрнутая карточка'}
    onclick={toggle}
  >
    <div
      class="overlay-card"
      role="document"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
    >
      <div class="overlay-header">
        {#if title}<div class="overlay-title">{title}</div>{/if}
        <button
          type="button"
          class="btn-toggle"
          onclick={toggle}
          title="Свернуть (Esc)"
          aria-label="Свернуть"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 3V5H3M11 3V5H13M3 11H5V13M11 13V11H13" />
          </svg>
        </button>
      </div>
      <div class="overlay-body">
        <div class="overlay-content">
          {@render children()}
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- Inline-рендер карточки. Когда expanded=true, сам chart отрисован в overlay,
     а здесь показываем placeholder чтобы не рендерить один и тот же canvas дважды
     (это ломает chart.js / matplotlib и даёт пустые графики). -->
<div class="card" data-tour={tourKey || undefined}>
  <div class="card-header">
    {#if title}<div class="card-title">{title}</div>{/if}
    <button
      type="button"
      class="btn-toggle card-toggle"
      onclick={toggle}
      title={expanded ? 'Свернуть (Esc)' : 'Развернуть на весь экран'}
      aria-label={expanded ? 'Свернуть' : 'Развернуть'}
    >
      {#if expanded}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 3V5H3M11 3V5H13M3 11H5V13M11 13V11H13" />
        </svg>
      {:else}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 5V3H5M11 3H13V5M13 11V13H11M5 13H3V11" />
        </svg>
      {/if}
    </button>
  </div>
  {#if !expanded}
    <div class="card-body">
      {@render children()}
    </div>
  {:else}
    <!-- Placeholder чтобы не схлопнулась высота карточки на странице -->
    <div class="card-placeholder">
      <span>График развёрнут на весь экран</span>
      <button type="button" class="placeholder-collapse" onclick={toggle}>Свернуть</button>
    </div>
  {/if}
</div>

<style>
  .card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-width: 0; /* чтобы внутри grid-cell flex/canvas ужимались нормально */
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 0; /* gap: 12px у .card сам даёт отступ */
  }

  .card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    line-height: 1.3;
  }

  .card-body {
    flex: 1;
    min-height: 0;
  }

  .card-placeholder {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 24px 16px;
    color: var(--text-muted);
    font-size: 13px;
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 6%, transparent);
    border: 1px dashed color-mix(in srgb, var(--accent-primary, #3b82f6) 25%, transparent);
    border-radius: 8px;
  }

  .placeholder-collapse {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .placeholder-collapse:hover {
    border-color: var(--accent-primary);
    color: var(--accent-primary);
  }

  .btn-toggle {
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-muted);
    padding: 4px 6px;
    border-radius: 6px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
  }
  .btn-toggle:hover {
    color: var(--text-primary);
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 10%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
  }

  /* ── Fullscreen overlay ───────────────────────────────────────────────── */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: color-mix(in srgb, #000 58%, transparent);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    display: flex;
    align-items: stretch;
    justify-content: stretch;
    padding: 24px;
    animation: fadeIn 0.12s ease-out;
  }

  .overlay-card {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 16px;
    background: var(--bg-surface, #0f1115);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    border-radius: 14px;
    padding: 20px 24px;
    overflow: hidden;
    box-shadow: 0 20px 60px rgba(0,0,0,0.45);
  }

  .overlay-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-shrink: 0;
  }

  .overlay-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .overlay-body {
    flex: 1;
    min-height: 0;
    overflow: auto;
    /* Центровка содержимого в fullscreen — чтобы график не прилипал к верху,
       когда он меньше доступной высоты. */
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px 0;
  }

  .overlay-content {
    width: 100%;
    max-width: 100%;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    justify-content: center;
  }

  /* Увеличиваем высоту чартов в fullscreen — ~3× inline (inline 280px → fullscreen ~70vh).
     ECharts-контейнеры имеют inline style="height:280px" → нужен !important чтобы перезаписать.
     ResizeObserver echarts подхватит новую высоту, SVG waterfall ресайзится через viewBox.
     Действует ТОЛЬКО в overlay, не на inline-виде на странице. */
  .overlay-content :global(> *) {
    flex: 1;
    height: 70vh !important;
    min-height: 70vh;
  }

  /* Внутри overlay даём canvas/img растянуться по ширине;
     высоту оставляем естественную (ResizeObserver сам подхватит) */
  .overlay-body :global(canvas),
  .overlay-body :global(img),
  .overlay-body :global(svg) {
    max-width: 100%;
    height: auto;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }
</style>
