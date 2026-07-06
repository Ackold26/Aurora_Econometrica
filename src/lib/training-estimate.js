/**
 * SSOT для оценки времени обучения модели.
 *
 * Используется в ConfigPanel (строка времени под кнопкой «Обучить») и
 * в текстах инсайтов (validateConfirmInsights, modelPreTrainingInsights).
 * Единственный источник — переписывать только здесь.
 */

/** Дефолтный текстовый диапазон (до 8 каналов). */
export const DEFAULT_TRAINING_ESTIMATE = '10-30 секунд';

/**
 * Возвращает текстовую оценку времени обучения Bayesian MMM.
 *
 * @param {number} enabledCount - число включённых медиа-каналов
 * @param {{ chains?: number, draws?: number, tune?: number }} [mcmcParams]
 * @returns {string} Текст для отображения пользователю
 */
export function estimateTrainingTime(enabledCount, mcmcParams = {}) {
  const { chains = 4, draws = 2000, tune = 2000 } = mcmcParams;

  // Дефолтный диапазон без расчёта для стандартных конфигураций
  if (enabledCount <= 8 && chains === 4 && draws === 2000 && tune === 2000) {
    return DEFAULT_TRAINING_ESTIMATE;
  }

  // Для нестандартных конфигураций — расчётная оценка
  const totalSamples = (draws + tune) * chains;
  const secPerSample = 0.005 + enabledCount * 0.0008;
  const totalSec = totalSamples * secPerSample + 20; // +20с JIT
  const minutes = Math.max(1, Math.ceil(totalSec / 60));
  return `~${minutes} мин`;
}
