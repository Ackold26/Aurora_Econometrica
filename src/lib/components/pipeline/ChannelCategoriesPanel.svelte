<script>
  /**
   * ChannelCategoriesPanel - Trust Level 3 (Brand vs Performance Split, v1.1.0).
   *
   * Categorize media каналы на:
   *   🎯 Brand (синий) - TV/TRPs/OOH/Радио → long-decay (effective half-life ~12 wk)
   *   📊 Performance (зелёный) - Digital/Search/Social → short-decay (~1.3 wk)
   *   ⚪ Mixed (серый) - ambiguous (Спецпроект/OLV/cross-channel) → single-prior fallback
   *
   * Auto-suggest backend endpoint /utils/auto_suggest_categories на mount.
   * Manual override через popup. Persistence через project_update.
   *
   * Identifiability constraint: backend в modeler автоматически demote'ит
   * single-N groups к mixed (предотвращает r_hat > 1.1 на degenerate hyperprior).
   *
   * @component ChannelCategoriesPanel
   */
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import { Check, Target, ChartColumn, Circle } from 'lucide-svelte';
  import {
    activeProjectId, activeProject, channelCategories,
    decomposeData, optimizeData,
  } from '$lib/project-state.js';

  /** @type {{ columns: any[] }} */
  let { columns } = $props();

  /** @type {Record<string, { category: string, confidence: number, reasoning: string }>} */
  let suggestions = $state({});
  let suggestionsLoaded = $state(false);
  /** @type {string | null} Channel currently being edited via popup (null = closed) */
  let editingChannel = $state(null);

  const BADGES = {
    brand: { Icon: Target, label: 'Brand', tone: 'brand' },
    performance: { Icon: ChartColumn, label: 'Performance', tone: 'performance' },
    mixed: { Icon: Circle, label: 'Смешанный', tone: 'mixed' },
  };

  /** @type {Record<'brand' | 'performance' | 'mixed', string>} */
  const HELP = {
    brand: 'Каналы с долгим эффектом - TV, TRPs, OOH, радио. Строят знание бренда (decay 4-26 недель). Модель применяет hierarchical prior с большей variance - отражает unknown brand-build duration.',
    performance: 'Каналы прямого отклика - Search, Social, контекст, programmatic. Закрывают спрос (decay 1-2 недели). Стандартный geometric adstock с тесным prior на короткий decay.',
    mixed: 'Категория «Смешанный» используется для ambiguous каналов (Спецпроект, OLV, cross-channel). Модель применяет single prior без group splitting.',
  };

  const mediaChannels = $derived(
    (columns ?? []).filter(/** @param {any} c */ (c) => c.role === 'media').map(/** @param {any} c */ (c) => c.name)
  );

  // Auto-suggest backend call (one-shot когда mediaChannels первый раз появляются)
  let lastSuggestedKey = '';
  $effect(() => {
    if (!mediaChannels.length) return;
    const key = mediaChannels.slice().sort().join('|');
    if (key === lastSuggestedKey) return;
    lastSuggestedKey = key;

    fetch_suggestions(mediaChannels);
  });

  /**
   * @param {string[]} channels
   */
  async function fetch_suggestions(channels) {
    try {
      const data = /** @type {{ status?: string, suggestions?: Record<string, any> }} */ (
        await invoke('econ_categorize_channels', { channels })
      );
      if (data && data.status === 'ok' && data.suggestions) {
        suggestions = data.suggestions;
        // Apply auto-suggestions only if no existing categorization
        const existing = get(channelCategories);
        /** @type {Record<string, 'brand' | 'performance' | 'mixed'>} */
        const updates = { ...existing };
        let changed = false;
        for (const [ch, sug] of Object.entries(suggestions)) {
          if (!existing[ch] && sug.confidence >= 0.7) {
            const cat = sug.category;
            if (cat === 'brand' || cat === 'performance' || cat === 'mixed') {
              updates[ch] = cat;
              changed = true;
            }
          }
        }
        if (changed) {
          channelCategories.set(updates);
          persist(updates);
        }
      }
      suggestionsLoaded = true;
    } catch {
      // Sidecar may be unavailable (cold-start, network issue) - keep manual-only mode.
      suggestionsLoaded = true;
    }
  }

  /**
   * @param {Record<string, string>} cats
   */
  async function persist(cats) {
    const projectId = get(activeProjectId);
    if (!projectId) return;
    try {
      const info = /** @type {any} */ (await invoke('project_update', {
        projectId,
        updates: { channel_categories: cats },
      }));
      // Synergy with UnitCostsPanel pattern: keep activeProject store in sync after persist.
      // Иначе ProjectSelector / ImportStep / др. components могут показывать stale data.
      if (info) activeProject.set(info);
    } catch (e) {
      console.warn('Failed to persist channel_categories:', e);
    }
  }

  /**
   * Reactive map канал → resolved категория.
   * FIX 2026-05-01: было `function getCategory(channel) { return get(channelCategories)[channel] }`,
   * но `get()` императивно читает store без подписки - Svelte не re-renders при изменении.
   * Кликаешь option в popup → setCategory() обновляет store → UI остаётся прежним.
   * `$derived.by` с `$channelCategories` reactivity-tracks store → автоматический re-render.
   * @type {Record<string, 'brand' | 'performance' | 'mixed'>}
   */
  const resolvedCategories = $derived.by(() => {
    const explicit = $channelCategories;
    /** @type {Record<string, 'brand' | 'performance' | 'mixed'>} */
    const result = {};
    for (const ch of mediaChannels) {
      const e = explicit[ch];
      if (e === 'brand' || e === 'performance' || e === 'mixed') {
        result[ch] = e;
      } else {
        const s = suggestions[ch]?.category;
        result[ch] = (s === 'brand' || s === 'performance' || s === 'mixed') ? s : 'mixed';
      }
    }
    return result;
  });

  /** Backward-compat helper для остального кода. Use resolvedCategories[ch] в template для reactivity.
   * @param {string} channel
   * @returns {'brand' | 'performance' | 'mixed'}
   */
  function getCategory(channel) {
    return resolvedCategories[channel] ?? 'mixed';
  }

  /**
   * @param {string} channel
   * @returns {number}
   */
  function getConfidence(channel) {
    const explicit = get(channelCategories)[channel];
    if (explicit) return 1.0;  // user-set = 100% confident
    return suggestions[channel]?.confidence ?? 0;
  }

  /**
   * @param {string} channel
   * @param {'brand' | 'performance' | 'mixed'} category
   */
  function setCategory(channel, category) {
    const current = get(channelCategories);
    if (current[channel] === category) {
      // No-op - no need to persist same value or invalidate downstream.
      editingChannel = null;
      return;
    }
    const updated = { ...current, [channel]: category };
    channelCategories.set(updated);
    persist(updated);
    // Категория влияет на priors при training. Старая модель использовала
    // другую категорию → её декомпозиция/оптимизация теперь не consistent с UI.
    // Inval'ить downstream → user видит «требуется переобучение» в pipeline.
    decomposeData.set(null);
    optimizeData.set(null);
    editingChannel = null;
  }

  /** @type {Array<'brand' | 'performance' | 'mixed'>} */
  const CATEGORY_OPTIONS = ['brand', 'mixed', 'performance'];

  // Reactive group counts (для insights summary).
  // Использует resolvedCategories (reactive) вместо getCategory() (imperative)
  // - раньше counts не пересчитывались после setCategory.
  const groupCounts = $derived.by(() => {
    let brand = 0, perf = 0, mixed = 0;
    for (const ch of mediaChannels) {
      const cat = resolvedCategories[ch] ?? 'mixed';
      if (cat === 'brand') brand++;
      else if (cat === 'performance') perf++;
      else mixed++;
    }
    return { brand, perf, mixed };
  });

  const willUseHierarchical = $derived(groupCounts.brand >= 2 || groupCounts.perf >= 2);

  /**
   * @param {KeyboardEvent} e
   */
  function onKeyClose(e) {
    if (e.key === 'Escape') editingChannel = null;
  }
