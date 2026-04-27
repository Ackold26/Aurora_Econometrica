"""Integration test using kagocel_pathology_project fixture.

Synthetic fixture matches real Kagocel data structure (Sprint 5 Track C):
- TV-dominant (TRPs native units, mROAS asymmetry)
- 6 channels (1 brand-TRP + 5 money channels)
- Hierarchical priors active (brand vs performance split, Trust 3)
- L4-style pathology encoded — lock-in regression detection

These tests НЕ требуют Kagocel.xlsx (real customer data).
Pattern matches existing tools/test_optimizer_kagocel_redistribution.py docstring philosophy.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_pickle_loads_via_compat_helper(kagocel_pathology_project):
    """Pre-trained pickle is loadable через persistence helper."""
    from econometrica.engines.persistence import load_model_with_compat
    pickle_path = kagocel_pathology_project / 'models' / 'latest.pkl'
    assert pickle_path.exists()
    data = load_model_with_compat(pickle_path)
    assert data['model_version'] == '1.3'
    assert data['use_hierarchical'] is True


def test_brand_channels_have_higher_decay_than_performance(kagocel_pathology_project):
    """Trust 3 invariant: brand channels должны have higher posterior decay.

    Brand: TRPs бренд + OOH (decay ~0.6+)
    Performance: Performance + Social + Search (decay ~0.2 or less)
    """
    from econometrica.engines.persistence import load_model_with_compat
    pickle_path = kagocel_pathology_project / 'models' / 'latest.pkl'
    data = load_model_with_compat(pickle_path)

    cats = data['channel_categories']
    params = data['channel_params']
    brand_decays = [params[ch]['decay'] for ch, cat in cats.items() if cat == 'brand']
    perf_decays = [params[ch]['decay'] for ch, cat in cats.items() if cat == 'performance']

    assert len(brand_decays) >= 2
    assert len(perf_decays) >= 2
    avg_brand = sum(brand_decays) / len(brand_decays)
    avg_perf = sum(perf_decays) / len(perf_decays)
    assert avg_brand > avg_perf, f'Brand decay {avg_brand:.3f} should > perf decay {avg_perf:.3f}'
    assert avg_brand > 0.4, 'Brand decay should be ≥0.4 (long-decay)'
    assert avg_perf < 0.3, 'Performance decay should be <0.3 (short-decay)'


def test_categorization_warnings_field_present(kagocel_pathology_project):
    """Decompose response surfaces hierarchical metadata (Sprint 4 audit fix)."""
    from econometrica.engines.persistence import load_model_with_compat
    pickle_path = kagocel_pathology_project / 'models' / 'latest.pkl'
    data = load_model_with_compat(pickle_path)
    assert 'categorization_warnings' in data
    assert isinstance(data['categorization_warnings'], list)


def test_hierarchical_priors_summary_persisted(kagocel_pathology_project):
    """Pickle persists priors mean values для methodology auto-gen."""
    from econometrica.engines.persistence import load_model_with_compat
    pickle_path = kagocel_pathology_project / 'models' / 'latest.pkl'
    data = load_model_with_compat(pickle_path)
    priors = data['hierarchical_priors']
    assert 'brand_mu_logit_mean' in priors
    assert 'performance_mu_logit_mean' in priors
    # Brand mu_logit should be > 0 (sigmoid > 0.5 → long decay)
    assert priors['brand_mu_logit_mean'] > 0
    # Performance mu_logit should be < 0 (sigmoid < 0.5 → short decay)
    assert priors['performance_mu_logit_mean'] < 0


def test_synthetic_smoke_pickle_works(synthetic_trained_project):
    """Generic synthetic fixture smoke test (no Trust 3 hierarchical)."""
    from econometrica.engines.persistence import load_model_with_compat
    pickle_path = synthetic_trained_project / 'models' / 'latest.pkl'
    data = load_model_with_compat(pickle_path)
    assert data['model_version'] in ('1.2', '1.3')
    assert len(data['media_columns']) == 5
    assert data['use_hierarchical'] is False
