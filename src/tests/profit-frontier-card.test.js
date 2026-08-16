/**
 * 2026-08-16: ProfitFrontierCard — «сколько вообще тратить» (профит-фронтир).
 *
 * Контракт: Projects/FRONTIER_DESIGN_2026-08-16.md. Три исхода максимума,
 * число максимума показывается ТОЛЬКО когда maximum.reportable === true,
 * интервал на положение максимума — либо числа, либо честное «недоступен»
 * (не ноль, не тишина), подпись периода обязательна у каждого набора чисел.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { activeProjectId, kpiType, kpiKind, valuePerCountUnit, grossMargin, unitCosts } from '$lib/project-state.js';
import ProfitFrontierCard from '$lib/components/pipeline/ProfitFrontierCard.svelte';

/** Минимальная кривая (3 точки) для сборки графика без ошибок рендера. */
function curveFixture() {
  return [
    { index: 0, multiplier: 0.2, budget: 52_000_000, sales_total: 9_262_000_000, sales_from_media: 409_688_747, profit: -100, is_current: false, basis: 'total_over_training_period', extrapolation_severity: 0 },
    { index: 1, multiplier: 1.0, budget: 260_183_663, sales_total: 11_107_624_040, sales_from_media: 2_255_312_787, profit: 442_200_000, is_current: true, basis: 'total_over_training_period', extrapolation_severity: 0 },
    { index: 2, multiplier: 3.0, budget: 780_600_000, sales_total: 12_178_000_000, sales_from_media: 3_325_688_747, profit: 200_000_000, is_current: false, basis: 'total_over_training_period', extrapolation_severity: 2 },
  ];
}

/** Базовый успешный ответ (interior_observed, reportable, интервал доступен). */
function okFixture(overrides = {}) {
  return {
    status: 'ok',
    period: { basis: 'total_over_training_period', n_periods: 31, granularity: 'M', granularity_label_ru: 'по месяцам', note: 'Бюджет и продажи – суммарные за весь период обучения (31 период, по месяцам), не за один месяц.' },
    economics: { mode: 'monetary_margin', unit_value: 0.3, marginal_threshold: 3.333, kpi_type: 'sales', kpi_kind: 'monetary', source: { unit_value: 'request' } },
    grid: { n_points: 3, lo_multiplier: 0.2, hi_multiplier: 3.0, step: 100_000_000, current_index: 1 },
    current: { budget: 260_183_663, sales_total: 11_107_624_040, profit: 442_200_000, basis: 'total_over_training_period' },
    // F-16 (fix-frontier, 2026-08-16): baseline_sales_total → блок с basis/note,
    // как остальные группы чисел контракта.
    baseline_sales: {
      total: 8_852_311_253, basis: 'total_over_training_period',
      note: 'Продажи без рекламы – суммарно за весь период обучения, не за один период.',
    },
    curve: curveFixture(),
    observed_frontier: { available: true, index: 1, budget: 260_183_663, multiplier: 1.0, profit: 442_200_000, basis: 'total_over_training_period', at_grid_ceiling: false, limited_by: 'data' },
    maximum: {
      at_grid_floor: false, at_grid_ceiling: false, at_observed_frontier: false, basis: 'total_over_training_period',
      outcome: 'interior_observed', reportable: true, index: 1, budget: 355_584_340.0186, multiplier: 1.4, profit: 442_200_000,
      sales_total: 11_500_000_000, severity: 0, grid_step: 100_000_000,
      profit_at_current: 400_000_000, profit_gain_vs_current: 42_200_000,
      // F-17: budget_display - округлённое до разрешения сетки число для экрана,
      // budget - точное техническое поле (карточка его больше не печатает).
      budget_display: 356_000_000, display_resolution: 30_000_000,
      display_note: 'Число округлено до разряда, соотнесённого с шагом расчётной сетки.',
      message: 'Максимум прибыли лежит внутри наблюдавшегося диапазона – около 356 000 000 ₽ суммарно за период обучения. Число округлено: расчёт идёт по сетке с шагом около 30 000 000 ₽, точнее этого шага положение максимума не определяется.',
    },
    posterior_interval: {
      available: true, hdi_prob: 0.9, low: 143_100_000, high: 416_300_000, mean: 300_000_000, method: 'hdi',
      n_samples: 200, share_at_grid_floor: 0, share_at_grid_ceiling: 0, share_beyond_observed: 0.025,
      // F-12 (fix-frontier): интервал целиком внутри сетки - вероятностный, без оговорки.
      truncated_by_grid: false, truncated_side: null, grid_censored: false, is_probabilistic: true,
      basis: 'total_over_training_period', note: 'Интервал отражает неуверенность модели в параметрах, а не разброс будущего факта.',
    },
    marginal_return_method: 'central_difference_1pct',
    allocation_mode: 'proportional',
    allocation_note: 'Расчёт масштабирует текущее распределение бюджета между каналами.',
    ...overrides,
  };
}

