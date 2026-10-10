/**
 * s61 (А0/А1): хранитель шага «Модель» и пары «бюджет + физическая метрика».
 *
 * Блокер выпущенной 2.5.9: на файле с парами (tv_spend + tv_trp …) шаг «Модель»
 * не открывался ни через «Принять авто-настройку», ни через «Далее ▶» без
 * рекомендаций. Хранитель `completeStep(1)` → `cppSatisfied(currentGateSnapshot())`
 * считал каналы по ролям и не знал, что физические половины пар выключены из
 * модели картой включённости; цены единицы у них нет → отказ, причём молчаливый.
 *
 * Неприкосновенное (класс артефакта ROI 12186×): физический канал, ВКЛЮЧЁННЫЙ в
 * модель, в режиме ROI без цены единицы не открывает «Модель» и не доходит до
 * обучения. Случаи C, E, E2, H, J держат именно это.
 *
 * Заготовка случаев – Projects/_s60/dig_confirm/gate_cases.js.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { tick } from 'svelte';
import { render, fireEvent } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import ConfigPanel from '$lib/components/ConfigPanel.svelte';
import {
  pipelineStepMeta, completeStep, validateData, perChannelInput, unitCosts,
  analysisMode, modelChannelEnabled, activeProject, activeProjectId,
  cppSatisfied, currentGateSnapshot, analysisModeIsPersisted,
  resolveChannelEnabled, mergeLiveChannelEnabled, isModelColumnEnabled,
  importData, chosenKpiColumn, isComputing, computeStatus, expertMode,
  cppSatisfiedForPairPlan, applyExpressPairPlan, applyPairSelectionToEnabledMap,
  modelStaleStatus, lastTrainedConfig, modelData, validationHeaderMetrics,
} from '$lib/project-state.js';
import { buildExpressPlan } from '$lib/express-validate.js';
import { groupChannelColumns, resolvePairSelection } from '$lib/channel-pairs.js';
// Исходники как текст – для сторожей «отказ хранителя не молчаливый» (экран
// «Валидация» целиком в тестах не отрисовывается; поведение проверяется вживую).
import validateStepSrc from '$lib/components/pipeline/ValidateStepV13.svelte?raw';
import pipelineLayoutSrc from '../routes/pipeline/+layout.svelte?raw';
import pipelinePageSrc from '../routes/pipeline/+page.svelte?raw';
import { detectChannelUnitType } from '$lib/services/classifier-patterns.js';

const PHYS = ['tv_trp', 'digital_impressions', 'ooh_contacts', 'performance_clicks'];
const MONEY = ['tv_spend', 'digital_spend', 'ooh_spend', 'performance_spend'];

/** Состав встроенного парного демо-файла: 4 бюджетных + 4 физических + 3 контроля. */
function columns() {
  return [
    { name: 'date', role: 'date' },
    { name: 'sales_rub', role: 'kpi' },
    ...MONEY.map((name) => ({ name, role: 'media', stats: { zeros_pct: 0 } })),
    ...PHYS.map((name) => ({ name, role: 'media', stats: { zeros_pct: 0 } })),
    { name: 'competitor_trp', role: 'control' },
    { name: 'price_index', role: 'control' },
    { name: 'category_sales', role: 'control' },
  ];
}

/** @param {any[]} cols */
function setColumns(cols) {
  validateData.set(/** @type {any} */ ({
    result: { status: 'ok', columns: cols }, correlationMatrix: null, columnHistograms: null,
  }));
}

const status = () => get(pipelineStepMeta).map((s) => s.status);
/** @returns {any} результат проверки из стора */
const validateResult = () => /** @type {any} */ (get(validateData)).result;

/** Экспресс-состояние: бюджетные monetary, физические половины выключены тумблером. */
function applyExpress() {
  const plan = buildExpressPlan({
    validateResult: validateResult(), currentKPI: 'sales', kpiUnavailable: false, kpiKind: 'monetary',
  });
  expect(plan.eligible).toBe(true);
  perChannelInput.set(plan.uniform);
  /** @type {Record<string, boolean>} */
  const map = {};
  for (const c of plan.disable) map[c] = false;
  modelChannelEnabled.set(map);
}

/**
 * Составное условие гейта обучения – то же выражение, что в
 * ConfigPanel.trainModel: `analysisModeIsPersisted() && !cppSatisfied({channels: enabledChannels, …})`.
 * @param {string[]} enabledChannels
 * @returns {boolean} true → обучение останавливается
 */
function trainGateBlocks(enabledChannels) {
  return analysisModeIsPersisted() && !cppSatisfied({
    channels: enabledChannels,
    perChannelInput: get(perChannelInput),
    unitCosts: get(unitCosts),
    analysisMode: get(analysisMode),
  });
}

/** Вызовы записи режима и метрик каналов в проект. */
const modeWrites = () => /** @type {any} */ (invoke).mock.calls.filter(
  (/** @type {any[]} */ c) => c[0] === 'project_update' && c[1]?.updates && 'per_channel_input' in c[1].updates,
);

