"""Centralized structured logging config — Phase 0.2.

Existing server.py имеет basic logging (logger = logging.getLogger('econometrica')
+ ~55 calls). Этот модуль добавляет:

1. JSON formatter (one event per line) — observability-friendly
2. Rotating file handler — writes к %LOCALAPPDATA%/aurora-econometrica-gui/logs/
3. structured_log(event, **fields) helper — standard event vocabulary
4. Per-module child loggers via setup_module_logger(__name__)

Used by Phase 1+ code для consistent audit trail (validation rejections,
migration events, classifier cache decisions, JCS hash mismatches).
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format records as one-line JSON для machine-readable logs."""

    def _iso_ts(self, record: logging.LogRecord) -> str:
        """ISO-8601 timestamp с milliseconds (Windows strftime не поддерживает %f)."""
        base = self.formatTime(record, datefmt='%Y-%m-%dT%H:%M:%S')
        return f'{base}.{int(record.msecs):03d}'

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'ts': self._iso_ts(record),
            'level': record.levelname,
            'logger': record.name,
            'msg': record.getMessage(),
        }
        # Include structured fields passed via extra={'event': ..., ...}
        for key, value in record.__dict__.items():
            if key.startswith('_') or key in {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                'thread', 'threadName', 'processName', 'process', 'message',
            }:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _resolve_log_dir() -> Path:
    """%LOCALAPPDATA%/aurora-econometrica-gui/logs/ (matches sidecar identifier)."""
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or str(Path.home())
    else:
        base = os.environ.get('XDG_STATE_HOME') or str(Path.home() / '.local' / 'state')
    log_dir = Path(base) / 'aurora-econometrica-gui' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def configure_structured_logging(
    level: int = logging.INFO,
    *,
    enable_json_file: bool = True,
    enable_console: bool = True,
) -> None:
    """Idempotent setup для root «econometrica» logger.

    Call once at sidecar startup. Adds JSON file handler + console handler.
    Existing handlers preserved (safe to call after basic setup в server.py).
    """
    root = logging.getLogger('econometrica')
    if getattr(root, '_aurora_structured_configured', False):
        return
    root.setLevel(level)

    if enable_json_file:
        log_path = _resolve_log_dir() / 'sidecar.json.log'
        json_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8',
        )
        json_handler.setFormatter(JsonFormatter())
        root.addHandler(json_handler)

    if enable_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(JsonFormatter())
        # Don't double-add console если existing setup
        if not any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            for h in root.handlers
        ):
            root.addHandler(console_handler)

    root._aurora_structured_configured = True  # type: ignore[attr-defined]


def setup_module_logger(module_name: str) -> logging.Logger:
    """Get child logger для конкретного модуля.

    Use в Phase 1+ modules вместо stand-alone logging.getLogger:
        from utils.log_config import setup_module_logger
        logger = setup_module_logger(__name__)
        logger.info('validation_rejected', extra={'event': 'unit_cost_rejected', 'channel': 'TRP'})
    """
    # Strip к last segment если passed __name__ (e.g. 'engines.validator')
    short = module_name.rsplit('.', 1)[-1]
    return logging.getLogger(f'econometrica.{short}')


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Helper для consistent event logging.

    Example:
        log_event(logger, 'kpi_settings_validated', project_id=pid, channels=6)
    """
    logger.log(level, event, extra={'event': event, **fields})
