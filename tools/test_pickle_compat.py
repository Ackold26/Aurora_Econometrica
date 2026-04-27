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
    get_channel_categories,
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
