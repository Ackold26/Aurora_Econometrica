"""Scenario extrapolation marker — характеризующие тесты мат-аудита 2026-07-02 (F-04).

Машинерия экстраполяции существовала (extrapolation_severity, endpoint
/compute/forecast-scaling), но пользователь сценариев её не видел: endpoint
не подключён к UI, а движок predict_scenario план не помечал. Теперь сценарий
сам возвращает result['extrapolation'] = {'severity': 0..3, 'channels': [...]}
— пиковый per-period план канала против p95/p99 наблюдавшихся трат
(Chan & Perry 2017 Fig. 2: кривая отклика вне наблюдённого диапазона не
идентифицируется данными).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_goalseek_honesty import _build_project  # noqa: E402 — соседний тест-модуль

from engines.scenario import predict_scenario  # noqa: E402


def _flat_plan(project_dir: Path, factor: float, n_periods: int = 36) -> dict:
    """Ровный план: factor × среднее наблюдавшееся по каждому каналу."""
    df = pd.read_csv(project_dir / 'data.csv')
    media_cols = [c for c in df.columns if c not in ('date', 'sales')]
    return {c: [float(df[c].mean()) * factor] * n_periods for c in media_cols}


def test_F04_scenario_marks_extrapolation_beyond_history(tmp_path):
    """План ×3 от среднего (заведомо выше p99 истории) → severity ≥ 2 + каналы."""
    pdir = _build_project(tmp_path, 'sc_extra', beta_sd=0.1)
    res = predict_scenario(
        {'scenario_name': 'aggressive', 'media_plan': _flat_plan(pdir, 3.0)},
        str(pdir),
    )
    assert res['status'] == 'ok', res.get('message')
    ex = res.get('extrapolation')
    assert ex is not None, 'Маркер экстраполяции отсутствует в сценарии (регрессия F-04)'
    assert ex['severity'] >= 2, f'План ×3 должен дать severity>=2, получено {ex}'
    assert ex['channels'], 'Каналы за диапазоном не перечислены'
    ch = ex['channels'][0]
    assert {'name', 'peak_per_period_native', 'hist_max_native', 'ratio_vs_max', 'severity'} <= set(ch)


def test_F04_scenario_silent_within_history(tmp_path):
    """Скромный план (×0.5 от среднего — внутри истории) → severity == 0."""
    pdir = _build_project(tmp_path, 'sc_inzone', beta_sd=0.1)
    res = predict_scenario(
        {'scenario_name': 'modest', 'media_plan': _flat_plan(pdir, 0.5)},
        str(pdir),
    )
    assert res['status'] == 'ok', res.get('message')
    ex = res.get('extrapolation')
    assert ex is not None
    assert ex['severity'] == 0, f'Ложная тревога экстраполяции на скромном плане: {ex}'
    assert ex['channels'] == []


def test_F04_graceful_none_when_history_unavailable(tmp_path):
    """История недоступна (data_file удалён) → extrapolation=None, сценарий жив."""
    pdir = _build_project(tmp_path, 'sc_nodata', beta_sd=0.1)
    plan = _flat_plan(pdir, 2.0)
    (pdir / 'data.csv').unlink()
    res = predict_scenario(
        {'scenario_name': 'nodata', 'media_plan': plan},
        str(pdir),
    )
    assert res['status'] == 'ok', res.get('message')
    assert res.get('extrapolation') is None


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
