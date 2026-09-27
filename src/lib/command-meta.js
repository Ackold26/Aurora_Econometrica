/**
 * Command metadata and cabinet categorization for Aurora AI.
 * Provides descriptions, examples, and grouping - all frontend-side.
 * CabinetCommand in Rust has only {command, label, group} - no descriptions.
 *
 * @module command-meta
 */

/**
 * @typedef {Object} BriefFieldOption
 * @property {string} value
 * @property {string} label
 * @property {boolean} [allowInput] - Show inline text input when this option is selected
 * @property {string} [inputPlaceholder]
 */

/**
 * @typedef {Object} BriefField
 * @property {string} id
 * @property {string} label
 * @property {'radio'|'checkboxes'|'text'} type
 * @property {BriefFieldOption[]} [options]
 * @property {string} [default] - Default value for radio
 * @property {string[]} [defaults] - Default selected values for checkboxes
 * @property {string[]} [chips] - Suggestion chips for text field
 * @property {string} [placeholder] - Placeholder for text field
 */

/**
 * @typedef {Object} CommandMeta
 * @property {string} description - Short description (1 line)
 * @property {string} [example] - Example task prompt
 * @property {string} [category] - Semantic category: create | analyze | edit | test | utility
 * @property {boolean} [needsFile] - Highlight when inbox has files
 * @property {BriefField[]} [briefFields] - If present, show CommandBrief panel on click
 */

// ── Data (loaded from content pack) ──

/** @type {Record<string, CommandMeta>} */
let _commands = {};
/** @type {Array<{name: string, ids: string[]}>} */
let _categories = [];
/** @type {Record<string, {name: string, cabinets: string[]|null}>} */
let _products = {};
/** @type {Record<string, string>} */
let _productNames = {};
/** Пакет с перечнем продуктов пришёл (initCommandMeta с `products`). Без него
 * JS-фильтр не решает за первый слой – список уже ограничен выдачей по
 * лицензии (аудит s51 M-1). Только ею: боевой `get_cabinets` фильтрует по
 * лицензии, Rust `filter_by_product` там зовётся лишь в DEV-ветке (аудит s52 L-2).
 * @type {boolean} */
let _productsLoaded = false;

/**
 * Initialize command metadata from content pack JSON.
 * Called once from +layout.svelte during app startup.
 * @param {any} data - parsed command-meta-data.json
 */
export function initCommandMeta(data) {
  if (data) {
    _commands = data.commands || {};
    _categories = data.categories || [];
    _products = data.products || {};
    _productsLoaded = !!data.products && typeof data.products === 'object';
    _productNames = Object.fromEntries(
      Object.entries(data.products || {}).map(([k, v]) => [k, v.name])
    );
  }
}

// ── Cabinet Categories (for NavRail sidebar grouping) ────────────────

/**
 * Group cabinets by category for NavRail sidebar.
 * Cabinets not in any category go into "Другое".
 * @param {Array<{id: string, name: string, icon: string, color: string}>} cabinets
 * @returns {Array<{name: string, items: any[]}>}
 */
export function getCategorizedCabinets(cabinets) {
  const result = [];
  const placed = new Set();

  for (const cat of _categories) {
    const items = [];
    for (const id of cat.ids) {
      const cab = cabinets.find(c => c.id === id);
      if (cab) {
        items.push(cab);
        placed.add(id);
      }
    }
    if (items.length > 0) {
      result.push({ name: cat.name, items });
    }
  }

  // Any cabinets not in categories
  const others = cabinets.filter(c => !placed.has(c.id));
  if (others.length > 0) {
    result.push({ name: 'ДРУГОЕ', items: others });
  }

  return result;
}

// ── Command Metadata ─────────────────────────────────────────────────

/**
 * Get metadata for a command. Returns null if not found.
 * @param {string} command - Slash command (e.g., "/contract")
 * @returns {CommandMeta|null}
 */
export function getCommandMeta(command) {
  return _commands[command] || null;
}

/**
 * Get brief fields for a command, if it requires a brief panel.
 * @param {string} command
 * @returns {{ fields: BriefField[] } | null}
 */
export function getCommandBrief(command) {
  const meta = _commands[command];
  if (!meta?.briefFields) return null;
  return { fields: meta.briefFields };
}

/**
 * Get commands that need files (for smart highlighting).
 * @param {string} _cabinetId - Currently unused, reserved for filtering
 * @returns {string[]} Array of command strings with needsFile: true
 */
export function getFileCommands(_cabinetId) {
  return Object.entries(_commands)
    .filter(([, meta]) => meta.needsFile)
    .map(([cmd]) => cmd);
}

// ── Product names and filtering ──────────────────────────────────────

/**
 * Get human-readable product name.
 * @param {string} productType
 * @returns {string}
 */
export function getProductName(productType) {
  return _productNames[productType] || 'Aurora AI';
}

/**
 * Ключи продукта без ограничения — видят ВСЕ кабинеты. Зеркалит
 * `cabinet.rs::filter_by_product()`: "agency" | "creative-hub" => None (все).
 * "media" сюда НЕ входит: в Rust у него `None`, но интерфейс и до правки
 * ограничивал его списком из content-pack (4 кабинета) — внесение в этот
 * перечень расширило бы права Insights Hub до всех кабинетов (s51).
 * @type {ReadonlySet<string>}
 */
const UNRESTRICTED_PRODUCT_KEYS = new Set(['agency', 'creative-hub']);

/**
 * Filter cabinets by product type. Agency/Creative Hub → all, others → subset,
 * незнакомый ключ ("unknown" или любой не перечисленный явно) → пусто.
 *
 * CPD-84 (JS-класс дыры, зеркалит правку Rust 44961d01): раньше `_products[productType]`
 * для незнакомого ключа был `undefined`, `?.cabinets` — `undefined`, `!allowed` — `true`,
 * и функция отдавала ВСЕ кабинеты — то же расширение прав, что было в
 * `filter_by_product`'s `_ => None` до правки. Теперь «все» — только для явно
 * перечисленных ключей, умолчание — пустой список.
 * @param {any[]} cabinets
 * @param {string} productType
 * @returns {any[]}
 */
export function filterCabinetsByProduct(cabinets, productType) {
  if (UNRESTRICTED_PRODUCT_KEYS.has(productType)) return cabinets;
  // Аудит s52 L-2: "unknown" – продукт НЕ опознан (отказ `get_product_type`), и
  // это известно без пакета. Проверяем ДО обхода ниже: иначе при неподгруженном
  // пакете незнакомый продукт снова получал бы всё, что выдала лицензия (CPD-84).
  if (productType === 'unknown') return [];
  // Аудит s51 M-1: пакет не пришёл (отказ подписи manifest, битый JSON) –
  // «ключа нет в пакете» здесь не значит «продукт незнаком». Список уже
  // ограничен первым слоем – выдачей по лицензии (Rust `filter_by_product`
  // в боевом `get_cabinets` не зовётся, только в DEV); закрыть его целиком –
  // спрятать кабинеты у своего же продукта без объяснения.
  if (!_productsLoaded) return cabinets;
  const allowed = _products[productType]?.cabinets;
  if (Array.isArray(allowed)) return cabinets.filter(c => allowed.includes(c.id));
  // CPD-84: незнакомый ключ продукта — пустой список, не «все».
  return [];
}
