"""Aurora Econometrica — авто-инъекция сезонной Фурье-компоненты (v2.2, 2026-07-04).

МОТИВАЦИЯ. Праздники РФ (holiday_calendar_ru) уже инжектятся автоматически как
12 точечных dummy-регрессоров. Но они ловят только КАЛЕНДАРНЫЕ ВСПЛЕСКИ, не
гладкую сезонную волну спроса (сезон гриппа октябрь→март, аллергия весной,
летний спад FMCG). Без сезонных контролей модель списывает волну спроса на
медиа → завышенный/искажённый ROI, а backtest-витрина честно бракует модель
как «не точнее наивного сезонного прогноза» (боевой случай Kagocel/MMX 2026-07).

РЕШЕНИЕ (автосезонность А). Гибкая периодическая волна раскладывается в ряд
Фурье: sum_k [a_k·sin(2πkt/P) + b_k·cos(2πkt/P)]. K пар гармоник дают гладкую
кривую произвольной формы с периодом P; модель оценивает коэффициенты a_k, b_k
как обычные контроли. Это канон Prophet (Taylor & Letham 2018, «Forecasting at
Scale», §3.2 seasonality), перенятый Robyn (Facebook MMM, prophet-декомпозиция
тренда/сезонности) и Google Meridian. Период P берётся из detect_seasonality
(автокорреляционный детектор, forecast_validation.py) — не задаётся вручную.

ЧЕСТНЫЙ ГЕЙТ. Оценить сезонность периода P можно лишь при ≥2 полных циклах в
данных (иначе гармоники неотличимы от тренда — переобучение). n_obs ≥ 2·P.
Поэтому короткий ряд (Kagocel 31 нед < 2·52) НЕ получает годовую компоненту —
но может получить квартальную (P=13: 31 ≥ 26). Это принцип INV-50: не подавать
недоказуемую сезонность.

ПАРИТЕТ. Как и с праздниками, инжектированные Фурье-колонки сохраняются в
model_data['fourier_seasonality'] и переинжектятся decomposer'ом бит-в-бит
(детерминизм по t-индексу, без зависимости от дат — чистая позиция в ряду).
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Префикс инжектированных колонок — распознаётся как control-фактор наравне с
# holiday_* (validator.py::CONTROL_PATTERNS), но семантически это сезонность.
FOURIER_COL_PREFIX = 'season_fourier'

# Минимум полных циклов периода в обучающих данных для оценки гармоник.
# < 2 циклов → сезонность неотличима от тренда (Prophet требует ≥2, здесь строго).
MIN_CYCLES_FOR_SEASONALITY = 2

# Порог автокорреляции для доверия детектору (совпадает с detect_seasonality
# default autocorr_threshold=0.2 — но требуем строго положительную: настоящая
# циклическая повторяемость, не анти-фаза полупериода).
MIN_AUTOCORR_FOR_INJECTION = 0.2


def decide_n_harmonics(period: int) -> int:
    """Разумное число пар гармоник K для периода P.

    Компромисс гибкость↔переобучение: больше K — тоньше форма волны, но больше
    параметров (2K степеней свободы). Prophet: yearly=10, weekly=3. Для MMM с
    десятками наблюдений держим консервативно: K ≈ P/4, зажато в [1, 4] и не
    выше предела Найквиста (P/2 — больше физически неразличимо на решётке).

    Args:
        period: длина сезонного цикла в шагах ряда (нед/мес).

    Returns:
        K ≥ 1 пар (sin, cos).
    """
    if period < 2:
        return 1
    nyquist_cap = period // 2
    k = max(1, min(4, period // 4))
    return min(k, nyquist_cap)


def should_inject_seasonality(
    seasonality_detected: Optional[dict],
    n_obs: int,
    *,
    min_cycles: int = MIN_CYCLES_FOR_SEASONALITY,
) -> tuple[bool, str]:
    """Гейт: можно ли честно оценить сезонную компоненту.

    Args:
        seasonality_detected: результат detect_seasonality ({period, autocorr, ...})
            или None если детектор ничего не нашёл.
        n_obs: число обучающих наблюдений.
        min_cycles: минимум полных циклов периода в данных (default 2).

    Returns:
        (inject, reason) — inject True/False + человекочитаемая причина (лог + честность).
    """
    if not seasonality_detected:
        return False, 'сезонность не обнаружена детектором'

    period = seasonality_detected.get('period')
    autocorr = seasonality_detected.get('autocorr')
    if not isinstance(period, (int, float)) or period < 2:
        return False, f'период невалиден ({period})'
    period = int(period)

    # Анти-фаза (отрицательная автокорреляция) — детектор мог зацепить полупериод.
    # Для инъекции требуем настоящую положительную циклическую повторяемость.
    if autocorr is None or autocorr < MIN_AUTOCORR_FOR_INJECTION:
        return False, (
            f'автокорреляция {autocorr} < порога {MIN_AUTOCORR_FOR_INJECTION} '
            f'(нет уверенной положительной сезонности)'
        )

    needed = min_cycles * period
    if n_obs < needed:
        return False, (
            f'данных {n_obs} < {needed} (нужно ≥{min_cycles} полных циклов '
            f'периода {period}) — сезонность неотличима от тренда'
        )

    return True, f'период {period}, ≥{min_cycles} циклов в {n_obs} набл.'


def generate_fourier_terms(
    n_obs: int,
    period: int,
    n_harmonics: int,
) -> pd.DataFrame:
    """Сгенерировать Фурье-регрессоры сезонности для ряда длины n_obs.

    Гармоники строятся по ПОЗИЦИИ в ряду (t = 0..n_obs-1), не по календарным
    датам — это гарантирует детерминизм и бит-в-бит паритет между обучением и
    декомпозицией (t-индекс воспроизводим без парсинга дат).

    Args:
        n_obs: длина обучающего ряда.
        period: период сезонности P (шагов на цикл).
        n_harmonics: число пар гармоник K.

    Returns:
        DataFrame (n_obs × 2K): колонки season_fourier_sin_1..K, season_fourier_cos_1..K.
        Значения в [-1, 1]. Пустой DataFrame если параметры вырождены.
    """
    if n_obs <= 0 or period < 2 or n_harmonics < 1:
        return pd.DataFrame(index=pd.RangeIndex(max(n_obs, 0)))

    t = np.arange(n_obs, dtype=np.float64)
    cols: dict[str, np.ndarray] = {}
    for k in range(1, n_harmonics + 1):
        angle = 2.0 * np.pi * k * t / float(period)
        cols[f'{FOURIER_COL_PREFIX}_sin_{k}'] = np.sin(angle)
        cols[f'{FOURIER_COL_PREFIX}_cos_{k}'] = np.cos(angle)

    return pd.DataFrame(cols, index=pd.RangeIndex(n_obs))


def list_fourier_columns(period: int, n_harmonics: int) -> list[str]:
    """Имена Фурье-колонок для (period, n_harmonics) — для паритета decomposer/persist."""
    if period < 2 or n_harmonics < 1:
        return []
    names: list[str] = []
    for k in range(1, n_harmonics + 1):
        names.append(f'{FOURIER_COL_PREFIX}_sin_{k}')
        names.append(f'{FOURIER_COL_PREFIX}_cos_{k}')
    return names
