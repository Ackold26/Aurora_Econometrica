/**
 * L1 lock-in test (math-fix v1.4 Section C, 2026-04-29).
 *
 * Verifies that all 3 mutator paths (drag-drop, Insights button, matrix click)
 * produce identical column state when applied to same input. Single source of
 * truth = `validateData.result.columns[i].role` via shared column-roles helper.
 *
 * Pre-fix: each mutator wrote inline mutation logic — vocabulary drift
 * (`'unused'` from Insights vs `'unknown'` from drag-drop unassigned) and
 * inconsistent persistence behavior. Lock-in test prevents regression.
 */
import { describe, it, expect } from 'vitest';
import {
  ROLES,
  isExcluded,
  setColumnRole,
  setColumnRolesBulk,
  deriveMapping,
  applyMapping,
  deriveExcludedColumns,
  restoreExcludedColumns,
  buildProjectUpdates,
} from '../lib/column-roles.js';

const COLUMNS = [
  { name: 'sales',     role: 'kpi' },
  { name: 'tv_grp',    role: 'media' },
  { name: 'digital',   role: 'media' },
  { name: 'social',    role: 'media' },
  { name: 'temperature', role: 'control' },
  { name: 'date',      role: 'date' },
  { name: 'unused_col', role: 'unknown' },
];

describe('ROLES vocabulary', () => {
  it('contains canonical 6 roles', () => {
    expect(ROLES).toEqual(['kpi', 'media', 'control', 'date', 'unused', 'unknown']);
  });

  it('isExcluded treats unused/unknown/null as excluded', () => {
    expect(isExcluded('unused')).toBe(true);
    expect(isExcluded('unknown')).toBe(true);
    expect(isExcluded(null)).toBe(true);
    expect(isExcluded(undefined)).toBe(true);
    expect(isExcluded('media')).toBe(false);
    expect(isExcluded('kpi')).toBe(false);
    expect(isExcluded('control')).toBe(false);
    expect(isExcluded('date')).toBe(false);
  });
});

describe('setColumnRole — single mutator', () => {
  it('returns immutable copy with target column updated', () => {
    const result = setColumnRole(COLUMNS, 'social', 'unused');
    expect(result).not.toBe(COLUMNS); // new array
    expect(result.find((c) => c.name === 'social').role).toBe('unused');
    expect(result.find((c) => c.name === 'tv_grp').role).toBe('media'); // unchanged
  });

  it('throws on invalid role', () => {
    expect(() => setColumnRole(COLUMNS, 'social', 'bogus')).toThrow();
  });

  it('returns same array if column not found (no-op)', () => {
    const result = setColumnRole(COLUMNS, 'nonexistent', 'unused');
    expect(result).toEqual(COLUMNS);
  });
});

describe('setColumnRolesBulk — bulk mutator (Insights "exclude")', () => {
  it('updates all named columns to target role', () => {
    const result = setColumnRolesBulk(COLUMNS, ['social', 'digital'], 'unused');
    expect(result.find((c) => c.name === 'social').role).toBe('unused');
    expect(result.find((c) => c.name === 'digital').role).toBe('unused');
    expect(result.find((c) => c.name === 'tv_grp').role).toBe('media');
  });

  it('throws on invalid role', () => {
    expect(() => setColumnRolesBulk(COLUMNS, ['social'], 'bogus')).toThrow();
  });
});

describe('deriveMapping → applyMapping round-trip', () => {
  it('preserves all roles after extract + apply', () => {
    const mapping = deriveMapping(COLUMNS);
    const reconstructed = applyMapping(COLUMNS, mapping);
    // Note: applyMapping only writes name+role, so we compare role per name
    for (const original of COLUMNS) {
      const restored = reconstructed.find((c) => c.name === original.name);
      expect(restored.role).toBe(original.role);
    }
  });

  it('mapping has expected shape', () => {
    const mapping = deriveMapping(COLUMNS);
    expect(mapping.kpi).toEqual(['sales']);
    expect(mapping.media).toEqual(['tv_grp', 'digital', 'social']);
    expect(mapping.control).toEqual(['temperature']);
    expect(mapping.date).toBe('date');
    expect(mapping.unknown).toEqual(['unused_col']);
  });
});

