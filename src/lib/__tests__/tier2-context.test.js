/**
 * Tier 2 контекст + промпт (Фаза 1). Тестируется на реальной фикстуре
 * декомпозиции Кагоцел + синтетике для optimize/model. Смыкается с
 * insights-grounding (INV-50 страж): честный ответ из фактов контекста
 * не должен флагаться.
 */
import { describe, it, expect } from 'vitest';
import {
  buildTier2Context,
  buildTier2Prompt,
  TIER2_SYSTEM_RULES,
  STEP,
} from '../tier2-context.js';
import { findUngroundedNumbers } from '../insights-grounding.js';
import decomposition from './fixtures/kagocel-load1/decomposition.json';

describe('buildTier2Context — декомпозиция (реальная фикстура)', () => {
  const ctx = buildTier2Context({ step: STEP.DECOMPOSE, dec: decomposition, tier1Insights: [] });

  it('сводка содержит ключевые факты, но не сырой мегаджейсон', () => {
    expect(ctx.facts.baseline_pct).toBe(80.6);
    expect(Array.isArray(ctx.facts.channels)).toBe(true);
    expect(ctx.facts.channels.length).toBe(7);
    // time_series / signed_factor_contributions НЕ должны попадать в сводку
    expect(ctx.facts).not.toHaveProperty('time_series');
    expect(ctx.facts).not.toHaveProperty('signed_factor_contributions');
  });

  it('канал несёт roi + интервал + verdict', () => {
    const statyi = ctx.facts.channels.find(/** @param {any} c */ (c) => c.name === 'Статьи');
    expect(statyi.roi).toBe(77.49);
    expect(statyi.roi_ci_low).toBeDefined();
    expect(statyi.roi_ci_high).toBeDefined();
    expect(statyi.verdict).toMatch(/эффективен/i);
  });

  it('grounding.jsonFacts = ПОЛНАЯ фикстура (для цитирования имён/нарратива)', () => {
    expect(ctx.grounding.jsonFacts).toBe(decomposition);
  });
});

describe('buildTier2Prompt — структура и правила', () => {
  const ctx = buildTier2Context({
    step: STEP.DECOMPOSE,
    dec: decomposition,
    tier1Insights: [{ severity: 'warning', text: 'OLV перенасыщен', tip: 'gap -28 пп' }],
  });
  const prompt = buildTier2Prompt(ctx, 'Почему OLV неэффективен?');

  it('содержит железные правила INV-50', () => {
    expect(prompt).toContain(TIER2_SYSTEM_RULES);
    expect(prompt).toMatch(/Ты НЕ считаешь/);
    expect(prompt).toMatch(/INV-50/);
  });

  it('содержит факты, Tier-1 инсайты и вопрос', () => {
    expect(prompt).toContain('Факты модели');
    expect(prompt).toContain('Статьи');
    expect(prompt).toContain('OLV перенасыщен');
    expect(prompt).toContain('Почему OLV неэффективен?');
  });

  it('пустой вопрос → дефолтное «объясни»', () => {
    const p = buildTier2Prompt(ctx, '');
    expect(p).toMatch(/Объясни этот результат/);
  });
});

describe('honesty verdict проходит в контекст и промпт verbatim (шаг Оптимизация)', () => {
  const opt = {
    expected_lift_pct: 5.7,
    total_budget_money: 2_342_802_669,
    model_reliability: {
      verdict: 'uncertain',
      caveat_text: 'Данных мало (Ratio 2.4:1): рекомендации ориентировочные.',
    },
    channels: [],
  };
  const ctx = buildTier2Context({ step: STEP.OPTIMIZE, opt, tier1Insights: [] });

  it('honesty извлечён', () => {
    expect(ctx.honesty?.verdict).toBe('uncertain');
    expect(ctx.honesty?.caveat_text).toMatch(/ориентировочные/);
  });

  it('промпт несёт блок «Надёжность» дословно', () => {
    const prompt = buildTier2Prompt(ctx, 'Можно доверять?');
    expect(prompt).toContain('Надёжность');
    expect(prompt).toContain('Данных мало (Ratio 2.4:1): рекомендации ориентировочные.');
  });
});

describe('INV-50 смычка: честный ответ из фактов контекста проходит страж', () => {
  const ctx = buildTier2Context({ step: STEP.DECOMPOSE, dec: decomposition, tier1Insights: [] });

  it('ответ, опирающийся на факты сводки, не флагается', () => {
    const honest =
      'Статьи — самый эффективный канал (ROI 77.5×). OLV перенасыщен: ' +
      'доля бюджета 38.4%, а вклад только 10%, разрыв около 28 пунктов. ' +
      'Базовые продажи дают 80.6%.';
    expect(findUngroundedNumbers(honest, ctx.grounding)).toEqual([]);
  });

  it('выдуманное число флагается даже при наличии контекста', () => {
    const halluc = 'Если удвоить Статьи, продажи вырастут на 137%.';
    const bad = findUngroundedNumbers(halluc, ctx.grounding).map((b) => b.value);
    expect(bad).toContain(137);
  });
});

describe('summarizeModel — диагностика (синтетика)', () => {
  it('сводка несёт r_hat, divergences, ratio, MQS', () => {
    const mod = {
      diagnostics: {
        metrics: { r_hat_max: 1.023, divergences: 4, ratio: 2.4, r_squared: 0.976, mape_pct: 6.46 },
        mqs: { score: 70, tier_label: 'Хорошее' },
      },
      channelParams: { OLV: {}, Banners: {} },
    };
    const ctx = buildTier2Context({ step: STEP.MODEL, mod, tier1Insights: [] });
    expect(ctx.facts.r_hat_max).toBe(1.023);
    expect(ctx.facts.divergences).toBe(4);
    expect(ctx.facts.mqs_score).toBe(70);
    expect(ctx.facts.channels).toEqual(['OLV', 'Banners']);
  });
});
