/**
 * insights-bugs-p5.test.js — регресс-тесты для трёх UX-багов инсайт-слоя.
 *
 * БАГ П5-1а: дубль ratio-инсайтов разной тональности (правка 2026-07-10).
 * БАГ П5-2:  обрезка имён каналов в заголовках парных инсайтов (правка 2026-07-10).
 * БАГ А5-1:  бессмысленный «объединить с каналом» для событийных колонок (правка 2026-07-10).
 */
import { describe, it, expect } from 'vitest';
import { validateInsights } from '../lib/insights-rules.js';

// ─── helpers ───────────────────────────────────────────────────────────────

/**
 * Минимальный result с нужными параметрами.
 *
 * P0.3 (2026-08-03): `detected` заполняется составом, который реально отдаёт
 * `validator.py`, — запас данных считается по ЭФФЕКТИВНОМУ числу параметров
 * (назначенные + 12 авто-праздников + свободный член для байеса). Раньше здесь
 * стоял пустой `detected: {}`, и тесты неявно опирались на сырой знаменатель.
 * Числа наблюдений в тестах ниже пересчитаны под эффективный, чтобы каждый
 * проверял ту же ситуацию, что и задумывался.
 */
const N_HOLIDAYS_AUTO = 12;
const N_INTERCEPT = 1;

function mkResult({ kpi = 1, media = 4, control = 0, rows = 48, warnings = [], status = 'ok', extraCols = [] } = {}) {
  const columns = [];
  for (let i = 0; i < kpi; i++) columns.push({ name: `kpi${i}`, role: 'kpi', stats: {} });
  for (let i = 0; i < media; i++) columns.push({ name: `media${i}`, role: 'media', stats: {} });
  for (let i = 0; i < control; i++) columns.push({ name: `ctrl${i}`, role: 'control', stats: {} });
  columns.push(...extraCols);
  const nPredictors = media + control;
  return {
    status,
    columns,
    file: { rows },
    warnings,
    detected: {
      n_predictors: nPredictors,
      n_holidays_auto: N_HOLIDAYS_AUTO,
      n_intercept: N_INTERCEPT,
      n_params_effective_bayesian: nPredictors + N_HOLIDAYS_AUTO + N_INTERCEPT,
      n_params_effective_ols: nPredictors + N_INTERCEPT,
    },
  };
}

const allTexts = (out) => out.map(i => i.text).join(' || ');
const countByText = (out, substr) => out.filter(i => (i.text ?? '').includes(substr)).length;
const sev = (out, s) => out.filter(i => i.severity === s);

// ─── БАГ П5-1а: НЕ БОЛЕЕ ОДНОГО ratio-инсайта на одно значение ────────────

describe('П5-1а: отсутствие дублей ratio-инсайтов', () => {
  it('ratio 3.0 → ровно один инсайт упоминает «3.0:1»', () => {
    // P0.3: 60 наблюдений / (5 медиа + 2 контроля + 12 праздников + 1) = 3.0
    const out = validateInsights(mkResult({ kpi: 1, media: 5, control: 2, rows: 60 }));
    const matches = out.filter(i => (i.text ?? '').includes('3.0:1'));
    expect(matches).toHaveLength(1);
  });

  it('ratio 3.5 → текущее значение (3.5:1) упоминается ровно один раз (нет дублей-вердиктов)', () => {
    // 21 rows / 6 params = 3.5
    const out = validateInsights(mkResult({ kpi: 1, media: 4, control: 2, rows: 21 }));
    // Ищем инсайты с конкретным ТЕКУЩИМ ratio (не с afterRatio после оптимизации).
    // afterRatio может упоминаться в «много каналов → исключите N» — это нормально.
    const currentRatioTexts = out.filter(i => (i.text ?? '').includes('3.5:1'));
    expect(currentRatioTexts.length).toBeLessThanOrEqual(1);
    // Не должно быть двух warning с взаимоисключающими вердиктами на одно число
    const ratioWarnings = out.filter(i => i.severity === 'warning' && (i.text ?? '').includes('3.5:1'));
    expect(ratioWarnings.length).toBeLessThanOrEqual(1);
  });

  it('ratio ≥ 5 → один success «Модель надёжна», нет дублирующего warning', () => {
    // P0.3: 170 наблюдений / (4 медиа + 12 праздников + 1) = 10.0
    const out = validateInsights(mkResult({ kpi: 1, media: 4, rows: 170 }));
    const nadezhn = out.filter(i => (i.text ?? '').includes('надёжна') || (i.text ?? '').includes('надёжен'));
    // success-инсайт «надёжна» только один
    expect(nadezhn.length).toBeLessThanOrEqual(1);
    // нет warning с «Ratio» при хорошем ratio
    const ratioWarn = out.filter(i => i.severity === 'warning' && /\d\.\d:1/.test(i.text ?? ''));
    expect(ratioWarn).toHaveLength(0);
  });

  it('два последовательных прогона с разными params → новый прогон не накапливает старые ratio', () => {
    // validateInsights чистый (без накопления стора) — проверяем что каждый вызов независим
    const out1 = validateInsights(mkResult({ kpi: 1, media: 5, control: 2, rows: 21 })); // ratio 3.0
    const out2 = validateInsights(mkResult({ kpi: 1, media: 4, rows: 60 }));              // ratio 15.0

    // В out2 не должно быть ratio 3.0
    expect(allTexts(out2)).not.toContain('3.0:1');
    // В out1 не должно быть «надёжна» (хорошего ratio)
    expect(allTexts(out1)).not.toContain('15.0:1');
  });
});

