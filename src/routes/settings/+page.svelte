<script>
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import { open } from '@tauri-apps/plugin-dialog';
  import { openUrl } from '@tauri-apps/plugin-opener';
  import { theme, toggleTheme, cloudConsentPromptOpen } from '$lib/store.js';
  import { assistantRoute, refreshAssistantRoute } from '$lib/assistant-route.js';
  import { productType } from '$lib/creative-store.js';
  import { getProductName, filterCabinetsByProduct } from '$lib/command-meta.js';

  let APP_VERSION = $state('...');
  // Номер версии один на поставку (ADR-049 §2): буква редакции убрана вместе со вторым
  // каналом обновлений. Где исполняется работа — показывает признак режима, не номер.
  invoke('display_version').then(v => { APP_VERSION = v; }).catch(() => { APP_VERSION = '?'; });
  // 🔴 15.08.2026, решение владельца: звуковых эффектов в программе нет, переключатель убран.
  // Прежнее сохранённое состояние стираем при открытии настроек: у клиента, включавшего звук
  // раньше, в памяти браузера осталось «включено», и без очистки эта запись пережила бы
  // возможный возврат переключателя, включив звук без спроса. Сам звук выключен в audio.js.
  import { forgetAudioPreference } from '$lib/audio.js';
  import { onboardingEnabled } from '$lib/onboarding-state.js';
  import { hideEducationalHints, showGlossaryPanel, showIntroTutorial } from '$lib/project-state.js';
  import { resolveLicenseTier } from '$lib/license-display.js';

  // INV-146: домен в местах для человека — читаемым регистром; машинный адрес ВЫВОДИТСЯ
  // из него приведением к строчным, а не хранится второй строкой рядом. Две строки-константы
  // расходятся молча: одну поправили, вторую забыли — человек видит один адрес, ссылка ведёт
  // на другой. Собранная поставка не должна содержать строчного написания вовсе.
  // Полное клиентское имя программы. Ни один источник его не содержит целиком: в пакете
  // лежит «Aurora AI Econometrica» (семейство), в конфигурации сборки — «Optimizer MMM»
  // (техническое имя поставки). На экране «о программе» человек должен видеть, чем именно
  // он пользуется, поэтому имя собрано здесь явно.
  const PRODUCT_NAME_FULL = 'Aurora AI Econometrica – MMM Optimizer';
  const PRODUCT_SITE = 'MMM-Optimizer.pro';
  const UMBRELLA_SITE = 'AuroraAi.pro';
  /** @param {string} site @returns {string} */
  const siteUrl = (site) => `https://${site.toLowerCase()}`;

  // INV-146, часть 3: target="_blank" в настольной программе ссылку не открывает — либо пустое
  // окно, либо уход из программы без возврата. Открываем системным способом; адрес в разметке
  // остаётся настоящим, чтобы работали доступность и «копировать адрес» в правом клике.
  /** @param {string} site */
  function openSite(site) {
    /** @param {MouseEvent} event */
    return (event) => {
      // preventDefault нужен и для средней кнопки мыши: она шлёт auxclick, а не click, и без
      // перехвата сработало бы штатное действие ссылки — встроенное окно ушло бы на сайт, а
      // вернуться из него нечем: полосы навигации и кнопки «назад» в приложении нет.
      //
      // 🔴 Но auxclick шлёт НЕ ТОЛЬКО средняя кнопка: правая и боковые тоже (находка
      // внешнего аудита 11.09.2026). Без разбора кнопки правый клик по ссылке — попытка
      // открыть меню и скопировать адрес — молча уводил человека в системный браузер.
      // Обычный клик (тип «click») проходит как прежде, разбор касается только auxclick.
      if (event.type === 'auxclick' && event.button !== 1) return;
      event.preventDefault();
      // Отказ не глушим молча: INV-146 сам называет тихий отказ главной опасностью этого места
      // (без разрешения opener:allow-open-url ссылка просто ничего не делает, и на глаз это
      // неотличимо от рабочей). Пишем причину, чтобы она попадала в журнал приложения.
      openUrl(siteUrl(site)).catch((err) => {
        console.error(`Не удалось открыть ${siteUrl(site)} в браузере системы:`, err);
      });
    };
  }

  forgetAudioPreference();

  // ── Единственный переключатель режима работы ──────────────────────────────────
  //
  // 🔴 Было три органа управления: «Облачная обработка» (согласие), «Только локально»
  // (запрет обращений) и выбор из трёх маршрутов исполнения, включая автоопределение.
  // Одно решение тремя переключателями — это и стоило отказа на показе 10.09.2026:
  // владелец включил облачную обработку, а работа ушла в чужой Claude Code на машине.
  // Осталось одно положение (решение владельца 10.09.2026): слева ассистента нет,
  // справа он работает через шлюз Авроры. Согласие стало частью выбора режима —
  // спрашивается один раз, при первом переводе вправо; отказ оставляет слева.
  let routeBusy = $state(false);
  let routeMsg = $state('');

  /** @param {boolean} cloud */
  async function setAssistantRoute(cloud) {
    if (routeBusy) return;
    routeBusy = true;
    routeMsg = '';
    try {
      await invoke('set_assistant_route', { cloud });
      await refreshAssistantRoute();
      routeMsg = cloud
        ? '✓ Режим «через шлюз Авроры»: ИИ-ассистент отвечает, запросы идут через наш сервер.'
        : '✓ Режим «полностью локально»: ИИ-ассистент отключён, материалы не покидают эту машину.';
      setTimeout(() => { routeMsg = ''; }, 7000);
    } catch (e) {
      const text = String(e);
      // Согласия ещё нет — вместо отказа показываем экран согласия. Дальше решает
      // человек: согласился — переключатель уходит вправо, «Позже» — остаётся слева.
      if (text.includes('MODE-CONSENT')) {
        cloudConsentPromptOpen.set(true);
      } else {
        routeMsg = 'Ошибка: ' + text;
      }
    } finally {
      routeBusy = false;
    }
  }

  function toggleAssistantRoute() {
    if ($assistantRoute.locked || !$assistantRoute.known) return;
    setAssistantRoute(!$assistantRoute.cloud);
  }

  // Econometrica projects root
  /** @type {{current: string, default: string, is_custom: boolean} | null} */
  let econRoot = $state(null);
  let econRootMsg = $state('');
  let econRootBusy = $state(false);

  async function loadEconRoot() {
    try {
      econRoot = /** @type {any} */ (await invoke('get_econometrica_projects_root'));
    } catch (e) {
      econRoot = null;
    }
  }
  loadEconRoot();
  // Положение переключателя перечитывается при открытии настроек: человек мог отозвать
  // согласие или сменить режим в другом окне, а подпись «Сейчас: …» обязана говорить о
  // сегодняшнем положении дел, а не о том, что прочиталось при запуске программы.
  refreshAssistantRoute();

  async function chooseEconRoot() {
    econRootBusy = true;
    econRootMsg = '';
    try {
      const selected = await open({ directory: true, multiple: false, title: 'Папка для проектов Econometrica' });
      if (!selected || typeof selected !== 'string') { econRootBusy = false; return; }
      await invoke('set_econometrica_projects_root', { path: selected });
      await loadEconRoot();
      econRootMsg = '✓ Папка изменена. Новые проекты будут сохраняться здесь. Существующие остались в прежней папке.';
      setTimeout(() => { econRootMsg = ''; }, 8000);
    } catch (e) {
      econRootMsg = 'Ошибка: ' + String(e);
    } finally {
      econRootBusy = false;
    }
  }

  async function resetEconRoot() {
    econRootBusy = true;
    econRootMsg = '';
    try {
      await invoke('set_econometrica_projects_root', { path: '' });
      await loadEconRoot();
      econRootMsg = '✓ Сброшено на папку по умолчанию';
      setTimeout(() => { econRootMsg = ''; }, 5000);
    } catch (e) {
      econRootMsg = 'Ошибка: ' + String(e);
    } finally {
      econRootBusy = false;
    }
  }

  async function openEconRoot() {
    try {
      await invoke('open_econometrica_projects_root');
    } catch (e) {
      econRootMsg = 'Ошибка: ' + String(e);
      setTimeout(() => { econRootMsg = ''; }, 5000);
    }
  }
  let machineId = $state('...');
  /** @type {any} */
  let licenseStatus = $state(null);
  /** @type {string|null} */
  let licenseError = $state(null);
  let importStatus = $state('');
  let allCopied = $state(false);
  /** @type {any} */
  let usageMetrics = $state(null);
  /** @type {Array<[string, string, boolean]>} */
  let vaultStatus = $state([]);
  let vaultImportStatus = $state('');
  let diagExporting = $state(false);
  let diagPath = $state('');
  /** @type {{status: string, content_version: string|null, expires_at: string|null, machine_id: string}|null} */
  let onlineStatus = $state(null);
  let contentVersion = $state('');

  // #61 (2026-06-02) [LI-001]: единый приоритет источников лицензии (см. license-display.js).
  let licenseTier = $derived(resolveLicenseTier(onlineStatus, licenseStatus));

  async function copyAllFingerprints() {
    try {
      const hash = await invoke('get_full_machine_hash');
      await navigator.clipboard.writeText(hash);
      allCopied = true;
      setTimeout(() => { allCopied = false; }, 2000);
    } catch (err) {
      console.error('Failed to copy fingerprints:', err);
    }
  }

  async function loadStatus() {
    try {
      machineId = await invoke('get_machine_id');
    } catch (err) {
      machineId = 'Ошибка: ' + err;
    }

    try {
      licenseStatus = await invoke('get_license_status');
      licenseError = null;
    } catch (err) {
      licenseError = String(err);
      licenseStatus = null;
    }
  }

  async function importLicense() {
    try {
      const filePath = await open({
        title: 'Выберите файл лицензии',
        filters: [{ name: 'License', extensions: ['json'] }],
        multiple: false,
      });
      if (!filePath) return;

      await invoke('import_license', { path: filePath });
      importStatus = 'Лицензия импортирована успешно!';
      await loadStatus();
    } catch (err) {
      importStatus = 'Ошибка: ' + err;
    }
  }

  /**
   * Запасной путь доставки: материалы кабинета берутся из файла, когда сеть
   * их не пропускает (корпоративный шлюз, проверка соединений антивирусом).
   */
  async function importVault() {
    try {
      const filePath = await open({
        title: 'Выберите файл материалов кабинета',
        filters: [{ name: 'Материалы кабинета', extensions: ['vault'] }],
        multiple: false,
      });
      if (!filePath) return;

      vaultImportStatus = /** @type {string} */ (await invoke('import_cabinet_vault', { path: filePath }));
      await loadVaultStatus();
    } catch (err) {
      vaultImportStatus = 'Не удалось загрузить: ' + err;
    }
  }

  async function loadMetrics() {
    try {
      usageMetrics = await invoke('get_usage_metrics');
    } catch (err) {
      console.error('Failed to load metrics:', err);
    }
  }

  async function resetMetrics() {
    try {
      await invoke('reset_metrics');
      usageMetrics = null;
    } catch (err) {
      console.error('Failed to reset metrics:', err);
    }
  }

  async function loadVaultStatus() {
    try {
      const all = /** @type {Array<[string, string, boolean]>} */ (await invoke('list_vault_status'));
      const allCabs = /** @type {any[]} */ (await invoke('get_cabinets'));
      const filtered = filterCabinetsByProduct(allCabs, $productType);
      const allowedIds = new Set(filtered.map(c => c.id));
      vaultStatus = all.filter(([cabId]) => allowedIds.has(cabId));
    } catch { vaultStatus = []; }
  }

  let guideError = $state('');
  let pdfSaveStatus = $state('');

  // Feedback form
  let fbCategory = $state('problem');
  let fbMessage = $state('');
  /** @type {'idle'|'loading'|'recorded'|'sent'|'error'} */
  let fbStatus = $state('idle');
  let fbError = $state('');
  /** Сырая строка отказа — нужна поддержке при разборе, человеку её показываем под «Подробности». */
  let fbErrorRaw = $state('');

  /** Предел длины текста обращения — тот же, что в `commands/feedback.rs`. */
  const FEEDBACK_MAX_CHARS = 4000;
  /** Столько секунд программа не принимает повторную отправку — RATE_LIMIT_SECS в commands/feedback.rs. */
  const FEEDBACK_COOLDOWN_SECS = 60;
  /** Ключ отметки времени. Свой у каждой программы: запреты у них независимые. */
  const FEEDBACK_SENT_KEY = 'econometrica-feedback-last-sent';
  let fbCooldown = $state(0);
  /** @type {ReturnType<typeof setInterval>|null} */
  let fbTimer = null;

  /**
   * Сколько секунд осталось до разрешённой повторной отправки.
   *
   * 🔴 Считается от ДОЛГОВРЕМЕННОЙ отметки времени, а не от счётчика тиков — перенос образца
   * Creative Center, где это уже исправлено по двум находкам внешнего аудита 15.08: счётчик в
   * состоянии страницы обнулялся при уходе с неё (человек возвращался раньше минуты, видел
   * активную кнопку и получал отказ), а счётчик тиков после сна компьютера держал кнопку
   * заблокированной дольше самого запрета.
   */
  function remainingCooldown() {
    let sentAt = 0;
    try {
      sentAt = Number(localStorage.getItem(FEEDBACK_SENT_KEY)) || 0;
    } catch {
      // Хранилище может быть недоступно. Отсчёт тогда не восстановится — это неприятно, но
      // отправку не ломает: запрет всё равно держит программа.
      sentAt = 0;
    }
    if (!sentAt) return 0;
    const passed = Math.floor((Date.now() - sentAt) / 1000);
    return Math.max(0, FEEDBACK_COOLDOWN_SECS - passed);
  }

  /** Запустить (или продолжить) отсчёт до конца запрета повторной отправки. */
  function startFeedbackCooldown() {
    if (fbTimer) clearInterval(fbTimer);
    fbCooldown = remainingCooldown();
    if (fbCooldown <= 0) {
      if (fbStatus === 'recorded' || fbStatus === 'sent') fbStatus = 'idle';
      return;
    }
    fbTimer = setInterval(() => {
      fbCooldown = remainingCooldown();
      if (fbCooldown <= 0) {
        if (fbTimer) clearInterval(fbTimer);
        fbTimer = null;
        fbStatus = 'idle';
      }
    }, 1000);
  }

  /**
   * Человеческий текст отказа по коду — строение то же, что в `updateErrorText.js` (CPD-167):
   * что случилось, чем это плохо, что делать. Сырая строка не теряется: она остаётся под
   * подписью «Подробности».
   */
  /** @param {unknown} raw сырая строка отказа из программы */
  function feedbackErrorText(raw) {
    const текст = String(raw);
    if (текст.includes('FB-002') || текст.includes('FB002')) {
      return 'Предыдущее обращение отправлено меньше минуты назад. Программа держит эту паузу, '
        + 'чтобы случайный повторный нажим не отправил одно и то же дважды – подождите, пока '
        + 'кнопка станет доступной, и отправьте снова.';
    }
    return 'Отправить обращение не удалось – связи с нашим сервером сейчас нет. '
      + 'Обращение при этом никуда не сохранилось: скопируйте свой текст, чтобы он не потерялся, '
      + 'и пришлите его на support@auroraai.pro – ответим так же.';
  }

  // Возврат на страницу раньше, чем истёк запрет повторной отправки: восстановить отсчёт,
  // иначе кнопка выглядит доступной, а программа отвечает отказом. Уборка таймера — рядом
  // с его запуском, чтобы одно не забылось без другого.
  onMount(() => {
    startFeedbackCooldown();
    return () => { if (fbTimer) clearInterval(fbTimer); };
  });


  async function submitFeedback() {
    if (!fbMessage.trim()) return;
    fbStatus = 'loading';
    fbError = '';
    try {
      // 🔴 Подтверждение показываем по ответу программы, а не по факту «вызов не упал»:
      // 'recorded' – сервис подтвердил запись, 'sent' – отправка прошла, но признака записи
      // в ответе не было. Утверждать доставку во втором случае нельзя.
      const исход = await invoke('submit_feedback', { category: fbCategory, message: fbMessage });
      fbStatus = исход === 'recorded' ? 'recorded' : 'sent';
      fbMessage = '';
      try {
        localStorage.setItem(FEEDBACK_SENT_KEY, String(Date.now()));
      } catch { /* хранилище недоступно — отсчёт не восстановится после ухода со страницы */ }
      startFeedbackCooldown();
    } catch (err) {
      fbStatus = 'error';
      fbError = feedbackErrorText(err);
      fbErrorRaw = String(err);
    }
  }

  /** @type {Array<{id: string, name: string, icon: string}>} */
  let cabinets = $state([]);
  /** @type {Record<string, string>} */
  let cabinetPaths = $state({});

  async function loadCabinetPaths() {
    try {
      const allCabs = /** @type {any[]} */ (await invoke('get_cabinets'));
      cabinets = filterCabinetsByProduct(allCabs, $productType);
      /** @type {Record<string, string>} */
      const paths = {};
      for (const cab of cabinets) {
        paths[cab.id] = /** @type {string} */ (await invoke('get_cabinet_path', { cabinetId: cab.id }));
      }
      cabinetPaths = paths;
    } catch (err) {
      console.error('Failed to load cabinet paths:', err);
    }
  }

  /** @param {string} cabinetId */
  async function pickCabinetFolder(cabinetId) {
    try {
      const selected = await open({ directory: true, title: 'Выбрать папку для результатов' });
      if (!selected) return;
      await invoke('set_cabinet_path', { cabinetId, path: selected });
      cabinetPaths = { ...cabinetPaths, [cabinetId]: /** @type {string} */ (selected) };
    } catch (err) {
      console.error('Failed to set cabinet path:', err);
    }
  }

  /** @param {string} cabinetId */
  async function resetCabinetFolder(cabinetId) {
    try {
      const defaultPath = /** @type {string} */ (await invoke('reset_cabinet_path', { cabinetId }));
      cabinetPaths = { ...cabinetPaths, [cabinetId]: defaultPath };
    } catch (err) {
      console.error('Failed to reset cabinet path:', err);
    }
  }

  /** @type {'sonnet'|'opus'} */
  let modelChoice = $state('sonnet');
  /** @type {'medium'|'high'|'max'} */
  let effortChoice = $state('medium');

  async function loadModelSettings() {
    try {
      const s = /** @type {{model: string, effort: string}} */ (await invoke('get_model_settings'));
      modelChoice = /** @type {'sonnet'|'opus'} */ (s.model || 'sonnet');
      effortChoice = /** @type {'medium'|'high'|'max'} */ (s.effort || 'medium');
    } catch (err) {
      console.error('Failed to load model settings:', err);
    }
  }

  async function saveModelSettings() {
    try {
      await invoke('set_model_settings', { model: modelChoice, effort: effortChoice });
    } catch (err) {
      console.error('Failed to save model settings:', err);
    }
  }

  loadStatus();
  loadMetrics();
  loadVaultStatus();
  loadCabinetPaths();
  loadModelSettings();

  // Load online connection status
  (async () => {
    try {
      onlineStatus = await invoke('check_online_auth');
    } catch { /* offline */ }
    try {
      contentVersion = /** @type {string} */ (await invoke('get_local_content_version')) || '';
    } catch { /* no version */ }
  })();
