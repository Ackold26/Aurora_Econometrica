"""Sprint 5 Sync Helper — auto-inject lists из code в help HTML pages.

Pattern: HTML файлы имеют `<!-- AUTO_X -->` placeholder comments. Этот скрипт reads
canonical lists из `sidecar/econometrica/utils/channel_categorization.py` и
inline'ит их в HTML — drift-proof.

Usage:
    python tools/sync_help_lists.py            # write updated HTMLs
    python tools/sync_help_lists.py --check    # verify no drift (CI)

Markers поддерживаются:
    <!-- AUTO_BRAND_HINTS -->        — comma-separated list брэнд-hints
    <!-- AUTO_PERF_HINTS -->         — comma-separated list perf-hints
    <!-- AUTO_STRONG_PERF_HINTS -->  — comma-separated list strong-perf hints

Used by:
- Pre-commit lefthook hook (auto-rebuild)
- CI help-sync job (verify --check mode)

Single source of truth: utils/channel_categorization.py BRAND_HINTS / PERF_HINTS / STRONG_PERF_HINTS.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
sys.path.insert(0, str(SIDECAR))

from econometrica.utils.channel_categorization import (
    BRAND_HINTS,
    PERF_HINTS,
    STRONG_PERF_HINTS,
)

HELP_DIR = ROOT / 'src-tauri' / 'help-econometrica'

# Marker → replacement function
def _format_hints(hints: tuple[str, ...]) -> str:
    """Render hints as inline HTML — comma-separated <code> tags."""
    return ', '.join(f'<code>{h}</code>' for h in hints)


REPLACEMENTS = {
    'AUTO_BRAND_HINTS': _format_hints(BRAND_HINTS),
    'AUTO_PERF_HINTS': _format_hints(PERF_HINTS),
    'AUTO_STRONG_PERF_HINTS': _format_hints(STRONG_PERF_HINTS),
}


# Two marker styles supported:
# 1. Inline: `<!-- AUTO_X -->` replaced со generated content
#    NB: idempotent через re-mark с генерированным content между sentinels
# 2. Block: `<!-- AUTO_X_START --> ... <!-- AUTO_X_END -->`
#    содержимое между маркерами целиком — managed by ЭТОТ скрипт.
#
# Inline implementation: replace `<!-- AUTO_X -->` с `<!-- AUTO_X --><span>{content}</span><!-- /AUTO_X -->`.
# At next run: regex pattern `<!-- AUTO_X -->.*?<!-- /AUTO_X -->` удаляется и заменяется заново.

INLINE_PATTERN = re.compile(
    r'<!-- (AUTO_[A-Z_]+) -->(.*?<!-- /\1 -->)?',
    re.DOTALL,
)


def _replace_inline(html: str) -> str:
    """Replace inline AUTO_X markers с rendered content."""
    def _repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in REPLACEMENTS:
            return match.group(0)  # unknown marker — preserve
        content = REPLACEMENTS[key]
        return f'<!-- {key} -->{content}<!-- /{key} -->'
    return INLINE_PATTERN.sub(_repl, html)


def sync_file(path: Path, check_only: bool = False) -> bool:
    """Sync one HTML file. Returns True если файл changed (или would change в check mode)."""
    original = path.read_text(encoding='utf-8')
    updated = _replace_inline(original)
    changed = updated != original
    if changed and not check_only:
        path.write_text(updated, encoding='utf-8')
    return changed


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    check_only = '--check' in argv

    if not HELP_DIR.exists():
        print(f'Help dir not found: {HELP_DIR}')
        return 1

    html_files = sorted(HELP_DIR.glob('*.html'))
    if not html_files:
        print(f'No HTML files в {HELP_DIR}')
        return 0

    drifted: list[Path] = []
    for f in html_files:
        if sync_file(f, check_only=check_only):
            drifted.append(f)

    if check_only:
        if drifted:
            print(f'[FAIL] Drift detected в {len(drifted)} files (sync needed):')
            for f in drifted:
                print(f'  - {f.relative_to(ROOT)}')
            print(f'\nRun: python tools/sync_help_lists.py')
            return 1
        print(f'[OK] All {len(html_files)} HTML files in sync')
        return 0

    if drifted:
        print(f'[OK] Synced {len(drifted)} HTML files:')
        for f in drifted:
            print(f'  - {f.relative_to(ROOT)}')
    else:
        print(f'[OK] Already synced ({len(html_files)} HTML files)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
