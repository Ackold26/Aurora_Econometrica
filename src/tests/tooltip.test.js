/**
 * Tooltip component tests - v2.1.0 п.6.1
 *
 * Tests:
 *   - Tooltip не видим изначально
 *   - Появляется после hover + delay
 *   - Скрывается после mouseleave
 *   - ESC закрывает немедленно
 *   - role="tooltip" на bubble
 *   - Пустой text: tooltip bubble не рендерится
 *   - aria-describedby ставится когда tooltip visible
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, act } from '@testing-library/svelte';
import { tick } from 'svelte';
import Tooltip from '$lib/components/Tooltip.svelte';

beforeEach(() => {
  vi.useFakeTimers();
  Element.prototype.getBoundingClientRect = vi.fn(() => ({
    top: 100, bottom: 200, left: 50, right: 300,
    width: 250, height: 100, x: 50, y: 100,
  }));
});

afterEach(() => {
  vi.useRealTimers();
});

/** Advance fake timers AND flush svelte reactivity. */
async function advanceAndFlush(ms) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await tick();
  });
}

describe('Tooltip', () => {
  it('не показывает tooltip bubble изначально', () => {
    const { container } = render(Tooltip, {
      props: { text: 'Тестовая подсказка' },
    });
    expect(container.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('tooltip-wrapper имеет role=group', () => {
    const { container } = render(Tooltip, {
      props: { text: 'Подсказка' },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    expect(wrapper).toBeTruthy();
    expect(wrapper?.getAttribute('role')).toBe('group');
  });

  it('показывает tooltip bubble после mouseenter + delay', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Hello tooltip', delay: 100 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    // Bubble не появился до истечения delay
    expect(container.querySelector('[role="tooltip"]')).toBeNull();
    // Прошло 150ms > delay 100ms - должен появиться
    await advanceAndFlush(150);
    expect(container.querySelector('[role="tooltip"]')).toBeTruthy();
  });

  it('скрывает tooltip bubble после mouseleave', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Hello', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    expect(container.querySelector('[role="tooltip"]')).toBeTruthy();

    await fireEvent.mouseLeave(wrapper);
    await advanceAndFlush(200); // hide delay 100ms
    expect(container.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('ESC закрывает tooltip немедленно', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Подсказка', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    expect(container.querySelector('[role="tooltip"]')).toBeTruthy();

    await act(async () => {
      await fireEvent.keyDown(wrapper, { key: 'Escape' });
      await tick();
    });
    expect(container.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('показывает tooltip bubble на focus (delay=0)', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Focus tooltip', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.focus(wrapper);
    await advanceAndFlush(10);
    expect(container.querySelector('[role="tooltip"]')).toBeTruthy();
  });

  it('скрывает tooltip на blur', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Blur me', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.focus(wrapper);
    await advanceAndFlush(10);
    expect(container.querySelector('[role="tooltip"]')).toBeTruthy();

    await fireEvent.blur(wrapper);
    await advanceAndFlush(200);
    expect(container.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('tooltip bubble содержит правильный текст', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'R² объясняет дисперсию', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    const bubble = container.querySelector('[role="tooltip"]');
    expect(bubble?.textContent).toContain('R²');
  });

  it('пустой text - tooltip bubble не рендерится', async () => {
    const { container } = render(Tooltip, {
      props: { text: '', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    expect(container.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('aria-describedby ставится на trigger когда tooltip видим', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Aria test', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    const trigger = container.querySelector('.tooltip-trigger');
    // Изначально нет
    expect(trigger?.getAttribute('aria-describedby')).toBeNull();
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    // Теперь должен быть
    expect(trigger?.getAttribute('aria-describedby')).toBeTruthy();
  });
});
