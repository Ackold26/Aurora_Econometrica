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

  it('grounding.jsonFacts включает ПОЛНУЮ фикстуру (для цитирования имён/нарратива)', () => {
    // Форма — массив источников [fullFacts, honesty?, help?]; фикстура первый.
    expect(Array.isArray(ctx.grounding.jsonFacts)).toBe(true);
    expect(ctx.grounding.jsonFacts[0]).toBe(decomposition);
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

  it('число из honesty.caveat_text не флагается стражем (grounding включает honesty)', () => {
    // 2.4 есть только в honesty.caveat_text, не в opt-фактах — без honesty в
    // grounding оно бы ложно флагалось. Фикс ревью #2.
    expect(findUngroundedNumbers('Доверять осторожно: Ratio всего 2.4:1.', ctx.grounding)).toEqual([]);
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

describe('справка о программе в контексте Авроры', () => {
  it('контекст несёт help; промпт — блок «Справка о программе»', () => {
    const ctx = buildTier2Context({
      step: STEP.DECOMPOSE,
      dec: decomposition,
      question: 'что такое декомпозиция?',
    });
    expect(ctx.help).toMatch(/СПРАВКА О ПРОГРАММЕ/);
    const prompt = buildTier2Prompt(ctx, 'что такое декомпозиция?');
    expect(prompt).toContain('Справка о программе');
    expect(prompt).toMatch(/Декомпозиция/);
  });

  it('норматив-порог из справки (R-hat 1,05) не флагается стражем', () => {
    const ctx = buildTier2Context({
      step: STEP.MODEL,
      question: 'модель сошлась?',
      mod: { diagnostics: { metrics: { r_hat_max: 1.02 } }, channelParams: {} },
    });
    // 1,05 — порог из справки (overview), 1,02 — факт модели. Оба grounded.
    expect(
      findUngroundedNumbers('R-hat 1,02 при пороге надёжности 1,05 — модель сошлась.', ctx.grounding),
    ).toEqual([]);
  });

  it('выдуманный результат всё ещё ловится при наличии справки', () => {
    const ctx = buildTier2Context({ step: STEP.DECOMPOSE, dec: decomposition, question: 'итог?' });
    const bad = findUngroundedNumbers('Вклад ТВ вырос на 137%.', ctx.grounding).map((b) => b.value);
    expect(bad).toContain(137);
  });
});

describe('методология (RAG-библиотека узла Б) в контексте и промпте', () => {
  /** @type {import('../tier2-context.js').MethodologyHit[]} */
  const hits = [
    { text: 'Jin et al. (2017): байесовская MMM с иерархическим пулингом каналов даёт более устойчивые оценки ROI при малом числе наблюдений.', source: 'Jin 2017', title: 'Bayesian Methods for Media Mix Modeling', score: 0.41 },
  ];

  it('methodology передаётся в контекст, пустой массив/undefined → null', () => {
    const withHits = buildTier2Context({ step: STEP.DECOMPOSE, dec: decomposition, methodology: hits });
    expect(withHits.methodology).toEqual(hits);

    const withoutHits = buildTier2Context({ step: STEP.DECOMPOSE, dec: decomposition });
    expect(withoutHits.methodology).toBeNull();

    const emptyHits = buildTier2Context({ step: STEP.DECOMPOSE, dec: decomposition, methodology: [] });
    expect(emptyHits.methodology).toBeNull();
  });

  it('промпт с methodology содержит секцию «Канон методологии» и атрибуцию source', () => {
    const ctx = buildTier2Context({ step: STEP.DECOMPOSE, dec: decomposition, methodology: hits });
    const prompt = buildTier2Prompt(ctx, 'Почему ROI неопределённый?');
    expect(prompt).toContain('Канон методологии');
    expect(prompt).toContain('«Jin 2017»');
    expect(prompt).toContain('иерархическим пулингом каналов');
  });

  it('без methodology секции «Канон методологии» в промпте нет', () => {
    const ctx = buildTier2Context({ step: STEP.DECOMPOSE, dec: decomposition });
    const prompt = buildTier2Prompt(ctx, 'Почему OLV неэффективен?');
    expect(prompt).not.toContain('Канон методологии');
  });

  it('длинный text обрезается по границе слова с «…»', () => {
    const longText = 'слово '.repeat(200).trim(); // сильно длиннее лимита 600
    const ctx = buildTier2Context({
      step: STEP.DECOMPOSE,
      dec: decomposition,
      methodology: [{ text: longText, source: 'Long Source' }],
    });
    const prompt = buildTier2Prompt(ctx, 'вопрос');
    const line = prompt.split('\n').find((l) => l.includes('«Long Source»'));
    expect(line).toBeDefined();
    expect(line?.endsWith('…')).toBe(true);
    // Не обрывает слово посередине — символ перед «…» это конец «слово», не «слов».
    expect(line?.slice(0, -1).trimEnd().endsWith('слово')).toBe(true);
    expect(line?.length).toBeLessThan(longText.length);
  });

  it('число, встречающееся только в тексте methodology, не флагается стражем', () => {
    const ctx = buildTier2Context({
      step: STEP.DECOMPOSE,
      dec: decomposition,
      methodology: [{ text: 'Критерий сходимости требует R-hat ниже 1.01 (Vehtari 2021).', source: 'Vehtari 2021' }],
    });
    // 1.01 присутствует только в methodology-тексте, не в decomposition-фактах.
    expect(findUngroundedNumbers('Порог сходимости — 1.01, по канону методологии.', ctx.grounding)).toEqual([]);
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
