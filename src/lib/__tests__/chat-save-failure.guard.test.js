// @ts-nocheck — node-side часть теста (fs/path/process), тот же паттерн, что в остальных
// *.guard.test.js этого продукта.
/**
 * Сторож CPD-41 (блокирующий, тихая потеря данных клиента).
 *
 * Дефект: сохранение реплики вызывалось как
 *   `try { await invoke('save_chat_message', …) } catch { /* non-critical *\/ }`
 * — бэкенд отказ возвращал исправно, а интерфейс его отбрасывал. Пользователь видел успешный
 * экран, а сообщение на диск не легло; узнать о пропаже можно было только перезапустив продукт.
 *
 * 🔴 Отдельная тяжесть: на предпосылке «клиент видит отказ и повторит отправку» построено
 * проектное решение ядра (батч C, пункт C4) — при занятом замке реплика пользователя сознательно
 * отклоняется. Интерфейс эту предпосылку отменял, то есть решение ядра держалось на условии,
 * которое не наступало.
 *
 * Гейт проверяет ОБА слоя, потому что каждый по отдельности обходится:
 *  1. поведение — чистая функция пометки (её можно позвать и проверить);
 *  2. связь — что `catch` у вызова сохранения действительно эту функцию зовёт. Без второго
 *     возврат к `catch {}` оставил бы функцию покрытой, а продукт — молчащим (урок Ф-04:
 *     вынесенная функция покрыта, её вызов — нет).
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { markMessageUnsaved } from '../chat-save-status.js';

const CHAT_PANEL = path.join(process.cwd(), 'src/lib/components/ChatPanel.svelte');

describe('сторож CPD-41: отказ сохранения переписки виден пользователю', () => {
  it('помечает ровно то сообщение, сохранение которого не удалось', () => {
    const lenta = [
      { role: 'user', content: 'первый вопрос', ts: 100 },
      { role: 'assistant', content: 'ответ', ts: 200 },
      { role: 'user', content: 'второй вопрос', ts: 300 },
    ];

    const after = markMessageUnsaved(lenta, 'user', 300);

    expect(after[2].unsaved, 'несохранённое сообщение обязано быть помечено').toBe(true);
    expect(after[0].unsaved, 'чужая реплика не имеет права получить пометку').toBeUndefined();
    expect(after[1].unsaved, 'ответ модели не имеет права получить пометку').toBeUndefined();
  });

  it('различает сообщения с совпадающей отметкой времени по роли', () => {
    // Реплика пользователя и быстрый ответ могут лечь в одну миллисекунду. Пометить чужой
    // пузырь — соврать пользователю о противоположном: он бы решил, что потерян ответ.
    const lenta = [
      { role: 'user', content: 'спасибо', ts: 500 },
      { role: 'assistant', content: 'Пожалуйста!', ts: 500, isQuickReply: true },
    ];

    const after = markMessageUnsaved(lenta, 'assistant', 500);

    expect(after[1].unsaved).toBe(true);
    expect(after[0].unsaved, 'совпадение отметки времени не должно задевать другую роль').toBeUndefined();
  });

  it('не изменяет исходную ленту', () => {
    const lenta = [{ role: 'user', content: 'вопрос', ts: 100 }];
    markMessageUnsaved(lenta, 'user', 100);
    expect(lenta[0].unsaved, 'исходный массив обязан остаться нетронутым').toBeUndefined();
  });

  it('связь: отказ сохранения в ChatPanel не глотается, а помечает сообщение и говорит пользователю', () => {
    const src = fs.readFileSync(CHAT_PANEL, 'utf8');

    // Окно — от объявления saveMsg до следующей функции. Границу НЕ ставим по «\n}» :
    // файлы хранятся с переводом строки Windows, и выражение не срабатывает вовсе, оставляя
    // сторож ложно-красным (та же грабля, что поймана в chat-message-field-parity 2026-07-29).
    const saveBlock = src.match(/async function saveMsg[\s\S]*?async function clearHistory/);
    expect(saveBlock, 'функция saveMsg не найдена в ChatPanel.svelte — разметка переехала').toBeTruthy();
    const window = saveBlock[0];
    expect(
      /invoke\(\s*['"]save_chat_message['"]/.test(window),
      'в saveMsg нет вызова save_chat_message — окно поймало не ту функцию',
    ).toBe(true);

    // Комментарии вырезаем: внутри обработки отказа прежняя форма процитирована намеренно —
    // она объясняет, что именно было дефектом. Без вырезания сторож ловил бы объяснение вместо
    // кода и краснел на верной правке (поймано первым же прогоном).
    const code = window.split('\n').map((line) => line.replace(/\/\/.*/, '')).join('\n');
    expect(
      /catch\s*(\([^)]*\))?\s*\{\s*(\/\*[\s\S]*?\*\/)?\s*\}/.test(code),
      'отказ сохранения снова глотается пустым catch — это тихая потеря переписки клиента (CPD-41)',
    ).toBe(false);

    expect(
      /markMessageUnsaved\s*\(/.test(window),
      'в обработке отказа нет пометки сообщения: пользователь не узнает, ЧТО именно не сохранилось',
    ).toBe(true);

    expect(
      /toast\s*\(/.test(window),
      'в обработке отказа нет уведомления пользователю: молчать при потере данных нельзя (INV-50)',
    ).toBe(true);
  });

  it('связь: лента показывает признак несохранённого сообщения', () => {
    const src = fs.readFileSync(CHAT_PANEL, 'utf8');
    expect(
      /\{#if\s+msg\.unsaved\}/.test(src),
      'в разметке ленты нет ветки msg.unsaved — пометка ставится, но пользователю не видна',
    ).toBe(true);
  });
});
