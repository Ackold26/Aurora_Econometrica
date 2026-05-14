"""Tests для column_detection.export_patterns_as_json() — Phase 1.1 SSOT."""
import json
import re
import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import pytest
from utils.column_detection import (
    classify_column,
    export_patterns_as_json,
    unit_label_for,
)


class TestExportSchema:
    def test_has_required_keys(self):
        payload = export_patterns_as_json()
        assert 'version' in payload
        assert 'kinds' in payload
        assert 'priority' in payload
        assert 'unit_label_rules' in payload

    def test_version_is_v1(self):
        assert export_patterns_as_json()['version'] == 'v1'

    def test_priority_kinds_all_in_kinds_map(self):
        payload = export_patterns_as_json()
        for kind in payload['priority']:
            assert kind in payload['kinds'], f'priority kind {kind} not in kinds map'

    def test_all_pattern_strings(self):
        """Every pattern must be a string (JSON serializable)."""
        payload = export_patterns_as_json()
        for kind, patterns in payload['kinds'].items():
            for p in patterns:
                assert isinstance(p, str), f'{kind} has non-string pattern: {p}'

    def test_unit_label_rules_have_pattern_and_label(self):
        payload = export_patterns_as_json()
        for rule in payload['unit_label_rules']:
            assert 'pattern' in rule
            assert 'label' in rule
            assert isinstance(rule['pattern'], str)
            assert isinstance(rule['label'], str)

    def test_json_serializable(self):
        """Roundtrip через JSON."""
        payload = export_patterns_as_json()
        serialized = json.dumps(payload, ensure_ascii=False)
        deserialized = json.loads(serialized)
        assert deserialized['version'] == 'v1'


class TestPatternsValid:
    """Каждый pattern должен быть valid Python regex (so JS можно reconstruct)."""

    def test_all_patterns_compile_in_python(self):
        payload = export_patterns_as_json()
        for kind, patterns in payload['kinds'].items():
            for p in patterns:
                try:
                    re.compile(p)
                except re.error as e:
                    pytest.fail(f'{kind} has invalid regex {p!r}: {e}')

    def test_all_unit_label_patterns_compile(self):
        payload = export_patterns_as_json()
        for rule in payload['unit_label_rules']:
            try:
                re.compile(rule['pattern'])
            except re.error as e:
                pytest.fail(f'unit_label rule {rule["label"]} has invalid regex: {e}')


class TestParityWithClassifier:
    """Exported patterns должны производить same kind как classify_column()."""

    @pytest.mark.parametrize("col_name,expected_kind", [
        ('tv_spend', 'monetary'),
        ('OLV Бюджет', 'monetary'),
        ('Banners Показы', 'physical'),
        ('TRPs бренд', 'physical'),
        ('Date', 'date'),
        ('Кол-во запросов', 'unknown'),  # Note: control_positive does not have 'запросов'
        ('competitor_trp', 'signed_competitor'),
        ('price_index', 'signed_price'),
        ('weather_temp', 'signed_weather'),
        ('cpi', 'signed_macro'),
        ('holiday_newyear', 'holiday'),
        ('sales_packs', 'target_count'),
        ('sales_rub', 'target_monetary'),
    ])
    def test_classify_results(self, col_name, expected_kind):
        assert classify_column(col_name) == expected_kind


class TestUnitLabelFor:
    @pytest.mark.parametrize("name,expected", [
        ('TRPs бренд (W 25-54)', '₽ за 1 TRP'),
        ('trp_brand', '₽ за 1 TRP'),
        ('GRP_total', '₽ за 1 GRP'),
        ('Banners Показы', '₽ за 1000 показов (CPM)'),
        ('impressions_total', '₽ за 1000 показов (CPM)'),
        ('Banners Клики', '₽ за 1 клик (CPC)'),
        ('clicks_search', '₽ за 1 клик (CPC)'),
        ('Social Визиты', '₽ за 1 визит'),
        ('Просмотры', '₽ за 1 просмотр'),
        ('reach_unique', '₽ за 1000 охвата'),
        ('Прочтения статей', '₽ за 1 прочтение'),
        ('Unknown', '₽ за 1 единицу'),
    ])
    def test_label_mapping(self, name, expected):
        assert unit_label_for(name) == expected

    def test_empty_name(self):
        assert unit_label_for('') == '₽ за 1 единицу'

    def test_none_safe(self):
        assert unit_label_for(None) == '₽ за 1 единицу'  # type: ignore[arg-type]
