#!/usr/bin/env node
/**
 * Сборка облачной поставки Aurora AI Oracle (ADR-041 + ADR-046).
 *
 * 🔴 Зачем этот скрипт (Н-01 и Н-02 аудита 2026-07-30).
 *
 * Обычный `src-tauri/Cargo.toml` НЕ упоминает крейт шлюза вовсе: слово `optional`
 * управляет компиляцией, но не разрешением графа зависимостей, поэтому одно
 * объявление в общем манифесте ломало обычную поставку — падали проверки, падал
 * выпуск по метке, падал `cargo` у любого, кто просто склонировал проект.
 *
 * Облачная сборка собирает манифест на время прогона: базовый + `Cargo.cloud.fragment.toml`.
 * Фрагмент содержит РОВНО то, что добавляет облачная поставка, поэтому копии манифеста
 * не существует и разъезжаться нечему.
 *
 * Перед сборкой скрипт проверяет крейт по пути из фрагмента: есть ли он и есть ли в нём
 * расширенный контракт. Иначе повторилась бы история этой сессии — «зелёный облачный
 * гейт», снятый с состояния деревьев, которого больше не существует, и сборка,
 * падающая на неизвестных именах вместо внятного отказа.
 *
 * 🔴 Безопасность подмены манифеста (E-1, E-1а, E-2, E-3, E-4, E-9 аудита 2026-07-31).
 *
 * Подмена рабочего файла на время сборки — опасная операция: оставленная подмена ломает
 * ОБЫЧНУЮ сборку, которая уже у клиентов. Прошлая версия восстанавливала манифест только
 * через `finally`, и аудит замерил исполнением: `spawnSync` блокирует поток, поэтому
 * Ctrl+C (консольное событие Windows) убивал процесс ДО `finally` — подмена оставалась
 * в дереве, готовая уехать первой же записью изменений. Отсюда четыре решения:
 *
 *   1. сборка запускается АСИНХРОННО (`spawn`), поток не заблокирован, поэтому
 *      обработчики сигналов действительно успевают сработать;
 *   2. восстановление идемпотентно и висит на всех путях выхода: SIGINT/SIGTERM/SIGHUP/
 *      SIGBREAK, `exit`, необработанное исключение, штатный конец;
 *   3. одновременный второй прогон отсекается файлом-замком: прежде второй прогон
 *      объявлял живой первый «прерванным», вытаскивал манифест из-под него и оставлял
 *      его падать внутри того самого `finally`, который обещает восстановление;
 *   4. в резерв уходит только манифест БЕЗ упоминания шлюза — тогда восстановление
 *      физически не может записать подмену обратно; и вместе с манифестом
 *      восстанавливается `Cargo.lock` (иначе после успешной сборки в дереве оставался
 *      изменённый замок зависимостей — инвариант «обычная поставка не меняется ни в чём»
 *      протекал).
 *
 * Чего этот скрипт по-прежнему НЕ может: жёсткое убийство процесса (`taskkill /F`,
 * SIGKILL, гашение питания) обработчики не проходят. На этот исход остаётся
 * самовосстановление при следующем запуске плюс отдельная проверка чистоты манифеста
 * (`tools/check-manifest-clean.mjs`) — её можно позвать перед обычной сборкой.
 *
 * Запуск: npm run tauri:build:cloud [-- доп-аргументы]
 *         npm run tauri:build:cloud -- --check   (только компиляция, без установщика)
 *         npm run tauri:build:cloud -- --test    (прогон тестов облачного пути)
 */
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, copyFileSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const TAURI_DIR = join(ROOT, 'src-tauri');
const MANIFEST = join(TAURI_DIR, 'Cargo.toml');
const FRAGMENT = join(TAURI_DIR, 'Cargo.cloud.fragment.toml');
/** Резервная копия обычного манифеста на время сборки. */
const BACKUP = join(TAURI_DIR, 'Cargo.toml.pre-cloud');
/**
 * Замок зависимостей: облачная сборка добавляет в него крейт шлюза (E-2).
 *
 * 🔴 Лежит в КОРНЕ дерева, не в `src-tauri/`. Первая версия этой правки резервировала
 * `src-tauri/Cargo.lock` — файла с таким путём не существует, поэтому резерв не снимался,
 * восстановления не было, и десять добавленных строк оставались в дереве. Зонд смотрел на
 * тот же неверный путь и потому был зелёным: и правка, и её проверка смотрели не туда.
 * Поймано `git status`, а не проверкой — сверяться с состоянием дерева обязательно.
 */
