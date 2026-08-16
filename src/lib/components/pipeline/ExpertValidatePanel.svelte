<script>
  /**
   * Expert-only panel for ValidateStep.
   * Adds numeric econometric metrics on top of the main view:
   *   - VIF (Variance Inflation Factor) table - quantitative multicollinearity
   *   - Detailed per-column statistics (missing%, zeros%, mean, std)
   * Correlation heatmap is shown in the main view - no duplication here.
   * @component ExpertValidatePanel
   */
  import { validateData } from '$lib/project-state.js';
  import { fmtNum, fmtPct } from '$lib/fmt.js';
  import { X } from 'lucide-svelte';
  import { roleIcons } from '$lib/role-icons.js';

  const result = $derived($validateData?.result);

  /** @type {Array<{name: string, vif: number}>} */
  const vifTable = $derived.by(() => {
    if (!result?.columns) return [];
    return result.columns
      .filter(/** @param {any} c */ (c) => c.role === 'media' && c.stats?.vif != null)
      .map(/** @param {any} c */ (c) => ({ name: c.name, vif: c.stats.vif }))
      .sort(/** @param {any} a @param {any} b */ (a, b) => b.vif - a.vif);
  });

  const dataStats = $derived.by(() => {
    if (!result?.columns) return [];
    return result.columns.map(/** @param {any} c */ (c) => ({
      name: c.name,
      role: c.role,
      dtype: c.dtype ?? '-',
      missing: fmtPct(c.stats?.missing_pct ?? 0),
      zeros: fmtPct(c.stats?.zeros_pct ?? 0),
      mean: fmtNum(c.stats?.mean),
      std: fmtNum(c.stats?.std),
    }));
  });

  const unknownCount = $derived(dataStats.filter(/** @param {any} r */ r => !r.role || r.role === 'unknown').length);

  // Если ни VIF, ни stats не посчитаны (objective ещё выбирается / validate не запускался) -
  // panel пустая обёртка с заголовком "Экспертный режим" сбивает с толку. Скрываем.
  const hasContent = $derived(vifTable.length > 0 || dataStats.length > 0);

  // ── Inline role editor ──
  /** @type {string|null} */
  let editingColumn = $state(null);

  // v2.1.0 (rc2 retry): унификация терминов с ColumnMapperConfirm.
  // Раньше использовались короткие термины (Медиа / KPI / Внешние /
  // Исключить), теперь полные общепринятые из MMM (Nielsen / Kantar).
  // Иконки ролей — единый источник $lib/role-icons.js (roleIcons[id]).
  const ROLE_OPTIONS = [
    { id: 'media',   label: 'Медиа-канал' },
    { id: 'kpi',     label: 'Целевая метрика' },
    { id: 'control', label: 'Контрольная' },
    { id: 'date',    label: 'Дата' },
    { id: 'unused',  label: 'Не использовать' },
  ];

  /** @param {string} colName @param {string} newRole */
  function assignRole(colName, newRole) {
    const val = $validateData;
    if (!val?.result?.columns) return;
    const updated = {
      ...val,
      result: {
        ...val.result,
        columns: val.result.columns.map(/** @param {any} c */ c =>
          c.name === colName ? { ...c, role: newRole } : c
        ),
      },
    };
    validateData.set(updated);
    editingColumn = null;
  }

  /** @param {string} role */
  function roleLabel(role) {
    if (!role || role === 'unknown') return '?';
    const opt = ROLE_OPTIONS.find(o => o.id === role);
    // Только текст; иконка роли рендерится отдельным компонентом (roleIcons) в template.
    return opt ? opt.label : role;
  }
</script>

