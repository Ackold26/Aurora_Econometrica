"""
Budget optimization engine.
Finds optimal spend allocation using scipy.optimize (SLSQP).
"""
import json
import pickle
import numpy as np
from pathlib import Path
from scipy.optimize import minimize
from typing import Any

from utils.adstock import apply_adstock
from utils.saturation import hill_function, response_curve


def _flat_alloc_adstock_avg(raw_per_period: float, n_periods: int, a_type: str) -> float:
    """F2 fix (math-audit v1.3): среднее adstocked spend под flat allocation.

    Optimizer оперирует с total spend per channel (scalar). Hill ожидает
    per-period adstocked spend (как в training + scenario). Для flat allocation
    raw_t = const повторяется по периодам, applied adstock декомпозирует carryover.
    Берём среднее за период — это эквивалент того что training Hill видел
    усреднённо.
    """
    if n_periods < 1 or raw_per_period <= 0:
        return float(raw_per_period)
    flat = np.full(n_periods, float(raw_per_period))
    adstocked = apply_adstock(flat, a_type)
    return float(adstocked.mean())


def _adstock_factor(x_per_period: float, n_periods: int, a_type: str) -> float:
    """∂(_flat_alloc_adstock_avg)/∂(x_per_period) — sensitivity factor.

    F0.2 (Phase 0.1 fix-session): adstock factor is the missing piece in
    chain rule for marginal ROAS. See docs/MATH_AUDIT_v1_3_PHASE_0_1.md §4.

    Args:
        x_per_period: spend per period (≥ 0)
        n_periods: training horizon length
        a_type: 'geometric' | 'weibull' | 'noop' | 'none'
    Returns:
        ∂(adstock_avg)/∂(x_per_period). Constant in x for linear adstock.
    """
    if n_periods < 1:
        return 0.0
    if a_type in ('noop', 'none'):
        return 1.0
    if a_type == 'geometric':
        # Analytical (exact for linear adstock with constant input).
        # adstock_avg(x, n) = x · [n - θ·(1-θ^n)/(1-θ)] / [n·(1-θ)]
        # ∂/∂x = [n - θ·(1-θ^n)/(1-θ)] / [n·(1-θ)]   (constant in x)
        theta = 0.5  # library default — see modeler.py:240-244 + docs §5
        if not (0.0 < theta < 1.0):
            return 1.0
        n = n_periods
        return (n - theta * (1.0 - theta ** n) / (1.0 - theta)) / (n * (1.0 - theta))
    # weibull / unknown — central difference (exact for linear convolution).
    if x_per_period <= 0:
        # Use small probe to discover linear factor.
        eps = 1.0
        plus = _flat_alloc_adstock_avg(eps, n_periods, a_type)
        minus = _flat_alloc_adstock_avg(0.0, n_periods, a_type)
        return float(plus - minus) / eps
    eps = max(x_per_period * 1e-4, 1e-9)
    plus = _flat_alloc_adstock_avg(x_per_period + eps, n_periods, a_type)
    minus = _flat_alloc_adstock_avg(max(x_per_period - eps, 1e-12), n_periods, a_type)
    return float(plus - minus) / (2.0 * eps)


