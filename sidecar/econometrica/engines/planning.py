"""SSOT-модуль детекции хвоста медиаплана (planning mode).

Задача: в одном Excel-файле после исторических строк (KPI заполнен) может
идти «хвост будущего» — строки с пустым KPI и заполненными инвестициями.
Этот модуль распознаёт границу истории/будущего и возвращает чистые DataFrame
без сайд-эффектов.

Публичное API:
  detect_media_plan_tail(df, date_col, kpi_col, media_cols) -> dict
  compute_source_hash(data_file) -> str
  load_frames(data_file, date_col, kpi_col, media_cols) -> dict
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Размер блока для хэша (первые 512 КБ — дёшево, детерминированно)
_HASH_READ_BYTES = 512 * 1024


# ─── Вспомогательные ────────────────────────────────────────────────────────


def _period_label(dt: "pd.Timestamp", granularity: str) -> str:
    """Человекочитаемый ярлык периода по гранулярности."""
    if granularity == "M":
        return dt.strftime("%Y-%m")
    if granularity == "W":
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if granularity == "D":
        return dt.strftime("%Y-%m-%d")
    if granularity == "Q":
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{q}"
    if granularity == "Y":
        return str(dt.year)
    return dt.strftime("%Y-%m-%d")


def _expected_next(last_hist: "pd.Timestamp", granularity: str) -> "pd.Timestamp":
    """Ожидаемая первая дата будущего (ровно один период за последней историей)."""
    if granularity == "D":
        return last_hist + pd.Timedelta(days=1)
    if granularity == "W":
        return last_hist + pd.Timedelta(weeks=1)
    if granularity == "M":
        return last_hist + pd.DateOffset(months=1)
    if granularity == "Q":
        return last_hist + pd.DateOffset(months=3)
    if granularity == "Y":
        return last_hist + pd.DateOffset(years=1)
    # Для «unknown» / прочих — используем медианный шаг как запас, возвращаем None-sentinel
    return last_hist + pd.Timedelta(days=1)


def _days_gap_tolerance(granularity: str) -> float:
    """Допустимое отклонение от «ровного» следующего периода (в днях).

    Месяцы имеют 28-31 день — нужен более широкий допуск.
    """
    return {
        "D": 0.5,
        "W": 1.0,
        "M": 5.0,
        "Q": 10.0,
        "Y": 30.0,
    }.get(granularity, 3.0)


# ─── Основная функция ────────────────────────────────────────────────────────


def detect_media_plan_tail(
    df: "pd.DataFrame",
    date_col: str,
    kpi_col: str,
    media_cols: list[str],
) -> dict[str, Any]:
    """Обнаружить хвост медиаплана в DataFrame.

    Аргументы:
        df: DataFrame со смешанными историческими строками и строками плана.
        date_col: имя колонки с датами.
        kpi_col: имя KPI-колонки (продажи).
        media_cols: список колонок инвестиций/медиа.

    Возвращает dict:
        {found: False}  — хвоста нет.
        {found: False, error: 'no_history'}  — весь KPI пуст.
        {found: False, reason: 'internal_gaps'}  — NaN в середине истории (не хвост).
        {
            found: True,
            n_future_periods: int,
            history_df: DataFrame,
            future_df: DataFrame,
            future_dates: [isoformat str],
            period_labels: [str],
            granularity: str ('D'|'W'|'M'|'Q'|'Y'|'unknown'),
            channels: {col: [float]},
            continuous: bool,
            warnings: [{type, message}],
        }
    """
    # Работаем на копии, не трогаем оригинал
    work = df.copy()

    # Приводим даты и сортируем
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.sort_values(date_col).reset_index(drop=True)

    kpi = work[kpi_col]

    # Случай 1: весь KPI пуст
    if kpi.last_valid_index() is None:
        return {"found": False, "error": "no_history"}

    last_idx = len(work) - 1

    # Случай 2: хвоста нет — последняя строка заполнена
    if pd.notna(kpi.iloc[-1]):
        return {"found": False}

    # Граница истории: последний индекс с непустым KPI
    boundary = int(kpi.last_valid_index())  # type: ignore[arg-type]

    # Хвост = строки после boundary
    tail_kpi = kpi.iloc[boundary + 1:]

    # Случай 3: проверка непрерывности хвоста.
    # Все строки ПОСЛЕ boundary должны иметь пустой KPI.
    # Если хоть одна строка хвоста имеет непустой KPI — это дыры в середине, не хвост.
    if tail_kpi.notna().any():
        return {"found": False, "reason": "internal_gaps"}

    history_df = work.iloc[: boundary + 1].copy()
    future_df = work.iloc[boundary + 1 :].copy()

    # Определяем гранулярность по истории
    from utils.forecast_validation import detect_granularity  # SSOT

    gran_result = detect_granularity(history_df[date_col])
    granularity: str = gran_result.get("granularity", "W")

    warnings: list[dict[str, str]] = []

    # Проверка непрерывности дат (A8)
    last_hist_date = history_df[date_col].dropna().iloc[-1]
    first_future_date = future_df[date_col].dropna().iloc[0]
    expected = _expected_next(last_hist_date, granularity)
    gap_days = abs((first_future_date - expected).total_seconds()) / 86400
    tolerance = _days_gap_tolerance(granularity)
    continuous = gap_days <= tolerance

    if not continuous:
        warnings.append(
            {
                "type": "date_gap",
                "message": (
                    f"Разрыв дат между историей и будущим: ожидалась {expected.date()}, "
                    f"получена {first_future_date.date()} "
                    f"(отклонение {gap_days:.1f} дн. при допуске {tolerance} дн.)."
                ),
            }
        )

    # Предупреждение: пустые медиа в будущем
    for col in media_cols:
        if col in future_df.columns:
            if future_df[col].isna().any():
                warnings.append(
                    {
                        "type": "empty_media_in_future",
                        "message": f"Колонка «{col}» содержит пустые значения в строках плана.",
                    }
                )

    # Собираем каналы: {col: [float]} — NaN → None для JSON-безопасности
    channels: dict[str, list[Any]] = {}
    for col in media_cols:
        if col in future_df.columns:
            vals = future_df[col].tolist()
            channels[col] = [float(v) if pd.notna(v) else None for v in vals]

    future_dates = [
        ts.isoformat() if pd.notna(ts) else None
        for ts in future_df[date_col]
    ]
    period_labels = [
        _period_label(ts, granularity) if pd.notna(ts) else ""
        for ts in future_df[date_col]
    ]

    return {
        "found": True,
        "n_future_periods": len(future_df),
        "history_df": history_df,
        "future_df": future_df,
        "future_dates": future_dates,
        "period_labels": period_labels,
        "granularity": granularity,
        "channels": channels,
        "continuous": continuous,
        "warnings": warnings,
    }


# ─── Хэш файла ──────────────────────────────────────────────────────────────


def compute_source_hash(data_file: str) -> str:
    """SHA-256 первых 512 КБ + размер файла.

    Детерминирован, дёшев — для сверки «тот ли файл был при обучении».

    Args:
        data_file: путь к xlsx/csv.

    Returns:
        hex-строка SHA-256 (64 символа).
    """
    p = Path(data_file)
    file_size = p.stat().st_size
    h = hashlib.sha256()
    with open(p, "rb") as f:
        chunk = f.read(_HASH_READ_BYTES)
        h.update(chunk)
    # Добавляем размер файла в хэш для устойчивости к коротким файлам
    h.update(file_size.to_bytes(8, "big"))
    return h.hexdigest()


# ─── Обёртка для чтения файла ────────────────────────────────────────────────


def _read_file(path: Path) -> "pd.DataFrame":
    """Читаем xlsx/csv в DataFrame (переиспользуем логику validator)."""
    if path.suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if path.suffix == ".csv":
        # C1: CSV русского Excel с «;» в качестве разделителя
        df = pd.read_csv(path)
        if df.shape[1] == 1 and ";" in str(df.columns[0]):
            df = pd.read_csv(path, sep=";")
        return df
    raise ValueError(f"Неподдерживаемый формат: {path.suffix}. Нужен xlsx или csv.")


def load_frames(
    data_file: str,
    date_col: str | None = None,
    kpi_col: str | None = None,
    media_cols: list[str] | None = None,
) -> dict[str, Any]:
    """SSOT-точка входа: читает файл, авто-детектирует роли, разделяет историю/план.

    Аргументы:
        data_file: путь к xlsx/csv.
        date_col: имя колонки дат (если None — автодетект).
        kpi_col: имя KPI-колонки (если None — автодетект).
        media_cols: список медиа-колонок (если None — автодетект).

    Возвращает:
        {
            history_df: DataFrame с историческими строками,
            future_df: DataFrame | None — строки медиаплана или None,
            detection: dict — результат detect_media_plan_tail,
            source_hash: str,
        }

    Без сайд-эффектов: никакой записи файлов.
    """
    path = Path(data_file)
    df = _read_file(path)

    # Автодетект ролей при необходимости
    if date_col is None or kpi_col is None or media_cols is None:
        from engines.validator import detect_column_role_with_confidence

        detected_date: str | None = None
        detected_kpi: str | None = None
        detected_media: list[str] = []

        for col in df.columns:
            role, _conf = detect_column_role_with_confidence(col)
            if role == "date" and detected_date is None:
                detected_date = str(col)
            elif role == "kpi" and detected_kpi is None:
                detected_kpi = str(col)
            elif role == "media":
                detected_media.append(str(col))

        if date_col is None:
            date_col = detected_date
        if kpi_col is None:
            kpi_col = detected_kpi
        if media_cols is None:
            media_cols = detected_media

    if not date_col:
        raise ValueError("Не удалось определить колонку дат. Передайте date_col явно.")
    if not kpi_col:
        raise ValueError("Не удалось определить KPI-колонку. Передайте kpi_col явно.")
    if not media_cols:
        media_cols = []

    src_hash = compute_source_hash(data_file)
    detection = detect_media_plan_tail(df, date_col, kpi_col, media_cols)

    if detection.get("found"):
        history_df = detection["history_df"]
        future_df = detection["future_df"]
    else:
        history_df = df.copy()
        future_df = None

    return {
        "history_df": history_df,
        "future_df": future_df,
        "detection": detection,
        "source_hash": src_hash,
    }
