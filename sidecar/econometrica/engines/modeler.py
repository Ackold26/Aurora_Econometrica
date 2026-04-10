"""
MMM Model training engine using PyMC-Marketing.
Bayesian Marketing Mix Model with Adstock + Hill saturation.
"""
import json
import pickle
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def check_compiler() -> bool:
    """Check if C compiler is available (for NUTS sampler)."""
    import subprocess
    import platform
    try:
        if platform.system() == 'Windows':
            # Try MSVC first, then MinGW
            for cmd in [['cl.exe'], ['g++', '--version']]:
                try:
                    subprocess.run(cmd, capture_output=True, timeout=5)
                    return True
                except FileNotFoundError:
                    continue
            return False
        else:
            result = subprocess.run(['gcc', '--version'], capture_output=True, timeout=5)
            return result.returncode == 0
    except Exception:
        return False


def get_mcmc_params(has_compiler: bool) -> dict:
    """MCMC parameters based on environment (Windows optimization)."""
    if has_compiler:
        return {'chains': 4, 'draws': 2000, 'tune': 1000, 'sampler': 'NUTS'}
    return {'chains': 2, 'draws': 1000, 'tune': 500, 'sampler': 'Metropolis'}


def train_model(config: dict, project_dir: str) -> dict[str, Any]:
    """Train a Bayesian MMM model.

    Args:
        config: {
            'data_file': str,          # Path to clean xlsx/csv
            'kpi_column': str,         # Target variable
            'media_columns': list,     # Media channel columns
            'control_columns': list,   # Control variable columns
            'date_column': str,        # Date column
            'adstock_config': dict,    # {channel: 'geometric'|'weibull'}
            'mcmc_override': dict|None # Override chains/draws/tune
        }
        project_dir: Path to project directory for saving results

    Returns:
        JSON-serializable result with diagnostics
    """
    project_path = Path(project_dir)
    models_dir = project_path / 'models'
    results_dir = project_path / 'results'
    models_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    # Read data
    data_file = config['data_file']
    if data_file.endswith('.csv'):
        df = pd.read_csv(data_file)
    else:
        df = pd.read_excel(data_file)

    kpi_col = config['kpi_column']
    media_cols = config['media_columns']
    control_cols = config.get('control_columns', [])
    date_col = config.get('date_column', 'date')
    adstock_config = config.get('adstock_config', {})

    # Parse dates
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col])

    y = df[kpi_col].values.astype(float)
    n_obs = len(y)
    n_params = len(media_cols) + len(control_cols) + 1  # +1 for intercept

    # Apply adstock transformations
    from utils.adstock import apply_adstock

    X_media = pd.DataFrame()
    adstock_params_used = {}
    for col in media_cols:
        a_type = adstock_config.get(col, 'geometric')
        X_media[col] = apply_adstock(df[col].fillna(0).values.astype(float), a_type)
        adstock_params_used[col] = {'type': a_type}

    X_control = df[control_cols].fillna(0).astype(float) if control_cols else pd.DataFrame()

    # Normalize
    media_means = X_media.mean()
    media_stds = X_media.std().replace(0, 1)
    X_media_norm = (X_media - media_means) / media_stds

    y_mean, y_std = y.mean(), max(y.std(), 1e-10)
    y_norm = (y - y_mean) / y_std

    # MCMC parameters
    has_compiler = check_compiler()
    mcmc = config.get('mcmc_override') or get_mcmc_params(has_compiler)
    chains = mcmc.get('chains', 2)
    draws = mcmc.get('draws', 1000)
    tune = mcmc.get('tune', 500)

    logger.info(f"Training MMM: {n_obs} obs, {len(media_cols)} media, {len(control_cols)} control, "
                f"MCMC: {chains} chains × {draws} draws (compiler={'yes' if has_compiler else 'no'})")

    # Build and fit model
    try:
        import pymc as pm

        with pm.Model() as mmm:
            # Priors
            intercept = pm.Normal('intercept', mu=0, sigma=1)

            # Media coefficients (positive — media should drive sales)
            media_betas = pm.HalfNormal('media_betas', sigma=0.5, shape=len(media_cols))

            # Control coefficients (can be negative)
            if len(control_cols) > 0:
                control_betas = pm.Normal('control_betas', mu=0, sigma=0.5, shape=len(control_cols))
                control_effect = pm.math.dot(X_control.values.astype(float), control_betas)
            else:
                control_effect = 0

            # Hill saturation per channel
            alphas = pm.Gamma('alphas', alpha=3, beta=1, shape=len(media_cols))
            gammas = pm.Beta('gammas', alpha=2, beta=2, shape=len(media_cols))

            # Saturated media effect
            from utils.saturation import hill_function
            media_effect = 0
            for i, col in enumerate(media_cols):
                x_ch = X_media_norm[col].values
                # Apply Hill saturation
                x_safe = pm.math.maximum(x_ch, 0)
                gamma_scaled = gammas[i] * x_safe.max() if hasattr(x_safe, 'max') else gammas[i]
                saturated = x_safe ** alphas[i] / (x_safe ** alphas[i] + gamma_scaled ** alphas[i] + 1e-10)
                media_effect = media_effect + media_betas[i] * saturated

            # Likelihood
            mu = intercept + media_effect + control_effect
            sigma = pm.HalfNormal('sigma', sigma=0.5)
            pm.Normal('obs', mu=mu, sigma=sigma, observed=y_norm)

            # Sample
            trace = pm.sample(
                draws=draws,
                tune=tune,
                chains=chains,
                cores=1,  # Windows compatibility
                return_inferencedata=True,
                progressbar=True,
            )

        # Diagnostics
        r_hat_values = []
        try:
            import arviz as az
            summary = az.summary(trace)
            r_hat_values = summary['r_hat'].values.tolist()
        except Exception:
            pass

        r_hat_max = max(r_hat_values) if r_hat_values else 1.0
        divergences = int(trace.sample_stats['diverging'].sum()) if hasattr(trace, 'sample_stats') else 0

        # Posterior predictions (no context manager needed for PyMC 5.10+)
        ppc = pm.sample_posterior_predictive(trace, model=mmm, extend_inferencedata=True)

        y_pred_norm = ppc.posterior_predictive['obs'].mean(dim=['chain', 'draw']).values
        y_pred = y_pred_norm * y_std + y_mean

        # Metrics
        from utils.diagnostics import compute_r_squared, compute_mape, compute_rmse, generate_diagnostics_summary

        r_squared = compute_r_squared(y, y_pred)
        mape = compute_mape(y, y_pred)
        rmse = compute_rmse(y, y_pred)

        diagnostics = generate_diagnostics_summary(
            r_squared=r_squared, mape=mape, rmse=rmse,
            r_hat_max=r_hat_max, divergences=divergences,
            n_obs=n_obs, n_params=n_params,
        )

        # Extract posterior means for channel contributions
        media_beta_means = trace.posterior['media_betas'].mean(dim=['chain', 'draw']).values.tolist()
        alpha_means = trace.posterior['alphas'].mean(dim=['chain', 'draw']).values.tolist()
        gamma_means = trace.posterior['gammas'].mean(dim=['chain', 'draw']).values.tolist()

        channel_params = {}
        for i, col in enumerate(media_cols):
            channel_params[col] = {
                'beta': round(media_beta_means[i], 4),
                'alpha': round(alpha_means[i], 4),
                'gamma': round(gamma_means[i], 4),
                'adstock': adstock_params_used[col],
            }

        # Save model
        model_data = {
            'trace': trace,
            'model': mmm,
            'config': config,
            'channel_params': channel_params,
            'normalization': {
                'media_means': media_means.to_dict(),
                'media_stds': media_stds.to_dict(),
                'y_mean': float(y_mean),
                'y_std': float(y_std),
            },
            'y_actual': y.tolist(),
            'y_predicted': y_pred.tolist(),
        }

        model_path = models_dir / 'latest.pkl'
        with open(model_path, 'wb') as f:
            pickle.dump(model_data, f)

        # Save params as JSON (for UI without loading pickle)
        params_path = models_dir / 'latest-params.json'
        with open(params_path, 'w', encoding='utf-8') as f:
            json.dump({
                'channel_params': channel_params,
                'diagnostics': diagnostics,
                'config': {k: v for k, v in config.items() if k != 'data_file'},
                'mcmc': mcmc,
                'has_compiler': has_compiler,
            }, f, ensure_ascii=False, indent=2)

        # Save diagnostics as result
        result_path = results_dir / 'model-diagnostics.json'
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(diagnostics, f, ensure_ascii=False, indent=2)

        return {
            'status': 'ok',
            'model_path': str(model_path),
            'diagnostics': diagnostics,
            'channel_params': channel_params,
            'mcmc_info': {
                **mcmc,
                'has_compiler': has_compiler,
            },
        }

    except ImportError as e:
        return {
            'status': 'error',
            'message': f'Пакет не установлен: {e}. Запустите pip install pymc pymc-marketing',
        }
    except Exception as e:
        logger.exception("Model training failed")
        return {
            'status': 'error',
            'message': f'Ошибка обучения модели: {e}',
        }
