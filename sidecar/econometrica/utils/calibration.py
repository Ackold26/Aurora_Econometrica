"""E2 (2026-07-03): калибровка модели lift-тестами — подготовка и валидация.

Канон: Robyn (Meta 2024, arXiv 2403.14674) §2.2/§4.3 — калибровка
экспериментами как метод идентификации (двигает оценки по «спектру
инкрементальности» к RCT-истине); Jin et al. 2017 — experiments as priors.
Реализация Aurora — MAPE.LIFT-класс: измеренный lift входит в модель
ДОПОЛНИТЕЛЬНЫМ НАБЛЮДЕНИЕМ правдоподобия (см. modeler), поэтому adstock/
насыщение/β согласуются с тестом совместно, без ручного пересчёта приора.

Этот модуль — чистая (без PyMC) подготовка: валидация входа, даты → индексы
строк, интервал теста → σ. Ошибки — русские, с действием.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

#: z-квантили поддерживаемых уровней интервала теста (двусторонний).
_Z_BY_CONFIDENCE = {0.8: 1.2816, 0.9: 1.6449, 0.95: 1.9600}

#: Минимальная длина периода теста в наблюдениях (1 точка = слишком шумно).
MIN_TEST_PERIODS = 2


class CalibrationError(ValueError):
    """Невалидный вход калибровки — сообщение готово для пользователя."""


def prepare_calibrations(
    df: pd.DataFrame,
    calibrations: list[dict] | None,
    *,
    media_columns: list[str],
    date_column: str = 'date',
) -> list[dict[str, Any]]:
    """Проверить и подготовить калибровки к вживлению в модель.

    Args:
        df: обучающие данные (уже после merge_rules).
        calibrations: [{channel, date_from, date_to, lift_abs,
            lift_low?, lift_high?, confidence_level?, test_type?}].
            Интервал теста задаётся либо (lift_low, lift_high [+ level]),
            либо прямо sigma_abs.
        media_columns: допустимые каналы.
        date_column: колонка дат данных.

    Returns:
        [{channel, idx_from, idx_to (полуинтервал [from, to)), lift_abs,
          sigma_abs, test_type, date_from, date_to, n_periods}] — только
        валидные записи; пустой вход → [].

    Raises:
        CalibrationError: канал не из модели / даты вне данных / период короче
        MIN_TEST_PERIODS / интервал не задан или вырожден / нулевые траты
        канала в период теста (тест нечего калибровать).
    """
    if not calibrations:
        return []
    if date_column not in df.columns:
        raise CalibrationError(
            f'Для калибровки нужна колонка дат «{date_column}» — в данных её нет.'
        )
    dates = pd.to_datetime(df[date_column], errors='coerce')
    if dates.isna().all():
        raise CalibrationError(
            f'Колонка дат «{date_column}» не распознаётся как даты — '
            f'калибровка по периоду теста невозможна.'
        )

    out: list[dict[str, Any]] = []
    for i, c in enumerate(calibrations, start=1):
        ch = c.get('channel')
        if ch not in media_columns:
            raise CalibrationError(
                f'Калибровка №{i}: канал «{ch}» не входит в медиа-каналы модели. '
                f'Доступные: {", ".join(media_columns)}.'
            )
        try:
            d_from = pd.to_datetime(c.get('date_from'))
            d_to = pd.to_datetime(c.get('date_to'))
        except (ValueError, TypeError) as exc:
            raise CalibrationError(
                f'Калибровка №{i} ({ch}): даты периода теста не распознаны '
                f'({c.get("date_from")!r} — {c.get("date_to")!r}).'
            ) from exc
        if pd.isna(d_from) or pd.isna(d_to) or d_to < d_from:
            raise CalibrationError(
                f'Калибровка №{i} ({ch}): период теста задан неверно '
                f'({c.get("date_from")!r} — {c.get("date_to")!r}).'
            )
        mask = (dates >= d_from) & (dates <= d_to)
        idx = np.flatnonzero(mask.to_numpy())
        if idx.size < MIN_TEST_PERIODS:
            raise CalibrationError(
                f'Калибровка №{i} ({ch}): в период теста попадает {idx.size} '
                f'наблюдений (нужно ≥ {MIN_TEST_PERIODS}). Проверьте даты — '
                f'обучающие данные покрывают {dates.min().date()} — {dates.max().date()}.'
            )
        idx_from, idx_to = int(idx[0]), int(idx[-1]) + 1
        if int(idx.size) != idx_to - idx_from:
            raise CalibrationError(
                f'Калибровка №{i} ({ch}): период теста не сплошной по датам данных.'
            )

        spend = df[ch].iloc[idx_from:idx_to].fillna(0).to_numpy(dtype=float)
        if not np.any(spend > 0):
            raise CalibrationError(
                f'Калибровка №{i} ({ch}): в период теста у канала нет затрат — '
                f'измеренный lift не с чем связывать.'
            )

        lift_abs = c.get('lift_abs')
        if lift_abs is None or not np.isfinite(float(lift_abs)):
            raise CalibrationError(
                f'Калибровка №{i} ({ch}): не задан измеренный lift (lift_abs, '
                f'в единицах KPI за период теста).'
            )
        lift_abs = float(lift_abs)

        sigma_abs = c.get('sigma_abs')
        if sigma_abs is None:
            lo, hi = c.get('lift_low'), c.get('lift_high')
            if lo is None or hi is None or float(hi) <= float(lo):
                raise CalibrationError(
                    f'Калибровка №{i} ({ch}): задайте интервал теста '
                    f'(lift_low < lift_high) или sigma_abs.'
                )
            level = float(c.get('confidence_level') or 0.9)
            z = _Z_BY_CONFIDENCE.get(round(level, 2))
            if z is None:
                raise CalibrationError(
                    f'Калибровка №{i} ({ch}): confidence_level {level} не '
                    f'поддерживается (допустимо 0.8 / 0.9 / 0.95).'
                )
            sigma_abs = (float(hi) - float(lo)) / (2.0 * z)
        sigma_abs = float(sigma_abs)
        if not np.isfinite(sigma_abs) or sigma_abs <= 0:
            raise CalibrationError(
                f'Калибровка №{i} ({ch}): σ теста должна быть положительной.'
            )

        out.append({
            'channel': ch,
            'idx_from': idx_from,
            'idx_to': idx_to,
            'n_periods': idx_to - idx_from,
            'lift_abs': lift_abs,
            'sigma_abs': sigma_abs,
            'test_type': str(c.get('test_type') or 'lift_test'),
            'date_from': str(pd.Timestamp(d_from).date()),
            'date_to': str(pd.Timestamp(d_to).date()),
        })
    return out
