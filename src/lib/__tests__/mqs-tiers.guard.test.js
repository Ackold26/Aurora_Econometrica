// @ts-nocheck — node-side тест (fs/path/process); svelte-check checkJs не имеет
// @types/node в scope. Логика проверяется через vitest, не через типы.
/**
 * Гард единого источника порогов MQS (2026-07-26, внешний аудит седьмой волны).
 *
 * Инцидент L16 закрывали заведением `mqs_tier_info()` в Python, но перевели на
 * него только отчёты. Интерфейс сохранил свою лестницу 80/60 — и при MQS=70
 * слайд говорил «Хорошее», а панель выводов «приемлемое качество». Греп «всех
 * мест» ловит существующие N, но не будущий N+1, поэтому гард структурный:
 *
 *   1. ПАРИТЕТ — таблица `MQS_TIERS` совпадает с питоновским `_MQS_TIERS`
 *      порог-в-порог, ярлык-в-ярлык, цвет-в-цвет. Правка одной стороны без
 *      второй красит гейт.
 *   2. НЕТ ГОЛЫХ ПОРОГОВ — ни один файл `src/` не сравнивает MQS с числом.
 *      Ветвление только по имени уровня (`mqsTierInfo(score).tier`).
 *   3. НЕТ РУЧНОГО ТЕКСТА ШКАЛЫ — описание шкалы в подсказках собирается
 *      `mqsScaleText()`, а не пишется числами в строке. Иначе поведение и его
 *      описание расходятся молча (ровно это и нашёл аудит в MQSBadge).
 *
 * Защита от тихого нуля: гард падает, если сканировать оказалось нечего.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { MQS_TIERS, mqsTierInfo, mqsTone, mqsIsDependable, mqsScaleText } from '../mqs-tiers.js';

const SRC_DIR = path.join(process.cwd(), 'src');
const PY_CANON = path.join(process.cwd(), 'sidecar', 'econometrica', 'utils', 'diagnostics.py');

/** @param {string} dir @returns {string[]} */
function walk(dir) {
  /** @type {string[]} */
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name === '.svelte-kit') continue;
      out.push(...walk(p));
    } else if (/\.(js|svelte)$/.test(e.name)) {
      out.push(p);
    }
  }
  return out;
}

/** Файлы, которым разрешено знать числа: сам источник порогов. */
const ALLOWED = new Set(['mqs-tiers.js']);

/**
 * Узаконенные исключения — ПО ТЕКСТУ ЛИТЕРАЛА, а не по номеру строки.
 * Номера сползают при любой правке файла, и реестр по ним молча протухает.
 * Каждая запись обязана нести обоснование в комментарии рядом.
 * @type {string[]}
 */
const LEGITIMISED = [
  // Сравнение ДВУХ моделей между собой: 10 — это величина расхождения баллов,
  // а не граница уровня качества. К шкале 85/70/55/40 отношения не имеет.
  'Math.abs(mqsA - mqsB) > 10',
];

