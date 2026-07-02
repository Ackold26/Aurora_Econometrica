"""Hill numerics — характеризующие тесты мат-аудита 2026-07-02 (F-09).

До правки x**alpha переполнялся при x ≳ 1e154 (alpha=2) → inf/inf = NaN тихо
уплывал через sanitize_nonfinite в JSON как null. Теперь — честный
математический предел: hill(x→∞)=1.0, hill'(x→∞)=0.0. Формула на нормальном
диапазоне НЕ изменена (byte-exact против прямой формулы — pin-регрессии целы);
NaN-вход не маскируется.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.saturation import (  # noqa: E402
    hill_derivative_batch,
    hill_function,
    hill_function_batch,
    hill_function_batch_2d,
)


def test_overflow_limit_is_one_not_nan():
    """x за порогом переполнения float64 → предел 1.0, не NaN."""
    for x, a in [(1e155, 2.0), (1e308, 2.0), (1e120, 3.0)]:
        r = hill_function(np.array([x]), alpha=a, gamma=0.5)
        assert np.isfinite(r[0]), f'hill({x:g}, a={a}) = {r[0]!r} (ожидали 1.0)'
        assert r[0] == pytest.approx(1.0)


def test_normal_range_byte_exact_vs_direct_formula():
    """На рабочем диапазоне числа НЕ изменились ни на бит (та же формула)."""
    x = np.array([0.0, 1e-6, 0.1, 0.5, 1.0, 1.078, 2.0, 10.0, 1e3, 1e6])
    for a, g in [(0.8, 0.4), (1.0, 0.5), (1.5, 0.4), (2.0, 0.6), (3.0, 1.2)]:
        expected = np.maximum(x, 0.0) ** a / (np.maximum(x, 0.0) ** a + max(g, 1e-10) ** a)
        got = hill_function(x, alpha=a, gamma=g)
        assert np.array_equal(got, expected), f'drift формулы при a={a}, g={g}'


def test_nan_input_not_masked():
    """NaN на входе остаётся NaN (не превращаем проблему данных в 1.0)."""
    r = hill_function(np.array([np.nan]), alpha=1.5, gamma=0.5)
    assert np.isnan(r[0])


def test_batch_variants_overflow_limits():
    """batch / batch_2d → 1.0; derivative → 0.0 на переполнении."""
    alphas = np.array([2.0, 3.0])
    gammas = np.array([0.5, 0.6])

    sat = hill_function_batch(np.array([1e200, 1.0]), alphas, gammas)
    assert np.all(np.isfinite(sat))
    assert sat[0, 0] == pytest.approx(1.0)
    assert sat[1, 0] == pytest.approx(1.0)

    sat2d = hill_function_batch_2d(np.array([[1e200, 1.0], [1e200, 2.0]]), alphas, gammas)
    assert np.all(np.isfinite(sat2d))
    assert sat2d[0, 0] == pytest.approx(1.0)

    der = hill_derivative_batch(np.array([1e200, 1.0]), alphas, gammas)
    assert np.all(np.isfinite(der))
    assert der[0, 0] == pytest.approx(0.0)
    assert der[0, 1] > 0  # нормальная точка — производная положительна


def test_derivative_normal_range_unchanged():
    """Производная на рабочем диапазоне совпадает с прямой формулой."""
    x = np.array([0.1, 0.5, 1.0, 2.0])
    a, g = 1.5, 0.4
    x_s = np.maximum(x, 1e-10)
    expected = (a * g ** a * x_s ** (a - 1.0)) / (x_s ** a + g ** a) ** 2
    got = hill_derivative_batch(x, np.array([a]), np.array([g]))
    assert np.allclose(got[0], expected, rtol=0, atol=0), 'drift формулы производной'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
