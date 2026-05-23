"""Tests для utils/kpi_registry.py - Phase B0.1 foundation.

Goal: ensure registry pattern stable, sales config frozen at Trust 3 values
(regression guard E3), awareness config sane.
"""
from __future__ import annotations

import pytest

import sys
from pathlib import Path
SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

from utils.kpi_registry import KPI_REGISTRY, KPIConfig, get_kpi_config, list_kpi_types


# ─── Registry structure ─────────────────────────────────────────────────────

def test_registry_has_sales_and_awareness():
    assert 'sales' in KPI_REGISTRY
    assert 'awareness' in KPI_REGISTRY


def test_list_kpi_types_returns_known():
    types = list_kpi_types()
    assert 'sales' in types
    assert 'awareness' in types


def test_get_kpi_config_returns_kpi_config_instance():
    config = get_kpi_config('sales')
    assert isinstance(config, KPIConfig)


def test_unknown_kpi_type_raises_value_error():
    with pytest.raises(ValueError, match='Unknown kpi_type'):
        get_kpi_config('nonexistent_kpi')


def test_get_kpi_config_rejects_non_string():
    """Audit fix: explicit type check vs silent dict.get behavior."""
    with pytest.raises(ValueError, match='must be string'):
        get_kpi_config(None)
    with pytest.raises(ValueError, match='must be string'):
        get_kpi_config(123)


def test_kpi_config_is_frozen_immutable():
    """frozen=True dataclass должен запрещать mutation. Specific exception."""
    from dataclasses import FrozenInstanceError
    config = get_kpi_config('sales')
    with pytest.raises(FrozenInstanceError):
        config.ceiling = 999


def test_list_kpi_types_returns_immutable_tuple():
    """Audit fix: returns tuple (was list - caller could mutate registry)."""
    types = list_kpi_types()
    assert isinstance(types, tuple)
    # Tuples don't have append method
    assert not hasattr(types, 'append')


def test_list_kpi_types_sorted_for_stable_ui():
    """Sorted output → stable UI dropdown ordering across runs."""
    types1 = list_kpi_types()
    types2 = list_kpi_types()
    assert types1 == types2
    assert list(types1) == sorted(types1)


# ─── Sales config - REGRESSION GUARD (Trust 3 frozen values) ────────────────

def test_sales_config_likelihood_is_normal():
    config = get_kpi_config('sales')
    assert config.likelihood == 'normal'


def test_sales_config_ceiling_is_none():
    config = get_kpi_config('sales')
    assert config.ceiling is None


def test_sales_config_no_baseline_drift():
    config = get_kpi_config('sales')
    assert config.baseline_drift is False


def test_sales_config_priors_match_trust3_frozen():
    """Trust 3 hardcoded values (modeler.py:408-410) - must NOT drift."""
    config = get_kpi_config('sales')
    # Brand: μ_logit=0.7, σ=0.3 → ~12wk decay
    assert config.brand_mu_logit_prior == (0.7, 0.3)
    # Performance: μ_logit=-1.4, σ=0.7 → ~1.3wk decay
    assert config.perf_mu_logit_prior == (-1.4, 0.7)
    # Mixed: same as performance (semantic compat)
    assert config.mixed_mu_logit_prior == (-1.4, 0.7)


def test_sales_config_beta_sigmas_match_trust3():
    """Trust 3 group beta sigmas (modeler.py:367-369) - must NOT drift."""
    config = get_kpi_config('sales')
    assert config.brand_beta_sigma == 0.7
    assert config.perf_beta_sigma == 0.3
    assert config.mixed_beta_sigma == 0.4


def test_sales_config_hill_gammas_match_trust3():
    """Trust 3 Beta(3, 3) для gammas (modeler.py:389)."""
    config = get_kpi_config('sales')
    assert config.gammas_alpha == 3.0
    assert config.gammas_beta == 3.0


def test_sales_config_obs_sigma_matches_trust3():
    """modeler.py:469 - HalfNormal(0.3)."""
    config = get_kpi_config('sales')
    assert config.obs_sigma_prior == 0.3


# ─── Awareness config - design assertions ────────────────────────────────────

def test_awareness_config_likelihood_is_logit_normal():
    """M1 fix: awareness bounded → logit-Normal."""
    config = get_kpi_config('awareness')
    assert config.likelihood == 'logit_normal'


def test_awareness_config_ceiling_is_100():
    """M4 fix: awareness % hard ceiling at 100."""
    config = get_kpi_config('awareness')
    assert config.ceiling == 100.0


def test_awareness_config_has_baseline_drift():
    """M2 fix: awareness drifts (long memory) → GaussianRandomWalk component."""
    config = get_kpi_config('awareness')
    assert config.baseline_drift is True


def test_awareness_brand_decay_longer_than_sales():
    """Awareness brand build-up должен быть длиннее sales."""
    sales = get_kpi_config('sales')
    awareness = get_kpi_config('awareness')
    # Higher μ_logit → longer decay
    assert awareness.brand_mu_logit_prior[0] > sales.brand_mu_logit_prior[0]


def test_awareness_hill_saturation_earlier_than_sales():
    """M4: awareness saturation earlier (γ tighter, lower mean)."""
    sales = get_kpi_config('sales')
    awareness = get_kpi_config('awareness')
    # Beta(α, β) mean = α/(α+β). Awareness < Sales (earlier saturation).
    sales_mean = sales.gammas_alpha / (sales.gammas_alpha + sales.gammas_beta)
    awareness_mean = awareness.gammas_alpha / (awareness.gammas_alpha + awareness.gammas_beta)
    assert awareness_mean < sales_mean
