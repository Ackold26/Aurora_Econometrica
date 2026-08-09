#!/usr/bin/env node
/**
 * Сторож редакции готового установщика (ADR-049 §2).
 *
 * 🔴 Зачем этот файл — дополняет, а не дублирует, `checkBuildConfigKeepsProductIdentity` из
 * `tools/build-cloud.mjs`. Тот гейт проверяет РЕЦЕПТ сборки: смотрит на аргументы команды
 * `tauri build` и на оверлей `tauri.thin.conf.json` ДО запуска сборщика — и потому бессилен
 * против сборки в обход самого скрипта: ручной вызов `tauri build --config …` никогда не
 * проходит через `build-cloud.mjs`, а значит и через его гейт тоже. Этот сторож проверяет не
 * рецепт, а ГОТОВЫЙ АРТЕФАКТ — установщик или бинарник на диске, — и потому стоит НАД любым
 * способом его получить: штатным скриптом, ручной командой, будущим CI.
 *
 * Живой прогон 09.08.2026 (разбор `Projects/PROGON_PC204_2026-08-08.md`): установщик,
 * собранный на PC204, прошёл бы эту проверку — идентификатор в бинарнике ровно один,
 * `com.aurora.econometrica`, без «.thin». Находка появилась только потому, что кто-то
 * распаковал файл руками; сторож существует, чтобы это не зависело от того, вспомнит ли
 * кто-то сделать так же в следующий раз.
 *
 * ## Как ищем
 *
 * Identifier — строка вида `com.aurora.econometrica[.суффикс]`, зашитая в бинарник
 * сборщиком Tauri (строковые литералы компилятор хранит то как ASCII/UTF-8, то как
 * UTF-16LE — ресурсы PE на Windows традиционно широкие).
 *
 * 🔴 Наивный подсчёт вхождений подстроки ловит настоящую ловушку: `com.aurora.econometrica` —
 * ПРЕФИКС одновременно `com.aurora.econometrica.local` и `com.aurora.econometrica.thin`.
 * Внутри локального установщика байты `com.aurora.econometrica` физически присутствуют — они
 * первая половина `com.aurora.econometrica.local`, — и наивная позитивная проверка
 * «универсальная редакция» прошла бы зелёной на установщике совсем другой редакции.
 *
 * 🔴 Первая версия лечила это общей границей «символ дальше входит в алфавит identifier'а или
 * нет» — и была неверна: `&'static str` в Rust не нуль-терминированы, компилятор пакует
 * соседние строковые константы впритык без разделителя. Живой установщик (PC204, 08.08) несёт
 * ровно это: `com.aurora.econometrica` там стоит без разделителя рядом с НЕСВЯЗАННОЙ строкой
 * `econometrica-sidecar` — а она тоже начинается с буквы. Граница «дальше идёт буква — значит
 * не отдельный identifier» дала бы ложный отказ на настоящем, исправном бинарнике.
 *
 * Лечение — граница не по алфавиту, а по РЕЕСТРУ: совпадение `needle` не засчитывается, только
 * если байты начиная с этой позиции совпадают с каким-то ДРУГИМ, более длинным identifier'ом
 * из известного реестра (`allKnownIdentifiers`) — то есть это на самом деле вхождение ЕГО, а
 * не `needle`. `com.aurora.econometrica`, за которой идёт `.local`, — вхождение
 * `com.aurora.econometrica.local`, не самостоятельного identifier'а. `com.aurora.econometrica`,
 * за которой идёт что угодно ещё (в т.ч. случайная соседняя буква), — самостоятельное
 * вхождение, потому что ни один identifier реестра его дальше не продолжает.
 *
 * Запуск: node tools/check-installer-edition.mjs <путь к .exe> <universal|local>
 * Код возврата: 0 — редакция подтверждена, 1 — несовпадение или ошибка входа.
 */
