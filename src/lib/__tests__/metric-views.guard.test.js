// @ts-nocheck — node-side тест (fs/path/process); svelte-check checkJs не имеет
// @types/node в scope. Логика проверяется через vitest, не через типы.
/**
 * INV-50 анти-рецидив греп-гард (2026-06-07).
 *
 * honesty-баг нечестного ratio/MQS всплывал ТРИЖДЫ, потому что одно число жило в
 * N расходящихся местах и пост-train дисплей читал оптимистичную метрику. Греп
 * «всех мест» ловит существующие N, но не будущий N+1. Этот гард — структурный:
 * единственный файл во всём `src/`, которому разрешён сырой доступ к
 * `.mqs.score` / `.metrics.ratio`, — это сам селектор `metric-views.js`. Любой
 * новый пост-train потребитель ОБЯЗАН ходить через mqsView/ratioView, иначе тест
 * падает на CI до мержа. Так N+1-й слой физически невозможен.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { mqsView, ratioView } from '../metric-views.js';

// vitest запускается из корня репо → src/ рядом. (import.meta.url под vite не
// file-scheme, поэтому берём cwd.)
const SRC_DIR = path.join(process.cwd(), 'src');

/** @param {string} dir @returns {string[]} */
function walk(dir) {
  /** @type {string[]} */
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name === '.svelte-kit') continue;
      out.push(...walk(p));
    } else if (/\.(js|svelte)$/.test(e.name)) {
      out.push(p);
    }
  }
  return out;
}

// `\bratio\b` исключает ratio_nominal/ratio_view; case-sensitive — displayMqs.score не ловится.
const RAW_ACCESS = /\.mqs\??\.score|\.metrics\??\.ratio\b/;
const ALLOWED = new Set(['metric-views.js']);

describe('INV-50 guard: пост-train MQS/ratio только через metric-views', () => {
  it('ни один файл src/ (кроме metric-views.js и тестов) не читает .mqs.score / .metrics.ratio напрямую', () => {
    /** @type {string[]} */
    const offenders = [];
    for (const f of walk(SRC_DIR)) {
      if (ALLOWED.has(path.basename(f))) continue;
      if (/__tests__|[.](test|spec)[.]/.test(f)) continue;
      const lines = fs.readFileSync(f, 'utf8').split('\n');
      lines.forEach((ln, i) => {
        const t = ln.trim();
        // пропускаем строки-комментарии (literal-путь в доке — не доступ)
        if (t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return;
        if (RAW_ACCESS.test(ln)) {
          offenders.push(`${path.relative(SRC_DIR, f)}:${i + 1}: ${t.slice(0, 90)}`);
        }
      });
    }
    expect(
      offenders,
      `Сырой пост-train доступ к MQS/ratio — заведи через mqsView/ratioView (metric-views.js):\n${offenders.join('\n')}`,
    ).toEqual([]);
  });
});

describe('mqsView', () => {
  it('null когда модель не обучена / нет mqs', () => {
    expect(mqsView(null)).toBeNull();
    expect(mqsView({})).toBeNull();
    expect(mqsView({ mqs: { score: NaN } })).toBeNull();
  });
  it('отдаёт честный backend score/tierLabel/thinnessCap', () => {
    const v = mqsView({ mqs: { score: 70, tier_label: 'Хорошее', thinness_cap: 70, color: '#3b82f6' } });
    expect(v).toEqual({ score: 70, tierLabel: 'Хорошее', thinnessCap: 70, color: '#3b82f6' });
  });
  it('thinnessCap = null когда cap не применён', () => {
    expect(mqsView({ mqs: { score: 88, tier_label: 'Отличное', thinness_cap: null } })?.thinnessCap).toBeNull();
  });
});

describe('ratioView', () => {
  it('приоритет — backend effective ratio (metrics.ratio), source=effective', () => {
    const v = ratioView({ metrics: { ratio: 2.4, ratio_nominal: 1.6 } }, 4.4);
    expect(v).toMatchObject({ ratio: 2.4, isThin: true, isVeryThin: false, nominal: 1.6, source: 'effective' });
  });
  it('media-ratio (fallback) НЕ вытесняет effective — честное число побеждает', () => {
    // honesty-инвариант: даже при оптимистичном fallback 4.4 показываем effective 2.4
    expect(ratioView({ metrics: { ratio: 2.4 } }, 4.4)?.ratio).toBe(2.4);
  });
  it('fallback используется ТОЛЬКО когда backend effective отсутствует, source=fallback', () => {
    const v = ratioView({ metrics: {} }, 4.4);
    expect(v).toMatchObject({ ratio: 4.4, source: 'fallback', isThin: false });
  });
  it('legacy-flat: diagnostics.ratio (без metrics) считается effective', () => {
    expect(ratioView({ ratio: 2.4 }, 9)?.source).toBe('effective');
  });
  it('isVeryThin при ratio < 2', () => {
    expect(ratioView({ metrics: { ratio: 1.5 } })?.isVeryThin).toBe(true);
  });
  it('null когда нет ни backend, ни fallback', () => {
    expect(ratioView({ metrics: {} }, null)).toBeNull();
    expect(ratioView(null)).toBeNull();
  });
});
