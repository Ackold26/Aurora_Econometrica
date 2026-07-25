<script>
  /**
   * HolidayControlsPanel — #6 Tier-3/OVB (2026-06-07).
   *
   * Панель управления 12 авто-праздниками РФ (holiday_*), которые modeler.py
   * инжектит как control-факторы из даты. Юзер может ОТКЛЮЧИТЬ отдельные праздники.
   *
   * Когда отключать: после обучения у каждого праздника появляется badge posterior
   * contraction. <0.1 = «неинформативный» (данные его не определили) → отключение
   * БЕЗ omitted-variable bias и без нечестного роста MQS (цель — чистота модели).
   * ≥0.3 = «влияет» → отключать НЕ рекомендуется (сместит ROI медиа + накрутит MQS-cap).
   *
   * Persistence через project_update({disabled_holidays}) — паттерн ChannelCategoriesPanel.
   * Отключение помечает обученную модель устаревшей (modelStaleStatus ловит disabled-дифф).
   *
   * @component HolidayControlsPanel
   */
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import {
    activeProjectId, activeProject, disabledHolidays, useHolidays, modelData,
    decomposeData, optimizeData,
  } from '$lib/project-state.js';
  import { HOLIDAY_CALENDAR_RU } from '$lib/holiday-calendar.js';
  import Tooltip from '$lib/components/Tooltip.svelte';

  let expanded = $state(false);

  // Мастер-флаг «учитывать праздники РФ как факторы» (ON по умолчанию). Когда OFF —
  // modeler.py не инжектит праздники → выше Ratio, но риск OVB. Per-holiday тоглы
  // ниже становятся неактивны (праздников в модели нет).
  const masterOn = $derived($useHolidays !== false);

  // Тултип ? на выключателе — описание + мотивация шага (требование 2026-06-13).
  const MASTER_TIP =
    'Праздники РФ (Новый год, 8 марта, чёрная пятница и др.) автоматически учитываются ' +
    'как факторы при обучении — это ~12 дополнительных контролей. Отключите, если ' +
    'данных мало или категория не зависит от праздников: модель станет проще, число ' +
    'параметров упадёт, а Ratio (наблюдения ÷ параметры — мера надёжности) вырастет. ' +
    'Риск: если праздники реально влияют на продажи, их отключение исказит вклад ' +
    'медиаканалов (omitted-variable bias).';

  /** Переключить мастер-флаг + persist (паттерн toggle ниже: оптимистично + rollback). */
  async function toggleMaster() {
    const prev = get(useHolidays);
    const next = prev === false;  // OFF→ON, иначе ON→OFF
    useHolidays.set(next);  // оптимистично
    const projectId = get(activeProjectId);
    if (!projectId) { useHolidays.set(prev); return; }
    try {
      const info = /** @type {any} */ (await invoke('project_update', {
        projectId,
        updates: { use_holidays: next },
      }));
      if (info) activeProject.set(info);
      // Состав контролей изменился → старая декомпозиция/оптимизация не consistent.
      decomposeData.set(null);
      optimizeData.set(null);
    } catch (e) {
      console.warn('Failed to persist use_holidays:', e);
      useHolidays.set(prev);  // rollback — иначе store ≠ диск
    }
  }

  // per_control_contraction появляется в diagnostics ПОСЛЕ обучения. До обучения null
  // → бейджи не показываем (нет данных «информативен ли праздник»).
  const contraction = $derived(
    /** @type {Record<string, number> | null} */ ($modelData?.diagnostics?.per_control_contraction ?? null)
  );

  const disabledSet = $derived(new Set($disabledHolidays ?? []));
  const disabledCount = $derived(disabledSet.size);

  /**
   * Тир информативности праздника по contraction (только после обучения).
   * @param {string} name
   * @returns {{ tier: 'uninformative'|'weak'|'informative', value: number } | null}
   */
  function tierOf(name) {
    if (!contraction || typeof contraction[name] !== 'number') return null;
    const v = contraction[name];
    if (v < 0.1) return { tier: 'uninformative', value: v };
    if (v >= 0.3) return { tier: 'informative', value: v };
    return { tier: 'weak', value: v };
  }

  // Сколько неинформативных праздников ВКЛючено (кандидаты на отключение) — для подсказки.
  const uninformativeEnabled = $derived(
    contraction
      ? HOLIDAY_CALENDAR_RU.filter((h) => {
          const t = tierOf(h.name);
          return t?.tier === 'uninformative' && !disabledSet.has(h.name);
        }).length
      : 0
  );

  /**
   * Переключить праздник ВКЛ/ВЫКЛ + persist. Стабильный порядок списка (по календарю)
   * — чтобы persisted-массив был детерминирован (упрощает диффы / stale-сравнение).
   * Оптимистичный update с ROLLBACK при ошибке persist (adversarial-аудит #2/#3):
   * store не должен расходиться с диском; инвалидация downstream — только при успехе.
   * @param {string} name
   */
  async function toggle(name) {
    const prev = get(disabledHolidays) ?? [];
    const set = new Set(prev);
    if (set.has(name)) set.delete(name); else set.add(name);
    const next = HOLIDAY_CALENDAR_RU.map((h) => h.name).filter((n) => set.has(n));
    disabledHolidays.set(next);  // оптимистично
    const ok = await persist(next);
    if (!ok) {
      disabledHolidays.set(prev);  // rollback — иначе store ≠ диск
      return;
    }
    // persist успешен → состав контролей изменился → декомпозиция/оптимизация старой
    // модели больше не consistent → inval'ить (паттерн ChannelCategoriesPanel.setCategory).
    decomposeData.set(null);
    optimizeData.set(null);
  }

  /** @param {string[]} list @returns {Promise<boolean>} успех persist */
  async function persist(list) {
    const projectId = get(activeProjectId);
    if (!projectId) return false;
    try {
      const info = /** @type {any} */ (await invoke('project_update', {
        projectId,
        updates: { disabled_holidays: list },
      }));
      // Sync activeProject (паттерн ChannelCategoriesPanel) — иначе др. компоненты
      // покажут stale. persist синхронный при каждом toggle → закрывает гонку
      // гидрации (mid-session overwrite), т.к. диск всегда = текущему состоянию.
      if (info) activeProject.set(info);
      return true;
    } catch (e) {
      console.warn('Failed to persist disabled_holidays:', e);
      return false;
    }
  }
