"""
Model diagnostics for MMM quality assessment.
MQS (Model Quality Score), convergence checks, fit metrics.
"""
import numpy as np
from typing import Any


def compute_r_squared(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Coefficient of determination."""
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


def compute_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Percentage Error (%)."""
    mask = y_true != 0
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def compute_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Root Mean Squared Error."""
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def model_quality_score(r_squared: float, mape: float, r_hat_max: float,
                        divergences: int = 0) -> dict:
    """Compute Model Quality Score (MQS) with tier classification.

    Returns:
        Dict with score, tier, tier_label, and component scores
    """
    # Component scores (0-100 each)
    r2_score = min(100, max(0, r_squared * 100))
    mape_score = min(100, max(0, 100 - mape * 2))  # MAPE 0%=100, 50%=0
    convergence_score = 100 if r_hat_max < 1.05 and divergences == 0 else (
        70 if r_hat_max < 1.1 else 30
    )

    # Weighted average
    mqs = r2_score * 0.4 + mape_score * 0.3 + convergence_score * 0.3

    # Tier classification
    if mqs >= 85:
        tier, label, color = 'excellent', 'Отличное', '#22c55e'
    elif mqs >= 70:
        tier, label, color = 'good', 'Хорошее', '#3b82f6'
    elif mqs >= 55:
        tier, label, color = 'acceptable', 'Приемлемое', '#f59e0b'
    elif mqs >= 40:
        tier, label, color = 'weak', 'Слабое', '#f97316'
    else:
        tier, label, color = 'poor', 'Ненадёжное', '#ef4444'

    return {
        'score': round(mqs, 1),
        'tier': tier,
        'tier_label': label,
        'color': color,
        'components': {
            'r_squared': {'value': round(r_squared, 4), 'score': round(r2_score, 1)},
            'mape': {'value': round(mape, 2), 'score': round(mape_score, 1)},
            'convergence': {'r_hat_max': round(r_hat_max, 4), 'divergences': divergences,
                           'score': round(convergence_score, 1)},
        },
    }


def generate_diagnostics_summary(r_squared: float, mape: float, rmse: float,
                                  r_hat_max: float, divergences: int,
                                  n_obs: int, n_params: int) -> dict:
    """Full diagnostics summary for UI display."""
    mqs = model_quality_score(r_squared, mape, r_hat_max, divergences)

    # Human-readable verdict
    if mqs['tier'] in ('excellent', 'good'):
        verdict = f"Модель объясняет {round(r_squared * 100)}% изменений продаж. Это надёжный результат для принятия бюджетных решений."
    elif mqs['tier'] == 'acceptable':
        verdict = f"Модель объясняет {round(r_squared * 100)}% изменений. Результаты приемлемые, но рекомендуем дополнительную валидацию."
    else:
        verdict = f"Модель объясняет только {round(r_squared * 100)}% изменений. Результаты ненадёжны — рекомендуем больше данных или другую спецификацию."

    return {
        'mqs': mqs,
        'verdict': verdict,
        'metrics': {
            'r_squared': round(r_squared, 4),
            'mape_pct': round(mape, 2),
            'rmse': round(rmse, 2),
            'r_hat_max': round(r_hat_max, 4),
            'divergences': divergences,
            'n_observations': n_obs,
            'n_parameters': n_params,
            'ratio': round(n_obs / max(n_params, 1), 1),
        },
        'checks': {
            'convergence': r_hat_max < 1.05 and divergences == 0,
            'fit': r_squared > 0.5,
            'ratio': n_obs / max(n_params, 1) >= 4,
        },
    }
