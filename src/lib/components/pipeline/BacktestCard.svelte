<script>
  /**
   * E1 (2026-07-03): карточка «Проверка модели на истории» (backtest-витрина).
   *
   * Rolling-origin «модель vs факт»: модель переобучается на исторических
   * окнах и предсказывает удержанные кварталы против факта. Главные числа:
   * «X из Y кварталов в 90%-интервале» + MAPE против наивного прогноза.
   * Витрина хранится в models/backtest.json; при монтировании читается
   * мгновенно (read_only), пересчёт — только по кнопке (минуты для
   * байесовской модели — честно предупреждаем).
   *
   * Честность: вердикты worse_than_naive / coverage_low показываются так же
   * заметно, как validated — витрина существует, чтобы НЕ льстить модели.
   *
   * @component BacktestCard
   */
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { activeProjectId } from '$lib/project-state.js';
  import { History, TriangleAlert, RefreshCw } from 'lucide-svelte';

  /** @type {'loading' | 'empty' | 'running' | 'done' | 'insufficient' | 'error'} */
  let cardState = $state('loading');
  /** @type {any | null} */
  let vitrina = $state(null);
  /** @type {string | null} */
  let message = $state(null);

  /** Вердикт-презентация: цвет + русский ярлык.
   * @type {Record<string, { label: string, tone: string }>} */
  const VERDICTS = {
    validated: { label: 'Модель подтверждена на истории', tone: 'ok' },
    coverage_low: { label: 'Интервалы модели самоуверенны', tone: 'warn' },
    worse_than_naive: { label: 'Модель не точнее наивного прогноза', tone: 'bad' },
  };

  const verdictView = $derived.by(() => {
    const v = vitrina?.verdict;
    return (v && VERDICTS[v]) || null;
  });

  /** «Кварталов» для окон-кварталов (M×3, W×13, D×90), иначе «окон проверки». */
  const windowsWord = $derived.by(() => {
    const g = vitrina?.granularity;
    const h = vitrina?.horizon_periods;
    const isQuarter = (g === 'M' && h === 3) || (g === 'W' && h === 13) || (g === 'D' && h === 90);
    return isQuarter ? 'кварталов' : 'окон проверки';
  });

  /** Модель переобучена ПОСЛЕ построения витрины → результат устарел. */
  const isStale = $derived.by(() => {
    const was = vitrina?.model_trained_at;
    const now = vitrina?.model_trained_at_current;
    return Boolean(was && now && now > was);
  });

  /** Выигрыш у наивного в процентах (положительный = модель точнее). */
  const naiveGainPct = $derived.by(() => {
    const m = vitrina?.mape_model;
    const n = vitrina?.mape_naive_best;
    if (m == null || n == null || n <= 0) return null;
    return (1 - m / n) * 100;
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
        const saved = /** @type {any} */ (await invoke('econ_backtest', {
          projectDir: dir, readOnly: true,
        }));
        if (saved?.status === 'ok') {
          vitrina = saved;
          cardState = 'done';
        } else {
          cardState = 'empty';
        }
      } catch {
        // Чтение витрины — необязательный путь: тихо показываем кнопку.
        cardState = 'empty';
      }
    })();
  });

  async function runBacktest() {
    cardState = 'running';
    message = null;
    try {
      const dir = await projectDir();
      if (!dir) {
        cardState = 'error';
        message = 'Проект не найден — переоткройте проект и повторите.';
        return;
      }
      const res = /** @type {any} */ (await invoke('econ_backtest', { projectDir: dir }));
      if (res?.status === 'ok') {
        vitrina = res;
        cardState = 'done';
      } else if (res?.status === 'insufficient') {
        message = res.message;
        cardState = 'insufficient';
      } else {
        message = res?.message || 'Проверка на истории не удалась.';
        cardState = 'error';
      }
    } catch (/** @type {any} */ e) {
      message = String(e);
      cardState = 'error';
    }
  }

  /** @param {number | null | undefined} v */
  function fmtPct(v) {
    return v == null ? '—' : `${(v * 100).toFixed(0)}%`;
  }
  /** @param {number | null | undefined} v */
  function fmtNum(v) {
    return v == null ? '—' : Number(v).toLocaleString('ru-RU', { maximumFractionDigits: 0 });
  }
</script>

