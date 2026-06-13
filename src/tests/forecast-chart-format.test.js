/**
 * forecast-chart-format.test.js — форматтеры тултипа/легенды MultiScenarioChart.
 * Доказывают логику без живого ECharts-hover (синтетику zrender не ловит).
 */
import { describe, it, expect } from 'vitest';
import {
  compactNum,
  fmtFull,
  buildForecastTooltip,
  forecastLegendLabel,
} from '../lib/forecast-chart-format.js';

const CTX = {
  baseline: { name: 'История (модель)' },
  visibleScenarios: [
    { name: 'A базовый', predictions: [300_000_000, 310_000_000, 320_000_000] },
    { name: 'B пик', predictions: [330_000_000, 360_000_000, 385_000_000] },
  ],
  allDates: ['2025-06-01', '2025-07-01', '2025-08-01', '2025-09-01'],
  cutoffIndex: 1, // история ≤ idx 1, прогноз > 1
  baselineColor: '#94a3b8',
  scenarioColors: ['#10b981', '#3b82f6'],
};

describe('compactNum / fmtFull', () => {
  it('compactNum: K/M/B', () => {
    expect(compactNum(385_000_000)).toBe('385M');
    expect(compactNum(1_210_000_000)).toBe('1.2B');
    expect(compactNum(2500)).toBe('3K');
  });
  it('fmtFull: разделители ru, нечисло → —', () => {
    expect(fmtFull(1817821375)).toMatch(/1\D817\D821\D375/);
    expect(fmtFull(NaN)).toBe('—');
  });
});

describe('buildForecastTooltip', () => {
  it('точка ИСТОРИИ: показывает baseline + метку «история»', () => {
    const params = [{ axisValue: '2025-06-01', seriesName: 'История (модель)', value: 250_000_000 }];
    const html = buildForecastTooltip(params, CTX);
    expect(html).toContain('2025-06-01');
    expect(html).toContain('история');
    expect(html).not.toContain('прогноз');
    expect(html).toContain('История (модель)');
    expect(html).toContain(CTX.baselineColor);
  });

  it('точка ПРОГНОЗА: показывает сценарии с ДИ 90% + метку «прогноз»', () => {
    const params = [
      { axisValue: '2025-08-01', seriesName: 'A базовый', value: 320_000_000 },
      { axisValue: '2025-08-01', seriesName: 'A базовый_ci_low', value: 300_000_000 },
      { axisValue: '2025-08-01', seriesName: 'A базовый_ci_high', value: 340_000_000 },
      { axisValue: '2025-08-01', seriesName: 'B пик', value: 385_000_000 },
    ];
    const html = buildForecastTooltip(params, CTX);
    expect(html).toContain('прогноз');
    expect(html).toContain('A базовый');
    expect(html).toContain('B пик');
    expect(html).toContain('ДИ'); // CI веер показан для A (low/high присутствуют)
    expect(html).toContain('300M');
    expect(html).toContain('340M');
    // helper-серии CI НЕ выводятся как отдельные строки
    expect(html).not.toContain('_ci_low');
    expect(html).not.toContain('_ci_high');
  });

  it('сценарий без band → строка есть, ДИ нет', () => {
    const params = [{ axisValue: '2025-08-01', seriesName: 'A базовый', value: 320_000_000 }];
    const html = buildForecastTooltip(params, CTX);
    expect(html).toContain('A базовый');
    expect(html).not.toContain('ДИ');
  });

  it('пустые/нечисловые значения → пустая строка (нет фантомных строк)', () => {
    expect(buildForecastTooltip([], CTX)).toBe('');
    const params = [{ axisValue: '2025-08-01', seriesName: 'A базовый', value: null }];
    expect(buildForecastTooltip(params, CTX)).toBe('');
  });

  it('не падает: одиночный объект вместо массива, baseline=null', () => {
    const single = { axisValue: '2025-08-01', seriesName: 'A базовый', value: 320_000_000 };
    expect(() => buildForecastTooltip(single, { ...CTX, baseline: null })).not.toThrow();
    expect(buildForecastTooltip(single, { ...CTX, baseline: null })).toContain('A базовый');
  });

  it('XSS: имя сценария (user-typed) экранируется, не исполняется в innerHTML', () => {
    const evil = '<img src=x onerror=alert(1)>';
    const ctx = { ...CTX, visibleScenarios: [{ name: evil, predictions: [1] }] };
    const params = [{ axisValue: '2025-08-01', seriesName: evil, value: 320_000_000 }];
    const html = buildForecastTooltip(params, ctx);
    expect(html).not.toContain('<img src=x onerror=alert(1)>'); // сырой тег НЕ просочился
    expect(html).toContain('&lt;img'); // экранирован
  });

  it('XSS: дата экранируется', () => {
    const params = [{ axisValue: '<svg/onload=alert(1)>', seriesName: 'A базовый', value: 1 }];
    const html = buildForecastTooltip(params, CTX);
    expect(html).not.toContain('<svg/onload');
    expect(html).toContain('&lt;svg');
  });
});

describe('forecastLegendLabel', () => {
  it('сценарий: добавляет endpoint-значение', () => {
    expect(forecastLegendLabel('B пик', CTX)).toBe('B пик  ·  385M');
  });
  it('baseline: без изменений', () => {
    expect(forecastLegendLabel('История (модель)', CTX)).toBe('История (модель)');
  });
  it('неизвестное имя / пустые predictions: как есть', () => {
    expect(forecastLegendLabel('Чужой', CTX)).toBe('Чужой');
    expect(forecastLegendLabel('X', { baseline: null, visibleScenarios: [{ name: 'X', predictions: [] }] })).toBe('X');
  });
});
