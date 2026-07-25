<script>
  /**
   * PlanningStep — шаг 5 пайплайна (индекс 5): Планирование / прогноз на будущий период.
   *
   * Фаза 4 реализации. Строится из готовых компонентов:
   *   - BacktestCard  — карточка доверия модели (E1-витрина)
   *   - BudgetOptimizer — слайдеры бюджетов для создания вариантов
   *   - ContinuationChart — веер история + прогноз с ДИ
   *   - MultiScenarioPage — сравнение сохранённых вариантов
   *   - PromisesCard — фиксация прогноза
   *
   * EXPAND-CONTRACT: PlanningStep независим от OptimizeStep; дублирование
   * некоторых компонентов временно — будет сведено при следующей фазе.
   *
   * TODO (backend): econ_confirm_media_plan — команда Rust для подтверждения
   *   медиаплана на диске (пока состояние хранится только во фронтенде).
   * TODO (backend): econ_download_media_plan_template — скачать шаблон Excel.
   */

  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import {
    activeProjectId,
    mediaPlanDetected,
    planningManifest,
    optimizeData,
    modelData,
    decomposeData,
    kpiType,
    kpiKind,
    valuePerCountUnit,
    forecastConfig,
    promisesVersion,
    completeStep,
    pipelineCurrentStep,
  } from '$lib/project-state.js';

  /** @type {Record<string, string>} */
  const KPI_LABELS = {
    sales:         'Выручка (₽)',
    revenue:       'Доход (₽)',
    profit:        'Прибыль (₽)',
    sales_packs:   'Продажи в штуках',
    leads:         'Лиды',
    registrations: 'Регистрации',
    loyalty_cards: 'Выданные карты',
    subscriptions: 'Подписки',
    app_installs:  'Установки',
    count_custom:  'Свой KPI',
  };

  import BudgetOptimizer from './BudgetOptimizer.svelte';
  import ContinuationChart from './ContinuationChart.svelte';
  import MultiScenarioPage from './MultiScenarioPage.svelte';
  import PromisesCard from './PromisesCard.svelte';
  import BacktestCard from './BacktestCard.svelte';
  import { Info, AlertTriangle, ChevronDown } from 'lucide-svelte';

  // ── Helpers ───────────────────────────────────────────────────────────────

  /** Получить projectDir (string) или null */
  async function getProjectDir() {
    const pid = get(activeProjectId);
    if (!pid) return null;
    try {
      return /** @type {string} */ (await invoke('project_get_dir', { projectId: pid }));
    } catch { return null; }
  }

  // ── Данные из сторов ───────────────────────────────────────────────────────

  /** Каналы из optimizeData (источник сида для вариантов) */
  const optChannels = $derived($optimizeData?.channels ?? []);

  /** unit_costs_snapshot из modelData (A12: физические каналы) */
  const ucTrain = $derived.by(() => {
    const diag = $modelData?.diagnostics;
    if (!diag?.unit_costs_applied_at_training) return null;
    return diag.unit_costs_snapshot ?? null;
  });

  /** scaledParams для BudgetOptimizer */
  const scaledParams = $derived($modelData?.diagnostics?.scaled_params ?? null);

  /** decays для BudgetOptimizer */
  const decays = $derived($modelData?.diagnostics?.decays ?? null);

  /** Исторические данные (для ContinuationChart).
   * Фикс аудита 2026-07-11: раньше читались `dData.dates`/`dData.kpi_actuals` —
   * таких полей в decompose НЕТ (структура: `decomposition_series.{dates,series}` +
   * `time_series.dates`), поэтому historicalSeries ВСЕГДА был null и график
   * история→прогноз не рисовался никогда. Историческая линия KPI = сумма вкладов
   * декомпозиции по периоду (data уже signed; `side` — только метка цвета) =
   * модельная реконструкция факта, когерентная с прогнозом (тоже из модели). */
  const historicalSeries = $derived.by(() => {
    const dData = $decomposeData;
    const ds = dData?.decomposition_series;
    const dates = /** @type {string[]} */ (ds?.dates ?? dData?.time_series?.dates);
    if (!dates?.length || !Array.isArray(ds?.series) || !ds.series.length) return null;
    const n = dates.length;
    const actuals = new Array(n).fill(0);
    for (const s of ds.series) {
      const arr = s?.data ?? [];
      for (let i = 0; i < n; i++) actuals[i] += Number(arr[i]) || 0;
    }
    return { dates, actuals };
  });

  /** Метка KPI из типа */
  const kpiLabelText = $derived(KPI_LABELS[$kpiType] ?? $kpiType ?? 'KPI');

  // ── Медиаплан ──────────────────────────────────────────────────────────────

  const mpData = $derived($mediaPlanDetected);

  /** N будущих периодов из медиаплана или forecastConfig */
  const nFuturePeriods = $derived(
    mpData?.n_future_periods ?? $forecastConfig?.periods ?? null
  );

  /** Метки периодов из медиаплана */
  const periodLabels = $derived(mpData?.period_labels ?? []);

  /** future_dates из медиаплана */
  const futureDates = $derived(mpData?.future_dates ?? []);

  // ── Варианты ───────────────────────────────────────────────────────────────

  /**
   * @typedef {{
   *   id: string,
   *   name: string,
   *   budget: number,
   *   predictedKpi: number,
   *   ciLow?: number,
   *   ciHigh?: number,
   *   perChannelAllocation?: Record<string, number>,
   *   dates?: string[],
   *   predictions?: number[],
   *   ciLowSeries?: number[],
   *   ciHighSeries?: number[],
   *   mediaPlan: Record<string, number[]>,
   *   disclaimers?: string[],
   * }} PlanVariant
   */

  /** @type {PlanVariant[]} */
  let variants = $state([]);

  /** Редактирование нового варианта активно */
  let editingVariant = $state(false);

  /** Текущие бюджеты слайдеров (по каналам, ₽) */
  let channelBudgets = $state(/** @type {Record<string, number>} */ ({}));

  /** Имя создаваемого варианта */
  let variantDraftName = $state('');

  /** Счётчик вариантов */
  let variantCounter = $state(1);

  /** Сохранение варианта — в процессе */
  let savingVariant = $state(false);
  /** @type {string | null} */
  let saveError = $state(null);

  // ── P-1: прогноз базового плана (авто при подтверждённом медиаплане) ────────

  /** Имя сценария базового плана (совпадает с results/scenarios/<name>.json). */
  const BASELINE_NAME = 'Базовый план';

  /**
   * @typedef {{
   *   predictions: number[], ciLow: number[], ciHigh: number[],
   *   totalKpi: number, totalSpend: number | null,
   *   ciLowTotal: number | null, ciHighTotal: number | null,
   *   dates: string[], disclaimers: string[]
   * }} BaselineForecast
   */
  /** @type {BaselineForecast | null} */
  let baselineForecast = $state(null);
  let baselineComputing = $state(false);
  /** @type {string | null} */
  let baselineError = $state(null);
  /** once-guard: source_hash файла, для которого прогноз уже построен/попытан. */
  let baselineComputedHash = $state(/** @type {string | null} */ (null));

  // ── Фиксация прогноза ─────────────────────────────────────────────────────

  let promiseSaving = $state(false);
  /** @type {string | null} */
  let promiseError = $state(null);
  /** @type {string | null} */
  let promiseSuccess = $state(null);

  // ── Disclaimers ───────────────────────────────────────────────────────────

  let disclaimersOpen = $state(false);

  /** Список disclaimers из последнего сохранённого варианта или дефолт */
  const activeDisclaimers = $derived.by(() => {
    const last = variants[variants.length - 1];
    if (last?.disclaimers?.length) return last.disclaimers;
    return ['прогноз составлен при неизменных прочих условиях: цена, дистрибуция и активность конкурентов приняты на историческом среднем'];
  });

  // ── Инициализация слайдеров из optimizeData ───────────────────────────────

  $effect(() => {
    const chs = optChannels;
    if (!chs.length) return;
    // Аудит 2026-07-10 (High): сеять только ПУСТОЙ ввод — любой ретриггер
    // $optimizeData (restore/reconcile/фоновое обновление) молча стирал бы
    // правки бюджетов пользователя в слайдерах.
    if (Object.keys(channelBudgets).length) return;
    /** @type {Record<string, number>} */
    const seed = {};
    for (const c of chs) {
      seed[c.name] = Number(c.optimal_spend_money ?? c.current_spend_money ?? 0);
    }
    channelBudgets = seed;
    if (!variantDraftName) variantDraftName = `Вариант ${variantCounter}`;
  });

  // ── Сохранение варианта ───────────────────────────────────────────────────

  async function saveVariant() {
    if (!nFuturePeriods) {
      saveError = 'Нет горизонта прогноза — загрузите файл с будущими строками или настройте горизонт.';
      return;
    }
    savingVariant = true;
    saveError = null;
    try {
      const projectDir = await getProjectDir();
      if (!projectDir) { saveError = 'Проект не выбран.'; return; }

      /** @type {Record<string, number[]>} */
      const mediaPlan = {};
      for (const [ch, budget] of Object.entries(channelBudgets)) {
        const perPeriod = Number(budget) / Math.max(1, nFuturePeriods);
        mediaPlan[ch] = Array.from({ length: nFuturePeriods }, () => perPeriod);
      }

      // A12: unit_costs_snapshot передаём в backend для физических каналов
      const _kuc = get(valuePerCountUnit);
      const kpiUnitCostP = get(kpiKind) === 'count' && typeof _kuc === 'number' && _kuc > 0 ? _kuc : null;

      // B-1/A-3 (аудит 2026-07-11): имя варианта = имя файла scenarios/<name>.json
      // И ключ манифеста planning.json. Чистим недопустимые для файла символы
      // (иначе запись падает или манифест рассинхронится с читателем → раздел
      // прогноза «не найден»); не даём занять имя базового плана и создать дубль.
      const rawName = variantDraftName || `Вариант ${variantCounter}`;
      const scenarioName = rawName.replace(/[/\\:*?"<>|]/g, '-').replace(/\s+/g, ' ').trim().slice(0, 120);
      if (!scenarioName || scenarioName === BASELINE_NAME) {
        saveError = `Название пустое или занято базовым планом — выберите другое (не «${BASELINE_NAME}»).`;
        return;
      }
      if (variants.some((v) => v.name === scenarioName)) {
        saveError = `Вариант «${scenarioName}» уже существует — выберите другое название.`;
        return;
      }

      const sc = /** @type {any} */ (await invoke('econ_scenario', {
        projectDir,
        scenarioName,
        mediaPlan,
        forecastPeriods: nFuturePeriods,
        forecastPeriodLabel: periodLabels[0] ?? null,
        kpiUnitCost: kpiUnitCostP,
        ...(futureDates.length ? { futureDates } : {}),
        carryIn: true,
      }));

      if (sc?.status !== 'ok') {
        saveError = sc?.message || 'Не удалось рассчитать вариант.';
        return;
      }

      const totals = sc.totals ?? {};
      const totalBudget = Object.values(channelBudgets).reduce((a, b) => a + b, 0);

      /** @type {PlanVariant} */
      const newVariant = {
        id: `plan-${Date.now()}`,
        name: scenarioName,
        budget: totalBudget,
        predictedKpi: Number(totals.predicted_kpi ?? 0),
        ciLow: totals.predicted_kpi_ci_low ?? undefined,
        ciHigh: totals.predicted_kpi_ci_high ?? undefined,
        perChannelAllocation: Object.fromEntries(
          Object.entries(channelBudgets).map(([k, v]) => [k, v])
        ),
        dates: sc.future_dates ?? futureDates,
        predictions: sc.predictions ?? [],
        ciLowSeries: sc.predictions_ci_low ?? [],
        ciHighSeries: sc.predictions_ci_high ?? [],
        mediaPlan,
        disclaimers: sc.disclaimers ?? [],
      };

      variants = [...variants, newVariant];
      variantCounter += 1;
      variantDraftName = `Вариант ${variantCounter}`;
      editingVariant = false;
    } catch (/** @type {any} */ e) {
      saveError = String(e?.message || e);
    } finally {
      savingVariant = false;
    }
    // Обновляем манифест: baseline + все варианты, accepted — последний созданный.
    if (!saveError) {
      const lastName = variants.length ? variants[variants.length - 1].name : BASELINE_NAME;
      await saveManifest(lastName);
    }
  }

  /**
   * Записать results/planning.json: baseline + пользовательские варианты.
   * Без манифеста раздел прогноза в PPTX/HTML/XLSX «не найден».
   * @param {string} acceptedName
   */
  async function saveManifest(acceptedName) {
    const projectDir = await getProjectDir();
    if (!projectDir) return;
    const ids = [
      ...(baselineForecast ? [BASELINE_NAME] : []),
      ...variants.map((v) => v.name),
    ];
    if (!ids.length) return;
    try {
      await invoke('econ_save_planning', {
        projectDir,
        variantIds: ids,
        acceptedVariant: acceptedName,
        disclaimers: baselineForecast?.disclaimers ?? [],
      });
    } catch (/** @type {any} */ e) {
      console.error('[PlanningStep] econ_save_planning не записался:', e);
    }
  }

  /**
   * P-1: прогноз базового плана — прогоняем медиаплан из файла через модель
   * СРАЗУ при входе (carry_in=true). Пишет scenarios/<baseline>.json + манифест,
   * чтобы график и раздел отчёта жили без ручного создания варианта.
   */
  async function computeBaseline() {
    const mp = get(mediaPlanDetected);
    const nFut = mp?.n_future_periods ?? get(forecastConfig)?.periods ?? null;
    if (!mp?.channels || !nFut) return;
    // Помечаем попытку СРАЗУ (idempotent guard) — иначе $effect зациклит при ошибке.
    baselineComputedHash = mp.source_hash ?? 'nohash';
    baselineComputing = true;
    baselineError = null;
    try {
      const projectDir = await getProjectDir();
      if (!projectDir) { baselineError = 'Проект не выбран.'; return; }

      const _kuc = get(valuePerCountUnit);
      const kpiUnitCostP = get(kpiKind) === 'count' && typeof _kuc === 'number' && _kuc > 0 ? _kuc : null;
      const fd = /** @type {string[]} */ (mp.future_dates ?? []);

      const sc = /** @type {any} */ (await invoke('econ_scenario', {
        projectDir,
        scenarioName: BASELINE_NAME,
        mediaPlan: mp.channels,
        forecastPeriods: nFut,
        forecastPeriodLabel: mp.period_labels?.[0] ?? null,
        kpiUnitCost: kpiUnitCostP,
        ...(fd.length ? { futureDates: fd } : {}),
        carryIn: true,
      }));

      if (sc?.status !== 'ok') {
        baselineError = sc?.message || 'Не удалось построить прогноз базового плана.';
        return;
      }

      const totals = sc.totals ?? {};
      // A-2 (аудит 2026-07-11): «Бюджет плана, ₽» — только когда backend перевёл
      // ВСЕ каналы в деньги (total_spend_money != null). Для физметрик (TRP/показы
      // без CPP) сумма сырых каналов НЕ рубли — не показываем валюту (INV-50).
      const spendMoney = totals.total_spend_money != null ? Number(totals.total_spend_money) : null;
      baselineForecast = {
        predictions: sc.predictions ?? [],
        ciLow: sc.predictions_ci_low ?? [],
        ciHigh: sc.predictions_ci_high ?? [],
        totalKpi: Number(totals.predicted_kpi ?? 0),
        totalSpend: spendMoney,
        ciLowTotal: totals.predicted_kpi_ci_low ?? null,
        ciHighTotal: totals.predicted_kpi_ci_high ?? null,
        dates: sc.future_dates ?? fd,
        disclaimers: sc.disclaimers ?? [],
      };

      // Автозапись манифеста — раздел прогноза в отчёте оживает без ручного варианта.
      await saveManifest(BASELINE_NAME);
    } catch (/** @type {any} */ e) {
      baselineError = String(e?.message || e);
    } finally {
      baselineComputing = false;
    }
  }

  /** Повторить прогноз базового плана после ошибки. */
  function retryBaseline() {
    baselineComputedHash = null;
    baselineError = null;
    computeBaseline();
  }

  // P-1: авто-запуск прогноза базового плана при подтверждённом медиаплане.
  // once-guard по source_hash — пересчёт только при смене файла, не при каждом
  // ретриггере стора. При ошибке hash уже помечен → цикла нет (retry вручную).
  $effect(() => {
    const mp = $mediaPlanDetected;
    if (!mp?.confirmed || !mp.channels) return;
    // A-4 (аудит 2026-07-11): PlanningStep смонтирован всегда (visibility-навигация,
    // +page.svelte:81), а mediaPlanDetected.confirmed ставится на Валидации ДО
    // обучения модели. Без гейта готовности модели $effect звал бы econ_scenario
    // без pickle → ошибка на нормальном пути. Ждём обученную модель.
    if (!$modelData?.diagnostics) return;
    const hash = mp.source_hash ?? 'nohash';
    if (baselineComputedHash === hash || baselineComputing) return;
    computeBaseline();
  });

  // ── Удаление варианта ─────────────────────────────────────────────────────

  /** @param {{ id: string }} scenario */
  function deleteVariant(scenario) {
    variants = variants.filter((v) => v.id !== scenario.id);
  }

  // ── Фиксация прогноза ─────────────────────────────────────────────────────

  async function fixForecastPromise() {
    if (!nFuturePeriods) {
      promiseError = 'Нет горизонта прогноза для фиксации.';
      return;
    }
    const src = variants.length ? variants[variants.length - 1] : null;
    if (!src) {
      promiseError = 'Сначала создайте хотя бы один вариант.';
      return;
    }
    promiseSaving = true;
    promiseError = null;
    promiseSuccess = null;
    try {
      const projectDir = await getProjectDir();
      if (!projectDir) { promiseError = 'Проект не выбран.'; return; }

      const totalMoney = Object.values(src.perChannelAllocation ?? {}).reduce((a, b) => a + b, 0);

      const created = /** @type {any} */ (await invoke('econ_promise_create', {
        projectDir,
        actionText: (
          `Медиаплан ${Math.round(totalMoney).toLocaleString('ru-RU')} ₽ — ` +
          `${src.name} (${nFuturePeriods} пер.)`
        ),
        expectedKpiTotal: src.predictedKpi,
        ciLow: src.ciLow ?? null,
        ciHigh: src.ciHigh ?? null,
        horizonPeriods: nFuturePeriods,
        channelChanges: null,
        extrapolationFlag: false,
        source: 'planning_step',
      }));

      if (created?.status === 'ok') {
        promiseSuccess = '✓ Прогноз зафиксирован — сверится с фактом при обновлении данных';
        promisesVersion.update((n) => n + 1);
        setTimeout(() => { promiseSuccess = null; }, 4000);
      } else {
        promiseError = created?.message || 'Не удалось зафиксировать прогноз.';
      }
    } catch (/** @type {any} */ e) {
      promiseError = String(e?.message || e);
    } finally {
      promiseSaving = false;
    }
  }

  // ── Скачать шаблон медиаплана ─────────────────────────────────────────────

  /** @type {string | null} */
  let templateError = $state(null);
  /** @type {boolean} */
  let templateLoading = $state(false);

  async function downloadTemplate() {
    const projectDir = await getProjectDir();
    if (!projectDir) {
      templateError = 'Не удалось определить папку проекта.';
      return;
    }
    templateLoading = true;
    templateError = null;
    try {
      const res = /** @type {{ status: string, path?: string, message?: string }} */ (
        await invoke('econ_download_media_plan_template', {
          projectDir,
          nFuturePeriods: nFuturePeriods ?? 12,
        })
      );
      if (res.status === 'ok' && res.path) {
        // Показываем файл в проводнике (reveal_path — Windows explorer /select,<path>)
        try { await invoke('reveal_path', { path: res.path }); } catch { /* no-op */ }
      } else {
        templateError = res.message || 'Не удалось создать шаблон.';
      }
    } catch (/** @type {any} */ e) {
      templateError = String(e?.message || e);
    } finally {
      templateLoading = false;
    }
  }

  // ── Вердикт: эвристика перекрытия ДИ ─────────────────────────────────────

  /**
   * Простая эвристика: считаем варианты «неразличимыми», если ДИ хотя бы
   * половины пар перекрываются (ciLow_a < ciHigh_b && ciLow_b < ciHigh_a).
   * Не используем сложную статистику — только сравниваем интервалы.
   * @param {PlanVariant[]} vs
   * @returns {{ best: PlanVariant | null, ambiguous: boolean }}
   */
  function computeVerdict(vs) {
    if (!vs.length) return { best: null, ambiguous: false };
    const sorted = [...vs].sort((a, b) => b.predictedKpi - a.predictedKpi);
    const best = sorted[0];
    if (vs.length < 2) return { best, ambiguous: false };

    let overlapCount = 0;
    let pairCount = 0;
    for (let i = 0; i < sorted.length - 1; i++) {
      for (let j = i + 1; j < sorted.length; j++) {
        const a = sorted[i];
        const b = sorted[j];
        if (
          a.ciLow != null && a.ciHigh != null &&
          b.ciLow != null && b.ciHigh != null
        ) {
          pairCount++;
          if (a.ciLow < b.ciHigh && b.ciLow < a.ciHigh) overlapCount++;
        }
      }
    }
    const ambiguous = pairCount > 0 && overlapCount / pairCount >= 0.5;
    return { best, ambiguous };
  }

  const verdict = $derived(computeVerdict(variants));

  // ── Завершение шага ───────────────────────────────────────────────────────

  async function goToReport() {
    // Финальный манифест: accepted — лучший вариант (или базовый план, если
    // вариантов не создавали). Гарантирует, что раздел прогноза в отчёте — живой.
    await saveManifest(verdict.best?.name ?? BASELINE_NAME);
    planningManifest.set({
      variants: variants.map((v) => ({
        id: v.id,
        name: v.name,
        budget: v.budget,
        predictedKpi: v.predictedKpi,
        ciLow: v.ciLow,
        ciHigh: v.ciHigh,
      })),
      bestVariantId: verdict.best?.id ?? null,
      ambiguous: verdict.ambiguous,
      nFuturePeriods,
    });
    completeStep(5);
    pipelineCurrentStep.set(6);
  }
</script>

<div class="planning-step">

  <!-- Дизайн-консистентность (Антон 2026-07-17): внутренней шапки-дубля нет
       ни у одного соседнего шага — заголовок даёт степпер, вводный смысл
       «оптимизация = прошлое, планирование = будущее» живёт в справке шага
       (contextual-help). -->

  <!-- ── U1: плашка доверия (BacktestCard) ─────────────────────────────── -->
  <section class="trust-section">
    <BacktestCard />
  </section>

  <!-- ── Базовый медиаплан из файла ──────────────────────────────────────── -->
  {#if mpData}
    <section class="mediaplan-section">
      <h3 class="section-title">Базовый план из файла</h3>
      <p class="section-note">
        Обнаружено {mpData.n_future_periods} {mpData.granularity === 'week' ? 'недель' : 'периодов'}
        {#if mpData.period_labels?.length}
          ({mpData.period_labels[0]} – {mpData.period_labels[mpData.period_labels.length - 1]})
        {/if}
      </p>
      {#if mpData.warnings?.length}
        <div class="mp-warnings">
          {#each mpData.warnings as w (w)}
            <div class="mp-warning"><AlertTriangle size={14} /> {w}</div>
          {/each}
        </div>
      {/if}
      <div class="mp-table-wrap">
        <table class="mp-table">
          <thead>
            <tr>
              <th>Канал</th>
              {#each periodLabels as lbl (lbl)}
                <th>{lbl}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each Object.entries(mpData.channels) as [ch, vals] (ch)}
              <tr>
                <td class="ch-name">{ch}</td>
                {#each /** @type {number[]} */ (vals) as v, i (i)}
                  <td class="val">{v.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}</td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {:else}
    <!-- U6: пустое состояние без медиаплана -->
    <section class="empty-plan-section">
      <div class="empty-plan-card">
        <Info size={20} />
        <p class="empty-text">
          В файле не обнаружен медиаплан на будущее.
          Создайте вариант от оптимального распределения или загрузите шаблон.
        </p>
        <!-- U5: скачать шаблон медиаплана -->
        <button type="button" class="btn-template" onclick={downloadTemplate}
          disabled={templateLoading}>
          {templateLoading ? 'Создаём шаблон...' : 'Скачать шаблон медиаплана'}
        </button>
        {#if templateError}
          <p class="template-error" role="alert">{templateError}</p>
        {/if}
      </div>
    </section>
  {/if}

  <!-- ── P-1: прогноз базового плана (авто при подтверждённом медиаплане) ─── -->
  {#if mpData?.confirmed}
    <section class="baseline-section">
      <div class="baseline-header">
        <h3 class="section-title">Прогноз базового плана</h3>
        <p class="section-note">
          Что произойдёт при вашем медиаплане из файла – прогноз через обученную модель.
          Варианты ниже – это «что если» изменить план.
        </p>
      </div>

      {#if baselineComputing}
        <div class="baseline-loading" aria-live="polite">
          <span class="spinner" aria-hidden="true"></span>
          Строим прогноз базового плана…
        </div>
      {:else if baselineError}
        <div class="baseline-error" role="alert">
          <AlertTriangle size={16} />
          <span>{baselineError}</span>
          <button type="button" class="btn-retry" onclick={retryBaseline}>Повторить</button>
        </div>
      {:else if baselineForecast}
        <div class="baseline-summary-card">
          <div class="bsc-metric">
            <span class="bsc-label">{kpiLabelText} за {nFuturePeriods} пер.</span>
            <span class="bsc-value">
              {baselineForecast.totalKpi.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}
            </span>
            {#if baselineForecast.ciLowTotal != null && baselineForecast.ciHighTotal != null}
              <span class="bsc-ci">
                интервал [{baselineForecast.ciLowTotal.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} –
                {baselineForecast.ciHighTotal.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}]
              </span>
            {/if}
          </div>
          {#if baselineForecast.totalSpend != null}
            <div class="bsc-metric">
              <span class="bsc-label">Бюджет плана</span>
              <span class="bsc-value">
                {baselineForecast.totalSpend.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽
              </span>
            </div>
          {/if}
        </div>

        {#if historicalSeries}
          <div class="chart-wrap">
            <ContinuationChart
              historical={historicalSeries}
              modelFit={null}
              scenarios={[
                {
                  name: BASELINE_NAME,
                  dates: baselineForecast.dates,
                  predictions: baselineForecast.predictions,
                  ciLow: baselineForecast.ciLow,
                  ciHigh: baselineForecast.ciHigh,
                },
                ...variants.map((v) => ({
                  name: v.name,
                  dates: v.dates ?? [],
                  predictions: v.predictions ?? [],
                  ciLow: v.ciLowSeries,
                  ciHigh: v.ciHighSeries,
                })),
              ]}
              cutoffIndex={historicalSeries.dates.length - 1}
              kpiLabel={kpiLabelText}
              maxScenarios={6}
            />
          </div>
        {/if}
      {/if}
    </section>
  {/if}

  <!-- ── Варианты медиаплана ─────────────────────────────────────────────── -->
  <section class="variants-section">
    <div class="variants-header">
      <h3 class="section-title">Варианты медиаплана</h3>
      {#if !editingVariant}
        <button type="button" class="btn-create-variant"
          onclick={() => { editingVariant = true; }}>
          + Создать вариант
        </button>
      {/if}
    </div>

    {#if editingVariant}
      <div class="variant-editor">
        <div class="variant-name-row">
          <label class="variant-name-label" for="variant-name">Название</label>
          <input
            id="variant-name"
            class="variant-name-input"
            type="text"
            bind:value={variantDraftName}
            placeholder="Вариант 1"
          />
        </div>

        {#if optChannels.length > 0}
          <div class="optimizer-wrap">
            <BudgetOptimizer
              channels={optChannels}
              scaledParams={scaledParams}
              channelBudgets={channelBudgets}
              initialSpend={optChannels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + Number(c.current_spend_money ?? 0), 0)}
              currentKPI={$optimizeData?.current_kpi ?? 0}
              locked={savingVariant}
              unitCosts={ucTrain ?? undefined}
              unitCostsAtTraining={ucTrain ?? undefined}
              nPeriods={nFuturePeriods ?? 1}
              decays={decays ?? undefined}
              onBudgetChange={(ch, val) => { channelBudgets = { ...channelBudgets, [ch]: val }; }}
              onOptimize={() => {}}
              onReset={() => {}}
            />
          </div>
        {:else}
          <p class="no-channels-note">
            Нет данных каналов. Сначала завершите шаг «Оптимизация».
          </p>
        {/if}

        {#if saveError}
          <div class="save-error" role="alert">{saveError}</div>
        {/if}

        <div class="variant-actions">
          <button type="button" class="btn-cancel"
            onclick={() => { editingVariant = false; saveError = null; }}>
            Отмена
          </button>
          <button type="button" class="btn-save-variant"
            onclick={saveVariant}
            disabled={savingVariant || !nFuturePeriods}>
            {savingVariant ? 'Рассчитываем...' : `Сохранить как «${variantDraftName}»`}
          </button>
        </div>
      </div>
    {/if}

    {#if variants.length > 0}
      <div class="variant-list">
        {#each variants as v (v.id)}
          <div class="variant-chip">
            <span class="variant-chip-name">{v.name}</span>
            <span class="variant-chip-kpi">
              {kpiLabelText}: {v.predictedKpi.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}
              {#if v.ciLow != null && v.ciHigh != null}
                <span class="ci-range">
                  [{v.ciLow.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} –
                  {v.ciHigh.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}]
                </span>
              {/if}
            </span>
            <button type="button" class="variant-delete"
              onclick={() => deleteVariant(v)}
              title="Удалить вариант" aria-label="Удалить вариант {v.name}">
              ×
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </section>

  <!-- ── Сравнение вариантов ─────────────────────────────────────────────── -->
  {#if variants.length > 0}
    <section class="comparison-section">
      <h3 class="section-title">Сравнение вариантов</h3>

      <!-- График истории+прогноза — единый, в секции «Прогноз базового плана»
           выше (baseline + варианты поверх). Здесь — табличное сравнение. -->
      {#if variants.length >= 1}
        <div class="scenario-page-wrap">
          <MultiScenarioPage
            scenarios={variants}
            baseline={null}
            kpiLabel={kpiLabelText}
            onDelete={deleteVariant}
          />
        </div>
      {/if}
    </section>

    <!-- ── U3/U4: вердикт ─────────────────────────────────────────────────── -->
    <section class="verdict-section" aria-live="polite">
      {#if verdict.ambiguous}
        <div class="verdict-card verdict-ambiguous">
          <AlertTriangle size={16} />
          <span>
            Разница между вариантами в пределах неопределённости –
            правдоподобные диапазоны перекрываются. Выбор любого из них обоснован.
          </span>
        </div>
      {:else if verdict.best}
        <div class="verdict-card verdict-best">
          <Info size={16} />
          <span>
            Рекомендуем «{verdict.best.name}»:
            {kpiLabelText} {verdict.best.predictedKpi.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}
            при бюджете {verdict.best.budget.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽.
          </span>
        </div>
      {/if}
    </section>
  {/if}

  <!-- ── U10: Disclaimers ──────────────────────────────────────────────────── -->
  <section class="disclaimers-section">
    <button
      type="button"
      class="disclaimers-toggle"
      onclick={() => { disclaimersOpen = !disclaimersOpen; }}
      aria-expanded={disclaimersOpen}
    >
      <Info size={14} />
      Показываем границы прогноза
      <ChevronDown size={14} class={disclaimersOpen ? 'chevron open' : 'chevron'} />
    </button>
    {#if disclaimersOpen}
      <ul class="disclaimers-list">
        {#each activeDisclaimers as d (d)}
          <li>{d}</li>
        {/each}
      </ul>
    {/if}
  </section>

  <!-- ── U7: Зафиксировать прогноз ─────────────────────────────────────────── -->
  <section class="promises-section">
    <h3 class="section-title">Зафиксировать прогноз</h3>
    <p class="promises-note">
      Зафиксируйте выбранный вариант – программа сверит прогноз с фактом
      при следующем обновлении данных.
    </p>

    <div class="promise-actions">
      <button
        type="button"
        class="btn-promise"
        onclick={fixForecastPromise}
        disabled={promiseSaving || !variants.length}
      >
        {promiseSaving ? 'Фиксируем...' : 'Зафиксировать прогноз'}
      </button>
      {#if promiseSuccess}
        <span class="promise-ok" role="status">{promiseSuccess}</span>
      {/if}
      {#if promiseError}
        <span class="promise-err" role="alert">{promiseError}</span>
      {/if}
    </div>

    <PromisesCard />
  </section>

  <!-- ── Переход к отчёту ─────────────────────────────────────────────────── -->
  <footer class="planning-footer">
    <button type="button" class="btn-to-report" onclick={goToReport}>
      К отчёту →
    </button>
  </footer>

</div>

<style>
  .planning-step {
    /* Дизайн-консистентность (2026-07-17): full-width + gap как у соседних
       шагов (Optimize 20 / Decompose 16). Узкая центрированная колонка
       960px и gap 32 выделяли раздел из программы. Скрол владеет
       .pipeline-main — здесь никаких overflow / height: 100%. */
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 0;
    box-sizing: border-box;
  }

  .trust-section { /* BacktestCard управляет своим display */ }

  .mediaplan-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .section-title {
    /* 15px как .block-title у OptimizeStep — ближайший структурный сосед */
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    margin: 0 0 4px;
  }
  .section-note {
    font-size: 13px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }
  .mp-warnings {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .mp-warning {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--warning, #f59e0b);
    padding: 4px 8px;
    background: color-mix(in srgb, var(--warning) 8%, transparent);
    border-radius: 4px;
  }
  .mp-table-wrap {
    overflow-x: auto;
    border-radius: 8px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
  }
  .mp-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .mp-table th,
  .mp-table td {
    padding: 8px 12px;
    text-align: right;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    color: var(--text-primary, #e2e8f0);
  }
  .mp-table th {
    font-weight: 500;
    color: var(--text-secondary, #94a3b8);
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
  }
  .mp-table .ch-name { text-align: left; font-weight: 500; }
  .mp-table .val { font-variant-numeric: tabular-nums; }

  .empty-plan-section {}
  .empty-plan-card {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
    padding: 20px 24px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
  }
  .empty-text {
    font-size: 14px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
    line-height: 1.6;
  }
  .btn-template {
    font-size: 13px;
    padding: 8px 16px;
    border-radius: 8px;
    border: 1px solid var(--border-default, rgba(255,255,255,0.15));
    background: transparent;
    color: var(--text-primary, #e2e8f0);
    cursor: pointer;
    transition: background 0.15s;
  }
  .btn-template:hover { background: rgba(255,255,255,0.06); }

  /* P-1: секция прогноза базового плана */
  .baseline-section {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .baseline-header {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .baseline-loading {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 20px 24px;
    font-size: 14px;
    color: var(--text-secondary, #94a3b8);
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
  }
  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid color-mix(in srgb, var(--accent-primary) 25%, transparent);
    border-top-color: var(--accent-primary, #3b82f6);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .baseline-error {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px;
    font-size: 14px;
    color: var(--danger, #ef4444);
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 20%, transparent);
    border-radius: 10px;
  }
  .btn-retry {
    margin-left: auto;
    font-size: 13px;
    padding: 6px 14px;
    border-radius: 8px;
    border: 1px solid var(--accent-primary, #3b82f6);
    background: transparent;
    color: var(--accent-primary, #3b82f6);
    cursor: pointer;
    white-space: nowrap;
  }
  .btn-retry:hover { background: color-mix(in srgb, var(--accent-primary) 10%, transparent); }
  .baseline-summary-card {
    display: flex;
    flex-wrap: wrap;
    gap: 32px;
    padding: 18px 24px;
    background: linear-gradient(
      135deg,
      color-mix(in srgb, var(--accent-primary) 10%, transparent),
      color-mix(in srgb, var(--accent-primary) 3%, transparent)
    );
    border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-radius: 12px;
  }
  .bsc-metric {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .bsc-label {
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .bsc-value {
    font-size: 22px;
    font-weight: 700;
    color: var(--text-primary, #e2e8f0);
    font-variant-numeric: tabular-nums;
  }
  .bsc-ci {
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    font-variant-numeric: tabular-nums;
  }

  .variants-section {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .variants-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  /* P-1: заметная btn-primary (была dashed-transparent — сливалась с фоном,
     Антон её не находил на приёмке 2026-07-10). */
  .btn-create-variant {
    font-size: 13px;
    font-weight: 500;
    padding: 9px 18px;
    border-radius: 8px;
    border: none;
    background: var(--accent-primary, #3b82f6);
    color: #fff;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  /* Hover-паттерн эталонных шагов — приглушение через opacity,
     не смена на посторонний оттенок (#2563eb вне палитры тем). */
  .btn-create-variant:hover { opacity: 0.85; }

  .variant-editor {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
  }
  .variant-name-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .variant-name-label {
    font-size: 13px;
    color: var(--text-secondary, #94a3b8);
    white-space: nowrap;
  }
  .variant-name-input {
    flex: 1;
    max-width: 280px;
    padding: 7px 12px;
    border-radius: 8px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.12));
    background: var(--bg-input, rgba(255,255,255,0.05));
    color: var(--text-primary, #e2e8f0);
    font-size: 14px;
  }
  .optimizer-wrap { /* BudgetOptimizer управляет шириной */ }
  .no-channels-note {
    font-size: 13px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
    padding: 12px;
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
  }
  .save-error {
    font-size: 13px;
    color: var(--danger, #ef4444);
    padding: 8px 12px;
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border-radius: 6px;
  }
  .variant-actions {
    display: flex;
    gap: 12px;
  }
  .btn-cancel {
    font-size: 13px;
    padding: 8px 16px;
    border-radius: 8px;
    border: 1px solid var(--border-default, rgba(255,255,255,0.12));
    background: transparent;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer;
  }
  .btn-save-variant {
    font-size: 13px;
    padding: 8px 20px;
    border-radius: 8px;
    border: none;
    background: var(--accent-primary, #3b82f6);
    color: #fff;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-save-variant:hover:not(:disabled) { opacity: 0.85; }
  .btn-save-variant:disabled { opacity: 0.5; cursor: not-allowed; }

  .variant-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .variant-chip {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 16px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 8px;
  }
  .variant-chip-name {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary, #e2e8f0);
    flex: 1;
  }
  .variant-chip-kpi {
    font-size: 13px;
    color: var(--text-secondary, #94a3b8);
    font-variant-numeric: tabular-nums;
  }
  .ci-range {
    font-size: 12px;
    opacity: 0.7;
    margin-left: 4px;
  }
  .variant-delete {
    background: none;
    border: none;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer;
    font-size: 18px;
    line-height: 1;
    padding: 0 4px;
    transition: color 0.15s;
  }
  .variant-delete:hover { color: var(--danger, #ef4444); }

  .comparison-section {
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .chart-wrap {
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
  }
  .scenario-page-wrap { /* MultiScenarioPage управляет высотой */ }

  .verdict-section {}
  .verdict-card {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 14px 18px;
    border-radius: 10px;
    font-size: 14px;
    line-height: 1.6;
  }
  .verdict-best {
    background: color-mix(in srgb, var(--success) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 20%, transparent);
    color: var(--success, #10b981);
  }
  .verdict-ambiguous {
    background: color-mix(in srgb, var(--warning) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning) 20%, transparent);
    color: var(--warning, #f59e0b);
  }

  .disclaimers-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .disclaimers-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--text-secondary, #94a3b8);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    transition: color 0.15s;
  }
  .disclaimers-toggle:hover { color: var(--text-primary, #e2e8f0); }
  :global(.chevron) { transition: transform 0.2s; }
  :global(.chevron.open) { transform: rotate(180deg); }
  .disclaimers-list {
    margin: 0;
    padding: 12px 20px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.6;
    list-style: disc;
  }

  .promises-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 20px 24px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
  }
  .promises-note {
    font-size: 13px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
    line-height: 1.6;
  }
  .promise-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .btn-promise {
    font-size: 13px;
    padding: 8px 20px;
    border-radius: 8px;
    border: 1px solid var(--accent-primary, #3b82f6);
    background: transparent;
    color: var(--accent-primary, #3b82f6);
    cursor: pointer;
    transition: background 0.15s;
  }
  .btn-promise:hover:not(:disabled) { background: color-mix(in srgb, var(--accent-primary) 10%, transparent); }
  .btn-promise:disabled { opacity: 0.5; cursor: not-allowed; }
  .promise-ok { font-size: 13px; color: var(--success, #10b981); }
  .promise-err { font-size: 13px; color: var(--danger, #ef4444); }

  .planning-footer {
    display: flex;
    justify-content: flex-end;
    padding-top: 8px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
  }
  .btn-to-report {
    font-size: 14px;
    font-weight: 500;
    padding: 10px 24px;
    border-radius: 10px;
    border: none;
    background: var(--accent-primary, #3b82f6);
    color: #fff;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-to-report:hover { opacity: 0.85; }
</style>
