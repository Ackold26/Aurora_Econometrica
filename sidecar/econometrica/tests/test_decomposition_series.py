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


# ── Автосезонность (2026-07-04): полоса «Сезонность» + % к базе + 4 группы ──


def test_seasonality_band_breakout_and_type():
    """Фактор type='seasonality' выносится полосой с group='Сезонность'."""
    dates = ['w1', 'w2', 'w3', 'w4']
    baseline = [100.0, 100.0, 100.0, 100.0]
    channels = {'TV': [0.0, 0.0, 0.0, 0.0]}
    sfc = {'Сезонность': {'type': 'seasonality', 'per_period': [20.0, -10.0, 15.0, -25.0]}}
    res = build_decomposition_series(dates, baseline, channels, sfc)
    season = next((s for s in res['series'] if s['type'] == 'seasonality'), None)
    assert season is not None, 'полоса «Сезонность» должна быть вынесена'
    assert season['group'] == 'Сезонность'
    assert season['role'] == 'factor'
    assert season['data'] == [20.0, -10.0, 15.0, -25.0]


def test_seasonality_pct_of_base_math():
    """pct_of_base[t] = 100·эффект[t]/base_reduced[t] (base после выноса сезона)."""
    dates = ['w1', 'w2']
    baseline = [120.0, 90.0]  # включает сезонную волну
    channels = {'TV': [0.0, 0.0]}
    sfc = {'Сезонность': {'type': 'seasonality', 'per_period': [20.0, -10.0]}}
    res = build_decomposition_series(dates, baseline, channels, sfc)
    season = next(s for s in res['series'] if s['type'] == 'seasonality')
    # base_reduced: w1 = 120-20 = 100; w2 = 90-(-10) = 100
    # pct: w1 = 100·20/100 = +20%; w2 = 100·(-10)/100 = -10%
    assert 'pct_of_base' in season
    assert season['pct_of_base'] == [20.0, -10.0]


def test_seasonality_pct_of_base_zero_guard():
    """Деление на ~0 базу → 0.0 (без исключения/inf)."""
    dates = ['w1', 'w2']
    baseline = [10.0, 0.0]  # w2 base после выноса станет 0
    channels = {'TV': [0.0, 0.0]}
    sfc = {'Сезонность': {'type': 'seasonality', 'per_period': [5.0, 0.0]}}
    res = build_decomposition_series(dates, baseline, channels, sfc)
    season = next(s for s in res['series'] if s['type'] == 'seasonality')
    # w2: per_period=0 (нулевой на этом шаге), base=0 → guard → 0.0
    assert season['pct_of_base'][1] == 0.0


def test_seasonality_identity_preserved():
    """Тождество base_reduced + Σфакторы + Σмедиа == исходный total с сезонностью."""
    dates = ['w1', 'w2', 'w3', 'w4']
    baseline = [200.0, 230.0, 180.0, 210.0]
    channels = {'TV': [10.0, 12.0, 8.0, 11.0]}
    sfc = {
        'Сезонность': {'type': 'seasonality', 'per_period': [30.0, -20.0, 25.0, -15.0]},
        'comp': {'type': 'signed_competitor', 'per_period': [-5.0, -3.0, -8.0, -2.0]},
    }
    orig = [baseline[t] + channels['TV'][t] for t in range(4)]
    res = build_decomposition_series(dates, baseline, channels, sfc)
    got = [0.0, 0.0, 0.0, 0.0]
    for s in res['series']:
        for t, v in enumerate(s['data']):
            got[t] += v
    for t in range(4):
        assert abs(orig[t] - got[t]) < 1e-6, f'период {t}: {orig[t]} != {got[t]}'


def test_no_seasonality_no_band():
    """Нет seasonality-фактора → нет полосы и нет pct_of_base у прочих серий."""
    dates = ['w1', 'w2']
    baseline = [100.0, 100.0]
    channels = {'TV': [5.0, 5.0]}
    sfc = {'comp': {'type': 'signed_competitor', 'per_period': [-3.0, -3.0]}}
    res = build_decomposition_series(dates, baseline, channels, sfc)
    assert all(s['type'] != 'seasonality' for s in res['series'])
    assert all('pct_of_base' not in s for s in res['series'])


def test_category_band_breakout_top_group():
    """Фаза Б: фактор type='category' выносится полосой «Категория» → ВНЕШНИЕ ФАКТОРЫ."""
    dates = ['w1', 'w2', 'w3']
    baseline = [100.0, 100.0, 100.0]
    channels = {'TV': [5.0, 5.0, 5.0]}
    sfc = {'Продажи рынка руб': {'type': 'category', 'per_period': [8.0, 12.0, 10.0]}}
    res = build_decomposition_series(dates, baseline, channels, sfc)
    cat = next((s for s in res['series'] if s['type'] == 'category'), None)
    assert cat is not None, 'полоса «Категория» должна быть вынесена'
    assert cat['group'] == 'Категория'
    assert cat['top_group'] == 'ВНЕШНИЕ ФАКТОРЫ'
    assert cat['role'] == 'factor'


def test_top_group_four_groups():
    """Каждая серия получает top_group ∈ 4 верхних группы (решение Антона)."""
    dates = ['w1', 'w2']
    baseline = [100.0, 100.0]
    channels = {'TV': [10.0, 10.0]}
    sfc = {
        'Сезонность': {'type': 'seasonality', 'per_period': [8.0, -8.0]},
        'newyear': {'type': 'holiday', 'per_period': [0.0, 12.0]},
        'comp': {'type': 'signed_competitor', 'per_period': [-4.0, -4.0]},
        'price': {'type': 'signed_price', 'per_period': [3.0, 3.0]},
    }
    res = build_decomposition_series(dates, baseline, channels, sfc)
    by = {s['name']: s for s in res['series']}
    assert by['Базовый уровень']['top_group'] == 'БАЗА'
    assert by['Сезонность']['top_group'] == 'БАЗА'
    assert by['newyear']['top_group'] == 'БАЗА'
    assert by['TV']['top_group'] == 'МЕДИА'
    assert by['comp']['top_group'] == 'КОНКУРЕНТЫ'
    assert by['price']['top_group'] == 'ВНЕШНИЕ ФАКТОРЫ'
    # Все 4 верхние группы представлены
    tops = {s['top_group'] for s in res['series']}
    assert tops == {'БАЗА', 'МЕДИА', 'ВНЕШНИЕ ФАКТОРЫ', 'КОНКУРЕНТЫ'}
