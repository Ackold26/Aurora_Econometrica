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
import { handleGlobalShortcut, handleHomeShortcut, handleCabinetShortcut, isKeydownOutsideBlockingOverlay } from '$lib/global-shortcuts.js';

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

describe('handleHomeShortcut - блокировка при открытом окне условий (главная страница)', () => {
  it('Ctrl+, НИЧЕГО не делает, пока окно условий открыто', () => {
    const gotoSettings = vi.fn();
    const openCabinetByIndex = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({ ctrlKey: true, key: ',', preventDefault: vi.fn() });

    handleHomeShortcut({
      trialConsentOpen: true,
      event,
      layoutCabinets: [{ id: 'a' }],
      gotoSettings,
      openCabinetByIndex,
    });

    expect(gotoSettings).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it('цифра 1 НИЧЕГО не делает (не открывает кабинет), пока окно условий открыто', () => {
    const gotoSettings = vi.fn();
    const openCabinetByIndex = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({ ctrlKey: false, altKey: false, metaKey: false, key: '1', target: { tagName: 'BODY' } });

    handleHomeShortcut({
      trialConsentOpen: true,
      event,
      layoutCabinets: [{ id: 'a' }],
      gotoSettings,
      openCabinetByIndex,
    });

    expect(openCabinetByIndex).not.toHaveBeenCalled();
  });

  it('после закрытия окна условий Ctrl+, снова ведёт в Настройки', () => {
    const gotoSettings = vi.fn();
    const openCabinetByIndex = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({ ctrlKey: true, key: ',', preventDefault: vi.fn() });

    handleHomeShortcut({
      trialConsentOpen: false,
      event,
      layoutCabinets: [{ id: 'a' }],
      gotoSettings,
      openCabinetByIndex,
    });

    expect(gotoSettings).toHaveBeenCalledTimes(1);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
  });

  it('после закрытия окна условий цифра 1 открывает первый кабинет (регрессия не превратилась в "навсегда сломано")', () => {
    const gotoSettings = vi.fn();
    const openCabinetByIndex = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({ ctrlKey: false, altKey: false, metaKey: false, key: '1', target: { tagName: 'BODY' } });

    handleHomeShortcut({
      trialConsentOpen: false,
      event,
      layoutCabinets: [{ id: 'a' }],
      gotoSettings,
      openCabinetByIndex,
    });

    expect(openCabinetByIndex).toHaveBeenCalledWith(0);
  });

  it('цифра 1 не срабатывает внутри поля ввода (сохранённое поведение)', () => {
    const gotoSettings = vi.fn();
    const openCabinetByIndex = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({ ctrlKey: false, altKey: false, metaKey: false, key: '1', target: { tagName: 'INPUT' } });

    handleHomeShortcut({
      trialConsentOpen: false,
      event,
      layoutCabinets: [{ id: 'a' }],
      gotoSettings,
      openCabinetByIndex,
    });

    expect(openCabinetByIndex).not.toHaveBeenCalled();
  });
});

describe('handleCabinetShortcut - блокировка при открытом окне условий (кабинет)', () => {
  it('Ctrl+Shift+Z НИЧЕГО не делает, пока окно условий открыто', () => {
    const setZenMode = vi.fn();
    const cancelBrief = vi.fn();
    const setWorkspaceMode = vi.fn();
    const goBack = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({ ctrlKey: true, shiftKey: true, key: 'z', preventDefault: vi.fn() });

    handleCabinetShortcut({
      trialConsentOpen: true,
      event,
      zenMode: false,
      setZenMode,
      pendingBriefCommand: null,
      cancelBrief,
      workspaceMode: 'selection',
      setWorkspaceMode,
      goBack,
    });

    expect(setZenMode).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it('Escape НИЧЕГО не делает (не выходит назад), пока окно условий открыто', () => {
    const setZenMode = vi.fn();
    const cancelBrief = vi.fn();
    const setWorkspaceMode = vi.fn();
    const goBack = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({ key: 'Escape', target: { tagName: 'BODY' } });

    handleCabinetShortcut({
      trialConsentOpen: true,
      event,
      zenMode: false,
      setZenMode,
      pendingBriefCommand: null,
      cancelBrief,
      workspaceMode: 'execution',
      setWorkspaceMode,
      goBack,
    });

    expect(setWorkspaceMode).not.toHaveBeenCalled();
    expect(goBack).not.toHaveBeenCalled();
  });

  it('после закрытия окна условий Ctrl+Shift+Z снова переключает дзен-режим', () => {
    const setZenMode = vi.fn();
    const cancelBrief = vi.fn();
    const setWorkspaceMode = vi.fn();
    const goBack = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({ ctrlKey: true, shiftKey: true, key: 'z', preventDefault: vi.fn() });

    handleCabinetShortcut({
      trialConsentOpen: false,
      event,
      zenMode: false,
      setZenMode,
      pendingBriefCommand: null,
      cancelBrief,
      workspaceMode: 'selection',
      setWorkspaceMode,
      goBack,
    });

    expect(setZenMode).toHaveBeenCalledWith(true);
  });

  it('после закрытия окна условий Escape снова ведёт назад (регрессия не превратилась в "навсегда сломано")', () => {
    const setZenMode = vi.fn();
    const cancelBrief = vi.fn();
    const setWorkspaceMode = vi.fn();
    const goBack = vi.fn();
    const event = /** @type {KeyboardEvent} */ ({ key: 'Escape', target: { tagName: 'BODY' } });

    handleCabinetShortcut({
      trialConsentOpen: false,
      event,
      zenMode: false,
      setZenMode,
      pendingBriefCommand: null,
      cancelBrief,
      workspaceMode: 'selection',
      setWorkspaceMode,
      goBack,
    });

    expect(goBack).toHaveBeenCalledTimes(1);
  });
});

describe('isKeydownOutsideBlockingOverlay - предикат второго слоя защиты', () => {
  it('цель ВНУТРИ оверлея - не гасить (false)', () => {
    const overlayEl = document.createElement('div');
    const inner = document.createElement('button');
    overlayEl.appendChild(inner);

    expect(isKeydownOutsideBlockingOverlay(overlayEl, inner)).toBe(false);
    expect(isKeydownOutsideBlockingOverlay(overlayEl, overlayEl)).toBe(false);
  });

  it('цель СНАРУЖИ оверлея - гасить (true)', () => {
    const overlayEl = document.createElement('div');
    const outside = document.createElement('button');

    expect(isKeydownOutsideBlockingOverlay(overlayEl, outside)).toBe(true);
  });

  it('оверлей ещё не смонтирован (null) - гасить на всякий случай (true)', () => {
    const outside = document.createElement('button');
    expect(isKeydownOutsideBlockingOverlay(null, outside)).toBe(true);
  });

  it('цель не Node (null/undefined) - гасить на всякий случай (true)', () => {
    const overlayEl = document.createElement('div');
    expect(isKeydownOutsideBlockingOverlay(overlayEl, null)).toBe(true);
    expect(isKeydownOutsideBlockingOverlay(overlayEl, undefined)).toBe(true);
  });
});
