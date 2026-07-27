"""
OLS modeler - small-data fallback engine (Sprint 2 / A1).

For datasets with n < 30 observations, Bayesian MCMC is unreliable:
posterior intervals don't converge, R-hat stays > 1.05, Hill alpha/gamma
parameters become unidentifiable. Robyn/LightweightMMM/PyMC-Marketing all
require n ≥ 50.

This engine provides honest fallback for small-N case:
- adstock + Hill applied with **fixed library defaults** (no per-channel learning)
- Closed-form OLS regression on hill-saturated features → β coefficients
- Predictive intervals (residual-based + jackknife) on y forecasts - NOT posterior CI on parameters
- Honest disclosure: "model trained on small data, β has wide bounds, treat as directional"

Schema:
- model_version='1.0-ols' (distinguishes from Bayesian v1.1+)
- channel_params: beta (from OLS), alpha=1.5, gamma=0.5, decay=0.5 (defaults - NOT learned)
- normalization: same as Bayesian (media_means + y_mean/std + control stats)
- ols_diagnostics: r_squared, adj_r_squared, mape, residual_std, n_obs, n_params, dof
- predictive_intervals: per-period stat for honest y CI

Downstream engines (decomposer/optimizer/scenario) treat '1.0-ols' pickle same
as v1.1 (point estimates only, no posterior CI). Migration banner in decomposer
will tell user "OLS-режим: CI на ROI недоступны (нужен n≥30 для Bayesian)".

Math reference:
- OLS: β = (X'X)^(-1) X'y, residual_std = sqrt(SSR / (n - p - 1))
- Predictive interval: ŷ ± t_{n-p-1, α/2} · σ · sqrt(1 + h_ii)
  where h_ii = leverage of i-th observation
- For new prediction: ŷ_new ± t · σ · sqrt(1 + x_new'(X'X)^(-1)x_new)

Used when: config['mode'] == 'ols' OR auto-recommend (n < threshold).
"""
from __future__ import annotations

import json
import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Library defaults for non-learnable params on small N (consistent with v1.1.5 fallback).
DEFAULT_ALPHA = 1.5      # Hill steepness - moderate S-curve
DEFAULT_GAMMA = 0.5      # Hill half-saturation point
DEFAULT_DECAY = 0.5      # Geometric adstock retention rate


