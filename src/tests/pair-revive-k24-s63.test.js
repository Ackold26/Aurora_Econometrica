/**
 * s63 (К2-4): физическая метрика, выключенная развязкой пар, включается обратно,
 * когда пользователь исключил денежную половину на «Ролях колонок».
 *
 * Дефект 2.5.10: «Далее» (развязка: денежная половина остаётся, физическая
 * выключается) → «Роли колонок» → исключить tv_spend → «Далее» → «Модель» открывается
 * с выключенной tv_trp. Канал с данными и ролью «медиа» молча отсутствует в модели,
 * обучение проходит без ошибки (смещение от пропущенной переменной).
 *
 * Правило (решение владельца, не пересматривать): различать, КТО выключил.
 *  1. Причина «выключено развязкой» помнится вне карты панели (стор pairToggleReasons).
 *  2. Ручная галочка пользователя снимает признак – его выбор не перезаписывается.
 *  3. Разреженная колонка (нулей > 80 %) остаётся выключенной – другая причина.
 *  4. Гейт цены единицы не ослабляется; запас данных в шапке – по включённым каналам.
 *
 * Экран «Валидация» в тестах целиком не отрисовывается: развязка воспроизводится той
 * же цепочкой, что у экрана (applyPairSelectionToEnabledMap / applyExpressPairPlan +
 * notePairDecoupling), смена роли – тем же setColumnRolesBulk, что у handleRoleChange.
 * Панель обучения отрисовывается настоящая.
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
  importData, chosenKpiColumn, isComputing, computeStatus, expertMode,
  cppSatisfied, cppSatisfiedForPairPlan, applyExpressPairPlan, applyPairSelectionToEnabledMap,
  validationHeaderMetrics, isModelColumnEnabled,
  pairToggleReasons, notePairDecoupling, forgetPairToggleReason, revivedHalvesNote,
} from '$lib/project-state.js';
import { buildExpressPlan } from '$lib/express-validate.js';
import { groupChannelColumns, resolvePairSelection } from '$lib/channel-pairs.js';
import { setColumnRolesBulk } from '$lib/column-roles.js';
import validateStepSrc from '$lib/components/pipeline/ValidateStepV13.svelte?raw';
import configPanelSrc from '$lib/components/ConfigPanel.svelte?raw';

const PHYS = ['tv_trp', 'digital_impressions', 'ooh_contacts', 'performance_clicks'];
const MONEY = ['tv_spend', 'digital_spend', 'ooh_spend', 'performance_spend'];

/** Парный демо-набор: 4 бюджетных + 4 физических + контроль. @param {Record<string, number>} [zeros] */
function columns(zeros = {}) {
  return [
    { name: 'date', role: 'date' },
    { name: 'sales_rub', role: 'kpi' },
    ...MONEY.map((name) => ({ name, role: 'media', stats: { zeros_pct: zeros[name] ?? 0 } })),
    ...PHYS.map((name) => ({ name, role: 'media', stats: { zeros_pct: zeros[name] ?? 0 } })),
    { name: 'price_index', role: 'control' },
  ];
}

/** @param {any[]} cols */
function setColumns(cols) {
  validateData.set(/** @type {any} */ ({
    result: { status: 'ok', columns: cols, file: { rows: 104 } }, correlationMatrix: null, columnHistograms: null,
  }));
}

/** @returns {any[]} */
const currentColumns = () => /** @type {any} */ (get(validateData)).result.columns;

/** Группировка экрана (pipeline/+page.svelte) по текущим медиа-колонкам. */
const byChannel = () => groupChannelColumns(
  currentColumns().filter((c) => c.role === 'media').map((c) => c.name),
).byChannel;

/** Выбор по базам: по умолчанию деньги, с правками. @param {Record<string, 'monetary'|'physical'>} [over] */
const selection = (over = {}) => /** @type {Record<string, 'monetary'|'physical'>} */ ({
  tv: 'monetary', digital: 'monetary', ooh: 'monetary', performance: 'monetary', ...over,
});

