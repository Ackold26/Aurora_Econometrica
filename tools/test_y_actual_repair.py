"""Phase 2.7 followup — y_actual truncation repair tests.

Sister to lift formula SSOT — covers backend-side mitigation для legacy pickles.
Reference: `project_econometrica_y_actual_truncation_investigation.md` (2026-05-04).
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd
import pytest

from engines.persistence import (
    _repair_y_actual_against_data_file,
    load_model_with_compat,
)


def _write_data_file(path, n_rows: int, kpi_col: str = 'sales', start: str = '2024-01-01'):
    df = pd.DataFrame({
        'date': pd.date_range(start, periods=n_rows, freq='W'),
        kpi_col: np.linspace(100.0, 200.0, n_rows),
        'TV_TRPs': np.linspace(50.0, 100.0, n_rows),
    })
    if str(path).lower().endswith(('.xlsx', '.xls')):
        df.to_excel(path, index=False)
    else:
        df.to_csv(path, index=False)
    return df


def _make_legacy_pickle(tmp_path, *, y_actual: list[float], data_file: str | None,
                        kpi_col: str = 'sales') -> tuple:
    """Build minimal legacy-style pickle. Returns (model_data, pickle_path)."""
    model_data = {
        'model_version': '1.0-ols',
        'config': {
            'data_file': data_file,
            'kpi_column': kpi_col,
            'media_columns': ['TV_TRPs'],
            'control_columns': [],
        },
        'normalization': {'y_mean': 150.0, 'y_std': 25.0, 'media_means': {'TV_TRPs': 75.0},
                          'control_means': {}, 'control_stds': {}, 'intercept_mean': 0.0,
                          'control_betas_mean': [], 'untrained_channels': []},
        'channel_params': {'TV_TRPs': {'beta': 0.5, 'alpha': 1.5, 'gamma': 0.5, 'decay': 0.5}},
        'channel_categories': {},
        'y_actual': list(y_actual),
        'y_predicted': list(y_actual),
        'causal_artifact_path': None,
    }
    pkl_path = tmp_path / 'latest.pkl'
    with open(pkl_path, 'wb') as f:
        pickle.dump(model_data, f)
    return model_data, pkl_path


def test_y_actual_repair_truncated_pickle_xlsx(tmp_path):
    """Legacy pickle с truncated y_actual (52) + data_file (156 rows) → repair к 156."""
    data_file = tmp_path / 'kagocel.xlsx'
    _write_data_file(data_file, n_rows=156)
    truncated = np.linspace(100.0, 200.0, 52).tolist()
    _, pkl_path = _make_legacy_pickle(tmp_path, y_actual=truncated, data_file=str(data_file))

    loaded = load_model_with_compat(pkl_path)

    assert len(loaded['y_actual']) == 156, (
        f"Expected y_actual repaired к 156 (full), got {len(loaded['y_actual'])}"
    )
    # First value should match data_file row 0 (linspace(100, 200, 156)[0] == 100.0)
    assert loaded['y_actual'][0] == pytest.approx(100.0)
    assert loaded['y_actual'][-1] == pytest.approx(200.0)


def test_y_actual_repair_truncated_pickle_csv(tmp_path):
    """CSV data_file branch — same logic."""
    data_file = tmp_path / 'project.csv'
    _write_data_file(data_file, n_rows=104, kpi_col='sales')
    truncated = np.linspace(100.0, 200.0, 30).tolist()
    _, pkl_path = _make_legacy_pickle(tmp_path, y_actual=truncated, data_file=str(data_file))

    loaded = load_model_with_compat(pkl_path)
    assert len(loaded['y_actual']) == 104


def test_y_actual_no_repair_when_already_full(tmp_path):
    """Current pickle с правильной длиной — no-op (idempotent)."""
    n = 100
    data_file = tmp_path / 'current.xlsx'
    _write_data_file(data_file, n_rows=n)
    full = np.linspace(100.0, 200.0, n).tolist()
    _, pkl_path = _make_legacy_pickle(tmp_path, y_actual=full, data_file=str(data_file))

    loaded = load_model_with_compat(pkl_path)
    assert len(loaded['y_actual']) == n
    # Idempotent: repeat helper run на repaired model_data — no change.
    _repair_y_actual_against_data_file(loaded)
    assert len(loaded['y_actual']) == n


def test_y_actual_no_repair_when_data_file_missing(tmp_path):
    """data_file deleted/moved → preserve pickle as canonical training-time state."""
    nonexistent = str(tmp_path / 'gone.xlsx')
    _, pkl_path = _make_legacy_pickle(
        tmp_path, y_actual=[1.0, 2.0, 3.0], data_file=nonexistent,
    )
    loaded = load_model_with_compat(pkl_path)
    assert loaded['y_actual'] == [1.0, 2.0, 3.0]


def test_y_actual_no_repair_when_data_file_shorter(tmp_path):
    """User trimmed data_file post-training → preserve pickle (canonical training snapshot)."""
    data_file = tmp_path / 'trimmed.xlsx'
    _write_data_file(data_file, n_rows=50)
    long_y = list(range(100))
    _, pkl_path = _make_legacy_pickle(tmp_path, y_actual=long_y, data_file=str(data_file))

    loaded = load_model_with_compat(pkl_path)
    assert len(loaded['y_actual']) == 100  # preserved


def test_y_actual_no_repair_when_kpi_column_missing(tmp_path):
    """KPI column renamed/dropped in data_file → preserve pickle."""
    data_file = tmp_path / 'renamed.xlsx'
    df = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=100, freq='W'),
        'revenue': np.arange(100, dtype=float),  # 'sales' missing
        'TV_TRPs': np.arange(100, dtype=float),
    })
    df.to_excel(data_file, index=False)

    _, pkl_path = _make_legacy_pickle(
        tmp_path, y_actual=[1.0, 2.0, 3.0],
        data_file=str(data_file), kpi_col='sales',
    )

    loaded = load_model_with_compat(pkl_path)
    assert loaded['y_actual'] == [1.0, 2.0, 3.0]


def test_y_actual_no_repair_when_data_file_unreadable(tmp_path):
    """Corrupt data_file → graceful skip без crash."""
    data_file = tmp_path / 'corrupt.xlsx'
    data_file.write_bytes(b'not a real xlsx')
    _, pkl_path = _make_legacy_pickle(
        tmp_path, y_actual=[10.0, 20.0, 30.0], data_file=str(data_file),
    )
    loaded = load_model_with_compat(pkl_path)
    assert loaded['y_actual'] == [10.0, 20.0, 30.0]


def test_y_actual_no_repair_when_data_file_field_missing(tmp_path):
    """Config sans data_file → no-op (legacy pickle pre-data_file field)."""
    model_data = {
        'model_version': '1.0',
        'config': {
            'kpi_column': 'sales',
            'media_columns': ['TV_TRPs'],
            'control_columns': [],
        },
        'normalization': {'y_mean': 0.0, 'y_std': 1.0},
        'channel_params': {},
        'y_actual': [5.0, 10.0, 15.0],
        'y_predicted': [5.0, 10.0, 15.0],
    }
    _repair_y_actual_against_data_file(model_data)
    assert model_data['y_actual'] == [5.0, 10.0, 15.0]


def test_y_actual_no_repair_when_empty(tmp_path):
    """Empty y_actual → no-op (different bug, не Phase 2.7 scope)."""
    model_data = {
        'config': {'data_file': str(tmp_path / 'x.xlsx'), 'kpi_column': 'sales'},
        'y_actual': [],
    }
    _repair_y_actual_against_data_file(model_data)
    assert model_data['y_actual'] == []


def test_y_actual_repair_idempotent(tmp_path):
    """Multiple helper invocations on same model_data → only first repairs, rest no-op."""
    data_file = tmp_path / 'kagocel.xlsx'
    _write_data_file(data_file, n_rows=156)
    truncated = np.linspace(100.0, 200.0, 52).tolist()
    model_data, _ = _make_legacy_pickle(
        tmp_path, y_actual=truncated, data_file=str(data_file),
    )

    _repair_y_actual_against_data_file(model_data)
    first_pass_y = list(model_data['y_actual'])
    assert len(first_pass_y) == 156

    _repair_y_actual_against_data_file(model_data)  # second call
    assert model_data['y_actual'] == first_pass_y  # unchanged


def test_y_actual_repair_alternate_kpi_field_name(tmp_path):
    """Config field `kpi_col` (legacy) recognized в дополнение к `kpi_column`."""
    data_file = tmp_path / 'legacy_field.xlsx'
    _write_data_file(data_file, n_rows=100, kpi_col='sales')
    model_data = {
        'model_version': '1.0',
        'config': {
            'data_file': str(data_file),
            'kpi_col': 'sales',  # legacy field name
            'media_columns': [],
            'control_columns': [],
        },
        'normalization': {'y_mean': 150.0, 'y_std': 25.0},
        'channel_params': {},
        'y_actual': [100.0, 110.0, 120.0],  # truncated to 3
        'y_predicted': [100.0, 110.0, 120.0],
    }
    _repair_y_actual_against_data_file(model_data)
    assert len(model_data['y_actual']) == 100


def test_y_actual_repair_skips_when_data_file_has_nan(tmp_path):
    """data_file KPI col contains NaN → preserve pickle (audit fix 2026-05-24).

    Repairing с NaN values would silently corrupt y_actual + downstream variance.
    Pickle's y_actual was validated finite at training time → canonical training
    snapshot more reliable than partially-corrupt data_file.
    """
    data_file = tmp_path / 'with_nan.xlsx'
    df = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=100, freq='W'),
        'sales': [np.nan if i % 10 == 0 else float(i) for i in range(100)],
        'TV_TRPs': np.arange(100, dtype=float),
    })
    df.to_excel(data_file, index=False)
    pickle_y = [1.0, 2.0, 3.0]  # truncated, len < 100
    _, pkl_path = _make_legacy_pickle(
        tmp_path, y_actual=pickle_y, data_file=str(data_file),
    )
    loaded = load_model_with_compat(pkl_path)
    assert loaded['y_actual'] == pickle_y  # preserved (NaN check kicked in)


def test_y_actual_repair_direct_call_data_file_missing():
    """Direct helper call с missing data_file → no-op без crash.

    Sister к test_y_actual_no_repair_when_data_file_missing (которая идёт через
    load_model_with_compat). Audit fix 2026-05-24: separate path coverage —
    direct call минует lazy_migrate_to_safe interaction что могла маскировать
    repair guard.
    """
    model_data = {
        'config': {
            'data_file': '/nonexistent/path/to/file.xlsx',
            'kpi_column': 'sales',
        },
        'y_actual': [1.0, 2.0, 3.0],
    }
    _repair_y_actual_against_data_file(model_data)
    assert model_data['y_actual'] == [1.0, 2.0, 3.0]


def test_y_actual_repair_handles_numpy_array_y_actual(tmp_path):
    """Legacy pickle с y_actual как numpy.ndarray — guard survives без ValueError.

    Audit fix 2026-05-24: `not y_actual` raised ValueError на np.ndarray (truth
    value ambiguous). Now explicit `len()` check works для list/ndarray/tuple.
    """
    data_file = tmp_path / 'arr.xlsx'
    _write_data_file(data_file, n_rows=156)
    np_y = np.linspace(100.0, 200.0, 52)  # numpy array truncated к 52
    model_data = {
        'config': {
            'data_file': str(data_file),
            'kpi_column': 'sales',
        },
        'y_actual': np_y,
    }
    _repair_y_actual_against_data_file(model_data)
    assert len(model_data['y_actual']) == 156  # repaired


def test_y_actual_repair_handles_empty_numpy_array(tmp_path):
    """Empty numpy array → no-op без ValueError (len-based guard)."""
    model_data = {
        'config': {'data_file': str(tmp_path / 'x.xlsx'), 'kpi_column': 'sales'},
        'y_actual': np.array([]),
    }
    _repair_y_actual_against_data_file(model_data)
    assert len(model_data['y_actual']) == 0


def test_y_actual_repair_handles_tuple_y_actual(tmp_path):
    """Tuple y_actual (theoretical legacy) — guard works."""
    data_file = tmp_path / 'tup.xlsx'
    _write_data_file(data_file, n_rows=50)
    tup_y = (1.0, 2.0, 3.0)
    model_data = {
        'config': {'data_file': str(data_file), 'kpi_column': 'sales'},
        'y_actual': tup_y,
    }
    _repair_y_actual_against_data_file(model_data)
    assert len(model_data['y_actual']) == 50


# ─────────────────────────────────────────────────────────────────────────
# Sprint Buffer #43 — observable counter tests (INV-27)
# ─────────────────────────────────────────────────────────────────────────

from engines.persistence import get_repair_stats, reset_repair_stats


def test_repair_counter_repaired_increments(tmp_path):
    """Successful repair → counter 'repaired' incremented."""
    reset_repair_stats()
    data_file = tmp_path / 'data.csv'
    _write_data_file(data_file, n_rows=156)
    model_data = {
        'config': {'data_file': str(data_file), 'kpi_column': 'sales'},
        'y_actual': [1.0] * 52,
    }
    _repair_y_actual_against_data_file(model_data)
    stats = get_repair_stats()
    assert stats['repaired'] == 1
    assert sum(v for k, v in stats.items() if k != 'repaired') == 0


def test_repair_counter_skipped_current(tmp_path):
    """Pickle length == data_file rows → 'skipped_current' incremented."""
    reset_repair_stats()
    data_file = tmp_path / 'data.csv'
    _write_data_file(data_file, n_rows=52)
    model_data = {
        'config': {'data_file': str(data_file), 'kpi_column': 'sales'},
        'y_actual': [1.0] * 52,
    }
    _repair_y_actual_against_data_file(model_data)
    assert get_repair_stats()['skipped_current'] == 1


def test_repair_counter_skipped_missing_meta():
    """data_file отсутствует в config → 'skipped_missing_meta'."""
    reset_repair_stats()
    model_data = {'config': {}, 'y_actual': [1.0] * 10}
    _repair_y_actual_against_data_file(model_data)
    assert get_repair_stats()['skipped_missing_meta'] == 1


def test_repair_counter_skipped_file_gone(tmp_path):
    """data_file path не существует → 'skipped_file_gone'."""
    reset_repair_stats()
    model_data = {
        'config': {'data_file': str(tmp_path / 'nonexistent.csv'), 'kpi_column': 'sales'},
        'y_actual': [1.0] * 10,
    }
    _repair_y_actual_against_data_file(model_data)
    assert get_repair_stats()['skipped_file_gone'] == 1


def test_repair_counter_skipped_col_missing(tmp_path):
    """kpi_column отсутствует в data_file → 'skipped_col_missing'."""
    reset_repair_stats()
    data_file = tmp_path / 'data.csv'
    _write_data_file(data_file, n_rows=50, kpi_col='other_col')
    model_data = {
        'config': {'data_file': str(data_file), 'kpi_column': 'sales'},
        'y_actual': [1.0] * 10,
    }
    _repair_y_actual_against_data_file(model_data)
    assert get_repair_stats()['skipped_col_missing'] == 1


def test_repair_counter_skipped_nan_values(tmp_path):
    """NaN в data_file KPI col → 'skipped_nan_values'."""
    reset_repair_stats()
    data_file = tmp_path / 'data.csv'
    df = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=156, freq='W'),
        'sales': [np.nan if i == 50 else float(i) for i in range(156)],
    })
    df.to_csv(data_file, index=False)
    model_data = {
        'config': {'data_file': str(data_file), 'kpi_column': 'sales'},
        'y_actual': [1.0] * 52,
    }
    _repair_y_actual_against_data_file(model_data)
    assert get_repair_stats()['skipped_nan_values'] == 1


def test_repair_counter_skipped_shorter_file(tmp_path):
    """data_file < pickle → 'skipped_shorter_file'."""
    reset_repair_stats()
    data_file = tmp_path / 'data.csv'
    _write_data_file(data_file, n_rows=30)
    model_data = {
        'config': {'data_file': str(data_file), 'kpi_column': 'sales'},
        'y_actual': [1.0] * 52,
    }
    _repair_y_actual_against_data_file(model_data)
    assert get_repair_stats()['skipped_shorter_file'] == 1


def test_repair_counter_skipped_empty_pickle():
    """y_actual length 0 → 'skipped_empty_pickle'."""
    reset_repair_stats()
    model_data = {'config': {'data_file': '/x', 'kpi_column': 'sales'}, 'y_actual': []}
    _repair_y_actual_against_data_file(model_data)
    assert get_repair_stats()['skipped_empty_pickle'] == 1


def test_repair_counter_skipped_unsized():
    """Scalar y_actual → 'skipped_unsized' (TypeError on len())."""
    reset_repair_stats()
    model_data = {'config': {'data_file': '/x', 'kpi_column': 'sales'}, 'y_actual': 42}
    _repair_y_actual_against_data_file(model_data)
    assert get_repair_stats()['skipped_unsized'] == 1


def test_repair_counter_independence(tmp_path):
    """Counters не пересекаются — 3 consecutive разных pathways → 3 distinct increments."""
    reset_repair_stats()
    # Path 1: skipped_missing_meta
    _repair_y_actual_against_data_file({'config': {}, 'y_actual': [1.0]})
    # Path 2: skipped_empty_pickle
    _repair_y_actual_against_data_file({'config': {'data_file': '/x', 'kpi_column': 's'},
                                         'y_actual': []})
    # Path 3: repaired
    data_file = tmp_path / 'data.csv'
    _write_data_file(data_file, n_rows=100)
    md3 = {'config': {'data_file': str(data_file), 'kpi_column': 'sales'},
           'y_actual': [1.0] * 30}
    _repair_y_actual_against_data_file(md3)
    stats = get_repair_stats()
    assert stats['skipped_missing_meta'] == 1
    assert stats['skipped_empty_pickle'] == 1
    assert stats['repaired'] == 1
    assert stats['skipped_current'] == 0


def test_reset_repair_stats_zeros_all():
    """reset_repair_stats() обнуляет ВСЕ ключи."""
    reset_repair_stats()
    _repair_y_actual_against_data_file({'config': {}, 'y_actual': [1.0]})
    assert get_repair_stats()['skipped_missing_meta'] == 1
    reset_repair_stats()
    stats = get_repair_stats()
    assert all(v == 0 for v in stats.values())


def test_repair_stats_snapshot_isolation():
    """get_repair_stats() returns снимок, не reference — mutation не влияет."""
    reset_repair_stats()
    _repair_y_actual_against_data_file({'config': {}, 'y_actual': [1.0]})
    snap = get_repair_stats()
    snap['skipped_missing_meta'] = 999
    # Original counter не задет
    assert get_repair_stats()['skipped_missing_meta'] == 1
