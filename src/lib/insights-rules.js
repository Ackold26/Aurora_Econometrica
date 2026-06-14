/**
 * Rule-Based Insights Engine (Tier 1 - offline, always works).
 * Generates contextual recommendations from pipeline data without API calls.
 * Covers ~80% of insight value at 0% cost.
 *
 * @module insights-rules
 */
// Audit pass 9 (2026-05-03): removed marginalROI/buildScaledParams imports.
// Insights теперь uses backend's ch.mroi_current + ch.action - three-way
// alignment с таблицей и compute_channel_action (single source of truth).

// v1.3.2: KPI/mode-aware label helpers - позволяют insights адаптироваться
// для count KPI (CPU вместо ROI) и effectiveness mode (доля вместо ROI×).
// Legacy callers (без kpi arg) получают monetary roi defaults - backward compat.
import {
  kpiView as _kpiView,
  fmtMetric as _fmtMetric,
  weightedPhrase as _weightedPhrase,
  underBreakevenPhrase as _underBreakeven,
  topMetricBenchmark as _topBenchmark,
} from './kpi-aware-formatting.js';
// v2.1.0 (пилот 2026-05-16): SSOT-классификатор ratio для согласованности
// меток с RatioInfoCard / sticky header / Контроль качества.
import { classifyRatio } from './ratio-classifier.js';
import { pluralizeRu } from './utils/i18n.js';
// INV-50 анти-рецидив (2026-06-07): единый пост-train селектор MQS / effective
// ratio. Инсайты больше НЕ читают эти производные из diagnostics напрямую —
// только через mqsView/ratioView, чтобы honesty-баг не вернулся N+1-м слоем.
import { mqsView, ratioView } from './metric-views.js';

/**
 * Resolve KPI view с default legacy fallback.
 * @param {import('./kpi-aware-formatting.js').KpiViewInput|null|undefined} kpi
 * @returns {import('./kpi-aware-formatting.js').KpiView}
 */
function resolveKpi(kpi) {
  if (kpi && typeof kpi === 'object' && 'isLegacy' in kpi) {
    return /** @type {import('./kpi-aware-formatting.js').KpiView} */ (kpi);
  }
  return _kpiView(kpi);
}

/**
 * @typedef {Object} InsightAction
 * @property {'exclude'|'keep_only'|'set_role'|'merge'} type
 * @property {string[]} columns - columns to act on
 * @property {string[]} [exclude] - columns to exclude (for keep_only)
 * @property {string} [label] - button label override
 * @property {string} [mergedName] - name for merged column (type=merge)
 */

/**
 * @typedef {Object} Insight
 * @property {'info'|'success'|'warning'|'error'} severity
 * @property {string} text
 * @property {string} [tip]
 * @property {InsightAction} [action]
 * @property {InsightAction} [secondaryAction] - дополнительная alternative action (paired metrics)
 */

// ── Import Step ─────────────────────────────────────────

/**
 * @param {{ rows: number, cols: number, columns: any[], zeros: Record<string, number>, fileName?: string }} data
 * @returns {Insight[]}
 */
export function importInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data) return out;

  const { rows, cols, columns, zeros, fileName } = data;

  // ── Оценка объёма данных ──
  if (rows === 0) {
    out.push({ severity: 'info', text: `Файл${fileName ? ` «${fileName}»` : ''} загружен. Запустите валидацию для анализа структуры данных.` });
    return out;
  }

  // Гранулярность: < 60 строк скорее всего месячные данные.
  // NUM-1 (2026-06-02): для месячных period уже в месяцах ("~31 месяц"), слово
  // "месячных" дублирует единицу → тавтология. Опускаем granularity-слово для месячных.
  const granularityWord = rows <= 60 ? '' : rows <= 260 ? 'недельных' : 'дневных';
  const obsLabel = granularityWord ? `${granularityWord} наблюдений` : 'наблюдений';
  // Корректное склонение (pluralizeRu вместо крудового n>1): "31 месяц", "5 лет".
  const years = rows <= 260 ? Math.round(rows / 52) : Math.round(rows / 365);
  const period = rows <= 60
    ? `~${rows} ${pluralizeRu(rows, ['месяц', 'месяца', 'месяцев'])}`
    : `~${years} ${pluralizeRu(years, ['год', 'года', 'лет'])}`;

  if (rows < 24) {
    out.push({ severity: 'warning', text: `Мало данных: ${rows} наблюдений (${period}). MMM требует минимум 2 года истории.`, tip: 'Байесовская модель работает с малыми выборками, но доверительные интервалы будут широкими.' });
  } else if (rows >= 104) {
    out.push({ severity: 'success', text: `${rows} ${obsLabel} (${period}) - отличный объём для MMM.` });
  } else {
    out.push({ severity: 'info', text: `${rows} ${obsLabel} (${period}), ${cols} столбцов.` });
  }

  // ── Автодетект медиаканалов по именам колонок ──
  const colNames = columns.map(/** @param {any} c */ c => (c.name ?? String(c)).toUpperCase());
  const MEDIA_KEYWORDS = ['OLV','TV','ТВ','RADIO','РАДИО','BANNER','БАННЕР','DIGITAL','CONTEXT','TARGET','SMM','OOH','ООН','ВНЕШН','НАРУЖН','OUTDOOR','PRESS','ПРЕССА','YOUTUBE','VK','OK','TG','TELEGRAM','SEARCH','SEO','EMAIL','PUSH','IN-APP','RTB','PROGRAMMATIC','CPC','CPM','GRP','TRP','OTS','IMPRESS','ПОКАЗ','CLICK','КЛИК','VISIT','ВИЗИТ','BUDGET','БЮДЖЕТ','SPEND','COST','РУБ','СОЦ','SOCIAL','PERFORMANCE','RETAIL','СПЕЦПРОЕКТ','СТАТЬИ'];
  const DATE_KEYWORDS = ['DATE','ДАТА','PERIOD','НЕДЕЛЯ','МЕСЯЦ','WEEK','MONTH','YEAR'];
  const KPI_KEYWORDS = ['SALES','ПРОДАЖИ','REVENUE','ВЫРУЧКА','UNITS','ШТУ','КОНВЕРС','CONVERSION','ORDERS','ЗАКАЗ','LEADS','ЛИД','CLICKS_KPI'];

  const detectedMedia = colNames.filter(n => MEDIA_KEYWORDS.some(k => n.includes(k))).length;
  const hasDate = colNames.some(n => DATE_KEYWORDS.some(k => n.includes(k)));
  const hasKpi = colNames.some(n => KPI_KEYWORDS.some(k => n.includes(k)));

  if (hasDate && hasKpi) {
    out.push({ severity: 'success', text: 'Обнаружены дата и целевой KPI - структура данных подходит для MMM.' });
  } else if (!hasDate) {
    out.push({ severity: 'warning', text: 'Колонка с датой не найдена. Убедитесь, что временной период присутствует в данных.', tip: 'MMM требует временного ряда. Колонка с датой должна быть первой или явно названа DATE/ДАТА/PERIOD.' });
  } else if (!hasKpi) {
    out.push({ severity: 'warning', text: 'Целевой KPI не распознан автоматически. На шаге Валидация назначьте его вручную.', tip: 'KPI - это что вы хотите объяснить: продажи, выручка, конверсии, заказы.' });
  }

  if (detectedMedia > 0) {
    out.push({ severity: 'info', text: `Найдено ~${detectedMedia} медиа-переменных. На шаге Валидация проверьте назначение ролей.` });
    if (detectedMedia > 10) {
      out.push({ severity: 'warning', text: `Много медиа-переменных (${detectedMedia}). Рассмотрите агрегацию мелких каналов.`, tip: 'Чем больше каналов, тем сложнее модель. При малом числе наблюдений это снижает точность.' });
    }
  }

  // ── Нули ──
  if (zeros) {
    for (const [col, pct] of Object.entries(zeros)) {
      if (pct > 80) {
        out.push({ severity: 'warning', text: `«${col}»: ${Math.round(pct)}% нулей - канал малоактивен.` });
      }
    }
  }

  return out;
}

// ── Validate Step ───────────────────────────────────────

/**
 * v2.1.0 (rc2 U-05): инсайты для под-шага «1. Целевая метрика» Валидации.
 *
 * Цель пользователя здесь: выбрать режим (ROI / Эффективность / Mixed) +
 * KPI. Инсайты должны ПОМОГАТЬ выбору, а не сообщать про каналы
 * (это для следующего под-шага «Роли колонок»).
 *
 * Подходящие темы:
 *  - Какие KPI колонки обнаружены (auto-detect)
 *  - Что в данных бюджетные / физические метрики → подсказка режима
 *  - Период данных, гранулярность - sufficient для надёжной модели?
 *  - Якорь на типичный выбор (90% ROI режим)
 *
 * НЕ обсуждаем:
 *  - % нулей в каналах, мультиколлинеарность, имена media каналов
 *  - exclusion рекомендации
 *
 * @param {any} result - validateData.result
 * @param {{ analysisMode?: string, kpiType?: string }} [context]
 * @returns {Insight[]}
 */
export function validateKpiInsights(result, context = {}) {
  /** @type {Insight[]} */
  const out = [];
  if (!result) return out;

  const cols = Array.isArray(result.columns) ? result.columns : [];
  const kpiCandidates = cols.filter(/** @param {any} c */ c => c.role === 'kpi');
  const totalRows = result.file?.rows ?? result.detected?.rows ?? 0;
  const granularity = totalRows <= 60 ? 'месячная' : totalRows <= 260 ? 'недельная' : 'дневная';

  // 1. Распознавание KPI колонки
  if (kpiCandidates.length === 1) {
    out.push({
      severity: 'success',
      text: `KPI распознан автоматически: «${kpiCandidates[0].name}». Это целевая метрика - то, что модель будет объяснять.`,
    });
  } else if (kpiCandidates.length > 1) {
    out.push({
      severity: 'info',
      text: `Найдено ${kpiCandidates.length} колонки похожих на KPI: ${kpiCandidates.slice(0, 3).map(/** @param {any} c */ c => `«${c.name}»`).join(', ')}. На следующем под-шаге («Роли колонок») оставите одну - ту, что считаете главной целью.`,
      tip: 'Если думаете в деньгах - выбирайте «Выручка». Если в штуках (упаковки, лиды) - выбирайте «Продажи в штуках» (изменится тип KPI и логика модели).',
    });
  } else {
    out.push({
      severity: 'warning',
      text: 'KPI колонка не распознана автоматически. На следующем под-шаге «Роли колонок» назначьте роль «Целевая метрика» вручную.',
    });
  }

  // 2. Подсказка режима из данных
  const colsUpper = cols.map(/** @param {any} c */ c => String(c.name ?? '').toUpperCase());
  const moneySignals = ['БЮДЖЕТ', 'BUDGET', 'SPEND', 'РУБ', '₽', 'COST'];
  const physicalSignals = ['TRP', 'GRP', 'ПОКАЗ', 'IMPRESS', 'КЛИК', 'CLICK', 'VISIT', 'ВИЗИТ', 'OTS', 'CPM', 'CPC'];
  const moneyCount = colsUpper.filter(/** @param {string} n */ n => moneySignals.some(s => n.includes(s))).length;
  const physCount = colsUpper.filter(/** @param {string} n */ n => physicalSignals.some(s => n.includes(s))).length;

  if (moneyCount > 0 && physCount === 0) {
    out.push({
      severity: 'success',
      text: `Все ваши медиа-данные - в рублях (${moneyCount} бюджетных колонок). Это идеальный кейс для **ROI режима** - модель сразу даст ответ «сколько ₽ принёс канал».`,
    });
  } else if (moneyCount === 0 && physCount > 0) {
    out.push({
      severity: 'info',
      text: `Все ваши медиа-данные - в физических метриках (${physCount} колонок: TRP / показы / клики). Без бюджетов ROI считать не получится - выбирайте **Эффективность режим** или укажите цену единицы на следующем шаге для конверсии в ₽.`,
    });
  } else if (moneyCount > 0 && physCount > 0) {
    out.push({
      severity: 'info',
      text: `В данных смешано: ${moneyCount} бюджетных + ${physCount} физических метрик (TRP / показы / клики). В **ROI режиме** физические каналы конвертируются в ₽ через цену единицы (CPP/CPM) - укажете на следующем шаге.`,
      tip: 'Если у канала есть только физические метрики без бюджета, оцените средний CPP по вашей категории.',
    });
  }

  // 3. Якорь на типичный выбор
  out.push({
    severity: 'info',
    text: '90% MMM-проектов используют **ROI режим** - он понятнее менеджменту компании и легко переводим в эффективность одной кнопкой.',
    tip: 'Эффективность режим оправдан когда бюджеты не вполне прозрачны (агентские скидки, доступ только к GRP/показам без рублёвых данных) - в этом случае модель выдаёт «доли вклада в %», не рубли.',
  });

  // 4. Период данных
  if (totalRows > 0) {
    if (totalRows < 24) {
      out.push({
        severity: 'warning',
        text: `${totalRows} наблюдений (${granularity} гранулярность) - очень мало для надёжной MMM. Модель запустится, но результаты будут с большой неопределённостью.`,
        tip: 'Рекомендуется ≥24 месяцев / ≥104 недель данных. Перейдите на недельную гранулярность если есть исходники - это в 4× больше точек.',
      });
    } else if (totalRows < 52) {
      out.push({
        severity: 'info',
        text: `${totalRows} наблюдений (${granularity} гранулярность) - приемлемо для пилота. Для production рекомендуется ≥52 наблюдений (год недельных или 2 года месячных).`,
      });
    } else {
      out.push({
        severity: 'success',
        text: `${totalRows} наблюдений (${granularity} гранулярность) - достаточно для надёжной MMM.`,
      });
    }
  }

  return out;
}

/**
 * v2.1.0 (rc2 U-05): инсайты для под-шага «2. Роли колонок».
 * Это была монолитная validateInsights - теперь явное имя.
 *
 * @param {any} result
 * @param {string} [objective]
 * @returns {Insight[]}
 */
export function validateRolesInsights(result, objective = 'roi') {
  return validateInsights(result, objective);
}

/**
 * v2.1.0 (rc2 U-05): инсайты для под-шага «3. Метрики каналов».
 *
 * На этом под-шаге пользователь видит AppliedModeSummary (Manager mode)
 * или PerChannelInputSelector (Expert mode). Инсайты должны помогать
 * корректно настроить единицы / конверсии.
 *
 * @param {any} result
 * @param {{ analysisMode?: string, perChannelInput?: Record<string, string>, unitCosts?: Record<string, number>, budgetInputs?: Record<string, number>, unitCostInputMode?: Record<string, string> }} [context]
 * @returns {Insight[]}
 */
export function validateMetricsInsights(result, context = {}) {
  /** @type {Insight[]} */
  const out = [];
  if (!result) return out;

  const cols = Array.isArray(result.columns) ? result.columns : [];
  const mediaCols = cols.filter(/** @param {any} c */ c => c.role === 'media');
  const mode = context.analysisMode || 'roi';
  const perChannel = context.perChannelInput || {};
  const unitCosts = context.unitCosts || {};
  // F-007 pilot (2026-05-18): для budget-mode channel check фактический
  // ввод budgetInputs[ch], не только derived unitCosts (которое может быть
  // stale из project.json). Когда юзер очистил budget input, UI status
  // warning «нужна конвертация», но insight ранее давал success.
  const budgetInputs = context.budgetInputs || {};
  const inputMode = context.unitCostInputMode || {};

  if (mediaCols.length === 0) {
    out.push({
      severity: 'error',
      text: 'Нет активных медиа-каналов. Вернитесь на «Роли колонок» и назначьте хотя бы один канал.',
    });
    return out;
  }

  // Проверка mode-specific конверсий
  if (mode === 'roi') {
    const needsConversion = mediaCols.filter(/** @param {any} c */ c => {
      const kind = perChannel[c.name] || 'monetary';
      if (kind !== 'physical') return false;
      // F-007: канал считается «готовым» только когда unit_cost > 0 И активный
      // input mode фактически заполнен (budget mode → budgetInputs[ch] > 0,
      // unit mode → unitCosts[ch] > 0). Иначе stale unit_cost из project.json
      // давал false success при пустых input полях.
      const ucReady = Number(unitCosts[c.name]) > 0;
      const mode = inputMode[c.name] ?? 'budget';
      const inputReady = mode === 'unit'
        ? ucReady
        : Number(budgetInputs[c.name]) > 0;
      return !(ucReady && inputReady);
    });
    if (needsConversion.length > 0) {
      out.push({
        severity: 'warning',
        text: `${needsConversion.length} канал${needsConversion.length === 1 ? '' : 'ов'} с физическими метриками без цены единицы. В ROI режиме нужно указать CPP/CPM для конверсии в ₽, иначе модель не посчитает ROI этих каналов.`,
        tip: 'Если не знаете точно - укажите средний CPP/CPM по рынку для вашей категории.',
      });
    } else {
      out.push({
        severity: 'success',
        text: `Все ${mediaCols.length} каналов готовы: бюджеты в ₽ или физические с конверсией. Можно идти к подтверждению.`,
      });
    }
  } else if (mode === 'effectiveness') {
    out.push({
      severity: 'info',
      text: `Эффективность режим: все ${mediaCols.length} каналов будут поданы в физических метриках. Модель посчитает доли вклада в KPI (%), без оценки ROI.`,
    });
  } else {
    out.push({
      severity: 'warning',
      text: `Смешанный режим: ${mediaCols.length} каналов. Точность ROI ±10-25% из-за смешения единиц измерения.`,
    });
  }

  return out;
}

