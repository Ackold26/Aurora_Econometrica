/**
 * Classifier patterns SSOT client — Phase 1.1.
 *
 * Fetches канонические patterns из backend `/api/static/classifier-patterns-v1.json`
 * через Tauri command `econ_classifier_patterns`. Caches result в localStorage
 * с TTL. Falls back к embedded patterns (last-known good copy) если backend
 * unavailable.
 *
 * Replaces inline MONETARY_RE / PHYSICAL_RE regex в ValidateStepV13.svelte и
 * unitLabel() в AppliedModeSummary.svelte. Eliminates regex duplication между
 * Python (utils/column_detection.py) и frontend.
 *
 * Architecture: cache-with-fallback (per audit P-05) — no SPOF, works offline
 * после initial fetch.
 *
 * @module classifier-patterns
 */
import { invoke } from '@tauri-apps/api/core';

const CACHE_KEY = 'aurora-classifier-patterns-v1';
const CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour

/**
 * Embedded fallback — last-known good patterns. Synced manually при major
 * version bumps. Used когда backend endpoint unreachable (sidecar crash,
 * network error) — prevents UI hard fail.
 *
 * MUST match shape of backend export_patterns_as_json() output.
 *
 * @type {ClassifierPatternsPayload}
 */
const EMBEDDED_FALLBACK = {
  version: 'v1',
  embedded_fallback: true,
  kinds: {
    // Minimal set sufficient для AppliedModeSummary / ValidateStepV13.
    // Full patterns canonical в backend; embedded covers most common cases.
    monetary: [
      '(?:^|(?<=[_\\s\\-]))spend(?:s|ing)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))budget(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))cost(?:s)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))бюджет(?:ы|а|ов)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))расход(?:ы|ов|а)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))rub(?=[_\\s\\-]|$)',
      '₽',
    ],
    physical: [
      '(?:^|(?<=[_\\s\\-]))impression(?:s)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))click(?:s)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))visit(?:s)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))view(?:s)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))grp(?:s)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))trp(?:s)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))показ(?:ы|ов|а)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))клик(?:ов|и)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))визит(?:ы|ов|а)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))просмотр(?:ы|ов|а)?(?=[_\\s\\-]|$)',
    ],
  },
  priority: ['monetary', 'physical'],
  unit_label_rules: [
    { pattern: '(?<![a-zA-Zа-яА-Я])(trp|трп)', label: '₽ за 1 TRP' },
    { pattern: '(?<![a-zA-Zа-яА-Я])(grp|грп)', label: '₽ за 1 GRP' },
    { pattern: '(impression|показ)', label: '₽ за 1000 показов (CPM)' },
    { pattern: '(click|клик)', label: '₽ за 1 клик (CPC)' },
    { pattern: '(visit|визит)', label: '₽ за 1 визит' },
    { pattern: '(view|просмотр)', label: '₽ за 1 просмотр' },
    { pattern: '(reach|охват)', label: '₽ за 1000 охвата' },
    { pattern: '(прочтен)', label: '₽ за 1 прочтение' },
  ],
};

/**
 * @typedef {{
 *   version: string,
 *   embedded_fallback?: boolean,
 *   kinds: Record<string, string[]>,
 *   priority: string[],
 *   unit_label_rules: Array<{pattern: string, label: string}>,
 *   generated_at?: string,
 *   sidecar_session?: string,
 * }} ClassifierPatternsPayload
 */

/** @type {ClassifierPatternsPayload | null} */
let cachedPayload = null;
/** @type {Map<string, RegExp[]>} Compiled regex кеш per kind. */
const compiledKindCache = new Map();
/** @type {Array<{rx: RegExp, label: string}> | null} */
let compiledUnitLabelRules = null;

/**
 * Try load from localStorage. Returns null если absent / expired / parse error.
 * @returns {ClassifierPatternsPayload | null}
 */
function readFromLocalStorage() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const { _cached_at, _payload } = parsed;
    if (typeof _cached_at !== 'number' || !_payload) return null;
    if (Date.now() - _cached_at > CACHE_TTL_MS) return null;
    return /** @type {ClassifierPatternsPayload} */ (_payload);
  } catch {
    return null;
  }
}

/**
 * Persist payload + timestamp.
 * @param {ClassifierPatternsPayload} payload
 */
function writeToLocalStorage(payload) {
  try {
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ _cached_at: Date.now(), _payload: payload }),
    );
  } catch {
    /* localStorage quota exceeded or unavailable — best-effort */
  }
}

/**
 * Compile + cache RegExp objects from string patterns.
 * @param {ClassifierPatternsPayload} payload
 */
