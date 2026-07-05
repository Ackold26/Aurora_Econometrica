/**
 * Прямые юнит-тесты для 6 функций insights-rules.js, ранее не покрытых:
 * importInsights (~72), validateKpiInsights (~164), validateRolesInsights (~257),
 * validateMetricsInsights (~272), validateConfirmInsights (~350),
 * modelPreTrainingInsights (~990).
 *
 * Стиль — describe/it/expect, комментарии на русском, negative-first там где
 * указано. Текстовые проверки — якорными подстроками, не дословным равенством.
 *
 * Аудит 2026-07-05.
 */
import { describe, it, expect } from 'vitest';
import {
  importInsights,
  validateKpiInsights,
  validateRolesInsights,
  validateMetricsInsights,
  validateConfirmInsights,
  modelPreTrainingInsights,
  validateInsights,
} from '../insights-rules.js';

// ── Вспомогательные фикстуры ────────────────────────────────────────────────

/** Минимальный корректный importInsights-вход. */
function mkImport({ rows = 52, cols = 5, columns = [], zeros = {} } = {}) {
  return { rows, cols, columns, zeros };
}

/** Колонка для importInsights с именем-строкой. */
function col(name) {
  return { name };
}

/** Минимальный корректный validateKpiInsights-вход. */
function mkKpiResult({ kpi = 1, media = 2, control = 0, rows = 52, colNames = [] } = {}) {
  const columns = [];
  for (let i = 0; i < kpi; i++) columns.push({ name: colNames[i] ?? `kpi${i}`, role: 'kpi' });
  for (let i = 0; i < media; i++) columns.push({ name: colNames[kpi + i] ?? `media${i}`, role: 'media' });
  for (let i = 0; i < control; i++) columns.push({ name: `ctrl${i}`, role: 'control' });
  return { columns, file: { rows } };
}

/** Минимальный корректный validateMetricsInsights-вход с медиа-ролями. */
function mkMetricsResult(mediaNames = ['ch']) {
  const columns = mediaNames.map(n => ({ name: n, role: 'media' }));
  return { columns };
}

/** validateConfirmInsights-вход. */
function mkConfirmResult({ media = 2, control = 0, rows = 100 } = {}) {
  const columns = [];
  for (let i = 0; i < media; i++) columns.push({ name: `m${i}`, role: 'media' });
  for (let i = 0; i < control; i++) columns.push({ name: `c${i}`, role: 'control' });
  return { columns, file: { rows } };
}

/** modelPreTrainingInsights-вход. */
function mkTrainResult({ kpi = 1, media = 2, control = 0, rows = 100, mergedFrom = null } = {}) {
  const columns = [];
  for (let i = 0; i < kpi; i++) columns.push({ name: `kpi${i}`, role: 'kpi' });
  for (let i = 0; i < media; i++) {
    const c = { name: `media${i}`, role: 'media' };
    // добавляем merged_from только на первый канал если указано
    if (i === 0 && mergedFrom) c.merged_from = mergedFrom;
    columns.push(c);
  }
  for (let i = 0; i < control; i++) columns.push({ name: `ctrl${i}`, role: 'control' });
  return { columns, file: { rows } };
}

/** Тексты всех инсайтов слиты в одну строку. */
const joinText = (arr) => arr.map(i => i.text + ' ' + (i.tip ?? '')).join(' | ');

// ── A. Общая гигиена (все 6 функций) ───────────────────────────────────────

describe('A. Гигиена — каждый инсайт имеет severity и непустой text', () => {
  const VALID_SEVERITIES = new Set(['info', 'success', 'warning', 'error']);

  function checkInsights(arr) {
    expect(Array.isArray(arr)).toBe(true);
    for (const ins of arr) {
      expect(VALID_SEVERITIES.has(ins.severity), `severity «${ins.severity}» не из набора`).toBe(true);
      expect(typeof ins.text).toBe('string');
      expect(ins.text.length, `text пустой: ${JSON.stringify(ins)}`).toBeGreaterThan(0);
    }
  }

  it('importInsights — валидный вход', () => {
    checkInsights(importInsights(mkImport({ columns: [col('DATE'), col('SALES'), col('TV_SPEND')] })));
  });

  it('validateKpiInsights — валидный вход', () => {
    checkInsights(validateKpiInsights(mkKpiResult()));
  });

  it('validateRolesInsights — валидный вход', () => {
    checkInsights(validateRolesInsights(mkKpiResult({ kpi: 1, media: 3 })));
  });

  it('validateMetricsInsights — валидный вход', () => {
    checkInsights(validateMetricsInsights(mkMetricsResult()));
  });

  it('validateConfirmInsights — валидный вход', () => {
    checkInsights(validateConfirmInsights(mkConfirmResult()));
  });

  it('modelPreTrainingInsights — валидный вход', () => {
    checkInsights(modelPreTrainingInsights(mkTrainResult()));
  });

  it('null/undefined → [] для всех 6 функций', () => {
    expect(importInsights(null)).toEqual([]);
    expect(validateKpiInsights(null)).toEqual([]);
    expect(validateRolesInsights(null)).toEqual([]);
    expect(validateMetricsInsights(null)).toEqual([]);
    expect(validateConfirmInsights(null)).toEqual([]);
    expect(modelPreTrainingInsights(null)).toEqual([]);
  });
});

