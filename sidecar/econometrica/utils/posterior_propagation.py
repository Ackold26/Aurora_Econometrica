"""
Posterior CI propagation helpers (Phase 1.9).

Centralizes CI computation, tail-ESS checks, verdict tier classification, and
backward-compat loading of posterior samples from pickle.

Single source of truth for honest uncertainty quantification across
decomposer / scenario / optimizer / narrative engines.

Math reference: docs/SPRINT1_FOUNDATION_ADR.md §3 (Amendments A3, A4, A5)
                docs/MATH_AUDIT_v1_3_PHASE_0_1.md §3 (mROAS chain rule)

Uses arviz.hdi for asymmetric posterior support (mROAS is non-linear function of
α/γ/β — point posterior may be skewed, percentile gives misleading "CI", HDI is
narrowest interval containing prob mass and is correct for asymmetric distributions).
"""
from __future__ import annotations

from typing import Any

import numpy as np

try:
    import arviz as az
    _HAS_ARVIZ = True
except ImportError:
    _HAS_ARVIZ = False


# Default CI probability mass (per ADR Amendment A3 — industry standard 90%
# matches Meridian, Recast, LightweightMMM; PyMC-Marketing's 94% is a protest, not standard).
DEFAULT_HDI_PROB = 0.9


def compute_ci_hdi(
    samples: np.ndarray,
    hdi_prob: float = DEFAULT_HDI_PROB,
) -> tuple[float, float, float]:
    """Compute mean + HDI bounds from posterior samples.

    Uses arviz.hdi (Highest Density Interval) — narrowest interval containing
    `hdi_prob` probability mass. Correct for asymmetric posteriors (mROAS,
    optimizer lift). Falls back to equal-tail percentile if arviz unavailable
    or computation fails.

    Args:
        samples: 1D array of posterior draws (after flattening chains × draws).
        hdi_prob: probability mass (default 0.9 = 90% CI).

    Returns:
        (mean, ci_low, ci_high). All floats. Returns (0, 0, 0) for empty/invalid.
        For samples.size < 4 (degenerate), returns mean as both bounds.
    """
    arr = np.asarray(samples).ravel()
    if arr.size == 0:
        return (0.0, 0.0, 0.0)

    # Filter NaN/inf defensively
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return (0.0, 0.0, 0.0)

    mean = float(arr.mean())
    if arr.size < 4:
        return (mean, mean, mean)

    if _HAS_ARVIZ:
        try:
            hdi = az.hdi(arr, hdi_prob=hdi_prob)
            return (mean, float(hdi[0]), float(hdi[1]))
        except Exception:
            pass

    # Fallback: equal-tail percentile
    alpha = (1.0 - hdi_prob) / 2.0
    low = float(np.percentile(arr, alpha * 100))
    high = float(np.percentile(arr, (1.0 - alpha) * 100))
    return (mean, low, high)


def tail_ess_threshold(n_chains: int) -> int:
    """Vehtari rule (2021): tail_ess >= 100 * n_chains for stable percentile estimation.

    Bulk-ESS is for mean accuracy; Tail-ESS is the right metric for CI bounds.
    """
    return 100 * max(int(n_chains), 1)


def load_posterior_samples(model_data: dict) -> dict | None:
    """Backward-compatible loader for posterior samples from pickle.

    Returns:
        dict with keys {media_betas, alphas, gammas, intercept, control_betas,
        media_columns, control_columns, n_chains, n_draws} for v1.1.5+ pickles.
        None for v1.0/v1.1 pickles (caller falls back to point estimate + warns).

    Schema validation: missing keys → return None (corrupted, treat as legacy).
    """
    samples = model_data.get('posterior_samples')
    if samples is None or not isinstance(samples, dict):
        return None

    required = {'media_betas', 'alphas', 'gammas', 'intercept', 'media_columns'}
    if not required.issubset(samples.keys()):
        return None

    return samples


