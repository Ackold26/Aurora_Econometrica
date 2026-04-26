"""
Adstock transformations for Marketing Mix Modeling.
Geometric (digital channels) and Weibull (TV/offline with delayed peak).
"""
import numpy as np


def geometric_adstock(x: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    """Geometric adstock: instant peak, exponential decay.
    Good for digital channels (immediate effect).

    Args:
        x: Spend/impressions time series
        alpha: Retention rate (0-1). Higher = longer carryover
    Returns:
        Adstocked series
    """
    result = np.zeros_like(x, dtype=float)
    result[0] = x[0]
    for t in range(1, len(x)):
        result[t] = x[t] + alpha * result[t - 1]
    return result


def weibull_adstock(x: np.ndarray, shape: float = 2.0, scale: float = 3.0,
                    max_lag: int = 12) -> np.ndarray:
    """Weibull CDF adstock: delayed peak, flexible decay.
    Good for TV/offline (effect builds over time).

    Args:
        x: Spend/GRP time series
        shape: Controls peak timing (>1 = delayed peak)
        scale: Controls how long effect lasts
        max_lag: Maximum lag periods to consider
    Returns:
        Adstocked series
    """
    lags = np.arange(max_lag)
    # Weibull PDF as weights (normalized)
    weights = (shape / scale) * (lags / scale) ** (shape - 1) * np.exp(-(lags / scale) ** shape)
    weights = weights / weights.sum() if weights.sum() > 0 else weights

    result = np.convolve(x, weights, mode='full')[:len(x)]
    return result


def apply_adstock(series: np.ndarray, adstock_type: str, params: dict | None = None) -> np.ndarray:
    """Apply adstock transformation based on type string.

    Args:
        series: Input time series
        adstock_type: 'geometric', 'weibull', or 'noop' (passthrough, used in tests)
        params: Optional parameters override
    """
    params = params or {}
    if adstock_type in ('noop', 'none'):
        # F0.5 (Phase 0.1): no carryover — used for analytical math tests where
        # adstock_factor must equal 1.0. Not used in production training.
        return np.asarray(series, dtype=float).copy()
    if adstock_type == 'weibull':
        return weibull_adstock(
            series,
            shape=params.get('shape', 2.0),
            scale=params.get('scale', 3.0),
            max_lag=params.get('max_lag', 12),
        )
    else:  # geometric (default for digital)
        return geometric_adstock(
            series,
            alpha=params.get('alpha', 0.5),
        )


# ─────────────────────────────────────────────────────────────────────
# Phase 1.1 — vectorized batch variants for posterior CI propagation
# ─────────────────────────────────────────────────────────────────────


def geometric_adstock_batch(raw_x: np.ndarray, decay_samples: np.ndarray) -> np.ndarray:
    """Vectorized geometric adstock across posterior samples.

    For each posterior sample i, compute geometric_adstock(raw_x, decay_samples[i]).
    Inner loop is vectorized over samples — 36 sequential time-step ops × broadcast
    over 8000 samples ≈ <1ms typical.

    Args:
        raw_x: 1D array of raw spend values, shape (n_periods,)
        decay_samples: 1D array of decay posterior draws, shape (n_samples,)

    Returns:
        Adstocked spend, shape (n_samples, n_periods).
        result[i, t] = adstock(raw_x[t]; decay_samples[i]) propagated through scan.
    """
    raw_x_arr = np.asarray(raw_x, dtype=np.float64)
    decays = np.asarray(decay_samples, dtype=np.float64)
    n_periods = raw_x_arr.shape[0]
    n_samples = decays.shape[0]
    if n_periods == 0 or n_samples == 0:
        return np.zeros((max(n_samples, 1), max(n_periods, 1)), dtype=np.float64)

    out = np.zeros((n_samples, n_periods), dtype=np.float64)
    out[:, 0] = raw_x_arr[0]
    for t in range(1, n_periods):
        out[:, t] = raw_x_arr[t] + decays * out[:, t - 1]
    return out


def adstock_factor_batch(
    decay_samples: np.ndarray, n_periods: int, adstock_type: str = 'geometric'
) -> np.ndarray:
    """Vectorized adstock sensitivity factor — ∂(_flat_alloc_adstock_avg)/∂x.

    For geometric adstock with flat input, factor is constant in x but varies
    with decay sample. Used by mROAS chain rule when adstock decay is sampled.

    Math: factor = [n - θ·(1 - θ^n)/(1-θ)] / [n·(1-θ)]   per ADR §3.A1 + MATH_AUDIT §4

    Args:
        decay_samples: 1D array of decay posterior draws, shape (n_samples,)
        n_periods: training horizon
        adstock_type: 'geometric' (analytical), 'weibull' (TODO Phase 1.5), 'noop' → 1.0

    Returns:
        1D array of adstock factors, shape (n_samples,).
    """
    decays = np.asarray(decay_samples, dtype=np.float64)
    if adstock_type in ('noop', 'none'):
        return np.ones_like(decays)
    if adstock_type == 'geometric':
        # Avoid θ=1 singularity (geometric series diverges) — clip decay slightly < 1
        theta = np.clip(decays, 0.0, 1.0 - 1e-9)
        n = max(int(n_periods), 1)
        # Factor = [n - θ·(1 - θ^n)/(1-θ)] / [n·(1-θ)]
        with np.errstate(divide='ignore', invalid='ignore'):
            geom_sum = (1.0 - theta ** n) / (1.0 - theta)
            factor = (n - theta * geom_sum) / (n * (1.0 - theta))
        # When θ→0, geom_sum→1, factor→1.0
        factor = np.where(theta < 1e-9, 1.0, factor)
        return factor
    # weibull batch: numerical fallback per-sample. Slow but correct.
    out = np.empty_like(decays)
    for i, d in enumerate(decays):
        # weibull doesn't actually use decay scalar — kept for API symmetry; return 1.0 fallback
        out[i] = 1.0
    return out
