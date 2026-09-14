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
import { tick } from 'svelte';
import { invoke } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { trialConsentPromptOpen, trialConsentResolved } from '$lib/store.js';
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
  // s48 (третья волна): в реальном потоке к моменту, когда окно вообще может стать видимым,
  // Rust уже ответил (resolveTrialConsentGate ставит trialConsentResolved ПЕРЕД тем, как
  // компонент показывается) - иначе trialConsentBlocking навсегда true независимо от того,
  // что происходит с trialConsentPromptOpen, и тест "перехват снимается" ниже не имел бы
  // смысла (проверял бы состояние, которого в бою не бывает).
  trialConsentResolved.set(true);
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

describe('TrialConsentOverlay — второй слой защиты: перехват клавиш вне оверлея (s48, аудит второй волны)', () => {
  it('нажатие клавиши на ФОНОВОМ элементе не доходит до window-обработчика продукта (bubble-фаза)', async () => {
    const backgroundBtn = document.createElement('button');
    document.body.appendChild(backgroundBtn);
    render(TrialConsentOverlay);
    await tick();

    // Имитация обработчика продукта (handleHomeShortcut/handleCabinetShortcut/handleGlobalShortcut
    // и любого будущего) - обычный window-слушатель без capture, ровно как они регистрируются.
    const productHandlerSpy = vi.fn();
    window.addEventListener('keydown', productHandlerSpy);

    backgroundBtn.focus();
    await fireEvent.keyDown(backgroundBtn, { key: '1' });

    expect(productHandlerSpy).not.toHaveBeenCalled();

    window.removeEventListener('keydown', productHandlerSpy);
    backgroundBtn.remove();
  });

  it('нажатие клавиши ВНУТРИ оверлея (чекбокс) не гасится - работает как обычно', async () => {
    render(TrialConsentOverlay);
    await tick();

    const productHandlerSpy = vi.fn();
    window.addEventListener('keydown', productHandlerSpy);

    const checkbox = screen.getByRole('checkbox');
    await fireEvent.keyDown(checkbox, { key: ' ' });

    expect(productHandlerSpy).toHaveBeenCalledTimes(1);

    window.removeEventListener('keydown', productHandlerSpy);
  });

  it('после принятия условий (visible=false) перехват снимается - фон снова получает клавиши', async () => {
    render(TrialConsentOverlay);
    await tick();

    trialConsentPromptOpen.set(false);
    await tick();

    const backgroundBtn = document.createElement('button');
    document.body.appendChild(backgroundBtn);
    const productHandlerSpy = vi.fn();
    window.addEventListener('keydown', productHandlerSpy);

    backgroundBtn.focus();
    await fireEvent.keyDown(backgroundBtn, { key: '1' });

    expect(productHandlerSpy).toHaveBeenCalledTimes(1);

    window.removeEventListener('keydown', productHandlerSpy);
    backgroundBtn.remove();
  });

  it('второй слой активен ДО монтирования разметки окна (Rust ещё не ответил - находка front-gate-s48)', async () => {
    // Ровно момент между запуском приложения и разрешением промиса
    // get_trial_consent_status: ответа ещё нет, поэтому решение «показывать ли модаль»
    // ещё не принято (trialConsentPromptOpen = false, {#if visible} не смонтирован,
    // overlayEl = null) - но заблокировано быть ОБЯЗАНО, потому что resolved = false.
    trialConsentPromptOpen.set(false);
    trialConsentResolved.set(false);
    render(TrialConsentOverlay);
    await tick();

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument(); // разметки окна ещё нет

    const backgroundBtn = document.createElement('button');
    document.body.appendChild(backgroundBtn);
    const productHandlerSpy = vi.fn();
    window.addEventListener('keydown', productHandlerSpy);

    backgroundBtn.focus();
    await fireEvent.keyDown(backgroundBtn, { key: '1' });

    // `overlayEl` = null → isKeydownOutsideBlockingOverlay возвращает true («цель
    // снаружи») → нажатие гасится. Это правильное поведение: раз окна ещё нет, внутри
    // него быть не может ничто, значит гасить надо всё.
    expect(productHandlerSpy).not.toHaveBeenCalled();

    window.removeEventListener('keydown', productHandlerSpy);
    backgroundBtn.remove();
  });
});
