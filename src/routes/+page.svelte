<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { activeCabinet, messages, errorMessage, hasCompletedOnboarding, theme, toggleTheme, updateRequired, layoutCabinets, lastCabinetId } from '$lib/store.js';
  import { isCreativeHub, activeBrand, brands, refreshBrands, setActiveBrand, productType } from '$lib/creative-store.js';
  import { toast } from '$lib/toast.js';
  import CabinetCard from '$lib/components/CabinetCard.svelte';
  import BrandSelector from '$lib/components/BrandSelector.svelte';
  import AetherLogo from '$lib/components/AetherLogo.svelte';
  import SkeletonCard from '$lib/components/SkeletonCard.svelte';
  import { milestones } from '$lib/psy.js';

  // Dashboard stats derived from milestones
  let dashStats = $derived.by(() => {
    const m = $milestones;
    const total = m.totalRequests || 0;
    const entries = Object.entries(m.cabinetRequests || {});
    const topCabinet = entries.sort((a, b) => /** @type {number} */(b[1]) - /** @type {number} */(a[1]))[0];
    const activeCabinets = entries.filter(([, v]) => /** @type {number} */(v) > 0).length;
    return { total, topCabinet: topCabinet ? { id: topCabinet[0], count: topCabinet[1] } : null, activeCabinets };
  });

  // Inline brand creation for welcome screen
  let newBrandName = $state('');
  let creatingBrand = $state(false);

  async function quickCreateBrand() {
    if (!newBrandName.trim() || creatingBrand) return;
    creatingBrand = true;
    try {
      const brandId = newBrandName.toLowerCase().replace(/[^a-zа-яё0-9\s-]/gi, '').trim().replace(/\s+/g, '-').slice(0, 30) || `brand-${Date.now()}`;
      await invoke('brand_create', { brandId, name: newBrandName.trim(), industry: '', description: '' });
      await setActiveBrand(brandId);
      await refreshBrands();
      newBrandName = '';
      toast(`Бренд "${newBrandName || brandId}" создан`, 'success');
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    } finally {
      creatingBrand = false;
    }
  }
  import DigitalClock from '$lib/components/DigitalClock.svelte';
  import OnboardingOverlay from '$lib/components/OnboardingOverlay.svelte';

  import { filterCabinetsByProduct, getProductName } from '$lib/command-meta.js';
  // Cabinets filtered by product type (Legal=3, Creative=5, Agency=all)
  const cabinets = $derived(filterCabinetsByProduct($layoutCabinets, $productType));
  /** @type {string|null} */
  let licenseError = $state(null);
  let loading = $derived($layoutCabinets.length === 0 && !licenseError);
  /** @type {{file: string, current: number, total: number}|null} */
  let vaultProgress = $state(null);

  // Listen for vault progress from layout-level cabinet loading
  $effect(() => {
    let unlisten = /** @type {Function|null} */ (null);
    (async () => {
      const { listen } = await import('@tauri-apps/api/event');
      unlisten = await listen('vault-download-progress', (event) => {
        vaultProgress = /** @type {{file: string, current: number, total: number}} */ (event.payload);
      });
    })();
    return () => { if (unlisten) unlisten(); };
  });

  // Fetch license status when cabinets load
  $effect(() => {
    if ($layoutCabinets.length > 0) {
      vaultProgress = null;
      (async () => {
        try {
          const status = /** @type {{days_remaining: number}} */ (await invoke('get_license_status'));
          licenseDaysRemaining = status.days_remaining;
        } catch { /* license status unavailable */ }
      })();
    }
  });

  /** @type {string|null} */
  let openError = $state(null);
  /** @type {Array<[string, string, string]>} */
  let recentExports = $state([]);
  /** @type {{cabinetId: string, filename: string}|null} */
  let shareTarget = $state(null);
  let shareSuccess = $state('');
  /** @type {any} */
  let updateInfo = $state(null);
  let updateDismissed = $state(false);
  /** @type {number|null} */
  let licenseDaysRemaining = $state(null);
  let licenseBannerDismissed = $state(false);

  async function loadRecentExports() {
    try {
      recentExports = await invoke('list_recent_exports');
    } catch { recentExports = []; }
  }

  /** @param {string} sourceCabinetId @param {string} filename @param {string} targetCabinetId */
  async function shareToInbox(sourceCabinetId, filename, targetCabinetId) {
    try {
      await invoke('copy_export_to_inbox', { sourceCabinetId, filename, targetCabinetId });
      shareSuccess = `${filename} → ${targetCabinetId}`;
      shareTarget = null;
      setTimeout(() => { shareSuccess = ''; }, 3000);
    } catch (err) {
      console.error('Share failed:', err);
    }
  }

  /** @param {{id: string, name: string, description: string, icon: string, color: string}} cabinet */
  async function openCabinet(cabinet) {
    openError = null;
    try {
      await invoke('open_cabinet', { cabinetId: cabinet.id });
      activeCabinet.set(cabinet);
      messages.set([]);
      goto('/cabinet');
    } catch (err) {
      console.error('open_cabinet error:', err);
      openError = String(err);
    }
  }

  async function checkUpdate() {
    try {
      updateInfo = await invoke('check_update');
      // Mandatory updates handled by layout → UpdateBlockingOverlay
    } catch { /* fail-silent */ }
  }

  function triggerUpdate() {
    if (!updateInfo) return;
    updateRequired.set({
      required: true,
      url: updateInfo.download_url || null,
      version: updateInfo.version || null,
      notes: updateInfo.release_notes || null,
      checksum: updateInfo.checksum || null,
    });
  }

  /** @param {KeyboardEvent} e */
  function handleHomeKeydown(e) {
    // Ctrl+, → Settings
    if (e.ctrlKey && e.key === ',') {
      e.preventDefault();
      goto('/settings');
      return;
    }
    // 1-9 → open cabinet by index (only when not in input)
    if (!e.ctrlKey && !e.altKey && !e.metaKey && /^[1-9]$/.test(e.key) && !['INPUT', 'TEXTAREA'].includes(/** @type {HTMLElement} */ (e.target)?.tagName)) {
      const idx = parseInt(e.key) - 1;
      if ($layoutCabinets[idx]) {
        openCabinet($layoutCabinets[idx]);
      }
    }
  }

  onMount(() => {
    window.addEventListener('keydown', handleHomeKeydown);
    return () => window.removeEventListener('keydown', handleHomeKeydown);
  });

  // lastCabinetId используется для NavRail highlighting, но НЕ для auto-redirect.
  // Пользователь сам выбирает кабинет при запуске.
  loadRecentExports();
  checkUpdate();
  // Mandatory update checks are centralized in +layout.svelte (heartbeat + check_update)
