"""Run legacy standalone test scripts (pre-Sprint 5 pattern).

Эти tests имеют top-level sys.exit() — не подходят для pytest collection,
но работают standalone. Этот runner запускает все по очереди.

Usage:
    python tools/run_legacy_tests.py        # all legacy
    python tools/run_legacy_tests.py --quick # skip slow MCMC tests

Used in CI как fallback to pytest для legacy tests coverage.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Files что должны run standalone (legacy pattern с top-level sys.exit).
# Synced с tools/conftest.py:collect_ignore.
LEGACY_TESTS = [
    'test_audit_of_sprint3.py',
    'test_causal_m0.py',
    'test_causal_m1.py',
    'test_causal_m2.py',
    'test_causal_m3.py',
    'test_causal_m4.py',
    'test_math_correctness.py',
    'test_narrative_adapter.py',
    'test_posterior_ci.py',
    'test_roi_verdict.py',
]

# Slow tests (MCMC training — skip с --quick).
SLOW_TESTS: set[str] = {
    # currently none — все pure synthetic / pickle-based.
    # Add e.g. 'test_full_mcmc.py' если появятся.
}


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    quick = '--quick' in argv
    tools_dir = Path(__file__).resolve().parent

    failed: list[str] = []
    total = 0
    for fname in LEGACY_TESTS:
        if quick and fname in SLOW_TESTS:
            print(f'  SKIP {fname} (--quick)')
            continue
        path = tools_dir / fname
        if not path.exists():
            print(f'  MISSING {fname}')
            continue
        total += 1
        print(f'\n=== {fname} ===')
        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(tools_dir.parent),
            capture_output=False,
        )
        if result.returncode != 0:
            failed.append(fname)
            print(f'  FAIL: {fname} (exit code {result.returncode})')

    print(f'\n' + '-' * 50)
    print(f'Legacy tests: {total - len(failed)}/{total} passed')
    if failed:
        print(f'Failed: {", ".join(failed)}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