function mockInvoke({ frontier = okFixture(), projectUpdateOk = true } = {}) {
  vi.mocked(invoke).mockImplementation(async (cmd, args) => {
    if (cmd === 'project_get_dir') return 'C:/fake/project';
    if (cmd === 'econ_profit_frontier') {
      if (frontier instanceof Error) throw frontier;
      return typeof frontier === 'function' ? frontier(args) : frontier;
    }
    if (cmd === 'project_update') {
      if (!projectUpdateOk) throw new Error('persist failed');
      return { id: 'p-test', gross_margin: /** @type {any} */ (args)?.updates?.gross_margin };
    }
    return null;
  });
}

// 🔴 Без явной очистки разметка предыдущего случая остаётся в документе, и
// проверки вида «числа НЕТ в разметке» находят элемент от прошлого рендера.
// В одиночном прогоне файла это не видно, в полном — падение (16.08).
afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  activeProjectId.set('p-test');
  kpiType.set('sales');
  kpiKind.set('monetary');
  valuePerCountUnit.set(null);
  grossMargin.set(0.3);
  unitCosts.set({});
});

describe('ProfitFrontierCard — три исхода максимума', () => {
  it('interior_observed → число максимума показано, подпись периода на месте', async () => {
    mockInvoke({ frontier: okFixture() });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByTestId('frontier-outcome')).toHaveTextContent('Максимум прибыли лежит внутри наблюдавшегося диапазона');
    });
    expect(screen.getByTestId('frontier-maximum-budget')).toHaveTextContent('356');
    // F-17: печатаем округлённое display-поле, не точное техническое (псевдоточность).
    expect(screen.getByTestId('frontier-maximum-budget')).not.toHaveTextContent('355 584 340');
    expect(screen.getByTestId('frontier-period')).toHaveTextContent('31 период');
    expect(screen.getByTestId('frontier-period')).toHaveTextContent('не за один месяц');
  });

  it('beyond_observed (limited_by=data) → reportable=false, числа максимума НЕТ в разметке', async () => {
    const fx = okFixture({
      maximum: {
        at_grid_floor: false, at_grid_ceiling: true, at_observed_frontier: false, basis: 'total_over_training_period',
        outcome: 'beyond_observed', reportable: false, limited_by: 'data', still_profitable_within_data: true, severity_at_grid_argmax: 2,
        message: 'В пределах ваших данных увеличение бюджета остаётся выгодным: прибыль растёт до самой границы наблюдавшихся трат (260 183 663 ₽ суммарно за период обучения). Где проходит потолок, эти данные не показывают.',
      },
    });
    mockInvoke({ frontier: fx });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByTestId('frontier-outcome')).toHaveTextContent('Где проходит потолок, эти данные не показывают');
    });
    expect(screen.queryByTestId('frontier-maximum-budget')).not.toBeInTheDocument();
    expect(screen.getByTestId('frontier-outcome').classList.contains('outcome-info')).toBe(true);
  });

  it('at_grid_ceiling (F-09, limited_by=grid) → отдельный исход, не путается с beyond_observed, чисел нет', async () => {
    const fx = okFixture({
      maximum: {
        at_grid_floor: false, at_grid_ceiling: true, at_observed_frontier: false, basis: 'total_over_training_period',
        outcome: 'at_grid_ceiling', reportable: false, limited_by: 'grid', still_profitable_within_data: true,
        grid_ceiling_budget: 780_600_000, grid_ceiling_multiplier: 3.0,
        message: 'Прибыль растёт до верхней границы расчёта – 780 600 000 ₽ суммарно за период обучения, это 3× текущего бюджета. Выше расчёт не заходил, поэтому точку максимума мы не называем: она лежит за пределами рассмотренного диапазона. Ваши данные её не ограничивают – в пределах расчёта выхода за наблюдавшиеся траты не было.',
      },
    });
    mockInvoke({ frontier: fx });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByTestId('frontier-outcome')).toHaveTextContent('Ваши данные её не ограничивают');
    });
    // Честность: текст НЕ должен утверждать, что это граница ДАННЫХ (это граница сетки).
    expect(screen.getByTestId('frontier-outcome')).not.toHaveTextContent('границы наблюдавшихся трат');
    expect(screen.queryByTestId('frontier-maximum-budget')).not.toBeInTheDocument();
    expect(screen.getByTestId('frontier-outcome').classList.contains('outcome-info')).toBe(true);
  });

  it('below_current → максимум ниже текущего, число потери показано (reportable=true)', async () => {
    const fx = okFixture({
      maximum: {
        at_grid_floor: false, at_grid_ceiling: false, at_observed_frontier: false, basis: 'total_over_training_period',
        outcome: 'below_current', reportable: true, index: 0, budget: 149_999_998.7, multiplier: 0.6, profit: 500_000_000,
        sales_total: 10_800_000_000, severity: 0, grid_step: 100_000_000,
        profit_at_current: 442_200_000, profit_lost_at_current: 57_800_000,
        budget_display: 150_000_000, display_resolution: 30_000_000,
        display_note: 'Число округлено до разряда, соотнесённого с шагом расчётной сетки.',
        message: 'Вы уже за точкой максимальной прибыли: она примерно при 150 000 000 ₽ суммарно за период обучения. На текущем бюджете теряется около 57 800 000 ₽ прибыли за тот же период.',
      },
    });
    mockInvoke({ frontier: fx });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByTestId('frontier-outcome')).toHaveTextContent('Вы уже за точкой максимальной прибыли');
    });
    expect(screen.getByTestId('frontier-maximum-budget')).toHaveTextContent('150');
  });

  it('at_observed_frontier=true → флаг границы виден в разметке', async () => {
    const fx = okFixture({
      maximum: { ...okFixture().maximum, at_observed_frontier: true },
    });
    mockInvoke({ frontier: fx });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByTestId('frontier-at-boundary-flag')).toBeInTheDocument();
    });
  });
});

