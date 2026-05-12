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

  const { onComplete, onSkip } = $props();

  const slides = [
    {
      emoji: '📊',
      title: 'Что такое MMM',
      body: 'Marketing Mix Modeling - это математический метод, который оценивает вклад каждого канала рекламы в продажи. Aurora использует Bayesian подход - даёт не одну точную цифру, а распределение возможных значений с уровнем уверенности.',
    },
    {
      emoji: '⏳',
      title: 'Эффект рекламы - adstock',
      body: 'Реклама работает не только в неделю показа. TV дотягивается до 8-12 недель, Performance - 1-3 недели. Параметр decay показывает, как быстро затухает эффект. Brand каналы → длинный adstock, Performance → короткий.',
    },
    {
      emoji: '📈',
      title: 'Закон насыщения - Hill function',
      body: 'Каждый следующий рубль на канал даёт меньше эффекта, чем предыдущий. Это закон убывающей отдачи. На графике Hill - S-образная кривая. Канал может быть недонасыщенным (давайте больше!), сбалансированным или перенасыщенным.',
    },
    {
      emoji: '🎯',
      title: 'Priors - наши ожидания',
      body: 'Модель не начинает с нуля. Мы передаём ожидания: «adstock для TV вероятно 0.5-0.9, для Performance - 0.1-0.3». Это priors. Данные обновляют эти ожидания через MCMC, и получается posterior. На малой выборке priors стабилизируют модель.',
    },
    {
      emoji: '🧮',
      title: 'Декомпозиция продаж',
      body: 'После обучения программа разлагает все ваши продажи на базу (что было бы без рекламы) + вклад каждого канала. ROI = вклад ÷ затраты. Светофор насыщения показывает, какие каналы насыщены, а какие - нет.',
    },
    {
      emoji: '⚖️',
      title: 'Forward оптимизация',
      body: 'Дан бюджет → программа находит распределение, максимизирующее продажи. Учитывает Hill saturation, adstock, ограничения. Результат: «перелейте N ₽ из канала А в канал B → +M ₽ выручки».',
    },
    {
      emoji: '🎯',
      title: 'Goal-Seek (новое в v1.3)',
      body: 'Дана цель продаж → программа находит минимальный бюджет, который её достигает. Отвечает на вопрос CFO: «нужно прирастить продажи на 10% - сколько потратить?». Считается через бисекцию по бюджету.',
    },
    {
      emoji: '🎛️',
      title: 'KPI и режимы (v1.3)',
      body: 'Aurora работает с разными KPI: выручка (₽), продажи в штуках, лиды, регистрации, подписки и т.д. Режим (ROI / Эффективность / Вручную) выводится автоматически из ваших данных. Готово работать в любом сценарии.',
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
      <button type="button" class="skip-btn" onclick={skip}>Пропустить ✕</button>
    </header>

    <div class="slide">
      <div class="emoji">{currentSlide.emoji}</div>
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
  .emoji {
    font-size: 64px;
    line-height: 1;
    margin-bottom: 12px;
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