<section class="backtest-card" aria-label="Проверка модели на истории">
  <header class="bt-header">
    <span class="bt-icon" aria-hidden="true"><History size={18} strokeWidth={1.6} /></span>
    <div class="bt-title-block">
      <h3 class="bt-title">Проверка на истории</h3>
      <p class="bt-subtitle">
        Модель переобучается на прошлом и предсказывает удержанные кварталы —
        затем прогноз сверяется с фактом. Это честный экзамен «вне выборки».
      </p>
    </div>
  </header>

  {#if cardState === 'loading'}
    <p class="bt-quiet" role="status">Загрузка сохранённой проверки…</p>

  {:else if cardState === 'empty'}
    <div class="bt-empty">
      <p class="bt-quiet">
        Проверка ещё не проводилась. Модель будет переобучена до 8 раз на
        исторических окнах: для байесовской модели это несколько минут,
        для OLS — меньше минуты.
      </p>
      <button class="bt-run" onclick={runBacktest}>Проверить модель на истории</button>
    </div>

  {:else if cardState === 'running'}
    <div class="bt-running" role="status" aria-busy="true">
      <span class="bt-spinner" aria-hidden="true"><RefreshCw size={16} strokeWidth={1.6} /></span>
      Проверяем: модель переобучается на исторических окнах… Для байесовской
      модели это несколько минут — можно продолжать работу в других шагах.
    </div>

  {:else if cardState === 'insufficient'}
    <div class="bt-banner bt-warn" role="note">
      <TriangleAlert size={16} strokeWidth={1.6} aria-hidden="true" />
      <span>{message}</span>
    </div>

  {:else if cardState === 'error'}
    <div class="bt-banner bt-bad" role="alert">
      <TriangleAlert size={16} strokeWidth={1.6} aria-hidden="true" />
      <span>{message}</span>
      <button class="bt-retry" onclick={runBacktest}>Повторить</button>
    </div>

  {:else if cardState === 'done' && vitrina}
    {#if isStale}
      <div class="bt-banner bt-warn" role="note">
        <TriangleAlert size={16} strokeWidth={1.6} aria-hidden="true" />
        <span>Модель переобучена после этой проверки — результат устарел.
        Запустите проверку заново.</span>
        <button class="bt-retry" onclick={runBacktest}>Обновить</button>
      </div>
    {/if}

    {#if verdictView}
      <div class="bt-verdict bt-{verdictView.tone}" data-testid="bt-verdict">
        {verdictView.label}
      </div>
    {/if}

    <div class="bt-hero">
      {#if vitrina.windows_hit_total != null && vitrina.windows_with_interval}
        <div class="bt-hero-num" data-testid="bt-hero">
          {vitrina.windows_hit_total} из {vitrina.windows_with_interval}
        </div>
        <div class="bt-hero-caption">
          {windowsWord} — факт внутри 90%-интервала прогноза
        </div>
      {:else}
        <div class="bt-hero-caption">
          Интервалы прогноза для этой модели недоступны — сверка по точности ниже.
        </div>
      {/if}
    </div>

    <ul class="bt-facts">
      <li>
        Средняя ошибка прогноза (MAPE): <b>{vitrina.mape_model?.toFixed(1)}%</b>
        {#if vitrina.mape_naive_best != null}
          — наивный прогноз: {vitrina.mape_naive_best.toFixed(1)}%{#if naiveGainPct != null && naiveGainPct > 0},
            модель точнее на <b>{naiveGainPct.toFixed(0)}%</b>{/if}
        {/if}
      </li>
      {#if vitrina.coverage_per_period != null}
        <li>
          Покрытие по отдельным периодам: {fmtPct(vitrina.coverage_per_period)}
          ({vitrina.n_holdout_points_with_interval} точек, норма ≈ 90%)
        </li>
      {/if}
      <li class="bt-quiet-li">{vitrina.verdict_text}</li>
    </ul>

    <details class="bt-details">
      <summary>Окна проверки ({vitrina.n_windows})</summary>
      <table class="bt-table">
        <thead>
          <tr>
            <th>Период</th><th>Факт</th><th>Прогноз</th><th>90%-интервал</th><th>Попадание</th>
          </tr>
        </thead>
        <tbody>
          {#each vitrina.windows as w (w.window)}
            <tr>
              <td>{w.window}</td>
              <td>{fmtNum(w.actual_total)}</td>
              <td>{fmtNum(w.predicted_total)}</td>
              <td>
                {#if w.pi_low_total != null}
                  {fmtNum(w.pi_low_total)} – {fmtNum(w.pi_high_total)}
                {:else}—{/if}
              </td>
              <td class="bt-hit">{w.hit_total === null ? '—' : w.hit_total ? '✓' : '✕'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p class="bt-method">
        Метод: скользящее обучение без подглядывания в будущее
        ({vitrina.n_windows} окон по {vitrina.horizon_periods} периодов);
        интервалы — {vitrina.pi_method === 'posterior_predictive_90' ? 'байесовские 90% предиктивные (параметры + шум наблюдения)'
          : vitrina.pi_method === 'posterior_hdi_90_mean_only' ? 'байесовские 90% только по средней (шум наблюдения недоступен)'
          : vitrina.pi_method === 'conformal_90' ? 'конформные 90%' : 'приближение по остаткам (90%)'}.
      </p>
      <button class="bt-rerun" onclick={runBacktest}>Повторить проверку</button>
    </details>
  {/if}
</section>

<style>
  .backtest-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px 18px;
    background: var(--bg-surface-quiet, rgba(255, 255, 255, 0.04));
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.12));
    border-radius: 10px;
  }
  .bt-header {
    display: flex;
    gap: 10px;
    align-items: flex-start;
  }
  .bt-icon { margin-top: 2px; opacity: 0.8; }
  .bt-title { margin: 0; font-size: 15px; font-weight: 600; }
  .bt-subtitle {
    margin: 4px 0 0;
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--text-secondary, #9aa3b2);
  }
  .bt-quiet { font-size: 13px; color: var(--text-secondary, #9aa3b2); margin: 0; }
  .bt-empty { display: flex; flex-direction: column; gap: 10px; }
  .bt-run, .bt-retry, .bt-rerun {
    align-self: flex-start;
    padding: 8px 14px;
    border-radius: 8px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.16));
    background: var(--bg-surface-focus, rgba(255, 255, 255, 0.08));
    color: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .bt-run:hover, .bt-retry:hover, .bt-rerun:hover { filter: brightness(1.15); }
  .bt-running {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 13px;
    color: var(--text-secondary, #9aa3b2);
  }
  .bt-spinner { animation: bt-spin 1.2s linear infinite; display: inline-flex; }
  @keyframes bt-spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) {
    .bt-spinner { animation: none; }
  }
  .bt-banner {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 10px 12px;
    border-radius: 8px;
    font-size: 13px;
  }
  .bt-warn {
    background: color-mix(in srgb, var(--warning, #d9a514) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #d9a514) 35%, transparent);
  }
  .bt-bad {
    background: color-mix(in srgb, var(--danger, #d64545) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger, #d64545) 35%, transparent);
  }
  .bt-verdict {
    align-self: flex-start;
    padding: 5px 12px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 600;
  }
  .bt-verdict.bt-ok {
    background: color-mix(in srgb, var(--success, #2f9e63) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #2f9e63) 40%, transparent);
  }
  .bt-verdict.bt-warn {
    background: color-mix(in srgb, var(--warning, #d9a514) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #d9a514) 40%, transparent);
  }
  .bt-verdict.bt-bad {
    background: color-mix(in srgb, var(--danger, #d64545) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger, #d64545) 40%, transparent);
  }
  .bt-hero { display: flex; flex-direction: column; gap: 2px; }
  .bt-hero-num { font-size: 28px; font-weight: 700; line-height: 1.1; }
  .bt-hero-caption { font-size: 12.5px; color: var(--text-secondary, #9aa3b2); }
  .bt-facts {
    margin: 0;
    padding-left: 18px;
    font-size: 13px;
    line-height: 1.55;
  }
  .bt-quiet-li { color: var(--text-secondary, #9aa3b2); }
  .bt-details summary {
    cursor: pointer;
    font-size: 13px;
    color: var(--text-secondary, #9aa3b2);
  }
  .bt-table {
    width: 100%;
    margin-top: 8px;
    border-collapse: collapse;
    font-size: 12.5px;
  }
  .bt-table th, .bt-table td {
    padding: 5px 8px;
    text-align: left;
    border-bottom: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  }
  .bt-hit { text-align: center; }
  .bt-method {
    margin: 8px 0 0;
    font-size: 12px;
    color: var(--text-secondary, #9aa3b2);
  }
  .bt-rerun { margin-top: 10px; }
</style>