/**
 * v2.1.0 (rc2 U-05): инсайты для под-шага «4. Подтверждение».
 *
 * Пользователь видит финальную сводку перед обучением. Инсайты должны
 * подсветить риски и рекомендации перед запуском MMM.
 *
 * @param {any} result
 * @param {{ analysisMode?: string }} [context]
 * @returns {Insight[]}
 */
export function validateConfirmInsights(result, context = {}) {
  /** @type {Insight[]} */
  const out = [];
  if (!result) return out;

  const cols = Array.isArray(result.columns) ? result.columns : [];
  const mediaCount = cols.filter(/** @param {any} c */ c => c.role === 'media').length;
  const controlCount = cols.filter(/** @param {any} c */ c => c.role === 'control').length;
  const rows = result.file?.rows ?? 0;
  const ratio = rows > 0 && (mediaCount + controlCount) > 0 ? rows / (mediaCount + controlCount) : 0;

  out.push({
    severity: 'success',
    text: `Готово к обучению: ${mediaCount} медиаканал${mediaCount > 4 ? 'ов' : mediaCount > 1 ? 'а' : ''}${controlCount > 0 ? ` + ${controlCount} контрольн${controlCount === 1 ? 'ая' : 'ых'}` : ''}, режим **${(context.analysisMode || 'roi').toUpperCase()}**. Обучение займёт 30-60 секунд (Bayesian) или ~5 секунд (OLS fallback).`,
  });

  if (ratio < 4) {
    out.push({
      severity: 'warning',
      text: `Ratio данных ${ratio.toFixed(1)}:1 (наблюдения ÷ выбранные признаки, оценка до обучения) ниже рекомендованного 4:1. Модель обучится, но результаты с широкими диапазонами возможных значений.`,
      tip: 'После обучения смотрите R-hat (показатель сходимости модели, < 1.05) и MQS - если < 1.05 и > 60 соответственно, модель надёжна для пилотных решений.',
    });
  }

  out.push({
    severity: 'info',
    text: 'После обучения вы увидите: декомпозицию продаж по каналам, ROI / mROAS, рекомендации по перераспределению бюджета, сценарии «что если».',
  });

  return out;
}

/**
 * @param {any} result
 * @returns {Insight[]}
 */
