/**
 * Советчик «сценарии словами» (Фаза 3) — разбор NL→config, применение к
 * расходам, подтверждение. Разбор реальным Claude проверяется live;
 * здесь — детерминированная логика извлечения/применения/описания.
 */
import { describe, it, expect } from 'vitest';
import {
  buildScenarioParsePrompt,
  extractScenarioConfig,
  applyChangesToMediaPlan,
  describeScenario,
} from '../scenario-advisor.js';

const CHANNELS = ['TV', 'OLV', 'Digital', 'Banners'];

describe('buildScenarioParsePrompt', () => {
  const p = buildScenarioParsePrompt('урежь ТВ на 20%', CHANNELS);
  it('содержит список каналов и схему JSON', () => {
    expect(p).toContain('"TV"');
    expect(p).toContain('"kind"');
    expect(p).toContain('delta_pct');
  });
  it('содержит запрос пользователя и правила', () => {
    expect(p).toContain('урежь ТВ на 20%');
    expect(p).toMatch(/Удвоить.*\+100/);
  });
});

describe('extractScenarioConfig', () => {
  it('чистый JSON', () => {
    const c = extractScenarioConfig('{"kind":"scenario","changes":[{"channel":"TV","delta_pct":-20}],"goal":"урезать ТВ"}');
    expect(c?.kind).toBe('scenario');
    expect(c?.changes).toEqual([{ channel: 'TV', delta_pct: -20 }]);
  });

  it('JSON с текстом вокруг (Claude добавил пояснение)', () => {
    const c = extractScenarioConfig('Вот разбор:\n{"kind":"scenario","changes":[{"channel":"Digital","delta_pct":100}],"goal":"удвоить диджитал"}\nГотово.');
    expect(c?.changes).toEqual([{ channel: 'Digital', delta_pct: 100 }]);
  });

  it('optimize-намерение', () => {
    const c = extractScenarioConfig('{"kind":"optimize","changes":[],"goal":"оптимизировать"}');
    expect(c?.kind).toBe('optimize');
  });

  it('scenario без изменений → unclear', () => {
    const c = extractScenarioConfig('{"kind":"scenario","changes":[],"goal":""}');
    expect(c?.kind).toBe('unclear');
  });

  it('фильтрует мусорные изменения (нет канала / нечисловой процент)', () => {
    const c = extractScenarioConfig('{"kind":"scenario","changes":[{"channel":"TV","delta_pct":-20},{"delta_pct":5},{"channel":"OLV","delta_pct":"много"}],"goal":""}');
    expect(c?.changes).toEqual([{ channel: 'TV', delta_pct: -20 }]);
  });

  it('мусор без JSON → null', () => {
    expect(extractScenarioConfig('не понял запрос')).toBeNull();
    expect(extractScenarioConfig('')).toBeNull();
    expect(extractScenarioConfig(null)).toBeNull();
  });
});

describe('applyChangesToMediaPlan', () => {
  const current = { TV: 1000, OLV: 500, Digital: 200 };

  it('урезать ТВ на 20% → 800, остальные без изменений', () => {
    const plan = applyChangesToMediaPlan([{ channel: 'TV', delta_pct: -20 }], current);
    expect(plan).toEqual({ TV: [800], OLV: [500], Digital: [200] });
  });

  it('удвоить (+100%) → 2×', () => {
    const plan = applyChangesToMediaPlan([{ channel: 'Digital', delta_pct: 100 }], current);
    expect(plan.Digital).toEqual([400]);
  });

  it('несколько изменений сразу', () => {
    const plan = applyChangesToMediaPlan(
      [{ channel: 'TV', delta_pct: -50 }, { channel: 'OLV', delta_pct: 20 }],
      current,
    );
    expect(plan).toEqual({ TV: [500], OLV: [600], Digital: [200] });
  });

  it('расход не уходит ниже нуля', () => {
    const plan = applyChangesToMediaPlan([{ channel: 'TV', delta_pct: -150 }], current);
    expect(plan.TV).toEqual([0]);
  });

  it('неизвестный канал игнорируется (защита от мисматча имени)', () => {
    const plan = applyChangesToMediaPlan([{ channel: 'Радио', delta_pct: -20 }], current);
    expect(plan).toEqual({ TV: [1000], OLV: [500], Digital: [200] });
  });

  it('формат media_plan — {channel: [budget]} (один период массивом)', () => {
    const plan = applyChangesToMediaPlan([], current);
    expect(Array.isArray(plan.TV)).toBe(true);
    expect(plan.TV.length).toBe(1);
  });
});

describe('describeScenario (human-in-the-loop)', () => {
  it('сценарий — перечисляет изменения словами', () => {
    const d = describeScenario({ kind: 'scenario', changes: [{ channel: 'TV', delta_pct: -20 }], goal: '' });
    expect(d).toMatch(/TV.*уменьшить на 20%/);
    expect(d).toMatch(/остальные каналы без изменений/);
    expect(d).toMatch(/Запустить расчёт\?/);
  });

  it('optimize — описание оптимизации', () => {
    const d = describeScenario({ kind: 'optimize', changes: [], goal: '' });
    expect(d).toMatch(/оптимальное распределение/);
  });

  it('unclear → null (подтверждать нечего)', () => {
    expect(describeScenario({ kind: 'unclear', changes: [], goal: '' })).toBeNull();
  });
});
