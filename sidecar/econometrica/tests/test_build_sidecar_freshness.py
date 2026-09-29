"""`build_sidecar.py::find_stale_sources()` – сторож свежести движка (s58, 29.09.2026).

Симптом s57: правка `engines/planning.py` внесена ПОСРЕДИ сборки движка, сторож
сказал «Freshness verified», а в exe уехал прежний текст отказа. Корень: порогом
служило время записи exe (конец сборки), а PyInstaller собирает исходники в
начале – правка между этими моментами «старше» exe. Порог теперь – момент старта
PyInstaller (`min(exe_mtime, build_started)`).

L-3 аудита 2.5.9: сторож смотрел только `*.py`, а тексты отчётов (json, html
шаблоны) уезжают в пакет данными через `--add-data`. Теперь сверяются и они –
по тому же списку `PYINSTALLER_ARGS`, который получает PyInstaller.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SIDECAR_ROOT = _HERE.parent

if str(_SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(_SIDECAR_ROOT))

from build_sidecar import (  # noqa: E402
    PYINSTALLER_ARGS,
    ROOT,
    add_data_sources,
    find_stale_sources,
)


def _touch(path: Path, mtime: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_edit_during_build_is_stale(tmp_path):
    started, exe_written = 1_000_000.0, 1_000_600.0  # сборка шла 10 минут
    edited = _touch(tmp_path / "engines" / "planning.py", started + 300)
    _touch(tmp_path / "engines" / "validator.py", started - 60)

    assert find_stale_sources(tmp_path, min(exe_written, started), data_sources=[]) == [edited]
    # Прежний порог (время exe) эту правку пропускал – ровно случай s57.
    assert find_stale_sources(tmp_path, exe_written, data_sources=[]) == []


def test_sources_before_build_are_fresh(tmp_path):
    started = 1_000_000.0
    _touch(tmp_path / "server.py", started - 1)
    _touch(tmp_path / "engines" / "data_io.py", started - 3600)
    assert find_stale_sources(tmp_path, started, data_sources=[]) == []


def test_bundle_dirs_and_build_script_are_ignored(tmp_path):
    started = 1_000_000.0
    for rel in ("_internal/pkg/mod.py", "dist/x/y.py", "build_tmp/z.py", "build_sidecar.py"):
        _touch(tmp_path / rel, started + 10)
    kept = _touch(tmp_path / "tests" / "test_new.py", started + 10)
    assert find_stale_sources(tmp_path, started, data_sources=[]) == [kept]


# ── L-3 аудита 2.5.9: данные поставки, а не только .py ─────────────────────────


def _add_data_tree(root: Path, started: float) -> list[Path]:
    """Каталоги и файл «как в --add-data», все файлы – до старта сборки."""
    for rel in (
        "aurora_html/builder.py",
        "aurora_html/strings_ru.json",
        "aurora_html/templates/shell.html",
        "aurora_pptx/strings_ru.json",
        "aurora_pptx/assets/icons/up.png",
        "aurora_tokens.py",
    ):
        _touch(root / rel, started - 600)
    return [root / "aurora_html", root / "aurora_pptx", root / "aurora_tokens.py"]


def test_json_and_html_newer_than_build_start_are_stale(tmp_path):
    started = 1_000_000.0
    sources = _add_data_tree(tmp_path, started)
    strings = _touch(tmp_path / "aurora_html" / "strings_ru.json", started + 120)
    shell = _touch(tmp_path / "aurora_html" / "templates" / "shell.html", started + 240)
    pptx_strings = _touch(tmp_path / "aurora_pptx" / "strings_ru.json", started + 60)
    stale = find_stale_sources(tmp_path, started, data_sources=sources)
    assert sorted(stale) == sorted([strings, shell, pptx_strings])


def test_single_file_add_data_source_is_checked(tmp_path):
    started = 1_000_000.0
    sources = _add_data_tree(tmp_path, started)
    tokens = _touch(tmp_path / "aurora_tokens.py", started + 30)
    assert find_stale_sources(tmp_path, started, data_sources=sources) == [tokens]


def test_pycache_and_pyc_in_data_dirs_are_ignored(tmp_path):
    started = 1_000_000.0
    sources = _add_data_tree(tmp_path, started)
    _touch(tmp_path / "aurora_html" / "__pycache__" / "builder.cpython-312.pyc", started + 10)
    _touch(tmp_path / "aurora_pptx" / "stray.pyc", started + 10)
    _touch(tmp_path / "aurora_pptx" / ".pytest_cache" / "v" / "lastfailed", started + 10)
    assert find_stale_sources(tmp_path, started, data_sources=sources) == []


def test_py_inside_data_dir_reported_once(tmp_path):
    started = 1_000_000.0
    sources = _add_data_tree(tmp_path, started)
    edited = _touch(tmp_path / "aurora_html" / "builder.py", started + 5)
    assert find_stale_sources(tmp_path, started, data_sources=sources) == [edited]


def test_default_sources_are_pyinstaller_add_data():
    """Список по умолчанию – из PYINSTALLER_ARGS, не отдельная копия перечня."""
    sources = add_data_sources(PYINSTALLER_ARGS)
    assert ROOT / "aurora_html" in sources
    assert ROOT / "aurora_pptx" in sources
    assert ROOT / "aurora_tokens.py" in sources
    dests = [a for a in PYINSTALLER_ARGS if a == "--add-data"]
    assert len(sources) == len(dests)


def test_without_explicit_sources_reads_pyinstaller_args(tmp_path, monkeypatch):
    """Без data_sources сторож берёт --add-data из PYINSTALLER_ARGS сам."""
    import build_sidecar

    started = 1_000_000.0
    _add_data_tree(tmp_path, started)
    strings = _touch(tmp_path / "aurora_html" / "strings_ru.json", started + 120)
    monkeypatch.setattr(
        build_sidecar, "PYINSTALLER_ARGS",
        ["server.py", "--add-data", f"{tmp_path / 'aurora_html'}:aurora_html"],
    )
    assert find_stale_sources(tmp_path, started) == [strings]
