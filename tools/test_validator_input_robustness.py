"""Validator input robustness — Phase 2.11 / Audit S1+Q3.

Audit S1: detect_column_role(col_name=None) — col_name.lower() raises
AttributeError если passed non-string. Existing tests don't cover.
Audit Q3: negative numbers / NaN / empty strings — what happens?

This module ensures validator gracefully handles malformed input что
может surface через corrupt project.json или buggy pandas operations.

NB: Phase 1.2 validate_role_compatibility tests cover OK path for unit_costs
bounds — this file targets validator.detect_column_role() row classification
api directly (older function used в many places downstream).
"""
import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1] / 'sidecar' / 'econometrica'
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import pytest
from engines.validator import (
    detect_column_role,
    detect_column_role_with_confidence,
)


class TestNoneInputSafety:
    """S1: None / non-string col_name. Currently raises AttributeError.

    Documenting current behaviour. Future hardening will catch и return
    'unknown' gracefully (defensive contract). Defining failure mode
    here so any regression is detected.
    """

    def test_none_currently_raises(self):
        """detect_column_role(None) → AttributeError на .lower() call."""
        with pytest.raises(AttributeError):
            detect_column_role(None)  # type: ignore[arg-type]

    def test_empty_string_returns_unknown(self):
        """Empty string не crashes, returns 'unknown'."""
        role = detect_column_role('')
        assert role == 'unknown'

    def test_whitespace_only_returns_unknown(self):
        role = detect_column_role('   ')
        assert role == 'unknown'

    def test_numeric_input_raises(self):
        """Integer not allowed (Python type protocol)."""
        with pytest.raises(AttributeError):
            detect_column_role(42)  # type: ignore[arg-type]

    def test_with_confidence_returns_zero_for_empty(self):
        role, conf = detect_column_role_with_confidence('')
        assert role == 'unknown'
        assert conf == 0.0


class TestCyrillicEdgeCases:
    """Q3-related: cyrillic strings с specific edge cases."""

    def test_combining_diacritics(self):
        """Combining acute accent character с regular letter."""
        # 'А́' = А + combining acute. Should be treated like normal text.
        role = detect_column_role('А́втор')
        # Result: 'unknown' (no specific pattern matches, не crashes)
        assert role in ('unknown', 'control', 'kpi', 'media')

    def test_mixed_case_cyrillic(self):
        role = detect_column_role('Бюджет')
        assert role == 'media'

    def test_with_punctuation(self):
        """Cyrillic + punctuation."""
        role = detect_column_role('Продажи, ₽')
        # Result not crash; '₽' triggers monetary content
        assert role in ('kpi', 'media', 'control', 'unknown')

    def test_leading_trailing_whitespace(self):
        role1 = detect_column_role('  бюджет  ')
        role2 = detect_column_role('бюджет')
        # Whitespace handling depends on patterns; both должны give valid role
        assert role1 in ('kpi', 'media', 'control', 'unknown')
        assert role2 == 'media'


class TestUnknownConfidenceFloor:
    """Validator may return 0.0 confidence; downstream consumers expect
    floating-point, not None or NaN."""

    def test_unknown_returns_zero_confidence(self):
        _role, conf = detect_column_role_with_confidence('totally_random_col_xyz')
        # Either 'unknown' с 0.0 OR something else с >0.0 — but no NaN
        assert conf == conf  # NaN check (NaN != NaN)
        assert conf >= 0.0
        assert conf <= 1.0


class TestSpecificColumnNames:
    """Q3 follow-up: explicit known column names from pilot datasets."""

    @pytest.mark.parametrize("col_name,expected_role", [
        # From pilot pharma dataset:
        ('OLV Бюджет до НДС до АК', 'media'),
        ('Banners Показы', 'media'),
        ('Кол-во запросов', 'control'),  # 'запрос' in CONTROL_PATTERNS via substring
        ('SOM в руб', 'unused'),  # BUG #3 fix via DERIVED_KEYS
        ('SOV', 'unused'),
        ('TRPs бренд (W 25-54)', 'media'),
        # KPI candidates:
        ('Продажи в руб. бренд', 'kpi'),
    ])
    def test_pilot_dataset_columns(self, col_name, expected_role):
        actual = detect_column_role(col_name)
        assert actual == expected_role, (
            f'Expected {expected_role!r} for {col_name!r}, got {actual!r}'
        )
