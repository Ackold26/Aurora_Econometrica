/**
 * Stores for Creative Hub features (Workflow, Campaign, Data Chat).
 * Separated from main store.js to avoid polluting non-Creative-Hub products.
 * Includes product awareness: detects product type, manages brands, RAG/Parser health.
 */
import { writable, derived, get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import { createPersistentStore } from '$lib/store.js';

// ── Product Awareness ────────────────────────────────────

/** @type {import('svelte/store').Writable<string>} */
export const productType = writable('agency');

/** @type {import('svelte/store').Readable<boolean>} */
export const isCreativeHub = derived(productType, $p => $p === 'creative-hub');

/** MMM-продукт Econometrica (обе редакции — локальная и облачная). Не зависит от наличия
 * advisor-кабинета econometrist, который локальная редакция скрывает.
 * @type {import('svelte/store').Readable<boolean>} */
export const isEconometrica = derived(productType, $p => $p === 'econometrica');

/** @type {import('svelte/store').Writable<boolean>} */
export const ragAvailable = writable(false);

/** @type {import('svelte/store').Writable<boolean>} */
export const parserAvailable = writable(false);

// ── Brand State ──────────────────────────────────────────

/**
 * @typedef {{brand_id: string, name: string, industry: string, description: string, created_at: string}} Brand
 */

/** @type {import('svelte/store').Writable<Brand[]>} */
export const brands = writable(/** @type {Brand[]} */ ([]));

/** @type {import('svelte/store').Writable<string|null>} */
export const activeBrandId = createPersistentStore('ai-agency-active-brand-id', null);

/** @type {import('svelte/store').Readable<Brand|null>} */
export const activeBrand = derived(
  [brands, activeBrandId],
  ([$brands, $id]) => $brands.find(b => b.brand_id === $id) || null
);

// ── Workflow State ───────────────────────────────────────

/** @type {import('svelte/store').Writable<any>} */
export const activeWorkflow = createPersistentStore('ai-agency-active-workflow', null);

/** @type {import('svelte/store').Writable<{id: string, status: string, steps: any}|null>} */
export const workflowExecution = writable(null);

/** @type {import('svelte/store').Writable<'simple'|'canvas'>} */
export const workflowView = createPersistentStore('ai-agency-workflow-view', 'simple');

// ── Initialization ───────────────────────────────────────

/**
 * Initialize product awareness - call once on app mount.
 * Detects product type, loads brands, checks RAG/Parser health.
 */
export async function initCreativeStore() {
  try {
    const type = /** @type {string} */ (await invoke('get_product_type'));
    productType.set(type);
  } catch {
    productType.set('agency');
  }

  // Load brands (filesystem-first - always works)
  await refreshBrands();

  // Load active brand from backend
  try {
    const resp = /** @type {{active_brand: string|null}} */ (await invoke('brand_get_active'));
    if (resp.active_brand) {
      activeBrandId.set(resp.active_brand);
    }
  } catch { /* keep localStorage value */ }

  // Non-Creative-Hub: ensure default brand exists silently
  if (get(productType) !== 'creative-hub') {
    try { await invoke('ensure_default_brand'); } catch { /* ignore */ }
  } else {
    // Creative Hub: check RAG/Parser health
    checkServices();
  }
}

/** Check RAG and Parser health (non-blocking). */
export async function checkServices() {
  try {
    const rag = /** @type {boolean} */ (await invoke('brand_health'));
    ragAvailable.set(rag);
  } catch {
    ragAvailable.set(false);
  }

  try {
    const parser = /** @type {boolean} */ (await invoke('parser_health'));
    parserAvailable.set(parser);
  } catch {
    parserAvailable.set(false);
  }
}

/**
 * Activate a brand.
 * @param {string} brandId
 */
export async function setActiveBrand(brandId) {
  await invoke('brand_activate', { brandId });
  activeBrandId.set(brandId);
}

/**
 * Update brand profile.
 * @param {string} brandId
 * @param {string} name
 * @param {string} industry
 * @param {string} description
 * @returns {Promise<Brand>}
 */
export async function updateBrand(brandId, name, industry, description) {
  const updated = /** @type {Brand} */ (
    await invoke('brand_update', { brandId, name, industry, description })
  );
  await refreshBrands();
  return updated;
}

/**
 * Delete a brand and clear active if needed.
 * @param {string} brandId
 */
export async function deleteBrand(brandId) {
  await invoke('brand_delete', { brandId });
  if (get(activeBrandId) === brandId) {
    activeBrandId.set(null);
  }
  await refreshBrands();
}

/**
 * Fetch recent pipeline statuses.
 * @returns {Promise<any[]>}
 */
export async function fetchRecentPipelines() {
  try {
    const brandId = get(activeBrandId) || '';
    const list = /** @type {any[]} */ (await invoke('campaign_list', { brandId }));
    return list
      .filter(c => c.campaign_type === 'workflow' && c.status)
      .slice(0, 5);
  } catch {
    return [];
  }
}

/** @type {import('svelte/store').Writable<any[]>} */
export const recentPipelines = writable([]);

/**
 * Refresh brands list from filesystem.
 */
export async function refreshBrands() {
  try {
    const list = /** @type {Brand[]} */ (await invoke('brand_list'));
    brands.set(list);
  } catch {
    // keep current state
  }
}
