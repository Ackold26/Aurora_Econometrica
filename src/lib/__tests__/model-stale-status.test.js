/**
 * STATE-1 (2026-06-02): ложный рассинхрон «было 7 стало 10» сразу после обучения.
 * Корень: lastTrainedConfig.media = обученное подмножество (enabled, напр. 7), а
 * modelStaleStatus сравнивал со ВСЕМИ media-ролями (10). Фикс: сравнивать с текущим
 * включённым подмножеством (modelChannelEnabled).
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import {
  modelData,
  validateData,
  lastTrainedConfig,
  modelChannelEnabled,
  disabledHolidays,
  modelStaleStatus,
  activeProject,
  activeProjectId,
} from '../project-state.js';

/** @param {string[]} media @param {string[]} control @param {string} kpi */
function setValidation(media, control, kpi) {
  const columns = [
    ...media.map((name) => ({ name, role: 'media' })),
    ...control.map((name) => ({ name, role: 'control' })),
    { name: kpi, role: 'kpi' },
  ];
  validateData.set(/** @type {any} */ ({ result: { columns } }));
}

beforeEach(() => {
  modelData.set(/** @type {any} */ ({ diagnostics: { r2: 0.9 }, channelParams: {}, picklePath: 'x', normalization: null }));
  lastTrainedConfig.set({ kpi: 'Sales', media: ['A', 'B', 'C'], control: ['X'] });
  modelChannelEnabled.set({});
  disabledHolidays.set([]);
});

describe('STATE-1 modelStaleStatus сравнивает с обученным подмножеством', () => {
  it('обучение на 3 из 4 каналов → НЕ stale сразу после обучения', () => {
    // 4 media-роли, но обучали на 3 (D выключен) — раньше давало ложный «было 3 стало 4»
    setValidation(['A', 'B', 'C', 'D'], ['X'], 'Sales');
    modelChannelEnabled.set({ A: true, B: true, C: true, D: false });
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false);
    expect(st.diff).toEqual([]);
  });

  it('включение ранее выключенного канала → stale', () => {
    setValidation(['A', 'B', 'C', 'D'], ['X'], 'Sales');
    modelChannelEnabled.set({ A: true, B: true, C: true, D: true }); // теперь 4 включено
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(true);
    expect(st.diff.join(' ')).toMatch(/Медиа-каналы: было 3, стало 4/);
  });

  it('смена KPI → stale независимо от каналов', () => {
    setValidation(['A', 'B', 'C'], ['X'], 'Revenue'); // KPI сменился
    modelChannelEnabled.set({ A: true, B: true, C: true });
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(true);
    expect(st.diff.join(' ')).toMatch(/KPI/);
  });

  it('guard: пустой enabled-map (после reload) → media-diff пропущен, нет ложного stale', () => {
    setValidation(['A', 'B', 'C', 'D'], ['X'], 'Sales');
    modelChannelEnabled.set({}); // enabled-инфо ещё нет
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false); // не флагуем media по всем ролям
  });

  it('изменение контрольных переменных → stale', () => {
    setValidation(['A', 'B', 'C'], ['X', 'Y'], 'Sales'); // добавлен контрольный Y
    modelChannelEnabled.set({ A: true, B: true, C: true });
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(true);
    expect(st.diff.join(' ')).toMatch(/Контрольные/);
  });
});

describe('#6 Tier-3/OVB modelStaleStatus реагирует на disabled_holidays', () => {
  it('изменение отключённых праздников после обучения → stale', () => {
    setValidation(['A', 'B', 'C'], ['X'], 'Sales'); // роли не менялись
    modelChannelEnabled.set({ A: true, B: true, C: true });
    lastTrainedConfig.set({ kpi: 'Sales', media: ['A', 'B', 'C'], control: ['X'], disabled: ['holiday_defender_day'] });
    disabledHolidays.set([]); // юзер вернул праздник после обучения
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(true);
    expect(st.diff.join(' ')).toMatch(/Отключённые праздники/);
  });

  it('те же отключённые праздники → НЕ stale (порядок не важен)', () => {
    setValidation(['A', 'B', 'C'], ['X'], 'Sales');
    modelChannelEnabled.set({ A: true, B: true, C: true });
    lastTrainedConfig.set({ kpi: 'Sales', media: ['A', 'B', 'C'], control: ['X'], disabled: ['holiday_a', 'holiday_b'] });
    disabledHolidays.set(['holiday_b', 'holiday_a']); // тот же набор, иной порядок
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false);
    expect(st.diff).toEqual([]);
  });

  it('legacy snapshot без disabled + ничего не отключено сейчас → НЕ stale', () => {
    setValidation(['A', 'B', 'C'], ['X'], 'Sales');
    modelChannelEnabled.set({ A: true, B: true, C: true });
    lastTrainedConfig.set({ kpi: 'Sales', media: ['A', 'B', 'C'], control: ['X'] }); // без disabled (модель до фичи)
    disabledHolidays.set([]);
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false);
  });
});

