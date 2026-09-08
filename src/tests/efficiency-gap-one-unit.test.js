/**
 * Живой прогон 08.09 (ЧИСЛА-1): одно значение `efficiency_gap = -38.5` показывалось на
 * ОДНОМ экране «Декомпозиция» тремя формами и двумя единицами сразу — подсказка
 * «-38 пп», главная рекомендация «-39%» (округление до целых), таблица «-38.5%».
 *
 * Величина — разность двух долей (доля эффекта минус доля расхода), её единица —
 * процентные пункты; «%» для неё неверен. Сторож держит два свойства: формат один
 * (функция) и в местах отрисовки этой величины нет собственных «%».
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { formatEfficiencyGap } from '$lib/format-numbers.js';

/** Экраны, показывающие разрыв канала пользователю. */
const RENDERERS = [
  'src/lib/components/pipeline/DecomposeStep.svelte',
  'src/lib/components/pipeline/ChannelComparisonChart.svelte',
  'src/lib/components/pipeline/ExpertDecomposePanel.svelte',
];

describe('разрыв канала — одна единица и одно округление', () => {
  it('формат один: знак, один знак после запятой, единица «пп»', () => {
    expect(formatEfficiencyGap(-38.5)).toBe('-38.5 пп');
    expect(formatEfficiencyGap(31.6)).toBe('+31.6 пп');
    expect(formatEfficiencyGap(0)).toBe('0.0 пп');
    expect(formatEfficiencyGap(null)).toBe('-');
    expect(formatEfficiencyGap(Number.NaN)).toBe('-');
  });

  it('«%» для этой величины не используется: -38.5 не превращается ни в «-39%», ни в «-38.5%»', () => {
    const s = formatEfficiencyGap(-38.5);
    expect(s).not.toContain('%');
    expect(s).not.toContain('-39');
  });

  it('экраны показывают разрыв только через общий формат, без собственных «%»', () => {
    for (const path of RENDERERS) {
      const src = readFileSync(path, 'utf-8');
      // Отрисовка значения разрыва со своим знаком процента — ровно то, что развело
      // единицы по трём местам одного экрана.
      const ownPercent = [
        /\{ch\.efficiency_gap[^}]*\}%/,          // ячейка таблицы «Детализация по каналам»
        /efficiency_gap\.toFixed\(\d\)\}%/,      // текст главной рекомендации
        /\$\{sign\}\$\{gap\}%/,                  // подсказка графика сравнения
        /fmtPct\(row\.gap\)/,                    // экспертная таблица
      ];
      for (const re of ownPercent) {
        expect(src, `${path}: разрыв отрисован в обход общего формата (${re})`).not.toMatch(re);
      }
    }
  });
});
