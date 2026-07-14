<script>
  /**
   * E3 (2026-07-03): карточка «История модели» — жизненный цикл поколений.
   *
   * Продукт живёт с клиентом кварталами: при переобучении прежняя версия
   * уходит в архив, и карточка отвечает на два вопроса:
   *  1) «Что изменилось с прошлого раза?» — сравнение поколений с интервалами
   *     (вердикты по перекрытию CI, канон Jin 2017);
   *  2) «Пора ли переобучать?» — дрейф: как архивное поколение держит
   *     точность на свежих точках.
   *
   * Честность: вердикты «резкий сдвиг» показываются так же заметно, как
   * «стабильно»; пороги приходят из движка и не прячутся.
   *
   * @component ModelHistoryCard
   */
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { activeProjectId } from '$lib/project-state.js';
  import { History, GitCompareArrows, TriangleAlert, RefreshCw } from 'lucide-svelte';

  /** @type {'loading' | 'empty' | 'ready'} */
  let cardState = $state('loading');
  /** @type {any[]} */
  let versions = $state([]);
  /** @type {any | null} */
  let compare = $state(null);
  /** @type {'idle' | 'running' | 'error'} */
  let compareState = $state('idle');
  /** @type {string | null} */
  let compareError = $state(null);
  /** @type {any | null} */
  let drift = $state(null);

  const VERDICT_TONES = /** @type {Record<string, string>} */ ({
    stable: 'ok',
    shift_within_ci: 'warn',
    shift_strong: 'bad',
  });

  async function projectDir() {
    const projectId = get(activeProjectId);
    if (!projectId) return null;
    return /** @type {string} */ (await invoke('project_get_dir', { projectId }));
  }

  onMount(() => {
    (async () => {
      try {
        const dir = await projectDir();
        if (!dir) { cardState = 'empty'; return; }
        const hist = /** @type {any} */ (await invoke('econ_model_history', { projectDir: dir }));
        versions = Array.isArray(hist?.versions) ? hist.versions : [];
        if (versions.length === 0) { cardState = 'empty'; return; }
        cardState = 'ready';
        // Сохранённое сравнение — мгновенно; дрейф — дёшев (секунды).
        const saved = /** @type {any} */ (await invoke('econ_generation_compare', {
          projectDir: dir, readOnly: true,
        }));
        if (saved?.status === 'ok') compare = saved;
        const d = /** @type {any} */ (await invoke('econ_drift_check', { projectDir: dir }));
        if (d?.status === 'ok') drift = d;
      } catch {
        // История — необязательный контур: тихо показываем пустое состояние.
        cardState = 'empty';
      }
    })();
  });

  async function runCompare() {
    compareState = 'running';
    compareError = null;
    try {
      const dir = await projectDir();
      if (!dir) {
        compareState = 'error';
        compareError = 'Проект не выбран — переоткройте проект.';
        return;
      }
      const res = /** @type {any} */ (await invoke('econ_generation_compare', { projectDir: dir }));
      if (res?.status === 'ok') {
        compare = res;
        compareState = 'idle';
      } else {
        compareError = res?.message || 'Сравнение не удалось.';
        compareState = 'error';
      }
    } catch (/** @type {any} */ e) {
      compareError = String(e);
      compareState = 'error';
    }
  }

  /** @param {string} ts - 'YYYYmmdd_HHMMSS' → 'ДД.ММ.ГГГГ ЧЧ:ММ' */
  function fmtTs(ts) {
    const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})/.exec(ts || '');
    if (!m) return ts || '—';
    return `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}`;
  }

  /** @param {[number|null, number|null] | undefined} ci */
  function fmtCi(ci) {
    if (!ci || ci[0] == null || ci[1] == null) return '';
    return ` [${Number(ci[0]).toFixed(1)}–${Number(ci[1]).toFixed(1)}]`;
  }
</script>

