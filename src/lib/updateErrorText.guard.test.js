// @ts-nocheck — node-side тест (fs/path/process): svelte-check checkJs не имеет
// @types/node в scope, логика проверяется через vitest, не через типы.
/**
 * 🔴 Сторож стыка «что знает Rust → что читает человек» в блокирующем окне обновления.
 *
 * Зачем отдельный сторож (внешний аудит s43, находка H-1). Текст отказа выбирался
 * ТОЛЬКО по коду, а один код в `updater.rs` покрывает 4–8 разных причин. Часть причин
 * там описана собственным русским текстом «что случилось + что делать», написанным
 * именно для этого окна, — и он молча выбрасывался. Самый дорогой случай: клиент
 * отказал в правах администратора, Rust говорит «подтвердите запрос прав», а человек
 * читает про нехватку места на диске и антивирус и ходит по кругу. Окно блокирует
 * работу, выхода, кроме «Повторить», нет.
 *
 * Обычный тест на функцию этого не ловит: он проверяет разбор придуманной строки, а
 * ломается СТЫК — конкретная ветка Rust перестаёт доезжать до экрана. Поэтому сторож
 * читает `updater.rs` и `lib.rs` с диска, собирает ВСЕ ветки, помеченные как
 * клиентский текст, и требует, чтобы каждая доехала до экрана дословно. Добавили
 * новую помеченную ветку — она проверяется сама, без правки сторожа.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import {
  describeUpdateError,
  USER_TEXT_MARK,
  UPDATE_ERROR_TEXTS,
  UPDATE_ERROR_FALLBACK,
} from './updateErrorText.js';

const RUST_UPDATER = path.join(process.cwd(), 'src-tauri/src/commands/updater.rs');
const RUST_LIB = path.join(process.cwd(), 'src-tauri/src/lib.rs');

/**
 * Боевая часть файла: тесты Rust отрезаны, их строки — не клиентский текст.
 * Переводы строк приводим к `\n`: файлы в дереве лежат с CRLF, и разбор по
 * границам вида `\n}` иначе молча захватывал бы весь остаток файла.
 */
function productionSource(path) {
  return readFileSync(path, 'utf8').replace(/\r\n/g, '\n').split('#[cfg(test)]')[0];
}

/**
 * Собрать вызовы `имя(...)` со строковыми литералами внутри.
 * Разбор идёт со счётчиком скобок и учётом строк — регулярка тут врёт на
 * `&format!("…{}…", x)` и на `if … { "A" } else { "B" }`.
 *
 * @param {string} source
 * @param {string} name
 * @returns {{ code: string, text: string }[]}
 */
function collectCalls(source, name) {
  const found = [];
  const head = new RegExp(`\\b${name}\\s*\\(`, 'g');
  let m;
  while ((m = head.exec(source)) !== null) {
    let i = head.lastIndex;
    let depth = 1;
    let inString = false;
    let escaped = false;
    let current = '';
    const texts = [];
    while (i < source.length && depth > 0) {
      const ch = source[i];
      if (inString) {
        if (escaped) { escaped = false; current += ch; }
        else if (ch === '\\') { escaped = true; current += ch; }
        else if (ch === '"') { inString = false; texts.push(current); current = ''; }
        else current += ch;
      } else if (ch === '"') { inString = true; current = ''; }
      else if (ch === '(') depth += 1;
      else if (ch === ')') depth -= 1;
      i += 1;
    }
    const body = source.slice(head.lastIndex, i - 1);
    const code = (body.match(/ErrorCode::UP(\d{3})/) || [])[1];
    for (const text of texts) found.push({ code: code ? `UP-${code}` : '', text });
  }
  return found;
}

/** Строка отказа в том виде, в каком её собирает `coded()` в `aurora_core`. */
function wireFormat({ code, text }) {
  return code ? `[${code}] ${USER_TEXT_MARK} ${text}` : `${USER_TEXT_MARK} ${text}`;
}

const МЕТКИ = [
  ...collectCalls(productionSource(RUST_UPDATER), 'user_err'),
  ...collectCalls(productionSource(RUST_UPDATER), 'user_text'),
  ...collectCalls(productionSource(RUST_LIB), 'updater::user_text'),
];

