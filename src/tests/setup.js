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

// H-10b: NB: do NOT import classifier-patterns здесь — module ref captures
// setup.js's mocked invoke, потом overridden test mock не применяется к
// service. UI test файлы (applied-mode-summary) сами устанавливают
// patternsReady.set(true) в beforeEach.
