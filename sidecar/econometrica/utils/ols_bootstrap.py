"""
OLS bootstrap для honest ROI CI на small data (Sprint 2 extension).

Frequentist β CI (β ± t·SE) — это uncertainty на coefficients, НЕ на ROI.
ROI = contribution / spend = β · hill(x_norm) · y_std × n_periods / (raw_spend · unit_cost).
Hill non-linearity + ratio amplifies/dampens β uncertainty в ROI bounds.

Bootstrap: refit OLS на N=200 resamples (with replacement) → ROI distribution per
channel → percentile CI. Closes gap "OLS показывает β CI, но не показывает ROI CI"
identified в Sprint 2 small-data review.

Math: each bootstrap sample i:
  1. Resample (X_i, y_i) with replacement from training data
  2. Refit OLS: β_i = (X_i'X_i)^(-1) X_i' y_i
  3. Compute per-channel ROI_i using β_i + same Hill defaults + same y_std
  4. Repeat N=200 times → ROI_i distribution
  5. Percentile [5, 95] для 90% CI

Reference: Efron 1979 "Bootstrap methods", standard frequentist alternative
к Bayesian posterior CI на small N.

Computation: ~0.5-2 sec per channel × N=200 = ~5-30 sec total для n=18, 5 channels.
Acceptable for OLS path (1-sec training + 30-sec CI = honest small-data analysis).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def bootstrap_roi_ci(
    X: np.ndarray,
    y: np.ndarray,
    media_means: dict[str, float],
    media_cols: list[str],
    y_std: float,
    n_periods: int,
    raw_spend_totals: dict[str, float],
    raw_spend_series: dict[str, np.ndarray],
    adstock_config: dict[str, str],
    unit_costs: dict[str, float] | None = None,
    *,
    n_boot: int = 200,
    seed: int | None = 42,
    hdi_prob: float = 0.9,
    hill_alpha: float = 1.5,
    hill_gamma: float = 0.5,
    decay_default: float = 0.5,
) -> dict[str, dict[str, float]]:
    """Bootstrap ROI CI per channel via N=200 OLS resampling.

    C-OLS-1 fix (audit 2026-04-27): real per-period adstock+Hill computation
    matching decomposer.py exactly. Pre-fix used hill_at_one=hill(1.0) as
    constant approximation — Jensen's inequality bias (E[hill(X)] ≠ hill(E[X]))
    caused systematic 10-30% drift between bootstrap CI and decomposer point
    estimate когда spend variance высокая. UI showed "ROI 2.4 [bootstrap 1.5—2.0]"
    where 2.4 outside CI — confusing user.

    C-OLS-2 fix: tracking presence mask per channel — pre-fix indexing
    `samples[:successful]` could include zeros from skipped iterations
    (LinAlgError during specific iters left default zeros in array).
    Post-fix: bool mask tracks successful writes, percentile only on those.

    M-OLS-1 fix: returns HDI bounds via compute_ci_hdi (asymmetric-correct)
    instead of raw percentile (matches Bayesian path semantics).

    Args:
        X: design matrix (n_obs, p) — already adstock+Hill applied features (для refit)
        y: KPI vector normalized (n_obs,) — y_norm = (y - y_mean) / y_std
        media_means: per-channel adstock mean (consistent с ols_modeler normalization)
        media_cols: ordered media channel names (matches X columns 1: after intercept)
        y_std: y normalization std для denormalization
        n_periods: training periods (for total contribution)
        raw_spend_totals: per-channel total raw spend (for ROI denominator)
        raw_spend_series: per-channel raw spend per period (NEW C-OLS-1) для exact contribution
        adstock_config: per-channel adstock type (NEW C-OLS-1) — geometric/weibull
        unit_costs: per-channel ₽/native (для money-mode ROI; default 1.0)
        n_boot: bootstrap iterations (default 200)
        seed: RNG seed
        hdi_prob: HDI probability mass (default 0.9)
        hill_alpha, hill_gamma, decay_default: OLS-fixed defaults matching ols_modeler

    Returns:
        dict per channel: {ci_low, ci_high, ci_mean, ci_median, n_successful}
        on ROI scale (incremental contribution / spend_money).
    """
    from utils.adstock import apply_adstock
    from utils.saturation import hill_function
    # Reuse compute_ci_hdi for HDI semantics (M-OLS-1 unification)
    try:
        from utils.posterior_propagation import compute_ci_hdi
        _has_hdi = True
    except ImportError:
        _has_hdi = False

    rng = np.random.default_rng(seed)
    unit_costs = unit_costs or {}

    n_obs, p = X.shape
    if n_obs < 8 or p < 2:
        logger.warning("bootstrap_roi_ci: too few obs/params для honest bootstrap")
        return {}

    n_media = len(media_cols)

    # C-OLS-1: precompute exact per-period Hill saturation per channel using ORIGINAL
    # spend pattern + ols_modeler defaults. β_boot варьируется across bootstrap, но
    # adstock + Hill — consistent с ols_modeler training (matches decomposer downstream).
    sat_per_channel = {}  # {col: shape (n_periods,) of Hill values}
    for col in media_cols:
        raw = raw_spend_series.get(col)
        if raw is None or len(raw) == 0:
            sat_per_channel[col] = np.zeros(n_periods)
            continue
        a_type = adstock_config.get(col, 'geometric')
        adstocked = apply_adstock(raw, a_type, {'alpha': decay_default})
        mean_ch = max(media_means.get(col, 1.0), 1e-10)
        x_norm = adstocked / mean_ch
        sat_per_channel[col] = hill_function(np.maximum(x_norm, 0), hill_alpha, hill_gamma)

    # Bootstrap arrays + presence mask per channel
    roi_samples = {col: np.zeros(n_boot, dtype=np.float64) for col in media_cols}
    presence_mask = {col: np.zeros(n_boot, dtype=bool) for col in media_cols}

    successful = 0
    for boot_i in range(n_boot):
        # Resample indices with replacement
        idx = rng.integers(0, n_obs, size=n_obs)
        X_boot = X[idx]
        y_boot = y[idx]

        try:
            beta_boot, _, _, _ = np.linalg.lstsq(X_boot, y_boot, rcond=None)
        except np.linalg.LinAlgError:
            # Singular bootstrap sample — skip iteration (presence stays False)
            continue

        # Extract media betas (skip intercept at index 0)
        media_betas_boot = beta_boot[1:1 + n_media]

        # C-OLS-1: REAL per-period contribution computation (matches decomposer math).
        # contribution_total = β_j × sum_t(hill(x_norm_t)) × y_std
        for j, col in enumerate(media_cols):
            beta_j = float(media_betas_boot[j])
            spend_native = raw_spend_totals.get(col, 0)
            if spend_native <= 0:
                roi_samples[col][boot_i] = 0.0
                presence_mask[col][boot_i] = True  # zero IS valid result
                continue
            uc = float(unit_costs.get(col, 1.0) or 1.0)
            spend_money = spend_native * uc
            sat = sat_per_channel[col]
            contribution = beta_j * float(sat.sum()) * y_std
            roi_samples[col][boot_i] = contribution / spend_money if spend_money > 0 else 0.0
            presence_mask[col][boot_i] = True

        successful += 1

    if successful < n_boot * 0.5:
        logger.warning(
            f"bootstrap_roi_ci: only {successful}/{n_boot} successful resamples — "
            f"results may be unreliable (likely multicollinearity or bad data)"
        )

    # Compute HDI per channel (M-OLS-1: HDI not percentile — matches Bayesian semantics)
    result = {}
    for col in media_cols:
        valid = roi_samples[col][presence_mask[col]]
        if valid.size < 10:
            result[col] = {'ci_low': None, 'ci_high': None, 'ci_mean': None, 'ci_median': None}
            continue
        if _has_hdi:
            mean_v, ci_low, ci_high = compute_ci_hdi(valid, hdi_prob=hdi_prob)
        else:
            alpha = (1.0 - hdi_prob) / 2.0
            mean_v = float(np.mean(valid))
            ci_low = float(np.percentile(valid, alpha * 100))
            ci_high = float(np.percentile(valid, (1 - alpha) * 100))
        result[col] = {
            'ci_low': float(ci_low),
            'ci_high': float(ci_high),
            'ci_mean': float(mean_v),
            'ci_median': float(np.median(valid)),
            'n_successful': int(valid.size),
        }
    return result


def predictive_interval_y(
    x_new: np.ndarray,
    XtX_inv: np.ndarray,
    residual_std: float,
    dof: int,
    *,
    confidence: float = 0.9,
) -> tuple[float, float]:
    """Frequentist predictive interval для new y prediction (OLS).

    Formula: ŷ_new ± t_{dof, α/2} · σ · √(1 + x_new'(X'X)^(-1) x_new)

    Args:
        x_new: design row for new observation (p,)
        XtX_inv: precomputed (X'X)^(-1) from training
        residual_std: σ̂ from training (in normalized scale если y_norm используется)
        dof: degrees of freedom = n_obs - p
        confidence: PI mass (default 0.9 = 90%)

    Returns:
        (interval_half_width, leverage) — caller computes ŷ ± half_width.
    """
    try:
        from scipy import stats as scipy_stats
        t_crit = float(scipy_stats.t.ppf((1 + confidence) / 2, dof))
    except Exception:
        t_crit = 1.645  # large-sample normal fallback

    leverage = float(x_new @ XtX_inv @ x_new.T)
    se_pred = residual_std * np.sqrt(max(1.0 + leverage, 0.0))
    return t_crit * se_pred, leverage


def ols_diagnostics(
    X: np.ndarray,
    y: np.ndarray,
    beta_hat: np.ndarray,
    XtX_inv: np.ndarray | None,
) -> dict[str, Any]:
    """Standard OLS diagnostics: leverage, Cook's distance, VIF.

    Args:
        X: design matrix (n_obs, p)
        y: target (n_obs,)
        beta_hat: fitted coefficients (p,)
        XtX_inv: (X'X)^(-1) — None if singular

    Returns:
        dict with leverage_per_obs, cooks_distance_per_obs, vif_per_param,
        outlier_obs_indices (Cook's > 4/n), high_leverage_indices (h > 2p/n).
    """
    n, p = X.shape
    out = {
        'leverage': None,
        'cooks_distance': None,
        'vif': None,
        'outliers': [],
        'high_leverage': [],
    }

    if XtX_inv is None:
        return out

    try:
        # Hat matrix diagonal: H_ii = x_i' (X'X)^(-1) x_i
        H_diag = np.einsum('ij,jk,ik->i', X, XtX_inv, X)
        out['leverage'] = [round(float(h), 4) for h in H_diag]

        # Cook's distance: d_i = r_i² / (p · σ̂²) · h_ii / (1 - h_ii)²
        y_pred = X @ beta_hat
        resid = y - y_pred
        residual_var = float(np.sum(resid ** 2) / max(n - p, 1))
        cooks = (resid ** 2) / (p * max(residual_var, 1e-10)) * (H_diag / np.maximum((1 - H_diag) ** 2, 1e-10))
        out['cooks_distance'] = [round(float(c), 4) for c in cooks]

        # Cook's threshold: > 4/n suggests outlier
        cooks_threshold = 4.0 / n
        out['outliers'] = [int(i) for i, c in enumerate(cooks) if c > cooks_threshold]

        # High leverage threshold: h > 2p/n
        leverage_threshold = 2 * p / n
        out['high_leverage'] = [int(i) for i, h in enumerate(H_diag) if h > leverage_threshold]

        # VIF per parameter j: VIF_j = 1 / (1 - R²_j) where R²_j is from regressing X_j on other X.
        # Simplification: VIF_j = (X'X)^(-1)_jj · σ̂_j² where σ̂_j² is variance of X_j.
        # Practical formula: VIF_j = ((X'X)^(-1))_jj · sum((X_j - mean(X_j))^2)
        vif = []
        for j in range(p):
            xj_centered_var = float(np.sum((X[:, j] - X[:, j].mean()) ** 2))
            if xj_centered_var < 1e-10:
                vif.append(None)  # constant column (intercept) — VIF undefined
            else:
                vif.append(round(float(XtX_inv[j, j] * xj_centered_var), 3))
        out['vif'] = vif
    except Exception as e:
        logger.warning(f"ols_diagnostics computation failed: {type(e).__name__}: {e}")

    return out
