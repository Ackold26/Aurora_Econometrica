<script>
  /**
   * FirstRunTour - пошаговый тур при первом запуске приложения.
   *
   * 8 шагов: приветствие → загрузка → автоопределение → KPI/роли →
   * запуск модели → результаты → сценарии → готово.
   *
   * Особенности:
   *   - Overlay + подсветка целевого элемента (box-shadow spotlight)
   *   - Позиция карточки адаптивная (снизу/сверху/центр)
   *   - ESC = пропустить тур + сохранить «видел»
   *   - localStorage key: aurora.firstRunTourCompleted
   *   - prefers-reduced-motion: переходы мгновенные
   *   - Прогресс-бар «N из 8»
   *
   * Props:
   *   onDone - callback при завершении/пропуске
   *
   * @component FirstRunTour
   */
  import { onMount, onDestroy } from 'svelte';

  const TOUR_KEY = 'aurora.firstRunTourCompleted';

  /** @type {{ onDone: () => void }} */
  let { onDone } = $props();

  const steps = [
    {
      selector: null,
      title: 'Добро пожаловать в Aurora',
      body: 'Это инструмент для маркетинг-микс моделирования. За 2 минуты покажем ключевые места - и можно сразу работать.',
    },
    {
      selector: '[data-tour-step="import-file"]',
      title: 'Загрузка данных',
      body: 'Здесь загружается файл с историческими данными - Excel или CSV. Нужны хотя бы 20 недель по каналам и KPI. Перетащите файл или нажмите для выбора.',
    },
    {
      selector: '[data-tour-step="auto-detect"]',
      title: 'Автоопределение каналов',
      body: 'Aurora сама распознаёт каналы, KPI и даты в файле. Если что-то определилось неправильно - можно исправить ниже в таблице ролей.',
    },
    {
      selector: '[data-tour-step="kpi-selector"]',
      title: 'Выбор KPI и ролей каналов',
      body: 'Выберите, что считать результатом рекламы: выручку в рублях, продажи в штуках, лиды. Это определяет, в каких единицах модель покажет отдачу каналов.',
    },
    {
      selector: '[data-tour-step="run-model"]',
      title: 'Запуск модели',
      body: 'Нажмите «Обучить модель» - начнётся байесовский расчёт на ваших данных. Займёт 1-5 минут. Пока идёт обучение, можно наблюдать за прогрессом.',
    },
    {
      selector: '[data-tour-step="results-section"]',
      title: 'Читаем результаты',
      body: 'Здесь ROI каждого канала, декомпозиция продаж на составляющие, качество модели. R² > 0.85 - хорошо. Нажмите на канал, чтобы увидеть кривую отклика.',
    },
    {
      selector: '[data-tour-step="scenario-playground"]',
      title: 'Сценарии «Что если»',
      body: 'Двигайте ползунки каналов - модель сразу покажет, что изменится в продажах. Можно сохранить несколько сценариев и сравнить их между собой.',
    },
    {
      selector: null,
      title: 'Готово - можно работать!',
      body: 'Тур завершён. Если понадобится подсказка - наводите мышь на названия метрик, появятся объяснения. Тур всегда можно перезапустить через Настройки.',
    },
  ];

  const TOTAL = steps.length;

  let current = $state(0);
  /** @type {DOMRect | null} */
  let targetRect = $state(null);
  /** @type {HTMLElement | null} */
  let cardEl = $state(null);
  /** @type {number | null} */
  let settleRAF = null;

  function complete() {
    try { localStorage.setItem(TOUR_KEY, '1'); } catch { /* ok */ }
    onDone();
  }

  function next() {
    if (current < steps.length - 1) {
      current += 1;
      updateTarget();
    } else {
      complete();
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

    const preRect = el.getBoundingClientRect();
    const vh = window.innerHeight;
    const alreadyVisible = preRect.top < vh * 0.8 && preRect.bottom > vh * 0.2;
    if (alreadyVisible) {
      targetRect = preRect;
      return;
    }

    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (settleRAF !== null) cancelAnimationFrame(settleRAF);
    let prevTop = NaN;
    let stable = 0;
    const startMs = performance.now();
    const tick = () => {
      const r = el.getBoundingClientRect();
      if (Math.abs(r.top - prevTop) < 0.5) stable++;
      else stable = 0;
      prevTop = r.top;
      if (stable >= 2 || performance.now() - startMs > 500) {
        targetRect = r;
        settleRAF = null;
        return;
      }
      settleRAF = requestAnimationFrame(tick);
    };
    settleRAF = requestAnimationFrame(tick);
  }

  /** @param {KeyboardEvent} e */
  function handleKey(e) {
    if (e.key === 'Escape') complete();
    else if (e.key === 'ArrowRight' || e.key === 'Enter') next();
    else if (e.key === 'ArrowLeft') back();
  }

  onMount(() => {
    updateTarget();
    window.addEventListener('keydown', handleKey);
    window.addEventListener('resize', updateTarget);
  });
  onDestroy(() => {
    window.removeEventListener('keydown', handleKey);
    window.removeEventListener('resize', updateTarget);
    if (settleRAF !== null) cancelAnimationFrame(settleRAF);
  });

  // Позиция карточки
  const cardStyle = $derived.by(() => {
    if (!targetRect) {
      return 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);';
    }
    const r = targetRect;
    const vh = window.innerHeight;
    const vw = window.innerWidth;
    const margin = 16;
    const cardW = Math.min(400, vw - 40);
    const below = vh - r.bottom;
    const above = r.top;
    let top;
    if (below >= 230) top = r.bottom + margin;
    else if (above >= 230) top = Math.max(margin, r.top - 230 - margin);
    else top = margin;
    let left = r.left + r.width / 2 - cardW / 2;
    left = Math.max(margin, Math.min(vw - cardW - margin, left));
    return `position:fixed;top:${top}px;left:${left}px;width:${cardW}px;`;
  });

  const spotlightStyle = $derived.by(() => {
    if (!targetRect) return '';
    const r = targetRect;
    const pad = 8;
    return `top:${r.top - pad}px;left:${r.left - pad}px;width:${r.width + pad * 2}px;height:${r.height + pad * 2}px;`;
  });

  // Progress percentage
  const progressPct = $derived(((current + 1) / TOTAL) * 100);
