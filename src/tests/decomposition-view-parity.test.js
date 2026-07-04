/**
 * decomposition-view-parity.test.js — П4 (2026-07-04): канарейка паритета
 * маппинга групп py↔js. Класс тот же, что палитры факторов (У2): backend
 * decomposer.py (_TOP_GROUP_MAP / _FACTOR_GROUP_LABELS) и фронт
 * decomposition-view.js (fallbackTopGroup / TOP_GROUP_ORDER / TOP_GROUP_DISPLAY)
 * должны согласованно раскладывать факторы по 4 верхним группам.
 *
 * SSOT несёт top_group полем (fallbackTopGroup — резерв для legacy без поля),
 * поэтому риск дрейфа низкий, но при добавлении новой группы/фактора одна из
 * сторон легко отстанет → chip/tooltip/легенда покажут не ту группу.
 *
 * 🔴 ЯКОРЬ: меняешь _TOP_GROUP_MAP или _FACTOR_GROUP_LABELS в decomposer.py —
 * обнови fallbackTopGroup/TOP_GROUP_* в decomposition-view.js, тест зелёный.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  TOP_GROUP_ORDER,
  TOP_GROUP_DISPLAY,
  fallbackTopGroup,
} from '../lib/decomposition-view.js';

// vitest запускается из корня репозитория (process.cwd()).
const DECOMPOSER_PY = resolve(process.cwd(), 'sidecar/econometrica/engines/decomposer.py');

/** Извлечь python-словарь `{'k': 'v', ...}` по имени переменной. */
function pyDict(source, varName) {
  const i = source.indexOf(`${varName} = {`);
  if (i === -1) throw new Error(`не найден ${varName} в decomposer.py`);
  const j = source.indexOf('}', i);
  const block = source.slice(i, j);
  /** @type {Record<string,string>} */
  const out = {};
  for (const m of block.matchAll(/'([^']+)'\s*:\s*'([^']+)'/g)) {
    out[m[1]] = m[2];
  }
  return out;
}

const PY = readFileSync(DECOMPOSER_PY, 'utf-8');
const TOP_GROUP_MAP = pyDict(PY, '_TOP_GROUP_MAP');
const FACTOR_GROUP_LABELS = pyDict(PY, '_FACTOR_GROUP_LABELS');

describe('парсинг decomposer.py (санити — иначе паритет тривиален)', () => {
  it('_TOP_GROUP_MAP распарсен и непуст', () => {
    expect(Object.keys(TOP_GROUP_MAP).length).toBeGreaterThanOrEqual(10);
    expect(TOP_GROUP_MAP['Сезонность']).toBe('БАЗА');
  });
  it('_FACTOR_GROUP_LABELS распарсен и содержит новые типы', () => {
    expect(FACTOR_GROUP_LABELS['seasonality']).toBe('Сезонность');
    expect(FACTOR_GROUP_LABELS['category']).toBe('Категория');
  });
});

describe('паритет множества верхних групп', () => {
  it('значения _TOP_GROUP_MAP == TOP_GROUP_ORDER (обе стороны знают ровно 4 группы)', () => {
    const pyGroups = new Set(Object.values(TOP_GROUP_MAP));
    const jsGroups = new Set(TOP_GROUP_ORDER);
    expect([...pyGroups].sort()).toEqual([...jsGroups].sort());
  });
});

describe('fallbackTopGroup согласован с _TOP_GROUP_MAP', () => {
  it('для КАЖДОГО group-label py → js даёт ту же верхнюю группу (точное имя; префикс — для factor-меток)', () => {
    // Префиксная форма «{группа}: <колонка>» реальна ТОЛЬКО для factor-серий
    // (_FACTOR_GROUP_LABELS): baseline зовётся «Базовый уровень», медиа — именем
    // канала. Точное имя-метку проверяем для всех (fallbackTopGroup знает их после А-3).
    const factorLabels = new Set(Object.values(FACTOR_GROUP_LABELS));
    const mism = [];
    for (const [label, top] of Object.entries(TOP_GROUP_MAP)) {
      if (fallbackTopGroup(label) !== top) {
        mism.push(`точное «${label}»: js=${fallbackTopGroup(label)} ≠ py=${top}`);
      }
      if (factorLabels.has(label)) {
        const asSeries = `${label}: X`;
        if (fallbackTopGroup(asSeries) !== top) {
          mism.push(`серия «${asSeries}»: js=${fallbackTopGroup(asSeries)} ≠ py=${top}`);
        }
      }
    }
    expect(mism).toEqual([]);
  });

  it('baseline и медиа-имена ложатся в свои группы', () => {
    expect(fallbackTopGroup('Базовый уровень')).toBe(TOP_GROUP_MAP['База']);
    expect(fallbackTopGroup('Медиа')).toBe(TOP_GROUP_MAP['Медиа']);
  });
});

describe('_FACTOR_GROUP_LABELS согласован с _TOP_GROUP_MAP', () => {
  it('каждый factor-label из _FACTOR_GROUP_LABELS есть в _TOP_GROUP_MAP', () => {
    const missing = Object.values(FACTOR_GROUP_LABELS).filter((l) => !(l in TOP_GROUP_MAP));
    expect(missing).toEqual([]);
  });
});

describe('агрегатные display-имена (свёрнутый вид) классифицируются в свою группу', () => {
  it('fallbackTopGroup(TOP_GROUP_DISPLAY[g]) === g для всех групп', () => {
    const mism = [];
    for (const g of TOP_GROUP_ORDER) {
      const disp = TOP_GROUP_DISPLAY[g];
      if (fallbackTopGroup(disp) !== g) mism.push(`«${disp}»: js=${fallbackTopGroup(disp)} ≠ ${g}`);
    }
    expect(mism).toEqual([]);
  });
});
