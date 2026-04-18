/**
 * Rule-Based Insights Engine (Tier 1 — offline, always works).
 * Generates contextual recommendations from pipeline data without API calls.
 * Covers ~80% of insight value at 0% cost.
 *
 * @module insights-rules
 */

/**
 * @typedef {Object} InsightAction
 * @property {'exclude'|'keep_only'|'set_role'|'merge'} type
 * @property {string[]} columns — columns to act on
 * @property {string[]} [exclude] — columns to exclude (for keep_only)
 * @property {string} [label] — button label override
 * @property {string} [mergedName] — name for merged column (type=merge)
 */

/**
 * @typedef {Object} Insight
 * @property {'info'|'success'|'warning'|'error'} severity
 * @property {string} text
 * @property {string} [tip]
 * @property {InsightAction} [action]
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

  // Гранулярность: < 60 строк скорее всего месячные данные
  const granularity = rows <= 60 ? 'месячных' : rows <= 260 ? 'недельных' : 'дневных';
  const period = rows <= 60 ? `~${rows} месяц${rows > 1 ? (rows < 5 ? 'а' : 'ев') : ''}` :
                 rows <= 260 ? `~${Math.round(rows / 52)} год${Math.round(rows/52) > 1 ? 'а' : ''}` :
                 `~${Math.round(rows / 365)} год${Math.round(rows/365) > 1 ? 'а' : ''}`;

  if (rows < 24) {
    out.push({ severity: 'warning', text: `Мало данных: ${rows} наблюдений (${period}). MMM требует минимум 2 года истории.`, tip: 'Байесовская модель работает с малыми выборками, но доверительные интервалы будут широкими.' });
  } else if (rows >= 104) {
    out.push({ severity: 'success', text: `${rows} ${granularity} наблюдений (${period}) — отличный объём для MMM.` });
  } else {
    out.push({ severity: 'info', text: `${rows} ${granularity} наблюдений (${period}), ${cols} столбцов.` });
  }

  // ── Автодетект медиаканалов по именам колонок ──
  const colNames = columns.map(/** @param {any} c */ c => (c.name ?? String(c)).toUpperCase());
  const MEDIA_KEYWORDS = ['OLV','TV','RADIO','BANNER','DIGITAL','CONTEXT','TARGET','SMM','OOH','PRESS','YOUTUBE','VK','OK','TG','TELEGRAM','SEARCH','SEO','EMAIL','PUSH','IN-APP','RTB','PROGRAMMATIC','CPC','CPM','GRP','IMPRESS','CLICK','BUDGET','SPEND','COST','РУБ'];
  const DATE_KEYWORDS = ['DATE','ДАТА','PERIOD','НЕДЕЛЯ','МЕСЯЦ','WEEK','MONTH','YEAR'];
  const KPI_KEYWORDS = ['SALES','ПРОДАЖИ','REVENUE','ВЫРУЧКА','UNITS','ШТУ','КОНВЕРС','CONVERSION','ORDERS','ЗАКАЗ','LEADS','ЛИД','CLICKS_KPI'];

  const detectedMedia = colNames.filter(n => MEDIA_KEYWORDS.some(k => n.includes(k))).length;
  const hasDate = colNames.some(n => DATE_KEYWORDS.some(k => n.includes(k)));
  const hasKpi = colNames.some(n => KPI_KEYWORDS.some(k => n.includes(k)));

  if (hasDate && hasKpi) {
    out.push({ severity: 'success', text: 'Обнаружены дата и целевой KPI — структура данных подходит для MMM.' });
  } else if (!hasDate) {
    out.push({ severity: 'warning', text: 'Колонка с датой не найдена. Убедитесь, что временной период присутствует в данных.', tip: 'MMM требует временного ряда. Колонка с датой должна быть первой или явно названа DATE/ДАТА/PERIOD.' });
  } else if (!hasKpi) {
    out.push({ severity: 'warning', text: 'Целевой KPI не распознан автоматически. На шаге Валидация назначьте его вручную.', tip: 'KPI — это что вы хотите объяснить: продажи, выручка, конверсии, заказы.' });
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
        out.push({ severity: 'warning', text: `«${col}»: ${Math.round(pct)}% нулей — канал малоактивен.` });
      }
    }
  }

  return out;
}

