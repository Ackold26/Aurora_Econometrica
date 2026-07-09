"""Тесты carry-in функционала для geometric adstock.

Покрывают:
- compute_geometric_carry_in: ненулевая история → carry_in > 0; пустая → 0
- geometric_adstock_with_carryin: обратная совместимость при carry_in=0; первый период выше
- затухание при нулевых будущих тратах: A[t] ≈ carry * alpha^t
- batch: регрессия carry_in=None == старое поведение; с carry_in первый столбец выше
- согласованность линии и веера (A2): batch[decays=[alpha]] ≈ точечный with_carryin
- apply_adstock_with_carryin: нет истории → fallback без carry; weibull → fallback + warning; geometric → с carry
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.adstock import (
    apply_adstock,
    apply_adstock_with_carryin,
    compute_geometric_carry_in,
    compute_geometric_carry_in_batch,
    geometric_adstock,
    geometric_adstock_batch,
    geometric_adstock_with_carryin,
)


# ---------------------------------------------------------------------------
# compute_geometric_carry_in
# ---------------------------------------------------------------------------

def test_carry_in_positive_for_nonzero_history():
    """Ненулевая история → carry_in > 0."""
    x_hist = np.array([100.0, 80.0, 60.0])
    alpha = 0.7
    ci = compute_geometric_carry_in(x_hist, alpha)
    assert ci > 0.0, f"Expected positive carry_in, got {ci}"


def test_carry_in_zero_for_empty_history():
    """Пустая история → carry_in == 0.0."""
    ci = compute_geometric_carry_in(np.array([]), 0.7)
    assert ci == 0.0


def test_carry_in_formula():
    """carry_in = alpha * adstock_last, формула соответствует рекуррентному geometric."""
    x_hist = np.array([50.0, 100.0, 80.0])
    alpha = 0.6
    adstock_hist = geometric_adstock(x_hist, alpha)
    expected = alpha * adstock_hist[-1]
    ci = compute_geometric_carry_in(x_hist, alpha)
    np.testing.assert_allclose(ci, expected, rtol=1e-10)


# ---------------------------------------------------------------------------
# geometric_adstock_with_carryin — обратная совместимость
# ---------------------------------------------------------------------------

def test_with_carryin_zero_equals_plain():
    """carry_in=0.0 → результат байт-в-байт совпадает с geometric_adstock."""
    x = np.array([10.0, 20.0, 15.0, 5.0])
    alpha = 0.5
    plain = geometric_adstock(x, alpha)
    with_ci = geometric_adstock_with_carryin(x, alpha, carry_in=0.0)
    np.testing.assert_allclose(with_ci, plain, rtol=1e-12)


def test_with_carryin_default_zero_equals_plain():
    """carry_in=0.0 — значение по умолчанию, совпадает с plain."""
    x = np.array([30.0, 10.0, 5.0])
    alpha = 0.8
    np.testing.assert_allclose(
        geometric_adstock_with_carryin(x, alpha),
        geometric_adstock(x, alpha),
        rtol=1e-12,
    )


# ---------------------------------------------------------------------------
# geometric_adstock_with_carryin — первый период выше
# ---------------------------------------------------------------------------

def test_first_period_higher_with_carry():
    """При alpha=0.7, ненулевой истории — первый будущий период с carry ВЫШЕ, чем без."""
    x_hist = np.array([100.0, 90.0, 80.0])
    x_future = np.array([50.0, 40.0, 30.0])
    alpha = 0.7
    carry_in = compute_geometric_carry_in(x_hist, alpha)
    assert carry_in > 0, "carry_in должен быть > 0"

    plain = geometric_adstock(x_future, alpha)
    with_carry = geometric_adstock_with_carryin(x_future, alpha, carry_in)

    assert with_carry[0] > plain[0], (
        f"Первый период с carry ({with_carry[0]:.4f}) должен быть выше без carry ({plain[0]:.4f})"
    )


# ---------------------------------------------------------------------------
# Затухание при нулевых будущих тратах
# ---------------------------------------------------------------------------

def test_decay_zeros_future_with_carry():
    """При x_future = zeros, carry > 0 → A[t] ≈ carry * alpha^t."""
    x_hist = np.array([100.0, 100.0, 100.0, 100.0])
    alpha = 0.6
    carry_in = compute_geometric_carry_in(x_hist, alpha)
    assert carry_in > 0

    T = 5
    x_future = np.zeros(T)
    result = geometric_adstock_with_carryin(x_future, alpha, carry_in)

    expected = np.array([carry_in * (alpha ** t) for t in range(T)])
    np.testing.assert_allclose(result, expected, rtol=1e-10,
                               err_msg="Затухание при нулевых тратах должно быть carry * alpha^t")


# ---------------------------------------------------------------------------
# Нет истории → carry_in=0 → диспетчер == apply_adstock
# ---------------------------------------------------------------------------

def test_no_history_dispatcher_equals_apply_adstock():
    """x_hist=[] → apply_adstock_with_carryin совпадает с apply_adstock."""
    x_future = np.array([10.0, 20.0, 15.0])
    params = {'alpha': 0.6}
    result_dispatcher = apply_adstock_with_carryin(x_future, 'geometric', params, x_hist=None)
    result_plain = apply_adstock(x_future, 'geometric', params)
    np.testing.assert_allclose(result_dispatcher, result_plain, rtol=1e-12)


def test_empty_list_history_dispatcher_equals_apply_adstock():
    """x_hist=[] (пустой список) → то же самое."""
    x_future = np.array([5.0, 10.0])
    params = {'alpha': 0.5}
    result_dispatcher = apply_adstock_with_carryin(x_future, 'geometric', params, x_hist=[])
    result_plain = apply_adstock(x_future, 'geometric', params)
    np.testing.assert_allclose(result_dispatcher, result_plain, rtol=1e-12)


# ---------------------------------------------------------------------------
# Batch: регрессия carry_in=None == старое поведение
# ---------------------------------------------------------------------------

def test_batch_regression_no_carry():
    """geometric_adstock_batch(x, decays, carry_in=None) == старое поведение."""
    x = np.array([10.0, 20.0, 30.0])
    decays = np.array([0.3, 0.5, 0.7])
    old = geometric_adstock_batch(x, decays)
    new = geometric_adstock_batch(x, decays, carry_in=None)
    np.testing.assert_allclose(new, old, rtol=1e-12)


def test_batch_with_carry_first_col_higher():
    """С carry_in > 0 первый столбец batch выше, чем без carry."""
    x_hist = np.array([100.0, 90.0, 80.0])
    x_future = np.array([50.0, 40.0])
    decays = np.array([0.5, 0.7, 0.9])

    carry_arr = compute_geometric_carry_in_batch(x_hist, decays)
    assert np.all(carry_arr > 0), "Все carry_in должны быть > 0"

    batch_no_carry = geometric_adstock_batch(x_future, decays)
    batch_with_carry = geometric_adstock_batch(x_future, decays, carry_in=carry_arr)

    # Первый столбец у всех сэмплов выше
    assert np.all(batch_with_carry[:, 0] > batch_no_carry[:, 0]), (
        "Первый столбец batch с carry должен быть выше без carry"
    )


# ---------------------------------------------------------------------------
# A2: согласованность линии и веера
# ---------------------------------------------------------------------------

def test_batch_single_decay_matches_pointwise():
    """Среднее batch[decays=[alpha]] ≈ точечный with_carryin при том же alpha (A2)."""
    x_hist = np.array([80.0, 90.0, 100.0, 90.0, 80.0])
    x_future = np.array([60.0, 50.0, 40.0])
    alpha = 0.65

    carry_point = compute_geometric_carry_in(x_hist, alpha)
    pointwise = geometric_adstock_with_carryin(x_future, alpha, carry_point)

    decays_single = np.array([alpha])
    carry_batch = compute_geometric_carry_in_batch(x_hist, decays_single)
    batch = geometric_adstock_batch(x_future, decays_single, carry_in=carry_batch)
    # batch[0, :] должен совпасть с точечным
    np.testing.assert_allclose(batch[0], pointwise, rtol=1e-10,
                               err_msg="Линия (точечная) и веер (batch) должны совпадать при одном сэмпле")


# ---------------------------------------------------------------------------
# compute_geometric_carry_in_batch
# ---------------------------------------------------------------------------

def test_carry_in_batch_empty_history():
    """Пустая история → compute_geometric_carry_in_batch возвращает zeros."""
    decays = np.array([0.3, 0.6, 0.9])
    result = compute_geometric_carry_in_batch(np.array([]), decays)
    np.testing.assert_array_equal(result, np.zeros(3))


def test_carry_in_batch_shape():
    """Форма результата (n_samples,)."""
    x_hist = np.array([10.0, 20.0])
    decays = np.linspace(0.1, 0.9, 7)
    result = compute_geometric_carry_in_batch(x_hist, decays)
    assert result.shape == (7,)


def test_carry_in_batch_consistent_with_pointwise():
    """Каждый элемент batch соответствует точечному compute_geometric_carry_in."""
    x_hist = np.array([50.0, 70.0, 60.0])
    decays = np.array([0.3, 0.5, 0.7, 0.9])
    batch_ci = compute_geometric_carry_in_batch(x_hist, decays)
    for i, alpha in enumerate(decays):
        point_ci = compute_geometric_carry_in(x_hist, alpha)
        np.testing.assert_allclose(batch_ci[i], point_ci, rtol=1e-10,
                                   err_msg=f"Несоответствие при alpha={alpha}")


# ---------------------------------------------------------------------------
# Weibull через диспетчер — не падает, возвращает обычный adstock (fallback)
# ---------------------------------------------------------------------------

def test_weibull_dispatcher_no_crash_returns_adstock():
    """apply_adstock_with_carryin с weibull не падает, возвращает apply_adstock без carry."""
    x_hist = np.array([100.0, 80.0, 60.0])
    x_future = np.array([50.0, 40.0, 30.0])
    params = {'shape': 2.0, 'scale': 3.0}

    import logging
    # Очистим guard-set чтобы warning точно сработал
    from utils import adstock as adstock_mod
    adstock_mod._warned_unknown_types.discard('weibull')

    with warnings.catch_warnings(record=True):
        warnings.simplefilter('always')
        result = apply_adstock_with_carryin(x_future, 'weibull', params, x_hist=x_hist)

    expected = apply_adstock(x_future, 'weibull', params)
    np.testing.assert_allclose(result, expected, rtol=1e-12,
                               err_msg="Weibull fallback должен совпадать с apply_adstock")


def test_weibull_dispatcher_warning_logged(caplog):
    """apply_adstock_with_carryin с weibull логирует warning."""
    import logging
    from utils import adstock as adstock_mod
    adstock_mod._warned_unknown_types.discard('weibull')

    x_hist = np.array([100.0, 80.0])
    x_future = np.array([50.0, 40.0])

    with caplog.at_level(logging.WARNING, logger='utils.adstock'):
        apply_adstock_with_carryin(x_future, 'weibull', {'shape': 2.0, 'scale': 3.0}, x_hist=x_hist)

    assert any('weibull' in rec.message.lower() for rec in caplog.records), (
        "Должен быть warning про weibull carry-in"
    )


# ---------------------------------------------------------------------------
# apply_adstock_with_carryin — geometric с историей
# ---------------------------------------------------------------------------

def test_dispatcher_geometric_with_history_higher_first():
    """Диспетчер geometric с историей → первый период выше, чем без carry."""
    x_hist = np.array([100.0, 90.0, 80.0, 70.0])
    x_future = np.array([60.0, 50.0, 40.0])
    params = {'alpha': 0.7}

    result_with = apply_adstock_with_carryin(x_future, 'geometric', params, x_hist=x_hist)
    result_plain = apply_adstock(x_future, 'geometric', params)

    assert result_with[0] > result_plain[0], (
        f"Первый период диспетчера с carry ({result_with[0]:.4f}) должен быть выше без ({result_plain[0]:.4f})"
    )