// `mqs >= 80`, `(mqsScore ?? 0) >= 60`, `mqs != null && mqs < 60`,
// `mqs_score >= 80`, `diagnostics.mqs.score >= 80`.
// Сравниваемое обязано стоять ВПЛОТНУЮ перед оператором: иначе правило ловило
// соседнюю метрику на той же строке — `mqsIsDependable(mqs) && rHat > 0`
// засчитывалось за свою шкалу MQS, хотя сравнивается сходимость.
// Идентификатор продолжается через `[A-Za-z0-9_]` (не только буквы — иначе
// слепо к `mqs_score`) и через цепочку доступа по точке (`mqs.score`,
// `diagnostics.mqs.score`). Конец идентификатора проверяется предпросмотром
// `(?![A-Za-z0-9_])`, а не `\b`: `\b` не видит границы между «s» и «_» —
// оба словесные символы, поэтому старое правило слепло на `mqs_score`.
const CMP_AFTER = /\bmqs[A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*\s*(?:\?\?\s*\d+\s*\)?\s*)?(?:>=|<=|>|<)\s*\d{1,3}/i;
// `80 <= mqs`
const CMP_BEFORE = /\d{1,3}\s*(?:>=|<=|>|<)[^\n]{0,20}\bmqs[A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*(?![A-Za-z0-9_])/i;
// `tierUp(mqs, 80, 60)` — пороги аргументами
const THRESHOLD_ARGS = /\bmqs[A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*(?![A-Za-z0-9_])\s*,\s*\d{1,3}\s*,\s*\d{1,3}/i;
// Идентификатор, оканчивающийся на `score`/`Score`, сравниваемый со СТАРОЙ
// лестницей 80/60 (докат L16: `mqs_score >= 80`, `diagnostics.mqs.score >= 60`
// — поле верное, но мерят его по прежней шкале, не 85/70/55/40). Узко: и
// хвост идентификатора «score», И порог ровно 80 или 60. Префикс перед
// «score» опционален (`(?:...)?`, не требует `mqs`), поэтому ловит и ГОЛОЕ
// `score` (`if (score >= 80)` — в т.ч. после `const { score } = mqsView()`
// строкой выше: гард построчный, а сравнение уже голое на своей строке), и
// обёртку вызовом вокруг поля (`Number(row.mqs_score) >= 80` — `\s*\)*\s*`
// пропускает закрывающие скобки обёртки перед оператором). Шире не делать —
// само по себе достаточно узко: два условия разом (хвост «score» + порог
// ровно 80/60) отсекают почти все посторонние метрики.
const OLD_SCALE_SCORE_AFTER = /\b(?:[A-Za-z_][A-Za-z0-9_.]*)?score(?![A-Za-z0-9_])\s*\)*\s*(?:\?\?\s*\d+\s*\)?\s*)?(?:>=|<=|>|<)\s*(?:80|60)(?!\d)/i;
const OLD_SCALE_SCORE_BEFORE = /(?:80|60)(?!\d)\s*(?:>=|<=|>|<)[^\n]{0,20}\b(?:[A-Za-z_][A-Za-z0-9_.]*)?score(?![A-Za-z0-9_])/i;
// «≥ 80 - отлично», «60-80 - хорошо», «40-60 - приемлемо» — шкала словами в тексте
const SCALE_TEXT = /(?:≥|>=)\s*\d{2}\s*[-–—]?\s*(?:отлич|хорош|приемлем)|\d{2}\s*[-–—]\s*\d{2}\s*[-–—]?\s*(?:отлич|хорош|приемлем)/i;

/** Строка-комментарий: литерал в документации — не поведение. */
function isComment(t) {
  return t.startsWith('//') || t.startsWith('*') || t.startsWith('/*') || t.startsWith('<!--');
}