const LOCKFILE = join(ROOT, 'Cargo.lock');
const LOCKFILE_BACKUP = join(ROOT, 'Cargo.lock.pre-cloud');
/** Файл-замок против двух одновременных прогонов (E-3). */
const RUN_LOCK = join(TAURI_DIR, '.cloud-build-running');

/** Функции расширенного контракта: без них облачный модуль не соберётся. */
// Контракт v1 (ADR-048): облачный слой Core. Прежние имена SSH-контракта здесь
// уже не проверяются — продукт ими не пользуется, и их наличие ничего не сказало
// бы о том, соберётся ли облачный путь.
const REQUIRED_EXPORTS = ['run_job_watched', 'download_file', 'start_job'];

/** Признак крейта шлюза: его присутствие в базовом манифесте — уже дефект (Н-01). */
const GATEWAY_MARK = 'aurora_gateway';

/** Имя признака облачной поставки. У Эконометрики оно историческое (`thin`),
 *  у Oracle — `cloud`; протокол требует не имени, а того, чтобы объявление жило
 *  во фрагменте и включало сетевой слой. */
const CLOUD_FEATURE = 'thin';

/** Настройка сборки облачной поставки. 🔴 Имя РАЗНОЕ у продуктов: у Oracle
 *  `tauri.cloud.conf.json`, у Эконометрики `tauri.thin.conf.json`. Перенос
 *  скрипта без правки этой строки ломает сборку установщика, а режимы
 *  `--check`/`--test` этого не ловят — они идут через cargo, минуя tauri. */
const CLOUD_CONFIG = 'src-tauri/tauri.thin.conf.json';

function fail(message, hint) {
  console.error(`\n[облачная сборка] ОТКАЗ: ${message}`);
  if (hint) console.error(`[облачная сборка] что делать: ${hint}\n`);
  process.exit(1);
}

function info(message) {
  console.log(`[облачная сборка] ${message}`);
}

// ── Восстановление рабочего дерева ────────────────────────────────────────────

/** Взяли ли мы замок в этом прогоне (снимать чужой замок нельзя). */
let ownsRunLock = false;
/**
 * Подмену манифеста сделали МЫ — значит нам её и убирать.
 *
 * 🔴 Вторая форма E-3, поймана зондом на первой версии этой правки: прогон, который
 * ПРАВИЛЬНО отказался по замку, всё равно доходил до обработчика выхода, видел резерв,
 * оставленный ЖИВЫМ первым прогоном, и восстанавливал манифест из-под него — то есть
 * ровно тот дефект, от которого замок и защищает, только другой дорогой. Чужого резерва
 * не касаемся никогда.
 */
let ownsWorkspaceEdit = false;
/** Восстановление уже сделано — второй раз не нужно и небезопасно. */
let restored = false;
/**
 * Восстановление не удалось — дерево осталось изменённым.
 *
 * 🔴 Находка внешнего аудита 2026-07-31: прежде провал восстановления печатал сообщение,
 * но код возврата оставался нулевым, и вызывающая сторона (обёртка выпуска, гейт, `npm
 * run`) видела успех при подменённом манифесте в дереве. Отказ обязан быть слышен машинно,
 * а не только глазами того, кто смотрит в консоль.
 */
let restoreFailed = false;
/** Текущий дочерний процесс сборки (нужен, чтобы погасить его при прерывании). */
let child = null;

function killChild() {
  if (!child || child.killed) return;
  try {
    child.kill();
  } catch {
    /* уже мёртв */
  }
}

/**
 * Вернуть дерево в обычное состояние. Идемпотентно и молча терпит сбои: функция
 * вызывается в том числе из обработчика сигнала, где бросать уже некуда.
 */
