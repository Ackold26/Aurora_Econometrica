"""P1 fix (2026-07-06): planning mode redistributes budget per mROAS signal.

Регрессионные тесты для фикса числовой обусловленности SLSQP в planning режиме.
До фикса: все каналы получали пропорциональный сплит (nit=1, ложный KKT).
После фикса: нормализация y=x/budget даёт SLSQP правильный масштаб переменных.

Тест строится на синтетических channel_params с заведомо разными mROAS:
  - channel A: крутая кривая Hill (low gamma), недонасыщен → должен получить >prop
  - channel B: пологая кривая Hill (high gamma), насыщен → должен получить <prop
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.forecasting import evaluate_flat_allocation_response


# ─── Синтетический engine для прямого тестирования фикса ───

def _make_synthetic_model(
    n_periods: int = 48,
    n_forecast: int = 12,
):
    """
    2 канала с резко разными кривыми Hill:
      ch_undersat: alpha=3.0, gamma=0.3 → крутая кривая, недонасыщен при current_spend
      ch_sat:      alpha=1.5, gamma=0.8 → пологая кривая, насыщен при current_spend

    При пропорциональном сплите mROAS ch_undersat >> mROAS ch_sat → оптимизатор
    должен сдвинуть бюджет от sat к undersat.
    """
    media_cols = ['ch_undersat', 'ch_sat']

    # adstock_mean_posterior ≈ среднее adstocked spend за обучение
    # Нормировка: x_norm = adstock(x_avg) / mean → при prop_split должен быть ~0.5
    # для undersat (будет вращать недонасыщенную часть) и ~1.5 для sat (насыщен).
    channel_params = {
        'ch_undersat': {
            'alpha': 3.0,
            'gamma': 0.30,   # полунасыщение в нормированных единицах
            'beta': 1.0,
            'decay': 0.3,
            'adstock_mean_posterior': 5_000_000.0,
        },
        'ch_sat': {
            'alpha': 1.5,
            'gamma': 0.80,   # полунасыщение выше → более насыщен при той же норме
            'beta': 1.0,
            'decay': 0.3,
            'adstock_mean_posterior': 5_000_000.0,
        },
    }

    # current_spend: одинаковый у обоих каналов → prop_split = 50/50
    # x_norm при prop = (current/48) * adstock_factor / mean
    # adstock_factor для decay=0.3, n=48 ≈ 1.43
    # x_norm ≈ (500_000_000/48) * 1.43 / 5_000_000 ≈ 2.98 → насыщен (у обоих одинак.)
    # Используем меньший current чтобы undersat был правда недонасыщен (x_norm << gamma)
    # undersat: x_norm << 0.30 → на крутом подъёме
    # sat: x_norm >> 0.80 → на пологом плато
    # Нужны разные current_spend при одинаковом mean.
    # undersat: x_avg = 5_000_000 * 0.15 / 1.43 ≈ 526_000 → total=526_000*48≈25М
    # sat:      x_avg = 5_000_000 * 2.0  / 1.43 ≈ 7М     → total=7М*48≈336М

    current_spend = {
        'ch_undersat': 25_200_000.0,   # x_norm ≈ 0.15 → недонасыщен
        'ch_sat':      336_000_000.0,  # x_norm ≈ 2.0  → насыщен
    }

    uc_arr = [1.0, 1.0]
    uc_train_arr = [1.0, 1.0]
    media_means = {}  # используем adstock_mean_posterior из channel_params
    adstock_config = {
        'ch_undersat': 'geometric',
        'ch_sat': 'geometric',
    }

    return (
        media_cols, channel_params, current_spend, uc_arr, uc_train_arr,
        media_means, adstock_config, n_periods, n_forecast,
    )


def _run_planning_optimize(
    media_cols, channel_params, current_spend, uc_arr, uc_train_arr,
    media_means, adstock_config, n_periods, n_forecast,
    money_target,
    min_pct=0.10, max_pct=3.0,
):
    """Воспроизводим логику optimizer.py planning ветки с нормализацией."""
    from scipy.optimize import minimize

    n_ch = len(media_cols)

    def objective(x_money):
        return -evaluate_flat_allocation_response(
            media_cols=media_cols,
            channel_params=channel_params,
            allocation_money=x_money,
            unit_costs=uc_arr,
            media_means=media_means,
            adstock_config=adstock_config,
            n_periods=n_forecast,
            unit_costs_at_training=uc_train_arr,
        )

    bounds_money = [
        (current_spend[col] * uc_arr[i] * min_pct,
         current_spend[col] * uc_arr[i] * max_pct)
        for i, col in enumerate(media_cols)
    ]

    # Пропорциональная стартовая точка
    prop_money = np.array(
        [current_spend[c] * uc_arr[i] for i, c in enumerate(media_cols)],
        dtype=float,
    )
    prop_money = prop_money / prop_money.sum() * money_target

    # Нормализованное пространство (P1 fix)
    scale = float(money_target)
    y0 = prop_money / scale
    y_bounds = [(lo / scale, hi / scale) for lo, hi in bounds_money]
    y_constraints = [{'type': 'eq', 'fun': lambda y: float(np.sum(y) - 1.0)}]

    def y_objective(y):
        return objective(y * scale)

    r = minimize(
        y_objective, y0,
        method='SLSQP',
        bounds=y_bounds,
        constraints=y_constraints,
        options={'maxiter': 500, 'ftol': 1e-9, 'disp': False},
    )

    opt_money = r.x * scale
    return r, opt_money, prop_money


class TestPlanningModeRedistributes:
    """P1: planning mode перераспределяет при разных mROAS."""

    def test_undersat_channel_gets_more_than_proportional(self):
        """Недонасыщенный канал должен получить долю > пропорциональной."""
        args = _make_synthetic_model()
        media_cols = args[0]
        current_spend = args[2]
        uc_arr = args[3]

        # money_target = 1/4 от суммы current (аналог симптома 226.5М при 906М)
        total_money = sum(current_spend[c] * uc_arr[i] for i, c in enumerate(media_cols))
        money_target = total_money * 0.25

        r, opt_money, prop_money = _run_planning_optimize(*args, money_target=money_target)

        assert r.success, f"SLSQP не сошёлся: {r.message}"

        idx_undersat = media_cols.index('ch_undersat')
        idx_sat = media_cols.index('ch_sat')

        # Недонасыщенный должен получить > пропорционального
        assert opt_money[idx_undersat] > prop_money[idx_undersat] * 1.05, (
            f"ch_undersat должен получить > пропорц.: "
            f"opt={opt_money[idx_undersat]:.0f}, prop={prop_money[idx_undersat]:.0f}"
        )
        # Насыщенный должен получить < пропорционального
        assert opt_money[idx_sat] < prop_money[idx_sat] * 0.95, (
            f"ch_sat должен получить < пропорц.: "
            f"opt={opt_money[idx_sat]:.0f}, prop={prop_money[idx_sat]:.0f}"
        )

    def test_optimal_response_better_than_proportional(self):
        """Оптимальный response должен быть лучше пропорционального."""
        args = _make_synthetic_model()
        media_cols = args[0]
        channel_params = args[1]
        current_spend = args[2]
        uc_arr = args[3]
        uc_train_arr = args[4]
        media_means = args[5]
        adstock_config = args[6]
        n_forecast = args[8]

        total_money = sum(current_spend[c] * uc_arr[i] for i, c in enumerate(media_cols))
        money_target = total_money * 0.25

        r, opt_money, prop_money = _run_planning_optimize(*args, money_target=money_target)

        assert r.success, f"SLSQP не сошёлся: {r.message}"

        def resp(alloc):
            return evaluate_flat_allocation_response(
                media_cols=media_cols,
                channel_params=channel_params,
                allocation_money=alloc,
                unit_costs=uc_arr,
                media_means=media_means,
                adstock_config=adstock_config,
                n_periods=n_forecast,
                unit_costs_at_training=uc_train_arr,
            )

        r_opt = resp(opt_money)
        r_prop = resp(prop_money)

        assert r_opt > r_prop * 1.01, (
            f"Оптимальный response должен быть > пропорц.: "
            f"opt={r_opt:.6f}, prop={r_prop:.6f}"
        )


class TestPlanningModeNotPurelyProportional:
    """P1-канарейка: planning mode не должен возвращать пропорциональный сплит."""

    def test_deltas_are_not_all_equal(self):
        """delta_pct каналов должны отличаться более чем на 1%."""
        args = _make_synthetic_model()
        media_cols = args[0]
        current_spend = args[2]
        uc_arr = args[3]

        total_money = sum(current_spend[c] * uc_arr[i] for i, c in enumerate(media_cols))
        money_target = total_money * 0.25

        r, opt_money, prop_money = _run_planning_optimize(*args, money_target=money_target)

        assert r.success, f"SLSQP не сошёлся: {r.message}"

        # Вычисляем delta_pct как в optimizer.py
        n_forecast = args[8]
        horizon_scale = n_forecast / args[7]
        deltas = []
        for i, col in enumerate(media_cols):
            cur_baseline = current_spend[col] * uc_arr[i] * horizon_scale
            if cur_baseline > 0:
                deltas.append((opt_money[i] - cur_baseline) / cur_baseline * 100)

        assert len(deltas) >= 2
        spread = max(deltas) - min(deltas)
        assert spread > 1.0, (
            f"Все дельты практически одинаковы ({spread:.2f}% разброс) — "
            f"оптимизатор вернул пропорциональный сплит. deltas={deltas}"
        )

    def test_full_budget_planning_also_redistributes(self):
        """При budget == training_total planning тоже должен перераспределять."""
        args = _make_synthetic_model()
        media_cols = args[0]
        current_spend = args[2]
        uc_arr = args[3]

        # Budget = 100% training total
        total_money = sum(current_spend[c] * uc_arr[i] for i, c in enumerate(media_cols))

        r, opt_money, prop_money = _run_planning_optimize(*args, money_target=total_money)

        assert r.success, f"SLSQP не сошёлся: {r.message}"

        idx_undersat = media_cols.index('ch_undersat')
        # Даже при полном бюджете undresat должен получить больше своей доли
        assert opt_money[idx_undersat] > prop_money[idx_undersat] * 1.05, (
            f"Даже при budget=training_total ch_undersat должен получить > пропорц."
        )
