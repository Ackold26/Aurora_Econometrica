/**
 * Юнит-тесты автогрейдеров эвал-харнеса кабинета econometrist
 * (tools/cabinet_eval/graders.mjs).
 *
 * Рычаг 1 (полировка 2026-07-13): эвал-харнес называет ответ «хорошим» или
 * «плохим» по вердиктам грейдеров — но сами грейдеры не были покрыты тестами.
 * Грейдер, который не РАЗЛИЧАЕТ хороший и плохой ответ, превращает эвал в
 * декоративный обвес (ложное «PASS» опаснее отсутствия проверки — тот же урок,
 * что линтеры Батча 5). Это детерминированная «негативная проба»: на каждый
 * грейдер — заведомо ХОРОШИЙ ответ (ждём pass) и заведомо ПЛОХОЙ (ждём FAIL).
 * Egress не нужен (грейдеры — чистые функции), в отличие от живого прогона.
 * Заодно — регресс-страж самих грейдеров (ослабление регэкспа уронит тест).
 */
import { describe, it, expect } from 'vitest';
import {
  numbersGrounded,
  noCliArtifacts,
  russianLanguage,
  structureTakeaway,
  honestyMissingStep,
  noEnvPaths,
} from '../../../tools/cabinet_eval/graders.mjs';

describe('numbersGrounded (INV-50): различает грунт/негрунт числа', () => {
  const facts = { channels: [{ name: 'ТВ', roi: 45.7, contribution_pct: 62.3 }] };
  const ctx = { caseId: 'test', facts };

  it('PASS: числа ответа взяты из приложенных фактов', () => {
    expect(numbersGrounded('ROI канала ТВ равен 45.7, его вклад 62.3%.', ctx).pass).toBe(true);
  });
  it('FAIL: число не из фактов и без пометки расчёта — выдумка', () => {
    expect(numbersGrounded('Прирост продаж составит 88.8% в следующем квартале.', ctx).pass).toBe(false);
  });
  it('PASS: то же число, помеченное как оценка/расчёт (средний путь INV-50)', () => {
    expect(numbersGrounded('Прирост продаж оценочно 88.8%.', ctx).pass).toBe(true);
  });
});

describe('noCliArtifacts: ловит slash-команды и служебную фразу', () => {
  it('PASS: чистый консультационный ответ', () => {
    expect(noCliArtifacts('Разбор канала показывает высокий вклад и надёжный ROI.').pass).toBe(true);
  });
  it('FAIL: предложение вызвать slash-команду', () => {
    expect(noCliArtifacts('Для распределения бюджета запустите /mmm-optimize.').pass).toBe(false);
  });
  it('FAIL: служебная фраза завершения пайплайна в консультации', () => {
    expect(noCliArtifacts('Разбор готов. Все задачи выполнены.').pass).toBe(false);
  });
});

describe('russianLanguage: доля кириллицы и длинные англ. фразы', () => {
  it('PASS: русский текст с признанными терминами', () => {
    expect(russianLanguage('Качество модели по метрике MAPE и показателю ROI в пределах нормы.').pass).toBe(true);
  });
  it('FAIL: длинная английская фраза (не термины)', () => {
    expect(russianLanguage('This is a very long english sentence that clearly exceeds the allowed limit here.').pass).toBe(false);
  });
});

describe('structureTakeaway: вывод сверху + блок действия', () => {
  it('PASS: короткий вывод первой строкой + блок «что улучшить»', () => {
    expect(structureTakeaway('Модель надёжна: R² высокий, диапазоны узкие.\n\nЧто улучшить: добавить контрольные переменные.').pass).toBe(true);
  });
  it('FAIL: есть вывод, но нет блока действия/рекомендации', () => {
    expect(structureTakeaway('Модель показывает результаты в пределах ожидаемого диапазона значений.').pass).toBe(false);
  });
});

describe('honestyMissingStep: честность об отсутствующем шаге', () => {
  it('PASS: ответ прямо называет непройденный шаг «Оптимизация»', () => {
    expect(honestyMissingStep('Шаг «Оптимизация» не пройден — сначала запустите его.').pass).toBe(true);
  });
  it('FAIL: выдаёт оптимум при отсутствии шага, молчит об этом', () => {
    expect(honestyMissingStep('Оптимальный сплит: ТВ 40%, диджитал 60%.').pass).toBe(false);
  });
});

describe('noEnvPaths: пути окружения не утекают в текст', () => {
  it('PASS: без путей файловой системы', () => {
    expect(noEnvPaths('Результаты сохранены в папку экспорта проекта.').pass).toBe(true);
  });
  it('FAIL: абсолютный путь C:\\...', () => {
    expect(noEnvPaths('Файл лежит в C:\\Users\\data\\project.').pass).toBe(false);
  });
  it('FAIL: упоминание APPDATA', () => {
    expect(noEnvPaths('Путь %APPDATA%\\vault сейчас недоступен.').pass).toBe(false);
  });
});
