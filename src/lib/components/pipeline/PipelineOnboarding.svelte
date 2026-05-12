<script>
  /**
   * PipelineOnboarding - универсальный тур для шагов пайплайна.
   *
   * Подсвечивает блок через box-shadow-mask, показывает info-карточку рядом с
   * элементом. Позиция адаптивная (снизу если сверху места мало, иначе сверху).
   * На null-selector - карточка по центру (intro/outro).
   *
   * Вынесен из OptimizeOnboarding в универсальную форму: принимает `steps` и
   * `stepKey` (ключ для localStorage). Используется для всех 5 шагов пайплайна.
   *
   * Props:
   *   steps - массив { selector, title, body }[]
   *   stepKey - используется как ключ completed-флага (через onboarding-state.js)
   *   onDone - callback при закрытии (маркирует шаг done + скрывает tour у родителя)
   *
   * @component PipelineOnboarding
   */
  import { onMount, onDestroy } from 'svelte';
  import { disableOnboarding } from '$lib/onboarding-state.js';

  /**
   * @type {{
   *   steps: Array<{selector: string | null, title: string, body: string}>,
   *   stepKey: string,
   *   onDone: () => void,
   * }}
   */
  let { steps, stepKey, onDone } = $props();

  let current = $state(0);
  /** @type {DOMRect | null} */
  let targetRect = $state(null);
  /** @type {HTMLElement | null} */
  let cardEl = $state(null);

  /** @type {number | null} */
  let scrollSettleRAF = null;

  /** Закрыть тур локально (на этом визите шага). При следующем заходе -
   * появится снова, если onboardingEnabled в Settings не выключен. */
  function markDone() {
    onDone();
  }

  /** Отключить онбординг глобально и закрыть тур. Пользователь больше не
   * увидит туры пока не включит toggle в Settings → Обучающий режим. */
  function disableGlobally() {
    disableOnboarding();
    onDone();
  }

  function next() {
    if (current < steps.length - 1) {
      current += 1;
      updateTarget();
    } else {
      markDone();
    }
  }
  function back() {
    if (current > 0) {
      current -= 1;
      updateTarget();
    }
  }

  function updateTarget() {
    const sel = steps[current].selector;
    if (!sel) {
      targetRect = null;
      return;
    }
    const el = /** @type {HTMLElement | null} */ (document.querySelector(sel));
    if (!el) {
      targetRect = null;
      return;
    }

    // Если элемент уже виден (частично) - замеряем сразу, избегая scroll race.
    const vh = window.innerHeight;
    const preRect = el.getBoundingClientRect();
    const alreadyVisible = preRect.top < vh * 0.8 && preRect.bottom > vh * 0.2;

    if (alreadyVisible) {
      targetRect = preRect;
      return;
    }

    // Smooth scroll → ждём стабильного rect (2 одинаковых замера) или 500мс cap.
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });

    if (scrollSettleRAF !== null) cancelAnimationFrame(scrollSettleRAF);
    let prevTop = NaN;
    let stableFrames = 0;
    const startMs = performance.now();

    const tick = () => {
      const r = el.getBoundingClientRect();
      if (Math.abs(r.top - prevTop) < 0.5) stableFrames += 1;
      else stableFrames = 0;
      prevTop = r.top;

      if (stableFrames >= 2 || performance.now() - startMs > 500) {
        targetRect = r;
        scrollSettleRAF = null;
        return;
      }
      scrollSettleRAF = requestAnimationFrame(tick);
    };
    scrollSettleRAF = requestAnimationFrame(tick);
  }

  /** @param {KeyboardEvent} e */
  function handleKey(e) {
    if (e.key === 'Escape') markDone();
    else if (e.key === 'ArrowRight' || e.key === 'Enter') next();
    else if (e.key === 'ArrowLeft') back();
  }

  function handleResize() {
    updateTarget();
  }

  onMount(() => {
    updateTarget();
    window.addEventListener('keydown', handleKey);
    window.addEventListener('resize', handleResize);
    window.addEventListener('scroll', handleResize, true);
  });

  onDestroy(() => {
    window.removeEventListener('keydown', handleKey);
    window.removeEventListener('resize', handleResize);
    window.removeEventListener('scroll', handleResize, true);
    if (scrollSettleRAF !== null) cancelAnimationFrame(scrollSettleRAF);
  });

  // Позиция карточки от targetRect
  const cardStyle = $derived.by(() => {
    if (!targetRect) {
      return 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);';
    }
    const r = targetRect;
    const vh = window.innerHeight;
    const vw = window.innerWidth;
    const below = vh - r.bottom;
    const above = r.top;
    const margin = 16;
    const cardW = Math.min(420, vw - 40);

    let top;
    if (below >= 220) top = r.bottom + margin;
    else if (above >= 220) top = Math.max(margin, r.top - 220 - margin);
    else top = margin;

    let left = r.left + r.width / 2 - cardW / 2;
    left = Math.max(margin, Math.min(vw - cardW - margin, left));

    return `position: fixed; top: ${top}px; left: ${left}px; width: ${cardW}px;`;
  });

  const spotlightStyle = $derived.by(() => {
    if (!targetRect) return '';
    const r = targetRect;
    const pad = 8;
    return `top: ${r.top - pad}px; left: ${r.left - pad}px; width: ${r.width + pad * 2}px; height: ${r.height + pad * 2}px;`;
  });
