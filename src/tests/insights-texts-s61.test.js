/**
 * s61 (Б2–Б8): тексты подсказок-инсайтов не противоречат числам на экране.
 *
 * Живой проход 10.10.2026 нашёл в подсказках: «8 медиаканалов» при четырёх
 * на экране, сырые `**`, «48 наблюдений (месячная) … для production ≥52»,
 * «+ 12 праздников РФ auto», «Результаты надёжны» рядом с баннером «модель
 * ориентировочная», «+0% – план уже оптимален» при перекладке 21,7 млн.
 *
 * Каждая проверка здесь обязана упасть на сломанном предмете (мутации –
 * Projects/_s61/EXEC_B_report.md).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import {
  validateKpiInsights,
  validateRolesInsights,
  validateInsights,
  validateMetricsInsights,
  validateConfirmInsights,
  modelPreTrainingInsights,
  modelInsights,
  reportInsights,
  optimizeShiftIsSignificant,
  OPTIMIZE_SHIFT_MIN_SHARE,
} from '../lib/insights-rules.js';

import { effectiveRatio } from '../lib/ratio-classifier.js';

const HERE = dirname(fileURLToPath(import.meta.url));

/** @param {any[]} arr */
const joined = (arr) => arr.map((i) => `${i.text} ${i.tip ?? ''}`).join('\n');

// ── Б2 ────────────────────────────────────────────────────────────────────

/**
 * 4 бюджетные + 4 физические медиа-колонки, 3 контрольные.
 * @param {{ rows?: number, detected?: any }} [o]
 * @returns {any}
 */
function pairsResult({ rows = 100, detected = undefined } = {}) {
  const budget = ['tv_spend', 'olv_spend', 'ooh_spend', 'radio_spend'];
  const phys = ['tv_trp', 'olv_impressions', 'ooh_contacts', 'radio_grp'];
  return {
    columns: [
      { name: 'sales', role: 'kpi' },
      ...budget.map((name) => ({ name, role: 'media' })),
      ...phys.map((name) => ({ name, role: 'media' })),
      { name: 'price', role: 'control' },
      { name: 'temp', role: 'control' },
      { name: 'promo', role: 'control' },
    ],
    file: { rows },
    detected,
  };
}
const PHYS_OFF = { tv_trp: false, olv_impressions: false, ooh_contacts: false, radio_grp: false };

describe('Б2: число каналов в инсайте подтверждения – по включённым колонкам', () => {
  it('4 физические выключены → «4 медиаканала», не «8 медиаканалов»', () => {
    const t = joined(validateConfirmInsights(pairsResult(), { analysisMode: 'roi' }, 'bayesian', true, 0, PHYS_OFF));
    expect(t).toContain('4 медиаканала');
    expect(t).not.toContain('8 медиаканалов');
  });
  it('карты нет → прежний счёт по ролям (8)', () => {
    const t = joined(validateConfirmInsights(pairsResult(), { analysisMode: 'roi' }));
    expect(t).toContain('8 медиаканалов');
  });
  it('пустая карта и ключ без записи = включена', () => {
    const t = joined(validateConfirmInsights(pairsResult(), {}, 'bayesian', true, 0, {}));
    expect(t).toContain('8 медиаканалов');
    const t2 = joined(validateConfirmInsights(pairsResult(), {}, 'bayesian', true, 0, { tv_trp: false }));
    expect(t2).toContain('7 медиаканалов');
  });
  it('только значение false выключает: true и не-булево оставляют колонку', () => {
    const t = joined(validateConfirmInsights(pairsResult(), {}, 'bayesian', true, 0, { tv_trp: true, olv_impressions: undefined }));
    expect(t).toContain('8 медиаканалов');
  });
  it('проводка: InsightsPanel передаёт в validateConfirmInsights КАРТУ $modelChannelEnabled, а не имена', () => {
    const src = readFileSync(resolve(HERE, '../lib/components/pipeline/InsightsPanel.svelte'), 'utf8');
    const call = src.split(String.fromCharCode(10)).find((l) => l.includes('validateConfirmInsights(')
      && !l.trim().startsWith('//') && !l.includes('import'));
    expect(call, 'вызов validateConfirmInsights не найден').toBeDefined();
    expect(call).toContain('$modelChannelEnabled');
    expect(call).not.toContain('$modelEnabledMediaNames');
  });
  it('запас данных считается по тем же включённым колонкам (число в предупреждении меняется)', () => {
    // 40 наблюдений: 8 колонок → 40/(8+3+13)=1.7; 4 колонки → 40/(4+3+13)=2.0
    const det = { n_holidays_auto: 12, n_params_effective_bayesian: undefined, n_params_effective_pretrain: undefined };
    const all = joined(validateConfirmInsights(pairsResult({ rows: 40, detected: det }), {}, 'bayesian', true, 0, {}));
    const four = joined(validateConfirmInsights(pairsResult({ rows: 40, detected: det }), {}, 'bayesian', true, 0, PHYS_OFF));
    const re = /Запас данных ([0-9.]+):1/;
    expect(all.match(re)?.[1]).toBeDefined();
    expect(four.match(re)?.[1]).toBeDefined();
    expect(all.match(re)?.[1]).not.toBe(four.match(re)?.[1]);
  });
});

// ── Б3 ────────────────────────────────────────────────────────────────────

