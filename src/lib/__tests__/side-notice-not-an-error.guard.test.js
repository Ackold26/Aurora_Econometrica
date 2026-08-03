// @ts-nocheck — node-side часть теста (fs/path/url), тот же приём, что в остальных
// *.guard.test.js этого продукта: проверка типов не знает про node-модули в тестах.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { getEmpathyError } from '../psy.js';

const here = dirname(fileURLToPath(import.meta.url));
const chatPanel = readFileSync(resolve(here, '../components/ChatPanel.svelte'), 'utf8');
const libRs = readFileSync(resolve(here, '../../../src-tauri/src/lib.rs'), 'utf8');

/**
 * 🔴 Находка внешнего аудита: предупреждение о ПОБОЧНОМ при полученном ответе (файл в папке
 * результатов занят другой программой) уходило как `type: "error"` и проходило через
 * `getEmpathyError`. Без кода `[CL-NN]` тот ставит заголовок «Произошла ошибка», а точный текст
 * прячет в подпись — человек читает первую строку и видит «ошибка» там, где работа сделана.
 * Это ровно то ложное утверждение продукта о себе (INV-50), которое блок и выкорчёвывает.
 */
describe('побочное предупреждение не выглядит отказом', () => {
	it('getEmpathyError без кода действительно даёт заголовок «Произошла ошибка»', () => {
		// Основание находки: если это перестанет быть правдой, сторожа ниже можно ослабить.
		const empathy = getEmpathyError('Ответ получен. Не обновлены файлы в папке результатов: отчёт.docx');
		expect(empathy.message).toBe('Произошла ошибка');
		expect(empathy.code).toBeNull();
	});

	it('фронт обрабатывает тип notice отдельной веткой, не через getEmpathyError', () => {
		expect(chatPanel).toContain("data.type === 'notice'");
		const noticeAt = chatPanel.indexOf("data.type === 'notice'");
		const errorAt = chatPanel.indexOf("data.type === 'error'");
		expect(noticeAt).toBeGreaterThan(-1);
		expect(errorAt).toBeGreaterThan(noticeAt);
		// Внутри ветки notice эмпатичный преобразователь звать нельзя — он и добавляет слово
		// «ошибка» к сообщению об успешном ответе.
		// 🔴 Комментарии вырезаются до поиска: пояснение «через getEmpathyError не проводим»
		// внутри самой ветки иначе читается как её вызов — сторож покраснел на этом первым же
		// прогоном (та же ловушка, что и у Rust-сторожа путей записи).
		const noticeBranch = chatPanel
			.slice(noticeAt, errorAt)
			.split('\n')
			.filter((line) => !line.trim().startsWith('//'))
			.join('\n');
		expect(noticeBranch).not.toContain('getEmpathyError(');
	});

	it('сообщение о незаписанных файлах отправляется с типом notice, а не error', () => {
		const at = libRs.indexOf('Не обновлены файлы в папке результатов');
		expect(at).toBeGreaterThan(-1);
		// Окно берём от начала отправки события до самого текста: тип объявляется выше текста.
		const from = libRs.lastIndexOf('app_handle.emit', at);
		const window = libRs.slice(from, at);
		expect(window).toContain('"type": "notice"');
		expect(window).not.toContain('"type": "error"');
	});
});
