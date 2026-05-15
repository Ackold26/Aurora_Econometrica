"""Tests для engines/project_migration.py — Phase 1.4."""
import json
import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import pytest
from engines.project_migration import (
    is_derived_metric,
    needs_migration,
    apply_migration,
    migrate_project_file,
    verify_project_integrity,
    TARGET_SCHEMA_VERSION,
    DERIVED_KEYS,
)


class TestIsDerivedMetric:
    @pytest.mark.parametrize("name,expected", [
        ('SOM в руб', True),
        ('SOM в уп.', True),
        ('SOV', True),
        ('sov_competitors', True),
        ('share_of_market', True),
        ('доля рынка', True),
        # False positives prevented:
        ('sales_rub', False),
        ('TV spend', False),
        ('TRPs бренд', False),
        ('Кол-во запросов', False),
        # Non-string
        (None, False),
        (123, False),
    ])
    def test_classification(self, name, expected):
        assert is_derived_metric(name) is expected


class TestNeedsMigration:
    def test_already_at_target(self):
        project = {'schema_version': TARGET_SCHEMA_VERSION, 'control_columns': []}
        needs, _ = needs_migration(project)
        assert needs is False

    def test_legacy_v1_0_no_derived(self):
        # H-09 added industry field — legacy without industry → needs migration
        project = {
            'control_columns': ['Кол-во запросов', 'temperature'],
            'industry': 'fmcg',  # legacy с уже выставленным industry → version bump only
        }
        needs, reason = needs_migration(project)
        assert needs is True
        assert 'version bump only' in reason

    def test_legacy_v1_0_missing_industry(self):
        """H-09: industry field absent → needs migration even без других changes."""
        project = {
            'schema_version': '2.0.1',  # already at previous target
            'control_columns': ['Кол-во запросов'],
        }
        needs, reason = needs_migration(project)
        assert needs is True
        assert 'industry' in reason.lower()

    def test_legacy_with_derived(self):
        project = {
            'schema_version': '1.0',
            'control_columns': ['Кол-во запросов', 'SOM в руб', 'SOV'],
        }
        needs, reason = needs_migration(project)
        assert needs is True
        assert 'misclassified' in reason
        assert 'SOM в руб' in reason or 'SOV' in reason

    def test_missing_schema_version(self):
        """No schema_version field defaults to '1.0' → needs migration."""
        project = {'control_columns': ['SOM в руб']}
        needs, _ = needs_migration(project)
        assert needs is True

    def test_invalid_input(self):
        assert needs_migration(None)[0] is False
        assert needs_migration([])[0] is False

    def test_malformed_control_columns(self):
        project = {'control_columns': 'not a list'}
        needs, _ = needs_migration(project)
        assert needs is False


class TestApplyMigration:
    def test_moves_derived_к_excluded(self):
        before = {
            'control_columns': ['Кол-во запросов', 'SOM в руб', 'SOV'],
            'excluded_columns': ['Other excluded'],
        }
        after = apply_migration(before)
        assert 'SOM в руб' not in after['control_columns']
        assert 'SOV' not in after['control_columns']
        assert 'SOM в руб' in after['excluded_columns']
        assert 'SOV' in after['excluded_columns']
        assert 'Other excluded' in after['excluded_columns']
        # Kept non-derived control
        assert 'Кол-во запросов' in after['control_columns']

    def test_bumps_schema_version(self):
        after = apply_migration({})
        assert after['schema_version'] == TARGET_SCHEMA_VERSION

    def test_does_not_mutate_input(self):
        before = {'control_columns': ['SOM в руб']}
        snapshot = dict(before)
        after = apply_migration(before)
        assert before == snapshot  # unchanged
        assert after is not before

    def test_preserves_other_fields(self):
        before = {
            'id': 'proj-1',
            'name': 'Test',
            'media_columns': ['tv_spend'],
            'kpi_column': 'sales_rub',
            'control_columns': ['SOM'],
        }
        after = apply_migration(before)
        assert after['id'] == 'proj-1'
        assert after['name'] == 'Test'
        assert after['media_columns'] == ['tv_spend']
        assert after['kpi_column'] == 'sales_rub'

    def test_idempotent(self):
        before = {
            'control_columns': ['Кол-во запросов', 'SOM в руб'],
            'excluded_columns': [],
        }
        once = apply_migration(before)
        twice = apply_migration(once)
        assert once == twice

    def test_dedup_in_excluded(self):
        before = {
            'control_columns': ['SOM'],
            'excluded_columns': ['SOM'],  # already excluded somehow
        }
        after = apply_migration(before)
        assert after['excluded_columns'].count('SOM') == 1

    # H-09 — industry field default stamping
    def test_stamps_industry_unknown_default(self):
        """Pre-Phase-4.1 project без industry → 'unknown' default."""
        after = apply_migration({'control_columns': []})
        assert after['industry'] == 'unknown'

    def test_preserves_valid_industry(self):
        """User-set industry (whitelist match) preserved through migration."""
        after = apply_migration({'control_columns': [], 'industry': 'pharma_otc'})
        assert after['industry'] == 'pharma_otc'

    def test_corrects_invalid_industry(self):
        """Malformed industry → corrected к 'unknown'."""
        after = apply_migration({'control_columns': [], 'industry': 'made_up'})
        assert after['industry'] == 'unknown'

    def test_corrects_non_string_industry(self):
        after = apply_migration({'control_columns': [], 'industry': 42})
        assert after['industry'] == 'unknown'

    # C-03 — JCS hash stamping
    def test_stamps_jcs_sha256(self):
        """apply_migration adds _jcs_sha256 field (INV-06 compliance)."""
        after = apply_migration({'control_columns': []})
        assert '_jcs_sha256' in after
        assert isinstance(after['_jcs_sha256'], str)
        assert len(after['_jcs_sha256']) == 64

    def test_hash_excludes_self(self):
        """Stored hash recomputable from payload без _jcs_sha256 field."""
        from utils.canonical_hash import compute_project_hash
        after = apply_migration({'control_columns': ['tv_spend']})
        stored = after['_jcs_sha256']
        payload_no_hash = {k: v for k, v in after.items() if k != '_jcs_sha256'}
        recomputed = compute_project_hash(payload_no_hash)
        assert recomputed == stored


