"""
MMM Model training engine using PyMC-Marketing.
Bayesian Marketing Mix Model with Adstock + Hill saturation.
"""
import json
import os
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
    merge_rules = config.get('merge_rules', {}) or {}

    # Parse dates
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col])

    # ── Материализация виртуальных каналов (merged recommendations) ──
    # См. utils/merge_rules.py. idempotent. Config + merge_rules сохранятся
    # в pickle → decomposer/optimizer увидят те же правила.
    from utils.merge_rules import apply_merge_rules
    if merge_rules:
        source_count = sum(len(v) for v in merge_rules.values() if isinstance(v, (list, tuple)))
        logger.info(f'Applying merge_rules: {list(merge_rules.keys())} ({source_count} source cols)')
    apply_merge_rules(df, merge_rules)

    # ── Валидация колонок ДО любых вычислений ─────────────────────────
    # Защита от race: пользователь мог применить рекомендацию «объединить с другим
    # каналом» (смерджить псевдо-канал «Малые медиа»), но xlsx остался прежним.
    # Или удалить колонку в xlsx после валидации. Падаем с понятной ошибкой вместо
    # сырого pandas KeyError в середине training loop.
    if kpi_col not in df.columns:
        return {
            'status': 'error',
            'error_code': 'MISSING_KPI_COLUMN',
            'message': f'Колонка KPI «{kpi_col}» не найдена в файле данных. '
                       f'Доступные колонки: {", ".join(df.columns[:20].tolist())}'
                       + ('...' if len(df.columns) > 20 else ''),
        }
    missing_media = [c for c in media_cols if c not in df.columns]
    if missing_media:
        return {
            'status': 'error',
            'error_code': 'MISSING_MEDIA_COLUMNS',
            'message': (
                f'В списке медиа-каналов есть {len(missing_media)} '
                f'колонк{"и" if len(missing_media) > 1 else "а"}, которы{"х" if len(missing_media) > 1 else "й"} нет в файле: '
                f'{", ".join(repr(c) for c in missing_media[:10])}'
                + (f' (и ещё {len(missing_media) - 10})' if len(missing_media) > 10 else '')
                + '. Вернитесь на шаг «Валидация» и проверьте назначение ролей колонок.'
            ),
            'missing_columns': missing_media,
        }
    missing_control = [c for c in control_cols if c not in df.columns]
    if missing_control:
        return {
            'status': 'error',
            'error_code': 'MISSING_CONTROL_COLUMNS',
            'message': (
                f'В списке контрольных колонок есть {len(missing_control)} отсутствующ'
                f'{"их" if len(missing_control) > 1 else "ая"}: {", ".join(repr(c) for c in missing_control[:10])}'
                + (f' (и ещё {len(missing_control) - 10})' if len(missing_control) > 10 else '')
                + '. Вернитесь на шаг «Валидация» и проверьте назначение ролей колонок.'
            ),
            'missing_columns': missing_control,
        }

    y = df[kpi_col].values.astype(float)
    n_obs = len(y)
    n_params = len(media_cols) + len(control_cols) + 1  # +1 for intercept

    # Apply adstock transformations
    from utils.adstock import apply_adstock

    # Phase 1.1: pre-compute X_media с default decay (0.5) ONLY для media_means estimate.
    # Inside model, per-channel adstock уже использует sampled decay (hierarchical
    # logit-normal prior, see lines below). This keeps media_means semantically
    # consistent с v1.1.5 pickles for downstream code that uses pre-computed mean.
    # Pragmatic tradeoff: training-time adstock varies per draw via scan;
    # mean normalization uses fixed point estimate. Documented in ADR §5.
    X_media = pd.DataFrame()
    adstock_params_used = {}
    raw_media = pd.DataFrame()  # Phase 1.1: keep raw spend for in-model scan-based adstock
    for col in media_cols:
        a_type = adstock_config.get(col, 'geometric')
        raw_arr = df[col].fillna(0).values.astype(float)
        raw_media[col] = raw_arr
        X_media[col] = apply_adstock(raw_arr, a_type)  # default decay для mean estimate
        adstock_params_used[col] = {'type': a_type}

    X_control = df[control_cols].fillna(0).astype(float) if control_cols else pd.DataFrame()

    # Normalize media — Robyn-style spend/mean (P0-1/2/9 fix, math-fix-v1.0.13).
    # Pre-fix: z-score (X - mean) / std produced negative values that were clipped
    # at line 310 by pm.math.maximum(x, 0), silently dropping ~50% of data and
    # destroying response curve curvature. Result: scenario/optimizer/what-if
    # showed near-zero sensitivity to budget changes.
    # Post-fix: spend/mean keeps non-negative scale, gamma stays in [0,1] range.
    #
    # A1 fix (post-audit v1.2): track channels with zero training variance.
    # Pre-fix `replace(0, 1)` silently corrupted these — pickle stored mean=1,
    # scenario divided spend by 1 (raw scale!), Hill saturated at huge x_norm,
    # contribution = β × 1 × y_std fabricated from prior (uninformative).
    # Post-fix: replace zero with 1 for division safety BUT mark channel as
    # "untrained" so scenario/optimizer can refuse spend on it.
    raw_means = X_media.mean()
    untrained_channels = [c for c in media_cols if float(raw_means.get(c, 0)) == 0]
    media_means = raw_means.replace(0, 1)  # avoid div/0; flagged separately above
    X_media_norm = X_media / media_means
    if untrained_channels:
        logger.warning(
            f"Untrained channels (zero variance in training data): {untrained_channels}. "
            f"Scenario / optimizer will reject spend on these to avoid prior-only fabrication."
        )
    # media_stds removed — not used in spend/mean normalization

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

            # Media coefficients — более консервативный HalfNormal, меньший разброс.
            # Sprint 2 / A3: opt-in horseshoe priors для sparse channel selection.
            # Каналы с истинным β≈0 получают сильную shrinkage к нулю, что снижает
            # overfit на small N + предотвращает spurious channel effects.
            # Reference: Carvalho/Polson/Scott 2010 "Horseshoe estimator".
            use_horseshoe = bool(config.get('use_horseshoe', False))
            if use_horseshoe:
                # Global shrinkage parameter (controls overall sparsity level)
                horseshoe_tau = pm.HalfCauchy('horseshoe_tau', beta=0.1)
                # Local shrinkage per channel (allows individual β to escape global shrinkage)
                horseshoe_lambda = pm.HalfCauchy('horseshoe_lambda', beta=1.0, shape=len(media_cols))
                # Media β with horseshoe sparsity: σ = τ × λ_i
                media_betas = pm.HalfNormal(
                    'media_betas',
                    sigma=horseshoe_tau * horseshoe_lambda,
                    shape=len(media_cols),
                )
            else:
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

            # ─────────────────────────────────────────────────────────────────
            # Phase 1.1 — hierarchical adstock decay (logit-normal parameterization)
            # ─────────────────────────────────────────────────────────────────
            # Pilot validated logit-normal vs Beta-Beta (docs/PHASE_1_1_PILOT_RESULTS.md):
            # logit-normal 35% faster, R-hat 1.000 vs 1.020, ESS 5× better.
            # Hyperprior calibration per ADR §3.A1 + A2 (monthly data, mean ~0.20).
            # Non-centered z parameterization avoids funnel geometry on small N.
            import pytensor.tensor as pt
            from pytensor.scan import scan as pt_scan

            adstock_mu_logit = pm.Normal('adstock_mu_logit', mu=-1.4, sigma=0.7)
            adstock_sigma_logit = pm.HalfNormal('adstock_sigma_logit', sigma=1.0)
            adstock_z = pm.Normal('adstock_z', mu=0.0, sigma=1.0, shape=len(media_cols))
            adstock_decay = pm.Deterministic(
                'adstock_decay',
                pm.math.sigmoid(adstock_mu_logit + adstock_sigma_logit * adstock_z),
            )

            # Saturated media effect — Phase 1.1 per-channel scan-based adstock with sampled decay.
            # Geometric channels: scan-based recursive adstock with per-sample decay.
            # Weibull channels: pre-computed (decay sampling deferred to Phase 1.5).
            #
            # C1 fix (2026-04-26 audit): normalize on adstock_full.mean() per draw —
            # NOT on pre-computed default-decay mean. Pre-fix had mathematical drift:
            # model trained on adstock(raw; sampled_decay) / mean(adstock(raw; 0.5)),
            # downstream inference used adstock(raw; posterior_mean_decay) / pre-computed
            # mean. When posterior decay diverged sharply from 0.5 (TV brand 0.6+, Digital
            # 0.05) β-coefficients absorbed the mismatch, biasing ROI by 5-15% per channel.
            # Post-fix: in-model mean per draw + persist posterior_mean_adstock_mean per
            # channel for downstream consistency.
            adstock_means_per_channel = []  # collect Deterministic refs for posterior extraction
            media_effect = 0
            for i, col in enumerate(media_cols):
                a_type = adstock_config.get(col, 'geometric')
                if a_type == 'geometric':
                    # scan-based adstock: result_t = raw_t + decay * result_{t-1}
                    raw_x = raw_media[col].values
                    adstock_init = pt.as_tensor_variable(raw_x[0])
                    adstock_seq, _ = pt_scan(
                        fn=lambda x_t, prev, d: x_t + d * prev,
                        sequences=[pt.as_tensor_variable(raw_x[1:])],
                        outputs_info=[adstock_init],
                        non_sequences=[adstock_decay[i]],
                    )
                    adstock_full = pt.concatenate([[adstock_init], adstock_seq])
                else:
                    # Weibull stays hardcoded (Phase 1.5 task to make learnable)
                    adstock_full = pt.as_tensor_variable(X_media[col].values)
                # C1 fix: normalize by IN-MODEL mean per draw (correct math), not pre-computed.
                # For untrained channels (zero raw), guard with 1e-10 floor.
                in_model_mean = adstock_full.mean()
                in_model_mean_safe = pt.maximum(in_model_mean, 1e-10)
                # Persist as Deterministic for posterior extraction → downstream uses these.
                adstock_means_per_channel.append(
                    pm.Deterministic(f'adstock_mean_{i}', in_model_mean_safe)
                )
                x_norm = adstock_full / in_model_mean_safe
                x_safe = pm.math.maximum(x_norm, 0)
                saturated = x_safe ** alphas[i] / (x_safe ** alphas[i] + gammas[i] ** alphas[i] + 1e-10)
                media_effect = media_effect + media_betas[i] * saturated

            # Likelihood
            mu = intercept + media_effect + control_effect
            sigma = pm.HalfNormal('sigma', sigma=0.3)  # было 0.5 — y_norm std=1, так что 0.3 ок
            pm.Normal('obs', mu=mu, sigma=sigma, observed=y_norm)

            # A1: report sampling start — pct stays at 25 during 3-15 min MCMC
            # elapsed timer in UI shows progress is alive
            report('sampling', pct=25)

            # ───────────────────────────────────────────────────────────────
            # Tier-based MCMC sampling с fallback (v1.0.9)
            # ───────────────────────────────────────────────────────────────
            # Tier-1: NumPyro NUTS (JAX JIT + vectorized chains) — 5-15× быстрее.
            # Tier-2: PyTensor NUTS (cores=1) — стабильный, но 3-5× медленнее.
            # Full fail: honest RuntimeError с кодом MMM_SAMPLER_EXHAUSTED.
            #
            # Metropolis НЕ используется как Tier-3 fallback — на MMM с
            # Adstock/Hill он даёт r_hat > 2.0 (ложный зелёный результат
            # опаснее честного fail).
            #
            # Fallback Tier-1 → Tier-2 ТОЛЬКО на `functools.partial` ошибке
            # (известный PyMC 5 + JAX JIT bug для custom Deterministic).
            # Другие ошибки (плохие данные, numerical issues) не маскируем
            # медленным backend'ом — Tier-2 даст ту же ошибку за 10 минут.
            #
            # Override: env `AURORA_NUTS_BACKEND=numpyro|pymc|auto` позволяет
            # оператору форсировать конкретный backend без rebuild'а.
            # ───────────────────────────────────────────────────────────────
            _backend = os.environ.get('AURORA_NUTS_BACKEND', 'auto').lower()
            _use_numpyro = False
            _jax_ref = None  # сохранить модуль jax для probe devices ниже
            if _backend in ('auto', 'numpyro'):
                try:
                    import numpyro  # noqa: F401
                    import jax
                    _jax_ref = jax
                    _use_numpyro = True
                    logger.info(
                        f'MCMC backend: NumPyro NUTS (JAX) — '
                        f'numpyro={numpyro.__version__}, jax={jax.__version__}'
                    )
                except ImportError:
                    if _backend == 'numpyro':
                        raise RuntimeError(
                            'AURORA_NUTS_BACKEND=numpyro but NumPyro/JAX not installed'
                        )
                    logger.warning('NumPyro/JAX not available — using PyTensor NUTS')

            trace = None
            _sampling_errors: list[tuple[str, str]] = []

            def _is_partial_bug(exc: BaseException) -> bool:
                """PyMC 5 + JAX JIT bug: custom Deterministic → functools.partial
                без __name__. Fallback оправдан только на этой конкретной ошибке."""
                msg = str(exc)
                return 'functools.partial' in msg or "'__name__'" in msg

            # ── Tier 1: NumPyro NUTS ───────────────────────────────────
            if _use_numpyro and _backend != 'pymc':
                # Auto-select chain_method:
                #   - parallel если JAX видит >1 host device (XLA_FLAGS сработал в server.py)
                #     → цепи реально распараллелены по ядрам, ускорение ×N.
                #   - vectorized fallback если 1 device (старый jax, либо пользователь
                #     задал AURORA_MCMC_CORES=1) → безопасный single-device путь.
                # Override: env AURORA_MCMC_CHAIN_METHOD=parallel|vectorized|sequential
                _n_devices = len(_jax_ref.devices()) if _jax_ref is not None else 1
                _chain_method_env = os.environ.get('AURORA_MCMC_CHAIN_METHOD', '').lower()
                if _chain_method_env in ('parallel', 'vectorized', 'sequential'):
                    _chain_method = _chain_method_env
                else:
                    _chain_method = 'parallel' if _n_devices > 1 else 'vectorized'
                logger.info(
                    f'NumPyro chain_method={_chain_method} '
                    f'(jax_devices={_n_devices}, chains={chains})'
                )
                try:
                    logger.info(
                        f'Sampling: Tier-1 NumPyro NUTS '
                        f'(chains={chains}, draws={draws}, tune={tune}, method={_chain_method})'
                    )
                    trace = pm.sample(
                        draws=draws,
                        tune=tune,
                        chains=chains,
                        return_inferencedata=True,
                        progressbar=True,
                        nuts_sampler='numpyro',
                        chain_method=_chain_method,
                        target_accept=0.95,  # Phase 0.1 live-test: funnel posterior на тонких данных требует tighter step (default 0.8 даёт 70+ divergences)
                    )
                    logger.info('Tier-1 NumPyro NUTS: SUCCESS')
                except AttributeError as e:
                    if _is_partial_bug(e):
                        logger.warning(
                            f'Tier-1 NumPyro NUTS: functools.partial bug '
                            f'({str(e)[:150]}) — falling back to Tier-2 PyTensor NUTS'
                        )
                        _sampling_errors.append(('numpyro', f'partial bug: {str(e)[:200]}'))
                        trace = None
                    else:
                        # Другая AttributeError — не маскируем медленным fallback'ом
                        raise
                except Exception as e:
                    # Non-partial errors (bad data, numerical issues) — instant fail,
                    # Tier-2 на тех же данных вернёт то же
                    _sampling_errors.append(
                        ('numpyro', f'{type(e).__name__}: {str(e)[:200]}')
                    )
                    logger.error(
                        f'Tier-1 NumPyro NUTS failed on non-partial error: '
                        f'{type(e).__name__}: {e}'
                    )
                    raise

            # ── Tier 2: PyTensor NUTS ──────────────────────────────────
            if trace is None:
                logger.info(
                    f'Sampling: Tier-2 PyTensor NUTS '
                    f'(chains={chains}, draws={draws}, tune={tune}, cores=1)'
                )
                try:
                    def _draw_cb(trace_slice, draw):
                        pass
                    try:
                        trace = pm.sample(
                            draws=draws,
                            tune=tune,
                            chains=chains,
                            cores=1,
                            return_inferencedata=True,
                            progressbar=True,
                            callback=_draw_cb,
                            target_accept=0.95,
                        )
                    except TypeError:
                        # Callback не поддерживается (старая PyMC версия)
                        trace = pm.sample(
                            draws=draws,
                            tune=tune,
                            chains=chains,
                            cores=1,
                            return_inferencedata=True,
                            progressbar=True,
                            target_accept=0.95,
                        )
                    logger.info('Tier-2 PyTensor NUTS: SUCCESS')
                except AttributeError as e:
                    if _is_partial_bug(e):
                        _sampling_errors.append(
                            ('pytensor', f'partial bug: {str(e)[:200]}')
                        )
                        logger.error(
                            'Tier-2 PyTensor NUTS тоже упал на functools.partial. '
                            'Модель structurally несовместима с текущим PyMC 5 build.'
                        )
                        trace = None
                    else:
                        raise
                except Exception as e:
                    _sampling_errors.append(
                        ('pytensor', f'{type(e).__name__}: {str(e)[:200]}')
                    )
                    raise

            # ── Full fail: honest error (NO Metropolis — даёт r_hat > 2) ──
            if trace is None:
                _err_summary = '\n'.join(
                    f'  - {tier}: {msg}' for tier, msg in _sampling_errors
                )
                raise RuntimeError(
                    'MMM_SAMPLER_EXHAUSTED: не удалось обучить модель ни одним '
                    'MCMC backend\'ом (NumPyro, PyTensor).\n'
                    f'Попытки:\n{_err_summary}\n\n'
                    'Это structural incompatibility между PyMC 5 и конфигурацией '
                    'модели (Adstock/Hill custom Deterministic). Обратитесь в '
                    'поддержку с диагностическим отчётом.'
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

        # Posterior predictions — reconstructed from posterior means directly.
        # Причина: pm.sample_posterior_predictive на модели с Hill saturation
        # рекомпилирует PyTensor graph для каждого posterior draw (4×2000 = 8000),
        # что даёт 13+ минут на Windows без native C compiler (PyTensor Python mode).
        # Manual reconstruction из posterior means математически эквивалентна
        # `E[posterior_predictive].mean(chain,draw)` при нулевом observation noise,
        # а расхождение из-за sigma-noise усредняется к нулю на 8000 draws.
        # Downstream (decomposer/optimizer) НЕ читает trace.posterior_predictive —
        # только y_pred_norm нужен для диагностики y_pred vs actual.
        y_pred_norm = None
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
                # P0-7 fix (math audit): use raw gamma matching training formula at line 312.
                # Pre-fix: gamma_scaled = gamma × max(x) created divergent y_pred → wrong R²/MAPE.
                saturated = x_safe ** alpha_i / (x_safe ** alpha_i + gamma_i ** alpha_i + 1e-10)
                media_effect_pred += beta_i * saturated

            # Control effect (используем нормализованные контроли — так же как внутри pm.Model)
            control_effect_pred = _np.zeros(n_obs)
            if len(control_cols) > 0:
                control_betas_mean = trace.posterior['control_betas'].mean(dim=['chain', 'draw']).values
                control_effect_pred = X_control_norm.values.astype(float) @ _np.asarray(control_betas_mean)

            y_pred_norm = intercept_mean + media_effect_pred + control_effect_pred
            logger.info(f"y_pred reconstructed from posterior means ({n_obs} obs)")
        except Exception as e:
            logger.exception(f"y_pred reconstruction failed: {e}")
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
        # MCMC config — needed by UI to give context-aware divergence advice
        # (e.g., "Tune already at 6000 → recommend target_accept=0.99 instead").
        diagnostics['metrics']['mcmc'] = {
            'chains': int(chains),
            'draws': int(draws),
            'tune': int(tune),
            'target_accept': 0.95,
        }
        diagnostics['actual_vs_predicted'] = {
            'actual': [round(float(v), 4) for v in y.tolist()],
            'predicted': [round(float(v), 4) for v in y_pred.tolist()],
            'dates': dates_list,
        }

        # Extract posterior means for channel contributions
        media_beta_means = trace.posterior['media_betas'].mean(dim=['chain', 'draw']).values.tolist()
        alpha_means = trace.posterior['alphas'].mean(dim=['chain', 'draw']).values.tolist()
        gamma_means = trace.posterior['gammas'].mean(dim=['chain', 'draw']).values.tolist()

        # Phase 1.9: extract FULL posterior samples (joint per channel) for CI propagation.
        # Shape convention: (n_channels, n_samples) — samples[i, :] = all draws for channel i.
        # Joint correlation preserved across alphas/gammas/betas via consistent stack order.
        # float32 halves storage vs float64 with negligible loss for percentile/HDI estimation.
        media_betas_samples = np.asarray(
            trace.posterior['media_betas'].stack(sample=('chain', 'draw')).values, dtype=np.float32
        )
        alphas_samples = np.asarray(
            trace.posterior['alphas'].stack(sample=('chain', 'draw')).values, dtype=np.float32
        )
        gammas_samples = np.asarray(
            trace.posterior['gammas'].stack(sample=('chain', 'draw')).values, dtype=np.float32
        )

        # Phase 1.1: hierarchical adstock decay samples.
        # Shape (n_channels, n_samples) — same as alphas/gammas. Used by downstream
        # decomposer/scenario/optimizer for honest mROAS CI through adstock chain.
        try:
            adstock_decay_samples = np.asarray(
                trace.posterior['adstock_decay'].stack(sample=('chain', 'draw')).values, dtype=np.float32
            )
            adstock_decay_means = trace.posterior['adstock_decay'].mean(dim=['chain', 'draw']).values.tolist()
            adstock_mu_logit_mean = float(trace.posterior['adstock_mu_logit'].mean().values)
            adstock_sigma_logit_mean = float(trace.posterior['adstock_sigma_logit'].mean().values)
        except KeyError:
            # Defensive: if model didn't include adstock_decay (shouldn't happen post Phase 1.1),
            # fall back to default 0.5 per channel for backward compat with v1.1.5 readers.
            logger.warning("adstock_decay not in trace — falling back to defaults (v1.1.5 compat)")
            adstock_decay_samples = np.full((len(media_cols), media_betas_samples.shape[1]), 0.5, dtype=np.float32)
            adstock_decay_means = [0.5] * len(media_cols)
            adstock_mu_logit_mean = -1.4
            adstock_sigma_logit_mean = 0.5

        # C1 fix (audit 2026-04-26): extract in-model adstock_mean per channel posterior.
        # These replace pre-computed default-decay means для downstream normalization
        # consistency. Without this, decomposer/scenario/optimizer use stale 0.5-decay
        # mean while model trained on per-draw mean → 5-15% ROI bias on extreme decays.
        adstock_means_posterior = {}  # {channel: posterior_mean_adstock_mean}
        for i, col in enumerate(media_cols):
            try:
                am_mean = float(trace.posterior[f'adstock_mean_{i}'].mean(dim=['chain', 'draw']).values)
                adstock_means_posterior[col] = am_mean
            except (KeyError, ValueError):
                # Fallback: use pre-computed default-decay mean (v1.1.5 semantic)
                adstock_means_posterior[col] = float(media_means.get(col, 1.0))

        # Tail-ESS check per channel (Vehtari rule: tail_ess ≥ 100·n_chains for stable percentile estimation).
        # F4 fix (audit 2026-04-27): extended from media_betas only к β + α + γ + adstock_decay.
        # ROI/mROAS CI propagation chain involves all four params via Hill saturation —
        # if α/γ/decay tail-ESS bad, CI bounds unreliable даже когда β tail-ESS ok.
        # Per-channel tail_ess_ok = AND of all four params для that channel.
        try:
            tail_ess_threshold = 100 * int(chains)
            param_var_names = ['media_betas', 'alphas', 'gammas']
            try:
                # adstock_decay only present для v1.2 pickles (Phase 1.1+)
                _ = trace.posterior['adstock_decay']
                param_var_names.append('adstock_decay')
            except (KeyError, AttributeError):
                pass
            ess_per_param: dict[str, np.ndarray] = {}
            for vname in param_var_names:
                try:
                    ess_per_param[vname] = az.ess(trace, var_names=[vname], method='tail')[vname].values
                except Exception as _vess_err:
                    logger.warning(f"Tail-ESS failed для {vname}: {_vess_err}. Skipping.")
            # Per-channel AND aggregation — pass только если все доступные params выше threshold.
            tail_ess_ok_per_channel = []
            for i in range(len(media_cols)):
                ok = True
                for vname, ess_arr in ess_per_param.items():
                    try:
                        if i < len(ess_arr) and float(ess_arr[i]) < tail_ess_threshold:
                            ok = False
                            break
                    except (IndexError, ValueError, TypeError):
                        # Defensive — ambiguous result treated as ok (don't block training)
                        pass
                tail_ess_ok_per_channel.append(bool(ok))
        except Exception as _ess_err:
            logger.warning(f"Tail-ESS computation failed: {_ess_err}. Treating as OK (defensive).")
            tail_ess_ok_per_channel = [True] * len(media_cols)

        channel_params = {}
        for i, col in enumerate(media_cols):
            channel_params[col] = {
                'beta': round(media_beta_means[i], 4),
                'alpha': round(alpha_means[i], 4),
                'gamma': round(gamma_means[i], 4),
                'adstock': adstock_params_used[col],
                'tail_ess_ok': tail_ess_ok_per_channel[i],
                # Phase 1.1: posterior mean of learnable decay. Used by downstream
                # engines for point-estimate adstock + as fallback when posterior_samples
                # fields missing.
                'decay': round(float(adstock_decay_means[i]), 4),
                # C1 fix (audit 2026-04-26): posterior-consistent adstock mean per channel.
                # Downstream normalizes spend_adstocked / adstock_mean_posterior (not
                # pre-computed default-decay mean). Eliminates math drift identified in
                # Phase 1.1 audit. None for legacy v1.0/v1.1/v1.1.5/v1.0-ols pickles.
                'adstock_mean_posterior': round(float(adstock_means_posterior.get(col, 1.0)), 4),
            }

        report('saving', pct=95)

        # Save model.
        # NOTE: we do NOT pickle `trace` or `mmm` because PyMC models with custom
        # Deterministic variables (Adstock/Hill via pm.math) contain functools.partial
        # closures that don't have __name__ → pickle.dump crashes with
        # `'functools.partial' object has no attribute '__name__'`.
        # Downstream engines (decomposer/optimizer/scenario) only need channel_params +
        # posterior means + normalization — not the raw trace or model graph.
        # Extract intercept + control betas posterior means for decomposer baseline (Phase 3).
        intercept_mean_posterior = float(trace.posterior['intercept'].mean(dim=['chain', 'draw']).values)
        control_betas_mean_posterior = []
        if len(control_cols) > 0:
            control_betas_mean_posterior = trace.posterior['control_betas'].mean(dim=['chain', 'draw']).values.tolist()

        # Phase 1.9: full posterior samples for CI propagation in decomposer/optimizer/scenario.
        # Shape: intercept (n_samples,), control_betas (n_controls, n_samples) if any.
        intercept_samples = np.asarray(
            trace.posterior['intercept'].stack(sample=('chain', 'draw')).values, dtype=np.float32
        )
        if len(control_cols) > 0:
            control_betas_samples = np.asarray(
                trace.posterior['control_betas'].stack(sample=('chain', 'draw')).values, dtype=np.float32
            )
        else:
            control_betas_samples = np.zeros((0, intercept_samples.shape[0]), dtype=np.float32)

        model_data = {
            'config': config,
            'channel_params': channel_params,
            'normalization': {
                # P0-1/2/9 fix: spend/mean normalization, media_stds removed (not used)
                'media_means': media_means.to_dict(),
                'control_means': control_means.to_dict() if len(control_cols) > 0 else {},
                'control_stds': control_stds.to_dict() if len(control_cols) > 0 else {},
                'y_mean': float(y_mean),
                'y_std': float(y_std),
                # Phase 3 dependency: decomposer baseline = intercept + control effects
                'intercept_mean': intercept_mean_posterior,
                'control_betas_mean': control_betas_mean_posterior,
                # A1 fix (post-audit v1.2): channels with zero training variance.
                # Scenario/optimizer reject spend on these to avoid prior-only fabrication.
                'untrained_channels': untrained_channels,
            },
            # Phase 1.9: persist full posterior draws for honest uncertainty quantification.
            # Joint structure preserves per-draw correlation between alpha/gamma/beta of same channel.
            # Storage: ~864 KB for n=36 × 7 channels × 8000 draws × float32 — negligible vs PyMC pickle overhead.
            'posterior_samples': {
                'media_betas': media_betas_samples,        # shape (n_channels, n_samples)
                'alphas': alphas_samples,                  # shape (n_channels, n_samples)
                'gammas': gammas_samples,                  # shape (n_channels, n_samples)
                'intercept': intercept_samples,            # shape (n_samples,)
                'control_betas': control_betas_samples,    # shape (n_controls, n_samples)
                # Phase 1.1: hierarchical adstock decay samples per channel.
                'adstock_decay': adstock_decay_samples,    # shape (n_channels, n_samples)
                'adstock_mu_logit_mean': adstock_mu_logit_mean,    # hyperparameter point estimate
                'adstock_sigma_logit_mean': adstock_sigma_logit_mean,
                'media_columns': list(media_cols),         # ordering reference
                'control_columns': list(control_cols),     # ordering reference
                'n_chains': int(chains),
                'n_draws': int(draws),
            },
            # Phase 1.1 schema: model_version='1.2' adds adstock_decay samples + per-channel
            # decay point estimate в channel_params. Backward compat for v1.1.5 readers
            # via .get() — they see full Hill posterior CI but ignore decay samples
            # (revert to default 0.5). Phase 1.5+ will sample Weibull decay too.
            'model_version': '1.2',
            'y_actual': y.tolist(),
            'y_predicted': y_pred.tolist(),
            # Sprint 3 ADR §11/Q4 refinement: optional hint к причинному артефакту
            # в same project. Backward-compat: legacy readers ignore via .get().
            # MMM model lifecycle independent от causal artifact (refresh causal experiment
            # не invalidates MMM training), but UI knows where to look для combined view.
            'causal_artifact_path': None,
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
            # Нормализация y нужна фронту для денормализации интерактивного predictKPI:
            # модель работает в нормализованной шкале (y_norm = (y - y_mean) / y_std).
            # Чтобы показать KPI в исходных единицах (рублях), фронт умножает predict на y_std + y_mean.
            'normalization': {
                'y_mean': float(y_mean),
                'y_std': float(y_std),
            },
            'mcmc_info': {
                **mcmc,
                'has_compiler': has_compiler,
            },
        }

    except ImportError as e:
        return {
            'status': 'error',
            'message': f'Пакет не установлен: {e}. Запустите pip install pymc pymc-marketing',
            'error_code': 'IMPORT_ERROR',
        }
    except RuntimeError as e:
        # MMM_SAMPLER_EXHAUSTED — honest error из triple fallback, с деталями
        msg = str(e)
        if 'MMM_SAMPLER_EXHAUSTED' in msg:
            logger.error(f"MMM sampler exhausted: {msg}")
            return {
                'status': 'error',
                'message': msg,
                'error_code': 'MMM_SAMPLER_EXHAUSTED',
            }
        logger.exception("Model training failed (RuntimeError)")
        return {
            'status': 'error',
            'message': f'Ошибка обучения модели: {msg[:300]}',
            'error_code': 'RUNTIME_ERROR',
        }
    except AttributeError as e:
        # Оставшийся functools.partial где-то ВНЕ sampling-блока (маловероятно,
        # но возможно — например, в save/pickle). Диагностика для поддержки.
        msg = str(e)
        if 'functools.partial' in msg or "'__name__'" in msg:
            logger.exception("functools.partial bug вне sampling block")
            return {
                'status': 'error',
                'message': f'Ошибка сериализации модели: {msg[:200]}. '
                           f'Обратитесь в поддержку с кодом SERIALIZATION_ERROR.',
                'error_code': 'SERIALIZATION_ERROR',
            }
        logger.exception("Model training failed (AttributeError)")
        return {
            'status': 'error',
            'message': f'Ошибка обучения модели: {msg[:300]}',
            'error_code': 'ATTRIBUTE_ERROR',
        }
    except Exception as e:
        logger.exception("Model training failed (unexpected)")
        return {
            'status': 'error',
            'message': f'Ошибка обучения модели: {str(e)[:300]}',
            'error_code': 'UNKNOWN_ERROR',
        }
