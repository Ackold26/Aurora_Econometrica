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
import {
  existsSync, readFileSync, readdirSync, writeFileSync, copyFileSync, rmSync, mkdtempSync,
  realpathSync,
} from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';

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

/**
 * Что продукт берёт из облачного слоя Core — выводится из его же кода.
 *
 * 🔴 Прежде здесь лежал перечень из трёх имён, выписанный вручную, и искался он
 * подстрокой `fn <имя>` в ОДНОМ файле крейта. Продукт же берёт полтора десятка
 * имён, часть из которых лежит в других файлах: проверка объявляла «контракт на
 * месте» на дереве, которым продукт не собирается, — ровно тот исход, против
 * которого она и написана. Вдобавок совпадение по подстроке зеленело от
 * упоминания имени в комментарии.
 *
 * Теперь перечень не выдуман, а прочитан из `use aurora_gateway::cloud::{…}`
 * самого продукта: добавили имя в коде — проверка подхватила его сама.
 */
export function usedGatewayNames() {
  const names = new Set();
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.name.endsWith('.rs')) {
        const source = readFileSync(full, 'utf8');
        for (const use of source.matchAll(/use\s+aurora_gateway::cloud::\{([^}]*)\}/g)) {
          for (const name of use[1].split(',')) {
            const clean = name.trim().replace(/\s+as\s+\w+$/, '');
            if (clean && /^[A-Za-z_][A-Za-z0-9_]*$/.test(clean)) names.add(clean);
          }
        }
        for (const single of source.matchAll(/use\s+aurora_gateway::cloud::([A-Za-z_][A-Za-z0-9_]*)\s*;/g)) {
          names.add(single[1]);
        }
      }
    }
  };
  walk(join(TAURI_DIR, 'src'));
  return names;
}

/**
 * Методы общего слоя, которые продукт зовёт НЕ через use-импорт, а на уже
 * импортированном значении: `err.is_resend_inputs()`, `state.is_success()`.
 *
 * 🔴 Находка П-5, продолжение (аудит 4): `usedGatewayNames()` видит только
 * `use aurora_gateway::cloud::{…}` — свободные ИМЕНА. Метод — другое дело, и
 * различить «метод Core» от метода `String`/`Vec`/`Option` голым текстом,
 * без разбора типов, НАДЁЖНО нельзя: типы Core в адаптере обычно выводятся
 * компилятором и ни разу не названы буквально (`CloudError`/`JobState` не
 * встречаются в тексте продукта ни разу, хотя их методы зовутся), а голая
 * `\.(\w+)\(` даёт по 40+ разных имён на один файл адаптера — `clone`,
 * `lock`, `unwrap_or_else`, `and_then`, `emit`, `path` и так далее; список
 * исключений для стандартной библиотеки никогда не станет полным и был бы
 * либо дырой (пропущенное новое имя), либо источником ложных находок.
 *
 * Поэтому список — явный и по каждому имени с пояснением, а не молчаливый
 * фильтр: не «всё, что может быть методом Core», а то, что РЕАЛЬНО зовёт хоть
 * один продукт сегодня. Пропуск здесь — не дыра: метод, которого гейт не
 * знает, всё равно поймает настоящий `cargo check`, только медленнее и без
 * этого текста на входе.
 */
export const KNOWN_GATEWAY_METHODS = {
  is_resend_inputs: {
    type: 'CloudError',
    why: 'вложения диалога не найдены на сервере, продукт решает, пересылать ли их заново',
  },
  needs_inputs_resend: {
    type: 'JobState',
    why: 'то же решение со стороны состояния уже принятого задания',
  },
  cancel_unconfirmed: { type: 'JobState', why: 'отмена не подтверждена сервером' },
  is_success: { type: 'JobState', why: 'задание завершилось успешно' },
  failure_text: { type: 'JobState', why: 'текст отказа для человека (и скрытая диагностика узла)' },
  user_text: { type: 'CloudError', why: 'текст для человека, без внутренних подробностей' },
  stray_job: { type: 'CloudError', why: 'номер задания, снятие которого сервер не подтвердил' },
};

/** Методы общего слоя из {@link KNOWN_GATEWAY_METHODS}, реально вызванные в коде продукта. */
export function usedGatewayMethods() {
  const names = new Set();
  const patterns = Object.keys(KNOWN_GATEWAY_METHODS).map(
    (name) => [name, new RegExp(`\\.${name}\\s*\\(`)],
  );
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.name.endsWith('.rs')) {
        const source = readFileSync(full, 'utf8');
        for (const [name, pattern] of patterns) {
          if (pattern.test(source)) names.add(name);
        }
      }
    }
  };
  walk(join(TAURI_DIR, 'src'));
  return names;
}

/**
 * Заменить пробелами всё, что кодом не является: комментарии и литералы.
 *
 * 🔴 Длина текста сохраняется в точности — позиции найденного в очищенном тексте
 * годятся и для исходного. Нужно это ради двух бед сразу: `#[cfg(test)]` внутри
 * строки или комментария не должен гасить живой код, а фигурная скобка в
 * литерале не должна сбивать счёт вложенности при поиске конца блока.
 */
