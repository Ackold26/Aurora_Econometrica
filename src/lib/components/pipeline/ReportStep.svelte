<script>
  /**
   * Step 5: Report — Markdown & XLSX export from MMM pipeline data.
   * R1: Summary cards from modelData / decomposeData / optimizeData.
   * R2: econ_generate_report → Markdown file with Executive Summary preview.
   * R3: econ_export_xlsx → multi-sheet XLSX (5 sheets).
   * R4: completeStep(5) + triggerCompletion() on finish.
   * Layout: summary-cards → generate-card → complete-row.
   * @component ReportStep
   */
  import { invoke } from '@tauri-apps/api/core';
  import { openPath } from '@tauri-apps/plugin-opener';
  import { get } from 'svelte/store';
  import {
    activeProjectId,
    modelData,
    decomposeData,
    optimizeData,
    completeStep,
    setStepError,
    triggerCompletion,
  } from '$lib/project-state.js';
  import PipelineOnboarding from '$lib/components/pipeline/PipelineOnboarding.svelte';
  import { TOURS } from '$lib/pipeline-tours.js';
  import { shouldShowOnboarding } from '$lib/onboarding-state.js';
  import { unitCosts, activeProject } from '$lib/project-state.js';

  let showOnboarding = $state(false);
  let onboardingChecked = false;

  // Recompute decompose + optimize прямо с Report — когда stores обнулились
  // после смены unit_costs, но модель и файлы на диске есть.
  let recomputing = $state(false);
  /** @type {string|null} */
  let recomputeError = $state(null);

  /** Попытаться загрузить уже посчитанные результаты с диска (validation,
   * model-diagnostics, decomposition, optimization). Используется когда
   * stores обнулились после переключения проекта, но JSON-файлы на диске
   * ещё валидны. Быстрая альтернатива recomputeDownstream(). */
  async function reloadFromDisk() {
    const pid = get(activeProjectId);
    if (!pid) return;
    recomputing = true;
    recomputeError = null;
    try {
      const r = /** @type {any} */ (await invoke('project_load_results', { projectId: pid }));
      if (r.modelDiagnostics) {
        modelData.update(m => ({ ...m, diagnostics: r.modelDiagnostics }));
      }
      if (r.decomposition) decomposeData.set(r.decomposition);
      if (r.optimization) optimizeData.set(r.optimization);
      if (!r.modelDiagnostics && !r.decomposition && !r.optimization) {
        recomputeError = 'На диске нет ранее посчитанных результатов. Нужен пересчёт.';
      }
    } catch (/** @type {any} */ e) {
      recomputeError = String(e?.message || e);
    } finally {
      recomputing = false;
    }
  }

  async function recomputeDownstream() {
    const pid = get(activeProjectId);
    if (!pid) return;
    recomputing = true;
    recomputeError = null;
    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId: pid }));
      const uc = get(unitCosts) ?? {};
      const ucArg = Object.keys(uc).length > 0 ? uc : null;

      // Decompose → затем Optimize (последовательно, т.к. optimize читает decompose).
      const dResult = /** @type {any} */ (await invoke('econ_decompose', {
        projectDir, unitCosts: ucArg,
      }));
      if (dResult?.status !== 'ok') throw new Error(dResult?.message || 'Ошибка декомпозиции');
      decomposeData.set(dResult);

      const oResult = /** @type {any} */ (await invoke('econ_optimize', {
        projectDir,
        totalBudget: null,
        totalBudgetMoney: null,
        minPct: 50,
        maxPct: 150,
        minPerChannel: null,
        maxPerChannel: null,
        unitCosts: ucArg,
      }));
      if (oResult?.status !== 'ok') throw new Error(oResult?.message || 'Ошибка оптимизации');
      optimizeData.set(oResult);
    } catch (/** @type {any} */ e) {
      recomputeError = String(e?.message || e);
    } finally {
      recomputing = false;
    }
  }

  /** @type {'idle' | 'generating-report' | 'generating-xlsx' | 'done' | 'error'} */
  let stepState = $state('idle');
  /** @type {string | null} */
  let errorMessage = $state(null);
  /** @type {string | null} */
  let reportPath = $state(null);
  /** @type {string | null} */
  let xlsxPath = $state(null);
  /** @type {string | null} */
  let pptxPath = $state(null);
  /** @type {string | null} */
  let htmlPath = $state(null);
  /** @type {string | null} */
  let executiveSummary = $state(null);

  // Reactive store reads
  const mData = $derived($modelData);
  const dData = $derived($decomposeData);
  const oData = $derived($optimizeData);

  // Summary card values
  const mqs      = $derived(/** @type {number|null} */ (mData?.diagnostics?.mqs?.score ?? null));
  const mqsLabel = $derived(/** @type {string} */ (mData?.diagnostics?.mqs?.tier_label ?? '—'));
  const rSq      = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.r_squared ?? mData?.diagnostics?.r_squared ?? null));
  const mape     = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.mape_pct ?? mData?.diagnostics?.mape ?? null));
  const lift     = $derived(/** @type {number|null} */ (oData?.expected_lift_pct ?? null));
  const budget   = $derived(/** @type {number|null} */ (oData?.total_budget ?? null));

  const hasData  = $derived(!!mData?.diagnostics && !!dData && !!oData);

  // Обучающий тур — запускается когда все данные подгружены (есть что показывать).
  $effect(() => {
    if (typeof window === 'undefined') return;
    if (onboardingChecked) return;
    if (!hasData) return;
    onboardingChecked = true;
    if (shouldShowOnboarding('report')) {
      requestAnimationFrame(() => { showOnboarding = true; });
    }
  });

  // ── Dynamic summary for cover email ─────────────────────────────────────────
  const ratio    = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.ratio ?? null));
  const rHat     = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.r_hat_max ?? null));
  const divergences = $derived(/** @type {number|null} */ (mData?.diagnostics?.metrics?.divergences ?? null));
  const basePct  = $derived(/** @type {number|null} */ (dData?.baseline_pct ?? null));
  const decChannels = $derived(/** @type {any[]} */ (dData?.channels ?? []));
  const nChannels = $derived(decChannels.length);
  const nPeriods = $derived((dData?.time_series?.dates ?? []).length);
  const topDriver = $derived(
    [...decChannels].sort((a, b) => (b.contribution_pct || 0) - (a.contribution_pct || 0))[0] ?? null
  );
  const suspiciousChannels = $derived(
    decChannels.filter(/** @param {any} c */ c => /подозрительно/i.test(c.verdict || ''))
  );
  const lossChannels = $derived(
    decChannels.filter(/** @param {any} c */ c => /убыточн/i.test(c.verdict || ''))
  );

  /** Краткое описание модели (2-3 предложения). */
  const modelSummary = $derived.by(() => {
    if (!mData?.diagnostics) return '';
    const parts = [];
    parts.push(`Bayesian Marketing Mix Model с ${nChannels} канал${nChannels > 4 ? 'ами' : nChannels > 1 ? 'ами' : 'ом'} медиа через Adstock (отложенный эффект) + Hill saturation (убывающая отдача).`);
    parts.push(`Оценка через MCMC-сэмплер${rHat != null ? `, R-hat = ${rHat.toFixed(3)}` : ''}${divergences != null ? `, дивергенций ${divergences}` : ''}.`);
    if (nPeriods > 0) parts.push(`База данных: ${nPeriods} период${nPeriods > 4 ? 'ов' : nPeriods > 1 ? 'а' : ''}${ratio != null ? `, Ratio наблюдений к параметрам ${ratio.toFixed(1)}:1` : ''}.`);
    return parts.join(' ');
  });

  /** Краткое описание результатов (2-3 предложения). */
  const resultsSummary = $derived.by(() => {
    if (!mData?.diagnostics) return '';
    const parts = [];
    if (mqs != null) parts.push(`Качество модели: MQS ${mqs.toFixed(0)} (${mqsLabel})${rSq != null ? `, R² ${rSq.toFixed(3)}` : ''}${mape != null ? `, MAPE ${mape.toFixed(1)}%` : ''}.`);
    if (basePct != null) parts.push(`Декомпозиция продаж: baseline ${basePct.toFixed(0)}%, медиа-вклад ${(100 - basePct).toFixed(0)}%.`);
    if (topDriver) parts.push(`Главный драйвер — ${topDriver.name} (${topDriver.contribution_pct?.toFixed(0) ?? '—'}% от медиа-вклада, ROI ${topDriver.roi?.toFixed(2) ?? '—'}×).`);
    if (lift != null) {
      if (lift > 5) parts.push(`Оптимизация обещает +${lift.toFixed(1)}% KPI при текущем бюджете.`);
      else if (lift > 0.5) parts.push(`Оптимизация: +${lift.toFixed(1)}% — план близок к оптимальному.`);
      else parts.push(`Оптимизация: прирост ≈0% — план уже оптимален в заданных ограничениях.`);
    }
    return parts.join(' ');
  });

  /** Ограничения моделирования. */
  const limitationsSummary = $derived.by(() => {
    if (!mData?.diagnostics) return '';
    const items = [];
    if (ratio != null && ratio < 2) {
      items.push(`Данных критически мало (Ratio ${ratio.toFixed(1)}:1 < 2:1) — высокий риск переобучения. ROI и декомпозицию рассматривайте как ориентир, не истину.`);
    } else if (ratio != null && ratio < 4) {
      items.push(`Данных мало (Ratio ${ratio.toFixed(1)}:1 < 4:1 рекомендуемых). Доверительные интервалы широкие, CI для отдельных каналов могут включать 0.`);
    }
    if (suspiciousChannels.length > 0) {
      const names = suspiciousChannels.map(/** @param {any} c */ c => c.name).join(', ');
      items.push(`Каналы с подозрительно высоким ROI (${names}) — скорее всего артефакт переобучения или смешанных единиц измерения; не используйте их абсолютные значения.`);
    }
    if (lossChannels.length > 0) {
      const names = lossChannels.map(/** @param {any} c */ c => c.name).join(', ');
      items.push(`Убыточные/перенасыщенные каналы: ${names}. Перед решениями о перераспределении проверьте корректность unit_costs.`);
    }
    items.push('Модель описывает историю — прогнозы чувствительны к изменению креатива, новым кампаниям и структурным сдвигам рынка.');
    items.push('Перед принятием решений — пилот 4-6 недель на части бюджета (20-30%) для валидации на практике.');
    return items;
  });

  // ── Interpretation blocks (для маркетолога/руководителя) ───────────────────
  /** HTML-escape для user-controlled строк (имена каналов из xlsx) —
   * защита от XSS перед вставкой в {@html} интерпретации.
   * @param {unknown} s
   * @returns {string}
   */
  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#x27;');
  }

  /** Канал с самым высоким ROI (эффективность). */
  const bestRoiChannel = $derived(
    [...decChannels].sort((a, b) => (b.roi || 0) - (a.roi || 0))[0] ?? null
  );
  /** Канал с самым низким ROI. */
  const worstRoiChannel = $derived(
    [...decChannels].filter(/** @param {any} c */ c => c.roi != null)
      .sort((a, b) => (a.roi || 0) - (b.roi || 0))[0] ?? null
  );
  /** Недоинвестированные каналы (Gap > 15%) — много эффекта, мало бюджета. */
  const underfundedChannels = $derived(
    decChannels.filter(/** @param {any} c */ c => (c.efficiency_gap ?? 0) >= 15)
  );
  /** Перенасыщенные каналы (Gap < -15%) — много бюджета, мало эффекта. */
  const oversaturatedChannels = $derived(
    decChannels.filter(/** @param {any} c */ c => (c.efficiency_gap ?? 0) <= -15)
  );

  /** Текст «Что такое MMM простыми словами» — адаптирован под эту модель. */
  const interpretationMMM = $derived.by(() => {
    if (!mData?.diagnostics) return '';
    return `Marketing Mix Modeling (MMM) — это статистический способ разложить продажи на вклад каждого канала медиа и «органический» фон (base). Модель смотрит на вашу историю ${nPeriods > 0 ? `за ${nPeriods} период${nPeriods > 4 ? 'ов' : 'а'}` : ''} и ищет закономерности: «когда я добавлял бюджет в TV — продажи через 2-3 недели росли», «когда Performance выключали — падали сразу». На основе найденных закономерностей модель говорит сколько инкремента даёт каждый рубль в каждом канале.`;
  });

  /** Интерпретация качества модели. */
  const interpretationQuality = $derived.by(() => {
    if (!mData?.diagnostics || mqs == null) return '';
    const parts = [];
    if (mqs >= 80) parts.push(`**Качество модели — отличное (MQS ${mqs.toFixed(0)}).** Можно уверенно использовать результаты для принятия решений, включая перераспределение бюджета.`);
    else if (mqs >= 60) parts.push(`**Качество модели — хорошее (MQS ${mqs.toFixed(0)}).** Результаты надёжны для стратегических решений, но крайние значения ROI по отдельным каналам перепроверяйте.`);
    else parts.push(`**Качество модели — требует доработки (MQS ${mqs.toFixed(0)}).** Используйте как первичный ориентир, но не делайте крупных перекладов бюджета без пилота.`);
    if (rSq != null) {
      if (rSq >= 0.9) parts.push(`R² = ${rSq.toFixed(3)} означает что модель объясняет ${(rSq * 100).toFixed(0)}% колебаний продаж — почти всю динамику.`);
      else if (rSq >= 0.7) parts.push(`R² = ${rSq.toFixed(3)} — модель объясняет ${(rSq * 100).toFixed(0)}% динамики продаж. Оставшиеся ${((1 - rSq) * 100).toFixed(0)}% — шум, внешние факторы или каналы которых нет в данных.`);
      else parts.push(`R² = ${rSq.toFixed(3)} — модель объясняет только ${(rSq * 100).toFixed(0)}% динамики. Возможно, не хватает данных по каналам или есть сильное внешнее влияние.`);
    }
    if (mape != null) {
      if (mape <= 10) parts.push(`MAPE ${mape.toFixed(1)}% — в среднем прогноз отклоняется от факта меньше чем на десятую часть. Это очень точно.`);
      else if (mape <= 20) parts.push(`MAPE ${mape.toFixed(1)}% — приемлемая точность для стратегических решений.`);
      else parts.push(`MAPE ${mape.toFixed(1)}% — ошибка прогноза высокая, результаты используйте как ориентир.`);
    }
    return parts.join(' ');
  });

  /** Интерпретация декомпозиции (бренд vs перформанс). */
  const interpretationDecomposition = $derived.by(() => {
    if (!dData || basePct == null) return '';
    const parts = [];
    if (basePct >= 70) parts.push(`**У вас сильный бренд.** Базовые продажи = ${basePct.toFixed(0)}% — это клиенты которые купили бы и без рекламы. Медиа добавляет ${(100 - basePct).toFixed(0)}%.`);
    else if (basePct >= 40) parts.push(`**Бренд и медиа работают вместе.** База = ${basePct.toFixed(0)}%, медиа-вклад = ${(100 - basePct).toFixed(0)}%.`);
    else parts.push(`**Продажи держатся на рекламе.** База всего ${basePct.toFixed(0)}% — если остановить медиа, продажи упадут на ${(100 - basePct).toFixed(0)}%. Это характерно для молодых брендов или категорий с короткой лояльностью.`);
    if (topDriver) {
      parts.push(`**Главный медиа-драйвер — «${escapeHtml(topDriver.name)}»** (${topDriver.contribution_pct?.toFixed(0) ?? '—'}% от всего медиа-вклада${topDriver.roi != null ? `, ROI ${topDriver.roi.toFixed(2)}×` : ''}). Этот канал лучше всего генерирует продажи на текущем бюджете.`);
    }
    return parts.join(' ');
  });

  /** Интерпретация возможностей оптимизации. */
  const interpretationOptimization = $derived.by(() => {
    if (!oData) return '';
    const parts = [];
    if (lift != null) {
      if (lift > 10) parts.push(`**Оптимизация даст значительный прирост: +${lift.toFixed(1)}% KPI.** Это говорит что текущее распределение далеко от оптимального — есть реальная возможность увеличить продажи без дополнительного бюджета.`);
      else if (lift > 3) parts.push(`**Оптимизация даст умеренный прирост: +${lift.toFixed(1)}% KPI.** Текущий план в целом адекватный, но можно выжать ещё.`);
      else if (lift > 0.5) parts.push(`**Прирост +${lift.toFixed(1)}%** — план близок к оптимальному. Крупных неэффективностей нет.`);
      else parts.push(`**Прирост ≈0%** — план уже оптимален в заданных ограничениях. Чтобы получить больше, нужно либо менять min/max % по каналам, либо увеличивать общий бюджет.`);
    }
    if (underfundedChannels.length > 0) {
      const names = underfundedChannels.map(/** @param {any} c */ c => `«${escapeHtml(c.name)}»`).join(', ');
      parts.push(`**Недоинвестированные каналы** (дают непропорционально много эффекта): ${names}. Логика: если вложить больше денег — прирост KPI будет выше среднего.`);
    }
    if (oversaturatedChannels.length > 0) {
      const names = oversaturatedChannels.map(/** @param {any} c */ c => `«${escapeHtml(c.name)}»`).join(', ');
      parts.push(`**Перенасыщенные каналы** (денег много, а эффекта относительно мало): ${names}. Если убрать часть бюджета — потеряете меньше чем получите в альтернативных каналах.`);
    }
    return parts.join(' ');
  });

  /** Практические рекомендации — что делать дальше. */
  const interpretationActions = $derived.by(() => {
    if (!mData?.diagnostics) return [];
    const actions = [];
    if (lift != null && lift > 5) {
      actions.push(`Провести **пилот перераспределения** на 20-30% бюджета по рекомендациям оптимизации. Замерить фактический lift через 4-6 недель и сравнить с прогнозом.`);
    }
    if (underfundedChannels.length > 0) {
      actions.push(`Подумать об **увеличении инвестиций в недоинвестированные каналы** — ROI там сейчас выше среднего по портфелю.`);
    }
    if (oversaturatedChannels.length > 0) {
      actions.push(`**Не заливать дальше** перенасыщенные каналы — дополнительные рубли там дают всё меньший возврат (Hill saturation).`);
    }
    if (lossChannels.length > 0) {
      actions.push(`Проверить **unit_costs и чистоту данных** для убыточных каналов (${lossChannels.map(/** @param {any} c */ c => escapeHtml(c.name)).join(', ')}) — часто причина в неправильных единицах измерения, а не в самом канале.`);
    }
    if (ratio != null && ratio < 4) {
      actions.push(`**Накопить больше данных.** Сейчас Ratio ${ratio.toFixed(1)}:1 — мало для узких доверительных интервалов. ≥ 4:1 = ROI уверенные.`);
    }
    actions.push(`**Обновлять модель каждые 3-6 месяцев** по мере накопления новых данных и смены медиа-микса.`);
    return actions;
  });

  // ── FAQ — автогенерация Q&A на данных проекта ──────────────────────────────
  /** @type {Array<{q: string, a: string}>} */
  const faqItems = $derived.by(() => {
    if (!mData?.diagnostics) return [];
    const items = /** @type {Array<{q: string, a: string}>} */ ([]);

    // Q: про качество модели
    if (mqs != null) {
      if (mqs >= 80) {
        items.push({
          q: `Модель показывает MQS ${mqs.toFixed(0)} — это хорошо?`,
          a: `Да, отличный результат. MQS ≥ 80 означает что прогнозы точны, доверительные интервалы узкие, модель сошлась. Можно уверенно использовать для принятия бюджетных решений.`,
        });
      } else if (mqs >= 60) {
        items.push({
          q: `MQS ${mqs.toFixed(0)} — насколько надёжны выводы?`,
          a: `Хороший уровень для стратегических решений. Ключевые тренды (сильные/слабые каналы, необходимость перераспределения) — точны. Но крайние значения ROI по отдельным каналам (очень высокие или отрицательные) перепроверяйте через пилот.`,
        });
      } else {
        items.push({
          q: `Почему такой низкий MQS (${mqs.toFixed(0)})?`,
          a: `Скорее всего — мало данных или высокий шум. Модель работает, но её выводы ещё «шатаются». Используйте как первичный ориентир, без крупных перекладов бюджета. Накопите ещё 3-6 месяцев данных и переобучите.`,
        });
      }
    }

    // Q: R-hat / сходимость
    if (rHat != null) {
      if (rHat < 1.05) {
        items.push({
          q: `Что такое R-hat = ${rHat.toFixed(3)}?`,
          a: `Это индикатор сходимости MCMC-сэмплера (движка модели). R-hat должен быть < 1.05 — у вас ${rHat.toFixed(3)}, значит все цепи Маркова сошлись к одному решению. Модели можно доверять.`,
        });
      } else {
        items.push({
          q: `R-hat = ${rHat.toFixed(3)} — это проблема?`,
          a: `Да — идеально должен быть < 1.05. У вас ${rHat.toFixed(3)} — значит MCMC-цепи разошлись к разным решениям. Результаты ненадёжны, модель нужно переобучить с большим числом draws/tune, либо проверить на мультиколлинеарность каналов.`,
        });
      }
    }

    // Q: про топ-канал
    if (topDriver) {
      items.push({
        q: `Почему «${topDriver.name}» показал самый большой вклад?`,
        a: `У этого канала сочетание высокого бюджета и высокой эффективности (ROI ${topDriver.roi?.toFixed(2) ?? '—'}×). Он даёт ${topDriver.contribution_pct?.toFixed(0) ?? '—'}% всего медиа-вклада в продажи. Это не значит «лучший» — просто самый крупный. Смотрите ROI чтобы понять эффективность на рубль.`,
      });
    }

    // Q: про лучший ROI
    if (bestRoiChannel && bestRoiChannel.roi > 1.5) {
      items.push({
        q: `«${bestRoiChannel.name}» — ROI ${bestRoiChannel.roi.toFixed(2)}×. Означает ли это что надо залить туда весь бюджет?`,
        a: `Нет. Высокий ROI означает что следующий рубль в этом канале работает эффективно — но каналы имеют saturation (насыщение): по мере роста инвестиций ROI падает. Оптимизатор на шаге 5 учитывает это и находит сбалансированную точку, где предельный ROI во всех каналах выравнивается.`,
      });
    }

    // Q: про убыточные каналы
    if (lossChannels.length > 0) {
      const names = lossChannels.map(/** @param {any} c */ c => c.name).join(', ');
      items.push({
        q: `Каналы ${names} показаны как убыточные — закрывать?`,
        a: `Сначала проверьте корректность данных: правильные ли unit_costs (CPP/CPM), не смешаны ли единицы, нет ли нулевых периодов. Часто «убыточность» — артефакт данных, не канала. Если данные чистые — действительно стоит пересмотреть канал или креатив в нём.`,
      });
    }

    // Q: про оптимизацию
    if (lift != null) {
      if (lift > 5) {
        items.push({
          q: `Оптимизация даёт +${lift.toFixed(1)}% KPI — можно просто взять и переложить бюджет?`,
          a: `Теоретически да, но на практике — через пилот. Возьмите 20-30% бюджета, переложите по рекомендациям оптимизатора, замерьте факт через 4-6 недель. Если прогноз сошёлся (±3%) — масштабируйте. Если нет — модель нужно дообучить.`,
        });
      } else if (lift <= 0.5) {
        items.push({
          q: `Lift ≈0% — модель не нашла как улучшить план?`,
          a: `В рамках заданных ограничений (min/max % по каналам) — не нашла. Это значит план уже близок к оптимальному. Чтобы увеличить прирост: 1) снять ограничения (min=0, max=300%), 2) рассмотреть изменение общего бюджета (блок C — «Другой бюджет»), 3) добавить новый канал в медиа-микс.`,
        });
      }
    }

    // Q: baseline / органика
    if (basePct != null) {
      if (basePct > 60) {
        items.push({
          q: `${basePct.toFixed(0)}% baseline — это нормально?`,
          a: `Это показывает силу бренда. Высокая база (>60%) типична для зрелых брендов с лояльной аудиторией. Означает что даже без рекламы продажи не упадут до нуля — есть постоянный спрос. Фокус медиа — защищать долю и расти сверх базы.`,
        });
      } else if (basePct < 30) {
        items.push({
          q: `Baseline ${basePct.toFixed(0)}% — почему так мало?`,
          a: `Характерно для молодых брендов или категорий с импульсным спросом. Большая часть продаж идёт «в моменте» — от активной рекламы. Риск: при сокращении медиа-бюджета продажи упадут быстро. Долгосрочно — инвестируйте в brand-building чтобы растить базу.`,
        });
      }
    }

    // Q: прогноз
    items.push({
      q: `Насколько надёжен прогноз модели для планирования?`,
      a: `Прогноз хорошо работает в пределах исторического опыта — при сходном медиа-миксе и бюджете. При резком изменении (новые каналы, смена позиционирования, экономический шок) модель будет менее точной. Хорошая практика — каждые 3-6 месяцев обновлять модель на свежих данных.`,
    });

    // Q: данных мало
    if (ratio != null && ratio < 4) {
      items.push({
        q: `Ratio ${ratio.toFixed(1)}:1 — что это значит для интерпретации?`,
        a: `Ratio показывает сколько периодов данных приходится на каждый параметр модели. < 4:1 означает мало. Выводы работают для крупных решений (у какого канала ROI выше) но не для мелких сравнений (точное значение ROI с узкими CI). Накопите ещё 1-2 квартала — интервалы сузятся.`,
      });
    }

    return items;
  });

  // ── UI state для раскрывающихся блоков ─────────────────────────────────────
  let coverExpanded = $state(false);
  /** Какой формат сопровождать: 'pptx' | 'xlsx' | 'html' */
  let coverFormat = $state('pptx');
  let interpretationExpanded = $state(false);
  let faqExpanded = $state(false);
  let copyMsg = $state('');

  /** Построить plain-text версию текущего сопроводительного и скопировать. */
  async function copyCoverToClipboard() {
    const fmt = coverFormat;
    const lines = /** @type {string[]} */ ([]);
    if (fmt === 'pptx') {
      lines.push('Коллеги, прикладываю презентацию с результатами Marketing Mix Modeling.');
    } else if (fmt === 'xlsx') {
      lines.push('Во вложении — полные данные MMM-анализа для самостоятельной работы.');
    } else {
      lines.push('Направляю интерактивный отчёт MMM — откроется в любом браузере, ничего устанавливать не нужно.');
    }
    lines.push('');
    if (modelSummary) lines.push(`Модель. ${modelSummary}`, '');
    if (resultsSummary) lines.push(`Результаты. ${resultsSummary}`, '');
    if (limitationsSummary.length > 0) {
      lines.push('Ограничения и оговорки:');
      for (const item of limitationsSummary) lines.push(`- ${item}`);
      lines.push('');
    }
    if (fmt === 'pptx') {
      lines.push('Структура презентации:');
      lines.push('- Executive summary — MQS, R², MAPE, прирост от оптимизации');
      lines.push('- Спецификация модели — Bayesian MMM, Adstock + Hill, MCMC');
      lines.push('- Декомпозиция продаж — baseline vs медиа по каналам');
      lines.push('- ROI-анализ — Share of Spend vs Share of Effect, Gap');
      lines.push('- Динамика по периодам — вклад каналов во времени');
      lines.push('- Сравнение сценариев (если сохранены)');
      lines.push('- Оптимальное распределение бюджета с ожидаемым lift');
      lines.push('');
      lines.push('Готов обсудить детали и план пилота.');
    } else if (fmt === 'xlsx') {
      lines.push('Структура файла (листы XLSX):');
      lines.push('- Executive Summary — ключевые метрики качества');
      lines.push('- Спецификация — параметры модели, priors, методология');
      lines.push('- Декомпозиция — вклад baseline и каналов');
      lines.push('- ROI каналов — ROI, Gap, Efficiency');
      lines.push('- Spend vs Effect');
      lines.push('- Динамика — таблица + stacked-area chart');
      lines.push('- Сценарии — сравнение сохранённых');
      lines.push('- Оптимизация — текущее vs оптимальное');
      lines.push('- Данные — сырые time-series для своих графиков');
      lines.push('- Глоссарий — определения MMM-терминов');
      lines.push('');
      lines.push('Лист «Данные» особенно полезен: выделите колонки → Вставка → Диаграмма.');
    } else {
      lines.push('Что внутри HTML-отчёта:');
      lines.push('- Один файл, открывается двойным кликом в любом браузере');
      lines.push('- Интерактивные графики (ECharts): waterfall, ROI, Spend vs Effect, timeline, оптимизация');
      lines.push('- Tooltip на каждом графике, zoom/scroll по таймлайну');
      lines.push('- KPI-панель сверху: MQS, R², MAPE, R-hat, baseline, прирост, бюджет');
      lines.push('- Сводная таблица по каналам с цветовой разметкой ROI/Gap');
      lines.push('- Сравнение сохранённых сценариев (если есть)');
      lines.push('');
      lines.push('Не нужно устанавливать приложение — достаточно браузера.');
    }
    const text = lines.join('\n');
    try {
      await navigator.clipboard.writeText(text);
      copyMsg = '✓ Скопировано';
      setTimeout(() => { copyMsg = ''; }, 3000);
    } catch {
      copyMsg = 'Не удалось скопировать';
      setTimeout(() => { copyMsg = ''; }, 4000);
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  /**
   * @param {number | null} n
   * @param {number} [dec]
   */
  function fmt(n, dec = 1) {
    if (n == null) return '—';
    return n.toFixed(dec);
  }

  /** @param {number | null} n */
  function fmtBudget(n) {
    if (!n) return '—';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + ' М';
    if (n >= 1_000)     return (n / 1_000).toFixed(0) + ' К';
    return n.toFixed(0);
  }

  /** @param {string} msg */
  function handleError(msg) {
    errorMessage = msg;
    stepState = 'error';
    setStepError(5, msg);
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  async function generateReport() {
    const pid = get(activeProjectId);
    if (!pid || !hasData) return;

    stepState = 'generating-report';
    errorMessage = null;

    try {
      const result = /** @type {any} */ (await invoke('econ_generate_report', {
        projectId:    pid,
        modelData:    get(modelData),
        decomposeData: get(decomposeData),
        optimizeData:  get(optimizeData),
      }));

      if (result.status === 'ok') {
        reportPath = result.path ?? null;
        executiveSummary = result.summary ?? null;
        stepState = 'done';
      } else {
        handleError(result.message ?? 'Ошибка генерации отчёта');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    }
  }

  async function exportXlsx() {
    const pid = get(activeProjectId);
    if (!pid || !hasData) return;

    stepState = 'generating-xlsx';
    errorMessage = null;

    try {
      const result = /** @type {any} */ (await invoke('econ_export_xlsx', {
        projectId:    pid,
        modelData:    get(modelData),
        decomposeData: get(decomposeData),
        optimizeData:  get(optimizeData),
      }));

      if (result.status === 'ok') {
        xlsxPath = result.path ?? null;
        stepState = 'done';
      } else {
        handleError(result.message ?? 'Ошибка XLSX экспорта');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    }
  }

  async function exportHtml() {
    const pid = get(activeProjectId);
    if (!pid || !hasData) return;

    stepState = 'generating-xlsx';
    errorMessage = null;

    try {
      const project = get(activeProject);
      const result = /** @type {any} */ (await invoke('econ_export_html', {
        projectId:     pid,
        modelData:     get(modelData),
        decomposeData: get(decomposeData),
        optimizeData:  get(optimizeData),
        projectName:   project?.name ?? 'Marketing Mix Model',
      }));

      if (result.status === 'ok') {
        htmlPath = result.path ?? null;
        stepState = 'done';
      } else {
        handleError(result.message ?? 'Ошибка HTML');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    }
  }

  async function exportPptx() {
    const pid = get(activeProjectId);
    if (!pid || !hasData) return;

    stepState = 'generating-xlsx'; // reuse spinner state
    errorMessage = null;

    try {
      const result = /** @type {any} */ (await invoke('econ_export_pptx', {
        projectId:     pid,
        modelData:     get(modelData),
        decomposeData: get(decomposeData),
        optimizeData:  get(optimizeData),
      }));

      if (result.status === 'ok' || result.status === 'partial') {
        pptxPath = result.path ?? null;
        stepState = 'done';
        if (result.status === 'partial' && Array.isArray(result.failed_phases)) {
          console.warn('PPTX partial: failed phases =', result.failed_phases);
        }
      } else {
        handleError(result.message ?? 'Ошибка PPTX');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    }
  }

  async function openFolder() {
    const pid = get(activeProjectId);
    if (!pid) return;
    try {
      await invoke('econ_open_exports', { projectId: pid });
    } catch (/** @type {any} */ e) {
      console.error('Open folder error:', e);
    }
  }

  /**
   * M5a: открыть сгенерированный PPTX через OS default handler.
   * Клиент делает File → Save As → PDF/XPS для публикации (v1.0.11 MVP;
   * автоконвертация через LibreOffice headless запланирована на v1.0.12).
   */
  async function openPptxFile() {
    if (!pptxPath) return;
    try {
      await openPath(pptxPath);
    } catch (/** @type {any} */ e) {
      console.error('Open PPTX error:', e);
    }
  }

  function finishAnalysis() {
    completeStep(5);
    triggerCompletion();
  }
</script>

<div class="report-step">

  <!-- Error banner -->
  {#if stepState === 'error' && errorMessage}
    <div class="error-banner">
      <span class="error-icon">⚠</span>
      <span class="error-text">{errorMessage}</span>
      <button class="btn-retry" onclick={() => { stepState = 'idle'; errorMessage = null; }}>
        Попробовать снова
      </button>
    </div>
  {/if}

  <!-- Summary cards -->
  {#if hasData}
    <div class="summary-cards">
      <div class="card-metric">
        <div class="metric-label">MQS Score</div>
        <div class="metric-value" class:good={mqs != null && mqs >= 60} class:warn={mqs != null && mqs < 60}>
          {fmt(mqs)}
        </div>
        <div class="metric-sub">{mqsLabel}</div>
      </div>

      <div class="card-metric">
        <div class="metric-label">R²</div>
        <div class="metric-value" class:good={rSq != null && rSq >= 0.7} class:warn={rSq != null && rSq < 0.7}>
          {fmt(rSq, 3)}
        </div>
        <div class="metric-sub">объяснённая дисперсия</div>
      </div>

      <div class="card-metric">
        <div class="metric-label">MAPE</div>
        <div class="metric-value" class:good={mape != null && mape < 10} class:warn={mape != null && mape >= 20}>
          {mape != null ? fmt(mape, 1) + '%' : '—'}
        </div>
        <div class="metric-sub">средняя ошибка прогноза</div>
      </div>

      <div class="card-metric">
        <div class="metric-label">Прирост от оптимизации</div>
        <div
          class="metric-value lift"
          class:positive={lift != null && lift > 0}
          class:negative={lift != null && lift < 0}
        >
          {lift != null ? (lift >= 0 ? '+' : '') + fmt(lift) + '%' : '—'}
        </div>
        <div class="metric-sub">при перераспределении</div>
      </div>

      <div class="card-metric">
        <div class="metric-label">Оптим. бюджет</div>
        <div class="metric-value">{fmtBudget(budget)}</div>
        <div class="metric-sub">руб.</div>
      </div>
    </div>
  {:else}
    {@const missing = [!mData?.diagnostics && 'модель', !dData && 'декомпозиция', !oData && 'оптимизация'].filter(Boolean).join(', ')}
    <div class="no-data-banner">
      <div class="stale-header">⚠ Данные не загружены в память</div>
      <p class="stale-body">
        В этой сессии отсутствуют: {missing || 'результаты шагов'}.
        Если вы уже прошли пайплайн в другой сессии — результаты лежат на диске,
        и их можно подтянуть одним кликом. Если результатов нет — нужен пересчёт.
      </p>
      <div class="stale-actions">
        <button class="btn-recompute" onclick={reloadFromDisk} disabled={recomputing}>
          {recomputing ? 'Загружаю…' : '↓ Загрузить результаты с диска'}
        </button>
        {#if mData?.diagnostics}
          <button class="btn-recompute" style="background: transparent; border-color: var(--border); color: var(--text-secondary);" onclick={recomputeDownstream} disabled={recomputing}>
            {recomputing ? 'Пересчитываю…' : '↺ Пересчитать (декомпозиция + оптимизация)'}
          </button>
        {/if}
        {#if recomputeError}
          <span class="stale-error">⚠ {recomputeError}</span>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Generate card -->
  <div class="card generate-card">
    <div class="card-title">Экспорт результатов</div>

    {#if stepState === 'idle' || stepState === 'error' || stepState === 'done'}
      {#if stepState === 'done'}
        <div class="success-section">
          <div class="success-header">
            <span class="success-icon">✅</span>
            <span class="success-title">Файл сохранён</span>
          </div>
          {#if xlsxPath}
            <div class="file-row">
              <span class="file-icon">📊</span>
              <span class="file-path">{xlsxPath}</span>
            </div>
          {/if}
          {#if pptxPath}
            <div class="file-row">
              <span class="file-icon">📽</span>
              <span class="file-path">{pptxPath}</span>
              <button
                class="btn-open-file"
                onclick={openPptxFile}
                title="Для экспорта в PDF откройте файл → File → Save As → PDF/XPS"
              >Открыть</button>
            </div>
          {/if}
          {#if htmlPath}
            <div class="file-row">
              <span class="file-icon">🌐</span>
              <span class="file-path">{htmlPath}</span>
            </div>
          {/if}
          <div class="more-exports">
            <button class="btn-folder" onclick={openFolder}>📁 Открыть папку</button>
          </div>
          {#if executiveSummary}
            <div class="summary-preview">
              <div class="preview-title">Executive Summary</div>
              <pre class="preview-text">{executiveSummary}</pre>
            </div>
          {/if}
        </div>
      {/if}

      <div class="export-buttons" data-tour="report-exports">
        <button
          class="btn-export pptx"
          onclick={exportPptx}
          disabled={!hasData}
        >
          <span class="btn-icon">📽</span>
          {pptxPath ? 'PPTX — пересоздать' : 'Презентация (PPTX)'}
        </button>
        <button
          class="btn-export secondary"
          onclick={exportXlsx}
          disabled={!hasData}
        >
          <span class="btn-icon">📊</span>
          {xlsxPath ? 'XLSX — пересоздать' : 'Данные (XLSX)'}
        </button>
        <button
          class="btn-export html"
          onclick={exportHtml}
          disabled={!hasData}
          title="Интерактивный HTML-отчёт — открывается в браузере без установки приложения"
        >
          <span class="btn-icon">🌐</span>
          {htmlPath ? 'HTML — пересоздать' : 'Интерактивный (HTML)'}
        </button>
      </div>

      <div class="format-cards" data-tour="report-formats">
        <div class="format-card">
          <div class="format-card-header">
            <span class="format-icon">📽</span>
            <div class="format-title">PPTX — для презентации</div>
          </div>
          <p class="format-desc">
            Executive summary, спецификация модели (Bayesian MMM, Adstock, Hill), декомпозиция продаж,
            ROI по каналам, Share of Spend vs Effect, динамика по периодам, сравнение сценариев,
            оптимальное распределение, прогноз. С графиками и рекомендациями.
          </p>
        </div>

        <div class="format-card">
          <div class="format-card-header">
            <span class="format-icon">📊</span>
            <div class="format-title">XLSX — для самостоятельной работы с данными</div>
          </div>
          <p class="format-desc">
            Executive Summary, спецификация, декомпозиция, ROI, Spend vs Effect, динамика,
            сценарии, оптимизация, сырые time-series для собственных графиков, глоссарий.
          </p>
        </div>

        <div class="format-card">
          <div class="format-card-header">
            <span class="format-icon">🌐</span>
            <div class="format-title">HTML — интерактивный отчёт</div>
          </div>
          <p class="format-desc">
            Standalone-файл с живыми графиками (ECharts): waterfall, ROI, Spend vs Effect,
            динамика по периодам, оптимизация, сценарии. Открывается в любом браузере без
            установки приложения — можно отправлять клиентам как ссылку или вложение.
          </p>
        </div>
      </div>

      <!-- ── Unified cover letter block ─────────────────────────── -->
      <section class="info-block">
        <button
          type="button"
          class="info-toggle"
          onclick={() => coverExpanded = !coverExpanded}
          aria-expanded={coverExpanded}
        >
          <span class="info-arrow" class:open={coverExpanded}>▸</span>
          <span class="info-icon">✉️</span>
          <span class="info-title">Сопроводительный текст для письма</span>
          <span class="info-hint">— скопируйте и вставьте в тело email</span>
        </button>
        {#if coverExpanded}
          <div class="info-body">
            <div class="cover-format-tabs">
              <button
                type="button"
                class="cover-tab"
                class:active={coverFormat === 'pptx'}
                onclick={() => coverFormat = 'pptx'}
              >📽 Для PPTX</button>
              <button
                type="button"
                class="cover-tab"
                class:active={coverFormat === 'xlsx'}
                onclick={() => coverFormat = 'xlsx'}
              >📊 Для XLSX</button>
              <button
                type="button"
                class="cover-tab"
                class:active={coverFormat === 'html'}
                onclick={() => coverFormat = 'html'}
              >🌐 Для HTML</button>
            </div>
            <div class="cover-content">
              {#if coverFormat === 'pptx'}
                <p>Коллеги, прикладываю презентацию с результатами Marketing Mix Modeling.</p>
              {:else if coverFormat === 'xlsx'}
                <p>Во вложении — полные данные MMM-анализа для самостоятельной работы.</p>
              {:else}
                <p>Направляю интерактивный отчёт MMM — откроется в любом браузере, ничего устанавливать не нужно.</p>
              {/if}
              {#if modelSummary}
                <p><b>Модель.</b> {modelSummary}</p>
              {/if}
              {#if resultsSummary}
                <p><b>Результаты.</b> {resultsSummary}</p>
              {/if}
              {#if limitationsSummary.length > 0}
                <p><b>Ограничения и оговорки.</b></p>
                <ul>
                  {#each limitationsSummary as item}
                    <li>{item}</li>
                  {/each}
                </ul>
              {/if}
              {#if coverFormat === 'pptx'}
                <p><b>Структура презентации:</b></p>
                <ul>
                  <li>Executive summary — MQS, R², MAPE, прирост от оптимизации</li>
                  <li>Спецификация модели — Bayesian MMM, Adstock + Hill saturation, MCMC-сэмплер, priors</li>
                  <li>Декомпозиция продаж — вклад baseline vs медиа по каналам</li>
                  <li>ROI-анализ — Share of Spend vs Share of Effect, Gap, Efficiency</li>
                  <li>Динамика по периодам — вклад каналов во времени</li>
                  <li>Сравнение сохранённых сценариев (если есть)</li>
                  <li>Оптимальное распределение бюджета с ожидаемым lift</li>
                </ul>
                <p>Готов обсудить детали и план пилота.</p>
              {:else if coverFormat === 'xlsx'}
                <p><b>Структура файла:</b></p>
                <ul>
                  <li><b>Executive Summary</b> — ключевые метрики качества модели</li>
                  <li><b>Спецификация</b> — параметры модели (alpha, gamma, beta), priors, методология</li>
                  <li><b>Декомпозиция</b> — вклад baseline и каждого канала в продажи</li>
                  <li><b>ROI каналов</b> — ROI, Gap, Efficiency</li>
                  <li><b>Spend vs Effect</b> — share of spend vs share of effect</li>
                  <li><b>Динамика</b> — таблица по периодам + stacked-area chart</li>
                  <li><b>Сценарии</b> — сравнение сохранённых (если есть)</li>
                  <li><b>Оптимизация</b> — текущее vs оптимальное распределение</li>
                  <li><b>Данные</b> — сырые time-series для собственных графиков</li>
                  <li><b>Глоссарий</b> — определения MMM-терминов</li>
                </ul>
                <p>Лист «Данные» особенно полезен: выделите нужные колонки → Вставка → Диаграмма.</p>
              {:else}
                <p><b>Что внутри:</b></p>
                <ul>
                  <li>Один HTML-файл, открывается двойным кликом в любом браузере</li>
                  <li>Интерактивные графики (ECharts): waterfall, ROI, Spend vs Effect, stacked-area timeline, оптимизация</li>
                  <li>Tooltip на каждом графике, zoom/scroll по таймлайну</li>
                  <li>KPI-панель сверху: MQS, R², MAPE, R-hat, baseline %, прирост, бюджет</li>
                  <li>Сводная таблица по каналам с цветовой разметкой ROI/Gap</li>
                  <li>Сравнение сохранённых сценариев (если есть) с подсветкой лучшего ROAS</li>
                </ul>
                <p>Не нужно устанавливать приложение — достаточно браузера. Подходит для отправки клиентам и руководству.</p>
              {/if}
            </div>
            <div class="cover-actions">
              <button
                type="button"
                class="btn-copy"
                onclick={() => copyCoverToClipboard()}
              >📋 Скопировать текст</button>
              {#if copyMsg}
                <span class="copy-msg">{copyMsg}</span>
              {/if}
            </div>
          </div>
        {/if}
      </section>

      <!-- ── Model interpretation block (для маркетолога/руководителя) ─────────── -->
      <section class="info-block">
        <button
          type="button"
          class="info-toggle"
          onclick={() => interpretationExpanded = !interpretationExpanded}
          aria-expanded={interpretationExpanded}
        >
          <span class="info-arrow" class:open={interpretationExpanded}>▸</span>
          <span class="info-icon">🧭</span>
          <span class="info-title">Как интерпретировать модель и результаты</span>
          <span class="info-hint">— простыми словами для маркетолога/руководителя</span>
        </button>
        {#if interpretationExpanded}
          <div class="info-body">
            {#if interpretationMMM}
              <h4 class="interp-h">Что делает модель</h4>
              <p>{interpretationMMM}</p>
            {/if}
            {#if interpretationQuality}
              <h4 class="interp-h">Качество модели и доверие к выводам</h4>
              <!-- aurora-fix:safe V40 — upstream escapeHtml на user-sourced именах каналов (topDriver.name), ** → <b> контролируемая замена -->
              <p>{@html interpretationQuality.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')}</p>
            {/if}
            {#if interpretationDecomposition}
              <h4 class="interp-h">Структура ваших продаж</h4>
              <!-- aurora-fix:safe V40 — upstream escapeHtml на topDriver.name, ** → <b> контролируемая замена -->
              <p>{@html interpretationDecomposition.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')}</p>
            {/if}
            {#if interpretationOptimization}
              <h4 class="interp-h">Что можно улучшить</h4>
              <!-- aurora-fix:safe V40 — upstream escapeHtml на именах каналов (underfunded/oversaturated), ** → <b> контролируемая замена -->
              <p>{@html interpretationOptimization.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')}</p>
            {/if}
            {#if interpretationActions.length > 0}
              <h4 class="interp-h">Что делать дальше — практические шаги</h4>
              <ol class="actions-list">
                {#each interpretationActions as action}
                  <!-- aurora-fix:safe V40 — actions — статические строки из derived, без user input; ** → <b> контролируемая замена -->
                  <li>{@html action.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')}</li>
                {/each}
              </ol>
            {/if}
          </div>
        {/if}
      </section>

      <!-- ── FAQ block ─────────────────────────────────────────── -->
      {#if faqItems.length > 0}
        <section class="info-block">
          <button
            type="button"
            class="info-toggle"
            onclick={() => faqExpanded = !faqExpanded}
            aria-expanded={faqExpanded}
          >
            <span class="info-arrow" class:open={faqExpanded}>▸</span>
            <span class="info-icon">❓</span>
            <span class="info-title">Часто задаваемые вопросы по этой модели</span>
            <span class="info-hint">— {faqItems.length} вопрос{faqItems.length > 4 ? 'ов' : faqItems.length > 1 ? 'а' : ''} с ответами на ваших данных</span>
          </button>
          {#if faqExpanded}
            <div class="info-body faq-body">
              {#each faqItems as item, i}
                <details class="faq-item">
                  <summary class="faq-q">{i + 1}. {item.q}</summary>
                  <p class="faq-a">{item.a}</p>
                </details>
              {/each}
            </div>
          {/if}
        </section>
      {/if}

    {:else if stepState === 'generating-report' || stepState === 'generating-xlsx'}
      <div class="generating-state">
        <div class="spinner"></div>
        <p>{stepState === 'generating-report' ? 'Генерирую отчёт…' : 'Создаю файл…'}</p>
      </div>
    {/if}
  </div>

  <!-- Complete step -->
  {#if stepState === 'done'}
    <div class="complete-row">
      <button class="btn-complete" onclick={finishAnalysis}>
        Завершить анализ ✓
      </button>
    </div>
  {/if}

  {#if showOnboarding}
    <PipelineOnboarding
      steps={TOURS.report}
      stepKey="report"
      onDone={() => { showOnboarding = false; }}
    />
  {/if}

</div>

<style>
  .report-step {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px;
    height: 100%;
    box-sizing: border-box;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.1) transparent;
  }

  /* ── Error banner ─────────────────────────────────────── */
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

  /* ── Summary cards ────────────────────────────────────── */
  .summary-cards {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 8px;
  }
  @media (max-width: 1200px) {
    .summary-cards { grid-template-columns: repeat(3, 1fr); }
  }
  @media (max-width: 700px) {
    .summary-cards { grid-template-columns: repeat(2, 1fr); }
  }

  .card-metric {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 10px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .metric-label {
    font-size: 10px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: var(--text-secondary, #94a3b8);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .metric-value {
    font-size: 20px;
    font-weight: 700;
    font-family: monospace;
    color: var(--text-primary, #e2e8f0);
    line-height: 1.15;
  }
  .metric-value.good   { color: #22c55e; }
  .metric-value.warn   { color: #f59e0b; }
  .metric-value.lift.positive { color: #22c55e; }
  .metric-value.lift.negative { color: #ef4444; }
  .metric-sub {
    font-size: 10px;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .no-data-banner {
    padding: 14px 16px;
    background: color-mix(in srgb, var(--warning) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning) 25%, transparent);
    border-radius: 10px;
    font-size: 13px;
    color: #f59e0b;
    text-align: center;
  }

  .stale-header { font-weight: 600; font-size: 14px; margin-bottom: 8px; }
  .stale-body {
    text-align: left;
    color: var(--text-secondary);
    margin: 0 0 12px 0;
    font-size: 13px;
    line-height: 1.55;
  }
  .stale-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    justify-content: center;
    flex-wrap: wrap;
  }
  .btn-recompute {
    padding: 9px 18px;
    background: var(--accent-primary, #3b82f6);
    color: white;
    border: 1px solid var(--accent-primary, #3b82f6);
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-recompute:hover:not(:disabled) { opacity: 0.85; }
  .btn-recompute:disabled { opacity: 0.5; cursor: not-allowed; }
  .stale-error { color: var(--danger); font-size: 12px; }

  /* ── Generate card ────────────────────────────────────── */
  .card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 20px;
  }
  .card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    margin-bottom: 16px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .generate-card { flex: 1; min-height: 0; }

  .export-buttons {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }
  .btn-export {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 20px;
    border: none;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
    white-space: nowrap;
  }
  .btn-export.primary {
    background: var(--accent-primary, #3b82f6);
    color: white;
  }
  .btn-export.secondary {
    background: color-mix(in srgb, var(--success) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
    color: #22c55e;
  }
  .btn-export.pptx {
    background: rgba(139,92,246,0.15);
    border: 1px solid rgba(139,92,246,0.3);
    color: #a78bfa;
  }
  .btn-export.html {
    background: rgba(14,165,233,0.15);
    border: 1px solid rgba(14,165,233,0.3);
    color: #38bdf8;
  }
  .btn-export:hover:not(:disabled) { opacity: 0.85; }
  .btn-export:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-icon { font-size: 16px; }

  .export-hint {
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.6;
    margin: 0;
  }

  .format-cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-top: 14px;
  }
  @media (max-width: 900px) {
    .format-cards { grid-template-columns: 1fr; }
  }

  .format-card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 10px;
    padding: 14px 16px;
  }
  .format-card-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }
  .format-icon {
    font-size: 18px;
  }
  .format-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }
  .format-desc {
    font-size: 12.5px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.55;
    margin: 0 0 10px;
  }
  /* ── Generating ───────────────────────────────────────── */
  .generating-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    padding: 48px 20px;
  }
  .generating-state p {
    font-size: 14px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
  }

  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner {
    width: 32px;
    height: 32px;
    border: 3px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-top-color: var(--accent-primary, #3b82f6);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  /* ── Success section ──────────────────────────────────── */
  .success-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .success-header {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .success-icon { font-size: 18px; }
  .success-title {
    font-size: 15px;
    font-weight: 600;
    color: #22c55e;
  }

  .file-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
  }
  .file-icon { font-size: 14px; flex-shrink: 0; }
  .file-path {
    font-size: 11px;
    font-family: monospace;
    color: var(--text-secondary, #94a3b8);
    word-break: break-all;
    flex: 1;
  }

  .btn-open-file {
    padding: 4px 10px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.14);
    border-radius: 6px;
    color: var(--text-secondary, #94a3b8);
    font-size: 11px;
    cursor: pointer;
    flex-shrink: 0;
    transition: all 0.15s;
  }
  .btn-open-file:hover {
    border-color: rgba(255,255,255,0.3);
    color: var(--text-primary, #e2e8f0);
  }

  .more-exports {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .btn-more, .btn-folder {
    padding: 7px 14px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
  }
  .btn-more:hover, .btn-folder:hover {
    border-color: rgba(255,255,255,0.22);
    color: var(--text-primary, #e2e8f0);
  }

  /* ── Executive Summary preview ────────────────────────── */
  .summary-preview {
    background: color-mix(in srgb, var(--accent-primary) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 15%, transparent);
    border-radius: 10px;
    padding: 14px;
    max-height: 220px;
    overflow-y: auto;
    scrollbar-width: thin;
  }
  .preview-title {
    font-size: 10px;
    font-weight: 700;
    color: color-mix(in srgb, var(--accent-primary) 80%, transparent);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 10px;
  }
  .preview-text {
    font-size: 12px;
    font-family: inherit;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.7;
    white-space: pre-wrap;
    margin: 0;
  }

  /* ── Complete row ─────────────────────────────────────── */
  .complete-row {
    display: flex;
    justify-content: flex-end;
  }
  .btn-complete {
    padding: 12px 28px;
    background: linear-gradient(135deg, #22c55e, #16a34a);
    border: none;
    border-radius: 10px;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-complete:hover { opacity: 0.9; }

  /* ── Unified info blocks (cover / interpretation / FAQ) ────────────── */
  .info-block {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    overflow: hidden;
  }
  .info-toggle {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 14px 18px;
    background: transparent;
    border: none;
    color: var(--text-primary, #e2e8f0);
    font-family: inherit;
    font-size: 14px;
    text-align: left;
    cursor: pointer;
    transition: background 0.15s;
  }
  .info-toggle:hover {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 5%, transparent);
  }
  .info-arrow {
    display: inline-block;
    color: var(--text-muted, #64748b);
    font-size: 11px;
    transition: transform 0.2s;
    width: 12px;
  }
  .info-arrow.open { transform: rotate(90deg); }
  .info-icon { font-size: 18px; flex-shrink: 0; }
  .info-title { font-weight: 600; }
  .info-hint {
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
    font-weight: 400;
    margin-left: auto;
  }
  .info-body {
    padding: 4px 20px 20px 40px;
    color: var(--text-secondary, #cbd5e1);
    font-size: 13px;
    line-height: 1.6;
  }
  .info-body p { margin: 10px 0; }
  .info-body ul, .info-body ol { margin: 10px 0; padding-left: 22px; }
  .info-body li { margin: 4px 0; }

  /* Cover format tabs */
  .cover-format-tabs {
    display: flex;
    gap: 6px;
    margin: 0 0 12px 0;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  .cover-tab {
    padding: 6px 14px;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 7px;
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
    font-family: inherit;
  }
  .cover-tab:hover {
    color: var(--text-primary);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
  }
  .cover-tab.active {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 15%, transparent);
    border-color: var(--accent-primary, #3b82f6);
    color: var(--accent-primary, #3b82f6);
    font-weight: 600;
  }
  .cover-content { padding: 4px 0; }
  .cover-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  .btn-copy {
    padding: 8px 16px;
    background: var(--accent-primary, #3b82f6);
    color: white;
    border: 1px solid var(--accent-primary, #3b82f6);
    border-radius: 7px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-copy:hover { opacity: 0.9; }
  .copy-msg { color: var(--success, #22c55e); font-size: 12px; }

  /* Interpretation */
  .interp-h {
    margin: 16px 0 6px 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .interp-h:first-child { margin-top: 4px; }
  .actions-list { padding-left: 22px; }
  .actions-list li { margin: 8px 0; line-height: 1.55; }

  /* FAQ */
  .faq-body { padding: 4px 20px 16px 40px; }
  .faq-item {
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.05));
    padding: 10px 0;
  }
  .faq-item:last-child { border-bottom: none; }
  .faq-q {
    cursor: pointer;
    color: var(--text-primary, #e2e8f0);
    font-weight: 500;
    font-size: 13px;
    list-style: none;
    padding-left: 18px;
    position: relative;
    line-height: 1.5;
  }
  .faq-q::before {
    content: '+';
    position: absolute;
    left: 0;
    top: 0;
    color: var(--accent-primary, #3b82f6);
    font-weight: 700;
    font-size: 15px;
    transition: transform 0.2s;
  }
  .faq-item[open] .faq-q::before {
    content: '−';
  }
  .faq-q:hover { color: var(--accent-primary, #3b82f6); }
  .faq-a {
    margin: 8px 0 4px 18px;
    color: var(--text-secondary, #cbd5e1);
    font-size: 13px;
    line-height: 1.6;
  }
</style>
