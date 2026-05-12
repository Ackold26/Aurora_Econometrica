"""
B7 Backtest framework - out-of-sample validation against business reality.

Sprint 1.5 (B7 from audit) - validates Aurora's ROI converges with real business
outcomes (post-campaign sales lift). Hold out last K periods, fit on rest,
predict, compare with actual. Catches "math correct, predictions wrong" failures
that unit tests + SBC + Coverage Probability cannot detect.

Why critical: SBC, Coverage Probability - synthetic-data validation. Real
business test: did Aurora's predicted ROI actually materialize? If model says
"+15% lift" and actual sales lift is +3%, Aurora's math may be technically
correct but practically useless.

Workflow:
1. Load original training dataset (n_obs total)
2. Split: train = first (n_obs - holdout) rows, test = last holdout rows
3. Train model on train subset (Bayesian or OLS based on n)
4. For each test period, predict expected y given media spend
5. Compare predicted vs actual:
   - Out-of-sample R² (ideal: close to in-sample R²)
   - Out-of-sample MAPE
   - Prediction interval coverage (% of actuals within 90% PI)

Acceptance: out-of-sample R² gap from in-sample < 15pp. If gap > 25pp →
overfit warning. Recommended holdout: ~20-30% of total observations
(default 8 periods for monthly data with n=36-50).

Integration: standalone engine. Server endpoint /compute/backtest invokes
when user clicks "Validate model" в Report step. Result attached to model
diagnostics for reporting transparency.

Math reference: standard k-fold cross-validation adapted for time series
(forward-chaining holdout - never train on future).
"""
from __future__ import annotations

