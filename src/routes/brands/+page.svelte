<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { brands, activeBrandId, refreshBrands, setActiveBrand, isCreativeHub } from '$lib/creative-store.js';
  import { toast } from '$lib/toast.js';

  // Route guard: non-Creative-Hub → redirect home
  onMount(() => {
    if (!$isCreativeHub) { goto('/'); }
  });

  // Wizard state
  let step = $state(1);
  let brandName = $state('');
  let brandIndustry = $state('');
  let brandDescription = $state('');
  let creating = $state(false);
  let showWizard = $state(false);

  /** @type {string|null} */
  let createdBrandId = $state(null);

  onMount(() => {
    refreshBrands();
  });

  function generateBrandId() {
    return brandName
      .toLowerCase()
      .replace(/[^a-zа-яё0-9\s-]/gi, '')
      .trim()
      .replace(/\s+/g, '-')
      .slice(0, 30) || `brand-${Date.now()}`;
  }

  async function createBrand() {
    if (!brandName.trim()) return;
    creating = true;
    try {
      const brandId = generateBrandId();
      await invoke('brand_create', {
        brandId,
        name: brandName.trim(),
        industry: brandIndustry.trim(),
        description: brandDescription.trim(),
      });
      createdBrandId = brandId;
      await setActiveBrand(brandId);
      await refreshBrands();
      step = 2;
      toast(`Бренд "${brandName}" создан`, 'success');
    } catch (err) {
      toast(`Ошибка: ${err}`, 'error');
    } finally {
      creating = false;
    }
  }

  function resetWizard() {
    step = 1;
    brandName = '';
    brandIndustry = '';
    brandDescription = '';
    createdBrandId = null;
    showWizard = false;
  }
</script>

