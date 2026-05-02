"""Phase 2.1 Step 3 — persistence migration helpers (G2 plan gap).

Tests pickle backward compat + at-load-time inference helpers для legacy
pre-Phase-2 pickles (v1.3 = current ship lacks training_granularity,
train_x_norm_quantiles, seasonality_detected).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'sidecar' / 'econometrica'))


class TestLoadModelWithCompatPhase2Defaults:
    """v2.0 pickle without Phase 2 fields → setdefault() injects None."""

    def test_phase2_fields_default_none(self, tmp_path):
        import pickle
        legacy_pickle = {
            'model_version': '1.3',
            'channel_categories': {},
            'kpi_type': 'sales',
            'kpi_likelihood': 'normal',
            'config': {'data_file': 'nonexistent.csv', 'date_column': 'date'},
            'channel_params': {},
            'normalization': {'media_means': {}, 'y_mean': 0, 'y_std': 1},
        }
        path = tmp_path / 'legacy.pkl'
        with open(path, 'wb') as f:
            pickle.dump(legacy_pickle, f)

        from engines.persistence import load_model_with_compat
        loaded = load_model_with_compat(path)
        assert loaded['training_granularity'] is None
        assert loaded['train_x_norm_quantiles'] is None
        assert loaded['seasonality_detected'] is None


class TestInferGranularityAtLoad:
    def test_returns_none_when_data_file_missing(self):
        from engines.persistence import infer_granularity_at_load
        model_data = {'config': {'data_file': '/nonexistent/path.csv'}}
        assert infer_granularity_at_load(model_data) is None

    def test_returns_none_when_no_data_file_key(self):
        from engines.persistence import infer_granularity_at_load
        assert infer_granularity_at_load({'config': {}}) is None
        assert infer_granularity_at_load({}) is None

    def test_infers_weekly_from_real_csv(self, tmp_path):
        import pandas as pd
        from engines.persistence import infer_granularity_at_load
        df = pd.DataFrame({
            'date': pd.date_range('2023-01-01', periods=52, freq='W'),
            'TV': np.random.randint(1000, 5000, 52),
            'sales': np.random.randint(50, 100, 52),
        })
        csv_path = tmp_path / 'training.csv'
        df.to_csv(csv_path, index=False)
        model_data = {'config': {'data_file': str(csv_path), 'date_column': 'date'}}
        result = infer_granularity_at_load(model_data)
        assert result == 'W'


class TestGetTrainingGranularityPersistedFirst:
    def test_persisted_value_used_when_present(self):
        from engines.persistence import get_training_granularity
        model_data = {
            'training_granularity': 'M',
            'config': {'data_file': '/nonexistent.csv'},  # would fail если fallback
        }
        assert get_training_granularity(model_data) == 'M'

    def test_falls_back_to_inference(self):
        from engines.persistence import get_training_granularity
        # No persisted, no data file → None
        assert get_training_granularity({}) is None


class TestInferSeasonalityAtLoad:
    def test_returns_none_when_no_y_actual(self):
        from engines.persistence import infer_seasonality_at_load
        assert infer_seasonality_at_load({}) is None
        assert infer_seasonality_at_load({'diagnostics': {}}) is None

    def test_detects_yearly_pattern(self):
        from engines.persistence import infer_seasonality_at_load
        t = np.arange(156)
        y = (100 + 30 * np.sin(2 * np.pi * t / 52)).tolist()
        model_data = {
            'diagnostics': {'actual_vs_predicted': {'actual': y}},
            'training_granularity': 'W',
        }
        result = infer_seasonality_at_load(model_data)
        assert result is not None
        assert result['period'] == 52


class TestGetSeasonalityPersistedFirst:
    def test_persisted_value_used(self):
        from engines.persistence import get_seasonality
        persisted = {'period': 13, 'autocorr': 0.7}
        model_data = {'seasonality_detected': persisted}
        assert get_seasonality(model_data) is persisted


class TestInferXNormQuantilesAtLoad:
    def test_returns_none_when_no_data_file(self):
        from engines.persistence import infer_x_norm_quantiles_at_load
        model_data = {'config': {}, 'channel_params': {'A': {'decay': 0.5}}}
        assert infer_x_norm_quantiles_at_load(model_data) is None

    def test_returns_none_when_no_channel_params(self):
        from engines.persistence import infer_x_norm_quantiles_at_load
        model_data = {'config': {'data_file': 'irrelevant.csv'}}
        assert infer_x_norm_quantiles_at_load(model_data) is None

    def test_computes_from_real_data(self, tmp_path):
        import pandas as pd
        from engines.persistence import infer_x_norm_quantiles_at_load

        np.random.seed(0)
        df = pd.DataFrame({
            'date': pd.date_range('2023-01-01', periods=52, freq='W'),
            'TV': np.random.randint(1000, 5000, 52).astype(float),
            'sales': np.random.randint(50, 100, 52).astype(float),
        })
        csv_path = tmp_path / 'data.csv'
        df.to_csv(csv_path, index=False)

        model_data = {
            'config': {'data_file': str(csv_path), 'date_column': 'date'},
            'channel_params': {
                'TV': {'decay': 0.5, 'adstock_mean_posterior': 5000.0,
                       'alpha': 2.0, 'gamma': 0.5, 'beta': 0.05},
            },
            'normalization': {'media_means': {'TV': 5000.0}},
            'channel_adstock_types': {'TV': 'geometric'},
        }
        result = infer_x_norm_quantiles_at_load(model_data)
        assert result is not None
        assert 'TV' in result
        assert all(k in result['TV'] for k in ('p50', 'p75', 'p90', 'p95', 'p99'))
        assert 0 < result['TV']['p50'] < result['TV']['p99']


class TestGetXNormQuantilesPersistedFirst:
    def test_persisted_per_channel_lookup(self):
        from engines.persistence import get_x_norm_quantiles
        persisted = {'TV': {'p50': 0.5, 'p75': 0.7, 'p90': 0.9, 'p95': 1.0, 'p99': 1.5}}
        model_data = {'train_x_norm_quantiles': persisted}
        result = get_x_norm_quantiles(model_data, 'TV')
        assert result == persisted['TV']

    def test_returns_none_for_missing_channel(self):
        from engines.persistence import get_x_norm_quantiles
        # No persisted, no fallback → None
        result = get_x_norm_quantiles({}, 'NonExistent')
        assert result is None
