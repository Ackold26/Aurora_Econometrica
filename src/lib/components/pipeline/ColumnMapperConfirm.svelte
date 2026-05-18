<script>
  /**
   * ColumnMapperConfirm - v1.3.1 / restyled v1.3.2.
   *
   * UX audit findings: ValidateStepV13 (new derived mode flow) НЕ показывает
   * ColumnMapper drag-drop (v1.2 feature). Backend auto-detects role через
   * column_detection.py, но юзер не видит / не подтверждает.
   *
   * Этот компонент показывает **detected roles в read-only table** с возможностью
   * override через dropdown. После confirm → переход к KPISelector.
   *
   * v1.3.2 restyle: removed emoji pictograms (🎯📊🔧📅❌⚠), replaced с premium
   * tier-1 typographic system - color-coded role badges (no emoji), serif/sans
   * split, sacred-lime header accent, mono font для column identifiers.
   * Matches Aurora deliverable brand styling.
   *
   * @component ColumnMapperConfirm
   */

  // v2.1.0 (rc2 retry): mode-aware рекомендации требуют доступа к analysisMode.
  import { analysisMode } from '$lib/project-state.js';

  const {
    columns = [],     // [{name, role, kind, stats?}]
    onConfirm,        // (mapping: Record<string, string>) => void
    /** Backend validate result - для warnings/issues per column. Если не
     *  передан - fallback на heuristic only. */
    validateResult = null,
    /** v1.3.2: insights-driven exclude map (column_name → insight.text).
     *  Computed by parent via validateInsights() - тот же source как
     *  InsightsPanel. Если колонка в map → recommendation = «Исключить»
     *  с insight text как reason. Гарантирует consistency между
     *  InsightsPanel и ColumnMapperConfirm. */
    insightExcludeMap = {},
    /** Real-time role change callback. Parent persists change в validateData
     *  store immediately → InsightsPanel + recommendations стабильно sync. */
    onRoleChange = null,
    /** v1.3.2: hard-block confirm button reason. Когда truthy, кнопка
     *  «Подтвердить роли» disabled и над ней показан reason text. Used для
     *  блокировки при ratio <2:1 (overfit risk). null/'' → button enabled. */
    blockedReason = null,
  } = $props();

  /** @type {Record<string, string>} */
  let overrides = $state({});

  const ROLES = /** @type {const} */ (['kpi', 'media', 'control', 'date', 'excluded']);
  /** @type {Record<string, {label: string, hint: string, tone: string}>} */
  const ROLE_META = {
    kpi:      { label: 'Целевая метрика', hint: 'KPI - что объясняем',  tone: 'gold'    },
    media:    { label: 'Медиа-канал',     hint: 'затраты или активность', tone: 'accent' },
    control:  { label: 'Контрольная',     hint: 'не-медиа фактор',        tone: 'neutral'},
    date:     { label: 'Дата',            hint: 'временной ряд',           tone: 'mono'   },
    excluded: { label: 'Не использовать', hint: 'игнорируем в модели',     tone: 'muted'  },
  };

  // Tooltips для column headers - explain все варианты per role + data kinds.
  const ROLE_HEADER_HELP = [
    'Каждая колонка играет одну роль в модели:',
    '',
    '• Целевая метрика (KPI) - то, что модель объясняет: продажи, выручка, лиды.',
    '• Медиа-канал - расходы или активность (TV GRP, OOH ₽, Digital impressions).',
    '• Контрольная - не-медиа фактор: сезонность, цена, погода, конкурент.',
    '• Дата - временной столбец (неделя / месяц).',
    '• Не использовать - колонка исключается из модели.',
    '',
    'Программа автоматически определяет роль по имени и типу данных. Измените, если что-то определено неверно.',
  ].join('\n');

  const KIND_HEADER_HELP = [
    'Тип данных колонки (определён автоматически):',
    '',
    '• Число - целое или дробное (бюджеты, продажи, GRP, проценты).',
    '• Дата - временной маркер (неделя / месяц).',
    '• Текст - название категории, бренд, тег.',
    '• Флаг - true/false / 0-1 (вкл/выкл, акция/не акция).',
    '',
    'Для MMM требуется числовая целевая метрика, числовые медиа-каналы и одна date-колонка.',
  ].join('\n');

  const RECO_HEADER_HELP = [
    'Автоматическая рекомендация по колонке на основе типа данных, роли',
    'и validation insights:',
    '',
    '• Оставить - колонка подходит для модели как есть.',
    '• Проверить - есть подозрительные сигналы (роль не определена,',
    '  пустые значения, дубликат метрики). Подтвердите вручную.',
    '• Исключить - колонка непригодна (нечисловой тип в числовой роли,',
    '  >80% нулей, текстовое поле).',
    '',
    'Рекомендации - подсказки, не блокирующие. Окончательное решение',
    'за вами.',
  ].join('\n');

  // v2.1.0 (пилот 2026-05-16): столбец «Объём за период» помогает бренд-
  // менеджеру оценить масштаб канала / показателя за всю историю данных
  // одним взглядом. Полезен для решения «оставить vs исключить» и для
  // отсева мелких / шумных факторов.
  const VOLUME_HEADER_HELP = [
    'Суммарное значение колонки за весь период данных:',
    '',
    '• Бюджеты - общая сумма потраченного в рублях.',
    '• TRP / GRP - суммарные рейтинги за весь период.',
    '• Показы / клики / просмотры - суммарное количество контактов.',
    '• Целевая метрика (продажи, выручка) - итог за период.',
    '',
    'Помогает увидеть масштаб каждого фактора и сравнить их между собой.',
    'Дата и текст не имеют суммы - отображаются как «-».',
  ].join('\n');

  /**
   * Translates pandas dtype names (float64, int64, object, datetime64, bool)
   * к человеческим русским labels. Fallback: «-» если type unknown.
   * @param {string | null | undefined} rawKind
   * @returns {string}
   */
  function humanizeKind(rawKind) {
    if (!rawKind) return '-';
    const k = String(rawKind).toLowerCase();
    if (k.includes('datetime') || k === 'date' || k.includes('timestamp')) return 'дата';
    if (k === 'bool' || k === 'boolean') return 'флаг';
    if (k.includes('int') || k.includes('float') || k === 'number' || k === 'numeric') return 'число';
    if (k === 'object' || k === 'string' || k === 'str' || k === 'text' || k.includes('category')) return 'текст';
    return rawKind;  // unknown - show as-is для debugging
  }

  /** @typedef {{ status: 'keep' | 'review' | 'exclude', label: string, reason: string, tone: string }} Recommendation */

  /**
   * Backend warnings/issues filtered per column. Reactively recomputes when
   * validateResult changes (after InsightsPanel action или role override).
   *
   * @param {string} colName
   * @returns {{ critical: any[], warning: any[] }}
   */
  function findingsFor(colName) {
    if (!validateResult) return { critical: [], warning: [] };
    /** @type {any[]} */
    const issues = Array.isArray(validateResult.issues) ? validateResult.issues : [];
    /** @type {any[]} */
    const warnings = Array.isArray(validateResult.warnings) ? validateResult.warnings : [];
    return {
      critical: issues.filter(i => i?.column === colName),
      warning: warnings.filter(w => w?.column === colName),
    };
  }

  /**
   * Generate recommendation для колонки. Приоритет:
   * 1. Backend critical issues (severity='critical') → «Исключить».
   * 2. Backend warnings (severity='warning') → «Проверить» с message.
   * 3. Type/role mismatch heuristic (text в numeric role) → «Исключить».
   * 4. Stats-based heuristic (zeros >80%, missing >30%) → «Исключить»/«Проверить».
   * 5. excluded role → «Не используется» neutral.
   * 6. Default → «Оставить».
   *
   * Insights-driven: when InsightsPanel applies action (excludes columns),
   * validateData updates → findingsFor sees new state → recommendation
   * recomputes automatically.
   *
   * @param {any} col
   * @returns {Recommendation}
   */
  /**
   * v2.1.0 (rc2 пилот retry): защита важных медиа-каналов (TRP / GRP / ТВ
   * бренда) от автоматического исключения. ТВ обычно 30-70% медиа-бюджета
   * OTC фарма-бренда - убийство этого канала ради улучшения ratio даёт
   * omitted variable bias, ROI остальных каналов завышается в 2-4 раза.
   *
   * Если канал распознан как критичный media:
   *   - Любая рекомендация «Исключить» -> понижается до «Проверить»
   *   - Reason дополняется подсказкой про конверсию (физика <-> деньги)
   *
   * @param {string} name
   * @returns {boolean}
   */
  function isCriticalMediaChannel(name) {
    if (!name) return false;
    const upper = String(name).toUpperCase();
    if (/(^|[^A-Z])(TRP|GRP)/i.test(upper)) return true;
    if (/(^|\s|_|-)(ТВ|TV|ТЕЛЕВИЗ)/i.test(upper)) return true;
    if (/(^|[^A-Z])(OLV|BANNER|БАННЕР|МЕДИЙ)/i.test(upper)) return true;
    // v2.1.0 pilot polish (2026-05-17): расширенный список media types
    // (sync с validator.py:MEDIA_PATTERNS - радио/пресса/OOH/print).
    if (/(^|\s|_|-)(РАДИО|RADIO)/i.test(upper)) return true;
    if (/(^|\s|_|-)(ПРЕССА|PRESS)/i.test(upper)) return true;
    if (/(^|[^A-Z])(OOH|OUTDOOR)/i.test(upper)) return true;
    if (/(^|\s|_|-)(НАРУЖН|ООН)/i.test(upper)) return true;
    if (/(^|\s|_|-)(ПЕЧАТ|PRINT)/i.test(upper)) return true;
    return false;
  }

  /**
   * v2.1.0 (rc2 retry): распознаёт колонку как физическую метрику
   * (TRP / GRP / показы / клики / визиты / просмотры / охваты).
   * @param {string} name
   * @returns {boolean}
   */
  function isPhysicalMetric(name) {
    if (!name) return false;
    const upper = String(name).toUpperCase();
    return /(^|\s|_|-|[^A-Z])(TRP|GRP|ПОКАЗ|IMPRESS|КЛИК|CLICK|ВИЗИТ|VISIT|OTS|VIEW|ПРОСМОТР|РЕЙТИНГ|REACH|ОХВАТ)/i.test(upper);
  }

  /**
   * v2.1.0 (rc2 retry): распознаёт колонку как денежную метрику
   * (бюджет / спенд / ₽ / cost).
   * @param {string} name
   * @returns {boolean}
   */
  function isMonetaryMetric(name) {
    if (!name) return false;
    const upper = String(name).toUpperCase();
    return /(^|\s|_|-)(БЮДЖЕТ|BUDGET|SPEND|РУБ|РУБЛ|COST|СПЕНД|РАСХОД)/i.test(upper) || /[₽]/.test(name);
  }

  /**
   * v2.1.0 (rc2 retry): извлекает корневое имя канала для pair detection.
   * «OLV Бюджет до НДС» → «OLV»; «OLV Показы» → «OLV».
   * @param {string} name
   * @returns {string}
   */
  function extractChannelRoot(name) {
    if (!name) return '';
    const upper = String(name).toUpperCase();
    // Известные prefix-имена каналов.
    const knownPrefixes = ['OLV', 'BANNERS', 'BANNER', 'SOCIAL', 'PERFORMANCE', 'RETAIL', 'TV', 'ТВ', 'РАДИО', 'RADIO', 'ПРЕССА', 'PRESS', 'OOH', 'ООН', 'SEARCH', 'CONTEXT', 'DIGITAL', 'YOUTUBE', 'VK', 'OK', 'TELEGRAM', 'TG'];
    for (const prefix of knownPrefixes) {
      if (upper.startsWith(prefix)) return prefix;
    }
    // Fallback: первое слово.
    return upper.split(/\s|_|-/)[0] || upper;
  }

  /**
   * v2.1.0 (rc2 retry): находит парную метрику для канала. Парная = другая
   * колонка media с тем же channel root, но другой kind (monetary <-> physical).
   *
   * Пример: «OLV Бюджет» ↔ «OLV Показы» парные. В ROI режиме оставляем бюджет,
   * исключаем показы (мультиколлинеарность).
   *
   * @param {string} name - текущая колонка
   * @returns {{ name: string, kind: 'monetary' | 'physical' } | null}
   */
  function findPairedMetric(name) {
    if (!name) return null;
    const selfKind = isMonetaryMetric(name) ? 'monetary' : isPhysicalMetric(name) ? 'physical' : null;
    if (!selfKind) return null;
    const root = extractChannelRoot(name);
    if (!root) return null;
    for (const c of columns) {
      if (!c?.name || c.name === name) continue;
      if (c.role !== 'media') continue;
      const otherRoot = extractChannelRoot(c.name);
      if (otherRoot !== root) continue;
      const otherKind = isMonetaryMetric(c.name) ? 'monetary' : isPhysicalMetric(c.name) ? 'physical' : null;
      if (!otherKind || otherKind === selfKind) continue;
      return { name: c.name, kind: /** @type {'monetary' | 'physical'} */ (otherKind) };
    }
    return null;
  }

  /**
   * Generate recommendation для колонки (см. README JSDoc выше).
   * @param {any} col
   * @returns {Recommendation}
   */
  function recommendationFor(col) {
    if (!col) {
      return { status: 'review', label: 'Проверить', reason: 'Нет данных по колонке.', tone: 'neutral' };
    }
    const role = effectiveRole(col.name);
    const findings = findingsFor(col.name);
    const mode = $analysisMode || 'roi';
    const isCritical = isCriticalMediaChannel(col.name) && role === 'media';

    // v2.1.0 (пилот 2026-05-16): zeros >80% для media-каналов проверяем
    // ДО mode-aware блока. Антон в пилоте: «почему реко - оставить, если
    // там более 80% нулей? И одновременно есть рекомендация убрать (банер
    // "исключите 4 канала с большой долей нулей")».
    // Причина: mode-aware ROI блок возвращал «Оставить» для любого ₽-канала
    // независимо от data quality - конфликт с banner и ConfigPanel
    // auto-uncheck (channelEnabled = !(zeros_pct > 80)).
    if (role === 'media') {
      const zerosPct = Number(col.stats?.zeros_pct ?? 0);
      if (zerosPct > 80) {
        if (isCritical) {
          // ТВ / OLV / Banners с >80% нулей - возможно сезонная активность.
          return {
            status: 'review',
            label: 'Проверить',
            reason: `${Math.round(zerosPct)}% нулей - возможно сезонная активность канала. Перед исключением убедитесь, что данные за активные периоды полны.`,
            tone: 'warn',
          };
        }
        return {
          status: 'exclude',
          label: 'Исключить',
          reason: `${Math.round(zerosPct)}% нулей - канал почти не активен, недостаточно данных для устойчивой оценки эффекта. Также влияет на ratio данных.`,
          tone: 'danger',
        };
      }
    }

    // ───────────────────────────────────────────────────────────────
    // v2.1.0 (rc2 retry): MODE-AWARE ИЕРАРХИЯ для media каналов.
    // Применяется ПЕРВОЙ - до insights-driven и backend warnings.
    // Логика:
    //   ROI режим:
    //     1. Бюджет в ₽           → ✅ Оставить (готов для ROI)
    //     2. Физика + парный ₽    → ❌ Исключить (мультиколлинеарность)
    //     3. Физика без пары + critical → ⚠ Проверить (конверсия)
    //     4. Физика без пары      → ⚠ Проверить (конверсия или исключить)
    //   Эффективность режим (симметрично):
    //     1. Физика               → ✅ Оставить
    //     2. ₽ + парная физика    → ❌ Исключить
    //     3. ₽ без пары           → ⚠ Проверить (обратная конверсия)
    // ───────────────────────────────────────────────────────────────
    if (role === 'media') {
      const isMonetary = isMonetaryMetric(col.name);
      const isPhysical = isPhysicalMetric(col.name);
      const pair = (isMonetary || isPhysical) ? findPairedMetric(col.name) : null;

      if (mode === 'roi') {
        if (isMonetary) {
          // Бюджет в ₽ - идеально для ROI режима.
          return {
            status: 'keep',
            label: 'Оставить',
            reason: 'Бюджет в ₽ - готов для ROI модели.',
            tone: 'ok',
          };
        }
        if (isPhysical && pair && pair.kind === 'monetary') {
          // Парный ₽ есть - физика дублирует, исключить (мультиколлинеарность).
          return {
            status: 'exclude',
            label: 'Исключить',
            reason: `Дублирует «${pair.name}» (парный бюджет того же канала). В ROI режиме оставьте один - бюджет в ₽.`,
            tone: 'danger',
          };
        }
        if (isPhysical && isCritical) {
          // Критичный physical канал без парного бюджета - конверсия нужна.
          return {
            status: 'review',
            label: 'Проверить',
            reason: 'Важный медиа-канал без парного бюджета в ₽. На следующем шаге укажите цену единицы (CPP/CPM) для конверсии - иначе модель не посчитает ROI этого канала.',
            tone: 'warn',
          };
        }
        if (isPhysical) {
          // Не critical physical без пары - тоже конверсия или явное исключение.
          return {
            status: 'review',
            label: 'Проверить',
            reason: 'Физическая метрика без парного бюджета. В ROI режиме нужна конверсия в ₽ (CPP/CPM) или исключение из модели.',
            tone: 'warn',
          };
        }
      } else if (mode === 'effectiveness') {
        if (isPhysical) {
          return {
            status: 'keep',
            label: 'Оставить',
            reason: 'Физические контакты - готовы для режима Эффективность.',
            tone: 'ok',
          };
        }
        if (isMonetary && pair && pair.kind === 'physical') {
          return {
            status: 'exclude',
            label: 'Исключить',
            reason: `Дублирует «${pair.name}» (парные физические контакты того же канала). В режиме Эффективность оставьте физику.`,
            tone: 'danger',
          };
        }
        if (isMonetary) {
          return {
            status: 'review',
            label: 'Проверить',
            reason: 'В режиме Эффективность нужны физические контакты. Бюджет можно конвертировать через обратное CPP/CPM или исключить.',
            tone: 'warn',
          };
        }
      }
      // Mixed Expert или unrecognized kind - падаем в обычные проверки ниже.
    }

    // 0. v1.3.2: insights-driven exclude - применяется ПОСЛЕ mode-aware
    //    решения. Для media каналов вышеприведённая логика уже отработала.
    //    Здесь обрабатываем controls / KPI / прочее.
    if (insightExcludeMap?.[col.name] && role !== 'excluded') {
      if (isCritical) {
        return {
          status: 'review',
          label: 'Проверить',
          reason: `Важный медиа-канал. ${insightExcludeMap[col.name]} Рассмотрите конверсию (TRP → ₽ через CPP, или наоборот) перед исключением.`,
          tone: 'warn',
        };
      }
      return {
        status: 'exclude',
        label: 'Исключить',
        reason: insightExcludeMap[col.name],
        tone: 'danger',
      };
    }

    // 1. Backend critical issues - next priority.
    if (findings.critical.length > 0) {
      const msg = findings.critical[0]?.message ?? 'Критическая проблема в данных.';
      return {
        status: 'exclude',
        label: 'Исключить',
        reason: `Критическая проблема: ${msg}`,
        tone: 'danger',
      };
    }

    // 2. Backend warnings (active only когда role != excluded - excluded skip warnings).
    if (findings.warning.length > 0 && role !== 'excluded') {
      const w = findings.warning[0];
      const msg = w?.message ?? 'Предупреждение по колонке.';
      // Decide tone by warning type/severity. Default - warn (gold).
      const severeTypes = new Set(['insufficient_data', 'too_many_zeros', 'collinearity', 'duplicate_metric']);
      const isSevere = severeTypes.has(String(w?.type ?? ''));
      // v2.1.0 (rc2 retry): для критичных media каналов severe warning
      // не переводим в «Исключить» автоматически - понижаем до «Проверить»
      // с подсказкой про конверсию или объединение метрик.
      if (isSevere && isCritical) {
        return {
          status: 'review',
          label: 'Проверить',
          reason: `Важный медиа-канал. ${msg} Возможные действия: конверсия (TRP <-> ₽), объединение с парной метрикой, или сбор больше истории.`,
          tone: 'warn',
        };
      }
      const tone = isSevere ? 'danger' : 'warn';
      const label = tone === 'danger' ? 'Исключить' : 'Проверить';
      const status = tone === 'danger' ? 'exclude' : 'review';
      return { status, label, reason: msg, tone };
    }

    // 3-4. Heuristic fallback когда backend findings отсутствуют.
    const rawKind = String(col.kind ?? '').toLowerCase();
    const isNumeric = rawKind.includes('int') || rawKind.includes('float') || rawKind === 'number' || rawKind === 'numeric';
    const isDate = rawKind.includes('datetime') || rawKind === 'date' || rawKind.includes('timestamp');
    const isText = rawKind === 'object' || rawKind === 'string' || rawKind === 'str' || rawKind === 'text' || rawKind.includes('category');
    const zerosPct = Number(col.stats?.zeros_pct ?? 0);
    const missingPct = Number(col.stats?.missing_pct ?? 0);

    if ((role === 'kpi' || role === 'media' || role === 'control') && !isNumeric) {
      if (isText) {
        return { status: 'exclude', label: 'Исключить', reason: 'Текстовый тип данных не подходит для числовой роли в модели.', tone: 'danger' };
      }
      if (isDate) {
        return { status: 'exclude', label: 'Исключить', reason: 'Колонка с датой не может играть роль числового канала.', tone: 'danger' };
      }
    }
    if (role === 'date' && !isDate) {
      return { status: 'review', label: 'Проверить', reason: 'Роль "Дата" назначена, но тип данных не похож на дату.', tone: 'warn' };
    }
    if (isNumeric && zerosPct > 80 && role !== 'excluded') {
      // v2.1.0 (rc2 retry): даже при >80% нулей, критичные media каналы
      // (ТВ TRP/GRP) не исключаем автоматически - может быть сезонная
      // активность. Понижаем до «Проверить».
      if (isCritical) {
        return {
          status: 'review',
          label: 'Проверить',
          reason: `${Math.round(zerosPct)}% нулей - возможно сезонная активность канала. Перед исключением убедитесь, что данные за активные периоды полны.`,
          tone: 'warn',
        };
      }
      return { status: 'exclude', label: 'Исключить', reason: `${Math.round(zerosPct)}% нулей - недостаточно данных для устойчивой оценки эффекта.`, tone: 'danger' };
    }
    if (isNumeric && zerosPct > 50 && role !== 'excluded') {
      return { status: 'review', label: 'Проверить', reason: `${Math.round(zerosPct)}% нулей - канал малоактивен, проверьте полноту данных.`, tone: 'warn' };
    }
    if (isNumeric && missingPct > 30 && role !== 'excluded') {
      return { status: 'review', label: 'Проверить', reason: `${Math.round(missingPct)}% пропусков - может ослабить модель.`, tone: 'warn' };
    }

    // 5. Excluded role - neutral state.
    if (role === 'excluded') {
      return { status: 'review', label: 'Не используется', reason: 'Колонка исключена из модели. Если это намеренно - оставьте как есть.', tone: 'neutral' };
    }

    // 5b. F-003 pilot (2026-05-18): KPI-like колонка (sales/выручка/leads/...)
    // НЕ должна быть «Оставить» когда роль НЕ kpi И уже выбрана другая KPI.
    // Customer ошибочно мог взять её как control / media. Помечаем
    // «Альтернативная цель» чтобы навести на мысль о role review.
    //
    // F-003 hardening (audit 2026-05-18): conditional on existing KPI presence.
    // Иначе legitimate control columns с именем «Продажи конкурентов» получали
    // ложный flag «Альтернативная цель» при том что KPI ещё не выбран.
    const kpiLikeRe = /продаж|sales|выручк|revenue|доход|profit|лид|leads|конверси|conversion|регистраций|signups|подписк|subscrib/i;
    const hasActiveKpi = columns.some(
      (/** @type {any} */ c) => effectiveRole(c.name) === 'kpi'
    );
    if (
      hasActiveKpi &&
      isNumeric &&
      role !== 'kpi' &&
      role !== 'media' &&
      role !== 'excluded' &&
      kpiLikeRe.test(String(col.name || ''))
    ) {
      return {
        status: 'review',
        label: 'Альтернативная цель',
        reason: 'Похоже на потенциальную KPI-метрику. KPI уже выбрана для другой колонки (одна KPI на проект). Если хотите моделировать эту - переназначьте роль. Иначе исключите.',
        tone: 'warn',
      };
    }

    // 6. Default: passes all checks.
    return { status: 'keep', label: 'Оставить', reason: 'Колонка подходит для выбранной роли. Никаких действий не требуется.', tone: 'ok' };
  }

  /**
   * v2.1.0 (пилот 2026-05-16): авто-определение единицы измерения колонки
   * для столбца «Объём за период». Используется ИМЯ колонки (а не тип
   * данных), потому что backend возвращает всё как float64 / int64.
   *
   * Денежные → «₽», TRP/GRP → как есть, физика → русское слово в
   * родительном падеже (показов / кликов / визитов / просмотров / охватов /
   * лидов / заявок / регистраций). Если ничего не распознано - пустая
   * строка (значение покажется без единицы измерения).
   *
   * @param {string} name
   * @returns {string}
   */
  function detectVolumeUnit(name) {
    if (!name) return '';
    const upper = String(name).toUpperCase();
    if (isMonetaryMetric(name)) return '₽';
    if (/(^|[^A-Z])TRP/i.test(upper)) return 'TRP';
    if (/(^|[^A-Z])GRP/i.test(upper)) return 'GRP';
    if (/ПОКАЗ|IMPRESS/i.test(upper)) return 'показов';
    if (/КЛИК|CLICK/i.test(upper)) return 'кликов';
    if (/ВИЗИТ|VISIT/i.test(upper)) return 'визитов';
    if (/ПРОСМОТР|VIEW/i.test(upper)) return 'просмотров';
    if (/ОХВАТ|REACH/i.test(upper)) return 'охватов';
    if (/ЛИД(?!Е)|LEAD/i.test(upper)) return 'лидов';
    if (/ЗАЯВ/i.test(upper)) return 'заявок';
    if (/РЕГИСТРАЦ|SIGNUP/i.test(upper)) return 'регистраций';
    if (/ПОДПИС|SUBSCRIB/i.test(upper)) return 'подписок';
    if (/ПРОДАЖ|SALES|UNITS/i.test(upper)) return 'шт.';
    if (/ВЫРУЧК|REVENUE|ДОХОД/i.test(upper)) return '₽';
    return '';
  }

  /**
   * v2.1.0 (пилот 2026-05-16): форматирует итоговую сумму колонки за весь
   * период. Возвращает null когда сумма недоступна (дата / текст / флаг /
   * stats не пришли) - UI покажет «-».
   *
   * @param {any} col
   * @returns {{ value: string, unit: string } | null}
   */
  function formatVolume(col) {
    if (!col?.stats || typeof col.stats.sum !== 'number') return null;
    const rawKind = String(col.kind ?? '').toLowerCase();
    const isNumeric = rawKind.includes('int') || rawKind.includes('float') || rawKind === 'number' || rawKind === 'numeric';
    if (!isNumeric) return null;
    const sum = col.stats.sum;
    // Округление до целого - бренд-менеджер не нуждается в копейках.
    const rounded = Math.round(sum);
    const formatted = new Intl.NumberFormat('ru-RU').format(rounded);
    return { value: formatted, unit: detectVolumeUnit(col.name) };
  }

  /**
   * Canonical role → UI vocabulary mapping. Backend column-roles.js uses
   * 6 roles (kpi/media/control/date/unused/unknown); UI displays 5
   * (kpi/media/control/date/excluded). unused/unknown/null → excluded.
   *
   * @param {string} colName
   * @returns {string}
   */
  function effectiveRole(colName) {
    if (overrides[colName] !== undefined) return overrides[colName];
    const col = columns.find((/** @type {any} */ c) => c.name === colName);
    const canonical = col?.role;
    if (canonical === 'unused' || canonical === 'unknown' || canonical == null) {
      return 'excluded';
    }
    // Защита от unknown role values (defensive - production выдаёт только canonical 6).
    if (!ROLES.includes(/** @type {any} */ (canonical))) {
      return 'excluded';
    }
    return canonical;
  }

  /** @param {string} colName @param {string} newRole */
  function setOverride(colName, newRole) {
    // F-002 (pilot 2026-05-18): KPI mutual exclusion — radio-like behavior.
    // When user assigns role='kpi' to column B while column A already has
    // role='kpi', auto-reset A to its predicted (prop) role or 'excluded'.
    if (newRole === 'kpi') {
      /** @type {Record<string, string>} */
      const next = { ...overrides, [colName]: newRole };
      for (const col of columns) {
        if (col.name === colName) continue;
        const currentRole = overrides[col.name] !== undefined ? overrides[col.name] : (col.role ?? 'excluded');
        const canonicalRole = (currentRole === 'unused' || currentRole === 'unknown' || currentRole == null)
          ? 'excluded'
          : currentRole;
        if (canonicalRole === 'kpi') {
          // Reset displaced KPI column to its original predicted role or 'excluded'.
          const predicted = (col.role === 'unused' || col.role === 'unknown' || col.role == null)
            ? 'excluded'
            : col.role;
          // If predicted role is also 'kpi' (backend assigned both) → fall back to 'excluded'.
          next[col.name] = (predicted === 'kpi') ? 'excluded' : predicted;
          onRoleChange?.(col.name, next[col.name]);
        }
      }
      overrides = next;
    } else {
      overrides = { ...overrides, [colName]: newRole };
    }
    // v1.3.2: real-time sync с validateData → InsightsPanel + recommendations
    // reactively recompute. Parent (ValidateStepV13) implements onRoleChange.
    onRoleChange?.(colName, newRole);
  }

  /** M-01 / 4i (пилот 2026-05-16): bulk recommendation actions.
   *  skippedRecommendations - Set of column names that user chose to ignore.
   *  flashingRows - Set of column names currently showing row-flash animation.
   */
  /** @type {Set<string>} */
  let skippedRecommendations = $state(new Set());
  /** @type {Set<string>} */
  let flashingRows = $state(new Set());

  /**
   * Pending recommendations = columns with 'exclude' recommendation that:
   * - are not yet set to excluded role (effectiveRole !== 'excluded')
   * - are not in skippedRecommendations
   * "keep"/"review" recommendations are not actionable via bulk-apply.
   */
  const pendingRecommendations = $derived.by(() => {
    return columns.filter((/** @type {any} */ col) => {
      if (skippedRecommendations.has(col.name)) return false;
      const reco = recommendationFor(col);
      return reco.status === 'exclude' && effectiveRole(col.name) !== 'excluded';
    });
  });

  const pendingRecommendationsCount = $derived(pendingRecommendations.length);

  /**
   * Apply all pending «Исключить» recommendations:
   * - For each pending column: set override to 'excluded'
   * - Trigger row-flash animation for each affected row
   */
  function applyAllRecommendations() {
    const toApply = [...pendingRecommendations];
    for (let i = 0; i < toApply.length; i++) {
      const col = toApply[i];
      setOverride(col.name, 'excluded');
      // Stagger row-flash animation
      const delay = i * 60;
      setTimeout(() => {
        flashingRows = new Set([...flashingRows, col.name]);
        setTimeout(() => {
          const next = new Set(flashingRows);
          next.delete(col.name);
          flashingRows = next;
        }, 620);
      }, delay);
    }
  }

  /**
   * Skip all pending recommendations (mark as seen, no role change).
   */
  function skipAllRecommendations() {
    const names = pendingRecommendations.map((/** @type {any} */ col) => col.name);
    skippedRecommendations = new Set([...skippedRecommendations, ...names]);
  }

  /** v2.1.0 п.5.1: pulse-confirm animation state.
   *  When true - button enters confirming state (pulse + check icon).
   *  After CONFIRM_DELAY ms, onConfirm is called and parent transitions.
   *  prefers-reduced-motion guard: global app.css collapses animation to
   *  0.01ms, so onConfirm fires effectively immediately. */
  let confirming = $state(false);
  const CONFIRM_DELAY = 420;

  function handleConfirm() {
    if (confirming) return; // prevent double-click
    confirming = true;
    /** @type {Record<string, string>} */
    const mapping = {};
    for (const col of columns) {
      mapping[col.name] = effectiveRole(col.name);
    }
    setTimeout(() => {
      onConfirm?.(mapping);
      // confirming reset is not needed - parent unmounts this component.
    }, CONFIRM_DELAY);
  }

  const stats = $derived.by(() => {
    /** @type {Record<string, number>} */
    const counts = { kpi: 0, media: 0, control: 0, date: 0, excluded: 0 };
    for (const col of columns) {
      counts[effectiveRole(col.name)] = (counts[effectiveRole(col.name)] ?? 0) + 1;
    }
    return counts;
  });