</script>

{#if !$hasCompletedOnboarding}
  <OnboardingOverlay />
{/if}

<div class="home">
  <!-- ── Top Bar ── -->
  <header class="topbar">
    <div class="topbar-left">
      <AetherLogo />
      <div class="brand">
        <span class="brand-rosst">{getProductName($productType).toUpperCase()}</span>
      </div>
    </div>
    <div class="topbar-center">
      <DigitalClock />
      <span class="tz-label">МСК</span>
    </div>
    <nav class="topbar-right">
      {#if $isCreativeHub && $brands.length > 0}
        <BrandSelector />
      {/if}
      <button class="nav-link" title="Переключить тему" aria-label="Переключить тему" onclick={toggleTheme}>
        {#if $theme === 'dark'}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
        {:else}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <circle cx="12" cy="12" r="5"/>
            <line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
            <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
          </svg>
        {/if}
      </button>
      <a href="/settings" class="nav-link" title="Настройки" aria-label="Настройки">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </a>
    </nav>
  </header>

  {#if updateInfo && !updateInfo.mandatory && !updateDismissed}
    <div class="update-banner">
      <span>Доступна версия {updateInfo.version}</span>
      {#if updateInfo.release_notes}
        <span class="update-notes">{updateInfo.release_notes}</span>
      {/if}
      <div class="update-actions">
        <button class="update-download" onclick={triggerUpdate}>Обновить сейчас</button>
        <button class="update-dismiss" onclick={() => updateDismissed = true}>Позже</button>
      </div>
    </div>
  {/if}

  {#if licenseDaysRemaining !== null && licenseDaysRemaining <= 14 && !licenseBannerDismissed}
    <div class="license-banner" class:license-banner-red={licenseDaysRemaining < 3}>
      <span>
        {#if licenseDaysRemaining <= 0}
          Срок лицензии истёк
        {:else if licenseDaysRemaining === 1}
          Лицензия истекает завтра
        {:else}
          Лицензия истекает через {licenseDaysRemaining} {licenseDaysRemaining < 5 ? 'дня' : 'дней'}
        {/if}
      </span>
      <div class="license-banner-actions">
        <a href="/settings" class="license-banner-renew">Продлить</a>
        <button class="license-banner-dismiss" onclick={() => licenseBannerDismissed = true}>Закрыть</button>
      </div>
    </div>
  {/if}

  <!-- ── Main Content ── -->
  <main class="main">
    {#if loading}
      <div class="state-panel">
        <div class="spinner"></div>
        {#if vaultProgress}
          <p class="state-text">Загрузка кабинетов... ({vaultProgress.current}/{vaultProgress.total})</p>
          <p class="state-subtext">{vaultProgress.file}</p>
        {:else}
          <p class="state-text">Проверка лицензии...</p>
        {/if}
      </div>
      <SkeletonCard count={6} height="110px" />

    {:else if licenseError}
      <div class="state-panel glass-panel">
        <div class="state-icon">🔒</div>
        <h2 class="state-title">Лицензия не найдена</h2>
        <p class="state-desc">{licenseError}</p>
        <a href="/settings" class="btn-primary">Импортировать лицензию</a>
      </div>

    {:else if cabinets.length === 0}
      <div class="state-panel glass-panel">
        <div class="state-icon">📦</div>
        <h2 class="state-title">Нет доступных кабинетов</h2>
        <p class="state-desc">В вашей лицензии нет активных кабинетов</p>
      </div>

    {:else}
      <!-- Quick actions: только для 6+ кабинетов (tabs уже показывают навигацию для ≤5) -->
      {#if cabinets.length > 5}
        <div class="quick-actions">
          {#each cabinets.slice(0, 3) as cab (cab.id)}
            <button class="qa-card" onclick={() => openCabinet(cab)}>
              <span class="qa-icon">{cab.icon}</span>
              <span class="qa-label">{cab.name}</span>
              <span class="qa-desc">{cab.description?.split(',')[0] || ''}</span>
            </button>
          {/each}
          {#if $isCreativeHub && $brands.length > 0}
            <button class="qa-card" onclick={() => goto('/brands')}>
              <span class="qa-icon">🎨</span>
              <span class="qa-label">Бренды</span>
              <span class="qa-desc">{$activeBrand ? $activeBrand.name : 'Управление'}</span>
            </button>
          {/if}
        </div>
      {/if}

      {#if $isCreativeHub && $brands.length === 0}
        <div class="welcome-brand">
          <h3>Creative Hub</h3>
          <p>Создайте первый бренд для начала работы</p>
          <div class="welcome-input-row">
            <input
              type="text"
              class="welcome-input"
              placeholder="Имя бренда..."
              bind:value={newBrandName}
              onkeydown={(e) => e.key === 'Enter' && quickCreateBrand()}
              disabled={creatingBrand}
            />
            <button class="welcome-create-btn" onclick={quickCreateBrand} disabled={!newBrandName.trim() || creatingBrand}>
              {creatingBrand ? '...' : 'Создать'}
            </button>
          </div>
        </div>
      {/if}

      <div class="cabinets-section">
        <div class="section-header">
          <div>
            <h2 class="section-title">Рабочие пространства</h2>
            <p class="section-subtitle">{cabinets.length} кабинет{cabinets.length > 1 ? 'a' : ''} доступно</p>
          </div>
        </div>

        {#if openError}
          <div class="open-error">
            <span>{openError}</span>
            <button onclick={() => openError = null}>✕</button>
          </div>
        {/if}

        <div class="cabinets-grid">
          {#each cabinets as cabinet, i}
            <div class="card-wrapper" style="animation-delay: {i * 65}ms">
              <CabinetCard {cabinet} onClick={() => openCabinet(cabinet)} />
            </div>
          {/each}
        </div>

        {#if recentExports.length > 0}
          <div class="exports-section">
            <h3 class="exports-title">Последние экспорты</h3>
            {#if shareSuccess}
              <div class="share-success">{shareSuccess}</div>
            {/if}
            <div class="exports-list">
              {#each recentExports as [cabId, filename, cabName]}
                <div class="export-row">
                  <span class="export-cab">{cabName}</span>
                  <span class="export-file" title={filename}>{filename}</span>
                  <button
                    class="share-btn"
                    onclick={() => shareTarget = { cabinetId: cabId, filename }}
                    title="Отправить в другой кабинет"
                    aria-label="Отправить {filename} в другой кабинет"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                      <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
                      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
                    </svg>
                  </button>
                </div>
                {#if shareTarget?.cabinetId === cabId && shareTarget?.filename === filename}
                  <div class="share-targets">
                    {#each cabinets.filter(c => c.id !== cabId) as target}
                      <button
                        class="target-btn"
                        onclick={() => shareToInbox(cabId, filename, target.id)}
                      >
                        {target.icon} {target.name}
                      </button>
                    {/each}
                  </div>
                {/if}
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </main>
</div>

<style>
  .home {
    height: 100%;
    display: flex;
    flex-direction: column;
  }

  /* ── Top Bar ── */
  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 52px;
    padding: 0 28px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-glass);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    position: relative;
    flex-shrink: 0;
    z-index: 10;
  }

  .topbar::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 1px;
    background: linear-gradient(90deg,
      transparent 0%,
      rgba(46, 91, 255, 0.4) 30%,
      rgba(204, 255, 0, 0.3) 70%,
      transparent 100%
    );
  }

  .topbar-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .brand {
    display: flex;
    flex-direction: column;
    gap: 0px;
    line-height: 1;
  }

  .brand-rosst {
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: var(--text-primary);
    text-transform: uppercase;
  }


  .topbar-center {
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .tz-label {
    font-size: 10px;
    color: var(--text-muted);
    letter-spacing: 0.05em;
    font-weight: 500;
  }

  .topbar-right {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .nav-link {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    color: var(--text-muted);
    border-radius: var(--radius-sm);
    transition: all var(--transition-fast);
    text-decoration: none;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
  }

  .nav-link:hover {
    color: var(--text-primary);
    background: var(--bg-tertiary);
  }

  /* ── Main ── */
  .main {
    flex: 1;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 32px 28px;
    overflow-y: auto;
  }

  /* ── States ── */
  .state-panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 48px 40px;
    min-width: 320px;
    margin-top: 48px;
  }

  .glass-panel {
    background: var(--bg-glass);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: var(--glass-border);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-card);
  }

  .state-icon {
    font-size: 44px;
    margin-bottom: 16px;
    filter: grayscale(0.2);
  }

  .state-title {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 8px;
  }

  .state-desc {
    color: var(--text-secondary);
    font-size: 14px;
    margin-bottom: 24px;
    line-height: 1.5;
  }

  .state-text {
    color: var(--text-secondary);
    font-size: 14px;
    margin-top: 12px;
  }

  .state-subtext {
    color: var(--text-muted);
    font-size: 11.5px;
    margin-top: 4px;
    font-family: var(--font-mono);
  }

  .spinner {
    width: 36px;
    height: 36px;
    border: 2px solid var(--border);
    border-top: 2px solid var(--accent-primary);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  .btn-primary {
    display: inline-flex;
    align-items: center;
    padding: 10px 24px;
    border-radius: var(--radius-sm);
    font-size: 14px;
    font-weight: 500;
    text-decoration: none;
    background: var(--accent-primary);
    color: white;
    transition: all var(--transition);
  }

  .btn-primary:hover {
    background: var(--accent-hover);
    box-shadow: var(--shadow-glow);
    transform: translateY(-1px);
  }

  /* ── Cabinets Section ── */
  .quick-actions {
    display: flex;
    gap: 10px;
    margin-bottom: 24px;
  }

  .qa-card {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 16px 12px;
    background: var(--bg-glass);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    cursor: pointer;
    color: var(--text-secondary);
    transition: all 0.2s ease;
    text-align: center;
  }

  .qa-card:hover {
    border-color: var(--accent-primary);
    color: var(--text-primary);
    transform: translateY(-2px);
  }

  .qa-icon { font-size: 22px; }
  .qa-label { font-size: 13px; font-weight: 600; }
  .qa-desc { font-size: 10px; color: var(--text-muted); }

  .cabinets-section {
    width: 100%;
    max-width: 960px;
  }

  .section-header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    margin-bottom: 28px;
  }

  .section-title {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, var(--text-primary) 40%, rgba(46, 91, 255, 0.8) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .section-subtitle {
    color: var(--text-muted);
    font-size: 13px;
    margin-top: 3px;
  }

  .open-error {
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.25);
    border-radius: var(--radius-sm);
    padding: 10px 14px;
    margin-bottom: 20px;
    color: #FCA5A5;
    font-size: 13px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .open-error button {
    background: transparent;
    color: #FCA5A5;
    font-size: 14px;
    opacity: 0.7;
    border: none;
    cursor: pointer;
    padding: 0 4px;
    line-height: 1;
  }

  /* ── Bento Grid ── */
  .cabinets-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(241px, 1fr));
    gap: 12px;
  }

  .card-wrapper {
    animation: card-appear 0.45s cubic-bezier(0.4, 0, 0.2, 1) both;
  }

  /* ── Recent Exports ── */
  .exports-section {
    margin-top: 32px;
  }

  .exports-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-muted);
    margin-bottom: 12px;
    letter-spacing: 0.02em;
  }

  .exports-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .export-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 10px;
    border-radius: 6px;
    transition: background 0.15s ease;
  }

  .export-row:hover {
    background: var(--hover-bg);
  }

  .export-cab {
    font-size: 11px;
    color: var(--text-muted);
    flex-shrink: 0;
    width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .export-file {
    flex: 1;
    font-size: 12.5px;
    color: var(--text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .share-btn {
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid var(--border-subtle);
    border-radius: 5px;
    color: var(--text-muted);
    cursor: pointer;
    opacity: 0;
    transition: all 0.15s ease;
    flex-shrink: 0;
  }

  .export-row:hover .share-btn {
    opacity: 1;
  }

  .share-btn:hover {
    color: var(--accent-primary);
    background: rgba(46, 91, 255, 0.1);
    border-color: rgba(46, 91, 255, 0.3);
  }

  .share-targets {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 6px 10px 10px;
  }

  .target-btn {
    padding: 5px 10px;
    background: rgba(46, 91, 255, 0.08);
    color: var(--text-secondary);
    border: 1px solid rgba(46, 91, 255, 0.2);
    border-radius: 6px;
    font-size: 11.5px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .target-btn:hover {
    background: rgba(46, 91, 255, 0.18);
    color: var(--text-primary);
    border-color: rgba(46, 91, 255, 0.4);
  }

  /* ── Update Banner ── */
  .update-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 28px;
    background: linear-gradient(90deg, rgba(46, 91, 255, 0.12) 0%, rgba(204, 255, 0, 0.08) 100%);
    border-bottom: 1px solid rgba(46, 91, 255, 0.2);
    font-size: 13px;
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  .update-actions {
    display: flex;
    gap: 8px;
  }

  .update-download {
    padding: 4px 14px;
    background: var(--accent-primary);
    color: white;
    border: none;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .update-download:hover {
    filter: brightness(1.15);
  }

  .update-notes {
    font-size: 11px;
    color: var(--text-secondary);
    opacity: 0.8;
  }

  .update-dismiss {
    padding: 4px 10px;
    background: transparent;
    color: var(--text-muted);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 5px;
    font-size: 12px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .update-dismiss:hover {
    color: var(--text-secondary);
    border-color: rgba(255, 255, 255, 0.15);
  }

  .share-success {
    font-size: 12px;
    color: var(--success, #10B981);
    margin-bottom: 8px;
    padding: 5px 10px;
    background: rgba(16, 185, 129, 0.08);
    border-radius: 6px;
    border: 1px solid rgba(16, 185, 129, 0.2);
  }


  /* ── License Expiry Banner ── */
  .license-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 28px;
    background: linear-gradient(90deg, rgba(234, 179, 8, 0.15) 0%, rgba(234, 179, 8, 0.06) 100%);
    border-bottom: 1px solid rgba(234, 179, 8, 0.3);
    font-size: 13px;
    color: #FBBF24;
    flex-shrink: 0;
  }

  .license-banner-red {
    background: linear-gradient(90deg, rgba(239, 68, 68, 0.15) 0%, rgba(239, 68, 68, 0.06) 100%);
    border-bottom-color: rgba(239, 68, 68, 0.3);
    color: #FCA5A5;
  }

  .license-banner-actions {
    display: flex;
    gap: 8px;
  }

  .license-banner-renew {
    padding: 4px 14px;
    background: rgba(234, 179, 8, 0.2);
    color: #FBBF24;
    border: 1px solid rgba(234, 179, 8, 0.3);
    border-radius: 5px;
    font-size: 12px;
    font-weight: 500;
    text-decoration: none;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .license-banner-red .license-banner-renew {
    background: rgba(239, 68, 68, 0.2);
    color: #FCA5A5;
    border-color: rgba(239, 68, 68, 0.3);
  }

  .license-banner-renew:hover {
    filter: brightness(1.2);
  }

  .license-banner-dismiss {
    padding: 4px 10px;
    background: transparent;
    color: inherit;
    opacity: 0.6;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 5px;
    font-size: 12px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .license-banner-dismiss:hover {
    opacity: 1;
    border-color: rgba(255, 255, 255, 0.15);
  }

  .welcome-brand {
    background: linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.08));
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 12px;
    padding: 24px;
    text-align: center;
    margin-bottom: 16px;
  }
  .welcome-brand h3 { font-size: 1.1rem; font-weight: 600; color: var(--text-primary, #fff); margin: 0 0 6px; }
  .welcome-brand p { font-size: 0.85rem; color: var(--text-secondary, #aaa); margin: 0 0 16px; }
  .welcome-input-row { display: flex; gap: 8px; max-width: 360px; margin: 0 auto; }
  .welcome-input { flex: 1; padding: 8px 12px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; color: var(--text-primary, #fff); font-size: 0.9rem; outline: none; font-family: inherit; }
  .welcome-input:focus { border-color: #6366f1; }
  .welcome-create-btn { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; border: none; padding: 8px 20px; border-radius: 8px; cursor: pointer; font-weight: 500; font-size: 0.9rem; }
  .welcome-create-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  /* ── Dashboard Stats ── */
  .dash-stats {
    display: flex;
    gap: 12px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }
  .dash-card {
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: 14px 18px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 110px;
    flex: 1;
  }
  .dash-card--wide { flex: 2; }
  .dash-value {
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dash-label {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
</style>