function restoreWorkspace(reason) {
  if (restored) return;
  restored = true;
  if (!ownsWorkspaceEdit) {
    // Подмену делали не мы: резерв в дереве принадлежит другому, возможно живому,
    // прогону. Снимаем только свой замок и уходим, ничего не восстанавливая.
    try {
      if (ownsRunLock && existsSync(RUN_LOCK)) rmSync(RUN_LOCK);
    } catch {
      /* следующий прогон распознает замок как брошенный */
    }
    return;
  }
  let restoredManifest = false;
  try {
    if (existsSync(BACKUP)) {
      // Резерв снимался только с чистого манифеста (см. backupPristineWorkspace),
      // поэтому обратная запись не может вернуть подмену в дерево.
      copyFileSync(BACKUP, MANIFEST);
      rmSync(BACKUP);
      restoredManifest = true;
    } else {
      // 🔴 Резерва нет, а подмену делали МЫ (находка внешнего аудита 2026-07-31). Это
      // аварийное состояние, а не «нечего восстанавливать»: резерв могла унести чистка
      // игнорируемых файлов (`git clean -fdX` — служебные файлы сборки закрыты игнором),
      // и в дереве остаётся манифест с крейтом шлюза. Прежде такой исход не давал ни
      // сообщения, ни ненулевого кода — подмена уезжала в запись молча.
      restoreFailed = true;
      console.error('[облачная сборка] АВАРИЯ: резервная копия манифеста исчезла, '
        + 'а подмена сделана этим прогоном');
      const rescue = spawnSync('git', ['checkout', '--', 'src-tauri/Cargo.toml'],
        { cwd: ROOT, stdio: 'inherit' });
      if (rescue.status === 0) {
        console.error('[облачная сборка] манифест возвращён из системы контроля версий');
        restoredManifest = true;
      } else {
        console.error(`[облачная сборка] верните вручную: git checkout -- ${MANIFEST}`);
      }
    }
  } catch (e) {
    restoreFailed = true;
    console.error(`[облачная сборка] не удалось восстановить манифест: ${e.message}`);
    console.error(`[облачная сборка] восстановите вручную: ${BACKUP} → ${MANIFEST}`);
  }
  try {
    if (existsSync(LOCKFILE_BACKUP)) {
      copyFileSync(LOCKFILE_BACKUP, LOCKFILE);
      rmSync(LOCKFILE_BACKUP);
    }
  } catch (e) {
    console.error(`[облачная сборка] не удалось восстановить замок зависимостей: ${e.message}`);
  }
  try {
    if (ownsRunLock && existsSync(RUN_LOCK)) rmSync(RUN_LOCK);
  } catch {
    /* не критично: следующий прогон распознает замок как брошенный */
  }
  if (restoredManifest) info(`обычный манифест восстановлен (${reason})`);
}

/** Восстановление на всех путях выхода, включая прерывание (E-1, E-1а). */
function installExitGuards() {
  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGBREAK']) {
    process.on(signal, () => {
      // Прерывание = отказ от сборки: гасим дочерний процесс и приводим дерево в порядок.
      killChild();
      restoreWorkspace(`прерывание, ${signal}`);
      process.exit(130); // обычный код для «прервано с клавиатуры»
    });
  }
  process.on('exit', () => restoreWorkspace('выход'));
  process.on('uncaughtException', (e) => {
    killChild();
    restoreWorkspace('необработанное исключение');
    console.error(`\n[облачная сборка] ОТКАЗ: ${e && e.stack ? e.stack : e}`);
    process.exit(1);
  });
}

// ── Замок против двух прогонов (E-3) ─────────────────────────────────────────

/** Жив ли процесс с таким номером (проверка существования, без посылки сигнала). */
function processAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    // EPERM = процесс есть, но чужой; для нас это «жив».
    return Boolean(e && e.code === 'EPERM');
  }
}

/**
 * Взять замок прогона. Второй одновременный прогон обязан отказаться: прежде он
 * объявлял живой первый «прерванным» и вытаскивал манифест из-под него.
 */
