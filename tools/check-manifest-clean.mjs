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
 * 🔴 Где зовётся (V70, N24 s58): `beforeBuildCommand` базового `src-tauri/tauri.conf.json`,
 * то есть перед КАЖДОЙ сборкой через tauri — `npm run tauri build` и `tauri:build:local`
 * (оверлей локальной редакции `build` не переопределяет). Но той же командой идёт и сама
 * облачная сборка — она зовёт `tauri build` при подменённом манифесте, с резервом и живым
 * замком, и прежняя проверка отказала бы ей по трём признакам сразу (H-3 аудита плана 2.5.9).
 * Поэтому проверка различает СВОЮ облачную сборку: `build-cloud.mjs` передаёт дочернему
 * процессу номер своего процесса в переменной {@link CLOUD_BUILD_ENV}, и если он совпадает
 * с номером в замке прогона, а процесс жив — подмена ожидаема. В этом случае проверяется
 * не рабочий манифест, а резерв обычного: он обязан быть чистым.
 *
 * Переменная без замка, с чужим номером или с мёртвым процессом ничего не снимает:
 * обычная сборка, запущенная ВО ВРЕМЯ чужой облачной, по-прежнему получает отказ.
 *
 * Запуск: npm run check:manifest
 * Код возврата: 0 — чисто, 1 — в дереве следы облачной сборки.
 */
import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** Переменная, в которой облачная сборка передаёт дочерним процессам номер своего процесса. */
export const CLOUD_BUILD_ENV = 'AURORA_CLOUD_BUILD_PID';

/** Пути, которые проверяются, — от корня дерева. */
export function treePaths(root) {
  return {
    manifest: join(root, 'src-tauri', 'Cargo.toml'),
    lockfile: join(root, 'Cargo.lock'),
    manifestBackup: join(root, 'src-tauri', 'Cargo.toml.pre-cloud'),
    lockfileBackup: join(root, 'Cargo.lock.pre-cloud'),
    /** Замок живого прогона: он же брошенный след, если прогон мёртв. */
    runLock: join(root, 'src-tauri', '.cloud-build-running'),
  };
}

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

/** Замок пишется облачной сборкой как JSON {pid, started} — читаем тем же способом. */
function readRunLock(path) {
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    // Разбор «по виду» разошёлся бы с записью молча: нечитаемый замок — брошенный.
    return {};
  }
}

/**
 * Проверить дерево. Возвращает `{ problems, ownCloudBuild }`: `ownCloudBuild` — замок
 * своей облачной сборки, если проверка идёт изнутри неё, иначе `null`.
 */
export function inspectTree(root = ROOT, env = process.env) {
  const paths = treePaths(root);
  const problems = [];
  const holder = readRunLock(paths.runLock);

  const claimed = String(env[CLOUD_BUILD_ENV] || '').trim();
  const own = holder !== null && claimed !== '' && String(holder.pid) === claimed && alive(holder.pid);
  if (own) {
    // 🔴 Изнутри своей облачной сборки подменённый манифест, резерв и замок — не следы, а
    // её рабочее состояние. Но и здесь не «пропуск»: проверяется то, что вернётся в дерево
    // после сборки, — резерв обычного манифеста и замка зависимостей.
    if (!existsSync(paths.manifestBackup)) {
      problems.push(`облачная сборка идёт, а резерва обычного манифеста нет: ${paths.manifestBackup}`);
    } else if (readFileSync(paths.manifestBackup, 'utf8').includes('aurora_gateway')) {
      problems.push('резерв обычного манифеста упоминает крейт шлюза — после сборки в дерево вернётся подмена');
    }
    if (existsSync(paths.lockfileBackup)
      && readFileSync(paths.lockfileBackup, 'utf8').includes('aurora_gateway')) {
      problems.push('резерв замка зависимостей упоминает крейт шлюза — после сборки в дерево вернётся след');
    }
    return { problems, ownCloudBuild: holder };
  }

  if (!existsSync(paths.manifest)) {
    problems.push(`манифест не найден вовсе: ${paths.manifest}`);
  } else if (readFileSync(paths.manifest, 'utf8').includes('aurora_gateway')) {
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
  if (!existsSync(paths.lockfile)) {
    problems.push(`замок зависимостей не найден вовсе: ${paths.lockfile}`);
  } else if (readFileSync(paths.lockfile, 'utf8').includes('aurora_gateway')) {
    problems.push(
      'замок зависимостей упоминает крейт шлюза — след облачной сборки остался в Cargo.lock. ' +
        'Верните файл из системы контроля версий: git checkout -- Cargo.lock',
    );
  }

  for (const path of [paths.manifestBackup, paths.lockfileBackup]) {
    if (existsSync(path)) {
      problems.push(`остался служебный файл облачной сборки: ${path}`);
    }
  }

  // 🔴 Замок живого прогона — не след, а признак идущей сборки. Прежде он числился
  // брошенным наравне с остальными, и сторож давал отказ ВО ВРЕМЯ законной облачной
  // сборки, называя её следом прерванной: назначение сторожа ровно обратное.
  // Отказ здесь остаётся (коммитить, пока манифест подменён, нельзя), но причина
  // называется своя, и действие из неё следует.
  if (holder !== null) {
    if (alive(holder.pid)) {
      problems.push(
        `облачная сборка идёт прямо сейчас (процесс ${holder.pid}, начата ` +
          `${holder.started || 'неизвестно когда'}) — манифест подменён на время прогона. ` +
          'Дождитесь её окончания и повторите проверку',
      );
    } else {
      problems.push(`остался служебный файл облачной сборки: ${paths.runLock}`);
    }
  }

  return { problems, ownCloudBuild: null };
}

function main() {
  const { problems, ownCloudBuild } = inspectTree();
  if (problems.length > 0) {
    console.error('\n[проверка манифеста] ОТКАЗ: дерево хранит следы облачной сборки');
    for (const p of problems) console.error(`  – ${p}`);
    console.error('');
    process.exit(1);
  }
  if (ownCloudBuild) {
    console.log(
      `[проверка манифеста] внутри своей облачной сборки (процесс ${ownCloudBuild.pid}): ` +
        'подмена манифеста ожидаема, резерв обычного манифеста чист',
    );
    return;
  }
  console.log('[проверка манифеста] чисто: обычная поставка не задета');
}

/** Запущен ли файл напрямую (а не импортирован) — с разыменованием junction, как в build-cloud.mjs. */
function startedDirectly(entryPath) {
  if (!entryPath) return false;
  const self = fileURLToPath(import.meta.url);
  const entry = resolve(entryPath);
  if (self === entry) return true;
  try {
    return realpathSync(self) === realpathSync(entry);
  } catch {
    return false;
  }
}

if (startedDirectly(process.argv[1])) {
  main();
}
