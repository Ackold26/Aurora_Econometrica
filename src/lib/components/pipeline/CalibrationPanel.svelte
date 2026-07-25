<script>
  /**
   * E2 (2026-07-03): форма «Результат эксперимента» — калибровка модели
   * lift-тестами (Robyn §4.3 / Jin 2017: эксперимент двигает оценки к истине).
   *
   * Пользователь вводит: канал, период теста, измеренный прирост KPI с
   * интервалом и уровнем уверенности, тип теста. При обучении lift войдёт
   * в модель дополнительным наблюдением; отчёт пометит канал [CALIBRATED]
   * и честно покажет расхождение, если модель и тест разойдутся.
   *
   * Только байесовский режим (гейт — у родителя).
   *
   * @component CalibrationPanel
   */
  import { FlaskConical, Trash2, Plus } from 'lucide-svelte';
  import {
    calibrations, persistCalibrations, validateCalibrationEntry,
  } from '$lib/calibration-store.js';

  /** @type {{ channels: string[], projectId: string | null }} */
  const { channels, projectId } = $props();

  let draft = $state({
    channel: '',
    date_from: '',
    date_to: '',
    lift_abs: '',
    lift_low: '',
    lift_high: '',
    confidence_level: 0.9,
    test_type: 'geo_lift',
  });
  /** @type {string | null} */
  let formError = $state(null);

  const TEST_TYPES = [
    { value: 'geo_lift', label: 'Гео-эксперимент' },
    { value: 'ab_test', label: 'A/B-тест' },
    { value: 'holdout', label: 'Отключение канала (holdout)' },
    { value: 'other', label: 'Другой' },
  ];

  function addCalibration() {
    const entry = {
      channel: draft.channel,
      date_from: draft.date_from,
      date_to: draft.date_to,
      lift_abs: Number(draft.lift_abs),
      lift_low: Number(draft.lift_low),
      lift_high: Number(draft.lift_high),
      confidence_level: Number(draft.confidence_level),
      test_type: draft.test_type,
    };
    const err = validateCalibrationEntry(entry);
    if (err) {
      formError = err;
      return;
    }
    formError = null;
    calibrations.update((list) => [...list, entry]);
    persistCalibrations(projectId);
    draft = { ...draft, lift_abs: '', lift_low: '', lift_high: '' };
  }

  /** @param {number} idx */
  function removeCalibration(idx) {
    calibrations.update((list) => list.filter((_, i) => i !== idx));
    persistCalibrations(projectId);
  }
</script>

<div class="calib-panel" data-testid="calibration-panel">
  <div class="calib-head">
    <span class="calib-icon" aria-hidden="true"><FlaskConical size={15} strokeWidth={1.7} /></span>
    <span class="calib-title">Калибровка экспериментом</span>
    <span class="calib-hint">
      Если у вас есть результат A/B или гео-теста – модель учтёт его как
      дополнительное наблюдение и приблизит оценку канала к измеренной.
    </span>
  </div>

  {#if $calibrations.length > 0}
    <ul class="calib-list">
      {#each $calibrations as c, idx (idx)}
        <li class="calib-row">
          <span class="calib-ch">{c.channel}</span>
          <span class="calib-meta">
            {c.date_from} – {c.date_to} · прирост {c.lift_abs}
            [{c.lift_low}–{c.lift_high}] ·
            {TEST_TYPES.find((t) => t.value === c.test_type)?.label ?? c.test_type}
          </span>
          <button
            type="button"
            class="calib-del"
            aria-label={`Удалить калибровку ${c.channel}`}
            onclick={() => removeCalibration(idx)}
          ><Trash2 size={14} strokeWidth={1.7} /></button>
        </li>
      {/each}
    </ul>
  {/if}

  <div class="calib-form">
    <select class="calib-input" bind:value={draft.channel} aria-label="Канал теста">
      <option value="" disabled>Канал…</option>
      {#each channels as ch (ch)}
        <option value={ch}>{ch}</option>
      {/each}
    </select>
    <input class="calib-input" type="date" bind:value={draft.date_from} aria-label="Начало теста" />
    <input class="calib-input" type="date" bind:value={draft.date_to} aria-label="Конец теста" />
    <input class="calib-input" type="number" placeholder="Прирост KPI"
           bind:value={draft.lift_abs} aria-label="Измеренный прирост" />
    <input class="calib-input calib-narrow" type="number" placeholder="от"
           bind:value={draft.lift_low} aria-label="Нижняя граница" />
    <input class="calib-input calib-narrow" type="number" placeholder="до"
           bind:value={draft.lift_high} aria-label="Верхняя граница" />
    <select class="calib-input calib-narrow" bind:value={draft.confidence_level}
            aria-label="Уровень интервала">
      <option value={0.8}>80%</option>
      <option value={0.9}>90%</option>
      <option value={0.95}>95%</option>
    </select>
    <select class="calib-input" bind:value={draft.test_type} aria-label="Тип теста">
      {#each TEST_TYPES as t (t.value)}
        <option value={t.value}>{t.label}</option>
      {/each}
    </select>
    <button type="button" class="calib-add" onclick={addCalibration}>
      <Plus size={14} strokeWidth={2} aria-hidden="true" /> Добавить
    </button>
  </div>
  {#if formError}
    <p class="calib-error" role="alert">{formError}</p>
  {/if}
</div>

<style>
  .calib-panel {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 14px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.12));
    border-radius: 8px;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.03));
  }
  .calib-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
  .calib-icon { opacity: 0.8; align-self: center; }
  .calib-title { font-size: 13px; font-weight: 600; }
  .calib-hint { font-size: 11.5px; color: var(--text-secondary, #9aa3b2); flex-basis: 100%; }
  .calib-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
  .calib-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    padding: 5px 8px;
    border-radius: 6px;
    background: var(--bg-surface-focus, rgba(255, 255, 255, 0.06));
  }
  .calib-ch { font-weight: 600; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .calib-meta { flex: 1; color: var(--text-secondary, #9aa3b2); }
  .calib-del {
    border: none; background: transparent; color: inherit;
    cursor: pointer; opacity: 0.7; display: inline-flex;
  }
  .calib-del:hover { opacity: 1; }
  .calib-form { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .calib-input {
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.16));
    background: var(--bg-surface-focus, rgba(255, 255, 255, 0.06));
    color: inherit;
    font-size: 12px;
    min-width: 110px;
  }
  .calib-narrow { min-width: 64px; max-width: 84px; }
  .calib-add {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 7px 12px;
    border-radius: 6px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.16));
    background: var(--bg-surface-focus, rgba(255, 255, 255, 0.08));
    color: inherit;
    font-size: 12px;
    cursor: pointer;
  }
  .calib-add:hover { filter: brightness(1.15); }
  .calib-error { margin: 0; font-size: 12px; color: var(--danger, #d64545); }
</style>