export function validateInsights(result, objective = 'roi') {
  /** @type {Insight[]} */
  const out = [];
  if (!result) return out;

  // v2.1.0 (rc2 retry): пересчёт effective status на frontend из текущих
  // ролей колонок. Раньше result.status был stale (backend value не
  // пересчитывался при frontend exclusions), приходилось видеть «error»
  // даже после фикса.
  /** @type {any[]} */
  const colsCheck = Array.isArray(result.columns) ? result.columns : [];
  const kpiCount = colsCheck.filter(/** @param {any} c */ c => c?.role === 'kpi').length;
  const mediaCount = colsCheck.filter(/** @param {any} c */ c => c?.role === 'media').length;
  const controlCount = colsCheck.filter(/** @param {any} c */ c => c?.role === 'control').length;
  const rowsCheck = result.file?.rows ?? result.detected?.rows ?? 0;
  const paramCountCheck = mediaCount + controlCount;
  const liveRatio = rowsCheck > 0 && paramCountCheck > 0 ? rowsCheck / paramCountCheck : 0;
  /** @type {'ok'|'warning'|'error'} */
  let effectiveStatus = 'ok';
  if (kpiCount !== 1 || mediaCount === 0 || liveRatio < 2) {
    effectiveStatus = 'error';
  } else if (liveRatio < 4) {
    effectiveStatus = 'warning';
  } else {
    // Если backend выдал warnings - keep warning
    effectiveStatus = (Array.isArray(result.warnings) && result.warnings.length > 0)
      ? 'warning' : 'ok';
  }

  // ── Общий статус ──
  if (effectiveStatus === 'ok') {
    out.push({ severity: 'success', text: 'Данные готовы к обучению модели. Структура валидна.' });
  } else if (effectiveStatus === 'warning') {
    if (liveRatio > 0 && liveRatio < 4) {
      out.push({
        severity: 'warning',
        text: `Ratio ${liveRatio.toFixed(1)}:1 - ниже рекомендованного 4:1. Модель работает, но с широкими доверительными интервалами.`,
        tip: 'Рекомендации по приоритету: (1) объединить парные метрики каналов, (2) конвертировать физические метрики в ₽ через CPP, (3) собрать ≥52 недели данных.',
      });
    } else {
      const warnCount = Array.isArray(result.warnings) ? result.warnings.length : 0;
      out.push({
        severity: 'warning',
        text: `Найдено ${warnCount} предупреждени${warnCount === 1 ? 'е' : warnCount < 5 ? 'я' : 'й'}. Модель можно запустить, но точность может быть ниже.`,
        tip: 'Предупреждения не блокируют моделирование, но каждое снижает надёжность результатов.',
      });
    }
  } else {
    // effectiveStatus === 'error': конкретное описание проблемы
    if (kpiCount === 0) {
      out.push({
        severity: 'error',
        text: 'Не выбрана целевая метрика. Назначьте одной колонке роль «Целевая метрика» в таблице ниже.',
        tip: 'Целевая метрика — это то, что модель будет объяснять: выручка, продажи в штуках, лиды, регистрации.',
      });
    } else if (kpiCount > 1) {
      const kpiNames = colsCheck
        .filter(/** @param {any} c */ c => c?.role === 'kpi')
        .map(/** @param {any} c */ c => `«${c.name}»`).slice(0, 3).join(', ');
      out.push({
        severity: 'error',
        text: `Найдено ${kpiCount} целевых метрик: ${kpiNames}. MMM-модель обучается на одной зависимой переменной.`,
        tip: 'Оставьте одну (главную для текущего режима), остальные отметьте как «Не использовать».',
      });
    } else if (mediaCount === 0) {
      out.push({
        severity: 'error',
        text: 'Нет активных медиа-каналов. Назначьте хотя бы одной колонке роль «Медиа-канал».',
        tip: 'Медиа-канал - это вложение в маркетинговую активность (бюджет канала или его физическая метрика - TRP/показы/клики).',
      });
    } else if (liveRatio < 2) {
      out.push({
        severity: 'error',
        text: `Ratio ${liveRatio.toFixed(1)}:1 - слишком мало данных (минимум 2:1, рекомендуется ≥4:1). Модель почти наверняка переобучится.`,
        tip: 'Приоритет действий: (1) объединить парные метрики каналов (бюджет + показы того же канала), (2) конвертация физических метрик в ₽, (3) собрать ≥52 недели данных.',
      });
    }
  }

  // v2.1.0 (rc2 retry): backward-compat для случаев когда backend выдал
  // critical issues которые не покрыты выше (специфичные data-type issues).
  // Сохраняем как «дополнительные критические проблемы» без префикса «status=error».
  if (effectiveStatus !== 'error' && result.status === 'error') {
    /** @type {any[]} */
    const criticalIssues = Array.isArray(result.issues) ? result.issues : [];
    const errorIssues = criticalIssues.filter(/** @param {any} i */ i =>
      (i?.severity === 'critical' || i?.severity === 'error') &&
      i?.type !== 'insufficient_data' &&  // покрыто выше через liveRatio
      i?.type !== 'low_data' &&
      i?.type !== 'borderline_data'
    );

    if (errorIssues.length === 0) {
      // status=error без issues - редкий case, generic message
      out.push({
        severity: 'error',
        text: 'Найдены критические проблемы со структурой данных.',
        tip: 'Откройте таблицу ролей ниже - проверьте что назначены: Целевая метрика (KPI), хотя бы один Медиа-канал, колонка Даты.',
      });
    } else {
      // Группируем по category для краткости
      /** @type {string[]} */
      const issuesList = errorIssues.slice(0, 4).map(/** @param {any} i */ i => {
        const colPart = i.column ? `«${i.column}»` : '';
        const msg = i.message || i.text || 'Проблема данных';
        return `• ${colPart} ${msg}`.trim();
      });
      const moreText = errorIssues.length > 4 ? `\n• …и ещё ${errorIssues.length - 4}` : '';

      out.push({
        severity: 'error',
        text: `Найдено ${errorIssues.length} критическ${errorIssues.length === 1 ? 'ая проблема' : errorIssues.length < 5 ? 'их проблемы' : 'их проблем'} с данными:\n${issuesList.join('\n')}${moreText}`,
        tip: 'Рекомендации по устранению: (1) проверьте назначение ролей в таблице ниже - должна быть Целевая метрика и хотя бы один Медиа-канал; (2) если колонка не должна участвовать в модели, отметьте её как «Не использовать»; (3) числовые колонки с нечисловыми значениями (например текстом «н/д») лучше очистить в исходном файле.',
      });
    }
  }

  // ── Распознанные роли колонок ──
  const cols = result.columns ?? [];
  const kpiCols = cols.filter(/** @param {any} c */ c => c.role === 'kpi');
  const mediaCols = cols.filter(/** @param {any} c */ c => c.role === 'media');
  const controlCols = cols.filter(/** @param {any} c */ c => c.role === 'control');
  const dateCols = cols.filter(/** @param {any} c */ c => c.role === 'date');

  // v2.1.0 (пилот 2026-05-17): auto-detect outlier колонок. Если control
  // или kpi колонка имеет sum в 100× больше max media sum → флагнуть как
  // вероятную ошибку данных. Пилот: «Продажи в руб. конкуренты» 195 млрд
  // при media 107 млн ломала Bayesian MMM (R²=-159%, 14774 divergences).
  // Без явного предупреждения юзер не догадается что фактор в 2000× больше
  // других ломает нормализацию.
  const maxMediaSum = mediaCols.reduce(
    /** @param {number} m @param {any} c */
    (m, c) => Math.max(m, Math.abs(Number(c.stats?.sum ?? 0))),
    0,
  );
  if (maxMediaSum > 0) {
    /** @type {Array<{name: string, sum: number, ratio: number, role: string}>} */
    const outliers = [];
    for (const c of [...controlCols, ...kpiCols]) {
      const sum = Math.abs(Number(c.stats?.sum ?? 0));
      if (sum > maxMediaSum * 100) {
        outliers.push({ name: c.name, sum, ratio: sum / maxMediaSum, role: c.role });
      }
    }
    if (outliers.length > 0) {
      const top = outliers[0];
      const fmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
      out.push({
        severity: 'warning',
        text: `Колонка «${top.name}» в ${Math.round(top.ratio)}× больше самого крупного медиа-канала (${fmt.format(Math.round(top.sum))} vs ${fmt.format(Math.round(maxMediaSum))}). Вероятно ошибка данных - проверьте единицы измерения (рубли vs копейки) или формат.`,
        tip: 'Bayesian MMM нормализует все переменные перед обучением. Фактор в 100× больше остальных доминирует при нормализации, что приводит к нестабильности модели (R-hat > 1.5, высокие отклонения сэмплера) и переобучению. Рекомендуем: либо исправить данные в Excel, либо пометить колонку как «Не использовать».',
      });
    }
  }

  if (kpiCols.length > 0 && mediaCols.length > 0) {
    out.push({ severity: 'success', text: `Распознано: KPI - ${kpiCols.map(/** @param {any} c */ c => c.name).join(', ')}, ${mediaCols.length} медиаканал${mediaCols.length > 4 ? 'ов' : mediaCols.length > 1 ? 'а' : ''}, ${controlCols.length} контрольн${controlCols.length === 1 ? 'ая' : 'ых'} переменн${controlCols.length === 1 ? 'ая' : 'ых'}.` });
  } else if (kpiCols.length === 0) {
    out.push({ severity: 'error', text: 'KPI не определён. Назначьте целевую метрику в таблице ролей.', tip: 'KPI - зависимая переменная, которую объясняет модель: продажи, выручка, конверсии.' });
  }

  // ── Объём данных vs параметры ──
  // Унифицированная формула rows / (media + control) - соответствует Python validator и индустриальной практике (rows-to-cols ratio).
  const totalRows = result.file?.rows ?? result.detected?.rows ?? 0;
  const paramCount = mediaCols.length + controlCols.length;
  if (totalRows > 0 && mediaCols.length > 0) {
    const ratio = totalRows / Math.max(paramCount, 1);

    // Найти каналы-кандидаты на исключение (>50% нулей) - для кнопки "Оптимизировать"
    const weakChannels = mediaCols
      .filter(/** @param {any} c */ c => (c.stats?.zeros_pct ?? 0) > 50)
      .sort(/** @param {any} a @param {any} b */ (a, b) => (b.stats?.zeros_pct ?? 0) - (a.stats?.zeros_pct ?? 0));
    const weakNames = weakChannels.map(/** @param {any} c */ c => c.name);

    // v2.1.0 (пилот 2026-05-16 U-03 + B-03): иерархия ratio-fix.
    // Раньше Aurora сразу предлагала «Исключить N каналов» - это
    // профессионально вредно (убивает ТВ/digital - omitted variable bias).
    // Новая логика: конверсия / сбор данных first, исключение last
    // и только для data quality issues (>50% нулей).
    //
    // Severity градация согласована с validationHeaderMetrics + ratio-classifier.js
    // (SEV-1, 2026-06-02, методологический порог по степеням свободы):
    //   ratio < 1:1 -> error (df ≤ 0, модель не определяется - параметров ≥ наблюдений)
    //   1-2:1 -> warning (критически мало, df > 0, только направление)
    //   2-3:1 -> warning (высокий)
    //   3-4:1 -> warning (обычный)
    //   4-5:1 -> info
    //   >= 5:1 -> success
    //
    // «Не определяется» теперь ТОЛЬКО при ratio < 1 (нет степеней свободы). При
    // 1 ≤ ratio < 2 Bayesian модель технически обучается (informative priors) -
    // это не ошибка, а высокий warning.

    /** Сколько каналов реально weak (>50% нулей) - кандидаты исключения.
     *  RC2-AUD-08 fix: если ВСЕ media каналы weak (mediaCols.length - weakNames.length === 0)
     *  и нет controls - модель невозможна (0 параметров). Не показываем
     *  обманчивый «после исключения ratio N:1». */
    const remainingPredictors = mediaCols.length - weakNames.length + controlCols.length;
    const weakRatio = weakNames.length > 0 && remainingPredictors > 0
      ? totalRows / remainingPredictors
      : null;  // null = «не считаем», caller должен fallback на сбор данных

    if (ratio < 1) {
      // SEV-1: df ≤ 0 - модель не определяется (параметров ≥ наблюдений, нет
      // единственного решения). Единственная зона настоящей «невозможности».
      out.push({
        severity: 'error',
        text: `Модель не определяется: ${paramCount} переменных при ${totalRows} наблюдениях (ratio ${ratio.toFixed(1)}:1). Параметров не меньше, чем точек данных - у модели нет единственного решения (нет степеней свободы).`,
        tip: `Сначала сократите число переменных или добавьте данные: (1) объедините парные метрики каналов (бюджет + показы одного канала = одна переменная); (2) исключите ${weakNames.length > 0 ? `${weakNames.length} каналов с >50% нулей` : 'каналы без активности'}; (3) соберите больше истории - недельная гранулярность даёт ~${Math.round(totalRows * 4.3)} наблюдений.`,
        action: weakNames.length > 0 ? { type: 'exclude', columns: weakNames, label: `Исключить ${weakNames.length} с >50% нулей` } : undefined,
      });
    } else if (ratio < 2) {
      // SEV-1: 1 ≤ ratio < 2 - модель идентифицируема и обучается (Кагоцел 1.7),
      // просто слабо. Не error (красный), а высокий warning (оранжевый).
      out.push({
        severity: 'warning',
        text: `Критически мало данных: ${totalRows} наблюдений / ${paramCount} переменных (ratio ${ratio.toFixed(1)}:1). Модель обучится, но результаты - только направление (что наращивать, что сокращать), не точные цифры. Приемлемо для пилота как ориентир.`,
        tip: `Bayesian модель обучится с информативными приорами, но доверительные интервалы будут широкими. Лучшие пути (по приоритету): (1) добавить данные - перейти на недельную гранулярность (${Math.round(totalRows * 4.3)} наблюдений) или собрать ещё ${Math.max(48 - totalRows, 12)} месяцев; (2) объединить парные метрики каналов (бюджет + показы одного канала = коллинеарность); (3) исключить ${weakNames.length > 0 ? `${weakNames.length} каналов с >50% нулей` : 'каналы без активности'} - только если их вклад в продажи действительно нулевой.`,
        action: weakNames.length > 0 ? { type: 'exclude', columns: weakNames, label: `Исключить ${weakNames.length} с >50% нулей` } : undefined,
      });
    } else if (ratio < 3) {
      out.push({
        severity: 'warning',
        text: `Критически мало данных: ratio ${ratio.toFixed(1)}:1 (минимум 4:1 для надёжной модели). Модель работает, но диапазоны возможных значений ROI будут шире — результаты как качественные ориентиры, не точные оценки.`,
        tip: `Приоритет действий: (1) объединить парные метрики (OLV Бюджет + OLV Показы = одна переменная); (2) ${weakRatio != null && weakNames.length > 0 ? `исключить ${weakNames.length} каналов с >50% нулей (после исключения ratio ${weakRatio.toFixed(1)}:1)` : weakNames.length > 0 ? `${weakNames.length} слабых каналов есть, но их исключение оставит модель без media - нужны новые данные` : 'добавить больше истории'}; (3) собрать ≥52 недели данных. Не исключайте основные media каналы (ТВ, OLV, Banners для бренда) без явных data quality проблем - это смещение из-за пропущенных переменных, ROI остальных каналов будет завышен.`,
        action: weakNames.length > 0 ? { type: 'exclude', columns: weakNames, label: `Исключить ${weakNames.length} с >50% нулей` } : undefined,
      });
    } else if (ratio < 4) {
      out.push({
        severity: 'warning',
        text: `Мало данных: ratio ${ratio.toFixed(1)}:1 (рекомендуется ≥4:1). Модель сойдётся, но с широкими диапазонами возможных значений.`,
        tip: `Для ${mediaCols.length} каналов оптимально ≥${mediaCols.length * 4} наблюдений. Доступные улучшения (по приоритету): объединение парных метрик > конверсия физических метрик в ₽ > сбор больше истории > исключение каналов с явными проблемами данных (>50% нулей).`,
        action: weakNames.length > 0 ? { type: 'exclude', columns: weakNames, label: `Исключить ${weakNames.length} с >50% нулей` } : undefined,
      });
    } else if (ratio < 5) {
      out.push({
        severity: 'info',
        text: `Ratio ${ratio.toFixed(1)}:1 - достаточно для пилота. Для production рекомендуется ≥4:1, для лучших доверительных интервалов ≥5:1.`,
      });
    } else {
      out.push({
        severity: 'success',
        text: `Ratio ${ratio.toFixed(1)}:1 - хорошее соотношение данных к параметрам. Модель надёжна.`,
      });
    }
  }

  // ── Предупреждения из валидации ──
  if (result.warnings?.length > 0) {
    for (const w of result.warnings) {
      // F-005 pilot (2026-05-18): не surfac'ить insufficient_data warning из
      // backend/objective-engine.recomputeResultAfterObjective. Тот же panel
      // уже эмитит fresh ratio insight (см. ratio rule с classifyRatio выше).
      // Stale `result.warnings[insufficient_data].message` мог содержать
      // pre-bulk-apply ratio (3.4) при том что fresh ratio 3.9 — конфликт SSOT.
      if (typeof w === 'object' && w !== null && w.type === 'insufficient_data') continue;
      const msg = typeof w === 'string' ? w : w?.message ?? w?.text ?? String(w);
      if (msg.toLowerCase().includes('корреляц') || msg.toLowerCase().includes('correl')) {
        out.push({ severity: 'warning', text: msg, tip: 'Высокая корреляция между каналами мешает модели разделить их вклады. Исключите один из пары или объедините в группу. В режиме «Эксперт» доступна корреляционная матрица и VIF.' });
      } else if (msg.toLowerCase().includes('нул') || msg.toLowerCase().includes('zero')) {
        out.push({ severity: 'warning', text: msg, tip: 'Каналы с >80% нулей дают нестабильные оценки ROI. Рекомендуем исключить их или агрегировать с аналогичным каналом.' });
      } else {
        out.push({ severity: 'warning', text: msg });
      }
    }
  }

  // ── Мультиколлинеарность (корреляции) ──
  if (result.correlations) {
    const seen = new Set();
    const highCorr = [];
    for (const [a, row] of Object.entries(result.correlations)) {
      for (const [b, r] of Object.entries(/** @type {Record<string, number>} */ (row))) {
        if (a === b) continue;
        const key = [a, b].sort().join('|');
        if (seen.has(key)) continue;
        seen.add(key);
        const absR = Math.abs(/** @type {number} */ (r));
        if (absR > 0.85) highCorr.push({ a, b, r: absR });
      }
    }
    if (highCorr.length > 0) {
      const pairs = highCorr.slice(0, 3).map(p => `${p.a} ↔ ${p.b} (r=${p.r.toFixed(2)})`).join('; ');
      out.push({ severity: 'warning', text: `Мультиколлинеарность: ${pairs}${highCorr.length > 3 ? ` и ещё ${highCorr.length - 3}` : ''}`, tip: 'Модель не сможет разделить вклады коррелирующих каналов. Решение: исключите один из пары, объедините в группу, или примите широкие доверительные интервалы.' });
    }
  }

  // ── Пропуски ──
  const missing = cols.filter(/** @param {any} c */ c => c.role !== 'unused' && c.stats?.missing_pct > 5);
  if (missing.length > 0) {
    const names = missing.map(/** @param {any} c */ c => `${c.name} (${c.stats.missing_pct.toFixed(0)}%)`).join(', ');
    out.push({ severity: 'warning', text: `Пропуски >5%: ${names}`, tip: 'Линейная интерполяция заполнит небольшие пробелы. При >20% пропусков столбец лучше исключить или найти альтернативный источник.' });
  }

  // ── Группировка парных колонок и рекомендации ──
  const VOLUME_KEYS = ['ПОКАЗ','ПРОСМОТР','КЛИК','ВИЗИТ','ПРОЧТЕН','GRP','TRP','OTS','IMPRESSION','CLICK','VIEW','VISIT','READ'];
  const COST_KEYS = ['БЮДЖЕТ','РАСХОД','ЗАТРАТ','СТОИМОСТЬ','SPEND','COST','BUDGET','РУБ'];

  /** @type {Map<string, {volume: any[], cost: any[]}>} */
  const channelGroups = new Map();

  // Canonical prefix: letters only + truncated to 6 chars (stemming - handles Russian plural vs singular, e.g. "СПЕЦПРОЕКТЫ"/"СПЕЦПРОЕКТ")
  /** @param {string} leading */
  const canonicalPrefix = (leading) => {
    const m = leading.match(/^[А-ЯЁA-Z]+/);
    return m ? m[0].slice(0, 6) : '';
  };

  for (const c of cols) {
    // Skip excluded columns - user-applied actions should not resurface them in insights
    if (c.role === 'unused') continue;
    const upper = (c.name ?? '').toUpperCase();
    // Extract channel prefix: everything before the metric keyword, canonicalized
    let prefix = '';
    let type = '';
    for (const k of VOLUME_KEYS) {
      const idx = upper.indexOf(k);
      if (idx > 0) { prefix = canonicalPrefix(upper.slice(0, idx)); type = 'volume'; break; }
    }
    if (!prefix) {
      for (const k of COST_KEYS) {
        const idx = upper.indexOf(k);
        if (idx > 0) { prefix = canonicalPrefix(upper.slice(0, idx)); type = 'cost'; break; }
      }
    }
    if (!prefix) continue;

    if (!channelGroups.has(prefix)) channelGroups.set(prefix, { volume: [], cost: [] });
    const g = channelGroups.get(prefix);
    if (!g) continue;  // unreachable due к has() above, но TS narrowing requires explicit guard
    if (type === 'volume') g.volume.push(c);
    else g.cost.push(c);
  }

  /** @type {Insight[]} */
  const channelRecs = [];
  for (const [prefix, g] of channelGroups) {
    const allCols = [...g.volume, ...g.cost];
    const allZero = allCols.every(/** @param {any} c */ c => (c.stats?.zeros_pct ?? 0) > 90);
    const highZero = allCols.every(/** @param {any} c */ c => (c.stats?.zeros_pct ?? 0) > 60);
    const hasCost = g.cost.length > 0;
    const hasVolume = g.volume.length > 0;
    const costNames = g.cost.map(/** @param {any} c */ c => c.name);
    const volNames = g.volume.map(/** @param {any} c */ c => c.name);

    if (allZero) {
      channelRecs.push({
        severity: 'warning',
        text: `${prefix}: все метрики >90% нулей (${allCols.map(/** @param {any} c */ c => c.name).join(', ')}). Канал неактивен - исключите из модели.`,
        action: { type: 'exclude', columns: allCols.map(/** @param {any} c */ c => c.name), label: 'Исключить канал' },
      });
    } else if (hasCost && hasVolume) {
      const costZeros = g.cost[0]?.stats?.zeros_pct ?? 0;
      const volZeros = g.volume[0]?.stats?.zeros_pct ?? 0;
      const costTooSparse = costZeros > 50 && costZeros > volZeros + 15; // override when budget gaps are severe

      // Objective-driven recommendation
      if (objective === 'roi' && !costTooSparse) {
        // ROI → keep budget (monetary attribution)
        channelRecs.push({
          severity: 'info',
          text: `${prefix}: парные метрики. Цель ROI → оставить бюджет (${costNames[0]}), исключить ${volNames.join(', ')}.`,
          tip: 'MMM моделирует зависимость KPI от затрат. Показы/клики - промежуточные метрики, коррелирующие с бюджетом. Для ROI-анализа нужен только денежный показатель.',
          action: { type: 'keep_only', columns: costNames.slice(0, 1), exclude: [...costNames.slice(1), ...volNames], label: 'Оставить бюджет' },
        });
      } else if (objective === 'effectiveness') {
        // Efficiency → keep natural metric (contact/volume-driven attribution)
        channelRecs.push({
          severity: 'info',
          text: `${prefix}: парные метрики. Цель Эффективность → оставить ${volNames[0]}, исключить ${[...costNames, ...volNames.slice(1)].join(', ')}.`,
          tip: 'При оценке эффективности медиа важны контакты (показы, клики, визиты), а не деньги. Бюджет уходит в расчёт стоимости контакта позднее.',
          action: { type: 'keep_only', columns: volNames.slice(0, 1), exclude: [...costNames, ...volNames.slice(1)], label: `Оставить ${volNames[0]}` },
        });
      } else {
        // Manual mode OR budget-too-sparse override - fallback to data-quality heuristic
        const reason = costTooSparse ? ` (бюджет ${costZeros.toFixed(0)}% нулей - слишком разрежен)` : '';
        channelRecs.push({
          severity: 'info',
          text: `${prefix}: парные метрики${reason}. Выберите базовую метрику.`,
          tip: 'Бюджет даёт прямой ROI; показы/клики показывают физическую активность. Модель может работать только с одной из них.',
          action: { type: 'keep_only', columns: costNames.slice(0, 1), exclude: [...costNames.slice(1), ...volNames], label: 'Оставить бюджет' },
          secondaryAction: { type: 'keep_only', columns: volNames.slice(0, 1), exclude: [...costNames, ...volNames.slice(1)], label: `Оставить ${volNames[0]}` },
        });
      }
    } else if (hasVolume && g.volume.length > 1) {
      channelRecs.push({
        severity: 'info',
        text: `${prefix}: ${g.volume.length} метрик (${volNames.join(', ')}). Оставьте одну наиболее полную.`,
        tip: 'Показы, клики, визиты одного канала сильно коррелируют. Модели достаточно одной метрики.',
        action: { type: 'keep_only', columns: [volNames[0]], exclude: volNames.slice(1), label: `Оставить ${volNames[0]}` },
      });
    } else if (highZero && allCols.length === 1) {
      channelRecs.push({
        severity: 'warning',
        text: `${prefix} (${allCols[0].name}): ${(allCols[0].stats?.zeros_pct ?? 0).toFixed(0)}% нулей - исключите или объедините.`,
        action: { type: 'exclude', columns: [allCols[0].name], label: 'Исключить' },
      });
    }
  }

  // Also catch standalone high-zero columns not in groups
  const groupedNames = new Set();
  for (const [, g] of channelGroups) {
    for (const c of [...g.volume, ...g.cost]) groupedNames.add(c.name);
  }
  const ungroupedZero = mediaCols.filter(/** @param {any} c */ c => !groupedNames.has(c.name) && (c.stats?.zeros_pct ?? 0) > 60);
  for (const c of ungroupedZero) {
    const pct = c.stats?.zeros_pct ?? 0;
    if (pct > 90) {
      channelRecs.push({ severity: 'warning', text: `${c.name}: ${pct.toFixed(0)}% нулей - исключите.`, action: { type: 'exclude', columns: [c.name], label: 'Исключить' } });
    } else {
      channelRecs.push({ severity: 'warning', text: `${c.name}: ${pct.toFixed(0)}% нулей - объединить или оставить с оговоркой.`, action: { type: 'exclude', columns: [c.name], label: 'Исключить' } });
    }
  }

  // ── Bulk-apply: единая кнопка "Применить цель" для всех парных каналов ──
  // Вынесено ВЫШЕ per-channel recs и независимо от channelRecs.length, чтобы быть первым видимым инсайтом.
  /** @type {string[]} */
  const bulkExclude = [];
  let keepCount = 0;
  for (const [, g] of channelGroups) {
    if (g.cost.length === 0 && g.volume.length === 0) continue;
    const hasBoth = g.cost.length > 0 && g.volume.length > 0;
    if (objective === 'roi' && g.cost.length > 0) {
      keepCount += 1;
      bulkExclude.push(...g.cost.slice(1).map(/** @param {any} c */ c => c.name));
      if (hasBoth) bulkExclude.push(...g.volume.map(/** @param {any} c */ c => c.name));
    } else if (objective === 'effectiveness' && g.volume.length > 0) {
      keepCount += 1;
      bulkExclude.push(...g.volume.slice(1).map(/** @param {any} c */ c => c.name));
      if (hasBoth) bulkExclude.push(...g.cost.map(/** @param {any} c */ c => c.name));
    }
  }
  const bulkHasEffect = bulkExclude.length >= 1 && (objective === 'roi' || objective === 'effectiveness');
  if (bulkHasEffect) {
    const label = objective === 'roi'
      ? `Оставить бюджеты (${keepCount} канала)`
      : `Оставить медийные метрики (${keepCount} канала)`;
    const text = objective === 'roi'
      ? `Цель: ROI (финансовая отдача). Оставим бюджет для каждого канала, исключим ${bulkExclude.length} промежуточных метрик (показы/клики/визиты).`
      : `Цель: Эффективность (физические контакты). Оставим показы/клики для каждого канала, исключим ${bulkExclude.length} бюджетных дублей.`;
    out.push({
      severity: 'info',
      text,
      tip: 'Переключите цель анализа вверху (ROI / Эффективность / Вручную), чтобы увидеть другой сценарий очистки.',
      action: { type: 'exclude', columns: bulkExclude, label },
    });
  } else if (objective === 'manual' && channelGroups.size > 0) {
    out.push({
      severity: 'info',
      text: `Режим «Вручную»: выберите метрику для каждого канала ниже. Переключите цель на ROI/Эффективность для авто-очистки.`,
    });
  }

  if (channelRecs.length > 0) {
    if (!bulkHasEffect && objective !== 'manual') {
      out.push({ severity: 'info', text: `Анализ каналов: ${channelGroups.size} групп обнаружено. Рекомендации ниже.` });
    }
    out.push(...channelRecs);
  }

  // ── Группировка слабых каналов → предложение объединить ──
  const allWeakMedia = mediaCols.filter(/** @param {any} c */ c => {
    const z = c.stats?.zeros_pct ?? 0;
    return z > 50 && z <= 90; // >90% → исключить, 50-90% → кандидат на объединение
  });
  if (allWeakMedia.length >= 2) {
    const weakNames = allWeakMedia.map(/** @param {any} c */ c => c.name);
    const avgZeros = allWeakMedia.reduce(/** @param {number} sum @param {any} c */ (sum, c) => sum + (c.stats?.zeros_pct ?? 0), 0) / allWeakMedia.length;
    // Наследование money-маркера: если ВСЕ источники содержат один и тот же
    // денежный индикатор (НДС/VAT/руб/₽/RUB) - добавляем его в имя merged
    // канала, чтобы UnitCostsPanel корректно пропускал его (суммированные
    // рубли остаются рублями, unit_cost=1 не нужен).
    /** @type {Array<{re: RegExp, suffix: string}>} */
    const MONEY_MARKERS = [
      { re: /до\s+НДС/i, suffix: ' до НДС' },
      { re: /без\s+НДС/i, suffix: ' без НДС' },
      { re: /с\s+НДС/i,   suffix: ' с НДС' },
      { re: /НДС/i,       suffix: ' НДС' },
      { re: /VAT/i,       suffix: ' VAT' },
      { re: /RUB/i,       suffix: ' RUB' },
      { re: /₽/,          suffix: ' ₽' },
      { re: /(^|[\s\(])руб/i, suffix: ' в руб' },
    ];
    let nameSuffix = '';
    for (const m of MONEY_MARKERS) {
      if (weakNames.every(/** @param {any} n */ n => m.re.test(String(n)))) {
        nameSuffix = m.suffix;
        break;
      }
    }
    const mergedName = `Малые медиа${nameSuffix}`;
    out.push({
      severity: 'info',
      text: `${allWeakMedia.length} каналов с 50-90% нулей (${weakNames.join(', ')}). Объедините их в один «${mergedName}» - суммарный сигнал будет сильнее.`,
      tip: `Каждый канал по отдельности слишком разреженный (в среднем ${avgZeros.toFixed(0)}% нулей). Объединение суммирует их активность - модель получит более стабильную оценку ROI для группы.`,
      action: { type: 'merge', columns: weakNames, mergedName, label: `Объединить ${allWeakMedia.length} канала` },
    });
  }

  // ── Динамическая оценка готовности (цепочка рекомендаций) ──
  // Формула едина с Python validator: ratio = rows / (media + control) variables.
  const currentRatio = totalRows > 0 && mediaCols.length > 0 ? totalRows / Math.max(mediaCols.length + controlCols.length, 1) : 0;
  const maxChannels = Math.max(2, Math.floor(totalRows / 4) - controlCols.length);
  const excessChannels = mediaCols.length - maxChannels;

  // Шаг 1: нет KPI → предложить назначить
  if (kpiCols.length === 0 && cols.length > 0) {
    // Найти кандидатов на KPI (продажи, выручка)
    const kpiCandidates = cols.filter(/** @param {any} c */ c =>
      c.role !== 'unused' && c.role !== 'date' && c.stats?.zeros_pct < 10 &&
      /продаж|sales|revenue|выручк|units|volume/i.test(c.name)
    );
    if (kpiCandidates.length > 0) {
      const bestName = kpiCandidates[0].name;
      out.push({
        severity: 'error',
        text: `KPI не назначен. Похоже, «${bestName}» - целевой показатель. Назначьте его как KPI.`,
        action: { type: 'set_role', columns: [bestName], label: `Назначить ${bestName} как KPI` },
      });
    } else {
      out.push({ severity: 'error', text: 'KPI не назначен. Выберите целевой показатель (продажи, выручка) в таблице ролей.' });
    }
  }

  // Шаг 2: слишком много каналов → предложить автооптимизацию
  if (mediaCols.length > 0 && excessChannels > 0) {
    // Ранжировать каналы: чем больше нулей → тем слабее
    const ranked = [...mediaCols]
      .filter(/** @param {any} c */ c => !c.merged_from) // не трогаем объединённые
      .sort(/** @param {any} a @param {any} b */ (a, b) => (b.stats?.zeros_pct ?? 0) - (a.stats?.zeros_pct ?? 0));
    const toExclude = ranked.slice(0, excessChannels).map(/** @param {any} c */ c => c.name);
    const afterRatio = totalRows / Math.max((mediaCols.length - toExclude.length) + controlCols.length, 1);

    if (currentRatio < 2) {
      out.push({
        severity: 'error',
        text: `Ratio ${currentRatio.toFixed(1)}:1 - критически мало. Нужно ≤${maxChannels} каналов (сейчас ${mediaCols.length}). Исключите ${toExclude.length} слабейших → ratio станет ${afterRatio.toFixed(1)}:1.`,
        tip: `Будут исключены: ${toExclude.join(', ')}. Это каналы с наибольшей долей нулей, вклад которых модель не сможет оценить надёжно.`,
        action: { type: 'exclude', columns: toExclude, label: `Оптимизировать: оставить ${maxChannels} каналов` },
      });
    } else if (currentRatio < 4) {
      out.push({
        severity: 'warning',
        text: `Ratio ${currentRatio.toFixed(1)}:1 (рекомендуется ≥4:1). Исключите ${toExclude.length} каналов → ratio ${afterRatio.toFixed(1)}:1.`,
        action: { type: 'exclude', columns: toExclude, label: `Оптимизировать до ${maxChannels} каналов` },
      });
    }
  }

  // Шаг 3: ratio ok, но есть предупреждения
  if (currentRatio >= 4 && mediaCols.length > 0 && kpiCols.length > 0) {
    const warnCount = out.filter(i => i.severity === 'warning').length;
    if (warnCount === 0) {
      out.push({ severity: 'success', text: `Данные готовы к моделированию. ${mediaCols.length} каналов, ratio ${currentRatio.toFixed(1)}:1. Нажмите «Далее».` });
    } else {
      out.push({ severity: 'info', text: `Ratio ${currentRatio.toFixed(1)}:1 - допустимо. ${warnCount} предупреждений не блокируют моделирование, но могут снизить точность.` });
    }
  } else if (currentRatio >= 2 && currentRatio < 4 && excessChannels <= 0 && kpiCols.length > 0) {
    out.push({
      severity: 'warning',
      text: `Ratio ${currentRatio.toFixed(1)}:1 - на грани. Модель посчитает, но доверительные интервалы будут широкими. Для надёжных результатов нужно ≥52 наблюдения.`,
      tip: 'Байесовский подход (PyMC) работает лучше частотного при малых выборках, но не творит чудеса. Интерпретируйте результаты осторожно.',
    });
  }

  return out;
}

// ── Model Step ──────────────────────────────────────────

/**
 * @param {{ diagnostics: { mqs: { score: number, tier_label: string }, r_squared: number, mape: number, r_hat: number, divergences: number }, channelParams: Record<string, any> }} data
 * @returns {Insight[]}
 */
/**
 * Pre-training insights - shown on Model step BEFORE training is launched.
 * Uses the validated data context to educate & warn the user.
 *
 * @param {any} validateResult - the validator output stored in validateData.result
 * @param {string[]} [enabledMediaNames] - v2.1.0 (пилот 2026-05-16): имена
 *   реально активных каналов на шаге Модель (с галочками). Если передано -
 *   счётчики и ratio считаются по нему, а не по всем media-ролям из
 *   validateResult. Это устраняет рассинхрон «10 медиаканалов» в инсайте
 *   при 7 включённых чекбоксах.
 * @returns {Insight[]}
 */
export function modelPreTrainingInsights(validateResult, enabledMediaNames = undefined) {
  /** @type {Insight[]} */
  const out = [];
  if (!validateResult) return out;

  const cols = validateResult.columns ?? [];
  const allMediaCols = cols.filter(/** @param {any} c */ c => c.role === 'media');
  // v2.1.0 (пилот 2026-05-16): если ConfigPanel передал список active каналов -
  // считаем по нему. Иначе fallback - все media-роли.
  const activeMediaCols = Array.isArray(enabledMediaNames)
    ? allMediaCols.filter(/** @param {any} c */ c => enabledMediaNames.includes(c.name))
    : allMediaCols;
  const mediaCount = activeMediaCols.length;
  const controlCount = cols.filter(/** @param {any} c */ c => c.role === 'control').length;
  const kpiNames = cols.filter(/** @param {any} c */ c => c.role === 'kpi').map(/** @param {any} c */ c => c.name);
  const mediaNames = activeMediaCols.map(/** @param {any} c */ c => c.name);
  const rows = validateResult.file?.rows ?? 0;
  // v2.1.0 (RC2-AUD-04 fix): ratio считается из ТЕКУЩИХ ролей колонок
  // (как в validateInsights), не из stale validateResult.detected.ratio
  // (которое было посчитано один раз при первом econ_validate).
  // Это устраняет рассогласование с SSOT validationHeaderMetrics.
  const paramCount = mediaCount + controlCount;
  const ratio = rows > 0 && paramCount > 0 ? rows / paramCount : 0;

  // ── 1. Ready-state summary ──
  if (kpiNames.length > 0 && mediaCount > 0) {
    out.push({
      severity: 'success',
      // F-009 pilot (2026-05-18): explicit «+ 12 праздников РФ auto» чтобы
      // counter на Model не расходился с Validation (где holidays bundle не
      // считается). Customer видит откуда возможная разница.
      text: `Готово к обучению: KPI «${kpiNames[0]}», ${mediaCount} медиаканал${mediaCount > 4 ? 'ов' : mediaCount > 1 ? 'а' : ''}${controlCount > 0 ? `, ${controlCount} контрольн${controlCount === 1 ? 'ая' : 'ых'} переменн${controlCount === 1 ? 'ая' : 'ых'} (+ 12 праздников РФ auto)` : ' (+ 12 праздников РФ auto)'}.`,
    });
  }

  // ── 2. What MMM does (education) ──
  out.push({
    severity: 'info',
    text: 'Что происходит: модель оценит вклад каждого канала в KPI через Байесовскую регрессию с учётом отложенного эффекта (Adstock) и насыщения (Hill).',
    tip: 'Результат - ROI и маргинальная отдача каждого канала. На шаге «Оптимизация» сможете перераспределить бюджет, на «Декомпозиции» - увидеть вклад по времени.',
  });

  // ── 3. Adstock guidance ──
  out.push({
    severity: 'info',
    text: 'Adstock: «Geometric» - быстрый спад эффекта (1-2 недели, digital). «Weibull» - плавная кривая с build-up (TV, OOH, Радио).',
    tip: 'Geometric: стандарт для OLV, Banners, Social, Performance, Search - эффект рекламы затухает экспоненциально после контакта. Weibull: лучше для охватных (TV, OOH, Радио, Пресса) - эффект нарастает и уходит медленнее. «Авто» - программа выбирает по имени канала.',
  });

  // ── 3b. v2.1.0 (пилот 2026-05-17): явная информация про auto-injected
  // holidays. Backend modeler.py:267 добавляет 12 РФ праздников как control
  // (ADR-019 §5). Юзер не выбирал их и удивляется когда видит в декомпозиции.
  out.push({
    severity: 'info',
    text: 'К контрольным переменным автоматически добавляется 12 праздников РФ (Новый год, 23 февраля, 8 марта, майские, 1 сентября и др.). Это нужно чтобы модель не приписывала сезонные скачки продаж рекламе.',
    tip: 'Если не нужно учитывать праздники - перейдите в Эксперт-режим и снимите соответствующие галочки в Расширенных настройках. Праздники проходят как обычные controls с собственным коэффициентом.',
  });

  // ── 4. Ratio-based warning - v2.1.0 (пилот 2026-05-16): SSOT classifyRatio
  // вернёт label/description согласованные с RatioInfoCard и Контроль качества.
  if (ratio > 0) {
    const cls = classifyRatio(ratio);
    /** @type {'error' | 'warning' | 'info' | 'success'} */
    let sev;
    if (cls.severity === 'error') sev = 'error';
    else if (cls.severity === 'warning-high' || cls.severity === 'warning') sev = 'warning';
    else if (cls.severity === 'info') sev = 'info';
    else sev = 'success';

    if (sev === 'success' || sev === 'info') {
      out.push({
        severity: sev,
        text: `Ratio ${ratio.toFixed(1)}:1 - ${cls.label.toLowerCase()}. ${cls.description}.`,
      });
    } else {
      out.push({
        severity: sev,
        text: `Ratio ${ratio.toFixed(1)}:1 - ${cls.label.toLowerCase()}. ${cls.description}.`,
        tip: `Байесовская MMM работает с малыми выборками, но при ${rows} наблюдениях на ${mediaCount + controlCount} переменных отдельные каналы могут быть слабо значимы. Интерпретируйте ROI по top-3 каналам с наибольшим вкладом.`,
      });
    }
  }

  // ── 5. Virtual merged channel warning ──
  const hasMerged = cols.some(/** @param {any} c */ c => c.role === 'media' && Array.isArray(c.merged_from));
  if (hasMerged) {
    const mergedCol = cols.find(/** @param {any} c */ c => c.role === 'media' && Array.isArray(c.merged_from));
    out.push({
      severity: 'info',
      text: `Канал «${mergedCol.name}» - объединённый из ${mergedCol.merged_from.length} столбцов. Модель оценит ROI группы как целого.`,
      tip: `Объединено: ${mergedCol.merged_from.join(', ')}. Если после обучения ROI группы высок - можно разделить её обратно и обучить отдельно на большем объёме данных.`,
    });
  }

  // ── 6. What to watch after training ──
  out.push({
    severity: 'info',
    text: 'После обучения смотрим: MQS (качество модели, ≥60) · R² (объяснительная сила, ≥0.7) · R-hat (показатель сходимости модели, < 1.05 значит модель надёжна).',
    tip: 'MQS - агрегированная оценка качества от 0 до 100. R² - доля объяснённой вариации KPI. R-hat — показатель сходимости байесовских цепей; если > 1.05 — увеличьте число итераций (Расширенные настройки, режим Эксперт).',
  });

  // ── 7. Time estimate (educational) - v2.1.0 (пилот 2026-05-16): считаем
  // по active каналам, не по всем media-ролям. Раньше показывал «~4 мин
  // для 10 каналов» при 7 включённых чекбоксах.
  // JAX/NumPyro NUTS на CPU: ~1-3 мин на 4-8 каналах при дефолтах (4×(2000+2000) samples).
  // Формула синхронизирована с ConfigPanel.svelte estimateMinutes (JIT + ~5-10 мс/sample).
  const estimatedMinutes = Math.max(1, Math.round(0.3 * mediaCount + 1));
  if (mediaCount > 5) {
    out.push({
      severity: 'info',
      text: `Оценка времени: ~${estimatedMinutes} мин для ${mediaCount} каналов на движке JAX/NumPyro. Для быстрого прогона можно уменьшить draws в Расширенных настройках (режим Эксперт).`,
      tip: 'Байесовский Markov Chain Monte Carlo (NUTS) проходит две фазы: warmup (подбор step-size) и sampling (основные выборки). Первый запуск включает ~20 сек JIT-компиляции XLA - далее каждый sample занимает миллисекунды.',
    });
  }

  return out;
}

/**
 * @param {any} data
 * @param {number} [ratioOverride] v2.1.0 (пилот 2026-05-16): SSOT ratio из
 *   frontend validationMetrics. Backend `m.ratio` иногда расходится с тем,
 *   что юзер видел на Валидации (Антон в пилоте: «Ратио в расчёте было 3.9,
 *   на модели опять неверные ratio»). Frontend SSOT использует ту же
 *   формулу что в Валидации - один источник правды.
 */
export function modelInsights(data, ratioOverride = undefined) {
  /** @type {Insight[]} */
  const out = [];
  if (!data?.diagnostics) return out;

  const d = data.diagnostics;
  // Backend nests metrics under diagnostics.metrics; legacy paths kept flat values.
  const m = d.metrics ?? d;
  const rSq = m.r_squared ?? d.r_squared ?? 0;
  const mape = m.mape_pct ?? d.mape ?? 0;
  const rHat = m.r_hat_max ?? d.r_hat ?? 0;
  const divergences = m.divergences ?? d.divergences ?? 0;
  // INV-50 анти-рецидив (2026-06-07): MQS и effective ratio — ТОЛЬКО через единый
  // селектор metric-views. ratioView отдаёт честный backend effective ratio
  // (obs/effective_params); ratioOverride (pre-train media-ratio ≈ 4.4) допустим
  // лишь как fallback. mqsView отдаёт честный backend score (cap по эффективным
  // параметрам). Это закрывает «N слоёв» honesty-бага одним источником: media-ratio
  // больше не вытеснит effective, score не раскопается. См. metric-views.js.
  const _mqsV = mqsView(d);
  const _ratioV = ratioView(d, ratioOverride ?? null);
  const ratio = _ratioV?.ratio ?? 0;
  /** @type {number} */
  const mqs = _mqsV?.score ?? 0;
  /** @type {string} */
  const label = _mqsV?.tierLabel ?? '';
  const thinnessCap = _mqsV?.thinnessCap ?? null;
  const isThin = _ratioV?.isThin ?? false;
  const isVeryThin = _ratioV?.isVeryThin ?? false;
  // Имя ratio зависит от источника: backend post-train = «Эффективный Ratio»
  // (наблюдения ÷ effective_params), pre-train fallback = «Ratio данных»
  // (÷ выбранные колонки). Разводим явно — иначе 4.4 (Валидация) vs 2.9 (после
  // обучения) читается клиентом как ошибка (репорт 2026-06-13).
  const ratioName = _ratioV?.source === 'effective' ? 'Эффективный Ratio' : 'Ratio данных';
  const ratioBridge = _ratioV?.source === 'effective'
    ? ' Примечание: это наблюдения ÷ параметры обученной модели — обычно ниже «Ratio данных» с шага Валидация (÷ выбранные колонки), т.к. модель оценивает больше параметров, чем колонок (трансформации каналов, сезонность). Расхождение нормально, не ошибка.'
    : '';
  const channels = data.channelParams ? Object.keys(data.channelParams) : [];
  const nChannels = channels.length;

  // v2.1.0 (пилот 2026-05-17 audit H-1): catastrophe warning при R²<0 /
  // MAPE>50%. Раньше R²<0 не имел отдельной ветки - модель не сошлась,
  // но юзер видел только generic thinness warning без actionable hint.
  if (rSq < 0 || mape > 100) {
    out.push({
      severity: 'error',
      text: `⚠ Модель НЕ сошлась: R² = ${(rSq * 100).toFixed(0)}% (отрицательный означает «модель хуже среднего»), MAPE = ${mape.toFixed(0)}%. Результаты не интерпретируйте.`,
      tip: 'Возможные причины: (1) outlier-фактор в данных - проверьте «Объём за период» в Валидации, если одна колонка в 100× больше других - пометьте её «Не использовать»; (2) mixed mode (KPI=шт, media=₽) без задания CPP/CPM - конверсии нет, модель путается; (3) сильная мультиколлинеарность - объедините парные каналы (OLV Бюджет+OLV Показы); (4) попробуйте упростить модель: 4-5 каналов вместо 10+, режим OLS вместо Bayesian.',
    });
  } else if (rHat > 1.5 || divergences / Math.max(8000, 1) > 0.05) {
    out.push({
      severity: 'error',
      text: `⚠ Модель не завершила расчёт корректно (показатель сходимости R-hat = ${rHat.toFixed(2)}, норма < 1.05), дивергенций ${divergences} (${(divergences / 80).toFixed(1)}%). Доверять выводам нельзя.`,
      tip: 'Действия: упростите модель (меньше каналов / контрольных), проверьте outlier-факторы в Валидации, либо переключитесь в режим OLS (Расширенные настройки → Эксперт) - он работает на малых выборках стабильнее Bayesian.',
    });
  }

  // ── 0. Data thinness warning - trumps everything else ──
  // v2.1.0 (пилот 2026-05-16): SSOT classifyRatio для label/description -
  // согласовано с RatioInfoCard, sticky header, Контроль качества Валидации.
  if (ratio > 0) {
    const cls = classifyRatio(ratio);
    if (cls.severity === 'error') {
      out.push({
        severity: 'error',
        text: `⚠ ${ratioName} ${ratio.toFixed(1)}:1 - ${cls.label.toLowerCase()}. ${cls.description}. Модель может «выучить» точки, а не закономерность - высокий R² здесь артефакт переобучения.`,
        tip: 'Рекомендуем: увеличить историю до ≥52 недель, либо упростить модель (меньше каналов, перевести недели в месяцы). ROI и декомпозиция ненадёжны при таком Ratio.' + ratioBridge,
      });
    } else if (cls.severity === 'warning-high' || cls.severity === 'warning') {
      out.push({
        severity: 'warning',
        text: `${ratioName} ${ratio.toFixed(1)}:1 - ${cls.label.toLowerCase()}. ${cls.description}. Высокий R² может быть артефактом переобучения.`,
        tip: 'Bayesian MMM с приорами (априорными ожиданиями) смягчает проблему, но не устраняет. Относитесь к декомпозиции как к ориентиру, а не истине. Для надёжности — ≥52 недель данных.' + ratioBridge,
      });
    }
  }

  // ── 0b. OVB-guardrail (#6, 2026-06-07): per-control contraction подсказка ──
  // Неинформативные контроли (contraction<0.1, posterior≈prior — данные их не
  // определили) можно убрать без omitted-variable bias и без нечестного роста MQS;
  // информативные убирать нельзя (сместит media-ROI + накрутит MQS-cap). Цель —
  // чистота модели, НЕ накрутка балла. Источник: diagnostics.per_control_contraction.
  const pcc = d.per_control_contraction;
  if (pcc && typeof pcc === 'object') {
    const pccEntries = Object.entries(pcc).filter(
      /** @param {[string, any]} e */ (e) => typeof e[1] === 'number');
    const uninform = pccEntries.filter(/** @param {[string, number]} e */ (e) => e[1] < 0.1).map((e) => e[0]);
    const informCount = pccEntries.length - uninform.length;
    if (pccEntries.length > 0 && uninform.length > 0) {
      // Авто-праздники РФ (holiday_*) — синтетические контроли. #6 (2026-06-07): теперь
      // их МОЖНО отключить в панели «Авто-праздники РФ» на шаге «Валидация» (toggle
      // реализован → даём actionable-подсказку). Data-колонки-контроли убираются ролью
      // «не использовать». Сырые машинные имена праздников клиенту не показываем.
      const dataCtrls = uninform.filter((/** @type {string} */ n) => !/^holiday_/i.test(n));
      const holidayCtrls = uninform.filter((/** @type {string} */ n) => /^holiday_/i.test(n));
      /** @type {string[]} */
      const tipParts = [];
      if (dataCtrls.length > 0) {
        const shown = dataCtrls.slice(0, 6).join(', ') + (dataCtrls.length > 6 ? ` и ещё ${dataCtrls.length - 6}` : '');
        tipParts.push(`Контроли-колонки данных (${shown}) можно отключить на шаге «Валидация» (роль → «не использовать») для простоты — это НЕ изменит ROI каналов, честный MQS и Эффективный Ratio, они и так вносили ≈0 эффективных параметров.`);
      }
      if (holidayCtrls.length > 0) {
        tipParts.push(`${holidayCtrls.length} праздник(ов) РФ внесли ≈0 (даты почти не попали в период данных) — их можно отключить в панели «Авто-праздники РФ» на шаге «Валидация» (помечены «не повлиял») и переобучить для чистоты модели. ROI каналов, честный MQS и Эффективный Ratio при этом НЕ изменятся — эти праздники и так вносили ≈0 эффективных параметров (Ratio считается по эффективным степеням свободы, не по числу праздников), поэтому отключение незначимых его не поднимет; поднять Эффективный Ratio можно только бóльшим объёмом данных.`);
      }
      tipParts.push(`Информативные контроли (${informCount}: сезонность/праздники/конкуренты, реально влияющие на продажи) убирать НЕ нужно — удаление сместит ROI медиа (omitted variable bias) и нечестно поднимет MQS. Цель — чистота модели, а не накрутка балла.`);
      out.push({
        severity: 'info',
        text: `🧹 Контроли: ${uninform.length} из ${pccEntries.length} внесли почти ноль — модель их не определила.`,
        tip: tipParts.join(' '),
      });
    }
  }

  // ── 1. Headline verdict (MQS-based) ──
  const thinSuffix = isThin ? ' Учитывайте, что данных мало - CI широкие.' : '';
  if (mqs >= 80) {
    out.push({
      severity: 'success',
      text: `MQS = ${mqs.toFixed(0)} (${label}) - высокое качество модели. Результаты надёжны для принятия решений.${thinSuffix}`,
      tip: 'Перейдите к Декомпозиции, чтобы увидеть вклад каждого канала, и к Оптимизации - для перераспределения бюджета.',
    });
  } else if (mqs >= 60) {
    out.push({
      severity: 'info',
      text: `MQS = ${mqs.toFixed(0)} (${label}) - приемлемое качество.${thinSuffix}`,
      tip: thinnessCap
        ? `MQS снижен из-за недостатка данных (Ratio ${ratio.toFixed(1)}:1). На толстых данных та же модель получила бы выше. Для решения: больше истории или меньше каналов.`
        : 'Можно работать, но добавление контрольных переменных (сезонность, праздники, промо) поднимет MQS и сузит CI.',
    });
  } else {
    out.push({
      severity: 'warning',
      text: `MQS = ${mqs.toFixed(0)} (${label}) - модель требует доработки.${thinSuffix}`,
      tip: 'Попробуйте: добавить промо-переменные, увеличить draws, проверить качество данных.',
    });
  }

  // ── 2. Convergence - positive signals ──
  if (rHat > 0 && rHat <= 1.01 && divergences === 0) {
    const convergenceText = isThin
      ? `Модель сошлась технически (показатель сходимости R-hat = ${rHat.toFixed(3)}, дивергенций = 0), но это не гарантирует содержательной надёжности на коротких данных.`
      : `Модель сошлась идеально: показатель сходимости R-hat = ${rHat.toFixed(3)}, дивергенций = 0. Результаты надёжны для оценки ROI и диапазонов.`;
    const convergenceTip = isThin
      ? 'Сэмплер корректно исследовал пространство параметров, но при Ratio < 4:1 «пространство» само по себе слабо ограничено данными. Модель могла сойтись к переобученному решению.'
      : 'R-hat ≤ 1.01 означает, что независимые цепи сошлись к одному распределению. 0 дивергенций — сэмплер исследовал всё пространство параметров без скачков. Posterior надёжен для оценки ROI и диапазонов значений.';
    out.push({
      severity: isThin ? 'info' : 'success',
      text: convergenceText,
      tip: convergenceTip,
    });
  } else if (rHat > 1.05) {
    out.push({
      severity: 'error',
      text: `Модель не завершила расчёт. Показатель сходимости R-hat = ${rHat.toFixed(3)} — результаты ненадёжны.`,
      tip: 'Увеличьте draws (2000+) и tune (2000+). Если не помогает - упростите модель (меньше каналов).',
    });
  } else if (rHat > 1.01) {
    out.push({
      severity: 'warning',
      text: `Показатель сходимости R-hat = ${rHat.toFixed(3)} — модель почти сошлась. Рассмотрите увеличение числа итераций.`,
    });
  }

  if (divergences > 0 && rHat <= 1.05) {
    out.push({
      severity: 'warning',
      text: `${divergences} дивергенций в Markov Chain Monte Carlo. Модель может быть нестабильна.`,
      tip: 'Дивергенции = сэмплер не смог исследовать часть пространства параметров. Увеличьте target_accept (0.9 → 0.95) или tune.',
    });
  }

  // ── 3. Fit metrics - positive signals ──
  if (rSq >= 0.9) {
    out.push({
      severity: isThin ? 'info' : 'success',
      text: isThin
        ? `R² = ${rSq.toFixed(3)} - очень высокий fit, но на коротких данных (${ratioName} ${ratio.toFixed(1)}:1) это признак переобучения, а не силы модели.`
        : `R² = ${rSq.toFixed(3)} - модель объясняет ${(rSq * 100).toFixed(0)}% вариации KPI. Очень сильный fit.`,
      tip: isThin
        ? 'На тонких данных R² стремится к 1 автоматически: модель подгоняется под каждую точку. Это НЕ означает, что декомпозиция каналов верна. Out-of-sample валидация невозможна (нет hold-out набора).'
        : 'R² ≥ 90% - модель захватывает почти всю динамику продаж. Прогнозы устойчивы, декомпозиция вкладов правдоподобна.',
    });
  } else if (rSq >= 0.7) {
    out.push({
      severity: 'success',
      text: `R² = ${rSq.toFixed(3)} - модель объясняет ${(rSq * 100).toFixed(0)}% вариации продаж.`,
    });
  } else if (rSq >= 0.5) {
    out.push({
      severity: 'info',
      text: `R² = ${rSq.toFixed(3)} - модель объясняет ${(rSq * 100).toFixed(0)}% вариации. Добавление контрольных факторов улучшит fit.`,
    });
  } else if (rSq > 0) {
    out.push({
      severity: 'warning',
      text: `R² = ${rSq.toFixed(3)} - модель объясняет менее 50% вариации. Добавьте контрольные переменные.`,
    });
  }

  if (mape > 0 && mape < 5) {
    out.push({
      severity: 'success',
      text: `MAPE = ${mape.toFixed(1)}% - крайне низкая ошибка прогноза. Модель точно следует фактической динамике.`,
      tip: 'Индустриальный benchmark: MAPE < 10% = отлично, 10-20% = приемлемо, > 20% = нужны доработки.',
    });
  } else if (mape > 15) {
    out.push({
      severity: 'warning',
      text: `MAPE = ${mape.toFixed(1)}% - модель объясняет тренд, но не улавливает краткосрочные скачки.`,
      tip: 'Добавьте промо-переменные (акции, праздники) как контрольные факторы.',
    });
  }

  // ── 4. Model architecture - what was built ──
  if (nChannels > 0) {
    out.push({
      severity: 'info',
      text: `Структура модели: Bayesian MMM с ${nChannels} канал${nChannels > 4 ? 'ами' : nChannels > 1 ? 'ами' : 'ом'} медиа. Каждый канал прошёл через Adstock (отложенный эффект) + Hill saturation (убывающая отдача).`,
      tip: 'Adstock моделирует, что реклама прошлой недели продолжает работать сегодня. Hill - что после определённого порога каждый дополнительный рубль даёт меньше продаж. Это две стандартные нелинейности в эконометрике медиа.',
    });
  }

  // ── 5. Trust foundation - что повышает доверие ──
  // Показываем только когда модель действительно хорошая - иначе совет «доверяй» звучит фальшиво.
  // На тонких данных (Ratio < 4:1) блок доверия НЕ показываем - он вводит в заблуждение.
  const isGoodModel = mqs >= 70 && rHat > 0 && rHat <= 1.05 && divergences === 0 && rSq >= 0.7 && !isThin;
  if (isGoodModel) {
    out.push({
      severity: 'info',
      text: 'Что повышает доверие к этой модели:',
      tip: [
        '• Tight priors (узкие диапазоны априорных ожиданий) — HalfNormal, Beta, Gamma — основаны на индустриальных бенчмарках MMM, не на data-mining.',
        '• Каждый ROI имеет 95% CI - видна неопределённость, не точечная оценка.',
        '• Полная спецификация модели и priors экспортируется в MD/XLSX/PPTX.',
        '• Декомпозиция показывает базовые продажи vs медиа-вклад - можно проверить sanity.',
        '• Sampler - NUTS (золотой стандарт Bayesian inference), не Metropolis.',
      ].join('\n'),
    });
  }

  return out;
}

// ── Decompose Step ──────────────────────────────────────

/**
 * @param {{ base_pct?: number, baseline_pct?: number, channels: Array<{ name: string, contribution_pct: number, contribution?: number, spend: number, roi: number, verdict?: string, unit_smell?: boolean }>, signed_factor_contributions?: Record<string, { value?: number, pct?: number, type?: string }> }} data
 * @param {import('./kpi-aware-formatting.js').KpiViewInput|null} [kpiInput] - KPI/mode context (v1.3.2). null → legacy monetary roi.
 * @returns {Insight[]}
 */
export function decomposeInsights(data, kpiInput = null) {
  /** @type {Insight[]} */
  const out = [];
  if (!data) return out;
  const kpi = resolveKpi(kpiInput);

  const channels = data.channels ?? [];
  // Backend returns `baseline_pct`; legacy field `base_pct` kept as fallback.
  const basePct = data.baseline_pct ?? data.base_pct ?? 0;
  // Audit pass 14 (Антон 2026-05-03): round basePct first, derive mediaPct
  // как 100 - rounded → sum guaranteed = 100. Pre-fix: 92.5 → toFixed «93»,
  // 7.5 → toFixed «8», sum = 101% (logical inconsistency in headline).
  const basePctRounded = Math.round(basePct);
  const mediaPctRounded = Math.max(0, 100 - basePctRounded);
  const mediaPct = Math.max(0, 100 - basePct);  // exact для downstream usage
  const totalSpend = channels.reduce((s, c) => s + (c.spend || 0), 0);
  const totalContrib = channels.reduce((s, c) => s + (c.contribution || 0), 0);
  const totalEffectPct = channels.reduce((s, c) => s + (c.contribution_pct || 0), 0);

  // ── 1. Headline: что показала декомпозиция ──
  const sortedByEffect = [...channels].sort((a, b) => (b.contribution_pct || 0) - (a.contribution_pct || 0));
  const top = sortedByEffect[0];
  if (top && totalEffectPct > 0) {
    out.push({
      severity: 'success',
      text: `Декомпозиция готова: ${basePctRounded}% продаж - базовые (без медиа), ${mediaPctRounded}% - вклад рекламы. Главный драйвер: ${top.name} (${top.contribution_pct?.toFixed(0)}% от медиа-вклада).`,
      tip: 'Базовые продажи - это то, что вы получили бы при нулевом медиа-бюджете (бренд, дистрибуция, лояльность). Медиа-вклад - что добавила реклама поверх базы.',
    });
  }

  // v2.1.0 (пилот 2026-05-16): инсайт об отъедании продаж конкурентами /
  // ценами / прочими отрицательными signed-факторами. Антон: «хочу видеть,
  // как сильно от продаж отъедают рекламные активности конкурентов».
  const signedFactors = data.signed_factor_contributions || {};
  /** @type {Array<{name: string, value: number, pct: number, type: string}>} */
  const negativeFactors = [];
  /** @type {Record<string, string>} */
  const factorGroupLabel = {
    signed_competitor: 'конкуренты',
    signed_price:      'цена',
    signed_weather:    'погода',
    signed_macro:      'макро-факторы',
  };
  for (const [name, fact] of Object.entries(signedFactors)) {
    if (!fact || typeof fact !== 'object') continue;
    const value = Number(fact.value ?? 0);
    if (value < 0 && fact.type && factorGroupLabel[fact.type]) {
      negativeFactors.push({ name, value, pct: Number(fact.pct ?? 0), type: String(fact.type) });
    }
  }
  if (negativeFactors.length > 0) {
    // Группируем по типу для агрегированного % impact.
    /** @type {Record<string, number>} */
    const sumByGroup = {};
    for (const f of negativeFactors) {
      sumByGroup[f.type] = (sumByGroup[f.type] ?? 0) + Math.abs(f.pct);
    }
    const parts = Object.entries(sumByGroup).map(
      ([type, totalPct]) => `${factorGroupLabel[type]} ~${totalPct.toFixed(1)}%`
    );
    const topNegative = [...negativeFactors].sort((a, b) => a.value - b.value)[0];
    out.push({
      severity: 'warning',
      text: `Внешние факторы отъедают продажи: ${parts.join(', ')}. Самый сильный: «${topNegative.name}» (-${Math.abs(topNegative.pct).toFixed(1)}% от продаж за период).`,
      tip: 'На графике «Динамика по периодам» отрицательный вклад показан ниже нулевой линии красно-оранжевой полосой. Это «потерянные продажи» - то, что бренд получил бы, если бы конкуренты/цены/погода не давили в течение периода.',
    });
  }

  // ── 2. Трактовка базовых продаж ──
  if (basePct > 80) {
    out.push({
      severity: 'info',
      text: `Base sales = ${basePct.toFixed(0)}% - большинство продаж органические. Медиа-эффект относительно слабый.`,
      tip: 'Возможные причины: (1) сильный бренд с лояльной аудиторией - медиа поддерживает, не двигает; (2) недостаточная мощность медиа-кампаний; (3) модель не уловила эффект (проверь Adstock и контрольные переменные).',
    });
  } else if (basePct < 30) {
    out.push({
      severity: 'warning',
      text: `Base sales = ${basePct.toFixed(0)}% - бренд критически зависит от рекламы. Остановка медиа = риск значительного падения продаж.`,
      tip: 'Это типично для категорий с низкой лояльностью или новых брендов. Стратегия: постепенно инвестировать в brand-equity медиа (TV, OOH), чтобы поднять базу.',
    });
  } else if (basePct < 50) {
    out.push({
      severity: 'info',
      text: `Base sales = ${basePct.toFixed(0)}% - медиа драйвит около половины продаж. Здоровый mix performance + brand.`,
    });
  }

  if (!channels.length) return out;

  // ── 3. Топ-3 драйвера: подробная раскладка ──
  const top3 = sortedByEffect.slice(0, Math.min(3, sortedByEffect.length));
  if (top3.length > 0 && totalEffectPct > 0) {
    const top3Sum = top3.reduce((s, c) => s + (c.contribution_pct || 0), 0);
    const lines = top3.map((c, i) => {
      const rank = ['🥇', '🥈', '🥉'][i] || `${i + 1}.`;
      const roi = c.roi != null ? c.roi.toFixed(2) + '×' : '-';
      const spend = c.spend?.toLocaleString('ru-RU') ?? '-';
      const contrib = c.contribution?.toLocaleString('ru-RU') ?? '-';
      return `${rank} ${c.name}: ${c.contribution_pct?.toFixed(0)}% от медиа-вклада, ROI ${roi}, бюджет ${spend} → вклад ${contrib}`;
    }).join('\n');
    out.push({
      severity: 'info',
      text: `Топ-${top3.length} драйверов медиа-вклада (${top3Sum.toFixed(0)}% от всего медиа-эффекта):`,
      tip: lines,
    });
  }

  // ── 4. Эффективные vs перенасыщенные каналы (per-channel разбор) ──
  /** @type {Array<{ch: any, spendShare: number, effectShare: number, ratio: number}>} */
  const efficient = [];
  /** @type {Array<{ch: any, spendShare: number, effectShare: number, ratio: number}>} */
  const inefficient = [];
  for (const ch of channels) {
    if (!totalSpend || !totalEffectPct) continue;
    const spendShare = (ch.spend || 0) / totalSpend;
    const effectShare = (ch.contribution_pct || 0) / totalEffectPct;
    if (spendShare < 0.02 && effectShare < 0.02) continue; // отбрасываем шум
    const ratio = effectShare / Math.max(spendShare, 0.001);
    if (ratio >= 1.5) efficient.push({ ch, spendShare, effectShare, ratio });
    else if (ratio <= 0.6 && spendShare > 0.08) inefficient.push({ ch, spendShare, effectShare, ratio });
  }
  efficient.sort((a, b) => b.ratio - a.ratio);
  inefficient.sort((a, b) => a.ratio - b.ratio);

  if (efficient.length > 0) {
    const lines = efficient.slice(0, 3).map(({ ch, spendShare, effectShare, ratio }) =>
      `✓ ${ch.name}: ${(spendShare * 100).toFixed(0)}% бюджета даёт ${(effectShare * 100).toFixed(0)}% эффекта (${ratio.toFixed(1)}× выше ожидания)`
    ).join('\n');
    out.push({
      severity: 'success',
      text: `${efficient.length} ${pluralizeRu(efficient.length, ['канал', 'канала', 'каналов'])} ${pluralizeRu(efficient.length, ['работает', 'работают', 'работают'])} эффективнее своей доли бюджета:`,
      tip: lines + '\n\nТакие каналы - кандидаты на докрутку бюджета на шаге Оптимизация.',
    });
  }

  if (inefficient.length > 0) {
    const lines = inefficient.slice(0, 3).map(({ ch, spendShare, effectShare, ratio }) =>
      `✗ ${ch.name}: ${(spendShare * 100).toFixed(0)}% бюджета - лишь ${(effectShare * 100).toFixed(0)}% эффекта (${ratio.toFixed(1)}× ниже ожидания)`
    ).join('\n');
    out.push({
      severity: 'warning',
      text: `${inefficient.length} ${pluralizeRu(inefficient.length, ['канал', 'канала', 'каналов'])} ${pluralizeRu(inefficient.length, ['перенасыщен', 'перенасыщены', 'перенасыщены'])} или ${pluralizeRu(inefficient.length, ['работает', 'работают', 'работают'])} ниже среднего:`,
      tip: lines + '\n\nВарианты: (1) сократить бюджет - проверить через Оптимизатор; (2) пересмотреть креатив/таргетинг; (3) проверить нет ли проблем с трекингом.',
    });
  }

  // ── 5. ROI лидеры и аутсайдеры - v1.3.2: KPI/mode-aware labels ──
  // B4 audit fix: c.roi от backend = mathematical KPI_units/₽_spend для всех KPI.
  // - monetary: бóльший = лучший ROI (intuitive).
  // - count: бóльший units/₽ = меньший ₽/ед. = лучший CPU.
  // - effectiveness: бóльший share = лидер.
  // Universal: sort descending raw → best first.
  /** @type {(a: any, b: any) => number} */
  const sortBest = (a, b) => (b.roi || 0) - (a.roi || 0);
  // REC-1-GAP (2026-06-03 audit): unit_smell-каналы (артефактный ROI из не-денежных
  // единиц, напр. TRP с unit_cost=1.0, ROI 12186×) НЕ должны короноваться «Лучший ROI/
  // CPU … можно увеличить инвестиции» — это та же ROI-1/2 проблема, что в optimizeInsights,
  // в соседней функции экрана Декомпозиции (рендер InsightsPanel case 3). Канал и так
  // помечен в таблице (verdict «ROI завышен (не рубли?)») и в шапке («не-денежные единицы»).
  const sortedByRoi = [...channels].filter(c => c.roi != null && c.unit_smell !== true).sort(sortBest);
  if (sortedByRoi.length >= 2) {
    const topRoi = sortedByRoi[0];
    const bottomRoi = sortedByRoi[sortedByRoi.length - 1];
    const metricShort = kpi.metricShort;

    if (kpi.isLegacy) {
      if (topRoi.roi >= 2) {
        out.push({
          severity: 'success',
          text: `Лучший ROI: ${topRoi.name} = ${topRoi.roi.toFixed(2)}× - каждый вложенный рубль возвращает ${topRoi.roi.toFixed(2)} рублей продаж.`,
          tip: 'ROI ≥ 2× - отличный показатель. Если канал не перенасыщен (см. кривую насыщения), можно увеличить инвестиции.',
        });
      } else if (topRoi.roi >= 1.2) {
        out.push({
          severity: 'info',
          text: `Лучший ROI: ${topRoi.name} = ${topRoi.roi.toFixed(2)}× - окупается, но не выдающийся.`,
        });
      }

      if (bottomRoi.roi < 1 && bottomRoi.roi > 0 && bottomRoi.spend > 0) {
        out.push({
          severity: 'warning',
          text: `Убыточный канал: ${bottomRoi.name} = ROI ${bottomRoi.roi.toFixed(2)}× - расходы превышают вклад в продажи.`,
          tip: 'Прежде чем сокращать: (1) проверить, есть ли brand-эффект (доля поиска, прямые заходы); (2) убедиться, что данные по каналу полные; (3) рассмотреть смену формата/креатива до полного отключения.',
        });
      }
    } else if (kpi.kpiKind === 'count') {
      // B4 audit fix: c.roi raw = units/₽ (mathematical). CPU = 1/c.roi.
      // Threshold logic в CPU space (₽/ед.); compare derived CPU vs vpcu.
      const vpcu = kpi.vpcu;
      const topRawMroas = Number(topRoi.roi);
      const bottomRawMroas = Number(bottomRoi.roi);
      const topCpu = topRawMroas > 0 ? 1 / topRawMroas : Infinity;
      const bottomCpu = bottomRawMroas > 0 ? 1 / bottomRawMroas : Infinity;
      const topGood = vpcu ? topCpu <= vpcu * 0.5 : topCpu < 100;
      const topAcceptable = vpcu ? topCpu <= vpcu : topCpu < 200;
      if (topGood) {
        out.push({
          severity: 'success',
          text: `Лучший ${metricShort}: ${topRoi.name} = ${_fmtMetric(topRawMroas, kpi)} - стоимость единицы значительно ниже ценности${vpcu ? ` (${vpcu.toFixed(0)} ₽)` : ''}.`,
          tip: `${_topBenchmark(kpi)} - отличный показатель. При условии что канал не перенасыщен (закон убывающей отдачи), можно увеличить инвестиции.`,
        });
      } else if (topAcceptable) {
        out.push({
          severity: 'info',
          text: `Лучший ${metricShort}: ${topRoi.name} = ${_fmtMetric(topRawMroas, kpi)} - окупается, но не выдающийся.`,
        });
      }

      if (vpcu && bottomCpu > vpcu && bottomRoi.spend > 0) {
        out.push({
          severity: 'warning',
          text: `Убыточный канал: ${bottomRoi.name} = ${metricShort} ${_fmtMetric(bottomRawMroas, kpi)} - стоимость единицы превышает её ценность (${vpcu.toFixed(0)} ₽).`,
          tip: 'Прежде чем сокращать: (1) проверить, есть ли brand-эффект; (2) убедиться, что данные по каналу полные; (3) рассмотреть смену формата/креатива до полного отключения.',
        });
      }
    } else if (kpi.mode === 'effectiveness') {
      // Доля semantics: higher = better (within portfolio).
      if (topRoi.roi >= 0.30) {
        out.push({
          severity: 'success',
          text: `Лучший по доле эффекта: ${topRoi.name} = ${_fmtMetric(topRoi.roi, kpi)} - основной драйвер в портфеле.`,
          tip: 'Доля ≥ 30% - канал доминирует в портфеле. Проверить нет ли концентрационного риска.',
        });
      } else if (topRoi.roi >= 0.15) {
        out.push({
          severity: 'info',
          text: `Лучший по доле эффекта: ${topRoi.name} = ${_fmtMetric(topRoi.roi, kpi)}.`,
        });
      }
      if (bottomRoi.roi < 0.05 && bottomRoi.spend > 0) {
        out.push({
          severity: 'warning',
          text: `Низкая доля: ${bottomRoi.name} = ${_fmtMetric(bottomRoi.roi, kpi)} - вклад канала минимален.`,
          tip: 'Канал почти не двигает портфель. Проверить (1) есть ли brand-эффект; (2) корректность данных; (3) формат/таргетинг.',
        });
      }
    }
  }

  // ── 6. Концентрация: один канал доминирует? ──
  if (top && top.contribution_pct > 50) {
    out.push({
      severity: 'warning',
      text: `Высокая концентрация: ${top.name} даёт ${top.contribution_pct.toFixed(0)}% всего медиа-вклада.`,
      tip: 'Зависимость от одного канала - риск. Если он перестанет работать (смена алгоритма, рост CPM, насыщение) - упадёт значительная часть продаж. Диверсифицируйте mix.',
    });
  }

  // ── 7. Куда дальше - guidance ──
  if (channels.length > 0 && totalEffectPct > 0) {
    out.push({
      severity: 'info',
      text: 'Что делать дальше:',
      tip: '• Перейдите в «Оптимизация» - модель посчитает оптимальное перераспределение бюджета.\n• В «Отчёт» - выгрузите MD/XLSX/PPTX с полной декомпозицией и спецификацией модели.\n• На графике «Динамика по периодам» можно увидеть, как вклад каналов меняется во времени.',
    });
  }

  return out;
}

// ── Optimize Step ───────────────────────────────────────

/**
 * @typedef {Object} OptimizeContext
 * @property {any} [dec] - decomposeData (для pre-state)
 * @property {any} [mod] - modelData (для pre-state)
 * @property {Record<string, number>} [channelMinPct] - per-channel custom лимиты (если были заданы в expert)
 * @property {Record<string, number>} [channelMaxPct]
 * @property {number} [globalMinPct]
 * @property {number} [globalMaxPct]
 * @property {Record<string, number>} [channelBudgets] - per-channel optimal budgets (post-optimize)
 */

/**
 * Реактивные инсайты оптимизации.
 * Без `data` (до запуска) - pre-state на основе decompose: что MMM посчитает, какой потенциал.
 * С `data` - post-state с lift, главные сдвиги, особый случай +0%, влияние custom-лимитов.
 *
 * @param {any} data - optimizeData (опционально)
 * @param {OptimizeContext & {kpi?: import('./kpi-aware-formatting.js').KpiViewInput|null}} [ctx]
 * @returns {Insight[]}
 */
export function optimizeInsights(data, ctx = {}) {
  /** @type {Insight[]} */
  const out = [];
  const { dec, mod, channelBudgets = null, channelMinPct = {}, channelMaxPct = {}, globalMinPct = 50, globalMaxPct = 150, kpi: kpiInput = null } = ctx;
  // v1.3.2: KPI/mode-aware view. legacy callers → backward compat.
  const kpi = resolveKpi(kpiInput);

  // ════════════════ PRE-STATE: оптимизация ещё не запущена ════════════════
  if (!data?.channels?.length) {
    if (!dec?.channels?.length) {
      // Нет даже decompose - нечего предсказать
      out.push({
        severity: 'info',
        text: 'Здесь будет интерактивный оптимизатор бюджета.',
        tip: 'Сначала пройдите шаги Декомпозиция, потом возвращайтесь - увидите потенциал перераспределения.',
      });
      return out;
    }

    const totalSpend = dec.channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + (c.spend || 0), 0);
    const totalContrib = dec.channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + (c.contribution || 0), 0);
    const avgROI = totalSpend > 0 ? totalContrib / totalSpend : 0;

    // Light версия miROAS-распределения через ROI каналов (proxy для saturation)
    let efficient = 0, balanced = 0, saturated = 0;
    for (const c of dec.channels) {
      const r = c.roi ?? 0;
      const gap = c.efficiency_gap ?? 0;
      if (r > 2 && gap >= 5) efficient++;
      else if (r < 1 || gap <= -10) saturated++;
      else balanced++;
    }

    // v1.3.2: KPI-aware portfolio phrase в headline.
    const portfolioPhrase = kpi.isLegacy
      ? `средний ROI ${avgROI.toFixed(2)}×`
      : _weightedPhrase(avgROI, kpi).toLowerCase();
    out.push({
      severity: 'success',
      text: `Готово к оптимизации: ${dec.channels.length} ${pluralizeRu(dec.channels.length, ['канал', 'канала', 'каналов'])}, бюджет ${totalSpend.toLocaleString('ru-RU')}₽, ${portfolioPhrase}.`,
      tip: 'Нажмите «🎯 Оптимизировать бюджет» - модель найдёт распределение, максимизирующее KPI при заданных Мин/Макс ограничениях.',
    });

    // Прогноз потенциала по структуре каналов
    if (saturated > efficient) {
      out.push({
        severity: 'warning',
        text: `Каналов в плато: ${saturated} (перенасыщены). Эффективных: ${efficient}. Прирост в рамках текущего бюджета может быть близок к 0% - оптимизатору некуда «переливать» деньги.`,
        tip: 'Что попробовать:\n• Снизить Мин. % (разрешить более радикальные сокращения)\n• Повысить Макс. % (разрешить больший рост недонасыщенных)\n• Использовать What-if (блок C) - увеличить общий бюджет и пересчитать\n• Проверить TRPs/non-money каналы - они искажают модель.',
      });
    } else if (efficient >= 2 && saturated <= 1) {
      const expected = Math.min(20, efficient * 4 + balanced * 1);
      out.push({
        severity: 'info',
        text: `Структура благоприятна: ${efficient} эффективных канала, ${saturated} перенасыщенных. Ожидаемый прирост: 5-${expected}%.`,
        tip: 'Перераспределение из перенасыщенных в эффективные обычно даёт значимый lift без увеличения общего бюджета.',
      });
    } else {
      out.push({
        severity: 'info',
        text: `Структура: ${efficient} эффективных, ${balanced} сбалансированных, ${saturated} перенасыщенных. Ожидаемый прирост: 3-10%.`,
      });
    }

    out.push({
      severity: 'info',
      text: 'Параметры оптимизации:',
      tip: '• Мин. % / Макс. % - глобальные границы изменения каждого канала.\n• Фиксировать бюджет - оптимизатор только перераспределяет, не меняет сумму.\n• Эксперт-режим - per-channel ограничения (зафиксировать TV-сделку, разрешить только рост OOH и т.д.).',
    });

    return out;
  }

  // ════════════════ POST-STATE: оптимизация выполнена ════════════════
  const lift = data.expected_lift_pct ?? 0;
  const channels = data.channels ?? [];
  const totalBudget = data.total_budget ?? 0;
  const totalCurrent = channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + (c.current_spend || 0), 0);
  const totalOptimal = channels.reduce((/** @type {number} */ s, /** @type {any} */ c) => s + (c.optimal_spend || 0), 0);
  const totalBudgetMoney = data.total_budget_money ?? totalBudget;

  // ── Базовый ROI и средняя отдача ──
  const decChannels = dec?.channels ?? [];
  const totalSpendDec = decChannels.reduce(/** @param {number} s @param {any} c */ (s, c) => s + (c.spend || 0), 0);
  const totalContribDec = decChannels.reduce(/** @param {number} s @param {any} c */ (s, c) => s + (c.contribution || 0), 0);
  const avgROI = totalSpendDec > 0 ? totalContribDec / totalSpendDec : 0;

  // ── 1. Headline lift ──
  if (lift > 15) {
    out.push({
      severity: 'success',
      text: `Найден оптимум: прирост +${lift.toFixed(1)}% продаж при том же бюджете (${totalBudgetMoney.toLocaleString('ru-RU')}₽).`,
      tip: 'Существенный потенциал перераспределения. Рекомендуется пилот 4-6 недель на части бюджета (20-30%) перед полным переходом, чтобы валидировать модельные оценки на практике.',
    });
  } else if (lift > 5) {
    out.push({
      severity: 'success',
      text: `Найден оптимум: прирост +${lift.toFixed(1)}% при текущем бюджете. Умеренный, но значимый потенциал.`,
      tip: 'Текущее распределение приемлемое. Перераспределение даст устойчивый прирост, но не радикальный - план уже близок к рациональному.',
    });
  } else if (lift > 0.5) {
    out.push({
      severity: 'info',
      text: `Прирост +${lift.toFixed(1)}% - текущее распределение почти оптимально.`,
      tip: 'Незначительный потенциал в рамках того же бюджета. Чтобы существенно улучшить - нужен либо рост бюджета (см. блок C What-if), либо пересмотр медиа-микса.',
    });
  } else {
    out.push({
      severity: 'warning',
      text: `Прирост ≈${lift.toFixed(1)}%. Оптимизатор не нашёл выигрыша в рамках текущих ограничений.`,
      tip: 'Это не баг - модель честно говорит «лучше уже не сделаешь в этих рамках». Причины обычно две: (1) большинство каналов уже на saturation plateau - каждый доп.рубль даёт меньше 1 рубля продаж, (2) Мин/Макс % слишком узкие, нет пространства для перекладки. Смотрите следующие инсайты для разбора по каналам.',
    });
  }

  // ── 2. Рыночный контекст: средний ROI / CPU / доля и общий бюджет ──
  // v1.3.2: KPI-aware portfolio metric phrase + benchmark comment.
  if (avgROI > 0) {
    let roiComment = '';
    let roiSev = /** @type {'success' | 'info' | 'warning'} */ ('info');
    if (kpi.isLegacy) {
      if (avgROI >= 3) { roiComment = 'Сильная отдача медиа'; roiSev = 'success'; }
      else if (avgROI >= 1.5) { roiComment = 'Здоровый уровень'; }
      else if (avgROI >= 1) { roiComment = 'Медиа окупается, но слабо'; roiSev = 'warning'; }
      else { roiComment = 'Медиа в среднем не окупается'; roiSev = 'warning'; }
    } else if (kpi.kpiKind === 'count') {
      // avgROI here = units/₽; CPU = 1/avgROI ₽/ед. vpcu = ценность единицы.
      const cpu = avgROI > 0 ? 1 / avgROI : Infinity;
      const vpcu = kpi.vpcu;
      if (vpcu) {
        if (cpu <= vpcu * 0.5) { roiComment = 'Стоимость единицы вдвое ниже ценности - отличная экономика'; roiSev = 'success'; }
        else if (cpu <= vpcu) { roiComment = 'Стоимость единицы окупается'; }
        else if (cpu <= vpcu * 1.5) { roiComment = 'Стоимость единицы близка к ценности - на грани'; roiSev = 'warning'; }
        else { roiComment = 'Стоимость единицы выше ценности - медиа в убыток'; roiSev = 'warning'; }
      } else {
        roiComment = 'Среднюю стоимость единицы - задайте ценность в шаге Validate';
      }
    } else if (kpi.mode === 'effectiveness') {
      roiComment = 'Сумма долей = 100% по построению';
    }
    const portfolioPhrase = kpi.isLegacy
      ? `Средний ROI = ${avgROI.toFixed(2)}×`
      : _weightedPhrase(avgROI, kpi);
    out.push({
      severity: roiSev,
      // Audit pass 15 (Антон 2026-05-03): scale consistency. avgROI =
      // totalContribDec / totalSpendDec - ОБЕ величины из decompose (training).
      // Pre-fix text использовал totalBudgetMoney (optimize/planning) → math
      // 842M / 1.781B = 0.47×, customer видел «0.18×» которое реально 842M /
      // 4.338B (training). Fix: показываем training spend (denominator avgROI)
      // → ratio совпадает: 0.18× = 842M / 4338M.
      text: `${portfolioPhrase} - ${roiComment}. На ${Math.round(totalSpendDec).toLocaleString('ru-RU')}₽ обучающего расхода - медиа-вклад ${Math.round(totalContribDec).toLocaleString('ru-RU')}₽ (без baseline).`,
      tip: kpi.isLegacy
        ? 'ROI рассчитан на обучающих данных (вся история). Прогноз для бюджета планирования может отличаться - см. блок B Прогноз KPI.\n\nBenchmark: ROI ≥ 2× - отлично; 1-2× - приемлемо, нужно улучшать микс; < 1× - медиа в среднем работает в убыток, требуется пересмотр каналов или креатива.'
        : `Метрика рассчитана на обучающих данных (вся история). Прогноз для бюджета планирования может отличаться.\n\nBenchmark: ${_topBenchmark(kpi)} - отлично; на грани с ценностью - приемлемо; выше ценности - убыточно.`,
    });
  }

  // ── 3. Saturation breakdown по mROAS (идентично светофору в блоке A) ──
  // Если доступен live channelBudgets (слайдеры в блоке B) - используем его, иначе
  // fallback на current_spend из последнего optimize run. buildScaledParams делает
  // нормализацию по reference-spend, которую брать из optimize (это не меняется при
  // движении слайдеров - это «nominal» от первоначальной тренировки).
  /** @type {Array<{name: string, mroas: number, status: 'scale'|'stable'|'saturated'|'unused'}>} */
  const satList = [];
  // Phase 2 audit pass 9 (2026-05-03): TWO sources of truth unification.
  // Pass 8 заменил frontend marginalROI() на ch.mroi_current - числа совпали с
  // таблицей. Но **status** thresholds (1.5/0.8) hardcoded на frontend
  // расходились с canonical backend compute_channel_action (Scale/Hold/Watch/
  // Reduce/Cut/Uncertain). Table uses ch.action directly. Insights status
  // теперь maps на ch.action: Scale → scale, Hold/Watch → stable, Reduce/Cut
  // → saturated, Uncertain → unused. Single source of truth across UI.
  /** @param {string|null|undefined} action */
  const actionToStatus = (action) => {
    switch (action) {
      case 'Scale': return /** @type {const} */ ('scale');
      case 'Hold': return /** @type {const} */ ('stable');
      case 'Watch': return /** @type {const} */ ('stable');
      case 'Reduce': return /** @type {const} */ ('saturated');
      case 'Cut': return /** @type {const} */ ('saturated');
      case 'Uncertain': return /** @type {const} */ ('unused');
      default: return null;
    }
  };
  if (data.channels) {
    for (const ch of data.channels) {
      const v = Number(ch.mroi_current ?? 0);
      const action = String(ch.action ?? '');
      const mappedStatus = actionToStatus(action);
      // Zero-spend or untrained - unused (table treats same way)
      if (!Number.isFinite(v) || v <= 0) {
        satList.push({ name: ch.name, mroas: 0, status: 'unused' });
        continue;
      }
      // Use backend action mapping when available; fallback к thresholds для
      // backward compat (legacy pickles без compute_channel_action results).
      /** @type {'scale'|'stable'|'saturated'} */
      const status = mappedStatus && mappedStatus !== 'unused'
        ? /** @type {'scale'|'stable'|'saturated'} */ (mappedStatus)
        : (v > 1.5 ? 'scale' : v > 0.8 ? 'stable' : 'saturated');
      satList.push({ name: ch.name, mroas: v, status });
    }
  }
  const saturated = satList.filter(s => s.status === 'saturated');
  const effective = satList.filter(s => s.status === 'scale');
  const stable = satList.filter(s => s.status === 'stable');
  const unused = satList.filter(s => s.status === 'unused');

  // Unit-smell из decompose (отдельный сигнал - не связан с mROAS)
  // REC-1-GAP (2026-06-03): детект ПО ФЛАГУ unit_smell (авторитетный сигнал
  // decomposer для не-денежных каналов с unit_cost=1.0), а не только по тексту
  // verdict. Реальный verdict движка = «ROI завышен (не рубли?)» (decomposer.py:121),
  // подстроки «подозрительно» он НЕ содержит → старый фильтр /подозрительно/ был
  // мёртв на реальных данных (TRPs снова коронован «лучшим по mROAS», ROI-1/2).
  /** @type {Array<{name: string, roi: number}>} */
  const suspicious = decChannels
    .filter((/** @type {any} */ c) => c.unit_smell === true || /подозрительно/i.test(c.verdict || ''))
    .map((/** @type {any} */ c) => ({ name: c.name, roi: c.roi ?? 0 }));
  // REC-1 (2026-06-02): unit_smell-каналы (артефактный ROI/mROAS из не-денежных
  // единиц, напр. TRP с unit_cost=1.0) НЕ должны попадать в рекомендации
  // «наращивать» — раньше защитная пометка (секция 5) не доходила до светофора
  // и mROAS-лидеров → продукт советовал вкладывать в канал с ROI 12186× (ROI-1/2).
  const suspiciousNames = new Set(suspicious.map((/** @type {{name: string}} */ c) => c.name));
  const effectiveClean = effective.filter((/** @type {any} */ s) => !suspiciousNames.has(s.name));

  // Всегда показываем расклад по saturation (4 категории) - стабильное количество инсайтов.
  if (satList.length > 0) {
    const rows = [];
    // v1.3.2: KPI-aware metric label в светофоре.
    const metric = kpi.metricShort;
    if (effective.length > 0) rows.push(`🟢 Недонасыщены: ${effective.length} - ${effective.map(c => `${c.name} (${metric} ${_fmtMetric(c.mroas, kpi)})${suspiciousNames.has(c.name) ? ' ⚠ не-денежные единицы, оценка ненадёжна' : ''}`).join(', ')}`);
    if (stable.length > 0) rows.push(`🟡 Стабильны: ${stable.length} - ${stable.map(c => `${c.name} (${metric} ${_fmtMetric(c.mroas, kpi)})`).join(', ')}`);
    if (saturated.length > 0) rows.push(`🔴 Перенасыщены: ${saturated.length} - ${saturated.map(c => `${c.name} (${metric} ${_fmtMetric(c.mroas, kpi)})`).join(', ')}`);
    if (unused.length > 0) rows.push(`⚪ Не используются: ${unused.length} - ${unused.map(c => c.name).join(', ')}`);

    // REC-1: «зона роста / есть куда вкладывать» считается по effectiveClean
    // (без unit_smell-каналов) — иначе артефактный канал раздувал бы счётчик роста.
    const headline =
      saturated.length >= Math.ceil(satList.length / 2)
        ? `${saturated.length} из ${satList.length} каналов перенасыщены - оптимизатор упирается в плато.`
        : effectiveClean.length >= 1 && saturated.length === 0
          ? `${effectiveClean.length} ${pluralizeRu(effectiveClean.length, ['канал', 'канала', 'каналов'])} в зоне роста - есть куда вкладывать.`
          : `Расклад: 🟢${effective.length} 🟡${stable.length} 🔴${saturated.length}${unused.length > 0 ? ` ⚪${unused.length}` : ''} из ${satList.length}.`;

    const sev = saturated.length >= Math.ceil(satList.length / 2)
      ? /** @type {'warning'} */ ('warning')
      : effectiveClean.length >= 1 && saturated.length === 0
        ? /** @type {'success'} */ ('success')
        : /** @type {'info'} */ ('info');

    // v1.3.2: tip criteria adapt per KPI.
    let criteriaTip = '';
    if (kpi.isLegacy) {
      criteriaTip = 'Критерии по mROAS (предельная отдача следующего рубля):\n• > 1.5× - недонасыщен (масштабировать)\n• 0.8–1.5× - стабильная зона (сохранить)\n• < 0.8× - перенасыщен (сократить)\n• 0 - не используется.';
    } else if (kpi.kpiKind === 'count' && kpi.vpcu) {
      criteriaTip = `Критерии по CPU (стоимость следующей единицы):\n• ≤ ${(kpi.vpcu * 0.5).toFixed(0)} ₽/ед. - недонасыщен (масштабировать)\n• ≤ ${kpi.vpcu.toFixed(0)} ₽/ед. - стабильная зона (сохранить)\n• > ${kpi.vpcu.toFixed(0)} ₽/ед. - перенасыщен (сократить)\n• 0 - не используется.`;
    } else if (kpi.kpiKind === 'count') {
      criteriaTip = 'Критерии: ниже стоимость единицы - лучше. Точные пороги задайте через ценность единицы (Validate шаг).';
    } else if (kpi.mode === 'effectiveness') {
      criteriaTip = 'Доля канала в эффекте - высокая доля = доминирующий канал; низкая = маргинальный.';
    }
    out.push({
      severity: sev,
      text: headline,
      tip: rows.join('\n') + (criteriaTip ? '\n\n' + criteriaTip : ''),
    });
  }

  // ── 4. miROAS leaders (стабильный инсайт - всегда виден) ──
  // REC-1: исключаем unit_smell-каналы из ранжирования «лучший/худший по mROAS» —
  // их предельная отдача артефактна (TRP в не-денежных единицах), нельзя кронить «лучшим».
  const activeSat = satList.filter(s => s.status !== 'unused' && s.mroas > 0 && !suspiciousNames.has(s.name));
  if (activeSat.length >= 2) {
    const sorted = [...activeSat].sort((a, b) => b.mroas - a.mroas);
    const best = sorted[0];
    const worst = sorted[sorted.length - 1];
    const spread = worst.mroas > 0 ? best.mroas / worst.mroas : 0;
    const spreadNote = spread > 10
      ? ` Разброс ${spread.toFixed(0)}× - есть реальный потенциал перекладки.`
      : spread > 3
        ? ` Умеренный разброс - потенциал есть, но ограниченный.`
        : ' Каналы выровнены - перекладка не даст существенного прироста.';
    // v1.3.2: KPI-aware label.
    const metricShort = kpi.metricShort;
    out.push({
      severity: 'info',
      text: `Предельная отдача (${metricShort}): лучший ${best.name} (${_fmtMetric(best.mroas, kpi)}), худший ${worst.name} (${_fmtMetric(worst.mroas, kpi)}).${spreadNote}`,
      tip: kpi.isLegacy
        ? 'mROAS - сколько рублей KPI приносит следующий рубль в канал (не путать с ROI, который про средний за период). Классическое правило оптимизации: переливать из канала с низким mROAS в канал с высоким, пока они не сравняются.'
        : `${metricShort} - предельная отдача следующего рубля. Правило оптимизации: переливать из худшего канала в лучший, пока они не сравняются.`,
    });
  } else if (activeSat.length === 1) {
    const only = activeSat[0];
    out.push({
      severity: 'warning',
      text: `Активен только 1 канал (${only.name}, mROAS ${only.mroas.toFixed(2)}×). Модель не может оценить перекладку - нужно включить хотя бы 2 канала.`,
      tip: 'Поставьте бюджет на остальных каналах > 0, чтобы увидеть сравнение mROAS. Каналы с 0₽ модель считает «не используются» и их отдача недоступна.',
    });
  } else if (satList.length > 0) {
    out.push({
      severity: 'warning',
      text: `Все ${satList.length} каналов с нулевым бюджетом - сравнить mROAS невозможно.`,
      tip: 'Верните бюджет хотя бы 2 каналам, чтобы увидеть их относительную эффективность.',
    });
  }

  // ── 5. Unit-smell / trust warning ──
  if (suspicious.length > 0) {
    out.push({
      severity: 'warning',
      text: `⚠ ${suspicious.length} ${pluralizeRu(suspicious.length, ['канал', 'канала', 'каналов'])} с подозрительно высоким ROI - не используйте их оценки для бюджетных решений.`,
      tip: suspicious.map(c => `⚠ ${c.name} - ROI ${c.roi.toFixed(1)}×`).join('\n') +
        '\n\nПричины завышенного ROI обычно две: (1) переобучение модели на коротких данных (Ratio < 4:1), (2) смешанные единицы измерения (TRP + рубли в одной модели). Оптимизатор учитывает эти цифры как есть - вручную скорректируйте рекомендации.',
    });
  }

  // ── 2. Главные сдвиги (top-3 по abs delta) ──
  const changes = channels
    .map((/** @type {any} */ ch) => ({
      name: ch.name,
      delta: (ch.optimal_spend ?? 0) - (ch.current_spend ?? 0),
      deltaPct: ch.current_spend > 0 ? ((ch.optimal_spend ?? 0) - (ch.current_spend ?? 0)) / ch.current_spend * 100 : 0,
      action: ch.action,
    }))
    .sort((/** @type {any} */ a, /** @type {any} */ b) => Math.abs(b.deltaPct) - Math.abs(a.deltaPct));

  const significantChanges = changes.filter(/** @param {any} c */ c => Math.abs(c.deltaPct) > 5);
  if (significantChanges.length > 0) {
    const lines = significantChanges.slice(0, 4).map(/** @param {any} c */ c => {
      const arrow = c.deltaPct > 0 ? '↑' : '↓';
      const sign = c.deltaPct > 0 ? '+' : '';
      const deltaAbs = Math.abs(c.delta).toLocaleString('ru-RU');
      return `${arrow} ${c.name}: ${sign}${c.deltaPct.toFixed(0)}% (${c.deltaPct > 0 ? '+' : '−'}${deltaAbs}₽)`;
    }).join('\n');
    out.push({
      severity: 'info',
      text: `Главные сдвиги бюджета (${significantChanges.length} канал${significantChanges.length > 4 ? 'ов' : significantChanges.length > 1 ? 'а' : ''}):`,
      tip: lines + '\n\nПерекладка идёт из перенасыщенных каналов в недонасыщенные - где каждый рубль ещё работает на полную.',
    });
  } else if (Math.abs(lift) < 0.5) {
    out.push({
      severity: 'info',
      text: 'Все каналы остаются практически в текущих позициях (изменения < 5%).',
      tip: 'Подтверждение того, что текущее распределение близко к оптимальному в рамках заданных лимитов.',
    });
  }

  // ── 3. Влияние custom-лимитов (если экспертный режим был использован) ──
  let customCount = 0;
  let lockedCount = 0;
  for (const ch of channels) {
    const minP = channelMinPct[ch.name];
    const maxP = channelMaxPct[ch.name];
    if (minP == null && maxP == null) continue;
    if ((minP != null && minP !== globalMinPct) || (maxP != null && maxP !== globalMaxPct)) {
      customCount++;
      if ((minP ?? globalMinPct) === 100 && (maxP ?? globalMaxPct) === 100) lockedCount++;
    }
  }
  if (customCount > 0) {
    out.push({
      severity: 'info',
      text: `Применены custom-ограничения: ${customCount} канал${customCount > 4 ? 'ов' : customCount > 1 ? 'а' : ''}${lockedCount > 0 ? ` (из них зафиксировано: ${lockedCount})` : ''}.`,
      tip: 'Custom-лимиты учтены оптимизатором как hard-constraints (бизнес-ограничения: контракты, обязательства). Без них достижимый lift мог бы быть выше - но рекомендации были бы нереалистичны.',
    });
  }

  // ── 4. Total budget изменение (если What-if когда-нибудь добавим) ──
  if (totalBudget > 0 && Math.abs(totalOptimal - totalCurrent) / Math.max(totalCurrent, 1) > 0.05) {
    const diff = totalOptimal - totalCurrent;
    const sign = diff > 0 ? '+' : '';
    out.push({
      severity: 'info',
      text: `Оптимальный общий бюджет: ${totalOptimal.toLocaleString('ru-RU')}₽ (${sign}${diff.toLocaleString('ru-RU')}₽ к текущему ${totalCurrent.toLocaleString('ru-RU')}₽).`,
      tip: 'Это значит «Фиксировать бюджет» был выключен - оптимизатор сам нашёл лучшую сумму в рамках per-channel лимитов.',
    });
  }

  // ── 6. Action items: куда дальше (context-aware) ──
  const noLift = Math.abs(lift) < 0.5;
  const manyChannelsSaturated = saturated.length >= Math.ceil(satList.length / 2);
  /** @type {string[]} */
  const actions = [];
  if (noLift) {
    actions.push('• Блок C (What-if) - подвигайте общий бюджет ×1.2–×1.5: увидите куда модель хочет направить доп.деньги.');
    actions.push('• Блок D (Forecast) - спрогнозируйте KPI на следующий период с учётом медиаинфляции.');
    if (manyChannelsSaturated) {
      actions.push('• Расширьте границы - Мин. % → 20–30%, Макс. % → 200–300%: оптимизатор получит пространство для перекладки.');
      actions.push('• Стратегически - обновите креатив или добавьте новый канал: кривая насыщения «не знает» о новой кампании, но на практике свежий креатив возвращает канал к точке до плато.');
    }
  } else if (lift > 15) {
    actions.push('• Пилот 4-6 недель на 20-30% бюджета с новыми пропорциями - валидация модельных оценок.');
    actions.push('• Блок E (Сценарии) - сохраните этот оптимум, сравните с другими конфигурациями.');
    actions.push('• Эксперт-режим в блоке B - если есть бизнес-ограничения (подписанные контракты, sponsor obligations), зафиксируйте каналы.');
  } else {
    actions.push('• Блок C (What-if) - поэкспериментируйте с бюджетом ±30%.');
    actions.push('• Блок D (Forecast) - планирование следующего периода.');
    actions.push('• Блок E (Сценарии) - сохраните и сравните несколько вариантов.');
    actions.push('• Подтвердить и перейти к отчёту - когда план устраивает.');
  }

  out.push({
    severity: 'info',
    text: 'Что делать дальше:',
    tip: actions.join('\n'),
  });

  return out;
}

