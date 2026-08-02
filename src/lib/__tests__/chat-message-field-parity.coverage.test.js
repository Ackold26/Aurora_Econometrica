// @ts-nocheck — node-side тест (fs/path/process), тот же паттерн, что в других
// *.coverage.test.js гейтах этого продукта: svelte-check checkJs не имеет
// @types/node в scope, логика проверяется через vitest, не через типы.
/**
 * Охват: набор служебных полей сообщения чата на фронте (JSDoc typedef ChatMsg
 * в store.js) сверяется с набором полей структуры хранения истории на
 * бэкенде (ChatHistoryMessage в src-tauri/src/session/history.rs).
 *
 * Зачем гейт (CPD-29, реестр aurora-meta/CROSS_PRODUCT_DEFECT_REGISTRY.md):
 * isAutoContinue/isQuickReply были объявлены во фронтовом типе, рендерились в
 * шаблоне, но НЕ сохранялись в Rust-структуре и не восстанавливались при
 * loadHistory — после перезагрузки пользователь читал сырую промпт-инструкцию
 * модели вместо компактной метки «Авто-продолжение». Это класс дефекта, не
 * единичный случай: любое новое служебное поле фронта рискует повторить его
 * молча.
 *
 * Гейт закрывает класс: новое поле ChatMsg обязано либо появиться в
 * ChatHistoryMessage (camelCase фронта ↔ snake_case Rust сверяется
 * автоматически, структура сериализуется с #[serde(rename_all = "camelCase")]),
 * либо быть явно занесено в реестр эфемерных полей ниже — с обоснованием,
 * почему поле сознательно не персистентно.
 *
 * Реестр ведётся ПО ИМЕНИ поля, не по номеру строки — номера сползают при
 * правках и молча теряют актуальность.
 *
 * Страховка от тихого нуля: если сверено 0 полей — это КРАСНЫЙ, а не «всё
 * чисто»: значит парсер typedef/struct смотрит не туда (файл переехал,
 * разметка типа изменилась).
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const STORE_JS = path.join(process.cwd(), 'src/lib/store.js');
const HISTORY_RS = path.join(process.cwd(), 'src-tauri/src/session/history.rs');
const CHAT_PANEL = path.join(process.cwd(), 'src/lib/components/ChatPanel.svelte');

/**
 * Поля фронта, которые сознательно НЕ персистентны — с обоснованием по
 * каждому. Ключ реестра — имя поля ТОЧНО как в typedef ChatMsg.
 * На момент написания гейта у ChatMsg Econometrica таких полей нет (в отличие
 * от Creative Hub, где есть счётчик id для сопоставления потоковых чанков) —
 * реестр пуст, но остаётся на случай появления такого поля в будущем.
 * @type {Record<string, string>}
 */
const EPHEMERAL_FIELDS = {};

/** @param {string} camel @returns {string} */
function toSnakeCase(camel) {
  return camel.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
}

