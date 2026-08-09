/**
 * StepSummary traffic-dot guard test.
 *
 * Майский аудит доступности M2: "no emoji for status" — светофор диагностики
 * (MCMC / Backtest / PPC / Sensitivity) обязан рисоваться CSS-точкой, не
 * эмодзи 🟢🟡🔴. Статус остаётся читаемым без цвета (screen-reader текст),
 * сама точка декоративная (aria-hidden).
 *
 * Сторож: краснеет, если эмодзи-светофор вернётся в trafficDot() или в
 * разметку. Проверено мутацией (см. отчёт задачи "эмодзи").
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import StepSummary from '$lib/components/pipeline/wizard/StepSummary.svelte';

/** Диагностика со всеми тремя статусами green + sensitivity (все 4 точки рендерятся). */
function makeDiagnostics() {
  return {
    mcmcConvergence: { rHatMax: 1.02, essMin: 500 },      // green
    backtest: { mape: 8, r2: 0.9, rmse: null },           // green
    ppc: { r2: 0.9, hasBias: false },                     // green
    sensitivity: [{ param: 'TV-adstock', deltaPct: 15 }], // always yellow
  };
}

function makeSummary() {
  return {
    scenarioLabel: 'Оптимизация медиа-бюджета',
    goalDescription: 'Распределить плановый бюджет 50 млн ₽ на 12 месяцев',
    channels: ['TV', 'Digital'],
    modeLabel: 'ROI режим (все каналы в ₽)',
    kpiLabel: 'продажи в упаковках',
    valuePerUnit: null,
    taskTypeLabel: 'Оптимизация бюджета',
    externalFactors: [],
    softRecommendations: [],
  };
}

function renderStepSummary() {
  return render(StepSummary, {
    props: {
      summary: makeSummary(),
      diagnostics: makeDiagnostics(),
      onRun: vi.fn(),
      onEditExpert: vi.fn(),
    },
  });
}

describe('StepSummary - traffic-dot (M2: no emoji for status)', () => {
  it('не содержит эмодзи-светофор 🟢🟡🔴 в отрисованной разметке', () => {
    const { container } = renderStepSummary();
    expect(container.innerHTML).not.toMatch(/[🟢🟡🔴]/u);
  });

  it('точка статуса присутствует как CSS-элемент .traffic-dot с классом статуса, а не текстовым эмодзи', () => {
    const { container } = renderStepSummary();
    const dots = container.querySelectorAll('.traffic-dot');
    // MCMC + Backtest + PPC + Sensitivity = 4 точки при полной диагностике.
    expect(dots.length).toBe(4);
    for (const dot of dots) {
      // Сама точка декоративна - пустая, без текстового содержимого (не эмодзи-глиф).
      expect(dot.textContent?.trim()).toBe('');
      // Цвет статуса задаётся модификатором класса, не inline-эмодзи.
      expect(dot.className).toMatch(/dot-(green|yellow|red)/);
    }
  });

  it('точка декоративна (aria-hidden), статус остаётся читаемым для скринридера рядом с ней', () => {
    const { container } = renderStepSummary();
    const dots = container.querySelectorAll('.traffic-dot');
    for (const dot of dots) {
      expect(dot.getAttribute('aria-hidden')).toBe('true');
    }
    // MCMC-точка зелёная (rHat/ESS хорошие) - рядом должен быть читаемый статус 'ok'.
    const mcmcDot = container.querySelector('.traffic-dot.dot-green');
    expect(mcmcDot).toBeInTheDocument();
    expect(container.textContent).toContain('MCMC: ok');
  });
});
