"""
Aurora Econometrica — inverse optimization (Goal-Seek) v1.3.0.

Per ADR-014, REFACTOR_PLAN_v1.3.0.md Stage 1 P0.2 (simplified to bisection):
дана цель продаж S* → найти минимальный бюджет B такой что S(B) ≥ S*.

Algorithm: бисекция по total budget. Forward задача монотонна по B
(в безопасном коридоре), bisection ищет минимальный B где expected_sales >= target.

Posterior CI на B* — Delta method (linearization): B_ci_half = std(S_target) / |∂S/∂B|.

Performance budget: < 1s на 7 каналов × 156 наблюдений (per docs/PERFORMANCE_BUDGET.md).

Usage:
    from optimize.inverse import optimize_inverse

    result = optimize_inverse(
        project_dir='/path/to/project',
        target_sales=1.05e8,        # ₽ для monetary, count для count KPI
        kpi_kind='monetary',
        mode='roi',                  # для logging / tracking, optimizer не использует
    )
    # {
    #   'achievable': True,
    #   'total_budget': {'p10': X, 'p50': Y, 'p90': Z},
    #   'distribution': {channel: budget},
    #   'delta_vs_current': 0.12,
    #   'p_hit_target': 0.78,
    #   'iterations': 12,
    # }
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

# Lazy imports — heavy modules (PyMC, scipy) не нужны на startup.
# Engineering invariant per docs/PERFORMANCE_BUDGET.md.


def _forward_at_budget(project_dir: str, total_budget: float) -> Dict[str, Any]:
    """Run forward optimizer at fixed total_budget.

    Wrapper around engines.optimizer.optimize() — задает scalar budget
    и возвращает expected_sales + distribution.

    Returns:
        {'expected_sales': float, 'distribution': {channel: budget}, 'status': 'ok'|'error'}
    """
    from engines.optimizer import optimize
    config = {
        'total_budget': total_budget,
        'min_pct': 0.0,    # Не ограничиваем per канал — global free reallocation.
        'max_pct': 1000.0,  # Effectively unlimited (canal can absorb full budget).
    }
    raw_result = optimize(config, project_dir)

    if raw_result.get('status') == 'error':
        return {
            'expected_sales': 0.0,
            'distribution': {},
            'status': 'error',
            'error_message': raw_result.get('message', 'Forward optimize failed'),
        }

    # Extract expected sales и распределение из raw_result.
    # Структура `optimize()` returns:
    # {
    #   'optimal': {'sales': float, 'allocation': {channel: spend}, ...},
    #   ...
    # }
    optimal = raw_result.get('optimal', {})
    return {
        'expected_sales': float(optimal.get('sales', 0.0)),
        'distribution': dict(optimal.get('allocation', {})),
        'status': 'ok',
    }


def bisect_for_target(
    project_dir: str,
    target_sales: float,
    budget_lo: float,
    budget_hi: float,
    rel_tol: float = 1e-3,
    max_iters: int = 30,
) -> Dict[str, Any]:
    """Bisection: find minimum total_budget B such that expected_sales(B) ≥ target_sales.

    Args:
        project_dir: Path to project.
        target_sales: целевая величина продаж (₽ или count units).
        budget_lo: нижняя граница (обычно 0 или corridor_lo).
        budget_hi: верхняя граница (обычно corridor_hi).
        rel_tol: tolerance относительно (hi - lo).
        max_iters: max iterations (защита от non-convergence).

    Returns:
        {
          'budget': float,        # B* — минимальный budget для достижения target
          'expected_sales': float, # S(B*) — ожидаемые продажи
          'achievable': bool,
          'iterations': int,
          'distribution': dict,   # final allocation
        }
    """
    # Sanity check: forward at hi должен достичь target.
    forward_hi = _forward_at_budget(project_dir, budget_hi)
    if forward_hi['status'] == 'error':
        return {
            'achievable': False,
            'error': forward_hi.get('error_message', 'Forward at hi failed'),
            'iterations': 0,
        }

    if forward_hi['expected_sales'] < target_sales:
        return {
            'achievable': False,
            'fallback_max_sales': forward_hi['expected_sales'],
            'fallback_budget': budget_hi,
            'iterations': 1,
            'message': (
                f'Цель {target_sales:.0f} недостижима в безопасном коридоре. '
                f'Максимум при upper corridor: {forward_hi["expected_sales"]:.0f}'
            ),
        }

    # Bisection loop.
    iters = 1  # уже сделали 1 forward (at hi).
    lo = budget_lo
    hi = budget_hi
    best_budget = budget_hi
    best_sales = forward_hi['expected_sales']
    best_distribution = forward_hi['distribution']

    while (hi - lo) > rel_tol * max(hi, 1.0) and iters < max_iters:
        mid = 0.5 * (lo + hi)
        forward_mid = _forward_at_budget(project_dir, mid)
        iters += 1

        if forward_mid['status'] == 'error':
            # Fallback to last valid solution.
            break

        if forward_mid['expected_sales'] >= target_sales:
            # Mid достаточно → уменьшаем budget.
            hi = mid
            best_budget = mid
            best_sales = forward_mid['expected_sales']
            best_distribution = forward_mid['distribution']
        else:
            # Mid не достаточно → увеличиваем budget.
            lo = mid

    return {
        'achievable': True,
        'budget': best_budget,
        'expected_sales': best_sales,
        'distribution': best_distribution,
        'iterations': iters,
    }


def estimate_budget_ci(
    project_dir: str,
    budget_optimum: float,
    target_sales: float,
    delta_pct: float = 0.05,
) -> Dict[str, float]:
    """Estimate posterior CI на budget через Delta method (linearization).

    Идея:
    - Локальный gradient: ∂S/∂B ≈ (S(B + δ) - S(B - δ)) / (2δ).
    - Posterior std на S(B*) — приближаем через 1-2 forward passes на B ± δ.
    - B_ci_half_width ≈ S_std / |∂S/∂B|.

    MVP — простая Delta method. Phase B: full posterior re-bisection.

    Returns:
        {'p10': float, 'p50': budget_optimum, 'p90': float, 'method': 'delta'}
    """
    delta = max(delta_pct * budget_optimum, 1.0)

    f_minus = _forward_at_budget(project_dir, budget_optimum - delta)
    f_plus = _forward_at_budget(project_dir, budget_optimum + delta)

    if f_minus['status'] == 'error' or f_plus['status'] == 'error':
        # Fallback: return point estimate as full CI (no width).
        return {
            'p10': budget_optimum,
            'p50': budget_optimum,
            'p90': budget_optimum,
            'method': 'point',
        }

    grad_approx = (f_plus['expected_sales'] - f_minus['expected_sales']) / (2 * delta)
    if abs(grad_approx) < 1e-9:
        return {
            'p10': budget_optimum * 0.9,
            'p50': budget_optimum,
            'p90': budget_optimum * 1.1,
            'method': 'flat_response_fallback',
        }

    # Variance proxy: difference between f_plus and f_minus / 2 — std-like estimate.
    response_spread = abs(f_plus['expected_sales'] - f_minus['expected_sales']) / 2
    # Conservative half-width for ~80% CI: 1.28 * spread / |grad|.
    half_width = 1.28 * response_spread / abs(grad_approx)

    # Cap CI width at 50% of optimum (paranoia против explosion).
    half_width = min(half_width, 0.5 * budget_optimum)

    return {
        'p10': max(0.0, budget_optimum - half_width),
        'p50': budget_optimum,
        'p90': budget_optimum + half_width,
        'method': 'delta',
    }


def estimate_p_hit_target(
    expected_sales_at_budget: float,
    target_sales: float,
    response_spread: float = 0.0,
) -> float:
    """Estimate P(S(B*) >= target).

    MVP: если expected >= target → 0.5+ (зависит от запаса). Если ниже — < 0.5.
    Точный расчёт требует MCMC posterior on S(B*) — Phase B.

    Returns:
        Probability в [0, 1].
    """
    if expected_sales_at_budget >= target_sales:
        # MVP: assume >50% if expected hits target. Crude.
        if response_spread > 0:
            # Z = (expected - target) / spread. P > target = 1 - Φ(-Z) = Φ(Z)
            from math import erf, sqrt
            z = (expected_sales_at_budget - target_sales) / response_spread
            return 0.5 * (1 + erf(z / sqrt(2)))
        return 0.5
    return 0.5 * (expected_sales_at_budget / target_sales) if target_sales > 0 else 0.0


def optimize_inverse(
    project_dir: str,
    target_sales: float,
    kpi_kind: str = 'monetary',
    mode: str = 'roi',
    budget_constraints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """High-level inverse / goal-seek optimization.

    Per ADR-014 + REFACTOR_PLAN_v1.3.0.md.

    Args:
        project_dir: Path to project.
        target_sales: целевая величина (₽ для monetary, count_unit для count).
        kpi_kind: 'monetary' | 'count' (для logging, не влияет на math).
        mode: 'roi' | 'effectiveness' | 'manual' (для logging).
        budget_constraints: optional {'max_budget': float, 'min_budget': float}.

    Returns:
        Dict (achievable=True case):
        {
          'achievable': True,
          'kpi_kind': 'monetary',
          'mode': 'roi',
          'target_sales': 1.05e8,
          'total_budget': {'p10': 8.5e7, 'p50': 9.5e7, 'p90': 1.05e8, 'method': 'delta'},
          'distribution': {channel: budget},
          'delta_vs_current': 0.12,
          'p_hit_target': 0.78,
          'iterations': 12,
          'expected_sales': 1.05e8,
        }

        Dict (achievable=False):
        {
          'achievable': False,
          'fallback_max_sales': float,
          'fallback_budget': float,
          'message': str,
        }
    """
    # Compute safe corridor для определения bisection bounds.
    from engines.persistence import load_model_with_compat
    from optimize.bounds import compute_safe_corridor

    model_path = Path(project_dir) / 'models' / 'latest.pkl'
    if not model_path.exists():
        return {
            'achievable': False,
            'error': 'MODEL_NOT_FOUND',
            'message': 'Модель не найдена. Сначала обучите модель.',
        }

    model_data = load_model_with_compat(model_path)
    corridor = compute_safe_corridor(model_data)

    budget_lo = 0.0
    budget_hi = corridor['aggregate_budget']['hi']
    current_total = corridor['aggregate_budget']['current']

    # Apply external budget constraints (если заданы юзером).
    if budget_constraints:
        budget_hi = min(budget_hi, budget_constraints.get('max_budget', budget_hi))
        budget_lo = max(budget_lo, budget_constraints.get('min_budget', budget_lo))

    # Bisection.
    bisect_result = bisect_for_target(
        project_dir=project_dir,
        target_sales=target_sales,
        budget_lo=budget_lo,
        budget_hi=budget_hi,
    )

    if not bisect_result.get('achievable'):
        return {
            'achievable': False,
            'kpi_kind': kpi_kind,
            'mode': mode,
            'target_sales': target_sales,
            'fallback_max_sales': bisect_result.get('fallback_max_sales'),
            'fallback_budget': bisect_result.get('fallback_budget'),
            'message': bisect_result.get('message', 'Goal not achievable'),
            'iterations': bisect_result.get('iterations', 0),
        }

    # Posterior CI via Delta method.
    budget_optimum = bisect_result['budget']
    ci = estimate_budget_ci(project_dir, budget_optimum, target_sales)

    # P(hit target): MVP — на основе expected_sales spread.
    p_hit = estimate_p_hit_target(
        bisect_result['expected_sales'],
        target_sales,
        response_spread=(ci['p90'] - ci['p10']) / 4,  # rough proxy
    )

    delta_vs_current = (
        (budget_optimum - current_total) / current_total if current_total > 0 else 0.0
    )

    return {
        'achievable': True,
        'kpi_kind': kpi_kind,
        'mode': mode,
        'target_sales': target_sales,
        'total_budget': ci,
        'distribution': bisect_result['distribution'],
        'delta_vs_current': delta_vs_current,
        'p_hit_target': p_hit,
        'iterations': bisect_result['iterations'],
        'expected_sales': bisect_result['expected_sales'],
        'current_total_budget': current_total,
    }
