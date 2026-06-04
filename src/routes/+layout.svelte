<script>
  import '../app.css';
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { theme, updateRequired, layoutCabinets, activeCabinet, messages, navCollapsed, licenseError } from '$lib/store.js';
  import { initCreativeStore, productType } from '$lib/creative-store.js';
  import { toasts, dismiss } from '$lib/toast.js';
  import { onMount } from 'svelte';
  import UpdateBlockingOverlay from '$lib/components/UpdateBlockingOverlay.svelte';
  import Toast from '$lib/components/Toast.svelte';
  import CommandPalette from '$lib/components/CommandPalette.svelte';
  import NavRail from '$lib/components/NavRail.svelte';
  import GlossaryPanel from '$lib/components/GlossaryPanel.svelte';
  import IntroTutorial from '$lib/components/IntroTutorial.svelte';
  import { showGlossaryPanel, glossaryInitialTerm, showIntroTutorial } from '$lib/project-state.js';
  import { filterCabinetsByProduct, initCommandMeta } from '$lib/command-meta.js';
  import { initPsyData } from '$lib/psy.js';
  import { initClassifierData } from '$lib/chat-classifier.js';
  import { initOnboardingData } from '$lib/onboarding-config.js';
  // v2.0.1-rc2: i18n infrastructure bootstrap. Side-effect import - triggers
  // register() для locale dictionaries + init() с persisted locale.
  // Реальная migration существующих strings → к v2.2.0.
  import '$lib/i18n/index.js';
  let { children } = $props();

  let paletteOpen = $state(false);
  /** @type {any} */
  let _themesData = null;

  const filteredCabinets = $derived(filterCabinetsByProduct($layoutCabinets, $productType));

  /** Flex direction: column for tabs (≤5), row for sidebar (6+) */
  const shellDirection = $derived(
    filteredCabinets.length <= 5 ? 'column' : 'row'
  );

  /**
   * Handle cabinet selection from NavRail.
   * @param {{id: string, name: string, description: string, icon: string, color: string}} cabinet
   */
  async function handleCabinetSelect(cabinet) {
    const currentRoute = /** @type {any} */ ($page).route?.id;
    // If already on /cabinet, close current first
    if (currentRoute === '/cabinet' && $activeCabinet) {
      try { await invoke('close_cabinet', { cabinetId: $activeCabinet.id }); } catch { /* ok */ }
    }
    await invoke('open_cabinet', { cabinetId: cabinet.id });
    activeCabinet.set(cabinet);
    messages.set([]);
    if (currentRoute !== '/cabinet') {
      goto('/cabinet');
    }
  }

  /**
   * Apply theme CSS variable overrides from content pack.
   * @param {Record<string, Record<string, string>>} themes
   * @param {string} currentTheme
   */
  function applyThemeOverrides(themes, currentTheme) {
    const root = document.documentElement;
    // Clear all previously set overrides from any theme
    for (const themeVars of Object.values(themes)) {
      for (const prop of Object.keys(themeVars)) {
        root.style.removeProperty(prop);
      }
    }
    const overrides = themes[currentTheme];
    if (!overrides) return;
    for (const [prop, value] of Object.entries(overrides)) {
      root.style.setProperty(prop, value);
    }
  }

  const HEARTBEAT_INTERVAL = 4 * 60 * 60 * 1000; // 4 hours
  const APP_VERSION = '1.2.0';

  /** Compare semver strings: returns true if remote > current
   * @param {string} remote
   * @param {string} current
   */
  function isNewer(remote, current) {
    const r = remote.split('.').map(Number);
    const c = current.split('.').map(Number);
    for (let i = 0; i < Math.max(r.length, c.length); i++) {
      if ((r[i] || 0) > (c[i] || 0)) return true;
      if ((r[i] || 0) < (c[i] || 0)) return false;
    }
    return false;
  }

  onMount(() => {
    // ONBOARD-1 (2026-06-02): IntroTutorial (теория MMM) больше НЕ авто-стартует
    // на first-run - это справочный материал, не блокер. Первый прогон ведёт
    // практический FirstRunTour (pipeline); теорию юзер открывает по желанию
    // кнопкой «Что такое MMM?» на главной. Решение Антона 2026-06-02.

    // Command Palette: Ctrl+K / Cmd+K. v1.3.0 + Ctrl+G - glossary panel.
    /** @param {KeyboardEvent} e */
    function handleGlobalKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        paletteOpen = !paletteOpen;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'g') {
        // Audit fix v1.3.0: guard против modal stacking - не показывать
        // glossary если CommandPalette открыт (избегаем z-index overlap).
        if (paletteOpen) return;
        e.preventDefault();
        showGlossaryPanel.update((v) => !v);
      }
    }
    window.addEventListener('keydown', handleGlobalKey);

    // Apply saved theme on mount
    const unsub = theme.subscribe(t => {
      if (t === 'dark') {
        document.documentElement.removeAttribute('data-theme');
      } else {
        document.documentElement.setAttribute('data-theme', t);
      }
      if (_themesData) applyThemeOverrides(_themesData, t);
    });

    // Check for updates via full manifest (Supabase → GitHub Pages fallback)
    async function checkFullUpdate() {
      try {
        const info = /** @type {any} */ (await invoke('check_update'));
        if (info) {
          updateRequired.set({
            required: info.mandatory || false,
            url: info.download_url || null,
            version: info.version || null,
            notes: info.release_notes || null,
            checksum: info.checksum || null,
          });
        }
      } catch { /* update check failed, non-critical */ }
    }

    // Heartbeat timer - periodic server ping
    async function heartbeat() {
      try {
        const resp = /** @type {{status: string, content_version: string|null, app_min_version: string}} */ (await invoke('send_heartbeat'));
        // Check if app needs mandatory update
        if (resp.app_min_version && isNewer(resp.app_min_version, APP_VERSION)) {
          await checkFullUpdate();
        }
      } catch { /* heartbeat failed silently */ }
    }

    // Initialize product type, content packs, and cabinets in correct order.
    // Content packs + product type MUST be ready before cabinets are set,
    // because filterCabinetsByProduct uses non-reactive _products from the pack.
    (async () => {
      // 1. Product type + content packs in parallel (both needed before filtering)
      const [, cmdMeta, psyData, classifierData, onboardingData, themesData] =
        await Promise.all([
          initCreativeStore(),
          invoke('get_content_pack', { packName: 'command-meta-data.json' }).catch(() => null),
          invoke('get_content_pack', { packName: 'psy-data.json' }).catch(() => null),
          invoke('get_content_pack', { packName: 'classifier-data.json' }).catch(() => null),
          invoke('get_content_pack', { packName: 'onboarding-data.json' }).catch(() => null),
          invoke('get_content_pack', { packName: 'themes.json' }).catch(() => null),
        ]);

      try {
        if (cmdMeta) initCommandMeta(JSON.parse(/** @type {string} */ (cmdMeta)));
        if (psyData) initPsyData(JSON.parse(/** @type {string} */ (psyData)));
        if (classifierData) initClassifierData(JSON.parse(/** @type {string} */ (classifierData)));
        if (onboardingData) initOnboardingData(JSON.parse(/** @type {string} */ (onboardingData)));

        if (themesData) {
          _themesData = JSON.parse(/** @type {string} */ (themesData));
          applyThemeOverrides(_themesData, /** @type {any} */ (get(theme)));
        }
      } catch (e) {
        console.warn('Content packs not available, using defaults:', e);
      }

      // 2. NOW load cabinets - product type and _products are ready for filtering
      try {
        const cabs = /** @type {any[]} */ (await invoke('get_cabinets'));
        layoutCabinets.set(cabs);

        // 2.1. Clean start: clear inbox + exports for all cabinets ONCE on app launch
        // (not on every cabinet open - user may navigate between cabinets and settings)
        for (const cab of cabs) {
          invoke('clear_workspace_files', { cabinetId: cab.id }).catch(() => {});
        }
      } catch (e) {
        licenseError.set(String(e));
      }

      // 3. Heartbeat AFTER auth - activation record must exist first
      heartbeat();
    })();

    // Update check on app start (heartbeat moved inside async after get_cabinets)
    checkFullUpdate();
    const interval = setInterval(heartbeat, HEARTBEAT_INTERVAL);

    return () => {
      window.removeEventListener('keydown', handleGlobalKey);
      unsub();
      clearInterval(interval);
    };
  });
