<script>
  import { brands, activeBrand, activeBrandId, setActiveBrand } from '$lib/creative-store.js';
  import { toast } from '$lib/toast.js';

  let open = $state(false);

  /** @param {string} brandId */
  async function selectBrand(brandId) {
    try {
      await setActiveBrand(brandId);
      open = false;
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    }
  }

  /** @param {MouseEvent} e */
  function handleClickOutside(e) {
    if (open && !(/** @type {HTMLElement} */ (e.target)).closest('.brand-selector')) {
      open = false;
    }
  }
</script>

<svelte:window onclick={handleClickOutside} />

<div class="brand-selector">
  <button class="selector-trigger" onclick={(e) => { e.stopPropagation(); open = !open; }}>
    <span class="selector-label">{$activeBrand?.name || 'Нет бренда'}</span>
    <svg class="selector-chevron" class:open width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
  </button>

  {#if open && $brands.length > 0}
    <div class="selector-dropdown">
      {#each $brands as b (b.brand_id)}
        <button
          class="selector-item"
          class:active={$activeBrandId === b.brand_id}
          onclick={(e) => { e.stopPropagation(); selectBrand(b.brand_id); }}
        >
          <span class="item-name">{b.name}</span>
          {#if $activeBrandId === b.brand_id}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>
          {/if}
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .brand-selector { position: relative; }

  .selector-trigger {
    display: flex; align-items: center; gap: 4px;
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
    color: var(--text-secondary, #aaa); padding: 4px 10px; border-radius: 6px;
    cursor: pointer; font-size: 0.8rem; font-family: inherit;
  }
  .selector-trigger:hover { background: rgba(255,255,255,0.08); color: var(--text-primary, #fff); }

  .selector-chevron { transition: transform 0.15s; }
  .selector-chevron.open { transform: rotate(180deg); }

  .selector-dropdown {
    position: absolute; top: calc(100% + 4px); right: 0;
    background: var(--bg-surface, #1a1a2e); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px; padding: 4px; min-width: 180px; max-height: 240px; overflow-y: auto;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4); z-index: 100;
  }

  .selector-item {
    display: flex; align-items: center; justify-content: space-between;
    width: 100%; padding: 8px 12px; border: none; background: none;
    color: var(--text-secondary, #aaa); cursor: pointer; border-radius: 6px;
    font-size: 0.85rem; font-family: inherit; text-align: left;
  }
  .selector-item:hover { background: rgba(255,255,255,0.06); color: var(--text-primary, #fff); }
  .selector-item.active { color: #818cf8; }
  .item-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