// ── Validate Step ───────────────────────────────────────

/**
 * @param {any} result
 * @returns {Insight[]}
 */
export function validateInsights(result) {
  /** @type {Insight[]} */
  const out = [];
  if (!result) return out;

  // ── Общий статус ──
  if (result.status === 'ok') {
    out.push({ severity: 'success', text: 'Данные прошли валидацию. Структура подходит для MMM-моделирования.' });
  } else if (result.status === 'warning') {
    const warnCount = result.warnings?.length ?? 0;
    out.push({ severity: 'warning', text: `Валидация выявила ${warnCount} предупреждени${warnCount === 1 ? 'е' : warnCount < 5 ? 'я' : 'й'}. Модель можно запустить, но точность может быть ниже.`, tip: 'Предупреждения не блокируют моделирование, но каждое снижает надёжность результатов. Рекомендуем устранить хотя бы критичные.' });
  } else if (result.status === 'error') {
    out.push({ severity: 'error', text: 'Критические проблемы с данными. Моделирование невозможно без исправления.' });
  }

  // ── Распознанные роли колонок ──
  const cols = result.columns ?? [];
  const kpiCols = cols.filter(/** @param {any} c */ c => c.role === 'kpi');
  const mediaCols = cols.filter(/** @param {any} c */ c => c.role === 'media');
  const controlCols = cols.filter(/** @param {any} c */ c => c.role === 'control');
  const dateCols = cols.filter(/** @param {any} c */ c => c.role === 'date');

  if (kpiCols.length > 0 && mediaCols.length > 0) {
    out.push({ severity: 'success', text: `Распознано: KPI — ${kpiCols.map(/** @param {any} c */ c => c.name).join(', ')}, ${mediaCols.length} медиаканал${mediaCols.length > 4 ? 'ов' : mediaCols.length > 1 ? 'а' : ''}, ${controlCols.length} контрольн${controlCols.length === 1 ? 'ая' : 'ых'} переменн${controlCols.length === 1 ? 'ая' : 'ых'}.` });
  } else if (kpiCols.length === 0) {
    out.push({ severity: 'error', text: 'KPI не определён. Назначьте целевую метрику в таблице ролей.', tip: 'KPI — зависимая переменная, которую объясняет модель: продажи, выручка, конверсии.' });
  }

  // ── Объём данных vs параметры ──
  const totalRows = result.detected?.rows ?? 0;
  const paramCount = mediaCols.length * 3 + controlCols.length + 2;
  if (totalRows > 0 && mediaCols.length > 0) {
    const ratio = totalRows / paramCount;

    // Найти каналы-кандидаты на исключение (>50% нулей) — для кнопки "Оптимизировать"
    const weakChannels = mediaCols
      .filter(/** @param {any} c */ c => (c.stats?.zeros_pct ?? 0) > 50)
      .sort(/** @param {any} a @param {any} b */ (a, b) => (b.stats?.zeros_pct ?? 0) - (a.stats?.zeros_pct ?? 0));
    const weakNames = weakChannels.map(/** @param {any} c */ c => c.name);

    if (ratio < 2) {
      const afterExclude = weakNames.length > 0 ? totalRows / ((mediaCols.length - weakNames.length) * 3 + controlCols.length + 2) : ratio;
      out.push({
        severity: 'error',
        text: `Критически мало данных: ${totalRows} наблюдений / ${mediaCols.length} каналов (ratio ${ratio.toFixed(1)}:1, минимум 4:1). ${weakNames.length > 0 ? `Исключите ${weakNames.length} неактивных каналов → ratio станет ${afterExclude.toFixed(1)}:1.` : 'Добавьте данные или уменьшите каналы.'}`,
        tip: `Каждый медиаканал добавляет ~3 параметра. При ${totalRows} наблюдениях рекомендуется не более ${Math.floor(totalRows / 12)} каналов. Два пути: (1) добавить данные в недельной гранулярности, (2) исключить каналы с >50% нулей.`,
        action: weakNames.length > 0 ? { type: 'exclude', columns: weakNames, label: `Исключить ${weakNames.length} неактивных` } : undefined,
      });
    } else if (ratio < 4) {
      out.push({
        severity: 'warning',
        text: `Мало данных: ratio ${ratio.toFixed(1)}:1 (рекомендуется ≥4:1). ${weakNames.length > 0 ? `${weakNames.length} каналов с >50% нулей можно исключить.` : ''}`,
        tip: `Для ${mediaCols.length} каналов оптимально ≥${mediaCols.length * 12} наблюдений. Байесовская модель сработает, но с широкими доверительными интервалами.`,
        action: weakNames.length > 0 ? { type: 'exclude', columns: weakNames, label: `Исключить ${weakNames.length} неактивных` } : undefined,
      });
    } else if (ratio < 6) {
      out.push({ severity: 'info', text: `Ratio ${ratio.toFixed(1)}:1 — приемлемо. Модель сойдётся, но для узких доверительных интервалов нужно ≥6:1.` });
    } else {
      out.push({ severity: 'success', text: `Ratio ${ratio.toFixed(1)}:1 — отличное соотношение данных к параметрам.` });
    }
  }

  // ── Предупреждения из валидации ──
  if (result.warnings?.length > 0) {
    for (const w of result.warnings) {
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
  const missing = cols.filter(/** @param {any} c */ c => c.stats?.missing_pct > 5);
  if (missing.length > 0) {
    const names = missing.map(/** @param {any} c */ c => `${c.name} (${c.stats.missing_pct.toFixed(0)}%)`).join(', ');
    out.push({ severity: 'warning', text: `Пропуски >5%: ${names}`, tip: 'Линейная интерполяция заполнит небольшие пробелы. При >20% пропусков столбец лучше исключить или найти альтернативный источник.' });
  }

  // ── Группировка парных колонок и рекомендации ──
  const VOLUME_KEYS = ['ПОКАЗ','ПРОСМОТР','КЛИК','ВИЗИТ','ПРОЧТЕН','GRP','TRP','IMPRESSION','CLICK','VIEW','VISIT','READ'];
  const COST_KEYS = ['БЮДЖЕТ','РАСХОД','ЗАТРАТ','СТОИМОСТЬ','SPEND','COST','BUDGET','РУБ'];

  /** @type {Map<string, {volume: any[], cost: any[]}>} */
  const channelGroups = new Map();

  for (const c of cols) {
    const upper = (c.name ?? '').toUpperCase();
    // Extract channel prefix: everything before the metric keyword
    let prefix = '';
    let type = '';
    for (const k of VOLUME_KEYS) {
      const idx = upper.indexOf(k);
      if (idx > 0) { prefix = upper.slice(0, idx).trim().replace(/[\s_-]+$/, ''); type = 'volume'; break; }
    }
    if (!prefix) {
      for (const k of COST_KEYS) {
        const idx = upper.indexOf(k);
        if (idx > 0) { prefix = upper.slice(0, idx).trim().replace(/[\s_-]+$/, ''); type = 'cost'; break; }
      }
    }
    if (!prefix) continue;

    if (!channelGroups.has(prefix)) channelGroups.set(prefix, { volume: [], cost: [] });
    const g = channelGroups.get(prefix);
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
        text: `${prefix}: все метрики >90% нулей (${allCols.map(/** @param {any} c */ c => c.name).join(', ')}). Канал неактивен — исключите из модели.`,
        action: { type: 'exclude', columns: allCols.map(/** @param {any} c */ c => c.name), label: 'Исключить канал' },
      });
    } else if (hasCost && hasVolume) {
      const costZeros = g.cost[0]?.stats?.zeros_pct ?? 0;
      const volZeros = g.volume[0]?.stats?.zeros_pct ?? 0;
      if (costZeros < volZeros) {
        channelRecs.push({
          severity: 'info',
          text: `${prefix}: парные метрики. Рекомендация — оставить бюджет (${costNames[0]}), исключить натуральные (${volNames.join(', ')}).`,
          tip: 'MMM моделирует зависимость KPI от затрат. Показы/клики — промежуточные метрики, коррелирующие с бюджетом. Включение обоих размывает оценку ROI.',
          action: { type: 'keep_only', columns: costNames, exclude: volNames, label: 'Оставить бюджет' },
        });
      } else {
        channelRecs.push({
          severity: 'info',
          text: `${prefix}: парные метрики. Бюджет ${costZeros.toFixed(0)}% нулей — используйте натуральный показатель (${volNames[0]}).`,
          tip: 'Если бюджетные данные неполные, но есть показы/GRP, используйте их как прокси.',
          action: { type: 'keep_only', columns: volNames.slice(0, 1), exclude: [...costNames, ...volNames.slice(1)], label: `Оставить ${volNames[0]}` },
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
        text: `${prefix} (${allCols[0].name}): ${(allCols[0].stats?.zeros_pct ?? 0).toFixed(0)}% нулей — исключите или объедините.`,
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
      channelRecs.push({ severity: 'warning', text: `${c.name}: ${pct.toFixed(0)}% нулей — исключите.`, action: { type: 'exclude', columns: [c.name], label: 'Исключить' } });
    } else {
      channelRecs.push({ severity: 'warning', text: `${c.name}: ${pct.toFixed(0)}% нулей — объединить или оставить с оговоркой.`, action: { type: 'exclude', columns: [c.name], label: 'Исключить' } });
    }
  }

  if (channelRecs.length > 0) {
    out.push({ severity: 'info', text: `Анализ каналов: ${channelGroups.size} групп обнаружено. Рекомендации ниже.` });
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
    out.push({
      severity: 'info',
      text: `${allWeakMedia.length} каналов с 50-90% нулей (${weakNames.join(', ')}). Объедините их в один «Малые медиа» — суммарный сигнал будет сильнее.`,
      tip: `Каждый канал по отдельности слишком разреженный (в среднем ${avgZeros.toFixed(0)}% нулей). Объединение суммирует их активность — модель получит более стабильную оценку ROI для группы.`,
      action: { type: 'merge', columns: weakNames, mergedName: 'Малые медиа', label: `Объединить ${allWeakMedia.length} канала` },
    });
  }

  // ── Динамическая оценка готовности ──
  const errorCount = out.filter(i => i.severity === 'error').length;
  const warnCount = out.filter(i => i.severity === 'warning').length;
  const currentRatio = totalRows > 0 && mediaCols.length > 0 ? totalRows / (mediaCols.length * 3 + controlCols.length + 2) : 0;
  const maxChannels = Math.floor(totalRows / 12);

  if (errorCount > 0) {
    out.push({ severity: 'error', text: `Моделирование не рекомендуется. Устраните критические проблемы выше.` });
  } else if (warnCount === 0 && mediaCols.length > 0 && kpiCols.length > 0) {
    out.push({ severity: 'success', text: `Данные готовы к моделированию. ${mediaCols.length} каналов, ratio ${currentRatio.toFixed(1)}:1. Нажмите «Далее».` });
  } else if (mediaCols.length > maxChannels && maxChannels > 0) {
    out.push({ severity: 'info', text: `Сейчас ${mediaCols.length} каналов. Для ${totalRows} наблюдений оптимально ≤${maxChannels}. Исключите наименее значимые каналы.` });
  } else if (warnCount > 0) {
    out.push({ severity: 'info', text: `${warnCount} предупреждений. Моделирование возможно, но рекомендуем устранить хотя бы критичные. Режим «Эксперт» покажет детали.` });
  }

  return out;
}

// ── Model Step ──────────────────────────────────────────

/**
 * @param {{ diagnostics: { mqs: { score: number, tier_label: string }, r_squared: number, mape: number, r_hat: number, divergences: number }, channelParams: Record<string, any> }} data
 * @returns {Insight[]}
 */
export function modelInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data?.diagnostics) return out;

  const d = data.diagnostics;
  const mqs = d.mqs?.score ?? 0;
  const label = d.mqs?.tier_label ?? '';

  if (mqs >= 80) {
    out.push({ severity: 'success', text: `MQS = ${mqs.toFixed(0)} (${label}) — высокое качество модели. Результаты надёжны для принятия решений.` });
  } else if (mqs >= 60) {
    out.push({ severity: 'info', text: `MQS = ${mqs.toFixed(0)} (${label}) — приемлемое качество. Рассмотрите добавление контрольных переменных для улучшения.` });
  } else {
    out.push({ severity: 'warning', text: `MQS = ${mqs.toFixed(0)} (${label}) — модель требует доработки.`, tip: 'Попробуйте: добавить промо-переменные, увеличить draws, проверить качество данных.' });
  }

  if (d.r_hat > 1.05) {
    out.push({ severity: 'error', text: `R-hat = ${d.r_hat.toFixed(3)} — MCMC цепи не сошлись. Результаты ненадёжны.`, tip: 'Увеличьте количество draws (2000+) и tune (1000+). Если не помогает — упростите модель (меньше каналов).' });
  } else if (d.r_hat > 1.01) {
    out.push({ severity: 'warning', text: `R-hat = ${d.r_hat.toFixed(3)} — цепи почти сошлись. Рассмотрите увеличение draws.` });
  }

  if (d.mape > 15) {
    out.push({ severity: 'warning', text: `MAPE = ${d.mape.toFixed(1)}% — модель объясняет тренд, но не улавливает краткосрочные скачки.`, tip: 'Добавьте промо-переменные (акции, праздники) как контрольные факторы.' });
  }

  if (d.r_squared < 0.5) {
    out.push({ severity: 'warning', text: `R² = ${d.r_squared.toFixed(3)} — модель объясняет менее 50% вариации. Добавьте контрольные переменные.` });
  } else if (d.r_squared >= 0.8) {
    out.push({ severity: 'success', text: `R² = ${d.r_squared.toFixed(3)} — модель объясняет ${(d.r_squared * 100).toFixed(0)}% вариации продаж.` });
  }

  if (d.divergences > 0) {
    out.push({ severity: 'warning', text: `${d.divergences} дивергенций в MCMC. Модель может быть нестабильна.`, tip: 'Увеличьте target_accept (0.9→0.95) или tune. Дивергенции означают, что сэмплер не смог исследовать всё пространство параметров.' });
  }

  return out;
}