import json
import logging
import pickle
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def run_backtest(
    project_dir: str,
    holdout_periods: int = 8,
    mode: str = 'bayesian',
    *,
    use_horseshoe: bool = False,
) -> dict[str, Any]:
    """Run out-of-sample backtest on existing project's data.

    Args:
        project_dir: project with data file + (optional) existing model
        holdout_periods: how many trailing periods to hold out (default 8 = ~6mo monthly)
        mode: 'bayesian' (NUTS, accurate but 3-15min) | 'ols' (closed-form, <1sec)
        use_horseshoe: opt-in sparse priors (only if mode='bayesian')

    Returns:
        dict with:
          - status: 'ok' | 'error'
          - in_sample: {r_squared, mape}
          - out_of_sample: {r_squared, mape, pi_coverage_90}
          - r_squared_gap_pp: in-sample minus out-of-sample (lower = better)
          - verdict: 'reliable' | 'directional' | 'overfit'
          - per_period: list of {date, predicted, actual, residual, pi_low, pi_high}
          - recommendation: human-readable next step
    """
    project_path = Path(project_dir)

    # Find data file
    model_path = project_path / 'models' / 'latest.pkl'
    if not model_path.exists():
        return {
            'status': 'error',
            'error_code': 'NO_MODEL',
            'message': 'Модель не найдена - обучите модель перед backtest',
        }

    # Trust Level 3: централизованный pickle compat helper.
    from engines.persistence import load_model_with_compat
    model_data = load_model_with_compat(model_path)

    config = model_data['config']
    data_file = config['data_file']
    if not Path(data_file).exists():
        return {
            'status': 'error',
            'error_code': 'NO_DATA',
            'message': f'Файл данных не найден: {data_file}',
        }

    # Load data
    if data_file.endswith('.csv'):
        df = pd.read_csv(data_file)
    else:
        df = pd.read_excel(data_file)

    n_obs = len(df)
    if holdout_periods >= n_obs - 4:
        return {
            'status': 'error',
            'error_code': 'HOLDOUT_TOO_LARGE',
            'message': (
                f'holdout_periods={holdout_periods} оставляет {n_obs - holdout_periods} '
                f'обучающих периодов - слишком мало. Уменьшите holdout или соберите больше данных.'
            ),
        }

    # Split: train_df + test_df (forward-chaining)
    train_df = df.iloc[:-holdout_periods].copy()
    test_df = df.iloc[-holdout_periods:].copy()

    # Save train subset to temp file for re-training
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        train_data_file = tmp_path / 'train_subset.xlsx'
        train_df.to_excel(train_data_file, index=False)

        train_project_dir = tmp_path / 'backtest_project'
        train_project_dir.mkdir(parents=True, exist_ok=True)

        # Build train config (same as original, but pointing to subset data)
        train_config = dict(config)
        train_config['data_file'] = str(train_data_file)
        train_config['mode'] = mode
        if use_horseshoe:
            train_config['use_horseshoe'] = True

        # Re-train on subset
        if mode == 'ols':
            from engines.ols_modeler import train_ols as _train
        else:
            from engines.modeler import train_model as _train

        try:
            train_result = _train(train_config, str(train_project_dir))
        except Exception as e:
            return {
                'status': 'error',
                'error_code': 'TRAIN_FAILED',
                'message': f'Re-training на subset failed: {type(e).__name__}: {e}',
            }
        if train_result.get('status') != 'ok':
            return {
                'status': 'error',
                'error_code': 'TRAIN_NOT_OK',
                'message': train_result.get('message') or 'Re-training returned non-ok',
            }

        # Predict on test period via scenario engine (uses retrained model)
        test_media_plan = {
            col: test_df[col].fillna(0).tolist()
            for col in config['media_columns']
        }
        scenario_config = {
            'scenario_name': 'backtest_holdout',
            'media_plan': test_media_plan,
            'unit_costs': config.get('unit_costs', {}),
        }
        from engines.scenario import predict_scenario
        sc = predict_scenario(scenario_config, str(train_project_dir))
        if sc.get('status') != 'ok':
            return {
                'status': 'error',
                'error_code': 'PREDICT_FAILED',
                'message': sc.get('message') or 'Scenario prediction on holdout failed',
            }

    # Compare predicted vs actual on test period
    kpi_col = config['kpi_column']
    actual = test_df[kpi_col].values.astype(float)
    predicted = np.array(sc['predictions'][:len(actual)])

    # Out-of-sample metrics
    residuals = actual - predicted
    ss_res_oos = float(np.sum(residuals ** 2))
    ss_tot_oos = float(np.sum((actual - actual.mean()) ** 2)) if len(actual) > 1 else 1.0
    r2_oos = max(-1.0, 1.0 - ss_res_oos / max(ss_tot_oos, 1e-10))
    mape_oos = float(np.mean(np.abs(residuals / np.maximum(np.abs(actual), 1e-10))) * 100)

    # Prediction interval coverage (if scenario provided CI)
    pi_low_arr = np.full(len(actual), np.nan)
    pi_high_arr = np.full(len(actual), np.nan)
    pi_coverage = None
    # Scenario doesn't return per-period PI (only totals). For per-period coverage,
    # we'd need to re-fit + propagate full posterior - defer to A4 polish.
    # For now: report None, UI shows 'PI coverage недоступна (требует full posterior propagation per period)'.

    # In-sample metrics from re-trained model
    in_diag = train_result.get('diagnostics', {}).get('metrics', {})
    r2_in = float(in_diag.get('r_squared', 0))
    mape_in = float(in_diag.get('mape', 0))

    r2_gap_pp = (r2_in - r2_oos) * 100

    # Verdict
    if r2_gap_pp < 15:
        verdict = 'reliable'
        rec = (
            f'Out-of-sample R² {r2_oos:.3f} близко к in-sample {r2_in:.3f} '
            f'(gap {r2_gap_pp:+.1f}пп). Модель обобщает на новые данные - результаты '
            f'можно использовать для бизнес-решений.'
        )
    elif r2_gap_pp < 25:
        verdict = 'directional'
        rec = (
            f'Out-of-sample R² {r2_oos:.3f} ниже in-sample {r2_in:.3f} на '
            f'{r2_gap_pp:.1f}пп. Модель частично переобучена - используйте результаты '
            f'как направление, не точную оценку. Соберите больше данных или попробуйте '
            f'horseshoe-приоры (Sprint 2 / A3).'
        )
    else:
        verdict = 'overfit'
        rec = (
            f'Out-of-sample R² {r2_oos:.3f} сильно ниже in-sample {r2_in:.3f} '
            f'(gap {r2_gap_pp:.1f}пп) - модель переобучена и не обобщает. '
            f'Не используйте текущие оценки ROI для бизнес-решений. Рекомендации: '
            f'соберите больше данных, упростите медиа-микс, или используйте OLS-режим '
            f'с frequentist CI (стабильнее на small N).'
        )

    return {
        'status': 'ok',
        'holdout_periods': holdout_periods,
        'train_periods': n_obs - holdout_periods,
        'mode': mode,
        'in_sample': {
            'r_squared': round(r2_in, 4),
            'mape': round(mape_in, 2),
        },
        'out_of_sample': {
            'r_squared': round(r2_oos, 4),
            'mape': round(mape_oos, 2),
            'pi_coverage_90': pi_coverage,
        },
        'r_squared_gap_pp': round(r2_gap_pp, 1),
        'verdict': verdict,
        'per_period': [
            {
                'period': i + 1,
                'predicted': round(float(predicted[i]), 2),
                'actual': round(float(actual[i]), 2),
                'residual': round(float(residuals[i]), 2),
                'residual_pct': round(float(residuals[i] / max(abs(actual[i]), 1e-10)) * 100, 2),
            }
            for i in range(len(actual))
        ],
        'recommendation': rec,
    }
