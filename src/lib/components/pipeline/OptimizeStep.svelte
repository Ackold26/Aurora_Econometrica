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
  import { tick } from 'svelte';
  import {
    activeProjectId,
    modelData,
    optimizeData,
    optimizeLiveState,
    decomposeData,
    completeStep,
    setStepError,
    isComputing,
    computeStatus,
    triggerCompletion,
    sessionStats,
    expertMode,
    unitCosts,
    channelCategories,
    planningMode,
    forecastConfig,
    forecastContext,
  } from '$lib/project-state.js';
  import { buildScaledParams, predictKPI } from '$lib/hill.js';
  import BudgetOptimizer from '$lib/components/pipeline/BudgetOptimizer.svelte';
  import ResponseCurves from '$lib/components/pipeline/ResponseCurves.svelte';
  import ExpandableCard from '$lib/components/ExpandableCard.svelte';
  import ScenarioPlayground from '$lib/components/pipeline/ScenarioPlayground.svelte';
  import ForecastHorizonPicker from '$lib/components/pipeline/ForecastHorizonPicker.svelte';
  import TrustBanner from '$lib/components/pipeline/TrustBanner.svelte';
  import PipelineOnboarding from '$lib/components/pipeline/PipelineOnboarding.svelte';
  import { TOURS } from '$lib/pipeline-tours.js';
  import { shouldShowOnboarding, markOnboardingDone } from '$lib/onboarding-state.js';

  // Onboarding — показываем первый визит на Optimize ТОЛЬКО когда блоки A-E
  // действительно отрендерены (channels.length > 0, то есть после успешного train).
  // Иначе spotlight бьётся по пустому DOM и пользователь видит 6 абстрактных модалок.
  let showOnboarding = $state(false);
  let onboardingChecked = false;
  $effect(() => {
    if (typeof window === 'undefined') return;
    if (onboardingChecked) return;
    if (!channels || channels.length === 0) return;
    onboardingChecked = true;
    if (shouldShowOnboarding('optimize')) {
      requestAnimationFrame(() => { showOnboarding = true; });
    }
  });
  function restartOnboarding() {
    if (!channels || channels.length === 0) {
      alert('Обучи модель на шаге «Моделирование» — тогда появятся блоки A-E и тур станет осмысленным.');
      return;
    }
    // Сбросить completed-флаг конкретно этого шага и запустить заново
    try { window.localStorage.removeItem('aurora-econ-onboarded:optimize'); } catch {}
    showOnboarding = true;
  }

  /** @type {'idle' | 'optimizing' | 'done' | 'error'} */
  let stepState = $state('idle');
  /** @type {string | null} */
  let errorMessage = $state(null);
  /** @type {boolean} */
  let budgetLocked = $state(true);

  /** v1.0.16: state для collapsible expert disclosure под Optimize controls.
   *  Default collapsed — customer notices availability через arrow icon, может
   *  expand если нужны per-channel constraints. */
  let expertExpanded = $state(false);
  /** Forecast inflation overlay внутри Block C (What-if). Default closed —
   *  customer открывает disclosure если хочет применить медиаинфляцию следующего
   *  периода. Hydration inflation values gated на это, чтобы default forecast
   *  не выполнялся automatically. */
  let forecastExpanded = $state(false);
  /** v1.0.16: applyInflation = «учесть инфляцию в сохраняемом сценарии».
   *  Когда true — saveWhatIfAsScenario использует ucNew вместо unit_costs. */
  let applyInflation = $state(false);
  // ucOldMap / ucNewMap declared LATER (after `channels`) to avoid TDZ.

  /** Bidirectional sync для global $expertMode и local disclosures.
   *  Forward (global → local): customer click «Эксперт» в header → expand both.
   *  Reverse (local → global): customer manually opens a disclosure → header
   *  badge активируется, signaling expert mode active.
   *  Cascade trade-off: открытие одного locally также раскрывает другое — это
   *  acceptable «expert mode is all-or-nothing» semantics. */
  $effect(() => {
    if ($expertMode) {
      expertExpanded = true;
      forecastExpanded = true;
    } else {
      expertExpanded = false;
      forecastExpanded = false;
    }
  });
  $effect(() => {
    const anyOpen = expertExpanded || forecastExpanded;
    if (anyOpen && !$expertMode) expertMode.set(true);
    else if (!anyOpen && $expertMode) expertMode.set(false);
  });
  /** @type {boolean} */
  let playgroundOpen = $state(false);
  /** @type {number | null} */
  let totalBudgetInput = $state(null);
  // O1.1 (Phase 0.1 fix-session 2026-04-25): defaults расширены 50/150 → 20/200.
  // Pre-fix: при money_budget = current × 1.5, sum(upper bounds × 1.5) = current × 1.5 →
  // SLSQP не может двигаться кроме как все каналы to max → trivial scaling.
  // 20/200 даёт реальную свободу: 10× difference между bounds extremes vs prev 3×.
  // Insights panel рекомендует 10/300 при binding — это escalation если defaults тоже binding.
  let minPct = $state(20);
  let maxPct = $state(200);

  // F.1 (D.3 frontend): per-group sliders для Trust 3 brand vs performance.
  // null = use global. Сохраняем гибкость: пользователь явно opt-in включает per-group.
  // Видны только когда модель hierarchical (≥2 brand или ≥2 perf — см. hasGroupSplit).
  /** @type {number | null} */
  let brandMinPct = $state(null);
  /** @type {number | null} */
  let brandMaxPct = $state(null);
  /** @type {number | null} */
  let perfMinPct = $state(null);
  /** @type {number | null} */
  let perfMaxPct = $state(null);
  let groupSlidersExpanded = $state(false);

  // O1.2 (Phase 0.1): dirty-state — если settings изменились после успешной
  // оптимизации, показываем индикатор у кнопки. Помогает Антону осознать
  // что нужно перезапустить optimize чтобы увидеть результат под новыми
  // settings. Snapshot обновляется AFTER successful response (см. runOptimize).
  /** @type {string | null} */
  let lastOptimizeSettings = $state(null);
  let optimizeSettingsDirty = $derived.by(() => {
    if (!lastOptimizeSettings) return false;
    const current = JSON.stringify({
      minPct, maxPct,
      brandMin: brandMinPct, brandMax: brandMaxPct,
      perfMin: perfMinPct, perfMax: perfMaxPct,
      cMin: { ...channelMinPct },
      cMax: { ...channelMaxPct },
      budget: totalBudgetInput,
    });
    return current !== lastOptimizeSettings;
  });

  // AUDIT-5 — Inline validation: per-group max должен быть ≤ глобального max.
  // Backend всё равно вернёт INFEASIBLE_GROUP_HIERARCHY, но early UX feedback
  // экономит roundtrip + наглядно показывает причину рядом со слайдерами.
  let groupConstraintWarnings = $derived.by(() => {
    /** @type {string[]} */
    const warnings = [];
    if (brandMaxPct != null && brandMaxPct > maxPct) {
      warnings.push(`Brand Макс. (${brandMaxPct}%) превышает глобальный Макс. (${maxPct}%) — backend вернёт ошибку.`);
    }
    if (perfMaxPct != null && perfMaxPct > maxPct) {
      warnings.push(`Perf Макс. (${perfMaxPct}%) превышает глобальный Макс. (${maxPct}%) — backend вернёт ошибку.`);
    }
    if (brandMinPct != null && brandMaxPct != null && brandMinPct > brandMaxPct) {
      warnings.push(`Brand Мин. (${brandMinPct}%) превышает Brand Макс. (${brandMaxPct}%) — диапазон пуст.`);
    }
    if (perfMinPct != null && perfMaxPct != null && perfMinPct > perfMaxPct) {
      warnings.push(`Perf Мин. (${perfMinPct}%) превышает Perf Макс. (${perfMaxPct}%) — диапазон пуст.`);
    }
    return warnings;
  });

  // F.3 — per-group sliders show только если МОДЕЛЬ hierarchical (не текущий UI state).
  // AUDIT-3 (post-F audit): authoritative source — backend train response
  // (`mData.diagnostics.hierarchical.enabled`), не volatile $channelCategories store.
  // Pre-fix: store отражал latest UI categorization, но обученная модель могла быть flat
  // (если user поменял категории после train, не переобучая). Frontend разрешал per-group
  // → backend optimizer.py rejects с PER_GROUP_REQUIRES_HIERARCHICAL_MODEL → confusing UX.
  // Post-fix: смотрим что фактически закодировано в pickle, fallback к store если
  // diagnostics недоступны (legacy projects до Trust 3 не имеют этого поля).
  let hasGroupSplit = $derived.by(() => {
    // Primary: backend authoritative flag из обученной модели.
    const hierEnabled = mData?.diagnostics?.hierarchical?.enabled;
    if (hierEnabled === true) return true;
    if (hierEnabled === false) return false;
    // Fallback: legacy diagnostics без hierarchical поля → infer из store
    // (pre-Trust3 проекты или ещё не train'ились в этой сессии).
    const cats = $channelCategories || {};
    let nBrand = 0, nPerf = 0;
    for (const v of Object.values(cats)) {
      if (v === 'brand') nBrand++;
      else if (v === 'performance') nPerf++;
    }
    return nBrand >= 2 || nPerf >= 2;
  });

  // Per-channel constraints (экспертный режим). null = используется глобальный min/max.
  /** @type {Record<string, number>} */
  let channelMinPct = $state({});
  /** @type {Record<string, number>} */
  let channelMaxPct = $state({});

  // ── Phase 3: What-if ────────────────────────────────────
  /** Мультипликатор к текущему money-бюджету (0.5…2.0). */
  let whatIfMult = $state(1.0);
  /** @type {any} Результат what-if optimize */
  let whatIfResult = $state(null);
  let whatIfRunning = $state(false);
  /** @type {string | null} — реальная ошибка (красный) */
  let whatIfError = $state(null);
  /** @type {string | null} — уведомление об успехе (зелёный) */
  let whatIfSuccess = $state(null);

  // Автосброс whatIfResult при возврате слайдера к 1.0 — чтобы старый результат
  // не висел на экране при нулевой разнице.
  $effect(() => {
    if (Math.abs(whatIfMult - 1) < 0.01 && whatIfResult) {
      whatIfResult = null;
    }
  });

  // ── Phase 4: Forecast с медиаинфляцией ──────────────────
  /** @type {Record<string, number>} — % инфляции per-канал (14 = +14%). */
  let channelInflation = $state({});
  /** 'volume' = сохранить объём (нужно больше денег), 'budget' = сохранить бюджет. */
  let forecastMode = $state(/** @type {'volume' | 'budget'} */ ('volume'));
  /** @type {any} */
  let forecastResult = $state(null);
  let forecastRunning = $state(false);
  /** @type {string | null} */
  let forecastError = $state(null);
  /** @type {string | null} */
  let forecastSuccess = $state(null);

  /** Дефолты инфляции РФ 2026 по категории. */
  const INFLATION_DEFAULTS = {
    brand_reach: 12,
    performance: 7,
    mixed: 8,
  };

  /** Пресеты для быстрой настройки per-channel ограничений. */
  const CHANNEL_PRESETS = {
    free:        { label: 'Свободно', min: 0,   max: 500, hint: 'без ограничений' },
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
    brandMin:       'Brand Мин. % — нижняя граница для каналов категории «brand» (TV, OOH, brand-PR).\n\nПереопределяет глобальный Мин. % для brand-каналов. Не задано (—) = используется глобальный.\n\nКлассический use-case: «не сокращать TV ниже 80% — контракт на год».',
    brandMax:       'Brand Макс. % — верхняя граница для brand-каналов.\n\nДолжен быть ≤ глобального Макс. (иначе ошибка constraint hierarchy). Например: brand_max=120% при global_max=200% означает «brand можно увеличить максимум на 20%, остальные до 200%».',
    perfMin:        'Performance Мин. % — нижняя граница для каналов категории «performance» (Search, Social, Programmatic).\n\nПереопределяет глобальный Мин. % для performance-каналов. Не задано = глобальный.',
    perfMax:        'Performance Макс. % — верхняя граница для performance-каналов.\n\nДолжен быть ≤ глобального Макс. Полезно когда performance уже на пике эффективности и дальнейшее наращивание не имеет смысла.',
    lockBudget:     'Фиксировать бюджет — запрет на изменение общей суммы при оптимизации.\n\nВключено: оптимизатор только перераспределяет деньги между каналами, общий бюджет = totalBudget.\nВыключено: общий бюджет может меняться (модель найдёт оптимум любой суммы в рамках Мин/Макс per-channel).\n\nДля стандартной задачи «выжать максимум из имеющегося» — оставить включённым.',
    runOptimize:    'Запускает scipy SLSQP оптимизатор: ищет распределение бюджета, максимизирующее KPI при заданных ограничениях.\n\nВремя: 1-5 секунд для стандартного медиаплана.\n\nРезультат: новое распределение per-channel + ожидаемый прирост KPI (lift %).',
    forecastKPI:    'Прогноз KPI — модельная оценка продаж при текущих значениях ползунков (или после оптимизации).\n\nРассчитывается через Hill saturation: вклад каждого канала суммируется по нормализованной шкале и переводится в реальные продажи.\n\nИспользуется как baseline для расчёта lift % при перераспределении.',
    miROAS:         'miROAS (Marginal ROI) — отдача от СЛЕДУЮЩЕГО вложенного рубля в канал, не средняя.\n\nРассчитывается через производную response curve в текущей точке.\n\n> 1.5× — канал недонасыщен, стоит увеличить бюджет\n0.8 - 1.5× — канал в зоне стабильной отдачи\n< 0.8× — канал перенасыщен, уменьшить бюджет (каждый рубль приносит меньше расхода)',
    responseCurves: 'Response Curves — кривые отдачи каналов от размера бюджета.\n\nX = бюджет канала, Y = вклад в KPI (продажи).\nТочка на кривой = текущая позиция (текущий бюджет канала).\nИзгиб (плато) = saturation: после этой точки каждый дополнительный рубль даёт меньше эффекта.\n\nЦель оптимизации — двигать точки вверх по кривой к более крутым участкам.',
    avgROI:         'Средний ROI = суммарный вклад медиа в продажи ÷ суммарный бюджет.\n\nИндустриальный benchmark: > 2× — отлично, 1-2× — приемлемо, < 1× — медиа в среднем не окупается.',
    saturation:     'Светофор насыщения каналов:\n🟢 Недонасыщен (mROAS > 1.5×) — кандидат на масштабирование\n🟡 Стабилен (0.8-1.5×) — оптимальная зона\n🔴 Перенасыщен (< 0.8×) — каждый дополнительный рубль работает в убыток',
  };

  // ── Phase 2 (Planning Mode) — audit pass 2 2026-05-02 ──
  // Auto-fetch forecast context when planning mode toggled. Cleared on project change.
  $effect(() => {
    const mode = $planningMode;
    const projectId = $activeProjectId;
    if (!projectId || mode !== 'planner') {
      forecastContext.set(null);
      return;
    }
    (async () => {
      try {
        const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId }));
        const ctx = /** @type {any} */ (await invoke('econ_forecast_context', { projectDir }));
        if (ctx?.status === 'ok') forecastContext.set(ctx);
      } catch { /* silent — planning mode degrades gracefully without context */ }
    })();
  });

  // Reset forecast config on project switch (P5 plan gap)
  $effect(() => {
    const _projectId = $activeProjectId;
    forecastConfig.set({ periods: null, periodLabel: null, budgetMoney: null, inflationPerChannel: null });
  });

  // ── Блок A — статус-карточка «Текущий бюджет» ─────────────
  // Display-бюджет всегда в money (рубли), чтобы суммы между каналами были сопоставимы.
  // Для optData используем current_spend_money (с unit_cost), fallback — current_spend.
  // Для decompose fallback ch.spend уже в money (см. decomposer.py).
  const currentTotalBudget = $derived.by(() => {
    if (optData?.channels) {
      return optData.channels.reduce((/** @type {number} */ s, /** @type {any} */ c) =>
        s + (c.current_spend_money ?? c.current_spend ?? 0), 0);
    }
    if (dData?.channels) {
      return dData.channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + (c.spend || 0), 0);
    }
    return 0;
  });

  // ROI × = money contribution / money spend. Оба берутся из decompose (ch.spend уже money).
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

  /** v1.0.16: derived inflation maps для inline overlay в Block C. */
  const ucOldMap = $derived($unitCosts ?? {});
  const ucNewMap = $derived(Object.fromEntries(channels.map((/** @type {string} */ ch) => [
    ch, (ucOldMap[ch] ?? 1.0) * (1 + (channelInflation[ch] ?? 0) / 100)
  ])));

  /** @type {Record<string, number>} current spend в НАТИВНЫХ единицах канала (raw).
   *  Hill-функции обучены на raw, поэтому слайдеры/scaledParams работают именно тут.
   *  Для decompose fallback используем raw_spend (не .spend, который теперь money).
   */
  const currentSpend = $derived.by(() => {
    if (optData?.channels) {
      return Object.fromEntries(optData.channels.map(/** @type {(c: any) => [string, number]} */ (c) => [c.name, c.current_spend]));
    }
    if (dData?.channels) {
      return Object.fromEntries(dData.channels.map(/** @type {(c: any) => [string, number]} */ (c) => [c.name, c.raw_spend ?? c.spend ?? 0]));
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

  /** Current KPI at current_spend (baseline for lift% — per-period prediction в рублях). */
  const currentKPI = $derived(predictKPI(currentSpend, scaledParams, yNorm));

  /**
   * miROAS per channel — marginal ROAS следующего рубля.
   *
   * L4 (math-fix v1.4 Section C, 2026-04-28): unified backend source. Both
   * decompose.json (idle) и optimize.json (post-optimize) теперь содержат
   * `mroi_current` в money axis (через _compute_mroas_money helper) + structured
   * `action`/`action_label`/`action_tone` (через compute_channel_action). UI
   * читает оба от backend → three-way alignment с HTML/PPTX commentary.
   *
   * Pre-fix (2026-04-25 → 2026-04-28): JS marginalROI fallback в Source #2 не
   * учитывал /unit_cost, /mean, adstock_factor → mixed units (Kagocel TRPs
   * pre-optimize 110.93× vs post-optimize 0.0285×). Closed by L4.
   *
   * Returns map: { ch: { value, status, action, actionLabel, actionTone, source } }.
   * status (для светофора): 'good'|'ok'|'low'|'unused' derived from action_tone:
   *   action='Scale'                  → 'good'  (🟢 масштабировать)
   *   action='Hold' | 'Watch'         → 'ok'    (🟡 стабильно/наблюдать)
   *   action='Reduce' | 'Cut'         → 'low'   (🔴 сократить)
   *   action='Uncertain' | spend=0    → 'unused' (⚪ нет данных)
   * source:
   *   'backend-optimize'   — после optimize (mroi_current от optimizer.py)
   *   'backend-decompose'  — idle, pre-optimize (mroi_current от decomposer.py)
   */
  const miROASMap = $derived.by(() => {
    /** @type {Record<string, {value: number, status: 'unused'|'good'|'ok'|'low', action: string, actionLabel: string, actionTone: string, actionReasoning: string, source: 'backend-optimize'|'backend-decompose'}>} */
    const map = {};

    /** Audit fix (2026-04-29): legacy optimization.json (saved pre-v1.0.16) had
     *  primitive Russian action vocabulary ('увеличить'/'сократить'/'сохранить').
     *  After Section C refactor, vocabulary = ACTION_KEYS ('Scale'/'Cut'/'Hold').
     *  Migration map handles cross-version display when customer loads old project.
     *  @type {Record<string, string>} */
    const LEGACY_ACTION_MIGRATION = {
      'увеличить': 'Scale',
      'сократить': 'Cut',
      'сохранить': 'Hold',
    };

    /** Audit fix (2026-04-29): Uncertain action covers 3 distinct causes —
     *  (a) zero spend (channel not in portfolio, no signal possible),
     *  (b) untrained channel (zero training variance), no useful mroi,
     *  (c) wide CI (value present but uncertain). Pre-fix: all 3 mapped к
     *  'unused' status which hides value via «—» display. Cause (c) had legit
     *  mroi (e.g. 1.5×) hidden, confusing customer. Fix: split by value —
     *  zero value → 'unused' (canonical no signal), non-zero → 'ok' (display
     *  value with neutral status, customer sees number with reasoning tooltip).
     *  @param {string} action @param {number} value */
    const actionToStatus = (action, value) => {
      if (action === 'Scale') return /** @type {const} */ ('good');
      if (action === 'Hold' || action === 'Watch') return /** @type {const} */ ('ok');
      if (action === 'Reduce' || action === 'Cut') return /** @type {const} */ ('low');
      // Uncertain: zero value = unused (canonical), non-zero = ok (CI/untrained edge)
      if (!Number.isFinite(value) || value === 0) return /** @type {const} */ ('unused');
      return /** @type {const} */ ('ok');
    };

    /** Resolve action key handling legacy migration + null fallback.
     *  @param {any} raw */
    const resolveAction = (raw) => {
      const s = raw == null ? 'Watch' : String(raw);
      return LEGACY_ACTION_MIGRATION[s] ?? s;
    };

    // Source #1: post-optimize (authoritative с optimizer signal)
    const opt = $optimizeData;
    if (opt?.channels && opt.channels.length > 0) {
      for (const ch of opt.channels) {
        const action = resolveAction(ch.action);
        const value = Number(ch.mroi_current ?? 0);
        map[ch.name] = {
          value: Number.isFinite(value) ? value : 0,
          status: actionToStatus(action, value),
          action,
          actionLabel: String(ch.action_label ?? ''),
          actionTone: String(ch.action_tone ?? 'neutral'),
          actionReasoning: String(ch.action_reasoning ?? ''),
          source: 'backend-optimize',
        };
      }
      return map;
    }

    // Source #2: pre-optimize idle — use decompose action (mROAS-only heuristic,
    // optimizer signal joins after run). Backend uses same _compute_mroas_money
    // helper — guaranteed money-axis math, no mixed-unit drift.
    const dec = $decomposeData;
    if (dec?.channels && dec.channels.length > 0) {
      for (const ch of dec.channels) {
        const action = resolveAction(ch.action);
        const value = Number(ch.mroi_current ?? 0);
        map[ch.name] = {
          value: Number.isFinite(value) ? value : 0,
          status: actionToStatus(action, value),
          action,
          actionLabel: String(ch.action_label ?? ''),
          actionTone: String(ch.action_tone ?? 'neutral'),
          actionReasoning: String(ch.action_reasoning ?? ''),
          source: 'backend-decompose',
        };
      }
      return map;
    }

    return map;
  });

  /** Светофор: подсчёт каналов по категориям насыщения (для блока A).
   *  L4: status field теперь derived напрямую от backend action_tone, не от
   *  локальных JS thresholds. Mapping: Scale→good, Hold/Watch→ok, Reduce/Cut→low,
   *  Uncertain→unused. */
  const saturationCount = $derived.by(() => {
    /** @type {{good: number, ok: number, low: number, unused: number}} */
    const counts = { good: 0, ok: 0, low: 0, unused: 0 };
    for (const ch of channels) {
      const r = miROASMap[ch];
      if (!r) continue;
      counts[r.status] += 1;
    }
    return counts;
  });

  /** Средняя инфляция по всем каналам — для UI-подсказки в блоке D. */
  const avgInflation = $derived(
    channels.length > 0
      ? channels.reduce((s, ch) => s + (channelInflation[ch] ?? 0), 0) / channels.length
      : 0
  );

  /** Shared channel budgets — source of truth for BudgetOptimizer & ResponseCurves */
  let channelBudgets = $state(/** @type {Record<string, number>} */ ({}));

  /** Optimal budgets from last run */
  let optimalBudgets = $state(/** @type {Record<string, number> | null} */ (null));

  /** Live KPI at channelBudgets (per-period prediction). Reacts to slider drag
   *  + L5 auto-apply animation. Used to scale displayKPI к live allocation. */
  const liveKPI = $derived(
    Object.keys(channelBudgets).length > 0 && Object.keys(scaledParams).length > 0
      ? predictKPI(channelBudgets, scaledParams, yNorm)
      : currentKPI
  );

  /** Display-KPI для блока A. baseTotal = decompose total_sales (KPI за весь
   *  период анализа в одной шкале с total budget). L5 (math-fix v1.4 Section C,
   *  2026-04-28): при applyOptimal channelBudgets анимируется к optimal_spend →
   *  liveKPI/currentKPI ratio scales displayKPI монотонно вверх в same period
   *  scale. Customer видит Прогноз KPI обновляющийся вместе со sliders, не
   *  frozen на baseline.
   *  Audit fix (2026-04-29): explicit Number.isFinite checks вместо truthiness
   *  (`!liveKPI` was true for legitimate 0 values too — false positive guard). */
  const displayKPI = $derived.by(() => {
    const baseTotal = Number.isFinite(dData?.total_sales) ? dData.total_sales : currentKPI;
    if (!Number.isFinite(currentKPI) || currentKPI <= 0) return baseTotal;
    if (!Number.isFinite(liveKPI)) return baseTotal;
    return baseTotal * (liveKPI / currentKPI);
  });

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
      // Берём raw_spend (native units для Hill), не .spend (money).
      const init = /** @type {Record<string, number>} */ ({});
      for (const ch of dec.channels) init[ch.name] = ch.raw_spend ?? ch.spend ?? 0;
      channelBudgets = init;
    }
  });

  // Sync live slider state → store. InsightsPanel слушает этот store и реактивно
  // пересчитывает mROAS/saturation на каждое движение слайдера, без полного прогона
  // оптимизатора.
  $effect(() => {
    optimizeLiveState.set({
      channelBudgets: { ...channelBudgets },
      channelMinPct: { ...channelMinPct },
      channelMaxPct: { ...channelMaxPct },
      globalMinPct: minPct,
      globalMaxPct: maxPct,
    });
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

  /** L8 (math-fix v1.4 Section C, 2026-04-29): количество каналов с per-channel
   *  override. Pre-fix: customer движет global Min/Max slider, но per-channel
   *  overrides остаются tacit — глобальные limits не применяются. Confusion source.
   *  Banner с reset action surfaces проблему когда expert section collapsed. */
  const overrideCount = $derived(
    channels.filter((/** @type {string} */ ch) => hasCustomLimit(ch)).length
  );

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

  // ── Phase 3: What-if ──────────────────────────────────────────────────────
  /** Native-эквивалент нового money-бюджета: масштабируем текущий native пропорционально.
   * @param {number} ratio */
  function nativeForMoneyRatio(ratio) {
    const currentNative = channels.reduce((s, ch) => s + (currentSpend[ch] ?? 0), 0);
    return currentNative * ratio;
  }

  async function runWhatIf() {
    whatIfRunning = true;
    whatIfError = null;
    try {
      const projectId = await ensureProjectId();
      if (!projectId) throw new Error('Проект не выбран');
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId }));
      // Phase 0.1.B fix: для mixed-units (TRPs+рубли) native total — арифметический
      // мусор (TRP count + рубли). Money budget — единственный осмысленный
      // constraint. Передаём его явно — backend auto-derive не сработает (target уже задан),
      // optimizer корректно scales к whatIfMult × currentTotalBudget.
      const targetMoneyBudget = currentTotalBudget * whatIfMult;
      const whatIfMax = Math.max(300, Math.ceil(whatIfMult * 200));
      const result = /** @type {any} */ (await invoke('econ_optimize', {
        projectDir,
        totalBudget: null,
        totalBudgetMoney: targetMoneyBudget,
        minPct: 0,
        maxPct: whatIfMax,
        minPerChannel: null,
        maxPerChannel: null,
        // AUDIT-4: pass per-group constraints для consistency с main optimize.
        // null когда user не задал → backend falls back к global (identical к pre-audit).
        // Brand max должен быть ≤ whatIfMax (whatIfMax обычно ≥300%, brandMax обычно ≤200%).
        brandMinPct,
        brandMaxPct,
        perfMinPct,
        perfMaxPct,
        unitCosts: get(unitCosts) ?? {},
        forecastPeriods: null,
        forecastPeriodLabel: null,
      }));
      if (result.status === 'ok') {
        whatIfResult = result;
      } else {
        throw new Error(result.message || 'Ошибка what-if');
      }
    } catch (/** @type {any} */ e) {
      whatIfError = String(e?.message || e);
    } finally {
      whatIfRunning = false;
    }
  }

  function resetWhatIf() {
    whatIfMult = 1.0;
    whatIfResult = null;
    whatIfError = null;
  }

  /** Сохранить What-if result как именованный сценарий.
   *  v1.0.16: optional unitCostsOverride — когда applyInflation=true,
   *  передаётся ucNew (uc0 × (1+infl/100)), сценарий сохраняется с post-inflation
   *  unit_costs. Backend econ_scenario принимает unit_costs для пересчёта money.
   *  KPI прогноз не меняется — объём медиа preserved через media_plan.
   *  @param {Record<string, number> | null} unitCostsOverride */
  async function saveWhatIfAsScenario(unitCostsOverride = null) {
    // v1.0.16: zero-scenario support — если whatIf не запущен но customer
    // активировал applyInflation, сохраняется current allocation с inflation
    // overlay. media_plan = current spend per channel (объём не меняется).
    const projectId = await ensureProjectId();
    if (!projectId) return;
    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId }));
      /** @type {Record<string, number[]>} */
      const mediaPlan = {};
      const sourceChannels = whatIfResult?.channels;
      if (sourceChannels) {
        for (const c of sourceChannels) mediaPlan[c.name] = [c.optimal_spend ?? 0];
      } else {
        // Zero scenario — use current allocation
        for (const ch of channels) mediaPlan[ch] = [currentSpend[ch] ?? 0];
      }
      const inflTag = unitCostsOverride ? '-infl' : '';
      const multTag = whatIfResult ? `${Math.round(whatIfMult * 100)}pct` : 'current';
      const name = `what-if-${multTag}${inflTag}-${Date.now().toString().slice(-6)}`;
      const payload = /** @type {any} */ ({
        projectDir, scenarioName: name, mediaPlan,
      });
      if (unitCostsOverride) payload.unitCosts = unitCostsOverride;
      const r = /** @type {any} */ (await invoke('econ_scenario', payload));
      if (r.status === 'ok') {
        whatIfSuccess = '✓ Сохранено как сценарий «' + name + '»';
        setTimeout(() => { whatIfSuccess = null; }, 3500);
      } else {
        whatIfError = r.message || 'Ошибка сохранения';
      }
    } catch (/** @type {any} */ e) {
      whatIfError = String(e?.message || e);
    }
  }

  // ── Phase 4: Прогноз с медиаинфляцией ─────────────────────────────────────
  /** Дефолтный процент инфляции per-канал по его category.
   * @param {string} ch */
  function defaultInflation(ch) {
    const cat = dData?.channels?.find(/** @param {any} c */ (c) => c.name === ch)?.category || 'mixed';
    return INFLATION_DEFAULTS[/** @type {keyof typeof INFLATION_DEFAULTS} */ (cat)] ?? 8;
  }

  // v1.0.16: Hydrate channelInflation ТОЛЬКО когда forecast блок expanded.
  // Pre-fix: defaults (8% per category) populated automatically при появлении
  // каналов — customer не активировал блок но «по-умолчанию» имел inflation
  // recommendations, что можно интерпретировать как авто-расчёт без согласия.
  // Post-fix: hydration deferred до момента когда customer открывает блок D
  // (expert disclosure). До тех пор channelInflation = {} → forecast не
  // выполняется автоматически.
  $effect(() => {
    if (!forecastExpanded || channels.length === 0) return;
    const next = /** @type {Record<string, number>} */ ({ ...channelInflation });
    let changed = false;
    for (const ch of channels) {
      if (next[ch] == null) {
        next[ch] = defaultInflation(ch);
        changed = true;
      }
    }
    if (changed) channelInflation = next;
  });

  async function runForecast() {
    forecastRunning = true;
    forecastError = null;
    try {
      // Новые unit_costs: старые × (1 + inflation%).
      const uc0 = get(unitCosts) ?? {};
      /** @type {Record<string, number>} */
      const ucNew = {};
      for (const ch of channels) {
        const oldU = uc0[ch] ?? 1.0;
        const infl = (channelInflation[ch] ?? 0) / 100;
        ucNew[ch] = oldU * (1 + infl);
      }
      const currentMoney = channels.reduce((s, ch) => s + (currentSpend[ch] ?? 0) * (uc0[ch] ?? 1.0), 0);

      // ── Режим «Сохранить объём»: raw_spend per channel НЕ меняется ──
      // v1.0.16 audit fix: pre-fix вызывал optimizer с native-budget constraint
      // и maxPct=300 → optimizer redistributed allocation в новой экономике,
      // показывал KPI lift +35%. Customer ожидал противоположного — объём
      // медиа сохраняется, цена растёт, KPI = неизменный (Hill saturation на
      // raw_spend которые остались прежними). Fix: skip optimizer для volume
      // mode, build static result локально (per-channel raw_spend = current,
      // money = raw × ucNew, lift_pct = 0).
      if (forecastMode === 'volume') {
        const newMoneyTotal = channels.reduce(
          (s, ch) => s + (currentSpend[ch] ?? 0) * (ucNew[ch] ?? 1.0), 0
        );
        const channelsResult = channels.map((ch) => {
          const raw = currentSpend[ch] ?? 0;
          const oldMoney = raw * (uc0[ch] ?? 1.0);
          const newMoney = raw * (ucNew[ch] ?? 1.0);
          return {
            name: ch,
            current_spend: raw,
            optimal_spend: raw, // объём не меняется
            current_spend_money: oldMoney,
            optimal_spend_money: newMoney,
            unit_cost: ucNew[ch] ?? 1.0,
            delta_pct: 0,
          };
        });
        forecastResult = {
          status: 'ok',
          mode: 'volume',
          ucOld: uc0,
          ucNew,
          currentMoney,
          total_budget_money: newMoneyTotal,
          expected_lift_pct: 0, // KPI не меняется при сохранении объёма
          channels: channelsResult,
          insight: (
            `При сохранении медиа-объёма потребуется ${(newMoneyTotal / 1e6).toFixed(1)} млн ₽ ` +
            `(было ${(currentMoney / 1e6).toFixed(1)} млн ₽, рост ${((newMoneyTotal / Math.max(currentMoney, 1) - 1) * 100).toFixed(1)}%). ` +
            `KPI остаётся прежним — медиа-объём (TRP/показы) не изменился, выросли лишь закупочные цены.`
          ),
        };
        return;
      }

      // ── Режим «Сохранить бюджет»: total money = currentMoney, optimizer ──
      // redistributes raw_spend per channel. Объём упадёт (меньше единиц
      // медиа на ту же сумму при выросших ценах), KPI снизится через Hill.
      const projectId = await ensureProjectId();
      if (!projectId) throw new Error('Проект не выбран');
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId }));

      const result = /** @type {any} */ (await invoke('econ_optimize', {
        projectDir,
        totalBudget: null,
        totalBudgetMoney: currentMoney,
        minPct: 0,
        maxPct: 300,
        minPerChannel: null,
        maxPerChannel: null,
        // AUDIT-4: pass per-group constraints для consistency с main optimize.
        brandMinPct,
        brandMaxPct,
        perfMinPct,
        perfMaxPct,
        unitCosts: ucNew,
        forecastPeriods: null,
        forecastPeriodLabel: null,
      }));
      if (result.status === 'ok') {
        forecastResult = { ...result, mode: forecastMode, ucOld: uc0, ucNew, currentMoney };
      } else {
        throw new Error(result.message || 'Ошибка прогноза');
      }
    } catch (/** @type {any} */ e) {
      forecastError = String(e?.message || e);
    } finally {
      forecastRunning = false;
    }
  }

  function resetForecast() {
    /** @type {Record<string, number>} */
    const next = {};
    for (const ch of channels) next[ch] = defaultInflation(ch);
    channelInflation = next;
    forecastResult = null;
    forecastError = null;
    forecastMode = 'volume';
  }

  /** Сохранить Forecast result как именованный сценарий. */
  async function saveForecastAsScenario() {
    if (!forecastResult?.channels) return;
    const projectId = await ensureProjectId();
    if (!projectId) return;
    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId }));
      /** @type {Record<string, number[]>} */
      const mediaPlan = {};
      for (const c of forecastResult.channels) mediaPlan[c.name] = [c.optimal_spend ?? 0];
      const avgInfl = Math.round(channels.reduce((s, ch) => s + (channelInflation[ch] ?? 0), 0) / Math.max(channels.length, 1));
      const name = `forecast-${forecastMode}-${avgInfl}pct-${Date.now().toString().slice(-6)}`;
      const r = /** @type {any} */ (await invoke('econ_scenario', {
        projectDir, scenarioName: name, mediaPlan,
      }));
      if (r.status === 'ok') {
        forecastSuccess = '✓ Сохранено как сценарий «' + name + '»';
        setTimeout(() => { forecastSuccess = null; }, 3500);
      } else {
        forecastError = r.message || 'Ошибка сохранения';
      }
    } catch (/** @type {any} */ e) {
      forecastError = String(e?.message || e);
    }
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
      // Phase 0.1 hotfix #18 (2026-04-26): pass per-channel constraints
      // ONLY when they differ from current global. Pre-fix bug: $effect:355
      // auto-initialized channelMinPct[ch] = minPct on first render. When user
      // moved global slider after that, per-channel остались на старом значении
      // and **overrode** new global → backend получал stale 100/190 вместо
      // 10/300. Now: skip пере-channel value if it equals global (user не
      // меняла его явно) — backend applies new global automatically.
      let minPerChannel = null;
      let maxPerChannel = null;
      if ($expertMode && channels.length > 0) {
        const minMap = /** @type {Record<string, number>} */ ({});
        const maxMap = /** @type {Record<string, number>} */ ({});
        for (const ch of channels) {
          // Передаём ТОЛЬКО если значение отличается от текущего global —
          // тогда это явная per-channel настройка экспертного режима.
          if (channelMinPct[ch] != null && channelMinPct[ch] !== minPct) {
            minMap[ch] = channelMinPct[ch];
          }
          if (channelMaxPct[ch] != null && channelMaxPct[ch] !== maxPct) {
            maxMap[ch] = channelMaxPct[ch];
          }
        }
        if (Object.keys(minMap).length > 0) minPerChannel = minMap;
        if (Object.keys(maxMap).length > 0) maxPerChannel = maxMap;
      }
      // Phase 0.1 hotfix #17 (2026-04-26): pass money budget explicitly.
      // Pre-fix: totalBudgetMoney=null → backend native sum constraint.
      // На mixed-units (TRPs + рубли) native sum арифметически бессмыслен —
      // optimizer не находил redistribution, all caps на current. Money mode
      // даёт physically meaningful constraint (sum money = const), позволяет
      // SLSQP redistribute между каналами при условии same total money budget.
      // Phase 2 — planning mode dispatch. analyst → forecast_periods=null
      // (byte-exact backward compat). planner → forecast_periods + budget from
      // forecastConfig store. forecastConfig.budgetMoney overrides currentTotalBudget.
      const fcfg = get(forecastConfig);
      const isPlanning = get(planningMode) === 'planner' && fcfg.periods != null && fcfg.periods >= 1;
      const planningBudget = isPlanning && fcfg.budgetMoney != null && fcfg.budgetMoney > 0
        ? fcfg.budgetMoney
        : null;
      const finalTotalBudgetMoney = planningBudget
        ?? (Number.isFinite(currentTotalBudget) && currentTotalBudget > 0 ? currentTotalBudget : null);

      const result = /** @type {any} */ (await invoke('econ_optimize', {
        projectDir,
        totalBudget: null,
        totalBudgetMoney: finalTotalBudgetMoney,
        minPct,
        maxPct,
        minPerChannel,
        maxPerChannel,
        // F.2 — per-group constraints (D.3 backend). null = optimizer falls back к global.
        brandMinPct,
        brandMaxPct,
        perfMinPct,
        perfMaxPct,
        unitCosts: get(unitCosts) ?? {},
        // Phase 2 — null преserves analyst mode byte-exact
        forecastPeriods: isPlanning ? fcfg.periods : null,
        forecastPeriodLabel: isPlanning ? fcfg.periodLabel : null,
      }));

      if (result.status === 'ok') {
        optimizeData.set(result);
        stepState = 'done';

        // Build optimalBudgets for slider animation targets
        const ob = /** @type {Record<string, number>} */ ({});
        for (const ch of (result.channels ?? [])) ob[ch.name] = ch.optimal_spend;
        optimalBudgets = ob;

        // L5 (math-fix v1.4 Section C, 2026-04-28): auto-apply optimal allocation
        // к sliders. Pre-fix: customer кликал «Оптимизировать» → backend возвращал
        // optimal_spend, Δ% labels рядом со sliders отображались, но slider positions
        // + money values + Прогноз KPI оставались на current. Customer не видел
        // результат своей оптимизации без manual click. Auto-apply устраняет UX gap.
        // Animation 800ms (через requestAnimationFrame) визуально показывает движение.
        // tick() ensures $effect at line ~340 fires first (resets channelBudgets к
        // current_spend); applyOptimal then animates from clean baseline → optimal.
        await tick();
        applyOptimal();

        // O1.2 (Phase 0.1): snapshot settings AFTER success so dirty-state
        // becomes false until user changes something. Same shape as
        // optimizeSettingsDirty derived to ensure exact match.
        lastOptimizeSettings = JSON.stringify({
          minPct, maxPct,
          brandMin: brandMinPct, brandMax: brandMaxPct,
          perfMin: perfMinPct, perfMax: perfMaxPct,
          cMin: { ...channelMinPct },
          cMax: { ...channelMaxPct },
          budget: totalBudgetInput,
        });
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

  <!-- Onboarding re-trigger — небольшая ссылка сверху для повторного тура -->
  <div class="onboarding-hint">
    <button class="btn-hint" onclick={restartOnboarding} title="Показать обзор блоков A→E">
      ? Показать тур
    </button>
  </div>

  <!-- Error banner -->
  {#if stepState === 'error' && errorMessage}
    <div class="error-banner">
      <span class="error-icon">⚠</span>
      <span class="error-text">{errorMessage}</span>
      <button class="btn-retry" onclick={runOptimize}>Повторить</button>
    </div>
  {/if}

  <!-- Trust banner — наследуем smell_flags от decompose -->
  {#if dData?.smell_flags?.length}
    <TrustBanner flags={dData.smell_flags} />
  {/if}

  <!-- ══════════ Phase 2 — Mode toggle (Analyst | Planner) ══════════ -->
  <section class="planning-mode-toggle" aria-label="Режим работы">
    <div class="mode-pills" role="radiogroup">
      <button
        type="button"
        role="radio"
        aria-checked={$planningMode === 'analyst'}
        class:active={$planningMode === 'analyst'}
        onclick={() => planningMode.set('analyst')}
      >
        <span class="mode-label">Аналитик</span>
        <span class="mode-desc">обучающий период</span>
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={$planningMode === 'planner'}
        class:active={$planningMode === 'planner'}
        onclick={() => planningMode.set('planner')}
      >
        <span class="mode-label">Планнер</span>
        <span class="mode-desc">будущий период</span>
      </button>
    </div>
    <p class="mode-hint">
      {#if $planningMode === 'planner'}
        Подберите оптимальное распределение бюджета для будущего периода — оптимизатор переключился на планирующий режим
        (per-period Hill summation, 3-way alignment с scenario engine).
      {:else}
        Оптимизатор работает в обучающем масштабе времени. Доли каналов валидны для сопоставимого периода.
      {/if}
    </p>
  </section>

  <!-- Phase 2 — Forecast horizon picker (только в planner mode) -->
  {#if $planningMode === 'planner' && currentTotalBudget > 0}
    <ForecastHorizonPicker
      trainNPeriods={$forecastContext?.train_n_periods ?? 52}
      currentBudgetMoney={currentTotalBudget}
    />
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
        <div class="status-value">{fmtBudget(displayKPI)}</div>
        <div class="status-sub">за весь период анализа</div>
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

    <!-- Planning horizon warning — explicit honest disclosure что цифры в training scale.
         Phase 1 (2026-05-02): пока Phase 2 (forecast_horizon parameter) не реализована,
         планнерам нужно понимать что absolute amounts = training period (3 года),
         а доли каналов универсальны для сопоставимых периодов (год/квартал/полугодие).
         Roadmap: project_econometrica_forecast_horizon_proposal.md — proper Planning Mode. -->
    <div class="planning-warn">
      <div class="planning-warn-icon">📅</div>
      <div class="planning-warn-body">
        <div class="planning-warn-title">Текущая версия — анализ исторического распределения</div>
        <div class="planning-warn-text">
          Optimizer показывает оптимум для бюджета <strong>периода обучения</strong>
          (за все годы данных). Для планирования будущего периода:
        </div>
        <ul class="planning-warn-list">
          <li>
            <strong>Используйте доли каналов</strong> (например, «TV — 84%, Performance — 1.3%, Search — 0.4%»).
            Они валидны для <strong>сопоставимого</strong> по длине периода (год/полугодие/квартал — если обучали на нескольких годах).
          </li>
          <li>
            <strong>НЕ применяйте absolute суммы напрямую</strong> к forecast budget — они для всего training periodа.
            Делите на (training_horizon ÷ forecast_horizon): если обучали на 3 годах, для года делите на 3.
          </li>
          <li>
            <strong>Forecast period должен быть ≥ training granularity.</strong>
            Для месячных данных нельзя планировать на день/неделю — saturation калибрована per month.
          </li>
          <li>
            <strong>Прогноз KPI %</strong> также рассчитан для training horizon. Для другого периода —
            реальный лифт пропорционален длительности.
          </li>
        </ul>
        <div class="planning-warn-roadmap">
          🚧 В roadmap: «Период планирования» (год / квартал / полугодие) + «Бюджет на период» —
          backend пересчитает all numbers в forecast scale напрямую, без manual ratios.
        </div>
      </div>
    </div>

    <!-- Controls -->
    <div class="controls-card">
      <div class="controls-row">
        <label class="ctrl-label">
          <span class="ctrl-name">Мин. %<span class="help-icon" title={HELP.minPct}>?</span></span>
          <input type="range" min={0} max={100} step={5} bind:value={minPct} class="mini-slider" />
          <span class="mini-val">{minPct}%</span>
        </label>
        <label class="ctrl-label">
          <span class="ctrl-name">Макс. %<span class="help-icon" title={HELP.maxPct}>?</span></span>
          <input type="range" min={100} max={500} step={10} bind:value={maxPct} class="mini-slider" />
          <span class="mini-val">{maxPct}%</span>
        </label>
        <!-- L9 final (math-fix v1.4 Section C, 2026-04-29): UI-control скрыт до
             v1.1. Pre-fix v1.0.15: checkbox активен, переключал budget mode но
             free-budget implementation incomplete. v1.0.16 Day 4: disabled с
             tooltip — UX дискомфорт (customer видит control без возможности
             использовать). Final v1.0.16: скрыт полностью, backend всегда
             получает budget_mode='fixed' (default). Возвращаем в UI когда
             true free-budget mode будет реализован в v1.1 (~16-24h работы:
             optimizer math + small-data validation + UX paths).
             budgetLocked store сохранён к Day 4 default (true) — passes к
             BudgetOptimizer locked prop без визуального selector. -->
        <button
          class="btn-run"
          onclick={runOptimize}
          disabled={stepState === 'optimizing'}
          title={HELP.runOptimize}
        >
          {stepState === 'optimizing' ? 'Оптимизирую...' : '🎯 Оптимизировать бюджет'}
        </button>
        {#if optimizeSettingsDirty}
          <span class="dirty-hint" title="Настройки изменились — перезапустите оптимизацию для актуального результата">
            ⚙️ Настройки изменились
          </span>
        {/if}
      </div>

      <!-- F.1+F.3 (D.3 frontend): per-group sliders для Trust 3 brand vs performance.
           Collapsed by default. Visible только когда модель hierarchical (≥2 brand или
           ≥2 perf в channelCategories). Backend применяет 3-level precedence:
           per-channel > per-group > global. Mixed → fall back к global. -->
      {#if hasGroupSplit}
        <details
          class="group-sliders"
          open={groupSlidersExpanded}
          ontoggle={(/** @type {any} */ e) => groupSlidersExpanded = e.currentTarget.open}
        >
          <summary class="group-summary">
            <span class="group-icon">🎚️</span>
            <span>Per-group ограничения (brand vs performance)</span>
            {#if brandMinPct != null || brandMaxPct != null || perfMinPct != null || perfMaxPct != null}
              <span class="group-active-badge" title="Per-group ограничения активны">●</span>
            {/if}
            {#if brandMinPct != null || brandMaxPct != null || perfMinPct != null || perfMaxPct != null}
              <button
                class="btn-reset-group"
                onclick={(/** @type {any} */ e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  brandMinPct = null;
                  brandMaxPct = null;
                  perfMinPct = null;
                  perfMaxPct = null;
                }}
                title="Вернуть per-group ограничения к defaults (использовать глобальные)"
                aria-label="Сбросить per-group ограничения"
              >
                ↺ Сбросить per-group
              </button>
            {/if}
          </summary>

          <!-- Инструкции по типичным сценариям использования. -->
          <div class="group-instructions">
            <div class="group-instr-title">Типичные сценарии:</div>
            <ul class="group-instr-list">
              <li>
                <strong>«Сохранить TV-контракт»</strong> — Brand закреплён годовым контрактом (нельзя резко сократить). Поставь
                <code>Brand Мин. = 90%</code>, <code>Brand Макс. = 110%</code>. Performance оставь свободным (Мин. 20%, Макс. 200%) — оптимизатор перераспределит внутри performance + Статьи.
              </li>
              <li>
                <strong>«Растить performance, не трогать brand»</strong> — поставь
                <code>🔒 Lock Brand 100%</code> (Brand=100/100), Performance оставь свободным. Optimizer перебросит деньги между performance-каналами без касания TV/OOH.
              </li>
              <li>
                <strong>«Точно знаю что хочу +30% в performance»</strong> — <code>Perf Мин. = 130%</code>, остальное free. Optimizer найдёт оптимум при условии что суммарный performance ≥ 130% от текущего.
              </li>
              <li>
                <strong>⚠️ Lock+Lock = 0% lift.</strong> Если оба <code>🔒 Lock 100%</code> заданы и есть только 1 mixed канал — optimizer заморожен (нет степеней свободы). Сначала очисти один из Lock'ов или дай группе свободу (например, Brand 95-105%).
              </li>
            </ul>
            <div class="group-instr-defaults">
              <strong>По умолчанию</strong> per-group отключены — все каналы используют глобальные Мин/Макс (20% / 200%). Активируй только когда нужны разные правила для brand vs performance.
            </div>
          </div>

          <div class="group-grid">
            <div class="group-col">
              <div class="group-col-title">🎨 Brand-каналы (TV, OOH, Brand-PR)</div>
              <label class="ctrl-label">
                <span class="ctrl-name">Brand Мин. %<span class="help-icon" title={HELP.brandMin}>?</span></span>
                <input
                  type="range" min={0} max={100} step={5}
                  value={brandMinPct ?? minPct}
                  oninput={(/** @type {any} */ e) => brandMinPct = Number(e.currentTarget.value)}
                  class="mini-slider"
                  aria-label="Brand минимальный процент"
                  aria-valuetext={brandMinPct != null ? `${brandMinPct} процентов (явно задан)` : `${minPct} процентов (глобальный)`}
                />
                <span class="mini-val">{brandMinPct != null ? `${brandMinPct}%` : `— (${minPct}%)`}</span>
                {#if brandMinPct != null}
                  <button class="btn-clear" onclick={() => brandMinPct = null} title="Сбросить к глобальному" aria-label="Сбросить Brand Мин. к глобальному">×</button>
                {/if}
              </label>
              <label class="ctrl-label">
                <span class="ctrl-name">Brand Макс. %<span class="help-icon" title={HELP.brandMax}>?</span></span>
                <input
                  type="range" min={100} max={500} step={10}
                  value={brandMaxPct ?? maxPct}
                  oninput={(/** @type {any} */ e) => brandMaxPct = Number(e.currentTarget.value)}
                  class="mini-slider"
                  aria-label="Brand максимальный процент"
                  aria-valuetext={brandMaxPct != null ? `${brandMaxPct} процентов (явно задан)` : `${maxPct} процентов (глобальный)`}
                />
                <span class="mini-val">{brandMaxPct != null ? `${brandMaxPct}%` : `— (${maxPct}%)`}</span>
                {#if brandMaxPct != null}
                  <button class="btn-clear" onclick={() => brandMaxPct = null} title="Сбросить к глобальному" aria-label="Сбросить Brand Макс. к глобальному">×</button>
                {/if}
              </label>
              <button
                class="btn-lock-group"
                onclick={() => { brandMinPct = 100; brandMaxPct = 100; }}
                title="Зафиксировать brand на текущем значении (контрактные обязательства)"
              >
                🔒 Lock Brand 100%
              </button>
            </div>
            <div class="group-col">
              <div class="group-col-title">📈 Performance-каналы (Search, Social, Programmatic)</div>
              <label class="ctrl-label">
                <span class="ctrl-name">Perf Мин. %<span class="help-icon" title={HELP.perfMin}>?</span></span>
                <input
                  type="range" min={0} max={100} step={5}
                  value={perfMinPct ?? minPct}
                  oninput={(/** @type {any} */ e) => perfMinPct = Number(e.currentTarget.value)}
                  class="mini-slider"
                  aria-label="Performance минимальный процент"
                  aria-valuetext={perfMinPct != null ? `${perfMinPct} процентов (явно задан)` : `${minPct} процентов (глобальный)`}
                />
                <span class="mini-val">{perfMinPct != null ? `${perfMinPct}%` : `— (${minPct}%)`}</span>
                {#if perfMinPct != null}
                  <button class="btn-clear" onclick={() => perfMinPct = null} title="Сбросить к глобальному" aria-label="Сбросить Perf Мин. к глобальному">×</button>
                {/if}
              </label>
              <label class="ctrl-label">
                <span class="ctrl-name">Perf Макс. %<span class="help-icon" title={HELP.perfMax}>?</span></span>
                <input
                  type="range" min={100} max={500} step={10}
                  value={perfMaxPct ?? maxPct}
                  oninput={(/** @type {any} */ e) => perfMaxPct = Number(e.currentTarget.value)}
                  class="mini-slider"
                  aria-label="Performance максимальный процент"
                  aria-valuetext={perfMaxPct != null ? `${perfMaxPct} процентов (явно задан)` : `${maxPct} процентов (глобальный)`}
                />
                <span class="mini-val">{perfMaxPct != null ? `${perfMaxPct}%` : `— (${maxPct}%)`}</span>
                {#if perfMaxPct != null}
                  <button class="btn-clear" onclick={() => perfMaxPct = null} title="Сбросить к глобальному" aria-label="Сбросить Perf Макс. к глобальному">×</button>
                {/if}
              </label>
              <button
                class="btn-lock-group"
                onclick={() => { perfMinPct = 100; perfMaxPct = 100; }}
                title="Зафиксировать performance на текущем значении"
              >
                🔒 Lock Performance 100%
              </button>
            </div>
          </div>
          <p class="group-hint">
            Brand/Perf max должны быть ≤ глобального Макс ({maxPct}%) — иначе backend вернёт ошибку constraint hierarchy.
            Mixed-каналы всегда наследуют глобальные ограничения.
          </p>
          {#if groupConstraintWarnings.length > 0}
            <div class="group-warnings" role="alert">
              {#each groupConstraintWarnings as warn}
                <div class="group-warn-line">⚠ {warn}</div>
              {/each}
            </div>
          {/if}
        </details>
      {/if}
    </div>

    <!-- L8: per-channel override warning. Persistent banner когда есть каналы
         с individual Min/Max — surfaces проблему когда expert section collapsed
         (где иначе orange dot indicators скрыты). -->
    {#if overrideCount > 0}
      <div class="override-banner">
        <span class="banner-icon">🎚️</span>
        <p class="banner-text">
          У <strong>{overrideCount}</strong>
          {overrideCount === 1 ? 'канала' : (overrideCount < 5 ? 'каналов' : 'каналов')}
          задан per-channel Мин/Макс — глобальные ограничения выше для них не применяются.
        </p>
        <button class="btn-override-reset" onclick={resetChannelLimits}>
          ↺ Сбросить все
        </button>
      </div>
    {/if}

    <!-- Экспертный режим: per-channel ограничения Мин/Макс -->
    <!-- v1.0.16: collapsible expert disclosure (visible to all users, not gated
         to global $expertMode). Default collapsed — customer notices availability
         через arrow icon. Click expand → per-channel Min/Max + preset buttons.
         Same info-toggle pattern как ReportStep cover letter / interpretation. -->
    {#if channels.length > 0}
      <details class="expert-disclosure" open={expertExpanded} ontoggle={(/** @type {any} */ e) => expertExpanded = e.currentTarget.open}>
        <summary class="expert-toggle">
          <span class="expert-arrow">▸</span>
          <span class="expert-badge">ЭКСПЕРТ</span>
          <span class="expert-toggle-title">Ограничения по каналам</span>
          <span class="expert-toggle-hint">— per-channel Мин/Макс для баинговых сделок и фиксированных контрактов</span>
          {#if overrideCount > 0}
            <span class="expert-toggle-count">{overrideCount} активных</span>
          {/if}
        </summary>
        <div class="expert-disclosure-body">
        <div class="expert-header">
          <span class="expert-subtitle">Глобальные Мин/Макс выше применяются ко всем каналам по умолчанию. Здесь — индивидуальные ограничения для каждого канала.</span>
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
          Пресеты — быстрая точка старта; ручной ввод даёт полный контроль.
        </p>
        </div>
      </details>
    {/if}

    <!-- L7 (math-fix v1.4 Section C, 2026-04-29): edge-case banners для honest
         объяснения когда optimizer не нашёл lift или не может оптимизировать.
         Mutually exclusive (priority order: baseline_zero > binding > converged).
         Pre-fix: customer видел только «+0.0%» без context — терял доверие к
         optimizer'у думая что он сломан, даже когда он correctly reported
         constraint state. Surfaces backend flags из Section A + L10 fix. -->
    {#if optData?.baseline_zero}
      <div class="edge-banner banner-error">
        <span class="banner-icon">🚨</span>
        <p class="banner-text">
          <strong>Медиа-вклад равен нулю.</strong>
          Текущая аллокация не даёт измеримого эффекта на KPI — оптимизация
          невозможна. Проверьте качество данных на шаге «Валидация» (нулевые
          spend, отсутствие связи с KPI, untrained channels).
        </p>
      </div>
    {:else if optData?.binding_constraints}
      <div class="edge-banner banner-warn">
        <span class="banner-icon">⚠️</span>
        <p class="banner-text">
          <strong>Все каналы упёрлись в границы.</strong>
          Optimizer не может найти улучшение при текущих ограничениях. Расширьте
          глобальные Мин/Макс или сбросьте per-channel overrides (рекомендуем 10/300%).
        </p>
      </div>
    {:else if optData?.converged_at_current}
      <div class="edge-banner banner-info">
        <span class="banner-icon">ℹ️</span>
        <p class="banner-text">
          <strong>Текущая аллокация уже близка к оптимуму</strong> при заданных
          ограничениях. Чтобы найти больший lift, попробуйте расширить границы
          (Мин 10% / Макс 300%) или сбросить per-channel overrides.
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
            unitCosts={$unitCosts}
            displayBaseKPI={displayKPI}
            backendLiftPct={optData?.expected_lift_pct ?? null}
          />
        </div>
        <ExpandableCard title="Response Curves" tourKey="optimize-response-curves">
          {#if optData?.response_curves && Object.keys(scaledParams).length > 0}
            <ResponseCurves
              responseCurves={optData.response_curves}
              {channelBudgets}
              {scaledParams}
              {channels}
              onBudgetChange={handleBudgetChange}
              unitCosts={$unitCosts}
            />
          {:else}
            <div class="no-curves">Запустите оптимизацию для отображения кривых</div>
          {/if}
        </ExpandableCard>
      </div>

      <!-- miROAS table -->
      {#if Object.keys(miROASMap).length > 0}
        <div class="card miroas-card">
          <div class="card-title">
            miROAS — предельная отдача следующего рубля<span class="help-icon" title={HELP.miROAS}>?</span>
          </div>
          <div class="miroas-table">
            {#each channels as ch}
              {@const r = miROASMap[ch] ?? { value: 0, status: 'unused', action: 'Watch', actionLabel: '', actionTone: 'neutral', actionReasoning: '' }}
              {@const cls =
                r.status === 'good' ? 'miroas-good' :
                r.status === 'ok'   ? 'miroas-ok' :
                r.status === 'low'  ? 'miroas-low' : 'miroas-unused'}
              {@const emoji =
                r.status === 'good' ? '🟢' :
                r.status === 'ok'   ? '🟡' :
                r.status === 'low'  ? '🔴' : '⚪'}
              <!-- Audit fix (2026-04-29): tooltip surfaces action_reasoning from
                   backend (compute_channel_action). For Uncertain channels с wide
                   CI tooltip объясняет «CI [...] шире чем mROAS» вместо
                   misleading «Под наблюдением» без context. -->
              {@const tooltip = r.actionReasoning || r.actionLabel || 'Под наблюдением'}
              <div class="miroas-row {cls}">
                <span class="miroas-name">{ch}</span>
                <span class="miroas-value">
                  {r.status === 'unused' ? '—' : r.value.toFixed(2) + '×'}
                </span>
                <span class="miroas-hint" title={tooltip}>{emoji} {r.actionLabel || 'Под наблюдением'}</span>
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
  {#if channels.length > 0}
    {@const curMoney = channels.reduce((s, ch) => s + (currentSpend[ch] ?? 0) * ((($unitCosts?.[ch]) ?? 1.0)), 0)}
    {@const newMoney = curMoney * whatIfMult}
    {@const deltaMoney = newMoney - curMoney}
    <!-- KPI-прогноз = total_sales × (1 + lift%). Lift backend считает в пространстве
         Hill-effect (media-вклад). Для total KPI применяем его к total_sales целиком
         — приближение, но в той же шкале с блоком A. -->
    {@const whatIfKPI = whatIfResult && dData?.total_sales
      ? dData.total_sales * (1 + (whatIfResult.expected_lift_pct ?? 0) / 100)
      : null}
    <section class="block block-whatif">
      <div class="block-header">
        <span class="block-letter">C</span>
        <h3 class="block-title">What-if: изменённый бюджет</h3>
        <span class="block-subtitle">— а если бюджет станет другим?</span>
      </div>

      <div class="whatif-controls">
        <label class="whatif-label">Новый бюджет: <b>{fmtBudget(newMoney)}</b>
          <span class="whatif-delta" class:positive={deltaMoney > 0} class:negative={deltaMoney < 0}>
            {deltaMoney > 0 ? '+' : ''}{((whatIfMult - 1) * 100).toFixed(0)}%
            ({deltaMoney > 0 ? '+' : ''}{fmtBudget(Math.abs(deltaMoney))})
          </span>
        </label>
        <input
          type="range"
          class="whatif-slider"
          min="0.5"
          max="2.0"
          step="0.05"
          bind:value={whatIfMult}
        />
        <div class="whatif-actions">
          <button class="btn-run" onclick={runWhatIf} disabled={whatIfRunning || Math.abs(whatIfMult - 1) < 0.01}>
            {whatIfRunning ? 'Считаю…' : 'Пересчитать'}
          </button>
          <button class="btn-reset-sm" onclick={resetWhatIf} disabled={whatIfRunning}>↺ Сбросить</button>
        </div>
      </div>

      {#if whatIfError}
        <div class="inline-error">⚠ {whatIfError}</div>
      {/if}
      {#if whatIfSuccess}
        <div class="inline-success">{whatIfSuccess}</div>
      {/if}

      <!-- v1.0.16: compare-row visible всегда (когда есть channels). Levels:
           1. baseline: показывается только Current cell
           2. + whatIfResult: добавляется Right cell с New budget
           3. + applyInflation: Right cell shows inflated total
           4. whatIfResult + applyInflation: Right cell shows New + inflation. -->
      {#if channels.length > 0}
        {@const inflatedOptimal = whatIfResult?.channels
          ? whatIfResult.channels.reduce((/** @type {number} */ s, /** @type {any} */ c) =>
              s + (c.optimal_spend ?? 0) * (ucNewMap[c.name] ?? 1.0), 0)
          : 0}
        {@const inflatedCurrent = channels.reduce((/** @type {number} */ s, /** @type {string} */ ch) =>
          s + (currentSpend[ch] ?? 0) * (ucNewMap[ch] ?? 1.0), 0)}
        {@const rightTotal = whatIfResult
          ? (applyInflation ? inflatedOptimal : newMoney)
          : (applyInflation ? inflatedCurrent : null)}
        {@const showRight = rightTotal != null}
        <div class="whatif-compare">
          <div class="compare-row">
            <div class="compare-cell">
              <div class="compare-label">Текущий бюджет</div>
              <div class="compare-value">{fmtBudget(curMoney)}</div>
              <div class="compare-sub">KPI: {fmtBudget(dData?.total_sales ?? 0)}</div>
            </div>
            {#if showRight}
              <div class="compare-arrow">→</div>
              <div class="compare-cell highlight">
                <div class="compare-label">
                  {#if whatIfResult}Новый бюджет{:else}С учётом инфляции{/if}{#if applyInflation && whatIfResult} <span class="inflation-tag">+ инфляция</span>{/if}
                </div>
                <div class="compare-value">{fmtBudget(rightTotal)}</div>
                <div class="compare-sub">
                  {#if whatIfResult}
                    KPI: {fmtBudget(whatIfKPI ?? 0)}
                    <span class="lift" class:positive={whatIfResult.expected_lift_pct > 0} class:negative={whatIfResult.expected_lift_pct < 0}>
                      ({whatIfResult.expected_lift_pct > 0 ? '+' : ''}{whatIfResult.expected_lift_pct.toFixed(1)}%)
                    </span>
                    {#if applyInflation && (inflatedOptimal - newMoney) > 0}
                      <span class="inflation-extra">+ {fmtBudget(inflatedOptimal - newMoney)} на инфляцию (без изменения KPI)</span>
                    {/if}
                  {:else}
                    KPI: {fmtBudget(dData?.total_sales ?? 0)} <span class="inflation-extra">— без изменений (объём медиа сохранён)</span>
                  {/if}
                </div>
              </div>
            {/if}
          </div>
          {#if whatIfResult?.insight}
            <div class="whatif-insight">{whatIfResult.insight}</div>
          {/if}
        </div>
      {/if}

      <!-- v1.0.16: интегрированный inflation overlay (был Block D). Customer
           опционально активирует — учёт медиа-инфляции на следующий период.
           Объём медиа не меняется → KPI не меняется. Растёт лишь бюджет
           (CPP/CPM × 1+infl). Сохраняется в сценарии если флаг включён.
           Disclosure visible всегда — customer может настроить inflation
           заранее, до запуска what-if. Save button — только после whatIfResult. -->
      <details class="forecast-inline expert-disclosure" open={forecastExpanded} ontoggle={(/** @type {any} */ e) => forecastExpanded = e.currentTarget.open}>
        <summary class="forecast-inline-summary expert-toggle">
          <span class="forecast-arrow expert-arrow">▸</span>
          <span class="expert-badge">ЭКСПЕРТ</span>
          <span class="forecast-inline-icon">📈</span>
          <span class="forecast-inline-title expert-toggle-title">Учесть инфляцию следующего периода</span>
          <span class="forecast-inline-hint expert-toggle-hint">— объём не меняется, цены растут</span>
        </summary>
        <div class="forecast-inline-body expert-disclosure-body">
          <label class="apply-inflation-toggle">
            <input type="checkbox" bind:checked={applyInflation} />
            <span><strong>Применить медиаинфляцию на следующий период</strong></span>
          </label>
          <div class="forecast-table">
            <div class="forecast-head">
              <div class="fc-name">Канал</div>
              <div class="fc-infl">Инфляция %</div>
              <div class="fc-cpp">Новый CPP / эффект</div>
            </div>
            {#each channels as ch}
              {@const oldU = ucOldMap[ch] ?? 1.0}
              {@const infl = channelInflation[ch] ?? 0}
              {@const newU = oldU * (1 + infl / 100)}
              <div class="forecast-row">
                <div class="fc-name">{ch}</div>
                <div class="fc-infl">
                  <input type="number" class="fc-input" min={0} max={100} step={1} value={infl}
                    oninput={(/** @type {any} */ e) => channelInflation = { ...channelInflation, [ch]: Number(e.target.value) }} />
                  <span class="fc-pct">%</span>
                </div>
                <div class="fc-cpp">
                  {#if oldU > 1.0}
                    {fmtBudget(newU)} <span class="fc-cpp-old">(было {fmtBudget(oldU)})</span>
                  {:else if infl > 0}
                    <span class="fc-cpp-money" title="Канал в деньгах — инфляция прибавляет к самому бюджету">+{infl}% к бюджету</span>
                  {:else}—{/if}
                </div>
              </div>
            {/each}
          </div>
          <p class="forecast-inline-note">
            <span class="help-icon" title="Объём медиа (TRP/показы/клики) остаётся прежним — Hill saturation возвращает тот же эффект → KPI не меняется. Растёт лишь сумма в рублях из-за подорожания закупок.">?</span>
            Средняя инфляция: <b>+{avgInflation.toFixed(0)}%</b>. KPI не меняется при сохранении объёма; меняется только сумма бюджета на следующий период.
          </p>
        </div>
      </details>

      <!-- v1.0.16: save scenario доступно даже при «нулевом» what-if (slider=1.0)
           если applyInflation активирован — customer может сохранить current
           allocation + inflation как сценарий следующего периода без необходимости
           двигать бюджет. -->
      {#if whatIfResult || (applyInflation && channels.length > 0)}
        <div class="whatif-save-row">
          <button
            class="btn-save-scenario"
            onclick={() => saveWhatIfAsScenario(applyInflation ? ucNewMap : null)}
            disabled={!whatIfResult && !applyInflation}
          >
            💾 Сохранить как сценарий {#if applyInflation}(с инфляцией){/if}
          </button>
          {#if !whatIfResult && applyInflation}
            <span class="save-hint">Сохранится текущая аллокация с поправкой на медиаинфляцию следующего периода</span>
          {/if}
        </div>
      {/if}
    </section>
  {/if}

  <!-- v1.0.16: standalone Block D «Прогноз на будущий период» удалён —
       функциональность интегрирована в Block C What-if как опциональный
       inflation overlay над «Сохранить как сценарий». Customer выбирает учёт
       инфляции на уровне сценария. expectedLiftPct=0 при volume mode (Hill
       saturation на raw_spend = unchanged → KPI = unchanged). -->

  <!-- ════════════════ Сценарии (постоянно видимы, переедут в Phase 5) ════════════════ -->
  {#if channels.length > 0}
    <section class="block block-scenarios">
      <div class="block-header">
        <span class="block-letter">D</span>
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
          <ScenarioPlayground {channelBudgets} {channels} {optimalBudgets} />
        </div>
      {/if}
    </section>
  {/if}

  {#if showOnboarding}
    <PipelineOnboarding
      steps={TOURS.optimize}
      stepKey="optimize"
      onDone={() => { showOnboarding = false; }}
    />
  {/if}

</div>

<style>
  /* ─── Phase 2 — Planning Mode toggle ─── */
  .planning-mode-toggle {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 16px;
    border-radius: 12px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.92));
    border: 1px solid var(--border-subtle, rgba(0,0,0,0.08));
    margin-bottom: 12px;
  }
  .mode-pills {
    display: inline-flex;
    align-self: flex-start;
    gap: 4px;
    padding: 4px;
    background: rgba(0,0,0,0.04);
    border-radius: 10px;
  }
  .mode-pills button {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    padding: 6px 14px;
    border: none;
    background: transparent;
    border-radius: 8px;
    cursor: pointer;
    transition: background 160ms ease, color 160ms ease;
  }
  .mode-pills button.active {
    background: var(--bg-surface-focus, white);
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }
  .mode-pills .mode-label { font-weight: 600; font-size: 0.95rem; }
  .mode-pills .mode-desc { font-size: 0.75rem; opacity: 0.7; }
  .mode-hint { margin: 0; font-size: 0.85rem; opacity: 0.75; }

  .optimize-step {
    /* Скрол владеет .pipeline-main — здесь никаких overflow / height: 100%,
       иначе двойной скрол + фантомное пустое пространство (см. DecomposeStep). */
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 0;
    box-sizing: border-box;
  }

  .onboarding-hint {
    display: flex;
    justify-content: flex-end;
    margin-top: -6px;
    margin-bottom: -6px;
  }
  .btn-hint {
    padding: 4px 10px;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    color: var(--text-secondary, #94a3b8);
    font-size: 11px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .btn-hint:hover {
    color: var(--text-primary, #e2e8f0);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 50%, transparent);
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

  /* ── Block C/D: What-if + Forecast ──────────────────────── */
  .whatif-controls {
    display: grid;
    grid-template-columns: minmax(220px, 1.4fr) 2fr auto;
    gap: 14px;
    align-items: center;
    padding: 10px 12px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.5));
    border-radius: 10px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  @media (max-width: 800px) {
    .whatif-controls { grid-template-columns: 1fr; }
  }
  .whatif-label { font-size: 12px; color: var(--text-secondary); display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .whatif-label b { color: var(--text-primary); font-weight: 600; font-variant-numeric: tabular-nums; }
  .whatif-delta {
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 12px;
  }
  .whatif-delta.positive { background: color-mix(in srgb, var(--success) 14%, transparent); color: var(--success); }
  .whatif-delta.negative { background: color-mix(in srgb, var(--danger) 14%, transparent); color: var(--danger); }
  .whatif-slider {
    width: 100%;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: rgba(255,255,255,0.1);
    border-radius: 2px;
    outline: none;
    cursor: pointer;
  }
  .whatif-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--accent-primary);
    cursor: pointer;
  }
  .whatif-actions { display: flex; gap: 8px; }
  .btn-run {
    padding: 7px 14px;
    background: var(--accent-primary);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .btn-run:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-run:hover:not(:disabled) { background: var(--accent-hover); }

  /* O1.2 (Phase 0.1): dirty-state hint after settings change. Subtle amber
     indicator next to button — клиент видит что нужно перезапустить optimize. */
  .dirty-hint {
    font-size: 12px;
    color: var(--warning, #f59e0b);
    background: color-mix(in srgb, var(--warning, #f59e0b) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #f59e0b) 25%, transparent);
    padding: 4px 10px;
    border-radius: 6px;
    margin-left: 8px;
    white-space: nowrap;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .btn-reset-sm {
    padding: 7px 12px;
    background: transparent;
    color: var(--text-secondary);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
  }
  .btn-reset-sm:hover:not(:disabled) { border-color: rgba(255,255,255,0.25); color: var(--text-primary); }
  .btn-reset-sm:disabled { opacity: 0.5; cursor: not-allowed; }

  /* F.1 — per-group sliders (Trust 3 brand vs performance) */
  .group-sliders {
    margin-top: 10px;
    background: color-mix(in srgb, var(--bg-surface-quiet, #1a1d22) 60%, transparent);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 4px 12px;
  }
  .group-summary {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 4px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    user-select: none;
  }
  .group-summary:hover { color: var(--accent); }
  .group-icon { font-size: 14px; }
  .group-active-badge {
    color: var(--success, #10b981);
    font-size: 16px;
    margin-left: 4px;
  }
  .group-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    padding: 12px 4px 8px;
  }
  @media (max-width: 760px) {
    .group-grid { grid-template-columns: 1fr; }
  }
  .group-col {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .group-col-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    color: var(--text-secondary);
    margin-bottom: 2px;
  }
  .btn-clear {
    background: transparent;
    border: none;
    color: var(--text-secondary);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
    padding: 0 4px;
    margin-left: 4px;
  }
  .btn-clear:hover { color: var(--danger); }
  .btn-lock-group {
    margin-top: 4px;
    padding: 6px 10px;
    background: transparent;
    color: var(--text-secondary);
    border: 1px dashed var(--border-subtle);
    border-radius: 6px;
    font-size: 11px;
    cursor: pointer;
    align-self: flex-start;
  }
  .btn-lock-group:hover { border-style: solid; color: var(--text-primary); border-color: var(--accent); }
  .group-hint {
    margin: 4px 4px 8px;
    padding: 6px 10px;
    background: color-mix(in srgb, var(--bg-surface-quiet, #1a1d22) 50%, transparent);
    border-left: 2px solid var(--border-subtle);
    border-radius: 4px;
    font-size: 11px;
    color: var(--text-secondary);
    line-height: 1.5;
  }
  /* Кнопка сброса per-group в default state. Inline в summary, справа. */
  .btn-reset-group {
    margin-left: auto;
    padding: 4px 10px;
    background: transparent;
    color: var(--text-secondary, rgba(255, 255, 255, 0.65));
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.1));
    border-radius: 6px;
    font-size: 11px;
    cursor: pointer;
    white-space: nowrap;
  }
  .btn-reset-group:hover {
    color: var(--text-primary, rgba(255, 255, 255, 0.92));
    border-color: var(--accent-primary, #3b82f6);
  }
  /* Инструкции по сценариям использования per-group sliders. */
  .group-instructions {
    margin: 4px 4px 12px;
    padding: 12px 14px;
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 5%, transparent);
    border-left: 3px solid color-mix(in srgb, var(--accent-primary, #3b82f6) 50%, transparent);
    border-radius: 6px;
    font-size: 12px;
    line-height: 1.55;
  }
  .group-instr-title {
    font-weight: 600;
    color: var(--text-primary, rgba(255, 255, 255, 0.92));
    margin-bottom: 6px;
  }
  .group-instr-list {
    margin: 0 0 8px 0;
    padding-left: 20px;
    color: var(--text-secondary, rgba(255, 255, 255, 0.7));
  }
  .group-instr-list li {
    margin-bottom: 6px;
  }
  .group-instr-list li strong {
    color: var(--text-primary, rgba(255, 255, 255, 0.88));
  }
  .group-instr-list code {
    padding: 1px 5px;
    background: color-mix(in srgb, var(--text-primary, #fff) 8%, transparent);
    border-radius: 3px;
    font-size: 11px;
    font-family: var(--font-mono, monospace);
  }
  .group-instr-defaults {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid color-mix(in srgb, var(--text-primary, #fff) 8%, transparent);
    color: var(--text-secondary, rgba(255, 255, 255, 0.65));
    font-size: 11px;
  }
  /* AUDIT-5: inline validation warnings — surfaces constraint hierarchy violation
     до backend roundtrip. role="alert" для screen readers. */
  .group-warnings {
    margin: 8px 4px 4px;
    padding: 8px 10px;
    background: color-mix(in srgb, var(--warning, #f59e0b) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #f59e0b) 30%, transparent);
    border-radius: 4px;
    color: var(--warning, #f59e0b);
    font-size: 11px;
    line-height: 1.6;
  }
  .group-warn-line { margin: 0; }

  .inline-error {
    margin-top: 8px;
    padding: 8px 12px;
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
    border-radius: 6px;
    color: var(--danger);
    font-size: 12px;
  }
  .inline-success {
    margin-top: 8px;
    padding: 8px 12px;
    background: color-mix(in srgb, var(--success, #10b981) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #10b981) 28%, transparent);
    border-radius: 6px;
    color: var(--success, #10b981);
    font-size: 12px;
    font-weight: 500;
  }
  .forecast-avg {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-secondary);
  }
  .forecast-avg b { color: var(--text-primary); font-weight: 600; }

  .whatif-compare {
    margin-top: 10px;
    padding: 12px 14px;
    background: color-mix(in srgb, var(--accent-primary) 5%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 18%, transparent);
    border-radius: 10px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .compare-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .compare-cell { flex: 1; min-width: 180px; }
  .compare-cell.highlight {
    padding: 8px 12px;
    background: color-mix(in srgb, var(--accent-primary) 10%, transparent);
    border-radius: 8px;
  }
  .compare-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .compare-value { font-size: 18px; font-weight: 700; color: var(--text-primary); margin-top: 2px; font-variant-numeric: tabular-nums; }
  .compare-sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
  .compare-arrow { font-size: 20px; color: var(--text-muted); }
  .lift { font-weight: 600; margin-left: 4px; }
  .lift.positive { color: var(--success); }
  .lift.negative { color: var(--danger); }
  .whatif-insight { font-size: 12px; color: var(--text-secondary); line-height: 1.5; font-style: italic; }

  /* Forecast mode radios */
  .forecast-mode {
    display: flex;
    gap: 14px;
    padding: 10px 12px;
    flex-wrap: wrap;
  }
  .mode-radio {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-primary);
    cursor: pointer;
  }
  .mode-radio input { cursor: pointer; }
  .mode-hint { font-size: 11px; color: var(--text-muted); }

  .forecast-table {
    padding: 0 12px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .forecast-head, .forecast-row {
    display: grid;
    grid-template-columns: 2fr 1fr 2fr;
    gap: 12px;
    align-items: center;
    padding: 6px 8px;
    font-size: 12px;
  }
  .forecast-head {
    color: var(--text-muted);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--border-subtle);
  }
  .forecast-row {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.3));
    border-radius: 6px;
  }
  .fc-name { color: var(--text-primary); }
  .fc-infl { display: flex; align-items: center; gap: 4px; }
  .fc-input {
    width: 60px;
    padding: 4px 8px;
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    color: var(--text-primary);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
  .fc-input:focus { outline: none; border-color: var(--accent-primary); }
  .fc-pct { color: var(--text-muted); }
  .fc-cpp { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
  .fc-cpp-old { color: var(--text-muted); font-size: 10px; margin-left: 4px; }
  .fc-cpp-money { color: var(--text-secondary); font-size: 12px; font-style: italic; cursor: help; }

  .forecast-actions { display: flex; gap: 8px; padding: 10px 12px; }

  .btn-save-scenario {
    padding: 6px 14px;
    background: color-mix(in srgb, var(--success, #10b981) 14%, transparent);
    color: var(--success, #10b981);
    border: 1px solid color-mix(in srgb, var(--success, #10b981) 30%, transparent);
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }
  .btn-save-scenario:hover { background: color-mix(in srgb, var(--success, #10b981) 22%, transparent); }

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

  /* v1.0.16: Block D collapsible (Прогноз на будущий период) */
  .forecast-disclosure { padding: 0; overflow: hidden; }
  .forecast-disclosure[open] .forecast-arrow { transform: rotate(90deg); }
  .forecast-summary {
    list-style: none;
    cursor: pointer;
    user-select: none;
    transition: background 0.15s ease;
    padding: 16px 18px;
  }
  .forecast-summary::-webkit-details-marker { display: none; }
  .forecast-summary:hover { background: color-mix(in srgb, var(--accent-primary, #3b82f6) 4%, transparent); }
  .forecast-arrow {
    font-size: 12px;
    color: var(--text-muted, #94a3b8);
    transition: transform 0.2s ease;
    flex-shrink: 0;
    margin-right: 6px;
  }
  .forecast-expert-badge {
    margin-left: auto;
    padding: 2px 8px;
    background: color-mix(in srgb, var(--danger) 18%, transparent);
    color: var(--danger);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.08em;
    border-radius: 4px;
  }
  .forecast-disclosure > .forecast-mode,
  .forecast-disclosure > .forecast-table,
  .forecast-disclosure > .forecast-actions,
  .forecast-disclosure > .whatif-compare,
  .forecast-disclosure > .inline-error,
  .forecast-disclosure > .inline-success { padding: 0 18px; }
  .forecast-disclosure > .forecast-actions { padding-bottom: 18px; }

  /* v1.0.16: collapsible expert disclosure — visible to all, default closed */
  .expert-disclosure {
    margin-top: 4px;
    border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
    border-radius: 10px;
    background: color-mix(in srgb, var(--danger) 4%, transparent);
    overflow: hidden;
  }
  .expert-disclosure[open] .expert-arrow { transform: rotate(90deg); }
  .expert-toggle {
    list-style: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    user-select: none;
    transition: background 0.15s ease;
  }
  .expert-toggle::-webkit-details-marker { display: none; }
  .expert-toggle:hover { background: color-mix(in srgb, var(--danger) 8%, transparent); }
  .expert-arrow {
    font-size: 12px;
    color: var(--text-muted, #94a3b8);
    transition: transform 0.2s ease;
    flex-shrink: 0;
  }
  .expert-toggle-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }
  .expert-toggle-hint {
    font-size: 12px;
    color: var(--text-muted, #94a3b8);
    flex: 1;
  }
  .expert-toggle-count {
    padding: 2px 8px;
    background: color-mix(in srgb, #f97316 18%, transparent);
    border: 1px solid color-mix(in srgb, #f97316 36%, transparent);
    border-radius: 12px;
    color: #fed7aa;
    font-size: 11px;
    font-weight: 600;
    flex-shrink: 0;
  }
  .expert-disclosure-body {
    padding: 0 16px 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    border-top: 1px solid color-mix(in srgb, var(--danger) 15%, transparent);
    padding-top: 14px;
  }

  /* v1.0.16: apply-inflation toggle — выделено отступом сверху чтобы не сливаться
     с заголовком disclosure (было слишком близко к summary line). */
  .apply-inflation-toggle {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 8px;
    padding: 10px 12px;
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 22%, transparent);
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px;
    color: var(--text-primary, #e2e8f0);
  }
  .apply-inflation-toggle input[type="checkbox"] {
    width: 16px; height: 16px;
    accent-color: var(--danger);
    cursor: pointer;
  }
  .apply-inflation-toggle:hover {
    background: color-mix(in srgb, var(--danger) 12%, transparent);
  }
  .apply-inflation-toggle strong { font-weight: 600; }

  /* ── Экспертная панель per-channel ограничений (legacy class, сохранён) ──── */
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

  /* L7: edge-case banners — mutually exclusive с insight banner */
  .edge-banner {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px 16px;
    border-radius: 10px;
    margin-bottom: 10px;
  }
  .edge-banner .banner-icon { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
  .edge-banner .banner-text { flex: 1; font-size: 13px; line-height: 1.55; margin: 0; }
  .edge-banner .banner-text strong { font-weight: 600; }
  .banner-error {
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 28%, transparent);
    color: #fecaca;
  }
  .banner-warn {
    background: color-mix(in srgb, #f59e0b 10%, transparent);
    border: 1px solid color-mix(in srgb, #f59e0b 28%, transparent);
    color: #fde68a;
  }
  .banner-info {
    background: color-mix(in srgb, #3b82f6 8%, transparent);
    border: 1px solid color-mix(in srgb, #3b82f6 22%, transparent);
    color: #bfdbfe;
  }

  /* L8: per-channel override warning — gentler tone (informational, not error) */
  .override-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    margin-top: 10px;
    border-radius: 10px;
    background: color-mix(in srgb, #f97316 8%, transparent);
    border: 1px solid color-mix(in srgb, #f97316 24%, transparent);
    color: #fed7aa;
    font-size: 13px;
  }
  .override-banner .banner-icon { font-size: 16px; flex-shrink: 0; }
  .override-banner .banner-text { flex: 1; line-height: 1.4; margin: 0; }
  .override-banner .banner-text strong { font-weight: 700; color: #fff; }
  .btn-override-reset {
    flex-shrink: 0;
    padding: 6px 12px;
    background: color-mix(in srgb, #f97316 18%, transparent);
    border: 1px solid color-mix(in srgb, #f97316 36%, transparent);
    border-radius: 6px;
    color: #fed7aa;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .btn-override-reset:hover {
    background: color-mix(in srgb, #f97316 30%, transparent);
    color: #fff;
  }
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

  /* Phase 1 (2026-05-02): planning horizon disclosure baner для пленнеров.
     Объясняет что optimizer выдаёт цифры для training period, не forecast.
     Будет упрощён в Phase 2 когда forecast_horizon parameter реализован. */
  .planning-warn {
    display: flex;
    gap: 12px;
    margin-bottom: 14px;
    padding: 12px 16px;
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 7%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
    border-left: 3px solid var(--accent-primary, #3b82f6);
    border-radius: 8px;
    font-size: 12.5px;
    line-height: 1.55;
  }
  .planning-warn-icon {
    font-size: 18px;
    flex-shrink: 0;
    margin-top: 1px;
  }
  .planning-warn-body { flex: 1; }
  .planning-warn-title {
    font-weight: 600;
    color: var(--text-primary, rgba(255, 255, 255, 0.92));
    margin-bottom: 4px;
  }
  .planning-warn-text {
    color: var(--text-secondary, rgba(255, 255, 255, 0.7));
    margin-bottom: 6px;
  }
  .planning-warn-list {
    margin: 0 0 8px 0;
    padding-left: 20px;
    color: var(--text-secondary, rgba(255, 255, 255, 0.7));
  }
  .planning-warn-list li { margin-bottom: 4px; }
  .planning-warn-list strong { color: var(--text-primary, rgba(255, 255, 255, 0.88)); }
  .planning-warn-roadmap {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid color-mix(in srgb, var(--text-primary, #fff) 8%, transparent);
    color: var(--text-secondary, rgba(255, 255, 255, 0.55));
    font-size: 11px;
    font-style: italic;
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
