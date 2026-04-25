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

from utils.saturation import hill_function, response_curve


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

    # Phase 2 normalization (spend/mean Robyn-style)
    media_means = norm.get('media_means', {}) or {}

    # Money constraint: если задан total_budget_money, constraint считается в money
    # (Σ x_native × unit_cost == total_budget_money). Иначе — native constraint как раньше.
    total_budget_money_target = config.get('total_budget_money')
    uc_arr = [float(unit_costs.get(col, 1.0) or 1.0) for col in media_cols]

    # P0-11 fix (math-fix-v1.0.13): mixed-units guard for native-mode budget.
    # Native total constraint Σ x makes no sense across channels in different units
    # (TRPs + rubles → arithmetic nonsense). Either all-money (uc=1.0) or all-native
    # (uc≠1.0) channels OR explicit money-mode (total_budget_money) is required.
    if total_budget_money_target is None:
        is_all_money = all(uc == 1.0 for uc in uc_arr)
        is_all_native = all(uc != 1.0 for uc in uc_arr)
        if not (is_all_money or is_all_native):
            return {
                'status': 'error',
                'error_code': 'MIXED_UNITS',
                'message': 'Каналы в смешанных единицах (часть в рублях, часть в TRP/показах). Укажите total_budget_money либо unit_costs для всех каналов.',
            }

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

    # Response function: spend → predicted effect
    # P0-5/6 fix (math-fix-v1.0.13): match training formula spend/mean + raw gamma.
    # Pre-fix used: hill(spend_raw, gamma=p.gamma * current_spend) — three different
    # formulas across modeler/optimizer/scenario for one model.
    def total_response(spend_vector):
        total = 0
        for i, col in enumerate(media_cols):
            p = channel_params[col]
            mean = float(media_means.get(col, 1)) or 1
            x_norm = spend_vector[i] / max(mean, 1e-10)
            sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 1e-6))
            total += p['beta'] * sat[0]
        return -total  # Negative for minimization

    # Constraints
    x0 = np.array([current_spend[col] * total_budget / total_current for col in media_cols])
    bounds = [
        (current_spend[col] * channel_min(col), current_spend[col] * channel_max(col))
        for col in media_cols
    ]
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

        # Marginal ROI at current and optimal points
        # Post-audit fix: full chain rule + y_std denormalization → KPI/spend.
        # marginal_roi returns d(β·hill(x_norm))/d(x_norm) in y_norm units.
        # d(KPI)/d(spend) = d(β·hill(x_norm))/d(x_norm) × dx_norm/dspend × y_std
        #                 = marginal × (1/mean) × y_std
        from utils.saturation import marginal_roi
        mean_ch = float(media_means.get(col, 1)) or 1
        cur_norm = cur / max(mean_ch, 1e-10)
        opt_norm = float(opt) / max(mean_ch, 1e-10)
        mroi_current_norm = float(marginal_roi(np.array([max(cur_norm, 1e-10)]), p['alpha'], max(p['gamma'], 1e-6), p['beta'])[0])
        mroi_optimal_norm = float(marginal_roi(np.array([max(opt_norm, 1e-10)]), p['alpha'], max(p['gamma'], 1e-6), p['beta'])[0])
        mroi_current = mroi_current_norm * y_std / max(mean_ch, 1e-10)
        mroi_optimal = mroi_optimal_norm * y_std / max(mean_ch, 1e-10)

        uc = float(unit_costs.get(col, 1.0) or 1.0)
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
    # P0-5/6 fix: response_curve domain in normalized space, displayed against raw spend.
    response_curves_data = {}
    for i, col in enumerate(media_cols):
        p = channel_params[col]
        cur = current_spend[col]
        mean_ch = float(media_means.get(col, 1)) or 1
        spend_range = np.linspace(0, cur * 2, 50)
        spend_range_norm = spend_range / max(mean_ch, 1e-10)
        responses = response_curve(spend_range_norm, p['alpha'], max(p['gamma'], 1e-6), p['beta'])
        response_curves_data[col] = {
            'spend': spend_range.tolist(),
            'response': responses.tolist(),
            'current_x': cur,
            'optimal_x': float(optimal_spend[i]),
        }

    # Money-эквиваленты total_budget: Hill-оптимизация ведётся в нативных единицах
    # каналов (TRP пункты + рубли), но пользователь хочет видеть суммы в валюте KPI.
    total_budget_money = sum(float(optimal_spend[i]) * float(unit_costs.get(col, 1.0) or 1.0)
                             for i, col in enumerate(media_cols))
    total_current_money = sum(current_spend[col] * float(unit_costs.get(col, 1.0) or 1.0)
                              for col in media_cols)

    insight = f"Оптимальное перераспределение бюджета ({round(total_budget_money, 0):,.0f} ₽) даёт ожидаемый прирост +{lift_pct:.1f}%."
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
