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
  const MEDIA_KEYWORDS = ['OLV','TV','ТВ','RADIO','РАДИО','BANNER','БАННЕР','DIGITAL','CONTEXT','TARGET','SMM','OOH','ООН','ВНЕШН','НАРУЖН','OUTDOOR','PRESS','ПРЕССА','YOUTUBE','VK','OK','TG','TELEGRAM','SEARCH','SEO','EMAIL','PUSH','IN-APP','RTB','PROGRAMMATIC','CPC','CPM','GRP','TRP','OTS','IMPRESS','ПОКАЗ','CLICK','КЛИК','VISIT','ВИЗИТ','BUDGET','БЮДЖЕТ','SPEND','COST','РУБ','СОЦ','SOCIAL','PERFORMANCE','RETAIL','СПЕЦПРОЕКТ','СТАТЬИ'];
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
export function validateInsights(result, objective = 'roi') {
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
  // Унифицированная формула rows / (media + control) — соответствует Python validator и индустриальной практике (rows-to-cols ratio).
  const totalRows = result.file?.rows ?? result.detected?.rows ?? 0;
  const paramCount = mediaCols.length + controlCols.length;
  if (totalRows > 0 && mediaCols.length > 0) {
    const ratio = totalRows / Math.max(paramCount, 1);

    // Найти каналы-кандидаты на исключение (>50% нулей) — для кнопки "Оптимизировать"
    const weakChannels = mediaCols
      .filter(/** @param {any} c */ c => (c.stats?.zeros_pct ?? 0) > 50)
      .sort(/** @param {any} a @param {any} b */ (a, b) => (b.stats?.zeros_pct ?? 0) - (a.stats?.zeros_pct ?? 0));
    const weakNames = weakChannels.map(/** @param {any} c */ c => c.name);

    if (ratio < 2) {
      const afterExclude = weakNames.length > 0 ? totalRows / Math.max(mediaCols.length - weakNames.length + controlCols.length, 1) : ratio;
      out.push({
        severity: 'error',
        text: `Критически мало данных: ${totalRows} наблюдений / ${mediaCols.length + controlCols.length} переменных (ratio ${ratio.toFixed(1)}:1, минимум 4:1). ${weakNames.length > 0 ? `Исключите ${weakNames.length} неактивных каналов → ratio станет ${afterExclude.toFixed(1)}:1.` : 'Добавьте данные или уменьшите каналы.'}`,
        tip: `При ${totalRows} наблюдениях рекомендуется не более ${Math.floor(totalRows / 4)} переменных (4:1). Два пути: (1) добавить данные в недельной гранулярности (${Math.round(totalRows * 4.3)} наблюдений), (2) исключить каналы с >50% нулей и объединить парные метрики.`,
        action: weakNames.length > 0 ? { type: 'exclude', columns: weakNames, label: `Исключить ${weakNames.length} неактивных` } : undefined,
      });
    } else if (ratio < 4) {
      out.push({
        severity: 'warning',
        text: `Мало данных: ratio ${ratio.toFixed(1)}:1 (рекомендуется ≥4:1). ${weakNames.length > 0 ? `${weakNames.length} каналов с >50% нулей можно исключить.` : ''}`,
        tip: `Для ${mediaCols.length} каналов оптимально ≥${mediaCols.length * 4} наблюдений. Байесовская модель сработает, но с широкими доверительными интервалами.`,
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

  // Canonical prefix: letters only + truncated to 6 chars (stemming — handles Russian plural vs singular, e.g. "СПЕЦПРОЕКТЫ"/"СПЕЦПРОЕКТ")
  /** @param {string} leading */
  const canonicalPrefix = (leading) => {
    const m = leading.match(/^[А-ЯЁA-Z]+/);
    return m ? m[0].slice(0, 6) : '';
  };

  for (const c of cols) {
    // Skip excluded columns — user-applied actions should not resurface them in insights
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
      const costTooSparse = costZeros > 50 && costZeros > volZeros + 15; // override when budget gaps are severe

      // Objective-driven recommendation
      if (objective === 'roi' && !costTooSparse) {
        // ROI → keep budget (monetary attribution)
        channelRecs.push({
          severity: 'info',
          text: `${prefix}: парные метрики. Цель ROI → оставить бюджет (${costNames[0]}), исключить ${volNames.join(', ')}.`,
          tip: 'MMM моделирует зависимость KPI от затрат. Показы/клики — промежуточные метрики, коррелирующие с бюджетом. Для ROI-анализа нужен только денежный показатель.',
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
        // Manual mode OR budget-too-sparse override — fallback to data-quality heuristic
        const reason = costTooSparse ? ` (бюджет ${costZeros.toFixed(0)}% нулей — слишком разрежен)` : '';
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
    out.push({
      severity: 'info',
      text: `${allWeakMedia.length} каналов с 50-90% нулей (${weakNames.join(', ')}). Объедините их в один «Малые медиа» — суммарный сигнал будет сильнее.`,
      tip: `Каждый канал по отдельности слишком разреженный (в среднем ${avgZeros.toFixed(0)}% нулей). Объединение суммирует их активность — модель получит более стабильную оценку ROI для группы.`,
      action: { type: 'merge', columns: weakNames, mergedName: 'Малые медиа', label: `Объединить ${allWeakMedia.length} канала` },
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
        text: `KPI не назначен. Похоже, «${bestName}» — целевой показатель. Назначьте его как KPI.`,
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
        text: `Ratio ${currentRatio.toFixed(1)}:1 — критически мало. Нужно ≤${maxChannels} каналов (сейчас ${mediaCols.length}). Исключите ${toExclude.length} слабейших → ratio станет ${afterRatio.toFixed(1)}:1.`,
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
      out.push({ severity: 'info', text: `Ratio ${currentRatio.toFixed(1)}:1 — допустимо. ${warnCount} предупреждений не блокируют моделирование, но могут снизить точность.` });
    }
  } else if (currentRatio >= 2 && currentRatio < 4 && excessChannels <= 0 && kpiCols.length > 0) {
    out.push({
      severity: 'warning',
      text: `Ratio ${currentRatio.toFixed(1)}:1 — на грани. Модель посчитает, но доверительные интервалы будут широкими. Для надёжных результатов нужно ≥52 наблюдения.`,
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
 * Pre-training insights — shown on Model step BEFORE training is launched.
 * Uses the validated data context to educate & warn the user.
 *
 * @param {any} validateResult — the validator output stored in validateData.result
 * @returns {Insight[]}
 */
export function modelPreTrainingInsights(validateResult) {
  /** @type {Insight[]} */
  const out = [];
  if (!validateResult) return out;

  const cols = validateResult.columns ?? [];
  const mediaCount = cols.filter(/** @param {any} c */ c => c.role === 'media').length;
  const controlCount = cols.filter(/** @param {any} c */ c => c.role === 'control').length;
  const kpiNames = cols.filter(/** @param {any} c */ c => c.role === 'kpi').map(/** @param {any} c */ c => c.name);
  const mediaNames = cols.filter(/** @param {any} c */ c => c.role === 'media').map(/** @param {any} c */ c => c.name);
  const rows = validateResult.file?.rows ?? 0;
  const ratio = validateResult.detected?.ratio ?? 0;

  // ── 1. Ready-state summary ──
  if (kpiNames.length > 0 && mediaCount > 0) {
    out.push({
      severity: 'success',
      text: `Готово к обучению: KPI «${kpiNames[0]}», ${mediaCount} медиаканал${mediaCount > 4 ? 'ов' : mediaCount > 1 ? 'а' : ''}${controlCount > 0 ? `, ${controlCount} контрольн${controlCount === 1 ? 'ая' : 'ых'} переменн${controlCount === 1 ? 'ая' : 'ых'}` : ''}.`,
    });
  }

  // ── 2. What MMM does (education) ──
  out.push({
    severity: 'info',
    text: 'Что происходит: модель оценит вклад каждого канала в KPI через Байесовскую регрессию с учётом отложенного эффекта (Adstock) и насыщения (Hill).',
    tip: 'Результат — ROI и маргинальная отдача каждого канала. На шаге «Оптимизация» сможете перераспределить бюджет, на «Декомпозиции» — увидеть вклад по времени.',
  });

  // ── 3. Adstock guidance ──
  out.push({
    severity: 'info',
    text: 'Adstock: «Geometric» — быстрый спад эффекта (1-2 недели, digital). «Weibull» — плавная кривая с build-up (TV, OOH, Радио).',
    tip: 'Geometric: стандарт для OLV, Banners, Social, Performance, Search — эффект рекламы затухает экспоненциально после контакта. Weibull: лучше для охватных (TV, OOH, Радио, Пресса) — эффект нарастает и уходит медленнее. «Авто» — программа выбирает по имени канала.',
  });

  // ── 4. Ratio-based warning ──
  if (ratio > 0 && ratio < 4) {
    const severity = /** @type {const} */ (ratio < 2 ? 'error' : 'warning');
    out.push({
      severity,
      text: `Ratio ${ratio.toFixed(1)}:1 — ниже идеала 4:1. Модель запустится, но доверительные интервалы будут широкими.`,
      tip: `Байесовская MMM работает с малыми выборками через priors, но при ${rows} наблюдениях на ${mediaCount + controlCount} переменных отдельные каналы могут быть слабо значимы. Интерпретируйте ROI по top-3 каналам с наибольшим вкладом.`,
    });
  } else if (ratio >= 4) {
    out.push({
      severity: 'success',
      text: `Ratio ${ratio.toFixed(1)}:1 — отличный объём данных для ${mediaCount + controlCount} переменных.`,
    });
  }

  // ── 5. Virtual merged channel warning ──
  const hasMerged = cols.some(/** @param {any} c */ c => c.role === 'media' && Array.isArray(c.merged_from));
  if (hasMerged) {
    const mergedCol = cols.find(/** @param {any} c */ c => c.role === 'media' && Array.isArray(c.merged_from));
    out.push({
      severity: 'info',
      text: `Канал «${mergedCol.name}» — объединённый из ${mergedCol.merged_from.length} столбцов. Модель оценит ROI группы как целого.`,
      tip: `Объединено: ${mergedCol.merged_from.join(', ')}. Если после обучения ROI группы высок — можно разделить её обратно и обучить отдельно на большем объёме данных.`,
    });
  }

  // ── 6. What to watch after training ──
  out.push({
    severity: 'info',
    text: 'После обучения смотрим: MQS (качество модели, ≥60) · R² (объяснительная сила, ≥0.7) · R-hat (сходимость MCMC, <1.05).',
    tip: 'MQS — агрегированная оценка качества от 0 до 100. R² — доля объяснённой вариации KPI. R-hat — сходимость Байесовских цепей; если >1.05 — увеличьте draws (в Расширенных настройках, режим Эксперт).',
  });

  // ── 7. Time estimate (educational) ──
  const estimatedMinutes = Math.round(mediaCount * 3.5 + 3); // rough: ~3.5 min/channel + overhead
  if (mediaCount > 5) {
    out.push({
      severity: 'info',
      text: `Оценка времени: ~${estimatedMinutes} мин для ${mediaCount} каналов. Для быстрого прогона можно уменьшить draws в Расширенных настройках (режим Эксперт).`,
      tip: 'Байесовский MCMC проходит две фазы: warmup (подбор step-size) и sampling (основные выборки). На слабой выборке warmup занимает больше времени, чем sampling.',
    });
  }

  return out;
}

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
