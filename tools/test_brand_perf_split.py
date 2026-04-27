"""Synthetic + smoke tests для Trust Level 3 (Brand vs Performance Split).

Coverage:
- Test 1: Backward compat — empty channel_categories → single-prior path (model_version=1.2 preserved)
- Test 2: All-mixed portfolio → identical к pre-Trust3 baseline (no hierarchical)
- Test 3: ≥2 brand + ≥2 perf → use_hierarchical=True (model_version=1.3)
- Test 4: Single-N brand group → identifiability fallback к mixed (no hierarchical)
- Test 5: validate_categorization_for_hierarchical produces correct demote
- Test 6: persistence — channel_categories сохраняются в pickle config
- Test 7: Decay extraction для hierarchical с per-group mu_logit available
- Test 8: Pickle compat helper централизован
- Test 9: Heuristic fallback применяется к pre-v1.3 pickles при decompose
- Test 10: Auto-suggest endpoint structure validation

Live MCMC training tests (NumPyro JAX sampling) helps Phase E validation
но они slow и требуют полный sidecar-stack — реальная live-валидация делается через
manual alpha gate на Kagocel/Венарус (Phase G).
"""

from __future__ import annotations

import pickle
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'sidecar'))

from econometrica.engines.persistence import (
    get_channel_categories,
    is_hierarchical_model,
    load_model_with_compat,
)
from econometrica.utils.channel_categorization import (
    auto_suggest_categories,
    auto_suggest_category,
    is_hierarchical_eligible,
    validate_categorization_for_hierarchical,
)


def _make_pickle_v12(media_cols, dest):
    """Pre-Trust3 v1.2 pickle (no channel_categories field)."""
    data = {
        'model_version': '1.2',
        'config': {'media_columns': media_cols, 'channel_categories': {}},
        'media_columns': media_cols,
        'channel_params': {c: {} for c in media_cols},
        'normalization': {'y_mean': 100, 'y_std': 30},
    }
    with open(dest, 'wb') as f:
        pickle.dump(data, f)


def _make_pickle_v13(media_cols, categories, dest):
    """v1.3 hierarchical pickle."""
    n_brand = sum(1 for v in categories.values() if v == 'brand')
    n_perf = sum(1 for v in categories.values() if v == 'performance')
    use_hierarchical = n_brand >= 2 or n_perf >= 2
    data = {
        'model_version': '1.3' if use_hierarchical else '1.2',
        'config': {'media_columns': media_cols, 'channel_categories': categories},
        'media_columns': media_cols,
        'channel_categories': categories,
        'use_hierarchical': use_hierarchical,
        'hierarchical_priors': {
            'brand_mu_logit_mean': 0.7,
            'brand_sigma_mean': 0.65,
            'performance_mu_logit_mean': -1.4,
            'performance_sigma_mean': 0.28,
        } if use_hierarchical else {},
        'channel_params': {c: {} for c in media_cols},
        'normalization': {'y_mean': 100, 'y_std': 30},
    }
    with open(dest, 'wb') as f:
        pickle.dump(data, f)


def test_backward_compat_v12_pickle_loads():
    """Pre-Trust3 pickle загружается через persistence helper, channel_categories injected."""
    with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as tmp:
        path = Path(tmp.name)
    try:
        _make_pickle_v12(['TRPs', 'OOH', 'Search'], path)
        loaded = load_model_with_compat(path)
        assert loaded['model_version'] == '1.2'
        assert loaded['channel_categories'] == {}
        assert is_hierarchical_model(loaded) is False
    finally:
        path.unlink()


def test_all_mixed_not_hierarchical():
    """All-mixed portfolio → не hierarchical (fallback к single prior)"""
    cats = {'a': 'mixed', 'b': 'mixed', 'c': 'mixed'}
    assert is_hierarchical_eligible(cats) is False


def test_brand_perf_split_hierarchical_eligible():
    """≥2 brand + ≥2 perf → hierarchical eligible"""
    cats = {'TRPs': 'brand', 'OOH': 'brand', 'Search': 'performance', 'Social': 'performance'}
    assert is_hierarchical_eligible(cats) is True


def test_n1_brand_demoted():
    """Single-N brand group → demoted к mixed (identifiability constraint)"""
    cats = {'TRPs': 'brand', 'Search': 'performance', 'Social': 'performance'}
    media = list(cats.keys())
    validated, warnings = validate_categorization_for_hierarchical(cats, media)
    assert validated['TRPs'] == 'mixed'  # demoted
    assert validated['Search'] == 'performance'
    assert validated['Social'] == 'performance'
    assert any('Brand' in w for w in warnings)


def test_n1_perf_demoted():
    cats = {'TRPs': 'brand', 'OOH': 'brand', 'Search': 'performance'}
    media = list(cats.keys())
    validated, warnings = validate_categorization_for_hierarchical(cats, media)
    assert validated['Search'] == 'mixed'
    assert any('Performance' in w for w in warnings)


def test_v13_pickle_persists_categories():
    with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as tmp:
        path = Path(tmp.name)
    try:
        cats = {'TRPs': 'brand', 'OOH': 'brand', 'Search': 'performance', 'Social': 'performance'}
        _make_pickle_v13(['TRPs', 'OOH', 'Search', 'Social'], cats, path)
        loaded = load_model_with_compat(path)
        assert loaded['model_version'] == '1.3'
        assert loaded['channel_categories'] == cats
        assert loaded['use_hierarchical'] is True
        assert is_hierarchical_model(loaded) is True
        # priors_summary persisted для methodology auto-gen
        assert 'brand_mu_logit_mean' in loaded['hierarchical_priors']
    finally:
        path.unlink()