describe('Б3: в текстах инсайтов нет сырых `**`', () => {
  /** @param {string[]} names */
  const kpiResult = (names) => ({
    columns: [{ name: 'sales', role: 'kpi' }, ...names.map((name) => ({ name, role: 'media' }))],
    file: { rows: 60 },
  });
  const nameSets = {
    рубли: ['БЮДЖЕТ_ТВ', 'BUDGET_OLV'],
    физика: ['TRP_TV', 'ПОКАЗЫ_OLV'],
    смесь: ['БЮДЖЕТ_ТВ', 'TRP_OLV'],
  };
  for (const [label, names] of Object.entries(nameSets)) {
    it(`validateKpiInsights (${label}): ни text, ни tip без «**»`, () => {
      const out = validateKpiInsights(kpiResult(names), { analysisMode: 'roi' });
      expect(out.length).toBeGreaterThan(0);
      for (const i of out) {
        expect(i.text).not.toMatch(/\*\*/);
        expect(i.tip ?? '').not.toMatch(/\*\*/);
      }
    });
  }
  it('validateConfirmInsights: «режим ROI» без звёздочек', () => {
    const out = validateConfirmInsights(pairsResult(), { analysisMode: 'roi' });
    const t = joined(out);
    expect(t).not.toMatch(/\*\*/);
    expect(t).toContain('режим ROI');
  });
  it('сторож по исходнику: в строковых литералах insights-rules.js нет «**слово**»', () => {
    const src = readFileSync(resolve(HERE, '../lib/insights-rules.js'), 'utf8');
    const bad = src.split('\n')
      .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
      .filter((l) => /\*\*[^*\s/][^*]*\*\*/.test(l));
    expect(bad).toEqual([]);
  });
});

// ── Б4 ────────────────────────────────────────────────────────────────────

describe('Б4: текст про число наблюдений – по настоящей частоте данных', () => {
  /**
   * @param {number} rows
   * @param {string | undefined} freq
   */
  const kpiRes = (rows, freq) => ({
    columns: [{ name: 'sales', role: 'kpi' }, { name: 'БЮДЖЕТ_ТВ', role: 'media' }],
    file: { rows },
    detected: freq === undefined ? {} : { date_frequency: freq },
  });
  /** @param {any} res */
  const period = (res) => validateKpiInsights(res).filter((i) => /наблюдени/.test(i.text));

  it('48 месячных → одна строка «достаточно», без «52» и «production»', () => {
    const out = period(kpiRes(48, 'monthly'));
    expect(out).toHaveLength(1);
    expect(out[0].severity).toBe('success');
    expect(out[0].text).toContain('месячные данные');
    expect(joined(out)).not.toMatch(/52|production/);
  });
  it('20 месячных → «очень мало», порог 24 мес', () => {
    const out = period(kpiRes(20, 'monthly'));
    expect(out[0].severity).toBe('warning');
    expect(out[0].text).toContain('очень мало');
    expect(out[0].tip).toContain('24 мес');
  });
  it('40 недельных → «пилот» и «52 нед», слов про месяцы нет', () => {
    const out = period(kpiRes(40, 'weekly'));
    expect(out[0].severity).toBe('info');
    expect(out[0].text).toContain('пилот');
    expect(out[0].text).toContain('52 нед');
    expect(out[0].text).toContain('недельные данные');
    expect(out[0].text).not.toMatch(/месяч/);
  });
  it('53 недельные строки не называются «месячными» (раньше – по числу строк)', () => {
    const out = period(kpiRes(53, 'weekly'));
    expect(out[0].text).toContain('недельные данные');
    expect(out[0].text).not.toContain('месячн');
  });
  it('граница «очень мало» – 24 для всех частот (как у движка): 10 квартальных → мало, 24 → достаточно', () => {
    const ten = period(kpiRes(10, 'quarterly'))[0];
    expect(ten.severity).toBe('warning');
    expect(ten.text).toContain('очень мало');
    expect(ten.text).not.toContain('достаточно');
    expect(ten.tip).toContain('не меньше 24 кв');
    expect(period(kpiRes(23, 'quarterly'))[0].severity).toBe('warning');
    const full = period(kpiRes(24, 'quarterly'))[0];
    expect(full.severity).toBe('success');
    expect(full.text).toContain('достаточно');
  });
  it('рекомендованный минимум в подсказке «очень мало»: мес 24, нед 52, неизвестная 52 наблюдений', () => {
    expect(period(kpiRes(10, 'monthly'))[0].tip).toContain('не меньше 24 мес');
    expect(period(kpiRes(10, 'weekly'))[0].tip).toContain('не меньше 52 нед');
    expect(period(kpiRes(10, 'unknown'))[0].tip).toContain('не меньше 52 наблюдений');
    expect(period(kpiRes(10, undefined))[0].tip).toContain('не меньше 52 наблюдений');
  });
  it('частота неизвестна (нет поля / unknown): частота в тексте не называется, порог 52', () => {
    for (const f of [undefined, 'unknown']) {
      const out = period(kpiRes(40, f));
      expect(out[0].severity).toBe('info');
      expect(out[0].text).not.toMatch(/месячн|недельн|дневн|квартальн/);
      expect(out[0].text).toContain('52 наблюдений');
    }
  });
  it('форма слова «наблюдение» по числу: 1 / 21 / 22 / 40', () => {
    expect(period(kpiRes(1, 'monthly'))[0].text).toMatch(/^1 наблюдение /);
    expect(period(kpiRes(21, 'monthly'))[0].text).toMatch(/^21 наблюдение /);
    expect(period(kpiRes(22, 'monthly'))[0].text).toMatch(/^22 наблюдения /);
    expect(period(kpiRes(40, 'weekly'))[0].text).toMatch(/^40 наблюдений /);
  });
  it('слова «production» нет ни в одной ветке', () => {
    for (const rows of [5, 20, 30, 40, 60, 300]) {
      for (const f of [undefined, 'monthly', 'weekly', 'daily', 'quarterly']) {
        expect(joined(validateKpiInsights(kpiRes(rows, f)))).not.toMatch(/production/);
      }
    }
  });
});

