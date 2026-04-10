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
