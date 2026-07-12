#!/usr/bin/env node
/**
 * Runner эвал-харнеса кабинета econometrist.
 *
 * Для каждого кейса манифеста (`fixtures/manifest.json`):
 *  1. собирает сообщение (`build_message.mjs::buildMessage`);
 *  2. в режиме `--dry` — только строит сообщение, БЕЗ вызова CLI (для CI);
 *     иначе — реально запускает `claude -p "<message>" --model sonnet` с
 *     cwd = `New_AI_Agency/econometrist/` (там подхватывается CLAUDE.md
 *     кабинета как системный контекст, а slash-команды — из
 *     `.claude/commands/`), таймаут 180с;
 *  3. прогоняет ответ через все автогрейдеры (`graders.mjs`) — для кейса
 *     `interpret-model-no-optimization` дополнительно навешивает
 *     `honestyMissingStep`;
 *  4. печатает таблицу PASS/FAIL и пишет полный результат в
 *     `results/<timestamp>.json`.
 *
 * Флаги:
 *   --case <id>   — прогнать только один кейс (по id из манифеста)
 *   --dry         — не звать CLI, только построить и напечатать сообщения
 *
 * Выход: exit 1, если хотя бы один грейдер FAIL (или --dry обнаружил
 * ошибку сборки сообщения); иначе exit 0.
 *
 * ВНИМАНИЕ: полный (не --dry) прогон расходует квоту вызовов Claude CLI —
 * см. README.md.
 *
 * @module run_eval
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { buildMessage, buildFacts } from './build_message.mjs';
import { DEFAULT_GRADERS, honestyMissingStep } from './graders.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = path.join(__dirname, 'fixtures');
const RESULTS_DIR = path.join(__dirname, 'results');
// cwd для CLI-вызова: там лежит CLAUDE.md кабинета + .claude/commands/*.md,
// подхватываемые Claude Code как системный промпт и slash-команды.
const CABINET_CWD = path.resolve(__dirname, '../../New_AI_Agency/econometrist');

const CLI_TIMEOUT_MS = 180_000;

/**
 * Кейсы, для которых сверх DEFAULT_GRADERS навешивается точечный грейдер
 * честности об отсутствующем шаге. Ключ — id кейса, значение — грейдер.
 * @type {Record<string, (answerText: string, ctx: { caseId: string, facts: unknown }) => { name: string, pass: boolean, details: string }>}
 */
const EXTRA_GRADERS_BY_CASE = {
  'interpret-model-no-optimization': honestyMissingStep,
};

/**
 * Разбирает argv на флаги `--case <id>` и `--dry`.
 * @param {string[]} argv
 * @returns {{ caseId: string | null, dry: boolean }}
 */
function parseArgs(argv) {
  let caseId = null;
  let dry = false;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--case') {
      caseId = argv[i + 1] ?? null;
      i += 1;
    } else if (argv[i] === '--dry') {
      dry = true;
    }
  }
  return { caseId, dry };
}

/**
 * Загружает манифест кейсов.
 * @returns {{ cases: Array<{ id: string, command: string, args?: string, description: string, data: string[] }> }}
 */
function loadManifest() {
  const raw = readFileSync(path.join(FIXTURES_DIR, 'manifest.json'), 'utf-8');
  return JSON.parse(raw);
}

/**
 * Реально запускает `claude -p --model sonnet` в cwd кабинета, передавая
 * сообщение через stdin (НЕ как аргумент `-p "<message>"`).
 *
 * Два независимых обхода Windows-специфики:
 *  1. Прямой spawn `claude`/`claude.cmd` без shell даёт ENOENT/EINVAL —
 *     npm-shim это .cmd-батник, CreateProcess его не резолвит напрямую.
 *     Обход: `cmd.exe /d /s /c` + `windowsVerbatimArguments: true` —
 *     передаёт каждый аргумент как отдельный элемент массива CreateProcess
 *     (в отличие от `shell: true`, который склеивает всё в одну строку
 *     без экранирования — небезопасно для кириллицы/спецсимволов).
 *  2. Полное сообщение кейса (JSON-факты проекта) — 20-30 тыс. символов;
 *     передача такой строки как аргумента `-p "<message>"` эмпирически
 *     обнаружена битой (`cmd.exe` теряет/портит длинный verbatim-аргумент —
 *     воспроизведено на interpret-model-no-optimization, 20875 симв.,
 *     `exit 1` + мусор в stderr). `--print` в CLI официально поддерживает
 *     чтение промпта из stdin — обходит любой лимит длины аргумента
 *     командной строки Windows (~8191/32767 симв. в зависимости от пути).
 *
 * @param {string} message
 * @returns {Promise<{ ok: true, answer: string } | { ok: false, reason: string, stdout: string, stderr: string }>}
 */
function runClaudeCli(message) {
  return new Promise((resolve) => {
    const isWin = process.platform === 'win32';
    const cliArgs = ['-p', '--model', 'sonnet'];
    const spawnCmd = isWin ? 'cmd.exe' : 'claude';
    const spawnArgs = isWin ? ['/d', '/s', '/c', 'claude', ...cliArgs] : cliArgs;

    let child;
    try {
      child = spawn(spawnCmd, spawnArgs, {
        cwd: CABINET_CWD,
        windowsVerbatimArguments: isWin,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (e) {
      resolve({ ok: false, reason: `spawn failed: ${e.message}`, stdout: '', stderr: '' });
      return;
    }

    let stdout = '';
    let stderr = '';
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      resolve({ ok: false, reason: `timeout after ${CLI_TIMEOUT_MS}ms`, stdout, stderr });
    }, CLI_TIMEOUT_MS);

    child.stdout.on('data', (d) => { stdout += d.toString('utf-8'); });
    child.stderr.on('data', (d) => { stderr += d.toString('utf-8'); });

    child.on('error', (e) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, reason: `spawn error: ${e.message}`, stdout, stderr });
    });

    child.stdin.write(message, 'utf-8');
    child.stdin.end();

    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code !== 0) {
        resolve({ ok: false, reason: `exit code ${code}`, stdout, stderr });
        return;
      }
      resolve({ ok: true, answer: stdout.trim() });
    });
  });
}

