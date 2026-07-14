"""Идеальные ДЕМО-файлы для режима ПЛАНИРОВАНИЯ Aurora Econometrica (MMM Optimizer).

Отдельны от SSOT-примеров tools/synthetic_pilot_data.py (корень static/sample-data/,
без хвоста, базовый анализ, под SSOT-гейтом). ЭТИ файлы — с хвостом-медиапланом,
для сквозного показа «планирование → прогноз → оптимизация» ("Попробовать
планирование на примере"). Кладутся в static/sample-data/planning/ (SSOT-гейт
смотрит только КОРЕНЬ sample-data, подкаталог не подхватывает).

Дизайн (переработка 2026-07-14 под «очевидную эффективность» + надёжную модель):
    • Кириллические имена бюджетов + пары «бюджет ₽ + натуральная метрика».
    • ПЕРЕКОС НАСЫЩЕНИЯ (sat_frac): доминирующий по бюджету канал сидит ЗА точкой
      полунасыщения Hill (плоско → низкий маржинальный ROAS), недокормленный
      сильный — ДО (круто → высокий маржинальный). Оптимизатор перекладывает
      донор→приёмник → заметный прирост при фиксированном бюджете.
    • Хвост-медиаплан ≥20% истории (иначе optimizer INFEASIBLE на коридоре 20/200:
      границы считаются на полной истории, а money_target — на хвосте).

Два кейса (по решению Антона: меньше файлов, но идеальные, полный функционал):
    • FMCG (synth_fmcg_brand) — НЕДЕЛЬНАЯ гранулярность, 104 нед + 26 хвост, KPI
      «Выручка» ₽. Прод-байес: прирост +11.8%, R² 0.94, ratio 6.7, backtest
      directional (gap 17.9пп).
    • OTC противопростудные (synth_otc_pharma) — МЕСЯЧНАЯ, 60 мес + 12 хвост,
      count-KPI «Продажи, упаковки». Прод-байес: прирост +3.3% итог / +13.6% медиа
      (count-KPI структурно скромнее), R² 0.88, ratio 5.1, backtest reliable.

🔴 OTC обучать с use_holidays=False (противопростудные нечувствительны к РФ-
праздникам; 12 авто-праздников иначе роняют ratio и топят модель в overfit).
FMCG аналогично выигрывает от use_holidays=False (Фурье ловит декабрь годовой
гармоникой). Флаг задаётся в UI на шаге «Валидация», не в данных.

Math model (identical to Aurora MMM):
    y[t] = base·(1+season[t]) + Σ_i beta_i·hill(adstock(x_i[t])) + Σ_j coef_j·z_j[t]·y_std + ε
    adstock(x[t]) = x[t] + decay·adstock(x[t-1])
    hill(s, alpha, sat_ref) = s^alpha / (s^alpha + sat_ref^alpha)   # sat_ref ФИКСИРОВАН
    beta_i = ROI_i·Σspend_i / Σhill_i   # аналитически из целевого ROI

Usage:
    python tools/generate_demo_samples.py
    → static/sample-data/planning/synth_fmcg_brand.xlsx
    → static/sample-data/planning/synth_otc_pharma.xlsx
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


# ─── Утилиты (форма модели программы; sat_ref фиксирован) ─────────────────────

def _geo_adstock(x: np.ndarray, decay: float) -> np.ndarray:
    s = np.zeros(len(x))
    for t in range(len(x)):
        s[t] = x[t] + (decay * s[t - 1] if t > 0 else 0.0)
    return s


def _hill_abs(adstock: np.ndarray, alpha: float, sat_ref_abs: float) -> np.ndarray:
    """Hill с АБСОЛЮТНОЙ (фиксированной) точкой полунасыщения. Фикс sat_ref
    обязателен: иначе при масштабировании бюджета среднее «едет» за spend →
    отклик инвариантен к бюджету → маржинальный ROAS = 0 (оптимизатору нечего
    перекладывать). В реальной модели half-saturation gamma тоже фиксирован."""
    xp = np.power(np.maximum(adstock, 0.0) + 1e-12, alpha)
    return xp / (xp + sat_ref_abs ** alpha)


def _sat_ref_from_frac(adstock: np.ndarray, sat_frac: float) -> float:
    """Абсолютный sat_ref = sat_frac·mean(исходного adstock). sat_frac<1 → канал
    ЗА насыщением (перекормлен); >1 → ДО (недокормлен)."""
    return sat_frac * max(float(np.mean(adstock)), 1e-9)


def _normalize(x: np.ndarray) -> np.ndarray:
    s = x.std()
    return (x - x.mean()) / s if s > 1e-10 else x - x.mean()


def _indep_channel(rng, period_idx, lo, hi, peaks=(), peak_amp=0.0, vol=0.30,
                   floor=None, dark_frac=0.0, period_len=52):
    """Независимый ряд давления: уровень + сезонный пик (по индексу периода года)
    + флайтинг (паузы). Идиосинкразия разделяет каналы (anti-collinearity)."""
    n = len(period_idx)
    level = rng.uniform(lo, hi, n)
    if peaks and peak_amp:
        level = level * (1.0 + peak_amp * np.isin(period_idx, peaks).astype(float))
    s = level * (1.0 + vol * rng.standard_normal(n))
    s = s.clip(min=(floor if floor is not None else lo * 0.15))
    if dark_frac > 0:
        s = np.where(rng.uniform(0, 1, n) < dark_frac, s * 0.02, s)
    return s


def _cpp_series(rng, n, cpp_base, infl_per_year=0.05, periods_per_year=52, noise=0.03):
    """CPP_t: медиаинфляция + переговорный шум. Пара spend=physical×CPP_t сильно
    коррелирована, но НЕ функционально-зависима."""
    trend = 1.0 + infl_per_year * (np.arange(n) / periods_per_year)
    jitter = 1.0 + noise * rng.standard_normal(n)
    return (cpp_base * trend * jitter).clip(min=cpp_base * 0.7)


def _season_wave(period_idx, amp, peak_period, period_len):
    return amp * np.cos(2.0 * np.pi * (period_idx - peak_period) / period_len)


def _betas_money(roi, hills, spends):
    return {c: roi[c] * float(spends[c].sum()) / max(float(hills[c].sum()), 1e-9) for c in roi}


def _money_base(roi, spends, media_share, n):
    total = sum(roi[c] * float(spends[c].sum()) for c in roi)
    return total * (1.0 / media_share - 1.0) / n


def _count_base_betas(roi, hills, spends, value_per_unit, media_share, n, y_std_frac):
    contribs = {c: roi[c] * float(spends[c].sum()) / value_per_unit for c in roi}
    base = sum(contribs.values()) * (1.0 / media_share - 1.0) / n
    y_std = base * y_std_frac
    betas = {c: contribs[c] / max(float(hills[c].sum()), 1e-9) for c in contribs}
    return base, y_std, betas


def _future_tail(dates, phys, spends, n_future, freq):
    """Хвост-медиаплан: базовый уровень = средний исторический physical канала,
    spend = physical × средний ист. CPP (+3% медиаинфляция). Сохраняет текущий
    (неоптимальный) сплит → оптимизатор на хвосте показывает прирост."""
    if freq == 'W-MON':
        fut_dates = pd.date_range(dates[-1] + pd.Timedelta(weeks=1), periods=n_future, freq='W-MON')
    else:
        fut_dates = pd.date_range(dates[-1] + pd.DateOffset(months=1), periods=n_future, freq='ME')
    fut_spend, fut_phys = {}, {}
    for ch in phys:
        cpp = float(np.mean(spends[ch] / np.maximum(phys[ch], 1e-9))) * 1.03
        lvl = float(np.mean(phys[ch]))
        fut_phys[ch] = np.full(n_future, lvl)
        fut_spend[ch] = np.full(n_future, lvl) * cpp
    return fut_dates, fut_spend, fut_phys


# ─── FMCG (недельный, денежный KPI) ──────────────────────────────────────────

FMCG_GT = {
    # ТВ+Наружная доминируют бюджетом и перекормлены (sat_frac<1); Онлайн+Performance
    # недокормлены (sat_frac>1, высокий ROI) → оптимизатор перекладывает донор→приёмник.
    'roi':      {'tv': 1.7, 'olv': 3.6, 'ooh': 1.2, 'perf': 6.0},
    'decay':    {'tv': 0.85, 'olv': 0.55, 'ooh': 0.75, 'perf': 0.45},
    'alpha':    {'tv': 1.7, 'olv': 1.7, 'ooh': 1.6, 'perf': 1.8},
    'sat_frac': {'tv': 0.38, 'olv': 2.0, 'ooh': 0.34, 'perf': 3.2},
    'season_amp': 0.15, 'season_peak_wk': 50,
    'media_share': 0.45, 'y_std_frac': 0.10, 'noise_frac': 0.025,
    'competitor_coef': -0.10, 'price_coef': -0.03, 'category_coef': 0.05,
}
FMCG_HIST, FMCG_FUT, FMCG_PPY, FMCG_SEED = 104, 26, 52, 140  # seed 140: backtest directional/reliable


def generate_fmcg() -> pd.DataFrame:
    """FMCG бренд массмаркет, НЕДЕЛЬНЫЙ (104 нед + 26 хвост). KPI «Выручка» ₽.
    Каналы: ТВ+TRP, Онлайн-видео+показы, Наружная+контакты, Performance+клики.
    Контроли: Активность конкурентов, Индекс цен, Продажи категории.
    Прод-байес (use_holidays=False): прирост +11.8%, R² 0.94, backtest directional."""
    gt, n = FMCG_GT, FMCG_HIST
    rng = np.random.default_rng(FMCG_SEED)
    dates = pd.date_range('2023-01-01', periods=n, freq='W-MON')
    wk = dates.isocalendar().week.to_numpy()

    tv   = _indep_channel(rng, wk, 20, 65, peaks=(48, 49, 50, 51, 52), peak_amp=0.35, vol=0.22, floor=5, dark_frac=0.10, period_len=FMCG_PPY)
    olv  = _indep_channel(rng, wk, 11e6, 34e6, peaks=(22, 23, 24), peak_amp=0.28, vol=0.28, floor=2e6, dark_frac=0.05, period_len=FMCG_PPY)
    ooh  = _indep_channel(rng, wk, 50e6, 140e6, peaks=(20, 21, 22, 23), peak_amp=0.30, vol=0.22, floor=10e6, dark_frac=0.08, period_len=FMCG_PPY)
    perf = _indep_channel(rng, wk, 20_000, 55_000, peaks=(10, 38, 39), peak_amp=0.25, vol=0.30, floor=4_000, dark_frac=0.06, period_len=FMCG_PPY)
    phys = {'tv': tv, 'olv': olv, 'ooh': ooh, 'perf': perf}

    tv_s   = tv * _cpp_series(rng, n, 250_000, periods_per_year=FMCG_PPY)
    olv_s  = olv / 1000.0 * _cpp_series(rng, n, 200.0, periods_per_year=FMCG_PPY)
    ooh_s  = ooh / 1000.0 * _cpp_series(rng, n, 80.0, periods_per_year=FMCG_PPY)
    perf_s = perf * _cpp_series(rng, n, 45.0, periods_per_year=FMCG_PPY)
    spends = {'tv': tv_s, 'olv': olv_s, 'ooh': ooh_s, 'perf': perf_s}

    comp = _indep_channel(rng, wk, 25, 180, peaks=(8, 9, 34), peak_amp=0.22, vol=0.28, floor=0.0, period_len=FMCG_PPY)
    price = (1.0 + 0.02 * np.arange(n) / n + 0.03 * rng.standard_normal(n)).clip(0.85, 1.25)
    season = _season_wave(wk, gt['season_amp'], gt['season_peak_wk'], FMCG_PPY)

    ads = {c: _geo_adstock(phys[c], gt['decay'][c]) for c in phys}
    sat_ref = {c: _sat_ref_from_frac(ads[c], gt['sat_frac'][c]) for c in phys}
    hills = {c: _hill_abs(ads[c], gt['alpha'][c], sat_ref[c]) for c in phys}

    base = _money_base(gt['roi'], spends, gt['media_share'], n)
    y_std = base * gt['y_std_frac']
    betas = _betas_money(gt['roi'], hills, spends)
    category = (8.0 * base * (1.0 + 0.8 * season) * (1.0 + 0.03 * np.arange(n) / FMCG_PPY) * (1.0 + 0.04 * rng.standard_normal(n))).clip(min=1e6)

    media_effect = sum(betas[c] * hills[c] for c in betas)
    control_effect = (gt['competitor_coef'] * _normalize(comp) + gt['price_coef'] * _normalize(price) + gt['category_coef'] * _normalize(category))
    sales = (base * (1.0 + season) + media_effect + control_effect * y_std + rng.normal(0, y_std * gt['noise_frac'], n)).clip(min=5e6)

    hist = pd.DataFrame({
        'Дата': dates,
        'Выручка': np.round(sales, 0).astype('int64'),
        'ТВ бюджет': np.round(tv_s, 0).astype('int64'),
        'ТВ TRP': np.round(tv, 1),
        'Онлайн-видео бюджет': np.round(olv_s, 0).astype('int64'),
        'Онлайн-видео показы': np.round(olv, 0).astype('int64'),
        'Наружная реклама бюджет': np.round(ooh_s, 0).astype('int64'),
        'Наружная реклама контакты': np.round(ooh, 0).astype('int64'),
        'Performance бюджет': np.round(perf_s, 0).astype('int64'),
        'Performance клики': np.round(perf, 0).astype('int64'),
        'Активность конкурентов': np.round(comp, 1),
        'Индекс цен': np.round(price, 4),
        'Продажи категории': np.round(category, 0).astype('int64'),
    })
    fut_dates, fs, fp = _future_tail(dates, phys, spends, FMCG_FUT, 'W-MON')
    future = pd.DataFrame({
        'Дата': fut_dates, 'Выручка': [np.nan] * FMCG_FUT,
        'ТВ бюджет': np.round(fs['tv'], 0), 'ТВ TRP': np.round(fp['tv'], 1),
        'Онлайн-видео бюджет': np.round(fs['olv'], 0), 'Онлайн-видео показы': np.round(fp['olv'], 0),
        'Наружная реклама бюджет': np.round(fs['ooh'], 0), 'Наружная реклама контакты': np.round(fp['ooh'], 0),
        'Performance бюджет': np.round(fs['perf'], 0), 'Performance клики': np.round(fp['perf'], 0),
        'Активность конкурентов': [np.nan] * FMCG_FUT, 'Индекс цен': [np.nan] * FMCG_FUT, 'Продажи категории': [np.nan] * FMCG_FUT,
    })
    return pd.concat([hist, future], ignore_index=True)


# ─── OTC противопростудные (месячный, count-KPI) ─────────────────────────────

OTC_GT = {
    # ТВ+Аптека доминируют+перекормлены; Онлайн+Детейлинг недокормлены (высокий ROI).
    'roi':      {'tv': 1.8, 'olv': 4.4, 'apteka': 1.3, 'visits': 4.6},
    'decay':    {'tv': 0.60, 'olv': 0.35, 'apteka': 0.45, 'visits': 0.25},
    'alpha':    {'tv': 1.7, 'olv': 1.7, 'apteka': 1.6, 'visits': 1.8},
    'sat_frac': {'tv': 0.30, 'olv': 2.6, 'apteka': 0.28, 'visits': 2.6},
    'season_amp': 0.22, 'season_peak_m': 1,   # простудный пик январь
    'media_share': 0.52, 'y_std_frac': 0.11, 'noise_frac': 0.025,
    'competitor_coef': -0.10, 'weather_coef': 0.05,
}
OTC_HIST, OTC_FUT, OTC_PPY, OTC_SEED = 60, 12, 12, 245  # seed 245: backtest reliable
OTC_VALUE_PER_UNIT = 400.0  # ₽/упаковка противопростудного OTC


def generate_otc() -> pd.DataFrame:
    """OTC противопростудные, МЕСЯЧНЫЙ (60 мес + 12 хвост). count-KPI «Продажи,
    упаковки». Каналы: ТВ+TRP, Онлайн-видео+показы, Аптечные материалы+контакты,
    Детейлинг+контакты. Контроли: Активность конкурентов, Температура.
    Обучать с use_holidays=False. Прод-байес: +3.3% итог / +13.6% медиа, backtest reliable."""
    gt, n = OTC_GT, OTC_HIST
    rng = np.random.default_rng(OTC_SEED)
    dates = pd.date_range('2021-01-01', periods=n, freq='ME')
    m = dates.month.to_numpy()

    tv   = _indep_channel(rng, m, 55, 170, peaks=(10, 11, 12), peak_amp=0.35, vol=0.22, floor=12, dark_frac=0.10, period_len=OTC_PPY)
    olv  = _indep_channel(rng, m, 18e6, 48e6, peaks=(11, 12, 1), peak_amp=0.30, vol=0.28, floor=3.5e6, dark_frac=0.05, period_len=OTC_PPY)
    apteka = _indep_channel(rng, m, 45e6, 130e6, peaks=(1, 2, 12), peak_amp=0.28, vol=0.20, floor=9e6, dark_frac=0.08, period_len=OTC_PPY)
    visits = _indep_channel(rng, m, 2_200, 6_000, peaks=(9, 10, 11), peak_amp=0.25, vol=0.30, floor=500, dark_frac=0.06, period_len=OTC_PPY)
    phys = {'tv': tv, 'olv': olv, 'apteka': apteka, 'visits': visits}

    tv_s     = tv * _cpp_series(rng, n, 180_000, periods_per_year=OTC_PPY)
    olv_s    = olv / 1000.0 * _cpp_series(rng, n, 250.0, periods_per_year=OTC_PPY)
    apteka_s = apteka / 1000.0 * _cpp_series(rng, n, 400.0, periods_per_year=OTC_PPY)
    visits_s = visits * _cpp_series(rng, n, 3_500.0, periods_per_year=OTC_PPY)
    spends = {'tv': tv_s, 'olv': olv_s, 'apteka': apteka_s, 'visits': visits_s}

    comp = _indep_channel(rng, m, 40, 300, peaks=(4, 5, 9), peak_amp=0.25, vol=0.30, floor=0.0, period_len=OTC_PPY)
    temp_base = -8 * np.cos(2 * np.pi * (m - 1) / 12)
    weather = np.maximum(0, -(temp_base + rng.normal(0, 3, n)))
    season = _season_wave(m, gt['season_amp'], gt['season_peak_m'], OTC_PPY)

    ads = {c: _geo_adstock(phys[c], gt['decay'][c]) for c in phys}
    sat_ref = {c: _sat_ref_from_frac(ads[c], gt['sat_frac'][c]) for c in phys}
    hills = {c: _hill_abs(ads[c], gt['alpha'][c], sat_ref[c]) for c in phys}

    base, y_std, betas = _count_base_betas(gt['roi'], hills, spends, OTC_VALUE_PER_UNIT, gt['media_share'], n, gt['y_std_frac'])
    media_effect = sum(betas[c] * hills[c] for c in betas)
    control_effect = gt['competitor_coef'] * _normalize(comp) + gt['weather_coef'] * _normalize(weather)
    packs = (base * (1.0 + season) + media_effect + control_effect * y_std + rng.normal(0, y_std * gt['noise_frac'], n)).clip(min=10_000)

    hist = pd.DataFrame({
        'Дата': dates,
        'Продажи, упаковки': np.round(packs, 0).astype('int64'),
        'ТВ бюджет': np.round(tv_s, 0).astype('int64'),
        'ТВ TRP': np.round(tv, 1),
        'Онлайн-видео бюджет': np.round(olv_s, 0).astype('int64'),
        'Онлайн-видео показы': np.round(olv, 0).astype('int64'),
        'Аптечные материалы бюджет': np.round(apteka_s, 0).astype('int64'),
        'Аптечные материалы контакты': np.round(apteka, 0).astype('int64'),
        'Детейлинг бюджет': np.round(visits_s, 0).astype('int64'),
        'Детейлинг контакты': np.round(visits, 0).astype('int64'),
        'Активность конкурентов': np.round(comp, 1),
        'Температура': np.round(weather, 2),
    })
    fut_dates, fs, fp = _future_tail(dates, phys, spends, OTC_FUT, 'ME')
    future = pd.DataFrame({
        'Дата': fut_dates, 'Продажи, упаковки': [np.nan] * OTC_FUT,
        'ТВ бюджет': np.round(fs['tv'], 0), 'ТВ TRP': np.round(fp['tv'], 1),
        'Онлайн-видео бюджет': np.round(fs['olv'], 0), 'Онлайн-видео показы': np.round(fp['olv'], 0),
        'Аптечные материалы бюджет': np.round(fs['apteka'], 0), 'Аптечные материалы контакты': np.round(fp['apteka'], 0),
        'Детейлинг бюджет': np.round(fs['visits'], 0), 'Детейлинг контакты': np.round(fp['visits'], 0),
        'Активность конкурентов': [np.nan] * OTC_FUT, 'Температура': [np.nan] * OTC_FUT,
    })
    return pd.concat([hist, future], ignore_index=True)


# ─── Main ────────────────────────────────────────────────────────────────────

GENERATORS = [
    ('synth_fmcg_brand', generate_fmcg),
    ('synth_otc_pharma', generate_otc),
]


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    served_dir = repo_root / 'static' / 'sample-data' / 'planning'
    served_dir.mkdir(parents=True, exist_ok=True)
    for name, gen in GENERATORS:
        df = gen()
        out = served_dir / f'{name}.xlsx'
        df.to_excel(out, index=False, sheet_name='Данные')
        n_hist = int(df.iloc[:, 1].notna().sum())
        print(f'  → {out.name}: {len(df)} строк ({n_hist} история + {len(df) - n_hist} медиаплан) × {len(df.columns)} колонок')
    print(f'\nГотово. Демо планирования: {served_dir}')


if __name__ == '__main__':
    main()
