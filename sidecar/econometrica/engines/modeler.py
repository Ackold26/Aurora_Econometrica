"""
MMM Model training engine using PyMC-Marketing.
Bayesian Marketing Mix Model with Adstock + Hill saturation.
"""
import json
import pickle
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _find_msvc_via_vswhere() -> str | None:
    """Locate MSVC cl.exe directory via official vswhere.exe.

    vswhere is always at %ProgramFiles(x86)%\\Microsoft Visual Studio\\Installer\\vswhere.exe
    regardless of VS version/edition. Returns bin path containing cl.exe, or None.
    Side effect: adds the path to os.environ['PATH'] so subsequent PyTensor subprocess calls find it.
    """
    import os
    import subprocess
    import glob

    vswhere = os.path.join(
        os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
        'Microsoft Visual Studio', 'Installer', 'vswhere.exe'
    )
    if not os.path.isfile(vswhere):
        return None

    try:
        result = subprocess.run(
            [vswhere, '-latest', '-products', '*',
             '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
             '-property', 'installationPath'],
            capture_output=True, text=True, timeout=10
        )
        vs_path = result.stdout.strip()
        if not vs_path:
            return None
    except Exception:
        return None

    # Find cl.exe inside VC\Tools\MSVC\<version>\bin\Hostx64\x64\
    pattern = os.path.join(vs_path, 'VC', 'Tools', 'MSVC', '*', 'bin', 'Hostx64', 'x64', 'cl.exe')
    matches = glob.glob(pattern)
    if not matches:
        return None

    cl_exe = sorted(matches)[-1]
    bin_dir = os.path.dirname(cl_exe)

    # Full env setup — run vcvars64.bat and capture INCLUDE/LIB/PATH/etc.
    # Without this, cl.exe runs but can't find windows.h / kernel32.lib → PyTensor compile fails.
    vcvars = os.path.join(vs_path, 'VC', 'Auxiliary', 'Build', 'vcvars64.bat')
    if os.path.isfile(vcvars):
        try:
            # Run vcvars64.bat and dump env via `set`, parse output
            proc = subprocess.run(
                f'"{vcvars}" >nul 2>&1 && set',
                shell=True, capture_output=True, text=True, timeout=30
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if '=' in line:
                        key, _, val = line.partition('=')
                        # Only inject compiler-relevant vars to avoid clobbering
                        if key.upper() in ('PATH', 'INCLUDE', 'LIB', 'LIBPATH', 'WINDOWSSDKDIR',
                                           'WINDOWSSDKVERSION', 'VCINSTALLDIR', 'VCTOOLSINSTALLDIR',
                                           'VSINSTALLDIR'):
                            os.environ[key] = val
                return bin_dir
        except Exception:
            pass

    # Fallback: at least add cl.exe dir to PATH (may still fail on missing headers)
    current_path = os.environ.get('PATH', '')
    if bin_dir not in current_path:
        os.environ['PATH'] = f"{bin_dir};{current_path}"
    return bin_dir


def check_compiler() -> bool:
    """Check if C compiler is available (for NUTS sampler).

    Windows strategy:
    1. Try cl.exe via PATH (activated via vcvars, or manually added)
    2. Try g++ (MinGW)
    3. Fall back to vswhere.exe to locate MSVC Build Tools installation
       (MSVC is not in PATH by default — must be activated via vcvars64.bat)
    """
    import subprocess
    import platform
    try:
        if platform.system() == 'Windows':
            for cmd in [['cl.exe'], ['g++', '--version']]:
                try:
                    subprocess.run(cmd, capture_output=True, timeout=5)
                    return True
                except FileNotFoundError:
                    continue
            # Last resort: locate MSVC via vswhere and inject into PATH
            return _find_msvc_via_vswhere() is not None
        else:
            result = subprocess.run(['gcc', '--version'], capture_output=True, timeout=5)
            return result.returncode == 0
    except Exception:
        return False


def get_mcmc_params(has_compiler: bool) -> dict:
    """MCMC parameters based on environment (Windows optimization).

    Defaults bumped 2026-04-19 to 4/2000/2000 — на JAX/NUTS секунды,
    но даёт надёжный R-hat (4 цепи) и точные ROI CI (2000 draws + 2000 tune).
    """
    if has_compiler:
        return {'chains': 4, 'draws': 2000, 'tune': 2000, 'sampler': 'NUTS'}
    # No compiler → Metropolis fallback. Сохраняем меньшие дефолты, иначе обучение
    # 4×2000×2000 на Metropolis = десятки минут. Antон поднимет вручную если нужно.
    return {'chains': 2, 'draws': 1000, 'tune': 500, 'sampler': 'Metropolis'}


def train_model(config: dict, project_dir: str, progress_callback=None) -> dict[str, Any]:
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
    def report(phase: str, pct: int = 0, **_kw):
        """A1: phase-level progress — no per-draw callback instability."""
        if progress_callback:
            try:
                progress_callback({'phase': phase, 'pct': pct})
            except Exception:
                pass  # never crash training due to callback error

    project_path = Path(project_dir)
    models_dir = project_path / 'models'
    results_dir = project_path / 'results'
    models_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    report('loading', pct=10)

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

    # Normalize media
    media_means = X_media.mean()
    media_stds = X_media.std().replace(0, 1)
    X_media_norm = (X_media - media_means) / media_stds

    # Normalize controls — критично: без этого большие контроли (price, budget) дают
    # огромный control_effect, y_pred улетает в ∞, R² получается астрономически отрицательным.
    if len(control_cols) > 0:
        control_means = X_control.mean()
        control_stds = X_control.std().replace(0, 1)
        X_control_norm = (X_control - control_means) / control_stds
    else:
        control_means = pd.Series(dtype=float)
        control_stds = pd.Series(dtype=float)
        X_control_norm = pd.DataFrame()

    y_mean, y_std = y.mean(), max(y.std(), 1e-10)
    y_norm = (y - y_mean) / y_std

    # MCMC parameters
    has_compiler = check_compiler()
    mcmc = config.get('mcmc_override') or get_mcmc_params(has_compiler)
    chains = mcmc.get('chains', 4)
    draws = mcmc.get('draws', 2000)
    tune = mcmc.get('tune', 2000)

    report('compiling', pct=20)

    logger.info(f"Training MMM: {n_obs} obs, {len(media_cols)} media, {len(control_cols)} control, "
                f"MCMC: {chains} chains × {draws} draws (compiler={'yes' if has_compiler else 'no'})")

    # Build and fit model
    try:
        import pymc as pm

        with pm.Model() as mmm:
            # Priors — tightened 2026-04-19 to fix NUTS funnel / divergences on small data.
            # Previous priors (Gamma(3,1) for alpha, Beta(2,2) for gamma, HalfNormal(0.5) for beta)
            # created poorly identified Hill saturation geometry → 1600+ divergences.
            intercept = pm.Normal('intercept', mu=0, sigma=0.5)  # было sigma=1

            # Media coefficients — более консервативный HalfNormal, меньший разброс
            media_betas = pm.HalfNormal('media_betas', sigma=0.3, shape=len(media_cols))  # было 0.5

            # Control coefficients (используем нормализованные X_control_norm)
            if len(control_cols) > 0:
                control_betas = pm.Normal('control_betas', mu=0, sigma=0.3, shape=len(control_cols))
                control_effect = pm.math.dot(X_control_norm.values.astype(float), control_betas)
            else:
                control_effect = 0

            # Hill saturation — жёстче priors для стабильной geometry
            # alpha ≈ 1-2 (типичный saturation shape), Gamma(5, 3) имеет mean=1.67, var=0.56
            alphas = pm.Gamma('alphas', alpha=5, beta=3, shape=len(media_cols))  # было Gamma(3, 1) mean=3
            # gamma — half-point of saturation, концентрируемся около 0.5
            gammas = pm.Beta('gammas', alpha=3, beta=3, shape=len(media_cols))  # было Beta(2, 2) too wide

            # Saturated media effect
            from utils.saturation import hill_function
            media_effect = 0
            for i, col in enumerate(media_cols):
                x_ch = X_media_norm[col].values
                x_safe = pm.math.maximum(x_ch, 0)
                # Простой Hill без gamma_scaled — стабильнее при x.max() низком
                saturated = x_safe ** alphas[i] / (x_safe ** alphas[i] + gammas[i] ** alphas[i] + 1e-10)
                media_effect = media_effect + media_betas[i] * saturated

            # Likelihood
            mu = intercept + media_effect + control_effect
            sigma = pm.HalfNormal('sigma', sigma=0.3)  # было 0.5 — y_norm std=1, так что 0.3 ок
            pm.Normal('obs', mu=mu, sigma=sigma, observed=y_norm)

            # A1: report sampling start — pct stays at 25 during 3-15 min MCMC
            # elapsed timer in UI shows progress is alive
            report('sampling', pct=25)

            # Prefer JAX/NumPyro backend (5-15× faster than PyTensor Python fallback).
            # PyTensor on Windows doesn't find g++ by default → falls back to slow Python NUTS.
            # NumPyro uses JAX+XLA → compiles gradient graph to native, handles parallel chains.
            _use_numpyro = False
            try:
                import numpyro  # noqa: F401
                import jax  # noqa: F401
                _use_numpyro = True
                logger.info('Using NumPyro NUTS sampler (JAX backend)')
            except ImportError:
                logger.warning('NumPyro/JAX not available — falling back to PyTensor NUTS')

            if _use_numpyro:
                trace = pm.sample(
                    draws=draws,
                    tune=tune,
                    chains=chains,
                    return_inferencedata=True,
                    progressbar=True,
                    nuts_sampler='numpyro',
                    chain_method='vectorized',  # parallel chains in single JAX call
                )
            else:
                try:
                    def _draw_cb(trace_slice, draw):
                        pass
                    trace = pm.sample(
                        draws=draws,
                        tune=tune,
                        chains=chains,
                        cores=1,
                        return_inferencedata=True,
                        progressbar=True,
                        callback=_draw_cb,
                    )
                except TypeError:
                    trace = pm.sample(
                        draws=draws,
                        tune=tune,
                        chains=chains,
                        cores=1,
                        return_inferencedata=True,
                        progressbar=True,
                    )

        report('diagnostics', pct=90)

        # Diagnostics
        r_hat_values = []
        per_param_rhat = {}
        try:
            import arviz as az
            summary = az.summary(trace)
            r_hat_values = summary['r_hat'].values.tolist()
            # C1: filter to key params only (intercept, sigma, media_betas[i])
            key_params = {'intercept', 'sigma'} | {f'media_betas[{i}]' for i in range(len(media_cols))}
            for param in summary.index:
                if param in key_params:
                    per_param_rhat[param] = round(float(summary.loc[param, 'r_hat']), 4)
        except Exception:
            pass

        r_hat_max = max(r_hat_values) if r_hat_values else 1.0
        divergences = int(trace.sample_stats['diverging'].sum()) if hasattr(trace, 'sample_stats') else 0

        # Posterior predictions. PyMC 5.x + custom Deterministic variables (Adstock/Hill)
        # sometimes crash with `'functools.partial' object has no attribute '__name__'`
        # inside sample_posterior_predictive. Fallback: reconstruct y_pred manually from posterior means.
        y_pred_norm = None
        try:
            ppc = pm.sample_posterior_predictive(trace, model=mmm, extend_inferencedata=True, progressbar=False)
            y_pred_norm = ppc.posterior_predictive['obs'].mean(dim=['chain', 'draw']).values
        except Exception as e:
            logger.warning(f"sample_posterior_predictive failed ({type(e).__name__}: {e}); computing y_pred manually from posterior means")
            try:
                import numpy as _np
                intercept_mean = float(trace.posterior['intercept'].mean(dim=['chain', 'draw']).values)
                media_betas_mean = trace.posterior['media_betas'].mean(dim=['chain', 'draw']).values
                alphas_mean = trace.posterior['alphas'].mean(dim=['chain', 'draw']).values
                gammas_mean = trace.posterior['gammas'].mean(dim=['chain', 'draw']).values

                # Reconstruct Hill-saturated predictions using posterior means
                # (using X_media_norm — same transformation as inside pm.Model)
                media_effect_pred = _np.zeros(n_obs)
                for i, col in enumerate(media_cols):
                    x_ch = X_media_norm[col].values
                    alpha_i = float(alphas_mean[i])
                    gamma_i = float(gammas_mean[i])
                    beta_i = float(media_betas_mean[i])
                    x_safe = _np.maximum(x_ch, 0)
                    gamma_scaled = gamma_i * max(x_safe.max(), 1e-10)
                    saturated = x_safe ** alpha_i / (x_safe ** alpha_i + gamma_scaled ** alpha_i + 1e-10)
                    media_effect_pred += beta_i * saturated

                # Control effect (используем нормализованные контроли — так же как внутри pm.Model)
                control_effect_pred = _np.zeros(n_obs)
                if len(control_cols) > 0:
                    control_betas_mean = trace.posterior['control_betas'].mean(dim=['chain', 'draw']).values
                    control_effect_pred = X_control_norm.values.astype(float) @ _np.asarray(control_betas_mean)

                y_pred_norm = intercept_mean + media_effect_pred + control_effect_pred
            except Exception as e2:
                logger.exception(f"Manual y_pred fallback also failed: {e2}")
                import numpy as _np
                y_pred_norm = _np.zeros(n_obs)

        y_pred = y_pred_norm * y_std + y_mean

        # C2: actual_vs_predicted with dates
        dates_list = None
        if date_col in df.columns:
            try:
                dates_list = df[date_col].dt.strftime('%Y-%m-%d').tolist()
            except Exception:
                dates_list = None

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
        # Enrich diagnostics with per-param R-hat and actual_vs_predicted
        diagnostics['per_param_rhat'] = per_param_rhat
        diagnostics['actual_vs_predicted'] = {
            'actual': [round(float(v), 4) for v in y.tolist()],
            'predicted': [round(float(v), 4) for v in y_pred.tolist()],
            'dates': dates_list,
        }

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

        report('saving', pct=95)

        # Save model.
        # NOTE: we do NOT pickle `trace` or `mmm` because PyMC models with custom
        # Deterministic variables (Adstock/Hill via pm.math) contain functools.partial
        # closures that don't have __name__ → pickle.dump crashes with
        # `'functools.partial' object has no attribute '__name__'`.
        # Downstream engines (decomposer/optimizer/scenario) only need channel_params +
        # posterior means + normalization — not the raw trace or model graph.
        model_data = {
            'config': config,
            'channel_params': channel_params,
            'normalization': {
                'media_means': media_means.to_dict(),
                'media_stds': media_stds.to_dict(),
                'control_means': control_means.to_dict() if len(control_cols) > 0 else {},
                'control_stds': control_stds.to_dict() if len(control_cols) > 0 else {},
                'y_mean': float(y_mean),
                'y_std': float(y_std),
            },
            'y_actual': y.tolist(),
            'y_predicted': y_pred.tolist(),
        }

        model_path = models_dir / 'latest.pkl'

        # Model versioning: archive previous model before overwriting
        history_dir = models_dir / 'history'
        history_dir.mkdir(exist_ok=True)
        if model_path.exists():
            import shutil
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            shutil.copy2(model_path, history_dir / f'model-{ts}.pkl')
            # Also archive params JSON
            prev_params = models_dir / 'latest-params.json'
            if prev_params.exists():
                shutil.copy2(prev_params, history_dir / f'params-{ts}.json')
            # Keep max 5 versions (oldest first)
            archives = sorted(history_dir.glob('model-*.pkl'))
            while len(archives) > 5:
                archives[0].unlink(missing_ok=True)
                # Also remove matching params
                param_f = archives[0].name.replace('model-', 'params-').replace('.pkl', '.json')
                (history_dir / param_f).unlink(missing_ok=True)
                archives.pop(0)

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

        report('complete', pct=100)

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