/**
 * Прогоняет один кейс: строит сообщение, (не-dry) вызывает CLI, применяет
 * грейдеры. В dry-режиме answer = null и грейдеры не считаются (dry
 * проверяет только то, что сообщение строится без исключений).
 *
 * @param {{ id: string, command: string, args?: string, description: string, data: string[] }} caseDef
 * @param {boolean} dry
 * @returns {Promise<{ caseId: string, description: string, message: string, dry: boolean, cliOk: boolean | null, cliReason: string | null, answer: string | null, graders: Array<{ name: string, pass: boolean, details: string }> }>}
 */
async function runCase(caseDef, dry) {
  const message = buildMessage(caseDef);

  if (dry) {
    return {
      caseId: caseDef.id,
      description: caseDef.description,
      message,
      dry: true,
      cliOk: null,
      cliReason: null,
      answer: null,
      graders: [],
    };
  }

  const cliResult = await runClaudeCli(message);
  if (!cliResult.ok) {
    return {
      caseId: caseDef.id,
      description: caseDef.description,
      message,
      dry: false,
      cliOk: false,
      cliReason: cliResult.reason,
      answer: null,
      graders: [],
    };
  }

  const facts = buildFacts(caseDef);
  const ctx = { caseId: caseDef.id, facts };
  const graderFns = [...DEFAULT_GRADERS];
  if (EXTRA_GRADERS_BY_CASE[caseDef.id]) graderFns.push(EXTRA_GRADERS_BY_CASE[caseDef.id]);

  const graders = graderFns.map((fn) => fn(cliResult.answer, ctx));

  return {
    caseId: caseDef.id,
    description: caseDef.description,
    message,
    dry: false,
    cliOk: true,
    cliReason: null,
    answer: cliResult.answer,
    graders,
  };
}

/**
 * Печатает сводную таблицу PASS/FAIL по всем кейсам/грейдерам в консоль.
 * @param {Array<Awaited<ReturnType<typeof runCase>>>} results
 * @returns {boolean} true, если всё зелёное (или dry без ошибок)
 */
function printSummary(results) {
  let allGreen = true;
  console.log('');
  console.log('='.repeat(78));
  console.log('РЕЗУЛЬТАТЫ ЭВАЛ-ХАРНЕСА KAБИНЕТА econometrist');
  console.log('='.repeat(78));

  for (const r of results) {
    console.log('');
    console.log(`── ${r.caseId} ──`);
    console.log(`   ${r.description}`);

    if (r.dry) {
      console.log(`   [DRY] сообщение построено (${r.message.length} симв.), CLI не вызывался.`);
      continue;
    }

    if (!r.cliOk) {
      allGreen = false;
      console.log(`   [CLI FAIL] ${r.cliReason}`);
      continue;
    }

    for (const g of r.graders) {
      const mark = g.pass ? 'PASS' : 'FAIL';
      if (!g.pass) allGreen = false;
      console.log(`   [${mark}] ${g.name} — ${g.details}`);
    }
  }

  console.log('');
  console.log('='.repeat(78));
  const totalGraders = results.reduce((s, r) => s + r.graders.length, 0);
  const failedGraders = results.reduce((s, r) => s + r.graders.filter((g) => !g.pass).length, 0);
  if (results.every((r) => r.dry)) {
    console.log(`DRY-прогон: ${results.length} кейсов, сообщения построены без ошибок.`);
  } else {
    console.log(`Грейдеров всего: ${totalGraders}, провалено: ${failedGraders}.`);
    console.log(allGreen ? 'ИТОГ: ЗЕЛЁНЫЙ' : 'ИТОГ: ЕСТЬ FAIL');
  }
  console.log('='.repeat(78));

  return allGreen;
}

/**
 * Сохраняет полный результат прогона в results/<timestamp>.json.
 * @param {Array<Awaited<ReturnType<typeof runCase>>>} results
 * @returns {string} путь к файлу
 */
function saveResults(results) {
  mkdirSync(RESULTS_DIR, { recursive: true });
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const filePath = path.join(RESULTS_DIR, `${timestamp}.json`);
  writeFileSync(filePath, JSON.stringify(results, null, 2), 'utf-8');
  return filePath;
}

async function main() {
  const { caseId, dry } = parseArgs(process.argv.slice(2));
  const manifest = loadManifest();

  const cases = caseId ? manifest.cases.filter((c) => c.id === caseId) : manifest.cases;
  if (cases.length === 0) {
    console.error(`Кейс с id "${caseId}" не найден в манифесте.`);
    process.exit(1);
  }

  /** @type {Array<Awaited<ReturnType<typeof runCase>>>} */
  const results = [];
  for (const caseDef of cases) {
    console.log(`Прогон кейса: ${caseDef.id}${dry ? ' [DRY]' : ''}...`);
    // eslint-disable-next-line no-await-in-loop -- намеренно последовательно: не бить квоту параллельными вызовами CLI
    const r = await runCase(caseDef, dry);
    results.push(r);
  }

  const savedPath = saveResults(results);
  console.log(`\nПолный результат сохранён: ${savedPath}`);

  const allGreen = printSummary(results);
  process.exit(allGreen ? 0 : 1);
}

main().catch((e) => {
  console.error('Runner упал с необработанной ошибкой:', e);
  process.exit(1);
});