export function blankNonCode(source) {
  const out = source.split('');
  const blank = (from, to) => {
    for (let k = from; k < to && k < out.length; k += 1) {
      if (out[k] !== '\n') out[k] = ' ';
    }
  };
  let i = 0;
  while (i < source.length) {
    const two = source.slice(i, i + 2);
    if (two === '//') {
      let end = source.indexOf('\n', i);
      if (end === -1) end = source.length;
      blank(i, end);
      i = end;
    } else if (two === '/*') {
      // Блочные комментарии в Rust вкладываются друг в друга.
      let depth = 1;
      let k = i + 2;
      while (k < source.length && depth > 0) {
        if (source.slice(k, k + 2) === '/*') { depth += 1; k += 2; } else if (source.slice(k, k + 2) === '*/') { depth -= 1; k += 2; } else k += 1;
      }
      blank(i, k);
      i = k;
    } else if (source[i] === 'r' && /["#]/.test(source[i + 1] || '')) {
      // Сырая строка: r"…" либо r#"…"# с любым числом решёток.
      let k = i + 1;
      let hashes = 0;
      while (source[k] === '#') { hashes += 1; k += 1; }
      if (source[k] !== '"') { i += 1; continue; }
      const closing = `"${'#'.repeat(hashes)}`;
      const end = source.indexOf(closing, k + 1);
      const stop = end === -1 ? source.length : end + closing.length;
      blank(i, stop);
      i = stop;
    } else if (source[i] === '"') {
      let k = i + 1;
      while (k < source.length && source[k] !== '"') k += source[k] === '\\' ? 2 : 1;
      blank(i, k + 1);
      i = k + 1;
    } else if (source[i] === "'") {
      // 🔴 Апостроф в Rust — либо символьный литерал, либо имя времени жизни
      // (`'a`), у которого закрывающей кавычки нет вовсе. Гасить время жизни
      // как строку значило бы съесть весь остаток файла до следующего
      // апострофа — вместе с объявлениями, которые ищем.
      const isChar = source[i + 1] === '\\' || source[i + 2] === "'";
      if (!isChar) { i += 1; continue; }
      let k = i + 1;
      while (k < source.length && source[k] !== "'") k += source[k] === '\\' ? 2 : 1;
      blank(i, k + 1);
      i = k + 1;
    } else i += 1;
  }
  return out.join('');
}

/** Конец блока, начинающегося фигурной скобкой на позиции `open` (текст без литералов). */
function blockEnd(code, open) {
  let depth = 0;
  for (let k = open; k < code.length; k += 1) {
    if (code[k] === '{') depth += 1;
    else if (code[k] === '}') {
      depth -= 1;
      if (depth === 0) return k + 1;
    }
  }
  return code.length;
}

/**
 * Погасить тела `#[cfg(test)]`: набор проверок крейта контрактом не является.
 *
 * 🔴 Находка пятого аудита: без этого одноимённый помощник в тестовом модуле
 * («`fn is_success()` для удобства проверок») зеленил гейт на крейте, где
 * настоящего метода уже нет. Приём взят у `check_ui_seam.py`: атрибут перед
 * формой БЕЗ тела (`mod tests;`) ничего не прячет — различаем по тому, что
 * встретится раньше, `;` или `{`.
 */
export function stripTestModules(code) {
  const attr = /#\[\s*cfg\s*\([^\]]*\btest\b[^\]]*\)\s*\]/g;
  let text = code;
  let from = 0;
  for (;;) {
    attr.lastIndex = from;
    const found = attr.exec(text);
    if (!found) return text;
    const after = found.index + found[0].length;
    const brace = text.indexOf('{', after);
    const semi = text.indexOf(';', after);
    if (brace === -1 || (semi !== -1 && semi < brace)) {
      from = after;
      continue;
    }
    const stop = blockEnd(text, brace);
    const gap = text.slice(found.index, stop).replace(/[^\n]/g, ' ');
    text = text.slice(0, found.index) + gap + text.slice(stop);
    from = stop;
  }
}

/** Имя типа из заголовка impl-блока: `impl<'a> Foo<'a>` → Foo, `impl Trait for X` → X. */
export function implTypeName(header) {
  let text = header;
  const forAt = text.search(/\bfor\b/);
  if (forAt !== -1) text = text.slice(forAt + 3);
  // Дженерики снимаются вместе с вложенными: `Foo<Bar<Baz>>` → `Foo`.
  for (let pass = 0; pass < 4 && /</.test(text); pass += 1) {
    text = text.replace(/<[^<>]*>/g, ' ');
  }
  text = text.split(/\bwhere\b/)[0];
  const parts = text.trim().split(/\s+/).filter(Boolean);
  const last = parts.length > 0 ? parts[parts.length - 1] : '';
  const segments = last.split('::').filter(Boolean);
  const name = segments.length > 0 ? segments[segments.length - 1] : '';
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(name) ? name : '';
}

/**
 * Объявления крейта: и голое имя, и `Тип::имя` для методов в impl-блоках.
 *
 * 🔴 Три находки пятого аудита разом, все класса «зелёное на сломанном контракте»:
 *
 *   1. Метод искался по всему дереву БЕЗ привязки к типу — а `user_text` в Core
 *      определён и у `CloudError`, и у `TicketProblem`. Пропади нужный —
 *      гейт молчал бы, потому что имя в дереве осталось.
 *   2. Тестовые модули считались наравне с рабочим кодом (см. stripTestModules).
 *   3. Форму `pub async fn` / `pub const fn` регулярка не видела вовсе — это
 *      зеркальная беда, ложное КРАСНОЕ на исправном крейте.
 *
 * `pub(crate) fn` намеренно НЕ считается объявлением: снаружи такой метод
 * недоступен, и продукт его позвать не может.
 */
export function definedFunctionNames(crateSrcDir) {
  const names = new Set();
  // 🔴 У `extern` кавычки НЕОБЯЗАТЕЛЬНЫ (находка внешнего аудита): `blankNonCode`
  // гасит строковые литералы вместе с кавычками ещё до этого разбора, поэтому
  // `pub extern "C" fn` приходит сюда как `pub extern     fn`. Требование кавычек
  // означало ложное КРАСНОЕ на исправном крейте — та самая зеркальная беда, ради
  // которой формы объявления и расширяли.
  const declaration = /\bpub\s+(?:const\s+|async\s+|unsafe\s+|extern\s+(?:"[^"]*"\s+)?)*fn\s+([A-Za-z_][A-Za-z0-9_]*)/g;
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.name.endsWith('.rs')) {
        const code = stripTestModules(blankNonCode(readFileSync(full, 'utf8')));
        for (const m of code.matchAll(declaration)) names.add(m[1]);
        const impls = /\bimpl\b/g;
        let found = impls.exec(code);
        while (found) {
          const brace = code.indexOf('{', found.index);
          if (brace === -1) break;
          const type = implTypeName(code.slice(found.index + 4, brace));
          const body = code.slice(brace, blockEnd(code, brace));
          if (type) {
            for (const m of body.matchAll(declaration)) names.add(`${type}::${m[1]}`);
          }
          impls.lastIndex = brace + 1;
          found = impls.exec(code);
        }
      }
    }
  };
  walk(crateSrcDir);
  return names;
}

