/**
 * s46: кнопка «Сообщить о проблеме» обязана стоять в окне ошибки каждого из шести
 * шагов мастера. Этот файл — два шага (Импорт, Валидация): монтируется настоящий
 * компонент, доводится до РЕАЛЬНОГО состояния ошибки через мок invoke (не через
 * текстовое чтение исходника), и проверяется присутствие кнопки в отрисованном
 * баннере ошибки — оракул поведения, не разметки: без живого errorMsg баннер вообще
 * не появляется.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import { importData, pipelineStepMeta } from '$lib/project-state.js';
import ImportStep from '$lib/components/pipeline/ImportStep.svelte';
import ValidateStep from '$lib/components/pipeline/ValidateStep.svelte';

// ImportStep слушает drag&drop окна через Tauri window API — недоступно в jsdom,
// к поведению кнопки обращения не относится.
vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({ onDragDropEvent: () => Promise.resolve(() => {}) }),
}));

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  vi.mocked(open).mockReset();
  importData.set({ file: null, fileName: null, shape: null });
});

describe('ImportStep — окно ошибки после отказа предпросмотра файла', () => {
  it('econ_data_preview вернул ошибку → баннер с кнопкой обращения (ekran="Импорт")', async () => {
    vi.mocked(open).mockResolvedValueOnce('C:/fake/data.xlsx');
    vi.mocked(invoke).mockImplementation(async (cmd) => {
      if (cmd === 'econ_data_preview') return { status: 'error', message: 'Файл повреждён' };
      return null;
    });

    render(ImportStep);

    const dropzone = screen.getByLabelText('Зона перетаскивания файла');
    await fireEvent.click(dropzone);

    await waitFor(() => {
      expect(screen.getByText('Файл повреждён')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Сообщить о проблеме/ })).toBeInTheDocument();
  });
});

describe('ValidateStep — окно ошибки после отказа валидации', () => {
  it('econ_validate вернул жёсткую ошибку → баннер с кнопкой обращения (ekran="Валидация")', async () => {
    importData.set({ file: 'C:/fake/data.xlsx', fileName: 'data.xlsx', shape: { rows: 10, cols: 3 } });
    pipelineStepMeta.set([
      { status: 'complete', errorMessage: null },
      { status: 'ready', errorMessage: null },
      { status: 'locked', errorMessage: null },
      { status: 'locked', errorMessage: null },
      { status: 'locked', errorMessage: null },
      { status: 'locked', errorMessage: null },
      { status: 'locked', errorMessage: null },
    ]);
    vi.mocked(invoke).mockImplementation(async (cmd) => {
      if (cmd === 'econ_validate') return { status: 'error', message: 'Не удалось разобрать столбцы' };
      return null;
    });

    render(ValidateStep);

    // Перед первой валидацией показан ObjectiveSelector — выбор цели запускает runValidate().
    const roiCard = await screen.findByRole('button', { name: /ROI/ });
    await fireEvent.click(roiCard);

    await waitFor(() => {
      expect(screen.getByText('Не удалось разобрать столбцы')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Сообщить о проблеме/ })).toBeInTheDocument();
  });
});
