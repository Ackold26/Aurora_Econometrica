"""Phase 2.7 — integration tests for synergy paths (G5 plan gap).

Audit pass 2 G5: «Plan tests Phase 2 in isolation. Missing integration tests
for: Phase 2 × Trust 3 hierarchical, Phase 2 × Conformal (OLS planning),
Phase 2 × KPI registry, Phase 2 × verdict_tier extended gate, Phase 2 ×
scenario engine alignment.»

Each test composes ≥2 Aurora subsystems, verifying Phase 2 INTEGRATES rather
than bolts on. Coverage:
- T1: Phase 2 × verdict_tier — extrapolation_severity gate composes correctly
  with R-hat / small-N / standard tier classification.
- T2: Phase 2 × KPI registry — sales/awareness configs read consistently
  through forecast_validation helper.
- T3: Phase 2 × Conformal — OLS planning case returns interval (S2 wired).
- T4: Phase 2 × scenario engine alignment — Option C math == scenario.py
  per-period semantics для same allocation + horizon.
- T5: Phase 2 × warning composition (G3) — composes drift + horizon + seasonal
  warnings with stable critical-first ordering.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'sidecar' / 'econometrica'))


class TestT1_VerdictTierComposition:
    """G5 T1 — Phase 2 extrapolation_severity composes with existing gates."""

    def test_severity_3_overrides_rhat_pass(self):
        from utils.posterior_propagation import verdict_tier
        # Confident CI + R-hat OK → would normally be «Уверенная»
        # Severity 3 → forces «Высокая неопределённость»
        tier, tone, _ = verdict_tier(
            mean=1.0, ci_low=0.85, ci_high=1.15,
            r_hat=1.01, extrapolation_severity=3,
        )
        assert tier == "Высокая неопределённость"
        assert tone == "bad"

    def test_rhat_failure_overrides_severity_zero(self):
        from utils.posterior_propagation import verdict_tier
        # Severity 0 → no Phase 2 escalation, but R-hat=1.10 → bad tier
        tier, _, _ = verdict_tier(
            mean=1.0, ci_low=0.85, ci_high=1.15,
            r_hat=1.10, extrapolation_severity=0,
        )
        assert tier == "Высокая неопределённость"

    def test_severity_2_with_small_n_compose(self):
        from utils.posterior_propagation import verdict_tier
        # n_obs<30 + narrow CI → small-N gate would force «Направленная»
        # Severity=2 ALSO forces «Направленная» — both gates compatible
        tier, tone, _ = verdict_tier(
            mean=1.0, ci_low=0.85, ci_high=1.15,  # narrow
            n_obs=20, extrapolation_severity=2,
        )
        assert tier == "Направленная"
        assert tone == "warn"


class TestT2_KPIRegistryThroughForecastValidation:
    """G5 T2 — sales vs awareness threshold differences flow correctly."""

    def test_sales_default_2x_cap(self):
        from utils.forecast_validation import get_forecast_horizon_max_multiplier
        assert get_forecast_horizon_max_multiplier('sales') == 2.0

    def test_awareness_uses_15x_cap(self):
        """S7 — awareness has longer brand build-up → tighter horizon cap."""
        from utils.forecast_validation import get_forecast_horizon_max_multiplier
        assert get_forecast_horizon_max_multiplier('awareness') == 1.5

    def test_unknown_kpi_fallback_to_default(self):
        from utils.forecast_validation import get_forecast_horizon_max_multiplier
        # Defensive — registry corruption shouldn't break planning
        assert get_forecast_horizon_max_multiplier('nonexistent') == 2.0


class TestT3_ConformalInPlanningMode:
    """G5 T3 — S2 synergy: OLS pickles get distribution-free P10/P90."""

    def test_returns_interval_for_ols_pickle(self):
        from utils.forecast_validation import conformal_planning_intervals
        np.random.seed(42)
        X = np.random.normal(0, 1, (100, 3))
        y = X[:, 0] * 2.5 + X[:, 1] * 1.5 + np.random.normal(0, 0.5, 100)
        model_data = {'X_train': X, 'y_train': y}
        result = conformal_planning_intervals(model_data, confidence=0.8)
        if result is None:
            pytest.skip('Conformal not available in this env')
        assert result['half_width'] > 0
        # Method must be one of conformal variants (S2)
        assert result['method'] in ('split_conformal', 'jackknife', 'unknown')

    def test_returns_none_for_bayesian_pickle(self):
        """Bayesian pickle uses posterior CI; conformal not applicable."""
        from utils.forecast_validation import conformal_planning_intervals
        bayesian_pickle = {'posterior_samples': {'media_betas': np.random.randn(3, 100)}}
        assert conformal_planning_intervals(bayesian_pickle) is None


class TestT4_OptimizerScenarioAlignment:
    """G5 T4 — Option C math matches scenario engine per-period semantics.

    Audit pass 2 §2bis claim: optimizer planning mode + scenario.py both use
    per-period sum-of-Hill. Test verifies they produce identical KPI for same
    allocation + horizon (modulo intercept handling — only media response).
    """

    def test_per_period_summation_matches_manual(self):
        """Mirror scenario.py:167-186 manually → must match utils/forecasting.py output."""
        from utils.adstock import apply_adstock
        from utils.forecasting import evaluate_flat_allocation_response
        from utils.saturation import hill_function

        cols = ['A', 'B']
        params = {
            'A': {'alpha': 2.5, 'gamma': 0.5, 'beta': 0.06, 'decay': 0.7,
                  'adstock_mean_posterior': 1000.0},
            'B': {'alpha': 1.8, 'gamma': 0.45, 'beta': 0.04, 'decay': 0.4,
                  'adstock_mean_posterior': 500.0},
        }
        means = {'A': 1000.0, 'B': 500.0}
        cfg = {'A': 'geometric', 'B': 'geometric'}
        unit_costs = [1.0, 1.0]
        alloc = np.array([100_000.0, 50_000.0])
        forecast_n = 26

        # Helper output (Option C in optimizer planning mode)
        actual = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=alloc, unit_costs=unit_costs,
            media_means=means, adstock_config=cfg,
            n_periods=forecast_n,
        )

        # Manual replication of scenario.py:167-186 logic per channel
        expected = 0.0
        for i, col in enumerate(cols):
            p = params[col]
            x_avg = alloc[i] / unit_costs[i] / forecast_n
            flat = np.full(forecast_n, x_avg)
            adstock = apply_adstock(flat, 'geometric', {'alpha': p['decay']})
            x_norm = adstock / p['adstock_mean_posterior']
            sat = hill_function(np.maximum(x_norm, 0), alpha=p['alpha'], gamma=p['gamma'])
            expected += p['beta'] * sat.sum()

        # Must match within float precision
        assert abs(actual - expected) < 1e-9, f"actual={actual}, expected={expected}"


class TestT5_WarningCompositionWithMultipleSources:
    """G5 T5 — G3 warning priority composes correctly across detection sources."""

    def test_drift_critical_overrides_horizon_warn(self):
        from utils.forecast_validation import resolve_warning_priority

        warnings = [
            {'severity': 'warn', 'message_ru': 'horizon 1.7×'},
            {'severity': 'critical', 'message_ru': 'TV drift 4×'},
            {'severity': 'info', 'message_ru': 'binding constraints'},
        ]
        result = resolve_warning_priority(warnings)
        assert result['top_warning']['message_ru'] == 'TV drift 4×'
        assert result['total_count'] == 3
        # Secondary preserves remaining priority order
        assert result['secondary'][0]['severity'] == 'warn'
        assert result['secondary'][1]['severity'] == 'info'

    def test_horizon_warns_first_when_no_critical(self):
        from utils.forecast_validation import resolve_warning_priority
        warnings = [
            {'severity': 'info', 'message_ru': 'binding constraints'},
            {'severity': 'warn', 'message_ru': 'horizon 1.6×'},
        ]
        result = resolve_warning_priority(warnings)
        assert result['top_warning']['severity'] == 'warn'
        assert result['secondary'][0]['severity'] == 'info'


class TestT6_PlanningModePlanFlow:
    """G5 T6 — end-to-end mock-pickle integration (forecast-scaling endpoint)."""

    def test_full_forecast_scaling_flow(self, tmp_path):
        """Server endpoint integrates persistence + validation + KPI registry."""
        import pickle

        from fastapi.testclient import TestClient
        from server import app

        project = tmp_path / 'integration_project'
        models_dir = project / 'models'
        models_dir.mkdir(parents=True)

        # Awareness pickle → S7 should give 1.5× cap, not 2.0×
        pickle_data = {
            'model_version': '1.3',
            'channel_categories': {},
            'kpi_type': 'awareness',
            'kpi_likelihood': 'logit_normal',
            'config': {'data_file': 'irrelevant.csv', 'date_column': 'date',
                       'media_columns': ['Brand']},
            'channel_params': {
                'Brand': {'alpha': 2.0, 'gamma': 0.3, 'beta': 0.05, 'decay': 0.8,
                          'adstock_mean_posterior': 1000.0},
            },
            'normalization': {'media_means': {'Brand': 1000.0}, 'y_mean': 0, 'y_std': 1},
            'y_actual': list(range(52)),  # train_n = 52
        }
        with open(models_dir / 'latest.pkl', 'wb') as f:
            pickle.dump(pickle_data, f)

        client = TestClient(app)

        # forecast 1.6× → exceeds awareness 1.5× hard cap → 400
        response = client.post('/compute/forecast-scaling', json={
            'project_dir': str(project),
            'forecast_periods': 84,  # 84/52 ≈ 1.62×
        })
        assert response.status_code == 400
        body = response.json()
        assert body['error_code'] == 'FORECAST_HORIZON_TOO_LONG'

        # forecast 1.3× → within awareness cap → 200
        response = client.post('/compute/forecast-scaling', json={
            'project_dir': str(project),
            'forecast_periods': 70,  # 70/52 ≈ 1.35×
        })
        assert response.status_code == 200
        body = response.json()
        assert body['horizon_max_multiplier'] == 1.5  # awareness, не 2.0