</script>

<div class="column-mapper-confirm">
  <header class="card-header">
    <span class="kicker">ШАГ 1 ИЗ 4 · РОЛИ КОЛОНОК</span>
    <h2>Подтвердите роли</h2>
    <div class="sacred-lime" aria-hidden="true"></div>
    <p class="lead">Программа автоматически распознала роли колонок в данных. Проверьте таблицу - измените, если что-то определено неверно.</p>
  </header>

  <div class="summary-row">
    {#each ROLES as r}
      <div class="stat-pill tone-{ROLE_META[r].tone}" class:empty={stats[r] === 0}>
        <span class="dot" aria-hidden="true"></span>
        <span class="stat-label">{ROLE_META[r].label}</span>
        <span class="stat-value">{stats[r]}</span>
      </div>
    {/each}
  </div>

  {#if stats.kpi === 0}
    <div class="attention-banner" role="alert">
      <span class="attention-mark" aria-hidden="true"></span>
      <div class="attention-body">
        <strong>Целевая метрика не определена.</strong>
        Выберите её в таблице ниже - модель не сможет работать без целевого KPI.
      </div>
    </div>
  {/if}
  {#if stats.media === 0}
    <div class="attention-banner" role="alert">
      <span class="attention-mark" aria-hidden="true"></span>
      <div class="attention-body">
        <strong>Медиа-каналы не обнаружены.</strong>
        Без каналов модель не сможет построить декомпозицию.
      </div>
    </div>
  {/if}

  {#if pendingRecommendationsCount > 0}
    <div class="bulk-actions" role="region" aria-label="Массовое применение рекомендаций">
      <span class="bulk-label">
        Есть рекомендации к исключению
      </span>
      <button
        type="button"
        class="bulk-apply-btn"
        onclick={applyAllRecommendations}
        aria-label="Применить все рекомендации по исключению колонок ({pendingRecommendationsCount} шт.)"
      >
        Применить все рекомендации ({pendingRecommendationsCount})
      </button>
      <button
        type="button"
        class="bulk-skip-btn"
        onclick={skipAllRecommendations}
        aria-label="Пропустить все рекомендации"
      >
        Пропустить все
      </button>
    </div>
  {/if}

  <div class="table-wrapper">
    <table>
      <thead>
        <tr>
          <th scope="col" class="th-name">Колонка</th>
          <th scope="col" class="th-volume">
            Объём за период
            <span class="help-icon" title={VOLUME_HEADER_HELP} aria-label="Что значит объём за период">?</span>
          </th>
          <th scope="col" class="th-kind">
            Тип данных
            <span class="help-icon" title={KIND_HEADER_HELP} aria-label="Что значат типы данных">?</span>
          </th>
          <th scope="col" class="th-role">
            Роль в модели
            <span class="help-icon" title={ROLE_HEADER_HELP} aria-label="Что значат роли">?</span>
          </th>
          <th scope="col" class="th-reco">
            Рекомендация
            <span class="help-icon" title={RECO_HEADER_HELP} aria-label="Что значат рекомендации">?</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {#each columns as col (col.name)}
          {@const role = effectiveRole(col.name)}
          {@const reco = recommendationFor(col)}
          {@const volume = formatVolume(col)}
          <tr class="role-{role}" class:row-flash={flashingRows.has(col.name)}>
            <td class="col-name">{col.name}</td>
            <td class="col-volume">
              {#if volume}
                <span class="volume-value">{volume.value}</span>
                {#if volume.unit}
                  <span class="volume-unit">{volume.unit}</span>
                {/if}
              {:else}
                <span class="volume-empty" aria-label="Объём не применим">-</span>
              {/if}
            </td>
            <td class="col-kind" title={col.kind ?? ''}>
              <span class="kind-label">{humanizeKind(col.kind)}</span>
              {#if col.stats}
                {@const zeros = Number(col.stats.zeros_pct ?? 0)}
                {@const missing = Number(col.stats.missing_pct ?? 0)}
                <span class="stat-badges">
                  {#if zeros >= 50}
                    <span class="stat-badge tone-{zeros > 80 ? 'danger' : 'warn'}"
                      title="Доля нулевых значений: {zeros.toFixed(0)}%. {zeros > 80 ? 'Канал практически неактивен - почти всегда исключают.' : 'Существенная разреженность данных - модель может оценить вклад с большой неопределённостью.'}">
                      {Math.round(zeros)}% нулей
                    </span>
                  {:else if zeros >= 30}
                    <span class="stat-badge tone-info" title="Доля нулевых значений: {zeros.toFixed(1)}%. Умеренная разреженность - модель справится, но обратите внимание.">
                      {Math.round(zeros)}% нулей
                    </span>
                  {/if}
                  {#if missing >= 5}
                    <span class="stat-badge tone-{missing > 20 ? 'warn' : 'neutral'}"
                      title="Доля пропусков (NaN): {missing.toFixed(1)}%. {missing > 20 ? 'Много пропусков - модель потеряет периоды.' : 'Небольшое число пропусков, не критично.'}">
                      {Math.round(missing)}% пусто
                    </span>
                  {/if}
                </span>
              {/if}
            </td>
            <td class="col-role">
              <div class="role-cell">
                <span class="role-dot tone-{ROLE_META[role].tone}" aria-hidden="true"></span>
                <select
                  value={role}
                  aria-label="Роль колонки {col.name}"
                  onchange={(e) => setOverride(col.name, /** @type {HTMLSelectElement} */ (e.target).value)}
                >
                  {#each ROLES as r}
                    <option value={r}>{ROLE_META[r].label}</option>
                  {/each}
                </select>
              </div>
            </td>
            <td class="col-reco">
              <span class="reco-badge tone-{reco.tone}" title={reco.reason}>
                <span class="reco-dot" aria-hidden="true"></span>
                {reco.label}
              </span>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <footer class="card-footer">
    {#if blockedReason}
      <!-- v1.3.2: hard-block при ratio <2:1 - кнопка disabled + reason text. -->
      <div class="block-banner" role="alert">
        <span class="block-mark" aria-hidden="true"></span>
        <div class="block-body">
          <strong>Нельзя продолжить.</strong> {blockedReason}
        </div>
      </div>
    {:else}
      <p class="footer-note">
        Все изменения применяются после подтверждения. Дальше - выбор целевого KPI.
      </p>
    {/if}
    <button
      type="button"
      class="btn-confirm"
      class:btn-confirm--confirming={confirming}
      onclick={handleConfirm}
      disabled={!!blockedReason || confirming}
      aria-label={confirming ? 'Роли подтверждены' : 'Подтвердить роли'}
      title={blockedReason || ''}
    >
      {#if confirming}
        <!-- v2.1.0 п.5.1: check-icon fade-in on confirm (lucide Check SVG inline) -->
        <svg
          class="btn-check-icon"
          aria-hidden="true"
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <polyline points="20 6 9 17 4 12" />
        </svg>
        Подтверждено
      {:else}
        Подтвердить роли
        <span class="btn-arrow" aria-hidden="true">→</span>
      {/if}
    </button>
  </footer>
</div>

<style>
  .column-mapper-confirm {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 28px 32px;
    max-width: 1100px;
    margin: 0 auto;
    width: 100%;
    color: var(--text-primary);
  }

  /* ─── Header (Aurora deliverable kicker + h2 + lime) ─── */
  .card-header {
    display: flex;
    flex-direction: column;
    gap: 6px;
    /* v2.1.0 (пилот 2026-05-16): расширено с 64ch чтобы lead-параграф
       помещался в одну строку без переноса. */
    max-width: 110ch;
  }
  .kicker {
    font-family: var(--font-sans, system-ui), sans-serif;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    color: var(--gold, #c9a449);
    text-transform: uppercase;
  }
  .card-header h2 {
    margin: 0;
    font-family: var(--font-serif, Georgia), serif;
    font-size: 24px;
    font-weight: 400;
    line-height: 1.2;
    letter-spacing: -0.01em;
    color: var(--text-primary);
  }
  .sacred-lime {
    width: 48px;
    height: 2px;
    background: var(--lime, #b8e043);
    margin-top: 4px;
    margin-bottom: 4px;
  }
  .lead {
    margin: 0;
    font-size: 13px;
    line-height: 1.55;
    color: var(--text-secondary);
  }

  /* ─── Summary stat pills (no emoji, color-coded dots) ─── */
  .summary-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }
  .stat-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px 6px 10px;
    border-radius: 4px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    font-size: 11px;
    line-height: 1;
    transition: opacity 0.15s, border-color 0.15s;
  }
  .stat-pill.empty {
    opacity: 0.45;
  }
  .stat-pill .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .stat-pill.tone-gold .dot    { background: var(--gold, #c9a449); }
  .stat-pill.tone-accent .dot  { background: var(--accent-primary, #6366f1); }
  .stat-pill.tone-neutral .dot { background: var(--text-secondary, #94a3b8); }
  .stat-pill.tone-mono .dot    { background: var(--text-muted, #64748b); }
  .stat-pill.tone-muted .dot   { background: rgba(148,163,184,0.4); }
  .stat-pill .stat-label {
    color: var(--text-secondary);
    letter-spacing: 0.02em;
  }
  .stat-pill .stat-value {
    color: var(--text-primary);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    margin-left: 2px;
  }

  /* ─── Attention banner (replaces warning emoji) ─── */
  .attention-banner {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    padding: 12px 14px;
    border-left: 2px solid var(--gold, #c9a449);
    background: color-mix(in srgb, var(--gold, #c9a449) 6%, transparent);
    border-radius: 0 4px 4px 0;
  }
  .attention-mark {
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: var(--gold, #c9a449);
    margin-top: 7px;
    flex-shrink: 0;
  }
  .attention-body {
    flex: 1;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-primary);
  }
  .attention-body strong {
    font-weight: 600;
    margin-right: 4px;
  }

  /* ─── Table (premium tier-1, hairline borders) ─── */
  .table-wrapper {
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  thead th {
    text-align: left;
    padding: 10px 0 8px;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--text-muted, #64748b);
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  /* v1.3.2: help-icon в th headers - premium tier-1 unobtrusive «?» tooltip */
  thead th .help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    margin-left: 6px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--text-muted, #64748b) 16%, transparent);
    color: var(--text-secondary, #94a3b8);
    font-size: 9px;
    font-weight: 700;
    cursor: help;
    user-select: none;
    text-transform: none;
    letter-spacing: 0;
    vertical-align: middle;
    transition: background 0.15s, color 0.15s;
  }
  thead th .help-icon:hover {
    background: color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
    color: var(--gold, #c9a449);
  }

  /* v1.3.2: Рекомендация column - color-coded badge с dot + reason tooltip. */
  .col-reco {
    font-size: 12px;
  }
  .reco-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 4px 10px;
    border-radius: 3px;
    border: 1px solid transparent;
    cursor: help;
    font-size: 11.5px;
    line-height: 1;
    user-select: none;
    transition: background 0.15s, border-color 0.15s;
  }
  .reco-badge .reco-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  /* Tone variants */
  .reco-badge.tone-ok {
    background: color-mix(in srgb, var(--success, #4ade80) 8%, transparent);
    border-color: color-mix(in srgb, var(--success, #4ade80) 22%, transparent);
    color: var(--success, #4ade80);
  }
  .reco-badge.tone-ok .reco-dot { background: var(--success, #4ade80); }

  .reco-badge.tone-warn {
    background: color-mix(in srgb, var(--gold, #c9a449) 10%, transparent);
    border-color: color-mix(in srgb, var(--gold, #c9a449) 28%, transparent);
    color: var(--gold, #c9a449);
  }
  .reco-badge.tone-warn .reco-dot { background: var(--gold, #c9a449); }

  .reco-badge.tone-danger {
    background: color-mix(in srgb, var(--danger, #f87171) 10%, transparent);
    border-color: color-mix(in srgb, var(--danger, #f87171) 28%, transparent);
    color: var(--danger, #f87171);
  }
  .reco-badge.tone-danger .reco-dot { background: var(--danger, #f87171); }

  .reco-badge.tone-neutral {
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
    border-color: var(--border-subtle, rgba(255,255,255,0.08));
    color: var(--text-muted, #64748b);
  }
  .reco-badge.tone-neutral .reco-dot { background: var(--text-muted, #64748b); }

  .reco-badge:hover {
    background-color: color-mix(in srgb, currentColor 18%, transparent);
  }
  /* v2.1.0 (пилот 2026-05-16): добавлен th-volume; ширины перераспределены. */
  .th-name   { width: 22%; }
  .th-volume { width: 18%; text-align: right; padding-right: 16px; }
  .th-kind   { width: 14%; }
  .th-role   { width: 28%; }
  .th-reco   { width: 18%; }

  tbody td {
    padding: 11px 0;
    border-bottom: 1px solid var(--border-faint, rgba(255,255,255,0.03));
    font-size: 13px;
    vertical-align: middle;
  }
  tbody tr:last-child td {
    border-bottom: none;
  }

  .col-name {
    font-family: var(--font-mono, 'JetBrains Mono', Consolas, monospace);
    font-size: 12.5px;
    font-weight: 500;
    color: var(--text-primary);
  }

  /* v2.1.0 (пилот 2026-05-16): «Объём за период» - правое выравнивание,
     tabular-nums чтобы цифры висели колонкой, единица серым в нижнем
     регистре. Пустое значение (даты / текст) - тонкий em-dash центром. */
  .col-volume {
    text-align: right;
    padding-right: 16px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: var(--text-primary);
  }
  .volume-value {
    font-family: var(--font-mono, 'JetBrains Mono', Consolas, monospace);
    font-size: 12.5px;
    font-weight: 500;
  }
  .volume-unit {
    margin-left: 5px;
    font-size: 11px;
    color: var(--text-muted, #64748b);
    font-weight: 400;
  }
  .volume-empty {
    color: var(--text-muted, #64748b);
    font-size: 12px;
    opacity: 0.5;
  }
  .col-kind {
    font-size: 11px;
    color: var(--text-muted);
    letter-spacing: 0.02em;
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: flex-start;
  }
  .col-kind .kind-label { text-transform: lowercase; }
  /* v1.3.2: stat-badges под kind label - zeros%/missing% per column. */
  .stat-badges {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }
  .stat-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    line-height: 1;
    font-variant-numeric: tabular-nums;
    border: 1px solid transparent;
    text-transform: none;
    cursor: help;
    white-space: nowrap;
  }
  .stat-badge.tone-danger {
    background: color-mix(in srgb, var(--danger, #f87171) 12%, transparent);
    border-color: color-mix(in srgb, var(--danger, #f87171) 30%, transparent);
    color: var(--danger, #f87171);
  }
  .stat-badge.tone-warn {
    background: color-mix(in srgb, var(--gold, #c9a449) 12%, transparent);
    border-color: color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
    color: var(--gold, #c9a449);
  }
  .stat-badge.tone-info {
    background: color-mix(in srgb, var(--accent-primary, #6366f1) 10%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary, #6366f1) 25%, transparent);
    color: var(--accent-primary, #6366f1);
  }
  .stat-badge.tone-neutral {
    background: var(--bg-surface-quiet, rgba(255,255,255,0.04));
    border-color: var(--border-subtle, rgba(255,255,255,0.08));
    color: var(--text-muted, #64748b);
  }

  /* Row tint tied к role (subtle, premium - не chrome-bright) */
  tr.role-kpi      { background: color-mix(in srgb, var(--gold, #c9a449) 4%, transparent); }
  tr.role-media    { background: color-mix(in srgb, var(--accent-primary, #6366f1) 3%, transparent); }
  tr.role-excluded { opacity: 0.5; }

  /* Role cell - dot + native select */
  .role-cell {
    display: inline-flex;
    align-items: center;
    gap: 10px;
  }
  .role-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .role-dot.tone-gold    { background: var(--gold, #c9a449); }
  .role-dot.tone-accent  { background: var(--accent-primary, #6366f1); }
  .role-dot.tone-neutral { background: var(--text-secondary, #94a3b8); }
  .role-dot.tone-mono    { background: var(--text-muted, #64748b); }
  .role-dot.tone-muted   { background: rgba(148,163,184,0.4); }

  select {
    /* v1.3.2: color-scheme: dark - подсказка Webview2 рендерить native
       option popup в dark тон. Без этого WIN browser показывает light
       popup → текст ролей сливается с background на тёмной теме. */
    color-scheme: dark;
    appearance: none;
    padding: 6px 26px 6px 10px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 3px;
    background: var(--bg-surface-quiet, rgba(255,255,255,0.03));
    color: var(--text-primary);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    min-width: 200px;
    transition: border-color 0.15s, background 0.15s;
    background-image:
      linear-gradient(45deg, transparent 50%, var(--text-muted) 50%),
      linear-gradient(135deg, var(--text-muted) 50%, transparent 50%);
    background-position:
      calc(100% - 13px) 50%,
      calc(100% - 8px) 50%;
    background-size: 5px 5px, 5px 5px;
    background-repeat: no-repeat;
  }
  /* Style option items in supporting browsers (Chromium 100+ honors на native popup) */
  select option {
    background: var(--bg-card, #0f172a);
    color: var(--text-primary, #e2e8f0);
    padding: 6px 10px;
  }
  select option:checked,
  select option:hover {
    background: color-mix(in srgb, var(--gold, #c9a449) 20%, var(--bg-card, #0f172a));
    color: var(--text-primary);
  }
  select:hover {
    border-color: var(--gold, #c9a449);
    background-color: color-mix(in srgb, var(--gold, #c9a449) 4%, transparent);
  }
  select:focus {
    outline: none;
    border-color: var(--gold, #c9a449);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--gold, #c9a449) 20%, transparent);
  }

  /* ─── Footer (premium CTA) ─── */
  .card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
    padding-top: 8px;
  }
  .footer-note {
    margin: 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-muted);
    font-style: italic;
    flex: 1;
    min-width: 200px;
  }
  .btn-confirm {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 11px 22px;
    border-radius: 3px;
    background: var(--text-primary);
    color: var(--bg-card, #0f172a);
    border: none;
    font: inherit;
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: 0.04em;
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
  }
  /* v1.3.2: hard-block banner - red attention для ratio <2:1 case. */
  .block-banner {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    padding: 12px 14px;
    border-left: 2px solid var(--danger, #f87171);
    background: color-mix(in srgb, var(--danger, #f87171) 7%, transparent);
    border-radius: 0 4px 4px 0;
    flex: 1;
    min-width: 240px;
  }
  .block-mark {
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: var(--danger, #f87171);
    margin-top: 7px;
    flex-shrink: 0;
  }
  .block-body {
    flex: 1;
    font-size: 12.5px;
    line-height: 1.55;
    color: var(--text-primary);
  }
  .block-body strong {
    font-weight: 600;
    margin-right: 4px;
    color: var(--danger, #f87171);
  }
  .btn-confirm:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    pointer-events: none;
  }
  .btn-confirm:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
  }
  .btn-confirm .btn-arrow {
    font-family: var(--font-serif, Georgia), serif;
    font-size: 14px;
    transition: transform 0.15s;
  }
  .btn-confirm:hover .btn-arrow {
    transform: translateX(3px);
  }

  /* v2.1.0 п.5.1: pulse-confirm animation.
     Applied only under no-preference; global app.css prefers-reduced-motion
     rule collapses all animations to 0.01ms for motion-sensitive users. */
  @media (prefers-reduced-motion: no-preference) {
    @keyframes pulse-once {
      0%   { box-shadow: 0 0 0 0 color-mix(in srgb, var(--success, #10B981) 55%, transparent); }
      45%  { box-shadow: 0 0 0 8px color-mix(in srgb, var(--success, #10B981) 0%, transparent); }
      100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--success, #10B981) 0%, transparent); }
    }
    @keyframes check-fade-in {
      from { opacity: 0; transform: scale(0.7) rotate(-10deg); }
      to   { opacity: 1; transform: scale(1) rotate(0deg); }
    }

    .btn-confirm--confirming {
      background: var(--success, #10B981);
      color: var(--bg-card, #0f172a);
      animation: pulse-once 0.42s ease-out forwards;
    }
    .btn-check-icon {
      animation: check-fade-in 0.28s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
    }
  }

  /* Non-animated state for reduced-motion - just show success colour instantly. */
  @media (prefers-reduced-motion: reduce) {
    .btn-confirm--confirming {
      background: var(--success, #10B981);
      color: var(--bg-card, #0f172a);
    }
  }

  /* ─── M-01/4i: Bulk actions panel ─── */
  .bulk-actions {
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 12px 16px;
    background: color-mix(in srgb, var(--accent-primary, #6366f1) 6%, transparent);
    border-radius: 8px;
    margin-bottom: 4px;
  }
  .bulk-label {
    flex: 1;
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.4;
  }
  .bulk-apply-btn {
    padding: 8px 16px;
    background: var(--accent-primary, #6366f1);
    color: #fff;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
    white-space: nowrap;
  }
  .bulk-apply-btn:hover { opacity: 0.9; }
  .bulk-skip-btn {
    padding: 8px 16px;
    background: transparent;
    color: var(--text-secondary, #94a3b8);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
    white-space: nowrap;
  }
  .bulk-skip-btn:hover {
    color: var(--text-primary);
    border-color: var(--text-secondary, #94a3b8);
  }

  /* ─── M-01/4i: Row flash animation (applied on bulk-apply) ─── */
  @keyframes row-flash {
    0%   { background: color-mix(in srgb, var(--success, #4ade80) 0%, transparent); }
    40%  { background: color-mix(in srgb, var(--success, #4ade80) 18%, transparent); }
    100% { background: color-mix(in srgb, var(--success, #4ade80) 0%, transparent); }
  }
  .row-flash {
    animation: row-flash 620ms ease-out;
  }
  @media (prefers-reduced-motion: reduce) {
    .row-flash { animation: none; }
  }
</style>