// ── Б5 ────────────────────────────────────────────────────────────────────

describe('Б5: число праздников – из данных движка, без «auto»', () => {
  /**
   * @param {any} detected
   * @param {...any} rest  engine, useHolidays, disabledHolidaysCount
   */
  const pre = (detected, ...rest) => joined(modelPreTrainingInsights(
    { ...pairsResult({ rows: 100, detected }), },
    undefined,
    ...rest,
  ));

  it('n_holidays_auto = 13 → «13 праздников РФ» в обеих строках, без «12» и «auto»', () => {
    const out = modelPreTrainingInsights(pairsResult({ detected: { n_holidays_auto: 13 } }));
    const summary = out.find((i) => i.text.startsWith('Готово к обучению'));
    const edu = out.find((i) => i.text.startsWith('К контрольным переменным'));
    expect(summary?.text).toContain('+ 13 праздников РФ автоматически');
    expect(edu?.text).toContain('добавляется 13 праздников РФ');
    const t = joined(out);
    expect(t).not.toContain('12 праздников');
    expect(t).not.toMatch(/\bauto\b/);
  });
  it('склонение: 1 праздник, 2 праздника, 5 праздников', () => {
    expect(pre({ n_holidays_auto: 1 })).toContain('1 праздник РФ');
    expect(pre({ n_holidays_auto: 2 })).toContain('2 праздника РФ');
    expect(pre({ n_holidays_auto: 5 })).toContain('5 праздников РФ');
  });
  it('поштучно отключённые вычитаются так же, как в запасе данных (13 − 3 = 10)', () => {
    expect(pre({ n_holidays_auto: 13 }, 'bayesian', true, 3)).toContain('10 праздников РФ');
  });
  it('поля нет в ответе → число не выдумывается', () => {
    const t = pre({});
    expect(t).not.toMatch(/\d+ праздник/);
    expect(t).toContain('праздники РФ автоматически');
  });
  it('ноль праздников (все учтены колонками / отключены) → отдельный текст без перечня и без подсказки', () => {
    const out = modelPreTrainingInsights(pairsResult({ detected: { n_holidays_auto: 0 } }));
    const edu = out.find((i) => i.text.startsWith('Праздники РФ автоматически не добавляются'));
    expect(edu?.text).toContain('все они уже учтены вашими колонками или отключены');
    expect(edu?.tip).toBeUndefined();
    const t = joined(out);
    expect(t).not.toMatch(/добавля\S* 0 праздник/);
    expect(t).not.toContain('Новый год');
    // все 13 отключены поштучно – тот же текст
    const out2 = modelPreTrainingInsights(pairsResult({ detected: { n_holidays_auto: 13 } }), undefined, 'bayesian', true, 13);
    expect(out2.some((i) => i.text.includes('все они уже учтены'))).toBe(true);
  });
  it('глагол согласован с числом: 1 / 2 / 13 праздников', () => {
    /** @param {number} n */
    const edu = (n) => modelPreTrainingInsights(pairsResult({ detected: { n_holidays_auto: n } }))
      .find((i) => i.text.startsWith('К контрольным переменным'))?.text ?? '';
    expect(edu(1)).toContain('автоматически добавляется 1 праздник РФ');
    expect(edu(2)).toContain('автоматически добавляются 2 праздника РФ');
    expect(edu(13)).toContain('автоматически добавляется 13 праздников РФ');
  });
  it('OLS и выключенные праздники → числа нет, «добавляется» не говорим', () => {
    for (const args of [['ols', true, 0], ['bayesian', false, 0]]) {
      const t = pre({ n_holidays_auto: 13 }, ...args);
      expect(t).not.toMatch(/\d+ праздник/);
      expect(t).not.toContain('автоматически добавля');
      expect(t).toContain('автоматически не добавляются');
      const summary = modelPreTrainingInsights(
        pairsResult({ detected: { n_holidays_auto: 13 } }), undefined, ...args,
      ).find((i) => i.text.startsWith('Готово к обучению'));
      expect(summary?.text).not.toMatch(/праздник/);
    }
  });
});

// ── Б6 ────────────────────────────────────────────────────────────────────

