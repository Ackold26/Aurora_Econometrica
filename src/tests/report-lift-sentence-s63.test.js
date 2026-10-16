/**
 * s63 (№15): ложное «прирост ≈0% – план уже оптимален» в сводке и тексте отчёта.
 *
 * `ReportStep.svelte` печатал это при `lift ≤ 0.5` без проверки, сошёлся ли расчёт,
 * упёрся ли он в рамки Мин/Макс % и значима ли перекладка. Теперь сводка («Результаты»)
 * и блок «Как интерпретировать» берут формулировки из `optimizeFlatLiftVerdict`
 * (`insights-rules.js`) – из того же места, что панель выводов (`reportInsights`).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { modelData, decomposeData, optimizeData, activeProjectId } from '$lib/project-state.js';
import ReportStep from '$lib/components/pipeline/ReportStep.svelte';
import { optimizeFlatLiftVerdict, optimizeNotConvergedVerdict, reportInsights } from '$lib/insights-rules.js';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
vi.mock('@tauri-apps/plugin-opener', () => ({ openPath: vi.fn() }));
vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: MockEChartBase } = await import('./__mocks__/MockEChartBase.svelte');
  return { default: MockEChartBase };
});

const M = 1_000_000;

/**
 * Результат оптимизации. По умолчанию: перекладка 21.7 млн из 1 077.8 млн (значима).
 * `shift: 0` – распределение не меняется.
 * @param {Partial<{ lift: number|null, shift: number, extra: any }>} [o]
 * @returns {any}
 */