</script>

<svelte:window on:keydown={onKeyClose} />

{#if mediaChannels.length > 0}
<section class="categories-panel">
  <header class="panel-head">
    <h4 class="panel-title">Категория канала <span class="badge-new">v1.1.0</span></h4>
    <p class="panel-hint">
      Brand-каналы (TV/TRPs/OOH) и performance-каналы (Search/Social/Digital)
      работают по-разному. Модель применяет разные priors для adstock decay
      (long для brand, short для performance) - даёт более точную атрибуцию ROI.
    </p>
    <p class="panel-hint panel-hint-action">
      Учитывая характер размещения и креативных материалов, определите категорию для каждого канала.
    </p>
  </header>

  <div class="summary-row" class:hierarchical-active={willUseHierarchical}>
    <span class="count brand"><Target size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> {groupCounts.brand} brand</span>
    <span class="count performance"><ChartColumn size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> {groupCounts.perf} performance</span>
    {#if groupCounts.mixed > 0}
      <span class="count mixed"><Circle size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> {groupCounts.mixed} смешанных</span>
    {/if}
    <span class="status">
      {#if willUseHierarchical}
        Hierarchical prior активен - модель разделит brand vs performance
      {:else}
        Hierarchical требует ≥2 каналов в одной из brand/performance групп
      {/if}
    </span>
  </div>

  <div class="badges-list">
    {#each mediaChannels as ch (ch)}
      {@const cat = resolvedCategories[ch] ?? 'mixed'}
      {@const badge = BADGES[cat]}
      {@const BadgeIcon = badge.Icon}
      <button
        type="button"
        class="badge-row tone-{badge.tone}"
        onclick={() => { editingChannel = ch; }}
        aria-haspopup="dialog"
      >
        <span class="channel-name">{ch}</span>
        <span class="badge-icon"><BadgeIcon size={16} strokeWidth={1.5} style="vertical-align: -0.15em" /></span>
        <span class="badge-label">{badge.label}</span>
        <span class="edit-hint">▾</span>
      </button>
    {/each}
  </div>
</section>
{/if}

{#if editingChannel}
  <div class="popup-overlay" role="dialog" aria-modal="true" onclick={() => editingChannel = null}>
    <div class="popup" role="document" onclick={(e) => e.stopPropagation()}>
      <header class="popup-head">
        <h5>Категория канала: <code>{editingChannel}</code></h5>
        <button class="close" onclick={() => editingChannel = null} aria-label="Закрыть">×</button>
      </header>
      <div class="popup-options">
        {#each CATEGORY_OPTIONS as opt (opt)}
          {@const badge = BADGES[opt]}
          {@const OptIcon = badge.Icon}
          {@const isActive = editingChannel ? (resolvedCategories[editingChannel] ?? 'mixed') === opt : false}
          <button
            type="button"
            class="option tone-{badge.tone}"
            class:active={isActive}
            onclick={() => editingChannel && setCategory(editingChannel, opt)}
          >
            <span class="opt-head">
              <span class="opt-icon"><OptIcon size={16} strokeWidth={1.5} style="vertical-align: -0.15em" /></span>
              <strong>{badge.label}</strong>
              {#if isActive}<span class="check"><Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /></span>{/if}
            </span>
            <span class="opt-help">{HELP[opt]}</span>
          </button>
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  .categories-panel {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.04));
    border-radius: 12px;
  }

  .panel-head { display: flex; flex-direction: column; gap: 4px; }
  .panel-title {
    margin: 0; font-size: 15px; font-weight: 600;
    display: flex; align-items: center; gap: 8px;
  }
  .badge-new {
    font-size: 10px; font-weight: 500;
    padding: 2px 6px; border-radius: 4px;
    background: rgba(127, 90, 240, 0.18);
    color: rgba(192, 165, 250, 0.95);
  }
  .panel-hint {
    margin: 0; font-size: 12px; line-height: 1.5;
    color: var(--text-secondary, rgba(255, 255, 255, 0.65));
  }
  .panel-hint-action {
    margin-top: 6px;
    color: var(--text-primary, rgba(255, 255, 255, 0.88));
    font-weight: 500;
  }

  .summary-row {
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    padding: 10px 12px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 8px;
    font-size: 13px;
  }
  .summary-row.hierarchical-active { border-left: 3px solid rgba(127, 90, 240, 0.7); }
  .count.brand { color: var(--color-info); }
  .count.performance { color: var(--success); }
  .count.mixed { color: rgba(200, 200, 200, 0.7); }
  .status { margin-left: auto; font-size: 11px; color: var(--text-muted, rgba(255, 255, 255, 0.5)); }

  .badges-list {
    display: grid; grid-template-columns: 1fr; gap: 6px;
  }
  .badge-row {
    display: grid;
    /* Swap 2026-05-01: channel-name → icon → label → hint.
       Имя канала первое = естественный read order ("Что → Какая категория").
       Confidence % убран 2026-05-01 - категорий только 3 фиксированных, manual=100%
       не несёт информации UI-stage. */
    grid-template-columns: 1fr auto auto auto;
    gap: 10px; align-items: center;
    padding: 8px 12px;
    /* Theme-adaptive contrast (2026-05-01): hardcoded rgba(255,255,255,…) был
       почти невидим в light/fun темах (white-on-white). color-mix с text-primary
       даёт consistent subtle contrast независимо от theme background. */
    background: color-mix(in srgb, var(--text-primary, #fff) 5%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-primary, #fff) 9%, transparent);
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    text-align: left; font-size: 13px;
    color: inherit;
  }
  .badge-row:hover {
    background: color-mix(in srgb, var(--text-primary, #fff) 10%, transparent);
    border-color: color-mix(in srgb, var(--text-primary, #fff) 18%, transparent);
  }
  .badge-row.tone-brand { border-left: 3px solid color-mix(in srgb, #6ea8fe 80%, var(--text-primary, #fff) 0%); }
  .badge-row.tone-performance { border-left: 3px solid color-mix(in srgb, #4caf50 80%, var(--text-primary, #fff) 0%); }
  .badge-row.tone-mixed { border-left: 3px solid color-mix(in srgb, var(--text-secondary, #888) 60%, transparent); }

  .badge-icon { font-size: 16px; }
  .badge-label { font-weight: 600; min-width: 100px; }
  .channel-name {
    color: var(--text-primary, rgba(255, 255, 255, 0.92));
    font-weight: 500;
  }
  .edit-hint { color: rgba(255, 255, 255, 0.4); font-size: 12px; }

  .popup-overlay {
    position: fixed; inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex; align-items: center; justify-content: center;
    z-index: 10500;  /* выше slideout (10500 set in v1.0.16) - modal-on-modal */
  }
  .popup {
    background: var(--bg-surface-focus, #2a2a32);
    border-radius: 14px; padding: 20px;
    max-width: 560px; width: 90vw;
    display: flex; flex-direction: column; gap: 14px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
  }
  .popup-head {
    display: flex; align-items: center; justify-content: space-between;
  }
  .popup-head h5 { margin: 0; font-size: 14px; font-weight: 600; }
  .popup-head code { font-family: monospace; font-size: 13px; color: var(--color-info); }
  .close {
    background: none; border: none; cursor: pointer;
    color: rgba(255, 255, 255, 0.6); font-size: 22px; line-height: 1;
  }
  .close:hover { color: white; }

  .popup-options { display: flex; flex-direction: column; gap: 8px; }
  .option {
    display: flex; flex-direction: column; gap: 6px;
    padding: 12px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 10px;
    cursor: pointer; text-align: left;
    color: inherit;
    transition: background 0.15s, border-color 0.15s;
  }
  .option:hover { background: rgba(255, 255, 255, 0.08); }
  .option.active { border-color: rgba(127, 90, 240, 0.6); background: rgba(127, 90, 240, 0.08); }
  .option.tone-brand { border-left: 3px solid rgba(110, 168, 254, 0.7); }
  .option.tone-performance { border-left: 3px solid rgba(110, 220, 158, 0.7); }
  .option.tone-mixed { border-left: 3px solid rgba(200, 200, 200, 0.4); }
  .opt-head { display: flex; align-items: center; gap: 8px; font-size: 14px; }
  .opt-icon { font-size: 16px; }
  .check { margin-left: auto; color: rgba(127, 220, 158, 0.95); font-weight: 700; }
  .opt-help {
    font-size: 12px; line-height: 1.5;
    color: var(--text-secondary, rgba(255, 255, 255, 0.7));
  }
</style>