describe('ProfitFrontierCard — интервал на положение максимума', () => {
  it('интервал недоступен (МНК/малые данные) → честное сообщение, не ноль и не тишина', async () => {
    const fx = okFixture({
      posterior_interval: { available: false, reason: 'no_posterior_samples', message: 'Модель обучена без байесовского вывода – апостериорных выборок нет. Интервал на положение максимума – нет.' },
    });
    mockInvoke({ frontier: fx });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByTestId('posterior-interval')).toHaveTextContent('апостериорных выборок нет');
    });
    expect(screen.getByTestId('posterior-interval')).not.toHaveTextContent('0 ₽');
  });

  it('интервал доступен → диапазон показан числами, подпись «90%»', async () => {
    mockInvoke({ frontier: okFixture() });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByTestId('posterior-interval')).toHaveTextContent('143');
    });
    expect(screen.getByTestId('posterior-interval')).toHaveTextContent('416');
    expect(screen.getByTestId('posterior-interval')).toHaveTextContent('90%');
    expect(screen.queryByTestId('posterior-interval-caveat')).not.toBeInTheDocument();
  });

  it('F-12: интервал усечён сеткой (is_probabilistic=false) → без подписи «90%», оговорка показана', async () => {
    const fx = okFixture({
      posterior_interval: {
        available: true, hdi_prob: 0.9, low: 52_000_000, high: 780_600_000, mean: 400_000_000, method: 'hdi',
        n_samples: 200, share_at_grid_floor: 0, share_at_grid_ceiling: 0.105, share_beyond_observed: 0.67,
        truncated_by_grid: true, truncated_side: 'high', grid_censored: true, is_probabilistic: false,
        basis: 'total_over_training_period',
        caveat: 'Диапазон ограничен рамками расчёта, а не только моделью: сверху диапазон упирается в верхнюю границу расчёта (780 600 000 ₽), за неё расчёт не заходил; у 11% выборок максимум лежит за этой границей. Поэтому читать его как «правдоподобный диапазон с вероятностью 90%» нельзя – со стороны упора это граница нашего расчёта.',
      },
    });
    mockInvoke({ frontier: fx });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByTestId('posterior-interval-caveat')).toBeInTheDocument();
    });
    // Подпись диапазона (не текст оговорки от движка, который сам объясняет
    // «нельзя читать как 90%») не должна утверждать «90%» как факт.
    expect(screen.getByTestId('posterior-interval')).toHaveTextContent('ограничен расчётной сеткой');
    expect(screen.getByTestId('posterior-interval')).not.toHaveTextContent('Правдоподобный диапазон положения максимума (90%)');
    expect(screen.getByTestId('posterior-interval-caveat')).toHaveTextContent('граница нашего расчёта');
  });

  it('F-01: maximum.reportable=false → интервал приходит withheld, без чисел low/high/mean', async () => {
    const fx = okFixture({
      maximum: {
        at_grid_floor: false, at_grid_ceiling: true, at_observed_frontier: false, basis: 'total_over_training_period',
        outcome: 'beyond_observed', reportable: false, limited_by: 'data', still_profitable_within_data: true,
        message: 'В пределах ваших данных увеличение бюджета остаётся выгодным – точку максимума мы не называем.',
      },
      posterior_interval: {
        available: false, status: 'withheld', reason: 'maximum_not_reportable', withheld_for_outcome: 'beyond_observed',
        basis: 'total_over_training_period', n_samples: 200, share_beyond_observed: 0.67,
        message: 'Положение максимума по этим данным мы не называем (причина – в пояснении к максимуму), поэтому не выдаём и правдоподобный диапазон его положения: его границы указывали бы на ту же точку. По апостериорным выборкам максимум оказывается за границей наблюдавшихся трат у 67% выборок.',
      },
    });
    mockInvoke({ frontier: fx });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByTestId('posterior-interval')).toHaveTextContent('его границы указывали бы на ту же точку');
    });
    expect(screen.getByTestId('posterior-interval')).not.toHaveTextContent('90%');
  });
});