function optRes({ lift = 0.3, shift = 21.7 * M, extra = {} } = {}) {
  const total = 1077.8 * M;
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

const NOT_CONVERGED = 'расчёт не сошёлся – вывод об оптимальности плана сделать нельзя';
const BINDING = 'в заданных ограничениях по каналам значимого прироста нет – расчёт упирается в рамки Мин/Макс %';
const OPTIMAL = 'план уже оптимален в заданных рамках – значимой перекладки бюджета нет';
const SHIFT_NOT_POSITIVE = 'расчёт предлагает изменить распределение бюджета, но прогнозный прирост не положителен';

describe('optimizeFlatLiftVerdict: ветки малого прироста', () => {
  it('расчёт не сошёлся → «не сошёлся», совет не менять план, «оптимален» нет', () => {
    const v = optimizeFlatLiftVerdict(optRes({ lift: 0.2, extra: { optimization_converged: false } }), 0.2);
    expect(v?.kind).toBe('not_converged');
    expect(v?.severity).toBe('warning');
    expect(v?.text).toContain(NOT_CONVERGED);
    expect(v?.summary).toContain('не меняйте план по этому расчёту');
    expect(`${v?.text} ${v?.tip}`).not.toContain('уже оптимален');
  });

  it('и не сошёлся, и упор в рамки → «не сошёлся» (отказ важнее упора)', () => {
    const v = optimizeFlatLiftVerdict(
      optRes({ lift: 0.2, extra: { optimization_converged: false, binding_constraints: true } }),
      0.2,
    );
    expect(v?.kind).toBe('not_converged');
  });

  it('упор в рамки Мин/Макс % → свой текст, «оптимален» нет', () => {
    const v = optimizeFlatLiftVerdict(optRes({ lift: 0.2, extra: { binding_constraints: true } }), 0.2);
    expect(v?.kind).toBe('binding');
    expect(v?.text).toContain(BINDING);
    expect(`${v?.text} ${v?.tip}`).not.toContain('уже оптимален');
  });

  it('расчёт стоит в текущей точке (converged_at_current), перекладки нет → «оптимален в заданных рамках»', () => {
    const v = optimizeFlatLiftVerdict(optRes({ lift: 0.1, shift: 0, extra: { converged_at_current: true } }), 0.1);
    expect(v?.kind).toBe('optimal');
    expect(v?.text).toContain(OPTIMAL);
  });

  it('converged_at_current при заметной перекладке в таблице – «оптимален» не говорим', () => {
    const v = optimizeFlatLiftVerdict(optRes({ lift: 0.1, extra: { converged_at_current: true } }), 0.1);
    // признак значимости перекладки выключен текущей точкой, поэтому ветка «оптимален» –
    // как в панели выводов (dfe15c91): её текст не должен обещать большего, чем «в заданных рамках»
    expect(v?.kind).toBe('optimal');
    expect(v?.text).toContain('в заданных рамках');
  });

  it('значимая перекладка при нулевом приросте → «прогнозный прирост не положителен», без «оптимален» и без «+N»', () => {
    const v = optimizeFlatLiftVerdict(optRes({ lift: 0 }), 0);
    expect(v?.kind).toBe('shift');
    expect(v?.text).toContain(SHIFT_NOT_POSITIVE);
    expect(`${v?.text} ${v?.tip}`).not.toContain('оптимален');
    expect(`${v?.text} ${v?.tip}`).not.toMatch(/\+\d/);
    expect(v?.tip).toContain('прогноз не обещает прироста');
    expect(v?.tip).not.toContain('прирост небольшой');
  });

  it('значимая перекладка при положительном малом приросте → «+0.3%»', () => {
    const v = optimizeFlatLiftVerdict(optRes({ lift: 0.3 }), 0.3);
    expect(v?.kind).toBe('shift');
    expect(v?.text).toBe('Оптимизация: +0.3% при изменении распределения бюджета.');
  });

  it('отрицательный прирост: в тексте нет «≈0» и «0%», ветки по признакам расчёта', () => {
    const cases = [
      [optRes({ lift: -1.2, extra: { optimization_converged: false } }), 'not_converged'],
      [optRes({ lift: -1.2, extra: { binding_constraints: true } }), 'binding'],
      [optRes({ lift: -1.2 }), 'shift'],
    ];
    for (const [opt, kind] of cases) {
      const v = optimizeFlatLiftVerdict(opt, -1.2);
      expect(v?.kind).toBe(kind);
      const all = `${v?.text} ${v?.tip} ${v?.summary}`;
      expect(all).not.toContain('≈0');
      expect(all).not.toMatch(/[+-]?\d+(\.\d+)?\s*%/);
    }
  });

  it('optimizeNotConvergedVerdict: только при optimization_converged === false, при любом приросте', () => {
    expect(optimizeNotConvergedVerdict(optRes())).toBeNull();
    expect(optimizeNotConvergedVerdict({ optimization_converged: true })).toBeNull();
    expect(optimizeNotConvergedVerdict(null)).toBeNull();
    const v = optimizeNotConvergedVerdict({ optimization_converged: false });
    expect(v?.kind).toBe('not_converged');
    expect(v?.text).toContain(NOT_CONVERGED);
    expect(optimizeFlatLiftVerdict({ optimization_converged: false }, 0.1)?.text).toBe(v?.text);
  });

  it('lift = null и lift > 0.5 – функция молчит (там свои ветки у вызывающего)', () => {
    expect(optimizeFlatLiftVerdict(optRes(), null)).toBeNull();
    expect(optimizeFlatLiftVerdict(optRes(), undefined)).toBeNull();
    expect(optimizeFlatLiftVerdict(optRes({ lift: 0.8 }), 0.8)).toBeNull();
    expect(optimizeFlatLiftVerdict(optRes({ lift: 0.5 }), 0.5)).not.toBeNull();
  });

  it('панель выводов (reportInsights) берёт ровно те же тексты', () => {
    const cases = [
      optRes({ lift: 0.2, extra: { optimization_converged: false } }),
      optRes({ lift: 0.2, extra: { binding_constraints: true } }),
      optRes({ lift: 0.2, shift: 0 }),
      optRes({ lift: 0.3 }),
      optRes({ lift: -0.4 }),
    ];
    for (const opt of cases) {
      const v = optimizeFlatLiftVerdict(opt, opt.expected_lift_pct);
      const out = reportInsights({
        mod: { diagnostics: { metrics: { ratio: 12 }, mqs: { score: 80, tier_label: 'Хорошее', tier: 'good' } } },
        dec: { baseline_pct: 60, channels: [{ name: 'TV', contribution_pct: 40, roi: 2.1 }] },
        opt,
      }).filter((i) => /Оптимизация:/.test(i.text));
      expect(out).toHaveLength(1);
      expect(out[0].text).toBe(`${v?.icon} ${v?.text}`);
      expect(out[0].tip).toBe(v?.tip);
      expect(out[0].severity).toBe(v?.severity);
    }
  });
});

describe('ReportStep: сводка и текст отчёта при малом приросте', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    vi.mocked(invoke).mockResolvedValue(null);
    activeProjectId.set(null);
    modelData.set({
      diagnostics: {
        mqs: { score: 82, tier: 'good' },
        metrics: { r_squared: 0.9, mape_pct: 5.0, r_hat_max: 1.01, divergences: 0, ratio: 5.0 },
      },
      channelParams: { TV: {} },
      picklePath: 'x',
      normalization: null,
    });
    decomposeData.set({
      baseline_pct: 40,
      channels: [{ name: 'TV', spend: 1_000_000, contribution: 100, contribution_pct: 100, roi: 1.5, efficiency_gap: 0 }],
    });
  });

  /** @param {any} opt */
  async function openTexts(opt) {
    optimizeData.set(opt);
    render(ReportStep);
    await fireEvent.click(screen.getByRole('button', { name: /Сопроводительный текст для письма/ }));
    const cover = screen.getByText(/Главный драйвер/).closest('.cover-content')?.textContent ?? '';
    await fireEvent.click(screen.getByRole('button', { name: /Как интерпретировать модель и результаты/ }));
    const interp = screen.getByText(/Главный медиа-драйвер/).closest('.info-body')?.textContent ?? '';
    return { cover, interp };
  }

  it('расчёт не сошёлся: ни в сводке, ни в тексте нет «план уже оптимален»; совет не менять план', async () => {
    const { cover, interp } = await openTexts(optRes({ lift: 0.2, extra: { optimization_converged: false } }));
    for (const t of [cover, interp]) {
      expect(t).toContain(NOT_CONVERGED);
      expect(t).not.toContain('уже оптимален');
      expect(t).not.toContain('≈0');
    }
    expect(cover).toContain('не меняйте план по этому расчёту');
    expect(interp).toContain('не меняйте план по этому расчёту');
  });

  it('упор в рамки: «упирается в рамки Мин/Макс %», «оптимален» нет', async () => {
    const { cover, interp } = await openTexts(optRes({ lift: 0.2, extra: { binding_constraints: true } }));
    for (const t of [cover, interp]) {
      expect(t).toContain(BINDING);
      expect(t).not.toContain('уже оптимален');
      expect(t).not.toContain('≈0');
    }
  });

  it('значимого сдвига нет, расчёт сошёлся: «план уже оптимален в заданных рамках»', async () => {
    const { cover, interp } = await openTexts(optRes({ lift: 0.1, shift: 0 }));
    for (const t of [cover, interp]) {
      expect(t).toContain(OPTIMAL);
      expect(t).not.toContain('≈0');
    }
  });

  it('отрицательный прирост: нет «≈0%», нет «план уже оптимален», текст про неположительный прогноз', async () => {
    const { cover, interp } = await openTexts(optRes({ lift: -1.2 }));
    for (const t of [cover, interp]) {
      expect(t).toContain(SHIFT_NOT_POSITIVE);
      expect(t).not.toContain('≈0');
      expect(t).not.toContain('уже оптимален');
    }
  });

  it('отрицательный прирост и несошедшийся расчёт: «не сошёлся»', async () => {
    const { cover, interp } = await openTexts(optRes({ lift: -1.2, extra: { optimization_converged: false } }));
    expect(cover).toContain(NOT_CONVERGED);
    expect(interp).toContain(NOT_CONVERGED);
  });

  it('регрессия: прирост 0.8 % и 6 % – прежние тексты', async () => {
    const a = await openTexts(optRes({ lift: 0.8 }));
    expect(a.cover).toContain('Оптимизация: +0.8% - план близок к оптимальному.');
    expect(a.interp).toContain('Прирост +0.8% - план близок к оптимальному. Крупных неэффективностей нет.');
  });

  it('регрессия: прирост 6 % – «обещает +6.0% KPI»', async () => {
    const b = await openTexts(optRes({ lift: 6 }));
    expect(b.cover).toContain('Оптимизация обещает +6.0% KPI при текущем бюджете.');
    expect(b.interp).toContain('Оптимизация даст умеренный прирост: +6.0% KPI.');
  });

  it('lift = null: о приросте оптимизации не говорится вовсе', async () => {
    const { cover, interp } = await openTexts(optRes({ lift: null }));
    expect(cover).not.toContain('Оптимизация:');
    expect(interp).not.toContain('Оптимизация:');
  });
  /** @param {any} opt */
  async function faqText(opt) {
    optimizeData.set(opt);
    render(ReportStep);
    await fireEvent.click(screen.getByRole('button', { name: /Часто задаваемые вопросы по этой модели/ }));
    const q = screen.getByText(/модель не нашла как улучшить план|Прогнозный прирост оптимизации отрицателен/);
    return q.closest('.faq-item')?.textContent ?? '';
  }

  it('FAQ: расчёт не сошёлся – нет «план уже близок к оптимальному», есть совет не менять план', async () => {
    const t = await faqText(optRes({ lift: 0.2, extra: { optimization_converged: false } }));
    expect(t).toContain('расчёт не сошёлся');
    expect(t).toContain('не меняйте план по этому расчёту');
    expect(t).not.toContain('близок к оптимальному');
    expect(t).not.toContain('уже оптимален');
  });

  it('FAQ: упор в рамки – про рамки Мин/Макс %, без «план уже оптимален»', async () => {
    const t = await faqText(optRes({ lift: 0.2, extra: { binding_constraints: true } }));
    expect(t).toContain('рамки Мин/Макс %');
    expect(t).toContain('оптимальность плана этим не доказана');
    expect(t).not.toContain('близок к оптимальному');
    expect(t).not.toContain('уже оптимален');
  });

  it('FAQ: значимого сдвига нет, расчёт сошёлся – «в этих рамках уже оптимален»', async () => {
    const t = await faqText(optRes({ lift: 0.1, shift: 0 }));
    expect(t).toContain('план в этих рамках уже оптимален');
    expect(t).not.toContain('близок к оптимальному');
  });

  it('FAQ: значимая перекладка при малом приросте – «это не план уже оптимален»', async () => {
    const t = await faqText(optRes({ lift: 0.3 }));
    expect(t).toContain('это не «план уже оптимален»');
    expect(t).not.toContain('близок к оптимальному');
  });

  it('FAQ: отрицательный прирост – свой вопрос без «≈0%»', async () => {
    const t = await faqText(optRes({ lift: -1.2 }));
    expect(t).toContain('Прогнозный прирост оптимизации отрицателен');
    expect(t).not.toContain('≈0');
    expect(t).toContain('не положителен');
  });

  it('FAQ: прирост ровно 0 – вопрос прежний (не про «отрицателен»)', async () => {
    const t = await faqText(optRes({ lift: 0, shift: 0 }));
    expect(t).toContain('модель не нашла как улучшить план');
    expect(t).not.toContain('отрицателен');
  });

  it('FAQ: прирост выше 0.5 % – вопроса про «Lift ≈0%» нет', async () => {
    optimizeData.set(optRes({ lift: 0.8 }));
    render(ReportStep);
    await fireEvent.click(screen.getByRole('button', { name: /Часто задаваемые вопросы по этой модели/ }));
    expect(screen.queryByText(/модель не нашла как улучшить план/)).toBeNull();
  });

  it('база доминирует (прирост тонет в базе), расчёт не сошёлся: нет «реально улучшает медиа-отдачу», есть «не сошёлся»', async () => {
    const { interp } = await openTexts(optRes({ lift: 1.0, extra: { media_only_lift_pct: 5, optimization_converged: false } }));
    expect(interp).toContain(NOT_CONVERGED);
    expect(interp).toContain('не меняйте план по этому расчёту');
    expect(interp).not.toContain('реально улучшает медиа-отдачу');
    expect(interp).not.toContain('органическая база доминирует');
  });

  it('база доминирует, расчёт сошёлся: прежний текст про органическую базу', async () => {
    const { interp } = await openTexts(optRes({ lift: 1.0, extra: { media_only_lift_pct: 5 } }));
    expect(interp).toContain('Итоговый прирост KPI ≈1.0%, но эффективность медиа растёт на +5.0%');
    expect(interp).toContain('органическая база доминирует');
    expect(interp).toContain('перераспределение каналов реально улучшает медиа-отдачу');
    expect(interp).not.toContain('расчёт не сошёлся');
  });
});