function rebuildCompiledCache(payload) {
  compiledKindCache.clear();
  for (const [kind, patterns] of Object.entries(payload.kinds)) {
    const compiled = patterns
      .map((p) => {
        try {
          return new RegExp(p, 'i');
        } catch {
          return null;
        }
      })
      .filter(/** @type {(rx: RegExp | null) => rx is RegExp} */ (rx) => rx !== null);
    compiledKindCache.set(kind, compiled);
  }
  compiledUnitLabelRules = payload.unit_label_rules
    .map((rule) => {
      try {
        return { rx: new RegExp(rule.pattern, 'i'), label: rule.label };
      } catch {
        return null;
      }
    })
    .filter(
      /** @type {(r: {rx: RegExp, label: string} | null) => r is {rx: RegExp, label: string}} */
      (r) => r !== null,
    );
}

/**
 * Initialize patterns: try cache → backend → embedded fallback.
 *
 * Idempotent (safe to call multiple times). Returns currently active payload.
 *
 * @returns {Promise<ClassifierPatternsPayload>}
 */
export async function ensurePatternsLoaded() {
  if (cachedPayload) return cachedPayload;

  // 1. Try localStorage
  const cached = readFromLocalStorage();
  if (cached) {
    cachedPayload = cached;
    rebuildCompiledCache(cached);
    // Refresh from backend в background (don't await — best-effort)
    refreshFromBackend().catch(() => {});
    return cached;
  }

  // 2. Try backend
  try {
    const fresh = /** @type {ClassifierPatternsPayload} */ (
      await invoke('econ_classifier_patterns')
    );
    if (fresh && fresh.version && fresh.kinds) {
      cachedPayload = fresh;
      writeToLocalStorage(fresh);
      rebuildCompiledCache(fresh);
      return fresh;
    }
  } catch {
    /* fall through to embedded */
  }

  // 3. Embedded fallback
  cachedPayload = EMBEDDED_FALLBACK;
  rebuildCompiledCache(EMBEDDED_FALLBACK);
  return EMBEDDED_FALLBACK;
}

/** Background refresh (no-throw). */
async function refreshFromBackend() {
  try {
    const fresh = /** @type {ClassifierPatternsPayload} */ (
      await invoke('econ_classifier_patterns')
    );
    if (fresh && fresh.version && fresh.kinds) {
      cachedPayload = fresh;
      writeToLocalStorage(fresh);
      rebuildCompiledCache(fresh);
    }
  } catch {
    /* keep cached */
  }
}

/**
 * Classify column name. Returns 'monetary' | 'physical' для media columns.
 * For Phase 1.1 scope — only those два kinds; rich classification via
 * backend `econ_validate` returns full role tag.
 *
 * Defaults к 'monetary' если nothing matches (matches audit P-06 decision —
 * conservative default безопасен для ROI mode).
 *
 * @param {string} name
 * @returns {'monetary' | 'physical'}
 */
export function detectChannelUnitType(name) {
  if (!name || typeof name !== 'string') return 'monetary';
  const payload = cachedPayload ?? EMBEDDED_FALLBACK;
  const monetaryRxs = compiledKindCache.get('monetary') ?? [];
  const physicalRxs = compiledKindCache.get('physical') ?? [];
  // Lazy-compile если ensurePatternsLoaded не вызвана
  if (!compiledKindCache.size) {
    rebuildCompiledCache(payload);
  }
  const isMonetary = (compiledKindCache.get('monetary') ?? monetaryRxs).some((rx) =>
    rx.test(name),
  );
  const isPhysical = (compiledKindCache.get('physical') ?? physicalRxs).some((rx) =>
    rx.test(name),
  );
  if (isPhysical && !isMonetary) return 'physical';
  return 'monetary';
}

/**
 * Human-readable unit label для physical channel (Manager ROI UI).
 *
 * Examples:
 *   unitLabelFor('TRPs бренд (W 25-54)') → '₽ за 1 TRP'
 *   unitLabelFor('Banners Показы') → '₽ за 1000 показов (CPM)'
 *
 * @param {string} name
 * @returns {string}
 */
export function unitLabelFor(name) {
  if (!name || typeof name !== 'string') return '₽ за 1 единицу';
  if (!compiledUnitLabelRules) {
    rebuildCompiledCache(cachedPayload ?? EMBEDDED_FALLBACK);
  }
  for (const rule of compiledUnitLabelRules ?? []) {
    if (rule.rx.test(name)) return rule.label;
  }
  return '₽ за 1 единицу';
}

/**
 * Get current loaded payload (для tests + diagnostics).
 * @returns {ClassifierPatternsPayload | null}
 */
export function _getCachedPayload() {
  return cachedPayload;
}

/**
 * Reset cached state — для tests only.
 */
export function _resetCache() {
  cachedPayload = null;
  compiledKindCache.clear();
  compiledUnitLabelRules = null;
  try {
    localStorage.removeItem(CACHE_KEY);
  } catch {
    /* ignore */
  }
}
