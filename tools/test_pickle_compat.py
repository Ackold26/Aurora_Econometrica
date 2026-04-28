"""Tests для engines/persistence.py — pickle backward-compat (Trust Level 3).

Coverage:
- load_model_with_compat() — fields default injected
- get_channel_categories() — explicit + heuristic fallback
- is_hierarchical_model() — v1.3+ detection
- Backward compat — v1.1, v1.2 pickles load без categories field
"""

from __future__ import annotations

import pickle
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'sidecar'))

from econometrica.engines.persistence import (
    get_adstock_type,
    get_baseline_posterior,
    get_channel_categories,
    get_feature_flags,
    get_kpi_type,
    get_weibull_params,
    has_baseline_posterior,
    is_awareness_model,
    is_hierarchical_model,
    load_model_with_compat,
)


def _write_pickle(data: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix='.pkl', delete=False)
    pickle.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


def test_load_v12_pickle_no_categories_field():
    """v1.2 pickle (pre-Trust3) — channel_categories field отсутствует, ожидается {}"""
    fixture = {
        'model_version': '1.2',
        'config': {'media_columns': ['TRPs', 'Search']},
        'media_columns': ['TRPs', 'Search'],
        'channel_params': {'TRPs': {}, 'Search': {}},
        'normalization': {},
    }
    path = _write_pickle(fixture)
    try:
        loaded = load_model_with_compat(path)
        assert loaded['channel_categories'] == {}, 'should default to empty dict'
        assert loaded['model_version'] == '1.2'
        assert loaded['media_columns'] == ['TRPs', 'Search']
    finally:
        path.unlink()


def test_load_v13_pickle_with_categories():
    fixture = {
        'model_version': '1.3',
        'config': {'media_columns': ['TRPs', 'OOH', 'Search']},
        'media_columns': ['TRPs', 'OOH', 'Search'],
        'channel_categories': {'TRPs': 'brand', 'OOH': 'brand', 'Search': 'performance'},
        'channel_params': {},
        'normalization': {},
    }
    path = _write_pickle(fixture)
    try:
        loaded = load_model_with_compat(path)
        assert loaded['channel_categories']['TRPs'] == 'brand'
        assert loaded['channel_categories']['Search'] == 'performance'
    finally:
        path.unlink()


def test_load_legacy_v10_pickle_no_version():
    """v1.0 era: без model_version field. Default к '1.0'."""
    fixture = {
        'media_columns': ['TRPs'],
        'channel_params': {},
    }
    path = _write_pickle(fixture)
    try:
        loaded = load_model_with_compat(path)
        assert loaded['model_version'] == '1.0'
        assert loaded['channel_categories'] == {}
    finally:
        path.unlink()


def test_get_channel_categories_explicit():
    model_data = {
        'channel_categories': {'TRPs': 'brand', 'Search': 'performance'},
        'media_columns': ['TRPs', 'Search'],
    }
    cats = get_channel_categories(model_data)
    assert cats == {'TRPs': 'brand', 'Search': 'performance'}


def test_get_channel_categories_heuristic_fallback():
    """Empty categories + fallback_heuristic=True → derived из имён"""
    model_data = {
        'channel_categories': {},
        'media_columns': ['TRPs бренд', 'Search Yandex'],
    }
    cats = get_channel_categories(model_data, fallback_heuristic=True)
    assert cats.get('TRPs бренд') == 'brand'
    assert cats.get('Search Yandex') == 'performance'


def test_get_channel_categories_no_fallback():
    model_data = {
        'channel_categories': {},
        'media_columns': ['TRPs бренд', 'Search Yandex'],
    }
    cats = get_channel_categories(model_data, fallback_heuristic=False)
    assert cats == {}


def test_is_hierarchical_model_v13_with_split():
    model_data = {
        'model_version': '1.3',
        'channel_categories': {
            'TRPs': 'brand', 'OOH': 'brand',
            'Search': 'performance', 'Social': 'performance',
        },
    }
    assert is_hierarchical_model(model_data) is True


def test_is_hierarchical_model_v12_rejected():
    """Pre-v1.3 → not hierarchical даже если categories somehow set"""
    model_data = {
        'model_version': '1.2',
        'channel_categories': {'TRPs': 'brand', 'OOH': 'brand'},
    }
    assert is_hierarchical_model(model_data) is False


