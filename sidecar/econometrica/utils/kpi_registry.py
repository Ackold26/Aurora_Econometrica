"""
Aurora Econometrica — KPI registry (v2.0+).

Centralizes per-KPI configuration: likelihood, hyperpriors, ceiling, baseline drift.
Replaces hardcoded priors в modeler.py с extensible registry pattern (плагин для future
KPIs: leads, NPS, conversions без modeler.py refactor).

Usage:
    from utils.kpi_registry import KPI_REGISTRY, get_kpi_config

    config = get_kpi_config('awareness')  # raises ValueError if unknown
    likelihood = config.likelihood        # 'logit_normal'
    brand_mu, brand_sigma = config.brand_mu_logit_prior  # (1.4, 0.4)

References:
- Math reference: docs/MATH_REFERENCE.md → "KPI Registry v2.0"
- Plan: bright-wandering-neumann.md → Phase B0.1
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional, Tuple

# Likelihood choices
KPILikelihood = Literal['normal', 'logit_normal', 'beta']


@dataclass(frozen=True)
class KPIConfig:
    """Immutable KPI-specific model configuration.

    Frozen для defensive use (config объекты не mutate'ятся между runs).
    """
    name: str
    likelihood: KPILikelihood

    # Outcome bounds. None = unbounded (sales). 100 = awareness percent.
    ceiling: Optional[float]

    # Hierarchical adstock decay priors (logit-normal hyperpriors per group).
    # Sales: Trust 3 frozen values (modeler.py:408-411).
    # Awareness: longer brand build-up calibrated.
    brand_mu_logit_prior: Tuple[float, float]      # (mu, sigma)
    perf_mu_logit_prior: Tuple[float, float]
    mixed_mu_logit_prior: Tuple[float, float]

    # Group-level beta sigmas (HalfNormal). Trust 3 lines 367-369.
    brand_beta_sigma: float
    perf_beta_sigma: float
    mixed_beta_sigma: float

    # Hill saturation:
    #   gammas Beta(alpha, beta) — half-saturation point
    #   alphas — steepness
    gammas_alpha: float
    gammas_beta: float

    # Whether to add Gaussian random walk baseline drift (M2 fix для awareness).
    baseline_drift: bool

    # Observation noise prior σ (HalfNormal sigma).
    obs_sigma_prior: float

    # Phase 2 S7 (audit pass 2 2026-05-02) — KPI-aware forecast horizon settings.
    # Hard cap multiplier для forecast_periods / train_n. Sales=2.0 (Robyn/Meridian
    # convention); awareness ставит tighter (1.5) т.к. brand build-up длиннее →
    # β stationarity слабее. Backward compat: existing entries не нужно
    # обновлять — registered after these fields just inherit defaults.
    forecast_horizon_max_multiplier: float = 2.0
    # Soft warning threshold (forecast / train ratio above which user sees
    # «extrapolation warning»). Sales=1.5×, awareness=1.2×.
    forecast_horizon_warn_multiplier: float = 1.5


# ─── Registered KPIs ────────────────────────────────────────────────────────

KPI_REGISTRY: Dict[str, KPIConfig] = {
    'sales': KPIConfig(
        name='sales',
        likelihood='normal',
        ceiling=None,                              # unbounded
        # Trust 3 hierarchical priors (modeler.py:408-410) — FROZEN.
        brand_mu_logit_prior=(0.7, 0.3),           # ~12wk half-life
        perf_mu_logit_prior=(-1.4, 0.7),           # ~1.3wk half-life
        mixed_mu_logit_prior=(-1.4, 0.7),          # same as perf semantically
        # Trust 3 beta sigmas (modeler.py:367-369) — FROZEN.
        brand_beta_sigma=0.7,
        perf_beta_sigma=0.3,
        mixed_beta_sigma=0.4,
        # Trust 3 Hill (modeler.py:389) — FROZEN.
        gammas_alpha=3.0,
        gammas_beta=3.0,
        # No drift для sales (stationary intercept assumption OK).
        baseline_drift=False,
        # Trust 3 obs sigma (modeler.py:469) — FROZEN.
        obs_sigma_prior=0.3,
    ),

    'awareness': KPIConfig(
        name='awareness',
        likelihood='logit_normal',                  # bounded, logit-Normal stable
        ceiling=100.0,                              # awareness % cap
        # Awareness brand build-up длиннее: ~26wk (vs sales 12wk).
        # μ_logit=1.4 → sigmoid≈0.80 → ~26wk effective half-life.
        # NOTE: starting calibration. A1b real-data validation refines.
        brand_mu_logit_prior=(1.4, 0.4),
        # Performance не двигает awareness стабильно — ~4wk echo.
        perf_mu_logit_prior=(-0.7, 0.5),
        mixed_mu_logit_prior=(-0.7, 0.5),
        # Brand awareness highly correlated → looser sigma.
        # Performance limited contribution → tighter.
        brand_beta_sigma=0.5,
        perf_beta_sigma=0.2,
        mixed_beta_sigma=0.3,
        # Awareness saturation hard ceiling: tight Beta around ~0.3 (early saturation).
        # Beta(2, 5) — mean=0.286, mode=0.20, не за ~0.5.
        gammas_alpha=2.0,
        gammas_beta=5.0,
        # M2 fix: awareness drifts (long memory). RW baseline captures.
        baseline_drift=True,
        # Logit-scale obs sigma — typically smaller (data в [-∞, ∞] post-logit).
        obs_sigma_prior=0.5,
        # Phase 2 S7: awareness has longer brand build-up → tighter forecast cap.
        # Plan / Customer feedback recalibrates после Phase 3 awareness ship.
        forecast_horizon_max_multiplier=1.5,
        forecast_horizon_warn_multiplier=1.2,
    ),
}


def get_kpi_config(kpi_type: str) -> KPIConfig:
    """Lookup KPI config с explicit error если unknown.

    Args:
        kpi_type: KPI name (e.g. 'sales', 'awareness'). Must be non-None string.

    Returns:
        Frozen KPIConfig instance (safe — frozen dataclass + validated values).

    Raises:
        ValueError: если kpi_type не в KPI_REGISTRY OR not str OR None.
    """
    if not isinstance(kpi_type, str):
        raise ValueError(
            f"kpi_type must be string (got {type(kpi_type).__name__}={kpi_type!r})"
        )
    if kpi_type not in KPI_REGISTRY:
        valid = sorted(KPI_REGISTRY.keys())
        raise ValueError(f"Unknown kpi_type='{kpi_type}'. Valid: {valid}")
    return KPI_REGISTRY[kpi_type]


def list_kpi_types() -> tuple[str, ...]:
    """Return tuple of registered KPI types (UI dropdowns + Pydantic validation).

    Audit fix: returns immutable tuple (was list) — caller cannot mutate registry
    via returned collection.
    """
    return tuple(sorted(KPI_REGISTRY.keys()))


# ─── Validation на module import (fail-fast vs runtime surprise) ─────────────
def _validate_registry() -> None:
    """Module-load-time sanity check для KPI_REGISTRY entries."""
    for name, config in KPI_REGISTRY.items():
        if config.likelihood == 'logit_normal' or config.likelihood == 'beta':
            if config.ceiling is None or config.ceiling <= 0.1:
                raise ValueError(
                    f"KPI_REGISTRY['{name}']: bounded likelihood ({config.likelihood}) "
                    f"requires ceiling > 0.1 (got {config.ceiling}). "
                    f"Logit-Normal clipping breaks для small ceiling."
                )
        if config.brand_beta_sigma <= 0 or config.perf_beta_sigma <= 0 or config.mixed_beta_sigma <= 0:
            raise ValueError(
                f"KPI_REGISTRY['{name}']: beta sigmas must be positive"
            )
        if config.gammas_alpha <= 0 or config.gammas_beta <= 0:
            raise ValueError(
                f"KPI_REGISTRY['{name}']: Beta(α, β) для gammas requires α>0, β>0"
            )
        if config.obs_sigma_prior <= 0:
            raise ValueError(
                f"KPI_REGISTRY['{name}']: obs_sigma_prior must be positive"
            )


_validate_registry()
