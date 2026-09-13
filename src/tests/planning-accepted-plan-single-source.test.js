/**
 * Сторож находки 2 внешнего аудита s47 (High, 2026-09-14): экран и унесённый
 * документ называли принятыми РАЗНЫЕ планы.
 *
 * Принятый план выбирался тремя правилами: при создании варианта в манифест
 * `results/planning.json` шёл ПОСЛЕДНИЙ созданный, кнопка «К отчёту» писала
 * ЛУЧШИЙ по прогнозу, а правило P4 панели подсказок считало лучшего только
 * среди вариантов С правдоподобным диапазоном. Документ
 * (`engines/planning.py`, `summarize_forecast`) судит `accepted_variant` из
 * манифеста – и на одних и тех же числах экран советовал «планировать от
 * центра» про один план, а документ «берите по нижней границе» про другой
 * (INV-50: имя и число на экране обязаны соответствовать источнику).
 *
 * Проверки взяты на наборе, где ЛУЧШИЙ по прогнозу и ПОСЛЕДНИЙ созданный –
 * разные варианты: прежние проверки шага брали один вариант и потому были
 * зелёными при любом из трёх правил.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent, screen } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { get } from 'svelte/store';
import {
  activeProjectId, modelData, decomposeData, optimizeData, mediaPlanDetected,
} from '$lib/project-state.js';
import { planningLiveState } from '$lib/planning-live-state.js';
import { planningInsights } from '$lib/insights-rules.js';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: Probe } = await import('./EChartOptionProbe.svelte');
  return { default: Probe };
});

import PlanningStep from '$lib/components/pipeline/PlanningStep.svelte';

const futureDates = ['2025-01', '2025-02', '2025-03'];

/** Прогнозы по имени сценария: А – сильный и узкий, Б – слабый и широкий. */
let SCENARIOS = {};
const DEFAULT_SCENARIOS = {
  'Базовый план': { kpi: 15000, lo: 12000, hi: 18000 },
  'Вариант А':    { kpi: 20000, lo: 19000, hi: 21000 },
  'Вариант Б':    { kpi: 12000, lo:  6000, hi: 18000 },
};

/** Имена, ушедшие в манифест в порядке записи (аргумент econ_save_planning). */
/** @type {string[]} */
let manifestLog = [];

/** Подсказки шага ровно так, как их строит InsightsPanel: из живого состояния. */
function screenInsights() {
  const live = get(planningLiveState);
  return planningInsights({
    mediaPlan: get(mediaPlanDetected),
    probeStatus: 'found',
    horizonPeriods: 3,
    historyPeriods: 24,
    baseline: live.baseline,
    variants: live.variants,
    acceptedName: live.acceptedName,
    diagnostics: get(modelData)?.diagnostics ?? null,
    ssotRatio: null,
  }).map((i) => i.text);
}

/** Создать вариант через интерфейс шага. */
async function createVariant(name) {
  await fireEvent.click(screen.getByRole('button', { name: /Создать вариант/ }));
  const input = await screen.findByLabelText('Название');
  await fireEvent.input(input, { target: { value: name } });
  await fireEvent.click(await screen.findByRole('button', { name: new RegExp('Сохранить как «' + name + '»') }));
  await waitFor(() => {
    expect(get(planningLiveState).variants.some((v) => v.name === name)).toBe(true);
  }, { timeout: 4000 });
}

async function mountWithBaseline() {
  const rendered = render(PlanningStep);
  await waitFor(() => {
    expect(get(planningLiveState).baseline).not.toBeNull();
  }, { timeout: 5000 });
  return rendered;
}

beforeEach(() => {
  vi.clearAllMocks();
  manifestLog = [];
  SCENARIOS = structuredClone(DEFAULT_SCENARIOS);
  vi.mocked(invoke).mockImplementation(async (/** @type {string} */ cmd, /** @type {any} */ args) => {
    if (cmd === 'project_get_dir') return 'D:/tmp/proj';
    if (cmd === 'project_load_results') throw new Error('нет результатов на диске');
    if (cmd === 'econ_save_planning') { manifestLog.push(String(args?.acceptedVariant)); return { status: 'ok' }; }
    if (cmd === 'econ_scenario') {
      const s = SCENARIOS[args?.scenarioName] ?? SCENARIOS['Базовый план'];
      return {
        status: 'ok',
        predictions: [s.kpi / 3, s.kpi / 3, s.kpi / 3],
        predictions_ci_low: s.lo == null ? [] : [s.lo / 3, s.lo / 3, s.lo / 3],
        predictions_ci_high: s.hi == null ? [] : [s.hi / 3, s.hi / 3, s.hi / 3],
        future_dates: futureDates,
        totals: {
          predicted_kpi: s.kpi,
          total_spend_money: 900_000,
          predicted_kpi_ci_low: s.lo,
          predicted_kpi_ci_high: s.hi,
        },
        disclaimers: [],
      };
    }
    return null;
  });

  activeProjectId.set('project-A');
  modelData.set({
    diagnostics: { mqs: { score: 75, tier_label: 'Хорошее' }, metrics: { ratio: 4.2 }, scaled_params: {}, decays: {} },
    channelParams: null, picklePath: 'x', normalization: null,
  });
  decomposeData.set({
    decomposition_series: {
      dates: Array.from({ length: 24 }, (_, i) => `2023-${String((i % 12) + 1).padStart(2, '0')}`),
      series: [{ name: 'ТВ', data: Array.from({ length: 24 }, () => 10) }],
    },
    channels: [{ name: 'ТВ', spend: 100, contribution: 40, roi: 0.4 }],
  });
  optimizeData.set({
    channels: [{ name: 'ТВ', optimal_spend_money: 600_000, current_spend_money: 500_000 }],
    current_kpi: 300,
  });
  mediaPlanDetected.set({
    n_future_periods: 3,
    channels: { ТВ: [300_000, 300_000, 300_000] },
    period_labels: futureDates,
    future_dates: futureDates,
    warnings: [],
    granularity: 'month',
    confirmed: true,
    source_hash: 'hash-A',
  });
  planningLiveState.set({ acceptedName: null, baseline: null, variants: [] });
});

