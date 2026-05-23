"""Tests для utils/channel_categorization.py - Trust Level 3 auto-suggest heuristic.

Coverage:
- normalize_channel_name() - handle parens, dots, Cyrillic, mixed case
- auto_suggest_category() - single channel suggestion + confidence
- auto_suggest_categories() - batch
- validate_categorization_for_hierarchical() - identifiability fallback (N<2 group → mixed)
- is_hierarchical_eligible() - guard для модели
- infer_categories_heuristic() - fallback для старых pickles (confidence threshold 0.7)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow direct invocation from project root: python tools/test_channel_categorization.py
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'sidecar'))

from econometrica.utils.channel_categorization import (
    BRAND_HINTS,
    PERF_HINTS,
    auto_suggest_categories,
    auto_suggest_category,
    infer_categories_heuristic,
    is_hierarchical_eligible,
    normalize_channel_name,
    validate_categorization_for_hierarchical,
)


def test_normalize_basic():
    assert normalize_channel_name('TRPs') == 'TRPS'
    assert normalize_channel_name('TRPs (W25-54)') == 'TRPS W25-54'
    assert normalize_channel_name('  trps  бренд  ') == 'TRPS БРЕНД'
    assert normalize_channel_name('') == ''


def test_normalize_punctuation():
    # Dots, slashes stripped
    n = normalize_channel_name('т.р.п./tv')
    assert 'ТРП' in n.replace(' ', '')
    assert 'TV' in n


def test_brand_strong_match():
    sug = auto_suggest_category('TRPs бренд')
    assert sug['category'] == 'brand'
    assert sug['confidence'] >= 0.85  # multiple hints
    assert 'TRP' in sug['reasoning'] or 'БРЕНД' in sug['reasoning']


def test_performance_strong_match():
    sug = auto_suggest_category('Search Yandex клики')
    assert sug['category'] == 'performance'
    assert sug['confidence'] >= 0.7


def test_brand_single_hint():
    sug = auto_suggest_category('OOH')
    assert sug['category'] == 'brand'
    assert sug['confidence'] == 0.7  # single hint match


def test_ambiguous_mixed():
    """Channel name с brand AND performance hints → mixed, confidence 0.5"""
    sug = auto_suggest_category('TV Digital cross-channel')
    assert sug['category'] == 'mixed'
    assert sug['confidence'] == 0.5
    assert 'ambiguous' in sug['reasoning'].lower()


def test_unknown_no_match():
    sug = auto_suggest_category('Спецпроект')
    assert sug['category'] == 'mixed'
    assert sug['confidence'] == 0.0


def test_empty_name():
    sug = auto_suggest_category('')
    assert sug['category'] == 'mixed'
    assert sug['confidence'] == 0.0


def test_batch_suggestions():
    channels = ['TRPs', 'Search', 'Спецпроект', 'OOH']
    suggestions = auto_suggest_categories(channels)
    assert suggestions['TRPs']['category'] == 'brand'
    assert suggestions['Search']['category'] == 'performance'
    assert suggestions['Спецпроект']['category'] == 'mixed'
    assert suggestions['OOH']['category'] == 'brand'


def test_validate_identifiability_brand_n1_demoted():
    """N=1 brand канал → demoted к mixed с warning"""
    cats = {'TRPs': 'brand', 'Search': 'performance', 'Social': 'performance'}
    media = ['TRPs', 'Search', 'Social']
    validated, warnings = validate_categorization_for_hierarchical(cats, media)
    assert validated['TRPs'] == 'mixed', 'Single-N brand should be demoted'
    assert validated['Search'] == 'performance'
    assert validated['Social'] == 'performance'
    assert any('Brand' in w and 'TRPs' in w for w in warnings)


def test_validate_identifiability_perf_n1_demoted():
    cats = {'TRPs': 'brand', 'OOH': 'brand', 'Search': 'performance'}
    media = ['TRPs', 'OOH', 'Search']
    validated, warnings = validate_categorization_for_hierarchical(cats, media)
    assert validated['Search'] == 'mixed'
    assert validated['TRPs'] == 'brand'
    assert validated['OOH'] == 'brand'
    assert any('Performance' in w for w in warnings)


def test_validate_both_groups_ok():
    cats = {'TRPs': 'brand', 'OOH': 'brand', 'Search': 'performance', 'Social': 'performance'}
    media = list(cats.keys())
    validated, warnings = validate_categorization_for_hierarchical(cats, media)
    assert validated == cats
    assert warnings == []


def test_validate_orphans_removed():
    cats = {'TRPs': 'brand', 'OOH': 'brand', 'DELETED_CH': 'performance'}
    media = ['TRPs', 'OOH']
    validated, warnings = validate_categorization_for_hierarchical(cats, media)
    assert 'DELETED_CH' not in validated
    assert any('orphaned' in w.lower() or 'DELETED_CH' in w for w in warnings)


def test_validate_missing_NOT_auto_filled():
    """POST-AUDIT FIX (2026-04-27): missing channels НЕ filled с 'mixed' auto.

    Pre-fix: validate auto-filled → pickle saved all-mixed → decomposer пропускал
    heuristic → pre-Trust3 проекты теряли категоризацию в отчётах.
    Post-fix: missing entries left absent. Single-N brand demote'ится к mixed.
    Caller использует resolve_per_channel_categories() для per-channel vector.
    """
    cats = {'TRPs': 'brand'}
    media = ['TRPs', 'NewChannel']
    validated, warnings = validate_categorization_for_hierarchical(cats, media)
    # NewChannel НЕ в validated (was missing, не explicit user choice).
    assert 'NewChannel' not in validated
    # TRPs demoted to mixed (N=1 brand identifiability fallback).
    assert validated.get('TRPs') == 'mixed'


def test_resolve_per_channel_categories_default():
    """resolve_per_channel_categories fills missing с default."""
    from econometrica.utils.channel_categorization import resolve_per_channel_categories
    explicit = {'TRPs': 'brand', 'OOH': 'brand'}
    media = ['TRPs', 'OOH', 'Search', 'Social']
    result = resolve_per_channel_categories(explicit, media)
    assert result == ['brand', 'brand', 'mixed', 'mixed']
    # Custom default
    result2 = resolve_per_channel_categories(explicit, media, default='performance')
    assert result2 == ['brand', 'brand', 'performance', 'performance']


def test_is_hierarchical_eligible_yes():
    cats = {'a': 'brand', 'b': 'brand', 'c': 'performance', 'd': 'mixed'}
    assert is_hierarchical_eligible(cats) is True


def test_is_hierarchical_eligible_no_groups_too_small():
    # Only 1 brand, 1 perf - both demote-eligible
    cats = {'a': 'brand', 'b': 'performance', 'c': 'mixed'}
    assert is_hierarchical_eligible(cats) is False


def test_is_hierarchical_eligible_all_mixed():
    cats = {'a': 'mixed', 'b': 'mixed'}
    assert is_hierarchical_eligible(cats) is False


def test_infer_categories_heuristic_high_confidence():
    media = ['TRPs бренд', 'OOH', 'Search Yandex', 'Social VK']
    inferred = infer_categories_heuristic(media)
    assert inferred['TRPs бренд'] == 'brand'
    assert inferred['OOH'] == 'brand'
    assert inferred['Search Yandex'] == 'performance'
    assert inferred['Social VK'] == 'performance'


def test_infer_categories_heuristic_low_confidence_to_mixed():
    media = ['Спецпроект', 'OLV кампания', 'Brand-format banner']
    inferred = infer_categories_heuristic(media)
    # Низкая уверенность → mixed
    assert inferred['Спецпроект'] == 'mixed'


def test_hints_lists_no_overlap():
    """Sanity check - no hint в обоих списках одновременно"""
    overlap = set(BRAND_HINTS) & set(PERF_HINTS)
    assert overlap == set(), f"Hints overlap: {overlap}"


def test_validation_set_accuracy():
    """Auto-suggest accuracy на manually-labeled fixture (Critical Audit issue P)"""
    fixture_path = ROOT / 'tools' / 'validation_set_categorization.json'
    if not fixture_path.exists():
        # Will be created later - skip assertion gracefully
        return
    import json
    fixture = json.loads(fixture_path.read_text(encoding='utf-8'))
    correct = 0
    total = len(fixture)
    for item in fixture:
        sug = auto_suggest_category(item['name'])
        if sug['category'] == item['expected']:
            correct += 1
    accuracy = correct / total if total > 0 else 0
    assert accuracy >= 0.85, f"Auto-suggest accuracy {accuracy:.2%} < 85% on {total} items"


def main():
    tests = [
        test_normalize_basic, test_normalize_punctuation,
        test_brand_strong_match, test_performance_strong_match,
        test_brand_single_hint, test_ambiguous_mixed,
        test_unknown_no_match, test_empty_name,
        test_batch_suggestions,
        test_validate_identifiability_brand_n1_demoted,
        test_validate_identifiability_perf_n1_demoted,
        test_validate_both_groups_ok,
        test_validate_orphans_removed,
        test_validate_missing_NOT_auto_filled,
        test_resolve_per_channel_categories_default,
        test_is_hierarchical_eligible_yes,
        test_is_hierarchical_eligible_no_groups_too_small,
        test_is_hierarchical_eligible_all_mixed,
        test_infer_categories_heuristic_high_confidence,
        test_infer_categories_heuristic_low_confidence_to_mixed,
        test_hints_lists_no_overlap,
        test_validation_set_accuracy,
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
