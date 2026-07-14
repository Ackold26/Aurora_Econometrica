/**
 * F-A1-18 (2026-07-06): текст «Главные сдвиги» генерируется из фактических
 * знаков дельт, а не хардкодированной фразы.
 *
 * Три сценария:
 *  - Есть и + и − → «Перекладка из X в Y» (называет каналы)
 *  - Только − (все снижаются) → «Масштабирование под плановый период»
 *  - Только + (всё растёт) → «Наращивание бюджета»
 *
 * Регрессионная проверка: строка «перенасыщенных каналов в недонасыщенные»
 * (хардкод) не должна присутствовать в выводе.
 */
import { describe, it, expect } from 'vitest';
import { optimizeInsights } from '../insights-rules.js';

/** Базовый ctx (dec не нужен для теста сдвигов, но функция его читает). */
const CTX_EMPTY = {
  dec: { channels: [] },
};

/** Строим минимальный optimizeData с заданными дельтами.
 * @param {any[]} channels
 * @returns {any}
 */
function buildOptData(channels) {
  return {
    expected_lift_pct: 5.0,
    total_budget: channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + c.optimal_spend, 0),
    channels,
  };
}

/** Собирает все тексты + tip'ы в одну строку.
 * @param {any[]} insights
 * @returns {string}
 */
function joinAll(insights) {
  return insights.map((/** @type {any} */ i) => `${i.text}\n${i.tip || ''}`).join('\n');
}

describe('F-A1-18: текст «Главные сдвиги» из фактических дельт', () => {
  it('есть и рост, и снижение → «Перекладка из» с упоминанием каналов-доноров', () => {
    const data = buildOptData([
      // снижаются (доноры)
      { name: 'TV', action: 'Reduce', current_spend: 1_000_000, optimal_spend: 700_000, mroi_current: 0.5 },
      { name: 'Radio', action: 'Reduce', current_spend: 500_000, optimal_spend: 300_000, mroi_current: 0.7 },
      // растёт (получатель)
      { name: 'Digital', action: 'Scale', current_spend: 500_000, optimal_spend: 900_000, mroi_current: 2.1 },
    ]);
    const insights = optimizeInsights(data, CTX_EMPTY);
    const text = joinAll(insights);

    expect(text).toMatch(/Перекладка из/);
    // Называет хотя бы один канал-донор (TV или Radio)
    expect(text).toMatch(/TV|Radio/);
    // Нет хардкода
    expect(text).not.toMatch(/перенасыщенных каналов в недонасыщенные/);
  });

  it('только снижения → «Масштабирование под плановый период»', () => {
    const data = buildOptData([
      { name: 'TV', action: 'Reduce', current_spend: 1_000_000, optimal_spend: 800_000, mroi_current: 0.8 },
      { name: 'Radio', action: 'Reduce', current_spend: 600_000, optimal_spend: 450_000, mroi_current: 0.9 },
      { name: 'Digital', action: 'Reduce', current_spend: 400_000, optimal_spend: 300_000, mroi_current: 0.6 },
    ]);
    const insights = optimizeInsights(data, CTX_EMPTY);
    const text = joinAll(insights);

    expect(text).toMatch(/Масштабирование под плановый период/);
    expect(text).not.toMatch(/перенасыщенных каналов в недонасыщенные/);
  });

  it('только рост → «Наращивание бюджета»', () => {
    const data = buildOptData([
      { name: 'Digital', action: 'Scale', current_spend: 500_000, optimal_spend: 800_000, mroi_current: 2.5 },
      { name: 'Social', action: 'Scale', current_spend: 300_000, optimal_spend: 500_000, mroi_current: 1.8 },
      { name: 'OLV', action: 'Scale', current_spend: 200_000, optimal_spend: 350_000, mroi_current: 1.5 },
    ]);
    const insights = optimizeInsights(data, CTX_EMPTY);
    const text = joinAll(insights);

    expect(text).toMatch(/Наращивание бюджета/);
    expect(text).not.toMatch(/перенасыщенных каналов в недонасыщенные/);
  });
});