describe('LOAD-1 (C) guard: пустые/реконструированные роли НЕ stale', () => {
  it('validation.result === null → stale=false (не «конфиг изменён»)', () => {
    validateData.set(/** @type {any} */ ({ result: null }));
    modelChannelEnabled.set({ A: true, B: true, C: true });
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false);
    expect(st.diff).toEqual([]);
  });

  it('пустой columns[] (loaded до гидрации) → stale=false, не ложный «Контрольные было 1 стало 0»', () => {
    validateData.set(/** @type {any} */ ({ result: { columns: [] } }));
    modelChannelEnabled.set({});
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false);
    expect(st.diff).toEqual([]);
  });

  it('reconstructed_from_project_json:true → stale=false даже при рассинхроне с lastTrainedConfig', () => {
    // Роли реконструированы из project.json (= САМ сохранённый конфиг). Даже если
    // они расходятся с lastTrainedConfig (напр. контрольных стало больше), это не
    // «устарело» — это и есть «как обучали». Флаг гасит сравнение.
    validateData.set(/** @type {any} */ ({
      result: {
        reconstructed_from_project_json: true,
        columns: [
          { name: 'A', role: 'media' },
          { name: 'B', role: 'media' },
          { name: 'X', role: 'control' },
          { name: 'Y', role: 'control' }, // лишний контрольный vs lastTrainedConfig.control=['X']
          { name: 'Revenue', role: 'kpi' }, // другой KPI vs lastTrainedConfig.kpi='Sales'
        ],
      },
    }));
    modelChannelEnabled.set({ A: true, B: true });
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false);
    expect(st.diff).toEqual([]);
  });
});

/**
 * s61 (А4): ложное «Декомпозиция устарела… Медиа-каналы: было 4, стало 8» после
 * повторного входа в проект. Сравнение в modelStaleStatus уже шло по включённым –
 * корень в восстановлении: сохранённый результат проверки хранит роли «как отдал
 * движок» (обе половины каждой пары – media), а выбор «не использовать» лежит в
 * excluded_columns проекта и при возврате не применялся. Восстановление запускает
 * подписка на activeProjectId (restoreProjectResults), диск подменён через invoke.
 */
