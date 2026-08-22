<script>
  import { invoke } from '@tauri-apps/api/core';
  import { open } from '@tauri-apps/plugin-dialog';
  import { theme, toggleTheme, cloudConsent, cloudConsentPromptOpen } from '$lib/store.js';
  import { productType } from '$lib/creative-store.js';
  import { getProductName, filterCabinetsByProduct } from '$lib/command-meta.js';

  let APP_VERSION = $state('...');
  // Номер версии один на поставку (ADR-049 §2): буква редакции убрана вместе со вторым
  // каналом обновлений. Где исполняется работа — показывает признак режима, не номер.
  invoke('display_version').then(v => { APP_VERSION = v; }).catch(() => { APP_VERSION = '?'; });
  import { isAudioEnabled, setAudioEnabled } from '$lib/audio.js';
  import { onboardingEnabled } from '$lib/onboarding-state.js';
  import { hideEducationalHints, showGlossaryPanel, showIntroTutorial } from '$lib/project-state.js';
  import { resolveLicenseTier } from '$lib/license-display.js';

  let audioEnabled = $state(isAudioEnabled());

  // Cloud-consent (облачная редакция): отзыв — прямое действие тумблера; выдача — через
  // экран согласия с чекбоксом-подтверждением (не молчаливый grant). Секция видна только
  // в облачной редакции ($cloudConsent.advisorsEnabled).
  let consentBusy = $state(false);
  let consentMsg = $state('');
  async function withdrawConsent() {
    if (consentBusy) return;
    consentBusy = true;
    consentMsg = '';
    try {
      await invoke('withdraw_cloud_consent');
      cloudConsent.update((c) => ({ ...c, granted: false }));
      consentMsg = '✓ Облачная обработка отключена. Кабинеты-советники недоступны; MMM-анализ работает.';
      setTimeout(() => { consentMsg = ''; }, 7000);
    } catch (e) {
      consentMsg = 'Ошибка: ' + String(e);
    } finally {
      consentBusy = false;
    }
  }
  function toggleCloudConsent() {
    if ($cloudConsent.granted) {
      withdrawConsent();
    } else {
      cloudConsentPromptOpen.set(true);
    }
  }

  // Runtime-режим «только локально»: явное отключение облачного ИИ (egress).
  // Гейт-поверх-согласия — даже при данном согласии пользователь может закрыть egress.
  let localOnlyBusy = $state(false);

  // ── Режим исполнения советника (ADR-049) ──────────────────────────────────────
  // 🔴 Ось, отдельная от согласия и тумблера «только локально» выше: те решают,
  // обращаться ли к облачному ИИ вообще, эта — чей Claude Code исполняет работу.
  /** @type {{mode: string, source: string, explanation: string, explicit: string|null, cloud_built_in: boolean, local_available: boolean, cloud_refusal: string}|null} */
  let executionMode = $state(null);
  let modeBusy = $state(false);
  let modeError = $state('');

  async function loadExecutionMode() {
    try {
      executionMode = await invoke('get_execution_mode');
      modeError = '';
    } catch (e) {
      modeError = String(e);
    }
  }

  /** @param {string} mode */
  async function chooseExecutionMode(mode) {
    modeBusy = true;
    try {
      await invoke('set_execution_mode', { mode });
      await loadExecutionMode();
    } catch (e) {
      modeError = String(e);
    } finally {
      modeBusy = false;
    }
  }

  async function recheckLocalClaude() {
    modeBusy = true;
    try {
      executionMode = await invoke('probe_local_claude');
      modeError = '';
    } catch (e) {
      modeError = String(e);
    } finally {
      modeBusy = false;
    }
  }
  async function toggleLocalOnly() {
    if (localOnlyBusy) return;
    localOnlyBusy = true;
    try {
      const next = !$cloudConsent.localOnly;
      await invoke('set_local_only', { enabled: next });
      cloudConsent.update((c) => ({ ...c, localOnly: next }));
      consentMsg = next
        ? '✓ Режим «только локально» включён: облачный ИИ отключён, данные не уходят.'
        : '✓ Режим «только локально» выключен: облачный ИИ доступен (при согласии).';
      setTimeout(() => { consentMsg = ''; }, 7000);
    } catch (e) {
      consentMsg = 'Ошибка: ' + String(e);
    } finally {
      localOnlyBusy = false;
    }
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
  loadExecutionMode();

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
  let fbContact = $state('');
  /** @type {'idle'|'loading'|'success'|'error'} */
  let fbStatus = $state('idle');
  let fbError = $state('');

  async function submitFeedback() {
    if (!fbMessage.trim()) return;
    fbStatus = 'loading';
    fbError = '';
    try {
      await invoke('submit_feedback', { category: fbCategory, message: fbMessage, contact: fbContact });
      fbStatus = 'success';
      fbMessage = '';
      fbContact = '';
      setTimeout(() => { fbStatus = 'idle'; }, 3000);
    } catch (err) {
      fbStatus = 'error';
      fbError = String(err);
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
      <div class="theme-toggle-row">
        <span class="theme-label">Звуковые уведомления</span>
        <button class="theme-toggle" onclick={() => { audioEnabled = !audioEnabled; setAudioEnabled(audioEnabled); }}>
          {#if audioEnabled}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
              <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
              <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
            </svg>
            <span>Включены</span>
          {:else}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
              <line x1="23" y1="9" x2="17" y2="15"/>
              <line x1="17" y1="9" x2="23" y2="15"/>
            </svg>
            <span>Выключены</span>
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

    {#if $cloudConsent.advisorsEnabled}
      <section class="section">
        <h2 class="section-title">Облачная обработка (кабинеты-советники)</h2>
        <p class="section-desc">
          Кабинеты-советники отправляют контекст задачи на защищённый AI-сервер по вашей команде.
          MMM-анализ всегда выполняется локально. Отключение делает советников недоступными –
          расчёты продолжают работать. Включение запросит согласие на облачную обработку.
        </p>
        <div class="theme-toggle-row">
          <span class="theme-label">Облачная обработка</span>
          <button
            class="theme-toggle"
            onclick={toggleCloudConsent}
            disabled={consentBusy}
            aria-label="Toggle cloud processing consent"
          >
            {#if $cloudConsent.granted}
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              <span>Включена</span>
            {:else}
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="9"/>
                <line x1="15" y1="9" x2="9" y2="15"/>
                <line x1="9" y1="9" x2="15" y2="15"/>
              </svg>
              <span>Выключена</span>
            {/if}
          </button>
        </div>
        <div class="theme-toggle-row" style="margin-top: 12px;">
          <span class="theme-label">Только локально (данные не уходят)</span>
          <button
            class="theme-toggle"
            onclick={toggleLocalOnly}
            disabled={localOnlyBusy}
            aria-label="Toggle local-only mode"
          >
            {#if $cloudConsent.localOnly}
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              <span>Включён</span>
            {:else}
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="9"/>
                <line x1="15" y1="9" x2="9" y2="15"/>
              </svg>
              <span>Выключен</span>
            {/if}
          </button>
        </div>
        <p class="section-desc" style="margin-top: 6px;">
          Когда включено – встроенный ИИ-ассистент отключён полностью, ни один запрос не
          уходит на серверы. MMM-расчёты работают как обычно. Удобно для конфиденциальных данных.
        </p>
        {#if consentMsg}
          <p class="import-status" style="color: {consentMsg.startsWith('Ошибка') ? 'var(--danger)' : 'var(--success)'}; margin-top: 8px;">{consentMsg}</p>
        {/if}
      </section>

      <!--
        🔴 Раздел стоит ВНУТРИ условия «советники есть» намеренно (ADR-049 §6, гейт
        приёмки 3а): в локальной редакции советника нет вовсе, и предлагать там выбор
        «каким путём он работает» значило бы спрашивать о несуществующем.

        Это ДРУГАЯ ось, чем тумблеры выше. Те решают, обращаться ли к облачному ИИ
        вообще; этот раздел — если обращаемся, чей Claude Code исполняет работу.
        Ползунком «менее приватно → более приватно» их объединять нельзя: ответы ведут
        в разные режимы, и человеку, которому важно одно, подсказка про другое вредит.

        Тексты точны: сказать «данные никуда не уходят» про свой Claude Code было бы
        неправдой — они уходят к Anthropic, просто напрямую, без нашего участия.
      -->
      <section class="section" id="execution-mode">
        <h2 class="section-title">Где исполняется работа советника</h2>
        {#if executionMode}
          <p class="section-desc">{executionMode.explanation}</p>
          <div class="mode-options">
            <label class="mode-option" class:mode-active={executionMode.mode === 'local'}>
              <input
                type="radio"
                name="execution-mode"
                value="local"
                checked={executionMode.explicit === 'local'}
                disabled={modeBusy}
                onchange={() => chooseExecutionMode('local')}
              />
              <span class="mode-body">
                <span class="mode-name">Ваш Claude Code</span>
                <span class="mode-note">
                  Материалы идут с вашей машины прямо к Anthropic и не проходят через серверы
                  Платформы Аврора. Нужна своя действующая подписка Claude.
                </span>
                {#if !executionMode.local_available}
                  <span class="mode-warn">Сейчас недоступен: Claude Code на этой машине не запускается.</span>
                {/if}
              </span>
            </label>

            <label class="mode-option" class:mode-active={executionMode.mode === 'cloud'}>
              <input
                type="radio"
                name="execution-mode"
                value="cloud"
                checked={executionMode.explicit === 'cloud'}
                disabled={modeBusy || !executionMode.cloud_built_in}
                onchange={() => chooseExecutionMode('cloud')}
              />
              <span class="mode-body">
                <span class="mode-name">Шлюз Авроры</span>
                <span class="mode-note">
                  Работу советника выполняет наш сервер: своя подписка Claude не нужна. Материалы
                  проходят через Платформу Аврора.
                </span>
                {#if !executionMode.cloud_built_in}
                  <span class="mode-warn">Не входит в эту сборку.</span>
                {:else if executionMode.cloud_refusal}
                  <span class="mode-warn">{executionMode.cloud_refusal}</span>
                {/if}
              </span>
            </label>

            <label class="mode-option" class:mode-active={!executionMode.explicit}>
              <input
                type="radio"
                name="execution-mode"
                value=""
                checked={!executionMode.explicit}
                disabled={modeBusy}
                onchange={() => chooseExecutionMode('')}
              />
              <span class="mode-body">
                <span class="mode-name">Выбирать самостоятельно</span>
                <span class="mode-note">
                  Ваш Claude Code, если он запускается на этой машине; иначе шлюз Авроры.
                </span>
              </span>
            </label>
          </div>
          <p class="section-desc">
            Расчёт медиасплита выполняется на вашей машине в любом режиме – этот выбор касается
            только кабинета-советника.
          </p>
          <button class="btn-logs" disabled={modeBusy} onclick={recheckLocalClaude}>
            Проверить Claude Code сейчас
          </button>
        {:else}
          <p class="section-desc">Определяю режим…</p>
        {/if}
        {#if modeError}
          <p class="import-status" style="color: var(--danger)">{modeError}</p>
        {/if}
      </section>
    {/if}

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
          rows="4"
        ></textarea>
        <input
          class="fb-input"
          type="text"
          placeholder="Контакт для связи (необязательно)"
          bind:value={fbContact}
        />
        <button
          class="fb-submit"
          onclick={submitFeedback}
          disabled={fbStatus === 'loading' || !fbMessage.trim()}
        >
          {#if fbStatus === 'loading'}
            Отправка...
          {:else if fbStatus === 'success'}
            Отправлено!
          {:else}
            Отправить
          {/if}
        </button>
        {#if fbStatus === 'error'}
          <p class="fb-error">{fbError}</p>
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
          <span class="app-info-name">{getProductName($productType)}</span>
          <span class="app-info-version">v{APP_VERSION}</span>
          <p class="about-text copyright">© 2026 А. Сипович · www.sipovich.pro</p>
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
    padding: 32px 28px;
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

  /* Режим исполнения советника (ADR-049): выбор из двух путей плюс автоопределение. */
  .mode-options {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: 12px 0 14px;
  }

  .mode-option {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .mode-option:hover {
    background: var(--hover-bg);
  }

  /* Действующий сейчас режим виден, даже если выбран автоопределением. */
  .mode-option.mode-active {
    border-color: var(--accent-primary, var(--text-primary));
    background: var(--hover-bg);
  }

  .mode-option input {
    margin-top: 3px;
    flex-shrink: 0;
  }

  .mode-body {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .mode-name {
    font-size: 14px;
    color: var(--text-primary);
  }

  .mode-note {
    font-size: 12px;
    line-height: 1.5;
    color: var(--text-secondary);
  }

  .mode-warn {
    font-size: 12px;
    color: var(--danger);
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
