<script>
  import { invoke } from '@tauri-apps/api/core';
  import { open } from '@tauri-apps/plugin-dialog';
  import { theme, toggleTheme } from '$lib/store.js';
  import { productType } from '$lib/creative-store.js';
  import { getProductName } from '$lib/command-meta.js';
  import { getVersion } from '@tauri-apps/api/app';

  let APP_VERSION = $state('...');
  getVersion().then(v => { APP_VERSION = v; }).catch(() => { APP_VERSION = '?'; });
  import { isAudioEnabled, setAudioEnabled } from '$lib/audio.js';

  let audioEnabled = $state(isAudioEnabled());
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
  /** @type {{status: string, content_version: string|null, expires_at: string|null, machine_id: string}|null} */
  let onlineStatus = $state(null);
  let contentVersion = $state('');

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
      vaultStatus = await invoke('list_vault_status');
    } catch { vaultStatus = []; }
  }

  let guideError = $state('');

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
      cabinets = await invoke('get_cabinets');
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

  loadStatus();
  loadMetrics();
  loadVaultStatus();
  loadCabinetPaths();

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
    <a href="/" class="back-link">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      Назад
    </a>
    <h1>Настройки</h1>
  </header>

  <main class="content">
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
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
            <span>Тёмная</span>
          {:else}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="5"/>
              <line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
              <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
            </svg>
            <span>Светлая</span>
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
      <h2 class="section-title">Справочный центр</h2>
      <p class="section-desc">Руководства по всем кабинетам, советы, рекомендации и pipeline работы.</p>
      <button class="btn-logs" onclick={async () => { try { await invoke('open_help', { cabinetId: 'index' }); } catch(e) { guideError = String(e); console.error(e); } }}>
        Открыть справочный центр
      </button>
      {#if guideError}
        <p class="import-status" style="color: var(--danger)">{guideError}</p>
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

    <section class="section">
      <h2 class="section-title">Лицензия</h2>
      {#if licenseError}
        <div class="status-card status-error">
          <span class="status-dot error"></span>
          <div>
            <p class="status-label">Лицензия не найдена</p>
            <p class="status-detail">{licenseError}</p>
          </div>
        </div>
      {:else if licenseStatus}
        <div class="status-card" class:status-ok={licenseStatus.valid} class:status-error={!licenseStatus.valid}>
          <span class="status-dot" class:ok={licenseStatus.valid} class:error={!licenseStatus.valid}></span>
          <div>
            <p class="status-label">
              {licenseStatus.valid ? 'Лицензия активна' : 'Лицензия невалидна'}
            </p>
            {#if licenseStatus.error}
              <p class="status-detail">{licenseStatus.error}</p>
            {/if}
            <p class="status-detail">Компания: {licenseStatus.issued_to}</p>
            <p class="status-detail">Истекает: {licenseStatus.expires_at}</p>
            {#if licenseStatus.cabinets.length > 0}
              <p class="status-detail">Кабинеты: {licenseStatus.cabinets.join(', ')}</p>
            {/if}
          </div>
        </div>
      {/if}

      <button class="btn btn-accent" onclick={importLicense}>
        Импортировать лицензию
      </button>
      {#if importStatus}
        <p class="import-status">{importStatus}</p>
      {/if}
    </section>

    <section class="section">
      <h2 class="section-title">Подключение к серверу</h2>
      <div class="connection-status">
        {#if onlineStatus}
          <div class="status-row">
            <span class="status-dot" class:dot-ok={onlineStatus.status === 'ok'} class:dot-cached={onlineStatus.status === 'cached'} class:dot-offline={onlineStatus.status === 'offline' || onlineStatus.status === 'blocked'}></span>
            <span class="status-text-label">
              {#if onlineStatus.status === 'ok'}
                Подключён к серверу
              {:else if onlineStatus.status === 'cached'}
                Работа по кэшу
              {:else}
                Офлайн
              {/if}
            </span>
          </div>
          {#if onlineStatus.expires_at}
            <p class="connection-detail">Лицензия до: {new Date(onlineStatus.expires_at).toLocaleDateString('ru-RU')}</p>
          {/if}
          {#if contentVersion}
            <p class="connection-detail">Версия контента: {contentVersion}</p>
          {/if}
          {#if onlineStatus.machine_id}
            <p class="connection-detail">Instance: {onlineStatus.machine_id}</p>
          {/if}
        {:else}
          <div class="status-row">
            <span class="status-dot dot-offline"></span>
            <span class="status-text-label">Статус неизвестен</span>
          </div>
        {/if}
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">Статистика использования</h2>
      {#if usageMetrics}
        <div class="metrics-grid">
          <div class="metric-card">
            <span class="metric-value">{usageMetrics.total_sessions}</span>
            <span class="metric-label">Сессий</span>
          </div>
          <div class="metric-card">
            <span class="metric-value">{usageMetrics.total_messages}</span>
            <span class="metric-label">Сообщений</span>
          </div>
          <div class="metric-card">
            <span class="metric-value">{usageMetrics.total_exports}</span>
            <span class="metric-label">Экспортов</span>
          </div>
          <div class="metric-card">
            <span class="metric-value">{usageMetrics.avg_response_time_secs > 0 ? usageMetrics.avg_response_time_secs.toFixed(0) + 'с' : '—'}</span>
            <span class="metric-label">Ср. время ответа</span>
          </div>
        </div>
        {#if usageMetrics.cabinets_used?.length > 0}
          <p class="metric-detail">Кабинеты: {usageMetrics.cabinets_used.join(', ')}</p>
        {/if}
        {#if usageMetrics.first_use}
          <p class="metric-detail">Используется с {usageMetrics.first_use.split('T')[0]}</p>
        {/if}
        {#if usageMetrics.command_counts && Object.keys(usageMetrics.command_counts).length > 0}
          {@const entries = Object.entries(usageMetrics.command_counts).sort((a, b) => b[1] - a[1]).slice(0, 10)}
          {@const maxCount = Math.max(...entries.map(e => e[1]))}
          <div class="chart-section">
            <h3 class="chart-title">Использование команд</h3>
            <div class="chart-bars">
              {#each entries as [cmd, count]}
                <div class="chart-row">
                  <span class="chart-label">/{cmd}</span>
                  <div class="chart-bar-track">
                    <div
                      class="chart-bar-fill"
                      style="width: {(count / maxCount) * 100}%"
                    ></div>
                  </div>
                  <span class="chart-value">{count}</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}
        <button class="reset-metrics-btn" onclick={resetMetrics}>Сбросить статистику</button>
      {:else}
        <p class="section-desc">Данных пока нет — начните работу с кабинетами</p>
      {/if}
    </section>

    {#if vaultStatus.length > 0}
      <section class="section">
        <h2 class="section-title">Vault-статус</h2>
        <div class="vault-list">
          {#each vaultStatus as [cabId, cabName, hasVault]}
            <div class="vault-row">
              <span class="vault-dot" class:vault-ok={hasVault} class:vault-missing={!hasVault}></span>
              <span class="vault-name">{cabName}</span>
              <span class="vault-status-text">{hasVault ? 'Активен' : 'Не найден'}</span>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <section class="section">
      <h2 class="section-title">Логи</h2>
      <p class="section-desc">Журнал работы приложения. Полезно для диагностики проблем.</p>
      <button class="btn-logs" onclick={async () => { try { await invoke('open_logs_folder'); } catch(e) { console.error(e); } }}>
        Открыть папку логов
      </button>
    </section>

    <section class="section about-section">
      <div class="app-info">
        <span class="app-info-name">{getProductName($productType)}</span>
        <span class="app-info-version">v{APP_VERSION}</span>
      </div>
      <p class="about-text copyright">© 2026 А. Сипович · www.sipovich.pro</p>
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
    border: 1px solid rgba(255, 255, 255, 0.06);
    transition: all var(--transition-fast);
  }

  .back-link:hover {
    color: var(--text-primary);
    background: var(--bg-tertiary);
    border-color: rgba(255, 255, 255, 0.1);
  }

  .content {
    flex: 1;
    overflow-y: auto;
    padding: 32px 28px;
    max-width: 580px;
  }

  .section {
    margin-bottom: 28px;
    padding: 20px 22px;
    background: var(--bg-glass);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: var(--glass-border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-card);
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
    background: rgba(0, 0, 0, 0.25);
    padding: 11px 14px;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(46, 91, 255, 0.15);
  }

  .machine-id code {
    flex: 1;
    font-size: 14px;
    font-family: var(--font-mono);
    letter-spacing: 0.12em;
    color: #8EB4FF;
  }


  .copy-hash-btn {
    margin-top: 10px;
    padding: 6px 14px;
    background: transparent;
    color: var(--text-muted);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: all var(--transition-fast);
    width: 100%;
  }

  .copy-hash-btn:hover {
    color: var(--text-secondary);
    border-color: rgba(255, 255, 255, 0.15);
    background: rgba(255, 255, 255, 0.04);
  }

  .raw-fp-btn {
    margin-top: 6px;
    border-color: rgba(204, 255, 0, 0.15);
    color: rgba(204, 255, 0, 0.6);
  }

  .raw-fp-btn:hover {
    border-color: rgba(204, 255, 0, 0.3);
    color: rgba(204, 255, 0, 0.85);
    background: rgba(204, 255, 0, 0.05);
  }

  .status-card {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 14px;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(255, 255, 255, 0.06);
    margin-bottom: 14px;
    background: rgba(0, 0, 0, 0.2);
  }

  .status-card.status-ok {
    border-color: rgba(16, 185, 129, 0.25);
    background: rgba(16, 185, 129, 0.05);
  }

  .status-card.status-error {
    border-color: rgba(239, 68, 68, 0.25);
    background: rgba(239, 68, 68, 0.05);
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
    box-shadow: 0 0 8px rgba(16, 185, 129, 0.5);
    animation: glow-pulse 2.5s ease-in-out infinite;
  }

  .status-dot.error {
    background: var(--danger);
    box-shadow: 0 0 6px rgba(239, 68, 68, 0.5);
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
    box-shadow: 0 2px 12px rgba(46, 91, 255, 0.25);
  }

  .btn-accent:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 20px rgba(46, 91, 255, 0.45);
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
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid rgba(255, 255, 255, 0.06);
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
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    font-size: 11px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .reset-metrics-btn:hover {
    color: #EF4444;
    border-color: rgba(239, 68, 68, 0.2);
    background: rgba(239, 68, 68, 0.05);
  }

  .btn-logs {
    padding: 8px 18px;
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-secondary);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .btn-logs:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.18);
  }

  /* ── Command Chart ── */
  .chart-section {
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
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
    background: rgba(0, 0, 0, 0.2);
    border-radius: 4px;
    overflow: hidden;
  }

  .chart-bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #2E5BFF 0%, rgba(204, 255, 0, 0.7) 100%);
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
    box-shadow: 0 0 6px rgba(16, 185, 129, 0.4);
  }

  .vault-dot.vault-missing {
    background: var(--danger, #EF4444);
    box-shadow: 0 0 6px rgba(239, 68, 68, 0.4);
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
    color: #fff;
    border: none;
    border-radius: var(--radius-lg);
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    cursor: pointer;
    transition: all var(--transition);
    box-shadow: 0 4px 20px rgba(46, 91, 255, 0.35);
  }

  .btn-platform:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 28px rgba(46, 91, 255, 0.5);
    filter: brightness(1.1);
  }

  .btn-platform:active {
    transform: translateY(0);
    box-shadow: 0 2px 12px rgba(46, 91, 255, 0.3);
  }

  .about-text {
    font-size: 13.5px;
    color: var(--text-primary);
    margin-bottom: 3px;
  }

  .app-info {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 6px;
  }

  .app-info-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .app-info-version {
    font-size: 11px;
    color: var(--text-muted);
    background: rgba(255, 255, 255, 0.04);
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
    color: #fff;
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
    box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
  }

  .dot-cached {
    background: var(--warning, #F59E0B);
    box-shadow: 0 0 6px rgba(245, 158, 11, 0.5);
  }

  .dot-offline {
    background: var(--danger, #EF4444);
    box-shadow: 0 0 6px rgba(239, 68, 68, 0.4);
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
</style>
