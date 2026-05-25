"""
PyInstaller build script for Aurora AI Econometrica sidecar.

Usage:
    cd sidecar/econometrica
    python build_sidecar.py

Output:
    dist/econometrica-sidecar/econometrica-sidecar.exe  (~400MB dir, no temp extraction)

Notes:
    - Uses --onedir (NOT --onefile): avoids 10-30s cold start from %TEMP% extraction
    - Bundled directory is referenced in tauri.conf.json as external binary resource
    - After build: copy dist/econometrica-sidecar/ → src-tauri/binaries/
"""
# ── Unicode-safe I/O ────────────────────────────────────────────────────
# На серверах с кодировкой cp1251 (Windows RU) print('✓') / любой не-ASCII
# символ → UnicodeEncodeError → sync-фаза build падает. PyInstaller сборка
# при этом завершается, но exe не копируется в sidecar/econometrica/.
# Инцидент: CLOUDEAI 2026-04-21. Fix универсальный, не точечный.
import os
import sys
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import subprocess
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / 'dist'
OUTPUT_NAME = 'econometrica-sidecar'

# PyInstaller spec - onedir for fast startup
PYINSTALLER_ARGS = [
    sys.executable, '-m', 'PyInstaller',
    'server.py',
    '--onedir',                          # directory bundle (no temp extraction)
    f'--name={OUTPUT_NAME}',
    '--noconfirm',                       # overwrite without prompting
    '--clean',                           # clean build cache
    '--distpath', str(DIST),
    '--workpath', str(ROOT / 'build_tmp'),
    '--specpath', str(ROOT / 'build_tmp'),

    # Hidden imports - PyMC / PyTensor lazy-import chains
    '--hidden-import=pymc',
    '--hidden-import=pytensor',
    '--hidden-import=pytensor.tensor',
    '--hidden-import=pymc_marketing',
    '--hidden-import=arviz',
    '--hidden-import=scipy',
    '--hidden-import=scipy.special',
    '--hidden-import=scipy.stats',
    '--hidden-import=scipy.optimize',
    '--hidden-import=numpy',
    '--hidden-import=pandas',
    '--hidden-import=openpyxl',
    '--collect-data=openpyxl',          # _constants.json runtime resource (V29 audit 2026-05-04)

    # v2.0.1 Phase 1.6 + 1.7 — JCS canonical hash + multi-tab file lock.
    # Both lazy-imported внутри hot paths; --hidden-import обязателен иначе
    # bundle ships silently broken (audit C-01).
    '--hidden-import=rfc8785',
    '--collect-data=rfc8785',
    '--hidden-import=filelock',
    '--collect-data=filelock',
    '--hidden-import=sklearn',
    '--hidden-import=fastapi',
    # FastAPI's OpenAPI models use Pydantic EmailStr → pydantic/networks.py calls
    # import_email_validator() which returns None if not bundled → AttributeError crash.
    # email_validator must be collected (not just hidden-import) so its data files ship too.
    '--collect-all=email_validator',
    '--hidden-import=uvicorn',
    '--hidden-import=uvicorn.logging',
    '--hidden-import=uvicorn.loops',
    '--hidden-import=uvicorn.loops.auto',
    '--hidden-import=uvicorn.protocols',
    '--hidden-import=uvicorn.protocols.http',
    '--hidden-import=uvicorn.protocols.http.auto',
    '--hidden-import=uvicorn.protocols.websockets',
    '--hidden-import=uvicorn.protocols.websockets.auto',
    '--hidden-import=uvicorn.lifespan',
    '--hidden-import=uvicorn.lifespan.on',

    # Include engines and charts as data (source files + any .json resources)
    '--add-data', f'{ROOT / "engines"}:engines',
    '--add-data', f'{ROOT / "charts"}:charts',
    '--add-data', f'{ROOT / "utils"}:utils',
    # aurora_pptx/ module + templates subfolder + strings_*.json (client-ready deliverables).
    # aurora_tokens.py is generated from Standards/tokens/tokens.json via build.py - see
    # regen step below in main(). Must be bundled as data so import works at runtime.
    '--add-data', f'{ROOT / "aurora_pptx"}:aurora_pptx',
    '--add-data', f'{ROOT / "aurora_tokens.py"}:.',
    # aurora_html/ - tier-1 interactive HTML deliverable (v1.0.12 program).
    # Ships bundled ECharts (common build), WOFF2 font subsets (Lora + Inter
    # cyrillic + latin), and generated aurora_html.css + aurora_html_tokens.js
    # from Standards/tokens/build.py html-css + html-js targets. Full tree
    # goes in as data so templates/ and fonts/ subdirs are available at runtime.
    '--add-data', f'{ROOT / "aurora_html"}:aurora_html',

    # Collect data files for packages that ship non-Python resources at runtime.
    # --hidden-import alone copies only .py; runtime resources (HTML/JSON/C templates/
    # fonts/headers) need --collect-data or --collect-all.
    #
    # Scanned 2026-04-20: packages with runtime data in site-packages. Core MMM stack
    # gets --collect-all (binaries + submodules + data) - safest against the class of
    # "FileNotFoundError at import" bugs (arviz icons, pytensor scan_perform.c, etc).
    '--collect-all=arviz',
    # arviz 0.23.4+ разделён на split packages (arviz_base, arviz_stats, arviz_plots).
    # --collect-all=arviz не тянет split-пакеты автоматически → FileNotFoundError
    # на импорте. Инцидент: CLOUDEAI 2026-04-21.
    '--collect-all=arviz_base',
    '--collect-all=arviz_stats',
    '--collect-all=arviz_plots',
    '--collect-all=pymc',
    '--collect-all=pymc_marketing',
    '--collect-all=pytensor',          # scan_perform.c, configdefaults, compile templates
    '--collect-all=xarray',
    # v1.0.9: NumPyro + JAX - нужны для Tier-1 NUTS sampler (5-15× скорость).
    # JAX CUDA wheels намеренно исключены (2GB+), CPU-only бандл ≈180MB.
    '--collect-all=numpyro',
    '--collect-all=jax',
    '--collect-all=jaxlib',
    # Secondary: data only (binaries auto-detected, submodules not all needed)
    '--collect-data=matplotlib',       # mpl-data: fonts, stylelib, rcparams
    '--collect-data=sklearn',          # datasets/data/*.csv
    '--collect-data=scipy',            # linalg headers, sparse/csgraph data
    '--collect-data=statsmodels',      # datasets CSV (if transitive dep)
    '--collect-data=numba',            # header files for JIT
    '--collect-data=pandas',           # io/formats/templates/*.tpl

    # Sprint 3 Pharma Causal - added 2026-04-27 для v1.0.14 ship (per ADR §3.1).
    # Per Q2(B): NO pysyncon, NO cvxpy. Manual scipy SLSQP for SCM weights.
    '--collect-all=linearmodels',      # DiD Callaway-Santanna 2021 (panel data)
    '--collect-all=econml',            # Causal Forest Wager-Athey (HTE)
    '--collect-data=statsmodels',      # panel utilities (transitive bumped explicit)

    # Exclude torch - would add 2GB, not needed (FTS5/keyword ML only)
    '--exclude-module=torch',
    '--exclude-module=torchvision',
    '--exclude-module=torchaudio',
    '--exclude-module=dostoevsky',
    '--exclude-module=tensorflow',
    '--exclude-module=keras',
    # JAX CUDA - CPU-only bundle; GPU backends бесполезны без NVIDIA driver + добавляют 2GB
    '--exclude-module=jaxlib.cuda',
    '--exclude-module=jax.experimental.gpu',
    '--exclude-module=jax.experimental.cuda',
]


