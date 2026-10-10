/**
 * Модуль состояния движка (`engine-status.js`): честный подвал.
 * Логика ожидания вынесена из `pipeline/+layout.svelte`, потому что проект
 * рендер-тесты компонентов обходит (см. `src/tests/nav2-footer-gate.test.js`).
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { ENGINE, engineLabel, waitEngineReady, watchEngineRecovery } from '../engine-status.js';

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

describe('watchEngineRecovery', () => {
  it("'stopped', затем 'ready' в следующем раунде фона → READY и onState(READY)", async () => {
    vi.useFakeTimers();
    const invokeFn = scriptedInvoke(['stopped', 'ready']);
    expect(await waitEngineReady(invokeFn, { pauseMs: 1 })).toBe(ENGINE.FAILED);
    expect(invokeFn).toHaveBeenCalledTimes(1);

    const states = /** @type {string[]} */ ([]);
    const p = watchEngineRecovery(invokeFn, { onState: (s) => states.push(s), everyMs: 30000 });
    await vi.advanceTimersByTimeAsync(29000); // до срока проверки нет
    expect(invokeFn).toHaveBeenCalledTimes(1);
    expect(states).toEqual([]);
    await vi.advanceTimersByTimeAsync(2000); // срок наступил: проверка отработала
    expect(await p).toBe(ENGINE.READY);
    expect(invokeFn).toHaveBeenCalledTimes(2);
    expect(invokeFn).toHaveBeenLastCalledWith('econ_sidecar_wait_ready', { timeoutMs: 30000 });
    expect(states).toEqual([ENGINE.READY]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('пока движок не отвечает, onState не вызывается (подвал не мигает «запускается»)', async () => {
    vi.useFakeTimers();
    const invokeFn = scriptedInvoke(['stopped', 'stopped', 'stopped', 'ready']);
    const states = /** @type {string[]} */ ([]);
    const p = watchEngineRecovery(invokeFn, { onState: (s) => states.push(s), everyMs: 1000 });
    await vi.advanceTimersByTimeAsync(3500);
    expect(invokeFn).toHaveBeenCalledTimes(3); // три «stopped» подряд, onState молчит
    expect(states).toEqual([]);
    await vi.advanceTimersByTimeAsync(1000);
    expect(await p).toBe(ENGINE.READY);
    expect(states).toEqual([ENGINE.READY]);
  });

  it('maxRounds исчерпан → остаётся FAILED, ровно N вызовов, дальше тишина', async () => {
    vi.useFakeTimers();
    const invokeFn = scriptedInvoke(['stopped']);
    const onState = vi.fn();
    const p = watchEngineRecovery(invokeFn, { onState, everyMs: 1000, maxRounds: 3 });
    await vi.advanceTimersByTimeAsync(10000);
    expect(await p).toBe(ENGINE.FAILED);
    expect(invokeFn).toHaveBeenCalledTimes(3);
    expect(onState).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(60000);
    expect(invokeFn).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('исключение из invoke – «ещё не отвечает», следующий раунд идёт', async () => {
    vi.useFakeTimers();
    const invokeFn = scriptedInvoke([new Error('boom'), true]);
    const p = watchEngineRecovery(invokeFn, { everyMs: 1000 });
    await vi.advanceTimersByTimeAsync(2500);
    expect(await p).toBe(ENGINE.READY);
    expect(invokeFn).toHaveBeenCalledTimes(2);
  });

  it('отмена: после неё вызовов нет, onState не вызывается, таймеры не висят', async () => {
    vi.useFakeTimers();
    let cancelled = false;
    const invokeFn = scriptedInvoke(['stopped']);
    const onState = vi.fn();
    const p = watchEngineRecovery(invokeFn, {
      onState, isCancelled: () => cancelled, everyMs: 1000, maxRounds: 10,
    });
    await vi.advanceTimersByTimeAsync(1100); // первая проверка прошла
    expect(invokeFn).toHaveBeenCalledTimes(1);
    cancelled = true;
    await vi.advanceTimersByTimeAsync(300); // не дольше одного куска паузы
    expect(await p).toBe(ENGINE.STARTING);
    await vi.advanceTimersByTimeAsync(20000);
    expect(invokeFn).toHaveBeenCalledTimes(1);
    expect(onState).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('отмена во время проверки в последнем раунде → STARTING (не FAILED) и onState молчит', async () => {
    vi.useFakeTimers();
    let cancelled = false;
    const invokeFn = /** @type {any} */ (vi.fn(async () => {
      cancelled = true; // ушли со страницы, пока шла проверка
      return 'ready';
    }));
    const onState = vi.fn();
    const p = watchEngineRecovery(invokeFn, {
      onState, isCancelled: () => cancelled, everyMs: 1000, maxRounds: 1,
    });
    await vi.advanceTimersByTimeAsync(1500);
    expect(await p).toBe(ENGINE.STARTING);
    expect(invokeFn).toHaveBeenCalledTimes(1);
    expect(onState).not.toHaveBeenCalled();
  });

  it('отмена до срока первой проверки → ни одного вызова', async () => {
    vi.useFakeTimers();
    let cancelled = false;
    const invokeFn = scriptedInvoke([true]);
    const p = watchEngineRecovery(invokeFn, { isCancelled: () => cancelled, everyMs: 30000 });
    await vi.advanceTimersByTimeAsync(5000);
    cancelled = true;
    await vi.advanceTimersByTimeAsync(300);
    expect(await p).toBe(ENGINE.STARTING);
    await vi.advanceTimersByTimeAsync(60000);
    expect(invokeFn).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('одновременный повторный вызов не создаёт второй цикл: общее обещание, один вызов на раунд', async () => {
    vi.useFakeTimers();
    const invokeFn = scriptedInvoke(['stopped', 'ready']);
    const first = /** @type {string[]} */ ([]);
    const second = /** @type {string[]} */ ([]);
    const a = watchEngineRecovery(invokeFn, { onState: (s) => first.push(s), everyMs: 1000 });
    const b = watchEngineRecovery(invokeFn, { onState: (s) => second.push(s), everyMs: 1000 });
    expect(b).toBe(a);
    await vi.advanceTimersByTimeAsync(2500);
    expect(await a).toBe(ENGINE.READY);
    expect(await b).toBe(ENGINE.READY);
    expect(invokeFn).toHaveBeenCalledTimes(2); // два раунда, а не четыре
    expect(first).toEqual([ENGINE.READY]);
    expect(second).toEqual([ENGINE.READY]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('первый подписчик отменён, второй продолжает цикл и получает итог', async () => {
    vi.useFakeTimers();
    let firstCancelled = false;
    const invokeFn = scriptedInvoke(['stopped', 'ready']);
    const first = vi.fn();
    const second = vi.fn();
    const a = watchEngineRecovery(invokeFn, {
      onState: first, isCancelled: () => firstCancelled, everyMs: 1000,
    });
    firstCancelled = true; // ушли со страницы и вернулись: новый монтаж присоединился
    const b = watchEngineRecovery(invokeFn, { onState: second, everyMs: 1000 });
    await vi.advanceTimersByTimeAsync(2500);
    expect(await Promise.all([a, b])).toEqual([ENGINE.READY, ENGINE.READY]);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledWith(ENGINE.READY);
  });

  it('защита сбрасывается по завершении: после исчерпания раундов новый вызов начинает заново', async () => {
    vi.useFakeTimers();
    const failing = scriptedInvoke(['stopped']);
    const p1 = watchEngineRecovery(failing, { everyMs: 500, maxRounds: 2 });
    await vi.advanceTimersByTimeAsync(2000);
    expect(await p1).toBe(ENGINE.FAILED);
    const healthy = scriptedInvoke([true]);
    const p2 = watchEngineRecovery(healthy, { everyMs: 500, maxRounds: 2 });
    await vi.advanceTimersByTimeAsync(700);
    expect(await p2).toBe(ENGINE.READY);
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

  it('FAILED не обещает «не запустился»: движок ещё могут поднять, подпись это говорит', () => {
    const text = engineLabel(ENGINE.FAILED);
    expect(text).toContain('не отвечает');
    expect(text).toContain('пробует');
    expect(text).toContain('перезапустите программу');
    expect(text).not.toContain('не запустился');
  });

  it('три состояния дают три разные подписи', () => {
    const set = new Set([ENGINE.STARTING, ENGINE.READY, ENGINE.FAILED].map(engineLabel));
    expect(set.size).toBe(3);
  });
});
