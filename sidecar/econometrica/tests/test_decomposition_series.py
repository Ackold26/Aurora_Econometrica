"""Аудит #12 (2026-06-07, INV-50): канонический decomposition_series.

Проверяет, что единый backend-источник timeline-декомпозиции:
- выносит signed/holiday факторы и НЕ выносит positive_control;
- пропускает нулевые факторы;
- сохраняет per-period тождество (baseline_reduced + Σфакторы + Σмедиа == исходный total);
- НЕ делает double-count положительных факторов (вычитает их из baseline);
- корректно классифицирует сторону стека (positive/negative).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engines.decomposer import build_decomposition_series


def _mk(dates, baseline, channels, sfc):
    return build_decomposition_series(dates, baseline, channels, sfc)


def test_breakout_only_signed_and_holiday_nonzero():
    dates = ['w1', 'w2', 'w3']
    baseline = [100.0, 100.0, 100.0]
    channels = {'TV': [10.0, 10.0, 10.0]}
    sfc = {
        'competitors': {'type': 'signed_competitor', 'per_period': [-5.0, -5.0, -5.0]},
        'newyear': {'type': 'holiday', 'per_period': [0.0, 20.0, 0.0]},
        'queries': {'type': 'positive_control', 'per_period': [3.0, 3.0, 3.0]},  # НЕ выносится
        'zero_holiday': {'type': 'holiday', 'per_period': [0.0, 0.0, 0.0]},      # пропуск
    }
    res = _mk(dates, baseline, channels, sfc)
    names = {s['name']: s for s in res['series']}
    assert 'competitors' in names and 'newyear' in names
    assert 'queries' not in names  # positive_control остаётся в baseline
    assert 'zero_holiday' not in names  # нулевой фактор без полосы
    roles = [s['role'] for s in res['series']]
    assert roles[0] == 'baseline'
    assert 'media' in roles


def test_per_period_identity_preserved():
    dates = ['w1', 'w2', 'w3', 'w4']
    baseline = [200.0, 210.0, 190.0, 205.0]   # уже включает control_effect
    channels = {'TV': [10.0, 12.0, 8.0, 11.0], 'Digital': [5.0, 6.0, 4.0, 7.0]}
    sfc = {
        'comp': {'type': 'signed_competitor', 'per_period': [-8.0, -3.0, -12.0, -5.0]},
        'val': {'type': 'holiday', 'per_period': [4.0, -1.0, 6.0, 2.0]},
    }
    # исходный total = baseline + media (контроли уже в baseline)
    orig = [baseline[t] + channels['TV'][t] + channels['Digital'][t] for t in range(4)]
    res = _mk(dates, baseline, channels, sfc)
    got = [0.0, 0.0, 0.0, 0.0]
    for s in res['series']:
        for t, v in enumerate(s['data']):
            got[t] += v
    for t in range(4):
        assert abs(orig[t] - got[t]) < 1e-6, f'период {t}: {orig[t]} != {got[t]}'


def test_no_double_count_positive_holiday():
    """Положительный праздник вычитается из baseline (не добавляется поверх полного)."""
    dates = ['w1', 'w2']
    baseline = [100.0, 100.0]
    channels = {'TV': [0.0, 0.0]}
    sfc = {'bts': {'type': 'holiday', 'per_period': [0.0, 50.0]}}  # пик +50 на w2
    res = _mk(dates, baseline, channels, sfc)
    base_series = next(s for s in res['series'] if s['role'] == 'baseline')
    # на w2 baseline_reduced = 100 - 50 = 50 (а не 100); полоса праздника = 50
    assert base_series['data'][1] == 50.0
    hol = next(s for s in res['series'] if s['name'] == 'bts')
    assert hol['data'][1] == 50.0
    # сумма на w2 = 50 (base) + 0 (TV) + 50 (holiday) = 100 == исходный baseline+media
    total_w2 = sum(s['data'][1] for s in res['series'])
    assert abs(total_w2 - 100.0) < 1e-6


def test_side_classification():
    dates = ['w1', 'w2']
    baseline = [100.0, 100.0]
    channels = {'TV': [0.0, 0.0]}
    sfc = {
        'neg': {'type': 'signed_competitor', 'per_period': [-10.0, -6.0]},  # mean<0
        'pos': {'type': 'holiday', 'per_period': [8.0, 2.0]},               # mean>0
    }
    res = _mk(dates, baseline, channels, sfc)
    by = {s['name']: s for s in res['series']}
    assert by['neg']['side'] == 'negative'
    assert by['pos']['side'] == 'positive'
    assert by['neg']['group'] == 'Конкуренты'
    assert by['pos']['group'] == 'Праздники'


def test_empty_inputs_safe():
    res = build_decomposition_series([], [], {}, None)
    assert res['series'][0]['role'] == 'baseline'
    assert res['dates'] == []