// ── B. importInsights ───────────────────────────────────────────────────────

describe('B. importInsights', () => {
  it('rows=0 → ровно 1 info с «Запустите валидацию»', () => {
    const out = importInsights(mkImport({ rows: 0 }));
    expect(out).toHaveLength(1);
    expect(out[0].severity).toBe('info');
    expect(out[0].text).toContain('Запустите валидацию');
  });

  it('rows=18 → warning «Мало данных» (и «месяц» в тексте)', () => {
    const out = importInsights(mkImport({ rows: 18, columns: [] }));
    const warns = out.filter(i => i.severity === 'warning');
    const txt = joinText(warns);
    expect(txt).toContain('Мало данных');
    expect(txt).toContain('месяц');
  });

  it('rows=24 (граница) → нет «Мало данных»', () => {
    const out = importInsights(mkImport({ rows: 24, columns: [] }));
    expect(joinText(out)).not.toContain('Мало данных');
  });

  it('rows=120 → success «отличный объём»', () => {
    const out = importInsights(mkImport({ rows: 120, columns: [] }));
    const txt = joinText(out.filter(i => i.severity === 'success'));
    expect(txt).toContain('отличный объём');
  });

  it('columns без даты → warning про дату', () => {
    const out = importInsights(mkImport({
      rows: 52,
      columns: [col('SALES'), col('TV_SPEND')],
    }));
    const txt = joinText(out.filter(i => i.severity === 'warning'));
    expect(txt).toContain('дат');
  });

  it('columns без KPI-имён → warning про KPI', () => {
    const out = importInsights(mkImport({
      rows: 52,
      columns: [col('DATE'), col('TV_SPEND')],
    }));
    const txt = joinText(out.filter(i => i.severity === 'warning'));
    expect(txt.toLowerCase()).toContain('kpi');
  });

  it('columns с DATE и SALES → success «структура данных подходит»', () => {
    const out = importInsights(mkImport({
      rows: 52,
      columns: [col('DATE'), col('SALES'), col('TV_SPEND')],
    }));
    const txt = joinText(out.filter(i => i.severity === 'success'));
    expect(txt).toContain('структура данных подходит');
  });

  it('>10 медиа-колонок → warning «Много медиа-переменных»', () => {
    const mediaNames = ['TV_SPEND', 'OLV_SPEND', 'BANNER_SPEND', 'DIGITAL_SPEND', 'RADIO_SPEND', 'SMM_SPEND', 'OUTDOOR_SPEND', 'SEARCH_SPEND', 'RTB_SPEND', 'PROGRAMMATIC_SPEND', 'EMAIL_SPEND'];
    const out = importInsights(mkImport({
      rows: 52,
      columns: [col('DATE'), col('SALES'), ...mediaNames.map(col)],
    }));
    expect(joinText(out)).toContain('Много медиа-переменных');
  });

  it('zeros: {ch: 85} → warning «% нулей»', () => {
    const out = importInsights(mkImport({
      rows: 52,
      columns: [col('DATE'), col('SALES')],
      zeros: { ch: 85 },
    }));
    expect(joinText(out.filter(i => i.severity === 'warning'))).toContain('нулей');
  });

  it('zeros: {ch: 50} → нет warning про нули', () => {
    const out = importInsights(mkImport({
      rows: 52,
      columns: [col('DATE'), col('SALES')],
      zeros: { ch: 50 },
    }));
    const warnTexts = out.filter(i => i.severity === 'warning').map(i => i.text);
    // предупреждение о нулях только при pct > 80
    expect(warnTexts.every(t => !t.includes('нулей'))).toBe(true);
  });

  it('columns как массив строк (не объектов) — не падает', () => {
    // Код делает c.name ?? String(c) — должен работать с любым типом
    const out = importInsights(mkImport({
      rows: 52,
      columns: ['DATE', 'SALES', 'TV_SPEND'],
    }));
    expect(Array.isArray(out)).toBe(true);
  });
});