/**
 * Русские детали, которые НАМЕРЕННО остаются служебными: на экран им нельзя, там
 * лучше общий текст по коду. Ключ — узнаваемый кусок, значение — причина.
 * Список закрытый: новая русская деталь без метки уронит сторож, и решение
 * «человеку или поддержке» придётся принять, а не забыть.
 */
const СЛУЖЕБНЫЕ_ПО_ЗАМЫСЛУ = {
  'Не удалось загрузить обновление за':
    'к русскому началу приклеен английский хвост {last_err} — человеку на экран ему нельзя, '
    + 'а общий текст UP-002 говорит ровно то же и чисто',
  'Частичный файл не соответствует серверному':
    'внутреннее решение цикла докачки, человеку не показывается: следующая попытка качает заново',
  'Ответ на докачку противоречив':
    'то же самое — внутреннее решение цикла докачки',
  'Файл обновления повреждён при загрузке':
    'несёт обрывки шестнадцатеричных сумм; общий текст UP-003 объясняет то же человеческим языком',
};

describe('отказ обновления: деталь из Rust доезжает до человека', () => {
  it('сторож видит боевые ветки, а не пустоту', () => {
    // Если разбор исходника сломается, все проверки ниже станут зелёными на пустом
    // множестве. Эта проверка не даёт сторожу тихо умереть.
    expect(МЕТКИ.length, 'помеченные клиентские тексты обязаны находиться').toBeGreaterThanOrEqual(5);
    expect(МЕТКИ.some((в) => в.text.includes('прав администратора'))).toBe(true);
  });

  it.each(МЕТКИ)('[$code] $text', (ветка) => {
    const разобрано = describeUpdateError(wireFormat(ветка));
    expect(
      разобрано.human,
      'помеченная деталь обязана попасть на экран дословно, а не подмениться общим текстом по коду',
    ).toBe(ветка.text);
    if (ветка.code) {
      expect(разобрано.code, 'код для поддержки не теряется').toBe(ветка.code);
      expect(
        разобрано.human,
        'смысл правки в том, что деталь ТОЧНЕЕ таблицы: совпадение с таблицей означает, что выбор детали не работает',
      ).not.toBe(UPDATE_ERROR_TEXTS[ветка.code]);
    }
    expect(разобрано.raw, 'сырая строка для поддержки не теряется').toContain(ветка.text);
  });

  it.each(МЕТКИ)('правила клиентского текста: [$code] $text', ({ text }) => {
    const безПодстановок = text.replace(/\{[^}]*\}/g, '…').replace(/support@auroraai\.pro/g, '…');
    expect(text, `длинное тире вместо короткого: ${text}`).not.toContain('—');
    expect(безПодстановок, `латиница в клиентском тексте: ${text}`).not.toMatch(/[A-Za-z]/);
    expect(text, `текст обязан говорить, что сделать: ${text}`).toMatch(
      /нажмите|проверьте|напишите|подождите|выберите|перезапустите|освободите|закройте|попробуйте/,
    );
    expect(text.length, `слишком коротко, чтобы объяснить человеку: ${text}`).toBeGreaterThan(40);
  });

  it('русские детали без метки — только те, что оставлены служебными намеренно', () => {
    const безМетки = collectCalls(productionSource(RUST_UPDATER), 'coded_err')
      .filter(({ text }) => /[А-Яа-яЁё]/.test(text));
    const незнакомые = безМетки.filter(
      ({ text }) => !Object.keys(СЛУЖЕБНЫЕ_ПО_ЗАМЫСЛУ).some((кусок) => text.includes(кусок)),
    );
    expect(
      незнакомые.map((в) => в.text),
      'новая русская деталь появилась без метки — реши, кому она адресована: '
      + 'человеку (user_err) или поддержке (coded_err + запись сюда с причиной)',
    ).toEqual([]);
  });
});

