<script>
  /**
   * SeasonalityControl — автосезонность А (2026-07-04).
   *
   * Мастер-тумблер «учитывать сезонность»: когда ON, modeler.py авто-детектит
   * сезонную волну спроса и инжектит Фурье-гармоники (гейт INV-50: ≥2 полных
   * цикла + статзначимая автокорреляция). Когда OFF — сезонность не инжектится.
   *
   * Зачем: без контроля сезонности модель списывает сезонную волну спроса на
   * медиа → завышенный ROI (боевой случай MMX: медиа-вклад −30% после отделения
   * сезона). После обучения строка честности показывает, учтена ли сезонность и
   * с каким периодом (или почему нет — гейт).
   *
   * Persistence через project_update({use_seasonality}) — паттерн HolidayControlsPanel.
   * @component SeasonalityControl
   */
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import {
    activeProjectId, activeProject, useSeasonality, modelData,
    decomposeData, optimizeData,
  } from '$lib/project-state.js';
  import Tooltip from '$lib/components/Tooltip.svelte';

  const masterOn = $derived($useSeasonality !== false);

  const MASTER_TIP =
    'Модель автоматически ищет сезонную волну спроса (сезон гриппа, весенняя ' +
    'аллергия, летний спад) и учитывает её как гибкую периодическую компоненту. ' +
    'Это защищает от завышения отдачи рекламы: без сезонного контроля модель ' +
    'приписывает сезонный рост спроса медиаканалам. Отключите, если данных мало ' +
    'или сезонность заведомо отсутствует — модель станет проще. Сезонность ' +
    'учитывается только при ≥2 полных циклах в данных (иначе её нельзя оценить честно).';

  // Статус после обучения: diagnostics.seasonality = {detected, period, n_harmonics,
  // autocorr, granularity} | {detected:false} | {detected:false, reason:'ols_mode'}.
  const season = $derived(
    /** @type {{detected: boolean, period?: number, n_harmonics?: number, autocorr?: number, granularity?: string, reason?: string} | null} */
    ($modelData?.diagnostics?.seasonality ?? null)
  );

  /**
   * Человекочитаемая длина периода: год/полугодие/квартал по granularity+period.
   * @param {number} period @param {string} gran
   */
  function periodLabel(period, gran) {
    const yearLen = gran === 'M' ? 12 : gran === 'D' ? 365 : 52;
    if (period === yearLen) return 'годовой';
    if (period === Math.round(yearLen / 2)) return 'полугодовой';
    if (period === Math.round(yearLen / 4)) return 'квартальный';
    const unit = gran === 'M' ? 'мес.' : gran === 'D' ? 'дн.' : 'нед.';
    return `${period} ${unit}`;
  }

  /** Переключить мастер-флаг + persist (оптимистично + rollback). */
  async function toggleMaster() {
    const prev = get(useSeasonality);
    const next = prev === false; // OFF→ON, иначе ON→OFF
    useSeasonality.set(next);
    const projectId = get(activeProjectId);
    if (!projectId) { useSeasonality.set(prev); return; }
    try {
      const info = /** @type {any} */ (await invoke('project_update', {
        projectId,
        updates: { use_seasonality: next },
      }));
      if (info) activeProject.set(info);
      // Состав контролей изменился → декомпозиция/оптимизация старой модели не consistent.
      decomposeData.set(null);
      optimizeData.set(null);
    } catch (e) {
      console.warn('Failed to persist use_seasonality:', e);
      useSeasonality.set(prev); // rollback
    }
  }
</script>

<section class="seasonality-panel">
  <div class="master-row">
    <label class="master-toggle">
      <input type="checkbox" checked={masterOn} onchange={toggleMaster} />
      <span class="master-label">Учитывать сезонность</span>
    </label>
    <Tooltip text={MASTER_TIP} position="auto">
      <span class="help-badge" tabindex="0" role="button"
            aria-label="Зачем нужен учёт сезонности и когда его отключать">?</span>
    </Tooltip>
  </div>

  {#if masterOn}
    {#if season}
      {#if season.detected}
        <p class="season-note detected">
          Сезонность учтена: {periodLabel(season.period ?? 0, season.granularity ?? 'W')} период{#if season.autocorr != null}, сила связи ρ=<abbr title="автокорреляция сезонного сигнала">{season.autocorr.toFixed(2)}</abbr>{/if}.
          Сезонный спрос отделён от вклада рекламы.
        </p>
      {:else if season.reason === 'ols_mode'}
        <p class="season-note none">
          В упрощённом режиме (мало данных) сезонная компонента не используется –
          она доступна в основном режиме обучения.
        </p>
      {:else}
        <p class="season-note none">
          Сезонность не обнаружена: в данных нет статистически значимой периодической
          волны (нужно ≥2 полных цикла). Модель обучена без сезонной компоненты.
        </p>
      {/if}
    {:else}
      <p class="panel-hint">
        Модель сама найдёт сезонную волну спроса при обучении (если её видно в данных).
        Обучите модель, чтобы увидеть результат.
      </p>
    {/if}
  {:else}
    <p class="master-off-note">
      Сезонность отключена – модель проще. Но если категория сезонна, вклад
      медиаканалов может быть завышен (сезонный спрос спишется на рекламу).
    </p>
  {/if}
</section>

<style>
  .seasonality-panel {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 16px;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.04));
    border-radius: 12px;
  }
  .master-row { display: flex; align-items: center; gap: 8px; }
  .master-toggle {
    display: flex; align-items: center; gap: 8px;
    cursor: pointer; font-size: 13px; font-weight: 600;
  }
  .master-toggle input {
    cursor: pointer; flex-shrink: 0;
    accent-color: var(--accent-primary, #8b5cf6);
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
    background: color-mix(in srgb, var(--accent-primary, #8b5cf6) 22%, transparent);
    color: var(--text-primary);
    outline: none;
  }
  .panel-hint {
    margin: 0; font-size: 12px; line-height: 1.5;
    color: var(--text-secondary, rgba(255, 255, 255, 0.65));
  }
  .season-note {
    margin: 0; font-size: 12px; line-height: 1.5;
    padding: 8px 10px; border-radius: 8px;
  }
  .season-note.detected {
    color: var(--success);
    background: color-mix(in srgb, var(--success) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
  }
  .season-note.none {
    color: var(--text-secondary, rgba(255, 255, 255, 0.65));
    background: color-mix(in srgb, var(--text-primary, #fff) 5%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-primary, #fff) 10%, transparent);
  }
  .master-off-note {
    margin: 0; font-size: 12px; line-height: 1.5;
    color: var(--warn-text, #b07a00);
    padding: 8px 10px; border-radius: 8px;
    background: var(--warn-bg, rgba(255, 176, 32, 0.1));
    border: 1px solid var(--warn-border, rgba(255, 176, 32, 0.4));
  }
</style>
