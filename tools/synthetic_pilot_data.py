"""
Synthetic РФ pilot data generator для Aurora MMM Optimizer v2.0.0 validation.

Replaces NDA-protected Кагоцел / Венарус pilot data для Phase E2 signed factor
priors calibration testing. Generated data имеет known ground-truth coefficients
(GROUND_TRUTH_* dicts), что позволяет verify prior recovery quantitatively.

Workflow:
    python tools/synthetic_pilot_data.py
    → tools/synthetic_pilots/*.xlsx  (working copies, ground-truth benchmarks)
    → static/sample-data/*.xlsx      (served «Попробовать на примере» SSOT)

SSOT contract (2026-06-07 redesign):
    Each category has ONE schema that is simultaneously (a) the empty template,
    (b) this filled «try me» example, and (c) the validator/export reference.
    Column names MUST classify correctly через utils.column_detection
    (нет `unknown`, нет mis-role) — gated в tests/test_sample_data_ssot.py.
    NO functionally-dependent columns (никаких reference-leak дублей вроде
    avg_temp ≡ -weather_temp_low или macro_cpi_cumulative ≡ cumprod(monthly)) —
    они раздувают номинальные параметры → бьют по честному MQS (effective params).
    Все наборы N ≥ 36 (monthly). real_estate намеренно «реалистично-тонкий» —
    показывает CI / коридор / мягкое предупреждение честных фич, а не идеальную
    картинку. fmcg / otc на TRP-входах — чистая фикстура под optimizer CPP.

Math model (identical to Aurora MMM):
    y[t] = intercept + Σ_i beta_i * hill(adstock(x_i[t])) + Σ_j coef_j * z_j[t] + ε[t]

    adstock(x[t]) = x[t] + decay * adstock(x[t-1])   (geometric)
    hill(x, alpha, gamma) = x^alpha / (x^alpha + gamma^alpha)

All values в реалистичных РФ FMCG / OTC pharma / retail / real-estate диапазонах.
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

GROUND_TRUTH_RETAIL_ECOM = {
    # Media
    'tv_beta': 0.30,
    'digital_beta': 0.40,
    'ooh_beta': 0.18,
    'retail_media_beta': 0.35,     # Ozon/WB реклама — сильный performance-канал
    'tv_decay': 0.55,
    'digital_decay': 0.30,
    'ooh_decay': 0.50,
    'retail_media_decay': 0.25,    # retail media эффект быстрый
    'tv_alpha': 2.0,
    'digital_alpha': 1.8,
    'ooh_alpha': 1.6,
    'retail_media_alpha': 1.8,
    # Signed / positive controls
    'promo_coef': 0.16,            # promo_indicator (positive control)
    'competitor_promo_coef': -0.14,  # промо конкурента давит наши продажи
    'holiday_blackfriday_coef': 0.20,
    'holiday_newyear_coef': 0.25,
    'base_sales_rub': 150_000_000,   # ₽/месяц average base (e-com ритейлер)
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
    'holiday_newyear_coef': 0.12,  # декабрь: year-end push сделок (МОДЕЛИРУЕМАЯ dummy)
    'base_leads': 850,             # заявок/месяц average
    # NB: магнитуда baked-сезонности Q1/Q4 — литерал 0.50 в generate_real_estate
    # (НЕ prior-recovery target; согласовано с OTC/retail, где она тоже хардкод).
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


def _indep_channel(
    rng: np.random.Generator,
    months: np.ndarray,
    lo: float,
    hi: float,
    peak_months: tuple = (),
    peak_amp: float = 0.0,
    vol: float = 0.30,
    floor: float | None = None,
) -> np.ndarray:
    """Independent media channel series — own level + own seasonal peak + own flighting.

    Identifiability (anti-collinearity): каждый канал тянет СОБСТВЕННЫЙ uniform-draw +
    канал-специфичный сезонный пик (разные месяцы у разных каналов) + большой
    идиосинкразический month-to-month разброс. Это даёт OLS leverage разделить
    каналы (vs старый дизайн «все × один сезонный индекс» → коллинеар → sign-flips).
    Последовательные rng-вызовы → каналы статистически независимы.
    """
    n = len(months)
    level = rng.uniform(lo, hi, n)
    if peak_months and peak_amp:
        level = level * (1.0 + peak_amp * np.isin(months, peak_months).astype(float))
    series = level * (1.0 + vol * rng.standard_normal(n))
    return series.clip(min=(floor if floor is not None else lo * 0.15))


# ─── Dataset 1: FMCG бренд массмаркет ────────────────────────────────────────

def generate_fmcg_brand(seed: int = 42) -> pd.DataFrame:
    """FMCG бренд массмаркет — 36 months (2023-01 → 2025-12).

    Channels: TV (₽ spend), Digital (₽), OOH (TRP physical), Performance (clicks physical).
    Target: sales_rub (₽ выручка).
    Signed factors: competitor_trp, price_index, holiday_newyear.
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_FMCG
    n = 36
    dates = pd.date_range('2023-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()

    # ── Media inputs (independent flighting + staggered per-channel seasonality) ─
    # Каждый канал — свой пик в разные месяцы → разделимы OLS (anti-collinearity).
    # TV: 4–13 М₽/мес, пик Q4 + Jan reactivation
    tv_spend = _indep_channel(rng, months, 4e6, 13e6, peak_months=(11, 12, 1), peak_amp=0.40, vol=0.28)
    # Digital: 3–9 М₽/мес, always-on (flat)
    digital_spend = _indep_channel(rng, months, 3e6, 9e6, vol=0.30)
    # OOH: 60–280 TRP, летний outdoor пик (Q2/Q3)
    ooh_trp = _indep_channel(rng, months, 60, 280, peak_months=(5, 6, 7, 8), peak_amp=0.35, vol=0.30, floor=10)
    # Performance (clicks): НЕЗАВИСИМ от digital, весна/осень пульсы
    performance_clicks = _indep_channel(rng, months, 150_000, 850_000, peak_months=(3, 9, 10), peak_amp=0.25, vol=0.32, floor=10_000)

    # ── Signed factor controls (независимы от медиа) ──────────────────────────
    competitor_trp = _indep_channel(rng, months, 30, 200, peak_months=(2, 3, 8), peak_amp=0.25, vol=0.28, floor=0.0)

    # Price index (1.0 = base; >1 = higher price). Mild inflation trend + noise.
    price_index = 1.0 + 0.02 * np.arange(n) / n + 0.03 * rng.standard_normal(n)
    price_index = price_index.clip(0.85, 1.25)

    # Holiday: New Year pre-shop (Nov 15 – Dec 31) → months 11, 12
    holiday_newyear = ((months == 11) | (months == 12)).astype(float)

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
        + gt['holiday_newyear_coef'] * holiday_newyear
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
        'holiday_newyear': holiday_newyear.astype(int),
    })


