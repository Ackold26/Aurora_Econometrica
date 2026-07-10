"""
Эталонные ДЕМО-файлы для Aurora Econometrica MMM-оптимайзера (режим планирования).

Отличие от tools/synthetic_pilot_data.py (SSOT-примеры «Попробовать на примере»):
    • synthetic_pilot_data.py → static/sample-data/*.xlsx — SSOT-контракт
      (латинские имена, 48 строк, гейт tools/test_sample_data_ssot.py + канарейка
      tools/test_priors_calibration.py). ЭТИ файлы НЕ трогаем.
    • этот модуль → отдельные ДЕМО-файлы с РАСШИРЕНИЯМИ под ручной прогон
      планирования: КИРИЛЛИЧЕСКИЕ имена бюджетов + хвост-МЕДИАПЛАН 12 будущих
      месяцев (KPI/контроли пусты, инвестиции заполнены). Кладутся в
      static/sample-data/planning/ (SSOT-гейт смотрит только КОРЕНЬ sample-data,
      этот подкаталог им не подхватывается) и на рабочий стол Антона.

Planted truth сохранён: физические ряды — носители истины, spend = physical×CPP_t,
беты решаются АНАЛИТИЧЕСКИ из целевых ROI (_solve_betas_roi / _solve_count_...),
сезонность — гладкой годовой волной (авто-Фурье её выносит). Переиспользуем
утилиты synthetic_pilot_data (никакого дублирования математики).

Отличия датасетов от SSOT-примеров:
    • 5 медиаканалов (SSOT — 4), пары «бюджет ₽ + натуральная метрика»;
    • ROI-лестница с ВЫРАЖЕННЫМ перекосом (сильный канал недокормлен, слабый
      перекормлен) → оптимизатор даёт lift ≥5% с дельтами РАЗНЫХ знаков;
    • разные Hill gamma (0.5–0.9) и adstock decay (0.3–0.8) по каналам;
    • контроли: category / price / competitor (FMCG) · category / weather /
      competitor (OTC);
    • медиаплан-хвост 12 мес — осмысленный план (не копия последних месяцев):
      тот же суммарный бюджет ±, лёгкий сдвиг в сильные каналы, сезонная
      модуляция; KPI и контроли пусты (NaN).

Usage:
    python tools/generate_demo_samples.py
    → static/sample-data/planning/synth_fmcg_brand.xlsx
    → static/sample-data/planning/synth_otc_pharma.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

# Переиспользуем математику planted truth из SSOT-генератора (не дублируем).
from synthetic_pilot_data import (  # noqa: E402
    _cpp_series,
    _indep_channel,
    _media_hills,
    _normalize,
    _season_wave,
    _solve_betas_roi,
    _solve_count_base_and_betas,
    _solve_money_base,
)

# ─── Ground truth демо (5 каналов, ВЫРАЖЕННЫЙ перекос) ────────────────────────
# ROI-лестница: сильный канал недокормлен, слабый перекормлен. Оптимизатор
# сдвинет бюджет из слабого в сильный → lift ≥5%, дельты разных знаков.

DEMO_GT_FMCG = {
    # ТВ 1.2× · Онлайн-видео 2.8× · Наружная 0.8× · Performance 4.2× · Радио 1.0×
    # (Performance-ROI усилен для чёткого сигнала недокорма → устойчивый lift ≥5%).
    'roi_targets': {'tv': 1.2, 'olv': 2.8, 'ooh': 0.8, 'performance': 4.2, 'radio': 1.0},
    # Разные adstock decay 0.3–0.8 и Hill gamma 0.5–0.9 по каналам.
    'decay': {'tv': 0.70, 'olv': 0.45, 'ooh': 0.55, 'performance': 0.30, 'radio': 0.60},
    'alpha': {'tv': 1.9, 'olv': 1.7, 'ooh': 1.6, 'performance': 1.8, 'radio': 1.5},
    'gamma': {'tv': 0.90, 'olv': 0.70, 'ooh': 0.80, 'performance': 0.50, 'radio': 0.75},
    'competitor_coef': -0.16,
    'price_coef': -0.05,
    'category_coef': 0.10,
    'season_amp': 0.25,          # ±25% — летний пик + новогодний всплеск (ТЗ FMCG)
    'season_peak_month': 7,      # летний пик (июль); декабрь — вторичный всплеск
    'media_share_target': 0.33,  # медиа-вклад ~33% продаж (в полосе 25–40%)
    'y_std_frac': 0.18,
    'noise_frac': 0.04,
}

DEMO_GT_OTC = {
    # ТВ 1.4× · Онлайн-видео 3.2× · Аптечные материалы 0.7× · Врачебные визиты 4.6× · Диджитал 1.1×
    # Увеличенный ROI-разрыв сильный↔слабый (visits 4.6× vs apteka 0.7×) →
    # оптимизатору выгоднее перекладывать бюджет → устойчивый lift ≥5%.
    'roi_targets': {'tv': 1.4, 'olv': 3.2, 'apteka': 0.7, 'visits': 4.6, 'digital': 1.1},
    'decay': {'tv': 0.65, 'olv': 0.40, 'apteka': 0.50, 'visits': 0.35, 'digital': 0.30},
    'alpha': {'tv': 1.9, 'olv': 1.6, 'apteka': 1.7, 'visits': 1.8, 'digital': 1.6},
    'gamma': {'tv': 0.90, 'olv': 0.65, 'apteka': 0.80, 'visits': 0.55, 'digital': 0.50},
    'competitor_coef': -0.18,
    'weather_coef': 0.06,
    'category_coef': 0.12,
    'season_amp': 0.30,          # ±30% — зимний простудный пик, ноябрь–февраль (ТЗ Pharma)
    'season_peak_month': 1,      # пик январь
    'media_share_target': 0.32,
    # ₽/упаковка (премиальный OTC, напр. противовирусное) — задаёт масштаб count-KPI
    # (KPI = вклад/value_per_unit) в полосу 50–200K упаковок/мес, физуровни не трогая.
    'value_per_unit': 2600.0,
    'y_std_frac': 0.24,
    'noise_frac': 0.05,
}

# Число месяцев: история + хвост-медиаплан.
N_HISTORY = 48
N_FUTURE = 12


# ─── Hill в форме модели с per-channel gamma ────────────────────────────────
# _media_hills SSOT использует фикс gamma=0.9. Для «разного насыщения» (треб. г)
# нужен per-channel gamma → локальная версия (форма идентична, gamma из GT).

def _media_hills_gamma(raw: dict, decay: dict, alpha: dict, gamma: dict) -> dict:
    from synthetic_pilot_data import _geometric_adstock, _hill
    out = {}
    for ch, x in raw.items():
        s_ads = _geometric_adstock(x, decay[ch])
        out[ch] = _hill(s_ads / max(s_ads.mean(), 1e-9), alpha[ch], gamma[ch])
    return out


def _future_plan(
    rng: np.random.Generator,
    hist_physical: dict[str, np.ndarray],
    months_future: np.ndarray,
    strong_channels: tuple[str, ...],
    weak_channels: tuple[str, ...],
    peak_months: tuple[int, ...],
) -> dict[str, np.ndarray]:
    """Осмысленный медиаплан-хвост (НЕ копия последних месяцев).

    Логика: базовый уровень канала = средний исторический (не последний месяц);
    лёгкий сдвиг бюджета к сильным каналам (+12%) от слабых (−10%); сезонная
    модуляция ±15% по peak_months; малый идиосинкразический шум. Реалистично:
    планировщик перекладывает часть бюджета в эффективные каналы и учитывает
    сезон, но не копирует прошлое дословно.
    """
    plan: dict[str, np.ndarray] = {}
    for ch, hist in hist_physical.items():
        base_level = float(np.mean(hist))          # средний, не последний
        shift = 1.12 if ch in strong_channels else (0.90 if ch in weak_channels else 1.0)
        seasonal = 1.0 + 0.15 * np.isin(months_future, peak_months).astype(float)
        jitter = 1.0 + 0.06 * rng.standard_normal(len(months_future))
        series = base_level * shift * seasonal * jitter
        plan[ch] = series.clip(min=base_level * 0.25)
    return plan


# ─── FMCG демо (5 каналов, кириллица, хвост) ─────────────────────────────────

def generate_demo_fmcg(seed: int = 142) -> pd.DataFrame:
    """FMCG бренд массмаркет — 48 истории + 12 медиаплан-хвост, кириллица.

    Каналы (пары physical-носитель + spend): ТВ+TRP, Онлайн-видео+показы,
    Наружная реклама+контакты, Performance+клики, Радио+GRP.
    Перекос: Наружная ~40% бюджета (ROI 0.8×), Performance недокормлен (ROI 3.5×).
    KPI «Выручка» (₽). Контроли: Продажи категории, Индекс цен, Активность
    конкурентов. Сезонность ±25% (летний пик, июль).
    """
    rng = np.random.default_rng(seed)
    gt = DEMO_GT_FMCG
    n = N_HISTORY
    dates_hist = pd.date_range('2021-01-01', periods=n, freq='ME')
    months = dates_hist.month.to_numpy()

    # ── Физические ряды истории (носители истины) — перекос в объёмах ─────────
    # Наружная: крупнейший бюджет × высокий CPT → ~33% бюджета (ROI 0.8×, перекормлен).
    # Performance: умеренный объём кликов → ~10% бюджета (ROI 3.5×, НЕДОкормлен) — но
    # достаточно объёма/вариации, чтобы OLS на 48 obs уверенно поймал высокий ROI
    # (иначе beta тонет в шуме → отрицательная → оптимизатор режет сильный канал).
    # Флайтинг (dark_frac) даёт контраст пауза→флайт для опознаваемости вклада.
    # Физуровни каналов — «здоровый» диапазон Hill-насыщения (даёт оптимизатору
    # запас движения → lift). Денежный масштаб KPI регулируется CPP (ниже), НЕ
    # объёмами: оптимизатор чувствителен к абсолютным физуровням (Hill), а
    # денежный KPI ∝ медиабюджету = физряд × CPP — рычаги разведены.
    tv_trp = _indep_channel(rng, months, 40, 110, peak_months=(6, 7, 8, 12), peak_amp=0.35, vol=0.30, floor=10, dark_frac=0.18)
    olv_impressions = _indep_channel(rng, months, 14e6, 46e6, peak_months=(6, 7, 8), peak_amp=0.32, vol=0.42, floor=3e6, dark_frac=0.10)
    ooh_contacts = _indep_channel(rng, months, 90e6, 240e6, peak_months=(5, 6, 7, 8), peak_amp=0.35, vol=0.30, floor=18e6, dark_frac=0.15)
    performance_clicks = _indep_channel(rng, months, 40_000, 130_000, peak_months=(3, 9, 11), peak_amp=0.30, vol=0.42, floor=9_000, dark_frac=0.10)
    # Радио — слабый вспомогательный канал (ROI 1.0×): малая доля бюджета. В OLS-
    # режиме без Фурье его beta может уходить в лёгкий минус (ловит сезонный
    # остаток) — в боевом байесе с авто-Фурье очищается (проверено зондом).
    radio_grp = _indep_channel(rng, months, 20, 62, peak_months=(6, 7), peak_amp=0.25, vol=0.32, floor=5, dark_frac=0.20)

    hist_physical = {
        'tv': tv_trp, 'olv': olv_impressions, 'ooh': ooh_contacts,
        'performance': performance_clicks, 'radio': radio_grp,
    }

    # ── Пары: spend = physical × CPP_t ───────────────────────────────────────
    # CPP-базы (реалистичные РФ, нижняя часть рынка) — задают денежный масштаб
    # KPI (∝ медиабюджету) в полосу ~50–200 млн ₽/мес, физуровни (Hill) не трогая.
    # TV 170k₽/TRP, OLV CPM 170₽, OOH CPT 60₽, Performance CPC 32₽, Радио 28k₽/GRP.
    tv_spend = tv_trp * _cpp_series(rng, months, 170_000)
    olv_spend = olv_impressions / 1000.0 * _cpp_series(rng, months, 170.0)
    ooh_spend = ooh_contacts / 1000.0 * _cpp_series(rng, months, 60.0)
    performance_spend = performance_clicks * _cpp_series(rng, months, 32.0)
    radio_spend = radio_grp * _cpp_series(rng, months, 28_000)

    spends = {
        'tv': tv_spend, 'olv': olv_spend, 'ooh': ooh_spend,
        'performance': performance_spend, 'radio': radio_spend,
    }

    # ── Controls ─────────────────────────────────────────────────────────────
    competitor_trp = _indep_channel(rng, months, 30, 200, peak_months=(2, 3, 8), peak_amp=0.25, vol=0.28, floor=0.0)
    price_index = (1.0 + 0.02 * np.arange(n) / n + 0.03 * rng.standard_normal(n)).clip(0.85, 1.25)

    season = _season_wave(months, gt['season_amp'], gt['season_peak_month'])
    # Новогодний всплеск (декабрь) поверх летней волны — вторичный пик.
    season = season + 0.12 * (months == 12).astype(float)

    hills = _media_hills_gamma(hist_physical, gt['decay'], gt['alpha'], gt['gamma'])

    base = _solve_money_base(gt['roi_targets'], spends, gt['media_share_target'], n)
    y_std = base * gt['y_std_frac']
    betas = _solve_betas_roi(gt['roi_targets'], hills, spends)

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

    _print_summary('FMCG-демо', sales_rub, spends, betas, hills, monetary=True)

    # ── История DataFrame (кириллица) ────────────────────────────────────────
    hist = pd.DataFrame({
        'Дата': dates_hist,
        'Выручка': np.round(sales_rub, 0).astype('int64'),
        'ТВ бюджет': np.round(tv_spend, 0).astype('int64'),
        'ТВ TRP': np.round(tv_trp, 1),
        'Онлайн-видео бюджет': np.round(olv_spend, 0).astype('int64'),
        'Онлайн-видео показы': np.round(olv_impressions, 0).astype('int64'),
        'Наружная реклама бюджет': np.round(ooh_spend, 0).astype('int64'),
        'Наружная реклама контакты': np.round(ooh_contacts, 0).astype('int64'),
        'Performance бюджет': np.round(performance_spend, 0).astype('int64'),
        'Performance клики': np.round(performance_clicks, 0).astype('int64'),
        'Радио бюджет': np.round(radio_spend, 0).astype('int64'),
        'Радио GRP': np.round(radio_grp, 1),
        'Активность конкурентов': np.round(competitor_trp, 1),
        'Индекс цен': np.round(price_index, 4),
        'Продажи категории': np.round(category_sales, 0).astype('int64'),
    })

    # ── Медиаплан-хвост 12 мес ───────────────────────────────────────────────
    dates_future = pd.date_range(dates_hist[-1] + pd.DateOffset(months=1), periods=N_FUTURE, freq='ME')
    months_future = dates_future.month.to_numpy()
    plan_phys = _future_plan(
        rng, hist_physical, months_future,
        strong_channels=('olv', 'performance'),   # сильные (ROI 2.8×, 3.5×) — сдвиг вверх
        weak_channels=('ooh',),                   # слабый (ROI 0.8×) — сдвиг вниз
        peak_months=(6, 7, 8, 12),
    )
    # CPP хвоста = средний исторический spend/physical канала (авто-синхронно с
    # историей, устойчиво к смене CPP-баз) + лёгкая медиаинфляция +3%.
    def _cpp_hist(spend, phys):
        return float(np.mean(spend / np.maximum(phys, 1e-9))) * 1.03
    fut_tv_spend = plan_phys['tv'] * _cpp_hist(tv_spend, tv_trp)
    fut_olv_spend = plan_phys['olv'] * _cpp_hist(olv_spend, olv_impressions)
    fut_ooh_spend = plan_phys['ooh'] * _cpp_hist(ooh_spend, ooh_contacts)
    fut_perf_spend = plan_phys['performance'] * _cpp_hist(performance_spend, performance_clicks)
    fut_radio_spend = plan_phys['radio'] * _cpp_hist(radio_spend, radio_grp)

    future = pd.DataFrame({
        'Дата': dates_future,
        'Выручка': [np.nan] * N_FUTURE,
        'ТВ бюджет': np.round(fut_tv_spend, 0),
        'ТВ TRP': np.round(plan_phys['tv'], 1),
        'Онлайн-видео бюджет': np.round(fut_olv_spend, 0),
        'Онлайн-видео показы': np.round(plan_phys['olv'], 0),
        'Наружная реклама бюджет': np.round(fut_ooh_spend, 0),
        'Наружная реклама контакты': np.round(plan_phys['ooh'], 0),
        'Performance бюджет': np.round(fut_perf_spend, 0),
        'Performance клики': np.round(plan_phys['performance'], 0),
        'Радио бюджет': np.round(fut_radio_spend, 0),
        'Радио GRP': np.round(plan_phys['radio'], 1),
        'Активность конкурентов': [np.nan] * N_FUTURE,
        'Индекс цен': [np.nan] * N_FUTURE,
        'Продажи категории': [np.nan] * N_FUTURE,
    })

    return pd.concat([hist, future], ignore_index=True)


# ─── OTC pharma демо (5 каналов, кириллица, хвост) ───────────────────────────

def generate_demo_otc(seed: int = 143) -> pd.DataFrame:
    """OTC pharma — 48 истории + 12 медиаплан-хвост, count-KPI (упаковки), кириллица.

    Каналы: ТВ+TRP, Онлайн-видео+показы, Аптечные материалы+контакты,
    Детейлинг+контакты, Диджитал+клики.
    Перекос: Аптечные материалы ~40% (ROI 0.9×), Детейлинг недокормлен
    (ROI 3.8×). «Детейлинг» — визиты медпредставителей (отраслевой термин). KPI «Продажи, упаковки». Контроли: Продажи категории,
    Температура, Активность конкурентов. Сезонность ±30% (зимний пик, январь).
    """
    rng = np.random.default_rng(seed)
    gt = DEMO_GT_OTC
    n = N_HISTORY
    dates_hist = pd.date_range('2021-01-01', periods=n, freq='ME')
    months = dates_hist.month.to_numpy()

    # Аптечные материалы: крупнейший бюджет (~40%, ROI 0.9×, перекормлен).
    # Врачебные визиты: НЕДОкормлены (~15%, ROI 3.8×), но достаточный объём/вариация
    # для уверенной OLS-оценки высокого ROI → оптимизатор наращивает их, давая lift.
    # OLV/Диджитал — умеренные вспомогательные.
    # Масштаб — средний OTC-бренд (KPI ~50–200K упаковок/мес): объёмы физрядов
    # подобраны так, чтобы медиабюджет+value_per_unit вывели базу в этой полосе.
    # Доли/ROI/lift инвариантны к масштабу (оптимизатор работает на долях).
    # Физуровни — «здоровый» Hill-диапазон (даёт оптимизатору запас → lift).
    # Масштаб count-KPI (упаковки) регулируется value_per_unit (ниже), НЕ объёмами.
    tv_trp = _indep_channel(rng, months, 55, 170, peak_months=(10, 11, 12), peak_amp=0.35, vol=0.32, floor=12, dark_frac=0.18)
    # OLV / Диджитал — слабые вспомогательные (малая доля): в OLS-режиме без Фурье
    # их beta может уходить в лёгкий минус (сезонный остаток) — в боевом байесе с
    # авто-Фурье очищается (проверено зондом: Радио −0.48 → −0.04 с Фурье-контролем).
    olv_impressions = _indep_channel(rng, months, 6e6, 22e6, peak_months=(11, 12, 1), peak_amp=0.32, vol=0.42, floor=1.2e6, dark_frac=0.10)
    apteka_contacts = _indep_channel(rng, months, 55e6, 150e6, peak_months=(1, 2, 12), peak_amp=0.30, vol=0.30, floor=12e6, dark_frac=0.15)
    visits = _indep_channel(rng, months, 2_400, 7_600, peak_months=(9, 10, 11), peak_amp=0.28, vol=0.40, floor=650, dark_frac=0.10)
    digital_clicks = _indep_channel(rng, months, 30_000, 110_000, peak_months=(1, 10), peak_amp=0.28, vol=0.40, floor=6_000, dark_frac=0.08)

    hist_physical = {
        'tv': tv_trp, 'olv': olv_impressions, 'apteka': apteka_contacts,
        'visits': visits, 'digital': digital_clicks,
    }

    # CPP-базы: TV 180k₽/TRP (W18-44), OLV CPM 250₽, Аптечный CPT 400₽,
    # Врачебный визит 3500₽/визит, Диджитал CPC 35₽.
    tv_spend = tv_trp * _cpp_series(rng, months, 180_000)
    olv_spend = olv_impressions / 1000.0 * _cpp_series(rng, months, 250.0)
    apteka_spend = apteka_contacts / 1000.0 * _cpp_series(rng, months, 400.0)
    visits_spend = visits * _cpp_series(rng, months, 3_500.0)
    digital_spend = digital_clicks * _cpp_series(rng, months, 35.0)

    spends = {
        'tv': tv_spend, 'olv': olv_spend, 'apteka': apteka_spend,
        'visits': visits_spend, 'digital': digital_spend,
    }

    competitor_trp = _indep_channel(rng, months, 40, 300, peak_months=(4, 5, 9), peak_amp=0.25, vol=0.30, floor=0.0)
    temp_base = -8 * np.cos(2 * np.pi * (months - 1) / 12)
    weather_temp_low = np.maximum(0, -(temp_base + rng.normal(0, 3, n)))

    season = _season_wave(months, gt['season_amp'], gt['season_peak_month'])

    hills = _media_hills_gamma(hist_physical, gt['decay'], gt['alpha'], gt['gamma'])

    base, y_std, betas = _solve_count_base_and_betas(
        gt['roi_targets'], hills, spends, gt['value_per_unit'],
        gt['media_share_target'], n, gt['y_std_frac'])

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

    _print_summary('OTC-демо', sales_packs, spends, betas, hills, monetary=False,
                   value_per_unit=gt['value_per_unit'])

    hist = pd.DataFrame({
        'Дата': dates_hist,
        'Продажи, упаковки': np.round(sales_packs, 0).astype('int64'),
        'ТВ бюджет': np.round(tv_spend, 0).astype('int64'),
        'ТВ TRP': np.round(tv_trp, 1),
        'Онлайн-видео бюджет': np.round(olv_spend, 0).astype('int64'),
        'Онлайн-видео показы': np.round(olv_impressions, 0).astype('int64'),
        'Аптечные материалы бюджет': np.round(apteka_spend, 0).astype('int64'),
        'Аптечные материалы контакты': np.round(apteka_contacts, 0).astype('int64'),
        'Детейлинг бюджет': np.round(visits_spend, 0).astype('int64'),
        'Детейлинг контакты': np.round(visits, 0).astype('int64'),
        'Диджитал бюджет': np.round(digital_spend, 0).astype('int64'),
        'Диджитал клики': np.round(digital_clicks, 0).astype('int64'),
        'Активность конкурентов': np.round(competitor_trp, 1),
        'Температура': np.round(weather_temp_low, 2),
        'Продажи категории': np.round(category_sales, 0).astype('int64'),
    })

    dates_future = pd.date_range(dates_hist[-1] + pd.DateOffset(months=1), periods=N_FUTURE, freq='ME')
    months_future = dates_future.month.to_numpy()
    plan_phys = _future_plan(
        rng, hist_physical, months_future,
        strong_channels=('olv', 'visits'),        # сильные (ROI 3.2×, 4.6×) — сдвиг вверх
        weak_channels=('apteka',),                # слабый (ROI 0.7×) — сдвиг вниз
        peak_months=(11, 12, 1, 2),
    )
    # CPP хвоста = средний исторический spend/physical (+3% медиаинфляция).
    def _cpp_hist(spend, phys):
        return float(np.mean(spend / np.maximum(phys, 1e-9))) * 1.03
    fut_tv_spend = plan_phys['tv'] * _cpp_hist(tv_spend, tv_trp)
    fut_olv_spend = plan_phys['olv'] * _cpp_hist(olv_spend, olv_impressions)
    fut_apteka_spend = plan_phys['apteka'] * _cpp_hist(apteka_spend, apteka_contacts)
    fut_visits_spend = plan_phys['visits'] * _cpp_hist(visits_spend, visits)
    fut_digital_spend = plan_phys['digital'] * _cpp_hist(digital_spend, digital_clicks)

    future = pd.DataFrame({
        'Дата': dates_future,
        'Продажи, упаковки': [np.nan] * N_FUTURE,
        'ТВ бюджет': np.round(fut_tv_spend, 0),
        'ТВ TRP': np.round(plan_phys['tv'], 1),
        'Онлайн-видео бюджет': np.round(fut_olv_spend, 0),
        'Онлайн-видео показы': np.round(plan_phys['olv'], 0),
        'Аптечные материалы бюджет': np.round(fut_apteka_spend, 0),
        'Аптечные материалы контакты': np.round(plan_phys['apteka'], 0),
        'Детейлинг бюджет': np.round(fut_visits_spend, 0),
        'Детейлинг контакты': np.round(plan_phys['visits'], 0),
        'Диджитал бюджет': np.round(fut_digital_spend, 0),
        'Диджитал клики': np.round(plan_phys['digital'], 0),
        'Активность конкурентов': [np.nan] * N_FUTURE,
        'Температура': [np.nan] * N_FUTURE,
        'Продажи категории': [np.nan] * N_FUTURE,
    })

    return pd.concat([hist, future], ignore_index=True)


# ─── Self-check заложенной истины ────────────────────────────────────────────

def _print_summary(name, y, spends, betas, hills, *, monetary, value_per_unit=None):
    total_y = float(y.sum())
    n = len(y)
    total_spend = sum(float(s.sum()) for s in spends.values())
    media_total = 0.0
    print(f'  [{name}] Σy={total_y:,.0f}{"₽" if monetary else " ед"} · '
          f'Σspend={total_spend:,.0f}₽ · base≈{total_y / n:,.0f}/мес')
    for ch, beta in betas.items():
        contrib = beta * float(hills[ch].sum())
        media_total += contrib
        spend = float(spends[ch].sum())
        share = contrib / total_y * 100.0
        spend_share = spend / total_spend * 100.0
        if monetary:
            roi = contrib / spend
        elif value_per_unit:
            roi = contrib * value_per_unit / spend
        else:
            roi = float('nan')
        print(f'    {ch:12} бюджет {spend_share:5.1f}% · вклад {share:5.2f}% · ROI {roi:4.2f}×')
    print(f'    MEDIA TOTAL   {media_total / total_y * 100:5.2f}%')


# ─── Main ────────────────────────────────────────────────────────────────────

DEMO_GENERATORS = [
    ('synth_fmcg_brand', generate_demo_fmcg),
    ('synth_otc_pharma', generate_demo_otc),
]


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    served_dir = repo_root / 'static' / 'sample-data' / 'planning'
    served_dir.mkdir(parents=True, exist_ok=True)

    for name, gen in DEMO_GENERATORS:
        df = gen()
        out = served_dir / f'{name}.xlsx'
        df.to_excel(out, index=False, sheet_name='Данные')
        n_hist = int(df.iloc[:, 1].notna().sum())
        n_future = len(df) - n_hist
        print(f'  → {out.name}: {len(df)} строк ({n_hist} история + {n_future} медиаплан) '
              f'× {len(df.columns)} колонок')

    print(f'\nГотово. Демо с медиапланом-хвостом: {served_dir}')


if __name__ == '__main__':
    main()
