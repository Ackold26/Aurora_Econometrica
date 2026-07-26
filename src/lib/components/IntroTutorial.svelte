<script>
  /**
   * IntroTutorial - v1.3.0 5-минутный walkthrough «Что такое MMM?»
   * (per Stage 4 Educational System).
   *
   * 8 слайдов: MMM intro → adstock → Hill → priors → decomposition → forward → goal-seek → KPI/режимы.
   * Каждый slide: image emoji + 2-3 предложения + Next/Skip кнопки.
   *
   * @component IntroTutorial
   */

  import { BarChart2, Hourglass, TrendingUp, Target, Calculator, Scale, Sliders, X } from 'lucide-svelte';

  const { onComplete, onSkip } = $props();

  const slides = [
    {
      icon: BarChart2,
      title: 'Что такое MMM',
      body: 'Marketing Mix Modeling – это математический метод, который оценивает вклад каждого канала рекламы в продажи. Aurora использует байесовский подход – даёт не одну точную цифру, а распределение возможных значений с уровнем уверенности.',
    },
    {
      icon: Hourglass,
      title: 'Эффект рекламы – остаточный эффект',
      body: 'Реклама работает не только в период показа. Часть каналов даёт быстрый эффект – почти сразу, но и затухает быстро. Другие работают вдолгую – нарастает постепенно и держится дольше. Параметр затухания показывает, как быстро спадает этот эффект.',
    },
    {
      icon: TrendingUp,
      title: 'Закон насыщения - Hill function',
      body: 'Каждый следующий рубль на канал даёт меньше эффекта, чем предыдущий. Это закон убывающей отдачи. На графике Hill - S-образная кривая. Канал может быть недонасыщенным (давайте больше!), сбалансированным или перенасыщенным.',
    },
    {
      icon: Target,
      title: 'Априорные ожидания',
      body: 'Модель не начинает с нуля. Мы передаём отраслевые ожидания о том, как работают каналы. Это априорные ожидания (приоры). Данные обновляют эти ожидания, и получаются итоговые оценки. На малой выборке приоры стабилизируют модель.',
    },
    {
      icon: Calculator,
      title: 'Декомпозиция продаж',
      body: 'После обучения программа разлагает все ваши продажи на базу (что было бы без рекламы) + вклад каждого канала. ROI = вклад ÷ затраты. Светофор насыщения показывает, какие каналы насыщены, а какие – нет.',
    },
    {
      icon: Scale,
      title: 'Оптимизация бюджета',
      body: 'Дан бюджет → программа находит распределение, максимизирующее продажи. Учитывает насыщение и остаточный эффект, ограничения. Результат: «перелейте N ₽ из канала А в канал B → +M ₽ выручки».',
    },
    {
      icon: Target,
      title: 'Расчёт от цели',
      body: 'Дана цель продаж → программа находит минимальный бюджет, который её достигает. Отвечает на вопрос финансового директора: «нужно прирастить продажи на 10% – сколько потратить?». Находит минимальный бюджет методом деления пополам.',
    },
    {
      icon: Sliders,
      title: 'KPI и режимы (v2.0)',
      body: 'Aurora работает с разными KPI: выручка (₽), продажи в штуках, лиды, регистрации, подписки и т.д. На старте выбираете режим одним кликом: ROI (все каналы в ₽) или Эффективность (все в физических метриках). Для опытных аналитиков в режиме эксперта доступен смешанный режим – поканальный выбор единиц.',
    },
  ];

  let currentIndex = $state(0);
  let isAnimating = $state(false);

  function next() {
    if (isAnimating) return;
    if (currentIndex < slides.length - 1) {
      isAnimating = true;
      currentIndex++;
      setTimeout(() => { isAnimating = false; }, 200);
    } else {
      onComplete?.();
    }
  }

  function prev() {
    if (isAnimating || currentIndex === 0) return;
    isAnimating = true;
    currentIndex--;
    setTimeout(() => { isAnimating = false; }, 200);
  }

  function skip() {
    onSkip?.();
  }

  /**
   * v1.3.1 hotfix: arrow key navigation per UX audit.
   * @param {KeyboardEvent} e
   */
  function handleKeydown(e) {
    if (e.key === 'ArrowRight' || e.key === 'Enter') {
      e.preventDefault();
      next();
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      prev();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      skip();
    }
  }

  const currentSlide = $derived(slides[currentIndex]);
  const isLast = $derived(currentIndex === slides.length - 1);
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="intro-tutorial" role="dialog" aria-modal="true" aria-labelledby="intro-title">
  <div class="modal" class:slide-in={!isAnimating}>
    <header class="modal-header">
      <span class="step-counter">{currentIndex + 1} / {slides.length}</span>
      <button type="button" class="skip-btn" onclick={skip}>Пропустить <X size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /></button>
    </header>

    <div class="slide">
      <div class="slide-icon">
        <svelte:component this={currentSlide.icon} size={56} strokeWidth={1} />
      </div>
      <h2 id="intro-title">{currentSlide.title}</h2>
      <p>{currentSlide.body}</p>
    </div>

    <div class="dots">
      {#each slides as _, i}
        <span class="dot" class:active={i === currentIndex}></span>
      {/each}
    </div>

    <div class="actions">
      <button
        type="button"
        class="btn-secondary"
        onclick={prev}
        disabled={currentIndex === 0}
      >
        ← Назад
      </button>
      <button type="button" class="btn-primary" onclick={next}>
        {isLast ? 'Начать работу →' : 'Далее →'}
      </button>
    </div>
  </div>
</div>

<style>
  .intro-tutorial {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: color-mix(in srgb, var(--bg-card) 70%, transparent);
    backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  .modal {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    max-width: 540px;
    width: 100%;
    box-shadow: 0 20px 60px rgba(0,0,0,0.4);
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .step-counter {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .skip-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 12px;
    font: inherit;
  }
  .skip-btn:hover { color: var(--text-primary); }

  .slide {
    text-align: center;
    padding: 20px 16px;
  }
  .slide-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 16px;
    color: var(--accent-secondary, #CCFF00);
    opacity: 0.85;
  }
  .slide h2 {
    font-size: 22px;
    font-weight: 700;
    margin: 0 0 10px;
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }
  .slide p {
    font-size: 14px;
    line-height: 1.6;
    color: var(--text-secondary);
    margin: 0;
  }

  .dots {
    display: flex;
    justify-content: center;
    gap: 6px;
    padding: 8px 0;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--border);
    transition: background 0.2s;
  }
  .dot.active { background: var(--accent-primary); }

  .actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
  }
  .btn-primary, .btn-secondary {
    padding: 10px 18px;
    border-radius: var(--radius-btn, 8px);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    font: inherit;
    transition: all 0.15s;
  }
  .btn-primary {
    background: var(--accent-primary);
    color: #fff;
  }
  .btn-secondary {
    background: var(--bg-card);
    color: var(--text-secondary);
    border-color: var(--border);
  }
  .btn-secondary:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