def test_is_hierarchical_model_n1_group_rejected():
    """v1.3 но в каждой группе только 1 канал → degenerate"""
    model_data = {
        'model_version': '1.3',
        'channel_categories': {'TRPs': 'brand', 'Search': 'performance'},
    }
    assert is_hierarchical_model(model_data) is False


def test_is_hierarchical_model_all_mixed():
    model_data = {
        'model_version': '1.3',
        'channel_categories': {'a': 'mixed', 'b': 'mixed'},
    }
    assert is_hierarchical_model(model_data) is False


# ─── v2.0 Awareness/Weibull additive fields (Phase B0.2) ────────────────────

def test_load_v13_pickle_defaults_to_sales_kpi():
    """Pre-v2.0 pickle → kpi_type defaults к 'sales'."""
    p = _write_pickle({'model_version': '1.3', 'channel_categories': {}})
    try:
        loaded = load_model_with_compat(p)
        assert loaded['kpi_type'] == 'sales'
        assert loaded['kpi_likelihood'] == 'normal'
    finally:
        p.unlink()


def test_load_v13_pickle_defaults_adstock_types_empty():
    """Pre-v2.0 → channel_adstock_types empty dict (geometric implied)."""
    p = _write_pickle({'model_version': '1.3'})
    try:
        loaded = load_model_with_compat(p)
        assert loaded['channel_adstock_types'] == {}
        assert loaded['weibull_params_per_channel'] == {}
    finally:
        p.unlink()


def test_load_v20_awareness_pickle_roundtrip():
    """v2.0 awareness pickle round-trip (write + load + helpers)."""
    p = _write_pickle({
        'model_version': '2.0',
        'channel_categories': {'TV': 'brand', 'Search': 'performance'},
        'kpi_type': 'awareness',
        'kpi_likelihood': 'logit_normal',
        'awareness_aggregation_mode': 'monthly_interpolated',
    })
    try:
        loaded = load_model_with_compat(p)
        assert get_kpi_type(loaded) == 'awareness'
        assert is_awareness_model(loaded) is True
        assert loaded['awareness_aggregation_mode'] == 'monthly_interpolated'
    finally:
        p.unlink()


def test_get_kpi_type_default_sales():
    """Empty pickle → defaults к 'sales'."""
    assert get_kpi_type({}) == 'sales'
    assert is_awareness_model({}) is False


def test_get_adstock_type_default_geometric():
    """Channel не в dict → defaults к 'geometric'."""
    assert get_adstock_type({'channel_adstock_types': {}}, 'TV') == 'geometric'
    assert get_adstock_type({}, 'unknown') == 'geometric'


def test_get_adstock_type_explicit_weibull():
    model_data = {'channel_adstock_types': {'TV': 'weibull', 'Search': 'geometric'}}
    assert get_adstock_type(model_data, 'TV') == 'weibull'
    assert get_adstock_type(model_data, 'Search') == 'geometric'


def test_get_weibull_params_returns_none_for_geometric():
    model_data = {
        'channel_adstock_types': {'Search': 'geometric'},
        'weibull_params_per_channel': {},
    }
    assert get_weibull_params(model_data, 'Search') is None


def test_get_weibull_params_returns_dict_for_weibull():
    model_data = {
        'channel_adstock_types': {'TV': 'weibull'},
        'weibull_params_per_channel': {
            'TV': {'peak_week_median': 3.0, 'tail_decay_median': 0.4, 'lam_median': 4.5, 'k_median': 2.5}
        },
    }
    params = get_weibull_params(model_data, 'TV')
    assert params is not None
    assert params['peak_week_median'] == 3.0
    assert params['k_median'] == 2.5


def test_has_baseline_posterior_false_when_none():
    assert has_baseline_posterior({}) is False
    assert has_baseline_posterior({'comparison_baseline_posterior': None}) is False


def test_has_baseline_posterior_true_when_present():
    model_data = {'comparison_baseline_posterior': {'TV': {'roi_median': 1.5}}}
    assert has_baseline_posterior(model_data) is True
    baseline = get_baseline_posterior(model_data)
    assert baseline is not None
    assert baseline['TV']['roi_median'] == 1.5


def test_get_feature_flags_default_empty():
    assert get_feature_flags({}) == []