describe('Б6: верные формы числа и счёт каналов после группировки пар', () => {
  /** @param {string[]} names */
  const metricsRes = (names) => ({ columns: names.map((name) => ({ name, role: 'media' })) });

  it('8 колонок в 4 парах → «Все 4 канала готовы», не «Все 8 каналов»', () => {
    const res = metricsRes(['tv_spend', 'tv_trp', 'olv_spend', 'olv_impressions', 'ooh_spend', 'ooh_contacts', 'radio_spend', 'radio_grp']);
    const t = joined(validateMetricsInsights(res, { analysisMode: 'roi' }));
    expect(t).toContain('Все 4 канала готовы');
    expect(t).not.toContain('8 каналов');
  });
  it('формы: 1 / 2 / 5 / 21 канал в разных режимах', () => {
    const mk = (/** @type {number} */ n) => metricsRes(Array.from({ length: n }, (_, i) => `ch${i}`));
    expect(joined(validateMetricsInsights(mk(1), { analysisMode: 'roi' }))).toContain('Канал готов');
    expect(joined(validateMetricsInsights(mk(2), { analysisMode: 'roi' }))).toContain('Все 2 канала готовы');
    expect(joined(validateMetricsInsights(mk(5), { analysisMode: 'roi' }))).toContain('Все 5 каналов готовы');
    expect(joined(validateMetricsInsights(mk(21), { analysisMode: 'roi' }))).toContain('Все 21 канал готовы');
    expect(joined(validateMetricsInsights(mk(3), { analysisMode: 'effectiveness' }))).toContain('все 3 канала будут поданы');
    expect(joined(validateMetricsInsights(mk(1), { analysisMode: 'effectiveness' }))).toContain('единственный канал будет подан');
    expect(joined(validateMetricsInsights(mk(2), { analysisMode: 'mixed' }))).toContain('Смешанный режим: 2 канала.');
    expect(joined(validateMetricsInsights(mk(1), { analysisMode: 'mixed' }))).toContain('Смешанный режим: 1 канал.');
  });
  it('«N каналов с физическими метриками без цены»: 1 канал / 2 канала / 5 каналов', () => {
    for (const [n, word] of /** @type {[number, string][]} */ ([[1, 'канал'], [2, 'канала'], [5, 'каналов']])) {
      const names = Array.from({ length: n }, (_, i) => `ch${i}`);
      const perChannelInput = Object.fromEntries(names.map((c) => [c, 'physical']));
      const t = joined(validateMetricsInsights(metricsRes(names), { analysisMode: 'roi', perChannelInput }));
      expect(t).toContain(`${n} ${word} с физическими метриками`);
    }
  });
  it('подтверждение: «1 медиаканал», «2 медиаканала», «5 медиаканалов», «21 медиаканал»; контрольные', () => {
    /** @param {number} m @param {number} c */
    const mk = (m, c) => ({
      columns: [
        { name: 'k', role: 'kpi' },
        ...Array.from({ length: m }, (_, i) => ({ name: `m${i}`, role: 'media' })),
        ...Array.from({ length: c }, (_, i) => ({ name: `c${i}`, role: 'control' })),
      ],
      file: { rows: 100 },
    });
    const first = (/** @type {number} */ m, /** @type {number} */ c) => validateConfirmInsights(mk(m, c), {})[0].text;
    expect(first(1, 0)).toContain('Готово к обучению: 1 медиаканал,');
    expect(first(2, 0)).toContain('2 медиаканала,');
    expect(first(5, 0)).toContain('5 медиаканалов,');
    expect(first(21, 0)).toContain('21 медиаканал,');
    expect(first(4, 1)).toContain('4 медиаканала + 1 контрольная,');
    expect(first(4, 2)).toContain('4 медиаканала + 2 контрольные,');
    expect(first(4, 5)).toContain('4 медиаканала + 5 контрольных,');
  });
  it('шаг «Модель»: «4 медиаканала, 3 контрольные переменные»', () => {
    const out = modelPreTrainingInsights(pairsResult({ detected: { n_holidays_auto: 13 } }), ['tv_spend', 'olv_spend', 'ooh_spend', 'radio_spend']);
    const summary = out.find((i) => i.text.startsWith('Готово к обучению'));
    expect(summary?.text).toContain('4 медиаканала, 3 контрольные переменные');
  });
});

// ── Б7 ────────────────────────────────────────────────────────────────────

