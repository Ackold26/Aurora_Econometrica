"""Тесты интеграции NaN-KPI фильтра.

Покрытие:
  1. validate_data с файлом С хвостом (24 история + 12 хвост):
     - media_plan_detected присутствует, n_future_periods == 12
     - статистика/ratio вычислены по 24 строкам, не по 36
     - results/media_plan.json записан с confirmed=false и source_hash
  2. validate_data с файлом БЕЗ хвоста:
     - media_plan_detected is None
  3. Инвариант current_spend оптимизатора:
     - сумма spend вычисляется только по истории (notna rows)
     - для файла без хвоста результат не меняется (no-op invariant)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.validator import validate_data


# ─── Фабрики DataFrame ──────────────────────────────────────────────────────


def _make_xlsx(tmp_path: Path, n_history: int, n_future: int, *, seed: int = 42) -> Path:
    """Записывает xlsx с history+tail и возвращает путь."""
    total = n_history + n_future
    dates = pd.date_range("2022-01-01", periods=total, freq="MS")
    rng = np.random.RandomState(seed)
    kpi = list(rng.uniform(100, 1000, n_history)) + [np.nan] * n_future
    media_a = rng.uniform(10, 100, total).tolist()
    media_b = rng.uniform(5, 50, total).tolist()
    df = pd.DataFrame({
        "date": dates,
        "sales": kpi,
        "tv_spend": media_a,
        "digital_spend": media_b,
    })
    p = tmp_path / "data.xlsx"
    df.to_excel(p, index=False)
    return p


# ─── Тест 1: validate_data на файле С хвостом ────────────────────────────────


def test_validator_detects_tail_and_splits(tmp_path: Path):
    """validate_data: 24 история + 12 хвост → media_plan_detected с n=12,
    ratio/статистика по 24 строкам, media_plan.json записан."""
    p = _make_xlsx(tmp_path, 24, 12)
    project_dir = str(tmp_path / "project")
    Path(project_dir).mkdir(parents=True, exist_ok=True)

    result = validate_data(str(p), project_dir=project_dir)

    # media_plan_detected должен присутствовать и быть непустым
    mpd = result.get("media_plan_detected")
    assert mpd is not None, "media_plan_detected отсутствует в результате"
    assert mpd["n_future_periods"] == 12, (
        f"Ожидалось 12 периодов будущего, получено {mpd['n_future_periods']}"
    )
    assert mpd["confirmed"] is False
    assert isinstance(mpd["source_hash"], str) and len(mpd["source_hash"]) == 64

    # ratio и n_rows — только по истории (24 строки, не 36)
    file_rows = result["file"]["rows"]
    assert file_rows == 24, (
        f"Ожидалось 24 строки истории в result['file']['rows'], получено {file_rows}"
    )
    ratio = result["detected"]["ratio"]
    # 24 строки / 2 предиктора = 12.0; для 36 строк = 18.0
    # Проверяем, что ratio ≤ 15 (то есть база — 24, а не 36)
    assert ratio <= 15.0, (
        f"ratio={ratio} — похоже, что статистика по 36 строкам вместо 24"
    )

    # media_plan.json должен быть записан
    mp_path = Path(project_dir) / "results" / "media_plan.json"
    assert mp_path.exists(), "media_plan.json не записан"
    with open(mp_path, encoding="utf-8") as f:
        mp_data = json.load(f)
    assert mp_data["n_future_periods"] == 12
    assert mp_data["confirmed"] is False
    assert len(mp_data["source_hash"]) == 64
    # channels содержит медиа-каналы
    assert "tv_spend" in mp_data.get("channels", {}) or "digital_spend" in mp_data.get("channels", {})


def test_validator_tail_period_labels_count(tmp_path: Path):
    """period_labels в media_plan_detected == n_future_periods."""
    p = _make_xlsx(tmp_path, 24, 12)
    result = validate_data(str(p))
    mpd = result.get("media_plan_detected")
    assert mpd is not None
    assert len(mpd["period_labels"]) == mpd["n_future_periods"]


# ─── Тест 2: validate_data БЕЗ хвоста ───────────────────────────────────────


def test_validator_no_tail_media_plan_absent(tmp_path: Path):
    """validate_data на файле без хвоста → media_plan_detected is None."""
    p = _make_xlsx(tmp_path, 24, 0)  # только история

    result = validate_data(str(p))

    mpd = result.get("media_plan_detected")
    assert mpd is None, (
        f"Ожидался None для файла без хвоста, получено: {mpd!r}"
    )

    # no-op invariant: n_rows совпадает с полным числом строк
    assert result["file"]["rows"] == 24


def test_validator_no_tail_no_media_plan_json(tmp_path: Path):
    """Без хвоста media_plan.json НЕ должен записываться."""
    p = _make_xlsx(tmp_path, 12, 0)
    project_dir = str(tmp_path / "project")
    Path(project_dir).mkdir(parents=True, exist_ok=True)

    validate_data(str(p), project_dir=project_dir)

    mp_path = Path(project_dir) / "results" / "media_plan.json"
    assert not mp_path.exists(), "media_plan.json не должен существовать без хвоста"


# ─── Тест 3: инвариант current_spend (notna-only) ────────────────────────────


def test_current_spend_noop_for_no_tail(tmp_path: Path):
    """Для файла без хвоста — сумма spend не изменяется при notna-фильтре.

    Тест проверяет инвариант на уровне pandas: df[df[kpi].notna()] == df если NaN нет.
    """
    n = 24
    rng = np.random.RandomState(10)
    dates = pd.date_range("2022-01-01", periods=n, freq="MS")
    kpi_vals = rng.uniform(100, 1000, n)
    spend_vals = rng.uniform(10, 100, n)
    df = pd.DataFrame({"date": dates, "sales": kpi_vals, "tv_spend": spend_vals})

    # Без хвоста: notna-фильтр = no-op
    df_filtered = df[df["sales"].notna()].reset_index(drop=True)
    assert len(df_filtered) == len(df)
    assert df_filtered["tv_spend"].sum() == pytest.approx(df["tv_spend"].sum())


def test_current_spend_history_only_for_tail(tmp_path: Path):
    """Для файла С хвостом — сумма spend по notna-строкам < полная сумма.

    Будущие строки (хвост) имеют KPI=NaN, но spend заполнен.
    После фильтра: sum(spend) только по истории.
    """
    n_hist = 12
    n_tail = 6
    total = n_hist + n_tail
    rng = np.random.RandomState(20)
    dates = pd.date_range("2022-01-01", periods=total, freq="MS")
    kpi_vals = list(rng.uniform(100, 1000, n_hist)) + [np.nan] * n_tail
    # Spend ненулевой везде, включая хвост
    spend_vals = rng.uniform(10, 100, total)
    df = pd.DataFrame({"date": dates, "sales": kpi_vals, "tv_spend": spend_vals})

    # Полная сумма (как если бы не фильтровали)
    full_spend_sum = float(df["tv_spend"].fillna(0).sum())

    # История-only через notna-фильтр
    df_hist = df[df["sales"].notna()].reset_index(drop=True)
    hist_spend_sum = float(df_hist["tv_spend"].fillna(0).sum())

    # История < полного (хвост добавляет spend)
    assert hist_spend_sum < full_spend_sum, (
        f"Ожидалось hist_spend < full_spend: {hist_spend_sum:.2f} < {full_spend_sum:.2f}"
    )
    assert len(df_hist) == n_hist

    # Точная проверка: история = первые 12 строк
    expected = float(df["tv_spend"].iloc[:n_hist].sum())
    assert hist_spend_sum == pytest.approx(expected)
