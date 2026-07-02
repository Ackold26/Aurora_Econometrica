"""
Adstock transformations for Marketing Mix Modeling.
Geometric (digital channels) and Weibull (TV/offline with delayed peak).

v1.2.0 additions (Phase 1.5 - Weibull learnable):
- weibull_kernel_survival: discrete kernel via S(t)-S(t+1) (H8 fix)
- weibull_convolution_toeplitz: numpy reference impl для testing math
- compute_weibull_peak / compute_weibull_half_life: metric helpers для reporting
- peak_week_to_lambda / tail_decay_to_k: parameter conversion helpers
"""
import logging

import numpy as np

logger = logging.getLogger(__name__)

# Мат-аудит 2026-07-02 (F-07): однократный лог на процесс для каждого
# неизвестного adstock_type — иначе тихий geometric-fallback маскирует
# опечатку/битый конфиг ('Weibull', 'weibul', мусор из legacy pickle).
_warned_unknown_types: set[str] = set()


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
    if weights.sum() > 0:
        weights = weights / weights.sum()
    else:
        # Мат-аудит 2026-07-02 (F-08): вырожденное ядро (underflow при
        # экстремальных shape/scale) прежде уходило в convolve молча —
        # канал занулялся без следа. Численное поведение сохранено
        # (детерминизм), добавлена наблюдаемость.
        logger.warning(
            'weibull_adstock: вырожденное ядро (weights.sum()=0) при '
            'shape=%.4g scale=%.4g max_lag=%d — канал получит ~нулевой '
            'adstock. Проверьте параметры Weibull.',
            shape, scale, max_lag,
        )

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
        # F0.5 (Phase 0.1): no carryover - used for analytical math tests where
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
        # Мат-аудит 2026-07-02 (F-07): неизвестный тип прежде падал в geometric
        # МОЛЧА — 'Weibull'/'weibul'/мусор из конфига незаметно менял модель
        # переноса. Fallback сохранён (back-compat, детерминизм), но с
        # однократным warning на процесс для каждого нового неизвестного типа.
        if adstock_type != 'geometric' and adstock_type not in _warned_unknown_types:
            _warned_unknown_types.add(adstock_type)
            logger.warning(
                "apply_adstock: неизвестный adstock_type=%r — fallback на "
                "geometric. Допустимые: 'geometric', 'weibull', 'noop'/'none'. "
                "Проверьте adstock_config (опечатка/регистр?).",
                adstock_type,
            )
        return geometric_adstock(
            series,
            alpha=params.get('alpha', 0.5),
        )


# ─────────────────────────────────────────────────────────────────────
# Phase 1.1 - vectorized batch variants for posterior CI propagation
# ─────────────────────────────────────────────────────────────────────


def geometric_adstock_batch(raw_x: np.ndarray, decay_samples: np.ndarray) -> np.ndarray:
    """Vectorized geometric adstock across posterior samples.

    For each posterior sample i, compute geometric_adstock(raw_x, decay_samples[i]).
    Inner loop is vectorized over samples - 36 sequential time-step ops × broadcast
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
    """Vectorized adstock sensitivity factor - ∂(_flat_alloc_adstock_avg)/∂x.

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
        # Avoid θ=1 singularity (geometric series diverges) - clip decay slightly < 1
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
        # weibull doesn't actually use decay scalar - kept for API symmetry; return 1.0 fallback
        out[i] = 1.0
    return out


# ─── v1.2.0: Weibull Learnable Adstock helpers ──────────────────────────────


def tail_decay_to_k(tail_decay: float) -> float:
    """Convert tail_decay (Beta-like 0..1) → k (Weibull shape).

    Higher tail_decay = slower tail = lower k.
    Lower tail_decay = faster tail = higher k.

    Formula: k = 1 + 1/tail_decay (clamped к avoid div-by-zero).
    """
    return 1.0 + 1.0 / max(float(tail_decay), 0.05)


def peak_week_to_lambda(peak_week: float, k: float) -> float:
    """Convert (peak_week, k) → λ (Weibull scale).

    Mode of continuous Weibull = λ × ((k-1)/k)^(1/k) для k > 1.
    Inverse: λ = peak_week / ((k-1)/k)^(1/k).
    """
    if k <= 1:
        return float(peak_week)  # exponential fallback
    return float(peak_week) / ((k - 1) / k) ** (1.0 / k)


