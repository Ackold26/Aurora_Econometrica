<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { activeCabinet, messages, errorMessage, theme, toggleTheme, updateRequired, layoutCabinets, cabinetsLoaded, lastCabinetId, licenseError as licenseErrorStore } from '$lib/store.js';
  import { isCreativeHub, isEconometrica, activeBrand, brands, refreshBrands, setActiveBrand, productType } from '$lib/creative-store.js';
  import { toast } from '$lib/toast.js';
  import CabinetCard from '$lib/components/CabinetCard.svelte';
  import BrandSelector from '$lib/components/BrandSelector.svelte';
  import AetherLogo from '$lib/components/AetherLogo.svelte';
  import { activeProject, activeProjectId, resetForNewAnalysis, PIPELINE_STEPS, showIntroTutorial } from '$lib/project-state.js';
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
  import SessionTimer from '$lib/components/SessionTimer.svelte';

  import { filterCabinetsByProduct, getProductName } from '$lib/command-meta.js';
  import { LockKeyhole, Package } from 'lucide-svelte';
  // Cabinets filtered by product type (Legal=3, Creative=5, Agency=all)
  const cabinets = $derived(filterCabinetsByProduct($layoutCabinets, $productType));
  // Индикатор загрузки опирается на флаг завершения, НЕ на количество кабинетов:
  // в локальной редакции Econometrica список advisor-кабинетов пуст по дизайну.
  let loading = $derived(!$cabinetsLoaded && !$licenseErrorStore);
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
  // Plain let (NOT $state) - invisible to Svelte reactivity, prevents $effect re-trigger
  let autoRedirectInProgress = false;
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
      autoRedirectInProgress = false; // allow retry
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
    // F1 (2026-07-02): гидрировать активный проект в стор на холодном старте,
    // чтобы показать «Продолжить проект →». Backend знает активный (active_project.json),
    // но фронт-стор пуст до захода в ProjectSelector/pipeline. Ставим ТОЛЬКО стор
    // (id + info); pipeline data-сторы гидрирует /pipeline через resetPipeline (LOAD-1).
    (async () => {
      try {
        const id = await invoke('project_get_active');
        if (id) {
          const info = await invoke('project_get', { projectId: id });
          activeProjectId.set(id);
          activeProject.set(info);
        }
      } catch (e) {
        // нет активного проекта или ошибка — просто без кнопки «Продолжить»
      }
    })();
    return () => window.removeEventListener('keydown', handleHomeKeydown);
  });

  let enteringCabinet = $state(false);

  function dismissPipeline() {
    enteringCabinet = true;
    if (cabinets.length >= 1) {
      openCabinet(cabinets[0]);
    }
  }

  loadRecentExports();
  checkUpdate();
  // Mandatory update checks are centralized in +layout.svelte (heartbeat + check_update)
</script>

<!-- ONBOARD-1 (2026-06-04): авто-старт OnboardingOverlay убран — дублировал welcome
     FirstRunTour (pipeline, практический тур) + теорию IntroTutorial (opt-in). FirstRunTour
     покрывает первый запуск, WhyThisStep — контекст шагов. Компонент OnboardingOverlay.svelte
     сохранён в кодовой базе для возможного ручного вызова. См. TEST_FINDINGS_2026-06-04 ONBOARD-1. -->

