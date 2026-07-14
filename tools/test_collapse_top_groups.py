"""П2 (2026-07-04): SSOT-свёртка серий в 4 верхние группы для отчётов.

collapse_series_to_top_groups — зеркало свёрнутого режима фронта
(decomposition-view.js planViewSeries, пустой expanded). Главный инвариант:
свёртка НЕ меняет значения → Σ агрегатов[t] == Σ исходных серий[t] (тождество
энергосохранения переносится в обзорный timeline отчёта).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engines.decomposer import (  # noqa: E402
    collapse_series_to_top_groups,
    _TOP_GROUP_ORDER,
    _TOP_GROUP_DISPLAY,
)


def _fixture():
    """~форма decomposition_series: 3 периода, 4 группы, знакопеременная сезонность."""
    return [
        {'name': 'Базовый уровень', 'role': 'baseline', 'type': 'baseline', 'group': 'База', 'top_group': 'БАЗА', 'side': 'positive', 'data': [1000, 1000, 1000]},
        {'name': 'TV', 'role': 'media', 'type': 'media', 'group': 'Медиа', 'top_group': 'МЕДИА', 'side': 'positive', 'data': [200, 250, 300]},
        {'name': 'Digital', 'role': 'media', 'type': 'media', 'group': 'Медиа', 'top_group': 'МЕДИА', 'side': 'positive', 'data': [100, 120, 140]},
        {'name': 'Сезонность', 'role': 'factor', 'type': 'seasonality', 'group': 'Сезонность', 'top_group': 'БАЗА', 'side': 'positive', 'data': [-50, 30, 80]},
        {'name': 'Праздники', 'role': 'factor', 'type': 'holiday', 'group': 'Праздники', 'top_group': 'БАЗА', 'side': 'positive', 'data': [40, 0, 0]},
        {'name': 'Цена', 'role': 'factor', 'type': 'signed_price', 'group': 'Цена', 'top_group': 'ВНЕШНИЕ ФАКТОРЫ', 'side': 'positive', 'data': [30, 20, 10]},
        {'name': 'Погода', 'role': 'factor', 'type': 'signed_weather', 'group': 'Погода', 'top_group': 'ВНЕШНИЕ ФАКТОРЫ', 'side': 'negative', 'data': [-20, -10, -5]},
        {'name': 'Конкуренты', 'role': 'factor', 'type': 'signed_competitor', 'group': 'Конкуренты', 'top_group': 'КОНКУРЕНТЫ', 'side': 'negative', 'data': [-80, -60, -40]},
    ]


def _sum_by_period(rows, n):
    acc = [0.0] * n
    for s in rows:
        for t in range(n):
            acc[t] += s['data'][t]
    return acc


def test_identity_collapsed_equals_original():
    """Σ агрегатов[t] == Σ исходных[t] — свёртка не меняет значения."""
    src = _fixture()
    n = 3
    truth = _sum_by_period(src, n)
    collapsed = collapse_series_to_top_groups(src)
    got = _sum_by_period(collapsed, n)
    for t in range(n):
        assert abs(got[t] - truth[t]) < 1e-6, f'период {t}: {got[t]} != {truth[t]}'


def test_four_groups_in_canonical_order():
    collapsed = collapse_series_to_top_groups(_fixture())
    assert [c['top_group'] for c in collapsed] == list(_TOP_GROUP_ORDER)
    assert [c['name'] for c in collapsed] == [_TOP_GROUP_DISPLAY[g] for g in _TOP_GROUP_ORDER]


def test_base_aggregate_values():
    """БАЗА = baseline + сезонность + праздники поэлементно."""
    collapsed = collapse_series_to_top_groups(_fixture())
    baza = next(c for c in collapsed if c['top_group'] == 'БАЗА')
    # t0: 1000-50+40=990; t1: 1000+30=1030; t2: 1000+80=1080
    assert baza['data'] == [990.0, 1030.0, 1080.0]
    assert baza['member_count'] == 3


def test_side_by_group_sign():
    collapsed = {c['top_group']: c for c in collapse_series_to_top_groups(_fixture())}
    assert collapsed['БАЗА']['side'] == 'positive'
    assert collapsed['МЕДИА']['side'] == 'positive'
    assert collapsed['КОНКУРЕНТЫ']['side'] == 'negative'
    # ВНЕШНИЕ: (30-20)+(20-10)+(10-5)=35 > 0
    assert collapsed['ВНЕШНИЕ ФАКТОРЫ']['side'] == 'positive'


def test_empty_and_missing_top_group():
    assert collapse_series_to_top_groups([]) == []
    # top_group отсутствует → берётся из group через _TOP_GROUP_MAP
    rows = [{'name': 'X', 'group': 'Цена', 'data': [1, 2]}]
    out = collapse_series_to_top_groups(rows)
    assert len(out) == 1 and out[0]['top_group'] == 'ВНЕШНИЕ ФАКТОРЫ'


def test_ragged_lengths_padded():
    rows = [
        {'name': 'A', 'top_group': 'МЕДИА', 'data': [1, 2, 3]},
        {'name': 'B', 'top_group': 'МЕДИА', 'data': [10]},
    ]
    out = collapse_series_to_top_groups(rows)
    assert out[0]['data'] == [11.0, 2.0, 3.0]


def test_identity_on_real_decompose():
    """Тождество на РЕАЛЬНОМ decompose (готовый pkl без MCMC, если доступен)."""
    proj = Path(r'C:\Users\ackol\AppData\Local\Temp\mmx_4groups_dw7vr06g')
    if not (proj / 'models' / 'latest.pkl').exists():
        import pytest
        pytest.skip('фикстура mmx_4groups недоступна')
    from engines.decomposer import decompose
    d = decompose(str(proj), save_results=False)
    assert d.get('status') == 'ok'
    series = d['decomposition_series']['series']
    n = len(series[0]['data'])
    truth = _sum_by_period(series, n)
    got = _sum_by_period(collapse_series_to_top_groups(series), n)
    for t in range(n):
        assert abs(got[t] - truth[t]) < max(1.0, abs(truth[t]) * 1e-6)