class TestVerifyProjectIntegrity:
    """C-03 / INV-06 hash verification on load."""

    def test_no_hash_field_returns_ok(self):
        """Pre-Phase 1.6 projects (no field) — return ok."""
        ok, reason = verify_project_integrity({'control_columns': []})
        assert ok is True
        assert 'pre-Phase' in reason

    def test_matching_hash_returns_ok(self):
        """Round-trip apply_migration → verify_project_integrity = ok."""
        migrated = apply_migration({'control_columns': []})
        ok, reason = verify_project_integrity(migrated)
        assert ok is True
        assert 'OK' in reason

    def test_tampered_returns_mismatch(self):
        """Modify a field after stamping → verify detects mismatch."""
        migrated = apply_migration({'control_columns': ['tv_spend']})
        migrated['control_columns'] = ['tv_spend', 'tampered_column']
        ok, reason = verify_project_integrity(migrated)
        assert ok is False
        assert 'mismatch' in reason.lower()

    def test_malformed_hash_returns_false(self):
        ok, reason = verify_project_integrity({'_jcs_sha256': 'too_short'})
        assert ok is False
        assert 'malformed' in reason.lower()

    def test_non_string_hash_returns_false(self):
        ok, reason = verify_project_integrity({'_jcs_sha256': 12345})
        assert ok is False


class TestMigrateProjectFile:
    def test_no_file_returns_error(self, tmp_path):
        result = migrate_project_file(tmp_path / 'nonexistent.json')
        assert result['status'] == 'error'

    def test_already_migrated_returns_no_op(self, tmp_path):
        proj_path = tmp_path / 'project.json'
        proj_path.write_text(json.dumps({
            'schema_version': TARGET_SCHEMA_VERSION,
            'control_columns': [],
        }), encoding='utf-8')
        result = migrate_project_file(proj_path)
        assert result['status'] == 'no_migration_needed'

    def test_full_migration_flow(self, tmp_path):
        proj_path = tmp_path / 'project.json'
        original = {
            'id': 'pilot-pharma',
            'control_columns': ['Кол-во запросов', 'SOM в руб', 'SOV'],
            'excluded_columns': [],
        }
        proj_path.write_text(json.dumps(original, ensure_ascii=False),
                             encoding='utf-8')

        result = migrate_project_file(proj_path)

        assert result['status'] == 'ok'
        assert result['from_version'] == '1.0'
        assert result['to_version'] == TARGET_SCHEMA_VERSION
        assert 'SOM в руб' in result['migrated_columns']
        assert 'SOV' in result['migrated_columns']
        assert result['backup_path']
        assert result['backup_sha256']
        assert result['new_sha256']

        # Verify file content updated
        loaded = json.loads(proj_path.read_text(encoding='utf-8'))
        assert loaded['schema_version'] == TARGET_SCHEMA_VERSION
        assert 'SOM в руб' not in loaded['control_columns']
        assert 'SOM в руб' in loaded['excluded_columns']

        # Verify backup exists
        backup = Path(result['backup_path'])
        assert backup.exists()
        # Backup has original content
        backup_data = json.loads(backup.read_text(encoding='utf-8'))
        assert 'SOM в руб' in backup_data['control_columns']

    def test_idempotent_on_disk(self, tmp_path):
        proj_path = tmp_path / 'project.json'
        original = {
            'control_columns': ['SOM в руб'],
            'excluded_columns': [],
        }
        proj_path.write_text(json.dumps(original, ensure_ascii=False), encoding='utf-8')

        first = migrate_project_file(proj_path)
        assert first['status'] == 'ok'

        second = migrate_project_file(proj_path)
        assert second['status'] == 'no_migration_needed'
