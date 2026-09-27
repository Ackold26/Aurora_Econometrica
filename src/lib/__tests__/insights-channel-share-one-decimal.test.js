/**
 * Аудит s50 (M-1): доля канала в медиа-вкладе на панели выводов показывала
 * целое («88%») через `contribution_pct.toFixed(0)`, а столбец «Доля» шага
 * «Декомпозиция» уже показывал одну десятую («87.5») — расхождение на
 * соседних экранах одного продукта (INV-50: число на экране равно расчёту).
 *
 * Правка: decomposeInsights/reportInsights переведены на общий помощник
 * format-numbers.js:formatChannelSharePct (тот же источник форматирования,
 * что DecomposeStep.svelte и ReportStep.svelte).
 *
 * Фикстура — те же числа, что test_channel_share_single_source.py:_dec_875
 * (87.5 / 7.5 / 5.0), для единой картины движок/фронт на одном примере.
 */
import { describe, it, expect } from 'vitest';
import { decomposeInsights, reportInsights } from '../insights-rules.js';

/** @returns {any[]} */
function channelsFixture() {
  return [
    { name: 'Канал A', spend: 1_000_000, contribution: 875, contribution_pct: 87.5, roi: 1.5 },
    { name: 'Канал B', spend: 200_000, contribution: 75, contribution_pct: 7.5, roi: 1.2 },
    { name: 'Канал C', spend: 100_000, contribution: 50, contribution_pct: 5.0, roi: 0.8 },
  ];
}

/** Собирает text+tip всех инсайтов в одну строку (см. insights-rules-shift-description.test.js).
 * @param {any[]} insights
 * @returns {string}
 */
function joinAll(insights) {
  return insights.map((/** @type {any} */ i) => `${i.text}\n${i.tip || ''}`).join('\n');
}

describe('decomposeInsights — доля канала в медиа-вкладе с одной десятой (аудит s50 M-1)', () => {
  it('заголовок, топ-3 и предупреждение о концентрации показывают 87.5%, не 88%', () => {
    const insights = decomposeInsights({ baseline_pct: 40, channels: channelsFixture() });
    const all = joinAll(insights);
    expect(all).toContain('87.5%');
    expect(all).not.toContain('88%');
  });
});

describe('reportInsights — доля главного драйвера с одной десятой (аудит s50 M-1)', () => {
  it('этап «Декомпозиция» показывает 87.5%, не 88%', () => {
    const insights = reportInsights({
      mod: { diagnostics: { mqs: { score: 82, tier: 'good' }, metrics: { r_squared: 0.9, mape_pct: 5.0, ratio: 5.0 } } },
      dec: { baseline_pct: 40, channels: channelsFixture() },
      opt: { expected_lift_pct: 3.0, total_budget_money: 1_000_000 },
    });
    const all = joinAll(insights);
    expect(all).toContain('87.5%');
    expect(all).not.toContain('88%');
  });
});