def _compute_mroas_money(
    *,
    current_spend_native: float,
    n_periods: int,
    mean: float,
    alpha: float,
    gamma: float,
    beta: float,
    adstock_type: str,
    y_std: float,
    unit_cost: float = 1.0,
) -> float:
    """Marginal ROAS in money-per-money — single source of truth.

    F0.2 (Phase 0.1 fix-session): canonical mROAS computation. Returns
    ∂KPI(money)/∂spend(money) at the current point.

    Math derivation: docs/MATH_AUDIT_v1_3_PHASE_0_1.md §3.

    Final formula:
        mROAS = β · hill'(x_norm) · adstock_factor · y_std / mean / unit_cost

    where:
        x_pp = current_spend_native / n_periods
        x_norm = adstock_avg(x_pp, n) / mean
        adstock_factor = ∂(adstock_avg)/∂(x_pp)

    Args:
        current_spend_native: total spend over n_periods (≥ 0), native units
        n_periods: training horizon
        mean: training-time mean of channel media volume
        alpha, gamma, beta: Hill saturation parameters
        adstock_type: 'geometric' | 'weibull' | 'noop'
        y_std: standard deviation of trained y (KPI scale)
        unit_cost: ₽ per native unit (e.g. CPP for TRPs); use 1.0 for money channels

    Returns:
        Marginal ROAS — ∂KPI(money)/∂spend(money). Unitless ratio.
        Returns 0.0 for degenerate inputs (zero spend, zero mean, zero beta).
    """
    if current_spend_native <= 0:
        return 0.0
    if mean <= 0 or beta == 0 or n_periods < 1 or unit_cost <= 0:
        return 0.0

    x_pp = current_spend_native / n_periods
    adstock_avg = _flat_alloc_adstock_avg(x_pp, n_periods, adstock_type)
    x_norm = adstock_avg / max(mean, 1e-10)

    # Hill derivative (normalized space): hill'(x) = α·γ^α·x^(α-1) / (x^α + γ^α)²
    g_safe = max(gamma, 1e-10)
    x_safe = max(x_norm, 1e-10)
    hill_deriv = (alpha * (g_safe ** alpha) * (x_safe ** (alpha - 1))) / (
        (x_safe ** alpha + g_safe ** alpha) ** 2
    )

    af = _adstock_factor(x_pp, n_periods, adstock_type)

    # Chain rule: KPI(money) per native spend
    mroas_native = beta * hill_deriv * af * y_std / max(mean, 1e-10)
    # Convert to per-money axis
    return float(mroas_native / unit_cost)


