"""E3 (2026-07-03): сравнение поколений модели — движок compare_generations.

Канон: вердикт сдвига по перекрытию CI поколений (Jin 2017), обе стороны
считаются ОДНИМ каноническим decompose-путём (архивная — через additive
model_path), сравнение не имеет побочных эффектов (save_results=False
не трогает results/decomposition.json текущей модели).
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
from engines.model_compare import (  # noqa: E402
    _channel_verdict,
    compare_generations,
    drift_check,
    load_saved_generation_compare,
)


def _retrain_with_new_tail(pdir: Path, extra_periods: int = 6, seed: int = 43) -> None:
    """Дописать свежий хвост в данные и переобучить — «новый квартал» клиента."""
    data_file = pdir / 'data.xlsx'
    df = pd.read_excel(data_file)
    rng = np.random.default_rng(seed)
    tv = np.clip(rng.normal(140, 20, extra_periods), 10, None)      # выше прежнего
    digital = np.clip(rng.normal(180, 40, extra_periods), 20, None)
    sales = 500.0 + 2.5 * tv + 1.2 * digital + rng.normal(0, 30, extra_periods)
    last = pd.to_datetime(df['date'].iloc[-1])
    tail = pd.DataFrame({
        'date': pd.date_range(last, periods=extra_periods + 1, freq='ME')[1:].strftime('%Y-%m-%d'),
        'TV': tv.round(2),
        'Digital': digital.round(2),
        'sales': sales.round(2),
    })
    pd.concat([df, tail], ignore_index=True).to_excel(data_file, index=False)

    from engines.ols_modeler import train_ols
    config = {
        'data_file': str(data_file),
        'kpi_column': 'sales',
        'media_columns': ['TV', 'Digital'],
        'control_columns': [],
        'date_column': 'date',
        'adstock_config': {'TV': 'geometric', 'Digital': 'geometric'},
        'unit_costs': {'TV': 1.0, 'Digital': 1.0},
        'merge_rules': {},
        'kpi_type': 'sales',
    }
    r = train_ols(config, str(pdir))
    assert r.get('status') == 'ok', f'ретрейн упал: {r.get("message")}'


@pytest.fixture(scope='module')
def two_generations(tmp_path_factory):
    """Проект с двумя поколениями: v1 (40 мес) уходит в архив АВТОМАТИЧЕСКИ
    при ретрейне (train_ols версионирует как и bayesian-тренер — подтверждено
    этим же тестом), v2 (46 мес) — текущая."""
    base = tmp_path_factory.mktemp('gen')
    pdir = _make_ols_project(base, 'proj')
    _retrain_with_new_tail(pdir)
    res = compare_generations(str(pdir))
    return pdir, res


# ─── Юнит вердикта ───────────────────────────────────────────────────────────


def test_channel_verdict_rules():
    # CI не пересекаются → резкий сдвиг
    v, m = _channel_verdict(3.0, 5.0, (2.6, 3.4), (4.5, 5.5))
    assert (v, m) == ('shift_strong', 'ci_overlap')
    # Пересекаются, дельта мала → стабильно
    v, m = _channel_verdict(3.2, 3.4, (2.6, 3.9), (2.8, 4.0))
    assert (v, m) == ('stable', 'ci_overlap')
    # Пересекаются, дельта заметна → сдвиг в пределах неопределённости
    v, m = _channel_verdict(3.0, 4.0, (2.0, 4.5), (3.0, 5.0))
    assert (v, m) == ('shift_within_ci', 'ci_overlap')
    # CI нет (вырожденные) → честный point_only
    v, m = _channel_verdict(3.0, 3.1, (0.0, 0.0), (0.0, 0.0))
    assert (v, m) == ('stable', 'point_only')
    v, m = _channel_verdict(3.0, 6.0, (None, None), (None, None))
    assert (v, m) == ('shift_strong', 'point_only')


# ─── Боевой путь на двух поколениях ─────────────────────────────────────────


def test_compare_ok_structure(two_generations):
    _, res = two_generations
    assert res['status'] == 'ok', res
    # Поколение создано АВТО-архивацией ретрейна (train_ols версионирует).
    assert len(res['generations_available']) == 1
    assert res['baseline']['timestamp'] == res['generations_available'][0]
    assert len(res['channels']) == 2
    for c in res['channels']:
        assert c['verdict'] in {'stable', 'shift_within_ci', 'shift_strong'}
        assert c['verdict_ru'] in {'стабильно', 'сдвиг в пределах неопределённости', 'резкий сдвиг'}
        assert c['method'] in {'ci_overlap', 'point_only'}
    s = res['summary']
    assert s['headline'] and 'был' in s['headline'] and 'стал' in s['headline']
    assert sum(s['counts'].values()) == 2
    assert 'Jin' in res['thresholds']['verdict_rule']


def test_canary_verdict_recount(two_generations):
    """Канарейка: вердикт каждого канала пересчитан из CI независимым кодом."""
    _, res = two_generations
    for c in res['channels']:
        v, m = _channel_verdict(
            c['roi_old'], c['roi_new'],
            tuple(c['roi_ci_old']), tuple(c['roi_ci_new']),
        )
        assert v == c['verdict'], f'{c["name"]}: пересчёт {v} vs заявлено {c["verdict"]}'
        assert m == c['method']


def test_no_side_effects_on_current_results(two_generations):
    """save_results=False: сравнение НЕ подменяет results/decomposition.json."""
    pdir, _ = two_generations
    marker_path = pdir / 'results' / 'decomposition.json'
    marker_path.parent.mkdir(exist_ok=True)
    marker = {'sentinel': 'до сравнения'}
    marker_path.write_text(json.dumps(marker), encoding='utf-8')
    res = compare_generations(str(pdir), save=False)
    assert res['status'] == 'ok'
    assert json.loads(marker_path.read_text(encoding='utf-8')) == marker, (
        'Сравнение поколений перетёрло результаты текущей декомпозиции!'
    )


def test_saved_roundtrip_and_determinism(two_generations):
    pdir, res = two_generations
    saved = load_saved_generation_compare(str(pdir))
    assert saved is not None and saved['summary']['headline'] == res['summary']['headline']
    res2 = compare_generations(str(pdir), save=False)
    assert [c['verdict'] for c in res2['channels']] == [c['verdict'] for c in res['channels']]
    assert [c['roi_new'] for c in res2['channels']] == [c['roi_new'] for c in res['channels']]


# ─── Честные отказы ──────────────────────────────────────────────────────────


def test_insufficient_without_history(tmp_path):
    pdir = _make_ols_project(tmp_path, 'nohist')
    res = compare_generations(str(pdir))
    assert res['status'] == 'insufficient'
    assert 'после первого переобучения' in res['message']
    assert load_saved_generation_compare(str(pdir)) is None


def test_generation_not_found(two_generations):
    pdir, res_ok = two_generations
    res = compare_generations(str(pdir), baseline_ts='19990101_000000')
    assert res['status'] == 'error'
    assert res['error_code'] == 'GENERATION_NOT_FOUND'
    assert res_ok['baseline']['timestamp'] in res['message']


def test_no_model_error(tmp_path):
    (tmp_path / 'empty').mkdir()
    res = compare_generations(str(tmp_path / 'empty'))
    assert res['status'] == 'error' and res['error_code'] == 'NO_MODEL'


# ─── E3-2: дрейф-мониторинг ─────────────────────────────────────────────────


def test_drift_check_on_fresh_tail(two_generations):
    """Поколение v1 оценивается на 6 свежих точках, которых не видело:
    структура результата, русский вердикт с действием, наивные бенчмарки."""
    pdir, _ = two_generations
    res = drift_check(str(pdir))
    assert res['status'] == 'ok', res
    assert res['verdict'] in {'fresh_ok', 'retrain_recommended'}
    assert res['n_tail_points'] == 6
    assert res['mape_tail'] > 0
    assert 'naive_last' in res['naive_mape']
    if res['verdict'] == 'retrain_recommended':
        assert 'Пора переобучить' in res['message'] and 'архив' in res['message']
    else:
        assert 'переобучение не требуется' in res['message']
    # Пороги названы явно — никакой скрытой магии
    assert res['thresholds']['retrain_mape_factor'] == 1.5


def test_drift_insufficient_without_history(tmp_path):
    pdir = _make_ols_project(tmp_path, 'drift_nohist')
    res = drift_check(str(pdir))
    assert res['status'] == 'insufficient'
    assert 'после первого переобучения' in res['message']


def test_drift_deterministic(two_generations):
    pdir, _ = two_generations
    a = drift_check(str(pdir))
    b = drift_check(str(pdir))
    assert (a['verdict'], a['mape_tail']) == (b['verdict'], b['mape_tail'])


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
