#!/usr/bin/env node
/**
 * Aurora Hybrid Design System — defensive tokens regen wrapper.
 *
 * Behavior:
 * - Default mode (no --check): если Standards/ доступен → regen tokens.generated.css.
 *   Если Standards/ отсутствует (CI runner без monorepo checkout) → skip с warning,
 *   build proceeds с vendored файлом.
 * - --check mode (lefthook + manual drift verify): требует Standards/ обязательно.
 *   Без него — exit 1 (нельзя verify drift).
 *
 * NB (Econometrica, 2026-07-02): генерит ТОЛЬКО tokens.generated.css (--target css).
 *   themes.generated.css / content-packs/themes.json НЕ трогаются — у Econometrica
 *   живой themes.json (v5) богаче appThemes SSOT (fun card-accents / pill-radius /
 *   insight-tint), app-themes переезд отложен (см. DESIGN_GAP_MAP_2026-07-01.md).
 *
 * Usage:
 *   node tools/build-tokens.mjs           # regen, defensive skip OK
 *   node tools/build-tokens.mjs --check   # drift check (exit 1 если drift OR Standards missing)
 */
import { existsSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const PRODUCT = 'econometrica';
const __dirname = dirname(fileURLToPath(import.meta.url));
const STANDARDS_BUILD = resolve(__dirname, '..', '..', '..', 'Standards', 'tokens', 'build.py');

const checkMode = process.argv.includes('--check');

if (!existsSync(STANDARDS_BUILD)) {
  if (checkMode) {
    console.error(`[hybrid-ds] ERROR: --check mode requires Standards/tokens/build.py`);
    console.error(`[hybrid-ds]   Looked at: ${STANDARDS_BUILD}`);
    console.error(`[hybrid-ds]   Solutions:`);
    console.error(`[hybrid-ds]     (1) Run from monorepo checkout (D:/Docs/Aurora_Ai/)`);
    console.error(`[hybrid-ds]     (2) Vendor Standards/tokens/ subset в product repo`);
    process.exit(1);
  }
  console.log(`[hybrid-ds] Standards/tokens/build.py не найден: ${STANDARDS_BUILD}`);
  console.log('[hybrid-ds] CI runner без monorepo checkout — using vendored tokens.generated.css');
  process.exit(0);
}

// 🔴 CPD-98: пути вывода общего генератора зашиты на дерево `Dev/Aurora_Econometrica`.
// Без явного указания сборка из ЛЮБОГО другого рабочего дерева (тонкого, канона,
// временного) писала бы токены в чужое дерево и чужую ветку, а своё оставляла со
// старыми. Проверено 16.08: файл в основном дереве менялся 15.08 в 22:06 – в момент
// сборки 2.4.10 отсюда. Считаем адресатов от СВОЕГО корня.
const REPO_ROOT = resolve(__dirname, '..');
const OUT = {
  css: resolve(REPO_ROOT, 'src', 'tokens.generated.css'),
  py: resolve(REPO_ROOT, 'sidecar', 'econometrica', 'aurora_tokens.py'),
  htmlCss: resolve(REPO_ROOT, 'sidecar', 'econometrica', 'aurora_html', 'templates', 'aurora_html.css'),
  htmlJs: resolve(REPO_ROOT, 'sidecar', 'econometrica', 'aurora_html', 'templates', 'aurora_html_tokens.js'),
};
const BSLASH = String.fromCharCode(92);
const q = (p) => '"' + p.split(BSLASH).join('/') + '"';
// Пути вывода задаёт сам генератор по --product, поэтому переносим их в СВОЁ
// рабочее дерево штатным флагом --product-root, а не переопределением --out-*
// (тот перекрывается флагом --product и молча не применяется).
const args = ['--target', 'css', '--product', PRODUCT, '--product-root', q(REPO_ROOT)];
if (checkMode) args.push('--check');

const standardsBuildNormalized = STANDARDS_BUILD.replaceAll('\\', '/');
const cmd = `python "${standardsBuildNormalized}" ${args.join(' ')}`;
try {
  execSync(cmd, { stdio: 'inherit' });
} catch (err) {
  process.exit(err.status || 1);
}
