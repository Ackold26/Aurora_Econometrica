/**
 * Сторож: когда пороги окупаемости отключены, экран говорит об этом прямо.
 *
 * ЗАЧЕМ. Движок честно отключает абсолютные пороги, когда денежного отношения
 * нет (`engines/channel_action.py`: «При money_roi_unavailable=True абсолютные
 * breakeven-пороги (шаги 4, 6, 7, 8) НЕ применяются»). Но признак жил ТОЛЬКО
 * внутри Python и во фронт не отдавался — экран показывал вердикты как обычно,
 * и пользователь не мог знать, что сравнения с точкой безубыточности за ними
 * нет. Молчание здесь хуже отсутствия функции: человек читает вердикт как
 * абсолютный, а он относительный.
 *
 * Признак приходит из движка (`decomposer.py` → `money_roi_unavailable`).
 * Вычислять его на фронте нельзя: это второй источник истины, и он разойдётся —
 * ровно так ломались ярусы MQS.
 */
import { describe, expect, it } from 'vitest';

import { decomposeInsights } from '../insights-rules.js';

/** Минимальный ответ декомпозиции. @param {Record<string, any>} extra */
const payload = (extra) => ({
  channels: [],
  baseline_pct: 60,
  total_sales: 1000,
  ...extra,
});

const texts = (/** @type {Record<string, any>} */ data) =>
  decomposeInsights(/** @type {any} */ (data))
    .map((/** @type {{text: string, tip?: string}} */ i) => `${i.text} ${i.tip ?? ''}`)
    .join('\n');

describe('признак отключённых порогов доезжает до пользователя', () => {
  it('при отключённых порогах сообщение показано', () => {
    const blob = texts(payload({ money_roi_unavailable: true }));
    expect(blob).toContain('пороги окупаемости отключены');
  });

  it('сообщение объясняет, на что опираются вердикты вместо порогов', () => {
    const blob = texts(payload({ money_roi_unavailable: true }));
    expect(blob).toContain('относительную эффективность');
  });

  it('сообщение подсказывает, как получить абсолютную оценку', () => {
    const blob = texts(payload({ money_roi_unavailable: true }));
    expect(blob).toContain('ценность единицы');
  });

  it('при работающих порогах сообщения нет — лишний шум недопустим', () => {
    expect(texts(payload({ money_roi_unavailable: false }))).not.toContain(
      'пороги окупаемости отключены',
    );
  });

  it('старые ответы без поля молчат так же, как раньше', () => {
    // Признак появился 2026-08-02; результаты, посчитанные до него, поля не
    // имеют. Показать им сообщение значило бы соврать: пороги там работали.
    expect(texts(payload({}))).not.toContain('пороги окупаемости отключены');
  });

  it('строковое «true» из старых артефактов за признак не принимается', () => {
    // Сравнение строгое (=== true): иначе любое непустое значение включало бы
    // сообщение, а поле приходит из JSON, где типы уже путались (см. историю
    // ярлыка mqs_tier_label).
    expect(texts(payload({ money_roi_unavailable: 'true' }))).not.toContain(
      'пороги окупаемости отключены',
    );
  });
});