/**
 * Сверить, что продукт не зовёт метода общего слоя, которого в этой версии
 * крейта нет. Отдельно от {@link assertContractSurface}: имена и методы —
 * разные пространства (свободное имя может быть на месте, а метод на нём —
 * ещё нет), и сверка одного не подменяет сверку другого.
 */
export function assertContractMethods(definedNames, describeSource) {
  const used = usedGatewayMethods();
  // 🔴 Спрашиваем ИМЕННО `Тип::метод`: голое имя в дереве крейта ничего не
  // доказывает — оно может принадлежать другому типу (в Core `user_text` есть
  // и у `CloudError`, и у `TicketProblem`).
  const qualified = (name) => {
    const type = KNOWN_GATEWAY_METHODS[name] && KNOWN_GATEWAY_METHODS[name].type;
    return type ? `${type}::${name}` : name;
  };
  const missing = [...used].map(qualified).filter((name) => !definedNames.has(name));
  if (missing.length > 0) {
    fail(
      `${describeSource} не содержит ${missing.join(', ')}`,
      'метод общего слоя, который продукт зовёт, отсутствует в этой версии крейта — ' +
        'сверьте путь/метку фрагмента и повторите, либо дождитесь новой метки Core',
    );
  }
  return used.size;
}

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
// 🔴 Больше НЕ применяется при сборке (ADR-049 §2, см. пояснение у формирования args).
// Константа оставлена как след: файл оверлея лежит в дереве, и без этой строки следующий,
// кто его найдёт, решит, что забыли подключить.
const CLOUD_CONFIG = 'src-tauri/tauri.thin.conf.json';

function fail(message, hint) {
  console.error(`\n[облачная сборка] ОТКАЗ: ${message}`);
  if (hint) console.error(`[облачная сборка] что делать: ${hint}\n`);
  process.exit(1);
}

function info(message) {
  console.log(`[облачная сборка] ${message}`);
}

/**
 * Наложение настройки сборки, если продукт его когда-либо заводил. У продуктов,
 * получивших облачный режим сразу объединённой поставкой, файла нет вовсе.
 */
const BUILD_CONFIG_OVERLAY = join(TAURI_DIR, 'tauri.thin.conf.json');

