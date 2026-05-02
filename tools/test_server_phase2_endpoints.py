"""Phase 2.1 Step 4 — server endpoint smoke tests.

Verifies new Phase 2 endpoints (/compute/forecast-context + /compute/
forecast-scaling) are wired correctly + handle missing pickle gracefully.

Full integration tests (real pickle round-trip) require trained MMM —
covered by manual QA in Phase 2.8 ship gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'sidecar' / 'econometrica'))


@pytest.fixture(scope='module')
def client():
    from fastapi.testclient import TestClient
    from server import app
    return TestClient(app)


class TestForecastContextEndpoint:
    def test_missing_pickle_returns_400(self, client, tmp_path):
        empty_project = tmp_path / 'empty_project'
        empty_project.mkdir()
        response = client.post('/compute/forecast-context', json={
            'project_dir': str(empty_project),
        })
        assert response.status_code == 400
        body = response.json()
        assert body['status'] == 'error'
        assert body['error_code'] == 'MODEL_NOT_FOUND'

    def test_invalid_path_returns_400(self, client):
        response = client.post('/compute/forecast-context', json={
            'project_dir': '/nonexistent/path',
        })
        assert response.status_code == 400


class TestForecastScalingEndpoint:
    def test_missing_pickle_returns_400(self, client, tmp_path):
        empty_project = tmp_path / 'empty'
        empty_project.mkdir()
        response = client.post('/compute/forecast-scaling', json={
            'project_dir': str(empty_project),
            'forecast_periods': 52,
        })
        assert response.status_code == 400
        body = response.json()
        assert body['error_code'] == 'MODEL_NOT_FOUND'

    def test_invalid_forecast_periods_with_pickle(self, client, tmp_path):
        """Even with valid pickle, forecast_periods=0 → 400."""
        import pickle
        project = tmp_path / 'project'
        models_dir = project / 'models'
        models_dir.mkdir(parents=True)
        # Minimal pickle stub
        pickle_data = {
            'model_version': '1.3',
            'channel_categories': {},
            'kpi_type': 'sales',
            'kpi_likelihood': 'normal',
            'config': {'data_file': 'irrelevant.csv', 'date_column': 'date'},
            'channel_params': {},
            'normalization': {'media_means': {}, 'y_mean': 0, 'y_std': 1},
            'y_actual': list(range(52)),
        }
        with open(models_dir / 'latest.pkl', 'wb') as f:
            pickle.dump(pickle_data, f)
        response = client.post('/compute/forecast-scaling', json={
            'project_dir': str(project),
            'forecast_periods': 0,
        })
        assert response.status_code == 400
        body = response.json()
        assert body['error_code'] == 'INVALID_FORECAST_PERIODS'

    def test_horizon_too_long_returns_400(self, client, tmp_path):
        """forecast_periods > train_n × 2 (sales cap) → 400."""
        import pickle
        project = tmp_path / 'project2'
        models_dir = project / 'models'
        models_dir.mkdir(parents=True)
        pickle_data = {
            'model_version': '1.3',
            'channel_categories': {},
            'kpi_type': 'sales',  # cap = 2.0×
            'kpi_likelihood': 'normal',
            'config': {'data_file': 'irrelevant.csv', 'date_column': 'date'},
            'channel_params': {},
            'normalization': {'media_means': {}, 'y_mean': 0, 'y_std': 1},
            'y_actual': list(range(52)),  # train_n = 52
        }
        with open(models_dir / 'latest.pkl', 'wb') as f:
            pickle.dump(pickle_data, f)
        response = client.post('/compute/forecast-scaling', json={
            'project_dir': str(project),
            'forecast_periods': 200,  # 200 / 52 ≈ 3.85× → too long
        })
        assert response.status_code == 400
        body = response.json()
        assert body['error_code'] == 'FORECAST_HORIZON_TOO_LONG'

    def test_valid_request_returns_ok_with_metadata(self, client, tmp_path):
        """Valid forecast → 200 with horizon metadata + warnings array."""
        import pickle
        project = tmp_path / 'project3'
        models_dir = project / 'models'
        models_dir.mkdir(parents=True)
        pickle_data = {
            'model_version': '1.3',
            'channel_categories': {},
            'kpi_type': 'sales',
            'kpi_likelihood': 'normal',
            'config': {'data_file': 'irrelevant.csv', 'date_column': 'date',
                       'media_columns': ['TV', 'Search']},
            'channel_params': {
                'TV': {'alpha': 2.0, 'gamma': 0.5, 'beta': 0.05, 'decay': 0.7,
                       'adstock_mean_posterior': 5000.0},
                'Search': {'alpha': 1.8, 'gamma': 0.4, 'beta': 0.04, 'decay': 0.3,
                           'adstock_mean_posterior': 200.0},
            },
            'normalization': {'media_means': {'TV': 5000.0, 'Search': 200.0},
                              'y_mean': 0, 'y_std': 1},
            'y_actual': list(range(156)),  # train_n = 156
        }
        with open(models_dir / 'latest.pkl', 'wb') as f:
            pickle.dump(pickle_data, f)
        response = client.post('/compute/forecast-scaling', json={
            'project_dir': str(project),
            'forecast_periods': 52,  # 1/3× train, OK
        })
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'ok'
        assert body['forecast_n_periods'] == 52
        assert body['train_n_periods'] == 156
        assert 'horizon_ratio' in body
        assert body['horizon_max_multiplier'] == 2.0  # sales default
        assert 'warnings_total' in body


class TestOptimizeRequestPhase2Schema:
    """Verify OptimizeRequest schema accepts Phase 2 fields without breaking existing usage."""

    def test_legacy_request_still_works(self):
        from server import OptimizeRequest
        # Legacy fields only — must instantiate без errors
        req = OptimizeRequest(project_dir='/tmp/test', total_budget=1000000)
        assert req.forecast_periods is None  # default analyst mode
        assert req.forecast_period_label is None

    def test_phase2_fields_accepted(self):
        from server import OptimizeRequest
        req = OptimizeRequest(
            project_dir='/tmp/test',
            total_budget=1000000,
            forecast_periods=52,
            forecast_period_label='Год',
        )
        assert req.forecast_periods == 52
        assert req.forecast_period_label == 'Год'