/** «Далее» на «Метриках каналов» – та же цепочка, что handlePerChannelConfirm. @param {Record<string, 'monetary'|'physical'>} sel */
function pressNext(sel) {
  const groups = byChannel();
  perChannelInput.set(resolvePairSelection(groups, sel).perColumn);
  const beforeDecoupling = get(modelChannelEnabled);
  modelChannelEnabled.update((mapping) => applyPairSelectionToEnabledMap(mapping, groups, sel));
  notePairDecoupling(beforeDecoupling);
}

/** Смена роли колонки на «Ролях колонок» – как handleRoleChange. @param {string} name @param {string} role */
function setRole(name, role) {
  setColumns(setColumnRolesBulk(currentColumns(), [name], role));
}

const status = () => get(pipelineStepMeta).map((s) => s.status);
const enabledNames = () => Object.entries(get(modelChannelEnabled)).filter(([, v]) => v).map(([k]) => k).sort();

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
  modelChannelEnabled.set(Object.fromEntries([...MONEY, ...PHYS].map((n) => [n, true])));
  pairToggleReasons.set({});
  analysisMode.set('roi');
  /** @type {any} */ (invoke).mockClear();
});

afterEach(() => {
  activeProject.set(null);
  activeProjectId.set(null);
  pairToggleReasons.set({});
});

