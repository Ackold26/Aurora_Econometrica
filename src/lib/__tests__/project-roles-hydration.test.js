/**
 * LOAD-1 (A): реконструкция ролей из project.json, когда validation.json
 * отсутствует (обученные проекты с data_file:null). Верифицируется на РЕАЛЬНЫХ
 * project.json + decomposition.json обученного проекта «Кагоцел РФ» (фикстуры в
 * fixtures/kagocel-load1/ — точная копия %APPDATA%/.../projects/<кагоцел>/).
 *
 * Это «existing-project» фикс целиком: весь путь applyProjectRolesToColumns →
 * hydrateRolesFromProjectIfEmpty → modelStaleStatus доказывается БЕЗ запуска
 * приложения (code-proof; GUI остаётся на одну финальную сверку).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
// Фикстуры — точная копия реального обученного проекта «Кагоцел РФ» из
// %APPDATA%/.../projects/<кагоцел>/ (project.json + results/decomposition.json),
// закоммичены рядом. JSON-импорт (resolveJsonModule) — без node:fs.
import kagocelProject from './fixtures/kagocel-load1/project.json';
import kagocelDecomp from './fixtures/kagocel-load1/decomposition.json';
import { applyProjectRolesToColumns, buildProjectUpdates } from '../column-roles.js';
import {
  activeProject,
  validateData,
  chosenKpiColumn,
  modelData,
  lastTrainedConfig,
  modelChannelEnabled,
  modelStaleStatus,
  hydrateRolesFromProjectIfEmpty,
  kpiType,
  kpiKind,
  valuePerCountUnit,
} from '../project-state.js';

beforeEach(() => {
  validateData.set(/** @type {any} */ ({ result: null, correlationMatrix: null, columnHistograms: null }));
  chosenKpiColumn.set(null);
  activeProject.set(null);
  modelData.set(/** @type {any} */ ({ diagnostics: null, channelParams: null, picklePath: null, normalization: null }));
  lastTrainedConfig.set(null);
  modelChannelEnabled.set({});
});

describe('applyProjectRolesToColumns — реальный project.json Кагоцела', () => {
  it('даёт 7 media + 4 control + 1 kpi + 16 excluded→unused', () => {
    const cols = applyProjectRolesToColumns(kagocelProject);
    /** @param {string} role */
    const byRole = (role) => cols.filter((c) => c.role === role);
    expect(byRole('kpi')).toHaveLength(1);
    expect(byRole('kpi')[0].name).toBe('Продажи в руб. бренд');
    expect(byRole('media')).toHaveLength(7);
    expect(byRole('control')).toHaveLength(4);
    expect(byRole('unused')).toHaveLength(16); // excluded_columns → 'unused'
    expect(cols).toHaveLength(1 + 7 + 4 + 16);
  });

  it('порядок: kpi → media → control → excluded (precedence)', () => {
    const cols = applyProjectRolesToColumns(kagocelProject);
    expect(cols[0]).toEqual({ name: 'Продажи в руб. бренд', role: 'kpi' });
    expect(cols[1].role).toBe('media');
    expect(cols[1 + 7].role).toBe('control');
    expect(cols[1 + 7 + 4].role).toBe('unused');
  });

  it('round-trip с buildProjectUpdates lossless', () => {
    const rebuilt = buildProjectUpdates(applyProjectRolesToColumns(kagocelProject));
    expect(rebuilt.kpi_column).toBe(kagocelProject.kpi_column);
    expect(rebuilt.media_columns).toEqual(kagocelProject.media_columns);
    expect(rebuilt.control_columns).toEqual(kagocelProject.control_columns);
    expect(rebuilt.excluded_columns).toEqual(kagocelProject.excluded_columns);
  });

  it('null / нет ролей → []', () => {
    expect(applyProjectRolesToColumns(null)).toEqual([]);
    expect(applyProjectRolesToColumns(undefined)).toEqual([]);
    expect(applyProjectRolesToColumns({})).toEqual([]);
    expect(applyProjectRolesToColumns({ kpi_column: null, media_columns: [], control_columns: [], excluded_columns: [] })).toEqual([]);
  });

  it('precedence: колонка в двух ролях попадает только в первую (kpi>media>control>excluded)', () => {
    const cols = applyProjectRolesToColumns({
      kpi_column: 'Sales',
      media_columns: ['Sales', 'TV'], // Sales дублируется как media — должен остаться kpi
      control_columns: ['TV'], // TV дублируется как control — остаётся media
      excluded_columns: ['TV'],
    });
    expect(cols).toEqual([
      { name: 'Sales', role: 'kpi' },
      { name: 'TV', role: 'media' },
    ]);
  });
});

