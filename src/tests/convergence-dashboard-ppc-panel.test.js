/**
 * ConvergenceDashboard — Panel C (PPCScatter подключение, 2026-08-07).
 *
 * Осиротевший компонент PPCScatter (рассеяние факт/прогноз + остатки во времени)
 * подключён третьей панелью рядом с «R-hat по параметрам» и «Факт vs Прогноз».
 * Контракт: показывается ТОЛЬКО когда diagnostics.actual_vs_predicted есть (тот же
 * гейт, что у Panel B); честно отсутствует для старых проектов без этого поля и
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

describe('ConvergenceDashboard — Panel C «Разброс прогноза и остатки»', () => {
  it('actual_vs_predicted есть → панель C показана', () => {
    const { getByText } = render(ConvergenceDashboard, { props: { diagnostics: diagnosticsFixture() } });
    expect(getByText('Разброс прогноза и остатки')).toBeInTheDocument();
  });

  it('actual_vs_predicted отсутствует (старый проект) → панель C честно скрыта, без падения', () => {
    const { queryByText } = render(ConvergenceDashboard, {
      props: { diagnostics: diagnosticsFixture({ actual_vs_predicted: undefined }) },
    });
    expect(queryByText('Разброс прогноза и остатки')).not.toBeInTheDocument();
  });

  it('diagnostics=null → без падения, панель C отсутствует', () => {
    expect(() =>
      render(ConvergenceDashboard, { props: { diagnostics: null } })
    ).not.toThrow();
  });
});
