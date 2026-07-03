"""A3/OPP-03 (2026-07-03): единый язык extrapolation-тиров на forward-оптимизации.

Goal-seek (F-01) и сценарии (F-04) помечают выход per-period трат за
наблюдавшийся диапазон (тиры p95/p99, Chan & Perry 2017 Fig. 2) — forward-
рекомендация обязана говорить тем же языком: optimal_spend_money канала
vs его история в нативных единицах, поле result['extrapolation'].

Зонд подтвердил: границы 0-1000% → severity 2 (TV 1.72× исторического
максимума); границы 90-110% → severity 0.
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
from engines.optimizer import optimize  # noqa: E402


@pytest.fixture(scope='module')
def project(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('opp03')
    return _build_project(tmp, 'fwd_extra', beta_sd=0.2, seed=7)


def test_forward_extrapolation_fires_on_wide_bounds(project):
    """Широкие границы уводят каналы за историю → severity ≥ 1, каналы с
    ratio_vs_max, структура канала совпадает с goal-seek (единый язык)."""
    res = optimize({'min_pct': 0.0, 'max_pct': 1000.0}, str(project))
    assert res.get('status', 'ok') != 'error', res.get('message')
    ex = res.get('extrapolation')
    assert ex is not None, 'Маркер экстраполяции отсутствует в forward-результате'
    assert ex['severity'] >= 1, f'Широкие границы должны дать severity>=1: {ex}'
    assert ex['channels'], 'Список каналов за диапазоном пуст'
    ch = ex['channels'][0]
    # Та же схема, что F-01 goal-seek — единый язык для UI.
    assert {'name', 'per_period_native', 'hist_max_native', 'ratio_vs_max', 'severity'} <= set(ch)


def test_forward_extrapolation_silent_in_observed_range(project):
    """Узкий коридор вокруг текущего → severity 0, каналов нет (без ложной тревоги)."""
    res = optimize({'min_pct': 90.0, 'max_pct': 110.0}, str(project))
    assert res.get('status', 'ok') != 'error', res.get('message')
    ex = res.get('extrapolation')
    assert ex is not None
    assert ex['severity'] == 0, f'Ложная тревога экстраполяции в наблюдаемой зоне: {ex}'
    assert ex['channels'] == []


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
