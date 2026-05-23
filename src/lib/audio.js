/**
 * audio.js - Web Audio API звуковая обратная связь.
 * 0 байт в бандле (программная генерация, без файлов).
 * По умолчанию ВЫКЛЮЧЕНО. Состояние сохраняется в localStorage.
 */

const STORAGE_KEY = 'ai-agency-audio-enabled';

/** @type {boolean} */
let enabled = false;
try {
  enabled = typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY) === 'true';
} catch { /* SSR / private mode */ }

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
 * Включить/выключить звуки.
 * @param {boolean} value
 */
export function setAudioEnabled(value) {
  enabled = value;
  try { localStorage.setItem(STORAGE_KEY, String(value)); } catch { /* quota / private mode */ }
}

/** @returns {boolean} */
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
