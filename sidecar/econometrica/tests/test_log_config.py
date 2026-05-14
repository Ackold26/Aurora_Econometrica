"""Tests для utils/log_config.py — Phase 0.2."""
import json
import logging
import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import pytest
from utils.log_config import (
    JsonFormatter,
    configure_structured_logging,
    setup_module_logger,
    log_event,
)


class TestJsonFormatter:
    def test_basic_format(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name='econometrica.validator',
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg='test message',
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        payload = json.loads(output)
        assert payload['msg'] == 'test message'
        assert payload['level'] == 'INFO'
        assert payload['logger'] == 'econometrica.validator'
        assert 'ts' in payload

    def test_extra_fields_included(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name='econometrica.test',
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg='custom',
            args=(),
            exc_info=None,
        )
        record.event = 'unit_cost_rejected'
        record.channel = 'TRPs бренд'
        record.value = -100
        output = formatter.format(record)
        payload = json.loads(output)
        assert payload['event'] == 'unit_cost_rejected'
        assert payload['channel'] == 'TRPs бренд'
        assert payload['value'] == -100

    def test_non_serializable_extra_repr_fallback(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name='econometrica.test',
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg='custom',
            args=(),
            exc_info=None,
        )
        record.weird = object()
        output = formatter.format(record)
        payload = json.loads(output)
        assert 'object' in payload['weird']

    def test_exception_info_included(self):
        formatter = JsonFormatter()
        try:
            raise ValueError('boom')
        except ValueError:
            record = logging.LogRecord(
                name='econometrica.test',
                level=logging.ERROR,
                pathname=__file__,
                lineno=10,
                msg='failed',
                args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        payload = json.loads(output)
        assert 'exc_info' in payload
        assert 'ValueError' in payload['exc_info']


class TestSetupModuleLogger:
    def test_returns_child_logger(self):
        logger = setup_module_logger('engines.validator')
        assert logger.name == 'econometrica.validator'

    def test_dunder_name_module_handled(self):
        # When called as setup_module_logger(__name__) e.g. 'sidecar.econometrica.utils.log_config'
        logger = setup_module_logger('sidecar.econometrica.utils.log_config')
        assert logger.name == 'econometrica.log_config'


class TestLogEvent:
    def test_log_event_includes_structured_fields(self, caplog):
        logger = logging.getLogger('econometrica.test_log_event')
        with caplog.at_level(logging.INFO, logger='econometrica.test_log_event'):
            log_event(logger, 'kpi_validated', project_id='proj-1', channels=6)
        record = caplog.records[-1]
        assert record.getMessage() == 'kpi_validated'
        assert record.event == 'kpi_validated'
        assert record.project_id == 'proj-1'
        assert record.channels == 6


class TestConfigureStructuredLogging:
    def test_idempotent(self):
        # Calling twice should not duplicate handlers
        root = logging.getLogger('econometrica')
        # Clear potential prior state
        root._aurora_structured_configured = False  # type: ignore[attr-defined]
        # Strip handlers added by other tests/sidecar startup
        original_handlers = list(root.handlers)
        for h in original_handlers:
            root.removeHandler(h)
        try:
            configure_structured_logging(enable_json_file=False, enable_console=True)
            n_after_first = len(root.handlers)
            configure_structured_logging(enable_json_file=False, enable_console=True)
            n_after_second = len(root.handlers)
            assert n_after_first == n_after_second, 'should be idempotent'
        finally:
            # Restore original state
            for h in list(root.handlers):
                root.removeHandler(h)
            for h in original_handlers:
                root.addHandler(h)
            root._aurora_structured_configured = False  # type: ignore[attr-defined]