describe('Three-mutator-path consistency (L1 lock-in)', () => {
  it('Insights "exclude social" → same final state as ColumnMapper drag-drop social to unassigned', () => {
    // Path 1: InsightsPanel.applyAction({ type: 'exclude', columns: ['social'] })
    const insightsPath = setColumnRolesBulk(COLUMNS, ['social'], 'unused');

    // Path 2: ColumnMapper drag-drop — sets role='unknown' for unassigned
    const mapperMapping = deriveMapping(COLUMNS);
    mapperMapping.media = mapperMapping.media.filter((n) => n !== 'social');
    mapperMapping.unknown = [...mapperMapping.unknown, 'social'];
    const mapperPath = applyMapping(COLUMNS, mapperMapping);

    // Both paths produce excluded set with 'social' (regardless of role label)
    const insightsExcluded = deriveExcludedColumns(insightsPath);
    const mapperExcluded = deriveExcludedColumns(mapperPath);
    expect(insightsExcluded).toContain('social');
    expect(mapperExcluded).toContain('social');

    // buildProjectUpdates produces identical persistence payload
    const insightsUpdates = buildProjectUpdates(insightsPath);
    const mapperUpdates = buildProjectUpdates(mapperPath);
    expect(insightsUpdates.media_columns).toEqual(mapperUpdates.media_columns);
    expect(insightsUpdates.kpi_column).toEqual(mapperUpdates.kpi_column);
    expect(insightsUpdates.control_columns).toEqual(mapperUpdates.control_columns);
    // excluded_columns lists differ in vocabulary (unused vs unknown) but contain same names
    expect(new Set(insightsUpdates.excluded_columns)).toEqual(new Set(mapperUpdates.excluded_columns));
  });

  it('ValidateStep.excludeColumnByName matches Insights bulk exclude', () => {
    const single = setColumnRole(COLUMNS, 'social', 'unused');
    const bulk = setColumnRolesBulk(COLUMNS, ['social'], 'unused');
    expect(single).toEqual(bulk);
  });
});

describe('Persistence round-trip — restore excluded across re-validation', () => {
  it('restoreExcludedColumns preserves user choice over fresh validator detection', () => {
    // Simulate: user excluded 'social', closed project, reopened, validator
    // detected 'social' as media again. Restore from project.json.
    const freshFromValidator = COLUMNS.map((c) =>
      c.name === 'social' ? { ...c, role: 'media' } : c
    );
    const excludedColumns = ['social'];
    const restored = restoreExcludedColumns(freshFromValidator, excludedColumns);
    expect(restored.find((c) => c.name === 'social').role).toBe('unused');
    expect(restored.find((c) => c.name === 'tv_grp').role).toBe('media'); // others unchanged
  });

  it('handles empty excluded list (no-op)', () => {
    const result = restoreExcludedColumns(COLUMNS, []);
    expect(result).toBe(COLUMNS); // same reference (early return)
  });

  it('full cycle: derive → save → restore = original excluded state', () => {
    const userState = setColumnRolesBulk(COLUMNS, ['social', 'digital'], 'unused');
    const persisted = deriveExcludedColumns(userState); // ['social', 'digital', 'unused_col']

    // After re-validation (validator detects all as media again)
    const freshState = userState.map((c) =>
      isExcluded(c.role) ? { ...c, role: 'media' } : c
    );
    const restored = restoreExcludedColumns(freshState, persisted);

    expect(deriveExcludedColumns(restored).sort()).toEqual(persisted.slice().sort());
  });
});

describe('buildProjectUpdates payload shape', () => {
  it('matches Rust ProjectInfo update fields', () => {
    const updates = buildProjectUpdates(COLUMNS);
    expect(updates).toHaveProperty('kpi_column');
    expect(updates).toHaveProperty('media_columns');
    expect(updates).toHaveProperty('control_columns');
    expect(updates).toHaveProperty('excluded_columns');
    expect(Array.isArray(updates.media_columns)).toBe(true);
    expect(Array.isArray(updates.excluded_columns)).toBe(true);
  });

  it('kpi_column is null when no kpi role', () => {
    const noKpi = COLUMNS.map((c) => (c.role === 'kpi' ? { ...c, role: 'unknown' } : c));
    const updates = buildProjectUpdates(noKpi);
    expect(updates.kpi_column).toBeNull();
  });
});
