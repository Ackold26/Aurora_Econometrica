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
    background: var(--hover-bg); border: 1px solid var(--border);
    color: var(--text-secondary, #aaa); padding: 4px 10px; border-radius: 6px;
    cursor: pointer; font-size: 0.8rem; font-family: inherit;
  }
  .selector-trigger:hover { background: var(--accent-glow); color: var(--text-primary); }

  .selector-chevron { transition: transform 0.15s; }
  .selector-chevron.open { transform: rotate(180deg); }

  .selector-dropdown {
    position: absolute; top: calc(100% + 4px); right: 0;
    background: var(--bg-surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 4px; min-width: 180px; max-height: 240px; overflow-y: auto;
    box-shadow: var(--shadow-glow); z-index: 100;
  }

  .selector-item {
    display: flex; align-items: center; justify-content: space-between;
    width: 100%; padding: 8px 12px; border: none; background: none;
    color: var(--text-secondary, #aaa); cursor: pointer; border-radius: 6px;
    font-size: 0.85rem; font-family: inherit; text-align: left;
  }
  .selector-item:hover { background: var(--hover-bg); color: var(--text-primary); }
  .selector-item.active { color: var(--accent-text-light); }
  .item-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