def test_get_feature_flags_returns_list_copy():
    model_data = {'feature_flags_used': ['awareness_mode', 'weibull_learnable']}
    flags = get_feature_flags(model_data)
    assert 'awareness_mode' in flags
    assert 'weibull_learnable' in flags
    # Verify это копия (mutation safety)
    flags.append('XXX')
    assert 'XXX' not in model_data['feature_flags_used']


# ─── Audit fixes (2026-04-28) ────────────────────────────────────────────────

def test_get_weibull_params_warns_on_malformed_pickle():
    """Audit fix: declared Weibull но params missing → RuntimeWarning."""
    import warnings
    model_data = {
        'channel_adstock_types': {'TV': 'weibull'},
        'weibull_params_per_channel': {},  # TV missing!
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        result = get_weibull_params(model_data, 'TV')
        assert result is None
        # Should emit RuntimeWarning
        assert any(issubclass(warning.category, RuntimeWarning) for warning in w)
        assert any('Weibull' in str(warning.message) for warning in w)


def test_is_hierarchical_model_handles_v1_10_correctly():
    """Audit fix: semantic version compare. '1.10' >= '1.3' (NOT lex order)."""
    # Future v1.10 pickle (hypothetical) с hierarchical setup
    model_data = {
        'model_version': '1.10',
        'channel_categories': {'TV': 'brand', 'OOH': 'brand', 'Search': 'performance', 'Social': 'performance'},
    }
    # Pre-fix: '1.10' < '1.3' lex → False (hierarchical NOT detected) — BUG
    # Post-fix: (1, 10, 0) >= (1, 3, 0) → True (hierarchical detected correctly)
    assert is_hierarchical_model(model_data) is True


def test_is_hierarchical_model_handles_v2_correctly():
    """v2.0 pickle с hierarchical categories → detected."""
    model_data = {
        'model_version': '2.0',
        'channel_categories': {'TV': 'brand', 'OOH': 'brand', 'Search': 'performance', 'Social': 'performance'},
    }
    assert is_hierarchical_model(model_data) is True


def test_is_hierarchical_model_handles_unparseable_version():
    """Defensive: unknown version string → defaults к (0,0,0) → not hierarchical."""
    model_data = {
        'model_version': 'unknown-format',
        'channel_categories': {'TV': 'brand', 'OOH': 'brand', 'Search': 'performance', 'Social': 'performance'},
    }
    assert is_hierarchical_model(model_data) is False  # version too low


def main():
    tests = [
        test_load_v12_pickle_no_categories_field,
        test_load_v13_pickle_with_categories,
        test_load_legacy_v10_pickle_no_version,
        test_get_channel_categories_explicit,
        test_get_channel_categories_heuristic_fallback,
        test_get_channel_categories_no_fallback,
        test_is_hierarchical_model_v13_with_split,
        test_is_hierarchical_model_v12_rejected,
        test_is_hierarchical_model_n1_group_rejected,
        test_is_hierarchical_model_all_mixed,
        # v2.0 additive
        test_load_v13_pickle_defaults_to_sales_kpi,
        test_load_v13_pickle_defaults_adstock_types_empty,
        test_load_v20_awareness_pickle_roundtrip,
        test_get_kpi_type_default_sales,
        test_get_adstock_type_default_geometric,
        test_get_adstock_type_explicit_weibull,
        test_get_weibull_params_returns_none_for_geometric,
        test_get_weibull_params_returns_dict_for_weibull,
        test_has_baseline_posterior_false_when_none,
        test_has_baseline_posterior_true_when_present,
        test_get_feature_flags_default_empty,
        test_get_feature_flags_returns_list_copy,
        # Audit fixes
        test_get_weibull_params_warns_on_malformed_pickle,
        test_is_hierarchical_model_handles_v1_10_correctly,
        test_is_hierarchical_model_handles_v2_correctly,
        test_is_hierarchical_model_handles_unparseable_version,
    ]
    passed = 0
    failed = []
    for t in tests:
        try:
            t()
            passed += 1
            print(f'  PASS {t.__name__}')
        except AssertionError as e:
            failed.append((t.__name__, str(e)))
            print(f'  FAIL {t.__name__}: {e}')
        except Exception as e:
            failed.append((t.__name__, f'{type(e).__name__}: {e}'))
            print(f'  ERROR {t.__name__}: {type(e).__name__}: {e}')
    print(f'\n{passed}/{len(tests)} passed')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