// ── Decompose Step ──────────────────────────────────────

/**
 * @param {{ base_pct: number, channels: Array<{ name: string, contribution_pct: number, spend: number, roi: number }> }} data
 * @returns {Insight[]}
 */
export function decomposeInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data) return out;

  if (data.base_pct > 80) {
    out.push({ severity: 'info', text: `Base sales = ${data.base_pct.toFixed(0)}% — большинство продаж органические. Медиа-эффект относительно слабый.`, tip: 'Это может означать сильный бренд (хорошо) или что модель не смогла уловить медиа-эффект (проверьте adstock).' });
  } else if (data.base_pct < 40) {
    out.push({ severity: 'info', text: `Base sales = ${data.base_pct.toFixed(0)}% — бренд сильно зависит от рекламы. Остановка медиа может привести к значительному падению.` });
  }

  if (!data.channels?.length) return out;

  // Spend share vs effect share divergence
  const totalSpend = data.channels.reduce((s, c) => s + (c.spend || 0), 0);
  const totalEffect = data.channels.reduce((s, c) => s + (c.contribution_pct || 0), 0);

  for (const ch of data.channels) {
    if (!totalSpend || !totalEffect) continue;
    const spendShare = ch.spend / totalSpend;
    const effectShare = (ch.contribution_pct || 0) / totalEffect;
    if (spendShare > 0.15 && effectShare > 0 && spendShare / effectShare > 2.5) {
      out.push({ severity: 'warning', text: `${ch.name}: ${(spendShare * 100).toFixed(0)}% бюджета, но лишь ${(effectShare * 100).toFixed(0)}% эффекта. ROI ниже среднего.` });
    }
    if (effectShare > 0.15 && spendShare > 0 && effectShare / spendShare > 2) {
      out.push({ severity: 'success', text: `${ch.name}: ${(effectShare * 100).toFixed(0)}% эффекта при ${(spendShare * 100).toFixed(0)}% бюджета — высокоэффективный канал.` });
    }
  }

  // Top/bottom ROI
  const sorted = [...data.channels].sort((a, b) => (b.roi || 0) - (a.roi || 0));
  if (sorted.length >= 2) {
    const top = sorted[0];
    const bottom = sorted[sorted.length - 1];
    if (top.roi > 2) {
      out.push({ severity: 'success', text: `Лучший канал по ROI: ${top.name} (${top.roi.toFixed(1)}x).` });
    }
    if (bottom.roi < 1 && bottom.roi > 0) {
      out.push({ severity: 'warning', text: `${bottom.name}: ROI = ${bottom.roi.toFixed(1)}x — расходы превышают вклад. Рассмотрите сокращение.` });
    }
  }

  return out;
}

