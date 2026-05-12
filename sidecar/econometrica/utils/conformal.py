"""
Conformal prediction - distribution-free PI for OLS path.

Sprint 2 (S-OLS-1) initially shipped 2026-04-27.
F2 + F3 honest revision (audit 2026-04-27 fix-session):

⚠️ COVERAGE CAVEATS - read before relying on guarantees:

1. **Exchangeability (F3):** Conformal coverage `P(y_new ∈ [ŷ ± hw]) ≥ 1-α` is
   guaranteed ONLY когда (training + test) data exchangeable. Marketing MMM
   data - это TIME-SERIES с trend/seasonality/regime changes → exchangeability
   нарушена. Vanilla split-conformal coverage **NOT mathematically guaranteed**
   for non-stationary marketing data. Empirically работает на stationary
   residuals (после adstock+Hill снимают autocorrelation), но без formal
   guarantee. Reference: Barber, Candes, Ramdas, Tibshirani 2022 "Conformal
   prediction beyond exchangeability" - для restored guarantee на time-series
   нужен weighted conformal или block conformal (Sprint 4+ enhancement).

2. **Jackknife (NOT jackknife+) (F2):** `jackknife_intervals` ниже implements
   plain leave-one-out residual quantile, NOT Barber et al. 2021 jackknife+.
   True jackknife+ требует test-point-dependent intervals; current API returns
   one symmetric `half_width`. Plain jackknife has **no finite-sample coverage
   guarantee** в general (Barber 2021 §1.1). Empirically reasonable on
   stationary residuals - useful as honest small-N alternative к split - но
   без 1-2α math guarantee.

References:
- Vovk, Gammerman, Shafer 2005 "Algorithmic Learning in a Random World"
- Angelopoulos, Bates 2021 "A Gentle Introduction to Conformal Prediction" arXiv:2107.07511
- Lei, G'Sell, Rinaldo, Tibshirani, Wasserman 2018 "Distribution-Free Predictive Inference for Regression"
- Barber, Candes, Ramdas, Tibshirani 2021 "Predictive inference with the jackknife+"
- Barber, Candes, Ramdas, Tibshirani 2022 "Conformal prediction beyond exchangeability"

Aurora positioning (revised post F2/F3 audit): "honest distribution-free PI
с calibration evidence на marketing data + clear caveats про exchangeability и
plain-jackknife semantics", не "math-guaranteed coverage" (which would require
Sprint 4+ weighted/block conformal + true jackknife+ implementation).

Implementation: Split-conformal (cleanest, fastest variant).
  1. Split data: train (70%) + calibration (30%)
  2. Fit OLS on train
  3. Predict on calibration → absolute residuals
  4. Half-width = ⌈(n_cal+1)(1-α)⌉/n_cal-th quantile of |residuals|
  5. PI for new x_test: ŷ_new ± half_width

Trade-offs vs alternatives:
  + Distribution-free (no normality assumption)
  + No model misspecification penalty (any fit)
  + Computationally cheap (one fit + one quantile)
  - Lose ~30% data к calibration set (wasteful on small N)
  - Marginal coverage only (not conditional на specific x - see Mondrian conformal для conditional)
  - Wider intervals than parametric when assumptions hold
  - Time-series violates exchangeability assumption (see F3 caveat above)
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
        X: design matrix (n_obs, p) - already preprocessed (Hill+adstock applied)
        y: target vector (n_obs,) - same scale as predictions will be made
        train_frac: fraction для training (rest = calibration). Default 0.7.
        confidence: target coverage (default 0.9 = 90% PI)
        seed: RNG для reproducible split

    Returns:
        dict with:
          - half_width: float - symmetric PI bound (ŷ ± half_width)
          - coverage_target: float
          - n_train, n_cal: integers
          - empirical_coverage: float - actual coverage on calibration set
          - method: 'split_conformal'
          - residuals_summary: {min, p25, median, p75, max} of |residuals|

    Returns dict with all-None values когда split fails (insufficient data).
    """
    rng = np.random.default_rng(seed)
    n = len(y)
    if n < 12:
        # Need at least n=12 to support 70/30 split с meaningful calibration
        logger.warning(f"split_conformal: n={n} < 12 - insufficient для valid split")
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
        logger.warning(f"split_conformal: n_cal={n_cal} < 4 - quantile estimate unreliable")
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

    # Empirical coverage on calibration set (sanity check - should be ≈ 1-α)
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


