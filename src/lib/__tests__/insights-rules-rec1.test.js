/**
 * REC-1 (2026-06-02): unit_smell-каналы (артефактный ROI/mROAS из не-денежных
 * единиц) не должны попадать в рекомендации «наращивать» / «лучший по mROAS».
 * Корень: защитная пометка (секция 5 unit-smell) существовала, но светофор и
 * mROAS-лидеры её игнорировали → продукт советовал вкладывать в TRP с ROI 12186×.
 */
import { describe, it, expect } from 'vitest';
import { optimizeInsights } from '../insights-rules.js';

/** Кагоцел-подобный вход: TRPs — артефактный высокий mROAS + unit_smell. */
function buildData() {
  return {
    expected_lift_pct: 3.0,
    total_budget: 1_000_000,
    channels: [
      // unit_smell-канал: огромный mROAS (артефакт), action Scale
      { name: 'TRPs', mroi_current: 9550, action: 'Scale', current_spend: 100, optimal_spend: 200 },
      // нормальные каналы
      { name: 'Social', mroi_current: 2.5, action: 'Scale', current_spend: 1000, optimal_spend: 1300 },
      { name: 'OLV', mroi_current: 1.1, action: 'Hold', current_spend: 2000, optimal_spend: 2000 },
    ],
  };
}

function buildCtx() {
  return {
    dec: {
      // REC-1-GAP (2026-06-03): фикстура использует РЕАЛЬНЫЙ verdict движка
      // (`engines/decomposer.py:121` = «ROI завышен (не рубли?)») + флаг unit_smell:true.
      // Старая фикстура подавала «подозрительно высокий ROI» — строку, которую движок
      // НЕ эмитит → тест был зелёным, а фильтр /подозрительно/ мёртв на реальных данных.
      channels: [
        { name: 'TRPs', verdict: 'ROI завышен (не рубли?) (широкий ROI-интервал)', unit_smell: true, roi: 12186, spend: 100, contribution: 1_200_000 },
        { name: 'Social', verdict: 'Высокоэффективен (широкий ROI-интервал)', unit_smell: false, roi: 26, spend: 1000, contribution: 26_000 },
        { name: 'OLV', verdict: '', unit_smell: false, roi: 15, spend: 2000, contribution: 30_000 },
      ],
    },
  };
}

/** @param {any[]} insights */
function joinText(insights) {
  return insights.map((/** @type {any} */ i) => `${i.text}\n${i.tip || ''}`).join('\n');
}

describe('REC-1 unit_smell не рекомендуется наращивать', () => {
  it('mROAS-лидер «лучший» не должен быть unit_smell-каналом (TRPs)', () => {
    const insights = optimizeInsights(buildData(), buildCtx());
    const leader = insights.find((/** @type {any} */ i) => /Предельная отдача/.test(i.text));
    expect(leader).toBeTruthy();
    // «лучший» = Social (2.5), не TRPs (9550 артефакт)
    expect(leader?.text).toMatch(/лучший Social/);
    expect(leader?.text).not.toMatch(/лучший TRPs/);
  });

  it('TRPs в светофоре помечен как ненадёжный (не молча в зоне роста)', () => {
    const insights = optimizeInsights(buildData(), buildCtx());
    const text = joinText(insights);
    // unit_smell-предупреждение присутствует (защитная пометка сохранена)
    expect(text).toMatch(/подозрительно высоким ROI/);
    // TRPs в строке «Недонасыщены» аннотирован
    expect(text).toMatch(/TRPs.*не-денежные единицы/);
  });

  it('счётчик «зона роста — есть куда вкладывать» не раздут unit_smell-каналом', () => {
    const insights = optimizeInsights(buildData(), buildCtx());
    const growth = insights.find((/** @type {any} */ i) => /в зоне роста - есть куда вкладывать/.test(i.text));
    if (growth) {
      // effectiveClean = только Social (TRPs исключён) → «1 канал», не «2 канала»
      expect(growth.text).toMatch(/^1 канал/);
    }
  });
});
