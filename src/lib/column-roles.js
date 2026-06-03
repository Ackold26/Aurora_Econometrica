/**
 * Single source of truth для column role mutations across pipeline.
 *
 * L1 (math-fix v1.4 Section C, 2026-04-29): unified handler для drag-drop
 * (ColumnMapper), Insights button (InsightsPanel), matrix click (ConfigPanel).
 * Pre-fix: each mutator wrote inline mutation logic - vocabulary drift
 * (`'unused'` from Insights vs `'unknown'` from drag-drop unassigned) and
 * inconsistent persistence behavior.
 *
 * Three principles:
 *   1. Immutable updates - return new column array, не mutate input
 *   2. Canonical role vocabulary - ROLES tuple defines all valid values
 *   3. Excluded set is derived - `isExcluded(role)` unifies 'unused' + 'unknown'
 *      semantics для downstream consumers (ratio, Model checkboxes, ConfigPanel
 *      media list).
 *
 * @module column-roles
 */

/**
 * Canonical column roles. Order matters для UI grouping defaults.
 * @type {readonly string[]}
 */
export const ROLES = /** @type {const} */ (['kpi', 'media', 'control', 'date', 'unused', 'unknown']);

/** Check if role represents «not used in model» (excluded set).
 *  'unused' = explicit user exclusion via Insights/manual
 *  'unknown' = unassigned (initial state OR drag-drop to «без роли»)
 *  Both treated equivalently downstream - backend receives only kpi/media/control/date.
 *  @param {string | undefined | null} role
 *  @returns {boolean} */
export function isExcluded(role) {
  return role === 'unused' || role === 'unknown' || role == null;
}

/** Single mutator API. Returns NEW columns array (immutable).
 *  Use this everywhere instead of inline `.map(c => c.name === name ? ...)` patterns.
 *  @param {any[]} columns
 *  @param {string} name - column name to update
 *  @param {string} role - one of ROLES
 *  @returns {any[]} new columns array */
export function setColumnRole(columns, name, role) {
  if (!ROLES.includes(role)) {
    throw new Error(`Invalid role '${role}'. Allowed: ${ROLES.join(', ')}`);
  }
  return columns.map((c) => (c.name === name ? { ...c, role } : c));
}

/** Bulk role update (e.g. для "exclude these 3 channels").
 *  @param {any[]} columns
 *  @param {string[]} names
 *  @param {string} role
 *  @returns {any[]} new columns array */
export function setColumnRolesBulk(columns, names, role) {
  if (!ROLES.includes(role)) {
    throw new Error(`Invalid role '${role}'. Allowed: ${ROLES.join(', ')}`);
  }
  const set = new Set(names);
  return columns.map((c) => (set.has(c.name) ? { ...c, role } : c));
}

/** Derive ColumnMapper-compatible mapping object from columns array.
 *  Used as adapter между store (canonical {name, role} per column) и
 *  ColumnMapper UI (mapping object с lists per role).
 *  @param {any[]} columns
 *  @returns {{kpi: string[], media: string[], control: string[], date: string|null, unknown: string[]}} */
export function deriveMapping(columns) {
  const kpi = [];
  const media = [];
  const control = [];
  const unknown = [];
  /** @type {string|null} */
  let date = null;
  for (const c of columns) {
    if (c.role === 'kpi') kpi.push(c.name);
    else if (c.role === 'media') media.push(c.name);
    else if (c.role === 'control') control.push(c.name);
    else if (c.role === 'date') date = c.name;
    else if (isExcluded(c.role)) unknown.push(c.name);
  }
  return { kpi, media, control, date, unknown };
}

/** Apply mapping object back к columns roles. Used after ColumnMapper
 *  emits onmappingchange - converts mapping to setColumnRole calls.
 *  @param {any[]} columns
 *  @param {{kpi?: string[], media?: string[], control?: string[], date?: string|null, unknown?: string[]}} mapping
 *  @returns {any[]} new columns array */
