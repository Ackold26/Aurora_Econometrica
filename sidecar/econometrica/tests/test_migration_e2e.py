"""E2E migration test on realistic project shape — H-21 (Партия 5).

End-to-end чрез pytest (без Tauri runtime). Verifies full migrate_project_file
flow на Кагоцел-shape dataset:
- 30+ column project с mixed KPI / media monetary / media physical / controls /
  SOM/SOV derived / holiday dummies.
- v1.0 schema без industry field.
- migrate_project_file должен:
  1. Detect needs_migration → True
  2. Create pre_2.0.2 backup с valid SHA-256 checksum
  3. Reclassify SOM/SOV/share_of_* → excluded_columns
  4. Stamp industry='unknown' default
  5. Stamp _jcs_sha256 canonical hash
  6. Bump schema_version → '2.0.2'
  7. Atomic write через safe_io
  8. Return status='ok' result с new_sha256

Не Tauri Driver / Playwright — Phase A scope. Полный Tauri E2E через
mcp__tauri__webview_* отложен к Phase 3 после proper budget.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from engines.project_migration import (
    migrate_project_file,
    needs_migration,
    apply_migration,
    verify_project_integrity,
    TARGET_SCHEMA_VERSION,
)
from utils.safe_io import verify_json_integrity


def realistic_pre_migration_project() -> dict:
    """30+ column Кагоцел-shape project на v1.0 schema без industry."""
    return {
        # No schema_version → treated as '1.0'
        'id': 'pilot-pharma-2024',
        'name': 'Pilot Pharma OTC 2024',
        'description': 'Pilot project for v2.0.1 hotfix verification',
        'created_at': '2024-01-15T10:00:00Z',
        'updated_at': '2024-12-20T14:30:00Z',
        'kpi_column': 'Продажи в руб. бренд',
        'media_columns': [
            'TV Бюджет',
            'OLV Бюджет до НДС до АК',
            'TRPs бренд (W 25-54)',
            'Banners Бюджет',
            'Banners Показы',
            'Banners Клики',
            'Social Бюджет',
            'Performance Бюджет',
            'Performance Клики',
            'OOH Бюджет',
            'Радио в руб.',
            'Пресса в руб.',
        ],
        'control_columns': [
            # Real controls
            'Кол-во запросов',
            'Конкуренты TRP',
            'Сезонность',
            'Холодная погода',
            'Праздники Q4',
            # BUG #3: derived metrics в control_columns должны migrate к excluded
            'SOM в руб',
            'SOV',
            'share_of_market_brand',
            'доля рынка Q4',
        ],
        'data_file': 'data/kagotsel_2024.xlsx',
        'unit_costs': {
            'TV Бюджет': 1.0,
            'OLV Бюджет до НДС до АК': 1.0,
            'TRPs бренд (W 25-54)': 850_000,  # OTC pharma typical
        },
        'excluded_columns': [],
        'channel_categories': {
            'TV Бюджет': 'brand',
            'OLV Бюджет до НДС до АК': 'mixed',
            'Banners Бюджет': 'performance',
            'Social Бюджет': 'brand',
        },
        'unit_cost_inflation_pct': {},
        # No `industry` field — Phase 4.1 H-09 added это в v2.0.2.
        # No `_jcs_sha256` field — Phase 1.6 C-03.
    }


class TestE2EMigrationFullFlow:
    """Full migration round-trip на realistic project shape."""

    def test_migrate_realistic_project_end_to_end(self, tmp_path):
        proj_json = tmp_path / 'project.json'
        original = realistic_pre_migration_project()
        proj_json.write_text(
            json.dumps(original, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

        # Step 1: pre-state assert — needs migration
        with open(proj_json, encoding='utf-8') as f:
            pre = json.load(f)
        needs, reason = needs_migration(pre)
        assert needs is True
        # Reason mentions both derived metrics + missing industry.
        assert 'derived' in reason.lower() or 'industry' in reason.lower()

        # Step 2: run migration
        result = migrate_project_file(proj_json)

        # Step 3: result envelope
        assert result['status'] == 'ok', f'migration failed: {result}'
        assert result['from_version'] == '1.0'
        assert result['to_version'] == TARGET_SCHEMA_VERSION  # '2.0.2'
        assert isinstance(result['migrated_columns'], list)
        # SOM/SOV/share_of/доля must be migrated
        moved = set(result['migrated_columns'])
        assert 'SOM в руб' in moved
        assert 'SOV' in moved
        assert 'share_of_market_brand' in moved
        assert 'доля рынка Q4' in moved
        # Real controls preserved (not moved)
        assert 'Кол-во запросов' not in moved
        assert 'Сезонность' not in moved

        # Step 4: backup created с valid checksum
        backup_path = Path(result['backup_path'])
        assert backup_path.exists(), f'backup missing: {backup_path}'
        assert verify_json_integrity(backup_path, result['backup_sha256']) is True

        # Step 5: new SHA-256 stamped
        assert isinstance(result['new_sha256'], str)
        assert len(result['new_sha256']) == 64

        # Step 6: load post-migration state
        with open(proj_json, encoding='utf-8') as f:
            post = json.load(f)

        # schema bumped
        assert post['schema_version'] == TARGET_SCHEMA_VERSION

        # industry default
        assert post['industry'] == 'unknown'

        # JCS hash stamped
        assert '_jcs_sha256' in post
        assert len(post['_jcs_sha256']) == 64

        # SOM/SOV moved к excluded
        excluded_set = set(post['excluded_columns'])
        assert 'SOM в руб' in excluded_set
        assert 'SOV' in excluded_set
        assert 'share_of_market_brand' in excluded_set
        assert 'доля рынка Q4' in excluded_set

        # Real controls preserved
        control_set = set(post['control_columns'])
        assert 'Кол-во запросов' in control_set
        assert 'Сезонность' in control_set
        # Derived removed
        assert 'SOM в руб' not in control_set
        assert 'SOV' not in control_set

        # Other fields preserved
        assert post['id'] == 'pilot-pharma-2024'
        assert post['kpi_column'] == 'Продажи в руб. бренд'
        assert len(post['media_columns']) == len(original['media_columns'])
        assert post['unit_costs']['TRPs бренд (W 25-54)'] == 850_000

        # Step 7: integrity verify on freshly migrated state
        integrity_ok, _ = verify_project_integrity(post)
        assert integrity_ok is True, 'fresh migration must produce verifiable hash'

    def test_idempotent_no_op_on_re_run(self, tmp_path):
        """Re-run migration on already-migrated project — no_migration_needed."""
        proj_json = tmp_path / 'project.json'
        proj_json.write_text(
            json.dumps(realistic_pre_migration_project(), ensure_ascii=False),
            encoding='utf-8',
        )
        # First run
        first = migrate_project_file(proj_json)
        assert first['status'] == 'ok'

        # Second run
        second = migrate_project_file(proj_json)
        assert second['status'] == 'no_migration_needed'

    def test_industry_preserved_if_user_set(self, tmp_path):
        """User manually set industry='pharma_otc' до migration — preserved."""
        proj_json = tmp_path / 'project.json'
        project = realistic_pre_migration_project()
        project['industry'] = 'pharma_otc'
        proj_json.write_text(
            json.dumps(project, ensure_ascii=False),
            encoding='utf-8',
        )
        result = migrate_project_file(proj_json)
        assert result['status'] == 'ok'

        with open(proj_json, encoding='utf-8') as f:
            post = json.load(f)
        assert post['industry'] == 'pharma_otc'

    def test_corrupt_industry_normalized(self, tmp_path):
        """Invalid industry value (not whitelist) → corrected к 'unknown'."""
        proj_json = tmp_path / 'project.json'
        project = realistic_pre_migration_project()
        project['industry'] = 'some_made_up_industry'
        proj_json.write_text(
            json.dumps(project, ensure_ascii=False),
            encoding='utf-8',
        )
        result = migrate_project_file(proj_json)
        assert result['status'] == 'ok'

        with open(proj_json, encoding='utf-8') as f:
            post = json.load(f)
        assert post['industry'] == 'unknown'


class TestE2EBackupIntegrity:
    """Verify backup safety net works end-to-end."""

    def test_backup_content_matches_pre_state(self, tmp_path):
        """Backup file должен exactly match pre-migration content."""
        proj_json = tmp_path / 'project.json'
        original = realistic_pre_migration_project()
        proj_json.write_text(
            json.dumps(original, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

        result = migrate_project_file(proj_json)
        backup_path = Path(result['backup_path'])
        with open(backup_path, encoding='utf-8') as f:
            backup_content = json.load(f)

        # Backup preserves original (no migration applied).
        assert backup_content == original

    def test_backup_checksum_round_trip(self, tmp_path):
        """SHA-256 returned matches recomputed file hash."""
        proj_json = tmp_path / 'project.json'
        proj_json.write_text(
            json.dumps(realistic_pre_migration_project(), ensure_ascii=False),
            encoding='utf-8',
        )
        result = migrate_project_file(proj_json)
        backup_path = Path(result['backup_path'])
        # verify_json_integrity recomputes hash → must match stored.
        assert verify_json_integrity(backup_path, result['backup_sha256']) is True


class TestE2EChannelSafety:
    """Edge cases: malformed channel lists должны handle gracefully."""

    def test_empty_control_columns_safe(self, tmp_path):
        proj_json = tmp_path / 'project.json'
        project = realistic_pre_migration_project()
        project['control_columns'] = []
        proj_json.write_text(json.dumps(project, ensure_ascii=False), encoding='utf-8')

        result = migrate_project_file(proj_json)
        assert result['status'] == 'ok'
        assert result['migrated_columns'] == []

    def test_all_derived_metrics_moved(self, tmp_path):
        """100% control_columns являются derived → all moved к excluded."""
        proj_json = tmp_path / 'project.json'
        project = realistic_pre_migration_project()
        project['control_columns'] = ['SOM', 'SOV', 'share_of_market', 'market_share_x']
        proj_json.write_text(json.dumps(project, ensure_ascii=False), encoding='utf-8')

        result = migrate_project_file(proj_json)
        assert result['status'] == 'ok'
        assert len(result['migrated_columns']) == 4

        with open(proj_json, encoding='utf-8') as f:
            post = json.load(f)
        assert post['control_columns'] == []
        assert len(set(post['excluded_columns']) & {'SOM', 'SOV', 'share_of_market', 'market_share_x'}) == 4
