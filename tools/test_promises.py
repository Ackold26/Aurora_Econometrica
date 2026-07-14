"""E4 (2026-07-03): рекомендации-обещания — движок promises.py.

Петля: создать обещание (точка отсчёта = длина данных) → клиент принёс свежие
строки → check сверяет факт с интервалом ожидания → kept/missed честно,
pending пока данных мало, окончательные вердикты не пересматриваются.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_rolling_backtest import _make_ols_project  # noqa: E402
from engines.promises import (  # noqa: E402
    check_promises,
    create_promise,
    list_promises,
)


def _append_tail(pdir: Path, values: list[float]) -> None:
    """Дописать свежие строки KPI (клиент принёс новый период) БЕЗ ретрейна."""
    f = pdir / 'data.xlsx'
    df = pd.read_excel(f)
    last = pd.to_datetime(df['date'].iloc[-1])
    rng = np.random.default_rng(9)
    tail = pd.DataFrame({
        'date': pd.date_range(last, periods=len(values) + 1, freq='ME')[1:].strftime('%Y-%m-%d'),
        'TV': np.clip(rng.normal(100, 10, len(values)), 10, None).round(2),
        'Digital': np.clip(rng.normal(200, 20, len(values)), 20, None).round(2),
        'sales': [round(v, 2) for v in values],
    })
    pd.concat([df, tail], ignore_index=True).to_excel(f, index=False)


@pytest.fixture()
def project(tmp_path):
    return _make_ols_project(tmp_path, 'promise_proj')  # 40 наблюдений


def _mk(project, **kw):
    args = {
        'action_text': 'Сдвиньте 10% бюджета с Digital на TV',
        'expected_kpi_total': 4000.0,
        'ci_low': 3600.0,
        'ci_high': 4400.0,
        'horizon_periods': 4,
        'channel_changes': {'TV': 10.0, 'Digital': -10.0},
        'extrapolation_flag': False,
    }
    args.update(kw)
    return create_promise(str(project), **args)


def test_create_and_list_roundtrip(project):
    r = _mk(project)
    assert r['status'] == 'ok'
    p = r['promise']
    assert p['check_after_index'] == 40, 'точка отсчёта = длина данных при создании'
    assert p['status'] == 'pending' and p['status_ru'] == 'ожидает данных'
    assert p['extrapolation_flag'] is False
    lst = list_promises(str(project))
    assert lst['total'] == 1
    assert lst['promises'][0]['id'] == p['id']


def test_create_validation(project):
    assert _mk(project, horizon_periods=0)['error_code'] == 'BAD_HORIZON'
    assert _mk(project, action_text='  ')['error_code'] == 'EMPTY_ACTION'


def test_check_pending_until_enough_data(project):
    _mk(project)
    r = check_promises(str(project))
    assert r['status'] == 'ok' and r['checked'] == 0
    p = r['promises'][0]
    assert p['status'] == 'pending'
    assert 'Свежих периодов 0 из 4' in p['verdict_note']
    # Пришла часть данных (2 из 4) — всё ещё pending, честный счётчик
    _append_tail(project, [1000.0, 1010.0])
    p = check_promises(str(project))['promises'][0]
    assert p['status'] == 'pending'
    assert 'Свежих периодов 2 из 4' in p['verdict_note']


def test_check_kept_and_missed(project):
    kept = _mk(project)['promise']
    missed = _mk(project, ci_low=100.0, ci_high=200.0,
                 expected_kpi_total=150.0)['promise']
    # 4 свежих периода: сумма 4040 → внутри [3600, 4400], вне [100, 200]
    _append_tail(project, [1000.0, 1010.0, 1015.0, 1015.0])
    r = check_promises(str(project))
    assert r['checked'] == 2
    by_id = {p['id']: p for p in r['promises']}
    k, m = by_id[kept['id']], by_id[missed['id']]
    assert k['status'] == 'kept' and k['status_ru'] == 'сбылось'
    assert k['actual_kpi_total'] == pytest.approx(4040.0)
    assert 'попал в обещанный интервал' in k['verdict_note']
    assert m['status'] == 'missed'
    assert 'не каузальный вывод' in m['verdict_note'], 'честная оговорка обязана быть'


def test_final_verdicts_not_rechecked(project):
    _mk(project)
    _append_tail(project, [1000.0, 1010.0, 1015.0, 1015.0])
    first = check_promises(str(project))['promises'][0]
    assert first['status'] == 'kept'
    checked_at = first['checked_at']
    # Дописали ещё данных — вердикт и checked_at неизменны
    _append_tail(project, [5000.0])
    second = check_promises(str(project))
    assert second['checked'] == 0
    assert second['promises'][0]['status'] == 'kept'
    assert second['promises'][0]['checked_at'] == checked_at


def test_inconclusive_without_ci(project):
    _mk(project, ci_low=None, ci_high=None)
    _append_tail(project, [1000.0, 1010.0, 1015.0, 1015.0])
    p = check_promises(str(project))['promises'][0]
    assert p['status'] == 'inconclusive'
    assert 'неубедительна' in p['verdict_note']


def test_corrupted_json_treated_empty(project):
    (project / 'results').mkdir(exist_ok=True)
    (project / 'results' / 'promises.json').write_text('{битый', encoding='utf-8')
    assert list_promises(str(project))['total'] == 0
    r = _mk(project)
    assert r['status'] == 'ok' and r['total'] == 1


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