/**
 * Настройка сборки не имеет права менять ЛИЦО продукта (ADR-049 §2, CPD-43).
 *
 * 🔴 Зачем гейт (найдено сессией Legal 2026-08-03 — глазами, по имени готового
 * установщика «Aurora AI Legal Center C»). Наложение переопределяло `productName` и
 * `identifier`, и собранная так поставка оказывалась не обновлением, а ВТОРОЙ
 * программой: каталог данных Tauri берётся из идентификатора, поэтому обновившийся
 * клиент получил бы пустой профиль — без лицензии, хранилищ кабинетов, выбранного
 * режима и истории, — а прежняя копия осталась бы рядом. Канал обновлений привязан к
 * тому же идентификатору, то есть выпуск вообще не встал бы обновлением, и человек об
 * этом не узнал бы.
 *
 * Ловится только гейтом: сборка проходит зелёной, оба контура на месте, проверки
 * редакции довольны — подмена видна лишь в имени файла установщика.
 *
 * 🔴 Отличие от исходной версии Legal: там при отсутствии файла функция молча
 * возвращалась. Молчание читается как «проверено и сошлось», хотя проверка не
 * выполнялась вовсе — тот же класс «отсутствие проверяемого = пройдено», что уже
 * ловили в гейтах режима и канала. Здесь область называется вслух.
 */
function checkBuildConfigKeepsProductIdentity(configPath, { applied }) {
  if (!existsSync(configPath)) {
    info(
      `настройка ${configPath} ${applied ? 'накладывается этим прогоном, но файла НЕТ' : 'отсутствует'}`
      + ' — проверять нечего. Это не «чисто»: переименуй файл, и проверка лица продукта'
      + ' выключится молча',
    );
    return;
  }
  let overlay;
  try {
    overlay = JSON.parse(readFileSync(configPath, 'utf8'));
  } catch (e) {
    fail(
      `настройка сборки ${configPath} не разбирается как JSON: ${e.message}`,
      'почините файл — молча пропустить его нельзя, он меняет собираемый продукт',
    );
    return;
  }
  const forbidden = ['productName', 'identifier'].filter((k) => overlay[k] !== undefined);
  if (!forbidden.length) {
    info(`настройка сборки лицо продукта не меняет (${configPath})`);
    return;
  }
  // 🔴 Наличие полей само по себе НЕ дефект — дефектом их делает ПРИМЕНЕНИЕ. У продуктов,
  // переведённых на ADR-049 раньше, файл оставлен в дереве намеренно (он заведён владельцем),
  // но сборка его больше не накладывает. Первая версия этой проверки судила по файлу и
  // покрасила два исправных продукта — поймано прогоном на них, а не рассуждением. А ложный
  // красный кончается тем, что проверку снимают вместе с защитой.
  const fields = forbidden.map((k) => `${k}=${JSON.stringify(overlay[k])}`).join(', ');
  if (applied) {
    fail(
      `настройка сборки ${configPath} переопределяет ${forbidden.join(' и ')} (${fields}) `
        + 'И накладывается сборкой — это отдельный продукт, а не объединённая поставка',
      'ADR-049 §2: объединённая поставка идёт под идентификатором обычной редакции и в её '
        + 'канал обновлений. Уберите эти поля из настройки либо перестаньте её накладывать; '
        + 'иначе у клиента будет вторая программа с пустым профилем — без лицензии, '
        + 'хранилищ кабинетов и истории',
    );
    return;
  }
  // Отказа нет, но и молчать нельзя: вернуть наложение — одна строка, а последствие у
  // клиента необратимо. Пусть тот, кто её вернёт, увидит предупреждение уже сейчас.
  info(
    `⚠ настройка сборки ${configPath} переопределяет ${forbidden.join(' и ')} (${fields}), `
    + 'но сборкой НЕ накладывается (ADR-049 §2) — дефекта нет. Вернёте наложение — '
    + 'получите второй продукт у клиента, проверка станет отказом',
  );
}

/** Тот же приём, что в гейтах на Python: комментарии гасятся, чтобы упоминание в
 *  пояснении не считалось применением. */
