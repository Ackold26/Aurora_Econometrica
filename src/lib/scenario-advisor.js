/**
 * Советчик «сценарии словами» (Фаза 3 Tier 2): разбор запроса на естественном
 * языке в параметры сценария/оптимизации, применение к текущим расходам и
 * человекочитаемое подтверждение (human-in-the-loop).
 *
 * Поток: NL-запрос → Claude разбирает в config (buildScenarioParsePrompt +
 * extractScenarioConfig) → пользователь подтверждает (describeScenario) →
 * applyChangesToMediaPlan → econ_scenario (детерминированный движок) → Аврора
 * интерпретирует числовой результат.
 *
 * INV-50: числа считает движок (predict_scenario), LLM лишь разбирает НАМЕРЕНИЕ
 * (какой канал, на сколько процентов) и объясняет результат. Проценты изменения
 * исходят от пользователя, не выдумываются.
 *
 * @module scenario-advisor
 */

/**
 * @typedef {Object} ChannelChange
 * @property {string} channel — точное имя канала
 * @property {number} delta_pct — изменение в % (+ увеличить, − уменьшить)
 */

/**
 * @typedef {Object} ScenarioConfig
 * @property {'scenario'|'optimize'|'unclear'} kind
 * @property {ChannelChange[]} changes — для kind='scenario'
 * @property {string} goal — краткое описание намерения
 */

/**
 * Промпт для Claude: разобрать NL-запрос в JSON-config. Возвращается строкой —
 * шлётся через тот же econ_ask_insight мост.
 *
 * @param {string} userText
 * @param {string[]} channelNames — точные имена каналов модели
 * @returns {string}
 */
export function buildScenarioParsePrompt(userText, channelNames) {
  return [
    'Разбери запрос пользователя в JSON для сценарного расчёта медиабюджета (MMM).',
    `Доступные каналы (используй ТОЧНЫЕ имена из списка): ${JSON.stringify(channelNames)}.`,
    'Верни ТОЛЬКО JSON, без пояснений и без markdown-обёртки:',
    '{"kind":"scenario"|"optimize"|"unclear","changes":[{"channel":"<точное имя>","delta_pct":<число: + увеличить, - уменьшить>}],"goal":"<краткое описание на русском>"}',
    '- "scenario": пользователь меняет расходы каналов на проценты («урежь ТВ на 20%», «удвой диджитал»).',
    '- "optimize": пользователь просит найти оптимальное распределение бюджета («оптимизируй», «как лучше разложить бюджет»).',
    '- "unclear": запрос не про сценарий и не про оптимизацию.',
    'Правила: канал называй ТОЧНЫМ именем из списка; если назван приблизительно – выбери ближайший по смыслу.',
    '«Удвоить» = +100%, «вполовину»/«вдвое меньше» = -50%, «на треть меньше» = -33.',
    '',
    `Запрос пользователя: ${userText}`,
  ].join('\n');
}

/**
 * Извлечь и нормализовать config из ответа Claude (ответ может содержать текст
 * вокруг JSON — берём первый сбалансированный объект).
 *
 * @param {string | null | undefined} claudeText
 * @returns {ScenarioConfig | null}
 */
export function extractScenarioConfig(claudeText) {
  if (typeof claudeText !== 'string') return null;
  const match = claudeText.match(/\{[\s\S]*\}/);
  if (!match) return null;
  let obj;
  try {
    obj = JSON.parse(match[0]);
  } catch {
    return null;
  }
  if (!obj || typeof obj !== 'object') return null;

  /** @type {'scenario'|'optimize'|'unclear'} */
  const kind = obj.kind === 'optimize' ? 'optimize' : obj.kind === 'unclear' ? 'unclear' : 'scenario';

  /** @type {ChannelChange[]} */
  const changes = Array.isArray(obj.changes)
    ? obj.changes
        .filter(
          /** @param {any} c */ (c) =>
            c && typeof c.channel === 'string' && Number.isFinite(Number(c.delta_pct)),
        )
        .map(/** @param {any} c */ (c) => ({ channel: c.channel, delta_pct: Number(c.delta_pct) }))
    : [];

  // scenario без изменений → unclear (нечего считать).
  const effectiveKind = kind === 'scenario' && changes.length === 0 ? 'unclear' : kind;

  return {
    kind: effectiveKind,
    changes,
    goal: typeof obj.goal === 'string' ? obj.goal : '',
  };
}

/**
 * Применить процентные изменения к текущим расходам → media_plan для
 * econ_scenario (формат {channel: [budget]} — один период массивом).
 * Каналы без изменений переносятся как есть. Неизвестные каналы в changes
 * игнорируются (защита от мисматча имени).
 *
 * @param {ChannelChange[]} changes
 * @param {Record<string, number>} currentBudgets — текущий расход по каналам (native)
 * @returns {Record<string, number[]>}
 */
