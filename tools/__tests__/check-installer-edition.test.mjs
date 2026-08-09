// Проверки сторожа редакции готового установщика (tools/check-installer-edition.mjs).
//
// Настоящий инсталлятор в тестах не нужен — нужны байты в тех же кодировках, что реально
// несёт бинарник Tauri (ASCII/UTF-8 и UTF-16LE), собранные во временные файлы. Главный
// предмет проверки — ловушка префикса (`com.aurora.econometrica` есть внутри
// `com.aurora.econometrica.local` как байтовая последовательность) и то, что граница по
// РЕЕСТРУ известных identifier'ов не ломается на реальной форме бинарника: соседние строковые
// константы Rust не разделены нуль-байтом (см. разбор в шапке проверяемого файла).
import {
  describe, it, expect, afterEach,
} from 'vitest';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  EDITION_IDENTIFIERS,
  RETIRED_IDENTIFIERS,
  countBoundedOccurrences,
  countAcrossEncodings,
  checkInstallerEdition,
} from '../check-installer-edition.mjs';

const UNIVERSAL = EDITION_IDENTIFIERS.universal; // com.aurora.econometrica
const LOCAL = EDITION_IDENTIFIERS.local; // com.aurora.econometrica.local
const THIN = RETIRED_IDENTIFIERS[0]; // com.aurora.econometrica.thin

function ascii(s) {
  return Buffer.from(s, 'ascii');
}
function utf16(s) {
  return Buffer.from(s, 'utf16le');
}
/** Нуль-байт — реалистичный разделитель между строковыми константами в rodata бинарника. */
const NUL = Buffer.from([0]);

const tempDirs = [];
/** Записать буфер во временный файл и вернуть путь — как проверялся бы реальный инсталлятор. */
function tempInstaller(buffer) {
  const dir = mkdtempSync(join(tmpdir(), 'installer-guard-'));
  tempDirs.push(dir);
  const path = join(dir, 'fake-setup.exe');
  writeFileSync(path, buffer);
  return path;
}

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop(), { recursive: true, force: true });
  }
});

describe('countBoundedOccurrences — ловушка префикса', () => {
  it('короткий identifier НЕ засчитывается, если он на деле начало длинного', () => {
    // Буфер несёт РОВНО .local — как в настоящем бинарнике: короткая форма присутствует
    // физически (она первая половина длинной), но как отдельной сущности её тут нет.
    const buffer = Buffer.concat([NUL, ascii(LOCAL), NUL]);
    expect(countBoundedOccurrences(buffer, UNIVERSAL, 'ascii')).toBe(0);
    expect(countBoundedOccurrences(buffer, LOCAL, 'ascii')).toBe(1);
  });

  it('та же ловушка для отставного .thin', () => {
    const buffer = Buffer.concat([NUL, ascii(THIN), NUL]);
    expect(countBoundedOccurrences(buffer, UNIVERSAL, 'ascii')).toBe(0);
    expect(countBoundedOccurrences(buffer, THIN, 'ascii')).toBe(1);
  });

  it('живая форма бинарника: identifier без разделителя рядом с ЧУЖОЙ строкой на букву — считается', () => {
    // Ровно то, что нашлось в установщике PC204 09.08: com.aurora.econometrica впритык, без
    // нуль-байта, к несвязанной строке econometrica-sidecar. Граница по алфавиту символов тут
    // дала бы ложный отказ — граница по реестру идентификаторов не должна.
    const buffer = Buffer.concat([NUL, ascii(`${UNIVERSAL}econometrica-sidecar`), NUL]);
    expect(countBoundedOccurrences(buffer, UNIVERSAL, 'ascii')).toBe(1);
  });

  it('самостоятельный короткий identifier засчитывается, когда за ним нет продолжения из реестра', () => {
    const buffer = Buffer.concat([NUL, ascii(UNIVERSAL), NUL]);
    expect(countBoundedOccurrences(buffer, UNIVERSAL, 'ascii')).toBe(1);
  });
});

describe('checkInstallerEdition', () => {
  it('ожидаемая редакция найдена → успех', () => {
    const path = tempInstaller(Buffer.concat([NUL, ascii(UNIVERSAL), NUL]));
    const { ok, message } = checkInstallerEdition(path, 'universal');
    expect(ok).toBe(true);
    expect(message).toContain(UNIVERSAL);
  });

  it('чужая редакция найдена → провал', () => {
    // Ожидаем universal, но в артефакте вдобавок сидит отставной .thin — ровно тот сценарий,
    // который случился бы при ручной сборке с --config tauri.thin.conf.json в обход скрипта.
    const path = tempInstaller(Buffer.concat([NUL, ascii(UNIVERSAL), NUL, ascii(THIN), NUL]));
    const { ok, message } = checkInstallerEdition(path, 'universal');
    expect(ok).toBe(false);
    expect(message).toContain(THIN);
  });

  it('ожидаемая редакция отсутствует → провал', () => {
    const path = tempInstaller(Buffer.concat([NUL, ascii('ничего похожего тут нет'), NUL]));
    const { ok, message } = checkInstallerEdition(path, 'universal');
    expect(ok).toBe(false);
    expect(message).toContain('не нашёлся');
  });

  it('префиксный случай: локальный установщик, проверенный КАК универсальный, → провал', () => {
    // В буфере физически есть байты UNIVERSAL (первая половина LOCAL), но самостоятельного
    // вхождения короткого identifier'а тут нет — только внутри более длинного .local.
    const path = tempInstaller(Buffer.concat([NUL, ascii(LOCAL), NUL]));
    const { ok, message } = checkInstallerEdition(path, 'universal');
    expect(ok).toBe(false);
    expect(message).toContain('не нашёлся');
  });

  it('тот же установщик, проверенный как локальный, → успех (несмотря на общий префикс)', () => {
    const path = tempInstaller(Buffer.concat([NUL, ascii(LOCAL), NUL]));
    const { ok, message } = checkInstallerEdition(path, 'local');
    expect(ok).toBe(true);
    expect(message).toContain(LOCAL);
  });

  it('UTF-16LE находится наравне с UTF-8', () => {
    const path = tempInstaller(Buffer.concat([NUL, NUL, utf16(UNIVERSAL), NUL, NUL]));
    const { ok, message } = checkInstallerEdition(path, 'universal');
    expect(ok).toBe(true);
    expect(message).toContain('1 вхожд');
  });

  it('неизвестная редакция на входе → провал с понятным сообщением', () => {
    const path = tempInstaller(Buffer.concat([NUL, ascii(UNIVERSAL), NUL]));
    const { ok, message } = checkInstallerEdition(path, 'thin');
    expect(ok).toBe(false);
    expect(message).toContain('неизвестная редакция');
  });

  it('файл не найден → провал, не исключение', () => {
    const { ok, message } = checkInstallerEdition(
      join(tmpdir(), 'installer-guard-нет-такого-файла.exe'),
      'universal',
    );
    expect(ok).toBe(false);
    expect(message).toContain('не найден');
  });
});

describe('countAcrossEncodings', () => {
  it('суммирует вхождения из ОБЕИХ кодировок сразу', () => {
    const buffer = Buffer.concat([NUL, ascii(UNIVERSAL), NUL, NUL, utf16(UNIVERSAL), NUL, NUL]);
    expect(countAcrossEncodings(buffer, UNIVERSAL)).toBe(2);
  });
});