describe('hydrateRolesFromProjectIfEmpty — реальные данные Кагоцела (без GUI)', () => {
  it('заполняет пустой validateData ролями + chosenKpiColumn + nObs=31 из decomposition', async () => {
    activeProject.set(/** @type {any} */ (kagocelProject)); // info.id === pid → без invoke
    const applied = await hydrateRolesFromProjectIfEmpty(kagocelProject.id, kagocelDecomp);
    expect(applied).toBe(true);

    const result = get(validateData).result;
    expect(result.reconstructed_from_project_json).toBe(true);
    expect(result.columns).toHaveLength(1 + 7 + 4 + 16);
    expect(result.file.rows).toBe(31); // decomposition.time_series.dates.length
    expect(result.detected.n_rows).toBe(31);
    expect(get(chosenKpiColumn)).toBe('Продажи в руб. бренд');
  });

  it('после гидрации modelStaleStatus.stale === false (Декомпозиция НЕ «устарела»)', async () => {
    // Симулируем загруженный обученный проект: модель есть, lastTrainedConfig из
    // localStorage расходится по форме (media-подмножество), но реконструированные
    // роли = сохранённый конфиг → не должно быть ложного «устарело».
    modelData.set(/** @type {any} */ ({ diagnostics: { r2: 0.9 }, channelParams: {}, picklePath: 'x', normalization: null }));
    lastTrainedConfig.set({ kpi: 'Продажи в руб. бренд', media: ['OLV Бюджет до НДС до АК'], control: [] });
    activeProject.set(/** @type {any} */ (kagocelProject));
    await hydrateRolesFromProjectIfEmpty(kagocelProject.id, kagocelDecomp);

    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false);
    expect(st.diff).toEqual([]);
  });

  it('НЕ затирает непустой реальный validateData (race guard)', async () => {
    const realValidate = { result: { status: 'ok', columns: [{ name: 'Real', role: 'kpi' }] } };
    validateData.set(/** @type {any} */ (realValidate));
    activeProject.set(/** @type {any} */ (kagocelProject));
    const applied = await hydrateRolesFromProjectIfEmpty(kagocelProject.id, kagocelDecomp);
    expect(applied).toBe(false);
    expect(get(validateData).result.columns).toEqual([{ name: 'Real', role: 'kpi' }]);
    expect(get(validateData).result.reconstructed_from_project_json).toBeUndefined();
  });

  it('пустые роли project.json → false (нет реконструкции)', async () => {
    const empty = { id: 'empty-proj', kpi_column: null, media_columns: [], control_columns: [], excluded_columns: [] };
    activeProject.set(/** @type {any} */ (empty));
    const applied = await hydrateRolesFromProjectIfEmpty('empty-proj', kagocelDecomp);
    expect(applied).toBe(false);
    expect(get(validateData).result).toBeNull();
  });
});

describe('LOAD-1 config-rehydration (аудит 2026-06-05): chosenKpiColumn из durable kpi_column', () => {
  it('activeProject.set с kpi_column → chosenKpiColumn ре-гидрирован (норм. load-путь, не только reconstruction)', () => {
    // Раньше chosenKpiColumn ставился ТОЛЬКО в hydrateRolesFromProjectIfEmpty
    // (validation.json отсутствует). При validation.json present оставался null →
    // ConfigPanel брал kpis[0] (первый алфавитно). Теперь activeProject.subscribe
    // ре-гидрирует из durable kpi_column на любом load.
    activeProject.set(/** @type {any} */ (kagocelProject));
    expect(get(chosenKpiColumn)).toBe('Продажи в руб. бренд');
  });

  it('activeProject.set(null) → chosenKpiColumn сброшен в null (no leakage между проектами)', () => {
    activeProject.set(/** @type {any} */ (kagocelProject));
    expect(get(chosenKpiColumn)).toBe('Продажи в руб. бренд');
    activeProject.set(null);
    expect(get(chosenKpiColumn)).toBeNull();
  });

  it('проект без kpi_column → chosenKpiColumn null (не падает)', () => {
    activeProject.set(/** @type {any} */ ({ id: 'no-kpi', media_columns: [], control_columns: [], excluded_columns: [] }));
    expect(get(chosenKpiColumn)).toBeNull();
  });
});