<section class="mh-card" aria-label="История модели">
  <header class="mh-header">
    <span class="mh-icon" aria-hidden="true"><History size={18} strokeWidth={1.6} /></span>
    <div>
      <h3 class="mh-title">История модели</h3>
      <p class="mh-subtitle">
        При каждом переобучении прежняя версия сохраняется в архив — продукт
        сравнивает поколения и следит, не пора ли обновить модель.
      </p>
    </div>
  </header>

  {#if cardState === 'loading'}
    <p class="mh-quiet" role="status">Загрузка истории…</p>

  {:else if cardState === 'empty'}
    <p class="mh-quiet">
      Поколений в архиве пока нет — история появится автоматически после
      первого переобучения модели.
    </p>

  {:else}
    <p class="mh-versions">
      Поколений в архиве: <b>{versions.length}</b>
      (последнее: {fmtTs(versions[0]?.timestamp)})
    </p>

    {#if drift}
      {#if drift.verdict === 'retrain_recommended'}
        <div class="mh-banner mh-warn" role="alert" data-testid="mh-drift">
          <TriangleAlert size={16} strokeWidth={1.6} aria-hidden="true" />
          <span>{drift.message}</span>
        </div>
      {:else}
        <p class="mh-quiet" data-testid="mh-drift">{drift.message}</p>
      {/if}
    {/if}

    {#if !compare}
      <button
        class="mh-btn"
        onclick={runCompare}
        disabled={compareState === 'running'}
      >
        <GitCompareArrows size={15} strokeWidth={1.7} aria-hidden="true" />
        {compareState === 'running' ? 'Сравниваем…' : 'Что изменилось с прошлого поколения?'}
      </button>
      {#if compareState === 'error' && compareError}
        <div class="mh-banner mh-bad" role="alert">
          <TriangleAlert size={16} strokeWidth={1.6} aria-hidden="true" />
          <span>{compareError}</span>
          <button class="mh-btn-sm" onclick={runCompare}>Повторить</button>
        </div>
      {/if}
    {:else}
      {#if compare.summary?.headline}
        <p class="mh-headline" data-testid="mh-headline">{compare.summary.headline}</p>
      {/if}
      <ul class="mh-channels">
        {#each compare.channels as c (c.name)}
          <li class="mh-channel-row">
            <span class="mh-ch-name">{c.name}</span>
            <span class="mh-ch-vals">
              {Number(c.roi_old).toFixed(1)}{fmtCi(c.roi_ci_old)} →
              {Number(c.roi_new).toFixed(1)}{fmtCi(c.roi_ci_new)}
            </span>
            <span class="mh-verdict mh-{VERDICT_TONES[c.verdict] ?? 'warn'}">
              {c.verdict_ru}{c.method === 'point_only' ? ' (без интервалов)' : ''}
            </span>
          </li>
        {/each}
      </ul>
      {#if compare.added_channels?.length || compare.removed_channels?.length}
        <p class="mh-quiet">
          {#if compare.added_channels?.length}Новые каналы: {compare.added_channels.join(', ')}.{/if}
          {#if compare.removed_channels?.length} Исчезли: {compare.removed_channels.join(', ')}.{/if}
        </p>
      {/if}
      {#if compare.summary?.strong_shifts?.length && compare.summary?.probable_causes?.length}
        <details class="mh-causes">
          <summary>Резкие сдвиги: {compare.summary.strong_shifts.join(', ')} — вероятные причины</summary>
          <ul>
            {#each compare.summary.probable_causes as cause}
              <li>{cause}</li>
            {/each}
          </ul>
        </details>
      {/if}
      <button class="mh-btn-sm mh-refresh" onclick={runCompare} disabled={compareState === 'running'}>
        <RefreshCw size={13} strokeWidth={1.7} aria-hidden="true" />
        {compareState === 'running' ? 'Пересчитываем…' : 'Пересчитать сравнение'}
      </button>
    {/if}
  {/if}
</section>

<style>
  .mh-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px 18px;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.04));
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.12));
    border-radius: 10px;
  }
  .mh-header { display: flex; gap: 10px; align-items: flex-start; }
  .mh-icon { margin-top: 2px; opacity: 0.8; }
  .mh-title { margin: 0; font-size: 15px; font-weight: 600; }
  .mh-subtitle {
    margin: 4px 0 0;
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--text-secondary, #9aa3b2);
  }
  .mh-quiet { font-size: 13px; color: var(--text-secondary, #9aa3b2); margin: 0; }
  .mh-versions { font-size: 13px; margin: 0; }
  .mh-banner {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 10px 12px;
    border-radius: 8px;
    font-size: 13px;
  }
  .mh-warn {
    background: color-mix(in srgb, var(--warning, #d9a514) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #d9a514) 35%, transparent);
  }
  .mh-bad {
    background: color-mix(in srgb, var(--danger, #d64545) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger, #d64545) 35%, transparent);
  }
  .mh-btn, .mh-btn-sm {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    align-self: flex-start;
    padding: 9px 14px;
    border-radius: 8px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.16));
    background: var(--bg-surface-focus, rgba(255, 255, 255, 0.08));
    color: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .mh-btn-sm { padding: 6px 10px; font-size: 12px; }
  .mh-btn:hover:not(:disabled), .mh-btn-sm:hover:not(:disabled) { filter: brightness(1.15); }
  .mh-btn:disabled, .mh-btn-sm:disabled { opacity: 0.6; cursor: default; }
  .mh-headline { margin: 0; font-size: 13.5px; font-weight: 600; }
  .mh-channels { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
  .mh-channel-row {
    display: flex;
    gap: 10px;
    align-items: baseline;
    font-size: 12.5px;
    border-bottom: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
    padding-bottom: 6px;
  }
  .mh-ch-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mh-ch-vals { font-variant-numeric: tabular-nums; }
  .mh-verdict {
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    white-space: nowrap;
  }
  .mh-verdict.mh-ok {
    background: color-mix(in srgb, var(--success, #2f9e63) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #2f9e63) 40%, transparent);
  }
  .mh-verdict.mh-warn {
    background: color-mix(in srgb, var(--warning, #d9a514) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #d9a514) 40%, transparent);
  }
  .mh-verdict.mh-bad {
    background: color-mix(in srgb, var(--danger, #d64545) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger, #d64545) 40%, transparent);
  }
  .mh-causes summary { cursor: pointer; font-size: 12.5px; color: var(--text-secondary, #9aa3b2); }
  .mh-causes ul { margin: 6px 0 0; padding-left: 18px; font-size: 12.5px; }
  .mh-refresh { margin-top: 2px; }
</style>