/**
 * Report step insights - structured per-stage summary + recommendations.
 * Каждый этап пайплайна получает свой key insight с recко, чтобы пользователь
 * увидел итоговую картину одним взглядом.
 *
 * @param {{ mod?: any, dec?: any, opt?: any, scenarioCount?: number, kpi?: import('./kpi-aware-formatting.js').KpiViewInput|null, ssotRatio?: number|null }} ctx
 * @returns {Insight[]}
 */
export function reportInsights(ctx = {}) {
  /** @type {Insight[]} */
  const out = [];
  const { mod, dec, opt, scenarioCount = 0, kpi: kpiInput = null, ssotRatio = null } = ctx;
  const kpi = resolveKpi(kpiInput);
  const rSq = mod?.diagnostics?.metrics?.r_squared ?? null;
  const mape = mod?.diagnostics?.metrics?.mape_pct ?? null;
  // INV-50 (live-audit 2026-06-07): отображаемый ratio в блоке КАЧЕСТВА модели =
  // честный backend effective ratio (obs/effective_params), тот же источник, что
  // MQS-cap и вердикт. Прежде предпочитался ssotRatio (obs/назначенные колонки ≈
  // 4.4) — оптимистичный media-ratio, который противоречил вердикту «2.4:1 < 4:1»
  // и глушил варнинг переобучения (isThin=false при 4.4). Это «второй слой» того
  // же un-cap, что сняли с MQS-score 2026-06-07. ssotRatio оставлен лишь fallback
  // при отсутствии backend-ratio. (Замечание: шаг «Валидация» показывает свой
  // pre-train obs/колонки ≈ 4.4 как индикатор структуры данных — это ДРУГАЯ метрика,
  // см. validationHeaderMetrics; расхождение pre-train 4.4 vs post-train 2.4 честно.)
  // INV-50 анти-рецидив (2026-06-07): MQS и effective ratio — через единый
  // селектор metric-views. ssotRatio (pre-train media-ratio) — только fallback.
  const _diag = mod?.diagnostics;
  const _ratioV = ratioView(_diag, ssotRatio ?? null);
  const _mqsV = mqsView(_diag);
  const ratio = _ratioV?.ratio ?? null;
  /** @type {number|null} */
  let mqs;
  /** @type {string} */
  let tierLabel;
  if (_mqsV == null) {
    mqs = null;
    tierLabel = '';
  } else {
    mqs = _mqsV.score;
    tierLabel = _mqsV.tierLabel;
  }
  const lift = opt?.expected_lift_pct ?? null;
  const budget = opt?.total_budget_money ?? null;
  const basePct = dec?.baseline_pct ?? null;
  const decChannels = dec?.channels ?? [];

  if (mqs == null) {
    out.push({
      severity: 'info',
      text: 'Пройдите все шаги пайплайна (Импорт → Оптимизация), чтобы увидеть сводку и выгрузить отчёт.',
    });
    return out;
  }

  // ════════════════ ЭТАП 1: Качество модели ════════════════
  const isThin = _ratioV?.isThin ?? false;
  const mqsParts = [`MQS ${mqs.toFixed(0)} (${tierLabel})`];
  if (rSq != null) mqsParts.push(`R² ${rSq.toFixed(3)}`);
  if (mape != null) mqsParts.push(`MAPE ${mape.toFixed(1)}%`);
  if (ratio != null) mqsParts.push(`Ratio ${ratio.toFixed(1)}:1`);

  if (mqs >= 80 && !isThin) {
    out.push({
      severity: 'success',
      text: `🎯 Модель: ${mqsParts.join(' · ')}. Результаты надёжны.`,
      tip: `Рекомендация: используйте выводы отчёта для бюджетных решений. Спецификация модели, priors и доверительные интервалы экспортируются в PPTX/MD/XLSX для воспроизводимости.\n\nВалидационный критерий: посмотрите график «Факт vs Прогноз» в отчёте - линии должны накладываться без систематического смещения.`,
    });
  } else if (isThin) {
    out.push({
      severity: 'warning',
      text: `⚠ Модель: ${mqsParts.join(' · ')}. Данных мало - возможно переобучение.`,
      tip: `Рекомендация: относитесь к ROI и декомпозиции как к ориентиру, а не истине. При Ratio < 4:1 модель может «выучить» точки, а не закономерность.\n\nЧто сделать: (1) запустите пилот 4-6 недель на части бюджета для валидации, (2) перед решениями смотрите на направление (увеличить/сократить), а не на абсолютные числа, (3) планируйте собрать ≥52 недель данных для следующей итерации.`,
    });
  } else {
    out.push({
      severity: mqs >= 60 ? 'info' : 'warning',
      text: `${mqs >= 60 ? '📊' : '⚠'} Модель: ${mqsParts.join(' · ')}.`,
      tip: mqs >= 60
        ? 'Рекомендация: приемлемое качество для ориентировочных решений. Пилот 4-6 недель обязателен перед полным переходом на новый медиа-план.'
        : 'Рекомендация: модель слабая. Добавьте контрольные переменные (сезонность, промо), увеличьте историю данных или упростите модель (меньше каналов).',
    });
  }

  // ════════════════ ЭТАП 2: Декомпозиция ════════════════
  if (basePct != null || decChannels.length > 0) {
    const sortedByContrib = [...decChannels].sort(/** @param {any} a @param {any} b */ (a, b) => (b.contribution_pct || 0) - (a.contribution_pct || 0));
    const top = sortedByContrib[0];
    // REC-1-GAP (2026-06-03): см. ЭТАП 1 — детект по флагу unit_smell, не только текст verdict.
    const suspicious = decChannels.filter(/** @param {any} c */ c => c.unit_smell === true || /подозрительно/i.test(c.verdict || ''));

    /** @type {'success' | 'warning' | 'info'} */
    let sev = 'info';
    let headline = '';
    let reco = '';

    if (basePct != null) {
      if (basePct > 70) {
        sev = 'info';
        headline = `📊 Декомпозиция: base ${basePct.toFixed(0)}% / медиа ${(100 - basePct).toFixed(0)}%. Бренд в основном органический.`;
        reco = 'Рекомендация: оптимизируйте эффективность внутри существующего медиа-бюджета, не увеличивайте объём - рост ограничен саморазогревом бренда.';
      } else if (basePct < 30) {
        sev = 'warning';
        headline = `⚠ Декомпозиция: base ${basePct.toFixed(0)}% - бренд зависит от рекламы.`;
        reco = 'Рекомендация: долгосрочно - инвестиции в brand-equity (TV, OOH) для поднятия базы. Остановка медиа = риск значительного падения продаж.';
      } else {
        sev = 'success';
        headline = `✅ Декомпозиция: здоровый mix - base ${basePct.toFixed(0)}% / медиа ${(100 - basePct).toFixed(0)}%.`;
        reco = 'Рекомендация: сбалансированная модель. Реклама драйвит существенную долю продаж, бренд имеет органическую базу. Фокус - на эффективности перекладки.';
      }
    }

    if (top) {
      // v1.3.2: KPI-aware metric label в драйвере.
      const driverMetric = kpi.isLegacy ? 'ROI' : kpi.metricShort;
      const driverValue = kpi.isLegacy
        ? (top.roi != null ? `${top.roi.toFixed(2)}×` : '-')
        : _fmtMetric(top.roi, kpi);
      reco += `\n\nГлавный драйвер продаж: ${top.name} (${top.contribution_pct?.toFixed(0) ?? '-'}% от медиа-вклада, ${driverMetric} ${driverValue}).`;
    }
    if (suspicious.length > 0) {
      const susMetric = kpi.isLegacy ? 'ROI' : kpi.metricShort;
      reco += `\n\n⚠ ${suspicious.length} ${pluralizeRu(suspicious.length, ['канал', 'канала', 'каналов'])} с подозрительно высоким ${susMetric} (${suspicious.map(/** @param {any} s */ s => s.name).join(', ')}). Оценки этих каналов не используйте как абсолютные - только относительно.`;
    }

    out.push({
      severity: sev,
      text: headline,
      tip: reco,
    });
  }

  // ════════════════ ЭТАП 3: Оптимизация ════════════════
  if (lift != null) {
    if (lift > 15) {
      out.push({
        severity: 'success',
        text: `🚀 Оптимизация: +${lift.toFixed(1)}% KPI при том же бюджете${budget ? ` (${budget.toLocaleString('ru-RU')}₽)` : ''}.`,
        tip: 'Рекомендация: высокий потенциал перекладки. Конкретные суммы по каналам - в отчёте. Перед полным переходом - пилот 4-6 недель на части бюджета (20-30%), чтобы валидировать модельные оценки на практике.',
      });
    } else if (lift > 5) {
      out.push({
        severity: 'success',
        text: `📈 Оптимизация: +${lift.toFixed(1)}% - умеренный, но значимый потенциал.`,
        tip: 'Рекомендация: перекладка даст устойчивый прирост. Текущий план близок к рациональному - радикальной перестройки не требуется. Пилот на 20% бюджета для подтверждения.',
      });
    } else if (lift > 0.5) {
      out.push({
        severity: 'info',
        text: `📊 Оптимизация: +${lift.toFixed(1)}% - план почти оптимален.`,
        tip: 'Рекомендация: существенного потенциала в рамках текущего бюджета нет. Для роста нужен либо увеличенный бюджет (What-if), либо пересмотр медиа-микса (новый канал, обновление креатива).',
      });
    } else {
      out.push({
        severity: 'info',
        text: '🟰 Оптимизация: +0% - план уже оптимален в заданных рамках.',
        tip: 'Рекомендация: каналы на плато насыщения или Мин/Макс % слишком узкие. Для прорыва: (1) What-if с ростом бюджета +30-50%, (2) обновление креатива в насыщенных каналах, (3) добавление нового канала — кривая насыщения «не знает» о новой кампании.',
      });
    }
  }

  // ════════════════ ЭТАП 4: Сценарии ════════════════
  if (scenarioCount > 0) {
    out.push({
      severity: 'info',
      text: `💼 Сценарии: сохранено ${scenarioCount}.`,
      tip: `Рекомендация: сравните сценарии в блоке E (Оптимизация) - таблица с ROAS, бюджетом и lift% покажет лучшую конфигурацию. Сохранённые планы экспортируются вместе с отчётом и доступны для следующих итераций.\n\nЧто обычно сохраняют: (1) Baseline - текущий план, (2) Optimal - результат оптимизации, (3) ±30% бюджета - what-if анализ, (4) Forecast - план на следующий период с учётом инфляции.`,
    });
  } else {
    out.push({
      severity: 'info',
      text: '💼 Сценарии: не сохранены.',
      tip: 'Рекомендация: вернитесь в блок E (Оптимизация → Сценарный анализ) и сохраните хотя бы 2 плана для сравнения - Baseline и Optimal. Это позволит отчёту показать альтернативы и обосновать решения.',
    });
  }

  // ════════════════ Экспорт ════════════════
  out.push({
    severity: 'info',
    text: '📤 Форматы экспорта:',
    tip: '• PPTX - для презентации заказчику/команде: executive summary, спецификация модели, декомпозиция, ROI, оптимизация.\n• XLSX - для аналитиков: метрики, спецификация, декомпозиция, ROI, Spend vs Effect, оптимизация, сырые time-series данные для собственных графиков, глоссарий.\n• HTML - интерактивный отчёт для удалённых клиентов: standalone-файл с живыми графиками (ECharts), waterfall, ROI, Spend vs Effect, динамика по периодам, оптимизация, сценарии. Открывается в любом браузере без установки приложения - отправляется как ссылка или вложение.\n\nВсе три формата содержат одну аналитику - выбирайте по аудитории и каналу доставки. К каждому файлу - автоматически генерируемый сопроводительный текст с описанием модели, результатов и ограничений.',
  });

  return out;
}
