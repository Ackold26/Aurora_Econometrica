<script>
  /**
   * Step 4: Budget Optimization — KILLER FEATURE.
   * C1: builds scaledParams from modelData.channelParams + current_spend from optimize response.
   * C4: triggerCompletion() on step completion.
   * A4: media query for two-column layout < 1000px → stack.
   * Layout: insight → controls → [BudgetOptimizer | ResponseCurves] → ScenarioPlayground.
   * @component OptimizeStep
   */
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import { marginalROI } from '$lib/hill.js';
  import {
    activeProjectId,
    modelData,
    optimizeData,
    decomposeData,
    completeStep,
    setStepError,
    isComputing,
    computeStatus,
    triggerCompletion,
    sessionStats,
    expertMode,
  } from '$lib/project-state.js';
  import { buildScaledParams, predictKPI } from '$lib/hill.js';
  import BudgetOptimizer from '$lib/components/pipeline/BudgetOptimizer.svelte';
  import ResponseCurves from '$lib/components/pipeline/ResponseCurves.svelte';
  import ScenarioPlayground from '$lib/components/pipeline/ScenarioPlayground.svelte';

  /** @type {'idle' | 'optimizing' | 'done' | 'error'} */
  let stepState = $state('idle');
  /** @type {string | null} */
  let errorMessage = $state(null);
  /** @type {boolean} */
  let budgetLocked = $state(true);
  /** @type {boolean} */
  let playgroundOpen = $state(false);
  /** @type {number | null} */
  let totalBudgetInput = $state(null);
  let minPct = $state(50);
  let maxPct = $state(150);

  // Per-channel constraints (экспертный режим). null = используется глобальный min/max.
  /** @type {Record<string, number>} */
  let channelMinPct = $state({});
  /** @type {Record<string, number>} */
  let channelMaxPct = $state({});

  /** Пресеты для быстрой настройки per-channel ограничений. */
  const CHANNEL_PRESETS = {
    free:        { label: 'Свободно', min: 0,   max: 300, hint: 'без ограничений' },
    flex:        { label: 'Гибкий',   min: 50,  max: 150, hint: '±50% от текущего' },
    only_up:     { label: 'Только ↑', min: 100, max: 200, hint: 'нельзя сокращать (фикс. контракт)' },
    only_down:   { label: 'Только ↓', min: 0,   max: 100, hint: 'нельзя увеличивать (бюджет ограничен)' },
    locked:      { label: 'Зафиксирован', min: 100, max: 100, hint: 'годовая сделка / неизменяемый' },
  };

  // Current data from store
  const optData = $derived($optimizeData);
  const mData = $derived($modelData);
  const dData = $derived($decomposeData);

  // ── Tooltip-помощь по всем опциям ─────────────────────────
  const HELP = {
    totalBudget:    'Общий бюджет — сумма по всем каналам.\n\nПо умолчанию = текущий медиа-бюджет (рассчитан моделью). Изменение здесь = переход в режим What-if (пересчёт оптимума для другого бюджета).\n\nЕсли «Фиксировать бюджет» включён — это значение остаётся неизменным при оптимизации.',
    minPct:         'Мин. % — нижняя граница изменения каждого канала при оптимизации.\n\n50% означает: бюджет канала может уменьшиться максимум вдвое.\n10% = почти любое сокращение разрешено.\n100% = сокращать каналы нельзя (только увеличивать).\n\nДля более радикальной оптимизации — снижайте Мин. %.',
    maxPct:         'Макс. % — верхняя граница изменения каждого канала.\n\n150% = можно увеличить бюджет канала в 1.5 раза.\n100% = увеличивать нельзя (только перераспределять между каналами).\n300% = почти без верхнего лимита.\n\nДля более агрессивной оптимизации — повышайте Макс. %.',
    lockBudget:     'Фиксировать бюджет — запрет на изменение общей суммы при оптимизации.\n\nВключено: оптимизатор только перераспределяет деньги между каналами, общий бюджет = totalBudget.\nВыключено: общий бюджет может меняться (модель найдёт оптимум любой суммы в рамках Мин/Макс per-channel).\n\nДля стандартной задачи «выжать максимум из имеющегося» — оставить включённым.',
    runOptimize:    'Запускает scipy SLSQP оптимизатор: ищет распределение бюджета, максимизирующее KPI при заданных ограничениях.\n\nВремя: 1-5 секунд для стандартного медиаплана.\n\nРезультат: новое распределение per-channel + ожидаемый прирост KPI (lift %).',
    forecastKPI:    'Прогноз KPI — модельная оценка продаж при текущих значениях ползунков (или после оптимизации).\n\nРассчитывается через Hill saturation: вклад каждого канала суммируется по нормализованной шкале и переводится в реальные продажи.\n\nИспользуется как baseline для расчёта lift % при перераспределении.',
    miROAS:         'miROAS (Marginal ROI) — отдача от СЛЕДУЮЩЕГО вложенного рубля в канал, не средняя.\n\nРассчитывается через производную response curve в текущей точке.\n\n> 1.5× — канал недонасыщен, стоит увеличить бюджет\n0.8 - 1.5× — канал в зоне стабильной отдачи\n< 0.8× — канал перенасыщен, уменьшить бюджет (каждый рубль приносит меньше расхода)',
    responseCurves: 'Response Curves — кривые отдачи каналов от размера бюджета.\n\nX = бюджет канала, Y = вклад в KPI (продажи).\nТочка на кривой = текущая позиция (текущий бюджет канала).\nИзгиб (плато) = saturation: после этой точки каждый дополнительный рубль даёт меньше эффекта.\n\nЦель оптимизации — двигать точки вверх по кривой к более крутым участкам.',
    avgROI:         'Средний ROI = суммарный вклад медиа в продажи ÷ суммарный бюджет.\n\nИндустриальный benchmark: > 2× — отлично, 1-2× — приемлемо, < 1× — медиа в среднем не окупается.',
    saturation:     'Светофор насыщения каналов:\n🟢 Недонасыщен (mROAS > 1.5×) — кандидат на масштабирование\n🟡 Стабилен (0.8-1.5×) — оптимальная зона\n🔴 Перенасыщен (< 0.8×) — каждый дополнительный рубль работает в убыток',
  };

  // ── Блок A — статус-карточка «Текущий бюджет» ─────────────
  const currentTotalBudget = $derived.by(() => {
    if (optData?.channels) {
      return optData.channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + (c.current_spend || 0), 0);
    }
    if (dData?.channels) {
      return dData.channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + (c.spend || 0), 0);
    }
    return 0;
  });

  const avgROI = $derived.by(() => {
    if (!dData?.channels) return null;
    const totalSpend = dData.channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + (c.spend || 0), 0);
    const totalContrib = dData.channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + (c.contribution || 0), 0);
    return totalSpend > 0 ? totalContrib / totalSpend : null;
  });

  /** @param {number} n @param {number} [dec] */
  const fmtNum = (n, dec = 0) => Number.isFinite(n) ? n.toLocaleString('ru-RU', { maximumFractionDigits: dec }) : '—';
  /** @param {number} n */
  const fmtBudget = (n) => {
    if (!Number.isFinite(n)) return '—';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + ' M ₽';
    if (n >= 1_000) return (n / 1_000).toFixed(0) + ' K ₽';
    return n.toFixed(0) + ' ₽';
  };

  // Channels: основной источник — optimizeData; fallback — decomposeData (до первого optimize).
  // Так блок A (статус-карточка) работает сразу при заходе на шаг.
  /** @type {string[]} */
  const channels = $derived(
    optData?.channels?.map(/** @type {(c: any) => string} */ (c) => c.name) ??
    dData?.channels?.map(/** @type {(c: any) => string} */ (c) => c.name) ??
    []
  );

  /** @type {Record<string, number>} current spend — из optimize или decompose. */
  const currentSpend = $derived.by(() => {
    if (optData?.channels) {
      return Object.fromEntries(optData.channels.map(/** @type {(c: any) => [string, number]} */ (c) => [c.name, c.current_spend]));
    }
    if (dData?.channels) {
      return Object.fromEntries(dData.channels.map(/** @type {(c: any) => [string, number]} */ (c) => [c.name, c.spend ?? 0]));
    }
    return {};
  });

  /** @type {Record<string, {alpha: number, gammaScaled: number, beta: number}>} */
  const scaledParams = $derived.by(() => {
    if (!mData?.channelParams || !Object.keys(currentSpend).length) return {};
    return buildScaledParams(mData.channelParams, currentSpend);
  });

  /** Normalization из тренировки модели (y_mean, y_std) — для денормализации в реальные единицы. */
  const yNorm = $derived(mData?.normalization ?? null);

  /** Current KPI at current_spend (baseline for lift%). Денормализован в исходные единицы. */
  const currentKPI = $derived(predictKPI(currentSpend, scaledParams, yNorm));

  /**
   * miROAS per channel — marginal ROI следующего рубля при ТЕКУЩИХ значениях слайдеров.
   * Возвращает map: { ch: { value, status } }.
   * status:
   *   'unused'      — spend = 0, канал не используется (≠ перенасыщен)
   *   'scale'       — value > 1.5 — недонасыщен, можно масштабировать
   *   'stable'      — 0.8-1.5 — стабильная зона
   *   'saturated'   — < 0.8 — перенасыщен
   */
  const miROASMap = $derived.by(() => {
    /** @type {Record<string, {value: number, status: 'unused'|'scale'|'stable'|'saturated'}>} */
    const map = {};
    for (const ch of channels) {
      const p = scaledParams[ch];
      if (!p) continue;
      const spend = channelBudgets[ch] ?? currentSpend[ch] ?? 0;
      if (!spend || spend < 1) {
        map[ch] = { value: 0, status: 'unused' };
        continue;
      }
      // Денормализация через y_std → реальные рубли KPI на рубль расхода.
      const v = marginalROI(spend, p.alpha, p.gammaScaled, p.beta, yNorm);
      const status = v > 1.5 ? 'scale' : v > 0.8 ? 'stable' : 'saturated';
      map[ch] = { value: v, status };
    }
    return map;
  });

  /** Светофор: подсчёт каналов по категориям насыщения (для блока A). */
  const saturationCount = $derived.by(() => {
    /** @type {{good: number, ok: number, low: number, unused: number}} */
    const counts = { good: 0, ok: 0, low: 0, unused: 0 };
    for (const ch of channels) {
      const r = miROASMap[ch];
      if (!r) continue;
      if (r.status === 'unused') counts.unused++;
      else if (r.status === 'scale') counts.good++;
      else if (r.status === 'stable') counts.ok++;
      else counts.low++;
    }
    return counts;
  });

  /** Shared channel budgets — source of truth for BudgetOptimizer & ResponseCurves */
  let channelBudgets = $state(/** @type {Record<string, number>} */ ({}));

  /** Optimal budgets from last run */
  let optimalBudgets = $state(/** @type {Record<string, number> | null} */ (null));

  // Init channelBudgets when optData OR decomposeData arrives.
  // IMPORTANT: don't read stepState — recursive dep.
  $effect(() => {
    const opt = $optimizeData;
    const dec = $decomposeData;
    if (opt?.channels && opt.channels.length > 0) {
      const init = /** @type {Record<string, number>} */ ({});
      for (const ch of opt.channels) init[ch.name] = ch.current_spend;
      channelBudgets = init;
      totalBudgetInput = opt.total_budget ?? null;
    } else if (dec?.channels && dec.channels.length > 0 && Object.keys(channelBudgets).length === 0) {
      // Fallback init from decompose (до первого optimize) — чтобы блок B был интерактивен.
      const init = /** @type {Record<string, number>} */ ({});
      for (const ch of dec.channels) init[ch.name] = ch.spend ?? 0;
      channelBudgets = init;
    }
  });

  // Init per-channel constraints when channels appear (default = global Min/Max).
  $effect(() => {
    if (channels.length === 0) return;
    const minInit = /** @type {Record<string, number>} */ ({});
    const maxInit = /** @type {Record<string, number>} */ ({});
    for (const ch of channels) {
      if (channelMinPct[ch] == null) minInit[ch] = minPct;
      if (channelMaxPct[ch] == null) maxInit[ch] = maxPct;
    }
    if (Object.keys(minInit).length > 0) channelMinPct = { ...channelMinPct, ...minInit };
    if (Object.keys(maxInit).length > 0) channelMaxPct = { ...channelMaxPct, ...maxInit };
  });

  /** Применить пресет к каналу. */
  function applyPreset(/** @type {string} */ ch, /** @type {keyof typeof CHANNEL_PRESETS} */ preset) {
    const p = CHANNEL_PRESETS[preset];
    if (!p) return;
    channelMinPct = { ...channelMinPct, [ch]: p.min };
    channelMaxPct = { ...channelMaxPct, [ch]: p.max };
  }

  /** Сбросить per-channel ограничения на глобальные. */
  function resetChannelLimits() {
    const minInit = /** @type {Record<string, number>} */ ({});
    const maxInit = /** @type {Record<string, number>} */ ({});
    for (const ch of channels) {
      minInit[ch] = minPct;
      maxInit[ch] = maxPct;
    }
    channelMinPct = minInit;
    channelMaxPct = maxInit;
  }

  /** Возвращает true если для канала задано ограничение, отличное от глобального. */
  function hasCustomLimit(/** @type {string} */ ch) {
    return (channelMinPct[ch] != null && channelMinPct[ch] !== minPct) ||
           (channelMaxPct[ch] != null && channelMaxPct[ch] !== maxPct);
  }

  /** Дожидаемся, пока projectId станет валидным (макс. 2с). */
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

  /** Получить projectId — сначала из store, потом ждём, потом fallback на backend. */
  async function ensureProjectId() {
    let projectId = await waitForProjectId(1500);
    if (projectId) return projectId;
    // Fallback: store пуст после HMR/reload — спросим backend напрямую.
    try {
      projectId = /** @type {string|null} */ (await invoke('project_get_active'));
      if (projectId) {
        activeProjectId.set(projectId);
        return projectId;
      }
    } catch { /* нет активного проекта */ }
    return null;
  }

  /** Run scipy optimization */
  async function runOptimize() {
    // Сразу показываем loading — пользователь видит, что клик сработал.
    stepState = 'optimizing';
    errorMessage = null;
    isComputing.set(true);
    computeStatus.set('Подготовка...');

    const projectId = await ensureProjectId();
    if (!projectId) {
      isComputing.set(false);
      computeStatus.set('');
      handleError('Проект не выбран. Вернитесь на шаг «Импорт» и загрузите данные.');
      return;
    }

    computeStatus.set('Оптимизирую бюджет...');

    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId }));
      // В экспертном режиме передаём per-channel ограничения (только те, что отличаются
      // от глобальных — backend применит глобальный fallback для остальных).
      let minPerChannel = null;
      let maxPerChannel = null;
      if ($expertMode && channels.length > 0) {
        const minMap = /** @type {Record<string, number>} */ ({});
        const maxMap = /** @type {Record<string, number>} */ ({});
        for (const ch of channels) {
          if (channelMinPct[ch] != null) minMap[ch] = channelMinPct[ch];
          if (channelMaxPct[ch] != null) maxMap[ch] = channelMaxPct[ch];
        }
        if (Object.keys(minMap).length > 0) minPerChannel = minMap;
        if (Object.keys(maxMap).length > 0) maxPerChannel = maxMap;
      }
      const result = /** @type {any} */ (await invoke('econ_optimize', {
        projectDir,
        totalBudget: totalBudgetInput,
        minPct,
        maxPct,
        minPerChannel,
        maxPerChannel,
      }));

      if (result.status === 'ok') {
        optimizeData.set(result);
        stepState = 'done';

        // Build optimalBudgets for slider animation targets
        const ob = /** @type {Record<string, number>} */ ({});
        for (const ch of (result.channels ?? [])) ob[ch.name] = ch.optimal_spend;
        optimalBudgets = ob;
      } else {
        handleError(result.message || 'Ошибка оптимизации');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    } finally {
      isComputing.set(false);
      computeStatus.set('');
    }
  }

  /** Apply optimal budgets to sliders with animation */
  function applyOptimal() {
    if (!optimalBudgets) return;
    // Animate: set budgets step by step over 800ms
    const start = { ...channelBudgets };
    const end = optimalBudgets;
    const duration = 800;
    const startTime = Date.now();

    /** @param {number} t */
    function smoothstep(t) {
      return t * t * (3 - 2 * t);
    }

    function animate() {
      const elapsed = Date.now() - startTime;
      const t = Math.min(elapsed / duration, 1);
      const s = smoothstep(t);

      const newBudgets = /** @type {Record<string, number>} */ ({});
      for (const ch of channels) {
        newBudgets[ch] = start[ch] + (end[ch] - start[ch]) * s;
      }
      channelBudgets = newBudgets;

      if (t < 1) requestAnimationFrame(animate);
    }
    requestAnimationFrame(animate);
  }

  /** @param {string} msg */
  function handleError(msg) {
    errorMessage = msg;
    stepState = 'error';
    setStepError(4, msg);
    isComputing.set(false);
    computeStatus.set('');
  }

  /** Reset to current spend */
  function resetBudgets() {
    const data = get(optimizeData);
    if (!data?.channels) return;
    const init = /** @type {Record<string, number>} */ ({});
    for (const ch of data.channels) init[ch.name] = ch.current_spend;
    channelBudgets = init;
    optimalBudgets = null;
  }

  /** Confirm optimization & complete step */
  function confirmOptimization() {
    sessionStats.update(s => ({ ...s, scenarioCount: s.scenarioCount + 1 }));
    completeStep(4);
    triggerCompletion();
  }

  /**
   * @param {string} ch
   * @param {number} val
   */
  function handleBudgetChange(ch, val) {
    channelBudgets = { ...channelBudgets, [ch]: val };
  }