// ── C. validateKpiInsights ──────────────────────────────────────────────────

describe('C. validateKpiInsights', () => {
  it('1 kpi-колонка → success «распознан автоматически»', () => {
    const out = validateKpiInsights(mkKpiResult({ kpi: 1 }));
    const txt = joinText(out.filter(i => i.severity === 'success'));
    expect(txt).toContain('распознан автоматически');
  });

  it('3+ kpi → info «Найдено»', () => {
    const out = validateKpiInsights(mkKpiResult({ kpi: 3 }));
    const txt = joinText(out.filter(i => i.severity === 'info'));
    expect(txt).toContain('Найдено');
  });

  it('0 kpi → warning «не распознана»', () => {
    const out = validateKpiInsights(mkKpiResult({ kpi: 0 }));
    const txt = joinText(out.filter(i => i.severity === 'warning'));
    expect(txt).toContain('не распознана');
  });

  it('только БЮДЖЕТ/SPEND-имена → success про ROI режим', () => {
    const out = validateKpiInsights(mkKpiResult({
      kpi: 1,
      media: 2,
      colNames: ['SALES', 'БЮДЖЕТ_ТВ', 'BUDGET_OLV'],
    }));
    const txt = joinText(out.filter(i => i.severity === 'success'));
    expect(txt).toContain('ROI');
  });

  it('только TRP/ПОКАЗ-имена → info про Эффективность', () => {
    const out = validateKpiInsights(mkKpiResult({
      kpi: 1,
      media: 2,
      colNames: ['SALES', 'TRP_TV', 'ПОКАЗЫ_OLV'],
    }));
    const txt = joinText(out.filter(i => i.severity === 'info'));
    expect(txt).toContain('Эффективность');
  });

  it('смесь БЮДЖЕТ + TRP → info «смешано» или «смешанный»', () => {
    const out = validateKpiInsights(mkKpiResult({
      kpi: 1,
      media: 2,
      colNames: ['SALES', 'БЮДЖЕТ_ТВ', 'TRP_OLV'],
    }));
    const txt = joinText(out.filter(i => i.severity === 'info'));
    expect(txt.toLowerCase()).toMatch(/смеш/);
  });

  it('имена без сигналов → ни один из трёх режим-инсайтов', () => {
    const out = validateKpiInsights(mkKpiResult({
      kpi: 1,
      media: 2,
      colNames: ['SALES', 'channel_a', 'channel_b'],
    }));
    const txt = joinText(out);
    // Нет конкретных сигналов — режимные инсайты не должны появляться
    // (moneyCount === 0 && physCount === 0 → ни одна из 3 ветвей не сработает)
    expect(txt).not.toContain('идеальный кейс для **ROI режима**');
    expect(txt).not.toContain('физических метриках');
    expect(txt).not.toContain('смешано');
  });

  it('«90% MMM-проектов» — якорь присутствует всегда (при kpi=1)', () => {
    const out = validateKpiInsights(mkKpiResult({ kpi: 1 }));
    expect(joinText(out)).toContain('90% MMM-проектов');
  });

  it('rows=20 → warning «очень мало»', () => {
    const out = validateKpiInsights(mkKpiResult({ rows: 20, kpi: 1 }));
    const txt = joinText(out.filter(i => i.severity === 'warning'));
    expect(txt).toContain('мало');
  });

  it('rows=40 → info «пилот»', () => {
    const out = validateKpiInsights(mkKpiResult({ rows: 40, kpi: 1 }));
    const txt = joinText(out.filter(i => i.severity === 'info'));
    expect(txt).toContain('пилот');
  });

  it('rows=60 → success «достаточно»', () => {
    const out = validateKpiInsights(mkKpiResult({ rows: 60, kpi: 1 }));
    const txt = joinText(out.filter(i => i.severity === 'success'));
    expect(txt).toContain('достаточно');
  });
});

// ── D. validateRolesInsights ────────────────────────────────────────────────