</script>

<UpdateBlockingOverlay />
<CommandPalette open={paletteOpen} onClose={() => paletteOpen = false} />

{#if $showGlossaryPanel}
  <GlossaryPanel
    initialTerm={$glossaryInitialTerm}
    onClose={() => { showGlossaryPanel.set(false); glossaryInitialTerm.set(null); }}
  />
{/if}

<!-- v1.3.2 audit: floating glossary FAB removed - выбивался из премиум-стилистики.
     Glossary остаётся доступен через (1) Ctrl+G keyboard shortcut, (2) Settings →
     «Открыть глоссарий» кнопка, (3) tooltip ?-icon рядом с каждым specialized
     термином в pipeline (in-context, не глобальный pictograph). -->

{#if $showIntroTutorial}
  <IntroTutorial
    onComplete={() => {
      showIntroTutorial.set(false);
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('aurora-intro-completed', '1');
      }
    }}
    onSkip={() => {
      showIntroTutorial.set(false);
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('aurora-intro-completed', '1');
      }
    }}
  />
{/if}

<div class="app-shell" style="flex-direction: {shellDirection}">
  <!-- NavRail: показывать только внутри кабинета (не на Home, Settings и т.п.) -->
  {#if $activeCabinet}
    <NavRail
      cabinets={filteredCabinets}
      activeCabinetId={$activeCabinet?.id}
      onSelect={handleCabinetSelect}
      collapsed={$navCollapsed}
      onToggleCollapse={() => navCollapsed.update(v => !v)}
    />
  {/if}
  <div class="main-content">
    {#key $page.url.pathname}
      <div class="page-transition">
        {@render children()}
      </div>
    {/key}
  </div>
</div>

{#if $toasts.length > 0}
  <div class="toast-container">
    {#each $toasts as t (t.id)}
      <Toast message={t.message} type={t.type} duration={t.duration} onClose={() => dismiss(t.id)} />
    {/each}
  </div>
{/if}

<style>
  /* v1.3.2 audit: .glossary-fab removed (см. template comment). */

  .toast-container {
    position: fixed;
    bottom: 20px;
    right: 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    z-index: 10000;
    pointer-events: auto;
  }
  .app-shell {
    height: 100vh;
    display: flex;
    /* flex-direction set inline via shellDirection: column (tabs) or row (sidebar) */
    overflow: hidden;
  }

  .main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 0;
  }

  .page-transition {
    display: contents;
    animation: pageFadeIn 0.15s ease-out;
  }

  @keyframes pageFadeIn {
    from { opacity: 0.6; }
    to { opacity: 1; }
  }

  /* v2.1.0 п.5.6: skip fade-in page transition */
  @media (prefers-reduced-motion: reduce) {
    .page-transition {
      animation: none;
      opacity: 1;
    }
  }
</style>
