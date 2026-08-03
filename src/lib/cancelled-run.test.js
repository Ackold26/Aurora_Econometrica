import { describe, it, expect } from 'vitest';
import { cancelledTailAction } from './cancelled-run.js';

describe('хвост остановленной работы (находка внешнего аудита 2026-08-03)', () => {
  it('человек смотрит на остановленный ответ — текст применим', () => {
    expect(cancelledTailAction(false, 'работа 7f3 осталась на узле')).toBe('apply');
    expect(cancelledTailAction(false, '')).toBe('apply');
  });

  it('идёт другая работа — показываем только приписку, чужой ответ не трогаем', () => {
    // Ровно найденный случай: человек остановил работу и сразу спросил дальше,
    // а хвост первой доехал уже во время второй.
    expect(cancelledTailAction(true, 'работа 7f3 осталась на узле')).toBe('notice');
  });

  it('идёт другая работа, а сказать нечего — молчим', () => {
    expect(cancelledTailAction(true, '')).toBe('skip');
    expect(cancelledTailAction(true, '   ')).toBe('skip');
    expect(cancelledTailAction(true, undefined)).toBe('skip');
    expect(cancelledTailAction(true, null)).toBe('skip');
  });

  it('приписка никогда не теряется, пока идёт работа', () => {
    // Номер осиротевшей работы — единственное, чем человек может назвать
    // поддержке занятое место среди одновременных. Потерять его нельзя.
    expect(cancelledTailAction(true, 'работа 7f3 осталась на узле')).not.toBe('skip');
  });
});
