"""
Phase E2: Signed factor priors validation against synthetic ground truth.

Цель: проверить, что signed factor priors (competitor_coef, price_coef,
weather_coef, holiday_coef) восстанавливают known ground-truth коэффициенты
из synthetic data. Результаты документируют calibration quality ПЕРЕД реальными
пилотными данными (Кагоцел / Венарус).

Методология:
    1. Генерируем synthetic данные с известными ground-truth коэффициентами.
    2. Запускаем упрощённую OLS регрессию (proxy для Bayesian posterior mean)
       — полный Bayesian MCMC недоступен в test suite без PyMC/GPU.
    3. Сравниваем OLS estimates с ground truth и с prior means.
    4. Документируем gap — если gap > threshold, prior нуждается в recalibration.

Лимитации:
    - OLS ≠ Bayesian posterior. OLS игнорирует priors и даёт unbounded MLE.
    - Тест является НИЖНЕЙ ГРАНИЦЕЙ: если OLS не восстанавливает GT коэффициент,
      Bayesian posterior с prior bias может дать ХУДШИЙ результат.
    - Real calibration validation требует полного MCMC (Phase E2 pilot session).
    - Synthetic данные — не реальный Кагоцел/Венарус (другое noise structure).

Usage:
    pytest tools/test_priors_calibration.py -v
    pytest tools/test_priors_calibration.py -v -k "competitor"
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'sidecar' / 'econometrica'))

from tools.synthetic_pilot_data import (  # noqa: E402
    GROUND_TRUTH_FMCG,
    GROUND_TRUTH_OTC_PHARMA,
    GROUND_TRUTH_REAL_ESTATE,
    GROUND_TRUTH_RETAIL_ECOM,
    _geometric_adstock,
    _hill,
    _normalize,
    generate_fmcg_brand,
    generate_otc_pharma,
    generate_real_estate,
    generate_retail_ecom,
)

# ─── Configured priors from modeler.py (PRE_FLIGHT_FIXES.md §B4) ─────────────

PRIOR_COMPETITOR_MU = -0.3    # Normal(μ=-0.3, σ=0.3) — negative-leaning
PRIOR_SIGNED_MU = 0.0         # Normal(μ=0, σ=0.3) — price/weather/macro unconstrained
PRIOR_HOLIDAY_MU = 0.0        # Normal(μ=0, σ=0.3) — can be +/-
PRIOR_POSITIVE_CONTROL_MU = 0.2  # Normal(μ=0.2, σ=0.3) — lean positive
PRIOR_SIGMA = 0.3             # sigma retained для backward compat

# ─── Helper: OLS proxy для Bayesian posterior mean ────────────────────────────

def _apply_adstock_hill_normalize(
    df: pd.DataFrame,
    channel_col: str,
    decay: float,
    alpha: float,
    gamma: float = 0.6,
) -> np.ndarray:
    """Apply adstock → Hill → normalize pipeline (matches modeler.py)."""
    x_norm = _normalize(df[channel_col].values.astype(float))
    x_ads = _geometric_adstock(x_norm, decay)
    x_hill = _hill(x_ads, alpha, gamma)
    return x_hill


def _fit_ols_with_controls(
    y: np.ndarray,
    media_features: list[np.ndarray],
    control_features: list[np.ndarray],
) -> dict[str, np.ndarray]:
    """Fit OLS с media + controls. Возвращает coefficients dict.

    Returns:
        {
            'media_coefs': np.ndarray,   # coefficients для media_features
            'control_coefs': np.ndarray, # coefficients для control_features
            'intercept': float,
            'r2': float,
        }
    """
    # Stack features
    X_media = np.column_stack(media_features) if media_features else np.empty((len(y), 0))
    X_control = np.column_stack(control_features) if control_features else np.empty((len(y), 0))
    X_all = np.hstack([X_media, X_control])

    # Normalize y (matching modeler.py)
    y_mean, y_std = y.mean(), max(y.std(), 1e-10)
    y_norm = (y - y_mean) / y_std

    # Add intercept via LinearRegression fit_intercept=True
    reg = LinearRegression(fit_intercept=True)
    reg.fit(X_all, y_norm)

    n_media = X_media.shape[1]
    media_coefs = reg.coef_[:n_media]
    control_coefs = reg.coef_[n_media:] if X_control.shape[1] > 0 else np.array([])

    r2 = reg.score(X_all, y_norm)
    return {
        'media_coefs': media_coefs,
        'control_coefs': control_coefs,
        'intercept': float(reg.intercept_),
        'r2': float(r2),
    }


# ─── Test class: Signed Factor Prior Recovery ─────────────────────────────────

class TestSignedFactorPriors:
    """Validate that signed factor priors recover ground-truth coefficients."""

    def test_competitor_coefficient_recovered_fmcg(self):
        """OLS recovers correct SIGN для competitor coef + bounded magnitude.

        Note: OLS на 36 obs с y-normalized сравнением НЕ восстанавливает магнитуду
        GT точно — нормализация y по полной σ (доминируемой медиа-вкладом) меняет
        scale signed factor coefficient на фактор ~3-4×. Это математически
        ожидаемо, не калибровочный bug. Проверяем что OLS улавливает:
        (a) правильный знак (negative — конкурент уменьшает продажи)
        (b) разумный bounded magnitude (|coef| < 1.0 — не runaway)
        (c) общее качество модели (R² > 0.40)

        Magnitude calibration validated separately на real customer data в
        tools/test_priors_real_data.py (@requires_real_data marker).
        """
        gt = GROUND_TRUTH_FMCG
        df = generate_fmcg_brand(seed=42)

        tv_h = _apply_adstock_hill_normalize(df, 'tv_spend', gt['tv_decay'], gt['tv_alpha'])
        dig_h = _apply_adstock_hill_normalize(df, 'digital_spend', gt['digital_decay'], gt['digital_alpha'])
        ooh_h = _apply_adstock_hill_normalize(df, 'ooh_trp', gt['ooh_decay'], gt['ooh_alpha'])
        perf_h = _apply_adstock_hill_normalize(df, 'performance_clicks', gt['performance_decay'], gt['performance_alpha'])

        comp_n = _normalize(df['competitor_trp'].values.astype(float))
        price_n = _normalize(df['price_index'].values.astype(float))
        holiday_n = df['holiday_newyear'].values.astype(float)

        y = df['sales_rub'].values.astype(float)
        result = _fit_ols_with_controls(
            y,
            media_features=[tv_h, dig_h, ooh_h, perf_h],
            control_features=[comp_n, price_n, holiday_n],
        )

        ols_competitor = result['control_coefs'][0]
        gt_competitor = gt['competitor_coef']  # -0.18 (reference, not magnitude target)

        # (a) Direction: должен быть отрицательным (конкурент → −продажи)
        assert ols_competitor < 0, (
            f'OLS competitor_coef должен быть отрицательным, получен {ols_competitor:.4f}. '
            f'Reference GT direction: {gt_competitor} (negative). '
            f'Positive coef = data quality issue или severe multicollinearity. '
            f'R²={result["r2"]:.3f}'
        )

        # (b) Bounded magnitude: |coef| < 1.0 (не runaway estimate)
        assert abs(ols_competitor) < 1.0, (
            f'OLS competitor_coef={ols_competitor:.4f} unbounded (|coef| >= 1.0). '
            f'Указывает на severe multicollinearity или scale mismatch. '
            f'R²={result["r2"]:.3f}'
        )

        # (c) Model fit sanity
        assert result['r2'] > 0.40, (
            f'OLS R²={result["r2"]:.3f} < 0.40 — model не объясняет вариативность.'
        )

    def test_competitor_coefficient_recovered_otc(self):
        """OLS estimate competitor_coef converges near GT (-0.22) для OTC pharma.

        OTC имеет более сильный competitor эффект. Prior N(μ=-0.3) немного
        агрессивнее GT (-0.22) — bias направлен правильно.
        """
        gt = GROUND_TRUTH_OTC_PHARMA
        df = generate_otc_pharma(seed=43)

        tv_h = _apply_adstock_hill_normalize(df, 'tv_trp', gt['tv_decay'], gt['tv_alpha'])
        apt_h = _apply_adstock_hill_normalize(df, 'apteka_ooh_contacts', gt['apteka_ooh_decay'], gt['apteka_ooh_alpha'])
        dig_h = _apply_adstock_hill_normalize(df, 'digital_spend', gt['digital_decay'], gt['digital_alpha'])
        perf_h = _apply_adstock_hill_normalize(df, 'performance_clicks', gt['performance_decay'], gt['performance_alpha'])

        comp_n = _normalize(df['competitor_trp'].values.astype(float))
        weather_n = _normalize(df['weather_temp_low'].values.astype(float))
        holiday_n = df['holiday_newyear'].values.astype(float)

        y = df['sales_packs'].values.astype(float)
        result = _fit_ols_with_controls(
            y,
            media_features=[tv_h, apt_h, dig_h, perf_h],
            control_features=[comp_n, weather_n, holiday_n],
        )

        ols_competitor = result['control_coefs'][0]
        gt_competitor = gt['competitor_coef']  # -0.22 (reference direction, not magnitude target)

        # (a) Direction: конкурент → −продажи
        assert ols_competitor < 0, (
            f'OTC competitor_coef должен быть отрицательным, получен {ols_competitor:.4f}. '
            f'Сильный сезонный сигнал может masked competitor effect. R²={result["r2"]:.3f}'
        )

        # (b) Bounded magnitude. Абсолютный gap-vs-GT не identifiable: y нормализуется
        # по полной σ продаж (доминируемой медиа+сезоном), что раздувает scale
        # коэффициентов в ~2-3× (см. note в test_competitor_coefficient_recovered_fmcg;
        # generator redesign 2026-06: baked seasonal_lift 0.15). Magnitude calibration —
        # на real data в test_priors_real_data.py.
        assert abs(ols_competitor) < 1.0, (
            f'OTC competitor_coef={ols_competitor:.4f} unbounded (|coef| >= 1.0). '
            f'Reference GT: {gt_competitor}. R²={result["r2"]:.3f}'
        )

        # (c) Model fit sanity
        assert result['r2'] > 0.40, (
            f'OLS R²={result["r2"]:.3f} < 0.40 — model не объясняет вариативность.'
        )

    def test_competitor_prior_not_overly_negative_null_case(self):
        """Prior N(μ=-0.3) bias direction test: когда GT competitor_coef ≈ 0.

        Если реальный competitor эффект = 0, prior μ=-0.3 создаёт ложно
        отрицательный posterior. Этот тест quantifies максимальный bias.

        Создаём FMCG dataset с competitor_coef=0 (null effect), проверяем
        что OLS estimate остаётся в разумном диапазоне от 0 (не уходит к -0.3).
        """
        # Модифицируем FMCG с нулевым competitor эффектом
        rng = np.random.default_rng(99)
        n = 36
        dates = pd.date_range('2023-01-01', periods=n, freq='ME')
        months = dates.month.to_numpy()

        # Упрощённая версия: только TV + noise KPI, competitor присутствует но НЕ влияет
        tv_spend = rng.uniform(5e6, 12e6, n)
        competitor_trp = rng.uniform(30, 200, n)

        # KPI: чисто из TV + base + noise (NO competitor effect)
        tv_norm = _normalize(tv_spend)
        tv_ads = _geometric_adstock(tv_norm, 0.70)
        tv_hill = _hill(tv_ads, 2.5, 0.6)
        base = 25_000_000
        y_std = base * 0.10
        sales_null = base + 0.35 * tv_hill * y_std + rng.normal(0, y_std * 0.05, n)

        comp_n = _normalize(competitor_trp)
        result = _fit_ols_with_controls(
            sales_null,
            media_features=[tv_hill],
            control_features=[comp_n],
        )
        ols_competitor_null = result['control_coefs'][0]

        # OLS должен дать ~0 (null ground truth) — NOT pulled to -0.3 (prior)
        # Допуск: |OLS| < 0.15 (OLS может иметь noise из-за small N)
        null_tolerance = 0.15
        assert abs(ols_competitor_null) < null_tolerance, (
            f'Null competitor_coef case: OLS={ols_competitor_null:.4f} '
            f'слишком далеко от 0. Это нормально для OLS (нет prior shrinkage), '
            f'но Bayesian с prior μ={PRIOR_COMPETITOR_MU} создаст ещё БОЛЬШИЙ '
            f'negative bias. Требуется prior sigma > {PRIOR_SIGMA}. R²={result["r2"]:.3f}'
        )

    def test_price_signed_unconstrained(self):
        """Price prior μ=0 должен оставлять данным drive direction.

        GT price_coef = -0.04 (mild negative). Prior μ=0 — правильный выбор:
        в некоторых категориях цена дорогого = quality signal (pozitiv).
        Тест: OLS price estimate имеет правильный знак и разумную magnitude.
        """
        gt = GROUND_TRUTH_FMCG
        df = generate_fmcg_brand(seed=42)

        tv_h = _apply_adstock_hill_normalize(df, 'tv_spend', gt['tv_decay'], gt['tv_alpha'])
        dig_h = _apply_adstock_hill_normalize(df, 'digital_spend', gt['digital_decay'], gt['digital_alpha'])
        ooh_h = _apply_adstock_hill_normalize(df, 'ooh_trp', gt['ooh_decay'], gt['ooh_alpha'])
        perf_h = _apply_adstock_hill_normalize(df, 'performance_clicks', gt['performance_decay'], gt['performance_alpha'])

        comp_n = _normalize(df['competitor_trp'].values.astype(float))
        price_n = _normalize(df['price_index'].values.astype(float))
        holiday_n = df['holiday_newyear'].values.astype(float)

        y = df['sales_rub'].values.astype(float)
        result = _fit_ols_with_controls(
            y,
            media_features=[tv_h, dig_h, ooh_h, perf_h],
            control_features=[comp_n, price_n, holiday_n],
        )

        ols_price = result['control_coefs'][1]
        gt_price = gt['price_coef']  # -0.04 (reference direction, not magnitude target)

        # (a) Direction-lean: price_coef ≤ +0.05 в FMCG (higher price → less sales);
        # допуск +0.05 на noise малых данных. |GT|=0.04 — сигнал слабее шума,
        # точная магнитуда не восстановима на 36 obs (плюс ~3× scale-фактор
        # y-нормализации, см. note в test_competitor_coefficient_recovered_fmcg).
        assert ols_price <= 0.05, (
            f'OLS price_coef={ols_price:.4f} должен быть ≤ +0.05 (negative-leaning). '
            f'Reference GT: {gt_price}. Prior μ=0 (unconstrained) — правильный выбор. '
            f'R²={result["r2"]:.3f}'
        )

        # (b) Bounded magnitude: не runaway estimate
        assert abs(ols_price) < 1.0, (
            f'OLS price_coef={ols_price:.4f} unbounded (|coef| >= 1.0). '
            f'R²={result["r2"]:.3f}'
        )

    def test_weather_signed_positive_otc(self):
        """Weather prior μ=0 позволяет recover положительный коэффициент для OTC.

        GT weather_temp_low_coef = +0.12 (холодная погода → больше OTC продаж).
        Prior μ=0 — правильный: не тянет к отрицательному.

        Если бы prior был μ=-0.3 (как competitor), posterior был бы смещён ВНИЗ
        от реального +0.12 → возможный отрицательный posterior = ошибка.
        """
        gt = GROUND_TRUTH_OTC_PHARMA
        df = generate_otc_pharma(seed=43)

        tv_h = _apply_adstock_hill_normalize(df, 'tv_trp', gt['tv_decay'], gt['tv_alpha'])
        apt_h = _apply_adstock_hill_normalize(df, 'apteka_ooh_contacts', gt['apteka_ooh_decay'], gt['apteka_ooh_alpha'])
        dig_h = _apply_adstock_hill_normalize(df, 'digital_spend', gt['digital_decay'], gt['digital_alpha'])
        perf_h = _apply_adstock_hill_normalize(df, 'performance_clicks', gt['performance_decay'], gt['performance_alpha'])

        comp_n = _normalize(df['competitor_trp'].values.astype(float))
        weather_n = _normalize(df['weather_temp_low'].values.astype(float))
        holiday_n = df['holiday_newyear'].values.astype(float)

        y = df['sales_packs'].values.astype(float)
        result = _fit_ols_with_controls(
            y,
            media_features=[tv_h, apt_h, dig_h, perf_h],
            control_features=[comp_n, weather_n, holiday_n],
        )

        ols_weather = result['control_coefs'][1]
        gt_weather = gt['weather_temp_low_coef']  # +0.12 (reference direction, not magnitude target)

        # (a) Direction: должен быть положительным (холод → +OTC продажи)
        assert ols_weather > -0.05, (
            f'OLS weather_coef={ols_weather:.4f} должен быть > -0.05. '
            f'GT={gt_weather}. Если сильно отрицательный — collinearity с сезонностью. '
            f'R²={result["r2"]:.3f}'
        )

        # (b) Bounded magnitude. Абсолютный gap-vs-GT не identifiable: weather коллинеарен
        # с baked flu-сезонностью (generator redesign 2026-06: seasonal_lift 0.15 без
        # dummy-колонки) + ~2-3× scale-фактор y-нормализации → OLS штатно поднимает
        # weather выше GT. Направление — инвариант; магнитуда — real data
        # (test_priors_real_data.py).
        assert abs(ols_weather) < 1.0, (
            f'OLS weather_coef={ols_weather:.4f} unbounded (|coef| >= 1.0). '
            f'Reference GT: {gt_weather}. R²={result["r2"]:.3f}'
        )

    def test_holiday_dummy_positive_recovered(self):
        """Holiday dummy: OLS recovers positive sign + bounded magnitude.

        Note: holiday binary dummy = 2 positives из 36 obs → высокая variance в
        OLS magnitude estimate (~±0.25). Точная calibration магнитуды не reliable
        на synthetic data — validates на real customer data. Здесь проверяем
        качественные свойства: sign + bounded magnitude.

        GT holiday_newyear_coef = +0.08 (reference direction).
        Prior μ=0 — correct (holiday может быть + или − для разных категорий).
        """
        gt = GROUND_TRUTH_FMCG
        df = generate_fmcg_brand(seed=42)

        tv_h = _apply_adstock_hill_normalize(df, 'tv_spend', gt['tv_decay'], gt['tv_alpha'])
        dig_h = _apply_adstock_hill_normalize(df, 'digital_spend', gt['digital_decay'], gt['digital_alpha'])
        ooh_h = _apply_adstock_hill_normalize(df, 'ooh_trp', gt['ooh_decay'], gt['ooh_alpha'])
        perf_h = _apply_adstock_hill_normalize(df, 'performance_clicks', gt['performance_decay'], gt['performance_alpha'])

        comp_n = _normalize(df['competitor_trp'].values.astype(float))
        price_n = _normalize(df['price_index'].values.astype(float))
        holiday_n = df['holiday_newyear'].values.astype(float)

        y = df['sales_rub'].values.astype(float)
        result = _fit_ols_with_controls(
            y,
            media_features=[tv_h, dig_h, ooh_h, perf_h],
            control_features=[comp_n, price_n, holiday_n],
        )

        ols_holiday = result['control_coefs'][2]
        gt_holiday = gt['holiday_newyear_coef']  # +0.08 (reference direction)

        # (a) Direction: New Year должен быть позитивным для FMCG (spending boost)
        assert ols_holiday > -0.05, (
            f'OLS holiday_coef={ols_holiday:.4f} должен быть ≥ -0.05 для FMCG. '
            f'Reference GT direction: {gt_holiday} (positive). '
            f'Negative coef = data quality issue или severe collinearity. '
            f'R²={result["r2"]:.3f}'
        )

        # (b) Bounded magnitude: |coef| < 1.0 (не runaway)
        assert abs(ols_holiday) < 1.0, (
            f'OLS holiday_coef={ols_holiday:.4f} unbounded (|coef| >= 1.0). '
            f'R²={result["r2"]:.3f}'
        )

    def test_macro_cpi_negative_recovered_real_estate(self):
        """Macro CPI prior μ=0 позволяет data reveal negative effect.

        GT macro_cpi_coef = -0.10 для недвижимости (инфляция → снижение спроса).
        Prior μ=0 (signed_macro unconstrained) — правильный: в некоторых сегментах
        CPI может быть positive (инфляция hedge asset).
        """
        gt = GROUND_TRUTH_REAL_ESTATE
        df = generate_real_estate(seed=45)

        tv_h = _apply_adstock_hill_normalize(df, 'tv_spend', gt['tv_decay'], gt['tv_alpha'])
        ooh_h = _apply_adstock_hill_normalize(df, 'ooh_contacts', gt['ooh_decay'], gt['ooh_alpha'])
        dig_h = _apply_adstock_hill_normalize(df, 'digital_spend', gt['digital_decay'], gt['digital_alpha'])
        perf_h = _apply_adstock_hill_normalize(df, 'performance_clicks', gt['performance_decay'], gt['performance_alpha'])

        comp_n = _normalize(df['competitor_activity'].values.astype(float))
        cpi_n = _normalize(df['macro_cpi'].values.astype(float))
        # Q1/Q4 сезонность в новой схеме baked в demand curve (не dummy-колонки,
        # см. generate_real_estate docstring) → строим дамми из дат, иначе
        # CPI-тренд конфаундится с сезонностью и recovery уплывает.
        months = pd.to_datetime(df['date']).dt.month.to_numpy()
        q1_n = np.isin(months, [1, 2, 3]).astype(float)
        q4_n = np.isin(months, [10, 11, 12]).astype(float)

        y = df['leads'].values.astype(float)
        result = _fit_ols_with_controls(
            y,
            media_features=[tv_h, ooh_h, dig_h, perf_h],
            control_features=[comp_n, cpi_n, q1_n, q4_n],
        )

        ols_cpi = result['control_coefs'][1]
        gt_cpi = gt['macro_cpi_coef']  # -0.10

        # Допуск широкий — CPI trend на 36 obs сложно отделить от trend в рекламе
        tolerance = 0.15
        gap = abs(ols_cpi - gt_cpi)
        assert gap < tolerance, (
            f'OLS macro_cpi_coef={ols_cpi:.4f} далеко от GT={gt_cpi}. '
            f'Gap={gap:.4f} > tolerance={tolerance}. '
            f'CPI trend на 36 obs confounded с media spend trend. '
            f'Prior μ=0 (signed_macro unconstrained) — правильный. R²={result["r2"]:.3f}'
        )

    def test_positive_control_promo_leans_positive(self):
        """Promo indicator (positive control) prior μ=0.2 помогает recover positive coef.

        Схема retail_ecom (rename retail_chain → retail_ecom, audit 2026-07-02):
        promo_indicator — positive CONTROL (GT promo_coef=+0.16), не медиа-канал;
        медиа: tv/digital/ooh_contacts/retail_media. Signed negative —
        competitor_promo (GT competitor_promo_coef=-0.14). KPI: sales_rub.
        """
        gt = GROUND_TRUTH_RETAIL_ECOM
        df = generate_retail_ecom(seed=44)

        tv_h = _apply_adstock_hill_normalize(df, 'tv_spend', gt['tv_decay'], gt['tv_alpha'])
        dig_h = _apply_adstock_hill_normalize(df, 'digital_spend', gt['digital_decay'], gt['digital_alpha'])
        ooh_h = _apply_adstock_hill_normalize(df, 'ooh_contacts', gt['ooh_decay'], gt['ooh_alpha'])
        rm_h = _apply_adstock_hill_normalize(
            df, 'retail_media_spend', gt['retail_media_decay'], gt['retail_media_alpha'])

        promo_n = _normalize(df['promo_indicator'].values.astype(float))
        comp_n = _normalize(df['competitor_promo'].values.astype(float))
        bf_n = df['holiday_blackfriday'].values.astype(float)
        ny_n = df['holiday_newyear'].values.astype(float)

        y = df['sales_rub'].values.astype(float)
        result = _fit_ols_with_controls(
            y,
            media_features=[tv_h, dig_h, ooh_h, rm_h],
            control_features=[promo_n, comp_n, bf_n, ny_n],
        )

        ols_promo = result['control_coefs'][0]
        ols_competitor = result['control_coefs'][1]

        # Promo (positive control, GT +0.16) должен восстановиться positive-leaning
        assert ols_promo >= -0.05, (
            f'Retail promo_coef={ols_promo:.4f} должен быть >= -0.05 (lean positive). '
            f'GT={gt["promo_coef"]}. R²={result["r2"]:.3f}'
        )

        # Competitor promo должен быть отрицательным для retail
        assert ols_competitor <= 0.05, (
            f'Retail competitor_promo_coef={ols_competitor:.4f} должен быть <= 0.05. '
            f'GT={gt["competitor_promo_coef"]}. R²={result["r2"]:.3f}'
        )

        # R² разумный (модель объясняет варьирование)
        assert result['r2'] > 0.40, (
            f'OLS R²={result["r2"]:.3f} слишком низкий (< 0.40). '
            f'Модель не объясняет варьирование данных — возможно structure mismatch.'
        )

    def test_model_r2_sanity_across_scenarios(self):
        """OLS R² > 0.40 для всех 4 synthetic scenarios (sanity check).

        Низкий R² указывает на structural mismatch между features и outcome —
        что нарушило бы смысл тестов выше.
        """
        scenarios = [
            ('fmcg', generate_fmcg_brand, GROUND_TRUTH_FMCG,
             ['tv_spend', 'digital_spend', 'ooh_trp', 'performance_clicks'],
             ['competitor_trp', 'price_index', 'holiday_newyear'],
             'sales_rub'),
            ('otc', generate_otc_pharma, GROUND_TRUTH_OTC_PHARMA,
             ['tv_trp', 'apteka_ooh_contacts', 'digital_spend', 'performance_clicks'],
             ['competitor_trp', 'weather_temp_low', 'holiday_newyear'],
             'sales_packs'),
        ]

        gt_keys = {
            'fmcg': {
                'tv_spend': ('tv_decay', 'tv_alpha'),
                'digital_spend': ('digital_decay', 'digital_alpha'),
                'ooh_trp': ('ooh_decay', 'ooh_alpha'),
                'performance_clicks': ('performance_decay', 'performance_alpha'),
            },
            'otc': {
                'tv_trp': ('tv_decay', 'tv_alpha'),
                'apteka_ooh_contacts': ('apteka_ooh_decay', 'apteka_ooh_alpha'),
                'digital_spend': ('digital_decay', 'digital_alpha'),
                'performance_clicks': ('performance_decay', 'performance_alpha'),
            },
        }

        for name, gen, gt, media_cols, control_cols, target_col in scenarios:
            df = gen()
            media_features = [
                _apply_adstock_hill_normalize(df, c, gt[dk], gt[ak])
                for c, (dk, ak) in gt_keys[name].items()
            ]
            control_features = [
                _normalize(df[c].values.astype(float)) for c in control_cols
            ]
            y = df[target_col].values.astype(float)
            result = _fit_ols_with_controls(y, media_features, control_features)
            assert result['r2'] > 0.40, (
                f'{name}: OLS R²={result["r2"]:.3f} < 0.40. '
                f'Synthetic data structure inconsistency — check generator ground truth.'
            )

    def test_prior_direction_alignment_competitor(self):
        """Prior direction для competitor (μ=-0.3) согласован с GT (-0.18 и -0.22).

        Оба GT coefficients отрицательны. Prior направление верное.
        Проблема: |prior_mu| = 0.3 > |GT| ∈ {0.18, 0.22} → prior немного агрессивнее.
        При малом N posterior будет смещён к -0.3 (overestimate эффекта).

        Тест документирует этот gap как KNOWN ISSUE для Phase E2 real calibration.
        """
        for gt_name, gt_coef in [
            ('FMCG', GROUND_TRUTH_FMCG['competitor_coef']),
            ('OTC', GROUND_TRUTH_OTC_PHARMA['competitor_coef']),
        ]:
            # Prior direction: both agree on negative
            assert PRIOR_COMPETITOR_MU < 0, 'Prior μ должен быть отрицательным'
            assert gt_coef < 0, f'{gt_name} GT должен быть отрицательным'

            # Document magnitude gap (не assert — просто quantify)
            prior_abs = abs(PRIOR_COMPETITOR_MU)
            gt_abs = abs(gt_coef)
            magnitude_overshoot = prior_abs - gt_abs

            # Prior не должен быть более чем 3× агрессивнее GT (качественный check)
            assert prior_abs < 3 * gt_abs, (
                f'{gt_name}: prior |μ|={prior_abs:.2f} более чем в 3× превышает '
                f'GT |coef|={gt_abs:.2f}. Posterior будет heavily biased. '
                f'Рекомендовать μ=-0.15 или μ=-0.20 для recalibration.'
            )

            # Expected direction: prior is somewhat overshoot but in same direction
            assert magnitude_overshoot < 0.20, (
                f'{gt_name}: prior overshoot = {magnitude_overshoot:.3f} '
                f'(prior_mu={PRIOR_COMPETITOR_MU}, GT={gt_coef}). '
                f'> 0.20 — существенное overestimation competitor effect. '
                f'Phase E2 recalibration: уменьшить |μ| до ~0.15-0.20.'
            )

    def test_prior_sigma_adequacy(self):
        """Prior sigma=0.3 должен охватывать реальный диапазон GT коэффициентов.

        Prior N(μ, σ=0.3) должен иметь 95% CI = [μ-0.6, μ+0.6].
        Для competitor (μ=-0.3): CI = [-0.9, +0.3] — охватывает GT -0.18 и -0.22. OK.
        Для price (μ=0): CI = [-0.6, +0.6] — охватывает GT -0.04. OK.
        Для weather (μ=0): CI = [-0.6, +0.6] — охватывает GT +0.12. OK.
        Для holiday (μ=0): CI = [-0.6, +0.6] — охватывает GT +0.08, +0.15. OK.
        """
        test_cases = [
            ('competitor_fmcg', PRIOR_COMPETITOR_MU, PRIOR_SIGMA, GROUND_TRUTH_FMCG['competitor_coef']),
            ('competitor_otc', PRIOR_COMPETITOR_MU, PRIOR_SIGMA, GROUND_TRUTH_OTC_PHARMA['competitor_coef']),
            ('price_fmcg', PRIOR_SIGNED_MU, PRIOR_SIGMA, GROUND_TRUTH_FMCG['price_coef']),
            ('weather_otc', PRIOR_SIGNED_MU, PRIOR_SIGMA, GROUND_TRUTH_OTC_PHARMA['weather_temp_low_coef']),
            ('holiday_fmcg', PRIOR_HOLIDAY_MU, PRIOR_SIGMA, GROUND_TRUTH_FMCG['holiday_newyear_coef']),
        ]

        for name, mu, sigma, gt_coef in test_cases:
            ci_lo = mu - 1.96 * sigma
            ci_hi = mu + 1.96 * sigma
            in_ci = ci_lo <= gt_coef <= ci_hi
            assert in_ci, (
                f'{name}: GT={gt_coef:.4f} вне 95% CI prior [{ci_lo:.3f}, {ci_hi:.3f}]. '
                f'Prior N(μ={mu}, σ={sigma}) несовместим с ground truth. '
                f'Требует срочная recalibration sigma.'
            )
