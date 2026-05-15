<script>
  /**
   * Tooltip — универсальная подсказка при наведении/фокусе.
   *
   * Props:
   *   text       — текст подсказки (обязательный)
   *   position   — 'auto' (по умолчанию) | 'top' | 'bottom' | 'left' | 'right'
   *   delay      — задержка появления в мс (по умолчанию 300)
   *   id         — идентификатор для aria-describedby (генерируется автоматически если не передан)
   *
   * Использование:
   *   <Tooltip text="Описание метрики">
   *     <button>ROAS</button>
   *   </Tooltip>
   *
   * Keyboard a11y:
   *   - Появляется при focus на дочернем элементе
   *   - ESC закрывает немедленно
   *   - aria-describedby связывает с текстом подсказки
   *
   * prefers-reduced-motion: transition-duration = 0ms.
   *
   * @component Tooltip
   */
  import { onDestroy } from 'svelte';

  /**
   * @type {{
   *   text: string,
   *   position?: 'auto' | 'top' | 'bottom' | 'left' | 'right',
   *   delay?: number,
   *   id?: string,
   *   children: import('svelte').Snippet,
   * }}
   */
  let {
    text,
    position = 'auto',
    delay = 300,
    id,
    children,
  } = $props();

  // Генерируем уникальный id если не передан
  const tooltipId = id ?? `tooltip-${Math.random().toString(36).slice(2, 9)}`;

  let visible = $state(false);
  /** @type {HTMLElement | null} */
  let wrapperEl = $state(null);
  /** @type {HTMLElement | null} */
  let tooltipEl = $state(null);
  /** @type {number | null} */
  let showTimer = null;
  /** @type {number | null} */
  let hideTimer = null;

  // Computed position based on viewport when 'auto'
  /** @type {'top' | 'bottom' | 'left' | 'right'} */
  let computedPosition = $state('top');

  function scheduleShow() {
    if (hideTimer !== null) { clearTimeout(hideTimer); hideTimer = null; }
    if (visible) return;
    showTimer = window.setTimeout(() => {
      visible = true;
      // Resolve auto position after render in next frame
      if (position === 'auto') {
        requestAnimationFrame(resolveAutoPosition);
      } else {
        computedPosition = /** @type {any} */ (position);
      }
    }, delay);
  }

  function scheduleHide() {
    if (showTimer !== null) { clearTimeout(showTimer); showTimer = null; }
    hideTimer = window.setTimeout(() => {
      visible = false;
    }, 100);
  }

  function hideImmediate() {
    if (showTimer !== null) { clearTimeout(showTimer); showTimer = null; }
    if (hideTimer !== null) { clearTimeout(hideTimer); hideTimer = null; }
    visible = false;
  }

  function resolveAutoPosition() {
    if (!wrapperEl || !tooltipEl) {
      computedPosition = 'top';
      return;
    }
    const wRect = wrapperEl.getBoundingClientRect();
    const tRect = tooltipEl.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const pad = 8;

    // Prefer top, fallback bottom, fallback right, fallback left
    if (wRect.top - tRect.height - pad >= 0) {
      computedPosition = 'top';
    } else if (wRect.bottom + tRect.height + pad <= vh) {
      computedPosition = 'bottom';
    } else if (wRect.right + tRect.width + pad <= vw) {
      computedPosition = 'right';
    } else {
      computedPosition = 'left';
    }
  }

  /** @param {KeyboardEvent} e */
  function handleKeydown(e) {
    if (e.key === 'Escape' && visible) {
      e.stopPropagation();
      hideImmediate();
    }
  }

  onDestroy(() => {
    if (showTimer !== null) clearTimeout(showTimer);
    if (hideTimer !== null) clearTimeout(hideTimer);
  });
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<span
  class="tooltip-wrapper"
  bind:this={wrapperEl}
  onmouseenter={scheduleShow}
  onmouseleave={scheduleHide}
  onfocus={scheduleShow}
  onblur={scheduleHide}
  onkeydown={handleKeydown}
  role="group"
>
  <!-- Slot: дочерний элемент получает aria-describedby -->
  <span
    class="tooltip-trigger"
    aria-describedby={visible ? tooltipId : undefined}
  >
    {@render children?.()}
  </span>

  {#if visible && text}
    <span
      bind:this={tooltipEl}
      id={tooltipId}
      class="tooltip-bubble"
      class:pos-top={computedPosition === 'top'}
      class:pos-bottom={computedPosition === 'bottom'}
      class:pos-left={computedPosition === 'left'}
      class:pos-right={computedPosition === 'right'}
      role="tooltip"
    >
      {text}
    </span>
  {/if}
</span>

<style>
  .tooltip-wrapper {
    position: relative;
    display: inline-flex;
    align-items: center;
  }

  .tooltip-trigger {
    display: contents;
  }

  .tooltip-bubble {
    position: absolute;
    z-index: 9500;
    padding: 7px 10px;
    background: var(--bg-surface-focus, #1e293b);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    color: var(--text-primary, #e2e8f0);
    font-size: 12px;
    font-weight: 400;
    line-height: 1.5;
    white-space: normal;
    max-width: 280px;
    min-width: 120px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4), 0 1px 4px rgba(0, 0, 0, 0.3);
    pointer-events: none;
    /* Entrance animation */
    animation: tooltip-in 0.15s ease-out both;
  }

  /* Positioning offsets */
  .tooltip-bubble.pos-top {
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
  }
  .tooltip-bubble.pos-bottom {
    top: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
  }
  .tooltip-bubble.pos-left {
    right: calc(100% + 8px);
    top: 50%;
    transform: translateY(-50%);
  }
  .tooltip-bubble.pos-right {
    left: calc(100% + 8px);
    top: 50%;
    transform: translateY(-50%);
  }

  /* Small arrow pointer */
  .tooltip-bubble::after {
    content: '';
    position: absolute;
    width: 6px;
    height: 6px;
    background: var(--bg-surface-focus, #1e293b);
    border: 1px solid rgba(255, 255, 255, 0.12);
  }
  .tooltip-bubble.pos-top::after {
    bottom: -4px;
    left: 50%;
    transform: translateX(-50%) rotate(45deg);
    border-top: none;
    border-left: none;
  }
  .tooltip-bubble.pos-bottom::after {
    top: -4px;
    left: 50%;
    transform: translateX(-50%) rotate(45deg);
    border-bottom: none;
    border-right: none;
  }
  .tooltip-bubble.pos-left::after {
    right: -4px;
    top: 50%;
    transform: translateY(-50%) rotate(45deg);
    border-top: none;
    border-right: none;
  }
  .tooltip-bubble.pos-right::after {
    left: -4px;
    top: 50%;
    transform: translateY(-50%) rotate(45deg);
    border-bottom: none;
    border-left: none;
  }

  @keyframes tooltip-in {
    from { opacity: 0; transform: translateX(-50%) translateY(4px); }
    to   { opacity: 1; transform: translateX(-50%) translateY(0); }
  }

  /* prefers-reduced-motion: instant appearance, no animation */
  @media (prefers-reduced-motion: reduce) {
    .tooltip-bubble {
      animation: none;
      transition: none;
    }
  }
</style>