describe('LOAD-1 count-KPI train-входы (2026-06-06): kpiType/kpiKind/valuePerCountUnit из durable project.json', () => {
  it('activeProject.set с kpi_type/kpi_kind/value_per_count_unit → сторы ре-гидрированы (фикс re-train артефакта)', () => {
    activeProject.set(/** @type {any} */ ({
      id: 'otc', kpi_column: 'sales_packs', media_columns: [], control_columns: [], excluded_columns: [],
      kpi_type: 'sales_packs', kpi_kind: 'count', value_per_count_unit: 150,
    }));
    expect(get(kpiType)).toBe('sales_packs');     // competitor prior → симметричный (не флип)
    expect(get(kpiKind)).toBe('count');
    expect(get(valuePerCountUnit)).toBe(150);     // kpi_unit_cost восстановлен
  });

  it('activeProject.set(null) → сброс к дефолтам (no leakage между проектами)', () => {
    activeProject.set(/** @type {any} */ ({ id: 'x', kpi_type: 'leads', kpi_kind: 'count', value_per_count_unit: 99 }));
    expect(get(kpiType)).toBe('leads');
    activeProject.set(null);
    expect(get(kpiType)).toBe('sales');
    expect(get(kpiKind)).toBe('monetary');
    expect(get(valuePerCountUnit)).toBeNull();
  });

  it('SET-IF-PRESENT: проект без kpi_type НЕ затирает выбор wizard (клоббер-guard)', () => {
    // wizard выставил count ДО первого train (persist ещё не было) → промежуточный
    // activeProject.set (напр. UnitCostsPanel) с project без kpi_type не должен сбросить.
    kpiType.set('count_custom');
    kpiKind.set('count');
    valuePerCountUnit.set(42);
    activeProject.set(/** @type {any} */ ({ id: 'fresh', kpi_column: 'x', media_columns: [], control_columns: [] }));
    expect(get(kpiType)).toBe('count_custom');   // НЕ сброшен в 'sales'
    expect(get(kpiKind)).toBe('count');
    expect(get(valuePerCountUnit)).toBe(42);
  });

  it('value_per_count_unit отсутствует/не число → не затирает (set-if-present)', () => {
    valuePerCountUnit.set(77);
    activeProject.set(/** @type {any} */ ({ id: 'p', kpi_type: 'sales', kpi_kind: 'monetary' }));
    expect(get(valuePerCountUnit)).toBe(77);     // не было числа в project → сохранён
  });

  it('ID-GUARD: re-конфигур monetary→count (same-id set со СТАРЫМ disk kpi_type) НЕ затирает выбор wizard', () => {
    // Адверсариальный аудит 2026-06-06: без id-guard SET-IF-PRESENT воспроизводил prior-flip
    // артефакт. Сценарий: обученный monetary-проект (disk kpi_type='sales'), reload, юзер
    // переключает на count, UnitCostsPanel.save шлёт project_update БЕЗ kpi_type → получает
    // ProjectInfo со СТАРЫМ disk kpi_type='sales' → activeProject.set(тот же id).
    activeProject.set(/** @type {any} */ ({ id: 'reconf', kpi_type: 'sales', kpi_kind: 'monetary' }));
    expect(get(kpiType)).toBe('sales');          // загрузка обученного monetary
    // wizard переключает на count (стор; НЕ персистится до train — buildProjectUpdates без kpi_type)
    kpiType.set('leads');
    kpiKind.set('count');
    // UnitCostsPanel.save → ProjectInfo со СТАРЫМ disk kpi_type='sales', ТОТ ЖЕ id
    activeProject.set(/** @type {any} */ ({ id: 'reconf', kpi_type: 'sales', kpi_kind: 'monetary', unit_costs: { tv: 100 } }));
    expect(get(kpiType)).toBe('leads');          // id-guard: тот же проект → НЕ ре-гидрирует → не затёрто
    expect(get(kpiKind)).toBe('count');
  });

  it('ID-GUARD: СМЕНА проекта (другой id) ре-гидрирует из disk', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A', kpi_type: 'sales', kpi_kind: 'monetary' }));
    expect(get(kpiType)).toBe('sales');
    activeProject.set(/** @type {any} */ ({ id: 'B', kpi_type: 'leads', kpi_kind: 'count', value_per_count_unit: 30 }));
    expect(get(kpiType)).toBe('leads');          // другой id → ре-гидрация
    expect(get(valuePerCountUnit)).toBe(30);
  });
});