function without_js_comments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (m) => ' '.repeat(m.length))
    .replace(/(^|[^:])\/\/[^\n]*/g, (m, p1) => p1 + ' '.repeat(m.length - p1.length));
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
  // 🔴 Гасить надо ДЕРЕВО, а не одного ребёнка. На Windows `child.kill()` снимает
  // оболочку (npm/npx), но НЕ внуков: живой `cargo`/`rustc` продолжает работу и
  // дописывает `Cargo.lock` уже ПОСЛЕ того, как манифест восстановлен. След
  // облачной сборки остаётся в замке зависимостей, а восстановление рапортует
  // об успехе. Сторож теперь такой замок ловит, но правильнее не создавать его
  // вовсе.
  if (process.platform === 'win32' && child.pid) {
    try {
      spawnSync('taskkill', ['/F', '/T', '/PID', String(child.pid)], { stdio: 'ignore' });
    } catch {
      /* инструмента нет — пробуем обычным способом ниже */
    }
  }
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
      // 🔴 Спасаем ОБА файла, а не один. Названная выше причина пропажи резерва
      // (`git clean -fdX`) уносит и резерв замка зависимостей, и тогда `Cargo.lock`
      // остаётся с крейтом шлюза: сторож краснеет, а сообщение сборки указывает
      // не на тот файл. Замок в системе контроля версий не у всех продуктов —
      // его неудача не считается провалом спасения.
      const rescue = spawnSync('git', ['checkout', '--', 'src-tauri/Cargo.toml'],
        { cwd: ROOT, stdio: 'inherit' });
      const rescueLock = spawnSync('git', ['checkout', '--', 'Cargo.lock'],
        { cwd: ROOT, stdio: 'inherit' });
      if (rescueLock.status === 0) {
        console.error('[облачная сборка] замок зависимостей возвращён из системы контроля версий');
      }
      if (rescue.status === 0) {
        console.error('[облачная сборка] манифест возвращён из системы контроля версий');
        restoredManifest = true;
        // 🔴 Отметку аварии снимаем: она выставлена ДО спасения, и, оставшись
        // висеть, заставляла итоговое сообщение говорить «восстановить манифест
        // не удалось» ровно там, где он восстановлен.
        restoreFailed = false;
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
/**
 * Откуда фрагмент велит брать крейт шлюза: из дерева на диске или по метке.
 *
 * 🔴 Развязка по метке — правильная: путь в дерево берёт то, что лежит на диске
 * ПРЯМО СЕЙЧАС, и продукт может собраться с чужой версией крейта, ничего об этом
 * не сказав. Ровно так и вышло: путь вёл в дерево основной линии, правки жили в
 * ветке облака, и сотни зелёных проверок собирались с прежним крейтом.
 */
export function gatewaySourceFromFragment(fragment) {
  const declaration = fragment.match(/^\s*aurora_gateway\s*=\s*\{([^}]*)\}/m);
  if (!declaration) {
    fail(
      'во фрагменте не нашлось объявление зависимости крейта шлюза',
      `проверьте ${FRAGMENT} — ожидается aurora_gateway = { path = "…" } ` +
        'либо aurora_gateway = { git = "…", tag = "…" }',
    );
  }
  const body = declaration[1];
  const path = body.match(/\bpath\s*=\s*"([^"]+)"/);
  const git = body.match(/\bgit\s*=\s*"([^"]+)"/);
  const tag = body.match(/\btag\s*=\s*"([^"]+)"/);
  if (path) return { kind: 'path', dir: resolve(TAURI_DIR, path[1]) };
  if (git && tag) return { kind: 'tag', url: git[1], tag: tag[1] };
  if (git) {
    fail(
      'зависимость шлюза объявлена по репозиторию, но без метки',
      'ветка вместо метки означает «собралось то, что там сегодня» — ' +
        `допишите tag = "aurora_gateway-vX.Y.Z" в ${FRAGMENT}`,
    );
  }
  fail(
    'во фрагменте не понято, откуда брать крейт шлюза',
    `ожидается либо path = "…", либо git = "…" вместе с tag = "…" (${FRAGMENT})`,
  );
}

/**
 * Публичная поверхность облачного слоя: что объявлено наружу в mod.rs, тем
 * продукт и может пользоваться.
 */
export function gatewaySurface(modSource) {
  const surface = new Set();
  for (const reexport of modSource.matchAll(/pub use [^;]+;/g)) {
    for (const word of reexport[0].matchAll(/[A-Za-z_][A-Za-z0-9_]*/g)) surface.add(word[0]);
  }
  for (const module of modSource.matchAll(/pub mod\s+([a-z_][a-z0-9_]*)/g)) surface.add(module[1]);
  return surface;
}

/**
 * Сверить, что продукт не зовёт того, чего в поверхности крейта нет. Общая для
 * ветки пути и ветки метки — состав контракта, а не способ достать исходники,
 * решает, пройдёт ли сборка.
 */
export function assertContractSurface(surface, describeSource) {
  const used = usedGatewayNames();
  const missing = [...used].filter((name) => !surface.has(name));
  if (missing.length > 0) {
    fail(
      `${describeSource} не отдаёт того, чем пользуется продукт: нет ${missing.join(', ')}`,
      'источник крейта устарел либо указывает не туда; сверьте путь/метку фрагмента ' +
        'и повторите — если правки только что уехали в Core, дождитесь новой метки',
    );
  }
  return used.size;
}

/**
 * Достать исходники крейта шлюза на КОНКРЕТНОЙ метке во временный каталог.
 *
 * 🔴 Находка П-5 аудита 4. Прежде ветка метки состав контракта не сверяла вовсе:
 * метка существует — не значит, что нужное имя внутри есть, и отказ приходил из
 * глубины cargo, спустя минуты компиляции, без внятной причины. Сверить состав
 * без исходников нечем, а достать их можно: `git archive --remote` не годится
 * (GitHub отключил git-upload-archive по протоколу для смарт-HTTP), поэтому
 * берём мелкий (`--depth 1`) клон РОВНО по метке — тот же приём годится для
 * любого хоста. Каталог одноразовый, лежит в системном temp (не в дереве
 * продукта) и это НЕ тот резерв, что бережёт `backupPristineWorkspace`.
 */