// ── Optimize Step ───────────────────────────────────────

/**
 * @param {{ expected_lift_pct: number, total_budget: number, channels: Array<{ name: string, current_spend: number, optimal_spend: number }> }} data
 * @returns {Insight[]}
 */
export function optimizeInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data) return out;

  const lift = data.expected_lift_pct ?? 0;

  if (lift > 15) {
    out.push({ severity: 'success', text: `Потенциальный рост: +${lift.toFixed(1)}% — значительный потенциал оптимизации.`, tip: 'Перераспределите бюджет согласно оптимальному плану. Рекомендуется пилотный период 4-6 недель.' });
  } else if (lift > 5) {
    out.push({ severity: 'info', text: `Потенциальный рост: +${lift.toFixed(1)}% — умеренный потенциал. Текущее распределение неплохое, но можно улучшить.` });
  } else if (lift > 0) {
    out.push({ severity: 'info', text: `Потенциальный рост: +${lift.toFixed(1)}% — текущее распределение уже близко к оптимальному.` });
  }

  if (!data.channels?.length) return out;

  // Biggest changes
  const changes = data.channels
    .map(ch => ({ name: ch.name, delta: (ch.optimal_spend - ch.current_spend), deltaPct: ch.current_spend > 0 ? (ch.optimal_spend - ch.current_spend) / ch.current_spend * 100 : 0 }))
    .sort((a, b) => Math.abs(b.deltaPct) - Math.abs(a.deltaPct));

  const biggest = changes[0];
  if (biggest && Math.abs(biggest.deltaPct) > 20) {
    const dir = biggest.deltaPct > 0 ? 'увеличить' : 'сократить';
    out.push({ severity: 'info', text: `Главное изменение: ${dir} ${biggest.name} на ${Math.abs(biggest.deltaPct).toFixed(0)}%.` });
  }

  return out;
}
