/**
 * Состояние модуля расчётов (движка) для подвала конвейера.
 *
 * Команда `econ_sidecar_wait_ready` возвращает строку `'ready'` / `'stopped'` / `'starting'`
 * (жизненный цикл в Rust). Прежний вид ответа – bool (`true` готов, `false` не дождались) –
 * оставлен для совместимости: модуль понимает оба вида. Исключение из `invoke` считается
 * «ещё не готов».
 *
 * Состояние – перечисление, а не текст: подвал красится по `ENGINE.*`, а не по сравнению строки.
 */

/** @typedef {'starting' | 'ready' | 'failed'} EngineState */

/** @type {{ STARTING: 'starting', READY: 'ready', FAILED: 'failed' }} */
export const ENGINE = Object.freeze({
  STARTING: 'starting',
  READY: 'ready',
  FAILED: 'failed',
});

/**
 * Подпись состояния для подвала и подсказки. Без вендор-слов (INV-50).
 * @param {EngineState | string | null | undefined} state
 * @returns {string}
 */
export function engineLabel(state) {
  if (state === ENGINE.READY) return 'Модуль расчётов: готов';
  if (state === ENGINE.FAILED) {
    return 'Модуль расчётов не отвечает – программа пробует его запустить; если не заработает, перезапустите программу';
  }
  return 'Модуль расчётов: запускается…';
}

/**
 * @typedef {{
 *   onState?: (state: EngineState) => void,
 *   isCancelled?: () => boolean,
 * }} Subscriber
 */

/**
 * Идущее ожидание – одно на всё приложение.
 * @type {{ promise: Promise<EngineState>, subscribers: Subscriber[], state: EngineState } | null}
 */
let current = null;

/** Шаг проверки отмены внутри паузы, мс: пауза не держит таймер дольше этого после отмены. */
const PAUSE_SLICE_MS = 250;

/**
 * @param {Subscriber} sub
 * @returns {boolean}
 */
function subscriberCancelled(sub) {
  return sub.isCancelled ? Boolean(sub.isCancelled()) : false;
}

/**
 * Пауза кусками: после каждого куска проверяет отмену и при ней не заводит новый таймер.
 * Одновременно висит не больше одного таймера, не длиннее `PAUSE_SLICE_MS`.
 * @param {number} ms
 * @param {() => boolean} isCancelled
 * @returns {Promise<void>}
 */
function pause(ms, isCancelled) {
  return new Promise((resolve) => {
    let left = ms;
    const step = () => {
      if (isCancelled() || left <= 0) {
        resolve();
        return;
      }
      const slice = Math.min(left, PAUSE_SLICE_MS);
      left -= slice;
      setTimeout(step, slice);
    };
    step();
  });
}

/**
 * Ждёт готовности движка не более `rounds` раундов (на каждом – `econ_sidecar_wait_ready`).
 *
 * - `true` / `'ready'` → READY;
 * - `'stopped'` → FAILED сразу, без повторов;
 * - иначе (`false`, `'starting'`, исключение) – пауза `pauseMs` и новый раунд;
 * - исчерпаны раунды → FAILED;
 * - при отмене всеми подписчиками (`isCancelled()`) выходит без вызова `onState`, результат STARTING.
 *
 * Одно ожидание на модуль: пока оно идёт, повторный вызов присоединяется к нему и возвращает то же
 * обещание (параметры `rounds` и `pauseMs` берутся от первого вызова), новый `onState` сразу получает
 * текущее состояние. Прогон отменяется, только когда отменены все подписчики. По завершении защита
 * сбрасывается: повторная попытка после FAILED – новым вызовом.
 *
 * @param {(cmd: string, args?: any) => Promise<any>} invokeFn
 * @param {{
 *   onState?: (state: EngineState) => void,
 *   isCancelled?: () => boolean,
 *   rounds?: number,
 *   pauseMs?: number,
 * }} [options]
 * @returns {Promise<EngineState>}
 */
