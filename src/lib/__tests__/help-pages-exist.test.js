// @ts-nocheck — node-side тест (fs/path/url); svelte-check checkJs не имеет
// @types/node в scope. Логика проверяется через vitest, не через типы.
/**
 * Сторож кнопки «Справка по этому шагу» (перестройка справки по шагам,
 * 2026-09-13).
 *
 * Кнопка в шапке мастера зовёт `open_help` с именем страницы из массива
 * HELP_PAGES (`src/routes/pipeline/+layout.svelte`). Rust-команда просто
 * складывает путь и открывает файл во внешнем браузере: если файла нет,
 * НИЧЕГО не падает — клиент получает пустоту по кнопке справки, а сборка
 * остаётся зелёной. Ровно этот дефект и сторожим.
 *
 * Проверяем три инварианта:
 *   1. записей в HELP_PAGES ровно столько же, сколько шагов мастера;
 *   2. каждое имя из HELP_PAGES имеет файл <имя>.html на диске;
 *   3. каждое имя из HELP_PAGES есть в PAGES econ-nav.js — иначе у страницы
 *      не будет ни навбара, ни попадания в поиск по справке.
 *
 * Имена читаются ЖИВЫМ разбором исходников, не замороженным снимком: снимок
 * сверял бы фронт сам с собой и пропустил бы переименование файла справки.
 */
import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { PIPELINE_STEPS } from '../project-state.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

const LAYOUT_PATH = resolve(__dirname, '../../routes/pipeline/+layout.svelte');
const HELP_DIR = resolve(__dirname, '../../../src-tauri/help-econometrica');
const NAV_JS_PATH = resolve(HELP_DIR, 'econ-nav.js');

/** Имена страниц из массива HELP_PAGES в +layout.svelte. */
function parseHelpPages() {
  const src = readFileSync(LAYOUT_PATH, 'utf-8');
  const block = src.match(/const HELP_PAGES\s*=\s*\[([\s\S]*?)\]/);
  if (!block) return [];
  return [...block[1].matchAll(/'([\w-]+)'/g)].map((m) => m[1]);
}

/** Идентификаторы страниц из PAGES в econ-nav.js. */
function parseNavPages() {
  const src = readFileSync(NAV_JS_PATH, 'utf-8');
  const block = src.match(/const PAGES\s*=\s*\[([\s\S]*?)\n\s*\];/);
  if (!block) return [];
  return [...block[1].matchAll(/id:\s*'([\w-]+)'/g)].map((m) => m[1]);
}

describe('справка по шагу мастера', () => {
  const helpPages = parseHelpPages();

  it('парсер вообще что-то нашёл (иначе тест мёртвый)', () => {
    expect(helpPages.length).toBeGreaterThan(0);
    expect(parseNavPages().length).toBeGreaterThan(0);
  });

  it('на каждый шаг мастера есть своя запись', () => {
    expect(helpPages).toHaveLength(PIPELINE_STEPS.length);
  });

  it.each(
    helpPages.map((page, i) => [PIPELINE_STEPS[i]?.labelRu ?? `шаг ${i}`, page]),
  )('шаг «%s» открывает существующий файл %s.html', (_label, page) => {
    expect(existsSync(resolve(HELP_DIR, `${page}.html`))).toBe(true);
  });

  it('каждая страница шага есть в навигации справки (econ-nav.js)', () => {
    const navIds = new Set(parseNavPages());
    const missing = helpPages.filter((p) => !navIds.has(p));
    expect(missing).toEqual([]);
  });
});
