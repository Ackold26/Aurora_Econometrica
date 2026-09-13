/**
 * s46: поведенческий сторож кнопки «Загрузить файл лицензии» в настройках.
 * Часть той же находки, что и feedback-report-button.test.js — кнопка добавлена
 * без единой проверки. Здесь проверяется, что нажатие: (1) открывает системный
 * диалог выбора файла, (2) зовёт invoke('import_license', { path }) с выбранным
 * путём, а не с чем-то придуманным.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import SettingsPage from '../routes/settings/+page.svelte';

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  // Минимум, нужный странице настроек, чтобы смонтироваться без падения на побочных
  // invoke-вызовах (get_cabinets/get_model_settings и т.п.) — к делу теста не относятся.
  vi.mocked(invoke).mockImplementation(async (cmd) => {
    if (cmd === 'get_cabinets') return [];
    if (cmd === 'get_model_settings') return { model: 'sonnet', effort: 'medium' };
    return null;
  });
  vi.mocked(open).mockReset();
});

describe('Настройки — кнопка «Загрузить файл лицензии»', () => {
  it('нажатие открывает диалог выбора файла и зовёт import_license с выбранным путём', async () => {
    vi.mocked(open).mockResolvedValueOnce('C:/fake/license.json');

    render(SettingsPage);

    const btn = await screen.findByRole('button', { name: 'Загрузить файл лицензии' });
    await fireEvent.click(btn);

    await waitFor(() => {
      expect(open).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('import_license', { path: 'C:/fake/license.json' });
    });
  });

  it('пользователь закрыл диалог без выбора файла → import_license НЕ вызывается', async () => {
    vi.mocked(open).mockResolvedValueOnce(null);

    render(SettingsPage);

    const btn = await screen.findByRole('button', { name: 'Загрузить файл лицензии' });
    await fireEvent.click(btn);

    await waitFor(() => {
      expect(open).toHaveBeenCalledTimes(1);
    });
    expect(invoke).not.toHaveBeenCalledWith('import_license', expect.anything());
  });
});