describe('принятый план выбирается одним правилом на всю программу', () => {
  it('уход со шага мимо «К отчёту» оставляет в манифесте тот же план, что назван на экране', async () => {
    await mountWithBaseline();

    await createVariant('Вариант А');   // лучший по прогнозу
    await createVariant('Вариант Б');   // слабее, но создан последним

    // «Далее ▶» в подвале мастера и боковая навигация goToReport не зовут –
    // манифест обязан быть согласован уже сейчас, на записи варианта.
    expect(
      manifestLog[manifestLog.length - 1],
      'в манифест обязан идти лучший по прогнозу, а не последний созданный',
    ).toBe('Вариант А');

    const texts = screenInsights();
    expect(
      texts.some((t) => t.includes('У принятого плана «Вариант А»')),
      'панель подсказок обязана называть принятым тот же план, что ушёл в манифест',
    ).toBe(true);
    expect(
      texts.some((t) => t.includes('У принятого плана «Вариант Б»')),
      'принятым не может называться план, которого нет в манифесте',
    ).toBe(false);
  });

  it('кнопка «К отчёту» пишет то же имя, что уже стоит в манифесте', async () => {
    await mountWithBaseline();
    await createVariant('Вариант А');
    await createVariant('Вариант Б');
    const beforeReport = manifestLog[manifestLog.length - 1];

    await fireEvent.click(screen.getByRole('button', { name: /К отчёту/ }));
    await waitFor(() => {
      expect(manifestLog.length).toBeGreaterThan(3);
    }, { timeout: 4000 });

    expect(
      manifestLog[manifestLog.length - 1],
      'штатный путь не имеет права менять принятый план по сравнению с уходом мимо него',
    ).toBe(beforeReport);
    expect(manifestLog[manifestLog.length - 1]).toBe('Вариант А');
  });

  it('лучший по прогнозу без правдоподобного диапазона остаётся принятым, а экран молчит про ширину', async () => {
    SCENARIOS['Вариант А'] = { kpi: 20000, lo: null, hi: null };
    await mountWithBaseline();

    await createVariant('Вариант А');   // лучший по прогнозу, диапазона нет
    await createVariant('Вариант Б');   // хуже, диапазон широкий

    expect(
      manifestLog[manifestLog.length - 1],
      'отсутствие диапазона не исключает вариант из выбора принятого плана',
    ).toBe('Вариант А');

    const texts = screenInsights();
    expect(
      texts.some((t) => t.includes('У принятого плана «Вариант Б»')),
      'нет диапазона у принятого – правило обязано промолчать, а не назвать принятым другой план',
    ).toBe(false);
    expect(texts.some((t) => t.includes('У принятого плана «Вариант А»'))).toBe(false);
  });

  it('удаление принятого варианта переписывает манифест на оставшийся', async () => {
    await mountWithBaseline();
    await createVariant('Вариант А');
    await createVariant('Вариант Б');
    expect(manifestLog[manifestLog.length - 1]).toBe('Вариант А');

    await fireEvent.click(screen.getAllByRole('button', { name: 'Удалить вариант Вариант А' })[0]);
    await waitFor(() => {
      expect(get(planningLiveState).variants.some((v) => v.name === 'Вариант А')).toBe(false);
    }, { timeout: 4000 });
    await waitFor(() => {
      expect(
        manifestLog[manifestLog.length - 1],
        'манифест не имеет права называть принятым удалённый со шага вариант',
      ).toBe('Вариант Б');
    }, { timeout: 4000 });
  });

  it('без единого варианта принятым остаётся базовый план и экран говорит это словами', async () => {
    await mountWithBaseline();

    expect(manifestLog[manifestLog.length - 1]).toBe('Базовый план');
    const texts = screenInsights();
    expect(texts.some((t) => t.includes('План ещё не выбран – у базового плана'))).toBe(true);
  });
});
