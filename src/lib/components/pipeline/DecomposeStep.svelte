<script>
  /**
   * Step 3: Sales Decomposition.
   * B2: auto-runs on mount if no decomposeData yet.
   * Layout: insight banner → waterfall (full width) → grid: ROI (50%) | timeline (50%).
   * Note: scroll владеет .pipeline-main, не сам компонент (см. +page.svelte).
   * @component DecomposeStep
   */
  import { onMount } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import {
    activeProjectId,
    decomposeData,
    modelData,
    completeStep,
    setStepError,
    isComputing,
    computeStatus,
    expertMode,
    unitCosts,
  } from '$lib/project-state.js';
  import WaterfallChart from '$lib/components/pipeline/WaterfallChart.svelte';
  import ROIComparison from '$lib/components/pipeline/ROIComparison.svelte';
  import ExpertDecomposePanel from '$lib/components/pipeline/ExpertDecomposePanel.svelte';
  import ChannelTimeline from '$lib/components/pipeline/ChannelTimeline.svelte';
  import TrustBanner from '$lib/components/pipeline/TrustBanner.svelte';
  import ExpandableCard from '$lib/components/ExpandableCard.svelte';
  import PipelineOnboarding from '$lib/components/pipeline/PipelineOnboarding.svelte';
  import { TOURS } from '$lib/pipeline-tours.js';
  import { shouldShowOnboarding } from '$lib/onboarding-state.js';

  let showOnboarding = $state(false);
  let onboardingChecked = false;
  $effect(() => {
    if (typeof window === 'undefined') return;
    if (onboardingChecked) return;
    // Запускаем только когда decompose data отрендерилась (ждём data из store)
    const d = $decomposeData;
    if (!d || !d.channels || d.channels.length === 0) return;
    onboardingChecked = true;
    if (shouldShowOnboarding('decompose')) {
      requestAnimationFrame(() => { showOnboarding = true; });
    }
  });

  /** @type {Record<string, string>} */
  const CATEGORY_LABEL = {
    brand_reach: 'Brand-Reach',
    performance: 'Performance',
    mixed: 'Mixed',
  };

  /** @type {Record<string, string>} */
  const CATEGORY_HELP = {
    brand_reach: 'Brand-Reach — охватные каналы (TV/TRPs/OOH/радио), работают на долгосрочный brand-эффект.\n\nЧто это: строят знание и доверие к бренду, влияние раскрывается месяцами.\n\nКак читать: ROI интерпретируй как «вклад в базу + короткий эффект», не чистый инкремент. Сравнивай только с другими Brand-Reach каналами.',
    performance: 'Performance — каналы прямого отклика (Digital/Search/Social/контекст), работают на короткий инкремент.\n\nЧто это: закрывают спрос здесь и сейчас, эффект виден в пределах недель.\n\nКак читать: ROI — чистая отдача на рубль. Сравнивай с другими Performance каналами.',
    mixed: 'Mixed — канал не однозначно классифицирован (нет явных маркеров brand/performance в имени).\n\nКак читать: смотри на тип контента и цель размещения — он может работать и на охват, и на отклик.',
  };

  /** @type {'idle' | 'loading' | 'done' | 'error'} */
  let stepState = $state('idle');
  /** @type {string | null} */
  let errorMessage = $state(null);

  const data = $derived($decomposeData);

  // Help-tooltips для основной таблицы «Детализация по каналам».
  const CH_HELP = {
    spend:   'Расходы — суммарный бюджет канала за весь период анализа.\n\nПочему важно: основа для ROI и доли бюджета. Если канал не в рублях (TRP, показы) — ROI будет искажён.',
    contrib: 'Вклад — оценка дополнительных продаж от канала (в денежной валюте KPI).\n\nПочему важно: вклад ÷ расход = ROI. Это и есть «деньги, которые принесла реклама поверх базовых продаж».',
    roi:     'ROI = вклад ÷ расход. Сколько рублей продаж приносит каждый вложенный рубль.\n\nROI ≥ 2× — отлично. 1-2× — окупается. < 1× — убыточен.\n\nВнимание: ROI > 50× обычно означает, что данные канала не в рублях (TRP, показы, клики) — нужна нормализация.',
    gap:     'Gap = % эффекта − % бюджета. Разрыв между долей вклада и долей бюджета.\n\n+10% и выше: канал работает сильно эффективнее своей доли бюджета — кандидат на докрутку.\n0 ± 5%: сбалансирован.\n−10% и ниже: канал перенасыщен — каждый дополнительный рубль даёт меньше отдачи.',
    verdict: 'Вердикт — комбинированная оценка по ROI и Gap.\n\n«Высокоэффективен / Эффективен» — приносит больше своей доли бюджета.\n«Сбалансирован» — окупается, доли совпадают.\n«Слабее своей доли / Перенасыщен» — приносит меньше, чем потребляет бюджета.\n«На грани окупаемости / Убыточный» — ROI ≤ 1×.\n«ROI завышен (не рубли?)» — данные канала не в денежных единицах.',
  };

  /** Дожидаемся, пока projectId станет валидным (макс. 2с), потом отдаём. */
  function waitForProjectId(timeoutMs = 2000) {
    return new Promise(/** @param {(id: string|null) => void} resolve */ (resolve) => {
      const current = get(activeProjectId);
      if (current) { resolve(current); return; }
      const timer = setTimeout(() => { unsub(); resolve(get(activeProjectId)); }, timeoutMs);
      const unsub = activeProjectId.subscribe((pid) => {
        if (pid) { clearTimeout(timer); unsub(); resolve(pid); }
      });
    });
  }

  /** Дожидаемся projectId через store + fallback на backend (как в OptimizeStep). */
  async function ensureProjectId() {
    let pid = await waitForProjectId(2000);
    if (pid) return pid;
    try {
      pid = /** @type {string|null} */ (await invoke('project_get_active'));
      if (pid) { activeProjectId.set(pid); return pid; }
    } catch { /* нет активного */ }
    return null;
  }

  /**
   * @param {number} [attemptsLeft] - Делаем до 4 попыток с возрастающим backoff
   *        (1.5/2/3с) чтобы дождаться pickle после свежей тренировки. Дефолт = 4
   *        принудительно (не полагаемся на event-arg от onclick).
   */
  async function runDecompose(attemptsLeft) {
    if (typeof attemptsLeft !== 'number' || !Number.isFinite(attemptsLeft)) attemptsLeft = 4;

    const projectId = await ensureProjectId();
    if (!projectId) { errorMessage = 'Проект не выбран'; stepState = 'error'; return; }

    stepState = 'loading';
    isComputing.set(true);
    computeStatus.set('Декомпозиция продаж...');
    errorMessage = null;

    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId }));
      // Trust Level 2: override unit_costs из store (если user менял CPP после train,
      // pickle содержит старые значения — override даёт актуальные).
      const result = /** @type {any} */ (await invoke('econ_decompose', {
        projectDir,
        unitCosts: get(unitCosts) ?? {},
      }));

      if (result.status === 'ok') {
        decomposeData.set(result);
        stepState = 'done';
        completeStep(3);
      } else {
        const msg = result.message || 'Ошибка декомпозиции';
        // Авто-retry на race «Модель не найдена» — pickle ещё пишется async.
        const isModelMissing = /модель не найдена|model not found|не найден|not found|pickle|latest\.pkl/i.test(msg);
        if (attemptsLeft > 1 && isModelMissing) {
          const delay = [1500, 2000, 3000][4 - attemptsLeft] || 3000;
          isComputing.set(false);
          computeStatus.set(`Жду готовность модели (попытка ${5 - attemptsLeft + 1}/4)...`);
          await new Promise(r => setTimeout(r, delay));
          isComputing.set(true);
          await runDecompose(attemptsLeft - 1);
          return;
        }
        handleError(msg);
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    } finally {
      isComputing.set(false);
      computeStatus.set('');
    }
  }

  /** @param {string} msg */
  function handleError(msg) {
    errorMessage = msg;
    stepState = 'error';
    setStepError(3, msg);
    // isComputing/computeStatus cleared in finally block
  }

  // Bug 2: activeProjectId гидрируется асинхронно из localStorage/IPC после mount.
  // Если запустить runDecompose синхронно в onMount — projectId === null,
  // показывается «Проект не выбран». Подписываемся и ждём первого валидного значения.
  // (Bug 1 со scroll-позицией решается в +layout.svelte — сбрасывается .pipeline-main.scrollTop при смене шага.)
  //
  // Также: если data уже есть в memory (вернулись на шаг через stepper) —
  // просто показываем done и не запускаем ничего, fallback тоже не нужен.
  onMount(() => {
    // Сбрасываем устаревший errorMessage в локальном state и в pipelineMeta —
    // иначе старая ошибка от прошлой попытки видна до того как retry отработает.
    errorMessage = null;
    if (get(decomposeData)) {
      stepState = 'done';
      return;
    }

    // ВАЖНО: все 6 step компонентов mount'ятся одновременно (см. +page.svelte
    // rule "visibility switching"). DecomposeStep mount'ится даже когда user
    // на Validate/Model. Guard — не запускать runDecompose пока нет обученной
    // модели. $effect(modelData) автоматически запустит когда train завершится.
    if (!get(modelData)?.channelParams) {
      stepState = 'idle';
      return;
    }

    let started = false;
    const unsub = activeProjectId.subscribe((pid) => {
      if (started) return;
      if (!pid) return; // ждём пока projectId станет валидным
      started = true;
      (async () => {
        // повторная проверка — за время ожидания pid могли подгрузиться данные
        if (!get(decomposeData)) {
          await runDecompose();
        } else {
          stepState = 'done';
        }
      })();
    });

    // Fallback: если projectId так и не появился за 3с И данных нет И модель ЕСТЬ —
    // показываем ошибку. Если модели нет — просто idle, ждём train.
    const fallback = setTimeout(() => {
      if (started) return;
      if (get(decomposeData)) {
        started = true;
        stepState = 'done';
        return;
      }
      if (!get(modelData)?.channelParams) {
        started = true;
        stepState = 'idle';
        return;
      }
      started = true;
      errorMessage = 'Проект не выбран';
      stepState = 'error';
    }, 3000);

    return () => {
      unsub();
      clearTimeout(fallback);
    };
  });

  // Авто-ретрай когда прилетела новая тренировка (pickle всегда latest.pkl,
  // поэтому сравниваем по object-reference modelData — каждый set() даёт
  // новый object). Срабатывает:
  //   • при error «Модель не найдена» (исправляется автоматом)
  //   • при idle без данных (первое открытие после train)
  //   • при done (пользователь перетренировал → декомпозиция устарела)
  /** @type {any} */
  let lastModelRef = null;
  $effect(() => {
    const md = $modelData;
    // Не триггерим при первом получении пустого state.
    if (!md?.channelParams) return;
    if (md === lastModelRef) return;
    const firstFire = lastModelRef === null;
    lastModelRef = md;
    // При первом запуске onMount уже отработал:
    //   • если onMount увидел channelParams → он вызвал runDecompose, skipping $effect здесь.
    //   • если onMount увидел idle (channelParams появились ПОСЛЕ mount через async train) →
    //     $effect должен запустить runDecompose, т.к. onMount уже ушёл в 'idle' и return;
    // Race, исправленный в rc1.5: раньше firstFire всегда skipping привело к пустой decompose
    // если DecomposeStep mount'ился до завершения train (типичный pipeline-first flow).
    if (firstFire && stepState !== 'idle' && stepState !== 'error') return;
    // Защита от race: если уже идёт runDecompose — не запускаем второй параллельно.
    if (stepState === 'loading') return;
    errorMessage = null;
    // Сбросим decomposeData — старая модель → старые результаты.
    if (stepState === 'done') decomposeData.set(null);
    runDecompose();
  });