</script>

<div class="optimize-step">

  <!-- Error banner -->
  {#if stepState === 'error' && errorMessage}
    <div class="error-banner">
      <span class="error-icon">⚠</span>
      <span class="error-text">{errorMessage}</span>
      <button class="btn-retry" onclick={runOptimize}>Повторить</button>
    </div>
  {/if}

  <!-- ════════════════ БЛОК A — Текущий бюджет (статус-карточка) ════════════════ -->
  <section class="block block-status">
    <div class="block-header">
      <span class="block-letter">A</span>
      <h3 class="block-title">Текущий бюджет</h3>
      <span class="block-subtitle">— стартовая точка вашего медиаплана</span>
    </div>
    <div class="status-grid">
      <div class="status-cell">
        <div class="status-label">
          Общий бюджет<span class="help-icon" title={HELP.totalBudget}>?</span>
        </div>
        <div class="status-value">{fmtBudget(currentTotalBudget)}</div>
        <div class="status-sub">{channels.length} канал{channels.length > 4 ? 'ов' : channels.length > 1 ? 'а' : ''}</div>
      </div>
      <div class="status-cell">
        <div class="status-label">
          Прогноз KPI<span class="help-icon" title={HELP.forecastKPI}>?</span>
        </div>
        <div class="status-value">{fmtNum(currentKPI, 0)}</div>
        <div class="status-sub">при текущем распределении</div>
      </div>
      <div class="status-cell">
        <div class="status-label">
          Средний ROI<span class="help-icon" title={HELP.avgROI}>?</span>
        </div>
        <div class="status-value" class:good={avgROI != null && avgROI >= 2} class:warn={avgROI != null && avgROI < 1}>
          {avgROI != null ? avgROI.toFixed(2) + '×' : '—'}
        </div>
        <div class="status-sub">вклад ÷ расход</div>
      </div>
      <div class="status-cell">
        <div class="status-label">
          Светофор насыщения<span class="help-icon" title={HELP.saturation}>?</span>
        </div>
        <div class="status-value status-traffic">
          <span class="traffic-good" title="Недонасыщенные — масштабировать">🟢 {saturationCount.good}</span>
          <span class="traffic-ok"   title="Стабильные">🟡 {saturationCount.ok}</span>
          <span class="traffic-low"  title="Перенасыщенные — сократить">🔴 {saturationCount.low}</span>
          {#if saturationCount.unused > 0}
            <span class="traffic-unused" title="Каналы с нулевым бюджетом — не используются">⚪ {saturationCount.unused}</span>
          {/if}
        </div>
        <div class="status-sub">по mROAS каналов</div>
      </div>
    </div>
  </section>

  <!-- ════════════════ БЛОК B — Оптимизация в рамках текущего бюджета ════════════════ -->
  <section class="block block-optimize">
    <div class="block-header">
      <span class="block-letter">B</span>
      <h3 class="block-title">Оптимизация распределения</h3>
      <span class="block-subtitle">— выжать максимум из текущего бюджета</span>
    </div>

    <!-- Controls -->
    <div class="controls-card">
      <div class="controls-row">
        <label class="ctrl-label">
          <span class="ctrl-name">Мин. %<span class="help-icon" title={HELP.minPct}>?</span></span>
          <input type="range" min={10} max={100} step={5} bind:value={minPct} class="mini-slider" />
          <span class="mini-val">{minPct}%</span>
        </label>
        <label class="ctrl-label">
          <span class="ctrl-name">Макс. %<span class="help-icon" title={HELP.maxPct}>?</span></span>
          <input type="range" min={100} max={300} step={10} bind:value={maxPct} class="mini-slider" />
          <span class="mini-val">{maxPct}%</span>
        </label>
        <label class="lock-label">
          <input type="checkbox" bind:checked={budgetLocked} class="lock-check" />
          <span>Фиксировать бюджет<span class="help-icon" title={HELP.lockBudget}>?</span></span>
        </label>
        <button
          class="btn-run"
          onclick={runOptimize}
          disabled={stepState === 'optimizing'}
          title={HELP.runOptimize}
        >
          {stepState === 'optimizing' ? 'Оптимизирую...' : '🎯 Оптимизировать бюджет'}
        </button>
      </div>
    </div>

    <!-- Экспертный режим: per-channel ограничения Мин/Макс -->
    {#if $expertMode && channels.length > 0}
      <div class="expert-limits">
        <div class="expert-header">
          <span class="expert-badge">ЭКСПЕРТ</span>
          <h4 class="expert-title">Ограничения по каналам</h4>
          <span class="expert-subtitle">— разные пределы изменения для каждого канала (баинговые сделки, фиксированные контракты и т.д.)</span>
          <button class="btn-reset-limits" onclick={resetChannelLimits} title="Сбросить все на глобальные Мин/Макс">↺ Сбросить</button>
        </div>
        <div class="limits-table">
          <div class="limits-header">
            <div>Канал</div>
            <div class="num">Мин. %</div>
            <div class="num">Макс. %</div>
            <div>Пресет</div>
          </div>
          {#each channels as ch}
            {@const isCustom = hasCustomLimit(ch)}
            <div class="limits-row" class:custom={isCustom}>
              <div class="lim-name">
                {ch}
                {#if isCustom}<span class="custom-mark" title="Отличается от глобальных Мин/Макс">●</span>{/if}
              </div>
              <div class="num">
                <input
                  type="number"
                  class="lim-input"
                  min={0}
                  max={300}
                  step={5}
                  value={channelMinPct[ch] ?? minPct}
                  oninput={(/** @type {any} */ e) => channelMinPct = { ...channelMinPct, [ch]: Number(e.target.value) }}
                />
              </div>
              <div class="num">
                <input
                  type="number"
                  class="lim-input"
                  min={0}
                  max={500}
                  step={5}
                  value={channelMaxPct[ch] ?? maxPct}
                  oninput={(/** @type {any} */ e) => channelMaxPct = { ...channelMaxPct, [ch]: Number(e.target.value) }}
                />
              </div>
              <div class="preset-cell">
                {#each Object.entries(CHANNEL_PRESETS) as [key, p]}
                  <button
                    class="preset-btn"
                    title={p.hint}
                    onclick={() => applyPreset(ch, /** @type {keyof typeof CHANNEL_PRESETS} */ (key))}
                  >{p.label}</button>
                {/each}
              </div>
            </div>
          {/each}
        </div>
        <p class="expert-hint">
          <span class="help-icon" title="Зафиксирован: годовая сделка, бюджет неизменен. Только ↑: фиксированный минимум, можно увеличивать. Только ↓: бюджет ограничен сверху, можно сокращать. Гибкий: ±50%. Свободно: без ограничений.">?</span>
          Глобальные Мин/Макс выше применяются ко всем каналам по умолчанию. Здесь можно переопределить для каждого канала отдельно — пресеты как быстрая точка старта.
        </p>
      </div>
    {/if}

    <!-- Insight banner (после optimize) -->
    {#if optData?.insight}
      <div class="insight-banner">
        <span class="insight-icon">🎯</span>
        <p class="insight-text">{optData.insight}</p>
        {#if optData.expected_lift_pct != null}
          <span class="lift-badge" class:negative-lift={optData.expected_lift_pct < 0}>
            {optData.expected_lift_pct >= 0 ? '+' : ''}{optData.expected_lift_pct.toFixed(1)}%
          </span>
        {/if}
      </div>
    {/if}

    <!-- Two-column: BudgetOptimizer | ResponseCurves -->
    {#if channels.length > 0}
      <div class="optimize-grid">
        <div class="card">
          <div class="card-title">
            Распределение бюджета
            <span class="help-icon" title="Слайдеры — текущий бюджет каждого канала. Двигайте, чтобы увидеть прогноз KPI в реальном времени. Кнопка «Применить оптимум» подставит найденное модели распределение.">?</span>
          </div>
          <BudgetOptimizer
            {channels}
            {scaledParams}
            {channelBudgets}
            initialSpend={currentSpend}
            currentKPI={currentKPI}
            normalization={yNorm}
            locked={budgetLocked}
            onBudgetChange={handleBudgetChange}
            onOptimize={applyOptimal}
            onReset={resetBudgets}
            optimizing={stepState === 'optimizing'}
            {optimalBudgets}
          />
        </div>
        <div class="card">
          <div class="card-title">
            Response Curves<span class="help-icon" title={HELP.responseCurves}>?</span>
          </div>
          {#if optData?.response_curves && Object.keys(scaledParams).length > 0}
            <ResponseCurves
              responseCurves={optData.response_curves}
              {channelBudgets}
              {scaledParams}
              {channels}
              onBudgetChange={handleBudgetChange}
            />
          {:else}
            <div class="no-curves">Запустите оптимизацию для отображения кривых</div>
          {/if}
        </div>
      </div>

      <!-- miROAS table -->
      {#if Object.keys(miROASMap).length > 0}
        <div class="card miroas-card">
          <div class="card-title">
            miROAS — предельная отдача следующего рубля<span class="help-icon" title={HELP.miROAS}>?</span>
          </div>
          <div class="miroas-table">
            {#each channels as ch}
              {@const r = miROASMap[ch] ?? { value: 0, status: 'unused' }}
              {@const cls =
                r.status === 'scale'     ? 'miroas-good' :
                r.status === 'stable'    ? 'miroas-ok' :
                r.status === 'saturated' ? 'miroas-low' : 'miroas-unused'}
              {@const label =
                r.status === 'scale'     ? '🟢 Масштабировать' :
                r.status === 'stable'    ? '🟡 Стабильно' :
                r.status === 'saturated' ? '🔴 Перенасыщен' :
                                           '⚪ Не используется'}
              <div class="miroas-row {cls}">
                <span class="miroas-name">{ch}</span>
                <span class="miroas-value">
                  {r.status === 'unused' ? '—' : r.value.toFixed(2) + '×'}
                </span>
                <span class="miroas-hint">{label}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Confirm -->
      <div class="confirm-row">
        <button class="btn-confirm" onclick={confirmOptimization}>
          Подтвердить и перейти к отчёту →
        </button>
      </div>
    {:else if stepState === 'idle'}
      <div class="empty-state">
        <p>Нажмите <b>«🎯 Оптимизировать бюджет»</b> выше — модель найдёт оптимальное распределение.</p>
        <p class="hint">Дефолты: бюджет = текущий, диапазон 50-150% per-channel. Для радикальной оптимизации снижайте Мин. % и повышайте Макс. %.</p>
      </div>
    {:else if stepState === 'optimizing'}
      <div class="empty-state">
        <div class="spinner-lg"></div>
        <p>Оптимизирую распределение бюджета...</p>
        <p class="hint">scipy SLSQP подбирает максимум продаж при заданных ограничениях.</p>
      </div>
    {/if}
  </section>

  <!-- ════════════════ БЛОК C — What-if: изменённый бюджет ════════════════ -->
  <section class="block block-whatif preview">
    <div class="block-header">
      <span class="block-letter">C</span>
      <h3 class="block-title">What-if: изменённый бюджет</h3>
      <span class="block-subtitle">— а если бюджет станет другим?</span>
      <span class="preview-badge">скоро</span>
    </div>
    <div class="preview-content">
      <p>Слайдер общего бюджета (±50% от текущего) и кнопка «Пересчитать для нового бюджета» с сравнительной таблицей текущий vs новый.</p>
      <p class="hint">Ответит на вопросы «куда уйдут дополнительные деньги», «каких каналов лишимся первыми при сокращении».</p>
    </div>
  </section>

  <!-- ════════════════ БЛОК D — Прогноз на будущий период (медиаинфляция) ════════════════ -->
  <section class="block block-forecast preview">
    <div class="block-header">
      <span class="block-letter">D</span>
      <h3 class="block-title">Прогноз на будущий период</h3>
      <span class="block-subtitle">— с учётом медиаинфляции по каналам</span>
      <span class="preview-badge">скоро</span>
    </div>
    <div class="preview-content">
      <p>Таблица % инфляции per-channel (с пресетами: TV +12%, Digital +7%, OOH +10%, Radio +8%, Print +5%, Social +7%) + режимы расчёта:</p>
      <p class="hint">«Сохранить объём» — нужно больше денег. «Сохранить бюджет» — реальный объём упадёт, модель пересчитает оптимум в новых ценах.</p>
    </div>
  </section>

  <!-- ════════════════ Сценарии (постоянно видимы, переедут в Phase 5) ════════════════ -->
  {#if channels.length > 0}
    <section class="block block-scenarios">
      <div class="block-header">
        <span class="block-letter">⚙</span>
        <h3 class="block-title">Сценарный анализ</h3>
        <span class="block-subtitle">— что будет, если изменить бюджет канала на N%?</span>
        <button
          class="btn-scenario-toggle"
          onclick={() => { playgroundOpen = !playgroundOpen; }}
        >
          {playgroundOpen ? '▲ Свернуть' : '▼ Развернуть'}
        </button>
      </div>
      {#if playgroundOpen}
        <div class="card scenario-card">
          <ScenarioPlayground {channelBudgets} {channels} />
        </div>
      {/if}
    </section>
  {/if}

</div>

<style>
  .optimize-step {
    /* Скрол владеет .pipeline-main — здесь никаких overflow / height: 100%,
       иначе двойной скрол + фантомное пустое пространство (см. DecomposeStep). */
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 0;
    box-sizing: border-box;
  }

  /* ── Section blocks (A/B/C/D) ─────────────────────────────── */
  .block {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px 18px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 14px;
    position: relative;
  }
  .block-header {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .block-letter {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 8px;
    background: color-mix(in srgb, var(--accent-primary) 18%, transparent);
    color: var(--accent-primary, #3b82f6);
    font-size: 13px;
    font-weight: 700;
    flex-shrink: 0;
  }
  .block-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
  }
  .block-subtitle {
    font-size: 12px;
    color: var(--text-muted);
    font-style: italic;
  }
  .preview-badge {
    margin-left: auto;
    padding: 3px 10px;
    border-radius: 12px;
    background: color-mix(in srgb, var(--warning) 15%, transparent);
    color: var(--warning);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .block.preview {
    opacity: 0.75;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border-style: dashed;
  }
  .preview-content {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.5;
  }
  .preview-content p { margin: 0; }
  .preview-content .hint {
    font-size: 11px;
    color: var(--text-muted);
  }

  /* ── Block A: Status grid ─────────────────────────────────── */
  .status-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
  }
  .status-cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px 14px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--text-primary) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-primary) 7%, transparent);
  }
  .status-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 10px;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .status-value {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.2;
    font-variant-numeric: tabular-nums;
  }
  .status-value.good { color: var(--success); }
  .status-value.warn { color: var(--warning); }
  .status-sub {
    font-size: 11px;
    color: var(--text-muted);
  }
  .status-traffic { display: flex; gap: 10px; font-size: 14px; }
  .traffic-good, .traffic-ok, .traffic-low { font-weight: 600; cursor: help; }

  /* ── Экспертная панель per-channel ограничений ───────────── */
  .expert-limits {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--danger) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
  }
  .expert-header {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .expert-badge {
    padding: 2px 8px;
    background: color-mix(in srgb, var(--danger) 18%, transparent);
    color: var(--danger);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.08em;
    border-radius: 4px;
  }
  .expert-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
  }
  .expert-subtitle {
    font-size: 11px;
    color: var(--text-muted);
    font-style: italic;
    flex: 1;
    min-width: 200px;
  }
  .btn-reset-limits {
    margin-left: auto;
    padding: 4px 10px;
    background: transparent;
    border: 1px solid color-mix(in srgb, var(--text-primary) 14%, transparent);
    border-radius: 6px;
    color: var(--text-secondary);
    font-size: 11px;
    cursor: pointer;
  }
  .btn-reset-limits:hover {
    border-color: color-mix(in srgb, var(--accent-primary) 50%, transparent);
    color: var(--accent-primary);
  }

  .limits-table { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
  .limits-header,
  .limits-row {
    display: grid;
    grid-template-columns: minmax(180px, 1.6fr) 90px 90px minmax(280px, 2fr);
    gap: 12px;
    align-items: center;
    padding: 6px 10px;
    border-radius: 6px;
  }
  .limits-header {
    color: var(--text-secondary);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 0.04em;
  }
  .limits-row {
    background: color-mix(in srgb, var(--text-primary) 3%, transparent);
  }
  .limits-row.custom {
    background: color-mix(in srgb, var(--warning) 8%, transparent);
    border-left: 3px solid var(--warning);
    padding-left: 7px;
  }
  .lim-name { display: flex; align-items: center; gap: 6px; color: var(--text-primary); }
  .custom-mark { color: var(--warning); font-size: 12px; }
  .lim-input {
    width: 100%;
    padding: 5px 8px;
    background: color-mix(in srgb, var(--text-primary) 5%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-primary) 12%, transparent);
    border-radius: 4px;
    color: var(--text-primary);
    font-size: 12px;
    font-family: monospace;
    font-variant-numeric: tabular-nums;
    text-align: right;
    outline: none;
  }
  .lim-input:focus { border-color: var(--accent-primary); }
  .num { text-align: right; }

  .preset-cell { display: flex; gap: 4px; flex-wrap: wrap; }
  .preset-btn {
    padding: 3px 8px;
    background: transparent;
    border: 1px solid color-mix(in srgb, var(--text-primary) 12%, transparent);
    border-radius: 4px;
    color: var(--text-secondary);
    font-size: 10px;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
  }
  .preset-btn:hover {
    background: color-mix(in srgb, var(--accent-primary) 14%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary) 35%, transparent);
    color: var(--accent-primary);
  }

  .expert-hint {
    font-size: 11px;
    color: var(--text-muted);
    line-height: 1.5;
    margin: 0;
  }

  /* ── Help icon (универсальный) ────────────────────────────── */
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
    margin-left: 4px;
    vertical-align: middle;
  }
  .help-icon:hover {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
    color: var(--accent-primary, #3b82f6);
  }

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
  .lift-badge {
    flex-shrink: 0;
    padding: 4px 10px;
    background: color-mix(in srgb, var(--success) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
    border-radius: 20px;
    color: #22c55e;
    font-size: 13px;
    font-weight: 700;
    font-family: monospace;
  }
  .lift-badge.negative-lift {
    background: color-mix(in srgb, var(--danger) 15%, transparent);
    border-color: color-mix(in srgb, var(--danger) 30%, transparent);
    color: #ef4444;
  }

  .controls-card {
    /* Внутри блока B — облегчённый фон, без card-in-card. */
    background: color-mix(in srgb, var(--text-primary) 3%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-primary) 6%, transparent);
    border-radius: 10px;
    padding: 12px 14px;
  }
  .controls-row {
    display: flex;
    align-items: center;
    gap: 18px;
    flex-wrap: wrap;
  }
  .ctrl-label {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
  }
  .ctrl-name {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
  }
  .budget-input {
    width: 100px;
    padding: 6px 10px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    font-size: 12px;
    outline: none;
  }
  .mini-slider {
    width: 80px;
    height: 3px;
    -webkit-appearance: none;
    appearance: none;
    background: rgba(255,255,255,0.1);
    border-radius: 2px;
    outline: none;
  }
  .mini-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--accent-primary, #3b82f6);
    cursor: pointer;
  }
  .mini-val { font-size: 11px; font-family: monospace; min-width: 32px; }

  .btn-run {
    padding: 8px 18px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 8px;
    color: white;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition: opacity 0.15s;
  }
  .btn-run:hover:not(:disabled) { opacity: 0.85; }
  .btn-run:disabled { opacity: 0.5; cursor: not-allowed; }

  .lock-label {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer;
    user-select: none;
  }
  .lock-check { cursor: pointer; accent-color: var(--accent-primary, #3b82f6); }

  /* A4: two-column, stack on narrow */
  .optimize-grid {
    display: grid;
    grid-template-columns: 2fr 3fr;
    gap: 16px;
  }
  @media (max-width: 1000px) {
    .optimize-grid { grid-template-columns: 1fr; }
  }

  .card {
    /* Card внутри блока — облегчённый, без двойной рамки. */
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-primary) 6%, transparent);
    border-radius: 10px;
    padding: 14px;
  }
  .card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .miroas-card { margin-top: 4px; }
  .miroas-table { display: flex; flex-direction: column; gap: 4px; }
  .miroas-row {
    display: flex; align-items: center; gap: 12px;
    padding: 8px 12px; border-radius: 6px;
    background: color-mix(in srgb, var(--text-primary) 3%, transparent);
    border-left: 3px solid transparent;
  }
  .miroas-row.miroas-good { border-left-color: var(--success); }
  .miroas-row.miroas-ok   { border-left-color: var(--warning); }
  .miroas-row.miroas-low  { border-left-color: var(--danger); }
  .miroas-row.miroas-unused {
    border-left-color: color-mix(in srgb, var(--text-muted) 50%, transparent);
    opacity: 0.65;
  }
  .miroas-name { flex: 1; font-size: 12px; color: var(--text-secondary); }
  .miroas-value {
    font-size: 14px; font-weight: 700;
    font-family: 'SF Mono', 'JetBrains Mono', Consolas, monospace;
    font-variant-numeric: tabular-nums;
    color: var(--text-primary);
    min-width: 60px; text-align: right;
  }
  .miroas-hint { font-size: 11px; color: var(--text-muted); min-width: 130px; text-align: right; }

  .no-curves {
    padding: 40px 20px;
    text-align: center;
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
  }

  .bottom-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .confirm-row {
    display: flex;
    gap: 10px;
    align-items: center;
  }

  .btn-confirm {
    flex: 1;
    padding: 11px 20px;
    background: linear-gradient(135deg, #22c55e, #16a34a);
    border: none;
    border-radius: 8px;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-confirm:hover { opacity: 0.9; }

  .btn-scenario-toggle {
    margin-left: auto;
    padding: 5px 12px;
    background: transparent;
    border: 1px solid color-mix(in srgb, var(--text-primary) 14%, transparent);
    border-radius: 6px;
    color: var(--text-secondary);
    font-size: 11px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
  }
  .btn-scenario-toggle:hover {
    border-color: color-mix(in srgb, var(--accent-primary) 50%, transparent);
    color: var(--accent-primary);
  }

  .scenario-card { margin-top: 8px; }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 50px 24px;
    text-align: center;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 1.6;
    max-width: 640px;
    margin: 0 auto;
  }
  .empty-state p { margin: 0; }
  .empty-state b { color: var(--text-primary); }
  .empty-state .hint {
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.5;
  }
  .spinner-lg {
    width: 32px;
    height: 32px;
    border: 3px solid color-mix(in srgb, var(--accent-primary) 25%, transparent);
    border-top-color: var(--accent-primary, #3b82f6);
    border-radius: 50%;
    animation: spin-lg 0.8s linear infinite;
  }
  @keyframes spin-lg { to { transform: rotate(360deg); } }
</style>
