"""
Aurora Econometrica - inverse optimization (Goal-Seek) v1.3.0.

Per ADR-014, REFACTOR_PLAN_v1.3.0.md Stage 1 P0.2 (simplified to bisection):
дана цель продаж S* → найти минимальный бюджет B такой что S(B) ≥ S*.

Algorithm: бисекция по total budget. Forward задача монотонна по B
(в безопасном коридоре), bisection ищет минимальный B где expected_sales >= target.

Posterior CI на B* - Delta method (linearization): B_ci_half = std(S_target) / |∂S/∂B|.

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

# Lazy imports - heavy modules (PyMC, scipy) не нужны на startup.
# Engineering invariant per docs/PERFORMANCE_BUDGET.md.


def _forward_at_budget(project_dir: str, total_budget: float) -> Dict[str, Any]:
    """Run forward optimizer at fixed total_budget.

    Wrapper around engines.optimizer.optimize() - задает scalar budget
    и возвращает expected_sales + distribution.

    Returns:
        {'expected_sales': float, 'distribution': {channel: budget}, 'status': 'ok'|'error'}
    """
    from engines.optimizer import optimize
    config = {
        'total_budget': total_budget,
        'min_pct': 0.0,    # Не ограничиваем per канал - global free reallocation.
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
    # Bug fix 2026-05-25 (Phase 3 smoke): optimize() возвращает FLAT schema
    # с keys total_optimal_kpi / channels[], не вложенный {optimal: {sales, allocation}}.
    # Wrapper писался на основе предполагаемой schema, никогда не testен против
    # real optimizer output → forward_hi.expected_sales всегда =0.0 → Goal-Seek
    # всегда reported «недостижима» независимо от target_sales.
    channels = raw_result.get('channels', []) or []
    return {
        'expected_sales': float(raw_result.get('total_optimal_kpi', 0.0) or 0.0),
        'distribution': {
            (ch.get('name') or ch.get('display_name', '')): float(ch.get('optimal_spend_money', 0.0) or 0.0)
            for ch in channels
        },
        'status': 'ok',
    }


def build_proportional_forward(project_dir: str):
    """GS-1 (2026-06-02): монотонный forward для Goal-Seek через фиксацию текущих
    пропорций каналов + скейл общего бюджета.

    Корень GS-1 (STEP0 probe на Кагоцел): старый `_forward_at_budget` зовёт
    `optimize()` с НАТИВНЫМ бюджетом → guard UNIT_SMELL (не-денежный канал без CPP) →
    error на каждом B → `_verify_monotonicity` маскирует под non_monotonic_forward →
    юзер видит ложное «Forward не монотонна / non-convex Hill». Здесь forward =
    Σ β·Hill(prop_i·B) - сумма индивидуально-монотонных откликов, монотонна по
    построению (эмпирически подтверждено probe), а `evaluate_flat_allocation_response`
    обрабатывает unit_costs напрямую (без smell-guard).

    Семантика goal-seek: «сколько бюджета при ТЕКУЩЕМ миксе каналов нужно для цели»
    (а не при оптимальном перераспределении - это смешивало бы goal-seek с
    оптимизацией и давало немонотонность из-за SLSQP-реаллокации на каждом B).

    Returns:
        (forward_fn, meta), где forward_fn(total_budget_money) -> {expected_sales,
        distribution, status}; meta = {'current_total_money', 'baseline_total'}.
    """
    import numpy as _np
    import pandas as _pd
    from engines.persistence import load_model_with_compat
    from utils.forecasting import evaluate_flat_allocation_response
    from utils.merge_rules import apply_merge_rules

    model_data = load_model_with_compat(Path(project_dir) / 'models' / 'latest.pkl')
    cfg = model_data['config']
    norm = model_data['normalization']
    channel_params = model_data['channel_params']
    media_cols = [c for c in cfg['media_columns']
                  if c not in set(norm.get('untrained_channels', []) or [])]
    y_std = float(norm.get('y_std', 1.0)) or 1.0
    media_means = norm.get('media_means', {}) or {}
    adstock_config = cfg.get('adstock_config', {}) or {}
    unit_costs = cfg.get('unit_costs', {}) or {}

    data_file = cfg['data_file']
    df = _pd.read_excel(data_file) if str(data_file).endswith(('.xlsx', '.xls')) else _pd.read_csv(data_file)
    apply_merge_rules(df, cfg.get('merge_rules'))
    n_periods = max(len(df), 1)

    # baseline (non-media) в KPI scale - константа, не зависит от B
    # (matches optimizer.py:1147-1148 non_media_baseline_total).
    y_mean = float(norm.get('y_mean', 0.0))
    intercept_mean = float(norm.get('intercept_mean', 0.0))
    baseline_total = (intercept_mean * y_std + y_mean) * n_periods

    uc_applied = bool(model_data.get('unit_costs_applied_at_training'))
    uc_snap = (model_data.get('unit_costs_snapshot') or {}) if uc_applied else {}
    uc_arr = [float(unit_costs.get(c, 1.0) or 1.0) for c in media_cols]
    uc_train_arr = [float(uc_snap.get(c, 1.0) or 1.0) for c in media_cols]

    current_native = {c: float(df[c].fillna(0).sum()) for c in media_cols}
    current_money = {c: current_native[c] * float(unit_costs.get(c, 1.0) or 1.0) for c in media_cols}
    total_cur_money = sum(current_money.values())
    if total_cur_money > 0:
        prop = {c: current_money[c] / total_cur_money for c in media_cols}
    else:
        n = len(media_cols)
        prop = {c: (1.0 / n if n else 0.0) for c in media_cols}

    def forward(total_budget_money: float) -> Dict[str, Any]:
        try:
            alloc = _np.array([prop[c] * float(total_budget_money) for c in media_cols], dtype=float)
            resp = evaluate_flat_allocation_response(
                media_cols=media_cols,
                channel_params=channel_params,
                allocation_money=alloc,
                unit_costs=uc_arr,
                media_means=media_means,
                adstock_config=adstock_config,
                n_periods=n_periods,
                unit_costs_at_training=(uc_train_arr if uc_applied else None),
            )
            return {
                'expected_sales': baseline_total + resp * y_std,
                'distribution': {c: prop[c] * float(total_budget_money) for c in media_cols},
                'status': 'ok',
            }
        except Exception as exc:  # noqa: BLE001 - forward не должен ронять bisection
            return {'expected_sales': 0.0, 'distribution': {}, 'status': 'error',
                    'error_message': str(exc)}

    return forward, {'current_total_money': total_cur_money, 'baseline_total': baseline_total}


def _verify_monotonicity(forward_fn, budget_lo: float, budget_hi: float, n_probes: int = 5) -> Dict[str, Any]:
    """v1.3.1 hotfix: verify forward(B) монотонна в [lo, hi].

    Probes forward function на n_probes equally-spaced points + checks
    monotonic increase. Если violated - flags non-monotonic для caller
    (bisection assumes monotonicity).

    Per red-team audit finding B6.

    GS-1 (2026-06-02): принимает forward_fn (callable B->result) вместо project_dir,
    чтобы caller мог подставить proportional forward (монотонный по построению).

    Returns:
        {'monotonic': bool, 'probes': [{B, S}], 'violation_at': int | None}
    """
    if n_probes < 3:
        n_probes = 3
    step = (budget_hi - budget_lo) / (n_probes - 1)
    probes = []
    prev_sales = -float('inf')
    violation_at = None
    for i in range(n_probes):
        B = budget_lo + step * i
        forward = forward_fn(B)
        if forward.get('status') == 'error':
            return {'monotonic': False, 'probes': probes, 'violation_at': i, 'error': True}
        S = forward['expected_sales']
        probes.append({'B': B, 'S': S})
        if S < prev_sales - 1e-6 * abs(prev_sales):  # strict decrease (with tolerance)
            violation_at = i
        prev_sales = S
    return {
        'monotonic': violation_at is None,
        'probes': probes,
        'violation_at': violation_at,
    }


def bisect_for_target(
    project_dir: str,
    target_sales: float,
    budget_lo: float,
    budget_hi: float,
    rel_tol: float = 1e-3,
    max_iters: int = 30,
    verify_monotonic: bool = True,
    forward_fn=None,
) -> Dict[str, Any]:
    """Bisection: find minimum total_budget B such that expected_sales(B) ≥ target_sales.

    v1.3.1 hotfix: добавлен verify_monotonic guard per red-team audit B6.

    Args:
        project_dir: Path to project.
        target_sales: целевая величина продаж (₽ или count units).
        budget_lo: нижняя граница (обычно 0 или corridor_lo).
        budget_hi: верхняя граница (обычно corridor_hi).
        rel_tol: tolerance относительно (hi - lo).
        max_iters: max iterations (защита от non-convergence).
        verify_monotonic: v1.3.1 - verify monotonicity перед bisection.

    Returns:
        {
          'budget': float,        # B* - минимальный budget для достижения target
          'expected_sales': float, # S(B*) - ожидаемые продажи
          'achievable': bool,
          'iterations': int,
          'distribution': dict,   # final allocation
          'monotonicity_check': dict | None,  # v1.3.1 audit trail
        }
    """
    # GS-1 (2026-06-02): forward_fn по умолчанию = legacy re-optimize per budget
    # (back-compat). optimize_inverse подставляет proportional forward.
    fwd = forward_fn if forward_fn is not None else (lambda B: _forward_at_budget(project_dir, B))

    # v1.3.1: verify monotonicity guard (per red-team audit B6).
    monotonicity_check = None
    if verify_monotonic:
        monotonicity_check = _verify_monotonicity(fwd, budget_lo, budget_hi)
        if not monotonicity_check['monotonic']:
            return {
                'achievable': False,
                'error': 'non_monotonic_forward',
                'monotonicity_check': monotonicity_check,
                'message': (
                    'Forward функция не монотонна в безопасном коридоре. '
                    'Bisection не применима - возможна non-convex Hill saturation. '
                    'Рекомендация: уменьшить диапазон или включить Expert Mode '
                    '(full posterior re-bisection - Phase B).'
                ),
                'iterations': monotonicity_check.get('violation_at', 0) or 0,
            }

    # Sanity check: forward at hi должен достичь target.
    forward_hi = fwd(budget_hi)
    if forward_hi['status'] == 'error':
        return {
            'achievable': False,
            'error': forward_hi.get('error_message', 'Forward at hi failed'),
            'iterations': 0,
            'monotonicity_check': monotonicity_check,
        }

    if forward_hi['expected_sales'] < target_sales:
        return {
            'achievable': False,
            'fallback_max_sales': forward_hi['expected_sales'],
            'fallback_budget': budget_hi,
            'iterations': 1,
            'monotonicity_check': monotonicity_check,
            'message': (
                f'Цель {target_sales:,.0f} недостижима в доступном диапазоне бюджета. '
                f'Максимум достижимых продаж при текущем миксе каналов: '
                f'{forward_hi["expected_sales"]:,.0f}'
            ).replace(',', ' '),  # 2026-06-07: разделители разрядов (пробел) вместо сырого числа
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
        forward_mid = fwd(mid)
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
        'monotonicity_check': monotonicity_check,
    }


def estimate_budget_ci(
    project_dir: str,
    budget_optimum: float,
    target_sales: float,
    delta_pct: float = 0.05,
    forward_fn=None,
) -> Dict[str, float]:
    """Estimate posterior CI на budget через Delta method (linearization).

    Идея:
    - Локальный gradient: ∂S/∂B ≈ (S(B + δ) - S(B - δ)) / (2δ).
    - Posterior std на S(B*) - приближаем через 1-2 forward passes на B ± δ.
    - B_ci_half_width ≈ S_std / |∂S/∂B|.

    MVP - простая Delta method. Phase B: full posterior re-bisection.

    Returns:
        {'p10': float, 'p50': budget_optimum, 'p90': float, 'method': 'delta'}
    """
    fwd = forward_fn if forward_fn is not None else (lambda B: _forward_at_budget(project_dir, B))
    delta = max(delta_pct * budget_optimum, 1.0)

    f_minus = fwd(budget_optimum - delta)
    f_plus = fwd(budget_optimum + delta)

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

    # Variance proxy: difference between f_plus and f_minus / 2 - std-like estimate.
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

    MVP: если expected >= target → 0.5+ (зависит от запаса). Если ниже - < 0.5.
    Точный расчёт требует MCMC posterior on S(B*) - Phase B.

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
    model_path = Path(project_dir) / 'models' / 'latest.pkl'
    if not model_path.exists():
        return {
            'achievable': False,
            'error': 'MODEL_NOT_FOUND',
            'message': 'Модель не найдена. Сначала обучите модель.',
        }

    # GS-1 (2026-06-02): proportional forward (фикс. текущий микс каналов) -
    # монотонен по построению, обрабатывает unit_costs напрямую (без UNIT_SMELL
    # guard, который ронял re-optimize forward на не-денежных каналах).
    forward_fn, fwd_meta = build_proportional_forward(project_dir)
    current_total = fwd_meta['current_total_money']

    budget_lo = 0.0
    # Диапазон bisection от текущего ДЕНЕЖНОГО бюджета (×5), а не из safe corridor:
    # на не-денежных каналах corridor смешивает единицы (STEP0 probe: current 279M
    # vs corridor hi 17.6M - несопоставимо), goal-seek упирался бы в ложный потолок.
    if current_total > 0:
        budget_hi = current_total * 5.0
    else:
        from engines.persistence import load_model_with_compat
        from optimize.bounds import compute_safe_corridor
        budget_hi = float(compute_safe_corridor(
            load_model_with_compat(model_path))['aggregate_budget']['hi'])

    # Apply external budget constraints (если заданы юзером).
    if budget_constraints:
        if budget_constraints.get('max_budget') is not None:
            budget_hi = float(budget_constraints['max_budget'])
        budget_lo = max(budget_lo, budget_constraints.get('min_budget', budget_lo))

    # Bisection через proportional forward.
    bisect_result = bisect_for_target(
        project_dir=project_dir,
        target_sales=target_sales,
        budget_lo=budget_lo,
        budget_hi=budget_hi,
        forward_fn=forward_fn,
    )

    if not bisect_result.get('achievable'):
        return {
            'achievable': False,
            'kpi_kind': kpi_kind,
            'mode': mode,
            'target_sales': target_sales,
            # #59 (2026-06-02): пробрасываем error code (напр. non_monotonic_forward),
            # чтобы UI различал «недостижима» vs «non-convex Hill» и показывал точный hint.
            'error': bisect_result.get('error'),
            'fallback_max_sales': bisect_result.get('fallback_max_sales'),
            'fallback_budget': bisect_result.get('fallback_budget'),
            'message': bisect_result.get('message', 'Goal not achievable'),
            'iterations': bisect_result.get('iterations', 0),
        }

    # Posterior CI via Delta method (тот же proportional forward для согласованного градиента).
    budget_optimum = bisect_result['budget']
    ci = estimate_budget_ci(project_dir, budget_optimum, target_sales, forward_fn=forward_fn)
    # #59 (2026-06-02): явный булев маркер насыщения для UI-баннера.
    # estimate_budget_ci ставит method='flat_response_fallback', когда локальный
    # градиент ∂S/∂B ≈ 0 (плоская кривая) — Goal-Seek нашёл бюджет, но маргинальная
    # отдача ≈ 0 и CI грубый (±10%). UI показывает баннер вместо сырого жаргона.
    flat_response_fallback = ci.get('method') == 'flat_response_fallback'

    # P(hit target): MVP - на основе expected_sales spread.
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
        'flat_response_fallback': flat_response_fallback,
        # GS-1: распределение получено масштабированием ТЕКУЩЕГО микса (фикс. пропорции),
        # а не оптимальным перераспределением. UI поясняет это пользователю.
        'allocation_mode': 'proportional',
    }
