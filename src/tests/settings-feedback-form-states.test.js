/**
 * CPD-178: успешная отправка обращения не сообщалась человеку отдельно от кнопки —
 * единственным признаком победы была надпись на самой кнопке, которая в этот же миг гасла
 * и через несколько секунд исчезала по таймеру. Здесь проверяются все три состояния формы
 * обратной связи (`src/routes/settings/+page.svelte`, кнопка «Открыть форму обратной связи»):
 * ожидание, успех, отказ. Каждая проверка обязана краснеть, если убрать соответствующий блок
 * разметки — это и есть сторож «на класс, а не на строку» из реестра.
 *
 * 13.09.2026 программа перестала отправлять обращение сама (см. commands/feedback.rs) — теперь
 * `open_feedback_form` только открывает браузер с предзаполненной формой, без сетевого
 * ожидания. Поэтому здесь нет проверки «12 секунд ожидания»: такого ожидания в текущей
 * реализации не существует, а честная надпись при открытии — короткая и появляется рядом
 * с кнопкой (не на ней).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import SettingsPage from '../routes/settings/+page.svelte';

beforeEach(() => {
  vi.mocked(invoke).mockReset();
});

/** Минимум, нужный странице настроек для монтирования без падения на побочных invoke. */
function mockBaseline(overrides = {}) {
  vi.mocked(invoke).mockImplementation(async (cmd, ...args) => {
    if (cmd === 'get_cabinets') return [];
    if (cmd === 'get_model_settings') return { model: 'sonnet', effort: 'medium' };
    if (overrides[cmd]) return overrides[cmd](...args);
    return null;
  });
}

async function clickFeedbackButton() {
  const btn = await screen.findByRole('button', { name: /Открыть форму обратной связи|Открываю форму/ });
  await fireEvent.click(btn);
}

describe('Настройки — состояния формы обратной связи (CPD-178)', () => {
  it('успех: рядом с формой появляется отдельное подтверждение, кнопка при этом не несёт признака победы', async () => {
    let resolveOpen;
    mockBaseline({
      open_feedback_form: () => new Promise((resolve) => { resolveOpen = resolve; }),
    });

    render(SettingsPage);
    await clickFeedbackButton();

    // Пока invoke не разрешился — кнопка занята, а честная надпись об открытии
    // браузера видна отдельно (не единственный признак успеха на кнопке из CPD-178).
    expect(await screen.findByText('Открываю системный браузер...')).toBeInTheDocument();

    resolveOpen('https://forms.yandex.ru/cloud/fake');

    const success = await screen.findByText(/Форма открылась в отдельном окне браузера/);
    expect(success).toBeInTheDocument();
    // role="status" — сторож эталона Creative Hub: подтверждение обязано быть доступным
    // программе чтения с экрана, а не только зрячим человеком.
    expect(success).toHaveAttribute('role', 'status');

    // Подтверждение не исчезает само — ждём дольше прежнего таймера (3с) и проверяем,
    // что текст остался. Раньше он гас через setTimeout(..., 3000).
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText(/Форма открылась в отдельном окне браузера/)).toBeInTheDocument();

    // Кнопка вернулась в обычный вид — сама по себе она не должна утверждать успех.
    const btn = screen.getByRole('button', { name: 'Открыть форму обратной связи' });
    expect(btn).not.toBeDisabled();
  });

  it('отказ: видимое и понятное сообщение об ошибке, с подсказкой куда написать', async () => {
    mockBaseline({
      open_feedback_form: () => Promise.reject('[FB-001] Форма обратной связи пока не подключена к этой сборке. Напишите нам на sales@auroraai.pro – ответим так же.'),
    });

    render(SettingsPage);
    await clickFeedbackButton();

    const error = (await screen.findAllByText(/Напишите нам на sales@auroraai\.pro/))
      .find((el) => el.classList.contains('fb-error'));
    expect(error).toBeInTheDocument();
    expect(error).toHaveAttribute('role', 'status');
    // Служебный код [FB-001] снят с человеческого текста и лежит только под «Подробности».
    expect(error.textContent).not.toMatch(/\[FB-001\]/);
    expect(await screen.findByText('Подробности')).toBeInTheDocument();

    // Отказ не путают с успехом: подтверждения успеха на экране нет.
    expect(screen.queryByText(/Форма открылась в отдельном окне браузера/)).not.toBeInTheDocument();
  });

  it('ожидание: кнопка занята и честно объясняет, что происходит открытие браузера, а не сеть', async () => {
    let resolveOpen;
    mockBaseline({
      open_feedback_form: () => new Promise((resolve) => { resolveOpen = resolve; }),
    });

    render(SettingsPage);
    await clickFeedbackButton();

    const btn = screen.getByRole('button', { name: 'Открываю форму...' });
    expect(btn).toBeDisabled();
    expect(await screen.findByText('Открываю системный браузер...')).toBeInTheDocument();

    resolveOpen('https://forms.yandex.ru/cloud/fake');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Открыть форму обратной связи' })).not.toBeDisabled();
    });
  });
});