export function applyMapping(columns, mapping) {
  const kpiSet = new Set(mapping.kpi ?? []);
  const mediaSet = new Set(mapping.media ?? []);
  const controlSet = new Set(mapping.control ?? []);
  const unknownSet = new Set(mapping.unknown ?? []);
  const dateName = mapping.date ?? null;
  return columns.map((c) => {
    let newRole = 'unknown';
    if (kpiSet.has(c.name)) newRole = 'kpi';
    else if (mediaSet.has(c.name)) newRole = 'media';
    else if (controlSet.has(c.name)) newRole = 'control';
    else if (dateName === c.name) newRole = 'date';
    else if (unknownSet.has(c.name)) newRole = 'unknown';
    return c.role === newRole ? c : { ...c, role: newRole };
  });
}

/** Extract list of excluded column names for project.json persistence.
 *  Includes both 'unused' and 'unknown' - all "not in model" columns.
 *  @param {any[]} columns
 *  @returns {string[]} */
export function deriveExcludedColumns(columns) {
  return columns.filter((c) => isExcluded(c.role)).map((c) => c.name);
}

/** Restore excluded set from project.json on project load. Sets role='unused'
 *  для columns в excluded_columns list, preserving other roles.
 *  Used after re-validation: validator detects auto-roles, then this restores
 *  user's explicit «не использовать» choices.
 *  @param {any[]} columns
 *  @param {string[]} excludedNames
 *  @returns {any[]} new columns array */
export function restoreExcludedColumns(columns, excludedNames) {
  if (!Array.isArray(excludedNames) || excludedNames.length === 0) return columns;
  const excludedSet = new Set(excludedNames);
  return columns.map((c) => (excludedSet.has(c.name) ? { ...c, role: 'unused' } : c));
}

/** Build project_update payload с full role-derived state.
 *  Used everywhere persistence happens - single source of truth для what's
 *  saved к project.json. Includes excluded_columns explicit list (L1 fix).
 *  @param {any[]} columns
 *  @returns {{kpi_column: string|null, media_columns: string[], control_columns: string[], excluded_columns: string[]}} */
export function buildProjectUpdates(columns) {
  const mapping = deriveMapping(columns);
  return {
    kpi_column: mapping.kpi[0] ?? null,
    media_columns: mapping.media,
    control_columns: mapping.control,
    excluded_columns: deriveExcludedColumns(columns),
  };
}

/** LOAD-1 (A): реконструкция columns[] из ролей project.json — инверсия
 *  `buildProjectUpdates`. Нужна когда `validation.json` отсутствует (обученные
 *  проекты с `data_file:null`): делает loaded-проект роль-полным без сырых данных.
 *
 *  Universe = union kpi ∪ media ∪ control ∪ excluded. `excluded_columns` → role
 *  'unused' (тот же канонический словарь, что и `restoreExcludedColumns`). De-dup
 *  по precedence kpi > media > control > excluded (первая роль выигрывает —
 *  колонка не должна попасть в две роли, но если project.json рассинхронен,
 *  precedence детерминирован). null / нет ролей → [].
 *
 *  Round-trip lossless: `buildProjectUpdates(applyProjectRolesToColumns(info))`
 *  возвращает те же kpi_column/media_columns/control_columns/excluded_columns.
 *
 *  @param {{kpi_column?: string|null, media_columns?: string[], control_columns?: string[], excluded_columns?: string[]}|null|undefined} projectInfo
 *  @returns {Array<{name:string, role:string}>} */
export function applyProjectRolesToColumns(projectInfo) {
  if (!projectInfo) return [];
  const media = Array.isArray(projectInfo.media_columns) ? projectInfo.media_columns : [];
  const control = Array.isArray(projectInfo.control_columns) ? projectInfo.control_columns : [];
  const excluded = Array.isArray(projectInfo.excluded_columns) ? projectInfo.excluded_columns : [];
  /** @type {Array<{name:string, role:string}>} */
  const cols = [];
  const seen = new Set();
  /** @param {string|null|undefined} name @param {string} role */
  const add = (name, role) => {
    if (!name || seen.has(name)) return; // precedence: первая роль выигрывает
    seen.add(name);
    cols.push({ name, role });
  };
  add(projectInfo.kpi_column, 'kpi');
  for (const m of media) add(m, 'media');
  for (const c of control) add(c, 'control');
  for (const e of excluded) add(e, 'unused');
  return cols;
}
