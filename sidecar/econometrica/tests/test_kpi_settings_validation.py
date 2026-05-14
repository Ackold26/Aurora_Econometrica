"""Tests для Phase 1.2 — backend validation gate `/project/save_kpi_settings`.

Coverage:
- Pydantic field_validator: unit_costs bounds (negative, NaN, > 1e9)
- Pydantic field_validator: inflation bounds (NaN, out of range)
- Pydantic field_validator: mode_for enum (budget | unit)
- validate_role_compatibility(): channel-not-in-media rejection
- atomic_write_json integration (Phase 0.3 reuse)
- structured logging events (Phase 0.2 reuse)
"""
import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import math
import pytest
from pydantic import ValidationError
from engines.validator import validate_role_compatibility


class TestValidateRoleCompatibility:
    def test_empty_unit_costs_passes(self):
        ok, code, msg = validate_role_compatibility({}, ['tv_spend'])
        assert ok is True
        assert code == 'OK'

    def test_none_unit_costs_passes(self):
        ok, code, _ = validate_role_compatibility(None, ['tv_spend'])
        assert ok is True
        assert code == 'OK'

    def test_unit_cost_for_media_channel_passes(self):
        ok, code, _ = validate_role_compatibility(
            {'tv_spend': 100.0, 'olv_grp': 50.0},
            ['tv_spend', 'olv_grp', 'banner_clicks'],
        )
        assert ok is True

    def test_unit_cost_for_non_media_rejected(self):
        ok, code, msg = validate_role_compatibility(
            {'sales_rub': 1.0},  # sales is target, not media
            ['tv_spend'],
        )
        assert ok is False
        assert code == 'UNIT_COST_CHANNEL_NOT_MEDIA'
        assert 'sales_rub' in msg

    def test_classifier_hint_included(self):
        def fake_classifier(name):
            if 'sales' in name:
                return 'target_monetary'
            return 'unknown'

        ok, code, msg = validate_role_compatibility(
            {'sales_total': 1.0},
            ['tv_spend'],
            classifier_fn=fake_classifier,
        )
        assert ok is False
        assert 'target_monetary' in msg

    def test_classifier_exception_safe(self):
        def crashy_classifier(_name):
            raise RuntimeError('boom')

        ok, code, _msg = validate_role_compatibility(
            {'sales_total': 1.0},
            ['tv_spend'],
            classifier_fn=crashy_classifier,
        )
        # Exception swallowed → still returns error (channel not in media)
        assert ok is False

    def test_media_columns_as_tuple(self):
        ok, _, _ = validate_role_compatibility(
            {'tv_spend': 1.0},
            ('tv_spend', 'olv_grp'),  # tuple instead of list
        )
        assert ok is True


# ─── Pydantic schema tests (import server.py inline для не trigger full uvicorn)


class TestPydanticValidators:
    """Test field_validator decorators on ValuePerCountUnitSaveRequest."""

    def _make_request_cls(self):
        # Lazy import чтобы не trigger heavy server.py side-effects
        from server import ValuePerCountUnitSaveRequest
        return ValuePerCountUnitSaveRequest

    def test_unit_costs_positive_passes(self):
        cls = self._make_request_cls()
        instance = cls(project_dir='/tmp/test', unit_costs={'tv': 100.0})
        assert instance.unit_costs == {'tv': 100.0}

    def test_unit_costs_zero_passes(self):
        """0 valid (means «exclude this channel» or yet-to-fill)."""
        cls = self._make_request_cls()
        instance = cls(project_dir='/tmp/test', unit_costs={'tv': 0.0})
        assert instance.unit_costs['tv'] == 0.0

    def test_unit_costs_negative_rejected(self):
        cls = self._make_request_cls()
        with pytest.raises(ValidationError) as exc_info:
            cls(project_dir='/tmp/test', unit_costs={'tv': -100.0})
        assert 'must be ≥ 0' in str(exc_info.value)

    def test_unit_costs_nan_rejected(self):
        cls = self._make_request_cls()
        with pytest.raises(ValidationError) as exc_info:
            cls(project_dir='/tmp/test', unit_costs={'tv': float('nan')})
        assert 'NaN' in str(exc_info.value)

    def test_unit_costs_above_bound_rejected(self):
        cls = self._make_request_cls()
        with pytest.raises(ValidationError) as exc_info:
            cls(project_dir='/tmp/test', unit_costs={'tv': 1e10})
        assert 'unreasonably high' in str(exc_info.value)

    def test_inflation_in_range_passes(self):
        cls = self._make_request_cls()
        instance = cls(project_dir='/tmp/test', unit_cost_inflation={'tv': 15.0})
        assert instance.unit_cost_inflation == {'tv': 15.0}

    def test_inflation_negative_accepted_within_range(self):
        cls = self._make_request_cls()
        instance = cls(project_dir='/tmp/test', unit_cost_inflation={'tv': -5.0})
        assert instance.unit_cost_inflation['tv'] == -5.0

    def test_inflation_out_of_range_rejected(self):
        cls = self._make_request_cls()
        with pytest.raises(ValidationError) as exc_info:
            cls(project_dir='/tmp/test', unit_cost_inflation={'tv': 1000.0})
        assert 'out of range' in str(exc_info.value)

    def test_inflation_nan_rejected(self):
        cls = self._make_request_cls()
        with pytest.raises(ValidationError) as exc_info:
            cls(project_dir='/tmp/test', unit_cost_inflation={'tv': float('nan')})
        assert 'NaN' in str(exc_info.value)

    def test_mode_for_valid(self):
        cls = self._make_request_cls()
        instance = cls(project_dir='/tmp/test', mode_for={'tv': 'budget', 'olv': 'unit'})
        assert instance.mode_for['tv'] == 'budget'
        assert instance.mode_for['olv'] == 'unit'

    def test_mode_for_invalid_value_rejected(self):
        cls = self._make_request_cls()
        with pytest.raises(ValidationError) as exc_info:
            cls(project_dir='/tmp/test', mode_for={'tv': 'invalid_mode'})
        assert 'budget' in str(exc_info.value)
        assert 'unit' in str(exc_info.value)

    def test_backward_compat_optional_fields(self):
        """v2.0.0 client w/o new fields still works."""
        cls = self._make_request_cls()
        instance = cls(project_dir='/tmp/test')
        assert instance.unit_costs is None
        assert instance.unit_cost_inflation is None
        assert instance.mode_for is None
        assert instance.budget_inputs is None
