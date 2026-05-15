"""C-05a: pickle SHA-256 sidecar verification regression tests.

Short-term RCE-attack mitigation per Aurora Launch retro 2026-05-15.
Full pickle replacement defer к v2.2.0.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pytest

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from engines.persistence import (
    write_pkl_sha256_sidecar,
    verify_pkl_sha256_sidecar,
    _pkl_sha256_sidecar_path,
)


class TestSidecarPath:
    def test_sidecar_path_appends_sha256(self, tmp_path):
        pkl = tmp_path / 'latest.pkl'
        sidecar = _pkl_sha256_sidecar_path(pkl)
        assert sidecar == tmp_path / 'latest.pkl.sha256'


class TestWriteSidecar:
    def test_writes_64_char_hex(self, tmp_path):
        pkl = tmp_path / 'latest.pkl'
        with open(pkl, 'wb') as f:
            pickle.dump({'data': 'value'}, f)
        sha = write_pkl_sha256_sidecar(pkl)
        assert len(sha) == 64
        sidecar = tmp_path / 'latest.pkl.sha256'
        assert sidecar.exists()
        assert sidecar.read_text().strip() == sha

    def test_overwrites_existing_sidecar(self, tmp_path):
        pkl = tmp_path / 'latest.pkl'
        with open(pkl, 'wb') as f:
            pickle.dump({'v': 1}, f)
        sha1 = write_pkl_sha256_sidecar(pkl)

        with open(pkl, 'wb') as f:
            pickle.dump({'v': 2}, f)
        sha2 = write_pkl_sha256_sidecar(pkl)

        assert sha1 != sha2
        assert (tmp_path / 'latest.pkl.sha256').read_text().strip() == sha2


class TestVerifySidecar:
    def test_matching_returns_ok(self, tmp_path):
        pkl = tmp_path / 'latest.pkl'
        with open(pkl, 'wb') as f:
            pickle.dump({'data': 'value'}, f)
        write_pkl_sha256_sidecar(pkl)
        ok, reason = verify_pkl_sha256_sidecar(pkl)
        assert ok is True
        assert 'OK' in reason

    def test_no_sidecar_returns_ok_legacy(self, tmp_path):
        """Pre-Phase-2 pickle без sidecar — backward compat."""
        pkl = tmp_path / 'latest.pkl'
        with open(pkl, 'wb') as f:
            pickle.dump({'data': 'value'}, f)
        ok, reason = verify_pkl_sha256_sidecar(pkl)
        assert ok is True
        assert 'no sidecar' in reason.lower()

    def test_tampered_pickle_detected(self, tmp_path):
        """Modify pickle bytes after stamping → mismatch detected."""
        pkl = tmp_path / 'latest.pkl'
        with open(pkl, 'wb') as f:
            pickle.dump({'data': 'value'}, f)
        write_pkl_sha256_sidecar(pkl)

        # Append garbage bytes — simulates tamper.
        with open(pkl, 'ab') as f:
            f.write(b'\x00malicious payload')

        ok, reason = verify_pkl_sha256_sidecar(pkl)
        assert ok is False
        assert 'mismatch' in reason.lower()

    def test_malformed_sidecar_returns_false(self, tmp_path):
        pkl = tmp_path / 'latest.pkl'
        with open(pkl, 'wb') as f:
            pickle.dump({'data': 'value'}, f)
        # Sidecar содержит garbage, не hex.
        (tmp_path / 'latest.pkl.sha256').write_text('not_a_valid_hash')
        ok, reason = verify_pkl_sha256_sidecar(pkl)
        assert ok is False
        assert 'malformed' in reason.lower()

    def test_empty_sidecar_returns_false(self, tmp_path):
        pkl = tmp_path / 'latest.pkl'
        with open(pkl, 'wb') as f:
            pickle.dump({}, f)
        (tmp_path / 'latest.pkl.sha256').write_text('')
        ok, reason = verify_pkl_sha256_sidecar(pkl)
        assert ok is False
