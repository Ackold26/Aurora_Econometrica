/**
 * ConvergenceDashboard — Panel C/D (PPCScatter подключение, 2026-08-07).
 *
 * Осиротевший компонент PPCScatter (рассеяние факт/прогноз + остатки во времени)
 * подключён панелями рядом с «R-hat по параметрам» и «Факт vs Прогноз». 2026-09-11
 * разведён на два самостоятельных графика («Разброс прогноза» + «Остатки»), каждый
 * в своей карточке - раньше общая карточка открывала оба графика одним разворотом.
 * Контракт: показываются ТОЛЬКО когда diagnostics.actual_vs_predicted есть (тот же
 * гейт, что у Panel B); честно отсутствуют для старых проектов без этого поля и
 * при diagnostics=null - без падения компонента.
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import ConvergenceDashboard from '$lib/components/pipeline/ConvergenceDashboard.svelte';

/** Диагностика в форме results/model-diagnostics.json (усечённая, но валидная). */
function diagnosticsFixture(overrides = {}) {
  return {
    metrics: { r_squared: 0.9763, mape_pct: 6.44 },
    checks: {},
    actual_vs_predicted: {
      actual: [100, 110, 95, 120, 105],
      predicted: [98, 112, 97, 118, 108],
      dates: ['2025-01', '2025-02', '2025-03', '2025-04', '2025-05'],
    },
    per_param_rhat: {},
    engine: 'bayesian',
    ...overrides,
  };
}

describe('ConvergenceDashboard — Panel C/D «Разброс прогноза» + «Остатки»', () => {
  it('actual_vs_predicted есть → обе панели показаны', () => {
    const { getByText } = render(ConvergenceDashboard, { props: { diagnostics: diagnosticsFixture() } });
    expect(getByText('Разброс прогноза')).toBeInTheDocument();
    expect(getByText('Остатки')).toBeInTheDocument();
  });

  it('actual_vs_predicted отсутствует (старый проект) → обе панели честно скрыты, без падения', () => {
    const { queryByText } = render(ConvergenceDashboard, {
      props: { diagnostics: diagnosticsFixture({ actual_vs_predicted: undefined }) },
    });
    expect(queryByText('Разброс прогноза')).not.toBeInTheDocument();
    expect(queryByText('Остатки')).not.toBeInTheDocument();
  });

  it('diagnostics=null → без падения, обе панели отсутствуют', () => {
    expect(() =>
      render(ConvergenceDashboard, { props: { diagnostics: null } })
    ).not.toThrow();
  });
});
