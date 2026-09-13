<script>
  /**
   * Tooltip - универсальная подсказка при наведении/фокусе.
   *
   * Props:
   *   text       - текст подсказки (обязательный)
   *   position   - 'auto' (по умолчанию) | 'top' | 'bottom' | 'left' | 'right'
   *   delay      - задержка появления в мс (по умолчанию 300)
   *   id         - идентификатор для aria-describedby (генерируется автоматически если не передан)
   *
   * Использование:
   *   <Tooltip text="Описание метрики">
   *     <button>ROAS</button>
   *   </Tooltip>
   *
   * Keyboard a11y:
   *   - Появляется при focus на дочернем элементе
   *   - ESC закрывает немедленно (и с фокуса, и с наведения мышью)
   *   - aria-describedby связывает с текстом подсказки
   *
   * prefers-reduced-motion: transition-duration = 0ms.
   *
   * 🔴 2026-09-13 (снимок владельца, шаг «Отчёт»): пузырь живёт в КОРНЕ документа,
   * а не внутри обёртки. Причина - класс дефекта: пузырь был `position: absolute`
   * внутри `.tooltip-wrapper`, а место под него считалось по окну. Режет же его не
   * окно, а ближайший предок с прокруткой или `overflow: hidden` (`.pipeline-main`
   * и любая карточка с прокруткой): расчёт говорил «сверху места полно», подсказка
   * раскрывалась вверх и попадала под нож контейнера - первых строк не видно.
   * Лечение закрывает ОБА случая сразу:
   *   1. предок-обрезатель - пузырь вынесен в <body> (action `portalToBody`),
   *      никакой предок его больше не кадрирует;
   *   2. край окна - `position: fixed` по координатам триггера + прижим к окну
   *      (`place()`), так что пузырь всегда помещается целиком.
   * Проверяется измерением: getBoundingClientRect() пузыря против границ окна у
   * самого верхнего и самого нижнего элемента - обе рамки внутри окна.
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

  // Сторона, с которой раскрылся пузырь (для стрелки-указателя).
  /** @type {'top' | 'bottom' | 'left' | 'right'} */
  let computedPosition = $state('top');

  /** Координаты пузыря в системе координат окна (position: fixed). */
  let bubbleX = $state(0);
  let bubbleY = $state(0);
  /** Смещение стрелки внутри пузыря: когда пузырь прижат к краю окна, он уже не
   *  отцентрован по элементу, а стрелка обязана продолжать указывать на элемент. */
  let arrowX = $state(0);
  let arrowY = $state(0);
  /** Пузырь уже измерен и поставлен на место. До этого он в разметке (иначе
   *  нечего мерить), но невидим - иначе владелец увидел бы кадр в углу экрана. */
  let placed = $state(false);

  /** Зазор между элементом и пузырём. */
  const GAP = 8;
  /** Минимальный отступ пузыря от края окна. */
  const EDGE = 8;

  /**
   * Переносит пузырь в корень документа.
   *
   * 🔴 Измерено 13.09: Svelte снимает разметку блока РАНЬШЕ, чем разрушает
   * действие. Значит возвращать узел на исходное место в destroy нельзя - он
   * воскресал бы уже после снятия и висел в обёртке навсегда (три случая в
   * tooltip.test.js падали именно так). destroy только подчищает за собой, если
   * узел почему-то ещё в документе.
   *
   * Блок {#if} содержит РОВНО один элемент - Svelte снимает его одним
   * `node.remove()`, без обхода соседей. Это условие закреплено случаем
   * «соседи в корне документа не пострадали»: добавите второй узел в блок -
   * он упадёт.
   *
   * @param {HTMLElement} node
   */
  function portalToBody(node) {
    document.body.appendChild(node);
    return {
      destroy() {
        node.remove();
      },
    };
  }

  /**
   * Считает сторону и координаты пузыря по прямоугольнику триггера.
   * Единственная система отсчёта - окно: пузырь `fixed`, предки на него не влияют.
   */
  function place() {
    if (!wrapperEl || !tooltipEl) return;
    const w = wrapperEl.getBoundingClientRect();
    const t = tooltipEl.getBoundingClientRect();
    const vw = window.innerWidth || document.documentElement.clientWidth;
    const vh = window.innerHeight || document.documentElement.clientHeight;

    /** @type {'top' | 'bottom' | 'left' | 'right'} */
    let side = position === 'auto' ? 'top' : /** @type {any} */ (position);
    if (position === 'auto') {
      // Порядок предпочтения прежний: сверху, снизу, справа, слева.
      if (w.top - t.height - GAP >= EDGE) side = 'top';
      else if (w.bottom + t.height + GAP <= vh - EDGE) side = 'bottom';
      else if (w.right + t.width + GAP <= vw - EDGE) side = 'right';
      else if (w.left - t.width - GAP >= EDGE) side = 'left';
      // Места не хватает нигде (пузырь выше окна) - идём к более просторной
      // стороне, а прижим ниже всё равно удержит пузырь внутри окна.
      else side = w.top >= vh - w.bottom ? 'top' : 'bottom';
    }

    let x = 0;
    let y = 0;
    if (side === 'top') {
      x = w.left + w.width / 2 - t.width / 2;
      y = w.top - t.height - GAP;
    } else if (side === 'bottom') {
      x = w.left + w.width / 2 - t.width / 2;
      y = w.bottom + GAP;
    } else if (side === 'left') {
      x = w.left - t.width - GAP;
      y = w.top + w.height / 2 - t.height / 2;
    } else {
      x = w.right + GAP;
      y = w.top + w.height / 2 - t.height / 2;
    }

    // Прижим к окну: пузырь обязан помещаться целиком по обеим осям.
    const maxX = Math.max(EDGE, vw - t.width - EDGE);
    const maxY = Math.max(EDGE, vh - t.height - EDGE);
    const fx = Math.min(Math.max(x, EDGE), maxX);
    const fy = Math.min(Math.max(y, EDGE), maxY);

    bubbleX = Math.round(fx);
    bubbleY = Math.round(fy);
    arrowX = Math.round(clamp(w.left + w.width / 2 - fx, 12, Math.max(12, t.width - 12)));
    arrowY = Math.round(clamp(w.top + w.height / 2 - fy, 12, Math.max(12, t.height - 12)));
    computedPosition = side;
    placed = true;
  }

  /**
   * @param {number} v
   * @param {number} lo
   * @param {number} hi
   */
  function clamp(v, lo, hi) {
    return Math.min(Math.max(v, lo), hi);
  }

  function scheduleShow() {
    if (hideTimer !== null) { clearTimeout(hideTimer); hideTimer = null; }
    if (visible) return;
    showTimer = window.setTimeout(() => {
      placed = false;
      visible = true;
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

  /** @param {KeyboardEvent} e */
  function handleKeydown(e) {
    if (e.key === 'Escape' && visible) {
      e.stopPropagation();
      hideImmediate();
    }
  }

  /** Esc для подсказки, поднятой мышью: фокуса на обёртке нет, её onkeydown
   *  такого события не увидит - слушаем окно, пока подсказка видима. */
  function handleWindowKeydown(/** @type {KeyboardEvent} */ e) {
    if (e.key === 'Escape') hideImmediate();
  }

  // Измерение и слежение. $effect срабатывает ПОСЛЕ отрисовки - к этому моменту
  // bind:this уже связан, и у пузыря есть размеры.
  $effect(() => {
    if (!visible || !tooltipEl) return;
    place();
    const onViewportChange = () => place();
    // capture: true - событие прокрутки внутреннего контейнера до окна не
    // всплывает; на фазе перехвата мы его видим и пузырь идёт за элементом.
    window.addEventListener('scroll', onViewportChange, true);
    window.addEventListener('resize', onViewportChange);
    window.addEventListener('keydown', handleWindowKeydown);
    return () => {
      window.removeEventListener('scroll', onViewportChange, true);
      window.removeEventListener('resize', onViewportChange);
      window.removeEventListener('keydown', handleWindowKeydown);
    };
  });

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
  <!-- Slot: дочерний элемент получает aria-describedby. Связь по id работает и
       через границу поддерева - пузырь лежит в <body>, для ARIA это не помеха. -->
  <span
    class="tooltip-trigger"
    aria-describedby={visible ? tooltipId : undefined}
  >
    {@render children?.()}
  </span>

  {#if visible && text}
    <span
      bind:this={tooltipEl}
      use:portalToBody
      id={tooltipId}
      class="tooltip-bubble"
      class:placed
      class:pos-top={computedPosition === 'top'}
      class:pos-bottom={computedPosition === 'bottom'}
      class:pos-left={computedPosition === 'left'}
      class:pos-right={computedPosition === 'right'}
      role="tooltip"
      style="left: {bubbleX}px; top: {bubbleY}px; --arrow-x: {arrowX}px; --arrow-y: {arrowY}px;"
    >{text}</span>
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
    /* fixed + координаты триггера: предки с прокруткой и overflow: hidden больше
       не кадрируют пузырь, а прижим в place() не даёт вылезти за край окна. */
    position: fixed;
    left: 0;
    top: 0;
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
    /* До первого измерения пузырь не показываем: размеры снимаются с уже
       отрисованного узла, а кадр в левом верхнем углу владельцу не нужен. */
    visibility: hidden;
  }

  .tooltip-bubble.placed {
    visibility: visible;
    /* Entrance animation */
    animation: tooltip-in 0.15s ease-out both;
  }

  /* Small arrow pointer. Смещение стрелки задаёт place(): пузырь у края окна
     сдвинут, а указывать он обязан на сам элемент. */
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
    left: var(--arrow-x, 50%);
    transform: translateX(-50%) rotate(45deg);
    border-top: none;
    border-left: none;
  }
  .tooltip-bubble.pos-bottom::after {
    top: -4px;
    left: var(--arrow-x, 50%);
    transform: translateX(-50%) rotate(45deg);
    border-bottom: none;
    border-right: none;
  }
  .tooltip-bubble.pos-left::after {
    right: -4px;
    top: var(--arrow-y, 50%);
    transform: translateY(-50%) rotate(45deg);
    border-top: none;
    border-right: none;
  }
  .tooltip-bubble.pos-right::after {
    left: -4px;
    top: var(--arrow-y, 50%);
    transform: translateY(-50%) rotate(45deg);
    border-bottom: none;
    border-left: none;
  }

  @keyframes tooltip-in {
    from { opacity: 0; transform: translateY(3px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  /* prefers-reduced-motion: instant appearance, no animation.
     Селектор с тем же весом, что .tooltip-bubble.placed - иначе правило
     появления перебивало бы отказ от анимации. */
  @media (prefers-reduced-motion: reduce) {
    .tooltip-bubble,
    .tooltip-bubble.placed {
      animation: none;
      transition: none;
    }
  }
</style>
