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
        adstock_type: 'geometric' or 'weibull'
        params: Optional parameters override
    """
    params = params or {}
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