beforeEach(() => {
  activeProject.set(null);
  activeProjectId.set(null);
  pipelineStepMeta.set([
    { status: 'complete', errorMessage: null },
    { status: 'ready', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
  ]);
  setColumns(columns());
  perChannelInput.set({});
  unitCosts.set({});
  modelChannelEnabled.set({});
  analysisMode.set('roi');
  /** @type {any} */ (invoke).mockClear();
});

afterEach(() => {
  activeProject.set(null);
  activeProjectId.set(null);
});

describe('хранитель completeStep(1) и пары «бюджет + физическая метрика»', () => {
  it('A. экспресс: 4 бюджетных включены, 4 физических выключены → true, «Модель» ready', () => {
    applyExpress();
    expect(completeStep(1)).toBe(true);
    expect(status().slice(1, 3)).toEqual(['complete', 'ready']);
  });

  it('B. «Далее» после развязки пар (все каналы деньгами) → true, «Модель» ready', () => {
    const media = validateResult().columns
      .filter((/** @type {any} */ c) => c.role === 'media').map((/** @type {any} */ c) => c.name);
    const { byChannel } = groupChannelColumns(media);
    const sel = /** @type {Record<string, 'monetary'|'physical'>} */ (
      Object.fromEntries(Object.keys(byChannel).map((b) => [b, 'monetary'])));
    const { perColumn, disable } = resolvePairSelection(byChannel, sel);
    perChannelInput.set(perColumn);
    /** @type {Record<string, boolean>} */
    const map = {};
    for (const c of Object.keys(perColumn)) map[c] = true;
    for (const c of disable) map[c] = false;
    modelChannelEnabled.set(map);
    expect(completeStep(1)).toBe(true);
    expect(status().slice(1, 3)).toEqual(['complete', 'ready']);
  });

  it('C. ROI 12186×: физический канал ВКЛЮЧЁН без цены (tv_trp вместо tv_spend) → false, «Модель» locked', () => {
    perChannelInput.set({
      tv_trp: 'physical', digital_spend: 'monetary', ooh_spend: 'monetary', performance_spend: 'monetary',
    });
    modelChannelEnabled.set({
      tv_trp: true, tv_spend: false, digital_impressions: false, ooh_contacts: false, performance_clicks: false,
    });
    expect(completeStep(1)).toBe(false);
    expect(status().slice(1, 3)).toEqual(['ready', 'locked']);
  });

  it('D. тот же физический канал с ценой единицы > 0 → открыто', () => {
    perChannelInput.set({
      tv_trp: 'physical', digital_spend: 'monetary', ooh_spend: 'monetary', performance_spend: 'monetary',
    });
    unitCosts.set({ tv_trp: 1500 });
    modelChannelEnabled.set({
      tv_trp: true, tv_spend: false, digital_impressions: false, ooh_contacts: false, performance_clicks: false,
    });
    expect(completeStep(1)).toBe(true);
    expect(status()[2]).toBe('ready');
  });

  it('E. пустая карта + физические без цены → заблокировано (нет данных о развязке = включено)', () => {
    perChannelInput.set({
      tv_spend: 'monetary', digital_spend: 'monetary', ooh_spend: 'monetary', performance_spend: 'monetary',
    });
    modelChannelEnabled.set({});
    expect(completeStep(1)).toBe(false);
    expect(status()[2]).toBe('locked');
  });

  it('E2. одна физическая половина выключена, другая включена без цены → заблокировано', () => {
    perChannelInput.set({
      tv_spend: 'monetary', digital_spend: 'monetary', ooh_spend: 'monetary', performance_spend: 'monetary',
    });
    modelChannelEnabled.set({
      tv_trp: false, digital_impressions: true, ooh_contacts: false, performance_clicks: false,
    });
    expect(completeStep(1)).toBe(false);
    expect(status()[2]).toBe('locked');
  });

  it('E3. физическая половина с именем вне запасного набора шаблонов (ooh_contacts) включена без цены → заблокировано', () => {
    // А-1 (аудит №1): тестовая среда работает на запасном наборе шаблонов, где
    // «contacts» нет – детектор считает ooh_contacts деньгами. Разбор пар считает её
    // физической (по нему она и была выключена) – гейт обязан быть не мягче.
    perChannelInput.set({
      tv_spend: 'monetary', digital_spend: 'monetary', ooh_spend: 'monetary', performance_spend: 'monetary',
    });
    modelChannelEnabled.set({
      tv_trp: false, digital_impressions: false, ooh_contacts: true, performance_clicks: false,
    });
    expect(completeStep(1)).toBe(false);
    expect(status()[2]).toBe('locked');
    // С ценой единицы – открыто.
    unitCosts.set({ ooh_contacts: 12 });
    expect(completeStep(1)).toBe(true);
    expect(status()[2]).toBe('ready');
  });

  it('А-1: гейт не мягче разбора пар – имя, физическое для пар, без записи о метрике физическое и для гейта', () => {
    for (const name of ['ooh_contacts', 'radio_reach', 'olv_impr', 'Наружка Контакты', 'ТВ охват', 'tv_грп', 'ТВ трп', 'Баннеры показами']) {
      expect(cppSatisfied({ channels: [name], perChannelInput: {}, unitCosts: {}, analysisMode: 'roi' }), name).toBe(false);
      expect(cppSatisfied({ channels: [name], perChannelInput: {}, unitCosts: { [name]: 10 }, analysisMode: 'roi' }), name).toBe(true);
      // Явная запись пользователя «деньги» по-прежнему важнее имени (D-1).
      expect(cppSatisfied({ channels: [name], perChannelInput: { [name]: 'monetary' }, unitCosts: {}, analysisMode: 'roi' }), name).toBe(true);
      // «Эффективность» физические единицы допускает без цены.
      expect(cppSatisfied({ channels: [name], perChannelInput: {}, unitCosts: {}, analysisMode: 'effectiveness' }), name).toBe(true);
    }
    // Денежные имена гейт не трогает.
    for (const name of ['tv_spend', 'ТВ бюджет', 'ooh_budget']) {
      expect(cppSatisfied({ channels: [name], perChannelInput: {}, unitCosts: {}, analysisMode: 'roi' }), name).toBe(true);
    }
  });

  it('F. режим «Эффективность» + физические без цены → открыто (прежнее поведение)', () => {
    analysisMode.set('effectiveness');
    perChannelInput.set({
      tv_trp: 'physical', digital_impressions: 'physical', ooh_contacts: 'physical', performance_clicks: 'physical',
    });
    modelChannelEnabled.set({ tv_spend: false, digital_spend: false, ooh_spend: false, performance_spend: false });
    expect(completeStep(1)).toBe(true);
    expect(status()[2]).toBe('ready');
  });

  it('G. completeStep возвращает true для шага ≠ 1 (даже при неудовлетворённом хранителе)', () => {
    // Пустая карта + физические без цены: хранитель шага 1 отказал бы.
    expect(cppSatisfied(currentGateSnapshot())).toBe(false);
    expect(completeStep(0)).toBe(true);
    expect(completeStep(2)).toBe(true);
    expect(completeStep(6)).toBe(true);
  });

  it('снимок хранителя несёт карту включённости (иначе правка cppSatisfied инертна)', () => {
    modelChannelEnabled.set({ tv_trp: false });
    expect(currentGateSnapshot().modelChannelEnabled).toEqual({ tv_trp: false });
  });

  it('cppSatisfied без карты ведёт себя как прежде; ветка channels карту не читает', () => {
    const cols = [{ name: 'sales_rub', role: 'kpi' }, { name: 'tv_trp', role: 'media' }];
    // Нет карты → колонка включена → физический без цены блокирует.
    expect(cppSatisfied({ columns: cols, perChannelInput: {}, unitCosts: {}, analysisMode: 'roi' })).toBe(false);
    // Явный false → колонка в модель не идёт → нечего проверять.
    expect(cppSatisfied({
      columns: cols, perChannelInput: {}, unitCosts: {}, analysisMode: 'roi', modelChannelEnabled: { tv_trp: false },
    })).toBe(true);
    // true и «не булево» – включена.
    expect(cppSatisfied({
      columns: cols, perChannelInput: {}, unitCosts: {}, analysisMode: 'roi', modelChannelEnabled: { tv_trp: true },
    })).toBe(false);
    // Готовый список каналов (гейт обучения) проверяется целиком, карта его не сужает.
    expect(cppSatisfied({
      channels: ['tv_trp'], perChannelInput: {}, unitCosts: {}, analysisMode: 'roi', modelChannelEnabled: { tv_trp: false },
    })).toBe(false);
  });

  it('isModelColumnEnabled: нет карты или ключа = включена, выключает только явный false', () => {
    expect(isModelColumnEnabled(undefined, 'a')).toBe(true);
    expect(isModelColumnEnabled(null, 'a')).toBe(true);
    expect(isModelColumnEnabled({}, 'a')).toBe(true);
    expect(isModelColumnEnabled({ a: true }, 'a')).toBe(true);
    expect(isModelColumnEnabled({ a: false }, 'a')).toBe(false);
    expect(isModelColumnEnabled({ b: false }, 'a')).toBe(true);
  });
});

describe('К2: гейт обучения работает уже в первой сессии свежего проекта', () => {
  /** Свежий проект: analysis_mode на диске нет (project.rs создаёт с None). */
  function openFreshProject() {
    activeProject.set(/** @type {any} */ ({ id: 'fresh-1', name: 'свежий' }));
    activeProjectId.set('fresh-1');
    /** @type {any} */ (invoke).mockClear();
  }

  it('H. после успешного completeStep(1) признак поднят, режим и метрики ушли в проект, гейт блокирует включённый физический без цены', () => {
    openFreshProject();
    expect(analysisModeIsPersisted()).toBe(false); // до «Валидации» гейт обучения молчит
    applyExpress();
    expect(trainGateBlocks([...MONEY, 'tv_trp'])).toBe(false); // …и пропустил бы артефакт

    expect(completeStep(1)).toBe(true);

    expect(analysisModeIsPersisted()).toBe(true);
    const writes = modeWrites();
    expect(writes.length).toBe(1);
    expect(writes[0][1]).toEqual({
      projectId: 'fresh-1',
      updates: { analysis_mode: 'roi', per_channel_input: get(perChannelInput) },
    });
    // Пользователь включил галочкой физическую половину на «Модели» → стоп.
    expect(trainGateBlocks([...MONEY, 'tv_trp'])).toBe(true);
    // Штатный набор (4 бюджетных) обучается.
    expect(trainGateBlocks(MONEY)).toBe(false);
    // С ценой единицы включённый физический канал допустим.
    unitCosts.set({ tv_trp: 1500 });
    expect(trainGateBlocks([...MONEY, 'tv_trp'])).toBe(false);
  });

  it('H2. отказ хранителя признак не поднимает и в проект не пишет', () => {
    openFreshProject();
    perChannelInput.set({ tv_trp: 'physical' });
    modelChannelEnabled.set({ tv_trp: true });
    expect(completeStep(1)).toBe(false);
    expect(analysisModeIsPersisted()).toBe(false);
    expect(modeWrites().length).toBe(0);
  });

  it('H3. без активного проекта – ничего не пишем и признак не поднимаем', () => {
    applyExpress();
    expect(completeStep(1)).toBe(true);
    expect(analysisModeIsPersisted()).toBe(false);
    expect(modeWrites().length).toBe(0);
  });

  it('H4. шаг ≠ 1 признак не поднимает и режим не пишет', () => {
    openFreshProject();
    applyExpress();
    expect(completeStep(0)).toBe(true);
    expect(completeStep(2)).toBe(true);
    expect(analysisModeIsPersisted()).toBe(false);
    expect(modeWrites().length).toBe(0);
  });

  it('H6. гейт обучения останавливает ЛЮБУЮ физическую половину встроенного примера, включённую галочкой', () => {
    openFreshProject();
    applyExpress();
    expect(completeStep(1)).toBe(true);
    for (const phys of PHYS) {
      expect(trainGateBlocks([...MONEY, phys]), phys).toBe(true);
    }
  });

  it('H5. признак сбрасывается при смене проекта (чужому проекту не достаётся)', () => {
    openFreshProject();
    applyExpress();
    completeStep(1);
    expect(analysisModeIsPersisted()).toBe(true);
    activeProject.set(/** @type {any} */ ({ id: 'legacy-2', kpi_column: 'sales' })); // без analysis_mode
    expect(analysisModeIsPersisted()).toBe(false);
  });

  it('J. физический канал без пары, автоотключённый (нулей > 80 %): хранителя проходит, после включения блокируется гейтом обучения', () => {
    openFreshProject();
    const cols = [
      { name: 'sales_rub', role: 'kpi' },
      { name: 'tv_spend', role: 'media', stats: { zeros_pct: 0 } },
      { name: 'digital_spend', role: 'media', stats: { zeros_pct: 0 } },
      { name: 'radio_trp', role: 'media', stats: { zeros_pct: 92 } },
    ];
    setColumns(cols);
    // Карта – ровно та, что ставит панель обучения при приходе результата проверки.
    const map = resolveChannelEnabled(cols.filter((c) => c.role === 'media'), {});
    expect(map).toEqual({ tv_spend: true, digital_spend: true, radio_trp: false });
    modelChannelEnabled.set(map);
    perChannelInput.set({ tv_spend: 'monetary', digital_spend: 'monetary' });

    expect(completeStep(1)).toBe(true); // выключенный канал хранителя не держит
    expect(status()[2]).toBe('ready');
    expect(analysisModeIsPersisted()).toBe(true);

    // Пользователь включает radio_trp галочкой на «Модели» – цены единицы нет.
    expect(trainGateBlocks(['tv_spend', 'digital_spend', 'radio_trp'])).toBe(true);
    expect(trainGateBlocks(['tv_spend', 'digital_spend'])).toBe(false);
  });
});

describe('I. mergeLiveChannelEnabled – перенос живой карты в карту панели обучения', () => {
  it('переносит булевы значения по существующим ключам', () => {
    const local = { tv_spend: true, tv_trp: true, digital_spend: true, digital_impressions: true };
    const merged = mergeLiveChannelEnabled(local, { tv_trp: false, digital_impressions: false });
    expect(merged).toEqual({ tv_spend: true, tv_trp: false, digital_spend: true, digital_impressions: false });
    expect(merged).not.toBe(local);
    expect(local.tv_trp).toBe(true); // исходный объект не тронут
  });

  it('переносит и включение (false → true)', () => {
    const merged = mergeLiveChannelEnabled({ a: false, b: true }, { a: true });
    expect(merged).toEqual({ a: true, b: true });
  });

  it('чужие ключи не добавляются', () => {
    const local = { tv_spend: true };
    const merged = mergeLiveChannelEnabled(local, { tv_spend: false, чужой: false, ещё: true });
    expect(Object.keys(merged)).toEqual(['tv_spend']);
    expect(merged.tv_spend).toBe(false);
  });

  it('не булевы значения игнорируются', () => {
    const local = { a: true, b: false };
    const live = /** @type {any} */ ({ a: 'false', b: 1 });
    expect(mergeLiveChannelEnabled(local, live)).toBe(local);
  });

  it('без отличий возвращает ТОТ ЖЕ объект (условие отсутствия петли эффектов)', () => {
    const local = { a: true, b: false };
    expect(mergeLiveChannelEnabled(local, { a: true, b: false })).toBe(local);
    expect(mergeLiveChannelEnabled(local, {})).toBe(local);
    expect(mergeLiveChannelEnabled(local, null)).toBe(local);
    expect(mergeLiveChannelEnabled(local, undefined)).toBe(local);
    expect(mergeLiveChannelEnabled(local, { чужой: true })).toBe(local);
  });

  it('повторный вызов на собственном результате – неподвижная точка (два эффекта не зацикливаются)', () => {
    // Круг «стор → панель → стор»: панель переносит отличия, пишет в стор копию
    // своей карты, обратный перенос этой копии обязан вернуть тот же объект.
    const local = { tv_spend: true, tv_trp: true };
    const afterStore = mergeLiveChannelEnabled(local, { tv_trp: false });
    const storeEcho = { ...afterStore }; // то, что панель записала бы в стор
    expect(mergeLiveChannelEnabled(afterStore, storeEcho)).toBe(afterStore);
    expect(mergeLiveChannelEnabled(afterStore, afterStore)).toBe(afterStore);
  });
});

/**
 * К1 – отрисовка панели обучения. Панель смонтирована с момента открытия конвейера,
 * развязка пар происходит позже и пишет только общий стор. Раньше локальная карта
 * панели стор не читала: в журнале живого прохода `econ_preflight … channels=8`
 * при четырёх выключенных физических половинах.
 *
 * Здесь же – проверка на петлю двух встречных эффектов (панель → стор, стор →
 * панель): зацикливание Svelte превращает в исключение effect_update_depth_exceeded
 * при сбросе эффектов, и `await tick()` уронил бы тест.
 */
describe('К1: панель обучения берёт карту включённости из общего стора', () => {
  const validation = () => ({ status: 'ok', columns: columns(), detected: { date: 'date' } });

  /** @param {HTMLElement} container */
  const checkedNames = (container) => [...container.querySelectorAll('.channel-item')]
    .filter((el) => /** @type {HTMLInputElement} */ (el.querySelector('input[type="checkbox"]')).checked)
    .map((el) => el.querySelector('.channel-name')?.textContent?.trim());

  const settle = async () => { for (let i = 0; i < 4; i++) await tick(); };

  /** Развязка пар на «Валидации» (то же, что делает expressConfirmAll). */
  function unlinkPairs() {
    modelChannelEnabled.update((mapping) => {
      const next = { ...mapping };
      for (const col of PHYS) next[col] = false;
      return next;
    });
  }

  beforeEach(() => {
    importData.set(/** @type {any} */ ({ file: null, columns: null, rows: null }));
    chosenKpiColumn.set(null);
    isComputing.set(false);
    computeStatus.set('');
    expertMode.set(false);
  });

  afterEach(() => {
    /** @type {any} */ (invoke).mockReset();
    /** @type {any} */ (invoke).mockResolvedValue(null);
    importData.set(/** @type {any} */ ({ file: null, columns: null, rows: null }));
    isComputing.set(false);
    computeStatus.set('');
  });

  it('развязка пар ПОСЛЕ монтирования доезжает до панели: 4 включённых канала, петли нет', async () => {
    const { container } = render(ConfigPanel, { props: { validation: validation() } });
    await settle();
    // Панель при приходе результата проверки включила все 8 и записала это в стор.
    expect(checkedNames(container)).toEqual([...MONEY, ...PHYS]);
    expect(Object.values(get(modelChannelEnabled)).filter(Boolean).length).toBe(8);

    unlinkPairs();
    await settle();

    expect(checkedNames(container)).toEqual(MONEY);
    expect(container.querySelector('.channels-grid')?.previousElementSibling?.textContent).toContain('(4)');
    // Стор после круга «стор → панель → стор»: все 8 ключей, 4 выключены.
    expect(get(modelChannelEnabled)).toEqual({
      ...Object.fromEntries(MONEY.map((n) => [n, true])),
      ...Object.fromEntries(PHYS.map((n) => [n, false])),
    });
    expect(container.querySelector('.config-summary')?.textContent).toContain('4 канала');
  });

  it('развязка пар ДО прихода результата проверки: инициализация берёт живую карту поверх сохранённой', async () => {
    // Стор проекта устарел: persistPairToggles пишет на диск, activeProject не обновляет.
    activeProject.set(/** @type {any} */ ({ id: 'k1-stale', model_channel_enabled: {} }));
    unlinkPairs();
    const { container } = render(ConfigPanel, { props: { validation: validation() } });
    await settle();
    expect(checkedNames(container)).toEqual(MONEY);
  });

  it('повторная инициализация (смена KPI) не затирает развязку пар', async () => {
    activeProject.set(/** @type {any} */ ({ id: 'k1-reinit', model_channel_enabled: {} }));
    const { container } = render(ConfigPanel, { props: { validation: validation() } });
    await settle();
    unlinkPairs();
    await settle();
    expect(checkedNames(container)).toEqual(MONEY);

    chosenKpiColumn.set('sales_rub'); // эффект инициализации срабатывает заново
    await settle();

    expect(checkedNames(container)).toEqual(MONEY);
    expect(Object.entries(get(modelChannelEnabled)).filter(([, v]) => v).map(([k]) => k)).toEqual(MONEY);
  });

  it('галочка в панели пишет стор и не откатывается обратной синхронизацией', async () => {
    const { container } = render(ConfigPanel, { props: { validation: validation() } });
    await settle();
    unlinkPairs();
    await settle();

    const box = /** @type {HTMLInputElement} */ ([...container.querySelectorAll('.channel-item')]
      .find((el) => el.querySelector('.channel-name')?.textContent?.trim() === 'tv_trp')
      ?.querySelector('input[type="checkbox"]'));
    await fireEvent.click(box);
    await settle();

    expect(get(modelChannelEnabled).tv_trp).toBe(true);
    expect(checkedNames(container)).toEqual([...MONEY, 'tv_trp']);

    await fireEvent.click(box);
    await settle();
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
    expect(checkedNames(container)).toEqual(MONEY);
  });

  it('в предпроверку и обучение уходят ровно включённые в сторе каналы (4, а не 8)', async () => {
    /** @type {any} */
    let preflightArgs = null;
    /** @type {any} */ (invoke).mockImplementation(async (/** @type {string} */ cmd, /** @type {any} */ args) => {
      if (cmd === 'project_get_dir') return 'C:/проект';
      if (cmd === 'econ_preflight') {
        preflightArgs = args;
        // Не «reliable» → панель останавливается на баннере, обучение не стартует.
        return { status: 'ok', overall_tier: 'directional', overrideable: true };
      }
      return null;
    });
    activeProject.set(/** @type {any} */ ({ id: 'k1-train' }));
    activeProjectId.set('k1-train');
    importData.set(/** @type {any} */ ({ file: 'C:/данные.csv', columns: null, rows: 48 }));

    const { container } = render(ConfigPanel, { props: { validation: validation() } });
    await settle();
    unlinkPairs();
    perChannelInput.set(Object.fromEntries(MONEY.map((n) => [n, 'monetary'])));
    await settle();

    await fireEvent.click(/** @type {HTMLElement} */ (container.querySelector('.run-btn')));
    for (let i = 0; i < 20 && !preflightArgs; i++) await new Promise((resolve) => setTimeout(resolve, 0));

    expect(preflightArgs?.mediaColumns).toEqual(MONEY);
    const update = /** @type {any} */ (invoke).mock.calls.find(
      (/** @type {any[]} */ c) => c[0] === 'project_update' && Array.isArray(c[1]?.updates?.media_columns));
    expect(update?.[1].updates.media_columns).toEqual(MONEY);
  });

  it.each(['tv_trp', 'ooh_contacts'])('включённый галочкой физический канал без цены (%s): обучение остановлено гейтом (после прохода «Валидации»)', async (physName) => {
    /** @type {string[]} */
    const commands = [];
    /** @type {any} */ (invoke).mockImplementation(async (/** @type {string} */ cmd) => {
      commands.push(cmd);
      if (cmd === 'project_get_dir') return 'C:/проект';
      return null;
    });
    activeProject.set(/** @type {any} */ ({ id: 'k1-gate' })); // свежий проект, режима на диске нет
    activeProjectId.set('k1-gate');
    importData.set(/** @type {any} */ ({ file: 'C:/данные.csv', columns: null, rows: 48 }));

    const { container } = render(ConfigPanel, { props: { validation: validation() } });
    await settle();
    // Экспресс на «Валидации»: развязка пар + успешный проход хранителя.
    perChannelInput.set(Object.fromEntries(MONEY.map((n) => [n, 'monetary'])));
    unlinkPairs();
    expect(completeStep(1)).toBe(true);
    await settle();

    // Пользователь включает физическую половину на «Модели».
    const box = /** @type {HTMLInputElement} */ ([...container.querySelectorAll('.channel-item')]
      .find((el) => el.querySelector('.channel-name')?.textContent?.trim() === physName)
      ?.querySelector('input[type="checkbox"]'));
    await fireEvent.click(box);
    await settle();
    expect(get(modelChannelEnabled)[physName]).toBe(true);
    commands.length = 0;

    await fireEvent.click(/** @type {HTMLElement} */ (container.querySelector('.run-btn')));
    await settle();

    expect(get(computeStatus)).toContain('Обучение остановлено');
    expect(commands).not.toContain('econ_preflight');
    expect(commands).not.toContain('econ_train');
    expect(commands).not.toContain('econ_train_start');
    expect(get(isComputing)).toBe(false);
  });

  it('сквозной: экспресс на парах → возврат в проект → 4 канала, «устарела» нет (физические – медиа, выключены картой, не ролью)', async () => {
    const CONTROL = ['competitor_trp', 'price_index', 'category_sales'];
    const saved = { status: 'ok', file: { rows: 48 }, columns: columns() };
    /** @type {any} */ (invoke).mockImplementation(async (/** @type {string} */ cmd) => {
      if (cmd === 'project_load_results') return { validation: saved, modelDiagnostics: { r2: 0.9 } };
      return null;
    });
    validateData.set(/** @type {any} */ ({ result: null, correlationMatrix: null, columnHistograms: null }));
    lastTrainedConfig.set({ kpi: 'sales_rub', media: [...MONEY], control: CONTROL });
    // Проект, сохранённый после экспресса и обучения: роли не исключались, развязка – в карте.
    activeProject.set(/** @type {any} */ ({
      id: 'e2e-express',
      analysis_mode: 'roi',
      kpi_column: 'sales_rub',
      media_columns: MONEY,
      control_columns: CONTROL,
      excluded_columns: [],
      per_channel_input: Object.fromEntries(MONEY.map((n) => [n, 'monetary'])),
      model_channel_enabled: {
        ...Object.fromEntries(MONEY.map((n) => [n, true])),
        ...Object.fromEntries(PHYS.map((n) => [n, false])),
      },
    }));
    activeProjectId.set('e2e-express');
    await new Promise((resolve) => setTimeout(resolve, 0));

    const result = validateResult();
    // Физические половины остались в роли media – выключает их карта.
    expect(result.columns.filter((/** @type {any} */ c) => c.role === 'media').length).toBe(8);
    expect(/** @type {any} */ (get(validationHeaderMetrics)).activeMedia).toBe(4);
    expect(get(modelStaleStatus)).toMatchObject({ stale: false, diff: [] });

    const { container } = render(ConfigPanel, { props: { validation: result } });
    await settle();
    expect(checkedNames(container)).toEqual(MONEY);
    expect(get(modelStaleStatus)).toMatchObject({ stale: false, diff: [] });
    // Хранитель «Валидации» проходит, гейт обучения держит включённую физическую половину.
    expect(cppSatisfied(currentGateSnapshot())).toBe(true);
    expect(analysisModeIsPersisted()).toBe(true);
    expect(trainGateBlocks([...MONEY, 'ooh_contacts'])).toBe(true);

    lastTrainedConfig.set(null);
    modelData.set(/** @type {any} */ ({ diagnostics: null, channelParams: null, picklePath: null, normalization: null }));
  });
});

/**
 * Круг 2, А-2 (живой проход П12): кнопка «Далее ▶» режима менеджера на «Метриках
 * каналов» была заперта гейтом, считавшим включёнными обе половины каждой пары, а
 * выключает физические половины только её же нажатие. Гейт кнопки – по плану развязки.
 */
describe('А-2: гейт кнопки «Далее ▶» по плану развязки пар', () => {
  const byChannel = () => groupChannelColumns([...MONEY, ...PHYS]).byChannel;
  const bases = () => Object.keys(byChannel());
  /** @param {'monetary'|'physical'} metric */
  const allAs = (metric) => /** @type {Record<string, 'monetary'|'physical'>} */ (
    Object.fromEntries(bases().map((b) => [b, metric])));
  const roi = { perChannelInput: {}, unitCosts: {}, analysisMode: 'roi' };

  it('парный набор, записей о метрике ещё нет, ROI → план проходит (кнопка открыта)', () => {
    expect(bases().length).toBe(4);
    expect(cppSatisfiedForPairPlan(byChannel(), allAs('monetary'), roi)).toBe(true);
    // Прежний признак на том же состоянии закрыт – это и был замкнутый круг.
    expect(cppSatisfied({ channels: [...MONEY, ...PHYS], ...roi })).toBe(false);
  });

  it('выбор по базам не задан → по умолчанию деньги там, где есть денежная половина', () => {
    expect(cppSatisfiedForPairPlan(byChannel(), {}, roi)).toBe(true);
    expect(cppSatisfiedForPairPlan(byChannel(), null, roi)).toBe(true);
  });

  it('одиночный физический канал без цены держит кнопку закрытой, с ценой – открывает', () => {
    const groups = groupChannelColumns([...MONEY, ...PHYS, 'radio_trp']).byChannel;
    const sel = { ...allAs('monetary'), radio: /** @type {'monetary'} */ ('monetary') };
    expect(cppSatisfiedForPairPlan(groups, sel, roi)).toBe(false);
    expect(cppSatisfiedForPairPlan(groups, sel, { ...roi, unitCosts: { radio_trp: 900 } })).toBe(true);
  });

  it('одиночный физический канал с именем вне запасного набора шаблонов (radio_reach) – тоже закрыто', () => {
    const groups = groupChannelColumns([...MONEY, 'radio_reach']).byChannel;
    expect(cppSatisfiedForPairPlan(groups, {}, roi)).toBe(false);
    expect(cppSatisfiedForPairPlan(groups, {}, { ...roi, unitCosts: { radio_reach: 5 } })).toBe(true);
  });

  it('выбранная физическая половина без цены держит кнопку закрытой, с ценой – открывает', () => {
    const sel = { ...allAs('monetary'), tv: /** @type {'physical'} */ ('physical') };
    expect(cppSatisfiedForPairPlan(byChannel(), sel, roi)).toBe(false);
    expect(cppSatisfiedForPairPlan(byChannel(), sel, { ...roi, unitCosts: { tv_trp: 1500 } })).toBe(true);
    // Цена у ДРУГОЙ колонки не помогает.
    expect(cppSatisfiedForPairPlan(byChannel(), sel, { ...roi, unitCosts: { tv_spend: 1500 } })).toBe(false);
  });

  it('устаревшая запись «физическая» у выключаемой половины план не закрывает', () => {
    // Раньше для ТВ выбирали физическую метрику, теперь план – деньги: tv_trp выключается.
    const stores = { ...roi, perChannelInput: { tv_trp: 'physical' } };
    expect(cppSatisfiedForPairPlan(byChannel(), allAs('monetary'), stores)).toBe(true);
  });

  it('план судит по метрике, которую применит нажатие: устаревшая запись «деньги» у выбираемой физической половины не открывает кнопку', () => {
    // Раньше tv_trp помечали «деньги» (колонка уже в рублях), теперь план – физическая
    // метрика для ТВ: нажатие запишет tv_trp = 'physical', и хранитель потребует цену.
    const sel = { ...allAs('monetary'), tv: /** @type {'physical'} */ ('physical') };
    const stores = { ...roi, perChannelInput: { tv_trp: 'monetary' } };
    expect(cppSatisfiedForPairPlan(byChannel(), sel, stores)).toBe(false);
    expect(cppSatisfiedForPairPlan(byChannel(), sel, { ...stores, unitCosts: { tv_trp: 1500 } })).toBe(true);
  });

  it('режим «Эффективность»: физические без цены допустимы', () => {
    expect(cppSatisfiedForPairPlan(byChannel(), allAs('physical'), { ...roi, analysisMode: 'effectiveness' })).toBe(true);
    expect(cppSatisfiedForPairPlan(byChannel(), allAs('physical'), roi)).toBe(false);
  });

  it('проводка: кнопка и нажатие судят один и тот же план', () => {
    // Признак кнопки – по плану; выбор по базам строится одним местом.
    expect(validateStepSrc).toMatch(/const managerPlanConfigured = \$derived\(cppSatisfiedForPairPlan\(\s*availableMetricsByChannel,\s*managerBaseSelection,/);
    expect(validateStepSrc).toMatch(/function confirmMetricsAndProceed\(\) \{\s*handlePerChannelConfirm\(managerBaseSelection\);\s*\}/);
    const from = validateStepSrc.indexOf('onclick={confirmMetricsAndProceed}');
    const button = validateStepSrc.slice(from, validateStepSrc.indexOf('Далее ▶', from));
    expect(button).toMatch(/disabled=\{!managerPlanConfigured\}/);
    expect(button).toMatch(/title=\{managerPlanConfigured\s*\?/);
    expect(button).not.toMatch(/allChannelsConfigured/);
    // Выбор по базам учитывает сохранённый выбор пары (то же правило, что у сводки).
    expect(validateStepSrc).toMatch(/const t = selectionByBase\[name\] \?\? \$perChannelInput\?\.\[name\] \?\? detectChannelType\(name\);/);
    // Перезапирание «Модели» по-прежнему судит прежний признак.
    expect(validateStepSrc).toMatch(/shouldRelockModel\(\{ subStep, cppSatisfied: allChannelsConfigured,/);
  });
});

/**
 * Круг 3, А3-1 (аудит К2-1, К2-2): разбор пар не мягче детектора. Имя, физическое
 * для детектора шаблонов, но неизвестное разбору пар (`olv_views`: слова view в
 * разборе пар нет), группировка клала в «денежные»; план развязки писал колонке
 * явное 'monetary' – кнопка менеджера и экспресс пропускали просмотры как рубли.
 */
describe('А3-1: разбор пар не мягче детектора шаблонов (olv_views)', () => {
  const isPhysical = (/** @type {string} */ name) => detectChannelUnitType(name) === 'physical';
  const VIEWS_COLS = () => [
    { name: 'date', role: 'date' },
    { name: 'sales_rub', role: 'kpi' },
    { name: 'tv_spend', role: 'media', stats: { zeros_pct: 0 } },
    { name: 'olv_views', role: 'media', stats: { zeros_pct: 0 } },
  ];
  const roi = { perChannelInput: {}, unitCosts: {}, analysisMode: 'roi' };
  /** Выбор по базам – как managerBaseSelection экрана при пустом perChannelInput. @param {string[]} bases */
  const managerSel = (bases) => /** @type {Record<string, 'monetary'|'physical'>} */ (
    Object.fromEntries(bases.map((b) => [b, isPhysical(b) ? 'physical' : 'monetary'])));

  it('предпосылка: olv_views – физическая для детектора, без метрики для разбора пар', () => {
    expect(detectChannelUnitType('olv_views')).toBe('physical');
    // Без классификатора – прежнее поведение (колонка считается денежной).
    expect(groupChannelColumns(['tv_spend', 'olv_views']).byChannel.olv_views)
      .toEqual({ monetary: ['olv_views'], physical: [] });
  });

  it('с классификатором olv_views – канал с одной физической колонкой', () => {
    const { byChannel, channels } = groupChannelColumns(['tv_spend', 'olv_views', 'youtube_views'], isPhysical);
    expect(channels).toEqual(['tv', 'olv_views', 'youtube_views']);
    expect(byChannel.olv_views).toEqual({ monetary: [], physical: ['olv_views'] });
    expect(byChannel.youtube_views).toEqual({ monetary: [], physical: ['youtube_views'] });
    expect(byChannel.tv).toEqual({ monetary: ['tv_spend'], physical: [] });
  });

  it('классификатор не перекрывает распознанный суффикс и не трогает парный встроенный набор', () => {
    const plain = groupChannelColumns([...MONEY, ...PHYS]);
    const withDetector = groupChannelColumns([...MONEY, ...PHYS], isPhysical);
    expect(withDetector).toEqual(plain);
    // Классификатор «всё физическое» распознанные денежные суффиксы не переворачивает.
    expect(groupChannelColumns(['tv_spend', 'tv_trp'], () => true).byChannel.tv)
      .toEqual({ monetary: ['tv_spend'], physical: ['tv_trp'] });
    // Имя без суффикса и не физическое по детектору – по-прежнему денежное.
    expect(groupChannelColumns(['Радио'], isPhysical).byChannel['Радио']).toEqual({ monetary: ['Радио'], physical: [] });
  });

  it('К2-1: кнопка «Далее ▶» менеджера закрыта, пока у olv_views нет цены единицы (ROI)', () => {
    const { byChannel, channels } = groupChannelColumns(['tv_spend', 'olv_views'], isPhysical);
    const sel = managerSel(channels);
    // Прежний признак кнопки (2.5.9 и круг 1) на этом состоянии закрыт:
    expect(cppSatisfied({ channels: ['tv_spend', 'olv_views'], ...roi })).toBe(false);
    // Признак по плану обязан быть не мягче:
    expect(cppSatisfiedForPairPlan(byChannel, sel, roi)).toBe(false);
    expect(cppSatisfiedForPairPlan(byChannel, sel, { ...roi, unitCosts: { olv_views: 0.35 } })).toBe(true);
    // Даже если выбор по базе ошибочно скажет «деньги» – денежной колонки у канала нет.
    expect(cppSatisfiedForPairPlan(byChannel, { tv: 'monetary', olv_views: 'monetary' }, roi)).toBe(false);
    expect(cppSatisfiedForPairPlan(byChannel, {}, roi)).toBe(false);
    // «Эффективность» цену не требует.
    expect(cppSatisfiedForPairPlan(byChannel, sel, { ...roi, analysisMode: 'effectiveness' })).toBe(true);
  });

  it('К2-2: экспресс не предлагается, если среди медиа есть физическая по детектору колонка без денежной пары', () => {
    const plan = buildExpressPlan({
      validateResult: { status: 'ok', columns: VIEWS_COLS() },
      currentKPI: 'sales', kpiUnavailable: false, kpiKind: 'monetary',
      isPhysicalChannel: isPhysical,
    });
    expect(plan.eligible).toBe(false);
    expect(plan.uniform.olv_views).toBeUndefined();
    expect(plan.reason).toContain('olv_views');
  });

  it('экспресс на парном встроенном наборе с классификатором – как прежде: предлагается, 4 денежных, 4 выключаются', () => {
    const plan = buildExpressPlan({
      validateResult: validateResult(), currentKPI: 'sales', kpiUnavailable: false, kpiKind: 'monetary',
      isPhysicalChannel: isPhysical,
    });
    expect(plan.eligible).toBe(true);
    expect(Object.keys(plan.uniform)).toEqual(MONEY);
    expect([...plan.disable].sort()).toEqual([...PHYS].sort());
  });

  it('проводка: классификатор передан в группировку экрана и в план экспресса', () => {
    expect(pipelinePageSrc).toMatch(/void \$patternsReady;\s*return groupChannelColumns\(media, \(name\) => detectChannelUnitType\(name\) === 'physical'\);/);
    expect(validateStepSrc).toMatch(/const expressPlan = \$derived\(buildExpressPlan\(\{[\s\S]{0,500}isPhysicalChannel: expressIsPhysical,/);
    expect(validateStepSrc).toMatch(/const expressIsPhysical = \$derived\.by\(\(\) => \{\s*void \$patternsReady;\s*return \([^)]*\) => detectChannelType\(name\) === 'physical';/);
  });
});

/**
 * Круг 2, А-3 и А-4: обновления карты включённости на «Валидации» – цепочкой тех
 * же чистых функций, которые зовёт экран (а не ручной сборкой состояния).
 */
describe('А-3 / А-4: карта включённости после экспресса и после «Далее»', () => {
  const byChannel = () => groupChannelColumns([...MONEY, ...PHYS]).byChannel;
  const allTrue = () => Object.fromEntries([...MONEY, ...PHYS].map((n) => [n, true]));
  const enabledNames = (/** @type {Record<string, boolean>} */ map) =>
    Object.entries(map).filter(([, v]) => v).map(([k]) => k).sort();
  const expressDisable = () => buildExpressPlan({
    validateResult: validateResult(), currentKPI: 'sales', kpiUnavailable: false, kpiKind: 'monetary',
  }).disable;

  it('А-3: «физическая для ТВ → экспресс» возвращает денежную половину: tv_spend true, tv_trp false, каналов 4', () => {
    // Шаг 1: «Далее» на «Метриках каналов» с физической метрикой для ТВ.
    const sel = /** @type {Record<string, 'monetary'|'physical'>} */ ({
      tv: 'physical', digital: 'monetary', ooh: 'monetary', performance: 'monetary',
    });
    const afterManual = applyPairSelectionToEnabledMap(allTrue(), byChannel(), sel);
    expect(afterManual.tv_spend).toBe(false);
    expect(afterManual.tv_trp).toBe(true);
    // Шаг 2: экспресс.
    const afterExpress = applyExpressPairPlan(afterManual, byChannel(), expressDisable());
    expect(afterExpress.tv_spend).toBe(true);
    expect(afterExpress.tv_trp).toBe(false);
    expect(enabledNames(afterExpress)).toEqual([...MONEY].sort());
    expect(enabledNames(afterExpress).length).toBe(4);
    // Хранитель на этой карте открывает «Модель».
    perChannelInput.set(Object.fromEntries(MONEY.map((n) => [n, 'monetary'])));
    modelChannelEnabled.set(afterExpress);
    expect(completeStep(1)).toBe(true);
  });

  it('А-3: экспресс не мутирует исходную карту и не трогает одиночные каналы', () => {
    const groups = groupChannelColumns([...MONEY, ...PHYS, 'radio_spend']).byChannel;
    const before = { ...allTrue(), tv_spend: false, radio_spend: false };
    const snapshot = { ...before };
    const after = applyExpressPairPlan(before, groups, PHYS);
    expect(before).toEqual(snapshot);
    expect(after.radio_spend).toBe(false); // одиночный: снят галочкой – так и остаётся
    expect(after.tv_spend).toBe(true);
  });

  it('А-3 проводка: экспресс применяет карту через applyExpressPairPlan', () => {
    const start = validateStepSrc.indexOf('function expressConfirmAll()');
    const body = validateStepSrc.slice(start, validateStepSrc.indexOf('let prevSubStepIdx', start));
    expect(body).toMatch(/modelChannelEnabled\.update\(\(mapping\) =>\s*applyExpressPairPlan\(mapping, availableMetricsByChannel, expressPlan\.disable\)\);\s*persistPairToggles\(\);/);
    expect(body).not.toMatch(/next\[col\] = false/);
  });

  it('А-4: «Далее» не включает одиночный канал с false в карте; у пары – выбранная true, вторая false', () => {
    const groups = groupChannelColumns([...MONEY, ...PHYS, 'radio_spend', 'promo_trp']).byChannel;
    // radio_spend автоотключён (разреженный), promo_trp снят галочкой на «Модели».
    const before = { ...allTrue(), radio_spend: false, promo_trp: false, tv_spend: false, tv_trp: false };
    const sel = /** @type {Record<string, 'monetary'|'physical'>} */ ({
      tv: 'monetary', digital: 'physical', ooh: 'monetary', performance: 'monetary',
      radio: 'monetary', promo: 'physical',
    });
    const after = applyPairSelectionToEnabledMap(before, groups, sel);
    expect(after.radio_spend).toBe(false);
    expect(after.promo_trp).toBe(false);
    expect(after.tv_spend).toBe(true);
    expect(after.tv_trp).toBe(false);
    expect(after.digital_impressions).toBe(true);
    expect(after.digital_spend).toBe(false);
    expect(before.tv_spend).toBe(false); // исходная карта не мутирована
  });

  it('А-4: одиночный канал без записи в карте записи не получает; включённый остаётся включённым', () => {
    const groups = groupChannelColumns(['tv_spend', 'tv_trp', 'radio_spend', 'press_spend']).byChannel;
    const after = applyPairSelectionToEnabledMap({ press_spend: true }, groups, {});
    expect('radio_spend' in after).toBe(false);
    expect(after.press_spend).toBe(true);
    expect(after).toEqual({ press_spend: true, tv_spend: true, tv_trp: false });
  });

  it('А-4 проводка: «Далее» применяет карту через applyPairSelectionToEnabledMap', () => {
    const start = validateStepSrc.indexOf('function handlePerChannelConfirm(');
    const body = validateStepSrc.slice(start, validateStepSrc.indexOf('async function handleContinue()', start));
    expect(body).toMatch(/modelChannelEnabled\.update\(\(mapping\) =>\s*applyPairSelectionToEnabledMap\(mapping, availableMetricsByChannel, baseSel\)\);/);
    expect(body).not.toMatch(/next\[col\] = true/);
  });
});

/**
 * Отказ хранителя не молчаливый (сторожа по исходнику). До правки оба пути звали
 * `completeStep(1)` и безусловно переходили на «Подтверждение»: экран показан,
 * «Модель» заперта, подсказка подвала отсылает к кнопке, которой в секции нет.
 */
describe('отказ хранителя виден пользователю (сторожа по исходнику)', () => {
  /** Тело функции без строк-комментариев. @param {string} from @param {string} to */
  function codeBetween(from, to) {
    const start = validateStepSrc.indexOf(from);
    const end = validateStepSrc.indexOf(to, start);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    return validateStepSrc.slice(start, end)
      .split('\n')
      .filter((/** @type {string} */ line) => !line.trim().startsWith('//'))
      .join('\n');
  }

  it('экспресс: при отказе – подшаг «Метрики каналов» с баннером, не «Подтверждение»', () => {
    const body = codeBetween('function expressConfirmAll()', 'let prevSubStepIdx');
    expect(body).toMatch(
      /if \(!completeStep\(1\)\) \{\s*subStep = 2;\s*expertCppMissing = true;\s*return;\s*\}\s*subStep = 3;/,
    );
    // Результат хранителя не выбрасывается: голого вызова-оператора нет.
    expect(body).not.toMatch(/^\s*completeStep\(1\);/m);
  });

  it('«Далее» на «Метриках каналов»: при отказе остаёмся на подшаге с баннером', () => {
    const body = codeBetween('function handlePerChannelConfirm(', 'async function handleContinue()');
    expect(body).toMatch(
      /if \(!completeStep\(1\)\) \{\s*expertCppMissing = true;\s*return;\s*\}\s*subStep = 3;/,
    );
    expect(body).not.toMatch(/^\s*completeStep\(1\);/m);
  });

  it('баннер про цену единицы рисуется на подшаге 2 – туда и ведёт отказ', () => {
    const tpl = validateStepSrc.slice(
      validateStepSrc.indexOf('{:else if subStep === 2}'),
      validateStepSrc.indexOf('{:else if subStep === 3}'),
    );
    expect(tpl).toMatch(/\{#if expertCppMissing\}/);
  });

  it('подсказка подвальной «Далее ▶» на «Подтверждении» не отсылает к несуществующей кнопке', () => {
    expect(pipelineLayoutSrc).toMatch(
      /\$validateSubStep === 3\s*\?\s*'Обучение пока закрыто: вернитесь к подшагу «Метрики каналов» и завершите настройку каналов'\s*:\s*'Завершите подшаги валидации – кнопка продолжения в секции ниже'/,
    );
  });
});

describe('А1: гидрация карты включённости из проекта – только при смене проекта', () => {
  it('открытие проекта ставит карту из project.json', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A', model_channel_enabled: { tv_spend: true, tv_trp: false } }));
    expect(get(modelChannelEnabled)).toEqual({ tv_spend: true, tv_trp: false });
  });

  it('повторный activeProject.set того же id со СТАРОЙ картой не затирает живую', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A', model_channel_enabled: { tv_spend: true, tv_trp: true } }));
    // Пользователь снял галочку на «Модели» (на диск карта уйдёт только при обучении).
    modelChannelEnabled.set({ tv_spend: true, tv_trp: false });
    // Панель праздников/цен единицы положила в стор ответ project_update со старой картой.
    activeProject.set(/** @type {any} */ ({ id: 'A', model_channel_enabled: { tv_spend: true, tv_trp: true }, use_holidays: false }));
    expect(get(modelChannelEnabled)).toEqual({ tv_spend: true, tv_trp: false });
  });

  it('смена проекта A→B сбрасывает карту (B без поля → {})', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A', model_channel_enabled: { tv_trp: false } }));
    expect(get(modelChannelEnabled)).toEqual({ tv_trp: false });
    activeProject.set(/** @type {any} */ ({ id: 'B' }));
    expect(get(modelChannelEnabled)).toEqual({});
  });

  it('смена проекта A→B ставит карту B, а не смесь с A', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A', model_channel_enabled: { tv_trp: false, radio: false } }));
    activeProject.set(/** @type {any} */ ({ id: 'B', model_channel_enabled: { tv_trp: true } }));
    expect(get(modelChannelEnabled)).toEqual({ tv_trp: true });
  });

  it('пустая карта проекта = сброс чужой карты', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A', model_channel_enabled: { tv_trp: false } }));
    activeProject.set(/** @type {any} */ ({ id: 'B', model_channel_enabled: {} }));
    expect(get(modelChannelEnabled)).toEqual({});
  });

  it('деселект (!p) → {} и запомненный id сброшен (повторное открытие того же проекта гидрирует заново)', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A', model_channel_enabled: { tv_trp: false } }));
    activeProject.set(null);
    expect(get(modelChannelEnabled)).toEqual({});
    activeProject.set(/** @type {any} */ ({ id: 'A', model_channel_enabled: { tv_trp: false } }));
    expect(get(modelChannelEnabled)).toEqual({ tv_trp: false });
  });

  it('чужая карта прежнего проекта не прячет от хранителя физический канал нового', () => {
    // Проект A: физическая половина tv_trp выключена. Проект B (свежий) с тем же
    // именем колонки: карта сброшена → tv_trp считается включённым → без цены стоп.
    activeProject.set(/** @type {any} */ ({ id: 'A', model_channel_enabled: { tv_trp: false } }));
    activeProject.set(/** @type {any} */ ({ id: 'B' }));
    setColumns([{ name: 'sales_rub', role: 'kpi' }, { name: 'tv_trp', role: 'media' }]);
    perChannelInput.set({});
    expect(completeStep(1)).toBe(false);
    expect(status()[2]).toBe('locked');
  });
});