export function fetchGatewaySourceAtTag(url, tag) {
  const dir = mkdtempSync(join(tmpdir(), 'aurora-gateway-tag-'));
  const clone = spawnSync(
    'git',
    ['clone', '--quiet', '--depth', '1', '--branch', tag, url, dir],
    { encoding: 'utf8' },
  );
  if (clone.status !== 0) {
    rmSync(dir, { recursive: true, force: true });
    fail(
      `не удалось скачать исходники крейта по метке ${tag}`,
      `git clone вернул отказ: ${(clone.stderr || '').trim() || 'неизвестная причина'}`,
    );
  }
  return dir;
}

/**
 * Запись, на которую метка указывает СЕЙЧАС, из вывода `git ls-remote --tags`.
 *
 * У аннотированной метки строк две: сам объект метки и разыменованная запись
 * (`^{}`) — брать надо вторую, потому что именно её пишет в замок зависимостей
 * cargo. У лёгкой метки строка одна и она же и есть запись.
 */
export function tagCommitFromLsRemote(stdout, tag) {
  let plain = null;
  for (const line of String(stdout || '').split('\n')) {
    const m = line.match(/^([0-9a-f]{40})\s+refs\/tags\/(.+?)(\^\{\})?\s*$/);
    if (!m || m[2] !== tag) continue;
    if (m[3]) return m[1];
    plain = m[1];
  }
  return plain;
}

/**
 * Крейт шлюза в замке зависимостей: по какой метке и на какой записи он взят.
 *
 * Возвращает `null`, если крейта в замке нет вовсе, и `{ tag, sha }` — если есть
 * (любое из полей может быть `null`, когда строку источника разобрать не вышло:
 * гейт обязан такое НАЗЫВАТЬ, а не пропускать).
 */
