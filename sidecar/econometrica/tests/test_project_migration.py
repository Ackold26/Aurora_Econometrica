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
        project = {'control_columns': ['Кол-во запросов', 'temperature']}
        needs, reason = needs_migration(project)
        assert needs is True
        assert 'version bump only' in reason

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