export function applyChangesToMediaPlan(changes, currentBudgets) {
  /** @type {Record<string, number[]>} */
  const plan = {};
  for (const [ch, val] of Object.entries(currentBudgets)) {
    const num = Number(val);
    plan[ch] = [Number.isFinite(num) ? num : 0];
  }
  for (const c of changes) {
    if (!(c.channel in plan)) continue; // защита от неизвестного имени
    const base = Number(currentBudgets[c.channel]) || 0;
    const factor = 1 + c.delta_pct / 100;
    plan[c.channel] = [Math.max(0, base * factor)];
  }
  return plan;
}

/**
 * Человекочитаемое подтверждение разобранного намерения (human-in-the-loop):
 * показывается пользователю ДО запуска расчёта.
 *
 * @param {ScenarioConfig} config
 * @returns {string | null} null, если подтверждать нечего (unclear)
 */
export function describeScenario(config) {
  if (!config || config.kind === 'unclear') return null;
  if (config.kind === 'optimize') {
    return 'Найти оптимальное распределение бюджета при текущем общем объёме. Запустить оптимизацию?';
  }
  const parts = config.changes.map((c) => {
    const dir = c.delta_pct >= 0 ? 'увеличить' : 'уменьшить';
    return `${c.channel}: ${dir} на ${Math.abs(c.delta_pct)}%`;
  });
  return `Сценарий – ${parts.join('; ')}; остальные каналы без изменений. Запустить расчёт?`;
}

/** Порог |r| для предупреждения о коллинеарности при перебросе бюджета.
 * Консервативнее UI-порога мультиколлинеарности (0.8): McElreath (гл. 5–6) —
 * коллинеарность мешает разделить вклад уже при умеренной корреляции, а для
 * совета «переложить бюджет с A на B» цена ошибки разделения высока. */
const COLLINEAR_THRESHOLD = 0.65;

/**
 * @typedef {Object} CollinearPair
 * @property {string} a
 * @property {string} b
 * @property {number} r — корреляция (со знаком)
 */

/**
 * Среди задействованных в сценарии каналов найти пары с высокой взаимной
 * корреляцией. Вклад таких каналов модель не может надёжно разделить, поэтому
 * прогноз переброса бюджета между ними ненадёжен (McElreath: коллинеарность).
 *
 * Имена сверяются с метками матрицы напрямую; канал без метки молча
 * пропускается (защита от мисматча имени, как в applyChangesToMediaPlan).
 *
 * @param {ChannelChange[]} changes
 * @param {{ labels: string[], matrix: number[][] } | null | undefined} correlationMatrix
 * @param {number} [threshold]
 * @returns {CollinearPair[]}
 */
export function findCollinearPairs(changes, correlationMatrix, threshold = COLLINEAR_THRESHOLD) {
  if (!correlationMatrix || !Array.isArray(correlationMatrix.labels) || !Array.isArray(correlationMatrix.matrix)) {
    return [];
  }
  const { labels, matrix } = correlationMatrix;
  /** @type {Map<string, number>} */
  const idx = new Map(labels.map((l, i) => [l, i]));
  const chans = [...new Set((changes || []).map((c) => c.channel))].filter((c) => idx.has(c));
  /** @type {CollinearPair[]} */
  const pairs = [];
  for (let i = 0; i < chans.length; i++) {
    for (let j = i + 1; j < chans.length; j++) {
      const ri = /** @type {number} */ (idx.get(chans[i]));
      const rj = /** @type {number} */ (idx.get(chans[j]));
      const r = Number(matrix[ri]?.[rj]);
      if (Number.isFinite(r) && Math.abs(r) >= threshold) {
        pairs.push({ a: chans[i], b: chans[j], r });
      }
    }
  }
  return pairs;
}

/**
 * Текст-оговорка о коллинеарности для промпта интерпретации сценария (или ''
 * если коллинеарных пар нет). Подаётся Авроре как методологический контекст —
 * число r здесь справочное (корреляция данных), не результат модели.
 *
 * @param {CollinearPair[] | null | undefined} pairs
 * @returns {string}
 */
export function collinearityCaveat(pairs) {
  if (!Array.isArray(pairs) || pairs.length === 0) return '';
  const list = pairs.map((p) => `«${p.a}» и «${p.b}» (r≈${p.r.toFixed(2)})`).join('; ');
  return (
    `Коллинеарность каналов сценария: ${list}. Их рекламная активность шла почти ` +
    `синхронно, поэтому модель не может надёжно разделить вклад этих каналов, и ` +
    `прогноз переброса бюджета между ними ненадёжен. Обязательно предупреди об этом ` +
    `и трактуй такой результат осторожно.`
  );
}