describe('ProfitFrontierCard — отказ без экономики', () => {
  it('monetary_margin_missing → поле ввода маржи, подтверждение персистит и пересчитывает', async () => {
    let calls = 0;
    mockInvoke({
      frontier: () => {
        calls += 1;
        if (calls === 1) {
          return { status: 'economics_required', error_code: 'ECONOMICS_REQUIRED', reason: 'monetary_margin_missing', message: 'Чтобы посчитать прибыль, нужна валовая маржа.', kpi_type: 'sales', kpi_kind: 'monetary' };
        }
        return okFixture();
      },
    });
    grossMargin.set(null);
    render(ProfitFrontierCard);
    const input = await screen.findByLabelText('Валовая маржа, %');
    await fireEvent.input(input, { target: { value: '30' } });
    const btn = screen.getByRole('button', { name: /Подтвердить/ });
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByTestId('frontier-outcome')).toBeInTheDocument();
    });
    const updateCall = vi.mocked(invoke).mock.calls.find(([cmd]) => cmd === 'project_update');
    expect(updateCall?.[1]?.updates?.gross_margin).toBeCloseTo(0.3);
  });

  it('count_value_missing → честное сообщение отказа, без карточки-графика', async () => {
    kpiKind.set('count');
    mockInvoke({
      frontier: { status: 'economics_required', error_code: 'ECONOMICS_REQUIRED', reason: 'count_value_missing', message: 'Чтобы посчитать прибыль, нужна ценность одной единицы.', kpi_type: 'sales_packs', kpi_kind: 'count' },
    });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByText(/ценность одной единицы/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId('frontier-outcome')).not.toBeInTheDocument();
  });
});

describe('ProfitFrontierCard — сбой', () => {
  it('MODEL_NOT_FOUND → честная ошибка, без графика', async () => {
    mockInvoke({ frontier: { status: 'error', error_code: 'MODEL_NOT_FOUND', message: 'Модель не найдена. Сначала обучите модель.' } });
    render(ProfitFrontierCard);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Модель не найдена');
    });
  });
});
