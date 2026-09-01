#!/usr/bin/env node
/**
 * Сторож СОСТАВА поставки: есть ли шлюз Авроры в собранном двоичном файле (CPD-87, CPD-115).
 *
 * 🔴 Зачем этот файл — ни один существующий гейт этого не проверяет.
 * `tools/build-cloud.mjs` проверяет РЕЦЕПТ сборки (метку крейта, контракт, признак) и
 * бессилен против сборки в обход себя. `tools/check-installer-edition.mjs` проверяет
 * ЛИЦО продукта — идентификатор редакции, — а не его начинку. Между ними осталась дыра
 * ровно того размера, из-за которого запись CPD-115 вообще возможна: сборка зелёная,
 * все гейты зелёные, суммы сходятся, а шлюза внутри нет, и клиент без своего Claude Code
 * не выполняет ничего. Так уехал установщик 2.4.10.
 *
 * Проверяется ГОТОВЫЙ АРТЕФАКТ, а не конфигурация: это единственный способ поймать и
 * ручную сборку `npm run tauri build`, и будущий CI, и забытую команду.
 *
 * ## Признаки и почему именно они
 *
 * 🔴 Прямая проба по кодам отказа (`TC-GW-`) НЕ РЕШАЮЩАЯ — измерено, а не предположено.
 * В выпущенном `aurora-econometrica-gui.exe` от 15.08, где шлюза нет вовсе, `TC-GW-`
 * встречается ОДИН раз: коды перечислены во встроенной справке продукта, которая едет в
 * бинарь ресурсом независимо от того, вкомпилён ли облачный путь. Порог «больше нуля» на
 * этой строке дал бы зелёный гейт на поставке без шлюза — ровно тот исход, против
 * которого сторож и написан. Число остаётся в отчёте как диагностика, но вердикта не
 * решает.
 *
 * Решают два имени из самого кода:
 *   • `gateway_executor` — имя модуля ПРОДУКТА. Не зависит от версии крейта Core вовсе,
 *     поэтому переживает любое обновление метки;
 *   • `aurora_gateway` — имя крейта общего слоя. Зависит от того, как крейт назван, и
 *     это правильная зависимость: переименуют крейт — сторож обязан покраснеть и
 *     заставить пересмотреть себя, а не молча зеленеть на изменившемся составе.
 *
 * Обратный признак — строка «Облачный режим не входит в эту сборку» (`execution_mode.rs`).
 * Она достижима ТОЛЬКО в сборке без облачного пути: с признаком `cloud_built_in()`
 * схлопывается в константу, ветка становится недостижимой и литерал выбрасывается
 * компилятором. Проверять наличие того, чего быть НЕ должно, надёжнее, чем отсутствие
 * того, что должно быть (приём из CPD-87).
 *
 * 🔴 Контрольная строка обязательна. Первый прогон пробы по линейке однажды дал ноль у
 * ВСЕХ продуктов, включая заведомо облачные, — потому что `ls` дописывает звёздочку к
 * исполняемым файлам и путь становился несуществующим (CPD-87). Без контроля это
 * читается как «регресс у всех». Здесь: не нашли контрольную строку — значит смотрим не
 * туда, и это ОТКАЗ, а не «шлюза нет».
 *
 * ## Чего этот сторож НЕ умеет
 *
 * Установщик NSIS (`*-setup.exe`) внутри сжат: строк кода в нём не найти, и проба на нём
 * дала бы ложное «шлюза нет». Такие файлы пропускаются ЯВНО и называются вслух — молчание
 * читалось бы как «проверено и сошлось». Проверять надо распакованный бинарь продукта:
 * либо из каталога сборки, либо из установленной программы.
 *
 * Запуск:
 *   node tools/check-gateway-in-build.mjs <путь к .exe или каталогу>
 *   node tools/check-gateway-in-build.mjs            (каталог сборки по умолчанию)
 *
 * Код возврата: 0 — шлюз на месте во всех проверенных файлах; 1 — нет, противоречие,
 * либо проверять оказалось нечего.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** Каталог сборки по умолчанию — тот же, что называет CLAUDE.md продукта. */
const DEFAULT_TARGET = process.env.CARGO_TARGET_DIR
  ? join(process.env.CARGO_TARGET_DIR, 'release')
  : join(ROOT, 'src-tauri', 'target', 'release');