def jackknife_intervals(
    X: np.ndarray,
    y: np.ndarray,
    *,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """Plain leave-one-out residual quantile (NOT jackknife+).

    F2 fix (audit 2026-04-27): function previously misnamed `jackknife_plus_intervals`
    с docstring claim "Coverage guarantee ≥ 1 - 2α (Barber 2021 Theorem 1)" -
    но implementation actually computes plain LOO residual quantile applied
    symmetrically as `± half_width`. True jackknife+ requires test-point-dependent
    intervals: lower = q_α^- of {ŷ^(-i)(x_test) - r_i}, upper = q_{1-α}^+ of
    {ŷ^(-i)(x_test) + r_i}. Current API returns one half_width - incompatible с
    real jackknife+ math.

    Plain jackknife coverage: **no finite-sample guarantee** в general (Barber et al.
    2021 §1.1). Empirically reasonable on stationary residuals - useful as honest
    small-N alternative к split-conformal - but without 1-2α math guarantee.

    Real jackknife+ deferred к Sprint 4+ когда weighted conformal addresses F3
    (exchangeability violation на time-series) - оба нужны вместе для real
    distribution-free guarantee на marketing data.

    Workflow (UNCHANGED - implementation correct, just was mislabeled):
      For i in 1..n: fit OLS leaving out obs i, compute residual r_i = |y_i - ŷ_i^(-i)|
      Half-width = ⌈(n+1)(1-α)⌉/n-th quantile of {r_i}.

    Computational cost: n OLS fits. На n=18 = 18 × 1ms = 18ms (negligible).
    На n=100+ becomes ~100ms (still fast).
    """
    n = len(y)
    if n < 8:
        return {
            'half_width': None, 'coverage_target': confidence,
            'n_obs': n,
            'method': 'jackknife', 'reason': 'insufficient_data',
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
            'method': 'jackknife', 'reason': 'too_many_singular_fits',
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
        'method': 'jackknife',
        'coverage_caveat': (
            'Plain jackknife: no finite-sample coverage guarantee in general. '
            'Empirically reasonable on stationary residuals. True jackknife+ (Barber 2021) '
            'requires test-point-dependent intervals - deferred to Sprint 4+.'
        ),
        'residuals_summary': {
            'min': round(float(valid.min()), 4),
            'median': round(float(np.median(valid)), 4),
            'max': round(float(valid.max()), 4),
        },
        'reason': None,
    }


# F2 backward-compat alias - old `jackknife_plus_intervals` name kept as deprecated
# alias for any external callers (none found in current codebase, but defensive).
# New code should use `jackknife_intervals`.
jackknife_plus_intervals = jackknife_intervals


def conformal_intervals_auto(
    X: np.ndarray,
    y: np.ndarray,
    *,
    confidence: float = 0.9,
    seed: int | None = 42,
) -> dict[str, Any]:
    """Auto-select conformal variant based on n_obs.

    n < 30   → jackknife (plain LOO residual quantile, no finite-sample guarantee)
    n ≥ 30   → split_conformal (faster, marginal 1-α under exchangeability)

    F3 caveat: BOTH variants assume residuals exchangeable. Marketing time-series
    (trend/seasonality) violates exchangeability → coverage NOT guaranteed for
    non-stationary data. See module docstring для full disclosure.

    Returns dict from chosen method + 'auto_choice' marker + 'exchangeability_caveat'.
    """
    n = len(y)
    if n < 30:
        result = jackknife_intervals(X, y, confidence=confidence)
        auto_choice = 'jackknife'
    else:
        result = split_conformal_intervals(X, y, confidence=confidence, seed=seed)
        auto_choice = 'split_conformal'
    result['auto_choice'] = auto_choice
    # F3: exchangeability caveat applied к both variants - surfaces к UI/report layer
    result['exchangeability_caveat'] = (
        'Conformal coverage guaranteed under exchangeability. Marketing time-series '
        'has trend/seasonality → exchangeability violated. Empirically работает на '
        'stationary residuals (после adstock+Hill снимают autocorrelation), но без '
        'formal guarantee для non-stationary data. Reference: Barber 2022.'
    )
    return result
