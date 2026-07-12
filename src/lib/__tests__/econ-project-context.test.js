/**
 * econ-project-context - блок с данными проекта, инъецируемый в сообщение
 * консультационных команд econometrist (правило №10 CLAUDE.md: pipeline
 * context в message, не файл).
 */
import { describe, it, expect } from 'vitest';
import { ECON_DATA_COMMANDS, buildProjectDataBlock } from '../econ-project-context.js';
import decomposition from './fixtures/kagocel-load1/decomposition.json';

describe('ECON_DATA_COMMANDS', () => {
  it('содержит все 6 консультационных команд', () => {
    expect(ECON_DATA_COMMANDS).toEqual([
      '/interpret-model',
      '/why-channel',
      '/explain-ratio',
      '/pilot-design',
      '/next-quarter-plan',
      '/data-gaps',
    ]);
  });
});

describe('buildProjectDataBlock - все секции присутствуют', () => {
  const block = buildProjectDataBlock({
    mod: { diagnostics: { metrics: { r_squared: 0.87 } } },
    dec: decomposition,
    opt: { expected_lift_pct: 5.7, channels: [] },
    projectMeta: { name: 'Кагоцел Q3', kpi_type: 'sales' },
  });

  it('содержит заголовок и все 4 секции', () => {
    expect(block).toContain('=== Данные проекта (приложены приложением) ===');
    expect(block).toContain('[model-diagnostics]');
    expect(block).toContain('[decomposition]');
    expect(block).toContain('[optimization]');
    expect(block).toContain('[project]');
  });

  it('секция project содержит переданную мету', () => {
    expect(block).toContain('Кагоцел Q3');
    expect(block).toContain('sales');
  });
});

describe('buildProjectDataBlock - отсутствующий артефакт', () => {
  it('null-артефакт → «нет – шаг … не пройден», а не пустой объект', () => {
    const block = buildProjectDataBlock({ mod: null, dec: null, opt: null, projectMeta: null });
    expect(block).toContain('нет – шаг «Модель» не пройден');
    expect(block).toContain('нет – шаг «Декомпозиция» не пройден');
    expect(block).toContain('нет – шаг «Оптимизация» не пройден');
    expect(block).not.toContain('{}');
  });

  it('все три стора пусты (кабинет открыт без прогона) - блок всё равно приложен целиком', () => {
    const block = buildProjectDataBlock({});
    expect(block).toContain('[model-diagnostics]');
    expect(block).toContain('нет – шаг «Модель» не пройден');
    expect(block).toContain('[decomposition]');
    expect(block).toContain('нет – шаг «Декомпозиция» не пройден');
    expect(block).toContain('[optimization]');
    expect(block).toContain('нет – шаг «Оптимизация» не пройден');
  });

  it('отсутствующая projectMeta (null) - секция [project] опускается', () => {
    const block = buildProjectDataBlock({ mod: null, dec: null, opt: null, projectMeta: null });
    expect(block).not.toContain('[project]');
  });
});

describe('buildProjectDataBlock - служебная телеметрия optimization вырезана', () => {
  const opt = {
    expected_lift_pct: 5.7,
    slsqp_diagnostics: { n_starts: 9, best_objective: -141.79413709408556 },
    response_curves: { 'ТВ': { spend: [1, 2, 3], response: [137.2, 140.1, 142.9] } },
    channels: [],
  };
  const block = buildProjectDataBlock({ mod: null, dec: null, opt, projectMeta: null });

  it('slsqp_diagnostics вырезан из optimization', () => {
    expect(block).not.toContain('slsqp_diagnostics');
    expect(block).not.toContain('141.79413709408556');
  });

  it('response_curves вырезан из optimization', () => {
    expect(block).not.toContain('response_curves');
  });

  it('остальные поля optimization сохранены', () => {
    expect(block).toContain('expected_lift_pct');
    expect(block).toContain('5.7');
  });
});

describe('buildProjectDataBlock - decomposition не режется', () => {
  const block = buildProjectDataBlock({ mod: null, dec: decomposition, opt: null, projectMeta: null });

  it('числа декомпозиции присутствуют в блоке (величиной)', () => {
    // Та же фикстура, что tier2-context.test.js: baseline_pct=80.6, канал «Статьи» roi=77.49.
    expect(block).toContain('80.6');
    expect(block).toContain('77.49');
    expect(block).toContain('Статьи');
  });

  it('decomposition приложен без урезки полей (raw JSON фикстуры)', () => {
    expect(block).toContain(JSON.stringify(decomposition));
  });
});

describe('validation-секция (сверка контракта S1<->S2, 2026-07-12)', () => {
  it('выжимка валидации попадает в блок: ratio + списки колонок по ролям', () => {
    const val = { result: {
      detected: { ratio: 5.2, date_frequency: 'weekly' },
      file: { rows: 104 },
      columns: [
        { name: 'TV', role: 'media' }, { name: 'OLV', role: 'media' },
        { name: 'Price', role: 'control' }, { name: 'Sales', role: 'kpi' },
      ],
    } };
    const block = buildProjectDataBlock({ val });
    expect(block).toContain('[validation]');
    expect(block).toContain('5.2');
    expect(block).toContain('"TV"');
    expect(block).toContain('"Price"');
    expect(block).not.toContain('нет – шаг «Валидация» не пройден');
  });

  it('без валидации секция честно говорит, какого шага не хватает', () => {
    const block = buildProjectDataBlock({});
    expect(block).toContain('[validation]');
    expect(block).toContain('нет – шаг «Валидация» не пройден');
  });
});
