/**
 * s63 (К2-3): путь «TRP + цена пункта» в парном файле больше не тупик.
 *
 * Дефект 2.5.10 (подтверждён вживую в s61): сводке «Метрик каналов» передавались
 * БАЗЫ каналов (`tv`), редактор цены писал `unitCosts = {tv: 270000}`, а гейт читает
 * по имени КОЛОНКИ (`tv_trp`) – «Подтвердить выбор →» / «Далее ▶» оставались на
 * подшаге 2. Для одиночного физического канала (`olv_views`) имя колонки совпадает
 * с именем канала – путь работал; его не сломать.
 *
 * Правка: сводке передаются колонки плана развязки (pairPlanSummaryChannels) –
 * того же плана, что судит кнопка; редактор пишет цену под именем колонки.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import AppliedModeSummary from '$lib/components/pipeline/AppliedModeSummary.svelte';
import {
  analysisMode, expertMode, unitCosts, unitCostInflation, unitCostInputMode, budgetInputs,
  perChannelInput, modelChannelEnabled, validateData, pipelineStepMeta, completeStep,
  activeProject, activeProjectId,
  cppSatisfiedForPairPlan, applyPairSelectionToEnabledMap,
  pairPlanSummaryChannels, adoptChannelKeyedUnitCosts,
} from '$lib/project-state.js';
import { patternsReady, detectChannelUnitType } from '$lib/services/classifier-patterns.js';
import { groupChannelColumns, resolvePairSelection } from '$lib/channel-pairs.js';
import validateStepSrc from '$lib/components/pipeline/ValidateStepV13.svelte?raw';

const isPhysical = (/** @type {string} */ name) => detectChannelUnitType(name) === 'physical';
const PAIRED = ['tv_spend', 'tv_trp', 'digital_spend', 'digital_impressions'];
const SUMS = { tv_spend: 9_000_000, tv_trp: 1200, digital_spend: 4_000_000, digital_impressions: 50_000_000, olv_views: 46_000 };

/** @param {string[]} media */
function setMedia(media) {
  validateData.set(/** @type {any} */ ({
    result: {
      status: 'ok',
      columns: [
        { name: 'date', role: 'date' },
        { name: 'sales_rub', role: 'kpi' },
        ...media.map((name) => ({ name, role: 'media', stats: { zeros_pct: 0, sum: /** @type {any} */ (SUMS)[name] } })),
      ],
    },
    correlationMatrix: null, columnHistograms: null,
  }));
}

/** Переключить редактор колонки в режим «Цена 1 ед.» и ввести цену. @param {HTMLElement} container @param {string} column @param {string} value */
async function typeUnitCost(container, column, value) {
  const row = /** @type {HTMLElement} */ (container.querySelector(`[data-testid="uc-editor"][data-channel="${column}"]`));
  expect(row).not.toBeNull();
  const unitBtn = /** @type {Element} */ ([...row.querySelectorAll('.uc-mode-btn')].find((b) => b.textContent?.includes('Цена 1 ед')));
  await fireEvent.click(unitBtn);
  const input = /** @type {HTMLInputElement} */ (row.querySelector('input[type="number"]'));
  await fireEvent.input(input, { target: { value } });
  vi.runAllTimers();
  await Promise.resolve();
}

/** «Подтвердить выбор →» / «Далее ▶» – та же цепочка, что handlePerChannelConfirm. @param {any} byChannel @param {Record<string, 'monetary'|'physical'>} sel */
function confirmSelection(byChannel, sel) {
  perChannelInput.set(resolvePairSelection(byChannel, sel).perColumn);
  modelChannelEnabled.update((m) => applyPairSelectionToEnabledMap(m, byChannel, sel));
  return completeStep(1);
}

const status = () => get(pipelineStepMeta).map((s) => s.status);

