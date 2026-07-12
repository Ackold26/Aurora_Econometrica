/**
 * Сборка сообщения кейса для CLI-прогона кабинета econometrist.
 *
 * Формат приложения данных — НЕ собственная реализация харнеса, а прямой
 * импорт продовой функции `buildProjectDataBlock` из `src/lib/econ-project-
 * context.js` (правило проекта №10, CLAUDE.md: «Pipeline context — inject
 * в message, не файл»). Так харнес гарантированно бьёт по тому же формату,
 * что реальный runtime кабинета, и автоматически подхватывает любой
 * будущий дрейф контракта — без ручной синхронизации 1:1.
 *
 * @module build_message
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { buildProjectDataBlock } from '../../src/lib/econ-project-context.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = path.join(__dirname, 'fixtures');

/**
 * Читает фикстуру JSON по короткому имени («model-diagnostics» → файл
 * fixtures/model-diagnostics.json).
 * @param {string} name
 * @returns {any}
 */
function loadFixture(name) {
  const p = path.join(FIXTURES_DIR, `${name}.json`);
  const raw = readFileSync(p, 'utf-8');
  return JSON.parse(raw);
}

/**
 * Собирает аргументы `buildProjectDataBlock` из списка data-ключей кейса.
 * Отсутствующий в `data` артефакт передаётся как `null` — так
 * `buildProjectDataBlock` сам отрендерит «нет – шаг «X» не пройден»,
 * воспроизводя реальную ситуацию непройденного шага пайплайна (тест
 * честности interpret-model-no-optimization ровно на этом построен).
 *
 * `val` оборачивается в `{ result: ... }` — фикстура `validation.json`
 * это сырой `ValidationResult`, а контракт `buildProjectDataBlock`
 * ожидает содержимое стора `validateData` целиком (обёртка `.result`,
 * см. `econ-project-context.test.js`).
 *
 * @param {string[]} availableData
 * @returns {{ mod: any, dec: any, opt: any, val: any }}
 */
function loadArtifacts(availableData) {
  const mod = availableData.includes('model-diagnostics') ? loadFixture('model-diagnostics') : null;
  const dec = availableData.includes('decomposition') ? loadFixture('decomposition') : null;
  const opt = availableData.includes('optimization') ? loadFixture('optimization') : null;
  const val = availableData.includes('validation') ? { result: loadFixture('validation') } : null;
  return { mod, dec, opt, val };
}

/**
 * Собирает полное сообщение для CLI-прогона одного кейса манифеста:
 * заголовок slash-команды + блок данных проекта (buildProjectDataBlock).
 *
 * @param {{ command: string, args?: string, data: string[] }} caseDef
 * @returns {string}
 */
export function buildMessage(caseDef) {
  const { command, args, data } = caseDef;
  const argsPart = args ? ` ${args}` : '';
  const header = `/${command}${argsPart}`;

  const { mod, dec, opt, val } = loadArtifacts(data);
  const dataBlock = buildProjectDataBlock({ mod, dec, opt, val });

  return header + dataBlock;
}

/**
 * Возвращает «сырые» факты кейса — используется грейдером numbers_grounded
 * для сверки чисел ответа. Строится из ТЕХ ЖЕ артефактов, что ушли в
 * промпт (через `loadArtifacts`), не шире: если ассистент процитирует
 * число из вырезанной телеметрии optimization (slsqp_diagnostics,
 * response_curves), которой в промпте не было, это обязано считаться
 * негрунд-числом.
 *
 * @param {{ data: string[] }} caseDef
 * @returns {Record<string, any>}
 */
export function buildFacts(caseDef) {
  const { mod, dec, opt, val } = loadArtifacts(caseDef.data);
  /** @type {Record<string, any>} */
  const facts = {};
  if (mod !== null) facts['model-diagnostics'] = mod;
  if (dec !== null) facts.decomposition = dec;
  if (opt !== null) {
    // Та же вырезка телеметрии, что buildProjectDataBlock применяет
    // внутри себя (stripOptTelemetry) — facts должны отражать именно то,
    // что физически присутствовало в промпте.
    const { slsqp_diagnostics, response_curves, ...rest } = opt;
    facts.optimization = rest;
  }
  if (val !== null) facts.validation = val;
  return facts;
}