function acquireRunLock() {
  if (existsSync(RUN_LOCK)) {
    let holder = {};
    try {
      holder = JSON.parse(readFileSync(RUN_LOCK, 'utf8'));
    } catch {
      /* нечитаемый замок трактуем как брошенный */
    }
    if (processAlive(holder.pid)) {
      fail(
        `облачная сборка уже идёт (процесс ${holder.pid}, начата ${holder.started || 'неизвестно когда'})`,
        `дождитесь её окончания. Если процесс точно мёртв, удалите файл ${RUN_LOCK} и повторите`,
      );
    }
    info('найден замок брошенного прогона — снимаю');
    try {
      rmSync(RUN_LOCK);
    } catch {
      /* попробуем создать заново ниже — исключительная запись поймает столкновение */
    }
  }
  try {
    // 'wx' — создать исключительно: если файл появился между проверкой и записью,
    // будет отказ, а не молча затёртый чужой замок.
    writeFileSync(
      RUN_LOCK,
      JSON.stringify({ pid: process.pid, started: new Date().toISOString() }),
      { encoding: 'utf8', flag: 'wx' },
    );
  } catch (e) {
    fail(
      'не удалось взять замок облачной сборки — вероятно, второй прогон стартовал одновременно',
      `проверьте ${RUN_LOCK} и повторите (${e.code || e.message})`,
    );
  }
  ownsRunLock = true;
}

// ── Проверки и склейка ───────────────────────────────────────────────────────

/** Путь к крейту шлюза, объявленный во фрагменте (единственный источник истины). */
function gatewayPathFromFragment(fragment) {
  const match = fragment.match(/aurora_gateway\s*=\s*\{[^}]*path\s*=\s*"([^"]+)"/);
  if (!match) {
    fail(
      'во фрагменте не нашлось объявление пути к крейту шлюза',
      `проверьте ${FRAGMENT} — там ожидается строка вида aurora_gateway = { path = "…", optional = true }`,
    );
  }
  return resolve(TAURI_DIR, match[1]);
}

/** Крейт на месте и содержит расширенный контракт (иначе сборка упадёт на именах). */
function verifyGatewayCrate(crateDir) {
  const transport = join(crateDir, 'src', 'cloud', 'client.rs');
  if (!existsSync(transport)) {
    fail(
      `крейт шлюза не найден: ${crateDir}`,
      'создайте рабочее дерево Core на основной линии — ' +
        'git -C <путь к aurora-platform-core> worktree add ../_wt_core_main main — ' +
        'либо поправьте путь во фрагменте Cargo.cloud.fragment.toml',
    );
  }
  const source = readFileSync(transport, 'utf8');
  const missing = REQUIRED_EXPORTS.filter((name) => !source.includes(`fn ${name}`));
  if (missing.length > 0) {
    fail(
      `крейт по пути ${crateDir} не содержит облачный контракт v1: нет ${missing.join(', ')}`,
      'дерево Core стоит на ветке без ADR-048 либо это неверсионированная копия крейта; ' +
        'обновите дерево до основной линии (git pull --ff-only) и повторите',
    );
  }
  info(`крейт шлюза проверен: ${crateDir} (контракт на месте)`);
}

