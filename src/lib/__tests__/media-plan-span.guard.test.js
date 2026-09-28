// @ts-nocheck — node-side тест (fs/path/process): svelte-check checkJs не имеет
// @types/node в scope, логика проверяется через vitest, не через типы.
/**
 * Сторож L2 (s55): срок найденного медиаплана на экране – человеческим видом,
 * как в отчёте («дек 2024 – авг 2025»), а не сырыми метками движка
 * («2025-W01 – 2025-W32»). Помощник проверяет period-format.test.js; этот сторож
 * ловит стык – экран перестал звать помощник и снова печатает period_labels.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SCREENS = [
  'src/lib/components/pipeline/PlanningStep.svelte',
  'src/lib/components/pipeline/ValidateStepV13.svelte',
];

describe('экраны медиаплана выводят срок через formatMediaPlanSpan', () => {
  for (const rel of SCREENS) {
    const src = readFileSync(path.join(process.cwd(), rel), 'utf-8');
    it(`${rel}: сырые края period_labels не печатаются`, () => {
      expect(src).not.toMatch(/period_labels\[0\]\}\s*–/);
      expect(src).not.toMatch(/granularity === 'week'/);
    });
    it(`${rel}: срок и число периодов – через помощники period-format.js`, () => {
      expect(src).toMatch(/\(\{formatMediaPlanSpan\((mpData|mp)\)\}\)/);
      expect(src).toMatch(/ruPlanPeriodsForm\((mpData|mp)\.n_future_periods, (mpData|mp)\.granularity\)/);
    });
  }
});