beforeEach(() => {
  activeProject.set(null);
  activeProjectId.set(null);
  analysisMode.set('roi');
  expertMode.set(false);
  unitCosts.set({});
  unitCostInflation.set({});
  unitCostInputMode.set({});
  budgetInputs.set({});
  perChannelInput.set({});
  modelChannelEnabled.set({});
  patternsReady.set(true);
  pipelineStepMeta.set([
    { status: 'complete', errorMessage: null },
    { status: 'ready', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
  ]);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('К2-3: сводка и гейт читают одно имя – имя колонки', () => {
  it('парный файл, выбрана физическая половина ТВ: в сводке колонки плана, а не базы', () => {
    const { byChannel } = groupChannelColumns(PAIRED, isPhysical);
    expect(pairPlanSummaryChannels(byChannel, { tv: 'physical', digital: 'monetary' })).toEqual([
      { name: 'tv_trp', detectedType: 'physical' },
      { name: 'digital_spend', detectedType: 'monetary' },
    ]);
  });

  it('парный файл: цена в редакторе пишется под tv_trp, гейт открыт, «Модель» открывается', async () => {
    setMedia(PAIRED);
    const { byChannel } = groupChannelColumns(PAIRED, isPhysical);
    const sel = /** @type {Record<string, 'monetary'|'physical'>} */ ({ tv: 'physical', digital: 'monetary' });
    const { container } = render(AppliedModeSummary, {
      props: { channels: pairPlanSummaryChannels(byChannel, sel), channelSums: SUMS },
    });
    // До цены: гейт кнопки закрыт, есть предупреждение.
    expect(cppSatisfiedForPairPlan(byChannel, sel, { unitCosts: get(unitCosts), analysisMode: 'roi' })).toBe(false);
    expect(container.querySelector('[data-testid="incompat-banner"]')).not.toBeNull();

    await typeUnitCost(container, 'tv_trp', '270000');

    expect(get(unitCosts)).toEqual({ tv_trp: 270000 });
    expect('tv' in get(unitCosts)).toBe(false);
    expect(container.querySelector('[data-testid="incompat-banner"]')).toBeNull();
    expect(cppSatisfiedForPairPlan(byChannel, sel, { unitCosts: get(unitCosts), analysisMode: 'roi' })).toBe(true);
    expect(confirmSelection(byChannel, sel)).toBe(true);
    expect(status()[2]).toBe('ready');
  });

  it('парный файл: цена не введена → гейт закрыт, «Модель» остаётся запертой', () => {
    setMedia(PAIRED);
    const { byChannel } = groupChannelColumns(PAIRED, isPhysical);
    const sel = /** @type {Record<string, 'monetary'|'physical'>} */ ({ tv: 'physical', digital: 'monetary' });
    const { container } = render(AppliedModeSummary, {
      props: { channels: pairPlanSummaryChannels(byChannel, sel), channelSums: SUMS },
    });
    expect(container.querySelector('[data-testid="uc-editor"][data-channel="tv_trp"]')).not.toBeNull();
    expect(cppSatisfiedForPairPlan(byChannel, sel, { unitCosts: {}, analysisMode: 'roi' })).toBe(false);
    expect(confirmSelection(byChannel, sel)).toBe(false);
    expect(status()[2]).toBe('locked');
  });

  it('режим «Общий бюджет»: сумма единиц берётся по колонке – цена = бюджет / сумма tv_trp', async () => {
    const { byChannel } = groupChannelColumns(PAIRED, isPhysical);
    const sel = /** @type {Record<string, 'monetary'|'physical'>} */ ({ tv: 'physical', digital: 'monetary' });
    const { container } = render(AppliedModeSummary, {
      props: { channels: pairPlanSummaryChannels(byChannel, sel), channelSums: SUMS },
    });
    const row = /** @type {HTMLElement} */ (container.querySelector('[data-testid="uc-editor"][data-channel="tv_trp"]'));
    const input = /** @type {HTMLInputElement} */ (row.querySelector('input[type="number"]'));
    await fireEvent.input(input, { target: { value: '324000000' } });
    vi.runAllTimers();
    expect(get(unitCosts).tv_trp).toBe(270000);
  });

  it('одиночный физический канал olv_views – как раньше: имя колонки = имя канала, цена под olv_views', async () => {
    const media = ['tv_spend', 'olv_views'];
    setMedia(media);
    const { byChannel, channels } = groupChannelColumns(media, isPhysical);
    const sel = /** @type {Record<string, 'monetary'|'physical'>} */ (
      Object.fromEntries(channels.map((b) => [b, isPhysical(b) ? 'physical' : 'monetary'])));
    const summary = pairPlanSummaryChannels(byChannel, sel);
    expect(summary).toEqual([
      { name: 'tv_spend', detectedType: 'monetary' },
      { name: 'olv_views', detectedType: 'physical' },
    ]);
    const { container } = render(AppliedModeSummary, { props: { channels: summary, channelSums: SUMS } });
    await typeUnitCost(container, 'olv_views', '0.2174');
    expect(get(unitCosts)).toEqual({ olv_views: 0.2174 });
    expect(confirmSelection(byChannel, sel)).toBe(true);
  });

  it('канал из одной колонки с суффиксом (tv_trp без пары) – тоже под именем колонки, вид – по плану', () => {
    const { byChannel } = groupChannelColumns(['tv_trp', 'radio_spend'], isPhysical);
    // Выбор по базе ошибочно «деньги» (детектор по имени базы «tv») – план всё равно физическая колонка.
    expect(pairPlanSummaryChannels(byChannel, { tv: 'monetary', radio: 'monetary' })).toEqual([
      { name: 'tv_trp', detectedType: 'physical' },
      { name: 'radio_spend', detectedType: 'monetary' },
    ]);
  });
});

describe('К2-3: запасное чтение цены, записанной под именем канала', () => {
  const paired = () => groupChannelColumns(PAIRED, isPhysical).byChannel;

  it('{tv: 270000} → цена переносится на tv_trp, старый ключ остаётся', () => {
    expect(adoptChannelKeyedUnitCosts({ tv: 270000 }, paired())).toEqual({ tv: 270000, tv_trp: 270000 });
  });

  it('нечего переносить → тот же объект (эффект не пишет в стор)', () => {
    const costs = { tv_trp: 5 };
    expect(adoptChannelKeyedUnitCosts(costs, paired())).toBe(costs);
    const empty = {};
    expect(adoptChannelKeyedUnitCosts(empty, paired())).toBe(empty);
  });

  it('своя цена колонки важнее старого ключа', () => {
    expect(adoptChannelKeyedUnitCosts({ tv: 270000, tv_trp: 1000 }, paired())).toEqual({ tv: 270000, tv_trp: 1000 });
  });

  it('имя канала совпадает с колонкой (olv_views) – переносить нечего', () => {
    const costs = { olv_views: 0.2 };
    expect(adoptChannelKeyedUnitCosts(costs, groupChannelColumns(['olv_views'], isPhysical).byChannel)).toBe(costs);
  });

  it('ключ – имя настоящей колонки канала (денежная колонка «tv»), а не старый ключ канала – не переносится', () => {
    const costs = { tv: 1 };
    expect(adoptChannelKeyedUnitCosts(costs, groupChannelColumns(['tv', 'tv_trp'], isPhysical).byChannel)).toBe(costs);
  });

  it('у канала две физические колонки – цена неоднозначна, не переносится', () => {
    const costs = { tv: 270000 };
    expect(adoptChannelKeyedUnitCosts(costs, groupChannelColumns(['tv_spend', 'tv_trp', 'tv_grp'], isPhysical).byChannel)).toBe(costs);
  });

  it('нулевая или нечисловая старая цена не переносится', () => {
    expect(adoptChannelKeyedUnitCosts({ tv: 0 }, paired())).toEqual({ tv: 0 });
    expect(adoptChannelKeyedUnitCosts(/** @type {any} */ ({ tv: '270000' }), paired())).toEqual({ tv: '270000' });
  });
});

describe('К2-3 проводка (экран «Валидация» в тестах не отрисовывается)', () => {
  it('сводке передаются колонки того же плана, что судит кнопка «Далее ▶»', () => {
    expect(validateStepSrc).toMatch(/const summaryChannels = \$derived\(pairPlanSummaryChannels\(availableMetricsByChannel, managerBaseSelection\)\);/);
    const tpl = validateStepSrc.slice(validateStepSrc.indexOf('{:else if subStep === 2}'));
    expect(tpl).toMatch(/<AppliedModeSummary\s+channels=\{summaryChannels\}/);
  });

  it('запасное чтение старого ключа подключено эффектом, пишет только при изменении', () => {
    expect(validateStepSrc).toMatch(/const adopted = adoptChannelKeyedUnitCosts\(\$unitCosts, availableMetricsByChannel\);\s*if \(adopted !== \$unitCosts\) unitCosts\.set\(adopted\);/);
  });
});
