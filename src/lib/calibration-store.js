/**
 * E2 (2026-07-03): состояние калибровок lift-тестами (per-project persist).
 *
 * Хранение — localStorage по ключу проекта (тот же класс, что kpiConfirmed
 * в Валидации): калибровки — редкая экспертная настройка, полный persist
 * в project.json не оправдан до спроса. При смене проекта — reload.
 */
import { writable, get } from 'svelte/store';

const KEY_PREFIX = 'aurora-econ-calibrations:';

/** @type {import('svelte/store').Writable<Array<Record<string, any>>>} */
export const calibrations = writable([]);

/** @param {string|null|undefined} projectId */
export function loadCalibrations(projectId) {
  if (typeof window === 'undefined' || !projectId) {
    calibrations.set([]);
    return;
  }
  try {
    const raw = window.localStorage.getItem(KEY_PREFIX + projectId);
    const parsed = raw ? JSON.parse(raw) : [];
    calibrations.set(Array.isArray(parsed) ? parsed : []);
  } catch {
    calibrations.set([]);
  }
}

/** @param {string|null|undefined} projectId */
export function persistCalibrations(projectId) {
  if (typeof window === 'undefined' || !projectId) return;
  try {
    window.localStorage.setItem(
      KEY_PREFIX + projectId, JSON.stringify(get(calibrations)),
    );
  } catch { /* квота/приватный режим — не роняем UI */ }
}

/**
 * Мини-валидация записи формы (полная — в utils/calibration.py на сервере).
 * @param {Record<string, any>} c
 * @returns {string|null} русская ошибка или null
 */
export function validateCalibrationEntry(c) {
  if (!c.channel) return 'Выберите канал теста.';
  if (!c.date_from || !c.date_to) return 'Укажите период теста (обе даты).';
  if (new Date(c.date_to) < new Date(c.date_from)) {
    return 'Дата окончания раньше даты начала.';
  }
  const lift = Number(c.lift_abs);
  if (!Number.isFinite(lift)) return 'Укажите измеренный прирост (lift) числом.';
  const lo = Number(c.lift_low);
  const hi = Number(c.lift_high);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) {
    return 'Укажите интервал теста: нижняя граница меньше верхней.';
  }
  if (lift < lo || lift > hi) {
    return 'Измеренный прирост должен лежать внутри интервала теста.';
  }
  return null;
}