describe('К2-4 п.1: причина «выключено развязкой» и включение, когда посылка исчезла', () => {
  it('развязка помечает ровно выключенные ею физические половины', () => {
    pressNext(selection());
    expect(enabledNames()).toEqual([...MONEY].sort());
    expect(get(pairToggleReasons)).toEqual(Object.fromEntries(PHYS.map((n) => [n, 'off'])));
  });

  it('исключили tv_spend → tv_trp включается, остальные физические половины остаются выключенными', () => {
    pressNext(selection());
    setRole('tv_spend', 'unused');
    const map = get(modelChannelEnabled);
    expect(map.tv_trp).toBe(true);
    for (const n of PHYS.filter((p) => p !== 'tv_trp')) expect(map[n]).toBe(false);
    expect(get(pairToggleReasons).tv_trp).toBe('revived');
  });

  it('повторное «Далее» после исключения не выключает tv_trp (канал больше не пара)', () => {
    pressNext(selection());
    setRole('tv_spend', 'unused');
    pressNext(selection());
    expect(get(modelChannelEnabled).tv_trp).toBe(true);
    // В модель идут включённые МЕДИА-колонки (tv_spend больше не медиа; ключ в карте
    // без панели остаётся, панель его убирает – см. блок с настоящей панелью ниже).
    const enabledMedia = currentColumns()
      .filter((c) => c.role === 'media' && isModelColumnEnabled(get(modelChannelEnabled), c.name))
      .map((c) => c.name).sort();
    expect(enabledMedia).toEqual(['digital_spend', 'ooh_spend', 'performance_spend', 'tv_trp']);
    // Признак «включена обратно» переживает повторное «Далее» – строка про цену не пропадает.
    expect(get(pairToggleReasons).tv_trp).toBe('revived');
  });

  it('развязка, включившая половину (выбрали физическую для ТВ), снимает с неё признак', () => {
    pressNext(selection());
    expect(get(pairToggleReasons).tv_trp).toBe('off');
    pressNext(selection({ tv: 'physical' }));
    expect(get(modelChannelEnabled).tv_trp).toBe(true);
    expect(get(pairToggleReasons).tv_trp).toBeUndefined();
    expect(get(pairToggleReasons).tv_spend).toBe('off');
  });

  it('экспресс-путь: физические половины помечаются так же, исключение tv_spend включает tv_trp', () => {
    const plan = buildExpressPlan({
      validateResult: /** @type {any} */ (get(validateData)).result, currentKPI: 'sales', kpiUnavailable: false, kpiKind: 'monetary',
    });
    expect(plan.eligible).toBe(true);
    const beforeDecoupling = get(modelChannelEnabled);
    modelChannelEnabled.update((mapping) => applyExpressPairPlan(mapping, byChannel(), plan.disable));
    notePairDecoupling(beforeDecoupling);
    expect(get(pairToggleReasons).tv_trp).toBe('off');
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(true);
  });

  it('то же правило в обратную сторону: выбрана физическая, исключили её – денежная половина возвращается', () => {
    pressNext(selection({ tv: 'physical' }));
    expect(get(modelChannelEnabled).tv_spend).toBe(false);
    setRole('tv_trp', 'unused');
    expect(get(modelChannelEnabled).tv_spend).toBe(true);
  });

  it('пара не развязана (обе половины в проекте) – смена другой роли карту не меняет, как в 2.5.10', () => {
    pressNext(selection());
    const before = { ...get(modelChannelEnabled) };
    setRole('price_index', 'unused');
    expect(get(modelChannelEnabled)).toEqual(before);
    expect(get(pairToggleReasons).tv_trp).toBe('off');
    // Исключили физическую половину другого канала – его денежная половина и так включена.
    setRole('digital_impressions', 'unused');
    expect(get(modelChannelEnabled)).toEqual(before);
  });

  it('вернули tv_spend в медиа и нажали «Далее» – пара снова развязана, tv_trp снова выключена развязкой', () => {
    pressNext(selection());
    setRole('tv_spend', 'unused');
    setRole('tv_spend', 'media');
    pressNext(selection());
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
    expect(get(modelChannelEnabled).tv_spend).toBe(true);
    expect(get(pairToggleReasons).tv_trp).toBe('off');
  });

  it('смена проекта сбрасывает признаки: в другом проекте исключение tv_spend ничего не включает', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A' }));
    modelChannelEnabled.set(Object.fromEntries([...MONEY, ...PHYS].map((n) => [n, true])));
    pressNext(selection());
    expect(get(pairToggleReasons).tv_trp).toBe('off');
    activeProject.set(/** @type {any} */ ({ id: 'B', model_channel_enabled: { tv_spend: true, tv_trp: false } }));
    expect(get(pairToggleReasons)).toEqual({});
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
  });

  it('включатель трогает только «off» и только при явном false в карте (защитные условия)', () => {
    // Признак 'revived' у выключенной колонки сам по себе её не включает.
    pairToggleReasons.set({ tv_trp: 'revived' });
    modelChannelEnabled.set({ tv_trp: false });
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
    // 'off' без явного false в карте: карта и признак не меняются.
    setRole('tv_spend', 'media');
    pairToggleReasons.set({ tv_trp: 'off' });
    modelChannelEnabled.set({});
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled)).toEqual({});
    expect(get(pairToggleReasons).tv_trp).toBe('off');
  });

  it('закрытие проекта (деселект) сбрасывает признаки', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A' }));
    modelChannelEnabled.set(Object.fromEntries([...MONEY, ...PHYS].map((n) => [n, true])));
    pressNext(selection());
    activeProject.set(null);
    expect(get(pairToggleReasons)).toEqual({});
  });

  it('тот же проект (промежуточный activeProject.set) признаки не сбрасывает', () => {
    activeProject.set(/** @type {any} */ ({ id: 'A' }));
    modelChannelEnabled.set(Object.fromEntries([...MONEY, ...PHYS].map((n) => [n, true])));
    pressNext(selection());
    activeProject.set(/** @type {any} */ ({ id: 'A', use_holidays: false }));
    expect(get(pairToggleReasons).tv_trp).toBe('off');
  });
});