<div class="brands-page">
  <header class="brands-header">
    <div class="header-left">
      <button class="back-btn" onclick={() => goto('/')}>← Назад</button>
      <h1>Бренды</h1>
    </div>
    <button class="create-btn" onclick={() => { showWizard = true; step = 1; }}>
      + Новый бренд
    </button>
  </header>

  {#if showWizard}
    <div class="wizard-overlay" role="dialog">
      <div class="wizard-card">
        {#if step === 1}
          <h2>Создание бренда</h2>
          <p class="wizard-subtitle">Шаг 1 из 2 - Основная информация</p>

          <label class="field">
            <span>Название <span class="required">*</span></span>
            <input
              type="text"
              bind:value={brandName}
              placeholder="Например: Aurora Technologies"
              maxlength="100"
            />
          </label>

          <label class="field">
            <span>Индустрия</span>
            <input
              type="text"
              bind:value={brandIndustry}
              placeholder="Например: SaaS, Финтех, Ритейл"
            />
          </label>

          <label class="field">
            <span>Описание</span>
            <textarea
              bind:value={brandDescription}
              placeholder="Краткое описание бренда, продуктов, позиционирования..."
              rows="3"
            ></textarea>
          </label>

          <div class="wizard-actions">
            <button class="btn-secondary" onclick={resetWizard}>Отмена</button>
            <button
              class="btn-primary"
              disabled={!brandName.trim() || creating}
              onclick={createBrand}
            >
              {creating ? 'Создаю...' : 'Создать'}
            </button>
          </div>

        {:else if step === 2}
          <h2>Бренд создан!</h2>
          <p class="wizard-subtitle">"{brandName}" готов к работе</p>

          <div class="success-info">
            <p>Бренд активирован. Вы можете добавить документы позже на странице бренда.</p>
          </div>

          <div class="wizard-actions">
            <button class="btn-secondary" onclick={() => {
              resetWizard();
              if (createdBrandId) goto(`/brand/${createdBrandId}`);
            }}>
              Открыть бренд
            </button>
            <button class="btn-primary" onclick={() => { resetWizard(); goto('/'); }}>
              К кабинетам
            </button>
          </div>
        {/if}
      </div>
    </div>
  {/if}

  <div class="brands-grid">
    {#each $brands as brand (brand.brand_id)}
      <button
        class="brand-card"
        class:active={$activeBrandId === brand.brand_id}
        onclick={() => goto(`/brand/${brand.brand_id}`)}
      >
        <div class="brand-icon">{brand.name.charAt(0).toUpperCase()}</div>
        <div class="brand-info">
          <h3>{brand.name}</h3>
          {#if brand.industry}
            <span class="brand-industry">{brand.industry}</span>
          {/if}
          {#if brand.description}
            <p class="brand-desc">{brand.description.length > 80 ? brand.description.slice(0, 80) + '...' : brand.description}</p>
          {/if}
        </div>
        {#if $activeBrandId === brand.brand_id}
          <span class="active-badge">Активный</span>
        {/if}
      </button>
    {:else}
      <div class="empty-state">
        <div class="empty-icon">*</div>
        <h3>Создайте первый бренд</h3>
        <p>Бренды помогают организовать документы, контекст и историю для AI</p>
        <button class="create-btn" onclick={() => { showWizard = true; step = 1; }}>+ Создать бренд</button>
      </div>
    {/each}
  </div>
</div>

<style>
  .brands-page {
    padding: 24px;
    max-width: 900px;
    margin: 0 auto;
    height: 100%;
    overflow-y: auto;
  }

  .brands-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .brands-header h1 {
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--text-primary, #fff);
    margin: 0;
  }

  .back-btn {
    background: none;
    border: 1px solid var(--border);
    color: var(--text-secondary, #aaa);
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.85rem;
  }

  .back-btn:hover {
    background: var(--hover-bg);
    color: var(--text-primary, #fff);
  }

  .create-btn {
    background: linear-gradient(135deg, var(--brand-gradient-start), var(--brand-gradient-end));
    color: var(--text-on-accent, #fff);
    border: none;
    padding: 8px 20px;
    border-radius: var(--radius-btn);
    cursor: pointer;
    font-weight: 500;
    font-size: 0.9rem;
  }

  .create-btn:hover {
    filter: brightness(1.1);
  }

  .brands-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 16px;
  }

  .brand-card {
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    padding: 16px;
    cursor: pointer;
    text-align: left;
    color: var(--text-primary, #fff);
    display: flex;
    gap: 12px;
    align-items: flex-start;
    position: relative;
    transition: border-color 0.15s, background 0.15s;
    font-family: inherit;
    font-size: inherit;
    width: 100%;
  }

  .brand-card:hover {
    border-color: var(--border);
    background: var(--hover-bg);
  }

  .brand-card.active {
    border-color: var(--brand-gradient-start);
    background: color-mix(in srgb, var(--brand-gradient-start) 8%, transparent);
  }

  .brand-icon {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    background: linear-gradient(135deg, var(--brand-gradient-start), var(--brand-gradient-end));
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 1.1rem;
    color: var(--text-on-accent, #fff);
    flex-shrink: 0;
  }

  .brand-info h3 {
    margin: 0 0 4px;
    font-size: 0.95rem;
    font-weight: 600;
  }

  .brand-industry {
    font-size: 0.75rem;
    color: var(--text-tertiary, #888);
    background: var(--hover-bg);
    padding: 2px 8px;
    border-radius: 4px;
  }

  .brand-desc {
    margin: 6px 0 0;
    font-size: 0.8rem;
    color: var(--text-secondary, #aaa);
    line-height: 1.3;
  }

  .active-badge {
    position: absolute;
    top: 8px;
    right: 8px;
    background: var(--brand-gradient-start);
    color: var(--text-on-accent, #fff);
    font-size: 0.7rem;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 500;
  }

  .empty-state {
    grid-column: 1 / -1;
    text-align: center;
    padding: 48px 16px;
    color: var(--text-secondary, #aaa);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }

  .empty-icon { font-size: 2rem; margin-bottom: 8px; }
  .empty-state h3 { margin: 0; font-size: 1.1rem; color: var(--text-primary, #fff); }
  .empty-state p { margin: 0; font-size: 0.85rem; max-width: 300px; }

  /* Wizard */
  .wizard-overlay {
    position: fixed;
    inset: 0;
    background: var(--overlay-bg);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    backdrop-filter: var(--blur-quiet);
  }

  .wizard-card {
    background: var(--bg-surface, #1a1a2e);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 32px;
    width: 90%;
    max-width: 480px;
  }

  .wizard-card h2 {
    margin: 0 0 4px;
    font-size: 1.3rem;
    color: var(--text-primary, #fff);
  }

  .wizard-subtitle {
    color: var(--text-secondary, #aaa);
    font-size: 0.85rem;
    margin: 0 0 24px;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 16px;
  }

  .field span {
    font-size: 0.85rem;
    color: var(--text-secondary, #aaa);
  }

  .required {
    color: var(--danger);
  }

  .field input, .field textarea {
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-input);
    padding: 10px 12px;
    color: var(--text-primary, #fff);
    font-size: 0.9rem;
    font-family: inherit;
    outline: none;
  }

  .field input:focus, .field textarea:focus {
    border-color: var(--brand-gradient-start);
  }

  .wizard-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 24px;
  }

  .btn-primary {
    background: linear-gradient(135deg, var(--brand-gradient-start), var(--brand-gradient-end));
    color: var(--text-on-accent, #fff);
    border: none;
    padding: 8px 20px;
    border-radius: var(--radius-btn);
    cursor: pointer;
    font-weight: 500;
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-secondary {
    background: var(--hover-bg);
    color: var(--text-primary, #fff);
    border: 1px solid var(--border);
    padding: 8px 20px;
    border-radius: var(--radius-btn);
    cursor: pointer;
  }

  .success-info {
    background: color-mix(in srgb, var(--brand-gradient-start) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--brand-gradient-start) 20%, transparent);
    border-radius: 8px;
    padding: 16px;
    margin: 16px 0;
    color: var(--text-secondary, #aaa);
    font-size: 0.9rem;
  }
</style>