/** Базовый манифест + фрагмент. Якоря обязательны: их отсутствие — отказ, не тихая сборка. */
function composeManifest(base, fragment) {
  // 🔴 Переносы строк приводятся к одному виду ДО склейки. Базовый манифест и
  // фрагмент приходят из системы контроля версий с разными окончаниями строк, и
  // смешение даёт одиночный возврат каретки — cargo отказывается разбирать такой
  // файл, указывая на строку манифеста, которого на диске уже нет (он подменён на
  // время сборки). Поймано на первом же продукте со своими признаками.
  base = base.replace(/\r\n/g, '\n');
  fragment = fragment.replace(/\r\n/g, '\n');

  const featuresBlock = fragment.match(/\[features\][\s\S]*?(?=\n\[|$)/);
  const dependencyLine = fragment.match(/^\s*aurora_gateway\s*=.*$/m);
  if (!featuresBlock || !dependencyLine) {
    fail(
      'фрагмент облачной сборки неполон: нужны секция [features] и строка зависимости шлюза',
      `проверьте ${FRAGMENT}`,
    );
  }
  if (base.includes(GATEWAY_MARK)) {
    fail(
      'обычный манифест уже упоминает крейт шлюза — это ровно то, чего быть не должно (Н-01)',
      'уберите объявление из src-tauri/Cargo.toml: облачная поставка получает его из фрагмента. ' +
        'Если файл остался от прерванной облачной сборки, верните его из системы контроля ' +
        'версий: git checkout -- src-tauri/Cargo.toml',
    );
  }
  if (!base.includes('[build-dependencies]')) {
    fail('в манифесте не найдена секция [build-dependencies] — не знаю, куда вставить признак сборки');
  }
  if (!/^\[dependencies\]$/m.test(base)) {
    fail('в манифесте не найдена секция [dependencies] — не знаю, куда вставить зависимость шлюза');
  }

  // 🔴 E-4: две секции [features] в одном манифесте — отказ cargo с указанием на
  // строку файла, которого на диске уже нет (манифест подменён на время сборки).
  // У продукта со своими признаками — а таких большинство — секция уже есть,
  // поэтому строки из фрагмента ДОПИСЫВАЮТСЯ в неё, а не вставляются второй.
  const featureLines = featuresBlock[0]
    .replace(/^\[features\][^\n]*\n?/, '')
    .split('\n')
    .filter((line) => line.trim() && !line.trim().startsWith('#'));
  if (featureLines.length === 0) {
    fail('во фрагменте секция [features] пуста — облачный признак объявить нечем');
  }

  const withFeatures = /^\[features\]$/m.test(base)
    ? base.replace(/^\[features\]$/m, `[features]\n${featureLines.join('\n')}`)
    : base.replace(
        '[build-dependencies]',
        `${featuresBlock[0].trim()}\n\n[build-dependencies]`,
      );
  return withFeatures.replace(
    /^\[dependencies\]$/m,
    `[dependencies]\n${dependencyLine[0].trim()}`,
  );
}

/**
 * Снять резерв ТОЛЬКО с чистого манифеста (без упоминания шлюза) и с замка зависимостей.
 * Так восстановление физически не может вернуть подмену в дерево.
 */
function backupPristineWorkspace(base) {
  if (base.includes(GATEWAY_MARK)) {
    // Сюда мы не доходим — composeManifest уже отказал, — но проверка стоит второй раз
    // намеренно: цена ошибки это записанная в дерево подмена.
    fail('отказываюсь снимать резерв с манифеста, упоминающего крейт шлюза');
  }
  copyFileSync(MANIFEST, BACKUP);
  if (existsSync(LOCKFILE)) copyFileSync(LOCKFILE, LOCKFILE_BACKUP);
}

/** Прерванный прошлый прогон мог оставить подменённый манифест — восстановить сразу. */
function recoverFromInterruptedRun() {
  if (!existsSync(BACKUP) && !existsSync(LOCKFILE_BACKUP)) return;
  info('обнаружен резерв от прерванного прогона — восстанавливаю');
  if (existsSync(BACKUP)) {
    copyFileSync(BACKUP, MANIFEST);
    rmSync(BACKUP);
  }
  if (existsSync(LOCKFILE_BACKUP)) {
    copyFileSync(LOCKFILE_BACKUP, LOCKFILE);
    rmSync(LOCKFILE_BACKUP);
  }
}

/**
 * Запустить сборку и дождаться кода возврата, НЕ блокируя поток (E-1).
 *
 * 🔴 `useShell` обязателен для `npx` на Windows (находка внешнего аудита 2026-07-31).
 * Начиная с Node 18.20.2 запуск `.cmd`/`.bat` без оболочки запрещён (закрытие
 * CVE-2024-27980) и `spawn` бросает `EINVAL` СИНХРОННО. Прежняя версия скрипта звала
 * `npx` через оболочку и работала; переход на прямой запуск сломал ровно тот путь,
 * который делает установщик, — и ни один гейт этого не увидел, потому что проверка и
 * прогон тестов идут через `cargo`, настоящий исполняемый файл, на который запрет не
 * распространяется. Для `cargo` оболочка не нужна: аргументы уезжают массивом, и
 * экранировать нечего (E-9).
 */
function runBuild(cmd, args, useShell) {
  return new Promise((finish) => {
    child = spawn(cmd, args, { cwd: ROOT, stdio: 'inherit', shell: useShell });
    child.on('error', (e) => {
      console.error(`[облачная сборка] не удалось запустить ${cmd}: ${e.message}`);
      finish(1);
    });
    child.on('close', (code, signal) => {
      child = null;
      if (signal) {
        console.error(`[облачная сборка] сборка прервана сигналом ${signal}`);
        finish(130);
        return;
      }
      finish(code ?? 1);
    });
  });
}

async function main() {
  installExitGuards();
  acquireRunLock();
  recoverFromInterruptedRun();

  if (!existsSync(FRAGMENT)) fail(`не найден фрагмент облачной сборки: ${FRAGMENT}`);
  const base = readFileSync(MANIFEST, 'utf8');
  const fragment = readFileSync(FRAGMENT, 'utf8');

  verifyGatewayCrate(gatewayPathFromFragment(fragment));

  const composed = composeManifest(base, fragment);
  backupPristineWorkspace(base);
  // С этой секунды дерево изменено НАМИ — и восстанавливать его наша обязанность.
  ownsWorkspaceEdit = true;

  const extra = process.argv.slice(2);
  // Режим `--check`: только компиляция облачного пути, без упаковки установщика.
  // Нужен, чтобы проверять облачную линию быстро и часто — именно её отсутствие
  // в проверках позволило дожить до состояния «облачная сборка не компилируется
  // вовсе, а гейт числится зелёным» (Н-02 аудита 2026-07-30).
  const checkOnly = extra.includes('--check');
  // Режим `--test`: прогон тестов облачного пути. Без него тесты облачного модуля
  // недостижимы вовсе — признак `cloud` существует только в манифесте, который собирает
  // этот инструмент, и `cargo test` из `src-tauri` о нём не знает. То есть их нельзя было
  // ни запустить, ни покрасить откатом правки.
  const testOnly = !checkOnly && extra.includes('--test');
  const passThrough = extra.filter((a) => a !== '--check' && a !== '--test');
  const isWindows = process.platform === 'win32';
  let cmd;
  let args;
  let useShell = false;  // оболочка нужна только пути установщика на Windows
  if (checkOnly) {
    cmd = 'cargo';
    args = ['check', '--manifest-path', 'src-tauri/Cargo.toml', '--features', CLOUD_FEATURE, ...passThrough];
  } else if (testOnly) {
    cmd = 'cargo';
    args = ['test', '--manifest-path', 'src-tauri/Cargo.toml', '--features', CLOUD_FEATURE, ...passThrough];
  } else {
    // 🔴 Через оболочку: прямой запуск npx.cmd бросает EINVAL на Node 18.20.2+
    // (см. пояснение у runBuild). Здесь же оболочка безопасна: аргументы наши, не
    // пользовательские, и в них нет ничего, что оболочка могла бы истолковать.
    cmd = 'npx';
    useShell = isWindows;
    args = [
      'tauri',
      'build',
      '--config',
      CLOUD_CONFIG,
      ...passThrough,
      '--',
      '--features',
      CLOUD_FEATURE,
    ];
  }

  writeFileSync(MANIFEST, composed, 'utf8');
  info(
    checkOnly
      ? 'манифест собран (базовый + фрагмент), проверяю компиляцию облачного пути'
      : testOnly
        ? 'манифест собран (базовый + фрагмент), прогоняю тесты облачного пути'
        : 'манифест собран (базовый + фрагмент), запускаю сборку',
  );
  // E-9: прежде в режиме проверки доп-аргументы молча пропадали.
  if (passThrough.length > 0) info(`доп-аргументы: ${passThrough.join(' ')}`);

  const code = await runBuild(cmd, args, useShell);
  restoreWorkspace('сборка закончена');
  if (code !== 0) fail(`сборка завершилась с кодом ${code}`);
  if (restoreFailed) {
    fail('сборка прошла, но дерево осталось изменённым — восстановить манифест не удалось',
      'проверьте src-tauri/Cargo.toml: он не должен упоминать крейт шлюза. '
        + 'Вернуть можно командой git checkout -- src-tauri/Cargo.toml');
  }
  info('готово');
}

main();
