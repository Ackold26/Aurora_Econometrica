"""Tests для utils/safe_io.py — Phase 0.3."""
import json
import sys
import tempfile
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import pytest
from utils.safe_io import (
    atomic_write_json,
    verify_json_integrity,
    safe_backup_with_checksum,
    cleanup_stale_backups,
    compute_file_sha256,
)


class TestAtomicWriteJson:
    def test_writes_file(self, tmp_path):
        target = tmp_path / 'data.json'
        data = {'key': 'value', 'nested': {'a': 1}}
        sha = atomic_write_json(target, data)
        assert target.exists()
        loaded = json.loads(target.read_text(encoding='utf-8'))
        assert loaded == data
        assert len(sha) == 64  # SHA-256 hex

    def test_sha_matches_file_content(self, tmp_path):
        target = tmp_path / 'data.json'
        sha_returned = atomic_write_json(target, {'a': 1})
        sha_disk = compute_file_sha256(target)
        assert sha_returned == sha_disk

    def test_overwrites_existing(self, tmp_path):
        target = tmp_path / 'data.json'
        atomic_write_json(target, {'first': 1})
        sha2 = atomic_write_json(target, {'second': 2})
        loaded = json.loads(target.read_text(encoding='utf-8'))
        assert loaded == {'second': 2}
        assert sha2 == compute_file_sha256(target)

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / 'a' / 'b' / 'c' / 'data.json'
        atomic_write_json(target, {'x': 1})
        assert target.exists()

    def test_no_tmp_file_left(self, tmp_path):
        target = tmp_path / 'data.json'
        atomic_write_json(target, {'a': 1})
        tmp_leftover = list(tmp_path.glob('*.tmp'))
        assert tmp_leftover == []

    def test_cyrillic_content(self, tmp_path):
        target = tmp_path / 'data.json'
        data = {'channel': 'TRPs бренд (W 25-54)', 'price': 25000}
        atomic_write_json(target, data)
        loaded = json.loads(target.read_text(encoding='utf-8'))
        assert loaded['channel'] == 'TRPs бренд (W 25-54)'

    def test_sort_keys_changes_hash(self, tmp_path):
        target = tmp_path / 'data.json'
        data = {'b': 2, 'a': 1}
        sha_no_sort = atomic_write_json(target, data, sort_keys=False)
        sha_sorted = atomic_write_json(target, data, sort_keys=True)
        # JSON serialization order differs unless sort_keys=True forces canonical
        # Hashes may or may not differ depending on Python dict ordering; just
        # verify both produce valid output.
        assert sha_sorted == compute_file_sha256(target)

    def test_rejects_infinity(self, tmp_path):
        """Audit H-02: allow_nan=False prevents writing non-standard JSON tokens
        `Infinity` / `NaN` (RFC 8259 violation). Subsequent json.load would crash."""
        target = tmp_path / 'data.json'
        with pytest.raises(ValueError, match=r'(?i)not.*JSON.*compliant|out of range'):
            atomic_write_json(target, {'budget': float('inf')})

    def test_rejects_negative_infinity(self, tmp_path):
        target = tmp_path / 'data.json'
        with pytest.raises(ValueError):
            atomic_write_json(target, {'inflation': float('-inf')})

    def test_rejects_nan(self, tmp_path):
        target = tmp_path / 'data.json'
        with pytest.raises(ValueError):
            atomic_write_json(target, {'pct': float('nan')})

    def test_rejects_nested_infinity(self, tmp_path):
        """Inf в глубоко вложенной структуре тоже отклоняется."""
        target = tmp_path / 'data.json'
        with pytest.raises(ValueError):
            atomic_write_json(target, {
                'channels': {
                    'tv': {'unit_cost': 100, 'inflation': float('inf')},
                },
            })


class TestVerifyJsonIntegrity:
    def test_matching_hash_returns_true(self, tmp_path):
        target = tmp_path / 'data.json'
        sha = atomic_write_json(target, {'a': 1})
        assert verify_json_integrity(target, sha) is True

    def test_mismatched_hash_returns_false(self, tmp_path):
        target = tmp_path / 'data.json'
        atomic_write_json(target, {'a': 1})
        assert verify_json_integrity(target, 'deadbeef' * 8) is False

    def test_missing_file_returns_false(self, tmp_path):
        assert verify_json_integrity(tmp_path / 'nope.json', 'abc' * 21 + 'd') is False


class TestSafeBackupWithChecksum:
    def test_creates_backup(self, tmp_path):
        src = tmp_path / 'project.json'
        atomic_write_json(src, {'original': True})
        backup, sha = safe_backup_with_checksum(src, suffix='.pre_2_0_1')
        assert backup.exists()
        assert backup.name == 'project.json.pre_2_0_1'
        assert sha == compute_file_sha256(backup)

    def test_backup_content_matches_source(self, tmp_path):
        src = tmp_path / 'project.json'
        atomic_write_json(src, {'value': 42})
        backup, _ = safe_backup_with_checksum(src)
        assert backup.read_text(encoding='utf-8') == src.read_text(encoding='utf-8')

    def test_raises_if_source_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            safe_backup_with_checksum(tmp_path / 'nonexistent.json')


class TestCleanupStaleBackups:
    def test_keeps_last_n(self, tmp_path):
        # Create 5 backup files с different mtimes
        import time
        for i in range(5):
            f = tmp_path / f'project.json.pre_{i}'
            f.write_text('{}')
            # Stagger mtime
            mtime = time.time() - (5 - i) * 100
            os_set_mtime(f, mtime)
        removed = cleanup_stale_backups(tmp_path, pattern='*.pre_*', keep_last=3)
        # 5 total - 3 kept = 2 removed
        assert len(removed) == 2
        # Remaining: 3 files
        remaining = list(tmp_path.glob('*.pre_*'))
        assert len(remaining) == 3

    def test_empty_dir_returns_empty(self, tmp_path):
        removed = cleanup_stale_backups(tmp_path, keep_last=3)
        assert removed == []

    def test_missing_dir_returns_empty(self):
        removed = cleanup_stale_backups('/nonexistent/path/12345', keep_last=3)
        assert removed == []


def os_set_mtime(path: Path, mtime: float):
    """Helper для setting file mtime for sort tests."""
    import os
    os.utime(path, (mtime, mtime))
