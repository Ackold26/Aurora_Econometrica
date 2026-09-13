/**
 * Кривые отдачи на открытом заново проекте (живой замер 2026-09-13).
 *
 * Класс дефекта: данные есть на диске, но читатель про них не знает.
 * Блок «Кривые отдачи» на шаге Оптимизации показывается при двух условиях:
 * в ответе оптимизации есть `response_curves` И непуст `scaledParams`, который
 * строится из `modelData.channelParams`. Восстановление проекта с диска
 * (`restoreProjectResults`) поднимало диагностику, разбор и оптимизацию, но
 * `channelParams` не поднимало вовсе – они лежат не в `results/*.json`, а рядом
 * с моделью, в `models/latest-params.json`. Итог замера: `response_curves` = 4
 * канала, `channelParams` = null → блок прятался ДАЖЕ после успешного расчёта,
 * а заглушка советовала «запустите оптимизацию», то есть сделать уже сделанное.
 *
 * Контракт фикса: снимок параметров восстанавливается в отдельный стор
 * `modelParamsSnapshot` (шаг Оптимизации берёт его запасным источником), но
 * ТОЛЬКО когда он принадлежит той же модели, что и восстановленная диагностика
 * (INV-50 – лучше не нарисовать кривые, чем нарисовать чужие). Признак «та же
 * модель»: опознаватели совпали, либо их нет ни у одной стороны (модель обучена
 * до появления штампа – таких проектов у клиента большинство).
 *
 * Почему отдельный стор, а не `modelData.channelParams`: на смену этого поля
 * завязан пересчёт разбора («прилетела новая тренировка»). Замером 2026-09-13
 * подстановка снимка прямо в `modelData` давала молчаливый пересчёт разбора и
 * оптимизации при открытии проекта, поверх сохранённого результата пользователя.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import {
  activeProject, activeProjectId, modelData, modelParamsSnapshot, optimizeData, resetPipeline,
} from '$lib/project-state.js';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));

/** Параметры каналов в форме models/latest-params.json → channel_params. */
function channelParamsFixture() {
  return {
    'ТВ бюджет': { beta: 0.119, alpha: 1.6313, gamma: 0.5178, decay: 0.4526, adstock_mean_posterior: 22229589.52 },
    'Онлайн-видео бюджет': { beta: 0.081, alpha: 1.2, gamma: 0.44, decay: 0.31, adstock_mean_posterior: 8123456.7 },
  };
}

/**
 * Мок диска. `paramsFingerprint` – опознаватель модели в снимке параметров,
 * `diagFingerprint` – в диагностике; null означает «штампа нет».
 * @param {{ withParams?: boolean, paramsFingerprint?: string|null, diagFingerprint?: string|null }} opts
 */
function mockDisk({ withParams = true, paramsFingerprint = 'fp-model-1', diagFingerprint = 'fp-model-1' } = {}) {
  vi.mocked(invoke).mockImplementation(async (cmd) => {
    if (cmd === 'project_load_results') {
      return {
        modelDiagnostics: diagFingerprint
          ? { mqs: { score: 70 }, model_fingerprint: diagFingerprint }
          : { mqs: { score: 70 } },
        decomposition: { time_series: { dates: ['2025-01', '2025-02'] }, channels: [{ name: 'ТВ бюджет', raw_spend: 100 }] },
        optimization: {
          channels: [{ name: 'ТВ бюджет', current_spend: 100, optimal_spend: 120 }],
          response_curves: { 'ТВ бюджет': { spend: [1, 2], response: [1, 2], current_x: 1, optimal_x: 2 } },
          status: 'ok',
        },
        validation: null,
        planning: null,
        mediaPlan: null,
        modelParams: withParams
          ? {
            channel_params: channelParamsFixture(),
            diagnostics: paramsFingerprint ? { model_fingerprint: paramsFingerprint } : {},
          }
          : null,
      };
    }
    if (cmd === 'project_get') return { id: get(activeProjectId) };
    return null;
  });
}

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  try { localStorage.clear(); } catch { /* jsdom */ }
  activeProjectId.set(null);
  modelData.set({ diagnostics: null, channelParams: null, picklePath: null, normalization: null });
  modelParamsSnapshot.set(null);
  optimizeData.set(null);
});

describe('восстановление проекта: параметры каналов для кривых отдачи', () => {
  it('снимок той же модели → channelParams подняты, обе половины условия показа истинны', async () => {
    mockDisk();
    activeProjectId.set('p-curves-1');
    activeProject.set(/** @type {any} */ ({ id: 'p-curves-1' }));
    resetPipeline('p-curves-1');
    await new Promise((r) => setTimeout(r, 80));

    const snap = get(modelParamsSnapshot);
    expect(snap).toBeTruthy();
    expect(snap?.projectId).toBe('p-curves-1');
    expect(Object.keys(snap?.channelParams ?? {})).toEqual(['ТВ бюджет', 'Онлайн-видео бюджет']);
    // Вторая половина условия показа блока: непустой набор параметров.
    expect(Object.keys(snap?.channelParams ?? {}).length).toBeGreaterThan(0);
    // Первая половина – кривые в ответе оптимизации.
    expect(get(optimizeData)?.response_curves).toBeTruthy();
    // Признак «обучено в этой сессии» НЕ трогаем – иначе разбор считает модель
    // переобученной и молча пересчитывает себя и оптимизацию.
    expect(get(modelData).channelParams).toBeNull();
  });

  it('INV-50: опознаватель снимка разошёлся с диагностикой → параметры НЕ подставляются', async () => {
    mockDisk({ paramsFingerprint: 'fp-другая-модель' });
    activeProjectId.set('p-curves-2');
    activeProject.set(/** @type {any} */ ({ id: 'p-curves-2' }));
    resetPipeline('p-curves-2');
    await new Promise((r) => setTimeout(r, 80));

    expect(get(modelParamsSnapshot)).toBeNull();
  });

  it('модель обучена до появления опознавателя (штампа нет ни там, ни там) → параметры подняты', async () => {
    mockDisk({ paramsFingerprint: null, diagFingerprint: null });
    activeProjectId.set('p-curves-4');
    activeProject.set(/** @type {any} */ ({ id: 'p-curves-4' }));
    resetPipeline('p-curves-4');
    await new Promise((r) => setTimeout(r, 80));

    expect(Object.keys(get(modelParamsSnapshot)?.channelParams ?? {})).toEqual(['ТВ бюджет', 'Онлайн-видео бюджет']);
  });

  it('опознаватель есть только у диагностики (снимок из другого поколения) → параметры НЕ подставляются', async () => {
    mockDisk({ paramsFingerprint: null, diagFingerprint: 'fp-model-1' });
    activeProjectId.set('p-curves-5');
    activeProject.set(/** @type {any} */ ({ id: 'p-curves-5' }));
    resetPipeline('p-curves-5');
    await new Promise((r) => setTimeout(r, 80));

    expect(get(modelParamsSnapshot)).toBeNull();
  });

  it('снимка параметров на диске нет → параметры остаются пустыми, без выдумки', async () => {
    mockDisk({ withParams: false });
    activeProjectId.set('p-curves-3');
    activeProject.set(/** @type {any} */ ({ id: 'p-curves-3' }));
    resetPipeline('p-curves-3');
    await new Promise((r) => setTimeout(r, 80));

    expect(get(modelParamsSnapshot)).toBeNull();
  });
});
