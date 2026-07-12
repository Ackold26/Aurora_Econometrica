/**
 * Тематизация RAG-запроса + читаемая атрибуция источника (Tier 2, живой
 * прогон 2026-07-11). buildRagQuery — двуязычные домен-термины по шагу
 * пайплайна; humanizeSource — имя файла источника → «Фамилия ГОД» для
 * промпта. Интеграционный тест смыкается с buildTier2Prompt.
 */
import { describe, it, expect } from 'vitest';
import { buildRagQuery, humanizeSource } from '../rag-query.js';
import { buildTier2Context, buildTier2Prompt, STEP } from '../tier2-context.js';

describe('buildRagQuery — тематизация по шагу', () => {
  it('OPTIMIZE: русские и английские термины + вопрос пользователя, длина в пределах лимита', () => {
    const q = buildRagQuery({ question: 'Почему такой ROI у ТВ?', step: STEP.OPTIMIZE });
    expect(q).toContain('Почему такой ROI у ТВ?');
    expect(q).toMatch(/marginal/i);
    expect(q).toMatch(/маржинальная|отдача/i);
    expect(q.length).toBeLessThanOrEqual(400);
  });

  it('DECOMPOSE: содержит carryover и насыщение', () => {
    const q = buildRagQuery({ question: 'Почему OLV неэффективен?', step: STEP.DECOMPOSE });
    expect(q).toMatch(/carryover/i);
    expect(q).toMatch(/насыщение/);
  });

  it('MODEL: содержит R-hat и сходимость', () => {
    const q = buildRagQuery({ question: 'Модель сошлась?', step: STEP.MODEL });
    expect(q).toMatch(/R-hat/);
    expect(q).toMatch(/сходимость/);
  });

  it('VALIDATE: содержит коллинеарность и confounder', () => {
    const q = buildRagQuery({ question: 'Каналы связаны?', step: STEP.VALIDATE });
    expect(q).toMatch(/коллинеарность/);
    expect(q).toMatch(/confounder/i);
  });

  it('шаг вне карты (IMPORT/REPORT/неизвестный) — fallback-термины без падения', () => {
    const qImport = buildRagQuery({ question: 'Что это за файл?', step: STEP.IMPORT });
    expect(qImport).toContain('Что это за файл?');
    expect(qImport).toMatch(/marketing mix modeling|эконометрика/i);

    const qReport = buildRagQuery({ question: 'Итог?', step: STEP.REPORT });
    expect(qReport).toMatch(/MMM/);

    const qNoStep = buildRagQuery({ question: 'Вопрос без шага' });
    expect(qNoStep).toContain('Вопрос без шага');
  });

  it('пустой вопрос — не падает, возвращает термины шага', () => {
    const q = buildRagQuery({ step: STEP.OPTIMIZE });
    expect(typeof q).toBe('string');
    expect(q.length).toBeGreaterThan(0);
  });

  it('focusChannelType добавляет уточнение по типу канала', () => {
    const reach = buildRagQuery({ question: 'ТВ снизить?', step: STEP.OPTIMIZE, focusChannelType: 'reach' });
    expect(reach).toMatch(/охватный|reach/i);

    const perf = buildRagQuery({ question: 'Директ снизить?', step: STEP.OPTIMIZE, focusChannelType: 'performance' });
    expect(perf).toMatch(/performance/i);
  });

  it('очень длинный вопрос обрезается до лимита по границе слова', () => {
    const longQuestion = 'Почему '.repeat(100);
    const q = buildRagQuery({ question: longQuestion, step: STEP.OPTIMIZE });
    expect(q.length).toBeLessThanOrEqual(400);
    expect(q.endsWith(' ')).toBe(false);
  });
});

describe('humanizeSource — атрибуция по имени файла', () => {
  it('Jin_2017_... → «Jin 2017»', () => {
    expect(humanizeSource('Jin_2017_Bayesian_Media_Mix_Modeling_Carryover_and_Shape_Effects')).toBe('Jin 2017');
  });

  it('Statistical_Rethinking_-_Richard_McElreath → «McElreath, «Statistical Rethinking»»', () => {
    expect(humanizeSource('Statistical_Rethinking_-_Richard_McElreath')).toBe('McElreath, «Statistical Rethinking»');
  });

  it('Bayesian_Workflow_-_Andrew_Gelman → «Gelman, «Bayesian Workflow»»', () => {
    expect(humanizeSource('Bayesian_Workflow_-_Andrew_Gelman')).toBe('Gelman, «Bayesian Workflow»');
  });

  it('Hernan_Robins_2025_Causal_Inference_What_If → «Hernan & Robins 2025»', () => {
    expect(humanizeSource('Hernan_Robins_2025_Causal_Inference_What_If')).toBe('Hernan & Robins 2025');
  });

  it('Chan_Perry_2017_Challenges_... → «Chan & Perry 2017»', () => {
    expect(humanizeSource('Chan_Perry_2017_Challenges_and_Opportunities')).toBe('Chan & Perry 2017');
  });

  it('неизвестный формат не падает — fallback на имя с пробелами', () => {
    expect(() => humanizeSource('Some_Weird_Name')).not.toThrow();
    expect(humanizeSource('Some_Weird_Name')).toBe('Some Weird Name');
  });

  it('пустая/undefined строка не падает', () => {
    expect(() => humanizeSource('')).not.toThrow();
    expect(humanizeSource(/** @type {any} */ (undefined))).toBe('');
  });
});

describe('buildTier2Prompt — атрибуция в промпте, не сырое имя файла', () => {
  it('промпт содержит «Jin 2017», НЕ содержит сырое «Jin_2017_Bayesian»', () => {
    const ctx = buildTier2Context({
      step: STEP.DECOMPOSE,
      tier1Insights: [],
      dec: { channels: [] },
      methodology: [
        {
          source: 'Jin_2017_Bayesian_Media_Mix_Modeling_Carryover_and_Shape_Effects',
          text: 'Adstock-эффект описывается геометрическим распадом.',
        },
      ],
    });
    const prompt = buildTier2Prompt(ctx, 'Почему такой carryover?');
    expect(prompt).toContain('Jin 2017');
    expect(prompt).not.toContain('Jin_2017_Bayesian');
  });
});

describe('buildRagQuery — длинный вопрос не вытесняет термины (самоаудит 2026-07-12)', () => {
  it('при вопросе >400 символов домен-термины шага сохраняются целиком', () => {
    const longQ = 'почему '.repeat(80).trim(); // ~560 символов
    const out = buildRagQuery({ question: longQ, step: 4 });
    expect(out.length).toBeLessThanOrEqual(400);
    // Ключевые двуязычные термины OPTIMIZE должны присутствовать несмотря на длинный вопрос.
    expect(out).toContain('marginal ROI');
    expect(out).toContain('насыщение');
    expect(out).toContain('diminishing returns');
  });
});
