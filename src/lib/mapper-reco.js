/**
 * mapper-reco.js — чистые хелперы для рекомендаций ColumnMapperConfirm.
 *
 * Выделены для unit-тестируемости: не содержат Svelte-сторов, реактивности
 * или импортов компонентов. Потребитель — ColumnMapperConfirm.svelte.
 *
 * R2 (2026-07-06): SSOT kind-based реко (F-A1-2/3).
 */

/**
 * Реко для category-колонки в роли control/excluded.
 * @returns {{ status: 'keep', label: string, reason: string, tone: 'ok' }}
 */
export function recoCategoryControl() {
  return {
    status: /** @type {'keep'} */ ('keep'),
    label: 'Оставить: контроль категории',
    reason:
      'Продажи категории/рынка — экзогенный прокси спроса (Chan & Perry §4.2.2). ' +
      'Стабилизирует сезонность лучше, чем Фурье. Оставьте как контрольную переменную.',
    tone: 'ok',
  };
}

/**
 * Реко для signed_competitor-колонки в роли control/excluded.
 * @returns {{ status: 'keep', label: string, reason: string, tone: 'ok' }}
 */
export function recoCompetitorControl() {
  return {
    status: /** @type {'keep'} */ ('keep'),
    label: 'Оставить: конкурентный контроль',
    reason:
      'Активность конкурентов — контрольный предиктор с отрицательным prior (снижает продажи). ' +
      'Оставьте для корректного разделения вклада.',
    tone: 'ok',
  };
}

/**
 * Реко «Альтернативная цель» для колонок target_monetary/target_count в не-kpi роли.
 * @returns {{ status: 'review', label: string, reason: string, tone: 'warn' }}
 */
export function recoAlternativeTarget() {
  return {
    status: /** @type {'review'} */ ('review'),
    label: 'Альтернативная цель',
    reason:
      'Тип данных указывает на KPI-метрику. KPI уже выбрана для другой колонки ' +
      '(одна KPI на проект). Если хотите моделировать эту — переназначьте роль. Иначе исключите.',
    tone: 'warn',
  };
}

/**
 * Возвращает kind-specific рекомендацию для контрольной колонки, или null
 * если kind не требует специальной обработки.
 *
 * Используется в ColumnMapperConfirm.recommendationFor() вместо regex kpiLikeRe.
 *
 * @param {string} colKind  - kind от Python classify_column ('category'|'signed_competitor'|...)
 * @param {string} role     - эффективная роль ('control'|'excluded'|'kpi'|'media'|...)
 * @param {boolean} isNumeric
 * @param {boolean} hasActiveKpi
 * @returns {{ status: 'keep' | 'review' | 'exclude', label: string, reason: string, tone: string } | null}
 */
export function kindSpecificReco(colKind, role, isNumeric, hasActiveKpi) {
  // Позитивные бейджи для контролей-специалистов (SSOT kind).
  if (role === 'control' || role === 'excluded') {
    if (colKind === 'category') return recoCategoryControl();
    if (colKind === 'signed_competitor') return recoCompetitorControl();
  }

  // Альтернативная цель: target_* в не-kpi роли при наличии уже выбранного KPI.
  if (
    hasActiveKpi &&
    isNumeric &&
    role !== 'kpi' &&
    role !== 'media' &&
    role !== 'excluded' &&
    (colKind === 'target_monetary' || colKind === 'target_count')
  ) {
    return recoAlternativeTarget();
  }

  return null;
}
