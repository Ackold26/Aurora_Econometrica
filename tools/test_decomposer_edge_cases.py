"""Decomposer engine edge case matrix - Phase B2 of engine audit extension.

Plan: C:\\Users\\ackol\\Desktop\\optimizer-audit-followup-plan.md, этап 4.

Six batches:

    A - Pickle compatibility (v1.0 reject / v1.1 / v1.1.5 / v1.2 / v1.3 hierarchical)
    B - Untrained channel mix (none / some / all)
    C - Unit costs (None / override / inflation_pct)
    D - Hybrid verdict transitions (deep loss / loss / breakeven / high)
    E - Hierarchical metadata exposure
    F - Smell flags (unit_smell / roi_max / roi_spread)

Total ~32 tests.

Run:
    pytest tools/test_decomposer_edge_cases.py -v
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _optimizer_fixtures import (  # noqa: E402
    build_multi_year_pickle,
    build_synthetic_pickle,
    is_ok,
    promote_to_hierarchical,
)


# ══════════════════════════════════════════════════════════════════════
# Batch A - Pickle compatibility
# ══════════════════════════════════════════════════════════════════════


def test_A1_legacy_v1_0_rejected(tmp_path):
    """model_version='1.0' (pre-spend/mean) → MODEL_OUTDATED."""
    proj = tmp_path / 'A1'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3)
    md['model_version'] = '1.0'
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'MODEL_OUTDATED'


def test_A2_v1_2_default_no_warning(tmp_path):
    """v1.2 pickle (current production) → no model_warning."""
    proj = tmp_path / 'A2'
    build_synthetic_pickle(proj, seed=1, n_channels=3)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    assert r.get('model_warning') is None


def test_A3_v1_1_warning(tmp_path):
    """v1.1 pickle → warning о missing posterior samples."""
    proj = tmp_path / 'A3'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, n_posterior_samples=0)
    md['model_version'] = '1.1'
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    assert r.get('model_warning') is not None
    assert 'CI' in r['model_warning'] or 'переобучите' in r['model_warning'].lower()


def test_A4_v1_1_5_warning(tmp_path):
    """v1.1.5 pickle (fixed adstock) → warning о missing decay learning."""
    proj = tmp_path / 'A4'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3)
    md['model_version'] = '1.1.5'
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    assert r.get('model_warning') is not None
    assert 'adstock' in r['model_warning'].lower()


def test_A5_hierarchical_v1_3(tmp_path):
    """v1.3 hierarchical → result includes hierarchical metadata."""
    proj = tmp_path / 'A5'
    build_synthetic_pickle(proj, seed=1, n_channels=4)
    promote_to_hierarchical(proj)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    assert r['hierarchical']['enabled'] is True
    assert r['hierarchical']['channel_categories']


def test_A6_no_pickle_returns_error(tmp_path):
    """No pickle → MODEL_NOT_FOUND error."""
    empty = tmp_path / 'A6'
    empty.mkdir()
    (empty / 'models').mkdir()

    from engines.decomposer import decompose
    r = decompose(str(empty))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'MODEL_NOT_FOUND'


# ══════════════════════════════════════════════════════════════════════
# Batch B - Untrained channel mix
# ══════════════════════════════════════════════════════════════════════


def test_B1_no_untrained_channels(tmp_path):
    """All channels trained → no 'Не обучен' verdicts."""
    proj = tmp_path / 'B1'
    build_synthetic_pickle(proj, seed=1, n_channels=4)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    untrained = [ch for ch in r['channels'] if ch.get('untrained')]
    assert len(untrained) == 0


def test_B2_partial_untrained_decoration(tmp_path):
    """Some untrained → verdict='Не обучен', contribution=0, action='Uncertain'."""
    proj = tmp_path / 'B2'
    build_synthetic_pickle(
        proj, seed=42, n_channels=4,
        untrained_channels=['ch_2'],
    )

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    untrained = [ch for ch in r['channels'] if ch['name'] == 'ch_2']
    assert len(untrained) == 1
    ch = untrained[0]
    assert float(ch['contribution']) == 0.0
    assert ch['verdict'] == 'Не обучен'
    assert ch['action'] == 'Uncertain'
    assert ch['action_label'] == 'Не обучен'


def test_B3_two_untrained_independent(tmp_path):
    """Two untrained channels → both get correct skip + decoration."""
    proj = tmp_path / 'B3'
    build_synthetic_pickle(
        proj, seed=42, n_channels=5,
        untrained_channels=['ch_2', 'ch_3'],
    )

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    untrained_names = {ch['name'] for ch in r['channels'] if ch.get('untrained')}
    assert untrained_names == {'ch_2', 'ch_3'}


# ══════════════════════════════════════════════════════════════════════
# Batch C - Unit costs handling
# ══════════════════════════════════════════════════════════════════════


def test_C1_default_unit_costs_from_pickle(tmp_path):
    """No override → reads unit_costs from pickle config."""
    proj = tmp_path / 'C1'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, mixed_units=True)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    assert trps is not None
    assert abs(trps['unit_cost'] - 150_000.0) < 1.0


def test_C2_unit_costs_override(tmp_path):
    """Override unit_costs param → overrides pickle config (e.g. CPP changed)."""
    proj = tmp_path / 'C2'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, mixed_units=True)
    override = {**md['config']['unit_costs'], 'tv_trps_brand': 200_000.0}

    from engines.decomposer import decompose
    r = decompose(str(proj), unit_costs_override=override)
    assert is_ok(r)
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    assert abs(trps['unit_cost'] - 200_000.0) < 1.0


def test_C3_inflation_pct_applied(tmp_path):
    """unit_cost_inflation_pct adjusts effective unit_cost via training-period weighted avg."""
    proj = tmp_path / 'C3'
    md = build_multi_year_pickle(proj, seed=1, n_channels=4)

    from engines.decomposer import decompose
    r = decompose(
        str(proj),
        unit_cost_inflation_pct={'tv_trps_brand': 25.0},
    )
    assert is_ok(r)
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    # Multi-year fixture (2024-2025) + 25% inflation → weighted avg < 150_000
    assert trps['unit_cost'] < 150_000.0


def test_C4_inflation_unknown_channel_ignored(tmp_path):
    """inflation_pct contains channel not in media_cols → silent skip."""
    proj = tmp_path / 'C4'
    md = build_multi_year_pickle(proj, seed=1, n_channels=4)

    from engines.decomposer import decompose
    try:
        r = decompose(
            str(proj),
            unit_cost_inflation_pct={'tv_trps_brand': 25.0, 'unknown_xyz': 50.0},
        )
    except (KeyError, ValueError) as e:
        pytest.fail(f'C4: unknown inflation channel crashed: {e}')
    assert is_ok(r)


# ══════════════════════════════════════════════════════════════════════
# Batch D - Hybrid verdict transitions
# ══════════════════════════════════════════════════════════════════════


def test_D1_deep_loss_threshold():
    from engines.decomposer import compute_roi_verdict, ROI_DEEP_LOSS
    label, tone = compute_roi_verdict(roi=ROI_DEEP_LOSS - 0.01, efficiency_gap=0)
    assert label == 'Глубоко убыточный'
    assert tone == 'bad'


def test_D2_loss_threshold():
    from engines.decomposer import compute_roi_verdict, ROI_LOSS
    label, _ = compute_roi_verdict(roi=ROI_LOSS - 0.01, efficiency_gap=0)
    assert label == 'Убыточный'


def test_D3_breakeven_threshold():
    from engines.decomposer import compute_roi_verdict, ROI_BREAKEVEN
    label, _ = compute_roi_verdict(roi=ROI_BREAKEVEN - 0.01, efficiency_gap=0)
    assert label == 'На грани окупаемости'


def test_D4_artifact_threshold():
    from engines.decomposer import compute_roi_verdict, ROI_ARTIFACT
    label, _ = compute_roi_verdict(roi=ROI_ARTIFACT + 1, efficiency_gap=0)
    assert 'нереалистич' in label.lower()


def test_D5_unit_smell_floor():
    from engines.decomposer import compute_roi_verdict, ROI_UNIT_SMELL_FLOOR
    label, _ = compute_roi_verdict(
        roi=ROI_UNIT_SMELL_FLOOR + 1, efficiency_gap=0, unit_smell=True
    )
    assert 'не рубли' in label.lower()


def test_D6_high_abs_roi_no_smell():
    from engines.decomposer import compute_roi_verdict, ROI_HIGH_ABS
    label, tone = compute_roi_verdict(
        roi=ROI_HIGH_ABS + 1, efficiency_gap=0, unit_smell=False
    )
    assert label == 'Высокоэффективен'
    assert tone == 'good'


def test_D7_efficiency_gap_oversaturation():
    from engines.decomposer import compute_roi_verdict, GAP_OVERSAT
    label, _ = compute_roi_verdict(roi=2.0, efficiency_gap=GAP_OVERSAT - 1)
    assert label == 'Перенасыщен'


def test_D8_quantile_mode_below_min_n():
    """N < 20 channels → no quantile lookup, falls к gap fallback."""
    from engines.decomposer import compute_roi_verdict
    quantiles = {'mixed': {'p10': 0.5, 'p25': 1.0, 'p75': 3.0, 'p90': 5.0}}
    # Small N → quantile gating disabled, use gap fallback
    label, _ = compute_roi_verdict(
        roi=2.0, efficiency_gap=12,
        n_channels=5,  # < QUANTILE_MIN_N=20
        category_quantiles=quantiles,
    )
    assert label == 'Высокоэффективен'  # gap-based, не quantile


def test_D9_quantile_mode_top_10():
    """N ≥ 20 + ROI ≥ p90 → 'Top-10% по категории'."""
    from engines.decomposer import compute_roi_verdict
    quantiles = {'mixed': {'p10': 0.5, 'p25': 1.0, 'p75': 3.0, 'p90': 5.0}}
    label, tone = compute_roi_verdict(
        roi=6.0, efficiency_gap=0,
        n_channels=25,
        category_quantiles=quantiles,
    )
    assert label == 'Top-10% по категории'
    assert tone == 'good'


# ══════════════════════════════════════════════════════════════════════
# Batch E - Hierarchical metadata exposure
# ══════════════════════════════════════════════════════════════════════


def test_E1_non_hierarchical_metadata(tmp_path):
    """v1.2 flat → hierarchical.enabled=False."""
    proj = tmp_path / 'E1'
    build_synthetic_pickle(proj, seed=1, n_channels=4)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    assert r['hierarchical']['enabled'] is False


def test_E2_hierarchical_categories_exposed(tmp_path):
    """v1.3 hierarchical → channel_categories filled."""
    proj = tmp_path / 'E2'
    build_synthetic_pickle(proj, seed=1, n_channels=4)
    promote_to_hierarchical(proj)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    cats = r['hierarchical']['channel_categories']
    assert len(cats) == 4
    assert set(cats.values()) <= {'brand', 'performance', 'mixed'}


def test_E3_hierarchical_priors_exposed(tmp_path):
    """Priors summary in hierarchical metadata."""
    proj = tmp_path / 'E3'
    build_synthetic_pickle(proj, seed=1, n_channels=4)
    promote_to_hierarchical(proj)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    priors = r['hierarchical']['priors_summary']
    assert 'brand_mean' in priors or 'brand_sigma' in priors


# ══════════════════════════════════════════════════════════════════════
# Batch F - Smell flags
# ══════════════════════════════════════════════════════════════════════


def test_F1_no_unit_smell_no_flag(tmp_path):
    """All-money channels → no unit_smell flags."""
    proj = tmp_path / 'F1'
    build_synthetic_pickle(proj, seed=1, n_channels=4, mixed_units=False)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    smell_types = [f['type'] for f in r.get('smell_flags', [])]
    assert 'unit_smell' not in smell_types


def test_F2_native_unit_uc1_triggers_unit_smell(tmp_path):
    """tv_trps_brand с uc=1 + UNIT_HINTS in name → unit_smell flag."""
    proj = tmp_path / 'F2'
    md = build_synthetic_pickle(proj, seed=1, n_channels=4, mixed_units=True)
    # Force smell trigger
    md['config']['unit_costs']['tv_trps_brand'] = 1.0
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)
    smell_flags = r.get('smell_flags', [])
    has_unit_smell = any(f['type'] == 'unit_smell' for f in smell_flags)
    assert has_unit_smell, f'Expected unit_smell flag, got {smell_flags}'


# ══════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
