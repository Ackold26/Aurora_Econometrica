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
const LEFTOVERS = [
  join(ROOT, 'src-tauri', 'Cargo.toml.pre-cloud'),
  join(ROOT, 'Cargo.lock.pre-cloud'),
  join(ROOT, 'src-tauri', '.cloud-build-running'),
];

const problems = [];

if (!existsSync(MANIFEST)) {
  problems.push(`манифест не найден вовсе: ${MANIFEST}`);
} else if (readFileSync(MANIFEST, 'utf8').includes('aurora_gateway')) {
  problems.push(
    'обычный манифест упоминает крейт шлюза — в дереве осталась подмена от облачной сборки. ' +
      'Верните файл из системы контроля версий: git checkout -- src-tauri/Cargo.toml',
  );
}

for (const path of LEFTOVERS) {
  if (existsSync(path)) {
    problems.push(`остался служебный файл облачной сборки: ${path}`);
  }
}

if (problems.length > 0) {
  console.error('\n[проверка манифеста] ОТКАЗ: дерево хранит следы облачной сборки');
  for (const p of problems) console.error(`  – ${p}`);
  console.error('');
  process.exit(1);
}

console.log('[проверка манифеста] чисто: обычная поставка не задета');
