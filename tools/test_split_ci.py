"""A4/OPP-04 (2026-07-03): интервалы неопределённости оптимального сплита.

Канон Jin et al. 2017: разброс оптимального микса по posterior-draws говорит
пользователю, насколько доверять модели в распределении бюджета. Зонд:
narrow-posterior → средняя ширина HDI 0.050 (TV 16% [15–17%]);
wide → 0.396 (TV 17% [4–29%]), перекрытий 10/10 пар. Время 60 draws ≈ 3-5 c.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_goalseek_honesty import _build_project  # noqa: E402
from optimize.split_ci import optimal_split_ci  # noqa: E402


@pytest.mark.slow
def test_split_ci_width_grows_with_posterior_spread(tmp_path):
    """Ширина HDI долей растёт с разбросом posterior (narrow ≪ wide);
    на wide перекрытия интервалов честно фиксируются."""
    widths = {}
    for label, sd in [('narrow', 0.03), ('wide', 0.40)]:
        pdir = _build_project(tmp_path, label, beta_sd=sd, seed=7)
        r = optimal_split_ci(str(pdir), n_draws=40)
        assert r['status'] == 'ok', r
        ws = [c['share_ci_high'] - c['share_ci_low'] for c in r['channels']]
        widths[label] = sum(ws) / len(ws)
        # Доли согласованы: средние в [0,1], сумма ~1
        total_mean = sum(c['share_mean'] for c in r['channels'])
        assert total_mean == pytest.approx(1.0, abs=0.02)
    assert widths['wide'] > widths['narrow'] * 3, (
        f"HDI сплита слеп к posterior-разбросу: narrow={widths['narrow']:.3f}, "
        f"wide={widths['wide']:.3f}"
    )


@pytest.mark.slow
def test_split_ci_overlaps_reported_on_wide(tmp_path):
    """Wide-posterior: перекрытия HDI между каналами зафиксированы —
    «разница долей статистически не выделяется» доносится до пользователя."""
    pdir = _build_project(tmp_path, 'wide_ovl', beta_sd=0.40, seed=7)
    r = optimal_split_ci(str(pdir), n_draws=40)
    assert r['status'] == 'ok'
    assert len(r['overlapping_pairs']) >= 1, 'На широком posterior перекрытия обязаны быть'
    assert 'Jin' in r['note']


def test_split_ci_requires_posterior(tmp_path):
    """OLS/legacy без posterior_samples → честный отказ NO_POSTERIOR."""
    pdir = _build_project(tmp_path, 'nopost', beta_sd=0.1, with_posterior=False)
    r = optimal_split_ci(str(pdir), n_draws=20)
    assert r['status'] == 'error'
    assert r['error_code'] == 'NO_POSTERIOR'
    assert 'апостериорные' in r['message']


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q', '-m', 'slow or not slow']))