def regenerate_tokens():
    """Regenerate aurora_tokens.py + aurora_html/templates/aurora_html.css +
    aurora_html/templates/aurora_html_tokens.js from Standards/tokens/tokens.json
    before bundle.

    Standards/tokens/build.py emits three generated files (Python for PPTX,
    CSS + JS for HTML). All are gitignored so must be regenerated on every
    build. Skipping any one causes ImportError or broken theming at runtime.
    """
    standards_build = ROOT.parent.parent.parent / 'Standards' / 'tokens' / 'build.py'
    if not standards_build.exists():
        print(f'WARNING: {standards_build} not found - tokens may be stale')
        return
    print(f'Regenerating tokens artifacts from tokens.json...')
    result = subprocess.run(
        [sys.executable, str(standards_build), '--target', 'all'],
        cwd=standards_build.parent,
    )
    if result.returncode != 0:
        print('ERROR: tokens regeneration failed')
        sys.exit(1)
    tokens_target = ROOT / 'aurora_tokens.py'
    html_css_target = ROOT / 'aurora_html' / 'templates' / 'aurora_html.css'
    html_js_target = ROOT / 'aurora_html' / 'templates' / 'aurora_html_tokens.js'
    for t in (tokens_target, html_css_target, html_js_target):
        if not t.exists():
            print(f'ERROR: {t} not produced by build.py')
            sys.exit(1)
        print(f'  [OK] {t.name} ({t.stat().st_size} bytes)')


