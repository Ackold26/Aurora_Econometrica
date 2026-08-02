<script>
  /**
   * OptimizeGoalSeek - v1.3.0 inverse optimization UI (per ADR-014).
   *
   * Юзер задаёт целевые продажи, система ищет минимальный бюджет.
   * Использует backend `econ_optimize_inverse` через bisection.
   *
   * @component OptimizeGoalSeek
   */

  import { invoke } from '@tauri-apps/api/core';
  import {
    activeProjectId,
    kpiKind,
    derivedMode,
    valuePerCountUnit,
    planningMode,
    forecastConfig,
  } from '$lib/project-state.js';
  import { get } from 'svelte/store';
  import CorridorSlider from './CorridorSlider.svelte';
  import GoalSeekResultCard from './GoalSeekResultCard.svelte';
  import WhyThisStep from './WhyThisStep.svelte';
  import { TriangleAlert } from 'lucide-svelte';

  const { currentSales = 0, salesCorridor } = $props();

  // Target slider state. GS-2: стартовая цель задаётся в $effect ниже
  // (рекомендуемый умеренный рост в пределах коридора), 0 = «ещё не задана».
  let targetSales = $state(0);
  /** @type {number | null} */
  let maxBudgetCap = $state(null);
  /** @type {any | null} */
  let result = $state(null);
  let busy = $state(false);
  /** @type {string | null} */
  let errorMessage = $state(null);
  /** @type {'green' | 'yellow' | 'red'} */
  let currentZone = $state('green');
  // OPP-02 (2026-07-03): режим «бюджет под вероятность». false = обычный
  // (медианный: бюджет достигает цели в ~половине сценариев модели),
  // true = осторожный (минимальный бюджет с P(достижения) >= 80% по
  // апостериорным сценариям). Уровень 0.8 фиксирован продуктово.
  let cautiousMode = $state(false);
  const CAUTIOUS_CONFIDENCE = 0.8;
  // C3-N2: показать кнопку «Переключить в Анализ» в сообщении об ошибке
  // (переключатель режимов отрисован только на вкладке «От бюджета»).
  let showAnalystSwitch = $state(false);

  function switchToAnalyst() {
    planningMode.set('analyst');
    showAnalystSwitch = false;
    errorMessage = null;
  }

  // 2026-06-07: АДАПТИВНАЯ шкала цели под РЕЗУЛЬТАТ модели. Раньше верх слайдера =
  // currentSales×1.5×1.15 (чистая эвристика, не связана с тем, что модель реально
  // может достичь при насыщении) → большая «недостижимая» зона. Теперь зондируем
  // достижимый потолок (forward при макс. бюджете) один раз: заведомо-недостижимая
  // цель в econ_optimize_inverse возвращает fallback_max_sales = этот потолок.
  // Слайдер ограничивается им → «Цель недостижима» только у самого края.
  /** @type {number | null} */
  let achievableCeiling = $state(null);
  let probingCeiling = $state(false);

  $effect(() => {
    if (!$activeProjectId || currentSales <= 0) return;
    if (achievableCeiling !== null || probingCeiling) return;
    if ($planningMode === 'planner') return; // goal-seek недоступен в planner
    probingCeiling = true;
    (async () => {
      try {
        const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId: get(activeProjectId) }));
        const probe = /** @type {any} */ (await invoke('econ_optimize_inverse', {
          projectDir,
          targetSales: currentSales * 1000, // заведомо недостижимо → вернёт потолок
          kpiKind: get(kpiKind),
          mode: get(derivedMode),
          maxBudget: null,
          minBudget: null,
        }));
        const c = Number(probe?.fallback_max_sales ?? probe?.expected_sales ?? 0);
        if (Number.isFinite(c) && c > currentSales) achievableCeiling = c;
      } catch (e) {
        /* мягко: оставляем эвристический коридор */
      } finally {
        probingCeiling = false;
      }
    })();
  });

  const corridorLo = $derived(salesCorridor?.lo ?? Math.max(0, currentSales * 0.7));
  // Мат-аудит 2026-07-02 (INV-50): зелёная зона слайдера = НАБЛЮДАВШИЙСЯ диапазон
  // (salesCorridor), НЕ потолок модели. Прежде (правка 2026-06-07, адаптивная шкала)
  // corridorHi = achievableCeiling закрашивал зелёным весь путь до асимптоты модели
  // при 5× бюджете — глубокую экстраполяцию, — тогда как подсказка рядом обещала
  // «зелёная зона = без экстраполяции за observed range». Потолок достижимости
  // остаётся ВЕРХОМ ШКАЛЫ (sliderMax): UX «недостижимая зона у самого края»
  // сохранён, но зона выше corridorHi честно жёлто-красная (Chan & Perry 2017:
  // кривая вне наблюдённого диапазона не идентифицируется данными).
  const corridorHi = $derived(salesCorridor?.hi ?? currentSales * 1.5);

  /**
   * Пришёл ли НАСТОЯЩИЙ коридор продаж, а не запасной ориентир.
   *
   * 🔴 Движок его пока не считает: `optimize/bounds.py::compute_safe_corridor`
   * возвращает `per_channel` и `aggregate_budget`, а `aggregate_sales` живёт
   * ТОЛЬКО в докстринге с пометкой «placeholder, требует forward pass» — в коде
   * его нет, и в `goal_seek.py` тоже. Пока так, зелёная зона считается от
   * текущего уровня (×0,7…×1,5), и называть её наблюдавшимся диапазоном нельзя:
   * это разные вещи, и клиент принимал бы решение по обещанию, которого продукт
   * не выполняет. Настоящий расчёт — в P1, вместе с профит-фронтиром: обоим
   * нужен один и тот же прямой проход через модель, считать порознь значит
   * делать работу дважды.
   */
  const corridorIsObserved = $derived(
    salesCorridor?.lo != null && salesCorridor?.hi != null,
  );

  const corridorNote = $derived(
    corridorIsObserved
      ? 'Цель должна быть в зелёной зоне коридора – иначе модель считает за пределами того, что наблюдала в данных.'
      : 'Зелёная зона – ориентир от текущего уровня продаж, а не диапазон, наблюдавшийся в данных: его модель пока не рассчитывает. Чем дальше цель от текущего уровня, тем осторожнее относитесь к результату.',
  );
  const sliderMax = $derived(
    Math.max(achievableCeiling ?? corridorHi * 1.15, corridorHi * 1.02)
  );

  // GS-2 (2026-06-02): рекомендуемый стартовый ориентир - умеренный рост +10%,
  // но не выше безопасного коридора (×0.95 от верхней границы). Раньше дефолт =
  // currentSales (цель = текущим, +0% - бессмысленный старт). Срабатывает один раз,
  // когда currentSales известен; дальше пользователь правит слайдером/полем.
  $effect(() => {
    if (currentSales > 0 && targetSales === 0) {
      const recommended = Math.min(currentSales * 1.1, corridorHi * 0.95);
      targetSales = recommended > 0 ? recommended : currentSales;
    }
  });

  /** @param {number} n */
  function formatTarget(n) {
    if ($kpiKind === 'monetary') {
      if (n >= 1e9) return `${(n / 1e9).toFixed(2)} млрд ₽`;
      if (n >= 1e6) return `${(n / 1e6).toFixed(1)} млн ₽`;
      return `${Math.round(n).toLocaleString('ru-RU')} ₽`;
    }
    return `${Math.round(n).toLocaleString('ru-RU')} ед.`;
  }

  async function runGoalSeek() {
    if (!$activeProjectId) {
      errorMessage = 'Откройте проект сначала.';
      return;
    }
    // v2.1.0 (pilot E P0-1 2026-05-17): block Goal-Seek в planning mode -
    // backend _forward_at_budget строит config без forecast_periods/inflation,
    // поэтому target из планируемого горизонта применяется к training horizon
    // → backend ищет budget в неверном масштабе. Honest reject с инструкцией
    // переключиться в analyst mode для Goal-Seek.
    if ($planningMode === 'planner') {
      // C3-N2 (2026-07-03): прежний текст отсылал к переключателю «вверху
      // страницы», который в goal-seek-ветке НЕ отрисован (он на вкладке
      // «От бюджета») — пользователь оказывался в тупике. Теперь кнопка
      // переключения прямо в сообщении (рендер ниже по showAnalystSwitch).
      errorMessage = (
        'Подбор бюджета под цель недоступен в режиме «Планирование». ' +
        'Переключитесь в режим «Анализ» кнопкой ниже, либо используйте расчёт ' +
        '«От бюджета» для прогнозного горизонта.'
      );
      showAnalystSwitch = true;
      return;
    }
    busy = true;
    errorMessage = null;
    result = null;
    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId: $activeProjectId }));
      const res = await invoke('econ_optimize_inverse', {
        projectDir,
        targetSales: targetSales,
        kpiKind: $kpiKind,
        mode: $derivedMode,
        maxBudget: maxBudgetCap,
        minBudget: null,
        // OPP-02: null = медианный режим (прежнее поведение).
        confidence: cautiousMode ? CAUTIOUS_CONFIDENCE : null,
      });
      result = res;
    } catch (e) {
      const err = /** @type {{message?: string} | string} */ (e);
      errorMessage = typeof err === 'string' ? err : String(err?.message ?? err);
      console.error('Goal-Seek failed:', e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="goal-seek-panel">
  <WhyThisStep
    stepId="optimize-goal-seek"
    title="Зачем Goal-Seek?"
    whatWeDo="Вы задаёте целевые продажи. Программа находит минимальный бюджет, при котором эта цель достижима с высокой вероятностью."
    whyNeed="Прямая оптимизация отвечает: «у меня есть бюджет – куда вложить?». Расчёт от цели отвечает на вопрос руководителя: «нужно достичь продаж X – сколько потратить?»"
    attentionTo={[
      corridorNote,
      'Правдоподобный диапазон на бюджете шире, чем точечная оценка - учитывайте при планировании.',
      'Низкая P(достижения) означает, что цель близка к границам - рассмотрите менее агрессивные цели.',
    ]}
    whatsNext="Получите распределение по каналам и можно сразу строить отчёт «План достижения цели X»."
  />

  <section class="target-controls">
    <h3>Целевые продажи</h3>
    <CorridorSlider
      value={targetSales}
      min={corridorLo * 0.5}
      max={sliderMax}
      corridorLo={corridorLo}
      corridorHi={corridorHi}
      yellowZonePct={0.10}
      step={(sliderMax - corridorLo * 0.5) / 100}
      label="Целевые продажи"
      formatFn={formatTarget}
      onChange={(/** @type {number} */ v) => { targetSales = v; }}
      onZoneChange={(/** @type {'green' | 'yellow' | 'red'} */ z) => { currentZone = z; }}
    />

    <div class="numeric-input">
      <label for="target-direct">Или введите точно:</label>
      <input
        id="target-direct"
        type="text"
        inputmode="numeric"
        value={Math.round(Number(targetSales) || 0).toLocaleString('ru-RU')}
        onfocus={(e) => /** @type {HTMLInputElement} */ (e.target).select()}
        oninput={(e) => {
          const raw = /** @type {HTMLInputElement} */ (e.target).value.replace(/\D/g, '');
          targetSales = parseInt(raw, 10) || 0;
        }}
      />
      <span class="unit">{$kpiKind === 'monetary' ? '₽' : 'ед.'}</span>
    </div>
  </section>

  <section class="budget-cap">
    <label>
      <input
        type="checkbox"
        checked={maxBudgetCap !== null}
        onchange={(e) => {
          const target = /** @type {HTMLInputElement} */ (e.target);
          maxBudgetCap = target.checked ? currentSales : null;
        }}
      />
      Ограничить максимальный бюджет (опционально)
    </label>
    {#if maxBudgetCap !== null}
      <input
        type="number"
        min="0"
        bind:value={maxBudgetCap}
        placeholder="например, 100000000"
      />
      <span class="unit">₽</span>
    {/if}
  </section>

<!-- OPP-02 (2026-07-03): «бюджет под вероятность» — переключатель режима расчёта. -->
  <section class="confidence-mode" role="radiogroup" aria-label="Режим расчёта бюджета">
    <span class="mode-title">Режим расчёта:</span>
    <div class="mode-segment">
      <button
        type="button"
        class="mode-option"
        class:active={!cautiousMode}
        aria-pressed={!cautiousMode}
        onclick={() => { cautiousMode = false; }}
      >
        Обычный (медиана)
      </button>
      <button
        type="button"
        class="mode-option"
        class:active={cautiousMode}
        aria-pressed={cautiousMode}
        onclick={() => { cautiousMode = true; }}
      >
        Осторожный (80%)
      </button>
    </div>
    <p class="mode-hint">
      {#if cautiousMode}
        Минимальный бюджет, при котором цель достигается не менее чем в 80%
        сценариев модели. Бюджет выше медианного – надбавка растёт с
        неопределённостью модели.
      {:else}
        Бюджет, при котором модель достигает цели в типичном (медианном)
        сценарии – примерно в половине случаев. Для планирования с запасом
        включите осторожный режим.
      {/if}
    </p>
  </section>

  <div class="actions">
    <button
      type="button"
      class="btn-primary"
      disabled={busy || currentZone === 'red' || !targetSales}
      onclick={runGoalSeek}
    >
      {busy ? 'Ищем оптимум...' : 'Найти решение →'}
    </button>
    {#if currentZone === 'red'}
      <span class="zone-warning">
        <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Цель в красной зоне - кнопка заблокирована.
      </span>
    {/if}
  </div>

  {#if errorMessage}
    <div class="error">
      {errorMessage}
      {#if showAnalystSwitch}
        <button type="button" class="btn-switch-analyst" onclick={switchToAnalyst}>
          Переключить в режим «Анализ»
        </button>
      {/if}
    </div>
  {/if}

  {#if result}
    <GoalSeekResultCard result={result} kpiKind={$kpiKind} targetSales={targetSales} />
  {/if}
</div>

<style>
  .goal-seek-panel {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 12px 0;
  }
  .target-controls h3 {
    margin: 0 0 12px;
    font-size: 14px;
    font-weight: 700;
    color: var(--text-primary);
  }
  .numeric-input {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 10px;
    font-size: 12px;
  }
  .numeric-input label { color: var(--text-muted); }
  .numeric-input input {
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 13px;
    width: 200px;
    font: inherit;
  }
  .unit { color: var(--text-muted); font-size: 12px; }

  .budget-cap {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 10px 12px;
    background: var(--bg-surface-quiet);
    border-radius: var(--radius-sm, 6px);
    font-size: 12px;
    color: var(--text-secondary);
  }
  .budget-cap label { display: flex; gap: 6px; align-items: center; cursor: pointer; }
  .budget-cap input[type="number"] {
    padding: 4px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 12px;
    width: 160px;
    font: inherit;
  }

  /* OPP-02: сегмент-переключатель режима расчёта («медиана» / «80%»). */
  .confidence-mode {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 10px;
    padding: 10px 12px;
    background: var(--bg-surface-quiet);
    border-radius: var(--radius-sm, 6px);
    font-size: 12px;
  }
  .mode-title { color: var(--text-secondary); font-weight: 600; }
  .mode-segment {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    overflow: hidden;
  }
  .mode-option {
    padding: 6px 12px;
    background: var(--bg-card);
    color: var(--text-secondary);
    border: none;
    font-size: 12px;
    cursor: pointer;
    font: inherit;
  }
  .mode-option + .mode-option { border-left: 1px solid var(--border); }
  .mode-option.active {
    background: var(--accent-primary);
    color: #fff;
    font-weight: 600;
  }
  .mode-hint {
    flex-basis: 100%;
    margin: 0;
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-muted);
  }

  .actions {
    display: flex;
    gap: 10px;
    align-items: center;
  }
  .btn-primary {
    padding: 10px 20px;
    background: var(--accent-primary);
    color: #fff;
    border: 1px solid var(--accent-primary);
    border-radius: var(--radius-btn, 8px);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    font: inherit;
  }
  .btn-primary:disabled {
    background: var(--bg-surface-quiet);
    color: var(--text-muted);
    border-color: var(--border);
    cursor: not-allowed;
  }
  .zone-warning {
    font-size: 11px;
    color: var(--danger, #f87171);
  }

  .error {
    padding: 10px 12px;
    background: color-mix(in srgb, var(--danger, #f87171) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger, #f87171) 30%, transparent);
    border-radius: var(--radius-sm, 6px);
    font-size: 12px;
    color: var(--danger, #f87171);
  }
  /* C3-N2: кнопка переключения режима прямо из сообщения об ошибке. */
  .btn-switch-analyst {
    display: block;
    margin-top: 8px;
    padding: 6px 12px;
    background: var(--accent-primary);
    color: #fff;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    font: inherit;
  }
</style>
