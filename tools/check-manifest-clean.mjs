#!/usr/bin/env node
/**
 * Проверка: дерево не хранит следов облачной сборки (E-1 аудита 2026-07-31).
 *
 * Облачная сборка подменяет `src-tauri/Cargo.toml` на время прогона. Инструмент
 * (`tools/build-cloud.mjs`) восстанавливает файл на всех путях выхода, включая
 * прерывание с клавиатуры, — но жёсткое убийство процесса (`taskkill /F`, гашение
 * питания) не проходит ни один обработчик. На этот исход и стоит эта проверка: она
 * дешёвая, и её место — перед обычной сборкой и перед выпуском.
 *
 * Почему это важно: манифест с объявлением крейта шлюза ломает ОБЫЧНУЮ поставку целиком
 * (слово `optional` управляет компиляцией, но не разрешением графа зависимостей — Н-01),
 * а сам файл лежит под контролем версий и уедет в запись первой же командой `commit -am`.
 *
 * Запуск: npm run check:manifest
 * Код возврата: 0 — чисто, 1 — в дереве следы облачной сборки.
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const MANIFEST = join(ROOT, 'src-tauri', 'Cargo.toml');
const LOCKFILE = join(ROOT, 'Cargo.lock');
const LEFTOVERS = [
  join(ROOT, 'src-tauri', 'Cargo.toml.pre-cloud'),
  join(ROOT, 'Cargo.lock.pre-cloud'),
];
/** Замок живого прогона: он же брошенный след, если прогон мёртв. */
const RUN_LOCK = join(ROOT, 'src-tauri', '.cloud-build-running');

/** Жив ли процесс с таким номером (проверка существования, без посылки сигнала). */
function alive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    // EPERM — процесс есть, но чужой: значит жив.
    return e && e.code === 'EPERM';
  }
}

const problems = [];

if (!existsSync(MANIFEST)) {
  problems.push(`манифест не найден вовсе: ${MANIFEST}`);
} else if (readFileSync(MANIFEST, 'utf8').includes('aurora_gateway')) {
  problems.push(
    'обычный манифест упоминает крейт шлюза — в дереве осталась подмена от облачной сборки. ' +
      'Верните файл из системы контроля версий: git checkout -- src-tauri/Cargo.toml',
  );
}

// 🔴 Замок зависимостей проверяется наравне с манифестом. Прежде сторож смотрел
// только сам манифест и служебные файлы — а след облачной сборки остаётся и в
// `Cargo.lock`: снятие сборки на Windows гасит оболочку, но не внуков, и живой
// `cargo` дописывает замок УЖЕ ПОСЛЕ того, как манифест восстановлен. Сторож
// при этом рапортовал «чисто», и запись увозила замок со шлюзом в обычную
// поставку — где крейта нет вовсе.
if (!existsSync(LOCKFILE)) {
  problems.push(`замок зависимостей не найден вовсе: ${LOCKFILE}`);
} else if (readFileSync(LOCKFILE, 'utf8').includes('aurora_gateway')) {
  problems.push(
    'замок зависимостей упоминает крейт шлюза — след облачной сборки остался в Cargo.lock. ' +
      'Верните файл из системы контроля версий: git checkout -- Cargo.lock',
  );
}

for (const path of LEFTOVERS) {
  if (existsSync(path)) {
    problems.push(`остался служебный файл облачной сборки: ${path}`);
  }
}

// 🔴 Замок живого прогона — не след, а признак идущей сборки. Прежде он числился
// брошенным наравне с остальными, и сторож давал отказ ВО ВРЕМЯ законной облачной
// сборки, называя её следом прерванной: назначение сторожа ровно обратное.
// Отказ здесь остаётся (коммитить, пока манифест подменён, нельзя), но причина
// называется своя, и действие из неё следует.
if (existsSync(RUN_LOCK)) {
  // Замок пишется облачной сборкой как JSON {pid, started} — читаем тем же
  // способом, каким пишем: разбор «по виду» разошёлся бы с записью молча.
  let holder = {};
  try {
    holder = JSON.parse(readFileSync(RUN_LOCK, 'utf8'));
  } catch {
    holder = {};
  }
  if (alive(holder.pid)) {
    problems.push(
      `облачная сборка идёт прямо сейчас (процесс ${holder.pid}, начата ` +
        `${holder.started || 'неизвестно когда'}) — манифест подменён на время прогона. ` +
        'Дождитесь её окончания и повторите проверку',
    );
  } else {
    problems.push(`остался служебный файл облачной сборки: ${RUN_LOCK}`);
  }
}

if (problems.length > 0) {
  console.error('\n[проверка манифеста] ОТКАЗ: дерево хранит следы облачной сборки');
  for (const p of problems) console.error(`  – ${p}`);
  console.error('');
  process.exit(1);
}

console.log('[проверка манифеста] чисто: обычная поставка не задета');