export function waitEngineReady(invokeFn, options = {}) {
  const { onState, isCancelled, rounds = 5, pauseMs = 3000 } = options;
  /** @type {Subscriber} */
  const sub = { onState, isCancelled };

  if (current) {
    current.subscribers.push(sub);
    if (onState && !subscriberCancelled(sub)) onState(current.state);
    return current.promise;
  }

  /** @type {{ promise: Promise<EngineState>, subscribers: Subscriber[], state: EngineState }} */
  const run = { promise: /** @type {any} */ (null), subscribers: [sub], state: ENGINE.STARTING };
  current = run;

  const allCancelled = () => run.subscribers.every(subscriberCancelled);
  /** @param {EngineState} state */
  const report = (state) => {
    run.state = state;
    for (const s of run.subscribers) {
      if (s.onState && !subscriberCancelled(s)) s.onState(state);
    }
  };

  run.promise = (async () => {
    try {
      if (allCancelled()) return ENGINE.STARTING;
      report(ENGINE.STARTING);

      for (let round = 0; round < rounds; round++) {
        if (allCancelled()) return ENGINE.STARTING;

        /** @type {any} */
        let answer = false;
        try {
          answer = await invokeFn('econ_sidecar_wait_ready', { timeoutMs: 30000 });
        } catch {
          answer = false;
        }
        if (allCancelled()) return ENGINE.STARTING;

        if (answer === true || answer === 'ready') {
          report(ENGINE.READY);
          return ENGINE.READY;
        }
        if (answer === 'stopped') {
          report(ENGINE.FAILED);
          return ENGINE.FAILED;
        }

        if (round < rounds - 1) {
          await pause(pauseMs, allCancelled);
          if (allCancelled()) return ENGINE.STARTING;
        }
      }

      report(ENGINE.FAILED);
      return ENGINE.FAILED;
    } finally {
      if (current === run) current = null;
    }
  })();

  return run.promise;
}

/**
 * Идущее фоновое восстановление – одно на всё приложение.
 * @type {{ promise: Promise<EngineState>, subscribers: Subscriber[] } | null}
 */
let recovering = null;

/**
 * Фоновое восстановление после FAILED (`'stopped'` или исчерпанные раунды): погибший движок позже
 * поднимает сторож или `ensure_alive` при первом запросе, и подвал не должен залипать красным.
 *
 * Раз в `everyMs` повторяет одну проверку (`waitEngineReady` с одним раундом) – не более
 * `maxRounds` проверок. Пауза нарезана, как у `waitEngineReady`: отмена мгновенная, таймеров
 * больше одного не бывает. При переходе в READY вызывает `onState(READY)` и заканчивает; пока
 * движок не отвечает, `onState` не вызывается (подвал остаётся FAILED, без мигания «запускается»).
 *
 * Одно восстановление на приложение: пока оно идёт, повторный вызов присоединяется к нему и
 * возвращает то же обещание (`everyMs` и `maxRounds` – от первого вызова); второй цикл не заводится.
 * Цикл останавливается, когда отменены все подписчики.
 *
 * Возвращает READY (поднялся), FAILED (раунды исчерпаны) или STARTING (отменено).
 *
 * @param {(cmd: string, args?: any) => Promise<any>} invokeFn
 * @param {{
 *   onState?: (state: EngineState) => void,
 *   isCancelled?: () => boolean,
 *   everyMs?: number,
 *   maxRounds?: number,
 * }} [options]
 * @returns {Promise<EngineState>}
 */
export function watchEngineRecovery(invokeFn, options = {}) {
  const { onState, isCancelled, everyMs = 30000, maxRounds = 20 } = options;
  /** @type {Subscriber} */
  const sub = { onState, isCancelled };

  if (recovering) {
    recovering.subscribers.push(sub);
    return recovering.promise;
  }

  /** @type {{ promise: Promise<EngineState>, subscribers: Subscriber[] }} */
  const run = { promise: /** @type {any} */ (null), subscribers: [sub] };
  recovering = run;

  const allCancelled = () => run.subscribers.every(subscriberCancelled);

  run.promise = (async () => {
    try {
      for (let round = 0; round < maxRounds; round++) {
        await pause(everyMs, allCancelled);
        if (allCancelled()) return ENGINE.STARTING;

        const state = await waitEngineReady(invokeFn, { rounds: 1, isCancelled: allCancelled });
        if (allCancelled()) return ENGINE.STARTING;

        if (state === ENGINE.READY) {
          for (const s of run.subscribers) {
            if (s.onState && !subscriberCancelled(s)) s.onState(ENGINE.READY);
          }
          return ENGINE.READY;
        }
      }
      return ENGINE.FAILED;
    } finally {
      if (recovering === run) recovering = null;
    }
  })();

  return run.promise;
}
