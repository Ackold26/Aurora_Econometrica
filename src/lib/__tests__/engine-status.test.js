/**
 * Модуль состояния движка (`engine-status.js`): честный подвал.
 * Логика ожидания вынесена из `pipeline/+layout.svelte`, потому что проект
 * рендер-тесты компонентов обходит (см. `src/tests/nav2-footer-gate.test.js`).
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { ENGINE, engineLabel, waitEngineReady } from '../engine-status.js';

/**
 * invoke, отвечающий по очереди; после конца очереди повторяет последний ответ.
 * Ответ-экземпляр Error бросается как исключение.
 * @param {any[]} answers
 */
function scriptedInvoke(answers) {
  let i = 0;
  const fn = vi.fn(async (/** @type {string} */ _cmd, /** @type {any} */ _args = undefined) => {
    const a = answers[Math.min(i, answers.length - 1)];
    i += 1;
    if (a instanceof Error) throw a;
    return a;
  });
  return /** @type {any} */ (fn);
}

afterEach(() => {
  vi.useRealTimers();
});

describe('waitEngineReady', () => {
  it('true с первого раза → READY, один вызов нужной команды', async () => {
    const invokeFn = scriptedInvoke([true]);
    const states = /** @type {string[]} */ ([]);
    const res = await waitEngineReady(invokeFn, { onState: (s) => states.push(s), pauseMs: 1 });
    expect(res).toBe(ENGINE.READY);
    expect(invokeFn).toHaveBeenCalledTimes(1);
    expect(invokeFn).toHaveBeenCalledWith('econ_sidecar_wait_ready', { timeoutMs: 30000 });
    expect(states).toEqual([ENGINE.STARTING, ENGINE.READY]);
  });

  it("строка 'ready' (будущий ответ Rust) → READY", async () => {
    const res = await waitEngineReady(scriptedInvoke(['ready']), { pauseMs: 1 });
    expect(res).toBe(ENGINE.READY);
  });

  it("false, false, 'ready' → итог READY за 3 вызова, FAILED не объявлялся", async () => {
    const invokeFn = scriptedInvoke([false, false, 'ready']);
    const states = /** @type {string[]} */ ([]);
    const res = await waitEngineReady(invokeFn, { onState: (s) => states.push(s), pauseMs: 1 });
    expect(res).toBe(ENGINE.READY);
    expect(invokeFn).toHaveBeenCalledTimes(3);
    expect(states).not.toContain(ENGINE.FAILED);
    expect(states[states.length - 1]).toBe(ENGINE.READY);
  });

  it("'starting' (будущий ответ Rust) и исключение считаются «ещё не готов»", async () => {
    const invokeFn = scriptedInvoke(['starting', new Error('boom'), true]);
    const res = await waitEngineReady(invokeFn, { pauseMs: 1 });
    expect(res).toBe(ENGINE.READY);
    expect(invokeFn).toHaveBeenCalledTimes(3);
  });

  it("'stopped' → FAILED сразу, ровно один вызов", async () => {
    const invokeFn = scriptedInvoke(['stopped']);
    const states = /** @type {string[]} */ ([]);
    const res = await waitEngineReady(invokeFn, { onState: (s) => states.push(s), pauseMs: 1 });
    expect(res).toBe(ENGINE.FAILED);
    expect(invokeFn).toHaveBeenCalledTimes(1);
    expect(states[states.length - 1]).toBe(ENGINE.FAILED);
  });

  it('всегда false при rounds=3 → FAILED, ровно 3 вызова (предел раундов)', async () => {
    const invokeFn = scriptedInvoke([false]);
    const res = await waitEngineReady(invokeFn, { rounds: 3, pauseMs: 1 });
    expect(res).toBe(ENGINE.FAILED);
    expect(invokeFn).toHaveBeenCalledTimes(3);
  });

  it('по умолчанию раундов пять', async () => {
    const invokeFn = scriptedInvoke([false]);
    const res = await waitEngineReady(invokeFn, { pauseMs: 1 });
    expect(res).toBe(ENGINE.FAILED);
    expect(invokeFn).toHaveBeenCalledTimes(5);
  });

  it('отмена после первого раунда → второго вызова нет, onState не получает итог', async () => {
    let cancelled = false;
    const invokeFn = /** @type {any} */ (vi.fn(async () => {
      cancelled = true; // компонент размонтировали, пока шёл первый вызов
      return false;
    }));
    const states = /** @type {string[]} */ ([]);
    const res = await waitEngineReady(invokeFn, {
      onState: (s) => states.push(s),
      isCancelled: () => cancelled,
      pauseMs: 1,
    });
    expect(invokeFn).toHaveBeenCalledTimes(1);
    expect(res).toBe(ENGINE.STARTING);
    expect(states).not.toContain(ENGINE.FAILED);
    expect(states).not.toContain(ENGINE.READY);
  });

  it('отмена до начала → ни одного вызова и ни одного onState', async () => {
    const invokeFn = scriptedInvoke([true]);
    const onState = vi.fn();
    await waitEngineReady(invokeFn, { onState, isCancelled: () => true });
    expect(invokeFn).not.toHaveBeenCalled();
    expect(onState).not.toHaveBeenCalled();
  });

  it('отмена во время паузы: следующего раунда нет и таймеры не висят', async () => {
    vi.useFakeTimers();
    let cancelled = false;
    const invokeFn = scriptedInvoke([false]);
    const p = waitEngineReady(invokeFn, { isCancelled: () => cancelled, pauseMs: 3000 });
    await vi.advanceTimersByTimeAsync(100); // первый вызов отработал, идёт пауза
    expect(invokeFn).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    cancelled = true;
    await vi.advanceTimersByTimeAsync(300); // не дольше одного куска паузы
    const res = await p;
    expect(res).toBe(ENGINE.STARTING);
    expect(invokeFn).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('два параллельных вызова → один invokeFn на раунд, общее обещание', async () => {
    const invokeFn = scriptedInvoke([false, true]);
    const a = waitEngineReady(invokeFn, { pauseMs: 1 });
    const b = waitEngineReady(invokeFn, { pauseMs: 1 });
    expect(b).toBe(a);
    const [ra, rb] = await Promise.all([a, b]);
    expect(ra).toBe(ENGINE.READY);
    expect(rb).toBe(ENGINE.READY);
    expect(invokeFn).toHaveBeenCalledTimes(2); // 2 раунда, а не 4
  });

  it('второй подписчик получает текущее состояние и итог', async () => {
    const invokeFn = scriptedInvoke([false, true]);
    const first = /** @type {string[]} */ ([]);
    const second = /** @type {string[]} */ ([]);
    const a = waitEngineReady(invokeFn, { onState: (s) => first.push(s), pauseMs: 1 });
    const b = waitEngineReady(invokeFn, { onState: (s) => second.push(s), pauseMs: 1 });
    await Promise.all([a, b]);
    expect(second[0]).toBe(ENGINE.STARTING);
    expect(second[second.length - 1]).toBe(ENGINE.READY);
    expect(first[first.length - 1]).toBe(ENGINE.READY);
  });

  it('повторный вход: первый подписчик отменён, второй продолжает и получает итог', async () => {
    let firstCancelled = false;
    const invokeFn = scriptedInvoke([false, true]);
    const first = /** @type {string[]} */ ([]);
    const second = /** @type {string[]} */ ([]);
    const a = waitEngineReady(invokeFn, {
      onState: (s) => first.push(s),
      isCancelled: () => firstCancelled,
      pauseMs: 1,
    });
    firstCancelled = true; // ушли со страницы
    const b = waitEngineReady(invokeFn, { onState: (s) => second.push(s), pauseMs: 1 });
    await Promise.all([a, b]);
    expect(second[second.length - 1]).toBe(ENGINE.READY);
    expect(first).not.toContain(ENGINE.READY);
    expect(invokeFn).toHaveBeenCalledTimes(2);
  });

  it('защита сбрасывается по завершении: после FAILED новый вызов начинает заново', async () => {
    const failing = scriptedInvoke(['stopped']);
    expect(await waitEngineReady(failing, { pauseMs: 1 })).toBe(ENGINE.FAILED);
    const healthy = scriptedInvoke([true]);
    expect(await waitEngineReady(healthy, { pauseMs: 1 })).toBe(ENGINE.READY);
    expect(healthy).toHaveBeenCalledTimes(1);
  });
});

describe('engineLabel', () => {
  const states = [ENGINE.STARTING, ENGINE.READY, ENGINE.FAILED, '', undefined, null, 'мусор'];

  it('не содержит Python, sidecar и длинного тире (U+2014)', () => {
    for (const s of states) {
      const text = engineLabel(s);
      expect(text).toBeTruthy();
      expect(text).not.toMatch(/python/i);
      expect(text).not.toMatch(/sidecar/i);
      expect(text).not.toContain('—');
    }
  });

  it('три состояния дают три разные подписи', () => {
    const set = new Set([ENGINE.STARTING, ENGINE.READY, ENGINE.FAILED].map(engineLabel));
    expect(set.size).toBe(3);
  });
});
