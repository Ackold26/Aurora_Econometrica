"""
Saturation (diminishing returns) functions for MMM.
Hill function: models the law of diminishing returns per channel.
"""
import numpy as np


def hill_function(x: np.ndarray, alpha: float = 1.0, gamma: float = 0.5) -> np.ndarray:
    """Hill saturation function.

    As spend increases, incremental effect diminishes.
    S-curve shape controlled by alpha (steepness) and gamma (half-saturation point).

    Args:
        x: Adstocked spend/impressions (non-negative)
        alpha: Steepness. >1 = S-curve, =1 = Michaelis-Menten, <1 = concave
        gamma: Half-saturation point (x at 50% max effect)
    Returns:
        Saturated effect (0 to 1 scale)
    """
    x_safe = np.maximum(x, 0.0)
    gamma_safe = max(gamma, 1e-10)
    return x_safe ** alpha / (x_safe ** alpha + gamma_safe ** alpha)


def marginal_roi(x: np.ndarray, alpha: float, gamma: float, beta: float,
                 delta: float = 1.0) -> np.ndarray:
    """Marginal ROI: derivative of Hill function × channel coefficient.

    Args:
        x: Current spend level
        alpha, gamma: Hill parameters
        beta: Channel coefficient from model
        delta: Spend normalization factor
    Returns:
        Marginal ROI at each spend level
    """
    x_safe = np.maximum(x, 1e-10)
    gamma_safe = max(gamma, 1e-10)
    # Derivative of Hill: alpha * gamma^alpha * x^(alpha-1) / (x^alpha + gamma^alpha)^2
    numerator = alpha * (gamma_safe ** alpha) * (x_safe ** (alpha - 1))
    denominator = (x_safe ** alpha + gamma_safe ** alpha) ** 2
    return beta * numerator / (denominator * delta)


def response_curve(spend_range: np.ndarray, alpha: float, gamma: float,
                   beta: float) -> np.ndarray:
    """Full response curve: spend → predicted contribution.

    Args:
        spend_range: Array of spend values (e.g., linspace 0 to 2×current)
        alpha, gamma: Hill parameters
        beta: Channel coefficient
    Returns:
        Predicted contribution at each spend level
    """
    saturated = hill_function(spend_range, alpha, gamma)
    return beta * saturated


# ─────────────────────────────────────────────────────────────────────
# Phase 1.9 — vectorized batch variants for posterior CI propagation
# ─────────────────────────────────────────────────────────────────────


def hill_function_batch(
    x_norm: np.ndarray,
    alpha_samples: np.ndarray,
    gamma_samples: np.ndarray,
) -> np.ndarray:
    """Vectorized Hill saturation across posterior samples.

    Computes hill(x_norm) for all (alpha_i, gamma_i) sample pairs simultaneously
    via numpy broadcasting. Joint correlation preserved — sample i uses
    alpha_samples[i] and gamma_samples[i] (corresponding draw).

    Args:
        x_norm: 1D array of normalized spend values (shape n_periods,) or scalar
        alpha_samples: 1D array of α posterior draws (shape n_samples,)
        gamma_samples: 1D array of γ posterior draws (shape n_samples,)
    Returns:
        Saturated values, shape (n_samples, n_periods).
        sat[i, t] = hill(x_norm[t]; alpha_samples[i], gamma_samples[i])
    """
    x_arr = np.atleast_1d(np.asarray(x_norm, dtype=np.float64))  # shape (n_periods,)
    alpha = np.asarray(alpha_samples, dtype=np.float64).reshape(-1, 1)  # (n_samples, 1)
    gamma = np.asarray(gamma_samples, dtype=np.float64).reshape(-1, 1)  # (n_samples, 1)

    x_safe = np.maximum(x_arr, 0.0).reshape(1, -1)  # (1, n_periods)
    gamma_safe = np.maximum(gamma, 1e-10)            # (n_samples, 1)
    x_pos = np.maximum(x_safe, 1e-10)                # avoid 0**negative
    # Broadcasting: result shape (n_samples, n_periods)
    x_pow = x_pos ** alpha
    gamma_pow = gamma_safe ** alpha
    return x_pow / (x_pow + gamma_pow)


def hill_derivative_batch(
    x_norm: np.ndarray,
    alpha_samples: np.ndarray,
    gamma_samples: np.ndarray,
) -> np.ndarray:
    """Vectorized Hill derivative across posterior samples.

    Used by optimizer / mROAS computation. Same broadcasting pattern as
    hill_function_batch.

    Formula: hill'(x) = α·γ^α·x^(α-1) / (x^α + γ^α)²

    Args:
        x_norm: 1D array of normalized spend values or scalar
        alpha_samples: 1D array of α posterior draws (shape n_samples,)
        gamma_samples: 1D array of γ posterior draws
    Returns:
        Derivative values, shape (n_samples, n_periods).
    """
    x_arr = np.atleast_1d(np.asarray(x_norm, dtype=np.float64))
    alpha = np.asarray(alpha_samples, dtype=np.float64).reshape(-1, 1)
    gamma = np.asarray(gamma_samples, dtype=np.float64).reshape(-1, 1)

    x_safe = np.maximum(x_arr, 1e-10).reshape(1, -1)
    gamma_safe = np.maximum(gamma, 1e-10)

    x_pow_alpha = x_safe ** alpha
    gamma_pow_alpha = gamma_safe ** alpha
    numerator = alpha * gamma_pow_alpha * (x_safe ** (alpha - 1.0))
    denominator = (x_pow_alpha + gamma_pow_alpha) ** 2
    return numerator / denominator
