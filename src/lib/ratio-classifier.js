/**
 * SSOT ratio-классификатор для Aurora MMM Optimizer.
 *
 * Ratio = observations / predictors. Это ключевая метрика статистической
 * надёжности модели. Аврора использует 5 коридоров (Антон 2026-05-16
 * запросил стандартизацию после рассогласованности RatioInfoCard /
 * ModeDerivedExplanation / sticky header «Критически мало» при 2.8).
 *
 * Все UI-компоненты которые показывают label / tone / описание ratio
 * должны импортировать `classifyRatio()` отсюда. Это гарантирует, что
 * пользователь видит одинаковые слова и цвета в:
 *   - sticky header валидации (project-state.validationHeaderMetrics)
 *   - RatioInfoCard (большая карточка Manager mode)
 *   - ModeDerivedExplanation (финальная сводка под-шага «Подтверждение»)
 *   - inline инсайтах InsightsPanel
 */

/**
 * 5-коридорные пороги ratio. Cross-referenced с insights-rules.js и
 * validator.py (backend). Менять только синхронно во всех 3 местах.
 */
export const RATIO_THRESHOLDS = Object.freeze({
  /** < 2 - error (модель почти наверняка переобучится) */
  ERROR: 2,
  /** 2 - 3 - warning-high (между минимумом и стандартом) */
  HIGH_WARNING: 3,
  /** 3 - 4 - warning (ниже рекомендуемого) */
  WARNING: 4,
  /** 4 - 6 - info (рекомендуемый уровень), >= 6 - success (идеально) */
  IDEAL: 6,
});

/**
 * @typedef {'error'|'warning-high'|'warning'|'info'|'success'|'unknown'} RatioSeverity
 * @typedef {'danger'|'warn-strong'|'warn'|'info'|'success'|'neutral'} RatioTone
 *
 * @typedef {{
 *   severity: RatioSeverity,
 *   label: string,
 *   description: string,
 *   tone: RatioTone,
 *   bandLabel: string,
 * }} RatioClassification
 */

/**
 * Классифицирует ratio данных в один из 5 коридоров + edge-case unknown.
 *
 * @param {number | null | undefined} ratio
 * @returns {RatioClassification}
 */
export function classifyRatio(ratio) {
  if (typeof ratio !== 'number' || !Number.isFinite(ratio) || ratio <= 0) {
    return {
      severity: 'unknown',
      label: 'Не определено',
      description: 'Ratio данных не рассчитано - убедитесь, что роли колонок назначены',
      tone: 'neutral',
      bandLabel: '',
    };
  }
  if (ratio < RATIO_THRESHOLDS.ERROR) {
    return {
      severity: 'error',
      label: 'Критически мало',
      description: 'Модель может «выучить» отдельные точки вместо общей закономерности - результаты ненадёжны',
      tone: 'danger',
      bandLabel: 'ниже минимума 2:1',
    };
  }
  if (ratio < RATIO_THRESHOLDS.HIGH_WARNING) {
    return {
      severity: 'warning-high',
      label: 'Ниже минимума',
      description: 'Модель сойдётся, но доверительные интервалы будут очень широкими - используйте результаты как ориентир',
      tone: 'warn-strong',
      bandLabel: 'между минимумом 2:1 и стандартом 4:1',
    };
  }
  if (ratio < RATIO_THRESHOLDS.WARNING) {
    return {
      severity: 'warning',
      label: 'Ниже рекомендуемого',
      description: 'Модель работает, но с широкими доверительными интервалами - результаты как качественные ориентиры',
      tone: 'warn',
      bandLabel: 'ниже рекомендуемого 4:1',
    };
  }
  if (ratio < RATIO_THRESHOLDS.IDEAL) {
    return {
      severity: 'info',
      label: 'Рекомендуемый уровень',
      description: 'Достаточно для надёжной модели. Для узких доверительных интервалов нужно ≥6:1',
      tone: 'info',
      bandLabel: 'рекомендуемый 4:1',
    };
  }
  return {
    severity: 'success',
    label: 'Идеально',
    description: 'Узкие доверительные интервалы, высокая надёжность - оптимальный объём данных',
    tone: 'success',
    bandLabel: 'идеально ≥ 6:1',
  };
}

/**
 * Маппинг 5-уровневой severity к legacy 3-tier (ok / warn / bad) - для
 * компонентов которые ещё используют traffic-light pill.
 *
 * @param {RatioSeverity} severity
 * @returns {'ok'|'warn'|'bad'|'na'}
 */
export function severityTo3Tier(severity) {
  if (severity === 'unknown') return 'na';
  if (severity === 'success' || severity === 'info') return 'ok';
  if (severity === 'warning') return 'warn';
  return 'bad';
}