export function lockedGatewayCommit(lockText) {
  for (const block of String(lockText || '').split('[[package]]')) {
    if (!/^\s*name\s*=\s*"aurora_gateway"\s*$/m.test(block)) continue;
    const source = block.match(/^\s*source\s*=\s*"([^"]+)"\s*$/m);
    if (!source) return { tag: null, sha: null, source: null };
    const parsed = source[1].match(/[?&]tag=([^#&]+)[^#]*#([0-9a-f]{40})/);
    if (!parsed) return { tag: null, sha: null, source: source[1] };
    return { tag: decodeURIComponent(parsed[1]), sha: parsed[2] };
  }
  return null;
}

/**
 * Сверить, что сборка взяла крейт с той самой записи, на которую метка указывает
 * сейчас.
 *
 * 🔴 Находка пятого аудита. Состав контракта гейт сверял по СВЕЖЕМУ клону метки,
 * а cargo собирает по записи из `Cargo.lock`: пока строка источника в замке
 * отвечает требованию манифеста, cargo к удалённому репозиторию не ходит вовсе.
 * Переставленная метка (или зафиксированная прежде запись) давала зелёный гейт на
 * составе, которого в сборке нет, — ровно тот класс «сотни зелёных проверок при
 * прежнем крейте», ради которого сверку и заводили.
 *
 * Зовётся ПОСЛЕ прогона cargo и ДО восстановления дерева: замок вернётся из
 * резерва, и доказывать будет нечем.
 */
export function assertBuiltFromTag(expected, lockText) {
  const locked = lockedGatewayCommit(lockText);
  if (!locked) {
    fail(
      `сборка прошла, но в замке зависимостей нет крейта шлюза — по какой записи собрано, доказать нечем (метка ${expected.tag})`,
      'проверьте, что признак облачной поставки действительно включён и Cargo.lock пишется в корень продукта',
    );
  }
  if (!locked.sha) {
    fail(
      `строку источника крейта в замке зависимостей разобрать не вышло: ${locked.source || '(источника нет вовсе)'}`,
      'ожидалась зависимость по метке вида git+…?tag=<метка>#<запись> — ' +
        'если форма записи cargo изменилась, научите этот гейт её читать, а не обходите его',
    );
  }
  if (locked.tag !== expected.tag || locked.sha !== expected.sha) {
    fail(
      `сборка взяла крейт по метке ${locked.tag} на записи ${locked.sha.slice(0, 12)}, `
        + `а метка ${expected.tag} указывает сейчас на ${expected.sha.slice(0, 12)}`,
      'состав контракта сверен по свежему клону метки, а собрано по другой записи: '
        + 'метку переставили либо замок зависимостей держит прежнюю. '
        + 'Снимите след облачной сборки (git checkout -- Cargo.lock) и повторите',
    );
  }
  info(`сборка взяла крейт по метке ${expected.tag} на записи ${expected.sha.slice(0, 12)} — совпало с меткой в репозитории`);
}

/** Источник крейта пригоден: дерево на месте с нужным составом либо метка существует
 *  и на ней тот же состав, каким пользуется продукт.
 *  Возвращает `{ tag, sha }` для ветки метки (для сверки после сборки) либо `null`. */
export function verifyGatewaySource(source) {
  if (source.kind === 'tag') {
    // Живость метки — быстрый признак, проверяем его первым: нет доступа к
    // репозиторию или метки не существует — отказ приходит немедленно, без
    // траты времени на клон.
    // 🔴 Образца ДВА, и второй обязателен. `ls-remote` отбирает строки по имени
    // ссылки, а разыменованная запись аннотированной метки называется
    // `refs/tags/<метка>^{}` — под образец `<метка>` она не подходит и в ответ не
    // попадает вовсе. Метки Core аннотированные, поэтому с одним образцом сюда
    // приходил объект МЕТКИ, а cargo пишет в замок зависимостей КОММИТ: сверка
    // краснела на исправной сборке. Поймано боевым прогоном на Oracle.
    const found = spawnSync(
      'git',
      ['ls-remote', '--tags', source.url, source.tag, `${source.tag}^{}`],
      { cwd: ROOT, encoding: 'utf8' },
    );
    if (found.status !== 0) {
      fail(
        `метку ${source.tag} не удалось проверить в ${source.url}`,
        'нет доступа к удалённому репозиторию: поднимите ключ и повторите — ' +
          `${(found.stderr || '').trim() || 'git ls-remote вернул отказ'}`,
      );
    }
    if (!found.stdout.includes(`refs/tags/${source.tag}`)) {
      fail(
        `в удалённом репозитории нет метки ${source.tag}`,
        'метка не отправлена: git push origin ' + source.tag + ' — либо поправьте её имя во фрагменте',
      );
    }
    // Запись метки снимается ЗДЕСЬ: после сборки метку могли бы уже переставить,
    // а сверять надо ровно с тем состоянием, по которому проверен состав.
    const tagSha = tagCommitFromLsRemote(found.stdout, source.tag);
    if (!tagSha) {
      fail(
        `в ответе о метке ${source.tag} не нашлось записи, на которую она указывает`,
        'ожидалась строка вида "<40 знаков> refs/tags/<метка>" — '
          + `git ls-remote ответил: ${(found.stdout || '').trim() || '(пусто)'}`,
      );
    }
    info(`крейт шлюза берётся по метке ${source.tag} (метка на месте, запись ${tagSha.slice(0, 12)})`);

    // 🔴 Метка существует — не значит, что состав контракта на месте: сверяем
    // тем же способом, что и ветка пути, а не просто фактом существования метки.
    //
    // 🔴 Очистка временного каталога сделана ЯВНО перед каждым `fail()`, а не
    // через `try/finally`: `fail()` зовёт `process.exit()` синхронно, а он
    // обрывает исполнение ДО того, как обвязывающий `finally` успеет
    // сработать (проверено зондом) — каталог остался бы висеть в temp ровно
    // на том пути, где сверка и находит нарушение.
    const tmpDir = fetchGatewaySourceAtTag(source.url, source.tag);
    const modRs = join(tmpDir, 'aurora_gateway', 'src', 'cloud', 'mod.rs');
    if (!existsSync(modRs)) {
      rmSync(tmpDir, { recursive: true, force: true });
      fail(
        `метка ${source.tag} не содержит облачного слоя (${modRs})`,
        'сверьте, что метка действительно облачная и расположение крейта ' +
          'внутри репозитория Core не менялось',
      );
    }
    const modSource = readFileSync(modRs, 'utf8');
    // Имена и методы читаются, ПОКА клон ещё жив: методы разбросаны по
    // impl-блокам client.rs/protocol.rs, а не только в mod.rs.
    const surface = gatewaySurface(modSource);
    const definedMethods = definedFunctionNames(join(tmpDir, 'aurora_gateway', 'src'));
    rmSync(tmpDir, { recursive: true, force: true });
    const size = assertContractSurface(surface, `крейт по метке ${source.tag}`);
    assertContractMethods(definedMethods, `метка ${source.tag}`);
    info(`контракт по метке ${source.tag} проверен (продукт берёт ${size} имён, все на месте)`);
    return { tag: source.tag, sha: tagSha };
  }

  const crateDir = source.dir;
  const modRs = join(crateDir, 'src', 'cloud', 'mod.rs');
  if (!existsSync(modRs)) {
    fail(
      `крейт шлюза не найден: ${crateDir}`,
      'создайте рабочее дерево Core на нужной ветке — ' +
        'git -C <путь к aurora-platform-core> worktree add <куда> <ветка> — ' +
        'либо переведите фрагмент на зависимость по метке',
    );
  }
  const surface = gatewaySurface(readFileSync(modRs, 'utf8'));
  const size = assertContractSurface(surface, `крейт по пути ${crateDir}`);
  assertContractMethods(definedFunctionNames(join(crateDir, 'src')), `крейт по пути ${crateDir}`);
  info(`крейт шлюза проверен: ${crateDir} (продукт берёт ${size} имён, все на месте)`);
  // Ветка пути: сверять после сборки нечего — крейт берётся с диска, и запись в
  // замке зависимостей у него местная.
  return null;
}

/**
 * Проверка типов фронта. 🔴 Отдельным шагом гейта, потому что её отсутствие уже
 * стоило дефекта: событие расхождения версий методики показывалось видом
 * «предупреждение», которого не существовало ни в типах, ни в стилях, — оба
 * продукта уехали с ошибкой проверки типов, а облачный гейт остался зелёным,
 * поскольку смотрел только на Rust. Порог — ошибки: предупреждений в дереве
 * сотни, и краснеть на них значило бы приучить обходить гейт.
 *
 * 🔴 Находка П-4 аудита 4: прежде звалась только в `--test`. Настоящий выпуск
 * идёт БЕЗ `--test` — значит и без этой проверки, и ошибка типов фронта уезжала
 * в сборку ровно так же, как уехал вид уведомления, ради которого проверку и
 * заводили. Зовётся теперь при любом запуске: сборке, `--check` и `--test`.
 */
export function checkFrontendTypes() {
  info('проверяю типы фронта (svelte-check)');
  const res = spawnSync('npx', ['svelte-check', '--threshold', 'error', '--output', 'human'], {
    cwd: ROOT,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  });
  const out = `${res.stdout || ''}${res.stderr || ''}`;
  const found = out.match(/found (\d+) errors?/);
  if (res.status !== 0 || (found && Number(found[1]) > 0)) {
    console.error(out.split(String.fromCharCode(10)).slice(-25).join(String.fromCharCode(10)));
    fail(
      'проверка типов фронта нашла ошибки',
      'почините их и повторите — облачный путь трогает слушатели событий, а они живут во фронте',
    );
  }
  info('типы фронта в порядке');
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
  // 🔴 Проверка лица продукта стоит ВПЛОТНУЮ к запуску, а не выше по потоку. Первая
  // версия звала её сразу после сборки `args` — и мутация показала дыру: строку
  // `args = [...args, '--config', …]` можно дописать НИЖЕ вызова, и проверка её уже не
  // увидит. Здесь args финальные по построению: следующий шаг — spawn.
  checkBuildConfigKeepsProductIdentity(BUILD_CONFIG_OVERLAY, {
    applied: args.some((a) => String(a).includes(basename(BUILD_CONFIG_OVERLAY))),
  });
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

  const expectedTag = verifyGatewaySource(gatewaySourceFromFragment(fragment));

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
    // 🔴 Оверлей CLOUD_CONFIG БОЛЬШЕ НЕ ПРИМЕНЯЕТСЯ (ADR-049 §2). Он подменял имя
    // продукта и идентификатор, то есть делал из тонкой поставки ОТДЕЛЬНОЕ приложение
    // операционной системы: свой каталог данных, своя запись в реестре, свой канал
    // обновлений. После слияния редакций поставка одна, режим выбирается во время
    // работы — второй идентификатор развёл бы одного клиента на две установки, между
    // которыми не переезжают ни лицензия, ни проекты. Оверлей ЛОКАЛЬНОЙ редакции
    // (`tauri.local.conf.json`) при этом остаётся: она не сливается (§7).
    // Сам файл оверлея оставлен в дереве нетронутым — решение о его судьбе за владельцем.
    args = [
      'tauri',
      'build',
      ...passThrough,
      '--',
      '--features',
      CLOUD_FEATURE,
    ];
  }

  // П-4 (аудит 4): гоняется при КАЖДОМ запуске — сборке, --check и --test, —
  // а не только в --test, иначе выпуск собирается без неё же самой проверки.
  checkFrontendTypes();
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
  // 🔴 Сверка ДО восстановления: `restoreWorkspace` вернёт замок зависимостей из
  // резерва, и следа того, по какой записи собрано, не останется вовсе.
  if (code === 0 && expectedTag) {
    assertBuiltFromTag(expectedTag, existsSync(LOCKFILE) ? readFileSync(LOCKFILE, 'utf8') : '');
  }
  restoreWorkspace('сборка закончена');
  if (code !== 0) fail(`сборка завершилась с кодом ${code}`);
  if (restoreFailed) {
    fail('сборка прошла, но дерево осталось изменённым — восстановить манифест не удалось',
      'проверьте src-tauri/Cargo.toml: он не должен упоминать крейт шлюза. '
        + 'Вернуть можно командой git checkout -- src-tauri/Cargo.toml');
  }
  info('готово');
}

/**
 * Запущен ли файл напрямую (а не импортирован набором проверок).
 *
 * 🔴 Находка пятого аудита: сравнение «в лоб» ломается на junction и символической
 * ссылке. `fileURLToPath(import.meta.url)` Node отдаёт уже разыменованным, а
 * `resolve(process.argv[1])` — как написано в командной строке; из каталога,
 * заведённого через `mklink /J` (обычная практика для параллельных рабочих
 * деревьев), пути не совпадают, и скрипт молча выходит кодом ноль: сборки нет,
 * установщик прежний, а вызывающая сторона считает сборку успешной.
 */
export function startedDirectly(entryPath) {
  if (!entryPath) return false;
  const self = fileURLToPath(import.meta.url);
  const entry = resolve(entryPath);
  if (self === entry) return true;
  try {
    return realpathSync(self) === realpathSync(entry);
  } catch {
    // Файла по одному из путей нет — значит это не наш запуск.
    return false;
  }
}

// Гард запуска: при импорте (тесты) main НЕ выполняется.
if (startedDirectly(process.argv[1])) {
  main();
}
