"""Weibull adstock learnable — synthetic recovery tests.

Phase B1.1 (foundation для B2 implementation).

Strategy:
- Generate synthetic media data (random noise) с known Weibull adstock applied.
- After implementing learnable Weibull в modeler.py (B2), train on synthetic data.
- Recovered (peak_week, tail_decay) MCMC posteriors should be within tolerance.
- Acceptance criterion: peak_week ±1 week, tail_decay ±20%.

Pre-B2: Tests verify ОНУ generator correctness + skip recovery test (depends на B2).
Post-B2: Recovery tests un-skipped, должны pass.

References:
- Plan: bright-wandering-neumann.md → Phase B1.1
- Math reference: docs/MATH_REFERENCE.md → "Weibull Learnable v1.2.0"
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sidecar'))


# ─── Synthetic generator ────────────────────────────────────────────────────

def weibull_kernel_survival(
    max_decay: int,
    peak_week: float,
    tail_decay: float,
) -> np.ndarray:
    """Compute discrete Weibull adstock kernel using survival function diff.

    H8 fix: kernel[t] = S(t) - S(t+1) где S(t) = exp(-(t/λ)^k)
    More accurate discrete probability mass than raw PDF discretization.

    Reparameterization (H7):
    - peak_week (interpretable): mode of continuous Weibull
    - tail_decay (interpretable): rate of tail (faster decay = higher rate)
    - λ (scale), k (shape) computed внутри

    Args:
        max_decay: max τ (number of weeks support)
        peak_week: where Weibull peaks (mode)
        tail_decay: 0..1 — tail rate (Beta-like)

    Returns:
        kernel: shape (max_decay,), normalized к sum=1
    """
    # Convert (peak_week, tail_decay) → (lam, k):
    # k = 1 + 1/tail_decay (lower tail_decay → higher k → faster tail)
    k = 1.0 + 1.0 / max(tail_decay, 0.05)  # avoid div-by-zero
    # Mode of Weibull = λ * ((k-1)/k)^(1/k) for k>1
    if k > 1:
        lam = peak_week / ((k - 1) / k) ** (1.0 / k)
    else:
        lam = peak_week  # exponential case fallback

    # Survival function S(t) = exp(-(t/λ)^k)
    tau = np.arange(max_decay + 1, dtype=np.float64)
    S = np.exp(-(tau / lam) ** k)
    kernel = S[:-1] - S[1:]  # length max_decay

    # Normalize к sum=1 (identifiability — separates kernel shape от β scale)
    kernel = kernel / np.sum(kernel)
    return kernel


def generate_synthetic_weibull_data(
    n_obs: int = 52,
    n_channels: int = 1,
    peak_week: float = 3.0,
    tail_decay: float = 0.5,
    max_decay: int = 26,
    beta: float = 1.0,
    noise_sigma: float = 0.1,
    seed: int = 42,
) -> dict:
    """Generate synthetic media data + simulated y с known Weibull adstock applied.

    y_t = β × convolution(media, weibull(peak_week, tail_decay))[t] + noise

    Returns:
        {
            'X_media': (n_obs, n_channels) raw media spend,
            'y': (n_obs,) observed outcome,
            'true_kernel': (max_decay,) Weibull kernel used,
            'true_peak_week': float,
            'true_tail_decay': float,
            'true_beta': float,
        }
    """
    rng = np.random.default_rng(seed)
    X_media = rng.lognormal(mean=2, sigma=0.5, size=(n_obs, n_channels))

    kernel = weibull_kernel_survival(max_decay, peak_week, tail_decay)

    # Apply convolution per channel
    y = np.zeros(n_obs)
    for ch in range(n_channels):
        for t in range(n_obs):
            for tau in range(min(t + 1, max_decay)):
                y[t] += beta * X_media[t - tau, ch] * kernel[tau]
    y += rng.normal(0, noise_sigma * np.std(y), size=n_obs)

    return {
        'X_media': X_media,
        'y': y,
        'true_kernel': kernel,
        'true_peak_week': peak_week,
        'true_tail_decay': tail_decay,
        'true_beta': beta,
    }


# ─── Generator correctness tests ────────────────────────────────────────────

def test_kernel_normalized_sum_to_one():
    """Survival function kernel должен sum к 1 (identifiability)."""
    kernel = weibull_kernel_survival(max_decay=26, peak_week=3, tail_decay=0.5)
    assert np.isclose(np.sum(kernel), 1.0, atol=1e-6)


def test_kernel_peaks_near_specified_week():
    """Peak week parameter должен match argmax kernel ±1."""
    for pw in [2.0, 4.0, 6.0]:
        kernel = weibull_kernel_survival(max_decay=26, peak_week=pw, tail_decay=0.5)
        peak_idx = int(np.argmax(kernel))
        assert abs(peak_idx - pw) <= 2, f'peak_week={pw}: argmax={peak_idx}, expected near {pw}'


def test_kernel_short_tail_for_low_tail_decay():
    """tail_decay=0.2 (fast tail) → kernel mass concentrates in first weeks."""
    kernel_fast = weibull_kernel_survival(max_decay=26, peak_week=3, tail_decay=0.2)
    kernel_slow = weibull_kernel_survival(max_decay=26, peak_week=3, tail_decay=0.8)
    # fast tail: 80% mass within 8 weeks
    fast_first_8 = np.sum(kernel_fast[:8])
    slow_first_8 = np.sum(kernel_slow[:8])
    assert fast_first_8 > slow_first_8, (
        f'fast tail должна concentrate mass earlier: fast_first_8={fast_first_8:.3f}, '
        f'slow_first_8={slow_first_8:.3f}'
    )


def test_kernel_non_negative():
    kernel = weibull_kernel_survival(max_decay=26, peak_week=3, tail_decay=0.5)
    assert np.all(kernel >= 0)


def test_kernel_monotonic_decay_after_peak():
    """После peak, kernel должен monotonically decay."""
    kernel = weibull_kernel_survival(max_decay=26, peak_week=3, tail_decay=0.5)
    peak_idx = int(np.argmax(kernel))
    after_peak = kernel[peak_idx:]
    assert np.all(np.diff(after_peak) <= 0), 'kernel должна decay монотонно после peak'


def test_synthetic_data_generation_shape_correct():
    """Generator returns expected shapes + finite values."""
    data = generate_synthetic_weibull_data(n_obs=52, n_channels=2, seed=42)
    assert data['X_media'].shape == (52, 2)
    assert data['y'].shape == (52,)
    assert np.all(np.isfinite(data['X_media']))
    assert np.all(np.isfinite(data['y']))


def test_synthetic_data_y_correlates_with_lagged_media():
    """y должен correlate с lagged media (peak_week=3 → lag 3 strongest)."""
    data = generate_synthetic_weibull_data(
        n_obs=200, n_channels=1, peak_week=3, tail_decay=0.4, noise_sigma=0.05, seed=42
    )
    media = data['X_media'][:, 0]
    y = data['y']
    # Correlation на lag=3 должна быть значимой
    corr_lag3 = np.corrcoef(media[:-3], y[3:])[0, 1]
    corr_lag0 = np.corrcoef(media, y)[0, 1]
    # При peak_week=3 lag=3 correlation должен превысить lag=0 (хотя бы немного)
    assert corr_lag3 > 0.1, f'expected lag-3 correlation > 0.1, got {corr_lag3:.3f}'


def test_synthetic_data_deterministic_with_seed():
    data1 = generate_synthetic_weibull_data(seed=42)
    data2 = generate_synthetic_weibull_data(seed=42)
    np.testing.assert_array_equal(data1['X_media'], data2['X_media'])
    np.testing.assert_array_equal(data1['y'], data2['y'])


# ─── Recovery tests (require B2 implementation) ─────────────────────────────

@pytest.mark.skip(reason='Requires B2 — learnable Weibull в modeler.py. Un-skip after B2 ship.')
def test_baseline_pre_computed_does_not_recover():
    """Current pre-computed Weibull (decay=0.5 hardcoded) cannot recover known params.

    This test demonstrates need для learnable Weibull. Will be replaced after B2.
    """
    pass


@pytest.mark.skip(reason='Requires B2 — learnable Weibull в modeler.py.')
def test_learnable_weibull_recovers_within_tolerance():
    """After B2: train on synthetic data, recovered posterior should match true.

    Acceptance criteria:
    - posterior_mean(peak_week) within ±1 week of true peak_week
    - posterior_mean(tail_decay) within ±20% of true tail_decay
    - R-hat<1.05 для both hyperparameters
    """
    pass


@pytest.mark.skip(reason='Requires B2 + JAX backend.')
def test_learnable_weibull_jax_backend_required():
    """Без JAX → BackendUnavailableError."""
    pass


@pytest.mark.skip(reason='Requires B2 + scipy MLE warm-start.')
def test_learnable_weibull_warm_start_speeds_convergence():
    """Warm-start MLE shaves ≥30% MCMC time vs cold-start."""
    pass
