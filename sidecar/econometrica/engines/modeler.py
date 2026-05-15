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

    # Full env setup - run vcvars64.bat and capture INCLUDE/LIB/PATH/etc.
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
       (MSVC is not in PATH by default - must be activated via vcvars64.bat)
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

    Defaults bumped 2026-04-19 to 4/2000/2000 - на JAX/NUTS секунды,
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
        """A1: phase-level progress - no per-draw callback instability."""
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

    # ─── KPI registry activation (v2.0 foundation, D.1) ─────────────────
    # Single source of truth для priors (sales / awareness / future KPIs).
    # Sales mode uses Trust 3 FROZEN values - no behavior change vs v1.0.16.
    from utils.kpi_registry import get_kpi_config
    kpi_type = config.get('kpi_type', 'sales')
    kpi_config = get_kpi_config(kpi_type)  # raises ValueError on unknown KPI

    # AUDIT-1 (post-D.1 hardening): explicit guard для KPI types beyond sales.
    # KPI_REGISTRY содержит awareness config (likelihood='logit_normal', ceiling,
    # baseline_drift), но modeler.py пока не реализует logit-Normal likelihood,
    # ceiling clipping, GaussianRandomWalk baseline drift. Awareness config
    # priors применятся, но likelihood останется Normal → silently broken model
    # (awareness data в [0, 100] обучатся как unbounded sales).
    # Phase A1a (PyMC integration) добавит full awareness support.
    if kpi_type != 'sales':
        return {
            'status': 'error',
            'error_code': 'KPI_TYPE_NOT_IMPLEMENTED',
            'message': (
                f"kpi_type='{kpi_type}' пока не поддержан в production. "
                f"KPI_REGISTRY содержит config, но likelihood/ceiling/baseline_drift "
                f"требуют Phase A1a integration (logit-Normal + RW baseline). "
                f"Сейчас доступен только kpi_type='sales'."
            ),
        }

    # ─── JAX backend enforcement (v2.0 foundation, D.2) ─────────────────
    # Weibull learnable adstock requires JAX/NumPyro (Toeplitz pt.scan на CPU = unbearable).
    # Sales mode без Weibull = no-op (all 'geometric' default).
    # AUDIT (post-D.2 hardening): also reject AURORA_NUTS_BACKEND=pymc + weibull -
    # JAX guard выше пропустит если jax установлен, но user мог форсировать pymc backend
    # через env var. PyTensor pt.scan + Toeplitz на CPU = unbearable MCMC time.
    from utils.backend_check import enforce_jax_for_weibull
    enforce_jax_for_weibull(adstock_config)  # raises BackendUnavailableError если Weibull без JAX
    _has_weibull = any(t == 'weibull' for t in adstock_config.values())
    if _has_weibull and os.environ.get('AURORA_NUTS_BACKEND', 'auto').lower() == 'pymc':
        return {
            'status': 'error',
            'error_code': 'WEIBULL_REQUIRES_JAX_BACKEND',
            'message': (
                "AURORA_NUTS_BACKEND=pymc + Weibull adstock = unbearable performance "
                "(Toeplitz pt.scan on CPU). Переключите AURORA_NUTS_BACKEND на 'auto' "
                "or 'numpyro', или поставьте все каналы на 'geometric'."
            ),
        }

    # Trust Level 3 (v1.1.0): channel_categories - brand / performance / mixed.
    # Если ≥2 канала в одной из brand/performance групп → hierarchical priors path.
    # Иначе fallback к single-prior path (backward compatible с v1.2 behavior).
    #
    # POST-AUDIT FIX: validate возвращает только explicit user entries (без auto-fill)
    # → pickle persists empty {} если user не assigned → pre-Trust3 проекты сохраняют
    # backward compat (decomposer применяет heuristic при decompose).
    # Per-channel vector для модели вычисляется через resolve_per_channel_categories.
    raw_categories = config.get('channel_categories', {}) or {}
    from utils.channel_categorization import (
        validate_categorization_for_hierarchical,
        is_hierarchical_eligible,
        resolve_per_channel_categories,
    )
    channel_categories, categorization_warnings = validate_categorization_for_hierarchical(
        raw_categories, media_cols
    )
    use_hierarchical = is_hierarchical_eligible(channel_categories)
    # Per-channel vector только используется in-model - не persists.
    per_channel_cats = resolve_per_channel_categories(channel_categories, media_cols)
    if categorization_warnings:
        for w in categorization_warnings:
            logger.warning(f'[Trust3 categorization] {w}')

    # Parse dates
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col])

    # ── v2.0.0 (ADR-019 §5): РФ holiday auto-injection ──
    # 12 hardcoded holidays auto-добавляются как control columns.
    # Customer customization (opt-out) откладывается в v2.2.0.
    # Existing user-supplied holidays preserved (no overwrite).
    holiday_cols_injected = []
    if date_col in df.columns:
        try:
            from utils.holiday_calendar_ru import generate_holiday_dummies, list_holiday_names
            holiday_df = generate_holiday_dummies(df[date_col])
            for hcol in holiday_df.columns:
                if hcol not in df.columns:  # preserve user-supplied
                    df[hcol] = holiday_df[hcol].values
                    holiday_cols_injected.append(hcol)
                    # Auto-add to control_cols если не included (it must be controlled out)
                    if hcol not in control_cols:
                        control_cols.append(hcol)
            if holiday_cols_injected:
                logger.info(f'Auto-injected {len(holiday_cols_injected)} РФ holiday dummies: '
                            f'{", ".join(holiday_cols_injected[:5])}{"..." if len(holiday_cols_injected) > 5 else ""}')
        except Exception as e:
            logger.warning('Holiday auto-injection skipped: %s', e)

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

    # Normalize media - Robyn-style spend/mean (P0-1/2/9 fix, math-fix-v1.0.13).
    # Pre-fix: z-score (X - mean) / std produced negative values that were clipped
    # at line 310 by pm.math.maximum(x, 0), silently dropping ~50% of data and
    # destroying response curve curvature. Result: scenario/optimizer/what-if
    # showed near-zero sensitivity to budget changes.
    # Post-fix: spend/mean keeps non-negative scale, gamma stays in [0,1] range.
    #
    # A1 fix (post-audit v1.2): track channels with zero training variance.
    # Pre-fix `replace(0, 1)` silently corrupted these - pickle stored mean=1,
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
    # media_stds removed - not used in spend/mean normalization

    # Normalize controls - критично: без этого большие контроли (price, budget) дают
    # огромный control_effect, y_pred улетает в ∞, R² получается астрономически отрицательным.
    # v2.0.0 audit fix (Backend H3): detect zero-variance control columns explicitly,
    # flag в untrained_controls для downstream visibility (vs silent divide-by-1).
    untrained_controls = []
    if len(control_cols) > 0:
        control_means = X_control.mean()
        control_stds_raw = X_control.std()
        # Identify zero-variance controls (would be degenerate features in model)
        for col in control_cols:
            if control_stds_raw[col] < 1e-10:
                untrained_controls.append(col)
                logger.warning(
                    'Control column %s has zero variance — will be degenerate в model '
                    '(coefficient unidentifiable, posterior = prior)', col,
                )
        control_stds = control_stds_raw.replace(0, 1)
        X_control_norm = (X_control - control_means) / control_stds
    else:
        control_means = pd.Series(dtype=float)
        control_stds = pd.Series(dtype=float)
        X_control_norm = pd.DataFrame()

    # ─────────────────────────────────────────────────────────────────────
    # v2.0.0 (ADR-019 §4): Signed factor categorization
    # ─────────────────────────────────────────────────────────────────────
    # Category-aware priors per Phase E2 real-data validation (RD-1 finding):
    #   - signed_competitor:
    #     * OTC pharma / категории с expanding market в season →
    #       prior N(μ=0, σ=0.3) symmetric (market не zero-sum)
    #     * FMCG / retail (fixed market, direct cannibalization) →
    #       prior N(μ=-0.3, σ=0.3) negative-leaning
    #     Default: symmetric (safer fallback — let data drive sign)
    #   - signed_price / signed_weather / signed_macro → prior mean 0 (signed)
    #   - holiday → prior mean 0 (event effect can be + or -)
    #   - positive control (distribution, trade) → prior mean +0.2 (lean positive)
    #
    # Source: tools/test_priors_real_data.py + PRIORS_VALIDATION_E2.md.
    # Validated на Кагоцел / Венарус / MMX Афала: competitor TRP correlates с
    # brand TRP +0.93 в OTC due к shared seasonal demand peak (cold/flu).
    # After search-query control variable — competitor coef → 0. Symmetric
    # prior recommended для OTC; negative-leaning preserved для FMCG.
    control_prior_mus = []  # list of prior means per control column
    control_kinds = []      # list of factor types для signed_factor_contributions

    # v2.0.0 Phase E2: detect kpi_type для category-aware competitor prior
    _kpi_type = config.get('kpi_type', 'sales')
    _is_otc_or_count = _kpi_type in ('sales_packs', 'leads', 'registrations',
                                       'subscriptions', 'loyalty_cards',
                                       'app_installs', 'count_custom', 'profit')
    # OTC pharma typical kpi=sales_packs. FMCG typical kpi=sales/revenue.
    # Heuristic: count KPI → likely OTC / pharma / expanding market → symmetric.
    # Customer may override через project config field 'competitor_prior_mu'.
    _competitor_mu_override = config.get('competitor_prior_mu')
    if _competitor_mu_override is not None:
        _competitor_mu = float(_competitor_mu_override)
    elif _is_otc_or_count:
        _competitor_mu = 0.0  # OTC / count KPI — expanding market, symmetric
    else:
        _competitor_mu = -0.3  # FMCG / monetary KPI — cannibalization assumption

    if len(control_cols) > 0:
        try:
            from utils.column_detection import classify_column
            for col in control_cols:
                kind = classify_column(col)
                control_kinds.append(kind)
                # Map kind → prior mean (sigma stays at 0.3 для backward compat)
                if kind == 'signed_competitor':
                    control_prior_mus.append(_competitor_mu)  # category-aware (Phase E2)
                elif kind in ('signed_price', 'signed_weather', 'signed_macro'):
                    control_prior_mus.append(0.0)   # unconstrained signed
                elif kind == 'holiday':
                    control_prior_mus.append(0.0)   # holiday effect can be either sign
                elif kind == 'control':
                    # Positive controls (distribution, trade_activity, promo) — lean positive
                    control_prior_mus.append(0.2)
                else:
                    # 'unknown' kind — true fallback, uninformative zero-centered prior
                    # (data will dominate). Avoid 0.2 «lean positive» bias on unrecognized.
                    control_prior_mus.append(0.0)
            logger.info(
                'v2.0.0 priors: competitor_mu=%.2f (KPI=%s, category=%s)',
                _competitor_mu, _kpi_type,
                'OTC/count' if _is_otc_or_count else 'FMCG/monetary',
            )
        except Exception as e:
            logger.warning('Signed factor classification fallback: %s — using uniform mu=0', e)
            control_prior_mus = [0.0] * len(control_cols)
            control_kinds = ['unknown'] * len(control_cols)

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
            # Priors - tightened 2026-04-19 to fix NUTS funnel / divergences on small data.
            # Previous priors (Gamma(3,1) for alpha, Beta(2,2) for gamma, HalfNormal(0.5) for beta)
            # created poorly identified Hill saturation geometry → 1600+ divergences.
            intercept = pm.Normal('intercept', mu=0, sigma=0.5)  # было sigma=1

            # Media coefficients - более консервативный HalfNormal, меньший разброс.
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
            elif use_hierarchical:
                # Trust Level 3: hierarchical brand vs performance priors.
                # Group-conditional sigma - brand wider (HalfNormal 0.7) accommodate
                # long-horizon brand effects, performance tighter (HalfNormal 0.3).
                # Non-centered z reparameterization (Critical Audit issue C) avoids funnel.
                # Math: HalfNormal(σ) = σ · HalfNormal(1) by scale invariance.
                # Sampling z ~ HalfNormal(1) и computing β = σ_group × z decouples
                # σ↔β posterior geometry - flat surface, NUTS converges robustly на small N.
                import pytensor.tensor as pt
                brand_sigma = pm.HalfNormal('brand_sigma', sigma=kpi_config.brand_beta_sigma)
                perf_sigma = pm.HalfNormal('perf_sigma', sigma=kpi_config.perf_beta_sigma)
                mixed_sigma = pm.HalfNormal('mixed_sigma', sigma=kpi_config.mixed_beta_sigma)
                # Map per-channel category → group sigma reference (Python list comprehension).
                _sigma_lookup = {'brand': brand_sigma, 'performance': perf_sigma, 'mixed': mixed_sigma}
                sigma_vec = pt.stack([_sigma_lookup[cat] for cat in per_channel_cats])
                media_betas_z = pm.HalfNormal('media_betas_z', sigma=1.0, shape=len(media_cols))
                media_betas = pm.Deterministic('media_betas', sigma_vec * media_betas_z)
            else:
                media_betas = pm.HalfNormal('media_betas', sigma=0.3, shape=len(media_cols))  # было 0.5

            # Control coefficients (используем нормализованные X_control_norm)
            # v2.0.0 (ADR-019 §4): per-column prior mean based on factor type
            # (competitor=negative-leaning, signed=zero, positive_control=lean+).
            # Sigma=0.3 retained для backward compat (Phase E2 math review).
            if len(control_cols) > 0:
                import numpy as _np
                _control_mu_array = _np.array(control_prior_mus, dtype=float)
                control_betas = pm.Normal(
                    'control_betas',
                    mu=_control_mu_array,
                    sigma=0.3,
                    shape=len(control_cols),
                )
                control_effect = pm.math.dot(X_control_norm.values.astype(float), control_betas)
            else:
                control_effect = 0

            # Hill saturation - жёстче priors для стабильной geometry
            # alpha ≈ 1-2 (типичный saturation shape), Gamma(5, 3) имеет mean=1.67, var=0.56
            alphas = pm.Gamma('alphas', alpha=5, beta=3, shape=len(media_cols))  # было Gamma(3, 1) mean=3
            # gamma - half-point of saturation, концентрируемся около 0.5
            gammas = pm.Beta('gammas', alpha=kpi_config.gammas_alpha, beta=kpi_config.gammas_beta, shape=len(media_cols))  # KPI registry - sales=Beta(3,3) FROZEN

            # ─────────────────────────────────────────────────────────────────
            # Phase 1.1 - hierarchical adstock decay (logit-normal parameterization)
            # ─────────────────────────────────────────────────────────────────
            # Pilot validated logit-normal vs Beta-Beta (docs/PHASE_1_1_PILOT_RESULTS.md):
            # logit-normal 35% faster, R-hat 1.000 vs 1.020, ESS 5× better.
            # Hyperprior calibration per ADR §3.A1 + A2 (monthly data, mean ~0.20).
            # Non-centered z parameterization avoids funnel geometry on small N.
            import pytensor.tensor as pt
            from pytensor.scan import scan as pt_scan

            adstock_sigma_logit = pm.HalfNormal('adstock_sigma_logit', sigma=1.0)
            adstock_z = pm.Normal('adstock_z', mu=0.0, sigma=1.0, shape=len(media_cols))
            if use_hierarchical:
                # Trust Level 3: group-conditional decay mu.
                # Brand: mu_logit ~ Normal(0.7, 0.3) → sigmoid ≈ 0.67 → ~12 wk effective half-life.
                # Performance: mu_logit ~ Normal(-1.4, 0.7) → sigmoid ≈ 0.20 → ~1.3 wk half-life.
                # Mixed: same prior shape как single-prior path - semantic compat.
                _b_mu, _b_sg = kpi_config.brand_mu_logit_prior
                _p_mu, _p_sg = kpi_config.perf_mu_logit_prior
                _m_mu, _m_sg = kpi_config.mixed_mu_logit_prior
                brand_mu_logit = pm.Normal('brand_mu_logit', mu=_b_mu, sigma=_b_sg)
                perf_mu_logit = pm.Normal('perf_mu_logit', mu=_p_mu, sigma=_p_sg)
                mixed_mu_logit = pm.Normal('mixed_mu_logit', mu=_m_mu, sigma=_m_sg)
                _mu_lookup = {'brand': brand_mu_logit, 'performance': perf_mu_logit, 'mixed': mixed_mu_logit}
                mu_vec = pt.stack([_mu_lookup[cat] for cat in per_channel_cats])
                adstock_decay = pm.Deterministic(
                    'adstock_decay',
                    pm.math.sigmoid(mu_vec + adstock_sigma_logit * adstock_z),
                )
            else:
                # Single-prior path - fallback к performance-style decay (соответствует kpi_config.perf_mu_logit_prior).
                _sp_mu, _sp_sg = kpi_config.perf_mu_logit_prior
                adstock_mu_logit = pm.Normal('adstock_mu_logit', mu=_sp_mu, sigma=_sp_sg)
                adstock_decay = pm.Deterministic(
                    'adstock_decay',
                    pm.math.sigmoid(adstock_mu_logit + adstock_sigma_logit * adstock_z),
                )

            # Saturated media effect - Phase 1.1 per-channel scan-based adstock with sampled decay.
            # Geometric channels: scan-based recursive adstock with per-sample decay.
            # Weibull channels: pre-computed (decay sampling deferred to Phase 1.5).
            #
            # C1 fix (2026-04-26 audit): normalize on adstock_full.mean() per draw -
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
            sigma = pm.HalfNormal('sigma', sigma=kpi_config.obs_sigma_prior)  # KPI registry - sales=0.3 FROZEN
            pm.Normal('obs', mu=mu, sigma=sigma, observed=y_norm)

            # A1: report sampling start - pct stays at 25 during 3-15 min MCMC
            # elapsed timer in UI shows progress is alive
            report('sampling', pct=25)

            # ───────────────────────────────────────────────────────────────
            # Tier-based MCMC sampling с fallback (v1.0.9)
            # ───────────────────────────────────────────────────────────────
            # Tier-1: NumPyro NUTS (JAX JIT + vectorized chains) - 5-15× быстрее.
            # Tier-2: PyTensor NUTS (cores=1) - стабильный, но 3-5× медленнее.
            # Full fail: honest RuntimeError с кодом MMM_SAMPLER_EXHAUSTED.
            #
            # Metropolis НЕ используется как Tier-3 fallback - на MMM с
            # Adstock/Hill он даёт r_hat > 2.0 (ложный зелёный результат
            # опаснее честного fail).
            #
            # Fallback Tier-1 → Tier-2 ТОЛЬКО на `functools.partial` ошибке
            # (известный PyMC 5 + JAX JIT bug для custom Deterministic).
            # Другие ошибки (плохие данные, numerical issues) не маскируем
            # медленным backend'ом - Tier-2 даст ту же ошибку за 10 минут.
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
                        f'MCMC backend: NumPyro NUTS (JAX) - '
                        f'numpyro={numpyro.__version__}, jax={jax.__version__}'
                    )
                except ImportError:
                    if _backend == 'numpyro':
                        raise RuntimeError(
                            'AURORA_NUTS_BACKEND=numpyro but NumPyro/JAX not installed'
                        )
                    logger.warning('NumPyro/JAX not available - using PyTensor NUTS')

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
                            f'({str(e)[:150]}) - falling back to Tier-2 PyTensor NUTS'
                        )
                        _sampling_errors.append(('numpyro', f'partial bug: {str(e)[:200]}'))
                        trace = None
                    else:
                        # Другая AttributeError - не маскируем медленным fallback'ом
                        raise
                except Exception as e:
                    # Non-partial errors (bad data, numerical issues) - instant fail,
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

            # ── Full fail: honest error (NO Metropolis - даёт r_hat > 2) ──
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
        hierarchical_rhat_warning: str | None = None
        # FIX 2026-05-02: hierarchical_priors_summary initialized EARLY чтобы избежать
        # UnboundLocalError в diagnostics block (line ~810). Было: defined только
        # в posterior extraction (line ~852), но diagnostics использует на line 810
        # → UnboundLocalError при use_hierarchical=True. Re-populated в posterior
        # extraction блок ниже когда trace доступен.
        hierarchical_priors_summary: dict[str, float] = {}
        try:
            import arviz as az
            summary = az.summary(trace)
            r_hat_values = summary['r_hat'].values.tolist()
            # C1: filter to key params only (intercept, sigma, media_betas[i])
            key_params = {'intercept', 'sigma'} | {f'media_betas[{i}]' for i in range(len(media_cols))}
            # Trust Level 3: hierarchical hyperparameters также важны (issue L).
            if use_hierarchical:
                key_params |= {
                    'brand_sigma', 'perf_sigma', 'mixed_sigma',
                    'brand_mu_logit', 'perf_mu_logit', 'mixed_mu_logit',
                }
            for param in summary.index:
                if param in key_params:
                    per_param_rhat[param] = round(float(summary.loc[param, 'r_hat']), 4)
            # Hierarchical hyperparameter gate - silently broken model prevention.
            if use_hierarchical:
                hyper_names = ['brand_sigma', 'perf_sigma', 'brand_mu_logit', 'perf_mu_logit']
                hyper_rhats = [per_param_rhat[n] for n in hyper_names if n in per_param_rhat]
                if hyper_rhats and max(hyper_rhats) > 1.05:
                    over_threshold = {n: per_param_rhat[n] for n in hyper_names if per_param_rhat.get(n, 0) > 1.05}
                    hierarchical_rhat_warning = (
                        f'Hierarchical hyperparameters did not converge: {over_threshold}. '
                        f'Consider increasing tune/draws or revert к single-prior path '
                        f'(set channel_categories = {{}} or pin all каналы to mixed).'
                    )
                    logger.warning(f'[Trust3 R-hat gate] {hierarchical_rhat_warning}')
        except Exception:
            pass

        r_hat_max = max(r_hat_values) if r_hat_values else 1.0
        divergences = int(trace.sample_stats['diverging'].sum()) if hasattr(trace, 'sample_stats') else 0

        # Posterior predictions - reconstructed from posterior means directly.
        # Причина: pm.sample_posterior_predictive на модели с Hill saturation
        # рекомпилирует PyTensor graph для каждого posterior draw (4×2000 = 8000),
        # что даёт 13+ минут на Windows без native C compiler (PyTensor Python mode).
        # Manual reconstruction из posterior means математически эквивалентна
        # `E[posterior_predictive].mean(chain,draw)` при нулевом observation noise,
        # а расхождение из-за sigma-noise усредняется к нулю на 8000 draws.
        # Downstream (decomposer/optimizer) НЕ читает trace.posterior_predictive -
        # только y_pred_norm нужен для диагностики y_pred vs actual.
        y_pred_norm = None
        try:
            import numpy as _np
            intercept_mean = float(trace.posterior['intercept'].mean(dim=['chain', 'draw']).values)
            media_betas_mean = trace.posterior['media_betas'].mean(dim=['chain', 'draw']).values
            alphas_mean = trace.posterior['alphas'].mean(dim=['chain', 'draw']).values
            gammas_mean = trace.posterior['gammas'].mean(dim=['chain', 'draw']).values

            # Reconstruct Hill-saturated predictions using posterior means
            # (using X_media_norm - same transformation as inside pm.Model)
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

            # Control effect (используем нормализованные контроли - так же как внутри pm.Model)
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
        # Trust Level 3: hierarchical metadata for UI display.
        if use_hierarchical:
            diagnostics['hierarchical'] = {
                'enabled': True,
                'channel_categories': dict(channel_categories),
                'categorization_warnings': list(categorization_warnings),
                'rhat_warning': hierarchical_rhat_warning,
                'priors_summary': hierarchical_priors_summary,
            }
        else:
            diagnostics['hierarchical'] = {'enabled': False}
        # MCMC config - needed by UI to give context-aware divergence advice
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
        # Shape convention: (n_channels, n_samples) - samples[i, :] = all draws for channel i.
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
        # Shape (n_channels, n_samples) - same as alphas/gammas. Used by downstream
        # decomposer/scenario/optimizer for honest mROAS CI through adstock chain.
        # Trust Level 3: hierarchical model uses brand_mu_logit/perf_mu_logit/mixed_mu_logit
        # вместо single adstock_mu_logit. Extract per-group для diagnostics + methodology.
        # NOTE: hierarchical_priors_summary initialized earlier (line ~701) - re-populated here.
        try:
            adstock_decay_samples = np.asarray(
                trace.posterior['adstock_decay'].stack(sample=('chain', 'draw')).values, dtype=np.float32
            )
            adstock_decay_means = trace.posterior['adstock_decay'].mean(dim=['chain', 'draw']).values.tolist()
            adstock_sigma_logit_mean = float(trace.posterior['adstock_sigma_logit'].mean().values)
            if use_hierarchical:
                # Trust Level 3: brand/perf/mixed mu_logit - group-conditional posteriors.
                for group in ('brand', 'performance', 'mixed'):
                    var_name = f'{group if group != "performance" else "perf"}_mu_logit'
                    if var_name in trace.posterior:
                        hierarchical_priors_summary[f'{group}_mu_logit_mean'] = float(
                            trace.posterior[var_name].mean().values
                        )
                    sigma_name = f'{group if group != "performance" else "perf"}_sigma'
                    if sigma_name in trace.posterior:
                        hierarchical_priors_summary[f'{group}_sigma_mean'] = float(
                            trace.posterior[sigma_name].mean().values
                        )
                # Backward-compat: keep adstock_mu_logit_mean field - average over channels' implied mu.
                adstock_mu_logit_mean = float(np.mean([
                    hierarchical_priors_summary.get(f'{g}_mu_logit_mean', -1.4)
                    for g in ('brand', 'performance', 'mixed')
                    if f'{g}_mu_logit_mean' in hierarchical_priors_summary
                ]) if hierarchical_priors_summary else -1.4)
            else:
                adstock_mu_logit_mean = float(trace.posterior['adstock_mu_logit'].mean().values)
        except KeyError:
            # Defensive: if model didn't include adstock_decay (shouldn't happen post Phase 1.1),
            # fall back to default 0.5 per channel for backward compat with v1.1.5 readers.
            logger.warning("adstock_decay not in trace - falling back to defaults (v1.1.5 compat)")
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
        # ROI/mROAS CI propagation chain involves all four params via Hill saturation -
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
            # Per-channel AND aggregation - pass только если все доступные params выше threshold.
            tail_ess_ok_per_channel = []
            for i in range(len(media_cols)):
                ok = True
                for vname, ess_arr in ess_per_param.items():
                    try:
                        if i < len(ess_arr) and float(ess_arr[i]) < tail_ess_threshold:
                            ok = False
                            break
                    except (IndexError, ValueError, TypeError):
                        # Defensive - ambiguous result treated as ok (don't block training)
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
        # posterior means + normalization - not the raw trace or model graph.
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
                # v2.0.0 (ADR-019 §4): control factor kinds для signed_factor_contributions
                # mapping в decomposer (без re-classify). Same order как control_cols.
                'control_kinds': control_kinds,
                # v2.0.0 (ADR-019 §5): holidays auto-injected at training time.
                # Used для backtest exclusion (holidays known) + provenance.
                'holiday_cols_injected': holiday_cols_injected,
                # v2.0.0: prior means used per control factor (placeholder per B4).
                'control_prior_mus': control_prior_mus,
                # v2.0.0 audit fix (Backend H3): zero-variance controls flagged
                # для downstream consistency — coefficients unidentifiable.
                'untrained_controls': untrained_controls,
            },
            # Phase 1.9: persist full posterior draws for honest uncertainty quantification.
            # Joint structure preserves per-draw correlation between alpha/gamma/beta of same channel.
            # Storage: ~864 KB for n=36 × 7 channels × 8000 draws × float32 - negligible vs PyMC pickle overhead.
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
            # Schema versions:
            # 1.2 - Phase 1.1 hierarchical adstock decay (single hyperprior)
            # 1.3 - Trust Level 3: brand vs performance split (channel_categories field)
            #       + group-conditional decay mu (brand_mu_logit, perf_mu_logit, mixed_mu_logit)
            #       + group-conditional sigma (brand_sigma, perf_sigma, mixed_sigma)
            'model_version': '1.3' if use_hierarchical else '1.2',
            # Trust Level 3: persist actual categorization (after identifiability validation,
            # may differ from raw user input если N=1 group → demoted к mixed).
            # Backward-compat: empty {} означает «user не assigned» → decomposer применяет heuristic.
            # Filled values represent EXPLICIT user choices (NOT auto-fills) - single source of truth.
            'channel_categories': dict(channel_categories),
            'categorization_warnings': list(categorization_warnings),
            'use_hierarchical': bool(use_hierarchical),
            # Group-level hyperparameter posterior means (для methodology auto-gen).
            # Empty dict for non-hierarchical models.
            'hierarchical_priors': hierarchical_priors_summary,
            'y_actual': y.tolist(),
            'y_predicted': y_pred.tolist(),
            # Sprint 3 ADR §11/Q4 refinement: optional hint к причинному артефакту
            # в same project. Backward-compat: legacy readers ignore via .get().
            # MMM model lifecycle independent от causal artifact (refresh causal experiment
            # не invalidates MMM training), but UI knows where to look для combined view.
            'causal_artifact_path': None,
            # ─── v2.0 foundation top-level fields (D.1 KPI activation) ──────
            # Sales mode → identical pickle structurally (model_version stays 1.2/1.3),
            # но top-level kpi_type/kpi_likelihood explicitly persisted для downstream
            # persistence.get_kpi_type() / is_awareness_model() без digging в config.
            # Pre-v2.0 readers ignore via .get() (backward-compat preserved).
            'kpi_type': kpi_type,
            'kpi_likelihood': kpi_config.likelihood,
            'channel_adstock_types': dict(adstock_config),
        }

        # ─── Phase 2 (Planning Mode) at-fit-time persistence ───
        # Audit pass 2 2026-05-02: persist granularity + x_norm quantiles +
        # seasonality detection so planning mode requests skip lazy inference
        # (G2 still handles legacy v1.3 pickles; new pickles are pre-computed).
        try:
            from utils.forecast_validation import (
                compute_x_norm_quantiles,
                detect_granularity,
                detect_seasonality,
            )
            # Granularity (peek date column directly here - already loaded df).
            if date_col in df.columns:
                gran_result = detect_granularity(df[date_col])
                if gran_result['confidence'] >= 0.4:
                    model_data['training_granularity'] = gran_result['granularity']
            # x_norm quantiles per channel - recompute from raw spend × decay
            # posterior mean (matches optimizer.py:496 fallback chain semantics).
            from utils.adstock import apply_adstock as _apply_adstock_fit
            quantiles_per_channel: dict[str, dict[str, float]] = {}
            for i, col in enumerate(media_cols):
                if col not in df.columns:
                    continue
                raw = df[col].fillna(0).values.astype(float)
                if raw.size == 0:
                    continue
                decay_pt = float(adstock_decay_means[i]) if i < len(adstock_decay_means) else 0.5
                a_type = adstock_config.get(col, 'geometric')
                try:
                    adstock_series = _apply_adstock_fit(raw, a_type, {'alpha': decay_pt})
                except Exception:
                    continue
                mean = adstock_means_posterior.get(col)
                if mean is None or mean <= 0:
                    mean = float(media_means.get(col, 1.0) or 1.0)
                if mean <= 0:
                    continue
                quantiles_per_channel[col] = compute_x_norm_quantiles(adstock_series, mean)
            if quantiles_per_channel:
                model_data['train_x_norm_quantiles'] = quantiles_per_channel
            # Seasonality detection on y_actual (training KPI series).
            granularity_for_season = model_data.get('training_granularity') or 'W'
            season_result = detect_seasonality(y, granularity=granularity_for_season)
            model_data['seasonality_detected'] = season_result  # dict | None
        except Exception as _phase2_persist_err:
            # Non-fatal - pre-Phase-2 fields will lazy-inferred at load time.
            logger.warning(
                f"Phase 2 at-fit-time persistence failed: {_phase2_persist_err}. "
                f"Legacy inference helpers will fill on demand."
            )

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

        # v2.1.0: безопасный формат aurora-model (zip + JSON + npz).
        # Заменяет pickle.dump — устраняет RCE-surface при load malicious моделей.
        # SH-AM-11: project_lock защищает от race условий с save_v20_diagnostics /
        # clear_sensitivity_cache, которые могут вызываться параллельно.
        from engines.persistence_safe import save_model_safe
        from engines.persistence import write_pkl_sha256_sidecar
        from utils.file_lock import project_lock
        with project_lock(Path(project_dir), timeout=10.0):
            save_model_safe(model_data, model_path)
            write_pkl_sha256_sidecar(model_path)

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
        # MMM_SAMPLER_EXHAUSTED - honest error из triple fallback, с деталями
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
        # но возможно - например, в save/pickle). Диагностика для поддержки.
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
