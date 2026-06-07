"""SSOT timeline-факторов (аудит #12, INV-50): backend-набор факторов должен
ТОЧНО воспроизводить правило фронтового ChannelTimeline, чтобы отчёты
показывали то же, что программа.

Правило (порт ChannelTimeline.svelte):
  • показываются type ∈ signed_* | holiday;
  • positive_control сворачивается в baseline (не отдельный фактор);
  • знак по СРЕДНЕМУ per_period (не по value);
  • для отрицательных факторов baseline очищается (baseline -= per_period).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.timeline_factors import build_timeline_factors, resolve_timeline_factors


def _sfc():
    return {
        'Кол-во запросов': {  # positive_control → свёрнут
            'value': -0.0, 'type': 'positive_control',
            'per_period': [10.0, -5.0, 3.0],
        },
        'Продажи конкуренты': {  # signed, в среднем отрицательный → ниже нуля
            'value': -0.0, 'type': 'signed_competitor',
            'per_period': [-30.0, -10.0, -20.0],
        },
        'holiday_march8': {  # holiday, в среднем положительный → выше нуля
            'value': 0.0, 'type': 'holiday',
            'per_period': [5.0, -50.0, 5.0],  # mean = -13.3 → NEGATIVE
        },
        'holiday_back_to_school': {  # holiday, mean положительный
            'value': 0.0, 'type': 'holiday',
            'per_period': [-7.0, 98.0, -7.0],  # mean = 28 → POSITIVE
        },
    }


def test_positive_control_folded_into_baseline():
    tf = build_timeline_factors([100.0, 100.0, 100.0], {'TV': [1, 2, 3]}, _sfc())
    names = [f['name'] for f in tf['factors']]
    assert 'Кол-во запросов' not in names, 'positive_control должен сворачиваться в baseline'
    # показаны только signed + holiday (3 из 4)
    assert set(names) == {'Продажи конкуренты', 'holiday_march8', 'holiday_back_to_school'}


def test_sign_by_mean_per_period():
    tf = build_timeline_factors([100.0, 100.0, 100.0], {}, _sfc())
    by_name = {f['name']: f for f in tf['factors']}
    assert by_name['Продажи конкуренты']['sign'] == 'negative'
    # holiday_march8: per_period mean (5-50+5)/3 = -13.3 < 0 → negative
    assert by_name['holiday_march8']['sign'] == 'negative'
    # holiday_back_to_school: mean (−7+98−7)/3 = 28 > 0 → positive
    assert by_name['holiday_back_to_school']['sign'] == 'positive'


def test_baseline_cleared_for_negative_factors_only():
    base = [100.0, 100.0, 100.0]
    tf = build_timeline_factors(base, {}, _sfc())
    # negatives: 'Продажи конкуренты' [-30,-10,-20] + 'holiday_march8' [5,-50,5]
    # baseline -= sum(neg per_period):
    #   t0: 100 - (-30) - 5  = 125
    #   t1: 100 - (-10) - (-50) = 160
    #   t2: 100 - (-20) - 5  = 115
    assert tf['baseline_adjusted'] == [125.0, 160.0, 115.0]
    # исходный список не мутирован
    assert base == [100.0, 100.0, 100.0]


def test_group_labels_and_media_order():
    tf = build_timeline_factors([0, 0, 0], {'OLV': [1, 1, 1], 'TV': [2, 2, 2]}, _sfc())
    assert tf['media_order'] == ['OLV', 'TV']
    by_name = {f['name']: f for f in tf['factors']}
    assert by_name['Продажи конкуренты']['group_label'] == 'Конкуренты'
    assert by_name['holiday_march8']['group_label'] == 'Праздники'


def test_empty_and_malformed_inputs_safe():
    assert build_timeline_factors(None, None, None) == {
        'baseline_adjusted': [], 'media_order': [], 'factors': []
    }
    # фактор без per_period — пропускается
    tf = build_timeline_factors([1.0], {}, {'X': {'type': 'holiday'}})
    assert tf['factors'] == []


def test_resolve_uses_present_field_verbatim():
    decompose = {'timeline_factors': {'baseline_adjusted': [1.0], 'media_order': ['X'], 'factors': []}}
    assert resolve_timeline_factors(decompose) is decompose['timeline_factors']


def test_resolve_backfills_legacy_without_field():
    # legacy decomposition.json без timeline_factors → пересчёт из raw полей
    legacy = {
        'time_series': {'baseline': [100.0, 100.0, 100.0], 'channels': {'TV': [1, 2, 3]}},
        'signed_factor_contributions': _sfc(),
    }
    tf = resolve_timeline_factors(legacy)
    names = {f['name'] for f in tf['factors']}
    assert names == {'Продажи конкуренты', 'holiday_march8', 'holiday_back_to_school'}
    assert tf['media_order'] == ['TV']


def test_no_per_period_factor_skipped_not_crash():
    tf = build_timeline_factors([1.0, 2.0], {}, {
        'Y': {'type': 'signed_competitor', 'per_period': []},  # пустой → skip
    })
    assert tf['factors'] == []
    assert tf['baseline_adjusted'] == [1.0, 2.0]
