/**
 * s48 (2026-09-14): экран «Условия ознакомительного использования» — блокирующий гейт,
 * заменивший полный текст пробного периода в лицензионном договоре на краткую суть +
 * ссылку на отдельный документ (п.5 ст.1286 ГК РФ). Поведенческие проверки, не текстовые:
 * монтируется настоящий компонент, отметка и кнопки доводятся до реальных состояний через
 * события и мок invoke — судим о том, что компонент ДЕЛАЕТ, а не что написано в разметке.
 *
 * Хранение согласия с редакцией и повторный показ при устаревшей редакции проверены
 * Rust-тестами в src-tauri/src/commands/user_config.rs (trial_consent_* — согласие живёт в
 * durable-конфиге, фронтенду об этом уровне ничего не известно).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { trialConsentPromptOpen } from '$lib/store.js';
import { SHOW_CLOUD_PROCESSING_PARAGRAPH } from '$lib/trial-terms-config.js';
import TrialConsentOverlay from '$lib/components/TrialConsentOverlay.svelte';

const closeWindow = vi.fn().mockResolvedValue(undefined);

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: vi.fn(() => ({ close: closeWindow })),
}));

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockResolvedValue(null);
  closeWindow.mockClear();
  trialConsentPromptOpen.set(true);
});

describe('TrialConsentOverlay — отметка и кнопка «Принимаю»', () => {
  it('отметка НЕ предустановлена, а «Принимаю» недоступна без неё', () => {
    render(TrialConsentOverlay);

    const checkbox = /** @type {HTMLInputElement} */ (screen.getByRole('checkbox'));
    const acceptBtn = screen.getByRole('button', { name: /Принимаю/ });

    expect(checkbox.checked).toBe(false);
    expect(acceptBtn).toBeDisabled();
  });

  it('после установки отметки «Принимаю» становится доступна и зовёт accept_trial_consent', async () => {
    render(TrialConsentOverlay);

    const checkbox = screen.getByRole('checkbox');
    const acceptBtn = screen.getByRole('button', { name: /Принимаю/ });

    await fireEvent.click(checkbox);
    expect(acceptBtn).not.toBeDisabled();

    await fireEvent.click(acceptBtn);

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('accept_trial_consent');
    });
  });

  it('успешное принятие закрывает экран (не оставляет человека перед мёртвым согласием)', async () => {
    render(TrialConsentOverlay);

    await fireEvent.click(screen.getByRole('checkbox'));
    await fireEvent.click(screen.getByRole('button', { name: /Принимаю/ }));

    await waitFor(() => {
      let open;
      trialConsentPromptOpen.subscribe((v) => (open = v))();
      expect(open).toBe(false);
    });
  });

  it('снятие отметки после установки снова блокирует «Принимаю»', async () => {
    render(TrialConsentOverlay);

    const checkbox = screen.getByRole('checkbox');
    const acceptBtn = screen.getByRole('button', { name: /Принимаю/ });

    await fireEvent.click(checkbox);
    expect(acceptBtn).not.toBeDisabled();

    await fireEvent.click(checkbox);
    expect(acceptBtn).toBeDisabled();
  });
});

describe('TrialConsentOverlay — «Отказаться»', () => {
  it('закрывает окно приложения (единственный выход без согласия)', async () => {
    render(TrialConsentOverlay);

    await fireEvent.click(screen.getByRole('button', { name: /Отказаться/ }));

    await waitFor(() => {
      expect(closeWindow).toHaveBeenCalledTimes(1);
    });
    // accept_trial_consent НЕ зовётся - отказ не должен случайно записаться как согласие.
    expect(invoke).not.toHaveBeenCalledWith('accept_trial_consent');
  });
});

describe('TrialConsentOverlay — условный абзац об обработке на серверах Aurora AI', () => {
  // Правило продукта (задание владельца s48): один переключатель, одно место
  // ($lib/trial-terms-config.js), текст абзаца не дублируется по файлам. Здесь проверяется
  // ПОВЕДЕНИЕ обоих состояний через явный проп (эквивалент двух значений константы), а не
  // сама константа — компонент не обязан знать, откуда пришло значение.
  const CLOUD_PARAGRAPH_TEXT = /отправляет содержание переданных в работу материалов/;

  it('без прокинутого пропа компонент берёт значение из единственной точки конфигурации (продакшн-путь +layout.svelte)', () => {
    render(TrialConsentOverlay);

    if (SHOW_CLOUD_PROCESSING_PARAGRAPH) {
      expect(screen.getByText(CLOUD_PARAGRAPH_TEXT)).toBeInTheDocument();
    } else {
      expect(screen.queryByText(CLOUD_PARAGRAPH_TEXT)).not.toBeInTheDocument();
    }
  });

  it('включённая проверка (true) — абзац показан, остальной текст на месте', () => {
    render(TrialConsentOverlay, { props: { showCloudProcessingParagraph: true } });

    expect(screen.getByText(CLOUD_PARAGRAPH_TEXT)).toBeInTheDocument();
    expect(screen.getByText(/передана вам для ознакомления/)).toBeInTheDocument();
    expect(screen.getByText(/Персональные данные в программу вводить нельзя/)).toBeInTheDocument();
  });

  it('выключенная проверка (false) — абзаца нет, а вёрстка вокруг не разъезжается', () => {
    render(TrialConsentOverlay, { props: { showCloudProcessingParagraph: false } });

    expect(screen.queryByText(CLOUD_PARAGRAPH_TEXT)).not.toBeInTheDocument();
    // Соседние абзацы и рабочие элементы окна не пострадали от снятия среднего абзаца.
    expect(screen.getByText(/передана вам для ознакомления/)).toBeInTheDocument();
    expect(screen.getByText(/Персональные данные в программу вводить нельзя/)).toBeInTheDocument();
    expect(screen.getByRole('checkbox')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Принимаю/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Отказаться/ })).toBeInTheDocument();
  });
});

describe('TrialConsentOverlay — открытие условий', () => {
  it('кнопка «Открыть условия» зовёт open_trial_terms', async () => {
    render(TrialConsentOverlay);

    await fireEvent.click(screen.getByRole('button', { name: /Открыть условия/ }));

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('open_trial_terms');
    });
  });

  it('отказ open_trial_terms (PDF ещё не поставлен) показывает понятную ошибку, а не молчит', async () => {
    vi.mocked(invoke).mockImplementation(async (cmd) => {
      if (cmd === 'open_trial_terms') {
        throw 'Файл «Условия ознакомительного использования.pdf» пока не поставляется вместе с программой.';
      }
      return null;
    });

    render(TrialConsentOverlay);
    await fireEvent.click(screen.getByRole('button', { name: /Открыть условия/ }));

    await waitFor(() => {
      expect(screen.getByText(/пока не поставляется/)).toBeInTheDocument();
    });
  });
});
