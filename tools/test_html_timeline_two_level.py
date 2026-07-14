"""Аудит №2 Б-5 (2026-07-04): двухрежимный timeline HTML-отчёта.

Контракт payload: CHART_DATA.timeline = {weeks, overview, detail}.
  • overview — SSOT-свёртка 4 групп (паритет с дефолтом программы);
  • detail  — прежний состав Аудита #12 (reduced baseline + каналы + факторы);
  • тождество: Σ серий overview[t] == Σ серий detail[t] (оба режима показывают
    ОДИН total — переключение вида не меняет сумму).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _decompose_fixture() -> dict:
    """Мини-decompose с канонической decomposition_series: 4 группы, 3 периода."""
    dates = ['2025-01-01', '2025-02-01', '2025-03-01']
    series = [
        {'name': 'Базовый уровень', 'role': 'baseline', 'type': 'baseline', 'group': 'База', 'top_group': 'БАЗА', 'side': 'positive', 'data': [1000, 1000, 1000]},
        {'name': 'TV', 'role': 'media', 'type': 'media', 'group': 'Медиа', 'top_group': 'МЕДИА', 'side': 'positive', 'data': [200, 250, 300]},
        {'name': 'Digital', 'role': 'media', 'type': 'media', 'group': 'Медиа', 'top_group': 'МЕДИА', 'side': 'positive', 'data': [100, 120, 140]},
        {'name': 'Сезонность', 'role': 'factor', 'type': 'seasonality', 'group': 'Сезонность', 'top_group': 'БАЗА', 'side': 'positive', 'data': [-50, 30, 80], 'pct_of_base': [-5.0, 3.0, 8.0]},
        {'name': 'Цена', 'role': 'factor', 'type': 'signed_price', 'group': 'Цена', 'top_group': 'ВНЕШНИЕ ФАКТОРЫ', 'side': 'positive', 'data': [30, 20, 10]},
        {'name': 'Конкуренты', 'role': 'factor', 'type': 'signed_competitor', 'group': 'Конкуренты', 'top_group': 'КОНКУРЕНТЫ', 'side': 'negative', 'data': [-80, -60, -40]},
    ]
    return {
        'status': 'ok',
        'channels': [
            {'name': 'TV', 'spend': 10e6, 'contribution': 750, 'roi': 1.5},
            {'name': 'Digital', 'spend': 5e6, 'contribution': 360, 'roi': 1.2},
        ],
        'time_series': {
            'dates': dates,
            'baseline': [950, 1030, 1050],  # legacy поле (reduced в ds — истина)
            'channels': {'TV': [200, 250, 300], 'Digital': [100, 120, 140]},
        },
        'decomposition_series': {'dates': dates, 'series': series},
    }


def _chart_data(html: str) -> dict:
    idx = html.index('{', html.index('var CHART_DATA'))
    obj, _ = json.JSONDecoder().raw_decode(html, idx)
    return obj


def _build_html_timeline() -> dict:
    from engines.html_export import build_html
    with tempfile.TemporaryDirectory() as td:
        out = str(Path(td) / 'r.html')
        res = build_html({}, _decompose_fixture(), {}, out, project_id='TwoLevel')
        assert res.get('status') == 'ok', res
        html = Path(out).read_text(encoding='utf-8')
    assert 'id="tl-view-toggle"' in html, 'нет кнопки переключателя режима'
    return _chart_data(html)['timeline']


def _sum_mode(mode: dict, n: int) -> list[float]:
    acc = [0.0] * n
    for arr in [mode.get('baseline') or []] + list((mode.get('channels') or {}).values()):
        for t in range(min(n, len(arr))):
            acc[t] += float(arr[t])
    for f in mode.get('factors') or []:
        d = f.get('data') or []
        for t in range(min(n, len(d))):
            acc[t] += float(d[t])
    return acc


def test_payload_has_two_modes():
    tl = _build_html_timeline()
    assert set(tl.keys()) == {'weeks', 'overview', 'detail'}
    assert len(tl['weeks']) == 3


def test_overview_matches_ssot_collapse():
    from engines.decomposer import collapse_series_to_top_groups
    tl = _build_html_timeline()
    ovr = tl['overview']
    collapsed = collapse_series_to_top_groups(_decompose_fixture()['decomposition_series']['series'])
    names = {ovr['baseline_label']} | set(ovr['channels']) | {f['name'] for f in ovr['factors']}
    assert names == {c['name'] for c in collapsed}
    # БАЗА-агрегат: 1000-50=950; 1030; 1080
    assert ovr['baseline_label'] == 'База'
    assert ovr['baseline'] == [950.0, 1030.0, 1080.0]
    # группа с отрицательным итогом идёт negative-полосой с фирменным rgb
    comp = next(f for f in ovr['factors'] if f['name'] == 'Конкуренты')
    assert comp['side'] == 'negative' and comp['rgb'] == '#dc2626'


def test_detail_keeps_full_composition():
    tl = _build_html_timeline()
    det = tl['detail']
    assert det['baseline_label'] == 'Базовый уровень'
    assert set(det['channels']) == {'TV', 'Digital'}
    assert {f['name'] for f in det['factors']} == {'Сезонность', 'Цена', 'Конкуренты'}
    # детальные факторы сохраняют type (цвет по типу в JS)
    assert {f['type'] for f in det['factors']} == {'seasonality', 'signed_price', 'signed_competitor'}


def test_modes_share_identity():
    """Σ overview[t] == Σ detail[t] — переключение вида не меняет total."""
    tl = _build_html_timeline()
    n = len(tl['weeks'])
    s_o = _sum_mode(tl['overview'], n)
    s_d = _sum_mode(tl['detail'], n)
    for t in range(n):
        assert abs(s_o[t] - s_d[t]) < 1e-6, f'период {t}: overview {s_o[t]} != detail {s_d[t]}'
