"""
A4 Pre-MCMC reliability — prior predictive + Nott KL divergence.

Sprint 1.5 Phase A4 backend (per ADR §6).

Two layers ON TOP of A4 quick proxy (utils/reliability_quick_proxy.py):
- A4.1 Prior predictive check — samples из priors WITHOUT observation, compares
  с y_observed range. Catches "priors too tight/wide" mismatches.
- A4.2 Nott KL divergence — measures prior-data conflict per channel β post-training.
  Detects "industry priors disagree with your data" cases.

Quick proxy (1 sec) is the first gate. A4.1 prior predictive (~5-15 sec) is run
before MCMC. A4.2 Nott KL (~1 sec) runs post-training on stored posterior_samples.

Reference: Nott et al. 2016 "Checking for prior-data conflict using prior-to-posterior
divergence" arXiv:1611.00113. NOT "Yang's test" — that was misnamed in early ADR
(see audit notes in docs/SPRINT1_FOUNDATION_ADR.md §3.A6).

Per ADR §3.A8: all messaging constructive — never "refuse" / "cannot". Always offers
override path with banner.
"""
from __future__ import annotations

from typing import Any

import numpy as np


# Calibration thresholds (per ADR §6 + Egidi 2022 + Nott 2016 literature)
PRIOR_PRED_COVERAGE_OK = 0.80     # ≥80% of y_observed within prior predictive 90% interval
PRIOR_PRED_COVERAGE_FAIL = 0.50   # <50% = priors way off — strong conflict
KL_GAMMA_OK = 0.05                # <0.05 = no significant prior-data conflict
KL_GAMMA_FAIL = 0.01              # <0.01 (tight на small N) — soft fail