def main():
    # ── Prerequisite: regenerate aurora_tokens.py from Standards/tokens/ ──
    # Without this, sidecar import econometrica.aurora_tokens fails at runtime.
    regenerate_tokens()

    print(f'\nBuilding {OUTPUT_NAME} with PyInstaller (--onedir)...')
    print(f'Output: {DIST / OUTPUT_NAME}/\n')

    result = subprocess.run(PYINSTALLER_ARGS, cwd=ROOT)
    if result.returncode != 0:
        print('\nBuild FAILED.')
        sys.exit(1)

    # Clean up build_tmp
    build_tmp = ROOT / 'build_tmp'
    if build_tmp.exists():
        shutil.rmtree(build_tmp, ignore_errors=True)

    exe_path = DIST / OUTPUT_NAME / f'{OUTPUT_NAME}.exe'
    if not exe_path.exists():
        print(f'\nWARNING: Expected exe not found at {exe_path}')
        return

    size_mb = sum(
        f.stat().st_size for f in (DIST / OUTPUT_NAME).rglob('*') if f.is_file()
    ) / 1e6
    print(f'\nBuild SUCCESS: {exe_path}')
    print(f'Bundle size: {size_mb:.0f} MB')

    # ── Auto-sync в sidecar/econometrica/ (где Tauri бандлит через resources) ──
    # Tauri.conf.json: "resources": ["../sidecar/econometrica/**/*"]
    # Поэтому копируем dist/econometrica-sidecar/* → sidecar/econometrica/
    # (ROOT это и есть sidecar/econometrica)
    print(f'\nSyncing bundle into {ROOT} (Tauri resource path)...')
    src_dir = DIST / OUTPUT_NAME

    # Снимаем старый exe + _internal/ перед копированием нового
    old_exe = ROOT / f'{OUTPUT_NAME}.exe'
    old_internal = ROOT / '_internal'
    for p in (old_exe, old_internal):
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except Exception as e:
                    print(f'  WARN: cannot remove {p}: {e}')

    # Копируем всё содержимое dist/econometrica-sidecar/ → ROOT
    copied = 0
    for item in src_dir.iterdir():
        dst = ROOT / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
            copied += 1
        except Exception as e:
            print(f'  ERROR copying {item.name}: {e}')
    print(f'  ✓ {copied} items synced into {ROOT}')

    # ── Freshness check (защита от stale exe в Tauri bundle) ───────────
    # npm run tauri build НЕ пересобирает sidecar - берёт готовый exe.
    # Если .py новее exe → installer попадёт старый sidecar, runtime
    # словит handshake mismatch / отсутствие эндпоинтов. Инцидент 2026-04-21.
    exe = ROOT / f'{OUTPUT_NAME}.exe'
    if exe.exists():
        exe_mtime = exe.stat().st_mtime
        stale = []
        for p in ROOT.rglob('*.py'):
            # Игнорируем build_tmp/ (если вдруг остался), dist/ и _internal/
            if any(part in ('build_tmp', 'dist', '_internal') for part in p.parts):
                continue
            if p.stat().st_mtime > exe_mtime:
                stale.append(p)
        if stale:
            print(f'\n[ERROR] Found {len(stale)} .py file(s) newer than {exe.name}:',
                  file=sys.stderr)
            for p in stale[:5]:
                print(f'  {p.relative_to(ROOT)}', file=sys.stderr)
            if len(stale) > 5:
                print(f'  ... +{len(stale) - 5} more', file=sys.stderr)
            print('Sync failed - exe was not refreshed. Re-run build.', file=sys.stderr)
            sys.exit(1)
        print(f'  [OK] Freshness verified (exe newer than all .py sources)')

    print(f'\nNext step: cd .. && npm run tauri build')


if __name__ == '__main__':
    main()
