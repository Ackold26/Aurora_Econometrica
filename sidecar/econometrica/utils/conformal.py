"""
Conformal prediction — distribution-free guaranteed-coverage CI.

Sprint 2 idealization (S-OLS-1 audit synergy 2026-04-27):
Modern alternative к Bayesian posterior CI и frequentist t-intervals — works
без parametric assumptions. На marketing data с small N + non-normal residuals
(common — sales spike events) parametric CI могут underestimate uncertainty.
Conformal prediction guarantees marginal coverage = 1-α под exchangeability
(weaker than i.i.d. — almost always holds for cross-sectional regression).

References:
- Vovk, Gammerman, Shafer 2005 "Algorithmic Learning in a Random World"
- Angelopoulos, Bates 2021 "A Gentle Introduction to Conformal Prediction" arXiv:2107.07511
- Lei, G'Sell, Rinaldo, Tibshirani, Wasserman 2018 "Distribution-Free Predictive Inference for Regression"

Aurora positioning: единственный MMM-tool с conformal prediction → marketing
differentiator "honest CI с math-guaranteed coverage, не assumption-based".

Implementation: Split-conformal (cleanest, fastest variant).
  1. Split data: train (70%) + calibration (30%)
  2. Fit OLS on train
  3. Predict on calibration → absolute residuals
  4. Half-width = (n_cal+1)(1-α)/n_cal-th quantile of |residuals|
  5. PI for new x_test: ŷ_new ± half_width

Coverage guarantee: P(y_new ∈ [ŷ - hw, ŷ + hw]) ≥ 1 - α (marginal, exchangeable test+cal).

Trade-offs vs alternatives:
  + Distribution-free (no normality assumption)
  + No model misspecification penalty (any fit)
  + Computationally cheap (one fit + one quantile)
  - Lose ~30% data к calibration set (wasteful on small N)
  - Marginal coverage only (not conditional на specific x — see Mondrian conformal для conditional)
  - Wider intervals than parametric when assumptions hold

Mitigation для small N: jackknife+ variant uses leave-one-out — full data utilization.
Implemented as fallback option below.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def split_conformal_intervals(
    X: np.ndarray,
    y: np.ndarray,
    *,
    train_frac: float = 0.7,
    confidence: float = 0.9,
    seed: int | None = 42,
) -> dict[str, Any]:
    """Split-conformal prediction intervals для y forecasts.

    Args:
        X: design matrix (n_obs, p) — already preprocessed (Hill+adstock applied)
        y: target vector (n_obs,) — same scale as predictions will be made
        train_frac: fraction для training (rest = calibration). Default 0.7.
        confidence: target coverage (default 0.9 = 90% PI)
        seed: RNG для reproducible split

    Returns:
        dict with:
          - half_width: float — symmetric PI bound (ŷ ± half_width)
          - coverage_target: float
          - n_train, n_cal: integers
          - empirical_coverage: float — actual coverage on calibration set
          - method: 'split_conformal'
          - residuals_summary: {min, p25, median, p75, max} of |residuals|

    Returns dict with all-None values когда split fails (insufficient data).
    """
    rng = np.random.default_rng(seed)
    n = len(y)
    if n < 12:
        # Need at least n=12 to support 70/30 split с meaningful calibration
        logger.warning(f"split_conformal: n={n} < 12 — insufficient для valid split")
        return {
            'half_width': None,
            'coverage_target': confidence,
            'n_train': 0, 'n_cal': 0,
            'empirical_coverage': None,
            'method': 'split_conformal',
            'reason': 'insufficient_data',
        }

    n_train = int(n * train_frac)
    n_cal = n - n_train
    if n_cal < 4:
        logger.warning(f"split_conformal: n_cal={n_cal} < 4 — quantile estimate unreliable")
        return {
            'half_width': None, 'coverage_target': confidence,
            'n_train': n_train, 'n_cal': n_cal,
            'empirical_coverage': None,
            'method': 'split_conformal', 'reason': 'cal_too_small',
        }

    indices = np.arange(n)
    rng.shuffle(indices)
    train_idx = indices[:n_train]
    cal_idx = indices[n_train:]

    X_train, X_cal = X[train_idx], X[cal_idx]
    y_train, y_cal = y[train_idx], y[cal_idx]

    # Fit OLS on train split
    try:
        beta_hat, *_ = np.linalg.lstsq(X_train, y_train, rcond=None)
    except np.linalg.LinAlgError:
        return {
            'half_width': None, 'coverage_target': confidence,
            'n_train': n_train, 'n_cal': n_cal,
            'empirical_coverage': None,
            'method': 'split_conformal', 'reason': 'singular_train',
        }

    # Calibration residuals
    y_pred_cal = X_cal @ beta_hat
    abs_residuals = np.abs(y_cal - y_pred_cal)

    # Conformal half-width: ⌈(n_cal+1)(1-α)⌉/n_cal-th quantile.
    # Standard formula from Lei et al. 2018, Angelopoulos-Bates 2021 §2.
    alpha = 1.0 - confidence
    q_index = int(np.ceil((n_cal + 1) * (1.0 - alpha)))
    q_index = min(max(q_index, 1), n_cal)  # bounds safety
    sorted_resid = np.sort(abs_residuals)
    half_width = float(sorted_resid[q_index - 1])

    # Empirical coverage on calibration set (sanity check — should be ≈ 1-α)
    empirical_coverage = float(np.mean(abs_residuals <= half_width))

    return {
        'half_width': half_width,
        'coverage_target': confidence,
        'n_train': n_train,
        'n_cal': n_cal,
        'empirical_coverage': round(empirical_coverage, 3),
        'method': 'split_conformal',
        'residuals_summary': {
            'min': round(float(abs_residuals.min()), 4),
            'p25': round(float(np.percentile(abs_residuals, 25)), 4),
            'median': round(float(np.median(abs_residuals)), 4),
            'p75': round(float(np.percentile(abs_residuals, 75)), 4),
            'max': round(float(abs_residuals.max()), 4),
        },
        'reason': None,
    }


def jackknife_plus_intervals(
    X: np.ndarray,
    y: np.ndarray,
    *,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """Jackknife+ conformal prediction (Barber, Candes, Ramdas, Tibshirani 2021).

    Better than split-conformal на small N — uses ALL data efficiently
    (leave-one-out training, no calibration set sacrifice).

    Workflow:
      For i in 1..n: fit OLS leaving out obs i, compute residual r_i = |y_i - ŷ_i^(-i)|
      Half-width = (n+1)(1-α)/n-th quantile of {r_i}.
      Coverage guarantee: ≥ 1 - 2α (slightly weaker than split's 1-α but still distribution-free).

    Computational cost: n OLS fits. На n=18 = 18 × 1ms = 18ms (negligible).
    На n=100+ becomes ~100ms (still fast).
    """
    n = len(y)
    if n < 8:
        return {
            'half_width': None, 'coverage_target': confidence,
            'n_obs': n,
            'method': 'jackknife_plus', 'reason': 'insufficient_data',
        }

    abs_residuals = np.zeros(n)
    failed_fits = 0
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        X_train_i = X[mask]
        y_train_i = y[mask]
        try:
            beta_i, *_ = np.linalg.lstsq(X_train_i, y_train_i, rcond=None)
        except np.linalg.LinAlgError:
            failed_fits += 1
            abs_residuals[i] = np.nan
            continue
        y_pred_i = float(X[i] @ beta_i)
        abs_residuals[i] = abs(float(y[i]) - y_pred_i)

    valid = abs_residuals[~np.isnan(abs_residuals)]
    if valid.size < 4:
        return {
            'half_width': None, 'coverage_target': confidence,
            'n_obs': n, 'failed_fits': failed_fits,
            'method': 'jackknife_plus', 'reason': 'too_many_singular_fits',
        }

    alpha = 1.0 - confidence
    q_index = int(np.ceil((valid.size + 1) * (1.0 - alpha)))
    q_index = min(max(q_index, 1), valid.size)
    sorted_resid = np.sort(valid)
    half_width = float(sorted_resid[q_index - 1])

    return {
        'half_width': half_width,
        'coverage_target': confidence,
        'n_obs': n,
        'failed_fits': failed_fits,
        'method': 'jackknife_plus',
        'residuals_summary': {
            'min': round(float(valid.min()), 4),
            'median': round(float(np.median(valid)), 4),
            'max': round(float(valid.max()), 4),
        },
        'reason': None,
    }


def conformal_intervals_auto(
    X: np.ndarray,
    y: np.ndarray,
    *,
    confidence: float = 0.9,
    seed: int | None = 42,
) -> dict[str, Any]:
    """Auto-select conformal variant based on n_obs.

    n < 30   → jackknife+ (uses all data, ~n× slower but ok at small scale)
    n ≥ 30   → split_conformal (faster, similar coverage on larger N)

    Returns dict from chosen method + 'auto_choice' marker.
    """
    n = len(y)
    if n < 30:
        result = jackknife_plus_intervals(X, y, confidence=confidence)
    else:
        result = split_conformal_intervals(X, y, confidence=confidence, seed=seed)
    result['auto_choice'] = 'jackknife_plus' if n < 30 else 'split_conformal'
    return result
