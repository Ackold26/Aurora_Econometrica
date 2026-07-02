"""Goal-Seek honesty — характеризующие тесты мат-аудита 2026-07-02 (F-01/F-02/F-03).

Закрывают три подтверждённых зондом дефекта optimize_inverse:
- F-02: Delta-CI бюджета схлопывался в константу ±6.4% (spread ≈ |grad|·δ →
  half = 1.28·δ) — CI был слеп к posterior-разбросу модели. Теперь при наличии
  posterior — sd(B) = z·sd_posterior(S(B*))/|grad| (method='delta_posterior';
  Gelman, Bayesian Workflow: неопределённость — из posterior-симуляций).
- F-03: p_hit_target ≈ 0.5 всегда (бисекция останавливается на S(B*)≈target →
  z≈0). Теперь — честная доля posterior draws ≥ цели (p_hit_method='posterior').
- F-01: рекомендация уводила траты каналов за наблюдавшийся диапазон БЕЗ пометки.
  Теперь — result['extrapolation'] с каноническими тирами p95/p99
  (Chan & Perry 2017 Fig. 2: кривая вне наблюдённого диапазона не
  идентифицируется данными).

Плюс: упор CI в cap 50% (почти плоская кривая) поднимает баннер насыщения
(flat_response_fallback) — прежде True только при grad < 1e-9.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from optimize.inverse import (  # noqa: E402
    build_proportional_forward,
    estimate_p_hit_target,
    optimize_inverse,
)


# ─── Synthetic project builder (по образцу tools/conftest.py, + data_file) ────

def _build_project(
    base_dir: Path,
    name: str,
    *,
    beta_sd: float,
    gamma: float = 1.2,
    seed: int = 7,
    with_posterior: bool = True,
) -> Path:
    """Проект v1.2 с CSV data_file. gamma=1.2 → рабочая зона Hill (x_norm~1 < γ),
    градиент здоровый, CI не упирается в cap — narrow/wide различимы."""
    rng = np.random.default_rng(seed)
    project_dir = base_dir / name
    (project_dir / 'models').mkdir(parents=True, exist_ok=True)

    n_obs = 36
    media_cols = ['TV', 'Digital', 'OOH', 'Search', 'Social']
    n_ch = len(media_cols)
    n_samples = 200

    means = np.array([100.0, 200.0, 300.0, 400.0, 500.0])
    spends = {c: np.clip(rng.normal(means[i], means[i] * 0.25, n_obs), 1, None)
              for i, c in enumerate(media_cols)}
    dates = pd.date_range('2023-01-31', periods=n_obs, freq='ME')
    df = pd.DataFrame({'date': dates, **{c: np.round(spends[c], 2) for c in media_cols}})
    df['sales'] = 1000.0 + rng.normal(0, 50, n_obs)
    data_file = project_dir / 'data.csv'
    df.to_csv(data_file, index=False)

    base_betas = np.array([0.5, 0.45, 0.4, 0.35, 0.3])
    betas = np.abs(rng.normal(base_betas[:, None], beta_sd, size=(n_ch, n_samples))).astype(np.float32)
    alphas = np.full((n_ch, n_samples), 1.5, dtype=np.float32)
    gammas = np.full((n_ch, n_samples), gamma, dtype=np.float32)
    intercept = rng.normal(0.0, 0.01, n_samples).astype(np.float32)
    decays = np.clip(rng.normal(0.3, 0.02, size=(n_ch, n_samples)), 0.0, 0.95).astype(np.float32)

    channel_params = {
        c: {
            'beta': float(betas[i].mean()),
            'alpha': 1.5,
            'gamma': gamma,
            'decay': float(decays[i].mean()),
        }
        for i, c in enumerate(media_cols)
    }
    raw_means = {c: float(np.mean(spends[c])) for c in media_cols}

    model_data = {
        'model_version': '1.2',
        'config': {
            'media_columns': media_cols,
            'control_columns': [],
            'kpi_column': 'sales',
            'date_column': 'date',
            'adstock_config': {c: 'geometric' for c in media_cols},
            'channel_categories': {},
            'data_file': str(data_file),
        },
        'media_columns': media_cols,
        'control_columns': [],
        'channel_params': channel_params,
        'channel_categories': {},
        'use_hierarchical': False,
        'hierarchical_priors': {},
        'categorization_warnings': [],
        'normalization': {
            'media_means': raw_means,
            'control_means': {},
            'control_stds': {},
            'y_mean': 1000.0,
            'y_std': 250.0,
            'intercept_mean': float(intercept.mean()),
            'control_betas_mean': [],
            'untrained_channels': [],
        },
        'y_actual': df['sales'].tolist(),
        'y_predicted': df['sales'].tolist(),
        'causal_artifact_path': None,
    }
    if with_posterior:
        model_data['posterior_samples'] = {
            'media_betas': betas,
            'alphas': alphas,
            'gammas': gammas,
            'intercept': intercept,
            'control_betas': np.zeros((0, n_samples), dtype=np.float32),
            'adstock_decay': decays,
            'media_columns': media_cols,
            'control_columns': [],
            'n_chains': 2,
            'n_draws': n_samples // 2,
        }
    from engines.persistence_safe import save_model_safe
    save_model_safe(model_data, project_dir / 'models' / 'latest.pkl')
    return project_dir


def _moderate_target(project_dir: Path, growth: float = 1.03) -> float:
    fwd, meta = build_proportional_forward(str(project_dir))
    s_cur = fwd(meta['current_total_money'])['expected_sales']
    return s_cur * growth


# ─── F-02: CI отражает разброс posterior ──────────────────────────────────────

@pytest.mark.parametrize('seed', [7, 11, 23])
def test_F02_ci_reflects_posterior_spread(tmp_path, seed):
    """Отн. ширина CI бюджета растёт с разбросом posterior (narrow ≪ wide).

    До правки: обе ширины = 12.80% (константа 2·1.28·δ) — ratio 1.00.
    """
    p_narrow = _build_project(tmp_path, f'narrow_{seed}', beta_sd=0.03, seed=seed)
    p_wide = _build_project(tmp_path, f'wide_{seed}', beta_sd=0.40, seed=seed)

    rels = {}
    for label, pdir in [('narrow', p_narrow), ('wide', p_wide)]:
        target = _moderate_target(pdir)
        res = optimize_inverse(str(pdir), target_sales=target, kpi_kind='monetary')
        assert res['achievable'] is True, f'{label}: цель +3% должна быть достижима'
        tb = res['total_budget']
        assert tb['method'] == 'delta_posterior', (
            f'{label}: ожидали delta_posterior, получили {tb["method"]}'
        )
        rels[label] = (tb['p90'] - tb['p10']) / tb['p50']

    assert rels['wide'] > rels['narrow'] * 1.5, (
        f'CI слеп к posterior-разбросу: narrow={rels["narrow"]:.4f}, '
        f'wide={rels["wide"]:.4f} (ожидали wide > narrow × 1.5). '
        f'Регрессия F-02 (схлопывание в константу).'
    )


# ─── F-03: p_hit — честная доля из posterior ─────────────────────────────────

def test_F03_p_hit_from_posterior_samples_unit():
    """estimate_p_hit_target с samples = точная доля draws ≥ target."""
    samples = np.array([1.0, 2.0, 3.0, 4.0])
    assert estimate_p_hit_target(2.5, 2.5, sales_samples=samples) == pytest.approx(0.5)
    assert estimate_p_hit_target(2.5, 1.5, sales_samples=samples) == pytest.approx(0.75)
    assert estimate_p_hit_target(2.5, 4.5, sales_samples=samples) == pytest.approx(0.0)
    # Битые samples (NaN) → отфильтрованы; один сэмпл → fallback-эвристика.
    assert estimate_p_hit_target(10.0, 5.0, sales_samples=[np.nan]) == pytest.approx(0.5)


def test_F03_p_hit_method_posterior_e2e(tmp_path):
    pdir = _build_project(tmp_path, 'phit', beta_sd=0.2)
    res = optimize_inverse(str(pdir), target_sales=_moderate_target(pdir), kpi_kind='monetary')
    assert res['achievable'] is True
    assert res['p_hit_method'] == 'posterior'
    # На B* бисекция останавливается у цели → доля ~симметрична; главное —
    # значение вычислено из draws (не литерал эвристики 0.5·expected/target).
    assert 0.25 <= res['p_hit_target'] <= 0.75


# ─── F-01: маркер экстраполяции ──────────────────────────────────────────────

def test_F01_extrapolation_marker_fires_near_ceiling(tmp_path):
    """Цель у потолка модели → severity ≥ 2 и непустой список каналов."""
    pdir = _build_project(tmp_path, 'extra', beta_sd=0.05, gamma=0.5)
    fwd, meta = build_proportional_forward(str(pdir))
    s_cur = fwd(meta['current_total_money'])['expected_sales']
    probe = optimize_inverse(str(pdir), target_sales=s_cur * 1000, kpi_kind='monetary')
    ceiling = probe['fallback_max_sales']
    res = optimize_inverse(
        str(pdir), target_sales=s_cur + (ceiling - s_cur) * 0.9, kpi_kind='monetary')
    assert res['achievable'] is True
    ex = res['extrapolation']
    assert ex is not None, 'Маркер экстраполяции отсутствует (регрессия F-01)'
    assert ex['severity'] >= 2, f'Ожидали severity>=2 у потолка, получили {ex["severity"]}'
    assert ex['channels'], 'Список каналов за диапазоном пуст'
    ch = ex['channels'][0]
    assert {'name', 'per_period_native', 'hist_max_native', 'ratio_vs_max', 'severity'} <= set(ch)


def test_F01_extrapolation_silent_in_observed_range(tmp_path):
    """Скромная цель (бюджет ниже текущего) → severity == 0, каналов нет."""
    pdir = _build_project(tmp_path, 'inzone', beta_sd=0.05)
    fwd, meta = build_proportional_forward(str(pdir))
    s_low = fwd(meta['current_total_money'] * 0.6)['expected_sales']
    res = optimize_inverse(str(pdir), target_sales=s_low, kpi_kind='monetary')
    assert res['achievable'] is True
    ex = res['extrapolation']
    assert ex is not None
    assert ex['severity'] == 0, f'Ложная тревога экстраполяции: {ex}'
    assert ex['channels'] == []


# ─── Насыщение: cap CI → баннер ──────────────────────────────────────────────

def test_capped_ci_raises_saturation_banner(tmp_path):
    """Цель у потолка (плоская зона, grad мал) → CI упирается в cap 50% →
    flat_response_fallback=True (баннер насыщения), даже если grad > 1e-9."""
    pdir = _build_project(tmp_path, 'satur', beta_sd=0.05, gamma=0.5)
    fwd, meta = build_proportional_forward(str(pdir))
    s_cur = fwd(meta['current_total_money'])['expected_sales']
    probe = optimize_inverse(str(pdir), target_sales=s_cur * 1000, kpi_kind='monetary')
    ceiling = probe['fallback_max_sales']
    res = optimize_inverse(
        str(pdir), target_sales=s_cur + (ceiling - s_cur) * 0.9, kpi_kind='monetary')
    assert res['achievable'] is True
    tb = res['total_budget']
    if tb.get('capped'):
        assert res['flat_response_fallback'] is True, (
            'CI упёрся в cap (насыщение), а баннер не поднят'
        )
    else:
        # Если вдруг не capped на этой конфигурации — метод обязан быть честным.
        assert tb['method'] in ('delta_posterior', 'flat_response_fallback')


# ─── Back-compat: OLS/legacy без posterior ───────────────────────────────────

def test_backcompat_no_posterior_falls_back(tmp_path):
    """Без posterior_samples: старый delta-прокси + эвристический p_hit,
    маркер экстраполяции работает (не зависит от posterior)."""
    pdir = _build_project(tmp_path, 'nopost', beta_sd=0.05, with_posterior=False)
    res = optimize_inverse(str(pdir), target_sales=_moderate_target(pdir), kpi_kind='monetary')
    assert res['achievable'] is True
    assert res['total_budget']['method'] in ('delta', 'flat_response_fallback', 'point')
    assert res['p_hit_method'] == 'heuristic'
    assert res['extrapolation'] is not None


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
