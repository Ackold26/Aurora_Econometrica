/**
 * Внешний аудит 08.09 (High-3, Medium-3, Low-2, Low-3): состояние РАСЧЁТОВ одного
 * проекта не имеет права участвовать в вердиктах о другом.
 *
 * Сторож `new-project-does-not-inherit-results` держит путь «создать проект». Этот —
 * все остальные пути смены проекта, на которых три хранилища переживали смену молча:
 *   • переключение проектов в шапке и импорт архива `.aurora` (loadPipelineForProject),
 *   • кнопка «Новый анализ» (resetForNewAnalysis),
 *   • гонка асинхронного восстановления (ответ по А доезжает в контекст Б),
 *   • третье состояние поиска медиаплана («определить не удалось»).
 *
 * Клиентское следствие High-3, ради которого сторож и написан: переключившись с
 * обученного проекта А на обученный проект Б, пользователь видел баннер «Декомпозиция
 * устарела. Конфигурация изменилась после обучения… Переобучите модель» со списком
 * расхождений — вердикт по конфигурации А о модели Б, которая не менялась.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import {
  activeProjectId,
  activeProject,
  lastTrainedConfig,
  forecastContext,
  optimizeLiveState,
  mediaPlanDetected,
  mediaPlanProbeStatus,
  decomposeData,
  optimizeData,
  modelData,
  loadPipelineForProject,
  resetForNewAnalysis,
  resetResultsKeepImport,
} from '$lib/project-state.js';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));

/** Дать отработать всем ожиданиям внутри restoreProjectResults. */
async function flush() {
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
}

/** Конфигурация обучения проекта А — та, по которой судится «модель устарела». */
function configA() {
  return {
    kpi: 'Выручка',
    media: ['ТВ', 'Онлайн-видео', 'Performance', 'Наружная', 'Радио', 'Пресса', 'Инфлюенсеры'],
    control: ['Промо', 'Дистрибуция', 'Цена'],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(invoke).mockResolvedValue(null);
  try { localStorage.clear(); } catch { /* jsdom */ }
  activeProject.set(null);
  activeProjectId.set(null);
  decomposeData.set(null);
  optimizeData.set(null);
  modelData.set({ diagnostics: null, channelParams: null, picklePath: null, normalization: null });
  mediaPlanDetected.set(null);
  mediaPlanProbeStatus.set(null);
  forecastContext.set(null);
  lastTrainedConfig.set(null);
});

describe('переключение между проектами (High-3)', () => {
  it('не тащит в проект Б конфигурацию обучения проекта А', () => {
    activeProjectId.set('proj-A');
    lastTrainedConfig.set(configA());

    activeProjectId.set('proj-B');
    loadPipelineForProject('proj-B');

    expect(
      get(lastTrainedConfig),
      'по конфигурации проекта А выносился вердикт «Декомпозиция устарела» о проекте Б',
    ).toBeNull();
  });

  it('но сохраняет конфигурацию для ТОГО проекта, которому она принадлежит', () => {
    activeProjectId.set('proj-A');
    lastTrainedConfig.set(configA());

    activeProjectId.set('proj-B');
    loadPipelineForProject('proj-B');
    activeProjectId.set('proj-A');
    loadPipelineForProject('proj-A');

    expect(
      get(lastTrainedConfig)?.kpi,
      'ключ разделён по проектам, а не стёрт: баннер «модель устарела» обязан пережить перезагрузку окна',
    ).toBe('Выручка');
  });

  it('снимает контекст прогноза, коридоры каналов и медиаплан прошлого проекта', () => {
    activeProjectId.set('proj-A');
    forecastContext.set({ training_granularity: 'week', seasonality_detected: { period: 52 } });
    optimizeLiveState.set({
      channelBudgets: { 'ТВ': 1000 },
      channelMinPct: { 'ТВ': 50 },
      channelMaxPct: { 'ТВ': 150 },
      globalMinPct: 50,
      globalMaxPct: 150,
    });
    mediaPlanDetected.set({ n_future_periods: 3, confirmed: true });

    activeProjectId.set('proj-B');
    loadPipelineForProject('proj-B');

    expect(get(forecastContext), 'гранулярность обучения и «сезонность обнаружена» чужой модели').toBeNull();
    expect(get(optimizeLiveState).channelBudgets, 'коридоры и бюджеты каналов чужого проекта').toEqual({});
    expect(get(mediaPlanDetected), 'медиаплан чужого проекта').toBeNull();
  });
});

