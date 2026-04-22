#!/usr/bin/env node
/**
 * V40 AST linter — защита от XSS в Svelte-шаблонах.
 *
 * Правило: `{@html expr}` должен быть либо
 *   1) вызов одного из whitelisted helpers (escape/escapeHtml/renderMd/renderMarkdown/sanitize/purify/DOMPurify.sanitize),
 *   2) Literal (статическая строка),
 *   3) явно помечен bypass-комментарием `aurora-fix:safe` на той же или предыдущей строке.
 *
 * Всё остальное (идентификаторы, member access, .replace() цепочки, тернары, concat) — violation.
 *
 * Usage:
 *   node tools/lint-xss.mjs            # scan src/**\/*.svelte, exit 1 если violations
 *   node tools/lint-xss.mjs --file X   # одиночный файл
 */
import { parse } from 'svelte/compiler';
import { readFileSync, readdirSync, statSync } from 'fs';
import { join, relative, sep } from 'path';

const ROOT = 'src';
// Маркер должен быть внутри HTML-комментария <!-- ... -->, иначе false-positive
// при совпадении в title-атрибуте или строковом литерале на предыдущей строке.
// Non-greedy .*? чтобы тело комментария могло содержать любые символы (включая <b>),
// но не захватывать соседний комментарий на той же строке.
const BYPASS_RE = /<!--.*?\baurora-fix:safe\b.*?-->/;
const HELPER_RE = /^(escape|_escape|escapeHtml|sanitize|purify|renderMd|renderMarkdown)$/i;

const violations = [];

function walkDir(dir) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const st = statSync(p);
    if (st.isDirectory()) {
      if (entry === 'node_modules' || entry.startsWith('.')) continue;
      walkDir(p);
    } else if (p.endsWith('.svelte')) {
      checkFile(p);
    }
  }
}

function isSafeExpression(expr) {
  if (!expr) return false;
  if (expr.type === 'Literal') return true;
  if (expr.type === 'TemplateLiteral' && expr.expressions.length === 0) return true;
  if (expr.type === 'CallExpression') {
    const callee = expr.callee;
    if (callee?.type === 'Identifier' && HELPER_RE.test(callee.name)) return true;
    if (callee?.type === 'MemberExpression') {
      const prop = callee.property?.name;
      if (prop && HELPER_RE.test(prop)) return true;
      if (callee.object?.name === 'DOMPurify' && prop === 'sanitize') return true;
    }
  }
  return false;
}

function hasBypassComment(code, nodeStart) {
  const before = code.slice(0, nodeStart);
  const lines = before.split('\n');
  const lineNum = lines.length;
  const currentLine = lines[lineNum - 1] ?? '';
  const prevLine = lineNum >= 2 ? lines[lineNum - 2] : '';
  return BYPASS_RE.test(currentLine) || BYPASS_RE.test(prevLine);
}

function walkAst(node, fn) {
  if (!node || typeof node !== 'object') return;
  fn(node);
  for (const key in node) {
    if (key === 'parent' || key === 'start' || key === 'end') continue;
    const v = node[key];
    if (Array.isArray(v)) v.forEach((n) => walkAst(n, fn));
    else if (v && typeof v === 'object') walkAst(v, fn);
  }
}

function checkFile(path) {
  let code;
  try {
    code = readFileSync(path, 'utf-8');
  } catch {
    return;
  }
  let ast;
  try {
    ast = parse(code, { modern: true });
  } catch (err) {
    // Не валим линтер на parse errors — это забота svelte-check
    return;
  }
  walkAst(ast, (node) => {
    if (node.type !== 'HtmlTag') return;
    if (isSafeExpression(node.expression)) return;
    if (hasBypassComment(code, node.start)) return;

    const before = code.slice(0, node.start);
    const line = before.split('\n').length;
    const snippet = code.slice(node.start, node.end).replace(/\s+/g, ' ').slice(0, 120);
    violations.push({
      path: relative('.', path).split(sep).join('/'),
      line,
      snippet,
    });
  });
}

// CLI
const args = process.argv.slice(2);
const fileIdx = args.indexOf('--file');
if (fileIdx >= 0 && args[fileIdx + 1]) {
  checkFile(args[fileIdx + 1]);
} else {
  try {
    statSync(ROOT);
  } catch {
    console.error(`lint-xss: directory '${ROOT}' not found`);
    process.exit(2);
  }
  walkDir(ROOT);
}

if (violations.length) {
  console.error(`\n❌ V40 XSS violations (${violations.length}):\n`);
  for (const v of violations) {
    console.error(`  ${v.path}:${v.line}`);
    console.error(`    ${v.snippet}`);
  }
  console.error(`\nFix: wrap expression in escape()/escapeHtml()/renderMd(),`);
  console.error(`or add HTML comment <!-- aurora-fix:safe ... --> on same/previous line if legit.\n`);
  process.exit(1);
}
console.log('✓ V40 lint: OK');
