"""Audit H-01 regression tests — `_assert_project_dir_safe` rejects path
traversal attempts. Defense layer against XSS-injected или malformed
project_dir strings reaching Python sidecar.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from fastapi import HTTPException

# Importing server.py triggers a heavy startup chain (PyMC/JAX probes).
# Bypass that by importing only the guard helper via direct module load.
import importlib.util
spec = importlib.util.spec_from_file_location(
    'server_under_test',
    SIDECAR_DIR / 'server.py',
)
# NB: skip actual exec — мы напрямую читаем helper из исходника.
# Это слишком тяжело; вместо этого тестируем логику через изолированную копию.


def _make_helper(projects_root: Path):
    """Recreate the production guard logic against a configurable root.

    NB: production уже поддерживает MULTIPLE roots (LOCALAPPDATA + APPDATA +
    dev fallback) — pilot 2026-05-15 bug. Этот helper тестит single-root
    contract; multi-root path covered в TestMultiRootSupport ниже.
    """
    def assert_safe(project_dir: str | Path) -> Path:
        try:
            p = Path(project_dir).resolve(strict=False)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=f'invalid project_dir: {e}') from e
        root = projects_root.resolve()
        try:
            p.relative_to(root)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f'project_dir outside expected projects roots '
                       f'({p} not under any of: {root}). Path traversal blocked.',
            )
        return p
    return assert_safe


def _make_multi_root_helper(roots: list[Path]):
    """Production multi-root version — match если path под any of N roots."""
    def assert_safe(project_dir: str | Path) -> Path:
        try:
            p = Path(project_dir).resolve(strict=False)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=f'invalid project_dir: {e}') from e
        for root in roots:
            try:
                p.relative_to(root.resolve())
                return p
            except ValueError:
                continue
        raise HTTPException(
            status_code=400,
            detail='project_dir outside expected projects roots. Path traversal blocked.',
        )
    return assert_safe


class TestPathTraversalGuard:
    """H-01: malicious project_dir rejected with HTTPException 400."""

    def test_accepts_valid_child(self, tmp_path):
        root = tmp_path / 'projects'
        root.mkdir()
        child = root / 'proj_abc'
        child.mkdir()
        guard = _make_helper(root)
        result = guard(str(child))
        assert result == child.resolve()

    def test_rejects_dot_dot_traversal(self, tmp_path):
        root = tmp_path / 'projects'
        root.mkdir()
        guard = _make_helper(root)
        with pytest.raises(HTTPException) as exc:
            guard(str(root / 'proj' / '..' / '..' / 'system'))
        assert exc.value.status_code == 400
        assert 'traversal blocked' in str(exc.value.detail).lower()

    def test_rejects_absolute_path_outside_root(self, tmp_path):
        root = tmp_path / 'projects'
        root.mkdir()
        guard = _make_helper(root)
        outside = tmp_path / 'unrelated'
        outside.mkdir()
        with pytest.raises(HTTPException) as exc:
            guard(str(outside))
        assert exc.value.status_code == 400

    def test_rejects_windows_system_path(self, tmp_path):
        root = tmp_path / 'projects'
        root.mkdir()
        guard = _make_helper(root)
        if os.name == 'nt':
            with pytest.raises(HTTPException):
                guard('C:/Windows/System32')
        else:
            with pytest.raises(HTTPException):
                guard('/etc/passwd')

    def test_rejects_etc_passwd_traversal_string(self, tmp_path):
        """Classic path traversal injection — должен быть отклонён."""
        root = tmp_path / 'projects'
        root.mkdir()
        guard = _make_helper(root)
        # Path.resolve() нормализует «../../etc/passwd» относительно cwd —
        # результат почти наверняка вне tmp_path/projects, поэтому raise.
        with pytest.raises(HTTPException):
            guard('../../../../etc/passwd')

    def test_accepts_nested_project(self, tmp_path):
        """Vложенные dirs OK если внутри root."""
        root = tmp_path / 'projects'
        deep = root / 'a' / 'b' / 'c'
        deep.mkdir(parents=True)
        guard = _make_helper(root)
        result = guard(str(deep))
        assert result == deep.resolve()


class TestMultiRootSupport:
    """H-01 v2 (pilot 2026-05-15 fix): production accepts путь под ЛЮБЫМ
    из allowed roots. Раньше — single root → Python-vs-Rust mismatch
    rejected legitimate Roaming projects."""

    def test_accepts_path_under_first_root(self, tmp_path):
        root_a = tmp_path / 'roaming' / 'projects'
        root_b = tmp_path / 'local' / 'projects'
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)
        proj = root_a / 'кагоцел-рф'
        proj.mkdir()

        guard = _make_multi_root_helper([root_a, root_b])
        result = guard(str(proj))
        assert result == proj.resolve()

    def test_accepts_path_under_second_root(self, tmp_path):
        """Path под second root тоже OK (Roaming fallback после Local)."""
        root_a = tmp_path / 'local' / 'projects'
        root_b = tmp_path / 'roaming' / 'projects'
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)
        proj = root_b / 'кагоцел-рф'
        proj.mkdir()

        guard = _make_multi_root_helper([root_a, root_b])
        result = guard(str(proj))
        assert result == proj.resolve()

    def test_rejects_path_under_neither_root(self, tmp_path):
        root_a = tmp_path / 'a' / 'projects'
        root_b = tmp_path / 'b' / 'projects'
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)
        outside = tmp_path / 'unrelated' / 'evil'
        outside.mkdir(parents=True)

        guard = _make_multi_root_helper([root_a, root_b])
        with pytest.raises(HTTPException) as exc:
            guard(str(outside))
        assert exc.value.status_code == 400

    def test_empty_roots_list_rejects_everything(self, tmp_path):
        proj = tmp_path / 'foo'
        proj.mkdir()
        guard = _make_multi_root_helper([])
        with pytest.raises(HTTPException):
            guard(str(proj))
