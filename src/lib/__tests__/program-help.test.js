/**
 * Справка о программе в контексте Авроры (program-help.js).
 * Проверяет: карту программы, релевантность терминов по шагу и по вопросу,
 * сборку help-контекста и смычку с INV-50 стражем (нормативы справки grounded,
 * выдуманные числа — нет).
 */
import { describe, it, expect } from 'vitest';
import {
  PROGRAM_OVERVIEW,
  STEP_TERMS,
  matchTermsInText,
  relevantTerms,
  buildHelpContext,
} from '../program-help.js';
import { findUngroundedNumbers } from '../insights-grounding.js';

describe('PROGRAM_OVERVIEW — карта программы', () => {
  it('несёт назначение, пайплайн и поддержку, без иллюстративных результатов', () => {
    expect(PROGRAM_OVERVIEW).toMatch(/Aurora MMM Optimizer/);
    expect(PROGRAM_OVERVIEW).toMatch(/Пайплайн/);
    expect(PROGRAM_OVERVIEW).toMatch(/Декомпозиция/);
    expect(PROGRAM_OVERVIEW).toMatch(/support@AuroraAi\.pro/);
    // методологические нормативы (пороги) — присутствуют
    expect(PROGRAM_OVERVIEW).toMatch(/1,05/);
  });
});

describe('matchTermsInText — термины по вопросу', () => {
  it('латинская аббревиатура: ROAS → roas', () => {
    expect(matchTermsInText('объясни ROAS канала')).toContain('roas');
  });

  it('трёхбуквенная аббревиатура: ROI → roi', () => {
    expect(matchTermsInText('что значит ROI?')).toContain('roi');
  });

  it('русское головное слово: «насыщение» → hill_saturation', () => {
    expect(matchTermsInText('что такое насыщение?')).toContain('hill_saturation');
  });

  it('словоформа: «декомпозиции» → decomposition', () => {
    expect(matchTermsInText('расскажи про результаты декомпозиции')).toContain('decomposition');
  });

  it('пустой/нерелевантный вопрос → нет ложных совпадений по ROI', () => {
    expect(matchTermsInText('')).toEqual([]);
    expect(matchTermsInText('какая сегодня погода')).not.toContain('roi');
  });
});

describe('relevantTerms — по шагу и вопросу', () => {
  it('шаг декомпозиции даёт термины декомпозиции', () => {
    const ids = relevantTerms({ step: 3 }).map((t) => t.id);
    expect(ids).toContain('decomposition');
    expect(ids).toContain('roi');
  });

  it('совпадение в вопросе приоритетнее и попадает даже вне термов шага', () => {
    // hill_saturation — терм шага 4, не 3; вопрос на шаге 3 всё равно поднимает его
    const ids = relevantTerms({ step: 3, question: 'почему насыщение?' }).map((t) => t.id);
    expect(ids).toContain('hill_saturation');
  });

  it('лимит не превышается', () => {
    const terms = relevantTerms({ step: 2, question: 'adstock и насыщение и ROI' });
    expect(terms.length).toBeLessThanOrEqual(8);
  });

  it('каждый терм несёт short-определение, без example/long (INV-50)', () => {
    for (const t of relevantTerms({ step: 3 })) {
      expect(typeof t.short).toBe('string');
      expect(t.short.length).toBeGreaterThan(0);
      expect(t).not.toHaveProperty('example');
      expect(t).not.toHaveProperty('long');
    }
  });
});

describe('buildHelpContext — сборка', () => {
  it('содержит карту программы и блок терминов', () => {
    const help = buildHelpContext({ step: 3, question: 'что такое насыщение?' });
    expect(help).toMatch(/СПРАВКА О ПРОГРАММЕ/);
    expect(help).toMatch(/Термины \(определения из справки/);
    expect(help).toMatch(/Насыщение/);
  });

  it('includeOverview=false убирает карту, оставляет термины', () => {
    const help = buildHelpContext({ step: 3, includeOverview: false });
    expect(help).not.toMatch(/СПРАВКА О ПРОГРАММЕ/);
    expect(help).toMatch(/Термины/);
  });
});

describe('INV-50 смычка: нормативы справки grounded, выдумки — нет', () => {
  it('порог из справки (1,05) не флагается стражем', () => {
    const help = buildHelpContext({ step: 2 });
    expect(findUngroundedNumbers('Порог сходимости R-hat — 1,05.', { jsonFacts: [help] })).toEqual([]);
  });

  it('выдуманное число, которого нет в справке, флагается', () => {
    const help = buildHelpContext({ step: 2 });
    const bad = findUngroundedNumbers('Точность модели 7777%.', { jsonFacts: [help] }).map((b) => b.value);
    expect(bad).toContain(7777);
  });
});

describe('STEP_TERMS — целостность маппинга', () => {
  it('все шаги 0..5 заданы', () => {
    for (let s = 0; s <= 5; s++) expect(Array.isArray(STEP_TERMS[s])).toBe(true);
  });
});
