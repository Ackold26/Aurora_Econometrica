/**
 * Industry CPP defaults — Phase 4.1 (R3 first step).
 *
 * Static lookup table для smart unit_cost suggestions per industry × channel
 * unit type. Customer brand-manager opens project → system suggests typical
 * cost («1 TRP ≈ 800k ₽ для pharma OTC») → 95% case covered; LLM (Phase 4.2)
 * remains для edge cases.
 *
 * Architecture rationale (audit P-08 + R3):
 * - Static = privacy-safe (no data leaves customer machine)
 * - Static = no COGS (no API calls)
 * - Static = customer-extensible (override values via project metadata)
 * - Bounded ICP (pharma / FMCG / SaaS / Finance / Retail в RU/CIS) sufficient
 * - Phi-3.5 deferred к v2.3.0 — table validates demand первый
 *
 * Data sources:
 * - Pharma OTC rates: Mediascope reports 2024-2025 + agency benchmarks
 *   (sanitized — no specific customer values)
 * - FMCG: industry averages from public reports
 * - Retail/SaaS/Finance: typical RU market rates 2024
 *
 * NB: All ranges represent **typical** 2024 RU market. Customer should
 * verify against agency rate cards. Values may shift 10-30% annually
 * (inflation captured separately via $unitCostInflation store).
 *
 * @module industry-cpp-defaults
 */

/**
 * @typedef {'pharma_otc' | 'pharma_rx' | 'fmcg' | 'retail' | 'saas' | 'finance' | 'b2b' | 'unknown'} IndustryCode
 *
 * @typedef {'trp' | 'grp' | 'cpm' | 'cpc' | 'cpv' | 'cpa'} UnitType
 *
 * @typedef {{
 *   typical: number,     // typical rate в ₽
 *   min: number,         // lower bound для sanity check
 *   max: number,         // upper bound для sanity check
 *   confidence: 'high' | 'medium' | 'low',
 *   year: number,        // data year (для inflation context)
 *   source?: string,     // optional human-readable attribution
 * }} CppRange
 */

/**
 * Industry × UnitType → CppRange. Values в ₽ (RUB), Russian market 2024.
 * Empty entry = no documented benchmark (LLM fallback in v2.3.0).
 *
 * @type {Record<IndustryCode, Partial<Record<UnitType, CppRange>>>}
 */
export const INDUSTRY_CPP_TABLE = Object.freeze({
  pharma_otc: {
    trp: { typical: 800_000, min: 400_000, max: 1_500_000, confidence: 'high', year: 2024, source: 'Mediascope OTC pharma benchmark' },
    grp: { typical: 600_000, min: 300_000, max: 1_200_000, confidence: 'high', year: 2024 },
    cpm: { typical: 350, min: 150, max: 800, confidence: 'high', year: 2024, source: 'Digital programmatic RU avg' },
    cpc: { typical: 45, min: 20, max: 120, confidence: 'medium', year: 2024 },
    cpv: { typical: 6, min: 2, max: 18, confidence: 'medium', year: 2024 },
  },
  pharma_rx: {
    // Rx pharma — limited TV (ФЗ-38 restrictions). Mostly trade marketing,
    // sales rep visits — рідко direct media buy. Conservative ranges.
    cpm: { typical: 400, min: 200, max: 900, confidence: 'medium', year: 2024 },
    cpc: { typical: 60, min: 30, max: 150, confidence: 'medium', year: 2024 },
    cpa: { typical: 2_500, min: 800, max: 8_000, confidence: 'low', year: 2024 },
  },
  fmcg: {
    trp: { typical: 500_000, min: 250_000, max: 950_000, confidence: 'high', year: 2024, source: 'Mediascope FMCG 2024 avg' },
    grp: { typical: 380_000, min: 180_000, max: 700_000, confidence: 'high', year: 2024 },
    cpm: { typical: 280, min: 120, max: 650, confidence: 'high', year: 2024 },
    cpc: { typical: 35, min: 15, max: 90, confidence: 'medium', year: 2024 },
    cpv: { typical: 5, min: 1.5, max: 15, confidence: 'medium', year: 2024 },
  },
  retail: {
    trp: { typical: 550_000, min: 280_000, max: 1_000_000, confidence: 'medium', year: 2024 },
    cpm: { typical: 320, min: 150, max: 750, confidence: 'high', year: 2024 },
    cpc: { typical: 50, min: 20, max: 130, confidence: 'high', year: 2024, source: 'Yandex.Direct retail RU avg' },
    cpa: { typical: 1_200, min: 400, max: 4_000, confidence: 'medium', year: 2024 },
  },
  saas: {
    // No traditional TV — focus digital + content.
    cpm: { typical: 450, min: 200, max: 1_100, confidence: 'high', year: 2024, source: 'B2B SaaS RU programmatic' },
    cpc: { typical: 85, min: 30, max: 220, confidence: 'high', year: 2024 },
    cpa: { typical: 3_500, min: 1_200, max: 12_000, confidence: 'medium', year: 2024 },
  },
  finance: {
    trp: { typical: 700_000, min: 400_000, max: 1_300_000, confidence: 'medium', year: 2024 },
    cpm: { typical: 420, min: 200, max: 1_000, confidence: 'high', year: 2024 },
    cpc: { typical: 95, min: 40, max: 250, confidence: 'high', year: 2024, source: 'Finance RU paid search avg' },
    cpa: { typical: 4_500, min: 1_500, max: 15_000, confidence: 'medium', year: 2024 },
  },
  b2b: {
    cpm: { typical: 380, min: 150, max: 900, confidence: 'medium', year: 2024 },
    cpc: { typical: 110, min: 40, max: 280, confidence: 'medium', year: 2024 },
    cpa: { typical: 6_000, min: 2_000, max: 25_000, confidence: 'low', year: 2024 },
  },
  unknown: {
    // Fallback — broadest ranges, low confidence.
    trp: { typical: 500_000, min: 100_000, max: 2_000_000, confidence: 'low', year: 2024 },
    cpm: { typical: 350, min: 100, max: 1_200, confidence: 'low', year: 2024 },
    cpc: { typical: 60, min: 15, max: 300, confidence: 'low', year: 2024 },
  },
});