def optimize(config: dict, project_dir: str) -> dict[str, Any]:
    """Optimize budget allocation across channels.

    Args:
        config: {
            'total_budget': float|None,  # None = use current total
            'min_pct': float,            # Глобальный Min % (default 50). Используется
                                         # как fallback если нет per-channel constraint.
            'max_pct': float,            # Глобальный Max % (default 150).
            'min_per_channel': dict|None,# Опционально: {channel: min_pct} — экспертный режим.
                                         # Если задан для канала, перекрывает глобальный min_pct.
            'max_per_channel': dict|None,# Опционально: {channel: max_pct} — экспертный режим.
        }
        project_dir: Path to project with models/latest.pkl

    Returns:
        JSON with current vs optimal allocation, response curves, expected lift
    """
    project_path = Path(project_dir)
    model_path = project_path / 'models' / 'latest.pkl'

    if not model_path.exists():
        return {'status': 'error', 'message': 'Модель не найдена'}

    with open(model_path, 'rb') as f:
        model_data = pickle.load(f)

    # P0-1/2/9 fix: pickle compat detection.
    model_version = model_data.get('model_version', '1.0')
    if model_version == '1.0':
        return {
            'status': 'error',
            'error_code': 'MODEL_OUTDATED',
            'message': 'Модель обучена до v1.0.13. Нормализация изменилась — переобучите модель в кабинете "Модель".',
        }

    config_model = model_data['config']
    channel_params = model_data['channel_params']
    norm = model_data['normalization']
    media_cols = config_model['media_columns']
    # y_std needed for KPI-scale conversions of mROI and response curves.
    y_std = float(norm.get('y_std', 1.0)) or 1.0

    # A1 fix (post-audit v1.2): exclude untrained channels from optimization domain.
    # Channels with zero training variance have β from prior (uninformative) — optimizer
    # would silently allocate budget to them based on fabricated response curves.
    untrained_channels = set(norm.get('untrained_channels', []) or [])
    if untrained_channels and any(c in untrained_channels for c in media_cols):
        # Filter: remove untrained from optimization scope but warn user.
        active_media_cols = [c for c in media_cols if c not in untrained_channels]
        if not active_media_cols:
            return {
                'status': 'error',
                'error_code': 'NO_TRAINED_CHANNELS',
                'message': (
                    'Все каналы в модели имели нулевую вариативность в обучающих '
                    'данных. Оптимизация невозможна — переобучите модель.'
                ),
            }
        media_cols = active_media_cols
    # Override > pickle-config (аналогично decomposer).
    unit_costs_override = config.get('unit_costs')
    unit_costs = unit_costs_override if unit_costs_override is not None else (config_model.get('unit_costs', {}) or {})

    # Read original data for current spend
    import pandas as pd
    data_file = config_model['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
    # Материализация виртуальных каналов (совпадает с train-time merge_rules)
    from utils.merge_rules import apply_merge_rules
    apply_merge_rules(df, config_model.get('merge_rules'))

    current_spend = {col: float(df[col].fillna(0).sum()) for col in media_cols}
    total_current = sum(current_spend.values())
    n_periods = max(len(df), 1)

    # Phase 2 normalization (spend/mean Robyn-style)
    media_means = norm.get('media_means', {}) or {}

    # F2 fix: adstock config per channel (matches training + scenario)
    adstock_config = config_model.get('adstock_config', {}) or {}

    def _adstock_type(col: str) -> str:
        raw = adstock_config.get(col)
        if isinstance(raw, dict):
            return raw.get('type', 'geometric')
        if isinstance(raw, str):
            return raw
        return 'geometric'

    # Money constraint: если задан total_budget_money, constraint считается в money
    # (Σ x_native × unit_cost == total_budget_money). Иначе — native constraint как раньше.
    total_budget_money_target = config.get('total_budget_money')
    uc_arr = [float(unit_costs.get(col, 1.0) or 1.0) for col in media_cols]

    # P0-11 fix (math-fix-v1.0.13) + Phase 0.1 live-test refinement:
    # Detect real unit_smell — native-unit channel (TRPs/clicks/impressions) with
    # default uc=1.0 (CPP/CPM не задан). Это арифметически некорректный mix.
    # Если unit_smell нет — auto-compute money budget из current spend × uc и идём
    # в money-mode без error. Это типичный кейс russian client: digital в рублях
    # (uc=1) + TV в TRPs (uc=CPP) — раньше guard блокировал false-positively.
    UNIT_HINTS = ('TRP', 'GRP', 'OTS', 'IMPRESSION', 'CLICK', 'ПОКАЗ',
                  'КЛИК', 'ПРОСМОТР', 'ВИЗИТ', 'ПУНКТ', 'ОХВАТ', 'РЕЙТИНГ')
    if total_budget_money_target is None:
        smell_channels = [
            col for col, uc in zip(media_cols, uc_arr)
            if uc == 1.0 and any(h in col.upper() for h in UNIT_HINTS)
        ]
        if smell_channels:
            return {
                'status': 'error',
                'error_code': 'UNIT_SMELL',
                'message': f'Не задана стоимость единицы (CPP/CPM) для каналов: {", ".join(smell_channels)}. Укажите unit_costs или total_budget_money.',
            }
        is_all_money = all(uc == 1.0 for uc in uc_arr)
        is_all_native = all(uc != 1.0 for uc in uc_arr)
        if not (is_all_money or is_all_native):
            # Mixed but all CPP/CPM explicit: auto-derive money budget
            total_budget_money_target = sum(
                current_spend[col] * uc_arr[i] for i, col in enumerate(media_cols)
            )

    if total_budget_money_target is not None:
        # В money-режиме total_budget для логов/insight = native-эквивалент (пропорция).
        total_current_money = sum(current_spend[col] * uc_arr[i] for i, col in enumerate(media_cols))
        ratio = float(total_budget_money_target) / max(total_current_money, 1e-9)
        total_budget = total_current * ratio
    else:
        total_budget = config.get('total_budget') or total_current

    min_pct_global = config.get('min_pct', 50) / 100
    max_pct_global = config.get('max_pct', 150) / 100

    # Per-channel constraints (экспертный режим). Если для канала задан явный
    # min/max в процентах — используется он, иначе глобальный.
    min_per_channel = config.get('min_per_channel') or {}
    max_per_channel = config.get('max_per_channel') or {}

    def channel_min(col: str) -> float:
        return min_per_channel.get(col, min_pct_global * 100) / 100

    def channel_max(col: str) -> float:
        return max_per_channel.get(col, max_pct_global * 100) / 100

    # F1+F2 fix (math-audit v1.3): per-period averaging + adstock matches
    # training and scenario semantics. Pre-fix optimizer used:
    #     x_norm = spend_vector[i] / mean    # spend_vector = TOTAL spend over n_periods!
    # → x_norm typically 30-100× для TRPs-heavy → Hill saturated ≈1.0 → SLSQP stuck.
    # Now: per-period avg + adstock factor matching training, contribution × n_periods
    # to scale to total predicted KPI delta units.
    def total_response(spend_vector):
        total = 0
        for i, col in enumerate(media_cols):
            p = channel_params[col]
            mean = float(media_means.get(col, 1)) or 1
            x_avg_raw = spend_vector[i] / n_periods
            x_avg_adstock = _flat_alloc_adstock_avg(x_avg_raw, n_periods, _adstock_type(col))
            x_norm = x_avg_adstock / max(mean, 1e-10)
            sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 1e-6))
            total += p['beta'] * sat[0] * n_periods
        return -total  # Negative for minimization

    # Constraints
    # Post-audit fix: zero-spend channels would have bounds=(0,0) → fixed at zero.
    # Allow optimizer to test channels with current=0 by giving them a default
    # bound = (0, total_budget × max_pct/n_channels) so they CAN receive budget.
    n_ch = max(len(media_cols), 1)
    fallback_max = max(total_budget * max_pct_global / n_ch, 1.0)

    def _bounds_for(col: str) -> tuple[float, float]:
        cs = current_spend[col]
        if cs > 0:
            return (cs * channel_min(col), cs * channel_max(col))
        # Zero-spend channel: allow up to fallback_max
        return (0.0, fallback_max)

    if total_current > 0:
        x0 = np.array([current_spend[col] * total_budget / total_current for col in media_cols])
    else:
        # Even-split fallback if no current spend at all (degenerate but recoverable)
        x0 = np.array([total_budget / n_ch for _ in media_cols])
    bounds = [_bounds_for(col) for col in media_cols]
    if total_budget_money_target is not None:
        # Money constraint: Σ x × unit_cost == total_budget_money
        constraints = [{
            'type': 'eq',
            'fun': lambda x: float(np.sum(np.asarray(x) * np.asarray(uc_arr)) - total_budget_money_target),
        }]
    else:
        constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x) - total_budget}]

    # Optimize
    result = minimize(total_response, x0, method='SLSQP', bounds=bounds, constraints=constraints)
    if not result.success:
        import logging
        logging.getLogger('econometrica').warning(f"Optimization did not converge: {result.message}")
    optimal_spend = result.x if result.success else np.array([current_spend[col] for col in media_cols])

    # Compare current vs optimal
    current_response = -total_response(np.array([current_spend[col] for col in media_cols]))
    optimal_response = -total_response(optimal_spend)
    lift_pct = (optimal_response - current_response) / current_response * 100 if current_response else 0

    channels = []
    for i, col in enumerate(media_cols):
        p = channel_params[col]
        cur = current_spend[col]
        opt = optimal_spend[i]
        delta_pct = (opt - cur) / cur * 100 if cur > 0 else 0

        # F0.2 (Phase 0.1 fix-session 2026-04-25): canonical mROAS chain rule
        # with adstock_factor + unit_cost normalization. See
        # docs/MATH_AUDIT_v1_3_PHASE_0_1.md §3 for full derivation.
        #
        # Pre-fix bugs (closed by F0.2):
        #   #11 missing adstock_factor → mROAS off by 2-15× depending on θ
        #   #12 missing /unit_cost     → TRPs (uc=250000) showed 1780× absurd
        # Both closed by single helper _compute_mroas_money() that returns
        # ∂KPI(money)/∂s(money) — comparable across native and money channels.
        mean_ch = float(media_means.get(col, 1)) or 1
        a_type = _adstock_type(col)
        uc = float(unit_costs.get(col, 1.0) or 1.0)

        mroi_current = _compute_mroas_money(
            current_spend_native=cur,
            n_periods=n_periods,
            mean=mean_ch,
            alpha=p['alpha'],
            gamma=p['gamma'],
            beta=p['beta'],
            adstock_type=a_type,
            y_std=y_std,
            unit_cost=uc,
        )
        mroi_optimal = _compute_mroas_money(
            current_spend_native=float(opt),
            n_periods=n_periods,
            mean=mean_ch,
            alpha=p['alpha'],
            gamma=p['gamma'],
            beta=p['beta'],
            adstock_type=a_type,
            y_std=y_std,
            unit_cost=uc,
        )

        channels.append({
            'name': col,
            'current_spend': round(cur, 0),
            'optimal_spend': round(float(opt), 0),
            'current_spend_money': round(cur * uc, 0),
            'optimal_spend_money': round(float(opt) * uc, 0),
            'unit_cost': uc,
            'delta_pct': round(delta_pct, 1),
            'mroi_current': round(mroi_current, 4),
            'mroi_optimal': round(mroi_optimal, 4),
            'action': 'увеличить' if delta_pct > 5 else ('сократить' if delta_pct < -5 else 'сохранить'),
        })

    # Generate response curves data (for charts)
    # Post-audit fix: response_curve domain in normalized space, displayed against
    # raw spend. Response × y_std → KPI scale (was: y_norm scale, mis-leading numbers).
    response_curves_data = {}
    for i, col in enumerate(media_cols):
        p = channel_params[col]
        cur = current_spend[col]
        mean_ch = float(media_means.get(col, 1)) or 1
        a_type = _adstock_type(col)
        # F5 fix (math-audit v1.3): X-axis в total spend (как было), но Hill input
        # — per-period adstocked / mean. Curve теперь показывает realistic S-shape
        # (раньше total/mean = 30+× → asymptotic plateau).
        upper = cur * 2 if cur > 0 else mean_ch * 2 * n_periods
        spend_range = np.linspace(0, upper, 50)
        # Per-period equivalent for Hill input
        per_period_avg = spend_range / n_periods
        adstocked_avg = np.array([_flat_alloc_adstock_avg(float(x), n_periods, a_type) for x in per_period_avg])
        spend_range_norm = adstocked_avg / max(mean_ch, 1e-10)
        responses_norm = response_curve(spend_range_norm, p['alpha'], max(p['gamma'], 1e-6), p['beta'])
        # Total contribution = per-period response × n_periods × y_std
        responses_kpi = responses_norm * y_std * n_periods
        response_curves_data[col] = {
            'spend': spend_range.tolist(),
            'response': responses_kpi.tolist(),
            'current_x': cur,
            'optimal_x': float(optimal_spend[i]),
        }

    # Money-эквиваленты total_budget: Hill-оптимизация ведётся в нативных единицах
    # каналов (TRP пункты + рубли), но пользователь хочет видеть суммы в валюте KPI.
    total_budget_money = sum(float(optimal_spend[i]) * float(unit_costs.get(col, 1.0) or 1.0)
                             for i, col in enumerate(media_cols))
    total_current_money = sum(current_spend[col] * float(unit_costs.get(col, 1.0) or 1.0)
                              for col in media_cols)

    _sign = '+' if lift_pct >= 0 else ''
    insight = f"Оптимальное перераспределение бюджета ({round(total_budget_money, 0):,.0f} ₽) даёт ожидаемый прирост {_sign}{lift_pct:.1f}%."
    top_increase = max(channels, key=lambda x: x['delta_pct'])
    top_decrease = min(channels, key=lambda x: x['delta_pct'])
    if top_increase['delta_pct'] > 5:
        insight += f" Увеличить {top_increase['name']} на {top_increase['delta_pct']:.0f}%."
    if top_decrease['delta_pct'] < -5:
        insight += f" Сократить {top_decrease['name']} на {abs(top_decrease['delta_pct']):.0f}%."

    result_data = {
        'status': 'ok',
        'total_budget': round(total_budget, 0),
        'total_budget_money': round(total_budget_money, 0),
        'total_current_money': round(total_current_money, 0),
        'expected_lift_pct': round(lift_pct, 1),
        'channels': channels,
        'response_curves': response_curves_data,
        'insight': insight,
        'optimization_converged': result.success,
    }

    # Save
    results_dir = project_path / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / 'optimization.json', 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    return result_data