def weibull_kernel_survival(
    max_decay: int,
    peak_week: float,
    tail_decay: float,
) -> np.ndarray:
    """Discrete Weibull adstock kernel via survival function differences (H8 fix).

    kernel[t] = S(t) - S(t+1) где S(t) = exp(-(t/λ)^k).
    Normalized к sum=1 для identifiability (kernel shape vs β scale).

    Args:
        max_decay: kernel support length (typically min(T//4, 52)). Must be ≥ 1.
        peak_week: where Weibull peaks (mode), > 0
        tail_decay: tail rate (0..1, Beta-like), interpretable, > 0

    Returns:
        kernel: shape (max_decay,), sums к 1.0

    Raises:
        ValueError: если max_decay < 1 OR peak_week ≤ 0 OR tail_decay ≤ 0.
    """
    if not isinstance(max_decay, (int, np.integer)) or max_decay < 1:
        raise ValueError(f"max_decay={max_decay} must be positive integer ≥ 1")
    if peak_week <= 0:
        raise ValueError(f"peak_week={peak_week} must be > 0")
    if tail_decay <= 0:
        raise ValueError(f"tail_decay={tail_decay} must be > 0 (use small ε для very fast tail)")

    k = tail_decay_to_k(tail_decay)
    lam = peak_week_to_lambda(peak_week, k)

    tau = np.arange(max_decay + 1, dtype=np.float64)
    S = np.exp(-(tau / lam) ** k)
    kernel = S[:-1] - S[1:]
    kernel_sum = np.sum(kernel)
    if kernel_sum < 1e-12:
        # Degenerate case - return uniform fallback
        return np.full(max_decay, 1.0 / max_decay, dtype=np.float64)
    return kernel / kernel_sum


def weibull_convolution_toeplitz(
    x: np.ndarray,
    peak_week: float = 3.0,
    tail_decay: float = 0.5,
    max_decay: int = 26,
) -> np.ndarray:
    """Numpy reference implementation of Weibull adstock convolution.

    adstock[t] = Σ_τ x[t-τ] × kernel[τ]   для τ ∈ [0, min(t, max_decay))

    Uses Toeplitz-style accumulation. Reference for PyTensor in-model implementation
    (matches semantics 1:1 для test parity).

    Args:
        x: media spend time series, shape (T,)
        peak_week: Weibull mode (interpretable param)
        tail_decay: tail rate 0..1 (interpretable param)
        max_decay: kernel support length

    Returns:
        adstocked: shape (T,)
    """
    x = np.asarray(x, dtype=np.float64)
    T = len(x)
    kernel = weibull_kernel_survival(max_decay, peak_week, tail_decay)

    # Convolution (causal - only past contributions)
    adstocked = np.zeros(T)
    for t in range(T):
        for tau in range(min(t + 1, max_decay)):
            adstocked[t] += x[t - tau] * kernel[tau]
    return adstocked


def compute_weibull_peak(peak_week: float, tail_decay: float) -> int:
    """Return integer week of kernel peak (argmax) для reporting/UI."""
    kernel = weibull_kernel_survival(max_decay=52, peak_week=peak_week, tail_decay=tail_decay)
    return int(np.argmax(kernel))


def compute_weibull_half_life(peak_week: float, tail_decay: float) -> float:
    """Half-life: smallest week k где cumulative kernel mass ≥ 0.5.

    Audit fix: boundary checks ПЕРЕД interpolation (avoid cum[-1] wrap-around
    при degenerate kernel где first element ≥ 0.5).

    Returns:
        Half-life в weeks (float, may be fractional via interpolation).
    """
    kernel = weibull_kernel_survival(max_decay=52, peak_week=peak_week, tail_decay=tail_decay)
    cum = np.cumsum(kernel)
    if len(cum) == 0:
        return 0.0
    half_idx = int(np.searchsorted(cum, 0.5, side='left'))
    # Boundary checks FIRST (avoid wrap-around в cum[-1] для degenerate cases)
    if half_idx == 0:
        # First element already ≥ 0.5 (heavy front-load) → half-life ≈ 0.5 week
        return 0.5
    if half_idx >= len(cum):
        # Cumulative mass never reaches 0.5 (degenerate) → half-life = full support
        return float(len(cum))
    # Linear interp between half_idx-1 (cum<0.5) и half_idx (cum≥0.5)
    prev_cum = cum[half_idx - 1]
    cur_cum = cum[half_idx]
    if cur_cum == prev_cum:
        return float(half_idx)
    frac = (0.5 - prev_cum) / (cur_cum - prev_cum)
    return float(half_idx - 1) + frac