def prior_predictive_check(
    y_observed: np.ndarray,
    media_matrix: np.ndarray,
    media_means: dict | None = None,
    n_samples: int = 500,
    *,
    intercept_prior_mu: float = 0.0,
    intercept_prior_sigma: float = 0.5,
    media_beta_sigma: float = 0.3,
    alpha_gamma_shape: tuple = (5, 3),  # Gamma(5, 3) for alphas
    gamma_beta_shape: tuple = (3, 3),   # Beta(3, 3) for gammas
    decay_default: float = 0.5,
    seed: int | None = 42,
) -> dict[str, Any]:
    """A4.1 — Prior predictive check.

    Samples N times from priors (matching modeler.py exactly), computes simulated
    y for each sample, then checks: does the empirical 5-95% range of simulated y
    cover the observed y range adequately?

    Mathematical setup (matches modeler.py):
        intercept ~ Normal(0, 0.5)
        media_betas[j] ~ HalfNormal(0.3)
        alphas[j] ~ Gamma(5, 3)
        gammas[j] ~ Beta(3, 3)
        x_norm[t,j] = adstock(raw[t,j]; decay=0.5) / mean[j]
        sat[t,j] = hill(x_norm; alpha[j], gamma[j])
        y_norm[t] = intercept + sum_j(media_betas[j] * sat[t,j])
        y_predicted[t] = y_norm[t] * y_std + y_mean

    Args:
        y_observed: 1D array of observed KPI values, shape (n_obs,)
        media_matrix: 2D array shape (n_obs, n_channels) raw spend
        media_means: dict {channel_name: pre-computed mean} or None (compute from data)
        n_samples: number of prior predictive samples (500 = fast + reliable)
        seed: RNG seed for reproducibility

    Returns:
        dict with:
          - coverage: float — fraction of y_observed within simulated 5-95% range
          - status: 'pass' | 'warn' | 'fail'
          - y_observed_range: (min, max) for context
          - y_simulated_quantiles: dict with p5, p50, p95 across samples × time
          - warning: human-readable issue if status != 'pass'
          - recommendation: actionable next step
    """
    rng = np.random.default_rng(seed)

    y_obs = np.asarray(y_observed, dtype=np.float64)
    X = np.asarray(media_matrix, dtype=np.float64)
    n_obs, n_channels = X.shape if X.ndim == 2 else (0, 0)

    if n_obs == 0 or n_channels == 0:
        return {
            'coverage': 0.0, 'status': 'fail',
            'warning': 'Пустая матрица — невозможно проверить prior predictive',
            'recommendation': 'Убедитесь что данные загружены и каналы выбраны',
        }

    # Compute media_means if not provided (matches modeler default)
    if media_means is None:
        means = X.mean(axis=0)
    else:
        means = np.array([float(media_means.get(f'ch_{j}', X[:, j].mean())) for j in range(n_channels)])
    means_safe = np.where(means > 1e-9, means, 1.0)

    # Apply adstock once with default decay (matches modeler pre-fit semantics).
    # We use simple geometric expansion — close enough to apply_adstock() для prior check.
    adstocked = np.zeros_like(X)
    adstocked[0] = X[0]
    for t in range(1, n_obs):
        adstocked[t] = X[t] + decay_default * adstocked[t - 1]
    x_norm = adstocked / means_safe.reshape(1, -1)

    # y normalization stats (matches modeler)
    y_mean = float(y_obs.mean())
    y_std = max(float(y_obs.std()), 1e-10)

    # Sample N draws from priors
    intercept = rng.normal(intercept_prior_mu, intercept_prior_sigma, n_samples)
    # HalfNormal samples = abs(Normal)
    media_betas = np.abs(rng.normal(0.0, media_beta_sigma, size=(n_samples, n_channels)))
    # Gamma(5, 3): scale = 1/3
    alphas = rng.gamma(alpha_gamma_shape[0], 1.0 / alpha_gamma_shape[1], size=(n_samples, n_channels))
    gammas = rng.beta(gamma_beta_shape[0], gamma_beta_shape[1], size=(n_samples, n_channels))

    # Compute simulated y_norm для each sample
    # Vectorized: for sample i, y_norm_i[t] = intercept_i + sum_j media_betas_i[j] * hill(x_norm[t,j]; alpha_i[j], gamma_i[j])
    y_norm_sim = np.zeros((n_samples, n_obs), dtype=np.float64)
    for j in range(n_channels):
        # Hill: x^α / (x^α + γ^α)
        x_pos = np.maximum(x_norm[:, j], 1e-10).reshape(1, -1)  # (1, n_obs)
        a = alphas[:, j].reshape(-1, 1)
        g = gammas[:, j].reshape(-1, 1)
        x_pow = x_pos ** a
        g_pow = np.maximum(g, 1e-10) ** a
        sat = x_pow / (x_pow + g_pow)
        y_norm_sim += media_betas[:, j].reshape(-1, 1) * sat
    y_norm_sim += intercept.reshape(-1, 1)

    # Denormalize to original units (matches y = y_norm * y_std + y_mean)
    y_sim = y_norm_sim * y_std + y_mean

    # Check coverage: at each time t, what fraction of samples cover y_observed[t]?
    # Use 5-95% range per time point.
    p5 = np.percentile(y_sim, 5, axis=0)
    p95 = np.percentile(y_sim, 95, axis=0)
    p50 = np.percentile(y_sim, 50, axis=0)
    coverage_per_t = ((y_obs >= p5) & (y_obs <= p95)).astype(float)
    coverage = float(coverage_per_t.mean())

    if coverage < PRIOR_PRED_COVERAGE_FAIL:
        status = 'fail'
        warning = (
            f'Prior predictive coverage {coverage*100:.0f}% < {PRIOR_PRED_COVERAGE_FAIL*100:.0f}%. '
            f'Приоры сильно расходятся с данными. '
            f'Возможно: ваш бренд / категория нестандартны (ROI gear отличается от индустрии), '
            f'либо проблема с unit_costs / нормализацией данных.'
        )
        recommendation = (
            'Проверьте unit_costs (для TRP/clicks). Если данные корректны — '
            'возможно вы в категории где приоры Aurora не подходят (например, '
            'специфическая ниша B2B). Можно попробовать обучить с шире приорами, '
            'но точность оценок будет ниже.'
        )
    elif coverage < PRIOR_PRED_COVERAGE_OK:
        status = 'warn'
        warning = (
            f'Prior predictive coverage {coverage*100:.0f}% между '
            f'{PRIOR_PRED_COVERAGE_FAIL*100:.0f}% и {PRIOR_PRED_COVERAGE_OK*100:.0f}%. '
            f'Приоры частично расходятся с данными — обучение продолжится, '
            f'но posterior CI могут быть оптимистично узкими.'
        )
        recommendation = (
            'Обучение возможно, но используйте результаты как направление. '
            'Для повышения точности — соберите данные за более длинный период '
            'либо проведите incrementality-тест на 1-2 ключевых каналах.'
        )
    else:
        status = 'pass'
        warning = ''
        recommendation = 'Приоры согласуются с диапазоном данных. Можно начинать обучение модели.'

    return {
        'coverage': round(coverage, 3),
        'status': status,
        'thresholds': {'ok': PRIOR_PRED_COVERAGE_OK, 'fail': PRIOR_PRED_COVERAGE_FAIL},
        'y_observed_range': (round(float(y_obs.min()), 2), round(float(y_obs.max()), 2)),
        'y_simulated_quantiles': {
            'p5': [round(float(v), 2) for v in p5.tolist()],
            'p50': [round(float(v), 2) for v in p50.tolist()],
            'p95': [round(float(v), 2) for v in p95.tolist()],
        },
        'warning': warning,
        'recommendation': recommendation,
        'n_samples': n_samples,
    }


