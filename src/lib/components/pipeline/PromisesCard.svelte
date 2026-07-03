<script>
  /**
   * E4 (2026-07-03): карточка «Сбывшиеся рекомендации» — прогнозы-обещания.
   *
   * Замыкает петлю доверия: зафиксированный прогноз («Зафиксировать прогноз»
   * у результата планирования) сверяется со свежим фактом, когда клиент
   * приносит новые данные. Вердикты честные: «сбылось» и «не сбылось»
   * одинаково заметны; «не сбылось» всегда с оговоркой, что это сверка
   * прогноза, а не каузальный вывод.
   *
   * @component PromisesCard
   */
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { activeProjectId } from '$lib/project-state.js';
  import { ClipboardCheck, RefreshCw, TriangleAlert } from 'lucide-svelte';

  /** @type {'loading' | 'empty' | 'ready' | 'error'} */
  let cardState = $state('loading');
  /** @type {any[]} */
  let promises = $state([]);
  /** @type {string | null} */
  let message = $state(null);
  let checking = $state(false);

  const TONES = /** @type {Record<string, string>} */ ({
    kept: 'ok',
    missed: 'bad',
    pending: 'quiet',
    inconclusive: 'warn',
  });

  async function projectDir() {
    const projectId = get(activeProjectId);
    if (!projectId) return null;
    return /** @type {string} */ (await invoke('project_get_dir', { projectId }));
  }

  async function reload() {
    try {
      const dir = await projectDir();
      if (!dir) { cardState = 'empty'; return; }
      const res = /** @type {any} */ (await invoke('econ_promises_list', { projectDir: dir }));
      promises = Array.isArray(res?.promises) ? res.promises : [];
      cardState = promises.length ? 'ready' : 'empty';
    } catch {
      cardState = 'empty';
    }
  }

  onMount(() => { void reload(); });

  async function checkNow() {
    checking = true;
    message = null;
    try {
      const dir = await projectDir();
      if (!dir) return;
      const res = /** @type {any} */ (await invoke('econ_promises_check', { projectDir: dir }));
      if (res?.status === 'ok') {
        promises = res.promises ?? [];
        cardState = promises.length ? 'ready' : 'empty';
      } else {
        message = res?.message || 'Сверка не удалась.';
        cardState = 'error';
      }
    } catch (/** @type {any} */ e) {
      message = String(e);
      cardState = 'error';
    } finally {
      checking = false;
    }
  }

  /** @param {string} iso */
  function fmtDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('ru-RU');
  }
  /** @param {number | null | undefined} v */
  function fmtNum(v) {
    return v == null ? '—' : Number(v).toLocaleString('ru-RU', { maximumFractionDigits: 0 });
  }
</script>