describe('отказ обновления: самые дорогие сценарии', () => {
  it('отказ в правах администратора зовёт подтвердить права, а не чистить диск', () => {
    const raw = '[UP-004] [клиенту] Установщик не запустился: запрос прав администратора не подтверждён.'
      + ' Программа продолжает работать – нажмите «Повторить» и в системном окне с вопросом о разрешении выберите «Да».';
    const { human, code } = describeUpdateError(raw);
    expect(human).toContain('прав администратора');
    expect(human, 'про нехватку места человеку тут говорить нельзя').not.toContain('место');
    expect(human).not.toBe(UPDATE_ERROR_TEXTS['UP-004']);
    expect(code).toBe('UP-004');
  });

  it('нет сети: отказ приходит с кодом UP-001 и зовёт проверить подключение', () => {
    const { human, code } = describeUpdateError(
      'Update request failed: error sending request for url (https://ackold26.github.io/…)',
    );
    expect(code, 'без кода человек получит запасной текст').toBe('');
    expect(human, 'запасной текст обязан называть подключение').toContain('подключение к интернету');

    const сКодом = describeUpdateError('[UP-001] Update request failed: error sending request for url');
    expect(сКодом.code).toBe('UP-001');
    expect(сКодом.human).toContain('подключение к интернету');
    expect(сКодом.human, 'служебная английская деталь на экран не идёт').not.toContain('request');
  });

  it('сетевые отказы проверки обновления несут код, а не уходят голым «?»', () => {
    // Сторож стыка для H-2: текст про подключение полезен, только если код до него
    // доезжает. Голый `?` на сетевом вызове отдаёт строку БЕЗ кода, и человек читает
    // запасной текст. Проверяем обе ветки проверки обновления в исходнике.
    const источник = productionSource(RUST_UPDATER);
    for (const имя of ['check_supabase', 'check_github_pages']) {
      const начало = источник.indexOf(`async fn ${имя}(`);
      expect(начало, `функция ${имя} обязана существовать`).toBeGreaterThan(0);
      const тело = источник.slice(начало, источник.indexOf('\n}\n', начало));
      expect(тело, `${имя}: сетевой отказ обязан нести код UP-001`).toContain('ErrorCode::UP001');
      expect(тело, `${имя}: голый «?» на сетевом вызове теряет код`).not.toMatch(/\.(send|build)\(\)[\s\S]{0,20}?\?;/);
      expect(тело, `${имя}: неразобранный манифест обязан нести код UP-005`).toContain('ErrorCode::UP005');
    }
  });

  it('запасной текст говорит про подключение раньше, чем про письмо в поддержку', () => {
    expect(UPDATE_ERROR_FALLBACK.indexOf('подключение'))
      .toBeLessThan(UPDATE_ERROR_FALLBACK.indexOf('support@auroraai.pro'));
  });

  it('«обновление не требуется» — не то же, что отказ загрузки', () => {
    const текст = collectCalls(productionSource(RUST_LIB), 'updater::user_text')[0];
    expect(текст, 'ветка Ok(None) обязана иметь свой текст').toBeTruthy();
    const { human, code } = describeUpdateError(wireFormat(текст));
    expect(code, 'кода у этой ситуации нет — чужой код увёл бы поддержку по ложному следу').toBe('');
    expect(human).toContain('Перезапустите');
    expect(human, 'звать «Повторить» здесь бессмысленно: сервер не считает обновление нужным')
      .not.toContain('«Повторить»');
    expect(human).not.toBe(UPDATE_ERROR_FALLBACK);
  });
});

describe('отказ обновления: разбор кода', () => {
  it('чужие коды линейки под заголовком обновления не показываются (L-6)', () => {
    const { code, human } = describeUpdateError('[LI-005] срок лицензии истёк');
    expect(code, 'код лицензирования — не код обновления').toBe('');
    expect(human).toBe(UPDATE_ERROR_FALLBACK);
  });

  it('UP-005 больше не мёртвая ветка (L-1)', () => {
    const источник = productionSource(RUST_UPDATER);
    expect(
      источник,
      'текст UP-005 написан для человека и обязан быть достижим — иначе это мёртвый задел',
    ).toMatch(/coded_err\(ErrorCode::UP005/);
    expect(describeUpdateError('[UP-005] Update manifest is not readable: expected value').human)
      .toBe(UPDATE_ERROR_TEXTS['UP-005']);
  });

  it('отказ без строки и без кода всё равно объясняет человеку, что делать', () => {
    for (const пусто of [null, undefined, '', {}]) {
      const { human } = describeUpdateError(пусто);
      expect(human.length).toBeGreaterThan(40);
      expect(human).toContain('Повторить');
    }
  });
});
