import { describe, it, expect } from 'vitest';
import { cancelledTailAction, insertBeforeActiveBubble } from './cancelled-run.js';

describe('хвост остановленной работы (находки внешнего аудита 2026-08-03)', () => {
  it('приписка показывается всегда, когда она есть', () => {
    // Номер осиротевшей работы — единственное, чем человек может назвать поддержке
    // занятое место среди одновременных. Решение НЕ зависит от состояния приёмника:
    // первая починка смотрела на `$isLoading` и воспроизводила сам дефект.
    expect(cancelledTailAction('работа 7f3 осталась на узле')).toBe('notice');
  });

  it('сказать нечего — молчим', () => {
    expect(cancelledTailAction('')).toBe('skip');
    expect(cancelledTailAction('   ')).toBe('skip');
    expect(cancelledTailAction(undefined)).toBe('skip');
    expect(cancelledTailAction(null)).toBe('skip');
  });

  it('решение не принимает НИ ОДНОГО признака состояния приёмника', () => {
    // Сторож на класс дефекта: у функции ровно один вход — приписка. Появится
    // второй параметр «идёт ли работа» — тест покраснеет, и это правильно.
    expect(cancelledTailAction.length).toBe(1);
  });
});

describe('служебная строка встаёт перед активным пузырём', () => {
  const note = { role: 'system', content: 'работа 7f3 осталась на узле' };

  it('во время живого ответа — ПЕРЕД ним, а не после', () => {
    // 🔴 Облачный путь шлёт поток накопительно: каждое событие несёт весь текст с
    // начала. Строка, приписанная в конец, рвёт склейку — следующий кусок видит
    // чужую роль последней и заводит второй пузырь с полным текстом.
    const lenta = [
      { role: 'user', content: 'вопрос' },
      { role: 'assistant', content: 'ответ печатается' },
    ];
    const out = insertBeforeActiveBubble(lenta, note);
    expect(out.map(m => m.role)).toEqual(['user', 'system', 'assistant']);
    expect(out[out.length - 1].content).toBe('ответ печатается');
  });

  it('когда ответа ещё нет — в конец', () => {
    const lenta = [{ role: 'user', content: 'вопрос' }];
    expect(insertBeforeActiveBubble(lenta, note).map(m => m.role)).toEqual(['user', 'system']);
  });

  it('на пустой ленте не падает', () => {
    expect(insertBeforeActiveBubble([], note)).toEqual([note]);
  });

  it('исходную ленту не меняет', () => {
    const lenta = [{ role: 'assistant', content: 'ответ' }];
    insertBeforeActiveBubble(lenta, note);
    expect(lenta).toHaveLength(1);
  });
});