describe('охват: паритет полей сообщения чата — фронт (ChatMsg) ↔ хранение (ChatHistoryMessage)', () => {
  it('каждое поле ChatMsg либо сохраняется в history.rs, либо занесено в EPHEMERAL_FIELDS', () => {
    const storeSrc = fs.readFileSync(STORE_JS, 'utf8');
    // Имя типа сверяется С ГРАНИЦЕЙ имени. Без границы выражение цепляется за
    // ChatMsgCore / ChatMsgBase и молча сверяет набор полей ЧУЖОГО (базового)
    // типа, а поля самого ChatMsg, добавленные через пересечение, не проверяет
    // вовсе. Проверено мутационно 2026-07-29 (Docs Lab): разбиение
    // `@typedef {{role, content, ts}} ChatMsgCore` +
    // `@typedef {ChatMsgCore & {…, isPinned}} ChatMsg` давало ЗЕЛЁНЫЙ гейт при
    // поле isPinned без пары в history.rs. Разбиение с непрефиксным именем
    // (BaseMsg) краснело и до правки — дыра была ровно в префиксе имени.
    const declarations = [...storeSrc.matchAll(/@typedef\s+([^\n]+?)\s+ChatMsg(?![A-Za-z0-9_$])/g)];
    expect(declarations.length, 'объявление типа ChatMsg не найдено в store.js (или их несколько) — разметка переехала').toBe(1);
    const inlineForm = declarations[0][1].match(/^\{\{(.*)\}\}$/s);
    expect(
      inlineForm,
      `тип ChatMsg объявлен составным: ${declarations[0][1]} — гейт разбирает только инлайн-объект {{…}}, поля из частей типа остались бы несверенными; расширь гейт до составных объявлений`,
    ).toBeTruthy();
    const frontendFields = [...inlineForm[1].matchAll(/(\w+)\??:/g)].map((m) => m[1]);
    expect(frontendFields.length, 'typedef ChatMsg найден, но полей не распознано — регекс смотрит не туда').toBeGreaterThan(0);

    const historySrc = fs.readFileSync(HISTORY_RS, 'utf8');
    const structMatch = historySrc.match(/pub struct ChatHistoryMessage\s*\{([^}]*)\}/s);
    expect(structMatch, 'struct ChatHistoryMessage не найдена в history.rs — разметка переехала').toBeTruthy();
    const rustFields = [...structMatch[1].matchAll(/pub\s+(\w+):/g)].map((m) => m[1]);
    expect(rustFields.length, 'struct ChatHistoryMessage найдена, но полей не распознано — регекс смотрит не туда').toBeGreaterThan(0);

    let compared = 0;
    const missing = [];
    for (const field of frontendFields) {
      if (Object.prototype.hasOwnProperty.call(EPHEMERAL_FIELDS, field)) continue;
      compared++;
      if (!rustFields.includes(toSnakeCase(field))) missing.push(field);
    }

    // Страховка от тихого нуля: если EPHEMERAL_FIELDS случайно накрыл ВСЕ
    // поля фронта (или парсер их не увидел), сверка выше молча "проходит",
    // не проверив ничего реального — это красный, не зелёный.
    expect(compared, `сверено 0 полей (${frontendFields.length} найдено в typedef, все — в EPHEMERAL_FIELDS) — гейт ничего не проверил`).toBeGreaterThan(0);
    expect(missing, `поля фронта без пары в history.rs и без записи в EPHEMERAL_FIELDS: ${missing.join(', ')}`).toEqual([]);
  });
  it('каждое персистентное поле реально ЕДЕТ: передаётся в сохранение и восстанавливается при загрузке', () => {
    // Объявление поля в обоих типах ещё не значит, что оно доезжает. Поле может
    // стоять и во фронтовом типе, и в структуре хранения — и не попасть в
    // аргументы команды сохранения или в разбор загруженной истории. Сверка
    // только объявлений такой разрыв не видит, а пользователь теряет признак
    // ровно так же, как при отсутствии поля в хранении (CPD-29).
    const storeSrc = fs.readFileSync(STORE_JS, 'utf8');
    const declarations = [...storeSrc.matchAll(/@typedef\s+([^\n]+?)\s+ChatMsg(?![A-Za-z0-9_$])/g)];
    expect(declarations.length, 'объявление типа ChatMsg не найдено в store.js (или их несколько) — разметка переехала').toBe(1);
    const inlineForm = declarations[0][1].match(/^\{\{(.*)\}\}$/s);
    expect(inlineForm, `тип ChatMsg объявлен составным: ${declarations[0][1]} — гейт разбирает только инлайн-объект {{…}}`).toBeTruthy();
    const frontendFields = [...inlineForm[1].matchAll(/(\w+)\??:/g)].map((m) => m[1]);

    const panelSrc = fs.readFileSync(CHAT_PANEL, 'utf8');
    const saveCall = panelSrc.match(/invoke\(\s*['"]save_chat_message['"][\s\S]{0,800}?\)\s*;/);
    expect(saveCall, 'вызов save_chat_message не найден в ChatPanel.svelte — разметка переехала').toBeTruthy();
    const restoreBlock = panelSrc.match(/messages\.set\(\s*history\.map\([\s\S]{0,900}?\)\s*\)\s*;/);
    expect(restoreBlock, 'восстановление истории (messages.set(history.map(…))) не найдено в ChatPanel.svelte — разметка переехала').toBeTruthy();

    // 🔴 Внешний аудит 2026-07-29 (High): проверка поиском ПОДСТРОКИ удовлетворялась
    // (а) упоминанием имени в комментарии внутри окна («// TODO: isPinned пока не
    // восстанавливаем» делало гейт зелёным при невосстанавливаемом поле) и (б) совпадением
    // с ФРАГМЕНТОМ другого идентификатора (поле `attachments` считалось переданным, если в
    // вызове стоял ключ `attachmentsMeta`). Комментарии вырезаем, имя ищем с границами.
      // Якорь `$` здесь НЕ ставится намеренно: файлы хранятся с переводом строки Windows,
      // и после split('\n') строка оканчивается на \r, который точка в JS не берёт — с якорем
      // выражение не срабатывало вовсе, комментарии оставались в окне, и проверка была
      // ложно-зелёной (поймано при доказательстве красноты 2026-07-29).
    const stripComments = (/** @type {string} */ src) =>
      src.split('\n').map((line) => line.replace(/\/\/.*/, '')).join('\n');
    const saveWindow = stripComments(saveCall[0]);
    const restoreWindow = stripComments(restoreBlock[0]);
    const mentions = (/** @type {string} */ window, /** @type {string} */ field) =>
      new RegExp(`(^|[^A-Za-z0-9_$])${field}([^A-Za-z0-9_$]|$)`).test(window);

    let checked = 0;
    const notSent = [];
    const notRestored = [];
    for (const field of frontendFields) {
      if (Object.prototype.hasOwnProperty.call(EPHEMERAL_FIELDS, field)) continue;
      checked++;
      if (!mentions(saveWindow, field)) notSent.push(field);
      if (!mentions(restoreWindow, field)) notRestored.push(field);
    }

    // Та же страховка от тихого нуля, что и в сверке объявлений.
    expect(checked, `проверено 0 полей на транспорт (${frontendFields.length} в typedef) — гейт ничего не проверил`).toBeGreaterThan(0);
    expect(notSent, `поля объявлены и хранятся, но НЕ передаются в save_chat_message: ${notSent.join(', ')} — после перезагрузки пропадут молча`).toEqual([]);
    expect(notRestored, `поля объявлены и хранятся, но НЕ восстанавливаются при загрузке истории: ${notRestored.join(', ')} — в файле они есть, до пользователя не доедут`).toEqual([]);
  });
});
