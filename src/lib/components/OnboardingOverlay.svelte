<script>
  import { hasCompletedOnboarding } from '$lib/store.js';

  let step = $state(0);

  const steps = [
    {
      title: 'Aurora AI Agency',
      desc: '11 специализированных кабинетов и более 100 команд — от аналитики и стратегии до креатива, эконометрики и юридической проверки.',
      icon: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
    },
    {
      title: 'Лицензия',
      desc: 'Для работы нужна лицензия, привязанная к вашему компьютеру. Импортируйте JSON-файл в Настройках или подключитесь к серверу.',
      icon: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
    },
    {
      title: 'Кабинеты',
      desc: 'Выберите кабинет на главном экране. Загрузите файлы через «Входящие». В пустом чате появятся советы. Длинные ответы можно сворачивать кнопкой «−».',
      icon: 'M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z M9 22V12h6v10',
    },
    {
      title: 'Команды',
      desc: 'Нажмите кнопку команды или введите её в чат. Ищите команды по названию, добавляйте в избранное звёздочкой для быстрого доступа.',
      icon: 'M16 18l6-6-6-6 M8 6l-6 6 6 6',
    },
  ];

  let direction = $state(1); // 1 = forward, -1 = back

  function next() {
    if (step < steps.length - 1) {
      direction = 1;
      step++;
    } else {
      finish();
    }
  }

  function finish() {
    hasCompletedOnboarding.set(true);
  }

  /** @param {KeyboardEvent} e */
  function handleKeydown(e) {
    if (e.key === 'Escape') {
      finish();
    }
    // Focus trap: Tab cycles within the modal
    if (e.key === 'Tab') {
      const focusable = /** @type {HTMLElement} */ (e.currentTarget)
        ?.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (!focusable?.length) return;
      const first = /** @type {HTMLElement} */ (focusable[0]);
      const last = /** @type {HTMLElement} */ (focusable[focusable.length - 1]);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="overlay" role="dialog" aria-modal="true" aria-label="Приветственный экран Aurora AI" tabindex="-1" onkeydown={handleKeydown}>
  <div class="modal">
    <div class="gradient-line"></div>
    {#key step}
      <div class="step-content" class:slide-left={direction === 1} class:slide-right={direction === -1}>
        <div class="step-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d={steps[step].icon}/>
          </svg>
        </div>
        <h2 class="step-title">{steps[step].title}</h2>
        <p class="step-desc">{steps[step].desc}</p>
      </div>
    {/key}

    <div class="dots">
      {#each steps as _, i}
        <span class="dot" class:active={i === step}></span>
      {/each}
    </div>

    <div class="actions">
      <button class="skip-btn" onclick={finish}>
        {step === steps.length - 1 ? '' : 'Пропустить'}
      </button>
      <button class="next-btn" class:next-btn-final={step === steps.length - 1} onclick={next}>
        {step === steps.length - 1 ? 'Начать работу' : 'Далее'}
      </button>
    </div>
  </div>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: var(--overlay-bg);
    backdrop-filter: var(--blur-quiet);
    -webkit-backdrop-filter: var(--blur-quiet);
    display: flex;
    align-items: center;
    justify-content: center;
    animation: fadeIn 0.3s ease;
  }

  .modal {
    background: var(--bg-secondary, #16161e);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 40px 36px 32px;
    max-width: 420px;
    width: 90%;
    text-align: center;
    box-shadow: var(--shadow-glow);
    animation: slideUp 0.35s cubic-bezier(0.4, 0, 0.2, 1);
    overflow: hidden;
    position: relative;
  }

  .gradient-line {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--gradient-accent-line);
  }

  .step-content {
    animation: step-slide 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .step-icon {
    margin-bottom: 20px;
    color: var(--accent-primary, #2E5BFF);
    opacity: 0.85;
    animation: icon-appear 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .step-title {
    font-size: 20px;
    font-weight: 700;
    margin-bottom: 10px;
    letter-spacing: -0.02em;
  }

  .step-desc {
    font-size: 14px;
    line-height: 1.6;
    color: var(--text-secondary);
    margin-bottom: 24px;
  }

  .dots {
    display: flex;
    justify-content: center;
    gap: 8px;
    margin-bottom: 24px;
  }

  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--border);
    transition: all 0.25s ease;
  }

  .dot.active {
    background: var(--accent-primary, #2E5BFF);
    box-shadow: var(--shadow-glow);
  }

  .actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .skip-btn {
    padding: 8px 16px;
    background: transparent;
    color: var(--text-muted);
    border: none;
    font-size: 13px;
    cursor: pointer;
    border-radius: 8px;
    transition: all 0.2s ease;
    min-width: 80px;
  }

  .skip-btn:hover {
    color: var(--text-secondary);
    background: var(--hover-bg);
  }

  .next-btn {
    padding: 10px 28px;
    background: linear-gradient(135deg, var(--accent-primary, #2E5BFF) 0%, var(--accent-hover) 100%);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
    box-shadow: var(--shadow-glow);
  }

  .next-btn:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-glow);
    filter: brightness(1.08);
  }

  .next-btn-final {
    background: var(--gradient-primary);
    box-shadow: var(--shadow-glow);
  }

  @keyframes slideUp {
    from { transform: translateY(20px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
  }

  @keyframes step-slide {
    from { transform: translateX(30px); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }

  @keyframes icon-appear {
    from { transform: scale(0.8); opacity: 0; }
    to { transform: scale(1); opacity: 0.85; }
  }
</style>
