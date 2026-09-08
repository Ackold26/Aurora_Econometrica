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


def test_validator_no_tail_writes_zero_media_plan_json(tmp_path: Path):
    """Без хвоста media_plan.json пишется с честным `n_future_periods: 0`.

    🔴 Договор изменён 2026-09-08 (аудит, находка High-2). Прежде файл писался
    ТОЛЬКО при найденном хвосте, и этот тест сторожил его отсутствие. Цена
    оказалась велика: в одном каталоге проекта файл прошлого, планового импорта
    переживал новый, базовый, и признак `media_plan_absent` уверенно отвечал
    «план есть» на данных, где плана нет. Источник признака оставляем один
    (этот файл, его же читает интерфейс) — значит он обязан описывать ТЕКУЩИЕ
    данные, а не последние, где хвост нашёлся. Удалять файл нельзя (правило
    проекта: только в корзину), поэтому перезаписываем честным нулём.
    """
    import json

    p = _make_xlsx(tmp_path, 12, 0)
    project_dir = str(tmp_path / "project")
    Path(project_dir).mkdir(parents=True, exist_ok=True)

    validate_data(str(p), project_dir=project_dir)

    mp_path = Path(project_dir) / "results" / "media_plan.json"
    assert mp_path.exists(), "media_plan.json обязан описывать текущие данные"
    payload = json.loads(mp_path.read_text(encoding="utf-8"))
    assert payload["n_future_periods"] == 0, payload
    assert payload["channels"] == [], payload


def test_validator_overwrites_stale_media_plan_json(tmp_path: Path):
    """Тот же каталог проекта: сначала данные с хвостом, потом без него.

    Сценарий находки High-2 целиком: пока файл не обнулялся, второй импорт
    оставлял продукт с признаком «план есть» на данных без будущих периодов.
    """
    import json

    project_dir = str(tmp_path / "project")
    Path(project_dir).mkdir(parents=True, exist_ok=True)
    mp_path = Path(project_dir) / "results" / "media_plan.json"

    (tmp_path / "a").mkdir(parents=True, exist_ok=True)
    (tmp_path / "b").mkdir(parents=True, exist_ok=True)

    with_tail = _make_xlsx(tmp_path / "a", 24, 12)
    validate_data(str(with_tail), project_dir=project_dir)
    assert json.loads(mp_path.read_text(encoding="utf-8"))["n_future_periods"] == 12

    no_tail = _make_xlsx(tmp_path / "b", 24, 0)
    validate_data(str(no_tail), project_dir=project_dir)
    assert json.loads(mp_path.read_text(encoding="utf-8"))["n_future_periods"] == 0, (
        "media_plan.json остался от прошлого импорта — признак наличия плана врёт"
    )


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


# ─── Тест 4: ранние выходы validate_data (аудит Medium-1, 2026-09-08) ────────


def _seed_stale_media_plan(project_dir: Path) -> Path:
    """Кладёт в каталог проекта media_plan.json от ПРОШЛОГО, планового импорта."""
    results = project_dir / "results"
    results.mkdir(parents=True, exist_ok=True)
    mp_path = results / "media_plan.json"
    mp_path.write_text(
        json.dumps({
            "n_future_periods": 3,
            "period_labels": ["2026-10", "2026-11", "2026-12"],
            "granularity": "month",
            "future_dates": [],
            "channels": ["tv_spend"],
            "warnings": [],
            "source_hash": "STALEHASH",
            "confirmed": True,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return mp_path


def _make_early_exit_file(tmp_path: Path, kind: str) -> str:
    """Готовит вход, на котором validate_data выходит РАНО, не прочитав данные."""
    if kind == "missing":
        return str(tmp_path / "нет_такого_файла_12345.xlsx")
    if kind == "bad_ext":
        p = tmp_path / "заметка.txt"
        p.write_text("это не таблица", encoding="utf-8")
        return str(p)
    if kind == "broken_xlsx":
        p = tmp_path / "битый.xlsx"
        p.write_bytes(b"not an xlsx at all")
        return str(p)
    if kind == "empty_csv":
        p = tmp_path / "пустой.csv"
        p.write_text("", encoding="utf-8")
        return str(p)
    if kind == "empty_xlsx":
        # Единственный вход, доходящий до ветки `n_cols == 0`: пустой .csv
        # pandas отбивает раньше (EmptyDataError), а пустой лист xlsx читается
        # в DataFrame формы (0, 0). Без него четвёртый ранний выход не покрыт.
        import openpyxl

        p = tmp_path / "пустой_лист.xlsx"
        openpyxl.Workbook().save(p)
        return str(p)
    raise AssertionError(f"неизвестный вид входа: {kind}")


@pytest.mark.parametrize(
    "kind, expected_message_prefix",
    [
        ("missing", "Файл не найден:"),
        ("bad_ext", "Неподдерживаемый формат:"),
        ("broken_xlsx", "Ошибка чтения файла:"),
        ("empty_csv", "Ошибка чтения файла:"),
        ("empty_xlsx", "Файл пуст"),
    ],
)
def test_validator_early_exit_writes_unknown_media_plan(
    tmp_path: Path, kind: str, expected_message_prefix: str
):
    """На ранних выходах media_plan.json обязан стать «определить не удалось».

    🔴 Аудит Medium-1 (2026-09-08). Договор «файл описывает ТЕКУЩИЕ данные»
    держался только на успешном пути. У validate_data четыре ранних выхода
    (файла нет / чужое расширение / ошибка чтения / файл пуст), и на них файл
    прошлого импорта переживал новую проверку: у проекта с медиапланом на 3
    периода пользователь выбирал нечитаемый файл, проверка падала — а признак
    `media_plan_absent` продолжал уверенно отвечать «план есть».

    Пишем именно третье состояние (`n_future_periods: null`), а не ноль:
    данные не прочитаны, про хвост НИЧЕГО не известно. «Плана нет» было бы
    утверждением, которого мы не проверяли.
    """
    from engines.optimizer import media_plan_absent

    project_dir = tmp_path / "project"
    mp_path = _seed_stale_media_plan(project_dir)
    assert media_plan_absent(str(project_dir)) is False, "подготовка: план должен «быть»"

    file_path = _make_early_exit_file(tmp_path, kind)
    result = validate_data(file_path, project_dir=str(project_dir))

    # Текст отказа пользователю не меняется — правка только про состояние на диске.
    assert result["status"] == "error", result
    assert result["message"].startswith(expected_message_prefix), result["message"]

    payload = json.loads(mp_path.read_text(encoding="utf-8"))
    assert payload["n_future_periods"] is None, (
        f"media_plan.json пережил ранний выход ({kind}) и врёт про наличие плана: {payload}"
    )
    assert payload["detection"] == "unavailable", payload
    assert payload["confirmed"] is False, payload

    assert media_plan_absent(str(project_dir)) is None, (
        "признак обязан вернуть «определить не удалось», а не True/False"
    )


@pytest.mark.parametrize(
    "kind", ["missing", "bad_ext", "broken_xlsx", "empty_csv", "empty_xlsx"]
)
def test_validator_early_exit_without_project_dir_does_not_crash(tmp_path: Path, kind: str):
    """`project_dir` необязателен: писать некуда — выходим как раньше, без падения."""
    file_path = _make_early_exit_file(tmp_path, kind)

    result = validate_data(file_path)
    assert result["status"] == "error", result
    assert result["message"], "пользователь обязан получить понятный отказ"