<section class="pr-card" aria-label="Сбывшиеся рекомендации">
  <header class="pr-header">
    <span class="pr-icon" aria-hidden="true"><ClipboardCheck size={18} strokeWidth={1.6} /></span>
    <div>
      <h3 class="pr-title">Сбывшиеся рекомендации</h3>
      <p class="pr-subtitle">
        Каждый зафиксированный прогноз — проверяемое обещание: принесите свежие
        данные, и продукт сам сверит факт с ожиданием.
      </p>
    </div>
  </header>

  {#if cardState === 'loading'}
    <p class="pr-quiet" role="status">Загрузка…</p>
  {:else if cardState === 'empty'}
    <p class="pr-quiet">
      Прогнозов пока не зафиксировано. Кнопка «Зафиксировать прогноз» — у
      результата планирования (блок «Что если», режим «Планирование»).
    </p>
  {:else if cardState === 'error'}
    <div class="pr-banner pr-bad" role="alert">
      <TriangleAlert size={16} strokeWidth={1.6} aria-hidden="true" />
      <span>{message}</span>
      <button class="pr-btn-sm" onclick={checkNow}>Повторить</button>
    </div>
  {:else}
    <ul class="pr-list">
      {#each promises as p (p.id)}
        <li class="pr-row">
          <div class="pr-row-top">
            <span class="pr-action">{p.action_text}</span>
            <span class="pr-badge pr-{TONES[p.status] ?? 'quiet'}" data-testid="pr-status">
              {p.status_ru}
            </span>
          </div>
          <div class="pr-row-meta">
            {fmtDate(p.created_at)} · ожидание {fmtNum(p.expected?.kpi_total)}
            {#if p.expected?.ci_low != null && p.expected?.ci_high != null}
              [{fmtNum(p.expected.ci_low)} – {fmtNum(p.expected.ci_high)}]
            {/if}
            за {p.expected?.horizon_periods} пер.
            {#if p.extrapolation_flag}
              <span class="pr-extra" title="Прогноз в зоне экстраполяции — интервал шире обычного">⚠ экстраполяция</span>
            {/if}
            {#if p.actual_kpi_total != null}
              · факт {fmtNum(p.actual_kpi_total)}
            {/if}
          </div>
          {#if p.verdict_note}
            <div class="pr-note">{p.verdict_note}</div>
          {/if}
        </li>
      {/each}
    </ul>
    <button class="pr-btn" onclick={checkNow} disabled={checking}>
      <RefreshCw size={14} strokeWidth={1.7} aria-hidden="true" />
      {checking ? 'Сверяем…' : 'Сверить с фактом'}
    </button>
  {/if}
</section>

<style>
  .pr-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px 18px;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.04));
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.12));
    border-radius: 10px;
  }
  .pr-header { display: flex; gap: 10px; align-items: flex-start; }
  .pr-icon { margin-top: 2px; opacity: 0.8; }
  .pr-title { margin: 0; font-size: 15px; font-weight: 600; }
  .pr-subtitle { margin: 4px 0 0; font-size: 12.5px; line-height: 1.45; color: var(--text-secondary, #9aa3b2); }
  .pr-quiet { font-size: 13px; color: var(--text-secondary, #9aa3b2); margin: 0; }
  .pr-banner { display: flex; gap: 8px; align-items: center; padding: 10px 12px; border-radius: 8px; font-size: 13px; }
  .pr-bad {
    background: color-mix(in srgb, var(--danger, #d64545) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger, #d64545) 35%, transparent);
  }
  .pr-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 10px; }
  .pr-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 12px;
    border-radius: 8px;
    background: var(--bg-surface-focus, rgba(255, 255, 255, 0.05));
  }
  .pr-row-top { display: flex; gap: 10px; align-items: baseline; justify-content: space-between; }
  .pr-action { font-size: 13px; font-weight: 600; }
  .pr-badge {
    flex-shrink: 0;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
  }
  .pr-ok {
    background: color-mix(in srgb, var(--success, #2f9e63) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #2f9e63) 40%, transparent);
  }
  .pr-bad.pr-badge, .pr-badge.pr-bad {
    background: color-mix(in srgb, var(--danger, #d64545) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger, #d64545) 40%, transparent);
  }
  .pr-warn {
    background: color-mix(in srgb, var(--warning, #d9a514) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #d9a514) 40%, transparent);
  }
  .pr-quiet.pr-badge, .pr-badge.pr-quiet {
    background: var(--bg-surface-focus, rgba(255, 255, 255, 0.08));
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.16));
  }
  .pr-row-meta { font-size: 12px; color: var(--text-secondary, #9aa3b2); }
  .pr-extra { color: var(--warning, #d9a514); }
  .pr-note { font-size: 12px; line-height: 1.4; }
  .pr-btn, .pr-btn-sm {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    align-self: flex-start;
    padding: 8px 13px;
    border-radius: 8px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.16));
    background: var(--bg-surface-focus, rgba(255, 255, 255, 0.08));
    color: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .pr-btn-sm { padding: 5px 10px; font-size: 12px; }
  .pr-btn:hover:not(:disabled), .pr-btn-sm:hover { filter: brightness(1.15); }
  .pr-btn:disabled { opacity: 0.6; cursor: default; }
</style>