/** Имена, решающие вердикт: их присутствие и означает облачный путь в бинаре. */
const GATEWAY_MARKS = ['gateway_executor', 'aurora_gateway'];

/** Строка, живущая ТОЛЬКО в сборке без облачного пути (обратный признак). */
const NO_CLOUD_MARK = 'Облачный режим не входит в эту сборку';

/** Диагностика, не вердикт: в бинаре БЕЗ шлюза встречается один раз (встроенная справка). */
const DIAGNOSTIC_MARK = 'TC-GW-';

/**
 * Контроль «мы вообще читаем бинарь ПРОДУКТА». Любая из строк — свидетельство того, что
 * файл распакован и это оболочка кабинетов; ни одной — проба смотрит не туда.
 *
 * 🔴 Слово `aurora` в контроль НЕ входит, хотя напрашивается первым. Оно есть в любом
 * нашем двоичном файле, включая вспомогательные: обход каталога установленной программы
 * поймал на этом `bin/aurora-llm.exe` — шлюз провайдеров моделей, отдельная программа без
 * кабинетов, — признал его бинарём продукта и вынес по нему вердикт о составе поставки.
 * Контроль обязан различать продукт и его спутников, иначе он подтверждает не то.
 */
const CONTROL_MARKS = ['content-packs', 'cabinets.json', 'claude-stream'];

function info(message) {
  console.log(`[состав поставки] ${message}`);
}

/** Сколько раз строка встречается в буфере. Строки Rust лежат в UTF-8, как и ищем. */
function countOccurrences(buffer, needle) {
  const pattern = Buffer.from(needle, 'utf8');
  let count = 0;
  let from = 0;
  for (;;) {
    const at = buffer.indexOf(pattern, from);
    if (at === -1) return count;
    count += 1;
    from = at + 1;
  }
}

/** Двоичные файлы продукта, пригодные к проверке, и отдельно — пропущенные с причиной. */
export function collectBinaries(target) {
  const takeable = [];
  const skipped = [];
  const consider = (file) => {
    const name = basename(file).toLowerCase();
    if (!name.endsWith('.exe')) return;
    if (name === 'uninstall.exe') {
      skipped.push([file, 'программа удаления, кода продукта в ней нет']);
      return;
    }
    if (name.includes('-setup') || name.includes('_setup')) {
      skipped.push([file, 'установщик сжат — строк кода в нём не найти, проверять надо распакованный бинарь']);
      return;
    }
    takeable.push(file);
  };
  if (statSync(target).isDirectory()) {
    const walk = (dir, depth) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name);
        // Промежуточные результаты компиляции продуктом не являются: `deps`, `build`,
        // `incremental` полны чужих и временных файлов, и вердикт по ним не значит ничего.
        if (entry.isDirectory()) {
          if (['deps', 'build', 'incremental', '.fingerprint'].includes(entry.name)) continue;
          if (depth > 0) walk(full, depth - 1);
        } else {
          consider(full);
        }
      }
    };
    walk(target, 3);
  } else {
    consider(target);
  }
  return { takeable, skipped };
}

/** Вердикт по одному файлу. */
export function judge(buffer) {
  const found = Object.fromEntries(GATEWAY_MARKS.map((m) => [m, countOccurrences(buffer, m)]));
  const noCloud = countOccurrences(buffer, NO_CLOUD_MARK);
  const diagnostic = countOccurrences(buffer, DIAGNOSTIC_MARK);
  const control = CONTROL_MARKS.reduce((sum, m) => sum + countOccurrences(buffer, m), 0);
  const present = GATEWAY_MARKS.filter((m) => found[m] > 0);

  if (control === 0) {
    return {
      state: 'проба-мимо',
      found, noCloud, diagnostic, control,
      why: 'ни одной контрольной строки продукта — файл сжат, повреждён либо это вообще не бинарь продукта',
    };
  }
  if (present.length === GATEWAY_MARKS.length && noCloud === 0) {
    return { state: 'шлюз-есть', found, noCloud, diagnostic, control };
  }
  if (present.length === 0 && noCloud > 0) {
    return {
      state: 'шлюза-нет',
      found, noCloud, diagnostic, control,
      why: 'ни одного имени облачного пути, и на месте строка «облачного режима нет» — поставка собрана штатной командой',
    };
  }
  // 🔴 Неоднозначность НЕ трактуется в пользу зелёного: половина признаков означает, что
  // состав поставки изменился так, как этот сторож не знает, и молчать об этом нельзя.
  return {
    state: 'противоречие',
    found, noCloud, diagnostic, control,
    why: `часть признаков на месте, часть нет (${GATEWAY_MARKS.map((m) => `${m}=${found[m]}`).join(', ')}, `
      + `«облачного режима нет»=${noCloud}) — состав поставки изменился, разберитесь и научите сторожа`,
  };
}