</script>

<div class="settings">
  <header class="header">
    <a href="/" class="header-logo-link" title="На главную" aria-label="Aurora AI – на главную">
      <img src="/logo-horizon.png" alt="Aurora AI" class="header-logo" />
    </a>
    <a href="/" class="back-link">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      Назад
    </a>
    <h1>Настройки</h1>
  </header>

  <main class="content">
    <div class="settings-logo">
      <img src="/logo-full.png" alt="Aurora AI" class="settings-logo-img" />
      <span class="settings-logo-subtitle">Econometrica</span>
    </div>
    <button class="btn-platform" onclick={async () => { try { await invoke('open_help', { cabinetId: 'about' }); } catch { /* */ } }}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      О платформе
    </button>

    <section class="section">
      <h2 class="section-title">Оформление</h2>
      <div class="theme-toggle-row">
        <span class="theme-label">Тема оформления</span>
        <button class="theme-toggle" onclick={toggleTheme}>
          {#if $theme === 'dark'}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
            <span>Тёмная</span>
          {:else if $theme === 'light'}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="12" cy="12" r="5"/>
              <line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
              <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
            </svg>
            <span>Светлая</span>
          {:else}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 8h1a4 4 0 0 1 0 8h-1"/>
              <path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4z"/>
              <line x1="6" y1="1" x2="6" y2="4"/>
              <line x1="10" y1="1" x2="10" y2="4"/>
              <line x1="14" y1="1" x2="14" y2="4"/>
            </svg>
            <span>Весёлая</span>
          {/if}
        </button>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">Обучающий режим</h2>
      <p class="section-desc">
        Краткие подсказки по каждому шагу пайплайна (Импорт → Валидация → Модель → Декомпозиция → Оптимизация → Отчёт).
        Показываются каждый раз пока включены - отключаются здесь или прямо из тура кнопкой «Отключить обучение».
      </p>
      <div class="theme-toggle-row">
        <span class="theme-label">Показывать туры</span>
        <button
          class="theme-toggle"
          onclick={() => onboardingEnabled.set(!$onboardingEnabled)}
          aria-label="Toggle onboarding"
        >
          {#if $onboardingEnabled}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            <span>Включены</span>
          {:else}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="9"/>
              <line x1="15" y1="9" x2="9" y2="15"/>
              <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            <span>Выключены</span>
          {/if}
        </button>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">Подсказки и обучение (v1.3)</h2>
      <p class="section-desc">
        Inline tooltips, «Зачем этот шаг?» панели и подсказки по терминам. По умолчанию включены для новых пользователей.
        Опытные эконометристы могут скрыть для чистого UI.
      </p>
      <div class="theme-toggle-row">
        <span class="theme-label">Скрыть подсказки</span>
        <button
          class="theme-toggle"
          onclick={() => hideEducationalHints.set(!$hideEducationalHints)}
          aria-label="Toggle educational hints"
        >
          {#if $hideEducationalHints}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            <span>Скрыты (Expert)</span>
          {:else}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="9"/>
              <line x1="15" y1="9" x2="9" y2="15"/>
              <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            <span>Показаны (Novice)</span>
          {/if}
        </button>
      </div>

      <div class="theme-toggle-row" style="margin-top: 12px;">
        <span class="theme-label">Открыть глоссарий</span>
        <button
          class="theme-toggle"
          onclick={() => showGlossaryPanel.set(true)}
          aria-label="Open glossary"
          title="Также Ctrl+G"
        >
          <span>📖 20 терминов · Ctrl+G</span>
        </button>
      </div>

      <div class="theme-toggle-row" style="margin-top: 12px;">
        <span class="theme-label">Показать вступительный тур</span>
        <button
          class="theme-toggle"
          onclick={() => showIntroTutorial.set(true)}
          aria-label="Show intro tutorial"
        >
          <span>🎓 Что такое MMM (5 мин)</span>
        </button>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">Папка для проектов Econometrica</h2>
      <p class="section-desc">
        Где хранятся данные, модели, результаты и экспорты всех MMM-проектов.
        По умолчанию - в скрытой системной папке. Можно задать свою (например,
        на облачном диске или внешнем накопителе) - но существующие проекты автоматически не переносятся.
      </p>
      {#if econRoot}
        <div class="theme-toggle-row" style="align-items: flex-start;">
          <span class="theme-label" style="max-width: 58%;">
            <span style="display: block; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px;">
              Текущая папка{econRoot.is_custom ? ' (кастомная)' : ' (по умолчанию)'}
            </span>
            <code style="font-size: 12px; word-break: break-all; color: var(--text-primary); line-height: 1.4;">{econRoot.current}</code>
          </span>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button class="btn-logs" onclick={openEconRoot} title="Открыть в проводнике">📂 Открыть</button>
            <button class="btn-logs" onclick={chooseEconRoot} disabled={econRootBusy}>📁 Выбрать папку</button>
            {#if econRoot.is_custom}
              <button class="btn-logs" onclick={resetEconRoot} disabled={econRootBusy} title="Вернуть к папке по умолчанию">↺ Сбросить</button>
            {/if}
          </div>
        </div>
        {#if econRoot.is_custom}
          <p class="import-status" style="color: var(--text-muted); margin-top: 8px; font-size: 12px;">
            По умолчанию: <code>{econRoot.default}</code>
          </p>
        {/if}
      {/if}
      {#if econRootMsg}
        <p class="import-status" style="color: var(--success); margin-top: 8px;">{econRootMsg}</p>
      {/if}
    </section>

    <!-- Выбор модели/нажима скрыт в Econometrica (Optimizer): пользователю не нужно
         управлять моделью — используется оптимальная актуальная (Sonnet, latest-алиас,
         авто-обновление). В других продуктах общего shell панель остаётся. -->
    {#if $productType !== 'econometrica'}
    <section class="section">
      <h2 class="section-title">AI-модель советников</h2>
      <p class="section-desc">Модель и уровень усилия для обработки запросов</p>
      <div class="theme-toggle-row">
        <span class="theme-label">Модель</span>
        <select class="model-select" bind:value={modelChoice} onchange={saveModelSettings}>
          <option value="sonnet">Быстрая (по умолчанию)</option>
          <option value="opus">Глубокий анализ</option>
        </select>
      </div>
      <div class="theme-toggle-row">
        <span class="theme-label">Уровень</span>
        <select class="model-select" bind:value={effortChoice} onchange={saveModelSettings}>
          <option value="medium">Medium</option>
          <option value="high">High (по умолчанию)</option>
          <option value="max">Max</option>
        </select>
      </div>
    </section>
    {/if}

    <!--
      🔴 Единственный переключатель режима работы. Стоит ВНЕ условия «советники есть»
      намеренно (решение владельца Р-2 от 11.09.2026): в локальной редакции он остаётся
      виден и заблокирован в левом положении с пояснением. Пропавший орган управления
      человек читает как неисправность программы, а не как гарантию приватности.

      Подпись «Сейчас: …» приходит из продукта готовой строкой и считается от
      ФАКТИЧЕСКОГО положения дел — редакция, наличие шлюза в сборке, согласие и выбор
      человека. Прежняя подпись смотрела на один переключатель из двух и на свежей
      установке жирным утверждала, что материалы уходят на наш сервер, хотя согласия
      никто не давал и наружу не уходило ничего (внешний аудит 11.09.2026).
    -->
    <section class="section" id="assistant-route">
      <h2 class="section-title">Режим работы</h2>
      <p class="section-desc">
        Расчёт медиасплита в любом режиме выполняется на вашей машине. Переключатель решает
        судьбу ИИ-ассистента: слева его нет вовсе, справа он отвечает через шлюз Авроры –
        своя подписка для этого не нужна.
      </p>

      <div class="route-switch">
        <span class="route-side" class:route-side-on={$assistantRoute.known && !$assistantRoute.cloud}>
          Полностью локально
        </span>
        <button
          class="route-toggle"
          class:route-toggle-on={$assistantRoute.known && $assistantRoute.cloud}
          class:route-toggle-unknown={!$assistantRoute.known}
          role="switch"
          aria-checked={$assistantRoute.known ? $assistantRoute.cloud : 'mixed'}
          aria-label="Режим работы: слева полностью локально, справа через шлюз Авроры"
          disabled={routeBusy || $assistantRoute.locked || !$assistantRoute.known}
          onclick={toggleAssistantRoute}
        >
          <span class="route-knob"></span>
        </button>
        <span class="route-side" class:route-side-on={$assistantRoute.known && $assistantRoute.cloud}>
          Через шлюз Авроры
        </span>
      </div>

      <p class="section-desc route-headline"><strong>{$assistantRoute.headline}</strong></p>

      {#if $assistantRoute.locked}
        <p class="section-desc route-locked">{$assistantRoute.lockedReason}</p>
      {/if}
      {#if routeMsg}
        <p class="import-status" style="color: {routeMsg.startsWith('Ошибка') ? 'var(--danger)' : 'var(--success)'}; margin-top: 8px;">{routeMsg}</p>
      {/if}
    </section>


    <section class="section">
      <h2 class="section-title">Справочный центр</h2>
      <p class="section-desc">Руководства по всем кабинетам, советы, рекомендации и pipeline работы.</p>
      <button class="btn-logs" onclick={async () => { try { await invoke('open_help', { cabinetId: 'index' }); } catch(e) { guideError = String(e); console.error(e); } }}>
        Открыть справочный центр
      </button>
      <button class="btn-logs" onclick={async () => { pdfSaveStatus = ''; try { const path = await invoke('save_help_pdf'); pdfSaveStatus = `Сохранено: ${path}`; } catch(e) { pdfSaveStatus = `Ошибка: ${e}`; console.error(e); } }}>
        Скачать PDF-справку
      </button>
      {#if guideError}
        <p class="import-status" style="color: var(--danger)">{guideError}</p>
      {/if}
      {#if pdfSaveStatus}
        <p class="import-status" style="color: {pdfSaveStatus.startsWith('Ошибка') ? 'var(--danger)' : 'var(--success)'}">{pdfSaveStatus}</p>
      {/if}
    </section>

    <section class="section">
      <h2 class="section-title">Обратная связь</h2>
      <p class="section-desc">Сообщите о проблеме, предложите улучшение или задайте вопрос.</p>
      <div class="feedback-form">
        <select class="fb-select" bind:value={fbCategory}>
          <option value="problem">Проблема</option>
          <option value="suggestion">Пожелание</option>
          <option value="question">Вопрос</option>
        </select>
        <textarea
          class="fb-textarea"
          placeholder="Опишите подробнее..."
          bind:value={fbMessage}
          maxlength={FEEDBACK_MAX_CHARS}
          rows="4"
        ></textarea>
        <p class="fb-note">
          Вместе с обращением уходят название и версия программы, метка компьютера и время – по ним
          мы поймём, откуда оно пришло. Персональные данные и содержимое документов в тексте не
          нужны: мы их не запрашиваем.
        </p>
        <p class="fb-note">
          Ответить в программе мы не сможем – обращение приходит без ваших контактных данных.
          Нужен ответ – напишите на support@auroraai.pro.
        </p>
        <button
          class="fb-submit"
          onclick={submitFeedback}
          disabled={fbStatus === 'loading' || fbCooldown > 0 || !fbMessage.trim()}
          title={fbCooldown > 0 ? `Следующее обращение можно отправить через ${fbCooldown} с` : ''}
        >
          {#if fbStatus === 'loading'}
            Отправка...
          {:else if fbCooldown > 0}
            Отправлено
          {:else}
            Отправить
          {/if}
        </button>
        {#if fbStatus === 'recorded'}
          <p class="fb-success" role="status">
            Спасибо, обращение записано. Следующее можно отправить через {fbCooldown} с.
          </p>
        {/if}
        {#if fbStatus === 'sent'}
          <p class="fb-success" role="status">
            Обращение отправлено. Подтверждения записи сервис не прислал – если дело важное,
            продублируйте письмом на support@auroraai.pro. Следующее обращение можно отправить
            через {fbCooldown} с.
          </p>
        {/if}
        {#if fbStatus === 'error'}
          <p class="fb-error">{fbError}</p>
          {#if fbErrorRaw}
            <details class="fb-details">
              <summary>Подробности</summary>
              <p>{fbErrorRaw}</p>
            </details>
          {/if}
        {/if}
      </div>
    </section>

    {#if cabinets.length > 0}
    <section class="section">
      <h2 class="section-title">Папки результатов</h2>
      <p class="section-desc">Выберите, куда каждый кабинет будет сохранять файлы (inbox и exports).</p>
      <div class="cabinet-paths">
        {#each cabinets as cab (cab.id)}
          <div class="cabinet-path-row">
            <div class="cabinet-path-header">
              <span class="cabinet-path-icon">{cab.icon}</span>
              <span class="cabinet-path-name">{cab.name}</span>
            </div>
            <div class="cabinet-path-value" title={cabinetPaths[cab.id] || '...'}>
              {cabinetPaths[cab.id] || '...'}
            </div>
            <div class="cabinet-path-actions">
              <button class="btn-path" onclick={() => pickCabinetFolder(cab.id)}>
                Выбрать папку
              </button>
              <button class="btn-path btn-path-reset" onclick={() => resetCabinetFolder(cab.id)}>
                Сбросить
              </button>
            </div>
          </div>
        {/each}
      </div>
    </section>
    {/if}

    <section class="section">
      <h2 class="section-title">Идентификатор машины</h2>
      <p class="section-desc">Уникальный ID этого компьютера. Передайте администратору для привязки лицензии.</p>
      <div class="machine-id">
        <code>{machineId}</code>
      </div>
      <button class="copy-hash-btn" onclick={copyAllFingerprints}>
        {allCopied ? '✓ Скопировано!' : 'Скопировать Hash для лицензии'}
      </button>
    </section>

    <!-- L18-L20 (math-fix v1.4 Section C, 2026-04-29): Settings cleanup.
         Removed: file-based «Лицензия» block (legacy [LI-001] error pattern),
         «Версия контента: c1» (unclear notation). Renamed: «Подключение к
         серверу» → «Лицензия» (online auth = primary licensing path).
         Backend code preserved (SA15) - Ed25519 + license.rs остаются для
         legacy fallback в online_auth.rs flow. -->
    <section class="section">
      <h2 class="section-title">Лицензия</h2>
      <div class="connection-status">
        <!-- #61 (2026-06-02) [LI-001 fix]: приоритет источников статуса.
             Раньше учитывался только onlineStatus → при offline (exception или
             status='offline') показывалось «не подтверждена / неизвестно», даже
             при валидной офлайн Ed25519-лицензии. Теперь: online-ok → офлайн-valid
             → cached → нет лицензии. Приоритет — в resolveLicenseTier (license-display.js). -->
        {#if licenseTier === 'online-ok'}
          <div class="status-row">
            <span class="status-dot dot-ok"></span>
            <span class="status-text-label">Лицензия активна</span>
          </div>
          {#if onlineStatus && onlineStatus.expires_at}
            <p class="connection-detail">Действует до: {new Date(onlineStatus.expires_at).toLocaleDateString('ru-RU')}</p>
          {/if}
          {#if onlineStatus && onlineStatus.machine_id}
            <p class="connection-detail">Instance: {onlineStatus.machine_id}</p>
          {/if}
        {:else if licenseTier === 'offline-valid'}
          <div class="status-row">
            <span class="status-dot dot-ok"></span>
            <span class="status-text-label">Лицензия активна (офлайн)</span>
          </div>
          {#if licenseStatus?.expires_at}
            <p class="connection-detail">Действует до: {new Date(licenseStatus.expires_at).toLocaleDateString('ru-RU')}</p>
          {/if}
        {:else if licenseTier === 'cached'}
          <div class="status-row">
            <span class="status-dot dot-cached"></span>
            <span class="status-text-label">Работа по кэшу (соединение временно недоступно)</span>
          </div>
          {#if onlineStatus && onlineStatus.expires_at}
            <p class="connection-detail">Действует до: {new Date(onlineStatus.expires_at).toLocaleDateString('ru-RU')}</p>
          {/if}
        {:else}
          <div class="status-row">
            <span class="status-dot dot-offline"></span>
            <span class="status-text-label">Лицензия не подтверждена</span>
          </div>
        {/if}
      </div>
    </section>

    <!-- L18-L20: «Статистика использования» block removed entirely (irrelevant
         для Econometrica build, leaked Aurora Agency commands в UI). -->

    <!-- Секция показывается ВСЕГДА, а не только при непустом списке кабинетов
         (находка аудита): список пуст ровно тогда, когда не прошла авторизация
         или не отдался список кабинетов — то есть при тех самых сетевых
         проблемах, ради которых запасной путь и существует. Пряча секцию по
         пустому списку, мы отнимали кнопку у единственных, кому она нужна. -->
    <section class="section">
      <h2 class="section-title">Материалы кабинетов</h2>
      {#if vaultStatus.length > 0}
        <div class="vault-list">
          {#each vaultStatus as [cabId, cabName, hasVault]}
            <div class="vault-row">
              <span class="vault-dot" class:vault-ok={hasVault} class:vault-missing={!hasVault}></span>
              <span class="vault-name">{cabName}</span>
              <span class="vault-status-text">{hasVault ? 'Активен' : 'Не найден'}</span>
            </div>
          {/each}
        </div>
      {:else}
        <p class="section-desc">
          Список кабинетов сейчас недоступен – обычно это значит, что не удалось связаться
          с сервером. Материалы можно загрузить из файла.
        </p>
      {/if}
      <p class="section-desc" style="margin-top: 12px;">
        Обычно материалы кабинетов приезжают с сервера сами. Если связь их не пропускает
        (например, в сети организации), запросите файл в поддержке и загрузите вручную.
      </p>
      <button class="btn-logs" onclick={importVault}>Загрузить материалы из файла</button>
      {#if vaultImportStatus}
        <p class="section-desc" style="margin-top: 8px;">{vaultImportStatus}</p>
      {/if}
    </section>

    <section class="section">
      <h2 class="section-title">Логи и диагностика</h2>
      <p class="section-desc">Журнал работы приложения. При проблемах - экспортируйте отчёт и отправьте в поддержку.</p>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <button class="btn-logs" onclick={async () => { try { await invoke('open_logs_folder'); } catch(e) { console.error(e); } }}>
          Открыть папку логов
        </button>
        <button class="btn-logs" disabled={diagExporting}
          onclick={async () => {
            diagExporting = true; diagPath = '';
            try {
              diagPath = /** @type {string} */ (await invoke('export_diagnostics'));
            } catch(e) { diagPath = `Ошибка: ${e}`; }
            finally { diagExporting = false; }
          }}>
          {diagExporting ? 'Экспорт...' : 'Экспорт диагностики'}
        </button>
      </div>
      {#if diagPath}
        <p class="section-desc" style="margin-top: 8px; font-size: 12px; color: var(--accent-primary);">{diagPath}</p>
      {/if}
    </section>

    <section class="section about-section">
      <div class="app-info">
        <img src="/logo-full.png" alt="" class="app-info-logo" />
        <div>
          <span class="app-info-name">{PRODUCT_NAME_FULL}</span>
          <span class="app-info-version">v{APP_VERSION}</span>
          <!-- CPD-09: до 17.08 здесь стояло «© 2026 А. Сипович · www.sipovich.pro» –
               имя частного лица и посторонний адрес на единственном экране, где клиент
               ищет, чья это программа. Канон линейки взят из справки (13 страниц,
               `help-econometrica/*.html`): правообладатель – ООО «Платформа Аврора». -->
          <p class="about-text copyright">© 2026 ООО «Платформа Аврора» ·
            <a class="site-link" href={siteUrl(PRODUCT_SITE)} onclick={openSite(PRODUCT_SITE)} onauxclick={openSite(PRODUCT_SITE)}>{PRODUCT_SITE}</a></p>
          <p class="about-text copyright">{PRODUCT_NAME_FULL} – часть семьи решений Aurora AI ·
            <a class="site-link" href={siteUrl(UMBRELLA_SITE)} onclick={openSite(UMBRELLA_SITE)} onauxclick={openSite(UMBRELLA_SITE)}>{UMBRELLA_SITE}</a></p>
        </div>
      </div>
    </section>
  </main>
</div>

<style>
  .settings {
    height: 100%;
    display: flex;
    flex-direction: column;
  }

  .header {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 28px;
    height: 52px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-glass);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    flex-shrink: 0;
  }

  .header-logo-link {
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    line-height: 0;
  }
  .header-logo {
    height: 40px;
    width: auto;
  }

  .header h1 {
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  .back-link {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-muted);
    text-decoration: none;
    font-size: 13px;
    padding: 6px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-subtle);
    transition: all var(--transition-fast);
  }

  .back-link:hover {
    color: var(--text-primary);
    background: var(--bg-tertiary);
    border-color: var(--border);
  }

  .content {
    flex: 1;
    overflow-y: auto;
    /* 09.09.2026: нижний отступ увеличен с 32 до 72 px. Карточка «о программе» получила
       вторую строку (INV-146), и на невысоком окне она обрезалась нижней границей —
       прокрутка доходила до предела раньше, чем текст помещался целиком. */
    padding: 32px 28px 72px;
    max-width: 580px;
  }

  .settings-logo {
    text-align: center;
    margin-bottom: 16px;
    padding: 16px 0 0;
  }

  .settings-logo-img {
    height: 140px;
    width: auto;
  }

  /* Чип названия (electric-blue, как BrandChip на главной – стандарт Aurora Core):
     accent-рамка 40% + accent-фон 8% + accent-текст. width: fit-content + margin
     auto центрирует блочный элемент внутри .settings-logo. */
  .settings-logo-subtitle {
    display: block;
    width: fit-content;
    margin: 4px auto 0;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: var(--accent-primary);
    padding: 5px 12px;
    border: 1px solid color-mix(in srgb, var(--accent-primary) 40%, transparent);
    background: color-mix(in srgb, var(--accent-primary) 8%, transparent);
    border-radius: var(--radius-chip, 8px);
    text-transform: uppercase;
  }

  .section {
    margin-bottom: 28px;
    padding: 20px 22px;
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    -webkit-backdrop-filter: var(--blur-quiet);
    border: var(--glass-border);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-elevation-1);
  }

  /* Единственный переключатель режима работы: слева «полностью локально»,
     справа «через шлюз Авроры». Промежуточного положения нет. */
  .route-switch {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 14px;
    margin: 16px 0 12px;
    flex-wrap: wrap;
  }

  .route-side {
    font-size: 13px;
    color: var(--text-secondary);
    transition: color var(--transition-fast);
  }

  /* Действующее положение читается без вглядывания в сам переключатель. */
  .route-side-on {
    color: var(--text-primary);
    font-weight: 600;
  }

  .route-toggle {
    position: relative;
    width: 56px;
    height: 28px;
    flex-shrink: 0;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg-tertiary);
    cursor: pointer;
    transition: background var(--transition-fast), border-color var(--transition-fast);
  }

  .route-toggle:hover:not(:disabled) {
    border-color: var(--border-active);
  }

  .route-toggle:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }

  .route-toggle-on {
    background: var(--accent-primary, var(--text-primary));
    border-color: var(--accent-primary, var(--text-primary));
  }

  /* Положение не прочитано: ползунок посередине — ни одно из двух не утверждается. */
  .route-toggle-unknown .route-knob {
    left: 50%;
    transform: translate(-50%, -50%);
    background: var(--text-secondary);
  }

  .route-knob {
    position: absolute;
    top: 50%;
    left: 3px;
    transform: translateY(-50%);
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--text-secondary);
    transition: left var(--transition-fast), background var(--transition-fast);
  }

  .route-toggle-on .route-knob {
    left: 31px;
    background: var(--bg-primary, #fff);
  }

  .route-headline {
    margin-top: 4px;
  }

  .route-locked {
    margin-top: 6px;
    color: var(--text-secondary);
  }

  @media (prefers-reduced-motion: reduce) {
    .route-toggle,
    .route-knob,
    .route-side {
      transition: none;
    }
  }

  .section-title {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 10px;
  }

  .section-desc {
    font-size: 13px;
    color: var(--text-secondary);
    margin-bottom: 14px;
    line-height: 1.55;
  }

  .machine-id {
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--bg-tertiary);
    padding: 11px 14px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--accent-glow);
  }

  .machine-id code {
    flex: 1;
    font-size: 14px;
    font-family: var(--font-mono);
    letter-spacing: 0.12em;
    color: var(--accent-text-light);
  }


  .copy-hash-btn {
    margin-top: 10px;
    padding: 6px 14px;
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: all var(--transition-fast);
    width: 100%;
  }

  .copy-hash-btn:hover {
    color: var(--text-secondary);
    border-color: var(--border);
    background: var(--hover-bg);
  }

  .raw-fp-btn {
    margin-top: 6px;
    border-color: color-mix(in srgb, var(--accent-secondary) 15%, transparent);
    color: color-mix(in srgb, var(--accent-secondary) 60%, transparent);
  }

  .raw-fp-btn:hover {
    border-color: color-mix(in srgb, var(--accent-secondary) 30%, transparent);
    color: var(--accent-secondary);
    background: color-mix(in srgb, var(--accent-secondary) 5%, transparent);
  }

  .status-card {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 14px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-subtle);
    margin-bottom: 14px;
    background: var(--bg-tertiary);
  }

  .status-card.status-ok {
    border-color: color-mix(in srgb, var(--success) 25%, transparent);
    background: color-mix(in srgb, var(--success) 5%, transparent);
  }

  .status-card.status-error {
    border-color: color-mix(in srgb, var(--danger) 25%, transparent);
    background: color-mix(in srgb, var(--danger) 5%, transparent);
  }

  .status-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    margin-top: 4px;
    flex-shrink: 0;
  }

  .status-dot.ok {
    background: var(--success);
    box-shadow: 0 0 8px color-mix(in srgb, var(--success) 50%, transparent);
    animation: glow-pulse 2.5s ease-in-out infinite;
  }

  .status-dot.error {
    background: var(--danger);
    box-shadow: 0 0 6px color-mix(in srgb, var(--danger) 50%, transparent);
  }

  .status-label {
    font-size: 13.5px;
    font-weight: 600;
    margin-bottom: 4px;
  }

  .status-detail {
    font-size: 12.5px;
    color: var(--text-secondary);
    margin-top: 2px;
  }

  .btn {
    padding: 9px 22px;
    border-radius: var(--radius-sm);
    font-size: 13.5px;
    font-weight: 500;
    cursor: pointer;
    transition: all var(--transition);
  }

  .btn-accent {
    background: linear-gradient(135deg, var(--accent-primary) 0%, #4A76FF 100%);
    color: white;
    border: none;
    box-shadow: var(--shadow-glow);
  }

  .btn-accent:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-glow);
    filter: brightness(1.08);
  }

  .import-status {
    margin-top: 10px;
    font-size: 13px;
    color: var(--text-secondary);
  }

  .metrics-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-bottom: 12px;
  }

  .metric-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 12px 8px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
  }

  .metric-value {
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }

  .metric-label {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 2px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .metric-detail {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 6px;
  }

  .reset-metrics-btn {
    margin-top: 12px;
    padding: 5px 14px;
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 11px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .reset-metrics-btn:hover {
    color: var(--danger);
    border-color: color-mix(in srgb, var(--danger) 20%, transparent);
    background: color-mix(in srgb, var(--danger) 5%, transparent);
  }

  .btn-logs {
    padding: 8px 18px;
    background: var(--hover-bg);
    color: var(--text-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .btn-logs:hover {
    color: var(--text-primary);
    background: var(--hover-bg);
    border-color: var(--border);
  }

  /* ── Command Chart ── */
  .chart-section {
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid var(--border-subtle);
  }

  .chart-title {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 10px;
  }

  .chart-bars {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .chart-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .chart-label {
    width: 80px;
    font-size: 12px;
    color: var(--text-secondary);
    font-family: var(--font-mono);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .chart-bar-track {
    flex: 1;
    height: 14px;
    background: var(--bg-tertiary);
    border-radius: 4px;
    overflow: hidden;
  }

  .chart-bar-fill {
    height: 100%;
    background: var(--gradient-accent-line);
    border-radius: 4px;
    min-width: 4px;
    transition: width 0.3s ease;
  }

  .chart-value {
    width: 30px;
    font-size: 12px;
    color: var(--text-muted);
    text-align: right;
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
  }

  /* ── Vault Status ── */
  .vault-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .vault-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
  }

  .vault-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .vault-dot.vault-ok {
    background: var(--success, #10B981);
    box-shadow: 0 0 6px color-mix(in srgb, var(--success) 40%, transparent);
  }

  .vault-dot.vault-missing {
    background: var(--danger, #EF4444);
    box-shadow: 0 0 6px color-mix(in srgb, var(--danger) 40%, transparent);
  }

  .vault-name {
    flex: 1;
    font-size: 13px;
    color: var(--text-secondary);
  }

  .vault-status-text {
    font-size: 11px;
    color: var(--text-muted);
    flex-shrink: 0;
  }

  /* ── Platform Button ── */
  .btn-platform {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    width: 100%;
    padding: 14px 24px;
    margin-bottom: 28px;
    background: linear-gradient(135deg, var(--accent-primary, #2E5BFF) 0%, #4A76FF 50%, #5A8AFF 100%);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-lg);
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    cursor: pointer;
    transition: all var(--transition);
    box-shadow: var(--shadow-glow);
  }

  .btn-platform:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-glow);
    filter: brightness(1.1);
  }

  .btn-platform:active {
    transform: translateY(0);
    box-shadow: var(--shadow-glow);
  }

  .about-text {
    font-size: 13.5px;
    color: var(--text-primary);
    margin-bottom: 3px;
  }

  .app-info {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 0;
  }

  .app-info-logo {
    height: 50px;
    width: auto;
    opacity: 0.85;
  }

  .app-info-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .app-info-version {
    font-size: 11px;
    color: var(--text-muted);
    background: var(--hover-bg);
    padding: 1px 6px;
    border-radius: 4px;
  }

  /* Ссылка подчёркнута постоянно: на этом экране адрес — единственный элемент, по
     которому можно нажать, и без подчёркивания он неотличим от обычного текста. */
  .site-link {
    color: inherit;
    text-decoration: underline;
    text-underline-offset: 2px;
    text-decoration-thickness: 1px;
    cursor: pointer;
  }

  .site-link:hover,
  .site-link:focus-visible {
    color: var(--text-primary);
    text-decoration-thickness: 2px;
  }

  .about-text.copyright {
    color: var(--text-muted);
    font-size: 11px;
    margin-top: 0;
    letter-spacing: 0.02em;
  }

  .feedback-form {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .fb-select {
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    cursor: pointer;
  }

  .fb-textarea {
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 13px;
    font-family: inherit;
    resize: vertical;
    min-height: 80px;
  }

  .fb-textarea::placeholder, .fb-input::placeholder {
    color: var(--text-muted);
  }

  .fb-input {
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
  }

  .fb-submit {
    background: var(--accent, #3B82F6);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    font-size: 13px;
    cursor: pointer;
    transition: opacity 0.2s;
    align-self: flex-start;
  }

  .fb-submit:hover:not(:disabled) {
    opacity: 0.9;
  }

  .fb-submit:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .fb-error {
    color: var(--danger, #EF4444);
    font-size: 12px;
    margin: 0;
  }

  /* Подтверждение отправки. Живёт столько же, сколько запрет повторной отправки. */
  .fb-success {
    color: var(--success, #10B981);
    font-size: 12px;
    margin: 0;
  }

  /* Пояснения под полем текста: что уходит вместе с обращением и куда писать за ответом. */
  .fb-note {
    color: var(--text-muted, #6B7280);
    font-size: 12px;
    line-height: 1.45;
    margin: 0;
  }

  /* Сырая строка отказа — нужна поддержке, человеку показываем по его выбору. */
  .fb-details {
    color: var(--text-muted, #6B7280);
    font-size: 11px;
  }

  .fb-details summary {
    cursor: pointer;
  }

  /* ── Theme Toggle ── */
  .theme-toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .theme-label {
    font-size: 13px;
    color: var(--text-secondary);
  }

  .theme-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 7px 14px;
    background: var(--bg-tertiary);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .theme-toggle:hover {
    background: var(--bg-card-hover);
    border-color: var(--border-active);
  }

  .model-select {
    background: var(--bg-card);
    color: var(--text-primary);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    cursor: pointer;
    outline: none;
  }

  .model-select:hover {
    border-color: var(--border-active);
  }

  /* ── Connection Status ── */
  .connection-status {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .status-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .dot-ok {
    background: var(--success, #10B981);
    box-shadow: 0 0 6px color-mix(in srgb, var(--success) 50%, transparent);
  }

  .dot-cached {
    background: var(--warning, #F59E0B);
    box-shadow: 0 0 6px color-mix(in srgb, var(--warning) 50%, transparent);
  }

  .dot-offline {
    background: var(--danger, #EF4444);
    box-shadow: 0 0 6px color-mix(in srgb, var(--danger) 40%, transparent);
  }

  .status-text-label {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .connection-detail {
    font-size: 12px;
    color: var(--text-muted);
    margin-left: 16px;
  }

  /* ── Cabinet Paths ── */
  .cabinet-paths {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .cabinet-path-row {
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
  }

  .cabinet-path-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }

  .cabinet-path-icon {
    font-size: 16px;
  }

  .cabinet-path-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .cabinet-path-value {
    font-size: 12px;
    color: var(--text-muted);
    font-family: monospace;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-bottom: 8px;
  }

  .cabinet-path-actions {
    display: flex;
    gap: 8px;
  }

  .btn-path {
    font-size: 12px;
    padding: 5px 12px;
    border-radius: 5px;
    border: 1px solid var(--border);
    background: var(--bg-secondary);
    color: var(--text-primary);
    cursor: pointer;
    transition: background 0.15s;
  }

  .btn-path:hover {
    background: var(--hover-bg);
  }

  .btn-path-reset {
    color: var(--text-muted);
  }

  /* v2.1.0 п.5.6: static status dot - no pulse glow */
  @media (prefers-reduced-motion: reduce) {
    .status-dot.dot-ok {
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--success) 40%, transparent);
    }
  }
</style>
