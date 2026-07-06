"""
Synthetic РФ pilot data generator для Aurora MMM Optimizer — sample-data SSOT.

Replaces NDA-protected Кагоцел / Венарус pilot data. Generated data имеет known
ground-truth (GROUND_TRUTH_* dicts + ROI/share-таргеты), что позволяет verify
recovery quantitatively.

Workflow:
    python tools/synthetic_pilot_data.py
    → tools/synthetic_pilots/*.xlsx  (working copies, ground-truth benchmarks)
    → static/sample-data/*.xlsx      (served «Попробовать на примере» SSOT)

SSOT contract (2026-06-07 redesign; ПАРЫ 2026-07-05 по решению Антона):
    Each category has ONE schema that is simultaneously (a) the template,
    (b) this filled «try me» example, and (c) the validator/export reference.
    Column names MUST classify correctly через utils.column_detection
    (нет `unknown`, нет mis-role) — gated в tools/test_sample_data_ssot.py.

    🔴 ПАРЫ (решение Антона 2026-07-05): КАЖДЫЙ медиаканал несёт ДВЕ колонки —
    бюджет (₽, `*_spend`) И релевантный натуральный Media KPI (`*_trp`/`*_grp`/
    `*_impressions`/`*_contacts`/`*_clicks`) — чтобы пользователь мог пройти
    обе модели: ROI (деньги) и Эффективность (физические контакты).
    Носитель истины — ФИЗИЧЕСКИЙ ряд (медиаэффект следует контактам);
    spend = physical × CPP_t, где CPP_t дрейфует (~5%/год + сезонная скидка +
    шум) → пара сильно коррелирована (это реальность закупки), но НЕ
    функционально-зависима. В модель одновременно идёт ОДНА колонка пары
    (выбор на под-шаге «Метрики каналов»); объявление пар — PAIRED_COLUMNS
    в test_sample_data_ssot.py (исключены из анти-коллинеарной проверки).

    CPP-базы согласованы с дефолтами UnitCostsPanel (РФ 2026): TV 250 000₽/TRP
    (W25-54) / 180 000₽ (W18-44), digital CPM 200₽, OOH CPT 80₽, retail media
    CPM 500₽; CPC / аптечный CPT — реалистичные рыночные.

    «Красивый убедительный результат» (решение Антона 2026-07-05): беты медиа
    решаются АНАЛИТИЧЕСКИ из целевых ROI (денежные KPI) или целевых долей
    вклада (count-KPI): beta_i = ROI_i·Σspend_i/(Σhill_i·y_std). Гладкая
    годовая волна спроса в базе (авто-Фурье её ловит и выносит полосой
    «Сезонность» ±% к базе). НЕТ holiday_newyear dummy — праздники РФ
    инжектятся программой автоматически (holiday_calendar_ru); ручная колонка
    задваивала бы НГ. holiday_blackfriday в retail ОСТАВЛЕН (не в РФ-календаре).
    category_sales (Фаза Б, kind='category') — в fmcg и otc.

Math model (identical to Aurora MMM):
    y[t] = base·(1 + season[t]) + [Σ_i beta_i·hill(adstock(x_i[t])) + Σ_j coef_j·z_j[t]]·y_std + ε[t]

    adstock(x[t]) = x[t] + decay · adstock(x[t-1])   (geometric)
    hill(x, alpha, gamma) = x^alpha / (x^alpha + gamma^alpha)

All values в реалистичных РФ FMCG / OTC pharma / retail / real-estate диапазонах.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ─── Ground truth (decay/alpha/controls) + ЦЕЛЕВЫЕ ROI / доли вклада ──────────
# ROI-таргеты (денежный KPI) или share-таргеты (count-KPI) — беты решаются из
# них аналитически в _solve_betas(). Лестница эффективности реалистична:
# performance/retail-media > digital > TV > OOH по ROI; TV крупнейший по объёму.

GROUND_TRUTH_FMCG = {
    'roi_targets': {'tv': 2.2, 'digital': 3.5, 'ooh': 1.6, 'performance': 5.5},
    'decay': {'tv': 0.70, 'digital': 0.40, 'ooh': 0.50, 'performance': 0.20},
    'alpha': {'tv': 1.9, 'digital': 1.7, 'ooh': 1.6, 'performance': 1.8},
    'competitor_coef': -0.16,
    'price_coef': -0.05,
    'category_coef': 0.10,
    'season_amp': 0.15,          # ±15% к базе, пик декабрь
    'season_peak_month': 12,
    # Денежный KPI: base ВЫВОДИТСЯ из бюджетов + целевой доли медиа
    # (реалистичная структура: медиа ~33% продаж, база ~67%; A/S ≈ 13-15%).
    'media_share_target': 0.33,
    'y_std_frac': 0.18,
    'noise_frac': 0.04,
}

GROUND_TRUTH_OTC_PHARMA = {
    # count-KPI (упаковки): ₽-ROI-таргеты при value_per_unit (цена производителя);
    # вклад_units_i = ROI_i·Σspend_i/value; база выводится из целевой доли медиа.
    'roi_targets': {'tv': 2.6, 'digital': 3.3, 'apteka': 1.8, 'performance': 4.6},
    'decay': {'tv': 0.65, 'digital': 0.35, 'apteka': 0.45, 'performance': 0.15},
    'alpha': {'tv': 1.9, 'digital': 1.6, 'apteka': 1.7, 'performance': 1.7},
    'competitor_coef': -0.18,
    'weather_coef': 0.06,        # умеренный: зимний спрос в основном несёт сезонная волна
    'category_coef': 0.12,
    'season_amp': 0.22,          # сильная простудная сезонность, пик январь
    'season_peak_month': 1,
    'media_share_target': 0.32,
    'value_per_unit': 250.0,     # ₽/упаковка (цена производителя) — подсказка юзеру на шаге KPI
    'y_std_frac': 0.24,
    'noise_frac': 0.05,
}

GROUND_TRUTH_RETAIL_ECOM = {
    'roi_targets': {'tv': 2.0, 'digital': 3.2, 'ooh': 1.4, 'retail_media': 4.8},
    'decay': {'tv': 0.55, 'digital': 0.30, 'ooh': 0.50, 'retail_media': 0.25},
    'alpha': {'tv': 1.8, 'digital': 1.6, 'ooh': 1.5, 'retail_media': 1.7},
    'promo_coef': 0.14,
    'competitor_promo_coef': -0.12,
    # ЧП: авто-календарь РФ её тоже знает (holiday_black_friday), но ручная
    # колонка примера гасит авто-инжект (семантический дедуп имён, календарь
    # v2.1 2026-07-05) и несёт месячный флаг события целиком.
    'holiday_blackfriday_coef': 0.18,
    'season_amp': 0.18,          # пик декабрь (подарочный сезон)
    'season_peak_month': 12,
    'media_share_target': 0.30,  # e-com медиа-ёмкий, но база (органика+повторные) 70%
    'y_std_frac': 0.18,
    'noise_frac': 0.04,
}

GROUND_TRUTH_REAL_ESTATE = {
    # count-KPI (лиды): ₽-ROI-таргеты при value_per_unit (ценность заявки девелоперу).
    'roi_targets': {'tv': 2.2, 'digital': 3.4, 'ooh': 1.5, 'performance': 5.0},
    'decay': {'tv': 0.80, 'digital': 0.55, 'ooh': 0.60, 'performance': 0.25},
    'alpha': {'tv': 1.8, 'digital': 1.9, 'ooh': 1.6, 'performance': 2.0},
    'competitor_coef': -0.10,
    'macro_cpi_coef': -0.08,
    'season_amp': 0.15,          # Q1 провал / Q4 year-end push → пик ноябрь
    'season_peak_month': 11,
    'media_share_target': 0.32,
    'value_per_unit': 120_000.0,  # ₽/лид — подсказка юзеру на шаге KPI
    'y_std_frac': 0.20,
    'noise_frac': 0.05,          # реалистично-тоньше прочих, но результат остаётся убедительным
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
    dark_frac: float = 0.0,
) -> np.ndarray:
    """Independent media channel series — own level + own seasonal peak + own flighting.

    Identifiability (anti-collinearity): каждый канал тянет СОБСТВЕННЫЙ uniform-draw +
    канал-специфичный сезонный пик (разные месяцы у разных каналов) + большой
    идиосинкразический month-to-month разброс → OLS/Bayes разделяют каналы.

    dark_frac: доля случайных месяцев-ПАУЗ (закупка ~0) — реальный флайтинг РФ
    (ТВ/OOH волнами). Контраст «пауза→флайт» делает вклад канала опознаваемым
    моделью (иначе константная часть давления неотличима от base/intercept).
    """
    n = len(months)
    level = rng.uniform(lo, hi, n)
    if peak_months and peak_amp:
        level = level * (1.0 + peak_amp * np.isin(months, peak_months).astype(float))
    series = level * (1.0 + vol * rng.standard_normal(n))
    series = series.clip(min=(floor if floor is not None else lo * 0.15))
    if dark_frac > 0:
        dark = rng.uniform(0, 1, n) < dark_frac
        series = np.where(dark, series * 0.02, series)
    return series


def _cpp_series(
    rng: np.random.Generator,
    months: np.ndarray,
    cpp_base: float,
    infl_per_year: float = 0.05,
    season_amp: float = 0.02,
    noise: float = 0.03,
) -> np.ndarray:
    """CPP_t для пары spend=physical×CPP_t: медиаинфляция ~5%/год + летние
    сезонные скидки + переговорный шум. Пара получает corr≈0.97–0.99 —
    реалистично коррелирована, но НЕ функционально-зависима (SSOT-правило
    о reference-leak дублях не нарушается; пары задекларированы в гейте)."""
    n = len(months)
    t = np.arange(n)
    trend = 1.0 + infl_per_year * (t / 12.0)
    seasonal = 1.0 - season_amp * np.isin(months, (6, 7, 8)).astype(float)  # летний дисконт
    jitter = 1.0 + noise * rng.standard_normal(n)
    return (cpp_base * trend * seasonal * jitter).clip(min=cpp_base * 0.7)


def _media_hills(
    raw: dict[str, np.ndarray],
    decay: dict[str, float],
    alpha: dict[str, float],
) -> dict[str, np.ndarray]:
    """Медиа-трансформ В ФОРМЕ МОДЕЛИ ПРОГРАММЫ (восстановимость истины):
    adstock на СЫРОМ положительном ряде → шкала к среднему (положительная,
    ~1) → hill(alpha, gamma=1) — полусатурация на среднем уровне давления,
    вариация флайтинга проходит в отклик (не душится нулями/сатурацией, как
    было бы у hill от normalize со средним 0)."""
    out = {}
    for ch, x in raw.items():
        s_ads = _geometric_adstock(x, decay[ch])
        out[ch] = _hill(s_ads / max(s_ads.mean(), 1e-9), alpha[ch], 0.9)
    return out


def _season_wave(months: np.ndarray, amp: float, peak_month: int) -> np.ndarray:
    """Гладкая годовая волна спроса (доля от base): amp·cos с пиком в peak_month.
    Авто-Фурье программы ловит её и выносит полосой «Сезонность» (±% к базе)."""
    return amp * np.cos(2.0 * np.pi * (months - peak_month) / 12.0)


def _solve_betas_roi(
    roi_targets: dict[str, float],
    hills: dict[str, np.ndarray],
    spends: dict[str, np.ndarray],
) -> dict[str, float]:
    """Беты из ЦЕЛЕВЫХ ROI (денежный KPI). Медиа-эффект в АБСОЛЮТНЫХ единицах
    KPI (форма модели программы): вклад_i = beta_i·Σhill_i ⇒
    beta_i = ROI_i·Σspend_i/Σhill_i."""
    return {
        ch: roi * float(spends[ch].sum()) / max(float(hills[ch].sum()), 1e-9)
        for ch, roi in roi_targets.items()
    }


def _solve_count_base_and_betas(
    roi_targets: dict[str, float],
    hills: dict[str, np.ndarray],
    spends: dict[str, np.ndarray],
    value_per_unit: float,
    media_share_target: float,
    n: int,
    y_std_frac: float,
) -> tuple[float, float, dict[str, float]]:
    """count-KPI: ₽-ROI-таргеты при ценности единицы. вклад_units_i =
    ROI_i·Σspend_i/value (от base не зависит); база из целевой доли медиа:
    base = Σвклад·(1/share − 1)/n; беты — из вкладов при y_std=frac·base."""
    contribs = {
        ch: roi * float(spends[ch].sum()) / value_per_unit
        for ch, roi in roi_targets.items()
    }
    total_contrib = sum(contribs.values())
    base = total_contrib * (1.0 / media_share_target - 1.0) / n
    y_std = base * y_std_frac
    betas = {
        ch: contribs[ch] / max(float(hills[ch].sum()), 1e-9)
        for ch in contribs
    }
    return base, y_std, betas


def _solve_money_base(
    roi_targets: dict[str, float],
    spends: dict[str, np.ndarray],
    media_share_target: float,
    n: int,
) -> float:
    """Денежный KPI: вклады фиксированы бюджетами и ROI-таргетами
    (Σвклад = Σ ROI_i·Σspend_i — от base не зависит: beta·y_std сокращается).
    База выводится из целевой ДОЛИ медиа: base = Σвклад·(1/share − 1)/n."""
    total_contrib = sum(roi * float(spends[ch].sum()) for ch, roi in roi_targets.items())
    return total_contrib * (1.0 / media_share_target - 1.0) / n


def _print_truth_summary(name: str, y: np.ndarray, spends: dict[str, np.ndarray],
                         betas: dict[str, float], hills: dict[str, np.ndarray],
                         y_std: float, monetary_kpi: bool,
                         value_per_unit: float | None = None) -> None:
    """Self-check заложенной истины: implied ROI/доли, media share, A/S ratio."""
    total_y = float(y.sum())
    n = len(y)
    total_spend = sum(float(s.sum()) for s in spends.values())
    print(f'  [{name}] Σy={total_y:,.0f} · base≈{total_y / n:,.0f}/период · '
          f'A/S={total_spend / total_y * 100 if monetary_kpi else float("nan"):.1f}%'
          if monetary_kpi else
          f'  [{name}] Σy={total_y:,.0f} единиц · Σspend={total_spend:,.0f}₽')
    media_total = 0.0
    for ch, beta in betas.items():
        contrib = beta * float(hills[ch].sum())
        media_total += contrib
        spend = float(spends[ch].sum())
        share = contrib / total_y * 100.0
        if monetary_kpi:
            tag = f'ROI {contrib / spend:4.2f}×'
        elif value_per_unit:
            tag = f'₽-ROI@{value_per_unit:,.0f}₽/ед {contrib * value_per_unit / spend:4.2f}×'
        else:
            tag = ''
        print(f'    {ch:14} вклад {share:5.2f}% · {tag}')
    print(f'    MEDIA TOTAL   {media_total / total_y * 100:5.2f}%')


# ─── Dataset 1: FMCG бренд массмаркет ────────────────────────────────────────

def generate_fmcg_brand(seed: int = 42) -> pd.DataFrame:
    """FMCG бренд массмаркет — 48 months (2022-01 → 2025-12).

    Пары (physical = носитель истины, spend = physical×CPP_t):
      TV: tv_trp (30–90 TRP, CPP 250 000₽ — панельный дефолт W25-54) + tv_spend
      Digital OLV/дисплей: digital_impressions (12–40М, CPM 200₽) + digital_spend
      OOH: ooh_contacts (18–60М, CPT 80₽) + ooh_spend
      Performance: performance_clicks (8–30К, CPC 45₽) + performance_spend
    Target: sales_rub (₽). Controls: competitor_trp, price_index,
    category_sales (Фаза Б). Сезонность: гладкая волна ±15% (пик декабрь) —
    авто-Фурье; НЕТ holiday-dummy (праздники РФ авто).

    Субоптимальный стартовый сплит (2026-07-06): TV ~63%, performance ~4%.
    ROI TV=2.2× vs performance=5.5× → оптимизатор должен находить lift +15-25%
    при перераспределении TV→performance (фиксированный total budget).
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_FMCG
    n = 48
    dates = pd.date_range('2022-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()

    # ── Физические ряды (носители истины; независимый флайтинг) ──────────────
    # Субоптимальный сплит: TV завышен (30-90 TRP), performance занижен (8-30k clicks).
    # Реализм: 30-90 TRP/мес = нормальный крупный FMCG; 8-30k clicks = небольшой
    # performance-бюджет (недоинвестированный канал).
    tv_trp = _indep_channel(rng, months, 30, 90, peak_months=(11, 12, 1), peak_amp=0.40, vol=0.28, floor=8, dark_frac=0.22)
    digital_impressions = _indep_channel(rng, months, 12e6, 40e6, vol=0.38, floor=2.5e6, dark_frac=0.08)
    ooh_contacts = _indep_channel(rng, months, 18e6, 60e6, peak_months=(5, 6, 7, 8), peak_amp=0.35, vol=0.30, floor=3.5e6, dark_frac=0.25)
    performance_clicks = _indep_channel(rng, months, 8_000, 30_000, peak_months=(3, 9, 10), peak_amp=0.25, vol=0.32, floor=2_000, dark_frac=0.15)

    # ── Пары: spend = physical × CPP_t ────────────────────────────────────────
    tv_spend = tv_trp * _cpp_series(rng, months, 250_000)
    digital_spend = digital_impressions / 1000.0 * _cpp_series(rng, months, 200.0)
    ooh_spend = ooh_contacts / 1000.0 * _cpp_series(rng, months, 80.0)
    performance_spend = performance_clicks * _cpp_series(rng, months, 45.0)

    # ── Controls ──────────────────────────────────────────────────────────────
    competitor_trp = _indep_channel(rng, months, 30, 200, peak_months=(2, 3, 8), peak_amp=0.25, vol=0.28, floor=0.0)
    price_index = (1.0 + 0.02 * np.arange(n) / n + 0.03 * rng.standard_normal(n)).clip(0.85, 1.25)

    season = _season_wave(months, gt['season_amp'], gt['season_peak_month'])

    # ── Ground truth outcome ──────────────────────────────────────────────────
    hills = _media_hills(
        {'tv': tv_trp, 'digital': digital_impressions,
         'ooh': ooh_contacts, 'performance': performance_clicks},
        gt['decay'], gt['alpha'])
    spends = {'tv': tv_spend, 'digital': digital_spend, 'ooh': ooh_spend, 'performance': performance_spend}

    # База из бюджетов + целевой доли медиа (реалистичная структура продаж).
    base = _solve_money_base(gt['roi_targets'], spends, gt['media_share_target'], n)
    y_std = base * gt['y_std_frac']
    betas = _solve_betas_roi(gt['roi_targets'], hills, spends)

    # Категория (Фаза Б): рынок ~8× бренда, та же сезонность (слабее) + тренд 3%/год.
    category_sales = (
        8.0 * base
        * (1.0 + 0.8 * season)
        * (1.0 + 0.03 * np.arange(n) / 12.0)
        * (1.0 + 0.04 * rng.standard_normal(n))
    ).clip(min=1e6)

    media_effect = sum(betas[ch] * hills[ch] for ch in betas)
    control_effect = (
        gt['competitor_coef'] * _normalize(competitor_trp)
        + gt['price_coef'] * _normalize(price_index)
        + gt['category_coef'] * _normalize(category_sales)
    )

    sales_rub = (
        base * (1.0 + season)
        + media_effect
        + control_effect * y_std
        + rng.normal(0, y_std * gt['noise_frac'], n)
    ).clip(min=5e6)

    _print_truth_summary('fmcg', sales_rub, spends, betas, hills, y_std, monetary_kpi=True)

    return pd.DataFrame({
        'date': dates,
        'sales_rub': np.round(sales_rub, 0).astype(int),
        'tv_spend': np.round(tv_spend, 0).astype(int),
        'tv_trp': np.round(tv_trp, 1),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'digital_impressions': np.round(digital_impressions, 0).astype(int),
        'ooh_spend': np.round(ooh_spend, 0).astype(int),
        'ooh_contacts': np.round(ooh_contacts, 0).astype(int),
        'performance_spend': np.round(performance_spend, 0).astype(int),
        'performance_clicks': np.round(performance_clicks, 0).astype(int),
        'competitor_trp': np.round(competitor_trp, 1),
        'price_index': np.round(price_index, 4),
        'category_sales': np.round(category_sales, 0).astype(int),
    })


# ─── Dataset 2: OTC Pharma (Кагоцел-like) ────────────────────────────────────

def generate_otc_pharma(seed: int = 43) -> pd.DataFrame:
    """OTC pharma — 48 months (2022-01 → 2025-12), count-KPI (упаковки).

    Пары: TV tv_trp (60–180, CPP 180 000₽ W18-44) + tv_spend;
    Аптечные экраны apteka_contacts (3–14М, CPT 400₽/1000) + apteka_spend;
    Digital digital_impressions (4–18М, CPM 200₽) + digital_spend;
    Performance performance_clicks (25–100К, CPC 35₽) + performance_spend.
    Controls: competitor_trp (сильный −), weather_temp_low (+, умеренный),
    category_sales. Сезонность: простудная волна ±22% (пик январь) — авто-Фурье.

    Субоптимальный стартовый сплит (2026-07-06): TV ~76%, performance ~7%.
    ROI TV=2.6× vs performance=4.6× → оптимизатор должен находить lift +10-20%
    при перераспределении TV→performance.
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_OTC_PHARMA
    n = 48
    dates = pd.date_range('2022-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()

    # Субоптимальный сплит: TV завышен (60-180 TRP), performance занижен (25-100k clicks).
    # Реализм: 60-180 TRP/мес OTC = активная ТВ-кампания (Кагоцел-like); 25-100k clicks
    # = недоинвестированный digital performance при доминировании ТВ.
    tv_trp = _indep_channel(rng, months, 60, 180, peak_months=(10, 11, 12), peak_amp=0.35, vol=0.30, floor=12, dark_frac=0.20)
    apteka_contacts = _indep_channel(rng, months, 3e6, 14e6, peak_months=(1, 2, 3), peak_amp=0.30, vol=0.30, floor=6e5, dark_frac=0.25)
    digital_impressions = _indep_channel(rng, months, 4e6, 18e6, vol=0.38, floor=8e5, dark_frac=0.08)
    performance_clicks = _indep_channel(rng, months, 25_000, 100_000, peak_months=(9, 10), peak_amp=0.25, vol=0.32, floor=5_000, dark_frac=0.15)

    tv_spend = tv_trp * _cpp_series(rng, months, 180_000)
    apteka_spend = apteka_contacts / 1000.0 * _cpp_series(rng, months, 400.0)
    digital_spend = digital_impressions / 1000.0 * _cpp_series(rng, months, 200.0)
    performance_spend = performance_clicks * _cpp_series(rng, months, 35.0)

    competitor_trp = _indep_channel(rng, months, 40, 300, peak_months=(4, 5, 9), peak_amp=0.25, vol=0.30, floor=0.0)

    temp_base = -8 * np.cos(2 * np.pi * (months - 1) / 12)
    weather_temp_low = np.maximum(0, -(temp_base + rng.normal(0, 3, n)))

    season = _season_wave(months, gt['season_amp'], gt['season_peak_month'])

    hills = _media_hills(
        {'tv': tv_trp, 'apteka': apteka_contacts,
         'digital': digital_impressions, 'performance': performance_clicks},
        gt['decay'], gt['alpha'])
    spends = {'tv': tv_spend, 'apteka': apteka_spend, 'digital': digital_spend, 'performance': performance_spend}

    base, y_std, betas = _solve_count_base_and_betas(
        gt['roi_targets'], hills, spends, gt['value_per_unit'],
        gt['media_share_target'], n, gt['y_std_frac'])

    # Категория (Фаза Б): рынок ~6× бренда, та же сезонность (чуть слабее) + тренд.
    category_sales = (
        6.0 * base
        * (1.0 + 0.85 * season)
        * (1.0 + 0.02 * np.arange(n) / 12.0)
        * (1.0 + 0.04 * rng.standard_normal(n))
    ).clip(min=5e4)

    media_effect = sum(betas[ch] * hills[ch] for ch in betas)
    control_effect = (
        gt['competitor_coef'] * _normalize(competitor_trp)
        + gt['weather_coef'] * _normalize(weather_temp_low)
        + gt['category_coef'] * _normalize(category_sales)
    )

    sales_packs = (
        base * (1.0 + season)
        + media_effect
        + control_effect * y_std
        + rng.normal(0, y_std * gt['noise_frac'], n)
    ).clip(min=10_000)

    _print_truth_summary('otc', sales_packs, spends, betas, hills, y_std, monetary_kpi=False, value_per_unit=gt['value_per_unit'])

    return pd.DataFrame({
        'date': dates,
        'sales_packs': np.round(sales_packs, 0).astype(int),
        'tv_spend': np.round(tv_spend, 0).astype(int),
        'tv_trp': np.round(tv_trp, 1),
        'apteka_spend': np.round(apteka_spend, 0).astype(int),
        'apteka_contacts': np.round(apteka_contacts, 0).astype(int),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'digital_impressions': np.round(digital_impressions, 0).astype(int),
        'performance_spend': np.round(performance_spend, 0).astype(int),
        'performance_clicks': np.round(performance_clicks, 0).astype(int),
        'competitor_trp': np.round(competitor_trp, 1),
        'weather_temp_low': np.round(weather_temp_low, 2),
        'category_sales': np.round(category_sales, 0).astype(int),
    })


# ─── Dataset 3: Ритейл e-com (Ozon/WB продавец) ───────────────────────────────

def generate_retail_ecom(seed: int = 44) -> pd.DataFrame:
    """Retail e-commerce — 48 months (2022-01 → 2025-12), денежный KPI.

    Пары: TV tv_trp (200–600, CPP 250 000₽) + tv_spend;
    Digital digital_impressions (80–250М, CPM 200₽) + digital_spend;
    OOH ooh_contacts (80–260М, CPT 80₽) + ooh_spend;
    Retail media retail_media_impressions (10–50М, CPM 500₽) + retail_media_spend.
    Controls: promo_indicator (+), competitor_promo (−),
    holiday_blackfriday (ноябрь; авто-календарь РФ знает ЧП, но ручная колонка
    гасит авто-инжект — семантический дедуп имён календаря v2.1).
    Сезонность: волна ±15% (пик декабрь) — авто-Фурье; НГ-dummy НЕТ (авто).

    Субоптимальный стартовый сплит (2026-07-06): TV ~61%, retail_media ~10%.
    ROI TV=2.0× vs retail_media=4.8× → оптимизатор должен находить lift +15-25%
    при перераспределении TV→retail_media.
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_RETAIL_ECOM
    n = 48
    dates = pd.date_range('2022-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()

    # Субоптимальный сплит: TV завышен (200-600 TRP крупный ритейл), retail_media занижен.
    # Реализм: 200-600 TRP/мес = масштабная ТВ-кампания WB/Ozon-like; 10-50M retail_media
    # impressions = скромные инвестиции в продвижение на платформе (недоинвестировано).
    tv_trp = _indep_channel(rng, months, 200, 600, peak_months=(11, 12), peak_amp=0.40, vol=0.26, floor=40, dark_frac=0.20)
    digital_impressions = _indep_channel(rng, months, 80e6, 250e6, vol=0.36, floor=20e6, dark_frac=0.08)
    ooh_contacts = _indep_channel(rng, months, 80e6, 260e6, peak_months=(8, 9), peak_amp=0.35, vol=0.30, floor=15e6, dark_frac=0.25)
    retail_media_impressions = _indep_channel(rng, months, 10e6, 50e6, peak_months=(3, 7, 11), peak_amp=0.40, vol=0.30, floor=2.5e6, dark_frac=0.18)

    tv_spend = tv_trp * _cpp_series(rng, months, 250_000)
    digital_spend = digital_impressions / 1000.0 * _cpp_series(rng, months, 200.0)
    ooh_spend = ooh_contacts / 1000.0 * _cpp_series(rng, months, 80.0)
    retail_media_spend = retail_media_impressions / 1000.0 * _cpp_series(rng, months, 500.0)

    promo_prob = np.where(np.isin(months, [10, 11, 12]), 0.6, 0.25)
    promo_indicator = (rng.uniform(0, 1, n) < promo_prob).astype(float)
    competitor_promo = (rng.uniform(0.2, 1.0, n) * (1 + 0.25 * rng.standard_normal(n))).clip(0.05, 1.5)
    holiday_blackfriday = (months == 11).astype(float)

    season = _season_wave(months, gt['season_amp'], gt['season_peak_month'])

    hills = _media_hills(
        {'tv': tv_trp, 'digital': digital_impressions,
         'ooh': ooh_contacts, 'retail_media': retail_media_impressions},
        gt['decay'], gt['alpha'])
    spends = {'tv': tv_spend, 'digital': digital_spend, 'ooh': ooh_spend, 'retail_media': retail_media_spend}

    base = _solve_money_base(gt['roi_targets'], spends, gt['media_share_target'], n)
    y_std = base * gt['y_std_frac']
    betas = _solve_betas_roi(gt['roi_targets'], hills, spends)

    media_effect = sum(betas[ch] * hills[ch] for ch in betas)
    control_effect = (
        gt['promo_coef'] * _normalize(promo_indicator)
        + gt['competitor_promo_coef'] * _normalize(competitor_promo)
        + gt['holiday_blackfriday_coef'] * holiday_blackfriday
    )

    sales_rub = (
        base * (1.0 + season)
        + media_effect
        + control_effect * y_std
        + rng.normal(0, y_std * gt['noise_frac'], n)
    ).clip(min=20e6)

    _print_truth_summary('retail', sales_rub, spends, betas, hills, y_std, monetary_kpi=True)

    return pd.DataFrame({
        'date': dates,
        'sales_rub': np.round(sales_rub, 0).astype(int),
        'tv_spend': np.round(tv_spend, 0).astype(int),
        'tv_trp': np.round(tv_trp, 1),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'digital_impressions': np.round(digital_impressions, 0).astype(int),
        'ooh_spend': np.round(ooh_spend, 0).astype(int),
        'ooh_contacts': np.round(ooh_contacts, 0).astype(int),
        'retail_media_spend': np.round(retail_media_spend, 0).astype(int),
        'retail_media_impressions': np.round(retail_media_impressions, 0).astype(int),
        'promo_indicator': promo_indicator.astype(int),
        'competitor_promo': np.round(competitor_promo, 3),
        'holiday_blackfriday': holiday_blackfriday.astype(int),
    })


# ─── Dataset 4: Застройщик (long sales cycle) ────────────────────────────────

def generate_real_estate(seed: int = 45) -> pd.DataFrame:
    """Застройщик / девелопер — 48 months (2022-01 → 2025-12), count-KPI (лиды).

    Пары: TV tv_grp (90–380 GRP регион+федерал, CPP 150 000₽) + tv_spend;
    OOH ooh_contacts (40–140М, CPT 80₽) + ooh_spend;
    Digital digital_impressions (20–75М, CPM 200₽) + digital_spend;
    Performance performance_clicks (25–110К, CPC 90₽ — дорогой клик ниши) +
    performance_spend.
    Controls: competitor_activity (−), macro_cpi (−).
    Сезонность: волна ±15% (Q1 провал / пик ноябрь) — авто-Фурье; НГ-dummy НЕТ.

    Субоптимальный стартовый сплит (2026-07-06): TV ~62%, performance ~9%.
    ROI TV=2.2× vs performance=5.0× → оптимизатор должен находить lift +15-20%
    при перераспределении TV→performance.
    """
    rng = np.random.default_rng(seed)
    gt = GROUND_TRUTH_REAL_ESTATE
    n = 48
    dates = pd.date_range('2022-01-01', periods=n, freq='ME')
    months = dates.month.to_numpy()

    # Субоптимальный сплит: TV завышен (90-380 GRP), performance занижен (25-110k clicks).
    # Реализм: 90-380 GRP/мес = активная ТВ-кампания девелопера (крупный застройщик);
    # 25-110k performance clicks = скромный лидогенерирующий budget (недоинвестировано
    # при доминировании TV/OOH — типичная ситуация в РФ недвижимости).
    tv_grp = _indep_channel(rng, months, 90, 380, peak_months=(9, 10, 11), peak_amp=0.30, vol=0.30, floor=20, dark_frac=0.20)
    ooh_contacts = _indep_channel(rng, months, 40e6, 140e6, peak_months=(4, 5), peak_amp=0.30, vol=0.30, floor=8e6, dark_frac=0.25)
    digital_impressions = _indep_channel(rng, months, 20e6, 75e6, vol=0.38, floor=4e6, dark_frac=0.08)
    performance_clicks = _indep_channel(rng, months, 25_000, 110_000, peak_months=(3, 9), peak_amp=0.25, vol=0.32, floor=5_000, dark_frac=0.15)

    tv_spend = tv_grp * _cpp_series(rng, months, 150_000)
    ooh_spend = ooh_contacts / 1000.0 * _cpp_series(rng, months, 80.0)
    digital_spend = digital_impressions / 1000.0 * _cpp_series(rng, months, 200.0)
    performance_spend = performance_clicks * _cpp_series(rng, months, 90.0)

    competitor_activity = _indep_channel(rng, months, 20, 150, peak_months=(6, 7), peak_amp=0.20, vol=0.30, floor=0.0)
    macro_cpi = np.cumprod((1.012 + 0.005 * rng.standard_normal(n)).clip(0.995, 1.035))

    season = _season_wave(months, gt['season_amp'], gt['season_peak_month'])

    hills = _media_hills(
        {'tv': tv_grp, 'ooh': ooh_contacts,
         'digital': digital_impressions, 'performance': performance_clicks},
        gt['decay'], gt['alpha'])
    spends = {'tv': tv_spend, 'ooh': ooh_spend, 'digital': digital_spend, 'performance': performance_spend}

    base, y_std, betas = _solve_count_base_and_betas(
        gt['roi_targets'], hills, spends, gt['value_per_unit'],
        gt['media_share_target'], n, gt['y_std_frac'])

    media_effect = sum(betas[ch] * hills[ch] for ch in betas)
    control_effect = (
        gt['competitor_coef'] * _normalize(competitor_activity)
        + gt['macro_cpi_coef'] * _normalize(macro_cpi)
    )

    leads = (
        base * (1.0 + season)
        + media_effect
        + control_effect * y_std
        + rng.normal(0, y_std * gt['noise_frac'], n)
    ).clip(min=50)

    _print_truth_summary('real_estate', leads, spends, betas, hills, y_std, monetary_kpi=False, value_per_unit=gt['value_per_unit'])

    return pd.DataFrame({
        'date': dates,
        'leads': np.round(leads, 0).astype(int),
        'tv_spend': np.round(tv_spend, 0).astype(int),
        'tv_grp': np.round(tv_grp, 1),
        'ooh_spend': np.round(ooh_spend, 0).astype(int),
        'ooh_contacts': np.round(ooh_contacts, 0).astype(int),
        'digital_spend': np.round(digital_spend, 0).astype(int),
        'digital_impressions': np.round(digital_impressions, 0).astype(int),
        'performance_spend': np.round(performance_spend, 0).astype(int),
        'performance_clicks': np.round(performance_clicks, 0).astype(int),
        'competitor_activity': np.round(competitor_activity, 1),
        'macro_cpi': np.round(macro_cpi, 4),
    })


# ─── Main: generate all 4 datasets → working copies + served SSOT ─────────────

# (id, generator). Served filename = SSOT в static/sample-data/.
GENERATORS = [
    ('synth_fmcg_brand', generate_fmcg_brand),
    ('synth_otc_pharma', generate_otc_pharma),
    ('synth_retail_ecom', generate_retail_ecom),
    ('synth_real_estate', generate_real_estate),
]


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    work_dir = Path(__file__).parent / 'synthetic_pilots'
    served_dir = repo_root / 'static' / 'sample-data'
    work_dir.mkdir(exist_ok=True)
    served_dir.mkdir(parents=True, exist_ok=True)

    # Пустые шаблоны справки = header-only копии примеров (SSOT-паритет колонок
    # гарантируется test_template_matches_sample_columns).
    template_dir = repo_root / 'src-tauri' / 'help-econometrica'
    template_names = {
        'synth_fmcg_brand': 'template_fmcg.xlsx',
        'synth_otc_pharma': 'template_pharma_otc.xlsx',
        'synth_retail_ecom': 'template_retail_ecom.xlsx',
        'synth_real_estate': 'template_realestate_b2b.xlsx',
    }

    for name, gen in GENERATORS:
        df = gen()
        for out_dir in (work_dir, served_dir):
            df.to_excel(out_dir / f'{name}.xlsx', index=False, sheet_name='Данные')
        if name in template_names and template_dir.exists():
            df.head(0).to_excel(template_dir / template_names[name], index=False, sheet_name='Данные')
        print(f'  → {name}.xlsx: {len(df)} строк × {len(df.columns)} колонок')

    print('\nГотово. Served SSOT: static/sample-data/*.xlsx')
    print('NB: build/sample-data + .svelte-kit/output — это build-артефакты, '
          'обновятся при следующей сборке (vite copy static/).')


if __name__ == '__main__':
    main()