import { readFileSync, existsSync, realpathSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Известные редакции продукта и их identifier (ADR-049 §2, §7). Единственный источник
 * истины для этого файла — добавить третью редакцию значит дописать одну строку здесь.
 */
export const EDITION_IDENTIFIERS = {
  universal: 'com.aurora.econometrica',
  local: 'com.aurora.econometrica.local',
};

/**
 * Identifier'ы, которых не должно быть НИ В ОДНОЙ поставке (ADR-049 §2: «тонкая» редакция
 * слита с обычной, второго identifier'а для неё больше не существует). Это не список
 * «прочих редакций» — список того, что является ошибкой само по себе, при любом входе.
 */
export const RETIRED_IDENTIFIERS = ['com.aurora.econometrica.thin'];

/** Все identifier'ы, которые этому сторожу известны — разрешённые редакции и отставные разом.
 *  Единый список нужен разбору вложенности в {@link countBoundedOccurrences}. */
function allKnownIdentifiers() {
  return [...Object.values(EDITION_IDENTIFIERS), ...RETIRED_IDENTIFIERS];
}

/**
 * Число ОГРАНИЧЕННЫХ вхождений `needle` в `buffer` при кодировке `encoding` (`'ascii'` —
 * 1 байт/символ, `'utf16le'` — 2 байта/символ). Вхождение НЕ засчитывается, если байты начиная
 * с этой позиции на самом деле образуют другой, более длинный identifier из реестра (разбор
 * ловушки-префикса и почему граница именно такая — в шапке файла).
 *
 * Шаг поиска — `step` (ширина ОДНОГО символа в этой кодировке), а не длина `needle`: иначе при
 * подавленном (вложенном) совпадении следующий поиск мог бы перескочить настоящее
 * самостоятельное вхождение той же строки чуть дальше в буфере.
 */
export function countBoundedOccurrences(buffer, needle, encoding) {
  const step = encoding === 'utf16le' ? 2 : 1;
  const target = Buffer.from(needle, encoding);
  const longerKnown = allKnownIdentifiers()
    .filter((id) => id !== needle && id.startsWith(needle))
    .map((id) => Buffer.from(id, encoding));
  let count = 0;
  let from = 0;
  for (;;) {
    const idx = buffer.indexOf(target, from);
    if (idx === -1) break;
    const isPartOfLonger = longerKnown.some((longTarget) => {
      const end = idx + longTarget.length;
      return end <= buffer.length && buffer.subarray(idx, end).equals(longTarget);
    });
    if (!isPartOfLonger) count += 1;
    from = idx + step;
  }
  return count;
}

/**
 * Общее число ограниченных вхождений `needle` в буфере сразу в обеих кодировках — то, что
 * нужно вызывающему коду: одному и тому же identifier'у всё равно, каким байтовым
 * представлением он зашит в конкретный бинарник.
 */
export function countAcrossEncodings(buffer, needle) {
  return (
    countBoundedOccurrences(buffer, needle, 'ascii')
    + countBoundedOccurrences(buffer, needle, 'utf16le')
  );
}

/**
 * Проверить редакцию готового артефакта. Возвращает `{ ok, message }`, ничего не печатает и
 * не завершает процесс — так тесты получают результат напрямую, не перехватывая вывод.
 */
export function checkInstallerEdition(filePath, expectedEdition) {
  const expected = EDITION_IDENTIFIERS[expectedEdition];
  if (!expected) {
    const known = Object.keys(EDITION_IDENTIFIERS).join(', ');
    return {
      ok: false,
      message: `неизвестная редакция «${expectedEdition}» — ожидается одна из: ${known}`,
    };
  }
  if (!existsSync(filePath)) {
    return { ok: false, message: `файл не найден: ${filePath}` };
  }
  const buffer = readFileSync(filePath);

  const foundExpected = countAcrossEncodings(buffer, expected);
  if (foundExpected < 1) {
    return {
      ok: false,
      message:
        `в артефакте не нашёлся identifier ожидаемой редакции «${expectedEdition}» `
        + `(${expected}) — проверьте, тот ли файл собран и не подменена ли настройка сборки`,
    };
  }

  const forbidden = [
    ...Object.entries(EDITION_IDENTIFIERS)
      .filter(([name]) => name !== expectedEdition)
      .map(([, identifier]) => identifier),
    ...RETIRED_IDENTIFIERS,
  ];
  for (const identifier of forbidden) {
    const found = countAcrossEncodings(buffer, identifier);
    if (found > 0) {
      return {
        ok: false,
        message:
          `в артефакте редакции «${expectedEdition}» найден чужой identifier «${identifier}» `
          + `(${found} вхожд.) — сборка велась в обход штатного скрипта, с наложенной `
          + 'настройкой чужой редакции; клиент получит вторую программу с пустым профилем '
          + 'вместо обновления',
      };
    }
  }

  return {
    ok: true,
    message:
      `редакция «${expectedEdition}» подтверждена: identifier ${expected} на месте `
      + `(${foundExpected} вхожд.), чужих identifier'ов нет`,
  };
}

// ── CLI ──────────────────────────────────────────────────────────────────────

/**
 * Запущен ли файл напрямую, а не импортирован тестами. Сравнение через realpath — рабочие
 * деревья этого продукта часто заведены через `mklink /J` (параллельные линии разработки,
 * см. `CLAUDE.md`), и голое сравнение путей рвётся на junction (тот же приём, что в
 * `build-cloud.mjs::startedDirectly`).
 */
export function startedDirectly(entryPath) {
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

function main() {
  const [, , filePath, expectedEdition] = process.argv;
  if (!filePath || !expectedEdition) {
    console.error(
      '[сторож редакции] использование: node tools/check-installer-edition.mjs '
      + '<путь к .exe> <universal|local>',
    );
    process.exit(1);
    return;
  }
  const { ok, message } = checkInstallerEdition(filePath, expectedEdition);
  if (!ok) {
    console.error(`[сторож редакции] ОТКАЗ: ${message}`);
    process.exit(1);
    return;
  }
  console.log(`[сторож редакции] ${message}`);
}

if (startedDirectly(process.argv[1])) {
  main();
}