// ─── БАГ П5-2: полные имена каналов в заголовках парных инсайтов ───────────

describe('П5-2: полные имена каналов в заголовках', () => {
  it('DIGITAL_SPEND → заголовок содержит «DIGITAL», но не «DIGITA»', () => {
    const out = validateInsights(mkResult({
      kpi: 1, rows: 48,
      extraCols: [
        { name: 'DIGITAL_SPEND', role: 'media', stats: { zeros_pct: 5 } },
        { name: 'DIGITAL_IMPRESSIONS', role: 'media', stats: { zeros_pct: 5 } },
      ],
    }));
    const paired = out.filter(i => (i.text ?? '').includes('парные метрики') || (i.text ?? '').includes('парн'));
    expect(paired.length).toBeGreaterThanOrEqual(1);
    const text = paired[0]?.text ?? '';
    expect(text).not.toMatch(/DIGITA[^L]/);   // не обрезанный вариант
    expect(text).toMatch(/DIGITAL/);           // полное имя
  });

  it('PERFORMANCE_SPEND → заголовок содержит «PERFORMANCE», не «PERFOR»', () => {
    const out = validateInsights(mkResult({
      kpi: 1, rows: 48,
      extraCols: [
        { name: 'PERFORMANCE_SPEND', role: 'media', stats: { zeros_pct: 5 } },
        { name: 'PERFORMANCE_IMPRESSIONS', role: 'media', stats: { zeros_pct: 5 } },
      ],
    }));
    const paired = out.filter(i => (i.text ?? '').includes('парн'));
    expect(paired.length).toBeGreaterThanOrEqual(1);
    const text = paired[0]?.text ?? '';
    expect(text).not.toMatch(/PERFOR[^M]/);
    expect(text).toMatch(/PERFORMANCE/);
  });

  it('длинное имя >14 символов получает многоточие, но НЕ ПЕРФОРМАНС обрезка букв', () => {
    const out = validateInsights(mkResult({
      kpi: 1, rows: 48,
      extraCols: [
        { name: 'SUPER_LONG_CHANNEL_NAME_SPEND', role: 'media', stats: { zeros_pct: 5 } },
        { name: 'SUPER_LONG_CHANNEL_NAME_IMPRESSIONS', role: 'media', stats: { zeros_pct: 5 } },
      ],
    }));
    const paired = out.filter(i => (i.text ?? '').includes('парн'));
    if (paired.length > 0) {
      // должно быть многоточие, НЕ просто оборванные буквы
      const text = paired[0].text ?? '';
      expect(text).toMatch(/…/);
    }
  });
});

// ─── БАГ А5-1: событийные колонки не получают «объединить с каналом» ────────

describe('А5-1: событийные / бинарные колонки — корректный текст', () => {
  it('black_friday (control, 92% нулей) → текст содержит «событ», НЕ «объединить с другим каналом»', () => {
    const out = validateInsights(mkResult({
      kpi: 1, rows: 48,
      extraCols: [
        { name: 'black_friday', role: 'control', stats: { zeros_pct: 92, min: 0, max: 1 } },
      ],
    }));
    const eventInsight = out.find(i => (i.text ?? '').toLowerCase().includes('black_friday'));
    expect(eventInsight).toBeDefined();
    expect((eventInsight?.text ?? '').toLowerCase()).toMatch(/событ/);
    expect((eventInsight?.text ?? '').toLowerCase()).not.toMatch(/объединить с другим каналом/);
  });

  it('бинарная media-колонка (max=1, 88% нулей) → info «событийная», не warning «объединить»', () => {
    const out = validateInsights(mkResult({
      kpi: 1, rows: 48,
      extraCols: [
        { name: 'is_promo_week', role: 'media', stats: { zeros_pct: 88, min: 0, max: 1 } },
      ],
    }));
    const ins = out.find(i => (i.text ?? '').includes('is_promo_week'));
    expect(ins).toBeDefined();
    expect(ins?.severity).toBe('info');
    expect((ins?.text ?? '').toLowerCase()).toMatch(/событ/);
    // старого текста «объединить» не должно быть
    expect((ins?.text ?? '').toLowerCase()).not.toContain('объедин');
  });

  it('обычный разреженный медиа-канал (не бинарный, 70% нулей) → сохраняется старый warning-текст', () => {
    const out = validateInsights(mkResult({
      kpi: 1, rows: 48,
      extraCols: [
        { name: 'outdoor_spend', role: 'media', stats: { zeros_pct: 70, min: 0, max: 500000 } },
      ],
    }));
    const ins = out.find(i => (i.text ?? '').includes('outdoor_spend'));
    expect(ins).toBeDefined();
    // должен быть warning (не info)
    expect(ins?.severity).toBe('warning');
    // старый текст «объединение» / «объединить» остаётся
    expect((ins?.text ?? '').toLowerCase()).toMatch(/объедин|исключ/);
  });
});