describe('Б7: «результаты надёжны» не печатается при ориентировочной модели', () => {
  /**
   * @param {{ ratio: number, verdict?: string | null, score?: number }} o
   * @returns {any}
   */
  function model({ ratio, verdict = null, score = 70 }) {
    return {
      diagnostics: {
        metrics: {
          r_squared: 0.9, mape_pct: 4, r_hat_max: 1.0, divergences: 0,
          ratio, n_observations: 60, n_parameters: 20,
        },
        mqs: { score, tier_label: 'Хорошее', tier: 'good' },
        ...(verdict ? { honesty_verdict: verdict } : {}),
      },
      channelParams: { OLV: {}, Banners: {}, Social: {} },
    };
  }
  const SAYS_RELIABLE = /Результаты надёжны/;
  /** Заголовок вердикта (первая строка с MQS) – перед ним могут идти другие подсказки. */
  const headline = (/** @type {any[]} */ out) => out.find((i) => /^MQS = /.test(i.text));

  it('MQS 70 при запасе данных 2.7 → фразы «Результаты надёжны» нет, есть «ориентировочные»', () => {
    const out = modelInsights(model({ ratio: 2.7 }));
    const head = headline(out);
    expect(head.text).toContain('MQS = 70');
    expect(head.text).toContain('оценка качества хорошая, но на ограниченных данных выводы ориентировочные');
    expect(head.severity).toBe('warning');
    expect(head.text).not.toMatch(SAYS_RELIABLE);
  });
  it('MQS 70, запас достаточный, но модель помечена «uncertain» → тоже без «надёжны»', () => {
    const head = headline(modelInsights(model({ ratio: 12, verdict: 'uncertain' })));
    expect(head.text).not.toMatch(SAYS_RELIABLE);
    expect(head.text).toContain('модель помечена как ориентировочная');
  });
  it('MQS 70, запас 12, вердикт «reliable» → прежняя фраза остаётся', () => {
    const head = headline(modelInsights(model({ ratio: 12, verdict: 'reliable' })));
    expect(head.text).toContain('Результаты надёжны для принятия решений');
    expect(head.severity).toBe('success');
  });
  it('MQS 70, запас 12, без штампа вердикта (старый проект) → прежняя фраза', () => {
    const head = headline(modelInsights(model({ ratio: 12 })));
    expect(head.text).toContain('Результаты надёжны для принятия решений');
  });
  it('«unreliable» по-прежнему уходит в ветку отказа, а не в «надёжны»', () => {
    const head = headline(modelInsights(model({ ratio: 12, verdict: 'unreliable' })));
    expect(head.text).not.toMatch(SAYS_RELIABLE);
    expect(head.text).toContain('MQS = 70');
  });
  it('балл и ступень остаются на экране в новой ветке', () => {
    const head = headline(modelInsights(model({ ratio: 2.7 })));
    expect(head.text).toContain('MQS = 70 (Хорошее)');
  });
});

// ── Б-1 (круг 2): инсайты «Ролей колонок» считают по включённым колонкам ──