def nott_kl_divergence_per_channel(
    posterior_samples: dict,
    prior_sigma: float = 0.3,
    n_prior_samples: int = 5000,
    seed: int | None = 42,
) -> dict[str, Any]:
    """A4.2 — Nott et al. 2016 prior-to-posterior KL divergence per channel β.

    For each channel j, compute KL(posterior(β_j) || prior(β_j)) using sample-based
    histogram approximation. Calibrate by sampling N prior draws и computing the
    null distribution of KL between independent prior subsamples. p-value = fraction
    of null KL ≥ observed KL.

    Threshold: γ = 0.05 standard, γ = 0.01 для small N (per Egidi 2022).
    Report status per channel: 'ok' | 'warn' | 'fail'.

    Args:
        posterior_samples: dict from utils/posterior_propagation.load_posterior_samples
            with media_betas shape (n_channels, n_samples) + media_columns
        prior_sigma: HalfNormal scale used in modeler.py (0.3 default)
        n_prior_samples: how many prior samples for null distribution
        seed: RNG

    Returns:
        dict with:
          - per_channel: list of {channel, kl, p_value, status}
          - overall_status: aggregate ('pass' | 'warn' | 'fail')
          - warnings: list of strings
          - recommendation: actionable text
    """
    rng = np.random.default_rng(seed)

    media_betas = np.asarray(posterior_samples.get('media_betas'))
    media_cols = posterior_samples.get('media_columns', [])
    if media_betas.ndim != 2 or media_betas.size == 0:
        return {
            'per_channel': [], 'overall_status': 'fail',
            'warnings': ['Empty media_betas posterior samples'],
            'recommendation': 'Posterior samples corrupted — re-train model',
        }
    n_channels, n_samples = media_betas.shape

    # Sample priors (HalfNormal = abs(Normal))
    prior_draws = np.abs(rng.normal(0.0, prior_sigma, size=n_prior_samples))

    # Histogram-based KL approximation
    def _kl_estimate(post_arr: np.ndarray, prior_arr: np.ndarray, bins: int = 40) -> float:
        # Joint range to ensure same bins
        lo = float(min(post_arr.min(), prior_arr.min()))
        hi = float(max(post_arr.max(), prior_arr.max()))
        if hi - lo < 1e-9:
            return 0.0
        edges = np.linspace(lo, hi, bins + 1)
        post_hist, _ = np.histogram(post_arr, bins=edges)
        prior_hist, _ = np.histogram(prior_arr, bins=edges)
        # Add Laplace smoothing (avoid log(0))
        post_p = (post_hist + 1.0) / (post_hist.sum() + bins)
        prior_p = (prior_hist + 1.0) / (prior_hist.sum() + bins)
        # KL(post || prior) = sum(post_p * log(post_p / prior_p))
        return float(np.sum(post_p * np.log(post_p / prior_p)))

    # Null distribution: KL between two independent prior subsamples
    null_kls = []
    n_null_iters = 200
    null_subsample_size = min(n_samples, 1000)
    for _ in range(n_null_iters):
        a = rng.choice(prior_draws, size=null_subsample_size, replace=True)
        b = rng.choice(prior_draws, size=null_subsample_size, replace=True)
        null_kls.append(_kl_estimate(a, b))
    null_kls = np.array(null_kls)

    # Per-channel KL + p-value
    per_channel = []
    fail_count = 0
    warn_count = 0
    threshold_p = KL_GAMMA_OK  # default; tighten if small N

    # Tighten threshold on small posterior (proxy for small N — fewer effective samples)
    if n_samples < 2000:
        threshold_p = KL_GAMMA_FAIL

    for i, ch_name in enumerate(media_cols):
        post_arr = media_betas[i]
        if post_arr.size < 100:
            per_channel.append({
                'channel': ch_name, 'kl': None, 'p_value': None, 'status': 'skip',
                'reason': 'too few posterior samples',
            })
            continue
        kl = _kl_estimate(post_arr, prior_draws)
        # p-value = fraction of null KLs ≥ observed (one-sided)
        p_val = float((null_kls >= kl).mean())
        if p_val < KL_GAMMA_FAIL:
            status = 'fail'
            fail_count += 1
        elif p_val < threshold_p:
            status = 'warn'
            warn_count += 1
        else:
            status = 'ok'
        per_channel.append({
            'channel': ch_name,
            'kl': round(kl, 4),
            'p_value': round(p_val, 4),
            'status': status,
        })

    # Aggregate
    if fail_count > 0:
        overall = 'fail'
        rec = (
            'Aurora обнаружила значительное расхождение приоров с данными по каналам. '
            'Приоры основаны на индустриальных бенчмарках — если ваш кейс нестандартный '
            '(нишевая категория, новый бренд, специфические каналы), приоры могут не подходить. '
            'Рекомендация: используйте horseshoe-приоры (Sprint 2 / A3, mode opt-in в Expert) — '
            'они автоматически адаптируются к данным с меньшей зависимостью от Aurora prior.'
        )
    elif warn_count > 0:
        overall = 'warn'
        rec = (
            'Часть каналов имеет умеренное расхождение приоров с данными. '
            'Posterior на эти каналы может быть biased к prior. Используйте результаты '
            'как ориентир, для премиум-точности — переобучите с горизонтом 50+ периодов.'
        )
    else:
        overall = 'pass'
        rec = 'Приоры согласуются с posterior — нет значимых prior-data conflicts.'

    return {
        'per_channel': per_channel,
        'overall_status': overall,
        'fail_count': fail_count,
        'warn_count': warn_count,
        'thresholds': {'gamma_ok': KL_GAMMA_OK, 'gamma_fail': KL_GAMMA_FAIL, 'threshold_used': threshold_p},
        'recommendation': rec,
        'method': 'Nott et al. 2016 sample-based KL divergence with null calibration',
    }
