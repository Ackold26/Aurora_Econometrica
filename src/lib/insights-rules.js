/**
 * Rule-Based Insights Engine (Tier 1 - offline, always works).
 * Generates contextual recommendations from pipeline data without API calls.
 * Covers ~80% of insight value at 0% cost.
 *
 * @module insights-rules
 */
// Audit pass 9 (2026-05-03): removed marginalROI/buildScaledParams imports.
// Insights теперь uses backend's ch.mroi_current + ch.action — three-way
// alignment с таблицей и compute_channel_action (single source of truth).

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
    // Наследование money-маркера: если ВСЕ источники содержат один и тот же
    // денежный индикатор (НДС/VAT/руб/₽/RUB) — добавляем его в имя merged
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
      text: `${allWeakMedia.length} каналов с 50-90% нулей (${weakNames.join(', ')}). Объедините их в один «${mergedName}» — суммарный сигнал будет сильнее.`,
      tip: `Каждый канал по отдельности слишком разреженный (в среднем ${avgZeros.toFixed(0)}% нулей). Объединение суммирует их активность — модель получит более стабильную оценку ROI для группы.`,
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
 * Pre-training insights - shown on Model step BEFORE training is launched.
 * Uses the validated data context to educate & warn the user.
 *
 * @param {any} validateResult - the validator output stored in validateData.result
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
    const severity = /** @type {'error' | 'warning'} */ (ratio < 2 ? 'error' : 'warning');
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
    text: 'После обучения смотрим: MQS (качество модели, ≥60) · R² (объяснительная сила, ≥0.7) · R-hat (сходимость Markov Chain Monte Carlo, <1.05).',
    tip: 'MQS — агрегированная оценка качества от 0 до 100. R² — доля объяснённой вариации KPI. R-hat — сходимость Байесовских цепей; если >1.05 — увеличьте draws (в Расширенных настройках, режим Эксперт).',
  });

  // ── 7. Time estimate (educational) ──
  // JAX/NumPyro NUTS на CPU: ~1-3 мин на 4-8 каналах при дефолтах (4×(2000+2000) samples).
  // Формула синхронизирована с ConfigPanel.svelte estimateMinutes (JIT + ~5-10 мс/sample).
  const estimatedMinutes = Math.max(1, Math.round(0.3 * mediaCount + 1));
  if (mediaCount > 5) {
    out.push({
      severity: 'info',
      text: `Оценка времени: ~${estimatedMinutes} мин для ${mediaCount} каналов на движке JAX/NumPyro. Для быстрого прогона можно уменьшить draws в Расширенных настройках (режим Эксперт).`,
      tip: 'Байесовский Markov Chain Monte Carlo (NUTS) проходит две фазы: warmup (подбор step-size) и sampling (основные выборки). Первый запуск включает ~20 сек JIT-компиляции XLA — далее каждый sample занимает миллисекунды.',
    });
  }

  return out;
}