</script>

<button
  type="button"
  class="onboarding-backdrop"
  class:with-spotlight={targetRect !== null}
  onclick={markDone}
  aria-label="Закрыть подсказку"
></button>

{#if targetRect}
  <div class="onboarding-spotlight" style={spotlightStyle}></div>
{/if}

<div bind:this={cardEl} class="onboarding-card" style={cardStyle} role="dialog" aria-labelledby="ob-title">
  <div class="step-counter">{current + 1} / {steps.length}</div>
  <h3 id="ob-title" class="card-title">{steps[current].title}</h3>
  <p class="card-body">{steps[current].body}</p>
  <div class="card-actions">
    <button
      class="btn-disable"
      onclick={disableGlobally}
      title="Больше не показывать туры ни на одном шаге. Включить обратно можно в Настройках → Обучающий режим."
    >Отключить обучение</button>
    <button class="btn-skip" onclick={markDone}>Пропустить</button>
    <div class="spacer"></div>
    {#if current > 0}
      <button class="btn-back" onclick={back}>← Назад</button>
    {/if}
    <button class="btn-next" onclick={next}>
      {current === steps.length - 1 ? 'Готово' : 'Далее →'}
    </button>
  </div>
</div>

<style>
  .onboarding-backdrop {
    position: fixed;
    inset: 0;
    z-index: 9000;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(2px);
    cursor: pointer;
    border: none;
    padding: 0;
  }
  .onboarding-backdrop.with-spotlight {
    background: transparent;
    backdrop-filter: none;
  }

  .onboarding-spotlight {
    position: fixed;
    z-index: 9001;
    border-radius: 14px;
    pointer-events: none;
    box-shadow:
      0 0 0 9999px rgba(0, 0, 0, 0.65),
      0 0 0 2px color-mix(in srgb, var(--accent-primary, #3b82f6) 70%, transparent),
      0 0 30px color-mix(in srgb, var(--accent-primary, #3b82f6) 40%, transparent);
    transition: top 0.25s ease, left 0.25s ease, width 0.25s ease, height 0.25s ease;
  }

  .onboarding-card {
    z-index: 9002;
    padding: 18px 20px;
    background: var(--bg-surface-focus, #1e293b);
    border: 1px solid color-mix(in srgb, var(--accent-primary, #3b82f6) 40%, transparent);
    border-radius: 12px;
    color: var(--text-primary, #e2e8f0);
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45);
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-width: 420px;
    transition: top 0.25s ease, left 0.25s ease;
  }

  .step-counter {
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .card-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }

  .card-body {
    margin: 0;
    font-size: 13px;
    line-height: 1.55;
    color: var(--text-secondary, #cbd5e1);
  }

  .card-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
  }

  .spacer { flex: 1; }

  .btn-skip,
  .btn-back,
  .btn-next,
  .btn-disable {
    padding: 7px 14px;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    border: 1px solid transparent;
    font-family: inherit;
  }
  .btn-skip {
    background: transparent;
    color: var(--text-secondary, #94a3b8);
    border-color: transparent;
  }
  .btn-skip:hover { color: var(--text-primary, #e2e8f0); }

  .btn-disable {
    background: transparent;
    color: var(--text-muted, #64748b);
    font-size: 11px;
    padding: 5px 10px;
    border-color: transparent;
    margin-right: 4px;
  }
  .btn-disable:hover {
    color: var(--danger, #ef4444);
    background: color-mix(in srgb, var(--danger, #ef4444) 10%, transparent);
  }

  .btn-back {
    background: transparent;
    color: var(--text-primary, #e2e8f0);
    border-color: rgba(255, 255, 255, 0.15);
  }
  .btn-back:hover { border-color: rgba(255, 255, 255, 0.3); }

  .btn-next {
    background: var(--accent-primary, #3b82f6);
    color: white;
    border-color: var(--accent-primary, #3b82f6);
    font-weight: 600;
  }
  .btn-next:hover { opacity: 0.9; }
</style>