describe('К2-4 п.2: выбор пользователя не перезаписывается', () => {
  it('выключил сам ДО развязки → признака нет → исключил tv_spend → tv_trp остаётся выключенной', () => {
    modelChannelEnabled.update((m) => ({ ...m, tv_trp: false }));
    pressNext(selection());
    expect(get(pairToggleReasons).tv_trp).toBeUndefined();
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
  });

  it('ручное переключение снимает признак (forgetPairToggleReason) → исключение tv_spend канал не включает', () => {
    pressNext(selection());
    forgetPairToggleReason('tv_trp');
    expect(get(pairToggleReasons).tv_trp).toBeUndefined();
    expect(get(pairToggleReasons).digital_impressions).toBe('off');
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
  });

  it('пользователь выключил включённую обратно половину – она остаётся выключенной при следующих сменах ролей', () => {
    pressNext(selection());
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(true);
    forgetPairToggleReason('tv_trp');
    modelChannelEnabled.update((m) => ({ ...m, tv_trp: false }));
    setRole('price_index', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
  });
});

describe('К2-4 п.3: разреженная колонка остаётся выключенной', () => {
  it('разреженная tv_trp, выключенная до развязки (сторож), признака не получает и не включается', () => {
    setColumns(columns({ tv_trp: 85 }));
    modelChannelEnabled.update((m) => ({ ...m, tv_trp: false }));
    pressNext(selection());
    expect(get(pairToggleReasons).tv_trp).toBeUndefined();
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
  });

  it('разреженная tv_trp с признаком развязки (карты не было) – после исключения tv_spend всё равно выключена', () => {
    setColumns(columns({ tv_trp: 85 }));
    modelChannelEnabled.set({});
    pressNext(selection());
    expect(get(pairToggleReasons).tv_trp).toBe('off');
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
  });

  it('граница: ровно 80 % нулей – не разреженная, включается', () => {
    setColumns(columns({ tv_trp: 80 }));
    pressNext(selection());
    setRole('tv_spend', 'unused');
    expect(get(modelChannelEnabled).tv_trp).toBe(true);
  });
});

describe('К2-4 п.4: гейт цены единицы не ослаблен, запас данных – по включённым каналам', () => {
  it('включённая tv_trp без цены: хранитель «Модели» закрыт; с ценой – открыт', () => {
    pressNext(selection());
    setRole('tv_spend', 'unused');
    expect(completeStep(1)).toBe(false);
    expect(status()[2]).toBe('locked');
    unitCosts.set({ tv_trp: 270000 });
    expect(completeStep(1)).toBe(true);
    expect(status()[2]).toBe('ready');
  });

  it('кнопка «Далее ▶» менеджера (план развязки) закрыта без цены tv_trp, открыта с ценой', () => {
    pressNext(selection());
    setRole('tv_spend', 'unused');
    const stores = { perChannelInput: get(perChannelInput), unitCosts: {}, analysisMode: 'roi' };
    expect(cppSatisfiedForPairPlan(byChannel(), selection(), stores)).toBe(false);
    expect(cppSatisfiedForPairPlan(byChannel(), selection(), { ...stores, unitCosts: { tv_trp: 270000 } })).toBe(true);
  });

  it('гейт обучения (каналы, включённые в карте) останавливает tv_trp без цены', () => {
    pressNext(selection());
    setRole('tv_spend', 'unused');
    const enabled = currentColumns()
      .filter((c) => c.role === 'media' && isModelColumnEnabled(get(modelChannelEnabled), c.name))
      .map((c) => c.name);
    expect(enabled).toContain('tv_trp');
    expect(cppSatisfied({ channels: enabled, perChannelInput: get(perChannelInput), unitCosts: {}, analysisMode: 'roi' })).toBe(false);
    expect(cppSatisfied({ channels: enabled, perChannelInput: get(perChannelInput), unitCosts: { tv_trp: 1 }, analysisMode: 'roi' })).toBe(true);
  });

  it('запас данных в шапке считается по новому числу включённых каналов (4, а не 3)', () => {
    pressNext(selection());
    expect(get(validationHeaderMetrics)?.activeMedia).toBe(4);
    setRole('tv_spend', 'unused');
    const metrics = get(validationHeaderMetrics);
    expect(metrics?.activeMedia).toBe(4);
    expect(metrics?.nPredictors).toBe(5); // 4 медиа + price_index
  });

  it('строка подсказки: одна включённая половина без цены → короткая строка с именем колонки', () => {
    pressNext(selection());
    setRole('tv_spend', 'unused');
    const note = revivedHalvesNote(get(pairToggleReasons), {
      modelChannelEnabled: get(modelChannelEnabled), perChannelInput: get(perChannelInput),
      unitCosts: {}, analysisMode: 'roi',
    });
    expect(note).toBe('Включена метрика «tv_trp» вместо исключённых расходов, укажите цену единицы.');
    expect(note).not.toMatch(/—/);
  });

  it('строка подсказки исчезает: цена задана / колонку выключили / режим «Эффективность»; две колонки – множественное число', () => {
    pressNext(selection());
    setRole('tv_spend', 'unused');
    setRole('ooh_spend', 'unused');
    const reasons = get(pairToggleReasons);
    const base = { modelChannelEnabled: get(modelChannelEnabled), perChannelInput: get(perChannelInput), unitCosts: {}, analysisMode: 'roi' };
    expect(revivedHalvesNote(reasons, base))
      .toBe('Включены метрики «tv_trp», «ooh_contacts» вместо исключённых расходов, укажите цену единицы.');
    expect(revivedHalvesNote(reasons, { ...base, unitCosts: { tv_trp: 5, ooh_contacts: 7 } })).toBeNull();
    expect(revivedHalvesNote(reasons, { ...base, unitCosts: { tv_trp: 5 } }))
      .toBe('Включена метрика «ooh_contacts» вместо исключённых расходов, укажите цену единицы.');
    expect(revivedHalvesNote(reasons, { ...base, modelChannelEnabled: { ...base.modelChannelEnabled, tv_trp: false, ooh_contacts: false } })).toBeNull();
    expect(revivedHalvesNote(reasons, { ...base, analysisMode: 'effectiveness' })).toBeNull();
    // Половина с признаком 'off' (развязка в силе) строки не даёт.
    expect(revivedHalvesNote({ digital_impressions: 'off' }, base)).toBeNull();
    // …даже если она включена в карте и без цены (строка – только про включённые обратно).
    expect(revivedHalvesNote({ digital_impressions: 'off' },
      { ...base, modelChannelEnabled: { digital_impressions: true } })).toBeNull();
  });

  it('денежная половина, включённая обратно, цены не требует – строки нет', () => {
    pressNext(selection({ tv: 'physical' }));
    setRole('tv_trp', 'unused');
    expect(revivedHalvesNote(get(pairToggleReasons), {
      modelChannelEnabled: get(modelChannelEnabled), perChannelInput: get(perChannelInput), unitCosts: {}, analysisMode: 'roi',
    })).toBeNull();
  });
});

describe('К2-4 через настоящую панель обучения', () => {
  /** @param {any[]} cols */
  const validation = (cols) => ({ status: 'ok', columns: cols, detected: { date: 'date' } });
  /** @param {HTMLElement} container */
  const checkedNames = (container) => [...container.querySelectorAll('.channel-item')]
    .filter((el) => /** @type {HTMLInputElement} */ (el.querySelector('input[type="checkbox"]')).checked)
    .map((el) => el.querySelector('.channel-name')?.textContent?.trim());
  /** @param {HTMLElement} container @param {string} name */
  const box = (container, name) => /** @type {HTMLInputElement} */ ([...container.querySelectorAll('.channel-item')]
    .find((el) => el.querySelector('.channel-name')?.textContent?.trim() === name)
    ?.querySelector('input[type="checkbox"]'));
  const settle = async () => { for (let i = 0; i < 4; i++) await tick(); };

  beforeEach(() => {
    importData.set(/** @type {any} */ ({ file: null, columns: null, rows: null }));
    chosenKpiColumn.set(null);
    isComputing.set(false);
    computeStatus.set('');
    expertMode.set(false);
    modelChannelEnabled.set({});
  });

  afterEach(() => {
    /** @type {any} */ (invoke).mockReset();
    /** @type {any} */ (invoke).mockResolvedValue(null);
  });

  it('развязка → исключили tv_spend → панель показывает tv_trp включённой (панель пересобрала карту)', async () => {
    const { container, rerender } = render(ConfigPanel, { props: { validation: validation(currentColumns()) } });
    await settle();
    pressNext(selection());
    await settle();
    expect(checkedNames(container)).toEqual(MONEY);

    setRole('tv_spend', 'unused');
    await rerender({ validation: validation(currentColumns()) });
    await settle();

    expect(checkedNames(container)).toEqual(['digital_spend', 'ooh_spend', 'performance_spend', 'tv_trp']);
    expect(get(modelChannelEnabled).tv_trp).toBe(true);
    expect('tv_spend' in get(modelChannelEnabled)).toBe(false); // панель пересобрала карту по медиа
  });

  it('галочка пользователя снимает признак: включил и снова выключил tv_trp → исключение tv_spend её не включает', async () => {
    const { container, rerender } = render(ConfigPanel, { props: { validation: validation(currentColumns()) } });
    await settle();
    pressNext(selection());
    await settle();

    await fireEvent.click(box(container, 'tv_trp'));
    await settle();
    expect(get(pairToggleReasons).tv_trp).toBeUndefined();
    await fireEvent.click(box(container, 'tv_trp'));
    await settle();
    expect(get(modelChannelEnabled).tv_trp).toBe(false);

    setRole('tv_spend', 'unused');
    await rerender({ validation: validation(currentColumns()) });
    await settle();

    expect(checkedNames(container)).toEqual(['digital_spend', 'ooh_spend', 'performance_spend']);
    expect(get(modelChannelEnabled).tv_trp).toBe(false);
  });

  it('галочка другой колонки чужой признак не снимает', async () => {
    const { container } = render(ConfigPanel, { props: { validation: validation(currentColumns()) } });
    await settle();
    pressNext(selection());
    await settle();
    await fireEvent.click(box(container, 'digital_impressions'));
    await settle();
    expect(get(pairToggleReasons).digital_impressions).toBeUndefined();
    expect(get(pairToggleReasons).tv_trp).toBe('off');
  });
});

describe('К2-4 проводка (экран «Валидация» в тестах не отрисовывается)', () => {
  /** @param {string} from @param {string} to */
  const between = (from, to) => {
    const start = validateStepSrc.indexOf(from);
    return validateStepSrc.slice(start, validateStepSrc.indexOf(to, start));
  };

  it('обе развязки запоминают карту ДО и отмечают причину ПОСЛЕ применения', () => {
    for (const body of [
      between('function expressConfirmAll()', 'let prevSubStepIdx'),
      between('function handlePerChannelConfirm(', 'async function handleContinue()'),
    ]) {
      expect(body).toMatch(/const beforeDecoupling = get\(modelChannelEnabled\);\s*modelChannelEnabled\.update\(/);
      expect(body).toMatch(/persistPairToggles\(\);[^\n]*\n(?:\s*\/\/[^\n]*\n)*\s*notePairDecoupling\(beforeDecoupling\);/);
    }
  });

  it('строка «включена метрика …» рисуется на подшаге «Метрики каналов» по revivedHalvesNote', () => {
    const tpl = between('{:else if subStep === 2}', '{:else if subStep === 3}');
    expect(tpl).toMatch(/\{#if revivedNote\}\s*<div[^>]*>\{revivedNote\}<\/div>\s*\{\/if\}/);
    expect(validateStepSrc).toMatch(/const revivedNote = \$derived\(revivedHalvesNote\(\$pairToggleReasons, \{/);
  });

  it('галочка панели обучения снимает признак своей колонки', () => {
    expect(configPanelSrc).toMatch(/bind:checked=\{channelEnabled\[ch\.name\]\} onchange=\{\(\) => forgetPairToggleReason\(ch\.name\)\}/);
  });
});