describe('Б-1: validateRolesInsights – то же число каналов и тот же запас, что шапка (по включённым)', () => {
  const det = { n_holidays_auto: 12 };
  /** @param {string[]} media @param {Record<string, number>} [zeros] */
  const res = (media, zeros = {}) => ({
    columns: [
      { name: 'sales', role: 'kpi', stats: {} },
      ...media.map((name) => ({ name, role: 'media', stats: { zeros_pct: zeros[name] ?? 0, sum: 1000 } })),
      { name: 'price', role: 'control', stats: {} },
    ],
    file: { rows: 104 },
    detected: det,
    warnings: [],
  });
  const four = ['a_spend', 'b_spend', 'c_spend', 'd_spend'];
  const five = [...four, 'sparse_spend'];
  const sparse = { sparse_spend: 85 };
  /** @param {any} r @param {any} [map] */
  const texts = (r, map) => validateRolesInsights(r, 'roi', 'bayesian', true, 0, map).map((i) => `${i.severity}|${i.text}|${i.tip ?? ''}`);

  it('канал «85 % нулей» выключен картой → инсайты те же, что для файла без этого канала', () => {
    expect(texts(res(five, sparse), { sparse_spend: false })).toEqual(texts(res(four)));
  });
  it('в тексте то же число каналов и тот же запас, что даёт расчёт по включённым', () => {
    const ratio = effectiveRatio(104, det, 'bayesian', 4 + 1, true, 0);
    const t = texts(res(five, sparse), { sparse_spend: false }).join('\n');
    expect(t).toContain('4 каналов');
    expect(t).toContain(`ratio ${ratio.toFixed(1)}:1`);
    expect(t).not.toContain('5 каналов');
  });
  it('карты нет (аргумент не передан) → прежний счёт по ролям', () => {
    const noMap = texts(res(five, sparse)).join('\n');
    expect(noMap).not.toBe(texts(res(five, sparse), { sparse_spend: false }).join('\n'));
    expect(noMap).toMatch(/5 (медиаканал|каналов)/);
  });
  it('ключ без записи = включена: карта с другим ключом ничего не меняет', () => {
    expect(texts(res(five, sparse), { other: false })).toEqual(texts(res(five, sparse)));
  });
  const NL = String.fromCharCode(10);
  // Сравнение «с картой» и «без карты» друг с другом не ловит ошибку правила «нет ключа = выключена»:
  // оба варианта ломаются одинаково (ноль каналов). Поэтому здесь проверяется содержание итога.
  it('ключ есть не у всех: колонки без записи включены, ошибки «Нет активных медиа-каналов» нет', () => {
    // у sparse_spend ключ false, у остальных четырёх записи нет: включены четыре, а не ноль
    const t = texts(res(five, sparse), { sparse_spend: false }).join(NL);
    expect(t, 'колонки без ключа в карте посчитаны выключенными').not.toContain('Нет активных медиа-каналов');
    expect(t).toContain('Данные готовы к обучению модели');
  });
  it('карта не передана, равна null или пуста: все медиа включены, ошибки о каналах нет', () => {
    for (const map of [undefined, null, {}]) {
      const t = texts(res(five, sparse), map).join(NL);
      expect(t, `карта ${JSON.stringify(map)}: каналы не засчитаны`).not.toContain('Нет активных медиа-каналов');
      expect(t).toContain('Данные готовы к обучению модели');
    }
  });
  it('ключ true или не-булево значение оставляют колонку включённой, только false выключает', () => {
    const t = texts(res(five, sparse), { a_spend: true, b_spend: undefined, c_spend: 1 }).join(NL);
    expect(t).not.toContain('Нет активных медиа-каналов');
    expect(t).toContain('Данные готовы к обучению модели');
  });
  it('выключены ВСЕ медиа-колонки → ошибка «Нет активных медиа-каналов» (отказ остаётся честным)', () => {
    const allOff = Object.fromEntries(five.map((n) => [n, false]));
    const t = texts(res(five, sparse), allOff).join(NL);
    expect(t).toContain('Нет активных медиа-каналов');
    expect(t).not.toContain('Данные готовы к обучению модели');
  });
  it('validateInsights принимает карту шестым аргументом так же, как validateRolesInsights', () => {
    const viaRoles = validateRolesInsights(res(five, sparse), 'roi', 'bayesian', true, 0, { sparse_spend: false });
    const direct = validateInsights(res(five, sparse), 'roi', 'bayesian', true, 0, { sparse_spend: false });
    expect(direct).toEqual(viaRoles);
  });
  it('проводка: InsightsPanel передаёт в validateRolesInsights карту, а гейт шага считает медиа по ней же', () => {
    const src = readFileSync(resolve(HERE, '../lib/components/pipeline/InsightsPanel.svelte'), 'utf8');
    const lines = src.split(String.fromCharCode(10));
    const call = lines.find((l) => l.includes('return validateRolesInsights('));
    expect(call, 'вызов validateRolesInsights не найден').toBeDefined();
    expect(call).toContain('$modelChannelEnabled');
    const gate = lines.find((l) => /const mediaCount = cols\.filter/.test(l));
    expect(gate, 'подсчёт mediaCount в гейте шага не найден').toBeDefined();
    expect(gate).toContain('enabledMapNow');
    // К2-6: эффект признака ошибки шага ПОДПИСАН на карту (`$modelChannelEnabled` внутри
    // эффекта) и передаёт её в функцию; чтение через get() реакции на смену карты не даёт.
    const start = src.indexOf('syncStepLockAfterValidate(result');
    const effectStart = src.lastIndexOf('$effect(() => {', start);
    const effectEnd = src.indexOf('});', start);
    expect(effectStart).toBeGreaterThan(-1);
    // комментарии вырезаем: слово в комментарии подписки не даёт
    const effectBody = src.slice(effectStart, effectEnd).split(String.fromCharCode(10))
      .filter((l) => !l.trim().startsWith('//')).join(String.fromCharCode(10));
    expect(effectBody, 'эффект не читает $modelChannelEnabled – смена карты его не перезапустит').toMatch(/const enabledMap = \$modelChannelEnabled/);
    expect(effectBody).toMatch(/syncStepLockAfterValidate\(result,\s*enabledMap\)/);
    expect(src).toMatch(/function syncStepLockAfterValidate\(result,\s*enabledMap/);
  });
});

// ── Б-2 (круг 2): «достаточно» не спорит с предупреждением движка short_period ──

describe('Б-2: «достаточно для надёжной MMM» не печатается при short_period', () => {
  const SHORT = { type: 'short_period', message: 'Период данных ~59 дн. (< 1 года)', severity: 'warning' };
  /** @param {number} rows @param {string} freq @param {any[]} [warnings] */
  const res = (rows, freq, warnings = []) => ({
    columns: [{ name: 'sales', role: 'kpi' }, { name: 'БЮДЖЕТ_ТВ', role: 'media' }],
    file: { rows },
    detected: { date_frequency: freq },
    warnings,
  });
  const period = (/** @type {any} */ r) => validateKpiInsights(r).filter((i) => /наблюдени/.test(i.text));

  it('60 дневных с short_period → нет «достаточно», «приемлемо для пилота» и причина про срок', () => {
    const out = period(res(60, 'daily', [SHORT]));
    expect(out).toHaveLength(1);
    expect(out[0].text).not.toContain('достаточно');
    expect(out[0].text).toContain('приемлемо для пилота');
    expect(out[0].text).toContain('меньше года');
    expect(out[0].severity).toBe('info');
  });
  it('60 дневных без предупреждения – прежнее «достаточно»', () => {
    const out = period(res(60, 'daily'));
    expect(out[0].text).toContain('достаточно');
    expect(out[0].severity).toBe('success');
  });
  it('16 квартальных с short_period → нет «достаточно» (ветка «очень мало»)', () => {
    const out = period(res(16, 'quarterly', [SHORT]));
    expect(out[0].text).not.toContain('достаточно');
    expect(out[0].severity).toBe('warning');
  });
  it('предупреждение другого типа не влияет', () => {
    const out = period(res(60, 'daily', [{ type: 'high_correlation', message: 'x', severity: 'warning' }]));
    expect(out[0].text).toContain('достаточно');
  });
  it('нет поля warnings вовсе – прежнее поведение, без падения', () => {
    const r = res(60, 'daily');
    delete (/** @type {any} */ (r)).warnings;
    expect(period(r)[0].text).toContain('достаточно');
  });
});

// ── Д4 (доработка по приёмке): те же утверждения о надёжности в соседних ветках ──

describe('Д4: «надёжны» не печатается при вердикте «uncertain» (сходимость и сводка отчёта)', () => {
  /** @param {string | null} verdict @param {number} ratio */
  function conv(verdict, ratio = 12) {
    return {
      diagnostics: {
        metrics: { r_squared: 0.9, mape_pct: 4, r_hat_max: 1.0, divergences: 0, ratio, n_observations: 60, n_parameters: 20 },
        mqs: { score: 70, tier_label: 'Хорошее', tier: 'good' },
        ...(verdict ? { honesty_verdict: verdict } : {}),
      },
      channelParams: { OLV: {}, Banners: {}, Social: {} },
    };
  }
  const convergence = (/** @type {any[]} */ out) => out.find((i) => /Модель сошлась/.test(i.text));

  it('modelInsights: сошлась, но «uncertain» → «Выводы ориентировочные», без «надёжны»', () => {
    const c = convergence(modelInsights(conv('uncertain')));
    expect(c.text).toContain('Модель сошлась идеально');
    expect(c.text).toContain('Выводы ориентировочные');
    expect(`${c.text} ${c.tip}`).not.toMatch(/надёжн/);
  });
  it('modelInsights: «reliable» и без штампа – прежний текст', () => {
    for (const v of ['reliable', null]) {
      const c = convergence(modelInsights(conv(v)));
      expect(c.text).toContain('Результаты надёжны для оценки ROI и диапазонов');
      expect(c.tip).toContain('надёжно для оценки ROI');
    }
  });
  it('modelInsights: нехватка данных по-прежнему даёт «сошлась технически» (ветка isThin не тронута)', () => {
    const c = convergence(modelInsights(conv('uncertain', 2.7)));
    expect(c.text).toContain('Модель сошлась технически');
  });

  /** @param {string} verdict @param {'opt' | 'mod'} where */
  function report(verdict, where) {
    const mod = conv(where === 'mod' ? verdict : 'reliable');
    mod.diagnostics.mqs = { score: 80, tier_label: 'Хорошее', tier: 'good' };
    return reportInsights({
      mod,
      dec: { baseline_pct: 60, channels: [{ name: 'TV', contribution_pct: 40, roi: 2.1 }] },
      opt: { expected_lift_pct: 12, total_budget_money: 5_000_000, model_reliability: { verdict: where === 'opt' ? verdict : 'reliable', refused: false } },
    }).find((i) => /^🎯 Модель:/.test(i.text));
  }
  it('reportInsights: «uncertain» из оптимизации или диагностики → «Выводы ориентировочные», без «надёжны»', () => {
    for (const where of /** @type {const} */ (['opt', 'mod'])) {
      const h = report('uncertain', where);
      expect(h.text).toContain('Выводы ориентировочные.');
      expect(h.text).toContain('MQS 80');
      expect(h.severity).toBe('warning');
      expect(`${h.text} ${h.tip}`).not.toMatch(/надёжн|используйте выводы отчёта для бюджетных/);
    }
  });
  it('reportInsights: «reliable» – прежний текст', () => {
    const h = report('reliable', 'opt');
    expect(h.text).toContain('Результаты надёжны.');
    expect(h.severity).toBe('success');
    expect(h.tip).toContain('используйте выводы отчёта для бюджетных решений');
  });
});

// ── Б8 ────────────────────────────────────────────────────────────────────

describe('Б8: «план уже оптимален» не печатается при значимой перекладке', () => {
  const M = 1_000_000;
  /**
   * @param {Partial<{ lift: number, shift: number, total: number, extra: any }>} [o]
   * @returns {any}
   */
  function optRes({ lift = 0.3, shift = 21.7 * M, total = 1077.8 * M, extra = {} } = {}) {
    const rest = total - 400 * M - 300 * M;
    return {
      expected_lift_pct: lift,
      total_budget_money: total,
      channels: [
        { name: 'TV', current_spend: 400 * M, optimal_spend: 400 * M - shift },
        { name: 'OLV', current_spend: 300 * M, optimal_spend: 300 * M + shift },
        { name: 'OOH', current_spend: rest, optimal_spend: rest },
      ],
      ...extra,
    };
  }
  /** @param {any} opt */
  const reportText = (opt) => {
    const out = reportInsights({
      mod: { diagnostics: { metrics: { ratio: 12 }, mqs: { score: 80, tier_label: 'Хорошее', tier: 'good' } } },
      dec: { baseline_pct: 60, channels: [{ name: 'TV', contribution_pct: 40, roi: 2.1 }] },
      opt,
    });
    return out.filter((i) => /Оптимизация:/.test(i.text)).map((i) => `${i.text} ${i.tip ?? ''}`).join('\n');
  };

  it('прирост 0.3 % при перекладке 21.7 млн из 1 077.8 млн → «+0.3 %», слов «уже оптимален» нет', () => {
    const t = reportText(optRes());
    expect(t).toContain('+0.3%');
    expect(t).not.toContain('+0%');
    expect(t).not.toContain('уже оптимален');
  });
  it('перекладка меньше 1 % бюджета → «план уже оптимален» без ложного числа «+0%»', () => {
    const t = reportText(optRes({ shift: 5 * M }));
    expect(t).toContain('план уже оптимален');
    expect(t).not.toContain('+0.3%');
    expect(t).not.toContain('+0%');
  });
  it('прирост 0.4 % и перекладка меньше порога → в тексте нет «+0%»', () => {
    const t = reportText(optRes({ lift: 0.4, shift: 5 * M }));
    expect(t).toContain('🟰 Оптимизация: план уже оптимален в заданных рамках – значимой перекладки бюджета нет.');
    expect(t).not.toContain('+0%');
    expect(t).not.toContain('+0.4%');
  });
  it('расчёт не сошёлся / упор в ограничения / «сошёлся в текущем плане» → признак не выполнен', () => {
    // s62 (аудит К3-1, М2): «план уже оптимален» и «перекладки нет» – только когда расчёт
    // сошёлся; при отказе и упоре в ограничения – свой текст, перекладка в таблице остаётся.
    const notConv = reportText(optRes({ extra: { optimization_converged: false } }));
    expect(notConv).toContain('расчёт не сошёлся');
    expect(notConv).not.toContain('оптимален в заданных');
    expect(notConv).not.toContain('перекладки бюджета нет');
    const binding = reportText(optRes({ extra: { binding_constraints: ['TV'] } }));
    expect(binding).toContain('упирается в рамки Мин/Макс %');
    expect(binding).not.toContain('план уже оптимален');
    expect(binding).not.toContain('перекладки бюджета нет');
    expect(reportText(optRes({ extra: { converged_at_current: true } }))).toContain('план уже оптимален');
  });
  it('только наращивание / только сокращение – признак выполнен без порога (как у «Главной рекомендации»)', () => {
    const onlyScale = optRes({ shift: 1 * M });
    onlyScale.channels[0].optimal_spend = onlyScale.channels[0].current_spend;
    expect(optimizeShiftIsSignificant(onlyScale)).toBe(true);
    const t1 = reportText(onlyScale);
    expect(t1).toContain('+0.3%');
    expect(t1).not.toContain('уже оптимален');
    const onlyCut = optRes({ shift: 1 * M });
    onlyCut.channels[1].optimal_spend = onlyCut.channels[1].current_spend;
    expect(optimizeShiftIsSignificant(onlyCut)).toBe(true);
    expect(reportText(onlyCut)).not.toContain('уже оптимален');
  });
  it('ни сокращения, ни наращивания → признак не выполнен, текст «план уже оптимален»', () => {
    const opt = optRes();
    for (const ch of opt.channels) ch.optimal_spend = ch.current_spend;
    expect(optimizeShiftIsSignificant(opt)).toBe(false);
    expect(reportText(opt)).toContain('план уже оптимален');
  });
  it('и перекладка меньше порога, но «только наращивание» – порог не применяется', () => {
    // 0.5 млн из 1 077.8 млн (< 1 %) при двух сторонах – не значима; при одной стороне – значима
    const both = optRes({ shift: 0.5 * M });
    expect(optimizeShiftIsSignificant(both)).toBe(false);
    both.channels[0].optimal_spend = both.channels[0].current_spend;
    expect(optimizeShiftIsSignificant(both)).toBe(true);
  });
  it('граница: перекладка ровно 1 % значима, чуть меньше – нет', () => {
    const total = 1000 * M;
    const atLimit = optRes({ total, shift: total * OPTIMIZE_SHIFT_MIN_SHARE });
    const below = optRes({ total, shift: total * OPTIMIZE_SHIFT_MIN_SHARE * 0.99 });
    expect(optimizeShiftIsSignificant(atLimit)).toBe(true);
    expect(optimizeShiftIsSignificant(below)).toBe(false);
  });
  it('прирост выше 0.5 % не затронут: «почти оптимален» как раньше', () => {
    const t = reportText(optRes({ lift: 0.8 }));
    expect(t).toContain('план почти оптимален');
  });
  it('нулевой или отрицательный прирост при значимой перекладке: нет «оптимален» и нет положительного процента', () => {
    for (const lift of [0, -0.2]) {
      const t = reportText(optRes({ lift }));
      expect(t, `lift=${lift}`).toContain('прогнозный прирост не положителен');
      expect(t, `lift=${lift}`).not.toContain('оптимален');
      expect(t, `lift=${lift}`).not.toMatch(/\+\d/);
      // Б3-2: подсказка не утверждает «прирост небольшой» (прироста нет) и не зовёт менять план вслепую
      expect(t, `lift=${lift}`).not.toContain('прирост небольшой');
      expect(t, `lift=${lift}`).toContain('прогноз не обещает прироста');
    }
    // при положительном приросте подсказка прежняя
    expect(reportText(optRes({ lift: 0.3 }))).toContain('прирост небольшой, но перекладка есть');
  });
  it('нулевой прирост без значимой перекладки – прежний текст «план уже оптимален»', () => {
    const t = reportText(optRes({ lift: 0, shift: 1 * M }));
    expect(t).toContain('план уже оптимален');
  });
  it('сторож: порог совпадает с числом в OptimizeStep.svelte (читает исходник как текст)', () => {
    const src = readFileSync(resolve(HERE, '../lib/components/pipeline/OptimizeStep.svelte'), 'utf8');
    const m = /shiftAmount\s*\/\s*totalSpend\s*<\s*([0-9.]+)/.exec(src);
    expect(m, 'в OptimizeStep.svelte не найдено сравнение shiftAmount / totalSpend < N').not.toBeNull();
    expect(Number(m?.[1])).toBe(OPTIMIZE_SHIFT_MIN_SHARE);
  });
});
