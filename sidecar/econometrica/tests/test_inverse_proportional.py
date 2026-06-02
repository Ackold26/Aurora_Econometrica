"""3C GS-1 (2026-06-02): proportional forward в Goal-Seek.

Корень: старый _forward_at_budget (re-optimize per budget) ронял UNIT_SMELL на
не-денежных каналах → _verify_monotonicity маскировал под non_monotonic_forward.
Proportional forward монотонен по построению и обрабатывает unit_costs напрямую.

Тесты проброса forward_fn через bisect/verify + честный unachievable (НЕ ложный
non_monotonic). Реальная интеграция на Кагоцел проверена live-probe (см. STEP0/память).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from optimize import inverse  # noqa: E402


def _mono(slope: float, baseline: float = 0.0):
    """Монотонный forward: S(B) = baseline + slope*B."""
    return lambda B: {
        'expected_sales': baseline + slope * B,
        'distribution': {'A': B},
        'status': 'ok',
    }


def test_bisect_finds_budget_with_proportional_forward():
    fwd = _mono(slope=2.0)  # S = 2B → target 200 → B = 100
    r = inverse.bisect_for_target(
        'x', target_sales=200.0, budget_lo=0.0, budget_hi=1000.0, forward_fn=fwd,
    )
    assert r['achievable'] is True
    assert abs(r['budget'] - 100.0) < 5.0
    assert abs(r['expected_sales'] - 200.0) < 10.0


def test_bisect_unachievable_is_honest_not_nonmonotonic():
    fwd = _mono(slope=1.0)  # max при hi=100 → 100, target 500 недостижим
    r = inverse.bisect_for_target(
        'x', target_sales=500.0, budget_lo=0.0, budget_hi=100.0, forward_fn=fwd,
    )
    assert r['achievable'] is False
    # ключевое: честный fallback, НЕ ложный non_monotonic_forward
    assert r.get('error') != 'non_monotonic_forward'
    assert r.get('fallback_max_sales') is not None
    assert abs(r['fallback_max_sales'] - 100.0) < 1.0


def test_verify_monotonicity_threads_forward_fn():
    assert inverse._verify_monotonicity(_mono(1.0), 0.0, 100.0)['monotonic'] is True

    def nonmono(B):
        return {'expected_sales': -((B - 50.0) ** 2), 'distribution': {}, 'status': 'ok'}

    assert inverse._verify_monotonicity(nonmono, 0.0, 100.0)['monotonic'] is False


def test_verify_monotonicity_forward_error_flagged():
    def err(_B):
        return {'expected_sales': 0.0, 'distribution': {}, 'status': 'error'}

    res = inverse._verify_monotonicity(err, 0.0, 100.0)
    assert res['monotonic'] is False
    assert res.get('error') is True


def test_estimate_budget_ci_uses_forward_fn():
    # Линейный forward → ненулевой градиент → method 'delta', не flat.
    ci = inverse.estimate_budget_ci('x', 100.0, 200.0, forward_fn=_mono(2.0))
    assert ci['method'] == 'delta'
    assert ci['p10'] <= ci['p50'] <= ci['p90']


def test_estimate_budget_ci_flat_response_marker():
    # Плоский forward (градиент ≈ 0) → flat_response_fallback (#59 сохранён).
    flat = lambda B: {'expected_sales': 1000.0, 'distribution': {}, 'status': 'ok'}
    ci = inverse.estimate_budget_ci('x', 100.0, 1000.0, forward_fn=flat)
    assert ci['method'] == 'flat_response_fallback'