def verdict_tier(
    mean: float | None,
    ci_low: float | None,
    ci_high: float | None,
    *,
    n_obs: int | None = None,
    r_hat: float | None = None,
    tail_ess_ok: bool | None = None,
) -> tuple[str, str, float]:
    """3-tier verdict per ADR Amendment A5 + conditional gates.

    Tier thresholds (relative_width = (ci_high - ci_low) / |mean|):
        < 0.5  → "Уверенная оценка"           (good)
        0.5-1.0 → "Направленная оценка"       (warn)
        > 1.0  → "Высокая неопределённость"   (bad)

    Conditional gates (auto-downgrade):
        - n_obs < 30 + relative_width < 0.5 → force "Направленная" (small-N can
          artificially tighten CI; don't trust narrow CI on tiny samples)
        - r_hat > 1.05 → force "Высокая неопределённость" (model not converged,
          CI itself is unreliable)
        - tail_ess_ok=False → caller should annotate "оценка нестабильна" (does
          NOT change tier — annotation only, since CI is still computable just less precise)

    H2 fix (audit 2026-04-26): default tail_ess_ok changed True → None to force
    explicit caller decision. None means "not checked" (skip gate); True/False means
    explicit assertion. Pre-fix default True silently skipped warning even when
    caller forgot to compute it.

    Returns:
        (tier_label, tone, relative_width).
        tier_label: one of three Russian strings above.
        tone: 'good' | 'warn' | 'bad'.
        relative_width: width / |mean| (inf for degenerate).
    """
    if mean is None or ci_low is None or ci_high is None:
        return ("Высокая неопределённость", "bad", float('inf'))
    if abs(mean) < 1e-10:
        return ("Высокая неопределённость", "bad", float('inf'))

    width = float(ci_high) - float(ci_low)
    relative_width = width / abs(float(mean))

    # Hard gate 1: model didn't converge
    if r_hat is not None and r_hat > 1.05:
        return ("Высокая неопределённость", "bad", relative_width)

    # Soft gate: small-N + narrow CI → suspect over-confidence
    if (n_obs is not None and n_obs < 30
            and relative_width < 0.5):
        return ("Направленная", "warn", relative_width)

    # Standard 3-tier classification
    if relative_width < 0.5:
        return ("Уверенная", "good", relative_width)
    elif relative_width < 1.0:
        return ("Направленная", "warn", relative_width)
    else:
        return ("Высокая неопределённость", "bad", relative_width)


def channel_index(samples: dict, channel_name: str) -> int | None:
    """Find channel index in posterior samples by name. Returns None if missing."""
    cols = samples.get('media_columns', [])
    try:
        return cols.index(channel_name)
    except ValueError:
        return None


def per_channel_samples(samples: dict, channel_name: str) -> dict[str, np.ndarray] | None:
    """Extract joint posterior arrays for a single channel.

    Joint structure preserved — alpha/gamma/beta/decay arrays indexed by same
    draws, so correlation between params on the same draw is intact.

    Phase 1.1 addition: if 'adstock_decay' present in samples (v1.2 pickles),
    return 'decay' key. None for v1.1.5 (decay hardcoded at default).

    Returns:
        {'alpha': arr, 'gamma': arr, 'beta': arr [, 'decay': arr]}
        each shape (n_samples,) float32. None if channel not found.
    """
    idx = channel_index(samples, channel_name)
    if idx is None:
        return None
    out = {
        'alpha': np.asarray(samples['alphas'][idx], dtype=np.float32),
        'gamma': np.asarray(samples['gammas'][idx], dtype=np.float32),
        'beta': np.asarray(samples['media_betas'][idx], dtype=np.float32),
        # M1 fix (audit 2026-04-26): always set 'decay' key (None when missing) для
        # API ergonomics. Pre-fix conditionally added — caller had to check `if 'decay' in ch`
        # which differs from "decay is None" semantically. Now uniformly: ch_samples['decay']
        # always present; None means not learnable (v1.0/v1.1.5/v1.0-ols pickles).
        'decay': None,
    }
    if 'adstock_decay' in samples:
        decay_arr = np.asarray(samples['adstock_decay'], dtype=np.float32)
        if decay_arr.ndim == 2 and decay_arr.shape[0] > idx:
            out['decay'] = decay_arr[idx]
    return out
