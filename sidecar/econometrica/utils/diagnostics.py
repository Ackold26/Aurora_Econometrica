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
                        divergences: int = 0, ratio: float | None = None) -> dict:
    """Compute Model Quality Score (MQS) with tier classification.

    Applies a data-thinness cap based on observations-to-parameters ratio:
      ratio < 2  → MQS capped at 50 (weak) - severe overfitting risk
      ratio < 4  → MQS capped at 70 (good, not excellent) - wide CIs likely

    Without the cap, a well-converged overfit model on thin data gets a
    misleadingly high score (R² ~0.99 when model just memorised noise).

    Returns:
        Dict with score, tier, tier_label, color, components, and thinness_cap.
    """
    # Component scores (0-100 each)
    r2_score = min(100, max(0, r_squared * 100))
    mape_score = min(100, max(0, 100 - mape * 2))  # MAPE 0%=100, 50%=0
    convergence_score = 100 if r_hat_max < 1.05 and divergences == 0 else (
        70 if r_hat_max < 1.1 else 30
    )

    # Weighted average
    raw_mqs = r2_score * 0.4 + mape_score * 0.3 + convergence_score * 0.3

    # Data-thinness cap
    thinness_cap = None
    if ratio is not None:
        if ratio < 2:
            thinness_cap = 50
        elif ratio < 4:
            thinness_cap = 70
    mqs = min(raw_mqs, thinness_cap) if thinness_cap is not None else raw_mqs

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
        'raw_score': round(raw_mqs, 1),
        'tier': tier,
        'tier_label': label,
        'color': color,
        'thinness_cap': thinness_cap,
        'ratio': round(ratio, 2) if ratio is not None else None,
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
    from utils.model_spec import bayesian_mmm_spec
    ratio = n_obs / max(n_params, 1)
    mqs = model_quality_score(r_squared, mape, r_hat_max, divergences, ratio=ratio)

    # Human-readable verdict.
    # ВАЖНО: MQS-бейдж (слева от текста) - агрегированный score 0-100 из R²+MAPE+convergence.
    # R² - отдельная метрика (fit), явно маркируем её в тексте чтобы не путать с MQS.
    r2_pct = round(r_squared * 100)
    thin_note = ""
    if mqs.get('thinness_cap') is not None:
        if ratio < 2:
            thin_note = f" ⚠ Данных критически мало (Ratio {ratio:.1f}:1) - высокий риск переобучения, результаты ненадёжны."
        else:
            thin_note = f" ⚠ Данных мало (Ratio {ratio:.1f}:1 < 4:1) - высокий R² может быть артефактом переобучения. Доверительные интервалы будут широкими."

    if mqs['tier'] in ('excellent', 'good'):
        verdict = f"Модель объясняет {r2_pct}% вариации продаж (R²). Надёжный результат для принятия бюджетных решений.{thin_note}"
    elif mqs['tier'] == 'acceptable':
        verdict = f"Модель объясняет {r2_pct}% вариации продаж (R²). Приемлемо для ориентировочных решений, рекомендуем дополнительную валидацию.{thin_note}"
    elif mqs.get('thinness_cap') is not None and r_squared >= 0.7:
        # MQS-1 (2026-06-02): tier weak/poor достигается двумя путями — реально низкий
        # fit ИЛИ высокий R², зажатый data-thinness cap (короткий ряд → переобучение).
        # «объясняет только 98%» вводит в заблуждение: 98% — высокий fit, реальная
        # проблема в переобучении (её раскрывает thin_note). INV-50: честно про корень.
        verdict = (
            f"Модель объясняет {r2_pct}% вариации продаж (R²) — высокий fit. "
            f"На коротких данных это вероятный признак переобучения, а не надёжности.{thin_note}"
        )
    else:
        verdict = f"Модель объясняет только {r2_pct}% вариации продаж (R²). Результаты ненадёжны - нужно больше данных или другая спецификация.{thin_note}"

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
        'model_spec': bayesian_mmm_spec(),
    }
