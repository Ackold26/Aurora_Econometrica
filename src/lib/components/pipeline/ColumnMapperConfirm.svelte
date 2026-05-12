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
  function recommendationFor(col) {
    if (!col) {
      return { status: 'review', label: 'Проверить', reason: 'Нет данных по колонке.', tone: 'neutral' };
    }
    const role = effectiveRole(col.name);
    const findings = findingsFor(col.name);

    // 0. v1.3.2: insights-driven exclude - top priority. Если same column
    //    flagged by validateInsights в InsightsPanel - show same reason.
    //    Skip когда юзер уже исключил (role='excluded') - нечего advise.
    if (insightExcludeMap?.[col.name] && role !== 'excluded') {
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
      const tone = severeTypes.has(String(w?.type ?? '')) ? 'danger' : 'warn';
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

    // 6. Default: passes all checks.
    return { status: 'keep', label: 'Оставить', reason: 'Колонка подходит для выбранной роли. Никаких действий не требуется.', tone: 'ok' };
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
    overrides = { ...overrides, [colName]: newRole };
    // v1.3.2: real-time sync с validateData → InsightsPanel + recommendations
    // reactively recompute. Parent (ValidateStepV13) implements onRoleChange.
    onRoleChange?.(colName, newRole);
  }

  function handleConfirm() {
    /** @type {Record<string, string>} */
    const mapping = {};
    for (const col of columns) {
      mapping[col.name] = effectiveRole(col.name);
    }
    onConfirm?.(mapping);
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
    <p class="lead">Программа автоматически распознала роли колонок в данных.</p>
    <p class="lead">Проверьте таблицу - измените, если что-то определено неверно.</p>
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

  <div class="table-wrapper">
    <table>
      <thead>
        <tr>
          <th scope="col" class="th-name">Колонка</th>
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
          <tr class="role-{role}">
            <td class="col-name">{col.name}</td>
            <td class="col-kind" title={col.kind ?? ''}>
              <span class="kind-label">{humanizeKind(col.kind)}</span>
              {#if col.stats}
                {@const zeros = Number(col.stats.zeros_pct ?? 0)}
                {@const missing = Number(col.stats.missing_pct ?? 0)}
                <span class="stat-badges">
                  {#if zeros >= 50}
                    <span class="stat-badge tone-{zeros > 80 ? 'danger' : 'warn'}"
                      title="Доля нулевых значений: {zeros.toFixed(0)}%. {zeros > 80 ? 'Канал практически неактивен — почти всегда исключают.' : 'Существенная разреженность данных — модель может оценить вклад с большой неопределённостью.'}">
                      {Math.round(zeros)}% нулей
                    </span>
                  {:else if zeros >= 30}
                    <span class="stat-badge tone-info" title="Доля нулевых значений: {zeros.toFixed(1)}%. Умеренная разреженность — модель справится, но обратите внимание.">
                      {Math.round(zeros)}% нулей
                    </span>
                  {/if}
                  {#if missing >= 5}
                    <span class="stat-badge tone-{missing > 20 ? 'warn' : 'neutral'}"
                      title="Доля пропусков (NaN): {missing.toFixed(1)}%. {missing > 20 ? 'Много пропусков — модель потеряет периоды.' : 'Небольшое число пропусков, не критично.'}">
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
      <!-- v1.3.2: hard-block при ratio <2:1 — кнопка disabled + reason text. -->
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
      onclick={handleConfirm}
      disabled={!!blockedReason}
      title={blockedReason || ''}
    >
      Подтвердить роли
      <span class="btn-arrow" aria-hidden="true">→</span>
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
    max-width: 64ch;
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
  .th-name { width: 30%; }
  .th-kind { width: 15%; }
  .th-role { width: 32%; }
  .th-reco { width: 23%; }

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
  /* v1.3.2: stat-badges под kind label — zeros%/missing% per column. */
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
  /* v1.3.2: hard-block banner — red attention для ratio <2:1 case. */
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
</style>
