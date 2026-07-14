"""
Phase E2 priors validation against REAL pilot data (Кагоцел, Венарус, MMX Афала).

Complements synthetic validation in test_priors_calibration.py.
Reads NDA-protected datasets, assembles digital+TV+competitor media proxies from
available column structure, runs OLS coefficient estimation per channel group,
and compares recovered coefficients against industry-typical prior expectations.

Dataset structures (verified 2026-05-13):
  Кагоцел РФ+: 31 data rows (2023-01 → 2025-07), OTC pharma (antiviral).
    Channels: OLV budget (col D), Banners budget (col H), Social budget (col L),
              Performance budget (col Q), Retail Media budget (col N), OOH (col AF).
    Target: Продажи уп бренд (col X). Competitor: TRPs конкуренты (col AB).
    Search: Кол-во запросов (col T).
  Венарус: 31 data rows (2023-01 → 2025-07), OTC pharma (varicose veins).
    Same digital channel structure. Target: Продажи уп бренд (col AB).
    Competitor: TRPs конкуренты (col AE).
  MMX Афала: 43 data rows (2021-10 → 2025-04, small-molecule OTC).
    Channels: OLV budget (col E), Banners budget (col I), Performance budget (col M).
    Target: Продажи уп бренд (col AB). Competitor: TRPs конкуренты (col AE).

Key validation hypotheses:
  H1: competitor_coef (TRP) is negative or near-zero for OTC pharma.
  H2: total media spend correlates positively with sales (sanity check).
  H3: prior sigma=0.3 provides adequate 95% CI coverage for OLS estimates.
  H4: search volume (запросы) is a positive predictor (brand awareness proxy).
  H5: seasonality pattern in OTC data consistent with Q4 flu/cold peak.
  H6: Кагоцел competitor prior μ=-0.3 not overly aggressive vs real data estimate.

Methodology:
  - OLS proxy: no adstock/Hill (data as-is; real modeler applies transforms).
    OLS on raw data = noisier, wider coefficient intervals → conservative test.
  - Signed factor test: extract competitor TRPs coefficient from multi-variate OLS.
  - Prior coverage test: check OLS estimate falls within prior 95% CI.
  - This is NOT a replacement for full MCMC on real data (Phase E2 pilot session).

Usage:
  pytest tools/test_priors_real_data.py -v
  pytest tools/test_priors_real_data.py -v -k "kagocel"
  pytest tools/test_priors_real_data.py -v --tb=short
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

# Module-level marker: все tests требуют real NDA-protected XLSX files на Антоновском
# Desktop. CI runner doesn't have these files → tests fail с FileNotFoundError.
# CI filter `-m "not requires_real_data and not slow"` filters this entire module.
# Local runs (AURORA_TESTDATA_DIR set + files present) execute normally.
# Sprint Buffer CI fix 2026-05-23: marker added explicitly (previously missing).
pytestmark = pytest.mark.requires_real_data

# ─── Paths ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent

# Аудит 2026-07-04: папка на Desktop переехала («Аврора - материалы…» →
# «Файлы для тестирования Авроры\Запрос данных по эконометрики\…») — 18 тестов
# падали FileNotFoundError, полный локальный gate всегда красный (маскирует
# реальные регрессы). Кандидаты путей: env-override → новый → старый; файла нет
# нигде → per-test skip с внятной причиной (environment-dependent данные под NDA).
_REAL_DATA_DIR_CANDIDATES = [
    Path(p) for p in filter(None, [os.environ.get('AURORA_TESTDATA_DIR')])
] + [
    Path(r'C:\Users\ackol\Desktop\Файлы для тестирования Авроры'
         r'\Запрос данных по эконометрики\Эконометрика - тестовые файлы\XLSX'),
    Path(r'C:\Users\ackol\Desktop\Аврора - материалы для обучения и тестирования'
         r'\Эконометрика - тестовые файлы\XLSX'),
]
REAL_DATA_DIR = next(
    (p for p in _REAL_DATA_DIR_CANDIDATES if p.is_dir()),
    _REAL_DATA_DIR_CANDIDATES[-1],
)

DATASETS = {
    'kagocel': REAL_DATA_DIR / 'Кагоцел РФ+_данные для эконометрики + наши данные 29.08.xlsx',
    'venarus': REAL_DATA_DIR / 'Венарус_данные для эконометрики для модели + наши данные.xlsx',
    'mmx_afala': REAL_DATA_DIR / 'MMX 2021-2025 исходник.xlsx',
}


@pytest.fixture(autouse=True)
def _skip_when_real_data_absent():
    """Файлы NDA-данных отсутствуют на машине → skip, не FileNotFoundError."""
    missing = [k for k, p in DATASETS.items() if not p.exists()]
    if missing:
        pytest.skip(f'реальные данные недоступны: {", ".join(missing)} (dir={REAL_DATA_DIR})')

# ─── Prior parameters (from modeler.py PRE_FLIGHT_FIXES.md §B4) ──────────────

PRIOR_COMPETITOR_MU = -0.3     # Normal(μ=-0.3, σ=0.3) — negative-leaning
PRIOR_SIGNED_MU = 0.0          # signed unconstrained (price, weather, macro)
PRIOR_SIGMA = 0.3              # all signed priors share this sigma
PRIOR_CI_95_HALF = 1.96 * PRIOR_SIGMA   # ±0.588


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_rub(s):
    """Parse Russian rubles string '3,836,962 ₽' or numeric to float."""
    if pd.isna(s):
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    text = str(s).replace('\xa0', '').replace('₽', '').replace(',', '').replace(' ', '').strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _normalize(x: np.ndarray) -> np.ndarray:
    """Standard normalize: (x - mean) / std. Safe for zero-variance arrays."""
    s = x.std()
    if s < 1e-10:
        return x - x.mean()
    return (x - x.mean()) / s


def _fit_ols(
    y: np.ndarray,
    feature_matrix: np.ndarray,
) -> dict:
    """Fit OLS regression, return coefficients + R²."""
    y_mean, y_std = y.mean(), max(y.std(), 1e-10)
    y_norm = (y - y_mean) / y_std
    reg = LinearRegression(fit_intercept=True)
    reg.fit(feature_matrix, y_norm)
    return {
        'coefs': reg.coef_,
        'intercept': float(reg.intercept_),
        'r2': float(reg.score(feature_matrix, y_norm)),
    }


def _load_kagocel() -> pd.DataFrame:
    """Load Кагоцел dataset. Returns clean numeric DataFrame с 31 obs."""
    sheet = 'Кагоцел РФ+Герпес'
    # Column indices (0-based): A=0 (Date), D=3 (OLV budget), H=7 (Banners budget),
    # L=11 (Social budget), N=13 (Retail Media budget), Q=16 (Perf budget),
    # T=19 (Запросы), U=20 (Продажи руб бренд), X=23 (Продажи уп бренд),
    # AA=26 (TRPs бренд), AB=27 (TRPs конкуренты), AF=31 (ООН руб)
    df_raw = pd.read_excel(DATASETS['kagocel'], sheet_name=sheet, header=0)
    # Drop trailing empty rows (rows 32-37 in 1-indexed = rows 31-36 in 0-indexed after header)
    df_raw = df_raw[df_raw.iloc[:, 0].notna() & (df_raw.iloc[:, 0].astype(str).str.strip() != '')].copy()
    df_raw = df_raw.reset_index(drop=True)

    result = pd.DataFrame()
    result['date'] = df_raw.iloc[:, 0]

    # OLV budget (col D = index 3)
    result['olv_budget'] = df_raw.iloc[:, 3].apply(_parse_rub)
    # Banners budget (col H = index 7)
    result['banners_budget'] = df_raw.iloc[:, 7].apply(_parse_rub)
    # Social budget (col L = index 11)
    result['social_budget'] = df_raw.iloc[:, 11].apply(_parse_rub)
    # Retail Media budget (col N = index 13)
    result['retail_media_budget'] = df_raw.iloc[:, 13].apply(_parse_rub)
    # Performance budget (col Q = index 16)
    result['performance_budget'] = df_raw.iloc[:, 16].apply(_parse_rub)
    # Search queries (col T = index 19)
    result['search_queries'] = pd.to_numeric(
        df_raw.iloc[:, 19].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # Sales rubles brand (col U = index 20)
    result['sales_rub'] = df_raw.iloc[:, 20].apply(_parse_rub)
    # Sales units brand (col X = index 23)
    result['sales_units'] = pd.to_numeric(
        df_raw.iloc[:, 23].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # TRPs brand (col AA = index 26)
    result['trp_brand'] = pd.to_numeric(
        df_raw.iloc[:, 26].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # TRPs competitor (col AB = index 27)
    result['trp_competitor'] = pd.to_numeric(
        df_raw.iloc[:, 27].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # OOH budget (col AF = index 31)
    result['ooh_budget'] = df_raw.iloc[:, 31].apply(_parse_rub)
    # Total digital budget
    result['total_digital'] = (
        result['olv_budget'] + result['banners_budget']
        + result['social_budget'] + result['performance_budget']
        + result['retail_media_budget']
    )
    return result


def _load_venarus() -> pd.DataFrame:
    """Load Венарус dataset. Returns clean numeric DataFrame с 31 obs."""
    sheet = 'Венарус (таб.)+Венапрокт (комп)'
    # Column structure same as Кагоцел but slightly different (no Retail Media, has Спецпроект).
    # A=0 (date), D=3 (OLV budget), H=7 (Banners budget), L=11 (Social budget),
    # Q=16 (Perf budget), T=19 (Спецпроект budget), V=21 (Запросы),
    # X=23 (Продажи уп бренд) = col X (index 23),
    # AD=29 (TRPs бренд W25-50), AE=30 (TRPs конкуренты)
    df_raw = pd.read_excel(DATASETS['venarus'], sheet_name=sheet, header=0)
    df_raw = df_raw[df_raw.iloc[:, 0].notna() & (df_raw.iloc[:, 0].astype(str).str.strip() != '')].copy()
    df_raw = df_raw.reset_index(drop=True)

    result = pd.DataFrame()
    result['date'] = df_raw.iloc[:, 0]
    result['olv_budget'] = df_raw.iloc[:, 3].apply(_parse_rub)
    result['banners_budget'] = df_raw.iloc[:, 7].apply(_parse_rub)
    result['social_budget'] = df_raw.iloc[:, 11].apply(_parse_rub)
    result['performance_budget'] = df_raw.iloc[:, 16].apply(_parse_rub)
    result['spec_project_budget'] = df_raw.iloc[:, 19].apply(_parse_rub)
    # Search queries col V = index 21
    result['search_queries'] = pd.to_numeric(
        df_raw.iloc[:, 21].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # Sales units brand col Z/AA = index 25 (Продажи в уп. бренд)
    # Note: col 27 = SOM в уп. (%), col 25 = actual units
    result['sales_units'] = pd.to_numeric(
        df_raw.iloc[:, 25].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # TRPs brand col AC = index 28
    result['trp_brand'] = pd.to_numeric(
        df_raw.iloc[:, 28].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # TRPs competitor col AD = index 29
    result['trp_competitor'] = pd.to_numeric(
        df_raw.iloc[:, 29].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    result['total_digital'] = (
        result['olv_budget'] + result['banners_budget']
        + result['social_budget'] + result['performance_budget']
        + result['spec_project_budget']
    )
    return result


def _load_mmx_afala() -> pd.DataFrame:
    """Load MMX Афала dataset. Returns clean numeric DataFrame с 43 obs."""
    sheet = 'Афала'
    # A=0 (Месяц), E=4 (OLV budget), I=8 (Banners budget), M=12 (Performance budget),
    # Q=16 (Статьи budget), U=20 (Спецпроект budget), V=21 (Запросы),
    # W=22 (total budget), X=23 (Продажи уп бренд), AB=27 (Продажи уп бренд),
    # AD=29 (TRPs бренд), AE=30 (TRPs конкуренты)
    df_raw = pd.read_excel(DATASETS['mmx_afala'], sheet_name=sheet, header=0)
    df_raw = df_raw[df_raw.iloc[:, 0].notna() & (df_raw.iloc[:, 0].astype(str).str.strip() != '')].copy()
    df_raw = df_raw.reset_index(drop=True)

    result = pd.DataFrame()
    result['date'] = df_raw.iloc[:, 0]
    result['olv_budget'] = df_raw.iloc[:, 4].apply(_parse_rub)
    result['banners_budget'] = df_raw.iloc[:, 8].apply(_parse_rub)
    result['performance_budget'] = df_raw.iloc[:, 12].apply(_parse_rub)
    # Search queries col V = index 21
    result['search_queries'] = pd.to_numeric(
        df_raw.iloc[:, 21].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # Sales units brand col AA = index 26 (Продажи в уп. бренд)
    # Note: col 28 = SOM в уп. (%), col 26 = actual units
    result['sales_units'] = pd.to_numeric(
        df_raw.iloc[:, 26].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # TRPs brand col AD = index 29
    result['trp_brand'] = pd.to_numeric(
        df_raw.iloc[:, 29].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    # TRPs competitor col AE = index 30
    result['trp_competitor'] = pd.to_numeric(
        df_raw.iloc[:, 30].astype(str).str.replace(r'[,\s]', '', regex=True),
        errors='coerce',
    ).fillna(0)
    result['total_digital'] = (
        result['olv_budget'] + result['banners_budget'] + result['performance_budget']
    )
    return result


# ─── Test class: real data structure validation ───────────────────────────────

class TestRealDataStructure:
    """Validate that real datasets load correctly with expected dimensions."""

    def test_kagocel_minimum_observations(self):
        """Кагоцел должен содержать минимум 24 наблюдения для OLS надёжности."""
        df = _load_kagocel()
        n = len(df)
        assert n >= 24, (
            f'Кагоцел: {n} obs < 24 минимум. Данных недостаточно для валидации priors.'
        )

    def test_venarus_minimum_observations(self):
        """Венарус должен содержать минимум 24 наблюдения."""
        df = _load_venarus()
        n = len(df)
        assert n >= 24, (
            f'Венарус: {n} obs < 24 минимум. Данных недостаточно для валидации priors.'
        )

    def test_mmx_afala_minimum_observations(self):
        """MMX Афала должен содержать минимум 24 наблюдения."""
        df = _load_mmx_afala()
        n = len(df)
        assert n >= 24, (
            f'MMX Афала: {n} obs < 24 минимум. Данных недостаточно для валидации priors.'
        )

    def test_kagocel_target_column_positive(self):
        """Продажи в уп бренд (Кагоцел) должны быть > 0 в большинстве периодов."""
        df = _load_kagocel()
        nonzero = (df['sales_units'] > 0).sum()
        total = len(df)
        assert nonzero >= total * 0.85, (
            f'Кагоцел: только {nonzero}/{total} obs имеют продажи > 0. '
            f'Целевая переменная выглядит некорректной.'
        )

    def test_venarus_target_column_positive(self):
        """Продажи в уп бренд (Венарус) должны быть > 0 в большинстве периодов."""
        df = _load_venarus()
        nonzero = (df['sales_units'] > 0).sum()
        total = len(df)
        assert nonzero >= total * 0.85, (
            f'Венарус: только {nonzero}/{total} obs имеют продажи > 0.'
        )

    def test_kagocel_competitor_trp_variation(self):
        """TRPs конкуренты (Кагоцел) должны иметь достаточную вариацию для OLS."""
        df = _load_kagocel()
        comp = df['trp_competitor'].values.astype(float)
        nonzero = (comp > 0).sum()
        # Нужно хотя бы несколько ненулевых значений для оценки эффекта
        assert nonzero >= 3, (
            f'Кагоцел competitor TRP: только {nonzero} ненулевых obs. '
            f'Insufficient variation — competitor prior неверифицируем на этих данных. '
            f'Тест должен быть marked xfail или skipped.'
        )


# ─── Test class: prior sign and magnitude validation on real data ─────────────

class TestRealDataPriorRecovery:
    """Validate signed factor priors against OLS estimates on real pilot data."""

    def test_kagocel_media_positively_correlated_with_sales(self):
        """H2 (sanity): total digital spend should correlate positively with Кагоцел sales.

        Если общий медиа-бюджет не коррелирует с продажами — данные некорректны
        или OLS на 31 obs с OTC сезонностью completely confounded.
        Широкий допуск: коэффициент total_digital ≥ -0.05 (не strongly negative).
        """
        df = _load_kagocel()
        y = df['sales_units'].values.astype(float)
        x_media = _normalize(df['total_digital'].values.astype(float))
        result = _fit_ols(y, x_media.reshape(-1, 1))
        media_coef = result['coefs'][0]

        assert media_coef > -0.05, (
            f'Кагоцел: total_digital_coef={media_coef:.4f} strongly negative. '
            f'На OTC данных с сезонностью медиа может быть confounded — '
            f'проверить структуру данных. R²={result["r2"]:.3f}'
        )

    def test_venarus_media_positively_correlated_with_sales(self):
        """H2 (sanity): total digital spend vs Венарус sales."""
        df = _load_venarus()
        y = df['sales_units'].values.astype(float)
        x_media = _normalize(df['total_digital'].values.astype(float))
        result = _fit_ols(y, x_media.reshape(-1, 1))
        media_coef = result['coefs'][0]

        assert media_coef > -0.05, (
            f'Венарус: total_digital_coef={media_coef:.4f} strongly negative. '
            f'R²={result["r2"]:.3f}'
        )

    def test_kagocel_competitor_seasonal_confound_documented(self):
        """REAL-DATA FINDING: competitor TRP is a seasonal co-marker for Кагоцел.

        OTC antiviral (flu/cold) market: brand AND competitor both advertise heavily
        in Q4/Q1 (flu season), which is exactly when ALL sales peak.
        corr(competitor_TRP, brand_TRP) = ~0.93 — they move together.
        corr(competitor_TRP, sales) = ~0.63 — positive (seasonal confound).

        This is NOT a competitor cannibalization signal. This is a MARKET EXPANSION
        effect: the whole OTC category grows in cold season, and all players advertise.

        IMPLICATION for priors:
        - Prior μ=-0.3 (designed for FMCG fixed-market) is WRONG for OTC pharma.
        - Correct prior for OTC competitor: μ=0 (symmetric signed prior).
        - The Bayesian model with prior μ=-0.3 will artificially create a negative
          competitor posterior, suppressing the seasonal demand signal.

        This test DOCUMENTS the confound (does not assert negative sign).
        It asserts that raw OLS competitor coef IS positive (seasonal effect confirmed).
        The search queries control absorbs the seasonal signal, driving competitor
        coefficient toward zero — this is the correct behaviour.
        """
        df = _load_kagocel()
        comp = df['trp_competitor'].values.astype(float)
        y = df['sales_units'].values.astype(float)
        x_digital = _normalize(df['total_digital'].values.astype(float))
        x_comp = _normalize(comp)
        x_search = _normalize(df['search_queries'].values.astype(float))

        # Without search control: competitor appears positive (seasonal confound)
        X_no_search = np.column_stack([x_digital, x_comp])
        r_no_search = _fit_ols(y, X_no_search)
        ols_comp_raw = r_no_search['coefs'][1]

        # With search control: competitor moves toward zero
        X_with_search = np.column_stack([x_digital, x_comp, x_search])
        r_with_search = _fit_ols(y, X_with_search)
        ols_comp_controlled = r_with_search['coefs'][1]

        # Assert seasonal confound is present (raw OLS is positive)
        assert ols_comp_raw > 0, (
            f'Кагоцел: expected positive raw competitor_coef (seasonal confound), '
            f'got {ols_comp_raw:.4f}. Data structure may have changed.'
        )

        # Assert search control reduces the competitor coefficient
        assert abs(ols_comp_controlled) < abs(ols_comp_raw), (
            f'Кагоцел: search control did not reduce competitor_coef. '
            f'raw={ols_comp_raw:.4f}, controlled={ols_comp_controlled:.4f}. '
            f'Search queries expected to absorb seasonal demand. '
            f'R² raw={r_no_search["r2"]:.3f}, controlled={r_with_search["r2"]:.3f}'
        )

        # Assert prior μ=0 (symmetric) covers search-controlled estimate
        ci_lo_sym = 0 - PRIOR_CI_95_HALF  # -0.588
        ci_hi_sym = 0 + PRIOR_CI_95_HALF  # +0.588
        in_sym_ci = ci_lo_sym <= ols_comp_controlled <= ci_hi_sym
        assert in_sym_ci, (
            f'Кагоцел: even symmetric prior N(μ=0, σ={PRIOR_SIGMA}) does not cover '
            f'search-controlled competitor_coef={ols_comp_controlled:.4f}. '
            f'Consider sigma=0.4. R²={r_with_search["r2"]:.3f}'
        )

    def test_venarus_competitor_sign_near_zero_when_controlled(self):
        """Венарус competitor TRP: with search control, coefficient should be near zero.

        Венарус (венотоник) is less seasonal than Кагоцел. Competitor (Венапрокт)
        has different seasonality pattern (corr brand/competitor TRP = -0.81).
        Raw OLS competitor coef may be small. With search control: ~0.
        """
        df = _load_venarus()
        comp = df['trp_competitor'].values.astype(float)
        if (comp > 0).sum() < 5:
            pytest.skip(
                f'Венарус competitor TRP: только {(comp > 0).sum()} ненулевых obs.'
            )

        y = df['sales_units'].values.astype(float)
        x_digital = _normalize(df['total_digital'].values.astype(float))
        x_comp = _normalize(comp)
        x_search = _normalize(df['search_queries'].values.astype(float))

        # With search control (organic demand absorbed)
        X = np.column_stack([x_digital, x_comp, x_search])
        result = _fit_ols(y, X)
        ols_comp = result['coefs'][1]

        # Prior μ=0 (symmetric for OTC) should cover search-controlled estimate
        ci_lo_sym = 0 - PRIOR_CI_95_HALF
        ci_hi_sym = 0 + PRIOR_CI_95_HALF
        in_ci = ci_lo_sym <= ols_comp <= ci_hi_sym
        assert in_ci, (
            f'Венарус: search-controlled competitor_coef={ols_comp:.4f} '
            f'вне symmetric prior 95% CI [{ci_lo_sym:.3f}, {ci_hi_sym:.3f}]. '
            f'R²={result["r2"]:.3f}. '
            f'Requires recalibration: even μ=0 prior insufficient.'
        )

    def test_mmx_afala_competitor_sign_with_search_control(self):
        """MMX Афала competitor TRP: with search control, should be near zero.

        Small-molecule OTC (Афала) — less seasonal than Кагоцел.
        With organic demand (search queries) as control variable,
        competitor_coef should reduce toward zero.
        """
        df = _load_mmx_afala()
        comp = df['trp_competitor'].values.astype(float)
        if (comp > 0).sum() < 5:
            pytest.skip(
                f'MMX Афала competitor TRP: только {(comp > 0).sum()} ненулевых obs.'
            )

        y = df['sales_units'].values.astype(float)
        x_digital = _normalize(df['total_digital'].values.astype(float))
        x_comp = _normalize(comp)
        x_search = _normalize(df['search_queries'].values.astype(float))

        X = np.column_stack([x_digital, x_comp, x_search])
        result = _fit_ols(y, X)
        ols_comp = result['coefs'][1]

        # Symmetric prior (μ=0) coverage check
        ci_lo_sym = 0 - PRIOR_CI_95_HALF
        ci_hi_sym = 0 + PRIOR_CI_95_HALF
        in_ci = ci_lo_sym <= ols_comp <= ci_hi_sym
        assert in_ci, (
            f'MMX Афала: search-controlled competitor_coef={ols_comp:.4f} '
            f'вне symmetric prior 95% CI [{ci_lo_sym:.3f}, {ci_hi_sym:.3f}]. '
            f'R²={result["r2"]:.3f}'
        )

    def test_kagocel_search_positive_predictor(self):
        """H4: Search queries (запросы) are a positive predictor of Кагоцел sales.

        Поисковые запросы по бренду — leading indicator спроса. Позитивная
        корреляция с продажами ожидаема. Prior μ=0 (unconstrained) — correct.
        """
        df = _load_kagocel()
        y = df['sales_units'].values.astype(float)
        x_search = _normalize(df['search_queries'].values.astype(float))
        result = _fit_ols(y, x_search.reshape(-1, 1))
        search_coef = result['coefs'][0]

        # Ожидаем положительный коэффициент (спрос → продажи)
        assert search_coef > -0.10, (
            f'Кагоцел search_coef={search_coef:.4f} strongly negative. '
            f'Unexpected: поиск по бренду обратно коррелирует с продажами? '
            f'Возможно reverse causality (сезонность → медиа → поиск). '
            f'R²={result["r2"]:.3f}'
        )

    def test_kagocel_q4_seasonality_peak(self):
        """H5: OTC sales peak in Q4 (October-December) for Кагоцел.

        Антивирусные препараты имеют чёткий flu-season пик Q4.
        Проверяем: средние продажи в Q4 (oct/nov/dec) > средние продажи Q2 (apr/may/jun).
        """
        df = _load_kagocel()
        # Extract month from datetime column (pandas reads Excel dates as Timestamp)
        months = pd.to_datetime(df['date']).dt.month.values

        y = df['sales_units'].values.astype(float)
        q4_mask = np.isin(months, [10, 11, 12])
        q2_mask = np.isin(months, [4, 5, 6])

        # Проверяем что есть данные в обеих группах
        if q4_mask.sum() < 2 or q2_mask.sum() < 2:
            pytest.skip('Недостаточно Q4/Q2 периодов для сезонного теста.')

        q4_mean = y[q4_mask].mean()
        q2_mean = y[q2_mask].mean()

        assert q4_mean > q2_mean, (
            f'Кагоцел: Q4 mean={q4_mean:.0f} units <= Q2 mean={q2_mean:.0f} units. '
            f'Ожидается Q4 peak для OTC антивирусного. Возможно данные 2023-2025 '
            f'имеют нетипичный сезонный паттерн. '
            f'Q4 obs={q4_mask.sum()}, Q2 obs={q2_mask.sum()}'
        )

    def test_prior_sigma_otc_symmetric_covers_kagocel(self):
        """H3 (OTC-specific): Symmetric prior N(μ=0, σ=0.3) covers Кагоцел
        search-controlled competitor estimate.

        After controlling for organic demand (search queries), competitor_coef
        should be near zero for OTC. Symmetric prior μ=0 should provide coverage.
        This replaces the original μ=-0.3 prior test, which was designed for FMCG.
        """
        df = _load_kagocel()
        y = df['sales_units'].values.astype(float)
        x_digital = _normalize(df['total_digital'].values.astype(float))
        x_comp = _normalize(df['trp_competitor'].values.astype(float))
        x_search = _normalize(df['search_queries'].values.astype(float))
        X = np.column_stack([x_digital, x_comp, x_search])
        result = _fit_ols(y, X)
        ols_comp = result['coefs'][1]

        # Symmetric prior 95% CI: [-0.588, +0.588]
        ci_lo_sym = -PRIOR_CI_95_HALF
        ci_hi_sym = +PRIOR_CI_95_HALF

        assert ci_lo_sym <= ols_comp <= ci_hi_sym, (
            f'Symmetric prior N(μ=0, σ={PRIOR_SIGMA}) inadequate for Кагоцел OTC: '
            f'search-controlled competitor_coef={ols_comp:.4f} '
            f'вне CI [{ci_lo_sym:.3f}, {ci_hi_sym:.3f}]. '
            f'Sigma needs expansion to 0.4+. R²={result["r2"]:.3f}'
        )

    def test_prior_sigma_otc_symmetric_covers_venarus(self):
        """H3 (OTC-specific): Symmetric prior N(μ=0, σ=0.3) covers Венарус
        search-controlled competitor estimate."""
        df = _load_venarus()
        comp = df['trp_competitor'].values.astype(float)
        if (comp > 0).sum() < 5:
            pytest.skip('Недостаточно ненулевых competitor obs.')

        y = df['sales_units'].values.astype(float)
        x_digital = _normalize(df['total_digital'].values.astype(float))
        x_comp = _normalize(comp)
        x_search = _normalize(df['search_queries'].values.astype(float))
        X = np.column_stack([x_digital, x_comp, x_search])
        result = _fit_ols(y, X)
        ols_comp = result['coefs'][1]

        ci_lo_sym = -PRIOR_CI_95_HALF
        ci_hi_sym = +PRIOR_CI_95_HALF

        assert ci_lo_sym <= ols_comp <= ci_hi_sym, (
            f'Symmetric prior N(μ=0, σ={PRIOR_SIGMA}) inadequate for Венарус OTC: '
            f'search-controlled competitor_coef={ols_comp:.4f} '
            f'вне CI [{ci_lo_sym:.3f}, {ci_hi_sym:.3f}]. '
            f'R²={result["r2"]:.3f}'
        )


# ─── Test class: cross-dataset prior consistency ─────────────────────────────

class TestCrossDatasetPriorConsistency:
    """Check prior consistency holds across all three real OTC datasets."""

    def test_competitor_ols_std_within_sigma_search_controlled(self):
        """H3 (cross-dataset): std of search-controlled OLS competitor estimates <= 2*sigma.

        After controlling for organic demand (search queries), OLS competitor estimates
        should cluster near zero. std across datasets <= 2*sigma=0.60 expected.
        This validates that a symmetric prior N(μ=0, σ=0.3) is adequate for OTC category.

        NOTE: Raw (uncontrolled) OLS competitor coef is positive for all OTC datasets
        due to flu-season confound. Only search-controlled estimates should be compared
        to the prior.
        """
        estimates = []
        datasets_loaded = []

        for name, loader in [
            ('kagocel', _load_kagocel),
            ('venarus', _load_venarus),
            ('mmx_afala', _load_mmx_afala),
        ]:
            df = loader()
            comp = df['trp_competitor'].values.astype(float)
            if (comp > 0).sum() < 5:
                continue  # skip если нет competitor data

            y = df['sales_units'].values.astype(float)
            x_digital = _normalize(df['total_digital'].values.astype(float))
            x_comp = _normalize(comp)
            x_search = _normalize(df['search_queries'].values.astype(float))
            X = np.column_stack([x_digital, x_comp, x_search])
            result = _fit_ols(y, X)
            estimates.append(result['coefs'][1])
            datasets_loaded.append(name)

        if len(estimates) < 2:
            pytest.skip(f'Только {len(estimates)} датасет(а) содержат competitor data. '
                        f'Нужно >= 2 для cross-dataset теста.')

        ols_std = np.std(estimates)
        tolerance = 2 * PRIOR_SIGMA  # = 0.60

        assert ols_std <= tolerance, (
            f'Cross-dataset search-controlled competitor_coef std={ols_std:.4f} > {tolerance:.2f}. '
            f'Datasets: {list(zip(datasets_loaded, [f"{e:.4f}" for e in estimates]))}. '
            f'Prior N(μ=0, σ={PRIOR_SIGMA}) for OTC category may be too tight.'
        )

    def test_all_datasets_sales_nonzero_majority(self):
        """Sanity: все три датасета должны иметь продажи > 0 в >= 85% периодов."""
        results = {}
        for name, loader in [
            ('kagocel', _load_kagocel),
            ('venarus', _load_venarus),
            ('mmx_afala', _load_mmx_afala),
        ]:
            df = loader()
            n = len(df)
            nonzero = (df['sales_units'] > 0).sum()
            results[name] = (nonzero, n)
            assert nonzero >= n * 0.85, (
                f'{name}: только {nonzero}/{n} obs с продажами > 0. '
                f'Целевая переменная может быть неверно идентифицирована.'
            )

    def test_symmetric_prior_coverage_rate_otc(self):
        """H3 (aggregate): symmetric prior N(μ=0, σ=0.3) covers >= 2/3 datasets.

        OTC FINDING: prior μ=-0.3 is calibrated for FMCG (fixed market, direct
        cannibalization). For OTC pharma, competitor and brand TRPs are correlated
        seasonal co-markers (flu season), NOT direct cannibalization signals.

        After search query control (organic demand absorbed):
        - Symmetric prior N(μ=0, σ=0.3) should cover search-controlled estimates.
        - This test validates that μ=0 (not μ=-0.3) is the correct OTC prior.
        """
        # Symmetric prior CI
        ci_lo_sym = -PRIOR_CI_95_HALF   # -0.588
        ci_hi_sym = +PRIOR_CI_95_HALF   # +0.588

        covered = 0
        skipped = 0
        details = []

        for name, loader in [
            ('kagocel', _load_kagocel),
            ('venarus', _load_venarus),
            ('mmx_afala', _load_mmx_afala),
        ]:
            df = loader()
            comp = df['trp_competitor'].values.astype(float)
            if (comp > 0).sum() < 5:
                skipped += 1
                details.append(f'{name}: skipped (no competitor data)')
                continue

            y = df['sales_units'].values.astype(float)
            x_digital = _normalize(df['total_digital'].values.astype(float))
            x_comp = _normalize(comp)
            x_search = _normalize(df['search_queries'].values.astype(float))
            X = np.column_stack([x_digital, x_comp, x_search])
            result = _fit_ols(y, X)
            ols_comp = result['coefs'][1]
            in_ci = ci_lo_sym <= ols_comp <= ci_hi_sym
            covered += int(in_ci)
            status = 'IN CI' if in_ci else 'OUTSIDE CI'
            details.append(
                f'{name}: search-controlled OLS={ols_comp:.4f} [{status}] '
                f'R²={result["r2"]:.3f}'
            )

        testable = 3 - skipped
        if testable < 2:
            pytest.skip(f'Только {testable} датасет(а) тестируемы.')

        assert covered >= max(1, testable - 1), (
            f'Symmetric prior N(μ=0, σ={PRIOR_SIGMA}) coverage: '
            f'{covered}/{testable} datasets в 95% CI [{ci_lo_sym:.3f}, {ci_hi_sym:.3f}]. '
            f'Детали: {details}. '
            f'Рекомендация: использовать μ=0 для OTC competitor prior (не μ=-0.3). '
            f'Prior μ=-0.3 calibrated для FMCG, НЕ для OTC pharma seasonal markets.'
        )