describe('кнопка «Новый анализ» (High-3)', () => {
  it('снимает состояние расчётов прошлого проекта', () => {
    activeProjectId.set('proj-A');
    lastTrainedConfig.set(configA());
    forecastContext.set({ training_granularity: 'week' });
    mediaPlanDetected.set({ n_future_periods: 3 });

    resetForNewAnalysis();

    expect(get(lastTrainedConfig), 'конфигурация обучения прошлого проекта').toBeNull();
    expect(get(forecastContext), 'контекст прогноза прошлого проекта').toBeNull();
    expect(get(mediaPlanDetected), 'медиаплан прошлого проекта').toBeNull();
  });
});

describe('гонка асинхронного восстановления (Medium-3)', () => {
  it('ответ по проекту А, вернувшийся после переключения на Б, не попадает в сторы', async () => {
    /** @type {(v: any) => void} */
    let releaseA = () => {};
    vi.mocked(invoke).mockImplementation(async (cmd, args) => {
      const pid = /** @type {any} */ (args)?.projectId;
      if (cmd === 'project_load_results' && pid === 'proj-A') {
        return new Promise((resolve) => { releaseA = resolve; });
      }
      if (cmd === 'project_load_results' && pid === 'proj-B') return {};
      return null;
    });

    activeProjectId.set('proj-A');   // запрос ушёл, ответ ещё в пути
    activeProjectId.set('proj-B');   // пользователь уже в другом проекте
    await flush();

    releaseA({
      decomposition: { channels: [{ name: 'ТВ', efficiency_gap: -38.5 }] },
      modelDiagnostics: { mqs: { score: 70 }, metrics: { r_squared: 0.936 } },
      optimization: { expected_lift_pct: 3.4 },
    });
    await flush();

    expect(get(decomposeData), 'разбор проекта А доехал в контекст проекта Б').toBeNull();
    expect(get(optimizeData), 'оптимизация проекта А доехала в контекст проекта Б').toBeNull();
    expect(get(modelData).diagnostics, 'диагностика модели проекта А доехала в контекст проекта Б').toBeNull();
  });
});

describe('три состояния поиска медиаплана (Low-2, Low-3)', () => {
  /** @param {any} mediaPlan */
  async function restoreWithMediaPlan(mediaPlan, pid = 'proj-mp') {
    vi.mocked(invoke).mockImplementation(async (cmd) => {
      if (cmd === 'project_load_results') return { mediaPlan };
      return null;
    });
    activeProjectId.set(pid);
    await flush();
  }

  it('«определить не удалось» не выдаётся за «плана нет»', async () => {
    await restoreWithMediaPlan({ n_future_periods: null, detection: 'unavailable', confirmed: false }, 'mp-unknown');
    expect(get(mediaPlanProbeStatus), 'третье честное состояние писателя').toBe('unavailable');
    expect(get(mediaPlanDetected), 'подтверждать нечего — плана в сторе быть не должно').toBeNull();
  });

  it('«хвоста нет» и «план найден» различаются между собой', async () => {
    await restoreWithMediaPlan({ n_future_periods: 0, confirmed: false }, 'mp-absent');
    expect(get(mediaPlanProbeStatus)).toBe('absent');
    expect(get(mediaPlanDetected)).toBeNull();

    await restoreWithMediaPlan({ n_future_periods: 3, confirmed: true }, 'mp-found');
    expect(get(mediaPlanProbeStatus)).toBe('found');
    expect(get(mediaPlanDetected)?.n_future_periods).toBe(3);
  });

  it('создание проекта снимает медиаплан прошлого проекта явно, не надеясь на восстановление', () => {
    mediaPlanDetected.set({ n_future_periods: 3, confirmed: true });
    mediaPlanProbeStatus.set('found');

    resetResultsKeepImport();

    expect(get(mediaPlanDetected), 'при отказе project_load_results план прошлого проекта оставался в сторе нового').toBeNull();
    expect(get(mediaPlanProbeStatus)).toBeNull();
  });
});
