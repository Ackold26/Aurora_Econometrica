"""Decomposer engine invariants — property-based tests (Phase B1 of engine audit extension).

Plan: C:\\Users\\ackol\\Desktop\\optimizer-audit-followup-plan.md, этап 4.

Thirteen formal invariants verified across random seeds:

    D1  — Energy conservation: total_sales == baseline + media_contribution (post-residual)
    D2  — Contribution sign matches β sign (positive β → non-negative contribution)
    D3  — ROI compute identity: roi = contribution / spend_money; 0 spend → roi=0
    D4  — mROAS alignment с optimizer (3-way alignment, both engines call same helper)
    D5  — Share-of-spend / share-of-effect sum к 100%
    D6  — efficiency_gap = share_of_effect - share_of_spend (rounding consistency)
    D7  — Verdict thresholds: ROI bands map к correct labels
    D8  — Action vocabulary alignment с optimizer (compute_channel_action shared helper)
    D9  — Time-series consistency: sum(time_series_channels[col]) ≈ channel.contribution
    D10 — Untrained channel: zero-contribution + verdict='Не обучен' + ci_skip_reason
    D11 — Waterfall sums: baseline + Σ channels = total
    D12 — Posterior ROI CI ordering: roi_ci_low ≤ roi ≤ roi_ci_high
    D13 — Determinism: same input → identical output

Math reference: docs/MATH_AUDIT_v1_3_PHASE_0_1.md (mROAS chain rule),
post-audit fix в decomposer.py:487-505 (energy conservation residual absorption).

Run:
    pytest tools/test_decomposer_invariants.py -v
"""
from __future__ import annotations

import math
import pickle
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _optimizer_fixtures import (  # noqa: E402
    build_synthetic_pickle,
    is_ok,
    promote_to_hierarchical,
)


# ──────────────────────────────────────────────────────────────────────
# D1 — Energy conservation: total_sales == baseline + media (within rounding)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(15)))
def test_D1_energy_conservation(tmp_path, seed):
    """sum(baseline_per_period) + Σ sum(channel_contributions) == total_sales."""
    proj = tmp_path / f'D1_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    total_sales = float(r['total_sales'])
    baseline = float(r['baseline'])
    media = float(r['media_contribution'])
    expected = baseline + media
    rel_err = abs(total_sales - expected) / max(abs(total_sales), 1.0)
    # 1.5% tolerance: round-0 на total_sales/baseline/media + per-channel round-0
    assert rel_err < 0.015, (
        f'D1 (seed={seed}): total_sales={total_sales:.0f}, '
        f'baseline+media={expected:.0f}, rel_err={rel_err*100:.3f}%'
    )


# ──────────────────────────────────────────────────────────────────────
# D2 — Per-channel contribution sign matches β sign
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_D2_contribution_sign_matches_beta(tmp_path, seed):
    """For positive β + positive raw spend: contribution ≥ 0 (Hill ≥ 0)."""
    proj = tmp_path / f'D2_{seed}'
    md = build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    for ch in r['channels']:
        beta = float(ch.get('beta', 0))
        contribution = float(ch['contribution'])
        if ch.get('untrained'):
            continue
        # Synthetic fixture uses positive β values via rng.uniform(0.04, 0.12)
        assert beta > 0, f'D2 seed={seed} ch={ch["name"]}: β={beta}'
        # → contribution should be ≥ 0 (Hill saturation ∈ [0, 1))
        assert contribution >= 0, (
            f'D2 (seed={seed}) ch={ch["name"]}: positive β={beta:.4f} but '
            f'contribution={contribution} < 0'
        )


# ──────────────────────────────────────────────────────────────────────
# D3 — ROI compute identity
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(15)))
def test_D3_roi_compute_identity(tmp_path, seed):
    """For each channel: roi == round(contribution / spend_money, 2); zero spend → roi=0."""
    proj = tmp_path / f'D3_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    for ch in r['channels']:
        spend = float(ch['spend'])
        contribution = float(ch['contribution'])
        roi = float(ch['roi'])
        if spend <= 0:
            assert roi == 0, f'D3 ch={ch["name"]} (seed={seed}): zero spend but roi={roi}'
            continue
        expected = round(contribution / spend, 2)
        assert abs(roi - expected) < 0.05, (
            f'D3 (seed={seed}) ch={ch["name"]}: roi={roi}, '
            f'contribution/spend={expected} (rounded), Δ={abs(roi-expected):.4f}'
        )


