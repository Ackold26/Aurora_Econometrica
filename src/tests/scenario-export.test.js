/**
 * scenario-export.js unit tests - v2.0.0 Phase D.
 *
 * Coverage:
 *   - exportToCsv: empty, single, multi-scenario, BOM prefix, comma escaping, number format
 *   - downloadBlob: DOM click triggered, URL revoked after timeout
 *   - buildExportFilename: includes date, correct structure
 *   - exportToExcel: mock invoke success, mock invoke throw (stub fallback)
 *   - exportToPptx: mock invoke success, mock invoke throw (stub fallback)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  exportToCsv,
  downloadBlob,
  buildExportFilename,
  exportToExcel,
  exportToPptx,
} from '../lib/scenario-export.js';
import { invoke } from '@tauri-apps/api/core';


// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** @returns {import('../lib/scenario-export.js').Scenario} */
function makeBaseline() {
  return {
    id: 'baseline',
    name: 'Базовый',
    budget: 50_000_000,
    predictedKpi: 200_000,
    ciLow: 185_000,
    ciHigh: 215_000,
    perChannelAllocation: { TV: 0.40, Digital: 0.35, OOH: 0.15, Print: 0.10 },
  };
}

/** @returns {import('../lib/scenario-export.js').Scenario} */
function makePlanA() {
  return {
    id: 'plan-a',
    name: 'План А',
    budget: 50_000_000,
    predictedKpi: 240_000,
    ciLow: 225_000,
    ciHigh: 256_000,
    perChannelAllocation: { TV: 0.25, Digital: 0.50, OOH: 0.15, Print: 0.10 },
  };
}

/** @returns {import('../lib/scenario-export.js').Scenario} */
function makePlanB() {
  return {
    id: 'plan-b',
    name: 'План Б',
    budget: 70_000_000,
    predictedKpi: 270_000,
    perChannelAllocation: { TV: 0.30, Digital: 0.40, OOH: 0.20, Print: 0.10 },
  };
}


// ---------------------------------------------------------------------------
// Suite 1: exportToCsv - structure
// ---------------------------------------------------------------------------
describe('exportToCsv - structure', () => {

  it('empty scenarios → header-only CSV (1 row after BOM)', () => {
    const csv = exportToCsv([], null);
    // BOM + header only → split on \r\n gives 1 entry
    const stripped = csv.replace(/^﻿/, '');
    const rows = stripped.split('\r\n').filter(r => r.length > 0);
    expect(rows.length).toBe(1);
    expect(rows[0]).toContain('Сценарий');
  });

  it('single scenario → header + 1 data row (2 rows total)', () => {
    const planA = makePlanA();
    const csv = exportToCsv([planA], null);
    const stripped = csv.replace(/^﻿/, '');
    const rows = stripped.split('\r\n').filter(r => r.length > 0);
    expect(rows.length).toBe(2);
  });

  it('baseline + 2 scenarios → header + 3 data rows (4 total)', () => {
    const baseline = makeBaseline();
    const csv = exportToCsv([makePlanA(), makePlanB()], baseline);
    const stripped = csv.replace(/^﻿/, '');
    const rows = stripped.split('\r\n').filter(r => r.length > 0);
    // header + baseline + planA + planB = 4
    expect(rows.length).toBe(4);
  });

  it('multi-scenario without baseline → correct row count', () => {
    const csv = exportToCsv([makePlanA(), makePlanB()], null);
    const stripped = csv.replace(/^﻿/, '');
    const rows = stripped.split('\r\n').filter(r => r.length > 0);
    expect(rows.length).toBe(3); // header + 2
  });

});


// ---------------------------------------------------------------------------
// Suite 2: exportToCsv - BOM and encoding
// ---------------------------------------------------------------------------
describe('exportToCsv - BOM prefix', () => {

  it('starts with UTF-8 BOM character (U+FEFF) for Excel compat', () => {
    const csv = exportToCsv([makePlanA()], null);
    expect(csv.charCodeAt(0)).toBe(0xFEFF);
  });

  it('BOM is exactly first char - second char starts the header column', () => {
    const csv = exportToCsv([makePlanA()], null);
    expect(csv[1]).not.toBe('﻿');
    // First header column starts with Сценарий
    expect(csv.slice(1)).toMatch(/^Сценарий/);
  });

});