def train_ols(config: dict, project_dir: str, progress_callback=None) -> dict[str, Any]:
    """Train OLS small-data fallback model.

    Args:
        config: same shape as Bayesian train_model:
            data_file, kpi_column, media_columns, control_columns,
            date_column, adstock_config, unit_costs.
        project_dir: project directory (saves models/latest.pkl + latest-params.json + diagnostics)
        progress_callback: optional fn(dict) for UI

    Returns:
        JSON-serializable result with diagnostics + status.
    """
    def report(phase: str, pct: int = 0, **_):
        if progress_callback:
            try:
                progress_callback({'phase': phase, 'pct': pct})
            except Exception:
                pass

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
    # Аудит 2026-07-10 (High): хвост-медиаплан (KPI пуст) без фильтра уходил бы
    # в fillna(0) → обучение на фейковых нулевых продажах при ненулевых тратах.
    # Инвариант: файл без хвоста → no-op. Симметрично modeler.py.
    if kpi_col in df.columns:
        df = df[df[kpi_col].notna()].reset_index(drop=True)
    media_cols = config['media_columns']
    control_cols = config.get('control_columns', [])
    adstock_config = config.get('adstock_config', {}) or {}

    # Аудит 2026-07-04: OLS-путь Фурье-сезонность не инжектит (упрощённый движок),
    # но config байесовской модели несёт season_fourier_* в control_columns
    # (backtest mode='ols' окна / переключение движка) — в сыром файле их нет,
    # df[control_cols] упал бы KeyError. Фильтруем runtime-колонки честно.
    from utils.fourier_seasonality import FOURIER_COL_PREFIX as _FOURIER_PREFIX
    _fourier_dropped = [c for c in control_cols if str(c).startswith(_FOURIER_PREFIX)]
    if _fourier_dropped:
        control_cols = [c for c in control_cols if c not in _fourier_dropped]
        logger.info(
            'OLS: %d Фурье-контролей сезонности исключены (OLS без сезонной '
            'компоненты; байесовский режим учитывает её).', len(_fourier_dropped),
        )

    if kpi_col not in df.columns:
        return {'status': 'error', 'message': f'KPI column "{kpi_col}" not found'}

    # Apply merge_rules if any
    from utils.merge_rules import apply_merge_rules
    apply_merge_rules(df, config.get('merge_rules'))

    y = df[kpi_col].fillna(0).values.astype(float)
    # E2 (2026-07-03, D-E2-4): калибровка lift-тестами живёт в правдоподобии
    # байесовской модели — у OLS вероятностной модели вкладов нет.
    if config.get('calibrations'):
        return {
            'status': 'error',
            'error_code': 'CALIBRATION_REQUIRES_BAYESIAN',
            'message': (
                'Калибровка lift-тестами доступна только байесовскому режиму. '
                'Переключите движок на Bayesian или уберите калибровки.'
            ),
        }

    n_obs = len(y)

    if n_obs < 8:
        return {
            'status': 'error',
            'error_code': 'INSUFFICIENT_DATA',
            'message': (
                f'Слишком мало наблюдений (n={n_obs}). OLS-режиму нужно минимум 8 '
                f'периодов. Соберите больше данных или добавьте каналов.'
            ),
        }

    n_params = len(media_cols) + len(control_cols) + 1  # +1 intercept
    if n_obs <= n_params + 1:
        return {
            'status': 'error',
            'error_code': 'OVERPARAMETERIZED',
            'message': (
                f'Параметров больше чем наблюдений (n={n_obs}, p={n_params}). '
                f'OLS не имеет степеней свободы. Уберите каналы или соберите больше данных.'
            ),
        }

    report('preprocessing', pct=30)

    # ── Apply adstock + Hill with library defaults ──
    from utils.adstock import apply_adstock
    from utils.saturation import hill_function

    media_means = {}
    untrained_channels = []
    # H3 fix (audit 2026-04-26): build feature matrix только для trained channels.
    # Pre-fix: untrained channels (zero variance) добавлялись как zero column в X →
    # OLS computed β для них (small spurious signal от noise correlation). Post-fix:
    # exclude untrained from X completely + persist channel order для downstream mapping.
    trained_media_cols = []
    trained_features = []

    # v2.1.0 (ADR-020): unit_costs apply симметрично с Bayesian modeler.
    unit_costs_cfg = config.get('unit_costs') or {}
    unit_costs_snapshot: dict[str, float] = {}

    for j, col in enumerate(media_cols):
        a_type = adstock_config.get(col, 'geometric')
        raw_x = df[col].fillna(0).values.astype(float)
        uc = float(unit_costs_cfg.get(col, 1.0) or 1.0)
        if uc > 0 and uc != 1.0:
            raw_x = raw_x * uc
            unit_costs_snapshot[col] = uc
        adstocked = apply_adstock(raw_x, a_type, {'alpha': DEFAULT_DECAY})
        mean_j = float(adstocked.mean())
        if mean_j == 0:
            untrained_channels.append(col)
            media_means[col] = 1.0  # safety value for downstream divisions
            continue  # H3: don't add to X
        x_norm = adstocked / max(mean_j, 1e-10)
        feat = hill_function(np.maximum(x_norm, 0), DEFAULT_ALPHA, DEFAULT_GAMMA)
        trained_features.append(feat)
        trained_media_cols.append(col)
        media_means[col] = mean_j

    if not trained_media_cols:
        return {
            'status': 'error',
            'error_code': 'NO_TRAINED_CHANNELS',
            'message': (
                'Все media-каналы имели нулевую вариативность в данных обучения. '
                'OLS не может построить модель - соберите данные с реальной spend variation.'
            ),
            'untrained_channels': untrained_channels,
        }
    X_features = np.column_stack(trained_features)

    # Controls: z-score standardize (same as Bayesian)
    if control_cols:
        X_control_raw = df[control_cols].fillna(0).astype(float).values
        control_means = X_control_raw.mean(axis=0)
        control_stds = X_control_raw.std(axis=0)
        control_stds_safe = np.where(control_stds > 1e-9, control_stds, 1.0)
        X_control_norm = (X_control_raw - control_means) / control_stds_safe
    else:
        X_control_norm = np.zeros((n_obs, 0))
        control_means = np.array([])
        control_stds = np.array([])
        control_stds_safe = np.array([])

    # Combine: [intercept, media features, control features]
    X = np.column_stack([np.ones(n_obs), X_features, X_control_norm])
    p = X.shape[1]  # n_params + 1 intercept

    # y normalize (same as Bayesian для consistency)
    y_mean = float(y.mean())
    y_std = max(float(y.std()), 1e-10)
    y_norm = (y - y_mean) / y_std

    report('fitting', pct=50)

    # ── OLS via numpy.linalg.lstsq (closed form, stable) ──
    try:
        beta_hat, residuals, rank, sv = np.linalg.lstsq(X, y_norm, rcond=None)
    except np.linalg.LinAlgError as e:
        return {
            'status': 'error',
            'error_code': 'OLS_SINGULAR',
            'message': f'OLS regression singular: {e}. Возможно multicollinearity между каналами.',
        }

    # Predictions in normalized scale
    y_pred_norm = X @ beta_hat
    residual_norm = y_norm - y_pred_norm

    # Denormalize for reporting
    y_pred = y_pred_norm * y_std + y_mean

    # ── Diagnostics ──
    ss_total = float(np.sum((y_norm - y_norm.mean()) ** 2))
    ss_residual = float(np.sum(residual_norm ** 2))
    r_squared = max(0.0, min(1.0, 1.0 - ss_residual / max(ss_total, 1e-10)))
    dof = max(n_obs - p, 1)
    adj_r_squared = 1.0 - (1.0 - r_squared) * (n_obs - 1) / dof
    residual_std_norm = float(np.sqrt(ss_residual / dof))
    residual_std = residual_std_norm * y_std  # back to original units
    mape = float(np.mean(np.abs((y - y_pred) / np.maximum(np.abs(y), 1e-10))) * 100)

    # Coefficient std errors (frequentist OLS): se(β) = sqrt(diag(σ² (X'X)^(-1)))
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
        beta_se_norm = np.sqrt(np.diag(XtX_inv) * (ss_residual / dof))
    except np.linalg.LinAlgError:
        beta_se_norm = np.full(p, np.nan)

    # Extract β per channel (skip intercept at index 0).
    # H3 fix: media_betas length = trained_media_cols (untrained excluded from X).
    intercept_norm = float(beta_hat[0])
    n_trained = len(trained_media_cols)
    media_betas = beta_hat[1:1 + n_trained]
    control_betas = beta_hat[1 + n_trained:]
    media_betas_se = beta_se_norm[1:1 + n_trained]

    # Frequentist t-critical: imported once at module top (stylistic improvement)
    try:
        from scipy import stats as scipy_stats
        t_crit = float(scipy_stats.t.ppf(0.95, dof))
    except Exception:
        t_crit = 1.645  # fallback к large-sample normal

    # ── Sprint 2 extension (small-data path): bootstrap ROI CI + OLS diagnostics ──
    # Closes gap "у OLS только β CI, не ROI CI" - bootstrap дает honest ROI distribution.
    # Computed once at training time, stored в pickle для downstream consumption.
    # C-OLS-1: pass raw_spend_series + adstock_config для real per-period contribution
    # computation (matches decomposer math exactly - eliminates Jensen approximation bias).
    raw_spend_totals_dict = {}
    raw_spend_series_dict = {}
    for col in trained_media_cols:
        col_arr = df[col].fillna(0).values.astype(float)
        raw_spend_totals_dict[col] = float(col_arr.sum())
        raw_spend_series_dict[col] = col_arr

    bootstrap_roi_results = {}
    ols_diag_results = {}
    conformal_pi = None
    try:
        # S-OLS-1 audit synergy (2026-04-27): conformal prediction для distribution-free
        # guaranteed-coverage PI на y forecasts. Aurora marketing differentiator -
        # никто из MMM-tools не имеет conformal prediction. Auto-selects jackknife+
        # (n<30) или split-conformal (n≥30) для optimal small-data behavior.
        from utils.conformal import conformal_intervals_auto
        conformal_pi = conformal_intervals_auto(X, y_norm, confidence=0.9, seed=42)
    except Exception as _conf_err:
        logger.warning(
            f"Conformal PI computation failed (continuing without): "
            f"{type(_conf_err).__name__}: {_conf_err}"
        )

    try:
        from utils.ols_bootstrap import bootstrap_roi_ci, ols_diagnostics
        bootstrap_roi_results = bootstrap_roi_ci(
            X=X, y=y_norm,
            media_means={c: media_means[c] for c in trained_media_cols},
            media_cols=trained_media_cols,
            y_std=y_std,
            n_periods=n_obs,
            raw_spend_totals=raw_spend_totals_dict,
            raw_spend_series=raw_spend_series_dict,
            adstock_config=adstock_config,
            unit_costs=config.get('unit_costs', {}),
            n_boot=200,
            seed=42,
        )
        ols_diag_results = ols_diagnostics(X, y_norm, beta_hat, XtX_inv if 'XtX_inv' in dir() else None)
    except Exception as _boot_err:
        logger.warning(
            f"Bootstrap ROI CI / OLS diagnostics failed (continuing without): "
            f"{type(_boot_err).__name__}: {_boot_err}"
        )

    # Build channel_params (compatible с decomposer/optimizer expectations).
    # All media_cols enumerated так что downstream sees все каналы - untrained
    # marked explicit с beta=0 + flag.
    channel_params = {}
    trained_set = set(trained_media_cols)
    for col in media_cols:
        if col not in trained_set:
            # Untrained channel: explicit zero β + flag so downstream skip
            channel_params[col] = {
                'beta': 0.0,
                'alpha': DEFAULT_ALPHA,
                'gamma': DEFAULT_GAMMA,
                'adstock': {'type': adstock_config.get(col, 'geometric')},
                'decay': DEFAULT_DECAY,
                'tail_ess_ok': True,
                'beta_se': None,
                'beta_ci_low_freq': 0.0,
                'beta_ci_high_freq': 0.0,
                'untrained': True,
            }
            continue
        j = trained_media_cols.index(col)
        beta_ci_half = t_crit * float(media_betas_se[j]) if not np.isnan(media_betas_se[j]) else 0.0
        ch_dict = {
            'beta': round(float(media_betas[j]), 4),
            'alpha': DEFAULT_ALPHA,
            'gamma': DEFAULT_GAMMA,
            'adstock': {'type': adstock_config.get(col, 'geometric')},
            'decay': DEFAULT_DECAY,
            'tail_ess_ok': True,  # OLS doesn't have ESS - always True
            # Phase 1.9-style CI fields (frequentist analog)
            'beta_se': round(float(media_betas_se[j]), 4) if not np.isnan(media_betas_se[j]) else None,
            'beta_ci_low_freq': round(float(media_betas[j] - beta_ci_half), 4),
            'beta_ci_high_freq': round(float(media_betas[j] + beta_ci_half), 4),
        }
        # Sprint 2 extension: bootstrap ROI CI when computed успешно. These map
        # to roi_ci_low/high downstream (decomposer reads channel_params['roi_ci_low_bootstrap']
        # if posterior samples отсутствуют - '1.0-ols' pickles).
        boot = bootstrap_roi_results.get(col)
        if boot is not None and boot.get('ci_low') is not None:
            ch_dict['roi_ci_low_bootstrap'] = round(boot['ci_low'], 4)
            ch_dict['roi_ci_high_bootstrap'] = round(boot['ci_high'], 4)
            ch_dict['roi_bootstrap_mean'] = round(boot['ci_mean'], 4)
        channel_params[col] = ch_dict

    diagnostics = {
        'engine': 'ols',
        # Аудит 2026-07-04 (F-2): честный статус сезонности для UI-строки
        # SeasonalityControl. OLS не инжектит Фурье (F-AUD-4 фильтрует) — без
        # ключа компонент вечно показывал бы «Обучите модель, чтобы увидеть»
        # ПОСЛЕ обучения (ложь). reason='ols_mode' → своя честная формулировка.
        'seasonality': {'detected': False, 'reason': 'ols_mode'},
        'n_obs': n_obs,
        'n_params': p,
        'dof': dof,
        'metrics': {
            'r_squared': round(r_squared, 4),
            'adj_r_squared': round(adj_r_squared, 4),
            'mape': round(mape, 2),
            'residual_std_norm': round(residual_std_norm, 4),
            'residual_std': round(residual_std, 4),
            # No MCMC diagnostics - OLS has no chains/divergences/r_hat
            'mcmc': None,
        },
        # Sprint 2 extension: standard OLS quality diagnostics (leverage, Cook's, VIF).
        # Empty dict if computation failed (defensive - no crash на degenerate data).
        'ols_quality': ols_diag_results,
        # S-OLS-1: conformal prediction PI (distribution-free coverage guarantee).
        # Available for downstream display alongside frequentist β CI + bootstrap ROI.
        'conformal_pi': conformal_pi,
        'actual_vs_predicted': {
            'actual': [round(float(v), 4) for v in y.tolist()],
            'predicted': [round(float(v), 4) for v in y_pred.tolist()],
            'residual': [round(float(v), 4) for v in (y - y_pred).tolist()],
        },
        # Honest small-N disclosure
        'honest_disclosure': (
            f'OLS-режим (small data fallback): n={n_obs} наблюдений, p={p} параметров, '
            f'dof={dof}. Hill α={DEFAULT_ALPHA}, γ={DEFAULT_GAMMA}, decay={DEFAULT_DECAY} - '
            f'фиксированы, не обучаются (нужен n≥30 для Bayesian estimate). '
            f'Правдоподобные диапазоны - frequentist на β-коэффициенты + predictive intervals на y. '
            f'Не апостериорный правдоподобный диапазон, как в байесовском режиме.'
        ),
        # v2.1.0 (pilot D2 round 2 R02): expose unit_costs snapshot для frontend
        # hill.js pre-multiply symmetry (was scaled in modeler pre-multiply).
        'unit_costs_applied_at_training': bool(unit_costs_snapshot),
        'unit_costs_snapshot': dict(unit_costs_snapshot),
    }

    # F-A1-9/OLS: вердикт надёжности сразу при обучении — одинаково с Bayesian-веткой.
    # model_reliability_verdict умеет OLS (engine='ols' → uncertain максимум, без r_hat/MCMC).
    try:
        from utils.optimizer_honesty import model_reliability_verdict as _mrv
        _r = _mrv(diagnostics)
        diagnostics['honesty_verdict'] = _r.get('verdict', 'unknown')
        _hr = [str(x) for x in (_r.get('reasons') or [])]
        if _hr:
            diagnostics['honesty_reasons'] = _hr[:3]
    except Exception as _hv_err:
        logger.warning('honesty_verdict in ols diagnostics skipped: %s', _hv_err)
        diagnostics['honesty_verdict'] = 'unknown'

    report('saving', pct=90)

    model_data = {
        'config': config,
        'channel_params': channel_params,
        # v2.1.0 (ADR-020): unit_costs trail для decomposer симметрии.
        'unit_costs_applied_at_training': bool(unit_costs_snapshot),
        'unit_costs_snapshot': dict(unit_costs_snapshot),
        # v2.1.0 (ADR-021): kpi_unit_cost snapshot для money ROI conversion.
        'kpi_unit_cost_snapshot': (
            float(config['kpi_unit_cost'])
            if config.get('kpi_unit_cost') is not None
            else None
        ),
        'normalization': {
            'media_means': media_means,
            'control_means': dict(zip(control_cols, control_means.tolist())) if len(control_cols) > 0 else {},
            'control_stds': dict(zip(control_cols, control_stds.tolist())) if len(control_cols) > 0 else {},
            'y_mean': y_mean,
            'y_std': y_std,
            'intercept_mean': intercept_norm,
            'control_betas_mean': control_betas.tolist() if len(control_betas) > 0 else [],
            'untrained_channels': untrained_channels,
        },
        # OLS-specific diagnostics for downstream banner / honest disclosure
        'ols_diagnostics': {
            'residual_std_norm': residual_std_norm,
            'residual_std': residual_std,
            'r_squared': r_squared,
            'adj_r_squared': adj_r_squared,
            'mape': mape,
            'beta_standard_errors': beta_se_norm.tolist(),
            'XtX_inverse_diag': np.diag(XtX_inv).tolist() if 'XtX_inv' in dir() else None,
        },
        # Schema: model_version='1.0-ols' - distinct from Bayesian v1.1+.
        # Downstream engines treat as v1.1 path (no posterior_samples → point estimate only).
        # Migration banner in decomposer offers Bayesian retrain when n≥30.
        'model_version': '1.0-ols',
        'y_actual': y.tolist(),
        'y_predicted': y_pred.tolist(),
    }

    model_path = models_dir / 'latest.pkl'
    history_dir = models_dir / 'history'
    history_dir.mkdir(exist_ok=True)
    if model_path.exists():
        import shutil
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy2(model_path, history_dir / f'model-{ts}.pkl')
        # F-E3-2 (2026-07-03): паритет с bayesian-тренером — архивировать и
        # params-снимок. Без него /compute/model_history не видел OLS-поколений,
        # а дрейф-мониторинг не мог определить окно обучения архива.
        prev_params = models_dir / 'latest-params.json'
        if prev_params.exists():
            shutil.copy2(prev_params, history_dir / f'params-{ts}.json')
        archives = sorted(history_dir.glob('model-*.pkl'))
        while len(archives) > 5:
            archives[0].unlink(missing_ok=True)
            param_f = archives[0].name.replace('model-', 'params-').replace('.pkl', '.json')
            (history_dir / param_f).unlink(missing_ok=True)
            archives.pop(0)

    # v2.1.0: безопасный формат aurora-model (zip + JSON + npz).
    # SH-AM-11: project_lock — защита от race с save_v20_diagnostics.
    from engines.persistence_safe import save_model_safe
    from engines.persistence import write_pkl_sha256_sidecar
    from utils.file_lock import project_lock
    with project_lock(Path(project_dir), timeout=10.0):
        save_model_safe(model_data, model_path)
        write_pkl_sha256_sidecar(model_path)

    params_path = models_dir / 'latest-params.json'
    with open(params_path, 'w', encoding='utf-8') as f:
        json.dump({
            'channel_params': channel_params,
            'diagnostics': diagnostics,
            'config': {k: v for k, v in config.items() if k != 'data_file'},
            'engine': 'ols',
        }, f, ensure_ascii=False, indent=2)

    # NaN-safe (2026-06-04 аудит): NaN→null, иначе Rust serde_json не парсит файл.
    from utils.safe_io import sanitize_nonfinite
    result_path = results_dir / 'model-diagnostics.json'
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(sanitize_nonfinite(diagnostics), f, ensure_ascii=False, indent=2)

    report('complete', pct=100)

    return {
        'status': 'ok',
        'engine': 'ols',
        'model_path': str(model_path),
        'diagnostics': diagnostics,
        'channel_params': channel_params,
        'normalization': {
            'y_mean': y_mean,
            'y_std': y_std,
        },
        'honest_disclosure': diagnostics['honest_disclosure'],
    }