/** @param {any} data */
export function modelInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data?.diagnostics) return out;

  const d = data.diagnostics;
  // Backend nests metrics under diagnostics.metrics; legacy paths kept flat values.
  const m = d.metrics ?? d;
  const mqs = d.mqs?.score ?? 0;
  const label = d.mqs?.tier_label ?? '';
  const thinnessCap = d.mqs?.thinness_cap ?? null;
  const rSq = m.r_squared ?? d.r_squared ?? 0;
  const mape = m.mape_pct ?? d.mape ?? 0;
  const rHat = m.r_hat_max ?? d.r_hat ?? 0;
  const divergences = m.divergences ?? d.divergences ?? 0;
  const ratio = m.ratio ?? 0;
  const isThin = ratio > 0 && ratio < 4;
  const isVeryThin = ratio > 0 && ratio < 2;
  const channels = data.channelParams ? Object.keys(data.channelParams) : [];
  const nChannels = channels.length;

  // ── 0. Data thinness warning — trumps everything else ──
  if (isVeryThin) {
    out.push({
      severity: 'error',
      text: `⚠ Данных критически мало: Ratio ${ratio.toFixed(1)}:1 (< 2:1). Модель может «выучить» точки, а не закономерность. Высокий R² здесь — артефакт переобучения, а не сигнал надёжности.`,
      tip: 'Рекомендуем: увеличить историю до ≥52 недель, либо упростить модель (меньше каналов, перевести недели в месяцы). ROI и декомпозиция ненадёжны при таком Ratio.',
    });
  } else if (isThin) {
    out.push({
      severity: 'warning',
      text: `⚠ Данных мало: Ratio ${ratio.toFixed(1)}:1 (< 4:1). Высокий R² может быть артефактом переобучения. ROI-оценки имеют широкие доверительные интервалы.`,
      tip: 'Bayesian MMM с priors смягчает проблему, но не устраняет. Относитесь к декомпозиции как к ориентиру, а не истине. Для надёжности — ≥52 недель данных.',
    });
  }

  // ── 1. Headline verdict (MQS-based) ──
  const thinSuffix = isThin ? ' Учитывайте, что данных мало — CI широкие.' : '';
  if (mqs >= 80) {
    out.push({
      severity: 'success',
      text: `MQS = ${mqs.toFixed(0)} (${label}) — высокое качество модели. Результаты надёжны для принятия решений.${thinSuffix}`,
      tip: 'Перейдите к Декомпозиции, чтобы увидеть вклад каждого канала, и к Оптимизации — для перераспределения бюджета.',
    });
  } else if (mqs >= 60) {
    out.push({
      severity: 'info',
      text: `MQS = ${mqs.toFixed(0)} (${label}) — приемлемое качество.${thinSuffix}`,
      tip: thinnessCap
        ? `MQS снижен из-за недостатка данных (Ratio ${ratio.toFixed(1)}:1). На толстых данных та же модель получила бы выше. Для решения: больше истории или меньше каналов.`
        : 'Можно работать, но добавление контрольных переменных (сезонность, праздники, промо) поднимет MQS и сузит CI.',
    });
  } else {
    out.push({
      severity: 'warning',
      text: `MQS = ${mqs.toFixed(0)} (${label}) — модель требует доработки.${thinSuffix}`,
      tip: 'Попробуйте: добавить промо-переменные, увеличить draws, проверить качество данных.',
    });
  }

  // ── 2. Convergence — positive signals ──
  if (rHat > 0 && rHat <= 1.01 && divergences === 0) {
    const convergenceText = isThin
      ? `Markov Chain Monte Carlo сошёлся технически (R-hat = ${rHat.toFixed(3)}, дивергенций = 0), но это не гарантирует содержательной надёжности на коротких данных.`
      : `Markov Chain Monte Carlo сошёлся идеально: R-hat = ${rHat.toFixed(3)}, дивергенций = 0.`;
    const convergenceTip = isThin
      ? 'Сэмплер корректно исследовал пространство параметров, но при Ratio < 4:1 «пространство» само по себе слабо ограничено данными. Модель могла сойтись к переобученному решению.'
      : 'R-hat ≤ 1.01 означает, что независимые цепи сошлись к одному распределению. 0 дивергенций — сэмплер исследовал всё пространство параметров без скачков. Posterior надёжен для оценки ROI и CI.';
    out.push({
      severity: isThin ? 'info' : 'success',
      text: convergenceText,
      tip: convergenceTip,
    });
  } else if (rHat > 1.05) {
    out.push({
      severity: 'error',
      text: `R-hat = ${rHat.toFixed(3)} — цепи Markov Chain Monte Carlo не сошлись. Результаты ненадёжны.`,
      tip: 'Увеличьте draws (2000+) и tune (2000+). Если не помогает — упростите модель (меньше каналов).',
    });
  } else if (rHat > 1.01) {
    out.push({
      severity: 'warning',
      text: `R-hat = ${rHat.toFixed(3)} — цепи почти сошлись. Рассмотрите увеличение draws.`,
    });
  }

  if (divergences > 0 && rHat <= 1.05) {
    out.push({
      severity: 'warning',
      text: `${divergences} дивергенций в Markov Chain Monte Carlo. Модель может быть нестабильна.`,
      tip: 'Дивергенции = сэмплер не смог исследовать часть пространства параметров. Увеличьте target_accept (0.9 → 0.95) или tune.',
    });
  }

  // ── 3. Fit metrics — positive signals ──
  if (rSq >= 0.9) {
    out.push({
      severity: isThin ? 'info' : 'success',
      text: isThin
        ? `R² = ${rSq.toFixed(3)} — очень высокий fit, но на коротких данных (Ratio ${ratio.toFixed(1)}:1) это признак переобучения, а не силы модели.`
        : `R² = ${rSq.toFixed(3)} — модель объясняет ${(rSq * 100).toFixed(0)}% вариации KPI. Очень сильный fit.`,
      tip: isThin
        ? 'На тонких данных R² стремится к 1 автоматически: модель подгоняется под каждую точку. Это НЕ означает, что декомпозиция каналов верна. Out-of-sample валидация невозможна (нет hold-out набора).'
        : 'R² ≥ 90% — модель захватывает почти всю динамику продаж. Прогнозы устойчивы, декомпозиция вкладов правдоподобна.',
    });
  } else if (rSq >= 0.7) {
    out.push({
      severity: 'success',
      text: `R² = ${rSq.toFixed(3)} — модель объясняет ${(rSq * 100).toFixed(0)}% вариации продаж.`,
    });
  } else if (rSq >= 0.5) {
    out.push({
      severity: 'info',
      text: `R² = ${rSq.toFixed(3)} — модель объясняет ${(rSq * 100).toFixed(0)}% вариации. Добавление контрольных факторов улучшит fit.`,
    });
  } else if (rSq > 0) {
    out.push({
      severity: 'warning',
      text: `R² = ${rSq.toFixed(3)} — модель объясняет менее 50% вариации. Добавьте контрольные переменные.`,
    });
  }

  if (mape > 0 && mape < 5) {
    out.push({
      severity: 'success',
      text: `MAPE = ${mape.toFixed(1)}% — крайне низкая ошибка прогноза. Модель точно следует фактической динамике.`,
      tip: 'Индустриальный benchmark: MAPE < 10% = отлично, 10-20% = приемлемо, > 20% = нужны доработки.',
    });
  } else if (mape > 15) {
    out.push({
      severity: 'warning',
      text: `MAPE = ${mape.toFixed(1)}% — модель объясняет тренд, но не улавливает краткосрочные скачки.`,
      tip: 'Добавьте промо-переменные (акции, праздники) как контрольные факторы.',
    });
  }

  // ── 4. Model architecture — what was built ──
  if (nChannels > 0) {
    out.push({
      severity: 'info',
      text: `Структура модели: Bayesian MMM с ${nChannels} канал${nChannels > 4 ? 'ами' : nChannels > 1 ? 'ами' : 'ом'} медиа. Каждый канал прошёл через Adstock (отложенный эффект) + Hill saturation (убывающая отдача).`,
      tip: 'Adstock моделирует, что реклама прошлой недели продолжает работать сегодня. Hill — что после определённого порога каждый дополнительный рубль даёт меньше продаж. Это две стандартные нелинейности в эконометрике медиа.',
    });
  }

  // ── 5. Trust foundation — что повышает доверие ──
  // Показываем только когда модель действительно хорошая — иначе совет «доверяй» звучит фальшиво.
  // На тонких данных (Ratio < 4:1) блок доверия НЕ показываем — он вводит в заблуждение.
  const isGoodModel = mqs >= 70 && rHat > 0 && rHat <= 1.05 && divergences === 0 && rSq >= 0.7 && !isThin;
  if (isGoodModel) {
    out.push({
      severity: 'info',
      text: 'Что повышает доверие к этой модели:',
      tip: [
        '• Tight priors (HalfNormal, Beta, Gamma) основаны на индустриальных бенчмарках MMM — не data-mining.',
        '• Каждый ROI имеет 95% CI — видна неопределённость, не точечная оценка.',
        '• Полная спецификация модели и priors экспортируется в MD/XLSX/PPTX.',
        '• Декомпозиция показывает базовые продажи vs медиа-вклад — можно проверить sanity.',
        '• Sampler — NUTS (золотой стандарт Bayesian inference), не Metropolis.',
      ].join('\n'),
    });
  }

  return out;
}

