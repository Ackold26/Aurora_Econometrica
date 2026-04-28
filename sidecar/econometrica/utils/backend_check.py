"""
Aurora Econometrica — backend availability check (v2.0+).

JAX/NumPyro mandatory для learnable Weibull adstock (Phase 1.5):
- Toeplitz convolution в pt.scan на CPU = unbearable MCMC time.
- JAX SIMD JIT + GPU optional → 10-50× speed-up.

Helpers used в modeler.py BEFORE PyMC sampling configures backend.

References:
- Plan: bright-wandering-neumann.md → Phase B0.3
- Math reference: docs/MATH_REFERENCE.md → "Weibull Learnable Performance"
"""
from __future__ import annotations

from typing import Dict, List


def is_jax_available() -> bool:
    """True если JAX + NumPyro importable (PyMC NumPyro backend usable)."""
    try:
        import jax  # noqa: F401
        import numpyro  # noqa: F401
        return True
    except ImportError:
        return False


def is_pymc_available() -> bool:
    """True если PyMC importable (always required для модели)."""
    try:
        import pymc  # noqa: F401
        return True
    except ImportError:
        return False


def get_backend_summary() -> Dict[str, bool]:
    """Snapshot всех backends — для diagnostic UI."""
    return {
        'pymc': is_pymc_available(),
        'jax': is_jax_available(),
        'numpyro': is_jax_available(),  # numpyro = JAX-based
    }


def enforce_jax_for_weibull(channel_adstock_types: Dict[str, str]) -> None:
    """Raise если any channel set to Weibull без JAX backend.

    Args:
        channel_adstock_types: dict {channel: 'geometric'|'weibull'}

    Raises:
        BackendUnavailableError: если any Weibull channel + JAX missing.
    """
    weibull_channels = [
        col for col, t in channel_adstock_types.items() if t == 'weibull'
    ]
    if not weibull_channels:
        return  # all geometric — no requirement

    if not is_jax_available():
        raise BackendUnavailableError(
            f"Weibull learnable adstock requires JAX/NumPyro backend, "
            f"но они недоступны. Channels с Weibull: {sorted(weibull_channels)}. "
            f"Решения:\n"
            f"  (1) install: pip install jax numpyro\n"
            f"  (2) переключить эти каналы на 'geometric' в Validate UI"
        )


class BackendUnavailableError(RuntimeError):
    """Raised when a required backend (JAX/NumPyro) не установлен."""
    pass