</script>

<div class="decompose-step">

  <!-- Loading state -->
  {#if stepState === 'loading'}
    <div class="loading-banner">
      <div class="spinner"></div>
      <span>Анализирую вклад каналов...</span>
    </div>
  {/if}

  <!-- Error banner -->
  {#if stepState === 'error' && errorMessage}
    <div class="error-banner">
      <span class="error-icon">⚠</span>
      <span class="error-text">{errorMessage}</span>
      <button class="btn-retry" onclick={() => runDecompose()}>Повторить</button>
    </div>
  {/if}

  <!-- Results -->
  {#if stepState === 'done' && data}

    <!-- Trust banner (smell_flags) -->
    {#if data.smell_flags?.length}
      <TrustBanner flags={data.smell_flags} />
    {/if}

    <!-- Insight banner -->
    {#if data.insight}
      <div class="insight-banner">
        <span class="insight-icon">💡</span>
        <p class="insight-text">{data.insight}</p>
        <button class="btn-rerun" onclick={() => runDecompose()} title="Пересчитать">↺</button>
      </div>
    {/if}

    <!-- Waterfall — full width -->
    <ExpandableCard title="Декомпозиция продаж" tourKey="decompose-waterfall">
      <WaterfallChart waterfall={data.waterfall} />
    </ExpandableCard>

    <!-- Two-column: ROI | Timeline -->
    <div class="charts-grid">
      <ExpandableCard title="Расходы vs Эффект" tourKey="decompose-roi">
        <ROIComparison channels={data.channels} />
      </ExpandableCard>
      <ExpandableCard title="Динамика по периодам" tourKey="decompose-timeline">
        {#if data.time_series?.dates?.length}
          <ChannelTimeline timeSeries={data.time_series} />
        {:else}
          <div class="no-data">Нет данных для временного ряда</div>
        {/if}
      </ExpandableCard>
    </div>

    <!-- Channel table -->
    <div class="card" data-tour="decompose-table">
      <div class="card-title">Детализация по каналам</div>
      <div class="channel-table">
        <table>
          <colgroup>
            <col style="width: 28%" />
            <col style="width: 16%" />
            <col style="width: 18%" />
            <col style="width: 11%" />
            <col style="width: 10%" />
            <col style="width: 17%" />
          </colgroup>
          <thead>
            <tr>
              <th>Канал</th>
              <th class="num">Расходы<span class="help-icon" title={CH_HELP.spend}>?</span></th>
              <th class="num">Вклад<span class="help-icon" title={CH_HELP.contrib}>?</span></th>
              <th class="num">ROI<span class="help-icon" title={CH_HELP.roi}>?</span></th>
              <th class="num">Gap<span class="help-icon" title={CH_HELP.gap}>?</span></th>
              <th class="num">Decay<span class="help-icon" title="Adstock decay — доля медиа-эффекта переносимая на следующий период. 0 = моментальный эффект (1 период), 0.7 ≈ 3-4 периода эффективной длительности (long brand). 50% CI показывает posterior uncertainty (Trust Level 3, v1.1.0).">?</span></th>
              <th>Вердикт<span class="help-icon" title={CH_HELP.verdict}>?</span></th>
            </tr>
          </thead>
          <tbody>
            {#each ['brand_reach', 'performance', 'mixed'] as groupKey}
              {@const groupChannels = data.channels.filter(/** @param {any} c */ c => (c.category || 'mixed') === groupKey)}
              {#if groupChannels.length > 0}
                <!-- Trust Level 3 (v1.1.0): visual grouping per category -->
                <tr class="group-header" class:gh-brand={groupKey === 'brand_reach'} class:gh-perf={groupKey === 'performance'} class:gh-mixed={groupKey === 'mixed'}>
                  <td colspan="7">
                    {#if groupKey === 'brand_reach'}🎯 Brand-каналы — long-decay (TV/TRPs/OOH){:else if groupKey === 'performance'}📊 Performance-каналы — short-decay (Search/Social){:else}⚪ Смешанные (single-prior){/if}
                    <span class="group-count">{groupChannels.length}</span>
                  </td>
                </tr>
                {#each groupChannels as ch}
                  <tr>
                    <td class="ch-name">
                      {ch.name}
                      {#if ch.category}
                        <span
                          class="ch-cat"
                          class:cat-brand={ch.category === 'brand_reach'}
                          class:cat-perf={ch.category === 'performance'}
                          class:cat-mixed={ch.category === 'mixed'}
                          title={CATEGORY_HELP[ch.category]}
                        >{CATEGORY_LABEL[ch.category]}</span>
                      {/if}
                    </td>
                    <td class="num" title={ch.unit_cost && ch.unit_cost !== 1 ? `${(ch.raw_spend ?? 0).toLocaleString('ru-RU')} юнитов × ${ch.unit_cost.toLocaleString('ru-RU')}₽ = ${ch.spend.toLocaleString('ru-RU')}₽` : ''}>
                      {ch.spend.toLocaleString('ru-RU')}
                      {#if ch.unit_cost && ch.unit_cost !== 1}
                        <span class="spend-sub">{(ch.raw_spend ?? 0).toLocaleString('ru-RU')} × {ch.unit_cost.toLocaleString('ru-RU')}₽</span>
                      {/if}
                    </td>
                    <td class="num">{ch.contribution.toLocaleString('ru-RU')}</td>
                    <td class="num" class:roi-good={ch.roi > 2 && ch.roi <= 50} class:roi-mid={ch.roi >= 0.8 && ch.roi <= 2} class:roi-bad={ch.roi < 0.8} class:roi-warn={ch.roi > 50}>
                      {ch.roi.toFixed(2)}×
                    </td>
                    <td class="num" class:gap-pos={ch.efficiency_gap >= 5} class:gap-neg={ch.efficiency_gap <= -5}>
                      {ch.efficiency_gap > 0 ? '+' : ''}{ch.efficiency_gap}%
                    </td>
                    <td class="num decay-cell">
                      {#if ch.adstock_decay_mean != null}
                        {ch.adstock_decay_mean.toFixed(2)}
                        {#if ch.adstock_decay_ci_low != null && ch.adstock_decay_ci_high != null}
                          <span class="decay-ci">{ch.adstock_decay_ci_low.toFixed(2)}–{ch.adstock_decay_ci_high.toFixed(2)}</span>
                        {/if}
                      {:else}
                        —
                      {/if}
                    </td>
                    <td class:verdict-good={ch.verdict_tone === 'good'} class:verdict-warn={ch.verdict_tone === 'warn'} class:verdict-bad={ch.verdict_tone === 'bad'}>
                      {ch.verdict}
                    </td>
                  </tr>
                {/each}
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    </div>

  {/if}

  {#if $expertMode}
    <ExpertDecomposePanel />
  {/if}

  {#if showOnboarding}
    <PipelineOnboarding
      steps={TOURS.decompose}
      stepKey="decompose"
      onDone={() => { showOnboarding = false; }}
    />
  {/if}

</div>

<style>
  .decompose-step {
    /* Скрол владеет .pipeline-main (см. +page.svelte). Здесь — никаких
       overflow-y / height: 100%, иначе двойной скрол + фантомное пустое
       пространство снизу (баг найден 2026-04-19). */
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 0;
    box-sizing: border-box;
  }

  .loading-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 18px 20px;
    background: color-mix(in srgb, var(--accent-primary) 6%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 15%, transparent);
    border-radius: 10px;
    color: var(--text-secondary, #94a3b8);
    font-size: 14px;
  }

  .spinner {
    width: 20px;
    height: 20px;
    border: 2px solid color-mix(in srgb, var(--accent-primary) 30%, transparent);
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .error-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
    border-radius: 10px;
    flex-wrap: wrap;
  }
  .error-icon { font-size: 16px; flex-shrink: 0; }
  .error-text { flex: 1; font-size: 13px; color: #ef4444; }
  .btn-retry {
    padding: 6px 14px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 6px;
    color: white;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .btn-retry:hover { opacity: 0.85; }

  .insight-banner {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 14px 16px;
    background: color-mix(in srgb, var(--accent-primary) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-radius: 10px;
  }
  .insight-icon { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
  .insight-text { flex: 1; font-size: 13px; color: var(--text-secondary, #94a3b8); line-height: 1.6; margin: 0; }
  .btn-rerun {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 16px;
    cursor: pointer;
    padding: 0 4px;
    line-height: 1;
    flex-shrink: 0;
    transition: color 0.15s;
  }
  .btn-rerun:hover { color: var(--text-secondary, #94a3b8); }

  .card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 16px;
  }
  .card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .charts-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  @media (max-width: 900px) {
    .charts-grid { grid-template-columns: 1fr; }
  }

  .no-data {
    padding: 24px;
    text-align: center;
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
  }

  .channel-table {
    overflow-x: auto;
  }
  table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    font-size: 12px;
  }
  th {
    text-align: left;
    padding: 6px 10px;
    color: var(--text-muted);
    font-weight: 500;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }
  td {
    padding: 7px 10px;
    color: var(--text-primary, #e2e8f0);
    border-bottom: 1px solid rgba(255,255,255,0.04);
  }
  th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
  th .help-icon { margin-left: 4px; vertical-align: middle; }
  .help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--text-secondary) 18%, transparent);
    color: var(--text-secondary);
    font-size: 10px;
    font-weight: 700;
    cursor: help;
    user-select: none;
    transition: background 0.15s, color 0.15s;
  }
  .help-icon:hover {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
    color: var(--accent-primary, #3b82f6);
  }
  .spend-sub {
    display: block;
    font-size: 10px;
    color: var(--text-muted);
    font-weight: 400;
    margin-top: 1px;
    line-height: 1.2;
  }
  .ch-name { font-weight: 500; }
  .ch-cat {
    display: inline-block;
    margin-left: 6px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    padding: 1px 6px;
    border-radius: 4px;
    vertical-align: middle;
    background: color-mix(in srgb, var(--text-secondary) 12%, transparent);
    color: var(--text-secondary);
    cursor: help;
  }
  .ch-cat.cat-brand {
    background: color-mix(in srgb, var(--warning, #f59e0b) 15%, transparent);
    color: var(--warning, #f59e0b);
  }
  .ch-cat.cat-perf {
    background: color-mix(in srgb, var(--success, #10b981) 15%, transparent);
    color: var(--success, #10b981);
  }
  .ch-cat.cat-mixed {
    background: color-mix(in srgb, var(--text-muted, #64748b) 14%, transparent);
    color: var(--text-muted, #64748b);
  }
  /* Trust Level 3 (v1.1.0): group headers и decay column */
  .group-header td {
    padding: 8px 10px !important;
    font-weight: 600;
    font-size: 12px;
    background: rgba(255, 255, 255, 0.03);
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    color: var(--text-secondary, #94a3b8);
  }
  .group-header.gh-brand td { border-left: 3px solid rgba(110, 168, 254, 0.7); }
  .group-header.gh-perf td { border-left: 3px solid rgba(110, 220, 158, 0.7); }
  .group-header.gh-mixed td { border-left: 3px solid rgba(200, 200, 200, 0.4); }
  .group-count {
    margin-left: 8px;
    padding: 2px 8px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.06);
    font-size: 11px;
    font-weight: 500;
  }
  .decay-cell { font-variant-numeric: tabular-nums; }
  .decay-ci {
    display: block;
    font-size: 10px;
    color: var(--text-muted, #64748b);
    margin-top: 2px;
  }
  .roi-good { color: var(--success); font-weight: 600; }
  .roi-mid { color: var(--warning); }
  .roi-bad { color: var(--danger); }
  .roi-warn { color: var(--warning); font-weight: 600; }  /* подозрительно высокий ROI */
  .gap-pos { color: var(--success); }
  .gap-neg { color: var(--danger); }
  .verdict-good { color: var(--success); font-weight: 500; }
  .verdict-warn { color: var(--warning); font-weight: 500; }
  .verdict-bad  { color: var(--danger);  font-weight: 500; }
</style>
