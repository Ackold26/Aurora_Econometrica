<script>
  import { invoke } from '@tauri-apps/api/core';
  import { cloudConsent, cloudConsentPromptOpen } from '$lib/store.js';

  // Экран согласия на облачную обработку (F2-2/F2-3, User Story #10). Управляется стором
  // cloudConsentPromptOpen: открывается на первом запуске (информирование) и при попытке
  // войти в кабинет-советник без согласия. Graceful: «Позже» закрывает экран без выхода —
  // MMM-анализ доступен полностью, кабинеты-советники остаются выключены до согласия.
  //
  // ВНИМАНИЕ (юр-ревью): текст ниже — типовой проект согласия на облачную/трансграничную
  // обработку, подготовленный для проверки юристом и согласования с EULA. При изменении
  // формулировок поднять CLOUD_CONSENT_TERMS_VERSION в user_config.rs (повторно запросит согласие).

  let agreed = $state(false); // чекбокс «даю согласие»
  let showFull = $state(false); // развернуть полные условия
  let busy = $state(false);
  let errorMsg = $state('');

  const visible = $derived($cloudConsentPromptOpen);

  function reset() {
    agreed = false;
    showFull = false;
    errorMsg = '';
  }

  async function accept() {
    if (!agreed || busy) return;
    busy = true;
    errorMsg = '';
    try {
      await invoke('accept_cloud_consent');
      cloudConsent.update((c) => ({ ...c, granted: true }));
      cloudConsentPromptOpen.set(false);
      busy = false;
      reset();
    } catch (e) {
      errorMsg = String(e);
      busy = false;
    }
  }

  function later() {
    // Graceful-degrade: без согласия. MMM работает, советники выключены.
    cloudConsentPromptOpen.set(false);
    reset();
  }

  /** @param {KeyboardEvent} e */
  function handleKeydown(e) {
    // Focus-trap внутри модали (без закрытия по Escape — выбор должен быть явным).
    if (e.key === 'Tab') {
      const focusable = /** @type {NodeListOf<HTMLElement>} */ (
        /** @type {HTMLElement} */ (e.currentTarget)?.querySelectorAll(
          'button:not([disabled]), input, [href], [tabindex]:not([tabindex="-1"])'
        )
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
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

{#if visible}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="overlay"
    role="dialog"
    aria-modal="true"
    aria-labelledby="consent-title"
    tabindex="-1"
    onkeydown={handleKeydown}
  >
    <div class="card">
      <div class="gradient-line"></div>

      <div class="icon" aria-hidden="true">
        <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z" />
          <path d="M12 13v-2" />
          <path d="M12 16h.01" />
        </svg>
      </div>

      <h2 id="consent-title" class="title">Согласие на облачную обработку данных</h2>

      <div class="body">
        <p>
          Расчёты MMM (модель, декомпозиция, оптимизация, отчёты, графики) выполняются
          <strong>локально на вашем компьютере</strong> и в облако не передаются.
        </p>
        <p>
          Эта редакция дополнительно включает <strong>кабинеты-советники</strong> – AI-интерпретацию
          модели. При запуске команды советника контекст задачи, включая фрагменты ваших данных,
          передаётся в сервис <strong>Anthropic (Claude)</strong> и возвращается ответ. Это
          происходит <strong>только по вашей команде</strong>, не в фоновом режиме.
        </p>

        {#if showFull}
          <div class="terms">
            <p>
              Запуская команду кабинета-советника, вы поручаете программе передать контекст
              задачи – включая фрагменты загруженных вами данных и производные от них (модель,
              показатели, рекомендации) – в сервис Anthropic (Claude, Anthropic PBC, США) для
              AI-интерпретации и получения ответа. Это означает <strong>трансграничную передачу</strong> данных.
            </p>
            <ul>
              <li>Передача происходит только по вашей инициативе (запуск конкретной команды), не в фоне.</li>
              <li>Расчёты MMM выполняются локально и в облако не передаются – в любой редакции.</li>
              <li>Маршрутизация в российские LLM (резидентность данных) в эту редакцию не входит.</li>
              <li>Согласие добровольно и может быть отозвано в любой момент (Настройки → отключить облачную обработку); отзыв не затрагивает локальный MMM-анализ.</li>
              <li>Вы подтверждаете, что имеете правовое основание передавать загружаемые данные и не загружаете специальные категории персональных данных без отдельного основания.</li>
              <li>Полные условия и гарантии – в лицензионном договоре (EULA) и политике обработки данных.</li>
            </ul>
          </div>
        {:else}
          <button type="button" class="link-btn" onclick={() => (showFull = true)}>Полные условия обработки</button>
        {/if}
      </div>

      <label class="consent-check">
        <input type="checkbox" bind:checked={agreed} />
        <span>
          Я ознакомлен(а) с условиями и даю согласие на облачную обработку данных, включая
          трансграничную передачу в Anthropic (Claude), при использовании кабинетов-советников.
        </span>
      </label>

      {#if errorMsg}
        <p class="error-text">{errorMsg}</p>
      {/if}

      <div class="actions">
        <button type="button" class="later-btn" onclick={later} disabled={busy}>
          Позже
        </button>
        <button type="button" class="accept-btn" onclick={accept} disabled={!agreed || busy}>
          {busy ? 'Сохранение…' : 'Принять и продолжить'}
        </button>
      </div>

      <p class="footnote">
        «Позже» – продолжить без облачной обработки: MMM-анализ доступен полностью, кабинеты-советники
        останутся выключены (включить можно в любой момент).
      </p>
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 10000;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--overlay-bg);
    backdrop-filter: var(--blur-focus);
    -webkit-backdrop-filter: var(--blur-focus);
    animation: fadeIn 0.3s ease;
  }

  .card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 34px 34px 24px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow), var(--shadow-glow);
    max-width: 500px;
    width: 92%;
    max-height: 88vh;
    overflow-y: auto;
    animation: slideUp 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .gradient-line {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--gradient-accent-line);
  }

  .icon {
    color: var(--accent-primary);
    opacity: 0.9;
  }

  .title {
    font-size: 19px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .body p {
    font-size: 13.5px;
    line-height: 1.6;
    color: var(--text-secondary);
    margin: 0;
  }

  .terms {
    display: flex;
    flex-direction: column;
    gap: 9px;
    padding: 12px 14px;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
  }

  .terms p {
    font-size: 12.5px;
    line-height: 1.55;
  }

  .terms ul {
    margin: 0;
    padding-left: 18px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .terms li {
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-secondary);
  }

  .link-btn {
    align-self: flex-start;
    padding: 0;
    background: none;
    border: none;
    color: var(--accent-primary);
    font-size: 12.5px;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .link-btn:hover {
    filter: brightness(1.15);
  }

  .consent-check {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px 14px;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }

  .consent-check input {
    margin-top: 2px;
    flex-shrink: 0;
    accent-color: var(--accent-primary);
    cursor: pointer;
  }

  .consent-check span {
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-secondary);
  }

  .actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 2px;
  }

  .later-btn {
    padding: 10px 18px;
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 13px;
    cursor: pointer;
    transition: all var(--transition);
  }

  .later-btn:hover:not(:disabled) {
    color: var(--text-secondary);
    background: var(--hover-bg);
  }

  .accept-btn {
    padding: 11px 26px;
    background: var(--gradient-primary);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-sm);
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all var(--transition);
    box-shadow: var(--shadow-glow);
  }

  .accept-btn:hover:not(:disabled) {
    transform: translateY(-1px);
    filter: brightness(1.08);
  }

  .accept-btn:disabled,
  .later-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .error-text {
    font-size: 12.5px;
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    padding: 8px 14px;
    border-radius: 6px;
    border: 1px solid color-mix(in srgb, var(--danger) 15%, transparent);
    word-break: break-word;
    margin: 0;
  }

  .footnote {
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-muted);
    margin: 0;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @keyframes slideUp {
    from { transform: translateY(20px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
  }

  @media (prefers-reduced-motion: reduce) {
    .overlay,
    .card {
      animation: none;
    }
  }
</style>