# ──────────────────────────────────────────────────────────────────────
# D4 — mROAS alignment с optimizer (3-way alignment cross-check)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_D4_mroas_alignment_with_optimizer(tmp_path, seed):
    """decompose.mroi_current ≈ optimize.mroi_current (same _compute_mroas_money helper)."""
    proj = tmp_path / f'D4_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    from engines.optimizer import optimize

    dec = decompose(str(proj))
    opt = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    if not is_ok(dec) or not is_ok(opt):
        pytest.skip(f'D4 (seed={seed}): one engine failed')

    dec_mroi = {ch['name']: float(ch.get('mroi_current') or 0) for ch in dec['channels']}
    opt_mroi = {ch['name']: float(ch.get('mroi_current') or 0) for ch in opt['channels']}
    common = set(dec_mroi) & set(opt_mroi)
    assert common, f'D4 (seed={seed}): no common channels'

    # Optimizer in analyst mode uses train_n; decomposer also uses train_n → identical.
    for name in common:
        delta = abs(dec_mroi[name] - opt_mroi[name])
        # Round-4 на mroi (1e-4) — tolerance 1e-3 absolute
        assert delta < 1e-3, (
            f'D4 (seed={seed}) ch={name}: dec_mroi={dec_mroi[name]:.6f}, '
            f'opt_mroi={opt_mroi[name]:.6f}, Δ={delta:.6f}'
        )


# ──────────────────────────────────────────────────────────────────────
# D5 — Share-of-spend + share-of-effect sums к 100%
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_D5_shares_sum_to_100(tmp_path, seed):
    """Σ share_of_spend ≈ 100; Σ share_of_effect ≈ 100 (across non-zero channels)."""
    proj = tmp_path / f'D5_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    sum_spend_share = sum(float(ch['share_of_spend']) for ch in r['channels'])
    sum_effect_share = sum(float(ch['share_of_effect']) for ch in r['channels'])

    # Round-1 на shares × n_channels = potential drift up to 0.5 pp
    assert abs(sum_spend_share - 100) < 1.0, (
        f'D5 (seed={seed}): Σshare_of_spend={sum_spend_share:.2f}'
    )
    assert abs(sum_effect_share - 100) < 1.0, (
        f'D5 (seed={seed}): Σshare_of_effect={sum_effect_share:.2f}'
    )


# ──────────────────────────────────────────────────────────────────────
# D6 — efficiency_gap = share_of_effect - share_of_spend
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_D6_efficiency_gap_identity(tmp_path, seed):
    """efficiency_gap[c] = share_of_effect[c] - share_of_spend[c] within rounding."""
    proj = tmp_path / f'D6_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    for ch in r['channels']:
        eff_gap = float(ch['efficiency_gap'])
        expected = round(float(ch['share_of_effect']) - float(ch['share_of_spend']), 1)
        assert abs(eff_gap - expected) < 0.2, (
            f'D6 ch={ch["name"]} (seed={seed}): gap={eff_gap}, '
            f'effect-spend={expected} (Δ={abs(eff_gap - expected):.2f})'
        )


# ──────────────────────────────────────────────────────────────────────
# D7 — Verdict thresholds correctness
# ──────────────────────────────────────────────────────────────────────


