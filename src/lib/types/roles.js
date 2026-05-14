/**
 * Column role enum — Phase 2.5 / Audit P-shared-enum.
 *
 * Single source of truth для column role strings used в Aurora MMM
 * Optimizer pipeline. Mirrors Python backend's ColumnKind taxonomy
 * (sidecar/econometrica/utils/column_detection.py).
 *
 * Why frozen Object вместо TypeScript enum: JSDoc projects don't have
 * native enum support; Object.freeze() gives runtime immutability +
 * IDE autocompletion via JSDoc type tags.
 *
 * Usage:
 *   import { ROLES, isExcludedRole } from '$lib/types/roles.js';
 *   if (col.role === ROLES.UNUSED) { ... }
 *   if (isExcludedRole(col.role)) { ... }
 *
 * NB: backend may return additional roles in future (e.g. 'derived'
 * separate from 'unused'). Frontend mapping has fallback к 'excluded'
 * для unknown roles (no silent breaks).
 */

export const ROLES = Object.freeze({
  KPI: 'kpi',
  TARGET_MONETARY: 'target_monetary',
  TARGET_COUNT: 'target_count',
  MEDIA: 'media',
  MEDIA_MONETARY: 'monetary',
  MEDIA_PHYSICAL: 'physical',
  CONTROL: 'control',
  SIGNED_COMPETITOR: 'signed_competitor',
  SIGNED_PRICE: 'signed_price',
  SIGNED_WEATHER: 'signed_weather',
  SIGNED_MACRO: 'signed_macro',
  HOLIDAY: 'holiday',
  DATE: 'date',
  UNUSED: 'unused',
  EXCLUDED: 'excluded',
  UNKNOWN: 'unknown',
});

/**
 * @typedef {typeof ROLES[keyof typeof ROLES]} ColumnRole
 */

/**
 * Roles that mean «excluded from model» в UI display layer.
 * Used by ColumnMapperConfirm / AppliedModeSummary excluded list.
 */
export const EXCLUDED_DISPLAY_ROLES = Object.freeze(
  /** @type {ReadonlySet<string>} */ (new Set([
    ROLES.UNUSED,
    ROLES.EXCLUDED,
    ROLES.UNKNOWN,
  ])),
);

/**
 * Roles that представляют sales/revenue target metrics.
 */
export const TARGET_ROLES = Object.freeze(
  /** @type {ReadonlySet<string>} */ (new Set([
    ROLES.KPI,
    ROLES.TARGET_MONETARY,
    ROLES.TARGET_COUNT,
  ])),
);

/**
 * Roles that представляют media inputs (monetary spend OR physical metrics).
 */
export const MEDIA_ROLES = Object.freeze(
  /** @type {ReadonlySet<string>} */ (new Set([
    ROLES.MEDIA,
    ROLES.MEDIA_MONETARY,
    ROLES.MEDIA_PHYSICAL,
  ])),
);

/**
 * Roles that представляют control variables (signed factors + plain controls).
 */
export const CONTROL_ROLES = Object.freeze(
  /** @type {ReadonlySet<string>} */ (new Set([
    ROLES.CONTROL,
    ROLES.SIGNED_COMPETITOR,
    ROLES.SIGNED_PRICE,
    ROLES.SIGNED_WEATHER,
    ROLES.SIGNED_MACRO,
    ROLES.HOLIDAY,
  ])),
);


/**
 * True если role означает что column excluded from model.
 * Null/undefined treated as excluded (defensive — unknown role state).
 *
 * @param {string | null | undefined} role
 * @returns {boolean}
 */
export function isExcludedRole(role) {
  if (role == null) return true;
  return EXCLUDED_DISPLAY_ROLES.has(role);
}


/**
 * True если role представляет media input column.
 *
 * @param {string | null | undefined} role
 * @returns {boolean}
 */
export function isMediaRole(role) {
  if (role == null) return false;
  return MEDIA_ROLES.has(role);
}


/**
 * True если role представляет control variable (incl. signed factors).
 *
 * @param {string | null | undefined} role
 * @returns {boolean}
 */
export function isControlRole(role) {
  if (role == null) return false;
  return CONTROL_ROLES.has(role);
}


/**
 * True если role представляет target/KPI metric.
 *
 * @param {string | null | undefined} role
 * @returns {boolean}
 */
export function isTargetRole(role) {
  if (role == null) return false;
  return TARGET_ROLES.has(role);
}
