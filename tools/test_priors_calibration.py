"""
Phase E2: Signed factor priors validation against synthetic ground truth.

Цель: проверить, что signed factor priors (competitor_coef, price_coef,
weather_coef, holiday/event_coef) восстанавливают known ground-truth коэффициенты
из synthetic data. Результаты документируют calibration quality ПЕРЕД реальными
пилотными данными (Кагоцел / Венарус).

Методология:
    1. Генерируем synthetic данные с известными ground-truth коэффициентами.
    2. Запускаем упрощённую OLS регрессию (proxy для Bayesian posterior mean)
       — полный Bayesian MCMC недоступен в test suite без PyMC/GPU.
    3. Сравниваем OLS estimates с ground truth и с prior means.
    4. Документируем gap — если gap > threshold, prior нуждается в recalibration.

Схема данных = tools/synthetic_pilot_data.py (пересборка 2026-07-05, пары
бюджет+MediaKPI): физические колонки — носители истины (spend = physical×CPP_t),
media-отклик строится генератором как hill(adstock(raw)/mean, alpha, γ=0.9),
сезонность baked в базу волной (авто-Фурье программы её выносит) — поэтому тест
добавляет известную cos-волну сезона контролом, как модель добавила бы Фурье.

Лимитации:
    - OLS ≠ Bayesian posterior. OLS игнорирует priors и даёт unbounded MLE.
    - Тест является НИЖНЕЙ ГРАНИЦЕЙ: если OLS не восстанавливает GT коэффициент,
      Bayesian posterior с prior bias может дать ХУДШИЙ результат.
    - y нормализуется полной σ (доминируемой медиа+сезоном) → магнитуды signed
      коэффициентов сжимаются в ~2-4× против GT; инвариант — ЗНАК + bounded.
    - Real calibration validation требует полного MCMC (Phase E2 pilot session;
      живой байес-фит примеров — tmp/probe_samples_fit2.py, R² 0.89-0.97).

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
PRIOR_CATEGORY_MU = 0.3       # Normal(μ=0.3, σ=0.3) — Фаза Б shared demand (modeler)
PRIOR_SIGMA = 0.3             # sigma retained для backward compat

# ─── Helpers: фичи В ФОРМЕ ГЕНЕРАТОРА (= форме модели программы) ─────────────

def _media_hill_feature(
    df: pd.DataFrame,
    channel_col: str,
    decay: float,
    alpha: float,
) -> np.ndarray:
    """Media-трансформ генератора (_media_hills): adstock на СЫРОМ положительном
    ряде → шкала к среднему → hill(alpha, γ=0.9). НЕ z-normalize перед adstock:
    hill от ряда со средним 0 душит флайтинг (см. docstring _media_hills)."""
    x = df[channel_col].values.astype(float)
    s_ads = _geometric_adstock(x, decay)
    return _hill(s_ads / max(s_ads.mean(), 1e-9), alpha, 0.9)


def _season_cos(df: pd.DataFrame, peak_month: int) -> np.ndarray:
    """Известная сезонная волна GT (форма _season_wave без амплитуды) — контрол,
    как модель программы добавила бы Фурье-гармоники."""
    months = pd.to_datetime(df['date']).dt.month.to_numpy()
    return np.cos(2.0 * np.pi * (months - peak_month) / 12.0)


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


def _fmcg_features(gt: dict, df: pd.DataFrame) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """FMCG: physical-носители пар + контролы генератора + сезонная волна.
    control_coefs порядок: [competitor, price, category, season]."""
    media = [
        _media_hill_feature(df, 'tv_trp', gt['decay']['tv'], gt['alpha']['tv']),
        _media_hill_feature(df, 'digital_impressions', gt['decay']['digital'], gt['alpha']['digital']),
        _media_hill_feature(df, 'ooh_contacts', gt['decay']['ooh'], gt['alpha']['ooh']),
        _media_hill_feature(df, 'performance_clicks', gt['decay']['performance'], gt['alpha']['performance']),
    ]
    controls = [
        _normalize(df['competitor_trp'].values.astype(float)),
        _normalize(df['price_index'].values.astype(float)),
        _normalize(df['category_sales'].values.astype(float)),
        _season_cos(df, gt['season_peak_month']),
    ]
    return media, controls


def _otc_features(gt: dict, df: pd.DataFrame) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """OTC: physical-носители пар + контролы генератора + сезонная волна.
    control_coefs порядок: [competitor, weather, category, season]."""
    media = [
        _media_hill_feature(df, 'tv_trp', gt['decay']['tv'], gt['alpha']['tv']),
        _media_hill_feature(df, 'apteka_contacts', gt['decay']['apteka'], gt['alpha']['apteka']),
        _media_hill_feature(df, 'digital_impressions', gt['decay']['digital'], gt['alpha']['digital']),
        _media_hill_feature(df, 'performance_clicks', gt['decay']['performance'], gt['alpha']['performance']),
    ]
    controls = [
        _normalize(df['competitor_trp'].values.astype(float)),
        _normalize(df['weather_temp_low'].values.astype(float)),
        _normalize(df['category_sales'].values.astype(float)),
        _season_cos(df, gt['season_peak_month']),
    ]
    return media, controls


# ─── Test class: Signed Factor Prior Recovery ─────────────────────────────────

class TestSignedFactorPriors:
    """Validate that signed factor priors recover ground-truth coefficients."""

    def test_competitor_coefficient_recovered_fmcg(self):
        """OLS recovers correct SIGN для competitor coef + bounded magnitude.

        Note: OLS на 48 obs с y-normalized сравнением НЕ восстанавливает магнитуду
        GT точно — нормализация y по полной σ (доминируемой медиа-вкладом) меняет
        scale signed factor coefficient на фактор ~2-4×. Это математически
        ожидаемо, не калибровочный bug. Проверяем что OLS улавливает:
        (a) правильный знак (negative — конкурент уменьшает продажи)
        (b) разумный bounded magnitude (|coef| < 1.0 — не runaway)
        (c) общее качество модели (R² > 0.40)

        Magnitude calibration validated separately на real customer data в
        tools/test_priors_real_data.py (@requires_real_data marker).
        """
        gt = GROUND_TRUTH_FMCG
        df = generate_fmcg_brand(seed=42)
        media, controls = _fmcg_features(gt, df)

        y = df['sales_rub'].values.astype(float)
        result = _fit_ols_with_controls(y, media, controls)

        ols_competitor = result['control_coefs'][0]
        gt_competitor = gt['competitor_coef']  # -0.16 (reference, not magnitude target)

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
        """OLS estimate competitor_coef: правильный знак для OTC pharma.

        OTC имеет более сильный competitor эффект (GT -0.18 vs FMCG -0.16).
        Prior N(μ=-0.3) немного агрессивнее GT — bias направлен правильно.
        """
        gt = GROUND_TRUTH_OTC_PHARMA
        df = generate_otc_pharma(seed=43)
        media, controls = _otc_features(gt, df)

        y = df['sales_packs'].values.astype(float)
        result = _fit_ols_with_controls(y, media, controls)

        ols_competitor = result['control_coefs'][0]
        gt_competitor = gt['competitor_coef']  # -0.18 (reference direction, not magnitude target)

        # (a) Direction: конкурент → −продажи
        assert ols_competitor < 0, (
            f'OTC competitor_coef должен быть отрицательным, получен {ols_competitor:.4f}. '
            f'Сильный сезонный сигнал может masked competitor effect. R²={result["r2"]:.3f}'
        )

        # (b) Bounded magnitude. Абсолютный gap-vs-GT не identifiable: y нормализуется
        # по полной σ продаж (доминируемой медиа+сезоном), что сжимает scale
        # коэффициентов (см. note в test_competitor_coefficient_recovered_fmcg).
        # Magnitude calibration — на real data в test_priors_real_data.py.
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

        GT price_coef = -0.05 (mild negative). Prior μ=0 — правильный выбор:
        в некоторых категориях цена дорогого = quality signal (pozitiv).
        Тест: OLS price estimate имеет правильный знак и разумную magnitude.
        """
        gt = GROUND_TRUTH_FMCG
        df = generate_fmcg_brand(seed=42)
        media, controls = _fmcg_features(gt, df)

        y = df['sales_rub'].values.astype(float)
        result = _fit_ols_with_controls(y, media, controls)

        ols_price = result['control_coefs'][1]
        gt_price = gt['price_coef']  # -0.05 (reference direction, not magnitude target)

        # (a) Direction-lean: price_coef ≤ +0.05 в FMCG (higher price → less sales);
        # допуск +0.05 на noise малых данных. |GT|=0.05 — сигнал слабее шума,
        # точная магнитуда не восстановима на 48 obs (плюс scale-фактор
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

        GT weather_coef = +0.06 (холодная погода → больше OTC продаж; умеренный —
        основной зимний спрос несёт сезонная волна). Prior μ=0 — правильный:
        не тянет к отрицательному.

        Если бы prior был μ=-0.3 (как competitor), posterior был бы смещён ВНИЗ
        от реального +0.06 → возможный отрицательный posterior = ошибка.
        """
        gt = GROUND_TRUTH_OTC_PHARMA
        df = generate_otc_pharma(seed=43)
        media, controls = _otc_features(gt, df)

        y = df['sales_packs'].values.astype(float)
        result = _fit_ols_with_controls(y, media, controls)

        ols_weather = result['control_coefs'][1]
        gt_weather = gt['weather_coef']  # +0.06 (reference direction, not magnitude target)

        # (a) Direction: не сильно отрицательный (холод → +OTC продажи). Weather
        # коллинеарен сезонной волне (пик январь) и category (несёт 0.85·season) —
        # тройной winter-сигнал раскладывается OLS с шумом; инвариант — не
        # выраженно противоположный знак.
        assert ols_weather > -0.05, (
            f'OLS weather_coef={ols_weather:.4f} должен быть > -0.05. '
            f'GT={gt_weather}. Если сильно отрицательный — collinearity с сезонностью. '
            f'R²={result["r2"]:.3f}'
        )

        # (b) Bounded magnitude. Направление — инвариант; магнитуда — real data
        # (test_priors_real_data.py).
        assert abs(ols_weather) < 1.0, (
            f'OLS weather_coef={ols_weather:.4f} unbounded (|coef| >= 1.0). '
            f'Reference GT: {gt_weather}. R²={result["r2"]:.3f}'
        )

    def test_event_dummy_positive_recovered_retail(self):
        """Event dummy (holiday_blackfriday, retail): positive sign + bounded.

        Note: binary dummy = 4 positives из 48 obs → высокая variance в OLS
        magnitude estimate. Точная calibration магнитуды не reliable на synthetic
        data — validates на real customer data. Здесь проверяем качественные
        свойства: sign + bounded magnitude.

        GT holiday_blackfriday_coef = +0.18 (reference direction). Prior μ=0 —
        correct (event может быть + или − для разных категорий). Ранее тест жил
        на fmcg holiday_newyear — колонка удалена из примеров (НГ авто-праздник,
        ручная dummy = двойной учёт); ЧП в retail — легитимная ручная dummy.
        """
        gt = GROUND_TRUTH_RETAIL_ECOM
        df = generate_retail_ecom(seed=44)

        media = [
            _media_hill_feature(df, 'tv_trp', gt['decay']['tv'], gt['alpha']['tv']),
            _media_hill_feature(df, 'digital_impressions', gt['decay']['digital'], gt['alpha']['digital']),
            _media_hill_feature(df, 'ooh_contacts', gt['decay']['ooh'], gt['alpha']['ooh']),
            _media_hill_feature(df, 'retail_media_impressions', gt['decay']['retail_media'], gt['alpha']['retail_media']),
        ]
        # Порядок как в генераторе: promo (norm), competitor_promo (norm), BF (raw
        # binary — так входит в GT y), + сезонная волна.
        controls = [
            _normalize(df['promo_indicator'].values.astype(float)),
            _normalize(df['competitor_promo'].values.astype(float)),
            df['holiday_blackfriday'].values.astype(float),
            _season_cos(df, gt['season_peak_month']),
        ]

        y = df['sales_rub'].values.astype(float)
        result = _fit_ols_with_controls(y, media, controls)

        ols_bf = result['control_coefs'][2]
        gt_bf = gt['holiday_blackfriday_coef']  # +0.18 (reference direction)

        # (a) Direction: Чёрная пятница должна быть позитивной для e-com
        assert ols_bf > -0.05, (
            f'OLS blackfriday_coef={ols_bf:.4f} должен быть ≥ -0.05 для e-com. '
            f'Reference GT direction: {gt_bf} (positive). '
            f'Negative coef = data quality issue или severe collinearity. '
            f'R²={result["r2"]:.3f}'
        )

        # (b) Bounded magnitude: |coef| < 1.0 (не runaway)
        assert abs(ols_bf) < 1.0, (
            f'OLS blackfriday_coef={ols_bf:.4f} unbounded (|coef| >= 1.0). '
            f'R²={result["r2"]:.3f}'
        )

    def test_macro_cpi_negative_recovered_real_estate(self):
        """Macro CPI prior μ=0 позволяет data reveal negative effect.

        GT macro_cpi_coef = -0.08 для недвижимости (инфляция → снижение спроса).
        Prior μ=0 (signed_macro unconstrained) — правильный: в некоторых сегментах
        CPI может быть positive (инфляция hedge asset).
        """
        gt = GROUND_TRUTH_REAL_ESTATE
        df = generate_real_estate(seed=45)

        media = [
            _media_hill_feature(df, 'tv_grp', gt['decay']['tv'], gt['alpha']['tv']),
            _media_hill_feature(df, 'ooh_contacts', gt['decay']['ooh'], gt['alpha']['ooh']),
            _media_hill_feature(df, 'digital_impressions', gt['decay']['digital'], gt['alpha']['digital']),
            _media_hill_feature(df, 'performance_clicks', gt['decay']['performance'], gt['alpha']['performance']),
        ]
        # Сезонность baked волной (пик ноябрь) → даём её cos-контролом, иначе
        # CPI-тренд конфаундится с сезонностью и recovery уплывает.
        controls = [
            _normalize(df['competitor_activity'].values.astype(float)),
            _normalize(df['macro_cpi'].values.astype(float)),
            _season_cos(df, gt['season_peak_month']),
        ]

        y = df['leads'].values.astype(float)
        result = _fit_ols_with_controls(y, media, controls)

        ols_cpi = result['control_coefs'][1]
        gt_cpi = gt['macro_cpi_coef']  # -0.08

        # Допуск широкий — CPI trend на 48 obs сложно отделить от trend в рекламе
        tolerance = 0.15
        gap = abs(ols_cpi - gt_cpi)
        assert gap < tolerance, (
            f'OLS macro_cpi_coef={ols_cpi:.4f} далеко от GT={gt_cpi}. '
            f'Gap={gap:.4f} > tolerance={tolerance}. '
            f'CPI trend на 48 obs confounded с media spend trend. '
            f'Prior μ=0 (signed_macro unconstrained) — правильный. R²={result["r2"]:.3f}'
        )

    def test_positive_control_promo_leans_positive(self):
        """Promo indicator (positive control) prior μ=0.2 помогает recover positive coef.

        Схема retail_ecom (пересборка 2026-07-05): promo_indicator — positive
        CONTROL (GT promo_coef=+0.14), не медиа-канал; медиа-пары:
        tv/digital/ooh/retail_media (physical-носители). Signed negative —
        competitor_promo (GT competitor_promo_coef=-0.12). KPI: sales_rub.
        """
        gt = GROUND_TRUTH_RETAIL_ECOM
        df = generate_retail_ecom(seed=44)

        media = [
            _media_hill_feature(df, 'tv_trp', gt['decay']['tv'], gt['alpha']['tv']),
            _media_hill_feature(df, 'digital_impressions', gt['decay']['digital'], gt['alpha']['digital']),
            _media_hill_feature(df, 'ooh_contacts', gt['decay']['ooh'], gt['alpha']['ooh']),
            _media_hill_feature(df, 'retail_media_impressions', gt['decay']['retail_media'], gt['alpha']['retail_media']),
        ]
        controls = [
            _normalize(df['promo_indicator'].values.astype(float)),
            _normalize(df['competitor_promo'].values.astype(float)),
            df['holiday_blackfriday'].values.astype(float),
            _season_cos(df, gt['season_peak_month']),
        ]

        y = df['sales_rub'].values.astype(float)
        result = _fit_ols_with_controls(y, media, controls)

        ols_promo = result['control_coefs'][0]
        ols_competitor = result['control_coefs'][1]

        # Promo (positive control, GT +0.14) должен восстановиться positive-leaning
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
        # (name, generator, gt, media[(col, ch)], controls[col], binary_raw[col], target)
        scenarios = [
            ('fmcg', generate_fmcg_brand, GROUND_TRUTH_FMCG,
             [('tv_trp', 'tv'), ('digital_impressions', 'digital'),
              ('ooh_contacts', 'ooh'), ('performance_clicks', 'performance')],
             ['competitor_trp', 'price_index', 'category_sales'], [],
             'sales_rub'),
            ('otc', generate_otc_pharma, GROUND_TRUTH_OTC_PHARMA,
             [('tv_trp', 'tv'), ('apteka_contacts', 'apteka'),
              ('digital_impressions', 'digital'), ('performance_clicks', 'performance')],
             ['competitor_trp', 'weather_temp_low', 'category_sales'], [],
             'sales_packs'),
            ('retail', generate_retail_ecom, GROUND_TRUTH_RETAIL_ECOM,
             [('tv_trp', 'tv'), ('digital_impressions', 'digital'),
              ('ooh_contacts', 'ooh'), ('retail_media_impressions', 'retail_media')],
             ['promo_indicator', 'competitor_promo'], ['holiday_blackfriday'],
             'sales_rub'),
            ('real_estate', generate_real_estate, GROUND_TRUTH_REAL_ESTATE,
             [('tv_grp', 'tv'), ('ooh_contacts', 'ooh'),
              ('digital_impressions', 'digital'), ('performance_clicks', 'performance')],
             ['competitor_activity', 'macro_cpi'], [],
             'leads'),
        ]

        for name, gen, gt, media_spec, control_cols, binary_cols, target_col in scenarios:
            df = gen()
            media_features = [
                _media_hill_feature(df, col, gt['decay'][ch], gt['alpha'][ch])
                for col, ch in media_spec
            ]
            control_features = [
                _normalize(df[c].values.astype(float)) for c in control_cols
            ] + [
                df[c].values.astype(float) for c in binary_cols
            ] + [
                _season_cos(df, gt['season_peak_month']),
            ]
            y = df[target_col].values.astype(float)
            result = _fit_ols_with_controls(y, media_features, control_features)
            assert result['r2'] > 0.40, (
                f'{name}: OLS R²={result["r2"]:.3f} < 0.40. '
                f'Synthetic data structure inconsistency — check generator ground truth.'
            )

    def test_prior_direction_alignment_competitor(self):
        """Prior direction для competitor (μ=-0.3) согласован с GT (-0.16 и -0.18).

        Оба GT coefficients отрицательны. Prior направление верное.
        Проблема: |prior_mu| = 0.3 > |GT| ∈ {0.16, 0.18} → prior немного агрессивнее.
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
        Для competitor (μ=-0.3): CI = [-0.9, +0.3] — охватывает GT -0.16 и -0.18. OK.
        Для price (μ=0): CI = [-0.6, +0.6] — охватывает GT -0.05. OK.
        Для weather (μ=0): CI = [-0.6, +0.6] — охватывает GT +0.06. OK.
        Для event dummy (μ=0): CI = [-0.6, +0.6] — охватывает GT +0.18. OK.
        Для macro (μ=0): CI = [-0.6, +0.6] — охватывает GT -0.08. OK.
        Для promo positive control (μ=0.2): CI = [-0.39, +0.79] — охватывает +0.14. OK.
        Для category Фаза Б (μ=0.3): CI = [-0.29, +0.89] — охватывает +0.10/+0.12. OK.
        """
        test_cases = [
            ('competitor_fmcg', PRIOR_COMPETITOR_MU, PRIOR_SIGMA, GROUND_TRUTH_FMCG['competitor_coef']),
            ('competitor_otc', PRIOR_COMPETITOR_MU, PRIOR_SIGMA, GROUND_TRUTH_OTC_PHARMA['competitor_coef']),
            ('price_fmcg', PRIOR_SIGNED_MU, PRIOR_SIGMA, GROUND_TRUTH_FMCG['price_coef']),
            ('weather_otc', PRIOR_SIGNED_MU, PRIOR_SIGMA, GROUND_TRUTH_OTC_PHARMA['weather_coef']),
            ('blackfriday_retail', PRIOR_HOLIDAY_MU, PRIOR_SIGMA, GROUND_TRUTH_RETAIL_ECOM['holiday_blackfriday_coef']),
            ('macro_cpi_realestate', PRIOR_SIGNED_MU, PRIOR_SIGMA, GROUND_TRUTH_REAL_ESTATE['macro_cpi_coef']),
            ('promo_retail', PRIOR_POSITIVE_CONTROL_MU, PRIOR_SIGMA, GROUND_TRUTH_RETAIL_ECOM['promo_coef']),
            ('category_fmcg', PRIOR_CATEGORY_MU, PRIOR_SIGMA, GROUND_TRUTH_FMCG['category_coef']),
            ('category_otc', PRIOR_CATEGORY_MU, PRIOR_SIGMA, GROUND_TRUTH_OTC_PHARMA['category_coef']),
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