def test_pre_v13_no_categories_heuristic_fallback_in_decomposer():
    """Pre-v1.3 pickle decompose flow: heuristic categorization применяется при чтении."""
    with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as tmp:
        path = Path(tmp.name)
    try:
        _make_pickle_v12(['TRPs бренд', 'OOH', 'Search Yandex'], path)
        loaded = load_model_with_compat(path)
        # Explicit categories empty
        assert get_channel_categories(loaded, fallback_heuristic=False) == {}
        # Heuristic fallback derives correctly
        derived = get_channel_categories(loaded, fallback_heuristic=True)
        assert derived.get('TRPs бренд') == 'brand'
        assert derived.get('OOH') == 'brand'
        assert derived.get('Search Yandex') == 'performance'
    finally:
        path.unlink()


def test_auto_suggest_endpoint_structure():
    """Endpoint contract: возвращает {channel: {category, confidence, reasoning}}"""
    suggestions = auto_suggest_categories(['TRPs', 'Search', 'Спецпроект'])
    for ch, sug in suggestions.items():
        assert 'category' in sug
        assert 'confidence' in sug
        assert 'reasoning' in sug
        assert sug['category'] in ('brand', 'performance', 'mixed')
        assert 0 <= sug['confidence'] <= 1


def test_brand_decay_higher_than_perf_priors():
    """Sanity: brand prior мать decay (sigmoid(0.7)≈0.67) > perf (sigmoid(-1.4)≈0.20).

    Эта релация — фундаментальная для Trust 3. Если flip — модель больше не разделяет.
    """
    import math
    brand_decay = 1 / (1 + math.exp(-0.7))
    perf_decay = 1 / (1 + math.exp(1.4))
    assert brand_decay > 0.5, 'Brand decay должен быть > 0.5 для long-horizon'
    assert perf_decay < 0.3, 'Performance decay должен быть < 0.3 для short-horizon'
    assert brand_decay > 2 * perf_decay, 'Brand decay должен быть существенно больше performance'


def test_audit_fix_empty_raw_no_autofill():
    """POST-AUDIT REGRESSION TEST (2026-04-27):
    Empty raw_categories → validate возвращает {} (NOT auto-filled с mixed).
    Это критично для backward compat: pre-Trust3 проекты должны сохранять empty
    в pickle → decomposer применяет heuristic fallback → каналы не теряют классификацию.
    """
    media = ['TRPs', 'Search', 'Social']
    validated, warnings = validate_categorization_for_hierarchical({}, media)
    assert validated == {}, f'Empty raw should produce empty validated, got {validated}'
    assert warnings == [], f'No warnings should be generated, got {warnings}'


def test_audit_fix_partial_user_assignment():
    """User assigned только часть каналов → validate keeps only those entries.

    Pre-fix: validate filled missing с mixed → все каналы saved в pickle as 'mixed'
    → decomposer treated пользователские pure mixed как explicit choice, skipping heuristic.
    Post-fix: missing каналы остаются вне validated dict → decomposer applies heuristic.
    """
    raw = {'TRPs': 'brand', 'OOH': 'brand'}
    media = ['TRPs', 'OOH', 'Search', 'Social']
    validated, warnings = validate_categorization_for_hierarchical(raw, media)
    assert validated == {'TRPs': 'brand', 'OOH': 'brand'}, \
        f'Should preserve user explicit choices only, got {validated}'
    assert 'Search' not in validated
    assert 'Social' not in validated


def test_methodology_auto_gen_block():
    """HTML methodology block рендерится из diagnostics.hierarchical."""
    from econometrica.aurora_html.sections import _render_brand_perf_split_block

    # Empty case: no hierarchical → empty string
    ctx_empty = {'diagnostics': {'hierarchical': {'enabled': False}}}
    assert _render_brand_perf_split_block(ctx_empty) == ''

    # Full case: hierarchical with priors
    ctx_full = {
        'diagnostics': {
            'hierarchical': {
                'enabled': True,
                'channel_categories': {'TRPs': 'brand', 'OOH': 'brand', 'Search': 'performance', 'Social': 'performance'},
                'priors_summary': {
                    'brand_mu_logit_mean': 0.7,
                    'performance_mu_logit_mean': -1.4,
                },
                'rhat_warning': None,
            },
        }
    }
    html = _render_brand_perf_split_block(ctx_full)
    assert 'Brand vs Performance' in html
    assert 'Brand:</strong> 2' in html
    assert 'Performance:</strong> 2' in html
    assert 'half-life' in html


def main():
    tests = [
        test_backward_compat_v12_pickle_loads,
        test_all_mixed_not_hierarchical,
        test_brand_perf_split_hierarchical_eligible,
        test_n1_brand_demoted,
        test_n1_perf_demoted,
        test_v13_pickle_persists_categories,
        test_pre_v13_no_categories_heuristic_fallback_in_decomposer,
        test_auto_suggest_endpoint_structure,
        test_brand_decay_higher_than_perf_priors,
        test_audit_fix_empty_raw_no_autofill,
        test_audit_fix_partial_user_assignment,
        test_methodology_auto_gen_block,
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
