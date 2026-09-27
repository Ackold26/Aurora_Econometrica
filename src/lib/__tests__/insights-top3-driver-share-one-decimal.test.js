/**
 * decomposeInsights, блок «Топ-3 драйвера медиа-вклада» (insights-rules.js:~1692).
 *
 * До правки заголовок блока форматировал сумму долей топ-3 через `top3Sum.toFixed(0)`
 * (целое число) вместо `formatChannelSharePct(top3Sum)` (десятая доля) — тот же класс
 * расхождения формата, что `insights-channel-share-one-decimal.test.js` закрыл для доли
 * главного драйвера (INV-50: число на экране равно расчёту, единый формат по программе).
 *
 * Фикстура подобрана так, чтобы топ-3 (сортировка по contribution_pct desc) давали сумму
 * X.Y5-подобного вида, где `toFixed(0)` и `formatChannelSharePct`(`toFixed(1)`) дают РАЗНЫЕ
 * строки: 50.14 + 35.34 + 12.46 = 97.94 → toFixed(0) = "98%", formatChannelSharePct = "97.9%".
 * Четвёртый канал (2.06) вне топ-3 — суммарно доли дают ровно 100%, реалистичная картина.
 */
import { describe, it, expect } from 'vitest';
import { decomposeInsights } from '../insights-rules.js';

/** @returns {any[]} */
function channelsFixture() {
  return [
    { name: 'Канал A', spend: 1_000_000, contribution: 5014, contribution_pct: 50.14, roi: 1.5 },
    { name: 'Канал B', spend: 700_000, contribution: 3534, contribution_pct: 35.34, roi: 1.3 },
    { name: 'Канал C', spend: 50_000, contribution: 206, contribution_pct: 2.06, roi: 0.9 },
    { name: 'Канал D', spend: 300_000, contribution: 1246, contribution_pct: 12.46, roi: 1.1 },
  ];
}

describe('decomposeInsights — доля топ-3 драйверов медиа-вклада с одной десятой', () => {
  it('заголовок блока показывает "97.9%", не "98%"', () => {
    const insights = decomposeInsights({ baseline_pct: 40, channels: channelsFixture() });
    const top3Insight = insights.find((/** @type {any} */ i) => i.text.includes('Топ-3 драйверов'));
    expect(top3Insight).toBeTruthy();
    const text = top3Insight?.text ?? '';
    expect(text).toContain('97.9%');
    expect(text).not.toContain('98%');
  });
});
