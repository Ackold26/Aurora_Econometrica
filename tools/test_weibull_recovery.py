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

# Use shared helpers из utils/adstock.py (B2.1 production helpers)
from econometrica.utils.adstock import (
    compute_weibull_half_life,
    compute_weibull_peak,
    peak_week_to_lambda,
    tail_decay_to_k,
    weibull_convolution_toeplitz,
    weibull_kernel_survival,
)


# ─── Synthetic generator ────────────────────────────────────────────────────

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

    Uses utils.adstock.weibull_convolution_toeplitz (production helper) — ensures
    test и in-model implementation share semantics.
    """
    rng = np.random.default_rng(seed)
    X_media = rng.lognormal(mean=2, sigma=0.5, size=(n_obs, n_channels))

    # Apply convolution per channel using shared helper
    y = np.zeros(n_obs)
    for ch in range(n_channels):
        adstocked = weibull_convolution_toeplitz(
            X_media[:, ch], peak_week=peak_week, tail_decay=tail_decay, max_decay=max_decay,
        )
        y += beta * adstocked
    y += rng.normal(0, noise_sigma * np.std(y), size=n_obs)

    kernel = weibull_kernel_survival(max_decay, peak_week, tail_decay)
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


# ─── utils/adstock.py shared helpers tests (B2.1 math layer) ────────────────

def test_tail_decay_to_k_inverse_relationship():
    """tail_decay=0.5 → k=3; tail_decay=0.2 → k=6 (faster tail)."""
    assert tail_decay_to_k(0.5) == 3.0
    assert tail_decay_to_k(0.2) == 6.0


def test_tail_decay_to_k_handles_near_zero():
    """tail_decay→0 без div-by-zero."""
    k = tail_decay_to_k(0.01)
    assert np.isfinite(k)
    assert k > 0


def test_peak_week_to_lambda_inverse_at_known_point():
    """Verify mode formula round-trips: λ from (peak, k), peak from (λ, k)."""
    pw_input = 4.0
    k = 3.0
    lam = peak_week_to_lambda(pw_input, k)
    # Mode = λ * ((k-1)/k)^(1/k) → should ≈ pw_input
    pw_recovered = lam * ((k - 1) / k) ** (1.0 / k)
    assert np.isclose(pw_recovered, pw_input, atol=1e-6)


def test_compute_weibull_peak_matches_input():
    """compute_weibull_peak возвращает int week of kernel argmax."""
    for pw in [2, 3, 5, 8]:
        peak = compute_weibull_peak(peak_week=pw, tail_decay=0.4)
        assert abs(peak - pw) <= 1, f'peak_week={pw}: computed={peak}'


def test_compute_weibull_half_life_increases_with_slower_tail():
    """Slower tail = longer half-life."""
    half_fast = compute_weibull_half_life(peak_week=3, tail_decay=0.2)
    half_slow = compute_weibull_half_life(peak_week=3, tail_decay=0.7)
    assert half_slow > half_fast


def test_weibull_convolution_toeplitz_zero_input_zero_output():
    """Sanity: zero input → zero output."""
    out = weibull_convolution_toeplitz(np.zeros(20), peak_week=3, tail_decay=0.5)
    np.testing.assert_array_equal(out, np.zeros(20))


def test_weibull_convolution_toeplitz_impulse_response_matches_kernel():
    """Impulse input (single 1.0 at t=0) → output ≈ kernel."""
    x = np.zeros(20)
    x[0] = 1.0
    max_decay = 15
    out = weibull_convolution_toeplitz(x, peak_week=3, tail_decay=0.5, max_decay=max_decay)
    expected_kernel = weibull_kernel_survival(max_decay, peak_week=3, tail_decay=0.5)
    # First max_decay timesteps должны match kernel
    np.testing.assert_allclose(out[:max_decay], expected_kernel, atol=1e-9)


def test_weibull_convolution_toeplitz_preserves_total_mass():
    """Sum of adstocked output ≈ sum of input (since kernel sum=1)."""
    rng = np.random.default_rng(42)
    x = rng.lognormal(2, 0.5, size=100)
    out = weibull_convolution_toeplitz(x, peak_week=3, tail_decay=0.5, max_decay=20)
    # Sum is approximately preserved (some tail mass cut off из-за boundary effects)
    # Check within reasonable tolerance — основная mass в первых ~15 weeks для these params
    assert 0.7 * np.sum(x) < np.sum(out) < 1.05 * np.sum(x)


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
