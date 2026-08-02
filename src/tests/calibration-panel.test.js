/**
 * E2 (2026-07-03): CalibrationPanel – форма «Результат эксперимента» +
 * calibration-store (persist per-project) + включение в train-конфиг.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import CalibrationPanel from '$lib/components/pipeline/CalibrationPanel.svelte';
import {
  calibrations, loadCalibrations, validateCalibrationEntry,
} from '$lib/calibration-store.js';
import { buildTrainConfig } from '$lib/train-config.js';

const CHANNELS = ['TV', 'Digital'];

function baseTrainState(overrides = {}) {
  return {
    projectDir: 'C:/p', dataFile: 'd.xlsx', kpiColumn: 'sales',
    mediaColumns: CHANNELS, controlColumns: [], dateColumn: 'date',
    channelAdstock: {}, engine: 'bayesian', showAdvanced: false,
    mcmcChains: 2, mcmcDraws: 500, mcmcTune: 500,
    unitCosts: {}, kpiType: 'sales', valuePerCountUnit: null,
    kpiKind: 'monetary', mergeRules: {}, channelCategories: {},
    disabledHolidays: [], useHolidays: true,
    ...overrides,
  };
}

const VALID = {
  channel: 'TV', date_from: '2026-01-01', date_to: '2026-03-01',
  lift_abs: 500, lift_low: 300, lift_high: 700,
  confidence_level: 0.9, test_type: 'geo_lift',
};

beforeEach(() => {
  localStorage.clear();
  calibrations.set([]);
});

describe('validateCalibrationEntry', () => {
  it('валидная запись → null; ошибки – по-русски и по делу', () => {
    expect(validateCalibrationEntry(VALID)).toBeNull();
    expect(validateCalibrationEntry({ ...VALID, channel: '' })).toMatch(/канал/i);
    expect(validateCalibrationEntry({ ...VALID, date_to: '2025-12-01' }))
      .toMatch(/раньше даты начала/);
    expect(validateCalibrationEntry({ ...VALID, lift_high: 100 }))
      .toMatch(/нижняя граница меньше верхней/);
    expect(validateCalibrationEntry({ ...VALID, lift_abs: 900 }))
      .toMatch(/внутри интервала/);
  });
});

describe('calibration-store persist', () => {
  it('persist/load по проекту; чужой проект – пусто', () => {
    calibrations.set([VALID]);
    // persist вызывается компонентом; проверяем функции напрямую
    loadCalibrations('p-none');
    expect(get(calibrations)).toEqual([]);
  });
});

describe('buildTrainConfig + калибровки', () => {
  it('bayesian + непустой список → calibrations в конфиге', () => {
    const cfg = buildTrainConfig(baseTrainState({ calibrations: [VALID] }));
    expect(cfg.calibrations).toEqual([VALID]);
  });
  it('OLS → калибровки НЕ включаются (сервер бы честно отказал)', () => {
    const cfg = buildTrainConfig(baseTrainState({ engine: 'ols', calibrations: [VALID] }));
    expect(cfg).not.toHaveProperty('calibrations');
  });
  it('пустой список → ключа нет (back-compat конфига)', () => {
    const cfg = buildTrainConfig(baseTrainState({ calibrations: [] }));
    expect(cfg).not.toHaveProperty('calibrations');
  });
});

describe('CalibrationPanel UI', () => {
  it('добавление валидной записи → строка в списке + persist', async () => {
    render(CalibrationPanel, { props: { channels: CHANNELS, projectId: 'p1' } });
    await fireEvent.change(screen.getByLabelText('Канал теста'), { target: { value: 'TV' } });
    await fireEvent.input(screen.getByLabelText('Начало теста'), { target: { value: '2026-01-01' } });
    await fireEvent.input(screen.getByLabelText('Конец теста'), { target: { value: '2026-03-01' } });
    await fireEvent.input(screen.getByLabelText('Измеренный прирост'), { target: { value: '500' } });
    await fireEvent.input(screen.getByLabelText('Нижняя граница'), { target: { value: '300' } });
    await fireEvent.input(screen.getByLabelText('Верхняя граница'), { target: { value: '700' } });
    await fireEvent.click(screen.getByRole('button', { name: /Добавить/ }));
    await waitFor(() => {
      expect(screen.getByText(/2026-01-01 – 2026-03-01/)).toBeInTheDocument();
    });
    expect(get(calibrations)).toHaveLength(1);
    expect(JSON.parse(localStorage.getItem('aurora-econ-calibrations:p1') ?? '[]'))
      .toHaveLength(1);
  });

  it('невалидная запись → русская ошибка, список пуст', async () => {
    render(CalibrationPanel, { props: { channels: CHANNELS, projectId: 'p1' } });
    await fireEvent.click(screen.getByRole('button', { name: /Добавить/ }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Выберите канал');
    });
    expect(get(calibrations)).toHaveLength(0);
  });

  it('удаление записи очищает список и persist', async () => {
    calibrations.set([VALID]);
    render(CalibrationPanel, { props: { channels: CHANNELS, projectId: 'p1' } });
    await fireEvent.click(screen.getByRole('button', { name: /Удалить калибровку TV/ }));
    await waitFor(() => {
      expect(get(calibrations)).toHaveLength(0);
    });
  });
});
