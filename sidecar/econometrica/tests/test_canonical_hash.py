"""Tests для utils/canonical_hash.py — Phase 1.6 / INV-06."""
import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import pytest
from utils.canonical_hash import (
    compute_project_hash,
    verify_project_hash,
)


class TestComputeProjectHash:
    def test_returns_hex_64(self):
        sha = compute_project_hash({'a': 1})
        assert isinstance(sha, str)
        assert len(sha) == 64

    def test_key_order_invariant(self):
        """JCS sorts keys lexicographically → same value any input order."""
        sha1 = compute_project_hash({'a': 1, 'b': 2})
        sha2 = compute_project_hash({'b': 2, 'a': 1})
        assert sha1 == sha2

    def test_different_values_different_hash(self):
        sha1 = compute_project_hash({'a': 1})
        sha2 = compute_project_hash({'a': 2})
        assert sha1 != sha2

    def test_nested_dict(self):
        sha = compute_project_hash({
            'nested': {'b': 2, 'a': [1, 2, {'x': 'y'}]},
            'top': 'value',
        })
        assert len(sha) == 64

    def test_cyrillic_strings(self):
        sha1 = compute_project_hash({'channel': 'TRPs бренд'})
        sha2 = compute_project_hash({'channel': 'TRPs бренд'})
        assert sha1 == sha2

    def test_empty_dict(self):
        sha = compute_project_hash({})
        assert len(sha) == 64

    def test_known_value_sha256(self):
        """Anchor: SHA-256 of canonical JSON {"a":1} is deterministic."""
        # Canonical JSON of {"a": 1} is: '{"a":1}' (7 bytes, no whitespace)
        # SHA-256 of '{"a":1}' bytes:
        import hashlib
        expected = hashlib.sha256(b'{"a":1}').hexdigest()
        assert compute_project_hash({'a': 1}) == expected


class TestVerifyProjectHash:
    def test_matching_returns_true(self):
        data = {'channels': ['tv', 'olv'], 'budget': 5000000}
        sha = compute_project_hash(data)
        assert verify_project_hash(data, sha) is True

    def test_mismatched_returns_false(self):
        data = {'a': 1}
        assert verify_project_hash(data, 'deadbeef' * 8) is False

    def test_invalid_hash_format(self):
        assert verify_project_hash({'a': 1}, 'not_a_hash') is False
        assert verify_project_hash({'a': 1}, '') is False
        # 32 chars (MD5-like, not SHA-256) → reject
        assert verify_project_hash({'a': 1}, 'a' * 32) is False

    def test_non_string_hash_safe(self):
        assert verify_project_hash({'a': 1}, None) is False  # type: ignore[arg-type]
        assert verify_project_hash({'a': 1}, 123) is False  # type: ignore[arg-type]


class TestUseCaseProjectJson:
    """Integration-like — test typical project.json payload."""

    def test_realistic_project_payload(self):
        project = {
            'id': 'кагоцел-рф-1405-26',
            'name': 'Pilot pharma project',
            'kpi_column': 'Продажи в руб. бренд',
            'media_columns': ['OLV Бюджет', 'Banners Бюджет', 'TRPs бренд'],
            'control_columns': ['Кол-во запросов'],
            'unit_costs': {'TRPs бренд': 25000.0},
            'unit_cost_inflation_pct': {'TRPs бренд': 15.0},
            'schema_version': '2.0.1',
        }
        sha = compute_project_hash(project)
        # Idempotent
        assert sha == compute_project_hash(project)
        # Sensitive к single byte mutation
        project['unit_costs']['TRPs бренд'] = 25001.0
        sha_mutated = compute_project_hash(project)
        assert sha != sha_mutated
