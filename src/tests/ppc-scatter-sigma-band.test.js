/**
 * PPCScatter — полоса «среднее ± 2σ» на графике остатков (сторож на класс дефекта,
 * найденный внешним аудитом 2026-08-08).
 *
 * Слои с общим `stack: 'sigma_band'` складываются: невидимая опора + заливка.
 * Инвариант: опора = нижняя граница (mean − 2σ), опора + заливка = верхняя граница
 * (mean + 2σ) — то есть полоса ОХВАТЫВАЕТ остатки. Дефект был в том, что опорой стояла
 * ВЕРХНЯЯ граница (bandHigh) — тогда полоса рисовалась от mean+2σ до mean+6σ, целиком
 * над точками остатков, а не вокруг них.
 *
 * ECharts option собирается внутри компонента и наружу не отдаётся — перехватываем его
 * через мок EChartBase (приём как в channel-timeline-click.test.js: копим каждый
 * применённый option, дальше сверяем ряды).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import { flushSync } from 'svelte';

vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: MockEChartBase } = await import('./__mocks__/MockEChartBase.svelte');
  return { default: MockEChartBase };
});

import PPCScatter from '$lib/components/pipeline/PPCScatter.svelte';
import { __getAppliedOptions, __resetAppliedOptions } from './__mocks__/MockEChartBase.svelte';

/**
 * Остатки [-2,-1,0,1,2] - среднее и σ считаются в уме: mean=0,
 * variance = (4+1+0+1+4)/5 = 2, σ = √2. actual/predicted подобраны так,
 * чтобы actual-predicted дал ровно эти остатки.
 */
function ppcDataFixture() {
  return {
    actual: [-2, -1, 0, 1, 2],
    predicted: [0, 0, 0, 0, 0],
    r2: 0.9,
  };
}

/** Находит option графика остатков среди всех применённых моку EChartBase - по
 *  уникальному для этого графика имени опорного слоя, а не по порядку монтирования. */
function findResidualsOption() {
  const opts = __getAppliedOptions();
  return opts.find((o) => (o.series ?? []).some((s) => s.name === 'mean-2σ'));
}

describe('PPCScatter — полоса mean±2σ охватывает остатки, не висит над ними', () => {
  beforeEach(() => {
    __resetAppliedOptions();
  });

  it('опора = mean-2σ, опора+заливка = mean+2σ (полоса охватывает диапазон остатков)', () => {
    render(PPCScatter, { props: { ppcData: ppcDataFixture() } });
    flushSync();

    const residualsOption = findResidualsOption();
    expect(residualsOption, 'график остатков не найден среди применённых option').toBeTruthy();

    const support = residualsOption.series.find((s) => s.name === 'mean-2σ');
    const fill = residualsOption.series.find((s) => s.name === 'mean±2σ');
    expect(support, 'опорный слой mean-2σ отсутствует').toBeTruthy();
    expect(fill, 'слой заливки mean±2σ отсутствует').toBeTruthy();

    const mean = 0;
    const std = Math.SQRT2; // √2
    const expectedLow = mean - 2 * std;
    const expectedHigh = mean + 2 * std;

    // Опора обязана стоять на НИЖНЕЙ границе.
    for (const v of support.data) {
      expect(v).toBeCloseTo(expectedLow, 6);
    }
    // Опора + заливка (ECharts stack складывает слои) обязаны давать ВЕРХНЮЮ границу.
    support.data.forEach((v, i) => {
      expect(v + fill.data[i]).toBeCloseTo(expectedHigh, 6);
    });

    // Полоса охватывает сами остатки [-2..2], не висит над ними.
    for (const residual of [-2, -1, 0, 1, 2]) {
      expect(residual).toBeGreaterThanOrEqual(expectedLow);
      expect(residual).toBeLessThanOrEqual(expectedHigh);
    }
  });
});
