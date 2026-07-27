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
    const typedefMatch = storeSrc.match(/@typedef\s+\{\{([^}]*)\}\}\s+ChatMsg/);
    expect(typedefMatch, 'typedef ChatMsg не найден в store.js — разметка переехала').toBeTruthy();
    const frontendFields = [...typedefMatch[1].matchAll(/(\w+)\??:/g)].map((m) => m[1]);
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
});