// ---------------------------------------------------------------------------
// Suite 3: exportToCsv - CSV escaping and number formatting
// ---------------------------------------------------------------------------
describe('exportToCsv - escaping and formatting', () => {

  it('scenario name containing comma → wrapped in double quotes', () => {
    const sc = {
      id: 'x',
      name: 'План А, вариант 2',
      budget: 10_000_000,
      predictedKpi: 100_000,
    };
    const csv = exportToCsv([sc], null);
    expect(csv).toContain('"План А, вариант 2"');
  });

  it('scenario name with double quote → escaped as ""', () => {
    const sc = {
      id: 'x',
      name: 'Plan "A"',
      budget: 10_000_000,
      predictedKpi: 100_000,
    };
    const csv = exportToCsv([sc], null);
    expect(csv).toContain('"Plan ""A"""');
  });

  it('budget written as integer without thousands separator in CSV', () => {
    const sc = { id: 'x', name: 'Тест', budget: 50_000_000, predictedKpi: 200_000 };
    const csv = exportToCsv([sc], null);
    // Should contain 50000000 (not 50,000,000 - that would break CSV parsing)
    expect(csv).toContain('50000000');
  });

  it('predictedKpi rounded to integer in output', () => {
    const sc = { id: 'x', name: 'Тест', budget: 10_000_000, predictedKpi: 123456.7 };
    const csv = exportToCsv([sc], null);
    expect(csv).toContain('123457');
  });

  it('uplift column shows - for baseline row', () => {
    const baseline = makeBaseline();
    const csv = exportToCsv([makePlanA()], baseline);
    // Baseline row: uplift = - (cannot compare against itself)
    const rows = csv.replace(/^﻿/, '').split('\r\n');
    const baselineRow = rows.find(r => r.startsWith('Базовый') || r.includes('Базовый'));
    expect(baselineRow).toBeDefined();
    expect(baselineRow).toContain('-');
  });

  it('channel allocation formatted as percentage string (not raw fraction)', () => {
    const sc = {
      id: 'x',
      name: 'Тест',
      budget: 10_000_000,
      predictedKpi: 100_000,
      perChannelAllocation: { TV: 0.40 },
    };
    const csv = exportToCsv([sc], null);
    // 0.40 should appear as "40.0" not "0.4"
    expect(csv).toContain('40.0');
  });

  it('CI values present in output when provided', () => {
    const sc = makeBaseline();
    const csv = exportToCsv([sc], null);
    expect(csv).toContain('185000');
    expect(csv).toContain('215000');
  });

  it('CI - marker when ciLow/ciHigh absent', () => {
    const sc = { id: 'x', name: 'Тест', budget: 10_000_000, predictedKpi: 100_000 };
    const csv = exportToCsv([sc], null);
    // ciLow and ciHigh missing → '-'
    const rows = csv.replace(/^﻿/, '').split('\r\n');
    const dataRow = rows[1];
    expect(dataRow).toContain('-');
  });

});


// ---------------------------------------------------------------------------
// Suite 4: buildExportFilename
// ---------------------------------------------------------------------------
describe('buildExportFilename', () => {

  it('includes current date in YYYY-MM-DD format', () => {
    const fname = buildExportFilename([makePlanA()]);
    const dateStr = new Date().toISOString().slice(0, 10);
    expect(fname).toContain(dateStr);
  });

  it('includes scenario count', () => {
    const fname = buildExportFilename([makePlanA(), makePlanB()]);
    expect(fname).toContain('2');
  });

  it('starts with «aurora-scenarios» prefix', () => {
    const fname = buildExportFilename([makePlanA()]);
    expect(fname).toMatch(/^aurora-scenarios/);
  });

  it('empty scenarios array → still produces a valid filename string', () => {
    const fname = buildExportFilename([]);
    expect(typeof fname).toBe('string');
    expect(fname.length).toBeGreaterThan(0);
  });

});


