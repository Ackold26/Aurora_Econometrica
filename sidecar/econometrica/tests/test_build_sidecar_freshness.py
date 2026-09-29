"""`build_sidecar.py::find_stale_sources()` – сторож свежести движка (s58, 29.09.2026).

Симптом s57: правка `engines/planning.py` внесена ПОСРЕДИ сборки движка, сторож
сказал «Freshness verified», а в exe уехал прежний текст отказа. Корень: порогом
служило время записи exe (конец сборки), а PyInstaller собирает исходники в
начале – правка между этими моментами «старше» exe. Порог теперь – момент старта
PyInstaller (`min(exe_mtime, build_started)`).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SIDECAR_ROOT = _HERE.parent

if str(_SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(_SIDECAR_ROOT))

from build_sidecar import find_stale_sources  # noqa: E402


def _touch(path: Path, mtime: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_edit_during_build_is_stale(tmp_path):
    started, exe_written = 1_000_000.0, 1_000_600.0  # сборка шла 10 минут
    edited = _touch(tmp_path / "engines" / "planning.py", started + 300)
    _touch(tmp_path / "engines" / "validator.py", started - 60)

    assert find_stale_sources(tmp_path, min(exe_written, started)) == [edited]
    # Прежний порог (время exe) эту правку пропускал – ровно случай s57.
    assert find_stale_sources(tmp_path, exe_written) == []


def test_sources_before_build_are_fresh(tmp_path):
    started = 1_000_000.0
    _touch(tmp_path / "server.py", started - 1)
    _touch(tmp_path / "engines" / "data_io.py", started - 3600)
    assert find_stale_sources(tmp_path, started) == []


def test_bundle_dirs_and_build_script_are_ignored(tmp_path):
    started = 1_000_000.0
    for rel in ("_internal/pkg/mod.py", "dist/x/y.py", "build_tmp/z.py", "build_sidecar.py"):
        _touch(tmp_path / rel, started + 10)
    kept = _touch(tmp_path / "tests" / "test_new.py", started + 10)
    assert find_stale_sources(tmp_path, started) == [kept]