def _honest_n_obs_tone(n_obs: int) -> str:
    """Тон по объёму наблюдений — только от n, независимо от override.

    Находка 6 (2026-07-26): объём наблюдений — свойство ДАННЫХ, а не движка.
    Явный выбор движка (override) не делает 12 строк достаточными, поэтому
    этот тон вычисляется по тем же порогам n<20/20≤n<30/n≥30 ВСЕГДА, в
    отличие от 'banner_tone' ниже, который при override коротко замыкается
    в 'good' (это управляет отдельной подсказкой интерфейса «ваш явный выбор
    принят» и намеренно не трогается).
    """
    if n_obs < 20:
        return 'bad'
    if n_obs < 30:
        return 'warn'
    return 'good'


def recommend_engine(n_obs: int, *, override: str | None = None) -> dict[str, Any]:
    """Auto-recommend Bayesian vs OLS based on sample size.

    Per ADR §3.A2 + Antón confirmation:
      n < 20  → strict OLS (Bayesian unreliable)
      20 ≤ n < 30 → user choice (default OLS, Bayesian opt-in)
      n ≥ 30 → Bayesian default (OLS opt-in for fast iteration)

    Args:
        n_obs: number of training observations
        override: 'bayesian' | 'ols' - explicit user choice; takes precedence

    Returns:
        {
          'recommended': 'bayesian' | 'ols',
          'allowed': list of allowed modes,
          'reason': human-readable rationale,
          'banner_tone': 'good' | 'warn' | 'bad'  (UI styling hint; 'good' при
              override — подсказка "ваш явный выбор принят", НЕ честность n),
          'n_obs_tone': 'good' | 'warn' | 'bad'  (честный тон по n, не
              зависит от override — см. _honest_n_obs_tone)
        }
    """
    n_obs_tone = _honest_n_obs_tone(n_obs)
    if override in ('bayesian', 'ols'):
        override_label = 'Bayesian MMM' if override == 'bayesian' else 'OLS'
        reason = f'Явный выбор пользователя: {override_label}.'
        # Находка 6 продолжение (2026-07-27): 'reason' теперь доезжает до
        # клиента (server.py::preflight) всякий раз, когда n_obs_tone не
        # 'good', - "выбор принят" сам по себе не объясняет вердикт, поэтому
        # при малом n к тексту добавляется честная причина вместо голой
        # констатации выбора.
        if n_obs_tone == 'bad':
            reason += (
                f' n={n_obs}: данных недостаточно (нужно n≥20) для надёжной оценки – '
                f'результаты могут быть ненадёжными вне зависимости от выбранного режима.'
            )
        elif n_obs_tone == 'warn':
            reason += (
                f' n={n_obs}: пограничная область (n<30) – результаты могут иметь '
                f'широкие правдоподобные диапазоны.'
            )
        return {
            'recommended': override,
            'allowed': ['bayesian', 'ols'],
            'reason': reason,
            'banner_tone': 'good',
            'n_obs_tone': n_obs_tone,
            'override_active': True,
        }
    if n_obs < 20:
        return {
            'recommended': 'ols',
            'allowed': ['ols'],
            'reason': (
                f'n={n_obs}: данных недостаточно для Bayesian MMM (нужен n≥20 для базовой '
                f'идентифицируемости, n≥30 для надёжных правдоподобных диапазонов). Используется OLS-режим '
                f'с частотным диапазоном на β + predictive intervals на y.'
            ),
            'banner_tone': 'bad',
            'n_obs_tone': n_obs_tone,
            'override_active': False,
        }
    if n_obs < 30:
        return {
            'recommended': 'ols',
            'allowed': ['ols', 'bayesian'],
            'reason': (
                f'n={n_obs}: пограничная область. По умолчанию рекомендуется OLS (стабильнее '
                f'на малых выборках), но можно попробовать Bayesian с экспериментальным режимом. '
                f'Bayesian результаты могут иметь R-hat>1.05 и широкие правдоподобные диапазоны.'
            ),
            'banner_tone': 'warn',
            'n_obs_tone': n_obs_tone,
            'override_active': False,
        }
    return {
        'recommended': 'bayesian',
        'allowed': ['bayesian', 'ols'],
        'reason': (
            f'n={n_obs}: достаточно данных для Bayesian MMM (NUTS estimate Hill α/γ + adstock '
            f'decay per channel + правдоподобный диапазон). OLS доступен как быстрый baseline.'
        ),
        'banner_tone': 'good',
        'n_obs_tone': n_obs_tone,
        'override_active': False,
    }