describe('D. validateRolesInsights — делегирует validateInsights с совпадением результата', () => {
  it('результат идентичен validateInsights для одинакового входа (toEqual)', () => {
    const result = {
      status: 'ok',
      columns: [
        { name: 'kpi0', role: 'kpi', stats: {} },
        { name: 'media0', role: 'media', stats: {} },
        { name: 'media1', role: 'media', stats: {} },
        { name: 'media2', role: 'media', stats: {} },
      ],
      file: { rows: 48 },
      warnings: [],
      detected: {},
    };
    const fromRoles = validateRolesInsights(result, 'roi');
    const fromValidate = validateInsights(result, 'roi');
    expect(fromRoles).toEqual(fromValidate);
  });

  it('null → [] и идентично validateInsights(null)', () => {
    expect(validateRolesInsights(null)).toEqual(validateInsights(null));
  });

  it('разные objective передаются корректно', () => {
    const result = {
      status: 'ok',
      columns: [
        { name: 'kpi0', role: 'kpi', stats: {} },
        { name: 'media0', role: 'media', stats: {} },
      ],
      file: { rows: 52 },
      warnings: [],
      detected: {},
    };
    expect(validateRolesInsights(result, 'effectiveness')).toEqual(
      validateInsights(result, 'effectiveness'),
    );
  });
});

// ── E. validateMetricsInsights ──────────────────────────────────────────────

describe('E. validateMetricsInsights', () => {
  it('media-ролей 0 → ровно 1 error «Нет активных медиа-каналов» (early return)', () => {
    const result = { columns: [{ name: 'kpi', role: 'kpi' }] };
    const out = validateMetricsInsights(result);
    expect(out).toHaveLength(1);
    expect(out[0].severity).toBe('error');
    expect(out[0].text).toContain('Нет активных медиа-каналов');
  });

  it('mode=roi, physical-канал, unitCosts={} → warning «без цены единицы»', () => {
    const out = validateMetricsInsights(mkMetricsResult(['ch']), {
      analysisMode: 'roi',
      perChannelInput: { ch: 'physical' },
      unitCosts: {},
    });
    expect(joinText(out.filter(i => i.severity === 'warning'))).toContain('физическими метриками');
  });

  it('F-007 stale: physical, unitCosts={ch:500}, budgetInputs={}, inputMode дефолт(budget) → всё равно warning', () => {
    // Канал physical + unitCost>0, НО budgetInputs пуст → inputReady=false → не ready
    const out = validateMetricsInsights(mkMetricsResult(['ch']), {
      analysisMode: 'roi',
      perChannelInput: { ch: 'physical' },
      unitCosts: { ch: 500 },
      budgetInputs: {},
      unitCostInputMode: {},
    });
    expect(joinText(out.filter(i => i.severity === 'warning'))).toContain('физическими метриками');
  });

  it('physical, unitCosts={ch:500}, unitCostInputMode={ch:unit} → success «готовы»', () => {
    const out = validateMetricsInsights(mkMetricsResult(['ch']), {
      analysisMode: 'roi',
      perChannelInput: { ch: 'physical' },
      unitCosts: { ch: 500 },
      unitCostInputMode: { ch: 'unit' },
    });
    expect(joinText(out.filter(i => i.severity === 'success'))).toContain('готовы');
  });

  it('physical, unitCosts={ch:500}, unitCostInputMode={ch:budget}, budgetInputs={ch:100000} → success', () => {
    const out = validateMetricsInsights(mkMetricsResult(['ch']), {
      analysisMode: 'roi',
      perChannelInput: { ch: 'physical' },
      unitCosts: { ch: 500 },
      unitCostInputMode: { ch: 'budget' },
      budgetInputs: { ch: 100000 },
    });
    expect(joinText(out.filter(i => i.severity === 'success'))).toContain('готовы');
  });

  it('mode=effectiveness → info «доли вклада»', () => {
    const out = validateMetricsInsights(mkMetricsResult(['ch']), {
      analysisMode: 'effectiveness',
    });
    expect(joinText(out.filter(i => i.severity === 'info'))).toContain('доли вклада');
  });

  it('mode=mixed → warning «±10-25%»', () => {
    const out = validateMetricsInsights(mkMetricsResult(['ch']), {
      analysisMode: 'mixed',
    });
    expect(joinText(out.filter(i => i.severity === 'warning'))).toContain('±10-25%');
  });
});

// ── F. validateConfirmInsights ──────────────────────────────────────────────