// ── Decompose Step ──────────────────────────────────────

/**
 * @param {{ base_pct?: number, baseline_pct?: number, channels: Array<{ name: string, contribution_pct: number, contribution?: number, spend: number, roi: number, verdict?: string }> }} data
 * @returns {Insight[]}
 */
export function decomposeInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data) return out;

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
      text: `Декомпозиция готова: ${basePctRounded}% продаж — базовые (без медиа), ${mediaPctRounded}% — вклад рекламы. Главный драйвер: ${top.name} (${top.contribution_pct?.toFixed(0)}% от медиа-вклада).`,
      tip: 'Базовые продажи — это то, что вы получили бы при нулевом медиа-бюджете (бренд, дистрибуция, лояльность). Медиа-вклад — что добавила реклама поверх базы.',
    });
  }

  // ── 2. Трактовка базовых продаж ──
  if (basePct > 80) {
    out.push({
      severity: 'info',
      text: `Base sales = ${basePct.toFixed(0)}% — большинство продаж органические. Медиа-эффект относительно слабый.`,
      tip: 'Возможные причины: (1) сильный бренд с лояльной аудиторией — медиа поддерживает, не двигает; (2) недостаточная мощность медиа-кампаний; (3) модель не уловила эффект (проверь Adstock и контрольные переменные).',
    });
  } else if (basePct < 30) {
    out.push({
      severity: 'warning',
      text: `Base sales = ${basePct.toFixed(0)}% — бренд критически зависит от рекламы. Остановка медиа = риск значительного падения продаж.`,
      tip: 'Это типично для категорий с низкой лояльностью или новых брендов. Стратегия: постепенно инвестировать в brand-equity медиа (TV, OOH), чтобы поднять базу.',
    });
  } else if (basePct < 50) {
    out.push({
      severity: 'info',
      text: `Base sales = ${basePct.toFixed(0)}% — медиа драйвит около половины продаж. Здоровый mix performance + brand.`,
    });
  }

  if (!channels.length) return out;

  // ── 3. Топ-3 драйвера: подробная раскладка ──
  const top3 = sortedByEffect.slice(0, Math.min(3, sortedByEffect.length));
  if (top3.length > 0 && totalEffectPct > 0) {
    const top3Sum = top3.reduce((s, c) => s + (c.contribution_pct || 0), 0);
    const lines = top3.map((c, i) => {
      const rank = ['🥇', '🥈', '🥉'][i] || `${i + 1}.`;
      const roi = c.roi != null ? c.roi.toFixed(2) + '×' : '—';
      const spend = c.spend?.toLocaleString('ru-RU') ?? '—';
      const contrib = c.contribution?.toLocaleString('ru-RU') ?? '—';
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
      text: `${efficient.length} канал${efficient.length > 1 ? 'а' : ''} работает эффективнее своей доли бюджета:`,
      tip: lines + '\n\nТакие каналы — кандидаты на докрутку бюджета на шаге Оптимизация.',
    });
  }

  if (inefficient.length > 0) {
    const lines = inefficient.slice(0, 3).map(({ ch, spendShare, effectShare, ratio }) =>
      `✗ ${ch.name}: ${(spendShare * 100).toFixed(0)}% бюджета — лишь ${(effectShare * 100).toFixed(0)}% эффекта (${ratio.toFixed(1)}× ниже ожидания)`
    ).join('\n');
    out.push({
      severity: 'warning',
      text: `${inefficient.length} канал${inefficient.length > 1 ? 'а' : ''} перенасыщен${inefficient.length > 1 ? 'ы' : ''} или работает${inefficient.length > 1 ? 'ют' : ''} ниже среднего:`,
      tip: lines + '\n\nВарианты: (1) сократить бюджет — проверить через Оптимизатор; (2) пересмотреть креатив/таргетинг; (3) проверить нет ли проблем с трекингом.',
    });
  }

  // ── 5. ROI лидеры и аутсайдеры ──
  const sortedByRoi = [...channels].filter(c => c.roi != null).sort((a, b) => (b.roi || 0) - (a.roi || 0));
  if (sortedByRoi.length >= 2) {
    const topRoi = sortedByRoi[0];
    const bottomRoi = sortedByRoi[sortedByRoi.length - 1];

    if (topRoi.roi >= 2) {
      out.push({
        severity: 'success',
        text: `Лучший ROI: ${topRoi.name} = ${topRoi.roi.toFixed(2)}× — каждый вложенный рубль возвращает ${topRoi.roi.toFixed(2)} рублей продаж.`,
        tip: 'ROI ≥ 2× — отличный показатель. Если канал не перенасыщен (см. Hill saturation), можно увеличить инвестиции.',
      });
    } else if (topRoi.roi >= 1.2) {
      out.push({
        severity: 'info',
        text: `Лучший ROI: ${topRoi.name} = ${topRoi.roi.toFixed(2)}× — окупается, но не выдающийся.`,
      });
    }

    if (bottomRoi.roi < 1 && bottomRoi.roi > 0 && bottomRoi.spend > 0) {
      out.push({
        severity: 'warning',
        text: `Убыточный канал: ${bottomRoi.name} = ROI ${bottomRoi.roi.toFixed(2)}× — расходы превышают вклад в продажи.`,
        tip: 'Прежде чем сокращать: (1) проверить, есть ли brand-эффект (доля поиска, прямые заходы); (2) убедиться, что данные по каналу полные; (3) рассмотреть смену формата/креатива до полного отключения.',
      });
    }
  }

  // ── 6. Концентрация: один канал доминирует? ──
  if (top && top.contribution_pct > 50) {
    out.push({
      severity: 'warning',
      text: `Высокая концентрация: ${top.name} даёт ${top.contribution_pct.toFixed(0)}% всего медиа-вклада.`,
      tip: 'Зависимость от одного канала — риск. Если он перестанет работать (смена алгоритма, рост CPM, насыщение) — упадёт значительная часть продаж. Диверсифицируйте mix.',
    });
  }

  // ── 7. Куда дальше — guidance ──
  if (channels.length > 0 && totalEffectPct > 0) {
    out.push({
      severity: 'info',
      text: 'Что делать дальше:',
      tip: '• Перейдите в «Оптимизация» — модель посчитает оптимальное перераспределение бюджета.\n• В «Отчёт» — выгрузите MD/XLSX/PPTX с полной декомпозицией и спецификацией модели.\n• На графике «Динамика по периодам» можно увидеть, как вклад каналов меняется во времени.',
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
 * @param {OptimizeContext} [ctx]
 * @returns {Insight[]}
 */
export function optimizeInsights(data, ctx = {}) {
  /** @type {Insight[]} */
  const out = [];
  const { dec, mod, channelBudgets = null, channelMinPct = {}, channelMaxPct = {}, globalMinPct = 50, globalMaxPct = 150 } = ctx;

  // ════════════════ PRE-STATE: оптимизация ещё не запущена ════════════════
  if (!data?.channels?.length) {
    if (!dec?.channels?.length) {
      // Нет даже decompose — нечего предсказать
      out.push({
        severity: 'info',
        text: 'Здесь будет интерактивный оптимизатор бюджета.',
        tip: 'Сначала пройдите шаги Декомпозиция, потом возвращайтесь — увидите потенциал перераспределения.',
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

    out.push({
      severity: 'success',
      text: `Готово к оптимизации: ${dec.channels.length} канал${dec.channels.length > 4 ? 'ов' : dec.channels.length > 1 ? 'а' : ''}, бюджет ${totalSpend.toLocaleString('ru-RU')}₽, средний ROI ${avgROI.toFixed(2)}×.`,
      tip: 'Нажмите «🎯 Оптимизировать бюджет» — модель найдёт распределение, максимизирующее KPI при заданных Мин/Макс ограничениях.',
    });

    // Прогноз потенциала по структуре каналов
    if (saturated > efficient) {
      out.push({
        severity: 'warning',
        text: `Каналов в плато: ${saturated} (перенасыщены). Эффективных: ${efficient}. Прирост в рамках текущего бюджета может быть близок к 0% — оптимизатору некуда «переливать» деньги.`,
        tip: 'Что попробовать:\n• Снизить Мин. % (разрешить более радикальные сокращения)\n• Повысить Макс. % (разрешить больший рост недонасыщенных)\n• Использовать What-if (блок C) — увеличить общий бюджет и пересчитать\n• Проверить TRPs/non-money каналы — они искажают модель.',
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
      tip: '• Мин. % / Макс. % — глобальные границы изменения каждого канала.\n• Фиксировать бюджет — оптимизатор только перераспределяет, не меняет сумму.\n• Эксперт-режим — per-channel ограничения (зафиксировать TV-сделку, разрешить только рост OOH и т.д.).',
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
      tip: 'Текущее распределение приемлемое. Перераспределение даст устойчивый прирост, но не радикальный — план уже близок к рациональному.',
    });
  } else if (lift > 0.5) {
    out.push({
      severity: 'info',
      text: `Прирост +${lift.toFixed(1)}% — текущее распределение почти оптимально.`,
      tip: 'Незначительный потенциал в рамках того же бюджета. Чтобы существенно улучшить — нужен либо рост бюджета (см. блок C What-if), либо пересмотр медиа-микса.',
    });
  } else {
    out.push({
      severity: 'warning',
      text: `Прирост ≈${lift.toFixed(1)}%. Оптимизатор не нашёл выигрыша в рамках текущих ограничений.`,
      tip: 'Это не баг — модель честно говорит «лучше уже не сделаешь в этих рамках». Причины обычно две: (1) большинство каналов уже на saturation plateau — каждый доп.рубль даёт меньше 1 рубля продаж, (2) Мин/Макс % слишком узкие, нет пространства для перекладки. Смотрите следующие инсайты для разбора по каналам.',
    });
  }

  // ── 2. Рыночный контекст: средний ROI и общий бюджет ──
  if (avgROI > 0) {
    let roiComment = '';
    let roiSev = /** @type {'success' | 'info' | 'warning'} */ ('info');
    if (avgROI >= 3) { roiComment = 'Сильная отдача медиа'; roiSev = 'success'; }
    else if (avgROI >= 1.5) { roiComment = 'Здоровый уровень'; }
    else if (avgROI >= 1) { roiComment = 'Медиа окупается, но слабо'; roiSev = 'warning'; }
    else { roiComment = 'Медиа в среднем не окупается'; roiSev = 'warning'; }
    out.push({
      severity: roiSev,
      // Audit pass 15 (Антон 2026-05-03): scale consistency. avgROI =
      // totalContribDec / totalSpendDec — ОБЕ величины из decompose (training).
      // Pre-fix text использовал totalBudgetMoney (optimize/planning) → math
      // 842M / 1.781B = 0.47×, customer видел «0.18×» которое реально 842M /
      // 4.338B (training). Fix: показываем training spend (denominator avgROI)
      // → ratio совпадает: 0.18× = 842M / 4338M.
      text: `Средний ROI = ${avgROI.toFixed(2)}× — ${roiComment}. На ${Math.round(totalSpendDec).toLocaleString('ru-RU')}₽ обучающего расхода — медиа-вклад ${Math.round(totalContribDec).toLocaleString('ru-RU')}₽ (без baseline).`,
      tip: 'ROI рассчитан на обучающих данных (вся история). Прогноз для бюджета планирования может отличаться — см. блок B Прогноз KPI.\n\nBenchmark: ROI ≥ 2× — отлично; 1-2× — приемлемо, нужно улучшать микс; < 1× — медиа в среднем работает в убыток, требуется пересмотр каналов или креатива.',
    });
  }

  // ── 3. Saturation breakdown по mROAS (идентично светофору в блоке A) ──
  // Если доступен live channelBudgets (слайдеры в блоке B) — используем его, иначе
  // fallback на current_spend из последнего optimize run. buildScaledParams делает
  // нормализацию по reference-spend, которую брать из optimize (это не меняется при
  // движении слайдеров — это «nominal» от первоначальной тренировки).
  /** @type {Array<{name: string, mroas: number, status: 'scale'|'stable'|'saturated'|'unused'}>} */
  const satList = [];
  // Phase 2 audit pass 9 (2026-05-03): TWO sources of truth unification.
  // Pass 8 заменил frontend marginalROI() на ch.mroi_current — числа совпали с
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
      // Zero-spend or untrained — unused (table treats same way)
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

  // Unit-smell из decompose (отдельный сигнал — не связан с mROAS)
  /** @type {Array<{name: string, roi: number}>} */
  const suspicious = decChannels
    .filter((/** @type {any} */ c) => /подозрительно/i.test(c.verdict || ''))
    .map((/** @type {any} */ c) => ({ name: c.name, roi: c.roi ?? 0 }));

  // Всегда показываем расклад по saturation (4 категории) — стабильное количество инсайтов.
  if (satList.length > 0) {
    const rows = [];
    if (effective.length > 0) rows.push(`🟢 Недонасыщены: ${effective.length} — ${effective.map(c => `${c.name} (mROAS ${c.mroas.toFixed(2)}×)`).join(', ')}`);
    if (stable.length > 0) rows.push(`🟡 Стабильны: ${stable.length} — ${stable.map(c => `${c.name} (mROAS ${c.mroas.toFixed(2)}×)`).join(', ')}`);
    if (saturated.length > 0) rows.push(`🔴 Перенасыщены: ${saturated.length} — ${saturated.map(c => `${c.name} (mROAS ${c.mroas.toFixed(2)}×)`).join(', ')}`);
    if (unused.length > 0) rows.push(`⚪ Не используются: ${unused.length} — ${unused.map(c => c.name).join(', ')}`);

    const headline =
      saturated.length >= Math.ceil(satList.length / 2)
        ? `${saturated.length} из ${satList.length} каналов перенасыщены — оптимизатор упирается в плато.`
        : effective.length >= 1 && saturated.length === 0
          ? `${effective.length} канал${effective.length > 1 ? 'а' : ''} в зоне роста — есть куда вкладывать.`
          : `Расклад: 🟢${effective.length} 🟡${stable.length} 🔴${saturated.length}${unused.length > 0 ? ` ⚪${unused.length}` : ''} из ${satList.length}.`;

    const sev = saturated.length >= Math.ceil(satList.length / 2)
      ? /** @type {'warning'} */ ('warning')
      : effective.length >= 1 && saturated.length === 0
        ? /** @type {'success'} */ ('success')
        : /** @type {'info'} */ ('info');

    out.push({
      severity: sev,
      text: headline,
      tip: rows.join('\n') + '\n\nКритерии по mROAS (предельная отдача следующего рубля):\n• > 1.5× — недонасыщен (масштабировать)\n• 0.8–1.5× — стабильная зона (сохранить)\n• < 0.8× — перенасыщен (сократить)\n• 0 — не используется.',
    });
  }

  // ── 4. miROAS leaders (стабильный инсайт — всегда виден) ──
  const activeSat = satList.filter(s => s.status !== 'unused' && s.mroas > 0);
  if (activeSat.length >= 2) {
    const sorted = [...activeSat].sort((a, b) => b.mroas - a.mroas);
    const best = sorted[0];
    const worst = sorted[sorted.length - 1];
    const spread = worst.mroas > 0 ? best.mroas / worst.mroas : 0;
    const spreadNote = spread > 10
      ? ` Разброс ${spread.toFixed(0)}× — есть реальный потенциал перекладки.`
      : spread > 3
        ? ` Умеренный разброс — потенциал есть, но ограниченный.`
        : ' Каналы выровнены — перекладка не даст существенного прироста.';
    out.push({
      severity: 'info',
      text: `Предельная отдача (mROAS): лучший ${best.name} (${best.mroas.toFixed(2)}×), худший ${worst.name} (${worst.mroas.toFixed(2)}×).${spreadNote}`,
      tip: 'mROAS — сколько рублей KPI приносит следующий рубль в канал (не путать с ROI, который про средний за период). Классическое правило оптимизации: переливать из канала с низким mROAS в канал с высоким, пока они не сравняются.',
    });
  } else if (activeSat.length === 1) {
    const only = activeSat[0];
    out.push({
      severity: 'warning',
      text: `Активен только 1 канал (${only.name}, mROAS ${only.mroas.toFixed(2)}×). Модель не может оценить перекладку — нужно включить хотя бы 2 канала.`,
      tip: 'Поставьте бюджет на остальных каналах > 0, чтобы увидеть сравнение mROAS. Каналы с 0₽ модель считает «не используются» и их отдача недоступна.',
    });
  } else if (satList.length > 0) {
    out.push({
      severity: 'warning',
      text: `Все ${satList.length} каналов с нулевым бюджетом — сравнить mROAS невозможно.`,
      tip: 'Верните бюджет хотя бы 2 каналам, чтобы увидеть их относительную эффективность.',
    });
  }

  // ── 5. Unit-smell / trust warning ──
  if (suspicious.length > 0) {
    out.push({
      severity: 'warning',
      text: `⚠ ${suspicious.length} канал${suspicious.length > 4 ? 'ов' : suspicious.length > 1 ? 'а' : ''} с подозрительно высоким ROI — не используйте их оценки для бюджетных решений.`,
      tip: suspicious.map(c => `⚠ ${c.name} — ROI ${c.roi.toFixed(1)}×`).join('\n') +
        '\n\nПричины завышенного ROI обычно две: (1) переобучение модели на коротких данных (Ratio < 4:1), (2) смешанные единицы измерения (TRP + рубли в одной модели). Оптимизатор учитывает эти цифры как есть — вручную скорректируйте рекомендации.',
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
      tip: lines + '\n\nПерекладка идёт из перенасыщенных каналов в недонасыщенные — где каждый рубль ещё работает на полную.',
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
      tip: 'Custom-лимиты учтены оптимизатором как hard-constraints (бизнес-ограничения: контракты, обязательства). Без них достижимый lift мог бы быть выше — но рекомендации были бы нереалистичны.',
    });
  }

  // ── 4. Total budget изменение (если What-if когда-нибудь добавим) ──
  if (totalBudget > 0 && Math.abs(totalOptimal - totalCurrent) / Math.max(totalCurrent, 1) > 0.05) {
    const diff = totalOptimal - totalCurrent;
    const sign = diff > 0 ? '+' : '';
    out.push({
      severity: 'info',
      text: `Оптимальный общий бюджет: ${totalOptimal.toLocaleString('ru-RU')}₽ (${sign}${diff.toLocaleString('ru-RU')}₽ к текущему ${totalCurrent.toLocaleString('ru-RU')}₽).`,
      tip: 'Это значит «Фиксировать бюджет» был выключен — оптимизатор сам нашёл лучшую сумму в рамках per-channel лимитов.',
    });
  }

  // ── 6. Action items: куда дальше (context-aware) ──
  const noLift = Math.abs(lift) < 0.5;
  const manyChannelsSaturated = saturated.length >= Math.ceil(satList.length / 2);
  /** @type {string[]} */
  const actions = [];
  if (noLift) {
    actions.push('• Блок C (What-if) — подвигайте общий бюджет ×1.2–×1.5: увидите куда модель хочет направить доп.деньги.');
    actions.push('• Блок D (Forecast) — спрогнозируйте KPI на следующий период с учётом медиаинфляции.');
    if (manyChannelsSaturated) {
      actions.push('• Расширьте границы — Мин. % → 20–30%, Макс. % → 200–300%: оптимизатор получит пространство для перекладки.');
      actions.push('• Стратегически — обновите креатив или добавьте новый канал: Hill saturation «не знает» о новой кампании, но на практике свежий креатив возвращает канал к точке до плато.');
    }
  } else if (lift > 15) {
    actions.push('• Пилот 4-6 недель на 20-30% бюджета с новыми пропорциями — валидация модельных оценок.');
    actions.push('• Блок E (Сценарии) — сохраните этот оптимум, сравните с другими конфигурациями.');
    actions.push('• Эксперт-режим в блоке B — если есть бизнес-ограничения (подписанные контракты, sponsor obligations), зафиксируйте каналы.');
  } else {
    actions.push('• Блок C (What-if) — поэкспериментируйте с бюджетом ±30%.');
    actions.push('• Блок D (Forecast) — планирование следующего периода.');
    actions.push('• Блок E (Сценарии) — сохраните и сравните несколько вариантов.');
    actions.push('• Подтвердить и перейти к отчёту — когда план устраивает.');
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
 * @param {{ mod?: any, dec?: any, opt?: any, scenarioCount?: number }} ctx
 * @returns {Insight[]}
 */
export function reportInsights(ctx = {}) {
  /** @type {Insight[]} */
  const out = [];
  const { mod, dec, opt, scenarioCount = 0 } = ctx;
  const mqs = mod?.diagnostics?.mqs?.score ?? null;
  const tierLabel = mod?.diagnostics?.mqs?.tier_label ?? '';
  const rSq = mod?.diagnostics?.metrics?.r_squared ?? null;
  const mape = mod?.diagnostics?.metrics?.mape_pct ?? null;
  const ratio = mod?.diagnostics?.metrics?.ratio ?? null;
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
  const isThin = ratio != null && ratio < 4;
  const mqsParts = [`MQS ${mqs.toFixed(0)} (${tierLabel})`];
  if (rSq != null) mqsParts.push(`R² ${rSq.toFixed(3)}`);
  if (mape != null) mqsParts.push(`MAPE ${mape.toFixed(1)}%`);
  if (ratio != null) mqsParts.push(`Ratio ${ratio.toFixed(1)}:1`);

  if (mqs >= 80 && !isThin) {
    out.push({
      severity: 'success',
      text: `🎯 Модель: ${mqsParts.join(' · ')}. Результаты надёжны.`,
      tip: `Рекомендация: используйте выводы отчёта для бюджетных решений. Спецификация модели, priors и доверительные интервалы экспортируются в PPTX/MD/XLSX для воспроизводимости.\n\nВалидационный критерий: посмотрите график «Факт vs Прогноз» в отчёте — линии должны накладываться без систематического смещения.`,
    });
  } else if (isThin) {
    out.push({
      severity: 'warning',
      text: `⚠ Модель: ${mqsParts.join(' · ')}. Данных мало — возможно переобучение.`,
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
    const suspicious = decChannels.filter(/** @param {any} c */ c => /подозрительно/i.test(c.verdict || ''));

    /** @type {'success' | 'warning' | 'info'} */
    let sev = 'info';
    let headline = '';
    let reco = '';

    if (basePct != null) {
      if (basePct > 70) {
        sev = 'info';
        headline = `📊 Декомпозиция: base ${basePct.toFixed(0)}% / медиа ${(100 - basePct).toFixed(0)}%. Бренд в основном органический.`;
        reco = 'Рекомендация: оптимизируйте эффективность внутри существующего медиа-бюджета, не увеличивайте объём — рост ограничен саморазогревом бренда.';
      } else if (basePct < 30) {
        sev = 'warning';
        headline = `⚠ Декомпозиция: base ${basePct.toFixed(0)}% — бренд зависит от рекламы.`;
        reco = 'Рекомендация: долгосрочно — инвестиции в brand-equity (TV, OOH) для поднятия базы. Остановка медиа = риск значительного падения продаж.';
      } else {
        sev = 'success';
        headline = `✅ Декомпозиция: здоровый mix — base ${basePct.toFixed(0)}% / медиа ${(100 - basePct).toFixed(0)}%.`;
        reco = 'Рекомендация: сбалансированная модель. Реклама драйвит существенную долю продаж, бренд имеет органическую базу. Фокус — на эффективности перекладки.';
      }
    }

    if (top) {
      reco += `\n\nГлавный драйвер продаж: ${top.name} (${top.contribution_pct?.toFixed(0) ?? '—'}% от медиа-вклада, ROI ${top.roi?.toFixed(2) ?? '—'}×).`;
    }
    if (suspicious.length > 0) {
      reco += `\n\n⚠ ${suspicious.length} канал${suspicious.length > 4 ? 'ов' : suspicious.length > 1 ? 'а' : ''} с подозрительно высоким ROI (${suspicious.map(/** @param {any} s */ s => s.name).join(', ')}). Оценки этих каналов не используйте как абсолютные — только относительно.`;
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
        tip: 'Рекомендация: высокий потенциал перекладки. Конкретные суммы по каналам — в отчёте. Перед полным переходом — пилот 4-6 недель на части бюджета (20-30%), чтобы валидировать модельные оценки на практике.',
      });
    } else if (lift > 5) {
      out.push({
        severity: 'success',
        text: `📈 Оптимизация: +${lift.toFixed(1)}% — умеренный, но значимый потенциал.`,
        tip: 'Рекомендация: перекладка даст устойчивый прирост. Текущий план близок к рациональному — радикальной перестройки не требуется. Пилот на 20% бюджета для подтверждения.',
      });
    } else if (lift > 0.5) {
      out.push({
        severity: 'info',
        text: `📊 Оптимизация: +${lift.toFixed(1)}% — план почти оптимален.`,
        tip: 'Рекомендация: существенного потенциала в рамках текущего бюджета нет. Для роста нужен либо увеличенный бюджет (What-if), либо пересмотр медиа-микса (новый канал, обновление креатива).',
      });
    } else {
      out.push({
        severity: 'info',
        text: '🟰 Оптимизация: +0% — план уже оптимален в заданных рамках.',
        tip: 'Рекомендация: каналы на saturation plateau или Мин/Макс % слишком узкие. Для прорыва: (1) What-if с ростом бюджета +30-50%, (2) обновление креатива в насыщенных каналах, (3) добавление нового канала — Hill saturation «не знает» о новой кампании.',
      });
    }
  }

  // ════════════════ ЭТАП 4: Сценарии ════════════════
  if (scenarioCount > 0) {
    out.push({
      severity: 'info',
      text: `💼 Сценарии: сохранено ${scenarioCount}.`,
      tip: `Рекомендация: сравните сценарии в блоке E (Оптимизация) — таблица с ROAS, бюджетом и lift% покажет лучшую конфигурацию. Сохранённые планы экспортируются вместе с отчётом и доступны для следующих итераций.\n\nЧто обычно сохраняют: (1) Baseline — текущий план, (2) Optimal — результат оптимизации, (3) ±30% бюджета — what-if анализ, (4) Forecast — план на следующий период с учётом инфляции.`,
    });
  } else {
    out.push({
      severity: 'info',
      text: '💼 Сценарии: не сохранены.',
      tip: 'Рекомендация: вернитесь в блок E (Оптимизация → Сценарный анализ) и сохраните хотя бы 2 плана для сравнения — Baseline и Optimal. Это позволит отчёту показать альтернативы и обосновать решения.',
    });
  }

  // ════════════════ Экспорт ════════════════
  out.push({
    severity: 'info',
    text: '📤 Форматы экспорта:',
    tip: '• PPTX — для презентации заказчику/команде: executive summary, спецификация модели, декомпозиция, ROI, оптимизация.\n• XLSX — для аналитиков: метрики, спецификация, декомпозиция, ROI, Spend vs Effect, оптимизация, сырые time-series данные для собственных графиков, глоссарий.\n• HTML — интерактивный отчёт для удалённых клиентов: standalone-файл с живыми графиками (ECharts), waterfall, ROI, Spend vs Effect, динамика по периодам, оптимизация, сценарии. Открывается в любом браузере без установки приложения — отправляется как ссылка или вложение.\n\nВсе три формата содержат одну аналитику — выбирайте по аудитории и каналу доставки. К каждому файлу — автоматически генерируемый сопроводительный текст с описанием модели, результатов и ограничений.',
  });

  return out;
}