// ---------------------------------------------------------------------------
// Suite 5: downloadBlob - DOM interaction
// ---------------------------------------------------------------------------
describe('downloadBlob - DOM interaction', () => {

  let createdUrls = [];
  let revokedUrls = [];
  let appendedElements = [];
  let clickedElements = [];

  beforeEach(() => {
    createdUrls = [];
    revokedUrls = [];
    appendedElements = [];
    clickedElements = [];

    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      const url = 'blob:mock-url-' + createdUrls.length;
      createdUrls.push(url);
      return url;
    });
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation((url) => {
      revokedUrls.push(url);
    });
    vi.spyOn(document.body, 'appendChild').mockImplementation((el) => {
      appendedElements.push(el);
      return el;
    });
    vi.spyOn(document.body, 'removeChild').mockImplementation((el) => el);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls URL.createObjectURL with the blob', () => {
    const blob = new Blob(['test'], { type: 'text/csv' });
    downloadBlob(blob, 'test.csv');
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
  });

  it('creates an anchor element with correct download attribute', () => {
    const blob = new Blob(['data'], { type: 'text/csv' });
    downloadBlob(blob, 'scenarios.csv');
    expect(appendedElements.length).toBeGreaterThan(0);
    const anchor = appendedElements[0];
    expect(anchor.tagName).toBe('A');
    expect(anchor.download).toBe('scenarios.csv');
  });

  it('anchor href is set to the object URL', () => {
    const blob = new Blob(['data']);
    downloadBlob(blob, 'file.csv');
    const anchor = appendedElements[0];
    expect(anchor.href).toMatch(/blob:mock-url/);
  });

  it('URL.revokeObjectURL called after timeout (async cleanup)', async () => {
    vi.useFakeTimers();
    const blob = new Blob(['data']);
    downloadBlob(blob, 'file.csv');
    expect(revokedUrls.length).toBe(0);
    vi.advanceTimersByTime(200);
    expect(revokedUrls.length).toBe(1);
    vi.useRealTimers();
  });

});


// ---------------------------------------------------------------------------
// Suite 6: exportToExcel - invoke mock
// ---------------------------------------------------------------------------
describe('exportToExcel - invoke mock', () => {

  it('returns path result on successful invoke', async () => {
    invoke.mockResolvedValueOnce({ path: '/tmp/scenarios.xlsx' });
    const result = await exportToExcel([makePlanA()], makeBaseline());
    expect(result).toEqual({ path: '/tmp/scenarios.xlsx' });
  });

  it('returns stub object when invoke throws (graceful degradation)', async () => {
    invoke.mockRejectedValueOnce(new Error('command not found'));
    const result = await exportToExcel([makePlanA()], null);
    expect(result).toHaveProperty('stub', true);
    expect(result).toHaveProperty('message');
    expect(typeof result.message).toBe('string');
  });

  it('stub message mentions CSV fallback', async () => {
    invoke.mockRejectedValueOnce(new Error('not impl'));
    const result = await exportToExcel([makePlanA()], null);
    expect(result.message).toContain('CSV');
  });

  it('returns a Promise', () => {
    invoke.mockResolvedValueOnce({ path: '/tmp/x.xlsx' });
    const r = exportToExcel([makePlanA()], null);
    expect(r).toBeInstanceOf(Promise);
  });

});


// ---------------------------------------------------------------------------
// Suite 7: exportToPptx - invoke mock
// ---------------------------------------------------------------------------
describe('exportToPptx - invoke mock', () => {

  it('returns path result on successful invoke', async () => {
    invoke.mockResolvedValueOnce({ path: '/tmp/scenarios.pptx' });
    const result = await exportToPptx([makePlanA()], makeBaseline());
    expect(result).toEqual({ path: '/tmp/scenarios.pptx' });
  });

  it('returns stub object when invoke throws', async () => {
    invoke.mockRejectedValueOnce(new Error('not implemented'));
    const result = await exportToPptx([makePlanA()], null);
    expect(result).toHaveProperty('stub', true);
    expect(result).toHaveProperty('message');
  });

  it('stub message mentions PPTX', async () => {
    invoke.mockRejectedValueOnce(new Error('not impl'));
    const result = await exportToPptx([makePlanA()], null);
    expect(result.message).toContain('PPTX');
  });

  it('returns a Promise', () => {
    invoke.mockResolvedValueOnce({ path: '/tmp/x.pptx' });
    const r = exportToPptx([makePlanA()], null);
    expect(r).toBeInstanceOf(Promise);
  });

});