# ─── Dataset 2: OTC Pharma (Кагоцел-like) ────────────────────────────────────

def generate_otc_pharma(seed: int = 43) -> pd.DataFrame:
    """OTC pharma (Кагоцел-like) — 48 months (2022-01 → 2025-12).

    Channels: TV (TRP physical), Apteka_OOH (contacts physical), Digital (₽), Performance (clicks).
    Target: sales_packs (упаковки).
    Signed factors: competitor_trp (strong negative), weather_temp_low (positive).
    Note: strong Q4 seasonal peak (cold/flu season) baked into demand curve.
    SSOT: single weather control (НЕТ дубля avg_temp ≡ -weather_temp_low).
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

    # ── Media inputs (independent flighting; НЕ всё привязано к flu-сезону) ───
    # TV TRP: 60–300, mild Q4 lean но сильное собственное flighting
    tv_trp = _indep_channel(rng, months, 60, 300, peak_months=(10, 11, 12), peak_amp=0.35, vol=0.30, floor=5)
    # Apteka OOH contacts: 300K–1.8M, ранне-годовые кампании
    apteka_ooh_contacts = _indep_channel(rng, months, 300_000, 1_800_000, peak_months=(1, 2, 3), peak_amp=0.30, vol=0.30, floor=10_000)
    # Digital: 1–4.5 М₽/мес, flat
    digital_spend = _indep_channel(rng, months, 1e6, 4.5e6, vol=0.30, floor=1e5)
    # Performance clicks: НЕЗАВИСИМ, осенние пульсы
    performance_clicks = _indep_channel(rng, months, 100_000, 600_000, peak_months=(9, 10), peak_amp=0.25, vol=0.32, floor=5_000)

    # ── Signed factors (независимы от медиа) ──────────────────────────────────
    competitor_trp = _indep_channel(rng, months, 40, 300, peak_months=(4, 5, 9), peak_amp=0.25, vol=0.30, floor=0.0)

    # Weather: cold-weather intensity (°C below zero). Positive effect on OTC sales.
    # Single signed control (НЕ держим вторую avg_temp колонку — она была бы
    # детерминированной функцией этой → коллинеар, бьёт по effective params).
    temp_base = -8 * np.cos(2 * np.pi * (months - 1) / 12)  # seasonal curve
    temp_noise = rng.normal(0, 3, n)
    avg_temp_internal = temp_base + temp_noise  # negative in winter (internal only)
    weather_temp_low = np.maximum(0, -avg_temp_internal)  # positive when cold

    # Holiday: New Year preshop effect на продажи (подарки → аптека)
    holiday_newyear = ((months == 11) | (months == 12)).astype(float)

    # ── MMM ground truth outcome ──────────────────────────────────────────────
    base = gt['base_sales_packs']
    y_std_target = base * 0.30  # 30% волатильность из-за сезонности

    tv_norm = _normalize(tv_trp)
    apt_norm = _normalize(apteka_ooh_contacts)
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

    # Seasonal uplift (separate from media — autonomous demand curve).
    # Уменьшен (0.4→0.15): меньше «бесхозного» сезонного сигнала, который раздувал
    # base и конфаундил weather/holiday; спрос объясняют каналы + weather + holiday.
    seasonal_lift = 0.15 * (seasonal_idx - 1.0)

    control_effect = (
        gt['competitor_coef'] * comp_norm
        + gt['weather_temp_low_coef'] * weather_norm
        + gt['holiday_newyear_coef'] * holiday_newyear
        + seasonal_lift
    )

    y_norm_hat = media_effect + control_effect
    sales_packs = base + y_norm_hat * y_std_target + rng.normal(0, y_std_target * 0.05, n)
    sales_packs = sales_packs.clip(min=10_000)

    return pd.DataFrame({
        'date': dates,
        'sales_packs': np.round(sales_packs, 0).astype(int),
        'tv_trp': np.round(tv_trp, 1),
        'apteka_ooh_contacts': np.round(apteka_ooh_contacts, 0).astype(int),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'performance_clicks': np.round(performance_clicks, 0).astype(int),
        'competitor_trp': np.round(competitor_trp, 1),
        'weather_temp_low': np.round(weather_temp_low, 2),
        'holiday_newyear': holiday_newyear.astype(int),
    })


# ─── Dataset 3: Ритейл e-com (Ozon/WB продавец) ───────────────────────────────

def generate_retail_ecom(seed: int = 44) -> pd.DataFrame:
    """Retail e-commerce — 36 months (2023-01 → 2025-12).

    Channels: TV (₽), Digital (₽), OOH (contacts physical), Retail Media (₽ Ozon/WB).
    Target: sales_rub (₽ выручка) — денежный KPI, режим ROI доступен.
    Controls: promo_indicator (positive), competitor_promo (signed negative),
              holiday_blackfriday, holiday_newyear.
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_RETAIL_ECOM
    n = 36
    dates = pd.date_range('2023-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()

    # ── Retail seasonality: Aug-Sep back-to-school, Nov-Dec holiday shopping ─
    retail_seasonal = np.where(
        np.isin(months, [11, 12]), 1.55,
        np.where(np.isin(months, [8, 9]), 1.2,
        np.where(np.isin(months, [1, 2]), 0.85, 1.0))
    )

    # ── Media (independent flighting + staggered peaks) ───────────────────────
    # TV: 40–130 М₽/мес, Q4 пик
    tv_spend = _indep_channel(rng, months, 40e6, 130e6, peak_months=(11, 12), peak_amp=0.40, vol=0.26, floor=8e6)
    # Digital: 20–60 М₽/мес, flat
    digital_spend = _indep_channel(rng, months, 20e6, 60e6, vol=0.28, floor=5e6)
    # OOH contacts: 15M–65M, back-to-school пик (Q3)
    ooh_contacts = _indep_channel(rng, months, 15e6, 65e6, peak_months=(8, 9), peak_amp=0.35, vol=0.30, floor=1e6)
    # Retail media (Ozon/WB): 8–40 М₽/мес, sale-event пульсы разнесены (Mar/Jul/Nov)
    retail_media_spend = _indep_channel(rng, months, 8e6, 40e6, peak_months=(3, 7, 11), peak_amp=0.40, vol=0.30, floor=2e6)

    # ── Controls ───────────────────────────────────────────────────────────────
    # Promo indicator: 1 = major nationwide promo active. Higher probability in Q4.
    promo_prob = np.where(np.isin(months, [10, 11, 12]), 0.6, 0.25)
    promo_indicator = (rng.uniform(0, 1, n) < promo_prob).astype(float)

    # Competitor promo activity (index 0.05–1.5, независим от нашего сезона). Signed negative.
    competitor_promo = (
        rng.uniform(0.2, 1.0, n) * (1 + 0.25 * rng.standard_normal(n))
    ).clip(0.05, 1.5)

    # Black Friday: ноябрь; New Year: декабрь
    holiday_blackfriday = (months == 11).astype(float)
    holiday_newyear = (months == 12).astype(float)

    # ── MMM ground truth outcome ──────────────────────────────────────────────
    base = gt['base_sales_rub']
    y_std_target = base * 0.16

    tv_norm = _normalize(tv_spend)
    dig_norm = _normalize(digital_spend)
    ooh_norm = _normalize(ooh_contacts)
    rm_norm = _normalize(retail_media_spend)
    promo_norm = _normalize(promo_indicator)
    comp_norm = _normalize(competitor_promo)

    tv_ads = _geometric_adstock(tv_norm, gt['tv_decay'])
    dig_ads = _geometric_adstock(dig_norm, gt['digital_decay'])
    ooh_ads = _geometric_adstock(ooh_norm, gt['ooh_decay'])
    rm_ads = _geometric_adstock(rm_norm, gt['retail_media_decay'])

    gamma_mid = 0.6
    tv_hill = _hill(tv_ads, gt['tv_alpha'], gamma_mid)
    dig_hill = _hill(dig_ads, gt['digital_alpha'], gamma_mid)
    ooh_hill = _hill(ooh_ads, gt['ooh_alpha'], gamma_mid)
    rm_hill = _hill(rm_ads, gt['retail_media_alpha'], gamma_mid)

    media_effect = (
        gt['tv_beta'] * tv_hill
        + gt['digital_beta'] * dig_hill
        + gt['ooh_beta'] * ooh_hill
        + gt['retail_media_beta'] * rm_hill
    )

    seasonal_lift = 0.3 * (retail_seasonal - 1.0)
    control_effect = (
        gt['promo_coef'] * promo_norm
        + gt['competitor_promo_coef'] * comp_norm
        + gt['holiday_blackfriday_coef'] * holiday_blackfriday
        + gt['holiday_newyear_coef'] * holiday_newyear
        + seasonal_lift
    )

    y_norm_hat = media_effect + control_effect
    sales_rub = base + y_norm_hat * y_std_target + rng.normal(0, y_std_target * 0.05, n)
    sales_rub = sales_rub.clip(min=20e6)

    return pd.DataFrame({
        'date': dates,
        'sales_rub': np.round(sales_rub, 0).astype(int),
        'tv_spend': np.round(tv_spend, 0).astype(int),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'ooh_contacts': np.round(ooh_contacts, 0).astype(int),
        'retail_media_spend': np.round(retail_media_spend, 0).astype(int),
        'promo_indicator': promo_indicator.astype(int),
        'competitor_promo': np.round(competitor_promo, 3),
        'holiday_blackfriday': holiday_blackfriday.astype(int),
        'holiday_newyear': holiday_newyear.astype(int),
    })


# ─── Dataset 4: Застройщик (long sales cycle, «реалистично-тонкий» showcase) ──

def generate_real_estate(seed: int = 45) -> pd.DataFrame:
    """Застройщик / девелопер — 36 months (2023-01 → 2025-12).

    Channels: TV (₽), OOH (contacts), Digital (₽), Performance (clicks).
    Target: leads (заявки на покупку).
    Signed factors: competitor_activity, macro_cpi (single index, negative).
    SSOT: единственный macro контроль (НЕТ дубля cpi_monthly + cpi_cumulative);
    сезонность Q1/Q4 baked в demand curve (auto-injected программой), не dummy-колонки.
    Намеренно «реалистично-тонкий» — выше шум наблюдений → честные CI / коридор.
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_REAL_ESTATE
    n = 36
    dates = pd.date_range('2023-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()
    quarters = (months - 1) // 3 + 1  # 1, 2, 3, 4

    # ── Real estate seasonality: Q1 слабый, Q4 year-end push (baked in demand) ─
    re_seasonal = np.where(
        quarters == 1, 0.80,
        np.where(quarters == 4, 1.20, 1.05)
    )

    # ── Media (independent flighting + staggered peaks) ───────────────────────
    # TV: 10–45 М₽/мес, осенний push
    tv_spend = _indep_channel(rng, months, 10e6, 45e6, peak_months=(9, 10, 11), peak_amp=0.30, vol=0.30, floor=2e6)
    # OOH contacts: 5M–25M, весенний пик
    ooh_contacts = _indep_channel(rng, months, 5e6, 25e6, peak_months=(4, 5), peak_amp=0.30, vol=0.30, floor=5e5)
    # Digital: 5–18 М₽/мес, flat
    digital_spend = _indep_channel(rng, months, 5e6, 18e6, vol=0.30, floor=5e5)
    # Performance: НЕЗАВИСИМ от digital, весна/осень пульсы
    performance_clicks = _indep_channel(rng, months, 60_000, 280_000, peak_months=(3, 9), peak_amp=0.25, vol=0.32, floor=1_000)

    # ── Signed factors (независимы от медиа) ──────────────────────────────────
    competitor_activity = _indep_channel(rng, months, 20, 150, peak_months=(6, 7), peak_amp=0.20, vol=0.30, floor=0.0)

    # Macro CPI — single cumulative index (~1.0 → ~1.5 over 3y). Higher → lower demand.
    # Один контроль: НЕ держим вторую monthly-колонку (cumulative ≡ cumprod(monthly)).
    macro_cpi_monthly_internal = (
        1.012 + 0.005 * rng.standard_normal(n)
    ).clip(0.995, 1.035)
    macro_cpi = np.cumprod(macro_cpi_monthly_internal)  # накопленный индекс (level)

    # ── MMM ground truth outcome ──────────────────────────────────────────────
    base = gt['base_leads']
    y_std_target = base * 0.20

    tv_norm = _normalize(tv_spend)
    ooh_norm = _normalize(ooh_contacts)
    dig_norm = _normalize(digital_spend)
    perf_norm = _normalize(performance_clicks)
    comp_norm = _normalize(competitor_activity)
    cpi_norm = _normalize(macro_cpi)

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

    # Baked Q1/Q4 сезонность в demand curve — магнитуда литералом (НЕ recovery-target,
    # как и хардкод 0.15 в OTC / 0.30 в retail). Auto-injected программой, не dummy.
    seasonal_lift = 0.50 * (re_seasonal - 1.0)
    # holiday_newyear — единственная ЯВНАЯ dummy real_estate (декабрьский year-end push).
    # МОДЕЛИРУЕТСЯ (есть и в GROUND_TRUTH, и в control_effect) → не колонка-шум.
    holiday_newyear = (months == 12).astype(float)

    control_effect = (
        gt['competitor_coef'] * comp_norm
        + gt['macro_cpi_coef'] * cpi_norm
        + gt['holiday_newyear_coef'] * holiday_newyear
        + seasonal_lift
    )

    y_norm_hat = media_effect + control_effect
    # Намеренно выше шум (0.10 vs 0.05–0.06 у других) → реалистично-тонкий пример,
    # показывает честные CI / коридор / мягкое предупреждение, а не идеальную картинку.
    leads = base + y_norm_hat * y_std_target + rng.normal(0, y_std_target * 0.10, n)
    leads = leads.clip(min=50)

    return pd.DataFrame({
        'date': dates,
        'leads': np.round(leads, 0).astype(int),
        'tv_spend': np.round(tv_spend, 0).astype(int),
        'ooh_contacts': np.round(ooh_contacts, 0).astype(int),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'performance_clicks': np.round(performance_clicks, 0).astype(int),
        'competitor_activity': np.round(competitor_activity, 1),
        'macro_cpi': np.round(macro_cpi, 4),
        'holiday_newyear': holiday_newyear.astype(int),
    })


# ─── Main: generate all 4 datasets → working copies + served SSOT ─────────────

# (id, generator, served filename). Served filename = SSOT в static/sample-data/.
GENERATORS = [
    ('synth_fmcg_brand', generate_fmcg_brand),
    ('synth_otc_pharma', generate_otc_pharma),
    ('synth_retail_ecom', generate_retail_ecom),
    ('synth_real_estate', generate_real_estate),
]

GROUND_TRUTH_BY_NAME = {
    'synth_fmcg_brand': GROUND_TRUTH_FMCG,
    'synth_otc_pharma': GROUND_TRUTH_OTC_PHARMA,
    'synth_retail_ecom': GROUND_TRUTH_RETAIL_ECOM,
    'synth_real_estate': GROUND_TRUTH_REAL_ESTATE,
}


def _write_all(verbose: bool = True) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    work_dir = Path(__file__).parent / 'synthetic_pilots'
    served_dir = repo_root / 'static' / 'sample-data'
    work_dir.mkdir(exist_ok=True)
    served_dir.mkdir(parents=True, exist_ok=True)

    for name, gen in GENERATORS:
        df = gen()
        for out_dir in (work_dir, served_dir):
            df.to_excel(out_dir / f'{name}.xlsx', index=False, sheet_name='Данные')
        if verbose:
            print(f'Generated {name}: {len(df)} rows | {len(df.columns)} cols | {df.columns.tolist()}')

    if verbose:
        print(f'\nWorking copies → {work_dir}')
        print(f'Served SSOT    → {served_dir}')
        print('NB: build/sample-data + .svelte-kit/output — это build-артефакты, '
              'регенерируются `npm run build` (не пишутся генератором).')
        print('\nGround truth summary (for prior recovery benchmarks):')
        for name, gt in GROUND_TRUTH_BY_NAME.items():
            comp = gt.get('competitor_coef') or gt.get('competitor_promo_coef', 'n/a')
            print(f'  {name}: competitor_coef={comp}')


if __name__ == '__main__':
    _write_all()