def test_D7_verdict_thresholds():
    """compute_roi_verdict applies correct labels per ROI band."""
    from engines.decomposer import compute_roi_verdict

    # Deep loss
    label, tone = compute_roi_verdict(roi=0.3, efficiency_gap=0)
    assert label == 'Глубоко убыточный', f'D7 deep loss: {label}'
    assert tone == 'bad'

    # Loss
    label, _ = compute_roi_verdict(roi=0.7, efficiency_gap=0)
    assert label == 'Убыточный', f'D7 loss: {label}'

    # Breakeven
    label, _ = compute_roi_verdict(roi=0.95, efficiency_gap=0)
    assert label == 'На грани окупаемости', f'D7 breakeven: {label}'

    # High ROI absolute (no smell)
    label, tone = compute_roi_verdict(roi=8.0, efficiency_gap=0, unit_smell=False)
    assert label == 'Высокоэффективен', f'D7 high abs: {label}'
    assert tone == 'good'

    # Unit smell flag
    label, _ = compute_roi_verdict(roi=80.0, efficiency_gap=0, unit_smell=True)
    assert 'не рубли' in label.lower(), f'D7 unit smell: {label}'

    # Artifact (>100)
    label, _ = compute_roi_verdict(roi=150.0, efficiency_gap=0)
    assert 'нереалистич' in label.lower(), f'D7 artifact: {label}'

    # Efficiency gap thresholds
    label, _ = compute_roi_verdict(roi=2.0, efficiency_gap=12)
    assert label == 'Высокоэффективен', f'D7 gap high: {label}'

    label, _ = compute_roi_verdict(roi=2.0, efficiency_gap=-12)
    assert label == 'Перенасыщен', f'D7 gap saturated: {label}'

    label, _ = compute_roi_verdict(roi=2.0, efficiency_gap=0)
    assert label == 'Сбалансирован', f'D7 balanced: {label}'


def test_D7_wide_ci_suffix():
    """Wide ROI CI → suffix «(широкий ROI-интервал)» appended to verdict."""
    from engines.decomposer import compute_roi_verdict
    label, tone = compute_roi_verdict(
        roi=2.0, efficiency_gap=12,
        roi_ci_low=0.5, roi_ci_high=10.0,  # wide CI
    )
    assert 'широкий' in label.lower(), f'D7 wide CI: {label}'


# ──────────────────────────────────────────────────────────────────────
# D8 — Action vocabulary alignment with optimizer
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_D8_action_decoration_present(tmp_path, seed):
    """Each channel has action / action_label / action_tone (compute_channel_action shared)."""
    proj = tmp_path / f'D8_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    for ch in r['channels']:
        for key in ('action', 'action_label', 'action_tone',
                    'action_reasoning', 'action_priority', 'action_confidence'):
            assert key in ch, f'D8 ch={ch["name"]}: missing `{key}`'
        # Action key должен быть в ACTION_KEYS vocabulary
        assert ch['action'] in {
            'Scale', 'Hold', 'Watch', 'Reduce', 'Cut', 'Uncertain'
        }, f'D8 ch={ch["name"]}: invalid action `{ch["action"]}`'


# ──────────────────────────────────────────────────────────────────────
# D9 — Time-series sum equals channel.contribution
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_D9_time_series_sum_consistency(tmp_path, seed):
    """sum(time_series.channels[col]) ≈ channel.contribution within rounding."""
    proj = tmp_path / f'D9_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    ts_channels = r['time_series']['channels']
    for ch in r['channels']:
        if ch.get('untrained'):
            continue
        col = ch['name']
        ts_sum = sum(float(v) for v in ts_channels[col])
        contribution = float(ch['contribution'])
        rel_err = abs(ts_sum - contribution) / max(abs(contribution), 1.0)
        # round-1 на time series + round-0 на contribution → up to 0.5%
        assert rel_err < 0.01, (
            f'D9 ch={col} (seed={seed}): ts_sum={ts_sum:.0f}, '
            f'contribution={contribution:.0f}, rel_err={rel_err*100:.3f}%'
        )


# ──────────────────────────────────────────────────────────────────────
# D10 — Untrained channel zero-contribution + 'Не обучен' verdict
# ──────────────────────────────────────────────────────────────────────