function main() {
  const argument = process.argv[2];
  const target = resolve(argument || DEFAULT_TARGET);
  if (!existsSync(target)) {
    console.error(`[состав поставки] ОТКАЗ: не найдено: ${target}`);
    console.error('[состав поставки] что делать: укажите путь к собранному .exe либо к каталогу сборки');
    process.exit(1);
  }

  const { takeable, skipped } = collectBinaries(target);
  for (const [file, why] of skipped) info(`пропущен ${basename(file)}: ${why}`);
  if (takeable.length === 0) {
    console.error(`[состав поставки] ОТКАЗ: проверять нечего — в ${target} нет двоичных файлов продукта`);
    console.error('[состав поставки] что делать: «нечего проверять» не значит «проверено». '
      + 'Укажите распакованный бинарь продукта, а не установщик');
    process.exit(1);
  }

  // 🔴 Один и тот же исход читается по-разному в зависимости от того, ЧТО спросили.
  // Указали файл прямо — «это не бинарь продукта» есть отказ: спросили не о том. Обходим
  // каталог — тот же исход есть пропуск с названной причиной: рядом с продуктом законно
  // лежат его спутники (шлюз моделей, вспомогательные программы), и вердикт о составе
  // поставки к ним не относится вовсе.
  const byDirectory = statSync(target).isDirectory();
  let bad = 0;
  let judged = 0;
  for (const file of takeable) {
    const verdict = judge(readFileSync(file));
    if (verdict.state === 'проба-мимо' && byDirectory) {
      info(`пропущен ${basename(file)}: не бинарь продукта (${verdict.why})`);
      continue;
    }
    judged += 1;
    const numbers = `${GATEWAY_MARKS.map((m) => `${m}=${verdict.found[m]}`).join(', ')}, `
      + `«облачного режима нет»=${verdict.noCloud}, ${DIAGNOSTIC_MARK}=${verdict.diagnostic} (диагностика), `
      + `контроль=${verdict.control}`;
    if (verdict.state === 'шлюз-есть') {
      info(`✓ ${file}: шлюз Авроры в поставке — ${numbers}`);
      continue;
    }
    bad += 1;
    console.error(`\n[состав поставки] ОТКАЗ: ${file}`);
    console.error(`[состав поставки] ${verdict.why}`);
    console.error(`[состав поставки] числа: ${numbers}`);
    if (verdict.state === 'шлюза-нет') {
      console.error('[состав поставки] что делать: пересоберите облачной командой продукта — '
        + 'npm run tauri:build:thin. Распоряжение владельца 17.08.2026: программы выпускаются '
        + 'только со шлюзом (CPD-115)');
    }
  }

  if (bad > 0) {
    console.error(`\n[состав поставки] ИТОГ: без шлюза либо неясно — ${bad} из ${judged}`);
    process.exit(1);
  }
  // 🔴 Ноль проверенных — не «сошлось». Каталог мог оказаться чужим, а спутники все до
  // одного пропущены: молчаливый нулевой код здесь означал бы «поставка со шлюзом»,
  // сказанное о поставке, которую никто не смотрел.
  if (judged === 0) {
    console.error(`\n[состав поставки] ОТКАЗ: в ${target} не нашлось ни одного бинаря продукта`);
    console.error('[состав поставки] что делать: «нечего проверять» не значит «проверено». '
      + 'Укажите каталог сборки продукта либо сам распакованный бинарь');
    process.exit(1);
  }
  info(`итог: шлюз на месте во всех проверенных файлах (${judged})`);
}

// Гард запуска: при импорте набором проверок main не выполняется.
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  main();
}
