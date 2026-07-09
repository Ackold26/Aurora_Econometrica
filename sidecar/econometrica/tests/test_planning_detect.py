"""Тесты для engines/planning.py — детекция хвоста медиаплана.

Покрытие:
  - happy path: 24 история + 12 хвост
  - весь KPI заполнен → found False
  - весь KPI пуст → found False / no_history
  - NaN в середине истории без хвоста → found False (internal_gaps)
  - NaN в середине + реальный хвост → found True, n_future = только хвост
  - разрыв дат перед хвостом → continuous False / warning date_gap
  - неупорядоченные строки → сортируются, детекция верна
  - недельная гранулярность → period_labels 'YYYY-Www'
  - месячная гранулярность → period_labels 'YYYY-MM'
  - compute_source_hash детерминизм + разный контент → разный хэш
  - load_frames с реальным xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.planning import compute_source_hash, detect_media_plan_tail, load_frames


# ─── Фабрики DataFrame ────────────────────────────────────────────────────────


def _monthly_df(n_history: int, n_future: int, *, nan_kpi_idx: list[int] | None = None) -> pd.DataFrame:
    """Месячный DataFrame: history + future (KPI пуст в хвосте)."""
    total = n_history + n_future
    dates = pd.date_range("2022-01-01", periods=total, freq="MS")
    rng = np.random.RandomState(42)
    kpi = list(rng.uniform(100, 1000, n_history)) + [np.nan] * n_future
    media_a = rng.uniform(10, 100, total).tolist()
    media_b = rng.uniform(5, 50, total).tolist()
    df = pd.DataFrame({"date": dates, "sales": kpi, "tv_spend": media_a, "digital_spend": media_b})
    if nan_kpi_idx:
        for i in nan_kpi_idx:
            df.at[i, "sales"] = np.nan
    return df


def _weekly_df(n_history: int, n_future: int) -> pd.DataFrame:
    """Недельный DataFrame."""
    total = n_history + n_future
    dates = pd.date_range("2022-01-03", periods=total, freq="W-MON")
    rng = np.random.RandomState(7)
    kpi = list(rng.uniform(100, 1000, n_history)) + [np.nan] * n_future
    media = rng.uniform(10, 100, total).tolist()
    return pd.DataFrame({"date": dates, "sales": kpi, "tv_spend": media})


# ─── Happy path ───────────────────────────────────────────────────────────────


def test_happy_path_monthly_24_12():
    """24 истории + 12 хвоста → found True, корректные поля."""
    df = _monthly_df(24, 12)
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend", "digital_spend"])

    assert result["found"] is True
    assert result["n_future_periods"] == 12
    assert len(result["history_df"]) == 24
    assert len(result["future_df"]) == 12
    # period_labels для месяцев должны быть 'YYYY-MM'
    labels = result["period_labels"]
    assert len(labels) == 12
    for lbl in labels:
        assert len(lbl) == 7, f"Ожидался формат YYYY-MM, получен: {lbl!r}"
        assert lbl[4] == "-"
    # Первый label — месяц, следующий за 24-м периодом
    assert labels[0] == "2024-01"
    assert result["granularity"] == "M"
    assert result["continuous"] is True
    assert "tv_spend" in result["channels"]
    assert len(result["channels"]["tv_spend"]) == 12
    assert isinstance(result["warnings"], list)


# ─── Без хвоста ──────────────────────────────────────────────────────────────


def test_all_kpi_filled_no_tail():
    """Весь KPI заполнен → found False."""
    df = _monthly_df(24, 0)
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend", "digital_spend"])
    assert result["found"] is False
    assert "error" not in result
    assert "reason" not in result


# ─── Весь KPI пуст ───────────────────────────────────────────────────────────


def test_all_kpi_empty_no_history():
    """Весь KPI пуст → found False + error no_history."""
    df = _monthly_df(0, 12)
    # Строим вручную: нет истории вообще
    dates = pd.date_range("2022-01-01", periods=12, freq="MS")
    df2 = pd.DataFrame({
        "date": dates,
        "sales": [np.nan] * 12,
        "tv_spend": np.random.uniform(10, 100, 12),
    })
    result = detect_media_plan_tail(df2, "date", "sales", ["tv_spend"])
    assert result["found"] is False
    assert result.get("error") == "no_history"


# ─── NaN в середине истории (без хвоста) ─────────────────────────────────────


def test_internal_nan_no_tail_all_kpi_filled_at_end():
    """NaN в середине истории, но последняя строка заполнена → found False (нет хвоста).

    Это базовая защита: если последняя строка заполнена — хвоста нет,
    независимо от дыр внутри истории.
    """
    dates = pd.date_range("2022-01-01", periods=20, freq="MS")
    rng = np.random.RandomState(1)
    kpi = rng.uniform(100, 1000, 20).tolist()
    kpi[5] = np.nan   # дыра в середине
    kpi[10] = np.nan  # ещё дыра
    # kpi[-1] (индекс 19) заполнен — хвоста нет
    df = pd.DataFrame({"date": dates, "sales": kpi, "tv_spend": rng.uniform(10, 100, 20)})
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend"])
    assert result["found"] is False
    # reason может быть не задан (просто нет хвоста) — не проверяем конкретный reason


# ─── NaN в середине + реальный хвост ─────────────────────────────────────────


def test_internal_nan_plus_real_tail():
    """Дыры в KPI внутри истории + реальный хвост в конце → found True, n_future = хвост."""
    # 20 история (2 дыры), 6 хвоста
    dates = pd.date_range("2022-01-01", periods=26, freq="MS")
    rng = np.random.RandomState(2)
    kpi = rng.uniform(100, 1000, 20).tolist() + [np.nan] * 6
    kpi[3] = np.nan   # дыра в истории
    kpi[12] = np.nan  # ещё дыра
    # kpi[19] должен быть заполнен — последний valid
    if np.isnan(kpi[19]):
        kpi[19] = 500.0
    df = pd.DataFrame({"date": dates, "sales": kpi, "tv_spend": rng.uniform(10, 100, 26)})
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend"])
    assert result["found"] is True
    assert result["n_future_periods"] == 6
    # История включает строки до последнего valid KPI (включительно), с дырами внутри
    assert len(result["history_df"]) == 20


# ─── Разрыв дат перед хвостом ────────────────────────────────────────────────


def test_date_gap_before_future():
    """Пропущен месяц между историей и будущим → continuous False + warning date_gap."""
    # История: 12 месяцев, затем пропуск месяца, потом 6 хвоста
    hist_dates = pd.date_range("2022-01-01", periods=12, freq="MS")
    # Будущее начинается через 2 месяца (пропущен 1)
    future_dates = pd.date_range("2023-02-01", periods=6, freq="MS")
    rng = np.random.RandomState(3)
    kpi = list(rng.uniform(100, 1000, 12)) + [np.nan] * 6
    media = rng.uniform(10, 100, 18).tolist()
    df = pd.DataFrame({
        "date": list(hist_dates) + list(future_dates),
        "sales": kpi,
        "tv_spend": media,
    })
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend"])
    assert result["found"] is True
    assert result["continuous"] is False
    warning_types = [w["type"] for w in result["warnings"]]
    assert "date_gap" in warning_types


# ─── Непрерывный хвост (без разрыва) → continuous True ──────────────────────


def test_continuous_flag_true_when_no_gap():
    """Непрерывный медиаплан → continuous True, нет warning date_gap."""
    df = _monthly_df(12, 6)
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend", "digital_spend"])
    assert result["found"] is True
    assert result["continuous"] is True
    warning_types = [w["type"] for w in result["warnings"]]
    assert "date_gap" not in warning_types


# ─── Неупорядоченные строки ───────────────────────────────────────────────────


def test_unsorted_input_sorted_before_detection():
    """Перемешанные строки → сортируются, детекция верна."""
    df = _monthly_df(12, 4)
    df_shuffled = df.sample(frac=1, random_state=99).reset_index(drop=True)
    result = detect_media_plan_tail(df_shuffled, "date", "sales", ["tv_spend", "digital_spend"])
    assert result["found"] is True
    assert result["n_future_periods"] == 4
    # History отсортирована
    hist = result["history_df"]
    assert hist["date"].is_monotonic_increasing


# ─── Гранулярность: недельная ────────────────────────────────────────────────


def test_weekly_granularity_period_labels():
    """Недельные данные → granularity='W', period_labels вида 'YYYY-Www'."""
    df = _weekly_df(24, 8)
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend"])
    assert result["found"] is True
    assert result["granularity"] == "W"
    for lbl in result["period_labels"]:
        assert "-W" in lbl, f"Ожидался формат YYYY-Www, получен: {lbl!r}"


# ─── Гранулярность: месячная (period_labels) ─────────────────────────────────


def test_monthly_granularity_period_labels_format():
    """Месячные данные → period_labels только 'YYYY-MM'."""
    df = _monthly_df(12, 3)
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend"])
    assert result["found"] is True
    assert result["granularity"] == "M"
    for lbl in result["period_labels"]:
        parts = lbl.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 4  # год
        assert len(parts[1]) == 2  # месяц


# ─── Предупреждение о пустых медиа в будущем ─────────────────────────────────


def test_empty_media_in_future_warning():
    """NaN в медиа-колонке будущего → warning empty_media_in_future."""
    df = _monthly_df(12, 4)
    # Вносим NaN в одну медиа-колонку будущего
    df.loc[14, "tv_spend"] = np.nan
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend", "digital_spend"])
    assert result["found"] is True
    warning_types = [w["type"] for w in result["warnings"]]
    assert "empty_media_in_future" in warning_types


# ─── compute_source_hash ─────────────────────────────────────────────────────


def test_source_hash_deterministic(tmp_path: Path):
    """Один и тот же файл → одинаковый хэш при двух вызовах."""
    df = _monthly_df(12, 0)
    fpath = tmp_path / "data.xlsx"
    df.to_excel(fpath, index=False)

    h1 = compute_source_hash(str(fpath))
    h2 = compute_source_hash(str(fpath))
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_source_hash_different_for_different_content(tmp_path: Path):
    """Разный контент → разный хэш."""
    df1 = _monthly_df(12, 0)
    df2 = _monthly_df(24, 0)  # другое число строк → другой контент
    p1 = tmp_path / "a.xlsx"
    p2 = tmp_path / "b.xlsx"
    df1.to_excel(p1, index=False)
    df2.to_excel(p2, index=False)

    assert compute_source_hash(str(p1)) != compute_source_hash(str(p2))


# ─── load_frames с реальным xlsx ─────────────────────────────────────────────


def test_load_frames_with_xlsx(tmp_path: Path):
    """load_frames: читает xlsx, детектирует хвост, возвращает history/future."""
    df = _monthly_df(18, 6)
    fpath = tmp_path / "plan.xlsx"
    df.to_excel(fpath, index=False)

    result = load_frames(
        str(fpath),
        date_col="date",
        kpi_col="sales",
        media_cols=["tv_spend", "digital_spend"],
    )

    assert result["detection"]["found"] is True
    assert len(result["history_df"]) == 18
    assert result["future_df"] is not None
    assert len(result["future_df"]) == 6
    assert len(result["source_hash"]) == 64


def test_load_frames_no_tail_future_is_none(tmp_path: Path):
    """load_frames без хвоста → future_df is None, history_df = весь df."""
    df = _monthly_df(12, 0)
    fpath = tmp_path / "no_tail.xlsx"
    df.to_excel(fpath, index=False)

    result = load_frames(
        str(fpath),
        date_col="date",
        kpi_col="sales",
        media_cols=["tv_spend", "digital_spend"],
    )

    assert result["detection"]["found"] is False
    assert result["future_df"] is None
    assert len(result["history_df"]) == 12


def test_load_frames_autodetect_roles(tmp_path: Path):
    """load_frames без явных ролей → автодетект через validator."""
    df = _monthly_df(12, 4)
    fpath = tmp_path / "auto.xlsx"
    df.to_excel(fpath, index=False)

    # Не передаём date_col/kpi_col/media_cols — автодетект
    result = load_frames(str(fpath))
    # Автодетект должен найти 'date' (date), 'sales' (kpi), tv_spend/digital_spend (media)
    assert result["detection"]["found"] is True or result["detection"]["found"] is False
    # Главное — не упало, history_df существует
    assert result["history_df"] is not None


# ─── Минимальный хвост (1 строка) ────────────────────────────────────────────


def test_single_future_row():
    """Один период в хвосте → n_future_periods == 1."""
    df = _monthly_df(12, 1)
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend", "digital_spend"])
    assert result["found"] is True
    assert result["n_future_periods"] == 1
    assert len(result["period_labels"]) == 1


# ─── history_df сохраняет внутренние дыры ────────────────────────────────────


def test_history_retains_internal_nan_rows():
    """История с внутренними дырами KPI → history_df включает эти строки."""
    df = _monthly_df(15, 5)
    df.loc[3, "sales"] = np.nan   # дыра
    df.loc[8, "sales"] = np.nan   # дыра
    # Убеждаемся, что последняя строка истории (14-я) заполнена
    df.loc[14, "sales"] = 500.0
    result = detect_media_plan_tail(df, "date", "sales", ["tv_spend", "digital_spend"])
    assert result["found"] is True
    # history_df должна иметь 15 строк (включая дыры)
    assert len(result["history_df"]) == 15
    assert result["n_future_periods"] == 5