describe('F. validateConfirmInsights', () => {
  it('всегда: success «Готово к обучению» + info «После обучения»', () => {
    const out = validateConfirmInsights(mkConfirmResult({ media: 2, rows: 100 }));
    const successTxt = joinText(out.filter(i => i.severity === 'success'));
    const infoTxt = joinText(out.filter(i => i.severity === 'info'));
    expect(successTxt).toContain('Готово к обучению');
    expect(infoTxt).toContain('После обучения');
  });

  it('rows=20, 3 media + 3 control (ratio 3.3) → warning «ниже рекомендованного»', () => {
    // ratio = 20 / (3+3) = 3.33 < 4 → warning
    const out = validateConfirmInsights(mkConfirmResult({ media: 3, control: 3, rows: 20 }));
    expect(joinText(out.filter(i => i.severity === 'warning'))).toContain('ниже рекомендованного');
  });

  it('rows=100, 3+3 (ratio 16.7) → БЕЗ ratio-warning, ровно 2 инсайта', () => {
    const out = validateConfirmInsights(mkConfirmResult({ media: 3, control: 3, rows: 100 }));
    expect(out.filter(i => i.severity === 'warning')).toHaveLength(0);
    expect(out).toHaveLength(2);
  });

  it('context.analysisMode=effectiveness → «EFFECTIVENESS» в success-тексте', () => {
    const out = validateConfirmInsights(mkConfirmResult(), { analysisMode: 'effectiveness' });
    const successTxt = joinText(out.filter(i => i.severity === 'success'));
    expect(successTxt).toContain('EFFECTIVENESS');
  });
});

// ── G. modelPreTrainingInsights ─────────────────────────────────────────────

describe('G. modelPreTrainingInsights', () => {
  it('базовый (1 kpi + 2 media, rows=100) → success «Готово к обучению» + образовательные info', () => {
    const out = modelPreTrainingInsights(mkTrainResult({ kpi: 1, media: 2, rows: 100 }));
    const txt = joinText(out);
    expect(txt).toContain('Готово к обучению');
    expect(txt).toContain('Что происходит');
    expect(txt).toContain('Adstock');
    expect(txt).toContain('12 праздников РФ');
    expect(txt).toContain('После обучения смотрим');
  });

  it('рассинхрон-фикс: 3 media, enabledMediaNames=[tv_spend] → success с «1 медиаканал»', () => {
    // Все 3 media-роли, но активен только 1 → инсайт должен считать по enabled
    const result = {
      columns: [
        { name: 'kpi0', role: 'kpi' },
        { name: 'tv_spend', role: 'media' },
        { name: 'olv_spend', role: 'media' },
        { name: 'banner_spend', role: 'media' },
      ],
      file: { rows: 100 },
    };
    const out = modelPreTrainingInsights(result, ['tv_spend']);
    const successTxt = joinText(out.filter(i => i.severity === 'success'));
    // «1 медиаканал» (не 2 или 3)
    expect(successTxt).toContain('1 медиаканал');
    expect(successTxt).not.toContain('2 медиаканал');
    expect(successTxt).not.toContain('3 медиаканал');
  });

  it('enabledMediaNames=undefined → счёт по всем media-ролям', () => {
    const result = mkTrainResult({ kpi: 1, media: 3, rows: 100 });
    const out = modelPreTrainingInsights(result, undefined);
    const successTxt = joinText(out.filter(i => i.severity === 'success'));
    // Все 3 канала считаются активными
    expect(successTxt).toContain('3 медиаканал');
  });

  it('merged-канал → info «объединённый из N»', () => {
    const result = mkTrainResult({ kpi: 1, media: 2, rows: 100, mergedFrom: ['a', 'b'] });
    const out = modelPreTrainingInsights(result);
    const infoTxt = joinText(out.filter(i => i.severity === 'info'));
    expect(infoTxt).toContain('объединённый из 2');
  });

  it('6 активных каналов → info про оценку времени', () => {
    const result = mkTrainResult({ kpi: 1, media: 6, rows: 200 });
    const out = modelPreTrainingInsights(result);
    const txt = joinText(out.filter(i => i.severity === 'info'));
    expect(txt).toContain('Оценка времени');
  });

  it('2 канала → info про оценку времени отсутствует', () => {
    const result = mkTrainResult({ kpi: 1, media: 2, rows: 100 });
    const out = modelPreTrainingInsights(result);
    const txt = joinText(out.filter(i => i.severity === 'info'));
    expect(txt).not.toContain('Оценка времени');
  });

  it('rows=0 → ratio-инсайта нет, но образовательные присутствуют', () => {
    const result = mkTrainResult({ kpi: 1, media: 2, rows: 0 });
    const out = modelPreTrainingInsights(result);
    // ratio = 0 → ветка ratio не входит
    const ratioInsights = out.filter(i => i.text.startsWith('Ratio '));
    expect(ratioInsights).toHaveLength(0);
    // образовательные инсайты присутствуют
    expect(joinText(out)).toContain('Что происходит');
  });
});
