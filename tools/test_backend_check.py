"""Tests для utils/backend_check.py — Phase B0.3 foundation."""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

from utils.backend_check import (
    BackendUnavailableError,
    enforce_jax_for_weibull,
    get_backend_summary,
    is_jax_available,
    is_pymc_available,
)


def test_is_pymc_available_returns_bool():
    assert isinstance(is_pymc_available(), bool)


def test_is_jax_available_returns_bool():
    assert isinstance(is_jax_available(), bool)


def test_get_backend_summary_returns_all_keys():
    summary = get_backend_summary()
    assert 'pymc' in summary
    assert 'jax' in summary
    assert 'numpyro' in summary


def test_enforce_no_op_when_all_geometric():
    """Все channels geometric → no error даже если JAX недоступен."""
    types = {'TV': 'geometric', 'Digital': 'geometric'}
    enforce_jax_for_weibull(types)  # no error


def test_enforce_no_op_when_empty():
    enforce_jax_for_weibull({})  # no channels


def test_enforce_passes_when_jax_available_and_weibull_present(monkeypatch):
    """Если JAX доступен → Weibull channels не trigger error."""
    monkeypatch.setattr('utils.backend_check.is_jax_available', lambda: True)
    types = {'TV': 'weibull', 'Digital': 'geometric'}
    enforce_jax_for_weibull(types)  # no error


def test_enforce_raises_when_weibull_without_jax(monkeypatch):
    """Mock JAX missing + Weibull channel → BackendUnavailableError."""
    monkeypatch.setattr('utils.backend_check.is_jax_available', lambda: False)
    types = {'TV': 'weibull', 'Digital': 'geometric'}
    with pytest.raises(BackendUnavailableError, match='Weibull learnable'):
        enforce_jax_for_weibull(types)


def test_enforce_error_lists_offending_channels(monkeypatch):
    """Error message contains list channels с Weibull."""
    monkeypatch.setattr('utils.backend_check.is_jax_available', lambda: False)
    types = {'TV': 'weibull', 'OOH': 'weibull', 'Digital': 'geometric'}
    with pytest.raises(BackendUnavailableError) as exc:
        enforce_jax_for_weibull(types)
    assert 'TV' in str(exc.value)
    assert 'OOH' in str(exc.value)


def test_backend_unavailable_error_is_runtime_error():
    """BackendUnavailableError должен быть RuntimeError для compat."""
    assert issubclass(BackendUnavailableError, RuntimeError)