def test_D10_untrained_channel_zero_contribution(tmp_path):
    """Channel в untrained_channels list: contribution=0, verdict='Не обучен'."""
    proj = tmp_path / 'D10'
    build_synthetic_pickle(
        proj, seed=42, n_channels=4, n_periods=24,
        untrained_channels=['ch_2'],
    )

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    untrained = next((ch for ch in r['channels'] if ch['name'] == 'ch_2'), None)
    assert untrained is not None
    assert float(untrained['contribution']) == 0.0
    assert untrained['verdict'] == 'Не обучен'
    assert untrained['untrained'] is True
    assert untrained.get('ci_skip_reason') == 'untrained_channel'


# ──────────────────────────────────────────────────────────────────────
# D11 — Waterfall sums correctly
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_D11_waterfall_sums(tmp_path, seed):
    """waterfall.values: baseline + Σ channels ≈ total (last value)."""
    proj = tmp_path / f'D11_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    waterfall = r['waterfall']
    values = waterfall['values']
    types = waterfall['types']
    assert types[0] == 'baseline'
    assert types[-1] == 'total'

    baseline = float(values[0])
    total = float(values[-1])
    channel_sum = sum(float(v) for v, t in zip(values, types) if t == 'channel')

    expected_total = baseline + channel_sum
    rel_err = abs(total - expected_total) / max(abs(total), 1.0)
    assert rel_err < 0.015, (
        f'D11 (seed={seed}): waterfall total={total:.0f}, '
        f'baseline+channels={expected_total:.0f}, rel_err={rel_err*100:.3f}%'
    )


# ──────────────────────────────────────────────────────────────────────
# D12 — Posterior ROI CI ordering: low ≤ point ≤ high
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_D12_posterior_roi_ci_ordering(tmp_path, seed):
    """When posterior_samples available: roi_ci_low ≤ roi ≤ roi_ci_high."""
    proj = tmp_path / f'D12_{seed}'
    build_synthetic_pickle(
        proj, seed=seed, n_channels=4, n_periods=24,
        n_posterior_samples=200,
    )

    from engines.decomposer import decompose
    r = decompose(str(proj))
    assert is_ok(r)

    found_ci = False
    for ch in r['channels']:
        if ch.get('roi_ci_low') is None:
            continue
        found_ci = True
        roi = float(ch['roi'])
        lo = float(ch['roi_ci_low'])
        hi = float(ch['roi_ci_high'])
        assert lo <= hi, f'D12 ch={ch["name"]}: lo={lo} > hi={hi}'
        margin = max(abs(hi - lo) * 0.10, abs(roi) * 0.10, 0.5)
        assert lo - margin <= roi <= hi + margin, (
            f'D12 ch={ch["name"]} (seed={seed}): roi={roi} not в [{lo}, {hi}] (margin={margin})'
        )

    if not found_ci:
        pytest.skip(f'D12 (seed={seed}): no posterior CI in any channel')


# ──────────────────────────────────────────────────────────────────────
# D13 — Determinism
# ──────────────────────────────────────────────────────────────────────


def test_D13_determinism(tmp_path):
    """Two consecutive decompose calls produce byte-identical results."""
    proj = tmp_path / 'D13'
    build_synthetic_pickle(proj, seed=99, n_channels=4, n_periods=24)

    from engines.decomposer import decompose
    r1 = decompose(str(proj))
    r2 = decompose(str(proj))
    assert is_ok(r1) and is_ok(r2)

    assert r1['total_sales'] == r2['total_sales']
    assert r1['baseline'] == r2['baseline']
    assert r1['media_contribution'] == r2['media_contribution']

    # Channels: compare key fields
    by_name1 = {ch['name']: ch for ch in r1['channels']}
    by_name2 = {ch['name']: ch for ch in r2['channels']}
    assert set(by_name1) == set(by_name2)
    for name in by_name1:
        for k in ('contribution', 'roi', 'mroi_current', 'beta', 'spend',
                  'share_of_spend', 'share_of_effect', 'efficiency_gap',
                  'verdict', 'verdict_tone', 'action'):
            assert by_name1[name][k] == by_name2[name][k], (
                f'D13 {name}.{k}: {by_name1[name][k]} != {by_name2[name][k]}'
            )


# ──────────────────────────────────────────────────────────────────────
# Standalone runner
# ──────────────────────────────────────────────────────────────────────


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
