<script>
  import '../app.css';
  import { invoke } from '@tauri-apps/api/core';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { theme, updateRequired, layoutCabinets, activeCabinet, messages, navCollapsed } from '$lib/store.js';
  import { initCreativeStore, productType } from '$lib/creative-store.js';
  import { toasts, dismiss } from '$lib/toast.js';
  import { onMount } from 'svelte';
  import UpdateBlockingOverlay from '$lib/components/UpdateBlockingOverlay.svelte';
  import Toast from '$lib/components/Toast.svelte';
  import CommandPalette from '$lib/components/CommandPalette.svelte';
  import NavRail from '$lib/components/NavRail.svelte';
  let { children } = $props();

  let paletteOpen = $state(false);

  import { filterCabinetsByProduct } from '$lib/command-meta.js';

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

  const HEARTBEAT_INTERVAL = 4 * 60 * 60 * 1000; // 4 hours
  const APP_VERSION = '0.4.1';

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
    // Command Palette: Ctrl+K / Cmd+K
    /** @param {KeyboardEvent} e */
    function handleGlobalKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        paletteOpen = !paletteOpen;
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

    // Heartbeat timer — periodic server ping
    async function heartbeat() {
      try {
        const resp = /** @type {{status: string, content_version: string|null, app_min_version: string}} */ (await invoke('send_heartbeat'));
        // Check if app needs mandatory update
        if (resp.app_min_version && isNewer(resp.app_min_version, APP_VERSION)) {
          await checkFullUpdate();
        }
      } catch { /* heartbeat failed silently */ }
    }

    // Initialize Creative Hub store (product type, brands, services)
    (async () => { await initCreativeStore(); })();

    // Load cabinets once for NavRail (shared across all pages via store)
    (async () => {
      try {
        const cabs = /** @type {any[]} */ (await invoke('get_cabinets'));
        layoutCabinets.set(cabs);
      } catch { /* license error — Home page handles this */ }
    })();

    // Immediate update check on app start + heartbeat
    checkFullUpdate();
    heartbeat();
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
</style>
