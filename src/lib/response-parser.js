/**
 * Parse markdown AI response into structured sections by ## headings.
 * Memoized to avoid re-parsing on every render.
 *
 * @module response-parser
 */

/** @type {Map<string, ResponseSection[]>} */
const cache = new Map();
const MAX_CACHE = 50;

/**
 * Fast string hash (djb2) - used as cache key instead of full markdown text.
 * @param {string} str
 * @returns {string}
 */
function hashKey(str) {
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0;
  return h.toString(36) + '_' + str.length;
}

/**
 * @typedef {Object} ResponseSection
 * @property {string} title - Section heading (empty for preamble before first heading)
 * @property {string} content - Section body markdown
 * @property {number} level - Heading level (1-3), 0 for preamble
 */

/**
 * Parse markdown into sections by headings.
 * Returns single-element array with empty title if no headings found.
 *
 * @param {string} markdown
 * @returns {ResponseSection[]}
 */
export function parseResponseSections(markdown) {
  if (!markdown || typeof markdown !== 'string') {
    return [{ title: '', content: '', level: 0 }];
  }

  const key = hashKey(markdown);

  // Check cache (LRU: move to end on access)
  if (cache.has(key)) {
    const val = /** @type {ResponseSection[]} */ (cache.get(key));
    cache.delete(key);
    cache.set(key, val);
    return val;
  }

  const lines = markdown.split('\n');
  /** @type {ResponseSection[]} */
  const sections = [];
  /** @type {ResponseSection} */
  let current = { title: '', content: '', level: 0 };

  for (const line of lines) {
    const match = line.match(/^(#{1,3})\s+(.+)/);
    if (match) {
      // Save previous section if it has content
      if (current.content.trim() || current.title) {
        sections.push({ ...current, content: current.content.trimEnd() });
      }
      current = {
        title: match[2].trim(),
        content: '',
        level: match[1].length,
      };
    } else {
      current.content += line + '\n';
    }
  }

  // Push last section
  if (current.content.trim() || current.title) {
    sections.push({ ...current, content: current.content.trimEnd() });
  }

  // Evict LRU (first entry in Map = oldest accessed)
  if (cache.size >= MAX_CACHE) {
    const first = cache.keys().next().value;
    if (first !== undefined) cache.delete(first);
  }
  cache.set(key, sections);

  return sections;
}

/**
 * Check if sections warrant structured rendering.
 * At least 2 sections with at least 1 titled section.
 *
 * @param {ResponseSection[]} sections
 * @returns {boolean}
 */
export function shouldRenderStructured(sections) {
  return sections.length >= 2 && sections.some(s => s.title.length > 0);
}

/** @type {RegExp} */
const SLIDE_RE = /^(?:(?:Слайд|Slide)\s*№?\s*\d+|\d+\.\s)/i;

/** @type {RegExp} */
const SYNTH_RE = /^(EXECUTIVE SUMMARY|ОБЩИЙ ВЫВОД|БЛОК:|МОСТЫ|РЕКОМЕНДАЦИИ)/i;

/**
 * Check if sections represent a PPTX slide deck (5+ slide-titled sections).
 * @param {ResponseSection[]} sections
 * @returns {boolean}
 */
export function isSlideDeckResponse(sections) {
  return sections.filter(s => SLIDE_RE.test(s.title)).length >= 5;
}

/**
 * Check if response has enough structured sections (## headings) for content panel.
 * Works for any command output: aurora-index, executive-summary, bridges, etc.
 * @param {ResponseSection[]} sections
 * @returns {boolean}
 */
export function isStructuredResponse(sections) {
  // At least 3 titled sections (excludes preamble with empty title)
  return sections.filter(s => s.title && s.title.trim()).length >= 3;
}

/**
 * Split sections into preamble (before first slide), slides, and synthesis (after last slide).
 * @param {ResponseSection[]} sections
 * @returns {{ preamble: ResponseSection[], slides: ResponseSection[], synthesis: ResponseSection[] }}
 */
export function splitSlideSections(sections) {
  /** @type {ResponseSection[]} */
  const preamble = [];
  /** @type {ResponseSection[]} */
  const slides = [];
  /** @type {ResponseSection[]} */
  const synthesis = [];

  let phase = 'preamble'; // preamble → slides → synthesis

  for (const sec of sections) {
    if (SLIDE_RE.test(sec.title)) {
      phase = 'slides';
      slides.push(sec);
    } else if (phase === 'slides' && SYNTH_RE.test(sec.title)) {
      phase = 'synthesis';
      synthesis.push(sec);
    } else if (phase === 'synthesis') {
      synthesis.push(sec);
    } else {
      preamble.push(sec);
    }
  }

  return { preamble, slides, synthesis };
}

/**
 * Extract completion statistics from parsed sections for Completion Summary Card.
 * @param {ResponseSection[]} sections
 * @returns {{ slides: number, recommendations: number, anomalies: number, bridges: number }}
 */
export function extractCompletionStats(sections) {
  const slides = sections.filter(s => SLIDE_RE.test(s.title)).length;
  let recommendations = 0;
  let anomalies = 0;
  let bridges = 0;

  for (const s of sections) {
    if (/РЕКОМЕНДАЦИИ/i.test(s.title)) {
      recommendations = (s.content.match(/^\d+\./gm) || []).length;
    }
    if (/МОСТЫ/i.test(s.title)) {
      bridges = (s.content.match(/^\d+\./gm) || []).length;
    }
    const anomalyMatches = s.content.match(/аномал|отклонен|выброс|резк/gi);
    if (anomalyMatches) anomalies += anomalyMatches.length;
  }

  return { slides, recommendations, anomalies: Math.min(anomalies, 10), bridges };
}

/**
 * C5: Group slides into named blocks based on synthesis section headings.
 * Synthesis sections matching "БЛОК: Name - слайды X-Y" define groups.
 * Slides not matching any block are placed in "Прочее" (if other groups exist).
 * Fallback: single group with empty name containing all slides (flat list).
 * @param {ResponseSection[]} slides
 * @param {ResponseSection[]} synthesis
 * @returns {Array<{ name: string, slides: ResponseSection[] }>}
 */
export function groupSlidesByBlocks(slides, synthesis) {
  const blockRe = /БЛОК:\s*(.+?)(?:\s*[-–\-]\s*слайды?\s*(\d+)\s*[-–-]\s*(\d+))?/i;
  /** @type {Array<{ name: string, slides: ResponseSection[] }>} */
  const groups = [];
  for (const sec of synthesis) {
    const m = sec.title.match(blockRe);
    if (m) {
      const name = m[1].trim();
      const from = m[2] ? +m[2] : 0;
      const to = m[3] ? +m[3] : 999;
      const blockSlides = slides.filter(s => {
        const num = cleanSlideTitle(s.title).num;
        return num >= from && num <= to;
      });
      if (blockSlides.length > 0) groups.push({ name, slides: blockSlides });
    }
  }
  const grouped = new Set(groups.flatMap(g => g.slides));
  const ungrouped = slides.filter(s => !grouped.has(s));
  if (ungrouped.length > 0 && groups.length > 0) groups.push({ name: 'Прочее', slides: ungrouped });
  return groups.length > 0 ? groups : [{ name: '', slides }];
}

/**
 * Extract clean slide number and name from a "Слайд N: Title" heading.
 * @param {string} title
 * @returns {{ num: number, name: string }}
 */
export function cleanSlideTitle(title) {
  const m = title.match(/^(?:Слайд|Slide)\s*№?\s*(\d+)\s*[:.-–\-]?\s*(.*)/i)
         || title.match(/^(\d+)\.\s+(.*)/);
  return m ? { num: +m[1], name: m[2].trim() || `Слайд ${m[1]}` } : { num: 0, name: title };
}
