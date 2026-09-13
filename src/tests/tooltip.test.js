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
 *   - Пузырь вынесен в корень документа (не внутри обёртки)
 *
 * 🔴 2026-09-13: пузырь живёт в <body>, а не в поддереве компонента - иначе его
 * режет любой предок с прокруткой (снимок владельца, шаг «Отчёт»). Поэтому ищем
 * его по документу, а не по `container` render-а: `container` - это обёртка
 * testing-library, и портированного узла в ней уже нет. Сам факт выноса
 * проверяется отдельным случаем ниже, чтобы правка не откатилась молча.
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

/** Пузырь подсказки: ищем по документу - он портирован в <body>. */
function bubble() {
  return document.body.querySelector('[role="tooltip"]');
}

/** Advance fake timers AND flush svelte reactivity. */
async function advanceAndFlush(ms) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await tick();
  });
}

describe('Tooltip', () => {
  it('не показывает tooltip bubble изначально', () => {
    render(Tooltip, {
      props: { text: 'Тестовая подсказка' },
    });
    expect(bubble()).toBeNull();
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
    expect(bubble()).toBeNull();
    // Прошло 150ms > delay 100ms - должен появиться
    await advanceAndFlush(150);
    expect(bubble()).toBeTruthy();
  });

  it('скрывает tooltip bubble после mouseleave', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Hello', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    expect(bubble()).toBeTruthy();

    await fireEvent.mouseLeave(wrapper);
    await advanceAndFlush(200); // hide delay 100ms
    expect(bubble()).toBeNull();
  });

  it('ESC закрывает tooltip немедленно', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Подсказка', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    expect(bubble()).toBeTruthy();

    await act(async () => {
      await fireEvent.keyDown(wrapper, { key: 'Escape' });
      await tick();
    });
    expect(bubble()).toBeNull();
  });

  it('показывает tooltip bubble на focus (delay=0)', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Focus tooltip', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.focus(wrapper);
    await advanceAndFlush(10);
    expect(bubble()).toBeTruthy();
  });

  it('скрывает tooltip на blur', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Blur me', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.focus(wrapper);
    await advanceAndFlush(10);
    expect(bubble()).toBeTruthy();

    await fireEvent.blur(wrapper);
    await advanceAndFlush(200);
    expect(bubble()).toBeNull();
  });

  it('tooltip bubble содержит правильный текст', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'R² объясняет дисперсию', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    expect(bubble()?.textContent).toContain('R²');
  });

  it('пустой text - tooltip bubble не рендерится', async () => {
    const { container } = render(Tooltip, {
      props: { text: '', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    expect(bubble()).toBeNull();
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

  it('пузырь вынесен в корень документа, а не в поддерево обёртки', async () => {
    // 🔴 Смысл случая: пузырь внутри обёртки режет любой предок с прокруткой или
    // overflow: hidden (снимок владельца 13.09, шаг «Отчёт»). Стоит кому-то
    // вернуть его в поддерево - этот случай упадёт сразу, а не на экране клиента.
    const { container } = render(Tooltip, {
      props: { text: 'Вынесена в корень', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);

    const el = bubble();
    expect(el).toBeTruthy();
    expect(el?.parentElement).toBe(document.body);
    expect(container.querySelector('[role="tooltip"]')).toBeNull();
    // Координаты считаются по окну - позиционирование обязано быть fixed.
    expect(el?.classList.contains('tooltip-bubble')).toBe(true);
    expect(/** @type {HTMLElement} */ (el).style.left).not.toBe('');
    expect(/** @type {HTMLElement} */ (el).style.top).not.toBe('');
  });

  it('соседи в корне документа не пострадали при снятии пузыря', async () => {
    // 🔴 Пузырь лежит в <body> рядом с чужими узлами. Если блок {#if} перестанет
    // быть одноэлементным, Svelte пойдёт снимать разметку по цепочке соседей и
    // снесёт вместе с пузырём всё, что лежит в корне ПОСЛЕ него. Маркер ниже
    // ловит ровно это.
    const marker = document.createElement('div');
    marker.id = 'sosed-marker';
    document.body.appendChild(marker);
    try {
      const { container } = render(Tooltip, { props: { text: 'Сосед', delay: 0 } });
      const wrapper = container.querySelector('.tooltip-wrapper');
      await fireEvent.mouseEnter(wrapper);
      await advanceAndFlush(10);
      expect(bubble()?.parentElement).toBe(document.body);

      await fireEvent.mouseLeave(wrapper);
      await advanceAndFlush(200);
      expect(bubble()).toBeNull();
      // Ни маркер, ни контейнер render-а (он тоже сосед в <body>) не снесены.
      expect(document.getElementById('sosed-marker')).toBe(marker);
      expect(container.isConnected).toBe(true);
      expect(container.querySelector('.tooltip-wrapper')).toBeTruthy();
    } finally {
      marker.remove();
    }
  });

  it('aria-describedby указывает на пузырь в корне документа (связь через границу поддерева)', async () => {
    const { container } = render(Tooltip, {
      props: { text: 'Связь по id', delay: 0 },
    });
    const wrapper = container.querySelector('.tooltip-wrapper');
    await fireEvent.mouseEnter(wrapper);
    await advanceAndFlush(10);
    const describedBy = container.querySelector('.tooltip-trigger')?.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(/** @type {string} */ (describedBy))).toBe(bubble());
  });
});