/**
 * Channel name → UnitType heuristic.
 *
 * @param {string} channelName
 * @returns {UnitType | null}
 */
export function detectUnitType(channelName) {
  if (!channelName || typeof channelName !== 'string') return null;
  const lower = channelName.toLowerCase();
  if (/(?<![a-zа-я])(trp|трп)/i.test(lower)) return 'trp';
  if (/(?<![a-zа-я])(grp|грп)/i.test(lower)) return 'grp';
  if (/(impression|показ|cpm)/i.test(lower)) return 'cpm';
  if (/(click|клик|cpc)/i.test(lower)) return 'cpc';
  if (/(view|просмотр|cpv)/i.test(lower)) return 'cpv';
  if (/(conversion|conversion|cpa|action)/i.test(lower)) return 'cpa';
  return null;
}


/**
 * Suggest typical unit_cost for given channel + industry context.
 *
 * @param {string} channelName
 * @param {IndustryCode} [industry='unknown']
 * @returns {{ value: number, range: { min: number, max: number }, confidence: 'high'|'medium'|'low', source?: string } | null}
 */
export function suggestUnitCostDefault(channelName, industry = 'unknown') {
  const unitType = detectUnitType(channelName);
  if (!unitType) return null;

  const industryTable = INDUSTRY_CPP_TABLE[industry] || INDUSTRY_CPP_TABLE.unknown;
  const range = industryTable[unitType];
  if (!range) {
    // Fallback на 'unknown' таблицу если specific industry не покрыт
    const fallback = INDUSTRY_CPP_TABLE.unknown[unitType];
    if (!fallback) return null;
    return {
      value: fallback.typical,
      range: { min: fallback.min, max: fallback.max },
      confidence: 'low',
      source: 'generic fallback',
    };
  }

  return {
    value: range.typical,
    range: { min: range.min, max: range.max },
    confidence: range.confidence,
    source: range.source,
  };
}


/**
 * Validate если user-entered unit_cost reasonable for industry + channel.
 *
 * @param {number} value
 * @param {string} channelName
 * @param {IndustryCode} [industry='unknown']
 * @returns {{ valid: boolean, severity: 'ok' | 'warning' | 'error', message?: string }}
 */
export function validateUnitCost(value, channelName, industry = 'unknown') {
  if (!isFinite(value) || value <= 0) {
    return { valid: false, severity: 'error', message: 'Стоимость должна быть положительным числом' };
  }
  const suggestion = suggestUnitCostDefault(channelName, industry);
  if (!suggestion) return { valid: true, severity: 'ok' };

  const { min, max } = suggestion.range;
  if (value < min) {
    return {
      valid: true,
      severity: 'warning',
      message: `Стоимость ниже типичной (${min.toLocaleString('ru-RU')} ₽). Уверены?`,
    };
  }
  if (value > max) {
    return {
      valid: true,
      severity: 'warning',
      message: `Стоимость выше типичной (${max.toLocaleString('ru-RU')} ₽). Уверены?`,
    };
  }
  return { valid: true, severity: 'ok' };
}


/**
 * List industries available в table.
 * @returns {IndustryCode[]}
 */
export function listIndustries() {
  return /** @type {IndustryCode[]} */ (Object.keys(INDUSTRY_CPP_TABLE));
}