</script>

<!-- Backdrop -->
<button
  type="button"
  class="frt-backdrop"
  class:with-spotlight={targetRect !== null}
  onclick={complete}
  aria-label="Пропустить тур"
></button>

<!-- Spotlight highlight -->
{#if targetRect}
  <div class="frt-spotlight" style={spotlightStyle}></div>
{/if}

<!-- Info card -->
<div
  bind:this={cardEl}
  class="frt-card"
  style={cardStyle}
  role="dialog"
  aria-modal="true"
  aria-labelledby="frt-title"
>
  <!-- Progress bar -->
  <div class="frt-progress" role="progressbar" aria-valuenow={current + 1} aria-valuemin={1} aria-valuemax={TOTAL}>
    <div class="frt-progress-bar" style="width:{progressPct}%"></div>
  </div>

  <div class="frt-counter">{current + 1} из {TOTAL}</div>
  <h3 id="frt-title" class="frt-title">{steps[current].title}</h3>
  <p class="frt-body">{steps[current].body}</p>

  <div class="frt-actions">
    <button class="frt-btn-skip" onclick={complete}>Пропустить</button>
    <span class="frt-spacer"></span>
    {#if current > 0}
      <button class="frt-btn-back" onclick={back}>← Назад</button>
    {/if}
    <button class="frt-btn-next" onclick={next}>
      {current === steps.length - 1 ? 'Готово' : 'Далее →'}
    </button>
  </div>
</div>

<style>
  .frt-backdrop {
    position: fixed;
    inset: 0;
    z-index: 9100;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(2px);
    cursor: pointer;
    border: none;
    padding: 0;
  }
  .frt-backdrop.with-spotlight {
    background: transparent;
    backdrop-filter: none;
  }

  .frt-spotlight {
    position: fixed;
    z-index: 9101;
    border-radius: 12px;
    pointer-events: none;
    box-shadow:
      0 0 0 9999px rgba(0, 0, 0, 0.68),
      0 0 0 2px color-mix(in srgb, var(--accent-primary, #3b82f6) 80%, transparent),
      0 0 28px color-mix(in srgb, var(--accent-primary, #3b82f6) 35%, transparent);
    transition: top 0.22s ease, left 0.22s ease, width 0.22s ease, height 0.22s ease;
  }

  .frt-card {
    z-index: 9102;
    padding: 16px 18px 14px;
    background: var(--bg-surface-focus, #1e293b);
    border: 1px solid color-mix(in srgb, var(--accent-primary, #3b82f6) 35%, transparent);
    border-radius: 12px;
    color: var(--text-primary, #e2e8f0);
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: 400px;
    transition: top 0.22s ease, left 0.22s ease;
  }

  .frt-progress {
    height: 3px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 2px;
    overflow: hidden;
  }
  .frt-progress-bar {
    height: 100%;
    background: var(--accent-primary, #3b82f6);
    border-radius: 2px;
    transition: width 0.22s ease;
  }

  .frt-counter {
    font-size: 10px;
    color: var(--text-secondary, #94a3b8);
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-top: 2px;
  }

  .frt-title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    line-height: 1.3;
  }

  .frt-body {
    margin: 0;
    font-size: 13px;
    line-height: 1.55;
    color: var(--text-secondary, #cbd5e1);
  }

  .frt-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }

  .frt-spacer { flex: 1; }

  .frt-btn-skip,
  .frt-btn-back,
  .frt-btn-next {
    padding: 7px 14px;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    border: 1px solid transparent;
    font-family: inherit;
    transition: all 0.12s;
  }

  .frt-btn-skip {
    background: transparent;
    color: var(--text-muted, #64748b);
    font-size: 11px;
    padding: 5px 8px;
  }
  .frt-btn-skip:hover { color: var(--text-secondary, #94a3b8); }

  .frt-btn-back {
    background: transparent;
    color: var(--text-primary, #e2e8f0);
    border-color: rgba(255, 255, 255, 0.15);
  }
  .frt-btn-back:hover { border-color: rgba(255, 255, 255, 0.3); }

  .frt-btn-next {
    background: var(--accent-primary, #3b82f6);
    color: #fff;
    border-color: var(--accent-primary, #3b82f6);
    font-weight: 600;
  }
  .frt-btn-next:hover { opacity: 0.9; }

  /* prefers-reduced-motion: no animated transitions */
  @media (prefers-reduced-motion: reduce) {
    .frt-spotlight,
    .frt-card,
    .frt-progress-bar {
      transition: none;
    }
  }
</style>