</script>

<section class="holidays-panel">
  <button
    type="button"
    class="panel-head"
    onclick={() => (expanded = !expanded)}
    aria-expanded={expanded}
  >
    <span class="head-main">
      <span class="chevron" class:open={expanded}>▸</span>
      <h4 class="panel-title">Авто-праздники РФ</h4>
      <span class="count-badge">12{#if disabledCount > 0} · {disabledCount} откл.{/if}</span>
    </span>
    {#if uninformativeEnabled > 0}
      <span class="tip-badge" title="После обучения видно, какие праздники не повлияли">
        {uninformativeEnabled} можно отключить
      </span>
    {/if}
  </button>

  {#if expanded}
    <!-- Мастер-выключатель «учитывать праздники как факторы» + ? тултип. -->
    <div class="master-row">
      <label class="master-toggle">
        <input type="checkbox" checked={masterOn} onchange={toggleMaster} />
        <span class="master-label">Учитывать праздники РФ как факторы</span>
      </label>
      <Tooltip text={MASTER_TIP} position="auto">
        <span class="help-badge" tabindex="0" role="button"
              aria-label="Зачем нужен учёт праздников и когда его отключать">?</span>
      </Tooltip>
    </div>

    {#if !masterOn}
      <p class="master-off-note">
        Праздники отключены – модель проще и Ratio (надёжность) выше. Но если категория
        сезонна к праздникам, вклад медиаканалов может исказиться (omitted-variable bias).
        Список ниже не применяется, пока учёт выключен.
      </p>
    {/if}

    {#if masterOn}
    <p class="panel-hint">
      Модель автоматически учитывает 12 праздников РФ как контрольные факторы.
      {#if contraction}
        После обучения у каждого виден вклад: <strong>не повлиял</strong> – данных
        не хватило, можно отключить для чистоты модели (ROI каналов и честный MQS
        не изменятся); <strong>влияет</strong> – отключать не нужно (сместит ROI медиа).
      {:else}
        Обучите модель, чтобы увидеть, какие из них реально повлияли на продажи.
      {/if}
    </p>
    {/if}

    <div class="holiday-list" class:dimmed={!masterOn}>
      {#each HOLIDAY_CALENDAR_RU as h (h.name)}
        {@const t = tierOf(h.name)}
        {@const off = disabledSet.has(h.name)}
        <div class="holiday-row" class:disabled={off || !masterOn}>
          <label class="holiday-toggle" title={h.hint}>
            <input
              type="checkbox"
              checked={!off}
              disabled={!masterOn}
              onchange={() => toggle(h.name)}
              aria-label="{h.label} – {off ? 'выключен' : 'включён'} ({h.hint})"
            />
            <span class="holiday-label">{h.label}</span>
          </label>
          {#if t}
            <span class="tier tier-{t.tier}">
              {#if t.tier === 'uninformative'}не повлиял{:else if t.tier === 'informative'}влияет{:else}слабо влияет{/if}
            </span>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  .holidays-panel {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.04));
    border-radius: 12px;
  }

  .panel-head {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px;
    background: none; border: none; cursor: pointer;
    padding: 0; width: 100%; text-align: left; color: inherit;
  }
  .head-main { display: flex; align-items: center; gap: 8px; }
  .chevron {
    font-size: 12px; color: var(--text-muted, rgba(255, 255, 255, 0.5));
    transition: transform 0.15s;
  }
  .chevron.open { transform: rotate(90deg); }
  .panel-title { margin: 0; font-size: 15px; font-weight: 600; }
  .count-badge {
    font-size: 11px; font-weight: 500;
    padding: 2px 7px; border-radius: 10px;
    background: color-mix(in srgb, var(--text-primary, #fff) 8%, transparent);
    color: var(--text-secondary, rgba(255, 255, 255, 0.7));
  }
  .tip-badge {
    font-size: 11px; font-weight: 600;
    padding: 2px 8px; border-radius: 10px;
    background: color-mix(in srgb, var(--success) 16%, transparent);
    color: var(--success);
  }

  .panel-hint {
    margin: 0; font-size: 12px; line-height: 1.5;
    color: var(--text-secondary, rgba(255, 255, 255, 0.65));
  }

  /* Мастер-выключатель + ? тултип + off-note. Тема-токены, не хардкод светлого. */
  .master-row { display: flex; align-items: center; gap: 8px; }
  .master-toggle {
    display: flex; align-items: center; gap: 8px;
    cursor: pointer; font-size: 13px; font-weight: 600;
  }
  .master-toggle input {
    cursor: pointer; flex-shrink: 0;
    accent-color: var(--accent-primary, #84cc16);
  }
  .master-label { color: var(--text-primary, rgba(255, 255, 255, 0.92)); }
  .help-badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 16px; height: 16px; border-radius: 50%;
    font-size: 11px; font-weight: 700; cursor: help;
    background: color-mix(in srgb, var(--text-primary, #fff) 12%, transparent);
    color: var(--text-secondary, rgba(255, 255, 255, 0.7));
    border: 1px solid color-mix(in srgb, var(--text-primary, #fff) 18%, transparent);
  }
  .help-badge:hover, .help-badge:focus-visible {
    background: color-mix(in srgb, var(--accent-primary, #84cc16) 22%, transparent);
    color: var(--text-primary);
    outline: none;
  }
  .master-off-note {
    margin: 0; font-size: 12px; line-height: 1.5;
    color: var(--warn-text, #b07a00);
    padding: 8px 10px; border-radius: 8px;
    background: var(--warn-bg, rgba(255, 176, 32, 0.1));
    border: 1px solid var(--warn-border, rgba(255, 176, 32, 0.4));
  }
  .holiday-list.dimmed { opacity: 0.45; pointer-events: none; }

  .holiday-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 6px;
  }
  .holiday-row {
    display: flex; align-items: center; justify-content: space-between;
    gap: 8px;
    padding: 7px 10px;
    background: color-mix(in srgb, var(--text-primary, #fff) 5%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-primary, #fff) 9%, transparent);
    border-radius: 8px;
    transition: opacity 0.15s, background 0.15s;
  }
  .holiday-row.disabled { opacity: 0.5; }
  .holiday-toggle {
    display: flex; align-items: center; gap: 8px;
    cursor: pointer; font-size: 13px; flex: 1; min-width: 0;
  }
  .holiday-toggle input { cursor: pointer; flex-shrink: 0; accent-color: #84cc16; }
  .holiday-label {
    color: var(--text-primary, rgba(255, 255, 255, 0.9));
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .tier {
    font-size: 10px; font-weight: 600;
    padding: 2px 6px; border-radius: 6px;
    flex-shrink: 0;
  }
  .tier-uninformative { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
  .tier-informative { background: color-mix(in srgb, var(--color-info) 16%, transparent); color: var(--color-info); }
  .tier-weak { background: color-mix(in srgb, var(--text-primary, #fff) 8%, transparent); color: var(--text-muted, rgba(255, 255, 255, 0.55)); }
</style>
