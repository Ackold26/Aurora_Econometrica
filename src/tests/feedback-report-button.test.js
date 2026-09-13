/**
 * s46: поведенческий сторож кнопки «Сообщить о проблеме».
 *
 * Находка PULSE (2026-09-13): кнопку добавили в шесть окон ошибок мастера и в шапку,
 * плюс кнопку загрузки файла лицензии в настройках — ни одной проверки фронтенда
 * не добавлено. Единственный сторож (`guard_cpd88_feedback_category_map.rs`) читает
 * исходник ТЕКСТОМ и ищет подстроку: он красит одинаково удаление вызова и
 * `if (false) { invoke(...) }` — текст цел, действие мертво, клиент нажимает кнопку,
 * ничего не происходит, а сторож зелёный.
 *
 * Этот файл проверяет само поведение: нажатие кнопки действительно зовёт команду
 * `open_feedback_form` РОВНО один раз и передаёт оба поля, шаг и текст ошибки,
 * с теми значениями, что были переданы кнопке пропсами.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import FeedbackReportButton from '$lib/components/FeedbackReportButton.svelte';

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockResolvedValue('https://forms.example/feedback');
});

describe('FeedbackReportButton — нажатие действительно зовёт open_feedback_form', () => {
  it('передаёт ekran и oshibka из пропсов, вызов ровно один раз', async () => {
    render(FeedbackReportButton, { props: { ekran: 'Оптимизация', oshibka: 'sidecar недоступен' } });

    const btn = screen.getByRole('button', { name: /Сообщить о проблеме/ });
    await fireEvent.click(btn);

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledTimes(1);
    });
    expect(invoke).toHaveBeenCalledWith('open_feedback_form', {
      ekran: 'Оптимизация',
      oshibka: 'sidecar недоступен',
    });
  });

  it('без oshibka (кнопка в шапке) — поле передаётся пустой строкой, не выдумывается', async () => {
    render(FeedbackReportButton, { props: { ekran: 'Импорт данных' } });

    const btn = screen.getByRole('button', { name: /Сообщить о проблеме/ });
    await fireEvent.click(btn);

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledTimes(1);
    });
    expect(invoke).toHaveBeenCalledWith('open_feedback_form', {
      ekran: 'Импорт данных',
      oshibka: '',
    });
  });

  it('отказ команды → человеческий текст ошибки на экране, кнопка не блокирует программу', async () => {
    vi.mocked(invoke).mockRejectedValueOnce('[FB-001] internal');
    render(FeedbackReportButton, { props: { ekran: 'Модель', oshibka: 'x' } });

    const btn = screen.getByRole('button', { name: /Сообщить о проблеме/ });
    await fireEvent.click(btn);

    // '[FB-001] internal' → служебный код снят, остаётся человеческий текст «internal».
    await waitFor(() => {
      expect(screen.getByText('internal')).toBeInTheDocument();
    });
  });
});
