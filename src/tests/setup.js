import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// Mock Tauri API invoke
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn().mockResolvedValue(null),
}));

// Mock Tauri dialog plugin
vi.mock('@tauri-apps/plugin-dialog', () => ({
  open: vi.fn().mockResolvedValue(null),
}));

// jsdom не реализует Web Animations API (element.animate), который использует
// Svelte transitions (fly, fade и т.д.). Полифилл-мок: возвращает дешёвый
// объект с одинаковыми методами, чтобы transitions завершались мгновенно.
// Без этого ScenarioWizard с transition:fly падает при mount в тестах.
if (typeof Element !== 'undefined' && typeof Element.prototype.animate !== 'function') {
  Element.prototype.animate = function () {
    const animation = {
      cancel() {},
      finish() {},
      play() {},
      pause() {},
      reverse() {},
      onfinish: null,
      oncancel: null,
      effect: null,
      finished: Promise.resolve(),
      currentTime: 0,
      playState: 'finished',
    };
    // Запускаем onfinish на следующем tick, чтобы transition logic
    // считала анимацию завершённой.
    queueMicrotask(() => {
      if (typeof animation.onfinish === 'function') {
        animation.onfinish();
      }
    });
    return animation;
  };
}

// matchMedia - jsdom тоже не реализует. Если кто-то его читает (например
// $prefersReducedMotion store), отдаём дефолт «не reduce».
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

// H-10b: NB: do NOT import classifier-patterns здесь - module ref captures
// setup.js's mocked invoke, потом overridden test mock не применяется к
// service. UI test файлы (applied-mode-summary) сами устанавливают
// patternsReady.set(true) в beforeEach.
