/**
 * Тематизация RAG-запроса + читаемая атрибуция источника (Tier 2, живой
 * прогон 2026-07-11). buildRagQuery — двуязычные домен-термины по шагу
 * пайплайна; humanizeSource — имя файла источника → «Фамилия ГОД» для
 * промпта. Интеграционный тест смыкается с buildTier2Prompt.
 */
import { describe, it, expect } from 'vitest';
import { buildRagQuery, humanizeSource, detectChannelType } from '../rag-query.js';
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

  it('шаг вне карты (IMPORT/неизвестный) — fallback-термины без падения', () => {
    const qImport = buildRagQuery({ question: 'Что это за файл?', step: STEP.IMPORT });
    expect(qImport).toContain('Что это за файл?');
    expect(qImport).toMatch(/marketing mix modeling|эконометрика/i);

    const qNoStep = buildRagQuery({ question: 'Вопрос без шага' });
    expect(qNoStep).toContain('Вопрос без шага');
    expect(qNoStep).toMatch(/marketing mix modeling|эконометрика/i);
  });

  it('planning (5) и report (6) тематизируются, а не тонут в fallback (7-шкала, аудит 2026-07-12)', () => {
    // Регресс: planning-mode сдвинул report 5→6 и вставил planning=5; STEP_TERMS
    // индексировался по старой 5-шкале → на этих шагах тематизация отваливалась.
    const qPlanning = buildRagQuery({ question: 'Как распределить бюджет?', step: STEP.PLANNING });
    expect(qPlanning).toMatch(/планирование|media planning|медиаплан/i);
    const qReport = buildRagQuery({ question: 'Итог?', step: STEP.REPORT });
    expect(qReport).toMatch(/MMM/);
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
  it('Jin_2017_... → «Jin, „…“» без года', () => {
    expect(humanizeSource('Jin_2017_Bayesian_Media_Mix_Modeling_Carryover_and_Shape_Effects')).toBe('Jin, «Bayesian Media Mix Modeling Carryover and Shape Effects»');
  });

  it('Statistical_Rethinking_-_Richard_McElreath → «McElreath, «Statistical Rethinking»»', () => {
    expect(humanizeSource('Statistical_Rethinking_-_Richard_McElreath')).toBe('McElreath, «Statistical Rethinking»');
  });

  it('Bayesian_Workflow_-_Andrew_Gelman → «Gelman, «Bayesian Workflow»»', () => {
    expect(humanizeSource('Bayesian_Workflow_-_Andrew_Gelman')).toBe('Gelman, «Bayesian Workflow»');
  });

  it('Hernan_Robins_2025_... → «Hernan & Robins, „…“» без года', () => {
    expect(humanizeSource('Hernan_Robins_2025_Causal_Inference_What_If')).toBe('Hernan & Robins, «Causal Inference What If»');
  });

  it('Chan_Perry_2017_... → «Chan & Perry, „…“» без года', () => {
    expect(humanizeSource('Chan_Perry_2017_Challenges_and_Opportunities')).toBe('Chan & Perry, «Challenges and Opportunities»');
  });

  it('неизвестный формат не падает — fallback на имя с пробелами', () => {
    expect(() => humanizeSource('Some_Weird_Name')).not.toThrow();
    expect(humanizeSource('Some_Weird_Name')).toBe('Some Weird Name');
  });

  it('пустая/undefined строка не падает', () => {
    expect(() => humanizeSource('')).not.toThrow();
    expect(humanizeSource(/** @type {any} */ (undefined))).toBe('');
  });

  // Края формата, найденные внешним аудитом 2026-07-12 — ложная/потерянная атрибуция.
  it('ГОД_Автор_Название (год в начале) — фамилия не тонет в названии', () => {
    expect(humanizeSource('2017_Jin_Bayesian_Media_Mix')).toBe('Jin, «Bayesian Media Mix»');
  });

  it('нормативный ГОСТ/ФЗ (ALL-CAPS токен) — не выдумывает ложного автора', () => {
    expect(humanizeSource('ГОСТ_Реклама_2006_Требования')).toBe('ГОСТ Реклама 2006 Требования');
  });

  it('псевдогод из середины большего числа не раскалывает имя', () => {
    // 2019 внутри 2019456 — не отдельный год; имя без ложной атрибуции.
    expect(humanizeSource('Report_2019456_data')).toBe('Report 2019456 data');
  });
});

describe('buildTier2Prompt — атрибуция в промпте, не сырое имя файла', () => {
  it('промпт содержит читаемое «Jin, „…“» БЕЗ года и БЕЗ сырого «Jin_2017_Bayesian»', () => {
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
    expect(prompt).toContain('Jin, «Bayesian Media Mix Modeling Carryover and Shape Effects»');
    expect(prompt).not.toContain('Jin_2017_Bayesian'); // не сырое имя файла
    expect(prompt).not.toContain('Jin 2017');           // без года
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

describe('detectChannelType — тип фокус-канала из вопроса (оживление focusChannelType, аудит 2026-07-12)', () => {
  it('охватные маркеры → reach', () => {
    expect(detectChannelType('Почему у ТВ такой ROI?')).toBe('reach');
    expect(detectChannelType('охватный канал перекормлен?')).toBe('reach');
    expect(detectChannelType('что с брендовыми каналами')).toBe('reach');
  });

  it('performance-маркеры → performance', () => {
    expect(detectChannelType('Директ снизить?')).toBe('performance');
    expect(detectChannelType('перформанс канал эффективность')).toBe('performance');
  });

  it('неоднозначное / пустое → undefined (доп-терминов не добавляем)', () => {
    expect(detectChannelType('Как дела с моделью?')).toBeUndefined();
    expect(detectChannelType('')).toBeUndefined();
    expect(detectChannelType(/** @type {any} */ (undefined))).toBeUndefined();
  });

  it('«ответ» не ловится как «тв» (границы по словам, не подстрока)', () => {
    expect(detectChannelType('дай ответ по модели')).toBeUndefined();
  });
});