{#if enteringCabinet}
  <div class="home">
    <div style="display: flex; align-items: center; justify-content: center; height: 100vh;">
      <div class="spinner"></div>
      <p style="margin-left: 12px; opacity: 0.6; font-size: 13px;">Открытие рабочей области...</p>
    </div>
  </div>
{:else}
<div class="home">
  <!-- ── Top Bar ── -->
  <header class="topbar">
    <div class="topbar-left">
      <img src="/logo-horizon.png" alt="Aurora AI" class="topbar-logo" />
      <div class="brand">
        <span class="brand-rosst">ECONOMETRICA</span>
        <span class="brand-sub">MMM Optimizer</span>
      </div>
    </div>
    <div class="topbar-center">
      <SessionTimer />
    </div>
    <nav class="topbar-right">
      {#if $isCreativeHub && $brands.length > 0}
        <BrandSelector />
      {/if}
      <button class="nav-link" title="Переключить тему" aria-label="Переключить тему" onclick={toggleTheme}>
        {#if $theme === 'dark'}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
        {:else if $theme === 'light'}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <circle cx="12" cy="12" r="5"/>
            <line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
            <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
          </svg>
        {:else}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 8h1a4 4 0 0 1 0 8h-1"/>
            <path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4z"/>
            <line x1="6" y1="1" x2="6" y2="4"/>
            <line x1="10" y1="1" x2="10" y2="4"/>
            <line x1="14" y1="1" x2="14" y2="4"/>
          </svg>
        {/if}
      </button>
      <a href="/settings" class="nav-link" title="Настройки" aria-label="Настройки">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </a>
      <button
        type="button"
        class="nav-link"
        title="Справочный центр"
        aria-label="Справочный центр"
        onclick={async () => { try { await invoke('open_help', { cabinetId: 'index' }); } catch (e) { console.error(e); } }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="12" cy="12" r="10"/>
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
      </button>
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
          <p class="state-text">Загрузка данных... ({vaultProgress.current}/{vaultProgress.total})</p>
          <p class="state-subtext">{vaultProgress.file}</p>
        {:else}
          <p class="state-text">Проверка лицензии...</p>
        {/if}
      </div>

    {:else if $licenseErrorStore}
      <div class="state-panel glass-panel">
        <div class="state-icon"><LockKeyhole size={28} strokeWidth={1.5} /></div>
        <h2 class="state-title">Лицензия не найдена</h2>
        <p class="state-desc">{$licenseErrorStore}</p>
        <a href="/settings" class="btn-primary">Импортировать лицензию</a>
      </div>

    {:else if cabinets.length === 0 && !$isEconometrica}
      <div class="state-panel glass-panel">
        <div class="state-icon"><Package size={28} strokeWidth={1.5} /></div>
        <h2 class="state-title">Рабочая область недоступна</h2>
        <p class="state-desc">В вашей лицензии не активирована Econometrica. Обратитесь в поддержку.</p>
      </div>

    {:else}
      <div class="pipeline-stage">
        <img
          src="/logo-hero.png"
          alt="Aurora AI"
          class="hero-logo"
        />
        <div class="pipeline-promo pipeline-promo-rich">
          <div class="promo-head">
            <div class="promo-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 3v18h18"/><path d="M7 16l4-5 4 3 4-7"/>
              </svg>
            </div>
            <div class="promo-head-text">
              <h2 class="promo-title">MMM БЮДЖЕТИРОВАНИЕ И ОПТИМИЗАЦИЯ</h2>
              <span class="promo-tagline">Определение размера бюджета и его распределения по каналам – на данных, а не на интуиции</span>
            </div>
          </div>

          <div class="promo-sections">
            <div class="promo-section">
              <h3>Когда использовать</h3>
              <p>Когда размер рекламного бюджета и его распределение между каналами нужно обосновать расчётом на данных, а не экспертной оценкой.</p>
            </div>
            <div class="promo-section">
              <h3>Что получите</h3>
              <p>Обоснованный размер бюджета под цель по продажам, затем – оптимальное распределение по каналам, декомпозицию вклада каждого канала и прогноз результата.</p>
            </div>
            <div class="promo-section promo-section-typical">
              <h3>Типичные задачи</h3>
              <p>Определить оптимальный размер бюджета кампании, распределить его между каналами, оценить окупаемость и просчитать сценарии «что если».</p>
            </div>
          </div>

          <p class="promo-process">
            <span class="promo-process-label">Процесс</span>
            <span class="pipeline-steps-line">{PIPELINE_STEPS.map(s => s.labelRu).join(' → ')}</span>
          </p>

          <div class="pipeline-promo-actions">
            {#if $activeProject}
              <button
                class="pipeline-promo-btn"
                onclick={() => goto('/pipeline')}
                title={$activeProject.name}
              >
                Продолжить проект →
              </button>
            {/if}
            <button
              class="pipeline-promo-btn"
              class:pipeline-promo-secondary={$activeProject}
              onclick={() => { resetForNewAnalysis(); goto('/pipeline?new=1'); }}
            >
              Новый проект
            </button>
            <!-- «Причинность →» СКРЫТА с главной 2026-07-02 (решение Антона): модуль
                 Sprint 3 Pharma Causal экспериментальный (v1.0.14-rc, был тупик навигации,
                 не локализован). Вернуть после доработки (навигация + локализация RU +
                 валидация на реальных данных). Роут /causal остаётся рабочим.
            {#if $activeProject}
              <button
                class="pipeline-promo-btn pipeline-promo-secondary"
                onclick={() => goto('/causal')}
                title="Sprint 3 Pharma Causal - DiD / SCM / Causal Forest"
              >
                Причинность →
              </button>
            {/if}
            -->

          </div>
          <!-- ONBOARD-1: теория MMM теперь по желанию (opt-in), не авто-старт. -->
          <button type="button" class="pipeline-promo-learn" onclick={() => showIntroTutorial.set(true)}>
            Что такое MMM? — короткий разбор за 5 минут
          </button>
        </div>
      </div>
    {/if}
  </main>
</div>
{/if}

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
    height: 100px;
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
    background: var(--gradient-accent-line);
  }

  .topbar-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .brand {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 5px;
    line-height: 1;
  }

  .topbar-logo {
    height: 87px;
    width: auto;
  }

  .brand-rosst {
    /* Чип названия продукта (Aurora design SSOT §2, эталон DocMaster) —
       пилюля accent-цветом, адаптируется к теме (blue/navy/coffee). */
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--accent-primary);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 40%, transparent);
    background: color-mix(in srgb, var(--accent-primary) 8%, transparent);
    padding: 4px 11px;
    border-radius: 999px;
  }

  .brand-sub {
    /* Вторичный чип продукта — приглушённая капсула под основным «ECONOMETRICA». */
    font-size: 9.5px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-secondary);
    border: 1px solid var(--border);
    background: color-mix(in srgb, var(--text-primary) 5%, transparent);
    padding: 3px 9px;
    border-radius: 999px;
  }


  .topbar-center {
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 6px;
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
    flex-direction: column;
    align-items: center;
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
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-elevation-1);
  }

  .state-icon {
    font-size: 44px;
    margin-bottom: 16px;
    filter: grayscale(0.2);
  }

  .state-title {
    font-size: 18px;
    font-weight: var(--font-weight-heading);
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
    color: var(--text-on-accent, #fff);
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
    width: 100%;
    max-width: 960px;
  }

  .qa-card {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 16px 12px;
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    border: 1px solid var(--hover-bg);
    border-radius: var(--radius-card);
    cursor: pointer;
    color: var(--text-secondary);
    transition: var(--hover-timing);
    text-align: center;
  }

  .qa-card:hover {
    border-color: var(--accent-primary);
    color: var(--text-primary);
    transform: var(--hover-transform);
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
    background: linear-gradient(135deg, var(--text-primary) 40%, var(--accent-primary) 100%);
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
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
    border-radius: var(--radius-sm);
    padding: 10px 14px;
    margin-bottom: 20px;
    color: var(--danger-text-light);
    font-size: 13px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .open-error button {
    background: transparent;
    color: var(--danger-text-light);
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
    border-radius: var(--radius-btn);
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
    background: var(--accent-glow);
    border-color: var(--accent-glow-strong);
  }

  .share-targets {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 6px 10px 10px;
  }

  .target-btn {
    padding: 5px 10px;
    background: var(--accent-glow);
    color: var(--text-secondary);
    border: 1px solid var(--accent-glow-strong);
    border-radius: 6px;
    font-size: 11.5px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .target-btn:hover {
    background: var(--accent-glow-strong);
    color: var(--text-primary);
    border-color: var(--border-active);
  }

  /* ── Update Banner ── */
  .update-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 28px;
    background: linear-gradient(90deg, color-mix(in srgb, var(--accent-primary) 12%, transparent) 0%, color-mix(in srgb, var(--accent-secondary) 8%, transparent) 100%);
    border-bottom: 1px solid var(--accent-glow-strong);
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
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-btn);
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
    border: 1px solid var(--border);
    border-radius: var(--radius-btn);
    font-size: 12px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .update-dismiss:hover {
    color: var(--text-secondary);
    border-color: var(--border);
  }

  .share-success {
    font-size: 12px;
    color: var(--success, #10B981);
    margin-bottom: 8px;
    padding: 5px 10px;
    background: color-mix(in srgb, var(--success) 8%, transparent);
    border-radius: 6px;
    border: 1px solid color-mix(in srgb, var(--success) 20%, transparent);
  }


  /* ── License Expiry Banner ── */
  .license-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 28px;
    background: linear-gradient(90deg, color-mix(in srgb, var(--warning) 15%, transparent) 0%, color-mix(in srgb, var(--warning) 6%, transparent) 100%);
    border-bottom: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
    font-size: 13px;
    color: var(--warning);
    flex-shrink: 0;
  }

  .license-banner-red {
    background: linear-gradient(90deg, color-mix(in srgb, var(--danger) 15%, transparent) 0%, color-mix(in srgb, var(--danger) 6%, transparent) 100%);
    border-bottom-color: color-mix(in srgb, var(--danger) 30%, transparent);
    color: var(--danger-text-light);
  }

  .license-banner-actions {
    display: flex;
    gap: 8px;
  }

  .license-banner-renew {
    padding: 4px 14px;
    background: color-mix(in srgb, var(--warning) 20%, transparent);
    color: var(--warning);
    border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
    border-radius: 5px;
    font-size: 12px;
    font-weight: 500;
    text-decoration: none;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .license-banner-red .license-banner-renew {
    background: color-mix(in srgb, var(--danger) 20%, transparent);
    color: var(--danger-text-light);
    border-color: color-mix(in srgb, var(--danger) 30%, transparent);
  }

  .license-banner-renew:hover {
    filter: brightness(1.2);
  }

  .license-banner-dismiss {
    padding: 4px 10px;
    background: transparent;
    color: inherit;
    opacity: 0.6;
    border: 1px solid var(--border);
    border-radius: 5px;
    font-size: 12px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .license-banner-dismiss:hover {
    opacity: 1;
    border-color: var(--border);
  }

  .welcome-brand {
    background: linear-gradient(135deg, color-mix(in srgb, var(--brand-gradient-start) 10%, transparent), color-mix(in srgb, var(--brand-gradient-end) 8%, transparent));
    border: 1px solid color-mix(in srgb, var(--brand-gradient-start) 20%, transparent);
    border-radius: 12px;
    padding: 24px;
    text-align: center;
    margin-bottom: 16px;
  }
  .welcome-brand h3 { font-size: 1.1rem; font-weight: 600; color: var(--text-primary, #fff); margin: 0 0 6px; }
  .welcome-brand p { font-size: 0.85rem; color: var(--text-secondary, #aaa); margin: 0 0 16px; }
  .welcome-input-row { display: flex; gap: 8px; max-width: 360px; margin: 0 auto; }
  .welcome-input { flex: 1; padding: 8px 12px; background: var(--hover-bg); border: 1px solid var(--border); border-radius: var(--radius-input); color: var(--text-primary, #fff); font-size: 0.9rem; outline: none; font-family: inherit; }
  .welcome-input:focus { border-color: var(--brand-gradient-start); }
  .welcome-create-btn { background: linear-gradient(135deg, var(--brand-gradient-start), var(--brand-gradient-end)); color: var(--text-on-accent, #fff); border: none; padding: 8px 20px; border-radius: var(--radius-btn); cursor: pointer; font-weight: 500; font-size: 0.9rem; }
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

  /* Pipeline Promo Panel */
  .pipeline-stage {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 32px;
    width: 100%;
    max-width: 900px;
  }

  .hero-logo {
    width: 180px;
    max-width: 60%;
    height: auto;
    object-fit: contain;
    user-select: none;
    pointer-events: none;
    filter: drop-shadow(0 4px 16px color-mix(in srgb, var(--accent-primary) 25%, transparent));
  }

  .pipeline-promo {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 16px;
    padding: 28px 32px;
    background: color-mix(in srgb, var(--accent-primary) 6%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-radius: 16px;
    width: 100%;
    max-width: 900px;
    text-align: left;
    animation: promoFadeIn 0.3s ease-out;
  }
  @keyframes promoFadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

  /* ── Rich promo (эталон облика — DocMaster CabinetCard) ── */
  .promo-head {
    display: grid;
    grid-template-columns: 46px 1fr;
    column-gap: 16px;
    align-items: center;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--hover-bg);
  }
  .promo-icon { width: 46px; height: 46px; color: var(--accent-primary); flex-shrink: 0; }
  .promo-icon svg { width: 100%; height: 100%; }
  .promo-head-text { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .promo-title {
    font-size: 19px;
    font-weight: var(--font-weight-heading, 700);
    letter-spacing: -0.01em;
    color: var(--text-primary);
    margin: 0;
    line-height: 1.15;
  }
  .promo-tagline { font-size: 12px; color: var(--text-secondary); line-height: 1.35; }

  .promo-sections {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 22px;
  }
  .promo-section { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .promo-section h3 {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin: 0;
  }
  .promo-section p { font-size: 12.5px; color: var(--text-secondary); line-height: 1.5; margin: 0; }
  .promo-section-typical p { font-style: italic; color: var(--text-muted); }
  @media (max-width: 920px) {
    .promo-sections { grid-template-columns: 1fr; gap: 14px; }
  }

  .promo-process {
    display: flex;
    justify-content: center;
    align-items: baseline;
    gap: 8px;
    margin: 18px 0 0;
    font-size: 12px;
    color: var(--text-secondary);
    flex-wrap: wrap;
  }
  .promo-process-label {
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-size: 10px;
    font-weight: 700;
    color: var(--text-muted);
  }
  .pipeline-steps-line {
    display: inline-block;
    white-space: nowrap;
    color: var(--text-primary);
    font-weight: 500;
  }
  .pipeline-promo-actions { display: flex; justify-content: center; flex-wrap: wrap; gap: 12px; margin-top: 4px; }
  .pipeline-promo-learn {
    align-self: center;
    margin-top: 12px;
    padding: 0;
    background: none;
    border: none;
    font-size: 12px;
    color: var(--text-muted, #94a3b8);
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 3px;
    transition: color 0.15s ease;
  }
  .pipeline-promo-learn:hover { color: var(--accent, #3b82f6); }
  /* Action buttons - same size, shape, font-weight; differ only by color */
  .pipeline-promo-btn {
    padding: 11px 28px;
    font-size: 13.5px;
    font-weight: 600;
    border-radius: 9px;
    border: 1px solid transparent;
    cursor: pointer;
    transition: all 0.15s;
    font-family: inherit;
    line-height: 1.2;
    white-space: nowrap;
    letter-spacing: -0.005em;
  }

  /* Primary - solid accent */
  .pipeline-promo-btn {
    background: var(--accent, #3b82f6);
    color: white;
  }
  .pipeline-promo-btn:hover {
    background: #2563eb;
  }

  /* Secondary - outline accent (for "Новый проект" when active project exists) */
  .pipeline-promo-btn.pipeline-promo-secondary {
    background: color-mix(in srgb, var(--accent-primary) 14%, transparent);
    color: var(--accent-primary);
    border-color: color-mix(in srgb, var(--accent-primary) 45%, transparent);
  }
  .pipeline-promo-btn.pipeline-promo-secondary:hover {
    background: color-mix(in srgb, var(--accent-primary) 24%, transparent);
    border-color: var(--accent-primary);
  }

  /* v2.1.0 п.5.6: static spinner and skip card-appear entrance */
  @media (prefers-reduced-motion: reduce) {
    .spinner {
      border-color: var(--accent-primary);
    }
    .cabinet-card {
      animation: none;
      opacity: 1;
      transform: none;
    }
  }
</style>
