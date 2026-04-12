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
import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / 'dist'
OUTPUT_NAME = 'econometrica-sidecar'

# PyInstaller spec — onedir for fast startup
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

    # Hidden imports — PyMC / PyTensor lazy-import chains
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
    '--hidden-import=sklearn',
    '--hidden-import=fastapi',
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

    # Exclude torch — would add 2GB, not needed (FTS5/keyword ML only)
    '--exclude-module=torch',
    '--exclude-module=torchvision',
    '--exclude-module=torchaudio',
    '--exclude-module=dostoevsky',
    '--exclude-module=tensorflow',
    '--exclude-module=keras',
]


def main():
    print(f'Building {OUTPUT_NAME} with PyInstaller (--onedir)...')
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
    if exe_path.exists():
        size_mb = sum(f.stat().st_size for f in (DIST / OUTPUT_NAME).rglob('*') if f.is_file()) / 1e6
        print(f'\nBuild SUCCESS: {exe_path}')
        print(f'Bundle size: {size_mb:.0f} MB')
        print(f'\nNext step:')
        print(f'  Copy dist/{OUTPUT_NAME}/ → src-tauri/binaries/{OUTPUT_NAME}/')
        print(f'  Then reference in tauri.conf.json as externalBin')
    else:
        print(f'\nWARNING: Expected exe not found at {exe_path}')


if __name__ == '__main__':
    main()
