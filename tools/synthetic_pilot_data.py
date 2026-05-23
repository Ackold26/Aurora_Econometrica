"""
Synthetic РФ pilot data generator для Aurora MMM Optimizer v2.0.0 validation.

Replaces NDA-protected Кагоцел / Венарус pilot data для Phase E2 signed factor
priors calibration testing. Generated data имеет known ground-truth coefficients
(GROUND_TRUTH_* dicts), что позволяет verify prior recovery quantitatively.

Workflow:
    python tools/synthetic_pilot_data.py
    → tools/synthetic_pilots/*.xlsx (4 datasets)

Math model (identical to Aurora MMM):
    y[t] = intercept + Σ_i beta_i * hill(adstock(x_i[t])) + Σ_j coef_j * z_j[t] + ε[t]

    adstock(x[t]) = x[t] + decay * adstock(x[t-1])   (geometric)
    hill(x, alpha, gamma) = x^alpha / (x^alpha + gamma^alpha)

All values в реалистичных РФ FMCG / OTC pharma диапазонах.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ─── Ground truth coefficients (normalized scale — модель работает с нормализованными данными) ───

GROUND_TRUTH_FMCG = {
    # Media coefficients (normalized β — доля std(KPI) на unit normalized spend)
    'tv_beta': 0.35,
    'digital_beta': 0.45,
    'ooh_beta': 0.15,
    'performance_beta': 0.30,
    # Adstock decay rates (monthly grain)
    'tv_decay': 0.70,
    'digital_decay': 0.40,
    'ooh_decay': 0.50,
    'performance_decay': 0.20,
    # Hill saturation (alpha=shape, gamma=half-saturation point normalized)
    'tv_alpha': 2.5,
    'digital_alpha': 2.0,
    'ooh_alpha': 1.8,
    'performance_alpha': 2.2,
    # Signed factor coefficients (normalized — на std(control))
    'competitor_coef': -0.18,  # TARGET для prior recovery test
    'price_coef': -0.04,       # mild negative (higher price → slightly less sales)
    'holiday_newyear_coef': 0.08,
    # Base level
    'base_sales_rub': 25_000_000,  # ₽/month average base
}

GROUND_TRUTH_OTC_PHARMA = {
    'tv_beta': 0.40,
    'digital_beta': 0.30,
    'apteka_ooh_beta': 0.20,
    'performance_beta': 0.25,
    'tv_decay': 0.65,
    'digital_decay': 0.35,
    'apteka_ooh_decay': 0.45,
    'performance_decay': 0.15,
    'tv_alpha': 2.2,
    'digital_alpha': 1.8,
    'apteka_ooh_alpha': 2.0,
    'performance_alpha': 2.0,
    'competitor_coef': -0.22,  # TARGET: сильнее чем FMCG (OTC конкурирует на полке)
    'weather_temp_low_coef': 0.12,  # positive: холодная погода → больше продаж ОТС
    'holiday_newyear_coef': 0.15,   # Q4 double peak: pre-shop + flu season
    'base_sales_packs': 120_000,    # пачек/месяц average base
}

GROUND_TRUTH_RETAIL = {
    'tv_beta': 0.30,
    'digital_beta': 0.40,
    'ooh_beta': 0.25,
    'promo_beta': 0.35,            # promo indicator (binary control, positive)
    'tv_decay': 0.55,
    'digital_decay': 0.30,
    'ooh_decay': 0.50,
    'promo_decay': 0.10,           # promo effect dies quickly
    'tv_alpha': 2.0,
    'digital_alpha': 1.8,
    'ooh_alpha': 1.6,
    'promo_alpha': 3.0,            # step-like saturation для binary promo
    'competitor_coef': -0.15,
    'holiday_blackfriday_coef': 0.20,
    'holiday_newyear_coef': 0.25,
    'base_traffic_visits': 2_500_000,  # визитов/месяц average
}

GROUND_TRUTH_REAL_ESTATE = {
    'tv_beta': 0.35,
    'ooh_beta': 0.20,
    'digital_beta': 0.40,
    'performance_beta': 0.45,
    'tv_decay': 0.80,              # недвижимость — длинный adstock
    'ooh_decay': 0.60,
    'digital_decay': 0.55,
    'performance_decay': 0.25,
    'tv_alpha': 2.0,
    'ooh_alpha': 1.8,
    'digital_alpha': 2.2,
    'performance_alpha': 2.5,
    'competitor_coef': -0.12,
    'macro_cpi_coef': -0.10,       # инфляция → снижение покупательной способности
    'seasonality_q1_coef': -0.08,  # Q1 типично слабый
    'seasonality_q4_coef': 0.10,   # Q4 сезон сделок
    'base_leads': 850,             # заявок/месяц average
}

# ─── Utility functions ────────────────────────────────────────────────────────

def _geometric_adstock(x: np.ndarray, decay: float) -> np.ndarray:
    """Geometric adstock: s[t] = x[t] + decay * s[t-1]."""
    n = len(x)
    s = np.zeros(n)
    for t in range(n):
        s[t] = x[t] + (decay * s[t - 1] if t > 0 else 0.0)
    return s


def _hill(x: np.ndarray, alpha: float, gamma: float) -> np.ndarray:
    """Hill saturation function: x^alpha / (x^alpha + gamma^alpha)."""
    x_safe = np.maximum(x, 0.0)
    xpow = np.power(x_safe + 1e-12, alpha)
    gpow = np.power(gamma + 1e-12, alpha)
    return xpow / (xpow + gpow)


def _normalize(x: np.ndarray) -> np.ndarray:
    """Standard normalize: (x - mean) / std."""
    s = x.std()
    if s < 1e-10:
        return x - x.mean()
    return (x - x.mean()) / s


# ─── Dataset 1: FMCG бренд массмаркет ────────────────────────────────────────

def generate_fmcg_brand(seed: int = 42) -> pd.DataFrame:
    """FMCG бренд массмаркет — 36 months (2023-01 → 2025-12).

    Channels: TV (₽ spend), Digital (₽), OOH (TRP physical), Performance (clicks physical).
    Target: sales_rub (₽ выручка).
    Signed factors: competitor_trp, price_index, holiday_newyear_preshop.
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_FMCG
    n = 36
    dates = pd.date_range('2023-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()

    # ── Media inputs (realistic РФ FMCG scales) ──────────────────────────────
    # TV: 5–15 М₽/мес, higher in Q4 (pre-New Year) and Q1 (post-NY reactivation)
    tv_seasonal = 1.0 + 0.3 * np.sin(2 * np.pi * (months - 1) / 12) + 0.2 * (months == 12)
    tv_spend = (
        rng.uniform(5e6, 12e6, n) * tv_seasonal
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=1e6)

    # Digital: 3–10 М₽/мес, more uniform
    digital_spend = (
        rng.uniform(3e6, 8e6, n) * (1 + 0.05 * rng.standard_normal(n))
    ).clip(min=5e5)

    # OOH: 50–300 TRP physical (outdoor GRP), Q2/Q3 outdoor higher
    ooh_seasonal = 1.0 + 0.2 * np.cos(2 * np.pi * (months - 6) / 12)
    ooh_trp = (
        rng.uniform(60, 250, n) * ooh_seasonal
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=10)

    # Performance (clicks): 200K–1M clicks, correlated с digital budget
    performance_clicks = (
        digital_spend / 8e6 * rng.uniform(300_000, 900_000, n)
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=10_000)

    # ── Signed factor controls ────────────────────────────────────────────────
    # Competitor TRP (их активность). Peaks alternating with our peaks.
    competitor_trp = (
        rng.uniform(30, 200, n)
        * (1 + 0.15 * np.sin(2 * np.pi * (months - 7) / 12 + np.pi))
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=0)

    # Price index (1.0 = base; >1 = higher price). Mild inflation trend + noise.
    price_index = 1.0 + 0.02 * np.arange(n) / n + 0.03 * rng.standard_normal(n)
    price_index = price_index.clip(0.85, 1.25)

    # Holiday: New Year pre-shop (Nov 15 – Dec 31) → months 11, 12
    holiday_newyear_preshop = ((months == 11) | (months == 12)).astype(float)

    # ── MMM ground truth outcome ──────────────────────────────────────────────
    base = gt['base_sales_rub']
    y_std_target = base * 0.15  # плановое std: 15% от base (умеренная волатильность)

    # Normalize inputs для model application
    tv_norm = _normalize(tv_spend)
    dig_norm = _normalize(digital_spend)
    ooh_norm = _normalize(ooh_trp)
    perf_norm = _normalize(performance_clicks)
    comp_norm = _normalize(competitor_trp)
    price_norm = _normalize(price_index)

    # Adstock
    tv_ads = _geometric_adstock(tv_norm, gt['tv_decay'])
    dig_ads = _geometric_adstock(dig_norm, gt['digital_decay'])
    ooh_ads = _geometric_adstock(ooh_norm, gt['ooh_decay'])
    perf_ads = _geometric_adstock(perf_norm, gt['performance_decay'])

    # Hill saturation (gamma = 0.6 — midpoint of typical saturation для normalized data)
    gamma_mid = 0.6
    tv_hill = _hill(tv_ads, gt['tv_alpha'], gamma_mid)
    dig_hill = _hill(dig_ads, gt['digital_alpha'], gamma_mid)
    ooh_hill = _hill(ooh_ads, gt['ooh_alpha'], gamma_mid)
    perf_hill = _hill(perf_ads, gt['performance_alpha'], gamma_mid)

    # Media contribution (normalized → scale to ₽)
    media_effect = (
        gt['tv_beta'] * tv_hill
        + gt['digital_beta'] * dig_hill
        + gt['ooh_beta'] * ooh_hill
        + gt['performance_beta'] * perf_hill
    )

    # Signed factor contributions (normalized controls × coef)
    control_effect = (
        gt['competitor_coef'] * comp_norm
        + gt['price_coef'] * price_norm
        + gt['holiday_newyear_coef'] * holiday_newyear_preshop
    )

    # Scale back to ₽
    y_norm_hat = media_effect + control_effect
    sales_rub = base + y_norm_hat * y_std_target + rng.normal(0, y_std_target * 0.05, n)
    sales_rub = sales_rub.clip(min=5e6)

    return pd.DataFrame({
        'date': dates,
        'sales_rub': np.round(sales_rub, 0).astype(int),
        'tv_spend': np.round(tv_spend, 0).astype(int),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'ooh_trp': np.round(ooh_trp, 1),
        'performance_clicks': np.round(performance_clicks, 0).astype(int),
        'competitor_trp': np.round(competitor_trp, 1),
        'price_index': np.round(price_index, 4),
        'holiday_newyear_preshop': holiday_newyear_preshop.astype(int),
    })


# ─── Dataset 2: OTC Pharma (Кагоцел-like) ────────────────────────────────────

def generate_otc_pharma(seed: int = 43) -> pd.DataFrame:
    """OTC pharma (Кагоцел-like) — 48 months (2022-01 → 2025-12).

    Channels: TV (TRP physical), Apteka_OOH (OTS physical), Digital (₽), Performance (clicks).
    Target: sales_packs (упаковки).
    Signed factors: competitor_trp (strong negative), weather_temp_low (positive).
    Note: strong Q4 seasonal peak (cold/flu season).
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_OTC_PHARMA
    n = 48
    dates = pd.date_range('2022-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()

    # ── Flu/cold seasonal pattern (strong Q4 + mild Q1 peak) ─────────────────
    # Oct-Dec strongest (months 10-12), Jan-Feb mild, rest flat
    seasonal_idx = np.where(
        np.isin(months, [10, 11, 12]), 2.0,
        np.where(np.isin(months, [1, 2, 3]), 1.4,
        np.where(np.isin(months, [4, 9]), 0.9, 0.6))
    )

    # ── Media inputs (OTC pharma, smaller budgets than FMCG) ─────────────────
    # TV TRP: 50–350 TRP/мес, heavier в Q4
    tv_trp = (
        rng.uniform(60, 280, n) * seasonal_idx
        * (1 + 0.12 * rng.standard_normal(n))
    ).clip(min=5)

    # Apteka OOH (аптечный рекламный носитель): OTS 200K–2M physical
    apteka_ooh_ots = (
        rng.uniform(300_000, 1_800_000, n) * (0.5 + 0.5 * seasonal_idx)
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=10_000)

    # Digital spend: 1–5 М₽/мес
    digital_spend = (
        rng.uniform(1e6, 4e6, n) * (0.7 + 0.3 * seasonal_idx)
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=1e5)

    # Performance clicks: 100K–600K
    performance_clicks = (
        digital_spend / 3e6 * rng.uniform(200_000, 600_000, n)
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=5_000)

    # ── Signed factors ────────────────────────────────────────────────────────
    # Competitor TRP (конкурент усиливается в сезон тоже, но с lag)
    competitor_trp = (
        rng.uniform(40, 300, n) * (0.6 + 0.4 * np.roll(seasonal_idx, 1))
        * (1 + 0.12 * rng.standard_normal(n))
    ).clip(min=0)

    # Weather: average temperature deviation from seasonal norm (°C).
    # Low temperature = positive effect. Sim: Oct-Mar cold, Apr-Sep warm.
    # weather_temp_low = max(0, -avg_temp_deviation) → positive when cold
    temp_base = -8 * np.cos(2 * np.pi * (months - 1) / 12)  # seasonal curve
    temp_noise = rng.normal(0, 3, n)
    avg_temp = temp_base + temp_noise  # negative in winter
    weather_temp_low = np.maximum(0, -avg_temp)  # positive when cold

    # Holiday: New Year preshop effect на продажи (подарки → аптека)
    holiday_newyear_preshop = ((months == 11) | (months == 12)).astype(float)

    # ── MMM ground truth outcome ──────────────────────────────────────────────
    base = gt['base_sales_packs']
    y_std_target = base * 0.30  # 30% волатильность из-за сезонности

    tv_norm = _normalize(tv_trp)
    apt_norm = _normalize(apteka_ooh_ots)
    dig_norm = _normalize(digital_spend)
    perf_norm = _normalize(performance_clicks)
    comp_norm = _normalize(competitor_trp)
    weather_norm = _normalize(weather_temp_low)

    tv_ads = _geometric_adstock(tv_norm, gt['tv_decay'])
    apt_ads = _geometric_adstock(apt_norm, gt['apteka_ooh_decay'])
    dig_ads = _geometric_adstock(dig_norm, gt['digital_decay'])
    perf_ads = _geometric_adstock(perf_norm, gt['performance_decay'])

    gamma_mid = 0.6
    tv_hill = _hill(tv_ads, gt['tv_alpha'], gamma_mid)
    apt_hill = _hill(apt_ads, gt['apteka_ooh_alpha'], gamma_mid)
    dig_hill = _hill(dig_ads, gt['digital_alpha'], gamma_mid)
    perf_hill = _hill(perf_ads, gt['performance_alpha'], gamma_mid)

    media_effect = (
        gt['tv_beta'] * tv_hill
        + gt['apteka_ooh_beta'] * apt_hill
        + gt['digital_beta'] * dig_hill
        + gt['performance_beta'] * perf_hill
    )

    # Seasonal uplift (separate from media — autonomous demand curve)
    seasonal_lift = 0.4 * (seasonal_idx - 1.0)  # normalized deviation

    control_effect = (
        gt['competitor_coef'] * comp_norm
        + gt['weather_temp_low_coef'] * weather_norm
        + gt['holiday_newyear_coef'] * holiday_newyear_preshop
        + seasonal_lift
    )

    y_norm_hat = media_effect + control_effect
    sales_packs = base + y_norm_hat * y_std_target + rng.normal(0, y_std_target * 0.05, n)
    sales_packs = sales_packs.clip(min=10_000)

    return pd.DataFrame({
        'date': dates,
        'sales_packs': np.round(sales_packs, 0).astype(int),
        'tv_trp': np.round(tv_trp, 1),
        'apteka_ooh_ots': np.round(apteka_ooh_ots, 0).astype(int),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'performance_clicks': np.round(performance_clicks, 0).astype(int),
        'competitor_trp': np.round(competitor_trp, 1),
        'weather_temp_low': np.round(weather_temp_low, 2),
        'holiday_newyear_preshop': holiday_newyear_preshop.astype(int),
        'avg_temp': np.round(avg_temp, 1),  # keep for reference
    })


# ─── Dataset 3: Ритейл сеть (Магнит-like) ────────────────────────────────────

def generate_retail_chain(seed: int = 44) -> pd.DataFrame:
    """Retail chain (Магнит-like) — 24 months (2024-01 → 2025-12).

    Channels: TV (₽), Digital (₽), OOH (OTS), Promo_indicator (binary control).
    Target: traffic (визиты в магазины, млн).
    Signed factors: competitor_trp, holiday_blackfriday, holiday_newyear.
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_RETAIL
    n = 24
    dates = pd.date_range('2024-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()

    # ── Retail seasonality: Aug-Sep back-to-school, Nov-Dec holiday shopping ─
    retail_seasonal = np.where(
        np.isin(months, [11, 12]), 1.6,
        np.where(np.isin(months, [8, 9]), 1.2,
        np.where(np.isin(months, [1, 2]), 0.85, 1.0))
    )

    # ── Media ─────────────────────────────────────────────────────────────────
    # TV: 50–200 М₽/мес (retail = массивные бюджеты)
    tv_spend = (
        rng.uniform(50e6, 180e6, n) * retail_seasonal
        * (1 + 0.08 * rng.standard_normal(n))
    ).clip(min=10e6)

    # Digital: 20–80 М₽/мес
    digital_spend = (
        rng.uniform(20e6, 70e6, n) * (0.7 + 0.3 * retail_seasonal)
        * (1 + 0.08 * rng.standard_normal(n))
    ).clip(min=5e6)

    # OOH (outdoor OTS): 10M–80M impressions
    ooh_ots = (
        rng.uniform(15e6, 75e6, n) * retail_seasonal
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=1e6)

    # Promo indicator: 1 = major nationwide promo active (random ~30% of months)
    # Higher probability in Q4
    promo_prob = np.where(np.isin(months, [10, 11, 12]), 0.6, 0.2)
    promo_indicator = (rng.uniform(0, 1, n) < promo_prob).astype(float)

    # ── Signed factors ────────────────────────────────────────────────────────
    competitor_trp = (
        rng.uniform(100, 500, n) * retail_seasonal
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=0)

    # Black Friday: ноябрь (last week, approximated at month level)
    holiday_blackfriday = (months == 11).astype(float)
    # New Year: декабрь
    holiday_newyear = (months == 12).astype(float)

    # ── MMM ground truth outcome ──────────────────────────────────────────────
    base = gt['base_traffic_visits']  # визитов/месяц
    y_std_target = base * 0.12

    tv_norm = _normalize(tv_spend)
    dig_norm = _normalize(digital_spend)
    ooh_norm = _normalize(ooh_ots)
    promo_norm = _normalize(promo_indicator)
    comp_norm = _normalize(competitor_trp)

    tv_ads = _geometric_adstock(tv_norm, gt['tv_decay'])
    dig_ads = _geometric_adstock(dig_norm, gt['digital_decay'])
    ooh_ads = _geometric_adstock(ooh_norm, gt['ooh_decay'])
    promo_ads = _geometric_adstock(promo_norm, gt['promo_decay'])

    gamma_mid = 0.6
    tv_hill = _hill(tv_ads, gt['tv_alpha'], gamma_mid)
    dig_hill = _hill(dig_ads, gt['digital_alpha'], gamma_mid)
    ooh_hill = _hill(ooh_ads, gt['ooh_alpha'], gamma_mid)
    promo_hill = _hill(promo_ads, gt['promo_alpha'], gamma_mid)

    media_effect = (
        gt['tv_beta'] * tv_hill
        + gt['digital_beta'] * dig_hill
        + gt['ooh_beta'] * ooh_hill
        + gt['promo_beta'] * promo_hill
    )

    seasonal_lift = 0.3 * (retail_seasonal - 1.0)
    control_effect = (
        gt['competitor_coef'] * comp_norm
        + gt['holiday_blackfriday_coef'] * holiday_blackfriday
        + gt['holiday_newyear_coef'] * holiday_newyear
        + seasonal_lift
    )

    y_norm_hat = media_effect + control_effect
    traffic = base + y_norm_hat * y_std_target + rng.normal(0, y_std_target * 0.04, n)
    traffic = traffic.clip(min=5e5)

    return pd.DataFrame({
        'date': dates,
        'traffic_visits': np.round(traffic, 0).astype(int),
        'tv_spend': np.round(tv_spend, 0).astype(int),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'ooh_ots': np.round(ooh_ots, 0).astype(int),
        'promo_indicator': promo_indicator.astype(int),
        'competitor_trp': np.round(competitor_trp, 1),
        'holiday_blackfriday': holiday_blackfriday.astype(int),
        'holiday_newyear': holiday_newyear.astype(int),
    })


# ─── Dataset 4: Застройщик (long sales cycle) ─────────────────────────────────

def generate_real_estate(seed: int = 45) -> pd.DataFrame:
    """Застройщик / devpeloper — 36 months (2023-01 → 2025-12).

    Channels: TV (₽), OOH (OTS), Digital (₽), Performance (clicks).
    Target: leads (заявки на покупку).
    Signed factors: competitor_trp, macro_cpi (negative), Q1/Q4 seasonality.
    Note: longer adstock decay (people consider purchase for months).
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_REAL_ESTATE
    n = 36
    dates = pd.date_range('2023-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()
    quarters = (months - 1) // 3 + 1  # 1, 2, 3, 4

    # ── Real estate seasonality: Q2/Q3 traditional season, Q4 year-end push ──
    re_seasonal = np.where(
        quarters == 1, 0.80,
        np.where(quarters == 4, 1.20, 1.05)
    )

    # ── Media ─────────────────────────────────────────────────────────────────
    # TV: 10–50 М₽/мес
    tv_spend = (
        rng.uniform(10e6, 45e6, n) * re_seasonal
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=2e6)

    # OOH: 5M–30M OTS
    ooh_ots = (
        rng.uniform(5e6, 25e6, n) * re_seasonal
        * (1 + 0.1 * rng.standard_normal(n))
    ).clip(min=5e5)

    # Digital: 5–20 М₽/мес
    digital_spend = (
        rng.uniform(5e6, 18e6, n) * re_seasonal
        * (1 + 0.08 * rng.standard_normal(n))
    ).clip(min=5e5)

    # Performance (target-ads clicks): 30K–300K
    performance_clicks = (
        digital_spend / 12e6 * rng.uniform(60_000, 280_000, n)
        * (1 + 0.12 * rng.standard_normal(n))
    ).clip(min=1_000)

    # ── Signed factors ────────────────────────────────────────────────────────
    competitor_trp = (
        rng.uniform(20, 150, n) * (0.8 + 0.2 * re_seasonal)
        * (1 + 0.15 * rng.standard_normal(n))
    ).clip(min=0)

    # Macro CPI (official РФ monthly CPI, ~1-2% monthly in 2023-24)
    # Base: 1.01/month trend + shocks; higher CPI → lower demand
    macro_cpi_monthly = (
        1.012 + 0.005 * rng.standard_normal(n)
    ).clip(0.995, 1.035)
    macro_cpi_cumulative = np.cumprod(macro_cpi_monthly)  # накопленный индекс

    # Q1 dummy (weak season for real estate)
    seasonality_q1 = (quarters == 1).astype(float)
    # Q4 dummy (year-end deals, mortgage rush before rate changes)
    seasonality_q4 = (quarters == 4).astype(float)

    # ── MMM ground truth outcome ──────────────────────────────────────────────
    base = gt['base_leads']
    y_std_target = base * 0.20

    tv_norm = _normalize(tv_spend)
    ooh_norm = _normalize(ooh_ots)
    dig_norm = _normalize(digital_spend)
    perf_norm = _normalize(performance_clicks)
    comp_norm = _normalize(competitor_trp)
    cpi_norm = _normalize(macro_cpi_cumulative)

    tv_ads = _geometric_adstock(tv_norm, gt['tv_decay'])
    ooh_ads = _geometric_adstock(ooh_norm, gt['ooh_decay'])
    dig_ads = _geometric_adstock(dig_norm, gt['digital_decay'])
    perf_ads = _geometric_adstock(perf_norm, gt['performance_decay'])

    gamma_mid = 0.6
    tv_hill = _hill(tv_ads, gt['tv_alpha'], gamma_mid)
    ooh_hill = _hill(ooh_ads, gt['ooh_alpha'], gamma_mid)
    dig_hill = _hill(dig_ads, gt['digital_alpha'], gamma_mid)
    perf_hill = _hill(perf_ads, gt['performance_alpha'], gamma_mid)

    media_effect = (
        gt['tv_beta'] * tv_hill
        + gt['ooh_beta'] * ooh_hill
        + gt['digital_beta'] * dig_hill
        + gt['performance_beta'] * perf_hill
    )

    control_effect = (
        gt['competitor_coef'] * comp_norm
        + gt['macro_cpi_coef'] * cpi_norm
        + gt['seasonality_q1_coef'] * seasonality_q1
        + gt['seasonality_q4_coef'] * seasonality_q4
    )

    y_norm_hat = media_effect + control_effect
    leads = base + y_norm_hat * y_std_target + rng.normal(0, y_std_target * 0.06, n)
    leads = leads.clip(min=50)

    return pd.DataFrame({
        'date': dates,
        'leads': np.round(leads, 0).astype(int),
        'tv_spend': np.round(tv_spend, 0).astype(int),
        'ooh_ots': np.round(ooh_ots, 0).astype(int),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'performance_clicks': np.round(performance_clicks, 0).astype(int),
        'competitor_trp': np.round(competitor_trp, 1),
        'macro_cpi_monthly': np.round(macro_cpi_monthly, 4),
        'macro_cpi_cumulative': np.round(macro_cpi_cumulative, 4),
        'seasonality_q1': seasonality_q1.astype(int),
        'seasonality_q4': seasonality_q4.astype(int),
    })


# ─── Main: generate all 4 datasets ────────────────────────────────────────────

if __name__ == '__main__':
    out_dir = Path(__file__).parent / 'synthetic_pilots'
    out_dir.mkdir(exist_ok=True)

    generators = [
        ('synth_fmcg_brand', generate_fmcg_brand),
        ('synth_otc_pharma', generate_otc_pharma),
        ('synth_retail_chain', generate_retail_chain),
        ('synth_real_estate', generate_real_estate),
    ]

    for name, gen in generators:
        df = gen()
        out_path = out_dir / f'{name}.xlsx'
        df.to_excel(out_path, index=False)
        print(f'Generated {name}: {len(df)} rows | {len(df.columns)} cols | {df.columns.tolist()}')
        print(f'  -> {out_path}')

    print(f'\nAll synthetic datasets generated in {out_dir}')
    print('\nGround truth summary (for prior recovery benchmarks):')
    for gt_name, gt in [
        ('FMCG', GROUND_TRUTH_FMCG),
        ('OTC Pharma', GROUND_TRUTH_OTC_PHARMA),
        ('Retail', GROUND_TRUTH_RETAIL),
        ('Real Estate', GROUND_TRUTH_REAL_ESTATE),
    ]:
        comp = gt.get('competitor_coef', 'n/a')
        print(f'  {gt_name}: competitor_coef={comp}')
