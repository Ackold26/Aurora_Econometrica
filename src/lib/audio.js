/**
 * audio.js - Web Audio API звуковая обратная связь.
 * 0 байт в бандле (программная генерация, без файлов).
 *
 * 🔴 15.08.2026, решение владельца: звуковых эффектов в программе нет. Переключатель убран из
 * настроек, и звук выключен НАСОВСЕМ — здесь, а не только в настройках.
 *
 * Почему одного удаления переключателя было мало: прежнее состояние хранится в памяти браузера
 * (`localStorage`), и у клиента, включившего звук раньше, он остался бы включённым навсегда —
 * выключить стало бы негде. Поэтому сохранённое значение больше не читается вовсе.
 *
 * Сами функции воспроизведения оставлены нетронутыми и просто ничего не делают: они вызываются
 * из `ChatPanel.svelte`, и вырезать вызовы значило бы править чат ради выключенной возможности.
 * Если звук когда-нибудь вернут — снять жёсткое `false` и вернуть переключатель в настройки.
 */

const STORAGE_KEY = 'ai-agency-audio-enabled';

/** @type {boolean} Всегда false: звук отключён решением владельца (15.08.2026). */
const enabled = false;

/** @type {AudioContext|null} */
let audioCtx = null;

/** Получить или создать единственный AudioContext. */
function getAudioContext() {
  if (!audioCtx || audioCtx.state === 'closed') {
    audioCtx = new AudioContext();
  }
  return audioCtx;
}

/**
 * Забыть прежнее сохранённое состояние звука.
 *
 * Вызывается один раз при запуске: у клиента, включавшего звук до 15.08.2026, в памяти браузера
 * осталось `true`. Само по себе это уже безвредно (значение больше не читается), но запись
 * лучше убрать — иначе она переживёт возможный возврат переключателя и включит звук без спроса.
 */
export function forgetAudioPreference() {
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* quota / private mode */ }
}

/** @returns {boolean} Всегда false — звук отключён решением владельца. */
export function isAudioEnabled() {
  return enabled;
}

/**
 * Воспроизвести тон через Web Audio API.
 * @param {number} frequency
 * @param {number} duration - секунды
 * @param {OscillatorType} [type]
 */
function playTone(frequency, duration, type = 'sine') {
  if (!enabled) return;
  try {
    const ctx = getAudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.value = frequency;
    gain.gain.value = 0.1;
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration);
  } catch { /* ignore if Web Audio unavailable */ }
}

/** Мягкий звук при отправке сообщения */
export function playSendSound() {
  playTone(800, 0.15, 'sine');
}

/** Звук завершения ответа */
export function playCompleteSound() {
  playTone(1200, 0.2, 'sine');
}

/** Звук достижения (milestone) */
export function playAchievementSound() {
  if (!enabled) return;
  playTone(800, 0.1);
  setTimeout(() => playTone(1200, 0.2), 100);
}