{#if hasContent}
<div class="expert-panel">
  <!--
    Корреляционная матрица уже показывается в основном режиме (ValidateStep) -
    в экспертном дублировать её нет смысла. Эксперт-секция добавляет то,
    чего нет в main: численный VIF + детальную статистику столбцов.
  -->

  {#if vifTable.length > 0}
    <div class="section-title">VIF (Variance Inflation Factor)</div>
    <table class="vif-table">
      <thead>
        <tr>
          <th>
            Канал
            <span class="help-icon" title="Название медиа или контрольной переменной, для которой рассчитан VIF.">?</span>
          </th>
          <th>
            VIF
            <span class="help-icon" title="Variance Inflation Factor - показывает во сколько раз дисперсия оценки коэффициента раздувается из-за корреляции этого канала с остальными. VIF = 1 / (1 − R²), где R² - объяснимость канала остальными. VIF ≤ 5 - норма, 5-10 - умеренная мультиколлинеарность, &gt;10 - критическая (канал почти полностью предсказуем из остальных, его ROI в модели будет нестабильным).">?</span>
          </th>
          <th>
            Статус
            <span class="help-icon" title="Интерпретация VIF: «Норма» (≤5) - канал вносит уникальный сигнал. «Умеренная» (5-10) - результат усреднится с другими каналами. «Мультиколлинеарность» (&gt;10) - модель не сможет разделить вклад этого канала от остальных, рекомендуется исключить или объединить.">?</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {#each vifTable as row}
          <tr class:high={row.vif > 10} class:medium={row.vif > 5 && row.vif <= 10}>
            <td>{row.name}</td>
            <td class="mono">{fmtNum(row.vif, { decimals: 1 })}</td>
            <td>{row.vif > 10 ? 'Мультиколлинеарность' : row.vif > 5 ? 'Умеренная' : 'Норма'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if dataStats.length > 0}
    <div class="section-title">
      Статистика столбцов
      {#if unknownCount > 0}
        <span class="hint-badge">Нажмите «?» чтобы назначить роль ({unknownCount} не определено)</span>
      {/if}
    </div>
    <div class="stats-scroll">
      <table class="stats-table">
        <thead>
          <tr>
            <th>Столбец</th>
            <th>Роль</th>
            <th>
              Тип
              <span class="help-icon" title="Тип данных столбца: float64 (числа с дробной частью - деньги, проценты), int64 (целые числа - количество), object (текст или дата).">?</span>
            </th>
            <th>
              Пропуски %
              <span class="help-icon" title="Доля строк с пропущенным значением (NaN). При обучении пропуски считаются нулём, то есть «активности не было» – восстановления значений в расчёте нет. При &gt;20% столбец лучше исключить.">?</span>
            </th>
            <th>
              Нули %
              <span class="help-icon" title="Доля строк с нулём. Отличается от пропусков: ноль - это факт отсутствия активности (канал не работал), пропуск - отсутствие данных. Высокий % нулей сигнализирует о разреженном канале.">?</span>
            </th>
            <th>
              Среднее
              <span class="help-icon" title="Среднее арифметическое по столбцу. Для бюджетов - средние расходы за период; для показов - средняя аудитория.">?</span>
            </th>
            <th>
              Std
              <span class="help-icon" title="Стандартное отклонение - мера разброса значений вокруг среднего. Чем больше Std относительно Mean, тем сильнее колебания. Std/Mean = коэффициент вариации (CV).">?</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {#each dataStats as row}
            <tr class:excluded={row.role === 'unused'}>
              <td>{row.name}</td>
              <td class="role-cell">
                {#if editingColumn === row.name}
                  <div class="role-picker">
                    {#each ROLE_OPTIONS as opt}
                      {@const OptIcon = roleIcons[opt.id]}
                      <button
                        class="role-option"
                        class:active={row.role === opt.id}
                        onclick={() => assignRole(row.name, opt.id)}
                      >
                        {#if OptIcon}<OptIcon size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> {/if}{opt.label}
                      </button>
                    {/each}
                    <button class="role-option role-cancel" onclick={() => editingColumn = null} aria-label="Отмена"><X size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /></button>
                  </div>
                {:else}
                  {@const RowIcon = roleIcons[row.role]}
                  <button
                    class="role-badge"
                    class:unknown={!row.role || row.role === 'unknown'}
                    class:role-unused={row.role === 'unused'}
                    onclick={() => editingColumn = row.name}
                    title="Нажмите для изменения роли"
                  >
                    {#if RowIcon}<RowIcon size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> {/if}{roleLabel(row.role)}
                  </button>
                {/if}
              </td>
              <td class="mono">{row.dtype}</td>
              <td class="mono" class:warn={parseFloat(row.missing) > 5}>{row.missing}</td>
              <td class="mono" class:warn={parseFloat(row.zeros) > 80}>{row.zeros}</td>
              <td class="mono">{row.mean}</td>
              <td class="mono">{row.std}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
{/if}

<style>
  .expert-panel {
    display: flex; flex-direction: column; gap: 16px; margin-top: 24px;
    padding: 16px; border-radius: var(--radius-md, 10px);
    background: color-mix(in srgb, var(--danger) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--danger) 8%, transparent);
    position: relative;
  }
  .expert-panel::before {
    content: 'Экспертный режим';
    position: absolute;
    top: -8px;
    left: 12px;
    padding: 2px 8px;
    background: var(--bg-primary, #0C0C12);
    color: var(--danger);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border-radius: 4px;
  }
  .section-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: rgba(252,165,165,0.85); }
  .empty { font-size: 12px; color: var(--text-muted); }

  table { width: 100%; border-collapse: collapse; font-size: 11px; }
  th { text-align: left; padding: 6px 8px; color: var(--text-secondary, #94a3b8); border-bottom: 1px solid rgba(255,255,255,0.06); font-weight: 600; }
  td { padding: 5px 8px; color: var(--text-primary, #e2e8f0); border-bottom: 1px solid rgba(255,255,255,0.03); }
  .mono { font-family: monospace; }
  .warn { color: var(--warning, #d97706); }
  tr.high td { background: color-mix(in srgb, var(--danger) 6%, transparent); }
  tr.medium td { background: color-mix(in srgb, var(--warning) 4%, transparent); }
  .role-cell { position: relative; }
  .role-badge {
    font-size: 10px; font-weight: 500;
    padding: 2px 8px; border-radius: 4px;
    background: none; border: 1px solid transparent;
    color: var(--accent-primary, #3b82f6);
    cursor: pointer; transition: all 0.15s;
  }
  .role-badge:hover { border-color: var(--accent-primary, #3b82f6); background: color-mix(in srgb, var(--accent-primary) 8%, transparent); }
  .role-badge.unknown {
    color: var(--warning, #f59e0b);
    border: 1px dashed var(--warning, #f59e0b);
    padding: 2px 10px;
    animation: pulse-border 2s infinite;
  }
  .role-badge.role-unused { color: var(--text-muted, #64748b); opacity: 0.6; text-decoration: line-through; }
  @keyframes pulse-border { 0%,100% { border-color: color-mix(in srgb, var(--warning) 40%, transparent); } 50% { border-color: color-mix(in srgb, var(--warning) 90%, transparent); } }

  .role-picker {
    display: flex; flex-wrap: wrap; gap: 3px;
    position: absolute; left: 0; top: -2px; z-index: 30;
    background: var(--bg-surface-quiet, #1e2130);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.12));
    border-radius: 8px; padding: 4px; box-shadow: 0 6px 20px rgba(0,0,0,0.4);
    min-width: 180px;
  }
  .role-option {
    padding: 4px 8px; border: none; border-radius: 4px;
    background: none; color: var(--text-primary, #e2e8f0);
    font-size: 11px; cursor: pointer; transition: background 0.1s;
    white-space: nowrap;
  }
  .role-option:hover { background: rgba(255,255,255,0.08); }
  .role-option.active { background: color-mix(in srgb, var(--accent-primary) 15%, transparent); color: var(--accent-primary); }
  .role-cancel { color: var(--text-muted, #64748b); }

  tr.excluded td { opacity: 0.4; }

  .hint-badge {
    font-size: 10px; font-weight: 400; text-transform: none; letter-spacing: 0;
    color: var(--warning, #f59e0b);
    margin-left: 8px;
  }

  .stats-scroll { overflow-x: auto; }

  .help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 13px;
    height: 13px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--accent-primary) 20%, transparent);
    color: var(--accent-primary);
    font-size: 9px;
    font-weight: 700;
    margin-left: 4px;
    cursor: help;
    vertical-align: middle;
    line-height: 1;
  }
  .help-icon:hover {
    background: var(--accent-primary);
    color: #fff;
  }

  /* v2.1.0 п.5.6: static dashed border for unknown role badge */
  @media (prefers-reduced-motion: reduce) {
    .role-badge.unknown {
      border-color: var(--warning, #f59e0b);
    }
  }
</style>
