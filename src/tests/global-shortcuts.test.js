/**
 * s48 (2026-09-14): узкий поведенческий тест на правило «пока окно условий ознакомительного
 * использования открыто - глобальные сочетания клавиш (Ctrl+K/Cmd+K, Ctrl+G/Cmd+G) не
 * работают вовсе». Найдено внешней проверкой: CommandPalette при открытии программно ставит
 * фокус в своё поле ввода независимо от z-index блокирующего оверлея - раньше сочетания
 * срабатывали ПОВЕРХ непринятого согласия и позволяли реально пользоваться программой
 * (открыть кабинет, перейти в Настройки), не нажимая «Принимаю».
 *
 * Функция вынесена в $lib/global-shortcuts.js специально для этого теста - монтировать весь
 * +layout.svelte непомерно тяжело (см. докстринг модуля), а правило проверяется прямым
 * вызовом с поддельным KeyboardEvent.
 */
import { describe, it, expect, vi } from 'vitest';
import { handleGlobalShortcut } from '$lib/global-shortcuts.js';

/** @param {Partial<KeyboardEvent> & {key: string}} overrides */
function fakeCtrlEvent(overrides) {
  return /** @type {KeyboardEvent} */ ({
    ctrlKey: true,
    metaKey: false,
    preventDefault: vi.fn(),
    ...overrides,
  });
}

describe('handleGlobalShortcut - блокировка при открытом окне условий', () => {
  it('Ctrl+K НИЧЕГО не делает, пока окно условий открыто', () => {
    const setPaletteOpen = vi.fn();
    const toggleGlossary = vi.fn();
    const event = fakeCtrlEvent({ key: 'k' });

    handleGlobalShortcut({
      trialConsentOpen: true,
      paletteOpen: false,
      setPaletteOpen,
      toggleGlossary,
      event,
    });

    expect(setPaletteOpen).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it('Ctrl+G НИЧЕГО не делает, пока окно условий открыто', () => {
    const setPaletteOpen = vi.fn();
    const toggleGlossary = vi.fn();
    const event = fakeCtrlEvent({ key: 'g' });

    handleGlobalShortcut({
      trialConsentOpen: true,
      paletteOpen: false,
      setPaletteOpen,
      toggleGlossary,
      event,
    });

    expect(toggleGlossary).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it('после закрытия окна условий Ctrl+K снова открывает палитру (регрессия не превратилась в "навсегда сломано")', () => {
    const setPaletteOpen = vi.fn();
    const toggleGlossary = vi.fn();
    const event = fakeCtrlEvent({ key: 'k' });

    handleGlobalShortcut({
      trialConsentOpen: false,
      paletteOpen: false,
      setPaletteOpen,
      toggleGlossary,
      event,
    });

    expect(setPaletteOpen).toHaveBeenCalledWith(true);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
  });

  it('после закрытия окна условий Ctrl+G снова переключает глоссарий', () => {
    const setPaletteOpen = vi.fn();
    const toggleGlossary = vi.fn();
    const event = fakeCtrlEvent({ key: 'g' });

    handleGlobalShortcut({
      trialConsentOpen: false,
      paletteOpen: false,
      setPaletteOpen,
      toggleGlossary,
      event,
    });

    expect(toggleGlossary).toHaveBeenCalledTimes(1);
  });

  it('Ctrl+G не срабатывает, пока палитра уже открыта (сохранённое поведение v1.3.0)', () => {
    const setPaletteOpen = vi.fn();
    const toggleGlossary = vi.fn();
    const event = fakeCtrlEvent({ key: 'g' });

    handleGlobalShortcut({
      trialConsentOpen: false,
      paletteOpen: true,
      setPaletteOpen,
      toggleGlossary,
      event,
    });

    expect(toggleGlossary).not.toHaveBeenCalled();
  });

  it('Cmd (metaKey) на Mac работает так же, как Ctrl, и тоже блокируется окном условий', () => {
    const setPaletteOpen = vi.fn();
    const toggleGlossary = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({
      ctrlKey: false,
      metaKey: true,
      key: 'k',
      preventDefault: vi.fn(),
    });

    handleGlobalShortcut({
      trialConsentOpen: true,
      paletteOpen: false,
      setPaletteOpen,
      toggleGlossary,
      event,
    });

    expect(setPaletteOpen).not.toHaveBeenCalled();
  });
});
