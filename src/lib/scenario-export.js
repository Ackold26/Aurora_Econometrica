/**
 * Scenario Export helpers - CSV / PPTX export.
 *
 * Per WIZARD_FLOW_v2_FINAL.md §4.2 ScenarioExport + ADR-019 §7.
 *
 * PPTX delegates to Rust backend command `export_scenarios_pptx`. Command may
 * not be implemented yet - stub returns placeholder Blob with TODO comment
 * (per spec instruction).
 *
 * CSV is native JS - no extra deps required.
 *
 * (Excel/XLSX export removed - `econ_export_scenarios_xlsx` Rust command never
 * existed, button always failed silently. XLSX export is a backlog item.)
 *
 * @module scenario-export
 */


/**
 * @typedef {Object} Scenario
 * @property {string} id
 * @property {string} name
 * @property {number} budget
 * @property {number} predictedKpi
 * @property {number} [ciLow]
 * @property {number} [ciHigh]
 * @property {Record<string, number>} [perChannelAllocation]
 * @property {string[]} [dates]
 * @property {number[]} [predictions]
 */

// ──────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Compute uplift % vs baseline KPI. Returns '' if no baseline or base=0.
 * @param {Scenario} scenario
 * @param {Scenario | null} baseline
 * @returns {string}
 */
function upliftStr(scenario, baseline) {
  if (!baseline || !baseline.predictedKpi) return '-';
  if (scenario.id === baseline.id) return '-';
  const pct = ((scenario.predictedKpi - baseline.predictedKpi) / Math.abs(baseline.predictedKpi)) * 100;
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

/**
 * Escape a CSV cell value (quote if contains comma/newline/quote).
 * @param {string | number | null | undefined} value
 * @returns {string}
 */
function csvCell(value) {
  if (value == null) return '';
  const s = String(value);
  if (s.includes(',') || s.includes('"') || s.includes('\n')) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

/**
 * Collect all unique channel names across all scenarios + baseline.
 * @param {Scenario[]} scenarios
 * @param {Scenario | null} baseline
 * @returns {string[]}
 */
function collectChannels(scenarios, baseline) {
  /** @type {Set<string>} */
  const ch = new Set();
  const all = baseline ? [baseline, ...scenarios] : scenarios;
  for (const sc of all) {
    for (const k of Object.keys(sc.perChannelAllocation ?? {})) ch.add(k);
  }
  return [...ch].sort();
}

// ──────────────────────────────────────────────────────────────────────────────
// Public API
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Export scenarios comparison to CSV string.
 *
 * Format:
 * ```
 * Scenario,Budget (₽),Predicted KPI,Правдоподобный диапазон 90% Low,Правдоподобный диапазон 90% High,Uplift %,<Channel1> %,...
 * Baseline,50000000,245000,230000,262000,-,40,35,15,10
 * План А,50000000,264000,248000,281000,+7.8,25,50,10,15
 * ```
 *
 * @param {Scenario[]} scenarios
 * @param {Scenario | null} [baseline]
 * @returns {string} UTF-8 CSV content (BOM-prefixed for Excel compatibility)
 */
export function exportToCsv(scenarios, baseline = null) {
  const channels = collectChannels(scenarios, baseline);

  // Header
  const headerCols = [
    'Сценарий',
    'Бюджет (₽)',
    'Прогноз KPI',
    'Правдоподобный диапазон 90% нижн.',
    'Правдоподобный диапазон 90% верхн.',
    'Прирост %',
    ...channels.map(ch => `${ch} %`),
  ];
  const rows = [headerCols.map(csvCell).join(',')];

  // All rows: baseline first, then scenarios
  const all = baseline
    ? [baseline, ...scenarios.filter(s => s.id !== baseline.id)]
    : scenarios;

  for (const sc of all) {
    const alloc = sc.perChannelAllocation ?? {};
    const channelCells = channels.map(ch => {
      const v = alloc[ch];
      return v != null ? `${(v * 100).toFixed(1)}` : '-';
    });

    const row = [
      sc.name,
      sc.budget != null ? Math.round(sc.budget) : '',
      sc.predictedKpi != null ? Math.round(sc.predictedKpi) : '',
      sc.ciLow != null ? Math.round(sc.ciLow) : '-',
      sc.ciHigh != null ? Math.round(sc.ciHigh) : '-',
      upliftStr(sc, baseline),
      ...channelCells,
    ];
    rows.push(row.map(csvCell).join(','));
  }

  // UTF-8 BOM for correct Excel opening
  return '﻿' + rows.join('\r\n');
}



/**
 * Download a string content as a file via browser link-click trick.
 *
 * @param {string} content - UTF-8 string content
 * @param {string} filename
 * @param {string} [mimeType]
 */
export function downloadText(content, filename, mimeType = 'text/csv;charset=utf-8;') {
  const blob = new Blob([content], { type: mimeType });
  downloadBlob(blob, filename);
}

/**
 * Download a Blob via browser native link-click trick.
 *
 * @param {Blob} blob
 * @param {string} filename
 */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  // Cleanup after short delay (Firefox needs the element for the click)
  setTimeout(() => {
    URL.revokeObjectURL(url);
    document.body.removeChild(a);
  }, 150);
}

/**
 * Build a safe filename prefix from scenario names (max 40 chars, safe chars).
 * @param {Scenario[]} scenarios
 * @returns {string}
 */
export function buildExportFilename(scenarios) {
  const count = scenarios.length;
  const dateStr = new Date().toISOString().slice(0, 10);
  return `aurora-scenarios-${count}-${dateStr}`;
}
