/**
 * CPD-178 в шести окнах ошибки пайплайна (Импорт/Валидация/Модель/Декомпозиция/Оптимизация/
 * Отчёт): после успешного открытия формы `opening` возвращался в `false`, кнопка выглядела
 * так же, как до нажатия — человек в момент сбоя не получал никакого подтверждения. Здесь
 * проверяется, что подтверждение появляется РЯДОМ с кнопкой (не на ней) и не гаснет само.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import FeedbackReportButton from '$lib/components/FeedbackReportButton.svelte';

beforeEach(() => {
  vi.mocked(invoke).mockReset();
});

describe('FeedbackReportButton — подтверждение успеха (CPD-178)', () => {
  it('после успешного открытия формы рядом с кнопкой появляется отдельное подтверждение', async () => {
    let resolveOpen;
    vi.mocked(invoke).mockImplementation(() => new Promise((resolve) => { resolveOpen = resolve; }));

    render(FeedbackReportButton, { props: { ekran: 'Оптимизация', oshibka: 'sidecar недоступен' } });

    const btn = screen.getByRole('button', { name: /Сообщить о проблеме/ });
    await fireEvent.click(btn);

    // Пока invoke не разрешился — подтверждения ещё нет.
    expect(screen.queryByText('Форма открылась в браузере.')).not.toBeInTheDocument();

    resolveOpen('https://forms.example/feedback');

    const success = await screen.findByText('Форма открылась в браузере.');
    expect(success).toBeInTheDocument();
    expect(success).toHaveAttribute('role', 'status');

    // Кнопка сама по себе не несёт признака успеха — вернулась в обычный вид.
    expect(screen.getByRole('button', { name: 'Сообщить о проблеме' })).not.toBeDisabled();

    // Не гаснет само по таймеру.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText('Форма открылась в браузере.')).toBeInTheDocument();
  });

  it('отказ после подтверждения — подтверждение сбрасывается, виден только отказ', async () => {
    vi.mocked(invoke)
      .mockResolvedValueOnce('https://forms.example/feedback')
      .mockRejectedValueOnce('[FB-001] недоступно');

    render(FeedbackReportButton, { props: { ekran: 'Модель' } });

    const btn = screen.getByRole('button', { name: /Сообщить о проблеме/ });
    await fireEvent.click(btn);
    await screen.findByText('Форма открылась в браузере.');

    await fireEvent.click(btn);
    await screen.findByText('недоступно');

    expect(screen.queryByText('Форма открылась в браузере.')).not.toBeInTheDocument();
  });
});
