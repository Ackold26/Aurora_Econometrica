#!/usr/bin/env node
/**
 * Гейт разбора заголовка `Range` в облачной функции доставки `content`.
 *
 * Зачем: через эту функцию файлы кабинетов идут ко ВСЕМ продуктам линейки, а
 * деплой необратим. Ошибка в границах диапазона не падает и не шумит — она
 * молча отдаёт клиенту усечённый файл. Поэтому логика границ проверяется здесь,
 * до выкладки, а не только живым зондом после неё.
 *
 * Проверяется ровно тот текст, что лежит в `index.ts`: функция извлекается из
 * файла, а не переписывается рядом — копия рано или поздно разойдётся с боевой.
 *
 * Запуск: node tools/check_content_range.mjs
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const SOURCE = "supabase/functions/content/index.ts";
const MARK_START = "/** Включительные границы";
const MARK_END = "Deno.serve(";

const src = readFileSync(SOURCE, "utf-8");
const start = src.indexOf(MARK_START);
const end = src.indexOf(MARK_END);
if (start < 0 || end < 0 || end <= start) {
  console.error(
    `ПРОВАЛ: в ${SOURCE} не найден блок разбора диапазонов ` +
      `(искали «${MARK_START}» до «${MARK_END}»). Если функцию переименовали — ` +
      `обновите маркеры, а не удаляйте проверку.`
  );
  process.exit(1);
}

const dir = mkdtempSync(join(tmpdir(), "content-range-"));
const modPath = join(dir, "range.ts");
writeFileSync(modPath, src.slice(start, end) + "\nexport { parseRange };\n", "utf-8");
const { parseRange } = await import(pathToFileURL(modPath).href);

const SIZE = 34165; // размер econometrist.vault — файла, на котором всё вскрылось
let failed = 0;

function check(name, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) {
    failed++;
    console.log(`ПРОВАЛ ${name}: получено ${g}, ожидалось ${w}`);
  }
}

// Обычная работа: докачка кусками идёт вот такими запросами.
check("заголовка нет — файл целиком", parseRange(null, SIZE), null);
check("первый кусок", parseRange("bytes=0-2047", SIZE), { start: 0, end: 2047 });
check("средний кусок", parseRange("bytes=2048-4095", SIZE), { start: 2048, end: 4095 });
check("открытый конец", parseRange("bytes=34000-", SIZE), { start: 34000, end: SIZE - 1 });
check("последний байт", parseRange(`bytes=${SIZE - 1}-`, SIZE), { start: SIZE - 1, end: SIZE - 1 });
check("пробелы по краям", parseRange("  bytes=0-9  ", SIZE), { start: 0, end: 9 });

// Хвост за краем обрезается, а не отвергается — иначе последний кусок файла
// никогда не доедет, ведь его длина обычно меньше запрошенной.
check("хвост за краем обрезан", parseRange("bytes=34000-99999", SIZE), { start: 34000, end: SIZE - 1 });
check("суффикс — последние байты", parseRange("bytes=-100", SIZE), { start: SIZE - 100, end: SIZE - 1 });
check("суффикс больше файла", parseRange("bytes=-99999", SIZE), { start: 0, end: SIZE - 1 });

// Невыполнимый диапазон обязан давать 416: клиент по нему сбрасывает частичный
// файл и качает начисто. Молчаливая отдача не того куска здесь опаснее отказа.
check("начало за концом файла", parseRange(`bytes=${SIZE}-`, SIZE), "invalid");
check("перевёрнутые границы", parseRange("bytes=500-100", SIZE), "invalid");
check("нулевой суффикс", parseRange("bytes=-0", SIZE), "invalid");
check("пустой файл", parseRange("bytes=0-10", 0), "invalid");

// Непонятый заголовок — отдаём файл целиком (так разрешает спецификация).
// Отвечать отказом нельзя: старые сборки клиентов не шлют Range вовсе.
check("единица не байтовая", parseRange("items=0-10", SIZE), null);
check("несколько диапазонов", parseRange("bytes=0-99,200-299", SIZE), null);
check("мусор вместо чисел", parseRange("bytes=abc", SIZE), null);
check("голое bytes=-", parseRange("bytes=-", SIZE), null);

const total = 17;
if (failed > 0) {
  console.error(`\nПроверок: ${total}, провалов: ${failed}`);
  process.exit(1);
}
console.log(`Разбор диапазонов: ${total} проверок пройдено.`);
