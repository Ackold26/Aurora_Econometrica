/**
 * FirstRunTour component tests - v2.1.0 п.6.2
 *
 * Tests:
 *   - Рендерится с шагом 1/8
 *   - Кнопка «Далее» переходит к шагу 2
 *   - Кнопка «Назад» недоступна на шаге 1 (нет кнопки)
 *   - ESC вызывает onDone и записывает в localStorage
 *   - «Пропустить» вызывает onDone и записывает в localStorage
 *   - «Готово» (последний шаг) вызывает onDone
 *   - Прогресс-бар width растёт при навигации вперёд
 *   - role="dialog" + aria-modal="true"
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, screen } from '@testing-library/svelte';
import FirstRunTour from '$lib/components/FirstRunTour.svelte';

// jsdom stub
beforeEach(() => {
  vi.useFakeTimers();
  // Clear localStorage before each test
  localStorage.clear();
  // Stub getBoundingClientRect
  Element.prototype.getBoundingClientRect = vi.fn(() => ({
    top: 200, bottom: 300, left: 100, right: 400,
    width: 300, height: 100, x: 100, y: 200,
  }));
});

afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
});

const TOUR_KEY = 'aurora.firstRunTourCompleted';

describe('FirstRunTour', () => {
  it('рендерит карточку с шагом "1 из 8"', () => {
    const { container } = render(FirstRunTour, {
      props: { onDone: vi.fn() },
    });
    expect(container.querySelector('.frt-counter')?.textContent).toContain('1 из 8');
  });

  it('role=dialog с aria-modal=true', () => {
    const { container } = render(FirstRunTour, {
      props: { onDone: vi.fn() },
    });
    const card = container.querySelector('[role="dialog"]');
    expect(card).toBeTruthy();
    expect(card?.getAttribute('aria-modal')).toBe('true');
  });

  it('первый шаг содержит приветственный заголовок', () => {
    const { container } = render(FirstRunTour, {
      props: { onDone: vi.fn() },
    });
    expect(container.querySelector('.frt-title')?.textContent).toContain('Добро пожаловать');
  });

  it('кнопка «Назад» отсутствует на первом шаге', () => {
    const { container } = render(FirstRunTour, {
      props: { onDone: vi.fn() },
    });
    const backBtn = container.querySelector('.frt-btn-back');
    expect(backBtn).toBeNull();
  });

  it('кнопка «Далее» переходит к шагу 2', async () => {
    const { container } = render(FirstRunTour, {
      props: { onDone: vi.fn() },
    });
    const nextBtn = container.querySelector('.frt-btn-next');
    await fireEvent.click(nextBtn);
    expect(container.querySelector('.frt-counter')?.textContent).toContain('2 из 8');
  });

  it('кнопка «Назад» появляется с шага 2 и возвращает к шагу 1', async () => {
    const { container } = render(FirstRunTour, {
      props: { onDone: vi.fn() },
    });
    const nextBtn = container.querySelector('.frt-btn-next');
    await fireEvent.click(nextBtn); // → шаг 2
    const backBtn = container.querySelector('.frt-btn-back');
    expect(backBtn).toBeTruthy();
    await fireEvent.click(backBtn); // → шаг 1
    expect(container.querySelector('.frt-counter')?.textContent).toContain('1 из 8');
  });

  it('«Пропустить» вызывает onDone и сохраняет в localStorage', async () => {
    const onDone = vi.fn();
    const { container } = render(FirstRunTour, { props: { onDone } });
    const skipBtn = container.querySelector('.frt-btn-skip');
    await fireEvent.click(skipBtn);
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(TOUR_KEY)).toBe('1');
  });

  it('ESC вызывает onDone и сохраняет в localStorage', async () => {
    const onDone = vi.fn();
    const { container } = render(FirstRunTour, { props: { onDone } });
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(TOUR_KEY)).toBe('1');
  });

  it('«Готово» на последнем шаге вызывает onDone', async () => {
    const onDone = vi.fn();
    const { container } = render(FirstRunTour, { props: { onDone } });
    const nextBtn = container.querySelector('.frt-btn-next');
    // Пройти все 8 шагов (последний - «Готово»)
    for (let i = 0; i < 7; i++) {
      await fireEvent.click(container.querySelector('.frt-btn-next'));
    }
    // Теперь последний шаг - кнопка говорит «Готово»
    expect(container.querySelector('.frt-btn-next')?.textContent?.trim()).toBe('Готово');
    await fireEvent.click(container.querySelector('.frt-btn-next'));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('прогресс-бар растёт при переходе вперёд', async () => {
    const { container } = render(FirstRunTour, {
      props: { onDone: vi.fn() },
    });
    const getWidth = () => {
      const bar = container.querySelector('.frt-progress-bar');
      return parseFloat(bar?.style.width ?? '0');
    };

    const w1 = getWidth();
    await fireEvent.click(container.querySelector('.frt-btn-next'));
    const w2 = getWidth();
    expect(w2).toBeGreaterThan(w1);
  });

  it('прогресс-бар корректен: шаг 1 = 1/8 * 100%', () => {
    const { container } = render(FirstRunTour, {
      props: { onDone: vi.fn() },
    });
    const bar = container.querySelector('.frt-progress-bar');
    const width = parseFloat(bar?.style.width ?? '0');
    expect(width).toBeCloseTo((1 / 8) * 100, 1);
  });

  it('backdrop с aria-label="Пропустить тур"', () => {
    const { container } = render(FirstRunTour, {
      props: { onDone: vi.fn() },
    });
    const backdrop = container.querySelector('.frt-backdrop');
    expect(backdrop?.getAttribute('aria-label')).toBe('Пропустить тур');
  });

  it('клик на backdrop вызывает onDone', async () => {
    const onDone = vi.fn();
    const { container } = render(FirstRunTour, { props: { onDone } });
    const backdrop = container.querySelector('.frt-backdrop');
    await fireEvent.click(backdrop);
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