describe('А4: возврат в проект применяет исключённые роли (нет ложного «устарела»)', () => {
  const MONEY = ['tv_spend', 'digital_spend', 'ooh_spend', 'performance_spend'];
  const PHYS = ['tv_trp', 'digital_impressions', 'ooh_contacts', 'performance_clicks'];
  const CONTROL = ['competitor_trp', 'price_index', 'category_sales'];

  /** Сохранённый results/validation.json: все 8 медиа-колонок в роли media. */
  function savedValidation() {
    return {
      status: 'ok',
      file: { rows: 48 },
      columns: [
        { name: 'date', role: 'date' },
        { name: 'sales_rub', role: 'kpi' },
        ...MONEY.map((name) => ({ name, role: 'media' })),
        ...PHYS.map((name) => ({ name, role: 'media' })),
        ...CONTROL.map((name) => ({ name, role: 'control' })),
      ],
    };
  }

  /** @param {string} id @param {string[]} excluded */
  function savedProject(id, excluded) {
    return {
      id,
      kpi_column: 'sales_rub',
      media_columns: MONEY,
      control_columns: CONTROL,
      excluded_columns: excluded,
      model_channel_enabled: Object.fromEntries(MONEY.map((name) => [name, true])),
    };
  }

  /**
   * Подменить диск: project_load_results и project_get.
   * @param {any} results
   * @param {any | (() => any)} project
   */
  function mockDisk(results, project) {
    /** @type {any} */ (invoke).mockImplementation(async (/** @type {string} */ cmd) => {
      if (cmd === 'project_load_results') return results;
      if (cmd === 'project_get') return typeof project === 'function' ? project() : project;
      return null;
    });
  }

  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
  const roleOf = (/** @type {string} */ name) =>
    /** @type {any} */ (get(validateData)).result?.columns?.find((/** @type {any} */ c) => c.name === name)?.role;
  const mediaNames = () =>
    /** @type {any[]} */ (/** @type {any} */ (get(validateData)).result?.columns ?? [])
      .filter((c) => c.role === 'media').map((c) => c.name);

  beforeEach(() => {
    activeProject.set(null);
    activeProjectId.set(null);
    validateData.set(/** @type {any} */ ({ result: null, correlationMatrix: null, columnHistograms: null }));
    lastTrainedConfig.set({ kpi: 'sales_rub', media: [...MONEY], control: [...CONTROL] });
  });

  afterEach(() => {
    activeProjectId.set(null);
    activeProject.set(null);
    /** @type {any} */ (invoke).mockReset();
    /** @type {any} */ (invoke).mockResolvedValue(null);
  });

  it('обучен на 4 каналах, 4 физические половины исключены → после восстановления НЕ stale', async () => {
    const results = { validation: savedValidation(), modelDiagnostics: { r2: 0.9 } };
    mockDisk(results, null);
    activeProject.set(/** @type {any} */ (savedProject('a4-1', PHYS)));
    activeProjectId.set('a4-1');
    await flush();

    expect(mediaNames()).toEqual(MONEY);
    for (const name of PHYS) expect(roleOf(name)).toBe('unused');
    const st = get(modelStaleStatus);
    expect(st.diff).toEqual([]);
    expect(st.stale).toBe(false);
    // Сохранённый результат не мутирован: роли «как отдал движок» на месте.
    expect(results.validation.columns.filter((c) => c.role === 'media').length).toBe(8);
  });

  it('после обучения исключён ещё один канал → stale (настоящее устаревание не замаскировано)', async () => {
    mockDisk({ validation: savedValidation(), modelDiagnostics: { r2: 0.9 } }, null);
    activeProject.set(/** @type {any} */ (savedProject('a4-2', [...PHYS, 'performance_spend'])));
    activeProjectId.set('a4-2');
    await flush();

    expect(mediaNames()).toEqual(['tv_spend', 'digital_spend', 'ooh_spend']);
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(true);
    expect(st.diff.join(' ')).toMatch(/Медиа-каналы: было 4, стало 3/);
  });

  it('холодный старт: стор проекта ещё не догнал id → роли читаются через project_get', async () => {
    mockDisk({ validation: savedValidation(), modelDiagnostics: { r2: 0.9 } }, savedProject('a4-3', PHYS));
    activeProjectId.set('a4-3'); // activeProject ещё null
    await flush();

    const calls = /** @type {any} */ (invoke).mock.calls;
    expect(calls.some((/** @type {any[]} */ c) => c[0] === 'project_get' && c[1]?.projectId === 'a4-3')).toBe(true);
    expect(mediaNames()).toEqual(MONEY);
    for (const name of PHYS) expect(roleOf(name)).toBe('unused');
  });

  it('пока читали проект, активным стал другой → чужой результат в стор не кладётся', async () => {
    const sentinel = { status: 'ok', columns: [{ name: 'чужой', role: 'media' }] };
    mockDisk({ validation: savedValidation() }, () => {
      // Ответ project_get по a4-4 возвращается уже после переключения на другой проект.
      validateData.set(/** @type {any} */ ({ result: sentinel, correlationMatrix: null, columnHistograms: null }));
      activeProjectId.set(null);
      return savedProject('a4-4', PHYS);
    });
    activeProjectId.set('a4-4');
    await flush();

    expect(/** @type {any} */ (get(validateData)).result).toBe(sentinel);
  });

  it('пустой или отсутствующий excluded_columns → результат кладётся как есть', async () => {
    const results = { validation: savedValidation() };
    mockDisk(results, null);
    activeProject.set(/** @type {any} */ ({ id: 'a4-5', kpi_column: 'sales_rub' }));
    activeProjectId.set('a4-5');
    await flush();

    expect(/** @type {any} */ (get(validateData)).result).toBe(results.validation);
    expect(mediaNames().length).toBe(8);
  });

  it('чтение проекта не удалось → результат проверки всё равно восстановлен', async () => {
    const results = { validation: savedValidation() };
    /** @type {any} */ (invoke).mockImplementation(async (/** @type {string} */ cmd) => {
      if (cmd === 'project_load_results') return results;
      if (cmd === 'project_get') throw new Error('диск недоступен');
      return null;
    });
    activeProjectId.set('a4-6');
    await flush();

    expect(/** @type {any} */ (get(validateData)).result).toBe(results.validation);
  });
});