describe('паритет с питоновским каноном порогов', () => {
  it('MQS_TIERS совпадает с _MQS_TIERS в utils/diagnostics.py', () => {
    expect(
      fs.existsSync(PY_CANON),
      `Канон порогов не найден: ${PY_CANON}. Путь сместился — почини гард, не отключай его.`,
    ).toBe(true);
    const py = fs.readFileSync(PY_CANON, 'utf8');
    const block = py.match(/_MQS_TIERS\s*=\s*\(([\s\S]*?)\n\)/);
    expect(block, 'Не найден блок _MQS_TIERS — изменилась форма записи канона').not.toBeNull();

    const rows = [...block[1].matchAll(/\(\s*(\d+)\s*,\s*'([a-z_]+)'\s*,\s*'([^']+)'\s*,\s*'(#[0-9a-fA-F]{6})'\s*\)/g)]
      .map((m) => ({ min: Number(m[1]), tier: m[2], label: m[3], color: m[4] }));

    // защита от тихого нуля: пустой разбор — это КРАСНЫЙ, а не «всё сходится»
    expect(rows.length, 'Из канона не разобрано ни одной ступени — гард смотрит не туда').toBeGreaterThan(0);

    expect(rows).toEqual(MQS_TIERS.map((t) => ({ min: t.min, tier: t.tier, label: t.label, color: t.color })));
  });
});

describe('структурный гард: интерфейс не держит своей шкалы MQS', () => {
  it('ни один файл src/ не сравнивает MQS с числом и не пишет шкалу руками', () => {
    /** @type {string[]} */
    const offenders = [];
    let scanned = 0;
    for (const f of walk(SRC_DIR)) {
      if (ALLOWED.has(path.basename(f))) continue;
      if (/__tests__|[.](test|spec)[.]/.test(f)) continue;
      scanned += 1;
      const lines = fs.readFileSync(f, 'utf8').split('\n');
      lines.forEach((ln, i) => {
        const t = ln.trim();
        if (isComment(t)) return;
        if (LEGITIMISED.some((lit) => ln.includes(lit))) return;
        // Текстовая шкала засчитывается только там, где речь именно о MQS:
        // у запаса данных (Ratio) своя шкала «≥10 отлично», к качеству модели
        // отношения не имеющая. Без этого условия гард ловил бы чужую метрику.
        const scaleHit = SCALE_TEXT.test(ln) && /\bmqs\b|Model Quality/i.test(ln);
        if (
          CMP_AFTER.test(ln)
          || CMP_BEFORE.test(ln)
          || THRESHOLD_ARGS.test(ln)
          || OLD_SCALE_SCORE_AFTER.test(ln)
          || OLD_SCALE_SCORE_BEFORE.test(ln)
          || scaleHit
        ) {
          offenders.push(`${path.relative(SRC_DIR, f)}:${i + 1}: ${t.slice(0, 110)}`);
        }
      });
    }
    // защита от тихого нуля: пустой список входов — КРАСНЫЙ, а не «чисто»
    expect(scanned, 'Гард не просмотрел ни одного файла — путь до src/ сместился').toBeGreaterThan(50);
    expect(
      offenders,
      `Своя лестница порогов MQS. Ветвись по mqsTierInfo(score).tier / mqsTone(score), `
        + `текст шкалы бери из mqsScaleText() (lib/mqs-tiers.js):\n${offenders.join('\n')}`,
    ).toEqual([]);
  });
});

describe('mqsTierInfo', () => {
  it('нет балла — нет уровня (null), а не «Ненадёжное»', () => {
    expect(mqsTierInfo(null)).toBeNull();
    expect(mqsTierInfo(undefined)).toBeNull();
    expect(mqsTierInfo(NaN)).toBeNull();
  });
  it('настоящий ноль — валидное измерение, уровень «Ненадёжное»', () => {
    expect(mqsTierInfo(0)?.tier).toBe('poor');
  });
  it('границы включительно, по канону 85/70/55/40', () => {
    expect(mqsTierInfo(85)?.tier).toBe('excellent');
    expect(mqsTierInfo(84.9)?.tier).toBe('good');
    expect(mqsTierInfo(70)?.tier).toBe('good');
    expect(mqsTierInfo(69.9)?.tier).toBe('acceptable');
    expect(mqsTierInfo(55)?.tier).toBe('acceptable');
    expect(mqsTierInfo(54.9)?.tier).toBe('weak');
    expect(mqsTierInfo(40)?.tier).toBe('weak');
    expect(mqsTierInfo(39.9)?.tier).toBe('poor');
  });
  it('случай инцидента: 70 — «Хорошее», не «Приемлемое»', () => {
    expect(mqsTierInfo(70)?.label).toBe('Хорошее');
  });
  it('случай инцидента: 82 — «Хорошее», не «Отличное»', () => {
    expect(mqsTierInfo(82)?.label).toBe('Хорошее');
  });
});

describe('mqsTone и mqsIsDependable', () => {
  it('тон по уровню, а не по числу', () => {
    expect(mqsTone(90)).toBe('good');
    expect(mqsTone(70)).toBe('good');
    expect(mqsTone(60)).toBe('warn');
    expect(mqsTone(50)).toBe('bad');
    expect(mqsTone(null)).toBeNull();
  });
  it('недоказанное не считается доказанным', () => {
    expect(mqsIsDependable(null)).toBe(false);
    expect(mqsIsDependable(69.9)).toBe(false);
    expect(mqsIsDependable(70)).toBe(true);
  });
});

describe('mqsScaleText', () => {
  it('собирается из порогов и покрывает все пять уровней', () => {
    const s = mqsScaleText();
    for (const t of MQS_TIERS) expect(s).toContain(t.label);
    // Целочисленные диапазоны (2026-07-27, единая форма с Rust-зеркалом
    // mqs_tiers.rs::mqs_scale_text) - без ≤/≥/<, верхняя граница каждого
    // диапазона на 1 меньше нижней границы следующего уровня.
    expect(s).toContain('85–100');
    expect(s).toContain('70–84');
    expect(s).toContain('55–69');
    expect(s).toContain('40–54');
    expect(s).toContain('0–39');
    expect(s).not.toMatch(/[≤≥<]/);
  });
  it('короткое тире в клиентском тексте', () => {
    expect(mqsScaleText()).not.toMatch(/—/);
  });
});
